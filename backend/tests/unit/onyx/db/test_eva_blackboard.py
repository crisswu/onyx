from pathlib import Path

from onyx.db.eva_personal import EvaBlackboardDB


def test_eva_blackboard_db_initializes_and_saves_boards(tmp_path: Path) -> None:
    blackboard_db = EvaBlackboardDB(db_path=tmp_path / "knowledge.db")

    summary = blackboard_db.list_blackboards_summary()

    assert len(summary) == 10
    assert [board["board_number"] for board in summary] == list(range(1, 11))
    assert not summary[0]["has_content"]

    assert blackboard_db.save_blackboard(
        board_number=3,
        content="# 临时笔记",
        settings={"fontSize": 18, "autoSave": True},
    )

    board = blackboard_db.get_blackboard(3)

    assert board is not None
    assert board["content"] == "# 临时笔记"
    assert board["settings"] == {"fontSize": 18, "autoSave": True}
    assert blackboard_db.list_blackboards_summary()[2]["has_content"]
