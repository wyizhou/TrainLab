"""SQLite persistence primitives owned exclusively by TrainLab layer four.

No method in this module calls a provider, Codex, a renderer, or sleeps.  The
repository uses only the current frozen Foundation tables and keeps write transactions
short and explicit.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Sequence

from .contracts import MailRequest, utc_now
from .eligibility import ActorEvidence, CanonicalMessage, Classification, TRAINLAB_LABEL, classify
from trainlab.foundation import (
    FOUNDATION_SCHEMA_VERSION,
    FoundationTool as _FoundationTool,
    TABLES as _FOUNDATION_TABLES,
    VIEWS as _FOUNDATION_VIEWS,
    validate_schema_manifest as _validate_foundation_schema_manifest,
)

_FOUNDATION_INDEX_SQL = {
    "idx_source_revisions_current": "CREATE INDEX idx_source_revisions_current ON source_revisions(provider,resource_kind,provider_object_id,is_current)",
    "ux_source_revision_current": "CREATE UNIQUE INDEX ux_source_revision_current ON source_revisions(provider,resource_kind,provider_object_id) WHERE is_current=1",
    "ux_activity_source_role_active": "CREATE UNIQUE INDEX ux_activity_source_role_active ON activity_source_revisions(activity_id,source_role) WHERE is_active=1",
    "ux_daily_health_current": "CREATE UNIQUE INDEX ux_daily_health_current ON daily_health(subject_id,local_date) WHERE is_current=1",
    "ux_analysis_artifact_current": "CREATE UNIQUE INDEX ux_analysis_artifact_current ON analysis_artifacts(subject_id,artifact_kind,period_start_local_date,period_end_local_date) WHERE is_current=1",
    "ux_mail_response_current": "CREATE UNIQUE INDEX ux_mail_response_current ON mail_response_artifacts(subject_id,mail_thread_id,response_kind) WHERE is_current=1",
    "ux_garmin_sync_gap_unresolved": "CREATE UNIQUE INDEX ux_garmin_sync_gap_unresolved ON garmin_sync_gaps(subject_id,resource_kind,logical_object_key,window_start_local_date,window_end_local_date,stage) WHERE status IN ('open','deferred')",
    "idx_coverage_resource_date": "CREATE INDEX idx_coverage_resource_date ON resource_coverage(resource_kind,local_date)",
    "idx_activity_samples_stream": "CREATE INDEX idx_activity_samples_stream ON activity_samples(activity_id,stream_kind,sample_index)",
}
_FOUNDATION_INDEX_METADATA = {
    "idx_source_revisions_current": ("source_revisions", False, False, ("provider", "resource_kind", "provider_object_id", "is_current")),
    "ux_source_revision_current": ("source_revisions", True, True, ("provider", "resource_kind", "provider_object_id")),
    "ux_activity_source_role_active": ("activity_source_revisions", True, True, ("activity_id", "source_role")),
    "ux_daily_health_current": ("daily_health", True, True, ("subject_id", "local_date")),
    "ux_analysis_artifact_current": ("analysis_artifacts", True, True, ("subject_id", "artifact_kind", "period_start_local_date", "period_end_local_date")),
    "ux_mail_response_current": ("mail_response_artifacts", True, True, ("subject_id", "mail_thread_id", "response_kind")),
    "ux_garmin_sync_gap_unresolved": ("garmin_sync_gaps", True, True, ("subject_id", "resource_kind", "logical_object_key", "window_start_local_date", "window_end_local_date", "stage")),
    "idx_coverage_resource_date": ("resource_coverage", False, False, ("resource_kind", "local_date")),
    "idx_activity_samples_stream": ("activity_samples", False, False, ("activity_id", "stream_kind", "sample_index")),
}
_FOUNDATION_TRIGGER_SQL = {
    "trg_training_plan_item_window": "CREATE TRIGGER trg_training_plan_item_window BEFORE INSERT ON training_plan_items FOR EACH ROW WHEN NEW.local_date < (SELECT plan_start_local_date FROM training_plans WHERE id=NEW.training_plan_id) OR NEW.local_date > (SELECT plan_end_local_date FROM training_plans WHERE id=NEW.training_plan_id) BEGIN SELECT RAISE(ABORT,'training_plan_item_outside_plan_window'); END",
    "trg_training_plan_artifact_insert": "CREATE TRIGGER trg_training_plan_artifact_insert BEFORE INSERT ON training_plans FOR EACH ROW WHEN (SELECT artifact_kind FROM analysis_artifacts WHERE id=NEW.analysis_artifact_id) != 'weekly_training_plan' BEGIN SELECT RAISE(ABORT,'training_plan_requires_weekly_training_plan'); END",
    "trg_training_plan_artifact_update": "CREATE TRIGGER trg_training_plan_artifact_update BEFORE UPDATE OF analysis_artifact_id ON training_plans FOR EACH ROW WHEN (SELECT artifact_kind FROM analysis_artifacts WHERE id=NEW.analysis_artifact_id) != 'weekly_training_plan' BEGIN SELECT RAISE(ABORT,'training_plan_requires_weekly_training_plan'); END",
    "trg_climbing_route_segment_insert": "CREATE TRIGGER trg_climbing_route_segment_insert BEFORE INSERT ON climbing_routes FOR EACH ROW WHEN (SELECT segment_type FROM activity_segments WHERE id=NEW.segment_id) != 'climb_active' BEGIN SELECT RAISE(ABORT,'climbing_route_requires_climb_active'); END",
    "trg_climbing_route_segment_update": "CREATE TRIGGER trg_climbing_route_segment_update BEFORE UPDATE OF segment_id ON climbing_routes FOR EACH ROW WHEN (SELECT segment_type FROM activity_segments WHERE id=NEW.segment_id) != 'climb_active' BEGIN SELECT RAISE(ABORT,'climbing_route_requires_climb_active'); END",
    "trg_strength_set_segment_insert": "CREATE TRIGGER trg_strength_set_segment_insert BEFORE INSERT ON strength_sets FOR EACH ROW WHEN (SELECT segment_type FROM activity_segments WHERE id=NEW.segment_id) NOT IN ('strength_active','strength_rest') BEGIN SELECT RAISE(ABORT,'strength_set_requires_strength_segment'); END",
    "trg_strength_set_segment_update": "CREATE TRIGGER trg_strength_set_segment_update BEFORE UPDATE OF segment_id ON strength_sets FOR EACH ROW WHEN (SELECT segment_type FROM activity_segments WHERE id=NEW.segment_id) NOT IN ('strength_active','strength_rest') BEGIN SELECT RAISE(ABORT,'strength_set_requires_strength_segment'); END",
}

_RUN_TRANSITIONS = {
    "started": {"started", "succeeded", "partial", "failed", "deferred", "rejected"},
    "partial": {"partial", "succeeded", "failed", "deferred", "rejected"},
    "deferred": {"deferred", "succeeded", "failed", "rejected"},
    "failed": {"failed"},
    "rejected": {"rejected"},
    "succeeded": {"succeeded"},
}
_POLL_PUBLIC_TO_RUN_STATUS = {
    "succeeded": "succeeded",
    "unchanged": "succeeded",
    "partial": "partial",
    "deferred": "deferred",
    "failed": "failed",
    "auth_required": "failed",
    "rejected": "rejected",
}
_ITEM_TRANSITIONS = {
    "pending": {"pending", "running", "succeeded", "failed", "deferred", "unchanged", "rejected"},
    "running": {"running", "succeeded", "failed", "deferred", "rejected"},
    "deferred": {"deferred", "running", "succeeded", "failed", "rejected"},
    "failed": {"failed"},
    "rejected": {"rejected"},
    "succeeded": {"succeeded"},
    "unchanged": {"unchanged"},
}
_STAGES = frozenset({"discover", "archive", "normalize", "classify", "context", "generate", "validate", "publish", "render", "send", "verify"})
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_URL = re.compile(r"https?://\S+")
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_POLL_RECEIPT_KEYS = frozenset({
    "schema_version", "run_key", "mail_agent_run_id", "invocation_id", "mode", "status", "counts",
    "processed_message_ids", "mail_response_artifact_ids", "mail_delivery_ids", "pending_dependencies",
    "poll_state", "next_action", "next_retry_at_utc", "warnings", "errors", "started_at_utc", "completed_at_utc",
})
_COUNT_KEYS = frozenset({"discovered", "archived", "unchanged", "queued", "processed", "ignored", "responses_accepted", "deliveries_sent", "deliveries_already_sent", "failed", "deferred"})
_RECEIPT_CODES = frozenset({
    "lock_busy", "auth_required", "gmail_adapter_failed", "gmail_transport_failed", "forbidden", "rate_limited",
    "identity_mismatch", "gmail_mapping_invalid", "gmail_tools_unavailable", "verified_identity_required",
    "poll_failed", "terminal_persistence_failed", "terminal_receipt_invalid", "provider_page_limit_unsplittable",
    "provider_thread_id_invalid", "gmail_message_time_invalid", "mail_cursor_invalid", "raw_archive_failed",
    "max_threads_reached", "archive_or_normalize_failed",
})
_ITEM_CODES = _RECEIPT_CODES | frozenset({"parse_failed", "mail_item_failed"})
_EVENT_ACTORS = {
    "feedback_recorded": "user",
    "new_request_received": "user",
    # A plan reason is a deterministic host record whose payload points back
    # to the exact untrusted user statement.  Layer three accepts only this
    # system-owned envelope; the source message remains user/untrusted.
    "plan_revision_reason_recorded": "trainlab",
    "reply_received": "user",
    "mail_quarantined": "unknown",
    "mail_response_prepared": "trainlab",
    "mail_response_sent": "trainlab",
    "daily_report_sent": "trainlab",
    "weekly_report_sent": "trainlab",
}
_RECEIPT_STAGES = frozenset({"lock", "prepare", "poll", "replay", "discover", "archive", "normalize", "tracked"})
_NEXT_ACTIONS = frozenset({"none", "continue_poll", "resume_processing", "invoke_analysis", "reconcile_delivery", "reauthenticate", "operator_review"})
_PUBLIC_SUMMARIES = {
    ("lock", "lock_busy"): "mail writer is active",
    ("prepare", "auth_required"): "gmail adapter unavailable",
    ("prepare", "gmail_adapter_failed"): "gmail adapter unavailable",
    ("prepare", "gmail_transport_failed"): "gmail adapter unavailable",
    ("prepare", "forbidden"): "gmail adapter unavailable",
    ("prepare", "rate_limited"): "gmail adapter unavailable",
    ("prepare", "identity_mismatch"): "gmail adapter unavailable",
    ("prepare", "gmail_mapping_invalid"): "gmail adapter unavailable",
    ("prepare", "gmail_tools_unavailable"): "gmail adapter unavailable",
    ("prepare", "verified_identity_required"): "gmail identity unavailable",
    ("replay", "terminal_receipt_invalid"): "terminal run requires operator review",
    ("poll", "poll_failed"): "poll did not complete",
    ("poll", "terminal_persistence_failed"): "poll requires operator review",
    ("discover", "gmail_adapter_failed"): "label discovery failed",
    ("discover", "gmail_transport_failed"): "label discovery failed",
    ("discover", "forbidden"): "label discovery failed",
    ("discover", "rate_limited"): "label discovery failed",
    ("discover", "provider_page_limit_unsplittable"): "label window incomplete",
    ("discover", "provider_thread_id_invalid"): "label result rejected",
    ("discover", "max_threads_reached"): "label window incomplete",
    ("archive", "archive_or_normalize_failed"): "thread not completed",
    ("archive", "gmail_adapter_failed"): "thread not completed",
    ("archive", "gmail_transport_failed"): "thread not completed",
    ("archive", "forbidden"): "thread not completed",
    ("archive", "rate_limited"): "thread not completed",
}
_DEFERRED_EVIDENCE = frozenset({
    ("discover", "max_threads_reached"), ("discover", "provider_page_limit_unsplittable"),
    ("discover", "rate_limited"), ("archive", "rate_limited"),
})
_AUTH_EVIDENCE = frozenset({("prepare", "auth_required")})
_FAILED_EVIDENCE = frozenset({
    ("poll", "poll_failed"), ("poll", "terminal_persistence_failed"),
    ("prepare", "gmail_adapter_failed"), ("prepare", "gmail_transport_failed"),
    ("prepare", "forbidden"), ("prepare", "rate_limited"), ("prepare", "identity_mismatch"),
    ("prepare", "gmail_mapping_invalid"), ("prepare", "gmail_tools_unavailable"),
    ("prepare", "verified_identity_required"), ("archive", "archive_or_normalize_failed"),
    ("archive", "gmail_adapter_failed"), ("archive", "gmail_transport_failed"), ("archive", "forbidden"),
})
_PARTIAL_EVIDENCE = frozenset({
    ("discover", "max_threads_reached"), ("discover", "provider_page_limit_unsplittable"),
    ("discover", "provider_thread_id_invalid"), ("discover", "gmail_adapter_failed"),
    ("discover", "gmail_transport_failed"), ("discover", "forbidden"), ("discover", "rate_limited"),
    ("archive", "archive_or_normalize_failed"), ("archive", "gmail_adapter_failed"),
    ("archive", "gmail_transport_failed"), ("archive", "forbidden"), ("archive", "rate_limited"),
})


class MailRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class MailPollCursor:
    subject_id: int
    identity_id: int
    stream_kind: str
    observed_through_utc: str
    overlap_start_utc: str
    last_successful_run_id: int


def _foundation_manifest_hash() -> str:
    path = Path(__file__).resolve().parents[3] / "harness" / "schemas" / "foundation_schema_manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        return hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    except (OSError, ValueError, TypeError) as exc:
        raise MailRepositoryError("foundation_manifest_unavailable") from exc


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value or len(value) > 40 or not value.endswith("Z"):
        return None
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if instant.tzinfo is None or instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") != value:
        return None
    return instant.astimezone(timezone.utc)


def _canonical_utc(value: object) -> bool:
    return _utc(value) is not None


def _canonical_snapshot(value: dict[str, object]) -> tuple[str, str]:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        digest = hashlib.sha256(
            encoded.encode("utf-8", errors="strict")
        ).hexdigest()
    except (TypeError, ValueError, UnicodeError) as exc:
        raise MailRepositoryError("mail_run_snapshot_invalid") from exc
    return encoded, digest


def _canonical_request_identity(
    request: MailRequest,
) -> tuple[dict[str, object], str, str]:
    """Return the full request identity and its initial snapshot envelope.

    ``requested_at_utc`` is intentionally part of the identity: it is a fixed
    field of the public M4-01 request, and changing it while reusing an
    invocation id is not an exact retry.
    """
    identity = request.to_dict()
    encoded, digest = _canonical_snapshot(
        {"mail_request_identity": identity}
    )
    return identity, encoded, digest


def _strict_json(
    value: object,
    *,
    require_object: bool,
    max_bytes: int,
    error_code: str,
) -> tuple[object, str]:
    """Parse one bounded JSON value and return a stable canonical encoding."""
    if not isinstance(value, str):
        raise MailRepositoryError(error_code)
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise MailRepositoryError(error_code) from exc
    if not raw or len(raw) > max_bytes:
        raise MailRepositoryError(error_code)

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = item
        return result

    def constant(_: str) -> object:
        raise ValueError("non_finite_json_number")

    try:
        parsed = json.loads(value, object_pairs_hook=pairs, parse_constant=constant)
    except (TypeError, ValueError, RecursionError) as exc:
        raise MailRepositoryError(error_code) from exc
    if require_object and not isinstance(parsed, dict):
        raise MailRepositoryError(error_code)

    nodes = 0

    def validate(item: object, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if depth > 24 or nodes > 4096:
            raise MailRepositoryError(error_code)
        if item is None or isinstance(item, (bool, int)):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise MailRepositoryError(error_code)
            return
        if isinstance(item, str):
            try:
                encoded = item.encode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise MailRepositoryError(error_code) from exc
            if len(encoded) > 65_536:
                raise MailRepositoryError(error_code)
            return
        if isinstance(item, list):
            if len(item) > 256:
                raise MailRepositoryError(error_code)
            for child in item:
                validate(child, depth + 1)
            return
        if isinstance(item, dict):
            if len(item) > 256:
                raise MailRepositoryError(error_code)
            for key, child in item.items():
                validate(key, depth + 1)
                validate(child, depth + 1)
            return
        raise MailRepositoryError(error_code)

    validate(parsed, 0)
    try:
        canonical = json.dumps(
            parsed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        canonical.encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise MailRepositoryError(error_code) from exc
    return parsed, canonical


def validate_poll_receipt(receipt: dict[str, object]) -> None:
    """Reject every non-public or structurally ambiguous terminal receipt."""
    if set(receipt) != _POLL_RECEIPT_KEYS:
        raise MailRepositoryError("mail_poll_receipt_shape_invalid")
    if receipt.get("schema_version") != "1" or receipt.get("mode") != "poll":
        raise MailRepositoryError("mail_poll_receipt_shape_invalid")
    for name in ("run_key", "mail_agent_run_id", "invocation_id"):
        if not isinstance(receipt.get(name), str) or not _SAFE_ID.fullmatch(receipt[name]):
            raise MailRepositoryError("mail_poll_receipt_shape_invalid")
    if receipt.get("status") not in _POLL_PUBLIC_TO_RUN_STATUS or receipt.get("next_action") not in _NEXT_ACTIONS:
        raise MailRepositoryError("mail_poll_receipt_shape_invalid")
    counts = receipt.get("counts")
    if not isinstance(counts, dict) or set(counts) != _COUNT_KEYS or any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts.values()):
        raise MailRepositoryError("mail_poll_receipt_shape_invalid")
    for name in ("processed_message_ids", "mail_response_artifact_ids", "mail_delivery_ids"):
        values = receipt.get(name)
        if not isinstance(values, list) or len(values) > 200 or any(not isinstance(value, str) or not _SAFE_ID.fullmatch(value) for value in values):
            raise MailRepositoryError("mail_poll_receipt_shape_invalid")
    for name in ("warnings", "errors"):
        values = receipt.get(name)
        if not isinstance(values, list) or len(values) > 100:
            raise MailRepositoryError("mail_poll_receipt_shape_invalid")
        for item in values:
            if not isinstance(item, dict) or set(item) != {"stage", "code", "summary"}:
                raise MailRepositoryError("mail_poll_receipt_shape_invalid")
            if item["stage"] not in _RECEIPT_STAGES or item["code"] not in _RECEIPT_CODES or _PUBLIC_SUMMARIES.get((item["stage"], item["code"])) != item["summary"]:
                raise MailRepositoryError("mail_poll_receipt_shape_invalid")
    states = receipt.get("poll_state")
    if not isinstance(states, list) or len(states) > 2:
        raise MailRepositoryError("mail_poll_receipt_shape_invalid")
    streams: set[str] = set()
    for item in states:
        if not isinstance(item, dict) or set(item) != {"stream", "status", "window_start_utc", "window_end_utc"}:
            raise MailRepositoryError("mail_poll_receipt_shape_invalid")
        if item["stream"] not in {"trainlab_label", "tracked_threads"} or item["status"] not in {"succeeded", "partial", "deferred"} or not _canonical_utc(item["window_start_utc"]) or not _canonical_utc(item["window_end_utc"]):
            raise MailRepositoryError("mail_poll_receipt_shape_invalid")
        if item["stream"] in streams or _utc(item["window_start_utc"]) > _utc(item["window_end_utc"]):
            raise MailRepositoryError("mail_poll_receipt_shape_invalid")
        streams.add(item["stream"])
    pending = receipt.get("pending_dependencies")
    if not isinstance(pending, list) or len(pending) > 100:
        raise MailRepositoryError("mail_poll_receipt_shape_invalid")
    for item in pending:
        if not isinstance(item, dict) or set(item) != {"mode", "reason_event_id", "artifact_id"} or item["mode"] not in {"revise-plan"} or not all(isinstance(item[key], str) and _SAFE_ID.fullmatch(item[key]) for key in item):
            raise MailRepositoryError("mail_poll_receipt_shape_invalid")
    if receipt.get("next_retry_at_utc") is not None and not _canonical_utc(receipt.get("next_retry_at_utc")):
        raise MailRepositoryError("mail_poll_receipt_shape_invalid")
    started, completed = _utc(receipt.get("started_at_utc")), _utc(receipt.get("completed_at_utc"))
    if started is None or completed is None or started > completed:
        raise MailRepositoryError("mail_poll_receipt_shape_invalid")
    status, action = receipt["status"], receipt["next_action"]
    errors = receipt["errors"]
    evidence = {(item["stage"], item["code"]) for item in errors}
    terminal_success = status in {"succeeded", "unchanged"}
    if terminal_success:
        if streams != {"trainlab_label", "tracked_threads"} or any(item["status"] != "succeeded" for item in states) or errors or receipt["warnings"] or action != "none" or receipt["next_retry_at_utc"] is not None or counts["failed"] or counts["deferred"]:
            raise MailRepositoryError("mail_poll_receipt_semantics_invalid")
    elif status == "partial":
        if streams != {"trainlab_label", "tracked_threads"} or not any(item["status"] == "partial" for item in states) or not errors or not evidence <= _PARTIAL_EVIDENCE or counts["failed"] + counts["deferred"] == 0 or action != "continue_poll" or receipt["next_retry_at_utc"] is not None:
            raise MailRepositoryError("mail_poll_receipt_semantics_invalid")
    elif status == "deferred":
        if not errors or not evidence <= _DEFERRED_EVIDENCE or counts["deferred"] == 0 or counts["failed"] != 0 or action != "continue_poll" or receipt["next_retry_at_utc"] is None or (states and not any(item["status"] == "deferred" for item in states)):
            raise MailRepositoryError("mail_poll_receipt_semantics_invalid")
    elif status == "auth_required":
        if streams or not errors or evidence != _AUTH_EVIDENCE or counts["failed"] == 0 or action != "reauthenticate" or receipt["next_retry_at_utc"] is not None:
            raise MailRepositoryError("mail_poll_receipt_semantics_invalid")
    elif status == "failed":
        if streams or not errors or not evidence <= _FAILED_EVIDENCE or counts["failed"] == 0 or action != "operator_review" or receipt["next_retry_at_utc"] is not None:
            raise MailRepositoryError("mail_poll_receipt_semantics_invalid")
    elif status == "rejected":
        # Poll has no M4-04 rejection publisher yet.  Persisting a fabricated
        # rejected terminal would make a future producer appear to have run.
        raise MailRepositoryError("mail_poll_receipt_semantics_invalid")


def safe_error_summary(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _URL.sub("<redacted-url>", _EMAIL.sub("<redacted-email>", value.replace("\n", " ").replace("\r", " ")))
    return cleaned[:160]


@dataclass(frozen=True)
class MailRun:
    id: int
    run_key: str
    invocation_id: str
    subject_id: int
    mode: str
    status: str
    started_at_utc: str
    completed_at_utc: str | None


@dataclass(frozen=True)
class MailItem:
    id: int
    run_id: int
    logical_item_kind: str
    logical_item_id: str
    stage: str
    status: str
    attempt_count: int


@dataclass(frozen=True)
class InputDraft:
    input_role: str
    source_entity_type: str
    input_sha256: str
    trust_class: str
    source_entity_id: int | None = None
    source_revision_id: int | None = None


@dataclass(frozen=True)
class EventDraft:
    event_type: str
    actor_role: str
    occurred_at_utc: str
    mail_message_id: int | None
    trust_level: str
    created_by: str = "mail_agent"
    related_run_key: str | None = None
    structured_payload_json: str = "{}"


@dataclass(frozen=True)
class FactDraft:
    fact_key: str
    fact_value_json: str
    scope: str
    source_event_type: str
    confidence: float | None = None
    effective_from_utc: str | None = None
    expires_at_utc: str | None = None
    is_active: bool = True
    supersedes_fact_id: int | None = None


@dataclass(frozen=True)
class DeliveryDraft:
    idempotency_key: str
    provider_thread_id: str | None = None


@dataclass(frozen=True)
class AcceptedResponseDraft:
    mail_thread_id: int | None
    in_reply_to_mail_message_id: int | None
    response_kind: str
    schema_version: str
    structured_content_json: str
    user_visible_text: str
    inputs: tuple[InputDraft, ...]
    events: tuple[EventDraft, ...]
    facts: tuple[FactDraft, ...] = ()
    delivery: DeliveryDraft | None = None


@dataclass(frozen=True)
class PublishedResponse:
    response_artifact_id: int
    delivery_id: int | None
    event_ids: tuple[int, ...]
    fact_ids: tuple[int, ...]


@dataclass(frozen=True)
class MailDeliveryState:
    id: int
    status: str
    mail_message_id: int | None
    provider_thread_id: str | None


class MailRepository:
    """Typed mapping over an already-created current Foundation schema."""

    def __init__(self, connection: sqlite3.Connection, *, clock=utc_now) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._clock = clock
        self._verify_foundation_schema()

    def _verify_foundation_schema(self) -> None:
        """Business code only attaches to the current frozen Foundation manifest."""
        try:
            state = self.connection.execute("SELECT state,schema_version,manifest_sha256 FROM foundation_state WHERE id=1").fetchone()
            manifest_path = Path(__file__).resolve().parents[3] / "harness" / "schemas" / "foundation_schema_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if _validate_foundation_schema_manifest(self.connection, manifest):
                raise MailRepositoryError("foundation_schema_incompatible")
            objects = {
                row["name"]: (row["type"], row["tbl_name"], row["sql"])
                for row in self.connection.execute(
                    "SELECT name,type,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            expected_objects = (
                {name: "table" for name in manifest["tables"]}
                | {name: "view" for name in manifest["views"]}
                | {name: "index" for name in _FOUNDATION_INDEX_SQL}
                | {name: "trigger" for name in _FOUNDATION_TRIGGER_SQL}
            )
            if {name: value[0] for name, value in objects.items()} != expected_objects:
                raise MailRepositoryError("foundation_schema_incompatible")
            for name, definition in manifest["tables"].items():
                if name == "schema_migrations":
                    expected_definition = "version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at_utc TEXT NOT NULL, code_revision TEXT NOT NULL DEFAULT 'foundation-v1', content_sha256 TEXT NOT NULL"
                else:
                    expected_definition = _FOUNDATION_TABLES.get(name)
                if expected_definition is None or objects.get(name, (None, None, None))[0] != "table":
                    raise MailRepositoryError("foundation_schema_incompatible")
                actual_sql = objects[name][2]
                if not isinstance(actual_sql, str) or self._normal_sql(actual_sql) != self._normal_sql(f"CREATE TABLE {name} ({expected_definition})"):
                    raise MailRepositoryError("foundation_schema_incompatible")
            for name, query in _FOUNDATION_VIEWS.items():
                actual = objects.get(name)
                if actual is None or actual[0] != "view" or not isinstance(actual[2], str) or self._normal_sql(actual[2]) != self._normal_sql(f"CREATE VIEW {name} AS {query}"):
                    raise MailRepositoryError("foundation_schema_incompatible")
            for name, expected_sql in _FOUNDATION_INDEX_SQL.items():
                actual = objects.get(name)
                table, unique, partial, columns = _FOUNDATION_INDEX_METADATA[name]
                metadata = self.connection.execute(
                    f"SELECT name,\"unique\",origin,partial FROM pragma_index_list('{table}') WHERE name=?",
                    (name,),
                ).fetchall()
                actual_columns = tuple(
                    row["name"]
                    for row in self.connection.execute(
                        f"SELECT name FROM pragma_index_info('{name}') ORDER BY seqno"
                    ).fetchall()
                )
                if (
                    actual is None
                    or actual[0] != "index"
                    or actual[1] != table
                    or not isinstance(actual[2], str)
                    or self._normal_sql(actual[2]) != self._normal_sql(expected_sql)
                    or len(metadata) != 1
                    or tuple(metadata[0]) != (name, int(unique), "c", int(partial))
                    or actual_columns != columns
                ):
                    raise MailRepositoryError("foundation_schema_incompatible")
            for name, expected_sql in _FOUNDATION_TRIGGER_SQL.items():
                actual = objects.get(name)
                expected_table = manifest["triggers"][name]["table"]
                if (
                    actual is None
                    or actual[0] != "trigger"
                    or actual[1] != expected_table
                    or not isinstance(actual[2], str)
                    or self._normal_sql(actual[2]) != self._normal_sql(expected_sql)
                ):
                    raise MailRepositoryError("foundation_schema_incompatible")
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
            raise MailRepositoryError("foundation_schema_unavailable") from exc
        if (
            state is None
            or state["state"] != "ready"
            or state["schema_version"] != FOUNDATION_SCHEMA_VERSION
            or state["manifest_sha256"] != _foundation_manifest_hash()
        ):
            raise MailRepositoryError("foundation_schema_incompatible")
        if not _FoundationTool._migration_receipt_valid(self.connection, state["manifest_sha256"]):
            raise MailRepositoryError("foundation_migration_incompatible")

    @staticmethod
    def _normal_sql(value: str) -> str:
        return "".join(value.lower().replace('"', "").replace("'", "'").split())

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        if self.connection.in_transaction:
            raise MailRepositoryError("repository_requires_no_outer_transaction")
        self._verify_foundation_schema()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except sqlite3.IntegrityError as exc:
            self.connection.execute("ROLLBACK")
            raise MailRepositoryError("mail_repository_constraint_violation") from exc
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        else:
            try:
                # Recheck immediately before publication: a caller may have
                # constructed the repository before Foundation was repaired or
                # replaced underneath this connection.
                self._verify_foundation_schema()
                self.connection.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise MailRepositoryError("mail_repository_constraint_violation") from exc
            except Exception:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _run(row: sqlite3.Row) -> MailRun:
        return MailRun(row["id"], row["run_key"], row["invocation_id"], row["subject_id"], row["request_kind"], row["status"], row["started_at_utc"], row["completed_at_utc"])

    @staticmethod
    def _item(row: sqlite3.Row) -> MailItem:
        return MailItem(row["id"], row["mail_agent_run_id"], row["logical_item_kind"], row["logical_item_id"], row["stage"], row["status"], row["attempt_count"])

    @staticmethod
    def _decode_run_snapshot(
        row: sqlite3.Row, *, verify_digest: bool
    ) -> tuple[dict[str, object], str]:
        try:
            parsed, canonical = _strict_json(
                row["context_snapshot_json"],
                require_object=True,
                max_bytes=1_000_000,
                error_code="mail_run_snapshot_invalid",
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise MailRepositoryError("mail_run_snapshot_invalid") from exc
        assert isinstance(parsed, dict)
        if (
            set(parsed) - {"mail_request_identity", "mail_poll_receipt"}
            or not isinstance(parsed.get("mail_request_identity"), dict)
            or row["context_snapshot_json"] != canonical
        ):
            raise MailRepositoryError("mail_run_snapshot_invalid")
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if verify_digest and row["context_snapshot_sha256"] != digest:
            raise MailRepositoryError("mail_run_snapshot_integrity_invalid")
        return parsed, canonical

    def start_or_resume_run(self, request: MailRequest) -> MailRun:
        if request.mode == "status":
            raise MailRepositoryError("status_is_read_only")
        request_identity, initial_snapshot, initial_snapshot_sha256 = (
            _canonical_request_identity(request)
        )
        with self._write_transaction():
            existing = self.connection.execute("SELECT * FROM mail_agent_runs WHERE invocation_id=?", (request.invocation_id,)).fetchone()
            if existing is not None:
                run = self._run(existing)
                try:
                    snapshot, _ = self._decode_run_snapshot(
                        existing, verify_digest=True
                    )
                except MailRepositoryError as exc:
                    raise MailRepositoryError(
                        "invocation_id_conflicts_with_existing_run"
                    ) from exc
                if (
                    run.subject_id != request.subject_id
                    or run.mode != request.mode
                    or run.run_key != request.stable_run_key
                    or snapshot.get("mail_request_identity") != request_identity
                ):
                    raise MailRepositoryError("invocation_id_conflicts_with_existing_run")
                return run
            now = self._clock()
            self.connection.execute(
                "INSERT INTO mail_agent_runs(run_key,invocation_id,subject_id,request_kind,status,context_snapshot_json,context_snapshot_sha256,started_at_utc) VALUES(?,?,?,?,?,?,?,?)",
                (
                    request.stable_run_key,
                    request.invocation_id,
                    request.subject_id,
                    request.mode,
                    "started",
                    initial_snapshot,
                    initial_snapshot_sha256,
                    now,
                ),
            )
            row = self.connection.execute("SELECT * FROM mail_agent_runs WHERE invocation_id=?", (request.invocation_id,)).fetchone()
            assert row is not None
            return self._run(row)

    def get_run(self, run_key: str) -> MailRun | None:
        self._verify_foundation_schema()
        row = self.connection.execute("SELECT * FROM mail_agent_runs WHERE run_key=?", (run_key,)).fetchone()
        return None if row is None else self._run(row)

    def save_poll_receipt(self, run_id: int, receipt: dict[str, object]) -> None:
        """Persist only the already-sanitized public receipt for terminal replay."""
        validate_poll_receipt(receipt)
        with self._write_transaction():
            row = self.connection.execute(
                "SELECT * FROM mail_agent_runs WHERE id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise MailRepositoryError("mail_run_not_found")
            snapshot, _ = self._decode_run_snapshot(row, verify_digest=True)
            existing_receipt = snapshot.get("mail_poll_receipt")
            snapshot["mail_poll_receipt"] = receipt
            encoded, digest = _canonical_snapshot(snapshot)
            if row["status"] != "started":
                if existing_receipt != receipt or row["context_snapshot_json"] != encoded:
                    raise MailRepositoryError("conflicting_mail_poll_receipt")
                return
            if existing_receipt is not None and existing_receipt != receipt:
                raise MailRepositoryError("conflicting_mail_poll_receipt")
            if row["context_snapshot_json"] != encoded:
                self.connection.execute(
                    "UPDATE mail_agent_runs SET context_snapshot_json=?,"
                    "context_snapshot_sha256=? WHERE id=?",
                    (encoded, digest, run_id),
                )

    def finish_poll_with_receipt(self, run_id: int, status: str, receipt: dict[str, object]) -> MailRun:
        """Commit terminal run state and its sanitized replay receipt together."""
        with self._write_transaction():
            validate_poll_receipt(receipt)
            row = self.connection.execute("SELECT * FROM mail_agent_runs WHERE id=?", (run_id,)).fetchone()
            if row is None or status not in _RUN_TRANSITIONS.get(row["status"], set()):
                raise MailRepositoryError("illegal_mail_run_transition")
            public_status = receipt.get("status")
            if not isinstance(public_status, str) or _POLL_PUBLIC_TO_RUN_STATUS.get(public_status) != status:
                raise MailRepositoryError("mail_poll_receipt_status_mismatch")
            if (
                receipt.get("run_key") != row["run_key"]
                or receipt.get("invocation_id") != row["invocation_id"]
                or receipt.get("mode") != row["request_kind"]
                or receipt.get("mail_agent_run_id") != str(run_id)
            ):
                raise MailRepositoryError("mail_poll_receipt_run_mismatch")
            completed = receipt.get("completed_at_utc")
            if not isinstance(completed, str) or not completed:
                raise MailRepositoryError("mail_poll_receipt_incomplete")
            next_retry = receipt.get("next_retry_at_utc")
            if next_retry is not None and not isinstance(next_retry, str):
                raise MailRepositoryError("mail_poll_receipt_invalid_retry")
            snapshot, _ = self._decode_run_snapshot(row, verify_digest=True)
            existing_receipt = snapshot.get("mail_poll_receipt")
            snapshot["mail_poll_receipt"] = receipt
            encoded, digest = _canonical_snapshot(snapshot)
            if row["status"] != "started":
                if (row["status"] != status or row["context_snapshot_json"] != encoded
                    or row["context_snapshot_sha256"] != digest
                    or row["completed_at_utc"] != completed or row["next_retry_at_utc"] != next_retry):
                    raise MailRepositoryError("conflicting_mail_poll_receipt")
                return self._run(row)
            if existing_receipt is not None and existing_receipt != receipt:
                raise MailRepositoryError("conflicting_mail_poll_receipt")
            self.connection.execute(
                "UPDATE mail_agent_runs SET status=?,context_snapshot_json=?,"
                "context_snapshot_sha256=?,next_retry_at_utc=?,completed_at_utc=? "
                "WHERE id=?",
                (status, encoded, digest, next_retry, completed, run_id),
            )
            updated = self.connection.execute("SELECT * FROM mail_agent_runs WHERE id=?", (run_id,)).fetchone()
            assert updated is not None
            return self._run(updated)

    def load_poll_receipt(self, run_id: int) -> dict[str, object] | None:
        self._verify_foundation_schema()
        row = self.connection.execute(
            "SELECT * FROM mail_agent_runs WHERE id=?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        snapshot, _ = self._decode_run_snapshot(row, verify_digest=True)
        value = snapshot.get("mail_poll_receipt")
        if not isinstance(value, dict):
            return None
        validate_poll_receipt(value)
        return value

    def status(self, request: MailRequest) -> MailRun | None:
        self._verify_foundation_schema()
        if request.mode != "status":
            raise MailRepositoryError("status_request_required")
        if request.run_key:
            return self.get_run(request.run_key)
        if request.mail_message_ids:
            row = self.connection.execute(
                "SELECT r.* FROM mail_agent_runs r JOIN mail_agent_items i ON i.mail_agent_run_id=r.id JOIN mail_messages m ON m.id=i.mail_message_id WHERE m.provider_message_id=? ORDER BY r.id DESC LIMIT 1",
                (request.mail_message_ids[0],),
            ).fetchone()
            return None if row is None else self._run(row)
        return None

    def get_poll_cursor(self, subject_id: int, identity_id: int, stream_kind: str) -> MailPollCursor | None:
        self._verify_foundation_schema()
        if stream_kind not in {"trainlab_label", "tracked_threads"} or subject_id <= 0 or identity_id <= 0:
            raise MailRepositoryError("invalid_mail_poll_cursor")
        row = self.connection.execute(
            "SELECT subject_id,identity_id,stream_kind,observed_through_utc,overlap_start_utc,last_successful_run_id FROM mail_poll_cursors WHERE subject_id=? AND identity_id=? AND stream_kind=?",
            (subject_id, identity_id, stream_kind),
        ).fetchone()
        if row is None:
            return None
        if not _canonical_utc(row["observed_through_utc"]) or not _canonical_utc(row["overlap_start_utc"]) or _utc(row["overlap_start_utc"]) > _utc(row["observed_through_utc"]) or not isinstance(row["last_successful_run_id"], int):
            raise MailRepositoryError("invalid_mail_poll_cursor")
        return MailPollCursor(*tuple(row))

    def advance_poll_cursor(self, run_id: int, subject_id: int, identity_id: int, stream_kind: str, observed_through_utc: str, overlap_start_utc: str, *, stream_completed: bool = True) -> MailPollCursor:
        if not isinstance(stream_completed, bool) or not stream_completed or stream_kind not in {"trainlab_label", "tracked_threads"} or not _canonical_utc(observed_through_utc) or not _canonical_utc(overlap_start_utc) or _utc(overlap_start_utc) > _utc(observed_through_utc):
            raise MailRepositoryError("invalid_mail_poll_cursor")
        with self._write_transaction():
            run = self.connection.execute("SELECT subject_id,request_kind,status FROM mail_agent_runs WHERE id=?", (run_id,)).fetchone()
            identity = self.connection.execute("SELECT subject_id,provider,identity_kind,is_verified FROM subject_identities WHERE id=?", (identity_id,)).fetchone()
            if (run is None or run["subject_id"] != subject_id or run["request_kind"] not in {"poll", "run"}
                or run["status"] not in {"started", "partial", "deferred"}
                or identity is None or identity["subject_id"] != subject_id or identity["provider"] != "gmail" or identity["identity_kind"] != "email" or identity["is_verified"] != 1):
                raise MailRepositoryError("mail_poll_cursor_ownership_invalid")
            previous = self.connection.execute("SELECT observed_through_utc FROM mail_poll_cursors WHERE subject_id=? AND identity_id=? AND stream_kind=?", (subject_id, identity_id, stream_kind)).fetchone()
            if previous is not None and (not _canonical_utc(previous[0]) or _utc(observed_through_utc) < _utc(previous[0])):
                raise MailRepositoryError("mail_poll_cursor_regression")
            self.connection.execute(
                "INSERT INTO mail_poll_cursors(subject_id,identity_id,stream_kind,observed_through_utc,overlap_start_utc,last_successful_run_id,updated_at_utc) VALUES(?,?,?,?,?,?,?) ON CONFLICT(subject_id,identity_id,stream_kind) DO UPDATE SET observed_through_utc=excluded.observed_through_utc,overlap_start_utc=excluded.overlap_start_utc,last_successful_run_id=excluded.last_successful_run_id,updated_at_utc=excluded.updated_at_utc",
                (subject_id, identity_id, stream_kind, observed_through_utc, overlap_start_utc, run_id, self._clock()),
            )
            row = self.connection.execute("SELECT subject_id,identity_id,stream_kind,observed_through_utc,overlap_start_utc,last_successful_run_id FROM mail_poll_cursors WHERE subject_id=? AND identity_id=? AND stream_kind=?", (subject_id, identity_id, stream_kind)).fetchone()
            assert row is not None
            return MailPollCursor(*tuple(row))

    def set_message_processing_state(
        self,
        subject_id: int,
        mail_message_id: int,
        state: str,
        *,
        recovery_kind: str = "normal",
    ) -> None:
        allowed = {"discovered", "archived", "normalized", "queued", "analyzing", "response_accepted", "ready_to_send", "sending", "sent", "store_only", "ignored", "quarantined", "awaiting_analysis", "deferred", "rejected", "failed", "delivery_unknown", "new", "processed", "error"}
        if (
            not isinstance(state, str)
            or state not in allowed
            or not isinstance(recovery_kind, str)
            or recovery_kind not in {
                "normal",
                "repair",
                "reconcile",
                "crash_recovery",
                "quarantine",
            }
        ):
            raise MailRepositoryError("invalid_mail_message_processing_state")
        with self._write_transaction():
            row = self.connection.execute("SELECT m.id,m.processing_state FROM mail_messages m JOIN mail_threads t ON t.id=m.mail_thread_id WHERE m.id=? AND t.subject_id=?", (mail_message_id, subject_id)).fetchone()
            if row is None:
                raise MailRepositoryError("mail_message_ownership_invalid")
            graph = {
                "new": {"discovered"},
                "discovered": {"archived", "ignored", "failed"}, "archived": {"normalized", "ignored", "failed"},
                "normalized": {"queued", "store_only", "ignored", "awaiting_analysis", "deferred", "rejected", "failed"},
                "queued": {"analyzing", "deferred", "rejected", "failed"}, "analyzing": {"response_accepted", "deferred", "rejected", "failed"},
                "awaiting_analysis": {"queued", "deferred", "rejected", "failed"}, "deferred": {"queued", "analyzing", "awaiting_analysis", "failed", "rejected"},
                "response_accepted": {"ready_to_send", "store_only", "failed"}, "ready_to_send": {"sending", "store_only", "failed"},
                "sending": {"sent", "delivery_unknown", "failed"}, "delivery_unknown": set(),
                "store_only": set(), "ignored": set(), "rejected": set(), "failed": set(), "sent": set(), "processed": set(), "error": set(),
            }
            current = row["processing_state"]
            if current == state:
                if state == "sent" and not self._message_has_verified_delivery(
                    subject_id, mail_message_id
                ):
                    raise MailRepositoryError(
                        "mail_message_delivery_evidence_required"
                    )
                return
            if current == "delivery_unknown":
                permitted = recovery_kind == "reconcile" and state in {"sent", "deferred", "failed"}
            elif current == "analyzing" and state == "queued":
                accepted = self.connection.execute(
                    "SELECT 1 FROM mail_response_artifacts "
                    "WHERE subject_id=? AND in_reply_to_mail_message_id=? LIMIT 1",
                    (subject_id, mail_message_id),
                ).fetchone()
                permitted = recovery_kind == "crash_recovery" and accepted is None
            elif current == "normalized" and state == "quarantined":
                permitted = recovery_kind == "quarantine"
            elif current in {"failed", "rejected", "quarantined"}:
                permitted = recovery_kind == "repair" and state == "queued"
            else:
                permitted = recovery_kind == "normal" and state in graph.get(current, set())
            if not permitted:
                raise MailRepositoryError("illegal_mail_message_transition")
            if state == "sent" and not self._message_has_verified_delivery(
                subject_id, mail_message_id
            ):
                raise MailRepositoryError("mail_message_delivery_evidence_required")
            self.connection.execute("UPDATE mail_messages SET processing_state=? WHERE id=?", (state, mail_message_id))

    def _message_has_verified_delivery(
        self, subject_id: int, trigger_mail_message_id: int
    ) -> bool:
        """Require an exact accepted-response/delivery/outbound-message chain."""
        rows = self.connection.execute(
            "SELECT d.sent_at_utc,d.last_verified_at_utc "
            "FROM mail_response_artifacts r "
            "JOIN mail_agent_runs rr ON rr.id=r.generated_by_mail_agent_run_id "
            "JOIN mail_threads rt ON rt.id=r.mail_thread_id "
            "JOIN mail_messages trigger ON trigger.id=r.in_reply_to_mail_message_id "
            "JOIN mail_delivery_artifacts da ON da.mail_response_artifact_id=r.id "
            "AND da.content_role='mail_response' AND da.ordinal=0 "
            "JOIN mail_deliveries d ON d.id=da.mail_delivery_id "
            "JOIN mail_messages outbound ON outbound.id=d.mail_message_id "
            "JOIN mail_threads ot ON ot.id=outbound.mail_thread_id "
            "WHERE r.subject_id=? AND rr.subject_id=? "
            "AND r.in_reply_to_mail_message_id=? "
            "AND trigger.mail_thread_id=r.mail_thread_id "
            "AND rt.subject_id=? AND ot.subject_id=? "
            "AND outbound.mail_thread_id=r.mail_thread_id "
            "AND outbound.actor_role='trainlab' "
            "AND outbound.direction IN ('outbound','self_copy') "
            "AND d.status IN ('sent','already_sent') "
            "AND d.provider_thread_id=rt.provider_thread_id "
            "AND d.provider_thread_id=ot.provider_thread_id "
            "AND d.related_run_key=rr.run_key "
            "AND d.error_code IS NULL AND d.error_summary IS NULL "
            "AND (SELECT count(*) FROM mail_delivery_artifacts x "
            "WHERE x.mail_delivery_id=d.id)=1",
            (
                subject_id,
                subject_id,
                trigger_mail_message_id,
                subject_id,
                subject_id,
            ),
        ).fetchall()
        return (
            len(rows) == 1
            and _canonical_utc(rows[0]["sent_at_utc"])
            and _canonical_utc(rows[0]["last_verified_at_utc"])
        )

    def transition_delivery_state(
        self,
        subject_id: int,
        mail_delivery_id: int,
        status: str,
        *,
        recovery_kind: str = "normal",
        mail_message_id: int | None = None,
        provider_thread_id: str | None = None,
        sent_at_utc: str | None = None,
        last_verified_at_utc: str | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> MailDeliveryState:
        """Persist delivery evidence only; this method never invokes a provider."""
        statuses = {"pending", "sending", "sent", "already_sent", "delivery_unknown", "failed"}
        if (
            not isinstance(subject_id, int)
            or isinstance(subject_id, bool)
            or subject_id <= 0
            or not isinstance(mail_delivery_id, int)
            or isinstance(mail_delivery_id, bool)
            or mail_delivery_id <= 0
            or status not in statuses
            or recovery_kind not in {"normal", "repair", "reconcile"}
            or (mail_message_id is not None and (
                not isinstance(mail_message_id, int)
                or isinstance(mail_message_id, bool)
                or mail_message_id <= 0
            ))
            or (provider_thread_id is not None and not _SAFE_ID.fullmatch(provider_thread_id))
            or (sent_at_utc is not None and not _canonical_utc(sent_at_utc))
            or (last_verified_at_utc is not None and not _canonical_utc(last_verified_at_utc))
            or (error_code is not None and not _SAFE_CODE.fullmatch(error_code))
        ):
            raise MailRepositoryError("invalid_mail_delivery_transition")
        with self._write_transaction():
            rows = self.connection.execute(
                "SELECT d.*,r.subject_id,r.mail_thread_id,t.provider_thread_id AS response_thread_id "
                "FROM mail_deliveries d "
                "JOIN mail_delivery_artifacts a ON a.mail_delivery_id=d.id "
                "JOIN mail_response_artifacts r ON r.id=a.mail_response_artifact_id "
                "LEFT JOIN mail_threads t ON t.id=r.mail_thread_id "
                "WHERE d.id=? AND a.content_role='mail_response' AND a.ordinal=0",
                (mail_delivery_id,),
            ).fetchall()
            if len(rows) != 1 or rows[0]["subject_id"] != subject_id:
                raise MailRepositoryError("mail_delivery_ownership_invalid")
            row = rows[0]
            current = row["status"]
            if current == status:
                replay_error_code = (
                    row["error_code"] if error_code is None else error_code
                )
                replay_error_summary = (
                    row["error_summary"]
                    if error_code is None and error_summary is None
                    else "mail delivery did not complete"
                    if replay_error_code is not None
                    else None
                )
                wanted = (
                    row["mail_message_id"] if mail_message_id is None else mail_message_id,
                    row["provider_thread_id"] if provider_thread_id is None else provider_thread_id,
                    row["sent_at_utc"] if sent_at_utc is None else sent_at_utc,
                    row["last_verified_at_utc"] if last_verified_at_utc is None else last_verified_at_utc,
                    replay_error_code,
                    replay_error_summary,
                )
                existing = (
                    row["mail_message_id"],
                    row["provider_thread_id"],
                    row["sent_at_utc"],
                    row["last_verified_at_utc"],
                    row["error_code"],
                    row["error_summary"],
                )
                if wanted != existing:
                    raise MailRepositoryError("conflicting_mail_delivery_replay")
                return MailDeliveryState(row["id"], current, row["mail_message_id"], row["provider_thread_id"])
            normal = {
                "pending": {"sending", "failed"},
                "sending": {"sent", "delivery_unknown", "failed"},
            }
            if current == "delivery_unknown":
                permitted = recovery_kind == "reconcile" and status in {"sent", "already_sent", "failed"}
            elif current == "failed":
                permitted = recovery_kind == "repair" and status == "pending"
            elif current == "pending" and status == "already_sent":
                permitted = recovery_kind == "reconcile"
            else:
                permitted = recovery_kind == "normal" and status in normal.get(current, set())
            if not permitted:
                raise MailRepositoryError("illegal_mail_delivery_transition")

            effective_message_id = row["mail_message_id"] if mail_message_id is None else mail_message_id
            effective_thread_id = row["provider_thread_id"] if provider_thread_id is None else provider_thread_id
            if row["mail_message_id"] is not None and mail_message_id not in {None, row["mail_message_id"]}:
                raise MailRepositoryError("conflicting_mail_delivery_message")
            if row["provider_thread_id"] is not None and provider_thread_id not in {None, row["provider_thread_id"]}:
                raise MailRepositoryError("conflicting_mail_delivery_thread")
            if effective_thread_id is not None and row["response_thread_id"] not in {None, effective_thread_id}:
                raise MailRepositoryError("mail_delivery_thread_mismatch")
            if effective_message_id is not None:
                message = self.connection.execute(
                    "SELECT m.id,m.mail_thread_id,m.actor_role,m.direction,t.provider_thread_id "
                    "FROM mail_messages m JOIN mail_threads t ON t.id=m.mail_thread_id "
                    "WHERE m.id=? AND t.subject_id=?",
                    (effective_message_id, subject_id),
                ).fetchone()
                if (
                    message is None
                    or message["actor_role"] != "trainlab"
                    or message["direction"] not in {"outbound", "self_copy"}
                    or (
                        row["mail_thread_id"] is not None
                        and message["mail_thread_id"] != row["mail_thread_id"]
                    )
                ):
                    raise MailRepositoryError("mail_delivery_message_ownership_invalid")
            if status in {"sent", "already_sent"} and (
                effective_message_id is None
                or sent_at_utc is None
                or last_verified_at_utc is None
            ):
                raise MailRepositoryError("mail_delivery_evidence_required")
            stored_summary = None if error_code is None else "mail delivery did not complete"
            self.connection.execute(
                "UPDATE mail_deliveries SET mail_message_id=?,provider_thread_id=?,status=?,"
                "sent_at_utc=?,last_verified_at_utc=?,error_code=?,error_summary=?,updated_at_utc=? "
                "WHERE id=?",
                (
                    effective_message_id,
                    effective_thread_id,
                    status,
                    sent_at_utc,
                    last_verified_at_utc,
                    error_code,
                    stored_summary,
                    self._clock(),
                    mail_delivery_id,
                ),
            )
            return MailDeliveryState(mail_delivery_id, status, effective_message_id, effective_thread_id)

    def classify_normalized_message(
        self,
        run_id: int,
        subject_id: int,
        mail_message_id: int,
        message: CanonicalMessage,
        evidence: ActorEvidence,
    ) -> Classification:
        """Persist one M4-05 decision atomically and idempotently.

        The method is intentionally called only after normalization.  It never
        creates work for an outbound/unknown item, and a terminal replay is a
        no-op rather than a second event.
        """
        with self._write_transaction():
            return self._classify_normalized_message_txn(run_id, subject_id, mail_message_id, message, evidence.tracked_thread, evidence.has_run_header, evidence.trainlab_label)

    def _classify_normalized_message_txn(
        self, run_id: int, subject_id: int, mail_message_id: int, supplied: CanonicalMessage,
        tracked_thread: bool, has_run_header: bool, thread_or_message_label: bool = False,
    ) -> Classification:
        """The sole classifier/persistence implementation; caller owns txn."""
        row = self.connection.execute(
            "SELECT m.processing_state,m.direction,m.actor_role,m.provider_message_id,m.labels_json,m.subject,m.body_text,m.received_at_utc,"
            "t.provider_thread_id FROM mail_messages m JOIN mail_threads t ON t.id=m.mail_thread_id "
            "WHERE m.id=? AND t.subject_id=?", (mail_message_id, subject_id),
        ).fetchone()
        run = self.connection.execute("SELECT subject_id FROM mail_agent_runs WHERE id=?", (run_id,)).fetchone()
        if row is None or run is None or run["subject_id"] != subject_id:
            raise MailRepositoryError("mail_message_ownership_invalid")
        try:
            labels = frozenset(json.loads(row["labels_json"]))
        except (TypeError, ValueError):
            raise MailRepositoryError("canonical_mail_labels_invalid")
        if (supplied.provider_message_id != row["provider_message_id"] or supplied.labels != labels
                or supplied.subject != row["subject"] or (supplied.body_text or "") != (row["body_text"] or "")):
            raise MailRepositoryError("classification_evidence_conflicts_with_canonical_message")
        attachment_count = self.connection.execute("SELECT count(*) FROM mail_attachments WHERE mail_message_id=?", (mail_message_id,)).fetchone()[0]
        local = bool(self.connection.execute(
            "SELECT EXISTS(SELECT 1 FROM mail_messages o WHERE o.provider_message_id=? AND o.direction='outbound' AND o.actor_role='trainlab') "
            "OR EXISTS(SELECT 1 FROM analysis_deliveries a WHERE a.subject_id=? AND a.provider_message_id=? AND a.status IN ('sent','already_sent')) "
            "OR EXISTS(SELECT 1 FROM mail_deliveries d JOIN mail_messages o ON o.id=d.mail_message_id WHERE o.provider_message_id=? AND o.direction='outbound' AND o.actor_role='trainlab' AND d.status IN ('sent','already_sent'))",
            (row["provider_message_id"], subject_id, row["provider_message_id"], row["provider_message_id"]),
        ).fetchone()[0])
        canonical = CanonicalMessage(row["provider_message_id"], supplied.sender_is_self, supplied.recipient_is_self,
                                     labels, row["subject"], row["body_text"], attachment_count,
                                     supplied.auto_submitted, supplied.is_bounce, supplied.is_complete)
        result = classify(canonical, ActorEvidence(local, tracked_thread, TRAINLAB_LABEL in labels or thread_or_message_label, has_run_header))
        if row["processing_state"] != "normalized":
            return Classification(row["actor_role"], row["direction"], row["processing_state"], "mail_classification_replay", "already_terminal", False)
        self.connection.execute("UPDATE mail_messages SET actor_role=?,direction=?,processing_state=? WHERE id=?", (result.actor_role, result.direction, result.processing_state, mail_message_id))
        event_trust = (
            "system_generated"
            if result.actor_role == "trainlab"
            else "untrusted_content"
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO conversation_events(subject_id,event_type,actor_role,occurred_at_utc,mail_message_id,related_run_key,structured_payload_json,trust_level,created_by) VALUES(?,?,?,?,?,(SELECT run_key FROM mail_agent_runs WHERE id=?),?,?,'mail_agent')",
            (subject_id, result.event_type, result.actor_role, row["received_at_utc"], mail_message_id, run_id, json.dumps({"reason_code": result.reason_code}, sort_keys=True), event_trust),
        )
        self.connection.execute(
            "INSERT INTO mail_agent_items(mail_agent_run_id,logical_item_kind,logical_item_id,mail_message_id,stage,status,attempt_count,started_at_utc,completed_at_utc) VALUES(?,?,?,?,?,'succeeded',1,?,?) ON CONFLICT(mail_agent_run_id,logical_item_kind,logical_item_id,stage) DO NOTHING",
            (run_id, "message", row["provider_message_id"], mail_message_id, "classify", self._clock(), self._clock()),
        )
        return result

    def select_queued_messages(self, subject_id: int, *, limit: int = 100) -> tuple[int, ...]:
        """Return the only AI-eligible state in stable provider order."""
        if not isinstance(subject_id, int) or isinstance(subject_id, bool) or subject_id <= 0 or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise MailRepositoryError("invalid_mail_queue_selector")
        self._verify_foundation_schema()
        rows = self.connection.execute(
            "SELECT m.id FROM mail_messages m JOIN mail_threads t ON t.id=m.mail_thread_id "
            "WHERE t.subject_id=? AND m.processing_state='queued' "
            "ORDER BY m.received_at_utc ASC, m.provider_message_id ASC, m.id ASC LIMIT ?",
            (subject_id, limit),
        ).fetchall()
        return tuple(int(row[0]) for row in rows)

    def finish_run(self, run_id: int, status: str, *, next_retry_at_utc: str | None = None) -> MailRun:
        if (
            not isinstance(run_id, int)
            or isinstance(run_id, bool)
            or run_id <= 0
            or not isinstance(status, str)
            or status not in _RUN_TRANSITIONS
            or (
                next_retry_at_utc is not None
                and not _canonical_utc(next_retry_at_utc)
            )
            or (status != "deferred" and next_retry_at_utc is not None)
        ):
            raise MailRepositoryError("invalid_mail_run_evidence")
        with self._write_transaction():
            row = self.connection.execute("SELECT * FROM mail_agent_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise MailRepositoryError("mail_run_not_found")
            current = row["status"]
            if status not in _RUN_TRANSITIONS.get(current, set()):
                raise MailRepositoryError("illegal_mail_run_transition")
            if (
                status == "deferred"
                and next_retry_at_utc is None
                and self.connection.execute(
                    "SELECT 1 FROM mail_agent_items i "
                    "LEFT JOIN analysis_artifacts a "
                    "ON a.id=i.dependency_analysis_artifact_id "
                    "LEFT JOIN analysis_runs ar ON ar.id=a.generated_by_run_id "
                    "LEFT JOIN mail_messages m ON m.id=i.mail_message_id "
                    "LEFT JOIN mail_threads t ON t.id=m.mail_thread_id "
                    "LEFT JOIN conversation_events e "
                    "ON e.mail_message_id=i.mail_message_id "
                    "AND e.event_type='plan_revision_reason_recorded' "
                    "WHERE i.mail_agent_run_id=? AND i.status='deferred' "
                    "AND i.next_retry_at_utc IS NULL "
                    "AND i.error_code IS NULL AND i.error_summary IS NULL "
                    "AND i.stage IN ('context','generate') "
                    "AND ("
                    "(a.id IS NOT NULL AND a.subject_id=? AND ar.subject_id=?) "
                    "OR (i.logical_item_kind='plan_revision_dependency' "
                    "AND i.logical_item_id='plan_revision:'||e.id "
                    "AND i.dependency_analysis_artifact_id IS NULL "
                    "AND m.processing_state='awaiting_analysis' "
                    "AND t.subject_id=? AND e.subject_id=? "
                    "AND e.actor_role='trainlab' "
                    "AND e.trust_level='system_generated')"
                    ") LIMIT 1",
                    (
                        run_id,
                        row["subject_id"],
                        row["subject_id"],
                        row["subject_id"],
                        row["subject_id"],
                    ),
                ).fetchone()
                is None
            ):
                raise MailRepositoryError("mail_run_deferred_evidence_required")
            if status == current and row["next_retry_at_utc"] != next_retry_at_utc:
                raise MailRepositoryError("conflicting_mail_run_replay")
            if status != current:
                self.connection.execute("UPDATE mail_agent_runs SET status=?,next_retry_at_utc=?,completed_at_utc=? WHERE id=?", (status, next_retry_at_utc, self._clock() if status != "started" else None, run_id))
            updated = self.connection.execute("SELECT * FROM mail_agent_runs WHERE id=?", (run_id,)).fetchone()
            assert updated is not None
            return self._run(updated)

    def record_item(self, run_id: int, *, logical_item_kind: str, logical_item_id: str, stage: str, status: str, mail_message_id: int | None = None, dependency_analysis_artifact_id: int | None = None, mail_response_artifact_id: int | None = None, mail_delivery_id: int | None = None, error_code: str | None = None, error_summary: str | None = None, next_retry_at_utc: str | None = None) -> MailItem:
        if (not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0
            or not isinstance(logical_item_kind, str) or not _SAFE_CODE.fullmatch(logical_item_kind)
            or not isinstance(logical_item_id, str) or not _SAFE_ID.fullmatch(logical_item_id)
            or not isinstance(stage, str) or stage not in _STAGES
            or not isinstance(status, str) or status not in _ITEM_TRANSITIONS
            or (error_code is not None and (
                not isinstance(error_code, str) or error_code not in _ITEM_CODES
            ))
            or (error_summary is not None and not isinstance(error_summary, str))
            or (next_retry_at_utc is not None and not _canonical_utc(next_retry_at_utc))):
            raise MailRepositoryError("invalid_mail_item_stage_or_status")
        for relation in (
            mail_message_id,
            dependency_analysis_artifact_id,
            mail_response_artifact_id,
            mail_delivery_id,
        ):
            if relation is not None and (
                not isinstance(relation, int)
                or isinstance(relation, bool)
                or relation <= 0
            ):
                raise MailRepositoryError("invalid_mail_item_relation")
        controlled_dependency_wait = (
            status == "deferred"
            and next_retry_at_utc is None
            and stage in {"context", "generate"}
            and (
                dependency_analysis_artifact_id is not None
                or (
                    logical_item_kind == "plan_revision_dependency"
                    and logical_item_id.startswith("plan_revision:")
                    and mail_message_id is not None
                    and mail_response_artifact_id is None
                    and mail_delivery_id is None
                )
            )
        )
        if (
            status in {"pending", "running", "succeeded", "unchanged"}
            and (
                error_code is not None
                or error_summary is not None
                or next_retry_at_utc is not None
            )
            or status in {"failed", "rejected"}
            and (
                error_code is None
                or next_retry_at_utc is not None
            )
            or status == "deferred"
            and (
                next_retry_at_utc is not None
                and error_code is None
                or next_retry_at_utc is None
                and not controlled_dependency_wait
                or controlled_dependency_wait
                and error_code is not None
            )
            or status != "deferred"
            and next_retry_at_utc is not None
            or error_code is None
            and error_summary is not None
        ):
            raise MailRepositoryError("invalid_mail_item_evidence")
        with self._write_transaction():
            run = self.connection.execute("SELECT subject_id FROM mail_agent_runs WHERE id=?", (run_id,)).fetchone()
            if run is None:
                raise MailRepositoryError("mail_run_not_found")
            if error_code is not None:
                error_summary = "mail item did not complete"
            row = self.connection.execute("SELECT * FROM mail_agent_items WHERE mail_agent_run_id=? AND logical_item_kind=? AND logical_item_id=? AND stage=?", (run_id, logical_item_kind, logical_item_id, stage)).fetchone()
            requested_relations = (
                mail_message_id,
                dependency_analysis_artifact_id,
                mail_response_artifact_id,
                mail_delivery_id,
            )
            if row is not None:
                if status not in _ITEM_TRANSITIONS[row["status"]]:
                    raise MailRepositoryError("illegal_mail_item_transition")
                existing_relations = (
                    row["mail_message_id"],
                    row["dependency_analysis_artifact_id"],
                    row["mail_response_artifact_id"],
                    row["mail_delivery_id"],
                )
                if existing_relations != requested_relations:
                    raise MailRepositoryError("conflicting_mail_item_replay")
            self._validate_item_relations(
                run["subject_id"],
                logical_item_kind,
                logical_item_id,
                mail_message_id,
                dependency_analysis_artifact_id,
                mail_response_artifact_id,
                mail_delivery_id,
            )
            now = self._clock()
            if row is None:
                self.connection.execute(
                    "INSERT INTO mail_agent_items(mail_agent_run_id,logical_item_kind,logical_item_id,mail_message_id,dependency_analysis_artifact_id,mail_response_artifact_id,mail_delivery_id,stage,status,attempt_count,error_code,error_summary,next_retry_at_utc,started_at_utc,completed_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, logical_item_kind, logical_item_id, mail_message_id, dependency_analysis_artifact_id, mail_response_artifact_id, mail_delivery_id, stage, status, 1, error_code, safe_error_summary(error_summary), next_retry_at_utc, now, now if status in {"succeeded", "failed", "deferred", "unchanged", "rejected"} else None),
                )
            else:
                current = row["status"]
                existing_status_evidence = (
                    row["error_code"], row["error_summary"], row["next_retry_at_utc"],
                )
                requested_status_evidence = (
                    error_code, safe_error_summary(error_summary), next_retry_at_utc,
                )
                if status == current and existing_status_evidence != requested_status_evidence:
                    raise MailRepositoryError("conflicting_mail_item_replay")
                if status != current:
                    self.connection.execute("UPDATE mail_agent_items SET status=?,attempt_count=attempt_count+1,error_code=?,error_summary=?,next_retry_at_utc=?,completed_at_utc=? WHERE id=?", (status, error_code, safe_error_summary(error_summary), next_retry_at_utc, now if status in {"succeeded", "failed", "deferred", "unchanged", "rejected"} else None, row["id"]))
            updated = self.connection.execute("SELECT * FROM mail_agent_items WHERE mail_agent_run_id=? AND logical_item_kind=? AND logical_item_id=? AND stage=?", (run_id, logical_item_kind, logical_item_id, stage)).fetchone()
            assert updated is not None
            return self._item(updated)

    def _validate_item_relations(
        self,
        subject_id: int,
        logical_item_kind: str,
        logical_item_id: str,
        mail_message_id: int | None,
        dependency_analysis_artifact_id: int | None,
        mail_response_artifact_id: int | None,
        mail_delivery_id: int | None,
    ) -> None:
        required_relations = {
            "message": mail_message_id,
            "analysis_artifact": dependency_analysis_artifact_id,
            "dependency_analysis_artifact": dependency_analysis_artifact_id,
            "response": mail_response_artifact_id,
            "mail_response_artifact": mail_response_artifact_id,
            "delivery": mail_delivery_id,
            "mail_delivery": mail_delivery_id,
        }
        if (
            logical_item_kind in required_relations
            and required_relations[logical_item_kind] is None
        ):
            raise MailRepositoryError("mail_item_logical_identity_invalid")
        message: sqlite3.Row | None = None
        if mail_message_id is not None:
            message = self.connection.execute(
                "SELECT m.id,m.provider_message_id,m.mail_thread_id "
                "FROM mail_messages m JOIN mail_threads t ON t.id=m.mail_thread_id "
                "WHERE m.id=? AND t.subject_id=?",
                (mail_message_id, subject_id),
            ).fetchone()
            if message is None:
                raise MailRepositoryError("mail_message_ownership_invalid")
            if (
                logical_item_kind == "message"
                and logical_item_id != message["provider_message_id"]
            ):
                raise MailRepositoryError("mail_item_logical_identity_invalid")
        if logical_item_kind == "plan_revision_dependency":
            if (
                message is None
                or dependency_analysis_artifact_id is not None
                or mail_response_artifact_id is not None
                or mail_delivery_id is not None
                or not logical_item_id.startswith("plan_revision:")
            ):
                raise MailRepositoryError("mail_item_logical_identity_invalid")
            event_id = logical_item_id.removeprefix("plan_revision:")
            if (
                not event_id.isdigit()
                or self.connection.execute(
                    "SELECT 1 FROM conversation_events "
                    "WHERE id=? AND subject_id=? AND mail_message_id=? "
                    "AND event_type='plan_revision_reason_recorded' "
                    "AND actor_role='trainlab' "
                    "AND trust_level='system_generated'",
                    (int(event_id), subject_id, mail_message_id),
                ).fetchone()
                is None
            ):
                raise MailRepositoryError("mail_item_logical_identity_invalid")

        if dependency_analysis_artifact_id is not None:
            dependency = self.connection.execute(
                "SELECT a.id,a.subject_id,ar.subject_id AS run_subject "
                "FROM analysis_artifacts a "
                "JOIN analysis_runs ar ON ar.id=a.generated_by_run_id "
                "WHERE a.id=?",
                (dependency_analysis_artifact_id,),
            ).fetchone()
            if (
                dependency is None
                or dependency["subject_id"] != subject_id
                or dependency["run_subject"] != subject_id
            ):
                raise MailRepositoryError(
                    "dependency_analysis_artifact_ownership_invalid"
                )
            if (
                logical_item_kind
                in {"analysis_artifact", "dependency_analysis_artifact"}
                and logical_item_id != str(dependency_analysis_artifact_id)
            ):
                raise MailRepositoryError("mail_item_logical_identity_invalid")

        response: sqlite3.Row | None = None
        if mail_response_artifact_id is not None:
            response = self.connection.execute(
                "SELECT r.id,r.subject_id,r.mail_thread_id,"
                "r.in_reply_to_mail_message_id,mr.subject_id AS run_subject,"
                "rt.subject_id AS thread_subject,tt.subject_id AS trigger_subject,"
                "trigger.mail_thread_id AS trigger_thread_id "
                "FROM mail_response_artifacts r "
                "JOIN mail_agent_runs mr "
                "ON mr.id=r.generated_by_mail_agent_run_id "
                "LEFT JOIN mail_threads rt ON rt.id=r.mail_thread_id "
                "LEFT JOIN mail_messages trigger "
                "ON trigger.id=r.in_reply_to_mail_message_id "
                "LEFT JOIN mail_threads tt ON tt.id=trigger.mail_thread_id "
                "WHERE r.id=?",
                (mail_response_artifact_id,),
            ).fetchone()
            if (
                response is None
                or response["subject_id"] != subject_id
                or response["run_subject"] != subject_id
                or (
                    response["thread_subject"] is not None
                    and response["thread_subject"] != subject_id
                )
                or (
                    response["trigger_subject"] is not None
                    and response["trigger_subject"] != subject_id
                )
                or (
                    response["mail_thread_id"] is not None
                    and response["trigger_thread_id"] is not None
                    and response["mail_thread_id"]
                    != response["trigger_thread_id"]
                )
                or (
                    mail_message_id is not None
                    and response["in_reply_to_mail_message_id"]
                    != mail_message_id
                )
            ):
                raise MailRepositoryError("mail_response_artifact_ownership_invalid")
            if (
                logical_item_kind in {"response", "mail_response_artifact"}
                and logical_item_id != str(mail_response_artifact_id)
            ):
                raise MailRepositoryError("mail_item_logical_identity_invalid")

        if mail_delivery_id is not None:
            delivery_rows = self.connection.execute(
                "SELECT d.id,d.idempotency_key,r.id AS response_id,"
                "r.subject_id,r.in_reply_to_mail_message_id,"
                "mr.subject_id AS run_subject,"
                "rt.subject_id AS thread_subject,"
                "tt.subject_id AS trigger_subject,"
                "r.mail_thread_id,trigger.mail_thread_id AS trigger_thread_id,"
                "d.related_run_key,mr.run_key,d.provider_thread_id,"
                "rt.provider_thread_id AS response_provider_thread_id,"
                "om.subject_id AS outbound_subject,"
                "outbound.mail_thread_id AS outbound_thread_id,"
                "outbound.actor_role AS outbound_actor_role,"
                "outbound.direction AS outbound_direction "
                "FROM mail_deliveries d "
                "JOIN mail_delivery_artifacts da ON da.mail_delivery_id=d.id "
                "JOIN mail_response_artifacts r "
                "ON r.id=da.mail_response_artifact_id "
                "JOIN mail_agent_runs mr "
                "ON mr.id=r.generated_by_mail_agent_run_id "
                "LEFT JOIN mail_threads rt ON rt.id=r.mail_thread_id "
                "LEFT JOIN mail_messages trigger "
                "ON trigger.id=r.in_reply_to_mail_message_id "
                "LEFT JOIN mail_threads tt ON tt.id=trigger.mail_thread_id "
                "LEFT JOIN mail_messages outbound ON outbound.id=d.mail_message_id "
                "LEFT JOIN mail_threads om ON om.id=outbound.mail_thread_id "
                "WHERE d.id=? AND da.content_role='mail_response' "
                "AND da.ordinal=0",
                (mail_delivery_id,),
            ).fetchall()
            if (
                len(delivery_rows) != 1
                or delivery_rows[0]["subject_id"] != subject_id
                or delivery_rows[0]["run_subject"] != subject_id
                or (
                    delivery_rows[0]["thread_subject"] is not None
                    and delivery_rows[0]["thread_subject"] != subject_id
                )
                or (
                    delivery_rows[0]["trigger_subject"] is not None
                    and delivery_rows[0]["trigger_subject"] != subject_id
                )
                or (
                    delivery_rows[0]["mail_thread_id"] is not None
                    and delivery_rows[0]["trigger_thread_id"] is not None
                    and delivery_rows[0]["mail_thread_id"]
                    != delivery_rows[0]["trigger_thread_id"]
                )
                or delivery_rows[0]["related_run_key"]
                != delivery_rows[0]["run_key"]
                or (
                    delivery_rows[0]["provider_thread_id"] is not None
                    and delivery_rows[0]["provider_thread_id"]
                    != delivery_rows[0]["response_provider_thread_id"]
                )
                or (
                    delivery_rows[0]["outbound_subject"] is not None
                    and delivery_rows[0]["outbound_subject"] != subject_id
                )
                or (
                    delivery_rows[0]["outbound_thread_id"] is not None
                    and delivery_rows[0]["outbound_thread_id"]
                    != delivery_rows[0]["mail_thread_id"]
                )
                or (
                    delivery_rows[0]["outbound_thread_id"] is not None
                    and (
                        delivery_rows[0]["outbound_actor_role"] != "trainlab"
                        or delivery_rows[0]["outbound_direction"]
                        not in {"outbound", "self_copy"}
                    )
                )
                or (
                    mail_response_artifact_id is not None
                    and delivery_rows[0]["response_id"]
                    != mail_response_artifact_id
                )
                or (
                    mail_message_id is not None
                    and delivery_rows[0]["in_reply_to_mail_message_id"]
                    != mail_message_id
                )
                or self.connection.execute(
                    "SELECT count(*) FROM mail_delivery_artifacts "
                    "WHERE mail_delivery_id=?",
                    (mail_delivery_id,),
                ).fetchone()[0]
                != 1
            ):
                raise MailRepositoryError("mail_delivery_relation_invalid")
            if (
                logical_item_kind in {"delivery", "mail_delivery"}
                and logical_item_id not in {
                    str(mail_delivery_id),
                    delivery_rows[0]["idempotency_key"],
                }
            ):
                raise MailRepositoryError("mail_item_logical_identity_invalid")

    @staticmethod
    def _analysis_reason_event_id(snapshot_json: object) -> int | None:
        """Extract one explicit reason id from a bounded analysis snapshot."""
        if snapshot_json is None:
            return None
        parsed, _ = _strict_json(
            snapshot_json,
            require_object=True,
            max_bytes=1_000_000,
            error_code="mail_analysis_dependency_invalid",
        )
        found: set[int] = set()

        def walk(value: object, depth: int = 0) -> None:
            if depth > 20:
                raise MailRepositoryError("mail_analysis_dependency_invalid")
            if isinstance(value, list):
                for child in value:
                    walk(child, depth + 1)
            elif isinstance(value, dict):
                for key, child in value.items():
                    if key == "reason_event_id":
                        if (
                            isinstance(child, int)
                            and not isinstance(child, bool)
                            and child > 0
                        ):
                            found.add(child)
                        elif (
                            isinstance(child, str)
                            and child.isdigit()
                            and int(child) > 0
                        ):
                            found.add(int(child))
                        else:
                            raise MailRepositoryError(
                                "mail_analysis_dependency_invalid"
                            )
                    walk(child, depth + 1)

        walk(parsed)
        if len(found) > 1:
            raise MailRepositoryError("mail_analysis_dependency_invalid")
        return next(iter(found), None)

    def _fact_gate_evidence_txn(
        self,
        run_id: int,
        context: Mapping[str, Any],
        *,
        as_of_utc: str | None = None,
    ) -> "FactGateEvidence":
        """Load the immutable DB side of the M4-08 comparison."""
        from .fact_gate import (
            ActiveFactEvidence,
            AnalysisDependencyEvidence,
            FactGateEvidence,
        )

        run = self.connection.execute(
            "SELECT * FROM mail_agent_runs WHERE id=?", (run_id,)
        ).fetchone()
        if run is None:
            raise MailRepositoryError("mail_run_not_found")
        snapshot, _ = self._decode_run_snapshot(run, verify_digest=True)
        identity = snapshot.get("mail_request_identity")
        if not isinstance(identity, dict):
            raise MailRepositoryError("mail_run_snapshot_invalid")
        requested = identity.get("mail_message_ids")
        if (
            not isinstance(requested, list)
            or len(requested) != 1
            or any(not isinstance(item, str) for item in requested)
        ):
            raise MailRepositoryError("mail_fact_gate_run_message_invalid")
        try:
            message_id = context["trigger_message"]["id"]
        except (KeyError, TypeError):
            message_id = None
        if (
            not isinstance(message_id, int)
            or isinstance(message_id, bool)
            or message_id <= 0
        ):
            raise MailRepositoryError("mail_fact_gate_context_invalid")
        message = self.connection.execute(
            "SELECT m.id,m.provider_message_id,m.mail_thread_id,m.actor_role,"
            "m.direction,m.processing_state,m.source_revision_id,"
            "t.provider_thread_id,t.subject_id,"
            "CASE WHEN sr.id IS NULL THEN 0 ELSE 1 END AS source_is_current "
            "FROM mail_messages m "
            "JOIN mail_threads t ON t.id=m.mail_thread_id "
            "LEFT JOIN source_revisions sr ON sr.id=m.source_revision_id "
            "AND sr.is_current=1 AND sr.provider='gmail' "
            "AND sr.resource_kind='message_json' "
            "AND sr.provider_object_id=m.provider_message_id "
            "WHERE m.id=? AND t.subject_id=? AND t.is_current=1",
            (message_id, run["subject_id"]),
        ).fetchone()
        if message is None or message["source_revision_id"] is None:
            raise MailRepositoryError("mail_fact_gate_message_invalid")
        eligible = self.connection.execute(
            "SELECT event_type FROM conversation_events "
            "WHERE subject_id=? AND mail_message_id=? "
            "AND event_type IN ('new_request_received','reply_received') "
            "AND actor_role='user' AND trust_level='untrusted_content'",
            (run["subject_id"], message_id),
        ).fetchall()
        if len(eligible) != 1:
            raise MailRepositoryError("mail_fact_gate_eligibility_invalid")
        response_rows = self.connection.execute(
            "SELECT id FROM mail_response_artifacts "
            "WHERE subject_id=? AND in_reply_to_mail_message_id=?",
            (run["subject_id"], message_id),
        ).fetchall()
        if len(response_rows) > 1:
            raise MailRepositoryError("mail_fact_gate_response_ambiguous")
        facts: list[ActiveFactEvidence] = []
        for row in self.connection.execute(
            "SELECT f.*,e.mail_message_id AS source_mail_message_id,"
            "e.subject_id AS event_subject_id "
            "FROM user_facts f "
            "LEFT JOIN conversation_events e ON e.id=f.source_event_id "
            "WHERE f.subject_id=? AND f.is_active=1",
            (run["subject_id"],),
        ).fetchall():
            value, _ = _strict_json(
                row["fact_value_json"],
                require_object=False,
                max_bytes=16_384,
                error_code="mail_active_fact_invalid",
            )
            if (
                row["source_event_id"] is not None
                and row["event_subject_id"] != run["subject_id"]
            ):
                raise MailRepositoryError("mail_active_fact_invalid")
            facts.append(
                ActiveFactEvidence(
                    int(row["id"]),
                    int(row["subject_id"]),
                    row["fact_key"],
                    value,
                    row["scope"],
                    row["effective_from_utc"],
                    row["expires_at_utc"],
                    row["source_event_id"],
                    row["source_mail_message_id"],
                    bool(row["is_active"]),
                    row["superseded_by_fact_id"],
                )
            )

        dependency = None
        plan = context.get("current_training_plan")
        plan_id = plan.get("id") if isinstance(plan, dict) else None
        artifact_id = (
            plan.get("analysis_artifact_id") if isinstance(plan, dict) else None
        )
        if (
            isinstance(plan_id, int)
            and not isinstance(plan_id, bool)
            and isinstance(artifact_id, int)
            and not isinstance(artifact_id, bool)
        ):
            dependency_row = self.connection.execute(
                "SELECT a.id AS artifact_id,a.subject_id,a.artifact_kind,"
                "a.period_start_local_date,a.period_end_local_date,a.is_current,"
                "ar.id AS analysis_run_id,ar.analysis_kind,ar.status AS analysis_status,"
                "ar.target_start_local_date,ar.target_end_local_date,"
                "ar.context_snapshot_json AS analysis_snapshot,"
                "p.id AS training_plan_id,p.status AS training_plan_status,"
                "p.plan_start_local_date,p.plan_end_local_date "
                "FROM analysis_artifacts a "
                "JOIN analysis_runs ar ON ar.id=a.generated_by_run_id "
                "LEFT JOIN training_plans p ON p.analysis_artifact_id=a.id "
                "WHERE a.id=? AND p.id=?",
                (artifact_id, plan_id),
            ).fetchone()
            if dependency_row is not None:
                reason_id = self._analysis_reason_event_id(
                    dependency_row["analysis_snapshot"]
                )
                reason = (
                    None
                    if reason_id is None
                    else self.connection.execute(
                        "SELECT id,mail_message_id,actor_role,trust_level "
                        "FROM conversation_events "
                        "WHERE id=? AND subject_id=? "
                        "AND event_type='plan_revision_reason_recorded'",
                        (reason_id, run["subject_id"]),
                    ).fetchone()
                )
                dependency = AnalysisDependencyEvidence(
                    int(dependency_row["artifact_id"]),
                    int(dependency_row["subject_id"]),
                    dependency_row["artifact_kind"],
                    dependency_row["period_start_local_date"],
                    dependency_row["period_end_local_date"],
                    bool(dependency_row["is_current"]),
                    int(dependency_row["analysis_run_id"]),
                    dependency_row["analysis_kind"],
                    dependency_row["analysis_status"],
                    dependency_row["target_start_local_date"],
                    dependency_row["target_end_local_date"],
                    dependency_row["training_plan_id"],
                    dependency_row["training_plan_status"],
                    dependency_row["plan_start_local_date"],
                    dependency_row["plan_end_local_date"],
                    reason_id,
                    None if reason is None else reason["mail_message_id"],
                    None if reason is None else reason["actor_role"],
                    None if reason is None else reason["trust_level"],
                )
        return FactGateEvidence(
            int(run["subject_id"]),
            int(run["id"]),
            run["run_key"],
            run["request_kind"],
            run["status"],
            tuple(requested),
            int(message["id"]),
            message["provider_message_id"],
            int(message["mail_thread_id"]),
            message["provider_thread_id"],
            int(message["source_revision_id"]),
            bool(message["source_is_current"]),
            message["actor_role"],
            message["direction"],
            message["processing_state"],
            eligible[0]["event_type"],
            None if not response_rows else int(response_rows[0]["id"]),
            self._clock() if as_of_utc is None else as_of_utc,
            tuple(facts),
            dependency,
        )

    def gate_mail_result(
        self,
        run_id: int,
        result_document: bytes | str | Mapping[str, Any],
        context: dict[str, Any],
        *,
        gate: "MailFactGate | None" = None,
    ) -> "FactGateDecision":
        """Run M4-08 and atomically persist only a plan dependency request.

        Accepted ordinary replies and facts are returned as immutable drafts
        for M4-09.  They are intentionally not published here.
        """
        from .fact_gate import (
            MailFactGate,
            bind_reason_event,
        )

        validator = gate or MailFactGate()
        self._verify_foundation_schema()
        as_of_utc = self._clock()
        evidence = self._fact_gate_evidence_txn(
            run_id, context, as_of_utc=as_of_utc
        )
        decision = validator.evaluate(result_document, context, evidence)
        if decision.status != "dependency_wait" or decision.event is None:
            return decision
        with self._write_transaction():
            current_evidence = self._fact_gate_evidence_txn(
                run_id, context, as_of_utc=as_of_utc
            )
            if current_evidence != evidence:
                raise MailRepositoryError("mail_fact_gate_evidence_changed")
            event = decision.event
            run = self.connection.execute(
                "SELECT * FROM mail_agent_runs WHERE id=?", (run_id,)
            ).fetchone()
            assert run is not None
            reason_id = self._create_or_recover_event(
                run,
                EventDraft(
                    event.event_type,
                    event.actor_role,
                    event.occurred_at_utc,
                    event.mail_message_id,
                    event.trust_level,
                    related_run_key=event.related_run_key,
                    structured_payload_json=event.structured_payload_json,
                ),
            )
            message = self.connection.execute(
                "SELECT processing_state FROM mail_messages WHERE id=?",
                (event.mail_message_id,),
            ).fetchone()
            if message is None or message["processing_state"] not in {
                "queued",
                "analyzing",
                "awaiting_analysis",
            }:
                raise MailRepositoryError("mail_fact_gate_message_state_invalid")
            if message["processing_state"] != "awaiting_analysis":
                self.connection.execute(
                    "UPDATE mail_messages SET processing_state='awaiting_analysis' "
                    "WHERE id=?",
                    (event.mail_message_id,),
                )
            logical_id = f"plan_revision:{reason_id}"
            self._validate_item_relations(
                evidence.subject_id,
                "plan_revision_dependency",
                logical_id,
                event.mail_message_id,
                None,
                None,
                None,
            )
            existing = self.connection.execute(
                "SELECT * FROM mail_agent_items "
                "WHERE mail_agent_run_id=? "
                "AND logical_item_kind='plan_revision_dependency' "
                "AND logical_item_id=? AND stage='generate'",
                (run_id, logical_id),
            ).fetchone()
            if existing is None:
                now = self._clock()
                self.connection.execute(
                    "INSERT INTO mail_agent_items("
                    "mail_agent_run_id,logical_item_kind,logical_item_id,"
                    "mail_message_id,stage,status,attempt_count,"
                    "started_at_utc,completed_at_utc"
                    ") VALUES(?, 'plan_revision_dependency', ?, ?, "
                    "'generate','deferred',1,?,?)",
                    (run_id, logical_id, event.mail_message_id, now, now),
                )
            elif (
                existing["mail_message_id"] != event.mail_message_id
                or existing["dependency_analysis_artifact_id"] is not None
                or existing["mail_response_artifact_id"] is not None
                or existing["mail_delivery_id"] is not None
                or existing["status"] != "deferred"
                or existing["error_code"] is not None
                or existing["error_summary"] is not None
                or existing["next_retry_at_utc"] is not None
            ):
                raise MailRepositoryError(
                    "mail_fact_gate_dependency_replay_conflict"
                )
            return bind_reason_event(decision, reason_id)

    def publish_accepted_response(self, run_id: int, draft: AcceptedResponseDraft) -> PublishedResponse:
        """Atomically publish an accepted response, its lineage, facts and relation."""
        with self._write_transaction():
            run = self.connection.execute("SELECT * FROM mail_agent_runs WHERE id=?", (run_id,)).fetchone()
            if run is None:
                raise MailRepositoryError("mail_run_not_found")
            structured_content_json, fact_value_json = self._validate_response_draft(run, draft)
            existing = self.connection.execute("SELECT id FROM mail_response_artifacts WHERE generated_by_mail_agent_run_id=?", (run_id,)).fetchone()
            if existing is not None:
                return self._assert_existing_response_matches(
                    run, existing["id"], draft, structured_content_json, fact_value_json
                )
            event_ids: dict[str, int] = {}
            for event in draft.events:
                event_ids[event.event_type] = self._create_or_recover_event(run, event)
            fact_ids: list[int] = []
            for fact, canonical_fact in zip(draft.facts, fact_value_json):
                event_id = event_ids.get(fact.source_event_type)
                if event_id is None:
                    raise MailRepositoryError("fact_source_event_missing")
                fact_ids.append(
                    self._create_or_recover_fact(
                        run["subject_id"], event_id, fact, canonical_fact
                    )
                )
            current_rows = self.connection.execute(
                "SELECT id,subject_id,mail_thread_id,response_kind,revision_no "
                "FROM mail_response_artifacts "
                "WHERE subject_id=? AND mail_thread_id IS ? AND response_kind=? AND is_current=1",
                (run["subject_id"], draft.mail_thread_id, draft.response_kind),
            ).fetchall()
            if len(current_rows) > 1:
                raise MailRepositoryError("mail_response_current_ambiguous")
            previous = current_rows[0] if current_rows else None
            if previous is not None and (
                previous["subject_id"],
                previous["mail_thread_id"],
                previous["response_kind"],
            ) != (run["subject_id"], draft.mail_thread_id, draft.response_kind):
                raise MailRepositoryError("mail_response_supersession_invalid")
            revision = self.connection.execute(
                "SELECT COALESCE(MAX(revision_no),0)+1 AS revision "
                "FROM mail_response_artifacts "
                "WHERE subject_id=? AND mail_thread_id IS ? AND response_kind=?",
                (run["subject_id"], draft.mail_thread_id, draft.response_kind),
            ).fetchone()["revision"]
            previous_id = None if previous is None else int(previous["id"])
            if (
                previous is None
                and revision != 1
                or previous is not None
                and previous["revision_no"] != revision - 1
            ):
                raise MailRepositoryError("mail_response_supersession_invalid")
            if previous_id is not None:
                changed = self.connection.execute(
                    "UPDATE mail_response_artifacts SET is_current=0 "
                    "WHERE id=? AND subject_id=? AND mail_thread_id IS ? "
                    "AND response_kind=? AND is_current=1",
                    (
                        previous_id,
                        run["subject_id"],
                        draft.mail_thread_id,
                        draft.response_kind,
                    ),
                ).rowcount
                if changed != 1:
                    raise MailRepositoryError("mail_response_supersession_invalid")
            digest = hashlib.sha256(
                (structured_content_json + "\n" + draft.user_visible_text).encode("utf-8")
            ).hexdigest()
            self.connection.execute(
                "INSERT INTO mail_response_artifacts("
                "subject_id,mail_thread_id,in_reply_to_mail_message_id,response_kind,"
                "revision_no,generated_by_mail_agent_run_id,schema_version,"
                "structured_content_json,user_visible_text,content_sha256,is_current,"
                "supersedes_mail_response_artifact_id,created_at_utc"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?)",
                (
                    run["subject_id"],
                    draft.mail_thread_id,
                    draft.in_reply_to_mail_message_id,
                    draft.response_kind,
                    revision,
                    run_id,
                    draft.schema_version,
                    structured_content_json,
                    draft.user_visible_text,
                    digest,
                    previous_id,
                    self._clock(),
                ),
            )
            response_id = self.connection.execute("SELECT id FROM mail_response_artifacts WHERE generated_by_mail_agent_run_id=?", (run_id,)).fetchone()["id"]
            for ordinal, item in enumerate(draft.inputs):
                self.connection.execute("INSERT INTO mail_response_inputs(mail_agent_run_id,input_role,source_entity_type,source_entity_id,source_revision_id,input_sha256,trust_class,ordinal) VALUES(?,?,?,?,?,?,?,?)", (run_id, item.input_role, item.source_entity_type, item.source_entity_id, item.source_revision_id, item.input_sha256, item.trust_class, ordinal))
            delivery_id: int | None = None
            if draft.delivery is not None:
                self.connection.execute(
                    "INSERT INTO mail_deliveries("
                    "idempotency_key,delivery_kind,related_run_key,mail_message_id,"
                    "provider_thread_id,status,created_at_utc,updated_at_utc"
                    ") VALUES(?,?,?,NULL,?,'pending',?,?)",
                    (
                        draft.delivery.idempotency_key,
                        "mail_response",
                        run["run_key"],
                        draft.delivery.provider_thread_id,
                        self._clock(),
                        self._clock(),
                    ),
                )
                delivery_id = self.connection.execute("SELECT id FROM mail_deliveries WHERE idempotency_key=?", (draft.delivery.idempotency_key,)).fetchone()["id"]
                self.connection.execute("INSERT INTO mail_delivery_artifacts(mail_delivery_id,mail_response_artifact_id,content_role,ordinal) VALUES(?,?,?,0)", (delivery_id, response_id, "mail_response"))
            return PublishedResponse(response_id, delivery_id, tuple(event_ids.values()), tuple(fact_ids))

    def _validate_response_draft(
        self, run: sqlite3.Row, draft: AcceptedResponseDraft
    ) -> tuple[str, tuple[str, ...]]:
        try:
            visible_text_bytes = (
                draft.user_visible_text.encode("utf-8", errors="strict")
                if isinstance(draft.user_visible_text, str)
                else b""
            )
        except UnicodeError as exc:
            raise MailRepositoryError("invalid_mail_response_draft") from exc
        if run["request_kind"] not in {"process", "run"} or run["status"] not in {
            "started",
            "partial",
            "deferred",
        }:
            raise MailRepositoryError("mail_response_run_state_invalid")
        if (
            not isinstance(draft.response_kind, str)
            or not _SAFE_CODE.fullmatch(draft.response_kind)
            or not isinstance(draft.schema_version, str)
            or not draft.schema_version
            or len(draft.schema_version) > 32
            or not isinstance(draft.user_visible_text, str)
            or len(visible_text_bytes) > 100_000
        ):
            raise MailRepositoryError("invalid_mail_response_draft")
        _, structured_content_json = _strict_json(
            draft.structured_content_json,
            require_object=True,
            max_bytes=100_000,
            error_code="invalid_mail_response_draft",
        )
        thread_provider_id: str | None = None
        if draft.mail_thread_id is not None:
            if not isinstance(draft.mail_thread_id, int) or isinstance(draft.mail_thread_id, bool):
                raise MailRepositoryError("mail_thread_ownership_invalid")
            row = self.connection.execute(
                "SELECT id,provider_thread_id FROM mail_threads "
                "WHERE id=? AND subject_id=? AND is_current=1",
                (draft.mail_thread_id, run["subject_id"]),
            ).fetchone()
            if row is None:
                raise MailRepositoryError("mail_thread_ownership_invalid")
            thread_provider_id = row["provider_thread_id"]
        trigger_message: sqlite3.Row | None = None
        if draft.in_reply_to_mail_message_id is not None:
            if (
                not isinstance(draft.in_reply_to_mail_message_id, int)
                or isinstance(draft.in_reply_to_mail_message_id, bool)
            ):
                raise MailRepositoryError("mail_message_ownership_invalid")
            trigger_message = self.connection.execute(
                "SELECT m.* FROM mail_messages m "
                "JOIN mail_threads t ON t.id=m.mail_thread_id "
                "WHERE m.id=? AND t.subject_id=? AND (? IS NULL OR m.mail_thread_id=?)",
                (
                    draft.in_reply_to_mail_message_id,
                    run["subject_id"],
                    draft.mail_thread_id,
                    draft.mail_thread_id,
                ),
            ).fetchone()
            if trigger_message is None:
                raise MailRepositoryError("mail_message_ownership_invalid")

        seen_inputs: set[tuple[str, int]] = set()
        trigger_count = 0
        for item in draft.inputs:
            if (
                not isinstance(item.input_role, str)
                or not _SAFE_CODE.fullmatch(item.input_role)
                or not isinstance(item.source_entity_type, str)
                or not _SAFE_CODE.fullmatch(item.source_entity_type)
                or not isinstance(item.source_entity_id, int)
                or isinstance(item.source_entity_id, bool)
                or item.source_entity_id <= 0
                or (
                    item.source_revision_id is not None
                    and (
                        not isinstance(item.source_revision_id, int)
                        or isinstance(item.source_revision_id, bool)
                        or item.source_revision_id <= 0
                    )
                )
                or item.trust_class
                not in {
                    "provider_fact",
                    "user_asserted",
                    "derived_statistic",
                    "prior_model_output",
                }
                or not re.fullmatch(r"[0-9a-f]{64}", item.input_sha256)
                or (item.input_role, item.source_entity_id) in seen_inputs
            ):
                raise MailRepositoryError("invalid_mail_response_input")
            seen_inputs.add((item.input_role, item.source_entity_id))
            self._validate_input_relation(run, draft, item)
            if item.input_role == "trigger_message":
                trigger_count += 1
                if (
                    trigger_message is None
                    or item.source_entity_id != trigger_message["id"]
                ):
                    raise MailRepositoryError("mail_response_trigger_mismatch")
        if trigger_message is not None and trigger_count != 1:
            raise MailRepositoryError("mail_response_trigger_mismatch")

        event_types: set[str] = set()
        for event in draft.events:
            expected_actor = (
                _EVENT_ACTORS.get(event.event_type)
                if isinstance(event.event_type, str)
                else None
            )
            expected_trust = (
                "system_generated"
                if event.actor_role == "trainlab"
                else "untrusted_content"
            )
            if (
                not isinstance(event.event_type, str)
                or not _SAFE_CODE.fullmatch(event.event_type)
                or event.event_type in event_types
                or not isinstance(event.actor_role, str)
                or event.actor_role not in {"user", "trainlab", "unknown"}
                or not isinstance(event.trust_level, str)
                or event.trust_level
                not in {"untrusted_content", "system_generated"}
                or event.created_by != "mail_agent"
                or not _canonical_utc(event.occurred_at_utc)
            ):
                raise MailRepositoryError("invalid_conversation_event_draft")
            _, canonical_event_payload = _strict_json(
                event.structured_payload_json,
                require_object=True,
                max_bytes=32_768,
                error_code="invalid_conversation_event_draft",
            )
            if event.structured_payload_json != canonical_event_payload:
                raise MailRepositoryError("invalid_conversation_event_draft")
            if (
                (
                    event.related_run_key is not None
                    and event.related_run_key != run["run_key"]
                )
                or expected_actor is None
                or event.actor_role != expected_actor
                or event.trust_level != expected_trust
            ):
                raise MailRepositoryError("conversation_event_ownership_invalid")
            event_types.add(event.event_type)
            if event.mail_message_id is not None:
                owned = self.connection.execute(
                    "SELECT m.id,m.actor_role,m.source_revision_id,"
                    "r.id AS current_source_revision_id "
                    "FROM mail_messages m JOIN mail_threads t ON t.id=m.mail_thread_id "
                    "LEFT JOIN source_revisions r ON r.id=m.source_revision_id "
                    "AND r.is_current=1 AND r.provider='gmail' "
                    "AND r.resource_kind='message_json' "
                    "AND r.provider_object_id=m.provider_message_id "
                    "WHERE m.id=? AND t.subject_id=?",
                    (event.mail_message_id, run["subject_id"]),
                ).fetchone()
                expected_trust = (
                    "system_generated"
                    if owned is not None and owned["actor_role"] == "trainlab"
                    else "untrusted_content"
                )
                plan_reason = (
                    event.event_type == "plan_revision_reason_recorded"
                    and event.actor_role == "trainlab"
                    and event.trust_level == "system_generated"
                    and owned is not None
                    and owned["actor_role"] == "user"
                )
                if (
                    owned is None
                    or (
                        not plan_reason
                        and (
                            event.actor_role != owned["actor_role"]
                            or event.trust_level != expected_trust
                        )
                    )
                    or owned["source_revision_id"] is None
                    or owned["current_source_revision_id"]
                    != owned["source_revision_id"]
                ):
                    raise MailRepositoryError("conversation_event_ownership_invalid")

        canonical_facts: list[str] = []
        fact_keys: set[tuple[str, str]] = set()
        for fact in draft.facts:
            if (
                not isinstance(fact.fact_key, str)
                or not _SAFE_CODE.fullmatch(fact.fact_key)
                or fact.source_event_type not in event_types
                or (fact.source_event_type, fact.fact_key) in fact_keys
                or fact.scope not in {"message_only", "temporary", "long_term"}
                or (
                    fact.confidence is not None
                    and (
                        isinstance(fact.confidence, bool)
                        or not isinstance(fact.confidence, (int, float))
                        or not math.isfinite(fact.confidence)
                        or not 0 <= fact.confidence <= 1
                    )
                )
                or not isinstance(fact.is_active, bool)
                or (
                    fact.supersedes_fact_id is not None
                    and (
                        not isinstance(fact.supersedes_fact_id, int)
                        or isinstance(fact.supersedes_fact_id, bool)
                        or fact.supersedes_fact_id <= 0
                    )
                )
                or (
                    fact.effective_from_utc is not None
                    and not _canonical_utc(fact.effective_from_utc)
                )
                or (
                    fact.expires_at_utc is not None
                    and not _canonical_utc(fact.expires_at_utc)
                )
                or (
                    fact.effective_from_utc is not None
                    and fact.expires_at_utc is not None
                    and _utc(fact.effective_from_utc) >= _utc(fact.expires_at_utc)
                )
                or (fact.scope == "temporary" and fact.expires_at_utc is None)
                or (
                    fact.scope == "message_only"
                    and (fact.is_active or fact.supersedes_fact_id is not None)
                )
                or (
                    fact.scope != "message_only"
                    and not fact.is_active
                )
            ):
                raise MailRepositoryError("invalid_user_fact_draft")
            fact_keys.add((fact.source_event_type, fact.fact_key))
            _, canonical_fact = _strict_json(
                fact.fact_value_json,
                require_object=False,
                max_bytes=16_384,
                error_code="invalid_user_fact_draft",
            )
            canonical_facts.append(canonical_fact)
            if fact.supersedes_fact_id is not None:
                old = self.connection.execute(
                    "SELECT f.*,e.subject_id AS event_subject_id "
                    "FROM user_facts f "
                    "LEFT JOIN conversation_events e ON e.id=f.source_event_id "
                    "WHERE f.id=?",
                    (fact.supersedes_fact_id,),
                ).fetchone()
                if (
                    old is None
                    or old["subject_id"] != run["subject_id"]
                    or old["event_subject_id"] != run["subject_id"]
                    or old["fact_key"] != fact.fact_key
                    or old["scope"] == "message_only"
                    or (
                        old["is_active"] == 1
                        and old["superseded_by_fact_id"] is not None
                    )
                    or (
                        old["is_active"] == 0
                        and old["superseded_by_fact_id"] is None
                    )
                ):
                    raise MailRepositoryError("user_fact_supersession_invalid")
        if draft.delivery is not None:
            if (
                not isinstance(draft.delivery.idempotency_key, str)
                or not _SAFE_ID.fullmatch(draft.delivery.idempotency_key)
                or (
                    draft.delivery.provider_thread_id is not None
                    and not _SAFE_ID.fullmatch(draft.delivery.provider_thread_id)
                )
                or (
                    thread_provider_id is not None
                    and draft.delivery.provider_thread_id
                    not in {None, thread_provider_id}
                )
            ):
                raise MailRepositoryError("invalid_mail_delivery_draft")
        return structured_content_json, tuple(canonical_facts)

    def _validate_current_source_revision(
        self, source_revision_id: int | None, expected_id: int | None
    ) -> None:
        if source_revision_id != expected_id:
            raise MailRepositoryError("mail_response_input_revision_invalid")
        if source_revision_id is None:
            return
        row = self.connection.execute(
            "SELECT is_current FROM source_revisions WHERE id=?",
            (source_revision_id,),
        ).fetchone()
        if row is None or row["is_current"] != 1:
            raise MailRepositoryError("mail_response_input_revision_invalid")

    def _validate_input_relation(
        self, run: sqlite3.Row, draft: AcceptedResponseDraft, item: InputDraft
    ) -> None:
        role_types = {
            "trigger_message": ("mail_message", "user_asserted"),
            "thread_message": ("mail_message", None),
            "active_user_fact": ("user_fact", "user_asserted"),
            "health_fact": ("daily_health", "provider_fact"),
            "activity_fact": ("activity", "provider_fact"),
            "analysis_artifact": ("analysis_artifact", "prior_model_output"),
            "prior_mail_response": ("mail_response_artifact", "prior_model_output"),
            "current_plan": ("training_plan", "prior_model_output"),
            "conversation_event": ("conversation_event", "derived_statistic"),
            "quality_state": ("data_quality_issue", "derived_statistic"),
        }
        specification = role_types.get(item.input_role)
        if (
            specification is None
            or item.source_entity_type != specification[0]
            or (
                specification[1] is not None
                and item.trust_class != specification[1]
            )
        ):
            raise MailRepositoryError("mail_response_input_role_invalid")
        subject_id = run["subject_id"]
        entity_id = item.source_entity_id
        if item.source_entity_type == "mail_message":
            row = self.connection.execute(
                "SELECT m.*,t.subject_id,r.id AS current_source_revision_id "
                "FROM mail_messages m "
                "JOIN mail_threads t ON t.id=m.mail_thread_id "
                "LEFT JOIN source_revisions r ON r.id=m.source_revision_id "
                "AND r.is_current=1 AND r.provider='gmail' "
                "AND r.resource_kind='message_json' "
                "AND r.provider_object_id=m.provider_message_id "
                "WHERE m.id=?",
                (entity_id,),
            ).fetchone()
            if (
                row is None
                or row["subject_id"] != subject_id
                or (
                    draft.mail_thread_id is not None
                    and row["mail_thread_id"] != draft.mail_thread_id
                )
                or row["source_revision_id"] is None
                or row["current_source_revision_id"] != row["source_revision_id"]
            ):
                raise MailRepositoryError("mail_response_input_ownership_invalid")
            self._validate_current_source_revision(
                item.source_revision_id, row["source_revision_id"]
            )
            if item.input_role == "trigger_message" and (
                row["id"] != draft.in_reply_to_mail_message_id
                or row["actor_role"] != "user"
                or row["direction"] != "inbound"
                or item.trust_class != "user_asserted"
            ):
                raise MailRepositoryError("mail_response_trigger_mismatch")
            if item.input_role == "thread_message":
                expected = (
                    "user_asserted"
                    if row["actor_role"] == "user" and row["direction"] == "inbound"
                    else "prior_model_output"
                    if row["actor_role"] == "trainlab"
                    and row["direction"] in {"outbound", "self_copy"}
                    else None
                )
                if item.trust_class != expected:
                    raise MailRepositoryError("mail_response_input_trust_invalid")
            return
        if item.source_entity_type == "user_fact":
            row = self.connection.execute(
                "SELECT f.*,e.subject_id AS event_subject_id "
                "FROM user_facts f JOIN conversation_events e ON e.id=f.source_event_id "
                "WHERE f.id=?",
                (entity_id,),
            ).fetchone()
            if (
                row is None
                or row["subject_id"] != subject_id
                or row["event_subject_id"] != subject_id
                or row["is_active"] != 1
                or row["superseded_by_fact_id"] is not None
                or row["scope"] == "message_only"
                or item.source_revision_id is not None
            ):
                raise MailRepositoryError("mail_response_input_ownership_invalid")
            return
        if item.source_entity_type == "daily_health":
            row = self.connection.execute(
                "SELECT * FROM daily_health WHERE id=?", (entity_id,)
            ).fetchone()
            if row is None or row["subject_id"] != subject_id or row["is_current"] != 1:
                raise MailRepositoryError("mail_response_input_ownership_invalid")
            self._validate_current_source_revision(
                item.source_revision_id, row["source_revision_id"]
            )
            return
        if item.source_entity_type == "activity":
            row = self.connection.execute(
                "SELECT * FROM activities WHERE id=?", (entity_id,)
            ).fetchone()
            if (
                row is None
                or row["subject_id"] != subject_id
                or row["provider_state"] == "provider_deleted"
            ):
                raise MailRepositoryError("mail_response_input_ownership_invalid")
            self._validate_current_source_revision(
                item.source_revision_id, row["primary_revision_id"]
            )
            active = self.connection.execute(
                "SELECT 1 FROM activity_source_revisions "
                "WHERE activity_id=? AND source_revision_id=? AND is_active=1",
                (entity_id, item.source_revision_id),
            ).fetchone()
            if active is None:
                raise MailRepositoryError("mail_response_input_revision_invalid")
            return
        if item.source_entity_type == "analysis_artifact":
            row = self.connection.execute(
                "SELECT a.subject_id,a.is_current,r.status,r.subject_id AS run_subject "
                "FROM analysis_artifacts a JOIN analysis_runs r ON r.id=a.generated_by_run_id "
                "WHERE a.id=?",
                (entity_id,),
            ).fetchone()
            if (
                row is None
                or row["subject_id"] != subject_id
                or row["run_subject"] != subject_id
                or row["is_current"] != 1
                or row["status"] != "succeeded"
                or item.source_revision_id is not None
            ):
                raise MailRepositoryError("mail_response_input_ownership_invalid")
            return
        if item.source_entity_type == "mail_response_artifact":
            row = self.connection.execute(
                "SELECT a.subject_id,a.mail_thread_id,r.subject_id AS run_subject "
                "FROM mail_response_artifacts a "
                "JOIN mail_agent_runs r ON r.id=a.generated_by_mail_agent_run_id "
                "WHERE a.id=?",
                (entity_id,),
            ).fetchone()
            if (
                row is None
                or row["subject_id"] != subject_id
                or row["run_subject"] != subject_id
                or (
                    draft.mail_thread_id is not None
                    and row["mail_thread_id"] != draft.mail_thread_id
                )
                or item.source_revision_id is not None
            ):
                raise MailRepositoryError("mail_response_input_ownership_invalid")
            return
        if item.source_entity_type == "training_plan":
            row = self.connection.execute(
                "SELECT p.subject_id,p.status,a.is_current,r.status AS run_status,"
                "r.subject_id AS run_subject FROM training_plans p "
                "JOIN analysis_artifacts a ON a.id=p.analysis_artifact_id "
                "JOIN analysis_runs r ON r.id=a.generated_by_run_id WHERE p.id=?",
                (entity_id,),
            ).fetchone()
            if (
                row is None
                or row["subject_id"] != subject_id
                or row["run_subject"] != subject_id
                or row["status"] != "active"
                or row["is_current"] != 1
                or row["run_status"] != "succeeded"
                or item.source_revision_id is not None
            ):
                raise MailRepositoryError("mail_response_input_ownership_invalid")
            return
        if item.source_entity_type == "conversation_event":
            row = self.connection.execute(
                "SELECT e.subject_id,m.mail_thread_id,t.subject_id AS message_subject "
                "FROM conversation_events e "
                "LEFT JOIN mail_messages m ON m.id=e.mail_message_id "
                "LEFT JOIN mail_threads t ON t.id=m.mail_thread_id WHERE e.id=?",
                (entity_id,),
            ).fetchone()
            if (
                row is None
                or row["subject_id"] != subject_id
                or (
                    row["message_subject"] is not None
                    and row["message_subject"] != subject_id
                )
                or (
                    draft.mail_thread_id is not None
                    and row["mail_thread_id"] is not None
                    and row["mail_thread_id"] != draft.mail_thread_id
                )
                or item.source_revision_id is not None
            ):
                raise MailRepositoryError("mail_response_input_ownership_invalid")
            return
        if item.source_entity_type == "data_quality_issue":
            row = self.connection.execute(
                "SELECT * FROM data_quality_issues WHERE id=?", (entity_id,)
            ).fetchone()
            if row is None or row["status"] not in {"open", "acknowledged"}:
                raise MailRepositoryError("mail_response_input_ownership_invalid")
            self._validate_current_source_revision(
                item.source_revision_id, row["source_revision_id"]
            )
            if not self._quality_issue_owned_by_subject(
                subject_id,
                row["entity_type"],
                row["entity_id"],
                row["source_revision_id"],
            ):
                raise MailRepositoryError("mail_response_input_ownership_invalid")
            return
        raise MailRepositoryError("mail_response_input_role_invalid")

    def _quality_issue_owned_by_subject(
        self,
        subject_id: int,
        entity_type: str,
        entity_id: int | None,
        source_revision_id: int | None,
    ) -> bool:
        if not isinstance(entity_id, int) or isinstance(entity_id, bool):
            return False
        queries = {
            "mail_message": (
                "SELECT 1 FROM mail_messages m JOIN mail_threads t ON t.id=m.mail_thread_id "
                "WHERE m.id=? AND t.subject_id=? "
                "AND (? IS NULL OR ?=m.source_revision_id)"
            ),
            "daily_health": (
                "SELECT 1 FROM daily_health WHERE id=? AND subject_id=? "
                "AND (? IS NULL OR ?=source_revision_id)"
            ),
            "activity": (
                "SELECT 1 FROM activities WHERE id=? AND subject_id=? "
                "AND (? IS NULL OR ?=primary_revision_id)"
            ),
            "user_fact": (
                "SELECT 1 FROM user_facts WHERE id=? AND subject_id=? "
                "AND ? IS NULL AND ? IS NULL"
            ),
            "analysis_artifact": (
                "SELECT 1 FROM analysis_artifacts WHERE id=? AND subject_id=? "
                "AND ? IS NULL AND ? IS NULL"
            ),
            "training_plan": (
                "SELECT 1 FROM training_plans WHERE id=? AND subject_id=? "
                "AND ? IS NULL AND ? IS NULL"
            ),
        }
        query = queries.get(entity_type)
        return (
            query is not None
            and self.connection.execute(
                query,
                (
                    entity_id,
                    subject_id,
                    source_revision_id,
                    source_revision_id,
                ),
            ).fetchone()
            is not None
        )

    def _event_row_matches(
        self, row: sqlite3.Row, run: sqlite3.Row, event: EventDraft
    ) -> bool:
        expected_run_key = event.related_run_key or run["run_key"]
        _, canonical_payload = _strict_json(
            event.structured_payload_json,
            require_object=True,
            max_bytes=32_768,
            error_code="invalid_conversation_event_draft",
        )
        base = (
            row["subject_id"],
            row["event_type"],
            row["actor_role"],
            row["occurred_at_utc"],
            row["mail_message_id"],
            row["structured_payload_json"],
            row["trust_level"],
            row["created_by"],
        )
        wanted = (
            run["subject_id"],
            event.event_type,
            event.actor_role,
            event.occurred_at_utc,
            event.mail_message_id,
            canonical_payload,
            event.trust_level,
            event.created_by,
        )
        # A message-backed event is source-idempotent across explicit
        # regeneration runs.  A NULL-message event is run-owned and therefore
        # requires the exact run key.
        return base == wanted and (
            event.mail_message_id is not None
            or row["related_run_key"] == expected_run_key
        )

    def _create_or_recover_event(
        self, run: sqlite3.Row, event: EventDraft
    ) -> int:
        run_key = event.related_run_key or run["run_key"]
        _, canonical_payload = _strict_json(
            event.structured_payload_json,
            require_object=True,
            max_bytes=32_768,
            error_code="invalid_conversation_event_draft",
        )
        if event.mail_message_id is None:
            rows = self.connection.execute(
                "SELECT * FROM conversation_events "
                "WHERE subject_id=? AND mail_message_id IS NULL "
                "AND event_type=? AND related_run_key=?",
                (run["subject_id"], event.event_type, run_key),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM conversation_events "
                "WHERE subject_id=? AND mail_message_id=? AND event_type=?",
                (run["subject_id"], event.mail_message_id, event.event_type),
            ).fetchall()
        if len(rows) > 1:
            raise MailRepositoryError("conversation_event_identity_ambiguous")
        if rows:
            if not self._event_row_matches(rows[0], run, event):
                raise MailRepositoryError("conversation_event_conflicts_with_existing")
            return int(rows[0]["id"])
        cursor = self.connection.execute(
            "INSERT INTO conversation_events("
            "subject_id,event_type,actor_role,occurred_at_utc,mail_message_id,"
            "related_run_key,structured_payload_json,trust_level,created_by"
            ") VALUES(?,?,?,?,?,?,?,?,?)",
            (
                run["subject_id"],
                event.event_type,
                event.actor_role,
                event.occurred_at_utc,
                event.mail_message_id,
                run_key,
                canonical_payload,
                event.trust_level,
                event.created_by,
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _fact_row_matches(
        row: sqlite3.Row,
        subject_id: int,
        event_id: int,
        fact: FactDraft,
        canonical_fact: str,
    ) -> bool:
        return (
            row["subject_id"],
            row["fact_key"],
            row["fact_value_json"],
            row["scope"],
            row["effective_from_utc"],
            row["expires_at_utc"],
            row["source_event_id"],
            row["confidence"],
            row["is_active"],
        ) == (
            subject_id,
            fact.fact_key,
            canonical_fact,
            fact.scope,
            fact.effective_from_utc,
            fact.expires_at_utc,
            event_id,
            fact.confidence,
            int(fact.is_active),
        )

    def _create_or_recover_fact(
        self,
        subject_id: int,
        event_id: int,
        fact: FactDraft,
        canonical_fact: str,
    ) -> int:
        if fact.supersedes_fact_id is None:
            rows = self.connection.execute(
                "SELECT * FROM user_facts WHERE source_event_id=? AND fact_key=?",
                (event_id, fact.fact_key),
            ).fetchall()
            if len(rows) > 1:
                raise MailRepositoryError("user_fact_identity_ambiguous")
            if rows:
                if not self._fact_row_matches(
                    rows[0], subject_id, event_id, fact, canonical_fact
                ):
                    raise MailRepositoryError("user_fact_conflicts_with_existing")
                return int(rows[0]["id"])
        cursor = self.connection.execute(
            "INSERT INTO user_facts("
            "subject_id,fact_key,fact_value_json,scope,effective_from_utc,"
            "expires_at_utc,source_event_id,confidence,is_active"
            ") VALUES(?,?,?,?,?,?,?,?,?)",
            (
                subject_id,
                fact.fact_key,
                canonical_fact,
                fact.scope,
                fact.effective_from_utc,
                fact.expires_at_utc,
                event_id,
                fact.confidence,
                int(fact.is_active),
            ),
        )
        fact_id = int(cursor.lastrowid)
        if fact.supersedes_fact_id is not None:
            changed = self.connection.execute(
                "UPDATE user_facts SET is_active=0,superseded_by_fact_id=? "
                "WHERE id=? AND subject_id=? AND fact_key=? AND is_active=1 "
                "AND superseded_by_fact_id IS NULL",
                (
                    fact_id,
                    fact.supersedes_fact_id,
                    subject_id,
                    fact.fact_key,
                ),
            ).rowcount
            if changed != 1:
                raise MailRepositoryError("user_fact_supersession_invalid")
        return fact_id

    def _resolve_fact_for_replay(
        self,
        subject_id: int,
        event_id: int,
        fact: FactDraft,
        canonical_fact: str,
    ) -> int:
        if fact.supersedes_fact_id is None:
            rows = self.connection.execute(
                "SELECT * FROM user_facts WHERE source_event_id=? AND fact_key=?",
                (event_id, fact.fact_key),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT new.* FROM user_facts old "
                "JOIN user_facts new ON new.id=old.superseded_by_fact_id "
                "WHERE old.id=? AND new.source_event_id=? AND new.fact_key=?",
                (fact.supersedes_fact_id, event_id, fact.fact_key),
            ).fetchall()
        if (
            len(rows) != 1
            or not self._fact_row_matches(
                rows[0], subject_id, event_id, fact, canonical_fact
            )
        ):
            raise MailRepositoryError("conflicting_mail_response_retry")
        if fact.supersedes_fact_id is not None:
            old = self.connection.execute(
                "SELECT is_active,superseded_by_fact_id FROM user_facts WHERE id=?",
                (fact.supersedes_fact_id,),
            ).fetchone()
            if (
                old is None
                or old["is_active"] != 0
                or old["superseded_by_fact_id"] != rows[0]["id"]
            ):
                raise MailRepositoryError("conflicting_mail_response_retry")
        return int(rows[0]["id"])

    def _assert_response_supersession_chain(self, row: sqlite3.Row) -> None:
        previous_id = row["supersedes_mail_response_artifact_id"]
        if row["revision_no"] == 1:
            if previous_id is not None:
                raise MailRepositoryError("conflicting_mail_response_retry")
            return
        previous = self.connection.execute(
            "SELECT subject_id,mail_thread_id,response_kind,revision_no,is_current "
            "FROM mail_response_artifacts WHERE id=?",
            (previous_id,),
        ).fetchone()
        if (
            previous is None
            or (
                previous["subject_id"],
                previous["mail_thread_id"],
                previous["response_kind"],
                previous["revision_no"],
                previous["is_current"],
            )
            != (
                row["subject_id"],
                row["mail_thread_id"],
                row["response_kind"],
                row["revision_no"] - 1,
                0,
            )
        ):
            raise MailRepositoryError("conflicting_mail_response_retry")

    def _assert_existing_response_matches(
        self,
        run: sqlite3.Row,
        response_id: int,
        draft: AcceptedResponseDraft,
        structured_content_json: str,
        fact_value_json: tuple[str, ...],
    ) -> PublishedResponse:
        row = self.connection.execute(
            "SELECT * FROM mail_response_artifacts WHERE id=?",
            (response_id,),
        ).fetchone()
        if row is None or (
            row["subject_id"],
            row["mail_thread_id"],
            row["in_reply_to_mail_message_id"],
            row["response_kind"],
            row["generated_by_mail_agent_run_id"],
            row["schema_version"],
            row["structured_content_json"],
            row["user_visible_text"],
        ) != (
            run["subject_id"],
            draft.mail_thread_id,
            draft.in_reply_to_mail_message_id,
            draft.response_kind,
            run["id"],
            draft.schema_version,
            structured_content_json,
            draft.user_visible_text,
        ):
            raise MailRepositoryError("conflicting_mail_response_retry")
        digest = hashlib.sha256(
            (structured_content_json + "\n" + draft.user_visible_text).encode("utf-8")
        ).hexdigest()
        if row["content_sha256"] != digest:
            raise MailRepositoryError("conflicting_mail_response_retry")
        self._assert_response_supersession_chain(row)
        existing_inputs = [
            tuple(item)
            for item in self.connection.execute(
                "SELECT input_role,source_entity_type,source_entity_id,"
                "source_revision_id,input_sha256,trust_class "
                "FROM mail_response_inputs WHERE mail_agent_run_id=? ORDER BY ordinal",
                (run["id"],),
            )
        ]
        wanted_inputs = [
            (
                item.input_role,
                item.source_entity_type,
                item.source_entity_id,
                item.source_revision_id,
                item.input_sha256,
                item.trust_class,
            )
            for item in draft.inputs
        ]
        if existing_inputs != wanted_inputs:
            raise MailRepositoryError("conflicting_mail_response_retry")

        event_ids: list[int] = []
        for event in draft.events:
            if event.mail_message_id is None:
                rows = self.connection.execute(
                    "SELECT * FROM conversation_events "
                    "WHERE subject_id=? AND mail_message_id IS NULL "
                    "AND event_type=? AND related_run_key=?",
                    (
                        run["subject_id"],
                        event.event_type,
                        event.related_run_key or run["run_key"],
                    ),
                ).fetchall()
            else:
                rows = self.connection.execute(
                    "SELECT * FROM conversation_events "
                    "WHERE subject_id=? AND mail_message_id=? AND event_type=?",
                    (run["subject_id"], event.mail_message_id, event.event_type),
                ).fetchall()
            if len(rows) != 1 or not self._event_row_matches(rows[0], run, event):
                raise MailRepositoryError("conflicting_mail_response_retry")
            event_ids.append(int(rows[0]["id"]))
        facts_by_event = {
            event.event_type: event_id
            for event, event_id in zip(draft.events, event_ids)
        }
        fact_ids = [
            self._resolve_fact_for_replay(
                run["subject_id"],
                facts_by_event[fact.source_event_type],
                fact,
                canonical_fact,
            )
            for fact, canonical_fact in zip(draft.facts, fact_value_json)
        ]

        deliveries = self.connection.execute(
            "SELECT d.*,a.mail_response_artifact_id,a.content_role,a.ordinal "
            "FROM mail_deliveries d "
            "JOIN mail_delivery_artifacts a ON a.mail_delivery_id=d.id "
            "WHERE a.mail_response_artifact_id=?",
            (response_id,),
        ).fetchall()
        if draft.delivery is None:
            if deliveries:
                raise MailRepositoryError("conflicting_mail_response_retry")
            delivery_id = None
        else:
            if len(deliveries) != 1:
                raise MailRepositoryError("conflicting_mail_response_retry")
            delivery = deliveries[0]
            if (
                delivery["idempotency_key"],
                delivery["delivery_kind"],
                delivery["related_run_key"],
                delivery["provider_thread_id"],
                delivery["mail_response_artifact_id"],
                delivery["content_role"],
                delivery["ordinal"],
            ) != (
                draft.delivery.idempotency_key,
                "mail_response",
                run["run_key"],
                draft.delivery.provider_thread_id,
                response_id,
                "mail_response",
                0,
            ):
                raise MailRepositoryError("conflicting_mail_response_retry")
            delivery_id = int(delivery["id"])
        return PublishedResponse(
            response_id, delivery_id, tuple(event_ids), tuple(fact_ids)
        )
