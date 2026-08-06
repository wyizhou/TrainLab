"""Offline L2-12 acceptance: enrichments, chart fallback, and reconciliation."""
from __future__ import annotations

import copy
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import fitdecode
import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.garmin import (
    ACTIVITY_CHART_MAX_POINTS,
    ACTIVITY_ENRICHMENTS,
    GarminCollectionTool,
    GarminConfig,
    GarminError,
    SyncRequest,
)
from trainlab.garmin_client import GarminConnectTransport, TokenStore


FIT_PATH = Path(__file__).resolve().parents[1] / "test_data/new/Running.fit"


def _fit_start(path: Path = FIT_PATH) -> str:
    with fitdecode.FitReader(path, check_crc=True) as reader:
        for frame in reader:
            if isinstance(frame, fitdecode.FitDataMessage) and frame.name == "session":
                values = {field.name: field.value for field in frame.fields}
                return values["start_time"].isoformat().replace("+00:00", "Z")
    raise AssertionError("running fixture has no session")


class L212Transport:
    def __init__(self, *, sport: str = "running", fit: bytes | GarminError | None = None) -> None:
        self.sport = sport
        self.fit = fit if fit is not None else GarminError("http_404", http_status=404)
        self.summary: dict[str, Any] = {
            "activityId": 1,
            "activityName": "L2-12 fixture",
            "activityType": {"typeKey": sport},
            "startTimeGMT": _fit_start(),
            "duration": 600,
            "movingDuration": 590,
            "distance": 2_000,
            "calories": 0,
            "unknownSummary": "raw-only",
        }
        self.extras: dict[str, Any] = {
            "splits_json": {"activityId": 1, "splits": [{"distance": 1_000}]},
            "typed_splits_json": {
                "activityId": 1,
                "typedSplits": [{
                    "splitType": "ACTIVE",
                    "gradeRaw": "6a",
                    "completed": False,
                    "falls": 0,
                    "duration": 0,
                    "unknownRoute": "raw-only",
                }],
            },
            "split_summaries_json": {"activityId": 1, "summaries": []},
            "exercise_sets_json": {
                "activityId": 1,
                "exerciseSets": [{
                    "setType": "active",
                    "exerciseCategory": "bench_press",
                    "exerciseName": "Bench press",
                    "repetitions": 0,
                    "weightKg": 0,
                    "duration": 0,
                    "unknownSet": "raw-only",
                }],
            },
            "hr_zones_json": {
                "activityId": 1,
                "zones": [{"zoneNumber": 1, "secsInZone": 0, "unknown": "raw-only"}],
            },
            "power_zones_json": {
                "activityId": 1,
                "zones": [{"zoneNumber": 1, "secsInZone": 0, "unknown": "raw-only"}],
            },
            "weather_json": {
                "activityId": 1,
                "temperature": 0,
                "relativeHumidity": None,
                "unknownWeather": "raw-only",
            },
            "gear_json": {
                "activityId": 1,
                "gear": [{"gearPk": 0, "displayName": None, "unknown": "raw-only"}],
            },
        }
        self.calls: list[str] = []

    def login(self) -> None:
        return None

    def identity(self) -> str:
        return "l2-12"

    def fetch_health(self, *_args: Any) -> list[Any]:
        return []

    def fetch_range(self, *_args: Any) -> list[Any]:
        return []

    def fetch_account(self, *_args: Any) -> list[Any]:
        return []

    def list_activities(self, *_args: Any) -> list[dict[str, Any]]:
        return [{"activityId": 1, "startTimeGMT": self.summary["startTimeGMT"]}]

    def activity_summary(self, _activity_id: str) -> dict[str, Any]:
        return copy.deepcopy(self.summary)

    def activity_original(self, _activity_id: str) -> bytes:
        if isinstance(self.fit, GarminError):
            raise self.fit
        assert isinstance(self.fit, bytes)
        return self.fit

    def activity_extra(self, _activity_id: str, role: str) -> Any:
        self.calls.append(role)
        value = self.extras.get(role)
        if isinstance(value, GarminError):
            raise value
        return copy.deepcopy(value)


def _setup(tmp_path: Path, transport: L212Transport) -> tuple[GarminCollectionTool, FoundationConfig]:
    root = tmp_path / "data"
    foundation = FoundationConfig(
        root, root / "data.db", root / "raw", root / "state",
        root / "state/ready", root / "state/locks/foundation.lock",
    )
    assert FoundationTool(foundation).execute(
        FoundationRequest("init", "l2-12", "2026-01-01T00:00:00Z")
    ).status == "initialized"
    tool = GarminCollectionTool(
        GarminConfig(
            foundation.database_path, foundation.raw_root,
            foundation.state_root, "2026-01-01", request_min_interval_ms=0,
        ),
        transport,
        sleep=lambda _seconds: None,
        clock=lambda: datetime(2026, 7, 20),
        monotonic=lambda: 1000.0,
    )
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    return tool, foundation


def _sync(
    tool: GarminCollectionTool,
    invocation: str,
    resources: tuple[str, ...],
):
    return tool.execute(SyncRequest(
        "repair", through_local_date="2026-07-19", activity_ids=("1",),
        resource_kinds=resources, invocation_id=invocation,
    ))


def _enrichment_resources() -> tuple[str, ...]:
    return tuple(resource for resource, _role in ACTIVITY_ENRICHMENTS)


def test_applicable_enrichments_have_exact_resource_revision_role_and_reviewed_projection(
    tmp_path: Path,
) -> None:
    transport = L212Transport()
    tool, foundation = _setup(tmp_path, transport)
    result = _sync(tool, "enrich-all", _enrichment_resources())
    assert result.status == "succeeded"
    expected_roles = {
        "splits_json", "typed_splits_json", "split_summaries_json",
        "hr_zones_json", "power_zones_json", "weather_json", "gear_json",
    }
    with sqlite3.connect(foundation.database_path) as conn:
        conn.row_factory = sqlite3.Row
        relations = {
            row["source_role"]: row["resource_kind"]
            for row in conn.execute(
                """SELECT ar.source_role,sr.resource_kind
                   FROM activity_source_revisions ar
                   JOIN source_revisions sr ON sr.id=ar.source_revision_id
                   WHERE ar.is_active=1 AND ar.source_role!='summary_json'"""
            )
        }
        assert set(relations) == expected_roles
        assert relations["typed_splits_json"] == "activity_typed_splits"
        assert relations["weather_json"] == "activity_weather"
        extras = json.loads(conn.execute(
            "SELECT extras_json FROM activities"
        ).fetchone()[0])
        weather = extras["connect_enrichments"]["weather_json"]["reviewed"]
        assert weather == {"relativeHumidity": None, "temperature": 0}
        assert "unknownWeather" not in json.dumps(extras)
        raw_path = conn.execute(
            """SELECT o.relative_path FROM source_revisions sr
               JOIN raw_objects o ON o.id=sr.raw_object_id
               WHERE sr.resource_kind='activity_weather'"""
        ).fetchone()[0]
    assert b"unknownWeather" in (foundation.data_root / raw_path).read_bytes()
    assert "exercise_sets_json" not in transport.calls


def test_exercise_sets_and_typed_routes_preserve_zero_null_and_revision_source(
    tmp_path: Path,
) -> None:
    transport = L212Transport(sport="strength_training")
    tool, foundation = _setup(tmp_path, transport)
    result = _sync(
        tool, "sets-routes",
        ("activity_exercise_sets", "activity_typed_splits"),
    )
    assert result.status == "succeeded"
    with sqlite3.connect(foundation.database_path) as conn:
        route = conn.execute(
            """SELECT r.completed,r.falls,s.duration_seconds,sr.resource_kind
               FROM climbing_routes r JOIN activity_segments s ON s.id=r.segment_id
               JOIN source_revisions sr ON sr.id=s.source_revision_id"""
        ).fetchone()
        assert route == (0, 0, 0.0, "activity_typed_splits")
        strength = conn.execute(
            """SELECT x.repetitions,x.weight_kg,x.duration_seconds,sr.resource_kind
               FROM strength_sets x JOIN activity_segments s ON s.id=x.segment_id
               JOIN source_revisions sr ON sr.id=s.source_revision_id"""
        ).fetchone()
        assert strength == (0, 0.0, 0.0, "activity_exercise_sets")


@pytest.mark.parametrize(
    ("role", "value", "terminal", "gap_count"),
    [
        ("splits_json", {}, "revised", 0),
        ("typed_splits_json", [], "revised", 0),
        ("split_summaries_json", GarminError("http_404", http_status=404), "not_available", 0),
        ("hr_zones_json", GarminError("http_403", http_status=403), "forbidden", 1),
        ("gear_json", GarminError("network"), "failed", 1),
    ],
)
def test_empty_and_endpoint_failures_are_isolated_to_exact_enrichment(
    tmp_path: Path,
    role: str,
    value: Any,
    terminal: str,
    gap_count: int,
) -> None:
    transport = L212Transport()
    transport.extras[role] = value
    resource = dict((role_value, resource_value) for resource_value, role_value in ACTIVITY_ENRICHMENTS)[role]
    tool, foundation = _setup(tmp_path, transport)
    _sync(tool, f"failure-{role}", (resource, "activity_weather"))
    with sqlite3.connect(foundation.database_path) as conn:
        assert conn.execute(
            """SELECT status FROM garmin_sync_items
               WHERE resource_kind=? AND stage IN ('fetch','project')
               ORDER BY id DESC LIMIT 1""",
            (resource,),
        ).fetchone()[0] == terminal
        assert conn.execute(
            "SELECT count(*) FROM garmin_sync_gaps WHERE resource_kind=?",
            (resource,),
        ).fetchone()[0] == gap_count
        assert conn.execute(
            """SELECT count(*) FROM source_revisions
               WHERE resource_kind='activity_weather' AND is_current=1"""
        ).fetchone()[0] == (0 if resource == "activity_weather" and terminal not in {"revised"} else 1)


def test_binding_mismatch_keeps_raw_noncurrent_and_has_zero_canonical_effects(
    tmp_path: Path,
) -> None:
    transport = L212Transport()
    transport.extras["weather_json"]["activityId"] = 999
    tool, foundation = _setup(tmp_path, transport)
    result = _sync(tool, "binding", ("activity_weather",))
    assert result.status == "partial"
    with sqlite3.connect(foundation.database_path) as conn:
        assert conn.execute(
            """SELECT count(*) FROM source_revisions
               WHERE resource_kind='activity_weather' AND is_current=0
                 AND parsed_at_utc IS NULL"""
        ).fetchone()[0] == 1
        assert conn.execute(
            """SELECT count(*) FROM activity_source_revisions
               WHERE source_role='weather_json'"""
        ).fetchone()[0] == 0
        extras = json.loads(conn.execute("SELECT extras_json FROM activities").fetchone()[0])
        assert "weather_json" not in extras.get("connect_enrichments", {})


def test_no_fit_chart_is_bounded_partial_then_fit_atomically_becomes_canonical(
    tmp_path: Path,
) -> None:
    transport = L212Transport()
    start = datetime.fromisoformat(_fit_start().replace("Z", "+00:00")).timestamp()
    transport.extras["details_json_fallback"] = {
        "activityId": 1,
        "points": [
            {
                "directTimestamp": (start + index) * 1000,
                "directHeartRate": 0 if index == 0 else 120,
                "unknown": "raw-only",
            }
            for index in range(ACTIVITY_CHART_MAX_POINTS + 501)
        ],
    }
    tool, foundation = _setup(tmp_path, transport)
    first = _sync(
        tool, "chart-first",
        ("activity_fit", "activity_details_fallback"),
    )
    assert first.status == "partial"
    with sqlite3.connect(foundation.database_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM activity_samples WHERE stream_kind='connect_chart'"
        ).fetchone()[0] == ACTIVITY_CHART_MAX_POINTS
        assert conn.execute(
            """SELECT count(*) FROM resource_coverage
               WHERE resource_kind='activity_details_fallback'
                 AND availability_state='partial'"""
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT heart_rate_bpm FROM activity_samples ORDER BY sample_index LIMIT 1"
        ).fetchone()[0] == 0
        source_map = json.loads(conn.execute(
            "SELECT source_map_json FROM activities"
        ).fetchone()[0])
        assert source_map["sensor_stream"]["coverage"] == "partial"
        evidence = json.loads(conn.execute(
            """SELECT details_json FROM data_quality_issues
               WHERE issue_code='activity_chart_sampled' AND status='open'"""
        ).fetchone()[0])
        assert evidence["received_point_count"] == ACTIVITY_CHART_MAX_POINTS + 501

    transport.fit = FIT_PATH.read_bytes()
    second = _sync(tool, "chart-promote", ("activity_fit",))
    assert second.status == "succeeded"
    with sqlite3.connect(foundation.database_path) as conn:
        source_map = json.loads(conn.execute(
            "SELECT source_map_json FROM activities"
        ).fetchone()[0])
        assert source_map["sensor_stream"]["stream_kind"] == "fit_record"
        assert conn.execute(
            """SELECT is_active FROM activity_source_revisions
               WHERE source_role='details_json_fallback'"""
        ).fetchone()[0] == 0
        assert conn.execute(
            """SELECT count(*) FROM source_revisions
               WHERE resource_kind='activity_details_fallback' AND is_current=1"""
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM activity_samples WHERE stream_kind='connect_chart'"
        ).fetchone()[0] == ACTIVITY_CHART_MAX_POINTS
        assert conn.execute(
            """SELECT count(*) FROM data_quality_issues
               WHERE issue_code='activity_sensor_fallback' AND status='resolved'"""
        ).fetchone()[0] == 1


def test_reconciliation_tolerance_tri_state_end_inference_and_replay(
    tmp_path: Path,
) -> None:
    transport = L212Transport(fit=FIT_PATH.read_bytes())
    transport.summary.update({
        "elapsedDuration": 7893.188,
        "duration": 7750.209,
        "movingDuration": 7700.0,
        "distance": 20140.0,
        "calories": 0,
        "anaerobicTrainingEffect": None,
    })
    tool, foundation = _setup(tmp_path, transport)
    assert _sync(tool, "reconcile-one", ("activity_fit",)).status == "succeeded"
    with sqlite3.connect(foundation.database_path) as conn:
        rows = {
            row[0]: row[1:]
            for row in conn.execute(
                """SELECT field_key,result,left_value_json,right_value_json
                   FROM reconciliation_results WHERE entity_type='activity'"""
            )
        }
        assert rows["distance_m"][0] == "within_tolerance"
        assert rows["calories_kcal"][0] == "mismatch"
        assert json.loads(rows["calories_kcal"][1]) == {"state": "value", "value": 0}
        assert json.loads(rows["anaerobic_training_effect"][1]) == {
            "state": "null", "value": None,
        }
        assert json.loads(rows["aerobic_training_effect"][1]) == {"state": "missing"}
        activity = conn.execute(
            "SELECT end_time_utc,extras_json,source_map_json,elapsed_seconds,timer_seconds FROM activities"
        ).fetchone()
        assert activity[0] is not None
        assert json.loads(activity[1])["end_time_inference"]["confidence"] >= 0.7
        assert json.loads(activity[2])["end_time_utc"]["evidence_revision_ids"]
        assert activity[3] == pytest.approx(7893.188)
        assert activity[4] == pytest.approx(7750.209)
        assert rows["elapsed_seconds"][0] in {"match", "within_tolerance"}
        assert rows["timer_seconds"][0] in {"match", "within_tolerance"}
        postprocessed = json.loads(activity[1])["postprocessed_metrics"]
        assert postprocessed["connect"]["values"]["calories_kcal"]["value"] == 0
        assert postprocessed["fit"]["values"]["calories_kcal"]["value"] == 1400
        count = conn.execute("SELECT count(*) FROM reconciliation_results").fetchone()[0]
    assert _sync(tool, "reconcile-replay", ("activity_fit",)).status == "succeeded"
    with sqlite3.connect(foundation.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM reconciliation_results").fetchone()[0] == count


def test_nested_summary_offline_reparse_uses_normalized_payload(tmp_path: Path) -> None:
    transport = L212Transport()
    original = dict(transport.summary)
    transport.summary = {
        "activityId": 1,
        "activityName": "nested summary",
        "activityTypeDTO": original["activityType"],
        "summaryDTO": {
            "activityId": 1,
            "startTimeGMT": original["startTimeGMT"],
            "elapsedDuration": 620,
            "duration": 600,
            "movingDuration": 590,
            "distance": 2_000,
        },
    }
    tool, foundation = _setup(tmp_path, transport)
    assert _sync(tool, "nested-source", ("activity_summary",)).status == "succeeded"
    with sqlite3.connect(foundation.database_path) as conn:
        conn.execute("UPDATE activities SET elapsed_seconds=NULL,timer_seconds=NULL")
        conn.commit()
    repaired = tool.execute(SyncRequest(
        "repair", through_local_date="2026-07-19", activity_ids=("1",),
        resource_kinds=("activity_summary",), repair_strategy="reparse",
        invocation_id="nested-reparse",
    ))
    assert repaired.status == "succeeded"
    with sqlite3.connect(foundation.database_path) as conn:
        assert conn.execute(
            "SELECT elapsed_seconds,timer_seconds FROM activities"
        ).fetchone() == pytest.approx((620, 600))


def test_conflicting_end_evidence_fails_closed_and_records_quality(
    tmp_path: Path,
) -> None:
    transport = L212Transport(fit=FIT_PATH.read_bytes())
    transport.summary["elapsedDuration"] = 100
    transport.summary["duration"] = 100
    tool, foundation = _setup(tmp_path, transport)
    assert _sync(tool, "end-conflict", ("activity_fit",)).status == "succeeded"
    with sqlite3.connect(foundation.database_path) as conn:
        activity = conn.execute(
            "SELECT end_time_utc,extras_json,source_map_json FROM activities"
        ).fetchone()
        assert activity[0] is None
        assert json.loads(activity[1])["end_time_inference"]["decision"] == "fail_closed"
        assert "end_time_utc" not in json.loads(activity[2])
        assert conn.execute(
            """SELECT count(*) FROM data_quality_issues
               WHERE issue_code='activity_end_time_conflict' AND status='open'"""
        ).fetchone()[0] == 1


@pytest.mark.parametrize(
    ("filename", "sport", "resource", "canonical_key", "json_resource"),
    [
        (
            "Bouldering.fit", "bouldering", "activity_typed_splits",
            "climbing_routes", "activity_typed_splits",
        ),
        (
            "力量训练.fit", "strength_training", "activity_exercise_sets",
            "strength_sets", "activity_exercise_sets",
        ),
    ],
)
def test_json_routes_and_sets_are_revision_bound_but_fit_remains_canonical(
    tmp_path: Path,
    filename: str,
    sport: str,
    resource: str,
    canonical_key: str,
    json_resource: str,
) -> None:
    fit_path = FIT_PATH.parent / filename
    transport = L212Transport(sport=sport, fit=fit_path.read_bytes())
    transport.summary["startTimeGMT"] = _fit_start(fit_path)
    tool, foundation = _setup(tmp_path, transport)
    assert _sync(tool, f"fit-priority-{resource}", ("activity_fit", resource)).status == "succeeded"
    with sqlite3.connect(foundation.database_path) as conn:
        source_map = json.loads(conn.execute(
            "SELECT source_map_json FROM activities"
        ).fetchone()[0])
        assert source_map[canonical_key]["source_role"] == "activity_fit"
        assert conn.execute(
            """SELECT count(*) FROM activity_segments s
               JOIN source_revisions sr ON sr.id=s.source_revision_id
               WHERE sr.resource_kind=?""",
            (json_resource,),
        ).fetchone()[0] > 0
        assert conn.execute(
            """SELECT count(*) FROM activity_source_revisions
               WHERE source_role=? AND is_active=1""",
            (
                "typed_splits_json"
                if resource == "activity_typed_splits"
                else "exercise_sets_json",
            ),
        ).fetchone()[0] == 1


def test_transient_fit_failure_does_not_implicitly_fetch_chart(
    tmp_path: Path,
) -> None:
    transport = L212Transport(fit=GarminError("network"))
    transport.extras["details_json_fallback"] = {"activityId": 1, "points": []}
    tool, foundation = _setup(tmp_path, transport)
    result = tool.execute(SyncRequest(
        "full", through_local_date="2026-07-19",
        resource_kinds=(), invocation_id="transient-no-chart",
    ))
    assert result.status == "partial"
    assert "details_json_fallback" not in transport.calls
    with sqlite3.connect(foundation.database_path) as conn:
        assert conn.execute(
            """SELECT count(*) FROM source_revisions
               WHERE resource_kind='activity_details_fallback'"""
        ).fetchone()[0] == 0


def test_bad_json_enrichment_has_no_raw_revision_relation_or_projection(
    tmp_path: Path,
) -> None:
    transport = L212Transport()
    transport.extras["weather_json"] = {"activityId": 1, "temperature": float("nan")}
    tool, foundation = _setup(tmp_path, transport)
    result = _sync(tool, "bad-json", ("activity_weather",))
    assert result.status == "partial"
    with sqlite3.connect(foundation.database_path) as conn:
        for table in ("raw_objects", "source_revisions"):
            assert conn.execute(
                f"SELECT count(*) FROM {table} WHERE resource_kind='activity_weather'"
            ).fetchone()[0] == 0
        assert conn.execute(
            """SELECT count(*) FROM activity_source_revisions
               WHERE source_role='weather_json'"""
        ).fetchone()[0] == 0


def test_adapter_details_uses_reviewed_chart_bounds_and_missing_method_is_not_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, ...]] = []

    class Client:
        def get_activity_details(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            calls.append((args, kwargs))
            return {}

    client = Client()
    monkeypatch.setattr(GarminConnectTransport, "_apply_request_timeout", lambda self: None)
    adapter = GarminConnectTransport(None, None, TokenStore(tmp_path / "tokens"), client=client)
    assert adapter.activity_extra("1", "details_json_fallback") == {}
    assert calls == [(("1",), {"maxchart": 2000, "maxpoly": 4000})]
    with pytest.raises(GarminError, match="not_supported"):
        adapter.activity_extra("1", "weather_json")


@pytest.mark.parametrize(
    ("sport", "resource", "role", "payload", "detail_table", "issue_code"),
    [
        (
            "strength_training", "activity_exercise_sets", "exercise_sets_json",
            {"activityId": 1, "exerciseSets": [{"newUnknown": "x"}]},
            "strength_sets", "activity_exercise_sets_drift",
        ),
        (
            "bouldering", "activity_typed_splits", "typed_splits_json",
            {"activityId": 1, "typedSplits": [{"newUnknown": "x"}]},
            "climbing_routes", "activity_typed_splits_drift",
        ),
    ],
)
def test_unknown_only_typed_rows_never_create_phantom_canonical(
    tmp_path: Path,
    sport: str,
    resource: str,
    role: str,
    payload: dict[str, Any],
    detail_table: str,
    issue_code: str,
) -> None:
    transport = L212Transport(sport=sport)
    transport.extras[role] = payload
    tool, foundation = _setup(tmp_path, transport)
    assert _sync(tool, f"unknown-only-{role}", (resource,)).status == "succeeded"
    with sqlite3.connect(foundation.database_path) as conn:
        assert conn.execute(
            """SELECT count(*) FROM activity_segments s
               JOIN source_revisions sr ON sr.id=s.source_revision_id
               WHERE sr.resource_kind=?""",
            (resource,),
        ).fetchone()[0] == 0
        assert conn.execute(f"SELECT count(*) FROM {detail_table}").fetchone()[0] == 0
        assert conn.execute(
            """SELECT count(*) FROM activity_source_revisions
               WHERE source_role=? AND is_active=1""",
            (role,),
        ).fetchone()[0] == 1
        evidence = json.loads(conn.execute(
            """SELECT details_json FROM data_quality_issues
               WHERE issue_code=? AND status='open'""",
            (issue_code,),
        ).fetchone()[0])
        assert evidence["received_row_count"] == 1
        assert evidence["valid_row_count"] == 0
        assert evidence["dropped_row_count"] == 1
        assert evidence["drop_reasons"] == {"unknown_only": 1}
        assert conn.execute(
            """SELECT count(*) FROM source_field_catalog
               WHERE resource_kind=? AND field_path LIKE '%/newUnknown'""",
            (resource,),
        ).fetchone()[0] == 1


@pytest.mark.parametrize(
    ("points", "issue_code", "received", "dropped"),
    [
        ([], "activity_chart_empty", 0, 0),
        (
            [{"newUnknown": "x"}, {"newUnknown": "y"}],
            "activity_chart_invalid", 2, 2,
        ),
    ],
)
def test_empty_or_unknown_only_chart_is_received_noncurrent_and_never_canonical(
    tmp_path: Path,
    points: list[dict[str, Any]],
    issue_code: str,
    received: int,
    dropped: int,
) -> None:
    transport = L212Transport()
    transport.extras["details_json_fallback"] = {
        "activityId": 1,
        "points": points,
    }
    tool, foundation = _setup(tmp_path, transport)
    invocation = f"invalid-chart-{issue_code}"
    result = _sync(tool, invocation, ("activity_details_fallback",))
    assert result.status == "partial"
    assert _sync(
        tool, invocation, ("activity_details_fallback",),
    ).json() == result.json()
    with sqlite3.connect(foundation.database_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM activity_samples WHERE stream_kind='connect_chart'"
        ).fetchone()[0] == 0
        assert conn.execute(
            """SELECT count(*) FROM activity_source_revisions
               WHERE source_role='details_json_fallback' AND is_active=1"""
        ).fetchone()[0] == 0
        revision = conn.execute(
            """SELECT is_current,parsed_at_utc FROM source_revisions
               WHERE resource_kind='activity_details_fallback'"""
        ).fetchone()
        assert revision == (0, None)
        activity = conn.execute(
            "SELECT extras_json,source_map_json FROM activities"
        ).fetchone()
        assert "sensor_stream" not in json.loads(activity[1])
        evidence = json.loads(conn.execute(
            """SELECT details_json FROM data_quality_issues
               WHERE issue_code=? AND status='open'""",
            (issue_code,),
        ).fetchone()[0])
        assert evidence["received_point_count"] == received
        assert evidence["valid_point_count"] == 0
        assert evidence["dropped_point_count"] == dropped
        assert evidence["persisted_point_count"] == 0
        assert conn.execute(
            """SELECT count(*) FROM garmin_sync_gaps
               WHERE resource_kind='activity_details_fallback'
                 AND stage='project' AND reason_code=?""",
            (issue_code,),
        ).fetchone()[0] == 1
        if received:
            assert conn.execute(
                """SELECT count(*) FROM source_field_catalog
                   WHERE resource_kind='activity_details_fallback'
                     AND field_path LIKE '%/newUnknown'"""
            ).fetchone()[0] == 1


def test_chart_filters_invalid_rows_before_sampling_and_keeps_source_indexes(
    tmp_path: Path,
) -> None:
    transport = L212Transport()
    start = datetime.fromisoformat(_fit_start().replace("Z", "+00:00")).timestamp()
    transport.extras["details_json_fallback"] = {
        "activityId": 1,
        "points": [
            {"newUnknown": "x"},
            {"directHeartRate": 0},
            {"directHeartRate": True},
            {"directTimestamp": start * 1000},
        ],
    }
    tool, foundation = _setup(tmp_path, transport)
    assert _sync(
        tool, "mixed-chart", ("activity_details_fallback",),
    ).status == "partial"
    with sqlite3.connect(foundation.database_path) as conn:
        rows = conn.execute(
            """SELECT heart_rate_bpm,timestamp_utc,
                      json_extract(extras_json,'$.source_index')
               FROM activity_samples WHERE stream_kind='connect_chart'
               ORDER BY sample_index"""
        ).fetchall()
        assert rows[0] == (0.0, None, 1)
        assert rows[1][0] is None and rows[1][1] is not None and rows[1][2] == 3
        evidence = json.loads(conn.execute(
            """SELECT details_json FROM data_quality_issues
               WHERE issue_code='activity_chart_invalid_rows' AND status='open'"""
        ).fetchone()[0])
        assert (
            evidence["received_point_count"],
            evidence["valid_point_count"],
            evidence["dropped_point_count"],
            evidence["persisted_point_count"],
        ) == (4, 2, 2, 2)


def test_invalid_chart_correction_deactivates_old_fallback_without_deleting_history(
    tmp_path: Path,
) -> None:
    transport = L212Transport()
    transport.extras["details_json_fallback"] = {
        "activityId": 1,
        "points": [{"directHeartRate": 100}],
    }
    tool, foundation = _setup(tmp_path, transport)
    assert _sync(
        tool, "chart-valid-before-invalid", ("activity_details_fallback",),
    ).status == "partial"
    transport.extras["details_json_fallback"] = {
        "activityId": 1,
        "points": [{"newUnknown": "correction"}],
    }
    assert _sync(
        tool, "chart-invalid-correction", ("activity_details_fallback",),
    ).status == "partial"
    with sqlite3.connect(foundation.database_path) as conn:
        revisions = conn.execute(
            """SELECT revision_no,is_current,parsed_at_utc
               FROM source_revisions
               WHERE resource_kind='activity_details_fallback'
               ORDER BY revision_no"""
        ).fetchall()
        assert [(row[0], row[1]) for row in revisions] == [(1, 1), (2, 0)]
        assert revisions[0][2] is not None and revisions[1][2] is None
        assert conn.execute(
            """SELECT count(*) FROM activity_source_revisions
               WHERE source_role='details_json_fallback' AND is_active=1"""
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM activity_samples WHERE stream_kind='connect_chart'"
        ).fetchone()[0] == 1
        activity = conn.execute(
            "SELECT extras_json,source_map_json FROM activities"
        ).fetchone()
        assert "sensor_stream" not in json.loads(activity[1])
        assert json.loads(activity[0])["connect_chart"]["canonical"] is False


def test_typed_rows_drop_invalid_numeric_and_reversed_time_but_keep_valid_zero(
    tmp_path: Path,
) -> None:
    transport = L212Transport(sport="strength_training")
    transport.extras["exercise_sets_json"] = {
        "activityId": 1,
        "exerciseSets": [
            {"newUnknown": "x"},
            {"repetitions": 0, "weightKg": 0, "duration": 0},
            {"repetitions": True},
            {"weightKg": -1},
            {
                "startTimeGMT": "2026-07-19T01:00:00Z",
                "endTimeGMT": "2026-07-19T00:00:00Z",
            },
        ],
    }
    tool, foundation = _setup(tmp_path, transport)
    assert _sync(
        tool, "strict-set-rows", ("activity_exercise_sets",),
    ).status == "succeeded"
    with sqlite3.connect(foundation.database_path) as conn:
        assert conn.execute(
            """SELECT s.segment_index,x.repetitions,x.weight_kg,x.duration_seconds
               FROM activity_segments s JOIN strength_sets x ON x.segment_id=s.id"""
        ).fetchone() == (1, 0, 0.0, 0.0)
        evidence = json.loads(conn.execute(
            """SELECT details_json FROM data_quality_issues
               WHERE issue_code='activity_exercise_sets_drift' AND status='open'"""
        ).fetchone()[0])
        assert (
            evidence["received_row_count"],
            evidence["valid_row_count"],
            evidence["dropped_row_count"],
        ) == (5, 1, 4)
        assert evidence["drop_reasons"] == {
            "reviewed_field_invalid": 3,
            "unknown_only": 1,
        }


def test_bad_typed_split_binding_isolated_from_successful_weather(
    tmp_path: Path,
) -> None:
    transport = L212Transport(sport="bouldering")
    transport.extras["typed_splits_json"] = {
        "activityId": 999,
        "typedSplits": [{"gradeRaw": "6a"}],
    }
    tool, foundation = _setup(tmp_path, transport)
    result = _sync(
        tool, "binding-isolation",
        ("activity_typed_splits", "activity_weather"),
    )
    assert result.status == "partial"
    with sqlite3.connect(foundation.database_path) as conn:
        typed = conn.execute(
            """SELECT is_current,parsed_at_utc FROM source_revisions
               WHERE resource_kind='activity_typed_splits'"""
        ).fetchone()
        assert typed == (0, None)
        assert conn.execute(
            """SELECT count(*) FROM garmin_sync_gaps
               WHERE resource_kind='activity_typed_splits'
                 AND stage='project'"""
        ).fetchone()[0] == 1
        assert conn.execute(
            """SELECT count(*) FROM activity_segments s JOIN source_revisions sr
                 ON sr.id=s.source_revision_id
               WHERE sr.resource_kind='activity_typed_splits'"""
        ).fetchone()[0] == 0
        assert conn.execute(
            """SELECT count(*) FROM source_revisions
               WHERE resource_kind='activity_weather' AND is_current=1
                 AND parsed_at_utc IS NOT NULL"""
        ).fetchone()[0] == 1
        assert conn.execute(
            """SELECT count(*) FROM activity_source_revisions
               WHERE source_role='weather_json' AND is_active=1"""
        ).fetchone()[0] == 1


def test_valid_to_unknown_only_revision_removes_json_canonical_pointer_but_keeps_history(
    tmp_path: Path,
) -> None:
    transport = L212Transport(sport="bouldering")
    tool, foundation = _setup(tmp_path, transport)
    assert _sync(
        tool, "typed-valid", ("activity_typed_splits",),
    ).status == "succeeded"
    transport.extras["typed_splits_json"] = {
        "activityId": 1,
        "typedSplits": [{"newUnknown": "corrected-away"}],
    }
    assert _sync(
        tool, "typed-unknown-correction", ("activity_typed_splits",),
    ).status == "succeeded"
    with sqlite3.connect(foundation.database_path) as conn:
        revisions = conn.execute(
            """SELECT revision_no,is_current FROM source_revisions
               WHERE resource_kind='activity_typed_splits'
               ORDER BY revision_no"""
        ).fetchall()
        assert revisions == [(1, 0), (2, 1)]
        assert conn.execute(
            """SELECT count(*) FROM climbing_routes r JOIN activity_segments s
                 ON s.id=r.segment_id"""
        ).fetchone()[0] == 1
        active_revision = conn.execute(
            """SELECT sr.revision_no FROM activity_source_revisions ar
               JOIN source_revisions sr ON sr.id=ar.source_revision_id
               WHERE ar.source_role='typed_splits_json' AND ar.is_active=1"""
        ).fetchone()[0]
        assert active_revision == 2
        source_map = json.loads(conn.execute(
            "SELECT source_map_json FROM activities"
        ).fetchone()[0])
        assert "climbing_routes" not in source_map
        assert conn.execute(
            """SELECT count(*) FROM data_quality_issues
               WHERE issue_code='activity_typed_splits_drift' AND status='open'"""
        ).fetchone()[0] == 1


def test_unknown_only_json_correction_never_displaces_fit_canonical(
    tmp_path: Path,
) -> None:
    fit_path = FIT_PATH.parent / "Bouldering.fit"
    transport = L212Transport(sport="bouldering", fit=fit_path.read_bytes())
    transport.summary["startTimeGMT"] = _fit_start(fit_path)
    tool, foundation = _setup(tmp_path, transport)
    assert _sync(
        tool, "fit-and-json-valid", ("activity_fit", "activity_typed_splits"),
    ).status == "succeeded"
    transport.extras["typed_splits_json"] = {
        "activityId": 1,
        "typedSplits": [{"newUnknown": "x"}],
    }
    assert _sync(
        tool, "fit-and-json-unknown", ("activity_typed_splits",),
    ).status == "succeeded"
    with sqlite3.connect(foundation.database_path) as conn:
        source_map = json.loads(conn.execute(
            "SELECT source_map_json FROM activities"
        ).fetchone()[0])
        assert source_map["climbing_routes"]["source_role"] == "activity_fit"
