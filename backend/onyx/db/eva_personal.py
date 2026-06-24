from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any

from onyx.db.eva_config import get_eva_conversation_db_path
from onyx.db.eva_config import get_eva_conversation_db_path_for_user
from onyx.db.eva_config import get_eva_knowledge_db_path
from onyx.db.eva_config import get_eva_knowledge_db_path_for_user
from onyx.db.eva_knowledge import _generate_embedding_blob
from onyx.db.eva_knowledge import _try_load_sqlite_vec


@dataclass
class EvaConversation:
    id: int
    criss: str
    eva: str
    timestamp: str
    distance: float | None = None


def _data_path(filename: str, env_var: str) -> Path:
    env_path = os.environ.get(env_var)
    if env_path:
        return Path(env_path)

    candidates = [
        Path("/app/data") / filename,
        Path.cwd() / "data" / filename,
        Path(__file__).resolve().parents[3] / "data" / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def eva_conversation_db_path() -> Path:
    configured_path = get_eva_conversation_db_path()
    if configured_path is not None:
        return configured_path
    return _data_path("conversation.db", "EVA_CONVERSATION_DB_PATH")


def eva_conversation_db_path_for_user(user_key: str | None) -> Path:
    configured_path = get_eva_conversation_db_path_for_user(user_key)
    if configured_path is not None:
        return configured_path
    return eva_conversation_db_path()


def eva_knowledge_db_path() -> Path:
    configured_path = get_eva_knowledge_db_path()
    if configured_path is not None:
        return configured_path
    return _data_path("knowledge.db", "EVA_KNOWLEDGE_DB_PATH")


def eva_knowledge_db_path_for_user(user_key: str | None) -> Path:
    configured_path = get_eva_knowledge_db_path_for_user(user_key)
    if configured_path is not None:
        return configured_path
    return eva_knowledge_db_path()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _keyword_terms(query: str) -> list[str]:
    normalized = query.strip()
    if not normalized:
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
        cleaned = term.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def _conversation_from_row(row: sqlite3.Row) -> EvaConversation:
    keys = set(row.keys())
    return EvaConversation(
        id=int(row["id"]),
        criss=str(row["criss"]),
        eva=str(row["eva"]),
        timestamp=str(row["timestamp"]),
        distance=float(row["distance"]) if "distance" in keys else None,
    )


class EvaConversationDB:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or eva_conversation_db_path()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with _connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    criss TEXT NOT NULL,
                    eva TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS contact_conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contact INTEGER NOT NULL,
                    sender TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            if _try_load_sqlite_vec(conn):
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS conversations_vec USING vec0(
                        conversation_id INTEGER,
                        criss_embedding FLOAT[1024],
                        eva_embedding FLOAT[1024]
                    )
                    """
                )

    def add_conversation(self, criss: str, eva: str) -> int:
        timestamp = datetime.now().isoformat()
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO conversations (criss, eva, timestamp)
                VALUES (?, ?, ?)
                """,
                (criss, eva, timestamp),
            )
            conversation_id = int(cursor.lastrowid)

            criss_blob = _generate_embedding_blob("", criss)
            eva_blob = _generate_embedding_blob("", eva)
            if criss_blob is not None and eva_blob is not None and _try_load_sqlite_vec(conn):
                try:
                    conn.execute(
                        """
                        INSERT INTO conversations_vec
                            (conversation_id, criss_embedding, eva_embedding)
                        VALUES (?, ?, ?)
                        """,
                        (conversation_id, criss_blob, eva_blob),
                    )
                except Exception:
                    pass
            return conversation_id

    def weighted_search(self, query: str, limit: int = 5) -> list[EvaConversation]:
        vector_results = self._weighted_vector_search(query, limit)
        if vector_results is not None:
            return vector_results
        return self._weighted_keyword_search(query, limit)

    def _weighted_vector_search(
        self, query: str, limit: int
    ) -> list[EvaConversation] | None:
        query_blob = _generate_embedding_blob("", query)
        if query_blob is None:
            return None

        with _connect(self.db_path) as conn:
            if not _try_load_sqlite_vec(conn):
                return None
            try:
                rows = conn.execute(
                    """
                    SELECT
                        c.id,
                        c.criss,
                        c.eva,
                        c.timestamp,
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

        return [_conversation_from_row(row) for row in rows]

    def _weighted_keyword_search(self, query: str, limit: int) -> list[EvaConversation]:
        terms = _keyword_terms(query)
        params: list[Any] = []
        where = ""
        if terms:
            clauses = []
            for term in terms:
                clauses.append("(criss LIKE ? OR eva LIKE ?)")
                like = f"%{term}%"
                params.extend([like, like])
            where = "WHERE " + " OR ".join(clauses)

        with _connect(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT id, criss, eva, timestamp
                FROM conversations
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                [*params, max(limit * 5, limit)],
            ).fetchall()

        conversations = [_conversation_from_row(row) for row in rows]
        conversations.sort(
            key=lambda conversation: self._keyword_score(conversation, query, terms),
            reverse=True,
        )
        return conversations[:limit]

    def _keyword_score(
        self, conversation: EvaConversation, query: str, terms: list[str]
    ) -> int:
        normalized_query = query.strip().lower()
        criss = conversation.criss.lower()
        eva = conversation.eva.lower()

        score = 0
        if normalized_query:
            if normalized_query in criss:
                score += 70
            if normalized_query in eva:
                score += 30

        for term in terms:
            lowered = term.lower()
            if lowered in criss:
                score += 7
            if lowered in eva:
                score += 3
        return score


class EvaReminderDB:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or eva_knowledge_db_path()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with _connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    send_time DATETIME NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    sent_at DATETIME
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reminders_status_time
                ON reminders(status, send_time)
                """
            )

    def add_reminder(self, message: str, recipient: str, send_time: datetime) -> int:
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO reminders
                    (message, recipient, send_time, status, created_at)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (message, recipient, send_time.isoformat(), datetime.now().isoformat()),
            )
            return int(cursor.lastrowid)

    def list_pending(self, limit: int = 20) -> list[dict[str, Any]]:
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM reminders
                WHERE status = 'pending'
                ORDER BY send_time ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_expired_reminders(self, grace_minutes: int = 60) -> int:
        threshold = (datetime.now() - timedelta(minutes=grace_minutes)).isoformat()
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE reminders
                SET status = 'expired'
                WHERE status = 'pending'
                  AND send_time < ?
                """,
                (threshold,),
            )
            return int(cursor.rowcount)


def coerce_email_metadata(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, Mapping):
                return dict(parsed)
        except json.JSONDecodeError:
            return {}
    return {}
