"""Foundation bootstrap and read-only compatibility boundary for the Supervisor.

This S5-01 adapter deliberately knows only the public Foundation request/receipt
contract.  It never imports ``FoundationTool``, opens SQLite, creates paths, or
offers a migrate operation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from jsonschema import Draft202012Validator


FOUNDATION_RECEIPT_SCHEMA_VERSION = "1"
FOUNDATION_SCHEMA_VERSION = 2
FoundationInvoker = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class FoundationAdapterError(RuntimeError):
    """The public Foundation boundary could not be safely consumed."""


class FoundationBootstrapAlreadyCalled(FoundationAdapterError):
    """A Supervisor lifetime may submit exactly one Foundation init bootstrap."""


@dataclass(frozen=True)
class FoundationAuditReference:
    """Data-free receipt reference suitable for a future orchestrator step record."""

    invocation_id: str
    mode: Literal["init", "status", "verify"]
    status: str
    receipt_sha256: str
    receipt_schema_version: str
    foundation_schema_version: int | None
    error_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]


@dataclass(frozen=True)
class FoundationGateResult:
    """A deterministic decision; later units persist it and create incidents."""

    gate: Literal["ready", "deferred", "attention_required"]
    may_start_workflow: bool
    incident_category: str | None
    maintenance_required: bool
    audit: FoundationAuditReference


class FoundationAdapter:
    """Invoke the frozen Foundation interface without any filesystem side effects."""

    def __init__(
        self,
        invoke: FoundationInvoker,
        *,
        expected_foundation_schema_version: int = FOUNDATION_SCHEMA_VERSION,
        receipt_schema_path: Path | None = None,
    ) -> None:
        self._invoke = invoke
        self._expected_foundation_schema_version = expected_foundation_schema_version
        path = receipt_schema_path or Path(__file__).resolve().parents[3] / "harness" / "schemas" / "foundation_receipt.schema.json"
        self._validator = Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))
        self._bootstrap_called = False

    def bootstrap(self, *, invocation_id: str, requested_at_utc: str) -> FoundationGateResult:
        """Call the only permitted startup write: public ``foundation init`` once."""
        if self._bootstrap_called:
            raise FoundationBootstrapAlreadyCalled("foundation_bootstrap_already_called")
        self._bootstrap_called = True
        return self._invoke_and_gate("init", invocation_id, requested_at_utc)

    def status(self, *, invocation_id: str, requested_at_utc: str) -> FoundationGateResult:
        """Run the public, read-only Foundation status compatibility check."""
        self._require_bootstrap()
        return self._invoke_and_gate("status", invocation_id, requested_at_utc)

    def verify(self, *, invocation_id: str, requested_at_utc: str) -> FoundationGateResult:
        """Run the public, read-only Foundation verify compatibility check."""
        self._require_bootstrap()
        return self._invoke_and_gate("verify", invocation_id, requested_at_utc)

    def _require_bootstrap(self) -> None:
        if not self._bootstrap_called:
            raise FoundationAdapterError("foundation_bootstrap_required")

    def _invoke_and_gate(
        self,
        mode: Literal["init", "status", "verify"],
        invocation_id: str,
        requested_at_utc: str,
    ) -> FoundationGateResult:
        request = {
            "mode": mode,
            "invocation_id": invocation_id,
            "requested_at_utc": requested_at_utc,
            "target_schema_version": None,
        }
        payload = dict(self._invoke(request))
        self._validate_receipt(payload, mode=mode, invocation_id=invocation_id)
        audit = FoundationAuditReference(
            invocation_id=invocation_id,
            mode=mode,
            status=payload["status"],
            receipt_sha256=sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            receipt_schema_version=payload["schema_version"],
            foundation_schema_version=payload["foundation_schema_version"],
            error_codes=tuple(item["code"] for item in payload["errors"]),
            warning_codes=tuple(item["code"] for item in payload["warnings"]),
        )
        status = payload["status"]
        compatible = payload["ready"] and payload["foundation_schema_version"] == self._expected_foundation_schema_version
        if status == "lock_busy":
            return FoundationGateResult("deferred", False, "foundation_lock_busy", False, audit)
        if status == "incompatible":
            return FoundationGateResult("attention_required", False, "foundation_incompatible", True, audit)
        if status == "failed":
            return FoundationGateResult("attention_required", False, "foundation_failed", False, audit)
        if mode == "init" and status != "already_initialized":
            return FoundationGateResult("attention_required", False, "foundation_incompatible", True, audit)
        if compatible:
            return FoundationGateResult("ready", True, None, False, audit)
        return FoundationGateResult("attention_required", False, "foundation_incompatible", True, audit)

    def _validate_receipt(self, payload: Mapping[str, Any], *, mode: str, invocation_id: str) -> None:
        errors = list(self._validator.iter_errors(payload))
        if errors:
            paths = ",".join("/".join(str(part) for part in error.path) or "root" for error in errors)
            raise FoundationAdapterError("invalid_foundation_receipt:" + paths)
        if payload["schema_version"] != FOUNDATION_RECEIPT_SCHEMA_VERSION:
            raise FoundationAdapterError("unsupported_foundation_receipt_schema")
        if payload["mode"] != mode:
            raise FoundationAdapterError("foundation_receipt_mode_mismatch")
        if payload["invocation_id"] != invocation_id:
            raise FoundationAdapterError("foundation_receipt_invocation_mismatch")
