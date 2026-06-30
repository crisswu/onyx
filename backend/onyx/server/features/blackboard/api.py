import os
from typing import Any

from fastapi import APIRouter
from fastapi import Depends

from onyx.auth.permissions import require_permission
from onyx.db.enums import Permission
from onyx.db.eva_personal import EvaBlackboardDB
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.blackboard.models import BlackboardEntry
from onyx.server.features.blackboard.models import BlackboardSaveRequest
from onyx.server.features.blackboard.models import BlackboardSaveResponse
from onyx.server.features.blackboard.models import BlackboardSummary


BLACKBOARD_ALLOWED_EMAILS = {
    email.strip().lower()
    for email in os.environ.get("BLACKBOARD_ALLOWED_EMAILS", "30939235@qq.com").split(
        ","
    )
    if email.strip()
}

router = APIRouter(
    prefix="/blackboard",
    dependencies=[Depends(require_permission(Permission.BASIC_ACCESS))],
)


def _require_blackboard_access(user: User) -> None:
    if user.email.lower() in BLACKBOARD_ALLOWED_EMAILS:
        return

    raise OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        "Blackboard is not enabled for this account",
    )


def _validate_board_number(board_number: int) -> None:
    if 1 <= board_number <= EvaBlackboardDB.BOARD_COUNT:
        return

    raise OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        "黑板编号必须在 1-10 之间",
    )


def _entry_from_data(data: dict[str, Any]) -> BlackboardEntry:
    settings = data.get("settings")
    return BlackboardEntry(
        id=int(data["id"]),
        board_number=int(data["board_number"]),
        content=str(data.get("content") or ""),
        settings=settings if isinstance(settings, dict) else {},
        created_at=str(data["created_at"]),
        updated_at=str(data["updated_at"]),
    )


@router.get("/all")
def list_blackboards(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> list[BlackboardSummary]:
    _require_blackboard_access(user)
    return [
        BlackboardSummary(**summary)
        for summary in EvaBlackboardDB().list_blackboards_summary()
    ]


@router.get("/{board_number}")
def get_blackboard(
    board_number: int,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> BlackboardEntry:
    _require_blackboard_access(user)
    _validate_board_number(board_number)

    data = EvaBlackboardDB().get_blackboard(board_number)
    if data is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, f"黑板 {board_number} 不存在")
    return _entry_from_data(data)


@router.post("/{board_number}")
def save_blackboard(
    board_number: int,
    request: BlackboardSaveRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> BlackboardSaveResponse:
    _require_blackboard_access(user)
    _validate_board_number(board_number)

    db = EvaBlackboardDB()
    if not db.save_blackboard(
        board_number=board_number,
        content=request.content,
        settings=request.settings,
    ):
        raise OnyxError(OnyxErrorCode.INTERNAL_ERROR, "保存失败")

    data = db.get_blackboard(board_number)
    updated_at = str(data["updated_at"]) if data else ""
    return BlackboardSaveResponse(
        success=True,
        message="保存成功",
        updated_at=updated_at,
    )
