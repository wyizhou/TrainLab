import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from trainlab.cli import create_owner
from trainlab.db.models.user import User


def test_create_owner_validates_lengths_without_touching_database() -> None:
    assert create_owner("short", None, "correct-password") == 2
    assert create_owner("owner-user", None, "short") == 2


def test_create_owner_is_idempotent_but_refuses_a_second_owner(engine) -> None:  # type: ignore[no-untyped-def]
    assert create_owner("owner-user", "Owner", "correct-password") == 0
    assert create_owner("owner-user", "Owner", "correct-password") == 0
    assert create_owner("another-owner", None, "correct-password") == 3
    with Session(engine) as db:
        owners = db.scalars(select(User).where(User.is_owner.is_(True))).all()
    assert len(owners) == 1
    assert owners[0].display_name == "Owner"


def test_create_owner_reports_database_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(
        "TRAINLAB_DATABASE_URL",
        "postgresql+psycopg://trainlab:trainlab@127.0.0.1:1/unavailable_test",
    )
    from trainlab.core.config import get_settings

    get_settings.cache_clear()
    try:
        assert create_owner("owner-user", None, "correct-password") == 4
    finally:
        monkeypatch.delenv("TRAINLAB_DATABASE_URL")
        get_settings.cache_clear()
        # Keep the imported module honest: no password-bearing automation variable leaks.
        assert not any(key.startswith("TRAINLAB_OWNER_PASSWORD") for key in os.environ)
