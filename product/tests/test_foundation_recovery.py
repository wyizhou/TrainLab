from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from trainlab.foundation import FOUNDATION_SCHEMA_VERSION, FoundationConfig, FoundationRequest, FoundationTool


class SimulatedCrash(RuntimeError):
    pass


def config(root: Path) -> FoundationConfig:
    return FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state" / "foundation-ready.json", root / "state" / "locks" / "foundation.lock")


def request(mode: str = "init") -> FoundationRequest:
    return FoundationRequest(mode=mode, invocation_id="recovery-test", requested_at_utc="2026-07-23T00:00:00Z")


def crashing_tool(root: Path, phase: str) -> FoundationTool:
    def failpoint(observed: str) -> None:
        if observed == phase:
            raise SimulatedCrash(phase)
    return FoundationTool(config(root), failpoint=failpoint)


def state(root: Path) -> tuple[str, int, str]:
    conn = sqlite3.connect(root / "data.db")
    try:
        return tuple(conn.execute("SELECT state,schema_version,manifest_sha256 FROM foundation_state WHERE id=1").fetchone())
    finally:
        conn.close()


def test_initialization_phases_are_observable_and_exact_phase1_or_phase2_recovers(tmp_path: Path) -> None:
    before = tmp_path / "before"
    receipt = crashing_tool(before, "before_schema").execute(request())
    assert receipt.status == "failed"
    assert state(before)[0] == "initializing"
    rejected = FoundationTool(config(before)).execute(request())
    assert rejected.status == "initialized" and rejected.ready
    assert state(before)[0] == "ready"

    after_schema = tmp_path / "after-schema"
    assert crashing_tool(after_schema, "after_schema").execute(request()).status == "failed"
    assert state(after_schema)[0] == "initializing"
    assert not (after_schema / "state" / "foundation-ready.json").exists()
    recovered = FoundationTool(config(after_schema)).execute(request())
    assert recovered.status == "initialized" and recovered.ready
    assert state(after_schema)[0] == "ready"

    after_marker = tmp_path / "after-marker"
    assert crashing_tool(after_marker, "after_marker").execute(request()).status == "failed"
    assert state(after_marker)[0] == "initializing"
    assert (after_marker / "state" / "foundation-ready.json").exists()
    recovered = FoundationTool(config(after_marker)).execute(request())
    assert recovered.status == "initialized" and recovered.ready
    assert state(after_marker)[0] == "ready"


@pytest.mark.parametrize("mutation", ["unknown_table", "manifest", "migration"])
def test_initializing_mismatch_is_preserved_and_never_rebuilt(tmp_path: Path, mutation: str) -> None:
    root = tmp_path / mutation
    assert crashing_tool(root, "after_schema").execute(request()).status == "failed"
    conn = sqlite3.connect(root / "data.db")
    if mutation == "unknown_table":
        conn.execute("CREATE TABLE operator_unknown (id INTEGER)")
    elif mutation == "manifest":
        conn.execute("UPDATE foundation_state SET manifest_sha256='wrong'")
    else:
        conn.execute("UPDATE schema_migrations SET content_sha256='wrong' WHERE version=1")
    conn.commit(); conn.close()
    digest = hashlib.sha256((root / "data.db").read_bytes()).hexdigest()
    receipt = FoundationTool(config(root)).execute(request())
    assert receipt.status == "incompatible" and receipt.next_action == "operator_review"
    assert state(root)[0] == "initializing"
    assert hashlib.sha256((root / "data.db").read_bytes()).hexdigest() == digest


def test_ready_marker_and_state_disagreements_are_not_repaired(tmp_path: Path) -> None:
    root = tmp_path / "ready"
    tool = FoundationTool(config(root))
    assert tool.execute(request()).status == "initialized"
    marker = root / "state" / "foundation-ready.json"
    marker.unlink()
    receipt = tool.execute(request())
    assert receipt.status == "incompatible" and receipt.next_action == "operator_review"
    assert not marker.exists()

    other = tmp_path / "marker"
    tool = FoundationTool(config(other)); assert tool.execute(request()).status == "initialized"
    marker = other / "state" / "foundation-ready.json"
    payload = json.loads(marker.read_text()); payload["schema_version"] = FOUNDATION_SCHEMA_VERSION + 1; marker.write_text(json.dumps(payload)); marker.chmod(0o600)
    receipt = tool.execute(request())
    assert receipt.status == "incompatible" and receipt.next_action == "operator_review"
    assert json.loads(marker.read_text())["schema_version"] == FOUNDATION_SCHEMA_VERSION + 1

    initializing_marker = tmp_path / "initializing-marker"
    assert crashing_tool(initializing_marker, "after_marker").execute(request()).status == "failed"
    marker = initializing_marker / "state" / "foundation-ready.json"
    payload = json.loads(marker.read_text()); payload["manifest_sha256"] = "wrong"; marker.write_text(json.dumps(payload)); marker.chmod(0o600)
    before = hashlib.sha256((initializing_marker / "data.db").read_bytes()).hexdigest()
    receipt = FoundationTool(config(initializing_marker)).execute(request())
    assert receipt.status == "incompatible" and receipt.next_action == "operator_review"
    assert hashlib.sha256((initializing_marker / "data.db").read_bytes()).hexdigest() == before

    third = tmp_path / "state"
    tool = FoundationTool(config(third)); assert tool.execute(request()).status == "initialized"
    conn = sqlite3.connect(third / "data.db"); conn.execute("UPDATE foundation_state SET state='initializing'"); conn.commit(); conn.close()
    receipt = tool.execute(request())
    assert receipt.status == "initialized"  # an otherwise complete initializing state is the sole recovery case
    assert state(third)[0] == "ready"


def test_status_is_bounded_while_verify_checks_the_complete_manifest(tmp_path: Path) -> None:
    root = tmp_path / "status"
    tool = FoundationTool(config(root)); assert tool.execute(request()).status == "initialized"
    conn = sqlite3.connect(root / "data.db")
    conn.execute("CREATE TABLE out_of_contract (id INTEGER)")
    conn.commit(); conn.close()
    status = tool.execute(request("status"))
    verify = tool.execute(request("verify"))
    assert status.status == "ready" and status.ready
    assert verify.status == "incompatible" and not verify.ready


def test_version_corruption_permissions_and_status_matrix_preserve_evidence(tmp_path: Path) -> None:
    high = tmp_path / "high"
    tool = FoundationTool(config(high)); assert tool.execute(request()).status == "initialized"
    conn = sqlite3.connect(high / "data.db"); conn.execute("UPDATE foundation_state SET schema_version=?", (FOUNDATION_SCHEMA_VERSION + 1,)); conn.commit(); conn.close()
    receipt = tool.execute(request())
    assert receipt.status == "incompatible" and receipt.next_action == "explicit_migrate"

    corrupt = tmp_path / "corrupt"; corrupt.mkdir(mode=0o700); db = corrupt / "data.db"; db.write_bytes(b"not sqlite"); db.chmod(0o600)
    receipt = FoundationTool(config(corrupt)).execute(request())
    assert receipt.status == "failed" and receipt.next_action == "operator_review"
    assert db.read_bytes() == b"not sqlite"

    unsafe = tmp_path / "unsafe"
    assert crashing_tool(unsafe, "after_schema").execute(request()).status == "failed"
    (unsafe / "raw").chmod(0o755)
    receipt = FoundationTool(config(unsafe)).execute(request())
    assert receipt.status == "incompatible" and receipt.next_action == "operator_review"
    assert (unsafe / "raw").stat().st_mode & 0o777 == 0o755
