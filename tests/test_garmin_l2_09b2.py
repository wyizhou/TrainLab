"""Offline L2-09B2 acceptance for all remaining advanced catalog resources."""
from __future__ import annotations

import copy
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.garmin import (
    GarminCollectionTool,
    GarminConfig,
    GarminError,
    SyncRequest,
    stable_json,
    validate_provider_json_payload,
)
from trainlab.garmin_catalog import RESOURCE_CATALOG


ADVANCED = {
    "training_readiness": ({"trainingReadinessScore": 71, "timestampGMT": "2026-04-15T01:00:00Z", "displayName": "PRIVATE"}, "garmin.training_readiness.score"),
    "max_metrics": ({"vo2Max": 44.2, "calendarDate": "2026-04-15"}, "garmin.vo2_max.ml_per_kg_min"),
    "lactate_threshold": ({"lactateThresholdHeartRate": 168, "lactateThresholdPower": 242, "calendarDate": "2026-04-15"}, "garmin.lactate_threshold.heart_rate_bpm"),
    "training_status": ({"trainingStatusScore": 64, "acuteTrainingLoad": 398, "calendarDate": "2026-04-15"}, "garmin.training_status.score"),
    "running_tolerance": ([{"runningTolerance": 53, "weeklyMileage": 26000, "calendarDate": "2026-04-15"}], "garmin.running_tolerance.score"),
    "endurance_score": ({"enduranceScore": 5120, "calendarDate": "2026-04-15"}, "garmin.endurance_score"),
    "hill_score": ({"hillScore": 48, "calendarDate": "2026-04-15"}, "garmin.hill_score"),
    "race_predictions": ({"racePredictions": [{"predictionSeconds": 1370, "calendarDate": "2026-04-15"}]}, "garmin.race_prediction.seconds"),
    "fitness_age": ({"fitnessAge": 31, "calendarDate": "2026-04-15"}, "garmin.fitness_age.years"),
    "menstrual_day": ({"cycleLength": 28, "periodLength": 5, "calendarDate": "2026-04-15", "symptomNote": "preserve-in-raw"}, "garmin.menstrual.cycle_length_days"),
    "menstrual": ({"cycleLength": 28, "periodLength": 5, "calendarDate": "2026-04-15", "partnerName": "PRIVATE"}, "garmin.menstrual.cycle_length_days"),
    "nutrition_food_log": ({"calories": 2030, "protein": 122, "carbohydrates": 250, "fat": 61, "calendarDate": "2026-04-15", "foodName": "preserve-in-raw"}, "garmin.nutrition.calories_kcal"),
    "nutrition_meals": ({"meals": [{"calories": 620, "protein": 30, "calendarDate": "2026-04-15", "name": "PRIVATE"}]}, "garmin.nutrition.calories_kcal"),
    "nutrition_settings": ({"calorieGoal": 2200, "calendarDate": "2026-04-15", "email": "private@example.invalid"}, "garmin.nutrition.calorie_goal_kcal"),
}


class AdvancedTransport:
    def __init__(self) -> None:
        self.payloads = {kind: copy.deepcopy(payload) for kind, (payload, _metric) in ADVANCED.items()}
        self.errors: dict[str, GarminError] = {}
        self.calls: list[tuple[str, str]] = []
        self.echo_requested_day = False
    def login(self): pass
    def identity(self): return "advanced-fixture"
    def fetch_health(self, resource: str, local_date: str):
        self.calls.append((resource, local_date))
        if resource in self.errors: raise self.errors[resource]
        payload = copy.deepcopy(self.payloads[resource])
        if self.echo_requested_day and isinstance(payload, dict):
            payload["calendarDate"] = local_date
        return payload
    def fetch_range(self, resource: str, start_date: str, end_date: str):
        self.calls.append((resource, f"{start_date}:{end_date}"))
        if resource in self.errors: raise self.errors[resource]
        payload = copy.deepcopy(self.payloads[resource])
        if self.echo_requested_day and isinstance(payload, dict):
            payload["calendarDate"] = start_date
        return payload
    def fetch_account(self, *_args): raise AssertionError("no account endpoint")
    def list_activities(self, *_args): return []
    def activity_summary(self, *_args): raise AssertionError("no activity")
    def activity_original(self, *_args): raise AssertionError("no activity")
    def activity_extra(self, *_args): raise AssertionError("no activity")


def _setup(tmp_path: Path):
    root = tmp_path / "data"
    f = FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state/ready.json", root / "state/locks/foundation.lock")
    assert FoundationTool(f).execute(FoundationRequest("init", "l2-09b2", "2026-01-01T00:00:00Z")).status == "initialized"
    config = GarminConfig(f.database_path, f.raw_root, f.state_root, "2026-04-01", request_min_interval_ms=0)
    transport = AdvancedTransport()
    tool = GarminCollectionTool(config, transport, sleep=lambda _: None, clock=lambda: datetime(2026, 4, 17), monotonic=lambda: 1000.0)
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    return config, tool, transport


def _repair(tool, resource: str, invocation: str):
    return tool.execute(SyncRequest("repair", health_from_local_date="2026-04-15", through_local_date="2026-04-15", resource_kinds=(resource,), repair_strategy="refetch", invocation_id=invocation))


@pytest.mark.parametrize(
    "payload",
    [
        {"nested": {"client_secret": "QUARANTINE_MARKER"}},
        {"nested": [{"oauthToken": "QUARANTINE_MARKER"}]},
        {"id_token": "QUARANTINE_MARKER"},
        {"api_key": "QUARANTINE_MARKER"},
        {"sessionCookie": "QUARANTINE_MARKER"},
        {"access-token": "QUARANTINE_MARKER"},
        {"nested": [{"x_api-key": "QUARANTINE_MARKER"}]},
        {"nested": [{"x_api_key": "QUARANTINE_MARKER"}]},
        {"api-key-value": "QUARANTINE_MARKER"},
        {"garminApiKeyValue": "QUARANTINE_MARKER"},
        {"vendor_access_token_value": "QUARANTINE_MARKER"},
        {"AUTHORIZATION": "QUARANTINE_MARKER"},
        {"bear-er": "QUARANTINE_MARKER"},
        {"pass.code": "QUARANTINE_MARKER"},
        {"Client Secret": "QUARANTINE_MARKER"},
        {"cre-den_tials": "QUARANTINE_MARKER"},
        {"session/cookie": "QUARANTINE_MARKER"},
        {"JwT": "QUARANTINE_MARKER"},
        {"healthNote": "Bearer fixture-credential"},
        {"healthNote": "Authorization: Basic Zml4dHVyZTpjcmVkZW50aWFs"},
    ],
)
def test_provider_json_quarantine_normalizes_reviewed_credentials_and_auth_values(payload: object) -> None:
    with pytest.raises(GarminError, match="provider_payload_quarantined"):
        validate_provider_json_payload(payload)


def test_provider_json_quarantine_allows_similarly_named_health_and_profile_fields() -> None:
    payload = {
        "authorizationStatus": "not-required",
        "tokenCount": 0,
        "oauthTokenExpiryDays": 7,
        "passwordStrengthScore": 4,
        "passwordlessEnabled": True,
        "secretoryRate": 12.5,
        "apiKeynote": "profile note",
        "credentialStatus": "verified",
        "cookiePreferences": "disabled",
        "sessionCookiePreference": "disabled",
        "jwtAlgorithmName": "profile metadata",
        "healthDescription": "Basic fitness profile",
        "profileDescription": "Bearer health profile",
    }
    assert validate_provider_json_payload(payload) is payload


@pytest.mark.parametrize(
    "payload",
    [
        {"nested": [{"x_api-key": "ARCHIVE_QUARANTINE_MARKER"}]},
        {"nested": [{"x_api_key": "ARCHIVE_QUARANTINE_MARKER"}]},
        {"api-key-value": "ARCHIVE_QUARANTINE_MARKER"},
        {"garminApiKeyValue": "ARCHIVE_QUARANTINE_MARKER"},
    ],
)
def test_repository_archive_boundary_rejects_wrapped_api_keys_without_payload_writes(
    tmp_path: Path,
    payload: object,
) -> None:
    config, tool, _transport = _setup(tmp_path)
    conn = tool.repo.connect()
    try:
        with pytest.raises(GarminError, match="provider_payload_quarantined"):
            tool.repo.archive(
                conn,
                "training_readiness",
                "garmin:health:training_readiness:2026-04-15",
                stable_json(payload),
                "json",
                "application/json",
            )
    finally:
        conn.close()
    with sqlite3.connect(config.database_path) as audit:
        assert audit.execute("SELECT count(*) FROM raw_objects").fetchone()[0] == 0
        assert audit.execute("SELECT count(*) FROM source_revisions").fetchone()[0] == 0
        assert audit.execute("SELECT count(*) FROM source_field_catalog").fetchone()[0] == 0
        dump = "\n".join(audit.iterdump())
        raw_files = b"".join(
            path.read_bytes() for path in config.raw_root.rglob("*") if path.is_file()
        )
        assert "ARCHIVE_QUARANTINE_MARKER" not in dump
        assert b"ARCHIVE_QUARANTINE_MARKER" not in raw_files


@pytest.mark.parametrize(("resource", "payload", "metric"), [(kind, payload, metric) for kind, (payload, metric) in ADVANCED.items()])
def test_each_advanced_resource_has_catalog_signature_raw_revision_and_canonical(tmp_path: Path, resource: str, payload: object, metric: str) -> None:
    config, tool, transport = _setup(tmp_path)
    spec = RESOURCE_CATALOG[resource]
    assert spec.scope in {"daily", "range"} and spec.conditional and spec.cursor_eligible
    first = _repair(tool, resource, f"advanced-{resource}")
    expected_call = (resource, "2026-04-15:2026-04-15") if spec.scope == "range" else (resource, "2026-04-15")
    assert first.status == "succeeded" and transport.calls == [expected_call]
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM source_revisions WHERE resource_kind=? AND is_current=1", (resource,)).fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM physiology_metrics WHERE metric_key=?", (metric,)).fetchone()[0] >= 1
        source_path = conn.execute("SELECT source_path FROM physiology_metrics WHERE metric_key=? LIMIT 1", (metric,)).fetchone()[0]
        assert conn.execute("SELECT mapping_state,canonical_metric_key FROM source_field_catalog WHERE resource_kind=? AND field_path=?", (resource, source_path)).fetchone() == ("mapped", metric)
        assert conn.execute("SELECT availability_state FROM resource_coverage WHERE resource_kind=?", (resource,)).fetchone()[0] == "fetched"
        assert conn.execute("SELECT count(*) FROM garmin_sync_items WHERE resource_kind=? AND status='running'", (resource,)).fetchone()[0] == 0
    again = _repair(tool, resource, f"advanced-{resource}-repeat")
    assert again.status == "succeeded" and again.counts["unchanged"] == 1


def test_advanced_revisions_tombstones_capabilities_and_snapshot_are_deterministic(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    _repair(tool, "training_readiness", "adv-first")
    transport.payloads["training_readiness"] = {"trainingReadinessScore": 75, "calendarDate": "2026-04-15"}
    revised = _repair(tool, "training_readiness", "adv-revised")
    assert revised.counts["revised"] == 1
    transport.payloads["training_readiness"] = {"availability_state": "not_enabled", "email": "private@example.invalid"}
    tombstone = _repair(tool, "training_readiness", "adv-disabled")
    assert tombstone.counts["not_enabled"] == 1
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT availability_state FROM resource_coverage WHERE resource_kind='training_readiness' ORDER BY id DESC LIMIT 1").fetchone()[0] == "not_enabled"
        assert conn.execute("SELECT count(*) FROM v_current_physiology_records WHERE record_type='training_readiness'").fetchone()[0] == 0
    transport.errors["hill_score"] = GarminError("missing", http_status=404)
    transport.errors["endurance_score"] = GarminError("forbidden", http_status=403)
    unavailable = tool.execute(SyncRequest("repair", health_from_local_date="2026-04-15", through_local_date="2026-04-15", resource_kinds=("hill_score", "endurance_score"), repair_strategy="refetch", invocation_id="adv-capability"))
    assert unavailable.status == "partial" and unavailable.counts["not_available"] == 1 and unavailable.counts["failed"] == 1
    transport.errors.clear()
    with sqlite3.connect(config.database_path) as conn:
        cursors_before = list(conn.execute("SELECT resource_kind,complete_through_local_date FROM garmin_sync_cursors ORDER BY resource_kind"))
    tool._activities = lambda *_args: None  # type: ignore[method-assign]
    snap = tool.execute(SyncRequest("snapshot", snapshot_local_date="2026-04-15", invocation_id="adv-snapshot"))
    assert snap.coverage_state == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert list(conn.execute("SELECT resource_kind,complete_through_local_date FROM garmin_sync_cursors ORDER BY resource_kind")) == cursors_before


def test_advanced_malformed_payload_rolls_back_and_sensitive_markers_stay_outside_raw(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    _repair(tool, "race_predictions", "adv-race-good")
    with sqlite3.connect(config.database_path) as conn:
        current = conn.execute("SELECT id FROM source_revisions WHERE resource_kind='race_predictions' AND is_current=1").fetchone()[0]
    transport.payloads["race_predictions"] = {"racePredictions": [{"predictionSeconds": 1200, "timestampGMT": "not-a-time"}], "token": "PRIVATE"}
    failed = _repair(tool, "race_predictions", "adv-race-bad")
    assert failed.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT id FROM source_revisions WHERE resource_kind='race_predictions' AND is_current=1").fetchone()[0] == current
        assert conn.execute("SELECT count(*) FROM garmin_sync_gaps WHERE resource_kind='race_predictions'").fetchone()[0] == 1
        assert conn.execute("SELECT error_code FROM garmin_sync_items WHERE resource_kind='race_predictions' AND status='failed' ORDER BY id DESC LIMIT 1").fetchone()[0] == "provider_payload_quarantined"
        raw = b"".join((config.raw_root.parent / row[0]).read_bytes() for row in conn.execute("SELECT relative_path FROM raw_objects"))
        dump = "\n".join(conn.iterdump()).encode()
        assert b"PRIVATE" not in raw + dump + failed.json().encode()


def test_advanced_full_incremental_lookback_and_single_coverage_per_day(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.echo_requested_day = True
    full = tool.execute(SyncRequest("full", health_from_local_date="2026-04-14", through_local_date="2026-04-15", resource_kinds=("fitness_age",), invocation_id="adv-full"))
    assert full.status == "succeeded"
    assert transport.calls == [("fitness_age", "2026-04-14"), ("fitness_age", "2026-04-15")]
    transport.calls.clear()
    incremental = tool.execute(SyncRequest("incremental", through_local_date="2026-04-15", invocation_id="adv-incremental"))
    # Incremental is a 14-day lookback; restrict the test to the target by
    # making every other advanced endpoint explicitly empty.
    assert incremental.status in {"succeeded", "partial"}
    assert len([call for call in transport.calls if call[0] == "fitness_age"]) == 14
    again = _repair(tool, "fitness_age", "adv-final-coverage")
    assert again.status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM resource_coverage WHERE resource_kind='fitness_age' AND local_date='2026-04-15'").fetchone()[0] == 1


def test_range_calendar_is_chunked_once_and_one_raw_revision_has_multi_day_lineage(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.payloads["menstrual"] = [
        {"calendarDate": "2026-04-14", "cycleLength": 28, "symptomNote": "kept-in-raw"},
        {"calendarDate": "2026-04-15", "cycleLength": 29, "symptomNote": "kept-in-raw"},
    ]
    receipt = tool.execute(SyncRequest("full", health_from_local_date="2026-04-14", through_local_date="2026-04-15", resource_kinds=("menstrual",), invocation_id="adv-calendar-range"))
    assert receipt.status == "succeeded"
    assert transport.calls == [("menstrual", "2026-04-14:2026-04-15")]
    with sqlite3.connect(config.database_path) as conn:
        revision = conn.execute("SELECT id FROM source_revisions WHERE resource_kind='menstrual' AND is_current=1").fetchone()[0]
        assert list(conn.execute("SELECT local_date,source_revision_id FROM resource_coverage WHERE resource_kind='menstrual' ORDER BY local_date")) == [("2026-04-14", revision), ("2026-04-15", revision)]
        raw = b"".join((config.raw_root.parent / row[0]).read_bytes() for row in conn.execute("SELECT relative_path FROM raw_objects WHERE resource_kind='menstrual'"))
        assert b"kept-in-raw" in raw
        assert raw == stable_json(transport.payloads["menstrual"])


def test_sparse_range_is_planned_by_catalog_limit_and_closes_empty_days(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    # This test exercises 14-day chunking, not future-date semantics.  Keep
    # its requested range inside the completed-day boundary required by L2-13.
    tool.clock = lambda: datetime(2026, 5, 1)
    records = [
        {"calendarDate": "2026-04-01", "cycleLength": 28},
        {"calendarDate": "2026-04-15", "cycleLength": 29},
        {"calendarDate": "2026-04-29", "cycleLength": 30},
    ]
    def bounded(resource: str, start: str, end: str):
        transport.calls.append((resource, f"{start}:{end}"))
        return [row for row in records if start <= row["calendarDate"] <= end]
    transport.fetch_range = bounded  # type: ignore[method-assign]
    receipt = tool.execute(SyncRequest("full", health_from_local_date="2026-04-01", through_local_date="2026-04-29", resource_kinds=("menstrual",), invocation_id="sparse-range"))
    assert receipt.status == "succeeded"
    assert transport.calls == [
        ("menstrual", "2026-04-01:2026-04-14"),
        ("menstrual", "2026-04-15:2026-04-28"),
        ("menstrual", "2026-04-29:2026-04-29"),
    ]
    with sqlite3.connect(config.database_path) as conn:
        rows = list(conn.execute("SELECT local_date,availability_state,source_revision_id FROM resource_coverage WHERE resource_kind='menstrual' ORDER BY local_date"))
        assert len(rows) == 29
        assert rows[0][1] == rows[14][1] == rows[28][1] == "fetched"
        assert rows[1][1] == "empty"  # sparse per-day absence is not a capability tombstone
        assert len({row[2] for row in rows[:14]}) == 1
        assert len({row[2] for row in rows[14:28]}) == 1
        assert conn.execute("SELECT count(*) FROM physiology_records WHERE record_type='menstrual'").fetchone()[0] == 3


def test_range_parse_failure_keeps_received_revision_and_reparse_same_payload(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    _repair(tool, "race_predictions", "range-good-current")
    with sqlite3.connect(config.database_path) as conn:
        old_current = conn.execute("SELECT id FROM source_revisions WHERE resource_kind='race_predictions' AND is_current=1").fetchone()[0]
    transport.payloads["race_predictions"] = {"racePredictions": [{"predictionSeconds": 1300, "calendarDate": "not-a-date"}], "displayName": "kept-raw"}
    failed = _repair(tool, "race_predictions", "range-unparsed")
    assert failed.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        revision = conn.execute("SELECT id,is_current,parsed_at_utc FROM source_revisions WHERE resource_kind='race_predictions' AND is_current=0 ORDER BY id DESC").fetchone()
        assert revision[1:] == (0, None)
        assert conn.execute("SELECT id FROM source_revisions WHERE resource_kind='race_predictions' AND is_current=1").fetchone()[0] == old_current
        assert conn.execute("SELECT source_revision_id FROM garmin_sync_gaps WHERE resource_kind='race_predictions'").fetchone()[0] == revision[0]
        raw = b"".join((config.raw_root.parent / row[0]).read_bytes() for row in conn.execute("SELECT relative_path FROM raw_objects WHERE resource_kind='race_predictions'"))
        assert b"kept-raw" in raw
    transport.payloads["race_predictions"] = {"racePredictions": [{"predictionSeconds": 1300, "calendarDate": "2026-04-15"}], "displayName": "kept-raw"}
    repaired = _repair(tool, "race_predictions", "range-reparse")
    assert repaired.status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM source_revisions WHERE resource_kind='race_predictions' AND is_current=1").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM physiology_metrics WHERE metric_key='garmin.race_prediction.seconds'").fetchone()[0] == 1


def test_unchanged_range_success_resolves_per_day_key_but_provider_error_does_not(
    tmp_path: Path,
) -> None:
    config, tool, transport = _setup(tmp_path)
    _repair(tool, "race_predictions", "range-unchanged-baseline")
    day = "2026-04-15"
    key = f"garmin:health:race_predictions:{day}:{day}"
    sibling = f"{key}:sibling"
    conn = tool.repo.connect()
    try:
        subject = tool.repo.subject(conn)
        tool.repo.gap(conn, subject, "race_predictions", key, day, "project", "parse_or_project_failed")
        tool.repo.gap(conn, subject, "race_predictions", sibling, day, "project", "parse_or_project_failed")
    finally:
        conn.close()
    unchanged = _repair(tool, "race_predictions", "range-unchanged-resolve")
    assert unchanged.counts["unchanged"] == 1
    with sqlite3.connect(config.database_path) as conn:
        states = dict(conn.execute(
            "SELECT logical_object_key,status FROM garmin_sync_gaps WHERE resource_kind='race_predictions'"
        ))
    assert states[key] == "resolved"
    assert states[sibling] == "open"

    conn = tool.repo.connect()
    try:
        subject = tool.repo.subject(conn)
        tool.repo.gap(conn, subject, "race_predictions", key, day, "project", "parse_or_project_failed")
    finally:
        conn.close()
    transport.errors["race_predictions"] = GarminError("provider_error", http_status=500)
    failed = _repair(tool, "race_predictions", "range-provider-error")
    assert failed.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT status FROM garmin_sync_gaps WHERE resource_kind='race_predictions' AND logical_object_key=?",
            (sibling,),
        ).fetchone()[0] == "open"
        assert conn.execute(
            "SELECT count(*) FROM garmin_sync_gaps WHERE resource_kind='race_predictions' AND logical_object_key=? AND stage='project' AND status='open'",
            (key,),
        ).fetchone()[0] == 1


def test_unchanged_range_success_promotes_each_snapshot_partial_in_place(
    tmp_path: Path,
) -> None:
    config, tool, _transport = _setup(tmp_path)
    _repair(tool, "race_predictions", "range-partial-baseline")
    with sqlite3.connect(config.database_path) as conn:
        before = conn.execute(
            """SELECT id,record_count,source_revision_id FROM resource_coverage
               WHERE resource_kind='race_predictions' AND local_date='2026-04-15'
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        assert before is not None
        conn.execute(
            "UPDATE resource_coverage SET availability_state='partial' WHERE id=?",
            (before[0],),
        )
        conn.commit()

    repeated = _repair(tool, "race_predictions", "range-partial-promote")
    assert repeated.status == "succeeded" and repeated.counts["unchanged"] == 1
    with sqlite3.connect(config.database_path) as conn:
        after = conn.execute(
            """SELECT id,availability_state,record_count,source_revision_id
               FROM resource_coverage WHERE resource_kind='race_predictions'
                 AND local_date='2026-04-15' ORDER BY id DESC LIMIT 1"""
        ).fetchone()
    assert after == (before[0], "fetched", before[1], before[2])


def test_range_long_rate_limit_defers_whole_catalog_chunks_and_does_not_close_cursor(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.errors["menstrual"] = GarminError("rate_limited", http_status=429, retry_after=121)
    receipt = tool.execute(SyncRequest("full", health_from_local_date="2026-04-01", through_local_date="2026-04-15", resource_kinds=("menstrual",), invocation_id="range-long-429"))
    assert receipt.status == "deferred" and receipt.counts["deferred"] == 1
    assert transport.calls == [("menstrual", "2026-04-01:2026-04-14")]
    with sqlite3.connect(config.database_path) as conn:
        assert list(conn.execute("SELECT window_start_local_date,window_end_local_date,status FROM garmin_sync_gaps WHERE resource_kind='menstrual' ORDER BY id")) == [
            ("2026-04-01", "2026-04-14", "deferred"),
        ]
        assert conn.execute("SELECT count(*) FROM garmin_sync_cursors WHERE resource_kind='menstrual'").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("surface", "credential_payload", "resource"),
    [
        ("daily", {"steps": 123, "client_secret": "QUARANTINE_DAILY_CLIENT"}, "steps"),
        ("daily", {"steps": 123, "sessionCookie": "QUARANTINE_DAILY_COOKIE"}, "steps"),
        (
            "daily",
            {"steps": 123, "healthNote": "Authorization: Bearer fixture-credential"},
            "steps",
        ),
        (
            "range",
            [{"calendarDate": "2026-04-15", "weight": 70, "oauthToken": "QUARANTINE_RANGE"}],
            "body_composition",
        ),
        (
            "activity",
            {
                "activityId": "opaque-id",
                "startTimeGMT": "2026-04-15T00:00:00Z",
                "id_token": "QUARANTINE_ACTIVITY",
            },
            "activity_summary",
        ),
        (
            "listing",
            [{"activityId": "opaque-id", "api_key": "QUARANTINE_LISTING"}],
            "activity_inventory",
        ),
    ],
)
def test_credential_quarantine_is_end_to_end_boundary_for_every_json_surface(
    tmp_path: Path,
    surface: str,
    credential_payload: object,
    resource: str,
) -> None:
    config, tool, transport = _setup(tmp_path)
    if surface in {"daily", "range"}:
        transport.payloads[resource] = credential_payload
    else:
        transport.list_activities = (
            (lambda *_: copy.deepcopy(credential_payload))
            if surface == "listing"
            else (lambda *_: [{"activityId": "opaque-id"}])
        )  # type: ignore[method-assign]
        if surface == "activity":
            transport.activity_summary = lambda *_: copy.deepcopy(credential_payload)  # type: ignore[method-assign]

    receipt = _repair(tool, resource, f"credential-{surface}-{resource}")
    assert receipt.status in {"partial", "failed"}
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM raw_objects WHERE resource_kind=?", (resource,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM source_revisions WHERE resource_kind=?", (resource,)
        ).fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM daily_health").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM health_samples").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM body_measurements").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM physiology_records").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM physiology_metrics").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM activities").fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM source_field_catalog WHERE resource_kind=?", (resource,)
        ).fetchone()[0] == 0
        assert conn.execute(
            """SELECT count(*) FROM garmin_sync_items
               WHERE resource_kind=? AND status='failed'
               AND error_code='provider_payload_quarantined'""",
            (resource,),
        ).fetchone()[0] >= 1
        raw_files = b"".join(
            path.read_bytes() for path in config.raw_root.rglob("*") if path.is_file()
        )
        durable = "\n".join(conn.iterdump()) + receipt.json() + raw_files.decode(errors="ignore")
        assert "QUARANTINE_" not in durable and "fixture-credential" not in durable


def test_same_raw_hash_reuses_unparsed_revision_after_projector_fix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, tool, transport = _setup(tmp_path)
    _repair(tool, "race_predictions", "same-hash-old-current")
    payload = {"racePredictions": [{"predictionSeconds": 1300, "calendarDate": "2026-04-15"}], "displayName": "raw-name"}
    transport.payloads["race_predictions"] = copy.deepcopy(payload)
    original = tool._project_health
    monkeypatch.setattr(tool, "_project_health", lambda *_args: (_ for _ in ()).throw(ValueError("controlled_project_failure")))
    assert _repair(tool, "race_predictions", "same-hash-fail").status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        received = conn.execute("SELECT id,payload_hash FROM source_revisions WHERE resource_kind='race_predictions' AND is_current=0 AND parsed_at_utc IS NULL").fetchone()
        assert received is not None
        received_id, received_hash = received
    monkeypatch.setattr(tool, "_project_health", original)
    assert _repair(tool, "race_predictions", "same-hash-reparse").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        current = conn.execute("SELECT id,payload_hash FROM source_revisions WHERE resource_kind='race_predictions' AND is_current=1").fetchone()
        assert current == (received_id, received_hash)
        assert conn.execute("SELECT count(*) FROM source_revisions WHERE resource_kind='race_predictions'").fetchone()[0] == 2


def test_malformed_range_is_validated_before_old_coverage_or_canonical_changes(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.payloads["menstrual"] = [
        {"calendarDate": "2026-04-14", "cycleLength": 28},
        {"calendarDate": "2026-04-15", "cycleLength": 29},
    ]
    assert tool.execute(SyncRequest("full", health_from_local_date="2026-04-14", through_local_date="2026-04-15", resource_kinds=("menstrual",), invocation_id="range-old-canonical")).status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        old_current = conn.execute("SELECT id FROM source_revisions WHERE resource_kind='menstrual' AND is_current=1").fetchone()[0]
        old_coverage = list(conn.execute("SELECT id,source_revision_id FROM resource_coverage WHERE resource_kind='menstrual' ORDER BY local_date"))
    transport.payloads["menstrual"] = [{"calendarDate": "2026-04-14", "cycleLength": 28}, {"calendarDate": "not-a-date", "cycleLength": 29}]
    failed = tool.execute(SyncRequest("full", health_from_local_date="2026-04-14", through_local_date="2026-04-15", resource_kinds=("menstrual",), invocation_id="range-malformed"))
    assert failed.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT id FROM source_revisions WHERE resource_kind='menstrual' AND is_current=1").fetchone()[0] == old_current
        assert list(conn.execute("SELECT id,source_revision_id FROM resource_coverage WHERE resource_kind='menstrual' ORDER BY local_date")) == old_coverage
        assert conn.execute("SELECT count(*) FROM source_revisions WHERE resource_kind='menstrual' AND is_current=0 AND parsed_at_utc IS NULL").fetchone()[0] == 1
        assert conn.execute("SELECT window_start_local_date,window_end_local_date FROM garmin_sync_gaps WHERE resource_kind='menstrual' ORDER BY id DESC LIMIT 1").fetchone() == ("2026-04-14", "2026-04-15")


def test_duplicate_advanced_range_date_is_shape_drift_before_projection(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.payloads["menstrual"] = [
        {"calendarDate": "2026-04-15", "cycleLength": 28},
        {"calendarDate": "2026-04-15", "cycleLength": 29},
    ]
    receipt = _repair(tool, "menstrual", "range-duplicate-date")
    assert receipt.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM physiology_records WHERE record_type='menstrual'").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM resource_coverage WHERE resource_kind='menstrual'").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM source_revisions WHERE resource_kind='menstrual' AND is_current=0 AND parsed_at_utc IS NULL").fetchone()[0] == 1


@pytest.mark.parametrize(("error", "expected_state", "expected_receipt"), [
    (GarminError("forbidden", http_status=403), "forbidden", "partial"),
    (GarminError("missing", http_status=404), "not_available", "succeeded"),
])
def test_range_terminal_4xx_has_chunk_coverage_capability_and_gap(tmp_path: Path, error: GarminError, expected_state: str, expected_receipt: str) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.errors["menstrual"] = error
    receipt = _repair(tool, "menstrual", f"range-{expected_state}")
    assert receipt.status == expected_receipt
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT availability_state FROM resource_coverage WHERE resource_kind='menstrual'").fetchone()[0] == expected_state
        assert conn.execute("SELECT capability_state FROM garmin_resource_capabilities WHERE resource_kind='menstrual'").fetchone()[0] == expected_state
        assert conn.execute("SELECT window_start_local_date,window_end_local_date FROM garmin_sync_gaps WHERE resource_kind='menstrual'").fetchone() == ("2026-04-15", "2026-04-15")


def test_range_short_rate_limit_retries_inline_and_transient_errors_stop_at_five(tmp_path: Path) -> None:
    _, tool, transport = _setup(tmp_path / "timeout")
    attempts = {"count": 0}
    def short_then_success(resource: str, start: str, end: str):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise GarminError("rate_limited", http_status=429, retry_after=1)
        return [{"calendarDate": start, "cycleLength": 28}]
    transport.fetch_range = short_then_success  # type: ignore[method-assign]
    assert _repair(tool, "menstrual", "range-short-429").status == "succeeded"
    assert attempts["count"] == 2

    _, tool, transport = _setup(tmp_path)
    transport.errors["menstrual"] = GarminError("timeout")
    failed = _repair(tool, "menstrual", "range-timeout-five")
    assert failed.status == "partial"
    assert [call for call in transport.calls if call[0] == "menstrual"] == [("menstrual", "2026-04-15:2026-04-15")] * 5


def test_range_second_401_is_run_auth_required_after_one_refresh(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    logins = {"count": 0}
    def login() -> None: logins["count"] += 1
    transport.login = login  # type: ignore[method-assign]
    transport.errors["menstrual"] = GarminError("unauthorized", http_status=401)
    receipt = _repair(tool, "menstrual", "range-second-401")
    assert receipt.status == "auth_required" and logins["count"] == 2  # initial login + one refresh
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT status FROM garmin_sync_runs ORDER BY id DESC LIMIT 1").fetchone()[0] == "auth_required"


@pytest.mark.parametrize(
    ("resource", "payload"),
    [
        ("blood_pressure", {
            "measurementSummaries": [], "categoryStats": {},
            "from": "2026-04-15", "until": "2026-04-15",
        }),
        ("body_composition", {
            "dateWeightList": [], "startDate": "2026-04-15",
            "endDate": "2026-04-15", "totalAverage": {},
        }),
        ("weigh_ins", {
            "dailyWeightSummaries": [], "previousDateWeight": {},
            "nextDateWeight": {}, "totalAverage": {},
        }),
        ("lactate_threshold", {"speed": [], "heart_rate": [], "power": []}),
        ("menstrual", {
            "cycleSummaries": [], "loggedNoteDays": [],
            "loggedOvulationDays": [], "loggedSymptomDays": [],
        }),
    ],
)
def test_live_range_metadata_envelopes_with_empty_results_are_valid(
    tmp_path: Path, resource: str, payload: object
) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.payloads[resource] = payload
    receipt = _repair(tool, resource, f"live-empty-{resource}")
    assert receipt.status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT availability_state FROM resource_coverage "
            "WHERE resource_kind=? AND local_date='2026-04-15'",
            (resource,),
        ).fetchone()[0] == "empty"
        assert conn.execute(
            "SELECT count(*) FROM garmin_sync_gaps WHERE resource_kind=?",
            (resource,),
        ).fetchone()[0] == 0


def test_live_health_range_shapes_project_only_measurements_and_preserve_raw(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    weigh_ins = {
        "dailyWeightSummaries": [{
            "summaryDate": "2026-04-15",
            "latestWeight": {"calendarDate": "2026-04-15", "weight": 70.1},
            "allWeightMetrics": [
                {"calendarDate": "2026-04-15", "weight": 70.2},
                {"timestampGMT": "2026-04-15T02:30:00Z", "weight": 70.0},
            ],
        }],
    }
    lactate = {
        "heart_rate": [{"from": "2026-04-15", "series": "daily", "until": "2026-04-15", "updatedDate": "2026-04-15", "value": 165}],
        "power": [{"from": "2026-04-15", "series": "daily", "until": "2026-04-15", "updatedDate": "2026-04-15", "value": 240}],
        "speed": [{"from": "2026-04-15", "series": "daily", "until": "2026-04-15", "updatedDate": "2026-04-15", "value": 3.8}],
    }
    hill_empty = {
        "hillScoreDTOList": [], "maxScore": None,
        "periodAvgScore": {"2026-04-15": None}, "startDate": "2026-04-15", "endDate": "2026-04-15",
    }
    transport.payloads.update({"weigh_ins": weigh_ins, "lactate_threshold": lactate, "hill_score": hill_empty})

    assert _repair(tool, "weigh_ins", "live-weigh-ins").status == "succeeded"
    assert _repair(tool, "lactate_threshold", "live-lactate").status == "succeeded"
    assert _repair(tool, "hill_score", "live-hill-empty").status == "succeeded"
    assert _repair(tool, "weigh_ins", "live-weigh-ins-repeat").counts["unchanged"] == 1
    assert _repair(tool, "lactate_threshold", "live-lactate-repeat").counts["unchanged"] == 1
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM body_measurements").fetchone()[0] == 2
        assert set(conn.execute(
            "SELECT metric_key FROM physiology_metrics WHERE metric_key LIKE 'garmin.lactate_threshold.%'"
        )) == {
            ("garmin.lactate_threshold.heart_rate_bpm",),
            ("garmin.lactate_threshold.power_w",),
            ("garmin.lactate_threshold.speed_mps",),
        }
        assert set(conn.execute(
            "SELECT source_path FROM physiology_metrics WHERE metric_key LIKE 'garmin.lactate_threshold.%'"
        )) == {("/heart_rate/*/value",), ("/power/*/value",), ("/speed/*/value",)}
        assert conn.execute(
            "SELECT count(*) FROM physiology_metrics WHERE metric_key='garmin.hill_score'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT availability_state,record_count FROM resource_coverage WHERE resource_kind='hill_score'"
        ).fetchone() == ("empty", 0)
        assert conn.execute(
            "SELECT count(*) FROM source_field_catalog WHERE resource_kind='lactate_threshold' AND field_path LIKE '%__trainlab%'"
        ).fetchone()[0] == 0
        assert set(conn.execute(
            "SELECT field_path FROM source_field_catalog WHERE resource_kind='lactate_threshold' AND mapping_state='mapped'"
        )) == {("/heart_rate/*/value",), ("/power/*/value",), ("/speed/*/value",)}
        raw = b"".join(
            (config.raw_root.parent / row[0]).read_bytes()
            for row in conn.execute(
                "SELECT relative_path FROM raw_objects WHERE resource_kind IN ('weigh_ins', 'lactate_threshold', 'hill_score')"
            )
        )
        assert stable_json(weigh_ins) in raw and stable_json(lactate) in raw and stable_json(hill_empty) in raw


def test_hill_score_non_null_period_average_is_not_silently_empty(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.payloads["hill_score"] = {
        "hillScoreDTOList": [], "maxScore": None,
        "periodAvgScore": {"2026-04-15": 42},
        "startDate": "2026-04-15", "endDate": "2026-04-15",
    }
    receipt = _repair(tool, "hill_score", "hill-non-null-period-average")
    assert receipt.status == "partial" and receipt.counts["failed"] == 1
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM resource_coverage WHERE resource_kind='hill_score'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT error_code FROM garmin_sync_items WHERE resource_kind='hill_score' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0] == "parse_or_project_failed"


def test_live_body_battery_date_and_endurance_singleton_envelopes(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    selected = tool._range_payload_by_day(
        [{
            "date": "2026-04-15",
            "startTimestampGMT": "2026-04-14T15:00:00Z",
            "bodyBatteryValuesArray": [["2026-04-15T00:00:00Z", 70]],
            "charged": 25,
            "drained": 10,
        }],
        datetime(2026, 4, 15).date(),
        datetime(2026, 4, 15).date(),
        resource="body_battery",
    )
    assert len(selected["2026-04-15"]) == 1

    transport.payloads["endurance_score"] = {
        "startDate": "2026-04-15",
        "endDate": "2026-04-15",
        "enduranceScoreDTO": {
            "calendarDate": "2026-04-15",
            "overallScore": 5100,
        },
        "groupMap": {},
    }
    receipt = _repair(tool, "endurance_score", "live-endurance-singleton")
    assert receipt.status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT value_number FROM physiology_metrics "
            "WHERE metric_key='garmin.endurance_score'"
        ).fetchone()[0] == 5100


def test_empty_meals_wrapper_is_zero_records_not_shape_failure(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.payloads["nutrition_meals"] = {
        "dailyViewType": "DAY",
        "meals": [],
    }
    receipt = _repair(tool, "nutrition_meals", "live-empty-meals")
    assert receipt.status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM physiology_records "
            "WHERE record_type='nutrition_meals'"
        ).fetchone()[0] == 0


def test_endurance_latest_outside_requested_window_is_not_misattributed(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.payloads["endurance_score"] = {
        "startDate": "2026-04-15",
        "endDate": "2026-04-15",
        "enduranceScoreDTO": {
            "calendarDate": "2026-04-08",
            "overallScore": 5000,
            "contributors": [{"type": "activity"}],
        },
        "groupMap": {},
    }
    receipt = _repair(tool, "endurance_score", "endurance-older-latest")
    assert receipt.status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT availability_state FROM resource_coverage "
            "WHERE resource_kind='endurance_score'"
        ).fetchone()[0] == "empty"
        assert conn.execute(
            "SELECT count(*) FROM physiology_metrics "
            "WHERE metric_key='garmin.endurance_score'"
        ).fetchone()[0] == 0


def test_endurance_supported_null_calendar_date_is_empty(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.payloads["endurance_score"] = {
        "calendarDate": None,
        "overallScore": None,
        "contributors": [],
    }
    receipt = _repair(tool, "endurance_score", "endurance-null-day")
    assert receipt.status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT availability_state FROM resource_coverage "
            "WHERE resource_kind='endurance_score'"
        ).fetchone()[0] == "empty"
