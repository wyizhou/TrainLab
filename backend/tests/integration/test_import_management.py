import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trainlab.core.security import hash_password, normalize_username
from trainlab.db.models.activity import Activity, ActivityImport
from trainlab.db.models.user import User
from trainlab.importers.fit import parse_fit_file
from trainlab.services.activity_storage import PrivateActivityStorage, StorageError
from trainlab.services.auth import LoginRateLimiter
from trainlab.services.import_management import DeleteTarget, delete_user_import

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


def _upload(client: TestClient, headers: dict[str, str], name: str = "run.fit") -> dict:
    response = client.post(
        "/api/v1/imports/fit",
        files={"file": (name, FIT_FIXTURE.read_bytes(), "application/vnd.ant.fit")},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


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


def test_import_list_exposes_all_public_states_with_stable_cursor_and_safe_errors(
    client: TestClient, user: User, engine
) -> None:  # type: ignore[no-untyped-def]
    statuses = [
        "pending",
        "processing",
        "complete",
        "partial",
        "failed",
        "deleting",
        "delete_failed",
    ]
    with Session(engine) as db:
        for index, status in enumerate(statuses):
            import_id = uuid.uuid4()
            imported = ActivityImport(
                id=import_id,
                user_id=user.id,
                source="fit_upload",
                original_filename=f"state-{status}.fit",
                size_bytes=index + 1,
                sha256=f"{index:064x}",
                storage_key=f"{user.id}/{import_id}.fit",
                status=status,
                parser_name="test",
                parser_version="1",
                attempt_count=1,
                warning_count=index,
                error_code="unsafe_code" if status == "failed" else None,
                error_message="/private/SECRET.fit" if status == "failed" else None,
                delete_error_code="private_storage_unavailable"
                if status == "delete_failed"
                else None,
                replay_metadata={},
                created_at=datetime(2026, 1, index + 1, tzinfo=UTC),
                updated_at=datetime(2026, 1, index + 1, tzinfo=UTC),
            )
            db.add(imported)
            db.flush()
            if status in {"complete", "partial"}:
                db.add(
                    Activity(
                        user_id=user.id,
                        source_import_id=import_id,
                        title=status,
                        sport="running",
                        sub_sport="generic",
                        profile="run",
                        start_time_utc=datetime(2026, 1, index + 1, tzinfo=UTC),
                        total_timer_time_sec=1,
                        total_elapsed_time_sec=1,
                        total_distance_m=1,
                        extra_metrics={},
                    )
                )
        db.commit()

    headers = _login(client, user)
    items: list[dict] = []
    cursor: str | None = None
    while True:
        suffix = f"&cursor={cursor}" if cursor else ""
        response = client.get(f"/api/v1/imports?limit=3{suffix}", headers=headers)
        assert response.status_code == 200
        page = response.json()
        items.extend(page["items"])
        cursor = page["nextCursor"]
        if cursor is None:
            break

    assert [item["status"] for item in items] == list(reversed(statuses))
    assert {item["status"] for item in items} == set(statuses)
    assert "SECRET" not in str(items)
    failed = next(item for item in items if item["status"] == "failed")
    assert failed["errorCode"] == "unsafe_code"
    assert failed["errorMessage"] == "FIT 导入处理失败"
    assert failed["retryAvailable"] is True
    delete_failed = next(item for item in items if item["status"] == "delete_failed")
    assert delete_failed["deleteRetryAvailable"] is True
    assert delete_failed["errorMessage"] == "原始 FIT 文件删除尚未完成"
    assert client.get("/api/v1/imports?cursor=invalid", headers=headers).json()["code"] == (
        "invalid_cursor"
    )


def test_activity_delete_removes_file_and_cascade_then_same_sha_can_upload_again(
    client: TestClient, user: User, engine, settings
) -> None:  # type: ignore[no-untyped-def]
    headers = _login(client, user)
    created = _upload(client, headers)
    activity_id = created["activity"]["id"]
    import_id = uuid.UUID(created["importId"])
    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        assert imported is not None
        source_path = PrivateActivityStorage(settings.private_storage_root).path_for_key(
            imported.storage_key, user.id
        )
    assert source_path.exists()

    deleted = client.delete(f"/api/v1/activities/{activity_id}", headers=headers)
    assert deleted.status_code == 204
    assert not source_path.exists()
    with Session(engine) as db:
        assert db.get(ActivityImport, import_id) is None
        assert db.scalar(select(func.count(Activity.id))) == 0
    assert client.delete(f"/api/v1/activities/{activity_id}", headers=headers).status_code == 204

    reuploaded = _upload(client, headers, "same.fit")
    assert reuploaded["importId"] != str(import_id)


def test_failed_import_and_missing_source_can_be_deleted(
    client: TestClient, user: User, engine, settings
) -> None:  # type: ignore[no-untyped-def]
    headers = _login(client, user)
    failed = client.post(
        "/api/v1/imports/fit",
        files={"file": ("broken.fit", b".FITbroken", "application/vnd.ant.fit")},
        headers=headers,
    )
    assert failed.status_code == 422
    import_id = uuid.UUID(failed.json()["details"]["importId"])
    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        assert imported is not None
        PrivateActivityStorage(settings.private_storage_root).remove(imported.storage_key, user.id)
        assert db.scalar(select(func.count(Activity.id))) == 0

    deleted = client.delete(f"/api/v1/imports/{import_id}", headers=headers)
    assert deleted.status_code == 204
    with Session(engine) as db:
        assert db.get(ActivityImport, import_id) is None


def test_file_delete_failure_is_private_recoverable_and_clears_processing_token(
    client: TestClient, user: User, engine, monkeypatch, caplog
) -> None:  # type: ignore[no-untyped-def]
    headers = _login(client, user)
    created = _upload(client, headers)
    import_id = uuid.UUID(created["importId"])
    sentinel = "/private/SECRET.fit"
    original_remove = PrivateActivityStorage.remove

    def fail_remove(self, storage_key, expected_user_id):  # type: ignore[no-untyped-def]
        raise StorageError("private_storage_unavailable", sentinel)

    monkeypatch.setattr(PrivateActivityStorage, "remove", fail_remove)
    failed = client.delete(f"/api/v1/imports/{import_id}", headers=headers)
    assert failed.status_code == 503
    assert failed.json()["code"] == "delete_incomplete"
    assert sentinel not in failed.text
    assert sentinel not in caplog.text
    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        assert imported is not None
        assert imported.status == "delete_failed"
        assert imported.processing_token is None
        assert imported.delete_attempt_count == 1
        assert imported.delete_error_code == "private_storage_unavailable"

    monkeypatch.setattr(PrivateActivityStorage, "remove", original_remove)
    recovered = client.delete(f"/api/v1/imports/{import_id}", headers=headers)
    assert recovered.status_code == 204
    with Session(engine) as db:
        assert db.get(ActivityImport, import_id) is None


def test_fresh_processing_rejects_delete_but_stale_attempt_is_fenced(
    client: TestClient, user: User, engine
) -> None:  # type: ignore[no-untyped-def]
    headers = _login(client, user)
    created = _upload(client, headers)
    import_id = uuid.UUID(created["importId"])
    token = uuid.uuid4()
    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        assert imported is not None
        imported.status = "processing"
        imported.last_attempt_at = datetime.now(UTC)
        imported.processing_token = token
        db.commit()

    busy = client.delete(f"/api/v1/imports/{import_id}", headers=headers)
    assert busy.status_code == 409
    assert busy.json()["code"] == "import_in_progress"
    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        assert imported is not None
        assert imported.processing_token == token
        imported.last_attempt_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()

    assert client.delete(f"/api/v1/imports/{import_id}", headers=headers).status_code == 204


def test_delete_is_csrf_protected_and_cross_user_idempotent_without_disclosure(
    client: TestClient, user: User, engine
) -> None:  # type: ignore[no-untyped-def]
    owner_headers = _login(client, user)
    created = _upload(client, owner_headers)
    import_id = uuid.UUID(created["importId"])
    client.cookies.clear()
    unauthenticated = client.delete(
        f"/api/v1/imports/{import_id}", headers={"Origin": "http://testserver"}
    )
    assert unauthenticated.status_code == 401

    other = _create_user(engine, "other-user")
    other_headers = _login(client, other)
    assert client.get("/api/v1/imports", headers=other_headers).json()["items"] == []
    without_csrf = client.delete(
        f"/api/v1/imports/{import_id}", headers={"Origin": "http://testserver"}
    )
    assert without_csrf.status_code == 403
    assert client.delete(f"/api/v1/imports/{import_id}", headers=other_headers).status_code == 204
    with Session(engine) as db:
        assert db.get(ActivityImport, import_id) is not None


def test_database_final_delete_failure_stays_recoverable(
    client: TestClient, user: User, engine, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    headers = _login(client, user)
    created = _upload(client, headers)
    import_id = uuid.UUID(created["importId"])
    original_commit = Session.commit
    commits = 0

    def fail_second_commit(session):  # type: ignore[no-untyped-def]
        nonlocal commits
        commits += 1
        if commits == 2:
            raise RuntimeError("database commit failed")
        return original_commit(session)

    monkeypatch.setattr(Session, "commit", fail_second_commit)
    failed = client.delete(f"/api/v1/imports/{import_id}", headers=headers)
    assert failed.status_code == 503
    assert failed.json()["code"] == "delete_incomplete"
    monkeypatch.setattr(Session, "commit", original_commit)
    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        assert imported is not None
        assert imported.status == "deleting"
        assert imported.processing_token is None

    assert client.delete(f"/api/v1/imports/{import_id}", headers=headers).status_code == 204
    with Session(engine) as db:
        assert db.get(ActivityImport, import_id) is None


def test_duplicate_upload_conflicts_while_delete_state_owns_import(
    client: TestClient, user: User, engine
) -> None:  # type: ignore[no-untyped-def]
    headers = _login(client, user)
    created = _upload(client, headers)
    import_id = uuid.UUID(created["importId"])
    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        assert imported is not None
        imported.status = "deleting"
        imported.processing_token = None
        db.commit()

    duplicate = client.post(
        "/api/v1/imports/fit",
        files={"file": ("same.fit", FIT_FIXTURE.read_bytes(), "application/vnd.ant.fit")},
        headers=headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "import_deleting"


def test_stale_running_parse_is_fenced_when_delete_wins(
    client: TestClient, user: User, engine, settings, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    headers = _login(client, user)
    parsed = parse_fit_file(FIT_FIXTURE, "run.fit")

    def delete_during_parse(_source, _name):  # type: ignore[no-untyped-def]
        with Session(engine) as other:
            imported = other.scalar(
                select(ActivityImport).where(
                    ActivityImport.user_id == user.id,
                    ActivityImport.status == "processing",
                )
            )
            assert imported is not None
            import_id = imported.id
            imported.last_attempt_at = datetime.now(UTC) - timedelta(hours=1)
            other.commit()
        with Session(engine) as deleter:
            delete_user_import(
                deleter,
                PrivateActivityStorage(settings.private_storage_root),
                user.id,
                DeleteTarget(import_id=import_id),
                settings.import_processing_stale_minutes,
            )
        return parsed

    monkeypatch.setattr("trainlab.services.activity_import.parse_fit_file", delete_during_parse)
    response = client.post(
        "/api/v1/imports/fit",
        files={"file": ("run.fit", FIT_FIXTURE.read_bytes(), "application/vnd.ant.fit")},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "import_attempt_superseded"
    with Session(engine) as db:
        assert db.scalar(select(func.count(ActivityImport.id))) == 0
        assert db.scalar(select(func.count(Activity.id))) == 0
