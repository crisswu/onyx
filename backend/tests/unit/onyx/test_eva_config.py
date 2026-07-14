from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from onyx.db.eva_config import get_eva_tools_config


def test_eva_tools_config_parses_aliyun_oss_backup(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config_path = tmp_path / "eva_tools_config.json"
    config_path.write_text(
        json.dumps(
            {
                "data_dir": str(tmp_path / "data"),
                "knowledge_db": "knowledge.db",
                "conversation_db": "conversation.db",
                "owner_email": "  30939235@qq.com ",
                "aliyun_oss_backup": {
                    "endpoint": "oss-cn-shanghai.aliyuncs.com",
                    "bucket": "criss",
                    "access_key_id": "access-key-id",
                    "access_key_secret": "access-key-secret",
                    "prefix": "eva-backups/30939235@qq.com/",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVA_TOOLS_CONFIG_PATH", str(config_path))

    config = get_eva_tools_config()

    assert config.owner_email == "30939235@qq.com"
    assert config.knowledge_db_path == tmp_path / "data" / "knowledge.db"
    assert config.conversation_db_path == tmp_path / "data" / "conversation.db"
    assert config.aliyun_oss_backup is not None
    assert config.aliyun_oss_backup.endpoint == "oss-cn-shanghai.aliyuncs.com"
    assert config.aliyun_oss_backup.bucket == "criss"
    assert config.aliyun_oss_backup.access_key_id == "access-key-id"
    assert config.aliyun_oss_backup.access_key_secret == "access-key-secret"
    assert config.aliyun_oss_backup.prefix == "eva-backups/30939235@qq.com"


def test_eva_tools_config_rejects_partial_aliyun_oss_backup(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config_path = tmp_path / "eva_tools_config.json"
    config_path.write_text(
        json.dumps(
            {
                "data_dir": str(tmp_path / "data"),
                "aliyun_oss_backup": {
                    "endpoint": "oss-cn-shanghai.aliyuncs.com",
                    "bucket": "criss",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVA_TOOLS_CONFIG_PATH", str(config_path))

    with pytest.raises(ValueError, match="missing required fields"):
        get_eva_tools_config()
