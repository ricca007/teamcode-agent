from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_values, new_id
from app.schemas.core import TaskStatus

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: new_id("task"),
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, values_callable=enum_values, native_enum=False, length=32),
        default=TaskStatus.PLANNED,
        index=True,
        nullable=False,
    )
    allowed_paths: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    interface_requirements: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    acceptance_criteria: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    replan_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    workspace_path: Mapped[str | None] = mapped_column(String(1024))
    branch_name: Mapped[str | None] = mapped_column(String(255))

    project: Mapped["Project"] = relationship(back_populates="tasks")
    owner: Mapped["User"] = relationship()
    dependencies: Mapped[list["Task"]] = relationship(
        secondary="task_dependencies",
        primaryjoin="Task.id == TaskDependency.task_id",
        secondaryjoin="Task.id == TaskDependency.depends_on_task_id",
        viewonly=True,
    )

    @property
    def task_id(self) -> str:
        return self.id

    @property
    def depends_on(self) -> list[str]:
        return [dependency.id for dependency in self.dependencies]


class TaskDependency(Base):
    __tablename__ = "task_dependencies"

    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    depends_on_task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )


def task_payload(task: Task) -> dict[str, Any]:
    return {
        "task_id": task.id,
        "project_id": task.project_id,
        "title": task.title,
        "description": task.description,
        "owner_id": task.owner_id,
        "allowed_paths": task.allowed_paths,
        "interface_requirements": task.interface_requirements,
        "depends_on": task.depends_on,
        "acceptance_criteria": task.acceptance_criteria,
        "priority": task.priority,
    }
