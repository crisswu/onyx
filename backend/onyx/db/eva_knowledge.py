from __future__ import annotations

import json
import os
import re
import sqlite3
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from onyx.db.eva_config import get_eva_knowledge_db_path
from onyx.db.eva_config import get_eva_knowledge_db_path_for_user
from onyx.utils.logger import setup_logger

logger = setup_logger()

VALID_EVA_FRAGMENT_TYPES = {"account", "bookmark", "diary", "code", "note"}
DEFAULT_EVA_EMBEDDING_MODEL = "BAAI/bge-large-zh-v1.5"
DEFAULT_EVA_EMBEDDING_API_BASE = "https://api.siliconflow.cn/v1"
DEFAULT_EVA_EMBEDDING_DIMENSION = 1024


@dataclass
class EvaKnowledgeFragment:
    title: str
    content: str
    type: str = "note"
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    original_content: str = ""
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    distance: float | None = None


def _knowledge_db_path() -> Path:
    configured_path = get_eva_knowledge_db_path()
    if configured_path is not None:
        return configured_path

    env_path = os.environ.get("EVA_KNOWLEDGE_DB_PATH")
    if env_path:
        return Path(env_path)

    candidates = [
        Path("/app/data/knowledge.db"),
        Path.cwd() / "data" / "knowledge.db",
        Path(__file__).resolve().parents[2] / "data" / "knowledge.db",
        Path(__file__).resolve().parents[3] / "data" / "knowledge.db",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[0]


def eva_knowledge_db_path_for_user(user_key: str | None) -> Path:
    configured_path = get_eva_knowledge_db_path_for_user(user_key)
    if configured_path is not None:
        return configured_path
    return _knowledge_db_path()


def _json_loads(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _serialize_float32(values: list[float]) -> bytes:
    return struct.pack(f"{len(values)}f", *values)


def _embedding_api_key() -> str | None:
    return (
        os.environ.get("EVA_EMBEDDING_API_KEY")
        or os.environ.get("EMBEDDING_API_KEY")
        or os.environ.get("LLM_API_KEY")
    )


def _generate_embedding_blob(title: str, content: str) -> bytes | None:
    api_key = _embedding_api_key()
    if not api_key:
        return None

    text = f"{title}\n{content}".strip()
    if not text:
        return None

    api_base = os.environ.get("EVA_EMBEDDING_API_BASE") or os.environ.get(
        "EMBEDDING_API_BASE", DEFAULT_EVA_EMBEDDING_API_BASE
    )
    model = os.environ.get("EVA_EMBEDDING_MODEL", DEFAULT_EVA_EMBEDDING_MODEL)
    timeout = float(os.environ.get("EVA_EMBEDDING_TIMEOUT_SECONDS", "20"))

    try:
        response = httpx.post(
            f"{api_base.rstrip('/')}/embeddings",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "input": text},
            timeout=timeout,
        )
        response.raise_for_status()
        embedding = response.json()["data"][0]["embedding"]
        if not isinstance(embedding, list):
            return None
        return _serialize_float32([float(value) for value in embedding])
    except Exception:
        logger.exception("Failed to generate EVA knowledge embedding")
        return None


def _try_load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    try:
        try:
            import sqlite_vec  # type: ignore[import-not-found]
        except ImportError:
            from onyx.vendor import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        return True
    except Exception:
        logger.debug("sqlite_vec unavailable; using keyword search for EVA knowledge")
        return False
    finally:
        try:
            conn.enable_load_extension(False)
        except Exception:
            pass


class EvaKnowledgeDB:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _knowledge_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fragments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    original_content TEXT DEFAULT '',
                    type TEXT NOT NULL DEFAULT 'note',
                    tags TEXT,
                    metadata TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fragments_type ON fragments(type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fragments_created ON fragments(created_at)"
            )

            if _try_load_sqlite_vec(conn):
                try:
                    conn.execute(
                        f"""
                        CREATE VIRTUAL TABLE IF NOT EXISTS fragments_vec USING vec0(
                            fragment_id INTEGER,
                            embedding FLOAT[{DEFAULT_EVA_EMBEDDING_DIMENSION}]
                        )
                        """
                    )
                except Exception:
                    logger.exception("Failed to ensure EVA fragments_vec table")

    def _row_to_fragment(self, row: sqlite3.Row) -> EvaKnowledgeFragment:
        row_keys = set(row.keys())
        tags_value = _json_loads(row["tags"], [])
        tags = [str(tag) for tag in tags_value] if isinstance(tags_value, list) else []
        metadata_value = _json_loads(row["metadata"], {})
        metadata = dict(metadata_value) if isinstance(metadata_value, Mapping) else {}
        return EvaKnowledgeFragment(
            id=int(row["id"]),
            title=str(row["title"]),
            content=str(row["content"]),
            original_content=str(row["original_content"] or ""),
            type=str(row["type"] or "note"),
            tags=tags,
            metadata=metadata,
            created_at=str(row["created_at"]) if row["created_at"] is not None else None,
            updated_at=str(row["updated_at"]) if row["updated_at"] is not None else None,
            distance=float(row["distance"]) if "distance" in row_keys else None,
        )

    def add(self, fragment: EvaKnowledgeFragment) -> int:
        now = datetime.now().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO fragments
                    (title, content, original_content, type, tags, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fragment.title,
                    fragment.content,
                    fragment.original_content or "",
                    fragment.type,
                    json.dumps(fragment.tags or [], ensure_ascii=False),
                    json.dumps(fragment.metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            fragment_id = int(cursor.lastrowid)
            self._replace_vector_rows(conn, fragment_id, fragment.title, fragment.content)
            return fragment_id

    def get(self, fragment_id: int) -> EvaKnowledgeFragment | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM fragments WHERE id = ?", (fragment_id,)
            ).fetchone()
        return self._row_to_fragment(row) if row else None

    def update(self, fragment: EvaKnowledgeFragment) -> bool:
        if fragment.id is None:
            raise ValueError("fragment.id is required")

        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE fragments
                SET title = ?, content = ?, original_content = ?, type = ?,
                    tags = ?, metadata = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    fragment.title,
                    fragment.content,
                    fragment.original_content or "",
                    fragment.type,
                    json.dumps(fragment.tags or [], ensure_ascii=False),
                    json.dumps(fragment.metadata or {}, ensure_ascii=False),
                    datetime.now().isoformat(),
                    fragment.id,
                ),
            )
            changed = cursor.rowcount > 0
            if changed:
                self._replace_vector_rows(
                    conn, fragment.id, fragment.title, fragment.content
                )
            return changed

    def delete(self, fragment_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM fragments WHERE id = ?", (fragment_id,))
            changed = cursor.rowcount > 0
            if changed:
                self._delete_vector_rows(conn, fragment_id)
            return changed

    def count(self, fragment_type: str | None = None) -> int:
        with self._connect() as conn:
            if fragment_type:
                row = conn.execute(
                    "SELECT COUNT(*) FROM fragments WHERE type = ?", (fragment_type,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM fragments").fetchone()
        return int(row[0])

    def list_by_type(
        self, fragment_type: str, limit: int = 50
    ) -> list[EvaKnowledgeFragment]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM fragments
                WHERE type = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (fragment_type, limit),
            ).fetchall()
        return [self._row_to_fragment(row) for row in rows]

    def list_all(self, limit: int = 100) -> list[EvaKnowledgeFragment]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM fragments
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_fragment(row) for row in rows]

    def search(
        self, query: str, type_filter: str | None = None, limit: int = 5
    ) -> list[EvaKnowledgeFragment]:
        vector_results = self._search_vector(query, type_filter, limit)
        if vector_results is not None:
            return vector_results
        return self._search_keyword(query, type_filter, limit)

    def _search_vector(
        self, query: str, type_filter: str | None, limit: int
    ) -> list[EvaKnowledgeFragment] | None:
        query_blob = _generate_embedding_blob(query, "")
        if query_blob is None:
            return None

        with self._connect() as conn:
            if not _try_load_sqlite_vec(conn):
                return None
            try:
                if type_filter:
                    rows = conn.execute(
                        """
                        SELECT f.*, v.distance
                        FROM fragments_vec v
                        JOIN fragments f ON v.fragment_id = f.id
                        WHERE v.embedding MATCH ? AND k = ? AND f.type = ?
                        ORDER BY v.distance
                        """,
                        (query_blob, limit * 2, type_filter),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT f.*, v.distance
                        FROM fragments_vec v
                        JOIN fragments f ON v.fragment_id = f.id
                        WHERE v.embedding MATCH ? AND k = ?
                        ORDER BY v.distance
                        """,
                        (query_blob, limit),
                    ).fetchall()
            except Exception:
                logger.exception("EVA vector search failed")
                return None

        return [self._row_to_fragment(row) for row in rows[:limit]]

    def _search_keyword(
        self, query: str, type_filter: str | None, limit: int
    ) -> list[EvaKnowledgeFragment]:
        terms = self._keyword_terms(query)

        where_parts: list[str] = []
        params: list[Any] = []
        if type_filter:
            where_parts.append("type = ?")
            params.append(type_filter)

        if terms:
            term_clauses = []
            for term in terms:
                term_clauses.append(
                    "(title LIKE ? OR content LIKE ? OR tags LIKE ? OR metadata LIKE ?)"
                )
                like = f"%{term}%"
                params.extend([like, like, like, like])
            where_parts.append("(" + " OR ".join(term_clauses) + ")")

        where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        sql = f"""
            SELECT * FROM fragments
            {where_sql}
            ORDER BY updated_at DESC, created_at DESC
        """

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        fragments = [self._row_to_fragment(row) for row in rows]
        fragments.sort(
            key=lambda fragment: self._keyword_score(fragment, query, terms),
            reverse=True,
        )
        return fragments[:limit]

    def _keyword_terms(self, query: str) -> list[str]:
        normalized = query.strip()
        if not normalized:
            return []

        terms: list[str] = [normalized]
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
            cleaned = term.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            deduped.append(cleaned)
        return deduped

    def _keyword_score(
        self, fragment: EvaKnowledgeFragment, query: str, terms: list[str]
    ) -> int:
        title = fragment.title.lower()
        content = fragment.content.lower()
        tags = json.dumps(fragment.tags or [], ensure_ascii=False).lower()
        metadata = json.dumps(fragment.metadata or {}, ensure_ascii=False).lower()
        normalized_query = query.strip().lower()

        score = 0
        if normalized_query:
            if normalized_query in title:
                score += 50
            if normalized_query in content:
                score += 25
            if normalized_query in tags or normalized_query in metadata:
                score += 10

        for term in terms:
            lowered = term.lower()
            if lowered in title:
                score += 10
            if lowered in content:
                score += 5
            if lowered in tags or lowered in metadata:
                score += 3
        return score

    def _replace_vector_rows(
        self, conn: sqlite3.Connection, fragment_id: int, title: str, content: str
    ) -> None:
        self._delete_vector_rows(conn, fragment_id)

        blob = _generate_embedding_blob(title, content)
        if blob is None or not _try_load_sqlite_vec(conn):
            return

        try:
            conn.execute(
                "INSERT INTO fragments_vec (fragment_id, embedding) VALUES (?, ?)",
                (fragment_id, blob),
            )
        except Exception:
            logger.exception("Failed to upsert EVA vector row")

    def _delete_vector_rows(self, conn: sqlite3.Connection, fragment_id: int) -> None:
        if not _try_load_sqlite_vec(conn):
            return
        try:
            conn.execute("DELETE FROM fragments_vec WHERE fragment_id = ?", (fragment_id,))
        except Exception:
            logger.exception("Failed to delete EVA vector rows")


def get_eva_knowledge_db(user_key: str | None = None) -> EvaKnowledgeDB:
    if user_key is not None:
        return EvaKnowledgeDB(eva_knowledge_db_path_for_user(user_key))
    return EvaKnowledgeDB()


def normalize_fragment_type(fragment_type: str | None) -> str | None:
    if fragment_type in VALID_EVA_FRAGMENT_TYPES:
        return fragment_type
    return None


def coerce_metadata(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return dict(parsed) if isinstance(parsed, Mapping) else None
        except json.JSONDecodeError:
            metadata: dict[str, Any] = {}
            for pair in value.split(","):
                if ":" not in pair:
                    continue
                key, item = pair.split(":", 1)
                metadata[key.strip()] = item.strip()
            return metadata or None
    return None
