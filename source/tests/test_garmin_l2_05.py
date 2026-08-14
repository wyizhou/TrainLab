from __future__ import annotations

import hashlib
import os
import shutil
import stat
from pathlib import Path

import pytest

from src.garmin import (
    GarminError,
    GarminRepository,
    SyncRequest,
    canonical_provider_json,
    validate_provider_json_payload,
)
from tests.fixtures.synthetic_fit import SYNTHETIC_FITS

from .test_garmin_l2_04 import _setup


def test_json_key_order_is_a_semantic_noop(tmp_path: Path) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    connection = repository.connect()
    projected: list[int] = []
    first = repository.archive(
        connection,
        "fixture_json",
        "object-1",
        b'{"b":2,"a":1}',
        "json",
        "application/json",
        projected.append,
    )
    second = repository.archive(
        connection,
        "fixture_json",
        "object-1",
        b'{"a":1,"b":2}',
        "json",
        "application/json",
        projected.append,
    )
    assert first[0] != second[0]
    assert first[1] == second[1]
    assert first[2] is True
    assert second[2] is False
    assert projected == [first[1]]
    assert (
        connection.execute(
            """SELECT count(*) FROM source_revisions
               WHERE resource_kind='fixture_json' AND provider_object_id='object-1'"""
        ).fetchone()[0]
        == 1
    )
    raw_rows = connection.execute(
        """SELECT sha256,relative_path FROM raw_objects
           WHERE resource_kind='fixture_json' ORDER BY id"""
    ).fetchall()
    assert len(raw_rows) == 2
    assert [
        (config.raw_root.parent / row["relative_path"]).read_bytes() for row in raw_rows
    ] == [b'{"b":2,"a":1}', b'{"a":1,"b":2}']
    semantic_hash = connection.execute(
        """SELECT payload_hash FROM source_revisions
           WHERE resource_kind='fixture_json' AND provider_object_id='object-1'"""
    ).fetchone()[0]
    assert semantic_hash == hashlib.sha256(b'{"a":1,"b":2}').hexdigest()
    assert semantic_hash == raw_rows[1]["sha256"]
    assert semantic_hash != raw_rows[0]["sha256"]
    connection.close()


@pytest.mark.parametrize(
    "payload",
    [
        b'{"a":1,"a":2}',
        b'{"nested":{"x":1,"x":2}}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":-Infinity}',
        b'\xef\xbb\xbf{"value":1}',
        b'{"value":"\xff"}',
        b'{"value":1} trailing',
        b'{"value":1}{"value":2}',
        b'"\\ud800"',
    ],
)
def test_strict_json_bytes_reject_ambiguity_nonfinite_encoding_and_trailing_data_without_artifacts(
    tmp_path: Path,
    payload: bytes,
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    with repository.connect() as connection:
        with pytest.raises(GarminError, match="provider_json_invalid") as caught:
            repository.archive(
                connection,
                "fixture_json",
                "strict-object",
                payload,
                "json",
                "application/json",
            )
        assert caught.value.code == "provider_json_invalid"
        assert connection.execute("SELECT count(*) FROM raw_objects").fetchone()[0] == 0
        assert (
            connection.execute("SELECT count(*) FROM source_revisions").fetchone()[0]
            == 0
        )
        assert (
            connection.execute("SELECT count(*) FROM source_field_catalog").fetchone()[
                0
            ]
            == 0
        )
    assert not list(config.raw_root.rglob(".tmp-*"))
    assert not list(config.raw_root.rglob("*.json"))


def test_provider_json_depth_width_node_and_byte_limits_have_exact_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)

    with monkeypatch.context() as scoped:
        scoped.setattr("src.garmin.PROVIDER_JSON_MAX_DEPTH", 2)
        assert canonical_provider_json({"a": {"b": 1}}) == b'{"a":{"b":1}}'
        with pytest.raises(GarminError, match="provider_json_invalid"):
            canonical_provider_json({"a": {"b": {"c": 1}}})

    with monkeypatch.context() as scoped:
        scoped.setattr("src.garmin.PROVIDER_JSON_MAX_CONTAINER_ITEMS", 2)
        assert canonical_provider_json({"a": 1, "b": 2}) == b'{"a":1,"b":2}'
        with pytest.raises(GarminError, match="provider_json_invalid"):
            canonical_provider_json({"a": 1, "b": 2, "c": 3})
        with pytest.raises(GarminError, match="provider_json_invalid"):
            canonical_provider_json([1, 2, 3])

    with monkeypatch.context() as scoped:
        scoped.setattr("src.garmin.PROVIDER_JSON_MAX_NODES", 3)
        assert canonical_provider_json([1, 2]) == b"[1,2]"
        with pytest.raises(GarminError, match="provider_json_invalid"):
            canonical_provider_json([1, 2, 3])

    with monkeypatch.context() as scoped:
        scoped.setattr("src.garmin.PROVIDER_JSON_MAX_BYTES", 7)
        with repository.connect() as connection:
            repository.archive(
                connection,
                "fixture_json",
                "byte-limit",
                b'{"a":1}',
                "json",
                "application/json",
            )
            with pytest.raises(GarminError, match="provider_json_invalid"):
                repository.archive(
                    connection,
                    "fixture_json",
                    "byte-limit-over",
                    b'{"a":1} ',
                    "json",
                    "application/json",
                )
    with repository.connect(readonly=True) as connection:
        assert connection.execute("SELECT count(*) FROM raw_objects").fetchone()[0] == 1
        assert (
            connection.execute("SELECT count(*) FROM source_revisions").fetchone()[0]
            == 1
        )


def test_python_provider_json_rejects_unsupported_types_keys_nonfinite_and_cycles() -> (
    None
):
    class DictSubclass(dict):
        pass

    class CustomValue:
        def __str__(self) -> str:
            return "MUST_NOT_STRINGIFY"

    recursive: list[object] = []
    recursive.append(recursive)
    invalid_values = [
        {"value": CustomValue()},
        {"value": (1, 2)},
        {"value": {1, 2}},
        {1: "numeric-key"},
        {"value": float("nan")},
        {"value": float("inf")},
        DictSubclass(value=1),
        recursive,
    ]
    for value in invalid_values:
        with pytest.raises(GarminError, match="provider_json_invalid"):
            validate_provider_json_payload(value)
        with pytest.raises(GarminError, match="provider_json_invalid"):
            canonical_provider_json(value)


def test_changed_payload_increments_revision_and_keeps_one_current(
    tmp_path: Path,
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    connection = repository.connect()
    repository.archive(
        connection,
        "fixture_json",
        "object-1",
        b'{"value":1}',
        "json",
        "application/json",
    )
    repository.archive(
        connection,
        "fixture_json",
        "object-1",
        b'{"value":2}',
        "json",
        "application/json",
    )
    rows = connection.execute(
        """SELECT revision_no,is_current FROM source_revisions
           WHERE resource_kind='fixture_json' AND provider_object_id='object-1'
           ORDER BY revision_no"""
    ).fetchall()
    assert [tuple(row) for row in rows] == [(1, 0), (2, 1)]
    connection.close()


def test_projector_failure_keeps_raw_and_old_canonical_current(tmp_path: Path) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    connection = repository.connect()

    def initial_projector(_: int) -> None:
        repository.fields(connection, "fixture_json", {"sentinel": 1})

    _, old_revision, _ = repository.archive(
        connection,
        "fixture_json",
        "object-1",
        b'{"value":1}',
        "json",
        "application/json",
        initial_projector,
    )

    def failing_projector(_: int) -> None:
        repository.fields(connection, "fixture_json", {"must_rollback": 2})
        raise RuntimeError("projector failed")

    with pytest.raises(RuntimeError, match="projector failed"):
        repository.archive(
            connection,
            "fixture_json",
            "object-1",
            b'{"value":2}',
            "json",
            "application/json",
            failing_projector,
        )

    current = connection.execute(
        """SELECT id FROM source_revisions
           WHERE resource_kind='fixture_json' AND provider_object_id='object-1'
             AND is_current=1"""
    ).fetchone()
    assert current["id"] == old_revision
    assert (
        connection.execute(
            """SELECT count(*) FROM source_field_catalog
               WHERE resource_kind='fixture_json' AND field_path='/must_rollback'"""
        ).fetchone()[0]
        == 0
    )
    assert (
        connection.execute(
            "SELECT count(*) FROM raw_objects WHERE resource_kind='fixture_json'"
        ).fetchone()[0]
        == 2
    )
    connection.close()


def test_create_only_publication_failure_leaves_no_partial_or_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)

    def fail_link(*_: object, **__: object) -> None:
        raise OSError("simulated create-only interruption")

    monkeypatch.setattr("src.garmin.os.link", fail_link)
    with pytest.raises(OSError, match="simulated create-only interruption"):
        repository.store_raw(
            "fixture_json",
            b'{"value":1}',
            "json",
            "application/json",
        )
    assert not list(config.raw_root.rglob(".tmp-*"))
    assert not list(config.raw_root.rglob("*.json"))
    with repository.connect() as connection:
        assert connection.execute("SELECT count(*) FROM raw_objects").fetchone()[0] == 0


def test_raw_write_fsyncs_file_and_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    original_fsync = os.fsync
    fsync_kinds: list[str] = []

    def observe_fsync(fd: int) -> None:
        mode = os.fstat(fd).st_mode
        fsync_kinds.append("directory" if stat.S_ISDIR(mode) else "file")
        original_fsync(fd)

    monkeypatch.setattr("src.garmin.os.fsync", observe_fsync)
    raw_id, _ = repository.store_raw(
        "fixture_json",
        b'{"value":1}',
        "json",
        "application/json",
    )
    assert {"file", "directory"}.issubset(fsync_kinds)
    with repository.connect(readonly=True) as connection:
        relative = connection.execute(
            "SELECT relative_path FROM raw_objects WHERE id=?",
            (raw_id,),
        ).fetchone()[0]
    stored = config.raw_root.parent / relative
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600


def test_raw_rejects_insecure_directory_or_file_permissions(tmp_path: Path) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    os.chmod(config.raw_root, 0o755)
    with pytest.raises(ValueError, match="unsafe_raw_path"):
        repository.store_raw("fixture_json", b'{"value":1}', "json", "application/json")
    os.chmod(config.raw_root, 0o700)
    raw_id, _ = repository.store_raw(
        "fixture_json", b'{"value":1}', "json", "application/json"
    )
    with repository.connect(readonly=True) as connection:
        relative = connection.execute(
            "SELECT relative_path FROM raw_objects WHERE id=?", (raw_id,)
        ).fetchone()[0]
    os.chmod(config.raw_root.parent / relative, 0o644)
    with pytest.raises(ValueError, match="raw_object_corrupt"):
        repository.store_raw("fixture_json", b'{"value":1}', "json", "application/json")


def test_raw_create_only_race_and_directory_fsync_failure_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    original_link = os.link

    def competing_link(source: str, destination: str, **kwargs: object) -> None:
        original_link(source, destination, **kwargs)
        raise FileExistsError

    monkeypatch.setattr("src.garmin.os.link", competing_link)
    raw_id, _ = repository.store_raw(
        "fixture_json", b'{"race":1}', "json", "application/json"
    )
    assert raw_id > 0

    original_fsync = os.fsync

    def fail_directory_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("directory fsync failed")
        original_fsync(fd)

    monkeypatch.setattr("src.garmin.os.fsync", fail_directory_fsync)
    with pytest.raises(OSError, match="directory fsync failed"):
        repository.store_raw("fixture_json", b'{"fsync":1}', "json", "application/json")
    with repository.connect(readonly=True) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM raw_objects WHERE sha256!=?", ("",)
            ).fetchone()[0]
            == 1
        )


def test_new_child_directory_requires_parent_fsync_before_any_db_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    original_fsync = os.fsync

    def fail_first_directory_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("new child parent fsync failed")
        original_fsync(fd)

    monkeypatch.setattr("src.garmin.os.fsync", fail_first_directory_fsync)
    with pytest.raises(OSError, match="new child parent fsync failed"):
        repository.store_raw(
            "fixture_json", b'{"new_child":true}', "json", "application/json"
        )
    with repository.connect(readonly=True) as connection:
        assert connection.execute("SELECT count(*) FROM raw_objects").fetchone()[0] == 0


def test_cleanup_claim_preserves_replaced_temp_and_blocks_db_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    original_rename, original_write = os.rename, os.write
    replacements: list[str] = []

    def replace_old_temp(source: str, destination: str, **kwargs: object) -> None:
        original_rename(source, destination, **kwargs)
        if str(source).startswith(".tmp-"):
            directory_fd = int(kwargs["src_dir_fd"])
            fd = os.open(
                source, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=directory_fd
            )
            try:
                original_write(fd, b"unknown replacement")
            finally:
                os.close(fd)
            replacements.append(str(source))

    monkeypatch.setattr("src.garmin.os.rename", replace_old_temp)
    with pytest.raises(ValueError, match="raw_cleanup_temp_replaced"):
        repository.store_raw(
            "fixture_json", b'{"cleanup_race":true}', "json", "application/json"
        )
    assert replacements
    assert list(config.raw_root.rglob(replacements[0]))
    assert not list(config.raw_root.rglob(".cleanup-*"))
    with repository.connect(readonly=True) as connection:
        assert connection.execute("SELECT count(*) FROM raw_objects").fetchone()[0] == 0


def test_cleanup_claim_swap_is_preserved_and_blocks_db_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    original_rename, original_write = os.rename, os.write
    claims: list[str] = []

    def replace_claim(source: str, destination: str, **kwargs: object) -> None:
        original_rename(source, destination, **kwargs)
        if str(destination).startswith(".cleanup-"):
            directory_fd = int(kwargs["dst_dir_fd"])
            os.unlink(destination, dir_fd=directory_fd)
            fd = os.open(
                destination,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
                dir_fd=directory_fd,
            )
            try:
                original_write(fd, b"unknown cleanup claim")
            finally:
                os.close(fd)
            claims.append(str(destination))

    monkeypatch.setattr("src.garmin.os.rename", replace_claim)
    with pytest.raises(ValueError, match="raw_cleanup_claim_replaced"):
        repository.store_raw(
            "fixture_json", b'{"claim_race":true}', "json", "application/json"
        )
    assert claims and list(config.raw_root.rglob(claims[0]))
    with repository.connect(readonly=True) as connection:
        assert connection.execute("SELECT count(*) FROM raw_objects").fetchone()[0] == 0


def test_loser_accepts_same_content_and_rejects_different_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    original_link, original_write = os.link, os.write

    def same_content_loser(source: str, destination: str, **kwargs: object) -> None:
        original_link(source, destination, **kwargs)
        raise FileExistsError

    monkeypatch.setattr("src.garmin.os.link", same_content_loser)
    assert (
        repository.store_raw(
            "fixture_json", b'{"loser":1}', "json", "application/json"
        )[0]
        > 0
    )
    monkeypatch.undo()
    original_link = os.link

    def different_content_loser(
        source: str, destination: str, **kwargs: object
    ) -> None:
        original_link(source, destination, **kwargs)
        directory_fd = int(kwargs["dst_dir_fd"])
        os.unlink(destination, dir_fd=directory_fd)
        fd = os.open(
            destination,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
            dir_fd=directory_fd,
        )
        try:
            original_write(fd, b'{"different":1}')
        finally:
            os.close(fd)
        raise FileExistsError

    monkeypatch.setattr("src.garmin.os.link", different_content_loser)
    with pytest.raises(ValueError, match="raw_object_corrupt"):
        repository.store_raw("fixture_json", b'{"loser":2}', "json", "application/json")
    with repository.connect(readonly=True) as connection:
        assert connection.execute("SELECT count(*) FROM raw_objects").fetchone()[0] == 1


def test_winner_requires_final_device_and_inode_match_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    original_fstat, original_link, original_write = os.fstat, os.link, os.write
    temp_fd: int | None = None
    published = False
    final_regular_fstats = 0

    def capture_temp(fd: int, data: bytes) -> int:
        nonlocal temp_fd
        temp_fd = fd
        return original_write(fd, data)

    def publish(source: str, destination: str, **kwargs: object) -> None:
        nonlocal published
        original_link(source, destination, **kwargs)
        published = True

    def spoof_final_device(fd: int):
        nonlocal final_regular_fstats
        info = original_fstat(fd)
        if published and fd != temp_fd and stat.S_ISREG(info.st_mode):
            final_regular_fstats += 1
            # The second post-publish final-file fstat is ``final_stat``;
            # _verify_filefd has already performed the content check.
            if final_regular_fstats == 2:
                values = list(info)
                values[2] = info.st_dev + 1
                return os.stat_result(values)
        return info

    monkeypatch.setattr("src.garmin.os.write", capture_temp)
    monkeypatch.setattr("src.garmin.os.link", publish)
    monkeypatch.setattr("src.garmin.os.fstat", spoof_final_device)
    with pytest.raises(ValueError, match="raw_object_corrupt"):
        repository.store_raw(
            "fixture_json", b'{"device":1}', "json", "application/json"
        )
    with repository.connect(readonly=True) as connection:
        assert connection.execute("SELECT count(*) FROM raw_objects").fetchone()[0] == 0


def test_db_transaction_failure_keeps_final_raw_but_no_raw_object_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    monkeypatch.setattr(
        repository,
        "_open_relative_rawfd",
        lambda _relative: (_ for _ in ()).throw(ValueError("verification failed")),
    )
    with pytest.raises(ValueError, match="verification failed"):
        repository.store_raw(
            "fixture_json", b'{"db_rollback":true}', "json", "application/json"
        )
    assert list(config.raw_root.rglob("*.json"))
    with repository.connect(readonly=True) as connection:
        assert connection.execute("SELECT count(*) FROM raw_objects").fetchone()[0] == 0


def test_raw_short_write_loops_and_zero_or_write_errors_leave_no_db_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    original_write = os.write
    calls = 0

    def partial_write(fd: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        return original_write(fd, data[: max(1, len(data) // 2)])

    monkeypatch.setattr("src.garmin.os.write", partial_write)
    repository.store_raw(
        "fixture_json", b'{"partial":true}', "json", "application/json"
    )
    assert calls >= 2

    monkeypatch.setattr("src.garmin.os.write", lambda _fd, _data: 0)
    with pytest.raises(OSError, match="raw_short_write"):
        repository.store_raw(
            "fixture_json", b'{"zero":true}', "json", "application/json"
        )
    monkeypatch.setattr(
        "src.garmin.os.write",
        lambda _fd, _data: (_ for _ in ()).throw(OSError("write failed")),
    )
    with pytest.raises(OSError, match="write failed"):
        repository.store_raw(
            "fixture_json", b'{"write":true}', "json", "application/json"
        )
    with repository.connect(readonly=True) as connection:
        assert connection.execute("SELECT count(*) FROM raw_objects").fetchone()[0] == 1
    assert not list(config.raw_root.rglob(".tmp-*"))


def test_raw_file_fsync_failure_leaves_no_db_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    original_fsync = os.fsync

    def fail_file_fsync(fd: int) -> None:
        if stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("file fsync failed")
        original_fsync(fd)

    monkeypatch.setattr("src.garmin.os.fsync", fail_file_fsync)
    with pytest.raises(OSError, match="file fsync failed"):
        repository.store_raw(
            "fixture_json", b'{"fsync":true}', "json", "application/json"
        )
    with repository.connect(readonly=True) as connection:
        assert connection.execute("SELECT count(*) FROM raw_objects").fetchone()[0] == 0
    assert not list(config.raw_root.rglob(".tmp-*"))


@pytest.mark.parametrize("replacement", [b'{"wrong":true}', b'{"value":1}'])
def test_raw_rejects_final_name_swap_after_create_only_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: bytes
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    original_link = os.link

    def replace_winner(source: str, destination: str, **kwargs: object) -> None:
        original_link(source, destination, **kwargs)
        directory_fd = int(kwargs["dst_dir_fd"])
        os.unlink(destination, dir_fd=directory_fd)
        fd = os.open(
            destination,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
            dir_fd=directory_fd,
        )
        try:
            original_write = os.write
            original_write(fd, replacement)
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)

    monkeypatch.setattr("src.garmin.os.link", replace_winner)
    with pytest.raises(ValueError, match="raw_object_corrupt"):
        repository.store_raw("fixture_json", b'{"value":1}', "json", "application/json")
    with repository.connect(readonly=True) as connection:
        assert connection.execute("SELECT count(*) FROM raw_objects").fetchone()[0] == 0


def test_raw_rejects_final_name_symlink_swap_after_create_only_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    outside = tmp_path / "outside-final.json"
    outside.write_bytes(b'{"outside":true}')
    original_link = os.link

    def replace_winner_with_symlink(
        source: str, destination: str, **kwargs: object
    ) -> None:
        original_link(source, destination, **kwargs)
        directory_fd = int(kwargs["dst_dir_fd"])
        os.unlink(destination, dir_fd=directory_fd)
        # The absolute target is intentionally outside the raw root.  The
        # final O_NOFOLLOW/open+identity sequence must reject it before DB IO.
        os.symlink(str(outside), destination, dir_fd=directory_fd)

    monkeypatch.setattr("src.garmin.os.link", replace_winner_with_symlink)
    with pytest.raises(ValueError, match="raw_object_corrupt"):
        repository.store_raw("fixture_json", b'{"value":1}', "json", "application/json")
    with repository.connect(readonly=True) as connection:
        assert connection.execute("SELECT count(*) FROM raw_objects").fetchone()[0] == 0


def test_dirfd_anchor_rejects_parent_symlink_swap_after_root_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    outside = tmp_path / "outside"
    outside.mkdir()
    original_open_root = repository._open_raw_rootfd

    def swap_after_root_open() -> int:
        fd = original_open_root()
        shutil.rmtree(config.raw_root / "garmin")
        (config.raw_root / "garmin").symlink_to(outside, target_is_directory=True)
        return fd

    monkeypatch.setattr(repository, "_open_raw_rootfd", swap_after_root_open)
    with pytest.raises(ValueError, match="unsafe_raw_path"):
        repository.store_raw("fixture_json", b'{"swap":1}', "json", "application/json")
    assert not list(outside.iterdir())


def test_dirfd_anchor_rejects_root_swap_and_read_does_not_create_missing_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    shutil.rmtree(config.raw_root / "garmin", ignore_errors=True)
    with pytest.raises(ValueError, match="raw_object_corrupt"):
        repository._open_relative_rawfd("raw/garmin/json/2099/01/missing.json")
    assert not (config.raw_root / "garmin").exists()

    outside = tmp_path / "outside-root"
    outside.mkdir()
    original_open_root = repository._open_raw_rootfd

    def swap_root_after_open() -> int:
        fd = original_open_root()
        shutil.rmtree(config.raw_root)
        config.raw_root.symlink_to(outside, target_is_directory=True)
        return fd

    monkeypatch.setattr(repository, "_open_raw_rootfd", swap_root_after_open)
    with pytest.raises(ValueError, match="unsafe_raw_path"):
        repository.store_raw(
            "fixture_json", b'{"root_swap":true}', "json", "application/json"
        )
    assert not list(outside.iterdir())


def test_raw_repeated_reads_do_not_leak_file_descriptors(tmp_path: Path) -> None:
    if not Path("/dev/fd").is_dir():
        pytest.skip("platform has no /dev/fd")
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    baseline = len(os.listdir("/dev/fd"))
    for _ in range(32):
        repository.store_raw(
            "fixture_json", b'{"same":true}', "json", "application/json"
        )
    assert len(os.listdir("/dev/fd")) <= baseline + 2


def test_corrupt_registered_raw_and_symlink_escape_are_rejected(tmp_path: Path) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    raw_id, _ = repository.store_raw(
        "fixture_json",
        b'{"value":1}',
        "json",
        "application/json",
    )
    with repository.connect(readonly=True) as connection:
        relative = connection.execute(
            "SELECT relative_path FROM raw_objects WHERE id=?",
            (raw_id,),
        ).fetchone()[0]
    stored = config.raw_root.parent / relative
    stored.write_bytes(b'{"value":2}')
    with pytest.raises(ValueError, match="raw_object_corrupt"):
        repository.store_raw(
            "fixture_json",
            b'{"value":1}',
            "json",
            "application/json",
        )

    outside = tmp_path / "outside"
    outside.mkdir()
    garmin_root = config.raw_root / "garmin"
    shutil.rmtree(garmin_root)
    garmin_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="raw_object_corrupt"):
        GarminRepository(config).store_raw(
            "fixture_json",
            b'{"value":1}',
            "json",
            "application/json",
        )
    assert not list(outside.rglob("*"))


def test_all_json_fields_are_cataloged_and_fit_never_creates_zip(
    tmp_path: Path,
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    connection = repository.connect()
    payload = {
        "items": [
            {"first": 1},
            {"second": 2},
            {"third": 3},
            {"fourth": {"deep": 4}},
        ]
    }
    repository.fields(connection, "fixture_json", payload)
    assert (
        connection.execute(
            """SELECT count(*) FROM source_field_catalog
               WHERE resource_kind='fixture_json'
                 AND field_path='/items/*/fourth/deep'"""
        ).fetchone()[0]
        == 1
    )
    fit_bytes = SYNTHETIC_FITS["Running.fit"]
    repository.archive(
        connection,
        "activity_fit",
        "activity-1",
        fit_bytes,
        "fit",
        "application/octet-stream",
    )
    assert list(config.raw_root.rglob("*.fit"))
    assert not list(config.raw_root.rglob("*.zip"))
    connection.close()


def test_raw_json_and_fit_revisions_are_permanent_append_only_evidence(
    tmp_path: Path,
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    connection = repository.connect()
    json_versions = (
        b'{"calendarDate":"2026-04-15","value":1}',
        b'{"calendarDate":"2026-04-15","value":2}',
    )
    fit_versions = (
        b".FIT permanent raw revision one",
        b".FIT permanent raw revision two",
    )

    for payload in json_versions:
        repository.archive(
            connection,
            "steps",
            "garmin:steps:2026-04-15",
            payload,
            "json",
            "application/json",
        )
    for payload in fit_versions:
        repository.archive(
            connection,
            "activity_fit",
            "garmin:activity:permanent-fixture",
            payload,
            "fit",
            "application/octet-stream",
        )

    for resource, expected_payloads in (
        ("steps", json_versions),
        ("activity_fit", fit_versions),
    ):
        rows = list(
            connection.execute(
                """SELECT o.relative_path
                     FROM source_revisions AS r
                     JOIN raw_objects AS o ON o.id=r.raw_object_id
                    WHERE r.resource_kind=?
                    ORDER BY r.revision_no""",
                (resource,),
            )
        )
        assert len(rows) == 2
        assert [
            (config.raw_root.parent / row["relative_path"]).read_bytes() for row in rows
        ] == list(expected_payloads)
        assert (
            connection.execute(
                """SELECT count(*) FROM source_revisions
                    WHERE resource_kind=? AND is_current=0""",
                (resource,),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                """SELECT count(*) FROM source_revisions
                    WHERE resource_kind=? AND is_current=1""",
                (resource,),
            ).fetchone()[0]
            == 1
        )

    assert len(list(config.raw_root.rglob("*.json"))) == 2
    assert len(list(config.raw_root.rglob("*.fit"))) == 2
    assert not list(config.raw_root.rglob("*.zip"))
    assert not list(config.raw_root.rglob(".tmp-*"))
    connection.close()


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_provider_values_fail_closed_before_raw_revision_or_json_projection(
    tmp_path: Path,
    invalid_value: float,
) -> None:
    config, tool = _setup(tmp_path)
    tool.transport.health["user_summary"] = {
        "calendarDate": "2026-04-15",
        "invalidMetric": invalid_value,
    }
    receipt = tool.execute(
        SyncRequest(
            "repair",
            through_local_date="2026-04-15",
            resource_kinds=("user_summary",),
            invocation_id=f"strict-nonfinite-{repr(invalid_value)}",
        )
    )
    assert receipt.status == "partial"
    assert "NaN" not in receipt.json()
    assert "Infinity" not in receipt.json()
    with repository_connection(config) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM raw_objects WHERE resource_kind='user_summary'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM source_revisions WHERE resource_kind='user_summary'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute("SELECT count(*) FROM daily_health").fetchone()[0] == 0
        )
        assert (
            connection.execute(
                """SELECT error_code FROM garmin_sync_items
               WHERE resource_kind='user_summary' AND status='failed'"""
            ).fetchone()[0]
            == "provider_json_invalid"
        )
        assert (
            connection.execute(
                """SELECT reason_code FROM garmin_sync_gaps
               WHERE resource_kind='user_summary'"""
            ).fetchone()[0]
            == "provider_json_invalid"
        )
        json_columns = [
            row[0]
            for row in connection.execute(
                """SELECT sql FROM sqlite_schema
                   WHERE type='table' AND sql LIKE '%JSON%'"""
            )
        ]
        assert all(
            "NaN" not in statement and "Infinity" not in statement
            for statement in json_columns
        )
    assert not list(config.raw_root.rglob(".tmp-*"))


def test_unsupported_provider_object_is_never_stringified_or_persisted(
    tmp_path: Path,
) -> None:
    class UnsupportedProviderObject:
        def __str__(self) -> str:
            return "PRIVATE_UNSUPPORTED_OBJECT_MARKER"

    config, tool = _setup(tmp_path)
    tool.transport.health["user_summary"] = {
        "calendarDate": "2026-04-15",
        "unsupported": UnsupportedProviderObject(),
    }
    receipt = tool.execute(
        SyncRequest(
            "repair",
            through_local_date="2026-04-15",
            resource_kinds=("user_summary",),
            invocation_id="strict-unsupported-object",
        )
    )
    assert receipt.status == "partial"
    assert "PRIVATE_UNSUPPORTED_OBJECT_MARKER" not in receipt.json()
    with repository_connection(config) as connection:
        dump = "\n".join(connection.iterdump())
        assert "PRIVATE_UNSUPPORTED_OBJECT_MARKER" not in dump
        assert (
            connection.execute(
                "SELECT count(*) FROM raw_objects WHERE resource_kind='user_summary'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM source_revisions WHERE resource_kind='user_summary'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute("SELECT count(*) FROM daily_health").fetchone()[0] == 0
        )
        assert (
            connection.execute(
                """SELECT error_code FROM garmin_sync_items
               WHERE resource_kind='user_summary' AND status='failed'"""
            ).fetchone()[0]
            == "provider_json_invalid"
        )
    assert not list(config.raw_root.rglob(".tmp-*"))


def test_health_project_failure_is_sanitized_and_leaves_repairable_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, tool = _setup(tmp_path)
    marker = "PRIVATE_PAYLOAD_MARKER"
    tool.transport.health["user_summary"] = {"unreviewedProviderField": marker}

    def fail_health_projection(*_: object) -> None:
        raise ValueError("projection failed")

    monkeypatch.setattr(tool, "_project_health", fail_health_projection)
    receipt = tool.execute(
        SyncRequest(
            "repair",
            through_local_date="2026-04-15",
            resource_kinds=("user_summary",),
            invocation_id="health-project-failure",
        )
    )
    assert receipt.status == "partial"
    assert marker not in receipt.json()
    with repository_connection(config) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM raw_objects WHERE resource_kind='user_summary'"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                """SELECT count(*) FROM source_revisions
                   WHERE resource_kind='user_summary'"""
            ).fetchone()[0]
            == 1
        )
        assert tuple(
            connection.execute(
                "SELECT is_current,parsed_at_utc FROM source_revisions WHERE resource_kind='user_summary'"
            ).fetchone()
        ) == (0, None)
        gap = connection.execute(
            """SELECT reason_code FROM garmin_sync_gaps
               WHERE resource_kind='user_summary'"""
        ).fetchone()
        item = connection.execute(
            """SELECT error_code,error_summary FROM garmin_sync_items
               WHERE resource_kind='user_summary' AND status='failed'"""
        ).fetchone()
        assert gap["reason_code"] == "parse_or_project_failed"
        assert item["error_code"] == "parse_or_project_failed"
        assert marker not in (item["error_summary"] or "")


def test_activity_fit_archive_failure_keeps_fit_revision_but_no_samples(
    tmp_path: Path,
) -> None:
    config, _ = _setup(tmp_path)
    repository = GarminRepository(config)
    connection = repository.connect()
    fit_payload = SYNTHETIC_FITS["Running.fit"]

    def fail_fit_projection(_: int) -> None:
        raise ValueError("fit projection failed")

    with pytest.raises(ValueError, match="fit projection failed"):
        repository.archive(
            connection,
            "activity_fit",
            "fixture-activity",
            fit_payload,
            "fit",
            "application/octet-stream",
            fail_fit_projection,
        )

    assert (
        connection.execute(
            "SELECT count(*) FROM raw_objects WHERE resource_kind='activity_fit'"
        ).fetchone()[0]
        == 1
    )
    assert (
        connection.execute(
            "SELECT count(*) FROM source_revisions WHERE resource_kind='activity_fit'"
        ).fetchone()[0]
        == 1
    )
    assert tuple(
        connection.execute(
            """SELECT is_current,parsed_at_utc FROM source_revisions
               WHERE resource_kind='activity_fit'"""
        ).fetchone()
    ) == (0, None)
    assert (
        connection.execute("SELECT count(*) FROM activity_samples").fetchone()[0] == 0
    )
    connection.close()


def repository_connection(config):
    return GarminRepository(config).connect()
