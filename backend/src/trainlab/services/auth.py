from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from trainlab.core.config import Settings
from trainlab.core.security import (
    hash_token,
    new_token,
    normalize_username,
    perform_dummy_password_check,
    verify_password,
)
from trainlab.db.models.session import LoginSession
from trainlab.db.models.user import User


@dataclass(frozen=True)
class CreatedSession:
    model: LoginSession
    session_token: str
    csrf_token: str


@dataclass
class AttemptWindow:
    failures: int = 0
    blocked_until: datetime | None = None


class LoginRateLimiter:
    """Process-local throttle keyed by request source and normalized username."""

    def __init__(self) -> None:
        self._attempts: dict[tuple[str, str], AttemptWindow] = {}
        self._lock = Lock()

    def is_blocked(self, source: str, username: str, now: datetime) -> bool:
        key = (source, normalize_username(username))
        with self._lock:
            window = self._attempts.get(key)
            if window is None or window.blocked_until is None:
                return False
            if window.blocked_until <= now:
                self._attempts.pop(key, None)
                return False
            return True

    def record_failure(self, settings: Settings, source: str, username: str, now: datetime) -> None:
        key = (source, normalize_username(username))
        with self._lock:
            window = self._attempts.setdefault(key, AttemptWindow())
            window.failures += 1
            if window.failures >= settings.login_failure_limit:
                window.blocked_until = now + timedelta(minutes=settings.login_lock_minutes)

    def clear(self, source: str, username: str) -> None:
        with self._lock:
            self._attempts.pop((source, normalize_username(username)), None)


def authenticate_user(
    db: Session,
    settings: Settings,
    rate_limiter: LoginRateLimiter,
    source: str,
    username: str,
    password: str,
    *,
    now: datetime | None = None,
) -> User | None:
    current_time = now or datetime.now(UTC)
    if rate_limiter.is_blocked(source, username, current_time):
        return None
    user = db.scalar(select(User).where(User.username_normalized == normalize_username(username)))
    if user is None:
        perform_dummy_password_check(password)
        rate_limiter.record_failure(settings, source, username, current_time)
        return None
    password_valid = verify_password(password, user.password_hash)
    if user.is_active and password_valid:
        rate_limiter.clear(source, username)
        return user
    if not user.is_active or not password_valid:
        rate_limiter.record_failure(settings, source, username, current_time)
        return None
    return None


def create_login_session(
    db: Session,
    settings: Settings,
    user: User,
    *,
    now: datetime | None = None,
) -> CreatedSession:
    current_time = now or datetime.now(UTC)
    session_token = new_token()
    csrf_token = new_token()
    model = LoginSession(
        user_id=user.id,
        token_hash=hash_token(session_token),
        csrf_token_hash=hash_token(csrf_token),
        created_at=current_time,
        expires_at=current_time + timedelta(days=settings.session_ttl_days),
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return CreatedSession(model=model, session_token=session_token, csrf_token=csrf_token)


def delete_expired_sessions(db: Session, *, now: datetime | None = None) -> None:
    current_time = now or datetime.now(UTC)
    db.execute(delete(LoginSession).where(LoginSession.expires_at <= current_time))
    db.commit()
