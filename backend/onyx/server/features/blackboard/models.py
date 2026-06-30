from typing import Any

from pydantic import BaseModel
from pydantic import Field


BLACKBOARD_CONTENT_CHAR_LIMIT = 200_000


class BlackboardEntry(BaseModel):
    id: int
    board_number: int
    content: str
    settings: dict[str, Any]
    created_at: str
    updated_at: str


class BlackboardSummary(BaseModel):
    board_number: int
    has_content: bool
    preview: str
    updated_at: str


class BlackboardSaveRequest(BaseModel):
    content: str = Field(max_length=BLACKBOARD_CONTENT_CHAR_LIMIT)
    settings: dict[str, Any] | None = None


class BlackboardSaveResponse(BaseModel):
    success: bool
    message: str
    updated_at: str
