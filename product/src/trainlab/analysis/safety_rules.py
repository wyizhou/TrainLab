"""A3-09 pure, deterministic heart-rate and training-safety rules.

The engine accepts only bounded DTOs, performs no database/network/model calls,
and returns a schema-validated recommendation decision with complete revision
provenance.  It does not diagnose medical conditions.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator, FormatChecker


class SafetyRuleError(ValueError):
    """Controlled fail-closed error for malformed or ambiguous rule inputs."""


_ROOT = Path(__file__).resolve().parent
_SCHEMA_ROOT = _ROOT / "schemas"


def _load_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"training_safety_static_json_invalid:{path.name}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"training_safety_static_json_invalid:{path.name}")
    return payload, raw


_POLICY, _POLICY_BYTES = _load_json(_ROOT / "training_safety_policy.json")
_POLICY_SCHEMA, _ = _load_json(_SCHEMA_ROOT / "training_safety_policy.schema.json")
_REQUEST_SCHEMA, _ = _load_json(_SCHEMA_ROOT / "training_safety_request.schema.json")
_RESULT_SCHEMA, _ = _load_json(_SCHEMA_ROOT / "training_safety_result.schema.json")
_FORMAT = FormatChecker()
_POLICY_VALIDATOR = Draft202012Validator(_POLICY_SCHEMA, format_checker=_FORMAT)
_REQUEST_VALIDATOR = Draft202012Validator(_REQUEST_SCHEMA, format_checker=_FORMAT)
_RESULT_VALIDATOR = Draft202012Validator(_RESULT_SCHEMA, format_checker=_FORMAT)

TRAINING_SAFETY_POLICY_VERSION = str(_POLICY["policy_version"])
TRAINING_SAFETY_POLICY_SHA256 = sha256(_POLICY_BYTES).hexdigest()
TRAINING_SAFETY_REQUEST_SCHEMA_VERSION = "1"
TRAINING_SAFETY_RESULT_SCHEMA_VERSION = "1"
_SG = ZoneInfo("Asia/Hong_Kong")
_RELIABLE_BASELINE_METHODS = frozenset({"provider_profile", "user_verified", "multiple_observations"})
_REASON_CODES = frozenset(_POLICY["reason_codes"])
_TOKENS = _POLICY["controlled_tokens"]


def _schema_error(
    validator: Draft202012Validator, payload: Mapping[str, Any], kind: str
) -> None:
    errors = sorted(
        validator.iter_errors(payload),
        key=lambda item: (tuple(str(part) for part in item.absolute_path), item.message),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "root"
        raise SafetyRuleError(f"training_safety_{kind}_schema_invalid:{location}")


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise SafetyRuleError("training_safety_json_invalid") from error


def stable_safety_hash(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _utc(value: Any, code: str = "training_safety_utc_invalid") -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SafetyRuleError(code)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise SafetyRuleError(code) from error
    if parsed.utcoffset() != timedelta(0):
        raise SafetyRuleError(code)
    return parsed


def _date(value: Any, code: str = "training_safety_date_invalid") -> date:
    if not isinstance(value, str):
        raise SafetyRuleError(code)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise SafetyRuleError(code) from error
    if parsed.isoformat() != value:
        raise SafetyRuleError(code)
    return parsed


def _revision(value: Any) -> str:
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int)):
        raise SafetyRuleError("training_safety_revision_invalid")
    return str(value)


def _validate_static_policy() -> None:
    errors = sorted(_POLICY_VALIDATOR.iter_errors(_POLICY), key=lambda error: list(error.absolute_path))
    if errors:
        raise RuntimeError("training_safety_policy_schema_invalid")
    if _POLICY["reason_codes"] != sorted(_POLICY["reason_codes"]):
        raise RuntimeError("training_safety_policy_reason_order_invalid")
    for key, values in _POLICY["controlled_tokens"].items():
        if key == "strength_exercises":
            if list(values) != sorted(values):
                raise RuntimeError("training_safety_policy_token_order_invalid")
        elif values != sorted(values):
            raise RuntimeError("training_safety_policy_token_order_invalid")
    previous_upper = 0.0
    for zone in range(1, 6):
        lower, upper = _POLICY["hrr_zone_percentages"][str(zone)]
        if lower >= upper or lower < previous_upper:
            raise RuntimeError("training_safety_policy_hrr_invalid")
        previous_upper = upper


_validate_static_policy()


def _reason(code: str, severity: str, revisions: tuple[str, ...] = ()) -> dict[str, Any]:
    if code not in _REASON_CODES:
        raise RuntimeError(f"training_safety_unknown_reason:{code}")
    return {
        "code": code,
        "severity": severity,
        "source_revision_ids": list(sorted(set(revisions))),
    }


def _add_reason(
    target: list[dict[str, Any]], code: str, severity: str, revisions: tuple[str, ...] = ()
) -> None:
    candidate = _reason(code, severity, revisions)
    if candidate not in target:
        target.append(candidate)


def _sort_reasons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (row["code"], row["severity"], tuple(row["source_revision_ids"])))


def _effective(
    row: Mapping[str, Any],
    as_of: datetime,
    reasons: list[dict[str, Any]],
) -> bool:
    revision = (_revision(row["source_revision_id"]),)
    if row["current"] is not True:
        _add_reason(reasons, "zone_evidence_noncurrent", "info", revision)
        return False
    start = _utc(row["effective_from_utc"])
    expiry = _utc(row["expires_at_utc"]) if row["expires_at_utc"] is not None else None
    if expiry is not None and expiry <= start:
        raise SafetyRuleError("training_safety_effective_range_invalid")
    if start > as_of:
        _add_reason(reasons, "zone_evidence_future", "info", revision)
        return False
    if expiry is not None and as_of >= expiry:
        _add_reason(reasons, "zone_evidence_expired", "info", revision)
        return False
    return True


def _active_signal(row: Mapping[str, Any], as_of: datetime) -> bool:
    start = _utc(row["effective_from_utc"])
    expiry = _utc(row["expires_at_utc"]) if row["expires_at_utc"] is not None else None
    if expiry is not None and expiry <= start:
        raise SafetyRuleError("training_safety_effective_range_invalid")
    return (
        row["current"] is True
        and row["active"] is True
        and start <= as_of
        and (expiry is None or as_of < expiry)
    )


def _validate_zones(row: Mapping[str, Any]) -> tuple[dict[str, int], ...]:
    zones = row["zones"]
    if not isinstance(zones, list):
        raise SafetyRuleError("training_safety_zone_boundaries_missing")
    output: list[dict[str, int]] = []
    prior_max: int | None = None
    for expected, boundary in enumerate(zones, 1):
        if boundary["zone"] != expected:
            raise SafetyRuleError("training_safety_zone_boundaries_invalid")
        low, high = boundary["minimum_bpm"], boundary["maximum_bpm"]
        if low > high or (prior_max is not None and low != prior_max + 1):
            raise SafetyRuleError("training_safety_zone_boundaries_invalid")
        output.append({"zone": expected, "minimum_bpm": low, "maximum_bpm": high})
        prior_max = high
    return tuple(output)


def _validate_zone_evidence(rows: list[dict[str, Any]]) -> None:
    ids: set[str] = set()
    for row in rows:
        evidence_id = row["evidence_id"]
        if evidence_id in ids:
            raise SafetyRuleError("training_safety_duplicate_evidence")
        ids.add(evidence_id)
        _revision(row["source_revision_id"])
        _utc(row["effective_from_utc"])
        if row["expires_at_utc"] is not None:
            _utc(row["expires_at_utc"])
        kind = row["source_kind"]
        zones = row["zones"]
        heart_rate = row["heart_rate_bpm"]
        method = row["measurement_method"]
        sport = row["sport"]
        if kind == "garmin_sport_zones":
            if sport != "running" or method != "provider_profile" or heart_rate is not None:
                raise SafetyRuleError("training_safety_zone_evidence_shape_invalid")
            _validate_zones(row)
        elif kind == "user_zones":
            if sport != "running" or method != "user_verified" or heart_rate is not None:
                raise SafetyRuleError("training_safety_zone_evidence_shape_invalid")
            _validate_zones(row)
        elif kind in {"max_hr_baseline", "resting_hr_baseline"}:
            if zones is not None or sport is not None or heart_rate is None:
                raise SafetyRuleError("training_safety_baseline_evidence_shape_invalid")
        elif kind == "time_in_zone":
            if zones is not None or heart_rate is not None or method != "activity_time_in_zone":
                raise SafetyRuleError("training_safety_prohibited_evidence_shape_invalid")
        elif kind == "age_formula":
            if zones is not None or heart_rate is None or method != "age_formula":
                raise SafetyRuleError("training_safety_prohibited_evidence_shape_invalid")
        elif kind == "single_sample_max_hr":
            if zones is not None or heart_rate is None or method != "single_sample":
                raise SafetyRuleError("training_safety_prohibited_evidence_shape_invalid")


def _hrr_zones(max_hr: int, resting_hr: int) -> tuple[dict[str, int], ...]:
    if not 100 <= max_hr <= 240 or not 30 <= resting_hr <= 120 or max_hr - resting_hr < 30:
        raise SafetyRuleError("training_safety_hrr_baseline_invalid")
    reserve = max_hr - resting_hr
    output = []
    prior_max: int | None = None
    for zone in range(1, 6):
        low, high = _POLICY["hrr_zone_percentages"][str(zone)]
        minimum = (
            math.ceil(resting_hr + reserve * low)
            if prior_max is None
            else prior_max + 1
        )
        maximum = (
            math.ceil(resting_hr + reserve * high) - 1
            if zone < 5
            else math.floor(resting_hr + reserve * high)
        )
        if minimum > maximum:
            raise SafetyRuleError("training_safety_hrr_baseline_invalid")
        output.append({"zone": zone, "minimum_bpm": minimum, "maximum_bpm": maximum})
        prior_max = maximum
    return tuple(output)


def _fallback_zone_selection() -> dict[str, Any]:
    return {
        "exact_bpm_allowed": False,
        "source_kind": "rpe_talk_test",
        "source_revision_id": None,
        "source_revision_ids": [],
        "zones": None,
    }


def _not_applicable_zone_selection() -> dict[str, Any]:
    return {
        "exact_bpm_allowed": False,
        "source_kind": "not_applicable",
        "source_revision_id": None,
        "source_revision_ids": [],
        "zones": None,
    }


def _zone_selection(
    evidence: list[dict[str, Any]],
    as_of: datetime,
    hr_blockers: list[dict[str, Any]],
    reasons: list[dict[str, Any]],
) -> dict[str, Any]:
    eligible: list[dict[str, Any]] = []
    for row in evidence:
        revision = (_revision(row["source_revision_id"]),)
        if row["source_kind"] in {"time_in_zone", "age_formula", "single_sample_max_hr"}:
            _add_reason(reasons, "prohibited_zone_evidence", "info", revision)
            continue
        if not _effective(row, as_of, reasons):
            continue
        if row["source_kind"] in {"max_hr_baseline", "resting_hr_baseline"} and row["measurement_method"] not in _RELIABLE_BASELINE_METHODS:
            _add_reason(reasons, "prohibited_zone_evidence", "info", revision)
            continue
        if row["reliability"] != "reliable":
            _add_reason(reasons, "source_evidence_invalid", "warning", revision)
            continue
        eligible.append(row)
    blocker_kinds = {row["kind"] for row in hr_blockers}
    exact_bpm_blocked = False
    if "hr_affecting_medication" in blocker_kinds:
        blocker_revisions = tuple(_revision(row["source_revision_id"]) for row in hr_blockers if row["kind"] == "hr_affecting_medication")
        _add_reason(reasons, "hr_medication_exact_bpm_blocked", "warning", blocker_revisions)
        exact_bpm_blocked = True
    if "hr_baseline_unreliable" in blocker_kinds:
        blocker_revisions = tuple(_revision(row["source_revision_id"]) for row in hr_blockers if row["kind"] == "hr_baseline_unreliable")
        _add_reason(reasons, "hr_baseline_unreliable", "warning", blocker_revisions)
        exact_bpm_blocked = True
    if exact_bpm_blocked:
        _add_reason(reasons, "exact_zone_unavailable", "warning")
        return _fallback_zone_selection()

    for source_kind, reason_code in (
        ("garmin_sport_zones", "exact_zone_source_garmin"),
        ("user_zones", "exact_zone_source_user"),
    ):
        candidates = [row for row in eligible if row["source_kind"] == source_kind]
        if len(candidates) > 1:
            _add_reason(
                reasons,
                "zone_source_conflict",
                "warning",
                tuple(_revision(row["source_revision_id"]) for row in candidates),
            )
            _add_reason(reasons, "exact_zone_unavailable", "warning")
            return _fallback_zone_selection()
        if candidates:
            row = candidates[0]
            revision = _revision(row["source_revision_id"])
            _add_reason(reasons, reason_code, "info", (revision,))
            return {
                "exact_bpm_allowed": True,
                "source_kind": source_kind,
                "source_revision_id": revision,
                "source_revision_ids": [revision],
                "zones": list(_validate_zones(row)),
            }

    max_rows = [row for row in eligible if row["source_kind"] == "max_hr_baseline"]
    resting_rows = [row for row in eligible if row["source_kind"] == "resting_hr_baseline"]
    usable_max = [row for row in max_rows if row["measurement_method"] in _RELIABLE_BASELINE_METHODS]
    usable_rest = [row for row in resting_rows if row["measurement_method"] in _RELIABLE_BASELINE_METHODS]
    if len(usable_max) > 1 or len(usable_rest) > 1:
        conflict_rows = usable_max if len(usable_max) > 1 else usable_rest
        _add_reason(
            reasons,
            "zone_source_conflict",
            "warning",
            tuple(_revision(row["source_revision_id"]) for row in conflict_rows),
        )
        _add_reason(reasons, "exact_zone_unavailable", "warning")
        return _fallback_zone_selection()
    if len(usable_max) == 1 and len(usable_rest) == 1:
        revisions = tuple(
            sorted(
                (
                    _revision(usable_max[0]["source_revision_id"]),
                    _revision(usable_rest[0]["source_revision_id"]),
                )
            )
        )
        derived_revision = "hrr:" + stable_safety_hash(
            {
                "policy_sha256": TRAINING_SAFETY_POLICY_SHA256,
                "source_revision_ids": revisions,
            }
        )[:32]
        zones = _hrr_zones(
            int(usable_max[0]["heart_rate_bpm"]),
            int(usable_rest[0]["heart_rate_bpm"]),
        )
        _add_reason(reasons, "exact_zone_source_hrr", "info", revisions)
        return {
            "exact_bpm_allowed": True,
            "source_kind": "hrr",
            "source_revision_id": derived_revision,
            "source_revision_ids": list(revisions),
            "zones": list(zones),
        }
    _add_reason(reasons, "exact_zone_unavailable", "warning")
    return _fallback_zone_selection()


def _validate_primary_semantics(item: Mapping[str, Any]) -> None:
    kind = item["activity_kind"]
    if kind == "running":
        role_course_types = {
            "easy": {"easy"},
            "long": {"long_easy"},
            "tempo": {"steady"},
            "speed": {"intervals"},
            "running_strength": {"intervals"},
        }
        if item["course_type"] not in role_course_types[item["hansons_session_role"]]:
            raise SafetyRuleError("training_safety_hansons_role_invalid")
        token_fields = {
            "warmup": "running_warmup",
            "main_set": "running_main_set",
            "cooldown": "running_cooldown",
            "total_volume": "running_total_volume",
            "talk_test": "running_talk_test",
            "rationale": "running_rationale",
        }
        if any(item[field] not in _TOKENS[token_group] for field, token_group in token_fields.items()):
            raise SafetyRuleError("training_safety_controlled_token_invalid")
        if item.get("planned_duration_seconds") is not None and item["planned_duration_seconds"] != item["planned_duration_minutes"] * 60:
            raise SafetyRuleError("training_safety_duration_units_ambiguous")
        bpm = item["target_bpm_range"]
        if bpm is not None and bpm["minimum_bpm"] > bpm["maximum_bpm"]:
            raise SafetyRuleError("training_safety_bpm_range_invalid")
        if item["target_zone"] is None and bpm is not None:
            raise SafetyRuleError("training_safety_bpm_without_zone")
    elif kind == "strength":
        if item["rationale"] not in _TOKENS["strength_rationale"]:
            raise SafetyRuleError("training_safety_controlled_token_invalid")
        keys = [row["exercise_key"] for row in item["movements"]]
        if len(keys) != len(set(keys)):
            raise SafetyRuleError("training_safety_duplicate_movement")
        if any(
            row["exercise_key"] not in _TOKENS["strength_exercises"]
            or _TOKENS["strength_exercises"][row["exercise_key"]] != row["movement_kind"]
            for row in item["movements"]
        ):
            raise SafetyRuleError("training_safety_controlled_token_invalid")
        movement_kinds = {row["movement_kind"] for row in item["movements"]}
        if not movement_kinds & {"squat", "hinge"} or not movement_kinds & {"push", "pull"} or not movement_kinds & {"carry", "core"}:
            raise SafetyRuleError("training_safety_strength_coverage_incomplete")
    elif kind == "climbing":
        if item["rationale"] not in _TOKENS["climbing_rationale"]:
            raise SafetyRuleError("training_safety_controlled_token_invalid")
    else:
        if (
            any(value not in _TOKENS["rest_evidence"] for value in item["evidence"])
            or item["uncertainty"] not in _TOKENS["rest_uncertainty"]
            or any(value not in _TOKENS["rest_recovery_signals"] for value in item["recovery_signals"])
            or any(value not in _TOKENS["rest_seek_help"] for value in item["seek_professional_help_if"])
        ):
            raise SafetyRuleError("training_safety_controlled_token_invalid")


def _validate_quality_sessions(rows: list[dict[str, Any]]) -> None:
    ids: set[str] = set()
    for row in rows:
        if row["activity_id"] in ids:
            raise SafetyRuleError("training_safety_duplicate_quality_session")
        ids.add(row["activity_id"])
        _revision(row["source_revision_id"])
        start, end = _utc(row["start_time_utc"]), _utc(row["end_time_utc"])
        if end < start:
            raise SafetyRuleError("training_safety_quality_session_range_invalid")
        if start.astimezone(_SG).date() != _date(row["local_date"]):
            raise SafetyRuleError("training_safety_quality_session_local_date_mismatch")


def _assess_substitution(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    if row["current"] is not True:
        raise SafetyRuleError("training_safety_substitution_noncurrent")
    revision = _revision(row["source_revision_id"])
    for prefix in ("planned", "actual"):
        minutes = float(row[f"{prefix}_duration_minutes"])
        seconds = row[f"{prefix}_duration_seconds"]
        if seconds is not None and not math.isclose(float(seconds), minutes * 60, rel_tol=0, abs_tol=1e-9):
            raise SafetyRuleError("training_safety_duration_units_ambiguous")
    ratio = float(row["actual_duration_minutes"]) / float(row["planned_duration_minutes"])
    exact = (
        row["planned_activity_kind"] == row["actual_activity_kind"]
        and 0.95 <= ratio <= 1.05
    )
    return {
        "status": "conflicts_with_exact_activity_evidence" if exact else "consistent_with_substitution",
        "planned_activity_kind": row["planned_activity_kind"],
        "actual_activity_kind": row["actual_activity_kind"],
        "duration_ratio": ratio,
        "source_revision_id": revision,
    }


def _rest_for_safety(
    evidence: tuple[str, ...],
    *,
    professional: bool,
    daily_activity_allowed: bool,
) -> dict[str, Any]:
    return {
        "activity_kind": "rest",
        "evidence": list(evidence),
        "uncertainty": "safety_rule_not_medical_diagnosis",
        "daily_activity_allowed": daily_activity_allowed,
        "recovery_signals": ["symptoms_resolved", "recovery_status_reassessed"],
        "seek_professional_help_if": (
            ["red_flag_present_or_persistent"]
            if professional
            else ["pain_or_recovery_concern_persists"]
        ),
    }


def _running_output(
    source: Mapping[str, Any],
    zone_selection: Mapping[str, Any],
    *,
    fallback: bool,
) -> dict[str, Any]:
    output = {
        key: deepcopy(source[key])
        for key in (
            "activity_kind",
            "hansons_session_role",
            "course_type",
            "warmup",
            "main_set",
            "cooldown",
            "planned_duration_minutes",
            "total_volume",
            "target_zone",
            "target_bpm_range",
            "prescribed_rpe",
            "talk_test",
            "work_intervals",
            "stop_conditions",
            "rationale",
        )
    }
    if fallback:
        output.update(
            {
                "hansons_session_role": "easy",
                "course_type": _POLICY["fallback"]["course_type"],
                "main_set": "talk_test_easy",
                "planned_duration_minutes": min(
                    output["planned_duration_minutes"],
                    _POLICY["fallback"]["maximum_duration_minutes"],
                ),
                "total_volume": "easy_by_duration",
                "target_zone": None,
                "target_bpm_range": None,
                "prescribed_rpe": min(
                    output["prescribed_rpe"], _POLICY["fallback"]["maximum_rpe"]
                ),
                "work_intervals": [],
            }
        )
    output["zone_source_kind"] = zone_selection["source_kind"]
    output["zone_source_revision_id"] = zone_selection["source_revision_id"]
    output["zone_source_revision_ids"] = list(zone_selection["source_revision_ids"])
    return output


def _rejected_result(
    base: dict[str, Any],
    zone_selection: dict[str, Any],
    reasons: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    substitution: dict[str, Any] | None,
) -> dict[str, Any]:
    result = {
        **base,
        "status": "rejected",
        "safety_state": "blocked",
        "professional_evaluation_recommended": False,
        "primary_items": [],
        "zone_selection": zone_selection,
        "substitution_assessment": substitution,
        "reasons": _sort_reasons(reasons),
        "warnings": _sort_reasons(warnings),
    }
    return result


def _high_intensity_rejection(
    item: Mapping[str, Any],
    advice_date: date,
    quality_sessions: list[dict[str, Any]],
    reasons: list[dict[str, Any]],
) -> bool:
    zone = item["target_zone"]
    if zone not in {4, 5}:
        return False
    if item["course_type"] != "intervals" or not item["work_intervals"]:
        _add_reason(reasons, "zone45_requires_intervals", "block")
        return True
    if item["prescribed_rpe"] > _POLICY["quality_session"]["maximum_rpe"]:
        _add_reason(reasons, "rpe_too_high", "block")
        return True
    if any(interval["target_zone"] != zone for interval in item["work_intervals"]):
        _add_reason(reasons, "interval_structure_invalid", "block")
        return True
    maximum_single = _POLICY["quality_session"][
        f"zone{zone}_maximum_single_work_seconds"
    ]
    maximum_total = _POLICY["quality_session"][
        f"zone{zone}_maximum_total_work_seconds"
    ]
    total_work = 0
    total_session = 0
    ratio = _POLICY["quality_session"]["minimum_recovery_to_work_ratio"]
    for interval in item["work_intervals"]:
        work = interval["work_seconds"]
        recovery = interval["recovery_seconds"]
        repetitions = interval["repetitions"]
        total_work += work * repetitions
        total_session += (work + recovery) * repetitions
        if work > maximum_single or recovery < math.ceil(work * ratio):
            _add_reason(reasons, "interval_structure_invalid", "block")
            return True
    available_interval_seconds = (
        item["planned_duration_minutes"] * 60
        - _POLICY["quality_session"]["minimum_warmup_cooldown_seconds"]
    )
    if total_work > maximum_total or total_session > available_interval_seconds:
        _add_reason(reasons, "zone45_dose_exceeded", "block")
        return True
    window_start = advice_date - timedelta(days=_POLICY["quality_session"]["lookback_days"])
    prior = [
        row
        for row in quality_sessions
        if row["current"] is True
        and row["is_formal_training"] is True
        and row["quality_session"] is True
        and window_start <= _date(row["local_date"]) < advice_date
    ]
    revisions = tuple(_revision(row["source_revision_id"]) for row in prior)
    if len(prior) >= _POLICY["quality_session"]["maximum_prior_sessions"]:
        _add_reason(reasons, "zone45_frequency_exceeded", "block", revisions)
        return True
    if prior:
        latest_end = max(_utc(row["end_time_utc"]) for row in prior)
        earliest_start = datetime.combine(advice_date, time.min, tzinfo=_SG).astimezone(
            timezone.utc
        )
        recovery_hours = (earliest_start - latest_end).total_seconds() / 3600
        if recovery_hours < _POLICY["quality_session"]["minimum_recovery_hours"]:
            _add_reason(reasons, "zone45_recovery_insufficient", "block", revisions)
            return True
    return False


def _running_structure_rejection(
    item: Mapping[str, Any], reasons: list[dict[str, Any]]
) -> bool:
    intervals = item["work_intervals"]
    target_zone = item["target_zone"]
    quality_rpe = item["prescribed_rpe"] >= _POLICY["quality_session"]["quality_rpe_threshold"]
    if quality_rpe and (
        target_zone not in {4, 5}
        or item["course_type"] != "intervals"
        or not intervals
    ):
        _add_reason(reasons, "zone45_requires_intervals", "block")
        return True
    if intervals and (
        item["course_type"] != "intervals"
        or target_zone is None
        or any(interval["target_zone"] != target_zone for interval in intervals)
    ):
        _add_reason(reasons, "interval_structure_invalid", "block")
        return True
    if item["course_type"] == "intervals" and not intervals and target_zone not in {4, 5}:
        _add_reason(reasons, "interval_structure_invalid", "block")
        return True
    return False


class TrainingSafetyRuleEngine:
    """Versioned A3-09 pure rule engine."""

    policy_version = TRAINING_SAFETY_POLICY_VERSION
    policy_sha256 = TRAINING_SAFETY_POLICY_SHA256

    def validate_request(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise SafetyRuleError("training_safety_request_type_invalid")
        _canonical(request)
        payload = deepcopy(dict(request))
        _schema_error(_REQUEST_VALIDATOR, payload, "request")
        as_of = _utc(payload["as_of_utc"])
        _date(payload["advice_local_date"])
        _validate_zone_evidence(payload["zone_evidence"])
        _validate_quality_sessions(payload["quality_sessions"])
        if any(_utc(row["end_time_utc"]) > as_of for row in payload["quality_sessions"]):
            raise SafetyRuleError("training_safety_future_quality_session")
        _validate_primary_semantics(payload["primary_items"][0])
        signal_ids: set[str] = set()
        for signal in payload["safety_signals"]:
            if signal["signal_id"] in signal_ids:
                raise SafetyRuleError("training_safety_duplicate_signal")
            signal_ids.add(signal["signal_id"])
            _revision(signal["source_revision_id"])
            _utc(signal["effective_from_utc"])
            if signal["expires_at_utc"] is not None:
                _utc(signal["expires_at_utc"])
            if signal["kind"] in _POLICY["red_flag_signal_kinds"] and signal["origin"] == "device_fact":
                raise SafetyRuleError("training_safety_device_red_flag_invalid")
        _assess_substitution(payload["substitution"])
        # Force all effective ranges through their semantic validators.
        for signal in payload["safety_signals"]:
            _active_signal(signal, as_of)
        return payload

    def validate_result(self, result: Mapping[str, Any]) -> None:
        if not isinstance(result, Mapping):
            raise SafetyRuleError("training_safety_result_type_invalid")
        _canonical(result)
        payload = dict(result)
        _schema_error(_RESULT_VALIDATOR, payload, "result")
        if (
            payload["policy_version"] != TRAINING_SAFETY_POLICY_VERSION
            or payload["policy_sha256"] != TRAINING_SAFETY_POLICY_SHA256
        ):
            raise SafetyRuleError("training_safety_result_policy_invalid")
        if any(row["code"] not in _REASON_CODES for row in [*payload["reasons"], *payload["warnings"]]):
            raise SafetyRuleError("training_safety_result_reason_invalid")
        if payload["input_revision_ids"] != sorted(set(payload["input_revision_ids"])):
            raise SafetyRuleError("training_safety_result_lineage_invalid")
        for field in ("reasons", "warnings"):
            if payload[field] != _sort_reasons(payload[field]):
                raise SafetyRuleError("training_safety_result_reason_order_invalid")
            if any(
                row["source_revision_ids"] != sorted(set(row["source_revision_ids"]))
                for row in payload[field]
            ):
                raise SafetyRuleError("training_safety_result_reason_lineage_invalid")
        if payload["zone_selection"]["source_revision_ids"] != sorted(
            set(payload["zone_selection"]["source_revision_ids"])
        ):
            raise SafetyRuleError("training_safety_result_zone_lineage_invalid")
        lineage = set(payload["input_revision_ids"])
        if any(
            not set(row["source_revision_ids"]) <= lineage
            for row in [*payload["reasons"], *payload["warnings"]]
        ) or not set(payload["zone_selection"]["source_revision_ids"]) <= lineage:
            raise SafetyRuleError("training_safety_result_lineage_invalid")
        zone = payload["zone_selection"]
        if zone["exact_bpm_allowed"]:
            if (
                zone["source_kind"] not in {"garmin_sport_zones", "user_zones", "hrr"}
                or zone["source_revision_id"] is None
                or not zone["source_revision_ids"]
                or zone["zones"] is None
            ):
                raise SafetyRuleError("training_safety_result_zone_invalid")
            _validate_zones(zone)
            if zone["source_kind"] in {"garmin_sport_zones", "user_zones"} and (
                zone["source_revision_ids"] != [zone["source_revision_id"]]
            ):
                raise SafetyRuleError("training_safety_result_zone_lineage_invalid")
        elif (
            zone["source_kind"] not in {"rpe_talk_test", "not_applicable"}
            or zone["source_revision_id"] is not None
            or zone["source_revision_ids"]
            or zone["zones"] is not None
        ):
            raise SafetyRuleError("training_safety_result_zone_invalid")
        if payload["status"] == "rejected" and payload["primary_items"]:
            raise SafetyRuleError("training_safety_result_rejected_item_invalid")
        if payload["status"] != "rejected" and len(payload["primary_items"]) != 1:
            raise SafetyRuleError("training_safety_result_primary_item_invalid")
        if payload["professional_evaluation_recommended"] and payload["safety_state"] != "suspended":
            raise SafetyRuleError("training_safety_result_professional_evaluation_invalid")
        if payload["substitution_assessment"] is not None and payload["substitution_assessment"]["source_revision_id"] not in lineage:
            raise SafetyRuleError("training_safety_result_lineage_invalid")
        if payload["primary_items"]:
            _validate_primary_semantics(payload["primary_items"][0])
        if payload["primary_items"] and payload["primary_items"][0]["activity_kind"] == "running":
            item = payload["primary_items"][0]
            result_rule_reasons: list[dict[str, Any]] = []
            if _running_structure_rejection(item, result_rule_reasons) or _high_intensity_rejection(
                item,
                date(2000, 1, 1),
                [],
                result_rule_reasons,
            ):
                raise SafetyRuleError("training_safety_result_running_rule_invalid")
            if (
                item["zone_source_kind"] != zone["source_kind"]
                or item["zone_source_revision_id"] != zone["source_revision_id"]
                or item["zone_source_revision_ids"] != zone["source_revision_ids"]
            ):
                raise SafetyRuleError("training_safety_result_zone_lineage_invalid")
            if item["target_zone"] is None:
                if item["target_bpm_range"] is not None:
                    raise SafetyRuleError("training_safety_result_zone_invalid")
            else:
                if not zone["exact_bpm_allowed"] or item["target_bpm_range"] is None:
                    raise SafetyRuleError("training_safety_result_zone_invalid")
                expected = next(row for row in zone["zones"] if row["zone"] == item["target_zone"])
                if item["target_bpm_range"] != {
                    "minimum_bpm": expected["minimum_bpm"],
                    "maximum_bpm": expected["maximum_bpm"],
                }:
                    raise SafetyRuleError("training_safety_result_zone_invalid")
        elif payload["primary_items"] and zone["source_kind"] != "not_applicable":
            raise SafetyRuleError("training_safety_result_zone_invalid")

    def serialize_result(self, result: Mapping[str, Any]) -> str:
        """Return the sole stable JSON representation after full validation."""

        self.validate_result(result)
        return _canonical(result)

    def evaluate(self, request: Mapping[str, Any]) -> dict[str, Any]:
        payload = self.validate_request(request)
        as_of = _utc(payload["as_of_utc"])
        advice_date = _date(payload["advice_local_date"])
        item = payload["primary_items"][0]
        reasons: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        all_revisions = sorted(
            {
                *(_revision(row["source_revision_id"]) for row in payload["zone_evidence"]),
                *(_revision(row["source_revision_id"]) for row in payload["safety_signals"]),
                *(_revision(row["source_revision_id"]) for row in payload["quality_sessions"]),
                *(
                    (_revision(payload["substitution"]["source_revision_id"]),)
                    if payload["substitution"] is not None
                    else ()
                ),
            }
        )
        substitution = _assess_substitution(payload["substitution"])
        if substitution is not None:
            code = (
                "substitution_conflicts_exact_evidence"
                if substitution["status"] == "conflicts_with_exact_activity_evidence"
                else "substitution_consistent"
            )
            _add_reason(reasons, code, "warning" if "conflicts" in code else "info", (substitution["source_revision_id"],))

        active_signals = [
            row for row in payload["safety_signals"] if _active_signal(row, as_of)
        ]
        device_anomalies = [
            row for row in active_signals if row["kind"] == "device_anomaly"
        ]
        if device_anomalies:
            _add_reason(
                warnings,
                "device_anomaly_warning",
                "warning",
                tuple(_revision(row["source_revision_id"]) for row in device_anomalies),
            )
        red_flags = [
            row
            for row in active_signals
            if row["kind"] in _POLICY["red_flag_signal_kinds"]
            and row["origin"] in {"user_asserted", "provider_fact"}
        ]
        base = {
            "schema_version": TRAINING_SAFETY_RESULT_SCHEMA_VERSION,
            "policy_version": TRAINING_SAFETY_POLICY_VERSION,
            "policy_sha256": TRAINING_SAFETY_POLICY_SHA256,
            "input_revision_ids": all_revisions,
            "constraints": {
                "maximum_primary_items": 1,
                "clock_time_forbidden": True,
                "medical_diagnosis_forbidden": True,
                "all_out_forbidden": True,
            },
        }
        if red_flags:
            revisions = tuple(_revision(row["source_revision_id"]) for row in red_flags)
            _add_reason(reasons, "red_flag_training_suspended", "block", revisions)
            _add_reason(reasons, "professional_evaluation_recommended", "warning", revisions)
            result = {
                **base,
                "status": "modified_for_safety",
                "safety_state": "suspended",
                "professional_evaluation_recommended": True,
                "primary_items": [
                    _rest_for_safety(
                        tuple(sorted({row["kind"] for row in red_flags})),
                        professional=True,
                        daily_activity_allowed=False,
                    )
                ],
                "zone_selection": _not_applicable_zone_selection(),
                "substitution_assessment": substitution,
                "reasons": _sort_reasons(reasons),
                "warnings": _sort_reasons(warnings),
            }
            self.validate_result(result)
            return result

        hr_blockers = [
            row
            for row in active_signals
            if row["kind"] in _POLICY["hr_blocking_signal_kinds"]
        ]
        zone_selection = (
            _zone_selection(payload["zone_evidence"], as_of, hr_blockers, reasons)
            if item["activity_kind"] == "running"
            else _not_applicable_zone_selection()
        )
        if item["activity_kind"] == "running":
            required_stop = set(_POLICY["required_running_stop_conditions"])
            if not required_stop <= set(item["stop_conditions"]):
                _add_reason(reasons, "stop_conditions_incomplete", "block")
                result = _rejected_result(base, zone_selection, reasons, warnings, substitution)
                self.validate_result(result)
                return result
            if item["prescribed_rpe"] >= 10:
                _add_reason(reasons, "rpe_too_high", "block")
                result = _rejected_result(base, zone_selection, reasons, warnings, substitution)
                self.validate_result(result)
                return result
            fallback = not zone_selection["exact_bpm_allowed"]
            if fallback:
                safe_item = _running_output(item, zone_selection, fallback=True)
                changed = {
                    key: value
                    for key, value in safe_item.items()
                    if key not in {"zone_source_kind", "zone_source_revision_id", "zone_source_revision_ids"}
                } != {
                    key: value
                    for key, value in item.items()
                    if key != "planned_duration_seconds"
                }
                _add_reason(reasons, "low_intensity_fallback", "warning")
                status = "modified_for_safety" if changed else "accepted"
            else:
                if _running_structure_rejection(item, reasons):
                    result = _rejected_result(base, zone_selection, reasons, warnings, substitution)
                    self.validate_result(result)
                    return result
                target_zone = item["target_zone"]
                target_range = item["target_bpm_range"]
                if target_zone is None:
                    if target_range is not None:
                        _add_reason(reasons, "target_bpm_mismatch", "block")
                        result = _rejected_result(base, zone_selection, reasons, warnings, substitution)
                        self.validate_result(result)
                        return result
                    safe_item = _running_output(item, zone_selection, fallback=False)
                else:
                    expected = next(
                        row for row in zone_selection["zones"] if row["zone"] == target_zone
                    )
                    expected_range = {
                        "minimum_bpm": expected["minimum_bpm"],
                        "maximum_bpm": expected["maximum_bpm"],
                    }
                    if target_range is not None and target_range != expected_range:
                        _add_reason(reasons, "target_bpm_mismatch", "block", tuple(zone_selection["source_revision_ids"]))
                        result = _rejected_result(base, zone_selection, reasons, warnings, substitution)
                        self.validate_result(result)
                        return result
                    safe_item = _running_output(item, zone_selection, fallback=False)
                    safe_item["target_bpm_range"] = expected_range
                if _high_intensity_rejection(
                    safe_item,
                    advice_date,
                    payload["quality_sessions"],
                    reasons,
                ):
                    result = _rejected_result(base, zone_selection, reasons, warnings, substitution)
                    self.validate_result(result)
                    return result
                status = (
                    "modified_for_safety"
                    if safe_item["target_bpm_range"] != item["target_bpm_range"]
                    else "accepted"
                )
            _add_reason(reasons, "recommendation_accepted", "info")
            result = {
                **base,
                "status": status,
                "safety_state": "warning" if warnings or status == "modified_for_safety" or any(row["severity"] == "warning" for row in reasons) else "normal",
                "professional_evaluation_recommended": False,
                "primary_items": [safe_item],
                "zone_selection": zone_selection,
                "substitution_assessment": substitution,
                "reasons": _sort_reasons(reasons),
                "warnings": _sort_reasons(warnings),
            }
        elif item["activity_kind"] in {"climbing", "strength"}:
            blocker_key = (
                "climbing_blocking_signal_kinds"
                if item["activity_kind"] == "climbing"
                else "strength_blocking_signal_kinds"
            )
            blockers = [
                row for row in active_signals if row["kind"] in _POLICY[blocker_key]
            ]
            if blockers:
                code = (
                    "climbing_recovery_insufficient"
                    if item["activity_kind"] == "climbing"
                    else "strength_recovery_insufficient"
                )
                revisions = tuple(_revision(row["source_revision_id"]) for row in blockers)
                _add_reason(reasons, code, "warning", revisions)
                result = {
                    **base,
                    "status": "modified_for_safety",
                    "safety_state": "warning",
                    "professional_evaluation_recommended": False,
                    "primary_items": [
                        _rest_for_safety(
                            tuple(sorted({row["kind"] for row in blockers})),
                            professional=False,
                            daily_activity_allowed=True,
                        )
                    ],
                    "zone_selection": zone_selection,
                    "substitution_assessment": substitution,
                    "reasons": _sort_reasons(reasons),
                    "warnings": _sort_reasons(warnings),
                }
            else:
                if item["activity_kind"] == "strength" and not set(
                    _POLICY["required_strength_stop_conditions"]
                ) <= set(item["stop_conditions"]):
                    _add_reason(reasons, "stop_conditions_incomplete", "block")
                    result = _rejected_result(base, zone_selection, reasons, warnings, substitution)
                    self.validate_result(result)
                    return result
                _add_reason(reasons, "recommendation_accepted", "info")
                accepted_item = deepcopy(item)
                if item["activity_kind"] == "strength":
                    accepted_item["movements"] = sorted(
                        accepted_item["movements"], key=lambda row: row["exercise_key"]
                    )
                result = {
                    **base,
                    "status": "accepted",
                    "safety_state": "warning" if warnings or any(row["severity"] == "warning" for row in reasons) else "normal",
                    "professional_evaluation_recommended": False,
                    "primary_items": [accepted_item],
                    "zone_selection": zone_selection,
                    "substitution_assessment": substitution,
                    "reasons": _sort_reasons(reasons),
                    "warnings": _sort_reasons(warnings),
                }
        else:
            _add_reason(reasons, "rest_selected", "info")
            result = {
                **base,
                "status": "accepted",
                "safety_state": "warning" if warnings or any(row["severity"] == "warning" for row in reasons) else "normal",
                "professional_evaluation_recommended": False,
                "primary_items": [deepcopy(item)],
                "zone_selection": zone_selection,
                "substitution_assessment": substitution,
                "reasons": _sort_reasons(reasons),
                "warnings": _sort_reasons(warnings),
            }
        self.validate_result(result)
        return result


def evaluate_training_safety(request: Mapping[str, Any]) -> dict[str, Any]:
    """Convenience pure entrypoint."""

    return TrainingSafetyRuleEngine().evaluate(request)
