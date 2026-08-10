"""Offline acceptance tests for L2-06's reviewed resource catalog."""

from __future__ import annotations

import inspect
from pathlib import Path

from garminconnect import Garmin

from trainlab.garmin_catalog import (
    ADAPTER_VERSION,
    CATALOG_VERSION,
    EXTRA_ROLES,
    HEALTH_RESOURCES,
    RESOURCE_CATALOG,
    catalog_change_audit,
    catalog_lint,
    coverage_plan,
    endpoint_capability,
    health_call_arguments,
    specs_for_mode,
)
from trainlab.garmin_client import GarminConnectTransport, TokenStore


def _adapter_methods() -> set[str]:
    return {name for name in dir(Garmin) if callable(getattr(Garmin, name))}


def test_catalog_is_versioned_complete_and_lints_against_pinned_client() -> None:
    assert CATALOG_VERSION == "garmin-v4"
    assert ADAPTER_VERSION == "garminconnect-0.3.9"
    assert not catalog_lint(adapter_methods=_adapter_methods())

    # This deliberately lists every §8.1 family, not merely endpoints that a
    # particular account happens to expose.
    expected = {
        "user_profile",
        "user_profile_settings",
        "devices",
        "primary_device",
        "device_settings",
        "device_last_used",
        "personal_records",
        "user_summary",
        "steps",
        "floors",
        "heart_rates",
        "rhr",
        "hydration",
        "respiration",
        "spo2",
        "intensity_minutes",
        "stress",
        "all_day_events",
        "sleep",
        "lifestyle",
        "hrv",
        "body_battery",
        "body_battery_events",
        "body_composition",
        "weigh_ins",
        "blood_pressure",
        "training_readiness",
        "max_metrics",
        "lactate_threshold",
        "training_status",
        "running_tolerance",
        "endurance_score",
        "hill_score",
        "race_predictions",
        "fitness_age",
        "cycling_ftp",
        "menstrual_day",
        "menstrual",
        "pregnancy",
        "nutrition_food_log",
        "nutrition_meals",
        "nutrition_settings",
        "activity_inventory",
        "activity_summary",
        "activity_fit",
        "activity_details_fallback",
        "activity_splits",
        "activity_typed_splits",
        "activity_split_summaries",
        "activity_exercise_sets",
        "activity_hr_zones",
        "activity_power_zones",
        "activity_weather",
        "activity_gear",
    }
    assert expected <= RESOURCE_CATALOG.keys()
    for kind in expected:
        spec = RESOURCE_CATALOG[kind]
        assert spec.adapter_version == ADAPTER_VERSION
        assert spec.source_role
        assert spec.projection_targets
        assert spec.disposition in {"required", "conditional"}


def test_catalog_methods_and_argument_shapes_are_staticly_compatible() -> None:
    """Bind signatures only: no Garmin instance, login or provider request."""
    for spec in RESOURCE_CATALOG.values():
        if not spec.requestable:
            continue
        method = getattr(Garmin, spec.method or "")
        signature = inspect.signature(method)
        if (
            spec.scope in {"daily", "range", "account"}
            and spec.resource_kind != "device_settings"
        ):
            args, kwargs = health_call_arguments(spec, "2026-07-22")
            signature.bind(None, *args, **kwargs)
            continue
        values = {
            "offset": 0,
            "limit": 100,
            "activity_id": "7",
            "ORIGINAL": Garmin.ActivityDownloadFormat.ORIGINAL,
            "maxchart": 2000,
            "maxpoly": 4000,
            "device_id": "device-1",
        }
        args = [values[token] for token in spec.argument_shape]
        signature.bind(None, *args)


def test_ignored_aliases_and_exclusions_never_plan_duplicate_requests() -> None:
    reasons = {
        "get_stats",
        "get_stats_and_body",
        "get_stress_data",
        "get_morning_training_readiness",
        "get_calories_daily",
        "get_functional_threshold_power_range",
        "get_golf_club_stats",
        "get_golf_user_stats",
        "get_heart_rate_zones",
        "get_hrv_data_range",
        "get_max_metrics_range",
        "get_power_zones",
        "get_power_zones_for_sport",
        "get_rhr_daily",
        "get_sleep_daily",
        "weekly_steps",
        "weekly_stress",
        "weekly_intensity_minutes",
        "progress_summary",
        "last_activity",
        "activities_for_date",
        "badges",
        "challenges",
        "social",
        "goals",
        "workout_templates",
        "scheduled_workouts",
        "training_plans",
        "activity_upload_edit_delete",
        "golf_community",
        "device_alarms",
        "device_solar",
    }
    assert reasons <= RESOURCE_CATALOG.keys()
    assert all(RESOURCE_CATALOG[name].ignored_with_reason for name in reasons)
    assert not {name for name in reasons if RESOURCE_CATALOG[name].requestable}
    requested_methods = [spec.method for spec in specs_for_mode("full")]
    assert len(requested_methods) == len(set(requested_methods))


def test_mode_plans_cursor_semantics_and_field_drift_capability_are_deterministic() -> (
    None
):
    full = {kind for kind, _, _ in coverage_plan("full")}
    incremental = {kind for kind, _, _ in coverage_plan("incremental")}
    snapshot = {kind for kind, _, _ in coverage_plan("snapshot")}
    assert set(HEALTH_RESOURCES) <= full <= incremental | full
    assert "activity_inventory" in snapshot and "activity_fit" in snapshot
    assert RESOURCE_CATALOG["user_summary"].cursor_eligible
    assert not RESOURCE_CATALOG["activity_inventory"].cursor_eligible
    # Unknown JSON fields are raw/source-field-catalog data, not a reason to
    # reinterpret absence; optional capabilities retain their explicit state.
    assert (
        endpoint_capability(RESOURCE_CATALOG["menstrual"], empty=True) == "not_enabled"
    )
    assert (
        endpoint_capability(RESOURCE_CATALOG["blood_pressure"], http_status=404)
        == "not_available"
    )
    assert (
        endpoint_capability(RESOURCE_CATALOG["activity_fit"], adapter_has_method=False)
        == "not_supported"
    )
    assert endpoint_capability(RESOURCE_CATALOG["get_stats"]) == "ignored_with_reason"


def test_catalog_change_requires_coverage_audit_and_extra_roles_are_catalog_derived() -> (
    None
):
    assert catalog_change_audit(CATALOG_VERSION)["coverage_audit_required"] is False
    audit = catalog_change_audit("garmin-v1")
    assert audit == {
        "previous_version": "garmin-v1",
        "current_version": CATALOG_VERSION,
        "coverage_audit_required": True,
    }
    assert EXTRA_ROLES == (
        "splits_json",
        "typed_splits_json",
        "split_summaries_json",
        "exercise_sets_json",
        "hr_zones_json",
        "power_zones_json",
        "weather_json",
        "gear_json",
    )


def test_every_pinned_get_method_is_planned_or_has_an_explicit_ignore_reason() -> None:
    """Prevent silent 0.3.9 endpoint drift or accidental duplicate fetches."""
    methods = {
        name
        for name in dir(Garmin)
        if name.startswith("get_") and callable(getattr(Garmin, name))
    }
    planned = {spec.method for spec in RESOURCE_CATALOG.values() if spec.requestable}
    ignored = {
        name
        for name, spec in RESOURCE_CATALOG.items()
        if spec.disposition == "ignored" and spec.ignored_with_reason
    }
    assert methods <= planned | ignored


def test_transport_uses_catalog_reviewed_health_shapes_with_fake_client(
    tmp_path: Path,
) -> None:
    class Client:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
            self.cs = self.Session()
            self._api_session = self.Session()

        class Session:
            def request(self, *args, **kwargs):
                return object()

        def get_body_composition(self, start: str, end: str):
            self.calls.append(("body", (start, end), {}))
            return {"ok": True}

        def get_lactate_threshold(
            self, *, latest: bool, start_date: str, end_date: str, aggregation: str
        ):
            self.calls.append(
                (
                    "lactate",
                    (),
                    {
                        "latest": latest,
                        "start_date": start_date,
                        "end_date": end_date,
                        "aggregation": aggregation,
                    },
                )
            )
            return {"ok": True}

        def get_cycling_ftp(self):
            self.calls.append(("ftp", (), {}))
            return {"ok": True}

    client = Client()
    transport = GarminConnectTransport(
        None, None, TokenStore(tmp_path / "tokens"), client=client
    )
    assert transport.fetch_health("body_composition", "2026-07-22") == {"ok": True}
    assert transport.fetch_health("lactate_threshold", "2026-07-22") == {"ok": True}
    assert transport.fetch_health("cycling_ftp", "2026-07-22") == {"ok": True}
    assert client.calls == [
        ("body", ("2026-07-22", "2026-07-22"), {}),
        (
            "lactate",
            (),
            {
                "latest": False,
                "start_date": "2026-07-22",
                "end_date": "2026-07-22",
                "aggregation": "daily",
            },
        ),
        ("ftp", (), {}),
    ]


def test_transport_uses_reviewed_account_and_per_device_shapes(tmp_path: Path) -> None:
    class Client:
        class Session:
            def request(self, *args, **kwargs):
                return object()

        def __init__(self) -> None:
            self.cs, self._api_session, self.calls = self.Session(), self.Session(), []

        def get_primary_training_device(self):
            self.calls.append(("primary", ()))
            return {"deviceId": "opaque"}

        def get_device_settings(self, device_id: str):
            self.calls.append(("settings", (device_id,)))
            return {"softwareVersion": "1"}

        def get_device_last_used(self):
            self.calls.append(("last", ()))
            return {"deviceId": "opaque"}

        def get_personal_record(self):
            self.calls.append(("records", ()))
            return {"vo2Max": 42}

        def get_cycling_ftp(self):
            self.calls.append(("ftp", ()))
            return {"ftp": 200}

        def get_pregnancy_summary(self):
            self.calls.append(("pregnancy", ()))
            return {"pregnancyWeek": 12}

    client = Client()
    transport = GarminConnectTransport(
        None, None, TokenStore(tmp_path / "tokens"), client=client
    )
    assert transport.fetch_account("primary_device") == {"deviceId": "opaque"}
    assert transport.fetch_account("device_settings", "opaque") == {
        "softwareVersion": "1"
    }
    assert transport.fetch_account("device_last_used") == {"deviceId": "opaque"}
    assert transport.fetch_account("personal_records") == {"vo2Max": 42}
    assert transport.fetch_account("cycling_ftp") == {"ftp": 200}
    assert transport.fetch_account("pregnancy") == {"pregnancyWeek": 12}
    assert client.calls == [
        ("primary", ()),
        ("settings", ("opaque",)),
        ("last", ()),
        ("records", ()),
        ("ftp", ()),
        ("pregnancy", ()),
    ]


def test_transport_uses_bounded_range_signatures_without_daily_fanout(
    tmp_path: Path,
) -> None:
    class Client:
        class Session:
            def request(self, *args, **kwargs):
                return object()

        def __init__(self):
            self.cs, self._api_session, self.calls = self.Session(), self.Session(), []

        def get_lactate_threshold(
            self, *, latest=True, start_date=None, end_date=None, aggregation="daily"
        ):
            self.calls.append(("lactate", latest, start_date, end_date, aggregation))
            return []

        def get_menstrual_calendar_data(self, start: str, end: str):
            self.calls.append(("menstrual", start, end))
            return []

    client = Client()
    transport = GarminConnectTransport(
        None, None, TokenStore(tmp_path / "tokens"), client=client
    )
    assert transport.fetch_range("lactate_threshold", "2026-04-01", "2026-04-14") == []
    assert transport.fetch_range("menstrual", "2026-04-01", "2026-04-14") == []
    assert client.calls == [
        ("lactate", False, "2026-04-01", "2026-04-14", "daily"),
        ("menstrual", "2026-04-01", "2026-04-14"),
    ]


def test_transport_uses_pinned_daily_signatures_for_race_and_endurance(
    tmp_path: Path,
) -> None:
    class Client:
        class Session:
            def request(self, *args, **kwargs):
                return object()

        def __init__(self):
            self.cs, self._api_session, self.calls = self.Session(), self.Session(), []

        def get_race_predictions(self, start: str, end: str, _type: str):
            self.calls.append(("race", start, end, _type))
            return []

        def get_endurance_score(self, start: str, end: str | None = None):
            self.calls.append(("endurance", start, end))
            return {}

    client = Client()
    transport = GarminConnectTransport(
        None, None, TokenStore(tmp_path / "tokens"), client=client
    )
    assert transport.fetch_range("race_predictions", "2026-04-15", "2026-04-15") == []
    assert transport.fetch_range("endurance_score", "2026-04-15", "2026-04-15") == {}
    assert client.calls == [
        ("race", "2026-04-15", "2026-04-15", "daily"),
        ("endurance", "2026-04-15", None),
    ]
