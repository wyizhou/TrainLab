from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.foundation import FoundationConfig
from src.foundation_sample import generate_sample_database
from src.garmin_smoke_backup import (
    GarminSmokeBackupError,
    _hash,
    _reject_wal,
    _walk_ancestors,
    prepare_backup,
    sqlite_aggregate_hash,
)
from src.resources import resource_bytes

ROOT = Path(__file__).resolve().parents[1]


def _key(path: Path, value: bytes = b"k" * 32) -> Path:
    path.write_bytes(value)
    path.chmod(0o600)
    return path


def _legacy(path: Path) -> Path:
    import sqlite3

    c = sqlite3.connect(path)
    c.execute("create table x(a text)")
    c.execute("insert into x values ('synthetic')")
    c.commit()
    c.close()
    path.chmod(0o600)
    return path


def _run(tmp_path: Path):
    sample = generate_sample_database(tmp_path / "foundation")
    legacy = _legacy(tmp_path / "legacy.db")
    key = _key(tmp_path / "key")
    config = FoundationConfig(
        sample,
        sample / "data.db",
        sample / "raw",
        sample / "state",
        sample / "state/foundation-ready.json",
        sample / "state/locks/foundation.lock",
    )
    before = ((sample / "data.db").read_bytes(), legacy.read_bytes())
    return (
        prepare_backup(
            project_root=ROOT,
            output_root=tmp_path / "out",
            key_file=key,
            authorization_id="authz-" + "a" * 32,
            operator_registered=True,
            legacy_db=legacy,
            config_loader=lambda _root: config,
        ),
        sample,
        legacy,
        before,
    )


def test_backup_restore_shadow_receipt_is_redacted_and_hashes_match(tmp_path: Path):
    receipt, source, legacy, _before = _run(tmp_path)
    schema = json.loads(
        resource_bytes("harness/schemas/garmin_smoke_backup_receipt.schema.json")
    )
    assert not list(Draft202012Validator(schema).iter_errors(receipt))
    assert (
        receipt["foundation_source_aggregate_sha256"]
        == receipt["foundation_restore_aggregate_sha256"]
        == receipt["foundation_shadow_aggregate_sha256"]
    )
    assert (
        receipt["legacy_source_aggregate_sha256"]
        == receipt["legacy_restore_aggregate_sha256"]
    )
    assert (
        "synthetic" not in json.dumps(receipt)
        and str(source) not in json.dumps(receipt)
        and str(legacy) not in json.dumps(receipt)
    )
    assert all(
        stat.S_IMODE((tmp_path / "out" / name).lstat().st_mode) == 0o600
        for name in (
            "foundation.tlfb",
            "foundation-restored.db",
            "legacy-backup.db",
            "legacy-restored.db",
        )
    )
    material = dict(receipt)
    receipt_hash = material.pop("receipt_sha256")
    assert receipt_hash == _hash("backup-receipt-v1", material)
    assert (tmp_path / "out" / "receipt.json").is_file()
    assert not list(tmp_path.glob(".garmin-smoke-backup-*"))


def test_existing_target_wrong_key_and_unsafe_key_fail_without_public_output(
    tmp_path: Path,
):
    sample = generate_sample_database(tmp_path / "foundation")
    legacy = _legacy(tmp_path / "legacy.db")
    key = _key(tmp_path / "key", b"x")
    config = FoundationConfig(
        sample,
        sample / "data.db",
        sample / "raw",
        sample / "state",
        sample / "state/foundation-ready.json",
        sample / "state/locks/foundation.lock",
    )
    for target in (tmp_path / "out",):
        with pytest.raises(GarminSmokeBackupError):
            prepare_backup(
                project_root=ROOT,
                output_root=target,
                key_file=key,
                authorization_id="authz-" + "a" * 32,
                operator_registered=True,
                legacy_db=legacy,
                config_loader=lambda _root: config,
            )
        assert not target.exists()
    key.write_bytes(b"k" * 32)
    key.chmod(0o644)
    with pytest.raises(GarminSmokeBackupError):
        prepare_backup(
            project_root=ROOT,
            output_root=tmp_path / "out2",
            key_file=key,
            authorization_id="authz-" + "a" * 32,
            operator_registered=True,
            legacy_db=legacy,
            config_loader=lambda _root: config,
        )


def test_source_files_are_unchanged_and_symlink_target_rejected(tmp_path: Path):
    receipt, source, legacy, before = _run(tmp_path)
    assert ((source / "data.db").read_bytes(), legacy.read_bytes()) == before
    key = _key(tmp_path / "key2")
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "elsewhere")
    config = FoundationConfig(
        source,
        source / "data.db",
        source / "raw",
        source / "state",
        source / "state/foundation-ready.json",
        source / "state/locks/foundation.lock",
    )
    with pytest.raises(GarminSmokeBackupError):
        prepare_backup(
            project_root=ROOT,
            output_root=link / "out",
            key_file=key,
            authorization_id="authz-" + "a" * 32,
            operator_registered=True,
            legacy_db=legacy,
            config_loader=lambda _root: config,
        )


def test_active_lock_and_wrong_restore_key_fail_closed(tmp_path: Path):
    sample = generate_sample_database(tmp_path / "foundation")
    legacy = _legacy(tmp_path / "legacy.db")
    key = _key(tmp_path / "key")
    config = FoundationConfig(
        sample,
        sample / "data.db",
        sample / "raw",
        sample / "state",
        sample / "state/foundation-ready.json",
        sample / "state/locks/foundation.lock",
    )
    config.lock_path.write_text('{"pid":1}', encoding="utf-8")
    config.lock_path.chmod(0o600)
    with pytest.raises(GarminSmokeBackupError):
        prepare_backup(
            project_root=ROOT,
            output_root=tmp_path / "out",
            key_file=key,
            authorization_id="authz-" + "a" * 32,
            operator_registered=True,
            legacy_db=legacy,
            config_loader=lambda _root: config,
        )
    assert not (tmp_path / "out").exists()
    assert not list(tmp_path.glob(".garmin-smoke-backup-*"))
    container = tmp_path / "backup.tlfb"
    from src.foundation import FoundationTool

    FoundationTool(config).backup_encrypted(container, lambda: b"k" * 32)
    with pytest.raises(Exception):
        FoundationTool.restore_encrypted(container, tmp_path / "wrong.db", b"x" * 32)
    assert not (tmp_path / "wrong.db").exists()


@pytest.mark.parametrize("stage", ["backup", "restore", "shadow", "publish"])
def test_failpoints_leave_no_public_target(tmp_path: Path, stage: str):
    sample = generate_sample_database(tmp_path / "foundation")
    legacy = _legacy(tmp_path / "legacy.db")
    key = _key(tmp_path / "key")
    config = FoundationConfig(
        sample,
        sample / "data.db",
        sample / "raw",
        sample / "state",
        sample / "state/foundation-ready.json",
        sample / "state/locks/foundation.lock",
    )
    with pytest.raises(RuntimeError):
        prepare_backup(
            project_root=ROOT,
            output_root=tmp_path / "out",
            key_file=key,
            authorization_id="authz-" + "a" * 32,
            operator_registered=True,
            legacy_db=legacy,
            config_loader=lambda _root: config,
            failpoint=lambda point: (
                (_ for _ in ()).throw(RuntimeError(point)) if point == stage else None
            ),
        )
    assert not (tmp_path / "out").exists()


def test_source_change_and_unsafe_ancestor_fail_closed(tmp_path: Path):
    sample = generate_sample_database(tmp_path / "foundation")
    legacy = _legacy(tmp_path / "legacy.db")
    key = _key(tmp_path / "key")
    config = FoundationConfig(
        sample,
        sample / "data.db",
        sample / "raw",
        sample / "state",
        sample / "state/foundation-ready.json",
        sample / "state/locks/foundation.lock",
    )

    def change(point: str) -> None:
        if point == "backup":
            legacy.write_bytes(legacy.read_bytes() + b"x")

    with pytest.raises(GarminSmokeBackupError, match="source_changed"):
        prepare_backup(
            project_root=ROOT,
            output_root=tmp_path / "out",
            key_file=key,
            authorization_id="authz-" + "a" * 32,
            operator_registered=True,
            legacy_db=legacy,
            config_loader=lambda _root: config,
            failpoint=change,
        )
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    unsafe.chmod(0o777)
    with pytest.raises(GarminSmokeBackupError):
        prepare_backup(
            project_root=ROOT,
            output_root=unsafe / "out",
            key_file=key,
            authorization_id="authz-" + "a" * 32,
            operator_registered=True,
            legacy_db=legacy,
            config_loader=lambda _root: config,
        )


def test_quoted_table_blob_null_and_float_are_deterministic(tmp_path: Path):
    import sqlite3

    db = tmp_path / "quoted.db"
    c = sqlite3.connect(db)
    c.execute('create table "odd""name"(b blob,n text,f real)')
    c.execute('insert into "odd""name" values(?,?,?)', (b"x", None, float("inf")))
    c.commit()
    c.close()
    db.chmod(0o600)
    assert sqlite_aggregate_hash(db, "test-domain") == sqlite_aggregate_hash(
        db, "test-domain"
    )


def test_user_owned_mount_root_allows_group_write_but_not_world_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    secure = tmp_path / "secure"
    secure.mkdir(mode=0o700)
    original_mode = stat.S_IMODE(tmp_path.lstat().st_mode)
    monkeypatch.setattr(os.path, "ismount", lambda value: Path(value) == tmp_path)
    tmp_path.chmod(0o770)
    _walk_ancestors(secure)
    tmp_path.chmod(0o777)
    with pytest.raises(GarminSmokeBackupError, match="unsafe_ancestor"):
        _walk_ancestors(secure)
    tmp_path.chmod(original_mode)


def test_zero_length_wal_with_shm_is_quiescent_but_nonempty_wal_is_rejected(
    tmp_path: Path,
):
    db = tmp_path / "sample.db"
    db.touch(mode=0o600)
    wal = tmp_path / "sample.db-wal"
    wal.touch(mode=0o600)
    shm = tmp_path / "sample.db-shm"
    shm.write_bytes(b"closed-reader-state")
    shm.chmod(0o600)
    _reject_wal(db)
    wal.write_bytes(b"uncheckpointed-frame")
    with pytest.raises(GarminSmokeBackupError, match="sqlite_not_quiescent"):
        _reject_wal(db)
