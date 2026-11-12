"""精简 stdio MCP；复用同一 REST 数据和 Markdown，不维护第二套数据库逻辑。"""

import json
import sys
from urllib.parse import quote

from cli.teamcode import fetch

TOOLS = [
    {
        "name": "list_interfaces",
        "description": "拉取接口文档，含依赖和版本历史",
        "inputSchema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
            "required": ["project_id"],
        },
    },
    {
        "name": "get_interface",
        "description": "查询接口详情及完整历史",
        "inputSchema": {
            "type": "object",
            "properties": {"interface_id": {"type": "string"}},
            "required": ["interface_id"],
        },
    },
]


def handle_message(message):
    request_id = message.get("id")
    if request_id is None:
        return None
    method, params = message.get("method"), message.get("params", {})
    result = None
    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "teamcode-mvp", "version": "0.1.0"},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "ping":
            result = {}
        elif method == "tools/call":
            args = params.get("arguments", {})
            if params.get("name") == "list_interfaces":
                body = fetch(
                    f"/api/projects/{quote(args['project_id'], safe='')}/interfaces?format=markdown"
                )
            elif params.get("name") == "get_interface":
                path = f"/api/interfaces/{quote(args['interface_id'], safe='')}"
                body = json.dumps(
                    {
                        "interface": json.loads(fetch(path)),
                        "history": json.loads(fetch(path + "/versions")),
                    },
                    ensure_ascii=False,
                )
            else:
                raise ValueError("未知工具")
            result = {"content": [{"type": "text", "text": body}], "isError": False}
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": "不支持的方法"},
            }
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except (KeyError, ValueError, RuntimeError) as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": str(exc)},
        }


def main():
    for line in sys.stdin:
        try:
            result = handle_message(json.loads(line))
        except (ValueError, TypeError, AttributeError):
            result = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "无效的 JSON-RPC 消息"},
            }
        if result is not None:
            print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
