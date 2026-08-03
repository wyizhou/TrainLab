from __future__ import annotations

from hashlib import sha256
import json
import sqlite3
from types import SimpleNamespace

import pytest

from trainlab.analysis.contracts import AnalysisRequest
from trainlab.analysis.delivery import AnalysisDeliveryFactory
from trainlab.analysis.publisher import AnalysisPublishError, AnalysisPublisher
from trainlab.analysis.regenerate import RegenerateRoute


def _request(artifact_id: str = "1", reason: str = "explicit_user_request") -> AnalysisRequest:
    return AnalysisRequest(
        "regenerate", "subject", "invoke", "2026-07-26T00:00:00Z",
        artifact_id=artifact_id, regeneration_reason_code=reason,
    )


def _route(kind: str, run_kind: str, *, current: int = 1) -> RegenerateRoute:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
      CREATE TABLE data_subjects(id INTEGER PRIMARY KEY, subject_key TEXT);
      CREATE TABLE analysis_runs(id INTEGER PRIMARY KEY, analysis_kind TEXT);
      CREATE TABLE analysis_artifacts(
        id INTEGER PRIMARY KEY, subject_id INTEGER, artifact_kind TEXT,
        period_start_local_date TEXT, period_end_local_date TEXT,
        generated_by_run_id INTEGER, is_current INTEGER
      );
      INSERT INTO data_subjects VALUES(1, 'subject');
    """)
    connection.execute("INSERT INTO analysis_runs VALUES(1, ?)", (run_kind,))
    connection.execute(
        "INSERT INTO analysis_artifacts VALUES(1,1,?,?,?,1,?)",
        (kind, "2026-07-20", "2026-07-26", current),
    )
    # _source is intentionally preflight-only, so its collaborators are not used.
    return RegenerateRoute(config=None, coordinator=None, stable_views=None, runner=None, publisher=None, delivery=None, connection=connection)  # type: ignore[arg-type]


@pytest.mark.parametrize(("kind", "run_kind", "shape"), [
    ("daily_summary", "daily", "daily"),
    ("daily_training_advice", "daily", "daily"),
    ("weekly_summary", "weekly", "weekly"),
    ("weekly_training_plan", "weekly", "weekly"),
    ("weekly_training_plan", "plan_revision", "plan_revision"),
])
def test_current_supported_target_maps_to_host_owned_shape(kind: str, run_kind: str, shape: str) -> None:
    assert _route(kind, run_kind)._source(_request())["shape"] == shape


@pytest.mark.parametrize("reason", ["manual", "free text", "source_revision_Changed"])
def test_reason_catalog_is_frozen(reason: str) -> None:
    with pytest.raises(ValueError, match="analysis_regeneration_request_invalid"):
        _route("daily_summary", "daily")._source(_request(reason=reason))


def test_noncurrent_and_unsupported_targets_are_rejected() -> None:
    with pytest.raises(ValueError, match="analysis_regeneration_target_unavailable"):
        _route("daily_summary", "daily", current=0)._source(_request())
    with pytest.raises(ValueError, match="analysis_regeneration_target_unsupported"):
        _route("weekly_summary", "plan_revision")._source(_request())


@pytest.mark.parametrize("reason", [
    "source_revision_changed",
    "policy_version_changed",
    "harness_version_changed",
    "quality_issue_resolved",
    "explicit_user_request",
    "operator_correction",
])
def test_all_frozen_reason_codes_are_accepted(reason: str) -> None:
    assert _route("daily_summary", "daily")._source(_request(reason=reason))["artifact_id"] == 1


def test_regeneration_windows_follow_the_target_artifact_kind() -> None:
    advice = RegenerateRoute._target_periods({
        "shape": "daily", "kind": "daily_training_advice",
        "start": "2026-07-25", "end": "2026-07-25",
    })
    assert advice["summary"]["start_local_date"] == "2026-07-24"
    assert advice["advice"]["start_local_date"] == "2026-07-25"
    summary = RegenerateRoute._target_periods({
        "shape": "weekly", "kind": "weekly_summary",
        "start": "2026-07-13", "end": "2026-07-19",
    })
    assert summary["review"] == {
        "start_local_date": "2026-07-13",
        "end_local_date": "2026-07-19",
    }
    assert summary["plan"] == {
        "start_local_date": "2026-07-20",
        "end_local_date": "2026-07-26",
    }


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(structured: object, text: str) -> str:
    return sha256(
        _canonical({"structured_content": structured, "user_visible_text": text}).encode()
    ).hexdigest()


def _publisher_database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE data_subjects(id INTEGER PRIMARY KEY);
    CREATE TABLE analysis_runs(id INTEGER PRIMARY KEY,run_key TEXT,subject_id INTEGER,analysis_kind TEXT,status TEXT,harness_version TEXT,input_schema_version TEXT,output_schema_version TEXT,context_snapshot_json TEXT,context_snapshot_sha256 TEXT,generator_metadata_json TEXT);
    CREATE TABLE analysis_artifacts(id INTEGER PRIMARY KEY,subject_id INTEGER,artifact_kind TEXT,period_start_local_date TEXT,period_end_local_date TEXT,revision_no INTEGER,generated_by_run_id INTEGER,schema_version TEXT,structured_content_json TEXT,user_visible_text TEXT,content_sha256 TEXT,is_current INTEGER,supersedes_artifact_id INTEGER,created_at_utc TEXT,UNIQUE(subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no));
    CREATE UNIQUE INDEX current_artifact ON analysis_artifacts(subject_id,artifact_kind,period_start_local_date,period_end_local_date) WHERE is_current=1;
    CREATE TABLE analysis_artifact_inputs(id INTEGER PRIMARY KEY,analysis_run_id INTEGER,input_role TEXT,source_entity_type TEXT,source_entity_id INTEGER,source_revision_id INTEGER,source_window_start_utc TEXT,source_window_end_utc TEXT,input_sha256 TEXT,trust_class TEXT,ordinal INTEGER,UNIQUE(analysis_run_id,ordinal));
    CREATE TABLE analysis_artifact_relations(id INTEGER PRIMARY KEY,from_artifact_id INTEGER,to_artifact_id INTEGER,relation_type TEXT,created_at_utc TEXT,UNIQUE(from_artifact_id,to_artifact_id,relation_type));
    CREATE TABLE training_plans(id INTEGER PRIMARY KEY,subject_id INTEGER,analysis_artifact_id INTEGER UNIQUE,plan_start_local_date TEXT,plan_end_local_date TEXT,timezone TEXT,status TEXT,objective_json TEXT,constraints_json TEXT,created_at_utc TEXT);
    CREATE TABLE training_plan_items(id INTEGER PRIMARY KEY,training_plan_id INTEGER,item_index INTEGER,local_date TEXT,activity_kind TEXT,prescription_json TEXT,rationale_text TEXT,stop_conditions_json TEXT,UNIQUE(training_plan_id,item_index));
    CREATE TABLE analysis_deliveries(id INTEGER PRIMARY KEY,subject_id INTEGER NOT NULL,idempotency_key TEXT NOT NULL UNIQUE,analysis_run_id INTEGER NOT NULL,delivery_kind TEXT NOT NULL,status TEXT NOT NULL,provider_message_id TEXT,provider_thread_id TEXT,sent_at_utc TEXT,last_verified_at_utc TEXT,error_code TEXT,error_summary TEXT,created_at_utc TEXT NOT NULL,updated_at_utc TEXT NOT NULL);
    CREATE TABLE analysis_delivery_artifacts(id INTEGER PRIMARY KEY,analysis_delivery_id INTEGER NOT NULL,analysis_artifact_id INTEGER NOT NULL,content_role TEXT NOT NULL,ordinal INTEGER NOT NULL,UNIQUE(analysis_delivery_id,analysis_artifact_id,content_role));
    INSERT INTO data_subjects VALUES(1);
    INSERT INTO analysis_runs(id,run_key,subject_id,analysis_kind,status) VALUES
      (1,'analysis:subject:regenerate:100:invoke',1,'regeneration','started'),
      (2,'old',1,'daily','succeeded');
    """)
    artifacts = [
        (100, "daily_summary", "2026-07-24", {"summary": "ok"}, "昨日恢复稳定。"),
        (101, "daily_training_advice", "2026-07-25", {"advice": "easy"}, "今日轻松训练。"),
    ]
    for artifact_id, kind, day, structured, text in artifacts:
        conn.execute(
            "INSERT INTO analysis_artifacts VALUES(?,?,?,?,?,1,2,'1',?,?,?,1,NULL,'2026-07-25T00:00:00Z')",
            (artifact_id, 1, kind, day, day, _canonical(structured), text, _hash(structured, text)),
        )
    conn.commit()
    return conn


def _accepted() -> dict[str, object]:
    return {
        "run_key": "analysis:subject:regenerate:100:invoke",
        "subject_id": 1,
        "mode": "regenerate",
        "status": "accepted",
        "artifacts": [
            {
                "artifact_kind": "daily_summary",
                "period": {"start_local_date": "2026-07-24", "end_local_date": "2026-07-24"},
                "structured_content": {"summary": "ok"},
                "user_visible_text": "昨日恢复稳定。",
            },
            {
                "artifact_kind": "daily_training_advice",
                "period": {"start_local_date": "2026-07-25", "end_local_date": "2026-07-25"},
                "structured_content": {"advice": "easy"},
                "user_visible_text": "今日轻松训练。",
            },
        ],
    }


def _manifest() -> list[dict[str, object]]:
    return [{
        "ordinal": 0,
        "input_role": "regeneration.source_artifact",
        "source_entity_type": "analysis_artifact",
        "source_entity_id": "100",
        "source_revision_id": "1",
        "source_window": {"start_local_date": "2026-07-24", "end_local_date": "2026-07-25"},
        "input_sha256": "a" * 64,
        "trust_class": "prior_model_output",
    }]


def _evidence(rows: list[dict[str, object]]) -> dict[str, object]:
    snapshot = {"input_manifest": rows}
    canonical = _canonical(snapshot)
    return {
        "harness_version": "regenerate-v1",
        "input_schema_version": "1",
        "output_schema_version": "1",
        "context_snapshot_json": snapshot,
        "context_snapshot_sha256": sha256(canonical.encode()).hexdigest(),
        "generator_metadata_json": {"runner": "fake"},
    }


def _source() -> dict[str, object]:
    return {
        "artifact_id": 100,
        "subject_id": 1,
        "shape": "daily",
        "kind": "daily_summary",
        "start": "2026-07-24",
        "end": "2026-07-24",
    }


def test_regeneration_keeps_same_content_revision_and_exact_direct_lineage() -> None:
    conn = _publisher_database()
    rows = _manifest()
    receipt = AnalysisPublisher(conn).publish(
        run_id=1,
        accepted=_accepted(),
        input_manifest=rows,
        run_evidence=_evidence(rows),
        regeneration_source=_source(),
    )
    assert receipt.content_same is True
    assert receipt.revisions == {"daily_summary": 2, "daily_training_advice": 2}
    relations = conn.execute(
        "SELECT from_artifact_id,to_artifact_id,relation_type "
        "FROM analysis_artifact_relations WHERE relation_type='derived_from'"
    ).fetchall()
    assert [tuple(row) for row in relations] == [
        (receipt.artifact_ids["daily_summary"], 100, "derived_from")
    ]
    assert conn.execute("SELECT is_current FROM analysis_artifacts WHERE id=100").fetchone()[0] == 0


def test_regeneration_rejects_tampered_source_and_rolls_back_failpoint() -> None:
    conn = _publisher_database()
    rows = _manifest()
    tampered = _source()
    tampered["start"] = "2026-07-23"
    with pytest.raises(AnalysisPublishError, match="source_invalid"):
        AnalysisPublisher(conn).publish(
            run_id=1,
            accepted=_accepted(),
            input_manifest=rows,
            run_evidence=_evidence(rows),
            regeneration_source=tampered,
        )
    with pytest.raises(RuntimeError):
        AnalysisPublisher(conn).publish(
            run_id=1,
            accepted=_accepted(),
            input_manifest=rows,
            run_evidence=_evidence(rows),
            regeneration_source=_source(),
            failpoint=lambda stage: (_ for _ in ()).throw(RuntimeError("injected"))
            if stage == "after_artifact:daily_summary" else None,
        )
    assert conn.execute("SELECT count(*) FROM analysis_artifacts").fetchone()[0] == 2
    assert conn.execute("SELECT is_current FROM analysis_artifacts WHERE id=100").fetchone()[0] == 1


def test_pending_delivery_failure_rolls_back_regeneration_current_switch() -> None:
    class FailingDelivery:
        def create_pending_in_transaction(self, **_kwargs):
            raise RuntimeError("pending failed")

    conn = _publisher_database()
    rows = _manifest()
    with pytest.raises(RuntimeError, match="pending failed"):
        AnalysisPublisher(conn).publish_with_pending_delivery(
            run_id=1,
            accepted=_accepted(),
            input_manifest=rows,
            run_evidence=_evidence(rows),
            regeneration_source=_source(),
            delivery_factory=FailingDelivery(),
            delivery_kind="daily_report",
        )
    assert conn.execute("SELECT count(*) FROM analysis_artifacts").fetchone()[0] == 2
    assert conn.execute("SELECT is_current FROM analysis_artifacts WHERE id=100").fetchone()[0] == 1
    assert conn.execute("SELECT harness_version FROM analysis_runs WHERE id=1").fetchone()[0] is None


def test_regeneration_and_pending_delivery_commit_in_one_transaction() -> None:
    conn = _publisher_database()
    rows = _manifest()
    receipt, pending = AnalysisPublisher(conn).publish_with_pending_delivery(
        run_id=1,
        accepted=_accepted(),
        input_manifest=rows,
        run_evidence=_evidence(rows),
        regeneration_source=_source(),
        delivery_factory=AnalysisDeliveryFactory(conn),
        delivery_kind="daily_report",
    )
    assert pending.analysis_run_id == receipt.run_id == 1
    assert conn.execute("SELECT status FROM analysis_deliveries").fetchone()[0] == "pending"
    assert conn.execute("SELECT count(*) FROM analysis_delivery_artifacts").fetchone()[0] == 2
    assert conn.execute("SELECT is_current FROM analysis_artifacts WHERE id=100").fetchone()[0] == 0


def test_same_invocation_restores_persisted_ids_periods_and_content_comparison() -> None:
    conn = _publisher_database()
    rows = _manifest()
    receipt = AnalysisPublisher(conn).publish(
        run_id=1,
        accepted=_accepted(),
        input_manifest=rows,
        run_evidence=_evidence(rows),
        regeneration_source=_source(),
    )
    conn.execute("UPDATE analysis_runs SET status='succeeded' WHERE id=1")
    conn.commit()
    route = RegenerateRoute(
        config=None, coordinator=None, stable_views=None, runner=None,
        publisher=None, delivery=None, connection=conn,
        clock=lambda: "2026-07-26T00:00:01Z",
    )  # type: ignore[arg-type]
    restored = route._persisted_receipt(
        _request("100"),
        SimpleNamespace(decision=SimpleNamespace(
            run_id=1,
            run_key="analysis:subject:regenerate:100:invoke",
        )),
        "2026-07-26T00:00:00Z",
    )
    assert restored.status == "unchanged"
    assert set(restored.artifact_ids) == {
        str(receipt.artifact_ids["daily_summary"]),
        str(receipt.artifact_ids["daily_training_advice"]),
    }
    assert restored.target_periods["summary"]["start_local_date"] == "2026-07-24"
    assert restored.content_same is True
    restored.validate()
