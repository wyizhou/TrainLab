"""Offline acceptance tests for L2-08 base daily health canonical projection."""
from __future__ import annotations

import copy
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.garmin import GarminCollectionTool, GarminConfig, GarminError, SyncRequest
from trainlab.garmin_catalog import RESOURCE_CATALOG


BASE_RESOURCES = (
    "user_summary", "steps", "floors", "heart_rates", "rhr", "hydration", "respiration",
    "spo2", "intensity_minutes", "stress", "all_day_events", "sleep", "lifestyle", "hrv",
    "body_battery", "body_battery_events", "body_composition", "weigh_ins", "blood_pressure",
)


class HealthFixtureTransport:
    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = payloads
        self.errors: dict[str, GarminError] = {}
        self.calls: list[str] = []

    def login(self) -> None: self.calls.append("login")
    def identity(self) -> str: return "fixture-account"
    def fetch_health(self, resource_kind: str, local_date: str):
        self.calls.append(f"health:{resource_kind}")
        if resource_kind in self.errors: raise self.errors[resource_kind]
        return copy.deepcopy(self.payloads.get(resource_kind, []))
    def list_activities(self, start: str | None, through: str | None): return []
    def activity_summary(self, activity_id: str): raise AssertionError("activity not expected")
    def activity_original(self, activity_id: str): raise AssertionError("activity not expected")
    def activity_extra(self, activity_id: str, role: str): raise AssertionError("activity not expected")


def _fixture_payloads() -> dict[str, object]:
    return json.loads((Path(__file__).parent / "fixtures" / "garmin_health_l2_08.json").read_text(encoding="utf-8"))


def _nested_fixture_payloads() -> dict[str, object]:
    """Synthetic shapes matching reviewed Garmin Connect endpoint contracts.

    The pinned 0.3.6 ``typed.BodyBatteryEntry`` contract documents
    ``bodyBatteryValuesArray`` as ``[[timestamp, level], ...]``.  For SpO₂,
    the selected Taxuspt Garmin consumer reads Connect's exact
    ``spO2HourlyAverages`` array spelling.  The fixture therefore exercises
    raw provider structures rather than an internal flattened representation.
    """
    return json.loads((Path(__file__).parent / "fixtures" / "garmin_health_nested_l2_08.json").read_text(encoding="utf-8"))


def _setup(tmp_path: Path):
    root = tmp_path / "data"
    foundation = FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state/receipt.json", root / "state/locks/foundation.lock")
    FoundationTool(foundation).execute(FoundationRequest("init", "fixture", "2026-01-01T00:00:00Z"))
    config = GarminConfig(foundation.database_path, foundation.raw_root, foundation.state_root, "2026-04-15", request_min_interval_ms=0)
    transport = HealthFixtureTransport(_fixture_payloads())
    tool = GarminCollectionTool(config, transport, sleep=lambda _: None, clock=lambda: datetime(2026, 4, 17), monotonic=lambda: 1000.0)
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    return config, tool, transport


def _repair(tool: GarminCollectionTool, resource: str, invocation: str):
    return tool.execute(SyncRequest("repair", through_local_date="2026-04-15", resource_kinds=(resource,), repair_strategy="refetch", invocation_id=invocation))


def test_fixture_is_synthetic_and_every_base_spec_has_real_catalog_mapping() -> None:
    text = (Path(__file__).parent / "fixtures" / "garmin_health_l2_08.json").read_text(encoding="utf-8")
    assert not re.search(r"(?i)(@|bearer\s|password|token\s*[:=])", text)
    payloads = _fixture_payloads()
    assert set(BASE_RESOURCES) == set(payloads)
    for resource in BASE_RESOURCES:
        spec = RESOURCE_CATALOG[resource]
        assert spec.requestable and spec.method and spec.scope in {"daily", "range"}


def test_all_base_resources_share_raw_revision_projection_coverage_pipeline(tmp_path: Path) -> None:
    config, tool, _ = _setup(tmp_path)
    for index, resource in enumerate(BASE_RESOURCES):
        receipt = _repair(tool, resource, f"base-{index}")
        assert receipt.status == "succeeded", resource
    with sqlite3.connect(config.database_path) as conn:
        coverage = {row[0]: row[1] for row in conn.execute("SELECT resource_kind,availability_state FROM resource_coverage WHERE provider='garmin'")}
        assert {resource: "fetched" for resource in BASE_RESOURCES}.items() <= coverage.items()
        assert conn.execute("SELECT count(*) FROM raw_objects WHERE provider='garmin' AND media_type='application/json'").fetchone()[0] >= len(BASE_RESOURCES)
        assert conn.execute("SELECT count(*) FROM source_revisions WHERE provider='garmin' AND is_current=1").fetchone()[0] >= len(BASE_RESOURCES)
        assert conn.execute("SELECT count(*) FROM daily_health WHERE is_current=1").fetchone()[0] == 1
        values = json.loads(conn.execute("SELECT values_json FROM daily_health WHERE is_current=1").fetchone()[0])
        assert values == {
            "garmin.daily.hydration_ml": 0.0,
            "garmin.daily.moderate_intensity_minutes": 20.0,
            "garmin.daily.resting_heart_rate_bpm": 51.0,
            "garmin.daily.steps": 1200.0,
        }
        assert conn.execute("SELECT count(*) FROM health_samples WHERE metric_key='garmin.steps.count' AND value_number=0").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM health_samples WHERE metric_key LIKE 'garmin.hydration.%'").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM physiology_records WHERE record_type IN ('all_day_events','lifestyle','body_battery_events')").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM body_measurements").fetchone()[0] == 3


def test_sleep_cross_midnight_nap_stage_bounds_and_singapore_sample_day(tmp_path: Path) -> None:
    config, tool, _ = _setup(tmp_path)
    assert _repair(tool, "sleep", "sleep").status == "succeeded"
    assert _repair(tool, "heart_rates", "heart").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        sessions = conn.execute("SELECT session_type,start_time_utc,end_time_utc FROM sleep_sessions ORDER BY id").fetchall()
        assert sessions == [("main_sleep", "2026-04-14T15:30:00Z", "2026-04-15T00:30:00Z"), ("nap", "2026-04-15T05:00:00Z", "2026-04-15T05:30:00Z")]
        assert conn.execute("SELECT count(*) FROM sleep_stages").fetchone()[0] == 3
        assert conn.execute("SELECT local_date FROM health_samples WHERE metric_key='garmin.heart_rate.bpm'").fetchone()[0] == "2026-04-15"


def test_noop_revision_change_field_drift_and_failed_sleep_project_are_atomic(tmp_path: Path, monkeypatch) -> None:
    config, tool, transport = _setup(tmp_path)
    assert _repair(tool, "user_summary", "summary-one").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        first_count = conn.execute("SELECT count(*) FROM source_revisions WHERE resource_kind='user_summary'").fetchone()[0]
    assert _repair(tool, "user_summary", "summary-repeat").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM source_revisions WHERE resource_kind='user_summary'").fetchone()[0] == first_count
        assert conn.execute("SELECT count(*) FROM source_field_catalog WHERE resource_kind='user_summary' AND field_path='/future/series/*/metric'").fetchone()[0] == 1
    transport.payloads["user_summary"]["steps"] = 1300
    assert _repair(tool, "user_summary", "summary-change").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM source_revisions WHERE resource_kind='user_summary'").fetchone()[0] == first_count + 1
        assert conn.execute("SELECT count(*) FROM source_revisions WHERE resource_kind='user_summary' AND is_current=1").fetchone()[0] == 1

    assert _repair(tool, "sleep", "sleep-good").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        old_revision = conn.execute("SELECT id FROM source_revisions WHERE resource_kind='sleep' AND is_current=1").fetchone()[0]
        old_sessions = conn.execute("SELECT count(*) FROM sleep_sessions").fetchone()[0]
    transport.payloads["sleep"]["sessions"][0]["stages"][0]["end_time_utc"] = "2026-04-15T03:00:00Z"
    receipt = _repair(tool, "sleep", "sleep-fail")
    assert receipt.status == "partial" and not any("sessions" in error.get("summary", "") for error in receipt.errors)
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT id FROM source_revisions WHERE resource_kind='sleep' AND is_current=1").fetchone()[0] == old_revision
        assert conn.execute("SELECT count(*) FROM sleep_sessions").fetchone()[0] == old_sessions
        assert conn.execute("SELECT count(*) FROM raw_objects WHERE resource_kind='sleep'").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM garmin_sync_gaps WHERE resource_kind='sleep' AND reason_code='parse_or_project_failed' AND status='open'").fetchone()[0] == 1


def test_empty_capability_states_and_snapshot_partial_do_not_create_zero_or_cursor(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.payloads["floors"] = []
    transport.payloads["hydration"] = {"availability_state": "not_enabled"}
    transport.errors["stress"] = GarminError("not_supported", http_status=404)
    transport.errors["heart_rates"] = GarminError("denied", http_status=403)
    assert _repair(tool, "floors", "empty").status == "succeeded"
    assert _repair(tool, "hydration", "disabled").status == "succeeded"
    assert _repair(tool, "stress", "unsupported").status == "succeeded"
    assert _repair(tool, "heart_rates", "forbidden").status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        coverage = dict(conn.execute("SELECT resource_kind,availability_state FROM resource_coverage WHERE provider='garmin'"))
        assert {"floors": "empty", "hydration": "not_enabled", "stress": "not_supported", "heart_rates": "forbidden"}.items() <= coverage.items()
        states = dict(conn.execute("SELECT resource_kind,capability_state FROM garmin_resource_capabilities"))
        assert states["hydration"] == "not_enabled" and states["stress"] == "not_supported" and states["heart_rates"] == "forbidden"
        assert conn.execute("SELECT count(*) FROM health_samples WHERE metric_key LIKE 'garmin.hydration.%'").fetchone()[0] == 0

    # Snapshot accepts the same raw pipeline but its coverage remains partial
    # and no completed-day cursor is advanced.
    snapshot_config, snapshot_tool, _ = _setup(tmp_path / "snapshot")
    snapshot = snapshot_tool.execute(SyncRequest("snapshot", snapshot_local_date="2026-04-15", invocation_id="snapshot-base"))
    assert snapshot.status == "succeeded" and snapshot.coverage_state == "partial"
    with sqlite3.connect(snapshot_config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM resource_coverage WHERE resource_kind='user_summary' AND availability_state='partial'").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM garmin_sync_cursors").fetchone()[0] == 0


def test_nested_connect_time_series_keep_each_sample_timestamp_and_local_day(tmp_path: Path) -> None:
    """Nested provider arrays/maps must not be flattened at the repair-day fallback."""
    config, tool, transport = _setup(tmp_path)
    nested = _nested_fixture_payloads()
    for resource in ("heart_rates", "stress", "respiration", "body_battery", "spo2", "body_composition", "blood_pressure"):
        transport.payloads[resource] = nested[resource]
        assert _repair(tool, resource, f"nested-{resource}").status == "succeeded"

    with sqlite3.connect(config.database_path) as conn:
        expected = {
            "garmin.heart_rate.bpm": [("2026-04-15T00:00:00Z", "2026-04-15", 59.0), ("2026-04-15T01:00:00Z", "2026-04-15", 62.0)],
            "garmin.stress.score": [("2026-04-15T00:00:00Z", "2026-04-15", 21.0), ("2026-04-15T02:00:00Z", "2026-04-15", 34.0)],
            "garmin.respiration.breaths_per_minute": [("2026-04-15T01:00:00Z", "2026-04-15", 13.2), ("2026-04-15T03:00:00Z", "2026-04-15", 14.1)],
            "garmin.body_battery.score": [("2026-04-15T00:00:00Z", "2026-04-15", 66.0), ("2026-04-15T03:00:00Z", "2026-04-15", 61.0)],
            "garmin.spo2.percent": [("2026-04-15T00:00:00Z", "2026-04-15", 97.0), ("2026-04-15T02:00:00Z", "2026-04-15", 98.0)],
        }
        for metric, rows in expected.items():
            actual = conn.execute(
                "SELECT observed_at_utc,local_date,value_number FROM health_samples WHERE metric_key=? ORDER BY observed_at_utc",
                (metric,),
            ).fetchall()
            assert actual == rows
        body_times = conn.execute(
            "SELECT observed_at_utc,local_date FROM body_measurements ORDER BY observed_at_utc"
        ).fetchall()
        assert body_times == [
            ("2026-04-15T00:00:00Z", "2026-04-15"),
            ("2026-04-15T01:00:00Z", "2026-04-15"),
            ("2026-04-15T03:00:00Z", "2026-04-15"),
            ("2026-04-15T03:00:00Z", "2026-04-15"),
        ]
        bp_records = conn.execute(
            "SELECT effective_at_utc,local_date FROM physiology_records WHERE record_type='blood_pressure' ORDER BY effective_at_utc"
        ).fetchall()
        assert bp_records == [
            ("2026-04-15T01:00:00Z", "2026-04-15"),
            ("2026-04-15T03:00:00Z", "2026-04-15"),
        ]
        # High-frequency arrays and measurement wrapper lists have dedicated
        # canonical tables.  They must never reappear as numbered pseudo
        # metrics in physiology_metrics.
        pseudo_metrics = conn.execute(
            "SELECT metric_key FROM physiology_metrics WHERE metric_key IN (?,?,?,?,?) OR metric_key GLOB '*_[0-9]*'",
            ("heartRateValues", "stressValuesArray", "respirationValuesArray", "spO2HourlyAverages", "bodyBatteryValuesArray"),
        ).fetchall()
        assert pseudo_metrics == []
        bp_metrics = conn.execute(
            "SELECT m.metric_key,m.value_number FROM physiology_metrics m JOIN physiology_records r ON r.id=m.physiology_record_id WHERE r.record_type='blood_pressure' ORDER BY r.effective_at_utc,m.metric_key"
        ).fetchall()
        assert bp_metrics == [("garmin.blood_pressure.diastolic_mmhg", 76.0), ("garmin.blood_pressure.systolic_mmhg", 118.0), ("garmin.blood_pressure.diastolic_mmhg", 77.0), ("garmin.blood_pressure.systolic_mmhg", 119.0)]
        # Future nested fields remain discoverable in the field catalog; they
        # do not cause the provider resource to be discarded.
        assert conn.execute(
            "SELECT count(*) FROM source_field_catalog WHERE resource_kind='heart_rates' AND field_path='/futureHeartRateEnvelope/algorithmVersion'"
        ).fetchone()[0] == 1


def test_respiration_accepts_only_the_closed_interval_next_midnight_boundary(
    tmp_path: Path,
) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.payloads["respiration"] = {
        "calendarDate": "2026-04-15",
        "respirationValuesArray": [
            [1776268799000, 13.2],
            [1776268800000, 13.3],
        ],
    }
    assert _repair(tool, "respiration", "respiration-midnight-boundary").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            """SELECT observed_at_utc,local_date FROM health_samples
               WHERE metric_key='garmin.respiration.breaths_per_minute'
               ORDER BY observed_at_utc"""
        ).fetchall() == [
            ("2026-04-15T15:59:59Z", "2026-04-15"),
            ("2026-04-15T16:00:00Z", "2026-04-16"),
        ]

    transport.payloads["respiration"]["respirationValuesArray"] = [
        [1776268801000, 13.4],
    ]
    receipt = _repair(tool, "respiration", "respiration-after-midnight")
    assert receipt.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            """SELECT count(*) FROM garmin_sync_gaps
               WHERE resource_kind='respiration'
                 AND reason_code='parse_or_project_failed'
                 AND status='open'"""
        ).fetchone()[0] == 1


def test_sleep_null_daily_dto_is_fetched_zero_but_one_sided_time_still_fails(
    tmp_path: Path,
) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.payloads["sleep"] = {
        "dailySleepDTO": {
            "calendarDate": "2026-04-15",
            "sleepStartTimestampGMT": None,
            "sleepEndTimestampGMT": None,
        }
    }
    receipt = _repair(tool, "sleep", "sleep-zero-session")
    assert receipt.status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM sleep_sessions").fetchone()[0] == 0
        assert conn.execute(
            """SELECT availability_state,record_count FROM resource_coverage
               WHERE resource_kind='sleep' ORDER BY id DESC LIMIT 1"""
        ).fetchone() == ("empty", 0)

    transport.payloads["sleep"]["dailySleepDTO"]["sleepStartTimestampGMT"] = (
        "2026-04-14T16:00:00Z"
    )
    receipt = _repair(tool, "sleep", "sleep-one-sided-time")
    assert receipt.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            """SELECT count(*) FROM garmin_sync_gaps
               WHERE resource_kind='sleep'
                 AND reason_code='parse_or_project_failed'
                 AND status='open'"""
        ).fetchone()[0] == 1


def test_unchanged_zero_record_snapshot_promotes_to_empty_not_fetched(
    tmp_path: Path,
) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.payloads["sleep"] = {
        "dailySleepDTO": {
            "calendarDate": "2026-04-15",
            "sleepStartTimestampGMT": None,
            "sleepEndTimestampGMT": None,
        }
    }
    assert tool.execute(SyncRequest(
        "snapshot", snapshot_local_date="2026-04-15",
        invocation_id="sleep-zero-snapshot",
    )).status == "succeeded"
    assert _repair(tool, "sleep", "sleep-zero-promotion").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            """SELECT availability_state,record_count FROM resource_coverage
               WHERE resource_kind='sleep' ORDER BY id DESC LIMIT 1"""
        ).fetchone() == ("empty", 0)
        assert conn.execute(
            "SELECT count(*) FROM resource_coverage WHERE resource_kind='sleep'"
        ).fetchone()[0] == 1


def test_sleep_levels_map_parses_string_epochs_and_iso_keys_into_bounded_stages(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.payloads["sleep"] = _nested_fixture_payloads()["sleep"]
    assert _repair(tool, "sleep", "sleep-level-map").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        session = conn.execute("SELECT start_time_utc,end_time_utc FROM sleep_sessions").fetchone()
        assert session == ("2026-04-14T15:00:00Z", "2026-04-14T18:00:00Z")
        stages = conn.execute(
            "SELECT stage_type,start_time_utc,end_time_utc,duration_seconds FROM sleep_stages ORDER BY stage_index"
        ).fetchall()
        # Input map order is deliberately mixed: ISO, millis-string, seconds-string.
        assert stages == [
            ("deep", "2026-04-14T15:00:00Z", "2026-04-14T16:00:00Z", 3600.0),
            ("light", "2026-04-14T16:00:00Z", "2026-04-14T17:00:00Z", 3600.0),
            ("rem", "2026-04-14T17:00:00Z", "2026-04-14T18:00:00Z", 3600.0),
        ]


def test_semantic_empty_tombstone_supersedes_current_and_snapshot_stays_partial(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    assert _repair(tool, "steps", "steps-fetched").status == "succeeded"
    transport.payloads["steps"] = []
    assert _repair(tool, "steps", "steps-empty").status == "succeeded"
    transport.payloads["steps"] = {"availability_state": "not_enabled"}
    assert _repair(tool, "steps", "steps-disabled").status == "succeeded"
    transport.payloads["steps"] = _fixture_payloads()["steps"]
    assert _repair(tool, "steps", "steps-restored").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM source_revisions WHERE resource_kind='steps'").fetchone()[0] == 4
        assert conn.execute("SELECT count(*) FROM source_revisions WHERE resource_kind='steps' AND is_current=1").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM health_samples WHERE metric_key='garmin.steps.count'").fetchone()[0] == 1
        coverage = conn.execute(
            "SELECT availability_state,source_revision_id FROM resource_coverage WHERE resource_kind='steps' ORDER BY id"
        ).fetchall()
        assert [row[0] for row in coverage] == ["fetched", "empty", "not_enabled", "fetched"]
        assert all(row[1] is not None for row in coverage)

    snapshot_config, snapshot_tool, snapshot_transport = _setup(tmp_path / "snapshot-empty")
    snapshot_transport.payloads["steps"] = []
    receipt = snapshot_tool.execute(SyncRequest("snapshot", snapshot_local_date="2026-04-15", invocation_id="snapshot-empty"))
    assert receipt.status == "succeeded" and receipt.coverage_state == "partial"
    with sqlite3.connect(snapshot_config.database_path) as conn:
        row = conn.execute("SELECT availability_state,source_revision_id FROM resource_coverage WHERE resource_kind='steps'").fetchone()
        assert row[0] == "partial" and row[1] is not None
        assert conn.execute("SELECT count(*) FROM garmin_sync_cursors").fetchone()[0] == 0


def test_snapshot_optional_404_and_forbidden_observations_are_always_partial(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.errors["floors"] = GarminError("missing", http_status=404)
    transport.errors["heart_rates"] = GarminError("denied", http_status=403)
    receipt = tool.execute(SyncRequest("snapshot", snapshot_local_date="2026-04-15", invocation_id="snapshot-errors"))
    assert receipt.status == "partial" and receipt.coverage_state == "partial"
    with sqlite3.connect(config.database_path) as conn:
        rows = dict(conn.execute("SELECT resource_kind,availability_state FROM resource_coverage WHERE resource_kind IN ('floors','heart_rates')"))
        assert rows == {"floors": "partial", "heart_rates": "partial"}
        assert conn.execute("SELECT count(*) FROM garmin_sync_cursors").fetchone()[0] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"heartRateValues": [["not-a-timestamp", 60]]},
        {"heartRateValues": [[1776211200000, 60, 999]]},
    ],
)
def test_invalid_high_frequency_time_or_tuple_arity_rolls_back_and_creates_gap(tmp_path: Path, payload: dict[str, object]) -> None:
    config, tool, transport = _setup(tmp_path)
    assert _repair(tool, "heart_rates", "heart-good").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        old = conn.execute("SELECT id FROM source_revisions WHERE resource_kind='heart_rates' AND is_current=1").fetchone()[0]
    transport.payloads["heart_rates"] = payload
    receipt = _repair(tool, "heart_rates", "heart-invalid")
    assert receipt.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT id FROM source_revisions WHERE resource_kind='heart_rates' AND is_current=1").fetchone()[0] == old
        assert conn.execute("SELECT count(*) FROM raw_objects WHERE resource_kind='heart_rates'").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM garmin_sync_gaps WHERE resource_kind='heart_rates' AND reason_code='parse_or_project_failed' AND status='open'").fetchone()[0] == 1


def test_canonical_registry_units_and_catalog_mapping_are_bounded(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.payloads["heart_rates"] = _nested_fixture_payloads()["heart_rates"]
    assert _repair(tool, "heart_rates", "registry-heart").status == "succeeded"
    assert _repair(tool, "user_summary", "registry-summary").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        sample = conn.execute(
            "SELECT metric_key,raw_unit,canonical_unit FROM health_samples WHERE metric_key='garmin.heart_rate.bpm'"
        ).fetchone()
        assert sample == ("garmin.heart_rate.bpm", "bpm", "bpm")
        mapped = conn.execute(
            "SELECT mapping_state,canonical_metric_key FROM source_field_catalog WHERE resource_kind='heart_rates' AND field_path='/heartRateValues/*/*'"
        ).fetchone()
        assert mapped == ("mapped", "garmin.heart_rate.bpm")
        unknown = conn.execute(
            "SELECT mapping_state FROM source_field_catalog WHERE resource_kind='heart_rates' AND field_path='/futureHeartRateEnvelope/algorithmVersion'"
        ).fetchone()
        assert unknown == ("unknown",)
        values = json.loads(conn.execute("SELECT values_json FROM daily_health WHERE is_current=1").fetchone()[0])
        assert values == {"garmin.daily.resting_heart_rate_bpm": 51.0, "garmin.daily.steps": 1200.0}
        assert all(not isinstance(value, (list, dict)) for value in values.values())


def test_date_only_timestamp_is_rejected_for_samples_and_allowed_only_for_day_boundary() -> None:
    with pytest.raises(ValueError, match="date_only_timestamp_not_allowed"):
        GarminCollectionTool._timestamp_utc("2026-04-15", "2026-04-15")
    assert GarminCollectionTool._timestamp_utc(
        "2026-04-15", "2026-04-15", allow_day_boundary=True
    ) == "2026-04-14T16:00:00Z"


def test_snapshot_forbidden_uses_one_partial_coverage_and_no_revision_growth(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.errors["heart_rates"] = GarminError("denied", http_status=403)
    request = lambda invocation: SyncRequest(
        "snapshot", snapshot_local_date="2026-04-15", invocation_id=invocation
    )
    assert tool.execute(request("snapshot-forbidden-one")).status == "partial"
    assert tool.execute(request("snapshot-forbidden-two")).status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM resource_coverage WHERE resource_kind='heart_rates' AND availability_state='partial'"
        ).fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM source_revisions WHERE resource_kind='heart_rates'").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM garmin_sync_cursors").fetchone()[0] == 0


def test_snapshot_parse_and_project_failures_have_partial_coverage_gap_item_and_no_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, tool, transport = _setup(tmp_path)
    # This payload reaches the real series parser and fails only on its date-only
    # timestamp; the source raw object remains outside the failed publisher txn.
    transport.payloads["heart_rates"] = {"heartRateValues": [["2026-04-15", 60]]}
    parsed = tool.execute(SyncRequest(
        "snapshot", snapshot_local_date="2026-04-15", invocation_id="snapshot-parse-failure"
    ))
    assert parsed.status == "partial"

    hit = {"project": False}
    original = tool._project_health
    def fail_project(*args, **kwargs):
        if args[2] == "steps":
            hit["project"] = True
            raise ValueError("fixture projection failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(tool, "_project_health", fail_project)
    transport.payloads["steps"][0]["steps"] = 1201  # force publisher/projector, not snapshot no-op
    projected = tool.execute(SyncRequest(
        "snapshot", snapshot_local_date="2026-04-15", invocation_id="snapshot-project-failure"
    ))
    assert projected.status == "partial" and hit["project"] is True
    monkeypatch.setattr(tool, "_project_health", original)

    with sqlite3.connect(config.database_path) as conn:
        for resource in ("heart_rates", "steps"):
            assert conn.execute(
                "SELECT count(*) FROM resource_coverage WHERE resource_kind=? AND availability_state='partial'", (resource,)
            ).fetchone()[0] == 1
            assert conn.execute(
                "SELECT count(*) FROM garmin_sync_gaps WHERE resource_kind=? AND reason_code='parse_or_project_failed'", (resource,)
            ).fetchone()[0] == 1
            assert conn.execute(
                "SELECT count(*) FROM garmin_sync_items WHERE resource_kind=? AND stage='project' AND status='failed'", (resource,)
            ).fetchone()[0] >= 1
        assert conn.execute("SELECT count(*) FROM garmin_sync_cursors").fetchone()[0] == 0


def test_meaningful_timestampless_sample_is_not_fetched_with_zero_projection(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    assert _repair(tool, "heart_rates", "heart-good-before-missing-time").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        old_revision = conn.execute(
            "SELECT id FROM source_revisions WHERE resource_kind='heart_rates' AND is_current=1"
        ).fetchone()[0]
        old_samples = conn.execute("SELECT count(*) FROM health_samples WHERE metric_key='garmin.heart_rate.bpm'").fetchone()[0]
    transport.payloads["heart_rates"] = [{"heartRate": 61}]
    receipt = _repair(tool, "heart_rates", "heart-missing-time")
    assert receipt.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT id FROM source_revisions WHERE resource_kind='heart_rates' AND is_current=1"
        ).fetchone()[0] == old_revision
        assert conn.execute("SELECT count(*) FROM health_samples WHERE metric_key='garmin.heart_rate.bpm'").fetchone()[0] == old_samples
        assert conn.execute(
            "SELECT status FROM garmin_sync_items WHERE logical_object_key='garmin:health:heart_rates:2026-04-15' AND stage='project' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0] == "failed"
        assert conn.execute(
            "SELECT count(*) FROM garmin_sync_gaps WHERE resource_kind='heart_rates' AND reason_code='parse_or_project_failed'"
        ).fetchone()[0] == 1


def test_live_daily_aliases_and_missing_sensor_points_do_not_drop_resource(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.payloads["steps"] = [{
        "startGMT": "2026-04-14T16:00:00.0",
        "endGMT": "2026-04-14T16:15:00.0",
        "steps": 9,
    }]
    transport.payloads["heart_rates"] = {
        "calendarDate": "2026-04-15",
        "startTimestampGMT": "2026-04-14T16:00:00.0",
        "heartRateValues": [
            ["2026-04-15T00:00:00Z", 61],
            ["2026-04-15T00:02:00Z", None],
        ],
    }
    transport.payloads["hrv"] = {
        "startTimestampGMT": "2026-04-14T15:00:00.0",
        "hrvReadings": [],
        "hrvSummary": {},
    }
    assert _repair(tool, "steps", "live-steps-start-gmt").status == "succeeded"
    assert _repair(tool, "heart_rates", "live-heart-null").status == "succeeded"
    assert _repair(tool, "hrv", "live-hrv-empty-summary").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT local_date,value_number FROM health_samples "
            "WHERE metric_key='garmin.steps.count'"
        ).fetchall() == [("2026-04-15", 9.0)]
        assert conn.execute(
            "SELECT observed_at_utc,value_number FROM health_samples "
            "WHERE metric_key='garmin.heart_rate.bpm'"
        ).fetchall() == [("2026-04-15T00:00:00Z", 61.0)]
        assert conn.execute(
            "SELECT count(*) FROM source_revisions "
            "WHERE resource_kind IN ('steps','heart_rates','hrv') AND is_current=1"
        ).fetchone()[0] == 3


def test_daily_capabilities_record_supported_empty_and_explicit_state_in_configured_region(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.payloads["floors"] = []
    transport.payloads["hydration"] = {"availability_state": "not_enabled"}
    assert _repair(tool, "steps", "capability-daily-fetched").status == "succeeded"
    assert _repair(tool, "floors", "capability-daily-empty").status == "succeeded"
    assert _repair(tool, "hydration", "capability-daily-disabled").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        rows = dict(conn.execute(
            "SELECT resource_kind,capability_state FROM garmin_resource_capabilities "
            "WHERE environment_key='cn'"
        ))
        assert {"steps": "supported", "floors": "supported", "hydration": "not_enabled"}.items() <= rows.items()
        assert conn.execute(
            "SELECT count(*) FROM garmin_resource_capabilities WHERE environment_key='default'"
        ).fetchone()[0] == 0


def test_audit_reconciles_legacy_default_and_backfills_completed_coverage_idempotently(tmp_path: Path) -> None:
    config, tool, _transport = _setup(tmp_path)
    conn = tool.repo.connect()
    try:
        subject = tool.repo.subject(conn)
        conn.execute(
            """INSERT INTO garmin_resource_capabilities(
                   subject_id,environment_key,resource_kind,capability_state,
                   reason_code,first_checked_at_utc,last_checked_at_utc,next_probe_at_utc)
               VALUES(?,?,?,?,?,?,?,?)""",
            (subject, "cn", "steps", "not_available", "missing",
             "2026-04-01T00:00:00Z", "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z"),
        )
        conn.execute(
            """INSERT INTO garmin_resource_capabilities(
                   subject_id,environment_key,resource_kind,capability_state,
                   first_checked_at_utc,last_checked_at_utc)
               VALUES(?,?,?,?,?,?)""",
            (subject, "default", "steps", "supported",
             "2026-04-02T00:00:00Z", "2026-04-02T00:00:00Z"),
        )
        conn.execute(
            """INSERT INTO resource_coverage(
                   subject_id,provider,resource_kind,local_date,availability_state,
                   record_count,observed_at_utc)
               VALUES(?,?,?,?,?,?,?)""",
            (subject, "garmin", "floors", "2026-04-15", "fetched", 0,
             "2026-04-03T00:00:00Z"),
        )
    finally:
        conn.close()
    assert tool.execute(SyncRequest("audit", invocation_id="capability-audit")).status in {"succeeded", "partial"}
    assert tool.execute(SyncRequest("audit", invocation_id="capability-audit-repeat")).status in {"succeeded", "partial"}
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT capability_state,next_probe_at_utc,first_checked_at_utc,last_checked_at_utc "
            "FROM garmin_resource_capabilities WHERE environment_key='cn' AND resource_kind='steps'"
        ).fetchone() == ("supported", None, "2026-04-01T00:00:00Z", "2026-04-02T00:00:00Z")
        assert conn.execute(
            "SELECT capability_state FROM garmin_resource_capabilities "
            "WHERE environment_key='cn' AND resource_kind='floors'"
        ).fetchone() == ("supported",)
        assert conn.execute(
            "SELECT count(*) FROM garmin_resource_capabilities WHERE environment_key='default'"
        ).fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM resource_coverage WHERE resource_kind='floors'").fetchone()[0] == 1
        assert conn.execute(
            "SELECT availability_state,record_count,observed_at_utc FROM resource_coverage WHERE resource_kind='floors'"
        ).fetchone() == ("empty", 0, "2026-04-03T00:00:00Z")


def test_zero_record_coverage_reconciliation_is_region_independent(tmp_path: Path) -> None:
    _config, tool, _transport = _setup(tmp_path)
    conn = tool.repo.connect()
    try:
        subject = tool.repo.subject(conn)
        conn.execute(
            """INSERT INTO resource_coverage(
                   subject_id,provider,resource_kind,local_date,availability_state,
                   record_count,observed_at_utc)
               VALUES(?,?,?,?,?,?,?)""",
            (subject, "garmin", "hydration", "2026-04-15", "fetched", 0,
             "2026-04-03T00:00:00Z"),
        )
        tool.repo.reconcile_legacy_capability_environment(conn, subject, "default")
        assert tuple(conn.execute(
            "SELECT availability_state,record_count FROM resource_coverage WHERE resource_kind='hydration'"
        ).fetchone()) == ("empty", 0)
    finally:
        conn.close()
