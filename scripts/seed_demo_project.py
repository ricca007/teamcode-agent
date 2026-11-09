#!/usr/bin/env python3
"""准备一个可直接演示的完整项目（A 规划 + B 执行 + C 接口）。

流程：
1. 把 ``experiments/fixtures/shop_app`` 复制到 /tmp 并初始化 Git 仓库；
2. 在 SQLite 中建表（A/B/C + 整合层）；
3. 创建项目、成员，调用 A 的 Manager Agent 生成任务；
4. 用 B 的 MockAdapter 跑一个任务，产生会话、日志、变更；
5. 用 C 的接口注册中心扫描 11 个接口。

运行（仓库根目录）：

    .venv/bin/python scripts/seed_demo_project.py --reset

脚本只写 /tmp，不会修改仓库文件。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 种子脚本是本地管理员操作，绕过登录，但仍会签发 leader token
os.environ.setdefault("TEAMCODE_REQUIRE_AUTH", "0")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

FIXTURE = ROOT / "experiments" / "fixtures" / "shop_app"
DEFAULT_DB = Path("/tmp/teamcode-demo.db")
DEFAULT_REPO = Path("/tmp/teamcode-demo-repo")
DEFAULT_PROJECT_ID = "p_demo"

REQUIREMENTS = (
    "在线商城：用户管理、商品管理、订单管理、优惠券功能，"
    "以及实时接口文档和前端控制台。"
)


def _remove_sqlite_file(db_url: str) -> None:
    if not db_url.startswith("sqlite"):
        return
    from sqlalchemy.engine import make_url

    database = make_url(db_url).database
    if database and database != ":memory:":
        path = Path(database)
        if path.exists():
            path.unlink()


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
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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
                    f"项目 {project_id} 已存在。若要重建演示数据，请加 --reset。"
                )
                return

            registration = await service.register(
                RegisterRequest(
                    name="演示负责人",
                    email="leader@demo.invalid",
                    password="demo123456",
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
                    name="在线商城演示",
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
                    requirements=REQUIREMENTS,
                    roles=["A", "B", "C"],
                    max_tasks=6,
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
                    RunRequest(actor_id=first["owner_id"]),
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

        print("演示数据已准备")
        print(f"  项目 ID：{project_id}")
        print("  队长账号：leader@demo.invalid / demo123456")
        print(f"  队长 Token：{leader_token}")
        print(f"  仓库路径：{repo_path}")
        print(f"  数据库：{db_url}")
        print(f"  任务数：{len(plan_result['plan']['tasks'])}（计划 v{plan_result['version']}）")
        print(f"  接口数：{status.total_interfaces}")
        if executed:
            print(
                "  已执行任务："
                f"{executed['task_id']} / {executed['status']} / "
                f"日志 {executed['logs']} 条 / 文件 {executed['files']} 个"
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

    if args.reset:
        _remove_sqlite_file(args.db_url)
        shutil.rmtree(repo_path, ignore_errors=True)
    if not repo_path.exists():
        shutil.copytree(FIXTURE, repo_path)
        shutil.rmtree(repo_path / ".teamcode", ignore_errors=True)
    _init_git_repo(repo_path)

    try:
        asyncio.run(
            seed(
                args.db_url,
                repo_path,
                args.project_id,
                run_task=args.run,
            )
        )
    except Exception as exc:  # noqa: BLE001 - 演示脚本给出明确失败信息
        print(f"[seed] 失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print()
    print("下一步：")
    print("  cd backend")
    print(
        f'  DATABASE_URL="{args.db_url}" ../.venv/bin/python -m uvicorn '
        "app.main:app --reload --port 8000"
    )
    print("  # 另开终端：")
    print("  cd frontend && npm run dev")
    print(f"  # 浏览器打开 http://localhost:5173 ，项目 ID 填：{args.project_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
