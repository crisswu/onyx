"""seed_eva_bash_tool

Revision ID: 9c8b7a6d5e4f
Revises: d4e1c2b3a4f5
Create Date: 2026-06-23 09:50:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "9c8b7a6d5e4f"
down_revision = "d4e1c2b3a4f5"
branch_labels = None
depends_on = None


EVA_BASH_TOOL = {
    "name": "execute_bash",
    "display_name": "执行命令",
    "description": "复刻 EVA 的 Bash 命令执行工具，可在受控环境中执行 Linux 命令，包含危险命令黑名单、sudo 安全校验、超时和输出截断。",
    "in_code_tool_id": "ExecuteBashTool",
    "enabled": True,
}


def upgrade() -> None:
    conn = op.get_bind()

    existing = conn.execute(
        sa.text("SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": EVA_BASH_TOOL["in_code_tool_id"]},
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
            EVA_BASH_TOOL,
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
            EVA_BASH_TOOL,
        )
        tool_id = result.scalar_one()

    conn.execute(
        sa.text(
            """
            INSERT INTO persona__tool (persona_id, tool_id)
            SELECT id, :tool_id
            FROM persona
            WHERE deleted = false
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
        {"in_code_tool_id": EVA_BASH_TOOL["in_code_tool_id"]},
    )
    conn.execute(
        sa.text("DELETE FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": EVA_BASH_TOOL["in_code_tool_id"]},
    )
