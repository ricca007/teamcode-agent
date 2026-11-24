"""整合层的持久化模型。

这些表已经合并进公共 ``Base.metadata``，与 A / B / C 共用同一套命名约定，
由同一份 Alembic 迁移和同一个懒建表入口管理。
"""

from __future__ import annotations

import asyncio
import logging
import weakref
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class IntegrationBase(Base):
    """整合层表的声明基类（共享 ``Base.metadata``）。"""

    __abstract__ = True


class ApiKey(IntegrationBase):
    """程序化访问用的长期 Key（CLI / MCP / 外部 Coding Agent）。"""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(default=False, nullable=False)


class UserCredential(IntegrationBase):
    """全局账号密码（与 A 的 users 表一对一，避免修改公共模型）。"""

    __tablename__ = "user_credentials"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(
        String(320), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class JoinRequest(IntegrationBase):
    """浏览器设备申请加入团队，等待队长审批。"""

    __tablename__ = "join_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False)
    device_secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    areas: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True, nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(String(64))
    decided_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(IntegrationBase):
    """登录态 token，统一映射到用户 + 项目 + 角色。"""

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # 全局登录 token 的 project_id/role 为空；旧的项目级 token 保留兼容
    project_id: Mapped[str | None] = mapped_column(String(64), index=True)
    role: Mapped[str | None] = mapped_column(String(32))
    device_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(default=False, nullable=False)


class PlanSnapshot(IntegrationBase):
    """每次规划/重规划保存一份完整快照，供 GET /plan 与 replan 使用。"""

    __tablename__ = "plan_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "version", name="uq_plan_snapshots_project_version"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # PlanResult.model_dump(mode="json")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # 产生该版本的 PlanningRequest，replan 时直接复用
    request: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


_ensured_engines: weakref.WeakSet[AsyncEngine] = weakref.WeakSet()
_ensure_locks: dict[int, asyncio.Lock] = {}


async def ensure_integration_tables(engine: AsyncEngine) -> None:
    """懒建整合层表（幂等、并发安全、失败有日志）。"""

    if engine in _ensured_engines:
        return

    loop = asyncio.get_running_loop()
    lock = _ensure_locks.setdefault(id(loop), asyncio.Lock())
    async with lock:
        if engine in _ensured_engines:
            return
        try:
            async with engine.begin() as connection:
                await connection.run_sync(IntegrationBase.metadata.create_all)
        except Exception:
            logger.exception("创建整合层表失败（engine=%s）", engine)
            raise
        _ensured_engines.add(engine)
        logger.info("整合层表就绪（engine=%s）", engine)
