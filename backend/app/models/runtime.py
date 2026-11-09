from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, enum_values, new_id
from app.schemas.core import AgentStatus

if TYPE_CHECKING:
    from app.models.task import Task


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: new_id("session"),
    )
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    adapter: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, values_callable=enum_values, native_enum=False, length=32),
        default=AgentStatus.PENDING,
        index=True,
        nullable=False,
    )
    workspace: Mapped[str] = mapped_column(String(1024), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    task: Mapped["Task"] = relationship()
    logs: Mapped[list["AgentLog"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    code_changes: Mapped[list["CodeChange"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )

    @property
    def session_id(self) -> str:
        return self.id


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: new_id("log"),
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
        nullable=False,
    )
    level: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    session: Mapped["AgentSession"] = relationship(back_populates="logs")


class CodeChange(Base):
    __tablename__ = "code_changes"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: new_id("change"),
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    files: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    diff: Mapped[str] = mapped_column(Text, default="", nullable=False)
    commit_hash: Mapped[str | None] = mapped_column(String(64))

    session: Mapped["AgentSession"] = relationship(back_populates="code_changes")
