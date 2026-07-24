"""Synthetic lower-layer and Gmail doubles for fifth-layer contract tests.

They only replay supplied, de-identified receipts.  They cannot contact providers,
read an inbox, access configuration, or persist any data.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping


RECEIPT_REQUIRED_BY_LAYER: Mapping[str, tuple[str, ...]] = {
    "foundation": ("schema_version", "invocation_id", "mode", "status", "foundation_schema_version", "ready", "created_count", "existing_count", "verified_count", "migration_start_version", "migration_end_version", "applied_migration_ids", "next_action", "warnings", "errors", "started_at_utc", "completed_at_utc"),
    "garmin": ("schema_version", "run_id", "mode", "status", "requested_range", "effective_range", "coverage_state", "counts", "complete_through_by_resource", "open_gap_count", "next_retry_at_utc", "errors", "started_at_utc", "completed_at_utc"),
    "analysis": ("schema_version", "run_key", "analysis_run_id", "invocation_id", "mode", "status", "target_periods", "quality_gate_state", "artifact_ids", "training_plan_id", "superseded_plan_id", "delivery", "input_snapshot_sha256", "harness_version", "input_schema_version", "output_schema_version", "warnings", "errors", "next_action", "next_retry_at_utc", "started_at_utc", "completed_at_utc"),
    "mail": ("schema_version", "run_key", "mail_agent_run_id", "invocation_id", "mode", "status", "counts", "processed_message_ids", "mail_response_artifact_ids", "mail_delivery_ids", "pending_dependencies", "poll_state", "next_action", "next_retry_at_utc", "warnings", "errors", "started_at_utc", "completed_at_utc"),
    "orchestration": ("schema_version", "workflow_run_id", "workflow_key", "workflow_kind", "status", "trigger_kind", "scheduled_at_utc", "started_at_utc", "completed_at_utc", "logical_local_date", "steps", "next_action", "next_retry_at_utc", "incident_ids", "warnings", "errors"),
}


def _validate_receipt_fields(layer: str, receipt: Mapping[str, Any]) -> None:
    missing = [name for name in RECEIPT_REQUIRED_BY_LAYER[layer] if name not in receipt]
    if missing:
        raise ValueError("fake_receipt_missing_fields:" + ",".join(missing))


@dataclass
class _ReceiptFake:
    receipts_by_mode: Mapping[str, Mapping[str, Any]]
    invocations: list[dict[str, Any]] = field(default_factory=list)

    MODES: ClassVar[frozenset[str]] = frozenset()
    STATUSES: ClassVar[frozenset[str]] = frozenset()
    STATUS_ONLY_SELECTOR: ClassVar[str | None] = None
    LAYER: ClassVar[str] = ""

    def execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        mode = request.get("mode")
        if not isinstance(mode, str) or mode not in self.MODES:
            raise ValueError("unsupported_fake_mode")
        selector = self.STATUS_ONLY_SELECTOR
        if selector is not None and request.get(selector) is not None and mode != "status":
            raise ValueError("status_only_selector_non_status")
        if selector is not None and mode == "status" and request.get(selector) is not None and not isinstance(request[selector], str):
            raise ValueError("invalid_status_only_selector")
        if mode not in self.receipts_by_mode:
            raise ValueError("fake_receipt_not_configured")
        receipt = deepcopy(dict(self.receipts_by_mode[mode]))
        _validate_receipt_fields(self.LAYER, receipt)
        if receipt.get("status") not in self.STATUSES:
            raise ValueError("unsupported_fake_status")
        self.invocations.append({"mode": mode, "invocation_id": request.get("invocation_id")})
        return receipt


class FakeFoundation(_ReceiptFake):
    """Replays Foundation receipts only."""

    MODES = frozenset({"init", "status", "verify", "migrate"})
    STATUSES = frozenset({"initialized", "already_initialized", "ready", "incompatible", "lock_busy", "failed"})
    LAYER = "foundation"


class FakeGarmin(_ReceiptFake):
    """Replays Garmin collection receipts only."""

    MODES = frozenset({"auth", "full", "incremental", "snapshot", "repair", "audit", "status"})
    STATUSES = frozenset({"succeeded", "partial", "deferred", "failed", "auth_required", "lock_busy"})
    LAYER = "garmin"


class FakeAnalysis(_ReceiptFake):
    """Replays Analysis receipts only."""

    MODES = frozenset({"daily", "weekly", "revise_plan", "regenerate", "retry_delivery", "reconcile_delivery", "status"})
    STATUSES = frozenset({"succeeded", "unchanged", "partial", "deferred", "rejected", "failed", "lock_busy"})
    STATUS_ONLY_SELECTOR = "run_key"
    LAYER = "analysis"


class FakeMail(_ReceiptFake):
    """Replays Mail Agent receipts only."""

    MODES = frozenset({"run", "poll", "process", "deliver_response", "reconcile", "status"})
    STATUSES = frozenset({"succeeded", "unchanged", "partial", "deferred", "lock_busy", "auth_required", "rejected", "failed"})
    STATUS_ONLY_SELECTOR = "run_key"
    LAYER = "mail"


@dataclass(frozen=True)
class FakeReceiptFactory:
    """Build independent, de-identified receipt copies for fixture-driven tests."""

    receipts_by_layer: Mapping[str, Mapping[str, Mapping[str, Any]]]

    def build(self, layer: str, mode: str) -> dict[str, Any]:
        try:
            receipt = self.receipts_by_layer[layer][mode]
        except KeyError as exc:
            raise ValueError("fake_receipt_not_configured") from exc
        result = deepcopy(dict(receipt))
        _validate_receipt_fields(layer, result)
        return result


@dataclass
class FakeGmailTransport:
    """Restricted operational-alert Gmail fake; inbox/thread reading is unavailable."""

    self_email: str = "owner@example.invalid"
    known_idempotency_keys: set[str] = field(default_factory=set)
    operations: list[dict[str, str]] = field(default_factory=list)

    def get_self(self) -> str:
        self.operations.append({"operation": "get_self"})
        return self.self_email

    def search_alert(self, idempotency_key: str) -> bool:
        self.operations.append({"operation": "search_alert", "idempotency_key": idempotency_key})
        return idempotency_key in self.known_idempotency_keys

    def send_html_self(self, *, idempotency_key: str, subject: str, html: str) -> dict[str, str]:
        self.operations.append({"operation": "send_html_self", "idempotency_key": idempotency_key})
        self.known_idempotency_keys.add(idempotency_key)
        return {"provider_message_id": "synthetic-alert-message", "subject": subject, "html": html}

    def apply_trainlab_label(self, provider_message_id: str) -> None:
        self.operations.append({"operation": "apply_trainlab_label", "provider_message_id": provider_message_id})
