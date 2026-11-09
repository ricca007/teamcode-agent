"""C-3（第二阶段，可选）：最小 MCP stdio server。

让成员的 Coding Agent 在会话中直接查询接口，而不必先落盘文档。

实现说明：
- 只实现 MCP 最常用的 initialize / tools/list / tools/call；
- 使用换行分隔的 JSON-RPC 2.0，stdout 只输出协议消息，日志走 stderr；
- 复用 ``InterfaceRegistryService``，不重复实现提取逻辑；
- 通过 ``--db-url`` 指定数据库，默认读取 DATABASE_URL。

启动示例（在 MCP 客户端配置中）：
    python -m cli.mcp_server --db-url sqlite+aiosqlite:///./teamcode.db
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any

from app.config import get_settings
from app.interface_registry.service import InterfaceRegistryService
from app.models.project import Project
from cli.logging_setup import configure_cli_logging
from cli.teamcode import (
    DEFAULT_FALLBACK_DATABASE_URL,
    _backend_name,
    _connect_engine,
    mask_url,
)

logger = logging.getLogger("teamcode.mcp")

PROTOCOL_VERSION = "2024-11-05"

_DB_URL: str | None = None
_FALLBACK_DB_URL: str | None = None

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_interfaces",
        "description": "列出项目已注册的接口；format=markdown 时返回可直接阅读的文档。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目 ID"},
                "format": {
                    "type": "string",
                    "enum": ["markdown", "json"],
                    "default": "markdown",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "get_interface",
        "description": "按名称（可按模块过滤）查询单个接口的签名与说明。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "name": {
                    "type": "string",
                    "description": "接口名称，支持限定名，如 UserService.get_user",
                },
                "module": {"type": "string", "description": "可选，模块名过滤"},
            },
            "required": ["project_id", "name"],
        },
    },
]


def configure(db_url: str | None = None, fallback_db_url: str | None = None) -> None:
    """测试和 main() 共用的数据库配置入口。"""
    global _DB_URL, _FALLBACK_DB_URL
    _DB_URL = db_url
    _FALLBACK_DB_URL = fallback_db_url


async def _open_engine():
    requested = _DB_URL or get_settings().database_url
    fallback = (
        _FALLBACK_DB_URL
        or os.getenv("FALLBACK_DATABASE_URL")
        or DEFAULT_FALLBACK_DATABASE_URL
    )
    try:
        return await _connect_engine(requested)
    except Exception as exc:
        if _backend_name(requested) == "sqlite" or requested == fallback:
            raise
        # stdout 只能输出协议消息，降级信息统一走 stderr
        logger.warning(
            "降级提示：%s 不可用（%s: %s）；当前使用 %s",
            _backend_name(requested),
            type(exc).__name__,
            exc,
            mask_url(fallback),
        )
        return await _connect_engine(fallback)


async def _list_interfaces_async(args: dict[str, Any]) -> str:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = await _open_engine()
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            service = InterfaceRegistryService(session)
            project_id = args["project_id"]
            project = await session.get(Project, project_id)
            interfaces = await service.list_interfaces(project_id)
            if project is None and not interfaces:
                raise ValueError(f"项目不存在：{project_id}")

            if args.get("format", "markdown") == "json":
                payload = [i.model_dump(mode="json") for i in interfaces]
                return json.dumps(payload, ensure_ascii=False, indent=2)
            return await service.render_markdown(project_id)
    finally:
        await engine.dispose()


async def _get_interface_async(args: dict[str, Any]) -> str:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = await _open_engine()
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            service = InterfaceRegistryService(session)
            project_id = args["project_id"]
            name = args["name"]
            module = args.get("module")
            for info in await service.list_interfaces(project_id):
                if info.name != name and info.name.split(".")[-1] != name:
                    continue
                if module and info.module != module:
                    continue
                return json.dumps(
                    info.model_dump(mode="json"), ensure_ascii=False, indent=2
                )
            raise ValueError(f"未找到接口：{name}")
    finally:
        await engine.dispose()


def _tool_list_interfaces(args: dict[str, Any]) -> str:
    return asyncio.run(_list_interfaces_async(args))


def _tool_get_interface(args: dict[str, Any]) -> str:
    return asyncio.run(_get_interface_async(args))


TOOL_HANDLERS = {
    "list_interfaces": _tool_list_interfaces,
    "get_interface": _tool_get_interface,
}


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """处理单条 JSON-RPC 消息；通知类消息返回 None。"""
    method = message.get("method")
    request_id = message.get("id")

    if request_id is None:
        # notifications/initialized 等通知不需要响应
        return None

    if method == "initialize":
        return _ok(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "teamcode-interface-registry", "version": "0.1.0"},
            },
        )

    if method == "tools/list":
        return _ok(request_id, {"tools": TOOLS})

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            logger.warning("MCP 调用未知工具: %s", name)
            return _error(request_id, -32602, f"未知工具：{name}")
        try:
            text = handler(arguments)
        except Exception as exc:  # 工具异常转成 JSON-RPC 错误
            logger.exception("MCP 工具执行失败: tool=%s args=%s", name, arguments)
            return _error(request_id, -32000, str(exc))
        return _ok(
            request_id,
            {"content": [{"type": "text", "text": text}], "isError": False},
        )

    logger.warning("MCP 收到未知方法: %s", method)
    return _error(request_id, -32601, f"不支持的方法：{method}")


def _ok(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def main(argv: list[str] | None = None) -> int:
    configure_cli_logging()
    parser = argparse.ArgumentParser(description="TeamCode 接口注册中心 MCP server（stdio）")
    parser.add_argument("--db-url", default=None, help="数据库连接串")
    parser.add_argument(
        "--fallback-db-url",
        default=None,
        help="数据库不可用时回退到的连接串（默认读取 FALLBACK_DATABASE_URL）",
    )
    args = parser.parse_args(argv)

    configure(args.db_url, args.fallback_db_url)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response = _error(None, -32700, "JSON 解析失败")
        else:
            response = handle_message(message)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
