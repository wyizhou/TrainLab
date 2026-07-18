import hashlib
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from trainlab.db.models.activity import Activity, ActivityImport, ActivitySegment
from trainlab.db.models.user import User
from trainlab.importers.fit import parse_fit_file
from trainlab.services.activity_import import ImportStateError, replay_import
from trainlab.services.activity_metadata import update_activity_name
from trainlab.services.activity_reparse import ActivityReparseError, reparse_fit_imports
from trainlab.services.activity_storage import PrivateActivityStorage
from trainlab.services.import_management import DeleteTarget, delete_user_import

FIT_FIXTURE = (
    Path(__file__).parents[3] / "frontend" / "tests" / "fixtures" / "614797758_ACTIVITY.fit"
)


def _seed_import(
    engine,  # type: ignore[no-untyped-def]
    storage: PrivateActivityStorage,
    user: User,
    payload: bytes,
    *,
    title_override: str | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    import_id = uuid.uuid4()
    storage_key = f"{user.id}/{import_id}.fit"
    path = storage.path_for_key(storage_key, user.id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(payload)
    path.chmod(0o600)
    imported = ActivityImport(
        id=import_id,
        user_id=user.id,
        source="fit_upload",
        original_filename="private.fit",
        content_type="application/vnd.ant.fit",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        storage_key=storage_key,
        status="complete",
        parser_name="older-parser",
        parser_version="0",
        attempt_count=1,
        warning_count=0,
        title_override=title_override,
        replay_metadata={"source": "fit_upload"},
    )
    activity = Activity(
        user_id=user.id,
        source_import_id=import_id,
        title="Old projection",
        sport="generic",
        sub_sport="generic",
        profile="generic",
        start_time_utc=parse_fit_file(FIT_FIXTURE, "fixture.fit").start_time_utc,
        total_timer_time_sec=1,
        total_elapsed_time_sec=1,
        total_distance_m=0,
    )
    with Session(engine) as db:
        db.add(imported)
        db.flush()
        db.add(activity)
        db.commit()
        return imported.id, activity.id


def _wait_for_postgres_lock(engine, pid: int, done: threading.Event) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + 10
    with engine.connect() as observer:
        while time.monotonic() < deadline:
            wait_type = observer.scalar(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": pid},
            )
            if wait_type == "Lock":
                return
            if done.is_set():
                raise AssertionError("contending transaction completed before waiting on a lock")
    raise AssertionError("contending transaction did not enter a PostgreSQL lock wait")


def _start_reparse_holding_projection_locks(
    engine,  # type: ignore[no-untyped-def]
    storage: PrivateActivityStorage,
    user: User,
    import_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[threading.Thread, threading.Event, list[BaseException]]:
    from trainlab.services.activity_import import replace_activity_projection_in_place

    locks_held = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def hold_locks(db, imported, activity, parsed):  # type: ignore[no-untyped-def]
        locks_held.set()
        if not release.wait(timeout=10):
            raise AssertionError("test did not release reparse transaction")
        replace_activity_projection_in_place(db, imported, activity, parsed)

    monkeypatch.setattr(
        "trainlab.services.activity_reparse.replace_activity_projection_in_place",
        hold_locks,
    )

    def run_reparse() -> None:
        try:
            with Session(engine) as db:
                reparse_fit_imports(db, storage, user.username, [import_id], apply=True)
        except BaseException as exc:  # pragma: no cover - surfaced by assertion
            errors.append(exc)

    thread = threading.Thread(target=run_reparse)
    thread.start()
    assert locks_held.wait(timeout=10)
    return thread, release, errors


def test_complete_reparse_defaults_to_dry_run_then_preserves_identity_and_override(
    engine, settings, user: User
) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(settings.private_storage_root)
    payload = FIT_FIXTURE.read_bytes()
    import_id, activity_id = _seed_import(
        engine, storage, user, payload, title_override="User title"
    )
    source_hash = hashlib.sha256(payload).hexdigest()

    with Session(engine) as db:
        imported_before = db.get(ActivityImport, import_id)
        activity_before = db.get(Activity, activity_id)
        assert imported_before is not None and activity_before is not None
        created_at = activity_before.created_at
        dry_run = reparse_fit_imports(db, storage, user.username, [import_id], apply=False)
        assert dry_run.applied is False
        assert dry_run.items[0].status == "ready"

    with Session(engine) as db:
        unchanged = db.get(ActivityImport, import_id)
        assert unchanged is not None
        assert unchanged.attempt_count == 1
        applied = reparse_fit_imports(db, storage, user.username, [import_id], apply=True)
        assert applied.applied is True
        assert applied.items[0].activity_id == activity_id

    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        activity = db.get(Activity, activity_id)
        assert imported is not None and activity is not None
        assert imported.user_id == user.id
        assert imported.title_override == "User title"
        assert imported.storage_key == f"{user.id}/{import_id}.fit"
        assert imported.sha256 == source_hash
        assert imported.processing_token is None
        assert imported.attempt_count == 2
        assert activity.id == activity_id
        assert activity.user_id == user.id
        assert activity.source_import_id == import_id
        assert activity.created_at == created_at
        assert db.scalar(select(func.count(ActivitySegment.id))) == 19
        first_segment = db.scalar(
            select(ActivitySegment).where(ActivitySegment.activity_id == activity_id)
        )
        assert first_segment is not None
        assert first_segment.extra_data["_trainlabSemantic"]["schemaVersion"] == 1
    opened = storage.open_for_read(f"{user.id}/{import_id}.fit", user.id)
    try:
        assert hashlib.sha256(opened.handle.read()).hexdigest() == source_hash
    finally:
        opened.handle.close()


def test_batch_reparse_rolls_back_every_projection_when_one_persistence_fails(
    engine, settings, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(settings.private_storage_root)
    first_import, first_activity = _seed_import(engine, storage, user, b"first")
    second_import, second_activity = _seed_import(engine, storage, user, b"second")
    parsed = parse_fit_file(FIT_FIXTURE, "fixture.fit")
    monkeypatch.setattr(
        "trainlab.services.activity_reparse.parse_fit_file",
        lambda _source, _name: parsed,
    )
    from trainlab.services.activity_import import replace_activity_projection_in_place

    calls = 0

    def fail_second(db, imported, activity, parsed_activity):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        replace_activity_projection_in_place(db, imported, activity, parsed_activity)
        if calls == 2:
            raise RuntimeError("synthetic persistence failure")

    monkeypatch.setattr(
        "trainlab.services.activity_reparse.replace_activity_projection_in_place",
        fail_second,
    )
    with Session(engine) as db, pytest.raises(ActivityReparseError) as raised:
        reparse_fit_imports(
            db,
            storage,
            user.username,
            [second_import, first_import],
            apply=True,
        )
    assert raised.value.code == "reparse_failed"
    with Session(engine) as db:
        assert db.get(Activity, first_activity).title == "Old projection"  # type: ignore[union-attr]
        assert db.get(Activity, second_activity).title == "Old projection"  # type: ignore[union-attr]
        attempts = db.scalars(
            select(ActivityImport.attempt_count).order_by(ActivityImport.id)
        ).all()
        assert attempts == [1, 1]
        assert db.scalar(select(func.count(ActivitySegment.id))) == 0


def test_three_import_batch_commits_once_and_preserves_every_identity(
    engine, settings, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(settings.private_storage_root)
    seeded = [
        _seed_import(engine, storage, user, payload, title_override=f"Override {index}")
        for index, payload in enumerate((b"one", b"two", b"three"), start=1)
    ]
    parsed = parse_fit_file(FIT_FIXTURE, "fixture.fit")
    monkeypatch.setattr(
        "trainlab.services.activity_reparse.parse_fit_file",
        lambda _source, _name: parsed,
    )

    with Session(engine) as db:
        report = reparse_fit_imports(
            db,
            storage,
            user.username,
            [item[0] for item in reversed(seeded)],
            apply=True,
        )
    assert report.applied is True
    assert {item.import_id for item in report.items} == {item[0] for item in seeded}
    with Session(engine) as db:
        for index, (import_id, activity_id) in enumerate(seeded, start=1):
            imported = db.get(ActivityImport, import_id)
            activity = db.get(Activity, activity_id)
            assert imported is not None and activity is not None
            assert imported.user_id == user.id
            assert imported.title_override == f"Override {index}"
            assert imported.processing_token is None
            assert activity.id == activity_id
            assert activity.source_import_id == import_id
            assert activity.user_id == user.id
            opened = storage.open_for_read(imported.storage_key, user.id)
            try:
                expected = (b"one", b"two", b"three")[index - 1]
                assert opened.handle.read() == expected
            finally:
                opened.handle.close()


def test_second_parse_failure_leaves_entire_batch_unchanged(
    engine, settings, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(settings.private_storage_root)
    seeded = [
        _seed_import(engine, storage, user, payload)
        for payload in (b"parse-one", b"parse-two", b"parse-three")
    ]
    parsed = parse_fit_file(FIT_FIXTURE, "fixture.fit")
    calls = 0

    def fail_second_parse(_source, _name):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic parse failure")
        return parsed

    monkeypatch.setattr("trainlab.services.activity_reparse.parse_fit_file", fail_second_parse)
    with Session(engine) as db, pytest.raises(ActivityReparseError) as raised:
        reparse_fit_imports(
            db,
            storage,
            user.username,
            [item[0] for item in seeded],
            apply=True,
        )
    assert raised.value.code == "fit_parse_failed"
    with Session(engine) as db:
        for import_id, activity_id in seeded:
            imported = db.get(ActivityImport, import_id)
            activity = db.get(Activity, activity_id)
            assert imported is not None and activity is not None
            assert imported.status == "complete"
            assert imported.attempt_count == 1
            assert activity.title == "Old projection"
        assert db.scalar(select(func.count(ActivitySegment.id))) == 0


@pytest.mark.parametrize("mutation", ["rename", "delete", "retry"])
def test_reparse_fences_concurrent_rename_delete_and_retry(
    engine,
    settings,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(settings.private_storage_root)
    import_id, activity_id = _seed_import(engine, storage, user, b"source")
    parsed = parse_fit_file(FIT_FIXTURE, "fixture.fit")

    def mutate_after_preflight(_source, _name):  # type: ignore[no-untyped-def]
        with Session(engine) as other:
            imported = other.get(ActivityImport, import_id)
            assert imported is not None
            if mutation == "rename":
                imported.title_override = "Concurrent title"
            elif mutation == "delete":
                imported.status = "deleting"
                imported.processing_token = None
            else:
                imported.status = "processing"
                imported.processing_token = uuid.uuid4()
            other.commit()
        return replace(parsed, title="New projection")

    monkeypatch.setattr("trainlab.services.activity_reparse.parse_fit_file", mutate_after_preflight)
    with Session(engine) as db, pytest.raises(ActivityReparseError) as raised:
        reparse_fit_imports(db, storage, user.username, [import_id], apply=True)
    assert raised.value.code == "import_changed_concurrently"
    with Session(engine) as db:
        activity = db.get(Activity, activity_id)
        imported = db.get(ActivityImport, import_id)
        assert activity is not None and imported is not None
        assert activity.title == "Old projection"
        assert imported.attempt_count == 1
        if mutation == "rename":
            assert imported.title_override == "Concurrent title"
        elif mutation == "delete":
            assert imported.status == "deleting"
        else:
            assert imported.status == "processing"
            assert imported.processing_token is not None


def test_real_rename_waits_for_reparse_import_then_activity_locks(
    engine, settings, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(settings.private_storage_root)
    import_id, activity_id = _seed_import(
        engine,
        storage,
        user,
        FIT_FIXTURE.read_bytes(),
        title_override="Before reparse",
    )
    reparse_thread, release, reparse_errors = _start_reparse_holding_projection_locks(
        engine, storage, user, import_id, monkeypatch
    )
    contender_done = threading.Event()
    pid_ready = threading.Event()
    contender_pid: list[int] = []
    contender_errors: list[BaseException] = []

    def rename() -> None:
        try:
            with Session(engine) as db:
                contender_pid.append(int(db.scalar(text("SELECT pg_backend_pid()"))))
                pid_ready.set()
                update_activity_name(db, user.id, activity_id, "After reparse")
        except BaseException as exc:  # pragma: no cover - surfaced by assertion
            contender_errors.append(exc)
        finally:
            contender_done.set()

    contender = threading.Thread(target=rename)
    contender.start()
    assert pid_ready.wait(timeout=10)
    _wait_for_postgres_lock(engine, contender_pid[0], contender_done)
    release.set()
    contender.join(timeout=10)
    reparse_thread.join(timeout=10)

    assert not contender.is_alive()
    assert not reparse_thread.is_alive()
    assert not contender_errors
    assert not reparse_errors
    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        activity = db.get(Activity, activity_id)
        assert imported is not None and activity is not None
        assert imported.title_override == "After reparse"
        assert activity.id == activity_id
        assert activity.source_import_id == import_id


def test_real_delete_waits_for_reparse_then_safely_removes_import(
    engine, settings, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(settings.private_storage_root)
    import_id, activity_id = _seed_import(engine, storage, user, FIT_FIXTURE.read_bytes())
    reparse_thread, release, reparse_errors = _start_reparse_holding_projection_locks(
        engine, storage, user, import_id, monkeypatch
    )
    contender_done = threading.Event()
    pid_ready = threading.Event()
    contender_pid: list[int] = []
    contender_errors: list[BaseException] = []

    def delete_import() -> None:
        try:
            with Session(engine) as db:
                contender_pid.append(int(db.scalar(text("SELECT pg_backend_pid()"))))
                pid_ready.set()
                delete_user_import(
                    db,
                    storage,
                    user.id,
                    DeleteTarget(import_id=import_id),
                    stale_minutes=15,
                )
        except BaseException as exc:  # pragma: no cover - surfaced by assertion
            contender_errors.append(exc)
        finally:
            contender_done.set()

    contender = threading.Thread(target=delete_import)
    contender.start()
    assert pid_ready.wait(timeout=10)
    _wait_for_postgres_lock(engine, contender_pid[0], contender_done)
    release.set()
    contender.join(timeout=10)
    reparse_thread.join(timeout=10)

    assert not contender.is_alive()
    assert not reparse_thread.is_alive()
    assert not contender_errors
    assert not reparse_errors
    with Session(engine) as db:
        assert db.get(ActivityImport, import_id) is None
        assert db.get(Activity, activity_id) is None


def test_real_replay_waits_for_reparse_then_rejects_completed_import(
    engine, settings, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(settings.private_storage_root)
    import_id, activity_id = _seed_import(
        engine,
        storage,
        user,
        FIT_FIXTURE.read_bytes(),
        title_override="Persistent title",
    )
    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        assert imported is not None
        imported.status = "partial"
        db.commit()
    reparse_thread, release, reparse_errors = _start_reparse_holding_projection_locks(
        engine, storage, user, import_id, monkeypatch
    )
    contender_done = threading.Event()
    pid_ready = threading.Event()
    contender_pid: list[int] = []
    replay_codes: list[str] = []
    contender_errors: list[BaseException] = []

    def replay() -> None:
        try:
            with Session(engine) as db:
                imported = db.get(ActivityImport, import_id)
                assert imported is not None
                contender_pid.append(int(db.scalar(text("SELECT pg_backend_pid()"))))
                pid_ready.set()
                replay_import(db, storage, imported, stale_minutes=15)
        except ImportStateError as exc:
            replay_codes.append(exc.code)
        except BaseException as exc:  # pragma: no cover - surfaced by assertion
            contender_errors.append(exc)
        finally:
            contender_done.set()

    contender = threading.Thread(target=replay)
    contender.start()
    assert pid_ready.wait(timeout=10)
    _wait_for_postgres_lock(engine, contender_pid[0], contender_done)
    release.set()
    contender.join(timeout=10)
    reparse_thread.join(timeout=10)

    assert not contender.is_alive()
    assert not reparse_thread.is_alive()
    assert not contender_errors
    assert not reparse_errors
    assert replay_codes == ["import_not_retryable"]
    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        activity = db.get(Activity, activity_id)
        assert imported is not None and activity is not None
        assert imported.status == "complete"
        assert imported.processing_token is None
        assert imported.title_override == "Persistent title"
        assert activity.id == activity_id
        assert activity.source_import_id == import_id


def test_reparse_rejects_cross_user_and_raw_file_mismatch(engine, settings, user: User) -> None:  # type: ignore[no-untyped-def]
    from conftest import create_test_user

    storage = PrivateActivityStorage(settings.private_storage_root)
    import_id, _ = _seed_import(engine, storage, user, b"source")
    other = create_test_user(engine, "another-user")
    with Session(engine) as db, pytest.raises(ActivityReparseError) as hidden:
        reparse_fit_imports(db, storage, other.username, [import_id], apply=False)
    assert hidden.value.code == "import_not_found"

    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        assert imported is not None
        imported.status = "failed"
        db.commit()
    with Session(engine) as db, pytest.raises(ActivityReparseError) as state:
        reparse_fit_imports(db, storage, user.username, [import_id], apply=False)
    assert state.value.code == "import_not_reparseable"
    with Session(engine) as db:
        imported = db.get(ActivityImport, import_id)
        assert imported is not None
        imported.status = "complete"
        db.commit()

    opened = storage.open_for_read(f"{user.id}/{import_id}.fit", user.id)
    opened.handle.close()
    storage.path_for_key(f"{user.id}/{import_id}.fit", user.id).write_bytes(b"changed")
    with Session(engine) as db, pytest.raises(ActivityReparseError) as mismatch:
        reparse_fit_imports(db, storage, user.username, [import_id], apply=False)
    assert mismatch.value.code == "raw_file_mismatch"
