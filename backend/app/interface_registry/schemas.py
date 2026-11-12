"""C 负责的接口注册中心数据契约。

设计说明：
- 公共契约 ``InterfaceInfo`` 由 A 维护在 ``app.schemas.core``；
- C 以子类补充行号、装饰器、是否 async 和参数调用约定；
  行号只影响展示，装饰器 / async / 参数调用约定参与契约版本比对；
  不修改 A 的公共模型文件；
- REST / CLI / MCP / 前端使用同一份模型，避免各写一套字段。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.core import InterfaceInfo as CoreInterfaceInfo
from app.schemas.core import ParamInfo as CoreParamInfo


class ParamInfo(CoreParamInfo):
    """C 的可选扩展：保存参数调用约定，不修改 A 的公共模型。"""

    kind: Literal[
        "positional_only", "positional_or_keyword", "var_positional", "keyword_only", "var_keyword"
    ] = "positional_or_keyword"


class InterfaceInfo(CoreInterfaceInfo):
    """在公共契约之上补充 C-1 提取的展示字段。"""

    params: list[ParamInfo] = Field(default_factory=list)
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
