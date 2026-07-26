"""Deterministic, read-only quality facts for Garmin collection.

This module deliberately stops at collection facts.  It never reads raw
payloads, writes a decision back to SQLite, or makes an analysis decision.
The analysis layer consumes the returned, small and safe readiness object.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
import sqlite3
from typing import Literal
from zoneinfo import ZoneInfo

from .garmin_catalog import CATALOG_VERSION, RESOURCE_CATALOG


ReadinessState = Literal["ready", "ready_with_warnings", "blocked"]
QUALITY_EVIDENCE_VERSION = "garmin-quality-v1"
_CLOSED = frozenset({"fetched", "empty"})
_OPTIONAL = frozenset({"not_available", "not_enabled", "not_supported"})
_ACTIVE_ISSUES = frozenset({"open", "acknowledged"})
_SAFE_ENTITY_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-"
)
_LOCAL_TZ = ZoneInfo("Asia/Singapore")


class GarminQualityError(ValueError):
    """Controlled invalid-request or unreadable-database error."""


@dataclass(frozen=True, order=True)
class QualityReason:
    """A safe locator, intentionally never a provider or health payload."""

    code: str
    entity: str

    def __post_init__(self) -> None:
        if not self.code or not self._safe(self.code):
            raise GarminQualityError("garmin_quality_reason_invalid")
        if not self.entity or not self._safe(self.entity):
            raise GarminQualityError("garmin_quality_reason_invalid")

    @staticmethod
    def _safe(value: str) -> bool:
        return len(value) <= 160 and all(char in _SAFE_ENTITY_CHARS for char in value)

    @property
    def summary(self) -> str:
        """Stable log-safe wording; callers must not attach payload text."""
        return self.code.replace("_", " ")


@dataclass(frozen=True)
class QualityGate:
    """Compatibility result for the pre-L2-15 public function."""

    state: ReadinessState
    reasons: tuple[str, ...]
    open_gap_count: int


@dataclass(frozen=True)
class WeekReadiness:
    """Small, reproducible collection fact for a seven-day candidate window."""

    state: ReadinessState
    subject_id: int
    start_local_date: str
    through_local_date: str
    blockers: tuple[QualityReason, ...]
    warnings: tuple[QualityReason, ...]
    open_gap_count: int
    evidence_version: str = QUALITY_EVIDENCE_VERSION

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(reason.code for reason in (*self.blockers, *self.warnings))


@dataclass(frozen=True)
class IntegrityFact:
    """A non-payload fact used by collection audit and monitoring only."""

    check: str
    entity: str
    severity: Literal["warning", "error"]


def _date(value: str) -> date:
    if not isinstance(value, str):
        raise GarminQualityError("garmin_quality_date_invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise GarminQualityError("garmin_quality_date_invalid") from error
    if parsed.isoformat() != value:
        raise GarminQualityError("garmin_quality_date_invalid")
    return parsed


def _reason(code: str, entity: str) -> QualityReason:
    # Entity construction is ours; fail closed rather than logging unexpected DB text.
    try:
        return QualityReason(code, entity)
    except GarminQualityError:
        return QualityReason("quality_evidence_invalid", "collection")


def _read_connection(database_path: str) -> sqlite3.Connection:
    if not isinstance(database_path, str) or not database_path:
        raise GarminQualityError("garmin_quality_database_invalid")
    try:
        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=ON")
        return connection
    except (sqlite3.Error, ValueError) as error:
        raise GarminQualityError("garmin_quality_database_unreadable") from error


def _resource_kinds() -> tuple[str, ...]:
    # The catalog is the authority.  Account-only resources have no date cursor
    # and activity sub-stages are checked per discovered activity below.
    return tuple(sorted(
        spec.resource_kind
        for spec in RESOURCE_CATALOG.values()
        if spec.cursor_eligible and spec.scope in {"daily", "range"}
    ))


def _rows(connection: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> list[sqlite3.Row]:
    prior = connection.row_factory
    connection.row_factory = sqlite3.Row
    try:
        return list(connection.execute(sql, params))
    except sqlite3.Error as error:
        raise GarminQualityError("garmin_quality_database_unreadable") from error
    finally:
        connection.row_factory = prior


def _append_unique(target: list[QualityReason], reason: QualityReason) -> None:
    if reason not in target:
        target.append(reason)


def _subject_valid(connection: sqlite3.Connection, subject_id: int) -> bool:
    rows = _rows(
        connection,
        "SELECT id FROM data_subjects WHERE id=? AND is_active=1 AND timezone='Asia/Singapore'",
        (subject_id,),
    )
    return len(rows) == 1


def _latest_capabilities(connection: sqlite3.Connection, subject_id: int) -> dict[str, str | None]:
    # Different environments cannot silently be mixed; an active account has a
    # single authoritative capability observation per resource/environment.
    result: dict[str, str | None] = {}
    for kind in _resource_kinds():
        rows = _rows(
            connection,
            "SELECT environment_key,capability_state FROM garmin_resource_capabilities "
            "WHERE subject_id=? AND resource_kind=? ORDER BY last_checked_at_utc DESC,id DESC",
            (subject_id, kind),
        )
        environments = {str(row["environment_key"]) for row in rows}
        if not rows:
            result[kind] = None
        elif len(environments) != 1:
            result[kind] = "conflict"
        else:
            result[kind] = str(rows[0]["capability_state"])
    return result


def _coverage_for_day(
    connection: sqlite3.Connection, subject_id: int, resource_kind: str, day: str
) -> tuple[str, int] | None:
    # A later completed-day result replaces a snapshot partial.  Equal-time,
    # conflicting rows remain deliberately ambiguous.
    rows = _rows(
        connection,
        "SELECT availability_state,record_count,observed_at_utc FROM resource_coverage "
        "WHERE subject_id=? AND provider='garmin' AND resource_kind=? AND local_date=? "
        "ORDER BY observed_at_utc DESC,id DESC",
        (subject_id, resource_kind, day),
    )
    if not rows:
        return None
    newest = rows[0]["observed_at_utc"]
    candidates = {(str(row["availability_state"]), int(row["record_count"])) for row in rows if row["observed_at_utc"] == newest}
    return next(iter(candidates)) if len(candidates) == 1 else ("ambiguous", 0)


def _cursor_complete(connection: sqlite3.Connection, subject_id: int, resource_kind: str) -> str | None:
    rows = _rows(
        connection,
        "SELECT complete_through_local_date,cursor_grain,catalog_version FROM garmin_sync_cursors "
        "WHERE subject_id=? AND resource_kind=?",
        (subject_id, resource_kind),
    )
    if len(rows) != 1 or rows[0]["cursor_grain"] != "local_date" or rows[0]["catalog_version"] != CATALOG_VERSION:
        return None
    value = rows[0]["complete_through_local_date"]
    try:
        return _date(value).isoformat() if value is not None else None
    except GarminQualityError:
        return None


def _activity_reasons(connection: sqlite3.Connection, subject_id: int, start: str, through: str) -> list[QualityReason]:
    rows = _rows(
        connection,
        "SELECT a.id,a.local_date,a.provider_state,"
        "SUM(CASE WHEN ar.source_role='summary_json' AND ar.is_active=1 AND sr.is_current=1 AND sr.parsed_at_utc IS NOT NULL AND sr.resource_kind='activity_summary' THEN 1 ELSE 0 END) AS summary_count,"
        "SUM(CASE WHEN ar.source_role='activity_fit' AND ar.is_active=1 AND sr.is_current=1 AND sr.parsed_at_utc IS NOT NULL AND sr.resource_kind='activity_fit' THEN 1 ELSE 0 END) AS fit_count,"
        "SUM(CASE WHEN ar.source_role='details_json_fallback' AND ar.is_active=1 AND sr.is_current=1 AND sr.parsed_at_utc IS NOT NULL AND sr.resource_kind='activity_details_fallback' THEN 1 ELSE 0 END) AS fallback_count "
        "FROM activities a LEFT JOIN activity_source_revisions ar ON ar.activity_id=a.id "
        "LEFT JOIN source_revisions sr ON sr.id=ar.source_revision_id "
        "WHERE a.subject_id=? AND a.provider='garmin' AND a.local_date BETWEEN ? AND ? "
        "AND a.provider_state IN ('active','suspected_missing') GROUP BY a.id",
        (subject_id, start, through),
    )
    reasons: list[QualityReason] = []
    for row in rows:
        entity = f"activity:{int(row['id'])}"
        if row["provider_state"] != "active":
            _append_unique(reasons, _reason("activity_provider_state_incomplete", entity))
        if int(row["summary_count"]) != 1:
            _append_unique(reasons, _reason("activity_summary_incomplete", entity))
        if int(row["fit_count"]) != 1 and int(row["fallback_count"]) != 1:
            _append_unique(reasons, _reason("activity_fit_or_fallback_incomplete", entity))
    return reasons


def _gap_reasons(connection: sqlite3.Connection, subject_id: int, start: str, through: str) -> list[QualityReason]:
    rows = _rows(
        connection,
        "SELECT resource_kind,logical_object_key,window_start_local_date,window_end_local_date,status "
        "FROM garmin_sync_gaps WHERE subject_id=? AND status IN ('open','deferred') "
        "AND (window_end_local_date='' OR window_end_local_date>=?) "
        "AND (window_start_local_date='' OR window_start_local_date<=?)",
        (subject_id, start, through),
    )
    reasons: list[QualityReason] = []
    for row in rows:
        # Never put an arbitrary provider object key in a log-safe entity.
        kind = str(row["resource_kind"])
        entity = f"gap:{kind}" if QualityReason._safe(kind) else "gap:unknown"
        _append_unique(reasons, _reason("gap_deferred" if row["status"] == "deferred" else "gap_open", entity))
    return reasons


def _quality_issue_reasons(connection: sqlite3.Connection, subject_id: int, start: str, through: str) -> tuple[list[QualityReason], list[QualityReason]]:
    # Issues have no subject FK. Restrict activity issues through the activity
    # owner and date.  Unscoped collection/subject rows are deliberately not
    # attributed: otherwise one account could block every other account.
    rows = _rows(
        connection,
        "SELECT q.entity_type,q.entity_id,q.severity FROM data_quality_issues q "
        "LEFT JOIN activities a ON q.entity_type='activity' AND q.entity_id=a.id "
        "WHERE q.status IN ('open','acknowledged') AND q.entity_type='activity' "
        "AND a.subject_id=? AND a.local_date BETWEEN ? AND ?",
        (subject_id, start, through),
    )
    blockers: list[QualityReason] = []
    warnings: list[QualityReason] = []
    for row in rows:
        entity = f"{row['entity_type']}:{row['entity_id'] if row['entity_id'] is not None else 'unknown'}"
        if row["severity"] == "error":
            _append_unique(blockers, _reason("quality_error", entity))
        elif row["severity"] == "warning":
            _append_unique(warnings, _reason("quality_warning", entity))
    return blockers, warnings


def _open_gap_count(connection: sqlite3.Connection, subject_id: int, start: str, through: str) -> int:
    row = _rows(
        connection,
        "SELECT count(*) FROM garmin_sync_gaps WHERE subject_id=? AND status IN ('open','deferred') "
        "AND (window_end_local_date='' OR window_end_local_date>=?) "
        "AND (window_start_local_date='' OR window_start_local_date<=?)",
        (subject_id, start, through),
    )
    return int(row[0][0])


def evaluate_week_readiness(connection: sqlite3.Connection, subject_id: int, through: str) -> WeekReadiness:
    """Evaluate seven completed local dates using caller-owned read connection.

    The function changes no connection data.  Database/query faults are
    represented as a conservative ``blocked`` result rather than a leak-prone
    provider/database exception.
    """
    if isinstance(subject_id, bool) or not isinstance(subject_id, int) or subject_id <= 0:
        raise GarminQualityError("garmin_quality_subject_invalid")
    end = _date(through)
    start = end - timedelta(days=6)
    start_text, end_text = start.isoformat(), end.isoformat()
    blockers: list[QualityReason] = []
    warnings: list[QualityReason] = []
    try:
        if not _subject_valid(connection, subject_id):
            _append_unique(blockers, _reason("subject_identity_invalid", "subject"))
        capabilities = _latest_capabilities(connection, subject_id)
        for kind, capability in capabilities.items():
            spec = RESOURCE_CATALOG[kind]
            if capability is None:
                _append_unique(blockers, _reason("capability_missing", kind))
                continue
            if capability == "conflict" or capability not in {"supported", *_OPTIONAL, "forbidden", "unknown"}:
                _append_unique(blockers, _reason("capability_conflict", kind))
                continue
            if capability in {"forbidden", "unknown"}:
                _append_unique(blockers, _reason("capability_unavailable", kind))
                continue
            if capability in _OPTIONAL:
                if spec.required:
                    _append_unique(blockers, _reason("capability_required_unavailable", kind))
                else:
                    _append_unique(warnings, _reason("capability_optional_unavailable", kind))
                continue
            cursor = _cursor_complete(connection, subject_id, kind)
            if cursor is None or cursor < end_text:
                _append_unique(blockers, _reason("cursor_incomplete", kind))
            for offset in range(7):
                day = (start + timedelta(days=offset)).isoformat()
                coverage = _coverage_for_day(connection, subject_id, kind, day)
                entity = f"{kind}:{day}"
                if coverage is None:
                    _append_unique(blockers, _reason("coverage_missing", entity))
                elif coverage[0] == "partial":
                    _append_unique(blockers, _reason("coverage_partial", entity))
                elif coverage[0] in {"error", "forbidden", "ambiguous"} or coverage[0] not in _CLOSED:
                    _append_unique(blockers, _reason("coverage_invalid", entity))
        for reason in _gap_reasons(connection, subject_id, start_text, end_text):
            _append_unique(blockers, reason)
        for reason in _activity_reasons(connection, subject_id, start_text, end_text):
            _append_unique(blockers, reason)
        issue_blockers, issue_warnings = _quality_issue_reasons(connection, subject_id, start_text, end_text)
        for reason in issue_blockers:
            _append_unique(blockers, reason)
        for reason in issue_warnings:
            _append_unique(warnings, reason)
    except (GarminQualityError, sqlite3.Error, TypeError, ValueError):
        blockers = [_reason("quality_evaluation_failed", "collection")]
        warnings = []
    state: ReadinessState = "blocked" if blockers else ("ready_with_warnings" if warnings else "ready")
    try:
        gap_count = _open_gap_count(connection, subject_id, start_text, end_text)
    except (GarminQualityError, sqlite3.Error, TypeError, ValueError):
        gap_count = 0
    return WeekReadiness(state, subject_id, start_text, end_text, tuple(sorted(blockers)), tuple(sorted(warnings)), gap_count)


def week_readiness(database_path: str, subject_id: int, through: str) -> WeekReadiness:
    """Open the database read-only and return a collection-owned safe fact."""
    connection = _read_connection(database_path)
    try:
        return evaluate_week_readiness(connection, subject_id, through)
    finally:
        connection.close()


def weekly_quality_gate(database_path: str, subject_id: int, through: str) -> QualityGate:
    """Backward-compatible compact view of :func:`week_readiness`."""
    result = week_readiness(database_path, subject_id, through)
    return QualityGate(result.state, result.reasons, result.open_gap_count)


def collection_integrity_facts(database_path: str, subject_id: int, through: str) -> tuple[IntegrityFact, ...]:
    """Return safe run-level integrity failures; it never writes a verdict.

    This checks the relational invariants not expressible by coverage alone:
    sleep bounds, sample ordering, activity stage, reconciliation mismatch and
    cursors crossing unresolved gaps.  It intentionally returns identifiers,
    not raw values, coordinates, timestamps or payload details.
    """
    end = _date(through)
    start_date = end - timedelta(days=6)
    start = start_date.isoformat()
    window_start_utc = datetime.combine(
        start_date, time.min, _LOCAL_TZ
    ).astimezone(UTC).isoformat().replace("+00:00", "Z")
    window_end_utc = datetime.combine(
        end + timedelta(days=1), time.min, _LOCAL_TZ
    ).astimezone(UTC).isoformat().replace("+00:00", "Z")
    connection = _read_connection(database_path)
    facts: list[IntegrityFact] = []
    try:
        if not _subject_valid(connection, subject_id):
            return (IntegrityFact("subject_identity_invalid", "subject", "error"),)
        checks = (
            (
                "sleep_stage_outside_session",
                """SELECT ss.id FROM sleep_stages s
                   JOIN sleep_sessions ss ON ss.id=s.sleep_session_id
                   WHERE ss.subject_id=? AND ss.start_time_utc<?
                     AND ss.end_time_utc>?
                     AND (s.start_time_utc<ss.start_time_utc
                          OR s.end_time_utc>ss.end_time_utc
                          OR s.end_time_utc<s.start_time_utc)""",
                "sleep",
                (subject_id, window_end_utc, window_start_utc),
            ),
            (
                "sample_timestamp_nonmonotonic",
                "SELECT DISTINCT a.id FROM activity_samples x JOIN activity_samples y ON y.activity_id=x.activity_id AND y.source_revision_id=x.source_revision_id AND y.stream_kind=x.stream_kind AND y.sample_index=x.sample_index+1 JOIN activities a ON a.id=x.activity_id WHERE a.subject_id=? AND a.local_date BETWEEN ? AND ? AND x.timestamp_utc IS NOT NULL AND y.timestamp_utc IS NOT NULL AND y.timestamp_utc<x.timestamp_utc",
                "activity",
                (subject_id, start, through),
            ),
            (
                "reconciliation_mismatch",
                "SELECT a.id FROM reconciliation_results r JOIN activities a ON r.entity_type='activity' AND r.entity_id=a.id WHERE a.subject_id=? AND a.local_date BETWEEN ? AND ? AND r.result='mismatch'",
                "activity",
                (subject_id, start, through),
            ),
            (
                "cursor_crosses_open_gap",
                "SELECT g.resource_kind FROM garmin_sync_gaps g JOIN garmin_sync_cursors c ON c.subject_id=g.subject_id AND c.resource_kind=g.resource_kind WHERE g.subject_id=? AND g.status IN ('open','deferred') AND (g.window_start_local_date='' OR c.complete_through_local_date>=g.window_start_local_date)",
                "resource",
                (subject_id,),
            ),
        )
        for check, sql, prefix, params in checks:
            for row in _rows(connection, sql, params):
                value = str(row[0])
                entity = f"{prefix}:{value}" if QualityReason._safe(value) else f"{prefix}:unknown"
                fact = IntegrityFact(check, entity, "error")
                if fact not in facts:
                    facts.append(fact)
        for reason in _activity_reasons(connection, subject_id, start, through):
            facts.append(IntegrityFact(reason.code, reason.entity, "error"))
    except (GarminQualityError, sqlite3.Error, TypeError, ValueError):
        facts = [IntegrityFact("quality_evaluation_failed", "collection", "error")]
    finally:
        connection.close()
    return tuple(sorted(set(facts), key=lambda fact: (fact.check, fact.entity)))
