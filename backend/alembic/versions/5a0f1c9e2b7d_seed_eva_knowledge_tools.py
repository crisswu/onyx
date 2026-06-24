"""seed_eva_knowledge_tools

Revision ID: 5a0f1c9e2b7d
Revises: 01c63968ff8f
Create Date: 2026-06-22 15:10:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "5a0f1c9e2b7d"
down_revision = "01c63968ff8f"
branch_labels = None
depends_on = None


EVA_KNOWLEDGE_TOOLS = [
    {
        "name": "save_note",
        "display_name": "保存笔记",
        "description": "保存重要信息到从 EVA 复制来的个人知识库。",
        "in_code_tool_id": "SaveNoteTool",
        "enabled": True,
    },
    {
        "name": "search_notes",
        "display_name": "搜索笔记",
        "description": "搜索从 EVA 复制来的个人知识库。",
        "in_code_tool_id": "SearchNotesTool",
        "enabled": True,
    },
    {
        "name": "list_notes",
        "display_name": "列出笔记",
        "description": "统计或列出从 EVA 复制来的个人知识库记录。",
        "in_code_tool_id": "ListNotesTool",
        "enabled": True,
    },
    {
        "name": "update_note",
        "display_name": "修改笔记",
        "description": "按 ID 修改从 EVA 复制来的个人知识库记录。",
        "in_code_tool_id": "UpdateNoteTool",
        "enabled": True,
    },
    {
        "name": "delete_note",
        "display_name": "删除笔记",
        "description": "按 ID 删除从 EVA 复制来的个人知识库记录。",
        "in_code_tool_id": "DeleteNoteTool",
        "enabled": True,
    },
]


def upgrade() -> None:
    conn = op.get_bind()

    for tool in EVA_KNOWLEDGE_TOOLS:
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
    in_code_tool_ids = [tool["in_code_tool_id"] for tool in EVA_KNOWLEDGE_TOOLS]

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
