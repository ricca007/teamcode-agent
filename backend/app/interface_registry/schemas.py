"""C 负责的接口注册中心数据契约。

设计说明：
- 公共契约 ``InterfaceInfo`` 由 A 维护在 ``app.schemas.core``；
- C 在其基础上补充三个「展示字段」：行号、装饰器、是否 async。
  这三个字段不参与接口内容哈希，只影响前端展示，因此以子类方式扩展，
  不修改公共契约文件；
- REST / CLI / MCP / 前端使用同一份模型，避免各写一套字段。
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.schemas.core import InterfaceInfo as CoreInterfaceInfo
from app.schemas.core import ParamInfo


class InterfaceInfo(CoreInterfaceInfo):
    """在公共契约之上补充 C-1 提取的展示字段。"""

    lineno: int | None = None
    decorators: list[str] = Field(default_factory=list)
    is_async: bool = False


class InterfaceListResponse(BaseModel):
    """GET /api/projects/{id}/interfaces?format=json 的响应体。"""

    project_id: str
    generated_at: datetime
    count: int
    interfaces: list[InterfaceInfo]


class RefreshRequest(BaseModel):
    """手动触发重扫的可选参数。"""

    root: str | None = None
    include_tests: bool = False


def utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "InterfaceInfo",
    "InterfaceListResponse",
    "ParamInfo",
    "RefreshRequest",
    "utcnow",
]
