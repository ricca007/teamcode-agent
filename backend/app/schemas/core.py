from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


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

    @property
    def terminal(self) -> bool:
        return self in {
            AgentStatus.SUCCEEDED,
            AgentStatus.FAILED,
            AgentStatus.TERMINATED,
        }


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
    interface_requirements: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str]
    priority: int = 0
    base_branch: str = "main"

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "TaskSpec":
        def as_list(name: str) -> list[str]:
            raw = value.get(name, [])
            if isinstance(raw, str):
                return [raw]
            return [str(item) for item in raw or []]

        return cls(
            task_id=str(value["task_id"]),
            title=str(value.get("title", value["task_id"])),
            description=str(value.get("description", "")),
            owner_id=str(value["owner_id"]),
            allowed_paths=as_list("allowed_paths"),
            interface_requirements=as_list("interface_requirements"),
            depends_on=as_list("depends_on"),
            acceptance_criteria=as_list("acceptance_criteria"),
            priority=int(value.get("priority", 0)),
            base_branch=str(value.get("base_branch", "main")),
        )


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
    started_at: datetime = Field(default_factory=utc_now)
    ended_at: datetime | None = None

    def with_status(
        self,
        status: AgentStatus,
        ended_at: datetime | None = None,
    ) -> "SessionInfo":
        resolved_end = ended_at
        if resolved_end is None and status.terminal:
            resolved_end = utc_now()
        return self.model_copy(
            update={
                "status": status,
                "ended_at": resolved_end if resolved_end is not None else self.ended_at,
            }
        )


class ChangeSet(BaseModel):
    files: list[str] = Field(default_factory=list)
    diff: str = ""
    commit_hash: str | None = None

    @classmethod
    def from_values(
        cls,
        files: Iterable[str] = (),
        diff: str = "",
        commit_hash: str | None = None,
    ) -> "ChangeSet":
        return cls(
            files=sorted({str(item) for item in files}),
            diff=diff,
            commit_hash=commit_hash,
        )


class AgentLog(BaseModel):
    session_id: str
    task_id: str
    ts: datetime = Field(default_factory=utc_now)
    level: str
    message: str
    sequence: int = 0

    def as_event(self, project_id: str) -> dict[str, Any]:
        return {
            "type": "agent.log",
            "project_id": project_id,
            "task_id": self.task_id,
            "payload": {
                "session_id": self.session_id,
                "ts": self.ts.isoformat(),
                "level": self.level,
                "message": self.message,
                "sequence": self.sequence,
            },
            "ts": self.ts.isoformat(),
        }


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


class GitWorkspace(BaseModel):
    project_id: str
    task_id: str
    root: Path
    worktree_path: Path
    branch_name: str
    base_branch: str = "main"


class ExecutionResult(BaseModel):
    session_id: str
    task_id: str
    project_id: str
    status: AgentStatus
    workspace: str
    changes: ChangeSet
    rejected_paths: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    log_count: int = 0

    @property
    def ok(self) -> bool:
        return self.status == AgentStatus.SUCCEEDED and not self.rejected_paths

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "status": self.status.value,
            "workspace": self.workspace,
            "changes": self.changes.model_dump(mode="json"),
            "rejected_paths": self.rejected_paths,
            "rejection_reasons": self.rejection_reasons,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_ms": self.duration_ms,
            "log_count": self.log_count,
            "ok": self.ok,
        }


def task_prompt(task: TaskSpec, extra_context: str = "") -> str:
    lines = [
        "你正在执行 TeamCode Agent 的开发任务。",
        "开始前先拉取并阅读项目接口文档；如果命令不可用，则阅读 docs/interface_contract.md。",
        "接口定义以拉取到的文档为唯一事实来源，不要凭空猜测接口。",
        f"任务 ID：{task.task_id}",
        f"任务标题：{task.title}",
        f"任务描述：{task.description}",
        f"允许修改路径：{', '.join(task.allowed_paths)}",
    ]
    if task.interface_requirements:
        lines.append("接口要求：" + "; ".join(task.interface_requirements))
    if task.acceptance_criteria:
        lines.append("验收标准：" + "; ".join(task.acceptance_criteria))
    if extra_context:
        lines.append("额外上下文：" + extra_context)
    return "\n".join(lines)
