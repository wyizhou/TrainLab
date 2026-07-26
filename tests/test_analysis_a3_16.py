from __future__ import annotations

import sqlite3

import pytest

from trainlab.analysis.delivery import (
    AnalysisDeliveryError,
    AnalysisDeliveryFactory,
    AnalysisDeliveryRepository,
)


NOW = "2026-07-26T00:00:00Z"


def database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
    PRAGMA foreign_keys=ON;
    CREATE TABLE data_subjects(id INTEGER PRIMARY KEY);
    CREATE TABLE analysis_runs(id INTEGER PRIMARY KEY,run_key TEXT NOT NULL,subject_id INTEGER NOT NULL);
    CREATE TABLE analysis_artifacts(
      id INTEGER PRIMARY KEY,subject_id INTEGER NOT NULL,artifact_kind TEXT NOT NULL,
      revision_no INTEGER NOT NULL,generated_by_run_id INTEGER NOT NULL,
      content_sha256 TEXT NOT NULL,user_visible_text TEXT NOT NULL,is_current INTEGER NOT NULL
    );
    CREATE TABLE analysis_deliveries(
      id INTEGER PRIMARY KEY,subject_id INTEGER NOT NULL,idempotency_key TEXT NOT NULL UNIQUE,
      analysis_run_id INTEGER NOT NULL,delivery_kind TEXT NOT NULL,status TEXT NOT NULL,
      provider_message_id TEXT,provider_thread_id TEXT,sent_at_utc TEXT,last_verified_at_utc TEXT,
      error_code TEXT,error_summary TEXT,created_at_utc TEXT NOT NULL,updated_at_utc TEXT NOT NULL
    );
    CREATE TABLE analysis_delivery_artifacts(
      id INTEGER PRIMARY KEY,analysis_delivery_id INTEGER NOT NULL,analysis_artifact_id INTEGER NOT NULL,
      content_role TEXT NOT NULL,ordinal INTEGER NOT NULL,
      UNIQUE(analysis_delivery_id,analysis_artifact_id,content_role)
    );
    INSERT INTO data_subjects VALUES(1);
    INSERT INTO analysis_runs VALUES(1,'analysis:1:daily:2026-07-25:one',1);
    INSERT INTO analysis_artifacts VALUES(11,1,'daily_summary',1,1,'a1','old summary',1);
    INSERT INTO analysis_artifacts VALUES(12,1,'daily_training_advice',1,1,'a2','old advice',1);
    """)
    return connection


def pending(connection: sqlite3.Connection) -> int:
    result = AnalysisDeliveryFactory(connection, clock=lambda: NOW).create_pending(
        publish_receipt={"run_id": 1, "artifact_ids": {"daily_summary": 11, "daily_training_advice": 12}},
        delivery_kind="daily_report",
    )
    return result.delivery_id


def repository(connection: sqlite3.Connection) -> AnalysisDeliveryRepository:
    return AnalysisDeliveryRepository(connection, clock=lambda: "2026-07-26T00:01:00Z")


def test_load_is_exact_revision_and_current_drift_is_never_followed():
    connection = database(); delivery_id = pending(connection)
    connection.execute("UPDATE analysis_artifacts SET is_current=0 WHERE id=11")
    connection.execute("INSERT INTO analysis_artifacts VALUES(13,1,'daily_summary',2,1,'a3','new current',1)")
    loaded = repository(connection).load_pending(delivery_id, subject_id=1)
    assert [artifact.artifact_id for artifact in loaded.artifacts] == [11, 12]
    assert "old summary" in repository(connection).load_rendered(delivery_id).plain_text


def test_crash_after_provider_acceptance_or_label_failure_is_unknown_and_never_resent():
    connection = database(); delivery_id = pending(connection); repo = repository(connection)
    assert repo.claim_for_send(1, delivery_id).status == "sending"
    unknown = repo.record_delivery_unknown(
        1, delivery_id, provider_message_id="gmail-message-1", provider_thread_id="thread-1",
        error_code="analysis_delivery_label_failed",
    )
    assert unknown.status == "delivery_unknown" and unknown.provider_message_id == "gmail-message-1"
    with pytest.raises(AnalysisDeliveryError, match="transition_illegal"):
        repo.claim_for_send(1, delivery_id)
    found = repo.record_search_match(
        1, delivery_id, provider_message_id="gmail-message-1", provider_thread_id="thread-1",
        sent_at_utc=NOW, last_verified_at_utc=NOW,
    )
    assert found.status == "already_sent"
    # Exact terminal replay is a no-op; a new provider ID cannot overwrite evidence.
    assert repo.record_search_match(
        1, delivery_id, provider_message_id="gmail-message-1", provider_thread_id="thread-1",
        sent_at_utc=NOW, last_verified_at_utc=NOW,
    ) == found
    with pytest.raises(AnalysisDeliveryError, match="replay_conflict"):
        repo.record_search_match(
            1, delivery_id, provider_message_id="gmail-message-2", sent_at_utc=NOW, last_verified_at_utc=NOW,
        )


def test_second_send_claim_fails_closed_instead_of_reusing_an_in_progress_claim():
    connection = database(); delivery_id = pending(connection); repo = repository(connection)
    assert repo.claim_for_send(1, delivery_id).status == "sending"
    with pytest.raises(AnalysisDeliveryError, match="transition_illegal"):
        repo.claim_for_send(1, delivery_id)
    assert repo.read_state(delivery_id).status == "sending"


def test_unknown_without_provider_evidence_cannot_be_retried_and_failed_can_be_claimed():
    connection = database(); first = pending(connection); repo = repository(connection)
    repo.claim_for_send(1, first)
    repo.record_delivery_unknown(1, first, error_code="analysis_delivery_send_ambiguous")
    with pytest.raises(AnalysisDeliveryError, match="transition_illegal"):
        repo.claim_for_send(1, first)

    other = database(); second = pending(other); other_repo = repository(other)
    other_repo.claim_for_send(1, second)
    assert other_repo.record_failed(1, second, error_code="analysis_delivery_provider_failed").status == "failed"
    assert other_repo.claim_for_send(1, second).status == "sending"


def test_failed_delivery_can_be_reconciled_when_provider_search_finds_it():
    connection = database(); delivery_id = pending(connection); repo = repository(connection)
    repo.claim_for_send(1, delivery_id)
    repo.record_failed(1, delivery_id, error_code="analysis_delivery_provider_failed")
    state = repo.record_search_match(
        1, delivery_id, provider_message_id="gmail-message-1",
        sent_at_utc=NOW, last_verified_at_utc=NOW,
    )
    assert state.status == "already_sent"


def test_exact_provider_evidence_is_required_for_sent_or_search_match():
    connection = database(); delivery_id = pending(connection); repo = repository(connection)
    repo.claim_for_send(1, delivery_id)
    with pytest.raises(AnalysisDeliveryError, match="evidence_required"):
        repo.transition_delivery_state(1, delivery_id, "sent", provider_message_id="message-1", sent_at_utc=NOW)
    assert repo.read_state(delivery_id).status == "sending"
    with pytest.raises(AnalysisDeliveryError, match="transition_invalid"):
        repo.record_search_match(1, delivery_id, provider_message_id="bad\nmessage", sent_at_utc=NOW, last_verified_at_utc=NOW)
    assert repo.record_sent(1, delivery_id, provider_message_id="message-1", sent_at_utc=NOW, last_verified_at_utc=NOW).status == "sent"


def test_bad_relation_or_transition_rolls_back_without_changing_state():
    connection = database(); delivery_id = pending(connection); repo = repository(connection)
    repo.claim_for_send(1, delivery_id)
    with pytest.raises(AnalysisDeliveryError, match="transition_invalid"):
        repo.transition_delivery_state(1, delivery_id, "failed", error_code="not_safe")
    assert repo.read_state(delivery_id).status == "sending"
    connection.execute("UPDATE analysis_delivery_artifacts SET content_role='wrong' WHERE analysis_delivery_id=?", (delivery_id,))
    connection.commit()
    with pytest.raises(AnalysisDeliveryError, match="relation_conflict"):
        repo.record_failed(1, delivery_id, error_code="analysis_delivery_provider_failed")
    assert connection.execute("SELECT status FROM analysis_deliveries WHERE id=?", (delivery_id,)).fetchone()[0] == "sending"
