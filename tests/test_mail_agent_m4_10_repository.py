from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.mail_agent.contracts import MailRequest
from trainlab.mail_agent.delivery import MailResponseDeliveryService
from trainlab.mail_agent.delivery_repository import MailDeliveryRepository, MailDeliveryRepositoryError
from trainlab.mail_agent.fact_gate import FactGateDecision
from trainlab.mail_agent.gmail_adapter import SendReceipt
from trainlab.mail_agent.publisher import MailResponsePublisher
from trainlab.mail_agent.repository import MailRepository

NOW = "2026-07-24T00:00:00Z"
LATER = "2026-07-24T00:01:00Z"


def prepared(tmp_path: Path):
    root = tmp_path / "f"
    cfg = FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state" / "foundation-ready.json", root / "state" / "locks" / "foundation.lock")
    assert FoundationTool(cfg).execute(FoundationRequest("init", "m410", NOW)).status == "initialized"
    conn = sqlite3.connect(root / "data.db"); conn.row_factory = sqlite3.Row; conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("INSERT INTO data_subjects(subject_key,created_at_utc) VALUES('s',?)", (NOW,)); subject = conn.execute("SELECT id FROM data_subjects").fetchone()[0]
    conn.execute("INSERT INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) VALUES(?,'gmail','email',?,1,?,?)", (subject, "e" * 64, NOW, NOW)); identity = conn.execute("SELECT id FROM subject_identities").fetchone()[0]
    conn.execute("INSERT INTO raw_objects(sha256,relative_path,media_type,size_bytes,provider,resource_kind,fetched_at_utc) VALUES(?,?,?,?,?,?,?)", ("a" * 64, "gmail/json/m.json", "application/json", 1, "gmail", "message_json", NOW)); raw = conn.execute("SELECT id FROM raw_objects").fetchone()[0]
    conn.execute("INSERT INTO source_revisions(provider,resource_kind,provider_object_id,revision_no,raw_object_id,payload_hash,is_current,parsed_at_utc) VALUES('gmail','message_json','m',1,?,?,1,?)", (raw, "b" * 64, NOW)); source = conn.execute("SELECT id FROM source_revisions").fetchone()[0]
    conn.execute("INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) VALUES(?,'thread-1',1)", (subject,)); thread = conn.execute("SELECT id FROM mail_threads").fetchone()[0]
    conn.execute("INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role,received_at_utc,body_text,body_sha256,source_revision_id,processing_state) VALUES(?,'m','inbound','user',?,'请求',?,?, 'analyzing')", (thread, NOW, "c" * 64, source)); message = conn.execute("SELECT id FROM mail_messages").fetchone()[0]
    conn.commit(); repo = MailRepository(conn, clock=lambda: NOW)
    run = repo.start_or_resume_run(MailRequest("process", subject, "inv", NOW, mail_message_ids=("m",)))
    context = {"run": {"id": run.id, "run_key": run.run_key}, "trigger_message": {"id": message, "thread_id": thread, "provider_thread_id": "thread-1", "timestamp_utc": NOW}, "input_manifest": [{"ordinal": 0, "input_role": "trigger_message", "source_entity_type": "mail_message", "source_entity_id": message, "source_revision_id": source, "input_sha256": "d" * 64, "trust_class": "user_asserted"}]}
    decision = FactGateDecision("1", "accepted", "reply", "mail_fact_gate_accepted", subject, run.id, run.run_key, message, thread, source, None, ())
    result = {"schema_version": "1", "run_key": run.run_key, "trigger_message_id": message, "response": {"response_kind": "mail_response", "subject_intent": "reply", "structured_content": {}, "user_visible_text": "好的", "requires_thread_reply": True}}
    published = MailResponsePublisher(repo).publish(decision, context, result)
    return conn, subject, identity, message, published.delivery_id


def test_claim_and_receipt_are_one_exact_outbound_evidence_chain(tmp_path: Path) -> None:
    conn, subject, identity, message, delivery = prepared(tmp_path)
    store = MailDeliveryRepository(MailRepository(conn, clock=lambda: NOW), clock=lambda: LATER)
    target = store.claim_pending_delivery(subject, delivery)
    assert target.status == "sending" and conn.execute("SELECT processing_state FROM mail_messages WHERE id=?", (message,)).fetchone()[0] == "sending"
    saved = store.record_provider_receipt(subject, delivery, identity, provider_message_id="out-1", provider_thread_id="thread-1", sent_at_utc=LATER, status="sent", label_applied=True)
    assert saved.status == "sent" and not saved.label_pending
    assert conn.execute("SELECT processing_state FROM mail_messages WHERE id=?", (message,)).fetchone()[0] == "sent"
    assert conn.execute("SELECT count(*) FROM conversation_events WHERE event_type='mail_response_sent' AND mail_delivery_id=?", (delivery,)).fetchone()[0] == 1
    assert conn.execute("SELECT status FROM mail_agent_items WHERE mail_delivery_id=? AND stage='verify'", (delivery,)).fetchone()[0] == "succeeded"


def test_label_failure_records_verify_deferred_without_resending(tmp_path: Path) -> None:
    conn, subject, identity, _, delivery = prepared(tmp_path)
    store = MailDeliveryRepository(MailRepository(conn, clock=lambda: NOW), clock=lambda: LATER)
    store.claim_pending_delivery(subject, delivery)
    saved = store.record_provider_receipt(subject, delivery, identity, provider_message_id="out-1", provider_thread_id="thread-1", sent_at_utc=LATER, status="sent", label_applied=False, label_retry_at_utc="2026-07-24T00:10:00Z")
    assert saved.label_pending
    row = conn.execute("SELECT status,error_code,next_retry_at_utc FROM mail_agent_items WHERE mail_delivery_id=? AND stage='verify'", (delivery,)).fetchone()
    assert tuple(row) == ("deferred", "label_pending", "2026-07-24T00:10:00Z")
    assert conn.execute("SELECT status FROM mail_deliveries WHERE id=?", (delivery,)).fetchone()[0] == "sent"


def test_thread_conflict_preserves_claimed_delivery_for_reconcile(tmp_path: Path) -> None:
    conn, subject, identity, message, delivery = prepared(tmp_path)
    store = MailDeliveryRepository(MailRepository(conn, clock=lambda: NOW), clock=lambda: LATER)
    store.claim_pending_delivery(subject, delivery)
    with pytest.raises(MailDeliveryRepositoryError, match="mail_delivery_thread_conflict"):
        store.record_provider_receipt(subject, delivery, identity, provider_message_id="out-1", provider_thread_id="other", sent_at_utc=LATER, status="sent", label_applied=True)
    assert conn.execute("SELECT status FROM mail_deliveries WHERE id=?", (delivery,)).fetchone()[0] == "sending"
    assert conn.execute("SELECT processing_state FROM mail_messages WHERE id=?", (message,)).fetchone()[0] == "sending"


def test_delivery_service_and_sqlite_repository_form_one_real_chain(tmp_path: Path) -> None:
    conn, subject, identity, message, delivery = prepared(tmp_path)
    repository = MailDeliveryRepository(
        MailRepository(conn, clock=lambda: NOW),
        verified_identity_id=identity,
        clock=lambda: LATER,
    )

    class Adapter:
        def search_run_id(self, **_):
            return ()

        def send_html_self(self, **kwargs):
            assert kwargs["thread_id"] == "thread-1"
            return SendReceipt("out-1", "thread-1", False)

        def apply_trainlab_label(self, **_):
            return None

    response_id = conn.execute(
        "SELECT mail_response_artifact_id FROM mail_delivery_artifacts "
        "WHERE mail_delivery_id=?",
        (delivery,),
    ).fetchone()[0]
    result = MailResponseDeliveryService(repository, Adapter()).deliver(
        subject_id=subject, response_artifact_id=response_id
    )
    assert result.status == "sent"
    assert conn.execute(
        "SELECT status FROM mail_deliveries WHERE id=?", (delivery,)
    ).fetchone()[0] == "sent"
    assert conn.execute(
        "SELECT processing_state FROM mail_messages WHERE id=?", (message,)
    ).fetchone()[0] == "sent"
