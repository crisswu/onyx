"""seed_eva_personal_tools

Revision ID: 6b7d8f2c4a91
Revises: 5a0f1c9e2b7d
Create Date: 2026-06-22 15:35:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "6b7d8f2c4a91"
down_revision = "5a0f1c9e2b7d"
branch_labels = None
depends_on = None


EVA_PERSONAL_TOOLS = [
    {
        "name": "recall_memory",
        "display_name": "回忆 EVA 记忆",
        "description": "搜索 EVA 的完整记忆，包括长期记忆、私人笔记、知识库、历史对话、联系人记录、画像和黑板。",
        "in_code_tool_id": "RecallMemoryTool",
        "enabled": True,
    },
    {
        "name": "ScheduleReminder",
        "display_name": "创建定时提醒",
        "description": "创建写入 EVA reminders 表的定时提醒。",
        "in_code_tool_id": "ScheduleReminderTool",
        "enabled": True,
    },
    {
        "name": "email_manager",
        "display_name": "邮箱管理",
        "description": "读取邮箱、提取验证码、搜索邮件和读取邮件正文。",
        "in_code_tool_id": "EmailManagerTool",
        "enabled": True,
    },
]


def upgrade() -> None:
    conn = op.get_bind()

    for tool in EVA_PERSONAL_TOOLS:
        existing = conn.execute(
            sa.text("SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
            {"in_code_tool_id": tool["in_code_tool_id"]},
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
                tool,
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
                tool,
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
    in_code_tool_ids = [tool["in_code_tool_id"] for tool in EVA_PERSONAL_TOOLS]

    conn.execute(
        sa.text(
            """
            DELETE FROM persona__tool
            WHERE tool_id IN (
                SELECT id
                FROM tool
                WHERE in_code_tool_id IN :in_code_tool_ids
            )
            """
        ).bindparams(sa.bindparam("in_code_tool_ids", expanding=True)),
        {"in_code_tool_ids": in_code_tool_ids},
    )

    conn.execute(
        sa.text(
            "DELETE FROM tool WHERE in_code_tool_id IN :in_code_tool_ids"
        ).bindparams(sa.bindparam("in_code_tool_ids", expanding=True)),
        {"in_code_tool_ids": in_code_tool_ids},
    )
