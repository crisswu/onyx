from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeedCandidate:
    title: str
    feed_url: str
    site_url: str | None = None


@dataclass(frozen=True)
class ParsedFeedEntry:
    title: str
    url: str | None
    guid: str | None
    author: str | None
    published_at: str | None
    summary: str | None
    content: str | None
    tags: list[str]
    category: str | None


@dataclass(frozen=True)
class ParsedFeed:
    title: str | None
    site_url: str | None
    entries: list[ParsedFeedEntry]


@dataclass(frozen=True)
class FeedFetchResult:
    subscription_id: int
    item_count: int
    new_article_count: int
    updated_article_count: int
    error: str | None = None
