from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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
        json.dumps({"sleep": {"duration": 28800}}), encoding="utf-8"
    )
    (activities / f"{prefix}-weather.json").write_text(
        json.dumps({"temperature": 24, "humidity": 70}), encoding="utf-8"
    )
    (activities / f"{prefix}-route.gpx").write_text(
        "<gpx version='1.1'><trk><trkseg><trkpt lat='1' lon='2'/></trkseg></trk></gpx>",
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
        item["evidence"].get("metrics", {}).get("resource") == "weather"
        for item in payload["evidence"]
    )


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
