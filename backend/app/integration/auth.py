"""课堂版只保留项目 token 和成员角色，省去账号/审批/Key 管理系统。"""

import hashlib
import os
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.integration.models import AuthSession


@dataclass(frozen=True)
class Actor:
    user_id: str
    project_id: str | None = None
    key_project_id: str | None = None


def auth_required() -> bool:
    return os.getenv("TEAMCODE_REQUIRE_AUTH", "1") != "0"


def issue_session(db: AsyncSession, user_id: str, project_id: str) -> str:
    token = "tc_" + secrets.token_urlsafe(24)
    db.add(
        AuthSession(
            id=secrets.token_hex(12),
            user_id=user_id,
            project_id=project_id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
        )
    )
    return token


async def resolve_token(db: AsyncSession, token: str | None) -> AuthSession | None:
    if not token:
        return None
    return await db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == hashlib.sha256(token.encode()).hexdigest(),
            AuthSession.revoked.is_(False),
        )
    )


async def get_actor(
    request: Request, db: Annotated[AsyncSession, Depends(get_session)]
) -> Actor | None:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    record = await resolve_token(db, token)
    return Actor(record.user_id, record.project_id, record.project_id) if record else None
