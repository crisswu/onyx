from __future__ import annotations

import json
from abc import ABC
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import ClassVar

from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.eva_knowledge import EvaKnowledgeDB
from onyx.db.eva_knowledge import EvaKnowledgeFragment
from onyx.db.eva_knowledge import VALID_EVA_FRAGMENT_TYPES
from onyx.db.eva_knowledge import coerce_metadata
from onyx.db.eva_knowledge import get_eva_knowledge_db
from onyx.db.eva_knowledge import normalize_fragment_type
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CustomToolArgs
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse

MAX_LLM_FACING_RESPONSE_CHARS = 8000

TYPE_NAMES = {
    "account": "账号",
    "bookmark": "书签",
    "diary": "日记",
    "code": "代码",
    "note": "笔记",
}

TYPE_LABELS = {
    "account": "账号",
    "bookmark": "书签",
    "diary": "日记",
    "code": "代码",
    "note": "笔记",
}


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


def _coerce_limit(value: Any, default: int, minimum: int = 1, maximum: int = 200) -> int:
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


def _coerce_tags(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        if not value:
            return []
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass
        return [item.strip() for item in value.split(",") if item.strip()]
    return None


def _format_fragment(fragment: EvaKnowledgeFragment, index: int) -> str:
    type_label = TYPE_LABELS.get(fragment.type, "信息")
    result = f"**{index}. [{type_label}] {fragment.title}** (ID: {fragment.id})\n"
    result += f"{fragment.content}\n"
    if fragment.metadata:
        meta_str = ", ".join(f"{key}: {value}" for key, value in fragment.metadata.items())
        result += f"  附加信息: {meta_str}\n"
    if fragment.distance is not None:
        result += f"  相关度: {(1 - fragment.distance) * 100:.1f}%"
    return result.rstrip()


class EvaKnowledgeTool(Tool[None], ABC):
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

    def _db(self) -> EvaKnowledgeDB:
        return get_eva_knowledge_db(self._user_key)


class SaveNoteTool(EvaKnowledgeTool):
    NAME = "save_note"
    DISPLAY_NAME = "保存笔记"
    DESCRIPTION = """保存重要信息到个人知识库。仅当用户明确要求保存、记录、记下或添加信息时调用。支持类型：account(账号)、bookmark(网址/书签)、diary(日记)、code(代码)、note(笔记)。"""
    PARAMETERS = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "标题或简短描述"},
            "content": {"type": "string", "description": "详细内容"},
            "original_content": {"type": "string", "description": "用户原始文本"},
            "type": {
                "type": "string",
                "enum": sorted(VALID_EVA_FRAGMENT_TYPES),
                "description": "信息类型",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "标签列表",
            },
            "metadata": {
                "type": "object",
                "description": "额外结构化信息，如账号、URL 等",
            },
            "name": {"type": "string", "description": "title 的兼容别名"},
        },
        "required": ["title", "content"],
    }

    @override
    def run(
        self, placement: Placement, override_kwargs: None, **llm_kwargs: Any
    ) -> ToolResponse:
        args = _preprocess_args(dict(llm_kwargs), "title")
        self._emit_args(placement, args)

        title = str(args.get("title") or args.get("name") or "").strip()
        if not title:
            raise ToolCallException("Missing title for save_note", "保存失败：缺少标题")

        metadata = coerce_metadata(args.get("metadata")) or {}
        for key, value in args.items():
            if key not in {
                "title",
                "name",
                "content",
                "original_content",
                "type",
                "tags",
                "metadata",
            }:
                metadata[key] = value

        content = str(args.get("content") or "").strip()
        if not content and metadata:
            content = "\n".join(f"{key}: {value}" for key, value in metadata.items())
        if not content:
            raise ToolCallException("Missing content for save_note", "保存失败：缺少内容")

        fragment_type = normalize_fragment_type(str(args.get("type") or "note")) or "note"
        fragment_id = self._db().add(
            EvaKnowledgeFragment(
                title=title,
                content=content,
                original_content=str(args.get("original_content") or ""),
                type=fragment_type,
                tags=_coerce_tags(args.get("tags")),
                metadata=metadata or None,
            )
        )
        type_name = TYPE_NAMES.get(fragment_type, "信息")
        return self._response(placement, f"已保存{type_name}「{title}」(ID: {fragment_id})")


class SearchNotesTool(EvaKnowledgeTool):
    NAME = "search_notes"
    DISPLAY_NAME = "搜索笔记"
    DESCRIPTION = """在个人知识库中搜索信息。当用户询问自己的账号、密码、保存的网址、日记、代码片段或笔记内容时调用。可按类型筛选。"""
    PARAMETERS = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词或自然语言问题"},
            "type_filter": {
                "type": "string",
                "enum": sorted(VALID_EVA_FRAGMENT_TYPES),
                "description": "可选类型筛选",
            },
            "limit": {"type": "integer", "description": "返回数量，默认 5"},
            "type": {"type": "string", "description": "type_filter 的兼容别名"},
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
            raise ToolCallException("Missing query for search_notes", "搜索失败：缺少查询内容")

        type_filter = normalize_fragment_type(
            str(args.get("type_filter") or args.get("type") or "")
        )
        limit = _coerce_limit(args.get("limit"), default=5, maximum=50)
        fragments = self._db().search(query, type_filter=type_filter, limit=limit)
        if not fragments:
            return self._response(placement, "未找到相关信息")

        result = "\n\n".join(
            _format_fragment(fragment, index)
            for index, fragment in enumerate(fragments, 1)
        )
        return self._response(placement, result)


class ListNotesTool(EvaKnowledgeTool):
    NAME = "list_notes"
    DISPLAY_NAME = "列出笔记"
    DESCRIPTION = """管理个人知识库记录。支持 stats(统计概览)、list(按类型列出)、all(列出全部)。类型包括 account、bookmark、diary、code、note。"""
    PARAMETERS = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["stats", "list", "all"],
                "description": "操作类型",
            },
            "type_filter": {
                "type": "string",
                "enum": sorted(VALID_EVA_FRAGMENT_TYPES),
                "description": "要列出的类型",
            },
            "limit": {"type": "integer", "description": "返回数量，默认 100"},
            "type": {"type": "string", "description": "type_filter 的兼容别名"},
        },
    }

    @override
    def run(
        self, placement: Placement, override_kwargs: None, **llm_kwargs: Any
    ) -> ToolResponse:
        args = _preprocess_args(dict(llm_kwargs), "action")
        self._emit_args(placement, args)

        action = args.get("action")
        type_filter = normalize_fragment_type(
            str(args.get("type_filter") or args.get("type") or "")
        )
        if action is None:
            action = "list" if type_filter else "stats"
        action = str(action)
        limit = _coerce_limit(args.get("limit"), default=100)

        db = self._db()
        if action == "stats":
            lines = ["数据库统计概览", "------------------"]
            total = 0
            for fragment_type in sorted(VALID_EVA_FRAGMENT_TYPES):
                count = db.count(fragment_type)
                total += count
                lines.append(f"{TYPE_NAMES.get(fragment_type, fragment_type)}: {count} 条")
            lines.append("------------------")
            lines.append(f"总计: {total} 条记录")
            return self._response(placement, "\n".join(lines))

        if action == "list":
            if not type_filter:
                return self._response(
                    placement, "请指定要列出的类型，或使用 action='all' 列出全部记录。"
                )
            fragments = db.list_by_type(type_filter, limit=limit)
            if not fragments:
                return self._response(
                    placement, f"未找到{TYPE_NAMES.get(type_filter, type_filter)}记录"
                )
            header = f"【{TYPE_NAMES.get(type_filter, type_filter)}列表】共 {len(fragments)} 条："
            return self._response(placement, self._format_list(fragments, header))

        if action == "all":
            fragments = db.list_all(limit=limit)
            total = db.count()
            if not fragments:
                return self._response(placement, "数据库为空，暂无记录")
            header = f"【全部记录】共 {total} 条"
            if len(fragments) < total:
                header += f"，显示前 {len(fragments)} 条"
            header += "："
            return self._response(placement, self._format_list(fragments, header))

        return self._response(
            placement, "无效的操作。支持的操作: stats, list, all"
        )

    def _format_list(self, fragments: list[EvaKnowledgeFragment], header: str) -> str:
        lines = [header]
        for index, fragment in enumerate(fragments, 1):
            type_label = TYPE_LABELS.get(fragment.type, "信息")
            content = fragment.content[:200]
            suffix = "..." if len(fragment.content) > 200 else ""
            lines.append(
                f"\n**{index}. [{type_label}] {fragment.title}** (ID: {fragment.id})"
                f"\n{content}{suffix}"
            )
            if fragment.metadata:
                meta_str = ", ".join(
                    f"{key}: {value}" for key, value in fragment.metadata.items()
                )
                lines.append(f"  附加信息: {meta_str}")
        return "\n".join(lines)


class UpdateNoteTool(EvaKnowledgeTool):
    NAME = "update_note"
    DISPLAY_NAME = "修改笔记"
    DESCRIPTION = """修改知识库中已保存的信息。先用 search_notes 或 list_notes 找到记录 ID，再传入 ID 和要修改的字段。未提供的字段保持不变。"""
    PARAMETERS = {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "description": "要修改的记录 ID"},
            "title": {"type": "string", "description": "新标题"},
            "content": {"type": "string", "description": "新内容"},
            "type": {
                "type": "string",
                "enum": sorted(VALID_EVA_FRAGMENT_TYPES),
                "description": "新类型",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "新标签列表",
            },
            "metadata": {"type": "object", "description": "新的额外信息"},
        },
        "required": ["id"],
    }

    @override
    def run(
        self, placement: Placement, override_kwargs: None, **llm_kwargs: Any
    ) -> ToolResponse:
        args = _preprocess_args(dict(llm_kwargs), "id")
        self._emit_args(placement, args)

        try:
            fragment_id = int(args["id"])
        except (KeyError, TypeError, ValueError):
            raise ToolCallException("Missing id for update_note", "修改失败：缺少记录 ID")

        db = self._db()
        original = db.get(fragment_id)
        if original is None:
            return self._response(placement, f"未找到ID为 {fragment_id} 的记录")

        metadata = coerce_metadata(args.get("metadata"))
        fragment_type = normalize_fragment_type(str(args.get("type") or "")) or original.type
        content = args.get("content")
        final_content = str(content) if content is not None else original.content
        final_metadata = metadata if metadata is not None else original.metadata

        if original.type == "account" and metadata is not None and content is None:
            username = metadata.get("username", "")
            password = metadata.get("password", "")
            if username or password:
                final_content = f"账号：{username}，密码：{password}"

        updated = EvaKnowledgeFragment(
            id=fragment_id,
            title=str(args.get("title") or original.title),
            content=final_content,
            original_content=original.original_content,
            type=fragment_type,
            tags=_coerce_tags(args.get("tags")) if "tags" in args else original.tags,
            metadata=final_metadata,
        )
        success = db.update(updated)
        if not success:
            return self._response(placement, "修改失败，请检查ID是否正确")

        changes: list[str] = []
        if args.get("title"):
            changes.append(f"标题→「{args['title']}」")
        if content is not None:
            changes.append("内容已更新")
        if args.get("type"):
            changes.append(f"类型→{TYPE_NAMES.get(fragment_type, fragment_type)}")
        if "tags" in args:
            changes.append(f"标签→{updated.tags}")
        if metadata is not None:
            changes.append("元数据已更新")
        changes_str = "、".join(changes) if changes else "无变化"
        return self._response(
            placement, f"已修改记录 (ID: {fragment_id})\n  变更: {changes_str}"
        )


class DeleteNoteTool(EvaKnowledgeTool):
    NAME = "delete_note"
    DISPLAY_NAME = "删除笔记"
    DESCRIPTION = """从知识库中删除已保存的信息。安全限制：只能删除单个记录；仅当用户明确要求删除某个 ID 时调用。建议先用 search_notes 或 list_notes 确认记录。"""
    PARAMETERS = {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "description": "要删除的单个记录 ID"},
        },
        "required": ["id"],
    }

    @override
    def run(
        self, placement: Placement, override_kwargs: None, **llm_kwargs: Any
    ) -> ToolResponse:
        args = _preprocess_args(dict(llm_kwargs), "id")
        self._emit_args(placement, args)

        try:
            fragment_id = int(args["id"])
        except (KeyError, TypeError, ValueError):
            raise ToolCallException("Missing id for delete_note", "删除失败：缺少记录 ID")

        db = self._db()
        fragment = db.get(fragment_id)
        if fragment is None:
            self._log_deletion(db.db_path.parent, fragment_id, "(不存在)", False, "记录不存在")
            return self._response(placement, f"ID {fragment_id} 的记录不存在")

        success = db.delete(fragment_id)
        self._log_deletion(
            db.db_path.parent,
            fragment_id,
            fragment.title,
            success,
            None if success else "数据库删除失败",
        )
        if success:
            return self._response(placement, f"已删除 id={fragment_id} [{fragment.title}]")
        return self._response(placement, "删除失败：数据库错误")

    def _log_deletion(
        self,
        data_dir: Path,
        fragment_id: int,
        title: str,
        success: bool,
        error: str | None,
    ) -> None:
        try:
            log_file = data_dir / "deletions.log"
            status = "成功" if success else "失败"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry = (
                "\n"
                "============================================================\n"
                f"[删除操作] {timestamp}\n"
                f"ID: {fragment_id}\n"
                f"标题: {title}\n"
                f"状态: {status}\n"
            )
            if error:
                entry += f"错误: {error}\n"
            entry += "============================================================\n"
            with log_file.open("a", encoding="utf-8") as file:
                file.write(entry)
        except Exception:
            pass
