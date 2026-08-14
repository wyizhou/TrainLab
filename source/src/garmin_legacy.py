"""L2-17 data-free legacy/Connect shadow reconciliation evidence.

This module intentionally has no database, provider, scheduler, or CLI
dependency.  A later migration task may feed it independently produced,
de-identified counts and hashes.  Its output is evidence only: it never selects
or changes a canonical source of truth.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Literal, Sequence, cast

REPORT_SCHEMA_VERSION = "1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DIFFERENCE_CODES = frozenset(
    {
        "activity_count_mismatch",
        "activity_missing_in_garmin",
        "activity_missing_in_legacy",
        "daily_coverage_mismatch",
        "legacy_snapshot_unavailable",
        "garmin_snapshot_unavailable",
    }
)


class LegacyReconciliationError(ValueError):
    """The caller attempted to put payload data into a summary-only report."""


@dataclass(frozen=True, slots=True)
class ReconciliationCounts:
    activity_count: int
    daily_coverage_count: int


@dataclass(frozen=True, slots=True)
class ReconciliationDifference:
    code: str
    entity_kind: Literal["activity", "daily_health", "snapshot"]
    legacy_count: int
    garmin_count: int


def _iso_date(value: str, error: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise LegacyReconciliationError(error) from exc


def _utc(value: str) -> str:
    if type(value) is not str or not _UTC.fullmatch(value):
        raise LegacyReconciliationError("legacy_reconciliation_timestamp_invalid")
    try:
        return (
            datetime.fromisoformat(value[:-1] + "+00:00")
            .astimezone(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    except ValueError as exc:
        raise LegacyReconciliationError(
            "legacy_reconciliation_timestamp_invalid"
        ) from exc


def _count(value: int) -> int:
    if type(value) is not int or value < 0:
        raise LegacyReconciliationError("legacy_reconciliation_count_invalid")
    return value


def _hash(value: str) -> str:
    if type(value) is not str or not _HASH.fullmatch(value):
        raise LegacyReconciliationError("legacy_reconciliation_hash_invalid")
    return value


def build_legacy_reconciliation_report(
    *,
    report_id: str,
    start_local_date: str,
    end_local_date: str,
    generated_at_utc: str,
    legacy_counts: ReconciliationCounts,
    garmin_counts: ReconciliationCounts,
    legacy_snapshot_sha256: str,
    garmin_snapshot_sha256: str,
    differences: Sequence[ReconciliationDifference] = (),
) -> dict[str, object]:
    """Build one schema-safe, payload-free shadow reconciliation report.

    Hashes identify separately retained snapshots without copying them here.  A
    non-empty difference list makes the report ``investigate``; it does not
    select Garmin or legacy as canonical and cannot trigger a cutover.
    """
    if type(report_id) is not str or not _ID.fullmatch(report_id):
        raise LegacyReconciliationError("legacy_reconciliation_report_id_invalid")
    start, end = (
        _iso_date(start_local_date, "legacy_reconciliation_date_invalid"),
        _iso_date(end_local_date, "legacy_reconciliation_date_invalid"),
    )
    if start > end:
        raise LegacyReconciliationError("legacy_reconciliation_date_range_invalid")
    normalized: list[dict[str, object]] = []
    for difference in differences:
        if (
            type(difference) is not ReconciliationDifference
            or difference.code not in _DIFFERENCE_CODES
        ):
            raise LegacyReconciliationError("legacy_reconciliation_difference_invalid")
        if difference.entity_kind not in {"activity", "daily_health", "snapshot"}:
            raise LegacyReconciliationError("legacy_reconciliation_difference_invalid")
        normalized.append(
            {
                "code": difference.code,
                "entity_kind": difference.entity_kind,
                "legacy_count": _count(difference.legacy_count),
                "garmin_count": _count(difference.garmin_count),
            }
        )
    normalized.sort(
        key=lambda item: (
            str(item["code"]),
            str(item["entity_kind"]),
            int(cast(int, item["legacy_count"])),
            int(cast(int, item["garmin_count"])),
        )
    )
    legacy = {
        "activity_count": _count(legacy_counts.activity_count),
        "daily_coverage_count": _count(legacy_counts.daily_coverage_count),
    }
    garmin = {
        "activity_count": _count(garmin_counts.activity_count),
        "daily_coverage_count": _count(garmin_counts.daily_coverage_count),
    }
    report: dict[str, object] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_id": report_id,
        "generated_at_utc": _utc(generated_at_utc),
        "window": {"start_local_date": start, "end_local_date": end},
        "shadow_only": True,
        "canonical_owner": "unchanged",
        "legacy": legacy,
        "garmin": garmin,
        "snapshot_hashes": {
            "legacy_snapshot_sha256": _hash(legacy_snapshot_sha256),
            "garmin_snapshot_sha256": _hash(garmin_snapshot_sha256),
        },
        "differences": normalized,
        "decision": "investigate" if normalized else "observe",
    }
    canonical = json.dumps(
        report, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    report["report_sha256"] = sha256(canonical).hexdigest()
    return report
