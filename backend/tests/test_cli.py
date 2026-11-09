"""C-3 验收测试：CLI 离线/在线拉取、输出文件、错误处理。"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from cli.teamcode import main


async def _prepare_database(db_path: Path, project_id: str, root: Path) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.interface_registry.models import InterfaceRegistryBase
    from app.interface_registry.service import InterfaceRegistryService
    from app.models import Base
    from app.models.project import Project
    from app.models.user import User

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


@pytest.fixture()
def prepared_db(tmp_path: Path, sample_project: Path) -> str:
    db_path = tmp_path / "cli.db"
    asyncio.run(_prepare_database(db_path, "p_test", sample_project))
    return f"sqlite+aiosqlite:///{db_path}"


# ---------------------------------------------------------------------------
# 离线模式
# ---------------------------------------------------------------------------


def test_offline_markdown_writes_file(prepared_db, tmp_path, capsys):
    output = tmp_path / "context" / "interfaces.md"

    code = main(
        [
            "pull-interfaces",
            "--project",
            "p_test",
            "--offline",
            "--db-url",
            prepared_db,
            "--output",
            str(output),
        ]
    )

    assert code == 0
    text = output.read_text(encoding="utf-8")
    assert "TeamCode 接口文档" in text
    assert "唯一事实来源" in text
    assert "UserService.get_user" in text
    assert "已写入" in capsys.readouterr().out


def test_offline_json_prints_to_stdout(prepared_db, capsys):
    code = main(
        [
            "pull-interfaces",
            "--project",
            "p_test",
            "--offline",
            "--db-url",
            prepared_db,
            "--format",
            "json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["project_id"] == "p_test"
    assert payload["count"] > 0
    assert any(item["name"] == "normalize_name" for item in payload["interfaces"])


def test_offline_reports_database_degradation(tmp_path, capsys):
    code = main(
        [
            "pull-interfaces",
            "--project",
            "p_missing",
            "--offline",
            "--db-url",
            "postgresql+psycopg://user:secret@127.0.0.1:1/teamcode",
            "--fallback-db-url",
            f"sqlite+aiosqlite:///{tmp_path / 'fallback.db'}",
        ]
    )

    assert code == 2
    captured = capsys.readouterr()
    assert "降级提示" in captured.err
    assert "postgresql" in captured.err.lower()
    assert "项目不存在" in captured.err
    assert "secret" not in captured.err


def test_offline_unknown_project_returns_clear_error(prepared_db, capsys):
    code = main(
        [
            "pull-interfaces",
            "--project",
            "p_missing",
            "--offline",
            "--db-url",
            prepared_db,
        ]
    )

    assert code == 2
    captured = capsys.readouterr()
    assert "项目不存在" in captured.err
    assert "p_missing" in captured.err


def test_offline_unexpected_database_error_is_logged(tmp_path, capsys):
    bad_url = f"sqlite+aiosqlite:///{tmp_path / 'missing-dir' / 'x.db'}"
    code = main(
        [
            "pull-interfaces",
            "--project",
            "p_test",
            "--offline",
            "--db-url",
            bad_url,
        ]
    )

    assert code == 2
    captured = capsys.readouterr()
    assert "离线读取失败" in captured.err


# ---------------------------------------------------------------------------
# 在线模式（本地 HTTP 假后端）
# ---------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/projects/p_ok/interfaces":
            fmt = parse_qs(parsed.query).get("format", ["markdown"])[0]
            if fmt == "json":
                body = json.dumps(
                    {
                        "project_id": "p_ok",
                        "generated_at": "2026-01-01T00:00:00Z",
                        "count": 1,
                        "interfaces": [
                            {
                                "interface_id": "i1",
                                "project_id": "p_ok",
                                "module": "app.users",
                                "file_path": "app/users.py",
                                "name": "get_user",
                                "kind": "function",
                                "params": [],
                                "returns": "dict",
                                "docstring": None,
                                "version": 1,
                                "commit_hash": None,
                                "dependencies": [],
                            }
                        ],
                    }
                ).encode("utf-8")
                self._respond(200, "application/json", body)
            else:
                self._respond(
                    200,
                    "text/markdown; charset=utf-8",
                    "# TeamCode 接口文档\n\n`get_user`".encode(),
                )
            return

        body = json.dumps(
            {"code": "project_not_found", "message": "项目不存在"}
        ).encode("utf-8")
        self._respond(404, "application/json", body)

    def _respond(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # 静默测试日志
        pass


@pytest.fixture()
def http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def test_remote_markdown(http_server, tmp_path, capsys):
    output = tmp_path / "interfaces.md"

    code = main(
        [
            "pull-interfaces",
            "--project",
            "p_ok",
            "--api-base",
            http_server,
            "--output",
            str(output),
        ]
    )

    assert code == 0
    assert "get_user" in output.read_text(encoding="utf-8")
    assert "已写入" in capsys.readouterr().out


def test_remote_json(http_server, tmp_path):
    output = tmp_path / "interfaces.json"

    code = main(
        [
            "pull-interfaces",
            "--project",
            "p_ok",
            "--api-base",
            http_server,
            "--format",
            "json",
            "--output",
            str(output),
        ]
    )

    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["project_id"] == "p_ok"
    assert payload["interfaces"][0]["name"] == "get_user"


def test_remote_unknown_project_returns_error(http_server, capsys):
    code = main(
        ["pull-interfaces", "--project", "p_missing", "--api-base", http_server]
    )

    assert code == 2
    assert "项目不存在" in capsys.readouterr().err


def test_remote_unreachable_backend_returns_error(capsys):
    # 端口 1 基本不可能有服务监听
    code = main(
        [
            "pull-interfaces",
            "--project",
            "p_ok",
            "--api-base",
            "http://127.0.0.1:1",
            "--timeout",
            "0.5",
        ]
    )

    assert code == 2
    assert "无法连接后端" in capsys.readouterr().err
