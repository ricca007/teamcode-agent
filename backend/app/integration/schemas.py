"""整合层 REST 请求模型。

响应直接使用 A/B/C 已有的 schema 或字典，避免再造一套契约。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.core import ProjectRole
from app.schemas.planning import TeamMemberSpec


class ProjectCreateRequest(BaseModel):
    name: str
    repo_path: str
    project_id: str | None = None
    owner_id: str | None = None
    owner_name: str | None = None
    owner_email: str | None = None

    @field_validator("name", "repo_path")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @field_validator("project_id")
    @classmethod
    def safe_project_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or not all(
            character.isalnum() or character in "._-" for character in value
        ):
            raise ValueError(
                "project_id 只能包含字母、数字、点、下划线和连字符"
            )
        return value


class MemberCreateRequest(BaseModel):
    user_id: str
    name: str | None = None
    email: str | None = None
    role: ProjectRole = ProjectRole.MEMBER

    @field_validator("user_id")
    @classmethod
    def user_id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("user_id must not be blank")
        return value.strip()


class RequirementsRequest(BaseModel):
    requirements: str
    members: list[TeamMemberSpec] = Field(default_factory=list)
    # 没有真实成员时，用 A/B/C 这类占位角色先分配任务
    roles: list[str] = Field(default_factory=list)
    max_tasks: int = Field(default=12, ge=1, le=50)
    mode: Literal["plan", "replan"] = "plan"

    @field_validator("requirements")
    @classmethod
    def requirements_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("requirements must not be blank")
        return value.strip()


class RunRequest(BaseModel):
    actor_id: str | None = None
    # agent_name 是每个成员可选的 Coding Agent（claude/codex/aider/自定义）
    agent_name: str | None = None
    adapter_name: str | None = None
    prompt: str | None = None
    context: dict[str, Any] | None = None
    base_branch: str = "main"


class CommitRequest(BaseModel):
    actor_id: str | None = None
    message: str

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("commit message must not be blank")
        return value.strip()


class MessageRequest(BaseModel):
    """会话内对话：向同一个 Worktree 里的 Claude 会话继续发消息。"""

    message: str
    actor_id: str | None = None

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value.strip()


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=6, max_length=128)

    @field_validator("name", "email")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class LoginRequest(BaseModel):
    email: str
    password: str


class JoinTeamRequest(BaseModel):
    areas: list[str] = Field(default_factory=list)


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    project_id: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value.strip()


class JoinRequestCreate(BaseModel):
    project_id: str
    display_name: str
    device_id: str
    device_secret: str = Field(min_length=16)

    @field_validator("project_id", "display_name", "device_id")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class ApproveJoinRequest(BaseModel):
    areas: list[str] = Field(default_factory=list)


class MergeTaskRequest(BaseModel):
    message: str = "merge task"
    base_branch: str = "main"

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value.strip()


class AssignTaskRequest(BaseModel):
    user_id: str

    @field_validator("user_id")
    @classmethod
    def user_id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("user_id must not be blank")
        return value.strip()
