"""One-shot, dependency-injected fourth-layer application service.

No composition root lives here: production wiring of SQLite, Gmail MCP and the
Codex runner is deliberately deferred until all lower-level adapters are
available.  The service is nevertheless complete for offline integration
tests, and a missing composition fails closed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Callable, Protocol

from .contracts import MailCounts, MailReceipt, MailRequest, utc_now


class MailApplicationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MailStage(Protocol):
    def execute(self, request: MailRequest) -> MailReceipt: ...


class QueuedMessageSelector(Protocol):
    def queued_message_ids(self, *, subject_id: int, limit: int) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class MailApplicationStages:
    poll: MailStage
    process: MailStage
    deliver: MailStage
    reconcile: MailStage
    status: MailStage
    queue: QueuedMessageSelector


@dataclass(frozen=True, slots=True)
class MailApplicationPolicy:
    default_max_items: int = 20
    max_max_items: int = 200
    default_deadline_seconds: int = 60
    max_deadline_seconds: int = 900


def _safe_code(error: Exception) -> str:
    if isinstance(error, MailApplicationError):
        return error.code
    return "mail_application_stage_failed"


def _sum_counts(receipts: list[MailReceipt]) -> MailCounts:
    fields = MailCounts.__dataclass_fields__
    return MailCounts(**{name: sum(getattr(item.counts, name) for item in receipts) for name in fields})


class UnavailableMailApplicationService:
    """Safe production default until a composition root has all dependencies."""

    def execute(self, request: MailRequest) -> MailReceipt:
        run_key = request.run_key if request.mode == "status" and request.run_key else request.stable_run_key
        return MailReceipt(
            run_key=run_key,
            invocation_id=request.invocation_id,
            mode=request.mode,
            status="failed",
            errors=({"stage": "application", "code": "mail_application_dependencies_unavailable", "summary": "mail tool is not configured"},),
            started_at_utc=request.requested_at_utc,
            completed_at_utc=utc_now(),
        )


class MailApplicationService:
    """Stable API implementation for all six Mail Agent modes."""

    def __init__(
        self,
        stages: MailApplicationStages,
        *,
        policy: MailApplicationPolicy = MailApplicationPolicy(),
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        if (
            policy.default_max_items < 1
            or policy.max_max_items < policy.default_max_items
            or policy.default_deadline_seconds < 1
            or policy.max_deadline_seconds < policy.default_deadline_seconds
        ):
            raise MailApplicationError("mail_application_policy_invalid")
        self._stages = stages
        self._policy = policy
        self._monotonic = monotonic
        self._clock = clock

    def execute(self, request: MailRequest) -> MailReceipt:
        if request.mode == "run":
            return self._run(request)
        stage = {
            "poll": self._stages.poll,
            "process": self._stages.process,
            "deliver_response": self._stages.deliver,
            "reconcile": self._stages.reconcile,
            "status": self._stages.status,
        }.get(request.mode)
        if stage is None:
            raise MailApplicationError("mail_application_mode_invalid")
        return self._execute_stage(stage, request)

    def _execute_stage(self, stage: MailStage, request: MailRequest) -> MailReceipt:
        try:
            receipt = stage.execute(request)
        except Exception as error:
            return self._failed_receipt(request, "stage", _safe_code(error))
        expected = request.run_key if request.mode == "status" and request.run_key else request.stable_run_key
        if (
            not isinstance(receipt, MailReceipt)
            or receipt.mode != request.mode
            or receipt.invocation_id != request.invocation_id
            or receipt.run_key != expected
        ):
            return self._failed_receipt(request, "stage", "mail_application_stage_receipt_invalid")
        return receipt

    def _run(self, request: MailRequest) -> MailReceipt:
        started = self._clock()
        begun = self._monotonic()
        max_items, deadline = self._run_limits(request)
        receipts: list[MailReceipt] = []
        errors: list[dict[str, str]] = []
        processed: list[str] = []
        response_ids: list[str] = []
        delivery_ids: list[str] = []
        pending: list[dict[str, str]] = []
        poll_state: list[dict[str, str]] = []

        poll_request = self._child(request, "poll")
        poll_receipt = self._execute_stage(self._stages.poll, poll_request)
        receipts.append(poll_receipt)
        self._collect(poll_receipt, processed, response_ids, delivery_ids, pending, poll_state, errors)
        if poll_receipt.status in {"failed", "auth_required", "lock_busy", "rejected"}:
            return self._run_receipt(request, started, receipts, processed, response_ids, delivery_ids, pending, poll_state, errors)

        if self._deadline_reached(begun, deadline):
            errors.append({"stage": "run", "code": "mail_run_deadline_reached", "summary": "mail run stopped at deadline"})
            return self._run_receipt(request, started, receipts, processed, response_ids, delivery_ids, pending, poll_state, errors, force_partial=True)
        try:
            queued = self._stages.queue.queued_message_ids(subject_id=request.subject_id, limit=max_items)
        except Exception as error:
            errors.append({"stage": "queue", "code": _safe_code(error), "summary": "queued items unavailable"})
            return self._run_receipt(request, started, receipts, processed, response_ids, delivery_ids, pending, poll_state, errors, force_partial=True)
        if not isinstance(queued, tuple) or any(not isinstance(item, str) or not item for item in queued):
            errors.append({"stage": "queue", "code": "mail_application_queue_invalid", "summary": "queued items unavailable"})
            return self._run_receipt(request, started, receipts, processed, response_ids, delivery_ids, pending, poll_state, errors, force_partial=True)

        # The selector is required to return a stable provider/order key.  Sort
        # defensively so a nondeterministic storage implementation cannot alter
        # which item is processed before a deadline.
        for message_id in sorted(queued)[:max_items]:
            if self._deadline_reached(begun, deadline):
                errors.append({"stage": "run", "code": "mail_run_deadline_reached", "summary": "mail run stopped at deadline"})
                break
            process_request = self._child(request, "process", mail_message_ids=(message_id,))
            process_receipt = self._execute_stage(self._stages.process, process_request)
            receipts.append(process_receipt)
            self._collect(process_receipt, processed, response_ids, delivery_ids, pending, poll_state, errors)
            if process_receipt.status not in {"succeeded", "unchanged", "partial"}:
                continue
            for response_id in process_receipt.mail_response_artifact_ids:
                if self._deadline_reached(begun, deadline):
                    errors.append({"stage": "run", "code": "mail_run_deadline_reached", "summary": "mail run stopped at deadline"})
                    break
                delivery_request = self._child(request, "deliver_response", mail_response_artifact_ids=(response_id,))
                delivery_receipt = self._execute_stage(self._stages.deliver, delivery_request)
                receipts.append(delivery_receipt)
                self._collect(delivery_receipt, processed, response_ids, delivery_ids, pending, poll_state, errors)
                if delivery_receipt.next_action == "reconcile_delivery":
                    for delivery_id in delivery_receipt.mail_delivery_ids:
                        reconcile_request = self._child(request, "reconcile", mail_delivery_ids=(delivery_id,))
                        reconcile_receipt = self._execute_stage(self._stages.reconcile, reconcile_request)
                        receipts.append(reconcile_receipt)
                        self._collect(reconcile_receipt, processed, response_ids, delivery_ids, pending, poll_state, errors)
        return self._run_receipt(request, started, receipts, processed, response_ids, delivery_ids, pending, poll_state, errors, force_partial=self._deadline_reached(begun, deadline))

    def _run_limits(self, request: MailRequest) -> tuple[int, int]:
        max_items = self._policy.default_max_items if request.max_items is None else request.max_items
        deadline = self._policy.default_deadline_seconds if request.deadline_seconds is None else request.deadline_seconds
        if not isinstance(max_items, int) or not 1 <= max_items <= self._policy.max_max_items:
            raise MailApplicationError("mail_run_max_items_invalid")
        if not isinstance(deadline, int) or not 1 <= deadline <= self._policy.max_deadline_seconds:
            raise MailApplicationError("mail_run_deadline_invalid")
        return max_items, deadline

    @staticmethod
    def _child(request: MailRequest, mode: str, **values: object) -> MailRequest:
        # Child IDs are bounded by the public identifier contract and never
        # equal the parent invocation, avoiding one run's persistent record
        # masquerading as a child-stage replay.
        invocation = f"{request.invocation_id}:{mode}"
        return MailRequest(
            mode=mode, subject_id=request.subject_id, invocation_id=invocation,
            requested_at_utc=request.requested_at_utc, **values,
        )  # type: ignore[arg-type]

    def _deadline_reached(self, started: float, deadline_seconds: int) -> bool:
        return self._monotonic() - started >= deadline_seconds

    @staticmethod
    def _collect(receipt: MailReceipt, processed: list[str], responses: list[str], deliveries: list[str], pending: list[dict[str, str]], poll_state: list[dict[str, str]], errors: list[dict[str, str]]) -> None:
        processed.extend(receipt.processed_message_ids)
        responses.extend(receipt.mail_response_artifact_ids)
        deliveries.extend(receipt.mail_delivery_ids)
        pending.extend(receipt.pending_dependencies)
        poll_state.extend(receipt.poll_state)
        errors.extend(receipt.errors)

    def _run_receipt(self, request: MailRequest, started: str, receipts: list[MailReceipt], processed: list[str], responses: list[str], deliveries: list[str], pending: list[dict[str, str]], poll_state: list[dict[str, str]], errors: list[dict[str, str]], *, force_partial: bool = False) -> MailReceipt:
        counts = _sum_counts(receipts)
        statuses = {receipt.status for receipt in receipts}
        if force_partial or (statuses - {"succeeded", "unchanged"} and statuses & {"succeeded", "unchanged"}):
            status = "partial"
        elif "auth_required" in statuses:
            status = "auth_required"
        elif "lock_busy" in statuses:
            status = "lock_busy"
        elif "failed" in statuses:
            status = "failed"
        elif "rejected" in statuses:
            status = "rejected"
        elif "deferred" in statuses:
            status = "deferred"
        elif statuses == {"unchanged"}:
            status = "unchanged"
        else:
            status = "succeeded"
        next_action = "none"
        for candidate in ("operator_review", "reauthenticate", "reconcile_delivery", "invoke_analysis", "resume_processing", "continue_poll"):
            if any(receipt.next_action == candidate for receipt in receipts):
                next_action = candidate
                break
        if force_partial:
            next_action = "resume_processing"
        return MailReceipt(
            run_key=request.stable_run_key,
            invocation_id=request.invocation_id,
            mode="run",
            status=status,
            counts=counts,
            processed_message_ids=tuple(dict.fromkeys(processed)),
            mail_response_artifact_ids=tuple(dict.fromkeys(responses)),
            mail_delivery_ids=tuple(dict.fromkeys(deliveries)),
            pending_dependencies=tuple(pending),
            poll_state=tuple(poll_state),
            next_action=next_action,
            warnings=(),
            errors=tuple(errors),
            started_at_utc=started,
            completed_at_utc=self._clock(),
        )

    def _failed_receipt(self, request: MailRequest, stage: str, code: str) -> MailReceipt:
        run_key = request.run_key if request.mode == "status" and request.run_key else request.stable_run_key
        return MailReceipt(
            run_key=run_key, invocation_id=request.invocation_id, mode=request.mode,
            status="failed", counts=MailCounts(failed=1),
            errors=({"stage": stage, "code": code, "summary": "mail stage did not complete"},),
            started_at_utc=request.requested_at_utc, completed_at_utc=self._clock(),
        )
