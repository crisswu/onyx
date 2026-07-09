from __future__ import annotations

import json
import re
from abc import ABC
from typing import Any
from typing import ClassVar

from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.eva_rss import DEFAULT_SEARCH_LIMIT
from onyx.db.eva_rss import EvaRssDB
from onyx.db.eva_rss import RssFeedSubscription
from onyx.db.eva_rss import RssSearchResponse
from onyx.rss.fetcher import discover_or_parse_feed
from onyx.rss.fetcher import fetch_subscription_now
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


def _truncate_for_llm(text: str, limit: int = MAX_LLM_FACING_RESPONSE_CHARS) -> str:
    if len(text) <= limit:
        return text
    return (
        text[:limit].rstrip()
        + "\n\n..."
        + "（RSS 工具结果过长，已截断给模型读取，原始长度 "
        + f"{len(text)} 字符）"
    )


def _coerce_tags(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        if not value.strip():
            return []
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
        return [item.strip() for item in value.split(",") if item.strip()]
    return None


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "enable", "enabled"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disable", "disabled"}:
        return False
    return default


def _coerce_int(value: Any, default: int, minimum: int = 1, maximum: int = 50) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time_range_hours(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    match = re.fullmatch(r"(\d+)\s*([hdw])", text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if unit == "h":
            return amount
        if unit == "d":
            return amount * 24
        if unit == "w":
            return amount * 24 * 7
    try:
        return int(text)
    except ValueError:
        return None


class EvaRssTool(Tool[None], ABC):
    NAME: ClassVar[str]
    DISPLAY_NAME: ClassVar[str]
    DESCRIPTION: ClassVar[str]
    PARAMETERS: ClassVar[dict[str, Any]]

    def __init__(
        self,
        tool_id: int,
        emitter: Emitter,
        user_key: str | None = None,
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

    def _db(self) -> EvaRssDB:
        return EvaRssDB(user_key=self._user_key)


class AddRssSubscriptionTool(EvaRssTool):
    NAME = "add_rss_subscription"
    DISPLAY_NAME = "添加 RSS 订阅"
    DESCRIPTION = (
        "添加一个 RSS/Atom 订阅源到 EVA 的本地 RSS 订阅池。仅当用户明确"
        "要求添加 RSS 订阅或提到 RSS 时调用。可传 RSS/Atom URL，也可传"
        "普通网页 URL 来发现 RSS feed。"
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "RSS/Atom URL 或普通网页 URL"},
            "name": {"type": "string", "description": "订阅源显示名称，可选"},
            "category": {"type": "string", "description": "订阅源分类，可选"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "订阅源标签，可选",
            },
            "fetch_interval_hours": {
                "type": "integer",
                "description": "抓取间隔小时数，默认 12，最小 1",
            },
            "priority_weight": {
                "type": "number",
                "description": "来源排序权重，默认 1.0",
            },
        },
        "required": ["url"],
    }

    @override
    def run(
        self,
        placement: Placement,
        override_kwargs: None,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        args = _preprocess_args(dict(llm_kwargs), "url")
        self._emit_args(placement, args)

        url = str(args.get("url") or "").strip()
        if not url:
            raise ToolCallException(
                "Missing url for add_rss_subscription",
                "添加 RSS 订阅失败：缺少 url",
            )

        candidates, error = discover_or_parse_feed(url)
        if error:
            return self._response(placement, f"没有找到可订阅的 RSS/Atom feed：{error}")
        if len(candidates) > 1:
            lines = ["发现多个 RSS/Atom 订阅候选，请让用户选择其中一个："]
            for index, candidate in enumerate(candidates, 1):
                lines.append(f"{index}. {candidate.title} - {candidate.feed_url}")
            return self._response(placement, "\n".join(lines))
        if not candidates:
            return self._response(placement, "没有找到可订阅的 RSS/Atom feed。")

        candidate = candidates[0]
        db = self._db()
        subscription = db.add_subscription(
            name=str(args.get("name") or candidate.title or candidate.feed_url),
            feed_url=candidate.feed_url,
            site_url=candidate.site_url,
            category=_optional_str(args.get("category")),
            tags=_coerce_tags(args.get("tags")),
            fetch_interval_hours=args.get("fetch_interval_hours"),
            priority_weight=_optional_float(args.get("priority_weight")) or 1.0,
        )
        fetch_result = fetch_subscription_now(db, subscription)
        lines = [
            "已添加 RSS 订阅。",
            _format_subscription(subscription),
        ]
        if fetch_result.error:
            lines.append(f"首次抓取失败：{fetch_result.error}")
        else:
            lines.append(
                "首次抓取完成："
                f"{fetch_result.item_count} 条，"
                f"新增 {fetch_result.new_article_count} 条，"
                f"更新 {fetch_result.updated_article_count} 条。"
            )
        return self._response(placement, "\n".join(lines))


class ListRssSubscriptionsTool(EvaRssTool):
    NAME = "list_rss_subscriptions"
    DISPLAY_NAME = "列出 RSS 订阅"
    DESCRIPTION = (
        "列出 EVA 本地 RSS 订阅池中的 RSS/Atom 订阅源和健康状态。仅当"
        "用户明确询问 RSS 订阅列表、RSS 状态或 RSS 来源时调用。"
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "include_disabled": {
                "type": "boolean",
                "description": "是否包含已停用/归档的 RSS 订阅，默认 true",
            }
        },
    }

    @override
    def run(
        self,
        placement: Placement,
        override_kwargs: None,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        args = _preprocess_args(dict(llm_kwargs), "include_disabled")
        self._emit_args(placement, args)
        include_disabled = _coerce_bool(args.get("include_disabled"), default=True)
        subscriptions = self._db().list_subscriptions(
            include_disabled=include_disabled
        )
        if not subscriptions:
            return self._response(placement, "当前没有 RSS 订阅。")
        lines = ["RSS 订阅列表："]
        for subscription in subscriptions:
            lines.append(_format_subscription(subscription))
        return self._response(placement, "\n\n".join(lines))


class UpdateRssSubscriptionTool(EvaRssTool):
    NAME = "update_rss_subscription"
    DISPLAY_NAME = "更新 RSS 订阅"
    DESCRIPTION = (
        "更新、停用或重新启用 EVA 本地 RSS 订阅。用户说删除/移除 RSS "
        "订阅时，也调用此工具将订阅停用或归档，而不是物理删除。"
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "subscription_id": {"type": "integer", "description": "RSS 订阅 ID"},
            "name": {"type": "string", "description": "新的显示名称，可选"},
            "category": {"type": "string", "description": "新的分类，可选"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "新的标签列表，可选",
            },
            "fetch_interval_hours": {
                "type": "integer",
                "description": "新的抓取间隔小时数，可选，最小 1",
            },
            "priority_weight": {"type": "number", "description": "新的来源权重，可选"},
            "enabled": {
                "type": "boolean",
                "description": "是否启用；删除/移除订阅时设为 false",
            },
            "fetch_now": {"type": "boolean", "description": "是否立即抓取一次"},
        },
        "required": ["subscription_id"],
    }

    @override
    def run(
        self,
        placement: Placement,
        override_kwargs: None,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        args = _preprocess_args(dict(llm_kwargs), "subscription_id")
        self._emit_args(placement, args)
        subscription_id = _coerce_int(
            args.get("subscription_id"),
            default=0,
            minimum=0,
        )
        if subscription_id <= 0:
            raise ToolCallException(
                "Missing subscription_id for update_rss_subscription",
                "更新 RSS 订阅失败：缺少 subscription_id",
            )

        db = self._db()
        updated = db.update_subscription(
            subscription_id,
            name=_optional_str(args.get("name")) if "name" in args else None,
            category=(
                _optional_str(args.get("category")) if "category" in args else None
            ),
            tags=_coerce_tags(args.get("tags")) if "tags" in args else None,
            fetch_interval_hours=args.get("fetch_interval_hours"),
            priority_weight=_optional_float(args.get("priority_weight")),
            enabled=(
                _coerce_bool(args.get("enabled"), default=True)
                if "enabled" in args
                else None
            ),
        )
        if updated is None:
            return self._response(placement, f"没有找到 RSS 订阅 ID: {subscription_id}")

        lines = ["已更新 RSS 订阅。", _format_subscription(updated)]
        if _coerce_bool(args.get("fetch_now"), default=False) and updated.enabled:
            fetch_result = fetch_subscription_now(db, updated)
            if fetch_result.error:
                lines.append(f"立即抓取失败：{fetch_result.error}")
            else:
                lines.append(
                    "立即抓取完成："
                    f"{fetch_result.item_count} 条，"
                    f"新增 {fetch_result.new_article_count} 条，"
                    f"更新 {fetch_result.updated_article_count} 条。"
                )
        return self._response(placement, "\n".join(lines))


class SearchRssArticlesTool(EvaRssTool):
    NAME = "search_rss_articles"
    DISPLAY_NAME = "搜索 RSS 文章"
    DESCRIPTION = (
        "搜索 EVA 本地 RSS 订阅池中的 RSS/Atom 文章。仅当用户明确要求"
        "搜索 RSS、查看 RSS 信息或提到 RSS 时调用；不要把它用于普通"
        "网页搜索、内部文档搜索或记忆搜索。"
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "RSS 文章搜索关键词"},
            "time_range": {
                "type": "string",
                "description": "时间范围，如 12h、24h、7d、30d；默认 7d",
            },
            "categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": "分类过滤，可选",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "标签过滤，可选",
            },
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "来源名过滤，可选",
            },
            "limit": {"type": "integer", "description": "返回条数，默认 10"},
            "include_disabled_sources": {
                "type": "boolean",
                "description": "是否包含已停用 RSS 来源的历史文章，默认 false",
            },
        },
        "required": ["query"],
    }

    @override
    def run(
        self,
        placement: Placement,
        override_kwargs: None,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        args = _preprocess_args(dict(llm_kwargs), "query")
        self._emit_args(placement, args)
        query = str(args.get("query") or "").strip()
        if not query:
            raise ToolCallException(
                "Missing query for search_rss_articles",
                "搜索 RSS 文章失败：缺少 query",
            )
        response = self._db().search_articles(
            query,
            time_range_hours=_parse_time_range_hours(args.get("time_range")),
            categories=_coerce_tags(args.get("categories")),
            tags=_coerce_tags(args.get("tags")),
            sources=_coerce_tags(args.get("sources")),
            limit=_coerce_int(args.get("limit"), default=DEFAULT_SEARCH_LIMIT),
            include_disabled_sources=_coerce_bool(
                args.get("include_disabled_sources"),
                default=False,
            ),
        )
        return self._response(placement, _format_search_response(response))


def _format_subscription(subscription: RssFeedSubscription) -> str:
    tags = ", ".join(subscription.tags) if subscription.tags else "无"
    return (
        f"ID: {subscription.id}\n"
        f"名称: {subscription.name}\n"
        f"RSS: {subscription.feed_url}\n"
        f"站点: {subscription.site_url or '未知'}\n"
        f"分类: {subscription.category or '未分类'}\n"
        f"标签: {tags}\n"
        f"状态: {subscription.status} "
        f"({'启用' if subscription.enabled else '停用'})\n"
        f"抓取间隔: {subscription.fetch_interval_hours} 小时\n"
        f"最近尝试: {subscription.last_fetch_attempt_at or '无'}\n"
        f"最近成功: {subscription.last_success_at or '无'}\n"
        f"连续失败: {subscription.consecutive_failures}\n"
        f"最后错误: {subscription.last_error or '无'}"
    )


def _format_search_response(response: RssSearchResponse) -> str:
    lines = [
        f"RSS 本地搜索状态: {response.status}",
        f"搜索范围: {response.searched_since} 到 {response.searched_until}",
        f"最近成功抓取: {response.latest_success_at or '无'}",
    ]
    if not response.results:
        lines.append("没有找到匹配的 RSS 文章。")
        return "\n".join(lines)

    lines.append("RSS 搜索结果：")
    for index, result in enumerate(response.results, 1):
        published = (
            result.published_at
            if not result.publication_time_unknown
            else f"发布时间未知，首次抓取 {result.first_seen_at}"
        )
        sources = ", ".join(result.seen_sources)
        summary = result.summary[:500].rstrip()
        if len(result.summary) > 500:
            summary += "..."
        tags = ", ".join(result.feed_tags) if result.feed_tags else "无"
        lines.extend(
            [
                f"{index}. {result.title} (ID: {result.article_id})",
                f"来源: {result.primary_source}；出现来源数: {result.source_count}",
                f"所有来源: {sources or '未知'}",
                f"时间: {published}",
                f"URL: {result.canonical_url or '无'}",
                f"分类: {result.feed_category or '未分类'}；标签: {tags}",
                f"匹配: {result.match_reason}; score={result.rank_score:.2f}",
                f"摘要: {summary or '无摘要'}",
                "",
            ]
        )
    return "\n".join(lines).strip()
