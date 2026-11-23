"""add agent log sequence

Revision ID: f2a7c1d9e4b3
Revises: c3d8e1f5a7b2
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2a7c1d9e4b3"
down_revision: str | None = "c3d8e1f5a7b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_logs",
        sa.Column(
            "sequence",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_agent_logs_session_id_sequence",
        "agent_logs",
        ["session_id", "sequence"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_logs_session_id_sequence",
        table_name="agent_logs",
    )
    op.drop_column("agent_logs", "sequence")
