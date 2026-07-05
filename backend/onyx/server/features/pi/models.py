from pydantic import BaseModel


class PiSessionCreateRequest(BaseModel):
    pass


class PiSessionCreateResponse(BaseModel):
    session_id: str
    workspace: str
    provider: str
    model: str


class PiMessageRequest(BaseModel):
    message: str


class PiAbortResponse(BaseModel):
    success: bool

