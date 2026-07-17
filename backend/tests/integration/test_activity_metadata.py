import threading
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from trainlab.core.security import hash_password, normalize_username
from trainlab.db.models.activity import Activity, ActivityImport
from trainlab.db.models.user import User
from trainlab.importers.fit import FitDecodeFailure
from trainlab.services.activity_metadata import update_activity_name
from trainlab.services.auth import LoginRateLimiter

FIT_FIXTURE = (
    Path(__file__).parents[3] / "frontend" / "tests" / "fixtures" / "614797758_ACTIVITY.fit"
)


def _login(client: TestClient, user: User) -> dict[str, str]:
    client.app.state.login_rate_limiter = LoginRateLimiter()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": "correct-password"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    csrf = client.cookies.get("trainlab_csrf")
    assert csrf
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf}


def _upload(client: TestClient, headers: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID, str]:
    response = client.post(
        "/api/v1/imports/fit",
        files={"file": ("run.fit", FIT_FIXTURE.read_bytes(), "application/vnd.ant.fit")},
        headers=headers,
    )
    assert response.status_code == 201
    payload = response.json()
    return (
        uuid.UUID(payload["activity"]["id"]),
        uuid.UUID(payload["importId"]),
        payload["activity"]["name"],
    )


def _create_user(engine, username: str) -> User:  # type: ignore[no-untyped-def]
    with Session(engine) as db:
        user = User(
            username=username,
            username_normalized=normalize_username(username),
            display_name=username,
            password_hash=hash_password("correct-password"),
            is_owner=False,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def test_owner_can_rename_and_clear_name_across_list_and_detail(
    client: TestClient, user: User
) -> None:
    headers = _login(client, user)
    activity_id, _, parsed_name = _upload(client, headers)

    renamed = client.patch(
        f"/api/v1/activities/{activity_id}", json={"name": "  Evening Run  "}, headers=headers
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Evening Run"
    assert client.get("/api/v1/activities").json()["items"][0]["name"] == "Evening Run"
    assert (
        client.get(f"/api/v1/activities/{activity_id}").json()["activity"]["name"] == "Evening Run"
    )

    cleared = client.patch(
        f"/api/v1/activities/{activity_id}", json={"name": None}, headers=headers
    )
    assert cleared.status_code == 200
    assert cleared.json()["name"] == parsed_name


@pytest.mark.parametrize("name", ["   ", "a" * 256, "bad\nname", "bad\x00name"])
def test_invalid_activity_names_return_stable_error(
    client: TestClient, user: User, name: str
) -> None:
    headers = _login(client, user)
    activity_id, _, _ = _upload(client, headers)
    response = client.patch(
        f"/api/v1/activities/{activity_id}", json={"name": name}, headers=headers
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_activity_name"


def test_rename_requires_session_csrf_and_does_not_disclose_other_user(
    client: TestClient, user: User, engine
) -> None:  # type: ignore[no-untyped-def]
    owner_headers = _login(client, user)
    activity_id, _, _ = _upload(client, owner_headers)

    client.cookies.clear()
    unauthenticated = client.patch(
        f"/api/v1/activities/{activity_id}",
        json={"name": "Hidden"},
        headers={"Origin": "http://testserver"},
    )
    assert unauthenticated.status_code == 401

    other = _create_user(engine, "other-user")
    other_headers = _login(client, other)
    missing_csrf = client.patch(
        f"/api/v1/activities/{activity_id}",
        json={"name": "Hidden"},
        headers={"Origin": "http://testserver"},
    )
    assert missing_csrf.status_code == 403
    hidden = client.patch(
        f"/api/v1/activities/{activity_id}", json={"name": "Hidden"}, headers=other_headers
    )
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "not_found"


def test_replay_success_and_failure_keep_title_override(
    client: TestClient, user: User, engine, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    headers = _login(client, user)
    activity_id, import_id, _ = _upload(client, headers)
    renamed = client.patch(
        f"/api/v1/activities/{activity_id}", json={"name": "Persistent Name"}, headers=headers
    )
    assert renamed.status_code == 200

    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        assert imported is not None
        imported.status = "partial"
        db.commit()
    replayed = client.post(f"/api/v1/imports/{import_id}/retry", headers=headers)
    assert replayed.status_code == 200
    assert replayed.json()["activity"]["name"] == "Persistent Name"

    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        assert imported is not None
        imported.status = "partial"
        db.commit()

    def fail_parse(_source, _name):  # type: ignore[no-untyped-def]
        raise FitDecodeFailure("fit_decode_failed", "FIT 文件无法解析")

    monkeypatch.setattr("trainlab.services.activity_import.parse_fit_file", fail_parse)
    failed = client.post(f"/api/v1/imports/{import_id}/retry", headers=headers)
    assert failed.status_code == 422
    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        assert imported is not None
        assert imported.status == "failed"
        assert imported.title_override == "Persistent Name"


def test_concurrent_update_keeps_last_committed_name(
    client: TestClient, user: User, engine
) -> None:  # type: ignore[no-untyped-def]
    headers = _login(client, user)
    activity_id, _, _ = _upload(client, headers)
    errors: list[BaseException] = []
    started = threading.Event()

    with Session(engine) as first:
        imported = first.scalar(
            select(ActivityImport)
            .join(Activity, Activity.source_import_id == ActivityImport.id)
            .where(Activity.id == activity_id, ActivityImport.user_id == user.id)
            .with_for_update()
        )
        assert imported is not None

        def second_update() -> None:
            started.set()
            try:
                with Session(engine) as second:
                    update_activity_name(second, user.id, activity_id, "Second")
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.append(exc)

        thread = threading.Thread(target=second_update)
        thread.start()
        assert started.wait(timeout=1)
        time.sleep(0.1)
        imported.title_override = "First"
        first.commit()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert not errors
    with Session(engine) as db:
        stored = db.scalar(select(ActivityImport).where(ActivityImport.user_id == user.id))
        assert stored is not None
        assert stored.title_override == "Second"
