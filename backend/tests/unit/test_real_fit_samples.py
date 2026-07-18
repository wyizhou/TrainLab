import hashlib
from collections import Counter
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest

from trainlab.importers.fit import ParsedFitActivity, parse_fit_file

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REAL_FIT_DIRECTORY = REPOSITORY_ROOT / "data"


@dataclass(frozen=True)
class RealFitCase:
    filename: str
    sha256: str
    size_bytes: int
    profile: str
    record_count: int
    lap_count: int
    segment_count: int
    device_count: int
    metric_definition_count: int


REAL_FIT_CASES = (
    RealFitCase(
        filename="578824608_ACTIVITY.fit",
        sha256="847a8fda2ed5900d9f59181899466dcb93342ad0ad863fa74a0a33958e850d0b",
        size_bytes=132_789,
        profile="strength",
        record_count=1_924,
        lap_count=0,
        segment_count=121,
        device_count=5,
        metric_definition_count=24,
    ),
    RealFitCase(
        filename="600348741_ACTIVITY.fit",
        sha256="8383e51ddf57e4a7ca0852ce87b3523aa6e99d392a48aeb569c7af5b1d3f7289",
        size_bytes=619_292,
        profile="hike",
        record_count=4_072,
        lap_count=1,
        segment_count=0,
        device_count=7,
        metric_definition_count=53,
    ),
    RealFitCase(
        filename="616627608_ACTIVITY.fit",
        sha256="9d6d7020c5c40d785d1fdc9878dfdfe71c8a8364c829994e2d6fd8a00df93ef0",
        size_bytes=83_574,
        profile="boulder",
        record_count=2_011,
        lap_count=1,
        segment_count=44,
        device_count=5,
        metric_definition_count=36,
    ),
    RealFitCase(
        filename="616634193_ACTIVITY.fit",
        sha256="e4cf083d8015712aa7780167539835dc0739606641c8ae47204b0c8ab7edc675",
        size_bytes=58_193,
        profile="lead",
        record_count=1_370,
        lap_count=1,
        segment_count=12,
        device_count=5,
        metric_definition_count=40,
    ),
    RealFitCase(
        filename="617273913_ACTIVITY.fit",
        sha256="eb0d18ee9c7ee0f91ea1e397823b596c3fd2734ead2960f4f475801d0225bae9",
        size_bytes=270_427,
        profile="run",
        record_count=2_057,
        lap_count=8,
        segment_count=34,
        device_count=7,
        metric_definition_count=110,
    ),
)
CASES_BY_PROFILE = {case.profile: case for case in REAL_FIT_CASES}
UNKNOWN_CLIMB_FIELDS = frozenset({"69", "70", "71", "72", "73"})


def _fixture_path(case: RealFitCase) -> Path:
    path = REAL_FIT_DIRECTORY / case.filename
    if not path.is_file():
        pytest.fail(f"missing authorized FIT fixture: {case.filename}", pytrace=False)
    return path


@cache
def _parsed(case: RealFitCase) -> ParsedFitActivity:
    path = _fixture_path(case)
    return parse_fit_file(path, case.filename)


def test_real_fit_directory_matches_the_authorized_manifest() -> None:
    expected = {case.filename for case in REAL_FIT_CASES}
    actual = {path.name for path in REAL_FIT_DIRECTORY.glob("*.fit")}

    assert actual == expected


@pytest.mark.parametrize("case", REAL_FIT_CASES, ids=lambda case: case.profile)
def test_real_fit_manifest_and_parser_structure(case: RealFitCase) -> None:
    path = _fixture_path(case)
    payload = path.read_bytes()

    assert len(payload) == case.size_bytes
    assert hashlib.sha256(payload).hexdigest() == case.sha256

    parsed = _parsed(case)
    assert parsed.status == "complete"
    assert parsed.warning_count == 0
    assert parsed.profile == case.profile
    assert len(parsed.sessions) == 1
    assert len(parsed.records) == case.record_count
    assert len(parsed.laps) == case.lap_count
    assert len(parsed.segments) == case.segment_count
    assert len(parsed.devices) == case.device_count
    assert len(parsed.metric_definitions) == case.metric_definition_count


def test_real_strength_sample_keeps_set_only_training_structure() -> None:
    parsed = _parsed(CASES_BY_PROFILE["strength"])
    sources = Counter(segment.semantic["sourceMessage"] for segment in parsed.segments)
    sets = [segment for segment in parsed.segments if segment.semantic["sourceMessage"] == "set"]
    active_sets = [segment for segment in sets if segment.kind == "active"]
    rest_sets = [segment for segment in sets if segment.kind == "rest"]
    named_active_sets = [segment for segment in active_sets if "exercise" in segment.semantic]
    action_count = len({segment.semantic["exercise"]["name"] for segment in named_active_sets})

    assert sources == Counter({"set": 59, "split": 58, "split_summary": 4})
    assert len(sets) == 59
    assert len(active_sets) == 30
    assert len(rest_sets) == 29
    assert len(named_active_sets) == 30
    assert action_count == 10
    assert all("exercise" not in segment.semantic for segment in rest_sets)


@pytest.mark.parametrize(
    ("profile", "active_count", "rest_count", "unknown_field_union"),
    (
        pytest.param("boulder", 21, 21, {"69", "70", "71"}, id="boulder"),
        pytest.param("lead", 5, 5, {"69", "70", "71", "72", "73"}, id="lead"),
    ),
)
def test_real_climbing_samples_keep_split_instances_and_unknown_grades(
    profile: str,
    active_count: int,
    rest_count: int,
    unknown_field_union: set[str],
) -> None:
    parsed = _parsed(CASES_BY_PROFILE[profile])
    sources = Counter(segment.semantic["sourceMessage"] for segment in parsed.segments)
    splits = [
        segment for segment in parsed.segments if segment.semantic["sourceMessage"] == "split"
    ]
    summaries = [
        segment
        for segment in parsed.segments
        if segment.semantic["sourceMessage"] == "split_summary"
    ]
    active = [segment for segment in splits if segment.kind == "climb_active"]
    rest = [segment for segment in splits if segment.kind == "climb_rest"]

    assert sources == Counter({"split": active_count + rest_count, "split_summary": 2})
    assert len(active) == active_count
    assert len(rest) == rest_count
    assert len(summaries) == 2
    assert all(
        segment.semantic.get("climb")
        == {
            "gradeStatus": "unavailable",
            "gradeReason": "unknown_profile_field",
        }
        for segment in active
    )
    assert all("climb" not in segment.semantic for segment in rest + summaries)
    assert (
        set().union(*(set(segment.extra_data) & UNKNOWN_CLIMB_FIELDS for segment in active))
        == unknown_field_union
    )


def test_real_run_and_hike_keep_reliable_extension_structure() -> None:
    run = _parsed(CASES_BY_PROFILE["run"])
    hike = _parsed(CASES_BY_PROFILE["hike"])

    run_developer_definitions = sum(
        definition.stable_key.startswith("developer:") for definition in run.metric_definitions
    )
    run_native_definitions = sum(
        definition.stable_key.startswith("native:") for definition in run.metric_definitions
    )
    hike_developer_definitions = sum(
        definition.stable_key.startswith("developer:") for definition in hike.metric_definitions
    )
    hike_native_definitions = sum(
        definition.stable_key.startswith("native:") for definition in hike.metric_definitions
    )

    assert run_developer_definitions == 24
    assert run_native_definitions == 86
    assert hike_developer_definitions == 0
    assert hike_native_definitions == 53
    assert all(record.extra_metrics for record in run.records)
    assert all(record.extra_metrics for record in hike.records)
