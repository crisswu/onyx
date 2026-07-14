from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sqlite3
import tempfile
from collections.abc import Callable
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import ClassVar
from typing import Protocol

from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.eva_config import AliyunOssBackupConfig
from onyx.db.eva_config import get_eva_backup_config
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CustomToolArgs
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse

MAX_LLM_FACING_RESPONSE_CHARS = 8000
OSS_CONNECT_TIMEOUT_SECONDS = 60
OSS_MULTIPART_THRESHOLD_BYTES = 128 * 1024
OSS_PART_SIZE_BYTES = 128 * 1024
OSS_UPLOAD_THREADS = 4


class OssBucket(Protocol):
    def put_object_from_file(self, key: str, filename: str) -> Any: ...

    def put_object(self, key: str, data: bytes) -> Any: ...


type FileUploader = Callable[[OssBucket, str, Path], Any]


@dataclass(frozen=True)
class SnapshotFile:
    name: str
    original_name: str
    source_path: Path
    snapshot_path: Path
    object_key: str
    size: int
    sha256: str
    original_size: int
    original_sha256: str
    compression: str


def _truncate_for_llm(text: str, limit: int = MAX_LLM_FACING_RESPONSE_CHARS) -> str:
    if len(text) <= limit:
        return text
    return (
        text[:limit].rstrip()
        + f"\n\n...（备份结果过长，已截断给模型读取，原始长度 {len(text)} 字符）"
    )


def _normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_sqlite_database(source_path: Path, destination_path: Path) -> None:
    if not source_path.exists():
        raise ToolCallException(
            f"EVA backup source database does not exist: {source_path}",
            f"备份失败：数据库文件不存在：{source_path.name}",
        )
    if not source_path.is_file():
        raise ToolCallException(
            f"EVA backup source path is not a file: {source_path}",
            f"备份失败：数据库路径不是文件：{source_path.name}",
        )

    source_uri = f"file:{source_path}?mode=ro"
    with sqlite3.connect(source_uri, uri=True, timeout=30) as source:
        with sqlite3.connect(destination_path) as destination:
            source.backup(destination)


def _gzip_file(source_path: Path, destination_path: Path) -> None:
    with source_path.open("rb") as source:
        with gzip.open(destination_path, "wb", compresslevel=6) as destination:
            shutil.copyfileobj(source, destination)


def _default_bucket_factory(config: AliyunOssBackupConfig) -> OssBucket:
    import oss2

    auth = oss2.Auth(config.access_key_id, config.access_key_secret)
    return oss2.Bucket(
        auth,
        config.endpoint,
        config.bucket,
        connect_timeout=OSS_CONNECT_TIMEOUT_SECONDS,
    )


def _default_file_uploader(bucket: OssBucket, key: str, path: Path) -> Any:
    from oss2 import resumable

    return resumable.resumable_upload(
        bucket,
        key,
        str(path),
        multipart_threshold=OSS_MULTIPART_THRESHOLD_BYTES,
        part_size=OSS_PART_SIZE_BYTES,
        num_threads=OSS_UPLOAD_THREADS,
    )


class BackupEvaDataToOssTool(Tool[None]):
    NAME = "backup_eva_data_to_oss"
    DISPLAY_NAME = "备份 EVA 数据"
    DESCRIPTION = (
        "手动将 EVA 核心数据文件 knowledge.db 和 conversation.db 备份到"
        "管理员配置的阿里云 OSS。仅当用户明确要求备份 EVA 数据时调用。"
    )
    PARAMETERS: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(
        self,
        tool_id: int,
        emitter: Emitter,
        user_email: str | None = None,
        bucket_factory: Callable[[AliyunOssBackupConfig], OssBucket]
        | None = None,
        file_uploader: FileUploader | None = None,
    ) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
        self._user_email = _normalize_email(user_email)
        self._bucket_factory = bucket_factory or _default_bucket_factory
        self._file_uploader = file_uploader or _default_file_uploader

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

    @classmethod
    @override
    def is_available(cls, db_session: Any) -> bool:  # noqa: ARG003
        config = get_eva_backup_config()
        return (
            config.knowledge_db_path is not None
            and config.conversation_db_path is not None
            and config.aliyun_oss_backup is not None
        )

    @classmethod
    def is_user_authorized(cls, user_email: str | None) -> bool:
        config = get_eva_backup_config()
        return _normalize_email(user_email) == _normalize_email(config.owner_email)

    @override
    def tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.PARAMETERS,
            },
        }

    @override
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

    @override
    def run(
        self,
        placement: Placement,
        override_kwargs: None,  # noqa: ARG002
        **_llm_kwargs: Any,
    ) -> ToolResponse:
        self._emit_args(placement, {})

        config = get_eva_backup_config()
        owner_email = _normalize_email(config.owner_email)
        if self._user_email != owner_email:
            raise ToolCallException(
                f"User {self._user_email or '<anonymous>'} cannot back up EVA data",
                "备份失败：只有 EVA 管理员账号可以执行数据备份。",
            )

        if not config.knowledge_db_path or not config.conversation_db_path:
            raise ToolCallException(
                "EVA backup database paths are not configured",
                "备份失败：EVA 数据库路径未配置。",
            )
        if config.aliyun_oss_backup is None:
            raise ToolCallException(
                "EVA Aliyun OSS backup config is not configured",
                "备份失败：阿里云 OSS 备份配置未完成。",
            )

        timestamp = datetime.now().astimezone()
        timestamp_key = timestamp.strftime("%Y-%m-%dT%H-%M-%S-%f%z")
        backup_prefix = f"{config.aliyun_oss_backup.prefix}/{timestamp_key}"

        files_to_backup = [
            ("knowledge.db", config.knowledge_db_path),
            ("conversation.db", config.conversation_db_path),
        ]

        with tempfile.TemporaryDirectory(prefix="eva-backup-") as temp_dir:
            snapshots = self._create_snapshots(
                files_to_backup=files_to_backup,
                backup_prefix=backup_prefix,
                temp_dir=Path(temp_dir),
            )
            try:
                bucket = self._bucket_factory(config.aliyun_oss_backup)
                for snapshot in snapshots:
                    try:
                        self._file_uploader(
                            bucket, snapshot.object_key, snapshot.snapshot_path
                        )
                    except Exception as e:
                        raise ToolCallException(
                            "EVA OSS backup upload failed for "
                            f"{snapshot.name}: {type(e).__name__}",
                            f"备份失败：上传 {snapshot.name} 到阿里云 OSS 时出错。"
                            "当前服务器到 OSS 的上传链路较慢或超时，请稍后重试。",
                        ) from e

                manifest_key = f"{backup_prefix}/manifest.json"
                manifest = self._build_manifest(
                    owner_email=owner_email,
                    created_at=timestamp.isoformat(),
                    backup_prefix=backup_prefix,
                    snapshots=snapshots,
                )
                bucket.put_object(
                    manifest_key,
                    json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                )
            except Exception as e:
                if isinstance(e, ToolCallException):
                    raise
                raise ToolCallException(
                    f"EVA OSS backup upload failed: {type(e).__name__}",
                    "备份失败：上传到阿里云 OSS 时出错，请检查 OSS 配置、权限和网络。",
                ) from e

        result = self._format_success_response(
            backup_prefix=backup_prefix,
            manifest_key=manifest_key,
            snapshots=snapshots,
        )
        return self._response(placement, result)

    def _create_snapshots(
        self,
        files_to_backup: Sequence[tuple[str, Path]],
        backup_prefix: str,
        temp_dir: Path,
    ) -> list[SnapshotFile]:
        snapshots: list[SnapshotFile] = []
        for filename, source_path in files_to_backup:
            sqlite_snapshot_path = temp_dir / filename
            _snapshot_sqlite_database(source_path, sqlite_snapshot_path)
            compressed_snapshot_path = temp_dir / f"{filename}.gz"
            _gzip_file(sqlite_snapshot_path, compressed_snapshot_path)
            snapshots.append(
                SnapshotFile(
                    name=f"{filename}.gz",
                    original_name=filename,
                    source_path=source_path,
                    snapshot_path=compressed_snapshot_path,
                    object_key=f"{backup_prefix}/{filename}.gz",
                    size=compressed_snapshot_path.stat().st_size,
                    sha256=_sha256(compressed_snapshot_path),
                    original_size=sqlite_snapshot_path.stat().st_size,
                    original_sha256=_sha256(sqlite_snapshot_path),
                    compression="gzip",
                )
            )
        return snapshots

    def _build_manifest(
        self,
        owner_email: str,
        created_at: str,
        backup_prefix: str,
        snapshots: Sequence[SnapshotFile],
    ) -> dict[str, Any]:
        return {
            "created_at": created_at,
            "owner_email": owner_email,
            "backup_set": backup_prefix,
            "files": [
                {
                    "name": snapshot.name,
                    "original_name": snapshot.original_name,
                    "object_key": snapshot.object_key,
                    "size": snapshot.size,
                    "sha256": snapshot.sha256,
                    "original_size": snapshot.original_size,
                    "original_sha256": snapshot.original_sha256,
                    "compression": snapshot.compression,
                }
                for snapshot in snapshots
            ],
        }

    def _format_success_response(
        self,
        backup_prefix: str,
        manifest_key: str,
        snapshots: Sequence[SnapshotFile],
    ) -> str:
        lines = [
            "EVA 数据备份成功。",
            f"备份集: {backup_prefix}",
            f"清单: {manifest_key}",
            "文件:",
        ]
        for snapshot in snapshots:
            lines.append(
                f"- {snapshot.original_name} -> {snapshot.name}: {snapshot.object_key} "
                f"(compressed_size={snapshot.size}, original_size={snapshot.original_size}, "
                f"sha256={snapshot.sha256}, original_sha256={snapshot.original_sha256})"
            )
        return "\n".join(lines)
