from __future__ import annotations

from importlib import import_module
from typing import Any

from onyx.db.eva_rss import EvaRssDB
from onyx.db.eva_rss import RssArticleInput
from onyx.db.eva_rss import RssFeedSubscription
from onyx.db.eva_rss import utc_now_iso
from onyx.rss.models import FeedCandidate
from onyx.rss.models import FeedFetchResult
from onyx.rss.parser import canonicalize_url
from onyx.rss.parser import content_hash
from onyx.rss.parser import discover_feed_candidates
from onyx.rss.parser import parse_feed
from onyx.server.security.models import outbound_allow_private_network
from onyx.server.security.store import get_security_settings
from onyx.utils.url import ssrf_safe_get

RSS_FETCH_TIMEOUT_SECONDS = 20.0
RSS_FETCH_CONNECT_TIMEOUT_SECONDS = 5.0
MIN_SUMMARY_LENGTH_FOR_NO_EXTRACTION = 500
MAX_FEED_ENTRIES_PER_FETCH = 50
MAX_ARTICLE_EXTRACTIONS_PER_FETCH = 10
RSS_FETCH_USER_AGENT = "Onyx EVA RSS Intake/1.0"
RSS_FETCH_HEADERS = {
    "User-Agent": RSS_FETCH_USER_AGENT,
    "Accept": (
        "application/rss+xml, application/atom+xml, text/xml, "
        "application/xml, text/html;q=0.8"
    ),
}


def fetch_text(url: str, *, timeout: float = RSS_FETCH_TIMEOUT_SECONDS) -> str:
    response = ssrf_safe_get(
        url,
        headers=RSS_FETCH_HEADERS,
        timeout=(RSS_FETCH_CONNECT_TIMEOUT_SECONDS, timeout),
        follow_redirects=True,
        allow_private_network=outbound_allow_private_network(
            get_security_settings().ssrf_protection_level
        ),
    )
    response.raise_for_status()
    return response.text


def discover_or_parse_feed(url: str) -> tuple[list[FeedCandidate], str | None]:
    try:
        text = fetch_text(url)
    except Exception as error:
        return [], f"Unable to fetch URL: {error}"

    try:
        parsed = parse_feed(text, url)
        return [
            FeedCandidate(
                title=parsed.title or url,
                feed_url=canonicalize_url(url) or url,
                site_url=parsed.site_url,
            )
        ], None
    except Exception:
        candidates = discover_feed_candidates(text, url)
        if not candidates:
            return [], "No RSS/Atom feed candidates found"
        return candidates, None


def fetch_subscription_now(
    db: EvaRssDB,
    subscription: RssFeedSubscription,
) -> FeedFetchResult:
    started_at = utc_now_iso()
    try:
        feed_text = fetch_text(subscription.feed_url)
        parsed_feed = parse_feed(feed_text, subscription.feed_url)
        item_count = 0
        new_articles = 0
        updated_articles = 0
        extraction_count = 0
        source_name = parsed_feed.title or subscription.name
        for entry in parsed_feed.entries[:MAX_FEED_ENTRIES_PER_FETCH]:
            item_count += 1
            canonical_url = canonicalize_url(entry.url, subscription.feed_url)
            full_text = entry.content
            summary = entry.summary
            if (
                canonical_url
                and extraction_count < MAX_ARTICLE_EXTRACTIONS_PER_FETCH
                and _should_extract(summary, full_text)
            ):
                extraction_count += 1
                extracted = extract_article_text(canonical_url)
                if extracted:
                    full_text = extracted
            article_input = RssArticleInput(
                title=entry.title,
                canonical_url=canonical_url,
                source_name=source_name,
                feed_guid=entry.guid,
                feed_entry_url=entry.url,
                author=entry.author,
                published_at=entry.published_at,
                summary=summary,
                full_text=full_text,
                feed_tags=entry.tags or subscription.tags,
                feed_category=entry.category or subscription.category,
                content_hash=content_hash(entry.title, summary, full_text),
            )
            result = db.upsert_article(subscription, article_input)
            if result.is_new_article:
                new_articles += 1
            else:
                updated_articles += 1

        db.record_fetch_result(
            subscription_id=subscription.id,
            started_at=started_at,
            status="success",
            item_count=item_count,
            new_article_count=new_articles,
            updated_article_count=updated_articles,
        )
        return FeedFetchResult(
            subscription_id=subscription.id,
            item_count=item_count,
            new_article_count=new_articles,
            updated_article_count=updated_articles,
        )
    except Exception as error:
        error_text = str(error)
        db.record_fetch_result(
            subscription_id=subscription.id,
            started_at=started_at,
            status="error",
            error=error_text,
        )
        return FeedFetchResult(
            subscription_id=subscription.id,
            item_count=0,
            new_article_count=0,
            updated_article_count=0,
            error=error_text,
        )


def fetch_due_subscriptions(db: EvaRssDB) -> list[FeedFetchResult]:
    results: list[FeedFetchResult] = []
    for subscription in db.due_subscriptions():
        results.append(fetch_subscription_now(db, subscription))
    db.cleanup_old_articles()
    return results


def extract_article_text(url: str) -> str | None:
    try:
        html = fetch_text(url)
        trafilatura: Any = import_module("trafilatura")
        extracted = trafilatura.extract(html, url=url, include_comments=False)
        return str(extracted).strip() if extracted else None
    except Exception:
        return None


def _should_extract(summary: str | None, full_text: str | None) -> bool:
    if full_text and len(full_text.strip()) >= MIN_SUMMARY_LENGTH_FOR_NO_EXTRACTION:
        return False
    if summary and len(summary.strip()) >= MIN_SUMMARY_LENGTH_FOR_NO_EXTRACTION:
        return False
    return True
