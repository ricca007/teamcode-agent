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
