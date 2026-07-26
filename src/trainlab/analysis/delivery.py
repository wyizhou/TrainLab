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
