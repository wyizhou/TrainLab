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
from typing import Any, Callable, Iterable, Literal, Mapping, Protocol
from zoneinfo import ZoneInfo

import fitdecode
from jsonschema import Draft202012Validator
from ..garmin_catalog import (
    ACTIVITY_COLLECTION_ALLOWLIST,
    CATALOG_VERSION,
    COLLECTED_HEALTH_RESOURCES,
    DEFAULT_ACTIVITY_ENRICHMENTS,
    EXTRA_ROLES,
    HEALTH_RESOURCES,
    RESOURCE_CATALOG,
)
from ..garmin_modes import (
    INCREMENTAL_LOOKBACK_DAYS,
    CollectionModePlan,
    ResourceDateWindow,
    build_collection_mode_plan,
)

COLLECTOR_VERSION = "1"
GARMINCONNECT_VERSION = "0.3.6"
PARSER_VERSION = "fitdecode-0.11.0"
ACCOUNT_PROFILE_SEMANTIC_VERSION = "account-profile-v1"
DEVICE_REFERENCE_SEMANTIC_VERSION = "device-reference-v1"
TZ = ZoneInfo("Asia/Hong_Kong")

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
    "hrv": {
        "lastNightAvg": ("garmin.hrv.last_night_average_ms", "ms", "ms", "provider_derived", "/hrvSummary/lastNightAvg"),
        "weeklyAvg": ("garmin.hrv.weekly_average_ms", "ms", "ms", "provider_derived", "/hrvSummary/weeklyAvg"),
        "lastNight5MinHigh": ("garmin.hrv.last_night_5_min_high_ms", "ms", "ms", "provider_derived", "/hrvSummary/lastNight5MinHigh"),
    },
    "rhr": {
        "restingHeartRate": ("garmin.daily.resting_heart_rate_bpm", "bpm", "bpm", "provider_derived", "/allMetrics/metricsMap/WELLNESS_RESTING_HEART_RATE/*/value"),
    },
    "heart_rates": {
        "minHeartRate": ("garmin.heart_rate.daily_min_bpm", "bpm", "bpm", "provider_derived", "/minHeartRate"),
        "maxHeartRate": ("garmin.heart_rate.daily_max_bpm", "bpm", "bpm", "provider_derived", "/maxHeartRate"),
        "restingHeartRate": ("garmin.daily.resting_heart_rate_bpm", "bpm", "bpm", "provider_derived", "/restingHeartRate"),
        "lastSevenDaysAvgRestingHeartRate": ("garmin.heart_rate.resting_7d_average_bpm", "bpm", "bpm", "provider_derived", "/lastSevenDaysAvgRestingHeartRate"),
        "dailyAverageHeartRate": ("garmin.heart_rate.daily_average_bpm", "bpm", "bpm", "derived_statistic", "/heartRateValues/*/1"),
    },
    "spo2": {
        "averageSpO2": ("garmin.spo2.daily_average_percent", "%", "%", "provider_derived", "/averageSpO2"),
        "avgSleepSpO2": ("garmin.spo2.sleep_average_percent", "%", "%", "provider_derived", "/avgSleepSpO2"),
        "latestSpO2": ("garmin.spo2.latest_percent", "%", "%", "provider_derived", "/latestSpO2"),
        "lowestSpO2": ("garmin.spo2.daily_lowest_percent", "%", "%", "provider_derived", "/lowestSpO2"),
        "lastSevenDaysAvgSpO2": ("garmin.spo2.seven_day_average_percent", "%", "%", "provider_derived", "/lastSevenDaysAvgSpO2"),
    },
    "weigh_ins": {
        "weight": ("garmin.body.weight_kg", "g", "kg", "sensor_observed", "/*/weight"),
        "weightKg": ("garmin.body.weight_kg", "kg", "kg", "sensor_observed", "/*/weightKg"),
    },
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
    "max_metrics": {
        "vo2MaxPreciseValue": ("garmin.vo2_max.ml_per_kg_min", "ml/kg/min", "ml/kg/min", "provider_derived", "/*/generic/vo2MaxPreciseValue"),
        "vo2MaxValue": ("garmin.vo2_max.ml_per_kg_min", "ml/kg/min", "ml/kg/min", "provider_derived", "/*/generic/vo2MaxValue"),
        "vo2Max": ("garmin.vo2_max.ml_per_kg_min", "ml/kg/min", "ml/kg/min", "provider_derived", "/vo2Max"),
    },
    "lactate_threshold": {"lactateThresholdHeartRate": ("garmin.lactate_threshold.heart_rate_bpm", "bpm", "bpm", "provider_derived", "/lactateThresholdHeartRate"), "lactateThresholdPower": ("garmin.lactate_threshold.power_w", "W", "W", "provider_derived", "/lactateThresholdPower"), "lactateThresholdSpeed": ("garmin.lactate_threshold.speed_mps", "m/s", "m/s", "provider_derived", "/lactateThresholdSpeed")},
    "training_status": {"trainingStatusScore": ("garmin.training_status.score", "score", "score", "provider_derived", "/trainingStatusScore"), "acuteTrainingLoad": ("garmin.training_status.acute_load", "load", "load", "provider_derived", "/acuteTrainingLoad")},
    "running_tolerance": {"runningTolerance": ("garmin.running_tolerance.score", "score", "score", "provider_derived", "/runningTolerance"), "weeklyMileage": ("garmin.running_tolerance.weekly_distance_m", "m", "m", "provider_derived", "/weeklyMileage")},
    "endurance_score": {
        "enduranceScore": ("garmin.endurance_score", "score", "score", "provider_derived", "/enduranceScore"),
        "overallScore": ("garmin.endurance_score", "score", "score", "provider_derived", "/overallScore"),
    },
    "hill_score": {"hillScore": ("garmin.hill_score", "score", "score", "provider_derived", "/hillScore")},
    # Garmin predictions are retained as provider-derived observations.  The
    # active collection contract does not mint a separate provider_predicted
    # trust class; the prediction semantics remain in the metric key/source.
    "race_predictions": {"predictionSeconds": ("garmin.race_prediction.seconds", "s", "s", "provider_derived", "/predictionSeconds"), "time": ("garmin.race_prediction.seconds", "s", "s", "provider_derived", "/time")},
    "fitness_age": {"fitnessAge": ("garmin.fitness_age.years", "year", "year", "provider_derived", "/fitnessAge")},
    "menstrual_day": {"cycleLength": ("garmin.menstrual.cycle_length_days", "day", "day", "provider_derived", "/cycleLength"), "periodLength": ("garmin.menstrual.period_length_days", "day", "day", "provider_derived", "/periodLength"), "predictedCycleLength": ("garmin.menstrual.predicted_cycle_length_days", "day", "day", "provider_derived", "/predictedCycleLength")},
    "menstrual": {"cycleLength": ("garmin.menstrual.cycle_length_days", "day", "day", "provider_derived", "/cycleLength"), "periodLength": ("garmin.menstrual.period_length_days", "day", "day", "provider_derived", "/periodLength"), "predictedCycleLength": ("garmin.menstrual.predicted_cycle_length_days", "day", "day", "provider_derived", "/predictedCycleLength")},
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
    "fit_not_available_for_activity_format", "activity_original_missing",
    "activity_original_ambiguous", "activity_original_archive_failed",
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
    lookback_days: int = INCREMENTAL_LOOKBACK_DAYS
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
