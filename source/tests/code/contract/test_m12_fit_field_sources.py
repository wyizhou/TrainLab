"""FIT-FIELD-SOURCE-001: original values, legal components and frozen replay."""

from __future__ import annotations

import base64
import importlib
import json
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))
fit_parse = importlib.import_module("skills._shared.fit_weekly.fit_parse")
fit_detail = importlib.import_module("skills._shared.fit_weekly.fit_detail")
storage = importlib.import_module("skills._shared.fit_weekly.storage")
FIXTURE = json.loads(
    (SOURCE / "tests/code/fixtures/m12_fit_field_sources.json").read_text()
)
CASES = FIXTURE["cases"]
REQUEST = FIXTURE["request"]


def data_for(case):
    data = base64.b64decode(case["fit_base64"], validate=True)
    assert storage.digest(data) == case["fit_sha256"]
    return data


def assert_value(actual, expected):
    if expected is None:
        assert actual is None
    else:
        assert actual == pytest.approx(expected, abs=1e-12, rel=0)


def assert_points(actual, expected):
    assert len(actual) == len(expected) == 3
    for point, sample in zip(actual, expected):
        assert_value(point.distance, sample["distance"])
        assert set(point.metrics) == set(sample["metrics"])
        for name, value in sample["metrics"].items():
            assert_value(point.metrics[name], value)


def assert_statistics(actual, points):
    assert actual["elapsed_seconds"] == actual["valid_seconds"] == 20
    assert actual["sample_covered_seconds"] == 20
    assert actual["sample_count"] == 3
    distance = (
        points[-1]["distance"] - points[0]["distance"]
        if all(p["distance"] is not None for p in points)
        else None
    )
    assert_value(actual["distance_m"], distance)
    assert actual["distance_covered_seconds"] == (20 if distance is not None else 0)
    assert_value(actual["pace_seconds_per_km"], 20000 / distance if distance else None)
    for name in points[0]["metrics"]:
        values = [p["metrics"][name] for p in points[:2]]
        values = [v for v in values if v is not None]
        metric = actual["metrics"][name]
        assert metric["covered_seconds"] == 10 * len(values)
        assert_value(metric["mean"], sum(values) / len(values) if values else None)
        assert_value(metric["min"], min(values, default=None))
        assert_value(metric["max"], max(values, default=None))


def register(tmp_path, data):
    root = tmp_path / "instance"
    storage.initialize(root)
    source = tmp_path / "anonymous.fit"
    source.write_bytes(data)
    source.chmod(0o600)
    sha = storage.digest(data)
    with storage.open_store(root) as db:
        storage.import_fit(db, root, "101", source, sha)
    return root, [{"activity_ref": "101", "fit_sha256": sha}]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_v3_original_and_component_values_decode(case):
    assert_points(fit_parse.decode(data_for(case)).points, case["expected_points"])


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_v3_original_values_reach_summary_and_detail_host(tmp_path, case):
    data = data_for(case)
    summary = fit_parse.summarize(data, "101", case["fit_sha256"])
    assert_statistics(summary["sessions"][0]["summary"], case["expected_points"])
    blocks = fit_detail.extract(data, REQUEST)
    assert len(blocks) == 1
    assert_statistics(blocks[0]["statistics"], case["expected_points"])
    root, members = register(tmp_path, data)
    end = "2026-09-06T07:00:00Z"
    scope = fit_detail.freeze_scope(root, end, members)
    host = fit_detail.DetailHost(root, end, scope["scope_sha256"])
    result = host.read(REQUEST)
    assert result["status"] == "available"
    assert result["blocks"] == blocks
    assert host.read(REQUEST) == result
    assert host.usage()["requests"] == 1


@pytest.mark.parametrize("version", ["fit-summary-1", "fit-summary-2"])
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_v1_v2_source_selection_and_uncached_host_replay_exactly(
    tmp_path, case, version
):
    data = data_for(case)
    expected = case["legacy"][version]
    assert_points(
        fit_parse.decode(data, parser_version=version).points, expected["points"]
    )
    summary = fit_parse.summarize(
        data, "101", case["fit_sha256"], parser_version=version
    )
    assert (
        storage.digest(storage.canonical(summary).encode())
        == expected["summary_sha256"]
    )
    blocks = fit_detail.extract(data, REQUEST, version)
    assert (
        storage.digest(storage.canonical(blocks).encode())
        == expected["uncached_detail_sha256"]
    )
    root, members = register(tmp_path, data)
    end = "2026-09-06T07:00:00Z"
    scope = fit_detail.freeze_scope(root, end, members, parser_version=version)
    host = fit_detail.DetailHost(root, end, scope["scope_sha256"])
    assert host.usage()["requests"] == 0
    result = host.read(REQUEST)
    assert result["blocks"] == blocks
    assert host.read(REQUEST) == result
    assert host.usage()["requests"] == 1
