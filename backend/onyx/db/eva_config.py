from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_EVA_TOOLS_CONFIG_PATH = Path("/app/config/eva_tools_config.json")
DEFAULT_EVA_OWNER_EMAIL = "30939235@qq.com"
DEFAULT_EVA_USER_DATA_SUBDIR = "users"


@dataclass(frozen=True)
class AliyunOssBackupConfig:
    endpoint: str
    bucket: str
    access_key_id: str
    access_key_secret: str
    prefix: str


@dataclass(frozen=True)
class EvaToolsConfig:
    data_dir: Path | None = None
    knowledge_db_path: Path | None = None
    conversation_db_path: Path | None = None
    owner_email: str = DEFAULT_EVA_OWNER_EMAIL
    user_data_root: Path | None = None
    aliyun_oss_backup: AliyunOssBackupConfig | None = None


def _config_path() -> Path:
    configured = os.environ.get("EVA_TOOLS_CONFIG_PATH")
    if configured:
        return Path(configured)
    return DEFAULT_EVA_TOOLS_CONFIG_PATH


def _resolve_path(raw_value: Any, base_dir: Path | None = None) -> Path | None:
    if not raw_value:
        return None

    path = Path(str(raw_value))
    if path.is_absolute():
        return path
    if base_dir is not None:
        return base_dir / path
    return path


def _normalize_user_key(user_key: str | None) -> str:
    normalized = (user_key or "").strip().lower()
    return normalized or "anonymous"


def _optional_str(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    return value or None


def _parse_aliyun_oss_backup_config(raw_value: Any) -> AliyunOssBackupConfig | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, dict):
        raise ValueError("aliyun_oss_backup config must be a JSON object")

    endpoint = _optional_str(raw_value.get("endpoint"))
    bucket = _optional_str(raw_value.get("bucket"))
    access_key_id = _optional_str(raw_value.get("access_key_id"))
    access_key_secret = _optional_str(raw_value.get("access_key_secret"))
    prefix = _optional_str(raw_value.get("prefix"))

    if not any([endpoint, bucket, access_key_id, access_key_secret, prefix]):
        return None

    missing_fields = [
        field
        for field, value in [
            ("endpoint", endpoint),
            ("bucket", bucket),
            ("access_key_id", access_key_id),
            ("access_key_secret", access_key_secret),
            ("prefix", prefix),
        ]
        if value is None
    ]
    if missing_fields:
        raise ValueError(
            "aliyun_oss_backup config is missing required fields: "
            + ", ".join(missing_fields)
        )

    return AliyunOssBackupConfig(
        endpoint=endpoint,
        bucket=bucket,
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        prefix=prefix.rstrip("/"),
    )


def _safe_user_dir_name(user_key: str | None) -> str:
    normalized = _normalize_user_key(user_key)
    safe = re.sub(r"[^a-z0-9_.@-]+", "_", normalized)
    return safe.strip("._") or "anonymous"


def get_eva_tools_config() -> EvaToolsConfig:
    path = _config_path()
    if not path.exists():
        return EvaToolsConfig()

    with path.open("r", encoding="utf-8") as file:
        raw_config = json.load(file)

    if not isinstance(raw_config, dict):
        raise ValueError(f"EVA tools config must be a JSON object: {path}")

    data_dir = _resolve_path(raw_config.get("data_dir"))
    knowledge_db_path = _resolve_path(
        raw_config.get("knowledge_db_path") or raw_config.get("knowledge_db"),
        data_dir,
    )
    conversation_db_path = _resolve_path(
        raw_config.get("conversation_db_path") or raw_config.get("conversation_db"),
        data_dir,
    )

    owner_email = str(raw_config.get("owner_email") or DEFAULT_EVA_OWNER_EMAIL).strip().lower()
    user_data_root = _resolve_path(
        raw_config.get("user_data_root") or raw_config.get("user_data_dir"),
        data_dir,
    )
    aliyun_oss_backup = _parse_aliyun_oss_backup_config(
        raw_config.get("aliyun_oss_backup")
    )

    if data_dir is not None:
        if knowledge_db_path is None:
            knowledge_db_path = data_dir / "knowledge.db"
        if conversation_db_path is None:
            conversation_db_path = data_dir / "conversation.db"
        if user_data_root is None:
            user_data_root = data_dir / DEFAULT_EVA_USER_DATA_SUBDIR

    return EvaToolsConfig(
        data_dir=data_dir,
        knowledge_db_path=knowledge_db_path,
        conversation_db_path=conversation_db_path,
        owner_email=owner_email,
        user_data_root=user_data_root,
        aliyun_oss_backup=aliyun_oss_backup,
    )


def get_eva_tools_config_for_user(user_key: str | None) -> EvaToolsConfig:
    config = get_eva_tools_config()
    normalized_user = _normalize_user_key(user_key)

    if not config.data_dir or normalized_user == config.owner_email:
        return config

    user_data_root = (
        config.user_data_root
        or config.data_dir / DEFAULT_EVA_USER_DATA_SUBDIR
    )
    user_data_dir = user_data_root / _safe_user_dir_name(normalized_user)
    return EvaToolsConfig(
        data_dir=user_data_dir,
        knowledge_db_path=user_data_dir / "knowledge.db",
        conversation_db_path=user_data_dir / "conversation.db",
        owner_email=config.owner_email,
        user_data_root=config.user_data_root,
        aliyun_oss_backup=config.aliyun_oss_backup,
    )


def get_eva_backup_config() -> EvaToolsConfig:
    """Return the owner-scoped EVA config used for backup operations."""
    return get_eva_tools_config()


def get_eva_knowledge_db_path() -> Path | None:
    return get_eva_tools_config().knowledge_db_path


def get_eva_conversation_db_path() -> Path | None:
    return get_eva_tools_config().conversation_db_path


def get_eva_knowledge_db_path_for_user(user_key: str | None) -> Path | None:
    return get_eva_tools_config_for_user(user_key).knowledge_db_path


def get_eva_conversation_db_path_for_user(user_key: str | None) -> Path | None:
    return get_eva_tools_config_for_user(user_key).conversation_db_path
