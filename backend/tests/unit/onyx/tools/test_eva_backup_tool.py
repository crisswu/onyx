from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from onyx.chat.emitter import NullEmitter
from onyx.db.eva_config import AliyunOssBackupConfig
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolCallKickoff
from onyx.tools.tool_implementations.eva_backup import BackupEvaDataToOssTool
from onyx.tools.tool_runner import _safe_run_single_tool


class FakeBucket:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.objects: dict[str, bytes] = {}

    def put_object_from_file(self, key: str, filename: str) -> None:
        self.calls.append(("file", key))
        self.objects[key] = Path(filename).read_bytes()

    def put_object(self, key: str, data: bytes) -> None:
        self.calls.append(("object", key))
        self.objects[key] = data


def _fake_file_uploader(bucket: FakeBucket, key: str, path: Path) -> None:
    bucket.put_object_from_file(key, str(path))


def _create_sqlite_db(path: Path, value: str) -> None:
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items (value TEXT NOT NULL)")
        db.execute("INSERT INTO items (value) VALUES (?)", (value,))


def _write_config(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _create_sqlite_db(data_dir / "knowledge.db", "knowledge")
    _create_sqlite_db(data_dir / "conversation.db", "conversation")

    config_path = tmp_path / "eva_tools_config.json"
    config_path.write_text(
        json.dumps(
            {
                "data_dir": str(data_dir),
                "knowledge_db": "knowledge.db",
                "conversation_db": "conversation.db",
                "owner_email": "30939235@qq.com",
                "aliyun_oss_backup": {
                    "endpoint": "oss-cn-shanghai.aliyuncs.com",
                    "bucket": "criss",
                    "access_key_id": "access-key-id",
                    "access_key_secret": "access-key-secret",
                    "prefix": "eva-backups/30939235@qq.com",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVA_TOOLS_CONFIG_PATH", str(config_path))


def test_backup_tool_uploads_database_snapshots_and_manifest_last(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _write_config(tmp_path, monkeypatch)
    fake_bucket = FakeBucket()

    def bucket_factory(config: AliyunOssBackupConfig) -> FakeBucket:
        assert config.bucket == "criss"
        return fake_bucket

    tool = BackupEvaDataToOssTool(
        tool_id=1,
        emitter=NullEmitter(),
        user_email="30939235@qq.com",
        bucket_factory=bucket_factory,
        file_uploader=_fake_file_uploader,
    )

    response = tool.run(Placement(turn_index=0), None)

    uploaded_keys = [key for _, key in fake_bucket.calls]
    assert len(uploaded_keys) == 3
    assert uploaded_keys[0].endswith("/knowledge.db.gz")
    assert uploaded_keys[1].endswith("/conversation.db.gz")
    assert uploaded_keys[2].endswith("/manifest.json")
    assert uploaded_keys[2].startswith("eva-backups/30939235@qq.com/")

    manifest = json.loads(fake_bucket.objects[uploaded_keys[2]].decode("utf-8"))
    assert manifest["backup_set"].startswith("eva-backups/30939235@qq.com/")
    assert [file["original_name"] for file in manifest["files"]] == [
        "knowledge.db",
        "conversation.db",
    ]
    assert [file["name"] for file in manifest["files"]] == [
        "knowledge.db.gz",
        "conversation.db.gz",
    ]
    assert all(file["compression"] == "gzip" for file in manifest["files"])
    assert all(file["sha256"] for file in manifest["files"])
    assert all(file["original_sha256"] for file in manifest["files"])
    assert "http" not in response.llm_facing_response.lower()
    assert "access-key" not in response.llm_facing_response

    uploaded_db_path = tmp_path / "uploaded.db"
    uploaded_db_path.write_bytes(gzip.decompress(fake_bucket.objects[uploaded_keys[0]]))
    with sqlite3.connect(uploaded_db_path) as db:
        assert db.execute("SELECT value FROM items").fetchone() == ("knowledge",)


def test_backup_tool_runs_through_tool_runner(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _write_config(tmp_path, monkeypatch)
    fake_bucket = FakeBucket()
    tool = BackupEvaDataToOssTool(
        tool_id=1,
        emitter=NullEmitter(),
        user_email="30939235@qq.com",
        bucket_factory=lambda _config: fake_bucket,
        file_uploader=_fake_file_uploader,
    )
    tool_call = ToolCallKickoff(
        tool_call_id="call_1",
        tool_name="backup_eva_data_to_oss",
        tool_args={},
        placement=Placement(turn_index=0),
    )

    response = _safe_run_single_tool(tool, tool_call, override_kwargs=None)

    assert response.llm_facing_response.startswith("EVA 数据备份成功。")
    assert response.tool_call == tool_call
    assert [key for _, key in fake_bucket.calls][0].endswith("/knowledge.db.gz")
    assert [key for _, key in fake_bucket.calls][-1].endswith("/manifest.json")


def test_backup_tool_rejects_non_owner_without_upload(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _write_config(tmp_path, monkeypatch)

    def bucket_factory(_config: AliyunOssBackupConfig) -> FakeBucket:
        raise AssertionError("bucket should not be created for unauthorized users")

    tool = BackupEvaDataToOssTool(
        tool_id=1,
        emitter=NullEmitter(),
        user_email="other@example.com",
        bucket_factory=bucket_factory,
        file_uploader=_fake_file_uploader,
    )

    with pytest.raises(ToolCallException, match="cannot back up EVA data"):
        tool.run(Placement(turn_index=0), None)


def test_backup_tool_authorization_helper_matches_owner(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _write_config(tmp_path, monkeypatch)

    assert BackupEvaDataToOssTool.is_user_authorized("  30939235@qq.com ")
    assert not BackupEvaDataToOssTool.is_user_authorized("other@example.com")
    assert not BackupEvaDataToOssTool.is_user_authorized(None)


def test_backup_tool_uses_distinct_backup_set_keys_for_repeated_runs(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _write_config(tmp_path, monkeypatch)
    fake_bucket = FakeBucket()

    tool = BackupEvaDataToOssTool(
        tool_id=1,
        emitter=NullEmitter(),
        user_email="30939235@qq.com",
        bucket_factory=lambda _config: fake_bucket,
        file_uploader=_fake_file_uploader,
    )

    first_response = tool.run(Placement(turn_index=0), None)
    second_response = tool.run(Placement(turn_index=0), None)

    first_backup_set = first_response.llm_facing_response.splitlines()[1]
    second_backup_set = second_response.llm_facing_response.splitlines()[1]
    assert first_backup_set != second_backup_set


def test_backup_tool_sanitizes_upload_failures(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _write_config(tmp_path, monkeypatch)

    def failing_bucket_factory(_config: AliyunOssBackupConfig) -> FakeBucket:
        raise RuntimeError("secret-looking upstream details")

    tool = BackupEvaDataToOssTool(
        tool_id=1,
        emitter=NullEmitter(),
        user_email="30939235@qq.com",
        bucket_factory=failing_bucket_factory,
        file_uploader=_fake_file_uploader,
    )

    with pytest.raises(ToolCallException) as exc_info:
        tool.run(Placement(turn_index=0), None)

    assert "RuntimeError" in str(exc_info.value)
    assert "secret-looking" not in str(exc_info.value)
    assert "secret-looking" not in exc_info.value.llm_facing_message


def test_backup_tool_is_unavailable_without_oss_config(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _create_sqlite_db(data_dir / "knowledge.db", "knowledge")
    _create_sqlite_db(data_dir / "conversation.db", "conversation")
    config_path = tmp_path / "eva_tools_config.json"
    config_path.write_text(
        json.dumps(
            {
                "data_dir": str(data_dir),
                "knowledge_db": "knowledge.db",
                "conversation_db": "conversation.db",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVA_TOOLS_CONFIG_PATH", str(config_path))

    assert not BackupEvaDataToOssTool.is_available(db_session=None)
