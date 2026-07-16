from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response

from trainlab.api.dependencies import CsrfSession, CurrentSession, Database, RequestSettings
from trainlab.core.errors import ApiError
from trainlab.schemas.auth import LoginRequest, LogoutResponse, SessionResponse, UserResponse
from trainlab.schemas.system import ErrorResponse
from trainlab.services.auth import authenticate_user, create_login_session

router = APIRouter(prefix="/auth", tags=["auth"])
ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


@router.post("/login", response_model=SessionResponse, responses=ERRORS)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Database,
    settings: RequestSettings,
) -> SessionResponse:
    source = request.client.host if request.client is not None else "unknown"
    user = authenticate_user(
        db,
        settings,
        request.app.state.login_rate_limiter,
        source,
        payload.username,
        payload.password,
    )
    if user is None:
        raise ApiError(401, "invalid_credentials", "账号或密码错误")

    created = create_login_session(db, settings, user)
    max_age = settings.session_ttl_days * 24 * 60 * 60
    response.set_cookie(
        settings.session_cookie_name,
        created.session_token,
        max_age=max_age,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        created.csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return SessionResponse(
        user=UserResponse.model_validate(user),
        expires_at=created.model.expires_at,
    )


@router.get("/session", response_model=SessionResponse, responses=ERRORS)
def session(current: CurrentSession) -> SessionResponse:
    return SessionResponse(
        user=UserResponse.model_validate(current.user),
        expires_at=current.session.expires_at,
    )


@router.post("/logout", response_model=LogoutResponse, responses=ERRORS)
def logout(
    response: Response,
    current: CsrfSession,
    db: Database,
    settings: RequestSettings,
) -> LogoutResponse:
    current.session.revoked_at = datetime.now(UTC)
    db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return LogoutResponse()
