"""A3-14 pending analysis-delivery creation and deterministic safe rendering.

This module intentionally stops before any provider interaction.  It binds a
pending delivery to the immutable artifact revisions returned by A3-13 and
returns an in-memory plain-text/HTML representation for the later delivery
runner.  It never stores a rendered body or changes artifact/current/run state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import html
import json
import re
import sqlite3
from typing import Callable, Literal, Mapping, Protocol, Sequence


DeliveryKind = Literal["daily_report", "weekly_report", "plan_revision"]

_DELIVERY_SHAPES: dict[str, tuple[tuple[str, str], ...]] = {
    "daily_report": (("daily_summary", "daily_summary"), ("daily_training_advice", "daily_advice")),
    "weekly_report": (("weekly_summary", "weekly_summary"), ("weekly_training_plan", "weekly_plan")),
    "plan_revision": (("weekly_training_plan", "plan_revision"),),
}
_TITLES = {
    "daily_summary": "每日总结",
    "daily_advice": "今日建议",
    "weekly_summary": "每周总结",
    "weekly_plan": "未来七天计划",
    "plan_revision": "计划修订",
}


class AnalysisDeliveryError(RuntimeError):
    """A controlled A3-14 failure; accepted artifacts remain untouched."""


_DELIVERY_STATUSES = frozenset({"pending", "sending", "sent", "already_sent", "delivery_unknown", "failed"})
_SAFE_PROVIDER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SAFE_ERROR_CODE = re.compile(r"analysis_[a-z0-9_]{1,120}\Z")
_DELIVERY_FAILURE_SUMMARY = "analysis delivery did not complete"


class _PublishReceiptLike(Protocol):
    run_id: int
    artifact_ids: Mapping[str, int]


@dataclass(frozen=True)
class DeliveryArtifact:
    artifact_id: int
    artifact_kind: str
    content_role: str
    revision_no: int
    content_sha256: str
    user_visible_text: str


@dataclass(frozen=True)
class PendingDelivery:
    delivery_id: int
    subject_id: int
    analysis_run_id: int
    run_key: str
    delivery_kind: DeliveryKind
    idempotency_key: str
    artifacts: tuple[DeliveryArtifact, ...]


@dataclass(frozen=True)
class RenderedDelivery:
    """Ephemeral provider-ready content.  It is deliberately not persisted."""

    subject: str
    headers: Mapping[str, str]
    plain_text: str
    html: str


@dataclass(frozen=True)
class AnalysisDeliveryState:
    """Provider-independent, durable delivery state and evidence."""

    delivery_id: int
    subject_id: int
    analysis_run_id: int
    status: str
    provider_message_id: str | None
    provider_thread_id: str | None
    sent_at_utc: str | None
    last_verified_at_utc: str | None
    error_code: str | None
    error_summary: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _safe_header(value: str) -> str:
    if not value or "\r" in value or "\n" in value:
        raise AnalysisDeliveryError("analysis_delivery_header_invalid")
    return value


def _receipt_values(receipt: _PublishReceiptLike | Mapping[str, object]) -> tuple[int, Mapping[str, int]]:
    if isinstance(receipt, Mapping):
        run_id, artifact_ids = receipt.get("run_id"), receipt.get("artifact_ids")
    else:
        run_id, artifact_ids = receipt.run_id, receipt.artifact_ids
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0 or not isinstance(artifact_ids, Mapping):
        raise AnalysisDeliveryError("analysis_delivery_publish_receipt_invalid")
    normalized: dict[str, int] = {}
    for kind, artifact_id in artifact_ids.items():
        if not isinstance(kind, str) or not isinstance(artifact_id, int) or isinstance(artifact_id, bool) or artifact_id <= 0:
            raise AnalysisDeliveryError("analysis_delivery_publish_receipt_invalid")
        normalized[kind] = artifact_id
    return run_id, normalized


def _idempotency_key(run_key: str, delivery_kind: str, artifacts: Sequence[DeliveryArtifact]) -> str:
    material = {
        "version": 1,
        "run_key": run_key,
        "delivery_kind": delivery_kind,
        "artifacts": [
            {"role": item.content_role, "id": item.artifact_id, "revision": item.revision_no, "content_sha256": item.content_sha256}
            for item in artifacts
        ],
    }
    return "analysis-delivery:v1:" + sha256(_canonical(material).encode("utf-8")).hexdigest()


class AnalysisDeliveryFactory:
    """Seed one pending delivery in a short transaction, with no send capability."""

    def __init__(self, connection: sqlite3.Connection, *, clock: Callable[[], str] = _now) -> None:
        self._connection = connection
        self._clock = clock

    def create_pending(
        self, *, publish_receipt: _PublishReceiptLike | Mapping[str, object], delivery_kind: DeliveryKind
    ) -> PendingDelivery:
        run_id, artifact_ids = _receipt_values(publish_receipt)
        shape = _DELIVERY_SHAPES.get(delivery_kind)
        if shape is None:
            raise AnalysisDeliveryError("analysis_delivery_kind_invalid")
        self._connection.execute("PRAGMA foreign_keys=ON")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            pending = self._create_in_transaction(run_id, artifact_ids, delivery_kind, shape)
            self._connection.execute("COMMIT")
            return pending
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def create_pending_in_transaction(
        self,
        *,
        publish_receipt: _PublishReceiptLike | Mapping[str, object],
        delivery_kind: DeliveryKind,
    ) -> PendingDelivery:
        """Seed pending delivery inside a caller-owned publication transaction."""
        if not self._connection.in_transaction:
            raise AnalysisDeliveryError(
                "analysis_delivery_transaction_required"
            )
        run_id, artifact_ids = _receipt_values(publish_receipt)
        shape = _DELIVERY_SHAPES.get(delivery_kind)
        if shape is None:
            raise AnalysisDeliveryError("analysis_delivery_kind_invalid")
        return self._create_in_transaction(
            run_id, artifact_ids, delivery_kind, shape
        )

    def prepare(
        self,
        *,
        publish_receipt: _PublishReceiptLike | Mapping[str, object],
        delivery_kind: DeliveryKind,
        renderer: Callable[[PendingDelivery], RenderedDelivery] = None,  # type: ignore[assignment]
    ) -> tuple[PendingDelivery, RenderedDelivery]:
        """Commit the pending seed before rendering, so render failures are recoverable."""
        pending = self.create_pending(publish_receipt=publish_receipt, delivery_kind=delivery_kind)
        return pending, (render_delivery if renderer is None else renderer)(pending)

    def _create_in_transaction(
        self, run_id: int, artifact_ids: Mapping[str, int], delivery_kind: str, shape: tuple[tuple[str, str], ...]
    ) -> PendingDelivery:
        if set(artifact_ids) != {artifact_kind for artifact_kind, _ in shape}:
            raise AnalysisDeliveryError("analysis_delivery_artifact_set_invalid")
        run = self._connection.execute(
            "SELECT id,subject_id,run_key FROM analysis_runs WHERE id=?", (run_id,)
        ).fetchone()
        if run is None:
            raise AnalysisDeliveryError("analysis_delivery_run_missing")
        artifacts: list[DeliveryArtifact] = []
        for artifact_kind, content_role in shape:
            row = self._connection.execute(
                "SELECT id,subject_id,artifact_kind,revision_no,content_sha256,user_visible_text,generated_by_run_id "
                "FROM analysis_artifacts WHERE id=?",
                (artifact_ids[artifact_kind],),
            ).fetchone()
            if row is None or row["subject_id"] != run["subject_id"] or row["generated_by_run_id"] != run_id or row["artifact_kind"] != artifact_kind:
                raise AnalysisDeliveryError("analysis_delivery_artifact_not_published_by_run")
            artifacts.append(DeliveryArtifact(
                artifact_id=int(row["id"]), artifact_kind=str(row["artifact_kind"]), content_role=content_role,
                revision_no=int(row["revision_no"]), content_sha256=str(row["content_sha256"]), user_visible_text=str(row["user_visible_text"]),
            ))
        run_key = _safe_header(str(run["run_key"]))
        key = _idempotency_key(run_key, delivery_kind, artifacts)
        existing = self._connection.execute(
            "SELECT id,subject_id,analysis_run_id,delivery_kind FROM analysis_deliveries WHERE idempotency_key=?", (key,)
        ).fetchone()
        if existing is not None:
            if existing["subject_id"] != run["subject_id"] or existing["analysis_run_id"] != run_id or existing["delivery_kind"] != delivery_kind:
                raise AnalysisDeliveryError("analysis_delivery_idempotency_conflict")
            self._verify_existing_relations(int(existing["id"]), artifacts)
            delivery_id = int(existing["id"])
        else:
            now = self._clock()
            cursor = self._connection.execute(
                "INSERT INTO analysis_deliveries(subject_id,idempotency_key,analysis_run_id,delivery_kind,status,created_at_utc,updated_at_utc) "
                "VALUES(?,?,?,?, 'pending',?,?)",
                (run["subject_id"], key, run_id, delivery_kind, now, now),
            )
            delivery_id = int(cursor.lastrowid)
            for ordinal, artifact in enumerate(artifacts):
                self._connection.execute(
                    "INSERT INTO analysis_delivery_artifacts(analysis_delivery_id,analysis_artifact_id,content_role,ordinal) VALUES(?,?,?,?)",
                    (delivery_id, artifact.artifact_id, artifact.content_role, ordinal),
                )
        return PendingDelivery(delivery_id, int(run["subject_id"]), run_id, run_key, delivery_kind, key, tuple(artifacts))

    def _verify_existing_relations(self, delivery_id: int, expected: Sequence[DeliveryArtifact]) -> None:
        actual = self._connection.execute(
            "SELECT analysis_artifact_id,content_role,ordinal FROM analysis_delivery_artifacts WHERE analysis_delivery_id=? ORDER BY ordinal",
            (delivery_id,),
        ).fetchall()
        triples = [(int(row["analysis_artifact_id"]), str(row["content_role"]), int(row["ordinal"])) for row in actual]
        wanted = [(item.artifact_id, item.content_role, ordinal) for ordinal, item in enumerate(expected)]
        if triples != wanted:
            raise AnalysisDeliveryError("analysis_delivery_relation_conflict")


class AnalysisDeliveryRepository:
    """Fail-closed SQLite state machine for one immutable analysis delivery.

    This repository deliberately has no Gmail dependency.  A future provider
    runner must claim a record, perform its external work, and then call one of
    the evidence-recording methods below.  Every write re-reads the immutable
    artifact relation in the same short ``BEGIN IMMEDIATE`` transaction.
    """

    def __init__(self, connection: sqlite3.Connection, *, clock: Callable[[], str] = _now) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._clock = clock

    def load_pending(self, delivery_id: int, *, subject_id: int | None = None) -> PendingDelivery:
        """Load exactly the revisions linked to one delivery, never current rows."""
        self._validate_identifier(delivery_id, "analysis_delivery_id_invalid")
        if subject_id is not None:
            self._validate_identifier(subject_id, "analysis_delivery_subject_invalid")
        row, artifacts = self._load_verified(delivery_id)
        if subject_id is not None and int(row["subject_id"]) != subject_id:
            raise AnalysisDeliveryError("analysis_delivery_ownership_invalid")
        return PendingDelivery(
            delivery_id=int(row["id"]), subject_id=int(row["subject_id"]), analysis_run_id=int(row["analysis_run_id"]),
            run_key=str(row["run_key"]), delivery_kind=str(row["delivery_kind"]),
            idempotency_key=str(row["idempotency_key"]), artifacts=tuple(artifacts),
        )

    def load_rendered(self, delivery_id: int, *, subject_id: int | None = None) -> RenderedDelivery:
        """Re-render the delivery's original revisions; never follow ``is_current``."""
        return render_delivery(self.load_pending(delivery_id, subject_id=subject_id))

    # Explicit aliases keep provider code readable without exposing raw rows.
    load_pending_delivery = load_pending
    load_rendered_delivery = load_rendered

    def read_state(self, delivery_id: int, *, subject_id: int | None = None) -> AnalysisDeliveryState:
        pending = self.load_pending(delivery_id, subject_id=subject_id)
        row = self._connection.execute(
            "SELECT * FROM analysis_deliveries WHERE id=?", (pending.delivery_id,)
        ).fetchone()
        if row is None:  # Defensive: a concurrent destructive writer is not a valid replay.
            raise AnalysisDeliveryError("analysis_delivery_missing")
        return self._state_from_row(row)

    get_state = read_state

    def claim_for_send(self, subject_id: int, delivery_id: int) -> AnalysisDeliveryState:
        """Atomically claim a pending/failed record. Unknown records are never resent."""
        return self.transition_delivery_state(subject_id, delivery_id, "sending")

    def record_sent(
        self, subject_id: int, delivery_id: int, *, provider_message_id: str,
        provider_thread_id: str | None = None, sent_at_utc: str, last_verified_at_utc: str,
    ) -> AnalysisDeliveryState:
        return self.transition_delivery_state(
            subject_id, delivery_id, "sent", provider_message_id=provider_message_id,
            provider_thread_id=provider_thread_id, sent_at_utc=sent_at_utc,
            last_verified_at_utc=last_verified_at_utc,
        )

    def record_search_match(
        self, subject_id: int, delivery_id: int, *, provider_message_id: str,
        provider_thread_id: str | None = None, sent_at_utc: str, last_verified_at_utc: str,
    ) -> AnalysisDeliveryState:
        """Persist one exact provider search result as already-sent evidence."""
        return self.transition_delivery_state(
            subject_id, delivery_id, "already_sent", recovery_kind="reconcile",
            provider_message_id=provider_message_id, provider_thread_id=provider_thread_id,
            sent_at_utc=sent_at_utc, last_verified_at_utc=last_verified_at_utc,
        )

    def record_failed(self, subject_id: int, delivery_id: int, *, error_code: str) -> AnalysisDeliveryState:
        return self.transition_delivery_state(subject_id, delivery_id, "failed", error_code=error_code)

    def record_delivery_unknown(
        self, subject_id: int, delivery_id: int, *, provider_message_id: str | None = None,
        provider_thread_id: str | None = None, error_code: str,
    ) -> AnalysisDeliveryState:
        """Use after an ambiguous send or a post-send label failure; do not retry it."""
        return self.transition_delivery_state(
            subject_id, delivery_id, "delivery_unknown", provider_message_id=provider_message_id,
            provider_thread_id=provider_thread_id, error_code=error_code,
        )

    def transition_delivery_state(
        self,
        subject_id: int,
        delivery_id: int,
        status: str,
        *,
        recovery_kind: str = "normal",
        provider_message_id: str | None = None,
        provider_thread_id: str | None = None,
        sent_at_utc: str | None = None,
        last_verified_at_utc: str | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> AnalysisDeliveryState:
        """CAS transition with durable, minimal evidence.

        ``error_summary`` is accepted only for API compatibility and is never
        persisted: provider/model text may contain private health or mailbox
        data.  The stable summary is derived from a validated error code.
        """
        del error_summary
        self._validate_identifier(subject_id, "analysis_delivery_subject_invalid")
        self._validate_identifier(delivery_id, "analysis_delivery_id_invalid")
        if status not in _DELIVERY_STATUSES or recovery_kind not in {"normal", "reconcile"}:
            raise AnalysisDeliveryError("analysis_delivery_transition_invalid")
        self._validate_provider_id(provider_message_id)
        self._validate_provider_id(provider_thread_id)
        if sent_at_utc is not None and not self._canonical_utc(sent_at_utc):
            raise AnalysisDeliveryError("analysis_delivery_transition_invalid")
        if last_verified_at_utc is not None and not self._canonical_utc(last_verified_at_utc):
            raise AnalysisDeliveryError("analysis_delivery_transition_invalid")
        if error_code is not None and not _SAFE_ERROR_CODE.fullmatch(error_code):
            raise AnalysisDeliveryError("analysis_delivery_transition_invalid")
        if status in {"sent", "already_sent"} and (
            provider_message_id is None or sent_at_utc is None or last_verified_at_utc is None
        ):
            raise AnalysisDeliveryError("analysis_delivery_evidence_required")
        if status in {"sending", "sent", "already_sent"} and error_code is not None:
            raise AnalysisDeliveryError("analysis_delivery_transition_invalid")
        if status in {"failed", "delivery_unknown"} and error_code is None:
            raise AnalysisDeliveryError("analysis_delivery_error_required")

        try:
            self._connection.execute("BEGIN IMMEDIATE")
            row, _ = self._load_verified(delivery_id)
            if int(row["subject_id"]) != subject_id:
                raise AnalysisDeliveryError("analysis_delivery_ownership_invalid")
            current = str(row["status"])
            if current == status:
                state = self._state_from_row(row)
                if current in {"sent", "already_sent"} and self._replay_matches(
                    state, provider_message_id, provider_thread_id, sent_at_utc,
                    last_verified_at_utc, error_code,
                ):
                    self._connection.execute("COMMIT")
                    return state
                raise AnalysisDeliveryError(
                    "analysis_delivery_replay_conflict" if current in {"sent", "already_sent"}
                    else "analysis_delivery_transition_illegal"
                )
            if not self._permitted(current, status, recovery_kind):
                raise AnalysisDeliveryError("analysis_delivery_transition_illegal")

            message_id = self._immutable_provider_value(row["provider_message_id"], provider_message_id)
            thread_id = self._immutable_provider_value(row["provider_thread_id"], provider_thread_id)
            if status in {"sent", "already_sent"} and message_id is None:
                raise AnalysisDeliveryError("analysis_delivery_evidence_required")
            # An ambiguous record intentionally remains non-sendable even when
            # Gmail accepted a message but applying the label later failed.
            stored_error_code = error_code if status in {"failed", "delivery_unknown"} else None
            stored_error_summary = _DELIVERY_FAILURE_SUMMARY if stored_error_code is not None else None
            cursor = self._connection.execute(
                "UPDATE analysis_deliveries SET provider_message_id=?,provider_thread_id=?,status=?,sent_at_utc=?,"
                "last_verified_at_utc=?,error_code=?,error_summary=?,updated_at_utc=? WHERE id=? AND status=?",
                (
                    message_id, thread_id, status, sent_at_utc, last_verified_at_utc,
                    stored_error_code, stored_error_summary, self._clock(), delivery_id, current,
                ),
            )
            if cursor.rowcount != 1:
                raise AnalysisDeliveryError("analysis_delivery_compare_and_swap_failed")
            updated = self._connection.execute("SELECT * FROM analysis_deliveries WHERE id=?", (delivery_id,)).fetchone()
            if updated is None:
                raise AnalysisDeliveryError("analysis_delivery_missing")
            self._connection.execute("COMMIT")
            return self._state_from_row(updated)
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    @staticmethod
    def _validate_identifier(value: object, code: str) -> None:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise AnalysisDeliveryError(code)

    @staticmethod
    def _validate_provider_id(value: str | None) -> None:
        if value is not None and (not isinstance(value, str) or not _SAFE_PROVIDER_ID.fullmatch(value)):
            raise AnalysisDeliveryError("analysis_delivery_transition_invalid")

    @staticmethod
    def _canonical_utc(value: str) -> bool:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return value.endswith("Z") and parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)

    @staticmethod
    def _immutable_provider_value(existing: object, supplied: str | None) -> str | None:
        if existing is not None and supplied not in {None, existing}:
            raise AnalysisDeliveryError("analysis_delivery_provider_evidence_conflict")
        return str(existing) if existing is not None else supplied

    @staticmethod
    def _permitted(current: str, target: str, recovery_kind: str) -> bool:
        if current in {"sent", "already_sent"}:
            return False
        if target == "sending":
            return recovery_kind == "normal" and current in {"pending", "failed"}
        if target in {"sent", "already_sent"}:
            if current == "sending" and target == "sent":
                return recovery_kind == "normal"
            # A provider search is the only route to already_sent. It can also
            # reconcile an ambiguous outcome, but never authorizes a re-send.
            return recovery_kind == "reconcile" and current in {"pending", "sending", "delivery_unknown", "failed"}
        if target in {"failed", "delivery_unknown"}:
            return recovery_kind == "normal" and current == "sending"
        return False

    @staticmethod
    def _replay_matches(
        state: AnalysisDeliveryState, provider_message_id: str | None, provider_thread_id: str | None,
        sent_at_utc: str | None, last_verified_at_utc: str | None, error_code: str | None,
    ) -> bool:
        wanted = (
            state.provider_message_id if provider_message_id is None else provider_message_id,
            state.provider_thread_id if provider_thread_id is None else provider_thread_id,
            state.sent_at_utc if sent_at_utc is None else sent_at_utc,
            state.last_verified_at_utc if last_verified_at_utc is None else last_verified_at_utc,
            state.error_code if error_code is None else error_code,
        )
        return wanted == (
            state.provider_message_id, state.provider_thread_id, state.sent_at_utc,
            state.last_verified_at_utc, state.error_code,
        )

    @staticmethod
    def _state_from_row(row: sqlite3.Row) -> AnalysisDeliveryState:
        return AnalysisDeliveryState(
            delivery_id=int(row["id"]), subject_id=int(row["subject_id"]), analysis_run_id=int(row["analysis_run_id"]),
            status=str(row["status"]), provider_message_id=row["provider_message_id"],
            provider_thread_id=row["provider_thread_id"], sent_at_utc=row["sent_at_utc"],
            last_verified_at_utc=row["last_verified_at_utc"], error_code=row["error_code"],
            error_summary=row["error_summary"],
        )

    def _load_verified(self, delivery_id: int) -> tuple[sqlite3.Row, list[DeliveryArtifact]]:
        row = self._connection.execute(
            "SELECT d.*,r.run_key,r.subject_id AS run_subject_id FROM analysis_deliveries d "
            "JOIN analysis_runs r ON r.id=d.analysis_run_id WHERE d.id=?", (delivery_id,)
        ).fetchone()
        if row is None:
            raise AnalysisDeliveryError("analysis_delivery_missing")
        if int(row["subject_id"]) != int(row["run_subject_id"]):
            raise AnalysisDeliveryError("analysis_delivery_run_subject_conflict")
        shape = _DELIVERY_SHAPES.get(str(row["delivery_kind"]))
        if shape is None:
            raise AnalysisDeliveryError("analysis_delivery_kind_invalid")
        links = self._connection.execute(
            "SELECT a.id AS link_id,a.analysis_artifact_id,a.content_role,a.ordinal,"
            "x.subject_id,x.artifact_kind,x.revision_no,x.content_sha256,x.user_visible_text,x.generated_by_run_id "
            "FROM analysis_delivery_artifacts a JOIN analysis_artifacts x ON x.id=a.analysis_artifact_id "
            "WHERE a.analysis_delivery_id=? ORDER BY a.ordinal", (delivery_id,),
        ).fetchall()
        expected = [(kind, role, ordinal) for ordinal, (kind, role) in enumerate(shape)]
        actual = [(str(item["artifact_kind"]), str(item["content_role"]), int(item["ordinal"])) for item in links]
        if actual != expected:
            raise AnalysisDeliveryError("analysis_delivery_relation_conflict")
        artifacts: list[DeliveryArtifact] = []
        for item, (_, role, _) in zip(links, expected, strict=True):
            if int(item["subject_id"]) != int(row["subject_id"]) or int(item["generated_by_run_id"]) != int(row["analysis_run_id"]):
                raise AnalysisDeliveryError("analysis_delivery_artifact_not_published_by_run")
            artifacts.append(DeliveryArtifact(
                artifact_id=int(item["analysis_artifact_id"]), artifact_kind=str(item["artifact_kind"]),
                content_role=role, revision_no=int(item["revision_no"]), content_sha256=str(item["content_sha256"]),
                user_visible_text=str(item["user_visible_text"]),
            ))
        run_key = _safe_header(str(row["run_key"]))
        if _idempotency_key(run_key, str(row["delivery_kind"]), artifacts) != str(row["idempotency_key"]):
            raise AnalysisDeliveryError("analysis_delivery_idempotency_conflict")
        return row, artifacts


def render_delivery(pending: PendingDelivery) -> RenderedDelivery:
    """Render verified text as escaped plain text and inline-only HTML, in memory."""
    run_key = _safe_header(pending.run_key)
    idempotency_key = _safe_header(pending.idempotency_key)
    subject = _safe_header(f"[TrainLab] {pending.delivery_kind} | run-id {run_key} | idempotency {idempotency_key}")
    header_lines = (f"Run-ID: {run_key}", f"Idempotency-Key: {idempotency_key}")
    plain_sections = ["TrainLab 分析报告", *header_lines]
    html_sections = [
        '<!doctype html><html><body style="margin:0;background:#f5f7fa;color:#172033;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;line-height:1.55">',
        '<main style="max-width:720px;margin:24px auto;padding:24px;background:#ffffff;border:1px solid #d9e0ea;border-radius:8px">',
        '<h1 style="margin:0 0 16px;font-size:22px">TrainLab 分析报告</h1>',
        f'<p style="margin:0 0 4px"><strong>Run-ID:</strong> {html.escape(run_key, quote=True)}</p>',
        f'<p style="margin:0 0 20px"><strong>Idempotency-Key:</strong> {html.escape(idempotency_key, quote=True)}</p>',
    ]
    for artifact in pending.artifacts:
        title = _TITLES[artifact.content_role]
        text = artifact.user_visible_text.replace("\r\n", "\n").replace("\r", "\n")
        plain_sections.extend(("", title, text))
        html_sections.extend((
            '<section style="margin:20px 0">',
            f'<h2 style="margin:0 0 8px;font-size:18px">{title}</h2>',
            f'<div style="white-space:pre-wrap">{html.escape(text, quote=True)}</div>',
            '</section>',
        ))
    html_sections.append('</main></body></html>')
    return RenderedDelivery(
        subject=subject,
        headers={"X-TrainLab-Run-ID": run_key, "X-TrainLab-Idempotency-Key": idempotency_key},
        plain_text="\n".join(plain_sections),
        html="".join(html_sections),
    )
