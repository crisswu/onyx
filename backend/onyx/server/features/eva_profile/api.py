from pathlib import Path

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from pydantic import Field

from onyx.auth.permissions import require_permission
from onyx.db.enums import Permission
from onyx.db.eva_config import get_eva_tools_config_for_user
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

router = APIRouter(prefix="/eva/profile")

EVA_PROFILE_CHAR_LIMIT = 12000


class EvaProfileResponse(BaseModel):
    criss_md: str
    eva_md: str


class EvaProfileUpdateRequest(BaseModel):
    criss_md: str = Field(max_length=EVA_PROFILE_CHAR_LIMIT)
    eva_md: str = Field(max_length=EVA_PROFILE_CHAR_LIMIT)


def _eva_data_dir_for_user(user: User) -> Path:
    config = get_eva_tools_config_for_user(user.email)
    if config.data_dir is None:
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "EVA profile storage is not configured.",
        )
    return config.data_dir


def _read_text_file(path: Path) -> str:
    if not path.exists():
        return ""
    if not path.is_file():
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            f"EVA profile path is not a file: {path.name}",
        )
    return path.read_text(encoding="utf-8")


@router.get("")
def get_eva_profile(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> EvaProfileResponse:
    data_dir = _eva_data_dir_for_user(user)
    return EvaProfileResponse(
        criss_md=_read_text_file(data_dir / "criss.md"),
        eva_md=_read_text_file(data_dir / "eva.md"),
    )


@router.put("")
def update_eva_profile(
    request: EvaProfileUpdateRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> EvaProfileResponse:
    data_dir = _eva_data_dir_for_user(user)
    data_dir.mkdir(parents=True, exist_ok=True)

    criss_path = data_dir / "criss.md"
    eva_path = data_dir / "eva.md"

    criss_path.write_text(request.criss_md, encoding="utf-8")
    eva_path.write_text(request.eva_md, encoding="utf-8")

    return EvaProfileResponse(
        criss_md=request.criss_md,
        eva_md=request.eva_md,
    )
