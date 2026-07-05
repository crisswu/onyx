import json
import os
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from fastapi import APIRouter
from fastapi import Depends
from fastapi.responses import StreamingResponse

from onyx.auth.permissions import require_permission
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.pi.models import PiAbortResponse
from onyx.server.features.pi.models import PiMessageRequest
from onyx.server.features.pi.models import PiSessionCreateRequest
from onyx.server.features.pi.models import PiSessionCreateResponse


PI_BRIDGE_URL = os.environ.get("PI_BRIDGE_URL", "http://pi_bridge:8787")
PI_ALLOWED_EMAILS = {
    email.strip().lower()
    for email in os.environ.get("PI_ALLOWED_EMAILS", "30939235@qq.com").split(",")
    if email.strip()
}

router = APIRouter(
    prefix="/pi",
    dependencies=[Depends(require_permission(Permission.BASIC_ACCESS))],
)


def _bridge_url(path: str) -> str:
    return f"{PI_BRIDGE_URL.rstrip('/')}/{path.lstrip('/')}"


def _require_pi_access(user: User) -> None:
    if user.email.lower() in PI_ALLOWED_EMAILS:
        return

    raise OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        "Pi is not enabled for this account",
    )


def _raise_for_bridge_error(response: httpx.Response) -> None:
    if response.status_code < 400:
        return

    detail = response.text
    try:
        payload = response.json()
        if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
            detail = payload["detail"]
    except ValueError:
        pass

    raise OnyxError(
        OnyxErrorCode.BAD_GATEWAY,
        detail or "Pi bridge request failed",
        status_code_override=response.status_code,
    )


@router.post("/sessions")
async def create_pi_session(
    _: PiSessionCreateRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> PiSessionCreateResponse:
    _require_pi_access(user)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            _bridge_url("/sessions"),
            json={"userId": str(user.id)},
        )

    _raise_for_bridge_error(response)
    data = response.json()
    return PiSessionCreateResponse(
        session_id=data["sessionId"],
        workspace=data["workspace"],
        provider=data["provider"],
        model=data["model"],
    )


@router.post("/sessions/{session_id}/messages")
async def stream_pi_message(
    session_id: str,
    request: PiMessageRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> StreamingResponse:
    _require_pi_access(user)

    async def event_stream() -> AsyncGenerator[str, None]:
        async with httpx.AsyncClient(timeout=None) as client:
            try:
                async with client.stream(
                    "POST",
                    _bridge_url(f"/sessions/{session_id}/messages"),
                    json={"message": request.message},
                    headers={"Accept": "text/event-stream"},
                ) as response:
                    if response.status_code >= 400:
                        error_text = await response.aread()
                        yield _format_sse(
                            {
                                "type": "bridge_error",
                                "message": error_text.decode("utf-8", "replace"),
                            }
                        )
                        return

                    async for chunk in response.aiter_text():
                        yield chunk
            except httpx.HTTPError as error:
                yield _format_sse(
                    {
                        "type": "bridge_error",
                        "message": str(error),
                    }
                )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions/{session_id}/abort")
async def abort_pi_session(
    session_id: str,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> PiAbortResponse:
    _require_pi_access(user)

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(_bridge_url(f"/sessions/{session_id}/abort"))

    _raise_for_bridge_error(response)
    data = response.json()
    return PiAbortResponse(success=bool(data.get("success")))


@router.delete("/sessions/{session_id}")
async def delete_pi_session(
    session_id: str,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> PiAbortResponse:
    _require_pi_access(user)

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.delete(_bridge_url(f"/sessions/{session_id}"))

    _raise_for_bridge_error(response)
    data = response.json()
    return PiAbortResponse(success=bool(data.get("success")))


def _format_sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
