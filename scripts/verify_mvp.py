"""临时数据 + 真 HTTP/WS + CLI/MCP；不调用外部模型或真实收费 Coding Agent。"""

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
results = []


def check(name, condition):
    results.append({"name": name, "passed": bool(condition)})
    print(f"[{'PASS' if condition else 'FAIL'}] {name}", flush=True)
    if not condition:
        raise AssertionError(name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="teamcode-mvp-") as temporary:
        data = Path(temporary).resolve()
        assert data.parent == Path(tempfile.gettempdir()).resolve()
        env = {
            **os.environ,
            "PYTHONUTF8": "1",
            "TEAMCODE_MOCK_DELAY": "0.02",
            "TEAMCODE_LLM_AUTO": "0",
        }
        # 验证独立于使用者的模型和数据库配置。
        for key in (
            "DATABASE_URL",
            "TEAMCODE_LLM_BASE_URL",
            "TEAMCODE_LLM_API_KEY",
            "TEAMCODE_LLM_MODEL",
        ):
            env[key] = ""
        env["DATABASE_URL"] = f"sqlite+aiosqlite:///{data / 'mvp.db'}"
        log = (data / "server.log").open("w", encoding="utf-8")
        process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "scripts/run_mvp.py"),
                "--port",
                str(port),
                "--data-dir",
                str(data),
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=log,
        )
        try:

            def http(path, token="", body=None, text=False):
                request = Request(
                    base + path,
                    method="POST" if body is not None else "GET",
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={
                        "Authorization": "Bearer " + token,
                        "Content-Type": "application/json",
                    },
                )
                with urlopen(request, timeout=40) as response:
                    value = response.read().decode("utf-8")
                    return value if text else json.loads(value)

            for _ in range(100):
                try:
                    http("/health")
                    break
                except (URLError, OSError):
                    if process.poll() is not None:
                        raise RuntimeError("MVP 服务启动失败")
                    time.sleep(0.1)
            check("health contract", http("/health") == {"status": "ok"})
            check("built React workbench", "课堂 MVP" in http("/", text=True))
            identities = http("/api/demo")["members"]
            token = identities[0]["token"]
            check("three classroom identities", len(identities) == 3)
            try:
                http("/api/projects/p_demo/tasks")
                denied = False
            except HTTPError as exc:
                denied = exc.code == 401
            check("unauthenticated requests rejected", denied)
            tasks = http("/api/projects/p_demo/tasks", token)["tasks"]
            check("A planning produces three tasks", len(tasks) == 3)
            listing = http("/api/projects/p_demo/interfaces", token)["interfaces"]
            order = next(i for i in listing if i["name"] == "create_order")
            check("AST call dependencies", len(order["dependencies"]) == 2)
            markdown = http(
                "/api/projects/p_demo/interfaces?format=markdown", token, text=True
            )
            check(
                "documentation includes history and dependencies",
                "版本历史" in markdown and "get_product" in markdown,
            )
            task = tasks[0]
            task_path = f"/api/tasks/{task['task_id']}"
            http(task_path + "/run", token, {"agent_name": "mock"})
            for _ in range(100):
                status = http(task_path + "/status", token)
                if status["status"] in {"succeeded", "failed"}:
                    break
                time.sleep(0.05)
            check(
                "B runtime uses isolated worktree",
                status["status"] == "succeeded" and ".teamcode" in status["workspace"],
            )
            check(
                "persisted agent logs", bool(http(task_path + "/logs", token)["logs"])
            )
            check(
                "real file diff",
                bool(http(task_path + "/changes", token)["changes"][0]["diff"]),
            )
            actual_tests = http(task_path + "/tests", token, {})
            check(
                "actual project pytest",
                actual_tests["status"] == "passed"
                and "4 passed" in actual_tests["output"],
            )
            http(task_path + "/commit", token, {})
            merged = http(
                f"/api/projects/p_demo/tasks/{task['task_id']}/merge", token, {}
            )
            check("commit then review and merge", merged["merged"])
            change = http(
                "/api/projects/p_demo/requirements",
                token,
                {
                    "requirements": "在线商城：用户管理、商品管理、订单管理，新增优惠券功能，订单支持优惠券抵扣",
                    "mode": "replan",
                },
            )
            after = http("/api/projects/p_demo/tasks", token)["tasks"]
            check(
                "coupon replanning preserves unaffected status",
                change["version"] == 2
                and next(t for t in after if t["task_id"] == task["task_id"])["status"]
                == "completed",
            )

            async def watch():
                import websockets

                async with websockets.connect(
                    base.replace("http", "ws") + "/ws/projects/p_demo?token=" + token
                ) as ws:
                    path = data / "shop/backend/app/modules/user/service.py"
                    path.write_text(
                        path.read_text(encoding="utf-8")
                        + "\n\ndef watched_example(flag: bool = True) -> bool:\n    return flag\n",
                        encoding="utf-8",
                    )
                    while True:
                        event = json.loads(await asyncio.wait_for(ws.recv(), 5))
                        if event.get("type") == "interface.updated":
                            return event

            check(
                "automatic filesystem to WebSocket update",
                asyncio.run(watch())["type"] == "interface.updated",
            )
            listing = http("/api/projects/p_demo/interfaces", token)["interfaces"]
            watched = next(i for i in listing if i["name"] == "watched_example")
            check("automatically refreshed interface", watched["version"] == 1)
            exported = data / "interfaces.md"
            cli = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "cli.teamcode",
                    "pull-interfaces",
                    "--project",
                    "p_demo",
                    "--api-base",
                    base,
                    "--api-key",
                    token,
                    "--output",
                    str(exported),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                check=False,
            )
            check(
                "CLI uses live authenticated REST",
                cli.returncode == 0
                and "watched_example" in exported.read_text(encoding="utf-8"),
            )
            mcp_env = {**env, "TEAMCODE_API_BASE": base, "TEAMCODE_TOKEN": token}
            message = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "get_interface",
                    "arguments": {"interface_id": watched["interface_id"]},
                },
            }
            mcp = subprocess.run(
                [sys.executable, "-m", "cli.mcp_server"],
                cwd=ROOT,
                env=mcp_env,
                input=json.dumps(message) + "\n",
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
                timeout=20,
            )
            check(
                "MCP returns live interface history",
                "history" in json.loads(mcp.stdout)["result"]["content"][0]["text"],
            )
            check(
                "shared health contract remains intact",
                http("/health") == {"status": "ok"},
            )
        finally:
            process.terminate()
            process.wait(timeout=10)
            log.close()
    report = {
        "passed": sum(r["passed"] for r in results),
        "checks": results,
        "mode": "real local services; MockAdapter; no external model",
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"Result: {report['passed']}/{len(results)} passed")


if __name__ == "__main__":
    main()
