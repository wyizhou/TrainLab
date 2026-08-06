"""A3-07 deterministic, snapshot-only route data-quality gates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Literal
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator

from .stable_views import StableSnapshot, StableSubjectContext

QualityRoute = Literal["daily_summary", "weekly_summary", "weekly_plan", "revise_plan"]
QualityGateState = Literal["ready", "ready_with_warnings", "blocked"]
NextAction = Literal["none", "rerun_collection", "repair_data"]

_ROOT = Path(__file__).resolve().parent
_POLICY_BYTES = (_ROOT / "quality_policy.json").read_bytes()
_POLICY: dict[str, Any] = json.loads(_POLICY_BYTES)
_RESULT_SCHEMA: dict[str, Any] = json.loads(
    (_ROOT / "schemas" / "quality_gate_result.schema.json").read_text(encoding="utf-8")
)
_RESULT_VALIDATOR = Draft202012Validator(_RESULT_SCHEMA)

QUALITY_GATE_POLICY_VERSION = str(_POLICY["version"])
QUALITY_GATE_POLICY_SHA256 = sha256(_POLICY_BYTES).hexdigest()
QUALITY_GATE_RESULT_SCHEMA_VERSION = "1"

_CATALOG_VERSION = str(_POLICY["catalog_version"])
_ROUTES = frozenset(_POLICY["routes"])
_REQUIRED: dict[str, bool] = {
    item["resource_kind"]: bool(item["cursor_required"]) for item in _POLICY["required_resources"]
}
_CONDITIONAL: dict[str, bool] = {
    item["resource_kind"]: bool(item["cursor_required"]) for item in _POLICY["conditional_resources"]
}
_RESOURCES = frozenset((*_REQUIRED, *_CONDITIONAL))
_CLOSED = frozenset({"fetched", "empty"})
_OPTIONAL = frozenset({"not_available", "not_enabled", "not_supported"})
_COVERAGE_STATES = _CLOSED | _OPTIONAL | frozenset({"partial", "forbidden", "error"})
_CAPABILITY_STATES = frozenset({"supported", *_OPTIONAL, "forbidden", "unknown"})
_ACTIVE_ISSUE_STATES = frozenset({"open", "acknowledged"})
_INACTIVE_ISSUE_STATES = frozenset({"resolved", "suppressed"})
_PLAN_KINDS = frozenset({"running", "climbing", "strength", "rest"})
_PLAN_FIELDS = frozenset(
    {
        "id",
        "subject_id",
        "analysis_artifact_id",
        "plan_start_local_date",
        "plan_end_local_date",
        "timezone",
        "status",
        "objective_json",
        "constraints_json",
        "created_at_utc",
    }
)
_PLAN_ITEM_FIELDS = frozenset(
    {
        "id",
        "subject_id",
        "training_plan_id",
        "item_index",
        "local_date",
        "activity_kind",
        "prescription_json",
        "rationale_text",
    }
)
_ARTIFACT_FIELDS = frozenset(
    {
        "id",
        "subject_id",
        "artifact_kind",
        "period_start_local_date",
        "period_end_local_date",
        "revision_no",
        "schema_version",
        "content_sha256",
        "created_at_utc",
    }
)
_REASON_FIELDS = frozenset(
    {
        "id",
        "event_type",
        "actor_role",
        "occurred_at_utc",
        "trust_level",
        "created_by",
    }
)
_REASON_DTO_FIELDS = _REASON_FIELDS | frozenset({
    "subject_id", "source_mail_message_id", "source_mail_thread_id",
    "source_revision_id", "change_kind", "affected_local_dates", "constraints",
    "effective_local_date", "current_plan_id",
})
_MAX_REASONS = int(_POLICY["max_reasons_per_bucket"])
_MAX_SNAPSHOT_ROWS = int(_POLICY["max_snapshot_rows"])
_MAX_SNAPSHOT_BYTES = int(_POLICY["max_snapshot_bytes"])
_MAX_ENTITY_LENGTH = int(_POLICY["max_entity_length"])
_REASONS = frozenset(_POLICY["reason_codes"])
_UTC_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?P<fraction>\.\d{1,6})?Z$"
)
_SAFE_ENTITY = re.compile(r"^[A-Za-z0-9_.:-]+$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_HONG_KONG = ZoneInfo("Asia/Hong_Kong")
_MALFORMED_HASH = sha256(b"trainlab:quality-gate:malformed-snapshot:v1").hexdigest()


class QualityGateError(ValueError):
    """Controlled request, policy, or result-contract failure."""


class _SnapshotMalformed(ValueError):
    """Internal marker converted to a sanitized, fail-closed gate result."""


@dataclass(frozen=True, order=True)
class QualityGateReason:
    code: str
    entity: str
    summary: str

    def __post_init__(self) -> None:
        if self.code not in _REASONS:
            raise QualityGateError("analysis_quality_reason_code_invalid")
        if not _valid_entity(self.entity):
            raise QualityGateError("analysis_quality_reason_entity_invalid")
        if self.summary != self.code.replace("_", " "):
            raise QualityGateError("analysis_quality_reason_summary_invalid")


@dataclass(frozen=True)
class QualityGateRequest:
    route: QualityRoute
    subject_id: int
    start_local_date: str
    end_local_date: str
    as_of_utc: str
    plan_id: int | None = None
    reason_event_id: int | None = None

    def validated(self) -> tuple[tuple[str, ...], datetime]:
        if (
            self.route not in _ROUTES
            or not _positive(self.subject_id)
            or not isinstance(self.start_local_date, str)
            or not isinstance(self.end_local_date, str)
        ):
            raise QualityGateError("analysis_quality_request_invalid")
        try:
            start = date.fromisoformat(self.start_local_date)
            end = date.fromisoformat(self.end_local_date)
        except (TypeError, ValueError) as error:
            raise QualityGateError("analysis_quality_date_invalid") from error
        if (
            start.isoformat() != self.start_local_date
            or end.isoformat() != self.end_local_date
            or start > end
        ):
            raise QualityGateError("analysis_quality_date_invalid")
        as_of = _canonical_utc(self.as_of_utc, "analysis_quality_as_of_utc_invalid")
        dates = tuple(
            (start + timedelta(days=index)).isoformat()
            for index in range((end - start).days + 1)
        )
        if self.route == "daily_summary" and len(dates) != 1:
            raise QualityGateError("analysis_quality_daily_window_invalid")
        if self.route in {"weekly_summary", "weekly_plan"} and len(dates) != 7:
            raise QualityGateError("analysis_quality_weekly_window_invalid")
        if self.route == "revise_plan":
            if len(dates) != 1 or not _positive(self.plan_id) or not _positive(self.reason_event_id):
                raise QualityGateError("analysis_quality_revision_request_invalid")
        if self.route != "revise_plan" and (self.plan_id is not None or self.reason_event_id is not None):
            raise QualityGateError("analysis_quality_request_invalid")
        if self.route != "revise_plan" and end > as_of.astimezone(_HONG_KONG).date():
            raise QualityGateError("analysis_quality_window_after_as_of")
        return dates, as_of

    def dates(self) -> tuple[str, ...]:
        """Compatibility helper that still performs full request validation."""
        return self.validated()[0]


@dataclass(frozen=True)
class QualityGateResult:
    state: QualityGateState
    snapshot_sha256: str
    blockers: tuple[QualityGateReason, ...]
    warnings: tuple[QualityGateReason, ...]
    next_action: NextAction
    policy_version: str = QUALITY_GATE_POLICY_VERSION
    schema_version: str = QUALITY_GATE_RESULT_SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "state": self.state,
            "snapshot_sha256": self.snapshot_sha256,
            "blockers": [asdict(reason) for reason in self.blockers],
            "warnings": [asdict(reason) for reason in self.warnings],
            "next_action": self.next_action,
        }

    def validate(self) -> None:
        errors = sorted(
            _RESULT_VALIDATOR.iter_errors(self.as_dict()),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        if errors:
            location = ".".join(str(part) for part in errors[0].absolute_path) or "root"
            raise QualityGateError(f"analysis_quality_result_schema_invalid:{location}")


def _positive(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _valid_entity(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= _MAX_ENTITY_LENGTH
        and _SAFE_ENTITY.fullmatch(value) is not None
    )


def _reason(code: str, entity: str) -> QualityGateReason:
    if not _valid_entity(entity):
        entity = "invalid"
    return QualityGateReason(code, entity, code.replace("_", " "))


def _canonical_date(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return value if parsed.isoformat() == value else None


def _canonical_utc(value: object, code: str = "analysis_quality_timestamp_invalid") -> datetime:
    if not isinstance(value, str) or _UTC_PATTERN.fullmatch(value) is None:
        raise QualityGateError(code)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise QualityGateError(code) from error
    fraction = value[19:-1]
    is_shortest_fraction = (
        len(fraction) > 1
        and len(fraction) < 7
        and fraction[-1] != "0"
    )
    is_fixed_microsecond_fraction = len(fraction) == 7
    if (
        parsed.tzinfo != timezone.utc
        or (fraction and parsed.microsecond == 0)
        or (fraction and not (is_shortest_fraction or is_fixed_microsecond_fraction))
    ):
        raise QualityGateError(code)
    return parsed


def _timestamp(value: object) -> datetime:
    try:
        return _canonical_utc(value)
    except QualityGateError as error:
        raise _SnapshotMalformed("timestamp") from error


def _local_day(value: object) -> str:
    return _timestamp(value).astimezone(_HONG_KONG).date().isoformat()


def _snapshot_payload(snapshot: StableSnapshot) -> tuple[str, str]:
    if not isinstance(snapshot, StableSnapshot):
        raise _SnapshotMalformed("snapshot_type")
    collections = (
        snapshot.coverage,
        snapshot.cursors,
        snapshot.gaps,
        snapshot.activity_stages,
        snapshot.quality_issues,
        snapshot.facts,
        snapshot.capabilities,
        snapshot.plan_reasons,
        snapshot.audit,
    )
    if any(not isinstance(rows, tuple) for rows in collections):
        raise _SnapshotMalformed("snapshot_collection")
    if not isinstance(snapshot.views, dict):
        raise _SnapshotMalformed("snapshot_views")
    total_rows = sum(len(rows) for rows in collections)
    for name, rows in snapshot.views.items():
        if not isinstance(name, str) or not isinstance(rows, tuple):
            raise _SnapshotMalformed("snapshot_view")
        total_rows += len(rows)
        if not all(isinstance(row, dict) for row in rows):
            raise _SnapshotMalformed("snapshot_view_row")
    if total_rows > _MAX_SNAPSHOT_ROWS:
        raise _SnapshotMalformed("snapshot_rows")
    for rows in collections[:-1]:
        if not all(isinstance(row, dict) for row in rows):
            raise _SnapshotMalformed("snapshot_row")
    try:
        payload = json.dumps(
            asdict(snapshot),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise _SnapshotMalformed("snapshot_json") from error
    encoded = payload.encode("utf-8")
    if len(encoded) > _MAX_SNAPSHOT_BYTES:
        raise _SnapshotMalformed("snapshot_bytes")
    return payload, sha256(encoded).hexdigest()


def _bounded(
    blockers: list[QualityGateReason], warnings: list[QualityGateReason]
) -> tuple[tuple[QualityGateReason, ...], tuple[QualityGateReason, ...]]:
    blocker_set = sorted(set(blockers))
    warning_set = sorted(set(warnings))
    overflow = len(blocker_set) > _MAX_REASONS or len(warning_set) > _MAX_REASONS
    if overflow:
        limit_reason = _reason("gate_evidence_limit_exceeded", "gate")
        blocker_set = sorted(set(blocker_set[: _MAX_REASONS - 1] + [limit_reason]))
        warning_set = warning_set[:_MAX_REASONS]
    return tuple(blocker_set), tuple(warning_set)


def _result(
    state: QualityGateState,
    snapshot_hash: str,
    blockers: list[QualityGateReason],
    warnings: list[QualityGateReason],
    action: NextAction,
) -> QualityGateResult:
    bounded_blockers, bounded_warnings = _bounded(blockers, warnings)
    result = QualityGateResult(
        state=state,
        snapshot_sha256=snapshot_hash,
        blockers=bounded_blockers,
        warnings=bounded_warnings,
        next_action=action,
    )
    result.validate()
    return result


class QualityGate:
    """Pure gate: no database handle, provider, model, network, or mutation."""

    def evaluate(self, request: QualityGateRequest, snapshot: StableSnapshot) -> QualityGateResult:
        if not isinstance(request, QualityGateRequest):
            raise QualityGateError("analysis_quality_request_invalid")
        dates, as_of = request.validated()
        try:
            _, snapshot_hash = _snapshot_payload(snapshot)
        except _SnapshotMalformed:
            return _result(
                "blocked",
                _MALFORMED_HASH,
                [_reason("snapshot_malformed", "snapshot")],
                [],
                "repair_data",
            )

        blockers: list[QualityGateReason] = []
        warnings: list[QualityGateReason] = []
        try:
            self._subject(request, snapshot, blockers)
            capabilities = self._capabilities(snapshot, dates[-1], as_of, blockers)
            coverage = self._coverage(
                snapshot, dates, as_of, capabilities, blockers, warnings
            )
            self._sleep(snapshot, dates, coverage, blockers)
            self._gaps(snapshot, dates, blockers)
            self._activities(snapshot, dates, coverage, capabilities, blockers, warnings)
            self._quality(snapshot, dates, blockers, warnings)
            self._facts(snapshot, blockers)
            self._plans(request, snapshot, dates, as_of, blockers)
        except (AttributeError, KeyError, TypeError, ValueError, QualityGateError, _SnapshotMalformed):
            return _result(
                "blocked",
                snapshot_hash,
                [_reason("snapshot_malformed", "snapshot")],
                [],
                "repair_data",
            )

        bounded_blockers, _ = _bounded(blockers, warnings)
        if bounded_blockers:
            repair_codes = {
                "activity_inventory_proof_missing",
                "activity_stage_incomplete",
                "capability_conflict",
                "coverage_ambiguous",
                "coverage_state_unknown",
                "cursor_ambiguous",
                "cursor_catalog_unknown",
                "gap_open",
                "gate_evidence_limit_exceeded",
                "plan_incomplete",
                "plan_lineage_invalid",
                "plan_reason_invalid",
                "quality_error",
                "quality_state_unknown",
                "snapshot_malformed",
                "subject_identity_invalid",
            }
            action: NextAction = (
                "repair_data"
                if any(reason.code in repair_codes for reason in bounded_blockers)
                else "rerun_collection"
            )
            return _result("blocked", snapshot_hash, blockers, warnings, action)
        return _result(
            "ready_with_warnings" if warnings else "ready",
            snapshot_hash,
            [],
            warnings,
            "none",
        )

    @staticmethod
    def _subject(
        request: QualityGateRequest,
        snapshot: StableSnapshot,
        blockers: list[QualityGateReason],
    ) -> None:
        context = snapshot.subject_context
        if (
            not isinstance(context, StableSubjectContext)
            or context.subject_id != request.subject_id
            or context.timezone != "Asia/Hong_Kong"
            or context.provider != "garmin"
            or context.identity_kind != "account"
            or context.verified is not True
        ):
            blockers.append(_reason("subject_identity_invalid", "subject"))
        row_groups = [
            *snapshot.views.values(),
            snapshot.coverage,
            snapshot.cursors,
            snapshot.gaps,
            snapshot.activity_stages,
            snapshot.quality_issues,
            snapshot.facts,
            snapshot.capabilities,
            snapshot.plan_reasons,
        ]
        for rows in row_groups:
            for row in rows:
                if "subject_id" in row and row["subject_id"] != request.subject_id:
                    blockers.append(_reason("subject_identity_invalid", "row"))
                    return

    @staticmethod
    def _capabilities(
        snapshot: StableSnapshot,
        through: str,
        as_of: datetime,
        blockers: list[QualityGateReason],
    ) -> dict[str, str]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        environments: set[str] = set()
        through_date = date.fromisoformat(through)
        as_of_date = as_of.astimezone(_HONG_KONG).date()
        for row in snapshot.capabilities:
            kind = row.get("resource_kind")
            if kind not in _RESOURCES:
                continue
            grouped.setdefault(str(kind), []).append(row)
        result: dict[str, str] = {}
        for kind in sorted(_RESOURCES):
            rows = grouped.get(kind, [])
            if not rows:
                blockers.append(_reason("capability_missing", kind))
                continue
            if len(rows) != 1:
                blockers.append(_reason("capability_conflict", kind))
                continue
            row = rows[0]
            state = row.get("capability_state")
            environment = row.get("environment_key")
            if (
                not isinstance(environment, str)
                or not _valid_entity(environment)
                or state not in _CAPABILITY_STATES
            ):
                blockers.append(_reason("capability_conflict", kind))
                continue
            try:
                checked_date = date.fromisoformat(_local_day(row.get("last_checked_at_utc")))
                probe = row.get("next_probe_at_utc")
                probe_date = date.fromisoformat(_local_day(probe)) if probe is not None else None
            except (ValueError, _SnapshotMalformed):
                blockers.append(_reason("capability_conflict", kind))
                continue
            if (
                checked_date < through_date
                or checked_date > as_of_date
                or (probe_date is not None and probe_date < as_of_date)
            ):
                blockers.append(_reason("capability_expired", kind))
                continue
            environments.add(environment)
            result[kind] = str(state)
        if len(environments) > 1:
            blockers.append(_reason("capability_conflict", "environment"))
        return result

    @staticmethod
    def _coverage(
        snapshot: StableSnapshot,
        dates: tuple[str, ...],
        as_of: datetime,
        capabilities: dict[str, str],
        blockers: list[QualityGateReason],
        warnings: list[QualityGateReason],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        indexed: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in snapshot.coverage:
            kind = row.get("resource_kind")
            day = row.get("local_date")
            if kind not in _RESOURCES or day not in dates:
                continue
            indexed.setdefault((str(kind), str(day)), []).append(row)

        selected: dict[tuple[str, str], dict[str, Any]] = {}
        for kind in sorted(_RESOURCES):
            capability = capabilities.get(kind)
            required = kind in _REQUIRED
            if capability is None:
                continue
            if required and capability != "supported":
                blockers.append(_reason("capability_required_unavailable", kind))
            if not required and capability in {"forbidden", "unknown"}:
                blockers.append(_reason("capability_required_unavailable", kind))
            for day in dates:
                entity = f"{kind}:{day}"
                rows = indexed.get((kind, day), [])
                if not rows:
                    blockers.append(_reason("coverage_missing", entity))
                    continue
                candidates: list[
                    tuple[datetime, tuple[str, str, str, int, str]]
                ] = []
                for row in rows:
                    state = row.get("availability_state")
                    record_count = row.get("record_count")
                    observed_at = row.get("observed_at_utc")
                    try:
                        observed = _timestamp(observed_at)
                    except _SnapshotMalformed:
                        blockers.append(_reason("coverage_state_unknown", entity))
                        continue
                    # A caller's as-of boundary is authoritative. A later
                    # persisted observation belongs to a future gate, not this
                    # snapshot decision. Once its timestamp is known, none of
                    # its other fields may affect the current as-of result.
                    if observed > as_of:
                        continue
                    if (
                        state not in _COVERAGE_STATES
                        or not isinstance(record_count, int)
                        or isinstance(record_count, bool)
                        or record_count < 0
                        or (state == "fetched" and record_count == 0)
                        or (state in _OPTIONAL | {"empty"} and record_count != 0)
                        or _canonical_date(day) is None
                        or observed.astimezone(_HONG_KONG).date()
                        < date.fromisoformat(day)
                    ):
                        blockers.append(_reason("coverage_state_unknown", entity))
                        continue
                    candidates.append(
                        (
                            observed,
                            (kind, day, str(state), record_count, str(observed_at)),
                        )
                    )
                if not candidates:
                    blockers.append(_reason("coverage_missing", entity))
                    continue
                latest_at = max(item[0] for item in candidates)
                latest = [item[1] for item in candidates if item[0] == latest_at]
                latest_semantics = set(latest)
                if len(latest_semantics) != 1:
                    blockers.append(_reason("coverage_ambiguous", entity))
                    continue
                resource_kind, local_date, state, record_count, observed_at = next(
                    iter(latest_semantics)
                )
                row = {
                    "resource_kind": resource_kind,
                    "local_date": local_date,
                    "availability_state": state,
                    "record_count": record_count,
                    "observed_at_utc": observed_at,
                }
                selected[(kind, day)] = row
                if capability == "supported":
                    if state == "partial":
                        blockers.append(_reason("coverage_partial", entity))
                    elif state in {"error", "forbidden"}:
                        blockers.append(_reason("coverage_error", entity))
                    elif state in _OPTIONAL:
                        blockers.append(_reason("capability_conflict", entity))
                    elif state not in _CLOSED:
                        blockers.append(_reason("coverage_state_unknown", entity))
                elif capability in _OPTIONAL:
                    if state != capability:
                        blockers.append(_reason("capability_conflict", entity))
                elif state not in _CLOSED:
                    blockers.append(_reason("coverage_error", entity))
            if not required and capability in _OPTIONAL:
                warnings.append(_reason("coverage_optional", kind))

            cursor_required = _REQUIRED.get(kind, _CONDITIONAL.get(kind, False))
            if capability == "supported" and cursor_required:
                cursor_rows = [
                    row for row in snapshot.cursors if row.get("resource_kind") == kind
                ]
                if not cursor_rows:
                    blockers.append(_reason("cursor_missing", kind))
                elif len(cursor_rows) != 1:
                    blockers.append(_reason("cursor_ambiguous", kind))
                else:
                    cursor = cursor_rows[0]
                    complete = _canonical_date(cursor.get("complete_through_local_date"))
                    if (
                        cursor.get("cursor_grain") != "local_date"
                        or cursor.get("catalog_version") != _CATALOG_VERSION
                    ):
                        blockers.append(_reason("cursor_catalog_unknown", kind))
                    elif complete is None or complete < dates[-1]:
                        blockers.append(_reason("cursor_hole", kind))
        return selected

    @staticmethod
    def _sleep(
        snapshot: StableSnapshot,
        dates: tuple[str, ...],
        coverage: dict[tuple[str, str], dict[str, Any]],
        blockers: list[QualityGateReason],
    ) -> None:
        sessions = snapshot.views.get("v_current_sleep_sessions")
        if not isinstance(sessions, tuple):
            raise _SnapshotMalformed("sleep_view")
        main_sleep_dates: set[str] = set()
        for row in sessions:
            if row.get("session_type") != "main_sleep":
                continue
            start = _timestamp(row.get("start_time_utc"))
            end = _timestamp(row.get("end_time_utc"))
            if end <= start:
                raise _SnapshotMalformed("sleep_window")
            main_sleep_dates.add(end.astimezone(_HONG_KONG).date().isoformat())
        for day in dates:
            row = coverage.get(("sleep", day))
            if row is not None and row.get("availability_state") == "fetched":
                # Garmin keys the fetched sleep resource by the evening's
                # local date, while the main session can end the following
                # morning.  Accept either boundary without accepting a sleep
                # session from a later day.
                next_day = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
                if day not in main_sleep_dates and next_day not in main_sleep_dates:
                    blockers.append(_reason("sleep_evidence_missing", day))

    @staticmethod
    def _gaps(
        snapshot: StableSnapshot,
        dates: tuple[str, ...],
        blockers: list[QualityGateReason],
    ) -> None:
        for row in snapshot.gaps:
            start = _canonical_date(row.get("window_start_local_date"))
            end = _canonical_date(row.get("window_end_local_date"))
            status = row.get("status")
            if start is None or end is None or start > end:
                blockers.append(_reason("gap_state_unknown", "gap"))
                continue
            if end < dates[0] or start > dates[-1]:
                continue
            kind = row.get("resource_kind")
            entity = f"{kind if kind in _RESOURCES else 'unknown'}:{start}:{end}"
            if status == "open":
                blockers.append(_reason("gap_open", entity))
            elif status == "deferred":
                blockers.append(_reason("gap_deferred", entity))
            elif status not in {"resolved", "ignored_with_reason"}:
                blockers.append(_reason("gap_state_unknown", entity))

    @staticmethod
    def _activities(
        snapshot: StableSnapshot,
        dates: tuple[str, ...],
        coverage: dict[tuple[str, str], dict[str, Any]],
        capabilities: dict[str, str],
        blockers: list[QualityGateReason],
        warnings: list[QualityGateReason],
    ) -> None:
        if capabilities.get("activity_inventory") != "supported":
            blockers.append(_reason("activity_inventory_incomplete", "activity_inventory"))
            return
        activities = [row for row in snapshot.activity_stages if row.get("local_date") in dates]
        if not activities:
            warnings.append(_reason("activity_absent_unconfirmed", f"{dates[0]}:{dates[-1]}"))
            return
        activity_counts = {
            day: sum(1 for row in activities if row.get("local_date") == day)
            for day in dates
        }
        for row in activities:
            activity_id = row.get("id")
            local_date = row.get("local_date")
            entity = f"activity:{activity_id if _positive(activity_id) else 'invalid'}:{local_date}"
            inventory = coverage.get(("activity_inventory", str(local_date)))
            inventory_matches = (
                inventory is not None
                and inventory.get("availability_state") == "fetched"
                and isinstance(inventory.get("record_count"), int)
                and not isinstance(inventory.get("record_count"), bool)
                and inventory["record_count"] >= activity_counts.get(str(local_date), 0)
                and row.get("inventory_coverage_state") == inventory.get("availability_state")
                and row.get("inventory_coverage_observed_at_utc")
                == inventory.get("observed_at_utc")
            )
            if not inventory_matches:
                blockers.append(_reason("activity_inventory_proof_missing", entity))
            ready_values = (
                row.get("summary_ready"),
                row.get("fit_core_ready"),
                row.get("fallback_ready"),
            )
            if (
                not _positive(activity_id)
                or _canonical_date(local_date) is None
                or row.get("provider_state") != "active"
                or any(value not in {0, 1} or isinstance(value, bool) for value in ready_values)
                or row.get("summary_ready") != 1
                or (
                    row.get("fit_core_ready") != 1
                    and row.get("fallback_ready") != 1
                )
            ):
                blockers.append(_reason("activity_stage_incomplete", entity))

    @staticmethod
    def _quality(
        snapshot: StableSnapshot,
        dates: tuple[str, ...],
        blockers: list[QualityGateReason],
        warnings: list[QualityGateReason],
    ) -> None:
        for row in snapshot.quality_issues:
            # Stable snapshots intentionally carry a wider history for trend
            # analysis.  A route must only be warned/blocked by an issue that
            # affects its requested review dates, not by an unrelated older
            # activity retained in that history window.
            local_date = row.get("local_date")
            if local_date is not None and local_date not in dates:
                continue
            entity_type = row.get("entity_type")
            entity_id = row.get("entity_id")
            severity = row.get("severity")
            status = row.get("status")
            if (
                not isinstance(entity_type, str)
                or not _valid_entity(entity_type)
                or not _positive(entity_id)
                or severity not in {"info", "warning", "error"}
                or status not in _ACTIVE_ISSUE_STATES | _INACTIVE_ISSUE_STATES
            ):
                blockers.append(_reason("quality_state_unknown", "quality"))
                continue
            if status in _INACTIVE_ISSUE_STATES:
                continue
            entity = f"{entity_type}:{entity_id}"
            if severity == "error":
                blockers.append(_reason("quality_error", entity))
            elif severity == "warning":
                warnings.append(_reason("quality_warning", entity))

    @staticmethod
    def _facts(
        snapshot: StableSnapshot,
        blockers: list[QualityGateReason],
    ) -> None:
        for row in snapshot.facts:
            if (
                not _positive(row.get("id"))
                or not isinstance(row.get("fact_key"), str)
                or not row["fact_key"]
                or not isinstance(row.get("scope"), str)
                or not row["scope"]
            ):
                blockers.append(_reason("facts_malformed", "facts"))

    @staticmethod
    def _plans(
        request: QualityGateRequest,
        snapshot: StableSnapshot,
        dates: tuple[str, ...],
        as_of: datetime,
        blockers: list[QualityGateReason],
    ) -> None:
        plans = snapshot.views.get("v_current_training_plans")
        items = snapshot.views.get("v_training_plan_items")
        artifacts = snapshot.views.get("v_current_analysis_artifacts")
        if not isinstance(plans, tuple) or not isinstance(items, tuple) or not isinstance(artifacts, tuple):
            raise _SnapshotMalformed("plan_views")

        relevant_plans = [
            plan
            for plan in plans
            if request.route == "revise_plan"
            and plan.get("id") == request.plan_id
            or request.route != "revise_plan"
            and _canonical_date(plan.get("plan_start_local_date")) is not None
            and _canonical_date(plan.get("plan_end_local_date")) is not None
            and str(plan["plan_end_local_date"]) >= dates[0]
            and str(plan["plan_start_local_date"]) <= dates[-1]
        ]
        if request.route == "revise_plan" and len(relevant_plans) != 1:
            blockers.append(_reason("plan_incomplete", f"plan:{request.plan_id}"))
        for plan in relevant_plans:
            plan_id = plan.get("id")
            start = _canonical_date(plan.get("plan_start_local_date"))
            end = _canonical_date(plan.get("plan_end_local_date"))
            artifact_id = plan.get("analysis_artifact_id")
            try:
                plan_created_at = _timestamp(plan.get("created_at_utc"))
            except _SnapshotMalformed:
                plan_created_at = as_of + timedelta(seconds=1)
            if (
                frozenset(plan) != _PLAN_FIELDS
                or not _positive(plan_id)
                or plan.get("subject_id") != request.subject_id
                or not _positive(artifact_id)
                or start is None
                or end is None
                or (date.fromisoformat(end) - date.fromisoformat(start)).days != 6
                or plan.get("timezone") != "Asia/Hong_Kong"
                or plan.get("status") not in {"proposed", "active"}
                or not isinstance(plan.get("objective_json"), str)
                or not isinstance(plan.get("constraints_json"), str)
                or plan_created_at > as_of
            ):
                blockers.append(_reason("plan_incomplete", f"plan:{plan_id}"))
                continue
            matching_artifacts = [row for row in artifacts if row.get("id") == artifact_id]
            if len(matching_artifacts) != 1:
                blockers.append(_reason("plan_lineage_invalid", f"plan:{plan_id}"))
            else:
                artifact = matching_artifacts[0]
                try:
                    created_at = _timestamp(artifact.get("created_at_utc"))
                except _SnapshotMalformed:
                    created_at = as_of + timedelta(seconds=1)
                if (
                    frozenset(artifact) != _ARTIFACT_FIELDS
                    or artifact.get("subject_id") != request.subject_id
                    or artifact.get("artifact_kind") != "weekly_training_plan"
                    or artifact.get("period_start_local_date") != start
                    or artifact.get("period_end_local_date") != end
                    or not _positive(artifact.get("revision_no"))
                    or not isinstance(artifact.get("schema_version"), str)
                    or not artifact["schema_version"]
                    or not isinstance(artifact.get("content_sha256"), str)
                    or _SHA256_PATTERN.fullmatch(artifact["content_sha256"]) is None
                    or created_at > as_of
                ):
                    blockers.append(_reason("plan_lineage_invalid", f"plan:{plan_id}"))
            expected_dates = tuple(day for day in dates if start <= day <= end)
            plan_items = [row for row in items if row.get("training_plan_id") == plan_id]
            indices: set[int] = set()
            for day in expected_dates:
                day_items = [row for row in plan_items if row.get("local_date") == day]
                if len(day_items) != 1:
                    blockers.append(_reason("plan_incomplete", f"plan:{plan_id}:{day}"))
                    continue
                item = day_items[0]
                index = item.get("item_index")
                if (
                    frozenset(item) != _PLAN_ITEM_FIELDS
                    or not _positive(item.get("id"))
                    or item.get("subject_id") != request.subject_id
                    or not isinstance(index, int)
                    or isinstance(index, bool)
                    or index < 0
                    or index in indices
                    or item.get("activity_kind") not in _PLAN_KINDS
                    or not isinstance(item.get("prescription_json"), str)
                    or not (
                        item.get("rationale_text") is None
                        or isinstance(item.get("rationale_text"), str)
                    )
                ):
                    blockers.append(_reason("plan_incomplete", f"plan:{plan_id}:{day}"))
                else:
                    indices.add(index)

        if request.route == "revise_plan":
            reasons = [
                row for row in snapshot.plan_reasons if row.get("id") == request.reason_event_id
            ]
            if len(reasons) != 1:
                blockers.append(_reason("plan_reason_invalid", f"reason:{request.reason_event_id}"))
                return
            reason = reasons[0]
            try:
                occurred_at = _timestamp(reason.get("occurred_at_utc"))
            except _SnapshotMalformed:
                occurred_at = as_of + timedelta(seconds=1)
            created_by = reason.get("created_by")
            reason_fields = frozenset(reason)
            if (
                reason_fields != _REASON_DTO_FIELDS
                or reason.get("subject_id") != request.subject_id
                or reason.get("event_type") != "plan_revision_reason_recorded"
                or reason.get("actor_role") != "trainlab"
                or reason.get("trust_level") != "system_generated"
                or reason.get("created_by") != "mail_agent"
                or reason.get("current_plan_id") != request.plan_id
                or reason.get("effective_local_date") != dates[0]
                or not isinstance(reason.get("source_mail_message_id"), int)
                or not isinstance(reason.get("source_mail_thread_id"), int)
                or not isinstance(reason.get("source_revision_id"), int)
                or reason.get("change_kind") not in {"move", "cancel", "replace", "availability", "injury", "preference"}
                or not isinstance(reason.get("affected_local_dates"), list)
                or not isinstance(reason.get("constraints"), (dict, list, str, int, float, bool, type(None)))
                or not isinstance(created_by, str)
                or not _valid_entity(created_by)
                or occurred_at > as_of
            ):
                blockers.append(_reason("plan_reason_invalid", f"reason:{request.reason_event_id}"))
