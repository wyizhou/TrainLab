from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import sqlite3
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def _formal_root(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    state = root / "state"
    raw = state / "raw" / "garmin" / "health"
    raw.mkdir(parents=True, mode=0o700)
    (state / "trainlab.db").write_bytes(b"synthetic-db")
    (state / "trainlab.lock").write_bytes(b"")
    (raw / "20260812-rhr.json").write_bytes(b"{}")
    for path in (
        state / "trainlab.db",
        state / "trainlab.lock",
        raw / "20260812-rhr.json",
    ):
        os.chmod(path, 0o600)
    os.chmod(root, 0o700)
    os.chmod(state, 0o700)
    for directory in (state / "raw", state / "raw/garmin", raw):
        os.chmod(directory, 0o700)
    return root


def test_formal_fingerprint_includes_raw_and_sidecars(tmp_path: Path) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_fingerprint",
    )
    root = _formal_root(tmp_path)
    fingerprint = builder._formal_state_fingerprint(root)
    paths = {str(item["path"]) for item in fingerprint["entries"]}
    assert "trainlab.db" in paths
    assert "trainlab.lock" in paths
    assert "raw/garmin/health/20260812-rhr.json" in paths
    assert fingerprint["raw_entry_count"] >= 3


def test_formal_private_files_reject_wide_mode_and_hardlinks(tmp_path: Path) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_private_files",
    )
    root = _formal_root(tmp_path)
    raw = root / "state/raw/garmin/health/20260812-rhr.json"
    os.chmod(raw, 0o644)
    with pytest.raises(ValueError, match="formal_state_unsafe_entry"):
        builder._formal_state_fingerprint(root)
    os.chmod(raw, 0o600)
    hardlink = raw.with_name("hardlink-rhr.json")
    os.link(raw, hardlink)
    with pytest.raises(ValueError, match="formal_state_unsafe_entry"):
        builder._formal_state_fingerprint(root)


def test_formal_database_and_wal_reject_unsafe_metadata(tmp_path: Path) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_private_db",
    )
    root = _formal_root(tmp_path)
    database = root / "state/trainlab.db"
    database_link = database.with_name("trainlab-linked.db")
    os.link(database, database_link)
    with pytest.raises(ValueError, match="formal_state_lock_unavailable"):
        builder._formal_state_fingerprint(root)
    database_link.unlink()
    wal = root / "state/trainlab.db-wal"
    wal.write_bytes(b"")
    os.chmod(wal, 0o644)
    with pytest.raises(ValueError, match="formal_state_unsafe_entry"):
        builder._formal_state_fingerprint(root)


def test_formal_active_shm_is_rejected_without_deleting_it(tmp_path: Path) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_active_shm",
    )
    root = _formal_root(tmp_path)
    database = root / "state/trainlab.db"
    database.unlink()
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE evidence(value INTEGER)")
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    connection.execute("BEGIN")
    connection.execute("SELECT * FROM evidence").fetchall()
    os.chmod(database, 0o600)
    os.chmod(root / "state/trainlab.db-wal", 0o600)
    shm = root / "state/trainlab.db-shm"
    os.chmod(shm, 0o600)
    try:
        with pytest.raises(ValueError, match="formal_state_active"):
            builder._formal_state_fingerprint(root)
        assert shm.exists()
        assert shm.stat().st_size > 0
    finally:
        connection.close()


def test_formal_idle_sqlite_connection_in_another_process_is_rejected(
    tmp_path: Path,
) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_external_idle",
    )
    root = _formal_root(tmp_path)
    database = root / "state/trainlab.db"
    database.unlink()
    ready = tmp_path / "ready"
    stop = tmp_path / "stop"
    program = """
import os, pathlib, sqlite3, sys, time
database, ready, stop = map(pathlib.Path, sys.argv[1:])
connection = sqlite3.connect(database)
connection.execute('PRAGMA journal_mode=WAL')
connection.execute('CREATE TABLE evidence(value INTEGER)')
connection.commit()
connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
for path in (database, pathlib.Path(str(database) + '-wal'), pathlib.Path(str(database) + '-shm')):
    if path.exists(): os.chmod(path, 0o600)
ready.write_text('ready', encoding='utf-8')
while not stop.exists(): time.sleep(0.01)
connection.close()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", program, str(database), str(ready), str(stop)]
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        with pytest.raises(ValueError, match="formal_state_active"):
            builder._formal_state_fingerprint(root)
    finally:
        stop.write_text("stop", encoding="utf-8")
        process.wait(timeout=5)


def test_nonempty_formal_wal_fails_before_candidate_creation(tmp_path: Path) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_wal",
    )
    root = _formal_root(tmp_path)
    wal = root / "state/trainlab.db-wal"
    wal.write_bytes(b"uncheckpointed")
    os.chmod(wal, 0o600)
    candidate = tmp_path / "candidate"
    with pytest.raises(ValueError, match="formal_wal_nonempty"):
        builder.build(root, candidate)
    assert not candidate.exists()


def test_formal_lock_contention_fails_before_candidate_creation(tmp_path: Path) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_lock",
    )
    root = _formal_root(tmp_path)
    lock_path = root / "state/trainlab.lock"
    descriptor = os.open(lock_path, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        candidate = tmp_path / "candidate"
        with pytest.raises(ValueError, match="formal_state_lock_unavailable"):
            builder.build(root, candidate)
        assert not candidate.exists()
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def test_formal_state_drift_is_detected_after_candidate_build(tmp_path: Path) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_drift",
    )
    root = _formal_root(tmp_path)

    def mutate(formal_root: Path, candidate_root: Path) -> dict[str, object]:
        candidate_root.mkdir(mode=0o700)
        raw = formal_root / "state/raw/garmin/health/20260812-rhr.json"
        raw.write_bytes(b"changed")
        os.chmod(raw, 0o600)
        return {"candidate_root": str(candidate_root)}

    builder._build_unlocked = mutate
    with pytest.raises(ValueError, match="formal_state_changed_during_snapshot"):
        builder.build(root, tmp_path / "candidate")


def test_nonempty_candidate_sidecar_is_not_deleted(tmp_path: Path) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_candidate_sidecar",
    )
    database = tmp_path / "trainlab.db"
    sidecar = tmp_path / "trainlab.db-wal"
    sidecar.write_bytes(b"must-keep")
    os.chmod(sidecar, 0o600)
    with pytest.raises(ValueError, match="candidate_wal_nonempty"):
        builder._assert_candidate_sidecars_quiescent(database)
    assert sidecar.read_bytes() == b"must-keep"


def test_checkpoint_rejects_preexisting_nonempty_wal_before_open(
    tmp_path: Path,
) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_preexisting_wal",
    )
    state = tmp_path / "source/state"
    state.mkdir(mode=0o700, parents=True)
    state.chmod(0o700)
    database = state / "trainlab.db"
    database.write_bytes(b"database-before")
    database.chmod(0o600)
    wal = state / "trainlab.db-wal"
    wal.write_bytes(b"uncheckpointed-evidence")
    wal.chmod(0o600)
    before_database = database.read_bytes()
    before_wal = wal.read_bytes()
    with pytest.raises(ValueError, match="candidate_wal_nonempty"):
        builder._checkpoint_candidate_database(database)
    assert database.read_bytes() == before_database
    assert wal.read_bytes() == before_wal


def test_checkpoint_rejects_wal_injected_after_initial_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_checkpoint_gate_race",
    )
    state = tmp_path / "source/state"
    state.mkdir(mode=0o700, parents=True)
    state.chmod(0o700)
    database = state / "trainlab.db"
    sqlite3.connect(database).close()
    database.chmod(0o600)
    before_database = database.read_bytes()
    wal = state / "trainlab.db-wal"
    injected = b"injected-after-initial-gate"
    original_gate = builder._assert_candidate_sidecars_quiescent
    calls = [0]

    def inject_after_first_gate(path: Path) -> None:
        original_gate(path)
        calls[0] += 1
        if calls[0] == 1:
            wal.write_bytes(injected)
            wal.chmod(0o600)

    monkeypatch.setattr(
        builder, "_assert_candidate_sidecars_quiescent", inject_after_first_gate
    )
    with pytest.raises(ValueError, match="candidate_wal_nonempty"):
        builder._checkpoint_candidate_database(database)
    assert database.read_bytes() == before_database
    assert wal.read_bytes() == injected


def test_scope_seal_rejects_wal_injected_after_initial_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_scope_gate_race",
    )
    candidate_root = tmp_path / "candidate"
    source = candidate_root / "source"
    state = source / "state"
    raw = state / "raw"
    raw.mkdir(mode=0o700, parents=True)
    for path in (candidate_root, source, state, raw):
        path.chmod(0o700)
    database = state / "trainlab.db"
    sqlite3.connect(database).close()
    database.chmod(0o600)
    builder._checkpoint_candidate_database(database)
    before_database = database.read_bytes()
    wal = state / "trainlab.db-wal"
    injected = b"injected-before-scope-connect"
    original_gate = builder._assert_candidate_sidecars_quiescent
    calls = [0]

    def inject_after_first_gate(path: Path) -> None:
        original_gate(path)
        calls[0] += 1
        if calls[0] == 1:
            wal.write_bytes(injected)
            wal.chmod(0o600)

    monkeypatch.setattr(
        builder, "_assert_candidate_sidecars_quiescent", inject_after_first_gate
    )
    fingerprint = {
        "schema_version": "formal_state_fingerprint_v1",
        "entries": [],
        "entry_count": 0,
        "raw_entry_count": 0,
        "sha256": hashlib.sha256(b"[]").hexdigest(),
    }
    with pytest.raises(ValueError, match="candidate_wal_nonempty"):
        builder._seal_candidate_scope(
            candidate_root,
            source,
            source,
            fingerprint,
            fingerprint,
        )
    assert database.read_bytes() == before_database
    assert wal.read_bytes() == injected
    assert not (candidate_root / "formal-state-fingerprint.json").exists()


def test_atomic_publish_restores_database_changed_at_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_atomic_publish_race",
    )
    state = tmp_path / "source/state"
    state.mkdir(mode=0o700, parents=True)
    state.chmod(0o700)
    database = state / "trainlab.db"
    sqlite3.connect(database).close()
    database.chmod(0o600)
    before = database.read_bytes()
    injected = b"changed-at-atomic-swap"
    original_swap = builder._atomic_swap
    calls = [0]

    def inject_then_swap(first: Path, second: Path) -> None:
        calls[0] += 1
        if calls[0] == 1:
            with first.open("ab") as stream:
                stream.write(injected)
        original_swap(first, second)

    monkeypatch.setattr(builder, "_atomic_swap", inject_then_swap)
    with pytest.raises(ValueError, match="candidate_database_changed_during_mutation"):
        builder._checkpoint_candidate_database(database)
    assert calls[0] == 2
    assert database.read_bytes() == before + injected


def test_atomic_rollback_failure_preserves_old_database_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_atomic_rollback_failure",
    )
    state = tmp_path / "source/state"
    state.mkdir(mode=0o700, parents=True)
    state.chmod(0o700)
    database = state / "trainlab.db"
    sqlite3.connect(database).close()
    database.chmod(0o600)
    before = database.read_bytes()
    injected = b"preserve-after-rollback-failure"
    original_swap = builder._atomic_swap
    calls = [0]

    def fail_second_swap(first: Path, second: Path) -> None:
        calls[0] += 1
        if calls[0] == 1:
            with first.open("ab") as stream:
                stream.write(injected)
            original_swap(first, second)
            return
        raise ValueError("candidate_atomic_swap_failed")

    monkeypatch.setattr(builder, "_atomic_swap", fail_second_swap)
    with pytest.raises(ValueError, match="candidate_atomic_rollback_failed"):
        builder._checkpoint_candidate_database(database)
    assert calls[0] == 2
    recovery_roots = list(state.glob(".trainlab-db-work-*"))
    assert len(recovery_roots) == 1
    preserved = recovery_roots[0] / "trainlab-replacement.db"
    assert preserved.read_bytes() == before + injected
    assert stat.S_IMODE(recovery_roots[0].stat().st_mode) == 0o700
    assert stat.S_IMODE(preserved.stat().st_mode) == 0o600


def test_candidate_schema_wal_is_checkpointed_and_sidecars_are_retained(
    tmp_path: Path,
) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_candidate_checkpoint",
    )
    state = tmp_path / "source/state"
    state.mkdir(mode=0o700, parents=True)
    state.chmod(0o700)
    database = state / "trainlab.db"
    database.touch(mode=0o600)
    database.chmod(0o600)
    builder._checkpoint_candidate_database(database)
    assert database.is_file()
    wal = database.with_name("trainlab.db-wal")
    assert not wal.exists() or wal.stat().st_size == 0
    shm = database.with_name("trainlab.db-shm")
    if shm.exists():
        assert shm.stat().st_size > 0
        assert stat.S_IMODE(shm.stat().st_mode) == 0o600


def test_current_schema_database_uses_copy_on_write_checkpoint(tmp_path: Path) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_current_schema_checkpoint",
    )
    state = tmp_path / "source/state"
    state.mkdir(mode=0o700, parents=True)
    state.chmod(0o700)
    database = state / "trainlab.db"
    state_module = _module(ROOT / "skills/_shared/state.py", "m8_r32_state_schema")
    state_module.init_database(database)
    database.chmod(0o600)
    builder._checkpoint_candidate_database(database)
    verify = sqlite3.connect(f"file:{database.resolve()}?mode=ro&immutable=1", uri=True)
    try:
        assert verify.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        tables = {
            str(row[0])
            for row in verify.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        verify.close()
    assert tables == {
        "activity_inventory",
        "approvals",
        "external_actions",
        "raw_files",
        "skill_outputs",
        "skill_runs",
    }


def test_active_candidate_shm_is_not_deleted(tmp_path: Path) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_candidate_active_shm",
    )
    state = tmp_path / "source/state"
    state.mkdir(mode=0o700, parents=True)
    state.chmod(0o700)
    database = state / "trainlab.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE evidence(value INTEGER)")
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    connection.execute("BEGIN")
    connection.execute("SELECT * FROM evidence").fetchall()
    for path in (
        database,
        database.with_name("trainlab.db-wal"),
        database.with_name("trainlab.db-shm"),
    ):
        if path.exists():
            path.chmod(0o600)
    try:
        with pytest.raises(ValueError, match="candidate_shm_active"):
            builder._assert_candidate_sidecars_quiescent(database)
        assert database.with_name("trainlab.db-shm").exists()
    finally:
        connection.close()


def test_candidate_sidecar_verification_never_unlinks_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = _module(
        ROOT / "skills/_shared/scripts/build_m8_candidate.py",
        "m8_r32_builder_candidate_atomic_cleanup",
    )
    state = tmp_path / "source/state"
    state.mkdir(mode=0o700, parents=True)
    state.chmod(0o700)
    database = state / "trainlab.db"
    database.write_bytes(b"database")
    database.chmod(0o600)
    wal = state / "trainlab.db-wal"
    wal.write_bytes(b"")
    wal.chmod(0o600)
    shm = state / "trainlab.db-shm"
    shm.write_bytes(b"inactive-shm")
    shm.chmod(0o600)
    original_unlink = Path.unlink

    def guarded_unlink(path: Path, missing_ok: bool = False) -> None:
        if path in {wal, shm}:
            raise AssertionError("candidate SQLite sidecars must be retained")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", guarded_unlink)
    builder._assert_candidate_sidecars_quiescent(database)
    assert wal.is_file()
    assert shm.is_file()


def _write_manifest(path: Path, files: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {"schema_version": "artifact_manifest_v1", "files": files},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_artifact_verifier_requires_owner_only_nonempty_declared_json(
    tmp_path: Path,
) -> None:
    verifier = _module(
        ROOT / "skills/_shared/scripts/verify_m8_artifacts.py",
        "m8_r32_artifacts",
    )
    root = tmp_path / "outputs"
    root.mkdir(mode=0o700)
    report = root / "reports/report.json"
    report.parent.mkdir(mode=0o700)
    report.write_text('{"ok":true}\n', encoding="utf-8")
    os.chmod(report, 0o600)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [{"path": "reports/report.json", "json": True}])
    result = verifier.verify_artifacts(root, manifest)
    assert result["verified"] is True


def test_artifact_verifier_rejects_empty_wrong_mode_and_undeclared_files(
    tmp_path: Path,
) -> None:
    verifier = _module(
        ROOT / "skills/_shared/scripts/verify_m8_artifacts.py",
        "m8_r32_artifacts_negative",
    )
    root = tmp_path / "outputs"
    root.mkdir(mode=0o700)
    declared = root / "reports/report.json"
    declared.parent.mkdir(mode=0o700)
    declared.write_bytes(b"")
    os.chmod(declared, 0o600)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [{"path": "reports/report.json", "json": True}])
    with pytest.raises(ValueError, match="artifact_empty_file"):
        verifier.verify_artifacts(root, manifest)
    declared.write_text("{}\n", encoding="utf-8")
    os.chmod(declared, 0o644)
    with pytest.raises(ValueError, match="artifact_file_permissions"):
        verifier.verify_artifacts(root, manifest)
    os.chmod(declared, 0o600)
    extra = root / "reports/extra.json"
    extra.write_text("{}\n", encoding="utf-8")
    os.chmod(extra, 0o600)
    with pytest.raises(ValueError, match="artifact_undeclared_file"):
        verifier.verify_artifacts(root, manifest)
