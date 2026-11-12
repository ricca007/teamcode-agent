"""课堂 MVP：项目/规划/执行 API，复用 A/B，保留公共路径。"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import engine, get_session, session_factory
from app.errors import Role2Error
from app.integration.auth import Actor, auth_required, get_actor, issue_session
from app.integration.models import IntegrationBase, RunRecord
from app.integration.service import (
    agent_configs,
    commit_and_merge,
    control,
    latest_plan,
    latest_run,
    plan_project,
    prepare_repo,
    publish_task,
    require,
    shutdown_runtimes,
    start_run,
    task_json,
    tasks,
)
from app.interface_registry.models import InterfaceRegistryBase
from app.interface_registry.service import InterfaceRegistryService
from app.interface_registry.watcher import watcher_manager
from app.models import Base
from app.models.project import Project, ProjectMember
from app.models.task import TaskStatus
from app.models.user import User
from app.schemas.core import ProjectRole, UserRole, utc_now

identities = []


async def bootstrap(factory, repo):
    """只准备真实课堂项目与成员；token 不写入源码。"""
    await asyncio.to_thread(prepare_repo, repo)
    async with factory() as db:
        for key, name in [
            ("u_a", "A · 规划负责人"),
            ("u_b", "B · 运行时负责人"),
            ("u_c", "C · 接口与前端"),
        ]:
            if await db.get(User, key) is None:
                db.add(
                    User(
                        id=key,
                        name=name,
                        email=key + "@classroom.invalid",
                        role=UserRole.LEADER if key == "u_a" else UserRole.MEMBER,
                    )
                )
        await db.flush()
        project = await db.get(Project, "p_demo")
        if project is None:
            project = Project(
                id="p_demo", name="在线商城 · 小组协作", owner_id="u_a", repo_path=str(repo)
            )
            db.add(project)
            await db.flush()
            for key in ("u_a", "u_b", "u_c"):
                db.add(
                    ProjectMember(
                        project_id=project.id,
                        user_id=key,
                        role=ProjectRole.OWNER if key == "u_a" else ProjectRole.MEMBER,
                    )
                )
        members = []
        for key in ("u_a", "u_b", "u_c"):
            members.append(
                {
                    "user_id": key,
                    "name": (await db.get(User, key)).name,
                    "token": issue_session(db, key, project.id),
                    "role": "leader" if key == "u_a" else "member",
                }
            )
        await db.commit()
        if await latest_plan(db, project.id) is None:
            await plan_project(db, project, "在线商城：用户管理、商品管理、订单管理")
        await InterfaceRegistryService(db).scan(project.id, project.repo_path)
        return {"project_id": project.id, "members": members}


@asynccontextmanager
async def lifespan(app):
    async with engine.begin() as conn:
        for metadata in (Base.metadata, IntegrationBase.metadata, InterfaceRegistryBase.metadata):
            await conn.run_sync(metadata.create_all)
    # 进程重启无法恢复外部进程；明确结束遗留状态，历史日志和 diff 仍可读。
    async with session_factory() as db:
        for run in (await db.scalars(select(RunRecord))).all():
            if run.data.get("status") in {"running", "pending", "paused"}:
                run.data = {**run.data, "status": "failed", "error": "服务已重启，请重新运行任务"}
                for task in await tasks(db, run.project_id):
                    if task.id == run.task_id:
                        task.status = TaskStatus.BLOCKED
        await db.commit()
    if os.getenv("TEAMCODE_DEMO") == "1":
        identities[:] = [await bootstrap(session_factory, Path(os.environ["TEAMCODE_DEMO_REPO"]))]
    try:
        yield
    finally:
        from app.interface_registry.documentation import shutdown

        await shutdown()
        watcher_manager.stop_all()
        await shutdown_runtimes()
        await engine.dispose()


router = APIRouter(lifespan=lifespan)


@dataclass
class Context:
    db: object
    project: Project
    actor: Actor
    task: object = None

    def leader(self):
        require(self.actor.user_id == self.project.owner_id, "此操作需要组长权限", 403)

    def executor(self):
        require(
            self.actor.user_id in {self.project.owner_id, self.task.owner_id},
            "仅任务负责人或组长可查看日志和执行任务",
            403,
        )


async def authorize(db, project, actor):
    require(project is not None, "项目不存在", 404)
    if actor is None and not auth_required():
        actor = Actor(project.owner_id)
    require(actor is not None, "请提供项目 token", 401)
    require(actor.project_id in {None, project.id}, "Token 不属于此项目", 403)
    member = await db.get(ProjectMember, {"project_id": project.id, "user_id": actor.user_id})
    require(member is not None or not auth_required(), "你不是该项目成员", 403)
    return Context(db, project, actor)


async def project_context(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_session)],
    actor: Annotated[Actor | None, Depends(get_actor)],
):
    return await authorize(db, await db.get(Project, project_id), actor)


async def task_context(
    task_id: str,
    db: Annotated[AsyncSession, Depends(get_session)],
    actor: Annotated[Actor | None, Depends(get_actor)],
):
    from app.models.task import Task

    task = await db.get(Task, task_id)
    require(task is not None, "任务不存在", 404)
    ctx = await authorize(db, await db.get(Project, task.project_id), actor)
    ctx.task = next(item for item in await tasks(db, task.project_id) if item.id == task_id)
    ctx.executor()
    return ctx


class Requirement(BaseModel):
    requirements: str = Field(min_length=1)
    mode: str = "plan"


class RunRequest(BaseModel):
    agent_name: str = "mock"
    context: dict | None = None


class NewProject(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    repo_path: str


class Member(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class Assignment(BaseModel):
    user_id: str


class Commit(BaseModel):
    message: str = Field(default="MVP: complete task", min_length=1, max_length=300)


@router.get("/api/demo")
async def demo():
    require(os.getenv("TEAMCODE_DEMO") == "1" and identities, "课堂身份入口未开启", 404)
    return identities[0]


@router.get("/api/agents")
async def agents():
    return {
        "agents": [{"name": "mock", "available": True, "kind": "demo"}]
        + [{"name": name, "available": True, "kind": "cli"} for name in agent_configs()]
    }


@router.get("/api/me")
async def me(
    db: Annotated[AsyncSession, Depends(get_session)],
    actor: Annotated[Actor | None, Depends(get_actor)],
):
    require(actor is not None, "需要项目 token", 401)
    project = await db.get(Project, actor.project_id)
    return {
        "user_id": actor.user_id,
        "project_id": actor.project_id,
        "name": (await db.get(User, actor.user_id)).name,
        "role": "leader" if project and project.owner_id == actor.user_id else "member",
    }


@router.post("/api/projects")
async def create_project(
    body: NewProject,
    db: Annotated[AsyncSession, Depends(get_session)],
    actor: Annotated[Actor | None, Depends(get_actor)],
):
    require(actor is not None, "需要项目 token", 401)
    repo = Path(body.repo_path).resolve()
    require(repo.is_dir(), "仓库目录不存在", 422)
    await asyncio.to_thread(prepare_repo, repo)
    project = Project(
        id="p_" + uuid4().hex[:10], name=body.name, repo_path=str(repo), owner_id=actor.user_id
    )
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=actor.user_id, role=ProjectRole.OWNER))
    token = issue_session(db, actor.user_id, project.id)
    await db.commit()
    return {"id": project.id, "name": project.name, "token": token}


@router.get("/api/projects/{project_id}/members")
async def members(ctx: Annotated[Context, Depends(project_context)]):
    rows = (
        await ctx.db.execute(
            select(ProjectMember, User).join(User).where(ProjectMember.project_id == ctx.project.id)
        )
    ).all()
    return {
        "members": [
            {
                "user_id": u.id,
                "name": u.name,
                "role": "leader" if m.role == ProjectRole.OWNER else "member",
            }
            for m, u in rows
        ]
    }


@router.post("/api/projects/{project_id}/members")
async def invite(body: Member, ctx: Annotated[Context, Depends(project_context)]):
    ctx.leader()
    user = User(
        id="u_" + uuid4().hex[:10], name=body.name, email=uuid4().hex + "@classroom.invalid"
    )
    ctx.db.add(user)
    await ctx.db.flush()
    ctx.db.add(ProjectMember(project_id=ctx.project.id, user_id=user.id, role=ProjectRole.MEMBER))
    token = issue_session(ctx.db, user.id, ctx.project.id)
    await ctx.db.commit()
    return {"user_id": user.id, "name": user.name, "token": token}


@router.post("/api/projects/{project_id}/requirements")
async def requirements(body: Requirement, ctx: Annotated[Context, Depends(project_context)]):
    ctx.leader()
    require(body.mode in {"plan", "replan"}, "mode 必须是 plan 或 replan", 422)
    return await plan_project(ctx.db, ctx.project, body.requirements, body.mode)


@router.get("/api/projects/{project_id}/plan")
async def read_plan(ctx: Annotated[Context, Depends(project_context)]):
    plan = await latest_plan(ctx.db, ctx.project.id)
    require(plan is not None, "尚无计划", 404)
    return {"plan": plan.payload, "version": plan.version, "diff": plan.request.get("diff")}


@router.get("/api/projects/{project_id}/tasks")
async def read_tasks(ctx: Annotated[Context, Depends(project_context)]):
    return {"tasks": [task_json(t) for t in await tasks(ctx.db, ctx.project.id)]}


@router.post("/api/projects/{project_id}/tasks/{task_id}/assign")
async def assign(project_id: str, body: Assignment, ctx: Annotated[Context, Depends(task_context)]):
    ctx.leader()
    require(project_id == ctx.project.id, "任务不属于此项目", 404)
    require(ctx.task.status != TaskStatus.IN_PROGRESS, "请先结束会话，再转交任务")
    require(
        await ctx.db.get(ProjectMember, {"project_id": project_id, "user_id": body.user_id}),
        "负责人必须是项目成员",
        422,
    )
    ctx.task.owner_id = body.user_id
    plan = await latest_plan(ctx.db, project_id)
    if plan:
        data = {**plan.payload, "tasks": [dict(t) for t in plan.payload["tasks"]]}
        for task in data["tasks"]:
            if f"{project_id}_{task['task_id']}" == ctx.task.id:
                task["owner_id"] = body.user_id
        plan.payload = data
    await ctx.db.commit()
    publish_task(ctx.task)
    return task_json(ctx.task)


@router.post("/api/tasks/{task_id}/run")
async def run(body: RunRequest, ctx: Annotated[Context, Depends(task_context)]):
    factory = async_sessionmaker(ctx.db.bind, expire_on_commit=False)
    return await start_run(
        ctx.db, factory, ctx.task, ctx.project, ctx.actor.user_id, body.agent_name, body.context
    )


@router.post("/api/tasks/{task_id}/{action}")
async def control_session(action: str, ctx: Annotated[Context, Depends(task_context)]):
    # 下方更具体的 POST 路由在此之前注册（文件尾调整顺序）。
    require(action in {"pause", "resume", "terminate"}, "未知会话操作", 404)
    try:
        return await control(ctx.db, ctx.task, action)
    except Role2Error as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/api/tasks/{task_id}/{resource}")
async def read_session(resource: str, ctx: Annotated[Context, Depends(task_context)]):
    require(resource in {"status", "logs", "changes", "tests"}, "未知资源", 404)
    row = await latest_run(ctx.db, ctx.task.id)
    data = (
        row.data
        if row
        else {"task_id": ctx.task.id, "status": "pending", "logs": [], "changes": {}}
    )
    if resource == "logs":
        return {"logs": data["logs"]}
    if resource == "changes":
        return {"changes": [data["changes"]] if data.get("changes") else []}
    if resource == "tests":
        return data.get("tests", {"status": "not_run"})
    return {key: value for key, value in data.items() if key not in {"logs", "changes", "tests"}}


@router.post("/api/tasks/{task_id}/commit")
async def commit(body: Commit, ctx: Annotated[Context, Depends(task_context)]):
    return await commit_and_merge(ctx.db, ctx.task, ctx.project, body.message)


@router.post("/api/projects/{project_id}/tasks/{task_id}/merge")
async def merge(project_id: str, body: Commit, ctx: Annotated[Context, Depends(task_context)]):
    ctx.leader()
    require(project_id == ctx.project.id, "任务不属于此项目", 404)
    return await commit_and_merge(ctx.db, ctx.task, ctx.project, body.message, merge=True)


test_locks = {}


@router.post("/api/tasks/{task_id}/tests")
async def run_tests(ctx: Annotated[Context, Depends(task_context)]):
    require(ctx.task.status != TaskStatus.IN_PROGRESS, "请先结束会话，再运行测试")
    workspace = Path(ctx.task.workspace_path or "").resolve()
    root = Path(ctx.project.repo_path).resolve() / ".teamcode" / "worktrees"
    require(workspace.is_dir() and workspace.is_relative_to(root), "请先运行任务生成工作区")
    require((workspace / "tests").is_dir(), "工作区没有 tests 目录，请先提供项目测试", 422)
    lock = test_locks.setdefault(ctx.task.id, asyncio.Lock())
    require(not lock.locked(), "测试正在运行")
    async with lock:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests",
            cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=30)
            status = "passed" if process.returncode == 0 else "failed"
        except TimeoutError:
            process.kill()
            output, _ = await process.communicate()
            status = "timeout"
        result = {
            "status": status,
            "exit_code": process.returncode,
            "output": output.decode("utf-8", errors="replace")[-20000:],
            "ts": utc_now().isoformat(),
            "workspace": str(workspace),
        }
        row = await latest_run(ctx.db, ctx.task.id)
        require(row is not None, "执行记录不存在", 404)
        row.data = {**row.data, "tests": result}
        await ctx.db.commit()
        return result


# 精确命令优先，避免 /commit 与 /tests 被通用 action 路由捕获。
router.routes.sort(key=lambda route: "{action}" in route.path)


frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"


@router.get("/", include_in_schema=False)
async def frontend():
    require((frontend_dist / "index.html").is_file(), "请先在 frontend 执行 npm run build", 503)
    return FileResponse(frontend_dist / "index.html")


@router.get("/assets/{asset}", include_in_schema=False)
async def frontend_asset(asset: str):
    path = (frontend_dist / "assets" / asset).resolve()
    require(path.is_relative_to(frontend_dist.resolve()) and path.is_file(), "资源不存在", 404)
    return FileResponse(path)
