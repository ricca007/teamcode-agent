"""C 负责的接口注册中心扩展表。

这些表已经合并进公共 ``Base.metadata``，由同一份 Alembic 迁移和同一个
懒建表入口管理；``ensure_registry_tables`` 仍保留为幂等的懒建表入口。
"""

from __future__ import annotations

import asyncio
import logging
import weakref
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class InterfaceRegistryBase(Base):
    """C 负责表的声明基类（共享 ``Base.metadata``）。"""

    __abstract__ = True


class InterfaceState(InterfaceRegistryBase):
    """接口的运行时状态（与 interface_contracts 一对一）。

    拆表原因：公共模型是 A 的初版，C 的扩展字段不直接写进公共表。
    业务层以 ``interface_id`` 把两张表在内存中合并，查询规模在课程项目内
    完全可以接受。
    """

    __tablename__ = "interface_registry_state"

    interface_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # 仅包含签名/返回/docstring 的内容哈希，用于判断是否升版本
    content_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True, nullable=False
    )
    lineno: Mapped[int | None] = mapped_column(Integer)
    decorators: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_async: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class InterfaceVersion(InterfaceRegistryBase):
    """接口历史版本快照，version 自增，永不物理删除。"""

    __tablename__ = "interface_versions"

    version_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    interface_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    commit_hash: Mapped[str | None] = mapped_column(String(64))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# 同一个引擎只建一次表；WeakSet 避免引擎被回收后 id 复用时误判
_ensured_engines: weakref.WeakSet[AsyncEngine] = weakref.WeakSet()
# 按事件循环加锁，避免首次并发请求重复建表
_ensure_locks: dict[int, asyncio.Lock] = {}


async def ensure_registry_tables(engine: AsyncEngine) -> None:
    """懒建 C 负责的表（幂等、并发安全、失败有日志）。

    Alembic 已建表时 ``checkfirst`` 会自动跳过；单测和 CLI 离线模式
    不依赖迁移即可运行。
    """

    if engine in _ensured_engines:
        return

    loop = asyncio.get_running_loop()
    lock = _ensure_locks.setdefault(id(loop), asyncio.Lock())
    async with lock:
        if engine in _ensured_engines:
            return
        try:
            async with engine.begin() as connection:
                await connection.run_sync(InterfaceRegistryBase.metadata.create_all)
        except Exception:
            logger.exception("创建接口注册中心扩展表失败（engine=%s）", engine)
            raise
        _ensured_engines.add(engine)
        logger.info("接口注册中心扩展表就绪（engine=%s）", engine)
