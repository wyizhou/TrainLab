from __future__ import annotations

import json
import sqlite3
from hashlib import sha256

import pytest

from src.analysis.publisher import AnalysisPublisher, AnalysisPublishError


def database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    PRAGMA foreign_keys=ON;
    CREATE TABLE data_subjects(id INTEGER PRIMARY KEY);
    CREATE TABLE analysis_runs(id INTEGER PRIMARY KEY,run_key TEXT,subject_id INTEGER,analysis_kind TEXT,status TEXT,harness_version TEXT,input_schema_version TEXT,output_schema_version TEXT,context_snapshot_json TEXT,context_snapshot_sha256 TEXT,generator_metadata_json TEXT);
    CREATE TABLE analysis_artifacts(id INTEGER PRIMARY KEY,subject_id INTEGER,artifact_kind TEXT,period_start_local_date TEXT,period_end_local_date TEXT,revision_no INTEGER,generated_by_run_id INTEGER,schema_version TEXT,structured_content_json TEXT,user_visible_text TEXT,content_sha256 TEXT,is_current INTEGER,supersedes_artifact_id INTEGER,created_at_utc TEXT, UNIQUE(subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no));
    CREATE UNIQUE INDEX current_artifact ON analysis_artifacts(subject_id,artifact_kind,period_start_local_date,period_end_local_date) WHERE is_current=1;
    CREATE TABLE analysis_artifact_inputs(id INTEGER PRIMARY KEY,analysis_run_id INTEGER,input_role TEXT,source_entity_type TEXT,source_entity_id INTEGER,source_revision_id INTEGER,source_window_start_utc TEXT,source_window_end_utc TEXT,input_sha256 TEXT,trust_class TEXT,ordinal INTEGER,UNIQUE(analysis_run_id,ordinal));
    CREATE TABLE analysis_artifact_relations(id INTEGER PRIMARY KEY,from_artifact_id INTEGER,to_artifact_id INTEGER,relation_type TEXT,created_at_utc TEXT,UNIQUE(from_artifact_id,to_artifact_id,relation_type));
    CREATE TABLE analysis_deliveries(id INTEGER PRIMARY KEY);
    INSERT INTO data_subjects VALUES(1);
    INSERT INTO analysis_runs(id,run_key,subject_id,analysis_kind,status) VALUES(1,'analysis:1:daily:2026-07-24:one',1,'daily','started');
    """)
    return conn


def accepted(run_key: str = "analysis:1:daily:2026-07-24:one") -> dict[str, object]:
    return {
        "run_key": run_key,
        "subject_id": 1,
        "mode": "daily",
        "status": "accepted",
        "artifacts": [
            {
                "artifact_kind": "daily_summary",
                "period": {
                    "start_local_date": "2026-07-23",
                    "end_local_date": "2026-07-23",
                },
                "structured_content": {"summary": "ok"},
                "user_visible_text": "昨日恢复稳定。",
            },
            {
                "artifact_kind": "daily_training_advice",
                "period": {
                    "start_local_date": "2026-07-24",
                    "end_local_date": "2026-07-24",
                },
                "structured_content": {"advice": "easy"},
                "user_visible_text": "今日轻松训练。",
            },
        ],
    }


def manifest() -> list[dict[str, object]]:
    return [
        {
            "ordinal": 0,
            "input_role": "quality_state",
            "source_entity_type": "data_quality_issue",
            "source_entity_id": "quality:1",
            "source_revision_id": "quality-gate:synthetic",
            "source_window": {
                "start_local_date": "2026-07-23",
                "end_local_date": "2026-07-24",
            },
            "input_sha256": "a" * 64,
            "trust_class": "derived_statistic",
        }
    ]


def evidence(rows: list[dict[str, object]] | None = None) -> dict[str, object]:
    snapshot = {"input_manifest": rows if rows is not None else manifest()}
    canonical = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return {
        "harness_version": "harness-v1",
        "input_schema_version": "1",
        "output_schema_version": "1",
        "context_snapshot_json": snapshot,
        "context_snapshot_sha256": sha256(canonical.encode()).hexdigest(),
        "generator_metadata_json": {"runner": "codex-exec", "attempt": 1},
    }


def test_daily_pair_inputs_and_relations_publish_together():
    conn = database()
    receipt = AnalysisPublisher(conn, clock=lambda: "2026-07-24T00:00:00Z").publish(
        run_id=1,
        accepted=accepted(),
        input_manifest=manifest(),
        run_evidence=evidence(),
    )
    assert set(receipt.artifact_ids) == {"daily_summary", "daily_training_advice"}
    assert (
        conn.execute("SELECT count(*) FROM analysis_artifact_inputs").fetchone()[0] == 1
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM analysis_artifact_relations WHERE relation_type='paired_with'"
        ).fetchone()[0]
        == 2
    )
    assert conn.execute("SELECT count(*) FROM analysis_deliveries").fetchone()[0] == 0
    assert (
        conn.execute(
            "SELECT count(*) FROM analysis_artifacts WHERE is_current=1"
        ).fetchone()[0]
        == 2
    )
    assert (
        conn.execute("SELECT status FROM analysis_runs WHERE id=1").fetchone()[0]
        == "started"
    )
    run = conn.execute("SELECT * FROM analysis_runs WHERE id=1").fetchone()
    assert run["harness_version"] == "harness-v1"
    assert run["context_snapshot_sha256"] == evidence()["context_snapshot_sha256"]
    stored_input = conn.execute(
        "SELECT source_entity_id,source_revision_id FROM analysis_artifact_inputs"
    ).fetchone()
    assert stored_input["source_entity_id"] is None
    assert stored_input["source_revision_id"] is None


@pytest.mark.parametrize(
    "trust_class",
    (
        "provider_fact",
        "provider_derived",
        "provider_predicted",
        "user_asserted",
        "derived_statistic",
        "prior_model_output",
        "unknown",
    ),
)
def test_publisher_accepts_every_analysis_context_trust_class(trust_class: str):
    conn = database()
    rows = manifest()
    rows[0]["trust_class"] = trust_class
    receipt = AnalysisPublisher(conn).publish(
        run_id=1,
        accepted=accepted(),
        input_manifest=rows,
        run_evidence=evidence(rows),
    )
    assert receipt.input_count == 1
    assert (
        conn.execute("SELECT trust_class FROM analysis_artifact_inputs").fetchone()[0]
        == trust_class
    )


def test_revisions_are_immutable_and_current_switches_with_supersedes():
    conn = database()
    publisher = AnalysisPublisher(conn)
    first = publisher.publish(
        run_id=1,
        accepted=accepted(),
        input_manifest=manifest(),
        run_evidence=evidence(),
    )
    conn.execute(
        "INSERT INTO analysis_runs(id,run_key,subject_id,analysis_kind,status) VALUES(2,'analysis:1:daily:2026-07-24:two',1,'daily','started')"
    )
    conn.commit()
    second = publisher.publish(
        run_id=2,
        accepted=accepted("analysis:1:daily:2026-07-24:two"),
        input_manifest=manifest(),
        run_evidence=evidence(),
    )
    assert second.revisions == {"daily_summary": 2, "daily_training_advice": 2}
    assert (
        conn.execute(
            "SELECT is_current FROM analysis_artifacts WHERE id=?",
            (first.artifact_ids["daily_summary"],),
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM analysis_artifact_relations WHERE relation_type='supersedes'"
        ).fetchone()[0]
        == 2
    )


@pytest.mark.parametrize(
    "stage",
    [
        "after_run_evidence",
        "after_inputs",
        "after_artifact:daily_summary",
        "after_artifact:daily_training_advice",
        "after_relations",
    ],
)
def test_failure_at_every_transaction_stage_rolls_back(stage: str):
    conn = database()

    def fail(actual: str) -> None:
        if actual == stage:
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError):
        AnalysisPublisher(conn).publish(
            run_id=1,
            accepted=accepted(),
            input_manifest=manifest(),
            run_evidence=evidence(),
            failpoint=fail,
        )
    assert conn.execute("SELECT count(*) FROM analysis_artifacts").fetchone()[0] == 0
    assert (
        conn.execute("SELECT count(*) FROM analysis_artifact_inputs").fetchone()[0] == 0
    )
    assert (
        conn.execute("SELECT count(*) FROM analysis_artifact_relations").fetchone()[0]
        == 0
    )
    run = conn.execute("SELECT * FROM analysis_runs WHERE id=1").fetchone()
    assert run["harness_version"] is None
    assert run["context_snapshot_json"] is None


def test_non_daily_and_bad_manifest_fail_without_side_effects():
    conn = database()
    payload = accepted()
    payload["mode"] = "weekly"
    with pytest.raises(AnalysisPublishError):
        AnalysisPublisher(conn).publish(
            run_id=1,
            accepted=payload,
            input_manifest=[],
            run_evidence=evidence([]),
        )
    assert conn.execute("SELECT count(*) FROM analysis_artifacts").fetchone()[0] == 0


def test_run_evidence_hash_manifest_and_secret_are_rejected_atomically():
    conn = database()
    bad_hash = evidence()
    bad_hash["context_snapshot_sha256"] = "0" * 64
    with pytest.raises(AnalysisPublishError, match="hash_mismatch"):
        AnalysisPublisher(conn).publish(
            run_id=1,
            accepted=accepted(),
            input_manifest=manifest(),
            run_evidence=bad_hash,
        )
    secret = evidence()
    secret["generator_metadata_json"] = {"raw_model_output": "unsafe"}
    with pytest.raises(AnalysisPublishError, match="forbidden"):
        AnalysisPublisher(conn).publish(
            run_id=1,
            accepted=accepted(),
            input_manifest=manifest(),
            run_evidence=secret,
        )
    assert conn.execute("SELECT count(*) FROM analysis_artifacts").fetchone()[0] == 0
    assert (
        conn.execute("SELECT harness_version FROM analysis_runs WHERE id=1").fetchone()[
            0
        ]
        is None
    )
