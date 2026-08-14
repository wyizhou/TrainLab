from __future__ import annotations

import multiprocessing
import sqlite3
from pathlib import Path

import pytest

import src.foundation as foundation
from src.foundation import FoundationConfig, FoundationRequest, FoundationTool

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


def request(mode: str = "init", target: int | None = None) -> FoundationRequest:
    return FoundationRequest(mode, "fnd02-lifecycle", UTC, target)


def _process_init(root_text: str, entered, release, output) -> None:
    root = Path(root_text)

    def hold(phase: str) -> None:
        if phase == "before_schema":
            entered.set()
            release.wait(10)

    output.put(FoundationTool(config(root), failpoint=hold).execute(request()).status)


def _tree(root: Path) -> tuple[tuple[str, int, int, bytes | None], ...]:
    return tuple(
        sorted(
            (
                str(path.relative_to(root)),
                path.stat().st_mode & 0o777,
                path.stat().st_mtime_ns,
                path.read_bytes() if path.is_file() else None,
            )
            for path in [root, *root.rglob("*")]
        )
    )


def test_fnd02_two_processes_have_one_writer_and_immediate_busy(tmp_path: Path) -> None:
    root = tmp_path / "process-root"
    ctx = multiprocessing.get_context("fork")
    entered, release, output = ctx.Event(), ctx.Event(), ctx.Queue()
    first = ctx.Process(
        target=_process_init, args=(str(root), entered, release, output)
    )
    first.start()
    assert entered.wait(10)
    second = FoundationTool(config(root)).execute(request())
    assert second.status == "lock_busy"
    release.set()
    first.join(10)
    assert first.exitcode == 0 and output.get(timeout=2) == "initialized"
    assert (
        FoundationTool(config(root)).execute(request()).status == "already_initialized"
    )


@pytest.mark.parametrize(
    "phase,expected_marker",
    [("before_schema", False), ("after_schema", False), ("after_marker", True)],
)
def test_fnd02_interrupted_init_preserves_evidence_and_no_transient_residue(
    tmp_path: Path, phase: str, expected_marker: bool
) -> None:
    root = tmp_path / phase

    def crash(observed: str) -> None:
        if observed == phase:
            raise RuntimeError(phase)

    receipt = FoundationTool(config(root), failpoint=crash).execute(request())
    assert receipt.status == "failed"
    assert (root / "data.db").exists()
    assert (root / "state" / "foundation-ready.json").exists() is expected_marker
    assert not list(root.rglob("foundation.lock"))
    assert not list(root.rglob(".foundation-readonly-*"))
    # Only the exact reviewed initialization checkpoints are recoverable.
    resumed = FoundationTool(config(root)).execute(request())
    assert resumed.status == "initialized" and resumed.ready


def test_fnd02_ready_init_is_byte_and_mtime_noop_and_sets_sqlite_contract(
    tmp_path: Path,
) -> None:
    root = tmp_path / "ready"
    tool = FoundationTool(config(root))
    assert tool.execute(request()).status == "initialized"
    before = _tree(root)
    assert tool.execute(request()).status == "already_initialized"
    assert _tree(root) == before
    conn = tool._connect(root / "data.db")
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 10000
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("status", "ready"), ("verify", "incompatible"), ("init", "incompatible")],
)
@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "version",
        "description",
        "code_revision",
        "content_sha256",
        "noncanonical_utc",
    ],
)
def test_fnd02_migration_receipt_tamper_requires_explicit_verify(
    tmp_path: Path, mode: str, expected: str, mutation: str
) -> None:
    root = tmp_path / f"{mode}-{mutation}"
    tool = FoundationTool(config(root))
    assert tool.execute(request()).status == "initialized"
    conn = sqlite3.connect(root / "data.db")
    if mutation == "missing":
        conn.execute("DELETE FROM schema_migrations WHERE version=2")
    elif mutation == "extra":
        conn.execute(
            "INSERT INTO schema_migrations VALUES(5,'unexpected','2026-01-01T00:00:00Z','unexpected','unexpected')"
        )
    elif mutation == "version":
        conn.execute("UPDATE schema_migrations SET version=7 WHERE version=2")
    elif mutation == "description":
        conn.execute(
            "UPDATE schema_migrations SET description='forged' WHERE version=2"
        )
    elif mutation == "code_revision":
        conn.execute(
            "UPDATE schema_migrations SET code_revision='forged' WHERE version=2"
        )
    elif mutation == "content_sha256":
        conn.execute(
            "UPDATE schema_migrations SET content_sha256='forged' WHERE version=2"
        )
    else:
        conn.execute(
            "UPDATE schema_migrations SET applied_at_utc='2026-01-01T00:00:00.000000Z' WHERE version=2"
        )
    conn.commit()
    conn.close()

    db = root / "data.db"
    marker = root / "state" / "foundation-ready.json"
    raw = root / "raw"
    before = (
        db.read_bytes(),
        db.stat().st_mtime_ns,
        marker.read_bytes(),
        marker.stat().st_mtime_ns,
        _tree(raw),
    )
    receipt = tool.execute(request(mode))
    after = (
        db.read_bytes(),
        db.stat().st_mtime_ns,
        marker.read_bytes(),
        marker.stat().st_mtime_ns,
        _tree(raw),
    )

    assert receipt.status == expected
    if expected == "incompatible":
        assert receipt.next_action == "operator_review"
        assert not receipt.ready
        assert receipt.warnings == [
            {"code": "foundation_not_ready", "summary": "migration_receipt_mismatch"}
        ]
    else:
        assert receipt.next_action == "none"
        assert receipt.ready
        assert receipt.warnings == []
    assert after == before


def test_fnd02_unknown_or_corrupt_existing_scene_never_rebuilds(tmp_path: Path) -> None:
    root = tmp_path / "unknown"
    root.mkdir(mode=0o700)
    db = root / "data.db"
    db.write_bytes(b"operator-evidence")
    db.chmod(0o600)
    original = db.read_bytes()
    receipt = FoundationTool(config(root)).execute(request())
    assert receipt.status == "failed" and db.read_bytes() == original
    assert not (root / "state" / "foundation-ready.json").exists()


def test_fnd02_manifest_verification_failure_prevents_ready_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "manifest-failure"
    monkeypatch.setattr(
        foundation,
        "validate_schema_manifest",
        lambda conn, manifest: ["forced_mismatch"],
    )
    receipt = FoundationTool(config(root)).execute(request())
    assert receipt.status == "incompatible"
    assert not (root / "state" / "foundation-ready.json").exists()
    conn = sqlite3.connect(root / "data.db")
    try:
        state = conn.execute("SELECT state FROM foundation_state").fetchone()[0]
    finally:
        conn.close()
    assert state == "initializing"


def test_fnd02_ddl_transaction_crash_rolls_back_to_recoverable_phase1(
    tmp_path: Path,
) -> None:
    root = tmp_path / "ddl-crash"

    def crash(phase: str) -> None:
        if phase == "during_schema":
            raise RuntimeError("hard-stop")

    assert (
        FoundationTool(config(root), failpoint=crash).execute(request()).status
        == "failed"
    )
    conn = sqlite3.connect(root / "data.db")
    try:
        objects = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert objects == {"foundation_state", "schema_migrations"}
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0
    finally:
        conn.close()
    receipt = FoundationTool(config(root)).execute(request())
    assert (
        receipt.status == "initialized"
        and receipt.ready
        and receipt.applied_migration_ids == [1, 2, 4]
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_object",
        "migration_row",
        "marker",
        "metadata",
        "initialized",
        "updated",
        "column",
        "default",
        "check",
        "unknown_index",
        "unknown_view",
        "unknown_trigger",
    ],
)
def test_fnd02_phase1_lookalikes_are_preserved_and_incompatible(
    tmp_path: Path, mutation: str
) -> None:
    root = tmp_path / mutation

    def crash(phase: str) -> None:
        if phase == "before_schema":
            raise RuntimeError("phase1")

    assert (
        FoundationTool(config(root), failpoint=crash).execute(request()).status
        == "failed"
    )
    if mutation == "marker":
        marker = root / "state" / "foundation-ready.json"
        marker.write_text('{"ready":true}')
        marker.chmod(0o600)
    else:
        conn = sqlite3.connect(root / "data.db")
        if mutation == "unknown_object":
            conn.execute("CREATE TABLE unknown_operator_object(id INTEGER)")
        elif mutation == "migration_row":
            conn.execute(
                "INSERT INTO schema_migrations VALUES(99,'x','2026-01-01T00:00:00Z','x','x')"
            )
        elif mutation == "metadata":
            conn.execute("UPDATE foundation_state SET implementation_version='forged'")
        elif mutation == "initialized":
            conn.execute(
                "UPDATE foundation_state SET initialized_at_utc='2026-01-01T00:00:00Z'"
            )
        elif mutation == "updated":
            conn.execute("UPDATE foundation_state SET updated_at_utc='invalid'")
        elif mutation == "unknown_index":
            conn.execute("CREATE INDEX operator_index ON foundation_state(state)")
        elif mutation == "unknown_view":
            conn.execute("CREATE VIEW operator_view AS SELECT 1 AS x")
        elif mutation == "unknown_trigger":
            conn.execute(
                "CREATE TRIGGER operator_trigger AFTER INSERT ON foundation_state BEGIN SELECT 1; END"
            )
        else:
            table = (
                "foundation_state"
                if mutation in {"column", "check"}
                else "schema_migrations"
            )
            conn.execute(f"ALTER TABLE {table} RENAME TO old_{table}")
            if mutation == "column":
                conn.execute(
                    "CREATE TABLE foundation_state(id INTEGER PRIMARY KEY,state TEXT,schema_version INTEGER,manifest_sha256 TEXT,initialized_at_utc TEXT,updated_at_utc TEXT,implementation_version TEXT,extra TEXT)"
                )
            elif mutation == "default":
                conn.execute(
                    "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,description TEXT NOT NULL,applied_at_utc TEXT NOT NULL,code_revision TEXT NOT NULL DEFAULT 'wrong',content_sha256 TEXT NOT NULL)"
                )
            else:
                conn.execute(
                    "CREATE TABLE foundation_state(id INTEGER PRIMARY KEY CHECK(id=1),state TEXT NOT NULL CHECK(state='initializing'),schema_version INTEGER NOT NULL,manifest_sha256 TEXT NOT NULL,initialized_at_utc TEXT,updated_at_utc TEXT NOT NULL,implementation_version TEXT NOT NULL)"
                )
            fields = [row[1] for row in conn.execute(f"PRAGMA table_info(old_{table})")]
            conn.execute(
                f"INSERT INTO {table}({','.join(fields)}) SELECT {','.join(fields)} FROM old_{table}"
            )
            conn.execute(f"DROP TABLE old_{table}")
        conn.commit()
        conn.close()
    before = (root / "data.db").read_bytes()
    receipt = FoundationTool(config(root)).execute(request())
    assert (
        receipt.status == "incompatible" and (root / "data.db").read_bytes() == before
    )
