"""Stable JSON error envelope contracts for API, tools and jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    ACTIVITY_NOT_FOUND = "ACTIVITY_NOT_FOUND"
    SPORT_NOT_ALLOWED = "SPORT_NOT_ALLOWED"
    SPORT_UNKNOWN = "SPORT_UNKNOWN"
    SCHEMA_UNSUPPORTED = "SCHEMA_UNSUPPORTED"
    DATA_INVALID = "DATA_INVALID"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    CONFIG_UNAVAILABLE = "CONFIG_UNAVAILABLE"
    AUTH_REFRESH_REQUIRED = "AUTH_REFRESH_REQUIRED"
    EXTERNAL_SERVICE_FAILED = "EXTERNAL_SERVICE_FAILED"
    TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
    TIMEOUT = "TIMEOUT"
    POLICY_UNCONFIGURED = "POLICY_UNCONFIGURED"
    REPARSE_CONFLICT = "REPARSE_CONFLICT"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    RUN_BUSY = "RUN_BUSY"


HTTP_STATUS_BY_ERROR: dict[ErrorCode, int] = {
    ErrorCode.INVALID_ARGUMENT: 400,
    ErrorCode.ACTIVITY_NOT_FOUND: 404,
    ErrorCode.SPORT_NOT_ALLOWED: 403,
    ErrorCode.SPORT_UNKNOWN: 409,
    ErrorCode.SCHEMA_UNSUPPORTED: 409,
    ErrorCode.DATA_INVALID: 422,
    ErrorCode.RESOURCE_LIMIT: 413,
    ErrorCode.DATABASE_UNAVAILABLE: 503,
    ErrorCode.CONFIG_UNAVAILABLE: 503,
    ErrorCode.AUTH_REFRESH_REQUIRED: 409,
    ErrorCode.EXTERNAL_SERVICE_FAILED: 502,
    ErrorCode.TOOL_NOT_ALLOWED: 403,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.POLICY_UNCONFIGURED: 501,
    ErrorCode.REPARSE_CONFLICT: 409,
    ErrorCode.SOURCE_CONFLICT: 409,
    ErrorCode.RUN_BUSY: 409,
}


@dataclass(frozen=True)
class ErrorDetail:
    code: ErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": self.message, "details": self.details}


@dataclass(frozen=True)
class ErrorEnvelope:
    ok: bool
    data: dict[str, Any] | list[Any] | str | float | bool | None
    error: ErrorDetail | None

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": None if self.error is None else self.error.to_json(),
        }


def success_envelope(data: dict[str, Any] | list[Any] | str | float | bool | None) -> ErrorEnvelope:
    return ErrorEnvelope(ok=True, data=data, error=None)


def failure_envelope(
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
) -> ErrorEnvelope:
    return ErrorEnvelope(
        ok=False,
        data=None,
        error=ErrorDetail(code=code, message=message, details={} if details is None else details),
    )


def http_status_for_error(code: ErrorCode) -> int:
    return HTTP_STATUS_BY_ERROR[code]
