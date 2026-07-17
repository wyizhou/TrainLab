import asyncio
import os
import threading
import uuid
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from trainlab.cli import build_parser, reconcile_private_storage
from trainlab.db.models.activity import ActivityImport
from trainlab.db.models.user import User
from trainlab.services.activity_import import (
    ImportInternalError,
    StorageQuotaExceeded,
    register_fit_upload,
)
from trainlab.services.activity_storage import PrivateActivityStorage, StorageError
from trainlab.services.auth import LoginRateLimiter
from trainlab.services.storage_usage import reconcile_storage

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


def _service_upload(
    db: Session,
    storage: PrivateActivityStorage,
    user_id: uuid.UUID,
    payload: bytes,
    *,
    max_bytes: int = 50 * 1024 * 1024,
    user_max_bytes: int = 5 * 1024 * 1024 * 1024,
    user_max_files: int = 10_000,
):  # type: ignore[no-untyped-def]
    return asyncio.run(
        register_fit_upload(
            db,
            storage,
            UploadFile(filename="activity.fit", file=BytesIO(payload)),
            user_id,
            max_bytes,
            15,
            user_max_bytes,
            user_max_files,
        )
    )


def test_storage_usage_is_authenticated_and_counts_every_import_state(
    client: TestClient, user: User, engine
) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/v1/storage/usage").status_code == 401
    with Session(engine) as db:
        for index, status in enumerate(["failed", "deleting", "delete_failed"]):
            import_id = uuid.uuid4()
            db.add(
                ActivityImport(
                    id=import_id,
                    user_id=user.id,
                    source="fit_upload",
                    original_filename=f"{status}.fit",
                    size_bytes=(index + 1) * 10,
                    sha256=f"{index:064x}",
                    storage_key=f"{user.id}/{import_id}.fit",
                    status=status,
                    parser_name="test",
                    parser_version="1",
                    attempt_count=1,
                    warning_count=0,
                    replay_metadata={},
                )
            )
        peer = User(
            username="peer-user",
            username_normalized="peer-user",
            display_name="Peer",
            password_hash="unused-in-this-test",
            is_owner=False,
            is_active=True,
        )
        db.add(peer)
        db.flush()
        peer_import_id = uuid.uuid4()
        db.add(
            ActivityImport(
                id=peer_import_id,
                user_id=peer.id,
                source="fit_upload",
                original_filename="peer.fit",
                size_bytes=999,
                sha256="f" * 64,
                storage_key=f"{peer.id}/{peer_import_id}.fit",
                status="failed",
                parser_name="test",
                parser_version="1",
                attempt_count=1,
                warning_count=0,
                replay_metadata={},
            )
        )
        db.commit()

    response = client.get("/api/v1/storage/usage", headers=_login(client, user))
    assert response.status_code == 200
    assert response.json() == {
        "usedBytes": 60,
        "fileCount": 3,
        "maxBytes": 5 * 1024 * 1024 * 1024,
        "maxFiles": 10_000,
        "remainingBytes": 5 * 1024 * 1024 * 1024 - 60,
        "remainingFiles": 9_997,
    }

    with Session(engine) as db:
        released = db.scalar(
            select(ActivityImport).where(
                ActivityImport.user_id == user.id,
                ActivityImport.size_bytes == 30,
            )
        )
        assert released is not None
        db.delete(released)
        db.commit()
    after_delete = client.get("/api/v1/storage/usage", headers=_login(client, user)).json()
    assert after_delete["usedBytes"] == 30
    assert after_delete["fileCount"] == 2


def test_byte_and_file_quota_reject_new_unique_file_but_duplicate_does_not_grow_usage(
    user: User, engine, settings
) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(settings.private_storage_root)
    payload = FIT_FIXTURE.read_bytes()
    with Session(engine) as db:
        first = _service_upload(db, storage, user.id, payload, user_max_files=1)
        assert first.model.status == "complete"
    with Session(engine) as db:
        duplicate = _service_upload(db, storage, user.id, payload, user_max_files=1)
        assert duplicate.deduplicated is True
    with Session(engine) as db:
        try:
            _service_upload(
                db,
                storage,
                user.id,
                payload + b"unique",
                user_max_bytes=len(payload) + 1,
                user_max_files=1,
            )
        except StorageQuotaExceeded as exc:
            assert exc.code == "storage_quota_exceeded"
            assert exc.details["fileCount"] == 1
        else:  # pragma: no cover - assertion boundary
            raise AssertionError("unique upload unexpectedly bypassed quota")
    with Session(engine) as db:
        assert (
            len(db.scalars(select(ActivityImport).where(ActivityImport.user_id == user.id)).all())
            == 1
        )


def test_single_file_limit_wins_before_user_quota(user: User, engine, settings) -> None:  # type: ignore[no-untyped-def]
    with Session(engine) as db:
        try:
            _service_upload(
                db,
                PrivateActivityStorage(settings.private_storage_root),
                user.id,
                b"too large",
                max_bytes=1,
                user_max_bytes=1,
                user_max_files=1,
            )
        except StorageError as exc:
            assert exc.code == "fit_file_too_large"
        else:  # pragma: no cover - assertion boundary
            raise AssertionError("single-file limit was not enforced")


def test_two_concurrent_uploads_are_serialized_by_user_quota(user: User, engine, settings) -> None:  # type: ignore[no-untyped-def]
    payload = FIT_FIXTURE.read_bytes()
    payloads = [payload + b"first", payload + b"second"]
    limit = len(payloads[0]) + 1
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def upload(payload_bytes: bytes) -> None:
        try:
            barrier.wait(timeout=5)
            with Session(engine) as db:
                _service_upload(
                    db,
                    PrivateActivityStorage(settings.private_storage_root),
                    user.id,
                    payload_bytes,
                    user_max_bytes=limit,
                )
            outcomes.append("accepted")
        except StorageQuotaExceeded:
            outcomes.append("quota")
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=upload, args=(item,)) for item in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not any(thread.is_alive() for thread in threads)
    assert not errors
    assert sorted(outcomes) == ["accepted", "quota"]
    with Session(engine) as db:
        imports = db.scalars(select(ActivityImport).where(ActivityImport.user_id == user.id)).all()
        assert len(imports) == 1
        assert imports[0].size_bytes <= limit


def test_storage_usage_failure_discards_staging_and_rolls_back(
    user: User, engine, settings, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(settings.private_storage_root)

    def fail_usage(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("injected quota query failure")

    monkeypatch.setattr("trainlab.services.activity_import.storage_usage", fail_usage)
    with Session(engine) as db:
        try:
            _service_upload(db, storage, user.id, FIT_FIXTURE.read_bytes())
        except ImportInternalError as exc:
            assert exc.code == "import_registration_failed"
        else:  # pragma: no cover - assertion boundary
            raise AssertionError("quota query failure unexpectedly registered an import")
        assert db.in_transaction() is False

    assert storage.generated_files(user.id) == []
    with Session(engine) as db:
        assert db.scalar(select(ActivityImport).where(ActivityImport.user_id == user.id)) is None


def test_same_user_large_http_uploads_do_not_deadlock_single_event_loop(
    client: TestClient, user: User
) -> None:
    headers = _login(client, user)
    fixture = FIT_FIXTURE.read_bytes()
    payloads = [
        fixture + (b"a" * (1024 * 1024 + 1)),
        fixture + (b"b" * (1024 * 1024 + 1)),
    ]
    barrier = threading.Barrier(2)
    statuses: list[int] = []
    errors: list[BaseException] = []

    def upload(payload: bytes) -> None:
        try:
            barrier.wait(timeout=5)
            response = client.post(
                "/api/v1/imports/fit",
                headers=headers,
                files={"file": ("activity.fit", payload, "application/vnd.ant.fit")},
            )
            statuses.append(response.status_code)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=upload, args=(payload,)) for payload in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not any(thread.is_alive() for thread in threads)
    assert not errors
    assert sorted(statuses) == [201, 201]
    with Session(client.app.state.engine) as db:
        imports = db.scalars(select(ActivityImport).where(ActivityImport.user_id == user.id)).all()
        assert len(imports) == 2


def test_next_upload_immediately_cleans_staging_and_promoted_orphans(
    user: User, engine, settings
) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(settings.private_storage_root)
    staging = asyncio.run(
        storage.stage_isolated(
            UploadFile(filename="orphan.fit", file=BytesIO(b"staging orphan")),
            user.id,
            uuid.uuid4(),
            1024,
        )
    )
    promoted = asyncio.run(
        storage.stage_isolated(
            UploadFile(filename="orphan.fit", file=BytesIO(b"promoted orphan")),
            user.id,
            uuid.uuid4(),
            1024,
        )
    )
    storage.promote(promoted, user.id)
    promoted_path = storage.path_for_key(promoted.storage_key, user.id)

    with Session(engine) as db:
        _service_upload(db, storage, user.id, FIT_FIXTURE.read_bytes())

    assert not staging.path.exists()
    assert not promoted_path.exists()


def test_reconcile_is_dry_run_by_default_and_apply_honors_grace_and_references(
    user: User, engine, tmp_path, settings, monkeypatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(tmp_path)
    old = asyncio.run(
        storage.stage_isolated(
            UploadFile(filename="old.fit", file=BytesIO(b"old orphan")),
            user.id,
            uuid.uuid4(),
            1024,
        )
    )
    fresh = asyncio.run(
        storage.stage_isolated(
            UploadFile(filename="fresh.fit", file=BytesIO(b"fresh orphan")),
            user.id,
            uuid.uuid4(),
            1024,
        )
    )
    os.utime(old.path, (1, 1))
    with Session(engine) as db:
        dry = reconcile_storage(db, storage, 60, apply=False, now=datetime(2026, 1, 1, tzinfo=UTC))
    assert dry.candidate_count == 1
    assert dry.removed_count == 0
    assert old.path.exists() and fresh.path.exists()

    cli_settings = settings.model_copy(
        update={"private_storage_root": tmp_path, "storage_staging_grace_minutes": 60}
    )
    monkeypatch.setattr("trainlab.cli.get_settings", lambda: cli_settings)
    assert build_parser().parse_args(["reconcile-storage"]).apply is False
    assert reconcile_private_storage(apply=True) == 0
    output = capsys.readouterr()
    assert "mode=apply" in output.out
    assert str(tmp_path) not in output.out + output.err
    assert not old.path.exists()
    assert fresh.path.exists()


def test_reconcile_waits_for_user_lock_and_never_deletes_valid_inflight_file(
    user: User, engine, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(tmp_path)
    staged = asyncio.run(
        storage.stage_isolated(
            UploadFile(filename="inflight.fit", file=BytesIO(b"inflight")),
            user.id,
            uuid.uuid4(),
            1024,
        )
    )
    os.utime(staged.path, (1, 1))
    reports = []
    errors: list[BaseException] = []

    with Session(engine) as uploader:
        locked_user = uploader.scalar(select(User).where(User.id == user.id).with_for_update())
        assert locked_user is not None

        def audit() -> None:
            try:
                with Session(engine) as auditor:
                    reports.append(
                        reconcile_storage(
                            auditor,
                            storage,
                            1,
                            apply=True,
                            now=datetime(2026, 1, 1, tzinfo=UTC),
                        )
                    )
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.append(exc)

        thread = threading.Thread(target=audit)
        thread.start()
        storage.promote(staged, user.id)
        import_id = uuid.UUID(Path(staged.storage_key).stem)
        uploader.add(
            ActivityImport(
                id=import_id,
                user_id=user.id,
                source="fit_upload",
                original_filename="inflight.fit",
                size_bytes=staged.size_bytes,
                sha256=staged.sha256,
                storage_key=staged.storage_key,
                status="pending",
                parser_name="test",
                parser_version="1",
                attempt_count=0,
                warning_count=0,
                replay_metadata={},
            )
        )
        uploader.commit()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert not errors
    assert reports[0].removed_count == 0
    assert storage.path_for_key(staged.storage_key, user.id).exists()
