"""add_feishu_user_binding

Revision ID: 0d6fd0f2f641
Revises: 9c8b7a6d5e4f
Create Date: 2026-07-02 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0d6fd0f2f641"
down_revision: str | None = "9c8b7a6d5e4f"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "feishu_user_binding",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("open_id", sa.Text(), nullable=True),
        sa.Column("union_id", sa.Text(), nullable=True),
        sa.Column("tenant_key", sa.Text(), nullable=True),
        sa.Column("bind_code", sa.String(length=32), nullable=True),
        sa.Column("bind_code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bind_code", name="uq_feishu_user_binding_bind_code"),
        sa.UniqueConstraint("open_id", name="uq_feishu_user_binding_open_id"),
        sa.UniqueConstraint("user_id", name="uq_feishu_user_binding_user_id"),
    )
    op.create_index(
        "ix_feishu_user_binding_union_id",
        "feishu_user_binding",
        ["union_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_feishu_user_binding_union_id", table_name="feishu_user_binding")
    op.drop_table("feishu_user_binding")
