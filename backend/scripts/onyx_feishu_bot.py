from __future__ import annotations

import json
import os

import lark_oapi as lark

from onyx.db.engine.sql_engine import SqlEngine
from onyx.server.eva_feishu.api import enqueue_feishu_payload
from onyx.utils.logger import setup_logger
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


def _enabled() -> bool:
    return os.environ.get("FEISHU_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _marshal_event_payload(data: object) -> dict[str, object]:
    raw = lark.JSON.marshal(data)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    parsed = json.loads(str(raw))
    if not isinstance(parsed, dict):
        raise RuntimeError("Unexpected Feishu event payload")
    return parsed


def _handle_message(data: object) -> None:
    try:
        payload = _marshal_event_payload(data)
        result = enqueue_feishu_payload(payload)
        logger.info("Feishu long-connection event handled: %s", result)
    except Exception:
        logger.exception("Failed to handle Feishu long-connection event")


def main() -> None:
    if not _enabled():
        logger.warning("FEISHU_ENABLED is false; Feishu bot will not start.")
        return

    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise RuntimeError("Missing FEISHU_APP_ID or FEISHU_APP_SECRET")

    CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)
    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_handle_message)
        .build()
    )

    logger.info("Starting Onyx Feishu long-connection bot.")
    client = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    client.start()


if __name__ == "__main__":
    main()
