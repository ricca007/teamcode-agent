"""C-2：基于 watchdog 的文件监听。

行为：代码变更 -> 防抖 500ms -> 在主事件循环上重新扫描（命中哈希缓存，
只解析变化文件）-> 发布 ``interface.updated`` 事件。

适配说明：
- A 的后端使用 async SQLAlchemy，异步引擎的连接池绑定事件循环；
  因此 watchdog 线程不直接访问数据库，而是通过
  ``asyncio.run_coroutine_threadsafe`` 把扫描调度回主事件循环。
- 本模块不 import FastAPI / WebSocket，只依赖注入的触发与发布回调。
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:  # watchdog 是可选能力：缺失时只降级为手动刷新
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except ImportError:  # pragma: no cover - 依赖缺失场景
    WATCHDOG_AVAILABLE = False
    FileSystemEvent = object  # type: ignore[assignment,misc]
    FileSystemEventHandler = object  # type: ignore[assignment,misc]
    Observer = None  # type: ignore[assignment]

from app.interface_registry.extractor import EXCLUDED_DIRS
from app.interface_registry.service import InterfaceRegistryService, ScanSummary
from app.realtime.events import make_event
from app.realtime.manager import bus

logger = logging.getLogger(__name__)

TriggerFn = Callable[[str, list[str]], Any]
PublishFn = Callable[[dict], None]


class _PythonChangeHandler(FileSystemEventHandler):
    def __init__(self, watcher: InterfaceWatcher):
        self._watcher = watcher

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def _handle(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        # 编辑器常把临时文件原子重命名为 .py；移动的两端都可能影响接口。
        paths = {event.src_path, getattr(event, "dest_path", "")}
        for raw_path in paths:
            path = Path(raw_path)
            if not raw_path or path.suffix != ".py":
                continue
            try:
                self._watcher.notify(path)
            except Exception:
                logger.exception("处理文件变更事件失败: %s", path)


class InterfaceWatcher:
    """单个项目的接口文件监听器。"""

    def __init__(
        self,
        *,
        project_id: str,
        root: str | Path,
        trigger: TriggerFn | None = None,
        include_tests: bool = False,
        debounce_seconds: float = 0.5,
    ):
        self.project_id = project_id
        self.root = Path(root).resolve()
        self._trigger = trigger
        self.include_tests = include_tests
        self.debounce_seconds = debounce_seconds

        self._observer: Observer | None = None
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._pending: set[str] = set()
        self.last_summary: ScanSummary | None = None

        # 降级状态：watchdog 缺失或监听启动失败时置位
        self.degraded = False
        self.degradation_reason: str | None = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self) -> InterfaceWatcher:
        if self._observer is not None or self.degraded:
            return self

        if not WATCHDOG_AVAILABLE or Observer is None:
            self.degraded = True
            self.degradation_reason = (
                "watchdog 未安装，接口变更不会自动推送，"
                "只能手动调用 POST /api/projects/{id}/interfaces/refresh"
            )
            logger.warning("[降级] %s（project=%s）", self.degradation_reason, self.project_id)
            return self

        try:
            observer = Observer()
            observer.schedule(_PythonChangeHandler(self), str(self.root), recursive=True)
            observer.start()
        except Exception as exc:  # pragma: no cover - 系统级监听失败
            self.degraded = True
            self.degradation_reason = f"启动文件监听失败：{exc}"
            logger.warning(
                "[降级] %s（project=%s）",
                self.degradation_reason,
                self.project_id,
                exc_info=True,
            )
            return self

        self._observer = observer
        logger.info("接口监听已启动: project=%s root=%s", self.project_id, self.root)
        return self

    def stop(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=3)
            except Exception:
                logger.exception("停止接口监听失败: project=%s", self.project_id)
            finally:
                self._observer = None
            logger.info("接口监听已停止: project=%s", self.project_id)

    # ------------------------------------------------------------------
    # 防抖与扫描
    # ------------------------------------------------------------------
    def notify(self, path: str | Path) -> None:
        path = Path(path)
        if self._is_ignored(path):
            return
        try:
            with self._lock:
                self._pending.add(str(path))
                if self._timer is not None:
                    self._timer.cancel()
                timer = threading.Timer(self.debounce_seconds, self._flush)
                timer.daemon = True
                self._timer = timer
                timer.start()
        except Exception:
            logger.exception("安排接口重扫失败: project=%s path=%s", self.project_id, path)

    def _is_ignored(self, path: Path) -> bool:
        try:
            rel = path.resolve().relative_to(self.root)
        except ValueError:
            return True
        return any(part in EXCLUDED_DIRS for part in rel.parts)

    def _flush(self) -> None:
        with self._lock:
            pending = sorted(self._pending)
            self._pending.clear()
            self._timer = None
        if not pending or self._trigger is None:
            return
        try:
            self._trigger(self.project_id, pending)
        except Exception:  # pragma: no cover - 监听线程必须自行兜底
            logger.exception("接口重扫调度失败: project=%s", self.project_id)


class WatcherManager:
    """按项目管理监听器，供 REST API 调用。"""

    def __init__(self, publish: PublishFn | None = None):
        self._publish = publish or bus.publish
        self._watchers: dict[str, InterfaceWatcher] = {}
        self._degraded_reasons: dict[str, str] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session_factory: Callable | None = None

    def bind(
        self,
        loop: asyncio.AbstractEventLoop,
        session_factory: Callable,
    ) -> None:
        """绑定主事件循环与异步会话工厂。"""
        self._loop = loop
        self._session_factory = session_factory

    def start(
        self,
        project_id: str,
        root: str | Path,
        session_factory: Callable | None = None,
        *,
        include_tests: bool = False,
    ) -> InterfaceWatcher | None:
        root_path = Path(root)
        if not root_path.exists():
            logger.warning("项目根目录不存在，跳过监听: %s", root_path)
            return None

        if session_factory is not None:
            self._session_factory = session_factory
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                # 同步上下文（如 CLI）无法自动取到循环；需要调用方显式 bind
                self._loop = None
                logger.warning("监听器未绑定事件循环，自动扫描会被丢弃: project=%s", project_id)

        with self._lock:
            existing = self._watchers.get(project_id)
            if existing is not None and existing.root == root_path.resolve():
                existing.include_tests = include_tests
                return existing
            if existing is not None:
                existing.stop()

            watcher = InterfaceWatcher(
                project_id=project_id,
                root=root_path,
                trigger=self._schedule_scan,
                include_tests=include_tests,
            )
            try:
                watcher.start()
            except Exception as exc:  # pragma: no cover - 监听失败不应阻断主服务
                logger.exception("启动接口监听失败: project=%s", project_id)
                self._degraded_reasons[project_id] = f"启动文件监听失败：{exc}"
                return None

            if watcher.degraded:
                self._degraded_reasons[project_id] = watcher.degradation_reason or "文件监听不可用"
                logger.warning(
                    "[降级] project=%s 文件监听不可用，后续只能手动刷新接口",
                    project_id,
                )
                return None

            self._degraded_reasons.pop(project_id, None)
            self._watchers[project_id] = watcher
            return watcher

    def _schedule_scan(self, project_id: str, pending: list[str]) -> Any:
        loop = self._loop
        session_factory = self._session_factory
        if loop is None or not loop.is_running() or session_factory is None:
            logger.warning(
                "事件循环不可用，跳过接口重扫（可手动刷新）: project=%s files=%s",
                project_id,
                pending,
            )
            return None
        try:
            return asyncio.run_coroutine_threadsafe(self._scan_and_publish(project_id), loop)
        except Exception:
            logger.exception("调度接口扫描失败: project=%s", project_id)
            return None

    async def _scan_and_publish(self, project_id: str) -> None:
        with self._lock:
            watcher = self._watchers.get(project_id)
        session_factory = self._session_factory
        if watcher is None or session_factory is None:
            return

        try:
            async with session_factory() as session:
                summary = await InterfaceRegistryService(session).scan(
                    project_id,
                    watcher.root,
                    include_tests=watcher.include_tests,
                )
        except Exception:  # pragma: no cover - 监听任务必须自行兜底
            logger.exception("接口重扫失败: project=%s", project_id)
            return

        watcher.last_summary = summary
        if not summary.has_changes:
            return

        event = make_event(
            "interface.updated",
            project_id,
            payload={
                "added": summary.added,
                "updated": summary.updated,
                "deleted": summary.deleted,
                "scanned_files": summary.scanned_files,
                "total_interfaces": summary.total_interfaces,
            },
        )
        try:
            self._publish(event)
            logger.info(
                "监听触发 interface.updated: project=%s added=%d updated=%d deleted=%d",
                project_id,
                len(summary.added),
                len(summary.updated),
                len(summary.deleted),
            )
        except Exception:
            logger.exception(
                "interface.updated 发布失败（扫描结果已落库）: project=%s",
                project_id,
            )

    def stop(self, project_id: str) -> None:
        with self._lock:
            watcher = self._watchers.pop(project_id, None)
            self._degraded_reasons.pop(project_id, None)
        if watcher is not None:
            try:
                watcher.stop()
            except Exception:
                logger.exception("停止接口监听失败: project=%s", project_id)

    def stop_all(self) -> None:
        with self._lock:
            watchers = list(self._watchers.values())
            self._watchers.clear()
            self._degraded_reasons.clear()
        for watcher in watchers:
            try:
                watcher.stop()
            except Exception:
                logger.exception("停止接口监听失败: project=%s", watcher.project_id)

    def is_running(self, project_id: str) -> bool:
        return project_id in self._watchers

    def status(self) -> dict:
        """供 /health/interfaces 展示监听能力与降级原因。"""
        with self._lock:
            watching = sorted(self._watchers)
            degraded = dict(self._degraded_reasons)

        reasons: list[str] = []
        if not WATCHDOG_AVAILABLE:
            reasons.append("watchdog 未安装，接口变更只能手动刷新")
        reasons.extend(f"{project_id}: {reason}" for project_id, reason in sorted(degraded.items()))
        return {
            "available": WATCHDOG_AVAILABLE,
            "watching": watching,
            "degraded": bool(reasons),
            "reasons": reasons,
        }


watcher_manager = WatcherManager()

# 进程退出时尽量停止监听线程，避免 pytest / CLI 挂起
atexit.register(watcher_manager.stop_all)
