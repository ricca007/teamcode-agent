"""add plan snapshots table

Revision ID: 5d1e7a9c3b21
Revises: 8b7f1c2d4a90
Create Date: 2026-11-09 13:10:00.000000

说明（整合层）：
- A 的规划结果原本只在内存中返回；整合层把每个版本保存到 plan_snapshots，
  以便 GET /plan、重规划以及进程重启后恢复；
- 使用独立 metadata，不修改 A 的公共模型与迁移。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5d1e7a9c3b21"
down_revision: str | None = "8b7f1c2d4a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_snapshots")),
        sa.UniqueConstraint(
            "project_id",
            "version",
            name="uq_plan_snapshots_project_version",
        ),
    )
    op.create_index(
        op.f("ix_plan_snapshots_project_id"),
        "plan_snapshots",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_plan_snapshots_project_id"), table_name="plan_snapshots"
    )
    op.drop_table("plan_snapshots")
