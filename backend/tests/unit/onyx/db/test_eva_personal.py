from __future__ import annotations

import json
from datetime import datetime
from datetime import timedelta
from pathlib import Path

from pytest import MonkeyPatch

from onyx.db.eva_personal import eva_reminder_db_paths
from onyx.db.eva_personal import EvaBlackboardDB
from onyx.db.eva_personal import EvaReminderDB


def test_eva_reminder_db_due_sent_and_expired_flow(tmp_path: Path) -> None:
    reminder_db = EvaReminderDB(db_path=tmp_path / "knowledge.db")
    due_id = reminder_db.add_reminder(
        "due",
        "Criss",
        datetime.now() - timedelta(minutes=5),
    )
    old_id = reminder_db.add_reminder(
        "old",
        "Criss",
        datetime.now() - timedelta(minutes=90),
    )
    future_id = reminder_db.add_reminder(
        "future",
        "Criss",
        datetime.now() + timedelta(minutes=10),
    )

    due_reminders = reminder_db.list_due_pending(
        retry_lookback_minutes=30,
        lookahead_minutes=1,
    )

    assert [reminder["id"] for reminder in due_reminders] == [due_id]

    reminder_db.mark_sent(due_id)
    expired_count = reminder_db.mark_expired_reminders(grace_minutes=60)

    assert expired_count == 1
    assert [reminder["id"] for reminder in reminder_db.list_pending()] == [future_id]
    assert old_id not in [reminder["id"] for reminder in reminder_db.list_pending()]


def test_eva_reminder_db_paths_include_base_and_user_dbs(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    config_path = tmp_path / "eva_tools_config.json"
    config_path.write_text(
        json.dumps(
            {
                "data_dir": str(data_dir),
                "knowledge_db": "knowledge.db",
                "conversation_db": "conversation.db",
                "user_data_root": "users",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVA_TOOLS_CONFIG_PATH", str(config_path))

    user_db_path = data_dir / "users" / "a@example.com" / "knowledge.db"
    EvaReminderDB(db_path=user_db_path)

    assert eva_reminder_db_paths() == [
        data_dir / "knowledge.db",
        user_db_path,
    ]


def test_eva_blackboard_db_initializes_and_saves_boards(tmp_path: Path) -> None:
    blackboard_db = EvaBlackboardDB(db_path=tmp_path / "knowledge.db")

    summary = blackboard_db.list_blackboards_summary()

    assert len(summary) == 10
    assert [board["board_number"] for board in summary] == list(range(1, 11))
    assert not summary[0]["has_content"]

    assert blackboard_db.save_blackboard(
        board_number=3,
        content="# 临时笔记",
        settings={"fontSize": 18},
    )

    board = blackboard_db.get_blackboard(3)

    assert board is not None
    assert board["content"] == "# 临时笔记"
    assert board["settings"] == {"fontSize": 18}
    assert blackboard_db.list_blackboards_summary()[2]["has_content"]
