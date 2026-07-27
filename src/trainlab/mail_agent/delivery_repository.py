"""M4-10 durable delivery state for an already accepted mail response.

Provider calls stay outside this module.  It owns only short SQLite
transactions that claim a precise response revision and persist a provider
receipt without ever re-rendering or re-generating content.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from .delivery import AcceptedDeliveryTarget as ServiceDeliveryTarget
from .repository import EventDraft, MailRepository, MailRepositoryError, utc_now


class MailDeliveryRepositoryError(RuntimeError):
    """Stable, content-free delivery persistence failure."""


@dataclass(frozen=True)
class AcceptedDeliveryTarget:
    delivery_id: int
    subject_id: int
    response_artifact_id: int
    trigger_message_id: int
    trigger_provider_message_id: str
    provider_thread_id: str
    idempotency_key: str
    run_key: str
    user_visible_text: str
    response_kind: str
    status: str


@dataclass(frozen=True)
class PersistedDeliveryReceipt:
    delivery_id: int
    outbound_mail_message_id: int
    status: str
    label_pending: bool


class MailDeliveryRepository:
    """Repository adapter for the M4-10 preflight/send/receipt boundary."""

    def __init__(
        self,
        repository: MailRepository,
        *,
        verified_identity_id: int | None = None,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        self.repository = repository
        self.connection = repository.connection
        self.verified_identity_id = verified_identity_id
        self._clock = clock

    def load_accepted_delivery_target(
        self, *, subject_id: int, response_artifact_id: int
    ) -> ServiceDeliveryTarget | None:
        rows = self.connection.execute(
            "SELECT d.id FROM mail_deliveries d "
            "JOIN mail_delivery_artifacts a ON a.mail_delivery_id=d.id "
            "WHERE a.mail_response_artifact_id=? AND a.content_role='mail_response' "
            "AND a.ordinal=0",
            (response_artifact_id,),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise MailDeliveryRepositoryError("mail_delivery_target_ambiguous")
        target = self._load_by_delivery_id(subject_id, int(rows[0]["id"]))
        label_pending = self.connection.execute(
            "SELECT 1 FROM mail_agent_items WHERE mail_delivery_id=? "
            "AND stage='verify' AND status='deferred' AND error_code='label_pending'",
            (target.delivery_id,),
        ).fetchone()
        identity_verified = False
        if self.verified_identity_id is not None:
            try:
                self._assert_identity(subject_id, self.verified_identity_id)
            except MailDeliveryRepositoryError:
                identity_verified = False
            else:
                identity_verified = True
        return ServiceDeliveryTarget(
            subject_id=target.subject_id,
            response_artifact_id=target.response_artifact_id,
            response_kind=target.response_kind,
            user_visible_text=target.user_visible_text,
            delivery_id=target.delivery_id,
            idempotency_key=target.idempotency_key,
            provider_thread_id=target.provider_thread_id,
            in_reply_to_provider_message_id=target.trigger_provider_message_id,
            delivery_status="label_pending" if label_pending else target.status,
            thread_verified=True,
            authenticated_self_verified=identity_verified,
        )

    def _load_by_delivery_id(
        self, subject_id: int, delivery_id: int
    ) -> AcceptedDeliveryTarget:
        if not isinstance(subject_id, int) or subject_id <= 0 or not isinstance(delivery_id, int) or delivery_id <= 0:
            raise MailDeliveryRepositoryError("mail_delivery_target_invalid")
        self.repository._verify_foundation_schema()
        rows = self.connection.execute(
            "SELECT d.id,d.status,d.idempotency_key,d.provider_thread_id,d.related_run_key,"
            "r.id AS response_id,r.subject_id,r.in_reply_to_mail_message_id,"
            "trigger.provider_message_id AS trigger_provider_message_id,"
            "r.user_visible_text,r.response_kind,"
            "t.provider_thread_id AS response_thread_id,mr.run_key "
            "FROM mail_deliveries d "
            "JOIN mail_delivery_artifacts a ON a.mail_delivery_id=d.id "
            "AND a.content_role='mail_response' AND a.ordinal=0 "
            "JOIN mail_response_artifacts r ON r.id=a.mail_response_artifact_id "
            "JOIN mail_messages trigger ON trigger.id=r.in_reply_to_mail_message_id "
            "JOIN mail_agent_runs mr ON mr.id=r.generated_by_mail_agent_run_id "
            "JOIN mail_threads t ON t.id=r.mail_thread_id "
            "WHERE d.id=? AND r.subject_id=?",
            (delivery_id, subject_id),
        ).fetchall()
        if len(rows) != 1:
            raise MailDeliveryRepositoryError("mail_delivery_target_not_found")
        row = rows[0]
        if (
            row["status"] not in {"pending", "sending", "sent", "already_sent", "delivery_unknown"}
            or row["provider_thread_id"] != row["response_thread_id"]
            or row["related_run_key"] != row["run_key"]
            or not row["in_reply_to_mail_message_id"]
            or not row["idempotency_key"]
            or not row["user_visible_text"]
        ):
            raise MailDeliveryRepositoryError("mail_delivery_target_invalid")
        return AcceptedDeliveryTarget(
            int(row["id"]),
            int(row["subject_id"]),
            int(row["response_id"]),
            int(row["in_reply_to_mail_message_id"]),
            str(row["trigger_provider_message_id"]),
            str(row["provider_thread_id"]),
            str(row["idempotency_key"]),
            str(row["run_key"]),
            str(row["user_visible_text"]),
            str(row["response_kind"]),
            str(row["status"]),
        )

    def claim_pending_delivery(self, subject_id: int, delivery_id: int) -> AcceptedDeliveryTarget:
        with self.repository._write_transaction():
            target = self._load_by_delivery_id(subject_id, delivery_id)
            if target.status == "sending":
                self._assert_trigger_state(target, "sending")
                return target
            if target.status != "pending":
                raise MailDeliveryRepositoryError("mail_delivery_not_pending")
            self._assert_trigger_state(target, "ready_to_send")
            self.connection.execute(
                "UPDATE mail_deliveries SET status='sending',updated_at_utc=? WHERE id=? AND status='pending'",
                (self._clock(), target.delivery_id),
            )
            self.connection.execute(
                "UPDATE mail_messages SET processing_state='sending' WHERE id=? AND processing_state='ready_to_send'",
                (target.trigger_message_id,),
            )
            self._upsert_item(target, "send", "running")
            return self._load_by_delivery_id(subject_id, delivery_id)

    def record_provider_receipt(
        self,
        subject_id: int,
        delivery_id: int,
        verified_identity_id: int,
        *,
        provider_message_id: str,
        provider_thread_id: str,
        sent_at_utc: str,
        status: str,
        label_applied: bool,
        label_retry_at_utc: str | None = None,
    ) -> PersistedDeliveryReceipt:
        if status not in {"sent", "already_sent"} or not isinstance(label_applied, bool):
            raise MailDeliveryRepositoryError("mail_delivery_receipt_invalid")
        with self.repository._write_transaction():
            target = self._load_by_delivery_id(subject_id, delivery_id)
            self._assert_identity(subject_id, verified_identity_id)
            if target.status not in {"sending", status}:
                raise MailDeliveryRepositoryError("mail_delivery_receipt_state_invalid")
            if provider_thread_id != target.provider_thread_id:
                raise MailDeliveryRepositoryError("mail_delivery_thread_conflict")
            if not self._safe_identifier(provider_message_id) or not self._safe_identifier(provider_thread_id):
                raise MailDeliveryRepositoryError("mail_delivery_receipt_invalid")
            if not self._canonical_utc(sent_at_utc):
                raise MailDeliveryRepositoryError("mail_delivery_receipt_invalid")
            outbound_id = self._persist_outbound_message(target, provider_message_id, sent_at_utc)
            if target.status == "sending":
                changed = self.connection.execute(
                    "UPDATE mail_deliveries SET mail_message_id=?,provider_thread_id=?,status=?,sent_at_utc=?,"
                    "last_verified_at_utc=?,error_code=NULL,error_summary=NULL,updated_at_utc=? "
                    "WHERE id=? AND status='sending'",
                    (outbound_id, provider_thread_id, status, sent_at_utc, self._clock(), self._clock(), target.delivery_id),
                ).rowcount
                if changed != 1:
                    raise MailDeliveryRepositoryError("mail_delivery_receipt_conflict")
            else:
                row = self.connection.execute(
                    "SELECT mail_message_id,provider_thread_id,status FROM mail_deliveries WHERE id=?",
                    (target.delivery_id,),
                ).fetchone()
                if row is None or tuple(row) != (outbound_id, provider_thread_id, status):
                    raise MailDeliveryRepositoryError("mail_delivery_receipt_conflict")
            self._record_sent_event(target, outbound_id, status, sent_at_utc)
            self._upsert_item(target, "send", "succeeded", outbound_id=outbound_id)
            self._assert_verified_delivery(target)
            self.connection.execute(
                "UPDATE mail_messages SET processing_state='sent' WHERE id=? AND processing_state='sending'",
                (target.trigger_message_id,),
            )
            if label_applied:
                self._upsert_item(target, "verify", "succeeded", outbound_id=outbound_id)
                pending = False
            else:
                if not self._canonical_utc(label_retry_at_utc):
                    raise MailDeliveryRepositoryError("mail_delivery_label_retry_required")
                self._upsert_item(
                    target,
                    "verify",
                    "deferred",
                    outbound_id=outbound_id,
                    error_code="label_pending",
                    next_retry_at_utc=label_retry_at_utc,
                )
                pending = True
            return PersistedDeliveryReceipt(target.delivery_id, outbound_id, status, pending)

    def record_delivery_unknown(
        self,
        subject_id: int,
        delivery_id: int,
        *,
        error_code: str = "mail_item_failed",
    ) -> None:
        if not self._safe_error_code(error_code):
            raise MailDeliveryRepositoryError("mail_delivery_error_code_invalid")
        with self.repository._write_transaction():
            target = self._load_by_delivery_id(subject_id, delivery_id)
            if target.status == "delivery_unknown":
                self._assert_trigger_state(target, "delivery_unknown")
                return
            if target.status != "sending":
                raise MailDeliveryRepositoryError("mail_delivery_unknown_state_invalid")
            self.connection.execute(
                "UPDATE mail_deliveries SET status='delivery_unknown',error_code=?,"
                "error_summary='mail delivery did not complete',updated_at_utc=? "
                "WHERE id=? AND status='sending'",
                (error_code, self._clock(), target.delivery_id),
            )
            self.connection.execute(
                "UPDATE mail_messages SET processing_state='delivery_unknown' WHERE id=? AND processing_state='sending'",
                (target.trigger_message_id,),
            )
            self._upsert_item(target, "send", "failed", error_code=error_code)

    def reconcile_provider_receipt(
        self,
        subject_id: int,
        delivery_id: int,
        verified_identity_id: int,
        *,
        provider_message_id: str,
        provider_thread_id: str,
        sent_at_utc: str,
    ) -> PersistedDeliveryReceipt:
        """Record the one proven outcome of an uncertain prior send.

        This is intentionally distinct from ``record_provider_receipt``:
        the original ``send`` item remains failed evidence and is never
        transitioned/retried.  Only a unique later provider lookup may add a
        successful ``reconcile`` item and converge the delivery state.
        """
        with self.repository._write_transaction():
            target = self._load_by_delivery_id(subject_id, delivery_id)
            self._assert_identity(subject_id, verified_identity_id)
            if provider_thread_id != target.provider_thread_id:
                raise MailDeliveryRepositoryError("mail_delivery_thread_conflict")
            if (
                not self._safe_identifier(provider_message_id)
                or not self._safe_identifier(provider_thread_id)
                or not self._canonical_utc(sent_at_utc)
            ):
                raise MailDeliveryRepositoryError("mail_delivery_receipt_invalid")
            outbound_id = self._persist_outbound_message(
                target, provider_message_id, sent_at_utc
            )
            if target.status == "delivery_unknown":
                changed = self.connection.execute(
                    "UPDATE mail_deliveries SET mail_message_id=?,provider_thread_id=?,status='sent',"
                    "sent_at_utc=?,last_verified_at_utc=?,error_code=NULL,error_summary=NULL,updated_at_utc=? "
                    "WHERE id=? AND status='delivery_unknown'",
                    (
                        outbound_id, provider_thread_id, sent_at_utc,
                        self._clock(), self._clock(), target.delivery_id,
                    ),
                ).rowcount
                if changed != 1:
                    raise MailDeliveryRepositoryError("mail_delivery_receipt_conflict")
                changed = self.connection.execute(
                    "UPDATE mail_messages SET processing_state='sent' "
                    "WHERE id=? AND processing_state='delivery_unknown'",
                    (target.trigger_message_id,),
                ).rowcount
                if changed != 1:
                    raise MailDeliveryRepositoryError("mail_delivery_trigger_state_invalid")
            elif target.status == "sent":
                row = self.connection.execute(
                    "SELECT mail_message_id,provider_thread_id,status FROM mail_deliveries WHERE id=?",
                    (target.delivery_id,),
                ).fetchone()
                if row is None or tuple(row) != (outbound_id, provider_thread_id, "sent"):
                    raise MailDeliveryRepositoryError("mail_delivery_receipt_conflict")
            else:
                raise MailDeliveryRepositoryError("mail_delivery_reconcile_state_invalid")
            self._record_sent_event(target, outbound_id, "sent", sent_at_utc)
            # Do not mutate the original failed ``send`` stage.  It records
            # precisely why this recovery path was needed; delivery-level
            # transient error columns clear only because Foundation's verified
            # delivery invariant requires a successful current record.
            # The original failed ``send`` evidence remains untouched.  The
            # first verify record is the distinct successful provider
            # reconciliation evidence for an unknown delivery.
            self._upsert_item(target, "verify", "succeeded", outbound_id=outbound_id)
            self._assert_verified_delivery(target)
            return PersistedDeliveryReceipt(target.delivery_id, outbound_id, "sent", False)

    # MailDeliveryStore protocol used by MailResponseDeliveryService.
    def mark_delivery_sending(self, target: ServiceDeliveryTarget) -> None:
        self.claim_pending_delivery(target.subject_id, target.delivery_id)

    def mark_delivery_sent(
        self,
        target: ServiceDeliveryTarget,
        *,
        status: str,
        provider_message_id: str,
        provider_thread_id: str,
    ) -> None:
        if self.verified_identity_id is None:
            raise MailDeliveryRepositoryError("mail_delivery_identity_unverified")
        self.record_provider_receipt(
            target.subject_id,
            target.delivery_id,
            self.verified_identity_id,
            provider_message_id=provider_message_id,
            provider_thread_id=provider_thread_id,
            sent_at_utc=self._clock(),
            status=status,
            label_applied=True,
        )

    def mark_delivery_unknown(
        self, target: ServiceDeliveryTarget, *, error_code: str
    ) -> None:
        persisted = self._load_by_delivery_id(target.subject_id, target.delivery_id)
        if persisted.status == "pending":
            self.claim_pending_delivery(target.subject_id, target.delivery_id)
        self.record_delivery_unknown(
            target.subject_id, target.delivery_id, error_code=error_code
        )

    def mark_label_pending(
        self,
        target: ServiceDeliveryTarget,
        *,
        provider_message_id: str,
        provider_thread_id: str,
        status: str,
    ) -> None:
        if self.verified_identity_id is None:
            raise MailDeliveryRepositoryError("mail_delivery_identity_unverified")
        now = datetime.fromisoformat(self._clock().replace("Z", "+00:00"))
        retry_at = (now.astimezone(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        self.record_provider_receipt(
            target.subject_id,
            target.delivery_id,
            self.verified_identity_id,
            provider_message_id=provider_message_id,
            provider_thread_id=provider_thread_id,
            sent_at_utc=self._clock(),
            status=status,
            label_applied=False,
            label_retry_at_utc=retry_at,
        )

    def mark_delivery_conflict(
        self, target: ServiceDeliveryTarget, *, error_code: str
    ) -> None:
        if not isinstance(error_code, str) or not error_code:
            raise MailDeliveryRepositoryError("mail_delivery_conflict_invalid")
        with self.repository._write_transaction():
            persisted = self._load_by_delivery_id(
                target.subject_id, target.delivery_id
            )
            if persisted.status in {"sent", "already_sent", "delivery_unknown"}:
                raise MailDeliveryRepositoryError("mail_delivery_conflict_state_invalid")
            self.connection.execute(
                "UPDATE mail_deliveries SET status='failed',error_code=?,"
                "error_summary='mail delivery did not complete',updated_at_utc=? "
                "WHERE id=?",
                (error_code, self._clock(), target.delivery_id),
            )
            self._upsert_item(
                persisted, "send", "failed", error_code=error_code
            )

    def _persist_outbound_message(
        self, target: AcceptedDeliveryTarget, provider_message_id: str, sent_at_utc: str) -> int:
        rows = self.connection.execute(
            "SELECT m.id,m.mail_thread_id,m.direction,m.actor_role,m.sent_at_utc "
            "FROM mail_messages m WHERE m.provider_message_id=?",
            (provider_message_id,),
        ).fetchall()
        thread = self.connection.execute(
            "SELECT id FROM mail_threads WHERE subject_id=? AND provider_thread_id=? AND is_current=1",
            (target.subject_id, target.provider_thread_id),
        ).fetchone()
        if thread is None:
            raise MailDeliveryRepositoryError("mail_delivery_thread_conflict")
        if not rows:
            cursor = self.connection.execute(
                "INSERT INTO mail_messages(mail_thread_id,provider_message_id,direction,actor_role,sent_at_utc,"
                "subject,body_sha256,labels_json,processing_state) VALUES(?,?, 'outbound','trainlab',?,NULL,NULL,'[]','sent')",
                (thread["id"], provider_message_id, sent_at_utc),
            )
            return int(cursor.lastrowid)
        if len(rows) != 1:
            raise MailDeliveryRepositoryError("mail_delivery_provider_message_conflict")
        row = rows[0]
        if (
            row["mail_thread_id"] != thread["id"]
            or row["direction"] not in {"outbound", "self_copy"}
            or row["actor_role"] != "trainlab"
            or row["sent_at_utc"] not in {None, sent_at_utc}
        ):
            raise MailDeliveryRepositoryError("mail_delivery_provider_message_conflict")
        if row["sent_at_utc"] is None:
            self.connection.execute(
                "UPDATE mail_messages SET sent_at_utc=?,processing_state='sent' WHERE id=?",
                (sent_at_utc, row["id"]),
            )
        return int(row["id"])

    def _record_sent_event(self, target: AcceptedDeliveryTarget, outbound_id: int, status: str, occurred_at_utc: str) -> None:
        rows = self.connection.execute(
            "SELECT id FROM conversation_events WHERE mail_delivery_id=? AND event_type='mail_response_sent'",
            (target.delivery_id,),
        ).fetchall()
        if len(rows) > 1:
            raise MailDeliveryRepositoryError("mail_delivery_event_conflict")
        if rows:
            return
        run = self.connection.execute("SELECT * FROM mail_agent_runs WHERE run_key=?", (target.run_key,)).fetchone()
        if run is None:
            raise MailDeliveryRepositoryError("mail_delivery_run_missing")
        event_id = self.repository._create_or_recover_event(
            run,
            EventDraft(
                "mail_response_sent", "trainlab", occurred_at_utc, outbound_id,
                "system_generated", related_run_key=target.run_key,
                structured_payload_json=json.dumps(
                    {"mail_delivery_id": target.delivery_id, "status": status},
                    sort_keys=True, separators=(",", ":"),
                ),
            ),
        )
        changed = self.connection.execute(
            "UPDATE conversation_events SET mail_delivery_id=? WHERE id=? AND mail_delivery_id IS NULL",
            (target.delivery_id, event_id),
        ).rowcount
        if changed != 1:
            raise MailDeliveryRepositoryError("mail_delivery_event_conflict")

    def _upsert_item(
        self, target: AcceptedDeliveryTarget, stage: str, status: str, *,
        outbound_id: int | None = None, error_code: str | None = None,
        next_retry_at_utc: str | None = None,
    ) -> None:
        self.repository._validate_item_relations(
            target.subject_id, "delivery", str(target.delivery_id), target.trigger_message_id,
            None, target.response_artifact_id, target.delivery_id,
        )
        run = self.connection.execute("SELECT id FROM mail_agent_runs WHERE run_key=?", (target.run_key,)).fetchone()
        if run is None:
            raise MailDeliveryRepositoryError("mail_delivery_run_missing")
        row = self.connection.execute(
            "SELECT * FROM mail_agent_items WHERE mail_agent_run_id=? AND logical_item_kind='delivery' "
            "AND logical_item_id=? AND stage=?",
            (run["id"], str(target.delivery_id), stage),
        ).fetchone()
        relations = (target.trigger_message_id, None, target.response_artifact_id, target.delivery_id)
        if row is not None:
            existing = (row["mail_message_id"], row["dependency_analysis_artifact_id"], row["mail_response_artifact_id"], row["mail_delivery_id"])
            if existing != relations:
                raise MailDeliveryRepositoryError("mail_delivery_item_conflict")
            if row["status"] == status:
                return
            permitted = {"running": {"succeeded", "failed"}, "deferred": {"succeeded"}}
            if status not in permitted.get(row["status"], set()):
                raise MailDeliveryRepositoryError("mail_delivery_item_conflict")
            self.connection.execute(
                "UPDATE mail_agent_items SET status=?,attempt_count=attempt_count+1,error_code=?,"
                "error_summary=?,next_retry_at_utc=?,completed_at_utc=? WHERE id=?",
                (status, error_code, "mail delivery did not complete" if error_code else None,
                 next_retry_at_utc, self._clock() if status != "running" else None, row["id"]),
            )
            return
        if status not in {"running", "succeeded", "deferred", "failed"}:
            raise MailDeliveryRepositoryError("mail_delivery_item_invalid")
        self.connection.execute(
            "INSERT INTO mail_agent_items(mail_agent_run_id,logical_item_kind,logical_item_id,mail_message_id,"
            "dependency_analysis_artifact_id,mail_response_artifact_id,mail_delivery_id,stage,status,attempt_count,"
            "error_code,error_summary,next_retry_at_utc,started_at_utc,completed_at_utc) "
            "VALUES(?,?,?,?,?,?,?, ?,?,1,?,?,?, ?,?)",
            (run["id"], "delivery", str(target.delivery_id), *relations, stage, status,
             error_code, "mail delivery did not complete" if error_code else None,
             next_retry_at_utc, self._clock(), self._clock() if status != "running" else None),
        )

    def _assert_identity(self, subject_id: int, identity_id: int) -> None:
        row = self.connection.execute(
            "SELECT id FROM subject_identities WHERE id=? AND subject_id=? AND provider='gmail' "
            "AND identity_kind='email' AND is_verified=1",
            (identity_id, subject_id),
        ).fetchone()
        if row is None:
            raise MailDeliveryRepositoryError("mail_delivery_identity_unverified")

    def _assert_trigger_state(self, target: AcceptedDeliveryTarget, state: str) -> None:
        row = self.connection.execute("SELECT processing_state FROM mail_messages WHERE id=?", (target.trigger_message_id,)).fetchone()
        if row is None or row["processing_state"] != state:
            raise MailDeliveryRepositoryError("mail_delivery_trigger_state_invalid")

    def _assert_verified_delivery(self, target: AcceptedDeliveryTarget) -> None:
        if not self.repository._message_has_verified_delivery(target.subject_id, target.trigger_message_id):
            raise MailDeliveryRepositoryError("mail_delivery_evidence_invalid")

    @staticmethod
    def _safe_identifier(value: object) -> bool:
        return isinstance(value, str) and bool(value) and len(value) <= 160 and all(
            char.isalnum() or char in "._:-" for char in value
        )

    @staticmethod
    def _safe_error_code(value: object) -> bool:
        return (
            isinstance(value, str)
            and 1 <= len(value) <= 64
            and value[0].islower()
            and all(char.islower() or char.isdigit() or char == "_" for char in value)
        )

    @staticmethod
    def _canonical_utc(value: object) -> bool:
        from .repository import _canonical_utc
        return _canonical_utc(value) if isinstance(value, str) else False
