"""add user credentials and global auth sessions

Revision ID: 9a6c2f4d8e11
Revises: 7c4b9d2e6f10
Create Date: 2026-11-09 15:00:00.000000

注册制：
- 新增 user_credentials（全局账号密码）；
- auth_sessions.project_id / role 改为可空，表示全局登录 token；
- 角色改为每次请求从 project_members 查询，同一账号可跨项目。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9a6c2f4d8e11"
down_revision: str | None = "7c4b9d2e6f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_credentials",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_credentials")),
    )
    op.create_index(
        op.f("ix_user_credentials_email"),
        "user_credentials",
        ["email"],
        unique=True,
    )
    with op.batch_alter_table("auth_sessions") as batch:
        batch.alter_column(
            "project_id", existing_type=sa.String(length=64), nullable=True
        )
        batch.alter_column(
            "role", existing_type=sa.String(length=32), nullable=True
        )


def downgrade() -> None:
    with op.batch_alter_table("auth_sessions") as batch:
        batch.alter_column(
            "role", existing_type=sa.String(length=32), nullable=False
        )
        batch.alter_column(
            "project_id", existing_type=sa.String(length=64), nullable=False
        )
    op.drop_index(
        op.f("ix_user_credentials_email"), table_name="user_credentials"
    )
    op.drop_table("user_credentials")
