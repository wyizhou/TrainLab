from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from .foundation_v1_fixture import create_published_v1_database
from trainlab.foundation import FOUNDATION_SCHEMA_VERSION, FoundationConfig, FoundationRequest, FoundationTool, TABLES, VIEWS
from trainlab.foundation_sample import (
    build_acceptance_manifest,
    generate_sample_database,
    run_final_acceptance,
    scan_sample_privacy,
)


UTC="2026-07-24T12:34:56Z"


def config(root: Path) -> FoundationConfig:
    return FoundationConfig(root,root/"data.db",root/"raw",root/"state",root/"state/foundation-ready.json",root/"state/locks/foundation.lock")


def request(mode: str,target: int | None=None) -> FoundationRequest:
    return FoundationRequest(mode,f"fnd12-{mode}",UTC,target)


def tree_evidence(root: Path) -> tuple[tuple[object,...],...]:
    result=[]
    for path in [root,*root.rglob("*")]:
        info=path.stat(); relative=str(path.relative_to(root))
        if path.is_dir():
            result.append((relative,"directory",info.st_mode&0o777,info.st_mtime_ns))
        else:
            payload=path.read_bytes()
            result.append((relative,"file",info.st_mode&0o777,info.st_mtime_ns,payload,hashlib.sha256(payload).hexdigest()))
    return tuple(sorted(result))


def relational(path: Path) -> dict[str,dict[str,object]]:
    conn=sqlite3.connect(path)
    try:
        return FoundationTool.relational_fingerprints(conn)
    finally:
        conn.close()


def test_fnd12_sample_is_deterministic_complete_and_privacy_clean(tmp_path: Path) -> None:
    first=generate_sample_database(tmp_path/"first")
    second=generate_sample_database(tmp_path/"second")
    first_manifest=build_acceptance_manifest(first)
    second_manifest=build_acceptance_manifest(second)
    assert first_manifest == second_manifest
    assert (first/"sample-acceptance.json").read_bytes() == (second/"sample-acceptance.json").read_bytes()
    assert (first/"sample-metadata.json").read_bytes() == (second/"sample-metadata.json").read_bytes()
    assert len(first_manifest["tables"]) == len(TABLES)+1
    assert set(first_manifest["views"]) == set(VIEWS) and len(VIEWS) == 23
    assert set(first_manifest["fit_shapes"]) == {
        "running","bouldering","indoor_climbing","cycling","hiking","strength"
    }
    assert all(item["segments"] >= 1 and item["samples"] >= 1 for item in first_manifest["fit_shapes"].values())
    assert all(item["row_count"] > 0 for item in first_manifest["tables"].values())
    assert scan_sample_privacy(first) == []

    conn=sqlite3.connect(first/"data.db")
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT COUNT(*) FROM fit_metric_definitions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM fit_unknown_message_catalog").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM climbing_routes").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM strength_sets").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM activity_segments WHERE segment_type='strength_rest'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM daily_health WHERE is_current=0").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM daily_health WHERE is_current=1").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM analysis_artifacts WHERE artifact_kind='daily_training_advice'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM v_plan_revision_reason_events").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM analysis_artifact_inputs WHERE trust_class='prior_model_output'").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM mail_response_artifacts WHERE is_current=0").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM mail_response_artifacts WHERE is_current=1").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM analysis_deliveries").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM mail_deliveries").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM operational_alert_deliveries").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM orchestrator_runs").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM operational_incidents").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM conversation_events WHERE content_text IS NOT NULL").fetchone()[0] == 0
        for code,forbidden in (
            ("email_address","person@example.invalid"),
            ("credential","api_key=SYNTHETIC_FORBIDDEN"),
            ("raw_html","<div>synthetic forbidden markup</div>"),
            ("full_payload","full provider payload"),
            ("hidden_reasoning","hidden reasoning"),
        ):
            conn.execute(
                "UPDATE analysis_artifacts SET user_visible_text=? "
                "WHERE id=(SELECT MIN(id) FROM analysis_artifacts)",
                (forbidden,),
            )
            conn.commit()
            assert any(item.startswith(f"{code}:") for item in scan_sample_privacy(first))
        conn.execute(
            "UPDATE analysis_artifacts SET user_visible_text='synthetic visible summary' "
            "WHERE id=(SELECT MIN(id) FROM analysis_artifacts)"
        )
        conn.commit()
    finally:
        conn.close()


def test_fnd12_encrypted_backup_restore_reconciles_rows_content_and_references(tmp_path: Path) -> None:
    root=generate_sample_database(tmp_path/"sample"); tool=FoundationTool(config(root)); key=b"k"*32
    expected=relational(root/"data.db")
    source_before=tree_evidence(root)
    encrypted=tool.backup_encrypted(tmp_path/"sample.tlfb",lambda:key)
    assert tree_evidence(root) == source_before
    restored=FoundationTool.restore_encrypted(encrypted,tmp_path/"restored.db",key)
    assert relational(restored) == expected
    conn=sqlite3.connect(restored)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()
    with pytest.raises(FileExistsError):
        tool.backup_encrypted(encrypted,key)
    wrong=tmp_path/"wrong.db"
    with pytest.raises(Exception):
        FoundationTool.restore_encrypted(encrypted,wrong,b"x"*32)
    assert not wrong.exists()
    tampered=tmp_path/"tampered.tlfb"; payload=bytearray(encrypted.read_bytes()); payload[len(payload)//2]^=1; tampered.write_bytes(payload)
    tampered_target=tmp_path/"tampered.db"
    with pytest.raises(Exception):
        FoundationTool.restore_encrypted(tampered,tampered_target,key)
    assert not tampered_target.exists()
    existing_bytes=restored.read_bytes()
    with pytest.raises(FileExistsError):
        FoundationTool.restore_encrypted(encrypted,restored,key)
    assert restored.read_bytes() == existing_bytes
    assert not [path for path in tmp_path.rglob("*") if path.name.startswith((".backup-",".restore-"))]


def test_fnd12_shadow_rebuild_reconciles_all_rows_references_views_and_raw(tmp_path: Path) -> None:
    root=generate_sample_database(tmp_path/"sample"); tool=FoundationTool(config(root))
    expected=build_acceptance_manifest(root)
    source_before=tree_evidence(root)
    shadow=tool.rebuild_into(tmp_path/"shadow")
    assert tree_evidence(root) == source_before
    assert build_acceptance_manifest(shadow) == expected
    rebuilt=FoundationTool(config(shadow))
    assert rebuilt.execute(request("status")).status == "ready"
    assert rebuilt.execute(request("verify")).status == "ready"
    assert rebuilt.execute(request("init")).status == "already_initialized"
    with pytest.raises(FileExistsError):
        tool.rebuild_into(shadow)


@pytest.mark.parametrize(
    "phase",
    ["shadow_after_schema","shadow_during_copy","shadow_after_copy","shadow_before_publish"],
)
def test_fnd12_shadow_failure_before_publication_rolls_back_without_source_change(
    tmp_path: Path, phase: str
) -> None:
    root=generate_sample_database(tmp_path/"sample"); before=tree_evidence(root)

    def failpoint(observed: str) -> None:
        if observed == phase:
            raise RuntimeError(phase)

    destination=tmp_path/"shadow"
    with pytest.raises(RuntimeError,match=phase):
        FoundationTool(config(root),failpoint=failpoint).rebuild_into(destination)
    assert not destination.exists()
    assert tree_evidence(root) == before
    assert not list(tmp_path.glob(".foundation-shadow-*"))


def test_fnd12_shadow_failure_after_publication_leaves_verified_candidate(tmp_path: Path) -> None:
    root=generate_sample_database(tmp_path/"sample"); expected=build_acceptance_manifest(root)

    def failpoint(observed: str) -> None:
        if observed == "shadow_after_publish":
            raise RuntimeError(observed)

    destination=tmp_path/"shadow"
    with pytest.raises(RuntimeError,match="shadow_after_publish"):
        FoundationTool(config(root),failpoint=failpoint).rebuild_into(destination)
    assert destination.exists() and build_acceptance_manifest(destination) == expected
    assert FoundationTool(config(destination)).execute(request("verify")).status == "ready"


def test_fnd12_legacy_migration_rollback_coexists_with_current_sample(tmp_path: Path) -> None:
    sample=generate_sample_database(tmp_path/"sample"); sample_before=tree_evidence(sample)
    legacy=create_published_v1_database(tmp_path/"legacy")

    def failpoint(observed: str) -> None:
        if observed == "during_migration_transaction":
            raise RuntimeError(observed)

    failed=FoundationTool(legacy.config,failpoint=failpoint).execute(request("migrate",FOUNDATION_SCHEMA_VERSION))
    assert failed.status == "failed"
    assert tree_evidence(sample) == sample_before
    migrated=FoundationTool(legacy.config).execute(request("migrate",FOUNDATION_SCHEMA_VERSION))
    assert migrated.status == "initialized" and migrated.ready
    assert FoundationTool(config(sample)).execute(request("verify")).status == "ready"


def test_fnd12_acceptance_has_no_network_provider_model_thread_or_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args,**kwargs):
        raise AssertionError("offline acceptance attempted an external worker or call")

    monkeypatch.setattr(socket,"socket",forbidden)
    monkeypatch.setattr(threading.Thread,"start",forbidden)
    monkeypatch.setattr(subprocess,"run",forbidden)
    monkeypatch.setattr(subprocess,"Popen",forbidden)
    result=run_final_acceptance(tmp_path/"acceptance")
    assert result["status"] == "passed"
    assert result["tables_verified"] == len(TABLES)+1
    assert result["views_verified"] == 23
    assert result["fit_shapes_verified"] == 6
    assert result["privacy_findings"] == 0


def test_fnd12_acceptance_command_is_repeat_safe_and_outputs_only_receipt(tmp_path: Path) -> None:
    project=Path(__file__).resolve().parents[1]; output=tmp_path/"acceptance"
    command=[sys.executable,"scripts/verify_foundation_acceptance.py","--output-root",str(output)]
    first=subprocess.run(command,cwd=project,text=True,capture_output=True,check=False)
    assert first.returncode == 0 and first.stderr == ""
    payload=json.loads(first.stdout)
    assert payload["status"] == "passed" and payload["views_verified"] == 23
    assert "synthetic-acceptance-key" not in first.stdout
    second=subprocess.run(command,cwd=project,text=True,capture_output=True,check=False)
    assert second.returncode != 0 and "acceptance_output_root_exists" in second.stderr
