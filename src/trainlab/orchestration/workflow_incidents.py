"""Conservative workflow-failure incident lifecycle coordination."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Protocol

from .evidence_codes import DOWNSTREAM_FAILURE_EVIDENCE_CODES
from .repository import IncidentRecord, WorkflowRunRecord
from .supervisor import BusinessIncidentEvents


class WorkflowIncidentRepository(Protocol):
    def get_workflow(self, workflow_key: str) -> WorkflowRunRecord | None: ...

    def record_incident(self, **values: object) -> IncidentRecord: ...

    def resolve_retryable_workflow_failures(
        self, workflow_key: str, *, at_utc: datetime
    ) -> tuple[IncidentRecord, ...]: ...


_WORKFLOW_KINDS = frozenset({"morning", "weekly", "mail", "health_check"})
_AUTOMATIC_RETRY_KINDS = frozenset({"mail", "health_check"})


def _failure_code(outcome: dict[str, object]) -> str:
    errors = outcome.get("errors")
    if isinstance(errors, list):
        for error in errors:
            if (
                isinstance(error, dict)
                and error.get("code") in DOWNSTREAM_FAILURE_EVIDENCE_CODES
            ):
                return str(error["code"])
    return "workflow_execution_failed"


class WorkflowIncidentCoordinator:
    """Open failed-workflow incidents and close only proven retry recoveries."""

    def __init__(self, repository: WorkflowIncidentRepository) -> None:
        self._repository = repository

    def observe(
        self,
        *,
        workflow_key: str,
        workflow_kind: str,
        outcome: object,
        seen_at_utc: datetime,
    ) -> BusinessIncidentEvents | None:
        if not isinstance(outcome, dict) or workflow_kind not in _WORKFLOW_KINDS:
            return None
        status = outcome.get("status")
        if status not in {"failed", "succeeded"}:
            return None
        workflow = self._repository.get_workflow(workflow_key)
        if workflow is None or workflow.workflow_kind != workflow_kind:
            raise RuntimeError("supervisor_workflow_outcome_not_persisted")
        if status == "succeeded":
            recovered = self._repository.resolve_retryable_workflow_failures(
                workflow_key, at_utc=seen_at_utc
            )
            return BusinessIncidentEvents(
                recovered=tuple(item.incident_key for item in recovered)
            )

        digest = hashlib.sha256(workflow_key.encode("utf-8")).hexdigest()[:32]
        incident_key = f"workflow:failed:{workflow_kind}:{digest}"
        failure_code = _failure_code(outcome)
        self._repository.record_incident(
            incident_key=incident_key,
            category="workflow",
            severity="error",
            seen_at_utc=seen_at_utc,
            error_code=failure_code,
            error_summary=failure_code,
            next_action=(
                "retry"
                if workflow_kind in _AUTOMATIC_RETRY_KINDS
                else "operator_review"
            ),
            related_workflow_run_id=workflow.id,
        )
        return BusinessIncidentEvents(opened=(incident_key,))
