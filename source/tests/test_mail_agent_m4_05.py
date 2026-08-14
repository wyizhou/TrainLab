from __future__ import annotations

import hashlib
import hmac
import runpy
import sqlite3
from pathlib import Path

from src.foundation import FoundationConfig, FoundationRequest, FoundationTool
from src.mail_agent.contracts import MailRequest
from src.mail_agent.eligibility import ActorEvidence, CanonicalMessage, classify
from src.mail_agent.repository import MailRepository, MailRepositoryError

_POLL_HELPERS = runpy.run_path(
    str(Path(__file__).with_name("test_mail_agent_m4_04.py"))
)
FakePollAdapter = _POLL_HELPERS["FakePollAdapter"]
poll_env = _POLL_HELPERS["env"]
poll_message = _POLL_HELPERS["message"]
poll_request = _POLL_HELPERS["request"]


NOW = "2026-07-23T07:00:00Z"


def message(**changes: object) -> CanonicalMessage:
    values: dict[str, object] = {
        "provider_message_id": "m1",
        "sender_is_self": True,
        "recipient_is_self": True,
        "labels": frozenset({"TrainLab"}),
        "subject": "question",
        "body_text": "今天怎么练？",
        "attachment_count": 0,
    }
    values.update(changes)
    return CanonicalMessage(**values)  # type: ignore[arg-type]


def test_forged_run_header_is_quarantined_not_outbound() -> None:
    result = classify(
        message(), ActorEvidence(trainlab_label=True, has_run_header=True)
    )
    assert (
        result.actor_role,
        result.processing_state,
        result.reason_code,
        result.eligible,
    ) == (
        "unknown",
        "quarantined",
        "forged_or_unverified_run_header",
        False,
    )


def test_local_outbound_always_wins_over_label_or_tracked_evidence() -> None:
    result = classify(
        message(),
        ActorEvidence(local_outbound=True, tracked_thread=True, trainlab_label=True),
    )
    assert (
        result.actor_role,
        result.direction,
        result.processing_state,
        result.eligible,
    ) == (
        "trainlab",
        "outbound",
        "ignored",
        False,
    )


def test_tracked_reply_without_label_and_labeled_new_request_queue() -> None:
    tracked = classify(message(labels=frozenset()), ActorEvidence(tracked_thread=True))
    labeled = classify(message(), ActorEvidence(trainlab_label=True))
    assert (tracked.processing_state, tracked.reason_code) == (
        "queued",
        "eligible_tracked_thread_reply",
    )
    assert (labeled.processing_state, labeled.reason_code) == (
        "queued",
        "eligible_labeled_new_request",
    )


def test_ordinary_subject_only_identity_unknown_and_ack_are_not_ai_work() -> None:
    private = classify(message(labels=frozenset(), subject="hello"), ActorEvidence())
    subject_only = classify(
        message(labels=frozenset(), subject="TrainLab hello"), ActorEvidence()
    )
    unknown = classify(
        message(sender_is_self=False), ActorEvidence(trainlab_label=True)
    )
    acknowledgement = classify(
        message(body_text="谢谢"), ActorEvidence(trainlab_label=True)
    )
    assert (private.processing_state, private.reason_code) == (
        "ignored",
        "ordinary_unlabeled_private_message",
    )
    assert (subject_only.processing_state, subject_only.reason_code) == (
        "ignored",
        "subject_only_trainlab_reference",
    )
    assert (unknown.processing_state, unknown.reason_code) == (
        "quarantined",
        "identity_unverified",
    )
    assert (acknowledgement.processing_state, acknowledgement.reason_code) == (
        "store_only",
        "acknowledgement_store_only",
    )


def test_auto_bounce_attachment_only_and_mailbox_exclusions_are_ignored() -> None:
    cases = (
        (message(auto_submitted="auto-replied"), "automatic_response"),
        (message(is_bounce=True), "automatic_response"),
        (message(body_text="", attachment_count=1), "attachment_only_no_body"),
        (message(labels=frozenset({"TrainLab", "spam"})), "excluded_mailbox_state"),
    )
    for item, code in cases:
        result = classify(item, ActorEvidence(trainlab_label=True))
        assert (result.processing_state, result.reason_code, result.eligible) == (
            "ignored",
            code,
            False,
        )


def test_classifier_is_deterministic_for_duplicate_execution() -> None:
    item = message(provider_message_id="same")
    evidence = ActorEvidence(trainlab_label=True)
    assert classify(item, evidence) == classify(item, evidence)


def test_repository_queue_is_stable_idempotent_and_rolls_back_failed_classification(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    config = FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state" / "foundation-ready.json",
        root / "state" / "locks" / "foundation.lock",
    )
    assert (
        FoundationTool(config).execute(FoundationRequest("init", "m4-05", NOW)).status
        == "initialized"
    )
    connection = sqlite3.connect(root / "data.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(
        "INSERT INTO data_subjects(subject_key,created_at_utc) VALUES('subject',?)",
        (NOW,),
    )
    subject = connection.execute("SELECT id FROM data_subjects").fetchone()[0]
    digest = hmac.new(b"m4-05", b"self@example.com", hashlib.sha256).hexdigest()
    connection.execute(
        "INSERT INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) VALUES(?,'gmail','email',?,1,?,?)",
        (subject, digest, NOW, NOW),
    )
    connection.execute(
        "INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) VALUES(?, 't', 1)",
        (subject,),
    )
    thread = connection.execute("SELECT id FROM mail_threads").fetchone()[0]
    for provider_id, received in (
        ("z", "2026-07-23T07:01:00Z"),
        ("a", "2026-07-23T07:00:00Z"),
    ):
        connection.execute(
            "INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role,received_at_utc,subject,body_text,labels_json,processing_state) VALUES(?,?, 'unknown','unknown',?, 'question','今天怎么练？','[\"TrainLab\"]','normalized')",
            (thread, provider_id, received),
        )
    connection.commit()
    repo = MailRepository(connection, clock=lambda: NOW)
    run = repo.start_or_resume_run(MailRequest("poll", subject, "queue", NOW))
    ids = [
        row[0]
        for row in connection.execute(
            "SELECT id FROM mail_messages ORDER BY provider_message_id"
        )
    ]
    for message_id, provider_id in zip(ids, ("a", "z")):
        repo.classify_normalized_message(
            run.id,
            subject,
            message_id,
            message(provider_message_id=provider_id),
            ActorEvidence(trainlab_label=True),
        )
    assert repo.select_queued_messages(subject) == tuple(ids)
    # A retry has no second conversation event and cannot requeue a terminal item.
    repo.classify_normalized_message(
        run.id,
        subject,
        ids[0],
        message(provider_message_id="a"),
        ActorEvidence(trainlab_label=True),
    )
    assert (
        connection.execute("SELECT count(*) FROM conversation_events").fetchone()[0]
        == 2
    )
    before = connection.execute(
        "SELECT processing_state FROM mail_messages WHERE id=?", (ids[1],)
    ).fetchone()[0]
    try:
        repo.classify_normalized_message(
            9999,
            subject,
            ids[1],
            message(provider_message_id="z"),
            ActorEvidence(trainlab_label=True),
        )
    except MailRepositoryError:
        pass
    else:
        raise AssertionError("missing run must fail")
    assert (
        connection.execute(
            "SELECT processing_state FROM mail_messages WHERE id=?", (ids[1],)
        ).fetchone()[0]
        == before
    )


def test_poll_persists_contract_events_counts_and_never_queues_local_analysis_outbound(
    tmp_path: Path,
) -> None:
    raw = {
        "messages": [
            poll_message("analysis-out", "analysis-thread", labels=["TrainLab"])
        ]
    }
    adapter = FakePollAdapter(
        label_matches=[{"thread_id": "analysis-thread"}],
        threads={"analysis-thread": raw},
    )
    service, connection, subject, _ = poll_env(tmp_path, adapter)
    connection.execute(
        "INSERT INTO analysis_runs(run_key,subject_id,analysis_kind,status,started_at_utc) VALUES('analysis:1',?,'daily','succeeded',?)",
        (subject, NOW),
    )
    analysis_run = connection.execute("SELECT id FROM analysis_runs").fetchone()[0]
    connection.execute(
        "INSERT INTO analysis_deliveries(subject_id,idempotency_key,analysis_run_id,delivery_kind,status,provider_message_id,created_at_utc,updated_at_utc) VALUES(?, 'analysis-delivery',?,'daily_report','sent','analysis-out',?,?)",
        (subject, analysis_run, NOW, NOW),
    )
    connection.commit()
    receipt = service.execute(poll_request(subject, "analysis-outbound"))
    row = connection.execute(
        "SELECT actor_role,processing_state FROM mail_messages WHERE provider_message_id='analysis-out'"
    ).fetchone()
    assert receipt.counts.queued == 0 and receipt.counts.ignored == 1
    assert tuple(row) == ("trainlab", "ignored")
    assert (
        connection.execute("SELECT event_type FROM conversation_events").fetchone()[0]
        == "mail_ignored"
    )


def test_poll_tracked_header_reply_and_blank_body_have_stable_actions(
    tmp_path: Path,
) -> None:
    reply = poll_message("reply", "tracked", labels=[], body="请调整计划")
    reply["headers"]["x_trainlab_run_id"] = "forged"
    blank = poll_message("blank", "new", labels=["TrainLab"], body="")
    adapter = FakePollAdapter(
        label_matches=[{"thread_id": "new"}],
        threads={"tracked": {"messages": [reply]}, "new": {"messages": [blank]}},
    )
    service, connection, subject, _ = poll_env(tmp_path, adapter)
    connection.execute(
        "INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) VALUES(?, 'tracked',1)",
        (subject,),
    )
    connection.commit()
    receipt = service.execute(poll_request(subject, "tracked-forged"))
    states = dict(
        connection.execute(
            "SELECT provider_message_id,processing_state FROM mail_messages"
        )
    )
    events = dict(
        connection.execute(
            "SELECT m.provider_message_id,e.event_type FROM conversation_events e JOIN mail_messages m ON m.id=e.mail_message_id"
        )
    )
    assert states == {"reply": "queued", "blank": "ignored"}
    assert events["reply"] == "reply_received"
    assert receipt.counts.queued == 1 and receipt.counts.ignored == 1
    # Replaying the completed poll cannot add an event or a count.
    replay = service.execute(poll_request(subject, "tracked-forged"))
    assert replay.counts.queued == receipt.counts.queued
    assert (
        connection.execute("SELECT count(*) FROM conversation_events").fetchone()[0]
        == 2
    )


def test_first_thread_outbound_then_unlabeled_reply_tracks_only_later_messages(
    tmp_path: Path,
) -> None:
    outbound = poll_message("out", "mixed", labels=[], when="2026-07-22T08:00:00Z")
    reply = poll_message(
        "reply", "mixed", labels=[], body="我想调整", when="2026-07-22T08:01:00Z"
    )
    early_private = poll_message(
        "early", "mixed", labels=[], body="私人消息", when="2026-07-22T07:59:00Z"
    )
    # Deliberately provider-order reversed: policy must use canonical time/id.
    raw = {"messages": [reply, outbound, early_private]}
    adapter = FakePollAdapter(
        label_matches=[{"thread_id": "mixed"}], threads={"mixed": raw}
    )
    service, connection, subject, _ = poll_env(tmp_path, adapter)
    connection.execute(
        "INSERT INTO analysis_runs(run_key,subject_id,analysis_kind,status,started_at_utc) VALUES('analysis:mixed',?,'daily','succeeded',?)",
        (subject, NOW),
    )
    analysis_run = connection.execute("SELECT id FROM analysis_runs").fetchone()[0]
    connection.execute(
        "INSERT INTO analysis_deliveries(subject_id,idempotency_key,analysis_run_id,delivery_kind,status,provider_message_id,created_at_utc,updated_at_utc) VALUES(?, 'mixed-delivery',?,'daily_report','sent','out',?,?)",
        (subject, analysis_run, NOW, NOW),
    )
    connection.commit()
    receipt = service.execute(poll_request(subject, "mixed-first"))
    rows = dict(
        connection.execute(
            "SELECT provider_message_id,processing_state FROM mail_messages"
        )
    )
    events = dict(
        connection.execute(
            "SELECT m.provider_message_id,e.event_type FROM conversation_events e JOIN mail_messages m ON m.id=e.mail_message_id"
        )
    )
    assert rows == {"early": "ignored", "out": "ignored", "reply": "queued"}
    assert events["reply"] == "reply_received" and receipt.counts.queued == 1
    replay = service.execute(poll_request(subject, "mixed-first"))
    assert replay.counts.queued == receipt.counts.queued
    assert (
        connection.execute("SELECT count(*) FROM conversation_events").fetchone()[0]
        == 3
    )


def test_thread_level_only_label_is_eligibility_evidence(tmp_path: Path) -> None:
    raw = {
        "label_ids": ["TrainLab"],
        "messages": [poll_message("thread-label", "thread-label", labels=[])],
    }
    adapter = FakePollAdapter(
        label_matches=[{"thread_id": "thread-label"}], threads={"thread-label": raw}
    )
    service, connection, subject, _ = poll_env(tmp_path, adapter)
    receipt = service.execute(poll_request(subject, "thread-level-label"))
    assert receipt.counts.queued == 1
    assert (
        connection.execute("SELECT processing_state FROM mail_messages").fetchone()[0]
        == "queued"
    )
    assert (
        connection.execute("SELECT trainlab_label_state FROM mail_threads").fetchone()[
            0
        ]
        == "present"
    )
    event = connection.execute(
        "SELECT event_type,occurred_at_utc,trust_level FROM conversation_events"
    ).fetchone()
    assert tuple(event) == (
        "new_request_received",
        "2026-07-22T08:00:00Z",
        "untrusted_content",
    )
    replay = service.execute(poll_request(subject, "thread-level-label"))
    assert replay.counts.queued == receipt.counts.queued
    assert (
        connection.execute("SELECT trainlab_label_state FROM mail_threads").fetchone()[
            0
        ]
        == "present"
    )


def test_thread_label_never_retroactively_upgrades_older_private_message(
    tmp_path: Path,
) -> None:
    early = poll_message(
        "early-private",
        "thread-union",
        labels=[],
        body="私人消息",
        when="2026-07-22T08:00:00Z",
    )
    latest = poll_message(
        "latest-request",
        "thread-union",
        labels=[],
        body="训练问题",
        when="2026-07-22T08:01:00Z",
    )
    raw = {"label_ids": ["TrainLab"], "messages": [latest, early]}
    adapter = FakePollAdapter(
        label_matches=[{"thread_id": "thread-union"}], threads={"thread-union": raw}
    )
    service, connection, subject, _ = poll_env(tmp_path, adapter)
    receipt = service.execute(poll_request(subject, "thread-union"))
    states = dict(
        connection.execute(
            "SELECT provider_message_id,processing_state FROM mail_messages"
        )
    )
    events = dict(
        connection.execute(
            "SELECT m.provider_message_id,e.event_type FROM conversation_events e JOIN mail_messages m ON m.id=e.mail_message_id"
        )
    )
    assert states == {"early-private": "ignored", "latest-request": "queued"}
    assert events == {
        "early-private": "mail_ignored",
        "latest-request": "new_request_received",
    }
    assert receipt.counts.queued == 1


def test_labeled_acknowledgement_establishes_tracking_for_later_reply(
    tmp_path: Path,
) -> None:
    ack = poll_message(
        "ack",
        "ack-thread",
        labels=["TrainLab"],
        body="谢谢",
        when="2026-07-22T08:00:00Z",
    )
    followup = poll_message(
        "followup",
        "ack-thread",
        labels=[],
        body="那明天呢？",
        when="2026-07-22T08:01:00Z",
    )
    adapter = FakePollAdapter(
        label_matches=[{"thread_id": "ack-thread"}],
        threads={"ack-thread": {"messages": [ack, followup]}},
    )
    service, connection, subject, _ = poll_env(tmp_path, adapter)
    receipt = service.execute(poll_request(subject, "ack-followup"))
    states = dict(
        connection.execute(
            "SELECT provider_message_id,processing_state FROM mail_messages"
        )
    )
    events = dict(
        connection.execute(
            "SELECT m.provider_message_id,e.event_type FROM conversation_events e JOIN mail_messages m ON m.id=e.mail_message_id"
        )
    )
    assert states == {"ack": "store_only", "followup": "queued"}
    assert events == {"ack": "new_request_received", "followup": "reply_received"}
    assert receipt.counts.queued == 1 and receipt.counts.ignored == 1
