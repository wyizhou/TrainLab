"""S5-07 bounded due evaluation, misfire handling and durable queue claiming.

This module intentionally does not construct a lower-layer request, run a
subprocess, or interpret a receipt.  It selects *one* stable workflow key for a
future executor.  All time comes from an injected UTC clock and every mutable
operation is a short repository transaction guarded by the S5-04 lease.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable, Literal, Protocol
from zoneinfo import ZoneInfo

from .recovery_planner import RecoveryContext, RecoveryDecision, plan_recovery
from .repository import OrchestrationRepository, OrchestrationRepositoryError, SchedulerJobRecord
from .scheduling_config import OrchestrationConfigSnapshot, UtcClock


HONG_KONG = ZoneInfo("Asia/Hong_Kong")
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SCHEDULE_KEYS = frozenset({"schedule_kind", "interval_seconds", "depends_on_job_key", "collection_strategy"})
_PRIORITY = {"recovery": 0, "morning": 1, "weekly": 2, "mail": 3, "health_check": 4}
_JOB_KIND = {"morning": "morning", "weekly": "weekly", "mail_poll": "mail", "health_check": "health_check"}


class SchedulerError(OrchestrationRepositoryError):
    """A malformed scheduler input is a controlled no-claim condition."""


class LeaseGate(Protocol):
    instance: str
    pid: int
    def heartbeat(self): ...


@dataclass(frozen=True, slots=True)
class DueItem:
    job_key: str
    workflow_key: str
    workflow_kind: Literal["morning", "weekly", "mail", "health_check", "recovery"]
    trigger_kind: Literal["scheduled", "recovery"]
    due_at_utc: datetime
    next_due_at_utc: datetime | None
    logical_local_date: str | None
    deadline_at_utc: datetime | None
    recovery: RecoveryDecision | None = None
    handoff: bool = False
    dispatch_reason: str = "due"

    @property
    def priority(self) -> int:
        return _PRIORITY[self.workflow_kind]

    @property
    def order_at_utc(self) -> datetime:
        # A real deadline must win over ordinary schedule time; recovery retry
        # and ordinary due time are both represented by due_at_utc.
        return self.deadline_at_utc or self.due_at_utc


@dataclass(frozen=True, slots=True)
class SchedulerIncident:
    incident_key: str
    category: str
    severity: Literal["warning", "error"]
    error_code: str
    next_action: str


@dataclass(frozen=True, slots=True)
class DueEvaluation:
    items: tuple[DueItem, ...]
    incidents: tuple[SchedulerIncident, ...]
    skipped: tuple[DueItem, ...] = ()


@dataclass(frozen=True, slots=True)
class SchedulerTick:
    status: Literal["claimed", "idle", "lease_lost", "invalid"]
    claim: DueItem | None
    incidents: tuple[SchedulerIncident, ...]


def _utc(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != UTC.utcoffset(None):
        raise SchedulerError("scheduler_time_invalid")
    return value.astimezone(UTC)


def _parse(value: str | None) -> datetime | None:
    if value is None:
        return None
    if type(value) is not str or not value.endswith("Z"):
        raise SchedulerError("scheduler_state_time_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise SchedulerError("scheduler_state_time_invalid") from exc
    return _utc(parsed)


def _text(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _local_date(value: datetime) -> str:
    return _utc(value).astimezone(HONG_KONG).date().isoformat()


def _morning_due(local_date: str) -> datetime:
    # date.fromisoformat would offer no useful extra flexibility here; the
    # exact value comes from an already validated Asia/Hong_Kong projection.
    return datetime.fromisoformat(local_date + "T09:00:00+08:00").astimezone(UTC)


def _next_calendar_due(kind: str, due: datetime) -> datetime:
    local = _utc(due).astimezone(HONG_KONG)
    delta = 7 if kind == "weekly" else 1
    return (local + timedelta(days=delta)).astimezone(UTC)


def _next_calendar_after(kind: str, due: datetime, now: datetime) -> datetime:
    result = _next_calendar_due(kind, due)
    # A static config could be stale for years.  This remains bounded by the
    # maximum useful calendar gap and never creates one catch-up per absence.
    for _ in range(4_000):
        if result > now:
            return result
        result = _next_calendar_due(kind, result)
    raise SchedulerError("scheduler_calendar_gap_unbounded")


def _workflow_key(kind: str, subject_id: int, host_id: str, due: datetime) -> str:
    local = _local_date(due)
    if kind == "morning":
        return f"morning:{subject_id}:{local}"
    if kind == "weekly":
        return f"weekly:{subject_id}:{local}"
    if kind == "mail":
        return f"mail-poll:{subject_id}:{_text(due).replace(':', '').replace('-', '')}"
    return f"health-check:{host_id}:{_text(due).replace(':', '').replace('-', '')}"


def _schedule(record: SchedulerJobRecord, snapshot: OrchestrationConfigSnapshot) -> dict[str, object]:
    if (record.timezone != "Asia/Hong_Kong" or record.job_key not in _JOB_KIND
            or record.workflow_kind != _JOB_KIND[record.job_key]):
        raise SchedulerError("scheduler_job_invalid")
    try:
        raw = json.loads(record.schedule_spec_json)
    except (TypeError, ValueError) as exc:
        raise SchedulerError("scheduler_job_invalid") from exc
    if type(raw) is not dict or set(raw) != _SCHEDULE_KEYS:
        raise SchedulerError("scheduler_job_invalid")
    if record.schedule_spec_json != json.dumps(raw, sort_keys=True, separators=(",", ":"), allow_nan=False):
        raise SchedulerError("scheduler_job_invalid")
    expected = {
        "morning": {"schedule_kind": "daily_at", "interval_seconds": None, "depends_on_job_key": None, "collection_strategy": "own_incremental"},
        "weekly": {"schedule_kind": "weekly_at", "interval_seconds": None, "depends_on_job_key": "morning", "collection_strategy": "reuse_morning_collection"},
        "mail_poll": {"schedule_kind": "interval", "interval_seconds": snapshot.mail_poll_interval_seconds, "depends_on_job_key": None, "collection_strategy": "none"},
        "health_check": {"schedule_kind": "interval", "interval_seconds": snapshot.health_check_interval_seconds, "depends_on_job_key": None, "collection_strategy": "none"},
    }[record.job_key]
    expected_misfire = "bounded" if record.job_key in {"morning", "weekly"} else "not_applicable"
    if raw != expected or record.misfire_policy != expected_misfire:
        raise SchedulerError("scheduler_job_invalid")
    return raw


def _validate_snapshot(snapshot: OrchestrationConfigSnapshot) -> None:
    if (type(snapshot) is not OrchestrationConfigSnapshot or snapshot.timezone != "Asia/Hong_Kong"
            or snapshot.morning_time != "09:00" or snapshot.weekly_day != "monday"
            or type(snapshot.config_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", snapshot.config_sha256) is None):
        raise SchedulerError("scheduler_configuration_invalid")
    for value in (snapshot.mail_poll_interval_seconds, snapshot.health_check_interval_seconds,
                  snapshot.workflow_deadline_seconds, snapshot.max_parallel_read_checks,
                  snapshot.lease_ttl_seconds, snapshot.heartbeat_interval_seconds,
                  snapshot.daily_misfire_window_hours, snapshot.weekly_misfire_window_hours):
        if type(value) is not int or value <= 0:
            raise SchedulerError("scheduler_configuration_invalid")
    if type(snapshot.operational_alerts_enabled) is not bool:
        raise SchedulerError("scheduler_configuration_invalid")


class DueEvaluator:
    """Pure, deterministic conversion of persisted job projections into due work."""

    def evaluate(
        self,
        snapshot: OrchestrationConfigSnapshot,
        jobs: tuple[SchedulerJobRecord, ...],
        *,
        now_utc: datetime,
        subject_id: int,
        host_id: str,
    ) -> DueEvaluation:
        now = _utc(now_utc)
        _validate_snapshot(snapshot)
        if (type(subject_id) is not int or subject_id <= 0 or type(host_id) is not str
                or _ID.fullmatch(host_id) is None):
            raise SchedulerError("scheduler_configuration_invalid")
        items: list[DueItem] = []
        incidents: list[SchedulerIncident] = []
        skipped: list[DueItem] = []
        seen: set[str] = set()
        for record in jobs:
            if record.job_key in seen:
                raise SchedulerError("scheduler_job_duplicate")
            seen.add(record.job_key)
            if not record.is_enabled:
                continue
            try:
                spec = _schedule(record, snapshot)
                due = _parse(record.next_due_at_utc)
                if due is None:
                    raise SchedulerError("scheduler_state_time_invalid")
                if record.config_sha256 != snapshot.config_sha256:
                    raise SchedulerError("scheduler_config_snapshot_mismatch")
            except SchedulerError as exc:
                incidents.append(SchedulerIncident(f"scheduler:{record.job_key}:invalid", "scheduler", "error", str(exc), "maintenance"))
                continue
            if due > now:
                continue
            kind = record.workflow_kind
            if kind in {"morning", "weekly"}:
                # The persisted due must be the fixed Hong Kong 09:00 projection. A
                # weekly job can only be Monday; this rejects accidental UTC or
                # DST/cron-style semantics before any claim.
                local = due.astimezone(HONG_KONG)
                valid = local.hour == 9 and local.minute == 0 and local.second == 0
                valid = valid and (kind != "weekly" or local.weekday() == 0)
                window = timedelta(hours=(snapshot.weekly_misfire_window_hours if kind == "weekly" else snapshot.daily_misfire_window_hours))
                if not valid:
                    incidents.append(SchedulerIncident(f"scheduler:{record.job_key}:invalid", "scheduler", "error", "scheduler_calendar_due_invalid", "maintenance"))
                    continue
                if now - due > window:
                    incidents.append(SchedulerIncident(f"scheduler:{record.job_key}:{_local_date(due)}:misfire", "scheduler", "warning", "scheduler_misfire_expired", "manual_review"))
                    skipped.append(DueItem(record.job_key, _workflow_key(kind, subject_id, host_id, due), kind, "recovery", due, _next_calendar_after(kind, due, now), _local_date(due), due + timedelta(seconds=snapshot.workflow_deadline_seconds)))
                    continue
                trigger: Literal["scheduled", "recovery"] = "scheduled" if now == due else "recovery"
                next_due = _next_calendar_due(kind, due)
                items.append(DueItem(record.job_key, _workflow_key(kind, subject_id, host_id, due), kind, trigger, due, next_due, _local_date(due), due + timedelta(seconds=snapshot.workflow_deadline_seconds)))
                continue
            interval = spec["interval_seconds"]
            expected_interval = snapshot.mail_poll_interval_seconds if kind == "mail" else snapshot.health_check_interval_seconds
            if type(interval) is not int or interval != expected_interval:
                incidents.append(SchedulerIncident(f"scheduler:{record.job_key}:invalid", "scheduler", "error", "scheduler_interval_invalid", "maintenance"))
                continue
            # Collapsed restart behavior: only one immediate operation, then a
            # fresh interval from now.  It deliberately never replays all missed
            # interval ticks.
            next_due = now + timedelta(seconds=expected_interval)
            items.append(DueItem(record.job_key, _workflow_key(kind, subject_id, host_id, due), kind, "scheduled" if now == due else "recovery", due, next_due, None, due + timedelta(seconds=snapshot.workflow_deadline_seconds)))
        return DueEvaluation(tuple(sorted(items, key=lambda item: (_text(item.order_at_utc), _text(item.due_at_utc), item.priority, item.workflow_key))), tuple(sorted(incidents, key=lambda item: item.incident_key)), tuple(sorted(skipped, key=lambda item: item.workflow_key)))


class DueQueueService:
    """Claim at most one selected due item per tick, under the exact S5-04 lease."""

    def __init__(self, repository: OrchestrationRepository, lease: LeaseGate, clock: UtcClock, *, subject_id: int, host_id: str) -> None:
        self._repository, self._lease, self._clock = repository, lease, clock
        self._subject_id, self._host_id = subject_id, host_id
        self._evaluator = DueEvaluator()
        self._stopped = False
        self._inflight_recovery: set[str] = set()
        self._recovery_offset = 0
        self._next_recovery_wake: datetime | None = None

    def stop(self) -> None:
        self._stopped = True

    def tick(self, snapshot: OrchestrationConfigSnapshot) -> SchedulerTick:
        if self._stopped:
            return SchedulerTick("idle", None, ())
        now = _utc(self._clock.now())
        try:
            lease_state = self._lease.heartbeat()
            if getattr(lease_state, "state", None) != "active" or getattr(lease_state, "owner_instance_id", None) != self._lease.instance:
                return SchedulerTick("lease_lost", None, ())
            evaluation = self._evaluator.evaluate(snapshot, self._repository.scheduler_jobs(), now_utc=now, subject_id=self._subject_id, host_id=self._host_id)
            recoveries = self._recoveries(now)
            pending = tuple(self._handoff_item(record, now) for record in self._repository.pending_scheduler_handoffs(owner_instance_id=self._lease.instance, owner_pid=self._lease.pid, now_utc=now))
        except (SchedulerError, OrchestrationRepositoryError) as exc:
            incident = SchedulerIncident("scheduler:global:invalid", "scheduler", "error", _safe_code(exc), "maintenance")
            try:
                self._persist_incidents((incident,), now)
            except Exception:
                pass
            return SchedulerTick("invalid", None, (incident,))
        try:
            self._persist_incidents(evaluation.incidents, now)
        except Exception:
            incident = SchedulerIncident("scheduler:incident_sink:unavailable", "scheduler", "error", "scheduler_incident_persistence_failed", "maintenance")
            return SchedulerTick("invalid", None, (*evaluation.incidents, incident))
        if any(incident.severity == "error" for incident in evaluation.incidents):
            return SchedulerTick("invalid", None, evaluation.incidents)
        # A successful lease heartbeat plus a valid scheduler evaluation is
        # positive evidence that a prior global clock/state anomaly has
        # recovered.  Close only that exact scheduler incident; misfires and
        # workflow/provider incidents retain their own evidence lifecycle.
        try:
            prior = self._repository.get_incident("scheduler:global:invalid")
            if prior is not None and prior.state in {"open", "acknowledged"}:
                self._repository.transition_incident(
                    "scheduler:global:invalid", "resolved", at_utc=now
                )
        except Exception:
            incident = SchedulerIncident("scheduler:incident_recovery_unavailable", "scheduler", "error", "scheduler_incident_recovery_failed", "maintenance")
            return SchedulerTick("invalid", None, (*evaluation.incidents, incident))
        for skipped in evaluation.skipped:
            # Consuming an expired calendar marker records that it was observed
            # and prevents a restart from generating the same incident forever.
            # It creates neither a workflow nor an invocation.
            try:
                consumed = self._repository.skip_scheduler_due(job_key=skipped.job_key, due_at_utc=skipped.due_at_utc, next_due_at_utc=skipped.next_due_at_utc or now + timedelta(seconds=1), now_utc=now, owner_instance_id=self._lease.instance, owner_pid=self._lease.pid)
            except Exception as exc:
                incident = SchedulerIncident("scheduler:misfire:consume_failed", "scheduler", "error", _safe_code(exc), "maintenance")
                return SchedulerTick("invalid", None, (*evaluation.incidents, incident))
            if not consumed:
                return SchedulerTick("lease_lost", None, evaluation.incidents)
        candidates = tuple(sorted((*recoveries, *pending, *evaluation.items), key=lambda item: (_text(item.order_at_utc), _text(item.due_at_utc), item.priority, item.workflow_key)))
        for item in candidates:
            if item.workflow_kind == "recovery":
                if item.workflow_key in self._inflight_recovery:
                    continue
                self._inflight_recovery.add(item.workflow_key)
                return SchedulerTick("claimed", item, evaluation.incidents)
            if item.handoff:
                reclaimed = self._repository.claim_pending_scheduler_handoff(workflow_key=item.workflow_key, owner_instance_id=self._lease.instance, owner_pid=self._lease.pid, now_utc=now)
                if reclaimed is not None:
                    return SchedulerTick("claimed", item, evaluation.incidents)
                continue
            # A durable workflow key is the final idempotency boundary.  The
            # scheduler never invokes the executor, so an existing workflow is
            # simply a no-op claim rather than a duplicate business operation.
            try:
                existing = self._repository.get_workflow(item.workflow_key)
            except Exception as exc:
                return self._controlled_invalid(now, evaluation.incidents, "scheduler_existing_workflow_invalid", exc)
            if existing is not None:
                if not self._existing_identity_matches(existing, item):
                    return self._controlled_invalid(now, evaluation.incidents, "scheduler_existing_workflow_identity_conflict", SchedulerError("scheduler_existing_workflow_identity_conflict"))
                try:
                    self._consume_existing(item, now)
                except Exception as exc:
                    return self._controlled_invalid(now, evaluation.incidents, "scheduler_existing_workflow_consume_failed", exc)
                continue
            try:
                claimed = self._repository.claim_scheduler_due(job_key=item.job_key, due_at_utc=item.due_at_utc, next_due_at_utc=item.next_due_at_utc or now + timedelta(seconds=1), now_utc=now, owner_instance_id=self._lease.instance, owner_pid=self._lease.pid, workflow_key=item.workflow_key, workflow_kind=item.workflow_kind, trigger_kind=item.trigger_kind, subject_id=None if item.workflow_kind == "health_check" else self._subject_id, logical_local_date=item.logical_local_date, deadline_at_utc=item.deadline_at_utc)
            except Exception as exc:
                incident = SchedulerIncident("scheduler:claim:invalid", "scheduler", "error", _safe_code(exc), "maintenance")
                try:
                    self._persist_incidents((incident,), now)
                except Exception:
                    pass
                return SchedulerTick("invalid", None, (*evaluation.incidents, incident))
            if claimed:
                return SchedulerTick("claimed", item, evaluation.incidents)
            return SchedulerTick("lease_lost", None, evaluation.incidents)
        return SchedulerTick("idle", None, evaluation.incidents)

    @staticmethod
    def _handoff_item(record, now: datetime) -> DueItem:
        kind = record.workflow.workflow_kind
        if kind not in {"morning", "weekly", "mail", "health_check"}:
            raise SchedulerError("scheduler_handoff_invalid")
        trigger = record.workflow.trigger_kind
        if trigger not in {"scheduled", "recovery"}:
            raise SchedulerError("scheduler_handoff_invalid")
        return DueItem(record.job_key, record.workflow.workflow_key, kind, trigger, _parse(record.due_at_utc) or now, _parse(record.next_due_at_utc), record.workflow.logical_local_date, _parse(record.workflow.deadline_at_utc), None, True, "handoff_recovery")

    def complete_recovery_claim(self, workflow_key: str) -> None:
        """Release only an in-process dispatch guard after its executor returns.

        Durable retry/invocation identity remains wholly in S5-05's workflow
        aggregate.  Releasing this guard cannot manufacture a second workflow.
        """
        if type(workflow_key) is not str or _ID.fullmatch(workflow_key) is None:
            raise SchedulerError("scheduler_workflow_key_invalid")
        self._inflight_recovery.discard(workflow_key)

    def _recoveries(self, now: datetime) -> tuple[DueItem, ...]:
        results: list[DueItem] = []
        page = self._repository.active_workflow_definitions(200, self._recovery_offset)
        self._recovery_offset = 0 if len(page) < 200 else self._recovery_offset + len(page)
        next_wakes: list[datetime] = []
        for aggregate in page:
            self._validate_recovery_subject(aggregate)
            decision = plan_recovery(aggregate, RecoveryContext(now))
            if decision.action == "wait_retry" and decision.next_retry_at_utc is not None:
                next_wakes.append(decision.next_retry_at_utc)
            if decision.action in {"wait_retry", "wait_parent", "no_action", "attention_required", "complete_workflow"}:
                continue
            if decision.action not in {"start_workflow", "resume_workflow", "resume_step", "reconcile_status", "reconcile_analysis_delivery", "reconcile_mail_delivery"}:
                raise SchedulerError("scheduler_recovery_decision_invalid")
            retry = decision.next_retry_at_utc
            # A non-retry recovery (especially running unknown) is immediately
            # due, but carries the same durable workflow/invocation identity.
            due = now if retry is None else retry
            results.append(DueItem("recovery", decision.workflow_key, "recovery", "recovery", due, None, aggregate.workflow.logical_local_date, aggregate.workflow.deadline_at_utc, decision))
        self._next_recovery_wake = min(next_wakes) if next_wakes else None
        return tuple(results)

    def _validate_recovery_subject(self, aggregate) -> None:
        workflow = aggregate.workflow
        if workflow.workflow_kind == "health_check":
            valid = workflow.subject_id is None and workflow.workflow_key.startswith(f"health-check:{self._host_id}:")
        else:
            valid = workflow.subject_id == self._subject_id
            if workflow.workflow_kind == "morning":
                valid = valid and workflow.workflow_key.startswith(f"morning:{self._subject_id}:")
            elif workflow.workflow_kind == "weekly":
                valid = valid and workflow.workflow_key.startswith(f"weekly:{self._subject_id}:")
            elif workflow.workflow_kind == "mail":
                valid = valid and workflow.workflow_key.startswith(f"mail-poll:{self._subject_id}:")
            else:
                valid = False
        if not valid:
            raise SchedulerError("scheduler_recovery_subject_mismatch")

    def _existing_identity_matches(self, run, item: DueItem) -> bool:
        expected_subject = None if item.workflow_kind == "health_check" else self._subject_id
        return (run.workflow_key == item.workflow_key and run.workflow_kind == item.workflow_kind
                and run.subject_id == expected_subject and run.logical_local_date == item.logical_local_date
                and run.trigger_kind == item.trigger_kind
                and run.deadline_at_utc == (None if item.deadline_at_utc is None else _text(item.deadline_at_utc)))

    def _controlled_invalid(self, now: datetime, prior: tuple[SchedulerIncident, ...], code: str, exc: Exception) -> SchedulerTick:
        incident = SchedulerIncident(f"scheduler:{code}", "scheduler", "error", code if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) else _safe_code(exc), "maintenance")
        try:
            self._persist_incidents((incident,), now)
        except Exception:
            incident = SchedulerIncident("scheduler:incident_sink:unavailable", "scheduler", "error", "scheduler_incident_persistence_failed", "maintenance")
        return SchedulerTick("invalid", None, (*prior, incident))

    def run(self, snapshot: OrchestrationConfigSnapshot, wait: Callable[[float], None], *, max_ticks: int | None = None) -> tuple[SchedulerTick, ...]:
        """Cooperative test seam; no timer/thread is created and it is stoppable."""
        if max_ticks is not None and (type(max_ticks) is not int or max_ticks < 0):
            raise SchedulerError("scheduler_loop_bound_invalid")
        results: list[SchedulerTick] = []
        while not self._stopped and (max_ticks is None or len(results) < max_ticks):
            result = self.tick(snapshot); results.append(result)
            if (self._stopped or result.status in {"lease_lost", "invalid"}
                    or (max_ticks is not None and len(results) >= max_ticks)):
                break
            wait(self._wait_seconds(snapshot))
        return tuple(results)

    def _wait_seconds(self, snapshot: OrchestrationConfigSnapshot) -> float:
        _validate_snapshot(snapshot)
        now = _utc(self._clock.now())
        candidates = [float(snapshot.heartbeat_interval_seconds)]
        for job in self._repository.scheduler_jobs():
            due = _parse(job.next_due_at_utc)
            if due is not None and due > now:
                candidates.append((due - now).total_seconds())
        if self._next_recovery_wake is not None and self._next_recovery_wake > now:
            candidates.append((self._next_recovery_wake - now).total_seconds())
        return max(0.001, min(candidates))

    def _consume_existing(self, item: DueItem, now: datetime) -> None:
        # Race/restart no-op: consume the due marker only while our lease still
        # owns it. A later executor resumes the already durable workflow key.
        self._repository.claim_scheduler_due(job_key=item.job_key, due_at_utc=item.due_at_utc, next_due_at_utc=item.next_due_at_utc or now + timedelta(seconds=1), now_utc=now, owner_instance_id=self._lease.instance, owner_pid=self._lease.pid, workflow_key=item.workflow_key, workflow_kind=item.workflow_kind, trigger_kind=item.trigger_kind, subject_id=None if item.workflow_kind == "health_check" else self._subject_id, logical_local_date=item.logical_local_date, deadline_at_utc=item.deadline_at_utc)

    def _persist_incidents(self, incidents: tuple[SchedulerIncident, ...], now: datetime) -> None:
        for incident in incidents[:16]:
            self._repository.record_incident(incident_key=incident.incident_key, category=incident.category, severity=incident.severity, seen_at_utc=now, error_code=incident.error_code, error_summary=incident.error_code, next_action=incident.next_action)


def _safe_code(exc: Exception) -> str:
    value = str(exc)
    return value if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value) else "scheduler_state_invalid"
