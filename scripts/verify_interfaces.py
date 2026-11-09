#!/usr/bin/env python3
"""端到端验证 C 负责的接口注册中心是否真的可用。

一条命令完成：
1. 用临时 SQLite 跑 Alembic 迁移（含 C 新增表）；
2. 启动真实的 uvicorn 后端；
3. 验证 A 的 /health 契约未被破坏；
4. 验证接口扫描、JSON / Markdown、详情、404；
5. 验证签名变化后版本递增、删除文件后软删除；
6. 验证 WebSocket 能收到 interface.updated（手动刷新 + watchdog 自动监听）；
7. 验证 ``teamcode pull-interfaces`` 在线 / 离线模式；
8. 验证 MCP server 的 get_interface 工具。

运行（仓库根目录）：

    .venv/bin/python scripts/verify_interfaces.py
    .venv/bin/python scripts/verify_interfaces.py --keep   # 保留临时目录便于排查

脚本不会写入仓库、不会访问网络（只连本机临时端口）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FIXTURE = ROOT / "experiments" / "fixtures" / "shop_app"
PROJECT_ID = "p_verify"


class Reporter:
    def __init__(self) -> None:
        self.results: list[tuple[str, str, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append(("PASS" if ok else "FAIL", name, detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        return ok

    def skip(self, name: str, detail: str = "") -> None:
        self.results.append(("SKIP", name, detail))
        print(f"[SKIP] {name}" + (f" — {detail}" if detail else ""))

    @property
    def ok(self) -> bool:
        return all(state != "FAIL" for state, _, _ in self.results)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http(
    method: str,
    url: str,
    data: dict | None = None,
    *,
    timeout: float = 10.0,
) -> tuple[int, str]:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def wait_until_ready(base_url: str, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, _ = http("GET", f"{base_url}/health", timeout=1)
            if status == 200:
                return True
        except OSError:
            pass
        time.sleep(0.2)
    return False


def prepare_database(db_path: Path, repo_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{db_path}"
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Alembic 迁移失败：\n{result.stdout}\n{result.stderr}")

    now = datetime.now(UTC).isoformat()
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "insert or replace into users"
            "(id, name, email, role, created_at, updated_at) "
            "values (?, ?, ?, ?, ?, ?)",
            ("u_verify", "Verifier", "verify@example.invalid", "member", now, now),
        )
        connection.execute(
            "insert or replace into projects"
            "(id, name, owner_id, repo_path, created_at, updated_at) "
            "values (?, ?, ?, ?, ?, ?)",
            (PROJECT_ID, "验证项目", "u_verify", str(repo_path), now, now),
        )
        connection.commit()
    finally:
        connection.close()


async def wait_event(
    websocket, event_type: str, timeout: float
) -> dict | None:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return None
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
        except TimeoutError:
            return None
        except Exception:  # noqa: BLE001 - 连接关闭 / 协议异常时结束等待
            return None
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if message.get("type") == event_type:
            return message


async def drain(websocket, seconds: float = 0.4) -> None:
    deadline = asyncio.get_running_loop().time() + seconds
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return
        try:
            await asyncio.wait_for(websocket.recv(), timeout=remaining)
        except Exception:  # noqa: BLE001 - 排空阶段无需区分原因
            return


async def websocket_checks(base_http: str, repo: Path, reporter: Reporter) -> None:
    try:
        import websockets
    except ImportError:
        reporter.skip("WebSocket 实时推送", "未安装 websockets（uvicorn[standard] 通常自带）")
        return

    ws_url = base_http.replace("http://", "ws://") + f"/ws/projects/{PROJECT_ID}"
    status, body = http("GET", f"{base_http}/health/interfaces")
    watcher_available = bool(json.loads(body).get("available")) if status == 200 else False

    try:
        async with websockets.connect(ws_url) as websocket:
            # 1) 手动刷新 -> 事件
            await drain(websocket)
            target = repo / "users.py"
            target.write_text(
                target.read_text(encoding="utf-8")
                + '\n\ndef ws_manual_event() -> None:\n    """手动刷新触发。"""\n    pass\n',
                encoding="utf-8",
            )
            status, _ = http(
                "POST", f"{base_http}/api/projects/{PROJECT_ID}/interfaces/refresh", {}
            )
            event = await wait_event(websocket, "interface.updated", 6)
            reporter.check(
                "手动 refresh 后 WebSocket 收到 interface.updated",
                status == 200 and event is not None,
                f"added={len(event['payload']['added'])}" if event else "未收到事件",
            )

            # 2) watchdog 自动监听 -> 事件（未安装则跳过）
            if not watcher_available:
                reporter.skip(
                    "watchdog 自动监听推送",
                    "后端未安装 watchdog，只能手动刷新",
                )
                return

            await drain(websocket)
            target = repo / "products.py"
            target.write_text(
                target.read_text(encoding="utf-8")
                + '\n\ndef ws_auto_event() -> None:\n    """文件监听自动触发。"""\n    pass\n',
                encoding="utf-8",
            )
            event = await wait_event(websocket, "interface.updated", 8)
            reporter.check(
                "文件变更后 watchdog 自动推送 interface.updated",
                event is not None,
                f"added={len(event['payload']['added'])}" if event else "未收到事件",
            )
    except Exception as exc:  # noqa: BLE001 - 连接失败也要给出明确结果
        reporter.check("WebSocket 实时推送", False, f"{type(exc).__name__}: {exc}")


def cli_and_mcp_checks(
    base_http: str, db_url: str, temp_dir: Path, reporter: Reporter
) -> None:
    online = temp_dir / "cli_online.md"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "cli.teamcode",
            "pull-interfaces",
            "--project",
            PROJECT_ID,
            "--api-base",
            base_http,
            "--output",
            str(online),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    online_text = online.read_text(encoding="utf-8") if online.exists() else ""
    reporter.check(
        "CLI 在线模式拉取 Markdown",
        result.returncode == 0
        and "唯一事实来源" in online_text
        and "normalize_email" in online_text,
        f"exit={result.returncode}",
    )

    offline = temp_dir / "cli_offline.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "cli.teamcode",
            "pull-interfaces",
            "--project",
            PROJECT_ID,
            "--offline",
            "--db-url",
            db_url,
            "--format",
            "json",
            "--output",
            str(offline),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    offline_ok = False
    if result.returncode == 0 and offline.exists():
        payload = json.loads(offline.read_text(encoding="utf-8"))
        offline_ok = payload["project_id"] == PROJECT_ID and any(
            item["name"] == "normalize_email" for item in payload["interfaces"]
        )
    reporter.check(
        "CLI 离线模式读取数据库", offline_ok, f"exit={result.returncode}"
    )

    mcp_message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_interface",
            "arguments": {"project_id": PROJECT_ID, "name": "normalize_email"},
        },
    }
    result = subprocess.run(
        [sys.executable, "-m", "cli.mcp_server", "--db-url", db_url],
        cwd=ROOT,
        input=json.dumps(mcp_message) + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    mcp_ok = False
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        text = payload["result"]["content"][0]["text"]
        mcp_ok = "normalize_email" in text
    except (IndexError, KeyError, json.JSONDecodeError):
        pass
    reporter.check("MCP get_interface 返回接口详情", mcp_ok)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="接口注册中心端到端验证")
    parser.add_argument("--keep", action="store_true", help="保留临时目录")
    args = parser.parse_args(argv)

    reporter = Reporter()
    temp_dir = Path(tempfile.mkdtemp(prefix="teamcode-verify-"))
    server = None
    log_handle = None

    try:
        repo = temp_dir / "repo"
        shutil.copytree(FIXTURE, repo)
        shutil.rmtree(repo / ".teamcode", ignore_errors=True)

        db_path = temp_dir / "verify.db"
        db_url = f"sqlite+aiosqlite:///{db_path}"
        prepare_database(db_path, repo)
        reporter.check("Alembic 迁移（含 C 的新表）", True)

        port = free_port()
        base_http = f"http://127.0.0.1:{port}"
        env = os.environ.copy()
        env["DATABASE_URL"] = db_url
        # 该脚本只验证接口注册中心本身，关闭登录鉴权
        env["TEAMCODE_REQUIRE_AUTH"] = "0"
        log_handle = (temp_dir / "server.log").open("w", encoding="utf-8")
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "info",
            ],
            cwd=BACKEND,
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        ready = wait_until_ready(base_http)
        reporter.check("后端启动并响应 /health", ready)
        if not ready:
            return 1

        status, body = http("GET", f"{base_http}/health")
        reporter.check(
            "A 的 /health 契约未被破坏",
            status == 200 and json.loads(body) == {"status": "ok"},
            body,
        )

        status, body = http("GET", f"{base_http}/health/interfaces")
        reporter.check(
            "C 的健康检查 /health/interfaces 可用",
            status == 200 and "available" in json.loads(body),
        )

        status, body = http(
            "POST", f"{base_http}/api/projects/{PROJECT_ID}/interfaces/refresh", {}
        )
        summary = json.loads(body) if status == 200 else {}
        reporter.check(
            "首次扫描注册接口",
            status == 200 and len(summary.get("added", [])) == 11,
            f"added={len(summary.get('added', []))}",
        )

        status, body = http(
            "GET", f"{base_http}/api/projects/{PROJECT_ID}/interfaces?format=json"
        )
        listing = json.loads(body) if status == 200 else {}
        interfaces = listing.get("interfaces", [])
        target = next(
            (item for item in interfaces if item["name"] == "normalize_email"), None
        )
        reporter.check(
            "JSON 列表包含接口与 C 扩展字段",
            status == 200
            and listing.get("count") == 11
            and target is not None
            and "lineno" in target,
            f"count={listing.get('count')}",
        )

        if target:
            status, body = http(
                "GET", f"{base_http}/api/interfaces/{target['interface_id']}"
            )
            detail = json.loads(body) if status == 200 else {}
            reporter.check(
                "接口详情 v1",
                status == 200 and detail.get("version") == 1,
                f"version={detail.get('version')}",
            )

        status, body = http(
            "GET", f"{base_http}/api/projects/{PROJECT_ID}/interfaces?format=markdown"
        )
        reporter.check(
            "Markdown 文档包含签名与使用说明",
            status == 200
            and "唯一事实来源" in body
            and "normalize_email" in body,
        )

        status, body = http("GET", f"{base_http}/api/interfaces/iface_missing")
        reporter.check(
            "不存在的接口返回结构化 404",
            status == 404 and json.loads(body).get("code") == "interface_not_found",
        )

        # 版本递增：修改签名后重新扫描
        users = repo / "users.py"
        users.write_text(
            users.read_text(encoding="utf-8").replace(
                "def normalize_email(email: str) -> str:",
                "def normalize_email(email: str, upper: bool = False) -> str:",
            ),
            encoding="utf-8",
        )
        http("POST", f"{base_http}/api/projects/{PROJECT_ID}/interfaces/refresh", {})
        if target:
            status, body = http(
                "GET", f"{base_http}/api/interfaces/{target['interface_id']}"
            )
            detail = json.loads(body) if status == 200 else {}
            reporter.check(
                "签名变化后版本递增到 v2",
                status == 200 and detail.get("version") == 2,
                f"version={detail.get('version')}",
            )

        asyncio.run(websocket_checks(base_http, repo, reporter))
        cli_and_mcp_checks(base_http, db_url, temp_dir, reporter)

        # 软删除：删除文件后接口不再出现在列表
        (repo / "orders.py").unlink()
        http("POST", f"{base_http}/api/projects/{PROJECT_ID}/interfaces/refresh", {})
        status, body = http(
            "GET", f"{base_http}/api/projects/{PROJECT_ID}/interfaces?format=json"
        )
        after_delete = json.loads(body) if status == 200 else {}
        remaining = after_delete.get("interfaces", [])
        reporter.check(
            "删除文件后接口被软删除",
            status == 200
            and not any(item["module"] == "orders" for item in remaining),
            f"remaining={after_delete.get('count')}",
        )

        status, body = http("GET", f"{base_http}/health")
        reporter.check(
            "全部操作后 /health 仍保持 A 的契约",
            status == 200 and json.loads(body) == {"status": "ok"},
        )

        print()
        passed = sum(1 for state, _, _ in reporter.results if state == "PASS")
        failed = sum(1 for state, _, _ in reporter.results if state == "FAIL")
        skipped = sum(1 for state, _, _ in reporter.results if state == "SKIP")
        print(f"结果：{passed} passed, {failed} failed, {skipped} skipped")
        if failed and log_handle is not None:
            log_handle.flush()
            tail = (temp_dir / "server.log").read_text(encoding="utf-8")[-3000:]
            print("\n--- server log (tail) ---\n" + tail)
        return 0 if reporter.ok else 1
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
        if log_handle is not None:
            log_handle.close()
        if args.keep:
            print(f"临时目录已保留：{temp_dir}")
        else:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
