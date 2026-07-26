"""One-shot Garmin collection tool.

The provider adapter is deliberately small: production can wrap the pinned
``garminconnect`` client while tests inject an in-memory transport.  All durable
state belongs in Foundation's data.db; this module never creates another DB.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import random
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime, time as datetime_time, timedelta
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Callable, Iterable, Literal, Protocol
from zoneinfo import ZoneInfo

import fitdecode
from jsonschema import Draft202012Validator
from .garmin_catalog import (
    CATALOG_VERSION,
    EXTRA_ROLES,
    HEALTH_RESOURCES,
    RESOURCE_CATALOG,
)
from .garmin_modes import CollectionModePlan, ResourceDateWindow, build_collection_mode_plan

COLLECTOR_VERSION = "1"
GARMINCONNECT_VERSION = "0.3.6"
PARSER_VERSION = "fitdecode-0.11.0"
ACCOUNT_PROFILE_SEMANTIC_VERSION = "account-profile-v1"
DEVICE_REFERENCE_SEMANTIC_VERSION = "device-reference-v1"
TZ = ZoneInfo("Asia/Singapore")

# Provider JSON is untrusted input.  These bounds are deliberately well above
# reviewed Garmin responses while keeping parser/field-catalog work finite.
PROVIDER_JSON_MAX_BYTES = 16 * 1024 * 1024
PROVIDER_JSON_MAX_DEPTH = 64
PROVIDER_JSON_MAX_CONTAINER_ITEMS = 100_000
PROVIDER_JSON_MAX_NODES = 1_000_000

# Garmin's climbing FIT profile stores the Font grade as a numeric raw value.
# Keep that raw value unchanged and expose only the reviewed display mapping.
_FONT_GRADE_DISPLAY = {0: "1", 2: "3", 3: "4", 4: "4+", 8: "5c", 10: "6a+"}

# L2-08's bounded canonical vocabulary.  Provider JSON remains immutable raw
# evidence; only these reviewed scalar facts are allowed into canonical tables.
# tuple entries are (canonical_key, raw_unit, canonical_unit, value_origin,
# source_field_path).
CANONICAL_SAMPLE_METRICS: dict[str, dict[str, tuple[str, str | None, str | None, str, str]]] = {
    "steps": {"steps": ("garmin.steps.count", "count", "count", "sensor_observed", "/steps"), "distanceMeters": ("garmin.steps.distance_m", "m", "m", "sensor_observed", "/distanceMeters")},
    "floors": {"floorsAscended": ("garmin.floors.ascended", "floors", "floors", "sensor_observed", "/floorsAscended")},
    "heart_rates": {"heartRate": ("garmin.heart_rate.bpm", "bpm", "bpm", "sensor_observed", "/heartRate")},
    "rhr": {"restingHeartRate": ("garmin.resting_heart_rate.bpm", "bpm", "bpm", "provider_derived", "/restingHeartRate")},
    "respiration": {"breathsPerMinute": ("garmin.respiration.breaths_per_minute", "breaths/min", "breaths/min", "sensor_observed", "/breathsPerMinute")},
    "spo2": {"spO2": ("garmin.spo2.percent", "%", "%", "sensor_observed", "/spO2")},
    "stress": {"stressLevel": ("garmin.stress.score", "score", "score", "sensor_observed", "/stressLevel")},
    "hrv": {"weeklyAvg": ("garmin.hrv.weekly_avg_ms", "ms", "ms", "provider_derived", "/weeklyAvg")},
    "body_battery": {"bodyBattery": ("garmin.body_battery.score", "score", "score", "provider_derived", "/bodyBattery")},
}
CANONICAL_SERIES_METRICS: dict[str, tuple[str, str, str, str, str]] = {
    "heart_rates": ("heartRateValues", "garmin.heart_rate.bpm", "bpm", "sensor_observed", "/heartRateValues/*/*"),
    "stress": ("stressValuesArray", "garmin.stress.score", "score", "sensor_observed", "/stressValuesArray/*/*"),
    "respiration": ("respirationValuesArray", "garmin.respiration.breaths_per_minute", "breaths/min", "sensor_observed", "/respirationValuesArray/*/*"),
    "spo2": ("spO2HourlyAverages", "garmin.spo2.percent", "%", "sensor_observed", "/spO2HourlyAverages/*/*"),
    "body_battery": ("bodyBatteryValuesArray", "garmin.body_battery.score", "score", "provider_derived", "/bodyBatteryValuesArray/*/*"),
}
DAILY_SCALAR_METRICS: dict[str, dict[str, tuple[str, str | None, str | None, str, str]]] = {
    "user_summary": {
        "steps": ("garmin.daily.steps", "count", "count", "provider_derived", "/steps"),
        "restingHeartRate": ("garmin.daily.resting_heart_rate_bpm", "bpm", "bpm", "provider_derived", "/restingHeartRate"),
    },
    "intensity_minutes": {"moderateIntensityMinutes": ("garmin.daily.moderate_intensity_minutes", "min", "min", "provider_derived", "/moderateIntensityMinutes")},
    "hydration": {"hydrationMl": ("garmin.daily.hydration_ml", "mL", "mL", "user_entered", "/hydrationMl")},
}
PHYSIOLOGY_SCALAR_METRICS: dict[str, dict[str, tuple[str, str | None, str | None, str, str]]] = {
    "blood_pressure": {
        "systolic": ("garmin.blood_pressure.systolic_mmhg", "mmHg", "mmHg", "provider_derived", "/systolic"),
        "diastolic": ("garmin.blood_pressure.diastolic_mmhg", "mmHg", "mmHg", "provider_derived", "/diastolic"),
    },
    "body_battery": {
        "charged": ("garmin.body_battery.charged", "score", "score", "provider_derived", "/charged"),
        "drained": ("garmin.body_battery.drained", "score", "score", "provider_derived", "/drained"),
    },
}

# L2-09B2's reviewed provider metrics.  These are Garmin-derived facts, not
# local recalculations.  Unknown fields stay in the immutable raw revision and
# field catalog, but never acquire an invented canonical key.
ADVANCED_PHYSIOLOGY_METRICS: dict[str, dict[str, tuple[str, str | None, str | None, str, str]]] = {
    "training_readiness": {"score": ("garmin.training_readiness.score", "score", "score", "provider_derived", "/score"), "trainingReadinessScore": ("garmin.training_readiness.score", "score", "score", "provider_derived", "/trainingReadinessScore")},
    "max_metrics": {"vo2Max": ("garmin.vo2_max.ml_per_kg_min", "ml/kg/min", "ml/kg/min", "provider_derived", "/vo2Max")},
    "lactate_threshold": {"lactateThresholdHeartRate": ("garmin.lactate_threshold.heart_rate_bpm", "bpm", "bpm", "provider_derived", "/lactateThresholdHeartRate"), "lactateThresholdPower": ("garmin.lactate_threshold.power_w", "W", "W", "provider_derived", "/lactateThresholdPower"), "lactateThresholdSpeed": ("garmin.lactate_threshold.speed_mps", "m/s", "m/s", "provider_derived", "/lactateThresholdSpeed")},
    "training_status": {"trainingStatusScore": ("garmin.training_status.score", "score", "score", "provider_derived", "/trainingStatusScore"), "acuteTrainingLoad": ("garmin.training_status.acute_load", "load", "load", "provider_derived", "/acuteTrainingLoad")},
    "running_tolerance": {"runningTolerance": ("garmin.running_tolerance.score", "score", "score", "provider_derived", "/runningTolerance"), "weeklyMileage": ("garmin.running_tolerance.weekly_distance_m", "m", "m", "provider_derived", "/weeklyMileage")},
    "endurance_score": {
        "enduranceScore": ("garmin.endurance_score", "score", "score", "provider_derived", "/enduranceScore"),
        "overallScore": ("garmin.endurance_score", "score", "score", "provider_derived", "/overallScore"),
    },
    "hill_score": {"hillScore": ("garmin.hill_score", "score", "score", "provider_derived", "/hillScore")},
    "race_predictions": {"predictionSeconds": ("garmin.race_prediction.seconds", "s", "s", "provider_predicted", "/predictionSeconds"), "time": ("garmin.race_prediction.seconds", "s", "s", "provider_predicted", "/time")},
    "fitness_age": {"fitnessAge": ("garmin.fitness_age.years", "year", "year", "provider_derived", "/fitnessAge")},
    "menstrual_day": {"cycleLength": ("garmin.menstrual.cycle_length_days", "day", "day", "provider_derived", "/cycleLength"), "periodLength": ("garmin.menstrual.period_length_days", "day", "day", "provider_derived", "/periodLength"), "predictedCycleLength": ("garmin.menstrual.predicted_cycle_length_days", "day", "day", "provider_predicted", "/predictedCycleLength")},
    "menstrual": {"cycleLength": ("garmin.menstrual.cycle_length_days", "day", "day", "provider_derived", "/cycleLength"), "periodLength": ("garmin.menstrual.period_length_days", "day", "day", "provider_derived", "/periodLength"), "predictedCycleLength": ("garmin.menstrual.predicted_cycle_length_days", "day", "day", "provider_predicted", "/predictedCycleLength")},
    "nutrition_food_log": {"calories": ("garmin.nutrition.calories_kcal", "kcal", "kcal", "user_entered", "/calories"), "protein": ("garmin.nutrition.protein_g", "g", "g", "user_entered", "/protein"), "carbohydrates": ("garmin.nutrition.carbohydrates_g", "g", "g", "user_entered", "/carbohydrates"), "fat": ("garmin.nutrition.fat_g", "g", "g", "user_entered", "/fat")},
    "nutrition_meals": {"calories": ("garmin.nutrition.calories_kcal", "kcal", "kcal", "user_entered", "/calories"), "protein": ("garmin.nutrition.protein_g", "g", "g", "user_entered", "/protein"), "carbohydrates": ("garmin.nutrition.carbohydrates_g", "g", "g", "user_entered", "/carbohydrates"), "fat": ("garmin.nutrition.fat_g", "g", "g", "user_entered", "/fat")},
    "nutrition_settings": {"calorieGoal": ("garmin.nutrition.calorie_goal_kcal", "kcal", "kcal", "user_entered", "/calorieGoal")},
}
ADVANCED_RESOURCES = frozenset(ADVANCED_PHYSIOLOGY_METRICS)

# L2-12 activity resources use catalog resource kinds for revisions/items and
# Foundation's frozen source-role vocabulary for activity provenance.
ACTIVITY_ENRICHMENTS: tuple[tuple[str, str], ...] = (
    ("activity_splits", "splits_json"),
    ("activity_typed_splits", "typed_splits_json"),
    ("activity_split_summaries", "split_summaries_json"),
    ("activity_exercise_sets", "exercise_sets_json"),
    ("activity_hr_zones", "hr_zones_json"),
    ("activity_power_zones", "power_zones_json"),
    ("activity_weather", "weather_json"),
    ("activity_gear", "gear_json"),
)
ACTIVITY_ENRICHMENT_RESOURCES = frozenset(resource for resource, _role in ACTIVITY_ENRICHMENTS)
ACTIVITY_ENRICHMENT_ROLES = {resource: role for resource, role in ACTIVITY_ENRICHMENTS}
ACTIVITY_RESOURCE_KINDS = frozenset({
    "activity_inventory", "activity_summary", "activity_fit",
    "activity_details_fallback", *ACTIVITY_ENRICHMENT_RESOURCES,
})
REQUEST_RESOURCE_KINDS = frozenset({*RESOURCE_CATALOG, "activities"})
ACCOUNT_RESOURCE_KINDS = frozenset(
    resource for resource, spec in RESOURCE_CATALOG.items()
    if spec.scope == "account"
)
ACTIVITY_CHART_MAX_POINTS = 2_000
ACTIVITY_CHART_MAX_POLYLINE_POINTS = 4_000

# Numeric reconciliation tolerances are absolute and intentionally explicit.
# Relative differences are still persisted as evidence.
ACTIVITY_RECONCILIATION_FIELDS: dict[str, tuple[str, str, float]] = {
    "distance_m": ("distance", "total_distance", 15.0),
    "elapsed_seconds": ("duration", "total_elapsed_time", 5.0),
    "timer_seconds": ("movingDuration", "total_timer_time", 5.0),
    "calories_kcal": ("calories", "total_calories", 1.0),
    "aerobic_training_effect": ("aerobicTrainingEffect", "total_training_effect", 0.1),
    "anaerobic_training_effect": ("anaerobicTrainingEffect", "total_anaerobic_training_effect", 0.1),
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def stable_json(value: Any) -> bytes:
    """Encode already-reviewed JSON values without lossy coercion."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _invalid_provider_json() -> GarminError:
    return GarminError("provider_json_invalid")


def canonical_provider_json(payload: Any) -> bytes:
    """Validate a Python provider value and return its stable JSON bytes."""
    validate_provider_json_payload(payload)
    try:
        canonical = stable_json(payload)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise _invalid_provider_json() from exc
    if len(canonical) > PROVIDER_JSON_MAX_BYTES:
        raise _invalid_provider_json()
    return canonical


def parse_provider_json_bytes(payload: bytes) -> tuple[Any, bytes]:
    """Strictly parse one UTF-8 JSON text and return value + canonical bytes."""
    if type(payload) is not bytes or len(payload) > PROVIDER_JSON_MAX_BYTES:
        raise _invalid_provider_json()
    if payload.startswith(b"\xef\xbb\xbf"):
        raise _invalid_provider_json()

    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _invalid_provider_json()
            result[key] = value
        return result

    def reject_constant(_constant: str) -> Any:
        raise _invalid_provider_json()

    try:
        text = payload.decode("utf-8", errors="strict")
        parsed = json.loads(
            text,
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_constant,
        )
    except GarminError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, OverflowError, RecursionError) as exc:
        raise _invalid_provider_json() from exc
    return parsed, canonical_provider_json(parsed)


_PROVIDER_CREDENTIAL_KEYS = frozenset({
    # HTTP authorization and bearer material.
    "authorization", "authorizationbearer", "authorizationheader",
    "authheader", "bearer", "bearerauthorization", "proxyauthorization",
    # OAuth/session/anti-forgery token values.  Metadata such as token expiry
    # and token counts is deliberately not included.
    "token", "accesstoken", "refreshtoken", "idtoken", "identitytoken",
    "oauthtoken", "authtoken", "bearertoken", "sessiontoken", "csrftoken",
    "xsrftoken", "jwttoken", "tokensecret",
    # Password and passcode values.
    "password", "passwd", "passcode", "clientpassword", "accountpassword",
    "userpassword", "garminpassword", "mfapasscode", "onetimepasscode",
    "otppasscode",
    # Client/API/shared secrets and API keys.
    "secret", "clientsecret", "oauthclientsecret", "apisecret",
    "sharedsecret", "consumersecret", "signingsecret", "apikey",
    "clientapikey", "publicapikey", "privateapikey", "apiaccesskey",
    "accesskey", "secretkey",
    # Credential containers and cookie/JWT values.
    "credential", "credentials", "clientcredential", "clientcredentials",
    "oauthcredential", "oauthcredentials", "serviceaccountcredentials",
    "cookie", "cookies", "sessioncookie", "sessioncookies", "authcookie",
    "authcookies", "authenticationcookie", "setcookie", "cookieheader", "jwt",
})

_PROVIDER_CREDENTIAL_FAMILIES = (
    ("api", "key"),
    ("client", "secret"),
    ("access", "token"),
    ("refresh", "token"),
    ("identity", "token"),
    ("id", "token"),
    ("oauth", "token"),
    ("auth", "token"),
    ("bearer", "token"),
    ("session", "token"),
    ("csrf", "token"),
    ("xsrf", "token"),
    ("jwt", "token"),
    ("token", "secret"),
    ("client", "credentials"),
    ("oauth", "credentials"),
    ("service", "account", "credentials"),
    ("session", "cookie"),
    ("auth", "cookie"),
    ("authentication", "cookie"),
    ("authorization",),
    ("bearer",),
    ("token",),
    ("password",),
    ("passwd",),
    ("passcode",),
    ("secret",),
    ("credential",),
    ("credentials",),
    ("cookie",),
    ("cookies",),
    ("jwt",),
)
_PROVIDER_CREDENTIAL_VALUE_SUFFIXES = frozenset({
    "value", "values", "data", "header", "string", "credential", "credentials",
})
_PROVIDER_CREDENTIAL_NORMALIZED_PREFIXES = frozenset({
    "", "x", "garmin", "provider", "vendor", "http", "request", "response",
    "header", "client", "account", "user", "oauth", "auth", "session", "service",
})
_PROVIDER_CREDENTIAL_NORMALIZED_SUFFIXES = frozenset({
    "", "value", "values", "data", "header", "string", "credential", "credentials",
})
_PROVIDER_STRONG_NORMALIZED_FAMILIES = frozenset({
    "apikey", "clientsecret", "accesstoken", "refreshtoken", "identitytoken",
    "idtoken", "oauthtoken", "authtoken", "bearertoken", "sessiontoken",
    "csrftoken", "xsrftoken", "jwttoken", "tokensecret", "clientcredentials",
    "oauthcredentials", "serviceaccountcredentials", "sessioncookie",
    "authcookie", "authenticationcookie",
})


def _normalise_provider_json_key(key: Any) -> str:
    """Make case and JSON-key separators irrelevant to the reviewed policy."""
    return "".join(character for character in str(key).casefold() if character.isalnum())


def _provider_json_key_words(key: Any) -> tuple[str, ...]:
    """Split separators and camel/acronym transitions into reviewed key words."""
    text = str(key)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return tuple(part.casefold() for part in re.findall(r"[A-Za-z0-9]+", text))


def _has_provider_credential_key(key: Any) -> bool:
    normalized = _normalise_provider_json_key(key)
    if normalized in _PROVIDER_CREDENTIAL_KEYS:
        return True

    words = _provider_json_key_words(key)
    for family in _PROVIDER_CREDENTIAL_FAMILIES:
        width = len(family)
        for index in range(len(words) - width + 1):
            if words[index:index + width] != family:
                continue
            suffix = words[index + width:]
            if not suffix or all(part in _PROVIDER_CREDENTIAL_VALUE_SUFFIXES for part in suffix):
                return True

    # A few providers collapse header/vendor names to one lowercase word.  The
    # finite wrapper sets catch those forms without turning substring matching
    # into a heuristic (for example, apiKeynote and secretory remain benign).
    return any(
        normalized == prefix + family + suffix
        for family in _PROVIDER_STRONG_NORMALIZED_FAMILIES
        for prefix in _PROVIDER_CREDENTIAL_NORMALIZED_PREFIXES
        for suffix in _PROVIDER_CREDENTIAL_NORMALIZED_SUFFIXES
    )


def _has_explicit_authorization_value(value: str) -> bool:
    """Recognise an HTTP Basic/Bearer value without guessing opaque secrets."""
    candidate = value.strip()
    lowered = candidate.casefold()
    if lowered.startswith("authorization"):
        remainder = candidate[len("authorization"):]
        if not remainder or remainder[0] not in " \t:=":
            return False
        candidate = remainder.lstrip(" \t:=")
    pieces = candidate.split(None, 1)
    if len(pieces) != 2:
        return False
    scheme, credential = pieces[0].casefold(), pieces[1].strip()
    if not credential or any(character.isspace() for character in credential):
        return False
    if scheme == "bearer":
        return True
    if scheme != "basic" or len(credential) < 4:
        return False
    # Basic credentials are base64/base64url.  This is a syntax check tied to
    # the explicit HTTP scheme, not a high-entropy value heuristic.
    return all(character.isalnum() or character in "+/=_-" for character in credential)


def validate_provider_json_payload(payload: Any) -> Any:
    """Fail closed before *any* Garmin JSON archive or canonical write.

    Raw evidence must retain provider semantics such as names and symptom text,
    but access credentials are operational secrets rather than health facts.
    This single guard is deliberately called by the repository archive boundary
    so account, daily, range and activity JSON cannot bypass it.
    """
    stack: list[tuple[Any, int, bool]] = [(payload, 0, False)]
    active_containers: set[int] = set()
    nodes = 0
    while stack:
        value, depth, exiting = stack.pop()
        if exiting:
            active_containers.remove(id(value))
            continue
        nodes += 1
        if nodes > PROVIDER_JSON_MAX_NODES or depth > PROVIDER_JSON_MAX_DEPTH:
            raise _invalid_provider_json()
        value_type = type(value)
        if value is None or value_type in {bool, int}:
            continue
        if value_type is float:
            if not math.isfinite(value):
                raise _invalid_provider_json()
            continue
        if value_type is str:
            if _has_explicit_authorization_value(value):
                raise GarminError("provider_payload_quarantined")
            continue
        if value_type is dict:
            identity = id(value)
            if identity in active_containers or len(value) > PROVIDER_JSON_MAX_CONTAINER_ITEMS:
                raise _invalid_provider_json()
            active_containers.add(identity)
            stack.append((value, depth, True))
            for key, child in value.items():
                if type(key) is not str:
                    raise _invalid_provider_json()
                if _has_provider_credential_key(key):
                    raise GarminError("provider_payload_quarantined")
                stack.append((child, depth + 1, False))
            continue
        if value_type is list:
            identity = id(value)
            if identity in active_containers or len(value) > PROVIDER_JSON_MAX_CONTAINER_ITEMS:
                raise _invalid_provider_json()
            active_containers.add(identity)
            stack.append((value, depth, True))
            stack.extend((child, depth + 1, False) for child in value)
            continue
        # Tuples, custom scalar/container subclasses, datetimes, sets and
        # arbitrary provider objects are not JSON and must never be stringified.
        raise _invalid_provider_json()
    return payload


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_provider_error_code(code: str) -> str:
    """Accept only reviewed machine codes; provider text is never durable."""
    if code in _DURABLE_PROVIDER_ERROR_CODES:
        return code
    return "provider_error"


# This is deliberately a finite allowlist, not a character-pattern check.
# Additions require a review of every durable error surface (receipt, runs,
# items, gaps and capabilities).
_DURABLE_PROVIDER_ERROR_CODES = frozenset({
    "auth_required", "forbidden", "not_available", "not_supported", "not_enabled",
    "rate_limited", "timeout", "dns", "network", "connection_reset",
    "cooldown_active", "cooldown_corrupt", "provider_error",
    "http_400", "http_401", "http_403", "http_404", "http_408", "http_429",
    "http_500", "http_502", "http_503", "http_504",
    "parse_or_project_failed", "account_project_failed", "invalid_fit",
    "activity_parse_or_project_failed", "activity_summary_project_failed",
    "activity_extra_project_failed", "identity_mismatch", "verified_identity_required",
    "unknown_device_reference",
    "activity_inventory_count_invalid", "activity_inventory_count_drift",
    "activity_inventory_page_invalid", "activity_inventory_page_size_mismatch",
    "activity_inventory_duplicate_ids", "activity_inventory_paging_loop",
    "activity_inventory_id_invalid", "activity_summary_invalid",
    "activity_summary_identity_mismatch", "activity_summary_time_invalid",
    "activity_summary_type_invalid",
    "interactive_provider_required", "transport_not_configured",
    "garminconnect_not_installed", "unsupported_garmin_client_structure",
    "raw_object_corrupt", "raw_cleanup_claim_replaced", "raw_cleanup_temp_replaced",
    "provider_payload_quarantined", "provider_json_invalid",
    "fit_zip_invalid", "fit_zip_unsafe_member", "fit_zip_limits_exceeded",
    "fit_ambiguous", "fit_missing", "fit_crc_invalid", "fit_no_session",
    "fit_identity_mismatch", "fit_ambiguous_session", "fit_parse_failed",
    "activity_enrichment_invalid", "activity_enrichment_identity_mismatch",
    "activity_enrichment_binding_mismatch", "activity_chart_invalid",
    "activity_chart_empty", "activity_reconcile_failed",
    # Local L2-14 repair/audit evidence codes.  They are intentionally
    # machine-only labels, never provider text or raw payload fragments.
    "raw_integrity", "coverage_error", "cursor_crosses_gap",
    "unmapped_field_signature", "activity_summary_missing",
    "offline_repair_failed", "capability_cooldown",
})


class GarminError(RuntimeError):
    def __init__(self, code: str, *, http_status: int | None = None, retry_after: int | None = None) -> None:
        super().__init__(code)
        self.code, self.http_status, self.retry_after = code, http_status, retry_after


@dataclass(frozen=True)
class RetryClassification:
    """Provider-error outcome at a logical item boundary; never includes payload."""

    status: Literal["retry", "deferred", "auth_required", "forbidden", "not_available", "failed"]
    retryable: bool


def classify_garmin_error(
    error: GarminError,
    *,
    allows_404: bool = False,
    inline_retry_after_max_seconds: int = 120,
    rate_limit_fallback_seconds: int = 900,
) -> RetryClassification:
    """Classify only status/code, never provider response text or credentials."""
    status = error.http_status
    if error.code == "cooldown_active":
        return RetryClassification("deferred", False)
    if status == 401:
        return RetryClassification("auth_required", False)
    if status == 403:
        return RetryClassification("forbidden", False)
    if status == 404:
        return RetryClassification("not_available" if allows_404 else "failed", False)
    if status == 429:
        retry_after = (
            error.retry_after
            if error.retry_after is not None
            else rate_limit_fallback_seconds
        )
        return RetryClassification(
            "deferred"
            if retry_after > inline_retry_after_max_seconds
            else "retry",
            True,
        )
    if status == 408 or status in {500, 502, 503, 504}:
        return RetryClassification("retry", True)
    if status is not None and 400 <= status < 500:
        return RetryClassification("failed", False)
    if error.code in {"network", "dns", "connection_reset", "timeout", "provider_error"}:
        return RetryClassification("retry", True)
    return RetryClassification("failed", False)


class GarminTransport(Protocol):
    def login(self) -> None: ...
    def fetch_health(self, resource_kind: str, local_date: str) -> Any: ...
    def fetch_range(self, resource_kind: str, start_local_date: str, end_local_date: str) -> Any: ...
    def fetch_account(self, resource_kind: str, provider_device_id: str | None = None) -> Any: ...
    def activity_count(self) -> int: ...
    def activity_page(self, offset: int, limit: int) -> Any: ...
    def list_activities(self, start: str | None, through: str | None) -> Iterable[dict[str, Any]]: ...
    def activity_summary(self, activity_id: str) -> dict[str, Any]: ...
    def activity_original(self, activity_id: str) -> bytes: ...
    def activity_extra(self, activity_id: str, role: str) -> Any: ...
    def identity(self) -> str: ...


IGNORED_RESOURCES = {"get_stats": "alias:user_summary", "get_stats_and_body": "client_combination", "get_stress_data": "alias:stress", "get_morning_training_readiness": "subset:training_readiness"}


@dataclass(frozen=True)
class GarminConfig:
    database_path: Path
    raw_root: Path
    state_root: Path
    history_start_date: str | None
    subject_key: str = "default"
    region: Literal["global", "cn"] = "cn"
    lookback_days: int = 14
    max_repair_items_per_incremental: int = 100
    request_min_interval_ms: int = 500
    request_interval_jitter_ms: int = 0
    request_timeout_seconds: int = 30
    max_attempts: int = 5
    retry_base_seconds: int = 2
    retry_max_seconds: int = 60
    inline_retry_after_max_seconds: int = 120
    rate_limit_fallback_seconds: int = 900


@dataclass(frozen=True)
class SyncRequest:
    mode: Literal["auth", "full", "incremental", "snapshot", "repair", "audit", "status"]
    health_from_local_date: str | None = None
    through_local_date: str | None = None
    snapshot_local_date: str | None = None
    resource_kinds: tuple[str, ...] = ()
    activity_ids: tuple[str, ...] = ()
    repair_strategy: Literal["auto", "refetch", "reparse", "reconcile"] | None = None
    invocation_id: str | None = None


@dataclass
class SyncReceipt:
    schema_version: str = "1"
    run_id: str | None = None
    mode: str = ""
    status: str = "failed"
    requested_range: dict[str, str | None] = field(default_factory=dict)
    effective_range: dict[str, str | None] = field(default_factory=dict)
    coverage_state: str | None = None
    counts: dict[str, int] = field(default_factory=lambda: {k: 0 for k in ("fetched", "empty", "unchanged", "revised", "failed", "deferred", "not_available", "not_enabled")})
    complete_through_by_resource: dict[str, str | None] = field(default_factory=dict)
    open_gap_count: int = 0
    next_retry_at_utc: str | None = None
    errors: list[dict[str, str]] = field(default_factory=list)
    started_at_utc: str = field(default_factory=utc_now)
    completed_at_utc: str | None = None

    def json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, allow_nan=False)


class GarminRepository:
    """All mutable Garmin state, with short transactions only."""
    def __init__(self, config: GarminConfig) -> None:
        self.config = config

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.config.database_path}?mode=ro" if readonly else self.config.database_path, isolation_level=None, uri=readonly)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def subject(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT id FROM data_subjects WHERE subject_key=?", (self.config.subject_key,)).fetchone()
        if row:
            return int(row[0])
        conn.execute("INSERT INTO data_subjects(subject_key,timezone,created_at_utc) VALUES(?,?,?)", (self.config.subject_key, "Asia/Singapore", utc_now()))
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    def start_run(self, conn: sqlite3.Connection, request: SyncRequest, subject_id: int, receipt: SyncReceipt) -> int:
        if request.invocation_id is None:
            raise ValueError("invocation_id_required")
        invocation = request.invocation_id
        existing = conn.execute("SELECT id,run_id,status FROM garmin_sync_runs WHERE invocation_id=?", (invocation,)).fetchone()
        if existing:
            full = conn.execute("SELECT * FROM garmin_sync_runs WHERE id=?", (existing["id"],)).fetchone()
            receipt.run_id, receipt.status = full["run_id"], full["status"]
            receipt.started_at_utc = full["started_at_utc"]
            receipt.requested_range = {"from": full["requested_from_local_date"], "through": full["requested_through_local_date"]}
            receipt.effective_range = {"from": full["actual_from_local_date"], "through": full["actual_through_local_date"]}
            receipt.counts.update({"fetched":full["fetched_count"],"empty":full["empty_count"],"unchanged":full["unchanged_count"],"revised":full["revised_count"],"failed":full["failed_count"],"deferred":full["deferred_count"]})
            for item_status, count in conn.execute(
                """SELECT status,count(*) AS count
                   FROM garmin_sync_items
                   WHERE garmin_sync_run_id=? AND status IN ('not_available','not_supported','not_enabled')
                   GROUP BY status""",
                (existing["id"],),
            ):
                # Receipt v1 has no separate not_supported counter.  It is a
                # completed unavailable outcome, deterministically folded
                # into not_available both live and during replay.
                counter = "not_available" if item_status == "not_supported" else item_status
                receipt.counts[counter] += int(count)
            fallback_used = conn.execute(
                """SELECT 1 FROM garmin_sync_items
                   WHERE garmin_sync_run_id=?
                     AND resource_kind='activity_details_fallback'
                     AND stage='project'
                     AND (
                         status IN ('revised','unchanged','succeeded')
                         OR (
                             status='failed'
                             AND error_code IN (
                                 'activity_chart_empty','activity_chart_invalid'
                             )
                         )
                     )
                   LIMIT 1""",
                (existing["id"],),
            ).fetchone()
            receipt.coverage_state = (
                "partial"
                if (
                    full["mode"] == "snapshot"
                    or fallback_used is not None
                    or full["status"] in {"partial", "deferred", "failed"}
                )
                else "complete" if full["status"] == "succeeded" else None
            )
            receipt.complete_through_by_resource = {
                row["resource_kind"]: row["complete_through_local_date"]
                for row in conn.execute(
                    """SELECT resource_kind,complete_through_local_date
                       FROM garmin_sync_cursors WHERE subject_id=?""",
                    (subject_id,),
                )
            }
            receipt.open_gap_count = int(
                conn.execute(
                    """SELECT count(*) FROM garmin_sync_gaps
                       WHERE subject_id=? AND status IN ('open','deferred')""",
                    (subject_id,),
                ).fetchone()[0]
            )
            receipt.next_retry_at_utc, receipt.completed_at_utc = full["next_retry_at_utc"], full["completed_at_utc"]
            if full["error_summary"]: receipt.errors.append({"code":full["error_summary"],"resource":"garmin","logical_object_key":"garmin:run","summary":full["error_summary"]})
            if full["status"] == "started":
                conn.execute(
                    """UPDATE garmin_sync_items
                       SET status='pending',completed_at_utc=NULL,next_retry_at_utc=NULL
                       WHERE garmin_sync_run_id=? AND status='running'""",
                    (existing["id"],),
                )
                # An interrupted run has not reached ``finish_run``, so its
                # aggregate columns still contain their initial zeros. Rebuild
                # only completed-success counters before skipping durable work.
                # Failed/deferred items are retried below; carrying their old
                # counts forward would incorrectly make a successful resume
                # finish partial/deferred.
                receipt.counts.update({key: 0 for key in receipt.counts})
                for item_status, count in conn.execute(
                    """SELECT status,count(*) AS count
                         FROM garmin_sync_items
                        WHERE garmin_sync_run_id=?
                          AND status IN (
                              'fetched','empty','unchanged','revised',
                              'not_available','not_supported',
                              'not_enabled'
                          )
                        GROUP BY status""",
                    (existing["id"],),
                ):
                    counter = (
                        "not_available"
                        if item_status == "not_supported"
                        else item_status
                    )
                    receipt.counts[counter] += int(count)
            return int(existing["id"])
        run_id = f"gr-{uuid.uuid4()}"
        receipt.run_id, receipt.status = run_id, "started"
        conn.execute("""INSERT INTO garmin_sync_runs(run_id,invocation_id,subject_id,mode,requested_from_local_date,requested_through_local_date,resource_catalog_version,collector_version,garminconnect_version,parser_version,status,started_at_utc)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (run_id, invocation, subject_id, request.mode if request.mode != "auth" and request.mode != "status" else "audit", request.health_from_local_date, request.through_local_date or request.snapshot_local_date, CATALOG_VERSION, COLLECTOR_VERSION, GARMINCONNECT_VERSION, PARSER_VERSION, "started", receipt.started_at_utc))
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    def finish_run(self, conn: sqlite3.Connection, run_id: int, receipt: SyncReceipt, actual_from: str | None, actual_through: str | None) -> None:
        receipt.completed_at_utc = utc_now()
        # A later successful stage proves that its provider fetch completed.
        # Close any such predecessor defensively so a future adapter omission
        # cannot publish a succeeded run with a lingering `running` item.
        conn.execute(
            """UPDATE garmin_sync_items AS fetch
               SET status='fetched',completed_at_utc=?,error_code=NULL,
                   error_summary=NULL,next_retry_at_utc=NULL
               WHERE fetch.garmin_sync_run_id=? AND fetch.stage='fetch'
                 AND fetch.status='running'
                 AND EXISTS(
                     SELECT 1 FROM garmin_sync_items AS later
                     WHERE later.garmin_sync_run_id=fetch.garmin_sync_run_id
                       AND later.resource_kind=fetch.resource_kind
                       AND later.logical_object_key=fetch.logical_object_key
                       AND later.stage IN ('extract','parse','project','reconcile','validate')
                       AND later.status IN ('fetched','empty','unchanged','revised','succeeded',
                                            'not_available','not_enabled','not_supported')
                 )""",
            (receipt.completed_at_utc, run_id),
        )
        remaining = int(
            conn.execute(
                """SELECT count(*) FROM garmin_sync_items
                   WHERE garmin_sync_run_id=? AND status='running'""",
                (run_id,),
            ).fetchone()[0]
        )
        if remaining:
            conn.execute(
                """UPDATE garmin_sync_items
                   SET status='failed',error_code='interrupted',
                       error_summary='interrupted',completed_at_utc=?
                   WHERE garmin_sync_run_id=? AND status='running'""",
                (receipt.completed_at_utc, run_id),
            )
            receipt.counts["failed"] += remaining
            if receipt.status == "succeeded":
                receipt.status = "partial"
        conn.execute("""UPDATE garmin_sync_runs SET status=?,actual_from_local_date=?,actual_through_local_date=?,fetched_count=?,empty_count=?,unchanged_count=?,revised_count=?,failed_count=?,deferred_count=?,next_retry_at_utc=?,error_summary=?,completed_at_utc=? WHERE id=?""", (receipt.status, actual_from, actual_through, receipt.counts["fetched"], receipt.counts["empty"], receipt.counts["unchanged"], receipt.counts["revised"], receipt.counts["failed"], receipt.counts["deferred"], receipt.next_retry_at_utc, safe_provider_error_code(receipt.errors[0]["code"]) if receipt.errors else None, receipt.completed_at_utc, run_id))

    def item(self, conn: sqlite3.Connection, run_id: int, resource: str, key: str, stage: str, status: str, *, revision_id: int | None = None, error: GarminError | None = None, next_retry: str | None = None, increment_attempt: bool = True) -> None:
        allowed={"pending":{"running","failed","deferred"},"running":{"fetched","empty","unchanged","revised","succeeded","failed","deferred","not_available","not_enabled","not_supported","forbidden"},"deferred":{"running","failed"},"failed":{"running"}}
        row=conn.execute("SELECT status FROM garmin_sync_items WHERE garmin_sync_run_id=? AND resource_kind=? AND logical_object_key=? AND stage=?",(run_id,resource,key,stage)).fetchone()
        terminal = {
            "fetched", "empty", "unchanged", "revised", "succeeded", "failed",
            "deferred", "not_available", "not_enabled", "not_supported",
            "forbidden",
        }
        replay_allowed = (
            row is not None
            and row["status"] in terminal
            and status in terminal | {"running"}
        )
        if row and row["status"]!=status and status not in allowed.get(row["status"],set()) and not replay_allowed: raise ValueError("invalid_item_transition")
        now = utc_now(); completed = now if status in {"fetched","empty","unchanged","revised","succeeded","failed","deferred","not_available","not_enabled","not_supported","forbidden"} else None
        error_code = self._safe_error_code(error.code) if error else None
        conn.execute("""INSERT INTO garmin_sync_items(garmin_sync_run_id,resource_kind,logical_object_key,stage,status,attempt_count,http_status,error_code,error_summary,next_retry_at_utc,source_revision_id,started_at_utc,completed_at_utc)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(garmin_sync_run_id,resource_kind,logical_object_key,stage) DO UPDATE SET status=excluded.status,attempt_count=garmin_sync_items.attempt_count+?,http_status=excluded.http_status,error_code=excluded.error_code,error_summary=excluded.error_summary,next_retry_at_utc=excluded.next_retry_at_utc,source_revision_id=excluded.source_revision_id,completed_at_utc=excluded.completed_at_utc""", (run_id, resource, key, stage, status, 1 if increment_attempt else 0, error.http_status if error else None, error_code, error_code if error else None, next_retry, revision_id, now, completed, 1 if increment_attempt else 0))

    @staticmethod
    def _safe_error_code(code: str) -> str:
        return safe_provider_error_code(code)

    def gap(self, conn: sqlite3.Connection, subject: int, resource: str, key: str, day: str, stage: str, reason: str, *, end_day: str | None = None, deferred: bool = False, next_retry: str | None = None, revision: int | None = None) -> None:
        now = utc_now(); status = "deferred" if deferred else "open"; reason = safe_provider_error_code(reason)
        conn.execute("""INSERT INTO garmin_sync_gaps(subject_id,resource_kind,logical_object_key,window_start_local_date,window_end_local_date,stage,reason_code,status,next_retry_at_utc,first_seen_at_utc,last_attempt_at_utc,source_revision_id)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(subject_id,resource_kind,logical_object_key,window_start_local_date,window_end_local_date,stage) WHERE status IN ('open','deferred') DO UPDATE SET reason_code=excluded.reason_code,status=excluded.status,next_retry_at_utc=excluded.next_retry_at_utc,last_attempt_at_utc=excluded.last_attempt_at_utc,attempt_count=garmin_sync_gaps.attempt_count+1""", (subject, resource, key, day, end_day or day, stage, reason, status, next_retry, now, now, revision))

    def resolve_gaps(
        self,
        conn: sqlite3.Connection,
        subject: int,
        resource: str,
        day: str,
        *,
        logical_object_key: str | None = None,
        stages: Iterable[str] | None = None,
    ) -> None:
        """Resolve a day-level gap scope, optionally narrowed to one object.

        Health resources intentionally use the original resource/day scope.
        Object resources such as activity FIT must also pass their logical key
        so one successful object cannot hide another object's unresolved gap.
        """
        now = utc_now()
        filters = [
            "subject_id=?",
            "resource_kind=?",
            "window_start_local_date<=?",
            "window_end_local_date>=?",
            "status IN ('open','deferred')",
        ]
        parameters: list[Any] = [subject, resource, day, day]
        if logical_object_key is not None:
            filters.append("logical_object_key=?")
            parameters.append(logical_object_key)
        if stages is not None:
            stage_values = tuple(dict.fromkeys(stages))
            if not stage_values:
                return
            filters.append(f"stage IN ({','.join('?' for _ in stage_values)})")
            parameters.extend(stage_values)
        conn.execute(
            f"""UPDATE garmin_sync_gaps
                SET status='resolved',resolved_at_utc=?,last_attempt_at_utc=?
                WHERE {' AND '.join(filters)}""",
            (now, now, *parameters),
        )

    def capability(self, conn: sqlite3.Connection, subject: int, resource: str, state: str, *, reason: str | None = None, next_probe: str | None = None, environment_key: str = "default") -> None:
        if state not in {"supported","not_enabled","not_available","not_supported","forbidden","unknown"}: raise ValueError("invalid_capability_state")
        reason = safe_provider_error_code(reason) if reason else None
        now=utc_now(); conn.execute("INSERT INTO garmin_resource_capabilities(subject_id,environment_key,resource_kind,capability_state,reason_code,first_checked_at_utc,last_checked_at_utc,next_probe_at_utc) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(subject_id,environment_key,resource_kind) DO UPDATE SET capability_state=excluded.capability_state,reason_code=excluded.reason_code,last_checked_at_utc=excluded.last_checked_at_utc,next_probe_at_utc=excluded.next_probe_at_utc",(subject,environment_key,resource,state,reason,now,now,next_probe))

    @staticmethod
    def _verify_dirfd(fd: int) -> None:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("unsafe_raw_path")

    @staticmethod
    def _verify_filefd(fd: int, payload: bytes, *, expected_size: int | None = None) -> None:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size != (len(payload) if expected_size is None else expected_size):
            raise ValueError("raw_object_corrupt")
        os.lseek(fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        if digest(b"".join(chunks)) != digest(payload):
            raise ValueError("raw_object_corrupt")

    def _open_raw_rootfd(self) -> int:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            before = os.lstat(self.config.raw_root)
        except OSError as exc:
            raise ValueError("unsafe_raw_path") from exc
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode) or before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != 0o700:
            raise ValueError("unsafe_raw_path")
        try:
            fd = os.open(self.config.raw_root, flags)
        except OSError as exc:
            raise ValueError("unsafe_raw_path") from exc
        try:
            self._verify_dirfd(fd)
            after = os.lstat(self.config.raw_root)
            current = os.fstat(fd)
            if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino) or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError("unsafe_raw_path")
        except Exception:
            os.close(fd)
            raise
        return fd

    def _open_child_dirfd(self, parent_fd: int, name: str, *, create: bool) -> int:
        if not name or name in {".", ".."} or "/" in name:
            raise ValueError("unsafe_raw_path")
        created = False
        try:
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            if not create:
                raise ValueError("raw_object_corrupt") from None
            try:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
                created = True
            except FileExistsError:
                pass
            except OSError as exc:
                raise ValueError("unsafe_raw_path") from exc
            try:
                before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except OSError as exc:
                raise ValueError("unsafe_raw_path") from exc
        except OSError as exc:
            raise ValueError("unsafe_raw_path") from exc
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
            raise ValueError("unsafe_raw_path")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            child_fd = os.open(name, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise ValueError("unsafe_raw_path") from exc
        try:
            self._verify_dirfd(child_fd)
            after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            current = os.fstat(child_fd)
            if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino) or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError("unsafe_raw_path")
            # A newly named directory cannot be used as a durable raw path
            # until its parent directory entry is durable.  This intentionally
            # fails closed before any raw_objects transaction is opened.
            if created:
                os.fsync(parent_fd)
        except Exception:
            os.close(child_fd)
            raise
        return child_fd

    def _cleanup_owned_temp(
        self,
        directory_fd: int,
        temporary_name: str,
        *,
        device: int,
        inode: int,
        payload: bytes,
    ) -> None:
        """Remove only an inode we still own, without temp-name stat/unlink.

        The first operation moves the random temporary entry to an independent
        cleanup claim.  A hostile replacement of the old temp name is never
        inspected or unlinked.  A replacement of the claim is detected by the
        descriptor-backed identity sequence and intentionally retained.
        """
        claim = f".cleanup-{uuid.uuid4()}"
        try:
            # Claim names are random and private to this invocation.  Check
            # before rename so a pre-existing unexpected claim is never
            # overwritten; a later replacement is caught below and preserved.
            try:
                os.stat(claim, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ValueError("raw_cleanup_claim_exists")
            os.rename(temporary_name, claim, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
        except FileNotFoundError as exc:
            raise ValueError("raw_cleanup_interrupted") from exc

        try:
            before = os.stat(claim, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode) or (before.st_dev, before.st_ino) != (device, inode):
                raise ValueError("raw_cleanup_claim_replaced")
            fd = os.open(claim, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
            try:
                opened = os.fstat(fd)
                self._verify_filefd(fd, payload)
                after = os.stat(claim, dir_fd=directory_fd, follow_symlinks=False)
                if (
                    (opened.st_dev, opened.st_ino) != (device, inode)
                    or (after.st_dev, after.st_ino) != (device, inode)
                    or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
                ):
                    raise ValueError("raw_cleanup_claim_replaced")
            finally:
                os.close(fd)
            # The only unlink follows a successful full descriptor-backed
            # verification of the random claim, never a stat(temp)/unlink.
            os.unlink(claim, dir_fd=directory_fd)
            os.fsync(directory_fd)
            # A rename removes the old temporary name.  If it has reappeared
            # while cleaning, it is somebody else's replacement: preserve it
            # and fail before any database publication.
            try:
                os.stat(temporary_name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ValueError("raw_cleanup_temp_replaced")
        except FileNotFoundError as exc:
            raise ValueError("raw_cleanup_claim_replaced") from exc

    def _open_relative_rawfd(self, relative_path: str) -> int:
        parts = Path(relative_path).parts
        if not parts or parts[0] != "raw" or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("raw_object_corrupt")
        root_fd = self._open_raw_rootfd()
        current = root_fd
        try:
            for part in parts[1:-1]:
                child = self._open_child_dirfd(current, part, create=False)
                os.close(current)
                current = child
            before = os.stat(parts[-1], dir_fd=current, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode):
                raise ValueError("raw_object_corrupt")
            fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=current)
            after = os.stat(parts[-1], dir_fd=current, follow_symlinks=False)
            opened = os.fstat(fd)
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino) or (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
                os.close(fd)
                raise ValueError("raw_object_corrupt")
            return fd
        except OSError as exc:
            raise ValueError("raw_object_corrupt") from exc
        finally:
            os.close(current)

    def store_raw(self, resource: str, payload: bytes, suffix: str, media_type: str) -> tuple[int, str]:
        """Append immutable provider evidence to the permanent raw archive.

        Final JSON and FIT objects are content-addressed and never removed or
        overwritten by collection, repair, audit, or replay.  The only cleanup
        in this write path is for a private temporary inode after the durable
        content-addressed file has been verified.
        """
        allowed_types = {
            "json": "application/json",
            "fit": "application/octet-stream",
        }
        if allowed_types.get(suffix) != media_type:
            raise ValueError("raw_type_not_allowed")
        if suffix == "json":
            # Validate at the lowest public raw boundary, but preserve the
            # provider's exact bytes as required by the raw evidence contract.
            parse_provider_json_bytes(payload)
        sha = digest(payload)
        now = utc_now()
        existing_connection = self.connect()
        try:
            existing = existing_connection.execute(
                """SELECT id,relative_path,size_bytes,media_type
                   FROM raw_objects WHERE sha256=?""",
                (sha,),
            ).fetchone()
        finally:
            existing_connection.close()
        if existing is not None:
            try:
                stored_fd = self._open_relative_rawfd(str(existing["relative_path"]))
                try:
                    self._verify_filefd(stored_fd, payload, expected_size=int(existing["size_bytes"]))
                finally:
                    os.close(stored_fd)
            except ValueError as exc:
                raise ValueError("raw_object_corrupt") from exc
            if existing["size_bytes"] != len(payload) or existing["media_type"] != media_type:
                raise ValueError("raw_object_corrupt")
            return int(existing["id"]), sha

        date_path = datetime.now(UTC).strftime("%Y/%m")
        root_fd = self._open_raw_rootfd()
        dir_fds = [root_fd]
        final_name = f"{sha}.{suffix}"
        try:
            for part in ("garmin", "fit" if suffix == "fit" else "json", *date_path.split("/")):
                child_fd = self._open_child_dirfd(dir_fds[-1], part, create=True)
                dir_fds.append(child_fd)
            directory_fd = dir_fds[-1]
            try:
                before_final = os.stat(final_name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                before_final = None
            if before_final is not None:
                if stat.S_ISLNK(before_final.st_mode):
                    raise ValueError("raw_object_corrupt")
                try:
                    final_fd = os.open(final_name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
                except OSError as exc:
                    raise ValueError("raw_object_corrupt") from exc
                try:
                    opened_final = os.fstat(final_fd)
                    self._verify_filefd(final_fd, payload)
                    after_final = os.stat(final_name, dir_fd=directory_fd, follow_symlinks=False)
                    if (before_final.st_dev, before_final.st_ino) != (opened_final.st_dev, opened_final.st_ino) or (after_final.st_dev, after_final.st_ino) != (opened_final.st_dev, opened_final.st_ino):
                        raise ValueError("raw_object_corrupt")
                finally:
                    os.close(final_fd)
            else:
                temporary_name = f".tmp-{uuid.uuid4()}"
                tmp_fd = os.open(temporary_name, os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=directory_fd)
                # Capture the owned temporary inode before any potentially
                # failing write.  Cleanup may only unlink this exact inode.
                tmp_inode: int | None = None
                tmp_device: int | None = None
                written = 0
                try:
                    tmp_info = os.fstat(tmp_fd)
                    if not stat.S_ISREG(tmp_info.st_mode) or tmp_info.st_uid != os.getuid():
                        raise ValueError("unsafe_raw_path")
                    tmp_inode, tmp_device = tmp_info.st_ino, tmp_info.st_dev
                    os.fchmod(tmp_fd, 0o600)
                    while written < len(payload):
                        count = os.write(tmp_fd, payload[written:])
                        if count <= 0:
                            raise OSError("raw_short_write")
                        written += count
                    os.fsync(tmp_fd)
                    self._verify_filefd(tmp_fd, payload)
                    tmp_inode = os.fstat(tmp_fd).st_ino
                    won = False
                    try:
                        os.link(temporary_name, final_name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
                        won = True
                    except FileExistsError:
                        pass
                    os.fsync(directory_fd)
                    before_final = os.stat(final_name, dir_fd=directory_fd, follow_symlinks=False)
                    if stat.S_ISLNK(before_final.st_mode):
                        raise ValueError("raw_object_corrupt")
                    final_fd = os.open(final_name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
                    try:
                        self._verify_filefd(final_fd, payload)
                        final_stat = os.fstat(final_fd)
                        after_final = os.stat(final_name, dir_fd=directory_fd, follow_symlinks=False)
                        if (before_final.st_dev, before_final.st_ino) != (final_stat.st_dev, final_stat.st_ino) or (after_final.st_dev, after_final.st_ino) != (final_stat.st_dev, final_stat.st_ino):
                            raise ValueError("raw_object_corrupt")
                        if won and (final_stat.st_dev, final_stat.st_ino) != (tmp_device, tmp_inode):
                            raise ValueError("raw_object_corrupt")
                    finally:
                        os.close(final_fd)
                finally:
                    os.close(tmp_fd)
                    if tmp_inode is not None and tmp_device is not None:
                        self._cleanup_owned_temp(
                            directory_fd,
                            temporary_name,
                            device=tmp_device,
                            inode=tmp_inode,
                            payload=payload[:written],
                        )
            rel = str(Path("raw") / "garmin" / ("fit" if suffix == "fit" else "json") / date_path / final_name)
        finally:
            for fd in reversed(dir_fds):
                os.close(fd)
        conn = self.connect()
        try:
            # Do not leave a raw_objects row behind if the second trusted
            # descriptor verification detects a concurrent name swap.
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR IGNORE INTO raw_objects(sha256,relative_path,media_type,size_bytes,provider,resource_kind,original_name,fetched_at_utc) VALUES(?,?,?,?,?,?,?,?)", (sha, rel, media_type, len(payload), "garmin", resource, None, now))
            row = conn.execute(
                """SELECT id,relative_path,size_bytes,media_type
                   FROM raw_objects WHERE sha256=?""",
                (sha,),
            ).fetchone()
            raw_id = int(row["id"])
            stored_fd = self._open_relative_rawfd(str(row["relative_path"]))
            try:
                self._verify_filefd(stored_fd, payload, expected_size=int(row["size_bytes"]))
            finally:
                os.close(stored_fd)
            if (
                row["size_bytes"] != len(payload)
                or row["media_type"] != media_type
            ):
                raise ValueError("raw_object_corrupt")
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        return raw_id, sha

    def publish_revision(
        self,
        conn: sqlite3.Connection,
        resource: str,
        provider_id: str,
        raw_id: int,
        raw_sha: str,
        projector: Callable[[int], None] | None = None,
        *,
        payload_hash: str | None = None,
        profile_version: str | None = None,
    ) -> tuple[int, bool]:
        if conn.in_transaction:
            raise ValueError("publisher_requires_clean_connection")
        raw = conn.execute(
            "SELECT sha256 FROM raw_objects WHERE id=?",
            (raw_id,),
        ).fetchone()
        if raw is None or raw["sha256"] != raw_sha:
            raise ValueError("raw_revision_mismatch")
        semantic_hash = payload_hash or raw_sha
        current = conn.execute("SELECT id,payload_hash,profile_version,revision_no FROM source_revisions WHERE provider='garmin' AND resource_kind=? AND provider_object_id=? AND is_current=1", (resource, provider_id)).fetchone()
        if current and current["payload_hash"] == semantic_hash and current["profile_version"] == profile_version:
            return int(current["id"]), False
        # Receiving provider evidence and accepting it as canonical are two
        # different durability boundaries.  A parser failure must leave an
        # immutable, non-current revision available for offline reparse.
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = conn.execute("SELECT id,payload_hash,profile_version FROM source_revisions WHERE provider='garmin' AND resource_kind=? AND provider_object_id=? AND is_current=1", (resource, provider_id)).fetchone()
            if current and current["payload_hash"] == semantic_hash and current["profile_version"] == profile_version:
                conn.execute("COMMIT")
                return int(current["id"]), False
            # Only a previously *unparsed* received revision may be reused.
            # Returning from a tombstone to an old payload is a provider
            # correction and needs a new revision/current transition.
            received = conn.execute("SELECT id FROM source_revisions WHERE provider='garmin' AND resource_kind=? AND provider_object_id=? AND payload_hash=? AND profile_version IS ? AND parsed_at_utc IS NULL ORDER BY revision_no DESC LIMIT 1", (resource, provider_id, semantic_hash, profile_version)).fetchone()
            if received is None:
                rev = int(conn.execute("SELECT coalesce(max(revision_no),0)+1 FROM source_revisions WHERE provider='garmin' AND resource_kind=? AND provider_object_id=?", (resource, provider_id)).fetchone()[0])
                conn.execute("INSERT INTO source_revisions(provider,resource_kind,provider_object_id,revision_no,raw_object_id,payload_hash,parser_name,parser_version,profile_version,is_current,parsed_at_utc) VALUES(?,?,?,?,?,?,?,?,?,0,NULL)", ("garmin", resource, provider_id, rev, raw_id, semantic_hash, "garmin", PARSER_VERSION, profile_version))
                revision = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            else:
                revision = int(received["id"])
            # Commit the received revision before canonical parsing.  The
            # following transaction is deliberately separate and may roll
            # back without erasing raw provenance.
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = conn.execute("SELECT id,payload_hash,profile_version FROM source_revisions WHERE provider='garmin' AND resource_kind=? AND provider_object_id=? AND is_current=1", (resource, provider_id)).fetchone()
            if current and current["payload_hash"] == semantic_hash and current["profile_version"] == profile_version:
                conn.execute("COMMIT")
                return int(current["id"]), False
            if projector:
                projector(revision)
            if current:
                conn.execute("UPDATE source_revisions SET is_current=0 WHERE id=?", (current["id"],))
            conn.execute("UPDATE source_revisions SET is_current=1,parsed_at_utc=? WHERE id=?", (utc_now(), revision))
            conn.execute("COMMIT")
            return revision, True
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    def archive(
        self,
        conn: sqlite3.Connection,
        resource: str,
        provider_id: str,
        payload: bytes,
        suffix: str,
        media_type: str,
        projector: Callable[[int], None] | None = None,
        *,
        semantic_payload: bytes | None = None,
        profile_version: str | None = None,
    ) -> tuple[int, int, bool]:
        semantic_hash: str | None = None
        if suffix == "json":
            _, canonical = parse_provider_json_bytes(
                semantic_payload if semantic_payload is not None else payload
            )
            semantic_hash = digest(canonical)
        raw_id, raw_sha = self.store_raw(resource, payload, suffix, media_type)
        revision, changed = self.publish_revision(
            conn, resource, provider_id, raw_id, raw_sha, projector,
            payload_hash=semantic_hash,
            profile_version=profile_version,
        )
        return raw_id, revision, changed

    def coverage(self, conn: sqlite3.Connection, subject: int, resource: str, day: str, state: str, revision: int | None, count: int, *, snapshot: bool = False) -> None:
        """Record coverage without turning a snapshot observation into history.

        Foundation coverage intentionally retains completed-day history.  A
        snapshot is different: its only date-level claim is ``partial``, so a
        repeat must update that one observation rather than append duplicate
        partial rows.
        """
        if snapshot:
            row = conn.execute(
                """SELECT id FROM resource_coverage WHERE subject_id=? AND provider='garmin'
                   AND resource_kind=? AND local_date=? AND availability_state='partial'
                   ORDER BY id DESC LIMIT 1""",
                (subject, resource, day),
            ).fetchone()
            if row is not None:
                conn.execute(
                    """UPDATE resource_coverage SET record_count=?,source_revision_id=?,observed_at_utc=?
                       WHERE id=?""",
                    (count, revision, utc_now(), row["id"]),
                )
                return
        conn.execute("INSERT INTO resource_coverage(subject_id,provider,resource_kind,local_date,availability_state,record_count,source_revision_id,observed_at_utc) VALUES(?,?,?,?,?,?,?,?)", (subject, "garmin", resource, day, state, count, revision, utc_now()))

    def fields(self, conn: sqlite3.Connection, resource: str, payload: Any) -> None:
        def walk(value: Any, path: str = ""):
            if isinstance(value, dict):
                for key, child in value.items(): yield from walk(child, f"{path}/{key}")
            elif isinstance(value, list):
                for child in value: yield from walk(child, f"{path}/*")
            else: yield path or "/", type(value).__name__
        now=utc_now()
        for path, kind in walk(payload):
            conn.execute("INSERT INTO source_field_catalog(provider,resource_kind,field_path,observed_type,first_seen_at_utc,last_seen_at_utc,mapping_state) VALUES(?,?,?,?,?,?,?) ON CONFLICT(provider,resource_kind,field_path) DO UPDATE SET last_seen_at_utc=excluded.last_seen_at_utc,observed_type=excluded.observed_type", ("garmin",resource,path,kind,now,now,"unknown"))

    def map_field(self, conn: sqlite3.Connection, resource: str, field_path: str, canonical_metric_key: str) -> None:
        """Mark only reviewed source paths as mapped; drift remains unknown."""
        conn.execute(
            """UPDATE source_field_catalog
               SET mapping_state='mapped',canonical_metric_key=?
               WHERE provider='garmin' AND resource_kind=? AND field_path=?""",
            (canonical_metric_key, resource, field_path),
        )

    def passthrough_field(self, conn: sqlite3.Connection, resource: str, field_path: str) -> None:
        conn.execute(
            """UPDATE source_field_catalog SET mapping_state='known_passthrough',canonical_metric_key=NULL
               WHERE provider='garmin' AND resource_kind=? AND field_path=?""",
            (resource, field_path),
        )

    def advance_cursor(self, conn: sqlite3.Connection, subject: int, resource: str, through: str, run_id: int, *, partial: bool = False) -> None:
        if partial: return
        current=conn.execute("SELECT complete_through_local_date FROM garmin_sync_cursors WHERE subject_id=? AND resource_kind=? AND cursor_grain='local_date'",(subject,resource)).fetchone()
        if current and current[0]: candidate=date.fromisoformat(current[0])+timedelta(days=1)
        else:
            first=conn.execute("SELECT min(local_date) FROM resource_coverage WHERE subject_id=? AND provider='garmin' AND resource_kind=? AND local_date<=?",(subject,resource,through)).fetchone()[0]
            candidate=date.fromisoformat(first) if first else None
        latest=None
        while candidate and candidate.isoformat()<=through:
            day=candidate.isoformat(); coverage=conn.execute("SELECT availability_state FROM resource_coverage WHERE subject_id=? AND provider='garmin' AND resource_kind=? AND local_date=? ORDER BY id DESC LIMIT 1",(subject,resource,day)).fetchone(); gap=conn.execute("SELECT 1 FROM garmin_sync_gaps WHERE subject_id=? AND resource_kind=? AND window_start_local_date<=? AND window_end_local_date>=? AND status IN ('open','deferred')",(subject,resource,day,day)).fetchone()
            if not coverage or coverage[0] not in {"fetched","empty","not_enabled","not_available","not_supported"} or gap: break
            latest=day; candidate+=timedelta(days=1)
        if latest: conn.execute("INSERT INTO garmin_sync_cursors(subject_id,resource_kind,cursor_grain,complete_through_local_date,last_success_at_utc,last_run_id,catalog_version) VALUES(?,?,?,?,?,?,?) ON CONFLICT(subject_id,resource_kind,cursor_grain) DO UPDATE SET complete_through_local_date=excluded.complete_through_local_date,last_success_at_utc=excluded.last_success_at_utc,last_run_id=excluded.last_run_id,catalog_version=excluded.catalog_version",(subject,resource,"local_date",latest,utc_now(),run_id,CATALOG_VERSION))


class GarminCollectionTool:
    def __init__(self, config: GarminConfig, transport: GarminTransport | None = None, *, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], datetime] = lambda: datetime.now(TZ), monotonic: Callable[[], float] = time.monotonic, rng: Callable[[], float] | None = None) -> None:
        self.config, self.transport, self.repo, self.sleep, self.clock, self.monotonic = config, transport, GarminRepository(config), sleep, clock, monotonic
        self.rng = rng or random.Random().random
        self._last_request: float | None = None

    def execute(self, request: SyncRequest) -> SyncReceipt:
        if request.invocation_id is None: request=replace(request,invocation_id=f"garmin-{uuid.uuid4()}")
        receipt = SyncReceipt(mode=request.mode, requested_range={"from": request.health_from_local_date, "through": request.through_local_date or request.snapshot_local_date}, effective_range={"from": None, "through": None})
        self._validate(request)
        if request.mode == "status": return self._validated_receipt(self._status(receipt))
        if request.mode == "auth": return self._validated_receipt(self._auth(receipt))
        lock = self.config.state_root / "locks" / "garmin.lock"; lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if not self._recover_stale_lock(lock, request.invocation_id):
                receipt.status, receipt.completed_at_utc = "lock_busy", utc_now(); return self._validated_receipt(receipt)
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, stable_json({"pid": os.getpid(), "invocation_id": request.invocation_id, "started_at_utc": receipt.started_at_utc}))
            os.fsync(fd)
            return self._validated_receipt(self._execute_locked(request, receipt))
        finally:
            os.close(fd); lock.unlink(missing_ok=True)

    def _recover_stale_lock(
        self,
        lock: Path,
        requested_invocation_id: str | None = None,
    ) -> bool:
        """Clear a dead-PID lock only when resuming its exact invocation.

        A matching started run is intentionally recoverable because
        ``start_run`` resets an interrupted running item to pending and reuses
        the same run.  A different invocation must remain ``lock_busy`` so it
        cannot strand or overlap the interrupted run.
        """
        try:
            payload=json.loads(lock.read_text()); pid=int(payload["pid"]); invocation_id=payload.get("invocation_id")
            os.kill(pid, 0); return False
        except ProcessLookupError:
            pass
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return False
        conn=self.repo.connect()
        try:
            active=conn.execute("SELECT 1 FROM garmin_sync_runs WHERE invocation_id=? AND status='started'",(invocation_id,)).fetchone() if invocation_id else None
            if active and requested_invocation_id != invocation_id:
                return False
        finally: conn.close()
        lock.unlink(missing_ok=True); return True

    def _execute_locked(self, request: SyncRequest, receipt: SyncReceipt) -> SyncReceipt:
        conn = self.repo.connect()
        run = 0
        actual_start: date | None = None
        actual_through: date | None = None
        try:
            subject = self.repo.subject(conn); run = self.repo.start_run(conn, request, subject, receipt)
            if receipt.status != "started": return receipt
            # Reparse and reconcile are deliberately offline operations.  In
            # particular they must remain usable while a token is expired or
            # Garmin is unavailable; the immutable raw object is the input.
            repair_strategy = self._repair_strategy(conn, subject, request, receipt)
            offline_repair = request.mode == "repair" and repair_strategy in {"reparse", "reconcile"}
            if request.mode == "repair" and repair_strategy == "deferred":
                receipt.status = "deferred"
                self.repo.finish_run(conn, run, receipt, None, None)
                return receipt
            if not offline_repair:
                identity = conn.execute("SELECT 1 FROM subject_identities WHERE subject_id=? AND provider='garmin' AND identity_kind='account' AND is_verified=1", (subject,)).fetchone()
                if identity is None:
                    receipt.status = "auth_required"; receipt.errors.append({"code":"verified_identity_required","resource":"auth","logical_object_key":"garmin:account:identity","summary":"authenticate before sync"}); self.repo.finish_run(conn, run, receipt, None, None); return receipt
                try:
                    self._transport().login()
                    actual = self._identity_hmac(self._transport().identity())
                    verified = conn.execute("SELECT 1 FROM subject_identities WHERE subject_id=? AND provider='garmin' AND identity_kind='account' AND identity_hmac=? AND is_verified=1", (subject, actual)).fetchone()
                    if verified is None:
                        receipt.status="failed"; receipt.errors.append({"code":"identity_mismatch","resource":"auth","logical_object_key":"garmin:account:identity","summary":"identity mismatch"}); self.repo.finish_run(conn,run,receipt,None,None); return receipt
                except GarminError as exc:
                    receipt.status="auth_required" if exc.http_status==401 else "failed"; receipt.errors.append({"code":exc.code,"resource":"auth","logical_object_key":"garmin:account:identity","summary":"provider authentication failed"}); self.repo.finish_run(conn,run,receipt,None,None); return receipt
            today = self._today_local()
            yesterday = today - timedelta(days=1)
            if request.mode == "repair" and offline_repair:
                actual_through = date.fromisoformat(request.through_local_date) if request.through_local_date else yesterday
                actual_start = date.fromisoformat(
                    request.health_from_local_date
                    or self.config.history_start_date
                    or actual_through.isoformat()
                )
                receipt.effective_range = {"from": actual_start.isoformat(), "through": actual_through.isoformat()}
                self._offline_repair(conn, run, subject, replace(request, repair_strategy=repair_strategy), receipt)
            elif request.mode in {"full", "incremental", "snapshot"}:
                plan = self._build_mode_plan(conn, subject, request, today)
                prior_gap_ceiling = (
                    int(conn.execute(
                        "SELECT coalesce(max(id),0) FROM garmin_sync_gaps"
                    ).fetchone()[0])
                    if request.mode == "incremental"
                    else 0
                )
                actual_start, actual_through = plan.effective_start, plan.effective_through
                receipt.effective_range = {
                    "from": actual_start.isoformat(),
                    "through": actual_through.isoformat(),
                }
                if plan.snapshot:
                    receipt.coverage_state = "partial"
                self._account_basics(conn, run, subject, plan.effective_through, request, receipt)
                self._account_b1(conn, run, subject, plan.effective_through, request, receipt)
                selected = set(request.resource_kinds)
                for window in plan.health_windows:
                    scoped = replace(request, resource_kinds=(window.resource_kind,))
                    self._health(
                        conn, run, subject, window.start, window.through,
                        scoped, receipt,
                    )
                # Explicit account-only repair is a closed provider scope: it
                # must not enumerate activities merely because activities are
                # normally part of a full collection invocation.
                activity_scope = {
                    "activity_inventory", "activity_summary", "activity_fit",
                    "activity_details_fallback", "activities",
                    *ACTIVITY_ENRICHMENT_RESOURCES,
                }
                if request.activity_ids or not selected or selected.intersection(activity_scope):
                    self._activities(
                        conn, run, subject, plan.activity_start,
                        plan.activity_through, request, receipt,
                        not selected or "activity_fit" in selected,
                    )
                if request.mode == "incremental":
                    self._process_due_gaps(
                        conn, run, subject, request, receipt,
                        plan.activity_start, plan.activity_through,
                        prior_gap_ceiling,
                    )
                if not plan.snapshot:
                    for window in plan.health_windows:
                        self.repo.advance_cursor(
                            conn, subject, window.resource_kind,
                            window.through.isoformat(), run,
                        )
                    if receipt.coverage_state != "partial":
                        receipt.coverage_state = (
                            "complete"
                            if self._health_windows_complete(conn, subject, plan.health_windows)
                            else "partial"
                        )
            elif request.mode == "audit":
                actual_through = date.fromisoformat(request.through_local_date) if request.through_local_date else today
                actual_start = date.fromisoformat(
                    request.health_from_local_date
                    or self.config.history_start_date
                    or actual_through.isoformat()
                )
                receipt.effective_range = {"from": actual_start.isoformat(), "through": actual_through.isoformat()}
                self._audit(conn, subject, receipt, actual_start, actual_through)
            elif request.mode == "repair":
                actual_through = date.fromisoformat(request.through_local_date) if request.through_local_date else yesterday
                actual_start = date.fromisoformat(
                    request.health_from_local_date
                    or self.config.history_start_date
                    or actual_through.isoformat()
                )
                receipt.effective_range = {"from": actual_start.isoformat(), "through": actual_through.isoformat()}
                self._account_basics(conn, run, subject, actual_through, request, receipt)
                self._account_b1(conn, run, subject, actual_through, request, receipt)
                selected = set(request.resource_kinds)
                if not selected or selected.intersection(HEALTH_RESOURCES):
                    self._health(conn, run, subject, actual_start, actual_through, request, receipt)
                activity_scope = {
                    "activity_inventory", "activity_summary", "activity_fit",
                    "activity_details_fallback", "activities",
                    *ACTIVITY_ENRICHMENT_RESOURCES,
                }
                if request.activity_ids or not selected or selected.intersection(activity_scope):
                    self._activities(
                        conn, run, subject, actual_start, actual_through,
                        request, receipt, not selected or "activity_fit" in selected,
                    )
            receipt.status = "deferred" if receipt.counts["deferred"] else (
                "partial"
                if receipt.counts["failed"] or (
                    request.mode != "snapshot" and receipt.coverage_state == "partial"
                )
                else "succeeded"
            )
            receipt.open_gap_count = int(conn.execute("SELECT count(*) FROM garmin_sync_gaps WHERE subject_id=? AND status IN ('open','deferred')", (subject,)).fetchone()[0])
            receipt.complete_through_by_resource = {r["resource_kind"]: r["complete_through_local_date"] for r in conn.execute("SELECT resource_kind,complete_through_local_date FROM garmin_sync_cursors WHERE subject_id=?", (subject,))}
            if receipt.next_retry_at_utc is None:
                pending_retry = conn.execute(
                    """SELECT min(next_retry_at_utc) FROM garmin_sync_gaps
                       WHERE subject_id=? AND status='deferred'
                         AND next_retry_at_utc IS NOT NULL""",
                    (subject,),
                ).fetchone()[0]
                receipt.next_retry_at_utc = pending_retry
            self.repo.finish_run(
                conn, run, receipt,
                actual_start.isoformat() if actual_start else None,
                actual_through.isoformat() if actual_through else None,
            )
            return receipt
        except GarminError as exc:
            receipt.status = "auth_required" if exc.http_status == 401 else "failed"; receipt.errors.append({"code": exc.code, "resource": "garmin", "logical_object_key":"garmin:run","summary": exc.code})
            try: self.repo.finish_run(conn, run, receipt, actual_start.isoformat() if actual_start else None, actual_through.isoformat() if actual_through else None)
            except Exception: receipt.completed_at_utc = utc_now()
            return receipt
        finally: conn.close()

    def _today_local(self) -> date:
        value = self.clock()
        if value.tzinfo is not None:
            value = value.astimezone(TZ)
        return value.date()

    def _build_mode_plan(
        self,
        conn: sqlite3.Connection,
        subject: int,
        request: SyncRequest,
        today: date,
    ) -> CollectionModePlan:
        selected = set(request.resource_kinds)
        health_resources = tuple(
            resource for resource in HEALTH_RESOURCES
            if not selected or resource in selected
        )
        cursors = {
            row["resource_kind"]: row["complete_through_local_date"]
            for row in conn.execute(
                """SELECT resource_kind,complete_through_local_date
                   FROM garmin_sync_cursors
                   WHERE subject_id=? AND cursor_grain='local_date'""",
                (subject,),
            )
        }
        history_start = (
            request.health_from_local_date
            or self.config.history_start_date
            or today.isoformat()
        )
        return build_collection_mode_plan(
            mode=request.mode,  # type: ignore[arg-type]
            today_local=today,
            history_start_date=history_start,
            requested_health_from=request.health_from_local_date,
            requested_through=request.through_local_date,
            requested_snapshot_date=request.snapshot_local_date,
            health_resources=health_resources,
            complete_through_by_resource=cursors,
            lookback_days=self.config.lookback_days,
        )

    @staticmethod
    def _health_windows_complete(
        conn: sqlite3.Connection,
        subject: int,
        windows: Iterable[ResourceDateWindow],
    ) -> bool:
        closed_states = {
            "fetched", "empty", "not_enabled", "not_available", "not_supported",
        }
        for window in windows:
            rows = conn.execute(
                """SELECT local_date,availability_state
                   FROM resource_coverage
                   WHERE subject_id=? AND provider='garmin'
                     AND resource_kind=? AND local_date>=? AND local_date<=?
                   ORDER BY id""",
                (
                    subject, window.resource_kind,
                    window.start.isoformat(), window.through.isoformat(),
                ),
            )
            latest = {row["local_date"]: row["availability_state"] for row in rows}
            expected = (window.through - window.start).days + 1
            if len(latest) != expected or any(
                state not in closed_states for state in latest.values()
            ):
                return False
            blocking_gap = conn.execute(
                """SELECT 1 FROM garmin_sync_gaps
                   WHERE subject_id=? AND resource_kind=?
                     AND status IN ('open','deferred')
                     AND window_start_local_date<=?
                     AND window_end_local_date>=?
                   LIMIT 1""",
                (
                    subject, window.resource_kind,
                    window.through.isoformat(), window.start.isoformat(),
                ),
            ).fetchone()
            if blocking_gap is not None:
                return False
        return True

    def _process_due_gaps(
        self,
        conn: sqlite3.Connection,
        run: int,
        subject: int,
        request: SyncRequest,
        receipt: SyncReceipt,
        activity_start: date,
        activity_through: date,
        prior_gap_ceiling: int,
    ) -> None:
        """Retry a bounded set of due gaps through the normal resource pipeline."""
        limit = self.config.max_repair_items_per_incremental
        if limit <= 0:
            return
        now = self._now_utc().isoformat().replace("+00:00", "Z")
        gaps = list(conn.execute(
            """SELECT id,resource_kind,logical_object_key,
                      window_start_local_date,window_end_local_date,stage
               FROM garmin_sync_gaps
               WHERE id<=?
                 AND (
                     status='open'
                     OR (
                         status='deferred'
                         AND (next_retry_at_utc IS NULL OR next_retry_at_utc<=?)
                     )
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM garmin_sync_items item
                     WHERE item.garmin_sync_run_id=?
                       AND item.resource_kind=garmin_sync_gaps.resource_kind
                       AND item.logical_object_key=garmin_sync_gaps.logical_object_key
                 )
               ORDER BY priority DESC,
                        CASE WHEN next_retry_at_utc IS NULL THEN 0 ELSE 1 END,
                        next_retry_at_utc,id
               LIMIT ?""",
            (prior_gap_ceiling, now, run, limit),
        ))
        activity_resources = {
            "activity_inventory", "activity_summary", "activity_fit",
            "activity_details_fallback", "activities",
            *ACTIVITY_ENRICHMENT_RESOURCES,
        }
        for gap in gaps:
            still_due = conn.execute(
                """SELECT 1 FROM garmin_sync_gaps
                   WHERE id=? AND (
                       status='open'
                       OR (
                           status='deferred'
                           AND (next_retry_at_utc IS NULL OR next_retry_at_utc<=?)
                       )
                   )""",
                (gap["id"], now),
            ).fetchone()
            if still_due is None:
                continue
            try:
                start = date.fromisoformat(gap["window_start_local_date"])
                through = date.fromisoformat(gap["window_end_local_date"])
            except (TypeError, ValueError):
                continue
            if start > through:
                continue
            resource = str(gap["resource_kind"])
            if resource in HEALTH_RESOURCES:
                scoped = replace(
                    request,
                    resource_kinds=(resource,),
                    activity_ids=(),
                )
                self._health(
                    conn, run, subject, start, through, scoped, receipt,
                )
                continue
            if resource not in activity_resources:
                continue
            logical_key = str(gap["logical_object_key"])
            activity_id = self._activity_id_from_key(logical_key)
            selected_resource = (
                "activity_summary" if resource == "activities" else resource
            )
            scoped = replace(
                request,
                resource_kinds=(selected_resource,),
                activity_ids=(activity_id,) if activity_id else (),
            )
            self._activities(
                conn, run, subject,
                start if activity_id else activity_start,
                through if activity_id else activity_through,
                scoped, receipt,
                selected_resource == "activity_fit",
            )

    @staticmethod
    def _activity_id_from_key(logical_key: str) -> str | None:
        prefix = "garmin:activity:"
        if not logical_key.startswith(prefix):
            return None
        value = logical_key[len(prefix):].strip()
        return value if value and ":" not in value else None

    def _now_utc(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=TZ)
        return value.astimezone(UTC)

    def _classify(self, error: GarminError, *, allows_404: bool = False) -> RetryClassification:
        return classify_garmin_error(
            error,
            allows_404=allows_404,
            inline_retry_after_max_seconds=self.config.inline_retry_after_max_seconds,
            rate_limit_fallback_seconds=self.config.rate_limit_fallback_seconds,
        )

    def _next_retry(self, error: GarminError, attempt: int) -> str:
        seconds = error.retry_after
        if seconds is None:
            # Garmin documents no Retry-After as a long cooldown.  It grows
            # between separate attempts while retaining a bounded value.
            seconds = min(
                86_400,
                self.config.rate_limit_fallback_seconds * (2 ** attempt),
            )
        return (self._now_utc() + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")

    def _cooldown_error(self, conn: sqlite3.Connection | None, subject: int | None, resource: str | None, key: str | None) -> GarminError | None:
        if conn is None or subject is None or resource is None or key is None:
            return None
        row = conn.execute(
            """SELECT next_retry_at_utc FROM garmin_sync_gaps
               WHERE subject_id=? AND resource_kind=? AND logical_object_key=?
                 AND status='deferred' AND next_retry_at_utc IS NOT NULL
               ORDER BY id DESC LIMIT 1""",
            (subject, resource, key),
        ).fetchone()
        if row is None:
            return None
        try:
            due = datetime.fromisoformat(row["next_retry_at_utc"].replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return GarminError("cooldown_corrupt")
        remaining = (due - self._now_utc()).total_seconds()
        return GarminError("cooldown_active", http_status=429, retry_after=max(1, int(remaining))) if remaining > 0 else None

    def _call(self, fn: Callable[[], Any], *, conn: sqlite3.Connection | None = None, run: int | None = None, subject: int | None = None, resource: str | None = None, key: str | None = None, stage: str = "fetch", allows_404: bool = False) -> Any:
        """Execute one provider call with controlled retry and durable attempts."""
        cooldown = self._cooldown_error(conn, subject, resource, key)
        if cooldown is not None:
            raise cooldown
        last: GarminError | None = None
        refreshed = False
        for attempt in range(self.config.max_attempts):
            try:
                now = self.monotonic()
                interval = 0.0
                if self._last_request is not None:
                    target_interval = (
                        self.config.request_min_interval_ms
                        + self.config.request_interval_jitter_ms * self.rng()
                    ) / 1000
                    interval = target_interval - (now - self._last_request)
                    if interval > 0:
                        self.sleep(interval)
                # Record the time before invoking so failed requests also
                # participate in the global pseudo-random interval.
                self._last_request = now + max(0.0, interval)
                if conn is not None and run is not None and resource and key:
                    self.repo.item(conn, run, resource, key, stage, "running")
                return fn()
            except GarminError as exc:
                last = exc
                # A persisted long-rate-limit cooldown is never converted
                # into an inline wait just because less than 120 seconds now
                # remain; the provider call must not be made before its due
                # timestamp.
                if exc.code == "cooldown_active":
                    raise exc
                classification = self._classify(exc, allows_404=allows_404)
                if exc.http_status == 401 and not refreshed:
                    refreshed = True
                    try:
                        self._transport().login()
                    except GarminError:
                        raise GarminError("auth_required", http_status=401) from None
                    continue
                if classification.status != "retry" or attempt + 1 == self.config.max_attempts:
                    raise exc
                if exc.http_status == 429:
                    # Short Retry-After is honoured precisely; long cooldowns
                    # were rejected by the classification above.
                    self.sleep(
                        float(
                            exc.retry_after
                            if exc.retry_after is not None
                            else self.config.rate_limit_fallback_seconds
                        )
                    )
                else:
                    delay = min(self.config.retry_max_seconds, self.config.retry_base_seconds * (2 ** attempt) + self.rng())
                    self.sleep(delay)
        raise last or GarminError("unknown")

    _ACCOUNT_BASIC_RESOURCES = ("user_profile", "user_profile_settings", "devices")
    _ACCOUNT_B1_RESOURCES = ("primary_device", "device_settings", "device_last_used", "personal_records", "cycling_ftp", "pregnancy")
    _PROFILE_SETTING_FIELDS = {
        "measurementSystem", "timeFormat", "weekStartDay", "heartRateMethod",
    }

    def _account_basics(self, conn: sqlite3.Connection, run: int, subject: int, day: date, request: SyncRequest, receipt: SyncReceipt) -> None:
        """Collect the reviewed account baseline without persisting PII payloads."""
        selected = set(request.resource_kinds)
        # The three device-reference resources are deliberately dependent on
        # this invocation's devices inventory.  No provider identifier is
        # cached across invocations.
        device_dependents = {"primary_device", "device_last_used", "device_settings"}
        resources = tuple(resource for resource in self._ACCOUNT_BASIC_RESOURCES if not selected or resource in selected or (resource == "devices" and bool(selected & device_dependents)))
        if not resources:
            return
        # Never reuse IDs discovered by a previous invocation.
        if "devices" in resources:
            self._account_device_ids = {}
            self._account_device_aliases = {}
            self._account_devices_ready = False
        from .garmin_catalog import RESOURCE_CATALOG
        for resource in resources:
            spec = RESOURCE_CATALOG[resource]
            key = f"garmin:account:{resource}"
            try:
                payload = self._call(
                    lambda r=resource: self._transport().fetch_health(r, day.isoformat()),
                    conn=conn, run=run, subject=subject, resource=resource, key=key,
                    allows_404=spec.allows_404,
                )
                raw_payload = validate_provider_json_payload(payload)
                state = self._health_payload_state(payload, spec.empty_state)
                if state is not None:
                    if state != "empty":
                        self.repo.capability(conn, subject, resource, state, reason="provider_empty_or_capability", next_probe=self._account_next_probe(state), environment_key=self.config.region)
                    self.repo.coverage(conn, subject, resource, day.isoformat(), "partial" if request.mode == "snapshot" else state, None, 0, snapshot=request.mode == "snapshot")
                    self.repo.item(conn, run, resource, key, "fetch", state, increment_attempt=False)
                    self._count_receipt_terminal(receipt, state)
                    continue
                self.repo.item(conn, run, resource, key, "fetch", "fetched", increment_attempt=False)
                safe = self._safe_account_payload(resource, payload)
                if resource == "devices":
                    self._account_device_ids = self._device_id_map(payload)
                    self._account_device_aliases = self._device_alias_map(payload)
                provider_id = self._identity_hmac(f"account-resource:{resource}")

                def projector(revision: int, *, safe_payload: Any = safe, kind: str = resource) -> None:
                    if kind == "devices":
                        self._catalog_device_fields(conn, safe_payload)
                        count = self._project_devices(conn, safe_payload)
                    else:
                        self.repo.fields(conn, kind, safe_payload)
                        count = self._project_profile_settings(conn, subject, kind, safe_payload, revision)
                    self.repo.coverage(conn, subject, kind, day.isoformat(), "partial" if request.mode == "snapshot" else "fetched", revision, count, snapshot=request.mode == "snapshot")
                    if request.mode != "snapshot":
                        self.repo.resolve_gaps(conn, subject, kind, day.isoformat())

                semantic_payload = (
                    canonical_provider_json(safe)
                    if resource == "user_profile"
                    else None
                )
                _, revision, changed = self.repo.archive(
                    conn,
                    resource,
                    provider_id,
                    canonical_provider_json(raw_payload),
                    "json",
                    "application/json",
                    projector,
                    semantic_payload=semantic_payload,
                    profile_version=(
                        ACCOUNT_PROFILE_SEMANTIC_VERSION
                        if semantic_payload is not None
                        else None
                    ),
                )
                if resource == "devices":
                    self._account_devices_ready = True
                if not changed and request.mode == "snapshot":
                    self.repo.coverage(conn, subject, resource, day.isoformat(), "partial", revision, 0, snapshot=True)
                self.repo.capability(conn, subject, resource, "supported", environment_key=self.config.region)
                self.repo.item(conn, run, resource, key, "project", "revised" if changed else "unchanged", revision_id=revision, increment_attempt=False)
                receipt.counts["revised" if changed else "unchanged"] += 1
            except GarminError as exc:
                outcome = self._classify(exc, allows_404=spec.allows_404)
                if outcome.status == "auth_required":
                    raise GarminError("auth_required", http_status=401) from None
                if outcome.status == "not_available" or exc.code == "not_supported":
                    state = "not_supported" if exc.code == "not_supported" else "not_available"
                    self.repo.capability(conn, subject, resource, state, reason=exc.code, next_probe=self._account_next_probe(state), environment_key=self.config.region)
                    self.repo.coverage(conn, subject, resource, day.isoformat(), "partial" if request.mode == "snapshot" else state, None, 0, snapshot=request.mode == "snapshot")
                    terminal, retry = state, None
                elif outcome.status == "forbidden":
                    self.repo.capability(conn, subject, resource, "forbidden", reason=exc.code, next_probe=self._account_next_probe("forbidden"), environment_key=self.config.region)
                    terminal, retry = "forbidden", None
                    self.repo.coverage(conn, subject, resource, day.isoformat(), "partial" if request.mode == "snapshot" else "forbidden", None, 0, snapshot=request.mode == "snapshot")
                else:
                    terminal = "deferred" if outcome.status == "deferred" else "failed"
                    retry = self._next_retry(exc, 0) if terminal == "deferred" else None
                    if request.mode == "snapshot":
                        self.repo.coverage(conn, subject, resource, day.isoformat(), "partial", None, 0, snapshot=True)
                self.repo.item(conn, run, resource, key, "fetch", terminal, error=exc, next_retry=retry, increment_attempt=False)
                self.repo.gap(conn, subject, resource, key, day.isoformat(), "fetch", exc.code, deferred=terminal == "deferred", next_retry=retry)
                self._count_receipt_terminal(receipt, terminal)
                # Account-baseline absence prevents a complete account
                # snapshot.  It remains explicitly counted as unavailable
                # while correctly making this run partial.
                if terminal == "not_available":
                    receipt.counts["failed"] += 1
                receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
            except Exception:
                error = GarminError("account_project_failed")
                if request.mode == "snapshot":
                    self.repo.coverage(conn, subject, resource, day.isoformat(), "partial", None, 0, snapshot=True)
                self.repo.item(conn, run, resource, key, "project", "failed", error=error)
                self.repo.gap(conn, subject, resource, key, day.isoformat(), "project", error.code)
                receipt.counts["failed"] += 1

    def _account_b1(self, conn: sqlite3.Connection, run: int, subject: int, day: date, request: SyncRequest, receipt: SyncReceipt) -> None:
        """Remaining reviewed account/device endpoints (L2-09B1 only)."""
        selected = set(request.resource_kinds)
        resources = tuple(resource for resource in self._ACCOUNT_B1_RESOURCES if not selected or resource in selected)
        if not resources:
            return
        from .garmin_catalog import RESOURCE_CATALOG
        device_ids = dict(getattr(self, "_account_device_ids", {}))
        for resource in resources:
            spec = RESOURCE_CATALOG[resource]
            keys = list(device_ids.items()) if resource == "device_settings" else [(None, None)]
            outcomes: list[tuple[str, int | None, int, str | None]] = []
            if resource in {"primary_device", "device_last_used"} and not getattr(self, "_account_devices_ready", False):
                key = f"garmin:account:{resource}:account"
                self.repo.gap(conn, subject, resource, key, day.isoformat(), "discover", "not_available")
                self.repo.item(conn, run, resource, key, "discover", "not_available", increment_attempt=False)
                outcomes.append(("not_available", None, 0, "not_available"))
                self._count_receipt_terminal(receipt, "not_available")
                self._publish_b1_coverage(conn, subject, resource, day.isoformat(), request, outcomes)
                continue
            if resource == "device_settings" and not keys:
                self.repo.gap(conn, subject, resource, "garmin:account:device_settings", day.isoformat(), "discover", "not_available")
                self.repo.item(conn, run, resource, "garmin:account:device_settings", "discover", "not_available", increment_attempt=False)
                outcomes.append(("not_available", None, 0, "not_available"))
                self._count_receipt_terminal(receipt, "not_available")
            for device_hash, provider_id in keys:
                key = f"garmin:account:{resource}:{device_hash or 'account'}"
                try:
                    payload = self._call(
                        lambda r=resource, p=provider_id: self._fetch_account(r, p),
                        conn=conn, run=run, subject=subject, resource=resource,
                        key=key, allows_404=spec.allows_404,
                    )
                    raw_payload = validate_provider_json_payload(payload)
                    state = self._health_payload_state(payload, spec.empty_state)
                    if state is not None:
                        # Capability/empty responses are immutable, sanitized
                        # tombstones too.  They supersede an older account
                        # canonical projection instead of leaving it current.
                        provider_key = self._identity_hmac(f"account-b1:{resource}:{device_hash or 'account'}")
                        tombstone = {"availability_state": state}
                        coverage_state = "partial" if request.mode == "snapshot" else state
                        def tombstone_projector(revision: int, *, kind: str = resource) -> None:
                            self.repo.fields(conn, kind, tombstone)
                            self._supersede_b1_projection(conn, subject, kind)
                        _, revision, changed = self.repo.archive(conn, resource, provider_key, stable_json(tombstone), "json", "application/json", tombstone_projector)
                        self.repo.item(conn, run, resource, key, "fetch", state, revision_id=revision, increment_attempt=False)
                        outcomes.append((state, revision, 0, "provider_empty_or_capability" if state != "empty" else None))
                        self._count_receipt_terminal(receipt, state)
                        continue
                    # _call records running for every provider operation.
                    # A successful fetch must end before projection begins.
                    self.repo.item(conn, run, resource, key, "fetch", "fetched", increment_attempt=False)
                    provider_key = self._identity_hmac(f"account-b1:{resource}:{device_hash or 'account'}")
                    def projector(
                        revision: int,
                        *,
                        kind: str = resource,
                        raw_payload: Any = payload,
                        hashed: str | None = device_hash,
                    ) -> None:
                        # Compute the redacted projection only after the raw
                        # object and received revision are durable.  A future
                        # wrapper drift therefore remains locally reparsable.
                        safe_payload = self._safe_b1_payload(
                            kind,
                            raw_payload,
                            device_hash=hashed,
                            device_ids=device_ids,
                            device_aliases=dict(
                                getattr(self, "_account_device_aliases", {})
                            ),
                        )
                        if kind in {"primary_device", "device_last_used", "device_settings"}:
                            count = self._project_device_b1(conn, subject, kind, safe_payload, hashed, revision)
                        else:
                            self._supersede_b1_projection(conn, subject, kind)
                            self.repo.fields(conn, kind, safe_payload)
                            count = self._project_b1_physiology(conn, subject, kind, safe_payload, revision)
                    reference_semantic = (
                        self._device_reference_semantic_payload(payload, resource)
                        if resource == "device_last_used"
                        else None
                    )
                    _, revision, changed = self.repo.archive(
                        conn,
                        resource,
                        provider_key,
                        canonical_provider_json(raw_payload),
                        "json",
                        "application/json",
                        projector,
                        semantic_payload=(
                            canonical_provider_json(reference_semantic)
                            if reference_semantic is not None
                            else None
                        ),
                        profile_version=(
                            DEVICE_REFERENCE_SEMANTIC_VERSION
                            if reference_semantic is not None
                            else None
                        ),
                    )
                    self.repo.item(conn, run, resource, key, "project", "revised" if changed else "unchanged", revision_id=revision, increment_attempt=False)
                    outcomes.append(("fetched", revision, 1, None))
                    receipt.counts["revised" if changed else "unchanged"] += 1
                except GarminError as exc:
                    outcome = self._classify(exc, allows_404=spec.allows_404)
                    if outcome.status == "auth_required": raise GarminError("auth_required", http_status=401) from None
                    if exc.code == "not_supported":
                        state, terminal, retry = "not_supported", "not_supported", None
                    elif outcome.status == "not_available":
                        state, terminal, retry = "not_available", "not_available", None
                    elif outcome.status == "forbidden":
                        state, terminal, retry = "forbidden", "forbidden", None
                    elif outcome.status == "deferred":
                        state, terminal, retry = "deferred", "deferred", self._next_retry(exc, 0)
                    else:
                        state, terminal, retry = "failed", "failed", None
                    if state in {"not_supported", "not_available", "forbidden"}:
                        pass
                    else:
                        self.repo.gap(conn, subject, resource, key, day.isoformat(), "fetch", exc.code, deferred=terminal == "deferred", next_retry=retry)
                        if request.mode == "snapshot":
                            self.repo.coverage(conn, subject, resource, day.isoformat(), "partial", None, 0, snapshot=True)
                    self.repo.item(conn, run, resource, key, "fetch", terminal, error=exc, next_retry=retry, increment_attempt=False)
                    outcomes.append((terminal, None, 0, exc.code))
                    if terminal == "deferred":
                        self._count_receipt_terminal(receipt, terminal)
                        receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
                    else:
                        self._count_receipt_terminal(receipt, terminal)
                except Exception as exc:
                    error = GarminError("unknown_device_reference" if str(exc) == "unknown_device_reference" else "account_project_failed")
                    self.repo.item(conn, run, resource, key, "project", "failed", error=error)
                    self.repo.gap(conn, subject, resource, key, day.isoformat(), "project", error.code)
                    outcomes.append(("failed", None, 0, error.code))
                    receipt.counts["failed"] += 1
            self._publish_b1_coverage(conn, subject, resource, day.isoformat(), request, outcomes)

    def _fetch_account(self, resource: str, provider_id: str | None) -> Any:
        method = getattr(self._transport(), "fetch_account", None)
        if not callable(method): raise GarminError("not_supported", http_status=404)
        return method(resource, provider_id)

    def _device_id_map(self, payload: Any) -> dict[str, str]:
        records = payload.get("devices", []) if isinstance(payload, dict) else payload
        result: dict[str, str] = {}
        if not isinstance(records, list): return result
        for entry in records:
            if not isinstance(entry, dict): continue
            provider_id = entry.get("deviceId") or entry.get("deviceUuid") or entry.get("unitId") or entry.get("serialNumber")
            if provider_id is not None: result[self._identity_hmac(f"device:{provider_id}")] = str(provider_id)
        return result

    def _device_alias_map(self, payload: Any) -> dict[str, str]:
        """Map every reviewed provider identifier to one canonical device hash."""
        records = payload.get("devices", []) if isinstance(payload, dict) else payload
        result: dict[str, str] = {}
        if not isinstance(records, list):
            return result
        for entry in records:
            if not isinstance(entry, dict):
                continue
            provider_id = (
                entry.get("deviceId")
                or entry.get("deviceUuid")
                or entry.get("unitId")
                or entry.get("serialNumber")
            )
            if provider_id is None:
                continue
            canonical = self._identity_hmac(f"device:{provider_id}")
            for field in (
                "deviceId",
                "deviceUuid",
                "unitId",
                "serialNumber",
                "userDeviceId",
            ):
                alias = entry.get(field)
                if alias is not None:
                    result[self._identity_hmac(f"device:{alias}")] = canonical
        return result

    def _safe_b1_payload(
        self,
        resource: str,
        payload: Any,
        *,
        device_hash: str | None,
        device_ids: dict[str, str],
        device_aliases: dict[str, str] | None = None,
    ) -> Any:
        if resource in {"primary_device", "device_last_used"}:
            source = self._device_reference_object(payload, resource)
            aliases = device_aliases or {
                canonical: canonical for canonical in device_ids
            }
            canonical = None
            for field in (
                "deviceId",
                "deviceUuid",
                "unitId",
                "serialNumber",
                "userDeviceId",
            ):
                provider_id = source.get(field)
                if provider_id is None:
                    continue
                canonical = aliases.get(
                    self._identity_hmac(f"device:{provider_id}")
                )
                if canonical is not None:
                    break
            if canonical is None or canonical not in device_ids:
                raise ValueError("unknown_device_reference")
            return {"device_uid_hash": canonical}
        if resource == "device_settings":
            if device_hash is None or device_hash not in device_ids: raise ValueError("unknown_device_reference")
            source = payload if isinstance(payload, dict) else {}
            safe = {"device_uid_hash": device_hash}
            for field in ("softwareVersion", "firmwareVersion", "batterySaveMode"):
                if isinstance(source.get(field), (str, int, float, bool)): safe[field] = source[field]
            return safe
        source = payload if isinstance(payload, dict) else {}
        allowed = {
            "personal_records": {"vo2Max", "maxHeartRate", "restingHeartRate"},
            "cycling_ftp": {"ftp", "ftpWatts"},
            "pregnancy": {"pregnancyWeek"},
        }[resource]
        return {key: source[key] for key in sorted(allowed) if isinstance(source.get(key), (int, float)) and not isinstance(source.get(key), bool)}

    @staticmethod
    def _device_reference_object(payload: Any, resource: str) -> dict[str, Any]:
        """Normalise the reviewed Connect wrappers without accepting guesses."""
        if isinstance(payload, list):
            if len(payload) != 1 or not isinstance(payload[0], dict):
                raise ValueError("unknown_device_reference")
            return payload[0]
        if not isinstance(payload, dict):
            raise ValueError("unknown_device_reference")
        wrappers = (
            (
                "primaryTrainingDevice",
                "PrimaryTrainingDevice",
                "primaryTrainingDeviceDTO",
                "primaryDevice",
                "deviceDTO",
                "device",
            )
            if resource == "primary_device"
            else (
                "lastUsedDevice",
                "lastUsedDeviceDTO",
                "deviceLastUsed",
                "deviceDTO",
                "device",
            )
        )
        for name in wrappers:
            value = payload.get(name)
            if isinstance(value, dict):
                return value
        return payload

    @classmethod
    def _device_reference_semantic_payload(
        cls,
        payload: Any,
        resource: str,
    ) -> dict[str, str] | None:
        """Select stable reference fields while retaining complete raw JSON."""
        try:
            source = cls._device_reference_object(payload, resource)
        except ValueError:
            return None
        reference = {
            field: str(source[field])
            for field in (
                "deviceId",
                "deviceUuid",
                "unitId",
                "serialNumber",
                "userDeviceId",
            )
            if source.get(field) is not None
        }
        # Unknown wrapper drift falls back to full-response revisioning.  Its
        # complete raw object remains available for a later parser repair.
        return reference or None

    def _project_device_b1(self, conn: sqlite3.Connection, subject: int, resource: str, payload: Any, device_hash: str | None, revision: int) -> int:
        hashed = payload.get("device_uid_hash") if isinstance(payload, dict) else device_hash
        if not hashed or conn.execute("SELECT 1 FROM devices WHERE device_uid_hash=?", (hashed,)).fetchone() is None:
            raise ValueError("unknown_device_reference")
        if resource == "device_settings":
            catalog = {key: value for key, value in payload.items() if key != "device_uid_hash"}
            self.repo.fields(conn, resource, catalog)
            for path in ("/softwareVersion", "/firmwareVersion", "/batterySaveMode"):
                self.repo.passthrough_field(conn, resource, path)
        # There is no device-role/settings table in the frozen Foundation DDL.
        # A revision-linked physiology record is the stable, de-identified
        # canonical relationship: provider IDs and serials never enter it.
        conn.execute(
            """DELETE FROM physiology_metrics WHERE physiology_record_id IN
               (SELECT id FROM physiology_records WHERE subject_id=? AND domain='garmin' AND record_type=? AND provider_record_id=?)""",
            (subject, resource, hashed),
        )
        conn.execute("DELETE FROM physiology_records WHERE subject_id=? AND domain='garmin' AND record_type=? AND provider_record_id=?", (subject, resource, hashed))
        stamp = self._now_utc().isoformat().replace("+00:00", "Z")
        record = int(conn.execute(
            """INSERT INTO physiology_records(subject_id,domain,record_type,provider_record_id,effective_at_utc,local_date,value_origin,extras_json,source_revision_id)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (subject, "garmin", resource, hashed, stamp, self._local_day(stamp), "provider_derived", stable_json({"device_uid_hash": hashed}), revision),
        ).lastrowid)
        values: dict[str, Any] = {}
        if resource == "primary_device": values["garmin.device.role.primary"] = True
        elif resource == "device_last_used": values["garmin.device.role.last_used"] = True
        else:
            values = {f"garmin.device.settings.{key}": value for key, value in payload.items() if key != "device_uid_hash"}
        for metric_key, value in values.items():
            conn.execute(
                """INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_number,value_text,value_boolean,raw_unit,canonical_unit,value_origin,source_path)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (record, metric_key, float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
                 value if isinstance(value, str) else None, int(value) if isinstance(value, bool) else None,
                 None, None, "provider_derived", "/" + metric_key.rsplit(".", 1)[-1]),
            )
        return 1

    def _publish_b1_coverage(self, conn: sqlite3.Connection, subject: int, resource: str, day: str, request: SyncRequest, outcomes: list[tuple[str, int | None, int, str | None]]) -> None:
        """One resource/day coverage row, after all per-device facts settle."""
        if not outcomes:
            return
        severity = {"fetched": 0, "empty": 1, "not_enabled": 2, "not_available": 3, "not_supported": 4, "forbidden": 5, "failed": 6, "deferred": 7}
        state, revision, _count, reason = max(outcomes, key=lambda outcome: severity.get(outcome[0], 6))
        total = sum(item[2] for item in outcomes) if state == "fetched" else 0
        coverage_state = "partial" if request.mode == "snapshot" else ({"failed": "error", "deferred": "partial"}.get(state, state))
        # Source revisions preserve history.  Coverage is the one current
        # aggregate claim for this account resource/date, never one row per
        # device response.
        conn.execute("DELETE FROM resource_coverage WHERE subject_id=? AND provider='garmin' AND resource_kind=? AND local_date=?", (subject, resource, day))
        self.repo.coverage(conn, subject, resource, day, coverage_state, revision, total, snapshot=request.mode == "snapshot")
        capability = "supported" if state in {"fetched", "empty"} else state
        if capability in {"supported", "not_enabled", "not_available", "not_supported", "forbidden"}:
            self.repo.capability(conn, subject, resource, capability, reason=reason, next_probe=self._account_next_probe(capability), environment_key=self.config.region)

    @staticmethod
    def _count_receipt_terminal(receipt: SyncReceipt, terminal: str) -> None:
        """Map every durable terminal state to receipt-v1's fixed counters."""
        counter = {
            "not_supported": "not_available",
            "forbidden": "failed",
        }.get(terminal, terminal)
        if counter in receipt.counts:
            receipt.counts[counter] += 1

    @staticmethod
    def _supersede_b1_projection(conn: sqlite3.Connection, subject: int, resource: str) -> None:
        """Account snapshots have one current canonical view per resource."""
        if resource in {"personal_records", "cycling_ftp", "pregnancy"}:
            conn.execute(
                """DELETE FROM physiology_metrics WHERE physiology_record_id IN
                   (SELECT id FROM physiology_records WHERE subject_id=? AND domain='garmin' AND record_type=?)""",
                (subject, resource),
            )
            conn.execute("DELETE FROM physiology_records WHERE subject_id=? AND domain='garmin' AND record_type=?", (subject, resource))

    def _project_b1_physiology(self, conn: sqlite3.Connection, subject: int, resource: str, payload: Any, revision: int) -> int:
        if not payload: return 0
        stamp = self._now_utc().isoformat().replace("+00:00", "Z")
        cursor = conn.execute("INSERT INTO physiology_records(subject_id,domain,record_type,effective_at_utc,local_date,value_origin,extras_json,source_revision_id) VALUES(?,?,?,?,?,?,?,?)", (subject, "garmin", resource, stamp, self._local_day(stamp), "provider_derived", "{}", revision))
        record = int(cursor.lastrowid)
        for key, value in payload.items():
            metric_key, unit = self._b1_metric_definition(resource, key)
            conn.execute("INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_number,raw_unit,canonical_unit,value_origin,source_path) VALUES(?,?,?,?,?,?,?)", (record, metric_key, float(value), unit, unit, "provider_derived", f"/{key}"))
            self.repo.map_field(conn, resource, f"/{key}", metric_key)
        return 1

    @staticmethod
    def _b1_metric_definition(resource: str, key: str) -> tuple[str, str | None]:
        """Reviewed scalar metrics; no provider container is treated as a metric."""
        units = {
            ("personal_records", "vo2Max"): "ml/kg/min",
            ("personal_records", "maxHeartRate"): "bpm",
            ("personal_records", "restingHeartRate"): "bpm",
            ("cycling_ftp", "ftp"): "W",
            ("cycling_ftp", "ftpWatts"): "W",
            ("pregnancy", "pregnancyWeek"): "week",
        }
        return f"garmin.{resource}.{key}", units.get((resource, key))

    def _account_next_probe(self, state: str) -> str | None:
        if state not in {"not_enabled", "not_available", "not_supported", "forbidden"}:
            return None
        return (self._now_utc() + timedelta(days=7)).isoformat().replace("+00:00", "Z")

    def _safe_account_payload(self, resource: str, payload: Any) -> Any:
        if resource in {"user_profile", "user_profile_settings"}:
            source = payload if isinstance(payload, dict) else {}
            safe: dict[str, str | int | float | bool] = {}
            for key in sorted(self._PROFILE_SETTING_FIELDS):
                value = source.get(key)
                if isinstance(value, (str, int, float, bool)):
                    safe[key] = value
            return safe
        if resource == "devices":
            source = payload.get("devices", []) if isinstance(payload, dict) else payload
            if not isinstance(source, list):
                raise ValueError("invalid_devices_payload")
            devices: list[dict[str, str]] = []
            for entry in source:
                if not isinstance(entry, dict):
                    raise ValueError("invalid_device_entry")
                uid = entry.get("deviceId") or entry.get("deviceUuid") or entry.get("unitId") or entry.get("serialNumber")
                if uid is None:
                    raise ValueError("missing_device_uid")
                safe = {"device_uid_hash": self._identity_hmac(f"device:{uid}")}
                for source_key, target_key in (("manufacturer", "manufacturer"), ("product", "product"), ("productName", "product"), ("deviceType", "deviceType"), ("type", "deviceType"), ("hardwareVersion", "hardwareVersion")):
                    value = entry.get(source_key)
                    if value is not None and target_key not in safe:
                        safe[target_key] = str(value)
                # Software is not hardware. The stable devices DDL has no
                # software column, so the reviewed raw source field is kept as
                # a known passthrough and never populates hardware_version.
                if entry.get("softwareVersion") is not None:
                    safe["softwareVersion"] = str(entry["softwareVersion"])
                devices.append(safe)
            return {"devices": sorted(devices, key=lambda device: device["device_uid_hash"])}
        raise ValueError("unknown_account_resource")

    def _catalog_device_fields(self, conn: sqlite3.Connection, payload: Any) -> None:
        devices = payload.get("devices", []) if isinstance(payload, dict) else []
        catalog_payload = {"devices": [{key: value for key, value in device.items() if key != "device_uid_hash"} for device in devices]}
        self.repo.fields(conn, "devices", catalog_payload)
        for path, key in (
            ("/devices/*/hardwareVersion", "garmin.device.hardware_version"),
        ):
            self.repo.map_field(conn, "devices", path, key)
        for path in ("/devices/*/softwareVersion", "/devices/*/manufacturer", "/devices/*/product", "/devices/*/deviceType"):
            self.repo.passthrough_field(conn, "devices", path)

    def _project_devices(self, conn: sqlite3.Connection, payload: Any) -> int:
        devices = payload.get("devices", []) if isinstance(payload, dict) else []
        now = self._now_utc().isoformat().replace("+00:00", "Z")
        for device in devices:
            conn.execute(
                """INSERT INTO devices(device_uid_hash,manufacturer,product,device_type,hardware_version,first_seen_at_utc,last_seen_at_utc)
                   VALUES(?,?,?,?,?,?,?) ON CONFLICT(device_uid_hash) DO UPDATE SET
                   manufacturer=excluded.manufacturer,product=excluded.product,device_type=excluded.device_type,
                   hardware_version=excluded.hardware_version,last_seen_at_utc=excluded.last_seen_at_utc""",
                (device["device_uid_hash"], device.get("manufacturer"), device.get("product"), device.get("deviceType"), device.get("hardwareVersion"), now, now),
            )
        return len(devices)

    def _project_profile_settings(self, conn: sqlite3.Connection, subject: int, resource: str, payload: Any, revision: int) -> int:
        if not isinstance(payload, dict):
            return 0
        allowed = {key: value for key, value in payload.items() if key in self._PROFILE_SETTING_FIELDS}
        if not allowed:
            return 0
        # Revisions make the view current; do not retain an unbounded complete
        # provider response in extras_json.
        cursor = conn.execute(
            """INSERT INTO physiology_records(subject_id,domain,record_type,effective_at_utc,local_date,value_origin,extras_json,source_revision_id)
               VALUES(?,?,?,?,?,?,?,?)""",
            (subject, "garmin", resource, self._now_utc().isoformat().replace("+00:00", "Z"), self._now_utc().astimezone(TZ).date().isoformat(), "profile_setting", "{}", revision),
        )
        record = int(cursor.lastrowid)
        for key, value in allowed.items():
            numeric = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            text = value if isinstance(value, str) else None
            boolean = int(value) if isinstance(value, bool) else None
            conn.execute(
                """INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_number,value_text,value_boolean,raw_unit,canonical_unit,value_origin,source_path)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (record, f"garmin.profile.{key}", numeric, text, boolean, None, None, "profile_setting", f"/{key}"),
            )
            self.repo.map_field(conn, resource, f"/{key}", f"garmin.profile.{key}")
        return 1

    @staticmethod
    def _health_item_completed(
        conn: sqlite3.Connection,
        run: int,
        resource: str,
        logical_key: str,
    ) -> bool:
        """Return true only for a fully durable successful health work item."""
        stages = {
            str(row["stage"]): str(row["status"])
            for row in conn.execute(
                """SELECT stage,status FROM garmin_sync_items
                    WHERE garmin_sync_run_id=? AND resource_kind=?
                      AND logical_object_key=?""",
                (run, resource, logical_key),
            )
        }
        fetch = stages.get("fetch")
        if fetch in {
            "empty", "not_available", "not_enabled", "not_supported",
        }:
            return True
        return (
            fetch == "fetched"
            and stages.get("project") in {"revised", "unchanged", "succeeded"}
        )

    def _health(self, conn: sqlite3.Connection, run: int, subject: int, start: date, through: date, request: SyncRequest, receipt: SyncReceipt) -> None:
        selected = set(request.resource_kinds) or set(HEALTH_RESOURCES)
        from .garmin_catalog import RESOURCE_CATALOG
        # Compatibility doubles used by pre-range tests expose only the old
        # one-day protocol. Real pinned transport always provides fetch_range.
        range_resources = ({resource for resource in selected if resource in RESOURCE_CATALOG and RESOURCE_CATALOG[resource].scope == "range"}
                           if callable(getattr(self._transport(), "fetch_range", None)) else set())
        for resource in sorted(range_resources):
            self._health_range(conn, run, subject, resource, start, through, request, receipt)
        selected -= range_resources
        for day in (start + timedelta(i) for i in range((through - start).days + 1)):
            for resource in HEALTH_RESOURCES:
                if resource not in selected: continue
                key = f"garmin:health:{resource}:{day}"
                if self._health_item_completed(conn, run, resource, key):
                    continue
                try:
                    spec = RESOURCE_CATALOG[resource]
                    payload = self._call(
                        lambda r=resource, d=day: self._transport().fetch_health(r, d.isoformat()),
                        conn=conn, run=run, subject=subject, resource=resource, key=key,
                        allows_404=spec.allows_404,
                    )
                    # Validate before recording a successful fetch stage: a
                    # credential-bearing response is quarantined with zero
                    # raw/revision/canonical writes.
                    stored_payload = validate_provider_json_payload(payload)
                    payload_state = self._health_payload_state(stored_payload, spec.empty_state)
                    if payload_state is not None:
                        if payload_state != "empty":
                            self.repo.capability(conn, subject, resource, payload_state, reason="provider_empty_or_capability")
                        coverage_state = "partial" if request.mode == "snapshot" else payload_state
                        def tombstone_projector(revision: int) -> None:
                            self.repo.fields(conn, resource, stored_payload)
                            self._supersede_health_projection(conn, subject, resource, key, day.isoformat())
                            self.repo.coverage(conn, subject, resource, day.isoformat(), coverage_state, revision, 0, snapshot=request.mode == "snapshot")
                            if request.mode != "snapshot":
                                self.repo.resolve_gaps(conn, subject, resource, day.isoformat())
                        _, revision, changed = self.repo.archive(
                            conn, resource, key, canonical_provider_json(stored_payload), "json", "application/json", tombstone_projector
                        )
                        if not changed:
                            # A stable tombstone remains an immutable current
                            # revision; record this observation with provenance.
                            self.repo.coverage(conn, subject, resource, day.isoformat(), coverage_state, revision, 0, snapshot=request.mode == "snapshot")
                        self.repo.item(conn, run, resource, key, "fetch", payload_state, revision_id=revision, increment_attempt=False)
                        if payload_state in receipt.counts: receipt.counts[payload_state] += 1
                        continue
                    self.repo.item(conn, run, resource, key, "fetch", "fetched", increment_attempt=False)
                    def projector(revision: int):
                        self.repo.fields(conn, resource, stored_payload)
                        self._supersede_health_projection(conn, subject, resource, key, day.isoformat())
                        projected = self._project_health(conn, subject, resource, day.isoformat(), stored_payload, revision)
                        self.repo.coverage(conn, subject, resource, day.isoformat(), "partial" if request.mode == "snapshot" else "fetched", revision, projected, snapshot=request.mode == "snapshot")
                        if request.mode != "snapshot": self.repo.resolve_gaps(conn,subject,resource,day.isoformat())
                    _, revision, changed = self.repo.archive(conn, resource, key, canonical_provider_json(stored_payload), "json", "application/json", projector)
                    self.repo.item(conn, run, resource, key, "project", "revised" if changed else "unchanged", revision_id=revision); receipt.counts["revised" if changed else "unchanged"] += 1
                except GarminError as exc:
                    outcome = self._classify(exc, allows_404=spec.allows_404)
                    if outcome.status == "auth_required":
                        raise GarminError("auth_required", http_status=401) from None
                    if outcome.status == "not_available" or exc.code == "not_supported":
                        state = "not_supported" if exc.code == "not_supported" else "not_available"
                        self.repo.capability(conn, subject, resource, state, reason=exc.code)
                        self.repo.coverage(conn, subject, resource, day.isoformat(), "partial" if request.mode == "snapshot" else state, None, 0, snapshot=request.mode == "snapshot")
                        if request.mode != "snapshot": self.repo.resolve_gaps(conn, subject, resource, day.isoformat())
                        self.repo.item(conn, run, resource, key, "fetch", state, error=exc, increment_attempt=False)
                        if state in receipt.counts: receipt.counts[state] += 1
                        continue
                    if outcome.status == "forbidden":
                        self.repo.capability(conn, subject, resource, "forbidden", reason=exc.code)
                        terminal, retry = "forbidden", None
                    elif outcome.status == "deferred":
                        terminal, retry = "deferred", self._next_retry(exc, 0)
                    else:
                        terminal, retry = "failed", None
                    if request.mode == "snapshot":
                        self.repo.coverage(conn, subject, resource, day.isoformat(), "partial", None, 0, snapshot=True)
                    elif outcome.status == "forbidden":
                        self.repo.coverage(conn, subject, resource, day.isoformat(), "forbidden", None, 0)
                    self.repo.item(conn, run, resource, key, "fetch", terminal, error=exc, next_retry=retry, increment_attempt=False)
                    self.repo.gap(conn, subject, resource, key, day.isoformat(), "fetch", exc.code, deferred=terminal == "deferred", next_retry=retry)
                    receipt.counts["deferred" if terminal == "deferred" else "failed"] += 1
                    receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
                except Exception:
                    error = GarminError("parse_or_project_failed")
                    received_revision = self._unparsed_revision(conn, resource, key)
                    if request.mode == "snapshot":
                        self.repo.coverage(conn, subject, resource, day.isoformat(), "partial", None, 0, snapshot=True)
                    self.repo.item(conn, run, resource, key, "project", "failed", error=error, revision_id=received_revision)
                    self.repo.gap(
                        conn,
                        subject,
                        resource,
                        key,
                        day.isoformat(),
                        "project",
                        error.code,
                        revision=received_revision,
                    )
                    receipt.counts["failed"] += 1
                finally:
                    if resource in ADVANCED_RESOURCES:
                        self._consolidate_advanced_coverage(conn, subject, resource, day.isoformat())

    def _health_range(self, conn: sqlite3.Connection, run: int, subject: int, resource: str, start: date, through: date, request: SyncRequest, receipt: SyncReceipt) -> None:
        """Fetch a bounded provider range once and fan it out with shared lineage."""
        from .garmin_catalog import RESOURCE_CATALOG
        spec = RESOURCE_CATALOG[resource]
        maximum_days = spec.max_range_days
        if maximum_days is None or maximum_days < 1:
            raise ValueError("range_spec_missing_max_days")
        cursor = start
        while cursor <= through:
            end = min(through, cursor + timedelta(days=maximum_days - 1))
            logical_key = f"garmin:health:{resource}:{cursor}:{end}"
            if self._health_item_completed(conn, run, resource, logical_key):
                cursor = end + timedelta(days=1)
                continue
            try:
                payload = self._call(lambda s=cursor, e=end: self._transport().fetch_range(resource, s.isoformat(), e.isoformat()), conn=conn, run=run, subject=subject, resource=resource, key=logical_key, allows_404=spec.allows_404)
                stored = validate_provider_json_payload(payload)
                state = self._health_payload_state(stored, spec.empty_state)
                days = [cursor + timedelta(index) for index in range((end - cursor).days + 1)]
                if state is not None:
                    def tombstone(revision: int) -> None:
                        for current_day in days:
                            self._supersede_range_projection(conn, subject, resource, current_day.isoformat())
                            self.repo.coverage(conn, subject, resource, current_day.isoformat(), "partial" if request.mode == "snapshot" else state, revision, 0, snapshot=request.mode == "snapshot")
                    _, revision, changed = self.repo.archive(conn, resource, logical_key, canonical_provider_json(stored), "json", "application/json", tombstone)
                    self.repo.item(conn, run, resource, logical_key, "fetch", state, revision_id=revision, increment_attempt=False)
                    self._count_receipt_terminal(receipt, state)
                    if state != "empty": self.repo.capability(conn, subject, resource, state, reason="provider_empty_or_capability", next_probe=self._account_next_probe(state), environment_key=self.config.region)
                    if request.mode != "snapshot":
                        for current_day in days:
                            self.repo.resolve_gaps(conn, subject, resource, current_day.isoformat())
                    cursor = end + timedelta(days=1); continue
                self.repo.item(conn, run, resource, logical_key, "fetch", "fetched", increment_attempt=False)
                def projector(revision: int) -> None:
                    # Validate every returned record before deleting or writing
                    # any canonical row.  The received revision already exists
                    # at this point, so a malformed range remains reparsable.
                    by_day = self._range_payload_by_day(stored, cursor, end, resource=resource)
                    lactate_envelope = resource == "lactate_threshold" and isinstance(stored, dict) and any(
                        isinstance(stored.get(family), list)
                        for family in ("heart_rate", "power", "speed")
                    )
                    if lactate_envelope:
                        self.repo.fields(conn, resource, stored)
                    for current_day in days:
                        day_payload = by_day[current_day.isoformat()]
                        self._supersede_range_projection(conn, subject, resource, current_day.isoformat())
                        # Lactate's range envelope identifies the metric family
                        # only at the top level.  Catalogue that source shape,
                        # rather than the internally grouped day payload below.
                        if not lactate_envelope:
                            self.repo.fields(conn, resource, day_payload)
                        count = self._project_health(conn, subject, resource, current_day.isoformat(), day_payload, revision) if day_payload else 0
                        # Sparse records are a per-day absence, not an account
                        # capability conclusion.  Only an explicitly empty
                        # *whole response* above uses spec.empty_state.
                        state_for_day = "partial" if request.mode == "snapshot" else ("fetched" if day_payload else "empty")
                        self.repo.coverage(conn, subject, resource, current_day.isoformat(), state_for_day, revision, count, snapshot=request.mode == "snapshot")
                        if request.mode != "snapshot":
                            self.repo.resolve_gaps(conn, subject, resource, current_day.isoformat())
                _, revision, changed = self.repo.archive(conn, resource, logical_key, canonical_provider_json(stored), "json", "application/json", projector)
                self.repo.item(conn, run, resource, logical_key, "project", "revised" if changed else "unchanged", revision_id=revision, increment_attempt=False)
                receipt.counts["revised" if changed else "unchanged"] += 1
            except GarminError as exc:
                outcome = self._classify(exc, allows_404=spec.allows_404)
                if outcome.status == "auth_required":
                    raise GarminError("auth_required", http_status=401) from None
                retry = self._next_retry(exc, 0) if outcome.status == "deferred" else None
                terminal = "not_supported" if exc.code == "not_supported" else ("not_available" if outcome.status == "not_available" else ("forbidden" if outcome.status == "forbidden" else ("deferred" if outcome.status == "deferred" else "failed")))
                self.repo.item(conn, run, resource, logical_key, "fetch", terminal, error=exc, increment_attempt=False)
                if terminal in {"not_available", "not_supported", "forbidden"}:
                    self.repo.capability(conn, subject, resource, terminal, reason=exc.code, next_probe=self._account_next_probe(terminal), environment_key=self.config.region)
                for current_day in [cursor + timedelta(index) for index in range((end - cursor).days + 1)]:
                    coverage_state = "partial" if request.mode == "snapshot" else (terminal if terminal in {"not_available", "not_supported", "forbidden"} else "error")
                    self.repo.coverage(conn, subject, resource, current_day.isoformat(), coverage_state, None, 0, snapshot=request.mode == "snapshot")
                if terminal in {"not_available", "not_supported"}:
                    # Preserve the observed recovery history without leaving a
                    # deterministic capability absence as a cursor blocker.
                    self.repo.gap(
                        conn, subject, resource, logical_key,
                        cursor.isoformat(), "fetch", exc.code,
                        end_day=end.isoformat(),
                    )
                    if request.mode != "snapshot":
                        for current_day in (
                            cursor + timedelta(index)
                            for index in range((end - cursor).days + 1)
                        ):
                            self.repo.resolve_gaps(
                                conn, subject, resource,
                                current_day.isoformat(),
                                logical_object_key=logical_key,
                                stages=("fetch",),
                            )
                else:
                    self.repo.gap(conn, subject, resource, logical_key, cursor.isoformat(), "fetch", exc.code, end_day=end.isoformat(), deferred=terminal == "deferred", next_retry=retry)
                receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
                self._count_receipt_terminal(receipt, terminal)
                if terminal == "deferred":
                    # Do not turn a provider cooldown into a burst across
                    # later chunks.  The unscheduled remainder has no
                    # coverage claim and will be planned by the next run.
                    break
            except Exception:
                error = GarminError("parse_or_project_failed")
                received_revision = self._unparsed_revision(conn, resource, logical_key)
                self.repo.item(conn, run, resource, logical_key, "project", "failed", error=error, revision_id=received_revision)
                self.repo.gap(conn, subject, resource, logical_key, cursor.isoformat(), "project", error.code, end_day=end.isoformat(), revision=received_revision)
                receipt.counts["failed"] += 1
            cursor = end + timedelta(days=1)

    def _range_payload_by_day(self, payload: Any, start: date, end: date, *, resource: str | None = None) -> dict[str, list[dict[str, Any]]]:
        """Validate a whole provider response, then fan sparse records by day.

        A range response is permitted to contain no record for a legal day
        (weigh-ins and menstrual events are naturally sparse).  Missing or
        malformed dates on *returned* records are not sparse: they invalidate
        the whole chunk before any canonical projection occurs.
        """
        records = self._range_records(payload, resource=resource)
        selected: dict[str, list[dict[str, Any]]] = {
            (start + timedelta(index)).isoformat(): []
            for index in range((end - start).days + 1)
        }
        for record in records:
            date_keys = [
                "calendarDate",
                "timestamp",
                "timestampGMT",
                "measurementTimestampGMT",
                "gmtTimestamp",
                "startTimeGMT",
                "startTimestampGMT",
            ]
            if resource == "lactate_threshold":
                # Garmin's lactate range entries are dated by their update,
                # not by the enclosing response's from/until bounds.
                date_keys.insert(0, "updatedDate")
            if resource in {
                "body_battery",
                "body_composition",
                "weigh_ins",
                "blood_pressure",
            }:
                # These reviewed range envelopes use a local calendar `date`.
                # Do not accept that ambiguous key for unrelated resources.
                date_keys.insert(1, "date")
            stamp = next(
                (
                    record.get(key)
                    for key in date_keys
                    if record.get(key) is not None
                ),
                None,
            )
            if stamp is None:
                raise ValueError("range_record_missing_date")
            parsed = self._timestamp_utc(stamp, start.isoformat(), allow_day_boundary=True)
            local_day = self._local_day(parsed)
            if local_day not in selected and resource == "endurance_score":
                # The precise-day endpoint can return the latest available
                # score even when it predates the requested window.  Keep that
                # response as raw evidence without assigning it to this day.
                continue
            if local_day not in selected:
                raise ValueError("range_record_outside_window")
            if resource in ADVANCED_RESOURCES and resource != "lactate_threshold" and selected[local_day]:
                # Reviewed advanced range endpoints carry one daily summary;
                # duplicate calendar records are a shape drift, not a second
                # canonical prediction.  Measurement endpoints may validly
                # contain multiple same-day observations and remain allowed.
                raise ValueError("range_duplicate_day")
            selected[local_day].append(record)
        return selected

    def _range_payload_for_day(self, payload: Any, day: str, span: int) -> Any:
        # Compatibility helper retained for older callers/tests.
        start = date.fromisoformat(day)
        return self._range_payload_by_day(payload, start, start + timedelta(days=span - 1))[day]

    @staticmethod
    def _unparsed_revision(conn: sqlite3.Connection, resource: str, provider_id: str) -> int | None:
        row = conn.execute(
            """SELECT id FROM source_revisions WHERE provider='garmin' AND resource_kind=?
               AND provider_object_id=? AND is_current=0 AND parsed_at_utc IS NULL
               ORDER BY revision_no DESC LIMIT 1""",
            (resource, provider_id),
        ).fetchone()
        return int(row["id"]) if row is not None else None

    def _range_records(
        self, payload: Any, *, resource: str | None = None
    ) -> list[dict[str, Any]]:
        """Open only reviewed range envelopes; metadata is never a record."""
        if isinstance(payload, dict):
            if resource == "weigh_ins" and isinstance(payload.get("dailyWeightSummaries"), list):
                # Daily summaries are envelopes.  Only allWeightMetrics holds
                # measurements; latestWeight is a summary pointer and would
                # otherwise duplicate a canonical observation.
                return [
                    metric
                    for summary in payload["dailyWeightSummaries"]
                    if isinstance(summary, dict)
                    for metric in (
                        summary.get("allWeightMetrics")
                        if isinstance(summary.get("allWeightMetrics"), list)
                        else []
                    )
                    if isinstance(metric, dict)
                ]
            if resource == "lactate_threshold" and any(
                isinstance(payload.get(name), list)
                for name in ("heart_rate", "power", "speed")
            ):
                # Retain the provider family only as ephemeral projection
                # context.  It is never archived and never field-catalogued.
                return [
                    {**entry, "__trainlab_lactate_family": family}
                    for family in ("heart_rate", "power", "speed")
                    for entry in (payload.get(family) if isinstance(payload.get(family), list) else [])
                    if isinstance(entry, dict)
                ]
            wrappers: dict[str, tuple[str, ...]] = {
                "body_composition": ("dateWeightList",),
                "weigh_ins": ("dailyWeightSummaries",),
                "blood_pressure": ("measurementSummaries",),
                "lactate_threshold": ("speed", "heart_rate", "power"),
                "menstrual": (
                    "cycleSummaries",
                    "loggedNoteDays",
                    "loggedOvulationDays",
                    "loggedSymptomDays",
                ),
            }
            selected_wrappers = wrappers.get(resource or "")
            if selected_wrappers is not None and any(
                name in payload for name in selected_wrappers
            ):
                return [
                    item
                    for name in selected_wrappers
                    for item in (
                        payload.get(name)
                        if isinstance(payload.get(name), list)
                        else []
                    )
                    if isinstance(item, dict)
                ]
            if (
                resource == "endurance_score"
                and "enduranceScoreDTO" in payload
            ):
                value = payload.get("enduranceScoreDTO")
                if value in (None, {}):
                    return []
                if not isinstance(value, dict):
                    raise ValueError("range_envelope_invalid")
                return [value]
            if (
                resource == "endurance_score"
                and "calendarDate" in payload
                and payload.get("calendarDate") is None
            ):
                # A supported account without a score yet returns the DTO
                # shape with a null day.  It is a valid empty observation for
                # the requested window, not a timestampless score.
                return []
            if resource == "endurance_score" and "calendarDate" in payload:
                # `contributors` is nested metadata, not a list of dated
                # records.  Keep the DTO itself as the sole daily record.
                return [payload]
            if (
                resource == "hill_score"
                and payload.get("hillScoreDTOList") == []
                and payload.get("maxScore") is None
                and isinstance(payload.get("periodAvgScore"), dict)
                and all(value is None for value in payload["periodAvgScore"].values())
            ):
                # A supported account can have no hill-score observations in
                # the requested period.  It is an empty range, never score 0.
                return []
        records = self._advanced_records(payload) if isinstance(payload, (dict, list)) else []
        if isinstance(payload, dict) and records == [payload]:
            nested = [item for value in payload.values() if isinstance(value, list) for item in value if isinstance(item, dict)]
            if nested:
                return nested
        return records

    @staticmethod
    def _supersede_range_projection(conn: sqlite3.Connection, subject: int, resource: str, day: str) -> None:
        conn.execute(
            """DELETE FROM body_measurements
                 WHERE subject_id=? AND local_date=?
                   AND source_revision_id IN (
                       SELECT id FROM source_revisions
                        WHERE provider='garmin' AND resource_kind=?
                   )""",
            (subject, day, resource),
        )
        records = list(conn.execute("SELECT id FROM physiology_records WHERE subject_id=? AND domain='garmin' AND record_type=? AND local_date=?", (subject, resource, day)))
        if records:
            ids = tuple(row[0] for row in records)
            conn.execute("DELETE FROM physiology_metrics WHERE physiology_record_id IN (%s)" % ",".join("?" for _ in ids), ids)
            conn.execute("DELETE FROM physiology_records WHERE id IN (%s)" % ",".join("?" for _ in ids), ids)

    @staticmethod
    def _consolidate_advanced_coverage(conn: sqlite3.Connection, subject: int, resource: str, day: str) -> None:
        """Advanced lookback has one unambiguous final resource/day verdict."""
        rows = conn.execute(
            """SELECT id FROM resource_coverage WHERE subject_id=? AND provider='garmin'
               AND resource_kind=? AND local_date=? ORDER BY id DESC""",
            (subject, resource, day),
        ).fetchall()
        if len(rows) > 1:
            conn.execute(
                "DELETE FROM resource_coverage WHERE id IN (%s)" % ",".join("?" for _ in rows[1:]),
                tuple(row["id"] for row in rows[1:]),
            )

    @staticmethod
    def _health_payload_state(payload: Any, empty_state: str) -> str | None:
        """Recognise only explicit provider capability states; null never means zero."""
        if payload is None or payload == [] or payload == {}:
            return empty_state
        if isinstance(payload, dict):
            state = payload.get("availability_state") or payload.get("capability_state")
            if state in {"not_enabled", "not_available", "not_supported"}:
                return str(state)
        return None

    @staticmethod
    def _timestamp_utc(
        value: Any,
        fallback_day: str,
        *,
        allow_day_boundary: bool = False,
        assume_utc: bool = False,
    ) -> str:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            # Garmin epoch timestamps appear in seconds or milliseconds.
            seconds = float(value) / 1000 if abs(value) > 10_000_000_000 else float(value)
            try:
                return datetime.fromtimestamp(seconds, UTC).isoformat().replace("+00:00", "Z")
            except (OverflowError, OSError, ValueError):
                pass
        if isinstance(value, str) and value:
            # JSON object keys are strings.  Garmin's ``sleepLevelsMap`` and
            # hourly maps therefore expose epoch seconds/milliseconds as text,
            # even though the same endpoint uses numeric values in arrays.
            # Test this before ISO parsing: ``fromisoformat`` cannot identify
            # an epoch key and would otherwise silently fall back to midnight.
            candidate_number = value.strip()
            try:
                if candidate_number and candidate_number.lstrip("+-").replace(".", "", 1).isdigit():
                    seconds = float(candidate_number)
                    seconds = seconds / 1000 if abs(seconds) > 10_000_000_000 else seconds
                    return datetime.fromtimestamp(seconds, UTC).isoformat().replace("+00:00", "Z")
            except (OverflowError, OSError, ValueError):
                pass
            # ``datetime.fromisoformat('YYYY-MM-DD')`` silently creates
            # midnight.  Date-only input is legal only for resource specs
            # which explicitly model a local-day aggregate.
            if len(value) == 10:
                try:
                    parsed_day = date.fromisoformat(value)
                except ValueError:
                    parsed_day = None
                if parsed_day is not None:
                    if not allow_day_boundary:
                        raise ValueError("date_only_timestamp_not_allowed")
                    return datetime.combine(parsed_day, datetime.min.time(), TZ).astimezone(UTC).isoformat().replace("+00:00", "Z")
            candidate = value.replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(candidate)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC if assume_utc else TZ)
                return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
            except ValueError:
                pass
        if value is not None or not allow_day_boundary:
            raise ValueError("invalid_or_missing_timestamp")
        return datetime.combine(date.fromisoformat(fallback_day), datetime.min.time(), TZ).astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _local_day(timestamp_utc: str) -> str:
        return datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00")).astimezone(TZ).date().isoformat()

    @staticmethod
    def _numeric_fields(value: Any, path: str = "") -> Iterable[tuple[str, float]]:
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() in {"timestamp", "timestampgmt", "starttimestampgmt", "endtimestampgmt", "sleepstarttimestampgmt", "sleependtimestampgmt"}:
                    continue
                yield from GarminCollectionTool._numeric_fields(child, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for child in value:
                yield from GarminCollectionTool._numeric_fields(child, path)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            yield path or "value", float(value)

    def _upsert_daily_health(self, conn: sqlite3.Connection, subject: int, day: str, resource: str, payload: Any, revision: int) -> None:
        """Store only reviewed scalar daily facts, never an endpoint payload."""
        prior = conn.execute("SELECT values_json,extras_json,source_map_json FROM daily_health WHERE subject_id=? AND local_date=? AND is_current=1", (subject, day)).fetchone()
        values = json.loads(prior["values_json"]) if prior else {}
        extras = json.loads(prior["extras_json"]) if prior else {}
        source_map = json.loads(prior["source_map_json"]) if prior else {}
        for metric in DAILY_SCALAR_METRICS.get(resource, {}).values():
            values.pop(metric[0], None)
            source_map.pop(metric[0], None)
        if isinstance(payload, dict):
            for source, metric in DAILY_SCALAR_METRICS.get(resource, {}).items():
                value = payload.get(source)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    values[metric[0]] = float(value)
                    source_map[metric[0]] = {
                        "source_revision_id": revision,
                        "source_path": metric[4],
                        "raw_unit": metric[1],
                        "canonical_unit": metric[2],
                        "value_origin": metric[3],
                    }
                    self.repo.map_field(conn, resource, metric[4], metric[0])
        conn.execute("UPDATE daily_health SET is_current=0 WHERE subject_id=? AND local_date=? AND is_current=1", (subject, day))
        if values:
            conn.execute("INSERT INTO daily_health(subject_id,local_date,values_json,extras_json,source_map_json,source_revision_id,is_current) VALUES(?,?,?,?,?,?,1)", (subject, day, stable_json(values).decode("utf-8"), json.dumps(extras, sort_keys=True, allow_nan=False), json.dumps(source_map, sort_keys=True, allow_nan=False), revision))

    def _clear_daily_health_resource(self, conn: sqlite3.Connection, subject: int, day: str, resource: str) -> None:
        prior = conn.execute("SELECT values_json,extras_json,source_map_json,source_revision_id FROM daily_health WHERE subject_id=? AND local_date=? AND is_current=1", (subject, day)).fetchone()
        if prior is None:
            return
        values, extras, source_map = (json.loads(prior[column]) for column in ("values_json", "extras_json", "source_map_json"))
        for metric in DAILY_SCALAR_METRICS.get(resource, {}).values():
            values.pop(metric[0], None)
            source_map.pop(metric[0], None)
        conn.execute("UPDATE daily_health SET is_current=0 WHERE subject_id=? AND local_date=? AND is_current=1", (subject, day))
        if values:
            conn.execute("INSERT INTO daily_health(subject_id,local_date,values_json,extras_json,source_map_json,source_revision_id,is_current) VALUES(?,?,?,?,?,?,1)", (subject, day, json.dumps(values, sort_keys=True, allow_nan=False), json.dumps(extras, sort_keys=True, allow_nan=False), json.dumps(source_map, sort_keys=True, allow_nan=False), prior["source_revision_id"]))

    def _assert_sample_day(
        self,
        stamp: str,
        requested_day: str,
        *,
        allow_next_midnight: bool = False,
    ) -> None:
        observed = datetime.fromisoformat(
            stamp.replace("Z", "+00:00")
        ).astimezone(TZ)
        requested = date.fromisoformat(requested_day)
        if observed.date() == requested:
            return
        # Garmin's completed-day respiration stream is a closed interval: its
        # final observation is exactly 00:00 on the following local day.  Keep
        # that real timestamp, but do not relax the boundary for any other
        # resource or for a later time on the following day.
        if (
            allow_next_midnight
            and observed.date() == requested + timedelta(days=1)
            and observed.time() == datetime.min.time()
        ):
            return
        raise ValueError("timestamp_outside_requested_day")

    def _project_samples(self, conn: sqlite3.Connection, subject: int, resource: str, day: str, payload: Any, revision: int) -> int:
        """Project direct samples plus documented Garmin timestamp/value containers.

        The pinned client returns a mixture of record lists and nested arrays:
        for example ``bodyBatteryValuesArray`` is ``[[epoch_ms, level], ...]``.
        Treating the parent object as a single record loses every observed-at
        timestamp.  Recognised series are normalised first and excluded from the
        generic recursive pass; unknown fields remain in the archived raw JSON
        and source-field catalog rather than rejecting the whole resource.
        """
        series = CANONICAL_SERIES_METRICS.get(resource)
        direct_metrics = CANONICAL_SAMPLE_METRICS.get(resource, {})
        records = payload if isinstance(payload, list) else [payload]
        inserted = 0
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            recognised: set[str] = set()
            if series is not None:
                field, canonical_key, raw_unit, origin, source_path = series
                values = record.get(field)
                if values is not None:
                    recognised.add(field)
                    if not isinstance(values, list):
                        raise ValueError("invalid_series_container")
                    for point_index, point in enumerate(values):
                        # The catalog declares timestamp/value tuples as exactly
                        # arity two. Extra tuple values are schema drift, not
                        # invented `*_2` canonical metrics.
                        if not isinstance(point, (list, tuple)) or len(point) != 2:
                            raise ValueError("invalid_series_tuple_arity")
                        stamp = self._timestamp_utc(point[0], day)
                        self._assert_sample_day(
                            stamp,
                            day,
                            allow_next_midnight=resource == "respiration",
                        )
                        if point[1] is None:
                            # Garmin uses null to represent a missing sensor
                            # interval.  The raw tuple remains immutable; no
                            # numeric sample is invented for this point.
                            continue
                        if not isinstance(point[1], (int, float)) or isinstance(point[1], bool):
                            raise ValueError("invalid_series_value")
                        conn.execute(
                            "INSERT INTO health_samples(subject_id,observed_at_utc,local_date,metric_key,value_number,raw_value_json,raw_unit,canonical_unit,source_revision_id) VALUES(?,?,?,?,?,?,?,?,?)",
                            (subject, stamp, self._local_day(stamp), canonical_key, float(point[1]), json.dumps({"sample_index": index, "series_index": point_index}, sort_keys=True, allow_nan=False), raw_unit, raw_unit, revision),
                        )
                        self.repo.map_field(conn, resource, source_path, canonical_key)
                        inserted += 1
            # Do not recursively flatten recognised timestamp/value containers:
            # their timestamps were handled above.  Preserve any other provider
            # fields (including future drift) through the generic path.
            generic_record = {key: value for key, value in record.items() if key not in recognised}
            if direct_metrics:
                timestamp_fields = (
                    "timestamp",
                    "timestampGMT",
                    "startTimeGMT",
                    "startTimestampGMT",
                    "startGMT",
                )
                timestamp_key = next(
                    (
                        key
                        for key in timestamp_fields
                        if generic_record.get(key) is not None
                    ),
                    None,
                )
                timestamp = (
                    generic_record.get(timestamp_key)
                    if timestamp_key is not None
                    else None
                )
                if timestamp is None and resource == "rhr":
                    timestamp = generic_record.get("calendarDate")
                def direct_value(source: str) -> Any:
                    # Older Connect daily SpO₂ responses have a reviewed
                    # lowercase scalar spelling; the canonical key remains
                    # the same and the exact raw source path is catalogued.
                    if source == "spO2" and source not in generic_record:
                        return generic_record.get("spo2")
                    return generic_record.get(source)

                meaningful_direct = any(
                    isinstance(direct_value(source), (int, float))
                    and not isinstance(direct_value(source), bool)
                    for source in direct_metrics
                )
                if meaningful_direct and timestamp is not None:
                    stamp = self._timestamp_utc(
                        timestamp,
                        day,
                        allow_day_boundary=resource == "rhr",
                        assume_utc=bool(
                            timestamp_key
                            and (
                                "GMT" in timestamp_key
                                or timestamp_key.endswith("UTC")
                            )
                        ),
                    )
                    self._assert_sample_day(stamp, day)
                    for source, metric in direct_metrics.items():
                        value = direct_value(source)
                        if not isinstance(value, (int, float)) or isinstance(value, bool):
                            continue
                        conn.execute(
                            "INSERT INTO health_samples(subject_id,observed_at_utc,local_date,metric_key,value_number,raw_value_json,raw_unit,canonical_unit,source_revision_id) VALUES(?,?,?,?,?,?,?,?,?)",
                            (subject, stamp, self._local_day(stamp), metric[0], float(value), json.dumps({"sample_index": index}, sort_keys=True, allow_nan=False), metric[1], metric[2], revision),
                        )
                        source_path = "/spo2" if source == "spO2" and source not in generic_record else metric[4]
                        self.repo.map_field(conn, resource, source_path, metric[0])
                        inserted += 1
                elif meaningful_direct:
                    # A numeric sensor/measurement value cannot be represented
                    # as a fetched zero-record day.  Only explicitly reviewed
                    # daily aggregates are permitted to use day boundaries.
                    raise ValueError("missing_sample_timestamp")
        return inserted

    def _project_physiology(self, conn: sqlite3.Connection, subject: int, resource: str, day: str, payload: Any, revision: int) -> None:
        """Publish provider summary records without duplicating specialist streams.

        ``health_samples`` owns high-frequency timestamp/value arrays and
        ``body_measurements`` owns composition/BP observations.  This method
        stores one provenance record per meaningful provider record and only
        direct scalar summary fields as metrics.  It deliberately does not
        recursively flatten response containers: array indices are transport
        details, not stable physiological metric names.
        """
        excluded_containers = {
            "heartRateValues", "stressValuesArray", "respirationValuesArray",
            "spO2HourlyAverages", "bodyBatteryValuesArray",
            "dateWeightList", "dailyWeightSummaries", "bloodPressureSummaries",
            "bloodPressureList", "bodyCompositionSummaries", "measurements",
        }
        measurement_wrappers = (
            "dateWeightList", "dailyWeightSummaries", "bloodPressureSummaries",
            "bloodPressureList", "bodyCompositionSummaries", "measurements",
        )
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            records = [payload]
            # A BP response is a provider wrapper around individual readings.
            # Give each reading its own provenance timestamp instead of one
            # synthetic record for the enclosing range response.
            for wrapper in measurement_wrappers:
                if isinstance(payload.get(wrapper), list):
                    records = payload[wrapper]
                    break
        else:
            return
        timestamp_keys = {
            "timestamp", "timestampGMT", "startTimeGMT", "startTimestampGMT",
            "endTimeGMT", "endTimestampGMT", "calendarDate",
        }
        metric_specs = PHYSIOLOGY_SCALAR_METRICS.get(resource, {})
        for record in records:
            if not isinstance(record, dict):
                continue
            scalar_items = [
                (metric, value, metric_specs[metric])
                for metric, value in record.items()
                if metric not in timestamp_keys | excluded_containers
                and metric in metric_specs
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ]
            # A record that consists solely of an already-projected stream has
            # no separate scalar summary fact to publish.
            if not scalar_items and (
                isinstance(payload, list)
                or resource in {"hrv"}
            ):
                continue
            daily_stamp = (
                record.get("calendarDate")
                or record.get("date")
                if resource in {
                    "body_battery",
                    "intensity_minutes",
                    "hrv",
                    "body_battery_events",
                }
                else None
            )
            timestamp_key = next(
                (
                    key
                    for key in (
                        "measurementTimestampGMT",
                        "timestamp",
                        "timestampGMT",
                        "startTimeGMT",
                        "startTimestampGMT",
                        "calendarDate",
                    )
                    if record.get(key) is not None
                ),
                None,
            )
            timestamp_value = daily_stamp or (
                record.get(timestamp_key) if timestamp_key else None
            )
            has_timestamp = timestamp_value is not None
            stamp = self._timestamp_utc(
                timestamp_value,
                day,
                allow_day_boundary=bool(daily_stamp) or resource in {
                    "intensity_minutes",
                    "all_day_events",
                    "lifestyle",
                    "body_battery_events",
                },
                assume_utc=bool(
                    not daily_stamp
                    and timestamp_key
                    and (
                        "GMT" in timestamp_key
                        or timestamp_key.endswith("UTC")
                    )
                ),
            )
            if has_timestamp:
                self._assert_sample_day(stamp, day)
            cursor = conn.execute(
                "INSERT INTO physiology_records(subject_id,domain,record_type,effective_at_utc,local_date,value_origin,extras_json,source_revision_id) VALUES(?,?,?,?,?,?,?,?)",
                (subject, "garmin", resource, stamp, self._local_day(stamp), "provider_derived", stable_json(record).decode("utf-8"), revision),
            )
            record_id = int(cursor.lastrowid)
            for metric, value, spec in scalar_items:
                conn.execute(
                    "INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_number,raw_unit,canonical_unit,value_origin,source_path) VALUES(?,?,?,?,?,?,?)",
                    (record_id, spec[0], float(value), spec[1], spec[2], spec[3], spec[4]),
                )
                self.repo.map_field(conn, resource, spec[4], spec[0])

    def _project_body_measurements(self, conn: sqlite3.Connection, subject: int, resource: str, day: str, payload: Any, revision: int) -> None:
        records = payload if isinstance(payload, list) else [payload]
        if isinstance(payload, dict):
            for key in ("dateWeightList", "dailyWeightSummaries", "bloodPressureSummaries", "bloodPressureList", "bodyCompositionSummaries", "measurements"):
                if isinstance(payload.get(key), list):
                    records = payload[key]
                    break
        for item in records:
            if not isinstance(item, dict):
                continue
            timestamp_key = next(
                (
                    key
                    for key in (
                        "measurementTimestampGMT",
                        "timestamp",
                        "timestampGMT",
                        "gmtTimestamp",
                        "dateTimestamp",
                        "calendarDate",
                        "date",
                    )
                    if item.get(key) is not None
                ),
                None,
            )
            stamp = self._timestamp_utc(
                item.get(timestamp_key) if timestamp_key else None,
                day,
                allow_day_boundary=timestamp_key in {"calendarDate", "date"},
                assume_utc=bool(
                    timestamp_key
                    and (
                        "GMT" in timestamp_key
                        or timestamp_key == "gmtTimestamp"
                    )
                ),
            )
            self._assert_sample_day(stamp, day)
            conn.execute("INSERT INTO body_measurements(subject_id,observed_at_utc,local_date,values_json,extras_json,source_revision_id) VALUES(?,?,?,?,?,?)", (subject, stamp, self._local_day(stamp), stable_json(item).decode("utf-8"), "{}", revision))

    def _project_sleep(self, conn: sqlite3.Connection, subject: int, day: str, payload: Any, revision: int) -> int:
        if not isinstance(payload, dict):
            raise ValueError("sleep_payload_not_object")
        sessions = payload.get("sessions") or payload.get("sleepSessions") or []
        naps = payload.get("naps") or []
        if isinstance(naps, list):
            sessions = [*sessions, *[{**nap, "session_type": nap.get("session_type", "nap")} for nap in naps if isinstance(nap, dict)]]
        main = payload.get("dailySleepDTO")
        if isinstance(main, dict):
            main_start = (
                main.get("start_time_utc")
                or main.get("startTimeGMT")
                or main.get("sleepStartTimestampGMT")
            )
            main_end = (
                main.get("end_time_utc")
                or main.get("endTimeGMT")
                or main.get("sleepEndTimestampGMT")
            )
            # Connect returns a populated dailySleepDTO with both timestamps
            # null when no sleep session exists for that completed day.  This
            # is a valid fetched zero-record observation.  A one-sided session
            # remains invalid and is rejected below.
            if main_start is not None or main_end is not None:
                sessions = [main, *sessions]
        if not sessions and any(key in payload for key in ("sleepStartTimestampGMT", "startTimeGMT")):
            sessions = [payload]
        inserted = 0
        for session_index, item in enumerate(sessions):
            if not isinstance(item, dict):
                continue
            start = self._timestamp_utc(item.get("start_time_utc") or item.get("startTimeGMT") or item.get("sleepStartTimestampGMT"), day)
            end = self._timestamp_utc(item.get("end_time_utc") or item.get("endTimeGMT") or item.get("sleepEndTimestampGMT"), day)
            if end < start:
                raise ValueError("sleep_session_end_before_start")
            kind = item.get("session_type") or item.get("sleepType") or ("nap" if item.get("isNap") else "main_sleep")
            kind = kind if kind in {"main_sleep", "nap"} else "unknown"
            cursor = conn.execute("INSERT INTO sleep_sessions(subject_id,session_type,start_time_utc,end_time_utc,values_json,extras_json,source_map_json,source_revision_id) VALUES(?,?,?,?,?,?,?,?)", (subject, kind, start, end, stable_json(item).decode("utf-8"), "{}", json.dumps({"source_revision_id": revision}, allow_nan=False), revision))
            session_id = int(cursor.lastrowid)
            stages = item.get("stages") or item.get("sleepStages") or []
            # Garmin daily sleep payloads may expose stage changes as an epoch
            # map rather than an array.  Derive bounded intervals without
            # inventing values when the map is absent.
            if not stages and isinstance(item.get("sleepLevelsMap"), dict):
                points = sorted((self._timestamp_utc(mark, day), level) for mark, level in item["sleepLevelsMap"].items())
                stages = [
                    {"stage_type": str(level), "start_time_utc": begin, "end_time_utc": points[index + 1][0] if index + 1 < len(points) else end}
                    for index, (begin, level) in enumerate(points)
                ]
            for stage_index, stage in enumerate(stages):
                if not isinstance(stage, dict):
                    continue
                stage_start = self._timestamp_utc(stage.get("start_time_utc") or stage.get("startTimeGMT") or stage.get("startTimestampGMT"), day)
                stage_end = self._timestamp_utc(stage.get("end_time_utc") or stage.get("endTimeGMT") or stage.get("endTimestampGMT"), day)
                if stage_end < stage_start or stage_start < start or stage_end > end:
                    raise ValueError("sleep_stage_outside_session")
                duration = (datetime.fromisoformat(stage_end.replace("Z", "+00:00")) - datetime.fromisoformat(stage_start.replace("Z", "+00:00"))).total_seconds()
                conn.execute("INSERT INTO sleep_stages(sleep_session_id,stage_index,stage_type,start_time_utc,end_time_utc,duration_seconds,source_revision_id) VALUES(?,?,?,?,?,?,?)", (session_id, stage_index, str(stage.get("stage_type") or stage.get("stageType") or "unknown"), stage_start, stage_end, duration, revision))
            inserted += 1
        return inserted

    def _supersede_health_projection(self, conn: sqlite3.Connection, subject: int, resource: str, provider_id: str, day: str) -> None:
        """Remove only the old current projection inside the replacement transaction."""
        revisions = [
            int(row[0])
            for row in conn.execute(
                """SELECT id FROM source_revisions WHERE provider='garmin'
                   AND resource_kind=? AND provider_object_id=? AND is_current=1""",
                (resource, provider_id),
            )
        ]
        if revisions:
            placeholders = ",".join("?" for _ in revisions)
            conn.execute(
                f"DELETE FROM health_samples WHERE subject_id=? AND source_revision_id IN ({placeholders})",
                (subject, *revisions),
            )
            conn.execute(
                f"DELETE FROM sleep_stages WHERE sleep_session_id IN (SELECT id FROM sleep_sessions WHERE subject_id=? AND source_revision_id IN ({placeholders}))",
                (subject, *revisions),
            )
            conn.execute(
                f"DELETE FROM sleep_sessions WHERE subject_id=? AND source_revision_id IN ({placeholders})",
                (subject, *revisions),
            )
            conn.execute(
                f"DELETE FROM body_measurements WHERE subject_id=? AND source_revision_id IN ({placeholders})",
                (subject, *revisions),
            )
            conn.execute(
                f"""DELETE FROM physiology_metrics WHERE physiology_record_id IN
                    (SELECT id FROM physiology_records WHERE subject_id=? AND source_revision_id IN ({placeholders}))""",
                (subject, *revisions),
            )
            conn.execute(
                f"DELETE FROM physiology_records WHERE subject_id=? AND source_revision_id IN ({placeholders})",
                (subject, *revisions),
            )
        self._clear_daily_health_resource(conn, subject, day, resource)

    @staticmethod
    def _safe_advanced_payload(resource: str, payload: Any) -> Any:
        """Return the provider response byte-for-byte semantically intact.

        Raw objects are evidence, not a redacted derivative.  Credential-like
        fields are the sole exception: their presence is quarantined before any
        archive/write, because persisting a token would violate the secret
        boundary.  Canonical projection below remains allow-listed.
        """
        return validate_provider_json_payload(payload)

    @staticmethod
    def _advanced_records(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            raise ValueError("advanced_payload_not_object")
        for wrapper in ("trainingReadiness", "racePredictions", "calendarEntries", "foodLog", "meals", "items", "data"):
            value = payload.get(wrapper)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return [value]
        return [payload]

    def _project_advanced(self, conn: sqlite3.Connection, subject: int, resource: str, day: str, payload: Any, revision: int) -> int:
        specs = ADVANCED_PHYSIOLOGY_METRICS[resource]
        if (
            resource == "lactate_threshold"
            and isinstance(payload, list)
            and any(
                isinstance(record, dict)
                and "__trainlab_lactate_family" in record
                for record in payload
            )
        ):
            inserted = 0
            lactate_specs = {
                "heart_rate": specs["lactateThresholdHeartRate"],
                "power": specs["lactateThresholdPower"],
                "speed": specs["lactateThresholdSpeed"],
            }
            for index, record in enumerate(payload):
                if not isinstance(record, dict):
                    continue
                family = record.get("__trainlab_lactate_family")
                spec = lactate_specs.get(family)
                value = record.get("value")
                if spec is None or not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                stamp = self._timestamp_utc(
                    record.get("updatedDate"), day, allow_day_boundary=True,
                )
                self._assert_sample_day(stamp, day)
                cursor = conn.execute(
                    """INSERT INTO physiology_records(subject_id,domain,record_type,provider_record_id,effective_at_utc,local_date,value_origin,extras_json,source_revision_id)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (subject, "garmin", resource, f"{family}:{index}", stamp,
                     self._local_day(stamp), "provider_derived", "{}", revision),
                )
                source_path = f"/{family}/*/value"
                conn.execute(
                    """INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_number,raw_unit,canonical_unit,value_origin,source_path)
                       VALUES(?,?,?,?,?,?,?)""",
                    (int(cursor.lastrowid), spec[0], float(value), spec[1], spec[2], spec[3], source_path),
                )
                self.repo.map_field(conn, resource, source_path, spec[0])
                inserted += 1
            return inserted
        records = self._advanced_records(payload)
        prefix = "/*/" if isinstance(payload, list) else "/"
        if isinstance(payload, dict):
            for wrapper in ("trainingReadiness", "racePredictions", "calendarEntries", "foodLog", "meals", "items", "data"):
                if isinstance(payload.get(wrapper), list):
                    prefix = f"/{wrapper}/*/"
                    break
                if isinstance(payload.get(wrapper), dict):
                    prefix = f"/{wrapper}/"
                    break
        inserted = 0
        for index, record in enumerate(records):
            scalars = [(field, value, specs[field]) for field, value in record.items() if field in specs and isinstance(value, (int, float)) and not isinstance(value, bool)]
            # These are provider daily/range summaries.  Their calendar date is
            # authoritative for the observation day; timestamps may describe
            # a contributing sleep/recovery interval crossing midnight.
            timestamp_value = next(
                (
                    record.get(field)
                    for field in (
                        "calendarDate",
                        "date",
                        "timestamp",
                        "timestampGMT",
                        "startTimeGMT",
                        "startTimestampGMT",
                    )
                    if record.get(field) is not None
                ),
                None,
            )
            # These endpoints are daily/range provider summaries. A missing
            # timestamp means the requested Singapore day boundary, never an
            # invented high-frequency sample time.
            stamp = self._timestamp_utc(timestamp_value, day, allow_day_boundary=True)
            self._assert_sample_day(stamp, day)
            cursor = conn.execute(
                """INSERT INTO physiology_records(subject_id,domain,record_type,provider_record_id,effective_at_utc,local_date,value_origin,extras_json,source_revision_id)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (subject, "garmin", resource, str(index), stamp, self._local_day(stamp), "provider_predicted" if resource == "race_predictions" else "provider_derived", "{}", revision),
            )
            record_id = int(cursor.lastrowid)
            for field, value, spec in scalars:
                source_path = prefix + field
                conn.execute(
                    """INSERT INTO physiology_metrics(physiology_record_id,metric_key,value_number,raw_unit,canonical_unit,value_origin,source_path)
                       VALUES(?,?,?,?,?,?,?)""",
                    (record_id, spec[0], float(value), spec[1], spec[2], spec[3], source_path),
                )
                self.repo.map_field(conn, resource, source_path, spec[0])
            inserted += 1
        known_empty_wrapper = isinstance(payload, dict) and any(
            wrapper in payload
            for wrapper in (
                "trainingReadiness",
                "racePredictions",
                "calendarEntries",
                "foodLog",
                "meals",
                "items",
                "data",
            )
        )
        if payload not in ({}, [], None) and not records and not known_empty_wrapper:
            raise ValueError("advanced_payload_shape")
        return inserted

    def _project_health(self, conn: sqlite3.Connection, subject: int, resource: str, day: str, payload: Any, revision: int) -> int:
        """Project one reviewed base resource inside the publisher transaction.

        Raw JSON and source-field discovery happen before this method.  A
        parse or projection exception therefore rolls back only this revision's
        canonical rows while retaining the raw object for repair.
        """
        if resource in ADVANCED_RESOURCES:
            return self._project_advanced(conn, subject, resource, day, payload, revision)
        daily_resources = {
            "user_summary", "steps", "floors", "heart_rates", "rhr", "hydration",
            "respiration", "spo2", "intensity_minutes", "stress",
        }
        sampled_resources = {
            "steps", "floors", "heart_rates", "rhr", "respiration", "spo2", "stress", "hrv", "body_battery",
        }
        physiology_resources = {
            "intensity_minutes", "all_day_events", "lifestyle", "hrv", "body_battery",
            "body_battery_events", "blood_pressure",
        }
        body_resources = {"body_composition", "weigh_ins", "blood_pressure"}
        projected = 0
        if resource in daily_resources:
            self._upsert_daily_health(conn, subject, day, resource, payload, revision)
            if any(
                isinstance(payload.get(source), (int, float)) and not isinstance(payload.get(source), bool)
                for source in DAILY_SCALAR_METRICS.get(resource, {})
            ) if isinstance(payload, dict) else False:
                projected += 1
        if resource in sampled_resources:
            projected += self._project_samples(conn, subject, resource, day, payload, revision)
        if resource == "sleep":
            projected += self._project_sleep(conn, subject, day, payload, revision)
        if resource in body_resources:
            self._project_body_measurements(conn, subject, resource, day, payload, revision)
            projected += 1
        if resource in physiology_resources or resource not in daily_resources | sampled_resources | body_resources | {"sleep"}:
            self._project_physiology(conn, subject, resource, day, payload, revision)
            projected += 1
        return projected

    def _activities_pre_l2_10_unused(self, conn: sqlite3.Connection, run: int, subject: int, start: date, through: date, request: SyncRequest, receipt: SyncReceipt) -> None:
        # Retained only temporarily to keep historical line references stable;
        # it is deliberately sealed so the pre-L2-11 ZIP/FIT path can never
        # become a second runtime implementation.
        raise RuntimeError("obsolete_activity_pipeline_unreachable")
        inventory_key = "garmin:inventory:activities"
        try:
            activities = list(self._call(
                lambda: self._transport().list_activities(start.isoformat(), through.isoformat()),
                conn=conn, run=run, subject=subject, resource="activity_inventory", key=inventory_key,
                stage="discover",
            ))
            # Inventory is provider JSON too.  Validate the complete listing
            # before reading even one activity ID so a quarantined later item
            # cannot leave earlier summary/canonical writes behind.
            validate_provider_json_payload(activities)
            self.repo.item(conn, run, "activity_inventory", inventory_key, "discover", "fetched", increment_attempt=False)
        except GarminError as exc:
            outcome = self._classify(exc)
            if outcome.status == "auth_required":
                raise GarminError("auth_required", http_status=401) from None
            deferred = outcome.status == "deferred"
            retry = self._next_retry(exc, 0) if deferred else None
            terminal = "deferred" if deferred else ("forbidden" if outcome.status == "forbidden" else "failed")
            self.repo.item(conn, run, "activity_inventory", inventory_key, "discover", terminal, error=exc, next_retry=retry, increment_attempt=False)
            self.repo.gap(conn, subject, "activity_inventory", inventory_key, start.isoformat(), "discover", exc.code, deferred=deferred, next_retry=retry)
            receipt.counts["deferred" if deferred else "failed"] += 1
            receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
            return
        for item in activities:
            activity_id = str(item.get("activityId") or item.get("id")); key = f"garmin:activity:{activity_id}"
            if not activity_id or activity_id == "None": continue
            try:
                summary = self._call(
                    lambda aid=activity_id: self._transport().activity_summary(aid),
                    conn=conn, run=run, subject=subject, resource="activity_summary", key=key,
                    allows_404=False,
                )
                validate_provider_json_payload(summary)
                self.repo.item(conn, run, "activity_summary", key, "fetch", "fetched", increment_attempt=False)
                activity_box={}
                def summary_projector(revision: int): activity_box["id"]=self._project_activity_pre_l2_10_unused(conn, subject, activity_id, summary, revision)
                _, revision, changed = self.repo.archive(conn, "activity_summary", activity_id, canonical_provider_json(summary), "json", "application/json", summary_projector)
                activity=activity_box.get("id") or int(conn.execute("SELECT id FROM activities WHERE provider='garmin' AND provider_activity_id=?",(activity_id,)).fetchone()[0])
                self.repo.item(conn, run, "activities", key, "project", "revised" if changed else "unchanged", revision_id=revision); receipt.counts["revised" if changed else "unchanged"] += 1
                try:
                    fit = self._extract_fit(self._call(
                        lambda aid=activity_id: self._transport().activity_original(aid),
                        conn=conn, run=run, subject=subject, resource="activity_fit", key=key,
                        allows_404=True,
                    ))
                    self.repo.item(conn, run, "activity_fit", key, "fetch", "fetched", increment_attempt=False)
                    def fit_projector(fit_rev: int):
                        self._project_fit(conn, activity, fit, fit_rev); conn.execute("UPDATE activity_source_revisions SET is_active=0 WHERE activity_id=? AND source_role='activity_fit'", (activity,)); conn.execute("INSERT OR IGNORE INTO activity_source_revisions(activity_id,source_revision_id,source_role,is_active) VALUES(?,?,?,1)", (activity, fit_rev, "activity_fit"))
                    _, fit_rev, fit_changed = self.repo.archive(conn, "activity_fit", activity_id, fit, "fit", "application/octet-stream", fit_projector); self.repo.item(conn, run, "activities", key, "parse", "revised" if fit_changed else "unchanged", revision_id=fit_rev)
                except GarminError as exc:
                    outcome = self._classify(exc, allows_404=True)
                    if outcome.status == "auth_required":
                        raise GarminError("auth_required", http_status=401) from None
                    deferred = outcome.status == "deferred"
                    terminal = "not_available" if outcome.status == "not_available" else ("forbidden" if outcome.status == "forbidden" else ("deferred" if deferred else "failed"))
                    retry = self._next_retry(exc, 0) if deferred else None
                    self.repo.gap(conn, subject, "activity_fit", key, start.isoformat(), "extract", exc.code, deferred=deferred, next_retry=retry)
                    self.repo.item(conn, run, "activity_fit", key, "fetch", terminal, error=exc, next_retry=retry, increment_attempt=False)
                    receipt.counts["deferred" if deferred else "failed"] += 1
                    receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
                except ValueError as exc:
                    self.repo.gap(conn, subject, "activities", key, start.isoformat(), "extract", "invalid_fit"); self.repo.item(conn, run, "activities", key, "extract", "failed", error=GarminError("invalid_fit")); receipt.counts["failed"] += 1
                except Exception:
                    error = GarminError("activity_parse_or_project_failed")
                    self.repo.gap(conn, subject, "activities", key, start.isoformat(), "parse", error.code)
                    self.repo.item(conn, run, "activities", key, "parse", "failed", error=error)
                    receipt.counts["failed"] += 1
                for role in EXTRA_ROLES:
                    try:
                        extra = self._call(
                            lambda aid=activity_id, r=role: self._transport().activity_extra(aid, r),
                            conn=conn, run=run, subject=subject, resource=role, key=key,
                            allows_404=True,
                        )
                        validate_provider_json_payload(extra)
                        self.repo.item(conn, run, role, key, "fetch", "fetched", increment_attempt=False)
                        if extra in (None, {}, []): continue
                        def extra_projector(extra_revision: int) -> None:
                            conn.execute(
                                """UPDATE activity_source_revisions SET is_active=0
                                   WHERE activity_id=? AND source_role=?""",
                                (activity, role),
                            )
                            conn.execute(
                                """INSERT OR IGNORE INTO activity_source_revisions(
                                       activity_id,source_revision_id,source_role,is_active
                                   ) VALUES(?,?,?,1)""",
                                (activity, extra_revision, role),
                            )

                        _, extra_revision, extra_changed = self.repo.archive(
                            conn,
                            role,
                            activity_id,
                            canonical_provider_json(extra),
                            "json",
                            "application/json",
                            extra_projector,
                        )
                        self.repo.item(
                            conn,
                            run,
                            role,
                            key,
                            "project",
                            "revised" if extra_changed else "unchanged",
                            revision_id=extra_revision,
                        )
                    except GarminError as exc:
                        outcome = self._classify(exc, allows_404=True)
                        if outcome.status == "auth_required":
                            raise GarminError("auth_required", http_status=401) from None
                        deferred = outcome.status == "deferred"
                        terminal = "not_available" if outcome.status == "not_available" else ("forbidden" if outcome.status == "forbidden" else ("deferred" if deferred else "failed"))
                        retry = self._next_retry(exc, 0) if deferred else None
                        self.repo.item(conn, run, role, key, "fetch", terminal, error=exc, next_retry=retry, increment_attempt=False)
                        self.repo.gap(conn, subject, role, key, start.isoformat(), "fetch", exc.code, deferred=deferred, next_retry=retry)
                        receipt.counts["deferred" if deferred else "failed"] += 1
                        receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
                    except Exception:
                        error = GarminError("activity_extra_project_failed")
                        self.repo.gap(conn, subject, role, key, start.isoformat(), "project", error.code)
                        self.repo.item(conn, run, role, key, "project", "failed", error=error)
                        receipt.counts["failed"] += 1
            except GarminError as exc:
                outcome = self._classify(exc)
                if outcome.status == "auth_required":
                    raise GarminError("auth_required", http_status=401) from None
                deferred = outcome.status == "deferred"
                terminal = "forbidden" if outcome.status == "forbidden" else ("deferred" if deferred else "failed")
                retry = self._next_retry(exc, 0) if deferred else None
                self.repo.item(conn, run, "activity_summary", key, "fetch", terminal, error=exc, next_retry=retry, increment_attempt=False)
                self.repo.gap(conn, subject, "activity_summary", key, start.isoformat(), "fetch", exc.code, deferred=deferred, next_retry=retry)
                receipt.counts["deferred" if deferred else "failed"] += 1
                receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
            except Exception:
                error = GarminError("activity_summary_project_failed")
                self.repo.item(conn, run, "activities", key, "project", "failed", error=error)
                self.repo.gap(conn, subject, "activities", key, start.isoformat(), "project", error.code)
                receipt.counts["failed"] += 1

    def _project_activity_pre_l2_10_unused(self, conn: sqlite3.Connection, subject: int, provider_id: str, summary: dict[str, Any], revision: int) -> int:
        start = str(summary.get("startTimeGMT") or summary.get("start_time_utc") or "1970-01-01T00:00:00Z")
        if not start.endswith("Z"): start += "Z"
        local = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(TZ).date().isoformat()
        conn.execute("""INSERT INTO activities(subject_id,provider,provider_activity_id,name,sport,sub_sport,start_time_utc,end_time_utc,local_date,elapsed_seconds,timer_seconds,distance_m,extras_json,source_map_json,primary_revision_id,provider_state)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active') ON CONFLICT(provider,provider_activity_id) DO UPDATE SET name=excluded.name,sport=excluded.sport,sub_sport=excluded.sub_sport,primary_revision_id=excluded.primary_revision_id,provider_state='active'""", (subject, "garmin", provider_id, summary.get("activityName"), summary.get("activityType", {}).get("typeKey") if isinstance(summary.get("activityType"), dict) else summary.get("activityType"), summary.get("activityType", {}).get("typeKey") if isinstance(summary.get("activityType"), dict) else None, start, summary.get("endTimeGMT"), local, summary.get("duration"), summary.get("movingDuration"), summary.get("distance"), stable_json(summary).decode("utf-8"), json.dumps({"summary": "garmin"}, allow_nan=False), revision))
        activity = int(conn.execute("SELECT id FROM activities WHERE provider='garmin' AND provider_activity_id=?", (provider_id,)).fetchone()[0])
        conn.execute("UPDATE activity_source_revisions SET is_active=0 WHERE activity_id=? AND source_role='summary_json'", (activity,)); conn.execute("INSERT OR IGNORE INTO activity_source_revisions(activity_id,source_revision_id,source_role,is_active) VALUES(?,?,?,1)", (activity, revision, "summary_json")); return activity

    def _activities(self, conn: sqlite3.Connection, run: int, subject: int, start: date, through: date, request: SyncRequest, receipt: SyncReceipt, collect_fit: bool = False) -> None:
        """L2-10 inventory and summary pipeline; FIT/enrichments are later units."""
        inventory_key = self._activity_inventory_key(request, start, through)
        if request.activity_ids:
            entries = [{"activityId": activity_id} for activity_id in request.activity_ids]
            inventory_complete = False
        else:
            entries, inventory_complete = self._collect_activity_inventory(
                conn, run, subject, start, through, request, receipt, inventory_key
            )
        if not entries and not inventory_complete:
            return

        unique_entries: dict[str, dict[str, Any]] = {}
        duplicate = False
        for entry in entries:
            try:
                activity_id = self._activity_inventory_id(entry)
            except ValueError:
                inventory_complete = False
                duplicate = False
                break
            if activity_id in unique_entries:
                duplicate = True
                continue
            unique_entries[activity_id] = entry
        if duplicate:
            inventory_complete = False
            error = GarminError("activity_inventory_duplicate_ids")
            self.repo.item(conn, run, "activity_inventory", inventory_key, "validate", "failed", error=error, increment_attempt=False)
            self.repo.gap(conn, subject, "activity_inventory", inventory_key, start.isoformat(), "validate", error.code, end_day=through.isoformat())
            receipt.counts["failed"] += 1

        applicable_ids: set[str] = set()
        for activity_id, entry in unique_entries.items():
            # Presence in a provider inventory is sufficient to protect or
            # reactivate an existing local activity even if summary refresh
            # later fails. Date bounds are applied by the state query itself.
            applicable_ids.add(activity_id)
            entry_day = self._activity_inventory_local_date(entry)
            if entry_day is not None and not self._activity_date_in_scope(entry_day, start, through, request.mode):
                continue
            self._collect_activity_summary(
                conn, run, subject, activity_id, start, through, request,
                receipt, applicable_ids,
            )
            activity = conn.execute("SELECT id,start_time_utc,sport,local_date FROM activities WHERE subject_id=? AND provider='garmin' AND provider_activity_id=?", (subject, activity_id)).fetchone()
            if activity is not None:
                fit_outcome = "not_requested"
                if collect_fit:
                    fit_outcome = self._collect_activity_fit(
                        conn, run, subject, activity_id, int(activity["id"]),
                        str(activity["start_time_utc"]), str(activity["sport"]),
                        date.fromisoformat(str(activity["local_date"])), receipt,
                    )
                selected = set(request.resource_kinds)
                collect_l2_12 = collect_fit or bool(
                    selected.intersection(
                        ACTIVITY_ENRICHMENT_RESOURCES | {"activity_details_fallback"}
                    )
                )
                if collect_l2_12:
                    for resource, role in ACTIVITY_ENRICHMENTS:
                        if not selected or resource in selected:
                            self._collect_activity_enrichment(
                                conn, run, subject, activity_id, int(activity["id"]),
                                str(activity["sport"]), date.fromisoformat(str(activity["local_date"])),
                                resource, role, receipt,
                            )
                fallback_requested = (
                    "activity_details_fallback" in selected
                    or (
                        not selected
                        and collect_fit
                        and fit_outcome in {"not_available", "not_supported", "invalid"}
                    )
                )
                if fallback_requested and not self._has_active_fit(conn, int(activity["id"])):
                    self._collect_activity_chart_fallback(
                        conn, run, subject, activity_id, int(activity["id"]),
                        date.fromisoformat(str(activity["local_date"])), receipt,
                    )
                self._reconcile_activity(
                    conn, run, subject, activity_id, int(activity["id"]),
                    date.fromisoformat(str(activity["local_date"])), receipt,
                )

        self._apply_activity_inventory_state(
            conn, subject, applicable_ids, start, through, request.mode,
            # Every successfully completed *full run* is one inventory
            # observation, even when its raw page hashes equal the previous
            # full run.  A repeated invocation_id returns its persisted run
            # before reaching this method, so it cannot manufacture another
            # observation.  Incremental/snapshot windows are not comparable
            # full inventories and can only reactivate activities they see.
            complete=request.mode == "full" and inventory_complete,
        )
        if inventory_complete:
            self.repo.capability(conn, subject, "activity_inventory", "supported", environment_key=self.config.region)
            self._publish_activity_inventory_coverage(conn, subject, applicable_ids, start, through, request)

    @staticmethod
    def _activity_inventory_key(request: SyncRequest, start: date, through: date) -> str:
        if request.mode == "full":
            return f"garmin:inventory:activities:full:through:{through.isoformat()}"
        return f"garmin:inventory:activities:{request.mode}:{start.isoformat()}:{through.isoformat()}"

    def _collect_activity_inventory(
        self,
        conn: sqlite3.Connection,
        run: int,
        subject: int,
        start: date,
        through: date,
        request: SyncRequest,
        receipt: SyncReceipt,
        inventory_key: str,
    ) -> tuple[list[dict[str, Any]], bool]:
        transport = self._transport()
        entries: list[dict[str, Any]] = []
        signatures: set[str] = set()
        current_key = inventory_key
        current_stage = "discover"
        try:
            has_paging = (
                request.mode == "full"
                and callable(getattr(transport, "activity_count", None))
                and callable(getattr(transport, "activity_page", None))
            )
            if has_paging:
                count_key = f"{inventory_key}:count"
                current_key, current_stage = count_key, "discover"
                count = self._call(
                    lambda: transport.activity_count(),
                    conn=conn, run=run, subject=subject, resource="activity_inventory",
                    key=count_key, stage="discover",
                )
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise GarminError("activity_inventory_count_invalid")
                self.repo.item(conn, run, "activity_inventory", count_key, "discover", "fetched", increment_attempt=False)
                for page_no, offset in enumerate(range(0, count, 100)):
                    limit = min(100, count - offset)
                    page_key = f"{inventory_key}:page:{page_no:06d}"
                    current_key, current_stage = page_key, "fetch"
                    payload = self._call(
                        lambda o=offset, size=limit: transport.activity_page(o, size),
                        conn=conn, run=run, subject=subject, resource="activity_inventory",
                        key=page_key,
                    )
                    current_stage = "validate"
                    page_entries, signature, _changed = self._archive_activity_inventory_page(
                        conn, run, receipt, page_key, payload, expected_size=limit,
                    )
                    if signature in signatures:
                        raise GarminError("activity_inventory_paging_loop")
                    signatures.add(signature)
                    entries.extend(page_entries)
                # Preserve the successful empty page as raw inventory
                # evidence.  The full run itself is the observation identity.
                if count == 0:
                    page_key = f"{inventory_key}:page:000000"
                    current_key, current_stage = page_key, "validate"
                    page_entries, signature, _changed = self._archive_activity_inventory_page(
                        conn, run, receipt, page_key, [], expected_size=0,
                    )
                    entries.extend(page_entries)
                    signatures.add(signature)
                final_key = f"{inventory_key}:count-final"
                current_key, current_stage = final_key, "discover"
                final_count = self._call(
                    lambda: transport.activity_count(),
                    conn=conn, run=run, subject=subject, resource="activity_inventory",
                    key=final_key, stage="discover",
                )
                if isinstance(final_count, bool) or not isinstance(final_count, int) or final_count != count:
                    raise GarminError("activity_inventory_count_drift")
                self.repo.item(conn, run, "activity_inventory", final_key, "discover", "fetched", increment_attempt=False)
            else:
                page_key = f"{inventory_key}:page:000000"
                current_key, current_stage = page_key, "fetch"
                bounded_start = None if request.mode == "full" else start.isoformat()
                payload = self._call(
                    lambda: list(transport.list_activities(bounded_start, through.isoformat())),
                    conn=conn, run=run, subject=subject, resource="activity_inventory",
                    key=page_key,
                )
                current_stage = "validate"
                entries, _signature, _changed = self._archive_activity_inventory_page(
                    conn, run, receipt, page_key, payload, expected_size=None,
                )
            self.repo.item(conn, run, "activity_inventory", inventory_key, "discover", "fetched", increment_attempt=False)
            return entries, True
        except GarminError as exc:
            if exc.http_status == 401:
                raise GarminError("auth_required", http_status=401) from None
            outcome = self._classify(exc)
            deferred = outcome.status == "deferred"
            retry = self._next_retry(exc, 0) if deferred else None
            terminal = "forbidden" if outcome.status == "forbidden" else ("deferred" if deferred else "failed")
            self.repo.item(conn, run, "activity_inventory", current_key, current_stage, terminal, error=exc, next_retry=retry, increment_attempt=False)
            self.repo.item(conn, run, "activity_inventory", inventory_key, "discover", terminal, error=exc, next_retry=retry, increment_attempt=False)
            self.repo.gap(conn, subject, "activity_inventory", current_key, start.isoformat(), current_stage, exc.code, end_day=through.isoformat(), deferred=deferred, next_retry=retry)
            receipt.counts["deferred" if deferred else "failed"] += 1
            receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
            return entries, False

    def _archive_activity_inventory_page(
        self,
        conn: sqlite3.Connection,
        run: int,
        receipt: SyncReceipt,
        page_key: str,
        payload: Any,
        *,
        expected_size: int | None,
    ) -> tuple[list[dict[str, Any]], str, bool]:
        page_box: dict[str, list[dict[str, Any]]] = {}
        def projector(_revision: int) -> None:
            page_box["entries"] = self._validate_activity_inventory_page(payload, expected_size)
            self.repo.fields(conn, "activity_inventory", payload)
        try:
            _, revision, changed = self.repo.archive(
                conn, "activity_inventory", page_key, canonical_provider_json(payload),
                "json", "application/json", projector,
            )
        except GarminError:
            raise
        except ValueError as exc:
            code = str(exc)
            if code not in {
                "activity_inventory_page_invalid",
                "activity_inventory_page_size_mismatch",
                "activity_inventory_id_invalid",
            }:
                code = "activity_inventory_page_invalid"
            raise GarminError(code) from None
        if not changed:
            page_box["entries"] = self._validate_activity_inventory_page(payload, expected_size)
        self.repo.item(
            conn, run, "activity_inventory", page_key, "fetch",
            "revised" if changed else "unchanged",
            revision_id=revision,
            increment_attempt=False,
        )
        receipt.counts["revised" if changed else "unchanged"] += 1
        return page_box["entries"], digest(canonical_provider_json(payload)), changed

    @staticmethod
    def _validate_activity_inventory_page(payload: Any, expected_size: int | None) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            entries = payload
        elif isinstance(payload, dict) and isinstance(payload.get("activities"), list):
            entries = payload["activities"]
        else:
            raise ValueError("activity_inventory_page_invalid")
        if expected_size is not None and len(entries) != expected_size:
            raise ValueError("activity_inventory_page_size_mismatch")
        result: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("activity_inventory_page_invalid")
            GarminCollectionTool._activity_inventory_id(entry)
            result.append(entry)
        return result

    @staticmethod
    def _activity_inventory_id(entry: dict[str, Any]) -> str:
        value = entry.get("activityId")
        if value is None:
            value = entry.get("id")
        if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
            raise ValueError("activity_inventory_id_invalid")
        return str(value).strip()

    def _activity_inventory_local_date(self, entry: dict[str, Any]) -> str | None:
        for key in ("startTimeGMT", "startTimeUTC", "start_time_utc"):
            if entry.get(key) is not None:
                try:
                    return self._activity_time_utc(entry[key], local=False)[1]
                except GarminError:
                    return None
        for key in ("startTimeLocal", "calendarDate"):
            if entry.get(key) is not None:
                try:
                    return self._activity_time_utc(entry[key], local=True)[1]
                except GarminError:
                    return None
        return None

    @staticmethod
    def _activity_date_in_scope(local_date: str, start: date, through: date, mode: str) -> bool:
        current = date.fromisoformat(local_date)
        return current <= through and (mode == "full" or current >= start)

    @staticmethod
    def _activity_time_utc(value: Any, *, local: bool) -> tuple[str, str]:
        if not isinstance(value, str) or not value.strip():
            raise GarminError("activity_summary_time_invalid")
        text = value.strip().replace(" ", "T")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            if len(text) != 10:
                raise GarminError("activity_summary_time_invalid") from None
            try:
                parsed = datetime.combine(date.fromisoformat(text), datetime.min.time())
            except ValueError:
                raise GarminError("activity_summary_time_invalid") from None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ if local else UTC)
        utc = parsed.astimezone(UTC)
        return utc.isoformat().replace("+00:00", "Z"), utc.astimezone(TZ).date().isoformat()

    def _validate_activity_summary(self, summary: Any, activity_id: str) -> dict[str, Any]:
        if not isinstance(summary, dict):
            raise GarminError("activity_summary_invalid")
        normalized = dict(summary)
        nested = summary.get("summaryDTO")
        if nested is not None:
            if not isinstance(nested, dict):
                raise GarminError("activity_summary_invalid")
            for key, value in nested.items():
                normalized.setdefault(key, value)
        if normalized.get("activityType") is None and isinstance(
            summary.get("activityTypeDTO"), dict
        ):
            normalized["activityType"] = summary["activityTypeDTO"]
        summary_id = normalized.get("activityId")
        if summary_id is None:
            summary_id = normalized.get("id")
        if isinstance(summary_id, bool) or str(summary_id).strip() != activity_id:
            raise GarminError("activity_summary_identity_mismatch")
        start_value = normalized.get("startTimeGMT") or normalized.get("startTimeUTC") or normalized.get("start_time_utc")
        start_utc, local_date = self._activity_time_utc(start_value, local=False)
        activity_type = normalized.get("activityType")
        if isinstance(activity_type, dict):
            sport = activity_type.get("typeKey")
            sub_sport = activity_type.get("subTypeKey")
        else:
            sport = activity_type
            sub_sport = normalized.get("activitySubType")
        if not isinstance(sport, str) or not sport.strip():
            raise GarminError("activity_summary_type_invalid")
        end_value = normalized.get("endTimeGMT") or normalized.get("endTimeUTC") or normalized.get("end_time_utc")
        end_utc = None
        if end_value is not None:
            end_utc, _ = self._activity_time_utc(end_value, local=False)
            if end_utc < start_utc:
                raise GarminError("activity_summary_time_invalid")
        return {
            "start_time_utc": start_utc,
            "end_time_utc": end_utc,
            "local_date": local_date,
            "sport": sport.strip(),
            "sub_sport": sub_sport.strip() if isinstance(sub_sport, str) and sub_sport.strip() else None,
            "normalized_summary": normalized,
        }

    def _collect_activity_summary(
        self,
        conn: sqlite3.Connection,
        run: int,
        subject: int,
        activity_id: str,
        start: date,
        through: date,
        request: SyncRequest,
        receipt: SyncReceipt,
        applicable_ids: set[str],
    ) -> None:
        key = f"garmin:activity:{activity_id}"
        try:
            summary = self._call(
                lambda: self._transport().activity_summary(activity_id),
                conn=conn, run=run, subject=subject, resource="activity_summary", key=key,
            )
            validate_provider_json_payload(summary)
            self.repo.item(conn, run, "activity_summary", key, "fetch", "fetched", increment_attempt=False)
            try:
                validated = self._validate_activity_summary(summary, activity_id)
            except GarminError as validation_error:
                def rejected_summary(_revision: int, error: GarminError = validation_error) -> None:
                    raise error
                try:
                    self.repo.archive(
                        conn, "activity_summary", activity_id, canonical_provider_json(summary),
                        "json", "application/json", rejected_summary,
                    )
                except GarminError:
                    pass
                raise validation_error
            if not self._activity_date_in_scope(validated["local_date"], start, through, request.mode):
                return
            applicable_ids.add(activity_id)
            def summary_projector(revision: int) -> None:
                self._project_activity(
                    conn,
                    subject,
                    activity_id,
                    validated["normalized_summary"],
                    validated,
                    revision,
                )
            _, revision, changed = self.repo.archive(
                conn, "activity_summary", activity_id, canonical_provider_json(summary),
                "json", "application/json", summary_projector,
            )
            if not changed:
                self._set_activity_active(conn, subject, activity_id)
            self.repo.item(
                conn, run, "activity_summary", key, "project",
                "revised" if changed else "unchanged",
                revision_id=revision,
            )
            self.repo.resolve_gaps(
                conn, subject, "activity_summary",
                date.fromisoformat(validated["local_date"]).isoformat(),
                logical_object_key=key,
                stages=("fetch", "project"),
            )
            receipt.counts["revised" if changed else "unchanged"] += 1
        except GarminError as exc:
            if exc.http_status == 401:
                raise GarminError("auth_required", http_status=401) from None
            outcome = self._classify(exc)
            deferred = outcome.status == "deferred"
            retry = self._next_retry(exc, 0) if deferred else None
            terminal = "forbidden" if outcome.status == "forbidden" else ("deferred" if deferred else "failed")
            stage = "project" if exc.code.startswith("activity_summary_") else "fetch"
            self.repo.item(conn, run, "activity_summary", key, stage, terminal, error=exc, next_retry=retry, increment_attempt=False)
            self.repo.gap(conn, subject, "activity_summary", key, start.isoformat(), stage, exc.code, end_day=through.isoformat(), deferred=deferred, next_retry=retry)
            receipt.counts["deferred" if deferred else "failed"] += 1
            receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
        except Exception:
            error = GarminError("activity_summary_project_failed")
            self.repo.item(conn, run, "activity_summary", key, "project", "failed", error=error, increment_attempt=False)
            self.repo.gap(conn, subject, "activity_summary", key, start.isoformat(), "project", error.code, end_day=through.isoformat())
            receipt.counts["failed"] += 1

    def _project_activity(
        self,
        conn: sqlite3.Connection,
        subject: int,
        provider_id: str,
        summary: dict[str, Any],
        validated: dict[str, Any],
        revision: int,
    ) -> int:
        existing = conn.execute(
            """SELECT extras_json,source_map_json FROM activities
               WHERE provider='garmin' AND provider_activity_id=?""",
            (provider_id,),
        ).fetchone()
        extras = json.loads(existing["extras_json"] or "{}") if existing else {}
        source_map = json.loads(existing["source_map_json"] or "{}") if existing else {}
        reviewed_summary_keys = (
            "activityId", "id", "activityName", "activityType", "activitySubType",
            "startTimeGMT", "startTimeUTC", "start_time_utc",
            "endTimeGMT", "endTimeUTC", "end_time_utc",
            "duration", "elapsedDuration", "movingDuration", "timerTime",
            "distance", "calories", "aerobicTrainingEffect",
            "anaerobicTrainingEffect", "trainingEffect",
            "uploadDate", "eventType", "privacy",
        )
        extras["connect_summary"] = {
            key: summary[key] for key in reviewed_summary_keys if key in summary
        }
        extras["connect_summary_revision_id"] = revision
        source_map["summary"] = revision
        for field_key in (
            "provider_activity_id", "name", "sport", "sub_sport",
            "start_time_utc", "local_date", "elapsed_seconds",
            "timer_seconds", "distance_m", "provider_state",
        ):
            source_map[field_key] = {
                "source_revision_id": revision,
                "source_role": "summary_json",
            }
        if validated["end_time_utc"] is not None:
            source_map["end_time_utc"] = {
                "source_revision_id": revision,
                "source_role": "summary_json",
                "method": "provider_explicit",
                "confidence": 1.0,
            }
            extras.pop("end_time_inference", None)
        else:
            source_map.pop("end_time_utc", None)
        conn.execute(
            """INSERT INTO activities(
                   subject_id,provider,provider_activity_id,name,sport,sub_sport,
                   start_time_utc,end_time_utc,local_date,elapsed_seconds,timer_seconds,
                   distance_m,extras_json,source_map_json,primary_revision_id,provider_state,
                   first_missing_at_utc,last_missing_at_utc,provider_deleted_at_utc
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active',NULL,NULL,NULL)
               ON CONFLICT(provider,provider_activity_id) DO UPDATE SET
                   subject_id=excluded.subject_id,name=excluded.name,sport=excluded.sport,
                   sub_sport=excluded.sub_sport,start_time_utc=excluded.start_time_utc,
                   end_time_utc=excluded.end_time_utc,local_date=excluded.local_date,
                   elapsed_seconds=excluded.elapsed_seconds,timer_seconds=excluded.timer_seconds,
                   distance_m=excluded.distance_m,extras_json=excluded.extras_json,
                   source_map_json=excluded.source_map_json,
                   primary_revision_id=excluded.primary_revision_id,provider_state='active',
                   first_missing_at_utc=NULL,last_missing_at_utc=NULL,provider_deleted_at_utc=NULL""",
            (
                subject, "garmin", provider_id, summary.get("activityName"),
                validated["sport"], validated["sub_sport"], validated["start_time_utc"],
                validated["end_time_utc"], validated["local_date"], summary.get("duration"),
                summary.get("movingDuration"), summary.get("distance"),
                json.dumps(extras, sort_keys=True, allow_nan=False),
                json.dumps(source_map, sort_keys=True, allow_nan=False), revision,
            ),
        )
        activity = int(conn.execute(
            "SELECT id FROM activities WHERE provider='garmin' AND provider_activity_id=?",
            (provider_id,),
        ).fetchone()[0])
        conn.execute(
            "UPDATE activity_source_revisions SET is_active=0 WHERE activity_id=? AND source_role='summary_json'",
            (activity,),
        )
        conn.execute(
            """INSERT INTO activity_source_revisions(
                   activity_id,source_revision_id,source_role,is_active
               ) VALUES(?,?,?,1)
               ON CONFLICT(activity_id,source_revision_id,source_role)
               DO UPDATE SET is_active=1""",
            (activity, revision, "summary_json"),
        )
        return activity

    @staticmethod
    def _set_activity_active(conn: sqlite3.Connection, subject: int, provider_id: str) -> None:
        conn.execute(
            """UPDATE activities SET provider_state='active',first_missing_at_utc=NULL,
                      last_missing_at_utc=NULL,provider_deleted_at_utc=NULL
               WHERE subject_id=? AND provider='garmin' AND provider_activity_id=?""",
            (subject, provider_id),
        )

    @staticmethod
    def _has_active_fit(conn: sqlite3.Connection, activity: int) -> bool:
        return conn.execute(
            """SELECT 1 FROM activity_source_revisions ar
               JOIN source_revisions sr ON sr.id=ar.source_revision_id
               WHERE ar.activity_id=? AND ar.source_role='activity_fit'
                 AND ar.is_active=1 AND sr.is_current=1
                 AND sr.parsed_at_utc IS NOT NULL""",
            (activity,),
        ).fetchone() is not None

    @staticmethod
    def _activity_enrichment_applicable(resource: str, sport: str) -> bool:
        normalized = sport.casefold()
        if resource == "activity_exercise_sets":
            return "strength" in normalized
        if resource == "activity_power_zones":
            return any(token in normalized for token in (
                "cycling", "running", "rowing", "ski", "multisport", "triathlon",
            ))
        if resource == "activity_weather":
            return not any(token in normalized for token in (
                "indoor", "strength", "pool", "yoga",
            ))
        return True

    @staticmethod
    def _validate_activity_enrichment_binding(
        conn: sqlite3.Connection,
        subject: int,
        activity: int,
        provider_id: str,
        payload: Any,
    ) -> None:
        row = conn.execute(
            """SELECT subject_id,provider,provider_activity_id
               FROM activities WHERE id=?""",
            (activity,),
        ).fetchone()
        if (
            row is None
            or int(row["subject_id"]) != subject
            or row["provider"] != "garmin"
            or str(row["provider_activity_id"]) != provider_id
        ):
            raise GarminError("activity_enrichment_binding_mismatch")
        if payload is not None and not isinstance(payload, (dict, list)):
            raise GarminError("activity_enrichment_invalid")
        if isinstance(payload, dict):
            for key in ("activityId", "activityID", "activity_id"):
                if key not in payload:
                    continue
                value = payload[key]
                if isinstance(value, bool) or str(value).strip() != provider_id:
                    raise GarminError("activity_enrichment_identity_mismatch")

    @staticmethod
    def _enrichment_state(payload: Any) -> str:
        if payload is None:
            return "null"
        if payload == {}:
            return "empty_object"
        if payload == []:
            return "empty_array"
        return "value"

    @staticmethod
    def _reviewed_enrichment_payload(role: str, payload: Any) -> Any:
        keys = {
            "hr_zones_json": {
                "zoneNumber", "zone", "secsInZone", "seconds", "zoneLowBoundary",
                "zoneHighBoundary", "lowBoundary", "highBoundary",
            },
            "power_zones_json": {
                "zoneNumber", "zone", "secsInZone", "seconds", "zoneLowBoundary",
                "zoneHighBoundary", "lowBoundary", "highBoundary",
            },
            "weather_json": {
                "temp", "temperature", "apparentTemperature", "dewPoint",
                "relativeHumidity", "humidity", "windSpeed", "windDirection",
                "weatherType", "issueDate", "observationTime",
            },
            "gear_json": {
                "gearPk", "uuid", "displayName", "gearTypeName", "modelName",
                "brandName", "customMakeModel",
            },
        }.get(role)
        if keys is None:
            return None

        def reviewed(value: Any) -> Any:
            if isinstance(value, list):
                return [reviewed(item) for item in value if isinstance(item, (dict, list))]
            if isinstance(value, dict):
                return {
                    key: value[key] for key in keys
                    if key in value and not isinstance(value[key], (dict, list))
                }
            return None

        if isinstance(payload, dict):
            for container_key in (
                "zones", "timeInZones", "weather", "gear", "activityGear",
            ):
                if container_key in payload and isinstance(payload[container_key], (dict, list)):
                    return reviewed(payload[container_key])
        return reviewed(payload)

    @staticmethod
    def _payload_rows(payload: Any, keys: tuple[str, ...]) -> tuple[list[Any], bool]:
        """Return source-index-preserving rows plus an invalid-container flag."""
        if isinstance(payload, list):
            return payload, False
        if not isinstance(payload, dict):
            return [], False
        for key in keys:
            if key not in payload:
                continue
            value = payload[key]
            return (value, False) if isinstance(value, list) else ([], True)
        return [], False

    @staticmethod
    def _json_number(value: Any) -> float | int | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return value if math.isfinite(float(value)) else None

    def _json_timestamp(self, value: Any) -> str | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            seconds = float(value) / 1000.0 if abs(float(value)) >= 10_000_000_000 else float(value)
            try:
                return datetime.fromtimestamp(seconds, UTC).isoformat().replace("+00:00", "Z")
            except (OverflowError, OSError, ValueError):
                return None
        if isinstance(value, str) and value.strip():
            try:
                return self._activity_time_utc(value, local=False)[0]
            except GarminError:
                return None
        return None

    @staticmethod
    def _row_value(
        row: dict[str, Any],
        keys: tuple[str, ...],
    ) -> tuple[bool, Any]:
        for key in keys:
            if key in row:
                return True, row[key]
        return False, None

    def _prepare_typed_split_row(
        self,
        item: Any,
        source_index: int,
        sport: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if not isinstance(item, dict):
            return None, "row_not_object"
        invalid = False
        semantic = False
        route_semantic = False

        split_type_present, split_type_value = self._row_value(item, ("splitType", "type"))
        split_type: str | None = None
        if split_type_present and split_type_value is not None:
            if not isinstance(split_type_value, str) or not split_type_value.strip():
                invalid = True
            else:
                split_type = split_type_value.strip()
                semantic = True

        route_name_present, route_name_value = self._row_value(item, ("routeName",))
        route_name: str | None = None
        if route_name_present and route_name_value is not None:
            if not isinstance(route_name_value, str) or not route_name_value.strip():
                invalid = True
            else:
                route_name = route_name_value.strip()
                semantic = True

        start_present, start_value = self._row_value(
            item, ("startTimeGMT", "startTime", "startTimestamp"),
        )
        end_present, end_value = self._row_value(
            item, ("endTimeGMT", "endTime", "endTimestamp"),
        )
        start = self._json_timestamp(start_value) if start_present and start_value is not None else None
        end = self._json_timestamp(end_value) if end_present and end_value is not None else None
        if start_present and start_value is not None:
            if start is None:
                invalid = True
            else:
                semantic = True
        if end_present and end_value is not None:
            if end is None:
                invalid = True
            else:
                semantic = True
        if start is not None and end is not None and end < start:
            invalid = True

        def number(
            keys: tuple[str, ...],
            *,
            integer: bool = False,
            route: bool = False,
        ) -> float | int | None:
            nonlocal invalid, semantic, route_semantic
            present, value = self._row_value(item, keys)
            if not present or value is None:
                return None
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value < 0
                or (integer and not isinstance(value, int))
            ):
                invalid = True
                return None
            semantic = True
            route_semantic = route_semantic or route
            return value

        duration = number(("duration", "durationSeconds"))
        distance = number(("distance", "distanceMeters"))
        falls = number(("falls",), integer=True, route=True)
        ascent = number(("ascentMeters", "elevationGain"), route=True)

        completed_present, completed_value = self._row_value(item, ("completed",))
        completed: int | None = None
        if completed_present and completed_value is not None:
            if isinstance(completed_value, bool):
                completed = int(completed_value)
            elif (
                isinstance(completed_value, int)
                and not isinstance(completed_value, bool)
                and completed_value in {0, 1}
            ):
                completed = completed_value
            else:
                invalid = True
            if completed is not None:
                semantic = True
                route_semantic = True

        grade_present, grade = self._row_value(item, ("gradeRaw", "grade", "gradeValue"))
        if grade_present and grade is not None:
            if (
                isinstance(grade, bool)
                or not isinstance(grade, (str, int, float))
                or (isinstance(grade, str) and not grade.strip())
                or (isinstance(grade, float) and not math.isfinite(grade))
            ):
                invalid = True
            else:
                semantic = True
                route_semantic = True
        grade_system_present, grade_system_value = self._row_value(item, ("gradeSystem",))
        grade_system: str | None = None
        if grade_system_present and grade_system_value is not None:
            if not isinstance(grade_system_value, str) or not grade_system_value.strip():
                invalid = True
            else:
                grade_system = grade_system_value.strip()
                semantic = True
                route_semantic = True
        grade_display_present, grade_display_value = self._row_value(item, ("gradeDisplay",))
        grade_display: str | None = None
        if grade_display_present and grade_display_value is not None:
            if not isinstance(grade_display_value, str) or not grade_display_value.strip():
                invalid = True
            else:
                grade_display = grade_display_value.strip()
                semantic = True
                route_semantic = True

        if invalid:
            return None, "reviewed_field_invalid"
        if not semantic:
            return None, "unknown_only"
        climbing = any(token in sport.casefold() for token in ("climb", "boulder"))
        is_rest = split_type is not None and "rest" in split_type.casefold()
        kind = (
            "climb_rest" if is_rest else "climb_active"
        ) if climbing or route_semantic else "split"
        return {
            "source_index": source_index,
            "segment_type": kind,
            "start": start,
            "end": end,
            "duration": duration,
            "distance": distance,
            "split_type": split_type,
            "route_name": route_name,
            "route_semantic": route_semantic,
            "grade": grade if grade_present else None,
            "grade_system": grade_system,
            "grade_display": grade_display,
            "completed": completed,
            "falls": falls,
            "ascent": ascent,
        }, None

    def _project_typed_splits(
        self,
        conn: sqlite3.Connection,
        activity: int,
        sport: str,
        payload: Any,
        revision: int,
    ) -> dict[str, Any]:
        items, container_invalid = self._payload_rows(
            payload, ("typedSplits", "activityTypedSplits", "activitySplits", "splits"),
        )
        prepared: list[dict[str, Any]] = []
        reasons: dict[str, int] = {}
        if container_invalid:
            reasons["container_not_array"] = 1
        for source_index, item in enumerate(items):
            row, reason = self._prepare_typed_split_row(item, source_index, sport)
            if row is None:
                reasons[reason or "invalid"] = reasons.get(reason or "invalid", 0) + 1
            else:
                prepared.append(row)
        for item in prepared:
            extras = {
                "source_role": "typed_splits_json",
                "source_revision_id": revision,
                "source_index": item["source_index"],
            }
            if item["split_type"] is not None:
                extras["splitType"] = item["split_type"]
            if item["route_name"] is not None:
                extras["routeName"] = item["route_name"]
            conn.execute(
                """INSERT OR IGNORE INTO activity_segments(
                       activity_id,segment_type,segment_index,start_time_utc,
                       end_time_utc,duration_seconds,distance_m,extras_json,
                       source_revision_id
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    activity, item["segment_type"], item["source_index"],
                    item["start"], item["end"], item["duration"], item["distance"],
                    json.dumps(extras, sort_keys=True, allow_nan=False), revision,
                ),
            )
            if item["segment_type"] != "climb_active" or not item["route_semantic"]:
                continue
            segment = conn.execute(
                """SELECT id FROM activity_segments
                   WHERE activity_id=? AND source_revision_id=?
                     AND segment_type=? AND segment_index=?""",
                (activity, revision, item["segment_type"], item["source_index"]),
            ).fetchone()
            conn.execute(
                """INSERT OR IGNORE INTO climbing_routes(
                       segment_id,grade_raw,grade_system,grade_display,
                       completed,falls,ascent_meters
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    int(segment["id"]),
                    str(item["grade"]) if item["grade"] is not None else None,
                    item["grade_system"],
                    item["grade_display"] if item["grade_display"] is not None else (
                        str(item["grade"]) if item["grade"] is not None else None
                    ),
                    item["completed"], item["falls"], item["ascent"],
                ),
            )
        return {
            "received_row_count": len(items),
            "valid_row_count": len(prepared),
            "dropped_row_count": len(items) - len(prepared) + int(container_invalid),
            "drop_reasons": dict(sorted(reasons.items())[:8]),
        }

    def _prepare_exercise_set_row(
        self,
        item: Any,
        source_index: int,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if not isinstance(item, dict):
            return None, "row_not_object"
        invalid = False
        semantic = False
        detail_semantic = False

        def text(keys: tuple[str, ...], *, detail: bool = False) -> str | None:
            nonlocal invalid, semantic, detail_semantic
            present, value = self._row_value(item, keys)
            if not present or value is None:
                return None
            if not isinstance(value, str) or not value.strip():
                invalid = True
                return None
            semantic = True
            detail_semantic = detail_semantic or detail
            return value.strip()

        def number(
            keys: tuple[str, ...],
            *,
            integer: bool = False,
            detail: bool = False,
        ) -> float | int | None:
            nonlocal invalid, semantic, detail_semantic
            present, value = self._row_value(item, keys)
            if not present or value is None:
                return None
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value < 0
                or (integer and not isinstance(value, int))
            ):
                invalid = True
                return None
            semantic = True
            detail_semantic = detail_semantic or detail
            return value

        set_type = text(("setType", "type"), detail=True)
        category = text(("exerciseCategory",), detail=True)
        exercise_name = text(("exerciseName",), detail=True)
        duration = number(("duration", "durationSeconds"), detail=True)
        repetitions = number(("repetitions", "reps"), integer=True, detail=True)
        weight = number(("weightKg", "weight"), detail=True)
        step = number(("workoutStepIndex",), integer=True, detail=True)
        raw_exercise = number(("exerciseNumber",), integer=True, detail=True)
        start_present, start_value = self._row_value(
            item, ("startTimeGMT", "startTime", "startTimestamp"),
        )
        end_present, end_value = self._row_value(
            item, ("endTimeGMT", "endTime", "endTimestamp"),
        )
        start = self._json_timestamp(start_value) if start_present and start_value is not None else None
        end = self._json_timestamp(end_value) if end_present and end_value is not None else None
        if start_present and start_value is not None:
            if start is None:
                invalid = True
            else:
                semantic = True
        if end_present and end_value is not None:
            if end is None:
                invalid = True
            else:
                semantic = True
        if start is not None and end is not None and end < start:
            invalid = True
        if invalid:
            return None, "reviewed_field_invalid"
        if not semantic:
            return None, "unknown_only"
        return {
            "source_index": source_index,
            "segment_type": (
                "strength_rest"
                if set_type is not None and "rest" in set_type.casefold()
                else "strength_active"
            ),
            "set_type": set_type,
            "category": category,
            "exercise_name": exercise_name,
            "duration": duration,
            "repetitions": repetitions,
            "weight": weight,
            "step": step,
            "raw_exercise": raw_exercise,
            "start": start,
            "end": end,
            "detail_semantic": detail_semantic,
        }, None

    def _project_exercise_sets(
        self,
        conn: sqlite3.Connection,
        activity: int,
        payload: Any,
        revision: int,
    ) -> dict[str, Any]:
        items, container_invalid = self._payload_rows(
            payload, ("exerciseSets", "activityExerciseSets", "sets"),
        )
        prepared: list[dict[str, Any]] = []
        reasons: dict[str, int] = {}
        if container_invalid:
            reasons["container_not_array"] = 1
        for source_index, item in enumerate(items):
            row, reason = self._prepare_exercise_set_row(item, source_index)
            if row is None:
                reasons[reason or "invalid"] = reasons.get(reason or "invalid", 0) + 1
            else:
                prepared.append(row)
        for item in prepared:
            conn.execute(
                """INSERT OR IGNORE INTO activity_segments(
                       activity_id,segment_type,segment_index,start_time_utc,
                       end_time_utc,duration_seconds,extras_json,source_revision_id
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    activity, item["segment_type"], item["source_index"],
                    item["start"], item["end"], item["duration"],
                    json.dumps({
                        "source_role": "exercise_sets_json",
                        "source_revision_id": revision,
                        "source_index": item["source_index"],
                    }, sort_keys=True, allow_nan=False),
                    revision,
                ),
            )
            if not item["detail_semantic"]:
                continue
            segment = conn.execute(
                """SELECT id FROM activity_segments
                   WHERE activity_id=? AND source_revision_id=?
                     AND segment_type=? AND segment_index=?""",
                (
                    activity, revision, item["segment_type"],
                    item["source_index"],
                ),
            ).fetchone()
            conn.execute(
                """INSERT OR IGNORE INTO strength_sets(
                       segment_id,workout_step_index,set_type,exercise_category,
                       raw_exercise_number,exercise_name,repetitions,weight_kg,
                       duration_seconds
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    int(segment["id"]), item["step"], item["set_type"],
                    item["category"], item["raw_exercise"],
                    item["exercise_name"], item["repetitions"],
                    item["weight"], item["duration"],
                ),
            )
        return {
            "received_row_count": len(items),
            "valid_row_count": len(prepared),
            "dropped_row_count": len(items) - len(prepared) + int(container_invalid),
            "drop_reasons": dict(sorted(reasons.items())[:8]),
        }

    def _project_activity_enrichment(
        self,
        conn: sqlite3.Connection,
        subject: int,
        provider_id: str,
        activity: int,
        sport: str,
        resource: str,
        role: str,
        payload: Any,
        revision: int,
    ) -> None:
        self._validate_activity_enrichment_binding(
            conn, subject, activity, provider_id, payload,
        )
        row = conn.execute(
            "SELECT extras_json,source_map_json FROM activities WHERE id=?", (activity,),
        ).fetchone()
        extras = json.loads(row["extras_json"] or "{}")
        source_map = json.loads(row["source_map_json"] or "{}")
        reviewed = self._reviewed_enrichment_payload(role, payload)
        enrichments = extras.setdefault("connect_enrichments", {})
        enrichment_entry: dict[str, Any] = {
            "source_revision_id": revision,
            "state": self._enrichment_state(payload),
        }
        if reviewed is not None:
            enrichment_entry["reviewed"] = reviewed
        enrichments[role] = enrichment_entry
        extras["connect_enrichments"] = enrichments
        source_map[role] = {
            "source_revision_id": revision,
            "source_role": role,
            "state": self._enrichment_state(payload),
        }
        projection: dict[str, Any] | None = None
        if role == "typed_splits_json":
            projection = self._project_typed_splits(
                conn, activity, sport, payload, revision,
            )
        elif role == "exercise_sets_json":
            projection = self._project_exercise_sets(
                conn, activity, payload, revision,
            )
        if projection is not None:
            enrichment_entry["projection"] = projection
            issue_code = (
                "activity_typed_splits_drift"
                if role == "typed_splits_json"
                else "activity_exercise_sets_drift"
            )
            if projection["dropped_row_count"] > 0:
                self._set_activity_issue(
                    conn, activity, issue_code, "warning",
                    {
                        "source_revision_id": revision,
                        **projection,
                    },
                    revision,
                )
            else:
                self._resolve_activity_issue(conn, activity, issue_code)
        conn.execute(
            "UPDATE activities SET extras_json=?,source_map_json=? WHERE id=?",
            (
                json.dumps(extras, sort_keys=True, allow_nan=False),
                json.dumps(source_map, sort_keys=True, allow_nan=False),
                activity,
            ),
        )
        conn.execute(
            "UPDATE activity_source_revisions SET is_active=0 WHERE activity_id=? AND source_role=?",
            (activity, role),
        )
        conn.execute(
            """INSERT OR IGNORE INTO activity_source_revisions(
                   activity_id,source_revision_id,source_role,is_active
               ) VALUES(?,?,?,1)""",
            (activity, revision, role),
        )

    def _collect_activity_enrichment(
        self,
        conn: sqlite3.Connection,
        run: int,
        subject: int,
        provider_id: str,
        activity: int,
        sport: str,
        day: date,
        resource: str,
        role: str,
        receipt: SyncReceipt,
    ) -> None:
        key = f"garmin:activity:{provider_id}"
        if not self._activity_enrichment_applicable(resource, sport):
            self.repo.item(
                conn, run, resource, key, "discover", "not_supported",
                error=GarminError("not_supported"), increment_attempt=False,
            )
            self._count_receipt_terminal(receipt, "not_supported")
            return
        method = getattr(self._transport(), "activity_extra", None)
        if not callable(method):
            self.repo.item(
                conn, run, resource, key, "fetch", "not_supported",
                error=GarminError("not_supported"), increment_attempt=False,
            )
            self._count_receipt_terminal(receipt, "not_supported")
            return
        try:
            payload = self._call(
                lambda: method(provider_id, role),
                conn=conn, run=run, subject=subject, resource=resource, key=key,
                allows_404=True,
            )
            validate_provider_json_payload(payload)
            # Field-shape discovery belongs to the received response, even
            # when binding/project validation later leaves its revision
            # non-current.  Autocommit here survives projector rollback.
            self.repo.fields(conn, resource, payload)
            self.repo.item(
                conn, run, resource, key, "fetch", "fetched",
                increment_attempt=False,
            )

            def projector(revision: int) -> None:
                self._project_activity_enrichment(
                    conn, subject, provider_id, activity, sport,
                    resource, role, payload, revision,
                )

            _, revision, changed = self.repo.archive(
                conn, resource, provider_id, canonical_provider_json(payload),
                "json", "application/json", projector,
            )
            self.repo.resolve_gaps(
                conn, subject, resource, day.isoformat(),
                logical_object_key=key, stages=("fetch", "project"),
            )
            self.repo.item(
                conn, run, resource, key, "project",
                "revised" if changed else "unchanged",
                revision_id=revision, increment_attempt=False,
            )
            receipt.counts["revised" if changed else "unchanged"] += 1
        except GarminError as exc:
            outcome = self._classify(exc, allows_404=True)
            if outcome.status == "auth_required":
                raise GarminError("auth_required", http_status=401) from None
            terminal = (
                "not_supported" if exc.code == "not_supported"
                else "not_available" if outcome.status == "not_available"
                else "forbidden" if outcome.status == "forbidden"
                else "deferred" if outcome.status == "deferred"
                else "failed"
            )
            retry = self._next_retry(exc, 0) if terminal == "deferred" else None
            stage = "project" if exc.code.startswith("activity_enrichment_") else "fetch"
            self.repo.item(
                conn, run, resource, key, stage, terminal,
                error=exc, next_retry=retry, increment_attempt=False,
            )
            if terminal not in {"not_available", "not_supported"}:
                self.repo.gap(
                    conn, subject, resource, key, day.isoformat(), stage,
                    exc.code, deferred=terminal == "deferred", next_retry=retry,
                )
            self._count_receipt_terminal(receipt, terminal)
            receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
        except Exception:
            error = GarminError("activity_extra_project_failed")
            self.repo.item(
                conn, run, resource, key, "project", "failed",
                error=error, increment_attempt=False,
            )
            self.repo.gap(
                conn, subject, resource, key, day.isoformat(), "project", error.code,
            )
            receipt.counts["failed"] += 1

    @staticmethod
    def _set_activity_issue(
        conn: sqlite3.Connection,
        activity: int,
        issue_code: str,
        severity: str,
        details: dict[str, Any],
        revision: int | None,
    ) -> None:
        now = utc_now()
        payload = json.dumps(details, sort_keys=True, allow_nan=False)
        row = conn.execute(
            """SELECT id FROM data_quality_issues
               WHERE entity_type='activity' AND entity_id=? AND issue_code=?
                 AND status='open' ORDER BY id DESC LIMIT 1""",
            (activity, issue_code),
        ).fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO data_quality_issues(
                       entity_type,entity_id,issue_code,severity,details_json,
                       status,first_seen_at_utc,last_seen_at_utc,source_revision_id
                   ) VALUES('activity',?,?,?,?,'open',?,?,?)""",
                (activity, issue_code, severity, payload, now, now, revision),
            )
        else:
            conn.execute(
                """UPDATE data_quality_issues
                   SET severity=?,details_json=?,last_seen_at_utc=?,
                       source_revision_id=?
                   WHERE id=?""",
                (severity, payload, now, revision, int(row["id"])),
            )

    @staticmethod
    def _resolve_activity_issue(
        conn: sqlite3.Connection,
        activity: int,
        issue_code: str,
    ) -> None:
        now = utc_now()
        conn.execute(
            """UPDATE data_quality_issues
               SET status='resolved',resolved_at_utc=?,last_seen_at_utc=?
               WHERE entity_type='activity' AND entity_id=? AND issue_code=?
                 AND status='open'""",
            (now, now, activity, issue_code),
        )

    @staticmethod
    def _chart_rows(payload: Any) -> tuple[list[Any], bool]:
        if isinstance(payload, list):
            return payload, False
        if not isinstance(payload, dict):
            return [], False
        for key in ("chartData", "points", "samples"):
            if key in payload:
                value = payload[key]
                return (value, False) if isinstance(value, list) else ([], True)
        descriptors = payload.get("metricDescriptors")
        metrics = payload.get("activityDetailMetrics")
        if descriptors is None and metrics is None:
            return [], False
        if not isinstance(descriptors, list) or not isinstance(metrics, list):
            return [], True
        index_to_key: dict[int, str] = {}
        for descriptor in descriptors:
            if not isinstance(descriptor, dict):
                continue
            index = descriptor.get("metricsIndex")
            key = descriptor.get("key")
            if isinstance(index, int) and not isinstance(index, bool) and isinstance(key, str):
                index_to_key[index] = key
        rows: list[Any] = []
        for entry in metrics:
            if not isinstance(entry, dict) or not isinstance(entry.get("metrics"), list):
                rows.append(entry)
                continue
            row = {
                key: entry["metrics"][index]
                for index, key in index_to_key.items()
                if index < len(entry["metrics"])
            }
            rows.append(row)
        return rows, False

    def _prepare_activity_chart(
        self,
        payload: Any,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        rows, container_invalid = self._chart_rows(payload)
        aliases = {
            "timestamp_utc": (
                "directTimestamp", "timestamp", "time", "startGMT", "startTimeGMT",
            ),
            "latitude": ("directLatitude", "latitude", "lat"),
            "longitude": ("directLongitude", "longitude", "lon", "lng"),
            "distance_m": ("directDistance", "distance", "distanceMeters"),
            "speed_mps": ("directSpeed", "speed", "speedMetersPerSecond"),
            "altitude_m": ("directElevation", "elevation", "altitude"),
            "heart_rate_bpm": ("directHeartRate", "heartRate", "heartRateBpm"),
            "cadence_rpm": ("directDoubleCadence", "directCadence", "cadence"),
            "power_w": ("directPower", "power", "watts"),
            "temperature_c": ("directAirTemperature", "temperature", "temperatureC"),
        }
        nonnegative = {
            "distance_m", "speed_mps", "heart_rate_bpm", "cadence_rpm", "power_w",
        }
        prepared: list[dict[str, Any]] = []
        reasons: dict[str, int] = {}
        if container_invalid:
            reasons["container_not_array"] = 1
        for source_index, row in enumerate(rows):
            if not isinstance(row, dict):
                reasons["row_not_object"] = reasons.get("row_not_object", 0) + 1
                continue
            invalid = False
            semantic = False
            timestamp_present, timestamp_value = self._row_value(
                row, aliases["timestamp_utc"],
            )
            stamp = (
                self._json_timestamp(timestamp_value)
                if timestamp_present and timestamp_value is not None
                else None
            )
            if timestamp_present and timestamp_value is not None:
                if stamp is None:
                    invalid = True
                else:
                    semantic = True
            values: dict[str, float | int | None] = {}
            for field, field_aliases in aliases.items():
                if field == "timestamp_utc":
                    continue
                present, value = self._row_value(row, field_aliases)
                if not present or value is None:
                    values[field] = None
                    continue
                numeric = self._json_number(value)
                if numeric is None:
                    invalid = True
                    values[field] = None
                    continue
                if field in nonnegative and numeric < 0:
                    invalid = True
                elif field == "latitude" and not -90 <= numeric <= 90:
                    invalid = True
                elif field == "longitude" and not -180 <= numeric <= 180:
                    invalid = True
                else:
                    semantic = True
                values[field] = numeric
            if invalid:
                reason = "reviewed_field_invalid"
                reasons[reason] = reasons.get(reason, 0) + 1
                continue
            if not semantic:
                reason = "unknown_only"
                reasons[reason] = reasons.get(reason, 0) + 1
                continue
            prepared.append({
                "source_index": source_index,
                "timestamp_utc": stamp,
                "values": values,
            })
        evidence = {
            "stream_kind": "connect_chart",
            "coverage": "partial",
            "requested_max_points": ACTIVITY_CHART_MAX_POINTS,
            "requested_max_polyline_points": ACTIVITY_CHART_MAX_POLYLINE_POINTS,
            "received_point_count": len(rows),
            "valid_point_count": len(prepared),
            "dropped_point_count": len(rows) - len(prepared) + int(container_invalid),
            "drop_reasons": dict(sorted(reasons.items())[:8]),
        }
        return prepared, evidence

    def _project_activity_chart(
        self,
        conn: sqlite3.Connection,
        subject: int,
        provider_id: str,
        activity: int,
        day: date,
        payload: Any,
        revision: int,
        prepared: list[dict[str, Any]],
        evidence: dict[str, Any],
    ) -> int:
        self._validate_activity_enrichment_binding(
            conn, subject, activity, provider_id, payload,
        )
        if evidence["received_point_count"] == 0:
            raise GarminError("activity_chart_empty")
        if evidence["valid_point_count"] == 0:
            raise GarminError("activity_chart_invalid")
        if len(prepared) <= ACTIVITY_CHART_MAX_POINTS:
            selected = prepared
            sampling_method = "none"
        elif ACTIVITY_CHART_MAX_POINTS == 1:
            selected = [prepared[0]]
            sampling_method = "even_stride"
        else:
            indices = [
                round(index * (len(prepared) - 1) / (ACTIVITY_CHART_MAX_POINTS - 1))
                for index in range(ACTIVITY_CHART_MAX_POINTS)
            ]
            selected = [prepared[index] for index in indices]
            sampling_method = "even_stride"
        for sample_index, prepared_row in enumerate(selected):
            values = prepared_row["values"]
            conn.execute(
                """INSERT OR IGNORE INTO activity_samples(
                       activity_id,source_revision_id,stream_kind,sample_index,
                       timestamp_utc,latitude,longitude,distance_m,speed_mps,
                       altitude_m,heart_rate_bpm,cadence_rpm,power_w,
                       temperature_c,extras_json
                   ) VALUES(?,?, 'connect_chart',?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    activity, revision, sample_index, prepared_row["timestamp_utc"],
                    values["latitude"], values["longitude"], values["distance_m"],
                    values["speed_mps"], values["altitude_m"],
                    values["heart_rate_bpm"], values["cadence_rpm"],
                    values["power_w"], values["temperature_c"],
                    json.dumps({
                        "source_index": prepared_row["source_index"],
                        "source_role": "details_json_fallback",
                    }, sort_keys=True, allow_nan=False),
                ),
            )
        row = conn.execute(
            "SELECT extras_json,source_map_json FROM activities WHERE id=?", (activity,),
        ).fetchone()
        extras = json.loads(row["extras_json"] or "{}")
        source_map = json.loads(row["source_map_json"] or "{}")
        evidence = {
            **evidence,
            "source_revision_id": revision,
            "persisted_point_count": len(selected),
            "sampling_method": sampling_method,
        }
        extras["connect_chart"] = evidence
        source_map["sensor_stream"] = {
            "source_revision_id": revision,
            "source_role": "details_json_fallback",
            "stream_kind": "connect_chart",
            "coverage": "partial",
        }
        conn.execute(
            "UPDATE activities SET extras_json=?,source_map_json=? WHERE id=?",
            (
                json.dumps(extras, sort_keys=True, allow_nan=False),
                json.dumps(source_map, sort_keys=True, allow_nan=False),
                activity,
            ),
        )
        conn.execute(
            """UPDATE activity_source_revisions SET is_active=0
               WHERE activity_id=? AND source_role='details_json_fallback'""",
            (activity,),
        )
        conn.execute(
            """INSERT OR IGNORE INTO activity_source_revisions(
                   activity_id,source_revision_id,source_role,is_active
               ) VALUES(?,?, 'details_json_fallback',1)""",
            (activity, revision),
        )
        self.repo.coverage(
            conn, subject, "activity_details_fallback", day.isoformat(),
            "partial", revision, len(selected),
        )
        self._set_activity_issue(
            conn, activity, "activity_sensor_fallback", "warning", evidence, revision,
        )
        if sampling_method != "none":
            self._set_activity_issue(
                conn, activity, "activity_chart_sampled", "info", evidence, revision,
            )
        else:
            self._resolve_activity_issue(conn, activity, "activity_chart_sampled")
        if evidence["dropped_point_count"] > 0:
            self._set_activity_issue(
                conn, activity, "activity_chart_invalid_rows", "warning",
                evidence, revision,
            )
        else:
            self._resolve_activity_issue(
                conn, activity, "activity_chart_invalid_rows",
            )
        self._resolve_activity_issue(conn, activity, "activity_chart_empty")
        self._resolve_activity_issue(conn, activity, "activity_chart_invalid")
        return len(selected)

    @staticmethod
    def _received_activity_revision(
        conn: sqlite3.Connection,
        resource: str,
        provider_id: str,
        payload_hash: str | None,
    ) -> int | None:
        if payload_hash is None:
            return None
        row = conn.execute(
            """SELECT id FROM source_revisions
               WHERE provider='garmin' AND resource_kind=?
                 AND provider_object_id=? AND payload_hash=?
                 AND parsed_at_utc IS NULL
               ORDER BY revision_no DESC LIMIT 1""",
            (resource, provider_id, payload_hash),
        ).fetchone()
        return int(row["id"]) if row is not None else None

    def _clear_invalid_chart_canonical(
        self,
        conn: sqlite3.Connection,
        subject: int,
        activity: int,
        day: date,
        issue_code: str,
        evidence: dict[str, Any],
        revision: int | None,
    ) -> None:
        conn.execute(
            """UPDATE activity_source_revisions SET is_active=0
               WHERE activity_id=? AND source_role='details_json_fallback'""",
            (activity,),
        )
        row = conn.execute(
            "SELECT extras_json,source_map_json FROM activities WHERE id=?",
            (activity,),
        ).fetchone()
        extras = json.loads(row["extras_json"] or "{}")
        source_map = json.loads(row["source_map_json"] or "{}")
        current_stream = source_map.get("sensor_stream")
        if (
            isinstance(current_stream, dict)
            and current_stream.get("source_role") == "details_json_fallback"
        ):
            source_map.pop("sensor_stream", None)
        prior_chart = extras.get("connect_chart")
        if isinstance(prior_chart, dict):
            prior_chart["canonical"] = False
            prior_chart["invalidated_by_revision_id"] = revision
            extras["connect_chart"] = prior_chart
        invalid_evidence = {
            **evidence,
            "source_revision_id": revision,
            "persisted_point_count": 0,
            "sampling_method": "none",
            "canonical_published": False,
        }
        extras["connect_chart_attempt"] = invalid_evidence
        conn.execute(
            "UPDATE activities SET extras_json=?,source_map_json=? WHERE id=?",
            (
                json.dumps(extras, sort_keys=True, allow_nan=False),
                json.dumps(source_map, sort_keys=True, allow_nan=False),
                activity,
            ),
        )
        self.repo.coverage(
            conn, subject, "activity_details_fallback", day.isoformat(),
            "error", revision, 0,
        )
        self._set_activity_issue(
            conn, activity, issue_code, "warning", invalid_evidence, revision,
        )
        other = (
            "activity_chart_invalid"
            if issue_code == "activity_chart_empty"
            else "activity_chart_empty"
        )
        self._resolve_activity_issue(conn, activity, other)
        self._resolve_activity_issue(
            conn, activity, "activity_chart_invalid_rows",
        )

    def _collect_activity_chart_fallback(
        self,
        conn: sqlite3.Connection,
        run: int,
        subject: int,
        provider_id: str,
        activity: int,
        day: date,
        receipt: SyncReceipt,
    ) -> None:
        resource = "activity_details_fallback"
        role = "details_json_fallback"
        key = f"garmin:activity:{provider_id}"
        chart_evidence: dict[str, Any] | None = None
        payload_hash: str | None = None
        method = getattr(self._transport(), "activity_extra", None)
        if not callable(method):
            self.repo.item(
                conn, run, resource, key, "fetch", "not_supported",
                error=GarminError("not_supported"), increment_attempt=False,
            )
            self._count_receipt_terminal(receipt, "not_supported")
            return
        try:
            payload = self._call(
                lambda: method(provider_id, role),
                conn=conn, run=run, subject=subject, resource=resource, key=key,
                allows_404=True,
            )
            validate_provider_json_payload(payload)
            canonical = canonical_provider_json(payload)
            payload_hash = digest(canonical)
            self.repo.fields(conn, resource, payload)
            prepared, chart_evidence = self._prepare_activity_chart(payload)
            self.repo.item(
                conn, run, resource, key, "fetch", "fetched",
                increment_attempt=False,
            )
            count_box: dict[str, int] = {}

            def projector(revision: int) -> None:
                count_box["count"] = self._project_activity_chart(
                    conn, subject, provider_id, activity, day, payload, revision,
                    prepared, chart_evidence or {},
                )

            _, revision, changed = self.repo.archive(
                conn, resource, provider_id, canonical,
                "json", "application/json", projector,
            )
            self.repo.resolve_gaps(
                conn, subject, resource, day.isoformat(),
                logical_object_key=key, stages=("fetch", "project"),
            )
            self.repo.item(
                conn, run, resource, key, "project",
                "revised" if changed else "unchanged",
                revision_id=revision, increment_attempt=False,
            )
            receipt.coverage_state = "partial"
            receipt.counts["revised" if changed else "unchanged"] += 1
        except GarminError as exc:
            if exc.code in {"activity_chart_empty", "activity_chart_invalid"}:
                received_revision = self._received_activity_revision(
                    conn, resource, provider_id, payload_hash,
                )
                self._clear_invalid_chart_canonical(
                    conn, subject, activity, day, exc.code,
                    chart_evidence or {
                        "stream_kind": "connect_chart",
                        "coverage": "partial",
                        "received_point_count": 0,
                        "valid_point_count": 0,
                        "dropped_point_count": 0,
                        "persisted_point_count": 0,
                        "sampling_method": "none",
                    },
                    received_revision,
                )
                receipt.coverage_state = "partial"
            outcome = self._classify(exc, allows_404=True)
            if outcome.status == "auth_required":
                raise GarminError("auth_required", http_status=401) from None
            terminal = (
                "not_supported" if exc.code == "not_supported"
                else "not_available" if outcome.status == "not_available"
                else "forbidden" if outcome.status == "forbidden"
                else "deferred" if outcome.status == "deferred"
                else "failed"
            )
            retry = self._next_retry(exc, 0) if terminal == "deferred" else None
            stage = "project" if exc.code.startswith(("activity_chart_", "activity_enrichment_")) else "fetch"
            self.repo.item(
                conn, run, resource, key, stage, terminal,
                error=exc, next_retry=retry, increment_attempt=False,
            )
            if terminal not in {"not_available", "not_supported"}:
                self.repo.gap(
                    conn, subject, resource, key, day.isoformat(), stage, exc.code,
                    deferred=terminal == "deferred", next_retry=retry,
                )
            self._count_receipt_terminal(receipt, terminal)
            receipt.next_retry_at_utc = retry or receipt.next_retry_at_utc
        except Exception:
            error = GarminError("activity_extra_project_failed")
            self.repo.item(
                conn, run, resource, key, "project", "failed",
                error=error, increment_attempt=False,
            )
            self.repo.gap(
                conn, subject, resource, key, day.isoformat(), "project", error.code,
            )
            receipt.counts["failed"] += 1

    def _promote_fit_canonical(
        self,
        conn: sqlite3.Connection,
        activity: int,
        revision: int,
    ) -> None:
        row = conn.execute(
            "SELECT extras_json,source_map_json FROM activities WHERE id=?", (activity,),
        ).fetchone()
        extras = json.loads(row["extras_json"] or "{}")
        source_map = json.loads(row["source_map_json"] or "{}")
        source_map["sensor_stream"] = {
            "source_revision_id": revision,
            "source_role": "activity_fit",
            "stream_kind": "fit_record",
            "coverage": "canonical",
        }
        source_map["segments"] = {
            "source_revision_id": revision,
            "source_role": "activity_fit",
        }
        if "connect_chart" in extras:
            extras["connect_chart"]["canonical"] = False
            extras["connect_chart"]["superseded_by_fit_revision_id"] = revision
        conn.execute(
            "UPDATE activities SET extras_json=?,source_map_json=? WHERE id=?",
            (
                json.dumps(extras, sort_keys=True, allow_nan=False),
                json.dumps(source_map, sort_keys=True, allow_nan=False),
                activity,
            ),
        )
        conn.execute(
            """UPDATE activity_source_revisions SET is_active=0
               WHERE activity_id=? AND source_role='details_json_fallback'""",
            (activity,),
        )
        self._resolve_activity_issue(conn, activity, "activity_sensor_fallback")
        self._resolve_activity_issue(conn, activity, "activity_chart_sampled")

    @staticmethod
    def _tri_value(values: dict[str, Any], key: str) -> dict[str, Any]:
        if key not in values:
            return {"state": "missing"}
        if values[key] is None:
            return {"state": "null", "value": None}
        return {"state": "value", "value": values[key]}

    @staticmethod
    def _fit_session_values(extras: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        sessions = extras.get("fit_sessions")
        if not isinstance(sessions, list) or not sessions:
            return {}, None
        session = sessions[0]
        if not isinstance(session, dict) or not isinstance(session.get("fields"), dict):
            return {}, None
        values = {
            key: evidence.get("value")
            for key, evidence in session["fields"].items()
            if isinstance(evidence, dict) and "value" in evidence
        }
        revision = session.get("source_revision_id")
        return values, revision if isinstance(revision, int) else None

    @staticmethod
    def _reconciliation_result(
        left: dict[str, Any],
        right: dict[str, Any],
        tolerance: float,
    ) -> tuple[str, float | None, float | None]:
        if left["state"] != "value" or right["state"] != "value":
            return ("match", None, None) if left == right else ("not_comparable", None, None)
        left_value, right_value = left["value"], right["value"]
        if isinstance(left_value, bool) or isinstance(right_value, bool):
            return ("match", None, None) if left_value == right_value else ("mismatch", None, None)
        if not isinstance(left_value, (int, float)) or not isinstance(right_value, (int, float)):
            return ("match", None, None) if left_value == right_value else ("mismatch", None, None)
        difference = abs(float(left_value) - float(right_value))
        denominator = max(abs(float(left_value)), abs(float(right_value)))
        relative = difference / denominator if denominator else (0.0 if difference == 0 else None)
        if difference == 0:
            return "match", difference, relative
        return (
            "within_tolerance" if difference <= tolerance else "mismatch",
            difference, relative,
        )

    def _store_reconciliation(
        self,
        conn: sqlite3.Connection,
        activity: int,
        field_key: str,
        left_revision: int,
        right_revision: int,
        left: dict[str, Any],
        right: dict[str, Any],
        tolerance: float,
    ) -> str:
        result, absolute, relative = self._reconciliation_result(left, right, tolerance)
        left_json = json.dumps(left, sort_keys=True, allow_nan=False)
        right_json = json.dumps(right, sort_keys=True, allow_nan=False)
        exists = conn.execute(
            """SELECT 1 FROM reconciliation_results
               WHERE entity_type='activity' AND entity_id=? AND field_key=?
                 AND left_source_revision_id=? AND right_source_revision_id=?
                 AND left_value_json=? AND right_value_json=? AND result=?""",
            (
                activity, field_key, left_revision, right_revision,
                left_json, right_json, result,
            ),
        ).fetchone()
        if exists is None:
            conn.execute(
                """INSERT INTO reconciliation_results(
                       entity_type,entity_id,field_key,left_source_revision_id,
                       right_source_revision_id,left_value_json,right_value_json,
                       absolute_difference,relative_difference,tolerance,result,
                       checked_at_utc
                   ) VALUES('activity',?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    activity, field_key, left_revision, right_revision,
                    left_json, right_json, absolute, relative, tolerance,
                    result, utc_now(),
                ),
            )
        return result

    def _end_time_candidates(
        self,
        conn: sqlite3.Connection,
        activity: int,
        start_utc: str,
        summary: dict[str, Any],
        summary_revision: int,
        fit_values: dict[str, Any],
        fit_revision: int | None,
    ) -> list[dict[str, Any]]:
        start = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
        candidates: list[dict[str, Any]] = []

        def duration_candidate(
            method: str,
            value: Any,
            revision: int | None,
            *,
            lower_bound: bool = False,
        ) -> None:
            seconds = self._json_number(value)
            if seconds is None or seconds < 0:
                return
            candidates.append({
                "method": method,
                "timestamp_utc": (start + timedelta(seconds=float(seconds))).isoformat().replace("+00:00", "Z"),
                "source_revision_id": revision,
                "lower_bound": lower_bound,
            })

        duration_candidate(
            "summary_elapsed", summary.get("duration"), summary_revision,
        )
        duration_candidate(
            "summary_timer",
            summary.get("timerTime") if "timerTime" in summary else summary.get("movingDuration"),
            summary_revision, lower_bound=True,
        )
        duration_candidate(
            "fit_elapsed", fit_values.get("total_elapsed_time"), fit_revision,
        )
        duration_candidate(
            "fit_timer", fit_values.get("total_timer_time"), fit_revision,
            lower_bound=True,
        )
        active_fit_clause = (
            """AND source_revision_id=?"""
            if fit_revision is not None else
            """AND stream_kind='connect_chart'
               AND source_revision_id IN (
                   SELECT source_revision_id FROM activity_source_revisions
                   WHERE activity_id=? AND source_role='details_json_fallback'
                     AND is_active=1
               )"""
        )
        sample_parameters: tuple[Any, ...] = (
            (activity, fit_revision) if fit_revision is not None else (activity, activity)
        )
        sample = conn.execute(
            f"""SELECT timestamp_utc,source_revision_id FROM activity_samples
                WHERE activity_id=? AND timestamp_utc IS NOT NULL
                  {active_fit_clause}
                ORDER BY timestamp_utc DESC LIMIT 1""",
            sample_parameters,
        ).fetchone()
        if sample is not None:
            candidates.append({
                "method": "last_sample",
                "timestamp_utc": sample["timestamp_utc"],
                "source_revision_id": int(sample["source_revision_id"]),
                "lower_bound": False,
            })
        if fit_revision is not None:
            segment = conn.execute(
                """SELECT end_time_utc,start_time_utc,duration_seconds,source_revision_id
                   FROM activity_segments
                   WHERE activity_id=? AND source_revision_id=?
                   ORDER BY coalesce(end_time_utc,start_time_utc) DESC LIMIT 1""",
                (activity, fit_revision),
            ).fetchone()
            if segment is not None:
                end = segment["end_time_utc"]
                if end is None and segment["start_time_utc"] is not None and segment["duration_seconds"] is not None:
                    segment_start = datetime.fromisoformat(str(segment["start_time_utc"]).replace("Z", "+00:00"))
                    end = (segment_start + timedelta(seconds=float(segment["duration_seconds"]))).isoformat().replace("+00:00", "Z")
                if end is not None:
                    candidates.append({
                        "method": "last_segment",
                        "timestamp_utc": end,
                        "source_revision_id": int(segment["source_revision_id"]),
                        "lower_bound": False,
                    })
        return candidates

    def _infer_activity_end_time(
        self,
        conn: sqlite3.Connection,
        activity: int,
        summary: dict[str, Any],
        summary_revision: int,
        fit_values: dict[str, Any],
        fit_revision: int | None,
    ) -> None:
        row = conn.execute(
            """SELECT start_time_utc,end_time_utc,extras_json,source_map_json
               FROM activities WHERE id=?""",
            (activity,),
        ).fetchone()
        candidates = self._end_time_candidates(
            conn, activity, str(row["start_time_utc"]), summary,
            summary_revision, fit_values, fit_revision,
        )
        primary = [candidate for candidate in candidates if not candidate["lower_bound"]]
        times = [
            datetime.fromisoformat(candidate["timestamp_utc"].replace("Z", "+00:00"))
            for candidate in primary
        ]
        conflict = len(times) > 1 and (max(times) - min(times)).total_seconds() > 60
        extras = json.loads(row["extras_json"] or "{}")
        source_map = json.loads(row["source_map_json"] or "{}")
        if row["end_time_utc"] is not None and source_map.get("end_time_utc", {}).get("method") == "provider_explicit":
            explicit = datetime.fromisoformat(str(row["end_time_utc"]).replace("Z", "+00:00"))
            conflict = conflict or any(abs((candidate - explicit).total_seconds()) > 60 for candidate in times)
            if conflict:
                self._set_activity_issue(
                    conn, activity, "activity_end_time_conflict", "warning",
                    {
                        "explicit_end_time_utc": row["end_time_utc"],
                        "candidates": candidates,
                        "decision": "provider_explicit_retained",
                    },
                    fit_revision or summary_revision,
                )
            else:
                self._resolve_activity_issue(conn, activity, "activity_end_time_conflict")
            return
        if conflict:
            extras["end_time_inference"] = {
                "method": "conflict",
                "confidence": 0.0,
                "candidates": candidates,
                "decision": "fail_closed",
            }
            source_map.pop("end_time_utc", None)
            conn.execute(
                "UPDATE activities SET end_time_utc=NULL,extras_json=?,source_map_json=? WHERE id=?",
                (
                    json.dumps(extras, sort_keys=True, allow_nan=False),
                    json.dumps(source_map, sort_keys=True, allow_nan=False),
                    activity,
                ),
            )
            self._set_activity_issue(
                conn, activity, "activity_end_time_conflict", "warning",
                extras["end_time_inference"], fit_revision or summary_revision,
            )
            return
        usable = primary or candidates
        if not usable:
            return
        chosen = max(
            usable,
            key=lambda candidate: datetime.fromisoformat(
                candidate["timestamp_utc"].replace("Z", "+00:00")
            ),
        )
        confidence = 0.9 if len(primary) >= 2 else (0.7 if primary else 0.4)
        evidence = {
            "method": "cross_source" if len(usable) > 1 else chosen["method"],
            "confidence": confidence,
            "end_time_utc": chosen["timestamp_utc"],
            "evidence": candidates,
        }
        extras["end_time_inference"] = evidence
        source_map["end_time_utc"] = {
            "source_revision_id": chosen["source_revision_id"],
            "source_role": (
                "activity_fit" if chosen["source_revision_id"] == fit_revision
                else "summary_json"
            ),
            "method": evidence["method"],
            "confidence": confidence,
            "evidence_revision_ids": sorted({
                candidate["source_revision_id"] for candidate in candidates
                if isinstance(candidate["source_revision_id"], int)
            }),
        }
        conn.execute(
            "UPDATE activities SET end_time_utc=?,extras_json=?,source_map_json=? WHERE id=?",
            (
                chosen["timestamp_utc"],
                json.dumps(extras, sort_keys=True, allow_nan=False),
                json.dumps(source_map, sort_keys=True, allow_nan=False),
                activity,
            ),
        )
        self._resolve_activity_issue(conn, activity, "activity_end_time_conflict")

    def _reconcile_activity(
        self,
        conn: sqlite3.Connection,
        run: int,
        subject: int,
        provider_id: str,
        activity: int,
        day: date,
        receipt: SyncReceipt,
    ) -> None:
        key = f"garmin:activity:{provider_id}"
        try:
            row = conn.execute(
                """SELECT a.extras_json,a.source_map_json,
                          summary.source_revision_id AS summary_revision
                   FROM activities a
                   JOIN activity_source_revisions summary
                     ON summary.activity_id=a.id
                    AND summary.source_role='summary_json'
                    AND summary.is_active=1
                   WHERE a.id=? AND a.subject_id=? AND a.provider='garmin'
                     AND a.provider_activity_id=?""",
                (activity, subject, provider_id),
            ).fetchone()
            if row is None:
                raise GarminError("activity_enrichment_binding_mismatch")
            extras = json.loads(row["extras_json"] or "{}")
            source_map = json.loads(row["source_map_json"] or "{}")
            summary = extras.get("connect_summary")
            if not isinstance(summary, dict):
                summary = {}
            summary_revision = int(row["summary_revision"])
            fit_values, fit_revision = self._fit_session_values(extras)
            mismatches: list[dict[str, Any]] = []
            connect_metrics: dict[str, Any] = {}
            fit_metrics: dict[str, Any] = {}
            if fit_revision is not None:
                for field_key, (summary_key, fit_key, tolerance) in ACTIVITY_RECONCILIATION_FIELDS.items():
                    left = self._tri_value(summary, summary_key)
                    right = self._tri_value(fit_values, fit_key)
                    connect_metrics[field_key] = left
                    fit_metrics[field_key] = right
                    result = self._store_reconciliation(
                        conn, activity, field_key, summary_revision, fit_revision,
                        left, right, tolerance,
                    )
                    if result == "mismatch":
                        mismatches.append({
                            "field_key": field_key,
                            "left": left,
                            "right": right,
                            "tolerance": tolerance,
                        })
                extras["postprocessed_metrics"] = {
                    "connect": {
                        "source_revision_id": summary_revision,
                        "values": connect_metrics,
                    },
                    "fit": {
                        "source_revision_id": fit_revision,
                        "values": fit_metrics,
                    },
                }
                source_map["postprocessed_metrics"] = {
                    field_key: {
                        "canonical_source_revision_id": summary_revision,
                        "canonical_source_role": "summary_json",
                        "alternate_source_revision_id": fit_revision,
                        "alternate_source_role": "activity_fit",
                    }
                    for field_key in ACTIVITY_RECONCILIATION_FIELDS
                }
                fit_routes = conn.execute(
                    """SELECT 1 FROM activity_segments s JOIN climbing_routes r
                         ON r.segment_id=s.id
                       WHERE s.activity_id=? AND s.source_revision_id=? LIMIT 1""",
                    (activity, fit_revision),
                ).fetchone()
                fit_sets = conn.execute(
                    """SELECT 1 FROM activity_segments s JOIN strength_sets x
                         ON x.segment_id=s.id
                       WHERE s.activity_id=? AND s.source_revision_id=? LIMIT 1""",
                    (activity, fit_revision),
                ).fetchone()
                if fit_routes:
                    source_map["climbing_routes"] = {
                        "source_revision_id": fit_revision,
                        "source_role": "activity_fit",
                    }
                if fit_sets:
                    source_map["strength_sets"] = {
                        "source_revision_id": fit_revision,
                        "source_role": "activity_fit",
                    }
            for role, canonical_key, detail_table in (
                ("typed_splits_json", "climbing_routes", "climbing_routes"),
                ("exercise_sets_json", "strength_sets", "strength_sets"),
            ):
                current_source = source_map.get(canonical_key)
                if (
                    isinstance(current_source, dict)
                    and current_source.get("source_role") == "activity_fit"
                ):
                    continue
                relation = conn.execute(
                    f"""SELECT ar.source_revision_id
                        FROM activity_source_revisions ar
                        WHERE ar.activity_id=? AND ar.source_role=? AND ar.is_active=1
                          AND EXISTS(
                              SELECT 1 FROM activity_segments s
                              JOIN {detail_table} detail ON detail.segment_id=s.id
                              WHERE s.activity_id=ar.activity_id
                                AND s.source_revision_id=ar.source_revision_id
                          )""",
                    (activity, role),
                ).fetchone()
                if relation is not None:
                    source_map[canonical_key] = {
                        "source_revision_id": int(relation["source_revision_id"]),
                        "source_role": role,
                    }
                elif (
                    isinstance(current_source, dict)
                    and current_source.get("source_role") == role
                ):
                    source_map.pop(canonical_key, None)
            conn.execute(
                "UPDATE activities SET extras_json=?,source_map_json=? WHERE id=?",
                (
                    json.dumps(extras, sort_keys=True, allow_nan=False),
                    json.dumps(source_map, sort_keys=True, allow_nan=False),
                    activity,
                ),
            )
            if mismatches:
                self._set_activity_issue(
                    conn, activity, "activity_reconciliation_mismatch", "warning",
                    {
                        "summary_revision_id": summary_revision,
                        "fit_revision_id": fit_revision,
                        "mismatches": mismatches,
                    },
                    fit_revision,
                )
            else:
                self._resolve_activity_issue(
                    conn, activity, "activity_reconciliation_mismatch",
                )
            self._infer_activity_end_time(
                conn, activity, summary, summary_revision, fit_values, fit_revision,
            )
            self.repo.resolve_gaps(
                conn, subject, "activities", day.isoformat(),
                logical_object_key=key, stages=("reconcile",),
            )
            self.repo.item(
                conn, run, "activities", key, "reconcile", "succeeded",
                increment_attempt=False,
            )
        except GarminError as exc:
            self.repo.item(
                conn, run, "activities", key, "reconcile", "failed",
                error=exc, increment_attempt=False,
            )
            self.repo.gap(
                conn, subject, "activities", key, day.isoformat(),
                "reconcile", exc.code,
            )
            receipt.counts["failed"] += 1
        except Exception:
            error = GarminError("activity_reconcile_failed")
            self.repo.item(
                conn, run, "activities", key, "reconcile", "failed",
                error=error, increment_attempt=False,
            )
            self.repo.gap(
                conn, subject, "activities", key, day.isoformat(),
                "reconcile", error.code,
            )
            receipt.counts["failed"] += 1

    def _apply_activity_inventory_state(
        self,
        conn: sqlite3.Connection,
        subject: int,
        seen_ids: set[str],
        start: date,
        through: date,
        mode: str,
        *,
        complete: bool,
    ) -> None:
        query = """SELECT id,provider_activity_id,provider_state
                   FROM activities
                   WHERE subject_id=? AND provider='garmin' AND local_date<=?"""
        parameters: list[Any] = [subject, through.isoformat()]
        if mode != "full":
            query += " AND local_date>=?"
            parameters.append(start.isoformat())
        rows = list(conn.execute(query, parameters))
        now = self._now_utc().isoformat().replace("+00:00", "Z")
        conn.execute("BEGIN IMMEDIATE")
        try:
            for row in rows:
                provider_id = str(row["provider_activity_id"])
                if provider_id in seen_ids:
                    self._set_activity_active(conn, subject, provider_id)
                elif complete and row["provider_state"] == "active":
                    conn.execute(
                        """UPDATE activities SET provider_state='suspected_missing',
                                  first_missing_at_utc=?,last_missing_at_utc=? WHERE id=?""",
                        (now, now, row["id"]),
                    )
                elif complete and row["provider_state"] == "suspected_missing":
                    conn.execute(
                        """UPDATE activities SET provider_state='provider_deleted',
                                  last_missing_at_utc=?,provider_deleted_at_utc=? WHERE id=?""",
                        (now, now, row["id"]),
                    )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def _publish_activity_inventory_coverage(
        self,
        conn: sqlite3.Connection,
        subject: int,
        seen_ids: set[str],
        start: date,
        through: date,
        request: SyncRequest,
    ) -> None:
        if request.mode == "full":
            return
        counts: dict[str, int] = {}
        if seen_ids:
            placeholders = ",".join("?" for _ in seen_ids)
            counts = {
                row["local_date"]: int(row["record_count"])
                for row in conn.execute(
                    f"""SELECT local_date,count(*) AS record_count FROM activities
                        WHERE subject_id=? AND provider='garmin'
                          AND provider_activity_id IN ({placeholders})
                          AND local_date>=? AND local_date<=?
                        GROUP BY local_date""",
                    (subject, *sorted(seen_ids), start.isoformat(), through.isoformat()),
                )
            }
        for offset in range((through - start).days + 1):
            day = (start + timedelta(days=offset)).isoformat()
            state = "partial" if request.mode == "snapshot" else ("fetched" if counts.get(day, 0) else "empty")
            self.repo.coverage(
                conn, subject, "activity_inventory", day, state, None,
                counts.get(day, 0), snapshot=request.mode == "snapshot",
            )

    _FIT_MAX_BYTES = 200 * 1024 * 1024
    _FIT_MAX_MEMBERS = 16
    _FIT_MAX_TOTAL_BYTES = 300 * 1024 * 1024

    def _fit_temp_dir(self) -> Path:
        parent = self.config.raw_root.parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if parent.is_symlink():
            raise GarminError("fit_zip_unsafe_member")
        return Path(tempfile.mkdtemp(prefix=".fit-download-", dir=parent))

    @staticmethod
    def _write_temp_file(path: Path, content: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        try:
            view = memoryview(content)
            while view:
                written = os.write(fd, view); view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _fit_timestamp(value: Any) -> str | None:
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @classmethod
    def _fit_json_value(cls, value: Any) -> Any:
        """Serialize FIT values without losing array or timestamp structure."""
        if isinstance(value, datetime):
            return cls._fit_timestamp(value)
        if isinstance(value, (date, datetime_time)):
            return value.isoformat()
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (tuple, list)):
            return [cls._fit_json_value(item) for item in value]
        raise TypeError(f"unsupported_fit_value:{type(value).__name__}")

    @classmethod
    def _fit_field_evidence(cls, field: Any) -> dict[str, Any]:
        is_developer = getattr(field, "field_type", None) == "devfield"
        definition = getattr(field, "field_def", None)
        return {
            "value": cls._fit_json_value(field.value),
            "unit": field.units,
            "field_definition_number": field.def_num,
            "developer_data_index": getattr(definition, "dev_data_index", None) if is_developer else None,
            "is_developer": is_developer,
        }

    @staticmethod
    def _fit_optional(primary: Any, fallback: Any) -> Any:
        return primary if primary is not None else fallback

    @staticmethod
    def _fit_unknown_timestamp(fields: Iterable[Any], fallback: str | None) -> str | None:
        for field in fields:
            if field.def_num == 253 and isinstance(field.value, int):
                return (datetime(1989, 12, 31, tzinfo=UTC) + timedelta(seconds=field.value)).isoformat().replace("+00:00", "Z")
        return fallback

    def _extract_fit_candidates(self, blob: bytes) -> list[bytes]:
        """Read ORIGINAL as an untrusted transient container; leave no ZIP behind."""
        if len(blob) > self._FIT_MAX_BYTES:
            raise GarminError("fit_zip_limits_exceeded")
        directory = self._fit_temp_dir()
        try:
            zip_path = directory / "original.zip"
            if not blob.startswith(b"PK"):
                return [blob] if len(blob) >= 12 else []
            self._write_temp_file(zip_path, blob)
            try:
                with zipfile.ZipFile(zip_path) as archive:
                    infos = archive.infolist()
                    if len(infos) > self._FIT_MAX_MEMBERS or sum(item.file_size for item in infos) > self._FIT_MAX_TOTAL_BYTES:
                        raise GarminError("fit_zip_limits_exceeded")
                    if archive.testzip() is not None:
                        raise GarminError("fit_zip_invalid")
                    candidates: list[bytes] = []
                    for info in infos:
                        name = PurePosixPath(info.filename)
                        mode = info.external_attr >> 16
                        file_type = stat.S_IFMT(mode)
                        if file_type == stat.S_IFLNK or name.is_absolute() or ".." in name.parts or "\\" in info.filename:
                            raise GarminError("fit_zip_unsafe_member")
                        if info.is_dir():
                            continue
                        # ZIPs produced on non-Unix platforms commonly have no
                        # file type bits.  Otherwise accept regular files only.
                        if file_type not in {0, stat.S_IFREG}:
                            raise GarminError("fit_zip_unsafe_member")
                        if info.file_size > self._FIT_MAX_BYTES:
                            raise GarminError("fit_zip_limits_exceeded")
                        if name.suffix.casefold() == ".fit":
                            try:
                                candidates.append(archive.read(info))
                            except (RuntimeError, zipfile.BadZipFile) as exc:
                                raise GarminError("fit_zip_invalid") from exc
                    return candidates
            except GarminError:
                raise
            except (RuntimeError, zipfile.BadZipFile) as exc:
                raise GarminError("fit_zip_invalid") from exc
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def _validate_fit_sessions(
        self,
        sessions: list[dict[str, Any]],
        activities: list[dict[str, Any]],
        start_utc: str,
        sport: str,
    ) -> tuple[str, str]:
        if not sessions:
            raise GarminError("fit_no_session")
        identities: list[tuple[str, str, str, int]] = []
        for index, session in enumerate(sessions):
            stamp = self._fit_timestamp(session.get("start_time") or session.get("timestamp"))
            fit_sport = str(session.get("sport") or "").strip()
            fit_sub_sport = str(session.get("sub_sport") or "").strip()
            if not stamp or not fit_sport:
                raise GarminError("fit_ambiguous_session" if len(sessions) > 1 else "fit_identity_mismatch")
            identities.append((stamp, fit_sport, fit_sub_sport, index))
        try:
            expected_start = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
            ordered = sorted(
                identities,
                key=lambda item: (
                    datetime.fromisoformat(item[0].replace("Z", "+00:00")),
                    item[3],
                ),
            )
            earliest_start = datetime.fromisoformat(ordered[0][0].replace("Z", "+00:00"))
        except ValueError as exc:
            raise GarminError("fit_identity_mismatch") from exc
        if abs((earliest_start - expected_start).total_seconds()) > 300:
            raise GarminError("fit_identity_mismatch")

        declared_counts = {
            int(activity["num_sessions"])
            for activity in activities
            if isinstance(activity.get("num_sessions"), int)
        }
        if declared_counts and declared_counts != {len(sessions)}:
            raise GarminError("fit_ambiguous_session")
        activity_types = {str(activity.get("type") or "").strip() for activity in activities}
        # Garmin Connect type keys and FIT sport vocabularies are not always
        # identical.  Keep this table explicit and closed: a time match alone
        # is never enough to accept an unrecognised Connect activity type.
        expected = {
            "badminton": ("racket", "badminton"),
            "breathwork": ("training", "breathing"),
            "indoor_cardio": ("training", "cardio_training"),
            "indoor_cycling": ("cycling", "indoor_cycling"),
            "indoor_running": ("running", "indoor_running"),
            "treadmill_running": ("running", "treadmill"),
            "strength_training": ("training", "strength_training"),
            "training": ("training", None),
            "bouldering": ("rock_climbing", "bouldering"),
            "indoor_climbing": ("rock_climbing", "indoor_climbing"),
            "rock_climbing": ("rock_climbing", None),
            "running": ("running", None),
            "cycling": ("cycling", None),
            "hiking": ("hiking", None),
        }.get(sport)
        multisport = (
            sport in {"multisport", "multi_sport", "triathlon"}
            or "auto_multi_sport" in activity_types
        )
        if not multisport:
            if expected is None:
                raise GarminError(
                    "fit_ambiguous_session" if len(sessions) > 1 else "fit_identity_mismatch"
                )
            conflicts = [
                identity for identity in identities
                if identity[1] != expected[0]
                or (expected[1] is not None and identity[2] != expected[1])
            ]
            if conflicts:
                raise GarminError("fit_ambiguous_session" if len(sessions) > 1 else "fit_identity_mismatch")
        return ordered[0][0], ordered[0][1]

    def _fit_session_identity(self, fit: bytes, start_utc: str, sport: str) -> tuple[str, str]:
        directory = self._fit_temp_dir()
        path = directory / "candidate.fit"
        try:
            self._write_temp_file(path, fit)
            sessions: list[dict[str, Any]] = []
            activities: list[dict[str, Any]] = []
            try:
                with fitdecode.FitReader(path, check_crc=True) as reader:
                    for frame in reader:
                        if isinstance(frame, fitdecode.FitDataMessage):
                            values = {field.name: field.value for field in frame.fields}
                            if frame.name == "session":
                                sessions.append(values)
                            elif frame.name == "activity":
                                activities.append(values)
            except Exception as exc:
                raise GarminError("fit_crc_invalid") from exc
            return self._validate_fit_sessions(sessions, activities, start_utc, sport)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def _collect_activity_fit(self, conn: sqlite3.Connection, run: int, subject: int, provider_id: str, activity: int, start_utc: str, sport: str, day: date, receipt: SyncReceipt) -> str:
        key = f"garmin:activity:{provider_id}"
        try:
            blob = self._call(lambda: self._transport().activity_original(provider_id), conn=conn, run=run, subject=subject, resource="activity_fit", key=key, allows_404=True)
            self.repo.item(
                conn, run, "activity_fit", key, "fetch", "fetched",
                increment_attempt=False,
            )
            candidates = self._extract_fit_candidates(blob)
            valid: list[bytes] = []
            invalid_codes: list[str] = []
            # Hash/deduplicate before parsing.  Stable hash order makes both
            # validation and the selected failure independent of ZIP order.
            unique_candidates = {
                candidate_hash: candidate
                for candidate_hash, candidate in sorted(
                    ((digest(candidate), candidate) for candidate in candidates),
                    key=lambda item: item[0],
                )
            }
            # Every extracted FIT is immutable received evidence, irrespective
            # of whether later validation selects it for canonical projection.
            # Archive before parsing so corrupt, mismatched, or multi-session
            # candidates cannot disappear with an extract failure.  The HMAC
            # keeps the provider activity id and candidate digest out of
            # externally visible identifiers; archive is content-addressed so
            # a repeated ORIGINAL response is a no-op.
            for candidate_hash, candidate in unique_candidates.items():
                candidate_key = self._identity_hmac(
                    f"fit-candidate:{provider_id}:{candidate_hash}"
                )
                self.repo.archive(
                    conn, "activity_fit_candidate", candidate_key, candidate,
                    "fit", "application/octet-stream",
                )
            for candidate in unique_candidates.values():
                try:
                    self._fit_session_identity(candidate, start_utc, sport)
                    valid.append(candidate)
                except GarminError as exc:
                    invalid_codes.append(exc.code)
            if not valid:
                failure_priority = {
                    "fit_crc_invalid": 0,
                    "fit_no_session": 1,
                    "fit_identity_mismatch": 2,
                    "fit_ambiguous_session": 3,
                }
                code = min(invalid_codes, key=lambda item: (failure_priority.get(item, 99), item)) if invalid_codes else "fit_missing"
                raise GarminError(code)
            unique = {digest(candidate): candidate for candidate in valid}
            if len(unique) != 1:
                candidate_revisions: list[int] = []
                for candidate_hash in unique:
                    candidate_key = self._identity_hmac(
                        f"fit-candidate:{provider_id}:{candidate_hash}"
                    )
                    candidate_revision = conn.execute(
                        """SELECT id FROM source_revisions
                             WHERE provider='garmin'
                               AND resource_kind='activity_fit_candidate'
                               AND provider_object_id=? AND is_current=1""",
                        (candidate_key,),
                    ).fetchone()
                    if candidate_revision is None:
                        raise ValueError("fit_candidate_archive_missing")
                    candidate_revisions.append(int(candidate_revision["id"]))
                now = utc_now()
                validation_errors: dict[str, str | None] = {}
                for candidate_hash, candidate in unique_candidates.items():
                    if candidate_hash in unique:
                        validation_errors[candidate_hash] = None
                        continue
                    try:
                        self._fit_session_identity(candidate, start_utc, sport)
                    except GarminError as exc:
                        validation_errors[candidate_hash] = exc.code
                details = json.dumps({
                    "candidate_count": len(unique_candidates),
                    "valid_candidate_count": len(unique),
                    "candidates": [
                        {"hash": candidate_hash, "error_code": validation_errors.get(candidate_hash)}
                        for candidate_hash in sorted(unique_candidates)
                    ],
                }, sort_keys=True, allow_nan=False)
                issue = conn.execute("SELECT id FROM data_quality_issues WHERE entity_type='activity' AND entity_id=? AND issue_code='ambiguous_activity_fit' AND status='open'", (activity,)).fetchone()
                if issue:
                    conn.execute("UPDATE data_quality_issues SET last_seen_at_utc=?,details_json=? WHERE id=?", (now, details, int(issue[0])))
                else:
                    conn.execute("INSERT INTO data_quality_issues(entity_type,entity_id,issue_code,severity,details_json,status,first_seen_at_utc,last_seen_at_utc,source_revision_id) VALUES(?,?,?,?,?,'open',?,?,?)", ("activity", activity, "ambiguous_activity_fit", "warning", details, now, now, candidate_revisions[0]))
                raise GarminError("fit_ambiguous")
            fit = next(iter(unique.values()))
            def projector(revision: int) -> None:
                # Revision-bound projections are immutable historical evidence.
                # Only canonical FIT rows without a revision FK are replaced.
                row = conn.execute("SELECT extras_json,source_map_json FROM activities WHERE id=?", (activity,)).fetchone()
                extras = json.loads(row["extras_json"] or "{}")
                extras.pop("fit_session", None)
                extras["fit_sessions"] = []
                source_map = json.loads(row["source_map_json"] or "{}")
                source_map.pop("fit_session", None)
                source_map.pop("fit_sessions", None)
                conn.execute("UPDATE activities SET extras_json=?,source_map_json=? WHERE id=?", (json.dumps(extras, sort_keys=True, allow_nan=False), json.dumps(source_map, sort_keys=True, allow_nan=False), activity))
                # These projections have no revision FK.  Replace only FIT-owned
                # rows inside the publish transaction; other source kinds remain.
                conn.execute("DELETE FROM activity_metric_sources WHERE activity_id=? AND source_kind IN ('standard_fit','developer_fit')", (activity,))
                conn.execute("DELETE FROM course_points WHERE activity_id=? AND course_identity='fit'", (activity,))
                self._project_fit(conn, activity, fit, revision)
                conn.execute("UPDATE activity_source_revisions SET is_active=0 WHERE activity_id=? AND source_role='activity_fit'", (activity,))
                conn.execute("INSERT OR IGNORE INTO activity_source_revisions(activity_id,source_revision_id,source_role,is_active) VALUES(?,?,?,1)", (activity, revision, "activity_fit"))
                self._promote_fit_canonical(conn, activity, revision)
            _, revision, changed = self.repo.archive(conn, "activity_fit", provider_id, fit, "fit", "application/octet-stream", projector)
            conn.execute("UPDATE data_quality_issues SET status='resolved',resolved_at_utc=?,last_seen_at_utc=? WHERE entity_type='activity' AND entity_id=? AND issue_code='ambiguous_activity_fit' AND status='open'", (utc_now(), utc_now(), activity))
            self.repo.resolve_gaps(
                conn, subject, "activity_fit", day.isoformat(),
                logical_object_key=key,
                stages=("extract", "parse"),
            )
            self.repo.item(conn, run, "activity_fit", key, "parse", "revised" if changed else "unchanged", revision_id=revision, increment_attempt=False)
            receipt.counts["revised" if changed else "unchanged"] += 1
            return "fit"
        except GarminError as exc:
            outcome = self._classify(exc, allows_404=True)
            terminal = "not_available" if outcome.status == "not_available" else ("forbidden" if outcome.status == "forbidden" else ("deferred" if outcome.status == "deferred" else "failed"))
            retry = self._next_retry(exc, 0) if terminal == "deferred" else None
            fetch = conn.execute(
                """SELECT status FROM garmin_sync_items
                   WHERE garmin_sync_run_id=? AND resource_kind='activity_fit'
                     AND logical_object_key=? AND stage='fetch'""",
                (run, key),
            ).fetchone()
            failure_stage = (
                "fetch"
                if fetch is not None and fetch["status"] == "running"
                else "extract"
            )
            self.repo.item(
                conn, run, "activity_fit", key, failure_stage, terminal,
                error=exc, next_retry=retry, increment_attempt=False,
            )
            self.repo.gap(
                conn, subject, "activity_fit", key, day.isoformat(),
                failure_stage, exc.code, deferred=terminal == "deferred",
                next_retry=retry,
            )
            if terminal == "not_available":
                receipt.counts["not_available"] += 1
            else:
                receipt.counts["deferred" if terminal == "deferred" else "failed"] += 1
            if self._has_active_fit(conn, activity):
                return "fit"
            if exc.code == "not_supported":
                return "not_supported"
            if terminal == "not_available":
                return "not_available"
            if exc.code in {
                "fit_missing", "fit_crc_invalid", "fit_no_session",
                "fit_identity_mismatch", "fit_ambiguous_session",
            }:
                return "invalid"
            return terminal
        except Exception:
            # ``archive`` has already committed received raw evidence before
            # entering the projector; do not let a parser/DDL failure erase it
            # or replace a prior current FIT revision.
            error = GarminError("fit_parse_failed")
            self.repo.item(conn, run, "activity_fit", key, "parse", "failed", error=error, increment_attempt=False)
            self.repo.gap(conn, subject, "activity_fit", key, day.isoformat(), "parse", error.code)
            receipt.counts["failed"] += 1
            return "fit" if self._has_active_fit(conn, activity) else "failed"

    def _store_fit_session_evidence(
        self,
        conn: sqlite3.Connection,
        activity: int,
        revision: int,
        fields: Iterable[Any],
    ) -> None:
        session_fields = {field.name: self._fit_field_evidence(field) for field in fields}
        row = conn.execute("SELECT extras_json,source_map_json FROM activities WHERE id=?", (activity,)).fetchone()
        extras = json.loads(row["extras_json"] or "{}")
        source_map = json.loads(row["source_map_json"] or "{}")
        sessions = extras.setdefault("fit_sessions", [])
        session_entry = {
            "session_index": len(sessions),
            "source_revision_id": revision,
            "fields": session_fields,
        }
        sessions.append(session_entry)
        extras["fit_sessions"] = sessions
        extras["fit_session"] = sessions[0]
        source_map["fit_session"] = {"source_revision_id": revision, "source_kind": "fit_session"}
        source_map["fit_sessions"] = {
            "source_revision_id": revision,
            "source_kind": "fit_session",
            "ordered": True,
            "session_count": len(sessions),
        }
        conn.execute(
            "UPDATE activities SET extras_json=?,source_map_json=? WHERE id=?",
            (json.dumps(extras, sort_keys=True, allow_nan=False), json.dumps(source_map, sort_keys=True, allow_nan=False), activity),
        )

    def _project_fit(self, conn: sqlite3.Connection, activity: int, fit: bytes, revision: int) -> None:
        directory = self._fit_temp_dir(); path = directory / "project.fit"
        try:
            self._write_temp_file(path, fit); indexes: dict[str, int] = {}; sport = ""
            metric_ranges: dict[tuple[str, str, int | None, str], list[str | None]] = {}
            workout_steps: dict[int, dict[str, Any]] = {}
            exercise_titles: dict[tuple[str, int | None], str] = {}
            # Workout steps and exercise titles are metadata for set messages,
            # not a positional stream.  Cache the complete definitions before
            # assigning any set its semantic fields.
            with fitdecode.FitReader(path, check_crc=True) as reader:
                for frame in reader:
                    if not isinstance(frame, fitdecode.FitDataMessage):
                        continue
                    values = {field.name: field.value for field in frame.fields}
                    if frame.name == "workout_step" and isinstance(values.get("message_index"), int):
                        workout_steps[values["message_index"]] = values
                    elif frame.name == "exercise_title":
                        category = values.get("exercise_category")
                        title = values.get("wkt_step_name")
                        if category is not None and isinstance(title, str) and title:
                            exercise_titles[(str(category), values.get("exercise_name"))] = title
            with fitdecode.FitReader(path, check_crc=True) as reader:
                for frame in reader:
                    if not isinstance(frame, fitdecode.FitDataMessage): continue
                    values = {field.name: field.value for field in frame.fields}; name = frame.name
                    stamp = self._fit_timestamp(values.get("timestamp"))
                    if name == "session":
                        sport = str(values.get("sport") or sport)
                        self._store_fit_session_evidence(conn, activity, revision, frame.fields)
                    if name == "record":
                        index = indexes.get("record", 0); indexes["record"] = index + 1
                        generic_fields = {"timestamp","position_lat","position_long","distance","speed","enhanced_speed","altitude","enhanced_altitude","heart_rate","cadence","power","temperature"}
                        extras: dict[str, Any] = {}
                        metadata: dict[str, Any] = {}
                        for field in frame.fields:
                            evidence = self._fit_field_evidence(field)
                            if field.name in generic_fields:
                                metadata[field.name] = evidence
                            else:
                                extras[field.name] = evidence
                            if field.name != "timestamp" and not field.name.startswith("unknown_") and field.value is not None:
                                is_developer = evidence["is_developer"]
                                source_kind = "developer_fit" if is_developer else "standard_fit"
                                developer_index = evidence["developer_data_index"] if is_developer else None
                                attribution = "explicit_developer" if is_developer else "unknown"
                                key = (field.name, source_kind, developer_index, attribution)
                                existing = metric_ranges.get(key)
                                if existing is None:
                                    metric_ranges[key] = [stamp, stamp]
                                else:
                                    existing[1] = stamp
                        extras["_field_metadata"] = metadata
                        lat = values.get("position_lat"); lon = values.get("position_long")
                        if isinstance(lat, (int, float)): lat = lat * 180.0 / (2 ** 31)
                        if isinstance(lon, (int, float)): lon = lon * 180.0 / (2 ** 31)
                        conn.execute("INSERT OR IGNORE INTO activity_samples(activity_id,source_revision_id,stream_kind,sample_index,timestamp_utc,latitude,longitude,distance_m,speed_mps,altitude_m,heart_rate_bpm,cadence_rpm,power_w,temperature_c,extras_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (activity, revision, "fit_record", index, stamp, lat, lon, values.get("distance"), self._fit_optional(values.get("enhanced_speed"), values.get("speed")), self._fit_optional(values.get("enhanced_altitude"), values.get("altitude")), values.get("heart_rate"), values.get("cadence"), values.get("power"), values.get("temperature"), json.dumps(extras, sort_keys=True, allow_nan=False)))
                    elif name in {"lap", "split", "set", "workout_step", "length", "interval"}:
                        if name == "set":
                            kind = "strength_rest" if str(values.get("set_type") or "").endswith("rest") else "strength_active"
                        elif name == "split" and sport == "rock_climbing":
                            kind = "climb_rest" if str(values.get("split_type") or "").endswith("rest") else "climb_active"
                        else:
                            kind = name
                        index = indexes.get(kind, 0); indexes[kind] = index + 1
                        cursor = conn.execute("INSERT OR IGNORE INTO activity_segments(activity_id,segment_type,segment_index,start_time_utc,end_time_utc,duration_seconds,distance_m,extras_json,source_revision_id) VALUES(?,?,?,?,?,?,?,?,?)", (activity, kind, index, self._fit_timestamp(values.get("start_time")), stamp, self._fit_optional(values.get("total_timer_time"), values.get("duration")), values.get("total_distance"), json.dumps({field.name: self._fit_json_value(field.value) for field in frame.fields}, sort_keys=True, allow_nan=False), revision))
                        row = conn.execute("SELECT id FROM activity_segments WHERE activity_id=? AND source_revision_id=? AND segment_type=? AND segment_index=?", (activity, revision, kind, index)).fetchone(); segment = int(row[0])
                        if kind == "strength_active":
                            step_index = values.get("wkt_step_index")
                            step = workout_steps.get(step_index, {}) if isinstance(step_index, int) else {}
                            raw_exercise_number = step.get("exercise_name")
                            step_category = step.get("exercise_category")
                            title = exercise_titles.get((str(step_category), raw_exercise_number)) if step_category is not None else None
                            intensity = step.get("intensity")
                            exercise_category = intensity if intensity in {"warmup", "cooldown"} else (step_category or (str(title) if title else None))
                            exercise_name = step.get("notes") or title or step.get("wkt_step_name") or exercise_category
                            conn.execute("INSERT OR IGNORE INTO strength_sets(segment_id,workout_step_index,set_type,exercise_category,raw_exercise_number,exercise_name,repetitions,weight_kg,duration_seconds) VALUES(?,?,?,?,?,?,?,?,?)", (segment, step_index, str(values.get("set_type") or "active"), exercise_category, raw_exercise_number, exercise_name, values.get("repetitions"), values.get("weight"), values.get("duration")))
                        elif kind == "climb_active":
                            grade = values.get("unknown_70")
                            if grade is None:
                                grade = values.get("grade")
                            explicit_completed = values.get("unknown_73")
                            if explicit_completed is not None:
                                completed = int(bool(explicit_completed))
                            else:
                                # In the bouldering sample, this outcome code
                                # is the only completion evidence: 3=completed,
                                # 2=not completed.  The untouched raw code
                                # remains in activity_segments.extras_json.
                                completed = {3: 1, 2: 0}.get(values.get("unknown_71"))
                            conn.execute("INSERT OR IGNORE INTO climbing_routes(segment_id,grade_raw,grade_system,grade_display,completed,falls,ascent_meters) VALUES(?,?,?,?,?,?,?)", (segment, str(grade) if grade is not None else None, "font" if grade is not None else None, _FONT_GRADE_DISPLAY.get(grade), completed, values.get("unknown_72") if values.get("unknown_72") is not None else values.get("falls"), values.get("total_ascent")))
                    elif name == "field_description": conn.execute("INSERT OR IGNORE INTO fit_metric_definitions(source_revision_id,developer_data_index,native_mesg_num,field_definition_number,field_name,base_type,raw_unit,canonical_metric_key) VALUES(?,?,?,?,?,?,?,?)", (revision, int(values.get("developer_data_index") or 0), values.get("native_mesg_num"), int(values.get("field_definition_number") or 0), values.get("field_name"), values.get("fit_base_type_id"), values.get("units"), None))
                    elif name == "developer_data_id":
                        developer_index = values.get("developer_data_index")
                        application_id = values.get("application_id")
                        if isinstance(developer_index, int) and application_id is not None:
                            uid = self._identity_hmac(f"garmin-developer:{developer_index}:{self._fit_json_value(application_id)}")
                            now = utc_now()
                            conn.execute("INSERT INTO devices(device_uid_hash,manufacturer,product,device_type,first_seen_at_utc,last_seen_at_utc) VALUES(?,?,?,?,?,?) ON CONFLICT(device_uid_hash) DO UPDATE SET last_seen_at_utc=excluded.last_seen_at_utc", (uid, "garmin_developer", f"developer_data_index:{developer_index}", "developer_app", now, now))
                            device = conn.execute("SELECT id FROM devices WHERE device_uid_hash=?", (uid,)).fetchone()
                            conn.execute("INSERT OR IGNORE INTO activity_devices(activity_id,device_id,device_role,source_revision_id) VALUES(?,?,?,?)", (activity, int(device[0]), "developer_app", revision))
                    elif name == "device_info":
                        serial = values.get("serial_number")
                        if serial is not None:
                            uid = self._identity_hmac(f"garmin:{serial}"); now = utc_now(); conn.execute("INSERT INTO devices(device_uid_hash,manufacturer,product,device_type,first_seen_at_utc,last_seen_at_utc) VALUES(?,?,?,?,?,?) ON CONFLICT(device_uid_hash) DO UPDATE SET last_seen_at_utc=excluded.last_seen_at_utc", (uid, str(values.get("manufacturer") or "garmin"), str(values.get("product") or ""), "fit_device", now, now)); device = conn.execute("SELECT id FROM devices WHERE device_uid_hash=?", (uid,)).fetchone(); conn.execute("INSERT OR IGNORE INTO activity_devices(activity_id,device_id,device_role,source_revision_id) VALUES(?,?,?,?)", (activity, int(device[0]), "unknown", revision))
                    elif name == "course_point":
                        index = indexes.get("course_point", 0); indexes["course_point"] = index + 1
                        lat = values.get("position_lat"); lon = values.get("position_long")
                        lat = lat * 180.0 / (2 ** 31) if isinstance(lat, (int, float)) else lat
                        lon = lon * 180.0 / (2 ** 31) if isinstance(lon, (int, float)) else lon
                        conn.execute("INSERT OR IGNORE INTO course_points(activity_id,course_identity,point_index,name,point_type,distance_m,latitude,longitude,route_time_utc) VALUES(?,?,?,?,?,?,?,?,?)", (activity, "fit", index, values.get("name"), values.get("type"), values.get("distance"), lat, lon, stamp))
                        conn.execute("INSERT OR IGNORE INTO activity_aux_messages(activity_id,source_revision_id,global_message_number,message_name,message_index,timestamp_utc,payload_json) VALUES(?,?,?,?,?,?,?)", (activity, revision, int(getattr(frame, "global_mesg_num", -1)), "course_point_evidence", index, stamp, json.dumps({field.name: self._fit_field_evidence(field) for field in frame.fields}, sort_keys=True, allow_nan=False)))
                    elif name.startswith("unknown_"):
                        number = int(name.split("_", 1)[1]); unknown_stamp = self._fit_unknown_timestamp(frame.fields, stamp)
                        signature = json.dumps(sorted(({"name": field.name, "field_definition_number": field.def_num, "unit": field.units, "developer_data_index": getattr(getattr(field, "field_def", None), "dev_data_index", None) if getattr(field, "field_type", None) == "devfield" else None, "is_developer": getattr(field, "field_type", None) == "devfield"} for field in frame.fields), key=lambda item: (item["name"], item["field_definition_number"])), sort_keys=True, allow_nan=False)
                        conn.execute("INSERT INTO fit_unknown_message_catalog(source_revision_id,global_message_number,message_count,field_signature_json,first_timestamp_utc,last_timestamp_utc) VALUES(?,?,1,?,?,?) ON CONFLICT(source_revision_id,global_message_number) DO UPDATE SET message_count=message_count+1,first_timestamp_utc=CASE WHEN excluded.first_timestamp_utc IS NOT NULL AND (fit_unknown_message_catalog.first_timestamp_utc IS NULL OR excluded.first_timestamp_utc<fit_unknown_message_catalog.first_timestamp_utc) THEN excluded.first_timestamp_utc ELSE fit_unknown_message_catalog.first_timestamp_utc END,last_timestamp_utc=CASE WHEN excluded.last_timestamp_utc IS NOT NULL AND (fit_unknown_message_catalog.last_timestamp_utc IS NULL OR excluded.last_timestamp_utc>fit_unknown_message_catalog.last_timestamp_utc) THEN excluded.last_timestamp_utc ELSE fit_unknown_message_catalog.last_timestamp_utc END", (revision, number, signature, unknown_stamp, unknown_stamp))
                    elif name not in {"session", "activity", "file_id", "file_creator", "sport", "event", "developer_data_id", "device_settings", "zones_target"}:
                        index = indexes.get(name, 0); indexes[name] = index + 1; conn.execute("INSERT OR IGNORE INTO activity_aux_messages(activity_id,source_revision_id,global_message_number,message_name,message_index,timestamp_utc,payload_json) VALUES(?,?,?,?,?,?,?)", (activity, revision, int(getattr(frame, "global_mesg_num", -1)), name, index, stamp, json.dumps({field.name: self._fit_field_evidence(field) for field in frame.fields}, sort_keys=True, allow_nan=False)))
            for (metric_key, source_kind, developer_index, attribution), (valid_from, valid_to) in metric_ranges.items():
                exists = conn.execute("SELECT 1 FROM activity_metric_sources WHERE activity_id=? AND metric_key=? AND valid_from_utc IS ? AND valid_to_utc IS ? AND source_kind=? AND device_id IS NULL AND developer_data_index IS ? AND attribution_method=?", (activity, metric_key, valid_from, valid_to, source_kind, developer_index, attribution)).fetchone()
                if exists is None:
                    conn.execute("INSERT INTO activity_metric_sources(activity_id,metric_key,valid_from_utc,valid_to_utc,source_kind,device_id,developer_data_index,attribution_method,confidence) VALUES(?,?,?,?,?,?,?,?,?)", (activity, metric_key, valid_from, valid_to, source_kind, None, developer_index, attribution, 1.0 if attribution == "explicit_developer" else None))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def _repair_strategy(
        self, conn: sqlite3.Connection, subject: int, request: SyncRequest,
        receipt: SyncReceipt,
    ) -> Literal["refetch", "reparse", "reconcile", "deferred"]:
        """Choose auto repair from durable evidence, never from a guess.

        A caller can explicitly choose a strategy.  ``auto`` only examines
        unresolved gaps in the requested scope; capability cooldown is kept as
        a deferred receipt rather than turning into an avoidable provider call.
        """
        if request.mode != "repair":
            return "refetch"
        if request.repair_strategy in {"refetch", "reparse", "reconcile"}:
            return request.repair_strategy
        resources = set(request.resource_kinds)
        if "activities" in resources:
            resources.remove("activities")
            resources.update(ACTIVITY_RESOURCE_KINDS)
        activity_ids = set(request.activity_ids)
        clauses = ["subject_id=?", "status IN ('open','deferred')"]
        values: list[Any] = [subject]
        if resources:
            clauses.append("resource_kind IN (%s)" % ",".join("?" for _ in resources))
            values.extend(sorted(resources))
        if request.health_from_local_date:
            clauses.append("window_end_local_date>=?")
            values.append(request.health_from_local_date)
        if request.through_local_date:
            clauses.append("window_start_local_date<=?")
            values.append(request.through_local_date)
        rows = list(conn.execute(
            "SELECT resource_kind,logical_object_key,reason_code,status,next_retry_at_utc "
            "FROM garmin_sync_gaps WHERE " + " AND ".join(clauses), values
        ))
        if activity_ids:
            rows = [row for row in rows if any(
                self._activity_id_matches(str(row["logical_object_key"]), activity_id)
                for activity_id in activity_ids
            )]
        if rows and all(
            row["status"] == "deferred" and row["next_retry_at_utc"]
            and row["next_retry_at_utc"] > utc_now()
            for row in rows
        ):
            receipt.counts["deferred"] += len(rows)
            receipt.next_retry_at_utc = min(str(row["next_retry_at_utc"]) for row in rows)
            receipt.errors.append({"code": "capability_cooldown", "resource": "garmin", "logical_object_key": "garmin:repair", "summary": "repair deferred until next retry"})
            return "deferred"
        reasons = {str(row["reason_code"]) for row in rows}
        # FIT extraction/identity failures have no locally repairable
        # canonical source.  They require a fresh ORIGINAL response, not an
        # offline reconcile of whatever source happens to be current.
        fit_refetch_reasons = {
            "fit_identity_mismatch", "fit_crc_invalid", "fit_no_session",
            "fit_ambiguous_session", "fit_missing", "fit_ambiguous",
            "fit_zip_invalid", "fit_zip_limits_exceeded", "fit_zip_unsafe_member",
        }
        if any(
            str(row["resource_kind"]) == "activity_fit"
            and str(row["reason_code"]) in fit_refetch_reasons
            for row in rows
        ):
            return "refetch"
        # Missing, corrupt, and transport evidence requires a new provider
        # response.  It has priority when a mixed scope is requested.
        if not rows or any(
            token in reason for reason in reasons
            for token in ("network", "timeout", "rate", "raw_integrity", "missing_raw", "fetch")
        ):
            return "refetch"
        if any("reconcile" in reason or "canonical" in reason for reason in reasons):
            return "reconcile"
        if any(token in reason for reason in reasons for token in ("parse", "project", "field")):
            return "reparse"
        return "refetch"

    def _audit(
        self, conn: sqlite3.Connection, subject: int, receipt: SyncReceipt,
        start: date, through: date,
    ) -> None:
        """Build local, repeatable evidence; never overwrite provider facts."""
        now = utc_now()
        # Audit-owned gaps are refreshed for this bounded window.  They remain
        # durable history, but a later clean scan closes stale evidence before
        # recreating any issue that is still present.
        conn.execute(
            """UPDATE garmin_sync_gaps
                  SET status='resolved',resolved_at_utc=?,last_attempt_at_utc=?
                WHERE subject_id=? AND status IN ('open','deferred')
                  AND reason_code IN ('coverage_error','cursor_crosses_gap',
                                      'activity_summary_missing')
                  AND (window_end_local_date='' OR window_end_local_date>=?)
                  AND (window_start_local_date='' OR window_start_local_date<=?)""",
            (now, now, subject, start.isoformat(), through.isoformat()),
        )
        conn.execute(
            """UPDATE garmin_sync_gaps
                  SET status='resolved',resolved_at_utc=?,last_attempt_at_utc=?
                WHERE subject_id=? AND status IN ('open','deferred')
                  AND reason_code='unmapped_field_signature'""",
            (now, now, subject),
        )
        for row in conn.execute(
            "SELECT resource_kind,local_date FROM resource_coverage "
            """WHERE subject_id=? AND provider='garmin'
                 AND availability_state='error'
                 AND local_date BETWEEN ? AND ?""",
            (subject, start.isoformat(), through.isoformat()),
        ):
            self.repo.gap(conn, subject, row["resource_kind"], f"coverage:{row['resource_kind']}:{row['local_date']}", row["local_date"] or "", "validate", "coverage_error")
        # A completed cursor must never leap an unresolved date-level gap.
        for cursor in conn.execute(
            "SELECT resource_kind,complete_through_local_date FROM garmin_sync_cursors WHERE subject_id=?",
            (subject,),
        ):
            ceiling = cursor["complete_through_local_date"]
            if not ceiling:
                continue
            gap = conn.execute(
                """SELECT logical_object_key,window_start_local_date,window_end_local_date,stage
                   FROM garmin_sync_gaps WHERE subject_id=? AND resource_kind=?
                     AND status IN ('open','deferred')
                     AND stage!='cursor_audit'
                     AND (window_end_local_date='' OR window_end_local_date>=?)
                     AND (window_start_local_date='' OR window_start_local_date<=?)
                     AND (window_start_local_date='' OR window_start_local_date<=?)
                   ORDER BY id LIMIT 1""",
                (
                    subject, cursor["resource_kind"], start.isoformat(),
                    through.isoformat(), ceiling,
                ),
            ).fetchone()
            if gap is not None:
                self.repo.gap(conn, subject, cursor["resource_kind"], str(gap["logical_object_key"]), str(gap["window_start_local_date"]), "cursor_audit", "cursor_crosses_gap", end_day=str(gap["window_end_local_date"]))
                receipt.counts["failed"] += 1
        # Validate every current revision's raw lineage.  ``raw_objects`` is
        # authoritative for byte hash; source payload hash can be semantic JSON.
        global_resources = tuple(sorted({*ACCOUNT_RESOURCE_KINDS, "activity_inventory"}))
        placeholders = ",".join("?" for _ in global_resources)
        raw_rows = conn.execute(
            f"""SELECT DISTINCT r.id,r.resource_kind,r.provider_object_id,r.payload_hash,
                       r.profile_version,
                       o.relative_path,o.sha256,o.size_bytes,o.media_type
                  FROM source_revisions r
                  JOIN raw_objects o ON o.id=r.raw_object_id
                 WHERE r.provider='garmin' AND r.is_current=1
                   AND (
                       r.resource_kind IN ({placeholders})
                       OR EXISTS (
                           SELECT 1 FROM resource_coverage coverage
                            WHERE coverage.subject_id=?
                              AND coverage.source_revision_id=r.id
                              AND coverage.local_date BETWEEN ? AND ?
                       )
                       OR EXISTS (
                           SELECT 1 FROM activity_source_revisions relation
                           JOIN activities activity ON activity.id=relation.activity_id
                            WHERE relation.source_revision_id=r.id
                              AND activity.subject_id=?
                              AND activity.local_date BETWEEN ? AND ?
                       )
                   )""",
            (
                *global_resources,
                subject, start.isoformat(), through.isoformat(),
                subject, start.isoformat(), through.isoformat(),
            ),
        )
        for row in raw_rows:
            try:
                raw = self._repair_raw_bytes(row)
                if digest(raw) != row["sha256"]:
                    raise ValueError("raw_object_corrupt")
                if str(row["media_type"]) == "application/json":
                    payload, canonical = parse_provider_json_bytes(raw)
                    if row["profile_version"] == ACCOUNT_PROFILE_SEMANTIC_VERSION:
                        canonical = canonical_provider_json(
                            self._safe_account_payload(
                                str(row["resource_kind"]),
                                payload,
                            )
                        )
                    elif row["profile_version"] == DEVICE_REFERENCE_SEMANTIC_VERSION:
                        reference = self._device_reference_semantic_payload(
                            payload,
                            str(row["resource_kind"]),
                        )
                        if reference is None:
                            raise ValueError("raw_object_corrupt")
                        canonical = canonical_provider_json(reference)
                    elif row["profile_version"] is not None:
                        raise ValueError("raw_object_corrupt")
                    if digest(canonical) != row["payload_hash"]:
                        raise ValueError("raw_object_corrupt")
            except (OSError, ValueError, json.JSONDecodeError):
                self.repo.gap(conn, subject, row["resource_kind"], row["provider_object_id"], "", "validate", "raw_integrity", revision=int(row["id"]))
                receipt.counts["failed"] += 1
            else:
                conn.execute(
                    """UPDATE garmin_sync_gaps
                          SET status='resolved',resolved_at_utc=?,
                              last_attempt_at_utc=?
                        WHERE subject_id=? AND resource_kind=?
                          AND logical_object_key=?
                          AND stage='validate' AND reason_code='raw_integrity'
                          AND status IN ('open','deferred')""",
                    (
                        now, now, subject, row["resource_kind"],
                        row["provider_object_id"],
                    ),
                )
        # Field catalog drift is retained as a gap so it is visible to repair
        # and later quality policy, without inventing a canonical metric.
        for row in conn.execute(
            """SELECT resource_kind,count(*) AS count FROM source_field_catalog
                 WHERE provider='garmin' AND mapping_state='unknown'
                 GROUP BY resource_kind"""
        ):
            self.repo.gap(conn, subject, row["resource_kind"], f"field-signature:{row['resource_kind']}", start.isoformat(), "audit", "unmapped_field_signature", end_day=through.isoformat())
        # An activity has a durable summary and, where FIT has been requested,
        # an active parsed FIT revision.  This check never declares a FIT
        # mandatory: an existing FIT-stage gap is the evidence of intent.
        for row in conn.execute(
            """SELECT a.id,a.provider_activity_id,a.local_date
                 FROM activities a WHERE a.subject_id=? AND a.provider='garmin'
                   AND a.local_date BETWEEN ? AND ? AND a.provider_state='active'
                   AND NOT EXISTS (SELECT 1 FROM activity_source_revisions ar
                                   WHERE ar.activity_id=a.id AND ar.source_role='summary_json'
                                     AND ar.is_active=1)""",
            (subject, start.isoformat(), through.isoformat()),
        ):
            self.repo.gap(conn, subject, "activity_summary", f"garmin:activity:{row['provider_activity_id']}", row["local_date"], "audit", "activity_summary_missing")
        receipt.counts["fetched"] += 1

    def _repair_raw_bytes(self, row: sqlite3.Row) -> bytes:
        root = self.config.raw_root.parent.resolve()
        path = (root / str(row["relative_path"])).resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError("raw_object_corrupt")
        raw = path.read_bytes()
        if "size_bytes" in row.keys() and len(raw) != int(row["size_bytes"]):
            raise ValueError("raw_object_corrupt")
        return raw

    @staticmethod
    def _repair_day(provider_object_id: str, request: SyncRequest) -> str | None:
        matches = re.findall(r"\d{4}-\d{2}-\d{2}", provider_object_id)
        if matches:
            return matches[-1]
        return request.through_local_date or request.health_from_local_date

    @staticmethod
    def _activity_id_matches(provider_object_id: str, activity_id: str) -> bool:
        """Match activity ids as complete colon-delimited key segments."""
        return (
            provider_object_id == activity_id
            or provider_object_id.endswith(f":{activity_id}")
            or f":{activity_id}:" in provider_object_id
        )

    @staticmethod
    def _repair_range_dates(
        resource: str, provider_object_id: str, request: SyncRequest,
    ) -> tuple[date, date]:
        """Recover a bounded range key without guessing an endpoint day."""
        match = re.fullmatch(
            rf"garmin:health:{re.escape(resource)}:(\d{{4}}-\d{{2}}-\d{{2}}):(\d{{4}}-\d{{2}}-\d{{2}})",
            provider_object_id,
        )
        if match is None:
            raise ValueError("repair_range_key_invalid")
        start, end = (date.fromisoformat(value) for value in match.groups())
        if start > end:
            raise ValueError("repair_range_invalid_bounds")
        if request.health_from_local_date and start < date.fromisoformat(request.health_from_local_date):
            raise ValueError("repair_range_before_request")
        if request.through_local_date and end > date.fromisoformat(request.through_local_date):
            raise ValueError("repair_range_after_request")
        return start, end

    def _offline_repair(self, conn: sqlite3.Connection, run: int, subject: int, request: SyncRequest, receipt: SyncReceipt) -> None:
        resources = set(request.resource_kinds)
        if "activities" in resources:
            resources.remove("activities")
            resources.update(ACTIVITY_RESOURCE_KINDS)
        activity_ids = set(request.activity_ids)
        rows = list(conn.execute(
            """SELECT r.id,r.resource_kind,r.provider_object_id,r.is_current,r.parsed_at_utc,
                      r.payload_hash,o.relative_path,o.sha256,o.size_bytes
                 FROM source_revisions r JOIN raw_objects o ON o.id=r.raw_object_id
                WHERE r.provider='garmin'
                ORDER BY r.resource_kind,r.provider_object_id,r.revision_no DESC"""
        ))
        gap_filters = [
            "subject_id=?", "status IN ('open','deferred')",
            "source_revision_id IS NOT NULL",
        ]
        gap_parameters: list[Any] = [subject]
        if request.health_from_local_date:
            gap_filters.append("window_end_local_date>=?")
            gap_parameters.append(request.health_from_local_date)
        if request.through_local_date:
            gap_filters.append("window_start_local_date<=?")
            gap_parameters.append(request.through_local_date)
        gap_revision_ids = {
            int(row[0])
            for row in conn.execute(
                "SELECT DISTINCT source_revision_id FROM garmin_sync_gaps "
                f"WHERE {' AND '.join(gap_filters)}",
                gap_parameters,
            )
        }
        eligible_rows = [
            row for row in rows
            if (not resources or str(row["resource_kind"]) in resources)
            and (
                not activity_ids
                or any(
                    self._activity_id_matches(
                        str(row["provider_object_id"]), activity_id,
                    )
                    for activity_id in activity_ids
                )
            )
        ]
        # A revision-linked unresolved gap is precise recovery evidence.  Do
        # not rebuild adjacent/current revisions from the same resource while
        # such evidence exists in the requested window.
        gap_rows = [row for row in eligible_rows if int(row["id"]) in gap_revision_ids]
        if gap_rows:
            selected = {
                int(row["id"]): row
                for row in gap_rows
            }
        else:
            # Without an unresolved revision-linked gap, explicit reparse is a
            # safe rebuild of the newest revision for each logical object.
            selected = {}
            for row in eligible_rows:
                selected.setdefault(
                    (str(row["resource_kind"]), str(row["provider_object_id"])), row,
                )
        for row in selected.values():
            resource, key, revision = str(row["resource_kind"]), str(row["provider_object_id"]), int(row["id"])
            day = self._repair_day(key, request) or ""
            resolved_range_days: list[str] = []
            try:
                raw = self._repair_raw_bytes(row)
                if digest(raw) != row["sha256"]:
                    raise ValueError("raw_object_corrupt")
                conn.execute("BEGIN IMMEDIATE")
                if request.repair_strategy == "reconcile":
                    if resource == "activity_fit" or resource == "activity_summary":
                        activity_id = key.removeprefix("garmin:activity:")
                        activity = conn.execute("SELECT id,local_date FROM activities WHERE provider='garmin' AND provider_activity_id=?", (activity_id,)).fetchone()
                        if activity is None:
                            raise ValueError("activity_missing")
                        self._reconcile_activity(conn, run, subject, activity_id, int(activity["id"]), date.fromisoformat(activity["local_date"]), receipt)
                    else:
                        # Non-activity source selection has one current raw
                        # source.  Persist a deterministic check, not a fake
                        # canonical rewrite.
                        conn.execute("INSERT INTO reconciliation_results(entity_type,entity_id,field_key,left_source_revision_id,right_source_revision_id,result,checked_at_utc) VALUES(?,?,?,?,?,?,?)", ("source_revision", revision, "canonical_source", revision, revision, "match", utc_now()))
                    conn.execute("COMMIT")
                    receipt.counts["unchanged"] += 1
                    continue
                if resource == "activity_fit":
                    activity_id = key.removeprefix("garmin:activity:")
                    activity = conn.execute("SELECT id,local_date FROM activities WHERE provider='garmin' AND provider_activity_id=?", (activity_id,)).fetchone()
                    if activity is None:
                        raise ValueError("activity_missing")
                    local_activity_id = int(activity["id"])
                    # Rebuild the revision-bound FIT projection inside this
                    # transaction.  A parser failure rolls the deletes back,
                    # so the prior canonical/current projection remains
                    # available rather than becoming half-reparsed.
                    segment_ids = [
                        int(item[0]) for item in conn.execute(
                            """SELECT id FROM activity_segments
                               WHERE activity_id=? AND source_revision_id=?""",
                            (local_activity_id, revision),
                        )
                    ]
                    if segment_ids:
                        placeholders = ",".join("?" for _ in segment_ids)
                        conn.execute(
                            f"DELETE FROM climbing_routes WHERE segment_id IN ({placeholders})",
                            segment_ids,
                        )
                        conn.execute(
                            f"DELETE FROM strength_sets WHERE segment_id IN ({placeholders})",
                            segment_ids,
                        )
                    for table in (
                        "activity_samples", "activity_aux_messages",
                        "fit_metric_definitions", "activity_devices",
                        "fit_unknown_message_catalog",
                    ):
                        conn.execute(
                            f"DELETE FROM {table} WHERE source_revision_id=?",
                            (revision,),
                        )
                    conn.execute(
                        "DELETE FROM activity_segments WHERE activity_id=? AND source_revision_id=?",
                        (local_activity_id, revision),
                    )
                    conn.execute(
                        """DELETE FROM activity_metric_sources
                           WHERE activity_id=?
                             AND source_kind IN ('standard_fit','developer_fit')""",
                        (local_activity_id,),
                    )
                    conn.execute(
                        "DELETE FROM course_points WHERE activity_id=? AND course_identity='fit'",
                        (local_activity_id,),
                    )
                    activity_state = conn.execute(
                        "SELECT extras_json,source_map_json FROM activities WHERE id=?",
                        (local_activity_id,),
                    ).fetchone()
                    extras = json.loads(activity_state["extras_json"] or "{}")
                    source_map = json.loads(activity_state["source_map_json"] or "{}")
                    extras.pop("fit_session", None)
                    extras["fit_sessions"] = []
                    source_map.pop("fit_session", None)
                    source_map.pop("fit_sessions", None)
                    conn.execute(
                        "UPDATE activities SET extras_json=?,source_map_json=? WHERE id=?",
                        (
                            json.dumps(extras, sort_keys=True, allow_nan=False),
                            json.dumps(source_map, sort_keys=True, allow_nan=False),
                            local_activity_id,
                        ),
                    )
                    self._project_fit(conn, local_activity_id, raw, revision)
                    conn.execute(
                        """UPDATE activity_source_revisions SET is_active=0
                           WHERE activity_id=? AND source_role='activity_fit'""",
                        (local_activity_id,),
                    )
                    conn.execute(
                        """INSERT INTO activity_source_revisions(
                               activity_id,source_revision_id,source_role,is_active
                           ) VALUES(?,?,?,1)
                           ON CONFLICT(activity_id,source_revision_id,source_role)
                           DO UPDATE SET is_active=1""",
                        (local_activity_id, revision, "activity_fit"),
                    )
                    self._promote_fit_canonical(conn, local_activity_id, revision)
                    day = str(activity["local_date"])
                elif resource == "activity_summary":
                    payload, _canonical = parse_provider_json_bytes(raw)
                    validated = self._validate_activity_summary(payload, key)
                    local_activity_id = self._project_activity(
                        conn, subject, key, payload, validated, revision
                    )
                    conn.execute(
                        """UPDATE activity_source_revisions SET is_active=1
                           WHERE activity_id=? AND source_revision_id=?
                             AND source_role='summary_json'""",
                        (local_activity_id, revision),
                    )
                    day = str(validated["local_date"])
                elif resource in HEALTH_RESOURCES:
                    payload, _canonical = parse_provider_json_bytes(raw)
                    spec = RESOURCE_CATALOG[resource]
                    if spec.scope == "range":
                        range_start, range_end = self._repair_range_dates(resource, key, request)
                        # Validate the entire immutable response before
                        # replacing a single day's canonical projection.
                        by_day = self._range_payload_by_day(
                            payload, range_start, range_end, resource=resource,
                        )
                        lactate_envelope = resource == "lactate_threshold" and isinstance(payload, dict) and any(
                            isinstance(payload.get(family), list)
                            for family in ("heart_rate", "power", "speed")
                        )
                        if lactate_envelope:
                            self.repo.fields(conn, resource, payload)
                        for current_day in (
                            range_start + timedelta(index)
                            for index in range((range_end - range_start).days + 1)
                        ):
                            current_day_text = current_day.isoformat()
                            day_payload = by_day[current_day_text]
                            self._supersede_range_projection(
                                conn, subject, resource, current_day_text,
                            )
                            if not lactate_envelope:
                                self.repo.fields(conn, resource, day_payload)
                            count = (
                                self._project_health(
                                    conn, subject, resource, current_day_text,
                                    day_payload, revision,
                                )
                                if day_payload else 0
                            )
                            self.repo.coverage(
                                conn, subject, resource, current_day_text,
                                "fetched" if day_payload else "empty", revision, count,
                            )
                            resolved_range_days.append(current_day_text)
                    else:
                        if not day:
                            raise ValueError("repair_date_unknown")
                        self.repo.fields(conn, resource, payload)
                        self._supersede_health_projection(conn, subject, resource, key, day)
                        count = self._project_health(conn, subject, resource, day, payload, revision)
                        self.repo.coverage(conn, subject, resource, day, "fetched", revision, count)
                else:
                    # Archive-only resources still get their raw syntax and
                    # field signature verified; their existing projection is
                    # intentionally left untouched until a typed projector is
                    # available rather than guessed here.
                    payload, _canonical = parse_provider_json_bytes(raw)
                    self.repo.fields(conn, resource, payload)
                current = conn.execute("SELECT id FROM source_revisions WHERE provider='garmin' AND resource_kind=? AND provider_object_id=? AND is_current=1", (resource, key)).fetchone()
                if current is not None and int(current["id"]) != revision:
                    conn.execute("UPDATE source_revisions SET is_current=0 WHERE id=?", (int(current["id"]),))
                conn.execute("UPDATE source_revisions SET is_current=1,parsed_at_utc=?,parser_version=? WHERE id=?", (utc_now(), PARSER_VERSION, revision))
                conn.execute("COMMIT")
                if resolved_range_days:
                    for resolved_day in resolved_range_days:
                        self.repo.resolve_gaps(
                            conn, subject, resource, resolved_day,
                            logical_object_key=key,
                        )
                elif day:
                    self.repo.resolve_gaps(conn, subject, resource, day)
                receipt.counts["revised"] += 1
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                self.repo.gap(conn, subject, resource, key, day, "reparse" if request.repair_strategy == "reparse" else "reconcile", "offline_repair_failed", revision=revision)
                receipt.counts["failed"] += 1

    def _status(self, receipt: SyncReceipt) -> SyncReceipt:
        conn = self.repo.connect(readonly=True)
        try:
            row = conn.execute("SELECT id FROM data_subjects WHERE subject_key=?", (self.config.subject_key,)).fetchone()
            if row is None:
                receipt.status = "succeeded"; receipt.completed_at_utc = utc_now(); return receipt
            subject = int(row["id"]); receipt.status = "succeeded"; receipt.open_gap_count = int(conn.execute("SELECT count(*) FROM garmin_sync_gaps WHERE subject_id=? AND status IN ('open','deferred')", (subject,)).fetchone()[0]); receipt.complete_through_by_resource = {row["resource_kind"]: row["complete_through_local_date"] for row in conn.execute("SELECT resource_kind,complete_through_local_date FROM garmin_sync_cursors WHERE subject_id=?", (subject,))}; receipt.completed_at_utc = utc_now(); return receipt
        finally: conn.close()

    def _auth(self, receipt: SyncReceipt) -> SyncReceipt:
        if self.transport is None:
            receipt.status = "auth_required"; receipt.errors.append({"code":"interactive_provider_required","resource":"auth","logical_object_key":"garmin:account:identity","summary":"no credential provider"})
        else:
            self.transport.login()
            identity = self._identity_hmac(self.transport.identity())
            conn = self.repo.connect()
            try:
                subject = self.repo.subject(conn)
                existing = conn.execute("SELECT subject_id FROM subject_identities WHERE provider='garmin' AND identity_kind='account' AND identity_hmac=?", (identity,)).fetchone()
                if existing and int(existing["subject_id"]) != subject:
                    receipt.status = "failed"; receipt.errors.append({"code":"identity_mismatch","resource":"auth","logical_object_key":"garmin:account:identity","summary":"identity mismatch"})
                else:
                    now = utc_now()
                    conn.execute("INSERT OR IGNORE INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) VALUES(?,?,?,?,1,?,?)", (subject, "garmin", "account", identity, now, now))
                    conn.execute("UPDATE subject_identities SET last_seen_at_utc=?,is_verified=1 WHERE provider='garmin' AND identity_kind='account' AND identity_hmac=?", (now, identity))
                    receipt.status = "succeeded"
            finally: conn.close()
        receipt.completed_at_utc = utc_now(); return receipt

    def _identity_hmac(self, identity: str) -> str:
        key_path = self.config.state_root / "secrets" / "garmin-identity.key"; key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not key_path.exists():
            fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try: os.write(fd, os.urandom(32))
            finally: os.close(fd)
        key = key_path.read_bytes(); os.chmod(key_path, 0o600)
        return hmac.new(key, identity.encode(), hashlib.sha256).hexdigest()

    def _transport(self) -> GarminTransport:
        if self.transport is None: raise GarminError("transport_not_configured")
        return self.transport

    def _validate(self, request: SyncRequest) -> None:
        if not 1 <= self.config.max_attempts <= 5: raise ValueError("max_attempts_out_of_range")
        if self.config.request_min_interval_ms < 0 or self.config.request_interval_jitter_ms < 0 or self.config.request_timeout_seconds <= 0 or self.config.retry_base_seconds <= 0 or self.config.retry_max_seconds <= 0 or self.config.inline_retry_after_max_seconds < 0 or self.config.rate_limit_fallback_seconds <= 0: raise ValueError("invalid_retry_configuration")
        if self.config.lookback_days < 1: raise ValueError("lookback_days_out_of_range")
        if self.config.max_repair_items_per_incremental < 0: raise ValueError("invalid_repair_item_limit")
        if request.mode not in {"auth","full","incremental","snapshot","repair","audit","status"}: raise ValueError("invalid_mode")
        if request.mode == "full" and not (request.health_from_local_date or self.config.history_start_date): raise ValueError("history_start_date_required")
        if request.mode == "incremental" and not self.config.history_start_date: raise ValueError("history_start_date_required")
        if request.mode == "repair" and not (request.health_from_local_date or request.through_local_date or request.resource_kinds or request.activity_ids): raise ValueError("repair_requires_scope")
        if request.mode == "snapshot" and request.through_local_date: raise ValueError("snapshot_uses_snapshot_date")
        if request.mode in {"auth", "status"} and any((request.health_from_local_date, request.through_local_date, request.snapshot_local_date, request.resource_kinds, request.activity_ids, request.repair_strategy)):
            raise ValueError("mode_requires_empty_scope")
        if request.mode in {"full", "incremental", "audit"} and any((request.snapshot_local_date, request.activity_ids, request.repair_strategy)):
            raise ValueError("mode_has_incompatible_parameters")
        if request.mode == "snapshot" and any((request.health_from_local_date, request.resource_kinds, request.activity_ids, request.repair_strategy)):
            raise ValueError("mode_has_incompatible_parameters")
        if request.mode == "repair" and request.snapshot_local_date:
            raise ValueError("mode_has_incompatible_parameters")
        if any(resource not in REQUEST_RESOURCE_KINDS for resource in request.resource_kinds):
            raise ValueError("resource_kind_invalid")
        for value in (request.health_from_local_date, request.through_local_date, request.snapshot_local_date):
            if value: date.fromisoformat(value)
        if self.config.history_start_date:
            date.fromisoformat(self.config.history_start_date)
        today = self._today_local()
        if request.mode in {"full", "incremental"}:
            through = (
                date.fromisoformat(request.through_local_date)
                if request.through_local_date
                else today - timedelta(days=1)
            )
            if through >= today:
                raise ValueError("completed_mode_through_must_be_before_today")
            if request.mode == "full":
                start = date.fromisoformat(
                    request.health_from_local_date
                    or self.config.history_start_date
                    or ""
                )
                if start > through:
                    raise ValueError("sync_range_start_after_through")
            elif date.fromisoformat(self.config.history_start_date or "") > through:
                raise ValueError("sync_range_start_after_through")
        if request.mode == "snapshot":
            snapshot_day = date.fromisoformat(
                request.snapshot_local_date or today.isoformat()
            )
            if snapshot_day > today:
                raise ValueError("snapshot_date_in_future")
        if request.mode in {"repair", "audit"}:
            through = date.fromisoformat(request.through_local_date) if request.through_local_date else today
            if through > today:
                raise ValueError("repair_or_audit_through_must_not_be_after_today")
            if request.health_from_local_date and date.fromisoformat(request.health_from_local_date) > through:
                raise ValueError("sync_range_start_after_through")
        schema_path = Path(__file__).resolve().parents[2] / "harness" / "schemas" / "garmin_sync_request.schema.json"
        payload = asdict(request); payload["resource_kinds"] = list(request.resource_kinds); payload["activity_ids"] = list(request.activity_ids)
        if list(Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8"))).iter_errors(payload)): raise ValueError("invalid_sync_request_schema")

    @staticmethod
    def _validated_receipt(receipt: SyncReceipt) -> SyncReceipt:
        for error in receipt.errors:
            original = str(error.get("code") or "provider_error")
            safe = safe_provider_error_code(original)
            error["code"] = safe
            if safe != original:
                error["summary"] = "provider request failed"
        schema_path = Path(__file__).resolve().parents[2] / "harness" / "schemas" / "garmin_sync_receipt.schema.json"
        if list(Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8"))).iter_errors(asdict(receipt))):
            raise RuntimeError("invalid_sync_receipt_schema")
        return receipt
