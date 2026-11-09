"""pytest 公共夹具（C 负责的接口注册中心测试使用）。

说明：
- 使用异步 SQLite 引擎，建表覆盖 A 的公共 Base 与 C 的扩展 metadata；
- 仓库根目录加入 sys.path，便于测试 ``cli`` 包；
- 不修改 A/B 的测试文件，夹具只提供新增能力。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FIXTURES = Path(__file__).parent / "fixtures"

# 原有集成测试使用 actor_id 兼容模式；新的身份测试会单独开启鉴权
os.environ.setdefault("TEAMCODE_REQUIRE_AUTH", "0")
# 集成测试默认使用 MockAdapter，避免启动真实外部 Agent
os.environ.setdefault("TEAMCODE_AGENT", "mock")


@pytest.fixture()
def sample_project(tmp_path: Path) -> Path:
    """复制一份样例项目，避免测试修改原始夹具。"""
    destination = tmp_path / "shop"
    # 保留 sample_pkg 这一层，模块名才是 sample_pkg.user_service
    shutil.copytree(FIXTURES / "sample_pkg", destination / "sample_pkg")
    # 语法错误样例在运行时生成：既保证夹具可测降级，又不让 ruff 扫描坏文件
    (destination / "sample_pkg" / "broken.py").write_text(
        '"""故意包含语法错误的文件，扫描时应被跳过并记录 warning。"""\n\n\n'
        "def broken(:\n    pass\n",
        encoding="utf-8",
    )
    return destination


@pytest.fixture()
async def engine(tmp_path: Path):
    from app.integration.models import IntegrationBase
    from app.interface_registry.models import InterfaceRegistryBase
    from app.models import Base

    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(InterfaceRegistryBase.metadata.create_all)
        await connection.run_sync(IntegrationBase.metadata.create_all)
    try:
        yield test_engine
    finally:
        await test_engine.dispose()


@pytest.fixture()
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture()
async def session(session_factory):
    async with session_factory() as db_session:
        yield db_session


@pytest.fixture()
async def project(session, sample_project: Path):
    from app.models.project import Project
    from app.models.user import User

    session.add(
        User(id="u1", name="Owner", email="owner@example.invalid")
    )
    session.add(
        Project(
            id="p_test",
            name="测试项目",
            owner_id="u1",
            repo_path=str(sample_project),
        )
    )
    await session.commit()
    return "p_test"


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """一个真实的 Git 仓库，供 Agent Worktree 测试使用。"""
    import subprocess

    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "sample_pkg", repo / "sample_pkg")
    (repo / "README.md").write_text("demo\n", encoding="utf-8")
    git_identity = (
        "-c",
        "user.name=TeamCode Test",
        "-c",
        "user.email=test@example.invalid",
    )
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", *git_identity, "-C", str(repo), "add", "."],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", *git_identity, "-C", str(repo), "commit", "-m", "init"],
        check=True,
        capture_output=True,
        text=True,
    )
    return repo


@pytest.fixture()
async def client(engine, project, session_factory):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.db import get_session
    from app.integration.api import router as integration_router
    from app.integration.service import shutdown_runtimes
    from app.interface_registry.api import router as interface_router
    from app.interface_registry.watcher import watcher_manager

    test_app = FastAPI()
    test_app.include_router(integration_router)
    test_app.include_router(interface_router)

    async def override_session():
        async with session_factory() as db_session:
            yield db_session

    test_app.dependency_overrides[get_session] = override_session

    transport = ASGITransport(app=test_app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http
    finally:
        await shutdown_runtimes()
        watcher_manager.stop_all()
