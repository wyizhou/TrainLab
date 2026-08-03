from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.orchestration import (
    ControlledClock,
    DueEvaluator,
    DueQueueService,
    OrchestrationConfigSnapshot,
    OrchestrationRepository,
    SchedulerJobProjection,
    StepTransitionEvent,
    WorkflowTransitionEvent,
)
from trainlab.orchestration.state_projection import StepDefinition, WorkflowDefinition
from trainlab.orchestration.repository import WorkflowRunRecord, WorkflowStepRecord
from trainlab.orchestration.workflow_definition_store import WorkflowDefinitionAggregate


NOW = datetime(2026, 7, 24, 0, 0, tzinfo=UTC)  # Friday 08:00 Hong Kong
HASH = "a" * 64


@dataclass
class Lease:
    instance: str = "test-supervisor"
    pid: int = 1234
    active: bool = True

    def heartbeat(self):
        return type("LeaseState", (), {"state": "active" if self.active else "passive", "owner_instance_id": self.instance if self.active else None})()


def snapshot(tmp_path: Path) -> OrchestrationConfigSnapshot:
    return OrchestrationConfigSnapshot("Asia/Hong_Kong", "09:00", "monday", 300, 600, 3600, 1, 90, 30, 12, 24, tmp_path / "lock", tmp_path / "tmp", tmp_path / "logs", False, "a" * 64)


def repo(tmp_path: Path, now: datetime = NOW) -> tuple[OrchestrationRepository, Lease]:
    root = tmp_path / "foundation"
    tool = FoundationTool(FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state/foundation-ready.json", root / "state/locks/foundation.lock"))
    assert tool.execute(FoundationRequest("init", "s5-07", "2026-07-23T00:00:00Z")).status == "initialized"
    result = OrchestrationRepository(root / "data.db")
    lease = Lease()
    with result._transaction() as conn:
        conn.execute("INSERT INTO data_subjects(id,subject_key,timezone,is_active,created_at_utc) VALUES (7,'test-subject','Asia/Hong_Kong',1,?)", (now.isoformat().replace("+00:00", "Z"),))
        conn.execute("INSERT INTO scheduler_leases (lease_key,owner_instance_id,owner_pid,acquired_at_utc,heartbeat_at_utc,expires_at_utc) VALUES (?,?,?,?,?,?)", ("supervisor", lease.instance, lease.pid, now.isoformat().replace("+00:00", "Z"), now.isoformat().replace("+00:00", "Z"), (now + timedelta(hours=2)).isoformat().replace("+00:00", "Z")))
    return result, lease


def jobs(result: OrchestrationRepository, config: OrchestrationConfigSnapshot, now: datetime, *, morning: datetime | None = None, weekly: datetime | None = None, mail: datetime | None = None, health: datetime | None = None) -> None:
    values = (("morning", "morning", "daily_at", morning, "2026-07-24", None, None, "own_incremental", timedelta(hours=12)), ("weekly", "weekly", "weekly_at", weekly, "2026-07-27", None, "morning", "reuse_morning_collection", timedelta(hours=24)), ("mail_poll", "mail", "interval", mail, None, config.mail_poll_interval_seconds, None, "none", None), ("health_check", "health_check", "interval", health, None, config.health_check_interval_seconds, None, "none", None))
    for key, kind, schedule, due, logical, interval, dep, strategy, window in values:
        if due is not None:
            result.upsert_scheduler_job(SchedulerJobProjection(key, kind, "Asia/Hong_Kong", schedule, due, logical, interval, dep, strategy, window, config.config_sha256), is_enabled=True, updated_at_utc=now)


def test_exact_0900_claim_is_stable_and_second_tick_is_noop(tmp_path: Path) -> None:
    now = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)  # 09:00 Hong Kong
    result, lease = repo(tmp_path, now); config = snapshot(tmp_path)
    jobs(result, config, now, morning=now)
    queue = DueQueueService(result, lease, ControlledClock(now), subject_id=7, host_id="host")
    first = queue.tick(config)
    assert first.status == "claimed" and first.claim and first.claim.workflow_key == "morning:7:2026-07-24"
    assert queue.tick(config).status == "idle"
    saved = result.get_scheduler_job("morning")
    assert saved and saved.last_due_at_utc == "2026-07-24T01:00:00Z"


def test_monday_weekly_and_morning_have_fixed_order_and_hong_kong_dates(tmp_path: Path) -> None:
    now = datetime(2026, 7, 27, 1, 0, tzinfo=UTC)  # Monday 09:00 Hong Kong
    result, _ = repo(tmp_path, now); config = snapshot(tmp_path)
    jobs(result, config, now, morning=now, weekly=now)
    value = DueEvaluator().evaluate(config, result.scheduler_jobs(), now_utc=now, subject_id=7, host_id="host")
    assert [(item.workflow_kind, item.logical_local_date) for item in value.items] == [("morning", "2026-07-27"), ("weekly", "2026-07-27")]


@pytest.mark.parametrize("hours, expected", [(5, "claimed"), (13, "idle")])
def test_daily_misfire_is_bounded_and_expiry_has_incident(tmp_path: Path, hours: int, expected: str) -> None:
    due = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)
    now = due + timedelta(hours=hours)
    result, lease = repo(tmp_path, now); config = snapshot(tmp_path)
    jobs(result, config, now, morning=due)
    tick = DueQueueService(result, lease, ControlledClock(now), subject_id=7, host_id="host").tick(config)
    assert tick.status == expected
    if hours == 13:
        assert tick.incidents and tick.incidents[0].error_code == "scheduler_misfire_expired"
        assert DueQueueService(result, lease, ControlledClock(now), subject_id=7, host_id="host").tick(config).incidents == ()


def test_mail_and_health_collapse_missed_intervals_once(tmp_path: Path) -> None:
    now = NOW; due = now - timedelta(hours=3)
    result, lease = repo(tmp_path, now); config = snapshot(tmp_path)
    jobs(result, config, now, mail=due, health=due)
    queue = DueQueueService(result, lease, ControlledClock(now), subject_id=7, host_id="host")
    assert queue.tick(config).claim.workflow_kind == "mail"
    assert queue.tick(config).claim.workflow_kind == "health_check"
    assert queue.tick(config).status == "idle"


def test_lease_loss_claims_nothing_and_stop_has_no_background_loop(tmp_path: Path) -> None:
    result, lease = repo(tmp_path, NOW); config = snapshot(tmp_path)
    jobs(result, config, NOW, morning=NOW)
    lease.active = False
    queue = DueQueueService(result, lease, ControlledClock(NOW), subject_id=7, host_id="host")
    assert queue.tick(config).status == "lease_lost"
    queue.stop()
    assert queue.run(config, lambda _: pytest.fail("must_not_wait"), max_ticks=3) == ()


def test_invalid_config_or_state_never_claims(tmp_path: Path) -> None:
    result, lease = repo(tmp_path, NOW); config = snapshot(tmp_path)
    jobs(result, config, NOW, morning=NOW)
    bad = replace(config, timezone="UTC")
    tick = DueQueueService(result, lease, ControlledClock(NOW), subject_id=7, host_id="host").tick(bad)
    assert tick.status == "invalid" and result.get_scheduler_job("morning").last_due_at_utc is None


def test_running_workflow_is_reconcile_first_and_never_creates_another_key(tmp_path: Path) -> None:
    result, lease = repo(tmp_path, NOW); config = snapshot(tmp_path)
    jobs(result, config, NOW, mail=NOW - timedelta(minutes=5))
    workflow = WorkflowDefinition("morning:7:2026-07-24", "morning", 7, "2026-07-24", "scheduled", NOW - timedelta(seconds=1), None, NOW - timedelta(minutes=1), "b" * 64, "c" * 64, "queued")
    step = StepDefinition("collect", 0, 2, "incremental", "d" * 64, "stable-invocation", None, "pending")
    result.create_workflow_definition(workflow, (step,))
    result.transition_workflow_domain(workflow.workflow_key, WorkflowTransitionEvent("wf-start", "running", NOW, "scheduler_start"))
    result.transition_step_domain(workflow.workflow_key, StepTransitionEvent("step-start", "collect", "running", NOW, evidence_code=None))
    queue = DueQueueService(result, lease, ControlledClock(NOW), subject_id=7, host_id="host")
    tick = queue.tick(config)
    assert tick.status == "claimed" and tick.claim and tick.claim.workflow_kind == "recovery"
    assert tick.claim.recovery and tick.claim.recovery.action == "reconcile_status"
    assert tick.claim.recovery.invocation_id == "stable-invocation"
    assert result.get_workflow(workflow.workflow_key) is not None
    assert queue.tick(config).claim.workflow_kind == "mail"


def test_claim_survives_crash_and_new_lease_reclaims_same_handoff(tmp_path: Path) -> None:
    now = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)
    result, lease = repo(tmp_path, now); config = snapshot(tmp_path)
    jobs(result, config, now, morning=now)
    first = DueQueueService(result, lease, ControlledClock(now), subject_id=7, host_id="host").tick(config)
    assert first.claim and result.get_workflow(first.claim.workflow_key) is not None
    successor = Lease("successor", 5678)
    with result._transaction() as conn:
        conn.execute("UPDATE scheduler_leases SET owner_instance_id=?,owner_pid=?,acquired_at_utc=?,heartbeat_at_utc=?,expires_at_utc=? WHERE lease_key='supervisor'", (successor.instance, successor.pid, (now + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"), (now + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"), (now + timedelta(hours=2)).isoformat().replace("+00:00", "Z")))
    clock = ControlledClock(now + timedelta(seconds=1))
    recovered = DueQueueService(result, successor, clock, subject_id=7, host_id="host").tick(config)
    assert recovered.status == "claimed" and recovered.claim
    assert recovered.claim.workflow_key == first.claim.workflow_key
    assert recovered.claim.trigger_kind == "scheduled"
    assert recovered.claim.dispatch_reason == "handoff_recovery"


def test_two_evaluators_same_lease_only_one_durable_handoff(tmp_path: Path) -> None:
    now = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)
    result, lease = repo(tmp_path, now); config = snapshot(tmp_path)
    jobs(result, config, now, morning=now)
    one = DueQueueService(result, lease, ControlledClock(now), subject_id=7, host_id="host")
    two = DueQueueService(result, lease, ControlledClock(now), subject_id=7, host_id="host")
    assert one.tick(config).status == "claimed"
    assert two.tick(config).status == "idle"
    with result._transaction() as conn:
        assert conn.execute("SELECT count(*) FROM orchestrator_runs WHERE workflow_key='morning:7:2026-07-24'").fetchone()[0] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE scheduler_jobs SET workflow_kind='weekly' WHERE job_key='morning'",
        "UPDATE scheduler_jobs SET schedule_spec_json='{}' WHERE job_key='morning'",
        "UPDATE scheduler_jobs SET misfire_policy='not_applicable' WHERE job_key='morning'",
    ],
)
def test_static_job_mapping_tamper_is_incident_and_no_claim(tmp_path: Path, mutation: str) -> None:
    now = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)
    result, lease = repo(tmp_path, now); config = snapshot(tmp_path)
    jobs(result, config, now, morning=now)
    with result._transaction() as conn:
        conn.execute(mutation)
    tick = DueQueueService(result, lease, ControlledClock(now), subject_id=7, host_id="host").tick(config)
    assert tick.status == "invalid" and tick.incidents and result.get_scheduler_job("morning").last_due_at_utc is None


def test_incident_sink_failure_prevents_other_due_claims(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)
    result, lease = repo(tmp_path, now); config = snapshot(tmp_path)
    jobs(result, config, now, morning=now, mail=now)
    with result._transaction() as conn:
        conn.execute("UPDATE scheduler_jobs SET workflow_kind='weekly' WHERE job_key='morning'")
    def fail(**_: object):
        raise Exception("sink unavailable")
    monkeypatch.setattr(result, "record_incident", fail)
    tick = DueQueueService(result, lease, ControlledClock(now), subject_id=7, host_id="host").tick(config)
    assert tick.status == "invalid"
    assert result.get_scheduler_job("mail_poll").last_due_at_utc is None


def test_loop_wait_is_positive_and_callback_can_stop(tmp_path: Path) -> None:
    result, lease = repo(tmp_path, NOW); config = snapshot(tmp_path)
    jobs(result, config, NOW, mail=NOW + timedelta(seconds=10))
    queue = DueQueueService(result, lease, ControlledClock(NOW), subject_id=7, host_id="host")
    waits: list[float] = []
    def wait(value: float) -> None:
        waits.append(value); queue.stop()
    assert len(queue.run(config, wait, max_ticks=3)) == 1
    assert waits and 0 < waits[0] <= 10


@pytest.mark.parametrize(("kind", "hours"), [("morning", 12), ("weekly", 24)])
def test_misfire_window_exact_boundary_is_inclusive(tmp_path: Path, kind: str, hours: int) -> None:
    due = datetime(2026, 7, 27, 1, 0, tzinfo=UTC) if kind == "weekly" else datetime(2026, 7, 24, 1, 0, tzinfo=UTC)
    now = due + timedelta(hours=hours)
    result, _ = repo(tmp_path, now); config = snapshot(tmp_path)
    jobs(result, config, now, **{kind: due})
    evaluated = DueEvaluator().evaluate(config, result.scheduler_jobs(), now_utc=now, subject_id=7, host_id="host")
    assert len(evaluated.items) == 1 and not evaluated.incidents


def test_deferred_retry_waits_then_reuses_original_workflow_step_and_invocation(tmp_path: Path) -> None:
    result, lease = repo(tmp_path, NOW); config = snapshot(tmp_path)
    started = NOW - timedelta(minutes=2); retry = NOW + timedelta(minutes=5)
    workflow = WorkflowDefinition("morning:7:deferred", "morning", 7, "2026-07-24", "recovery", NOW + timedelta(hours=1), None, started, "a" * 64, "b" * 64, "queued")
    step = StepDefinition("collect", 0, 2, "incremental", "c" * 64, "original-invocation", None, "pending")
    result.create_workflow_definition(workflow, (step,))
    result.transition_workflow_domain(workflow.workflow_key, WorkflowTransitionEvent("wf-running", "running", started + timedelta(seconds=1), "scheduler_start"))
    result.transition_step_domain(workflow.workflow_key, StepTransitionEvent("step-running", "collect", "running", started + timedelta(seconds=2)))
    result.transition_step_domain(workflow.workflow_key, StepTransitionEvent("step-deferred", "collect", "deferred", started + timedelta(seconds=3), receipt_sha256="d" * 64, next_retry_at_utc=retry))
    result.transition_workflow_domain(workflow.workflow_key, WorkflowTransitionEvent("wf-deferred", "deferred", started + timedelta(seconds=4), "retry_scheduled"))
    clock = ControlledClock(NOW)
    queue = DueQueueService(result, lease, clock, subject_id=7, host_id="host")
    assert queue.tick(config).status == "idle"
    persisted = result.load_workflow_definition(workflow.workflow_key)
    assert persisted and persisted.step_records[0].next_retry_at_utc == retry.isoformat().replace("+00:00", "Z")
    clock.set(retry)
    due = queue.tick(config)
    assert due.claim and due.claim.recovery
    assert due.claim.recovery.action == "resume_workflow"
    assert due.claim.recovery.workflow_key == workflow.workflow_key
    assert due.claim.recovery.step_key == "collect" and due.claim.recovery.invocation_id == "original-invocation"


def test_handoff_materialization_is_exact_one_way_ack(tmp_path: Path) -> None:
    now = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)
    result, lease = repo(tmp_path, now); config = snapshot(tmp_path)
    jobs(result, config, now, morning=now)
    item = DueQueueService(result, lease, ControlledClock(now), subject_id=7, host_id="host").tick(config).claim
    assert item is not None
    run = result.get_workflow(item.workflow_key); assert run is not None
    binding = result.get_scheduler_handoff(item.workflow_key); assert binding is not None
    workflow = WorkflowDefinition(run.workflow_key, run.workflow_kind, run.subject_id, run.logical_local_date, run.trigger_kind, datetime.fromisoformat(run.deadline_at_utc.replace("Z", "+00:00")), None, datetime.fromisoformat(run.started_at_utc.replace("Z", "+00:00")), binding.materialization_command_sha256, binding.materialization_evidence_sha256, "queued")
    step = StepDefinition("collect", 0, 2, "incremental", "1" * 64, "stable-invocation", None, "pending")
    materialized = result.create_workflow_definition(workflow, (step,))
    assert materialized.workflow.workflow_key == item.workflow_key
    assert result.create_workflow_definition(workflow, (step,)).definition_sha256 == materialized.definition_sha256


def test_recovery_pagination_cannot_starve_due_item_behind_future_page(tmp_path: Path) -> None:
    def aggregate(index: int, retry: datetime) -> WorkflowDefinitionAggregate:
        key = f"morning:7:page-{index}"
        workflow = WorkflowDefinition(key, "morning", 7, "2026-07-24", "recovery", NOW + timedelta(days=1), None, NOW - timedelta(minutes=1), "a" * 64, "b" * 64, "deferred")
        step = StepDefinition("collect", 0, 2, "incremental", "c" * 64, f"invocation-{index}", None, "deferred")
        run = WorkflowRunRecord(index + 1, key, "morning", 7, "2026-07-24", "recovery", "deferred", (NOW + timedelta(days=1)).isoformat().replace("+00:00", "Z"), None, (NOW - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"), NOW.isoformat().replace("+00:00", "Z"), "{}")
        record = WorkflowStepRecord(index + 1, index + 1, "collect", 0, 2, "incremental", "c" * 64, f"invocation-{index}", None, "d" * 64, "deferred", 1, retry.isoformat().replace("+00:00", "Z"), NOW.isoformat().replace("+00:00", "Z"), None)
        return WorkflowDefinitionAggregate(run, (record,), workflow, (step,), "e" * 64, "{}", "{}")
    values = tuple(aggregate(i, NOW + timedelta(hours=1)) for i in range(200)) + (aggregate(200, NOW),)
    class PagedRepository:
        def active_workflow_definitions(self, limit: int, offset: int):
            return values[offset:offset + limit]
    queue = DueQueueService(PagedRepository(), Lease(), ControlledClock(NOW), subject_id=7, host_id="host")  # type: ignore[arg-type]
    assert queue._recoveries(NOW) == ()
    second = queue._recoveries(NOW)
    assert len(second) == 1 and second[0].recovery and second[0].recovery.invocation_id == "invocation-200"


def test_invalid_heartbeat_snapshot_run_is_controlled_and_never_waits(tmp_path: Path) -> None:
    result, lease = repo(tmp_path, NOW); config = replace(snapshot(tmp_path), heartbeat_interval_seconds="bad")  # type: ignore[arg-type]
    waits: list[float] = []
    values = DueQueueService(result, lease, ControlledClock(NOW), subject_id=7, host_id="host").run(config, waits.append, max_ticks=1)
    assert len(values) == 1 and values[0].status == "invalid" and waits == []


def test_mixed_invalid_and_valid_due_is_fail_closed(tmp_path: Path) -> None:
    now = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)
    result, lease = repo(tmp_path, now); config = snapshot(tmp_path)
    jobs(result, config, now, morning=now, mail=now)
    with result._transaction() as conn:
        conn.execute("UPDATE scheduler_jobs SET workflow_kind='weekly' WHERE job_key='morning'")
    tick = DueQueueService(result, lease, ControlledClock(now), subject_id=7, host_id="host").tick(config)
    assert tick.status == "invalid" and tick.claim is None
    assert result.get_scheduler_job("mail_poll").last_due_at_utc is None
    assert result.get_incident("scheduler:morning:invalid") is not None


def test_completed_wrong_subject_existing_key_cannot_consume_due(tmp_path: Path) -> None:
    now = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)
    result, lease = repo(tmp_path, now); config = snapshot(tmp_path)
    jobs(result, config, now, morning=now)
    result.create_workflow(workflow_key="morning:7:2026-07-24", workflow_kind="morning", trigger_kind="scheduled", started_at_utc=now, logical_local_date="2026-07-24", subject_id=None, deadline_at_utc=now + timedelta(hours=1))
    result.transition_workflow("morning:7:2026-07-24", "succeeded", at_utc=now)
    tick = DueQueueService(result, lease, ControlledClock(now), subject_id=7, host_id="host").tick(config)
    assert tick.status == "invalid" and result.get_scheduler_job("morning").last_due_at_utc is None


def test_active_wrong_subject_recovery_is_controlled(tmp_path: Path) -> None:
    result, lease = repo(tmp_path, NOW); config = snapshot(tmp_path)
    workflow = WorkflowDefinition("morning:7:wrong-subject", "morning", None, "2026-07-24", "scheduled", NOW + timedelta(hours=1), None, NOW - timedelta(minutes=1), "a" * 64, "b" * 64, "queued")
    step = StepDefinition("collect", 0, 2, "incremental", "c" * 64, "stable", None, "pending")
    result.create_workflow_definition(workflow, (step,))
    tick = DueQueueService(result, lease, ControlledClock(NOW), subject_id=7, host_id="host").tick(config)
    assert tick.status == "invalid" and tick.claim is None


def test_handoff_binding_tamper_rejected_and_lineage_survives_state_change(tmp_path: Path) -> None:
    now = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)
    result, lease = repo(tmp_path, now); config = snapshot(tmp_path)
    jobs(result, config, now, morning=now)
    item = DueQueueService(result, lease, ControlledClock(now), subject_id=7, host_id="host").tick(config).claim; assert item
    run = result.get_workflow(item.workflow_key); binding = result.get_scheduler_handoff(item.workflow_key)
    assert run and binding
    wrong = WorkflowDefinition(run.workflow_key, run.workflow_kind, run.subject_id, run.logical_local_date, run.trigger_kind, datetime.fromisoformat(run.deadline_at_utc.replace("Z", "+00:00")), None, datetime.fromisoformat(run.started_at_utc.replace("Z", "+00:00")), "0" * 64, binding.materialization_evidence_sha256, "queued")
    step = StepDefinition("collect", 0, 2, "incremental", "1" * 64, "stable", None, "pending")
    with pytest.raises(Exception, match="scheduler_handoff_materialization_conflict"):
        result.create_workflow_definition(wrong, (step,))
    assert result.get_scheduler_handoff(item.workflow_key) == binding
    correct = replace(wrong, create_command_sha256=binding.materialization_command_sha256)
    materialized = result.create_workflow_definition(correct, (step,))
    assert materialized.scheduler_handoff_lineage_json is not None
    result.transition_workflow_domain(item.workflow_key, WorkflowTransitionEvent("start-bound", "running", now, "scheduler_start"))
    reloaded = result.load_workflow_definition(item.workflow_key)
    assert reloaded and reloaded.scheduler_handoff_lineage_json == materialized.scheduler_handoff_lineage_json


def test_corrupt_existing_workflow_is_controlled_and_does_not_advance(tmp_path: Path) -> None:
    now = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)
    result, lease = repo(tmp_path, now); config = snapshot(tmp_path)
    jobs(result, config, now, morning=now)
    result.create_workflow(workflow_key="morning:7:2026-07-24", workflow_kind="morning", trigger_kind="scheduled", started_at_utc=now, logical_local_date="2026-07-24", subject_id=7, deadline_at_utc=now + timedelta(hours=1))
    with result._transaction() as conn:
        conn.execute("UPDATE orchestrator_runs SET result_summary_json='{\"bad\":1}' WHERE workflow_key='morning:7:2026-07-24'")
    tick = DueQueueService(result, lease, ControlledClock(now), subject_id=7, host_id="host").tick(config)
    assert tick.status == "invalid" and result.get_scheduler_job("morning").last_due_at_utc is None
