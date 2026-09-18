from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from trainlab.contracts.errors import ErrorCode, http_status_for_error, success_envelope
from trainlab.local_web.auth_runtime import AuthRuntime
from trainlab.local_web.auth_security import (
    COOKIE,
    MAX_BODY,
    PREFIX,
    AuthHTTPError,
    check_csrf,
    check_source,
    error_response,
)


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("duplicate_fields")
    return dict(pairs)


async def read_body(request: Request, action: str) -> dict[str, str]:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise AuthHTTPError(ErrorCode.INVALID_ARGUMENT, "json_required", 400)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BODY:
            raise AuthHTTPError(ErrorCode.RESOURCE_LIMIT, "request_too_large", 413)
        raw.extend(chunk)
    try:
        body = json.loads(raw, object_pairs_hook=_unique_fields)
    except (ValueError, UnicodeError):
        raise AuthHTTPError(ErrorCode.INVALID_ARGUMENT, "invalid_body", 400) from None
    fields = {"login": {"region": 3, "username": 320, "password": 1024},
              "mfa": {"attempt_id": 128, "code": 128}, "cancel": {"attempt_id": 128},
              "maintenance/retry": {}}[action]
    if not isinstance(body, dict) or set(body) != set(fields):
        raise AuthHTTPError(ErrorCode.INVALID_ARGUMENT, "invalid_body", 400)
    for key, maximum in fields.items():
        if type(body[key]) is not str or not body[key] or len(body[key]) > maximum:
            raise AuthHTTPError(ErrorCode.INVALID_ARGUMENT, "invalid_body", 400)
        if key != "password" and not body[key].strip():
            raise AuthHTTPError(ErrorCode.INVALID_ARGUMENT, "invalid_body", 400)
    if action == "login" and body["region"] not in ("com", "cn"):
        raise AuthHTTPError(ErrorCode.INVALID_ARGUMENT, "invalid_region", 400)
    return body


def register_auth_routes(app: FastAPI) -> None:
    async def dispatch(request: Request) -> JSONResponse:
        try:
            check_source(request)
            runtime: AuthRuntime | None = getattr(request.app.state, "auth", None)
            if runtime is None or runtime.stopping:
                raise AuthHTTPError(ErrorCode.RUN_BUSY, "service_not_running", 409)
            action = request.url.path.removeprefix(PREFIX + "/")
            session, replaced = runtime.sessions.get(request, create=action == "session")
            if request.method == "GET":
                if action == "session":
                    response = JSONResponse(success_envelope({"csrf": session.csrf, "idle_timeout_seconds": runtime.sessions.ttl,
                                                             "session_replaced": replaced}).to_json())
                    response.set_cookie(COOKIE, session.identity, httponly=True, samesite="strict", path=PREFIX)
                    return response
                return JSONResponse(success_envelope(await runtime.status(session.identity)).to_json())
            check_csrf(request, session)
            body = await read_body(request, action)
            result = await runtime.action(session.identity, action, body)
            status = 200
            if result.error is not None:
                status = http_status_for_error(result.error.code)
                if result.error.details.get("reason") == "server_rate_limited":
                    status = 429
            return JSONResponse(result.to_json(), status_code=status)
        except AuthHTTPError as exc:
            return error_response(exc.code, exc.reason, exc.status)
        except Exception:  # noqa: BLE001
            return error_response(ErrorCode.EXTERNAL_SERVICE_FAILED, "auth_request_failed", 502)

    for method, action in (("GET", "session"), ("GET", "status"), ("POST", "login"),
                           ("POST", "mfa"), ("POST", "cancel"), ("POST", "maintenance/retry")):
        app.add_api_route(PREFIX + "/" + action, dispatch, methods=[method], response_model=None)
