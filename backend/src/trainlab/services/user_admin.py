from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from trainlab.core.security import hash_password, normalize_username
from trainlab.db.models.session import LoginSession
from trainlab.db.models.user import User


class UserNotFoundError(Exception):
    """Raised when an administrative command targets an unknown user."""


class UsernameConflictError(Exception):
    """Raised when an administrative rename targets an existing username."""


def _locked_user(db: Session, username: str) -> User:
    user = db.scalar(
        select(User)
        .where(User.username_normalized == normalize_username(username))
        .with_for_update()
    )
    if user is None:
        raise UserNotFoundError
    return user


def _revoke_active_sessions(db: Session, user: User, revoked_at: datetime) -> None:
    db.execute(
        update(LoginSession)
        .where(
            LoginSession.user_id == user.id,
            LoginSession.revoked_at.is_(None),
        )
        .values(revoked_at=revoked_at)
    )


def reset_password_and_revoke_sessions(
    db: Session,
    username: str,
    password: str,
    *,
    now: datetime | None = None,
) -> None:
    """Replace one user's password and revoke their sessions atomically."""

    try:
        user = _locked_user(db, username)
        user.password_hash = hash_password(password)
        _revoke_active_sessions(db, user, now or datetime.now(UTC))
        db.commit()
    except Exception:
        db.rollback()
        raise


def revoke_all_sessions(
    db: Session,
    username: str,
    *,
    now: datetime | None = None,
) -> None:
    """Idempotently revoke every active session belonging to one user."""

    try:
        user = _locked_user(db, username)
        _revoke_active_sessions(db, user, now or datetime.now(UTC))
        db.commit()
    except Exception:
        db.rollback()
        raise


def configure_development_owner(
    db: Session,
    username: str,
    password: str,
    *,
    now: datetime | None = None,
) -> User:
    """Create or atomically reconfigure the sole local-development owner."""

    try:
        normalized = normalize_username(username)
        owner = db.scalar(select(User).where(User.is_owner.is_(True)).with_for_update())
        conflicting = db.scalar(
            select(User).where(User.username_normalized == normalized).with_for_update()
        )
        if conflicting is not None and (owner is None or conflicting.id != owner.id):
            raise UsernameConflictError

        if owner is None:
            owner = User(
                username=username.strip(),
                username_normalized=normalized,
                display_name=username.strip(),
                password_hash=hash_password(password),
                is_owner=True,
                is_active=True,
            )
            db.add(owner)
        else:
            previous_username = owner.username
            owner.username = username.strip()
            owner.username_normalized = normalized
            owner.is_active = True
            if owner.display_name == previous_username:
                owner.display_name = owner.username
            owner.password_hash = hash_password(password)
            _revoke_active_sessions(db, owner, now or datetime.now(UTC))

        db.commit()
        db.refresh(owner)
        return owner
    except Exception:
        db.rollback()
        raise
