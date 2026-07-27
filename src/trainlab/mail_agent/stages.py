"""Concrete, one-shot Mail Agent stages.

The stages deliberately contain no environment discovery.  They receive the
already constructed, restricted Gmail adapter and the controlled Mail runner
from :mod:`runtime`.  This keeps the public application service testable and
prevents a ``status`` request from accidentally constructing an external
dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Protocol

from .contracts import MailCounts, MailReceipt, MailRequest, utc_now
from .delivery import MailResponseDeliveryService
from .delivery_repository import MailDeliveryRepository
from .fact_gate import FactGate
from .poll import MailPollService
from .publisher import MailResponsePublisher
from .recovery import DeliveryCandidate, reconcile_unknown_delivery, recover_label_only
from .repository import MailRepository


class MailGenerationRunner(Protocol):
    def generate(
        self, context: dict[str, Any], *, invocation_id: str,
        regeneration_reason: str | None = None,
    ) -> Any: ...


def _failure(request: MailRequest, code: str, *, stage: str = "runtime") -> MailReceipt:
    run_key = request.run_key if request.mode == "status" and request.run_key else request.stable_run_key
    return MailReceipt(
        run_key=run_key, invocation_id=request.invocation_id, mode=request.mode,
        status="failed", counts=MailCounts(failed=1),
        errors=({"stage": stage, "code": code, "summary": "mail stage did not complete"},),
        started_at_utc=request.requested_at_utc, completed_at_utc=utc_now(),
    )


@dataclass(frozen=True)
class MissingDependencyStage:
    """A typed fail-closed stage used when no current-environment adapter exists."""

    code: str = "mail_environment_adapter_unavailable"

    def execute(self, request: MailRequest) -> MailReceipt:
        return _failure(request, self.code, stage="prepare")


@dataclass
class PollStage:
    service: MailPollService

    def execute(self, request: MailRequest) -> MailReceipt:
        return self.service.execute(request)


@dataclass
class QueueStage:
    repository: MailRepository

    def queued_message_ids(self, *, subject_id: int, limit: int) -> tuple[str, ...]:
        # The application contract intentionally deals in provider IDs; the
        # integer primary key never leaves the persistence boundary.
        ids = self.repository.select_queued_messages(subject_id, limit=limit)
        if not ids:
            return ()
        placeholders = ",".join("?" for _ in ids)
        rows = self.repository.connection.execute(
            f"SELECT id,provider_message_id FROM mail_messages WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        values = {int(row["id"]): row["provider_message_id"] for row in rows}
        result = tuple(values.get(identifier) for identifier in ids)
        if any(not isinstance(item, str) or not item for item in result):
            raise RuntimeError("mail_runtime_queue_integrity_invalid")
        return result  # type: ignore[return-value]


@dataclass
class StatusStage:
    repository: MailRepository

    def execute(self, request: MailRequest) -> MailReceipt:
        # This is deliberately repository-only: no adapter, runner, lock, or
        # provider construction belongs in status.
        try:
            run = self.repository.status(request)
        except Exception:
            return _failure(request, "mail_status_unavailable", stage="status")
        if run is None:
            return MailReceipt(
                run_key=request.run_key or request.stable_run_key,
                invocation_id=request.invocation_id, mode="status", status="unchanged",
                started_at_utc=request.requested_at_utc, completed_at_utc=utc_now(),
            )
        status = "succeeded" if run.status == "succeeded" else run.status
        if status not in {"succeeded", "partial", "deferred", "rejected", "failed"}:
            return _failure(request, "mail_status_invalid", stage="status")
        return MailReceipt(
            run_key=request.run_key or request.stable_run_key,
            mail_agent_run_id=str(run.id), invocation_id=request.invocation_id,
            mode="status", status=status, started_at_utc=request.requested_at_utc,
            completed_at_utc=utc_now(),
        )


@dataclass
class ProcessStage:
    repository: MailRepository
    context_builder: Any
    runner: MailGenerationRunner
    gate: FactGate
    publisher: MailResponsePublisher
    local_today: Callable[[], str]

    def execute(self, request: MailRequest) -> MailReceipt:
        try:
            row = self.repository.connection.execute(
                "SELECT m.id,m.processing_state FROM mail_messages m JOIN mail_threads t ON t.id=m.mail_thread_id "
                "WHERE m.provider_message_id=? AND t.subject_id=?",
                (request.mail_message_ids[0], request.subject_id),
            ).fetchone()
            if row is None:
                return _failure(request, "mail_process_message_not_found", stage="process")
            message_id = int(row["id"])
            # M4-14 owns validation/binding of the returned analysis artifact.
            # This composition root must never promote an awaiting message back
            # to queued merely because a caller supplied a string identifier.
            if row["processing_state"] == "awaiting_analysis":
                return self._dependency_wait(request, message_id, None)
            if row["processing_state"] not in {"queued", "awaiting_analysis"}:
                return MailReceipt(
                    run_key=request.stable_run_key, invocation_id=request.invocation_id,
                    mode="process", status="unchanged", processed_message_ids=request.mail_message_ids,
                    started_at_utc=request.requested_at_utc, completed_at_utc=utc_now(),
                )
            run = self.repository.start_or_resume_run(request)
            context = self.context_builder.build(
                run_id=run.id, subject_id=request.subject_id, trigger_message_id=message_id,
                as_of_local_date=self.local_today(),
            ).payload
            # Context construction is read-only.  Only after it has succeeded
            # do we claim the message for generation.
            self.repository.set_message_processing_state(request.subject_id, message_id, "analyzing")
            generation = self.runner.generate(
                context, invocation_id=request.invocation_id,
                regeneration_reason=request.regeneration_reason_code,
            )
            decision = self.repository.gate_mail_result(
                run.id, generation.result, context, gate=self.gate,
            )
            if decision.status == "dependency_wait":
                return self._dependency_wait(request, message_id, decision.reason_event_id, run_id=run.id)
            published = self.publisher.publish(decision, context, generation.result)
            self.repository.finish_run(run.id, "succeeded")
            return MailReceipt(
                run_key=request.stable_run_key, mail_agent_run_id=str(run.id),
                invocation_id=request.invocation_id, mode="process", status="unchanged" if published.unchanged else "succeeded",
                counts=MailCounts(processed=1, responses_accepted=0 if published.unchanged else 1),
                processed_message_ids=request.mail_message_ids,
                mail_response_artifact_ids=(str(published.response_artifact_id),),
                mail_delivery_ids=(str(published.delivery_id),),
                next_action="none", started_at_utc=request.requested_at_utc, completed_at_utc=utc_now(),
            )
        except Exception as error:
            return _failure(request, self._code(error), stage="process")

    def _dependency_wait(
        self, request: MailRequest, message_id: int, reason_event_id: int | None, *, run_id: int | None = None
    ) -> MailReceipt:
        pending = {"kind": "plan_revision", "mail_message_id": str(message_id)}
        if reason_event_id is not None:
            pending["reason_event_id"] = str(reason_event_id)
        if run_id is not None:
            self.repository.finish_run(run_id, "deferred")
        return MailReceipt(
            run_key=request.stable_run_key, mail_agent_run_id=None if run_id is None else str(run_id),
            invocation_id=request.invocation_id, mode="process", status="deferred",
            counts=MailCounts(deferred=1), processed_message_ids=request.mail_message_ids,
            pending_dependencies=(pending,), next_action="invoke_analysis",
            started_at_utc=request.requested_at_utc, completed_at_utc=utc_now(),
        )

    @staticmethod
    def _code(error: Exception) -> str:
        value = getattr(error, "code", None)
        return value if isinstance(value, str) and value.startswith("mail_") else "mail_process_failed"


@dataclass
class DeliveryStage:
    service: MailResponseDeliveryService

    def execute(self, request: MailRequest) -> MailReceipt:
        try:
            response_id = int(request.mail_response_artifact_ids[0])
            if response_id <= 0:
                raise ValueError
            result = self.service.deliver(subject_id=request.subject_id, response_artifact_id=response_id)
        except Exception as error:
            return _failure(request, getattr(error, "code", "mail_delivery_failed"), stage="delivery")
        status = (
            "succeeded"
            if result.status == "sent"
            else "unchanged"
            if result.status == "already_sent"
            else "auth_required"
            if result.error_code == "auth_required"
            else "rejected"
            if result.error_code == "forbidden"
            else "deferred"
            if result.status in {"label_pending", "delivery_unknown"}
            else "rejected"
        )
        counts = MailCounts(
            deliveries_sent=1 if result.status == "sent" else 0,
            deliveries_already_sent=1 if result.status == "already_sent" else 0,
            deferred=1 if status == "deferred" else 0,
            failed=1 if status in {"auth_required", "rejected"} else 0,
        )
        return MailReceipt(
            run_key=request.stable_run_key, invocation_id=request.invocation_id,
            mode="deliver_response", status=status, counts=counts,
            mail_response_artifact_ids=request.mail_response_artifact_ids,
            mail_delivery_ids=(str(result.delivery_id),),
            next_action=(
                "reauthenticate"
                if status == "auth_required"
                else "operator_review"
                if status == "rejected"
                else result.next_action
            ),
            errors=() if result.error_code is None else ({"stage": "delivery", "code": result.error_code, "summary": "delivery requires recovery"},),
            started_at_utc=request.requested_at_utc, completed_at_utc=utc_now(),
        )


@dataclass
class PreparedStage:
    """Verify the self identity before a stage can mutate delivery state."""

    stage: Any
    repository: MailRepository
    adapter: Any
    identity_sink: Any | None = None

    def execute(self, request: MailRequest) -> MailReceipt:
        try:
            self.adapter.prepare(self.repository.connection, request.subject_id)
            identity_id = getattr(self.adapter, "verified_identity_id", None)
            if not isinstance(identity_id, int) or identity_id <= 0:
                raise RuntimeError("mail_delivery_identity_unverified")
            if self.identity_sink is not None:
                self.identity_sink.verified_identity_id = identity_id
        except Exception as error:
            return _failure(request, getattr(error, "code", "mail_delivery_identity_unverified"), stage="prepare")
        return self.stage.execute(request)


@dataclass
class ReconcileStage:
    """Conservative recovery boundary.

    The delivery service itself never resends unknown outcomes.  Until the
    environment adapter supplies an exact search result, reconciliation is a
    deterministic defer to the scheduler rather than a guessed send.
    """

    repository: MailRepository
    delivery_repository: MailDeliveryRepository
    adapter: Any

    def execute(self, request: MailRequest) -> MailReceipt:
        try:
            identity = self.adapter.prepare(self.repository.connection, request.subject_id)
            identity_id = getattr(self.adapter, "verified_identity_id", None)
            if not isinstance(identity_id, int) or identity_id <= 0:
                raise RuntimeError("mail_reconcile_identity_unverified")
            delivery_id = int(request.mail_delivery_ids[0]) if request.mail_delivery_ids else 0
            if delivery_id <= 0:
                raise ValueError("mail_reconcile_delivery_required")
            # The delivery id is part of the public reconcile request; this
            # private typed lookup does not broaden provider selection.
            target = self.delivery_repository._load_by_delivery_id(request.subject_id, delivery_id)
            visible = self.delivery_repository.load_accepted_delivery_target(
                subject_id=request.subject_id, response_artifact_id=target.response_artifact_id,
            )
            if visible is None:
                raise RuntimeError("mail_reconcile_delivery_not_found")
            if visible.delivery_status == "label_pending":
                decision = recover_label_only(
                    delivery_status=target.status, provider_message_id=self._stored_provider_message_id(delivery_id),
                )
                if decision.action != "apply_label" or decision.provider_message_id is None:
                    return self._deferred(request, delivery_id, decision.code)
                self.adapter.apply_trainlab_label(
                    message_id=decision.provider_message_id, thread_id=target.provider_thread_id,
                )
                self.delivery_repository.record_provider_receipt(
                    request.subject_id, delivery_id, identity_id,
                    provider_message_id=decision.provider_message_id,
                    provider_thread_id=target.provider_thread_id, sent_at_utc=utc_now(),
                    status=target.status, label_applied=True,
                )
                return self._success(request, delivery_id, "succeeded")
            if target.status != "delivery_unknown":
                return self._success(request, delivery_id, "unchanged")
            candidates = tuple(
                DeliveryCandidate(
                    str(item.get("message_id", "")), str(item.get("thread_id", "")), target.idempotency_key
                )
                for item in self.adapter.search_run_id(run_id=target.idempotency_key)
                if isinstance(item, dict)
            )
            decision = reconcile_unknown_delivery(
                expected_run_id=target.idempotency_key, expected_thread_id=target.provider_thread_id,
                candidates=candidates,
            )
            if decision.action != "record_sent" or decision.provider_message_id is None:
                return self._deferred(request, delivery_id, decision.code)
            self.adapter.apply_trainlab_label(
                message_id=decision.provider_message_id, thread_id=target.provider_thread_id,
            )
            self.delivery_repository.reconcile_provider_receipt(
                request.subject_id, delivery_id, identity_id,
                provider_message_id=decision.provider_message_id,
                provider_thread_id=target.provider_thread_id, sent_at_utc=utc_now(),
            )
            return self._success(request, delivery_id, "succeeded")
        except Exception as error:
            return self._deferred(request, request.mail_delivery_ids[0] if request.mail_delivery_ids else "", getattr(error, "code", "mail_reconcile_failed"))

    def _stored_provider_message_id(self, delivery_id: int) -> str | None:
        row = self.repository.connection.execute(
            "SELECT m.provider_message_id FROM mail_deliveries d JOIN mail_messages m ON m.id=d.mail_message_id WHERE d.id=?",
            (delivery_id,),
        ).fetchone()
        return None if row is None or not isinstance(row[0], str) else row[0]

    @staticmethod
    def _success(request: MailRequest, delivery_id: int, status: str) -> MailReceipt:
        return MailReceipt(
            run_key=request.stable_run_key, invocation_id=request.invocation_id, mode="reconcile",
            status=status, mail_delivery_ids=(str(delivery_id),), next_action="none",
            started_at_utc=request.requested_at_utc, completed_at_utc=utc_now(),
        )

    @staticmethod
    def _deferred(request: MailRequest, delivery_id: object, code: object) -> MailReceipt:
        safe = (
            code
            if isinstance(code, str)
            and (code.startswith("mail_") or code in {"delivery_not_found", "duplicate_delivery_conflict", "label_recovery_evidence_missing"})
            else "mail_reconcile_failed"
        )
        return MailReceipt(
            run_key=request.stable_run_key, invocation_id=request.invocation_id, mode="reconcile",
            status="deferred", counts=MailCounts(deferred=1),
            mail_delivery_ids=() if not delivery_id else (str(delivery_id),), next_action="operator_review",
            errors=({"stage": "reconcile", "code": safe, "summary": "delivery recovery requires review"},),
            started_at_utc=request.requested_at_utc, completed_at_utc=utc_now(),
        )
