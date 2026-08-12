from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from trainlab.garmin import GarminCollectionTool, GarminConfig, SyncReceipt, SyncRequest
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


def test_explicit_repair_accepts_catalogued_excluded_health_resource(
    tmp_path: Path,
) -> None:
    tool = GarminCollectionTool(
        GarminConfig(
            database_path=tmp_path / "foundation.db",
            raw_root=tmp_path / "raw",
            state_root=tmp_path / "state",
            history_start_date="2026-01-01",
        ),
        clock=lambda: datetime(2026, 8, 3),
    )

    tool._validate(SyncRequest(mode="repair", resource_kinds=("user_summary",)))

    assert "user_summary" not in COLLECTED_HEALTH_RESOURCES
    with pytest.raises(ValueError, match="resource_kind_not_allowlisted"):
        tool._validate(
            SyncRequest(
                mode="incremental",
                through_local_date="2026-08-02",
                resource_kinds=("user_summary",),
            )
        )


@pytest.mark.parametrize(
    (
        "mode",
        "request_args",
        "complete_through",
        "fallback_used",
        "expected_coverage",
    ),
    (
        (
            "incremental",
            {"through_local_date": "2026-08-02"},
            "2026-08-02",
            False,
            "complete",
        ),
        (
            "incremental",
            {"through_local_date": "2026-08-02"},
            "2026-08-01",
            False,
            "partial",
        ),
        (
            "incremental",
            {"through_local_date": "2026-08-02"},
            "2026-08-02",
            True,
            "partial",
        ),
        (
            "snapshot",
            {"snapshot_local_date": "2026-08-03"},
            "2026-08-03",
            False,
            "partial",
        ),
    ),
)
def test_terminal_replay_normalizes_only_completed_collection_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    request_args: dict[str, object],
    complete_through: str,
    fallback_used: bool,
    expected_coverage: str,
) -> None:
    tool = GarminCollectionTool(
        GarminConfig(
            database_path=tmp_path / "foundation.db",
            raw_root=tmp_path / "raw",
            state_root=tmp_path / "state",
            history_start_date="2026-01-01",
        ),
        clock=lambda: datetime(2026, 8, 3),
    )

    class Connection:
        def close(self) -> None:
            return None

        def execute(self, *_args):
            return type(
                "Result", (), {"fetchone": lambda _: (1,) if fallback_used else None}
            )()

    receipt = SyncReceipt(
        mode=mode,
        status="partial",
        coverage_state="partial",
        effective_range={
            "from": "2026-08-01",
            "through": complete_through if mode == "snapshot" else "2026-08-02",
        },
    )
    receipt.complete_through_by_resource = {
        resource: complete_through for resource in COLLECTED_HEALTH_RESOURCES
    }
    tool._normalize_terminal_replay_coverage(
        Connection(),
        1,
        SyncRequest(mode=mode, invocation_id="terminal", **request_args),
        receipt,
    )

    assert receipt.status == "partial"
    assert receipt.coverage_state == expected_coverage
