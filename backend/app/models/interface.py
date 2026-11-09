from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, new_id


class InterfaceContract(TimestampMixin, Base):
    __tablename__ = "interface_contracts"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "file_path",
            "name",
            "version",
            name="uq_interface_contracts_identity_version",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: new_id("interface"),
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    module: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    params: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    returns: Mapped[str | None] = mapped_column(Text)
    docstring: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    commit_hash: Mapped[str | None] = mapped_column(String(64))
    dependencies: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    @property
    def interface_id(self) -> str:
        return self.id
