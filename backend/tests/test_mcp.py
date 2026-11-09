"""C-3 可选 MCP server 的协议处理测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


async def _prepare(project_id: str, root: Path) -> str:
    import tempfile

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.interface_registry.models import InterfaceRegistryBase
    from app.interface_registry.service import InterfaceRegistryService
    from app.models import Base
    from app.models.project import Project
    from app.models.user import User

    db_path = Path(tempfile.mkdtemp()) / "mcp.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(InterfaceRegistryBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(User(id="u1", name="Owner", email="owner@example.invalid"))
        session.add(
            Project(
                id=project_id,
                name="测试项目",
                owner_id="u1",
                repo_path=str(root),
            )
        )
        await session.commit()
        await InterfaceRegistryService(session).scan(project_id, root)
    await engine.dispose()
    return f"sqlite+aiosqlite:///{db_path}"


@pytest.fixture()
def mcp_database(sample_project: Path) -> str:
    from cli import mcp_server

    url = asyncio.run(_prepare("p_test", sample_project))
    mcp_server.configure(url)
    return url


def test_initialize_and_tools_list(mcp_database):
    from cli.mcp_server import handle_message

    init = handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )
    assert init["result"]["protocolVersion"]
    assert "tools" in init["result"]["capabilities"]

    tools = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {tool["name"] for tool in tools["result"]["tools"]}
    assert names == {"list_interfaces", "get_interface"}


def test_tool_calls_reuse_registry(mcp_database):
    from cli.mcp_server import handle_message

    listing = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "list_interfaces",
                "arguments": {"project_id": "p_test", "format": "markdown"},
            },
        }
    )
    assert "UserService.get_user" in listing["result"]["content"][0]["text"]

    detail = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "get_interface",
                "arguments": {"project_id": "p_test", "name": "get_user"},
            },
        }
    )
    assert "UserService.get_user" in detail["result"]["content"][0]["text"]


def test_unknown_method_returns_jsonrpc_error():
    from cli.mcp_server import handle_message

    response = handle_message({"jsonrpc": "2.0", "id": 9, "method": "unknown"})
    assert response["error"]["code"] == -32601
