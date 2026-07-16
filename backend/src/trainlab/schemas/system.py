from typing import Any

from pydantic import BaseModel


class StatusResponse(BaseModel):
    status: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | list[Any] | None
    requestId: str | None
