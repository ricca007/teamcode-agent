"""设备身份、加入申请与 token 鉴权。

设计：
- 浏览器持久化 ``device_id`` + ``device_secret``；
- 加入团队时只保存 ``device_secret`` 的哈希；
- 队长批准后，成员用 device_secret 轮询状态；服务端用
  HMAC(request_id, device_secret) 派生稳定 token，因此成员丢失本地 token
  后仍可恢复；
- 队长创建项目时签发随机 leader token；
- ``get_actor`` 依赖把 token 解析成 (user_id, project_id, role)，
  业务层不再信任客户端传入的 actor_id。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.integration.models import ApiKey, AuthSession
from app.models.user import User

logger = logging.getLogger(__name__)


def auth_required() -> bool:
    return os.getenv("TEAMCODE_REQUIRE_AUTH", "1") != "0"


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_token() -> str:
    return "tc_" + secrets.token_urlsafe(32)


def derive_join_token(request_id: str, device_secret: str) -> str:
    secret = os.getenv("TEAMCODE_AUTH_SECRET", "teamcode-dev-secret")
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{request_id}:{device_secret}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return "tc_" + digest


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 200_000
    ).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 200_000
    ).hex()
    return hmac.compare_digest(candidate, digest)


@dataclass(frozen=True)
class Actor:
    session_id: str
    user_id: str
    name: str
    # 全局 token：project_id/role 为空，角色按项目实时查询
    # 旧的项目级 token：保留这两个字段用于兼容
    project_id: str | None = None
    role: str | None = None
    # API Key 可选的项目范围
    key_project_id: str | None = None


def extract_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        if token:
            return token
    token = request.headers.get("x-api-key", "").strip()
    if token:
        return token
    token = request.headers.get("x-session-token", "").strip()
    if token:
        return token
    cookie = request.cookies.get("teamcode_token", "").strip()
    return cookie or None


async def resolve_token(
    db: AsyncSession, token: str | None
) -> AuthSession | None:
    if not token:
        return None
    return await db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == hash_secret(token),
            AuthSession.revoked.is_(False),
        )
    )


async def get_actor(
    request: Request,
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> Actor | None:
    token = extract_token(request)
    session = await resolve_token(db, token)
    if session is not None:
        user = await db.get(User, session.user_id)
        return Actor(
            session_id=session.id,
            user_id=session.user_id,
            name=user.name if user is not None else session.user_id,
            project_id=session.project_id,
            role=session.role,
        )

    # API Key 也是 Bearer token，角色按项目实时查询
    if token:
        api_key = await db.scalar(
            select(ApiKey).where(
                ApiKey.key_hash == hash_secret(token),
                ApiKey.revoked.is_(False),
            )
        )
        if api_key is not None:
            user = await db.get(User, api_key.user_id)
            return Actor(
                session_id=api_key.id,
                user_id=api_key.user_id,
                name=user.name if user is not None else api_key.user_id,
                project_id=None,
                role=None,
                key_project_id=api_key.project_id,
            )
    return None


def issue_session(
    db: AsyncSession,
    *,
    user_id: str,
    project_id: str | None = None,
    role: str | None = None,
    token: str | None = None,
    device_id: str | None = None,
) -> tuple[AuthSession, str]:
    raw = token or new_token()
    session = AuthSession(
        id=f"auth_{secrets.token_hex(8)}",
        token_hash=hash_secret(raw),
        user_id=user_id,
        project_id=project_id,
        role=role,
        device_id=device_id,
        created_at=datetime.now(UTC),
    )
    db.add(session)
    return session, raw
