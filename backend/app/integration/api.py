"""整合层 REST API（A 规划 + B 执行 + C 事件 + 身份/审批）。

鉴权模型：
- 队长创建项目时拿到 leader token；
- 队员用 device_id + device_secret 申请加入，队长批准后用同一 device_secret
  轮询拿到 member token；
- 所有写操作优先使用 ``Authorization: Bearer <token>`` 解析出的 actor，
  不再信任请求体里的 actor_id；未启用登录时（TEAMCODE_REQUIRE_AUTH=0）
  保留旧 actor_id 兼容模式，便于单测和本地调试。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import get_session
from app.integration.agents import list_agents
from app.integration.auth import Actor, auth_required, get_actor
from app.integration.models import ensure_integration_tables
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
from app.integration.service import IntegrationError, IntegrationService
from app.interface_registry.logging_setup import configure_logging
from app.models.project import Project

configure_logging()
logger = logging.getLogger(__name__)

router = APIRouter(tags=["integration"])


async def _service(
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> IntegrationService:
    bind = db.bind
    if not isinstance(bind, AsyncEngine):
        raise IntegrationError(
            "storage_unavailable", "当前数据库会话没有可用的异步引擎", 500
        )
    await ensure_integration_tables(bind)
    return IntegrationService(
        db, async_sessionmaker(bind, expire_on_commit=False)
    )


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "detail": None},
    )


def _handle(exc: Exception) -> JSONResponse:
    if isinstance(exc, IntegrationError):
        return _error(exc.status_code, exc.code, exc.message)
    logger.exception("整合层未预期异常")
    return _error(500, "internal_error", "服务内部错误，请查看服务日志")


def _require_identity(actor: Actor | None) -> JSONResponse | None:
    if actor is None:
        return _error(401, "actor_required", "请先加入团队或使用有效 Token")
    return None


def _check_project(actor: Actor | None, _project_id: str) -> JSONResponse | None:
    # 全局 token 不携带项目；具体成员角色由 service 查询 project_members
    return _require_identity(actor) if auth_required() else None


# ---------------------------------------------------------------------------
# 身份 / 加入团队 / 队长审批
# ---------------------------------------------------------------------------


@router.get("/api/me", summary="当前登录身份")
async def me(actor: Actor | None = Depends(get_actor)):  # noqa: B008
    denied = _require_identity(actor)
    if denied is not None:
        return denied
    assert actor is not None
    return {"user_id": actor.user_id, "name": actor.name}


@router.get("/api/agents", summary="可用的 Coding Agent")
async def available_agents(
    actor: Actor | None = Depends(get_actor),  # noqa: B008
) -> Any:
    denied = _require_identity(actor) if auth_required() else None
    if denied is not None:
        return denied
    return {"agents": list_agents()}


@router.post("/api/auth/register", summary="注册全局账号")
async def register(
    request: RegisterRequest,
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.register(request)
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.post("/api/auth/login", summary="登录全局账号")
async def login(
    request: LoginRequest,
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.login(request)
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.post("/api/auth/api-keys", summary="创建 API Key")
async def create_api_key(
    request: ApiKeyCreate,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.create_api_key(request, actor)
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.get("/api/auth/api-keys", summary="我的 API Key")
async def list_api_keys(
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return {"keys": await service.list_api_keys(actor)}
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.delete("/api/auth/api-keys/{key_id}", summary="撤销 API Key")
async def revoke_api_key(
    key_id: str,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.revoke_api_key(key_id, actor)
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.get("/api/projects", summary="我的团队")
async def my_projects(
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return {"projects": await service.list_my_projects(actor)}
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.get("/api/join-requests/mine", summary="我的加入申请")
async def my_join_requests(
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return {"requests": await service.list_my_join_requests(actor)}
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.post(
    "/api/projects/{project_id}/join-requests",
    summary="申请加入团队（注册账号）",
)
async def request_join(
    project_id: str,
    request: JoinTeamRequest | None = None,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.request_join(
            project_id, request or JoinTeamRequest(), actor
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.post("/api/join-requests", summary="申请加入团队（旧设备模式）")
async def create_join_request(
    request: JoinRequestCreate,
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.create_join_request(request)
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.get("/api/join-requests/{request_id}", summary="查询加入申请状态")
async def get_join_status(
    request_id: str,
    device_secret: str = Header(alias="X-Device-Secret"),
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.get_join_status(request_id, device_secret)
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.get(
    "/api/projects/{project_id}/join-requests",
    summary="队长查看加入申请",
)
async def list_join_requests(
    project_id: str,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return {"requests": await service.list_join_requests(project_id, actor)}
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.post(
    "/api/projects/{project_id}/join-requests/{request_id}/approve",
    summary="队长批准加入申请",
)
async def approve_join_request(
    project_id: str,
    request_id: str,
    request: ApproveJoinRequest | None = None,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.approve_join_request(
            project_id, request_id, request or ApproveJoinRequest(), actor
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.post(
    "/api/projects/{project_id}/join-requests/{request_id}/reject",
    summary="队长拒绝加入申请",
)
async def reject_join_request(
    project_id: str,
    request_id: str,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.reject_join_request(project_id, request_id, actor)
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


# ---------------------------------------------------------------------------
# 项目 / 成员 / 规划
# ---------------------------------------------------------------------------


@router.post("/api/projects", summary="创建团队（创建者成为队长）")
async def create_project(
    request: ProjectCreateRequest,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.create_project(request, actor)
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.get("/api/projects/{project_id}", summary="项目详情")
async def get_project(
    project_id: str,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    denied = _check_project(actor, project_id)
    if denied is not None:
        return denied
    try:
        await service._require_project_access(project_id, actor)  # noqa: SLF001
        project = await service.db.get(Project, project_id)
        if project is None:
            raise IntegrationError(
                "project_not_found", f"项目不存在: {project_id}", 404
            )
        return {
            "id": project.id,
            "name": project.name,
            "repo_path": project.repo_path,
            "owner_id": project.owner_id,
            "created_at": project.created_at.isoformat(),
        }
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.post("/api/projects/{project_id}/members", summary="添加项目成员")
async def add_member(
    project_id: str,
    request: MemberCreateRequest,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.add_member(project_id, request, actor)
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.get("/api/projects/{project_id}/members", summary="项目成员列表")
async def list_members(
    project_id: str,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return {"members": await service.list_members(project_id, actor)}
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.post(
    "/api/projects/{project_id}/requirements",
    summary="提交 Markdown 大纲，触发规划或重规划",
)
async def submit_requirements(
    project_id: str,
    request: RequirementsRequest,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.plan_project(project_id, request, actor)
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.get("/api/projects/{project_id}/plan", summary="当前计划")
async def get_plan(
    project_id: str,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        plan = await service.get_plan(project_id, actor)
        if plan is None:
            return _error(404, "plan_not_found", f"项目还没有计划: {project_id}")
        return plan
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.get("/api/projects/{project_id}/tasks", summary="任务列表")
async def list_tasks(
    project_id: str,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return {"tasks": await service.list_tasks(project_id, actor)}
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.post(
    "/api/projects/{project_id}/tasks/{task_id}/assign",
    summary="队长把任务分配给成员",
)
async def assign_task(
    project_id: str,
    task_id: str,
    request: AssignTaskRequest,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        task = await service._load_task(task_id)  # noqa: SLF001
        if task.project_id != project_id:
            raise IntegrationError("task_not_found", "任务不属于当前项目", 404)
        return await service.assign_task(task_id, request, actor)
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


# ---------------------------------------------------------------------------
# 任务执行
# ---------------------------------------------------------------------------


@router.post("/api/tasks/{task_id}/run", summary="启动 Coding Agent")
async def run_task(
    task_id: str,
    request: RunRequest | None = None,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.run_task(
            task_id, request or RunRequest(), actor
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.post("/api/tasks/{task_id}/pause", summary="暂停会话")
async def pause_task(
    task_id: str,
    actor_id: str | None = Query(default=None),
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.control_task(task_id, "pause", actor_id, actor)
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.post("/api/tasks/{task_id}/resume", summary="恢复会话")
async def resume_task(
    task_id: str,
    actor_id: str | None = Query(default=None),
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.control_task(task_id, "resume", actor_id, actor)
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.post("/api/tasks/{task_id}/terminate", summary="终止会话")
async def terminate_task(
    task_id: str,
    actor_id: str | None = Query(default=None),
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.control_task(
            task_id, "terminate", actor_id, actor
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.get("/api/tasks/{task_id}/status", summary="会话状态")
async def task_status(
    task_id: str,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.task_status_dict(task_id, actor)
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.get("/api/tasks/{task_id}/logs", summary="历史日志")
async def task_logs(
    task_id: str,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return {"logs": await service.task_logs(task_id, actor)}
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.get("/api/tasks/{task_id}/changes", summary="文件变更")
async def task_changes(
    task_id: str,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return {"changes": await service.task_changes(task_id, actor)}
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.post("/api/tasks/{task_id}/messages", summary="会话内继续对话")
async def send_message(
    task_id: str,
    request: MessageRequest,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.send_message(task_id, request, actor)
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.post(
    "/api/projects/{project_id}/tasks/{task_id}/merge",
    summary="合并任务分支并刷新接口注册表",
)
async def merge_task(
    project_id: str,
    task_id: str,
    request: MergeTaskRequest | None = None,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.merge_task(
            project_id,
            task_id,
            request or MergeTaskRequest(),
            actor,
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)


@router.post("/api/tasks/{task_id}/commit", summary="提交授权变更")
async def commit_task(
    task_id: str,
    request: CommitRequest,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: IntegrationService = Depends(_service),  # noqa: B008
) -> Any:
    try:
        return await service.commit_task(task_id, request, actor)
    except Exception as exc:  # noqa: BLE001
        return _handle(exc)
