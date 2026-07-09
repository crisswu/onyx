from __future__ import annotations

from pathlib import Path

import pytest

from onyx.db.eva_rss import EvaRssDB
from onyx.rss import fetcher
from onyx.rss.fetcher import MAX_ARTICLE_EXTRACTIONS_PER_FETCH
from onyx.rss.fetcher import MAX_FEED_ENTRIES_PER_FETCH
from onyx.rss.fetcher import discover_or_parse_feed
from onyx.rss.fetcher import fetch_subscription_now


def test_discover_or_parse_feed_returns_error_for_fetch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_fetch_text(_url: str, *, timeout: float = 20.0) -> str:
        _ = timeout
        raise RuntimeError("blocked")

    monkeypatch.setattr(fetcher, "fetch_text", failing_fetch_text)

    candidates, error = discover_or_parse_feed("https://example.com")

    assert candidates == []
    assert error is not None
    assert "blocked" in error


def test_fetch_subscription_now_bounds_items_and_article_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = "\n".join(
        f"""
        <item>
          <title>Story {index}</title>
          <link>https://example.com/story/{index}</link>
          <guid>story-{index}</guid>
          <description>short</description>
        </item>
        """
        for index in range(MAX_FEED_ENTRIES_PER_FETCH + 10)
    )
    feed = f"""
    <rss version="2.0">
      <channel>
        <title>Example Feed</title>
        <link>https://example.com</link>
        {entries}
      </channel>
    </rss>
    """
    extraction_urls: list[str] = []

    def fake_fetch_text(_url: str, *, timeout: float = 20.0) -> str:
        _ = timeout
        return feed

    def fake_extract_article_text(url: str) -> str:
        extraction_urls.append(url)
        return "Extracted full text for RSS article. " * 3

    monkeypatch.setattr(fetcher, "fetch_text", fake_fetch_text)
    monkeypatch.setattr(fetcher, "extract_article_text", fake_extract_article_text)

    db = EvaRssDB(db_path=tmp_path / "rss.db")
    subscription = db.add_subscription(
        name="Example Feed",
        feed_url="https://example.com/feed.xml",
    )

    result = fetch_subscription_now(db, subscription)

    assert result.error is None
    assert result.item_count == MAX_FEED_ENTRIES_PER_FETCH
    assert result.new_article_count == MAX_FEED_ENTRIES_PER_FETCH
    assert len(extraction_urls) == MAX_ARTICLE_EXTRACTIONS_PER_FETCH
