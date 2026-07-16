from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from conftest import create_test_user
from trainlab.db.models.session import LoginSession


def login(
    client: TestClient,
    headers: dict[str, str],
    username: str = "owner-user",
    password: str = "correct-password",
):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers=headers,
    )


def test_login_sets_secure_session_shape_and_restores_user(
    client: TestClient,
    user,
    origin_headers: dict[str, str],
) -> None:  # type: ignore[no-untyped-def]
    response = login(client, origin_headers)
    assert response.status_code == 200
    assert response.json()["user"]["id"] == str(user.id)
    assert response.json()["user"]["isOwner"] is True
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(value for value in cookies if value.startswith("trainlab_session="))
    csrf_cookie = next(value for value in cookies if value.startswith("trainlab_csrf="))
    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie
    assert "HttpOnly" not in csrf_cookie

    restored = client.get("/api/v1/auth/session")
    assert restored.status_code == 200
    assert restored.json()["user"]["username"] == "owner-user"


def test_missing_or_untrusted_origin_is_rejected(client: TestClient, user) -> None:  # type: ignore[no-untyped-def]
    missing = login(client, {})
    assert missing.status_code == 403
    assert missing.json()["code"] == "invalid_origin"
    foreign = login(client, {"Origin": "https://evil.example"})
    assert foreign.status_code == 403


def test_bad_and_unknown_credentials_share_generic_failure(
    client: TestClient,
    user,
    origin_headers: dict[str, str],
) -> None:  # type: ignore[no-untyped-def]
    wrong = login(client, origin_headers, password="incorrect-password")
    unknown = login(client, origin_headers, username="missing-user")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["code"] == unknown.json()["code"] == "invalid_credentials"
    assert wrong.json()["message"] == unknown.json()["message"]


def test_repeated_failures_are_generic_and_cannot_lock_out_valid_owner(
    client: TestClient,
    user,
    origin_headers: dict[str, str],
) -> None:  # type: ignore[no-untyped-def]
    for _ in range(5):
        assert login(client, origin_headers, password="incorrect-password").status_code == 401
    still_generic = login(client, origin_headers, password="incorrect-password")
    assert still_generic.status_code == 401
    assert still_generic.json()["code"] == "invalid_credentials"
    assert login(client, origin_headers).status_code == 401

    with TestClient(client.app, client=("owner-recovery", 50000)) as recovery_client:
        assert login(recovery_client, origin_headers).status_code == 200


def test_logout_requires_csrf_and_revokes_server_session(
    client: TestClient,
    user,
    origin_headers: dict[str, str],
) -> None:  # type: ignore[no-untyped-def]
    assert login(client, origin_headers).status_code == 200
    no_csrf = client.post("/api/v1/auth/logout", headers=origin_headers)
    assert no_csrf.status_code == 403

    csrf = client.cookies.get("trainlab_csrf")
    assert csrf is not None
    logged_out = client.post(
        "/api/v1/auth/logout",
        headers={**origin_headers, "X-CSRF-Token": csrf},
    )
    assert logged_out.status_code == 200
    assert client.get("/api/v1/auth/session").status_code == 401


def test_expired_session_is_rejected(
    client: TestClient,
    user,
    origin_headers: dict[str, str],
    engine,
) -> None:  # type: ignore[no-untyped-def]
    assert login(client, origin_headers).status_code == 200
    with Session(engine) as db:
        session = db.scalar(select(LoginSession))
        assert session is not None
        session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/auth/session").status_code == 401


def test_two_users_restore_only_their_own_identity(
    settings,
    engine,
    user,
    origin_headers: dict[str, str],
) -> None:  # type: ignore[no-untyped-def]
    second = create_test_user(engine, "second-user")
    from trainlab.main import create_app

    with (
        TestClient(create_app(settings)) as owner_client,
        TestClient(create_app(settings)) as second_client,
    ):
        assert login(owner_client, origin_headers).status_code == 200
        assert login(second_client, origin_headers, username="second-user").status_code == 200
        owner_me = owner_client.get("/api/v1/auth/session").json()["user"]
        second_me = second_client.get("/api/v1/auth/session").json()["user"]
    assert owner_me["id"] == str(user.id)
    assert second_me["id"] == str(second.id)
    assert owner_me["id"] != second_me["id"]
