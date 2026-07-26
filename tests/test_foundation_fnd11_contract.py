from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import threading
from multiprocessing import active_children
from pathlib import Path

import pytest

import trainlab.foundation as foundation
from .foundation_v1_fixture import create_published_v1_database
from trainlab.foundation import (
    FOUNDATION_SCHEMA_VERSION,
    FoundationConfig,
    FoundationReceipt,
    FoundationRequest,
    FoundationTool,
)


UTC = "2026-07-24T12:34:56Z"


def config(root: Path) -> FoundationConfig:
    return FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state" / "foundation-ready.json",
        root / "state" / "locks" / "foundation.lock",
    )


def request(mode: str, invocation: str | None = None, target: int | None = None) -> FoundationRequest:
    return FoundationRequest(mode, invocation or f"fnd11-{mode}", UTC, target)


def tree_evidence(root: Path) -> tuple[tuple[object, ...], ...]:
    values: list[tuple[object, ...]] = []
    for path in [root, *root.rglob("*")]:
        relative = str(path.relative_to(root))
        info = path.stat()
        if path.is_dir():
            values.append((relative, "directory", info.st_mode & 0o777, info.st_mtime_ns))
        else:
            payload = path.read_bytes()
            values.append(
                (
                    relative,
                    "file",
                    info.st_mode & 0o777,
                    info.st_mtime_ns,
                    payload,
                    hashlib.sha256(payload).hexdigest(),
                )
            )
    return tuple(sorted(values))


def sqlite_source_evidence(root: Path) -> dict[str, tuple[object, ...]]:
    values: dict[str, tuple[object, ...]] = {}
    for path in (root / "data.db", root / "data.db-wal", root / "data.db-shm"):
        if path.exists():
            info = path.stat()
            payload = path.read_bytes()
            values[path.name] = (
                info.st_ino,
                info.st_mode & 0o777,
                info.st_mtime_ns,
                info.st_size,
                payload,
                hashlib.sha256(payload).hexdigest(),
            )
    return values


def test_fnd11_first_init_and_ready_init_are_identity_preserving_full_tree_noop(tmp_path: Path) -> None:
    root=tmp_path / "foundation"; tool=FoundationTool(config(root))
    first=tool.execute(request("init", "first-init"))
    assert (first.invocation_id,first.mode,first.status,first.ready) == ("first-init","init","initialized",True)
    before=tree_evidence(root)

    def forbidden_lock(_: Path):
        raise AssertionError("ready init must remain lock-free")

    tool._lock=forbidden_lock  # type: ignore[method-assign]
    repeated=tool.execute(request("init", "bootstrap-init"))
    assert (repeated.invocation_id,repeated.mode,repeated.status,repeated.ready) == (
        "bootstrap-init","init","already_initialized",True
    )
    assert tree_evidence(root) == before


@pytest.mark.parametrize(("mode","expected"), [("status","ready"),("verify","ready"),("init","already_initialized")])
def test_fnd11_ready_modes_preserve_live_wal_sidecars_and_mtimes(
    tmp_path: Path, mode: str, expected: str
) -> None:
    root=tmp_path / mode; tool=FoundationTool(config(root))
    assert tool.execute(request("init")).status == "initialized"
    writer=tool._connect(root / "data.db")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute(
        "INSERT INTO data_subjects(subject_key,created_at_utc) VALUES(?,?)",
        (f"wal-{mode}",UTC),
    )
    try:
        before=sqlite_source_evidence(root)
        assert set(before) == {"data.db","data.db-wal","data.db-shm"}
        receipt=tool.execute(request(mode, f"wal-{mode}"))
        assert (receipt.invocation_id,receipt.mode,receipt.status,receipt.ready) == (
            f"wal-{mode}",mode,expected,True
        )
        assert sqlite_source_evidence(root) == before
        assert not list(root.glob(".foundation-readonly-*"))
    finally:
        writer.close()


@pytest.mark.parametrize("mode", ["status","verify","init"])
@pytest.mark.parametrize("anomaly", ["missing_raw_leaf","unsafe_raw","missing_marker"])
def test_fnd11_ready_filesystem_anomaly_is_rejected_without_repair(
    tmp_path: Path, mode: str, anomaly: str
) -> None:
    root=tmp_path / f"{mode}-{anomaly}"; tool=FoundationTool(config(root))
    assert tool.execute(request("init")).status == "initialized"
    if anomaly == "missing_raw_leaf":
        (root / "raw" / "legacy" / "fit").rmdir()
    elif anomaly == "unsafe_raw":
        (root / "raw" / "gmail").chmod(0o755)
    else:
        (root / "state" / "foundation-ready.json").unlink()
    before=tree_evidence(root)
    receipt=tool.execute(request(mode))
    assert receipt.status == "incompatible" and receipt.next_action == "operator_review" and not receipt.ready
    assert tree_evidence(root) == before
    assert not (root / "state" / "locks" / "foundation.lock").exists()


@pytest.mark.parametrize("mode", ["status","verify","init"])
@pytest.mark.parametrize("mutation", ["implementation","initialized_timestamp","updated_timestamp","foreign_key"])
def test_fnd11_complete_ready_compatibility_checks_are_read_only(
    tmp_path: Path, mode: str, mutation: str
) -> None:
    root=tmp_path / f"{mode}-{mutation}"; tool=FoundationTool(config(root))
    assert tool.execute(request("init")).status == "initialized"
    conn=sqlite3.connect(root / "data.db")
    if mutation == "implementation":
        conn.execute("UPDATE foundation_state SET implementation_version='forged'")
    elif mutation == "initialized_timestamp":
        conn.execute("UPDATE foundation_state SET initialized_at_utc='2026-01-01T00:00:00.000000Z'")
    elif mutation == "updated_timestamp":
        conn.execute("UPDATE foundation_state SET updated_at_utc='2026-01-01T00:00:00.000000Z'")
    else:
        conn.execute("INSERT INTO mail_threads(subject_id,provider_thread_id) VALUES(999,'orphan')")
    conn.commit(); conn.close()
    before=tree_evidence(root)
    receipt=tool.execute(request(mode))
    assert receipt.status == "incompatible" and receipt.next_action == "operator_review" and not receipt.ready
    assert tree_evidence(root) == before


@pytest.mark.parametrize(
    ("status","expected_exit"),
    [
        ("initialized",0),
        ("already_initialized",0),
        ("ready",0),
        ("incompatible",10),
        ("lock_busy",11),
        ("failed",20),
    ],
)
def test_fnd11_cli_exit_mapping_and_receipt_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    expected_exit: int,
) -> None:
    monkeypatch.setattr(
        foundation.FoundationConfig,
        "load",
        classmethod(lambda cls, _: config(tmp_path / "unused")),
    )

    def execute(self, item: FoundationRequest) -> FoundationReceipt:
        return FoundationReceipt(
            invocation_id=item.invocation_id,
            mode=item.mode,
            status=status,
            foundation_schema_version=FOUNDATION_SCHEMA_VERSION,
            ready=status in {"initialized","already_initialized","ready"},
            next_action="none" if status in {"initialized","already_initialized","ready","lock_busy"} else "operator_review",
            completed_at_utc=UTC,
        )

    monkeypatch.setattr(foundation.FoundationTool,"execute",execute)
    assert foundation.main(["--invocation-id","receipt-identity","status"]) == expected_exit
    captured=capsys.readouterr()
    payload=json.loads(captured.out)
    assert captured.err == "" and captured.out.count("\n") == 1
    assert (payload["invocation_id"],payload["mode"],payload["status"]) == (
        "receipt-identity","status",status
    )


def test_fnd11_four_modes_start_no_thread_process_subprocess_or_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root=tmp_path / "foundation"; tool=FoundationTool(config(root))
    before_threads={item.ident for item in threading.enumerate()}
    before_children={item.pid for item in active_children()}

    def forbidden(*args, **kwargs):
        raise AssertionError("Foundation must not start a worker or subprocess")

    monkeypatch.setattr(threading.Thread,"start",forbidden)
    monkeypatch.setattr(subprocess,"run",forbidden)
    monkeypatch.setattr(subprocess,"Popen",forbidden)
    if hasattr(os,"fork"):
        monkeypatch.setattr(os,"fork",forbidden)
    assert tool.execute(request("init")).status == "initialized"
    assert tool.execute(request("status")).status == "ready"
    assert tool.execute(request("verify")).status == "ready"
    assert tool.execute(request("migrate", target=FOUNDATION_SCHEMA_VERSION)).status == "already_initialized"
    assert {item.ident for item in threading.enumerate()} == before_threads
    assert {item.pid for item in active_children()} == before_children


def v1_logical_evidence(root: Path) -> tuple[object, ...]:
    conn=sqlite3.connect(root / "data.db")
    try:
        state=conn.execute("SELECT * FROM foundation_state").fetchall()
        migrations=conn.execute("SELECT * FROM schema_migrations ORDER BY version").fetchall()
        objects=conn.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        integrity=conn.execute("PRAGMA integrity_check").fetchall()
    finally:
        conn.close()
    marker=(root / "state" / "foundation-ready.json").read_bytes()
    raw=tuple(
        sorted(
            (
                str(path.relative_to(root / "raw")),
                path.stat().st_mode & 0o777,
                path.stat().st_mtime_ns,
                path.read_bytes() if path.is_file() else None,
            )
            for path in [root / "raw", *(root / "raw").rglob("*")]
        )
    )
    return state,migrations,objects,integrity,marker,raw


@pytest.mark.parametrize("phase", ["before_migration_transaction","during_migration_transaction"])
def test_fnd11_precommit_migration_failure_rolls_back_last_known_good(
    tmp_path: Path, phase: str
) -> None:
    root=tmp_path / phase; base=create_published_v1_database(root)
    before=v1_logical_evidence(root)

    def failpoint(observed: str) -> None:
        if observed == phase:
            raise RuntimeError(phase)

    failed=FoundationTool(base.config,failpoint=failpoint).execute(
        request("migrate", target=FOUNDATION_SCHEMA_VERSION)
    )
    assert failed.status == "failed" and failed.next_action == "operator_review"
    assert v1_logical_evidence(root) == before
    recovered=FoundationTool(base.config).execute(request("migrate", target=FOUNDATION_SCHEMA_VERSION))
    assert recovered.status == "initialized" and recovered.ready


def test_fnd11_postcommit_premarker_failure_requires_explicit_republication(tmp_path: Path) -> None:
    root=tmp_path / "postcommit"; base=create_published_v1_database(root)

    def failpoint(observed: str) -> None:
        if observed == "after_migration_transaction":
            raise RuntimeError(observed)

    failed=FoundationTool(base.config,failpoint=failpoint).execute(
        request("migrate", target=FOUNDATION_SCHEMA_VERSION)
    )
    assert failed.status == "failed"
    marker=json.loads((root / "state" / "foundation-ready.json").read_text())
    assert marker["schema_version"] == 1
    assert FoundationTool(base.config).execute(request("init")).status == "incompatible"
    repaired=FoundationTool(base.config).execute(request("migrate", target=FOUNDATION_SCHEMA_VERSION))
    assert repaired.status == "initialized" and repaired.ready
    assert repaired.warnings == [{"code":"migration_marker_republished","summary":"completed explicit migration publication"}]


def test_fnd11_postmarker_failure_leaves_verified_last_known_good(tmp_path: Path) -> None:
    root=tmp_path / "postmarker"; base=create_published_v1_database(root)

    def failpoint(observed: str) -> None:
        if observed == "after_migration_marker":
            raise RuntimeError(observed)

    failed=FoundationTool(base.config,failpoint=failpoint).execute(
        request("migrate", target=FOUNDATION_SCHEMA_VERSION)
    )
    assert failed.status == "failed"
    ready=FoundationTool(base.config)
    assert ready.execute(request("status")).status == "incompatible"
    assert ready.execute(request("verify")).status == "incompatible"
    assert ready.execute(request("init")).status == "incompatible"
    assert ready.execute(request("migrate", target=FOUNDATION_SCHEMA_VERSION)).status == "initialized"
    assert ready.execute(request("status")).status == "ready"


@pytest.mark.parametrize("mutation", ["marker_timestamp","state_timestamp","migration_timestamp"])
def test_fnd11_explicit_migrate_rejects_noncanonical_v1_metadata_without_writes(
    tmp_path: Path, mutation: str
) -> None:
    root=tmp_path / mutation; base=create_published_v1_database(root)
    marker=root / "state" / "foundation-ready.json"
    if mutation == "marker_timestamp":
        payload=json.loads(marker.read_text())
        payload["initialized_at_utc"]="2026-01-01T00:00:00.000000Z"
        marker.write_text(json.dumps(payload)); marker.chmod(0o600)
    else:
        conn=sqlite3.connect(root / "data.db")
        if mutation == "state_timestamp":
            conn.execute("UPDATE foundation_state SET initialized_at_utc='2026-01-01T00:00:00.000000Z'")
        else:
            conn.execute("UPDATE schema_migrations SET applied_at_utc='2026-01-01T00:00:00.000000Z'")
        conn.commit(); conn.close()
    db=root / "data.db"
    before=(db.read_bytes(),db.stat().st_mtime_ns,marker.read_bytes(),marker.stat().st_mtime_ns,tree_evidence(root / "raw"))
    receipt=base.execute(request("migrate", target=FOUNDATION_SCHEMA_VERSION))
    after=(db.read_bytes(),db.stat().st_mtime_ns,marker.read_bytes(),marker.stat().st_mtime_ns,tree_evidence(root / "raw"))
    assert receipt.status == "incompatible" and receipt.next_action == "operator_review"
    assert after == before


def test_fnd11_explicit_migrate_rejects_inconsistent_current_receipt_without_data_write(tmp_path: Path) -> None:
    root=tmp_path / "current"; tool=FoundationTool(config(root))
    assert tool.execute(request("init")).status == "initialized"
    conn=sqlite3.connect(root / "data.db")
    conn.execute("UPDATE schema_migrations SET description='forged' WHERE version=2")
    conn.commit(); conn.close()
    db=root / "data.db"; marker=root / "state" / "foundation-ready.json"
    before=(db.read_bytes(),db.stat().st_mtime_ns,marker.read_bytes(),marker.stat().st_mtime_ns,tree_evidence(root / "raw"))
    receipt=tool.execute(request("migrate", target=FOUNDATION_SCHEMA_VERSION))
    after=(db.read_bytes(),db.stat().st_mtime_ns,marker.read_bytes(),marker.stat().st_mtime_ns,tree_evidence(root / "raw"))
    assert receipt.status == "incompatible" and receipt.next_action == "operator_review"
    assert after == before


def test_fnd11_bootstrap_accepts_only_already_initialized(tmp_path: Path) -> None:
    from trainlab.orchestration import FoundationAdapter

    root=tmp_path / "foundation"; tool=FoundationTool(config(root))

    def invoke(payload):
        return json.loads(tool.execute(FoundationRequest(**payload)).json())

    provision=tool.execute(request("init","provision"))
    assert provision.status == "initialized"
    result=FoundationAdapter(invoke).bootstrap(invocation_id="bootstrap",requested_at_utc=UTC)
    assert result.may_start_workflow and result.audit.status == "already_initialized"
