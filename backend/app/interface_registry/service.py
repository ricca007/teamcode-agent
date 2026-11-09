"""C-2：接口注册中心 service（异步版，适配 A 的 async SQLAlchemy 骨架）。

核心职责：
1. 扫描代码 -> 与数据库比对 -> 接口新增/更新/删除；
2. 接口内容变化时 version + 1，并写入 ``interface_versions`` 快照；
3. 输出 Markdown / JSON 两种对外形式。

适配说明：
- 公共表 ``interface_contracts`` 来自 ``app.models.interface``（A 维护）；
- C 的扩展状态与版本快照在 ``interface_registry.models`` 的独立 metadata 中；
- 本层只依赖 ``AsyncSession``，不依赖 FastAPI / WebSocket / watchdog。

并发控制：
- 进程内按「项目 + 事件循环」加 ``asyncio.Lock``，同一项目串行扫描；
- 跨进程由数据库主键（稳定哈希 ID）兜底，课程演示默认单进程。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.interface_registry.cache import HashCache
from app.interface_registry.config import interface_cache_path
from app.interface_registry.extractor import extract_project
from app.interface_registry.markdown import render_markdown
from app.interface_registry.models import InterfaceState, InterfaceVersion
from app.interface_registry.schemas import InterfaceInfo, ParamInfo
from app.models.interface import InterfaceContract

logger = logging.getLogger(__name__)


def interface_content_hash(info: InterfaceInfo) -> str:
    """接口「内容」哈希。

    刻意排除 lineno / decorators / is_async 等展示字段：代码上下移动或
    加装饰器不应被视为接口契约变更。只有签名、返回值和说明变化才升版本。
    """
    payload = {
        "module": info.module,
        "name": info.name,
        "kind": info.kind,
        "params": [p.model_dump() for p in info.params],
        "returns": info.returns,
        "docstring": info.docstring,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class ScanSummary:
    """一次扫描的变更摘要，可直接序列化给 API / WebSocket / CLI。"""

    project_id: str
    scanned_files: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    removed_files: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    total_interfaces: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.updated or self.deleted)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["has_changes"] = self.has_changes
        return data


# 进程内按「项目 + 事件循环」串行化扫描。
# 之所以带上 loop：asyncio.Lock 在 3.10+ 会绑定首次使用的事件循环，
# 测试会为每个用例创建新循环，不能复用同一个锁对象。
_scan_locks: dict[tuple[str, int], asyncio.Lock] = {}


def _scan_lock(project_id: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    return _scan_locks.setdefault((project_id, id(loop)), asyncio.Lock())


def _repo_commit(root: Path) -> str | None:
    """记录扫描时仓库 HEAD 提交；不是 Git 仓库时返回 None。"""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            errors="replace",
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    commit = completed.stdout.strip()
    return commit or None


class InterfaceRegistryService:
    """接口注册中心。一个实例对应一个异步数据库会话。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # 扫描与版本管理
    # ------------------------------------------------------------------
    async def scan(
        self,
        project_id: str,
        project_root: str | Path,
        *,
        include_tests: bool = False,
    ) -> ScanSummary:
        """扫描项目并更新接口注册表。

        兜底策略：
        - 同一项目串行扫描（进程内锁）；
        - 跨进程并发导致的唯一键冲突（IntegrityError）自动回滚并重试一次；
        - 任何失败都记录带 project/root 上下文的日志后再向上抛，由 API /
          watcher / CLI 决定如何提示用户。
        """

        started = time.perf_counter()
        async with _scan_lock(project_id):
            for attempt in (1, 2):
                try:
                    summary = await self._scan_locked(
                        project_id, project_root, include_tests=include_tests
                    )
                except IntegrityError:
                    await self.db.rollback()
                    if attempt >= 2:
                        logger.exception(
                            "接口扫描并发冲突，重试后仍失败: project=%s root=%s",
                            project_id,
                            project_root,
                        )
                        raise
                    logger.warning(
                        "接口扫描并发冲突，回滚后重试（第 %d 次）: project=%s",
                        attempt,
                        project_id,
                    )
                    await asyncio.sleep(0.05 * attempt)
                    continue
                except Exception:
                    await self.db.rollback()
                    logger.exception(
                        "接口扫描失败: project=%s root=%s", project_id, project_root
                    )
                    raise

                elapsed_ms = (time.perf_counter() - started) * 1000
                logger.info(
                    "接口扫描完成: project=%s added=%d updated=%d deleted=%d "
                    "scanned=%d total=%d 耗时=%.1fms",
                    project_id,
                    len(summary.added),
                    len(summary.updated),
                    len(summary.deleted),
                    len(summary.scanned_files),
                    summary.total_interfaces,
                    elapsed_ms,
                )
                return summary

        raise RuntimeError("unreachable")  # pragma: no cover

    async def _scan_locked(
        self,
        project_id: str,
        project_root: str | Path,
        *,
        include_tests: bool = False,
    ) -> ScanSummary:
        root = Path(project_root).resolve()
        repo_commit = await asyncio.to_thread(_repo_commit, root)
        cache_path = root / interface_cache_path()
        cache = HashCache.load(cache_path)

        contracts = list(
            (
                await self.db.scalars(
                    select(InterfaceContract).where(
                        InterfaceContract.project_id == project_id
                    )
                )
            ).all()
        )
        states = list(
            (
                await self.db.scalars(
                    select(InterfaceState).where(
                        InterfaceState.project_id == project_id
                    )
                )
            ).all()
        )
        state_by_id = {state.interface_id: state for state in states}

        existing_by_key: dict[tuple[str, str, str], tuple[InterfaceContract, InterfaceState]] = {}
        for contract in contracts:
            state = state_by_id.get(contract.id)
            if state is None:
                # 兼容公共表里已存在、但 C 的扩展状态尚未写入的行
                state = InterfaceState(
                    interface_id=contract.id,
                    project_id=project_id,
                    content_hash="",
                    is_deleted=False,
                )
                self.db.add(state)
                state_by_id[contract.id] = state
            existing_by_key[(contract.file_path, contract.name, contract.kind)] = (
                contract,
                state,
            )

        # 数据库为空时忽略旧缓存，强制全量扫描，避免出现「有缓存无数据」
        full_scan = not contracts or cache.is_empty()
        if not contracts:
            cache = HashCache(path=cache_path)

        # AST 解析是纯 CPU 工作，放到线程池，避免阻塞事件循环
        result = await asyncio.to_thread(
            extract_project,
            root,
            project_id,
            include_tests=include_tests,
            hash_cache=cache,
        )
        cache.save()

        if result.warnings:
            skipped = ", ".join(
                warning.get("file", "?") for warning in result.warnings[:5]
            )
            logger.warning(
                "[降级] 项目 %s 有 %d 个 Python 文件解析失败，已跳过：%s",
                project_id,
                len(result.warnings),
                skipped,
            )

        summary = ScanSummary(project_id=project_id)
        summary.scanned_files = result.scanned_files
        summary.skipped_files = result.skipped_files
        summary.removed_files = result.removed_files
        summary.warnings = result.warnings

        extracted_keys: set[tuple[str, str, str]] = set()

        for info in result.interfaces:
            key = (info.file_path, info.name, info.kind)
            extracted_keys.add(key)
            content_hash = interface_content_hash(info)
            pair = existing_by_key.get(key)

            if pair is None:
                contract = InterfaceContract(
                    id=info.interface_id,
                    project_id=project_id,
                    file_path=info.file_path,
                    name=info.name,
                    kind=info.kind,
                    version=1,
                    params=[],
                    dependencies=[],
                )
                state = InterfaceState(
                    interface_id=info.interface_id,
                    project_id=project_id,
                )
                self._apply_contract(contract, info, repo_commit)
                self._apply_state(state, info, content_hash)
                self.db.add(contract)
                self.db.add(state)
                self._snapshot(contract, state, deleted=False)
                summary.added.append(contract.id)
            else:
                contract, state = pair
                if state.is_deleted or state.content_hash != content_hash:
                    # 内容变化或从删除状态恢复：版本 +1
                    contract.version += 1
                    state.is_deleted = False
                    self._apply_contract(contract, info, repo_commit)
                    self._apply_state(state, info, content_hash)
                    self._snapshot(contract, state, deleted=False)
                    summary.updated.append(contract.id)
                else:
                    # 内容未变，只同步行号等展示字段
                    self._apply_state(state, info, content_hash)

        failed_files = {warning.get("file") for warning in result.warnings}

        for key, (contract, state) in existing_by_key.items():
            if state.is_deleted or key in extracted_keys:
                continue
            file_path, _name, _kind = key
            # 解析失败的文件可能只是临时语法错误，不能误删其接口
            if file_path in failed_files:
                continue
            if full_scan:
                stale = True
            else:
                stale = (
                    file_path in summary.scanned_files
                    or file_path in summary.removed_files
                )
            if not stale:
                continue
            state.is_deleted = True
            contract.version += 1
            self._snapshot(contract, state, deleted=True)
            summary.deleted.append(contract.id)

        await self.db.commit()

        summary.total_interfaces = int(
            await self.db.scalar(
                select(func.count())
                .select_from(InterfaceState)
                .where(
                    InterfaceState.project_id == project_id,
                    InterfaceState.is_deleted.is_(False),
                )
            )
            or 0
        )
        return summary

    async def list_interfaces(self, project_id: str) -> list[InterfaceInfo]:
        contracts = list(
            (
                await self.db.scalars(
                    select(InterfaceContract).where(
                        InterfaceContract.project_id == project_id
                    )
                )
            ).all()
        )
        states = {
            state.interface_id: state
            for state in (
                await self.db.scalars(
                    select(InterfaceState).where(
                        InterfaceState.project_id == project_id
                    )
                )
            ).all()
        }

        interfaces: list[InterfaceInfo] = []
        for contract in contracts:
            state = states.get(contract.id)
            if state is None or state.is_deleted:
                continue
            interfaces.append(self._to_info(contract, state))

        return sorted(
            interfaces,
            key=lambda item: (
                item.module,
                item.lineno or 0,
                item.name,
                item.kind,
            ),
        )

    async def get_interface(self, interface_id: str) -> InterfaceInfo | None:
        contract = await self.db.get(InterfaceContract, interface_id)
        state = await self.db.get(InterfaceState, interface_id)
        if contract is None or state is None or state.is_deleted:
            return None
        return self._to_info(contract, state)

    async def list_versions(self, interface_id: str) -> list[dict]:
        rows = (
            await self.db.scalars(
                select(InterfaceVersion)
                .where(InterfaceVersion.interface_id == interface_id)
                .order_by(InterfaceVersion.version, InterfaceVersion.version_id)
            )
        ).all()
        return [
            {
                "version_id": row.version_id,
                "interface_id": row.interface_id,
                "project_id": row.project_id,
                "version": row.version,
                "content_hash": row.content_hash,
                "commit_hash": row.commit_hash,
                "snapshot": row.snapshot,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    async def render_markdown(self, project_id: str) -> str:
        return render_markdown(project_id, await self.list_interfaces(project_id))

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _apply_contract(
        contract: InterfaceContract,
        info: InterfaceInfo,
        commit_hash: str | None = None,
    ) -> None:
        contract.module = info.module
        contract.params = [param.model_dump() for param in info.params]
        contract.returns = info.returns
        contract.docstring = info.docstring
        contract.dependencies = list(info.dependencies)
        if info.commit_hash:
            contract.commit_hash = info.commit_hash
        elif commit_hash:
            contract.commit_hash = commit_hash

    @staticmethod
    def _apply_state(
        state: InterfaceState, info: InterfaceInfo, content_hash: str
    ) -> None:
        state.content_hash = content_hash
        state.lineno = info.lineno
        state.decorators = list(info.decorators)
        state.is_async = info.is_async

    def _snapshot(
        self,
        contract: InterfaceContract,
        state: InterfaceState,
        *,
        deleted: bool,
    ) -> None:
        snapshot = self._to_info(contract, state).model_dump(mode="json")
        snapshot["is_deleted"] = deleted
        self.db.add(
            InterfaceVersion(
                interface_id=contract.id,
                project_id=contract.project_id,
                version=contract.version,
                content_hash=state.content_hash,
                commit_hash=contract.commit_hash,
                snapshot=snapshot,
            )
        )

    @staticmethod
    def _to_info(
        contract: InterfaceContract, state: InterfaceState
    ) -> InterfaceInfo:
        return InterfaceInfo(
            interface_id=contract.id,
            project_id=contract.project_id,
            module=contract.module,
            file_path=contract.file_path,
            name=contract.name,
            kind=contract.kind,  # type: ignore[arg-type]
            params=[ParamInfo(**param) for param in (contract.params or [])],
            returns=contract.returns,
            docstring=contract.docstring,
            version=contract.version,
            commit_hash=contract.commit_hash,
            dependencies=list(contract.dependencies or []),
            lineno=state.lineno,
            decorators=list(state.decorators or []),
            is_async=state.is_async,
        )
