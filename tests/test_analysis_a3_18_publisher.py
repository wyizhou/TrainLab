from __future__ import annotations

from hashlib import sha256
import json
import sqlite3

import pytest

from trainlab.analysis.publisher import AnalysisPublishError, AnalysisPublisher


def database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE data_subjects(id INTEGER PRIMARY KEY);
        CREATE TABLE analysis_runs(id INTEGER PRIMARY KEY,run_key TEXT,subject_id INTEGER,analysis_kind TEXT,status TEXT,harness_version TEXT,input_schema_version TEXT,output_schema_version TEXT,context_snapshot_json TEXT,context_snapshot_sha256 TEXT,generator_metadata_json TEXT);
        CREATE TABLE analysis_artifacts(id INTEGER PRIMARY KEY,subject_id INTEGER,artifact_kind TEXT,period_start_local_date TEXT,period_end_local_date TEXT,revision_no INTEGER,generated_by_run_id INTEGER,schema_version TEXT,structured_content_json TEXT,user_visible_text TEXT,content_sha256 TEXT,is_current INTEGER,supersedes_artifact_id INTEGER,created_at_utc TEXT, UNIQUE(subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no));
        CREATE UNIQUE INDEX current_artifact ON analysis_artifacts(subject_id,artifact_kind,period_start_local_date,period_end_local_date) WHERE is_current=1;
        CREATE TABLE analysis_artifact_inputs(id INTEGER PRIMARY KEY,analysis_run_id INTEGER,input_role TEXT,source_entity_type TEXT,source_entity_id INTEGER,source_revision_id INTEGER,source_window_start_utc TEXT,source_window_end_utc TEXT,input_sha256 TEXT,trust_class TEXT,ordinal INTEGER,UNIQUE(analysis_run_id,ordinal));
        CREATE TABLE analysis_artifact_relations(id INTEGER PRIMARY KEY,from_artifact_id INTEGER,to_artifact_id INTEGER,relation_type TEXT,created_at_utc TEXT,UNIQUE(from_artifact_id,to_artifact_id,relation_type));
        CREATE TABLE training_plans(id INTEGER PRIMARY KEY,subject_id INTEGER,analysis_artifact_id INTEGER UNIQUE,plan_start_local_date TEXT,plan_end_local_date TEXT,timezone TEXT,status TEXT,objective_json TEXT,constraints_json TEXT,created_at_utc TEXT);
        CREATE TABLE training_plan_items(id INTEGER PRIMARY KEY,training_plan_id INTEGER,item_index INTEGER,local_date TEXT,activity_kind TEXT,prescription_json TEXT,rationale_text TEXT,stop_conditions_json TEXT,UNIQUE(training_plan_id,item_index));
        INSERT INTO data_subjects VALUES(1);
        INSERT INTO analysis_runs(id,run_key,subject_id,analysis_kind,status) VALUES(1,'analysis:1:weekly:2026-07-26:one',1,'weekly','started');
        """
    )
    return conn


def plan_items() -> list[dict[str, object]]:
    kinds = ("rest", "running", "strength", "rest", "climbing", "rest", "running")
    return [
        {
            "item_index": index,
            "local_date": f"2026-07-{26 + index:02d}" if index < 6 else "2026-08-01",
            "activity_kind": kind,
            "prescription": {"kind": kind},
            "rationale_text": "依据近期恢复安排。",
            "stop_conditions": ["acute_pain"],
        }
        for index, kind in enumerate(kinds)
    ]


def accepted(run_key: str = "analysis:1:weekly:2026-07-26:one") -> dict[str, object]:
    period = {"start_local_date": "2026-07-26", "end_local_date": "2026-08-01"}
    training_plan = {
        "period": period, "timezone": "Asia/Singapore", "objective": {"focus": "consistent"},
        "constraints": {}, "prior_artifact_state": {"summary": "no_prior_artifact", "plan": "no_prior_artifact"},
        "items": plan_items(),
    }
    return {
        "run_key": run_key,
        "subject_id": 1,
        "mode": "weekly",
        "status": "accepted",
        "artifacts": [
            {"artifact_kind": "weekly_summary", "period": {"start_local_date": "2026-07-19", "end_local_date": "2026-07-25"}, "structured_content": {"summary": "ok"}, "user_visible_text": "本周恢复与训练已复盘。"},
            {"artifact_kind": "weekly_training_plan", "period": period, "structured_content": training_plan, "user_visible_text": "未来七天计划已制定。"},
        ],
        "training_plan": training_plan,
    }


def manifest(*, prior_artifact_id: int | None = None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [{
        "ordinal": 0, "input_role": "quality_state", "source_entity_type": "data_quality_issue",
        "source_entity_id": "quality:1", "source_revision_id": "quality-gate:synthetic",
        "source_window": {"start_local_date": "2026-06-21", "end_local_date": "2026-07-25"},
        "input_sha256": "a" * 64, "trust_class": "derived_statistic",
    }]
    if prior_artifact_id is not None:
        rows.append({
            "ordinal": 1, "input_role": "prior_artifact", "source_entity_type": "analysis_artifact",
            "source_entity_id": str(prior_artifact_id), "source_revision_id": f"artifact:{prior_artifact_id}",
            "source_window": {"start_local_date": "2026-07-12", "end_local_date": "2026-07-25"},
            "input_sha256": "b" * 64, "trust_class": "prior_model_output",
        })
    return rows


def evidence(rows: list[dict[str, object]]) -> dict[str, object]:
    snapshot = {"input_manifest": rows}
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "harness_version": "weekly-harness-v1", "input_schema_version": "1", "output_schema_version": "1",
        "context_snapshot_json": snapshot, "context_snapshot_sha256": sha256(canonical.encode()).hexdigest(),
        "generator_metadata_json": {"runner": "fake", "attempt": 1},
    }


def test_weekly_pair_plan_and_seven_items_publish_atomically() -> None:
    conn = database()
    rows = manifest()
    receipt = AnalysisPublisher(conn, clock=lambda: "2026-07-26T00:00:00Z").publish(
        run_id=1, accepted=accepted(), input_manifest=rows, run_evidence=evidence(rows)
    )
    assert set(receipt.artifact_ids) == {"weekly_summary", "weekly_training_plan"}
    assert receipt.training_plan_id is not None and receipt.superseded_plan_ids == ()
    assert conn.execute("SELECT count(*) FROM analysis_artifact_relations WHERE relation_type='paired_with'").fetchone()[0] == 2
    plan = conn.execute("SELECT * FROM training_plans WHERE id=?", (receipt.training_plan_id,)).fetchone()
    assert plan["status"] == "active" and plan["timezone"] == "Asia/Singapore"
    items = conn.execute("SELECT item_index,local_date,activity_kind FROM training_plan_items WHERE training_plan_id=? ORDER BY item_index", (receipt.training_plan_id,)).fetchall()
    assert [(row["item_index"], row["local_date"], row["activity_kind"]) for row in items] == [
        (0, "2026-07-26", "rest"), (1, "2026-07-27", "running"), (2, "2026-07-28", "strength"),
        (3, "2026-07-29", "rest"), (4, "2026-07-30", "climbing"), (5, "2026-07-31", "rest"), (6, "2026-08-01", "running"),
    ]


def test_weekly_prior_relations_and_overlapping_plans_are_preserved_then_superseded() -> None:
    conn = database()
    conn.execute("INSERT INTO analysis_runs(id,run_key,subject_id,analysis_kind,status) VALUES(2,'old',1,'weekly','succeeded')")
    conn.execute("INSERT INTO analysis_artifacts(id,subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no,generated_by_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,is_current,created_at_utc) VALUES(8,1,'weekly_training_plan','2026-07-20','2026-07-26',1,2,'1','{}','旧计划','c',1,'2026-07-20T00:00:00Z')")
    conn.execute("INSERT INTO training_plans(id,subject_id,analysis_artifact_id,plan_start_local_date,plan_end_local_date,timezone,status,objective_json,constraints_json,created_at_utc) VALUES(9,1,8,'2026-07-20','2026-07-26','Asia/Singapore','active','{}','{}','2026-07-20T00:00:00Z')")
    conn.commit()
    rows = manifest(prior_artifact_id=8)
    receipt = AnalysisPublisher(conn).publish(run_id=1, accepted=accepted(), input_manifest=rows, run_evidence=evidence(rows))
    assert receipt.superseded_plan_ids == (9,)
    assert conn.execute("SELECT status FROM training_plans WHERE id=9").fetchone()[0] == "superseded"
    relations = conn.execute("SELECT from_artifact_id,relation_type FROM analysis_artifact_relations WHERE to_artifact_id=8 ORDER BY from_artifact_id").fetchall()
    assert len(relations) == 2 and {row["relation_type"] for row in relations} == {"references_prior_plan"}


def test_only_prior_weekly_artifacts_create_weekly_reference_relations() -> None:
    conn = database()
    conn.execute("INSERT INTO analysis_runs(id,run_key,subject_id,analysis_kind,status) VALUES(2,'old',1,'weekly','succeeded')")
    conn.executemany(
        "INSERT INTO analysis_artifacts(id,subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no,generated_by_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,is_current,created_at_utc) VALUES(?,1,?,?,?,1,2,'1','{}','旧内容','c',1,'2026-07-20T00:00:00Z')",
        (
            (7, "weekly_summary", "2026-07-13", "2026-07-19"),
            (8, "weekly_training_plan", "2026-07-19", "2026-07-25"),
            (9, "daily_summary", "2026-07-25", "2026-07-25"),
        ),
    )
    conn.commit()
    rows = manifest()
    for artifact_id in (7, 8, 9):
        rows.append({
            "ordinal": len(rows), "input_role": "prior_artifact",
            "source_entity_type": "analysis_artifact",
            "source_entity_id": str(artifact_id),
            "source_revision_id": f"artifact:{artifact_id}",
            "source_window": {"start_local_date": "2026-07-13", "end_local_date": "2026-07-25"},
            "input_sha256": f"{artifact_id:064x}",
            "trust_class": "prior_model_output",
        })
    AnalysisPublisher(conn).publish(
        run_id=1, accepted=accepted(), input_manifest=rows,
        run_evidence=evidence(rows),
    )
    relations = conn.execute(
        "SELECT to_artifact_id,relation_type FROM analysis_artifact_relations "
        "WHERE relation_type LIKE 'references_prior_%' ORDER BY to_artifact_id,relation_type"
    ).fetchall()
    assert {(row["to_artifact_id"], row["relation_type"]) for row in relations} == {
        (7, "references_prior_summary"),
        (8, "references_prior_plan"),
    }


@pytest.mark.parametrize("stage", [
    "after_run_evidence", "after_inputs", "after_artifact:weekly_summary", "after_artifact:weekly_training_plan",
    "after_relations", "after_plan_supersession", "after_plan", "after_plan_item:0", "after_plan_item:6", "after_plan_items",
])
def test_weekly_failpoints_roll_back_artifacts_plans_and_items(stage: str) -> None:
    conn = database()
    rows = manifest()
    with pytest.raises(RuntimeError):
        AnalysisPublisher(conn).publish(
            run_id=1, accepted=accepted(), input_manifest=rows, run_evidence=evidence(rows),
            failpoint=lambda actual: (_ for _ in ()).throw(RuntimeError("injected")) if actual == stage else None,
        )
    assert conn.execute("SELECT count(*) FROM analysis_artifacts").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM training_plans").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM training_plan_items").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM analysis_artifact_relations").fetchone()[0] == 0
    assert conn.execute("SELECT harness_version FROM analysis_runs WHERE id=1").fetchone()[0] is None


def test_plan_supersession_failure_restores_existing_active_plan() -> None:
    conn = database()
    conn.execute("INSERT INTO analysis_runs(id,run_key,subject_id,analysis_kind,status) VALUES(2,'old',1,'weekly','succeeded')")
    conn.execute("INSERT INTO analysis_artifacts(id,subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no,generated_by_run_id,schema_version,structured_content_json,user_visible_text,content_sha256,is_current,created_at_utc) VALUES(8,1,'weekly_training_plan','2026-07-20','2026-07-26',1,2,'1','{}','旧计划','c',1,'2026-07-20T00:00:00Z')")
    conn.execute("INSERT INTO training_plans(id,subject_id,analysis_artifact_id,plan_start_local_date,plan_end_local_date,timezone,status,objective_json,constraints_json,created_at_utc) VALUES(9,1,8,'2026-07-20','2026-07-26','Asia/Singapore','active','{}','{}','2026-07-20T00:00:00Z')")
    conn.commit()
    rows = manifest()
    with pytest.raises(RuntimeError):
        AnalysisPublisher(conn).publish(
            run_id=1, accepted=accepted(), input_manifest=rows, run_evidence=evidence(rows),
            failpoint=lambda stage: (_ for _ in ()).throw(RuntimeError("injected")) if stage == "after_plan_supersession" else None,
        )
    assert conn.execute("SELECT status FROM training_plans WHERE id=9").fetchone()[0] == "active"
    assert conn.execute("SELECT count(*) FROM analysis_artifacts WHERE id!=8").fetchone()[0] == 0


@pytest.mark.parametrize("mutate", [
    lambda payload: payload["training_plan"].update({"timezone": "UTC"}),  # type: ignore[index]
    lambda payload: payload["training_plan"].update({"prior_artifact_state": {"summary": "unknown", "plan": "no_prior_artifact"}}),  # type: ignore[index]
    lambda payload: payload["training_plan"].update({"items": plan_items()[:-1]}),  # type: ignore[index]
    lambda payload: payload["training_plan"]["items"][1].update({"local_date": "2026-07-29"}),  # type: ignore[index]
    lambda payload: payload["training_plan"]["items"][1].update({"activity_kind": "cycling"}),  # type: ignore[index]
])
def test_weekly_invalid_plan_never_publishes(mutate) -> None:
    conn = database()
    payload = accepted()
    mutate(payload)
    rows = manifest()
    with pytest.raises(AnalysisPublishError, match="weekly_plan"):
        AnalysisPublisher(conn).publish(run_id=1, accepted=payload, input_manifest=rows, run_evidence=evidence(rows))
    assert conn.execute("SELECT count(*) FROM analysis_artifacts").fetchone()[0] == 0


def test_weekly_plan_artifact_content_must_match_complete_structured_plan() -> None:
    conn = database()
    payload = accepted()
    payload["artifacts"][1]["structured_content"] = {"different": True}  # type: ignore[index]
    rows = manifest()
    with pytest.raises(AnalysisPublishError, match="artifact_mismatch"):
        AnalysisPublisher(conn).publish(run_id=1, accepted=payload, input_manifest=rows, run_evidence=evidence(rows))
    assert conn.execute("SELECT count(*) FROM analysis_artifacts").fetchone()[0] == 0
