import threading
from time import monotonic

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from trainlab import cli
from trainlab.db.models.session import LoginSession
from trainlab.main import create_app
from trainlab.services import auth as auth_service
from trainlab.services import user_admin


def _login(
    client: TestClient,
    headers: dict[str, str],
    *,
    password: str = "correct-password",
):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/v1/auth/login",
        json={"username": "owner-user", "password": password},
        headers=headers,
    )


def _pause_first_successful_old_password_check(monkeypatch):  # type: ignore[no-untyped-def]
    verified = threading.Event()
    release = threading.Event()
    original_verify = auth_service.verify_password

    def controlled_verify(password: str, password_hash: str) -> bool:
        valid = original_verify(password, password_hash)
        if password == "correct-password" and valid and not verified.is_set():
            verified.set()
            if not release.wait(timeout=10):
                raise AssertionError("concurrent login was not released")
        return valid

    monkeypatch.setattr(auth_service, "verify_password", controlled_verify)
    return verified, release


def _observe_admin_backend(monkeypatch):  # type: ignore[no-untyped-def]
    pid_ready = threading.Event()
    pid: list[int] = []
    original_locked_user = user_admin._locked_user

    def observed_locked_user(db: Session, username: str):  # type: ignore[no-untyped-def]
        backend_pid = db.scalar(text("SELECT pg_backend_pid()"))
        assert isinstance(backend_pid, int)
        pid.append(backend_pid)
        pid_ready.set()
        return original_locked_user(db, username)

    monkeypatch.setattr(user_admin, "_locked_user", observed_locked_user)
    return pid_ready, pid


def _wait_until_postgres_reports_lock(engine, pid: int, completed: threading.Event) -> None:  # type: ignore[no-untyped-def]
    deadline = monotonic() + 10
    while monotonic() < deadline:
        if completed.is_set():
            raise AssertionError("admin command bypassed the login user-row lock")
        with engine.connect() as connection:
            wait_event_type = connection.scalar(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": pid},
            )
        if wait_event_type == "Lock":
            return
    raise AssertionError("admin command did not wait on the login user-row lock")


def _active_session_count(engine, user_id) -> int:  # type: ignore[no-untyped-def]
    with Session(engine) as db:
        count = db.scalar(
            select(func.count())
            .select_from(LoginSession)
            .where(
                LoginSession.user_id == user_id,
                LoginSession.revoked_at.is_(None),
            )
        )
    assert isinstance(count, int)
    return count


def test_reset_password_serializes_with_login_before_revoking_session(
    settings,
    engine,
    user,
    origin_headers: dict[str, str],
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    verified, release_login = _pause_first_successful_old_password_check(monkeypatch)
    pid_ready, admin_pid = _observe_admin_backend(monkeypatch)
    login_result: list[object] = []
    admin_result: list[int] = []
    login_error: list[BaseException] = []
    admin_error: list[BaseException] = []
    admin_completed = threading.Event()
    new_password = "new-race-safe-password"

    with TestClient(create_app(settings), client=("concurrent-login", 50100)) as login_client:

        def run_login() -> None:
            try:
                login_result.append(_login(login_client, origin_headers))
            except BaseException as exc:
                login_error.append(exc)

        def run_reset() -> None:
            try:
                admin_result.append(cli.reset_password(user.username, new_password))
            except BaseException as exc:
                admin_error.append(exc)
            finally:
                admin_completed.set()

        login_thread = threading.Thread(target=run_login)
        login_thread.start()
        assert verified.wait(timeout=10)

        admin_thread = threading.Thread(target=run_reset)
        admin_thread.start()
        assert pid_ready.wait(timeout=10)
        _wait_until_postgres_reports_lock(engine, admin_pid[0], admin_completed)

        release_login.set()
        login_thread.join(timeout=10)
        admin_thread.join(timeout=10)
        assert not login_thread.is_alive()
        assert not admin_thread.is_alive()
        assert not login_error
        assert not admin_error
        assert admin_result == [0]
        assert len(login_result) == 1
        assert login_result[0].status_code == 200  # type: ignore[union-attr]
        assert login_client.get("/api/v1/auth/session").status_code == 401

    assert _active_session_count(engine, user.id) == 0
    with TestClient(create_app(settings), client=("post-reset-login", 50101)) as post_reset:
        assert _login(post_reset, origin_headers).status_code == 401
        assert _login(post_reset, origin_headers, password=new_password).status_code == 200

    captured = capsys.readouterr()
    assert new_password not in captured.out + captured.err


def test_revoke_sessions_serializes_with_login_and_leaves_no_missed_session(
    settings,
    engine,
    user,
    origin_headers: dict[str, str],
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    verified, release_login = _pause_first_successful_old_password_check(monkeypatch)
    pid_ready, admin_pid = _observe_admin_backend(monkeypatch)
    login_result: list[object] = []
    admin_result: list[int] = []
    login_error: list[BaseException] = []
    admin_error: list[BaseException] = []
    admin_completed = threading.Event()

    with TestClient(create_app(settings), client=("concurrent-login", 50102)) as login_client:

        def run_login() -> None:
            try:
                login_result.append(_login(login_client, origin_headers))
            except BaseException as exc:
                login_error.append(exc)

        def run_revoke() -> None:
            try:
                admin_result.append(cli.revoke_sessions(user.username))
            except BaseException as exc:
                admin_error.append(exc)
            finally:
                admin_completed.set()

        login_thread = threading.Thread(target=run_login)
        login_thread.start()
        assert verified.wait(timeout=10)

        admin_thread = threading.Thread(target=run_revoke)
        admin_thread.start()
        assert pid_ready.wait(timeout=10)
        _wait_until_postgres_reports_lock(engine, admin_pid[0], admin_completed)

        release_login.set()
        login_thread.join(timeout=10)
        admin_thread.join(timeout=10)
        assert not login_thread.is_alive()
        assert not admin_thread.is_alive()
        assert not login_error
        assert not admin_error
        assert admin_result == [0]
        assert len(login_result) == 1
        assert login_result[0].status_code == 200  # type: ignore[union-attr]
        assert login_client.get("/api/v1/auth/session").status_code == 401

    assert _active_session_count(engine, user.id) == 0
    with TestClient(create_app(settings), client=("post-revoke-login", 50103)) as post_revoke:
        assert _login(post_revoke, origin_headers).status_code == 200

    captured = capsys.readouterr()
    assert "correct-password" not in captured.out + captured.err
