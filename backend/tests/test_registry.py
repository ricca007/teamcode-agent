"""C-2 验收测试：版本递增、软删除、Markdown、并发扫描不重复入库。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.interface_registry.service import InterfaceRegistryService
from app.models.interface import InterfaceContract


async def _find(service: InterfaceRegistryService, project_id: str, name: str):
    return next(item for item in await service.list_interfaces(project_id) if item.name == name)


async def test_scan_records_git_commit(session, git_repo: Path):
    import subprocess

    service = InterfaceRegistryService(session)
    await service.scan("p_git", git_repo)

    head = subprocess.run(
        ["git", "-C", str(git_repo), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    info = next(
        item for item in await service.list_interfaces("p_git") if item.name == "normalize_name"
    )
    assert info.commit_hash == head


async def test_first_scan_registers_interfaces(session, sample_project: Path):
    service = InterfaceRegistryService(session)
    summary = await service.scan("p_test", sample_project)

    assert summary.added
    assert summary.deleted == []
    assert summary.total_interfaces > 0

    names = {item.name for item in await service.list_interfaces("p_test")}
    assert "UserService.get_user" in names
    assert "normalize_name" in names


async def test_markdown_contains_contract_and_usage_note(session, sample_project: Path):
    service = InterfaceRegistryService(session)
    await service.scan("p_test", sample_project)
    markdown = await service.render_markdown("p_test")

    assert "# TeamCode 接口文档" in markdown
    assert "唯一事实来源" in markdown
    assert "UserService.get_user" in markdown
    assert "sample_pkg/user_service.py" in markdown
    assert "async def UserService.fetch_remote" in markdown


async def test_version_increments_only_when_content_changes(session, sample_project: Path):
    service = InterfaceRegistryService(session)
    await service.scan("p_test", sample_project)

    target = await _find(service, "p_test", "normalize_name")
    assert target.version == 1

    path = sample_project / "sample_pkg" / "user_service.py"
    source = path.read_text(encoding="utf-8").replace(
        "def normalize_name(value: str, *, strip: bool = True) -> str:",
        "def normalize_name(value: str, *, strip: bool = True, upper: bool = False) -> str:",
    )
    path.write_text(source, encoding="utf-8")

    summary = await service.scan("p_test", sample_project)
    assert target.interface_id in summary.updated

    updated = await service.get_interface(target.interface_id)
    assert updated is not None
    assert updated.version == 2
    assert {param.name for param in updated.params} == {"value", "strip", "upper"}

    versions = await service.list_versions(target.interface_id)
    assert [item["version"] for item in versions] == [1, 2]

    # 内容未变时再次扫描不应升版本
    unchanged = await service.scan("p_test", sample_project)
    assert unchanged.has_changes is False
    assert (await service.get_interface(target.interface_id)).version == 2


async def test_removed_file_soft_deletes_interfaces(session, sample_project: Path):
    service = InterfaceRegistryService(session)
    await service.scan("p_test", sample_project)

    removed = await _find(service, "p_test", "UserService.get_user")
    (sample_project / "sample_pkg" / "user_service.py").unlink()

    summary = await service.scan("p_test", sample_project)
    assert summary.deleted
    assert removed.interface_id in summary.deleted
    assert await service.get_interface(removed.interface_id) is None


async def test_syntax_error_does_not_delete_existing_interfaces(session, sample_project: Path):
    service = InterfaceRegistryService(session)
    await service.scan("p_test", sample_project)
    before = await _find(service, "p_test", "UserService.get_user")
    broken_path = sample_project / "sample_pkg" / "user_service.py"
    original = broken_path.read_text(encoding="utf-8")

    broken_path.write_text("def broken(:\n    pass\n", encoding="utf-8")

    summary = await service.scan("p_test", sample_project)
    assert summary.warnings
    assert summary.deleted == []
    assert await service.get_interface(before.interface_id) is not None

    # 恢复后内容与历史版本一致，不应产生新版本
    broken_path.write_text(original, encoding="utf-8")
    restored = await service.scan("p_test", sample_project)
    assert restored.has_changes is False
    assert (await service.get_interface(before.interface_id)).version == 1


async def test_projects_are_isolated(session, sample_project: Path):
    service = InterfaceRegistryService(session)
    await service.scan("p_test", sample_project)

    assert await service.list_interfaces("another_project") == []


async def test_concurrent_scan_does_not_duplicate_rows(session_factory, sample_project: Path):
    async def run_scan():
        async with session_factory() as db_session:
            return (
                await InterfaceRegistryService(db_session).scan("p_concurrent", sample_project)
            ).total_interfaces

    totals = await asyncio.gather(run_scan(), run_scan())
    assert totals[0] == totals[1]

    async with session_factory() as db_session:
        rows = (
            await db_session.scalars(
                select(InterfaceContract).where(InterfaceContract.project_id == "p_concurrent")
            )
        ).all()

    identities = {(row.file_path, row.name, row.kind) for row in rows}
    assert len(identities) == len(rows)


async def test_integrity_conflict_rolls_back_and_retries(
    session, sample_project: Path, monkeypatch, caplog
):
    """跨进程并发冲突时自动回滚并重试一次，最终成功。"""

    original = InterfaceRegistryService._scan_locked
    calls = {"count": 0}

    async def flaky(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(InterfaceRegistryService, "_scan_locked", flaky)
    service = InterfaceRegistryService(session)

    with caplog.at_level(logging.WARNING, logger="app.interface_registry.service"):
        summary = await service.scan("p_retry", sample_project)

    assert calls["count"] == 2
    assert summary.added
    assert "重试" in caplog.text


async def test_commit_failure_does_not_cache_uncommitted_interfaces(
    session, tmp_path: Path, monkeypatch
):
    source = tmp_path / "api.py"
    source.write_text("def lookup(value: str) -> str: ...\n", encoding="utf-8")
    service = InterfaceRegistryService(session)
    await service.scan("p_retry", tmp_path)
    before = await _find(service, "p_retry", "lookup")
    source.write_text("def lookup(value: int) -> int: ...\n", encoding="utf-8")

    commit = session.commit
    attempts = 0

    async def fail_first_commit():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise IntegrityError("COMMIT", {}, Exception("temporary conflict"))
        await commit()

    monkeypatch.setattr(session, "commit", fail_first_commit)
    summary = await service.scan("p_retry", tmp_path)
    updated = await service.get_interface(before.interface_id)
    assert attempts == 2
    assert before.interface_id in summary.updated
    assert updated.returns == "int"
    assert updated.version == 2


@pytest.mark.parametrize(
    "updated_source",
    ["async def lookup(value: str) -> str: ...\n", "@cached\ndef lookup(value: str) -> str: ...\n"],
)
async def test_callable_semantics_changes_increment_version(
    session, tmp_path: Path, updated_source: str
):
    source = tmp_path / "api.py"
    source.write_text("def lookup(value: str) -> str: ...\n", encoding="utf-8")
    service = InterfaceRegistryService(session)
    await service.scan("p_semantics", tmp_path)
    before = await _find(service, "p_semantics", "lookup")

    source.write_text(updated_source, encoding="utf-8")
    summary = await service.scan("p_semantics", tmp_path)
    assert before.interface_id in summary.updated
    assert (await service.get_interface(before.interface_id)).version == 2
