from __future__ import annotations

import sqlite3
from pathlib import Path

from src.foundation import FoundationConfig, FoundationRequest, FoundationTool
from src.mail_agent.contracts import MailRequest
from src.mail_agent.fact_gate import FactGateDecision, GatedFact
from src.mail_agent.publisher import MailResponsePublisher
from src.mail_agent.repository import MailRepository

NOW = "2026-07-24T00:00:00Z"


def _fixture(tmp_path: Path):
    root = tmp_path / "foundation"
    config = FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state" / "foundation-ready.json",
        root / "state" / "locks" / "foundation.lock",
    )
    assert (
        FoundationTool(config).execute(FoundationRequest("init", "m409", NOW)).status
        == "initialized"
    )
    connection = sqlite3.connect(root / "data.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(
        "INSERT INTO data_subjects(subject_key,created_at_utc) VALUES('s',?)", (NOW,)
    )
    subject = connection.execute("SELECT id FROM data_subjects").fetchone()[0]
    connection.execute(
        "INSERT INTO raw_objects(sha256,relative_path,media_type,size_bytes,provider,resource_kind,fetched_at_utc) VALUES(?,?,?,?,?,?,?)",
        (
            "a" * 64,
            "gmail/json/m.json",
            "application/json",
            2,
            "gmail",
            "message_json",
            NOW,
        ),
    )
    raw = connection.execute("SELECT id FROM raw_objects").fetchone()[0]
    connection.execute(
        "INSERT INTO source_revisions(provider,resource_kind,provider_object_id,revision_no,raw_object_id,payload_hash,is_current,parsed_at_utc) VALUES('gmail','message_json','m',1,?,?,1,?)",
        (raw, "b" * 64, NOW),
    )
    source = connection.execute("SELECT id FROM source_revisions").fetchone()[0]
    connection.execute(
        "INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) VALUES(?,'thread-1',1)",
        (subject,),
    )
    thread = connection.execute("SELECT id FROM mail_threads").fetchone()[0]
    connection.execute(
        "INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role,received_at_utc,body_text,body_sha256,source_revision_id,processing_state) VALUES(?,'m','inbound','user',?,'请记录我的目标',?,?, 'analyzing')",
        (thread, NOW, "text" * 16, source),
    )
    message = connection.execute("SELECT id FROM mail_messages").fetchone()[0]
    connection.commit()
    request = MailRequest("process", subject, "inv-1", NOW, mail_message_ids=("m",))
    run = MailRepository(connection, clock=lambda: NOW).start_or_resume_run(request)
    return (
        connection,
        MailRepository(connection, clock=lambda: NOW),
        subject,
        thread,
        message,
        source,
        run,
    )


def _context(run_id: int, run_key: str, thread: int, message: int, source: int):
    return {
        "run": {"id": run_id, "run_key": run_key},
        "trigger_message": {
            "id": message,
            "thread_id": thread,
            "provider_thread_id": "thread-1",
            "timestamp_utc": NOW,
        },
        "input_manifest": [
            {
                "ordinal": 0,
                "input_role": "trigger_message",
                "source_entity_type": "mail_message",
                "source_entity_id": message,
                "source_revision_id": source,
                "input_sha256": "d" * 64,
                "trust_class": "user_asserted",
            }
        ],
    }


def _result(run_key: str, message: int, text: str = "已记录。"):
    return {
        "schema_version": "1",
        "run_key": run_key,
        "trigger_message_id": message,
        "response": {
            "response_kind": "mail_response",
            "subject_intent": "ack",
            "structured_content": {"summary": text},
            "user_visible_text": text,
            "requires_thread_reply": True,
        },
    }


def _decision(subject: int, run, thread: int, message: int, source: int, *, facts=()):
    return FactGateDecision(
        "1",
        "accepted",
        "reply",
        "mail_fact_gate_accepted",
        subject,
        run.id,
        run.run_key,
        message,
        thread,
        source,
        None,
        tuple(facts),
    )


def test_publish_is_atomic_replayable_and_binds_exact_delivery_revision(
    tmp_path: Path,
) -> None:
    connection, repo, subject, thread, message, source, run = _fixture(tmp_path)
    publisher = MailResponsePublisher(repo)
    decision = _decision(subject, run, thread, message, source)
    first = publisher.publish(
        decision,
        _context(run.id, run.run_key, thread, message, source),
        _result(run.run_key, message),
    )
    replay = publisher.publish(
        decision,
        _context(run.id, run.run_key, thread, message, source),
        _result(run.run_key, message),
    )
    assert not first.unchanged and replay.unchanged
    assert replay.response_artifact_id == first.response_artifact_id
    assert (
        connection.execute(
            "SELECT processing_state FROM mail_messages WHERE id=?", (message,)
        ).fetchone()[0]
        == "ready_to_send"
    )
    assert (
        connection.execute(
            "SELECT status FROM mail_deliveries WHERE id=?", (first.delivery_id,)
        ).fetchone()[0]
        == "pending"
    )
    assert (
        connection.execute(
            "SELECT idempotency_key FROM mail_deliveries WHERE id=?",
            (first.delivery_id,),
        ).fetchone()[0]
        == f"mail:response:{first.response_artifact_id}:thread-1"
    )
    assert (
        connection.execute(
            "SELECT count(*) FROM mail_response_inputs WHERE mail_agent_run_id=?",
            (run.id,),
        ).fetchone()[0]
        == 1
    )
    assert (
        connection.execute(
            "SELECT count(*) FROM conversation_events WHERE event_type='mail_response_prepared' AND mail_response_artifact_id=?",
            (first.response_artifact_id,),
        ).fetchone()[0]
        == 1
    )
    item = connection.execute(
        "SELECT status,mail_message_id,mail_response_artifact_id,mail_delivery_id FROM mail_agent_items WHERE mail_agent_run_id=? AND stage='publish'",
        (run.id,),
    ).fetchone()
    assert tuple(item) == (
        "succeeded",
        message,
        first.response_artifact_id,
        first.delivery_id,
    )


def test_explicit_new_invocation_creates_superseding_revision_and_persists_gated_fact(
    tmp_path: Path,
) -> None:
    connection, repo, subject, thread, message, source, first_run = _fixture(tmp_path)
    publisher = MailResponsePublisher(repo)
    first = publisher.publish(
        _decision(subject, first_run, thread, message, source),
        _context(first_run.id, first_run.run_key, thread, message, source),
        _result(first_run.run_key, message),
    )
    second_request = MailRequest(
        "process",
        subject,
        "inv-2",
        NOW,
        mail_message_ids=("m",),
        regeneration_reason_code="user_requested",
    )
    second_run = repo.start_or_resume_run(second_request)
    fact = GatedFact(
        "goal",
        '"half marathon"',
        "long_term",
        NOW,
        None,
        0.9,
        "feedback_recorded",
        None,
        True,
    )
    second = publisher.publish(
        _decision(subject, second_run, thread, message, source, facts=(fact,)),
        _context(second_run.id, second_run.run_key, thread, message, source),
        _result(second_run.run_key, message, "目标已更新。"),
    )
    rows = connection.execute(
        "SELECT revision_no,is_current,supersedes_mail_response_artifact_id FROM mail_response_artifacts ORDER BY revision_no"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        (1, 0, None),
        (2, 1, first.response_artifact_id),
    ]
    assert tuple(
        connection.execute(
            "SELECT fact_key,fact_value_json,scope FROM user_facts"
        ).fetchone()
    ) == ("goal", '"half marathon"', "long_term")
    assert (
        connection.execute(
            "SELECT idempotency_key FROM mail_deliveries WHERE id=?",
            (second.delivery_id,),
        ).fetchone()[0]
        == f"mail:response:{second.response_artifact_id}:thread-1"
    )


def test_invalid_manifest_fails_before_any_publication(tmp_path: Path) -> None:
    connection, repo, subject, thread, message, source, run = _fixture(tmp_path)
    context = _context(run.id, run.run_key, thread, message, source)
    context["input_manifest"][0]["ordinal"] = 3
    try:
        MailResponsePublisher(repo).publish(
            _decision(subject, run, thread, message, source),
            context,
            _result(run.run_key, message),
        )
    except Exception as exc:
        assert str(exc) == "mail_publication_manifest_invalid"
    else:
        raise AssertionError("invalid manifest was published")
    for table in (
        "mail_response_artifacts",
        "mail_response_inputs",
        "mail_deliveries",
        "mail_agent_items",
    ):
        assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_publication_state_failure_rolls_back_artifact_lineage_and_delivery(
    tmp_path: Path,
) -> None:
    connection, repo, subject, thread, message, source, run = _fixture(tmp_path)
    connection.execute(
        "UPDATE mail_messages SET processing_state='queued' WHERE id=?", (message,)
    )
    connection.commit()
    try:
        MailResponsePublisher(repo).publish(
            _decision(subject, run, thread, message, source),
            _context(run.id, run.run_key, thread, message, source),
            _result(run.run_key, message),
        )
    except Exception as exc:
        assert str(exc) == "mail_response_publication_state_invalid"
    else:
        raise AssertionError("invalid state was published")
    for table in (
        "mail_response_artifacts",
        "mail_response_inputs",
        "mail_deliveries",
        "mail_delivery_artifacts",
        "mail_agent_items",
        "conversation_events",
    ):
        assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert (
        connection.execute(
            "SELECT processing_state FROM mail_messages WHERE id=?", (message,)
        ).fetchone()[0]
        == "queued"
    )
