import pytest
from pydantic import ValidationError

from trainlab.core.config import Settings


def test_production_requires_secure_cookie() -> None:
    with pytest.raises(ValidationError, match="SESSION_COOKIE_SECURE"):
        Settings(
            environment="production",
            public_origin="https://trainlab.example",
            trusted_origins=["https://trainlab.example"],
            session_cookie_secure=False,
        )


def test_public_origin_must_be_trusted() -> None:
    with pytest.raises(ValidationError, match="public_origin"):
        Settings(public_origin="http://localhost:9000", trusted_origins=["http://localhost:8000"])


def test_csrf_cookie_name_is_a_stable_frontend_contract() -> None:
    with pytest.raises(ValidationError):
        Settings(csrf_cookie_name="renamed_csrf")  # type: ignore[arg-type]


def test_login_throttle_settings_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="throttle"):
        Settings(login_failure_limit=0)
