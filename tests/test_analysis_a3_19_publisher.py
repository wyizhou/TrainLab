from __future__ import annotations

from hashlib import sha256
import json
import sqlite3

import pytest

from trainlab.analysis.publisher import AnalysisPublishError, AnalysisPublisher


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
    CREATE TABLE training_plans(id INTEGER PRIMARY KEY,subject_id INTEGER,analysis_artifact_id INTEGER UNIQUE,plan_start_local_date TEXT,plan_end_local_date TEXT,timezone TEXT,status TEXT,objective_json TEXT,constraints_json TEXT,created_at_utc TEXT);
    CREATE TABLE training_plan_items(id INTEGER PRIMARY KEY,training_plan_id INTEGER,item_index INTEGER,local_date TEXT,activity_kind TEXT,prescription_json TEXT,rationale_text TEXT,stop_conditions_json TEXT,UNIQUE(training_plan_id,item_index));
    CREATE TABLE conversation_events(id INTEGER PRIMARY KEY,subject_id INTEGER,event_type TEXT,actor_role TEXT,trust_level TEXT);
    INSERT INTO data_subjects VALUES(1); INSERT INTO data_subjects VALUES(2);
    INSERT INTO analysis_runs(id,run_key,subject_id,analysis_kind,status) VALUES(1,'analysis:1:revise_plan:9:31:one',1,'plan_revision','started');
    INSERT INTO analysis_runs(id,run_key,subject_id,analysis_kind,status) VALUES(2,'old',1,'weekly','succeeded');
    INSERT INTO analysis_artifacts(id,subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no,generated_by_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,is_current,created_at_utc) VALUES(8,1,'weekly_training_plan','2026-07-20','2026-07-26',1,2,'1','{}','旧计划','a',1,'2026-07-20T00:00:00Z');
    INSERT INTO training_plans(id,subject_id,analysis_artifact_id,plan_start_local_date,plan_end_local_date,timezone,status,objective_json,constraints_json,created_at_utc) VALUES(9,1,8,'2026-07-20','2026-07-26','Asia/Singapore','active','{}','{}','2026-07-20T00:00:00Z');
    INSERT INTO conversation_events VALUES(31,1,'plan_revision_reason_recorded','trainlab','system_generated');
    """)
    for index in range(7):
        day = f"2026-07-{20 + index:02d}"
        conn.execute(
            "INSERT INTO training_plan_items(training_plan_id,item_index,local_date,activity_kind,prescription_json,rationale_text,stop_conditions_json) VALUES(?,?,?,?,?,?,?)",
            (9, index, day, "rest", json.dumps({"source": index}, separators=(",", ":")), f"旧理由 {index}", json.dumps([f"old-{index}"], separators=(",", ":"))),
        )
    conn.commit()
    return conn


def items() -> list[dict[str, object]]:
    rows = []
    for index in range(4):
        day = 23 + index
        rows.append({
            "item_index": index, "local_date": f"2026-07-{day:02d}",
            "activity_kind": "running",
            "prescription": {"activity_kind": "running", "revision": index},
            "rationale_text": f"新理由 {index}",
            "stop_conditions": [f"new-{index}"],
        })
    return rows


def accepted() -> dict[str, object]:
    plan = {
        "period": {"start_local_date": "2026-07-20", "end_local_date": "2026-07-26"},
        "timezone": "Asia/Singapore", "objective": {"focus": "adjust"}, "constraints": {},
        "original_plan_id": 9, "original_artifact_id": 8, "reason_event_id": 31,
        "effective_local_date": "2026-07-23",
        "items": items(),
    }
    return {"run_key": "analysis:1:revise_plan:9:31:one", "subject_id": 1, "mode": "revise_plan", "status": "accepted", "artifacts": [{"artifact_kind": "weekly_training_plan", "period": plan["period"], "structured_content": plan, "user_visible_text": "修订计划。"}], "training_plan": plan}


def manifest() -> list[dict[str, object]]:
    source_window = {"start_local_date": "2026-07-13", "end_local_date": "2026-07-26"}
    return [
        {"ordinal": 0, "input_role": "current_plan", "source_entity_type": "training_plan", "source_entity_id": "9", "source_revision_id": "plan:9", "source_window": source_window, "input_sha256": "a" * 64, "trust_class": "prior_model_output"},
        {"ordinal": 1, "input_role": "prior_artifact", "source_entity_type": "analysis_artifact", "source_entity_id": "8", "source_revision_id": "artifact:8", "source_window": source_window, "input_sha256": "b" * 64, "trust_class": "prior_model_output"},
        {"ordinal": 2, "input_role": "revision_reason", "source_entity_type": "conversation_event", "source_entity_id": "31", "source_revision_id": "event:31", "source_window": source_window, "input_sha256": "c" * 64, "trust_class": "user_asserted"},
    ]


def evidence(rows: list[dict[str, object]]) -> dict[str, object]:
    snapshot = {"input_manifest": rows}
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"harness_version": "revision-v1", "input_schema_version": "1", "output_schema_version": "1", "context_snapshot_json": snapshot, "context_snapshot_sha256": sha256(canonical.encode()).hexdigest(), "generator_metadata_json": {"runner": "fake"}}


def publish(conn: sqlite3.Connection):
    rows = manifest()
    return AnalysisPublisher(conn, clock=lambda: "2026-07-23T00:00:00Z").publish(run_id=1, accepted=accepted(), input_manifest=rows, run_evidence=evidence(rows))


def test_revision_creates_full_snapshot_preserves_history_and_records_lineage() -> None:
    conn = database()
    receipt = publish(conn)
    assert receipt.training_plan_id is not None and receipt.superseded_plan_ids == (9,)
    assert receipt.revisions == {"weekly_training_plan": 2}
    assert conn.execute("SELECT status FROM training_plans WHERE id=9").fetchone()[0] == "superseded"
    assert conn.execute("SELECT is_current FROM analysis_artifacts WHERE id=8").fetchone()[0] == 0
    artifact = receipt.artifact_ids["weekly_training_plan"]
    assert conn.execute("SELECT supersedes_artifact_id,is_current FROM analysis_artifacts WHERE id=?", (artifact,)).fetchone()[:] == (8, 1)
    assert {row[0] for row in conn.execute("SELECT relation_type FROM analysis_artifact_relations WHERE from_artifact_id=?", (artifact,))} == {"supersedes", "derived_from", "references_prior_plan"}
    old = conn.execute("SELECT item_index,prescription_json,rationale_text,stop_conditions_json FROM training_plan_items WHERE training_plan_id=9 ORDER BY item_index").fetchall()
    new = conn.execute("SELECT item_index,prescription_json,rationale_text,stop_conditions_json FROM training_plan_items WHERE training_plan_id=? ORDER BY item_index", (receipt.training_plan_id,)).fetchall()
    assert len(new) == 7 and [tuple(row) for row in new[:3]] == [tuple(row) for row in old[:3]]
    assert json.loads(new[3][1]) == {"activity_kind": "running", "revision": 0}


@pytest.mark.parametrize("stage", ["after_run_evidence", "after_inputs", "after_artifact:weekly_training_plan", "after_plan_revision_lineage", "after_plan_supersession", "after_plan", "after_plan_item:0", "after_plan_item:6", "after_plan_items"])
def test_revision_failpoints_restore_old_current_active_state(stage: str) -> None:
    conn = database(); rows = manifest()
    with pytest.raises(RuntimeError):
        AnalysisPublisher(conn).publish(run_id=1, accepted=accepted(), input_manifest=rows, run_evidence=evidence(rows), failpoint=lambda actual: (_ for _ in ()).throw(RuntimeError("injected")) if actual == stage else None)
    assert conn.execute("SELECT status FROM training_plans WHERE id=9").fetchone()[0] == "active"
    assert conn.execute("SELECT is_current FROM analysis_artifacts WHERE id=8").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM training_plans").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM analysis_artifacts").fetchone()[0] == 1
    assert conn.execute("SELECT harness_version FROM analysis_runs WHERE id=1").fetchone()[0] is None


@pytest.mark.parametrize("mutate", [
    lambda value: value["training_plan"]["items"][0].update(local_date="2026-07-22"),
    lambda value: value["training_plan"].update(original_plan_id=99),
    lambda value: value["training_plan"].update(effective_local_date="2026-07-27"),
])
def test_revision_rejects_invalid_suffix_or_source_without_side_effects(mutate) -> None:
    conn = database(); value = accepted(); mutate(value); value["artifacts"][0]["structured_content"] = value["training_plan"]
    rows = manifest()
    with pytest.raises(AnalysisPublishError):
        AnalysisPublisher(conn).publish(run_id=1, accepted=value, input_manifest=rows, run_evidence=evidence(rows))
    assert conn.execute("SELECT status FROM training_plans WHERE id=9").fetchone()[0] == "active"
    assert conn.execute("SELECT count(*) FROM analysis_artifacts").fetchone()[0] == 1


def test_revision_requires_exact_manifest_and_unused_reason() -> None:
    conn = database(); rows = manifest(); rows.pop()
    with pytest.raises(AnalysisPublishError, match="manifest"):
        AnalysisPublisher(conn).publish(run_id=1, accepted=accepted(), input_manifest=rows, run_evidence=evidence(rows))
    conn = database()
    conn.execute("INSERT INTO analysis_runs(id,run_key,subject_id,analysis_kind,status) VALUES(3,'prior',1,'plan_revision','succeeded')")
    conn.execute("INSERT INTO analysis_artifact_inputs(analysis_run_id,input_role,source_entity_type,source_entity_id,source_revision_id,source_window_start_utc,source_window_end_utc,input_sha256,trust_class,ordinal) VALUES(3,'revision_reason','conversation_event',31,NULL,'2026-07-13T16:00:00Z','2026-07-26T16:00:00Z',?,'user_asserted',0)", ("d" * 64,))
    conn.commit(); rows = manifest()
    with pytest.raises(AnalysisPublishError, match="already_consumed"):
        AnalysisPublisher(conn).publish(run_id=1, accepted=accepted(), input_manifest=rows, run_evidence=evidence(rows))
