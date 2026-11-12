"""C-2 验收测试：文件监听防抖、忽略目录与 interface.updated 推送。"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.interface_registry import watcher as watcher_module
from app.interface_registry.watcher import InterfaceWatcher, WatcherManager


def test_atomic_save_move_notifies_python_destination(tmp_path: Path, monkeypatch):
    watcher = InterfaceWatcher(project_id="p_test", root=tmp_path)
    notified = []
    monkeypatch.setattr(watcher, "notify", notified.append)
    handler = watcher_module._PythonChangeHandler(watcher)
    target = tmp_path / "api.py"
    handler.on_moved(
        SimpleNamespace(
            is_directory=False, src_path=str(tmp_path / "api.py.tmp"), dest_path=str(target)
        )
    )
    assert target in notified


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_watcher_debounce_merges_notifications(tmp_path: Path):
    calls: list[list[str]] = []
    watcher = InterfaceWatcher(
        project_id="p_test",
        root=tmp_path,
        trigger=lambda _project_id, pending: calls.append(pending),
        debounce_seconds=0.05,
    )

    target = tmp_path / "module.py"
    target.write_text("def f():\n    pass\n", encoding="utf-8")

    watcher.notify(target)
    watcher.notify(target)

    assert _wait_until(lambda: bool(calls))
    # 连续两次通知应被防抖合并为一次触发
    assert len(calls) == 1
    assert calls[0] == [str(target)]


def test_watcher_ignores_runtime_directories(tmp_path: Path):
    watcher = InterfaceWatcher(
        project_id="p_test",
        root=tmp_path,
        trigger=lambda _project_id, _pending: None,
    )

    ignored = tmp_path / ".teamcode" / "cache" / "x.py"
    ignored.parent.mkdir(parents=True, exist_ok=True)
    ignored.write_text("def f():\n    pass\n", encoding="utf-8")

    watcher.notify(ignored)
    # 忽略路径不会进入待处理集合
    assert watcher._pending == set()


def test_watcher_degrades_without_watchdog(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(watcher_module, "WATCHDOG_AVAILABLE", False)

    watcher = InterfaceWatcher(
        project_id="p_test",
        root=tmp_path,
        trigger=lambda _project_id, _pending: None,
    )
    watcher.start()
    assert watcher.degraded is True
    assert "watchdog" in (watcher.degradation_reason or "")

    manager = WatcherManager(publish=lambda event: None)
    assert manager.start("p_test", tmp_path, None) is None
    status = manager.status()
    assert status["degraded"] is True
    assert any("watchdog" in reason for reason in status["reasons"])


@pytest.mark.skipif(not watcher_module.WATCHDOG_AVAILABLE, reason="watchdog 未安装")
async def test_watcher_schedules_scan_on_main_loop(session_factory, sample_project: Path):
    received: list[dict] = []
    manager = WatcherManager(publish=received.append)
    watcher = manager.start("p_test", sample_project, session_factory)
    assert watcher is not None

    target = sample_project / "sample_pkg" / "user_service.py"
    target.write_text(
        target.read_text(encoding="utf-8")
        + '\n\ndef added_by_watcher() -> None:\n    """监听触发的新函数。"""\n    pass\n',
        encoding="utf-8",
    )
    watcher.notify(target)

    deadline = asyncio.get_running_loop().time() + 5
    while not received and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)

    try:
        assert received, "等待超时：没有收到 interface.updated 事件"
        event = received[0]
        assert event["type"] == "interface.updated"
        assert event["project_id"] == "p_test"
        assert event["payload"]["added"]

        assert watcher.last_summary is not None
        assert "sample_pkg/user_service.py" in watcher.last_summary.scanned_files
    finally:
        manager.stop_all()


@pytest.mark.skipif(not watcher_module.WATCHDOG_AVAILABLE, reason="watchdog 未安装")
async def test_watcher_publish_failure_does_not_break_scan(
    session_factory, sample_project: Path, caplog
):
    """事件发布失败只记录日志，扫描结果仍然落库并保留。"""

    def bad_publish(_event: dict) -> None:
        raise RuntimeError("publish boom")

    manager = WatcherManager(publish=bad_publish)
    watcher = manager.start("p_test", sample_project, session_factory)
    assert watcher is not None

    target = sample_project / "sample_pkg" / "user_service.py"
    target.write_text(
        target.read_text(encoding="utf-8")
        + '\n\ndef publish_failure_probe() -> None:\n    """发布失败探针。"""\n    pass\n',
        encoding="utf-8",
    )

    loop = asyncio.get_running_loop()
    try:
        with caplog.at_level(logging.ERROR, logger="app.interface_registry.watcher"):
            watcher.notify(target)
            deadline = loop.time() + 5
            while watcher.last_summary is None and loop.time() < deadline:
                await asyncio.sleep(0.02)

        assert watcher.last_summary is not None
        assert watcher.last_summary.has_changes
        assert "interface.updated 发布失败" in caplog.text
    finally:
        manager.stop_all()
