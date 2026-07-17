import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from trainlab.core.config import Settings
from trainlab.core.errors import ApiError, error_response

logger = logging.getLogger("trainlab.request")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _is_private_activity_api(path: str) -> bool:
    return path in {
        "/api/v1/activities",
        "/api/v1/imports",
        "/api/v1/storage/usage",
    } or path.startswith(("/api/v1/activities/", "/api/v1/imports/"))


async def request_context_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = request.headers.get("X-Request-ID")
    try:
        request.state.request_id = str(uuid.UUID(request_id)) if request_id else str(uuid.uuid4())
    except ValueError:
        request.state.request_id = str(uuid.uuid4())

    started = time.perf_counter()
    try:
        validate_origin(request, request.app.state.settings)
        response = await call_next(request)
    except ApiError as exc:
        response = error_response(
            request,
            exc.status_code,
            exc.code,
            exc.message,
            exc.details,
        )
    except Exception as exc:
        logger.error(
            "unhandled application error",
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={
                "request_id": request.state.request_id,
                "method": request.method,
                "path": request.url.path,
            },
        )
        response = error_response(request, 500, "internal_error", "服务暂时不可用")
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if _is_private_activity_api(request.url.path):
        response.headers["Cache-Control"] = "private, no-store"
    logger.info(
        "request completed",
        extra={
            "request_id": request.state.request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


def validate_origin(request: Request, settings: Settings) -> None:
    if request.method in SAFE_METHODS or not request.url.path.startswith("/api/"):
        return
    origin = request.headers.get("Origin")
    if origin is None or origin.rstrip("/") not in settings.trusted_origins:
        raise ApiError(403, "invalid_origin", "请求来源无效")
