"""add interface registry state and version tables

Revision ID: 8b7f1c2d4a90
Revises: 1133bcc80bab
Create Date: 2026-11-09 12:30:00.000000

说明（C 负责）：
- 公共表 interface_contracts 保持 A 的定义不变；
- C 的内容哈希 / 软删除 / 行号 / 装饰器 / async 标记放在
  interface_registry_state（与 interface_contracts 一对一）；
- 每次接口新增、更新、删除都向 interface_versions 追加一条快照。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8b7f1c2d4a90"
down_revision: str | None = "1133bcc80bab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interface_registry_state",
        sa.Column("interface_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("lineno", sa.Integer(), nullable=True),
        sa.Column("decorators", sa.JSON(), nullable=False),
        sa.Column("is_async", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("interface_id", name=op.f("pk_interface_registry_state")),
    )
    op.create_index(
        op.f("ix_interface_registry_state_project_id"),
        "interface_registry_state",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_interface_registry_state_is_deleted"),
        "interface_registry_state",
        ["is_deleted"],
        unique=False,
    )

    op.create_table(
        "interface_versions",
        sa.Column("version_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("interface_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("commit_hash", sa.String(length=64), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("version_id", name=op.f("pk_interface_versions")),
    )
    op.create_index(
        op.f("ix_interface_versions_interface_id"),
        "interface_versions",
        ["interface_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_interface_versions_project_id"),
        "interface_versions",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_interface_versions_project_id"), table_name="interface_versions"
    )
    op.drop_index(
        op.f("ix_interface_versions_interface_id"), table_name="interface_versions"
    )
    op.drop_table("interface_versions")
    op.drop_index(
        op.f("ix_interface_registry_state_is_deleted"),
        table_name="interface_registry_state",
    )
    op.drop_index(
        op.f("ix_interface_registry_state_project_id"),
        table_name="interface_registry_state",
    )
    op.drop_table("interface_registry_state")
