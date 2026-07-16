from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from trainlab.core.config import Settings
from trainlab.core.errors import ApiError
from trainlab.core.security import hash_token
from trainlab.db.database import get_db
from trainlab.db.models.session import LoginSession
from trainlab.db.models.user import User

Database = Annotated[Session, Depends(get_db)]


def get_request_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


RequestSettings = Annotated[Settings, Depends(get_request_settings)]


@dataclass(frozen=True)
class AuthenticatedSession:
    session: LoginSession
    user: User


def get_authenticated_session(
    request: Request,
    db: Database,
    settings: RequestSettings,
) -> AuthenticatedSession:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise ApiError(401, "authentication_required", "需要登录")
    result = db.execute(
        select(LoginSession, User)
        .join(User, User.id == LoginSession.user_id)
        .where(LoginSession.token_hash == hash_token(token))
    ).one_or_none()
    if result is None:
        raise ApiError(401, "invalid_session", "会话无效")
    login_session, user = result
    now = datetime.now(UTC)
    if (
        login_session.revoked_at is not None
        or login_session.expires_at <= now
        or not user.is_active
    ):
        raise ApiError(401, "invalid_session", "会话已过期或已失效")
    return AuthenticatedSession(session=login_session, user=user)


CurrentSession = Annotated[AuthenticatedSession, Depends(get_authenticated_session)]


def require_csrf(
    request: Request,
    current: CurrentSession,
    settings: RequestSettings,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    csrf_cookie: Annotated[str | None, Cookie(alias="trainlab_csrf")] = None,
) -> AuthenticatedSession:
    # Cookie name is configurable, so read it directly instead of relying on the
    # static alias used only to keep the parameter visible in generated docs.
    csrf_cookie = request.cookies.get(settings.csrf_cookie_name, csrf_cookie)
    if (
        csrf_header is None
        or csrf_cookie is None
        or csrf_header != csrf_cookie
        or hash_token(csrf_header) != current.session.csrf_token_hash
    ):
        raise ApiError(403, "invalid_csrf", "CSRF 令牌无效")
    return current


CsrfSession = Annotated[AuthenticatedSession, Depends(require_csrf)]
