#!/usr/bin/env python3
"""准备一个可直接演示的完整项目（A 规划 + B 执行 + C 接口）。

流程：
1. 把对应语言的 fixture 复制到 /tmp 并初始化 Git 仓库；
2. 在 SQLite 中建表（A/B/C + 整合层）；
3. 创建项目、成员，调用 A 的 Manager Agent 生成任务；
4. 用 B 的 MockAdapter 跑一个任务，产生会话、日志、变更；
5. 用 C 的接口注册中心扫描 11 个接口。

运行（仓库根目录）：

    .venv/bin/python scripts/seed_demo_project.py --reset
    .venv/bin/python scripts/seed_demo_project.py --reset --lang en --run

``--lang`` 控制 fixture、需求文案、项目/成员名以及占位角色名
（角色 A / Role A），默认中文。

脚本只写 /tmp（加 ``--lang`` 不改变路径），不会修改仓库文件。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

# 种子脚本是本地管理员操作，绕过登录，但仍会签发 leader token
os.environ.setdefault("TEAMCODE_REQUIRE_AUTH", "0")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

FIXTURES = {
    "zh": ROOT / "experiments" / "fixtures" / "shop_app",
    "en": ROOT / "experiments" / "fixtures" / "shop_app_en",
}
DEFAULT_DB = Path("/tmp/teamcode-demo.db")
DEFAULT_REPO = Path("/tmp/teamcode-demo-repo")
DEFAULT_PROJECT_ID = "p_demo"

REQUIREMENTS = {
    "zh": (
        "在线商城：用户管理、商品管理、订单管理、优惠券功能，"
        "以及实时接口文档和前端控制台。"
    ),
    "en": """Online store demo with these modules:
- User accounts and login
- Product catalog and inventory
- Discount coupons
- Orders, cart, and payment
- Real-time API contract docs
- React frontend console""",
}

PROJECT_NAME = {"zh": "在线商城演示", "en": "Online Store Demo"}
LEADER_NAME = {"zh": "演示负责人", "en": "Demo Leader"}

DEMO_EMAIL = "leader@demo.invalid"


def pick(lang: str, zh: str, en: str) -> str:
    return en if lang == "en" else zh


def _seed_password() -> tuple[str, bool]:
    """返回 (演示密码, 是否来自环境变量)。

    优先读取 ``TEAMCODE_SEED_PASSWORD``；未设置时随机生成一次，
    避免脚本里硬编码的弱口令进入演示库。
    """
    env_password = os.getenv("TEAMCODE_SEED_PASSWORD", "").strip()
    if env_password:
        return env_password, True
    return secrets.token_urlsafe(12), False


def _remove_sqlite_file(db_url: str) -> None:
    if not db_url.startswith("sqlite"):
        return
    from sqlalchemy.engine import make_url

    database = make_url(db_url).database
    if database and database != ":memory:":
        path = Path(database)
        if path.exists():
            path.unlink()


def _remove_tree(path: Path) -> None:
    """删除目录；Windows 上 Git 对象是只读的，先补写权限再删。"""
    if not path.exists():
        return

    def _on_error(func, target, _exc):  # type: ignore[no-untyped-def]
        try:
            os.chmod(target, 0o700)
        except OSError:
            pass
        func(target)

    shutil.rmtree(path, onexc=_on_error)


def _init_git_repo(repo_path: Path) -> None:
    if (repo_path / ".git").exists():
        return
    identity = (
        "-c",
        "user.name=TeamCode Demo",
        "-c",
        "user.email=demo@teamcode.invalid",
    )
    subprocess.run(
        ["git", "init", "-b", "main", str(repo_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", *identity, "-C", str(repo_path), "add", "."],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", *identity, "-C", str(repo_path), "commit", "-m", "demo fixture"],
        check=True,
        capture_output=True,
        text=True,
    )


async def _wait_terminal(factory, task_id: str, timeout: float = 10.0) -> dict:
    from app.integration.service import IntegrationError, IntegrationService

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    last: dict | None = None
    while loop.time() < deadline:
        async with factory() as db:
            try:
                last = await IntegrationService(db, factory).task_status_dict(
                    task_id
                )
            except IntegrationError:
                last = None
        if last is not None and last["status"] in {
            "succeeded",
            "failed",
            "terminated",
        }:
            return last
        await asyncio.sleep(0.1)
    raise RuntimeError(f"等待任务结束超时，最后状态: {last}")


async def seed(
    db_url: str,
    repo_path: Path,
    project_id: str,
    *,
    run_task: bool,
    lang: str = "zh",
) -> None:
    from app.integration.auth import Actor
    from app.integration.models import IntegrationBase
    from app.integration.schemas import (
        ProjectCreateRequest,
        RegisterRequest,
        RequirementsRequest,
        RunRequest,
    )
    from app.integration.service import IntegrationService, shutdown_runtimes
    from app.interface_registry.models import InterfaceRegistryBase
    from app.interface_registry.service import InterfaceRegistryService
    from app.models import Base
    from app.models.project import Project
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(db_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(InterfaceRegistryBase.metadata.create_all)
            await connection.run_sync(IntegrationBase.metadata.create_all)

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            service = IntegrationService(session, factory)

            existing = await session.get(Project, project_id)
            if existing is not None:
                print(
                    pick(
                        lang,
                        f"项目 {project_id} 已存在。若要重建演示数据，请加 --reset。",
                        f"Project {project_id} already exists. Add --reset to rebuild.",
                    )
                )
                return

            password, password_from_env = _seed_password()
            registration = await service.register(
                RegisterRequest(
                    name=LEADER_NAME[lang],
                    email=DEMO_EMAIL,
                    password=password,
                )
            )
            leader_token = registration["token"]
            leader_user = registration["user"]
            leader_actor = Actor(
                session_id="seed",
                user_id=leader_user["id"],
                name=leader_user["name"],
            )
            await service.create_project(
                ProjectCreateRequest(
                    project_id=project_id,
                    name=PROJECT_NAME[lang],
                    repo_path=str(repo_path),
                ),
                leader_actor,
            )

            status = await InterfaceRegistryService(session).scan(
                project_id, repo_path
            )

            plan_result = await service.plan_project(
                project_id,
                RequirementsRequest(
                    requirements=REQUIREMENTS[lang],
                    roles=["A", "B", "C"],
                    max_tasks=6,
                    locale=lang,
                ),
                leader_actor,
            )
            tasks = await service.list_tasks(project_id, leader_actor)

        executed: dict | None = None
        if run_task and tasks:
            first = tasks[0]
            async with factory() as session:
                service = IntegrationService(session, factory)
                started = await service.run_task(
                    first["task_id"],
                    RunRequest(actor_id=first["owner_id"], locale=lang),
                    leader_actor,
                )
            terminal = await _wait_terminal(factory, first["task_id"])
            async with factory() as session:
                service = IntegrationService(session, factory)
                logs = await service.task_logs(first["task_id"], leader_actor)
                changes = await service.task_changes(
                    first["task_id"], leader_actor
                )
            executed = {
                "task_id": first["task_id"],
                "session_id": started["session_id"],
                "status": terminal["status"],
                "logs": len(logs),
                "files": len(changes[0]["files"]) if changes else 0,
            }

        print(pick(lang, "演示数据已准备", "Demo data is ready"))
        print(
            pick(
                lang,
                f"  项目 ID：{project_id}",
                f"  Project ID: {project_id}",
            )
        )
        if password_from_env:
            print(
                pick(
                    lang,
                    f"  队长账号：{DEMO_EMAIL}（密码来自 TEAMCODE_SEED_PASSWORD，未回显）",
                    f"  Leader account: {DEMO_EMAIL} (password from "
                    "TEAMCODE_SEED_PASSWORD, not echoed)",
                )
            )
        else:
            print(
                pick(
                    lang,
                    f"  队长账号：{DEMO_EMAIL} / {password}",
                    f"  Leader account: {DEMO_EMAIL} / {password}",
                )
            )
            print(
                pick(
                    lang,
                    "  注意：该密码为随机生成，请首次登录后立即修改。",
                    "  Note: this password was generated randomly; "
                    "change it after first login.",
                )
            )
        print(
            pick(
                lang,
                f"  队长 Token：{leader_token}",
                f"  Leader token: {leader_token}",
            )
        )
        print(pick(lang, f"  仓库路径：{repo_path}", f"  Repo path: {repo_path}"))
        print(pick(lang, f"  数据库：{db_url}", f"  Database: {db_url}"))
        print(
            pick(
                lang,
                f"  任务数：{len(plan_result['plan']['tasks'])}"
                f"（计划 v{plan_result['version']}）",
                f"  Tasks: {len(plan_result['plan']['tasks'])} "
                f"(plan v{plan_result['version']})",
            )
        )
        print(
            pick(
                lang,
                f"  接口数：{status.total_interfaces}",
                f"  Interfaces: {status.total_interfaces}",
            )
        )
        if executed:
            print(
                pick(
                    lang,
                    "  已执行任务："
                    f"{executed['task_id']} / {executed['status']} / "
                    f"日志 {executed['logs']} 条 / 文件 {executed['files']} 个",
                    "  Executed task: "
                    f"{executed['task_id']} / {executed['status']} / "
                    f"logs {executed['logs']} / files {executed['files']}",
                )
            )
        await shutdown_runtimes()
    finally:
        await engine.dispose()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="准备完整演示项目")
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--db-url", default=f"sqlite+aiosqlite:///{DEFAULT_DB}")
    parser.add_argument("--repo-path", default=str(DEFAULT_REPO))
    parser.add_argument(
        "--lang",
        choices=("zh", "en"),
        default="zh",
        help="演示数据语言：zh 使用中文 fixture，en 使用英文 fixture",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="删除 /tmp 下的演示数据库与仓库后重建",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="生成计划后自动执行第一个任务（默认不执行，留给网页操作）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_path = Path(args.repo_path)
    fixture = FIXTURES[args.lang]

    if args.reset:
        _remove_sqlite_file(args.db_url)
        _remove_tree(repo_path)
    if not repo_path.exists():
        shutil.copytree(fixture, repo_path)
        shutil.rmtree(repo_path / ".teamcode", ignore_errors=True)
    _init_git_repo(repo_path)

    try:
        asyncio.run(
            seed(
                args.db_url,
                repo_path,
                args.project_id,
                run_task=args.run,
                lang=args.lang,
            )
        )
    except Exception as exc:  # noqa: BLE001 - 演示脚本给出明确失败信息
        print(f"[seed] 失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print()
    print(pick(args.lang, "下一步：", "Next steps:"))
    print("  cd backend")
    print(
        f'  DATABASE_URL="{args.db_url}" ../.venv/bin/python -m uvicorn '
        "app.main:app --reload --port 8000"
    )
    print(pick(args.lang, "  # 另开终端：", "  # In another terminal:"))
    print("  cd frontend && npm run dev")
    print(
        pick(
            args.lang,
            f"  # 浏览器打开 http://localhost:5173 ，项目 ID 填：{args.project_id}",
            "  # Open http://localhost:5173 and use project ID: "
            f"{args.project_id}",
        )
    )
    print(
        pick(
            args.lang,
            "  # 让界面能选择 mock：后端启动时加 "
            "TEAMCODE_AGENT=mock TEAMCODE_EXPOSE_MOCK=1",
            "  # To select mock in the UI, start the backend with "
            "TEAMCODE_AGENT=mock TEAMCODE_EXPOSE_MOCK=1",
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
