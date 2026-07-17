import asyncio
import os
import uuid
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile

from trainlab.services.activity_storage import PrivateActivityStorage, StorageError


def test_storage_key_never_uses_the_untrusted_filename(tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(tmp_path)
    user_id = uuid.uuid4()
    import_id = uuid.uuid4()
    upload = UploadFile(filename="../../private.fit", file=BytesIO(b"safe payload"))

    staged = asyncio.run(storage.stage(upload, user_id, import_id, 1024))

    assert staged.storage_key == f"{user_id}/{import_id}.fit"
    assert staged.path == tmp_path / str(user_id) / f"{import_id}.fit"
    assert staged.path.read_bytes() == b"safe payload"
    assert os.stat(tmp_path).st_mode & 0o777 == 0o700
    assert os.stat(staged.path.parent).st_mode & 0o777 == 0o700
    assert os.stat(staged.path).st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "key",
    ["../escape.fit", "user/file.fit", "/tmp/file.fit", "a/b/c.fit", "a/b.txt"],
)
def test_storage_rejects_traversal_and_non_generated_keys(tmp_path, key: str) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(tmp_path)

    with pytest.raises(StorageError, match="路径"):
        storage.path_for_key(key, uuid.uuid4())


def test_storage_rejects_a_valid_key_owned_by_another_user(tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(tmp_path)
    owner_id = uuid.uuid4()
    peer_id = uuid.uuid4()

    with pytest.raises(StorageError, match="路径"):
        storage.path_for_key(f"{peer_id}/{uuid.uuid4()}.fit", owner_id)


def test_storage_removes_partial_file_when_limit_is_exceeded(tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(tmp_path)
    upload = UploadFile(filename="large.fit", file=BytesIO(b"12345"))

    with pytest.raises(StorageError, match="大小"):
        asyncio.run(storage.stage(upload, uuid.uuid4(), uuid.uuid4(), 4))

    assert list(tmp_path.rglob("*.fit")) == []


def test_storage_rejects_an_empty_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(tmp_path)
    upload = UploadFile(filename="empty.fit", file=BytesIO(b""))

    with pytest.raises(StorageError, match="为空"):
        asyncio.run(storage.stage(upload, uuid.uuid4(), uuid.uuid4(), 1024))

    assert list(tmp_path.rglob("*.fit")) == []


def test_stage_exclusive_create_conflict_never_deletes_the_existing_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(tmp_path)
    user_id = uuid.uuid4()
    import_id = uuid.uuid4()
    first = asyncio.run(
        storage.stage(
            UploadFile(filename="first.fit", file=BytesIO(b"original private payload")),
            user_id,
            import_id,
            1024,
        )
    )

    with pytest.raises(StorageError):
        asyncio.run(
            storage.stage(
                UploadFile(filename="second.fit", file=BytesIO(b"replacement")),
                user_id,
                import_id,
                1024,
            )
        )

    assert first.path.read_bytes() == b"original private payload"


def test_storage_opens_an_owner_file_and_sanitizes_low_level_read_open_errors(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(tmp_path)
    user_id = uuid.uuid4()
    import_id = uuid.uuid4()
    staged = asyncio.run(
        storage.stage(
            UploadFile(filename="safe.fit", file=BytesIO(b"private payload")),
            user_id,
            import_id,
            1024,
        )
    )

    opened = storage.open_for_read(staged.storage_key, user_id)
    with opened.handle as handle:
        assert opened.size_bytes == len(b"private payload")
        assert handle.read() == b"private payload"

    sentinel = "SECRET_READ_PATH_SENTINEL"
    real_os_open = os.open

    def fail_open(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if str(path).endswith(".fit"):
            raise OSError(f"{sentinel}/private.fit")
        return real_os_open(path, *args, **kwargs)

    monkeypatch.setattr("trainlab.services.activity_storage.os.open", fail_open)
    with pytest.raises(StorageError) as caught:
        storage.open_for_read(staged.storage_key, user_id)

    assert caught.value.code == "raw_file_unavailable"
    assert sentinel not in str(caught.value)
    assert caught.value.__suppress_context__ is True


def test_storage_rejects_cross_user_file_and_parent_directory_symlinks(tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(tmp_path)
    owner_id = uuid.uuid4()
    peer_id = uuid.uuid4()
    owner_import_id = uuid.uuid4()
    peer_import_id = uuid.uuid4()
    peer = asyncio.run(
        storage.stage(
            UploadFile(filename="peer.fit", file=BytesIO(b"peer private payload")),
            peer_id,
            peer_import_id,
            1024,
        )
    )

    owner_directory = tmp_path / str(owner_id)
    owner_directory.mkdir(mode=0o700)
    owner_file = owner_directory / f"{owner_import_id}.fit"
    owner_file.symlink_to(peer.path)
    with pytest.raises(StorageError) as file_symlink:
        storage.open_for_read(f"{owner_id}/{owner_import_id}.fit", owner_id)
    assert file_symlink.value.code == "raw_file_unavailable"
    assert peer.path.read_bytes() == b"peer private payload"

    owner_file.unlink()
    owner_directory.rmdir()
    owner_directory.symlink_to(peer.path.parent, target_is_directory=True)
    with pytest.raises(StorageError) as directory_symlink:
        storage.open_for_read(f"{owner_id}/{peer_import_id}.fit", owner_id)
    assert directory_symlink.value.code == "raw_file_unavailable"
    assert peer.path.read_bytes() == b"peer private payload"


def test_storage_os_error_is_sanitized_without_a_path_context(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    storage = PrivateActivityStorage(tmp_path)
    upload = UploadFile(filename="safe.fit", file=BytesIO(b"payload"))
    sentinel = "SECRET_PATH_SENTINEL"

    def fail_open(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise OSError(f"{sentinel}/private.fit")

    monkeypatch.setattr("trainlab.services.activity_storage.os.open", fail_open)
    with pytest.raises(StorageError) as caught:
        asyncio.run(storage.stage(upload, uuid.uuid4(), uuid.uuid4(), 1024))

    assert caught.value.code == "private_storage_unavailable"
    assert sentinel not in str(caught.value)
    assert caught.value.__suppress_context__ is True


def test_storage_resolve_runtime_error_is_sanitized(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    sentinel = "SYMLINK_LOOP_SECRET_PATH"

    def fail_resolve(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError(f"{sentinel}/private.fit")

    monkeypatch.setattr("pathlib.Path.resolve", fail_resolve)
    with pytest.raises(StorageError) as caught:
        PrivateActivityStorage(tmp_path)

    assert caught.value.code == "private_storage_unavailable"
    assert sentinel not in str(caught.value)
    assert caught.value.__suppress_context__ is True


def test_storage_refuses_the_filesystem_root() -> None:
    with pytest.raises(StorageError) as caught:
        PrivateActivityStorage(Path("/"))

    assert caught.value.code == "private_storage_unavailable"
