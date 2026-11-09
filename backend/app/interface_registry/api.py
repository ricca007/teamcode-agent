"""C-2：接口注册中心 REST API。

路由与 ``docs/interface_contract.md`` 保持一致：
- GET  /api/projects/{project_id}/interfaces?format=json|markdown
- GET  /api/interfaces/{interface_id}
- POST /api/projects/{project_id}/interfaces/refresh
- GET  /health/interfaces（C 自己的降级可观测入口）

本层只做「参数校验 + 调用 service + 可选事件推送」，业务逻辑全部在
``interface_registry.service``。

错误兜底：
- 所有可预期错误返回 ``{code, message, detail}``；
- 未预期异常记录完整堆栈日志，并返回结构化 500，避免把 traceback 暴露给前端；
- 事件推送 / 监听启动失败只降级，不影响接口查询本身。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import get_session
from app.integration.auth import Actor, auth_required, get_actor
from app.interface_registry.logging_setup import configure_logging
from app.interface_registry.models import ensure_registry_tables
from app.interface_registry.schemas import (
    InterfaceInfo,
    InterfaceListResponse,
    RefreshRequest,
    utcnow,
)
from app.interface_registry.service import InterfaceRegistryService
from app.interface_registry.watcher import watcher_manager
from app.models.project import Project, ProjectMember
from app.realtime.events import make_event
from app.realtime.manager import bus

configure_logging()
logger = logging.getLogger(__name__)

router = APIRouter(tags=["interfaces"])


async def _registry(
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> InterfaceRegistryService:
    bind = db.bind
    if isinstance(bind, AsyncEngine):
        try:
            await ensure_registry_tables(bind)
        except Exception:
            logger.exception("初始化接口注册中心失败")
            raise
    return InterfaceRegistryService(db)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "detail": None},
    )


async def _require_member(
    project_id: str,
    actor: Actor | None,
    db: AsyncSession,
) -> JSONResponse | None:
    """接口文档是团队共享资源，但必须登录/API Key 且属于该项目。"""
    if not auth_required():
        return None
    if actor is None:
        return _error(401, "actor_required", "请先登录或使用 API Key")
    if actor.key_project_id and actor.key_project_id != project_id:
        return _error(
            403, "permission_denied", "该 API Key 仅限其他项目"
        )
    member = await db.get(
        ProjectMember,
        {"project_id": project_id, "user_id": actor.user_id},
    )
    if member is None:
        return _error(403, "permission_denied", "你不是该项目成员")
    return None


def _session_factory(service: InterfaceRegistryService) -> async_sessionmaker | None:
    """为文件监听器生成与当前引擎绑定的异步会话工厂。"""
    bind = service.db.bind
    if not isinstance(bind, AsyncEngine):
        logger.warning("当前数据库会话没有可用的异步引擎，跳过文件监听")
        return None
    return async_sessionmaker(bind, expire_on_commit=False)


def _start_watcher(
    service: InterfaceRegistryService,
    project_id: str,
    root: str | Path,
    *,
    include_tests: bool = False,
) -> None:
    """启动文件监听；失败只降级，不影响接口查询。"""
    try:
        factory = _session_factory(service)
        if factory is None:
            return
        watcher_manager.start(
            project_id, root, factory, include_tests=include_tests
        )
    except Exception:
        logger.exception("启动接口文件监听失败（降级为手动刷新）: project=%s", project_id)


@router.get(
    "/api/projects/{project_id}/interfaces",
    response_model=None,
    summary="接口列表 / 可拉取的 Markdown 文档",
)
async def list_interfaces(
    project_id: str,
    format: Literal["json", "markdown"] = "json",
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: InterfaceRegistryService = Depends(_registry),  # noqa: B008
):
    try:
        denied = await _require_member(project_id, actor, service.db)
        if denied is not None:
            return denied
        project = await service.db.get(Project, project_id)
        interfaces = await service.list_interfaces(project_id)

        # 未知项目返回 404，避免 CLI / 前端把「项目不存在」误判为空项目
        if project is None and not interfaces:
            return _error(404, "project_not_found", f"项目不存在: {project_id}")

        # 顺带开启文件监听，避免依赖修改 A 的应用生命周期
        if (
            project is not None
            and project.repo_path
            and Path(project.repo_path).exists()
        ):
            _start_watcher(service, project_id, project.repo_path)

        if format == "markdown":
            return PlainTextResponse(
                await service.render_markdown(project_id),
                media_type="text/markdown; charset=utf-8",
            )

        return InterfaceListResponse(
            project_id=project_id,
            generated_at=utcnow(),
            count=len(interfaces),
            interfaces=interfaces,
        )
    except Exception:
        logger.exception("读取接口列表失败: project=%s format=%s", project_id, format)
        return _error(500, "internal_error", "读取接口列表失败，请查看服务日志")


@router.get(
    "/api/interfaces/{interface_id}",
    response_model=InterfaceInfo,
    summary="单个接口详情",
)
async def get_interface(
    interface_id: str,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: InterfaceRegistryService = Depends(_registry),  # noqa: B008
):
    try:
        info = await service.get_interface(interface_id)
        if info is not None:
            denied = await _require_member(
                info.project_id, actor, service.db
            )
            if denied is not None:
                return denied
    except Exception:
        logger.exception("读取接口详情失败: interface=%s", interface_id)
        return _error(500, "internal_error", "读取接口详情失败，请查看服务日志")

    if info is None:
        return _error(
            404, "interface_not_found", f"接口不存在或已删除: {interface_id}"
        )
    return info


@router.post(
    "/api/projects/{project_id}/interfaces/refresh",
    response_model=None,
    summary="手动触发重扫",
)
async def refresh_interfaces(
    project_id: str,
    request: RefreshRequest | None = None,
    actor: Actor | None = Depends(get_actor),  # noqa: B008
    service: InterfaceRegistryService = Depends(_registry),  # noqa: B008
) -> dict | JSONResponse:
    started = time.perf_counter()
    options = request or RefreshRequest()

    try:
        denied = await _require_member(project_id, actor, service.db)
        if denied is not None:
            return denied
        project = await service.db.get(Project, project_id)
        root = options.root or (project.repo_path if project else None)

        if not root:
            logger.warning("接口刷新失败：项目不存在或未配置 repo_path: %s", project_id)
            return _error(
                404,
                "project_not_found",
                f"项目不存在或未配置 repo_path: {project_id}",
            )
        if not Path(root).exists():
            logger.warning("接口刷新失败：目录不存在: project=%s root=%s", project_id, root)
            return _error(422, "project_root_missing", f"项目根目录不存在: {root}")

        logger.info("开始接口刷新: project=%s root=%s", project_id, root)
        summary = await service.scan(
            project_id,
            root,
            include_tests=options.include_tests,
        )
    except Exception:
        logger.exception("接口刷新失败: project=%s", project_id)
        return _error(500, "internal_error", "接口刷新失败，请查看服务日志")

    if summary.has_changes:
        try:
            bus.publish(
                make_event(
                    "interface.updated",
                    project_id,
                    payload={
                        "added": summary.added,
                        "updated": summary.updated,
                        "deleted": summary.deleted,
                        "scanned_files": summary.scanned_files,
                        "total_interfaces": summary.total_interfaces,
                    },
                )
            )
        except Exception:
            logger.exception(
                "interface.updated 事件发布失败（不影响刷新结果）: project=%s",
                project_id,
            )

    _start_watcher(
        service,
        project_id,
        root,
        include_tests=options.include_tests,
    )

    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "接口刷新完成: project=%s added=%d updated=%d deleted=%d 耗时=%.1fms",
        project_id,
        len(summary.added),
        len(summary.updated),
        len(summary.deleted),
        elapsed_ms,
    )
    return summary.to_dict()


@router.get("/health/interfaces", tags=["system"], summary="接口监听健康状态")
async def interfaces_health() -> dict:
    """C 的降级状态通过独立路径暴露，不改动 A 的 /health 契约。"""
    return watcher_manager.status()
