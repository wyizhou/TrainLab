import asyncio
import os
import uuid
from io import BytesIO

import pytest
from fastapi import UploadFile

from trainlab.services.activity_storage import PrivateActivityStorage, StorageError


def _upload(payload: bytes = b"private payload") -> UploadFile:
    return UploadFile(filename="activity.fit", file=BytesIO(payload))


def test_isolated_stage_is_atomically_promoted_to_final_owner_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(tmp_path)
    user_id = uuid.uuid4()
    import_id = uuid.uuid4()
    staged = asyncio.run(storage.stage_isolated(_upload(), user_id, import_id, 1024))
    final_path = storage.path_for_key(staged.storage_key, user_id)

    assert staged.isolated is True
    assert staged.path == tmp_path / str(user_id) / ".staging" / f"{import_id}.fit.part"
    assert staged.path.exists()
    assert not final_path.exists()

    storage.promote(staged, user_id)
    assert not staged.path.exists()
    assert final_path.read_bytes() == b"private payload"


def test_cleanup_removes_only_unreferenced_generated_files(tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(tmp_path)
    user_id = uuid.uuid4()
    kept = asyncio.run(storage.stage(_upload(b"kept"), user_id, uuid.uuid4(), 1024))
    orphan = asyncio.run(storage.stage(_upload(b"orphan"), user_id, uuid.uuid4(), 1024))
    staging = asyncio.run(storage.stage_isolated(_upload(b"staging"), user_id, uuid.uuid4(), 1024))
    unrelated = tmp_path / str(user_id) / "notes.txt"
    unrelated.write_text("untouched", encoding="utf-8")

    count, size = storage.cleanup_user_orphans(user_id, {kept.storage_key})

    assert count == 2
    assert size == len(b"orphan") + len(b"staging")
    assert kept.path.exists()
    assert not orphan.path.exists()
    assert not staging.path.exists()
    assert unrelated.read_text(encoding="utf-8") == "untouched"


def test_promotion_never_overwrites_an_existing_final_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(tmp_path)
    user_id = uuid.uuid4()
    import_id = uuid.uuid4()
    existing = asyncio.run(storage.stage(_upload(b"existing"), user_id, import_id, 1024))
    staged = asyncio.run(storage.stage_isolated(_upload(b"replacement"), user_id, import_id, 1024))

    with pytest.raises(StorageError) as caught:
        storage.promote(staged, user_id)

    assert caught.value.code == "private_storage_unavailable"
    assert existing.path.read_bytes() == b"existing"
    assert staged.path.read_bytes() == b"replacement"


def test_promotion_removes_final_link_when_staging_unlink_fails(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(tmp_path)
    user_id = uuid.uuid4()
    import_id = uuid.uuid4()
    staged = asyncio.run(storage.stage_isolated(_upload(), user_id, import_id, 1024))
    final_path = storage.path_for_key(staged.storage_key, user_id)
    real_unlink = os.unlink

    def fail_staging_unlink(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if str(path).endswith(".fit.part"):
            raise OSError("injected staging unlink failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr("trainlab.services.activity_storage.os.unlink", fail_staging_unlink)

    with pytest.raises(StorageError) as caught:
        storage.promote(staged, user_id)

    assert caught.value.code == "private_storage_unavailable"
    assert not final_path.exists()
    assert staged.path.read_bytes() == b"private payload"


def test_promotion_removes_final_link_when_directory_fsync_fails(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(tmp_path)
    user_id = uuid.uuid4()
    import_id = uuid.uuid4()
    staged = asyncio.run(storage.stage_isolated(_upload(), user_id, import_id, 1024))
    final_path = storage.path_for_key(staged.storage_key, user_id)

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("injected directory fsync failure")

    monkeypatch.setattr("trainlab.services.activity_storage.os.fsync", fail_fsync)

    with pytest.raises(StorageError) as caught:
        storage.promote(staged, user_id)

    assert caught.value.code == "private_storage_unavailable"
    assert not final_path.exists()
    assert not staged.path.exists()


def test_generated_file_scan_exposes_no_absolute_path_and_tracks_mtime(tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(tmp_path)
    user_id = uuid.uuid4()
    staged = asyncio.run(storage.stage_isolated(_upload(), user_id, uuid.uuid4(), 1024))
    os.utime(staged.path, (1, 1))

    candidate = storage.generated_files(user_id)[0]
    assert candidate.isolated is True
    assert candidate.storage_key is None
    assert candidate.filename.endswith(".fit.part")
    assert "path" not in repr(candidate).lower()
