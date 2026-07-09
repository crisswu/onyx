from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Any

from onyx.db.eva_config import get_eva_tools_config
from onyx.db.eva_config import get_eva_tools_config_for_user

DEFAULT_FETCH_INTERVAL_HOURS = 12
MIN_FETCH_INTERVAL_HOURS = 1
DEFAULT_RETENTION_DAYS = 30
DEFAULT_SEARCH_DAYS = 7
DEFAULT_SEARCH_LIMIT = 10
FAILING_FAILURE_THRESHOLD = 5


@dataclass(frozen=True)
class RssFeedSubscription:
    id: int
    name: str
    feed_url: str
    site_url: str | None
    category: str | None
    tags: list[str]
    enabled: bool
    archived_at: str | None
    fetch_interval_hours: int
    last_fetch_attempt_at: str | None
    last_success_at: str | None
    last_error: str | None
    consecutive_failures: int
    status: str
    priority_weight: float
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class RssArticleInput:
    title: str
    canonical_url: str | None
    source_name: str
    feed_guid: str | None = None
    feed_entry_url: str | None = None
    author: str | None = None
    published_at: str | None = None
    summary: str | None = None
    full_text: str | None = None
    language: str | None = None
    feed_tags: list[str] | None = None
    feed_category: str | None = None
    content_hash: str | None = None


@dataclass(frozen=True)
class RssUpsertResult:
    article_id: int
    is_new_article: bool
    is_new_source: bool


@dataclass(frozen=True)
class RssSearchResult:
    article_id: int
    title: str
    primary_source: str
    source_count: int
    seen_sources: list[str]
    published_at: str | None
    publication_time_unknown: bool
    first_seen_at: str
    summary: str
    canonical_url: str | None
    feed_tags: list[str]
    feed_category: str | None
    rank_score: float
    match_reason: str


@dataclass(frozen=True)
class RssSearchResponse:
    results: list[RssSearchResult]
    status: str
    latest_success_at: str | None
    searched_since: str
    searched_until: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _from_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _coerce_tags(tags: list[str] | str | None) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        try:
            parsed = json.loads(tags)
            if isinstance(parsed, list):
                tags = [str(item) for item in parsed]
            else:
                tags = tags.split(",")
        except json.JSONDecodeError:
            tags = tags.split(",")
    deduped: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        normalized = str(tag).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _coerce_fetch_interval(value: int | str | None) -> int:
    try:
        interval = int(value) if value is not None else DEFAULT_FETCH_INTERVAL_HOURS
    except (TypeError, ValueError):
        interval = DEFAULT_FETCH_INTERVAL_HOURS
    return max(MIN_FETCH_INTERVAL_HOURS, interval)


def _keyword_terms(query: str) -> list[str]:
    normalized = query.strip()
    if not normalized:
        return []
    if normalized.lower() in {"*", "all", "全部"}:
        return []

    terms = [normalized]
    terms.extend(term for term in normalized.split() if term)
    terms.extend(re.findall(r"[A-Za-z0-9_./:@-]+", normalized))
    cjk_runs = re.findall(r"[\u4e00-\u9fff]{2,}", normalized)
    terms.extend(cjk_runs)
    for cjk_run in cjk_runs:
        max_ngram = min(6, len(cjk_run))
        for size in range(2, max_ngram + 1):
            terms.extend(
                cjk_run[index : index + size]
                for index in range(0, len(cjk_run) - size + 1)
            )

    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        cleaned = term.strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def eva_rss_db_path_for_user(user_key: str | None = None) -> Path:
    if user_key is not None:
        config = get_eva_tools_config_for_user(user_key)
    else:
        config = get_eva_tools_config()

    if config.data_dir is not None:
        return config.data_dir / "rss.db"

    env_path = os.environ.get("EVA_RSS_DB_PATH")
    if env_path:
        return Path(env_path)

    candidates = [
        Path("/app/data/rss.db"),
        Path.cwd() / "data" / "rss.db",
        Path(__file__).resolve().parents[3] / "data" / "rss.db",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _subscription_from_row(row: sqlite3.Row) -> RssFeedSubscription:
    return RssFeedSubscription(
        id=int(row["id"]),
        name=str(row["name"]),
        feed_url=str(row["feed_url"]),
        site_url=str(row["site_url"]) if row["site_url"] is not None else None,
        category=str(row["category"]) if row["category"] is not None else None,
        tags=_from_json_list(row["tags"]),
        enabled=bool(row["enabled"]),
        archived_at=str(row["archived_at"]) if row["archived_at"] is not None else None,
        fetch_interval_hours=int(row["fetch_interval_hours"]),
        last_fetch_attempt_at=(
            str(row["last_fetch_attempt_at"])
            if row["last_fetch_attempt_at"] is not None
            else None
        ),
        last_success_at=(
            str(row["last_success_at"]) if row["last_success_at"] is not None else None
        ),
        last_error=str(row["last_error"]) if row["last_error"] is not None else None,
        consecutive_failures=int(row["consecutive_failures"]),
        status=str(row["status"]),
        priority_weight=float(row["priority_weight"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


class EvaRssDB:
    def __init__(self, db_path: Path | None = None, user_key: str | None = None) -> None:
        self.db_path = db_path or eva_rss_db_path_for_user(user_key)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return _connect(self.db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rss_feed_subscription (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    feed_url TEXT NOT NULL UNIQUE,
                    site_url TEXT,
                    category TEXT,
                    tags TEXT NOT NULL DEFAULT '[]',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    archived_at TEXT,
                    fetch_interval_hours INTEGER NOT NULL DEFAULT 12,
                    last_fetch_attempt_at TEXT,
                    last_success_at TEXT,
                    last_error TEXT,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'active',
                    priority_weight REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rss_article (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_url TEXT UNIQUE,
                    title TEXT NOT NULL,
                    author TEXT,
                    published_at TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    summary TEXT,
                    full_text TEXT,
                    language TEXT,
                    feed_tags TEXT NOT NULL DEFAULT '[]',
                    feed_category TEXT,
                    content_hash TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rss_article_source (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER NOT NULL,
                    subscription_id INTEGER NOT NULL,
                    source_name TEXT NOT NULL,
                    feed_guid TEXT,
                    feed_entry_url TEXT,
                    seen_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(article_id) REFERENCES rss_article(id) ON DELETE CASCADE,
                    FOREIGN KEY(subscription_id)
                        REFERENCES rss_feed_subscription(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rss_fetch_attempt (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subscription_id INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    item_count INTEGER NOT NULL DEFAULT 0,
                    new_article_count INTEGER NOT NULL DEFAULT 0,
                    updated_article_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    FOREIGN KEY(subscription_id)
                        REFERENCES rss_feed_subscription(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rss_article_content_hash
                ON rss_article(content_hash)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rss_article_published_at
                ON rss_article(published_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rss_article_first_seen
                ON rss_article(first_seen_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rss_article_source_article
                ON rss_article_source(article_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rss_article_source_subscription
                ON rss_article_source(subscription_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rss_article_source_guid
                ON rss_article_source(subscription_id, feed_guid)
                """
            )

    def add_subscription(
        self,
        *,
        name: str,
        feed_url: str,
        site_url: str | None = None,
        category: str | None = None,
        tags: list[str] | str | None = None,
        fetch_interval_hours: int | str | None = None,
        priority_weight: float = 1.0,
    ) -> RssFeedSubscription:
        now = utc_now_iso()
        clean_tags = _coerce_tags(tags)
        interval = _coerce_fetch_interval(fetch_interval_hours)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM rss_feed_subscription WHERE feed_url = ?",
                (feed_url,),
            ).fetchone()
            if existing is not None:
                conn.execute(
                    """
                    UPDATE rss_feed_subscription
                    SET name = ?,
                        site_url = COALESCE(?, site_url),
                        category = COALESCE(?, category),
                        tags = ?,
                        enabled = 1,
                        archived_at = NULL,
                        fetch_interval_hours = ?,
                        priority_weight = ?,
                        status = CASE
                            WHEN status = 'disabled' THEN 'active'
                            ELSE status
                        END,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        name,
                        site_url,
                        category,
                        _to_json(clean_tags),
                        interval,
                        float(priority_weight),
                        now,
                        int(existing["id"]),
                    ),
                )
                subscription_id = int(existing["id"])
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO rss_feed_subscription (
                        name,
                        feed_url,
                        site_url,
                        category,
                        tags,
                        enabled,
                        fetch_interval_hours,
                        priority_weight,
                        status,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?, 'active', ?, ?)
                    """,
                    (
                        name,
                        feed_url,
                        site_url,
                        category,
                        _to_json(clean_tags),
                        interval,
                        float(priority_weight),
                        now,
                        now,
                    ),
                )
                subscription_id = int(cursor.lastrowid)
        subscription = self.get_subscription(subscription_id)
        if subscription is None:
            raise RuntimeError("RSS subscription was not persisted")
        return subscription

    def get_subscription(self, subscription_id: int) -> RssFeedSubscription | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM rss_feed_subscription WHERE id = ?",
                (subscription_id,),
            ).fetchone()
        return _subscription_from_row(row) if row is not None else None

    def list_subscriptions(
        self,
        *,
        include_disabled: bool = True,
    ) -> list[RssFeedSubscription]:
        query = "SELECT * FROM rss_feed_subscription"
        params: tuple[Any, ...] = ()
        if not include_disabled:
            query += " WHERE enabled = 1 AND archived_at IS NULL"
        query += " ORDER BY enabled DESC, name ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_subscription_from_row(row) for row in rows]

    def update_subscription(
        self,
        subscription_id: int,
        *,
        name: str | None = None,
        category: str | None = None,
        tags: list[str] | str | None = None,
        fetch_interval_hours: int | str | None = None,
        priority_weight: float | None = None,
        enabled: bool | None = None,
    ) -> RssFeedSubscription | None:
        existing = self.get_subscription(subscription_id)
        if existing is None:
            return None

        now = utc_now_iso()
        new_enabled = existing.enabled if enabled is None else enabled
        archived_at = existing.archived_at
        status = existing.status
        if enabled is False:
            archived_at = archived_at or now
            status = "disabled"
        elif enabled is True:
            archived_at = None
            if status == "disabled":
                status = "active"

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE rss_feed_subscription
                SET name = ?,
                    category = ?,
                    tags = ?,
                    enabled = ?,
                    archived_at = ?,
                    fetch_interval_hours = ?,
                    priority_weight = ?,
                    status = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    name if name is not None else existing.name,
                    category if category is not None else existing.category,
                    (
                        _to_json(_coerce_tags(tags))
                        if tags is not None
                        else _to_json(existing.tags)
                    ),
                    1 if new_enabled else 0,
                    archived_at,
                    (
                        _coerce_fetch_interval(fetch_interval_hours)
                        if fetch_interval_hours is not None
                        else existing.fetch_interval_hours
                    ),
                    (
                        float(priority_weight)
                        if priority_weight is not None
                        else existing.priority_weight
                    ),
                    status,
                    now,
                    subscription_id,
                ),
            )
        return self.get_subscription(subscription_id)

    def due_subscriptions(self, *, now: datetime | None = None) -> list[RssFeedSubscription]:
        now_dt = now or utc_now()
        subscriptions = self.list_subscriptions(include_disabled=False)
        due: list[RssFeedSubscription] = []
        for subscription in subscriptions:
            if subscription.last_fetch_attempt_at is None:
                due.append(subscription)
                continue
            last_attempt = _parse_datetime(subscription.last_fetch_attempt_at)
            if last_attempt is None:
                due.append(subscription)
                continue
            if now_dt - last_attempt >= timedelta(
                hours=subscription.fetch_interval_hours
            ):
                due.append(subscription)
        return due

    def record_fetch_result(
        self,
        *,
        subscription_id: int,
        started_at: str,
        status: str,
        item_count: int = 0,
        new_article_count: int = 0,
        updated_article_count: int = 0,
        error: str | None = None,
    ) -> None:
        finished_at = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO rss_fetch_attempt (
                    subscription_id,
                    started_at,
                    finished_at,
                    status,
                    item_count,
                    new_article_count,
                    updated_article_count,
                    error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subscription_id,
                    started_at,
                    finished_at,
                    status,
                    item_count,
                    new_article_count,
                    updated_article_count,
                    error,
                ),
            )
            if status == "success":
                conn.execute(
                    """
                    UPDATE rss_feed_subscription
                    SET last_fetch_attempt_at = ?,
                        last_success_at = ?,
                        last_error = NULL,
                        consecutive_failures = 0,
                        status = CASE
                            WHEN enabled = 1 THEN 'active'
                            ELSE 'disabled'
                        END,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (finished_at, finished_at, finished_at, subscription_id),
                )
            else:
                row = conn.execute(
                    """
                    SELECT consecutive_failures, enabled
                    FROM rss_feed_subscription
                    WHERE id = ?
                    """,
                    (subscription_id,),
                ).fetchone()
                failures = int(row["consecutive_failures"]) + 1 if row else 1
                enabled = bool(row["enabled"]) if row else True
                next_status = (
                    "disabled"
                    if not enabled
                    else (
                        "failing"
                        if failures >= FAILING_FAILURE_THRESHOLD
                        else "active"
                    )
                )
                conn.execute(
                    """
                    UPDATE rss_feed_subscription
                    SET last_fetch_attempt_at = ?,
                        last_error = ?,
                        consecutive_failures = ?,
                        status = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        finished_at,
                        error,
                        failures,
                        next_status,
                        finished_at,
                        subscription_id,
                    ),
                )

    def upsert_article(
        self,
        subscription: RssFeedSubscription,
        article: RssArticleInput,
    ) -> RssUpsertResult:
        now = utc_now_iso()
        with self._connect() as conn:
            article_id = self._find_article_id(conn, subscription, article)
            is_new_article = article_id is None
            if article_id is None:
                cursor = conn.execute(
                    """
                    INSERT INTO rss_article (
                        canonical_url,
                        title,
                        author,
                        published_at,
                        first_seen_at,
                        last_seen_at,
                        summary,
                        full_text,
                        language,
                        feed_tags,
                        feed_category,
                        content_hash,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        article.canonical_url,
                        article.title,
                        article.author,
                        article.published_at,
                        now,
                        now,
                        article.summary,
                        article.full_text,
                        article.language,
                        _to_json(_coerce_tags(article.feed_tags)),
                        article.feed_category,
                        article.content_hash,
                        now,
                        now,
                    ),
                )
                article_id = int(cursor.lastrowid)
            else:
                conn.execute(
                    """
                    UPDATE rss_article
                    SET title = COALESCE(NULLIF(?, ''), title),
                        author = COALESCE(?, author),
                        published_at = COALESCE(?, published_at),
                        last_seen_at = ?,
                        summary = COALESCE(?, summary),
                        full_text = COALESCE(?, full_text),
                        language = COALESCE(?, language),
                        feed_tags = CASE
                            WHEN ? != '[]' THEN ?
                            ELSE feed_tags
                        END,
                        feed_category = COALESCE(?, feed_category),
                        content_hash = COALESCE(?, content_hash),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        article.title,
                        article.author,
                        article.published_at,
                        now,
                        article.summary,
                        article.full_text,
                        article.language,
                        _to_json(_coerce_tags(article.feed_tags)),
                        _to_json(_coerce_tags(article.feed_tags)),
                        article.feed_category,
                        article.content_hash,
                        now,
                        article_id,
                    ),
                )

            source_row = conn.execute(
                """
                SELECT id
                FROM rss_article_source
                WHERE article_id = ?
                  AND subscription_id = ?
                  AND COALESCE(feed_guid, '') = COALESCE(?, '')
                  AND COALESCE(feed_entry_url, '') = COALESCE(?, '')
                """,
                (
                    article_id,
                    subscription.id,
                    article.feed_guid,
                    article.feed_entry_url,
                ),
            ).fetchone()
            is_new_source = source_row is None
            if source_row is None:
                conn.execute(
                    """
                    INSERT INTO rss_article_source (
                        article_id,
                        subscription_id,
                        source_name,
                        feed_guid,
                        feed_entry_url,
                        seen_at,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        article_id,
                        subscription.id,
                        article.source_name,
                        article.feed_guid,
                        article.feed_entry_url,
                        now,
                        now,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE rss_article_source
                    SET source_name = ?,
                        seen_at = ?
                    WHERE id = ?
                    """,
                    (article.source_name, now, int(source_row["id"])),
                )
        return RssUpsertResult(
            article_id=article_id,
            is_new_article=is_new_article,
            is_new_source=is_new_source,
        )

    def _find_article_id(
        self,
        conn: sqlite3.Connection,
        subscription: RssFeedSubscription,
        article: RssArticleInput,
    ) -> int | None:
        if article.canonical_url:
            row = conn.execute(
                "SELECT id FROM rss_article WHERE canonical_url = ?",
                (article.canonical_url,),
            ).fetchone()
            if row is not None:
                return int(row["id"])

        if article.feed_guid:
            row = conn.execute(
                """
                SELECT article_id
                FROM rss_article_source
                WHERE subscription_id = ? AND feed_guid = ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (subscription.id, article.feed_guid),
            ).fetchone()
            if row is not None:
                return int(row["article_id"])

        if article.content_hash:
            row = conn.execute(
                """
                SELECT id
                FROM rss_article
                WHERE content_hash = ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (article.content_hash,),
            ).fetchone()
            if row is not None:
                return int(row["id"])

        return None

    def search_articles(
        self,
        query: str,
        *,
        time_range_hours: int | None = None,
        categories: list[str] | None = None,
        tags: list[str] | None = None,
        sources: list[str] | None = None,
        limit: int = DEFAULT_SEARCH_LIMIT,
        include_disabled_sources: bool = False,
        now: datetime | None = None,
    ) -> RssSearchResponse:
        now_dt = now or utc_now()
        hours = time_range_hours or DEFAULT_SEARCH_DAYS * 24
        since_dt = now_dt - timedelta(hours=hours)
        searched_since = since_dt.isoformat()
        searched_until = now_dt.isoformat()
        terms = _keyword_terms(query)
        categories_set = {item.lower() for item in categories or []}
        tags_set = {item.lower() for item in tags or []}
        sources_set = {item.lower() for item in sources or []}

        where = ["COALESCE(a.published_at, a.first_seen_at) >= ?"]
        params: list[Any] = [searched_since]
        if not include_disabled_sources:
            where.append("s.enabled = 1 AND s.archived_at IS NULL")
        sql = f"""
            SELECT
                a.*,
                GROUP_CONCAT(DISTINCT src.source_name) AS seen_sources,
                GROUP_CONCAT(DISTINCT s.name) AS subscription_names,
                COUNT(DISTINCT src.subscription_id) AS source_count,
                MAX(s.priority_weight) AS max_priority_weight,
                MAX(s.last_success_at) AS latest_success_at
            FROM rss_article a
            JOIN rss_article_source src ON src.article_id = a.id
            JOIN rss_feed_subscription s ON s.id = src.subscription_id
            WHERE {' AND '.join(where)}
            GROUP BY a.id
            ORDER BY COALESCE(a.published_at, a.first_seen_at) DESC
            LIMIT 500
        """
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            latest_row = conn.execute(
                "SELECT MAX(last_success_at) AS latest_success_at FROM rss_feed_subscription"
            ).fetchone()

        results: list[RssSearchResult] = []
        for row in rows:
            feed_category = (
                str(row["feed_category"]) if row["feed_category"] is not None else None
            )
            feed_tags = _from_json_list(row["feed_tags"])
            seen_sources = [
                source
                for source in str(row["seen_sources"] or "").split(",")
                if source
            ]
            subscription_names = [
                source
                for source in str(row["subscription_names"] or "").split(",")
                if source
            ]
            if categories_set and (feed_category or "").lower() not in categories_set:
                continue
            if tags_set and not tags_set.intersection({tag.lower() for tag in feed_tags}):
                continue
            searchable_sources = {source.lower() for source in seen_sources}
            searchable_sources.update(source.lower() for source in subscription_names)
            if sources_set and not sources_set.intersection(searchable_sources):
                continue

            text_fields = {
                "title": str(row["title"] or ""),
                "summary": str(row["summary"] or ""),
                "full_text": str(row["full_text"] or ""),
                "source": " ".join(seen_sources + subscription_names),
                "category": feed_category or "",
                "tags": " ".join(feed_tags),
            }
            keyword_score = self._keyword_score(terms, text_fields)
            if terms and keyword_score <= 0:
                continue

            published_at = (
                str(row["published_at"]) if row["published_at"] is not None else None
            )
            recency_time = _parse_datetime(published_at) or _parse_datetime(
                str(row["first_seen_at"])
            )
            freshness_score = 0.0
            if recency_time is not None:
                age_hours = max(
                    0.0,
                    (now_dt - recency_time).total_seconds() / 3600,
                )
                freshness_score = max(0.0, 1.0 - (age_hours / max(1, hours)))
                if published_at is None:
                    freshness_score *= 0.5

            source_count = int(row["source_count"] or 1)
            priority = float(row["max_priority_weight"] or 1.0)
            rank_score = (
                keyword_score * 10.0
                + freshness_score * 3.0
                + priority
                + min(source_count, 5) * 0.5
            )
            if not terms:
                rank_score = freshness_score * 3.0 + priority + min(source_count, 5) * 0.5

            results.append(
                RssSearchResult(
                    article_id=int(row["id"]),
                    title=str(row["title"]),
                    primary_source=seen_sources[0] if seen_sources else "RSS",
                    source_count=source_count,
                    seen_sources=seen_sources,
                    published_at=published_at,
                    publication_time_unknown=published_at is None,
                    first_seen_at=str(row["first_seen_at"]),
                    summary=str(row["summary"] or ""),
                    canonical_url=(
                        str(row["canonical_url"])
                        if row["canonical_url"] is not None
                        else None
                    ),
                    feed_tags=feed_tags,
                    feed_category=feed_category,
                    rank_score=rank_score,
                    match_reason=self._match_reason(terms, text_fields),
                )
            )

        results.sort(key=lambda result: result.rank_score, reverse=True)
        limited = results[: max(1, min(limit, 50))]
        latest_success_at = (
            str(latest_row["latest_success_at"])
            if latest_row and latest_row["latest_success_at"] is not None
            else None
        )
        latest_dt = _parse_datetime(latest_success_at)
        if latest_dt is None:
            status = "stale"
        elif now_dt - latest_dt > timedelta(hours=24):
            status = "stale"
        elif limited:
            status = "ok"
        else:
            status = "insufficient"

        return RssSearchResponse(
            results=limited,
            status=status,
            latest_success_at=latest_success_at,
            searched_since=searched_since,
            searched_until=searched_until,
        )

    def _keyword_score(self, terms: list[str], fields: dict[str, str]) -> float:
        if not terms:
            return 0.0
        score = 0.0
        weights = {
            "title": 4.0,
            "summary": 2.0,
            "full_text": 1.0,
            "source": 0.75,
            "category": 0.75,
            "tags": 0.75,
        }
        for field, text in fields.items():
            lowered = text.lower()
            for term in terms:
                if term in lowered:
                    score += weights.get(field, 1.0)
        return score

    def _match_reason(self, terms: list[str], fields: dict[str, str]) -> str:
        if not terms:
            return "freshness/source ranking"
        matched_fields: list[str] = []
        for field, text in fields.items():
            lowered = text.lower()
            if any(term in lowered for term in terms):
                matched_fields.append(field)
        if not matched_fields:
            return "metadata ranking"
        return "matched " + ", ".join(matched_fields)

    def cleanup_old_articles(
        self,
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        now: datetime | None = None,
    ) -> int:
        now_dt = now or utc_now()
        cutoff = (now_dt - timedelta(days=retention_days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id
                FROM rss_article
                WHERE COALESCE(last_seen_at, first_seen_at) < ?
                """,
                (cutoff,),
            ).fetchall()
            article_ids = [int(row["id"]) for row in rows]
            for article_id in article_ids:
                conn.execute(
                    "DELETE FROM rss_article_source WHERE article_id = ?",
                    (article_id,),
                )
                conn.execute("DELETE FROM rss_article WHERE id = ?", (article_id,))
        return len(article_ids)
