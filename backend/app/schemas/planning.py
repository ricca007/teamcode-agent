from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.core import ParamInfo, TaskSpec


class TeamMemberSpec(BaseModel):
    member_id: str
    name: str
    areas: list[str] = Field(default_factory=list)


class PlanningRequest(BaseModel):
    project_id: str
    requirements: str
    repo_path: str
    members: list[TeamMemberSpec] = Field(min_length=1)
    max_tasks: int = Field(default=12, ge=1, le=50)

    @field_validator("requirements")
    @classmethod
    def requirements_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("requirements must not be blank")
        return value


class RepositoryModuleSnapshot(BaseModel):
    module: str
    file_path: str
    classes: list[str] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)


class RepositorySnapshot(BaseModel):
    root_path: str
    modules: list[RepositoryModuleSnapshot] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)
    truncated: bool = False


class InterfaceContractDraft(BaseModel):
    interface_id: str
    module: str
    file_path: str
    name: str
    kind: Literal["function", "method", "class"] = "class"
    params: list[ParamInfo] = Field(default_factory=list)
    returns: str | None = None
    docstring: str | None = None
    dependencies: list[str] = Field(default_factory=list)


class PlannedTask(TaskSpec):
    module: str


class PlanResult(BaseModel):
    project_id: str
    version: int = 1
    normalized_requirements: list[str]
    repository: RepositorySnapshot
    tasks: list[PlannedTask]
    interface_contracts: list[InterfaceContractDraft]


class TaskFieldChange(BaseModel):
    task_id: str
    changed_fields: list[str]


class TaskDependencyChange(BaseModel):
    task_id: str
    before: list[str] = Field(default_factory=list)
    after: list[str] = Field(default_factory=list)


class InterfaceContractChange(BaseModel):
    interface_id: str
    change_type: Literal["added", "removed", "updated"]
    before: InterfaceContractDraft | None = None
    after: InterfaceContractDraft | None = None


class PlanDiff(BaseModel):
    added_tasks: list[str] = Field(default_factory=list)
    removed_tasks: list[str] = Field(default_factory=list)
    updated_tasks: list[TaskFieldChange] = Field(default_factory=list)
    unchanged_tasks: list[str] = Field(default_factory=list)
    dependency_changes: list[TaskDependencyChange] = Field(default_factory=list)
    interface_changes: list[InterfaceContractChange] = Field(default_factory=list)
    impact_notes: list[str] = Field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.added_tasks
            or self.removed_tasks
            or self.updated_tasks
            or self.dependency_changes
            or self.interface_changes
        )


class ReplanResult(BaseModel):
    previous_version: int
    plan: PlanResult
    diff: PlanDiff
