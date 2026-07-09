from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path

from onyx.db.eva_rss import DEFAULT_SEARCH_DAYS
from onyx.db.eva_rss import EvaRssDB
from onyx.db.eva_rss import RssArticleInput


def test_eva_rss_db_merges_strong_duplicates_and_preserves_sources(
    tmp_path: Path,
) -> None:
    db = EvaRssDB(db_path=tmp_path / "rss.db")
    source_a = db.add_subscription(name="A", feed_url="https://a.example/feed.xml")
    source_b = db.add_subscription(name="B", feed_url="https://b.example/feed.xml")

    first = db.upsert_article(
        source_a,
        RssArticleInput(
            title="Shared story",
            canonical_url="https://news.example/story",
            source_name="A",
            feed_guid="a-1",
            summary="A shared RSS story about manufacturing AI.",
            content_hash="same-hash",
        ),
    )
    second = db.upsert_article(
        source_b,
        RssArticleInput(
            title="Shared story",
            canonical_url="https://news.example/story",
            source_name="B",
            feed_guid="b-1",
            summary="A shared RSS story about manufacturing AI.",
            content_hash="same-hash",
        ),
    )

    assert first.article_id == second.article_id
    response = db.search_articles("manufacturing AI")
    assert len(response.results) == 1
    assert response.results[0].source_count == 2
    assert response.results[0].seen_sources == ["A", "B"]


def test_eva_rss_db_does_not_merge_title_similar_articles(tmp_path: Path) -> None:
    db = EvaRssDB(db_path=tmp_path / "rss.db")
    source = db.add_subscription(name="A", feed_url="https://a.example/feed.xml")

    first = db.upsert_article(
        source,
        RssArticleInput(
            title="OpenAI releases agent update",
            canonical_url="https://example.com/a",
            source_name="A",
            summary="OpenAI releases an agent update with details.",
        ),
    )
    second = db.upsert_article(
        source,
        RssArticleInput(
            title="OpenAI agent update released",
            canonical_url="https://example.com/b",
            source_name="A",
            summary="A different article about the same event.",
        ),
    )

    assert first.article_id != second.article_id


def test_eva_rss_search_defaults_and_excludes_disabled_sources(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    db = EvaRssDB(db_path=tmp_path / "rss.db")
    active = db.add_subscription(name="Active", feed_url="https://a.example/feed.xml")
    disabled = db.add_subscription(
        name="Disabled",
        feed_url="https://b.example/feed.xml",
    )
    db.update_subscription(disabled.id, enabled=False)

    for index in range(12):
        db.upsert_article(
            active,
            RssArticleInput(
                title=f"AI story {index}",
                canonical_url=f"https://example.com/active/{index}",
                source_name="Active",
                published_at=(now - timedelta(hours=index)).isoformat(),
                summary="RSS item about AI agents.",
            ),
        )
    db.upsert_article(
        disabled,
        RssArticleInput(
            title="AI disabled source",
            canonical_url="https://example.com/disabled",
            source_name="Disabled",
            published_at=now.isoformat(),
            summary="RSS item about AI agents.",
        ),
    )
    db.upsert_article(
        active,
        RssArticleInput(
            title="Old AI story",
            canonical_url="https://example.com/old",
            source_name="Active",
            published_at=(now - timedelta(days=DEFAULT_SEARCH_DAYS + 1)).isoformat(),
            summary="RSS item about AI agents.",
        ),
    )

    response = db.search_articles("AI agents", now=now)

    assert len(response.results) == 10
    assert all(result.primary_source != "Disabled" for result in response.results)
    assert all(result.title != "Old AI story" for result in response.results)

    with_disabled = db.search_articles(
        "AI agents",
        include_disabled_sources=True,
        now=now,
    )

    assert any(result.primary_source == "Disabled" for result in with_disabled.results)


def test_eva_rss_search_source_filter_matches_subscription_name(
    tmp_path: Path,
) -> None:
    db = EvaRssDB(db_path=tmp_path / "rss.db")
    subscription = db.add_subscription(
        name="中国新闻网要闻导读",
        feed_url="https://www.chinanews.com.cn/rss/importnews.xml",
    )
    db.upsert_article(
        subscription,
        RssArticleInput(
            title="特朗普称将要求最高法院重审案件",
            canonical_url="https://www.chinanews.com/example",
            source_name="中新网要闻导读",
            summary="中新网7月9日电 国际新闻。",
        ),
    )

    response = db.search_articles(
        "特朗普",
        sources=["中国新闻网要闻导读"],
    )

    assert len(response.results) == 1
    assert response.results[0].title == "特朗普称将要求最高法院重审案件"
