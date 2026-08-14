"""Append-only persistence helpers for confirmed running HR zone revisions.

Foundation already provides immutable ``physiology_records`` and
``physiology_metrics`` tables.  A confirmed TrainLab zone revision is stored as
one parent row with exactly three child metrics (HRR, threshold proxy and
Tanaka), so no Foundation schema migration or destructive replacement is
needed.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Any, Mapping

from ..util import require_lastrowid

_RECORD_TYPE = "running_heart_rate_zone_revision"
_CANDIDATE_RECORD_TYPE = "running_heart_rate_zone_candidate"
_METHODS = (
    ("hrr", "hrr"),
    ("historical_threshold_proxy", "historical_threshold_proxy"),
    ("tanaka_low_confidence", "tanaka_low_confidence"),
)


def _canonical_utc(value: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("heart_rate_zone_timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ValueError("heart_rate_zone_timestamp_invalid") from None
    if parsed.tzinfo != timezone.utc:
        raise ValueError("heart_rate_zone_timestamp_invalid")
    return parsed.isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def append_confirmed_zone_revision(
    connection: Any,
    subject_id: int,
    candidate: Mapping[str, Any],
    *,
    effective_from_utc: str,
    confirmation_event_id: int | None = None,
) -> int:
    """Append one confirmed candidate and return its physiology record ID."""
    if (
        isinstance(subject_id, bool)
        or not isinstance(subject_id, int)
        or subject_id <= 0
    ):
        raise ValueError("heart_rate_zone_subject_invalid")
    if (
        candidate.get("primary_method") != "hrr"
        or candidate.get("accepted") is not True
    ):
        raise ValueError("heart_rate_zone_confirmation_required")
    timestamp = _canonical_utc(effective_from_utc)
    values: dict[str, Any] = {}
    for key, _metric in _METHODS:
        value = candidate.get(key)
        if not isinstance(value, Mapping):
            raise ValueError("heart_rate_zone_candidate_incomplete")
        values[key] = dict(value)
    digest = sha256(_json(values).encode("utf-8")).hexdigest()
    extras = {
        "algorithm_version": candidate.get("algorithm_version", "trainlab-hrr-v1"),
        "accepted": True,
        "primary_method": "hrr",
        "confirmation_event_id": confirmation_event_id,
        "candidate_sha256": digest,
    }
    cursor = connection.execute(
        "INSERT INTO physiology_records(subject_id,domain,record_type,provider_record_id,effective_at_utc,local_date,value_origin,extras_json,source_revision_id) VALUES(?,?,?,?,?,?,?,?,NULL)",
        (
            subject_id,
            "trainlab",
            _RECORD_TYPE,
            f"trainlab-hrr:{digest}",
            timestamp,
            timestamp[:10],
            "profile_setting",
            _json(extras),
        ),
    )
    record_id = require_lastrowid(cursor)
    for key, metric in _METHODS:
        connection.execute(
            "INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_json,value_origin,source_path) VALUES(?,?,?,?,?)",
            (
                record_id,
                metric,
                _json(values[key]),
                "profile_setting",
                f"/confirmed/{key}",
            ),
        )
    return record_id


def latest_confirmed_zone_revision(
    connection: Any, subject_id: int
) -> dict[str, Any] | None:
    """Return the latest intact confirmed row without changing state."""
    rows = connection.execute(
        "SELECT id,effective_at_utc,extras_json FROM physiology_records "
        "WHERE subject_id=? AND domain='trainlab' AND record_type=? "
        "ORDER BY effective_at_utc DESC,id DESC",
        (subject_id, _RECORD_TYPE),
    ).fetchall()
    for row in rows:
        try:
            extras = json.loads(
                row["extras_json"] if isinstance(row, Mapping) else row[2]
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if extras.get("accepted") is not True:
            continue
        metrics = connection.execute(
            "SELECT metric_key,value_json FROM physiology_metrics WHERE physiology_record_id=?",
            (int(row["id"] if isinstance(row, Mapping) else row[0]),),
        ).fetchall()
        values = {}
        for metric in metrics:
            if metric["value_json"] is None:
                continue
            try:
                values[str(metric["metric_key"])] = json.loads(metric["value_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                values = {}
                break
        if all(key in values for _key, key in _METHODS):
            return {
                "id": int(row["id"] if isinstance(row, Mapping) else row[0]),
                "effective_at_utc": row["effective_at_utc"]
                if isinstance(row, Mapping)
                else row[1],
                "extras": extras,
                "methods": values,
            }
    return None


def latest_zone_candidate(connection: Any, subject_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT id,local_date,effective_at_utc,extras_json FROM physiology_records "
        "WHERE subject_id=? AND domain='trainlab' AND record_type=? "
        "ORDER BY local_date DESC,id DESC LIMIT 1",
        (subject_id, _CANDIDATE_RECORD_TYPE),
    ).fetchone()
    if row is None:
        return None
    record_id = int(row["id"] if isinstance(row, Mapping) else row[0])
    metrics = connection.execute(
        "SELECT metric_key,value_json FROM physiology_metrics WHERE physiology_record_id=?",
        (record_id,),
    ).fetchall()
    values: dict[str, Any] = {}
    for metric in metrics:
        try:
            values[str(metric["metric_key"])] = json.loads(metric["value_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    if not all(key in values for key, _metric in _METHODS):
        return None
    return {
        "id": record_id,
        "local_date": row["local_date"],
        "effective_at_utc": row["effective_at_utc"],
        "methods": values,
    }


def ensure_zone_candidate(
    connection: Any,
    subject_id: int,
    *,
    as_of_local_date: str,
    effective_at_utc: str,
    weekly_refresh: bool,
    age_years: int | None = None,
) -> dict[str, Any]:
    """Calculate and append a bounded candidate when due.

    Daily execution only bootstraps a missing candidate. Weekly execution
    appends at most one candidate for that completed review date. Candidates
    never become prescription evidence until a separate user confirmation
    appends a confirmed revision.
    """
    as_of = date.fromisoformat(as_of_local_date)
    previous = latest_zone_candidate(connection, subject_id)
    if previous is not None and (
        not weekly_refresh or previous.get("local_date") == as_of.isoformat()
    ):
        return {"status": "unchanged", "record_id": previous["id"], **previous}

    resting: list[dict[str, Any]] = []
    for row in connection.execute(
        "SELECT local_date,values_json FROM daily_health WHERE subject_id=? AND is_current=1 "
        "AND local_date BETWEEN date(?,'-27 days') AND ? ORDER BY local_date,id",
        (subject_id, as_of.isoformat(), as_of.isoformat()),
    ):
        try:
            values = json.loads(row["values_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        bpm = values.get(
            "garmin.daily.resting_heart_rate_bpm", values.get("resting_heart_rate")
        )
        resting.append({"local_date": row["local_date"], "bpm": bpm, "valid": True})

    running: list[dict[str, Any]] = []
    sample_rows = connection.execute(
        "SELECT a.id,a.local_date,a.timer_seconds,a.name,a.sub_sport,s.heart_rate_bpm "
        "FROM activities a JOIN activity_source_revisions ar ON ar.activity_id=a.id "
        "AND ar.source_role='activity_fit' AND ar.is_active=1 "
        "JOIN source_revisions sr ON sr.id=ar.source_revision_id AND sr.is_current=1 "
        "JOIN activity_samples s ON s.activity_id=a.id AND s.source_revision_id=ar.source_revision_id "
        "WHERE a.subject_id=? AND lower(a.sport) IN ('running','run','trail_running','treadmill_running') "
        "AND a.local_date BETWEEN date(?,'-179 days') AND ? AND s.heart_rate_bpm IS NOT NULL "
        "ORDER BY a.id,s.sample_index",
        (subject_id, as_of.isoformat(), as_of.isoformat()),
    )
    active_id: int | None = None
    active: dict[str, Any] | None = None
    for row in sample_rows:
        row_id = int(row["id"])
        if row_id != active_id:
            if active is not None:
                running.append(active)
            active_id = row_id
            active = {
                "activity_id": str(row_id),
                "local_date": row["local_date"],
                "duration_seconds": row["timer_seconds"],
                "sample_interval_seconds": 1.0,
                "source_quality": "fit_verified",
                "session_type": " ".join(
                    str(value or "") for value in (row["name"], row["sub_sport"])
                ),
                "heart_rate_bpm": [],
            }
        if active is None:
            raise RuntimeError("heart_rate_activity_state_invalid")
        active["heart_rate_bpm"].append(row["heart_rate_bpm"])
    if active is not None:
        running.append(active)

    from .heart_rate_zones import calculate_zone_candidates

    candidate = calculate_zone_candidates(
        resting, running, as_of=as_of, age_years=age_years
    )
    values = {key: candidate[key] for key, _metric in _METHODS}
    digest = sha256(_json(values).encode("utf-8")).hexdigest()
    timestamp = _canonical_utc(effective_at_utc)
    cursor = connection.execute(
        "INSERT INTO physiology_records(subject_id,domain,record_type,provider_record_id,effective_at_utc,local_date,value_origin,extras_json,source_revision_id) VALUES(?,?,?,?,?,?,?, ?,NULL)",
        (
            subject_id,
            "trainlab",
            _CANDIDATE_RECORD_TYPE,
            f"trainlab-hrr-candidate:{as_of.isoformat()}:{digest}",
            timestamp,
            as_of.isoformat(),
            "unknown",
            _json(
                {
                    "algorithm_version": candidate["algorithm_version"],
                    "accepted": False,
                    "requires_user_confirmation": True,
                    "primary_method": "hrr",
                    "candidate_sha256": digest,
                }
            ),
        ),
    )
    record_id = require_lastrowid(cursor)
    for key, metric in _METHODS:
        connection.execute(
            "INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_json,value_origin,source_path) VALUES(?,?,?,?,?)",
            (record_id, metric, _json(values[key]), "unknown", f"/candidate/{key}"),
        )
    return {"status": "created", "record_id": record_id, "candidate": candidate}


def zone_evidence_from_snapshot(snapshot: Any) -> list[dict[str, Any]]:
    """Convert the latest confirmed HRR row in a stable snapshot to safety input."""
    views = getattr(snapshot, "views", {})
    records = (
        views.get("v_current_physiology_records", ())
        if isinstance(views, Mapping)
        else ()
    )
    metrics = (
        views.get("v_current_physiology_metrics", ())
        if isinstance(views, Mapping)
        else ()
    )
    by_record: dict[str, dict[str, Any]] = {}
    record_meta = {
        str(row.get("id")): row
        for row in records
        if isinstance(row, Mapping) and row.get("id") is not None
    }
    for metric in metrics:
        if not isinstance(metric, Mapping):
            continue
        parent = record_meta.get(str(metric.get("physiology_record_id")), {})
        domain = metric.get("domain", parent.get("domain"))
        record_type = metric.get("record_type", parent.get("record_type"))
        if (
            domain != "trainlab"
            or record_type != _RECORD_TYPE
            or metric.get("metric_key") != "hrr"
            or metric.get("value_origin") != "profile_setting"
        ):
            continue
        try:
            hrr = json.loads(metric.get("value_json") or "null")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(hrr, Mapping) and metric.get("physiology_record_id") is not None:
            by_record[str(metric["physiology_record_id"])] = {
                "row": {**parent, **metric},
                "methods": {"hrr": hrr},
            }
    candidates = [
        item
        for item in by_record.values()
        if isinstance(item["methods"].get("hrr"), Mapping)
    ]
    candidates.sort(
        key=lambda item: (
            str(item["row"].get("effective_at_utc")),
            str(item["row"].get("id")),
        ),
        reverse=True,
    )
    if not candidates:
        return []
    item = candidates[0]
    hrr = item["methods"]["hrr"]
    zones = []
    for boundary in hrr.get("zones", []) if isinstance(hrr, Mapping) else []:
        bpm = boundary.get("bpm") if isinstance(boundary, Mapping) else None
        if (
            isinstance(bpm, list)
            and len(bpm) == 2
            and all(isinstance(value, int) for value in bpm)
        ):
            zones.append(
                {
                    "zone": boundary.get("zone"),
                    "minimum_bpm": bpm[0],
                    "maximum_bpm": bpm[1],
                }
            )
    if len(zones) != 5:
        return []
    row = item["row"]
    revision = f"zone:{row.get('physiology_record_id')}"
    return [
        {
            "evidence_id": revision,
            "source_kind": "user_zones",
            "source_revision_id": revision,
            "measurement_method": "user_verified",
            "reliability": "reliable",
            "current": True,
            "effective_from_utc": row.get("effective_at_utc"),
            "expires_at_utc": None,
            "sport": "running",
            "heart_rate_bpm": None,
            "zones": zones,
        }
    ]


__all__ = [
    "append_confirmed_zone_revision",
    "latest_confirmed_zone_revision",
    "latest_zone_candidate",
    "ensure_zone_candidate",
    "zone_evidence_from_snapshot",
]
