from __future__ import annotations

from datetime import date

from trainlab.garmin_catalog import (
    COLLECTED_HEALTH_RESOURCES,
    DEFAULT_ACTIVITY_ENRICHMENTS,
    HEALTH_COLLECTION_ALLOWLIST,
)
from trainlab.garmin_modes import INCREMENTAL_LOOKBACK_DAYS, build_collection_mode_plan


def test_default_health_plan_is_the_confirmed_whitelist() -> None:
    assert set(COLLECTED_HEALTH_RESOURCES) == HEALTH_COLLECTION_ALLOWLIST
    assert "steps" not in COLLECTED_HEALTH_RESOURCES
    assert "blood_pressure" not in COLLECTED_HEALTH_RESOURCES
    assert DEFAULT_ACTIVITY_ENRICHMENTS == (("activity_weather", "weather_json"),)


def test_incremental_activity_window_has_fourteen_day_overlap() -> None:
    plan = build_collection_mode_plan(
        mode="incremental",
        today_local=date(2026, 8, 3),
        history_start_date="2026-01-01",
        requested_health_from=None,
        requested_through=None,
        requested_snapshot_date=None,
        health_resources=("sleep",),
        complete_through_by_resource={"sleep": "2026-08-01"},
        lookback_days=INCREMENTAL_LOOKBACK_DAYS,
    )
    assert plan.activity_start.isoformat() == "2026-07-20"
    assert plan.activity_through.isoformat() == "2026-08-02"
