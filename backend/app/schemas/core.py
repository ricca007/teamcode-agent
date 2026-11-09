from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UserRole(StrEnum):
    LEADER = "leader"
    MEMBER = "member"


class ProjectRole(StrEnum):
    OWNER = "owner"
    MEMBER = "member"


class TaskStatus(StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AgentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TERMINATED = "terminated"


class UserCreate(BaseModel):
    name: str
    email: str
    role: UserRole = UserRole.MEMBER


class UserRead(UserCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    name: str
    repo_path: str


class ProjectRead(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: str
    created_at: datetime
    updated_at: datetime


class ProjectMemberCreate(BaseModel):
    user_id: str
    role: ProjectRole = ProjectRole.MEMBER


class ProjectMemberRead(ProjectMemberCreate):
    model_config = ConfigDict(from_attributes=True)

    project_id: str
    created_at: datetime


class TaskSpec(BaseModel):
    task_id: str
    title: str
    description: str
    owner_id: str
    allowed_paths: list[str]
    interface_requirements: list[str]
    depends_on: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str]
    priority: int = 0


class TaskRead(TaskSpec):
    model_config = ConfigDict(from_attributes=True)

    project_id: str
    status: TaskStatus = TaskStatus.PLANNED
    replan_version: int = 1
    workspace_path: str | None = None
    branch_name: str | None = None
    created_at: datetime
    updated_at: datetime


class ParamInfo(BaseModel):
    name: str
    annotation: str | None = None
    default: str | None = None


class InterfaceInfo(BaseModel):
    interface_id: str
    project_id: str
    module: str
    file_path: str
    name: str
    kind: Literal["function", "method", "class"]
    params: list[ParamInfo]
    returns: str | None = None
    docstring: str | None = None
    version: int
    commit_hash: str | None = None
    dependencies: list[str] = Field(default_factory=list)


class SessionInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    task_id: str
    adapter: str
    status: AgentStatus
    workspace: str
    started_at: datetime


class ChangeSet(BaseModel):
    files: list[str]
    diff: str
    commit_hash: str | None = None


class AgentLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    ts: datetime
    level: str
    message: str


class CodeChangeRead(ChangeSet):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    task_id: str
