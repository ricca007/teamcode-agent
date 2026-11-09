"""A/B/C 整合服务。

职责边界：
- A：调用 ``create_plan`` / ``replan``，把 PlannedTask 落库为 tasks /
  task_dependencies，并把每次计划保存为 PlanSnapshot；
- B：使用 Agent Runtime 的公开原语（create_workspace / SessionManager /
  validate_paths / commit_changes）执行任务，把会话、日志、变更写入数据库；
- C：把 task.updated / agent.log / code.changed 推送到统一的 WebSocket 总线。

设计取舍：
- 不修改 A/B 的业务代码，只在整合层做编排与持久化；
- 运行时状态（活跃会话、后台任务）保存在进程内；进程重启后，
  历史会话仍可从数据库读取，但无法再 pause/terminate；
- 默认使用 MockAdapter，设置 ``TEAMCODE_AGENT_COMMAND`` 后可切换到 CLI 适配器。
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.agent_runtime.cli_adapter import CLIAdapter, CLIAdapterConfig
from app.agent_runtime.mock_adapter import MockAdapter
from app.agent_runtime.session_manager import SessionManager
from app.git_ops.workspace import collect_changes, commit_changes, create_workspace
from app.integration.agents import agent_specs, generic_wrapper_path
from app.integration.auth import (
    Actor,
    auth_required,
    derive_join_token,
    hash_password,
    hash_secret,
    issue_session,
    verify_password,
)
from app.integration.models import (
    ApiKey,
    AuthSession,
    JoinRequest,
    PlanSnapshot,
    UserCredential,
)
from app.integration.schemas import (
    ApiKeyCreate,
    ApproveJoinRequest,
    AssignTaskRequest,
    CommitRequest,
    JoinRequestCreate,
    JoinTeamRequest,
    LoginRequest,
    MemberCreateRequest,
    MergeTaskRequest,
    MessageRequest,
    ProjectCreateRequest,
    RegisterRequest,
    RequirementsRequest,
    RunRequest,
)
from app.manager_agent import create_plan, replan
from app.models.project import Project, ProjectMember
from app.models.runtime import AgentLog as AgentLogModel
from app.models.runtime import AgentSession as AgentSessionModel
from app.models.runtime import CodeChange as CodeChangeModel
from app.models.task import Task, TaskDependency
from app.models.user import User
from app.realtime.events import make_event
from app.realtime.manager import bus
from app.schemas.core import (
    AgentStatus,
    ChangeSet,
    GitWorkspace,
    ProjectRole,
    TaskSpec,
    TaskStatus,
    UserRole,
    task_prompt,
    utc_now,
)
from app.schemas.planning import PlanningRequest, PlanResult, TeamMemberSpec
from app.security.path_policy import validate_paths

logger = logging.getLogger(__name__)


class IntegrationError(Exception):
    """整合层可预期错误，由 API 转成结构化响应。"""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass
class ProjectRuntime:
    project_id: str
    repo_root: Path
    sessions: SessionManager = field(default_factory=SessionManager)
    active_tasks: set[str] = field(default_factory=set)
    background: dict[str, asyncio.Task] = field(default_factory=dict)
    # 活跃会话的 adapter，供 pause/resume/terminate 直接控制，
    # 绕过 SessionManager.send_task 的长锁
    adapters: dict[str, Any] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_runtimes: dict[str, ProjectRuntime] = {}


async def shutdown_runtimes() -> None:
    """测试/退出时关闭所有运行时。"""
    for runtime in list(_runtimes.values()):
        try:
            await runtime.sessions.shutdown()
        except Exception:
            logger.exception("关闭项目运行时失败: project=%s", runtime.project_id)
    _runtimes.clear()


class IntegrationService:
    def __init__(
        self,
        db: AsyncSession,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.db = db
        self.session_factory = session_factory

    # ------------------------------------------------------------------
    # 全局账号
    # ------------------------------------------------------------------
    async def register(self, request: RegisterRequest) -> dict[str, Any]:
        email = request.email.strip().lower()
        if await self.db.scalar(
            select(UserCredential).where(UserCredential.email == email)
        ):
            raise IntegrationError("email_taken", "该邮箱已注册", 409)
        if await self.db.scalar(select(User).where(User.email == email)):
            raise IntegrationError("email_taken", "该邮箱已被使用", 409)

        user = User(
            id=f"u_{uuid4().hex[:10]}",
            name=request.name.strip(),
            email=email,
            role=UserRole.MEMBER,
        )
        self.db.add(user)
        await self.db.flush()
        self.db.add(
            UserCredential(
                user_id=user.id,
                email=email,
                password_hash=hash_password(request.password),
            )
        )
        _, token = issue_session(self.db, user_id=user.id)
        await self.db.commit()
        logger.info("注册账号: user=%s email=%s", user.id, email)
        return {
            "token": token,
            "user": {"id": user.id, "name": user.name, "email": email},
        }

    async def login(self, request: LoginRequest) -> dict[str, Any]:
        email = request.email.strip().lower()
        credential = await self.db.scalar(
            select(UserCredential).where(UserCredential.email == email)
        )
        if credential is None or not verify_password(
            request.password, credential.password_hash
        ):
            raise IntegrationError("invalid_credentials", "邮箱或密码错误", 401)
        user = await self.db.get(User, credential.user_id)
        if user is None:
            raise IntegrationError("invalid_credentials", "账号不存在", 401)
        _, token = issue_session(self.db, user_id=user.id)
        await self.db.commit()
        logger.info("登录成功: user=%s", user.id)
        return {
            "token": token,
            "user": {"id": user.id, "name": user.name, "email": user.email},
        }

    async def create_api_key(
        self, request: ApiKeyCreate, actor: Actor | None
    ) -> dict[str, Any]:
        if actor is None:
            raise IntegrationError("actor_required", "请先注册/登录", 401)
        if request.project_id:
            await self._require_project_access(request.project_id, actor)
        raw = "tcak_" + secrets.token_urlsafe(32)
        key = ApiKey(
            id=f"key_{uuid4().hex[:12]}",
            user_id=actor.user_id,
            project_id=request.project_id,
            name=request.name,
            key_hash=hash_secret(raw),
            prefix=raw[:16],
        )
        self.db.add(key)
        await self.db.commit()
        return {
            "id": key.id,
            "name": key.name,
            "prefix": key.prefix,
            "project_id": key.project_id,
            "raw_key": raw,
            "created_at": key.created_at.isoformat(),
        }

    async def list_api_keys(
        self, actor: Actor | None
    ) -> list[dict[str, Any]]:
        if actor is None:
            raise IntegrationError("actor_required", "请先注册/登录", 401)
        rows = (
            await self.db.scalars(
                select(ApiKey)
                .where(ApiKey.user_id == actor.user_id)
                .order_by(ApiKey.created_at.desc())
            )
        ).all()
        return [
            {
                "id": row.id,
                "name": row.name,
                "prefix": row.prefix,
                "project_id": row.project_id,
                "created_at": row.created_at.isoformat(),
                "last_used_at": row.last_used_at.isoformat()
                if row.last_used_at
                else None,
                "revoked": row.revoked,
            }
            for row in rows
        ]

    async def revoke_api_key(
        self, key_id: str, actor: Actor | None
    ) -> dict[str, Any]:
        if actor is None:
            raise IntegrationError("actor_required", "请先注册/登录", 401)
        key = await self.db.get(ApiKey, key_id)
        if key is None or key.user_id != actor.user_id:
            raise IntegrationError("api_key_not_found", "API Key 不存在", 404)
        key.revoked = True
        await self.db.commit()
        return {"id": key.id, "revoked": True}

    async def list_my_projects(
        self, actor: Actor | None
    ) -> list[dict[str, Any]]:
        if actor is None:
            if auth_required():
                raise IntegrationError(
                    "actor_required", "请先注册/登录", 401
                )
            return []
        rows = (
            await self.db.execute(
                select(Project, ProjectMember)
                .join(ProjectMember, ProjectMember.project_id == Project.id)
                .where(ProjectMember.user_id == actor.user_id)
                .order_by(Project.created_at)
            )
        ).all()
        return [
            {
                "id": project.id,
                "name": project.name,
                "repo_path": project.repo_path,
                "role": "leader"
                if member.role == ProjectRole.OWNER
                else "member",
            }
            for project, member in rows
        ]

    # ------------------------------------------------------------------
    # 项目与成员
    # ------------------------------------------------------------------
    async def create_project(
        self,
        request: ProjectCreateRequest,
        actor: Actor | None = None,
    ) -> dict[str, Any]:
        root = Path(request.repo_path).expanduser().resolve()
        if not root.is_dir():
            raise IntegrationError(
                "invalid_repo_path", f"仓库目录不存在: {root}", 422
            )
        if not (root / ".git").exists():
            raise IntegrationError(
                "repository_not_git",
                "repo_path 必须是 Git 仓库（Agent Worktree 依赖 Git）",
                422,
            )

        if actor is not None:
            owner = await self._ensure_user(
                actor.user_id,
                name=actor.name,
            )
        else:
            if auth_required():
                raise IntegrationError(
                    "actor_required", "请先注册/登录后再创建团队", 401
                )
            owner_id = (request.owner_id or "u_local").strip()
            owner = await self._ensure_user(
                owner_id,
                name=request.owner_name or "Local Leader",
                email=request.owner_email or f"{owner_id}@teamcode.invalid",
                role=UserRole.LEADER,
            )
        project = Project(
            **(  # 允许演示脚本指定稳定 ID
                {"id": request.project_id} if request.project_id else {}
            ),
            name=request.name,
            owner_id=owner.id,
            repo_path=str(root),
        )
        self.db.add(project)
        await self.db.flush()
        self.db.add(
            ProjectMember(
                project_id=project.id,
                user_id=owner.id,
                role=ProjectRole.OWNER,
            )
        )
        await self.db.commit()
        await self.db.refresh(project)
        logger.info("创建项目: project=%s repo=%s owner=%s", project.id, root, owner.id)
        return {
            "id": project.id,
            "name": project.name,
            "repo_path": project.repo_path,
            "owner_id": project.owner_id,
            "role": "leader",
            "created_at": project.created_at.isoformat(),
        }

    async def add_member(
        self,
        project_id: str,
        request: MemberCreateRequest,
        actor: Actor | None = None,
    ) -> dict[str, Any]:
        await self._require_leader(project_id, actor)
        project = await self._get_project(project_id)
        user = await self._ensure_user(
            request.user_id,
            name=request.name or request.user_id,
            email=request.email or f"{request.user_id}@teamcode.invalid",
        )
        member = await self.db.get(
            ProjectMember, {"project_id": project.id, "user_id": user.id}
        )
        if member is None:
            member = ProjectMember(
                project_id=project.id,
                user_id=user.id,
                role=request.role,
            )
            self.db.add(member)
        else:
            member.role = request.role
        await self.db.commit()
        logger.info(
            "添加项目成员: project=%s user=%s role=%s",
            project.id,
            user.id,
            request.role.value,
        )
        return {
            "project_id": project.id,
            "user_id": user.id,
            "name": user.name,
            "role": request.role.value,
        }

    async def list_members(
        self, project_id: str, actor: Actor | None = None
    ) -> list[dict[str, Any]]:
        await self._require_project_access(project_id, actor)
        rows = (
            await self.db.execute(
                select(ProjectMember, User)
                .join(User, User.id == ProjectMember.user_id)
                .where(ProjectMember.project_id == project_id)
                .order_by(ProjectMember.created_at)
            )
        ).all()
        return [
            {
                "project_id": member.project_id,
                "user_id": user.id,
                "name": user.name,
                "email": user.email,
                "role": member.role.value,
            }
            for member, user in rows
        ]

    # ------------------------------------------------------------------
    # 加入团队与队长审批
    # ------------------------------------------------------------------
    async def request_join(
        self,
        project_id: str,
        request: JoinTeamRequest,
        actor: Actor | None,
    ) -> dict[str, Any]:
        if actor is None:
            raise IntegrationError("actor_required", "请先注册/登录", 401)
        await self._get_project(project_id)
        member = await self.db.get(
            ProjectMember,
            {"project_id": project_id, "user_id": actor.user_id},
        )
        if member is not None:
            return {
                "request_id": None,
                "project_id": project_id,
                "status": "already_member",
                "display_name": actor.name,
            }

        row = await self.db.scalar(
            select(JoinRequest)
            .where(
                JoinRequest.project_id == project_id,
                JoinRequest.user_id == actor.user_id,
                JoinRequest.status == "pending",
            )
            .order_by(JoinRequest.created_at.desc())
            .limit(1)
        )
        if row is None:
            row = JoinRequest(
                id=f"join_{uuid4().hex[:16]}",
                project_id=project_id,
                device_id="",
                device_secret_hash="",
                display_name=actor.name,
                areas=list(request.areas),
                status="pending",
                user_id=actor.user_id,
            )
            self.db.add(row)
            await self.db.commit()
            await self.db.refresh(row)
        logger.info(
            "账号申请加入: project=%s user=%s request=%s",
            project_id,
            actor.user_id,
            row.id,
        )
        return {
            "request_id": row.id,
            "project_id": project_id,
            "status": row.status,
            "display_name": actor.name,
        }

    async def list_my_join_requests(
        self, actor: Actor | None
    ) -> list[dict[str, Any]]:
        if actor is None:
            if auth_required():
                raise IntegrationError("actor_required", "请先注册/登录", 401)
            return []
        rows = (
            await self.db.execute(
                select(JoinRequest, Project)
                .join(Project, Project.id == JoinRequest.project_id)
                .where(JoinRequest.user_id == actor.user_id)
                .order_by(JoinRequest.created_at.desc())
            )
        ).all()
        return [
            {
                "request_id": row.id,
                "project_id": row.project_id,
                "project_name": project.name,
                "status": row.status,
                "areas": list(row.areas or []),
                "created_at": row.created_at.isoformat(),
            }
            for row, project in rows
        ]

    async def create_join_request(self, request: JoinRequestCreate) -> dict[str, Any]:
        project = await self._get_project(request.project_id)
        secret_hash = hash_secret(request.device_secret)
        existing = await self.db.scalar(
            select(JoinRequest)
            .where(
                JoinRequest.project_id == project.id,
                JoinRequest.device_id == request.device_id,
                JoinRequest.status == "pending",
            )
            .order_by(JoinRequest.created_at.desc())
            .limit(1)
        )
        if existing is not None:
            existing.display_name = request.display_name
            existing.device_secret_hash = secret_hash
            row = existing
        else:
            row = JoinRequest(
                id=f"join_{uuid4().hex[:16]}",
                project_id=project.id,
                device_id=request.device_id,
                device_secret_hash=secret_hash,
                display_name=request.display_name,
                areas=[],
                status="pending",
            )
            self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        logger.info(
            "收到加入申请: project=%s device=%s request=%s",
            project.id,
            request.device_id,
            row.id,
        )
        return {
            "request_id": row.id,
            "project_id": row.project_id,
            "status": row.status,
            "display_name": row.display_name,
        }

    async def get_join_status(
        self, request_id: str, device_secret: str
    ) -> dict[str, Any]:
        row = await self.db.get(JoinRequest, request_id)
        if row is None or not hmac.compare_digest(
            row.device_secret_hash, hash_secret(device_secret)
        ):
            raise IntegrationError(
                "join_request_not_found", "加入申请不存在或设备凭据不匹配", 404
            )
        result: dict[str, Any] = {
            "request_id": row.id,
            "project_id": row.project_id,
            "status": row.status,
            "display_name": row.display_name,
            "user_id": row.user_id,
            "role": "member" if row.status == "approved" else None,
        }
        if row.status == "approved" and row.user_id:
            token = derive_join_token(row.id, device_secret)
            session = await self.db.scalar(
                select(AuthSession).where(
                    AuthSession.token_hash == hash_secret(token)
                )
            )
            if session is None:
                issue_session(
                    self.db,
                    user_id=row.user_id,
                    project_id=row.project_id,
                    role="member",
                    token=token,
                    device_id=row.device_id,
                )
                await self.db.commit()
            result["token"] = token
        return result

    async def list_join_requests(
        self, project_id: str, actor: Actor | None = None
    ) -> list[dict[str, Any]]:
        await self._require_leader(project_id, actor)
        rows = (
            await self.db.scalars(
                select(JoinRequest)
                .where(JoinRequest.project_id == project_id)
                .order_by(JoinRequest.created_at.desc())
            )
        ).all()
        return [
            {
                "request_id": row.id,
                "project_id": row.project_id,
                "device_id": row.device_id,
                "display_name": row.display_name,
                "areas": list(row.areas or []),
                "status": row.status,
                "user_id": row.user_id,
                "decided_by": row.decided_by,
                "created_at": row.created_at.isoformat(),
                "decided_at": row.decided_at.isoformat()
                if row.decided_at
                else None,
            }
            for row in rows
        ]

    async def approve_join_request(
        self,
        project_id: str,
        request_id: str,
        request: ApproveJoinRequest,
        actor: Actor | None = None,
    ) -> dict[str, Any]:
        leader = await self._require_leader(project_id, actor)
        row = await self.db.get(JoinRequest, request_id)
        if row is None or row.project_id != project_id:
            raise IntegrationError("join_request_not_found", "加入申请不存在", 404)
        if row.status != "pending":
            raise IntegrationError("join_request_closed", "该申请已处理", 409)

        if row.user_id:
            user = await self.db.get(User, row.user_id)
            if user is None:
                raise IntegrationError("user_not_found", "申请账号不存在", 404)
            user_id = user.id
        else:
            # 兼容旧的设备加入申请：没有账号时创建一个
            user_id = f"u_{uuid4().hex[:10]}"
            self.db.add(
                User(
                    id=user_id,
                    name=row.display_name,
                    email=f"{user_id}@teamcode.invalid",
                    role=UserRole.MEMBER,
                )
            )
            await self.db.flush()
        await self._ensure_project_member(project_id, user_id, ProjectRole.MEMBER)
        row.status = "approved"
        row.user_id = user_id
        row.areas = list(request.areas)
        row.decided_by = leader.user_id if leader is not None else "leader"
        row.decided_at = utc_now()
        await self.db.commit()
        logger.info(
            "批准加入申请: project=%s request=%s user=%s areas=%s",
            project_id,
            request_id,
            user_id,
            row.areas,
        )
        return {
            "request_id": row.id,
            "status": row.status,
            "user_id": user_id,
            "areas": list(row.areas or []),
        }

    async def reject_join_request(
        self,
        project_id: str,
        request_id: str,
        actor: Actor | None = None,
    ) -> dict[str, Any]:
        leader = await self._require_leader(project_id, actor)
        row = await self.db.get(JoinRequest, request_id)
        if row is None or row.project_id != project_id:
            raise IntegrationError("join_request_not_found", "加入申请不存在", 404)
        if row.status != "pending":
            raise IntegrationError("join_request_closed", "该申请已处理", 409)
        row.status = "rejected"
        row.decided_by = leader.user_id if leader is not None else "leader"
        row.decided_at = utc_now()
        await self.db.commit()
        return {"request_id": row.id, "status": row.status}

    # ------------------------------------------------------------------
    # A：规划 / 重规划
    # ------------------------------------------------------------------
    async def plan_project(
        self,
        project_id: str,
        request: RequirementsRequest,
        actor: Actor | None = None,
    ) -> dict[str, Any]:
        await self._require_leader(project_id, actor)
        project = await self._get_project(project_id)
        members = await self._member_specs(
            project_id, request.members, request.roles
        )
        planning_request = PlanningRequest(
            project_id=project.id,
            requirements=request.requirements,
            repo_path=project.repo_path,
            members=members,
            max_tasks=request.max_tasks,
        )

        diff: dict[str, Any] | None = None
        try:
            if request.mode == "replan":
                previous = await self._latest_plan(project_id)
                if previous is None:
                    raise IntegrationError(
                        "plan_not_found", "没有可重规划的旧计划", 404
                    )
                result = await asyncio.to_thread(
                    replan, previous, planning_request
                )
                plan = result.plan
                diff = result.diff.model_dump(mode="json")
            else:
                plan = await asyncio.to_thread(create_plan, planning_request)
        except IntegrationError:
            raise
        except Exception as exc:
            logger.exception("规划失败: project=%s mode=%s", project_id, request.mode)
            raise IntegrationError(
                "planning_failed", f"规划失败: {exc}", 500
            ) from exc

        for task in plan.tasks:
            await self._ensure_user(task.owner_id)
        await self._store_plan(project_id, plan, planning_request)
        await self._sync_tasks(project, plan)
        await self.db.commit()

        tasks = await self.list_tasks(project_id, actor)
        for task in tasks:
            self._publish_task(task)

        logger.info(
            "规划完成: project=%s mode=%s version=%d tasks=%d",
            project_id,
            request.mode,
            plan.version,
            len(plan.tasks),
        )
        return {
            "project_id": project_id,
            "version": plan.version,
            "plan": plan.model_dump(mode="json"),
            "diff": diff,
        }

    async def get_plan(
        self, project_id: str, actor: Actor | None = None
    ) -> dict[str, Any] | None:
        await self._require_project_access(project_id, actor)
        plan = await self._latest_plan(project_id)
        if plan is None:
            return None
        return {
            "project_id": project_id,
            "version": plan.version,
            "plan": plan.model_dump(mode="json"),
        }

    async def list_tasks(
        self, project_id: str, actor: Actor | None = None
    ) -> list[dict[str, Any]]:
        _, role = await self._require_project_access(project_id, actor)
        query = (
            select(Task)
            .where(Task.project_id == project_id)
            .options(selectinload(Task.dependencies))
            .order_by(Task.created_at, Task.id)
        )
        if role != "leader" and actor is not None:
            query = query.where(Task.owner_id == actor.user_id)
        tasks = (await self.db.scalars(query)).all()
        users = await self._users_for([task.owner_id for task in tasks])
        return [self._task_dict(task, users.get(task.owner_id)) for task in tasks]

    # ------------------------------------------------------------------
    # B：任务执行
    # ------------------------------------------------------------------
    async def run_task(
        self,
        task_or_session_id: str,
        request: RunRequest,
        actor: Actor | None = None,
    ) -> dict[str, Any]:
        task = await self._load_task(task_or_session_id)
        project = await self._get_project(task.project_id)
        actor_id = await self._authorize(task, project, request.actor_id, actor)

        runtime = self._runtime_for(project)
        async with runtime.lock:
            if task.id in runtime.active_tasks:
                raise IntegrationError(
                    "task_already_running",
                    f"任务 {task.id} 正在运行",
                    409,
                )
            runtime.active_tasks.add(task.id)

        try:
            task_spec = TaskSpec(
                task_id=task.id,
                title=task.title,
                description=task.description,
                owner_id=task.owner_id,
                allowed_paths=list(task.allowed_paths or []),
                interface_requirements=list(task.interface_requirements or []),
                depends_on=[dep.id for dep in task.dependencies],
                acceptance_criteria=list(task.acceptance_criteria or []),
                priority=task.priority,
                base_branch=request.base_branch or "main",
            )
            adapter = self._build_adapter(
                request.agent_name, request.adapter_name
            )
            context = request.context
            if context is None and adapter.name == "mock":
                context = {"write_files": self._mock_writes(task_spec)}
            interface_doc = await self._render_interfaces(project.id)

            workspace = await asyncio.to_thread(
                create_workspace,
                project.id,
                task.id,
                Path(project.repo_path),
                task_spec.base_branch,
            )
            info = await runtime.sessions.start_session(
                project_id=project.id,
                task=task_spec,
                workspace=workspace.worktree_path,
                adapter=adapter,
            )
        except IntegrationError:
            runtime.active_tasks.discard(task.id)
            raise
        except Exception as exc:
            runtime.active_tasks.discard(task.id)
            logger.exception("启动任务失败: project=%s task=%s", project.id, task.id)
            raise IntegrationError(
                "execution_start_failed", f"启动任务失败: {exc}", 400
            ) from exc

        runtime.adapters[info.session_id] = adapter
        self.db.add(
            AgentSessionModel(
                id=info.session_id,
                task_id=task.id,
                adapter=info.adapter,
                status=info.status,
                workspace=str(workspace.worktree_path),
                started_at=info.started_at,
                ended_at=info.ended_at,
            )
        )
        task.status = TaskStatus.IN_PROGRESS
        task.workspace_path = str(workspace.worktree_path)
        task.branch_name = workspace.branch_name
        await self.db.commit()

        users = await self._users_for([task.owner_id])
        self._publish_task(
            self._task_dict(task, users.get(task.owner_id)), actor=actor_id
        )

        background = asyncio.create_task(
            self._execute(
                project_id=project.id,
                task_id=task.id,
                task_spec=task_spec,
                workspace=workspace,
                session_id=info.session_id,
                prompt=request.prompt,
                context=context,
                interface_doc=interface_doc,
                runtime=runtime,
            )
        )
        runtime.background[task.id] = background
        background.add_done_callback(
            lambda finished, task_id=task.id: self._on_background_done(
                runtime, task_id, finished
            )
        )

        logger.info(
            "任务已启动: project=%s task=%s session=%s adapter=%s",
            project.id,
            task.id,
            info.session_id,
            info.adapter,
        )
        return {
            "session_id": info.session_id,
            "task_id": task.id,
            "project_id": project.id,
            "status": info.status.value,
            "workspace": str(workspace.worktree_path),
        }

    async def control_task(
        self,
        task_or_session_id: str,
        action: str,
        actor_id: str | None,
        actor: Actor | None = None,
    ) -> dict[str, Any]:
        if action not in {"pause", "resume", "terminate"}:
            raise IntegrationError("invalid_action", f"不支持的操作: {action}", 400)
        task = await self._load_task(task_or_session_id)
        project = await self._get_project(task.project_id)
        await self._authorize(task, project, actor_id, actor)

        session = await self._latest_session(task.id)
        if session is None:
            raise IntegrationError(
                "session_not_found", "任务还没有运行记录", 404
            )
        runtime = _runtimes.get(project.id)
        if runtime is None:
            raise IntegrationError(
                "runtime_restarted",
                "会话运行时已重启，无法控制历史会话，请重新运行任务",
                409,
            )

        try:
            adapter = runtime.adapters.get(session.id)
            if adapter is not None:
                # 直接控制 adapter，避免 SessionManager 的 send_task 长锁
                if action == "pause":
                    await adapter.pause(session.id)
                elif action == "resume":
                    await adapter.resume(session.id)
                else:
                    await adapter.terminate(session.id)
                status = await adapter.get_status(session.id)
            else:
                status = await getattr(runtime.sessions, action)(session.id)
        except Exception as exc:
            logger.exception(
                "控制会话失败: project=%s task=%s action=%s",
                project.id,
                task.id,
                action,
            )
            raise IntegrationError(
                "session_control_failed", f"{action} 失败: {exc}", 409
            ) from exc

        session.status = status
        if status.terminal:
            session.ended_at = utc_now()
            task.status = self._task_status_for(status)
        else:
            task.status = TaskStatus.IN_PROGRESS
        await self.db.commit()

        users = await self._users_for([task.owner_id])
        self._publish_task(
            self._task_dict(task, users.get(task.owner_id))
        )
        return {
            "task_id": task.id,
            "session_id": session.id,
            "status": status.value,
        }

    async def task_status_dict(
        self, task_or_session_id: str, actor: Actor | None = None
    ) -> dict[str, Any]:
        task = await self._load_task(task_or_session_id)
        await self._require_task_read(task, actor)
        session = await self._latest_session(task.id)
        if session is None:
            raise IntegrationError("session_not_found", "任务还没有运行记录", 404)
        return {
            "session_id": session.id,
            "task_id": task.id,
            "adapter": session.adapter,
            "status": session.status.value,
            "workspace": session.workspace,
            "started_at": session.started_at.isoformat(),
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        }

    async def task_logs(
        self, task_or_session_id: str, actor: Actor | None = None
    ) -> list[dict[str, Any]]:
        task = await self._load_task(task_or_session_id)
        await self._require_task_read(task, actor)
        session = await self._latest_session(task.id)
        if session is None:
            return []
        rows = (
            await self.db.scalars(
                select(AgentLogModel)
                .where(AgentLogModel.session_id == session.id)
                .order_by(AgentLogModel.ts, AgentLogModel.id)
            )
        ).all()
        return [
            {
                "id": row.id,
                "session_id": row.session_id,
                "task_id": task.id,
                "ts": row.ts.isoformat(),
                "level": row.level,
                "message": row.message,
                "sequence": index,
            }
            for index, row in enumerate(rows)
        ]

    async def task_changes(
        self, task_or_session_id: str, actor: Actor | None = None
    ) -> list[dict[str, Any]]:
        task = await self._load_task(task_or_session_id)
        await self._require_task_read(task, actor)
        rows = (
            await self.db.scalars(
                select(CodeChangeModel)
                .where(CodeChangeModel.task_id == task.id)
                .order_by(CodeChangeModel.id)
            )
        ).all()
        sessions = {
            session.id: session
            for session in (
                await self.db.scalars(
                    select(AgentSessionModel).where(
                        AgentSessionModel.id.in_(
                            [row.session_id for row in rows] or [""]
                        )
                    )
                )
            ).all()
        }
        return [
            {
                "id": row.id,
                "task_id": row.task_id,
                "files": list(row.files or []),
                "diff": row.diff,
                "commit_hash": row.commit_hash,
                "ts": (
                    sessions[row.session_id].ended_at
                    or sessions[row.session_id].started_at
                ).isoformat()
                if row.session_id in sessions
                else utc_now().isoformat(),
            }
            for row in rows
        ]

    async def commit_task(
        self,
        task_or_session_id: str,
        request: CommitRequest,
        actor: Actor | None = None,
    ) -> dict[str, Any]:
        task = await self._load_task(task_or_session_id)
        project = await self._get_project(task.project_id)
        await self._authorize(task, project, request.actor_id, actor)
        session = await self._latest_session(task.id)
        if session is None:
            raise IntegrationError("session_not_found", "任务还没有运行记录", 404)

        workspace = GitWorkspace(
            project_id=project.id,
            task_id=task.id,
            root=Path(project.repo_path),
            worktree_path=Path(session.workspace),
            branch_name=task.branch_name or f"teamcode/{task.id}",
        )
        try:
            commit_hash = await asyncio.to_thread(
                commit_changes,
                workspace,
                list(task.allowed_paths or []),
                request.message,
            )
        except Exception as exc:
            logger.exception("提交任务变更失败: project=%s task=%s", project.id, task.id)
            raise IntegrationError(
                "commit_failed", f"提交失败: {exc}", 400
            ) from exc

        change = await self.db.scalar(
            select(CodeChangeModel)
            .where(CodeChangeModel.task_id == task.id)
            .order_by(CodeChangeModel.id.desc())
            .limit(1)
        )
        if change is not None:
            change.commit_hash = commit_hash
            await self.db.commit()
            self._publish_change(
                task.project_id,
                {
                    "id": change.id,
                    "task_id": change.task_id,
                    "files": list(change.files or []),
                    "diff": change.diff,
                    "commit_hash": change.commit_hash,
                    "ts": utc_now().isoformat(),
                },
            )
        logger.info(
            "任务变更已提交: project=%s task=%s commit=%s",
            project.id,
            task.id,
            commit_hash,
        )
        return {"task_id": task.id, "commit_hash": commit_hash}

    async def merge_task(
        self,
        project_id: str,
        task_id: str,
        request: MergeTaskRequest,
        actor: Actor | None = None,
    ) -> dict[str, Any]:
        """把任务分支合回主分支，并立即重扫接口注册表。"""
        await self._require_leader(project_id, actor)
        task = await self._load_task(task_id)
        if task.project_id != project_id:
            raise IntegrationError("task_not_found", "任务不属于当前项目", 404)
        session = await self._latest_session(task.id)
        if session is None:
            raise IntegrationError(
                "session_not_found", "任务还没有运行记录，先运行再合并", 409
            )
        workspace_path = Path(session.workspace)
        if not workspace_path.is_dir():
            raise IntegrationError(
                "workspace_missing", "任务 Worktree 不存在", 409
            )

        project = await self._get_project(project_id)
        repo_root = Path(project.repo_path).resolve()
        base = (request.base_branch or "main").strip()
        if (
            not re.fullmatch(r"[A-Za-z0-9._/-]+", base)
            or base.startswith("-")
            or ".." in base
        ):
            raise IntegrationError(
                "invalid_base_branch", f"非法的主分支名: {base}", 400
            )
        branch = task.branch_name or f"teamcode/{project.id}/{task.id}"
        workspace = GitWorkspace(
            project_id=project.id,
            task_id=task.id,
            root=repo_root,
            worktree_path=workspace_path,
            branch_name=branch,
            base_branch=base,
        )

        # 1) 先提交 Worktree 里尚未提交的改动
        commit_hash: str | None = None
        try:
            changes = await asyncio.to_thread(collect_changes, workspace_path)
            if changes.files:
                commit_hash = await asyncio.to_thread(
                    commit_changes,
                    workspace,
                    list(task.allowed_paths or []),
                    request.message,
                )
                change = await self.db.scalar(
                    select(CodeChangeModel)
                    .where(CodeChangeModel.task_id == task.id)
                    .order_by(CodeChangeModel.id.desc())
                    .limit(1)
                )
                if change is not None:
                    change.commit_hash = commit_hash
                    await self.db.commit()
        except Exception as exc:
            logger.exception(
                "合并前提交任务分支失败: project=%s task=%s",
                project.id,
                task.id,
            )
            raise IntegrationError(
                "commit_failed", f"提交任务分支失败: {exc}", 400
            ) from exc

        # 2) 合并到主分支
        merge_commit, merge_error = await asyncio.to_thread(
            self._merge_branches, repo_root, base, branch, request.message
        )
        if merge_error is not None:
            raise IntegrationError("merge_failed", merge_error, 409)

        # 3) 重扫接口注册表并推送
        interface_summary = await self._refresh_registry_after_merge(project)

        logger.info(
            "任务已合并: project=%s task=%s branch=%s base=%s merge=%s",
            project.id,
            task.id,
            branch,
            base,
            merge_commit,
        )
        return {
            "task_id": task.id,
            "branch": branch,
            "base_branch": base,
            "commit_hash": commit_hash,
            "merge_commit": merge_commit,
            "interfaces": interface_summary,
        }

    @staticmethod
    def _merge_branches(
        repo_root: Path,
        base_branch: str,
        task_branch: str,
        message: str,
    ) -> tuple[str | None, str | None]:
        def run(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run(
                ["git", *args],
                cwd=str(repo_root),
                text=True,
                errors="replace",
                capture_output=True,
                check=False,
            )

        check = run("rev-parse", "--verify", task_branch)
        if check.returncode != 0:
            return None, f"任务分支不存在: {task_branch}"
        status = run("status", "--porcelain", "--untracked-files=no")
        if status.stdout.strip():
            return None, "主仓库有未提交的已跟踪文件，请先清理后再合并"
        checkout = run("checkout", base_branch)
        if checkout.returncode != 0:
            return (
                None,
                f"切换到 {base_branch} 失败: "
                f"{checkout.stderr.strip() or checkout.stdout.strip()}",
            )
        merge = run(
            "-c",
            "user.name=TeamCode",
            "-c",
            "user.email=teamcode@example.invalid",
            "merge",
            "--no-ff",
            task_branch,
            "-m",
            message,
        )
        if merge.returncode != 0:
            run("merge", "--abort")
            return (
                None,
                "合并失败（可能有冲突）: "
                f"{merge.stderr.strip() or merge.stdout.strip()}",
            )
        head = run("rev-parse", "HEAD")
        return head.stdout.strip() or None, None

    async def _refresh_registry_after_merge(
        self, project: Project
    ) -> dict[str, Any]:
        from sqlalchemy.ext.asyncio import AsyncEngine

        from app.interface_registry.models import ensure_registry_tables
        from app.interface_registry.service import InterfaceRegistryService

        try:
            bind = self.db.bind
            if isinstance(bind, AsyncEngine):
                await ensure_registry_tables(bind)
            summary = await InterfaceRegistryService(self.db).scan(
                project.id, project.repo_path
            )
            if summary.has_changes:
                bus.publish(
                    make_event(
                        "interface.updated",
                        project.id,
                        payload={
                            "added": summary.added,
                            "updated": summary.updated,
                            "deleted": summary.deleted,
                            "scanned_files": summary.scanned_files,
                            "total_interfaces": summary.total_interfaces,
                        },
                    )
                )
            return summary.to_dict()
        except Exception as exc:
            logger.exception(
                "合并后重扫接口失败: project=%s", project.id
            )
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 会话内对话（继续同一个 Claude 会话）
    # ------------------------------------------------------------------
    async def send_message(
        self,
        task_or_session_id: str,
        request: MessageRequest,
        actor: Actor | None = None,
    ) -> dict[str, Any]:
        task = await self._load_task(task_or_session_id)
        project = await self._get_project(task.project_id)
        await self._authorize(task, project, request.actor_id, actor)

        session = await self._latest_session(task.id)
        if session is None:
            raise IntegrationError(
                "session_not_found", "任务还没有运行记录，请先运行任务", 409
            )
        workspace = Path(session.workspace)
        if not workspace.is_dir():
            raise IntegrationError(
                "workspace_missing", "会话工作区不存在，请重新运行任务", 409
            )
        if (
            session.adapter not in {"claude", "cli"}
            and not os.getenv("TEAMCODE_CHAT_COMMAND")
        ):
            raise IntegrationError(
                "chat_not_supported",
                f"{session.adapter} 会话暂不支持续聊；"
                "可设置 TEAMCODE_CHAT_COMMAND 或使用 Claude",
                409,
            )

        runtime = self._runtime_for(project)
        async with runtime.lock:
            if task.id in runtime.active_tasks:
                raise IntegrationError(
                    "task_already_running", "任务正在运行，请稍后再发消息", 409
                )
            runtime.active_tasks.add(task.id)

        try:
            session.status = AgentStatus.RUNNING
            session.ended_at = None
            task.status = TaskStatus.IN_PROGRESS
            await self.db.commit()

            await self._append_log(
                project.id,
                task.id,
                session.id,
                "info",
                f"用户：{request.message}",
            )
            users = await self._users_for([task.owner_id])
            self._publish_task(self._task_dict(task, users.get(task.owner_id)))
        except Exception:
            runtime.active_tasks.discard(task.id)
            raise

        background = asyncio.create_task(
            self._chat(
                project_id=project.id,
                task_id=task.id,
                workspace=workspace,
                session_id=session.id,
                message=request.message,
                allowed_paths=list(task.allowed_paths or []),
                runtime=runtime,
            )
        )
        runtime.background[task.id] = background
        background.add_done_callback(
            lambda finished, task_id=task.id: self._on_background_done(
                runtime, task_id, finished
            )
        )
        logger.info(
            "会话消息已发送: project=%s task=%s session=%s",
            project.id,
            task.id,
            session.id,
        )
        return {
            "session_id": session.id,
            "task_id": task.id,
            "status": "running",
        }

    async def _chat(
        self,
        *,
        project_id: str,
        task_id: str,
        workspace: Path,
        session_id: str,
        message: str,
        allowed_paths: list[str],
        runtime: ProjectRuntime,
    ) -> None:
        status = AgentStatus.FAILED
        changes = ChangeSet()
        timeout = self._chat_timeout()

        try:
            command = self._chat_command()
            allowed = ", ".join(allowed_paths) or "(未限制)"
            prompt = (
                f"{message}\n\n"
                "执行约束（必须遵守）：\n"
                f"- 当前工作目录是独立的 Git Worktree；只允许创建或修改：{allowed}\n"
                "- 不要修改 .git、.teamcode 目录；不要提交、不要执行 git push。\n"
                "- 继续在现有代码上修改，完成后说明改了哪些文件。"
            )
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(workspace),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=os.environ.copy(),
            )
            if process.stdin is None or process.stdout is None or process.stderr is None:
                raise IntegrationError(
                    "chat_failed", "无法建立 Agent 进程管道", 500
                )

            async with self.session_factory() as log_db:

                async def pump(stream, level: str) -> None:
                    async for raw in stream:
                        line = raw.decode("utf-8", errors="replace").rstrip()
                        if not line:
                            continue
                        await self._append_log_with(
                            log_db,
                            project_id,
                            task_id,
                            session_id,
                            level,
                            line,
                        )

                process.stdin.write(prompt.encode("utf-8"))
                await process.stdin.drain()
                process.stdin.close()
                readers = [
                    asyncio.create_task(pump(process.stdout, "info")),
                    asyncio.create_task(pump(process.stderr, "warn")),
                ]
                try:
                    await asyncio.wait_for(process.wait(), timeout=timeout)
                except TimeoutError:
                    process.kill()
                    await process.wait()
                    await asyncio.gather(*readers, return_exceptions=True)
                    await self._append_log_with(
                        log_db,
                        project_id,
                        task_id,
                        session_id,
                        "error",
                        f"会话响应超时（{timeout:.0f}s）",
                    )
                    raise IntegrationError(
                        "chat_timeout", "Agent 响应超时", 504
                    ) from None
                await asyncio.gather(*readers, return_exceptions=True)
                status = (
                    AgentStatus.SUCCEEDED
                    if process.returncode == 0
                    else AgentStatus.FAILED
                )
                if status != AgentStatus.SUCCEEDED:
                    await self._append_log_with(
                        log_db,
                        project_id,
                        task_id,
                        session_id,
                        "error",
                        f"CLI 退出码 {process.returncode}",
                    )
        except IntegrationError as exc:
            logger.warning(
                "会话对话失败: project=%s task=%s %s",
                project_id,
                task_id,
                exc.message,
            )
        except Exception:
            logger.exception(
                "会话对话异常: project=%s task=%s", project_id, task_id
            )
        finally:
            runtime.active_tasks.discard(task_id)

        try:
            changes = await asyncio.to_thread(collect_changes, workspace)
            validation = validate_paths(workspace, changes.files, allowed_paths)
            if validation.rejected:
                status = AgentStatus.FAILED
                logger.warning(
                    "会话修改了未授权路径: project=%s task=%s rejected=%s",
                    project_id,
                    task_id,
                    [path for path, _ in validation.rejected],
                )
        except Exception:
            logger.exception(
                "收集会话变更失败: project=%s task=%s", project_id, task_id
            )

        try:
            async with self.session_factory() as db:
                await self._finalize_chat(
                    db,
                    project_id=project_id,
                    task_id=task_id,
                    session_id=session_id,
                    status=status,
                    changes=changes,
                )
        except Exception:
            logger.exception(
                "持久化会话结果失败: project=%s task=%s", project_id, task_id
            )

    async def _finalize_chat(
        self,
        db: AsyncSession,
        *,
        project_id: str,
        task_id: str,
        session_id: str,
        status: AgentStatus,
        changes: ChangeSet,
    ) -> None:
        session = await db.get(AgentSessionModel, session_id)
        if session is not None:
            session.status = status
            session.ended_at = utc_now() if status.terminal else None

        if changes.files:
            change_id = f"change_{session_id}"
            change = await db.get(CodeChangeModel, change_id)
            if change is None:
                change = CodeChangeModel(
                    id=change_id,
                    session_id=session_id,
                    task_id=task_id,
                    files=list(changes.files),
                    diff=changes.diff,
                    commit_hash=changes.commit_hash,
                )
                db.add(change)
            else:
                change.files = list(changes.files)
                change.diff = changes.diff
                change.commit_hash = changes.commit_hash

        task = await db.get(Task, task_id)
        if task is not None:
            task.status = self._task_status_for(status)
        await db.commit()

        if changes.files:
            self._publish_change(
                project_id,
                {
                    "id": f"change_{session_id}",
                    "task_id": task_id,
                    "files": list(changes.files),
                    "diff": changes.diff,
                    "commit_hash": changes.commit_hash,
                    "ts": utc_now().isoformat(),
                },
            )

        task_with_relations = await db.scalar(
            select(Task)
            .where(Task.id == task_id)
            .options(selectinload(Task.dependencies))
        )
        if task_with_relations is not None:
            owner = await db.get(User, task_with_relations.owner_id)
            self._publish_task(self._task_dict(task_with_relations, owner))

        logger.info(
            "会话对话结束: project=%s task=%s session=%s status=%s files=%d",
            project_id,
            task_id,
            session_id,
            status.value,
            len(changes.files),
        )

    async def _append_log(
        self,
        project_id: str,
        task_id: str,
        session_id: str,
        level: str,
        message: str,
    ) -> str:
        return await self._append_log_with(
            self.db, project_id, task_id, session_id, level, message
        )

    async def _append_log_with(
        self,
        db: AsyncSession,
        project_id: str,
        task_id: str,
        session_id: str,
        level: str,
        message: str,
    ) -> str:
        log_id = f"log_{session_id}_{uuid4().hex[:8]}"
        now = utc_now()
        db.add(
            AgentLogModel(
                id=log_id,
                session_id=session_id,
                ts=now,
                level=level,
                message=message,
            )
        )
        await db.commit()
        self._publish_log_payload(
            project_id, task_id, session_id, log_id, level, message, now
        )
        return log_id

    async def _set_session_status(
        self, session_id: str, status: AgentStatus
    ) -> None:
        try:
            async with self.session_factory() as db:
                session = await db.get(AgentSessionModel, session_id)
                if session is not None:
                    session.status = status
                    if status.terminal:
                        session.ended_at = utc_now()
                    await db.commit()
        except Exception:
            logger.exception(
                "更新会话状态失败: session=%s status=%s", session_id, status.value
            )

    @staticmethod
    def _chat_command() -> list[str]:
        raw = os.getenv("TEAMCODE_CHAT_COMMAND", "").strip()
        if raw:
            return shlex.split(raw)
        wrapper = (
            Path(__file__).resolve().parents[3]
            / "scripts"
            / "claude_stream_wrapper.py"
        )
        if not wrapper.exists():
            raise IntegrationError(
                "chat_not_configured",
                "未找到 scripts/claude_stream_wrapper.py，无法进行会话内对话",
                500,
            )
        return [sys.executable, str(wrapper), "--continue-session"]

    @staticmethod
    def _chat_timeout() -> float:
        raw = os.getenv(
            "TEAMCODE_CHAT_TIMEOUT", os.getenv("TEAMCODE_AGENT_TIMEOUT", "300")
        )
        try:
            return max(float(raw), 1.0)
        except ValueError:
            return 300.0

    # ------------------------------------------------------------------
    # 后台执行
    # ------------------------------------------------------------------
    async def _render_interfaces(self, project_id: str) -> str:
        """把当前接口注册表渲染成 Markdown，直接注入 Agent Prompt。"""
        from app.interface_registry.service import InterfaceRegistryService

        try:
            return await InterfaceRegistryService(self.db).render_markdown(
                project_id
            )
        except Exception:
            logger.exception(
                "生成任务接口文档失败，继续执行: project=%s", project_id
            )
            return ""

    async def _execute(
        self,
        *,
        project_id: str,
        task_id: str,
        task_spec: TaskSpec,
        workspace: GitWorkspace,
        session_id: str,
        prompt: str | None,
        context: dict[str, Any] | None,
        interface_doc: str = "",
        runtime: ProjectRuntime,
    ) -> None:
        stop = asyncio.Event()
        await self._set_session_status(session_id, AgentStatus.RUNNING)
        consumer = asyncio.create_task(
            self._stream_logs(project_id, task_id, session_id, runtime, stop)
        )
        changes = ChangeSet()
        status = AgentStatus.FAILED
        allowed = ", ".join(task_spec.allowed_paths) or "(未限制)"
        prompt_text = (
            f"{prompt or task_prompt(task_spec)}\n\n"
            "以下是当前接口注册表（Markdown，唯一事实来源），请直接以此为准，"
            "不要猜测接口，也不需要再执行 pull-interfaces：\n\n"
            f"{interface_doc or '（当前项目还没有已注册接口）'}\n\n"
            "执行约束（必须遵守）：\n"
            f"- 当前工作目录是独立的 Git Worktree；只允许创建或修改：{allowed}\n"
            "- 不要修改 .git、.teamcode 目录；不要提交、不要执行 git push。\n"
            "- 你可以使用 Bash 运行 pytest / python / git status 等命令。"
            "实现完成后请运行相关测试；如果测试失败，请自行定位并修复，"
            "直到通过或确认无法修复。\n"
            "- 完成后用一两句话说明修改了哪些文件、测试结果。"
        )
        try:
            await runtime.sessions.send_task(
                session_id,
                prompt_text,
                context=context,
            )
            changes = await runtime.sessions.get_changes(session_id)
            status = await runtime.sessions.get_status(session_id)
            validation = validate_paths(
                workspace.worktree_path,
                changes.files,
                task_spec.allowed_paths,
            )
            if validation.rejected:
                status = await runtime.sessions.mark_failed(
                    session_id,
                    "rejected changed paths: "
                    + ", ".join(path for path, _ in validation.rejected),
                )
        except Exception as exc:
            logger.exception("任务执行失败: project=%s task=%s", project_id, task_id)
            try:
                status = await runtime.sessions.mark_failed(
                    session_id, f"execution failed: {exc}"
                )
            except Exception:  # pragma: no cover - 兜底
                logger.exception("标记任务失败时再次出错: session=%s", session_id)
                status = AgentStatus.FAILED
        finally:
            # 给日志消费者最后一次拉取机会
            await asyncio.sleep(0.05)
            stop.set()
            await asyncio.gather(consumer, return_exceptions=True)
            runtime.active_tasks.discard(task_id)
            runtime.adapters.pop(session_id, None)

        try:
            async with self.session_factory() as db:
                await self._finalize(
                    db,
                    project_id=project_id,
                    task_id=task_id,
                    session_id=session_id,
                    status=status,
                    changes=changes,
                    workspace=workspace,
                )
        except Exception:
            logger.exception(
                "持久化任务结果失败: project=%s task=%s session=%s",
                project_id,
                task_id,
                session_id,
            )

    async def _stream_logs(
        self,
        project_id: str,
        task_id: str,
        session_id: str,
        runtime: ProjectRuntime,
        stop: asyncio.Event,
    ) -> None:
        seen = 0
        try:
            async with self.session_factory() as db:
                while not stop.is_set():
                    seen = await self._flush_logs(
                        db, project_id, task_id, session_id, runtime, seen
                    )
                    await asyncio.sleep(0.05)
                await self._flush_logs(
                    db, project_id, task_id, session_id, runtime, seen
                )
        except Exception:
            logger.exception(
                "持久化 Agent 日志失败: project=%s task=%s session=%s",
                project_id,
                task_id,
                session_id,
            )

    async def _flush_logs(
        self,
        db: AsyncSession,
        project_id: str,
        task_id: str,
        session_id: str,
        runtime: ProjectRuntime,
        seen: int,
    ) -> int:
        logs = runtime.sessions.list_logs(session_id)
        new_logs = logs[seen:]
        for log in new_logs:
            log_id = f"log_{session_id}_{log.sequence}"
            if await db.get(AgentLogModel, log_id) is None:
                db.add(
                    AgentLogModel(
                        id=log_id,
                        session_id=session_id,
                        ts=log.ts,
                        level=log.level,
                        message=log.message,
                    )
                )
                self._publish_log(project_id, task_id, session_id, log_id, log)
        if new_logs:
            await db.commit()
        return len(logs)

    async def _finalize(
        self,
        db: AsyncSession,
        *,
        project_id: str,
        task_id: str,
        session_id: str,
        status: AgentStatus,
        changes: ChangeSet,
        workspace: GitWorkspace,
    ) -> None:
        session = await db.get(AgentSessionModel, session_id)
        if session is not None:
            session.status = status
            session.ended_at = utc_now() if status.terminal else None

        if changes.files:
            change_id = f"change_{session_id}"
            change = await db.get(CodeChangeModel, change_id)
            if change is None:
                change = CodeChangeModel(
                    id=change_id,
                    session_id=session_id,
                    task_id=task_id,
                    files=list(changes.files),
                    diff=changes.diff,
                    commit_hash=changes.commit_hash,
                )
                db.add(change)
            else:
                change.files = list(changes.files)
                change.diff = changes.diff
                change.commit_hash = changes.commit_hash

        task = await db.get(Task, task_id)
        if task is not None:
            task.status = self._task_status_for(status)
            task.workspace_path = str(workspace.worktree_path)
            task.branch_name = workspace.branch_name
        await db.commit()

        if changes.files:
            self._publish_change(
                project_id,
                {
                    "id": f"change_{session_id}",
                    "task_id": task_id,
                    "files": list(changes.files),
                    "diff": changes.diff,
                    "commit_hash": changes.commit_hash,
                    "ts": utc_now().isoformat(),
                },
            )

        if task is not None:
            task_with_relations = await db.scalar(
                select(Task)
                .where(Task.id == task_id)
                .options(selectinload(Task.dependencies))
            )
            if task_with_relations is not None:
                owner = await db.get(User, task_with_relations.owner_id)
                self._publish_task(
                    self._task_dict(task_with_relations, owner),
                    actor=task_with_relations.owner_id,
                )

        logger.info(
            "任务执行结束: project=%s task=%s session=%s status=%s files=%d",
            project_id,
            task_id,
            session_id,
            status.value,
            len(changes.files),
        )

    def _on_background_done(
        self,
        runtime: ProjectRuntime,
        task_id: str,
        finished: asyncio.Task,
    ) -> None:
        runtime.background.pop(task_id, None)
        if finished.cancelled():
            logger.warning("任务后台执行被取消: project=%s task=%s", runtime.project_id, task_id)
            return
        error = finished.exception()
        if error is not None:
            logger.error(
                "任务后台执行异常: project=%s task=%s",
                runtime.project_id,
                task_id,
                exc_info=error,
            )

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def _publish_task(
        self, task: dict[str, Any], *, actor: str | None = None
    ) -> None:
        payload: dict[str, Any] = {"task": task}
        if actor is not None:
            payload["actor_id"] = actor
        try:
            bus.publish(
                make_event(
                    "task.updated",
                    task["project_id"],
                    payload,
                    task_id=task["task_id"],
                )
            )
        except Exception:
            logger.exception("task.updated 发布失败: task=%s", task.get("task_id"))

    def _publish_log(
        self,
        project_id: str,
        task_id: str,
        session_id: str,
        log_id: str,
        log: Any,
    ) -> None:
        self._publish_log_payload(
            project_id,
            task_id,
            session_id,
            log_id,
            log.level,
            log.message,
            log.ts,
        )

    def _publish_log_payload(
        self,
        project_id: str,
        task_id: str,
        session_id: str,
        log_id: str,
        level: str,
        message: str,
        ts,
    ) -> None:
        try:
            bus.publish(
                make_event(
                    "agent.log",
                    project_id,
                    {
                        "id": log_id,
                        "session_id": session_id,
                        "task_id": task_id,
                        "ts": ts.isoformat(),
                        "level": level,
                        "message": message,
                        "sequence": 0,
                    },
                    task_id=task_id,
                )
            )
        except Exception:
            logger.exception(
                "agent.log 发布失败: project=%s task=%s", project_id, task_id
            )

    def _publish_change(self, project_id: str, change: dict[str, Any]) -> None:
        try:
            bus.publish(
                make_event(
                    "code.changed",
                    project_id,
                    change,
                    task_id=change.get("task_id"),
                )
            )
        except Exception:
            logger.exception(
                "code.changed 发布失败: project=%s task=%s",
                project_id,
                change.get("task_id"),
            )

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    async def _get_project(self, project_id: str) -> Project:
        project = await self.db.get(Project, project_id)
        if project is None:
            raise IntegrationError("project_not_found", f"项目不存在: {project_id}", 404)
        return project

    async def _ensure_user(
        self,
        user_id: str,
        *,
        name: str | None = None,
        email: str | None = None,
        role: UserRole = UserRole.MEMBER,
    ) -> User:
        user_id = (user_id or "").strip() or "u_local"
        user = await self.db.get(User, user_id)
        if user is None:
            user = User(
                id=user_id,
                name=name or user_id,
                email=email or f"{user_id}@teamcode.invalid",
                role=role,
            )
            self.db.add(user)
            await self.db.flush()
        return user

    async def _ensure_project_member(
        self,
        project_id: str,
        user_id: str,
        role: ProjectRole = ProjectRole.MEMBER,
    ) -> ProjectMember:
        member = await self.db.get(
            ProjectMember, {"project_id": project_id, "user_id": user_id}
        )
        if member is None:
            member = ProjectMember(
                project_id=project_id, user_id=user_id, role=role
            )
            self.db.add(member)
            await self.db.flush()
        return member

    async def _users_for(self, user_ids: list[str]) -> dict[str, User]:
        ids = {user_id for user_id in user_ids if user_id}
        if not ids:
            return {}
        users = (
            await self.db.scalars(select(User).where(User.id.in_(ids)))
        ).all()
        return {user.id: user for user in users}

    async def _member_specs(
        self,
        project_id: str,
        provided: list[TeamMemberSpec],
        roles: list[str] | None = None,
    ) -> list[TeamMemberSpec]:
        if provided:
            specs: list[TeamMemberSpec] = []
            for member in provided:
                user = await self._ensure_user(
                    member.member_id, name=member.name or member.member_id
                )
                await self._ensure_project_member(project_id, user.id)
                specs.append(
                    TeamMemberSpec(
                        member_id=user.id,
                        name=member.name or user.name,
                        areas=list(member.areas),
                    )
                )
            return specs

        if roles:
            specs = []
            for role in roles:
                role_name = role.strip()
                if not role_name:
                    continue
                slug = re.sub(r"[^a-zA-Z0-9]+", "-", role_name.lower()).strip("-")
                user = await self._ensure_user(
                    f"role_{slug or 'member'}",
                    name=f"角色 {role_name}",
                )
                specs.append(
                    TeamMemberSpec(
                        member_id=user.id, name=user.name, areas=[]
                    )
                )
            if specs:
                return specs

        rows = (
            await self.db.execute(
                select(ProjectMember, User)
                .join(User, User.id == ProjectMember.user_id)
                .where(ProjectMember.project_id == project_id)
                .order_by(ProjectMember.created_at)
            )
        ).all()
        if rows:
            areas_by_user: dict[str, list[str]] = {}
            approved = (
                await self.db.scalars(
                    select(JoinRequest).where(
                        JoinRequest.project_id == project_id,
                        JoinRequest.status == "approved",
                    )
                )
            ).all()
            for join in approved:
                if join.user_id:
                    areas_by_user[join.user_id] = list(join.areas or [])
            return [
                TeamMemberSpec(
                    member_id=user.id,
                    name=user.name,
                    areas=areas_by_user.get(user.id, []),
                )
                for _, user in rows
            ]

        project = await self._get_project(project_id)
        owner = await self._ensure_user(project.owner_id, name="Local Leader")
        return [TeamMemberSpec(member_id=owner.id, name=owner.name, areas=[])]

    async def assign_task(
        self,
        task_id: str,
        request: AssignTaskRequest,
        actor: Actor | None = None,
    ) -> dict[str, Any]:
        task = await self._load_task(task_id)
        leader = await self._require_leader(task.project_id, actor)
        user = await self.db.get(User, request.user_id)
        if user is None:
            raise IntegrationError("user_not_found", "成员不存在", 404)
        member = await self.db.get(
            ProjectMember,
            {"project_id": task.project_id, "user_id": user.id},
        )
        if member is None:
            raise IntegrationError(
                "not_project_member", "该用户还不是项目成员", 422
            )
        task.owner_id = user.id
        await self.db.commit()
        task_with_relations = await self.db.scalar(
            select(Task)
            .where(Task.id == task.id)
            .options(selectinload(Task.dependencies))
        )
        if task_with_relations is not None:
            self._publish_task(
                self._task_dict(task_with_relations, user),
                actor=leader.user_id if leader is not None else None,
            )
        logger.info(
            "任务已分配: project=%s task=%s user=%s",
            task.project_id,
            task.id,
            user.id,
        )
        return self._task_dict(task_with_relations or task, user)

    async def _store_plan(
        self,
        project_id: str,
        plan: PlanResult,
        request: PlanningRequest,
    ) -> None:
        snapshot = await self.db.scalar(
            select(PlanSnapshot).where(
                PlanSnapshot.project_id == project_id,
                PlanSnapshot.version == plan.version,
            )
        )
        payload = plan.model_dump(mode="json")
        request_payload = request.model_dump(mode="json")
        if snapshot is None:
            self.db.add(
                PlanSnapshot(
                    project_id=project_id,
                    version=plan.version,
                    payload=payload,
                    request=request_payload,
                )
            )
        else:
            snapshot.payload = payload
            snapshot.request = request_payload

    async def _latest_plan(self, project_id: str) -> PlanResult | None:
        snapshot = await self.db.scalar(
            select(PlanSnapshot)
            .where(PlanSnapshot.project_id == project_id)
            .order_by(PlanSnapshot.version.desc())
            .limit(1)
        )
        if snapshot is None:
            return None
        try:
            return PlanResult.model_validate(snapshot.payload)
        except Exception:
            logger.exception("解析计划快照失败: project=%s", project_id)
            return None

    async def _sync_tasks(self, project: Project, plan: PlanResult) -> None:
        existing = {
            task.id: task
            for task in (
                await self.db.scalars(
                    select(Task).where(Task.project_id == project.id)
                )
            ).all()
        }
        plan_ids = {task.task_id for task in plan.tasks}

        for planned in plan.tasks:
            task = existing.get(planned.task_id)
            if task is None:
                task = Task(
                    id=planned.task_id,
                    project_id=project.id,
                    title=planned.title,
                    description=planned.description,
                    owner_id=planned.owner_id,
                    status=TaskStatus.PLANNED,
                    allowed_paths=list(planned.allowed_paths),
                    interface_requirements=list(planned.interface_requirements),
                    acceptance_criteria=list(planned.acceptance_criteria),
                    priority=planned.priority,
                    replan_version=plan.version,
                )
                self.db.add(task)
                existing[task.id] = task
            else:
                task.title = planned.title
                task.description = planned.description
                # 占位角色只是默认分配；已经分给真人的任务保持真人 owner
                if not (
                    planned.owner_id.startswith("role_")
                    and task.owner_id
                    and not task.owner_id.startswith("role_")
                ):
                    task.owner_id = planned.owner_id
                task.allowed_paths = list(planned.allowed_paths)
                task.interface_requirements = list(planned.interface_requirements)
                task.acceptance_criteria = list(planned.acceptance_criteria)
                task.priority = planned.priority
                task.replan_version = plan.version

        if plan_ids:
            await self.db.execute(
                delete(TaskDependency).where(TaskDependency.task_id.in_(plan_ids))
            )
            known_ids = set(existing) | plan_ids
            for planned in plan.tasks:
                for dependency in planned.depends_on:
                    if dependency in known_ids:
                        self.db.add(
                            TaskDependency(
                                task_id=planned.task_id,
                                depends_on_task_id=dependency,
                            )
                        )
        await self.db.flush()

    async def _load_task(self, task_or_session_id: str) -> Task:
        task = await self.db.scalar(
            select(Task)
            .where(Task.id == task_or_session_id)
            .options(selectinload(Task.dependencies))
        )
        if task is not None:
            return task
        session = await self.db.get(AgentSessionModel, task_or_session_id)
        if session is not None:
            task = await self.db.scalar(
                select(Task)
                .where(Task.id == session.task_id)
                .options(selectinload(Task.dependencies))
            )
        if task is None:
            raise IntegrationError(
                "task_not_found", f"任务不存在: {task_or_session_id}", 404
            )
        return task

    async def _latest_session(self, task_id: str) -> AgentSessionModel | None:
        return await self.db.scalar(
            select(AgentSessionModel)
            .where(AgentSessionModel.task_id == task_id)
            .order_by(AgentSessionModel.started_at.desc())
            .limit(1)
        )

    async def _authorize(
        self,
        task: Task,
        project: Project,
        actor_id: str | None,
        actor: Actor | None = None,
    ) -> str:
        if actor is not None:
            role = await self._project_role(project.id, actor)
            if role is None:
                raise IntegrationError(
                    "permission_denied", "你不是该项目成员", 403
                )
            if (
                actor.user_id not in {task.owner_id, project.owner_id}
                and role != "leader"
            ):
                raise IntegrationError(
                    "permission_denied",
                    f"用户 {actor.user_id} 无权操作任务 {task.id}",
                    403,
                )
            return actor.user_id

        if auth_required():
            raise IntegrationError(
                "actor_required", "请先加入团队或使用有效 Token", 401
            )

        candidate = (actor_id or "").strip()
        if not candidate:
            raise IntegrationError(
                "actor_required", "请求必须提供 actor_id（未启用登录模式）", 401
            )
        if candidate not in {task.owner_id, project.owner_id}:
            raise IntegrationError(
                "permission_denied",
                f"用户 {candidate} 无权操作任务 {task.id}",
                403,
            )
        return candidate

    async def _project_role(
        self, project_id: str, actor: Actor | None
    ) -> str | None:
        """解析账号在指定项目中的角色（owner -> leader）。"""
        if actor is None:
            return None
        # 兼容旧的项目级 token
        if actor.project_id == project_id and actor.role in {"leader", "member"}:
            return actor.role
        member = await self.db.get(
            ProjectMember,
            {"project_id": project_id, "user_id": actor.user_id},
        )
        if member is None:
            return None
        return "leader" if member.role == ProjectRole.OWNER else "member"

    async def _require_project_access(
        self, project_id: str, actor: Actor | None
    ) -> tuple[Project, str]:
        project = await self._get_project(project_id)
        if actor is None:
            if auth_required():
                raise IntegrationError(
                    "actor_required", "请先注册/登录", 401
                )
            return project, "leader"
        if actor.key_project_id and actor.key_project_id != project_id:
            raise IntegrationError(
                "permission_denied",
                f"该 API Key 仅限项目 {actor.key_project_id}",
                403,
            )
        role = await self._project_role(project_id, actor)
        if role is None:
            raise IntegrationError(
                "permission_denied", "你不是该项目成员", 403
            )
        return project, role

    async def _require_leader(
        self, project_id: str, actor: Actor | None
    ) -> Actor | None:
        _, role = await self._require_project_access(project_id, actor)
        if role != "leader":
            raise IntegrationError(
                "permission_denied", "只有队长可以执行该操作", 403
            )
        return actor

    async def _require_task_read(
        self, task: Task, actor: Actor | None
    ) -> None:
        if actor is None:
            if auth_required():
                raise IntegrationError(
                    "actor_required", "请先注册/登录", 401
                )
            return
        role = await self._project_role(task.project_id, actor)
        if role is None:
            raise IntegrationError(
                "permission_denied", "你不是该项目成员", 403
            )
        if role == "leader" or actor.user_id == task.owner_id:
            return
        raise IntegrationError(
            "permission_denied", "只能查看自己的任务", 403
        )

    def _runtime_for(self, project: Project) -> ProjectRuntime:
        repo_root = Path(project.repo_path).resolve()
        runtime = _runtimes.get(project.id)
        if runtime is None:
            runtime = ProjectRuntime(project_id=project.id, repo_root=repo_root)
            _runtimes[project.id] = runtime
            logger.info(
                "创建项目运行时: project=%s root=%s", project.id, repo_root
            )
        elif runtime.repo_root != repo_root:
            raise IntegrationError(
                "runtime_conflict",
                "项目仓库路径已变化，请重启服务后再运行任务",
                409,
            )
        return runtime

    @staticmethod
    def _task_status_for(status: AgentStatus) -> TaskStatus:
        return {
            AgentStatus.SUCCEEDED: TaskStatus.COMPLETED,
            AgentStatus.FAILED: TaskStatus.BLOCKED,
            AgentStatus.TERMINATED: TaskStatus.CANCELLED,
        }.get(status, TaskStatus.IN_PROGRESS)

    @staticmethod
    def _task_dict(task: Task, owner: User | None = None) -> dict[str, Any]:
        return {
            "task_id": task.id,
            "project_id": task.project_id,
            "title": task.title,
            "description": task.description,
            "owner_id": task.owner_id,
            "owner_name": owner.name if owner is not None else task.owner_id,
            "status": task.status.value
            if isinstance(task.status, TaskStatus)
            else str(task.status),
            "allowed_paths": list(task.allowed_paths or []),
            "interface_requirements": list(task.interface_requirements or []),
            "acceptance_criteria": list(task.acceptance_criteria or []),
            "depends_on": [dependency.id for dependency in task.dependencies],
            "priority": task.priority,
            "replan_version": task.replan_version,
            "workspace_path": task.workspace_path,
            "branch_name": task.branch_name,
        }

    @staticmethod
    def _build_adapter(
        agent_name: str | None = None,
        adapter_name: str | None = None,
    ):
        name = (agent_name or adapter_name or "").strip().lower()
        if not name:
            name = os.getenv("TEAMCODE_AGENT", "claude").strip().lower()
        if name == "cli":  # 兼容旧配置
            name = "claude"

        specs = agent_specs()
        spec = specs.get(name)
        if spec is None:
            raise IntegrationError(
                "unknown_agent",
                f"未知 Agent: {name}；可用: {', '.join(sorted(specs))}",
                400,
            )

        if spec.kind == "mock":
            delay_raw = os.getenv("TEAMCODE_MOCK_DELAY", "").strip()
            try:
                delay = float(delay_raw) if delay_raw else 0.0
            except ValueError as exc:
                raise IntegrationError(
                    "invalid_adapter_config",
                    "TEAMCODE_MOCK_DELAY 必须是数字",
                    400,
                ) from exc
            fail = os.getenv("TEAMCODE_MOCK_FAIL", "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            return MockAdapter(fail=fail, delay=max(delay, 0.0))

        if spec.command is None:
            raise IntegrationError(
                "agent_not_configured",
                f"Agent {name} 还没有配置启动命令",
                400,
            )

        binary = spec.binary or spec.command[0]
        if not (shutil.which(binary) or Path(binary).exists()):
            raise IntegrationError(
                "agent_unavailable",
                f"Agent {name} 不可用：未找到命令 {binary}。"
                "请先安装对应 CLI，或在服务端配置命令后重试。",
                400,
            )

        timeout_raw = os.getenv("TEAMCODE_AGENT_TIMEOUT", "").strip()
        try:
            timeout = float(timeout_raw) if timeout_raw else None
        except ValueError as exc:
            raise IntegrationError(
                "invalid_adapter_config",
                "TEAMCODE_AGENT_TIMEOUT 必须是数字",
                400,
            ) from exc

        if spec.kind == "claude-stream":
            adapter = CLIAdapter(
                CLIAdapterConfig(
                    command=spec.command,
                    prompt_mode=spec.prompt_mode,
                    timeout=timeout,
                )
            )
        else:
            # 通用 CLI Agent：由 C 的包装器按 stdin/arg/file 传递 prompt
            wrapped = (
                sys.executable,
                str(generic_wrapper_path()),
                "--prompt-mode",
                spec.prompt_mode,
                "--",
                *spec.command,
            )
            adapter = CLIAdapter(
                CLIAdapterConfig(
                    command=wrapped,
                    prompt_mode="stdin",
                    timeout=timeout,
                )
            )
        adapter.name = spec.name  # type: ignore[attr-defined]
        return adapter

    @staticmethod
    def _mock_writes(task: TaskSpec) -> dict[str, str]:
        base = (task.allowed_paths[0] if task.allowed_paths else "generated").rstrip(
            "/"
        )
        if base in {"", "."}:
            base = "generated"
        class_name = "GeneratedService"
        if task.interface_requirements:
            class_name = (
                str(task.interface_requirements[0]).split(".")[-1]
                or class_name
            )
        class_name = re.sub(r"[^A-Za-z0-9_]", "", class_name) or "GeneratedService"
        content = (
            '"""由 MockAdapter 生成的演示文件。"""\n\n\n'
            f"class {class_name}:\n"
            '    """演示接口实现。"""\n\n'
            "    def run(self) -> str:\n"
            '        return "ok"\n'
        )
        return {f"{base}/generated_service.py": content}
