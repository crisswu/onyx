from __future__ import annotations

import datetime
import secrets
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import FeishuUserBinding
from onyx.db.models import User

FEISHU_BIND_CODE_TTL_MINUTES = 10


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _is_expired(value: datetime.datetime) -> bool:
    if value.tzinfo is None:
        return value <= datetime.datetime.now()
    return value <= datetime.datetime.now(value.tzinfo)


def _generate_bind_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def get_feishu_binding_by_user_id(
    db_session: Session, user_id: UUID
) -> FeishuUserBinding | None:
    return db_session.scalar(
        select(FeishuUserBinding).where(FeishuUserBinding.user_id == user_id)
    )


def get_feishu_binding_by_open_id(
    db_session: Session, open_id: str
) -> FeishuUserBinding | None:
    return db_session.scalar(
        select(FeishuUserBinding).where(FeishuUserBinding.open_id == open_id)
    )


def get_feishu_user_by_open_id(db_session: Session, open_id: str) -> User | None:
    return db_session.scalar(
        select(User)
        .join(FeishuUserBinding, FeishuUserBinding.user_id == User.id)
        .where(FeishuUserBinding.open_id == open_id)
    )


def create_or_refresh_feishu_bind_code(
    db_session: Session, user_id: UUID
) -> FeishuUserBinding:
    binding = get_feishu_binding_by_user_id(db_session, user_id)
    if binding is None:
        binding = FeishuUserBinding(user_id=user_id)
        db_session.add(binding)

    existing_code = ""
    for _ in range(10):
        bind_code = _generate_bind_code()
        existing = db_session.scalar(
            select(FeishuUserBinding).where(FeishuUserBinding.bind_code == bind_code)
        )
        if existing is None or existing.user_id == user_id:
            existing_code = bind_code
            break

    if not existing_code:
        raise RuntimeError("Unable to generate a unique Feishu bind code")

    binding.bind_code = existing_code
    binding.bind_code_expires_at = _utc_now() + datetime.timedelta(
        minutes=FEISHU_BIND_CODE_TTL_MINUTES
    )
    db_session.commit()
    db_session.refresh(binding)
    return binding


def bind_feishu_open_id_with_code(
    db_session: Session,
    *,
    bind_code: str,
    open_id: str,
    union_id: str | None,
    tenant_key: str | None,
) -> FeishuUserBinding | None:
    binding = db_session.scalar(
        select(FeishuUserBinding).where(FeishuUserBinding.bind_code == bind_code)
    )
    if binding is None or binding.bind_code_expires_at is None:
        return None

    if _is_expired(binding.bind_code_expires_at):
        binding.bind_code = None
        binding.bind_code_expires_at = None
        db_session.commit()
        return None

    previous_binding = get_feishu_binding_by_open_id(db_session, open_id)
    if previous_binding is not None and previous_binding.user_id != binding.user_id:
        previous_binding.open_id = None
        previous_binding.union_id = None
        previous_binding.tenant_key = None
        db_session.flush()

    binding.open_id = open_id
    binding.union_id = union_id
    binding.tenant_key = tenant_key
    binding.bind_code = None
    binding.bind_code_expires_at = None
    db_session.commit()
    db_session.refresh(binding)
    return binding


def delete_feishu_binding_for_user(db_session: Session, user_id: UUID) -> None:
    binding = get_feishu_binding_by_user_id(db_session, user_id)
    if binding is None:
        return
    db_session.delete(binding)
    db_session.commit()
