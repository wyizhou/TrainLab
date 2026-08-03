"""Append-only persistence helpers for confirmed running HR zone revisions.

Foundation already provides immutable ``physiology_records`` and
``physiology_metrics`` tables.  A confirmed TrainLab zone revision is stored as
one parent row with exactly three child metrics (HRR, threshold proxy and
Tanaka), so no Foundation schema migration or destructive replacement is
needed.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping


_RECORD_TYPE = "running_heart_rate_zone_revision"
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
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def append_confirmed_zone_revision(
    connection: Any,
    subject_id: int,
    candidate: Mapping[str, Any],
    *,
    effective_from_utc: str,
    confirmation_event_id: int | None = None,
) -> int:
    """Append one confirmed candidate and return its physiology record ID."""
    if isinstance(subject_id, bool) or not isinstance(subject_id, int) or subject_id <= 0:
        raise ValueError("heart_rate_zone_subject_invalid")
    if candidate.get("primary_method") != "hrr" or candidate.get("accepted") is not True:
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
        (subject_id, "trainlab", _RECORD_TYPE, f"trainlab-hrr:{digest}", timestamp, timestamp[:10], "profile_setting", _json(extras)),
    )
    record_id = int(cursor.lastrowid)
    for key, metric in _METHODS:
        connection.execute(
            "INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_json,value_origin,source_path) VALUES(?,?,?,?,?)",
            (record_id, metric, _json(values[key]), "profile_setting", f"/confirmed/{key}"),
        )
    return record_id


def latest_confirmed_zone_revision(connection: Any, subject_id: int) -> dict[str, Any] | None:
    """Return the latest intact confirmed row without changing state."""
    rows = connection.execute(
        "SELECT id,effective_at_utc,extras_json FROM physiology_records "
        "WHERE subject_id=? AND domain='trainlab' AND record_type=? "
        "ORDER BY effective_at_utc DESC,id DESC",
        (subject_id, _RECORD_TYPE),
    ).fetchall()
    for row in rows:
        try:
            extras = json.loads(row["extras_json"] if isinstance(row, Mapping) else row[2])
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
                "effective_at_utc": row["effective_at_utc"] if isinstance(row, Mapping) else row[1],
                "extras": extras,
                "methods": values,
            }
    return None


def zone_evidence_from_snapshot(snapshot: Any) -> list[dict[str, Any]]:
    """Convert the latest confirmed HRR row in a stable snapshot to safety input."""
    views = getattr(snapshot, "views", {})
    records = views.get("v_current_physiology_records", ()) if isinstance(views, Mapping) else ()
    metrics = views.get("v_current_physiology_metrics", ()) if isinstance(views, Mapping) else ()
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
    candidates = [item for item in by_record.values() if isinstance(item["methods"].get("hrr"), Mapping)]
    candidates.sort(key=lambda item: (str(item["row"].get("effective_at_utc")), str(item["row"].get("id"))), reverse=True)
    if not candidates:
        return []
    item = candidates[0]
    hrr = item["methods"]["hrr"]
    zones = []
    for boundary in hrr.get("zones", []) if isinstance(hrr, Mapping) else []:
        bpm = boundary.get("bpm") if isinstance(boundary, Mapping) else None
        if isinstance(bpm, list) and len(bpm) == 2 and all(isinstance(value, int) for value in bpm):
            zones.append({"zone": boundary.get("zone"), "minimum_bpm": bpm[0], "maximum_bpm": bpm[1]})
    if len(zones) != 5:
        return []
    row = item["row"]
    revision = f"zone:{row.get('physiology_record_id')}"
    return [{
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
    }]


__all__ = ["append_confirmed_zone_revision", "latest_confirmed_zone_revision", "zone_evidence_from_snapshot"]
