"""Versioned, data-free interface contracts for fifth-layer development.

S5-00 establishes only the frozen boundary.  It intentionally does not invoke a
lower-layer tool, open SQLite, read configuration, or start a long-running process.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, Mapping


ORCHESTRATION_SCHEMA_VERSION = "1"

FROZEN_CONTRACT_HASHES: Mapping[str, str] = {
    "01-data-foundation.md": "9bf0a91e61bda47c9dba971c731ca6ec79e064b7f0ea4eb8124a5a216d67e396",
    "02-data-collection.md": "c39ae1b82afcafe9f4fc3c54d1f851b4992c48021c5238038f078fab1ec885d6",
    "03-data-analysis.md": "2bc279170dfd7f8fc50acaf96ca631bad0fcd65069f3402a0c6d1b67c0caa99a",
    "04-mail-agent.md": "95ff7a8541c3e803661f4d8543aea545c1f9115fc1990a3409cd574b56d8c8a4",
    "05-orchestration-monitoring.md": "f46aca332f146fa2efffb4da8a03b48037989b7e4e4f31df9d562932e46db356",
}


class ContractSnapshotMismatch(RuntimeError):
    """A frozen cross-layer contract changed, so implementation must stop."""


def project_root() -> Path:
    """Return the repository root without consulting configuration or the network."""
    return Path(__file__).resolve().parents[3]


def verify_frozen_contracts(root: Path | None = None) -> None:
    """Reject work when any authority contract differs from the S5-00 snapshot."""
    root = root or project_root()
    mismatches: list[str] = []
    for filename, expected in FROZEN_CONTRACT_HASHES.items():
        path = root / "docs" / "layers" / filename
        actual = sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"
        if actual != expected:
            mismatches.append(f"{filename}:{actual}")
    if mismatches:
        raise ContractSnapshotMismatch("frozen_contract_mismatch:" + ",".join(mismatches))


@dataclass(frozen=True)
class WorkflowRequest:
    """Draft of the only future fifth-layer application-service request."""

    workflow_kind: Literal["morning", "weekly", "mail", "health_check"]
    subject_id: str | None
    logical_local_date: str | None
    invocation_id: str
    trigger_kind: Literal["scheduled", "recovery", "manual", "dependency"]
    parent_workflow_run_id: str | None
    dependency_ids: tuple[str, ...]
    deadline_at_utc: str
    requested_at_utc: str

    def as_json_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["dependency_ids"] = list(self.dependency_ids)
        return value


@dataclass(frozen=True)
class WorkflowStepReceipt:
    """Public, data-free representation of one downstream invocation."""

    step_id: str
    layer: Literal["foundation", "garmin", "analysis", "mail", "orchestration"]
    mode: str
    status: Literal[
        "pending", "running", "succeeded", "unchanged", "partial", "deferred",
        "lock_busy", "auth_required", "rejected", "failed", "skipped",
    ]
    downstream_run_id: str | None
    downstream_invocation_id: str | None
    receipt_sha256: str | None
    counts: dict[str, int] = field(default_factory=dict)

    def as_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkflowReceipt:
    """Draft of the fifth-layer receipt, deliberately excluding business payloads."""

    workflow_run_id: str
    workflow_key: str
    workflow_kind: Literal["morning", "weekly", "mail", "health_check"]
    status: Literal[
        "queued", "running", "succeeded", "partial", "deferred",
        "attention_required", "failed", "cancelled",
    ]
    trigger_kind: Literal["scheduled", "recovery", "manual", "dependency"]
    scheduled_at_utc: str | None
    started_at_utc: str | None
    completed_at_utc: str | None
    logical_local_date: str | None
    steps: tuple[WorkflowStepReceipt, ...]
    next_action: str
    next_retry_at_utc: str | None
    incident_ids: tuple[str, ...]
    warnings: tuple[dict[str, str], ...]
    errors: tuple[dict[str, str], ...]
    schema_version: str = ORCHESTRATION_SCHEMA_VERSION

    def as_json_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["steps"] = [step.as_json_dict() for step in self.steps]
        value["incident_ids"] = list(self.incident_ids)
        value["warnings"] = list(self.warnings)
        value["errors"] = list(self.errors)
        return value


class ControlledClock:
    """Deterministic UTC clock for fixtures; no wall-clock reads are performed."""

    def __init__(self, now_utc: datetime) -> None:
        if now_utc.tzinfo is None or now_utc.utcoffset() is None:
            raise ValueError("timezone_aware_utc_required")
        self._now = now_utc.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self._now

    def set(self, now_utc: datetime) -> None:
        if now_utc.tzinfo is None or now_utc.utcoffset() is None:
            raise ValueError("timezone_aware_utc_required")
        self._now = now_utc.astimezone(timezone.utc)

    def advance(self, seconds: int) -> datetime:
        self._now += timedelta(seconds=seconds)
        return self._now
