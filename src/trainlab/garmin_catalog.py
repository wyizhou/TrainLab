"""Versioned, audited Garmin Connect resource semantics.

This module intentionally contains *descriptions*, not provider calls.  The
descriptions are the single source of truth used to plan collection work.  A
resource whose installed ``python-garminconnect`` client has no matching
endpoint is recorded as ``not_supported`` rather than being guessed or
silently represented as an empty successful response.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CATALOG_VERSION = "garmin-v3"
ADAPTER_VERSION = "garminconnect-0.3.6"
PARSER_VERSION = "fitdecode-0.11.0"

Scope = Literal["account", "daily", "range", "activity"]
Disposition = Literal["required", "conditional", "ignored"]
RawKind = Literal["json", "fit", "none"]
Mode = Literal["full", "incremental", "snapshot", "repair"]


@dataclass(frozen=True)
class GarminResourceSpec:
    """One semantic provider fact, including its deterministic absence policy."""

    resource_kind: str
    method: str | None
    argument_shape: tuple[str, ...]
    scope: Scope
    disposition: Disposition
    date_chunk: str
    max_range_days: int | None
    modes: frozenset[Mode]
    empty_state: Literal["empty", "not_enabled", "not_available"]
    allowed_404_state: Literal["not_available", "not_supported", "forbidden"]
    capability_state: Literal["supported", "not_enabled", "not_available", "not_supported"]
    raw_kind: RawKind
    source_role: str | None
    adapter_version: str
    parser_version: str | None
    projection_targets: tuple[str, ...]
    cursor_eligible: bool
    ignored_with_reason: str | None = None

    @property
    def requestable(self) -> bool:
        return self.disposition != "ignored" and self.method is not None

    @property
    def required(self) -> bool:
        return self.disposition == "required"

    @property
    def conditional(self) -> bool:
        return self.disposition == "conditional"

    @property
    def allows_404(self) -> bool:
        return self.allowed_404_state in {"not_available", "not_supported"}

    @property
    def ignored_reason(self) -> str | None:
        """Backward-compatible read-only spelling used by early callers."""
        return self.ignored_with_reason


def _spec(
    kind: str,
    method: str | None,
    arguments: tuple[str, ...],
    scope: Scope,
    disposition: Disposition,
    *,
    chunk: str = "one_local_day",
    max_range_days: int | None = None,
    modes: frozenset[Mode] = frozenset({"full", "incremental", "snapshot", "repair"}),
    empty: Literal["empty", "not_enabled", "not_available"] = "empty",
    missing: Literal["not_available", "not_supported", "forbidden"] = "not_available",
    capability: Literal["supported", "not_enabled", "not_available", "not_supported"] = "supported",
    raw: RawKind = "json",
    role: str | None = None,
    parser: str | None = None,
    targets: tuple[str, ...] = (),
    cursor: bool = False,
    ignored: str | None = None,
) -> GarminResourceSpec:
    if role is None and disposition != "ignored":
        role = "account" if scope == "account" else "health"
    return GarminResourceSpec(
        kind, method, arguments, scope, disposition, chunk, max_range_days, modes, empty, missing,
        capability, raw, role, ADAPTER_VERSION, parser, targets, cursor, ignored,
    )


_DAY_MODES = frozenset({"full", "incremental", "snapshot", "repair"})
_NO_SNAPSHOT = frozenset({"full", "incremental", "repair"})
_ACTIVITY_MODES = frozenset({"full", "incremental", "snapshot", "repair"})

# Each non-ignored method and argument shape is verified against the pinned
# 0.3.6 class in tests.  Keeping unavailable capabilities explicit means a
# newer endpoint cannot accidentally start being called before its semantics
# and canonical projection have been reviewed.
_SPECS = (
    # Account and devices.
    _spec("user_profile", "get_user_profile", (), "account", "required", chunk="account_snapshot", missing="forbidden", targets=("data_subjects", "physiology_records")),
    _spec("user_profile_settings", "get_userprofile_settings", (), "account", "conditional", chunk="account_snapshot", targets=("physiology_records",)),
    _spec("devices", "get_devices", (), "account", "conditional", chunk="account_snapshot", targets=("devices", "physiology_records")),
    _spec("primary_device", "get_primary_training_device", (), "account", "conditional", chunk="account_snapshot", targets=("devices", "physiology_records", "physiology_metrics")),
    _spec("device_settings", "get_device_settings", ("device_id",), "account", "conditional", chunk="per_device", targets=("devices", "physiology_records", "physiology_metrics")),
    _spec("device_last_used", "get_device_last_used", (), "account", "conditional", chunk="account_snapshot", targets=("devices", "physiology_records", "physiology_metrics")),
    _spec("personal_records", "get_personal_record", (), "account", "conditional", chunk="account_snapshot", targets=("physiology_records", "physiology_metrics")),
    # Daily/range health data.
    _spec("user_summary", "get_user_summary", ("local_date",), "daily", "required", missing="forbidden", targets=("daily_health",), cursor=True),
    _spec("steps", "get_steps_data", ("local_date",), "daily", "required", targets=("health_samples", "daily_health"), cursor=True),
    _spec("floors", "get_floors", ("local_date",), "daily", "conditional", targets=("health_samples", "daily_health"), cursor=True),
    _spec("heart_rates", "get_heart_rates", ("local_date",), "daily", "conditional", targets=("health_samples", "daily_health"), cursor=True),
    _spec("rhr", "get_rhr_day", ("local_date",), "daily", "conditional", targets=("health_samples", "daily_health"), cursor=True),
    _spec("hydration", "get_hydration_data", ("local_date",), "daily", "conditional", targets=("health_samples", "daily_health"), cursor=True),
    _spec("respiration", "get_respiration_data", ("local_date",), "daily", "conditional", targets=("health_samples", "daily_health"), cursor=True),
    _spec("spo2", "get_spo2_data", ("local_date",), "daily", "conditional", targets=("health_samples", "daily_health"), cursor=True),
    _spec("intensity_minutes", "get_intensity_minutes_data", ("local_date",), "daily", "conditional", targets=("daily_health", "physiology_metrics"), cursor=True),
    _spec("stress", "get_all_day_stress", ("local_date",), "daily", "conditional", targets=("health_samples", "daily_health"), cursor=True),
    _spec("all_day_events", "get_all_day_events", ("local_date",), "daily", "conditional", targets=("physiology_records",), cursor=True),
    _spec("sleep", "get_sleep_data", ("local_date",), "daily", "conditional", targets=("sleep_sessions", "sleep_stages", "health_samples"), cursor=True),
    _spec("lifestyle", "get_lifestyle_logging_data", ("local_date",), "daily", "conditional", targets=("physiology_records", "physiology_metrics"), cursor=True),
    _spec("hrv", "get_hrv_data", ("local_date",), "daily", "conditional", targets=("health_samples", "physiology_records"), cursor=True),
    _spec("body_battery", "get_body_battery", ("start_date", "end_date"), "range", "conditional", chunk="bounded_date_range", max_range_days=14, targets=("health_samples", "physiology_records"), cursor=True),
    _spec("body_battery_events", "get_body_battery_events", ("local_date",), "daily", "conditional", targets=("physiology_records",), cursor=True),
    _spec("body_composition", "get_body_composition", ("start_date", "end_date"), "range", "conditional", chunk="bounded_date_range", max_range_days=14, targets=("body_measurements",), cursor=True),
    _spec("weigh_ins", "get_weigh_ins", ("start_date", "end_date"), "range", "conditional", chunk="bounded_date_range", max_range_days=14, targets=("body_measurements",), cursor=True),
    _spec("blood_pressure", "get_blood_pressure", ("start_date", "end_date"), "range", "conditional", chunk="bounded_date_range", max_range_days=14, targets=("body_measurements", "physiology_records"), cursor=True),
    _spec("training_readiness", "get_training_readiness", ("local_date",), "daily", "conditional", targets=("physiology_records", "physiology_metrics"), cursor=True),
    _spec("max_metrics", "get_max_metrics", ("local_date",), "daily", "conditional", targets=("physiology_records", "physiology_metrics"), cursor=True),
    _spec("lactate_threshold", "get_lactate_threshold", ("start_date", "end_date", "aggregation=daily"), "range", "conditional", chunk="bounded_date_range", max_range_days=14, targets=("physiology_records", "physiology_metrics"), cursor=True),
    _spec("training_status", "get_training_status", ("local_date",), "daily", "conditional", targets=("physiology_records", "physiology_metrics"), cursor=True),
    _spec("running_tolerance", "get_running_tolerance", ("start_date", "end_date", "aggregation=weekly"), "range", "conditional", chunk="bounded_date_range", max_range_days=14, targets=("physiology_records", "physiology_metrics"), cursor=True),
    _spec("endurance_score", "get_endurance_score", ("start_date", "end_date"), "range", "conditional", chunk="bounded_date_range", max_range_days=14, targets=("physiology_records", "physiology_metrics"), cursor=True),
    _spec("hill_score", "get_hill_score", ("start_date", "end_date"), "range", "conditional", chunk="bounded_date_range", max_range_days=14, targets=("physiology_records", "physiology_metrics"), cursor=True),
    _spec("race_predictions", "get_race_predictions", ("start_date", "end_date"), "range", "conditional", chunk="bounded_date_range", max_range_days=14, targets=("physiology_records", "physiology_metrics"), cursor=True),
    _spec("fitness_age", "get_fitnessage_data", ("local_date",), "daily", "conditional", targets=("physiology_records", "physiology_metrics"), cursor=True),
    _spec("cycling_ftp", "get_cycling_ftp", (), "account", "conditional", chunk="account_snapshot", targets=("physiology_records", "physiology_metrics")),
    _spec("menstrual_day", "get_menstrual_data_for_date", ("local_date",), "daily", "conditional", empty="not_enabled", targets=("physiology_records", "physiology_metrics"), cursor=True),
    _spec("menstrual", "get_menstrual_calendar_data", ("start_date", "end_date"), "range", "conditional", chunk="bounded_date_range", max_range_days=14, empty="not_enabled", targets=("physiology_records", "physiology_metrics"), cursor=True),
    _spec("pregnancy", "get_pregnancy_summary", (), "account", "conditional", chunk="account_snapshot", empty="not_enabled", targets=("physiology_records", "physiology_metrics")),
    _spec("nutrition_food_log", "get_nutrition_daily_food_log", ("local_date",), "daily", "conditional", empty="not_enabled", targets=("physiology_records", "physiology_metrics"), cursor=True),
    _spec("nutrition_meals", "get_nutrition_daily_meals", ("local_date",), "daily", "conditional", empty="not_enabled", targets=("physiology_records", "physiology_metrics"), cursor=True),
    _spec("nutrition_settings", "get_nutrition_daily_settings", ("local_date",), "daily", "conditional", empty="not_enabled", targets=("physiology_records", "physiology_metrics"), cursor=True),
    # Completed activity pipeline and enrichments.
    _spec("activity_inventory", "get_activities", ("offset", "limit"), "activity", "required", chunk="paged_account_history", modes=_ACTIVITY_MODES, role="inventory", targets=("activity_source_revisions",)),
    _spec("activity_summary", "get_activity", ("activity_id",), "activity", "required", chunk="one_activity", modes=_ACTIVITY_MODES, role="summary", targets=("activities", "activity_source_revisions")),
    _spec("activity_fit", "download_activity", ("activity_id", "ORIGINAL"), "activity", "conditional", chunk="one_activity", modes=_ACTIVITY_MODES, raw="fit", role="FIT", parser=PARSER_VERSION, targets=("activity_samples", "activity_segments", "fit_metric_definitions", "activity_source_revisions")),
    _spec("activity_details_fallback", "get_activity_details", ("activity_id", "maxchart", "maxpoly"), "activity", "conditional", chunk="one_activity", modes=_ACTIVITY_MODES, role="details_json_fallback", targets=("activity_source_revisions",)),
    _spec("activity_splits", "get_activity_splits", ("activity_id",), "activity", "conditional", chunk="one_activity", modes=_ACTIVITY_MODES, role="splits", targets=("activity_source_revisions",)),
    _spec("activity_typed_splits", "get_activity_typed_splits", ("activity_id",), "activity", "conditional", chunk="one_activity", modes=_ACTIVITY_MODES, role="typed_splits", targets=("activity_source_revisions",)),
    _spec("activity_split_summaries", "get_activity_split_summaries", ("activity_id",), "activity", "conditional", chunk="one_activity", modes=_ACTIVITY_MODES, role="split_summaries", targets=("activity_source_revisions",)),
    _spec("activity_exercise_sets", "get_activity_exercise_sets", ("activity_id",), "activity", "conditional", chunk="one_activity", modes=_ACTIVITY_MODES, role="sets", targets=("strength_sets", "activity_source_revisions")),
    _spec("activity_hr_zones", "get_activity_hr_in_timezones", ("activity_id",), "activity", "conditional", chunk="one_activity", modes=_ACTIVITY_MODES, role="hr_zones", targets=("activity_source_revisions",)),
    _spec("activity_power_zones", "get_activity_power_in_timezones", ("activity_id",), "activity", "conditional", chunk="one_activity", modes=_ACTIVITY_MODES, role="power_zones", targets=("activity_source_revisions",)),
    _spec("activity_weather", "get_activity_weather", ("activity_id",), "activity", "conditional", chunk="one_activity", modes=_ACTIVITY_MODES, role="weather", targets=("activity_source_revisions",)),
    _spec("activity_gear", "get_activity_gear", ("activity_id",), "activity", "conditional", chunk="one_activity", modes=_ACTIVITY_MODES, role="gear", targets=("activity_source_revisions",)),
)

_IGNORED = {
    "get_daily_steps": "alias:steps_data; range helper only, not a second canonical stream",
    "get_daily_weigh_ins": "alias:weigh_ins; avoids duplicate body measurement source",
    "get_unit_system": "alias:user_profile_settings; presentation preference, not physiology",
    "get_activities_by_date": "alias:activity_inventory",
    "get_activities_fordate": "alias:activity_inventory",
    "get_activity_types": "metadata_only:catalog does not require remote type registry",
    "get_adaptive_training_plan_by_id": "excluded:future_plan",
    "get_adhoc_challenges": "excluded:social_reward",
    "get_available_badge_challenges": "excluded:non_health_reward",
    "get_available_badges": "excluded:non_health_reward",
    "get_badge_challenges": "excluded:social_reward",
    "get_device_alarms": "excluded:non_health_device_setting",
    "get_device_solar_data": "excluded:non_health_device_telemetry",
    "get_earned_badges": "excluded:non_health_reward",
    "get_full_name": "identity_only:auth binding, not collection resource",
    "get_gear": "excluded:activity_gear endpoint is canonical source",
    "get_gear_activities": "excluded:activity_gear endpoint is canonical source",
    "get_gear_defaults": "excluded:activity_gear endpoint is canonical source",
    "get_gear_stats": "excluded:activity_gear endpoint is canonical source",
    "get_goals": "excluded:future_goal",
    "get_golf_scorecard": "excluded:golf_social",
    "get_golf_shot_data": "excluded:golf_social",
    "get_golf_summary": "excluded:golf_social",
    "get_in_progress_badges": "excluded:non_health_reward",
    "get_inprogress_virtual_challenges": "excluded:social_reward",
    "get_last_activity": "alias:activity_inventory",
    "get_morning_training_readiness": "subset:training_readiness",
    "get_non_completed_badge_challenges": "excluded:social_reward",
    "get_progress_summary_between_dates": "locally_recomputable:completed_activities",
    "get_scheduled_workout_by_id": "excluded:future_workout",
    "get_scheduled_workouts": "excluded:future_workout",
    "get_training_plan_by_id": "excluded:future_plan",
    "get_training_plans": "excluded:future_plan",
    "get_weekly_intensity_minutes": "locally_recomputable:daily_intensity_minutes",
    "get_weekly_steps": "locally_recomputable:daily_steps",
    "get_weekly_stress": "locally_recomputable:daily_stress",
    "get_workout_by_id": "excluded:future_workout",
    "get_workouts": "excluded:future_workout",
    "get_stats": "alias:user_summary",
    "get_stats_and_body": "client_combination:user_summary+body_composition",
    "get_stress_data": "alias:stress",
    "get_morning_training_readiness": "subset:training_readiness",
    "weekly_steps": "locally_recomputable:daily_steps",
    "weekly_stress": "locally_recomputable:daily_stress",
    "weekly_intensity_minutes": "locally_recomputable:daily_intensity_minutes",
    "progress_summary": "locally_recomputable:completed_activities",
    "last_activity": "inventory_wrapper:activity_inventory",
    "activities_for_date": "inventory_wrapper:activity_inventory",
    "badges": "excluded:non_health_reward",
    "challenges": "excluded:social_reward",
    "social": "excluded:social",
    "goals": "excluded:future_goal",
    "workout_templates": "excluded:future_workout",
    "scheduled_workouts": "excluded:future_workout",
    "training_plans": "excluded:future_plan",
    "activity_upload_edit_delete": "excluded:mutating_api",
    "golf_community": "excluded:golf_social; activities remain covered",
    "device_alarms": "excluded:non_health_device_setting",
    "device_solar": "excluded:non_health_device_telemetry",
}

RESOURCE_CATALOG: dict[str, GarminResourceSpec] = {spec.resource_kind: spec for spec in _SPECS}
RESOURCE_CATALOG.update({
    name: _spec(name, None, (), "account", "ignored", chunk="not_planned", modes=frozenset(), raw="none", ignored=reason)
    for name, reason in _IGNORED.items()
})

# Compatibility names used by the early collection pipeline.  They now derive
# from the catalog, so a resource cannot be added to a fetch loop without a
# reviewed resource description.
HEALTH_RESOURCES = tuple(
    spec.resource_kind for spec in _SPECS
    if spec.scope in {"daily", "range"} and spec.requestable
)
_ROLE_TO_LEGACY_EXTRA = {
    "splits": "splits_json",
    "typed_splits": "typed_splits_json",
    "split_summaries": "split_summaries_json",
    "sets": "exercise_sets_json",
    "hr_zones": "hr_zones_json",
    "power_zones": "power_zones_json",
    "weather": "weather_json",
    "gear": "gear_json",
}
EXTRA_ROLES = tuple(
    _ROLE_TO_LEGACY_EXTRA[spec.source_role]
    for spec in _SPECS
    if spec.scope == "activity" and spec.source_role in _ROLE_TO_LEGACY_EXTRA
)


def specs_for_mode(mode: Mode, *, include_ignored: bool = False) -> tuple[GarminResourceSpec, ...]:
    """Deterministic work-plan input for full/incremental/snapshot/repair."""
    return tuple(
        spec for spec in RESOURCE_CATALOG.values()
        if (include_ignored and spec.disposition == "ignored") or (spec.requestable and mode in spec.modes)
    )


def endpoint_capability(spec: GarminResourceSpec, *, http_status: int | None = None, empty: bool = False, enabled: bool = True, adapter_has_method: bool = True) -> str:
    """Map a catalog-described result to its only permitted semantic state."""
    if spec.disposition == "ignored":
        return "ignored_with_reason"
    if not adapter_has_method or spec.method is None:
        return "not_supported"
    if http_status == 404:
        return spec.allowed_404_state
    if http_status == 403:
        return "forbidden"
    if not enabled:
        return "not_enabled"
    if empty:
        return spec.empty_state
    return "supported"


def coverage_plan(mode: Mode) -> tuple[tuple[str, str, bool], ...]:
    """Stable audit-friendly list of resource, scope and cursor eligibility."""
    return tuple((s.resource_kind, s.scope, s.cursor_eligible) for s in specs_for_mode(mode))


def health_call_arguments(spec: GarminResourceSpec, local_date: str) -> tuple[tuple[object, ...], dict[str, object]]:
    """Translate a reviewed health spec into the pinned adapter call shape.

    The transport receives one local date today; range endpoints use that date
    as a one-day range until the later range planner batches them.  Keyword-only
    lactate-threshold arguments are intentionally represented here rather than
    improvised by a fetch loop.
    """
    if spec.scope == "account":
        return (), {}
    if spec.argument_shape == ("local_date",):
        return (local_date,), {}
    if spec.argument_shape == ("start_date", "end_date"):
        return (local_date, local_date), {}
    if spec.resource_kind == "lactate_threshold":
        return (), {"latest": False, "start_date": local_date, "end_date": local_date, "aggregation": "daily"}
    if spec.resource_kind == "running_tolerance":
        return (local_date, local_date), {"aggregation": "weekly"}
    if spec.resource_kind == "race_predictions":
        return (local_date, local_date), {}
    raise ValueError(f"unsupported_health_call_shape:{spec.resource_kind}")


def catalog_change_audit(previous_version: str, current_version: str = CATALOG_VERSION) -> dict[str, str | bool]:
    """A small durable audit payload for a caller that observes catalog change."""
    return {"previous_version": previous_version, "current_version": current_version, "coverage_audit_required": previous_version != current_version}


def catalog_lint(*, adapter_methods: set[str] | None = None) -> list[str]:
    """Return errors rather than raising, so release checks can show all faults."""
    errors: list[str] = []
    seen_methods: set[tuple[str, tuple[str, ...], str | None]] = set()
    for key, spec in RESOURCE_CATALOG.items():
        if key != spec.resource_kind:
            errors.append(f"key_mismatch:{key}")
        if spec.disposition == "ignored":
            if spec.method is not None or not spec.ignored_with_reason:
                errors.append(f"ignored_semantics:{key}")
            continue
        if not spec.method or spec.ignored_with_reason:
            errors.append(f"request_semantics:{key}")
        if not spec.projection_targets:
            errors.append(f"projection_missing:{key}")
        if not spec.source_role:
            errors.append(f"source_role_missing:{key}")
        if spec.raw_kind == "fit" and not spec.parser_version:
            errors.append(f"fit_parser_missing:{key}")
        if adapter_methods is not None and spec.method not in adapter_methods:
            errors.append(f"adapter_method_missing:{key}:{spec.method}")
        semantic_key = (spec.method or "", spec.argument_shape, spec.source_role)
        if semantic_key in seen_methods:
            errors.append(f"duplicate_request_semantics:{key}")
        seen_methods.add(semantic_key)
    return errors
