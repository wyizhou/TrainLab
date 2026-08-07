"""Fail-closed persistence for Layer 5 runtime and operational audit state.

This module owns writes only to the seven Foundation-provided Layer 5 tables.
It deliberately has no scheduler loop, lease acquisition, subprocess, Gmail, or
provider behavior.  Every operation opens a short SQLite transaction.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import stat
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Mapping

from trainlab.foundation import validate_schema_manifest

from .evidence_codes import DOWNSTREAM_FAILURE_EVIDENCE_CODES
from .scheduling_config import SchedulerJobProjection

if TYPE_CHECKING:
    from .domain_state_machine import (
        StepTransitionEvent,
        WorkflowTransitionEvent,
    )
    from .state_projection import (
        StepDefinition,
        WorkflowDefinition,
    )
    from .workflow_definition_store import WorkflowDefinitionAggregate


class OrchestrationRepositoryError(RuntimeError):
    """The requested audited state change is not safe or valid."""


class OrchestrationSchemaIncompatible(OrchestrationRepositoryError):
    """Foundation's existing schema is absent or incompatible; do not repair it."""


RunStatus = Literal[
    "started", "succeeded", "partial", "failed", "deferred", "cancelled"
]
StepStatus = Literal["pending", "running", "succeeded", "failed", "deferred", "skipped"]
IncidentState = Literal["open", "acknowledged", "resolved", "suppressed"]
AlertStatus = Literal[
    "pending", "sending", "sent", "already_sent", "delivery_unknown", "failed"
]

_HASH = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_UTC_TEXT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_NO_RECEIPT_EVIDENCE = (
    frozenset(
        {
            "deterministic_check",
            "process_start_failed",
            "process_timeout",
            "provider_unavailable",
        }
    )
    | DOWNSTREAM_FAILURE_EVIDENCE_CODES
)
_ALLOWED_TABLES = frozenset(
    {
        "scheduler_jobs",
        "scheduler_leases",
        "orchestrator_runs",
        "orchestrator_steps",
        "service_health_checks",
        "operational_incidents",
        "operational_alert_deliveries",
    }
)
_RUN_TRANSITIONS = {
    "started": {"succeeded", "partial", "failed", "deferred", "cancelled"},
    "deferred": {"started", "failed", "cancelled"},
    "succeeded": set(),
    "partial": set(),
    "failed": set(),
    "cancelled": set(),
}
_STEP_TRANSITIONS = {
    "pending": {"running", "skipped"},
    "running": {"succeeded", "failed", "deferred"},
    "deferred": {"running", "failed", "skipped"},
    "succeeded": set(),
    "failed": set(),
    "skipped": set(),
}
_INCIDENT_TRANSITIONS = {
    "open": {"acknowledged", "resolved", "suppressed"},
    "acknowledged": {"resolved", "suppressed"},
    "resolved": {"open"},
    "suppressed": {"open"},
}
_ALERT_TRANSITIONS = {
    "pending": {"sending", "failed", "delivery_unknown"},
    "sending": {"sent", "already_sent", "failed", "delivery_unknown"},
    "delivery_unknown": {"sent", "already_sent", "failed"},
    "failed": {"sending"},
    "sent": set(),
    "already_sent": set(),
}


@dataclass(frozen=True)
class WorkflowRunRecord:
    id: int
    workflow_key: str
    workflow_kind: str
    subject_id: int | None
    logical_local_date: str | None
    trigger_kind: str
    status: RunStatus
    deadline_at_utc: str | None
    parent_workflow_run_id: int | None
    started_at_utc: str
    completed_at_utc: str | None
    result_summary_json: str


@dataclass(frozen=True)
class WorkflowStepRecord:
    id: int
    orchestrator_run_id: int
    step_key: str
    ordinal: int
    layer_no: int
    tool_mode: str
    request_sha256: str
    invocation_id: str | None
    downstream_run_id: str | None
    receipt_sha256: str | None
    status: StepStatus
    attempt_count: int
    next_retry_at_utc: str | None
    started_at_utc: str | None
    completed_at_utc: str | None


@dataclass(frozen=True)
class IncidentRecord:
    id: int
    incident_key: str
    category: str
    severity: str
    state: IncidentState
    related_workflow_run_id: int | None
    related_step_id: int | None
    first_seen_at_utc: str
    last_seen_at_utc: str
    occurrence_count: int
    resolved_at_utc: str | None
    error_code: str | None
    error_summary: str | None
    next_action: str | None


@dataclass(frozen=True)
class AlertDeliveryRecord:
    id: int
    operational_incident_id: int
    idempotency_key: str
    status: AlertStatus
    provider_message_id: str | None
    provider_thread_id: str | None
    sent_at_utc: str | None
    last_verified_at_utc: str | None
    error_code: str | None
    error_summary: str | None


@dataclass(frozen=True)
class SchedulerJobRecord:
    id: int
    job_key: str
    workflow_kind: str
    timezone: str
    schedule_spec_json: str
    is_enabled: bool
    misfire_policy: str
    last_due_at_utc: str | None
    next_due_at_utc: str | None
    config_sha256: str
    updated_at_utc: str


@dataclass(frozen=True)
class SchedulerLeaseRecord:
    id: int
    lease_key: str
    owner_instance_id: str
    owner_pid: int
    acquired_at_utc: str
    heartbeat_at_utc: str
    expires_at_utc: str


@dataclass(frozen=True)
class SchedulerHandoffRecord:
    workflow: WorkflowRunRecord
    job_key: str
    due_at_utc: str
    next_due_at_utc: str
    config_sha256: str
    dispatch_generation: str
    materialization_command_sha256: str
    materialization_evidence_sha256: str


class OrchestrationRepository:
    """The only Layer 5 write gateway; it never creates or changes schema."""

    def __init__(
        self, database_path: Path, *, manifest_path: Path | None = None
    ) -> None:
        self._database_path = database_path
        self._manifest_path = (
            manifest_path
            or Path(__file__).resolve().parents[3]
            / "harness/schemas/foundation_schema_manifest.json"
        )
        self._manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        self._identity_fds: dict[int, tuple[int, tuple[int, int, int, int]]] = {}

    def create_workflow(
        self,
        *,
        workflow_key: str,
        workflow_kind: str,
        trigger_kind: Literal["scheduled", "manual", "recovery", "reconcile"],
        started_at_utc: datetime,
        logical_local_date: str | None = None,
        subject_id: int | None = None,
        deadline_at_utc: datetime | None = None,
        parent_workflow_run_id: int | None = None,
    ) -> WorkflowRunRecord:
        _identifier(workflow_key)
        _identifier(workflow_kind)
        start = _utc_text(started_at_utc)
        if logical_local_date is not None:
            try:
                date.fromisoformat(logical_local_date)
            except ValueError as exc:
                raise OrchestrationRepositoryError(
                    "orchestrator_logical_date_invalid"
                ) from exc
        if deadline_at_utc is not None and _parse_utc(
            _utc_text(deadline_at_utc)
        ) < _parse_utc(start):
            raise OrchestrationRepositoryError("orchestrator_deadline_invalid")
        with self._transaction() as conn:
            try:
                cursor = conn.execute(
                    "INSERT INTO orchestrator_runs (workflow_key,workflow_kind,subject_id,logical_local_date,trigger_kind,status,deadline_at_utc,parent_workflow_run_id,started_at_utc,result_summary_json) VALUES (?,?,?,?,?,'started',?,?,?,'{}')",
                    (
                        workflow_key,
                        workflow_kind,
                        subject_id,
                        logical_local_date,
                        trigger_kind,
                        _optional_utc(deadline_at_utc),
                        parent_workflow_run_id,
                        start,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise OrchestrationRepositoryError(
                    "orchestrator_workflow_key_conflict"
                ) from exc
            return self._run_by_id(conn, cursor.lastrowid)

    def create_workflow_definition(
        self,
        workflow: "WorkflowDefinition",
        steps: tuple["StepDefinition", ...],
    ) -> "WorkflowDefinitionAggregate":
        """Atomically create or exactly replay an immutable workflow definition."""

        from .workflow_definition_store import (
            create_persisted_workflow_definition,
        )

        return create_persisted_workflow_definition(self, workflow, steps)

    def load_workflow_definition(
        self,
        workflow_key: str,
    ) -> "WorkflowDefinitionAggregate | None":
        """Deeply reload a persisted workflow definition on a fresh connection."""

        from .workflow_definition_store import (
            load_persisted_workflow_definition,
        )

        if not isinstance(workflow_key, str):
            raise OrchestrationRepositoryError("workflow_definition_key_invalid")
        _identifier(workflow_key)
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            self._verify_connected_identity(connection)
            result = load_persisted_workflow_definition(
                self,
                connection,
                workflow_key,
                missing_none=True,
            )
            self._verify_connected_identity(connection)
            connection.rollback()
            return result
        except OrchestrationRepositoryError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise OrchestrationRepositoryError(
                "workflow_definition_persistence_unavailable"
            ) from exc
        finally:
            self._close_connected(connection)

    def transition_workflow_domain(
        self,
        workflow_key: str,
        event: "WorkflowTransitionEvent",
    ) -> "WorkflowDefinitionAggregate":
        """Atomically append one strict S5-05A2 workflow transition."""

        from .workflow_definition_store import transition_persisted_workflow

        if not isinstance(workflow_key, str):
            raise OrchestrationRepositoryError("workflow_definition_key_invalid")
        _identifier(workflow_key)
        return transition_persisted_workflow(self, workflow_key, event)

    def transition_step_domain(
        self,
        workflow_key: str,
        event: "StepTransitionEvent",
    ) -> "WorkflowDefinitionAggregate":
        """Atomically append one strict S5-05A2 step transition."""

        from .workflow_definition_store import transition_persisted_step

        if not isinstance(workflow_key, str):
            raise OrchestrationRepositoryError("workflow_definition_key_invalid")
        _identifier(workflow_key)
        return transition_persisted_step(self, workflow_key, event)

    def upsert_scheduler_job(
        self,
        projection: SchedulerJobProjection,
        *,
        is_enabled: bool,
        updated_at_utc: datetime,
    ) -> SchedulerJobRecord:
        """Persist a fixed S5-02 projection; it cannot redefine scheduling semantics."""
        _identifier(projection.job_key)
        _identifier(projection.workflow_kind)
        _hash(projection.config_sha256)
        schedule = json.dumps(
            {
                "schedule_kind": projection.schedule_kind,
                "interval_seconds": projection.interval_seconds,
                "depends_on_job_key": projection.depends_on_job_key,
                "collection_strategy": projection.collection_strategy,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        misfire = (
            "bounded" if projection.misfire_window is not None else "not_applicable"
        )
        projected_due = _utc_text(projection.next_due_at_utc)
        updated = _utc_text(updated_at_utc)
        with self._transaction() as conn:
            # Calendar jobs keep an already-persisted due marker across a
            # Supervisor restart.  Otherwise projecting "the next" 09:00 at
            # startup would erase a still-valid bounded misfire before the due
            # queue can claim it.  Interval jobs intentionally collapse missed
            # ticks and therefore always use the fresh projection.
            existing = self._job_by_key(conn, projection.job_key, missing_none=True)
            if (
                existing is not None
                and projection.schedule_kind in {"daily_at", "weekly_at"}
                and existing.next_due_at_utc is not None
                and existing.config_sha256 == projection.config_sha256
                and existing.timezone == projection.timezone
                and existing.workflow_kind == projection.workflow_kind
                and existing.is_enabled == bool(is_enabled)
                and _parse_utc(existing.next_due_at_utc) <= _parse_utc(updated)
            ):
                projected_due = existing.next_due_at_utc
            conn.execute(
                "INSERT INTO scheduler_jobs (job_key,workflow_kind,timezone,schedule_spec_json,is_enabled,misfire_policy,next_due_at_utc,config_sha256,updated_at_utc) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(job_key) DO UPDATE SET workflow_kind=excluded.workflow_kind,timezone=excluded.timezone,schedule_spec_json=excluded.schedule_spec_json,is_enabled=excluded.is_enabled,misfire_policy=excluded.misfire_policy,next_due_at_utc=excluded.next_due_at_utc,config_sha256=excluded.config_sha256,updated_at_utc=excluded.updated_at_utc",
                (
                    projection.job_key,
                    projection.workflow_kind,
                    projection.timezone,
                    schedule,
                    int(is_enabled),
                    misfire,
                    projected_due,
                    projection.config_sha256,
                    updated,
                ),
            )
            return self._job_by_key(conn, projection.job_key)

    def transition_workflow(
        self, workflow_key: str, status: RunStatus, *, at_utc: datetime
    ) -> WorkflowRunRecord:
        _identifier(workflow_key)
        timestamp = _utc_text(at_utc)
        with self._transaction() as conn:
            current = self._validated_run_by_key(conn, workflow_key)
            if _has_workflow_definition(current.result_summary_json):
                raise OrchestrationRepositoryError(
                    "workflow_definition_transition_not_implemented"
                )
            if current.status == status:
                if (current.completed_at_utc or current.started_at_utc) == timestamp:
                    return current
                raise OrchestrationRepositoryError(
                    "orchestrator_run_same_status_conflict"
                )
            _transition(_RUN_TRANSITIONS, current.status, status, "orchestrator_run")
            if _parse_utc(timestamp) < _parse_utc(current.started_at_utc):
                raise OrchestrationRepositoryError("orchestrator_run_timestamp_invalid")
            complete = timestamp if status != "started" else None
            conn.execute(
                "UPDATE orchestrator_runs SET status=?,completed_at_utc=? WHERE id=?",
                (status, complete, current.id),
            )
            return self._run_by_id(conn, current.id)

    def create_step(
        self,
        *,
        workflow_key: str,
        step_key: str,
        ordinal: int,
        layer_no: int,
        tool_mode: str,
        request_sha256: str,
        status: StepStatus = "pending",
        invocation_id: str | None = None,
        downstream_run_id: str | None = None,
    ) -> WorkflowStepRecord:
        _identifier(workflow_key)
        _identifier(step_key)
        _identifier(tool_mode)
        _hash(request_sha256)
        if ordinal < 0 or not 1 <= layer_no <= 5 or status != "pending":
            raise OrchestrationRepositoryError(
                "orchestrator_step_invalid_initial_state"
            )
        if invocation_id is not None:
            _identifier(invocation_id)
        if downstream_run_id is not None:
            _identifier(downstream_run_id)
        with self._transaction() as conn:
            run = self._validated_run_by_key(conn, workflow_key)
            if _has_workflow_definition(run.result_summary_json):
                raise OrchestrationRepositoryError(
                    "workflow_definition_transition_not_implemented"
                )
            if conn.execute(
                "SELECT 1 FROM orchestrator_steps WHERE orchestrator_run_id=? AND ordinal=?",
                (run.id, ordinal),
            ).fetchone():
                raise OrchestrationRepositoryError("orchestrator_step_ordinal_conflict")
            try:
                cursor = conn.execute(
                    "INSERT INTO orchestrator_steps (orchestrator_run_id,step_key,ordinal,layer_no,tool_mode,request_sha256,invocation_id,downstream_run_id,status) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        run.id,
                        step_key,
                        ordinal,
                        layer_no,
                        tool_mode,
                        request_sha256,
                        invocation_id,
                        downstream_run_id,
                        status,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise OrchestrationRepositoryError(
                    "orchestrator_step_key_conflict"
                ) from exc
            summary = _validated_step_summary(self._run_summary(conn, run.id))
            summary["steps"][step_key] = {"events": []}
            conn.execute(
                "UPDATE orchestrator_runs SET result_summary_json=? WHERE id=?",
                (json.dumps(summary, sort_keys=True, separators=(",", ":")), run.id),
            )
            return self._step_by_id(conn, cursor.lastrowid)

    def transition_step(
        self,
        *,
        workflow_key: str,
        step_key: str,
        status: StepStatus,
        at_utc: datetime,
        receipt_sha256: str | None = None,
        controlled_counts: Mapping[str, int] | None = None,
        evidence_code: str | None = None,
        next_retry_at_utc: datetime | None = None,
    ) -> WorkflowStepRecord:
        _identifier(workflow_key)
        _identifier(step_key)
        timestamp = _utc_text(at_utc)
        if receipt_sha256 is not None:
            _hash(receipt_sha256)
        _counts(controlled_counts or {})
        if evidence_code is not None:
            _code(evidence_code)
        _validate_transition_payload(
            status, receipt_sha256, evidence_code, next_retry_at_utc, at_utc
        )
        with self._transaction() as conn:
            current = self._validated_step_by_key(conn, workflow_key, step_key)
            run = self._run_by_key(conn, workflow_key)
            if _has_workflow_definition(run.result_summary_json):
                raise OrchestrationRepositoryError(
                    "workflow_definition_transition_not_implemented"
                )
            retry = _optional_utc(next_retry_at_utc)
            raw_summary = self._run_summary(conn, current.orchestrator_run_id)
            history = _validated_step_summary(raw_summary)
            _validate_step_row(current, history)
            previous_events = (
                history["steps"].get(current.step_key, {}).get("events", [])
            )
            if previous_events and _parse_utc(timestamp) < _parse_utc(
                previous_events[-1]["at_utc"]
            ):
                raise OrchestrationRepositoryError(
                    "orchestrator_step_timestamp_invalid"
                )
            if current.status == status:
                if _same_step_event(
                    raw_summary,
                    current.step_key,
                    status,
                    timestamp,
                    receipt_sha256,
                    controlled_counts or {},
                    evidence_code,
                    retry,
                ):
                    return current
                raise OrchestrationRepositoryError(
                    "orchestrator_step_same_status_conflict"
                )
            _transition(_STEP_TRANSITIONS, current.status, status, "orchestrator_step")
            if current.started_at_utc is not None and _parse_utc(
                timestamp
            ) < _parse_utc(current.started_at_utc):
                raise OrchestrationRepositoryError(
                    "orchestrator_step_timestamp_invalid"
                )
            if status in {"succeeded", "failed", "skipped"}:
                retry = None
            completed = (
                timestamp if status in {"succeeded", "failed", "skipped"} else None
            )
            started = (
                timestamp
                if status == "running" and current.status == "pending"
                else None
            )
            attempts = current.attempt_count + (
                1
                if status == "running" and current.status in {"pending", "deferred"}
                else 0
            )
            summary = _append_step_event(
                current.step_key,
                raw_summary,
                attempts,
                status,
                timestamp,
                controlled_counts or {},
                receipt_sha256,
                evidence_code,
                retry,
            )
            _validated_step_summary(summary)
            conn.execute(
                "UPDATE orchestrator_steps SET status=?,receipt_sha256=?,attempt_count=?,next_retry_at_utc=?,started_at_utc=COALESCE(?,started_at_utc),completed_at_utc=? WHERE id=?",
                (
                    status,
                    receipt_sha256,
                    attempts,
                    retry,
                    started,
                    completed,
                    current.id,
                ),
            )
            conn.execute(
                "UPDATE orchestrator_runs SET result_summary_json=? WHERE id=?",
                (summary, current.orchestrator_run_id),
            )
            return self._step_by_id(conn, current.id)

    def record_health_check(
        self,
        *,
        check_kind: str,
        target_kind: str,
        status: str,
        checked_at_utc: datetime,
        target_id: str | None = None,
        metrics: Mapping[str, int | float | bool | str | None] | None = None,
        threshold_version: str | None = None,
    ) -> int:
        _identifier(check_kind)
        _identifier(target_kind)
        _identifier(status)
        _utc_text(checked_at_utc)
        if target_id is not None:
            _identifier(target_id)
        if threshold_version is not None:
            _identifier(threshold_version)
        summary = _summary(metrics or {})
        with self._transaction() as conn:
            return int(
                conn.execute(
                    "INSERT INTO service_health_checks (check_kind,target_kind,target_id,status,metrics_json,threshold_version,checked_at_utc) VALUES (?,?,?,?,?,?,?)",
                    (
                        check_kind,
                        target_kind,
                        target_id,
                        status,
                        summary,
                        threshold_version,
                        _utc_text(checked_at_utc),
                    ),
                ).lastrowid
            )

    def latest_health_check_at(
        self,
        *,
        check_kind: str,
        target_kind: str,
        target_id: str | None = None,
    ) -> datetime | None:
        """Return only the latest validated probe timestamp for cadence control."""
        _identifier(check_kind)
        _identifier(target_kind)
        if target_id is not None:
            _identifier(target_id)

        def read(conn: sqlite3.Connection) -> datetime | None:
            if target_id is None:
                row = conn.execute(
                    "SELECT checked_at_utc FROM service_health_checks "
                    "WHERE check_kind=? AND target_kind=? AND target_id IS NULL "
                    "ORDER BY checked_at_utc DESC,id DESC LIMIT 1",
                    (check_kind, target_kind),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT checked_at_utc FROM service_health_checks "
                    "WHERE check_kind=? AND target_kind=? AND target_id=? "
                    "ORDER BY checked_at_utc DESC,id DESC LIMIT 1",
                    (check_kind, target_kind, target_id),
                ).fetchone()
            return None if row is None else _parse_utc(str(row[0]))

        return self._readonly(read)

    def record_incident(
        self,
        *,
        incident_key: str,
        category: str,
        severity: Literal["info", "warning", "error", "critical"],
        seen_at_utc: datetime,
        error_code: str | None = None,
        error_summary: str | None = None,
        next_action: str | None = None,
        related_workflow_run_id: int | None = None,
        related_step_id: int | None = None,
    ) -> IncidentRecord:
        _identifier(incident_key)
        _code(category)
        if severity not in {"info", "warning", "error", "critical"}:
            raise OrchestrationRepositoryError("operational_incident_severity_invalid")
        for value in (error_code, error_summary, next_action):
            _safe_text(value)
        timestamp = _utc_text(seen_at_utc)
        with self._transaction() as conn:
            if related_workflow_run_id is not None and related_step_id is not None:
                owner = conn.execute(
                    "SELECT orchestrator_run_id FROM orchestrator_steps WHERE id=?",
                    (related_step_id,),
                ).fetchone()
                if owner is None or owner[0] != related_workflow_run_id:
                    raise OrchestrationRepositoryError(
                        "operational_incident_reference_invalid"
                    )
            row = conn.execute(
                "SELECT id FROM operational_incidents WHERE incident_key=?",
                (incident_key,),
            ).fetchone()
            if row:
                previous = self._incident_by_id(conn, row[0])
                if (
                    previous.category != category
                    or previous.related_workflow_run_id != related_workflow_run_id
                    or previous.related_step_id != related_step_id
                ):
                    raise OrchestrationRepositoryError(
                        "operational_incident_identity_conflict"
                    )
                severity_value = _higher_severity(previous.severity, severity)
                reopened = previous.state in {"resolved", "suppressed"}
                seen = (
                    max(_parse_utc(previous.last_seen_at_utc), _parse_utc(timestamp))
                    .isoformat()
                    .replace("+00:00", "Z")
                )
                conn.execute(
                    "UPDATE operational_incidents SET severity=?,state=?,resolved_at_utc=?,last_seen_at_utc=?,occurrence_count=occurrence_count+1,error_code=COALESCE(?,error_code),error_summary=COALESCE(?,error_summary),next_action=COALESCE(?,next_action) WHERE id=?",
                    (
                        severity_value,
                        "open" if reopened else previous.state,
                        None if reopened else previous.resolved_at_utc,
                        seen,
                        error_code,
                        error_summary,
                        next_action,
                        previous.id,
                    ),
                )
                return self._incident_by_id(conn, previous.id)
            try:
                cursor = conn.execute(
                    "INSERT INTO operational_incidents (incident_key,category,severity,state,related_workflow_run_id,related_step_id,first_seen_at_utc,last_seen_at_utc,occurrence_count,error_code,error_summary,next_action) VALUES (?,?,?,'open',?,?,?,?,1,?,?,?)",
                    (
                        incident_key,
                        category,
                        severity,
                        related_workflow_run_id,
                        related_step_id,
                        timestamp,
                        timestamp,
                        error_code,
                        error_summary,
                        next_action,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise OrchestrationRepositoryError(
                    "operational_incident_reference_invalid"
                ) from exc
            return self._incident_by_id(conn, cursor.lastrowid)

    def transition_incident(
        self, incident_key: str, state: IncidentState, *, at_utc: datetime
    ) -> IncidentRecord:
        _identifier(incident_key)
        timestamp = _utc_text(at_utc)
        with self._transaction() as conn:
            current = self._incident_by_key(conn, incident_key)
            if current.state == state:
                return current
            _transition(
                _INCIDENT_TRANSITIONS, current.state, state, "operational_incident"
            )
            if _parse_utc(timestamp) < _parse_utc(
                current.first_seen_at_utc
            ) or _parse_utc(timestamp) < _parse_utc(current.last_seen_at_utc):
                raise OrchestrationRepositoryError(
                    "operational_incident_timestamp_invalid"
                )
            resolved = timestamp if state == "resolved" else None
            conn.execute(
                "UPDATE operational_incidents SET state=?,resolved_at_utc=? WHERE id=?",
                (state, resolved, current.id),
            )
            return self._incident_by_id(conn, current.id)

    def resolve_retryable_workflow_failures(
        self, workflow_key: str, *, at_utc: datetime
    ) -> tuple[IncidentRecord, ...]:
        """Resolve only earlier open workflow failures recovered by a success.

        Matching is intentionally narrower than the generic incident surface:
        mail is scoped to one subject, health to its workflow kind, and
        morning/weekly to one subject and logical date.  Acknowledged,
        suppressed, safety, data-quality, and unrelated incidents are never
        candidates.
        """
        _identifier(workflow_key)
        timestamp = _utc_text(at_utc)
        with self._transaction() as conn:
            workflow = self._validated_run_by_key(conn, workflow_key)
            if workflow.status != "succeeded":
                raise OrchestrationRepositoryError("workflow_recovery_requires_success")
            clauses = [
                "i.category='workflow'",
                "i.state='open'",
                "i.error_code='workflow_execution_failed'",
                "i.related_workflow_run_id IS NOT NULL",
                "r.id<?",
            ]
            parameters: list[object] = [workflow.id]
            if workflow.workflow_kind == "mail":
                if workflow.subject_id is None:
                    return ()
                clauses.extend(("r.workflow_kind='mail'", "r.subject_id=?"))
                parameters.append(workflow.subject_id)
            elif workflow.workflow_kind == "health_check":
                clauses.append("r.workflow_kind='health_check'")
            elif workflow.workflow_kind in {"morning", "weekly"}:
                if workflow.subject_id is None or workflow.logical_local_date is None:
                    return ()
                clauses.extend(
                    (
                        "r.workflow_kind=?",
                        "r.subject_id=?",
                        "r.logical_local_date=?",
                    )
                )
                parameters.extend(
                    (
                        workflow.workflow_kind,
                        workflow.subject_id,
                        workflow.logical_local_date,
                    )
                )
            else:
                return ()
            recovered: list[IncidentRecord] = []
            resolved_at = _parse_utc(timestamp)
            last_incident_id = 0
            while True:
                rows = conn.execute(
                    "SELECT i.id,i.incident_key,i.category,i.severity,i.state,"
                    "i.related_workflow_run_id,i.related_step_id,"
                    "i.first_seen_at_utc,i.last_seen_at_utc,i.occurrence_count,"
                    "i.resolved_at_utc,i.error_code,i.error_summary,i.next_action "
                    "FROM operational_incidents AS i "
                    "JOIN orchestrator_runs AS r "
                    "ON r.id=i.related_workflow_run_id WHERE "
                    + " AND ".join((*clauses, "i.id>?"))
                    + " ORDER BY i.id ASC LIMIT 200",
                    (*parameters, last_incident_id),
                ).fetchall()
                if not rows:
                    break
                last_incident_id = int(rows[-1][0])
                for row in rows:
                    incident = self._incident_from_row(row)
                    if resolved_at < _parse_utc(incident.last_seen_at_utc):
                        continue
                    changed = conn.execute(
                        "UPDATE operational_incidents "
                        "SET state='resolved',resolved_at_utc=? "
                        "WHERE id=? AND state='open'",
                        (timestamp, incident.id),
                    ).rowcount
                    if changed == 1:
                        recovered.append(self._incident_by_id(conn, incident.id))
            return tuple(recovered)

    def create_alert_delivery(
        self, *, incident_key: str, idempotency_key: str
    ) -> AlertDeliveryRecord:
        _identifier(incident_key)
        _identifier(idempotency_key)
        with self._transaction() as conn:
            incident = self._incident_by_key(conn, incident_key)
            existing = conn.execute(
                "SELECT id FROM operational_alert_deliveries WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                alert = self._alert_by_id(conn, existing[0])
                if alert.operational_incident_id != incident.id:
                    raise OrchestrationRepositoryError(
                        "operational_alert_idempotency_conflict"
                    )
                return alert
            try:
                cursor = conn.execute(
                    "INSERT INTO operational_alert_deliveries (operational_incident_id,idempotency_key,status) VALUES (?,?,'pending')",
                    (incident.id, idempotency_key),
                )
            except sqlite3.IntegrityError as exc:
                raise OrchestrationRepositoryError(
                    "operational_alert_reference_invalid"
                ) from exc
            return self._alert_by_id(conn, cursor.lastrowid)

    def transition_alert_delivery(
        self,
        idempotency_key: str,
        status: AlertStatus,
        *,
        at_utc: datetime | None = None,
        provider_message_id: str | None = None,
        provider_thread_id: str | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> AlertDeliveryRecord:
        _identifier(idempotency_key)
        for provider_id in (provider_message_id, provider_thread_id):
            if provider_id is not None:
                _identifier(provider_id)
        _safe_text(error_code)
        _safe_text(error_summary)
        timestamp = _optional_utc(at_utc)
        with self._transaction() as conn:
            current = self._alert_by_key(conn, idempotency_key)
            if status in {"sent", "already_sent"}:
                if provider_message_id is None and current.provider_message_id is None:
                    raise OrchestrationRepositoryError(
                        "operational_alert_receipt_required"
                    )
                if timestamp is None and current.last_verified_at_utc is None:
                    raise OrchestrationRepositoryError(
                        "operational_alert_verification_required"
                    )
            for supplied, saved in (
                (provider_message_id, current.provider_message_id),
                (provider_thread_id, current.provider_thread_id),
            ):
                if supplied is not None and saved is not None and supplied != saved:
                    raise OrchestrationRepositoryError(
                        "operational_alert_receipt_conflict"
                    )
            if (
                current.status == status
                and provider_message_id is None
                and provider_thread_id is None
                and timestamp is None
                and error_code is None
                and error_summary is None
            ):
                return current
            if current.status != status:
                _transition(
                    _ALERT_TRANSITIONS, current.status, status, "operational_alert"
                )
            success = status in {"sent", "already_sent"}
            conn.execute(
                "UPDATE operational_alert_deliveries SET status=?,"
                "provider_message_id=COALESCE(?,provider_message_id),"
                "provider_thread_id=COALESCE(?,provider_thread_id),"
                "sent_at_utc=CASE WHEN ?='sent' THEN COALESCE(sent_at_utc,?) ELSE sent_at_utc END,"
                "last_verified_at_utc=CASE WHEN ? IN ('sent','already_sent') THEN COALESCE(?,last_verified_at_utc) ELSE last_verified_at_utc END,"
                "error_code=?,error_summary=? WHERE id=?",
                (
                    status,
                    provider_message_id,
                    provider_thread_id,
                    status,
                    timestamp,
                    status,
                    timestamp,
                    None if success else error_code,
                    None if success else error_summary,
                    current.id,
                ),
            )
            return self._alert_by_id(conn, current.id)

    def reconcilable_alert_deliveries(
        self, limit: int = 100
    ) -> tuple[tuple[IncidentRecord, AlertDeliveryRecord], ...]:
        """Return bounded ambiguous alert sends for startup reconciliation."""

        if type(limit) is not int or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise OrchestrationRepositoryError("operational_alert_query_limit_invalid")

        def query(conn):
            rows = conn.execute(
                "SELECT i.id,i.incident_key,i.category,i.severity,i.state,"
                "i.related_workflow_run_id,i.related_step_id,i.first_seen_at_utc,"
                "i.last_seen_at_utc,i.occurrence_count,i.resolved_at_utc,"
                "i.error_code,i.error_summary,i.next_action,"
                "d.id,d.operational_incident_id,d.idempotency_key,d.status,"
                "d.provider_message_id,d.provider_thread_id,d.sent_at_utc,"
                "d.last_verified_at_utc,d.error_code,d.error_summary "
                "FROM operational_alert_deliveries AS d "
                "JOIN operational_incidents AS i ON i.id=d.operational_incident_id "
                "WHERE d.status IN ('sending','delivery_unknown') "
                "ORDER BY d.id ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return tuple(
                (self._incident_from_row(row[:14]), self._alert_from_row(row[14:]))
                for row in rows
            )

        return self._readonly(query)

    def get_workflow(self, workflow_key: str) -> WorkflowRunRecord | None:
        _identifier(workflow_key)
        return self._readonly(
            lambda conn: self._validated_run_by_key(
                conn, workflow_key, missing_none=True
            )
        )

    def get_workflow_by_id(self, workflow_run_id: int) -> WorkflowRunRecord | None:
        """Return one validated workflow without weakening key-based identity."""
        if (
            type(workflow_run_id) is not int
            or isinstance(workflow_run_id, bool)
            or workflow_run_id <= 0
        ):
            raise OrchestrationRepositoryError("orchestrator_workflow_id_invalid")

        def query(conn: sqlite3.Connection) -> WorkflowRunRecord | None:
            row = conn.execute(
                "SELECT workflow_key FROM orchestrator_runs WHERE id=?",
                (workflow_run_id,),
            ).fetchone()
            if row is None:
                return None
            workflow = self._validated_run_by_key(conn, str(row[0]))
            if workflow.id != workflow_run_id:
                raise OrchestrationRepositoryError(
                    "orchestrator_run_summary_row_mismatch"
                )
            return workflow

        return self._readonly(query)

    def get_scheduler_job(self, job_key: str) -> SchedulerJobRecord | None:
        _identifier(job_key)
        return self._readonly(
            lambda conn: self._job_by_key(conn, job_key, missing_none=True)
        )

    def scheduler_jobs(self, limit: int = 16) -> tuple[SchedulerJobRecord, ...]:
        """Return the bounded scheduler projection in stable key order.

        This is deliberately a projection query rather than a generic SQL escape
        hatch.  S5-07 is the only consumer; later executor units must not infer
        business state from it.
        """
        if type(limit) is not int or not 1 <= limit <= 16:
            raise OrchestrationRepositoryError("scheduler_job_query_limit_invalid")
        return self._readonly(
            lambda conn: tuple(
                self._job_from_row(row)
                for row in conn.execute(
                    "SELECT id,job_key,workflow_kind,timezone,schedule_spec_json,is_enabled,misfire_policy,"
                    "last_due_at_utc,next_due_at_utc,config_sha256,updated_at_utc "
                    "FROM scheduler_jobs ORDER BY job_key ASC LIMIT ?",
                    (limit,),
                )
            )
        )

    def claim_scheduler_due(
        self,
        *,
        job_key: str,
        due_at_utc: datetime,
        next_due_at_utc: datetime,
        now_utc: datetime,
        owner_instance_id: str,
        owner_pid: int,
        workflow_key: str,
        workflow_kind: str,
        trigger_kind: Literal["scheduled", "recovery"],
        subject_id: int | None,
        logical_local_date: str | None,
        deadline_at_utc: datetime | None,
    ) -> bool:
        """CAS-consume one due marker while the exact supervisor lease is live.

        The transaction creates a strict durable handoff row and advances the
        job together. It does not fabricate a lower-layer invocation; the later
        executor atomically materializes the immutable workflow definition on
        that same row/key through ``create_workflow_definition``.
        """
        _identifier(job_key)
        _identifier(owner_instance_id)
        _identifier(workflow_key)
        _identifier(workflow_kind)
        if type(owner_pid) is not int or isinstance(owner_pid, bool) or owner_pid <= 0:
            raise OrchestrationRepositoryError("scheduler_claim_owner_invalid")
        due, next_due, now = (
            _utc_text(due_at_utc),
            _utc_text(next_due_at_utc),
            _utc_text(now_utc),
        )
        if _parse_utc(next_due) <= _parse_utc(due):
            raise OrchestrationRepositoryError("scheduler_claim_next_due_invalid")
        with self._transaction() as conn:
            lease = self._lease_by_key(conn, "supervisor", missing_none=True)
            if (
                lease is None
                or lease.owner_instance_id != owner_instance_id
                or lease.owner_pid != owner_pid
                or _parse_utc(lease.expires_at_utc) <= _parse_utc(now)
            ):
                return False
            job = self._job_by_key(conn, job_key, missing_none=True)
            if (
                job is None
                or not job.is_enabled
                or job.next_due_at_utc != due
                or job.last_due_at_utc == due
            ):
                return False
            generation = _lease_generation(lease)
            handoff_summary = _handoff_summary(
                job_key,
                due,
                next_due,
                job.config_sha256,
                generation,
                workflow_key,
                workflow_kind,
                subject_id,
                logical_local_date,
                trigger_kind,
                _optional_utc(deadline_at_utc),
            )
            existing = self._run_by_key(conn, workflow_key, missing_none=True)
            if existing is not None:
                handoff = _decode_handoff(existing.result_summary_json)
                if handoff is not None and not _handoff_identity_matches(
                    existing,
                    handoff,
                    workflow_kind,
                    subject_id,
                    logical_local_date,
                    trigger_kind,
                    deadline_at_utc,
                ):
                    raise OrchestrationRepositoryError(
                        "scheduler_handoff_identity_conflict"
                    )
            else:
                cursor = conn.execute(
                    "INSERT INTO orchestrator_runs (workflow_key,workflow_kind,subject_id,logical_local_date,trigger_kind,status,deadline_at_utc,parent_workflow_run_id,started_at_utc,result_summary_json) VALUES (?,?,?,?,?,'started',?,NULL,?,?)",
                    (
                        workflow_key,
                        workflow_kind,
                        subject_id,
                        logical_local_date,
                        trigger_kind,
                        _optional_utc(deadline_at_utc),
                        now,
                        handoff_summary,
                    ),
                )
                if cursor.lastrowid is None:
                    raise OrchestrationRepositoryError(
                        "scheduler_handoff_persistence_failed"
                    )
            changed = conn.execute(
                "UPDATE scheduler_jobs SET last_due_at_utc=?,next_due_at_utc=?,updated_at_utc=? "
                "WHERE id=? AND is_enabled=1 AND next_due_at_utc=? AND (last_due_at_utc IS NULL OR last_due_at_utc<>?)",
                (due, next_due, now, job.id, due, due),
            ).rowcount
            if changed != 1:
                raise OrchestrationRepositoryError(
                    "scheduler_handoff_persistence_failed"
                )
            return existing is None

    def claim_pending_scheduler_handoff(
        self,
        *,
        workflow_key: str,
        owner_instance_id: str,
        owner_pid: int,
        now_utc: datetime,
    ) -> SchedulerHandoffRecord | None:
        """Re-dispatch one abandoned handoff only to a new lease generation."""
        _identifier(workflow_key)
        _identifier(owner_instance_id)
        if type(owner_pid) is not int or isinstance(owner_pid, bool) or owner_pid <= 0:
            raise OrchestrationRepositoryError("scheduler_claim_owner_invalid")
        now = _utc_text(now_utc)
        with self._transaction() as conn:
            lease = self._lease_by_key(conn, "supervisor", missing_none=True)
            if (
                lease is None
                or lease.owner_instance_id != owner_instance_id
                or lease.owner_pid != owner_pid
                or _parse_utc(lease.expires_at_utc) <= _parse_utc(now)
            ):
                return None
            generation = _lease_generation(lease)
            rows = conn.execute(
                "SELECT id,workflow_key,workflow_kind,subject_id,logical_local_date,trigger_kind,status,deadline_at_utc,parent_workflow_run_id,started_at_utc,completed_at_utc,result_summary_json FROM orchestrator_runs WHERE workflow_key=? AND status='started' AND json_extract(result_summary_json,'$.schema_version')='scheduler_handoff_v1' LIMIT 1",
                (workflow_key,),
            ).fetchall()
            for row in rows:
                run = self._run_from_row(row)
                handoff = _decode_handoff(run.result_summary_json)
                if handoff is None or handoff["dispatch_generation"] == generation:
                    continue
                updated = _handoff_summary(
                    handoff["job_key"],
                    handoff["due_at_utc"],
                    handoff["next_due_at_utc"],
                    handoff["config_sha256"],
                    generation,
                    run.workflow_key,
                    run.workflow_kind,
                    run.subject_id,
                    run.logical_local_date,
                    run.trigger_kind,
                    run.deadline_at_utc,
                )
                changed = conn.execute(
                    "UPDATE orchestrator_runs SET result_summary_json=? WHERE id=? AND result_summary_json=?",
                    (updated, run.id, run.result_summary_json),
                ).rowcount
                if changed == 1:
                    parsed = _decode_handoff(updated)
                    assert parsed is not None
                    return _handoff_record(self._run_by_id(conn, run.id), parsed)
            return None

    def pending_scheduler_handoffs(
        self,
        *,
        owner_instance_id: str,
        owner_pid: int,
        now_utc: datetime,
        limit: int = 200,
    ) -> tuple[SchedulerHandoffRecord, ...]:
        """Read a bounded stable page of handoffs abandoned by older leases."""
        _identifier(owner_instance_id)
        if (
            type(owner_pid) is not int
            or isinstance(owner_pid, bool)
            or owner_pid <= 0
            or type(limit) is not int
            or not 1 <= limit <= 200
        ):
            raise OrchestrationRepositoryError("scheduler_claim_owner_invalid")
        now = _utc_text(now_utc)
        with self._transaction() as conn:
            lease = self._lease_by_key(conn, "supervisor", missing_none=True)
            if (
                lease is None
                or lease.owner_instance_id != owner_instance_id
                or lease.owner_pid != owner_pid
                or _parse_utc(lease.expires_at_utc) <= _parse_utc(now)
            ):
                return ()
            generation = _lease_generation(lease)
            rows = conn.execute(
                "SELECT id,workflow_key,workflow_kind,subject_id,logical_local_date,trigger_kind,status,deadline_at_utc,parent_workflow_run_id,started_at_utc,completed_at_utc,result_summary_json FROM orchestrator_runs WHERE status='started' AND json_extract(result_summary_json,'$.schema_version')='scheduler_handoff_v1' AND json_extract(result_summary_json,'$.dispatch_generation')<>? ORDER BY COALESCE(deadline_at_utc,started_at_utc),workflow_key LIMIT ?",
                (generation, limit),
            ).fetchall()
            result: list[SchedulerHandoffRecord] = []
            for row in rows:
                run = self._run_from_row(row)
                handoff = _decode_handoff(run.result_summary_json)
                if handoff is not None and handoff["dispatch_generation"] != generation:
                    result.append(_handoff_record(run, handoff))
            return tuple(result)

    def skip_scheduler_due(
        self,
        *,
        job_key: str,
        due_at_utc: datetime,
        next_due_at_utc: datetime,
        now_utc: datetime,
        owner_instance_id: str,
        owner_pid: int,
    ) -> bool:
        """Atomically consume an expired misfire without creating a workflow."""
        _identifier(job_key)
        _identifier(owner_instance_id)
        if type(owner_pid) is not int or isinstance(owner_pid, bool) or owner_pid <= 0:
            raise OrchestrationRepositoryError("scheduler_claim_owner_invalid")
        due, next_due, now = (
            _utc_text(due_at_utc),
            _utc_text(next_due_at_utc),
            _utc_text(now_utc),
        )
        if _parse_utc(next_due) <= _parse_utc(due):
            raise OrchestrationRepositoryError("scheduler_claim_next_due_invalid")
        with self._transaction() as conn:
            lease = self._lease_by_key(conn, "supervisor", missing_none=True)
            if (
                lease is None
                or lease.owner_instance_id != owner_instance_id
                or lease.owner_pid != owner_pid
                or _parse_utc(lease.expires_at_utc) <= _parse_utc(now)
            ):
                return False
            return (
                conn.execute(
                    "UPDATE scheduler_jobs SET last_due_at_utc=?,next_due_at_utc=?,updated_at_utc=? WHERE job_key=? AND is_enabled=1 AND next_due_at_utc=? AND (last_due_at_utc IS NULL OR last_due_at_utc<>?)",
                    (due, next_due, now, job_key, due, due),
                ).rowcount
                == 1
            )

    def get_scheduler_lease(self, lease_key: str) -> SchedulerLeaseRecord | None:
        """Read-only by design; acquisition and takeover begin in S5-04."""
        _identifier(lease_key)
        return self._readonly(
            lambda conn: self._lease_by_key(conn, lease_key, missing_none=True)
        )

    def get_scheduler_handoff(self, workflow_key: str) -> SchedulerHandoffRecord | None:
        """Return the exact immutable materialization binding for one queued handoff."""
        _identifier(workflow_key)

        def query(conn):
            run = self._run_by_key(conn, workflow_key, missing_none=True)
            if run is None:
                return None
            handoff = _decode_handoff(run.result_summary_json)
            return None if handoff is None else _handoff_record(run, handoff)

        return self._readonly(query)

    def reconcile_expired_scheduler_handoff(
        self, workflow_key: str, *, at_utc: datetime
    ) -> WorkflowRunRecord:
        """Materialize a terminal, auditable state for an expired handoff.

        A scheduler handoff has no workflow definition or steps yet.  Once its
        deadline has passed it cannot safely be executed with the old request
        identity, so reconciliation records a deterministic Layer-5 failure
        instead of changing a lower-layer table or leaving the row forever in
        ``started``.
        """
        _identifier(workflow_key)
        now = _parse_utc(_utc_text(at_utc))
        run = self.get_workflow(workflow_key)
        handoff = self.get_scheduler_handoff(workflow_key)
        if run is None or handoff is None or run.status != "started":
            raise OrchestrationRepositoryError("scheduler_handoff_not_reconcilable")
        if run.deadline_at_utc is None or _parse_utc(run.deadline_at_utc) >= now:
            raise OrchestrationRepositoryError("scheduler_handoff_not_expired")
        from .domain_state_machine import StepTransitionEvent, WorkflowTransitionEvent
        from .state_projection import StepDefinition, WorkflowDefinition

        started = _parse_utc(run.started_at_utc)
        workflow = WorkflowDefinition(
            run.workflow_key,
            run.workflow_kind,
            run.subject_id,
            run.logical_local_date,
            run.trigger_kind,
            _parse_utc(run.deadline_at_utc),
            run.parent_workflow_run_id,
            started,
            handoff.materialization_command_sha256,
            handoff.materialization_evidence_sha256,
            "queued",
        )
        request_hash = hashlib.sha256(
            f"expired-scheduler-handoff-reconcile\0{run.workflow_key}".encode("utf-8")
        ).hexdigest()
        step = StepDefinition(
            "reconcile",
            0,
            5,
            "reconcile",
            request_hash,
            f"reconcile-expired-{run.id}",
            None,
            "pending",
        )
        self.create_workflow_definition(workflow, (step,))
        cursor = max(now, started + timedelta(microseconds=1))
        self.transition_workflow_domain(
            run.workflow_key,
            WorkflowTransitionEvent(
                f"reconcile-expired-{run.id}:workflow:running",
                "running",
                cursor,
                "deterministic_check",
            ),
        )
        cursor += timedelta(microseconds=1)
        self.transition_step_domain(
            run.workflow_key,
            StepTransitionEvent(
                f"reconcile-expired-{run.id}:reconcile:running",
                "reconcile",
                "running",
                cursor,
            ),
        )
        cursor += timedelta(microseconds=1)
        self.transition_step_domain(
            run.workflow_key,
            StepTransitionEvent(
                f"reconcile-expired-{run.id}:reconcile:failed",
                "reconcile",
                "failed",
                cursor,
                evidence_code="deterministic_check",
            ),
        )
        cursor += timedelta(microseconds=1)
        self.transition_workflow_domain(
            run.workflow_key,
            WorkflowTransitionEvent(
                f"reconcile-expired-{run.id}:workflow:failed",
                "failed",
                cursor,
                "deterministic_check",
            ),
        )
        result = self.get_workflow(workflow_key)
        if result is None:
            raise OrchestrationRepositoryError("scheduler_handoff_reconcile_failed")
        return result

    def get_step(self, workflow_key: str, step_key: str) -> WorkflowStepRecord | None:
        _identifier(workflow_key)
        _identifier(step_key)
        return self._readonly(
            lambda conn: self._validated_step_by_key(
                conn, workflow_key, step_key, missing_none=True
            )
        )

    def get_incident(self, incident_key: str) -> IncidentRecord | None:
        _identifier(incident_key)
        return self._readonly(
            lambda conn: self._incident_by_key(conn, incident_key, missing_none=True)
        )

    def get_alert_delivery(self, idempotency_key: str) -> AlertDeliveryRecord | None:
        _identifier(idempotency_key)
        return self._readonly(
            lambda conn: self._alert_by_key(conn, idempotency_key, missing_none=True)
        )

    def recent_workflows(self, limit: int = 50) -> tuple[WorkflowRunRecord, ...]:
        if not 1 <= limit <= 200:
            raise OrchestrationRepositoryError("orchestrator_query_limit_invalid")
        return self._readonly(
            lambda conn: tuple(
                self._validated_run_by_key(conn, row[1])
                for row in conn.execute(
                    "SELECT id,workflow_key FROM v_recent_orchestrator_runs ORDER BY started_at_utc DESC,id DESC LIMIT ?",
                    (limit,),
                )
            )
        )

    def active_workflow_definitions(
        self, limit: int = 200, offset: int = 0
    ) -> tuple["WorkflowDefinitionAggregate", ...]:
        """Bounded durable recovery frontier, never a raw-table escape hatch."""
        if (
            type(limit) is not int
            or not 1 <= limit <= 200
            or type(offset) is not int
            or not 0 <= offset <= 1_000_000
        ):
            raise OrchestrationRepositoryError("orchestrator_query_limit_invalid")
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT workflow_key FROM orchestrator_runs WHERE status IN ('started','deferred') "
                "AND json_type(result_summary_json,'$.workflow_definition')='object' "
                "ORDER BY COALESCE(deadline_at_utc,started_at_utc) ASC,workflow_key ASC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            from .workflow_definition_store import load_persisted_workflow_definition

            values = tuple(
                load_persisted_workflow_definition(
                    self, connection, row[0], missing_none=False
                )
                for row in rows
            )
            if any(value is None for value in values):
                raise OrchestrationRepositoryError(
                    "workflow_definition_persistence_unavailable"
                )
            return values
        finally:
            self._close_connected(connection)

    def open_incidents(self, limit: int = 50) -> tuple[IncidentRecord, ...]:
        if not 1 <= limit <= 200:
            raise OrchestrationRepositoryError("orchestrator_query_limit_invalid")
        return self._readonly(
            lambda conn: tuple(
                self._incident_from_row(row)
                for row in conn.execute(
                    "SELECT id,incident_key,category,severity,state,related_workflow_run_id,related_step_id,first_seen_at_utc,last_seen_at_utc,occurrence_count,resolved_at_utc,error_code,error_summary,next_action FROM v_open_operational_incidents ORDER BY last_seen_at_utc DESC,id DESC LIMIT ?",
                    (limit,),
                )
            )
        )

    def _connect(self) -> sqlite3.Connection:
        fd, identity = _open_database_identity(self._database_path)
        try:
            conn = sqlite3.connect(
                f"file:{self._database_path}?mode=rw", uri=True, timeout=0
            )
        except BaseException as exc:
            os.close(fd)
            raise OrchestrationSchemaIncompatible(
                "orchestrator_database_unavailable"
            ) from exc
        try:
            _assert_database_identity(self._database_path, fd, identity)
            listing = conn.execute("PRAGMA database_list").fetchall()
            if (
                len(listing) != 1
                or listing[0][1] != "main"
                or os.path.realpath(listing[0][2])
                != os.path.realpath(self._database_path)
            ):
                raise OrchestrationSchemaIncompatible(
                    "orchestrator_database_path_unsafe"
                )
            conn.execute("PRAGMA foreign_keys=ON")
            issues = validate_schema_manifest(conn, self._manifest)
        except BaseException as exc:
            conn.close()
            os.close(fd)
            raise OrchestrationSchemaIncompatible(
                "orchestrator_schema_unreadable"
            ) from exc
        if issues or not _ALLOWED_TABLES <= set(self._manifest.get("tables", {})):
            conn.close()
            os.close(fd)
            raise OrchestrationSchemaIncompatible("orchestrator_schema_incompatible")
        self._identity_fds[id(conn)] = (fd, identity)
        return conn

    def _verify_connected_identity(self, conn: sqlite3.Connection) -> None:
        record = self._identity_fds.get(id(conn))
        if record is None:
            raise OrchestrationSchemaIncompatible("orchestrator_database_path_unsafe")
        _assert_database_identity(self._database_path, *record)

    def _close_connected(self, conn: sqlite3.Connection) -> None:
        record = self._identity_fds.pop(id(conn), None)
        try:
            conn.close()
        finally:
            if record is not None:
                os.close(record[0])

    def _transaction(self):
        class _Tx:
            def __enter__(inner):
                inner.conn = self._connect()
                try:
                    inner.conn.execute("BEGIN IMMEDIATE")
                    self._verify_connected_identity(inner.conn)
                except BaseException as exc:
                    self._close_connected(inner.conn)
                    if _is_sqlite_busy_or_locked(exc):
                        raise OrchestrationRepositoryError(
                            "orchestrator_database_busy"
                        ) from None
                    raise
                return inner.conn

            def __exit__(inner, typ, value, traceback):
                try:
                    if typ:
                        inner.conn.rollback()
                    else:
                        try:
                            self._verify_connected_identity(inner.conn)
                            inner.conn.commit()
                        except BaseException:
                            inner.conn.rollback()
                            raise
                finally:
                    self._close_connected(inner.conn)

        return _Tx()

    def _readonly(self, query):
        conn = self._connect()
        try:
            return query(conn)
        finally:
            self._close_connected(conn)

    @staticmethod
    def _run_summary(conn, run_id: int) -> str:
        row = conn.execute(
            "SELECT result_summary_json FROM orchestrator_runs WHERE id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise OrchestrationRepositoryError("orchestrator_workflow_not_found")
        return row[0]

    @staticmethod
    def _run_from_row(row: sqlite3.Row | tuple) -> WorkflowRunRecord:
        return WorkflowRunRecord(*row)

    def _run_by_id(self, conn, record_id: int) -> WorkflowRunRecord:
        row = conn.execute(
            "SELECT id,workflow_key,workflow_kind,subject_id,logical_local_date,trigger_kind,status,deadline_at_utc,parent_workflow_run_id,started_at_utc,completed_at_utc,result_summary_json FROM orchestrator_runs WHERE id=?",
            (record_id,),
        ).fetchone()
        if row is None:
            raise OrchestrationRepositoryError("orchestrator_workflow_not_found")
        return self._run_from_row(row)

    def _run_by_key(self, conn, key: str, *, missing_none: bool = False):
        row = conn.execute(
            "SELECT id,workflow_key,workflow_kind,subject_id,logical_local_date,trigger_kind,status,deadline_at_utc,parent_workflow_run_id,started_at_utc,completed_at_utc,result_summary_json FROM orchestrator_runs WHERE workflow_key=?",
            (key,),
        ).fetchone()
        if row is None:
            if missing_none:
                return None
            raise OrchestrationRepositoryError("orchestrator_workflow_not_found")
        return self._run_from_row(row)

    def _validated_run_by_key(self, conn, key: str, *, missing_none: bool = False):
        run = self._run_by_key(conn, key, missing_none=missing_none)
        if run is None:
            return None
        handoff = _decode_handoff(run.result_summary_json)
        if handoff is not None:
            if (
                run.status != "started"
                or run.completed_at_utc is not None
                or run.parent_workflow_run_id is not None
            ):
                raise OrchestrationRepositoryError("scheduler_handoff_row_mismatch")
            if (
                conn.execute(
                    "SELECT 1 FROM orchestrator_steps WHERE orchestrator_run_id=? LIMIT 1",
                    (run.id,),
                ).fetchone()
                is not None
            ):
                raise OrchestrationRepositoryError("scheduler_handoff_row_mismatch")
            _handoff_record(run, handoff)
            return run
        summary = _validated_step_summary(run.result_summary_json)
        if run.status not in {
            "started",
            "succeeded",
            "partial",
            "failed",
            "deferred",
            "cancelled",
        }:
            raise OrchestrationRepositoryError("orchestrator_run_summary_row_mismatch")
        started = _parse_utc(run.started_at_utc)
        if (
            run.deadline_at_utc is not None
            and _parse_utc(run.deadline_at_utc) < started
            and run.trigger_kind not in {"recovery", "reconcile"}
        ):
            raise OrchestrationRepositoryError("orchestrator_run_summary_row_mismatch")
        terminal = {"succeeded", "partial", "failed", "deferred", "cancelled"}
        if (run.status == "started" and run.completed_at_utc is not None) or (
            run.status in terminal and run.completed_at_utc is None
        ):
            raise OrchestrationRepositoryError("orchestrator_run_summary_row_mismatch")
        if (
            run.completed_at_utc is not None
            and _parse_utc(run.completed_at_utc) < started
        ):
            raise OrchestrationRepositoryError("orchestrator_run_summary_row_mismatch")
        rows = [
            self._step_from_row(row)
            for row in conn.execute(
                "SELECT id,orchestrator_run_id,step_key,ordinal,layer_no,tool_mode,request_sha256,invocation_id,downstream_run_id,receipt_sha256,status,attempt_count,next_retry_at_utc,started_at_utc,completed_at_utc FROM orchestrator_steps WHERE orchestrator_run_id=?",
                (run.id,),
            )
        ]
        if set(summary["steps"]) != {row.step_key for row in rows}:
            raise OrchestrationRepositoryError("orchestrator_run_summary_row_mismatch")
        for row in rows:
            _validate_step_row(row, summary)
        if "workflow_definition" in summary:
            from .workflow_definition_store import (
                load_persisted_workflow_definition,
            )

            load_persisted_workflow_definition(
                self,
                conn,
                key,
                missing_none=False,
                preloaded_run=run,
            )
        return run

    @staticmethod
    def _step_from_row(row):
        return WorkflowStepRecord(*row)

    def _step_by_id(self, conn, record_id: int):
        row = conn.execute(
            "SELECT id,orchestrator_run_id,step_key,ordinal,layer_no,tool_mode,request_sha256,invocation_id,downstream_run_id,receipt_sha256,status,attempt_count,next_retry_at_utc,started_at_utc,completed_at_utc FROM orchestrator_steps WHERE id=?",
            (record_id,),
        ).fetchone()
        if row is None:
            raise OrchestrationRepositoryError("orchestrator_step_not_found")
        return self._step_from_row(row)

    def _step_by_key(
        self, conn, workflow_key: str, step_key: str, *, missing_none: bool = False
    ):
        row = conn.execute(
            "SELECT s.id,s.orchestrator_run_id,s.step_key,s.ordinal,s.layer_no,s.tool_mode,s.request_sha256,s.invocation_id,s.downstream_run_id,s.receipt_sha256,s.status,s.attempt_count,s.next_retry_at_utc,s.started_at_utc,s.completed_at_utc FROM orchestrator_steps s JOIN orchestrator_runs r ON r.id=s.orchestrator_run_id WHERE r.workflow_key=? AND s.step_key=?",
            (workflow_key, step_key),
        ).fetchone()
        if row is None:
            if missing_none:
                return None
            raise OrchestrationRepositoryError("orchestrator_step_not_found")
        return self._step_from_row(row)

    def _validated_step_by_key(
        self, conn, workflow_key: str, step_key: str, *, missing_none: bool = False
    ):
        step = self._step_by_key(
            conn, workflow_key, step_key, missing_none=missing_none
        )
        if step is None:
            return None
        self._validated_run_by_key(conn, workflow_key)
        return step

    @staticmethod
    def _job_from_row(row):
        return SchedulerJobRecord(*row)

    def _job_by_key(self, conn, key: str, *, missing_none: bool = False):
        row = conn.execute(
            "SELECT id,job_key,workflow_kind,timezone,schedule_spec_json,is_enabled,misfire_policy,last_due_at_utc,next_due_at_utc,config_sha256,updated_at_utc FROM scheduler_jobs WHERE job_key=?",
            (key,),
        ).fetchone()
        if row is None:
            if missing_none:
                return None
            raise OrchestrationRepositoryError("scheduler_job_not_found")
        return self._job_from_row(row)

    @staticmethod
    def _lease_from_row(row):
        return SchedulerLeaseRecord(*row)

    def _lease_by_key(self, conn, key: str, *, missing_none: bool = False):
        row = conn.execute(
            "SELECT id,lease_key,owner_instance_id,owner_pid,acquired_at_utc,heartbeat_at_utc,expires_at_utc FROM scheduler_leases WHERE lease_key=?",
            (key,),
        ).fetchone()
        if row is None:
            if missing_none:
                return None
            raise OrchestrationRepositoryError("scheduler_lease_not_found")
        return self._lease_from_row(row)

    @staticmethod
    def _incident_from_row(row):
        return IncidentRecord(*row)

    def _incident_by_id(self, conn, record_id: int):
        row = conn.execute(
            "SELECT id,incident_key,category,severity,state,related_workflow_run_id,related_step_id,first_seen_at_utc,last_seen_at_utc,occurrence_count,resolved_at_utc,error_code,error_summary,next_action FROM operational_incidents WHERE id=?",
            (record_id,),
        ).fetchone()
        if row is None:
            raise OrchestrationRepositoryError("operational_incident_not_found")
        return self._incident_from_row(row)

    def _incident_by_key(self, conn, key: str, *, missing_none: bool = False):
        row = conn.execute(
            "SELECT id,incident_key,category,severity,state,related_workflow_run_id,related_step_id,first_seen_at_utc,last_seen_at_utc,occurrence_count,resolved_at_utc,error_code,error_summary,next_action FROM operational_incidents WHERE incident_key=?",
            (key,),
        ).fetchone()
        if row is None:
            if missing_none:
                return None
            raise OrchestrationRepositoryError("operational_incident_not_found")
        return self._incident_from_row(row)

    @staticmethod
    def _alert_from_row(row):
        return AlertDeliveryRecord(*row)

    def _alert_by_id(self, conn, record_id: int):
        row = conn.execute(
            "SELECT id,operational_incident_id,idempotency_key,status,provider_message_id,provider_thread_id,sent_at_utc,last_verified_at_utc,error_code,error_summary FROM operational_alert_deliveries WHERE id=?",
            (record_id,),
        ).fetchone()
        if row is None:
            raise OrchestrationRepositoryError("operational_alert_not_found")
        return self._alert_from_row(row)

    def _alert_by_key(self, conn, key: str, *, missing_none: bool = False):
        row = conn.execute(
            "SELECT id,operational_incident_id,idempotency_key,status,provider_message_id,provider_thread_id,sent_at_utc,last_verified_at_utc,error_code,error_summary FROM operational_alert_deliveries WHERE idempotency_key=?",
            (key,),
        ).fetchone()
        if row is None:
            if missing_none:
                return None
            raise OrchestrationRepositoryError("operational_alert_not_found")
        return self._alert_from_row(row)


def _utc_text(value: datetime) -> str:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise OrchestrationRepositoryError("orchestrator_timestamp_not_utc")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _is_sqlite_busy_or_locked(error: BaseException) -> bool:
    """Classify SQLite contention without inspecting provider error text."""

    error_code = getattr(error, "sqlite_errorcode", None)
    if not isinstance(error_code, int) or isinstance(error_code, bool):
        return False
    return error_code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not _UTC_TEXT.fullmatch(value):
        raise OrchestrationRepositoryError("orchestrator_timestamp_invalid")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except (TypeError, ValueError) as exc:
        raise OrchestrationRepositoryError("orchestrator_timestamp_invalid") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise OrchestrationRepositoryError("orchestrator_timestamp_invalid")
    return result.astimezone(UTC)


def _optional_utc(value: datetime | None) -> str | None:
    return None if value is None else _utc_text(value)


def _lease_generation(lease: SchedulerLeaseRecord) -> str:
    value = f"{lease.owner_instance_id}\0{lease.owner_pid}\0{lease.acquired_at_utc}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _handoff_summary(
    job_key: str,
    due: str,
    next_due: str,
    config_sha256: str,
    generation: str,
    workflow_key: str,
    workflow_kind: str,
    subject_id: int | None,
    logical_local_date: str | None,
    trigger_kind: str,
    deadline_at_utc: str | None,
) -> str:
    _identifier(job_key)
    _hash(config_sha256)
    _hash(generation)
    _identifier(workflow_key)
    _identifier(workflow_kind)
    _identifier(trigger_kind)
    _parse_utc(due)
    _parse_utc(next_due)
    if subject_id is not None and (type(subject_id) is not int or subject_id <= 0):
        raise OrchestrationRepositoryError("scheduler_handoff_invalid")
    if logical_local_date is not None:
        try:
            date.fromisoformat(logical_local_date)
        except (TypeError, ValueError) as exc:
            raise OrchestrationRepositoryError("scheduler_handoff_invalid") from exc
    if deadline_at_utc is not None:
        _parse_utc(deadline_at_utc)
    value = {
        "config_sha256": config_sha256,
        "dispatch_generation": generation,
        "due_at_utc": due,
        "job_key": job_key,
        "workflow_key": workflow_key,
        "workflow_kind": workflow_kind,
        "subject_id": subject_id,
        "logical_local_date": logical_local_date,
        "trigger_kind": trigger_kind,
        "deadline_at_utc": deadline_at_utc,
        "next_due_at_utc": next_due,
        "materialization_command_sha256": config_sha256,
        "schema_version": "scheduler_handoff_v1",
    }
    evidence = hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()
    value["materialization_evidence_sha256"] = evidence
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _decode_handoff(raw: object) -> dict[str, Any] | None:
    if type(raw) is not str or len(raw) > 4096:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if type(value) is not dict or value.get("schema_version") != "scheduler_handoff_v1":
        return None
    required = {
        "schema_version",
        "job_key",
        "due_at_utc",
        "next_due_at_utc",
        "config_sha256",
        "dispatch_generation",
        "workflow_key",
        "workflow_kind",
        "subject_id",
        "logical_local_date",
        "trigger_kind",
        "deadline_at_utc",
        "materialization_command_sha256",
        "materialization_evidence_sha256",
    }
    if set(value) != required:
        raise OrchestrationRepositoryError("scheduler_handoff_invalid")
    if not all(
        type(value[name]) is str
        for name in (
            "job_key",
            "due_at_utc",
            "next_due_at_utc",
            "config_sha256",
            "dispatch_generation",
            "workflow_key",
            "workflow_kind",
            "trigger_kind",
            "materialization_command_sha256",
            "materialization_evidence_sha256",
        )
    ):
        raise OrchestrationRepositoryError("scheduler_handoff_invalid")
    _identifier(value["job_key"])
    _parse_utc(value["due_at_utc"])
    _parse_utc(value["next_due_at_utc"])
    _identifier(value["workflow_key"])
    _identifier(value["workflow_kind"])
    _identifier(value["trigger_kind"])
    for name in (
        "config_sha256",
        "dispatch_generation",
        "materialization_command_sha256",
        "materialization_evidence_sha256",
    ):
        _hash(value[name])
    if value["materialization_command_sha256"] != value["config_sha256"]:
        raise OrchestrationRepositoryError("scheduler_handoff_invalid")
    if value["subject_id"] is not None and (
        type(value["subject_id"]) is not int or value["subject_id"] <= 0
    ):
        raise OrchestrationRepositoryError("scheduler_handoff_invalid")
    if value["logical_local_date"] is not None:
        try:
            date.fromisoformat(value["logical_local_date"])
        except (TypeError, ValueError) as exc:
            raise OrchestrationRepositoryError("scheduler_handoff_invalid") from exc
    if value["deadline_at_utc"] is not None:
        _parse_utc(value["deadline_at_utc"])
    evidence_source = dict(value)
    evidence = evidence_source.pop("materialization_evidence_sha256")
    expected = hashlib.sha256(
        json.dumps(
            evidence_source, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()
    if evidence != expected:
        raise OrchestrationRepositoryError("scheduler_handoff_invalid")
    if raw != json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False):
        raise OrchestrationRepositoryError("scheduler_handoff_invalid")
    return value


def _handoff_identity_matches(
    run: WorkflowRunRecord,
    handoff: Mapping[str, Any],
    workflow_kind: str,
    subject_id: int | None,
    logical_local_date: str | None,
    trigger_kind: str,
    deadline_at_utc: datetime | None,
) -> bool:
    return (
        run.workflow_kind == workflow_kind
        and run.subject_id == subject_id
        and run.logical_local_date == logical_local_date
        and run.trigger_kind == trigger_kind
        and run.deadline_at_utc == _optional_utc(deadline_at_utc)
        and handoff["workflow_key"] == run.workflow_key
        and handoff["workflow_kind"] == run.workflow_kind
        and handoff["subject_id"] == run.subject_id
        and handoff["logical_local_date"] == run.logical_local_date
        and handoff["trigger_kind"] == run.trigger_kind
        and handoff["deadline_at_utc"] == run.deadline_at_utc
    )


def _handoff_record(
    run: WorkflowRunRecord, value: Mapping[str, Any]
) -> SchedulerHandoffRecord:
    if not _handoff_identity_matches(
        run,
        value,
        run.workflow_kind,
        run.subject_id,
        run.logical_local_date,
        run.trigger_kind,
        None if run.deadline_at_utc is None else _parse_utc(run.deadline_at_utc),
    ):
        raise OrchestrationRepositoryError("scheduler_handoff_row_mismatch")
    return SchedulerHandoffRecord(
        run,
        value["job_key"],
        value["due_at_utc"],
        value["next_due_at_utc"],
        value["config_sha256"],
        value["dispatch_generation"],
        value["materialization_command_sha256"],
        value["materialization_evidence_sha256"],
    )


def _open_database_identity(path: Path) -> tuple[int, tuple[int, int, int, int]]:
    """Reject a swapped/symlinked/insecure database before opening it."""
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise OrchestrationSchemaIncompatible(
            "orchestrator_database_unavailable"
        ) from exc
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_uid != os.getuid()
        or stat.S_IMODE(before.st_mode) != 0o600
    ):
        raise OrchestrationSchemaIncompatible("orchestrator_database_path_unsafe")
    try:
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
    except OSError as exc:
        raise OrchestrationSchemaIncompatible(
            "orchestrator_database_path_unsafe"
        ) from exc
    opened = os.fstat(fd)
    identity = (
        opened.st_dev,
        opened.st_ino,
        opened.st_uid,
        stat.S_IMODE(opened.st_mode),
    )
    if identity != (
        before.st_dev,
        before.st_ino,
        before.st_uid,
        stat.S_IMODE(before.st_mode),
    ):
        os.close(fd)
        raise OrchestrationSchemaIncompatible("orchestrator_database_path_unsafe")
    return fd, identity


def _assert_database_identity(
    path: Path, fd: int, expected: tuple[int, int, int, int]
) -> None:
    opened = os.fstat(fd)
    current = os.lstat(path)
    for info in (opened, current):
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise OrchestrationSchemaIncompatible("orchestrator_database_path_unsafe")
    if (
        opened.st_dev,
        opened.st_ino,
        opened.st_uid,
        stat.S_IMODE(opened.st_mode),
    ) != expected or (
        current.st_dev,
        current.st_ino,
        current.st_uid,
        stat.S_IMODE(current.st_mode),
    ) != expected:
        raise OrchestrationSchemaIncompatible("orchestrator_database_path_unsafe")


def _identifier(value: str) -> None:
    if not _IDENTIFIER.fullmatch(value):
        raise OrchestrationRepositoryError("orchestrator_identifier_invalid")


def _hash(value: str) -> None:
    if not _HASH.fullmatch(value):
        raise OrchestrationRepositoryError("orchestrator_sha256_invalid")


def _safe_text(value: str | None) -> None:
    if value is not None:
        _code(value)


def _code(value: str) -> None:
    if not _CODE.fullmatch(value):
        raise OrchestrationRepositoryError("orchestrator_controlled_code_invalid")


def _counts(values: Mapping[str, int]) -> None:
    for key, value in values.items():
        _code(key)
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= 1_000_000_000
        ):
            raise OrchestrationRepositoryError("orchestrator_controlled_counts_invalid")


def _summary(values: Mapping[str, int | float | bool | str | None]) -> str:
    for key, value in values.items():
        _code(key)
        if not isinstance(value, (int, float, bool, str, type(None))):
            raise OrchestrationRepositoryError("orchestrator_metrics_invalid")
        if isinstance(value, float) and not math.isfinite(value):
            raise OrchestrationRepositoryError("orchestrator_metrics_invalid")
        if isinstance(value, str):
            _code(value)
    return json.dumps(
        dict(values), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _validate_transition_payload(
    status: str,
    receipt: str | None,
    evidence: str | None,
    retry_value: datetime | None,
    at_value: datetime,
) -> None:
    retry = None if retry_value is None else _utc_text(retry_value)
    at = _utc_text(at_value)
    if status == "running" and (
        receipt is not None or evidence is not None or retry is not None
    ):
        raise OrchestrationRepositoryError("orchestrator_step_payload_invalid")
    if status == "succeeded" and (
        receipt is None
        or evidence not in {None, "receipt_received"}
        or retry is not None
    ):
        raise OrchestrationRepositoryError("orchestrator_step_payload_invalid")
    if status in {"failed", "skipped"} and (
        (receipt is None and evidence not in _NO_RECEIPT_EVIDENCE)
        or (receipt is not None and evidence not in {None, "receipt_received"})
        or retry is not None
    ):
        raise OrchestrationRepositoryError("orchestrator_step_payload_invalid")
    if status == "deferred" and (
        (
            receipt is not None
            and (evidence not in {None, "receipt_received"} or retry is None)
        )
        or (receipt is None and retry is None and evidence not in _NO_RECEIPT_EVIDENCE)
        or (retry is not None and _parse_utc(retry) <= _parse_utc(at))
    ):
        raise OrchestrationRepositoryError("orchestrator_step_payload_invalid")


def _has_workflow_definition(raw: str) -> bool:
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise OrchestrationRepositoryError(
            "orchestrator_result_summary_invalid"
        ) from exc
    return isinstance(parsed, dict) and "workflow_definition" in parsed


def _validated_step_summary(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise OrchestrationRepositoryError(
            "orchestrator_result_summary_invalid"
        ) from exc
    if parsed == {}:
        parsed = {"schema_version": "step_summary_v2", "steps": {}}
    if not isinstance(parsed, dict):
        raise OrchestrationRepositoryError("orchestrator_result_summary_invalid")
    allowed_keys = (
        {"schema_version", "steps", "workflow_definition"}
        if "workflow_definition" in parsed
        else {"schema_version", "steps"}
    )
    if (
        set(parsed) != allowed_keys
        or parsed.get("schema_version") != "step_summary_v2"
        or not isinstance(parsed.get("steps"), dict)
    ):
        raise OrchestrationRepositoryError("orchestrator_result_summary_invalid")
    stateful_definition = False
    if "workflow_definition" in parsed:
        envelope = parsed["workflow_definition"]
        if not isinstance(envelope, dict):
            raise OrchestrationRepositoryError("orchestrator_result_summary_invalid")
        version = envelope.get("schema_version")
        expected_envelope_keys = (
            {"schema_version", "definition_sha256", "projection"}
            if version == "workflow_definition_v1"
            else {
                "schema_version",
                "definition_sha256",
                "projection",
                "events",
            }
            if version == "workflow_state_v1"
            else set()
        )
        if "scheduler_handoff" in envelope:
            expected_envelope_keys.add("scheduler_handoff")
        if (
            set(envelope) != expected_envelope_keys
            or not isinstance(envelope.get("definition_sha256"), str)
            or _HASH.fullmatch(envelope["definition_sha256"]) is None
            or not isinstance(envelope.get("projection"), dict)
        ):
            raise OrchestrationRepositoryError("orchestrator_result_summary_invalid")
        if "scheduler_handoff" in envelope:
            if (
                not isinstance(envelope["scheduler_handoff"], dict)
                or _decode_handoff(
                    json.dumps(
                        envelope["scheduler_handoff"],
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                )
                is None
            ):
                raise OrchestrationRepositoryError(
                    "orchestrator_result_summary_invalid"
                )
        stateful_definition = version == "workflow_state_v1"
        if stateful_definition:
            domain_events = envelope["events"]
            if (
                not isinstance(domain_events, dict)
                or set(domain_events) != {"schema_version", "workflow", "steps"}
                or domain_events.get("schema_version") != "domain_events_v1"
                or not isinstance(domain_events.get("workflow"), list)
                or len(domain_events["workflow"]) > 64
                or not isinstance(domain_events.get("steps"), dict)
                or len(domain_events["steps"]) > 64
                or any(
                    not isinstance(history, list) or len(history) > 32
                    for history in domain_events["steps"].values()
                )
            ):
                raise OrchestrationRepositoryError(
                    "orchestrator_result_summary_invalid"
                )
    if len(parsed["steps"]) > 64:
        raise OrchestrationRepositoryError("orchestrator_result_summary_limit")
    for key, value in parsed["steps"].items():
        _identifier(key)
        if (
            not isinstance(value, dict)
            or set(value) != {"events"}
            or not isinstance(value["events"], list)
            or not 0 <= len(value["events"]) <= 32
        ):
            raise OrchestrationRepositoryError("orchestrator_result_summary_invalid")
        prior_status = "pending"
        prior_attempt = 0
        prior_time: datetime | None = None
        for event in value["events"]:
            if not isinstance(event, dict) or set(event) != {
                "attempt",
                "status",
                "at_utc",
                "counts",
                "receipt_sha256",
                "evidence_code",
                "next_retry_at_utc",
            }:
                raise OrchestrationRepositoryError(
                    "orchestrator_result_summary_invalid"
                )
            if (
                type(event["attempt"]) is not int
                or not 0 <= event["attempt"] <= 16
                or event["status"] not in _STEP_TRANSITIONS
                or not isinstance(event["counts"], dict)
            ):
                raise OrchestrationRepositoryError(
                    "orchestrator_result_summary_invalid"
                )
            _parse_utc(event["at_utc"])
            _counts(event["counts"])
            if event["receipt_sha256"] is not None:
                _hash(event["receipt_sha256"])
            if event["evidence_code"] is not None:
                _code(event["evidence_code"])
            if event["next_retry_at_utc"] is not None:
                _parse_utc(event["next_retry_at_utc"])
            at = _parse_utc(event["at_utc"])
            if prior_time is not None and (
                at <= prior_time if stateful_definition else at < prior_time
            ):
                raise OrchestrationRepositoryError(
                    "orchestrator_result_summary_invalid"
                )
            if stateful_definition:
                prior_time = at
                continue
            if event["status"] not in _STEP_TRANSITIONS.get(prior_status, set()):
                raise OrchestrationRepositoryError(
                    "orchestrator_result_summary_invalid"
                )
            expected_attempt = prior_attempt + (
                1
                if event["status"] == "running"
                and prior_status in {"pending", "deferred"}
                else 0
            )
            if event["attempt"] != expected_attempt:
                raise OrchestrationRepositoryError(
                    "orchestrator_result_summary_invalid"
                )
            if (
                event["status"] == "deferred"
                and event["next_retry_at_utc"] is not None
                and _parse_utc(event["next_retry_at_utc"]) <= at
            ):
                raise OrchestrationRepositoryError(
                    "orchestrator_result_summary_invalid"
                )
            if (
                event["status"] in {"succeeded", "failed", "skipped"}
                and event["next_retry_at_utc"] is not None
            ):
                raise OrchestrationRepositoryError(
                    "orchestrator_result_summary_invalid"
                )
            if event["status"] == "succeeded" and event["receipt_sha256"] is None:
                raise OrchestrationRepositoryError(
                    "orchestrator_result_summary_invalid"
                )
            receipt, evidence, retry = (
                event["receipt_sha256"],
                event["evidence_code"],
                event["next_retry_at_utc"],
            )
            if event["status"] == "running" and (
                receipt is not None or evidence is not None or retry is not None
            ):
                raise OrchestrationRepositoryError(
                    "orchestrator_result_summary_invalid"
                )
            if event["status"] == "succeeded" and (
                evidence != "receipt_received" or retry is not None
            ):
                raise OrchestrationRepositoryError(
                    "orchestrator_result_summary_invalid"
                )
            if event["status"] in {"failed", "skipped"} and (
                (receipt is None and evidence not in _NO_RECEIPT_EVIDENCE)
                or (receipt is not None and evidence != "receipt_received")
            ):
                raise OrchestrationRepositoryError(
                    "orchestrator_result_summary_invalid"
                )
            if event["status"] == "deferred" and (
                (
                    receipt is not None
                    and (evidence != "receipt_received" or retry is None)
                )
                or (
                    receipt is None
                    and retry is None
                    and evidence not in _NO_RECEIPT_EVIDENCE
                )
            ):
                raise OrchestrationRepositoryError(
                    "orchestrator_result_summary_invalid"
                )
            prior_status, prior_attempt, prior_time = (
                event["status"],
                event["attempt"],
                at,
            )
    return parsed


def _validate_step_row(row: WorkflowStepRecord, summary: dict[str, Any]) -> None:
    events = summary["steps"].get(row.step_key, {}).get("events", [])
    if not events:
        if (
            row.status != "pending"
            or row.attempt_count != 0
            or row.receipt_sha256 is not None
            or row.next_retry_at_utc is not None
            or row.started_at_utc is not None
            or row.completed_at_utc is not None
        ):
            raise OrchestrationRepositoryError("orchestrator_step_summary_row_mismatch")
        return
    last = events[-1]
    if (
        row.status != last["status"]
        or row.attempt_count != last["attempt"]
        or row.receipt_sha256 != last["receipt_sha256"]
        or row.next_retry_at_utc != last["next_retry_at_utc"]
    ):
        raise OrchestrationRepositoryError("orchestrator_step_summary_row_mismatch")
    first_running = next(
        (event for event in events if event["status"] == "running"), None
    )
    if (first_running is None and row.started_at_utc is not None) or (
        first_running is not None and row.started_at_utc != first_running["at_utc"]
    ):
        raise OrchestrationRepositoryError("orchestrator_step_summary_row_mismatch")
    if row.status in {"running", "deferred"} and row.completed_at_utc is not None:
        raise OrchestrationRepositoryError("orchestrator_step_summary_row_mismatch")
    if (
        row.status in {"succeeded", "failed", "skipped"}
        and row.completed_at_utc != last["at_utc"]
    ):
        raise OrchestrationRepositoryError("orchestrator_step_summary_row_mismatch")


def _append_step_event(
    step_key: str,
    raw: str,
    attempt: int,
    status: str,
    at_utc: str,
    counts: Mapping[str, int],
    receipt_sha256: str | None,
    evidence_code: str | None,
    retry: str | None,
) -> str:
    parsed = _validated_step_summary(raw)
    events = parsed["steps"].setdefault(step_key, {"events": []})["events"]
    if len(events) >= 32 or attempt > 16:
        raise OrchestrationRepositoryError("orchestrator_result_summary_limit")
    events.append(
        {
            "attempt": attempt,
            "status": status,
            "at_utc": at_utc,
            "counts": dict(counts),
            "receipt_sha256": receipt_sha256,
            "evidence_code": evidence_code
            or ("receipt_received" if receipt_sha256 else None),
            "next_retry_at_utc": retry,
        }
    )
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"))


def _same_step_event(
    raw: str,
    step_key: str,
    status: str,
    at_utc: str,
    receipt: str | None,
    counts: Mapping[str, int],
    evidence: str | None,
    retry: str | None,
) -> bool:
    parsed = _validated_step_summary(raw)
    events = parsed["steps"].get(step_key, {}).get("events", [])
    if not events:
        return receipt is None and not counts and evidence is None and retry is None
    event = events[-1]
    return event == {
        "attempt": event["attempt"],
        "status": status,
        "at_utc": at_utc,
        "counts": dict(counts),
        "receipt_sha256": receipt,
        "evidence_code": evidence or ("receipt_received" if receipt else None),
        "next_retry_at_utc": retry,
    }


def _higher_severity(left: str, right: str) -> str:
    levels = {"info": 0, "warning": 1, "error": 2, "critical": 3}
    return left if levels[left] >= levels[right] else right


def _transition(table, current: str, requested: str, label: str) -> None:
    if requested == current:
        return
    if requested not in table.get(current, set()):
        raise OrchestrationRepositoryError(f"{label}_transition_invalid")
