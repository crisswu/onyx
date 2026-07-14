"""seed_eva_backup_tool

Revision ID: b4c8f2a9e1d3
Revises: a7d4c9e2f1b8
Create Date: 2026-07-14 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b4c8f2a9e1d3"
down_revision = "a7d4c9e2f1b8"
branch_labels = None
depends_on = None


EVA_BACKUP_TOOL = {
    "name": "backup_eva_data_to_oss",
    "display_name": "备份 EVA 数据",
    "description": (
        "手动将 EVA 核心数据文件 knowledge.db 和 conversation.db 备份到"
        "管理员配置的阿里云 OSS。"
    ),
    "in_code_tool_id": "BackupEvaDataToOssTool",
    "enabled": True,
}


def upgrade() -> None:
    conn = op.get_bind()
    existing = conn.execute(
        sa.text("SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": EVA_BACKUP_TOOL["in_code_tool_id"]},
    ).fetchone()

    if existing:
        conn.execute(
            sa.text(
                """
                UPDATE tool
                SET name = :name,
                    display_name = :display_name,
                    description = :description,
                    enabled = :enabled
                WHERE in_code_tool_id = :in_code_tool_id
                """
            ),
            EVA_BACKUP_TOOL,
        )
        tool_id = existing[0]
    else:
        result = conn.execute(
            sa.text(
                """
                INSERT INTO tool
                    (name, display_name, description, in_code_tool_id, enabled)
                VALUES
                    (:name, :display_name, :description, :in_code_tool_id, :enabled)
                RETURNING id
                """
            ),
            EVA_BACKUP_TOOL,
        )
        tool_id = result.scalar_one()

    conn.execute(
        sa.text(
            """
            INSERT INTO persona__tool (persona_id, tool_id)
            SELECT id, :tool_id
            FROM persona
            WHERE id = 0 AND deleted = false
            ON CONFLICT DO NOTHING
            """
        ),
        {"tool_id": tool_id},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM persona__tool
            WHERE tool_id IN (
                SELECT id
                FROM tool
                WHERE in_code_tool_id = :in_code_tool_id
            )
            """
        ),
        {"in_code_tool_id": EVA_BACKUP_TOOL["in_code_tool_id"]},
    )
    conn.execute(
        sa.text("DELETE FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": EVA_BACKUP_TOOL["in_code_tool_id"]},
    )
