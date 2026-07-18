import base64
import hashlib
import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trainlab.api.routes.activities import PrivateFitStreamError, _stream_private_fit
from trainlab.core.security import hash_password, normalize_username
from trainlab.db.models.activity import (
    Activity,
    ActivityDevice,
    ActivityImport,
    ActivityMetricDefinition,
    ActivityRecord,
)
from trainlab.db.models.user import User
from trainlab.importers.fit import FitDecodeFailure, parse_fit_file

FIT_FIXTURE = (
    Path(__file__).parents[3] / "frontend" / "tests" / "fixtures" / "614797758_ACTIVITY.fit"
)


def login(client: TestClient, username: str, password: str = "correct-password") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    csrf = client.cookies.get("trainlab_csrf")
    assert csrf
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf}


def upload_fixture(client: TestClient, headers: dict[str, str], name: str = "run.fit"):
    return client.post(
        "/api/v1/imports/fit",
        files={"file": (name, FIT_FIXTURE.read_bytes(), "application/vnd.ant.fit")},
        headers=headers,
    )


def test_authenticated_fit_upload_is_persistent_idempotent_and_downloadable(
    client: TestClient, user: User, engine
) -> None:  # type: ignore[no-untyped-def]
    unauthenticated = client.post(
        "/api/v1/imports/fit",
        files={"file": ("run.fit", FIT_FIXTURE.read_bytes(), "application/vnd.ant.fit")},
        headers={"Origin": "http://testserver"},
    )
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["cache-control"] == "private, no-store"

    headers = login(client, user.username)
    created = upload_fixture(client, headers)
    assert created.status_code == 201
    assert created.headers["cache-control"] == "private, no-store"
    payload = created.json()
    assert payload["status"] == "complete"
    assert payload["deduplicated"] is False
    assert payload["activity"]["date"] == "2026-07-09"
    activity_id = payload["activity"]["id"]

    duplicate = upload_fixture(client, headers, "same-content-renamed.fit")
    assert duplicate.status_code == 200
    assert duplicate.json()["deduplicated"] is True
    assert duplicate.json()["activity"]["id"] == activity_id

    listing = client.get("/api/v1/activities")
    assert listing.status_code == 200
    assert listing.headers["cache-control"] == "private, no-store"
    assert [item["id"] for item in listing.json()["items"]] == [activity_id]
    assert listing.json()["items"][0]["source"] == "FIT上传"

    detail = client.get(f"/api/v1/activities/{activity_id}")
    assert detail.status_code == 200
    assert detail.headers["cache-control"] == "private, no-store"
    detail_payload = detail.json()
    assert detail_payload["activity"]["profile"] == "run"
    assert detail_payload["recordCount"] == 1890
    assert len(detail_payload["laps"]) == 8
    assert detail_payload["devices"]
    assert all(item["semantic"]["schemaVersion"] == 1 for item in detail_payload["segments"])
    assert all("_trainlabSemantic" not in item["extraData"] for item in detail_payload["segments"])
    assert all(item["deviceId"] is None for item in detail_payload["metricDefinitions"])
    assert detail_payload["summary"]["extraMetrics"][
        "native:time_in_zone:session:time_in_hr_zone"
    ] == pytest.approx([68.49, 798.924, 1014.229, 4.915, 0.0])
    assert "serial" not in detail.text.lower()

    downloaded = client.get(f"/api/v1/activities/{activity_id}/source")
    assert downloaded.status_code == 200
    assert downloaded.content == FIT_FIXTURE.read_bytes()
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert int(downloaded.headers["content-length"]) == FIT_FIXTURE.stat().st_size

    with Session(engine) as db:
        assert db.scalar(select(func.count(ActivityImport.id))) == 1
        assert db.scalar(select(func.count(Activity.id))) == 1
        assert db.scalar(select(func.count(ActivityRecord.id))) == 1890
        assert db.scalar(select(func.count(ActivityDevice.id))) == 8
        assert db.scalar(select(func.count(ActivityMetricDefinition.id))) > 0
        assert db.scalar(select(ActivityImport.user_id)) == user.id
        assert db.scalar(select(Activity.user_id)) == user.id


def test_corrupt_fit_is_retained_as_failed_and_can_be_retried(
    client: TestClient, user: User, settings, engine
) -> None:  # type: ignore[no-untyped-def]
    headers = login(client, user.username)
    failed = client.post(
        "/api/v1/imports/fit",
        files={"file": ("broken.fit", b"not a fit file", "application/x-browser-fit")},
        headers=headers,
    )
    assert failed.status_code == 422
    assert failed.json()["code"] == "fit_import_failed"
    import_id = failed.json()["details"]["importId"]

    with Session(engine) as db:
        model = db.get(ActivityImport, import_id)
        assert model is not None
        assert model.status == "failed"
        assert model.attempt_count == 1
        path = settings.private_storage_root / model.storage_key
        assert path.read_bytes() == b"not a fit file"

    retried = client.post(f"/api/v1/imports/{import_id}/retry", headers=headers)
    assert retried.status_code == 422
    assert retried.json()["details"]["importId"] == import_id
    with Session(engine) as db:
        model = db.get(ActivityImport, import_id)
        assert model is not None
        assert model.attempt_count == 2

    duplicate = client.post(
        "/api/v1/imports/fit",
        files={"file": ("broken-again.fit", b"not a fit file", "application/vnd.ant.fit")},
        headers=headers,
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["details"]["importId"] == import_id


def test_fit_with_invalid_crc_is_rejected_instead_of_persisted_as_partial(
    client: TestClient, user: User, engine
) -> None:  # type: ignore[no-untyped-def]
    content = bytearray(FIT_FIXTURE.read_bytes())
    content[-1] ^= 0x01
    headers = login(client, user.username)
    response = client.post(
        "/api/v1/imports/fit",
        files={"file": ("crc-corrupt.fit", bytes(content), "application/x-browser-fit")},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "fit_import_failed"
    assert response.json()["details"]["errorCode"] == "fit_crc_invalid"
    with Session(engine) as db:
        imported = db.get(ActivityImport, response.json()["details"]["importId"])
        assert imported is not None
        assert imported.status == "failed"
        assert imported.error_code == "fit_crc_invalid"
        assert db.scalar(select(func.count(Activity.id))) == 0


def test_duplicate_upload_never_returns_a_null_activity_success(
    client: TestClient, user: User, engine
) -> None:  # type: ignore[no-untyped-def]
    content = FIT_FIXTURE.read_bytes()
    with Session(engine) as db:
        imported = ActivityImport(
            user_id=user.id,
            source="fit_upload",
            original_filename="existing.fit",
            content_type="application/vnd.ant.fit",
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            storage_key=f"{user.id}/{uuid.uuid4()}.fit",
            status="processing",
            parser_name="garmin-fit-sdk",
            parser_version="21.208.0",
            attempt_count=0,
            last_attempt_at=datetime.now(UTC),
            warning_count=0,
            replay_metadata={},
        )
        db.add(imported)
        db.commit()
        import_id = imported.id

    headers = login(client, user.username)
    processing = upload_fixture(client, headers)
    assert processing.status_code == 409
    assert processing.json()["code"] == "import_in_progress"
    assert processing.json()["details"]["importId"] == str(import_id)

    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        assert imported is not None
        imported.status = "complete"
        db.commit()
    missing_activity = upload_fixture(client, headers)
    assert missing_activity.status_code == 409
    assert missing_activity.json()["code"] == "import_state_invalid"

    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        assert imported is not None
        imported.status = "failed"
        imported.error_code = "fit_decode_failed"
        db.commit()
    failed = upload_fixture(client, headers)
    assert failed.status_code == 422
    assert failed.json()["code"] == "fit_import_failed"
    assert failed.json()["details"]["importId"] == str(import_id)


@pytest.mark.parametrize("initial_status", ["pending", "stale_processing"])
def test_same_file_reupload_recovers_without_a_known_import_id(
    client: TestClient,
    user: User,
    engine,
    settings,
    initial_status: str,
) -> None:  # type: ignore[no-untyped-def]
    content = FIT_FIXTURE.read_bytes()
    import_id = uuid.uuid4()
    storage_key = f"{user.id}/{import_id}.fit"
    raw_path = settings.private_storage_root / storage_key
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(content)
    with Session(engine) as db:
        db.add(
            ActivityImport(
                id=import_id,
                user_id=user.id,
                source="fit_upload",
                original_filename="interrupted.fit",
                content_type="application/vnd.ant.fit",
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                storage_key=storage_key,
                status="pending" if initial_status == "pending" else "processing",
                parser_name="garmin-fit-sdk",
                parser_version="21.208.0",
                attempt_count=1,
                last_attempt_at=(
                    None
                    if initial_status == "pending"
                    else datetime.now(UTC)
                    - timedelta(minutes=settings.import_processing_stale_minutes + 1)
                ),
                warning_count=0,
                replay_metadata={},
            )
        )
        db.commit()

    headers = login(client, user.username)
    recovered = upload_fixture(client, headers)
    assert recovered.status_code == 200
    assert recovered.json()["deduplicated"] is True
    assert recovered.json()["status"] == "complete"
    assert recovered.json()["activity"] is not None
    with Session(engine) as db:
        assert db.scalar(select(func.count(ActivityImport.id))) == 1
        assert db.scalar(select(func.count(Activity.id))) == 1


def test_user_ownership_is_applied_to_list_detail_download_and_deduplication(
    client: TestClient, user: User, engine
) -> None:  # type: ignore[no-untyped-def]
    owner_headers = login(client, user.username)
    first = upload_fixture(client, owner_headers)
    assert first.status_code == 201
    activity_id = first.json()["activity"]["id"]

    with Session(engine) as db:
        peer = User(
            username="peer-user",
            username_normalized=normalize_username("peer-user"),
            display_name="peer-user",
            password_hash=hash_password("correct-password"),
            is_owner=False,
            is_active=True,
        )
        db.add(peer)
        db.commit()
        db.refresh(peer)
        db.expunge(peer)
    client.cookies.clear()
    peer_headers = login(client, peer.username)

    assert client.get(f"/api/v1/activities/{activity_id}").status_code == 404
    assert client.get(f"/api/v1/activities/{activity_id}/source").status_code == 404
    peer_upload = upload_fixture(client, peer_headers)
    assert peer_upload.status_code == 201
    assert peer_upload.json()["activity"]["id"] != activity_id

    with Session(engine) as db:
        assert db.scalar(select(func.count(ActivityImport.id))) == 2
        assert (
            db.scalar(
                select(func.count(ActivityImport.id)).where(ActivityImport.user_id == peer.id)
            )
            == 1
        )


def test_tampered_storage_key_cannot_read_or_replay_another_users_file(
    client: TestClient, user: User, engine, settings
) -> None:  # type: ignore[no-untyped-def]
    owner_headers = login(client, user.username)
    owner_created = upload_fixture(client, owner_headers)
    owner_activity_id = owner_created.json()["activity"]["id"]
    owner_import_id = owner_created.json()["importId"]

    with Session(engine) as db:
        peer = User(
            username="storage-peer",
            username_normalized=normalize_username("storage-peer"),
            display_name="storage-peer",
            password_hash=hash_password("correct-password"),
            is_owner=False,
            is_active=True,
        )
        db.add(peer)
        db.commit()
        peer_id = peer.id
    client.cookies.clear()
    peer_headers = login(client, "storage-peer")
    peer_created = upload_fixture(client, peer_headers)
    peer_import_id = peer_created.json()["importId"]

    with Session(engine) as db:
        owner_import = db.get(ActivityImport, owner_import_id)
        peer_import = db.get(ActivityImport, peer_import_id)
        assert owner_import is not None and peer_import is not None
        peer_path = settings.private_storage_root / peer_import.storage_key
        peer_payload = peer_path.read_bytes()
        tampered_key = f"{peer_id}/{uuid.uuid4()}.fit"
        tampered_path = settings.private_storage_root / tampered_key
        tampered_path.write_bytes(peer_payload)
        owner_import.storage_key = tampered_key
        owner_import.status = "partial"
        db.commit()

    client.cookies.clear()
    owner_headers = login(client, user.username)
    detail = client.get(f"/api/v1/activities/{owner_activity_id}")
    assert detail.status_code == 200
    assert detail.json()["downloadAvailable"] is False
    source = client.get(f"/api/v1/activities/{owner_activity_id}/source")
    assert source.status_code == 410
    assert source.json()["code"] == "raw_file_unavailable"
    assert source.content != peer_payload

    replay = client.post(f"/api/v1/imports/{owner_import_id}/retry", headers=owner_headers)
    assert replay.status_code == 422
    assert replay.json()["details"]["errorCode"] == "raw_file_unavailable"
    with Session(engine) as db:
        peer_import = db.get(ActivityImport, peer_import_id)
        assert peer_import is not None
        assert peer_import.user_id == peer_id
        assert (
            settings.private_storage_root / peer_import.storage_key
        ).read_bytes() == peer_payload
        assert tampered_path.read_bytes() == peer_payload


def test_cross_user_symlink_cannot_be_downloaded_or_replayed(
    client: TestClient, user: User, engine, settings
) -> None:  # type: ignore[no-untyped-def]
    owner_headers = login(client, user.username)
    owner_created = upload_fixture(client, owner_headers)
    owner_activity_id = owner_created.json()["activity"]["id"]
    owner_import_id = owner_created.json()["importId"]

    with Session(engine) as db:
        peer = User(
            username="symlink-peer",
            username_normalized=normalize_username("symlink-peer"),
            display_name="symlink-peer",
            password_hash=hash_password("correct-password"),
            is_owner=False,
            is_active=True,
        )
        db.add(peer)
        db.commit()
    client.cookies.clear()
    peer_headers = login(client, "symlink-peer")
    peer_created = upload_fixture(client, peer_headers)
    peer_import_id = peer_created.json()["importId"]

    with Session(engine) as db:
        owner_import = db.get(ActivityImport, owner_import_id)
        peer_import = db.get(ActivityImport, peer_import_id)
        assert owner_import is not None and peer_import is not None
        owner_path = settings.private_storage_root / owner_import.storage_key
        peer_path = settings.private_storage_root / peer_import.storage_key
        peer_payload = peer_path.read_bytes()
        owner_path.unlink()
        owner_path.symlink_to(peer_path)
        owner_import.status = "partial"
        db.commit()

    client.cookies.clear()
    owner_headers = login(client, user.username)
    source = client.get(f"/api/v1/activities/{owner_activity_id}/source")
    assert source.status_code == 410
    assert source.json()["code"] == "raw_file_unavailable"
    assert source.content != peer_payload
    replay = client.post(f"/api/v1/imports/{owner_import_id}/retry", headers=owner_headers)
    assert replay.status_code == 422
    assert replay.json()["details"]["errorCode"] == "raw_file_unavailable"
    assert peer_path.read_bytes() == peer_payload


@pytest.mark.parametrize(
    ("filename", "content_type", "content"),
    [
        ("track.gpx", "application/gpx+xml", b"<gpx/>"),
        ("workout.tcx", "application/vnd.garmin.tcx+xml", b"<TrainingCenterDatabase/>"),
    ],
)
def test_fit_endpoint_rejects_non_fit_before_storage(
    client: TestClient,
    user: User,
    filename: str,
    content_type: str,
    content: bytes,
) -> None:
    headers = login(client, user.username)
    response = client.post(
        "/api/v1/imports/fit",
        files={"file": (filename, content, content_type)},
        headers=headers,
    )
    assert response.status_code == 415
    assert response.json()["code"] == "fit_format_required"


def test_fit_extension_uses_decoder_instead_of_untrusted_client_mime(
    client: TestClient, user: User, engine
) -> None:  # type: ignore[no-untyped-def]
    headers = login(client, user.username)
    browser_mime = "application/x-browser-fit-" + "x" * 120
    valid = client.post(
        "/api/v1/imports/fit",
        files={"file": ("browser-upload.fit", FIT_FIXTURE.read_bytes(), browser_mime)},
        headers=headers,
    )
    assert valid.status_code == 201
    assert valid.json()["status"] == "complete"
    with Session(engine) as db:
        imported = db.get(ActivityImport, valid.json()["importId"])
        assert imported is not None
        assert imported.content_type == browser_mime[:100]


def test_partial_import_can_retry_and_stale_processing_can_recover(
    client: TestClient, user: User, engine, settings, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    parsed = parse_fit_file(FIT_FIXTURE, "run.fit")
    partial = replace(parsed, status="partial", warning_count=1)

    def parse_open_handle(source, _name):  # type: ignore[no-untyped-def]
        assert not isinstance(source, Path)
        return partial

    monkeypatch.setattr("trainlab.services.activity_import.parse_fit_file", parse_open_handle)
    headers = login(client, user.username)
    created = upload_fixture(client, headers)
    assert created.status_code == 201
    assert created.json()["status"] == "partial"
    assert created.json()["retryAvailable"] is True
    import_id = created.json()["importId"]

    retried = client.post(f"/api/v1/imports/{import_id}/retry", headers=headers)
    assert retried.status_code == 200
    assert retried.json()["status"] == "partial"

    with Session(engine) as db:
        model = db.get(ActivityImport, import_id)
        assert model is not None
        model.status = "processing"
        model.last_attempt_at = datetime.now(UTC)
        db.commit()
    busy = client.post(f"/api/v1/imports/{import_id}/retry", headers=headers)
    assert busy.status_code == 409
    assert busy.json()["code"] == "import_in_progress"

    with Session(engine) as db:
        model = db.get(ActivityImport, import_id)
        assert model is not None
        model.last_attempt_at = datetime.now(UTC) - timedelta(
            minutes=settings.import_processing_stale_minutes + 1
        )
        db.commit()
    recovered = client.post(f"/api/v1/imports/{import_id}/retry", headers=headers)
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "partial"
    recovered_activity_id = recovered.json()["activity"]["id"]

    def fail_decode(_path, _name):  # type: ignore[no-untyped-def]
        raise FitDecodeFailure("fit_decode_failed", "FIT 文件无法解析")

    monkeypatch.setattr("trainlab.services.activity_import.parse_fit_file", fail_decode)
    failed_retry = client.post(f"/api/v1/imports/{import_id}/retry", headers=headers)
    assert failed_retry.status_code == 422
    assert failed_retry.json()["code"] == "fit_import_failed"
    assert client.get(f"/api/v1/activities/{recovered_activity_id}").status_code == 404
    assert client.get("/api/v1/activities").json()["items"] == []
    with Session(engine) as db:
        model = db.get(ActivityImport, import_id)
        assert model is not None
        assert model.status == "failed"
        assert db.scalar(select(func.count(Activity.id))) == 0


def test_missing_raw_file_fails_retry_and_source_returns_410(
    client: TestClient, user: User, engine, settings, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    parsed = replace(parse_fit_file(FIT_FIXTURE, "run.fit"), status="partial", warning_count=1)
    monkeypatch.setattr(
        "trainlab.services.activity_import.parse_fit_file", lambda _path, _name: parsed
    )
    headers = login(client, user.username)
    created = upload_fixture(client, headers)
    import_id = created.json()["importId"]
    activity_id = created.json()["activity"]["id"]
    with Session(engine) as db:
        model = db.get(ActivityImport, import_id)
        assert model is not None
        (settings.private_storage_root / model.storage_key).unlink()

    detail = client.get(f"/api/v1/activities/{activity_id}")
    assert detail.status_code == 200
    assert detail.json()["downloadAvailable"] is False
    assert detail.headers["cache-control"] == "private, no-store"
    source = client.get(f"/api/v1/activities/{activity_id}/source")
    assert source.status_code == 410
    assert source.json()["code"] == "raw_file_unavailable"
    assert source.headers["cache-control"] == "private, no-store"
    retried = client.post(f"/api/v1/imports/{import_id}/retry", headers=headers)
    assert retried.status_code == 422
    assert retried.json()["details"]["errorCode"] == "raw_file_unavailable"
    with Session(engine) as db:
        model = db.get(ActivityImport, import_id)
        assert model is not None
        assert model.status == "failed"
        assert db.scalar(select(func.count(Activity.id))) == 0


def test_source_download_pins_the_open_file_and_sanitizes_open_races(
    client: TestClient, user: User, settings, monkeypatch, caplog
) -> None:  # type: ignore[no-untyped-def]
    headers = login(client, user.username)
    created = upload_fixture(client, headers)
    activity_id = created.json()["activity"]["id"]

    from trainlab.services.activity_storage import PrivateActivityStorage

    original_open = PrivateActivityStorage.open_for_read

    def open_then_unlink(self, key, expected_user_id):  # type: ignore[no-untyped-def]
        handle = original_open(self, key, expected_user_id)
        self.path_for_key(key, expected_user_id).unlink()
        return handle

    monkeypatch.setattr(PrivateActivityStorage, "open_for_read", open_then_unlink)
    streamed = client.get(f"/api/v1/activities/{activity_id}/source")
    assert streamed.status_code == 200
    assert streamed.content == FIT_FIXTURE.read_bytes()
    assert str(settings.private_storage_root) not in caplog.text

    monkeypatch.setattr(PrivateActivityStorage, "open_for_read", original_open)
    sentinel = "SECRET_DOWNLOAD_RACE_PATH"
    real_os_open = os.open

    def fail_os_open(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if str(path).endswith(".fit"):
            raise OSError(f"{sentinel}/{settings.private_storage_root}/private.fit")
        return real_os_open(path, *args, **kwargs)

    monkeypatch.setattr("trainlab.services.activity_storage.os.open", fail_os_open)
    unavailable = client.get(f"/api/v1/activities/{activity_id}/source")
    assert unavailable.status_code == 410
    assert unavailable.json()["code"] == "raw_file_unavailable"
    assert sentinel not in unavailable.text
    assert sentinel not in caplog.text
    assert str(settings.private_storage_root) not in unavailable.text


def test_late_private_stream_failure_is_detectable_sanitized_and_closes_handle() -> None:
    sentinel = "SECRET_LATE_READ_PATH"

    class FailingHandle:
        def __init__(self) -> None:
            self.calls = 0
            self.closed = False

        def read(self, _size: int) -> bytes:
            self.calls += 1
            if self.calls == 1:
                return b"abc"
            raise OSError(f"{sentinel}/private.fit")

        def close(self) -> None:
            self.closed = True

    handle = FailingHandle()
    with pytest.raises(PrivateFitStreamError) as caught:
        list(_stream_private_fit(handle, 6))  # type: ignore[arg-type]

    assert sentinel not in str(caught.value)
    assert caught.value.__suppress_context__ is True
    assert handle.closed is True


def test_activity_list_uses_an_opaque_stable_cursor(client: TestClient, user: User, engine) -> None:  # type: ignore[no-untyped-def]
    with Session(engine) as db:
        for index in range(3):
            import_id = uuid.uuid4()
            imported = ActivityImport(
                id=import_id,
                user_id=user.id,
                source="fit_upload",
                original_filename=f"seed-{index}.fit",
                content_type="application/vnd.ant.fit",
                size_bytes=10,
                sha256=f"{index:064x}",
                storage_key=f"{user.id}/{import_id}.fit",
                status="complete",
                parser_name="test",
                parser_version="1",
                attempt_count=1,
                warning_count=0,
                replay_metadata={},
            )
            db.add(imported)
            db.flush()
            db.add(
                Activity(
                    user_id=user.id,
                    source_import_id=import_id,
                    title=f"seed-{index}",
                    sport="running",
                    sub_sport="generic",
                    profile="run",
                    start_time_utc=datetime(2026, 1, index + 1, tzinfo=UTC),
                    total_timer_time_sec=600,
                    total_elapsed_time_sec=600,
                    total_distance_m=1000,
                    extra_metrics={},
                )
            )
        db.commit()
    headers = login(client, user.username)
    first = client.get("/api/v1/activities?limit=2", headers=headers)
    assert first.status_code == 200
    assert [item["name"] for item in first.json()["items"]] == ["seed-2", "seed-1"]
    assert all(item["avgHr"] is None for item in first.json()["items"])
    cursor = first.json()["nextCursor"]
    assert cursor and "2026" not in cursor
    second = client.get(f"/api/v1/activities?limit=2&cursor={cursor}", headers=headers)
    assert second.status_code == 200
    assert [item["name"] for item in second.json()["items"]] == ["seed-0"]
    invalid = client.get("/api/v1/activities?cursor=not-a-cursor", headers=headers)
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "invalid_cursor"
    naive = base64.urlsafe_b64encode(f"2026-01-02T00:00:00|{uuid.uuid4()}".encode()).decode()
    naive_response = client.get(f"/api/v1/activities?cursor={naive}", headers=headers)
    assert naive_response.status_code == 422
    assert naive_response.json()["code"] == "invalid_cursor"


def test_list_type_comes_from_fit_sport_not_detail_profile(
    client: TestClient, user: User, engine
) -> None:  # type: ignore[no-untyped-def]
    with Session(engine) as db:
        for index, (sport, sub_sport, profile, expected) in enumerate(
            [
                ("swimming", "lap_swimming", "generic", "游泳"),
                ("running", "trail", "hike", "越野跑"),
            ]
        ):
            import_id = uuid.uuid4()
            imported = ActivityImport(
                id=import_id,
                user_id=user.id,
                source="fit_upload",
                original_filename=f"{expected}.fit",
                content_type="application/vnd.ant.fit",
                size_bytes=10,
                sha256=f"{index + 10:064x}",
                storage_key=f"{user.id}/{import_id}.fit",
                status="complete",
                parser_name="test",
                parser_version="1",
                attempt_count=1,
                warning_count=0,
                replay_metadata={},
            )
            db.add(imported)
            db.flush()
            db.add(
                Activity(
                    user_id=user.id,
                    source_import_id=import_id,
                    title=expected,
                    sport=sport,
                    sub_sport=sub_sport,
                    profile=profile,
                    start_time_utc=datetime(2026, 2, index + 1, tzinfo=UTC),
                    total_timer_time_sec=600,
                    total_elapsed_time_sec=600,
                    total_distance_m=1000,
                    extra_metrics={},
                )
            )
        db.commit()

    headers = login(client, user.username)
    items = client.get("/api/v1/activities", headers=headers).json()["items"]
    assert {(item["name"], item["type"], item["profile"]) for item in items} == {
        ("游泳", "游泳", "generic"),
        ("越野跑", "越野跑", "hike"),
    }


def test_persistence_failure_is_sanitized_and_marks_the_import_failed(
    client: TestClient, user: User, engine, monkeypatch, caplog
) -> None:  # type: ignore[no-untyped-def]
    sentinel = "SECRET_GPS_AND_PATH_SENTINEL"

    def fail_persistence(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError(f"{sentinel}/private.fit")

    monkeypatch.setattr("trainlab.services.activity_import._replace_activity", fail_persistence)
    headers = login(client, user.username)
    response = upload_fixture(client, headers)

    assert response.status_code == 500
    assert response.json()["code"] == "fit_persistence_failed"
    assert sentinel not in response.text
    assert sentinel not in caplog.text
    with Session(engine) as db:
        assert db.scalar(select(ActivityImport.status)) == "failed"
        assert db.scalar(select(func.count(Activity.id))) == 0


def test_unexpected_parser_failure_is_sanitized_and_never_stays_processing(
    client: TestClient, user: User, engine, monkeypatch, caplog
) -> None:  # type: ignore[no-untyped-def]
    sentinel = "SECRET_PARSER_GPS_PATH_SENTINEL"

    def fail_parser(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError(f"{sentinel}/private.fit")

    monkeypatch.setattr("trainlab.services.activity_import.parse_fit_file", fail_parser)
    headers = login(client, user.username)
    response = upload_fixture(client, headers)

    assert response.status_code == 500
    assert response.json()["code"] == "fit_parse_failed"
    assert sentinel not in response.text
    assert sentinel not in caplog.text
    with Session(engine) as db:
        imported = db.scalar(select(ActivityImport))
        assert imported is not None
        assert imported.status == "failed"
        assert imported.error_code == "fit_parse_failed"
