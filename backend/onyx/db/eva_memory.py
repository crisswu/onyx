from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from onyx.db.eva_config import get_eva_conversation_db_path
from onyx.db.eva_config import get_eva_conversation_db_path_for_user
from onyx.db.eva_config import get_eva_knowledge_db_path
from onyx.db.eva_config import get_eva_knowledge_db_path_for_user
from onyx.db.eva_config import get_eva_tools_config
from onyx.db.eva_config import get_eva_tools_config_for_user
from onyx.db.eva_knowledge import _generate_embedding_blob
from onyx.db.eva_knowledge import _try_load_sqlite_vec


VALID_EVA_MEMORY_SCOPES = {
    "all",
    "conversations",
    "memories",
    "notes",
    "knowledge",
    "contacts",
    "profile",
}


@dataclass
class EvaMemoryItem:
    source: str
    id: int
    content: str
    timestamp: str | None = None
    title: str | None = None
    metadata: dict[str, Any] | None = None
    distance: float | None = None
    score: int = 0


@dataclass
class EvaProfileSnapshot:
    criss_profile: str | None
    relationship_state: dict[str, Any] | None
    blackboards: list[EvaMemoryItem]
    counts: dict[str, int]


@dataclass
class EvaMemorySearchResult:
    profile: EvaProfileSnapshot | None
    items_by_source: dict[str, list[EvaMemoryItem]]


def normalize_eva_memory_scope(scope: str | None) -> str:
    normalized = (scope or "all").strip().lower()
    if normalized in VALID_EVA_MEMORY_SCOPES:
        return normalized
    return "all"


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        conn = sqlite3.connect(":memory:", timeout=30)
    else:
        conn = sqlite3.connect(f"file:{path}?mode=ro", timeout=30, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _connect_readonly(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", timeout=30, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _keyword_terms(query: str) -> list[str]:
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


def _keyword_where(columns: list[str], terms: list[str]) -> tuple[str, list[Any]]:
    if not terms:
        return "", []

    clauses: list[str] = []
    params: list[Any] = []
    for term in terms:
        term_clauses = [f"{column} LIKE ?" for column in columns]
        clauses.append("(" + " OR ".join(term_clauses) + ")")
        params.extend([f"%{term}%"] * len(columns))
    return "WHERE " + " OR ".join(clauses), params


def _keyword_score(query: str, terms: list[str], weighted_text: dict[str, int]) -> int:
    normalized_query = query.strip().lower()
    score = 0

    for text, weight in weighted_text.items():
        lowered = text.lower()
        if normalized_query and normalized_query in lowered:
            score += weight * 10
        for term in terms:
            if term.lower() in lowered:
                score += weight
    return score


def _json_loads(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


class EvaMemoryDB:
    def __init__(
        self,
        knowledge_db_path: Path | None = None,
        conversation_db_path: Path | None = None,
        user_key: str | None = None,
    ) -> None:
        self.user_key = user_key
        self.knowledge_db_path = (
            knowledge_db_path
            or (
                get_eva_knowledge_db_path_for_user(user_key)
                if user_key is not None
                else get_eva_knowledge_db_path()
            )
            or Path("/app/data/knowledge.db")
        )
        self.conversation_db_path = (
            conversation_db_path
            or (
                get_eva_conversation_db_path_for_user(user_key)
                if user_key is not None
                else get_eva_conversation_db_path()
            )
            or Path("/app/data/conversation.db")
        )

    def search(
        self,
        query: str,
        limit: int = 5,
        scope: str = "all",
        include_profile: bool = True,
    ) -> EvaMemorySearchResult:
        normalized_scope = normalize_eva_memory_scope(scope)
        per_source_limit = max(1, min(20, limit))
        terms = _keyword_terms(query)

        items_by_source: dict[str, list[EvaMemoryItem]] = {}

        if normalized_scope in {"all", "memories"}:
            items_by_source["长期记忆"] = self._search_memories(
                query, terms, per_source_limit
            )

        if normalized_scope in {"all", "notes"}:
            items_by_source["Eva私人笔记"] = self._search_eva_notes(
                query, terms, per_source_limit
            )

        if normalized_scope in {"all", "knowledge"}:
            items_by_source["个人知识库"] = self._search_fragments(
                query, terms, per_source_limit
            )

        if normalized_scope in {"all", "conversations"}:
            items_by_source["历史对话"] = self._search_conversations(
                query, terms, per_source_limit
            )

        if normalized_scope in {"all", "contacts"}:
            contact_items = self._search_contact_conversations(
                query, terms, per_source_limit
            )
            contact_items.extend(self._search_wechat_messages(query, terms, per_source_limit))
            contact_items.sort(key=lambda item: item.score, reverse=True)
            items_by_source["联系人/微信记录"] = contact_items[:per_source_limit]

        profile = None
        if include_profile and normalized_scope in {"all", "profile"}:
            profile = self.get_profile_snapshot()

        return EvaMemorySearchResult(profile=profile, items_by_source=items_by_source)

    def get_profile_snapshot(self) -> EvaProfileSnapshot:
        return EvaProfileSnapshot(
            criss_profile=self._read_criss_profile(),
            relationship_state=self._get_relationship_state(),
            blackboards=[],
            counts=self._get_counts(),
        )

    def get_recent_conversations(self, limit: int = 5) -> list[EvaMemoryItem]:
        safe_limit = max(1, min(20, limit))
        conn = _connect_readonly(self.conversation_db_path)
        if conn is None:
            return []
        with conn:
            if not _table_exists(conn, "conversations"):
                return []
            rows = conn.execute(
                """
                SELECT *
                FROM conversations
                ORDER BY id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()

        items = [
            EvaMemoryItem(
                source="conversations",
                id=int(row["id"]),
                content=f"Criss: {row['criss']}\nEva: {row['eva']}",
                timestamp=str(row["timestamp"]) if row["timestamp"] else None,
            )
            for row in reversed(rows)
        ]
        return items

    def _search_memories(
        self, query: str, terms: list[str], limit: int
    ) -> list[EvaMemoryItem]:
        vector_items = self._search_simple_vector_table(
            db_path=self.knowledge_db_path,
            table="memories",
            vector_table="memories_vec",
            join_id_column="memory_id",
            content_column="content",
            timestamp_column="created_at",
            query=query,
            limit=limit,
            source="memories",
        )
        if vector_items is not None:
            return vector_items

        with _connect(self.knowledge_db_path) as conn:
            if not _table_exists(conn, "memories"):
                return []
            where, params = _keyword_where(["content", "source", "type", "tags"], terms)
            rows = conn.execute(
                f"""
                SELECT *
                FROM memories
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                [*params, max(limit * 5, limit)],
            ).fetchall()

        items = [
            EvaMemoryItem(
                source="memories",
                id=int(row["id"]),
                content=str(row["content"]),
                timestamp=str(row["created_at"]) if row["created_at"] else None,
                metadata={
                    "type": row["type"] if "type" in row.keys() else "general",
                    "source": row["source"] if "source" in row.keys() else "",
                    "importance": row["importance"] if "importance" in row.keys() else 5,
                    "tags": _json_loads(row["tags"], [])
                    if "tags" in row.keys()
                    else [],
                },
                score=_keyword_score(
                    query,
                    terms,
                    {
                        str(row["content"]): 10,
                        str(row["type"] if "type" in row.keys() else ""): 2,
                        str(row["tags"] if "tags" in row.keys() else ""): 2,
                    },
                ),
            )
            for row in rows
        ]
        items.sort(key=lambda item: item.score, reverse=True)
        return items[:limit]

    def _search_eva_notes(
        self, query: str, terms: list[str], limit: int
    ) -> list[EvaMemoryItem]:
        vector_items = self._search_simple_vector_table(
            db_path=self.knowledge_db_path,
            table="eva_notes",
            vector_table="eva_notes_vec",
            join_id_column="note_id",
            content_column="content",
            timestamp_column="created_at",
            query=query,
            limit=limit,
            source="eva_notes",
        )
        if vector_items is not None:
            return vector_items

        with _connect(self.knowledge_db_path) as conn:
            if not _table_exists(conn, "eva_notes"):
                return []
            where, params = _keyword_where(["content"], terms)
            rows = conn.execute(
                f"""
                SELECT *
                FROM eva_notes
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                [*params, max(limit * 5, limit)],
            ).fetchall()

        items = [
            EvaMemoryItem(
                source="eva_notes",
                id=int(row["id"]),
                content=str(row["content"]),
                timestamp=str(row["created_at"]) if row["created_at"] else None,
                score=_keyword_score(query, terms, {str(row["content"]): 10}),
            )
            for row in rows
        ]
        items.sort(key=lambda item: item.score, reverse=True)
        return items[:limit]

    def _search_fragments(
        self, query: str, terms: list[str], limit: int
    ) -> list[EvaMemoryItem]:
        vector_items = self._search_fragments_vector(query, limit)
        if vector_items is not None:
            return vector_items

        with _connect(self.knowledge_db_path) as conn:
            if not _table_exists(conn, "fragments"):
                return []
            where, params = _keyword_where(
                ["title", "content", "original_content", "tags", "metadata"], terms
            )
            rows = conn.execute(
                f"""
                SELECT *
                FROM fragments
                {where}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                [*params, max(limit * 5, limit)],
            ).fetchall()

        items: list[EvaMemoryItem] = []
        for row in rows:
            metadata = _json_loads(row["metadata"], {})
            tags = _json_loads(row["tags"], [])
            items.append(
                EvaMemoryItem(
                    source="fragments",
                    id=int(row["id"]),
                    title=str(row["title"]),
                    content=str(row["content"]),
                    timestamp=str(row["updated_at"] or row["created_at"]),
                    metadata={
                        "type": row["type"],
                        "tags": tags,
                        "metadata": metadata if isinstance(metadata, dict) else {},
                    },
                    score=_keyword_score(
                        query,
                        terms,
                        {
                            str(row["title"]): 10,
                            str(row["content"]): 6,
                            str(row["tags"]): 3,
                            str(row["metadata"]): 3,
                        },
                    ),
                )
            )
        items.sort(key=lambda item: item.score, reverse=True)
        return items[:limit]

    def _search_conversations(
        self, query: str, terms: list[str], limit: int
    ) -> list[EvaMemoryItem]:
        vector_items = self._search_conversations_vector(query, limit)
        if vector_items is not None:
            return vector_items

        with _connect(self.conversation_db_path) as conn:
            if not _table_exists(conn, "conversations"):
                return []
            where, params = _keyword_where(["criss", "eva"], terms)
            rows = conn.execute(
                f"""
                SELECT *
                FROM conversations
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                [*params, max(limit * 5, limit)],
            ).fetchall()

        items = [
            EvaMemoryItem(
                source="conversations",
                id=int(row["id"]),
                content=f"Criss: {row['criss']}\nEva: {row['eva']}",
                timestamp=str(row["timestamp"]) if row["timestamp"] else None,
                score=_keyword_score(
                    query,
                    terms,
                    {str(row["criss"]): 10, str(row["eva"]): 5},
                ),
            )
            for row in rows
        ]
        items.sort(key=lambda item: item.score, reverse=True)
        return items[:limit]

    def _search_contact_conversations(
        self, query: str, terms: list[str], limit: int
    ) -> list[EvaMemoryItem]:
        with _connect(self.conversation_db_path) as conn:
            if not _table_exists(conn, "contact_conversations"):
                return []
            where, params = _keyword_where(["sender", "content"], terms)
            rows = conn.execute(
                f"""
                SELECT *
                FROM contact_conversations
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                [*params, max(limit * 5, limit)],
            ).fetchall()

        return [
            EvaMemoryItem(
                source="contact_conversations",
                id=int(row["id"]),
                title=f"联系人 {row['contact']} / {row['sender']}",
                content=str(row["content"]),
                timestamp=str(row["timestamp"]) if row["timestamp"] else None,
                score=_keyword_score(
                    query,
                    terms,
                    {str(row["sender"]): 4, str(row["content"]): 10},
                ),
            )
            for row in rows
        ]

    def _search_wechat_messages(
        self, query: str, terms: list[str], limit: int
    ) -> list[EvaMemoryItem]:
        with _connect(self.conversation_db_path) as conn:
            if not _table_exists(conn, "wechat_messages"):
                return []
            where, params = _keyword_where(["sender", "content"], terms)
            rows = conn.execute(
                f"""
                SELECT *
                FROM wechat_messages
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                [*params, max(limit * 5, limit)],
            ).fetchall()

        return [
            EvaMemoryItem(
                source="wechat_messages",
                id=int(row["id"]),
                title=f"微信 / {row['sender']}",
                content=str(row["content"]),
                timestamp=str(row["timestamp"]) if row["timestamp"] else None,
                score=_keyword_score(
                    query,
                    terms,
                    {str(row["sender"]): 4, str(row["content"]): 10},
                ),
            )
            for row in rows
        ]

    def _search_simple_vector_table(
        self,
        db_path: Path,
        table: str,
        vector_table: str,
        join_id_column: str,
        content_column: str,
        timestamp_column: str,
        query: str,
        limit: int,
        source: str,
    ) -> list[EvaMemoryItem] | None:
        query_blob = _generate_embedding_blob("", query)
        if query_blob is None:
            return None

        with _connect(db_path) as conn:
            if not _try_load_sqlite_vec(conn):
                return None
            if not _table_exists(conn, table) or not _table_exists(conn, vector_table):
                return []
            try:
                rows = conn.execute(
                    f"""
                    SELECT m.*, v.distance
                    FROM {vector_table} v
                    JOIN {table} m ON v.{join_id_column} = m.id
                    WHERE v.embedding MATCH ? AND k = ?
                    ORDER BY v.distance
                    """,
                    (query_blob, limit * 2),
                ).fetchall()
            except Exception:
                return None

        seen: set[int] = set()
        items: list[EvaMemoryItem] = []
        for row in rows:
            row_id = int(row["id"])
            if row_id in seen:
                continue
            seen.add(row_id)
            items.append(
                EvaMemoryItem(
                    source=source,
                    id=row_id,
                    content=str(row[content_column]),
                    timestamp=str(row[timestamp_column])
                    if row[timestamp_column]
                    else None,
                    distance=float(row["distance"]),
                    score=max(0, int(10000 - float(row["distance"]) * 10000)),
                )
            )
            if len(items) >= limit:
                break
        return items

    def _search_fragments_vector(
        self, query: str, limit: int
    ) -> list[EvaMemoryItem] | None:
        query_blob = _generate_embedding_blob("", query)
        if query_blob is None:
            return None

        with _connect(self.knowledge_db_path) as conn:
            if not _try_load_sqlite_vec(conn):
                return None
            if not _table_exists(conn, "fragments") or not _table_exists(
                conn, "fragments_vec"
            ):
                return []
            try:
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
                return None

        return [
            EvaMemoryItem(
                source="fragments",
                id=int(row["id"]),
                title=str(row["title"]),
                content=str(row["content"]),
                timestamp=str(row["updated_at"] or row["created_at"]),
                metadata={
                    "type": row["type"],
                    "tags": _json_loads(row["tags"], []),
                    "metadata": _json_loads(row["metadata"], {}),
                },
                distance=float(row["distance"]),
                score=max(0, int(10000 - float(row["distance"]) * 10000)),
            )
            for row in rows[:limit]
        ]

    def _search_conversations_vector(
        self, query: str, limit: int
    ) -> list[EvaMemoryItem] | None:
        query_blob = _generate_embedding_blob("", query)
        if query_blob is None:
            return None

        with _connect(self.conversation_db_path) as conn:
            if not _try_load_sqlite_vec(conn):
                return None
            if not _table_exists(conn, "conversations") or not _table_exists(
                conn, "conversations_vec"
            ):
                return []
            try:
                rows = conn.execute(
                    """
                    SELECT
                        c.*,
                        (
                            vec_distance_cosine(v.criss_embedding, ?) * 0.7 +
                            vec_distance_cosine(v.eva_embedding, ?) * 0.3
                        ) AS distance
                    FROM conversations c
                    JOIN conversations_vec v ON c.id = v.conversation_id
                    ORDER BY distance ASC
                    LIMIT ?
                    """,
                    (query_blob, query_blob, limit),
                ).fetchall()
            except Exception:
                return None

        return [
            EvaMemoryItem(
                source="conversations",
                id=int(row["id"]),
                content=f"Criss: {row['criss']}\nEva: {row['eva']}",
                timestamp=str(row["timestamp"]) if row["timestamp"] else None,
                distance=float(row["distance"]),
                score=max(0, int(10000 - float(row["distance"]) * 10000)),
            )
            for row in rows
        ]

    def _read_criss_profile(self) -> str | None:
        data_dir = (
            get_eva_tools_config_for_user(self.user_key).data_dir
            if self.user_key is not None
            else get_eva_tools_config().data_dir
        )
        if data_dir is None:
            return None

        path = data_dir / "criss.md"
        if not path.exists():
            return None
        return _truncate(path.read_text(encoding="utf-8").strip(), 3000)

    def _get_relationship_state(self) -> dict[str, Any] | None:
        with _connect(self.knowledge_db_path) as conn:
            if not _table_exists(conn, "eva_relationship_state"):
                return None
            row = conn.execute(
                "SELECT * FROM eva_relationship_state WHERE id = 1"
            ).fetchone()
        return dict(row) if row else None

    def _get_blackboards(self, limit: int) -> list[EvaMemoryItem]:
        with _connect(self.knowledge_db_path) as conn:
            if not _table_exists(conn, "blackboards"):
                return []
            rows = conn.execute(
                """
                SELECT *
                FROM blackboards
                WHERE content IS NOT NULL AND TRIM(content) <> ''
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            EvaMemoryItem(
                source="blackboards",
                id=int(row["id"]),
                title=f"黑板 {row['board_number']}",
                content=_truncate(str(row["content"]), 900),
                timestamp=str(row["updated_at"] or row["created_at"]),
                metadata={"settings": _json_loads(row["settings"], {})},
            )
            for row in rows
        ]

    def _get_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        knowledge_tables = [
            "memories",
            "eva_notes",
            "fragments",
            "reminders",
        ]
        with _connect(self.knowledge_db_path) as conn:
            for table in knowledge_tables:
                if _table_exists(conn, table):
                    counts[table] = int(
                        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    )

        conversation_tables = [
            "conversations",
            "contact_conversations",
            "wechat_messages",
        ]
        with _connect(self.conversation_db_path) as conn:
            for table in conversation_tables:
                if _table_exists(conn, table):
                    counts[table] = int(
                        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    )

        return counts
