from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[3]


def test_bounded_parser_handles_health_activity_formats_without_values(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    health = source_root / "state/raw/garmin/health"
    activities = source_root / "state/raw/garmin/activities"
    health.mkdir(parents=True)
    activities.mkdir(parents=True)
    prefix = "20260814"
    (health / f"{prefix}-sleep.json").write_text(
        json.dumps(
            {
                "dailySleepDTO": {
                    "sleepStartTimestampGMT": "2026-08-13T16:00:00.0",
                    "sleepEndTimestampGMT": "2026-08-14T00:00:00.0",
                    "sleepTimeSeconds": 28800,
                }
            }
        ),
        encoding="utf-8",
    )
    (activities / f"{prefix}-weather.json").write_text(
        json.dumps({"temperature": 24, "humidity": 70}), encoding="utf-8"
    )
    (activities / f"{prefix}-route.gpx").write_text(
        "<gpx version='1.1'><trk><trkseg>"
        "<trkpt lat='1' lon='2'><time>2026-08-14T00:00:00Z</time></trkpt>"
        "<trkpt lat='1.001' lon='2.001'><time>2026-08-14T00:00:30Z</time></trkpt>"
        "</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    (activities / f"{prefix}-route.tcx").write_text(
        "<TrainingCenterDatabase xmlns='http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2'>"
        "<Activities><Activity Sport='Running'/></Activities></TrainingCenterDatabase>",
        encoding="utf-8",
    )
    (activities / f"{prefix}-route.fit").write_bytes(b"synthetic-not-a-fit")
    result = subprocess.run(
        [
            sys.executable,
            str(SOURCE / "skills/training-coach/scripts/parse_raw.py"),
            "--source-root",
            str(source_root),
            "--date",
            "2026-08-14",
        ],
        cwd=SOURCE,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["raw_values_included"] is False
    parsers = {item["evidence"]["parser"] for item in payload["evidence"]}
    assert {"json", "gpx", "tcx", "fitdecode"}.issubset(parsers)
    assert any(
        item["evidence"].get("metrics", {}).get("duration_seconds") == 28800
        for item in payload["evidence"]
    )
    assert any(
        item["evidence"].get("metrics", {}).get("resource") == "activity_weather"
        for item in payload["evidence"]
    )
    gpx = next(
        item for item in payload["evidence"] if item["evidence"]["parser"] == "gpx"
    )
    assert gpx["evidence"]["metrics"]["distance_km"] > 0


def test_real_weather_suffix_maps_to_json_and_activity_weather(tmp_path: Path) -> None:
    module_spec = importlib.util.spec_from_file_location(
        "trainlab_index_raw",
        SOURCE / "skills/garmin-sync/scripts/index_raw.py",
    )
    assert module_spec and module_spec.loader
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    raw_root = tmp_path / "state/raw"
    activities = raw_root / "garmin/activities"
    activities.mkdir(parents=True)
    weather = activities / ("20260814-" + "a" * 64 + ".weather.json")
    weather.write_text(json.dumps({"temperature": 24}), encoding="utf-8")
    weather.chmod(0o600)
    metadata = module._metadata(weather, raw_root)
    assert metadata["file_format"] == "json"
    assert metadata["resource_kind"] == "activity_weather"


def test_garmin_nested_sleep_fields_are_complete_and_wake_day_is_hkt(
    tmp_path: Path,
) -> None:
    module_spec = importlib.util.spec_from_file_location(
        "trainlab_parse_sleep",
        SOURCE / "skills/training-coach/scripts/parse_raw.py",
    )
    assert module_spec and module_spec.loader
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    path = tmp_path / ("20260812-sleep-" + "a" * 64 + ".json")
    path.write_text(
        json.dumps(
            {
                "dailySleepDTO": {
                    "sleepStartTimestampGMT": "2026-08-11T16:30:40.0",
                    "sleepEndTimestampGMT": "2026-08-12T00:36:40.0",
                    "sleepTimeSeconds": 29160,
                }
            }
        ),
        encoding="utf-8",
    )
    evidence = module.parse_evidence(path)
    metrics = evidence["metrics"]
    assert metrics["completeness"] == "complete"
    assert metrics["sleep_wake_date"] == "2026-08-12"
    assert metrics["duration_seconds"] == 29160


def test_weight_parser_uses_exact_date_and_normalizes_grams(tmp_path: Path) -> None:
    module_spec = importlib.util.spec_from_file_location(
        "trainlab_parse_weight",
        SOURCE / "skills/training-coach/scripts/parse_raw.py",
    )
    assert module_spec and module_spec.loader
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    path = tmp_path / ("20260807-weigh_ins-" + "a" * 64 + ".json")
    path.write_text(
        json.dumps(
            {
                "previousDateWeight": {"calendarDate": "2026-08-06", "weight": 69000},
                "dailyWeightSummaries": [
                    {
                        "summaryDate": "2026-08-07",
                        "latestWeight": {"calendarDate": "2026-08-07", "weight": 70100},
                        "trend": {"weight": 99999},
                    },
                    {
                        "summaryDate": "2026-08-08",
                        "latestWeight": {"calendarDate": "2026-08-08", "weight": 72000},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    metrics = module.parse_evidence(path)["metrics"]
    assert metrics["weight"] == 70.1
    assert metrics["unit"] == "kg"


def test_vo2_parser_uses_only_the_expected_observation_date(tmp_path: Path) -> None:
    module_spec = importlib.util.spec_from_file_location(
        "trainlab_parse_vo2",
        SOURCE / "skills/training-coach/scripts/parse_raw.py",
    )
    assert module_spec and module_spec.loader
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    path = tmp_path / ("20260810-max_metrics-" + "a" * 64 + ".json")
    path.write_text(
        json.dumps(
            [
                {
                    "generic": {
                        "calendarDate": "2026-08-09",
                        "vo2MaxPreciseValue": 62.0,
                    }
                },
                {
                    "generic": {
                        "calendarDate": "2026-08-10",
                        "vo2MaxPreciseValue": 51.0,
                    }
                },
            ]
        ),
        encoding="utf-8",
    )
    metrics = module.parse_evidence(path)["metrics"]
    assert metrics["vo2_max"] == 51.0
    assert metrics["unit"] == "ml/kg/min"

    conflicting = tmp_path / ("20260811-max_metrics-" + "b" * 64 + ".json")
    conflicting.write_text(
        json.dumps({"generic": {"calendarDate": "2026-08-10", "vo2MaxValue": 51.0}}),
        encoding="utf-8",
    )
    conflicting_metrics = module.parse_evidence(conflicting)["metrics"]
    assert "vo2_max" not in conflicting_metrics


def test_fit_parser_emits_bounded_activity_metrics(monkeypatch, tmp_path: Path) -> None:
    class Field:
        def __init__(self, name: str, value: object) -> None:
            self.name = name
            self.value = value

    class Frame:
        def __init__(self, name: str, fields: list[Field]) -> None:
            self.name = name
            self.fields = fields

    class Reader:
        def __init__(self, _path: Path) -> None:
            self.frames = [
                Frame("record", [Field("distance", 5000), Field("heart_rate", 150)]),
                Frame(
                    "session",
                    [
                        Field("total_elapsed_time", 1800),
                        Field("avg_heart_rate", 145),
                        Field("max_heart_rate", 172),
                    ],
                ),
                Frame("sport", [Field("sport", "running")]),
                Frame("lap", []),
            ]

        def __enter__(self) -> "Reader":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def __iter__(self):
            return iter(self.frames)

    monkeypatch.setitem(sys.modules, "fitdecode", SimpleNamespace(FitReader=Reader))
    sys.path.insert(0, str(SOURCE))
    module_spec = importlib.util.spec_from_file_location(
        "trainlab_parse_raw", SOURCE / "skills/training-coach/scripts/parse_raw.py"
    )
    assert module_spec and module_spec.loader
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    path = tmp_path / "20260814-activity.fit"
    path.write_bytes(b"synthetic-fit")
    evidence = module.parse_evidence(path)
    assert evidence["parser"] == "fitdecode"
    metrics = evidence["metrics"]
    assert metrics["distance_km"] == 5
    assert metrics["duration_seconds"] == 1800
    assert metrics["activity_kind"] == "running"
    assert metrics["heart_rate_maximum"] == 172
    assert metrics["lap_count"] == 1


def test_recent_trend_compresses_structured_ai_daily_metrics(tmp_path: Path) -> None:
    state_spec = importlib.util.spec_from_file_location(
        "trainlab_state_for_trend", SOURCE / "skills/_shared/state.py"
    )
    assert state_spec and state_spec.loader
    state = importlib.util.module_from_spec(state_spec)
    state_spec.loader.exec_module(state)
    database = state.init_database(tmp_path / "state" / "trainlab.db")
    for day, sleep, rhr, hrv, distance in (
        ("2026-08-01", 8.0, 48, 76, 5.0),
        ("2026-08-02", 6.5, 52, 70, 0.0),
        ("2026-08-03", 6.0, 54, 68, 7.0),
    ):
        metrics = [
            {"name": "main_sleep_duration", "value": sleep, "unit": "hours"},
            {"name": "resting_heart_rate", "value": rhr, "unit": "bpm"},
            {"name": "last_night_average_hrv", "value": hrv, "unit": "ms"},
        ]
        if distance:
            metrics.append(
                {"name": "running_distance", "value": distance, "unit": "km"}
            )
        connection = state.connect(database)
        try:
            run_id = state.begin_run(
                connection,
                run_key=f"trend:{day}",
                workflow_key=f"daily:{day}",
                dedupe_key=f"trend:{day}",
                skill_name="training-coach",
                operation="daily_coach",
                trigger_kind="skill",
                input_manifest={"day": day},
            )
            content = {
                "status": "succeeded",
                "report_date": day,
                "bounded_metrics": metrics,
                "safety": "caution" if sleep < 7 else "ready",
            }
            state.append_output(
                connection,
                skill_run_id=run_id,
                output_kind="daily_summary",
                logical_key=f"daily:{day}:summary",
                schema_name="daily_ai_result_v1",
                schema_version="1",
                content_json=content,
                content_text=json.dumps(content, sort_keys=True),
                period_start_date=day,
                period_end_date=day,
            )
            state.finish_run(connection, run_id, status="succeeded")
        finally:
            connection.close()
    context_spec = importlib.util.spec_from_file_location(
        "trainlab_context_for_trend",
        SOURCE / "skills/training-coach/scripts/build_context.py",
    )
    assert context_spec and context_spec.loader
    context = importlib.util.module_from_spec(context_spec)
    context_spec.loader.exec_module(context)
    trend = context._recent_trend(database, date(2026, 8, 4))
    assert trend["days_available"] == 3
    assert trend["sleep"]["average_hours"] == 6.83
    assert trend["sleep"]["insufficient_days"] == 2
    assert trend["recovery"]["rhr_change"] == 6.0
    assert trend["recovery"]["hrv_change"] == -8.0
    assert trend["running"] == {
        "distance_km": 12.0,
        "activity_count": 2,
        "activity_days": 2,
    }
