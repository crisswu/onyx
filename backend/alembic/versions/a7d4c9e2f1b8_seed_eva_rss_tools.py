"""seed_eva_rss_tools

Revision ID: a7d4c9e2f1b8
Revises: 9c8b7a6d5e4f
Create Date: 2026-07-09 11:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a7d4c9e2f1b8"
down_revision = "9c8b7a6d5e4f"
branch_labels = None
depends_on = None


EVA_RSS_TOOLS = [
    {
        "name": "add_rss_subscription",
        "display_name": "添加 RSS 订阅",
        "description": (
            "添加 RSS/Atom 订阅源到 EVA 本地 RSS 订阅池，支持从普通网页 URL "
            "发现 RSS feed。"
        ),
        "in_code_tool_id": "AddRssSubscriptionTool",
        "enabled": True,
    },
    {
        "name": "list_rss_subscriptions",
        "display_name": "列出 RSS 订阅",
        "description": "列出 EVA 本地 RSS 订阅源、抓取状态和健康信息。",
        "in_code_tool_id": "ListRssSubscriptionsTool",
        "enabled": True,
    },
    {
        "name": "update_rss_subscription",
        "display_name": "更新 RSS 订阅",
        "description": "更新、停用或重新启用 EVA 本地 RSS 订阅源。",
        "in_code_tool_id": "UpdateRssSubscriptionTool",
        "enabled": True,
    },
    {
        "name": "search_rss_articles",
        "display_name": "搜索 RSS 文章",
        "description": (
            "搜索 EVA 本地 RSS 订阅池中的 RSS/Atom 文章；仅用于用户明确要求 "
            "RSS 信息的场景。"
        ),
        "in_code_tool_id": "SearchRssArticlesTool",
        "enabled": True,
    },
]


def upgrade() -> None:
    conn = op.get_bind()

    for tool in EVA_RSS_TOOLS:
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
    in_code_tool_ids = [tool["in_code_tool_id"] for tool in EVA_RSS_TOOLS]

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
