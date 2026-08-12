"""A3-06 bounded, read-only access to Foundation's analysis projections."""

from __future__ import annotations

import sqlite3
import re
import math
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


class StableViewError(RuntimeError):
    """Controlled read-boundary or compatible-schema failure."""


_VIEW_ALLOWLIST = frozenset({
    "v_current_daily_health", "v_current_physiology_records", "v_current_physiology_metrics",
    "v_current_sleep_sessions", "v_current_activities", "v_activity_segments",
    "v_activity_metric_sources", "v_active_user_facts", "v_current_analysis_artifacts",
    "v_current_weekly_summaries", "v_current_training_plans", "v_training_plan_items",
    "v_analysis_history_context", "v_open_data_quality_issues",
})
_DENIED_PROJECTION_COLUMNS = frozenset({
    "extras_json", "source_map_json", "raw_value_json", "payload_json",
    "body_text", "identity_hmac", "provider_account_id", "display_name",
    "latitude", "longitude", "token", "access_token", "refresh_token",
    "password", "credential", "authorization", "mime", "attachment",
})
_MAX_SAMPLE_LIMIT = 100
_MAX_PUBLIC_VIEW_ROWS = 500
_MAX_VIEW_ROWS = 2_000
# Analysis reads one fixed 30-completed-day boundary. Stable reads retain
# detailed records for deterministic quality checks and future explicitly
# requested drill-down, while the default context builder emits only aggregate
# health/sleep/physiology and activity-level summaries.
_MAX_AUX_ROWS = 4_000
_MAX_READ_ROWS = 4_000
_MAX_SNAPSHOT_ROWS = 8_000
_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("v_current_daily_health", "SELECT id,subject_id,local_date,values_json,source_revision_id FROM v_current_daily_health WHERE subject_id=? AND local_date BETWEEN ? AND ? ORDER BY local_date,id", ("subject", "date", "date")),
    ("v_current_physiology_records", "SELECT id,subject_id,domain,record_type,effective_at_utc,period_start_utc,period_end_utc,local_date,value_origin,status_key,status_text,source_revision_id FROM v_current_physiology_records WHERE subject_id=? AND COALESCE(local_date,substr(effective_at_utc,1,10)) BETWEEN ? AND ? ORDER BY COALESCE(local_date,substr(effective_at_utc,1,10)),id", ("subject", "date", "date")),
    ("v_current_physiology_metrics", "SELECT m.id,r.subject_id,r.domain,r.record_type,r.effective_at_utc,m.physiology_record_id,m.metric_key,m.value_number,m.value_text,m.value_boolean,m.value_json,m.raw_unit,m.canonical_unit,m.value_origin FROM v_current_physiology_metrics m JOIN physiology_records r ON r.id=m.physiology_record_id WHERE r.subject_id=? AND COALESCE(r.local_date,substr(r.effective_at_utc,1,10)) BETWEEN ? AND ? ORDER BY COALESCE(r.local_date,substr(r.effective_at_utc,1,10)),m.metric_key,m.id", ("subject", "date", "date")),
    ("v_current_sleep_sessions", "SELECT id,subject_id,session_type,start_time_utc,end_time_utc,values_json,source_revision_id FROM v_current_sleep_sessions WHERE subject_id=? AND start_time_utc<? AND end_time_utc>? ORDER BY start_time_utc,id", ("subject", "end_utc", "start_utc")),
    ("v_current_activities", """SELECT a.id,a.subject_id,a.provider_activity_id,a.name,a.sport,a.sub_sport,a.start_time_utc,a.end_time_utc,a.local_date,a.elapsed_seconds,a.timer_seconds,a.distance_m,a.primary_revision_id,a.provider_state,
        (SELECT ar.source_revision_id FROM activity_source_revisions ar JOIN source_revisions sr ON sr.id=ar.source_revision_id WHERE ar.activity_id=a.id AND ar.source_role='activity_fit' AND ar.is_active=1 AND sr.is_current=1 AND sr.parsed_at_utc IS NOT NULL LIMIT 1) AS active_fit_revision_id,
        (SELECT ar.source_revision_id FROM activity_source_revisions ar JOIN source_revisions sr ON sr.id=ar.source_revision_id WHERE ar.activity_id=a.id AND ar.source_role='weather_json' AND ar.is_active=1 AND sr.is_current=1 AND sr.parsed_at_utc IS NOT NULL LIMIT 1) AS active_weather_revision_id,
        json_extract(a.extras_json,'$.fit_session.fields.avg_heart_rate.value') AS fit_avg_heart_rate_bpm,
        json_extract(a.extras_json,'$.fit_session.fields.max_heart_rate.value') AS fit_max_heart_rate_bpm,
        CASE WHEN lower(a.sport) IN ('running','run','trail_running','treadmill_running') THEN 2.0 * (COALESCE(json_extract(a.extras_json,'$.fit_session.fields.avg_running_cadence.value'),0) + COALESCE(json_extract(a.extras_json,'$.fit_session.fields.avg_fractional_cadence.value'),0)) END AS fit_avg_running_cadence_spm,
        json_extract(a.extras_json,'$.fit_session.fields.enhanced_avg_speed.value') AS fit_avg_speed_mps,
        json_extract(a.extras_json,'$.fit_session.fields.avg_power.value') AS fit_avg_power_w,
        json_extract(a.extras_json,'$.fit_session.fields.avg_temperature.value') AS fit_avg_temperature_c,
        json_extract(a.extras_json,'$.fit_session.fields.total_ascent.value') AS fit_total_ascent_m,
        COALESCE(json_extract(a.extras_json,'$.connect_enrichments.weather_json.reviewed.temperature'),json_extract(a.extras_json,'$.connect_enrichments.weather_json.reviewed.temp')) AS weather_temperature_provider_value,
        json_extract(a.extras_json,'$.connect_enrichments.weather_json.reviewed.relativeHumidity') AS weather_relative_humidity_percent,
        COALESCE(json_extract(a.extras_json,'$.connect_enrichments.weather_json.reviewed.weatherTypeDTO.desc'),json_extract(a.extras_json,'$.connect_enrichments.weather_json.reviewed.weatherType')) AS weather_condition,
        json_extract(a.extras_json,'$.connect_enrichments.weather_json.reviewed.windSpeed') AS weather_wind_speed_provider_value,
        COALESCE(json_extract(a.extras_json,'$.connect_enrichments.weather_json.reviewed.issueDate'),json_extract(a.extras_json,'$.connect_enrichments.weather_json.reviewed.observationTime')) AS weather_observed_at
      FROM v_current_activities a WHERE a.subject_id=? AND a.local_date BETWEEN ? AND ? ORDER BY a.local_date,a.start_time_utc,a.id""", ("subject", "date", "date")),
    ("v_activity_segments", "SELECT s.id,a.subject_id,s.activity_id,s.segment_type,s.segment_index,s.start_time_utc,s.end_time_utc,s.duration_seconds,s.distance_m,s.source_revision_id FROM v_activity_segments s JOIN activities a ON a.id=s.activity_id WHERE a.subject_id=? AND a.local_date BETWEEN ? AND ? ORDER BY a.local_date,s.activity_id,s.segment_index,s.id", ("subject", "date", "date")),
    ("v_activity_metric_sources", "SELECT m.id,a.subject_id,m.activity_id,m.metric_key,m.valid_from_utc,m.valid_to_utc,m.source_kind,m.device_id,m.developer_data_index,m.attribution_method,m.confidence FROM v_activity_metric_sources m JOIN activities a ON a.id=m.activity_id WHERE a.subject_id=? AND a.local_date BETWEEN ? AND ? ORDER BY a.local_date,m.activity_id,m.metric_key,m.id", ("subject", "date", "date")),
    ("v_active_user_facts", "SELECT id,subject_id,fact_key,fact_value_json,scope,effective_from_utc,expires_at_utc,confidence FROM v_active_user_facts WHERE subject_id=? ORDER BY fact_key,id", ("subject",)),
    ("v_current_analysis_artifacts", "SELECT id,subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no,schema_version,content_sha256,created_at_utc FROM v_current_analysis_artifacts WHERE subject_id=? AND period_end_local_date>=? AND period_start_local_date<=? ORDER BY period_start_local_date,artifact_kind,revision_no,id", ("subject", "date", "date")),
    ("v_current_weekly_summaries", "SELECT id,subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no,schema_version,content_sha256,created_at_utc FROM v_current_weekly_summaries WHERE subject_id=? AND period_end_local_date>=? AND period_start_local_date<=? ORDER BY period_start_local_date,revision_no,id", ("subject", "date", "date")),
    ("v_current_training_plans", "SELECT id,subject_id,analysis_artifact_id,plan_start_local_date,plan_end_local_date,timezone,status,objective_json,constraints_json,created_at_utc FROM v_current_training_plans WHERE subject_id=? AND plan_end_local_date>=? AND plan_start_local_date<=? ORDER BY plan_start_local_date,id", ("subject", "date", "date")),
    ("v_training_plan_items", "SELECT i.id,p.subject_id,i.training_plan_id,i.item_index,i.local_date,i.activity_kind,i.prescription_json,i.rationale_text FROM v_training_plan_items i JOIN v_current_training_plans p ON p.id=i.training_plan_id WHERE p.subject_id=? AND i.local_date BETWEEN ? AND ? ORDER BY i.local_date,i.item_index,i.id", ("subject", "date", "date")),
    ("v_analysis_history_context", "SELECT id,subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no,schema_version,content_sha256,is_current,created_at_utc,trust_class FROM v_analysis_history_context WHERE subject_id=? AND period_end_local_date>=? AND period_start_local_date<=? ORDER BY period_start_local_date,artifact_kind,revision_no,id", ("subject", "date", "date")),
)

_SNAPSHOT_ACTIVITY_SEGMENTS_SQL = """
SELECT s.id,a.subject_id,s.activity_id,s.segment_type,s.segment_index,
       s.start_time_utc,s.end_time_utc,s.duration_seconds,s.distance_m,
       s.source_revision_id
FROM v_activity_segments s
JOIN activities a ON a.id=s.activity_id
WHERE a.subject_id=? AND a.local_date BETWEEN ? AND ?
  AND EXISTS (
      SELECT 1
      FROM v_training_plan_items i
      JOIN v_current_training_plans p ON p.id=i.training_plan_id
      WHERE p.subject_id=a.subject_id AND i.local_date=a.local_date
  )
ORDER BY a.local_date,s.activity_id,s.segment_index,s.id
"""


@dataclass(frozen=True)
class QueryAudit:
    operation: str
    subject_id: int
    start_local_date: str | None
    end_local_date: str | None
    row_count: int


@dataclass(frozen=True)
class StableSubjectContext:
    """Safe, immutable identity evidence for a snapshot subject."""
    subject_id: int
    timezone: str
    provider: str
    identity_kind: str
    verified: bool


@dataclass(frozen=True)
class StableSnapshot:
    views: dict[str, tuple[dict[str, Any], ...]]
    coverage: tuple[dict[str, Any], ...]
    cursors: tuple[dict[str, Any], ...]
    gaps: tuple[dict[str, Any], ...]
    activity_stages: tuple[dict[str, Any], ...]
    quality_issues: tuple[dict[str, Any], ...]
    facts: tuple[dict[str, Any], ...]
    capabilities: tuple[dict[str, Any], ...]
    plan_reasons: tuple[dict[str, Any], ...]
    audit: tuple[QueryAudit, ...]
    subject_context: StableSubjectContext | None = None


def _safe_row(row: sqlite3.Row) -> dict[str, Any]:
    # Every SQL shape is fixed and must already be an intentional public
    # projection.  Reject a sensitive column rather than silently changing a
    # result shape (or accidentally filtering the safe `fit_core_ready`).
    if any(key.lower() in _DENIED_PROJECTION_COLUMNS for key in row.keys()):
        raise StableViewError("analysis_snapshot_projection_forbidden")
    return {key: row[key] for key in row.keys()}


def _date(value: str) -> str:
    try: return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError) as error: raise StableViewError("analysis_snapshot_date_invalid") from error


_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.(?!000000Z)\d{6})?Z$")


def _utc(value: str) -> tuple[str, datetime]:
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        raise StableViewError("analysis_snapshot_utc_invalid")
    fmt = "%Y-%m-%dT%H:%M:%S.%fZ" if "." in value else "%Y-%m-%dT%H:%M:%SZ"
    try: parsed = datetime.strptime(value, fmt)
    except ValueError as error: raise StableViewError("analysis_snapshot_utc_invalid") from error
    return value, parsed


_REASON_PAYLOAD_FIELDS = frozenset({
    "schema_version", "policy_version", "subject_id", "run_key",
    "source_mail_message_id", "source_mail_thread_id", "source_revision_id",
    "value_origin", "content_instruction_trust", "change_kind",
    "affected_local_dates", "constraints", "effective_local_date",
    "current_plan_id", "evidence_text_span",
})
_REASON_CHANGE_KINDS = frozenset({"move", "cancel", "replace", "availability", "injury", "preference"})


def _reason_payload(row: dict[str, Any], subject_id: int) -> dict[str, Any]:
    """Return the small, verified reason-event DTO; never retain mail evidence."""
    try:
        payload = json.loads(row.pop("reason_payload"))
    except (TypeError, json.JSONDecodeError) as error:
        raise StableViewError("analysis_plan_reason_payload_invalid") from error
    if not isinstance(payload, dict) or frozenset(payload) != _REASON_PAYLOAD_FIELDS:
        raise StableViewError("analysis_plan_reason_payload_invalid")
    if (
        payload.get("schema_version") != "1"
        or payload.get("subject_id") != subject_id
        or payload.get("value_origin") != "user_asserted"
        or payload.get("content_instruction_trust") != "untrusted_content"
        or payload.get("change_kind") not in _REASON_CHANGE_KINDS
        or not isinstance(payload.get("policy_version"), str)
        or not payload["policy_version"]
        or not isinstance(payload.get("run_key"), str)
        or not payload["run_key"]
        or not isinstance(payload.get("constraints"), (dict, list, str, int, float, bool, type(None)))
        or not isinstance(payload.get("affected_local_dates"), list)
        or not 1 <= len(payload["affected_local_dates"]) <= 31
        or len(set(payload["affected_local_dates"])) != len(payload["affected_local_dates"])
        or any(_date(value) != value for value in payload["affected_local_dates"])
        or _date(payload.get("effective_local_date")) != payload.get("effective_local_date")
        or payload.get("current_plan_id") is None
        or isinstance(payload.get("current_plan_id"), bool)
        or not isinstance(payload.get("current_plan_id"), int)
        or payload["current_plan_id"] <= 0
    ):
        raise StableViewError("analysis_plan_reason_payload_invalid")
    for key in ("source_mail_message_id", "source_mail_thread_id", "source_revision_id"):
        if isinstance(payload.get(key), bool) or not isinstance(payload.get(key), int) or payload[key] <= 0:
            raise StableViewError("analysis_plan_reason_payload_invalid")
    if (
        row.get("subject_id") != subject_id
        or row.get("thread_subject_id") != subject_id
        or row.get("mail_actor_role") != "user"
        or row.get("direction") != "inbound"
        or row.get("processing_state") != "awaiting_analysis"
        or row.get("thread_is_current") != 1
        or row.get("source_is_current") != 1
        or payload["source_mail_message_id"] != row.get("mail_message_id")
        or payload["source_mail_thread_id"] != row.get("mail_thread_id")
        or payload["source_revision_id"] != row.get("source_revision_id")
    ):
        raise StableViewError("analysis_plan_reason_lineage_invalid")
    return {
        "id": row["id"], "subject_id": subject_id,
        "event_type": row["event_type"], "actor_role": row["actor_role"],
        "occurred_at_utc": row["occurred_at_utc"], "trust_level": row["trust_level"],
        "created_by": row["created_by"], "source_mail_message_id": row["mail_message_id"],
        "source_mail_thread_id": row["mail_thread_id"], "source_revision_id": row["source_revision_id"],
        "change_kind": payload["change_kind"], "affected_local_dates": payload["affected_local_dates"],
        "constraints": payload["constraints"], "effective_local_date": payload["effective_local_date"],
        "current_plan_id": payload["current_plan_id"],
    }


class StableViewRepository:
    """No-SQL-input repository with fixed SELECT shapes and short read txns."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._audit: list[QueryAudit] = []
        self._snapshot_read_active = False

    def _execute(self, sql: str, params: tuple[object, ...] = ()) -> sqlite3.Cursor:
        """Single seam for fixed SQL and deterministic transaction fault tests."""
        return self._conn.execute(sql, params)

    def _set_row_factory(self, value: object) -> None:
        """Test seam for caller-owned connection state."""
        self._conn.row_factory = value  # type: ignore[assignment]

    def _snapshot_after_subject_context(self) -> None:
        """Test seam: production intentionally has no work at this boundary."""

    def _restore_snapshot_state(
        self,
        prior_factory: object,
        prior_query_only: int | None,
        *,
        rollback: bool,
    ) -> None:
        """Restore every caller-owned connection setting or fail closed.

        A restore failure cannot be hidden: a caller must know that its SQLite
        connection may no longer be in the state it supplied.
        """
        restore_error: Exception | None = None
        if rollback and self._conn.in_transaction:
            try:
                self._execute("ROLLBACK")
            except Exception as error:  # pragma: no cover - exercised by injected seam
                restore_error = error
                # A test seam or adapter may fail before it reaches SQLite.  A
                # direct fallback gives the caller its transaction boundary
                # back, while the controlled error still reports the failed
                # primary restoration path.
                try:
                    self._conn.rollback()
                except Exception:
                    pass
        try:
            self._set_row_factory(prior_factory)
        except Exception as error:  # pragma: no cover - sqlite permits assignment
            restore_error = restore_error or error
        if prior_query_only is not None:
            try:
                self._execute(f"PRAGMA query_only={prior_query_only}")
            except Exception as error:
                restore_error = restore_error or error
                try:
                    self._conn.execute(f"PRAGMA query_only={prior_query_only}")
                except Exception:
                    pass
        if restore_error is not None:
            raise StableViewError("analysis_snapshot_restore_failed") from restore_error

    def _begin_read_transaction(self) -> tuple[object, int]:
        """Enter a short read-only transaction without borrowing caller state."""
        if self._conn.in_transaction:
            raise StableViewError("analysis_snapshot_caller_transaction_active")
        prior_factory = self._conn.row_factory
        prior_query_only: int | None = None
        try:
            # Read PRAGMA only after installing the predictable Row factory;
            # arbitrary caller factories must not affect repository internals.
            self._set_row_factory(sqlite3.Row)
            prior_query_only = int(self._execute("PRAGMA query_only").fetchone()[0])
            self._execute("PRAGMA query_only=ON")
            self._execute("BEGIN")
        except Exception as error:
            try:
                self._restore_snapshot_state(prior_factory, prior_query_only, rollback=True)
            except StableViewError as restore_error:
                raise restore_error from error
            raise StableViewError("analysis_snapshot_read_failed") from error
        return prior_factory, prior_query_only

    def _read(self, operation: str, subject_id: int, sql: str, params: tuple[object, ...], start: str | None = None, end: str | None = None, *, limit: int = _MAX_AUX_ROWS) -> tuple[dict[str, Any], ...]:
        if isinstance(subject_id, bool) or not isinstance(subject_id, int) or subject_id <= 0:
            raise StableViewError("analysis_snapshot_subject_invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_READ_ROWS:
            raise StableViewError("analysis_snapshot_limit_invalid")
        if self._snapshot_read_active:
            try:
                rows = tuple(_safe_row(row) for row in self._execute(sql, params))
                if len(rows) > limit: raise StableViewError("analysis_snapshot_limit_exceeded")
            except Exception as error:
                if isinstance(error, StableViewError): raise
                raise StableViewError("analysis_snapshot_read_failed") from error
            self._audit.append(QueryAudit(operation, subject_id, start, end, len(rows)))
            return rows
        prior_factory: object | None = None
        prior_query_only: int | None = None
        started = False
        committed = False
        try:
            prior_factory, prior_query_only = self._begin_read_transaction()
            started = True
            rows = tuple(_safe_row(row) for row in self._execute(sql, params))
            if len(rows) > limit:
                raise StableViewError("analysis_snapshot_limit_exceeded")
            self._execute("COMMIT")
            committed = True
        except Exception as error:
            self._audit.clear()
            if started:
                try:
                    self._restore_snapshot_state(prior_factory, prior_query_only, rollback=True)
                except StableViewError as restore_error:
                    raise restore_error from error
            if isinstance(error, StableViewError): raise
            raise StableViewError("analysis_snapshot_read_failed") from error
        try:
            self._restore_snapshot_state(prior_factory, prior_query_only, rollback=not committed)
        except StableViewError:
            self._audit.clear()
            raise
        self._audit.append(QueryAudit(operation, subject_id, start, end, len(rows)))
        return rows

    def view(self, name: str, subject_id: int, start_local_date: str, end_local_date: str, *, limit: int = _MAX_PUBLIC_VIEW_ROWS) -> tuple[dict[str, Any], ...]:
        start_local_date, end_local_date = _date(start_local_date), _date(end_local_date)
        maximum = _MAX_VIEW_ROWS if self._snapshot_read_active else _MAX_PUBLIC_VIEW_ROWS
        if start_local_date > end_local_date or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
            raise StableViewError("analysis_snapshot_query_forbidden")
        spec = next((item for item in _SPECS if item[0] == name), None)
        if spec is None: raise StableViewError("analysis_snapshot_query_forbidden")
        _, sql, kinds = spec
        start_utc, end_utc = f"{start_local_date}T00:00:00Z", f"{end_local_date}T23:59:59.999999Z"
        params = tuple({"subject": subject_id, "date": start_local_date if index == 1 else end_local_date, "start_utc": start_utc, "end_utc": end_utc}[kind] for index, kind in enumerate(kinds)) + (limit + 1,)
        sql += " LIMIT ?"
        return self._read(f"view:{name}", subject_id, sql, params, start_local_date, end_local_date, limit=limit)

    def snapshot(self, subject_id: int, start_local_date: str, end_local_date: str) -> StableSnapshot:
        start_local_date, end_local_date = _date(start_local_date), _date(end_local_date)
        if start_local_date > end_local_date: raise StableViewError("analysis_snapshot_date_invalid")
        if isinstance(subject_id, bool) or not isinstance(subject_id, int) or subject_id <= 0:
            raise StableViewError("analysis_snapshot_subject_invalid")
        self._audit = []
        prior_factory: object | None = None
        prior_query_only: int | None = None
        views: dict[str, tuple[dict[str, Any], ...]] = {}
        committed = False
        started = False
        try:
            prior_factory, prior_query_only = self._begin_read_transaction()
            started = True
            self._snapshot_read_active = True
            subject_rows = tuple(self._execute("SELECT id,timezone,is_active FROM data_subjects WHERE id=?", (subject_id,)))
            identity_rows = tuple(self._execute("SELECT subject_id,provider,identity_kind,is_verified FROM subject_identities WHERE subject_id=? AND provider='garmin' AND identity_kind='account' AND is_verified=1", (subject_id,)))
            if len(subject_rows) != 1 or len(identity_rows) != 1:
                raise StableViewError("analysis_snapshot_subject_context_invalid")
            subject, identity = subject_rows[0], identity_rows[0]
            if subject["id"] != subject_id or subject["is_active"] != 1 or subject["timezone"] != "Asia/Hong_Kong" or identity["subject_id"] != subject_id or identity["provider"] != "garmin" or identity["identity_kind"] != "account" or identity["is_verified"] != 1:
                raise StableViewError("analysis_snapshot_subject_context_invalid")
            subject_context = StableSubjectContext(subject_id, "Asia/Hong_Kong", "garmin", "account", True)
            self._snapshot_after_subject_context()
        # These views are intentionally queried independently: a missing
        # projection is schema incompatibility, never silently interpreted as empty.
            for name, _, _ in _SPECS:
                if name == "v_activity_segments":
                    views[name] = self._read(
                        f"view:{name}",
                        subject_id,
                        _SNAPSHOT_ACTIVITY_SEGMENTS_SQL + " LIMIT ?",
                        (
                            subject_id,
                            start_local_date,
                            end_local_date,
                            _MAX_VIEW_ROWS + 1,
                        ),
                        start_local_date,
                        end_local_date,
                        limit=_MAX_VIEW_ROWS,
                    )
                else:
                    views[name] = self.view(
                        name,
                        subject_id,
                        start_local_date,
                        end_local_date,
                        limit=_MAX_VIEW_ROWS,
                    )
            def aux(op: str, sql: str, params: tuple[object, ...]) -> tuple[dict[str, Any], ...]: return self._read(op, subject_id, sql + " LIMIT ?", params + (_MAX_AUX_ROWS + 1,), start_local_date, end_local_date, limit=_MAX_AUX_ROWS)
            coverage = aux("coverage", "SELECT c.id,c.subject_id,c.provider,c.resource_kind,c.local_date,c.availability_state,c.record_count,c.source_revision_id,1 AS source_revision_current,c.observed_at_utc FROM resource_coverage c WHERE c.subject_id=? AND c.local_date>=? AND c.local_date<=? AND (c.source_revision_id IS NULL OR EXISTS(SELECT 1 FROM source_revisions current_source WHERE current_source.id=c.source_revision_id AND current_source.is_current=1)) AND NOT EXISTS(SELECT 1 FROM resource_coverage newer WHERE newer.subject_id=c.subject_id AND newer.provider=c.provider AND newer.resource_kind=c.resource_kind AND newer.local_date=c.local_date AND (newer.observed_at_utc>c.observed_at_utc OR (newer.observed_at_utc=c.observed_at_utc AND newer.id>c.id))) ORDER BY c.local_date,c.resource_kind,c.id", (subject_id, start_local_date, end_local_date))
            cursors = aux("cursors", "SELECT resource_kind,cursor_grain,complete_through_local_date,last_success_at_utc,catalog_version FROM garmin_sync_cursors WHERE subject_id=? ORDER BY resource_kind,cursor_grain", (subject_id,))
            gaps = aux("gaps", "SELECT resource_kind,logical_object_key,window_start_local_date,window_end_local_date,stage,reason_code,status,priority,next_retry_at_utc FROM garmin_sync_gaps WHERE subject_id=? AND status IN ('open','deferred') AND window_end_local_date>=? AND window_start_local_date<=? ORDER BY priority DESC,window_start_local_date,resource_kind,id", (subject_id, start_local_date, end_local_date))
            stages = aux("activity_stage", "SELECT a.id,a.provider_activity_id,a.sport,a.sub_sport,a.local_date,a.start_time_utc,a.end_time_utc,a.elapsed_seconds,a.timer_seconds,a.distance_m,a.provider_state,(SELECT c.availability_state FROM resource_coverage c WHERE c.subject_id=a.subject_id AND c.provider=a.provider AND c.resource_kind='activity_inventory' AND c.local_date=a.local_date ORDER BY c.observed_at_utc DESC,c.id DESC LIMIT 1) AS inventory_coverage_state,(SELECT c.observed_at_utc FROM resource_coverage c WHERE c.subject_id=a.subject_id AND c.provider=a.provider AND c.resource_kind='activity_inventory' AND c.local_date=a.local_date ORDER BY c.observed_at_utc DESC,c.id DESC LIMIT 1) AS inventory_coverage_observed_at_utc,SUM(CASE WHEN ar.source_role='summary_json' AND ar.is_active=1 THEN 1 ELSE 0 END) AS summary_relation_count,SUM(CASE WHEN ar.source_role='activity_fit' AND ar.is_active=1 THEN 1 ELSE 0 END) AS fit_relation_count,SUM(CASE WHEN ar.source_role='details_json_fallback' AND ar.is_active=1 THEN 1 ELSE 0 END) AS fallback_relation_count,CASE WHEN SUM(CASE WHEN ar.source_role='summary_json' AND ar.is_active=1 THEN 1 ELSE 0 END)=1 AND SUM(CASE WHEN ar.source_role='summary_json' AND ar.is_active=1 AND sr.is_current=1 AND sr.parsed_at_utc IS NOT NULL AND sr.provider=a.provider AND sr.resource_kind='activity_summary' AND sr.provider_object_id=a.provider_activity_id THEN 1 ELSE 0 END)=1 THEN 1 ELSE 0 END AS summary_ready,CASE WHEN SUM(CASE WHEN ar.source_role='activity_fit' AND ar.is_active=1 THEN 1 ELSE 0 END)=1 AND SUM(CASE WHEN ar.source_role='activity_fit' AND ar.is_active=1 AND sr.is_current=1 AND sr.parsed_at_utc IS NOT NULL AND sr.provider=a.provider AND sr.resource_kind='activity_fit' AND sr.provider_object_id=a.provider_activity_id THEN 1 ELSE 0 END)=1 THEN 1 ELSE 0 END AS fit_core_ready,CASE WHEN SUM(CASE WHEN ar.source_role='details_json_fallback' AND ar.is_active=1 THEN 1 ELSE 0 END)=1 AND SUM(CASE WHEN ar.source_role='details_json_fallback' AND ar.is_active=1 AND sr.is_current=1 AND sr.parsed_at_utc IS NOT NULL AND sr.provider=a.provider AND sr.resource_kind='activity_details_fallback' AND sr.provider_object_id=a.provider_activity_id THEN 1 ELSE 0 END)=1 THEN 1 ELSE 0 END AS fallback_ready,MAX(CASE WHEN ar.source_role='activity_fit' AND ar.is_active=1 AND sr.is_current=1 AND sr.parsed_at_utc IS NOT NULL THEN sr.id END) AS active_fit_revision_id FROM activities a LEFT JOIN activity_source_revisions ar ON ar.activity_id=a.id LEFT JOIN source_revisions sr ON sr.id=ar.source_revision_id WHERE a.subject_id=? AND a.local_date>=? AND a.local_date<=? AND a.provider_state IN ('active','suspected_missing') GROUP BY a.id ORDER BY a.local_date,a.start_time_utc,a.id", (subject_id, start_local_date, end_local_date))
            quality_start_local_date = max(
                start_local_date,
                (
                    datetime.strptime(end_local_date, "%Y-%m-%d").date()
                    - timedelta(days=27)
                ).isoformat(),
            )
            quality = aux("quality", "SELECT q.entity_type,q.entity_id,q.issue_code,q.severity,q.status,q.first_seen_at_utc,q.last_seen_at_utc,CASE q.entity_type WHEN 'activity' THEN (SELECT a.local_date FROM activities a WHERE a.id=q.entity_id) WHEN 'daily_health' THEN (SELECT d.local_date FROM daily_health d WHERE d.id=q.entity_id) WHEN 'sleep_session' THEN (SELECT substr(s.end_time_utc,1,10) FROM sleep_sessions s WHERE s.id=q.entity_id) WHEN 'physiology_record' THEN (SELECT p.local_date FROM physiology_records p WHERE p.id=q.entity_id) WHEN 'coverage' THEN (SELECT c.local_date FROM resource_coverage c WHERE c.id=q.entity_id) END AS local_date FROM v_open_data_quality_issues q WHERE (q.entity_type='activity' AND EXISTS(SELECT 1 FROM activities a WHERE a.id=q.entity_id AND a.subject_id=? AND a.local_date>=? AND a.local_date<=?)) OR (q.entity_type='daily_health' AND EXISTS(SELECT 1 FROM daily_health d WHERE d.id=q.entity_id AND d.subject_id=? AND d.local_date>=? AND d.local_date<=?)) OR (q.entity_type='sleep_session' AND EXISTS(SELECT 1 FROM sleep_sessions s WHERE s.id=q.entity_id AND s.subject_id=? AND substr(s.end_time_utc,1,10)>=? AND substr(s.end_time_utc,1,10)<=?)) OR (q.entity_type='physiology_record' AND EXISTS(SELECT 1 FROM physiology_records p WHERE p.id=q.entity_id AND p.subject_id=? AND p.local_date>=? AND p.local_date<=?)) OR (q.entity_type='coverage' AND EXISTS(SELECT 1 FROM resource_coverage c WHERE c.id=q.entity_id AND c.subject_id=? AND c.local_date>=? AND c.local_date<=?)) ORDER BY q.severity DESC,q.last_seen_at_utc,q.id", (subject_id,quality_start_local_date,end_local_date,subject_id,quality_start_local_date,end_local_date,subject_id,quality_start_local_date,end_local_date,subject_id,quality_start_local_date,end_local_date,subject_id,quality_start_local_date,end_local_date))
            facts = aux("facts", "SELECT id,fact_key,scope,effective_from_utc,expires_at_utc,confidence FROM v_active_user_facts WHERE subject_id=? ORDER BY fact_key,id", (subject_id,))
            capabilities = aux("capabilities", "SELECT environment_key,resource_kind,capability_state,last_checked_at_utc,next_probe_at_utc FROM garmin_resource_capabilities WHERE subject_id=? ORDER BY environment_key,resource_kind,id", (subject_id,))
            raw_plan_reasons = aux("plan_reasons", "SELECT e.id,e.subject_id,e.event_type,e.actor_role,e.occurred_at_utc,e.trust_level,e.created_by,e.structured_payload_json AS reason_payload,m.id AS mail_message_id,m.mail_thread_id,m.actor_role AS mail_actor_role,m.direction,m.processing_state,m.source_revision_id,t.subject_id AS thread_subject_id,t.is_current AS thread_is_current,CASE WHEN sr.id IS NULL THEN 0 ELSE 1 END AS source_is_current FROM v_plan_revision_reason_events e JOIN mail_messages m ON m.id=e.mail_message_id JOIN mail_threads t ON t.id=m.mail_thread_id LEFT JOIN source_revisions sr ON sr.id=m.source_revision_id AND sr.is_current=1 AND sr.provider='gmail' AND sr.resource_kind='message_json' AND sr.provider_object_id=m.provider_message_id WHERE e.subject_id=? ORDER BY e.occurred_at_utc,e.id", (subject_id,))
            plan_reasons = tuple(_reason_payload(dict(row), subject_id) for row in raw_plan_reasons)
            if sum(len(x) for x in [*views.values(),coverage,cursors,gaps,stages,quality,facts,capabilities,plan_reasons]) > _MAX_SNAPSHOT_ROWS:
                self._audit.clear()
                raise StableViewError("analysis_snapshot_total_limit_exceeded")
            self._execute("COMMIT")
            committed = True
            result = StableSnapshot(views, coverage, cursors, gaps, stages, quality, facts, capabilities, plan_reasons, tuple(self._audit), subject_context)
        except Exception as error:
            self._audit.clear()
            if started:
                try:
                    self._restore_snapshot_state(prior_factory, prior_query_only, rollback=True)
                except StableViewError as restore_error:
                    raise restore_error from error
            if isinstance(error, StableViewError): raise
            raise StableViewError("analysis_snapshot_read_failed") from error
        finally:
            self._snapshot_read_active = False
        try:
            self._restore_snapshot_state(prior_factory, prior_query_only, rollback=not committed)
        except StableViewError:
            self._audit.clear()
            raise
        return result

    def technical_samples(self, subject_id: int, activity_id: int, metric: str, start_utc: str, end_utc: str, *, limit: int) -> dict[str, Any]:
        if (isinstance(subject_id, bool) or not isinstance(subject_id, int) or subject_id <= 0 or isinstance(activity_id, bool) or not isinstance(activity_id, int) or activity_id <= 0 or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_SAMPLE_LIMIT):
            raise StableViewError("analysis_sample_request_invalid")
        start_utc, start_at = _utc(start_utc); end_utc, end_at = _utc(end_utc)
        if start_at >= end_at: raise StableViewError("analysis_sample_window_invalid")
        column = {"heart_rate_bpm", "cadence_rpm", "power_w", "speed_mps", "altitude_m", "temperature_c"}
        if not isinstance(metric, str) or metric not in column:
            raise StableViewError("analysis_sample_metric_forbidden")
        start_key = f"{start_at:%Y-%m-%dT%H:%M:%S}.{start_at.microsecond:06d}Z"
        end_key = f"{end_at:%Y-%m-%dT%H:%M:%S}.{end_at.microsecond:06d}Z"
        sql = f"""
            WITH bounded_samples AS (
                SELECT s.id, s.sample_index, s.{metric} AS value,
                       CASE
                         WHEN length(s.timestamp_utc) = 20
                          AND s.timestamp_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
                          AND strftime('%Y-%m-%dT%H:%M:%S', s.timestamp_utc) = substr(s.timestamp_utc, 1, 19)
                         THEN substr(s.timestamp_utc, 1, 19) || '.000000Z'
                         WHEN length(s.timestamp_utc) = 27
                          AND s.timestamp_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]Z'
                          AND strftime('%Y-%m-%dT%H:%M:%S', s.timestamp_utc) = substr(s.timestamp_utc, 1, 19)
                         THEN s.timestamp_utc
                         ELSE NULL
                       END AS timestamp_key
                FROM activity_samples AS s
                JOIN activities AS a ON a.id = s.activity_id
                JOIN activity_source_revisions AS ar
                  ON ar.activity_id = s.activity_id
                 AND ar.source_revision_id = s.source_revision_id
                 AND ar.is_active = 1
                 AND ar.source_role = 'activity_fit'
                JOIN source_revisions AS sr
                  ON sr.id = s.source_revision_id
                 AND sr.is_current = 1
                 AND sr.parsed_at_utc IS NOT NULL
                 AND sr.provider = a.provider
                 AND sr.resource_kind = 'activity_fit'
                 AND sr.provider_object_id = a.provider_activity_id
                WHERE s.activity_id = ? AND a.subject_id = ?
                  AND a.provider_state = 'active'
                  AND typeof(s.{metric}) IN ('integer', 'real')
                  AND s.{metric} > -1e999 AND s.{metric} < 1e999
            )
            SELECT timestamp_key, value FROM bounded_samples
            WHERE timestamp_key IS NOT NULL AND timestamp_key >= ? AND timestamp_key <= ?
            ORDER BY timestamp_key, sample_index, id LIMIT ?
        """
        try:
            rows = self._read("technical_samples", subject_id, sql, (activity_id, subject_id, start_key, end_key, limit + 1), start_utc, end_utc, limit=limit + 1)
        except Exception:
            self._audit.clear()
            raise
        truncated = len(rows) > limit
        rows = rows[:limit]
        try:
            values = [float(row["value"]) for row in rows]
            if not all(math.isfinite(value) for value in values):
                raise ValueError("non-finite sample")
        except (TypeError, ValueError, OverflowError) as error:
            self._audit.clear()
            raise StableViewError("analysis_sample_value_invalid") from error
        return {"activity_id": activity_id, "metric": metric, "start_utc": start_utc, "end_utc": end_utc, "count": len(values), "minimum": min(values) if values else None, "maximum": max(values) if values else None, "latest": values[-1] if values else None, "truncated": truncated}
