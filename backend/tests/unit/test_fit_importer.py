import json
from collections import Counter
from pathlib import Path

import pytest

from trainlab.importers.fit import (
    _devices_from_snapshots,
    _extra_metrics,
    _semicircle_degrees,
    _text,
    _workout_step_name,
    parse_fit_file,
    parse_fit_segments,
)

FIT_FIXTURE = (
    Path(__file__).parents[3] / "frontend" / "tests" / "fixtures" / "614797758_ACTIVITY.fit"
)
SEMANTICS_FIXTURE = Path(__file__).parents[1] / "fixtures" / "fit_semantics_messages.json"


def test_safe_fit_text_never_stringifies_enums_or_dirty_values() -> None:
    assert _text("  动作\t甲\n") == "动作 甲"
    assert _text("e\u0301") == "é"
    assert _text(b"\xe5\x90\x88\xe6\x88\x90\x00\xe5\x8a\xa8\xe4\xbd\x9c") == "合成动作"
    assert _text(b"\xff") is None
    assert _text(23) is None
    assert _text(["pull_up", "weighted"]) is None
    assert _text({"name": "dirty"}) is None
    assert _workout_step_name(["合成动作丙", "", "dirty\x00bytes"]) == "合成动作丙"
    assert _workout_step_name([23, "动作"]) is None


def test_synthetic_segments_use_set_step_identity_and_keep_unknown_climb_fields() -> None:
    fixture = json.loads(SEMANTICS_FIXTURE.read_text(encoding="utf-8"))
    segments = parse_fit_segments(fixture["strength"])

    assert [item.extra_data["sourceMessage"] for item in segments] == [
        "set",
        "set",
        "set",
        "split",
        "split",
        "split_summary",
    ]
    assert [(item.kind, item.label) for item in segments[:3]] == [
        ("active", "合成动作甲"),
        ("rest", "休息"),
        ("active", "合成动作乙"),
    ]
    assert segments[0].semantic == {
        "schemaVersion": 1,
        "sourceMessage": "set",
        "exercise": {"stepIndex": 0, "name": "合成动作甲"},
    }
    assert segments[1].semantic == {"schemaVersion": 1, "sourceMessage": "set"}
    assert segments[2].weight_kg == 0
    assert all("exercise" not in item.semantic for item in segments[3:])
    rest_with_active_step = parse_fit_segments(
        {
            **fixture["strength"],
            "set_mesgs": [{"set_type": "rest", "wkt_step_index": 0}],
            "split_mesgs": [],
            "split_summary_mesgs": [],
        }
    )[0]
    assert rest_with_active_step.label == "休息"
    assert "exercise" not in rest_with_active_step.semantic

    climbing = parse_fit_segments(fixture["climbing"])
    assert climbing[0].semantic == {
        "schemaVersion": 1,
        "sourceMessage": "split",
        "climb": {
            "gradeStatus": "unavailable",
            "gradeReason": "unknown_profile_field",
        },
    }
    assert climbing[1].semantic == {"schemaVersion": 1, "sourceMessage": "split"}
    assert climbing[2].semantic == {
        "schemaVersion": 1,
        "sourceMessage": "split_summary",
    }
    assert {key: climbing[0].extra_data[key] for key in ("69", "70", "71", "72", "73")} == {
        "69": 8,
        "70": 1,
        "71": 3,
        "72": 0,
        "73": 1,
    }


def test_semicircles_are_converted_to_degrees() -> None:
    assert _semicircle_degrees(366001775, latitude=True) == pytest.approx(30.677914, abs=1e-6)
    assert _semicircle_degrees(1242067118, latitude=False) == pytest.approx(104.108863, abs=1e-6)
    assert _semicircle_degrees(2**31, latitude=True) is None


def test_safe_unknown_named_fields_are_preserved_with_stable_definitions() -> None:
    definitions = {}
    extras = _extra_metrics(
        "record",
        {
            "heart_rate": 150,
            "vertical_ratio": 8.2,
            "step_length": 1040,
            "position_lat": 123,
            "end_position_long": 456,
            "serial_number": 789,
            "notes": "private",
        },
        {"heart_rate", "position_lat"},
        definitions,
        {},
    )
    assert extras == {
        "native:record:vertical_ratio": 8.2,
        "native:record:step_length": 1040,
    }
    assert definitions["native:record:vertical_ratio"].field_name == "vertical_ratio"


def test_anonymous_same_model_devices_are_not_merged_without_a_stable_identity() -> None:
    snapshots = [
        {"manufacturer": "garmin", "product": "same-model", "source_type": "local"},
        {"manufacturer": "garmin", "product": "same-model", "source_type": "local"},
    ]
    anonymous = _devices_from_snapshots(snapshots)
    assert len(anonymous) == 2
    assert [item.raw_metadata["snapshotCount"] for item in anonymous] == [1, 1]

    identified = _devices_from_snapshots(
        [
            {**snapshots[0], "device_index": 3, "battery_level": 80},
            {**snapshots[1], "device_index": 3, "battery_level": 70},
        ]
    )
    assert len(identified) == 1
    assert identified[0].raw_metadata["snapshotCount"] == 2
    assert identified[0].battery_status == "70"


def test_official_sdk_parses_the_existing_fit_fixture_without_leaking_raw_identity() -> None:
    parsed = parse_fit_file(FIT_FIXTURE, "activity.fit")

    assert parsed.status == "complete"
    assert parsed.profile == "run"
    assert parsed.start_time_utc.isoformat() == "2026-07-08T22:41:56+00:00"
    assert parsed.local_start_time is not None
    assert parsed.local_start_time.isoformat() == "2026-07-09T06:41:56"
    assert parsed.utc_offset_minutes == 480
    assert len(parsed.records) == 1890
    assert len(parsed.laps) == 8
    assert parsed.records[0].position_lat == pytest.approx(30.677914, abs=1e-6)
    assert parsed.records[0].position_long == pytest.approx(104.108863, abs=1e-6)
    assert "native:record:vertical_ratio" in parsed.records[10].extra_metrics
    assert "native:record:step_length" in parsed.records[10].extra_metrics
    assert any(
        item.stable_key == "native:record:vertical_ratio" for item in parsed.metric_definitions
    )
    assert "native:lap:end_position_lat" not in parsed.laps[0].extra_metrics
    assert parsed.devices
    assert len(parsed.devices) == 8
    assert all(device.raw_metadata["snapshotCount"] == 4 for device in parsed.devices)
    assert all("serial_number" not in device.raw_metadata for device in parsed.devices)
    assert "developer:0:160:dr_s_distance" in parsed.extra_metrics
    assert parsed.extra_metrics["native:time_in_zone:session:time_in_hr_zone"] == pytest.approx(
        [68.49, 798.924, 1014.229, 4.915, 0.0]
    )
    assert parsed.sessions[0].summary["extra_metrics"][
        "native:time_in_zone:session:time_in_hr_zone"
    ] == pytest.approx([68.49, 798.924, 1014.229, 4.915, 0.0])
    assert "developer:unknown:0" not in parsed.extra_metrics
    assert any(item.stable_key.startswith("developer:0:") for item in parsed.metric_definitions)
    assert any(
        item.stable_key == "native:time_in_zone:session:time_in_hr_zone" and item.unit == "s"
        for item in parsed.metric_definitions
    )
    sources = Counter(item.extra_data["sourceMessage"] for item in parsed.segments)
    assert sources == {"split": 13, "split_summary": 6}
