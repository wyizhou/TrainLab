from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.mail_agent.contracts import MailRequest
from trainlab.mail_agent.locks import MailLockBusyError, MailWriteLock
from trainlab.mail_agent.repository import (
    AcceptedResponseDraft,
    DeliveryDraft,
    EventDraft,
    FactDraft,
    InputDraft,
    MailRepository,
    MailRepositoryError,
    safe_error_summary,
)


NOW = "2026-07-23T00:00:00Z"


def initialize(tmp_path: Path) -> tuple[sqlite3.Connection, MailRepository, int, int, int]:
    root = tmp_path / "foundation"
    config = FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state" / "foundation-ready.json", root / "state" / "locks" / "foundation.lock")
    assert FoundationTool(config).execute(FoundationRequest("init", "mail-repository-fixture", NOW)).status == "initialized"
    connection = sqlite3.connect(root / "data.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("INSERT INTO data_subjects(subject_key,created_at_utc) VALUES(?,?)", ("mail-subject", NOW))
    subject_id = connection.execute("SELECT id FROM data_subjects").fetchone()[0]
    connection.execute("INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) VALUES(?,?,1)", (subject_id, "thread-1"))
    thread_id = connection.execute("SELECT id FROM mail_threads").fetchone()[0]
    connection.execute(
        "INSERT INTO raw_objects(sha256,relative_path,media_type,size_bytes,provider,"
        "resource_kind,fetched_at_utc) VALUES(?,?,?,?,?,?,?)",
        ("a" * 64, "gmail/json/message-1.json", "application/json", 2, "gmail", "message_json", NOW),
    )
    raw_id = connection.execute(
        "SELECT id FROM raw_objects WHERE sha256=?", ("a" * 64,)
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO source_revisions(provider,resource_kind,provider_object_id,"
        "revision_no,raw_object_id,payload_hash,is_current,parsed_at_utc) "
        "VALUES('gmail','message_json','message-1',1,?,?,1,?)",
        (raw_id, "b" * 64, NOW),
    )
    source_revision_id = connection.execute(
        "SELECT id FROM source_revisions WHERE provider_object_id='message-1'"
    ).fetchone()[0]
    connection.execute("INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role,source_revision_id,processing_state) VALUES(?,?,?,?,?,?)", (thread_id, "message-1", "inbound", "user", source_revision_id, "new"))
    message_id = connection.execute("SELECT id FROM mail_messages").fetchone()[0]
    connection.commit()
    return connection, MailRepository(connection, clock=lambda: NOW), subject_id, thread_id, message_id


def request(subject_id: int, invocation_id: str = "inv-1") -> MailRequest:
    return MailRequest(mode="process", subject_id=subject_id, invocation_id=invocation_id, requested_at_utc=NOW, mail_message_ids=("message-1",))


def response_draft(thread_id: int, message_id: int, *, key: str = "delivery-1", fact_scope: str = "temporary") -> AcceptedResponseDraft:
    return AcceptedResponseDraft(
        mail_thread_id=thread_id,
        in_reply_to_mail_message_id=message_id,
        response_kind="mail_response",
        schema_version="1",
        structured_content_json=json.dumps({"kind": "reply"}, sort_keys=True),
        user_visible_text="已记录。",
        inputs=(
            InputDraft(
                "trigger_message",
                "mail_message",
                "a" * 64,
                "user_asserted",
                message_id,
                1,
            ),
        ),
        events=(EventDraft("feedback_recorded", "user", NOW, message_id, "untrusted_content"),),
        facts=(
            FactDraft(
                "availability",
                "{}",
                fact_scope,
                "feedback_recorded",
                expires_at_utc=(
                    "2026-08-01T00:00:00Z"
                    if fact_scope == "temporary"
                    else None
                ),
            ),
        ),
        delivery=DeliveryDraft(key, "thread-1"),
    )


def test_same_invocation_resumes_same_run_and_status_is_read_only(tmp_path: Path) -> None:
    connection, repo, subject_id, _, _ = initialize(tmp_path)
    created = repo.start_or_resume_run(request(subject_id))
    resumed = MailRepository(sqlite3.connect(tmp_path / "foundation" / "data.db"), clock=lambda: NOW).start_or_resume_run(request(subject_id))
    assert created.id == resumed.id and created.run_key == resumed.run_key
    selector = MailRequest(mode="status", subject_id=subject_id, invocation_id="status-inv", requested_at_utc=NOW, run_key=created.run_key)
    before = connection.total_changes
    assert repo.status(selector) == created
    assert connection.total_changes == before
    with pytest.raises(MailRepositoryError, match="status_is_read_only"):
        repo.start_or_resume_run(selector)


def test_item_state_machine_is_idempotent_and_sanitizes_error(tmp_path: Path) -> None:
    connection, repo, subject_id, _, message_id = initialize(tmp_path)
    run = repo.start_or_resume_run(request(subject_id))
    first = repo.record_item(run.id, logical_item_kind="message", logical_item_id="message-1", stage="classify", status="pending", mail_message_id=message_id)
    again = repo.record_item(run.id, logical_item_kind="message", logical_item_id="message-1", stage="classify", status="pending", mail_message_id=message_id)
    assert first.id == again.id and again.attempt_count == 1
    failed = repo.record_item(
        run.id,
        logical_item_kind="message",
        logical_item_id="message-1",
        stage="classify",
        status="failed",
        mail_message_id=message_id,
        error_code="parse_failed",
        error_summary="secret@example.invalid https://private.invalid/path",
    )
    assert failed.attempt_count == 2
    stored = connection.execute("SELECT error_summary FROM mail_agent_items WHERE id=?", (failed.id,)).fetchone()[0]
    assert "secret@example.invalid" not in stored and "https://private.invalid" not in stored
    with pytest.raises(MailRepositoryError, match="illegal_mail_item_transition"):
        repo.record_item(run.id, logical_item_kind="message", logical_item_id="message-1", stage="classify", status="running")


def test_accepted_publish_is_atomic_idempotent_and_keeps_exact_delivery_relation(tmp_path: Path) -> None:
    connection, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    run = repo.start_or_resume_run(request(subject_id))
    published = repo.publish_accepted_response(run.id, response_draft(thread_id, message_id))
    retried = repo.publish_accepted_response(run.id, response_draft(thread_id, message_id))
    assert published.response_artifact_id == retried.response_artifact_id
    assert published.delivery_id == retried.delivery_id
    assert connection.execute("SELECT COUNT(*) FROM mail_response_artifacts").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM mail_response_inputs").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM user_facts").fetchone()[0] == 1
    relation = connection.execute("SELECT mail_response_artifact_id,content_role FROM mail_delivery_artifacts").fetchone()
    assert relation[0] == published.response_artifact_id and relation[1] == "mail_response"
    second = repo.start_or_resume_run(request(subject_id, "inv-2"))
    newer = repo.publish_accepted_response(second.id, response_draft(thread_id, message_id, key="delivery-2"))
    rows = connection.execute("SELECT id,is_current FROM mail_response_artifacts ORDER BY revision_no").fetchall()
    assert [(row[0], row[1]) for row in rows] == [(published.response_artifact_id, 0), (newer.response_artifact_id, 1)]


def test_accepted_publish_rolls_back_all_rows_on_constraint_failure(tmp_path: Path) -> None:
    connection, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    run = repo.start_or_resume_run(request(subject_id))
    with pytest.raises(MailRepositoryError, match="invalid_user_fact_draft"):
        repo.publish_accepted_response(run.id, response_draft(thread_id, message_id, fact_scope="invalid-scope"))
    for table in ("conversation_events", "user_facts", "mail_response_artifacts", "mail_response_inputs", "mail_deliveries", "mail_delivery_artifacts"):
        assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_run_recovery_and_legal_transitions(tmp_path: Path) -> None:
    _, repo, subject_id, _, _ = initialize(tmp_path)
    run = repo.start_or_resume_run(request(subject_id))
    assert repo.finish_run(
        run.id,
        "deferred",
        next_retry_at_utc="2026-07-23T00:01:00Z",
    ).status == "deferred"
    assert repo.finish_run(run.id, "succeeded").status == "succeeded"
    with pytest.raises(MailRepositoryError, match="illegal_mail_run_transition"):
        repo.finish_run(run.id, "partial")
    assert repo.start_or_resume_run(request(subject_id)).id == run.id


def test_single_writer_lock_preserves_live_lock_and_recovers_only_dead_pid(tmp_path: Path) -> None:
    path = tmp_path / "state" / "locks" / "mail.lock"
    path.parent.mkdir(parents=True, mode=0o700)
    os.chmod(path.parent.parent, 0o700)
    os.chmod(path.parent, 0o700)
    owner = MailWriteLock(path, "mail:1:process:owner")
    owner.acquire()
    contender = MailWriteLock(path, "mail:1:process:contender")
    with pytest.raises(MailLockBusyError):
        contender.acquire()
    assert json.loads(path.read_text())["pid"] == os.getpid()
    owner.release()
    path.write_text(json.dumps({"pid": 99999999, "run_key": "dead", "uid": os.getuid(), "started_at_utc": NOW}, sort_keys=True, separators=(",", ":")))
    os.chmod(path, 0o600)
    stale = MailWriteLock(path, "mail:1:process:replacement", process_is_alive=lambda _: False)
    stale.acquire()
    assert json.loads(path.read_text())["run_key"] == "mail:1:process:replacement"
    stale.release()


def test_lock_rejects_missing_private_parent_symlink_and_malformed_record(tmp_path: Path) -> None:
    missing = MailWriteLock(tmp_path / "missing" / "locks" / "mail.lock", "mail:1:poll:x")
    with pytest.raises(MailLockBusyError):
        missing.acquire()
    state = tmp_path / "state"; locks = state / "locks"
    state.mkdir(mode=0o700); locks.mkdir(mode=0o700)
    outside = tmp_path / "outside"; outside.mkdir()
    (locks / "mail.lock").symlink_to(outside)
    with pytest.raises(MailLockBusyError):
        MailWriteLock(locks / "mail.lock", "mail:1:poll:x").acquire()
    (locks / "mail.lock").unlink()
    (locks / "mail.lock").write_text("{")
    os.chmod(locks / "mail.lock", 0o600)
    with pytest.raises(MailLockBusyError):
        MailWriteLock(locks / "mail.lock", "mail:1:poll:x", process_is_alive=lambda _: False).acquire()


def test_safe_error_summary_never_keeps_urls_or_email_addresses() -> None:
    assert safe_error_summary("a@example.invalid https://example.invalid/a\nbody") == "<redacted-email> <redacted-url> body"


def test_repository_rejects_unready_manifest_and_does_not_migrate(tmp_path: Path) -> None:
    connection, repo, subject_id, _, _ = initialize(tmp_path)
    connection.execute("UPDATE foundation_state SET state='initializing'")
    connection.commit()
    with pytest.raises(MailRepositoryError, match="foundation_schema_incompatible"):
        MailRepository(connection, clock=lambda: NOW)
    assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2


def test_cursor_and_processing_state_are_subject_scoped_and_monotonic(tmp_path: Path) -> None:
    connection, repo, subject_id, _, message_id = initialize(tmp_path)
    connection.execute("INSERT INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) VALUES(?, 'gmail','email',?,1,?,?)", (subject_id, "h" * 64, NOW, NOW))
    identity_id = connection.execute("SELECT id FROM subject_identities WHERE identity_hmac=?", ("h" * 64,)).fetchone()[0]
    connection.commit()
    run = repo.start_or_resume_run(MailRequest(mode="poll", subject_id=subject_id, invocation_id="poll-cursor", requested_at_utc=NOW))
    cursor = repo.advance_poll_cursor(run.id, subject_id, identity_id, "trainlab_label", NOW, "2026-07-22T00:00:00Z")
    assert repo.get_poll_cursor(subject_id, identity_id, "trainlab_label") == cursor
    with pytest.raises(MailRepositoryError, match="regression"):
        repo.advance_poll_cursor(run.id, subject_id, identity_id, "trainlab_label", "2026-07-22T00:00:00Z", "2026-07-21T00:00:00Z")
    repo.set_message_processing_state(subject_id, message_id, "discovered")
    repo.set_message_processing_state(subject_id, message_id, "archived")
    assert connection.execute("SELECT processing_state FROM mail_messages WHERE id=?", (message_id,)).fetchone()[0] == "archived"
    with pytest.raises(MailRepositoryError):
        repo.set_message_processing_state(subject_id, message_id, "not-a-state")


def test_same_run_conflicting_response_draft_is_rejected(tmp_path: Path) -> None:
    _, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    run = repo.start_or_resume_run(request(subject_id))
    repo.publish_accepted_response(run.id, response_draft(thread_id, message_id))
    conflicting = response_draft(thread_id, message_id)
    conflicting = AcceptedResponseDraft(
        conflicting.mail_thread_id, conflicting.in_reply_to_mail_message_id, conflicting.response_kind,
        conflicting.schema_version, conflicting.structured_content_json, "different", conflicting.inputs,
        conflicting.events, conflicting.facts, conflicting.delivery,
    )
    with pytest.raises(MailRepositoryError, match="conflicting_mail_response_retry"):
        repo.publish_accepted_response(run.id, conflicting)


def test_cursor_rejects_verified_non_gmail_identity_and_incomplete_window(tmp_path: Path) -> None:
    connection, repo, subject_id, _, _ = initialize(tmp_path)
    connection.execute(
        "INSERT INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) VALUES(?, 'garmin','account',?,1,?,?)",
        (subject_id, "g" * 64, NOW, NOW),
    )
    identity_id = connection.execute("SELECT id FROM subject_identities WHERE identity_hmac=?", ("g" * 64,)).fetchone()[0]
    connection.commit()
    run = repo.start_or_resume_run(MailRequest(mode="poll", subject_id=subject_id, invocation_id="poll-identity", requested_at_utc=NOW))
    with pytest.raises(MailRepositoryError, match="ownership"):
        repo.advance_poll_cursor(run.id, subject_id, identity_id, "trainlab_label", NOW, "2026-07-22T00:00:00Z")
    connection.execute(
        "INSERT INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) VALUES(?, 'gmail','email',?,1,?,?)",
        (subject_id, "m" * 64, NOW, NOW),
    )
    gmail_id = connection.execute("SELECT id FROM subject_identities WHERE identity_hmac=?", ("m" * 64,)).fetchone()[0]
    connection.commit()
    with pytest.raises(MailRepositoryError, match="invalid_mail_poll_cursor"):
        repo.advance_poll_cursor(run.id, subject_id, gmail_id, "trainlab_label", NOW, "2026-07-22T00:00:00Z", stream_completed=False)


def test_accepted_response_replay_checks_events_facts_and_cross_subject_ownership(tmp_path: Path) -> None:
    connection, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    connection.execute("INSERT INTO data_subjects(subject_key,created_at_utc) VALUES(?,?)", ("other", NOW))
    other_subject = connection.execute("SELECT id FROM data_subjects WHERE subject_key='other'").fetchone()[0]
    connection.execute("INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) VALUES(?,?,1)", (other_subject, "thread-other"))
    other_thread = connection.execute("SELECT id FROM mail_threads WHERE provider_thread_id='thread-other'").fetchone()[0]
    connection.execute("INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role,processing_state) VALUES(?,?,?,?,?)", (other_thread, "message-other", "inbound", "user", "new"))
    other_message = connection.execute("SELECT id FROM mail_messages WHERE provider_message_id='message-other'").fetchone()[0]
    connection.commit()
    run = repo.start_or_resume_run(request(subject_id))
    bad = response_draft(thread_id, message_id)
    bad = AcceptedResponseDraft(
        bad.mail_thread_id, bad.in_reply_to_mail_message_id, bad.response_kind, bad.schema_version,
        bad.structured_content_json, bad.user_visible_text, bad.inputs,
        (EventDraft("feedback_recorded", "user", NOW, other_message, "untrusted_content"),), bad.facts, bad.delivery,
    )
    with pytest.raises(MailRepositoryError, match="ownership"):
        repo.publish_accepted_response(run.id, bad)
    repo.publish_accepted_response(run.id, response_draft(thread_id, message_id))
    changed_event = AcceptedResponseDraft(
        thread_id, message_id, "mail_response", "1", json.dumps({"kind": "reply"}, sort_keys=True), "已记录。",
        (
            InputDraft(
                "trigger_message",
                "mail_message",
                "a" * 64,
                "user_asserted",
                message_id,
                1,
            ),
        ),
        (EventDraft("feedback_recorded", "trainlab", NOW, message_id, "untrusted_content"),),
        (
            FactDraft(
                "availability",
                '{"changed":true}',
                "temporary",
                "feedback_recorded",
                expires_at_utc="2026-08-01T00:00:00Z",
            ),
        ),
        DeliveryDraft("delivery-1", "thread-1"),
    )
    with pytest.raises(MailRepositoryError, match="ownership"):
        repo.publish_accepted_response(run.id, changed_event)


@pytest.mark.parametrize("ddl", (
    "DROP TABLE mail_agent_items",
    "DROP VIEW v_current_mail_messages",
    "DROP TRIGGER trg_training_plan_item_window",
))
def test_after_constructor_schema_object_tamper_fails_before_business_write(tmp_path: Path, ddl: str) -> None:
    connection, repo, subject_id, _, _ = initialize(tmp_path)
    connection.execute(ddl)
    connection.commit()
    before = connection.total_changes
    with pytest.raises(MailRepositoryError, match="foundation_schema"):
        repo.start_or_resume_run(request(subject_id, f"tamper-{abs(hash(ddl))}"))
    assert connection.total_changes == before


def test_cursor_rejects_process_or_terminal_run_and_state_cross_step_is_zero_write(tmp_path: Path) -> None:
    connection, repo, subject_id, _, message_id = initialize(tmp_path)
    connection.execute("INSERT INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) VALUES(?, 'gmail','email',?,1,?,?)", (subject_id, "z" * 64, NOW, NOW))
    identity_id = connection.execute("SELECT id FROM subject_identities WHERE identity_hmac=?", ("z" * 64,)).fetchone()[0]
    connection.commit()
    process = repo.start_or_resume_run(request(subject_id, "process-cursor"))
    with pytest.raises(MailRepositoryError, match="ownership"):
        repo.advance_poll_cursor(process.id, subject_id, identity_id, "trainlab_label", NOW, "2026-07-22T00:00:00Z")
    before = connection.total_changes
    with pytest.raises(MailRepositoryError, match="illegal_mail_message_transition"):
        repo.set_message_processing_state(subject_id, message_id, "queued")
    assert connection.total_changes == before
    repo.set_message_processing_state(subject_id, message_id, "discovered")
    before = connection.total_changes
    repo.set_message_processing_state(subject_id, message_id, "discovered")
    assert connection.total_changes == before


def test_item_same_status_requires_exact_immutable_evidence(tmp_path: Path) -> None:
    connection, repo, subject_id, _, message_id = initialize(tmp_path)
    run = repo.start_or_resume_run(request(subject_id, "item-replay"))
    repo.record_item(run.id, logical_item_kind="message", logical_item_id="message-1", stage="classify", status="pending", mail_message_id=message_id)
    before = connection.total_changes
    repo.record_item(run.id, logical_item_kind="message", logical_item_id="message-1", stage="classify", status="pending", mail_message_id=message_id)
    assert connection.total_changes == before
    with pytest.raises(MailRepositoryError, match="conflicting_mail_item_replay"):
        repo.record_item(run.id, logical_item_kind="message", logical_item_id="message-1", stage="classify", status="pending")


@pytest.mark.parametrize(
    "tamper",
    (
        "DELETE FROM schema_migrations WHERE version=1",
        "INSERT INTO schema_migrations VALUES(3,'extra','2026-07-23T00:00:00Z','foundation-v3','deadbeef')",
        "UPDATE schema_migrations SET description='wrong' WHERE version=1",
        "UPDATE schema_migrations SET applied_at_utc='not-utc' WHERE version=2",
        "UPDATE schema_migrations SET code_revision='wrong' WHERE version=2",
        "UPDATE schema_migrations SET content_sha256='wrong' WHERE version=2",
    ),
)
def test_repository_requires_exact_two_foundation_migration_receipts(tmp_path: Path, tamper: str) -> None:
    connection, _, _, _, _ = initialize(tmp_path)
    connection.execute(tamper)
    connection.commit()
    with pytest.raises(MailRepositoryError, match="foundation_migration_incompatible"):
        MailRepository(connection, clock=lambda: NOW)


@pytest.mark.parametrize(
    "ddl",
    (
        "CREATE TABLE extra_foundation_object(id INTEGER)",
        "CREATE VIEW extra_foundation_object AS SELECT 1 AS id",
        "CREATE INDEX extra_foundation_object ON mail_messages(id)",
        "CREATE TRIGGER extra_foundation_object BEFORE UPDATE ON mail_messages BEGIN SELECT 1; END",
    ),
)
def test_repository_rejects_every_extra_database_object_kind(tmp_path: Path, ddl: str) -> None:
    connection, _, _, _, _ = initialize(tmp_path)
    connection.execute(ddl)
    connection.commit()
    with pytest.raises(MailRepositoryError, match="foundation_schema_incompatible"):
        MailRepository(connection, clock=lambda: NOW)


@pytest.mark.parametrize(
    ("name", "replacement"),
    (
        ("idx_source_revisions_current", "CREATE INDEX idx_source_revisions_current ON source_revisions(resource_kind,provider,provider_object_id,is_current)"),
        ("ux_source_revision_current", "CREATE UNIQUE INDEX ux_source_revision_current ON source_revisions(provider,resource_kind,provider_object_id,is_current)"),
        ("ux_activity_source_role_active", "CREATE UNIQUE INDEX ux_activity_source_role_active ON activity_source_revisions(source_role,activity_id) WHERE is_active=1"),
        ("ux_daily_health_current", "CREATE UNIQUE INDEX ux_daily_health_current ON daily_health(local_date,subject_id) WHERE is_current=1"),
        ("ux_analysis_artifact_current", "CREATE UNIQUE INDEX ux_analysis_artifact_current ON analysis_artifacts(subject_id,artifact_kind,period_start_local_date,period_end_local_date) WHERE is_current=0"),
        ("ux_mail_response_current", "CREATE UNIQUE INDEX ux_mail_response_current ON mail_response_artifacts(subject_id,response_kind,mail_thread_id) WHERE is_current=1"),
        ("ux_garmin_sync_gap_unresolved", "CREATE UNIQUE INDEX ux_garmin_sync_gap_unresolved ON garmin_sync_gaps(subject_id,resource_kind,logical_object_key,window_start_local_date,window_end_local_date,stage) WHERE status IN ('open')"),
        ("idx_coverage_resource_date", "CREATE UNIQUE INDEX idx_coverage_resource_date ON resource_coverage(resource_kind,local_date)"),
        ("idx_activity_samples_stream", "CREATE INDEX idx_activity_samples_stream ON activity_samples(activity_id,sample_index,stream_kind)"),
    ),
)
def test_repository_validates_all_explicit_foundation_indexes_exactly(
    tmp_path: Path, name: str, replacement: str
) -> None:
    connection, _, _, _, _ = initialize(tmp_path)
    connection.execute(f"DROP INDEX {name}")
    connection.execute(replacement)
    connection.commit()
    with pytest.raises(MailRepositoryError, match="foundation_schema_incompatible"):
        MailRepository(connection, clock=lambda: NOW)


def test_repository_validates_complete_trigger_sql_not_just_manifest_token(tmp_path: Path) -> None:
    connection, _, _, _, _ = initialize(tmp_path)
    connection.execute("DROP TRIGGER trg_training_plan_item_window")
    connection.execute(
        "CREATE TRIGGER trg_training_plan_item_window BEFORE INSERT ON training_plan_items "
        "FOR EACH ROW WHEN 1=0 BEGIN "
        "SELECT RAISE(ABORT,'training_plan_item_outside_plan_window'); END"
    )
    connection.commit()
    with pytest.raises(MailRepositoryError, match="foundation_schema_incompatible"):
        MailRepository(connection, clock=lambda: NOW)


def test_item_relations_remain_immutable_across_status_transitions(tmp_path: Path) -> None:
    connection, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    connection.execute(
        "INSERT INTO analysis_runs(run_key,subject_id,analysis_kind,status,started_at_utc) "
        "VALUES(?,?,?,?,?)",
        ("analysis-1", subject_id, "daily", "succeeded", NOW),
    )
    analysis_run_id = connection.execute(
        "SELECT id FROM analysis_runs WHERE run_key='analysis-1'"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO analysis_runs(run_key,subject_id,analysis_kind,status,started_at_utc) "
        "VALUES(?,?,?,?,?)",
        ("analysis-2", subject_id, "weekly", "succeeded", NOW),
    )
    other_analysis_run_id = connection.execute(
        "SELECT id FROM analysis_runs WHERE run_key='analysis-2'"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO analysis_artifacts(subject_id,artifact_kind,period_start_local_date,"
        "period_end_local_date,revision_no,generated_by_run_id,schema_version,"
        "structured_content_json,user_visible_text,content_sha256,is_current,created_at_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (subject_id, "daily_summary", "2026-07-23", "2026-07-23", 1, analysis_run_id, "1", "{}", "one", "a" * 64, 1, NOW),
    )
    analysis_id = connection.execute("SELECT id FROM analysis_artifacts").fetchone()[0]
    connection.execute(
        "INSERT INTO analysis_artifacts(subject_id,artifact_kind,period_start_local_date,"
        "period_end_local_date,revision_no,generated_by_run_id,schema_version,"
        "structured_content_json,user_visible_text,content_sha256,is_current,created_at_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (subject_id, "weekly_summary", "2026-07-17", "2026-07-23", 1, other_analysis_run_id, "1", "{}", "two", "b" * 64, 1, NOW),
    )
    other_analysis_id = connection.execute("SELECT id FROM analysis_artifacts ORDER BY id DESC LIMIT 1").fetchone()[0]
    connection.execute(
        "INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role,processing_state) "
        "VALUES(?,?,?,?,?)",
        (thread_id, "message-2", "inbound", "user", "new"),
    )
    other_message_id = connection.execute(
        "SELECT id FROM mail_messages WHERE provider_message_id='message-2'"
    ).fetchone()[0]
    connection.commit()

    publishing_run = repo.start_or_resume_run(request(subject_id, "publish-relations"))
    first = repo.publish_accepted_response(
        publishing_run.id,
        response_draft(thread_id, message_id, key="relation-delivery-1"),
    )
    other_run = repo.start_or_resume_run(request(subject_id, "publish-relations-2"))
    second = repo.publish_accepted_response(
        other_run.id,
        response_draft(thread_id, message_id, key="relation-delivery-2"),
    )
    item_run = repo.start_or_resume_run(request(subject_id, "item-relations"))
    immutable = {
        "mail_message_id": message_id,
        "dependency_analysis_artifact_id": analysis_id,
        "mail_response_artifact_id": first.response_artifact_id,
        "mail_delivery_id": first.delivery_id,
    }
    created = repo.record_item(
        item_run.id,
        logical_item_kind="message",
        logical_item_id="message-1",
        stage="classify",
        status="pending",
        **immutable,
    )
    before = connection.execute(
        "SELECT mail_message_id,dependency_analysis_artifact_id,mail_response_artifact_id,"
        "mail_delivery_id,status,attempt_count FROM mail_agent_items WHERE id=?",
        (created.id,),
    ).fetchone()
    mutations = (
        {"mail_message_id": other_message_id},
        {"dependency_analysis_artifact_id": other_analysis_id},
        {"mail_response_artifact_id": second.response_artifact_id},
        {"mail_delivery_id": second.delivery_id},
    )
    for mutation in mutations:
        changed = immutable | mutation
        with pytest.raises(MailRepositoryError, match="conflicting_mail_item_replay"):
            repo.record_item(
                item_run.id,
                logical_item_kind="message",
                logical_item_id="message-1",
                stage="classify",
                status="running",
                **changed,
            )
        assert connection.execute(
            "SELECT mail_message_id,dependency_analysis_artifact_id,mail_response_artifact_id,"
            "mail_delivery_id,status,attempt_count FROM mail_agent_items WHERE id=?",
            (created.id,),
        ).fetchone() == before
    transitioned = repo.record_item(
        item_run.id,
        logical_item_kind="message",
        logical_item_id="message-1",
        stage="classify",
        status="running",
        **immutable,
    )
    assert transitioned.status == "running" and transitioned.attempt_count == 2


@pytest.mark.parametrize(
    "mutation",
    (
        {"mail_message_ids": ("message-mutated",)},
        {"dependency_analysis_artifact_ids": ("analysis-1",)},
        {"regeneration_reason_code": "explicit-regeneration"},
        {"requested_at_utc": "2026-07-23T00:00:01Z"},
    ),
)
def test_same_invocation_requires_exact_full_request_identity(
    tmp_path: Path, mutation: dict[str, object]
) -> None:
    connection, repo, subject_id, _, _ = initialize(tmp_path)
    original = request(subject_id, "identity")
    run = repo.start_or_resume_run(original)
    snapshot = {"mail_request_identity": original.to_dict()}
    canonical = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    persisted = connection.execute(
        "SELECT context_snapshot_json,context_snapshot_sha256 "
        "FROM mail_agent_runs WHERE id=?",
        (run.id,),
    ).fetchone()
    assert persisted["context_snapshot_json"] == canonical
    assert persisted["context_snapshot_sha256"] == hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    with pytest.raises(
        MailRepositoryError, match="invocation_id_conflicts_with_existing_run"
    ):
        repo.start_or_resume_run(replace(original, **mutation))
    assert connection.execute("SELECT count(*) FROM mail_agent_runs").fetchone()[0] == 1


def test_exact_publication_relations_are_identical_on_replay(tmp_path: Path) -> None:
    _, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    run = repo.start_or_resume_run(request(subject_id, "exact-receipt"))
    first = repo.publish_accepted_response(
        run.id, response_draft(thread_id, message_id, key="exact-delivery")
    )
    replay = repo.publish_accepted_response(
        run.id, response_draft(thread_id, message_id, key="exact-delivery")
    )
    assert replay == first
    assert first.event_ids and first.fact_ids and first.delivery_id is not None


def test_response_supersedes_exact_prior_current_and_late_fault_rolls_back(
    tmp_path: Path,
) -> None:
    connection, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    first_run = repo.start_or_resume_run(request(subject_id, "supersession-1"))
    first = repo.publish_accepted_response(
        first_run.id,
        response_draft(thread_id, message_id, key="supersession-delivery-1"),
    )
    second_run = repo.start_or_resume_run(request(subject_id, "supersession-2"))
    second = repo.publish_accepted_response(
        second_run.id,
        response_draft(thread_id, message_id, key="supersession-delivery-2"),
    )
    chain = connection.execute(
        "SELECT id,is_current,supersedes_mail_response_artifact_id "
        "FROM mail_response_artifacts ORDER BY revision_no"
    ).fetchall()
    assert [tuple(row) for row in chain] == [
        (first.response_artifact_id, 0, None),
        (second.response_artifact_id, 1, first.response_artifact_id),
    ]

    fault_run = repo.start_or_resume_run(request(subject_id, "supersession-fault"))
    before = tuple(
        connection.execute(
            "SELECT id,is_current,supersedes_mail_response_artifact_id "
            "FROM mail_response_artifacts ORDER BY revision_no"
        ).fetchall()
    )
    with pytest.raises(
        MailRepositoryError, match="mail_repository_constraint_violation"
    ):
        repo.publish_accepted_response(
            fault_run.id,
            response_draft(
                thread_id, message_id, key="supersession-delivery-2"
            ),
        )
    after = tuple(
        connection.execute(
            "SELECT id,is_current,supersedes_mail_response_artifact_id "
            "FROM mail_response_artifacts ORDER BY revision_no"
        ).fetchall()
    )
    assert after == before
    assert connection.execute(
        "SELECT is_current FROM mail_response_artifacts WHERE id=?",
        (second.response_artifact_id,),
    ).fetchone()[0] == 1


def test_concurrent_response_publications_form_one_exact_revision_chain(
    tmp_path: Path,
) -> None:
    connection, _, subject_id, thread_id, message_id = initialize(tmp_path)
    database = tmp_path / "foundation" / "data.db"
    barrier = threading.Barrier(2)
    results: list[int] = []
    errors: list[BaseException] = []

    def publish(invocation: str, delivery: str) -> None:
        worker_connection = sqlite3.connect(database, timeout=10)
        try:
            worker = MailRepository(worker_connection, clock=lambda: NOW)
            run = worker.start_or_resume_run(request(subject_id, invocation))
            barrier.wait(timeout=10)
            result = worker.publish_accepted_response(
                run.id,
                response_draft(thread_id, message_id, key=delivery),
            )
            results.append(result.response_artifact_id)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            worker_connection.close()

    threads = [
        threading.Thread(target=publish, args=("concurrent-1", "concurrent-d1")),
        threading.Thread(target=publish, args=("concurrent-2", "concurrent-d2")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not errors and len(results) == 2
    rows = connection.execute(
        "SELECT id,revision_no,is_current,supersedes_mail_response_artifact_id "
        "FROM mail_response_artifacts ORDER BY revision_no"
    ).fetchall()
    assert len(rows) == 2
    assert tuple(rows[0])[1:] == (1, 0, None)
    assert tuple(rows[1])[1:] == (2, 1, rows[0]["id"])


def test_null_message_events_are_run_and_subject_scoped(tmp_path: Path) -> None:
    connection, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    connection.execute(
        "INSERT INTO data_subjects(subject_key,created_at_utc) VALUES(?,?)",
        ("subject-2", NOW),
    )
    subject_2 = connection.execute(
        "SELECT id FROM data_subjects WHERE subject_key='subject-2'"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) "
        "VALUES(?,?,1)",
        (subject_2, "thread-2"),
    )
    thread_2 = connection.execute(
        "SELECT id FROM mail_threads WHERE provider_thread_id='thread-2'"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,"
        "actor_role,processing_state) VALUES(?,?,?,?,?)",
        (thread_2, "message-2", "inbound", "user", "new"),
    )
    message_2 = connection.execute(
        "SELECT id FROM mail_messages WHERE provider_message_id='message-2'"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO raw_objects(sha256,relative_path,media_type,size_bytes,provider,"
        "resource_kind,fetched_at_utc) VALUES(?,?,?,?,?,?,?)",
        ("c" * 64, "gmail/json/message-2.json", "application/json", 2, "gmail", "message_json", NOW),
    )
    raw_2 = connection.execute(
        "SELECT id FROM raw_objects WHERE sha256=?", ("c" * 64,)
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO source_revisions(provider,resource_kind,provider_object_id,"
        "revision_no,raw_object_id,payload_hash,is_current,parsed_at_utc) "
        "VALUES('gmail','message_json','message-2',1,?,?,1,?)",
        (raw_2, "d" * 64, NOW),
    )
    source_2 = connection.execute(
        "SELECT id FROM source_revisions WHERE provider_object_id='message-2'"
    ).fetchone()[0]
    connection.execute(
        "UPDATE mail_messages SET source_revision_id=? WHERE id=?",
        (source_2, message_2),
    )
    connection.commit()

    def null_event_draft(
        thread: int,
        message: int,
        source_revision: int,
        delivery: str,
        provider_thread: str,
    ) -> AcceptedResponseDraft:
        base = response_draft(thread, message, key=delivery)
        return replace(
            base,
            inputs=(
                InputDraft(
                    "trigger_message",
                    "mail_message",
                    "a" * 64,
                    "user_asserted",
                    message,
                    source_revision,
                ),
            ),
            events=(
                EventDraft(
                    "mail_response_prepared",
                    "trainlab",
                    NOW,
                    None,
                    "system_generated",
                ),
            ),
            facts=(),
            delivery=DeliveryDraft(delivery, provider_thread),
        )

    first_run = repo.start_or_resume_run(request(subject_id, "null-event-1"))
    first_draft = null_event_draft(
        thread_id, message_id, 1, "null-delivery-1", "thread-1"
    )
    first = repo.publish_accepted_response(first_run.id, first_draft)
    assert repo.publish_accepted_response(first_run.id, first_draft) == first

    second_request = MailRequest(
        mode="process",
        subject_id=subject_2,
        invocation_id="null-event-2",
        requested_at_utc=NOW,
        mail_message_ids=("message-2",),
    )
    second_run = repo.start_or_resume_run(second_request)
    second = repo.publish_accepted_response(
        second_run.id,
        null_event_draft(
            thread_2, message_2, source_2, "null-delivery-2", "thread-2"
        ),
    )
    assert first.event_ids != second.event_ids
    rows = connection.execute(
        "SELECT subject_id,related_run_key,event_type FROM conversation_events "
        "WHERE mail_message_id IS NULL ORDER BY id"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        (subject_id, first_run.run_key, "mail_response_prepared"),
        (subject_2, second_run.run_key, "mail_response_prepared"),
    ]


@pytest.mark.parametrize(
    "invalid_json",
    (
        '{"duplicate":1,"duplicate":2}',
        '{"number":NaN}',
        '{"surrogate":"\\ud800"}',
        '{"one":1} {"two":2}',
        "[]",
        '{"deep":' + "[" * 25 + "0" + "]" * 25 + "}",
        "{" + ",".join(f'"k{index}":{index}' for index in range(257)) + "}",
    ),
)
def test_structured_content_uses_strict_bounded_canonical_json(
    tmp_path: Path, invalid_json: str
) -> None:
    connection, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    run = repo.start_or_resume_run(request(subject_id, "strict-structured"))
    draft = replace(
        response_draft(thread_id, message_id, key="strict-structured-delivery"),
        structured_content_json=invalid_json,
    )
    before = {
        table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in (
            "conversation_events",
            "user_facts",
            "mail_response_artifacts",
            "mail_response_inputs",
            "mail_deliveries",
            "mail_delivery_artifacts",
        )
    }
    with pytest.raises(MailRepositoryError, match="invalid_mail_response_draft"):
        repo.publish_accepted_response(run.id, draft)
    assert {
        table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in before
    } == before


@pytest.mark.parametrize(
    "invalid_json",
    (
        '{"duplicate":1,"duplicate":2}',
        "Infinity",
        '"\\ud800"',
        "true false",
        "[" + ",".join("0" for _ in range(257)) + "]",
    ),
)
def test_fact_values_use_strict_bounded_canonical_json(
    tmp_path: Path, invalid_json: str
) -> None:
    connection, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    run = repo.start_or_resume_run(request(subject_id, "strict-fact"))
    base = response_draft(thread_id, message_id, key="strict-fact-delivery")
    draft = replace(
        base,
        facts=(replace(base.facts[0], fact_value_json=invalid_json),),
    )
    with pytest.raises(MailRepositoryError, match="invalid_user_fact_draft"):
        repo.publish_accepted_response(run.id, draft)
    assert connection.execute(
        "SELECT count(*) FROM conversation_events"
    ).fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM user_facts").fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM mail_response_artifacts"
    ).fetchone()[0] == 0


def test_equivalent_json_is_stored_and_replayed_canonically(tmp_path: Path) -> None:
    connection, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    run = repo.start_or_resume_run(request(subject_id, "canonical-json"))
    first_draft = replace(
        response_draft(thread_id, message_id, key="canonical-delivery"),
        structured_content_json='{ "z": 2, "a": 1 }',
    )
    first = repo.publish_accepted_response(run.id, first_draft)
    second_draft = replace(first_draft, structured_content_json='{"a":1,"z":2}')
    assert repo.publish_accepted_response(run.id, second_draft) == first
    assert connection.execute(
        "SELECT structured_content_json FROM mail_response_artifacts WHERE id=?",
        (first.response_artifact_id,),
    ).fetchone()[0] == '{"a":1,"z":2}'


def test_input_lineage_rejects_cross_subject_wrong_type_revision_and_thread(
    tmp_path: Path,
) -> None:
    connection, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    connection.execute(
        "INSERT INTO data_subjects(subject_key,created_at_utc) VALUES('lineage-other',?)",
        (NOW,),
    )
    other_subject = connection.execute(
        "SELECT id FROM data_subjects WHERE subject_key='lineage-other'"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) "
        "VALUES(?, 'lineage-other-thread',1)",
        (other_subject,),
    )
    other_thread = connection.execute(
        "SELECT id FROM mail_threads WHERE provider_thread_id='lineage-other-thread'"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,"
        "actor_role,processing_state) VALUES(?, 'lineage-other-message','inbound','user','new')",
        (other_thread,),
    )
    other_message = connection.execute(
        "SELECT id FROM mail_messages WHERE provider_message_id='lineage-other-message'"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) "
        "VALUES(?, 'lineage-second-thread',1)",
        (subject_id,),
    )
    second_thread = connection.execute(
        "SELECT id FROM mail_threads WHERE provider_thread_id='lineage-second-thread'"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,"
        "actor_role,processing_state) VALUES(?, 'lineage-second-message','inbound','user','new')",
        (second_thread,),
    )
    second_message = connection.execute(
        "SELECT id FROM mail_messages WHERE provider_message_id='lineage-second-message'"
    ).fetchone()[0]
    source_revision = connection.execute(
        "SELECT id FROM source_revisions WHERE provider_object_id='message-1'"
    ).fetchone()[0]
    connection.commit()
    run = repo.start_or_resume_run(request(subject_id, "lineage"))
    base = response_draft(thread_id, message_id, key="lineage-delivery")
    cases = (
        replace(
            base,
            inputs=(
                InputDraft(
                    "trigger_message",
                    "mail_message",
                    "a" * 64,
                    "user_asserted",
                    other_message,
                    None,
                ),
            ),
        ),
        replace(
            base,
            inputs=(
                InputDraft(
                    "trigger_message",
                    "conversation_event",
                    "a" * 64,
                    "user_asserted",
                    message_id,
                    source_revision,
                ),
            ),
        ),
        replace(
            base,
            inputs=(
                InputDraft(
                    "trigger_message",
                    "mail_message",
                    "a" * 64,
                    "user_asserted",
                    message_id,
                    None,
                ),
            ),
        ),
        replace(
            base,
            inputs=(
                InputDraft(
                    "trigger_message",
                    "mail_message",
                    "a" * 64,
                    "user_asserted",
                    message_id,
                    source_revision,
                ),
                InputDraft(
                    "thread_message",
                    "mail_message",
                    "b" * 64,
                    "user_asserted",
                    second_message,
                    None,
                ),
            ),
        ),
    )
    for draft in cases:
        with pytest.raises(MailRepositoryError):
            repo.publish_accepted_response(run.id, draft)
    assert connection.execute(
        "SELECT count(*) FROM mail_response_artifacts"
    ).fetchone()[0] == 0


def test_fact_scope_dates_activity_and_exact_supersession(tmp_path: Path) -> None:
    connection, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    first_run = repo.start_or_resume_run(request(subject_id, "fact-original"))
    first_base = response_draft(
        thread_id, message_id, key="fact-original-delivery"
    )
    first_draft = replace(
        first_base,
        facts=(
            FactDraft(
                "goal",
                '{"distance_km":10}',
                "long_term",
                "feedback_recorded",
                0.9,
                effective_from_utc=NOW,
            ),
        ),
    )
    first = repo.publish_accepted_response(first_run.id, first_draft)
    old_fact = first.fact_ids[0]

    second_run = repo.start_or_resume_run(request(subject_id, "fact-new"))
    second_base = response_draft(
        thread_id, message_id, key="fact-new-delivery"
    )
    second_draft = replace(
        second_base,
        facts=(
            FactDraft(
                "goal",
                '{"distance_km":21}',
                "long_term",
                "feedback_recorded",
                0.95,
                effective_from_utc="2026-07-24T00:00:00Z",
                supersedes_fact_id=old_fact,
            ),
        ),
    )
    second = repo.publish_accepted_response(second_run.id, second_draft)
    assert repo.publish_accepted_response(second_run.id, second_draft) == second
    old = connection.execute(
        "SELECT is_active,superseded_by_fact_id FROM user_facts WHERE id=?",
        (old_fact,),
    ).fetchone()
    new = connection.execute(
        "SELECT is_active,effective_from_utc FROM user_facts WHERE id=?",
        (second.fact_ids[0],),
    ).fetchone()
    assert tuple(old) == (0, second.fact_ids[0])
    assert tuple(new) == (1, "2026-07-24T00:00:00Z")

    message_only_run = repo.start_or_resume_run(
        request(subject_id, "fact-message-only")
    )
    message_only_base = response_draft(
        thread_id, message_id, key="fact-message-only-delivery"
    )
    message_only = repo.publish_accepted_response(
        message_only_run.id,
        replace(
            message_only_base,
            facts=(
                FactDraft(
                    "one_time_note",
                    '"today only"',
                    "message_only",
                    "feedback_recorded",
                    is_active=False,
                ),
            ),
        ),
    )
    assert tuple(
        connection.execute(
            "SELECT scope,is_active FROM user_facts WHERE id=?",
            (message_only.fact_ids[0],),
        ).fetchone()
    ) == ("message_only", 0)


def test_delivery_unknown_requires_reconcile_and_terminal_states_need_explicit_repair(
    tmp_path: Path,
) -> None:
    connection, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    run = repo.start_or_resume_run(request(subject_id, "delivery-state"))
    published = repo.publish_accepted_response(
        run.id, response_draft(thread_id, message_id, key="delivery-state-key")
    )
    assert published.delivery_id is not None
    assert repo.transition_delivery_state(
        subject_id, published.delivery_id, "sending"
    ).status == "sending"
    assert repo.transition_delivery_state(
        subject_id, published.delivery_id, "delivery_unknown"
    ).status == "delivery_unknown"
    with pytest.raises(MailRepositoryError, match="illegal_mail_delivery_transition"):
        repo.transition_delivery_state(
            subject_id, published.delivery_id, "sending"
        )

    connection.execute(
        "INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,"
        "actor_role,sent_at_utc,processing_state) VALUES(?,?,?,?,?,?)",
        (
            thread_id,
            "outbound-message",
            "outbound",
            "trainlab",
            NOW,
            "sent",
        ),
    )
    outbound = connection.execute(
        "SELECT id FROM mail_messages WHERE provider_message_id='outbound-message'"
    ).fetchone()[0]
    connection.commit()
    reconciled = repo.transition_delivery_state(
        subject_id,
        published.delivery_id,
        "sent",
        recovery_kind="reconcile",
        mail_message_id=outbound,
        provider_thread_id="thread-1",
        sent_at_utc=NOW,
        last_verified_at_utc=NOW,
    )
    assert reconciled.status == "sent" and reconciled.mail_message_id == outbound

    connection.execute(
        "UPDATE mail_messages SET processing_state='delivery_unknown' WHERE id=?",
        (message_id,),
    )
    connection.commit()
    with pytest.raises(MailRepositoryError, match="illegal_mail_message_transition"):
        repo.set_message_processing_state(subject_id, message_id, "sending")
    repo.set_message_processing_state(
        subject_id, message_id, "sent", recovery_kind="reconcile"
    )

    for terminal in ("failed", "rejected", "quarantined"):
        connection.execute(
            "UPDATE mail_messages SET processing_state=? WHERE id=?",
            (terminal, message_id),
        )
        connection.commit()
        with pytest.raises(
            MailRepositoryError, match="illegal_mail_message_transition"
        ):
            repo.set_message_processing_state(subject_id, message_id, "queued")
        repo.set_message_processing_state(
            subject_id, message_id, "queued", recovery_kind="repair"
        )

    repair_run = repo.start_or_resume_run(request(subject_id, "delivery-repair"))
    repair_delivery = repo.publish_accepted_response(
        repair_run.id,
        response_draft(
            thread_id, message_id, key="delivery-repair-key"
        ),
    ).delivery_id
    assert repair_delivery is not None
    repo.transition_delivery_state(subject_id, repair_delivery, "failed")
    with pytest.raises(MailRepositoryError, match="illegal_mail_delivery_transition"):
        repo.transition_delivery_state(subject_id, repair_delivery, "pending")
    assert repo.transition_delivery_state(
        subject_id,
        repair_delivery,
        "pending",
        recovery_kind="repair",
    ).status == "pending"


@pytest.mark.parametrize("terminal", ("failed", "rejected"))
def test_terminal_run_replay_never_reopens_or_rewrites(
    tmp_path: Path, terminal: str
) -> None:
    connection, repo, subject_id, _, _ = initialize(tmp_path)
    original = request(subject_id, f"terminal-{terminal}")
    run = repo.start_or_resume_run(original)
    finished = repo.finish_run(run.id, terminal)
    before = connection.total_changes
    replay = repo.start_or_resume_run(original)
    assert replay == finished
    assert replay.status == terminal
    assert connection.total_changes == before


@pytest.mark.parametrize(
    ("actor_role", "trust_level"),
    (
        ("system", "system_generated"),
        ("user", "user_asserted"),
        ("trainlab", "provider_fact"),
    ),
)
def test_event_draft_uses_exact_foundation_enums(
    tmp_path: Path, actor_role: str, trust_level: str
) -> None:
    connection, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    run = repo.start_or_resume_run(request(subject_id, "event-enums"))
    base = response_draft(thread_id, message_id, key="event-enums-delivery")
    bad = replace(
        base,
        events=(
            EventDraft(
                "feedback_recorded",
                actor_role,
                NOW,
                message_id,
                trust_level,
            ),
        ),
    )
    with pytest.raises(MailRepositoryError):
        repo.publish_accepted_response(run.id, bad)
    assert connection.execute(
        "SELECT count(*) FROM conversation_events"
    ).fetchone()[0] == 0


@pytest.mark.parametrize("terminal", (False, True))
@pytest.mark.parametrize(
    "tamper_kind",
    ("digest", "noncanonical_json", "identity_with_matching_digest"),
)
def test_resume_validates_canonical_snapshot_digest_and_full_identity_zero_write(
    tmp_path: Path, terminal: bool, tamper_kind: str
) -> None:
    connection, repo, subject_id, _, _ = initialize(tmp_path)
    original = request(subject_id, f"resume-integrity-{terminal}-{tamper_kind}")
    run = repo.start_or_resume_run(original)
    if terminal:
        repo.finish_run(run.id, "succeeded")
    row = connection.execute(
        "SELECT context_snapshot_json,context_snapshot_sha256 "
        "FROM mail_agent_runs WHERE id=?",
        (run.id,),
    ).fetchone()
    snapshot = json.loads(row["context_snapshot_json"])
    if tamper_kind == "digest":
        encoded = row["context_snapshot_json"]
        digest = "0" * 64
    elif tamper_kind == "noncanonical_json":
        encoded = json.dumps(snapshot, ensure_ascii=False, indent=2)
        digest = row["context_snapshot_sha256"]
    else:
        snapshot["mail_request_identity"]["requested_at_utc"] = (
            "2026-07-23T00:00:01Z"
        )
        encoded = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    connection.execute(
        "UPDATE mail_agent_runs SET context_snapshot_json=?,"
        "context_snapshot_sha256=? WHERE id=?",
        (encoded, digest, run.id),
    )
    connection.commit()
    before_changes = connection.total_changes
    before_row = connection.execute(
        "SELECT * FROM mail_agent_runs WHERE id=?", (run.id,)
    ).fetchone()
    with pytest.raises(
        MailRepositoryError, match="invocation_id_conflicts_with_existing_run"
    ):
        repo.start_or_resume_run(original)
    assert connection.total_changes == before_changes
    assert connection.execute(
        "SELECT * FROM mail_agent_runs WHERE id=?", (run.id,)
    ).fetchone() == before_row
    assert connection.execute(
        "SELECT count(*) FROM mail_agent_runs"
    ).fetchone()[0] == 1


@pytest.mark.parametrize(
    "event",
    (
        EventDraft(
            "feedback_recorded",
            "user",
            NOW,
            None,
            "system_generated",
        ),
        EventDraft(
            "mail_quarantined",
            "unknown",
            NOW,
            None,
            "system_generated",
        ),
        EventDraft(
            "mail_response_prepared",
            "trainlab",
            NOW,
            None,
            "untrusted_content",
        ),
        EventDraft(
            "feedback_recorded",
            "trainlab",
            NOW,
            None,
            "system_generated",
        ),
        EventDraft(
            "mail_response_prepared",
            "trainlab",
            NOW,
            None,
            "system_generated",
            related_run_key="foreign-run",
        ),
    ),
)
def test_null_message_event_semantics_and_run_ownership_fail_closed(
    tmp_path: Path, event: EventDraft
) -> None:
    connection, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    run = repo.start_or_resume_run(request(subject_id, "null-event-semantics"))
    base = response_draft(
        thread_id, message_id, key="null-event-semantics-delivery"
    )
    draft = replace(base, events=(event,), facts=())
    before_changes = connection.total_changes
    with pytest.raises(MailRepositoryError, match="conversation_event_ownership"):
        repo.publish_accepted_response(run.id, draft)
    assert connection.total_changes == before_changes
    for table in (
        "conversation_events",
        "mail_response_artifacts",
        "mail_response_inputs",
        "mail_deliveries",
        "mail_delivery_artifacts",
    ):
        assert connection.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0] == 0


def test_message_quarantine_and_crash_recovery_are_explicit_and_evidenced(
    tmp_path: Path,
) -> None:
    connection, repo, subject_id, _, message_id = initialize(tmp_path)
    connection.execute(
        "UPDATE mail_messages SET processing_state='normalized' WHERE id=?",
        (message_id,),
    )
    connection.commit()
    before = connection.total_changes
    with pytest.raises(MailRepositoryError, match="illegal_mail_message_transition"):
        repo.set_message_processing_state(
            subject_id, message_id, "quarantined"
        )
    assert connection.total_changes == before
    repo.set_message_processing_state(
        subject_id,
        message_id,
        "quarantined",
        recovery_kind="quarantine",
    )
    repo.set_message_processing_state(
        subject_id, message_id, "queued", recovery_kind="repair"
    )
    repo.set_message_processing_state(subject_id, message_id, "analyzing")
    before = connection.total_changes
    with pytest.raises(MailRepositoryError, match="illegal_mail_message_transition"):
        repo.set_message_processing_state(subject_id, message_id, "queued")
    assert connection.total_changes == before
    repo.set_message_processing_state(
        subject_id,
        message_id,
        "queued",
        recovery_kind="crash_recovery",
    )


def test_crash_recovery_cannot_requeue_an_accepted_response(
    tmp_path: Path,
) -> None:
    connection, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    run = repo.start_or_resume_run(request(subject_id, "accepted-crash"))
    repo.publish_accepted_response(
        run.id,
        response_draft(thread_id, message_id, key="accepted-crash-delivery"),
    )
    connection.execute(
        "UPDATE mail_messages SET processing_state='analyzing' WHERE id=?",
        (message_id,),
    )
    connection.commit()
    before = connection.total_changes
    with pytest.raises(MailRepositoryError, match="illegal_mail_message_transition"):
        repo.set_message_processing_state(
            subject_id,
            message_id,
            "queued",
            recovery_kind="crash_recovery",
        )
    assert connection.total_changes == before
    assert connection.execute(
        "SELECT processing_state FROM mail_messages WHERE id=?", (message_id,)
    ).fetchone()[0] == "analyzing"


def test_message_sent_requires_exact_verified_delivery_chain(
    tmp_path: Path,
) -> None:
    connection, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    run = repo.start_or_resume_run(request(subject_id, "message-send-proof"))
    published = repo.publish_accepted_response(
        run.id,
        response_draft(thread_id, message_id, key="message-send-proof-delivery"),
    )
    assert published.delivery_id is not None
    connection.execute(
        "UPDATE mail_messages SET processing_state='sending' WHERE id=?",
        (message_id,),
    )
    connection.commit()
    before = connection.total_changes
    with pytest.raises(
        MailRepositoryError, match="mail_message_delivery_evidence_required"
    ):
        repo.set_message_processing_state(subject_id, message_id, "sent")
    assert connection.total_changes == before
    assert connection.execute(
        "SELECT processing_state FROM mail_messages WHERE id=?", (message_id,)
    ).fetchone()[0] == "sending"
    connection.execute(
        "UPDATE mail_deliveries SET status='sent' WHERE id=?",
        (published.delivery_id,),
    )
    connection.commit()
    before = connection.total_changes
    with pytest.raises(
        MailRepositoryError, match="mail_message_delivery_evidence_required"
    ):
        repo.set_message_processing_state(subject_id, message_id, "sent")
    assert connection.total_changes == before
    connection.execute(
        "UPDATE mail_deliveries SET status='pending' WHERE id=?",
        (published.delivery_id,),
    )
    connection.commit()

    connection.execute(
        "INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,"
        "actor_role,sent_at_utc,processing_state) VALUES(?,?,?,?,?,?)",
        (
            thread_id,
            "message-send-proof-outbound",
            "outbound",
            "trainlab",
            NOW,
            "sent",
        ),
    )
    outbound = connection.execute(
        "SELECT id FROM mail_messages "
        "WHERE provider_message_id='message-send-proof-outbound'"
    ).fetchone()[0]
    connection.commit()
    repo.transition_delivery_state(
        subject_id, published.delivery_id, "sending"
    )
    repo.transition_delivery_state(
        subject_id,
        published.delivery_id,
        "sent",
        mail_message_id=outbound,
        provider_thread_id="thread-1",
        sent_at_utc=NOW,
        last_verified_at_utc=NOW,
    )
    repo.set_message_processing_state(subject_id, message_id, "sent")
    assert connection.execute(
        "SELECT processing_state FROM mail_messages WHERE id=?", (message_id,)
    ).fetchone()[0] == "sent"


def _add_analysis_artifact(
    connection: sqlite3.Connection,
    subject_id: int,
    suffix: str,
) -> int:
    connection.execute(
        "INSERT INTO analysis_runs(run_key,subject_id,analysis_kind,status,"
        "started_at_utc) VALUES(?,?,?,?,?)",
        (f"analysis-{suffix}", subject_id, "daily", "succeeded", NOW),
    )
    analysis_run_id = connection.execute(
        "SELECT id FROM analysis_runs WHERE run_key=?",
        (f"analysis-{suffix}",),
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO analysis_artifacts(subject_id,artifact_kind,"
        "period_start_local_date,period_end_local_date,revision_no,"
        "generated_by_run_id,schema_version,structured_content_json,"
        "user_visible_text,content_sha256,is_current,created_at_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,1,?)",
        (
            subject_id,
            "daily_summary",
            "2026-07-23",
            "2026-07-23",
            1,
            analysis_run_id,
            "1",
            "{}",
            suffix,
            hashlib.sha256(suffix.encode("utf-8")).hexdigest(),
            NOW,
        ),
    )
    return connection.execute(
        "SELECT id FROM analysis_artifacts WHERE generated_by_run_id=?",
        (analysis_run_id,),
    ).fetchone()[0]


def _add_subject_mail_fixture(
    connection: sqlite3.Connection,
) -> tuple[int, int, int, int]:
    connection.execute(
        "INSERT INTO data_subjects(subject_key,created_at_utc) VALUES(?,?)",
        ("other-item-subject", NOW),
    )
    subject_id = connection.execute(
        "SELECT id FROM data_subjects WHERE subject_key='other-item-subject'"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) "
        "VALUES(?,?,1)",
        (subject_id, "other-item-thread"),
    )
    thread_id = connection.execute(
        "SELECT id FROM mail_threads WHERE provider_thread_id='other-item-thread'"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO raw_objects(sha256,relative_path,media_type,size_bytes,"
        "provider,resource_kind,fetched_at_utc) VALUES(?,?,?,?,?,?,?)",
        (
            "e" * 64,
            "gmail/json/other-item-message.json",
            "application/json",
            2,
            "gmail",
            "message_json",
            NOW,
        ),
    )
    raw_id = connection.execute(
        "SELECT id FROM raw_objects WHERE sha256=?", ("e" * 64,)
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO source_revisions(provider,resource_kind,"
        "provider_object_id,revision_no,raw_object_id,payload_hash,is_current,"
        "parsed_at_utc) VALUES('gmail','message_json',?,1,?,?,1,?)",
        ("other-item-message", raw_id, "f" * 64, NOW),
    )
    source_revision_id = connection.execute(
        "SELECT id FROM source_revisions WHERE provider_object_id=?",
        ("other-item-message",),
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,"
        "actor_role,source_revision_id,processing_state) VALUES(?,?,?,?,?,?)",
        (
            thread_id,
            "other-item-message",
            "inbound",
            "user",
            source_revision_id,
            "new",
        ),
    )
    message_id = connection.execute(
        "SELECT id FROM mail_messages WHERE provider_message_id=?",
        ("other-item-message",),
    ).fetchone()[0]
    connection.commit()
    return subject_id, thread_id, message_id, source_revision_id


def test_item_relations_validate_subject_exact_relation_and_logical_identity(
    tmp_path: Path,
) -> None:
    connection, repo, subject_id, thread_id, message_id = initialize(tmp_path)
    other_subject, other_thread, other_message, other_revision = (
        _add_subject_mail_fixture(connection)
    )
    other_analysis = _add_analysis_artifact(
        connection, other_subject, "other-item"
    )
    connection.commit()
    other_request = MailRequest(
        mode="process",
        subject_id=other_subject,
        invocation_id="other-item-response",
        requested_at_utc=NOW,
        mail_message_ids=("other-item-message",),
    )
    other_run = repo.start_or_resume_run(other_request)
    other_base = response_draft(
        other_thread, other_message, key="other-item-delivery"
    )
    other_draft = replace(
        other_base,
        inputs=(
            InputDraft(
                "trigger_message",
                "mail_message",
                "e" * 64,
                "user_asserted",
                other_message,
                other_revision,
            ),
        ),
        delivery=DeliveryDraft("other-item-delivery", "other-item-thread"),
    )
    other_published = repo.publish_accepted_response(
        other_run.id, other_draft
    )
    primary_run = repo.start_or_resume_run(
        request(subject_id, "primary-item-relations")
    )
    primary_published = repo.publish_accepted_response(
        primary_run.id,
        response_draft(
            thread_id, message_id, key="primary-item-relations-delivery"
        ),
    )
    second_primary_run = repo.start_or_resume_run(
        request(subject_id, "second-primary-item-relations")
    )
    second_primary = repo.publish_accepted_response(
        second_primary_run.id,
        response_draft(
            thread_id, message_id, key="second-primary-item-delivery"
        ),
    )
    item_run = repo.start_or_resume_run(
        request(subject_id, "item-relation-validation")
    )
    bad_relations = (
        {
            "logical_item_kind": "thread",
            "logical_item_id": "cross-message",
            "mail_message_id": other_message,
        },
        {
            "logical_item_kind": "thread",
            "logical_item_id": "cross-analysis",
            "dependency_analysis_artifact_id": other_analysis,
        },
        {
            "logical_item_kind": "thread",
            "logical_item_id": "cross-response",
            "mail_response_artifact_id": other_published.response_artifact_id,
        },
        {
            "logical_item_kind": "thread",
            "logical_item_id": "cross-delivery",
            "mail_delivery_id": other_published.delivery_id,
        },
        {
            "logical_item_kind": "thread",
            "logical_item_id": "mismatched-response-delivery",
            "mail_response_artifact_id": primary_published.response_artifact_id,
            "mail_delivery_id": second_primary.delivery_id,
        },
        {
            "logical_item_kind": "message",
            "logical_item_id": "wrong-message-id",
            "mail_message_id": message_id,
        },
    )
    for ordinal, relation in enumerate(bad_relations):
        before_changes = connection.total_changes
        before_count = connection.execute(
            "SELECT count(*) FROM mail_agent_items"
        ).fetchone()[0]
        with pytest.raises(MailRepositoryError):
            repo.record_item(
                item_run.id,
                stage="context",
                status="pending",
                **relation,
            )
        assert connection.total_changes == before_changes, ordinal
        assert connection.execute(
            "SELECT count(*) FROM mail_agent_items"
        ).fetchone()[0] == before_count


def test_item_and_run_evidence_combinations_are_strict_and_idempotent(
    tmp_path: Path,
) -> None:
    connection, repo, subject_id, _, message_id = initialize(tmp_path)
    run = repo.start_or_resume_run(request(subject_id, "strict-evidence"))
    invalid_items = (
        {
            "status": "succeeded",
            "error_code": "parse_failed",
            "next_retry_at_utc": "2026-07-23T00:01:00Z",
        },
        {"status": "succeeded", "error_summary": "must not persist"},
        {"status": "failed"},
        {"status": "rejected", "next_retry_at_utc": "2026-07-23T00:01:00Z"},
        {"status": "deferred"},
        {
            "status": "deferred",
            "error_code": "rate_limited",
            "next_retry_at_utc": "not-a-time",
        },
    )
    for ordinal, evidence in enumerate(invalid_items):
        before = connection.total_changes
        with pytest.raises(MailRepositoryError):
            repo.record_item(
                run.id,
                logical_item_kind="message",
                logical_item_id="message-1",
                stage="context",
                mail_message_id=message_id,
                **evidence,
            )
        assert connection.total_changes == before, ordinal
    before = connection.total_changes
    with pytest.raises(MailRepositoryError, match="invalid_mail_run_evidence"):
        repo.finish_run(
            run.id, "partial", next_retry_at_utc="not-a-time"
        )
    assert connection.total_changes == before

    retry_item = repo.record_item(
        run.id,
        logical_item_kind="message",
        logical_item_id="message-1",
        stage="generate",
        status="deferred",
        mail_message_id=message_id,
        error_code="rate_limited",
        error_summary="private@example.invalid",
        next_retry_at_utc="2026-07-23T00:01:00Z",
    )
    before = connection.total_changes
    assert repo.record_item(
        run.id,
        logical_item_kind="message",
        logical_item_id="message-1",
        stage="generate",
        status="deferred",
        mail_message_id=message_id,
        error_code="rate_limited",
        error_summary="ignored on normalization",
        next_retry_at_utc="2026-07-23T00:01:00Z",
    ) == retry_item
    assert connection.total_changes == before
    with pytest.raises(MailRepositoryError, match="conflicting_mail_item_replay"):
        repo.record_item(
            run.id,
            logical_item_kind="message",
            logical_item_id="message-1",
            stage="generate",
            status="deferred",
            mail_message_id=message_id,
            error_code="rate_limited",
            next_retry_at_utc="2026-07-23T00:02:00Z",
        )
    assert connection.total_changes == before

    run_with_retry = repo.start_or_resume_run(
        request(subject_id, "strict-run-retry")
    )
    repo.finish_run(
        run_with_retry.id,
        "deferred",
        next_retry_at_utc="2026-07-23T00:01:00Z",
    )
    before = connection.total_changes
    repo.finish_run(
        run_with_retry.id,
        "deferred",
        next_retry_at_utc="2026-07-23T00:01:00Z",
    )
    assert connection.total_changes == before
    with pytest.raises(MailRepositoryError, match="conflicting_mail_run_replay"):
        repo.finish_run(
            run_with_retry.id,
            "deferred",
            next_retry_at_utc="2026-07-23T00:02:00Z",
        )
    assert connection.total_changes == before


def test_dependency_wait_is_the_only_deferred_item_and_run_without_retry(
    tmp_path: Path,
) -> None:
    connection, repo, subject_id, _, _ = initialize(tmp_path)
    dependency_id = _add_analysis_artifact(
        connection, subject_id, "dependency-wait"
    )
    connection.commit()
    run = repo.start_or_resume_run(request(subject_id, "dependency-wait"))
    before = connection.total_changes
    with pytest.raises(MailRepositoryError, match="invalid_mail_item_evidence"):
        repo.record_item(
            run.id,
            logical_item_kind="dependency_analysis_artifact",
            logical_item_id=str(dependency_id),
            stage="generate",
            status="deferred",
            dependency_analysis_artifact_id=dependency_id,
            error_code="parse_failed",
        )
    assert connection.total_changes == before
    item = repo.record_item(
        run.id,
        logical_item_kind="dependency_analysis_artifact",
        logical_item_id=str(dependency_id),
        stage="context",
        status="deferred",
        dependency_analysis_artifact_id=dependency_id,
    )
    assert item.status == "deferred"
    assert repo.finish_run(run.id, "deferred").status == "deferred"
