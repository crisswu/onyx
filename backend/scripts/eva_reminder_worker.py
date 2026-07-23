from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.eva_config import get_eva_knowledge_db_path
from onyx.db.eva_config import get_eva_tools_config
from onyx.db.eva_personal import eva_reminder_db_paths
from onyx.db.eva_personal import EvaReminderDB
from onyx.db.feishu import get_feishu_binding_by_user_id
from onyx.db.users import get_user_by_email
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

POLL_SECONDS = int(os.environ.get("EVA_REMINDER_POLL_SECONDS", "60"))
RETRY_LOOKBACK_MINUTES = int(
    os.environ.get("EVA_REMINDER_RETRY_LOOKBACK_MINUTES", "30")
)
LOOKAHEAD_MINUTES = int(os.environ.get("EVA_REMINDER_LOOKAHEAD_MINUTES", "1"))
EXPIRY_GRACE_MINUTES = int(os.environ.get("EVA_REMINDER_EXPIRY_GRACE_MINUTES", "60"))
FEISHU_API_BASE = os.environ.get("FEISHU_API_BASE", "https://open.feishu.cn").rstrip(
    "/"
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


def _send_feishu_message(open_id: str, message: str) -> None:
    if not _feishu_enabled():
        raise RuntimeError("FEISHU_ENABLED is not true")

    token = _get_tenant_access_token()
    response = _request_json(
        f"{FEISHU_API_BASE}/open-apis/im/v1/messages?receive_id_type=open_id",
        {
            "receive_id": open_id,
            "msg_type": "text",
            "content": json.dumps({"text": message}, ensure_ascii=False),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.get("code") != 0:
        raise RuntimeError(response.get("msg") or str(response))


def _user_email_for_reminder_db_path(db_path: Path) -> str:
    config = get_eva_tools_config()
    base_path = (get_eva_knowledge_db_path() or db_path).resolve()
    if db_path.resolve() == base_path:
        return config.owner_email
    return db_path.parent.name.strip().lower()


def _open_id_for_reminder_db_path(db_path: Path) -> str | None:
    user_email = _user_email_for_reminder_db_path(db_path)
    with get_session_with_current_tenant() as db_session:
        user = get_user_by_email(user_email, db_session)
        if user is not None:
            binding = get_feishu_binding_by_user_id(db_session, user.id)
            if binding and binding.open_id:
                return binding.open_id

    owner_open_id = os.environ.get("FEISHU_OWNER_OPEN_ID", "").strip()
    if user_email == get_eva_tools_config().owner_email and owner_open_id:
        return owner_open_id
    return None


def _send_reminder_message(db_path: Path, message: str) -> None:
    open_id = _open_id_for_reminder_db_path(db_path)
    if not open_id:
        raise RuntimeError(f"No Feishu binding found for reminders in {db_path}")
    _send_feishu_message(open_id, message)


def process_once() -> None:
    for db_path in eva_reminder_db_paths():
        reminder_db = EvaReminderDB(db_path=db_path)
        for reminder in reminder_db.list_due_pending(
            retry_lookback_minutes=RETRY_LOOKBACK_MINUTES,
            lookahead_minutes=LOOKAHEAD_MINUTES,
        ):
            reminder_id = int(reminder["id"])
            recipient = str(reminder["recipient"] or "Criss")
            message = str(reminder["message"])
            if recipient.lower() not in {"criss", "owner"}:
                print(
                    f"[WARN] Reminder #{reminder_id} unsupported recipient: {recipient}"
                )
                continue

            try:
                _send_reminder_message(db_path, message)
            except Exception as exc:
                print(f"[WARN] Reminder #{reminder_id} send failed: {exc}")
                continue

            reminder_db.mark_sent(reminder_id)
            print(f"[OK] Reminder #{reminder_id} sent from {db_path}")

        expired = reminder_db.mark_expired_reminders(
            grace_minutes=EXPIRY_GRACE_MINUTES
        )
        if expired:
            print(f"[INFO] Marked {expired} expired reminders in {db_path}")


def main() -> None:
    CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)
    SqlEngine.init_engine(pool_size=2, max_overflow=1)

    for db_path in eva_reminder_db_paths():
        EvaReminderDB(db_path=db_path)
    print("EVA reminder worker started")
    print("DBs:")
    for db_path in eva_reminder_db_paths():
        print(f"- {db_path}")
    print(f"Poll seconds: {POLL_SECONDS}")
    while True:
        try:
            process_once()
        except Exception as exc:
            print(f"[ERROR] Reminder processing failed: {exc}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
