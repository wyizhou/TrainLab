from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from trainlab.contracts.errors import ErrorCode, failure_envelope, http_status_for_error

PREFIX = "/api/garmin/auth"
ORIGIN = "http://127.0.0.1:8080"
COOKIE = "trainlab_gui"
MAX_BODY = 16384


class AuthHTTPError(Exception):
    def __init__(self, code: ErrorCode, reason: str, status: int | None = None) -> None:
        self.code, self.reason, self.status = code, reason, status


def error_response(code: ErrorCode, reason: str, status: int | None = None) -> JSONResponse:
    return JSONResponse(failure_envelope(code, "认证请求未完成，请检查状态后重试。", {"reason": reason}).to_json(),
                        status_code=status or http_status_for_error(code))


@dataclass(repr=False)
class BrowserSession:
    identity: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    csrf: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    touched: float = 0


class Sessions:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic, ttl: float = 1800) -> None:
        self.clock, self.ttl = clock, ttl
        self.items: dict[str, BrowserSession] = {}

    def sweep(self) -> set[str]:
        expired = {key for key, value in self.items.items() if self.clock() - value.touched >= self.ttl}
        for key in expired:
            del self.items[key]
        return expired

    def get(self, request: Request, *, create: bool = False) -> tuple[BrowserSession, bool]:
        self.sweep()
        cookie = request.cookies.get(COOKIE)
        item = self.items.get(cookie or "")
        replaced = bool(cookie) and item is None
        if item is None:
            if not create:
                raise AuthHTTPError(ErrorCode.SOURCE_CONFLICT, "browser_session_expired", 409)
            if len(self.items) >= 32:
                raise AuthHTTPError(ErrorCode.RESOURCE_LIMIT, "browser_session_limit", 429)
            item = BrowserSession()
            self.items[item.identity] = item
        item.touched = self.clock()
        return item, replaced


def check_source(request: Request) -> None:
    if request.url.query:
        raise AuthHTTPError(ErrorCode.INVALID_ARGUMENT, "query_not_allowed", 400)
    origin = request.headers.get("origin")
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site not in (None, "same-origin", "none"):
        raise AuthHTTPError(ErrorCode.TOOL_NOT_ALLOWED, "request_not_allowed", 403)
    if request.method == "GET":
        allowed = request.headers.get("x-trainlab-gui") == "1" and origin in (None, ORIGIN)
    else:
        allowed = request.method == "POST" and origin == ORIGIN
    if not allowed:
        raise AuthHTTPError(ErrorCode.TOOL_NOT_ALLOWED, "request_not_allowed", 403)


def check_csrf(request: Request, session: BrowserSession) -> None:
    csrf = request.headers.get("x-csrf-token", "")
    if not csrf.isascii() or not secrets.compare_digest(csrf, session.csrf):
        raise AuthHTTPError(ErrorCode.TOOL_NOT_ALLOWED, "request_not_allowed", 403)


class LocalSecurity:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers", [])
        auth = scope["path"].startswith(PREFIX)
        started = False

        async def safe_send(message: Any) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message["headers"] += [(b"referrer-policy", b"no-referrer"), (b"x-frame-options", b"DENY"),
                                       (b"content-security-policy", b"frame-ancestors 'none'")]
                if auth:
                    message["headers"].append((b"cache-control", b"no-store"))
            await send(message)

        if [v for k, v in headers if k.lower() == b"host"] != [b"127.0.0.1:8080"]:
            await error_response(ErrorCode.TOOL_NOT_ALLOWED, "request_not_allowed", 403)(scope, receive, safe_send)
            return
        try:
            await self.app(scope, receive, safe_send)
        except Exception:
            if not auth:
                raise
            if not started:
                await error_response(ErrorCode.EXTERNAL_SERVICE_FAILED, "auth_request_failed", 502)(scope, receive, safe_send)
