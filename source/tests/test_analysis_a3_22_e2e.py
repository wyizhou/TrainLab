"""A3-22 synthetic cross-module safety evidence.

These checks intentionally use only in-memory SQLite state and injected
providers.  They must never start the Codex runner, a Gmail client, or a
background worker.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from src.analysis.contracts import AnalysisRequest
from src.analysis.delivery_service import AnalysisDeliveryService
from src.analysis.gmail_delivery import GmailDeliveryError, GmailDeliveryReceipt
from src.analysis.publisher import AnalysisPublisher
from src.analysis.status import AnalysisStatusQueryService

NOW = "2026-07-26T00:00:00Z"


class _DeliveryRepository:
    """Minimal synthetic A3-16 repository; no provider or filesystem state."""

    def __init__(self, status: str = "pending") -> None:
        self.state = SimpleNamespace(
            delivery_id=1,
            subject_id=1,
            analysis_run_id=1,
            status=status,
            provider_message_id=None,
            provider_thread_id=None,
            error_code=None,
        )
        self.calls: list[str] = []

    def load_pending(self, delivery_id: int):
        assert delivery_id == 1
        return SimpleNamespace(
            delivery_id=1,
            subject_id=1,
            idempotency_key="analysis-delivery:v1:synthetic",
        )

    def read_state(self, delivery_id: int, subject_id: int):
        assert (delivery_id, subject_id) == (1, 1)
        return self.state

    def load_rendered(self, delivery_id: int, subject_id: int):
        assert (delivery_id, subject_id) == (1, 1)
        return SimpleNamespace(
            subject="[TrainLab] synthetic", plain_text="safe", html="<p>safe</p>"
        )

    def _set(self, status: str, **values: object):
        self.state.status = status
        for key, value in values.items():
            setattr(self.state, key, value)
        return self.state

    def claim_for_send(self, _subject_id: int, _delivery_id: int):
        self.calls.append("claim")
        return self._set("sending")

    def record_delivery_unknown(
        self, _subject_id: int, _delivery_id: int, **values: object
    ):
        self.calls.append("unknown")
        return self._set("delivery_unknown", **values)

    def record_search_match(
        self, _subject_id: int, _delivery_id: int, **values: object
    ):
        self.calls.append("match")
        return self._set("already_sent", **values)

    def record_failed(self, _subject_id: int, _delivery_id: int, **values: object):
        self.calls.append("failed")
        return self._set("failed", **values)

    def record_sent(self, _subject_id: int, _delivery_id: int, **values: object):
        self.calls.append("sent")
        return self._set("sent", **values)


class _Gateway:
    def __init__(
        self, *, failure: Exception | None = None, reconciliation=None
    ) -> None:
        self.failure = failure
        self.reconciliation = reconciliation
        self.calls: list[str] = []

    def deliver(self, **_: object):
        self.calls.append("deliver")
        if self.failure:
            raise self.failure
        return GmailDeliveryReceipt("sent", "synthetic-message", None, "label", None)

    def reconcile(self, **_: object):
        self.calls.append("reconcile")
        return self.reconciliation


def _status_request() -> AnalysisRequest:
    return AnalysisRequest.from_dict(
        {
            "schema_version": "1",
            "mode": "status",
            "subject_id": "synthetic",
            "invocation_id": None,
            "run_key": None,
            "summary_local_date": None,
            "advice_local_date": None,
            "as_of_local_date": None,
            "plan_id": None,
            "reason_event_id": None,
            "effective_local_date": None,
            "artifact_id": None,
            "delivery_id": None,
            "regeneration_reason_code": None,
            "requested_at_utc": NOW,
        }
    )


def _status_database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE data_subjects(id INTEGER PRIMARY KEY, subject_key TEXT, is_active INTEGER);
    CREATE TABLE analysis_runs(id INTEGER PRIMARY KEY, run_key TEXT, subject_id INTEGER, status TEXT, started_at_utc TEXT, completed_at_utc TEXT);
    CREATE TABLE analysis_artifacts(id INTEGER PRIMARY KEY, subject_id INTEGER, artifact_kind TEXT, period_start_local_date TEXT, period_end_local_date TEXT, revision_no INTEGER, is_current INTEGER, user_visible_text TEXT, structured_content_json TEXT);
    CREATE TABLE training_plans(id INTEGER PRIMARY KEY, subject_id INTEGER, plan_start_local_date TEXT, plan_end_local_date TEXT, status TEXT, created_at_utc TEXT, objective_json TEXT, constraints_json TEXT);
    CREATE TABLE analysis_deliveries(id INTEGER PRIMARY KEY, subject_id INTEGER, delivery_kind TEXT, status TEXT, created_at_utc TEXT, updated_at_utc TEXT, provider_message_id TEXT, provider_thread_id TEXT, error_summary TEXT);
    CREATE TABLE analysis_delivery_artifacts(analysis_delivery_id INTEGER, analysis_artifact_id INTEGER, ordinal INTEGER);
    CREATE TABLE data_quality_issues(id INTEGER PRIMARY KEY, entity_type TEXT, entity_id INTEGER, issue_code TEXT, severity TEXT, status TEXT, details_json TEXT);
    CREATE VIEW v_current_analysis_artifacts AS SELECT * FROM analysis_artifacts WHERE is_current=1;
    CREATE VIEW v_current_training_plans AS SELECT * FROM training_plans WHERE status IN ('proposed', 'active');
    CREATE VIEW v_open_data_quality_issues AS SELECT * FROM data_quality_issues WHERE status IN ('open', 'acknowledged');
    INSERT INTO data_subjects VALUES(1, 'synthetic', 1);
    INSERT INTO analysis_runs VALUES(1, 'analysis:synthetic:daily:2026-07-25:one', 1, 'succeeded', '2026-07-26T00:00:00Z', '2026-07-26T00:01:00Z');
    INSERT INTO analysis_artifacts VALUES(11, 1, 'daily_summary', '2026-07-25', '2026-07-25', 1, 1, 'PRIVATE BODY', '{"private":"value"}');
    INSERT INTO analysis_deliveries VALUES(21, 1, 'daily_report', 'delivery_unknown', '2026-07-26T00:00:00Z', '2026-07-26T00:02:00Z', 'provider-message', 'provider-thread', 'PRIVATE ERROR');
    INSERT INTO analysis_delivery_artifacts VALUES(21, 11, 0);
    """)
    return conn


def test_synthetic_unknown_delivery_reconciles_without_a_second_send_or_background_worker():
    before = {thread.ident for thread in threading.enumerate()}
    repository = _DeliveryRepository()
    timeout = GmailDeliveryError("gmail_delivery_timeout", may_have_sent=True)
    gateway = _Gateway(failure=timeout)
    service = AnalysisDeliveryService(repository, gateway, clock=lambda: NOW)

    unknown = service.execute(1, "retry_delivery")
    assert unknown.status == "delivery_unknown"
    assert repository.calls == ["claim", "unknown"] and gateway.calls == ["deliver"]

    # Unknown is reconcile-only; retry cannot contact a provider again.
    assert service.execute(1, "retry_delivery").next_action == "reconcile_delivery"
    assert gateway.calls == ["deliver"]
    gateway.reconciliation = GmailDeliveryReceipt(
        "already_sent", "synthetic-message", None, "label", NOW
    )
    reconciled = service.execute(1, "reconcile_delivery")
    assert reconciled.status == "already_sent"
    assert gateway.calls == ["deliver", "reconcile"]
    assert {thread.ident for thread in threading.enumerate()} == before


def test_synthetic_status_is_select_only_and_redacts_provider_and_artifact_bodies():
    conn = _status_database()
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    receipt = AnalysisStatusQueryService(conn, clock=lambda: NOW).execute(
        _status_request()
    )
    payload = receipt.as_dict()
    assert receipt.status == "succeeded"
    assert all(
        statement.lstrip().upper().startswith("SELECT") for statement in statements
    )
    encoded = json.dumps(payload, sort_keys=True)
    for secret in (
        "PRIVATE",
        "provider-message",
        "provider-thread",
        "structured_content_json",
        "user_visible_text",
    ):
        assert secret not in encoded


def test_synthetic_publish_fault_rolls_back_before_delivery_seed():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE data_subjects(id INTEGER PRIMARY KEY);
    CREATE TABLE analysis_runs(id INTEGER PRIMARY KEY,run_key TEXT,subject_id INTEGER,analysis_kind TEXT,status TEXT,harness_version TEXT,input_schema_version TEXT,output_schema_version TEXT,context_snapshot_json TEXT,context_snapshot_sha256 TEXT,generator_metadata_json TEXT);
    CREATE TABLE analysis_artifacts(id INTEGER PRIMARY KEY,subject_id INTEGER,artifact_kind TEXT,period_start_local_date TEXT,period_end_local_date TEXT,revision_no INTEGER,generated_by_run_id INTEGER,schema_version TEXT,structured_content_json TEXT,user_visible_text TEXT,content_sha256 TEXT,is_current INTEGER,supersedes_artifact_id INTEGER,created_at_utc TEXT);
    CREATE UNIQUE INDEX current_artifact ON analysis_artifacts(subject_id,artifact_kind,period_start_local_date,period_end_local_date) WHERE is_current=1;
    CREATE TABLE analysis_artifact_inputs(id INTEGER PRIMARY KEY,analysis_run_id INTEGER,input_role TEXT,source_entity_type TEXT,source_entity_id INTEGER,source_revision_id INTEGER,source_window_start_utc TEXT,source_window_end_utc TEXT,input_sha256 TEXT,trust_class TEXT,ordinal INTEGER);
    CREATE TABLE analysis_artifact_relations(id INTEGER PRIMARY KEY,from_artifact_id INTEGER,to_artifact_id INTEGER,relation_type TEXT,created_at_utc TEXT);
    CREATE TABLE analysis_deliveries(id INTEGER PRIMARY KEY);
    INSERT INTO data_subjects VALUES(1);
    INSERT INTO analysis_runs VALUES(1,'analysis:synthetic:daily:2026-07-25:one',1,'daily','started',NULL,NULL,NULL,NULL,NULL,NULL);
    """)
    accepted = {
        "run_key": "analysis:synthetic:daily:2026-07-25:one",
        "subject_id": 1,
        "mode": "daily",
        "status": "accepted",
        "artifacts": [
            {
                "artifact_kind": "daily_summary",
                "period": {
                    "start_local_date": "2026-07-25",
                    "end_local_date": "2026-07-25",
                },
                "structured_content": {"summary": "ok"},
                "user_visible_text": "摘要",
            },
            {
                "artifact_kind": "daily_training_advice",
                "period": {
                    "start_local_date": "2026-07-26",
                    "end_local_date": "2026-07-26",
                },
                "structured_content": {"advice": "rest"},
                "user_visible_text": "建议",
            },
        ],
    }
    manifest = [
        {
            "ordinal": 0,
            "input_role": "quality_state",
            "source_entity_type": "data_quality_issue",
            "source_entity_id": "quality:1",
            "source_revision_id": "quality:synthetic",
            "source_window": {
                "start_local_date": "2026-07-25",
                "end_local_date": "2026-07-26",
            },
            "input_sha256": "a" * 64,
            "trust_class": "derived_statistic",
        }
    ]
    snapshot = {"input_manifest": manifest}
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    evidence = {
        "harness_version": "synthetic",
        "input_schema_version": "1",
        "output_schema_version": "1",
        "context_snapshot_json": snapshot,
        "context_snapshot_sha256": __import__("hashlib")
        .sha256(canonical.encode())
        .hexdigest(),
        "generator_metadata_json": {"adapter": "fake"},
    }
    with pytest.raises(RuntimeError, match="fault"):
        AnalysisPublisher(conn).publish(
            run_id=1,
            accepted=accepted,
            input_manifest=manifest,
            run_evidence=evidence,
            failpoint=lambda stage: (
                (_ for _ in ()).throw(RuntimeError("fault"))
                if stage == "after_artifact:daily_summary"
                else None
            ),
        )
    assert conn.execute("SELECT count(*) FROM analysis_artifacts").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM analysis_deliveries").fetchone()[0] == 0
