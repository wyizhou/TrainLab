from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.mail_agent.context import MailContextBuilder
from trainlab.mail_agent.contracts import MailRequest
from trainlab.mail_agent.fact_gate import (
    ActiveFactEvidence,
    AnalysisDependencyEvidence,
    FactGateEvidence,
    MailFactGate,
    MailFactGateError,
)
from trainlab.mail_agent.repository import MailRepository, MailRepositoryError

NOW = "2026-07-24T00:00:00Z"
END = "2026-07-30"


def initialize(
    tmp_path: Path,
    *,
    body: str = "From now on my training goal is marathon.",
) -> tuple[sqlite3.Connection, MailRepository, int, int, int, int]:
    root = tmp_path / "foundation"
    config = FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state" / "foundation-ready.json",
        root / "state" / "locks" / "foundation.lock",
    )
    assert FoundationTool(config).execute(
        FoundationRequest("init", "m408", NOW)
    ).ready
    connection = sqlite3.connect(root / "data.db", isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute(
        "INSERT INTO data_subjects(subject_key,created_at_utc) VALUES('subject',?)",
        (NOW,),
    )
    subject_id = connection.execute(
        "SELECT id FROM data_subjects"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO source_revisions("
        "provider,resource_kind,provider_object_id,revision_no,payload_hash,"
        "is_current,parsed_at_utc) "
        "VALUES('gmail','message_json','message-1',1,?,1,?)",
        ("a" * 64, NOW),
    )
    source_revision_id = connection.execute(
        "SELECT id FROM source_revisions"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) "
        "VALUES(?,'thread-1',1)",
        (subject_id,),
    )
    thread_id = connection.execute(
        "SELECT id FROM mail_threads"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO mail_messages("
        "mail_thread_id,provider_message_id,direction,actor_role,"
        "received_at_utc,subject,body_text,body_sha256,source_revision_id,"
        "processing_state) VALUES(?,'message-1','inbound','user',?,"
        "'TrainLab',?,?,?,'queued')",
        (thread_id, NOW, body, "b" * 64, source_revision_id),
    )
    message_id = connection.execute(
        "SELECT id FROM mail_messages"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO conversation_events("
        "subject_id,event_type,actor_role,occurred_at_utc,mail_message_id,"
        "structured_payload_json,trust_level,created_by) "
        "VALUES(?,'new_request_received','user',?,?,'{}',"
        "'untrusted_content','mail_agent')",
        (subject_id, NOW, message_id),
    )
    _add_plan(
        connection,
        subject_id,
        suffix="original",
        analysis_kind="weekly",
        analysis_status="succeeded",
        plan_status="active",
        is_current=1,
    )
    repo = MailRepository(connection, clock=lambda: NOW)
    run = repo.start_or_resume_run(
        MailRequest(
            mode="process",
            subject_id=subject_id,
            invocation_id="process-1",
            requested_at_utc=NOW,
            mail_message_ids=("message-1",),
        )
    )
    return connection, repo, subject_id, thread_id, message_id, run.id


def _add_plan(
    connection: sqlite3.Connection,
    subject_id: int,
    *,
    suffix: str,
    analysis_kind: str,
    analysis_status: str,
    plan_status: str,
    is_current: int,
    reason_event_id: int | None = None,
    period_start: str = "2026-07-24",
    period_end: str = END,
) -> tuple[int, int, int]:
    snapshot = (
        "{}"
        if reason_event_id is None
        else json.dumps({"request": {"reason_event_id": reason_event_id}})
    )
    connection.execute(
        "INSERT INTO analysis_runs("
        "run_key,subject_id,analysis_kind,target_start_local_date,"
        "target_end_local_date,status,context_snapshot_json,started_at_utc,"
        "completed_at_utc) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            f"analysis-{suffix}",
            subject_id,
            analysis_kind,
            period_start,
            period_end,
            analysis_status,
            snapshot,
            NOW,
            NOW if analysis_status != "started" else None,
        ),
    )
    analysis_run_id = connection.execute(
        "SELECT id FROM analysis_runs WHERE run_key=?",
        (f"analysis-{suffix}",),
    ).fetchone()[0]
    revision_no = connection.execute(
        "SELECT COALESCE(MAX(revision_no),0)+1 FROM analysis_artifacts "
        "WHERE subject_id=? AND artifact_kind='weekly_training_plan' "
        "AND period_start_local_date=? AND period_end_local_date=?",
        (subject_id, period_start, period_end),
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO analysis_artifacts("
        "subject_id,artifact_kind,period_start_local_date,"
        "period_end_local_date,revision_no,generated_by_run_id,"
        "schema_version,structured_content_json,user_visible_text,"
        "content_sha256,is_current,created_at_utc) "
        "VALUES(?,'weekly_training_plan',?,?,?,?, '1','{}',?,?,?,?)",
        (
            subject_id,
            period_start,
            period_end,
            revision_no,
            analysis_run_id,
            suffix,
            hashlib.sha256(suffix.encode()).hexdigest(),
            is_current,
            NOW,
        ),
    )
    artifact_id = connection.execute(
        "SELECT id FROM analysis_artifacts WHERE generated_by_run_id=?",
        (analysis_run_id,),
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO training_plans("
        "subject_id,analysis_artifact_id,plan_start_local_date,"
        "plan_end_local_date,timezone,status,objective_json,"
        "constraints_json,created_at_utc) "
        "VALUES(?,?,?,?,'Asia/Singapore',?,'{}','{}',?)",
        (
            subject_id,
            artifact_id,
            period_start,
            period_end,
            plan_status,
            NOW,
        ),
    )
    plan_id = connection.execute(
        "SELECT id FROM training_plans WHERE analysis_artifact_id=?",
        (artifact_id,),
    ).fetchone()[0]
    start_day = int(period_start[-2:])
    for index in range(7):
        day = f"2026-07-{start_day + index:02d}"
        connection.execute(
            "INSERT INTO training_plan_items("
            "training_plan_id,item_index,local_date,activity_kind,"
            "prescription_json,rationale_text,stop_conditions_json) "
            "VALUES(?,?,?,'rest','{}',NULL,'{}')",
            (plan_id, index, day),
        )
    return analysis_run_id, artifact_id, plan_id


def context(
    connection: sqlite3.Connection,
    subject_id: int,
    run_id: int,
    message_id: int,
) -> dict:
    return MailContextBuilder(
        connection,
        shared_harness_version="shared",
        mail_harness_version="mail",
    ).build(
        run_id=run_id,
        subject_id=subject_id,
        trigger_message_id=message_id,
        as_of_local_date="2026-07-24",
    ).payload


def usage(payload: dict, *roles: str) -> list[dict]:
    selected = []
    for entry in payload["input_manifest"]:
        if entry["input_role"] in roles:
            selected.append(
                {
                    "ordinal": entry["ordinal"],
                    "input_role": entry["input_role"],
                    "source_entity_id": entry["source_entity_id"],
                }
            )
    return selected


def result(payload: dict, **changes: object) -> dict:
    value = {
        "schema_version": "1",
        "run_key": payload["run"]["run_key"],
        "trigger_message_id": payload["trigger_message"]["id"],
        "intent": "feedback",
        "action": "store_only",
        "response": None,
        "fact_candidates": [],
        "plan_revision_request": None,
        "source_usage": usage(payload, "trigger_message"),
        "data_limitations": [],
        "safety": {"red_flag": False, "exercise_suspended": False},
        "warnings": [],
    }
    value.update(changes)
    return value


def evidence(payload: dict, **changes: object) -> FactGateEvidence:
    trigger = payload["trigger_message"]
    value = FactGateEvidence(
        subject_id=payload["current_training_plan"]["subject_id"],
        run_id=payload["run"]["id"],
        run_key=payload["run"]["run_key"],
        request_kind="process",
        run_status="started",
        requested_provider_message_ids=(trigger["provider_message_id"],),
        mail_message_id=trigger["id"],
        provider_message_id=trigger["provider_message_id"],
        mail_thread_id=trigger["thread_id"],
        provider_thread_id=trigger["provider_thread_id"],
        source_revision_id=trigger["source_revision_id"],
        source_revision_is_current=True,
        actor_role="user",
        direction="inbound",
        processing_state="queued",
        eligibility_event_type="new_request_received",
        accepted_response_id=None,
        as_of_utc=NOW,
    )
    return replace(value, **changes)


def fact_candidate(
    payload: dict,
    *,
    key: str = "training_goal",
    value: str = "marathon",
    scope: str = "long_term",
    effective: str | None = NOW,
    expires: str | None = None,
) -> dict:
    text = payload["trigger_message"]["latest_authored_text"]
    return {
        "fact_key": key,
        "fact_value": value,
        "scope": scope,
        "effective_from": effective,
        "expires_at": expires,
        "source_mail_message_id": payload["trigger_message"]["id"],
        "evidence_text_span": {
            "start": 0,
            "end": len(text),
            "text": text,
        },
        "confidence": 1.0,
    }


def reply(payload: dict, text: str = "Thanks, I recorded that.") -> dict:
    return {
        "response_kind": "mail_response",
        "subject_intent": "TrainLab reply",
        "structured_content": {"kind": "reply"},
        "user_visible_text": text,
        "requires_thread_reply": True,
    }


def plan_result(payload: dict) -> dict:
    text = payload["trigger_message"]["latest_authored_text"]
    return result(
        payload,
        intent="plan_change_request",
        action="await_analysis",
        plan_revision_request={
            "source_mail_message_id": payload["trigger_message"]["id"],
            "change_kind": "move",
            "affected_local_dates": ["2026-07-25"],
            "constraints": {},
            "effective_local_date": "2026-07-25",
            "current_plan_id": payload["current_training_plan"]["id"],
            "evidence_text_span": {
                "start": 0,
                "end": len(text),
                "text": text,
            },
            "trust_level": "user_asserted",
        },
    )


def test_policy_is_versioned_closed_and_schema_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    policy = json.loads(
        (root / "harness/mail/fact-gate-policy.json").read_text()
    )
    schema = json.loads(
        (root / "harness/schemas/mail_fact_gate_policy.schema.json").read_text()
    )
    assert policy["policy_version"] == "mail-fact-gate-v1"
    assert not list(Draft202012Validator(schema).iter_errors(policy))
    bad = {**policy, "unknown": True}
    assert list(Draft202012Validator(schema).iter_errors(bad))


def test_long_term_fact_is_exact_and_repository_gate_has_zero_writes(
    tmp_path: Path,
) -> None:
    connection, repo, subject, _, message, run = initialize(tmp_path)
    payload = context(connection, subject, run, message)
    output = result(
        payload,
        intent="user_fact_update",
        fact_candidates=[fact_candidate(payload)],
    )
    before = connection.total_changes
    decision = repo.gate_mail_result(run, output, payload)
    assert decision.status == "accepted"
    assert decision.facts[0].persist
    assert decision.facts[0].fact_value_json == '"marathon"'
    assert connection.total_changes == before
    assert connection.execute("SELECT count(*) FROM user_facts").fetchone()[0] == 0


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"subject_id": 999}, "identity"),
        ({"run_key": "wrong"}, "identity"),
        ({"mail_thread_id": 999}, "identity"),
        ({"mail_message_id": 999}, "identity"),
        ({"source_revision_is_current": False}, "identity"),
        ({"actor_role": "trainlab"}, "identity"),
        ({"direction": "outbound"}, "identity"),
        ({"eligibility_event_type": "ambiguous"}, "identity"),
        ({"accepted_response_id": 1}, "identity"),
    ],
)
def test_subject_thread_message_run_revision_actor_and_response_fail_closed(
    tmp_path: Path, changes: dict, code: str
) -> None:
    connection, _, subject, _, message, run = initialize(tmp_path)
    payload = context(connection, subject, run, message)
    with pytest.raises(MailFactGateError, match=code):
        MailFactGate().evaluate(
            result(payload),
            payload,
            evidence(payload, **changes),
        )


@pytest.mark.parametrize(
    "scope,effective,expires,body,code",
    [
        ("long_term", NOW, None, "My training goal is marathon.", "long_term"),
        ("temporary", NOW, None, "Now pain status is sore.", "scope"),
        (
            "temporary",
            NOW,
            "2026-07-23T00:00:00Z",
            "Now pain status is sore.",
            "scope",
        ),
        (
            "temporary",
            "2026-07-25T00:00:00Z",
            "2026-07-24T00:00:00Z",
            "Now pain status is sore.",
            "scope",
        ),
    ],
)
def test_fact_scope_effective_expiry_are_strict(
    tmp_path: Path,
    scope: str,
    effective: str | None,
    expires: str | None,
    body: str,
    code: str,
) -> None:
    connection, _, subject, _, message, run = initialize(tmp_path, body=body)
    payload = context(connection, subject, run, message)
    candidate = fact_candidate(
        payload,
        key="pain_status" if scope == "temporary" else "training_goal",
        value="sore" if scope == "temporary" else "marathon",
        scope=scope,
        effective=effective,
        expires=expires,
    )
    with pytest.raises(MailFactGateError, match=code):
        MailFactGate().evaluate(
            result(
                payload,
                intent="user_fact_update",
                fact_candidates=[candidate],
            ),
            payload,
            evidence(payload),
        )


def test_exact_replay_and_explicit_supersession_not_last_write_wins(
    tmp_path: Path,
) -> None:
    connection, _, subject, _, message, run = initialize(tmp_path)
    payload = context(connection, subject, run, message)
    active = ActiveFactEvidence(
        41,
        subject,
        "training_goal",
        "marathon",
        "long_term",
        NOW,
        None,
        3,
        message,
        True,
        None,
    )
    gate = MailFactGate()
    output = result(
        payload,
        intent="user_fact_update",
        fact_candidates=[fact_candidate(payload)],
    )
    replay = gate.evaluate(
        output, payload, evidence(payload, active_facts=(active,))
    )
    assert not replay.facts[0].persist
    assert replay.facts[0].replay_fact_id == 41

    conflict_db, _, conflict_subject, _, conflict_message, conflict_run = (
        initialize(
            tmp_path / "conflict",
            body="Going forward my training goal is ultramarathon.",
        )
    )
    conflict_payload = context(
        conflict_db, conflict_subject, conflict_run, conflict_message
    )
    conflict_active = replace(
        active,
        subject_id=conflict_subject,
        source_mail_message_id=conflict_message,
    )
    candidate = fact_candidate(conflict_payload, value="ultramarathon")
    with pytest.raises(MailFactGateError, match="conflict"):
        gate.evaluate(
            result(
                conflict_payload,
                intent="user_fact_update",
                fact_candidates=[candidate],
            ),
            conflict_payload,
            evidence(conflict_payload, active_facts=(conflict_active,)),
        )
    supersede_db, _, supersede_subject, _, supersede_message, supersede_run = (
        initialize(
            tmp_path / "supersede",
            body="Change my training goal to ultramarathon from now on.",
        )
    )
    supersede_payload = context(
        supersede_db, supersede_subject, supersede_run, supersede_message
    )
    supersede_active = replace(
        active,
        subject_id=supersede_subject,
        source_mail_message_id=supersede_message,
    )
    candidate = fact_candidate(supersede_payload, value="ultramarathon")
    superseded = gate.evaluate(
        result(
            supersede_payload,
            intent="user_fact_update",
            fact_candidates=[candidate],
        ),
        supersede_payload,
        evidence(supersede_payload, active_facts=(supersede_active,)),
    )
    assert superseded.facts[0].supersedes_fact_id == 41


@pytest.mark.parametrize(
    "mutator,code",
    [
        (
            lambda value: value.update(
                response={
                    "response_kind": "mail_response",
                    "subject_intent": "diagnosis",
                    "structured_content": {},
                    "user_visible_text": "You have arthritis.",
                    "requires_thread_reply": True,
                }
            ),
            "medical",
        ),
        (
            lambda value: value.update(
                response={
                    "response_kind": "mail_response",
                    "subject_intent": "provider",
                    "structured_content": {},
                    "user_visible_text": "Garmin says your VO2 max is 55.",
                    "requires_thread_reply": True,
                }
            ),
            "provider",
        ),
        (
            lambda value: value.update(
                response={
                    "response_kind": "mail_response",
                    "subject_intent": "plan",
                    "structured_content": {"recipient": "attacker@example.test"},
                    "user_visible_text": "Okay.",
                    "requires_thread_reply": True,
                }
            ),
            "privileged",
        ),
        (
            lambda value: value.update(
                response={
                    "response_kind": "mail_response",
                    "subject_intent": "plan",
                    "structured_content": {},
                    "user_visible_text": "I changed your plan.",
                    "requires_thread_reply": True,
                }
            ),
            "privileged",
        ),
    ],
)
def test_diagnosis_provider_invention_and_privileged_actions_are_rejected(
    tmp_path: Path, mutator, code: str
) -> None:
    connection, _, subject, _, message, run = initialize(tmp_path)
    payload = context(connection, subject, run, message)
    output = result(
        payload,
        intent="training_question",
        action="reply",
        response=reply(payload),
    )
    mutator(output)
    with pytest.raises(MailFactGateError, match=code):
        MailFactGate().evaluate(output, payload, evidence(payload))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":"1","schema_version":"1"}',
        b'{"x":NaN}',
        b"{}{}",
        b"\xef\xbb\xbf{}",
        ("{" + '"x":' + "[" * 20 + "0" + "]" * 20 + "}").encode(),
        b"x" * 262145,
    ],
)
def test_duplicate_nonfinite_multiple_deep_and_oversize_json_rejected(
    tmp_path: Path, raw: bytes
) -> None:
    connection, _, subject, _, message, run = initialize(tmp_path)
    payload = context(connection, subject, run, message)
    with pytest.raises(MailFactGateError, match="result_invalid"):
        MailFactGate().evaluate(raw, payload, evidence(payload))


def test_action_matrix_rejects_ack_reply_irrelevant_reply_and_operator_payload(
    tmp_path: Path,
) -> None:
    connection, _, subject, _, message, run = initialize(tmp_path)
    payload = context(connection, subject, run, message)
    gate = MailFactGate()
    cases = (
        result(
            payload,
            intent="acknowledgement",
            action="reply",
            response=reply(payload),
        ),
        result(
            payload,
            intent="non_trainlab_or_unsupported",
            action="reply",
            response=reply(payload),
        ),
        result(
            payload,
            intent="training_question",
            action="operator_review",
            fact_candidates=[fact_candidate(payload)],
        ),
    )
    for item in cases:
        with pytest.raises(MailFactGateError):
            gate.evaluate(item, payload, evidence(payload))


def test_plan_change_persists_only_reason_and_dependency_wait_idempotently(
    tmp_path: Path,
) -> None:
    body = "Please move 2026-07-25 training."
    connection, repo, subject, _, message, run = initialize(tmp_path, body=body)
    payload = context(connection, subject, run, message)
    output = plan_result(payload)
    before_plan = tuple(
        connection.execute(
            "SELECT id,status,analysis_artifact_id FROM training_plans ORDER BY id"
        )
    )
    first = repo.gate_mail_result(run, output, payload)
    assert first.status == "dependency_wait"
    assert first.reason_event_id is not None
    event = connection.execute(
        "SELECT * FROM conversation_events WHERE id=?",
        (first.reason_event_id,),
    ).fetchone()
    event_payload = json.loads(event["structured_payload_json"])
    assert (
        event["actor_role"],
        event["trust_level"],
        event["mail_message_id"],
        event["related_run_key"],
    ) == ("trainlab", "system_generated", message, payload["run"]["run_key"])
    assert event_payload["source_revision_id"] == payload["trigger_message"][
        "source_revision_id"
    ]
    assert connection.execute(
        "SELECT processing_state FROM mail_messages WHERE id=?", (message,)
    ).fetchone()[0] == "awaiting_analysis"
    item = connection.execute(
        "SELECT * FROM mail_agent_items "
        "WHERE logical_item_kind='plan_revision_dependency'"
    ).fetchone()
    assert (
        item["status"],
        item["dependency_analysis_artifact_id"],
        item["next_retry_at_utc"],
    ) == ("deferred", None, None)
    assert tuple(
        connection.execute(
            "SELECT id,status,analysis_artifact_id FROM training_plans ORDER BY id"
        )
    ) == before_plan
    before = connection.total_changes
    assert repo.gate_mail_result(run, output, payload) == first
    assert connection.total_changes == before
    assert repo.finish_run(run, "deferred").status == "deferred"


def _ready_dependency(
    payload: dict,
    subject: int,
    message: int,
    reason_id: int,
) -> AnalysisDependencyEvidence:
    plan = payload["current_training_plan"]
    artifact = next(
        item
        for item in payload["relevant_analysis_artifacts"]
        if item["id"] == plan["analysis_artifact_id"]
    )
    return AnalysisDependencyEvidence(
        artifact["id"],
        subject,
        "weekly_training_plan",
        plan["plan_start_local_date"],
        plan["plan_end_local_date"],
        True,
        artifact["generated_by_run_id"],
        "plan_revision",
        "succeeded",
        plan["plan_start_local_date"],
        plan["plan_end_local_date"],
        plan["id"],
        "active",
        plan["plan_start_local_date"],
        plan["plan_end_local_date"],
        reason_id,
        message,
        "trainlab",
        "system_generated",
    )


def test_dependency_ready_and_wait_failed_stale_cross_period_matrix(
    tmp_path: Path,
) -> None:
    body = "Please move 2026-07-25 training."
    connection, repo, subject, _, message, run = initialize(tmp_path, body=body)
    original = context(connection, subject, run, message)
    waiting = repo.gate_mail_result(run, plan_result(original), original)
    assert waiting.reason_event_id is not None
    connection.execute(
        "UPDATE analysis_artifacts SET is_current=0"
    )
    connection.execute(
        "UPDATE training_plans SET status='superseded'"
    )
    _, artifact_id, plan_id = _add_plan(
        connection,
        subject,
        suffix="revision",
        analysis_kind="plan_revision",
        analysis_status="succeeded",
        plan_status="active",
        is_current=1,
        reason_event_id=waiting.reason_event_id,
    )
    repo.set_message_processing_state(subject, message, "queued")
    payload = context(connection, subject, run, message)
    assert payload["current_training_plan"]["id"] == plan_id
    output = result(
        payload,
        intent="plan_change_request",
        action="reply",
        response=reply(payload, "The revised plan is ready."),
        source_usage=usage(
            payload, "trigger_message", "analysis_artifact", "current_plan"
        ),
    )
    ready = _ready_dependency(
        payload, subject, message, waiting.reason_event_id
    )
    gate = MailFactGate()
    accepted = gate.evaluate(
        output, payload, evidence(payload, dependency=ready)
    )
    assert accepted.status == "accepted"
    assert accepted.dependency_artifact_id == artifact_id

    variants = (
        None,
        replace(ready, is_current=False),
        replace(ready, subject_id=subject + 1),
        replace(ready, artifact_kind="weekly_summary"),
        replace(ready, analysis_status="rejected"),
        replace(ready, period_end_local_date="2026-08-01"),
        replace(ready, reason_mail_message_id=message + 1),
    )
    for dependency in variants:
        deferred = gate.evaluate(
            output, payload, evidence(payload, dependency=dependency)
        )
        assert deferred.status == "dependency_wait"
        assert deferred.action == "await_analysis"
        assert deferred.dependency_artifact_id is None


def test_repository_rechecks_cross_subject_and_transaction_failure_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = "Please move 2026-07-25 training."
    connection, repo, subject, _, message, run = initialize(tmp_path, body=body)
    payload = context(connection, subject, run, message)
    output = plan_result(payload)
    before = {
        table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("conversation_events", "mail_agent_items")
    }
    original = repo._create_or_recover_event

    def fail_after_insert(*args, **kwargs):
        original(*args, **kwargs)
        raise MailRepositoryError("injected_transaction_failure")

    monkeypatch.setattr(repo, "_create_or_recover_event", fail_after_insert)
    with pytest.raises(MailRepositoryError, match="injected"):
        repo.gate_mail_result(run, output, payload)
    assert {
        table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in before
    } == before
    assert connection.execute(
        "SELECT processing_state FROM mail_messages WHERE id=?", (message,)
    ).fetchone()[0] == "queued"

    payload["current_training_plan"]["subject_id"] = subject + 1
    with pytest.raises((MailFactGateError, MailRepositoryError)):
        repo.gate_mail_result(run, output, payload)
    assert connection.execute(
        "SELECT count(*) FROM conversation_events "
        "WHERE event_type='plan_revision_reason_recorded'"
    ).fetchone()[0] == 0
