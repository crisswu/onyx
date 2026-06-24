from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from fastapi import Request

from onyx.auth.users import get_anonymous_user
from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.process_message import gather_stream_full
from onyx.chat.process_message import handle_stream_message_objects
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.users import get_user_by_email
from onyx.server.query_and_chat.models import ChatSessionCreationRequest
from onyx.server.query_and_chat.models import MessageOrigin
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.utils.logger import setup_logger
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

router = APIRouter(prefix="/feishu")

FEISHU_REQUEST_TIMEOUT_SECONDS = 20
FEISHU_STATE_DB_PATH = Path(
    os.environ.get("FEISHU_STATE_DB_PATH", "/app/file-system/eva_feishu_state.db")
)
FEISHU_CARD_MAX_MARKDOWN_CHARS = 2600
FEISHU_CARD_MAX_BLOCKS = 24
FEISHU_CARD_MAX_MARKDOWN_CHARS_PER_CARD = 5200
FEISHU_CARD_MAX_TABLES_PER_CARD = 5
FEISHU_CARD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
FEISHU_CARD_TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$"
)
FEISHU_CARD_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<src>[^)]+)\)")


def _feishu_enabled() -> bool:
    return os.environ.get("FEISHU_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _get_env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _ensure_state_db() -> None:
    FEISHU_STATE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(FEISHU_STATE_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feishu_sessions (
                open_id TEXT PRIMARY KEY,
                chat_session_id TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feishu_messages (
                message_id TEXT PRIMARY KEY,
                event_id TEXT,
                sender_open_id TEXT,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def _get_chat_session_id(open_id: str) -> UUID | None:
    _ensure_state_db()
    with sqlite3.connect(FEISHU_STATE_DB_PATH) as conn:
        row = conn.execute(
            "SELECT chat_session_id FROM feishu_sessions WHERE open_id = ?",
            (open_id,),
        ).fetchone()
    if not row:
        return None
    try:
        return UUID(str(row[0]))
    except ValueError:
        return None


def _set_chat_session_id(open_id: str, chat_session_id: UUID) -> None:
    _ensure_state_db()
    with sqlite3.connect(FEISHU_STATE_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO feishu_sessions (open_id, chat_session_id, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(open_id) DO UPDATE SET
                chat_session_id = excluded.chat_session_id,
                updated_at = excluded.updated_at
            """,
            (open_id, str(chat_session_id)),
        )


def _get_message_status(message_id: str) -> str:
    _ensure_state_db()
    with sqlite3.connect(FEISHU_STATE_DB_PATH) as conn:
        row = conn.execute(
            "SELECT status FROM feishu_messages WHERE message_id = ?",
            (message_id,),
        ).fetchone()
    return str(row[0]) if row else ""


def _set_message_status(
    *,
    message_id: str,
    event_id: str,
    sender_open_id: str,
    status: str,
) -> None:
    _ensure_state_db()
    with sqlite3.connect(FEISHU_STATE_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO feishu_messages (
                message_id, event_id, sender_open_id, status, updated_at
            )
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(message_id) DO UPDATE SET
                event_id = excluded.event_id,
                sender_open_id = excluded.sender_open_id,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (message_id, event_id, sender_open_id, status),
        )


def _request_json(
    url: str,
    *,
    method: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request_headers = dict(headers or {})
    data = None
    if payload is not None:
        request_headers = {"Content-Type": "application/json", **request_headers}
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(
            request, timeout=FEISHU_REQUEST_TIMEOUT_SECONDS
        ) as response:
            body = response.read().decode("utf-8")
            if not body:
                return {"code": 0}
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body)
        except ValueError:
            return {"code": e.code, "msg": body[:500]}


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    return _request_json(url, method="POST", payload=payload, headers=headers)


def _feishu_render_mode() -> str:
    mode = (_get_env("FEISHU_RENDER_MODE") or "text").lower()
    return mode if mode in {"text", "card"} else "text"


def _build_text_reply_payload(text: str) -> dict[str, Any]:
    return {
        "msg_type": "text",
        "content": json.dumps({"text": text[:12000]}, ensure_ascii=False),
        "reply_in_thread": _env_flag("FEISHU_REPLY_IN_THREAD", default=False),
    }


def _normalize_card_markdown(text: str) -> str:
    lines: list[str] = []
    for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        heading = FEISHU_CARD_HEADING_RE.match(line)
        if heading:
            lines.append(f"**{heading.group(1).strip()}**")
            continue
        lines.append(line)
    normalized = "\n".join(lines).strip()

    def image_replacement(match: re.Match[str]) -> str:
        alt = (match.group("alt") or "图片").strip()
        src = (match.group("src") or "").strip()
        return f"[{alt}]({src})" if src else alt

    return FEISHU_CARD_IMAGE_RE.sub(image_replacement, normalized)


def _split_markdown_blocks(text: str) -> list[tuple[str, bool]]:
    blocks: list[tuple[str, bool]] = []
    current_lines: list[str] = []
    in_code_block = False

    for line in str(text or "").split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            current_lines.append(line)
            in_code_block = not in_code_block
            if not in_code_block:
                blocks.append(("\n".join(current_lines).strip(), True))
                current_lines.clear()
            continue

        if in_code_block:
            current_lines.append(line)
            continue

        if not stripped:
            if current_lines:
                blocks.append(("\n".join(current_lines).strip(), False))
                current_lines.clear()
            continue

        current_lines.append(line)

    if current_lines:
        blocks.append(("\n".join(current_lines).strip(), in_code_block))
    return [(block, is_code) for block, is_code in blocks if block]


def _split_long_text(text: str, max_chars: int) -> list[str]:
    clean = str(text or "").strip()
    if not clean:
        return []
    if len(clean) <= max_chars:
        return [clean]
    return [clean[index : index + max_chars] for index in range(0, len(clean), max_chars)]


def _chunk_card_markdown(text: str) -> list[str]:
    clean = str(text or "").strip()
    if not clean:
        return []
    if len(clean) <= FEISHU_CARD_MAX_MARKDOWN_CHARS:
        return [clean]

    chunks: list[str] = []
    current = ""
    for block, is_code_block in _split_markdown_blocks(clean):
        parts = [block]
        if len(block) > FEISHU_CARD_MAX_MARKDOWN_CHARS:
            if is_code_block:
                parts = _split_long_text(block, FEISHU_CARD_MAX_MARKDOWN_CHARS)
            else:
                parts = _split_long_text(block, FEISHU_CARD_MAX_MARKDOWN_CHARS)

        for part in parts:
            candidate = part if not current else f"{current}\n\n{part}"
            if len(candidate) <= FEISHU_CARD_MAX_MARKDOWN_CHARS:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = part

    if current:
        chunks.append(current)
    return chunks


def _parse_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _build_table_column_name(index: int) -> str:
    return f"col_{index + 1}"


def _consume_markdown_table(lines: list[str], start: int) -> tuple[dict[str, Any] | None, int]:
    if start + 1 >= len(lines):
        return None, start

    header_line = lines[start].strip()
    separator_line = lines[start + 1].strip()
    if "|" not in header_line or not FEISHU_CARD_TABLE_SEPARATOR_RE.match(separator_line):
        return None, start

    raw_rows = [lines[start]]
    index = start + 2
    while index < len(lines):
        candidate = lines[index]
        if "|" not in candidate.strip():
            break
        raw_rows.append(candidate)
        index += 1

    header_cells = _parse_table_row(raw_rows[0])
    data_rows = [_parse_table_row(row) for row in raw_rows[1:]]
    if not header_cells:
        return None, start

    column_count = max([len(header_cells)] + [len(row) for row in data_rows] or [len(header_cells)])
    if column_count <= 1:
        return None, start

    header_cells = header_cells + [""] * (column_count - len(header_cells))
    normalized_rows = [row + [""] * (column_count - len(row)) for row in data_rows]

    columns = [
        {
            "name": _build_table_column_name(col_index),
            "display_name": header_cells[col_index].strip() or f"列{col_index + 1}",
            "data_type": "lark_md",
            "width": "auto",
            "horizontal_align": "left",
            "vertical_align": "top",
        }
        for col_index in range(column_count)
    ]
    rows = [
        {
            _build_table_column_name(col_index): row[col_index].strip()
            for col_index in range(column_count)
        }
        for row in normalized_rows
    ]

    return (
        {
            "tag": "table",
            "page_size": min(max(len(rows), 1), 5),
            "row_height": "low",
            "freeze_first_column": False,
            "header_style": {
                "text_align": "left",
                "text_size": "normal",
                "background_style": "none",
                "text_color": "default",
                "bold": True,
                "lines": 1,
            },
            "columns": columns,
            "rows": rows,
        },
        index,
    )


def _build_card_blocks(text: str) -> list[dict[str, Any]]:
    clean = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not clean:
        return [{"tag": "markdown", "content": "我暂时还没有整理出有效回复。"}]

    blocks: list[dict[str, Any]] = []
    markdown_lines: list[str] = []
    lines = clean.split("\n")
    index = 0

    def flush_markdown() -> None:
        if not markdown_lines:
            return
        markdown = _normalize_card_markdown("\n".join(markdown_lines))
        markdown_lines.clear()
        for chunk in _chunk_card_markdown(markdown):
            blocks.append({"tag": "markdown", "content": chunk})

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            markdown_lines.append(line)
            index += 1
            while index < len(lines):
                markdown_lines.append(lines[index])
                if lines[index].strip().startswith("```"):
                    index += 1
                    break
                index += 1
            continue

        table, next_index = _consume_markdown_table(lines, index)
        if table is not None:
            flush_markdown()
            blocks.append(table)
            index = next_index
            continue

        markdown_lines.append(line)
        index += 1

    flush_markdown()
    return blocks or [{"tag": "markdown", "content": "我暂时还没有整理出有效回复。"}]


def _split_card_blocks(blocks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    markdown_chars = 0
    table_count = 0

    for block in blocks:
        block_markdown_chars = len(str(block.get("content", ""))) if block.get("tag") == "markdown" else 0
        block_table_count = 1 if block.get("tag") == "table" else 0
        overflow = (
            current
            and (
                len(current) >= FEISHU_CARD_MAX_BLOCKS
                or table_count + block_table_count > FEISHU_CARD_MAX_TABLES_PER_CARD
                or markdown_chars + block_markdown_chars > FEISHU_CARD_MAX_MARKDOWN_CHARS_PER_CARD
            )
        )
        if overflow:
            groups.append(current)
            current = []
            markdown_chars = 0
            table_count = 0

        current.append(block)
        markdown_chars += block_markdown_chars
        table_count += block_table_count

    if current:
        groups.append(current)
    return groups or [[{"tag": "markdown", "content": "我暂时还没有整理出有效回复。"}]]


def _build_reply_cards(text: str, *, success: bool = True) -> list[dict[str, Any]]:
    title_base = _get_env("FEISHU_CARD_TITLE") or "EVA 回复"
    template = _get_env("FEISHU_CARD_TEMPLATE_SUCCESS") or "green"
    if not success:
        template = _get_env("FEISHU_CARD_TEMPLATE_ERROR") or "red"

    block_groups = _split_card_blocks(_build_card_blocks(text))
    total = len(block_groups)
    cards: list[dict[str, Any]] = []
    for index, group in enumerate(block_groups, 1):
        elements: list[dict[str, Any]] = []
        for block in group:
            if elements:
                elements.append({"tag": "hr"})
            elements.append(block)

        title = title_base if total == 1 else f"{title_base} ({index}/{total})"
        cards.append(
            {
                "config": {
                    "wide_screen_mode": True,
                    "enable_forward": True,
                },
                "header": {
                    "title": {"tag": "plain_text", "content": title[:80]},
                    "template": template,
                },
                "elements": elements,
            }
        )
    return cards


def _build_status_card(
    status_text: str,
    *,
    success: bool | None = None,
) -> dict[str, Any]:
    clean = str(status_text or "").strip() or "正在处理..."
    if success is None:
        title = _get_env("FEISHU_STATUS_CARD_TITLE_PROCESSING") or "EVA 正在处理"
        template = _get_env("FEISHU_CARD_TEMPLATE_PROCESSING") or "blue"
        status = "进行中"
    elif success:
        title = _get_env("FEISHU_STATUS_CARD_TITLE_SUCCESS") or "EVA 已完成"
        template = _get_env("FEISHU_CARD_TEMPLATE_SUCCESS") or "green"
        status = "已完成"
    else:
        title = _get_env("FEISHU_STATUS_CARD_TITLE_ERROR") or "EVA 处理失败"
        template = _get_env("FEISHU_CARD_TEMPLATE_ERROR") or "red"
        status = "处理失败"

    elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": _normalize_card_markdown(clean)}
    ]
    if _env_flag("FEISHU_FOOTER_STATUS", default=True):
        elements.append({"tag": "hr"})
        elements.append(
            {
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": f"状态：{status}"}],
            }
        )

    return {
        "config": {
            "wide_screen_mode": True,
            "enable_forward": True,
        },
        "header": {
            "title": {"tag": "plain_text", "content": title[:80]},
            "template": template,
        },
        "elements": elements,
    }


def _build_card_reply_payloads(text: str, *, success: bool = True) -> list[dict[str, Any]]:
    return [
        {
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
            "reply_in_thread": _env_flag("FEISHU_REPLY_IN_THREAD", default=False),
        }
        for card in _build_reply_cards(text, success=success)
    ]


def _build_card_update_payloads(text: str, *, success: bool = True) -> list[dict[str, Any]]:
    return [
        {
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        }
        for card in _build_reply_cards(text, success=success)
    ]


def _build_text_update_payload(text: str) -> dict[str, Any]:
    return {
        "msg_type": "text",
        "content": json.dumps({"text": text[:12000]}, ensure_ascii=False),
    }


def _get_tenant_access_token() -> str:
    app_id = _get_env("FEISHU_APP_ID")
    app_secret = _get_env("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        raise RuntimeError("missing FEISHU_APP_ID or FEISHU_APP_SECRET")

    api_base = _get_env("FEISHU_API_BASE") or "https://open.feishu.cn"
    response = _post_json(
        f"{api_base.rstrip('/')}/open-apis/auth/v3/tenant_access_token/internal",
        {"app_id": app_id, "app_secret": app_secret},
    )
    if response.get("code") != 0:
        raise RuntimeError(response.get("msg") or str(response))
    token = response.get("tenant_access_token")
    if not token:
        raise RuntimeError("missing tenant_access_token in Feishu response")
    return str(token)


def _extract_message_id(response: dict[str, Any]) -> str | None:
    data = response.get("data")
    if not isinstance(data, dict):
        return None
    value = data.get("message_id")
    return str(value) if value else None


def _send_reply_payload(message_id: str, payload: dict[str, Any]) -> str | None:
    api_base = _get_env("FEISHU_API_BASE") or "https://open.feishu.cn"
    token = _get_tenant_access_token()
    response = _post_json(
        f"{api_base.rstrip('/')}/open-apis/im/v1/messages/{message_id}/reply",
        payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.get("code") != 0:
        raise RuntimeError(response.get("msg") or str(response))
    return _extract_message_id(response)


def _update_message_payload(message_id: str, payload: dict[str, Any]) -> None:
    api_base = _get_env("FEISHU_API_BASE") or "https://open.feishu.cn"
    token = _get_tenant_access_token()
    response = _request_json(
        f"{api_base.rstrip('/')}/open-apis/im/v1/messages/{message_id}",
        method="PATCH",
        payload=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.get("code") != 0:
        raise RuntimeError(response.get("msg") or str(response))


def _reply_processing_status(message_id: str) -> str | None:
    if not _env_flag("FEISHU_STATUS_MESSAGE_ENABLED", default=True):
        return None
    if _feishu_render_mode() != "card":
        return None

    status_text = (
        _get_env("FEISHU_PROCESSING_STATUS_TEXT")
        or "我已经收到消息，正在整理回复..."
    )
    payload = {
        "msg_type": "interactive",
        "content": json.dumps(
            _build_status_card(status_text, success=None),
            ensure_ascii=False,
        ),
        "reply_in_thread": _env_flag("FEISHU_REPLY_IN_THREAD", default=False),
    }
    try:
        return _send_reply_payload(message_id, payload)
    except Exception:
        logger.exception("Feishu processing status reply failed")
        return None


def _update_reply_message(
    update_message_id: str,
    source_message_id: str,
    text: str,
    *,
    success: bool = True,
) -> None:
    clean = str(text or "").strip() or "我刚刚没组织好回答，你再发我一次。"
    if _feishu_render_mode() != "card":
        _update_message_payload(update_message_id, _build_text_update_payload(clean))
        return

    payloads = _build_card_update_payloads(clean, success=success)
    if not payloads:
        return
    _update_message_payload(update_message_id, payloads[0])

    for payload in payloads[1:]:
        _send_reply_payload(
            source_message_id,
            {
                **payload,
                "reply_in_thread": _env_flag("FEISHU_REPLY_IN_THREAD", default=False),
            },
        )


def _reply_to_message(message_id: str, text: str, *, success: bool = True) -> None:
    clean = str(text or "").strip() or "我刚刚没组织好回答，你再发我一次。"
    if _feishu_render_mode() != "card":
        _send_reply_payload(message_id, _build_text_reply_payload(clean))
        return

    try:
        for payload in _build_card_reply_payloads(clean, success=success):
            _send_reply_payload(message_id, payload)
    except Exception:
        logger.exception("Feishu card reply failed; falling back to text reply")
        _send_reply_payload(message_id, _build_text_reply_payload(clean))


def _extract_reaction_id(response: dict[str, Any]) -> str | None:
    data = response.get("data")
    if not isinstance(data, dict):
        return None

    for key in ("reaction_id", "id"):
        value = data.get(key)
        if value:
            return str(value)

    reaction = data.get("reaction")
    if isinstance(reaction, dict):
        for key in ("reaction_id", "id"):
            value = reaction.get(key)
            if value:
                return str(value)

    return None


def _add_typing_reaction(message_id: str) -> str | None:
    if not _env_flag("FEISHU_TYPING_REACTION_ENABLED", default=True):
        return None

    emoji_type = _get_env("FEISHU_TYPING_EMOJI_TYPE") or "Typing"
    api_base = _get_env("FEISHU_API_BASE") or "https://open.feishu.cn"

    try:
        token = _get_tenant_access_token()
        response = _post_json(
            f"{api_base.rstrip('/')}/open-apis/im/v1/messages/{message_id}/reactions",
            {"reaction_type": {"emoji_type": emoji_type}},
            headers={"Authorization": f"Bearer {token}"},
        )
    except Exception:
        logger.exception("Failed to add Feishu typing reaction")
        return None

    if response.get("code") != 0:
        logger.warning("Feishu typing reaction rejected: %s", response)
        return None

    reaction_id = _extract_reaction_id(response)
    if reaction_id is None:
        logger.warning(
            "Feishu typing reaction added but no reaction id was returned: %s",
            response,
        )
    return reaction_id


def _delete_typing_reaction(message_id: str, reaction_id: str | None) -> None:
    if not reaction_id:
        return

    api_base = _get_env("FEISHU_API_BASE") or "https://open.feishu.cn"
    try:
        token = _get_tenant_access_token()
        response = _request_json(
            f"{api_base.rstrip('/')}/open-apis/im/v1/messages/{message_id}/reactions/{reaction_id}",
            method="DELETE",
            headers={"Authorization": f"Bearer {token}"},
        )
    except Exception:
        logger.exception("Failed to delete Feishu typing reaction")
        return

    if response.get("code") != 0:
        logger.warning("Feishu typing reaction delete rejected: %s", response)


def _extract_text_content(raw_content: Any) -> str:
    try:
        parsed = json.loads(str(raw_content or ""))
    except ValueError:
        return ""
    return str(parsed.get("text", "")).strip()


def _run_onyx_chat(sender_open_id: str, text: str) -> str:
    CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)

    user_email = _get_env("FEISHU_ONYX_USER_EMAIL") or "a@example.com"
    with get_session_with_current_tenant() as db_session:
        user = get_user_by_email(user_email, db_session) or get_anonymous_user()

    chat_session_id = _get_chat_session_id(sender_open_id)
    if chat_session_id is None:
        chat_session_info = ChatSessionCreationRequest(
            persona_id=int(_get_env("FEISHU_PERSONA_ID") or "0"),
            description="飞书对话",
        )
    else:
        chat_session_info = None

    request = SendMessageRequest(
        message=text,
        chat_session_id=chat_session_id,
        chat_session_info=chat_session_info,
        stream=False,
        include_citations=False,
        origin=MessageOrigin.API,
    )

    state_container = ChatStateContainer()
    packets = handle_stream_message_objects(
        new_msg_req=request,
        user=user,
        litellm_additional_headers={},
        custom_tool_additional_headers={},
        mcp_headers=None,
        additional_context="这条消息来自飞书私聊，请用适合飞书聊天的简洁中文回复。",
        external_state_container=state_container,
    )
    result = gather_stream_full(packets, state_container)
    if result.chat_session_id is not None:
        _set_chat_session_id(sender_open_id, result.chat_session_id)
    if result.error_msg:
        raise RuntimeError(result.error_msg)
    return result.answer_citationless or result.answer


def _process_message(
    *,
    message_id: str,
    event_id: str,
    sender_open_id: str,
    text: str,
) -> None:
    typing_reaction_id: str | None = None
    status_message_id: str | None = None
    try:
        _set_message_status(
            message_id=message_id,
            event_id=event_id,
            sender_open_id=sender_open_id,
            status="processing",
        )
        status_message_id = _reply_processing_status(message_id)
        typing_reaction_id = _add_typing_reaction(message_id)
        answer = _run_onyx_chat(sender_open_id, text)
        _delete_typing_reaction(message_id, typing_reaction_id)
        typing_reaction_id = None
        if status_message_id:
            try:
                _update_reply_message(
                    status_message_id,
                    message_id,
                    answer,
                    success=True,
                )
            except Exception:
                logger.exception("Feishu final status update failed")
                _reply_to_message(message_id, answer)
        else:
            _reply_to_message(message_id, answer)
        _set_message_status(
            message_id=message_id,
            event_id=event_id,
            sender_open_id=sender_open_id,
            status="done",
        )
    except Exception as exc:
        logger.exception("Feishu message processing failed")
        try:
            failure_text = "我刚刚处理失败了，你可以再发我一次。"
            if status_message_id:
                try:
                    _update_reply_message(
                        status_message_id,
                        message_id,
                        failure_text,
                        success=False,
                    )
                except Exception:
                    logger.exception("Feishu failure status update failed")
                    _reply_to_message(message_id, failure_text, success=False)
            else:
                _reply_to_message(message_id, failure_text, success=False)
        except Exception:
            logger.exception("Feishu failure reply failed")
        _set_message_status(
            message_id=message_id,
            event_id=event_id,
            sender_open_id=sender_open_id,
            status=f"failed:{str(exc)[:200]}",
        )
    finally:
        _delete_typing_reaction(message_id, typing_reaction_id)


@router.post("/events")
async def handle_feishu_event(request: Request) -> dict[str, Any]:
    payload = await request.json()
    return enqueue_feishu_payload(payload)


def enqueue_feishu_payload(payload: dict[str, Any]) -> dict[str, Any]:

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    if not _feishu_enabled():
        return {"status": "disabled"}

    header = payload.get("header") or {}
    event_type = str(header.get("event_type") or payload.get("type") or "")
    if event_type != "im.message.receive_v1":
        return {"status": "ignored", "event_type": event_type}

    event = payload.get("event") or {}
    message = event.get("message") or {}
    sender = event.get("sender") or {}
    sender_id = sender.get("sender_id") or {}

    message_id = str(message.get("message_id", "")).strip()
    event_id = str(header.get("event_id", "")).strip()
    sender_open_id = str(sender_id.get("open_id", "")).strip()
    chat_type = str(message.get("chat_type", "")).strip().lower()
    message_type = str(message.get("message_type", "")).strip().lower()
    text = _extract_text_content(message.get("content"))

    if not message_id or not sender_open_id:
        return {"status": "ignored", "reason": "missing_message_or_sender"}

    owner_open_id = _get_env("FEISHU_OWNER_OPEN_ID")
    if owner_open_id and sender_open_id != owner_open_id:
        logger.info("Ignoring Feishu message from non-owner sender.")
        return {"status": "ignored", "reason": "owner_mismatch"}

    if chat_type != "p2p":
        return {"status": "ignored", "reason": "non_p2p"}

    if message_type != "text" or not text:
        _reply_to_message(message_id, "当前只支持文本单聊消息。")
        return {"status": "ignored", "reason": "unsupported_message_type"}

    existing_status = _get_message_status(message_id)
    if existing_status in {"queued", "processing", "done"}:
        return {"status": "duplicate", "message_status": existing_status}

    _set_message_status(
        message_id=message_id,
        event_id=event_id,
        sender_open_id=sender_open_id,
        status="queued",
    )
    thread = threading.Thread(
        target=_process_message,
        kwargs={
            "message_id": message_id,
            "event_id": event_id,
            "sender_open_id": sender_open_id,
            "text": text,
        },
        name=f"feishu-message-{message_id[:8]}",
        daemon=True,
    )
    thread.start()
    return {"status": "queued"}
