"""Fail-closed application service for the fifth-layer public Python API.

The service is intentionally a small adapter: it accepts the frozen, data-free
``WorkflowRequest`` and delegates to injected workflow services.  It neither
opens a provider connection nor owns any Layer 1--4 table.  A deployment wires
the adapters and its Layer-5-only receipt store explicitly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from .analysis_workflows import AnalysisWorkflowRequest, AnalysisWorkflowResult
from .contracts import WorkflowReceipt, WorkflowRequest, WorkflowStepReceipt
from .mail_workflow import MailWorkflowOutcome


class OrchestrationApplicationError(ValueError):
    """The public request cannot be safely routed."""


class SubjectAuthorizer(Protocol):
    """Read-only active-subject projection supplied by the composition root."""

    def is_active(self, subject_id: str) -> bool: ...
    def workflow_identity(self, subject_id: str) -> str: ...


class ReceiptStore(Protocol):
    """Layer-5-only durable receipt sink; it must not write business tables."""

    def record_orchestration_receipt(
        self, request: WorkflowRequest, receipt: WorkflowReceipt
    ) -> None: ...


class AnalysisWorkflowExecutor(Protocol):
    def execute(self, request: AnalysisWorkflowRequest) -> AnalysisWorkflowResult: ...


class MailWorkflowExecutor(Protocol):
    def execute(
        self, *, subject_id: int, invocation_id: str, max_items: int,
        deadline_seconds: int,
    ) -> MailWorkflowOutcome: ...


class HealthWorkflowExecutor(Protocol):
    """A read-only probe adapter plus ``HealthMonitor`` persistence boundary."""

    def execute(self, request: WorkflowRequest) -> "HealthWorkflowOutcome": ...


@dataclass(frozen=True, slots=True)
class HealthWorkflowOutcome:
    status: str
    next_action: str
    incident_ids: tuple[str, ...] = ()
    warnings: tuple[dict[str, str], ...] = ()
    errors: tuple[dict[str, str], ...] = ()
    next_retry_at_utc: str | None = None


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$")
_SUBJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_MAIL_SUBJECT = re.compile(r"^[1-9][0-9]{0,18}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_SINGAPORE = ZoneInfo("Asia/Singapore")
_WORKFLOW_STATUSES = frozenset({
    "succeeded", "partial", "deferred", "attention_required", "failed",
})
_STEP_STATUSES = frozenset({
    "pending", "running", "succeeded", "unchanged", "partial", "deferred",
    "lock_busy", "auth_required", "rejected", "failed", "skipped",
})
_SAFE_CODES = frozenset({
    "orchestration_dependency_missing", "orchestration_subject_inactive",
    "orchestration_request_invalid", "orchestration_execution_failed",
    "orchestration_receipt_persistence_failed", "orchestration_outcome_invalid",
})


def _parse_utc(value: object, code: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise OrchestrationApplicationError(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OrchestrationApplicationError(code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(None):
        raise OrchestrationApplicationError(code)
    return parsed.astimezone(UTC)


def _date(value: object) -> date:
    if not isinstance(value, str):
        raise OrchestrationApplicationError("orchestration_request_invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise OrchestrationApplicationError("orchestration_request_invalid") from exc
    if parsed.isoformat() != value:
        raise OrchestrationApplicationError("orchestration_request_invalid")
    return parsed


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _safe_error(code: str) -> tuple[dict[str, str], ...]:
    return ({"code": code if code in _SAFE_CODES else "orchestration_execution_failed", "summary": "workflow could not be completed safely"},)


class OrchestrationTool:
    """Route a frozen request to an injected, bounded fifth-layer workflow.

    ``None`` adapters are deliberate: the service returns a data-free failure
    instead of silently selecting a local executable, configuration, recipient,
    or provider transport.
    """

    def __init__(
        self,
        *,
        clock: callable,
        subject_authorizer: SubjectAuthorizer | None,
        receipt_store: ReceiptStore | None,
        morning: AnalysisWorkflowExecutor | None = None,
        weekly: AnalysisWorkflowExecutor | None = None,
        mail: MailWorkflowExecutor | None = None,
        health_check: HealthWorkflowExecutor | None = None,
        mail_max_items: int = 100,
        mail_deadline_seconds: int = 120,
    ) -> None:
        if not isinstance(mail_max_items, int) or isinstance(mail_max_items, bool) or not 1 <= mail_max_items <= 10_000:
            raise OrchestrationApplicationError("orchestration_request_invalid")
        if not isinstance(mail_deadline_seconds, int) or isinstance(mail_deadline_seconds, bool) or not 1 <= mail_deadline_seconds <= 10_000:
            raise OrchestrationApplicationError("orchestration_request_invalid")
        self._clock = clock
        self._subjects = subject_authorizer
        self._store = receipt_store
        self._morning, self._weekly = morning, weekly
        self._mail, self._health = mail, health_check
        self._mail_max_items, self._mail_deadline_seconds = mail_max_items, mail_deadline_seconds

    def execute(self, request: WorkflowRequest) -> WorkflowReceipt:
        """Execute exactly one known workflow without accepting arbitrary inputs."""
        if type(request) is not WorkflowRequest:
            raise OrchestrationApplicationError("orchestration_request_invalid")
        now = self._now()
        try:
            self._validate(request, now)
            receipt = self._route(request, now)
        except OrchestrationApplicationError as error:
            receipt = self._failure(request, now, str(error))
        except Exception:
            # Provider/adaptor exception strings can contain account data or a
            # mail body.  They never cross this application boundary.
            receipt = self._failure(request, now, "orchestration_execution_failed")
        try:
            if self._store is None:
                raise OrchestrationApplicationError("orchestration_dependency_missing")
            self._store.record_orchestration_receipt(request, receipt)
        except Exception:
            receipt = self._failure(request, now, "orchestration_receipt_persistence_failed")
        return receipt

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != UTC.utcoffset(None):
            raise OrchestrationApplicationError("orchestration_request_invalid")
        return value.astimezone(UTC)

    def _validate(self, request: WorkflowRequest, now: datetime) -> None:
        if request.workflow_kind not in {"morning", "weekly", "mail", "health_check"}:
            raise OrchestrationApplicationError("orchestration_request_invalid")
        if request.trigger_kind not in {"scheduled", "recovery", "manual", "dependency"}:
            raise OrchestrationApplicationError("orchestration_request_invalid")
        if not isinstance(request.invocation_id, str) or _ID.fullmatch(request.invocation_id) is None:
            raise OrchestrationApplicationError("orchestration_request_invalid")
        if request.parent_workflow_run_id is not None and (
            not isinstance(request.parent_workflow_run_id, str) or _ID.fullmatch(request.parent_workflow_run_id) is None
        ):
            raise OrchestrationApplicationError("orchestration_request_invalid")
        if type(request.dependency_ids) is not tuple or len(request.dependency_ids) > 64 or len(set(request.dependency_ids)) != len(request.dependency_ids):
            raise OrchestrationApplicationError("orchestration_request_invalid")
        if any(not isinstance(item, str) or _ID.fullmatch(item) is None for item in request.dependency_ids):
            raise OrchestrationApplicationError("orchestration_request_invalid")
        requested = _parse_utc(request.requested_at_utc, "orchestration_request_invalid")
        deadline = _parse_utc(request.deadline_at_utc, "orchestration_request_invalid")
        if requested > deadline or deadline < now:
            raise OrchestrationApplicationError("orchestration_request_invalid")
        if request.workflow_kind == "health_check":
            if request.subject_id is not None or request.logical_local_date is not None:
                raise OrchestrationApplicationError("orchestration_request_invalid")
            return
        if not isinstance(request.subject_id, str) or _SUBJECT.fullmatch(request.subject_id) is None:
            raise OrchestrationApplicationError("orchestration_request_invalid")
        if self._subjects is None or not self._subjects.is_active(request.subject_id):
            raise OrchestrationApplicationError("orchestration_subject_inactive")
        if request.workflow_kind == "mail":
            if request.logical_local_date is not None or _MAIL_SUBJECT.fullmatch(request.subject_id) is None:
                raise OrchestrationApplicationError("orchestration_request_invalid")
        else:
            logical = _date(request.logical_local_date)
            if requested.astimezone(_SINGAPORE).date() != logical:
                raise OrchestrationApplicationError("orchestration_request_invalid")
            if request.workflow_kind == "weekly" and logical.weekday() != 6:
                raise OrchestrationApplicationError("orchestration_request_invalid")

    def _route(self, request: WorkflowRequest, now: datetime) -> WorkflowReceipt:
        if self._store is None:
            raise OrchestrationApplicationError("orchestration_dependency_missing")
        if request.workflow_kind == "morning":
            if self._morning is None:
                raise OrchestrationApplicationError("orchestration_dependency_missing")
            outcome = self._morning.execute(self._analysis_request_instance(request, "morning"))
            return self._analysis_receipt(request, now, outcome)
        if request.workflow_kind == "weekly":
            if self._weekly is None:
                raise OrchestrationApplicationError("orchestration_dependency_missing")
            outcome = self._weekly.execute(self._analysis_request_instance(request, "sunday"))
            return self._analysis_receipt(request, now, outcome)
        if request.workflow_kind == "mail":
            if self._mail is None:
                raise OrchestrationApplicationError("orchestration_dependency_missing")
            outcome = self._mail.execute(subject_id=int(request.subject_id or "0"), invocation_id=request.invocation_id, max_items=self._mail_max_items, deadline_seconds=self._mail_deadline_seconds)
            return self._mail_receipt(request, now, outcome)
        if self._health is None:
            raise OrchestrationApplicationError("orchestration_dependency_missing")
        return self._health_receipt(request, now, self._health.execute(request))

    def _workflow_key(self, request: WorkflowRequest) -> str:
        if request.workflow_kind == "health_check":
            return f"health-check:{request.invocation_id}"
        assert request.subject_id is not None
        if self._subjects is None:
            raise OrchestrationApplicationError("orchestration_dependency_missing")
        identity = self._subjects.workflow_identity(request.subject_id)
        if not isinstance(identity, str) or _MAIL_SUBJECT.fullmatch(identity) is None:
            raise OrchestrationApplicationError("orchestration_subject_inactive")
        if request.trigger_kind == "manual":
            return f"manual:{request.workflow_kind}:{request.invocation_id}"
        if request.workflow_kind == "mail":
            return f"mail-poll:{identity}:{request.invocation_id}"
        assert request.logical_local_date is not None
        return f"{request.workflow_kind}:{identity}:{request.logical_local_date}"

    def _analysis_request_instance(
        self, request: WorkflowRequest, kind: str
    ) -> AnalysisWorkflowRequest:
        assert request.subject_id is not None and request.logical_local_date is not None
        return AnalysisWorkflowRequest(
            self._workflow_key(request), request.subject_id,
            request.logical_local_date,
            _parse_utc(request.requested_at_utc, "orchestration_request_invalid"),
            kind,  # type: ignore[arg-type]
        )

    def _base(self, request: WorkflowRequest, now: datetime, *, status: str, steps: tuple[WorkflowStepReceipt, ...] = (), next_action: str = "none", next_retry: str | None = None, incidents: tuple[str, ...] = (), warnings: tuple[dict[str, str], ...] = (), errors: tuple[dict[str, str], ...] = ()) -> WorkflowReceipt:
        return WorkflowReceipt(
            workflow_run_id=f"run:{self._workflow_key(request)}",
            workflow_key=self._workflow_key(request), workflow_kind=request.workflow_kind, status=status,  # type: ignore[arg-type]
            trigger_kind=request.trigger_kind, scheduled_at_utc=request.requested_at_utc if request.trigger_kind == "scheduled" else None,
            started_at_utc=_utc_text(now), completed_at_utc=_utc_text(now), logical_local_date=request.logical_local_date,
            steps=steps, next_action=next_action, next_retry_at_utc=next_retry,
            incident_ids=incidents, warnings=warnings, errors=errors,
        )

    def _analysis_receipt(self, request: WorkflowRequest, now: datetime, outcome: AnalysisWorkflowResult) -> WorkflowReceipt:
        if outcome.status not in _WORKFLOW_STATUSES or outcome.logical_local_date != request.logical_local_date:
            raise OrchestrationApplicationError("orchestration_outcome_invalid")
        steps = tuple(
            WorkflowStepReceipt(
                step_id=item.step_key, layer=item.layer, mode=item.mode,
                status=item.status if item.status in _STEP_STATUSES else "failed", downstream_run_id=None,
                downstream_invocation_id=item.invocation_id, receipt_sha256=item.receipt_sha256,
            ) for item in outcome.steps
        )
        if any(item.status == "failed" and source.status not in _STEP_STATUSES for item, source in zip(steps, outcome.steps)):
            raise OrchestrationApplicationError("orchestration_outcome_invalid")
        return self._base(request, now, status=outcome.status, steps=steps, next_action=outcome.next_action, next_retry=outcome.next_retry_at_utc)

    def _mail_receipt(self, request: WorkflowRequest, now: datetime, outcome: MailWorkflowOutcome) -> WorkflowReceipt:
        if outcome.status not in _WORKFLOW_STATUSES:
            raise OrchestrationApplicationError("orchestration_outcome_invalid")
        if len(outcome.calls) != len(outcome.receipt_sha256s) and outcome.status == "succeeded":
            raise OrchestrationApplicationError("orchestration_outcome_invalid")
        steps = tuple(
            WorkflowStepReceipt(
                step_id=f"mail:{index}", layer=call.layer, mode=call.mode,
                status="succeeded" if index < len(outcome.receipt_sha256s) else "pending",
                downstream_run_id=None, downstream_invocation_id=call.invocation_id,
                receipt_sha256=outcome.receipt_sha256s[index] if index < len(outcome.receipt_sha256s) else None,
            ) for index, call in enumerate(outcome.calls)
        )
        errors = _safe_error(outcome.error_code) if outcome.error_code else ()
        return self._base(request, now, status=outcome.status, steps=steps, next_action=outcome.next_action, errors=errors)

    def _health_receipt(self, request: WorkflowRequest, now: datetime, outcome: HealthWorkflowOutcome) -> WorkflowReceipt:
        if type(outcome) is not HealthWorkflowOutcome or outcome.status not in _WORKFLOW_STATUSES:
            raise OrchestrationApplicationError("orchestration_outcome_invalid")
        return self._base(request, now, status=outcome.status, next_action=outcome.next_action, next_retry=outcome.next_retry_at_utc, incidents=outcome.incident_ids, warnings=outcome.warnings, errors=outcome.errors)

    def _failure(self, request: WorkflowRequest, now: datetime, code: str) -> WorkflowReceipt:
        return self._base(request, now, status="failed", next_action="operator_review", errors=_safe_error(code))
