from __future__ import annotations

import io

import fitdecode

from tests.fixtures.synthetic_fit import (
    SYNTHETIC_FIT_NAMES,
    SYNTHETIC_FIT_SHA256,
    SYNTHETIC_FITS,
    build_synthetic_fit,
)


def test_fixture_catalog_is_deterministic_and_contains_only_synthetic_names() -> None:
    assert SYNTHETIC_FIT_NAMES == (
        "Running.fit",
        "Bouldering.fit",
        "Indoor Climbing.fit",
        "Strength.fit",
        "Cycling.fit",
        "Hiking.fit",
    )
    for name in SYNTHETIC_FIT_NAMES:
        assert build_synthetic_fit(name) == SYNTHETIC_FITS[name]
        assert len(SYNTHETIC_FIT_SHA256[name]) == 64
        assert len(SYNTHETIC_FITS[name]) > 1_000


def test_every_fixture_has_valid_crc_records_and_one_session() -> None:
    expected = {
        "Running.fit": ("running", "generic"),
        "Bouldering.fit": ("rock_climbing", "bouldering"),
        "Indoor Climbing.fit": ("rock_climbing", "indoor_climbing"),
        "Strength.fit": ("training", "strength_training"),
        "Cycling.fit": ("cycling", "road"),
        "Hiking.fit": ("hiking", "generic"),
    }
    for name, payload in SYNTHETIC_FITS.items():
        sessions: list[dict[str, object]] = []
        record_count = 0
        lap_count = 0
        with fitdecode.FitReader(io.BytesIO(payload), check_crc=True) as reader:
            for frame in reader:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue
                if frame.name == "record":
                    record_count += 1
                elif frame.name == "lap":
                    lap_count += 1
                elif frame.name == "session":
                    sessions.append({field.name: field.value for field in frame.fields})
        assert record_count == 200
        assert lap_count == 1
        assert len(sessions) == 1
        assert (sessions[0]["sport"], sessions[0]["sub_sport"]) == expected[name]


def test_fixture_bytes_contain_no_private_source_markers() -> None:
    forbidden = (b"lucas", b"apple watch", b"workoutdoors", b"climbingpark")
    for payload in SYNTHETIC_FITS.values():
        lowered = payload.lower()
        assert all(marker not in lowered for marker in forbidden)
