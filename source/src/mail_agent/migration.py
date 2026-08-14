"""Offline M4-15 shadow-comparison and cutover-gate helpers.

The caller supplies de-identified metadata snapshots.  Bodies, credentials,
and provider calls are deliberately outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class MigrationFinding:
    code: str
    entity: str
    summary: str = "mail migration comparison differs"


@dataclass(frozen=True, slots=True)
class ShadowComparison:
    findings: tuple[MigrationFinding, ...]

    @property
    def matches(self) -> bool:
        return not self.findings


_STREAMS: dict[str, tuple[str, tuple[str, ...]]] = {
    "threads": ("provider_thread_id", ("subject_id", "is_current")),
    "messages": (
        "provider_message_id",
        ("provider_thread_id", "processing_state", "source_revision_id"),
    ),
    "responses": (
        "idempotency_key",
        ("provider_thread_id", "response_revision_no", "content_sha256", "is_current"),
    ),
    "deliveries": (
        "idempotency_key",
        ("status", "provider_message_id", "provider_thread_id"),
    ),
    "cursors": ("cursor_key", ("observed_through_utc", "overlap_start_utc", "state")),
}


def _index(
    rows: object, *, stream: str, key: str
) -> tuple[dict[str, Mapping[str, object]], tuple[MigrationFinding, ...]]:
    if not isinstance(rows, (tuple, list)):
        return {}, (MigrationFinding("snapshot_stream_invalid", stream),)
    result: dict[str, Mapping[str, object]] = {}
    findings: list[MigrationFinding] = []
    for position, row in enumerate(rows):
        if (
            not isinstance(row, Mapping)
            or not isinstance(row.get(key), str)
            or not row[key]
        ):
            findings.append(
                MigrationFinding("snapshot_identity_invalid", f"{stream}[{position}]")
            )
            continue
        identity = row[key]
        if identity in result:
            findings.append(
                MigrationFinding("snapshot_identity_duplicate", f"{stream}:{identity}")
            )
            continue
        result[identity] = row
    return result, tuple(findings)


def compare_shadow_snapshots(
    old: Mapping[str, object], new: Mapping[str, object]
) -> ShadowComparison:
    """Compare only immutable identifiers and safe state metadata.

    Unknown extra payload fields are ignored, so an email body can never enter
    a finding.  Missing, duplicate, or mismatched state is fail-closed.
    """
    findings: list[MigrationFinding] = []
    if not isinstance(old, Mapping) or not isinstance(new, Mapping):
        return ShadowComparison((MigrationFinding("snapshot_invalid", "snapshot"),))
    for stream, (key, fields) in _STREAMS.items():
        old_index, old_errors = _index(old.get(stream), stream=stream, key=key)
        new_index, new_errors = _index(new.get(stream), stream=stream, key=key)
        findings.extend(old_errors)
        findings.extend(new_errors)
        for identity in sorted(set(old_index) - set(new_index)):
            findings.append(MigrationFinding("shadow_missing", f"{stream}:{identity}"))
        for identity in sorted(set(new_index) - set(old_index)):
            findings.append(
                MigrationFinding("shadow_unexpected", f"{stream}:{identity}")
            )
        for identity in sorted(set(old_index) & set(new_index)):
            if any(
                old_index[identity].get(name) != new_index[identity].get(name)
                for name in fields
            ):
                findings.append(
                    MigrationFinding("shadow_state_mismatch", f"{stream}:{identity}")
                )
    return ShadowComparison(tuple(findings))


@dataclass(frozen=True, slots=True)
class ExternalAcceptanceGate:
    read_only_authorized: bool = False
    self_send_authorized: bool = False
    reconcile_authorized: bool = False

    def missing(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, allowed in (
                ("read_only", self.read_only_authorized),
                ("self_send", self.self_send_authorized),
                ("reconcile", self.reconcile_authorized),
            )
            if allowed is not True
        )


@dataclass(frozen=True, slots=True)
class CutoverDecision:
    allowed: bool
    reasons: tuple[str, ...]


def evaluate_cutover(
    *,
    backup_id: str | None,
    shadow: ShadowComparison,
    old_writer_enabled: bool,
    new_writer_enabled: bool,
    acceptance: ExternalAcceptanceGate,
) -> CutoverDecision:
    """Fail closed unless backup, clean shadow, one writer, and authority exist."""
    reasons: list[str] = []
    if not isinstance(backup_id, str) or not backup_id:
        reasons.append("backup_required")
    if not shadow.matches:
        reasons.append("shadow_mismatch")
    if bool(old_writer_enabled) == bool(new_writer_enabled):
        reasons.append("single_writer_required")
    reasons.extend(f"authorization_{name}_required" for name in acceptance.missing())
    return CutoverDecision(not reasons, tuple(reasons))


def evaluate_rollback(
    *, backup_id: str | None, new_writer_enabled: bool
) -> CutoverDecision:
    """A rollback is safe only with a named backup and the new writer stopped."""
    reasons: list[str] = []
    if not isinstance(backup_id, str) or not backup_id:
        reasons.append("backup_required")
    if new_writer_enabled is not False:
        reasons.append("new_writer_must_be_stopped")
    return CutoverDecision(not reasons, tuple(reasons))
