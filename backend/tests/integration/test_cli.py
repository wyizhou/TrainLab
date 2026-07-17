import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from conftest import create_test_user
from trainlab.cli import (
    create_owner,
    create_user,
    main,
    reset_password,
    revoke_sessions,
)
from trainlab.core.security import verify_password
from trainlab.db.models.session import LoginSession
from trainlab.db.models.user import User
from trainlab.main import create_app


def _login(
    client: TestClient,
    headers: dict[str, str],
    *,
    username: str = "owner-user",
    password: str = "correct-password",
):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers=headers,
    )


def _run_cli(monkeypatch, *args: str) -> int:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "argv", ["trainlab", *args])
    with pytest.raises(SystemExit) as raised:
        main()
    return int(raised.value.code)


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


def test_create_user_is_idempotent_and_cannot_replace_the_owner(engine) -> None:  # type: ignore[no-untyped-def]
    assert create_owner("owner-user", "Owner", "correct-password") == 0
    assert create_user("peer-user", "Peer", "correct-password") == 0
    assert create_user("peer-user", "Peer", "correct-password") == 0
    assert create_user("owner-user", "Owner", "correct-password") == 3
    with Session(engine) as db:
        peer = db.scalar(select(User).where(User.username_normalized == "peer-user"))
    assert peer is not None
    assert peer.display_name == "Peer"
    assert peer.is_owner is False


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


def test_reset_password_from_environment_revokes_two_sessions_and_changes_login(
    settings,
    engine,
    user,
    origin_headers: dict[str, str],
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    secret = "new-correct-password"
    variable = "TRAINLAB_TEST_RESET_PASSWORD"
    monkeypatch.setenv(variable, secret)
    with (
        TestClient(create_app(settings), client=("old-session-one", 50001)) as first,
        TestClient(create_app(settings), client=("old-session-two", 50002)) as second,
    ):
        assert _login(first, origin_headers).status_code == 200
        assert _login(second, origin_headers).status_code == 200
        session_secrets = [
            first.cookies.get("trainlab_session"),
            first.cookies.get("trainlab_csrf"),
            second.cookies.get("trainlab_session"),
            second.cookies.get("trainlab_csrf"),
        ]

        assert (
            _run_cli(
                monkeypatch,
                "reset-password",
                "--username",
                "owner-user",
                "--password-env",
                variable,
            )
            == 0
        )
        assert first.get("/api/v1/auth/session").status_code == 401
        assert second.get("/api/v1/auth/session").status_code == 401

    with TestClient(create_app(settings), client=("new-login", 50003)) as login_client:
        assert _login(login_client, origin_headers).status_code == 401
        assert _login(login_client, origin_headers, password=secret).status_code == 200

    captured = capsys.readouterr()
    with Session(engine) as db:
        stored = db.scalar(select(User.password_hash).where(User.id == user.id))
    assert stored is not None
    assert secret not in captured.out
    assert secret not in captured.err
    assert stored not in captured.out
    assert stored not in captured.err
    for session_secret in session_secrets:
        assert session_secret is not None
        assert session_secret not in captured.out
        assert session_secret not in captured.err
    assert stored.startswith("$argon2")


def test_reset_password_interactive_input_is_hidden_and_must_match(
    user,
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    prompts: list[str] = []
    answers = iter(["first-secret", "different-secret"])

    def fake_getpass(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("trainlab.cli.getpass.getpass", fake_getpass)
    assert _run_cli(monkeypatch, "reset-password", "--username", user.username) == 2
    captured = capsys.readouterr()
    assert prompts == ["密码：", "确认密码："]
    assert "first-secret" not in captured.out + captured.err
    assert "different-secret" not in captured.out + captured.err


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("reset-password", "--username", "unknown-user", "--password-env", "MISSING"), 2),
        (("reset-password", "--username", "unknown-user"), 3),
        (("reset-password", "--username", "short", "--password-env", "PASSWORD"), 2),
        (("revoke-sessions", "--username", "short"), 2),
        (("revoke-sessions", "--username", "unknown-user"), 3),
    ],
)
def test_admin_cli_fixed_input_and_unknown_user_exit_codes(
    args: tuple[str, ...],
    expected: int,
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("MISSING", raising=False)
    monkeypatch.setenv("PASSWORD", "correct-password")
    if args == ("reset-password", "--username", "unknown-user"):
        answers = iter(["correct-password", "correct-password"])
        monkeypatch.setattr("trainlab.cli.getpass.getpass", lambda _prompt: next(answers))
    assert _run_cli(monkeypatch, *args) == expected
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "correct-password" not in output


def test_reset_password_rejects_short_password_without_changing_hash(
    engine,
    user,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    assert reset_password(user.username, "short") == 2
    captured = capsys.readouterr()
    assert "short" not in captured.out + captured.err
    with Session(engine) as db:
        stored = db.scalar(select(User.password_hash).where(User.id == user.id))
    assert stored is not None
    assert verify_password("correct-password", stored)


def test_reset_password_rolls_back_hash_when_session_revocation_fails(
    engine,
    user,
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    def fail_revocation(*_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
        raise SQLAlchemyError("database operation failed")

    monkeypatch.setattr("trainlab.services.user_admin._revoke_active_sessions", fail_revocation)
    assert reset_password(user.username, "new-correct-password") == 4
    captured = capsys.readouterr()
    assert "new-correct-password" not in captured.out + captured.err
    with Session(engine) as db:
        stored = db.scalar(select(User.password_hash).where(User.id == user.id))
    assert stored is not None
    assert verify_password("correct-password", stored)
    assert not verify_password("new-correct-password", stored)


def test_reset_password_rolls_back_hash_and_revocation_when_commit_fails(
    engine,
    user,
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    with Session(engine) as db:
        db.add(
            LoginSession(
                user_id=user.id,
                token_hash="a" * 64,
                csrf_token_hash="b" * 64,
                created_at=user.created_at,
                expires_at=user.updated_at,
            )
        )
        db.commit()

    def fail_commit(db: Session) -> None:
        db.flush()
        raise SQLAlchemyError("commit failed")

    monkeypatch.setattr(Session, "commit", fail_commit)
    assert reset_password(user.username, "new-correct-password") == 4
    captured = capsys.readouterr()
    assert "new-correct-password" not in captured.out + captured.err
    with Session(engine) as db:
        stored = db.scalar(select(User.password_hash).where(User.id == user.id))
        login_session = db.scalar(select(LoginSession).where(LoginSession.user_id == user.id))
    assert stored is not None
    assert login_session is not None
    assert verify_password("correct-password", stored)
    assert login_session.revoked_at is None


def test_admin_commands_report_database_failure_without_exception_details(
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    unavailable_url = "postgresql+psycopg://trainlab:do-not-print@127.0.0.1:1/unavailable_test"
    monkeypatch.setenv("TRAINLAB_DATABASE_URL", unavailable_url)
    from trainlab.core.config import get_settings

    get_settings.cache_clear()
    try:
        assert revoke_sessions("owner-user") == 4
        captured = capsys.readouterr()
        assert "do-not-print" not in captured.out + captured.err
        assert unavailable_url not in captured.out + captured.err
    finally:
        monkeypatch.delenv("TRAINLAB_DATABASE_URL")
        get_settings.cache_clear()


def test_revoke_sessions_is_idempotent_and_does_not_affect_another_user(
    settings,
    engine,
    user,
    origin_headers: dict[str, str],
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    peer = create_test_user(engine, "second-user")
    with (
        TestClient(create_app(settings), client=("owner-session", 50004)) as owner_client,
        TestClient(create_app(settings), client=("peer-session", 50005)) as peer_client,
    ):
        assert _login(owner_client, origin_headers).status_code == 200
        assert _login(peer_client, origin_headers, username=peer.username).status_code == 200
        session_secrets = [
            owner_client.cookies.get("trainlab_session"),
            owner_client.cookies.get("trainlab_csrf"),
            peer_client.cookies.get("trainlab_session"),
            peer_client.cookies.get("trainlab_csrf"),
        ]
        assert revoke_sessions(user.username) == 0
        with Session(engine) as db:
            first_revoked_at = db.scalar(
                select(LoginSession.revoked_at).where(LoginSession.user_id == user.id)
            )
        assert first_revoked_at is not None
        assert revoke_sessions(user.username) == 0
        with Session(engine) as db:
            second_revoked_at = db.scalar(
                select(LoginSession.revoked_at).where(LoginSession.user_id == user.id)
            )
        assert second_revoked_at == first_revoked_at
        assert owner_client.get("/api/v1/auth/session").status_code == 401
        assert peer_client.get("/api/v1/auth/session").status_code == 200

    with (
        TestClient(create_app(settings), client=("owner-new-login", 50006)) as owner_login,
        TestClient(create_app(settings), client=("peer-new-login", 50007)) as peer_login,
    ):
        assert _login(owner_login, origin_headers).status_code == 200
        assert _login(peer_login, origin_headers, username=peer.username).status_code == 200
    captured = capsys.readouterr()
    for session_secret in session_secrets:
        assert session_secret is not None
        assert session_secret not in captured.out + captured.err
