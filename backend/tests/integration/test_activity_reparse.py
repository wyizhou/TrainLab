import hashlib
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trainlab.db.models.activity import Activity, ActivityImport, ActivitySegment
from trainlab.db.models.user import User
from trainlab.importers.fit import parse_fit_file
from trainlab.services.activity_reparse import ActivityReparseError, reparse_fit_imports
from trainlab.services.activity_storage import PrivateActivityStorage

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
