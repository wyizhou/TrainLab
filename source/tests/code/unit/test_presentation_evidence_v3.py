from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

SOURCE = Path(__file__).resolve().parents[3]


def _load(name: str, relative: str) -> Any:
    path = SOURCE / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ACTIVITY = _load(
    "trainlab_activity_evidence_v3_test",
    "skills/training-coach/scripts/activity_evidence.py",
)
PARSE = _load(
    "trainlab_sleep_presentation_v3_test",
    "skills/training-coach/scripts/parse_raw.py",
)
PRESENTATION = _load(
    "trainlab_presentation_evidence_v3_test",
    "skills/training-coach/scripts/presentation_evidence.py",
)


class _Field:
    def __init__(self, name: str, value: object) -> None:
        self.name = name
        self.value = value


class _Frame:
    def __init__(self, name: str, **fields: object) -> None:
        self.name = name
        self.fields = [_Field(key, value) for key, value in fields.items()]


def _fit_reader(monkeypatch: pytest.MonkeyPatch, frames: list[_Frame]) -> None:
    class Reader:
        def __init__(self, _path: Path) -> None:
            self.frames = frames

        def __enter__(self) -> Reader:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def __iter__(self):
            return iter(self.frames)

    monkeypatch.setitem(sys.modules, "fitdecode", SimpleNamespace(FitReader=Reader))


def _records(*, heart_rate: int = 100) -> list[_Frame]:
    return [
        _Frame(
            "record",
            timestamp=datetime(2026, 8, 11, tzinfo=timezone.utc),
            distance=0,
            heart_rate=heart_rate,
        ),
        _Frame(
            "record",
            timestamp=datetime(2026, 8, 11, 0, 30, tzinfo=timezone.utc),
            distance=100,
            heart_rate=heart_rate + 1,
        ),
    ]


def _session_zones() -> _Frame:
    return _Frame(
        "time_in_zone",
        reference_mesg="session",
        reference_index=0,
        time_in_hr_zone=(120.0, 300.0, 180.0, 60.0, 30.0, 0.0, 0.0),
        hr_zone_high_boundary=(120, 140, 155, 170, 185, 200),
    )


def test_fit_uses_only_unique_session_zone_vector(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    frames = [
        *_records(),
        _Frame(
            "time_in_zone",
            reference_mesg="lap",
            reference_index=0,
            time_in_hr_zone=(1, 1, 1, 1, 1, 1, 1),
            hr_zone_high_boundary=(1, 2, 3, 4, 5, 6),
        ),
        _Frame(
            "time_in_zone",
            reference_mesg="split",
            reference_index=0,
            time_in_hr_zone=(2, 2, 2, 2, 2, 2, 2),
            hr_zone_high_boundary=(1, 2, 3, 4, 5, 6),
        ),
        _session_zones(),
    ]
    _fit_reader(monkeypatch, frames)
    path = tmp_path / "activity.fit"
    path.write_bytes(b"fit")
    _records_result, summary = ACTIVITY._fit_records(path)
    zones = summary["observed_heart_rate_zones"]
    assert zones["source"] == "fit_session_time_in_hr_zone"
    assert zones["durations_seconds"] == [120, 300, 180, 60, 30, 0, 0]
    assert zones["reference_mesg"] == "session"
    assert zones["reference_index"] == 0
    assert len(zones["definition_sha256"]) == 64


@pytest.mark.parametrize(
    "bad_vector",
    [
        (1, 2, 3),
        (1, 2, 3, 4, 5, 6, -1),
        (1, 2, 3, 4, 5, 6, float("nan")),
    ],
)
def test_fit_hides_invalid_or_duplicate_session_zones(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bad_vector: tuple[float, ...]
) -> None:
    bad = _Frame(
        "time_in_zone",
        reference_mesg="session",
        reference_index=0,
        time_in_hr_zone=bad_vector,
        hr_zone_high_boundary=(120, 140, 155, 170, 185, 200),
    )
    _fit_reader(monkeypatch, [*_records(), bad])
    path = tmp_path / "bad.fit"
    path.write_bytes(b"bad")
    _record_result, summary = ACTIVITY._fit_records(path)
    assert "observed_heart_rate_zones" not in summary

    _fit_reader(monkeypatch, [*_records(), _session_zones(), _session_zones()])
    _record_result, duplicate = ACTIVITY._fit_records(path)
    assert "observed_heart_rate_zones" not in duplicate


def test_fit_counts_every_session_zone_candidate_before_selecting_index_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    second_session = _Frame(
        "time_in_zone",
        reference_mesg="session",
        reference_index=1,
        time_in_hr_zone=(60, 120, 180, 240, 300, 0, 0),
        hr_zone_high_boundary=(120, 140, 155, 170, 185, 200),
    )
    path = tmp_path / "multiple-sessions.fit"
    path.write_bytes(b"fit")

    _fit_reader(monkeypatch, [*_records(), _session_zones(), second_session])
    _record_result, duplicate = ACTIVITY._fit_records(path)
    assert "observed_heart_rate_zones" not in duplicate

    _fit_reader(monkeypatch, [*_records(), second_session])
    _record_result, unsupported_index = ACTIVITY._fit_records(path)
    assert "observed_heart_rate_zones" not in unsupported_index


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_index",
        "none_index",
        "float_index",
        "string_index",
        "string_durations",
        "string_boundaries",
        "boolean_duration",
    ],
)
def test_fit_hides_noncanonical_session_zone_types(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    fields: dict[str, object] = {
        "reference_mesg": "session",
        "reference_index": 0,
        "time_in_hr_zone": (120, 300, 180, 60, 30, 0, 0),
        "hr_zone_high_boundary": (120, 140, 155, 170, 185, 200),
    }
    if mutation == "missing_index":
        fields.pop("reference_index")
    elif mutation == "none_index":
        fields["reference_index"] = None
    elif mutation == "float_index":
        fields["reference_index"] = 0.0
    elif mutation == "string_index":
        fields["reference_index"] = "0"
    elif mutation == "string_durations":
        fields["time_in_hr_zone"] = ("120", "300", "180", "60", "30", "0", "0")
    elif mutation == "string_boundaries":
        fields["hr_zone_high_boundary"] = (
            "120",
            "140",
            "155",
            "170",
            "185",
            "200",
        )
    else:
        fields["time_in_hr_zone"] = (120, 300, 180, 60, 30, False, 0)

    _fit_reader(monkeypatch, [*_records(), _Frame("time_in_zone", **fields)])
    path = tmp_path / f"{mutation}.fit"
    path.write_bytes(b"fit")
    _record_result, summary = ACTIVITY._fit_records(path)
    assert "observed_heart_rate_zones" not in summary


def test_fit_never_reclassifies_heart_rate_samples(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "same-zones.fit"
    path.write_bytes(b"same")
    results = []
    for heart_rate in (80, 220):
        _fit_reader(monkeypatch, [*_records(heart_rate=heart_rate), _session_zones()])
        _records_result, summary = ACTIVITY._fit_records(path)
        results.append(summary["observed_heart_rate_zones"])
    assert results[0] == results[1]


def test_fit_v4_preserves_explicit_lap_roles_and_running_dynamics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    frames = [
        _Frame(
            "record",
            timestamp=datetime(2026, 8, 11, tzinfo=timezone.utc),
            distance=0,
            heart_rate=130,
            cadence=168,
            power=210,
            step_length=1.02,
            stance_time=248,
            vertical_oscillation=82,
            vertical_ratio=8.1,
        ),
        _Frame(
            "lap",
            message_index=0,
            intensity="interval",
            total_elapsed_time=180,
            total_distance=800,
            avg_power=245,
            avg_cadence=172,
        ),
        _Frame(
            "lap",
            message_index=1,
            intensity="recovery",
            total_elapsed_time=120,
            total_distance=300,
        ),
        _Frame(
            "record",
            timestamp=datetime(2026, 8, 11, 0, 30, tzinfo=timezone.utc),
            distance=100,
            heart_rate=132,
            cadence=169,
            power=212,
            step_length=1.03,
            stance_time=247,
            vertical_oscillation=81,
            vertical_ratio=8.0,
        ),
    ]
    _fit_reader(monkeypatch, frames)
    path = tmp_path / "technical.fit"
    path.write_bytes(b"fit")
    records, summary = ACTIVITY._fit_records(path, include_technical=True)
    assert summary["technical_laps"][0]["lap_role"] == "work"
    assert summary["technical_laps"][1]["lap_role"] == "recovery"
    assert records[0]["step_length_m"] == 1.02
    assert records[0]["ground_contact_time_ms"] == 248
    assert records[0]["vertical_oscillation_mm"] == 82
    assert records[0]["vertical_ratio_pct"] == 8.1


def test_fit_v4_does_not_guess_unlabelled_active_lap_as_work(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    frames = [
        *_records(),
        _Frame(
            "lap",
            message_index=0,
            intensity="active",
            total_elapsed_time=180,
            total_distance=800,
        ),
    ]
    _fit_reader(monkeypatch, frames)
    path = tmp_path / "unlabelled.fit"
    path.write_bytes(b"fit")
    _records_result, summary = ACTIVITY._fit_records(path, include_technical=True)
    assert summary["technical_laps"][0]["lap_role"] == "unclassified"


def test_sleep_parser_preserves_named_stage_durations_and_timeline(
    tmp_path: Path,
) -> None:
    path = tmp_path / ("20260812-sleep-" + "a" * 64 + ".json")
    path.write_text(
        json.dumps(
            {
                "dailySleepDTO": {
                    "sleepStartTimestampGMT": "2026-08-11T16:00:00Z",
                    "sleepEndTimestampGMT": "2026-08-11T18:00:00Z",
                    "sleepTimeSeconds": 7200,
                    "deepSleepSeconds": 1800,
                    "lightSleepSeconds": 2700,
                    "remSleepSeconds": 1800,
                    "awakeSleepSeconds": 900,
                },
                "sleepLevels": [
                    {
                        "activityLevel": 0,
                        "startGMT": "2026-08-11T16:00:00Z",
                        "endGMT": "2026-08-11T16:30:00Z",
                    },
                    {
                        "activityLevel": 1,
                        "startGMT": "2026-08-11T16:30:00Z",
                        "endGMT": "2026-08-11T17:15:00Z",
                    },
                    {
                        "activityLevel": 2,
                        "startGMT": "2026-08-11T17:15:00Z",
                        "endGMT": "2026-08-11T17:45:00Z",
                    },
                    {
                        "activityLevel": 3,
                        "startGMT": "2026-08-11T17:45:00Z",
                        "endGMT": "2026-08-11T18:00:00Z",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    metrics = PARSE.parse_evidence(path)["metrics"]
    stages = metrics["sleep_stages"]
    assert stages["durations_seconds"] == {
        "deep": 1800,
        "light": 2700,
        "rem": 1800,
        "awake": 900,
    }
    assert [item["stage"] for item in stages["timeline"]] == [
        "deep",
        "light",
        "rem",
        "awake",
    ]


def test_sleep_stage_conflict_or_missing_fields_hides_stage_evidence(
    tmp_path: Path,
) -> None:
    for name, payload in {
        "conflict": {
            "dailySleepDTO": {
                "sleepStartTimestampGMT": "2026-08-11T16:00:00Z",
                "sleepEndTimestampGMT": "2026-08-11T18:00:00Z",
                "sleepTimeSeconds": 7200,
                "deepSleepSeconds": 100,
                "lightSleepSeconds": 100,
                "remSleepSeconds": 100,
                "awakeSleepSeconds": 100,
            },
            "sleepLevels": [
                {
                    "activityLevel": 0,
                    "startGMT": "2026-08-11T16:00:00Z",
                    "endGMT": "2026-08-11T18:00:00Z",
                }
            ],
        },
        "missing": {
            "dailySleepDTO": {
                "sleepStartTimestampGMT": "2026-08-11T16:00:00Z",
                "sleepEndTimestampGMT": "2026-08-11T18:00:00Z",
                "sleepTimeSeconds": 7200,
            }
        },
    }.items():
        path = tmp_path / f"20260812-sleep-{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        metrics = PARSE.parse_evidence(path)["metrics"]
        assert "sleep_stages" not in metrics


def test_presentation_zone_percentages_are_only_provider_duration_ratios() -> None:
    zones = PRESENTATION.presentation_heart_rate_zones(
        {
            "source": "fit_session_time_in_hr_zone",
            "reference_mesg": "session",
            "reference_index": 0,
            "durations_seconds": [60, 120, 180, 240, 0, 0, 0],
            "definition_sha256": "a" * 64,
        }
    )
    assert zones is not None
    assert zones["percentage_source"] == "derived_from_provider_duration"
    assert [item["percentage"] for item in zones["segments"]] == [
        10.0,
        20.0,
        30.0,
        40.0,
        0.0,
        0.0,
        0.0,
    ]
    assert hashlib.sha256(b"heart-rate-points").hexdigest() not in json.dumps(zones)


@pytest.mark.parametrize("reference_index", [False, 0.0])
def test_presentation_zones_require_native_integer_session_index(
    reference_index: object,
) -> None:
    zones = PRESENTATION.presentation_heart_rate_zones(
        {
            "source": "fit_session_time_in_hr_zone",
            "reference_mesg": "session",
            "reference_index": reference_index,
            "durations_seconds": [60, 120, 180, 240, 0, 0, 0],
            "definition_sha256": "a" * 64,
        }
    )

    assert zones is None
