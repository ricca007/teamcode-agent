"""WebSocket 路由：``/ws/projects/{project_id}``。

只负责连接建立/断开，事件格式由各模块通过 ``bus.publish`` 统一发送。
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.db import session_factory
from app.integration.auth import auth_required, resolve_token
from app.models.project import ProjectMember
from app.models.task import Task
from app.realtime.manager import bus, manager
from app.schemas.core import ProjectRole

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/projects/{project_id}")
async def project_socket(
    websocket: WebSocket,
    project_id: str,
    token: str | None = Query(default=None),
) -> None:
    allowed_tasks: set[str] | None = None
    member_id: str | None = None
    if auth_required():
        try:
            async with session_factory() as db:
                record = await resolve_token(db, token)
                if record is None or (
                    record.project_id is not None
                    and record.project_id != project_id
                ):
                    await websocket.close(code=4401)
                    return
                role = (
                    record.role
                    if record.project_id == project_id and record.role
                    else None
                )
                if role is None:
                    member = await db.get(
                        ProjectMember,
                        {
                            "project_id": project_id,
                            "user_id": record.user_id,
                        },
                    )
                    if member is None:
                        await websocket.close(code=4403)
                        return
                    role = (
                        "leader"
                        if member.role == ProjectRole.OWNER
                        else "member"
                    )
                if role != "leader":
                    member_id = record.user_id
                    allowed_tasks = set(
                        (
                            await db.scalars(
                                select(Task.id).where(
                                    Task.project_id == project_id,
                                    Task.owner_id == record.user_id,
                                )
                            )
                        ).all()
                    )
        except Exception:
            logger.exception("WebSocket 鉴权失败: project=%s", project_id)
            await websocket.close(code=1011)
            return

    try:
        await manager.connect(project_id, websocket, allowed_tasks, user_id=member_id)
        # 事件总线绑定当前事件循环：watcher 线程发布事件时据此跨线程广播
        bus.bind_loop(asyncio.get_running_loop())
        logger.info("WebSocket 已连接: project=%s", project_id)
    except Exception:
        logger.exception("WebSocket 建立连接失败: project=%s", project_id)
        return

    try:
        while True:
            message = await websocket.receive_text()
            # 轻量心跳，前端可据此判断连接活性
            if message == "ping":
                await websocket.send_json({"type": "pong", "project_id": project_id})
    except WebSocketDisconnect:
        logger.info("WebSocket 正常断开: project=%s", project_id)
    except Exception:
        logger.exception("WebSocket 会话异常: project=%s", project_id)
    finally:
        try:
            await manager.disconnect(project_id, websocket)
        except Exception:
            logger.exception("WebSocket 清理连接失败: project=%s", project_id)
