from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


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


class AgentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TERMINATED = "terminated"


class SessionInfo(BaseModel):
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
