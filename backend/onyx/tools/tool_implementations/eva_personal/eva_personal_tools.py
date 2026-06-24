from __future__ import annotations

import email
import imaplib
import json
import os
import re
from abc import ABC
from email.header import decode_header
from html.parser import HTMLParser
from typing import Any
from typing import ClassVar

from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.eva_memory import EvaMemoryDB
from onyx.db.eva_memory import EvaMemoryItem
from onyx.db.eva_memory import EvaMemorySearchResult
from onyx.db.eva_memory import VALID_EVA_MEMORY_SCOPES
from onyx.db.eva_memory import normalize_eva_memory_scope
from onyx.db.eva_personal import eva_knowledge_db_path_for_user
from onyx.db.eva_personal import EvaReminderDB
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CustomToolArgs
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse

MAX_LLM_FACING_RESPONSE_CHARS = 8000


def _preprocess_args(kwargs: dict[str, Any], expected_key: str) -> dict[str, Any]:
    if len(kwargs) == 1:
        value = next(iter(kwargs.values()))
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

    value = kwargs.get(expected_key)
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict) and expected_key in parsed:
                return parsed
        except json.JSONDecodeError:
            pass

    return kwargs


def _coerce_limit(value: Any, default: int, minimum: int = 1, maximum: int = 50) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    return max(minimum, min(maximum, limit))


def _truncate_for_llm(text: str, limit: int = MAX_LLM_FACING_RESPONSE_CHARS) -> str:
    if len(text) <= limit:
        return text
    return (
        text[:limit].rstrip()
        + f"\n\n...（工具结果过长，已截断给模型读取，原始长度 {len(text)} 字符）"
    )


class EvaPersonalTool(Tool[None], ABC):
    NAME: ClassVar[str]
    DISPLAY_NAME: ClassVar[str]
    DESCRIPTION: ClassVar[str]
    PARAMETERS: ClassVar[dict[str, Any]]

    def __init__(
        self, tool_id: int, emitter: Emitter, user_key: str | None = None
    ) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
        self._user_key = user_key

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    def tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.PARAMETERS,
            },
        }

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CustomToolStart(tool_name=self.name, tool_id=self.id),
            )
        )

    def _emit_args(self, placement: Placement, args: dict[str, Any]) -> None:
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CustomToolArgs(tool_name=self.name, tool_args=args),
            )
        )

    def _response(self, placement: Placement, result: str) -> ToolResponse:
        llm_facing_response = _truncate_for_llm(result)
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CustomToolDelta(
                    tool_name=self.name,
                    tool_id=self.id,
                    response_type="text",
                    data=result,
                ),
            )
        )
        return ToolResponse(
            rich_response=llm_facing_response,
            llm_facing_response=llm_facing_response,
        )


class RecallMemoryTool(EvaPersonalTool):
    NAME = "recall_memory"
    DISPLAY_NAME = "回忆 EVA 记忆"
    DESCRIPTION = """在 EVA 的完整记忆中搜索 Criss 的历史信息。覆盖长期记忆、Eva 私人笔记、个人知识库、历史对话、联系人/微信记录、Criss 静态画像和关系状态。当用户提到之前、曾经、上次、以前、记得吗、偏好、项目背景、人物、账号、保存的信息或历史经过时使用。"""
    PARAMETERS = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词或事件描述"},
            "scope": {
                "type": "string",
                "enum": sorted(VALID_EVA_MEMORY_SCOPES),
                "description": "搜索范围，默认 all；可选 conversations/memories/notes/knowledge/contacts/profile",
            },
            "limit": {"type": "integer", "description": "每类返回数量，默认 5"},
        },
        "required": ["query"],
    }

    @override
    def run(
        self, placement: Placement, override_kwargs: None, **llm_kwargs: Any
    ) -> ToolResponse:
        args = _preprocess_args(dict(llm_kwargs), "query")
        self._emit_args(placement, args)

        query = str(args.get("query") or "").strip()
        if not query:
            raise ToolCallException(
                "Missing query for recall_memory", "搜索 EVA 记忆失败：缺少查询内容"
            )
        limit = _coerce_limit(args.get("limit"), default=5)
        scope = normalize_eva_memory_scope(str(args.get("scope") or "all"))
        result = EvaMemoryDB(user_key=self._user_key).search(
            query, limit=limit, scope=scope
        )
        formatted = self._format_result(result)
        if not formatted:
            return self._response(placement, "没有找到相关的 EVA 记忆。")

        return self._response(placement, formatted)

    def _format_result(self, result: EvaMemorySearchResult) -> str:
        lines: list[str] = []

        if result.profile:
            profile_lines = self._format_profile(result)
            if profile_lines:
                lines.extend(profile_lines)
                lines.append("")

        for source, items in result.items_by_source.items():
            if not items:
                continue
            lines.append(f"## {source}")
            for index, item in enumerate(items, 1):
                lines.extend(self._format_memory_item(item, index))
            lines.append("")

        return "\n".join(lines).strip()

    def _format_profile(self, result: EvaMemorySearchResult) -> list[str]:
        if result.profile is None:
            return []

        profile = result.profile
        lines = ["## EVA 画像与状态"]
        if profile.counts:
            count_text = ", ".join(
                f"{key}: {value}" for key, value in sorted(profile.counts.items())
            )
            lines.append(f"- 数据量: {count_text}")

        if profile.relationship_state:
            state = profile.relationship_state
            lines.append(
                "- 关系状态: "
                f"阶段={state.get('current_stage')}, "
                f"互动次数={state.get('interaction_count')}, "
                f"连续天数={state.get('continuous_days')}, "
                f"总积分={state.get('total_points')}"
            )

        if profile.criss_profile:
            lines.append("- Criss 静态画像:")
            lines.append(profile.criss_profile)

        return lines

    def _format_memory_item(self, item: EvaMemoryItem, index: int) -> list[str]:
        timestamp = self._format_timestamp(item.timestamp)
        title = item.title or f"{item.source}#{item.id}"
        content = item.content
        if len(content) > 500:
            content = content[:500].rstrip() + "..."

        prefix = f"{index}. [{timestamp}] {title}"
        if item.distance is not None:
            prefix += f" (distance={item.distance:.4f})"

        lines = [prefix, content]
        if item.metadata:
            metadata = json.dumps(item.metadata, ensure_ascii=False)
            if len(metadata) > 260:
                metadata = metadata[:260].rstrip() + "..."
            lines.append(f"metadata: {metadata}")
        lines.append("")
        return lines

    def _format_timestamp(self, timestamp: str | None) -> str:
        if not timestamp:
            return "时间未知"
        return timestamp[:16].replace("T", " ")


class ScheduleReminderTool(EvaPersonalTool):
    NAME = "ScheduleReminder"
    DISPLAY_NAME = "创建定时提醒"
    DESCRIPTION = """创建定时提醒，在指定分钟数后提醒 Criss。当前只支持 recipient 为 Criss 或 owner。参数：message、delay_minutes、recipient（可选）。"""
    PARAMETERS = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "提醒内容"},
            "delay_minutes": {"type": "integer", "description": "多少分钟后提醒"},
            "recipient": {
                "type": "string",
                "description": "接收人，不传则默认 Criss；仅支持 Criss/owner",
            },
        },
        "required": ["message", "delay_minutes"],
    }

    @override
    def run(
        self, placement: Placement, override_kwargs: None, **llm_kwargs: Any
    ) -> ToolResponse:
        args = _preprocess_args(dict(llm_kwargs), "message")
        self._emit_args(placement, args)

        message = str(args.get("message") or "").strip()
        if not message:
            raise ToolCallException(
                "Missing message for ScheduleReminder", "创建失败：缺少提醒内容"
            )

        recipient = str(args.get("recipient") or "Criss").strip()
        if recipient.lower() not in {"criss", "owner"}:
            return self._response(
                placement, "创建失败：定时提醒目前只支持发给 Criss"
            )

        try:
            delay_minutes = int(args.get("delay_minutes"))
        except (TypeError, ValueError):
            raise ToolCallException(
                "Invalid delay_minutes for ScheduleReminder",
                "创建失败：delay_minutes 必须是整数",
            )

        if delay_minutes <= 0:
            return self._response(placement, "创建失败：延迟时间必须大于 0 分钟")
        if delay_minutes > 259200:
            return self._response(
                placement, "创建失败：延迟时间不能超过半年（259200 分钟）"
            )

        from datetime import datetime
        from datetime import timedelta

        send_time = datetime.now() + timedelta(minutes=delay_minutes)
        reminder_id = EvaReminderDB(
            db_path=eva_knowledge_db_path_for_user(self._user_key)
        ).add_reminder(message, recipient, send_time)
        time_str = send_time.strftime("%Y-%m-%d %H:%M")
        result = (
            "提醒已创建\n"
            f"- 内容：{message}\n"
            f"- 时间：{time_str}（{delay_minutes} 分钟后）\n"
            f"- 接收人：{recipient}\n"
            f"- 任务 ID：{reminder_id}"
        )
        return self._response(placement, result)


class EmailManagerTool(EvaPersonalTool):
    NAME = "email_manager"
    DISPLAY_NAME = "邮箱管理"
    DESCRIPTION = """管理 Criss 的邮箱。可以提取最新验证码、查看最新邮件、搜索邮件、读取指定序号邮件完整内容。参数：action(get_code/list_latest/search/read), keywords, limit, email_index。"""
    PARAMETERS = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["get_code", "list_latest", "search", "read"],
                "description": "操作类型",
            },
            "keywords": {
                "type": "string",
                "description": "搜索关键词，用于 search/read",
            },
            "limit": {"type": "integer", "description": "返回邮件数量，默认 5"},
            "email_index": {
                "type": "integer",
                "description": "邮件序号，从 1 开始，用于 read",
            },
        },
        "required": ["action"],
    }

    @override
    def run(
        self, placement: Placement, override_kwargs: None, **llm_kwargs: Any
    ) -> ToolResponse:
        args = _preprocess_args(dict(llm_kwargs), "action")
        self._emit_args(placement, args)

        action = str(args.get("action") or "").strip()
        keywords = args.get("keywords")
        keywords = str(keywords).strip() if keywords is not None else None
        limit = _coerce_limit(args.get("limit"), default=5)
        email_index = self._coerce_optional_int(args.get("email_index"))

        if not self._email_account() or not self._email_password():
            return self._response(
                placement,
                "邮箱未配置，请在部署环境中设置 EMAIL_ACCOUNT 和 EMAIL_PASSWORD",
            )

        mail: imaplib.IMAP4_SSL | None = None
        try:
            mail = self._get_connection()
            if action == "get_code":
                emails = self._fetch_emails(mail, limit=10)
                result = self._extract_verification_code(emails)
                if result:
                    return self._response(
                        placement,
                        f"验证码：{result['code']}\n"
                        f"来源：{result['sender']}\n"
                        f"主题：{result['subject']}\n"
                        f"时间：{result['time']}",
                    )
                return self._response(placement, "未在最近邮件中找到验证码")

            if action == "list_latest":
                emails = self._fetch_emails(mail, limit)
                return self._response(placement, self._format_email_list(emails))

            if action == "search":
                if not keywords:
                    return self._response(placement, "请提供搜索关键词")
                criteria = self._subject_search_criteria(keywords)
                emails = self._fetch_emails(mail, limit, criteria)
                return self._response(placement, self._format_email_list(emails))

            if action == "read":
                if email_index is None:
                    return self._response(
                        placement,
                        "请提供邮件序号（email_index），可先使用 list_latest 或 search 查看邮件列表",
                    )
                if email_index < 1:
                    return self._response(placement, "邮件序号必须从1开始")

                if keywords:
                    criteria = self._subject_search_criteria(keywords)
                    emails = self._fetch_emails(
                        mail,
                        max(email_index, limit),
                        criteria,
                        body_max_length=5000,
                    )
                else:
                    emails = self._fetch_emails(
                        mail, max(email_index, 10), body_max_length=5000
                    )

                if not emails:
                    suffix = "（关键词无匹配）" if keywords else ""
                    return self._response(placement, f"没有找到邮件{suffix}")
                if email_index > len(emails):
                    return self._response(
                        placement,
                        f"邮件序号 {email_index} 超出范围，当前共 {len(emails)} 封邮件",
                    )
                return self._response(
                    placement, self._format_email_detail(emails[email_index - 1])
                )

            return self._response(
                placement,
                f"未知操作：{action}，支持的操作：get_code / list_latest / search / read",
            )
        except imaplib.IMAP4.error as exc:
            return self._response(placement, f"邮箱连接失败：{exc}，请检查账号密码是否正确")
        except Exception as exc:
            return self._response(placement, f"操作失败：{exc}")
        finally:
            if mail is not None:
                self._close_connection(mail)

    def _email_imap_server(self) -> str:
        return os.environ.get("EMAIL_IMAP_SERVER", "imap.qq.com")

    def _email_account(self) -> str | None:
        return os.environ.get("EMAIL_ACCOUNT")

    def _email_password(self) -> str | None:
        return os.environ.get("EMAIL_PASSWORD")

    def _email_folder(self) -> str:
        return os.environ.get("EMAIL_FOLDER", "INBOX")

    def _coerce_optional_int(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _subject_search_criteria(self, keywords: str) -> str:
        escaped_keywords = keywords.replace("\\", "\\\\").replace('"', '\\"')
        return f'(SUBJECT "{escaped_keywords}")'

    def _get_connection(self) -> imaplib.IMAP4_SSL:
        mail = imaplib.IMAP4_SSL(self._email_imap_server(), 993)
        mail.login(self._email_account() or "", self._email_password() or "")
        mail.select(self._email_folder())
        return mail

    def _close_connection(self, mail: imaplib.IMAP4_SSL) -> None:
        try:
            mail.close()
            mail.logout()
        except Exception:
            pass

    def _fetch_emails(
        self,
        mail: imaplib.IMAP4_SSL,
        limit: int,
        search_criteria: str = "ALL",
        body_max_length: int = 2000,
    ) -> list[dict[str, Any]]:
        has_non_ascii = any(ord(char) > 127 for char in search_criteria)
        if has_non_ascii:
            status, data = mail.search("UTF-8", search_criteria.encode("utf-8"))
        else:
            status, data = mail.search(None, search_criteria)
        if status != "OK" or not data:
            return []

        email_ids = data[0].split()
        email_ids = email_ids[-limit:] if len(email_ids) > limit else email_ids

        emails: list[dict[str, Any]] = []
        for email_id in reversed(email_ids):
            status, msg_data = mail.fetch(email_id, "(RFC822)")
            if status == "OK" and msg_data:
                payload = msg_data[0][1]
                if isinstance(payload, bytes):
                    emails.append(
                        self._parse_email(payload, body_max_length=body_max_length)
                    )
        return emails

    def _parse_email(
        self, raw_email: bytes, body_max_length: int = 2000
    ) -> dict[str, Any]:
        msg = email.message_from_bytes(raw_email)
        return {
            "sender": self._decode_header_value(msg.get("From", "")),
            "subject": self._decode_header_value(msg.get("Subject", "")),
            "date": msg.get("Date", ""),
            "body": self._extract_body(msg, max_length=body_max_length),
        }

    def _decode_header_value(self, value: str) -> str:
        if not value:
            return ""
        decoded_parts = decode_header(value)
        result: list[str] = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or "utf-8", errors="ignore"))
            else:
                result.append(part)
        return "".join(result)

    def _extract_body(self, msg: email.message.Message, max_length: int = 2000) -> str:
        body = ""
        html_body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body = payload.decode(charset, errors="ignore")
                        break
                elif content_type == "text/html" and not html_body:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        html_body = payload.decode(charset, errors="ignore")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                raw = payload.decode(charset, errors="ignore")
                if msg.get_content_type() == "text/html":
                    html_body = raw
                else:
                    body = raw

        if not body and html_body:
            body = self._html_to_text(html_body)
        return body[:max_length] if body else ""

    def _html_to_text(self, html: str) -> str:
        class _TextExtractor(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.texts: list[str] = []
                self._skip = False

            def handle_starttag(
                self, tag: str, attrs: list[tuple[str, str | None]]
            ) -> None:
                if tag in {"script", "style"}:
                    self._skip = True

            def handle_endtag(self, tag: str) -> None:
                if tag in {"script", "style"}:
                    self._skip = False

            def handle_data(self, data: str) -> None:
                if self._skip:
                    return
                text = data.strip()
                if text:
                    self.texts.append(text)

        extractor = _TextExtractor()
        try:
            extractor.feed(html)
        except Exception:
            pass
        return "\n".join(extractor.texts)

    def _extract_verification_code(
        self, emails: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        patterns = [
            r"验证码[是为：:\s]*(\d{4,6})",
            r"code[是为：:\s]*(\d{4,6})",
            r"动态码[是为：:\s]*(\d{4,6})",
            r"(\d{6})\s*为您的验证码",
            r"验证码.*?(\d{4,6})",
        ]
        for email_info in emails:
            content = f"{email_info.get('body', '')} {email_info.get('subject', '')}"
            for pattern in patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    return {
                        "code": match.group(1),
                        "sender": email_info.get("sender", ""),
                        "subject": email_info.get("subject", ""),
                        "time": email_info.get("date", ""),
                    }
        return None

    def _format_email_list(self, emails: list[dict[str, Any]]) -> str:
        if not emails:
            return "没有找到邮件"

        lines = ["最近邮件："]
        for index, email_info in enumerate(emails, 1):
            date_str = str(email_info.get("date", ""))[:16]
            sender = str(email_info.get("sender", ""))[:25]
            subject = str(email_info.get("subject", ""))[:40]
            lines.append(f"{index}. [{date_str}] {sender}\n   {subject}")
        lines.append("\n可使用 action=read, email_index=<序号> 查看完整邮件正文")
        return "\n".join(lines)

    def _format_email_detail(self, email_info: dict[str, Any]) -> str:
        sender = email_info.get("sender", "（无）")
        subject = email_info.get("subject", "（无主题）")
        date = email_info.get("date", "（无时间）")
        body = email_info.get("body") or "（正文为空）"
        return (
            f"发件人：{sender}\n"
            f"主题：{subject}\n"
            f"时间：{date}\n"
            "----------------------------------------\n"
            f"{body}"
        )
