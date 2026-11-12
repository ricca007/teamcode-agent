"""薄接线：A 负责规划；B 负责 Worktree、Adapter、状态机和路径校验。"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload

from app.agent_runtime.cli_adapter import CLIAdapter, CLIAdapterConfig
from app.agent_runtime.execution import ExecutionService
from app.agent_runtime.mock_adapter import MockAdapter
from app.agent_runtime.session_manager import InMemorySessionStore, SessionManager
from app.git_ops.workspace import GitWorkspace, collect_changes, commit_changes
from app.integration.models import PlanSnapshot, RunRecord
from app.interface_registry.service import InterfaceRegistryService
from app.log_stream import LogBroker
from app.manager_agent import create_plan, replan
from app.models.project import ProjectMember
from app.models.task import Task, TaskDependency
from app.models.user import User
from app.realtime.events import make_event
from app.realtime.manager import bus
from app.schemas.core import AgentStatus, ChangeSet, TaskSpec, TaskStatus, task_prompt, utc_now
from app.schemas.planning import PlanningRequest, PlanResult, TeamMemberSpec
from app.security.path_policy import validate_paths


def require(condition, message, code=409):
    if not condition:
        raise HTTPException(code, message)


def git(root, *args):
    result = subprocess.run(
        ["git", "-c", "user.name=TeamCode MVP", "-c", "user.email=mvp@example.invalid", *args],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    require(result.returncode == 0, result.stderr.strip() or result.stdout.strip(), 409)
    return result.stdout.strip()


async def latest_plan(db, project_id):
    return await db.scalar(
        select(PlanSnapshot)
        .where(PlanSnapshot.project_id == project_id)
        .order_by(PlanSnapshot.version.desc())
        .limit(1)
    )


def prepare_repo(repo):
    repo = Path(repo).resolve()
    require(
        Path(git(repo, "rev-parse", "--show-toplevel")).resolve() == repo,
        "请指定 Git 仓库根目录",
        422,
    )
    exclude = Path(git(repo, "rev-parse", "--git-path", "info/exclude"))
    if not exclude.is_absolute():
        exclude = repo / exclude
    content = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    entries = ["/.teamcode/", "__pycache__/", ".pytest_cache/"]
    missing = [entry for entry in entries if entry not in content.splitlines()]
    if missing:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(content + "\n" + "\n".join(missing) + "\n", encoding="utf-8")


async def tasks(db, project_id):
    return list(
        (
            await db.scalars(
                select(Task)
                .where(Task.project_id == project_id)
                .options(selectinload(Task.dependencies))
                .execution_options(populate_existing=True)
                .order_by(Task.priority, Task.id)
            )
        ).all()
    )


def task_json(task):
    return {
        **TaskSpec.model_validate(
            {
                "task_id": task.id,
                "title": task.title,
                "description": task.description,
                "owner_id": task.owner_id,
                "allowed_paths": task.allowed_paths,
                "interface_requirements": task.interface_requirements,
                "acceptance_criteria": task.acceptance_criteria,
                "depends_on": [item.id for item in task.dependencies],
                "priority": task.priority,
            }
        ).model_dump(mode="json"),
        "project_id": task.project_id,
        "status": task.status.value,
        "workspace_path": task.workspace_path,
        "branch_name": task.branch_name,
        "replan_version": task.replan_version,
    }


def publish_task(task):
    bus.publish(make_event("task.updated", task.project_id, task_json(task), task_id=task.id))


async def plan_project(db, project, requirements, mode="plan"):
    require(bool(requirements.strip()), "需求不能为空", 422)
    members = list(
        (
            await db.scalars(select(ProjectMember).where(ProjectMember.project_id == project.id))
        ).all()
    )
    request = PlanningRequest(
        project_id=project.id,
        repo_path=project.repo_path,
        # A 按句子归类；把课堂常用的顿号/逗号需求清单转换为独立条目。
        requirements=requirements.replace("、", "\n").replace("，", "\n"),
        members=[
            TeamMemberSpec(
                member_id=m.user_id,
                name=(await db.get(User, m.user_id)).name,
                areas={"u_a": ["user"], "u_b": ["product"], "u_c": ["order", "coupon"]}.get(
                    m.user_id, []
                ),
            )
            for m in members
        ],
    )
    previous = await latest_plan(db, project.id)
    diff = None
    if previous:
        require(mode == "replan", "已有计划，请使用重规划")
        result = await asyncio.to_thread(
            replan, PlanResult.model_validate(previous.payload), request
        )
        plan, diff = result.plan, result.diff.model_dump(mode="json")
    else:
        plan = await asyncio.to_thread(create_plan, request)
    existing = {t.id: t for t in await tasks(db, project.id)}

    def identity(key):
        return f"{project.id}_{key}"

    changed = {item["task_id"] for item in (diff or {}).get("updated_tasks", [])}
    changed.update(item["task_id"] for item in (diff or {}).get("dependency_changes", []))
    affected = changed | set((diff or {}).get("removed_tasks", []))
    require(
        not any(
            row.status == TaskStatus.IN_PROGRESS
            for key, row in existing.items()
            if key in {identity(raw) for raw in affected}
        ),
        "受影响任务正在执行，请先结束或终止这些会话；未受影响任务可继续运行",
    )
    for planned in plan.tasks:
        task_id = identity(planned.task_id)
        row = existing.get(task_id)
        if row is None:
            row = Task(id=task_id, project_id=project.id)
            db.add(row)
        for key in (
            "title",
            "description",
            "owner_id",
            "allowed_paths",
            "interface_requirements",
            "acceptance_criteria",
            "priority",
        ):
            setattr(row, key, getattr(planned, key))
        if row.status is None or planned.task_id in changed:
            row.status = TaskStatus.PLANNED
        row.replan_version = plan.version
    for removed in (diff or {}).get("removed_tasks", []):
        if identity(removed) in existing:
            existing[identity(removed)].status = TaskStatus.CANCELLED
    await db.flush()
    ids = [identity(t.task_id) for t in plan.tasks]
    await db.execute(delete(TaskDependency).where(TaskDependency.task_id.in_(ids)))
    for t in plan.tasks:
        db.add_all(
            [
                TaskDependency(task_id=identity(t.task_id), depends_on_task_id=identity(d))
                for d in t.depends_on
            ]
        )
    db.add(
        PlanSnapshot(
            project_id=project.id,
            version=plan.version,
            payload=plan.model_dump(mode="json"),
            request={**request.model_dump(mode="json"), "diff": diff},
        )
    )
    await db.commit()
    for task in await tasks(db, project.id):
        publish_task(task)
    return {"plan": plan.model_dump(mode="json"), "version": plan.version, "diff": diff}


async def latest_run(db, task_id):
    return await db.scalar(
        select(RunRecord)
        .where(RunRecord.task_id == task_id)
        .order_by(RunRecord.created_at.desc())
        .limit(1)
    )


class PersistedBroker(LogBroker):
    def __init__(self, factory, run_ids):
        super().__init__()
        self.factory, self.run_ids = factory, run_ids

    async def publish(self, project_id, event):
        async with self.factory() as db:
            run = await db.get(RunRecord, self.run_ids[event["task_id"]])
            log = event["payload"]
            run.data = {
                **run.data,
                "session_id": log["session_id"],
                "logs": [*run.data.get("logs", []), log][-2000:],
            }
            await db.commit()
        bus.publish(event)
        await super().publish(project_id, event)


@dataclass
class Runtime:
    execution: ExecutionService
    store: InMemorySessionStore
    factory: async_sessionmaker
    run_ids: dict
    adapters: dict = field(default_factory=dict)
    background: dict = field(default_factory=dict)


runtimes: dict[str, Runtime] = {}


def runtime_for(project, factory):
    if project.id not in runtimes:
        store, run_ids = InMemorySessionStore(), {}
        broker = PersistedBroker(factory, run_ids)
        execution = ExecutionService(
            Path(project.repo_path),
            SessionManager(store=store, broker=broker),
            leader_id=project.owner_id,
        )
        runtimes[project.id] = Runtime(execution, store, factory, run_ids)
    return runtimes[project.id]


def agent_configs():
    config = json.loads(os.getenv("TEAMCODE_AGENTS", "{}"))
    if os.getenv("TEAMCODE_AGENT_COMMAND"):
        config["cli"] = {
            "command": json.loads(os.environ["TEAMCODE_AGENT_COMMAND"]),
            "prompt_mode": os.getenv("TEAMCODE_AGENT_PROMPT_MODE", "arg"),
        }
    return config


async def start_run(db, factory, task, project, actor_id, agent_name, context=None):
    runtime = runtime_for(project, factory)
    require(task.id not in runtime.background, "任务正在运行")
    spec = TaskSpec.model_validate(task_json(task))
    documentation = await InterfaceRegistryService(db).render_markdown(project.id)
    if agent_name == "mock":
        adapter = MockAdapter(delay=float(os.getenv("TEAMCODE_MOCK_DELAY", "0.4")))
        if context is None:
            target = task.allowed_paths[0].rstrip("/") + "/demo_feature.py"
            context = {"write_files": {target: 'def demo_feature() -> str:\n    return "MVP"\n'}}
    else:
        require(agent_name in agent_configs(), "该 Coding Agent 尚未配置", 422)
        config = agent_configs()[agent_name]
        command = list(config["command"])
        mode = config.get("prompt_mode", "stdin")
        # 当前 B 的 arg 模式未追加 prompt；在 C 的配置接线中补齐，不改 B 源码。
        if mode == "arg":
            command.append(task_prompt(spec, documentation))
        adapter = CLIAdapter(
            CLIAdapterConfig(
                command=tuple(command),
                prompt_mode=mode,
                timeout=config.get("timeout", 300),
            )
        )
    run = RunRecord(
        id="run_" + uuid4().hex[:16],
        task_id=task.id,
        project_id=project.id,
        data={
            "task_id": task.id,
            "status": "running",
            "adapter": agent_name,
            "logs": [],
            "started_at": utc_now().isoformat(),
            "changes": {"files": [], "diff": ""},
        },
    )
    task.status = TaskStatus.IN_PROGRESS
    db.add(run)
    await db.commit()
    runtime.adapters[task.id] = adapter
    runtime.run_ids[task.id] = run.id
    runtime.background[task.id] = asyncio.create_task(
        execute(runtime, project.id, spec, actor_id, adapter, context, documentation)
    )
    publish_task(task)
    return run.data


async def execute(runtime, project_id, spec, actor_id, adapter, context, documentation):
    result, error = None, None
    try:
        result = await runtime.execution.run(
            project_id,
            spec,
            actor_id,
            adapter=adapter,
            prompt=task_prompt(spec, documentation),
            context=context,
        )
        # 某些 CLI 会自行 commit；把它们的分支变更也交给 B 的公开路径策略校验。
        committed = (
            await asyncio.to_thread(
                git, result.workspace, "diff", "--name-only", "-z", "main...HEAD"
            )
        ).split("\0")
        committed = [name for name in committed if name]
        if committed:
            validation = validate_paths(Path(result.workspace), committed, spec.allowed_paths)
            diff = await asyncio.to_thread(git, result.workspace, "diff", "main...HEAD")
            commit_hash = await asyncio.to_thread(git, result.workspace, "rev-parse", "HEAD")
            result = result.model_copy(
                update={
                    "changes": ChangeSet(
                        files=sorted(set(committed) | set(result.changes.files)),
                        diff=diff + "\n" + result.changes.diff,
                        commit_hash=commit_hash,
                    ),
                    "status": AgentStatus.FAILED if validation.rejected else result.status,
                    "rejected_paths": [name for name, _ in validation.rejected],
                }
            )
    except Exception as exc:
        error = str(exc)
    finally:
        async with runtime.factory() as db:
            row = await db.get(RunRecord, runtime.run_ids[spec.task_id])
            row.data = {
                **row.data,
                **(result.as_dict() if result else {"status": "failed"}),
                "ended_at": utc_now().isoformat(),
                "error": error,
            }
            task = next(t for t in await tasks(db, project_id) if t.id == spec.task_id)
            task.status = {
                "succeeded": TaskStatus.COMPLETED,
                "terminated": TaskStatus.CANCELLED,
            }.get(row.data["status"], TaskStatus.BLOCKED)
            if result:
                task.workspace_path = result.workspace
                task.branch_name = await asyncio.to_thread(
                    git, result.workspace, "branch", "--show-current"
                )
            await db.commit()
            publish_task(task)
            bus.publish(
                make_event("code.changed", project_id, row.data["changes"], task_id=task.id)
            )
        runtime.background.pop(spec.task_id, None)


async def control(db, task, action):
    runtime = runtimes.get(task.project_id)
    require(runtime is not None and task.id in runtime.background, "没有可控制的活跃会话")
    info = next(
        (i for i in reversed(list(runtime.store.sessions.values())) if i.task_id == task.id), None
    )
    require(info is not None, "工作区正在创建，请稍后重试")
    # Adapter 是 B 的公开控制入口；避免等待 send_task 持有的 SessionManager 长锁。
    adapter = runtime.adapters[task.id]
    await getattr(adapter, action)(info.session_id)
    row = await latest_run(db, task.id)
    row.data = {**row.data, "status": (await adapter.get_status(info.session_id)).value}
    await db.commit()
    publish_task(task)
    return row.data


async def commit_and_merge(db, task, project, message, merge=False):
    require(task.status == TaskStatus.COMPLETED, "仅成功结束的任务可以提交或合并")
    require(task.workspace_path, "任务没有工作区")
    if merge:
        require(
            not git(project.repo_path, "status", "--porcelain"), "主仓库存在未提交改动，请先处理"
        )
        require(
            git(project.repo_path, "branch", "--show-current") == "main", "请先将主仓库切回 main"
        )
    workspace = GitWorkspace(
        project_id=project.id,
        task_id=task.id,
        root=Path(project.repo_path),
        worktree_path=Path(task.workspace_path),
        branch_name=task.branch_name,
        base_branch="main",
    )
    changes = await asyncio.to_thread(collect_changes, workspace.worktree_path)
    row = await latest_run(db, task.id)
    if changes.files:
        commit = await asyncio.to_thread(commit_changes, workspace, task.allowed_paths, message)
    else:
        require(row and row.data["changes"].get("commit_hash"), "没有可提交的变更")
        commit = row.data["changes"]["commit_hash"]
    # 再检查整个分支，包括 Coding Agent 自己提交过的文件，仍使用 B 的路径策略。
    branch_files = git(task.workspace_path, "diff", "--name-only", "-z", "main...HEAD").split("\0")
    validation = validate_paths(
        Path(task.workspace_path), [f for f in branch_files if f], task.allowed_paths
    )
    require(not validation.rejected, "分支中存在超出任务范围的已提交文件", 403)
    if merge:
        try:
            await asyncio.to_thread(
                git, project.repo_path, "merge", "--no-ff", "--no-edit", task.branch_name
            )
        except HTTPException:
            await asyncio.to_thread(git, project.repo_path, "merge", "--abort")
            raise
        await InterfaceRegistryService(db).scan(project.id, project.repo_path)
        bus.publish(make_event("interface.updated", project.id, {"merged_task": task.id}))
    row.data = {
        **row.data,
        "changes": {**row.data["changes"], "commit_hash": commit},
        "merged": merge or row.data.get("merged", False),
    }
    await db.commit()
    bus.publish(make_event("code.changed", project.id, row.data["changes"], task_id=task.id))
    return {"commit_hash": commit, "merged": merge}


async def shutdown_runtimes():
    for runtime in list(runtimes.values()):
        for task_id, adapter in list(runtime.adapters.items()):
            if task_id not in runtime.background:
                continue
            info = next(
                (
                    i
                    for i in reversed(list(runtime.store.sessions.values()))
                    if i.task_id == task_id
                ),
                None,
            )
            if info and not (await adapter.get_status(info.session_id)).terminal:
                await adapter.terminate(info.session_id)
        pending = list(runtime.background.values())
        if pending:
            await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=10)
        await runtime.execution.shutdown()
    runtimes.clear()
