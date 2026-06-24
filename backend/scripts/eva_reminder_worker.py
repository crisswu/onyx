from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any

from onyx.db.eva_config import get_eva_knowledge_db_path
from onyx.db.eva_config import get_eva_tools_config

BASE_DB_PATH = get_eva_knowledge_db_path() or Path(
    os.environ.get("EVA_KNOWLEDGE_DB_PATH", "/app/data/knowledge.db")
)
POLL_SECONDS = int(os.environ.get("EVA_REMINDER_POLL_SECONDS", "60"))
RETRY_LOOKBACK_MINUTES = int(os.environ.get("EVA_REMINDER_RETRY_LOOKBACK_MINUTES", "30"))
LOOKAHEAD_MINUTES = int(os.environ.get("EVA_REMINDER_LOOKAHEAD_MINUTES", "1"))
EXPIRY_GRACE_MINUTES = int(os.environ.get("EVA_REMINDER_EXPIRY_GRACE_MINUTES", "60"))
FEISHU_API_BASE = os.environ.get("FEISHU_API_BASE", "https://open.feishu.cn").rstrip("/")


def _knowledge_db_paths() -> list[Path]:
    paths: list[Path] = [BASE_DB_PATH]
    config = get_eva_tools_config()
    if config.user_data_root and config.user_data_root.exists():
        paths.extend(sorted(config.user_data_root.glob("*/knowledge.db")))

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(path)
    return deduped


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(db_path: Path) -> None:
    with _connect(db_path) as conn:
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


def _request_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            **(headers or {}),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Unexpected response from {url}: {body[:200]}")
    return parsed


def _feishu_enabled() -> bool:
    return os.environ.get("FEISHU_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _get_tenant_access_token() -> str:
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise RuntimeError("missing FEISHU_APP_ID or FEISHU_APP_SECRET")

    response = _request_json(
        f"{FEISHU_API_BASE}/open-apis/auth/v3/tenant_access_token/internal",
        {"app_id": app_id, "app_secret": app_secret},
    )
    if response.get("code") != 0:
        raise RuntimeError(response.get("msg") or str(response))
    token = response.get("tenant_access_token")
    if not token:
        raise RuntimeError("missing tenant_access_token in Feishu response")
    return str(token)


def _send_feishu_owner_message(message: str) -> None:
    if not _feishu_enabled():
        raise RuntimeError("FEISHU_ENABLED is not true")

    owner_open_id = os.environ.get("FEISHU_OWNER_OPEN_ID", "").strip()
    if not owner_open_id:
        raise RuntimeError("missing FEISHU_OWNER_OPEN_ID")

    token = _get_tenant_access_token()
    response = _request_json(
        f"{FEISHU_API_BASE}/open-apis/im/v1/messages?receive_id_type=open_id",
        {
            "receive_id": owner_open_id,
            "msg_type": "text",
            "content": json.dumps({"text": message}, ensure_ascii=False),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.get("code") != 0:
        raise RuntimeError(response.get("msg") or str(response))


def _pending_reminders(db_path: Path) -> list[dict[str, Any]]:
    now = datetime.now()
    time_start = (now - timedelta(minutes=RETRY_LOOKBACK_MINUTES)).isoformat()
    time_end = (now + timedelta(minutes=LOOKAHEAD_MINUTES)).isoformat()
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM reminders
            WHERE status = 'pending'
              AND send_time BETWEEN ? AND ?
            ORDER BY send_time ASC
            """,
            (time_start, time_end),
        ).fetchall()
    return [dict(row) for row in rows]


def _mark_sent(db_path: Path, reminder_id: int) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE reminders
            SET status = 'sent', sent_at = ?
            WHERE id = ?
            """,
            (datetime.now().isoformat(), reminder_id),
        )


def _mark_expired(db_path: Path) -> int:
    threshold = (datetime.now() - timedelta(minutes=EXPIRY_GRACE_MINUTES)).isoformat()
    with _connect(db_path) as conn:
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


def process_once() -> None:
    for db_path in _knowledge_db_paths():
        _ensure_schema(db_path)
        for reminder in _pending_reminders(db_path):
            reminder_id = int(reminder["id"])
            recipient = str(reminder["recipient"] or "Criss")
            message = str(reminder["message"])
            if recipient.lower() not in {"criss", "owner"}:
                print(
                    f"[WARN] Reminder #{reminder_id} unsupported recipient: {recipient}"
                )
                continue

            try:
                _send_feishu_owner_message(message)
            except Exception as exc:
                print(f"[WARN] Reminder #{reminder_id} send failed: {exc}")
                continue

            _mark_sent(db_path, reminder_id)
            print(f"[OK] Reminder #{reminder_id} sent from {db_path}")

        expired = _mark_expired(db_path)
        if expired:
            print(f"[INFO] Marked {expired} expired reminders in {db_path}")


def main() -> None:
    for db_path in _knowledge_db_paths():
        _ensure_schema(db_path)
    print("EVA reminder worker started")
    print("DBs:")
    for db_path in _knowledge_db_paths():
        print(f"- {db_path}")
    print(f"Poll seconds: {POLL_SECONDS}")
    while True:
        try:
            process_once()
        except (urllib.error.URLError, sqlite3.Error, Exception) as exc:
            print(f"[ERROR] Reminder processing failed: {exc}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
