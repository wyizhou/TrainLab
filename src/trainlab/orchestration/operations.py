"""Restricted, data-free operator actions for Layer 5.

The Foundation schema intentionally has no generic audit or free-form command
table.  This adapter therefore persists a bounded audit observation in the
orchestrator-owned ``service_health_checks`` table.  It never accepts SQL,
commands, paths, recipients, prompts, or business payloads.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
import re
import stat
from pathlib import Path
from typing import Literal, Protocol


_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_INCIDENT = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_ACTIONS = frozenset({"retry", "reconcile", "acknowledge", "suppress", "resume", "forced_takeover"})
_LOG_KEYS = frozenset({"event", "workflow", "step", "layer", "mode", "status", "error_code", "instance", "action"})


class OperationError(ValueError):
    """An operator action cannot be safely accepted."""


class OperationRepository(Protocol):
    def record_health_check(self, **values: object) -> int: ...
    def transition_incident(self, incident_key: str, state: str, *, at_utc: datetime): ...


@dataclass(frozen=True, slots=True)
class OperationReceipt:
    """Public audit outcome.  It deliberately has no business content."""

    action: Literal["retry", "reconcile", "acknowledge", "suppress", "resume", "forced_takeover"]
    status: Literal["accepted", "rejected"]
    audit_id: int | None
    target_sha256: str
    error_code: str | None = None

    def as_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "action": self.action,
            "status": self.status,
            "audit_id": self.audit_id,
            "target_sha256": self.target_sha256,
            "error_code": self.error_code,
        }


def _utc(value: datetime | None) -> datetime:
    value = value or datetime.now(UTC)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise OperationError("operation_time_invalid")
    return value.astimezone(UTC)


def _id(value: str, code: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise OperationError(code)
    return value


def _target_digest(action: str, target: str, operator_id: str) -> str:
    return sha256(f"operation-v1\0{action}\0{target}\0{operator_id}".encode("utf-8")).hexdigest()


class OperatorOperations:
    """Persist a bounded audit before returning an operator action receipt.

    The workflow executor remains the only place that may resume/reconcile a
    lower-layer operation.  This class intentionally does *not* manufacture an
    invocation ID or directly mutate any lower-layer table.
    """

    def __init__(self, repository: OperationRepository | None) -> None:
        self._repository = repository

    def audit(
        self,
        action: Literal["retry", "reconcile", "acknowledge", "suppress", "resume", "forced_takeover"],
        *,
        target_id: str,
        operator_id: str,
        at_utc: datetime | None = None,
    ) -> OperationReceipt:
        if action not in _ACTIONS:
            raise OperationError("operation_action_invalid")
        target = _id(target_id, "operation_target_invalid")
        operator = _id(operator_id, "operation_operator_invalid")
        now = _utc(at_utc)
        digest = _target_digest(action, target, operator)
        if self._repository is None:
            return OperationReceipt(action, "rejected", None, digest, "operation_repository_required")
        try:
            audit_id = self._repository.record_health_check(
                check_kind="operator_action",
                target_kind=action,
                target_id=digest[:32],
                status="accepted",
                metrics={"action_version": "v1", "operator_sha256": sha256(operator.encode("utf-8")).hexdigest()},
                threshold_version="s5_16",
                checked_at_utc=now,
            )
        except Exception:
            return OperationReceipt(action, "rejected", None, digest, "operation_audit_unavailable")
        return OperationReceipt(action, "accepted", int(audit_id), digest)

    def acknowledge(self, incident_key: str, *, operator_id: str, at_utc: datetime | None = None) -> OperationReceipt:
        _id(incident_key, "operation_incident_invalid")
        receipt = self.audit("acknowledge", target_id=incident_key, operator_id=operator_id, at_utc=at_utc)
        if receipt.status != "accepted" or self._repository is None:
            return receipt
        try:
            self._repository.transition_incident(incident_key, "acknowledged", at_utc=_utc(at_utc))
        except Exception:
            return OperationReceipt("acknowledge", "rejected", receipt.audit_id, receipt.target_sha256, "operation_transition_rejected")
        return receipt

    def suppress(self, incident_key: str, *, operator_id: str, at_utc: datetime | None = None) -> OperationReceipt:
        _id(incident_key, "operation_incident_invalid")
        receipt = self.audit("suppress", target_id=incident_key, operator_id=operator_id, at_utc=at_utc)
        if receipt.status != "accepted" or self._repository is None:
            return receipt
        try:
            self._repository.transition_incident(incident_key, "suppressed", at_utc=_utc(at_utc))
        except Exception:
            return OperationReceipt("suppress", "rejected", receipt.audit_id, receipt.target_sha256, "operation_transition_rejected")
        return receipt


class RedactingAuditLogger:
    """Owner-only, size-rotated event log with a deliberately tiny schema.

    It is not a general logging sink: callers cannot place request bodies,
    credentials, prompts, or arbitrary exception text into this log.
    """

    def __init__(self, log_root: Path, *, max_bytes: int = 1_000_000) -> None:
        if type(max_bytes) is not int or not 1_024 <= max_bytes <= 100_000_000:
            raise OperationError("operation_log_limit_invalid")
        self._root = Path(log_root)
        self._max_bytes = max_bytes

    def write(self, event: str, *, at_utc: datetime | None = None, **fields: str) -> None:
        if event not in {"supervisor", "workflow", "operation", "doctor"}:
            raise OperationError("operation_log_event_invalid")
        safe: dict[str, str] = {"event": event, "at_utc": _utc(at_utc).isoformat().replace("+00:00", "Z")}
        for key, value in fields.items():
            if key not in _LOG_KEYS or not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
                raise OperationError("operation_log_field_invalid")
            safe[key] = value
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        details = self._root.stat()
        if not stat.S_ISDIR(details.st_mode) or details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) & 0o077:
            raise OperationError("operation_log_root_unsafe")
        active, prior = self._root / "orchestrator.jsonl", self._root / "orchestrator.jsonl.1"
        line = json.dumps(safe, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        if active.exists() and active.stat().st_size + len(line.encode("utf-8")) > self._max_bytes:
            # The parent is owner-only and the names are static; no caller
            # controls the target.  Replace a single bounded previous segment.
            os.replace(active, prior)
        flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(active, flags, 0o600)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid() or stat.S_IMODE(opened.st_mode) != 0o600:
                raise OperationError("operation_log_file_unsafe")
            os.write(descriptor, line.encode("utf-8")); os.fsync(descriptor)
        finally:
            os.close(descriptor)
