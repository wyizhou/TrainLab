"""VC-004: real FIT coordinates are admitted, never averaged or invented."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from jsonschema import ValidationError

SOURCE = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(SOURCE), str(SOURCE / "tests/code/fixtures")]
sys.path.insert(0, str(Path(__file__).parent))
fixture = importlib.import_module("m12_fit_factory")
fit_parse = importlib.import_module("skills._shared.fit_weekly.fit_parse")
storage = importlib.import_module("skills._shared.fit_weekly.storage")


def gps_record(t: int, latitude: float | None, longitude: float | None) -> bytes:
    extra = []
    for field, degrees in ((0, latitude), (1, longitude)):
        if degrees is not None:
            extra.append((field, 0x85, round(degrees * 2**31 / 180)))
    return fixture.record(t, t * 3, 123, extra=extra)


def project(records: list[bytes], end=240, *, version="fit-summary-2") -> dict:
    data = fixture.file_bytes(records + [fixture.session(end, timer=end)])
    return fit_parse.summarize(
        data, "101", storage.digest(data), parser_version=version
    )


def test_location_uses_actual_points_with_time_and_source_binding() -> None:
    result = project([gps_record(0, 12.5, 45.25), gps_record(10, 13.5, 46.25)])
    assert result["schema_version"] == "fit_activity_v2"
    assert result["activity_ref"] == "101" and len(result["fit_sha256"]) == 64
    location = result["sessions"][0]["summary"]["location"]
    assert location["source"] == "record.position_lat/position_long"
    assert location["coordinate_unit"] == "degrees"
    assert location["valid_point_count"] == 2
    assert location["first_latitude"] == pytest.approx(12.5, abs=1e-7)
    assert location["last_latitude"] == pytest.approx(13.5, abs=1e-7)
    assert location["first_longitude"] == pytest.approx(45.25, abs=1e-7)
    assert location["first_time_utc"] == result["start_utc"]
    assert location["last_time_utc"] != location["first_time_utc"]
    assert "latitude" not in result["sessions"][0]["summary"]["metrics"]
    assert result["provider_calls"] == 0


def test_adjacent_segments_count_boundary_point_exactly_once() -> None:
    result = project([gps_record(t, 10 + t / 100, 45) for t in (0, 120, 240)])
    summary = result["sessions"][0]["summary"]["location"]
    segments = result["sessions"][0]["segments"]
    assert summary["valid_point_count"] == 3
    assert [s["location"]["valid_point_count"] for s in segments] == [1, 2]
    assert (
        segments[0]["location"]["first_time_utc"]
        == segments[0]["location"]["last_time_utc"]
    )
    assert sum(s["location"]["valid_point_count"] for s in segments) == 3


@pytest.mark.parametrize("gap", [0, 5])
@pytest.mark.parametrize("boundary_kind", ["valid", "missing", "invalid"])
@pytest.mark.parametrize("view", ["summary", "laps", "series"])
@pytest.mark.parametrize("resolution", [1, 5])
def test_session_location_partition_is_lossless_across_views_and_replay(
    tmp_path: Path, gap: int, boundary_kind: str, view: str, resolution: int
) -> None:
    helpers = importlib.import_module("test_m12_fit_detail")
    detail = helpers.module()
    transport = importlib.import_module("skills._shared.fit_weekly.detail_transport")
    times = sorted({0, 5, 10, 10 + gap, 15 + gap, 20 + gap})
    records = []
    for t in times:
        latitude, longitude = 12 + t / 100, 45.0
        if t == 10 and boundary_kind == "missing":
            records.append(gps_record(t, None, None))
        else:
            if t == 10 and boundary_kind == "invalid":
                latitude = 91
            records.append(gps_record(t, latitude, longitude))
    # A genuine gap sample belongs to neither session, not to the last bin.
    if gap:
        records.append(gps_record(12, 70, 80))
    data = fixture.file_bytes(
        records
        + [fixture.lap(0, 10, 0), fixture.lap(10 + gap, 20 + gap, 1)]
        + [
            fixture.session(10, start=0, timer=10),
            fixture.session(20 + gap, start=10 + gap, timer=10),
        ]
    )
    sha = storage.digest(data)
    parsed = fit_parse.summarize(data, "101", sha, parser_version="fit-summary-2")
    total = parsed["location"]
    assert total["sample_count"] == len(times)
    assert total["valid_point_count"] == len(times) - (boundary_kind != "valid")
    assert total["missing_point_count"] == (boundary_kind == "missing")
    assert total["invalid_point_count"] == (boundary_kind == "invalid")
    for key in (
        "sample_count",
        "valid_point_count",
        "missing_point_count",
        "invalid_point_count",
    ):
        assert (
            sum(s["summary"]["location"][key] for s in parsed["sessions"]) == total[key]
        )
        for shape in ("laps", "segments"):
            assert (
                sum(b["location"][key] for s in parsed["sessions"] for b in s[shape])
                == total[key]
            )
    first = parsed["sessions"][0]["summary"]["location"]
    assert first["sample_count"] == (3 if gap else 2)
    if not gap:
        expected_last = datetime.fromisoformat(parsed["start_utc"]) + timedelta(
            seconds=5
        )
        assert first["last_time_utc"] == expected_last.isoformat().replace(
            "+00:00", "Z"
        )

    # Location ownership must not alter any original time-weighted sport result.
    legacy = fit_parse.summarize(data, "101", sha, parser_version="fit-summary-1")

    def without_location(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: without_location(v)
                for k, v in value.items()
                if k not in {"location", "schema_version", "parser_version"}
            }
        if isinstance(value, list):
            return [without_location(v) for v in value]
        return value

    assert without_location(parsed) == without_location(legacy)
    root, end, members = helpers.instance(tmp_path, data)
    scope = detail.freeze_scope(root, end, members, parser_version="fit-summary-2")
    host = detail.DetailHost(root, end, scope["scope_sha256"])
    req = helpers.request(
        view=view, end_offset_seconds=20 + gap, resolution_seconds=resolution
    )
    result = host.read(req)
    assert result["status"] == "available"
    for key in (
        "sample_count",
        "valid_point_count",
        "missing_point_count",
        "invalid_point_count",
    ):
        assert (
            sum(b["statistics"]["location"][key] for b in result["blocks"])
            == total[key]
        )
    assert transport.unpack(transport.pack(result)) == result
    before = (root / "trainlab-fit.db").read_bytes()
    assert host.read(req) == result
    assert (root / "trainlab-fit.db").read_bytes() == before
    assert host.usage()["requests"] == 1
    assert result["provider_calls"] == 0


@pytest.mark.parametrize("latitude,longitude", [(None, None), (91, 45), (12, None)])
def test_missing_or_invalid_gps_preserves_sport_statistics(latitude, longitude) -> None:
    result = project(
        [gps_record(0, latitude, longitude), gps_record(10, latitude, longitude)]
    )
    summary = result["sessions"][0]["summary"]
    loc = summary["location"]
    assert loc["valid_point_count"] == 0
    assert loc["first_latitude"] is None and loc["last_time_utc"] is None
    assert loc["status"] == (
        "missing" if latitude is longitude is None else "insufficient_data"
    )
    assert summary["metrics"]["heart_rate_bpm"]["mean"] == 123
    assert summary["distance_m"] == 30


def test_zero_and_negative_coordinates_are_not_missing() -> None:
    result = project([gps_record(0, 0, 0), gps_record(10, -12.25, -45.5)])
    loc = result["sessions"][0]["summary"]["location"]
    assert loc["first_latitude"] == loc["first_longitude"] == 0
    assert loc["last_latitude"] == pytest.approx(-12.25, abs=1e-7)
    assert loc["last_longitude"] == pytest.approx(-45.5, abs=1e-7)


def test_gps_only_duplicate_conflict_does_not_discard_activity_or_change_legacy() -> (
    None
):
    records = [gps_record(0, 12, 45), gps_record(0, 13, 46), gps_record(10, 14, 47)]
    old = project(records, version="fit-summary-1")
    new = project(records)
    assert "location" not in json.dumps(old)
    assert old["sessions"][0]["summary"]["sample_count"] == 2
    location = new["sessions"][0]["summary"]["location"]
    assert location["invalid_point_count"] == 1
    assert location["valid_point_count"] == 1
    assert location["first_latitude"] == pytest.approx(14, abs=1e-7)
    assert (
        new["sessions"][0]["summary"]["metrics"]
        == old["sessions"][0]["summary"]["metrics"]
    )


def test_legacy_projection_ignores_location_at_decode_not_only_output() -> None:
    records = [gps_record(0, 12, 45), gps_record(10, 13, 46)]
    old = project(records, version="fit-summary-1")
    plain = project(
        [fixture.record(0, 0, 123), fixture.record(10, 30, 123)],
        version="fit-summary-1",
    )
    old.pop("fit_sha256")
    plain.pop("fit_sha256")
    assert old == plain


def test_schema_rejects_unknown_parser_and_gps_fields() -> None:
    with pytest.raises(ValueError, match="fit_parser_version_invalid"):
        project([gps_record(0, 12, 45)], version="future-parser")
    result = project([gps_record(0, 12, 45)])
    result["sessions"][0]["summary"]["location"]["credential"] = "synthetic"
    with pytest.raises(ValidationError):
        fit_parse.validate(result)


def test_new_parse_is_append_only_and_legacy_can_be_replayed(tmp_path: Path) -> None:
    root = tmp_path / "instance"
    storage.initialize(root)
    data = fixture.file_bytes(
        [gps_record(0, 12, 45), gps_record(10, 13, 46), fixture.session(240, timer=240)]
    )
    original = tmp_path / "synthetic.fit"
    original.write_bytes(data)
    original.chmod(0o600)
    sha = storage.digest(data)
    with storage.open_store(root) as db:
        storage.import_fit(db, root, "101", original, sha)
        old = fit_parse.parse_registered(
            db, root, "101", sha, parser_version="fit-summary-1"
        )
        new = fit_parse.parse_registered(
            db, root, "101", sha, parser_version="fit-summary-2"
        )
        assert old["schema_version"] != new["schema_version"]
        count = db.execute("SELECT COUNT(*) FROM parses").fetchone()[0]
        assert (
            fit_parse.parse_registered(
                db, root, "101", sha, parser_version="fit-summary-1"
            )
            == old
        )
        assert db.execute("SELECT COUNT(*) FROM parses").fetchone()[0] == count == 2


def test_detail_v2_actual_point_windows_roundtrip_and_cached_budget(
    tmp_path: Path,
) -> None:
    helpers = importlib.import_module("test_m12_fit_detail")
    detail = helpers.module()
    transport = importlib.import_module("skills._shared.fit_weekly.detail_transport")
    data = fixture.file_bytes(
        [gps_record(t, 12 + t / 100, 45) for t in (0, 1, 5, 10)]
        + [fixture.session(10, timer=10)]
    )
    root, end, members = helpers.instance(tmp_path, data)
    scope = detail.freeze_scope(root, end, members, parser_version="fit-summary-2")
    host = detail.DetailHost(root, end, scope["scope_sha256"])
    req = helpers.request(end_offset_seconds=10)
    result = host.read(req)
    assert result["schema_version"] == "fit_detail_v2"
    assert (
        result["representation"] == "time_weighted_bins_with_actual_location_endpoints"
    )
    assert [
        b["statistics"]["location"]["valid_point_count"] for b in result["blocks"]
    ] == [2, 2]
    table = transport.pack(result)
    assert table["schema_version"] == "fit_detail_table_v2"
    assert transport.unpack(table) == result
    before = (root / "trainlab-fit.db").read_bytes()
    assert host.read(req) == result
    assert (root / "trainlab-fit.db").read_bytes() == before
    assert host.usage()["requests"] == 1


def test_location_missing_bins_have_same_lossless_column_shape(tmp_path: Path) -> None:
    helpers = importlib.import_module("test_m12_fit_detail")
    detail = helpers.module()
    transport = importlib.import_module("skills._shared.fit_weekly.detail_transport")
    data = fixture.file_bytes(
        [gps_record(0, 12, 45), gps_record(10, None, None)]
        + [fixture.session(10, timer=10)]
    )
    root, end, members = helpers.instance(tmp_path, data)
    scope = detail.freeze_scope(root, end, members, parser_version="fit-summary-2")
    result = detail.DetailHost(root, end, scope["scope_sha256"]).read(
        helpers.request(end_offset_seconds=10)
    )
    assert result["blocks"][1]["statistics"]["location"]["first_latitude"] is None
    assert transport.unpack(transport.pack(result)) == result


def test_saved_v1_scope_chooses_legacy_before_any_new_parse(
    tmp_path: Path, monkeypatch
) -> None:
    helpers = importlib.import_module("test_m12_fit_detail")
    detail = helpers.module()
    root, end, members = helpers.instance(tmp_path)
    scope = detail.freeze_scope(root, end, members, parser_version="fit-summary-1")
    host = detail.DetailHost(root, end, scope["scope_sha256"])
    cached = host.read(helpers.request())
    before = (root / "trainlab-fit.db").read_bytes()
    monkeypatch.setattr(fit_parse, "VERSION", "fit-summary-2")
    assert detail.freeze_scope(root, end, members) == scope
    assert host.read(helpers.request()) == cached
    assert (root / "trainlab-fit.db").read_bytes() == before
    with pytest.raises(ValueError, match="detail_scope_conflict"):
        detail.freeze_scope(root, end, members, parser_version="fit-summary-2")
    assert (root / "trainlab-fit.db").read_bytes() == before
    assert (
        host.read(helpers.request(end_offset_seconds=10))["schema_version"]
        == "fit_detail_v1"
    )
    assert host.usage()["requests"] == 2


def test_exhausted_legacy_budget_survives_upgrade_and_instance_move(
    tmp_path: Path, monkeypatch
) -> None:
    import shutil

    helpers = importlib.import_module("test_m12_fit_detail")
    detail = helpers.module()
    root, end, members = helpers.instance(tmp_path)
    scope = detail.freeze_scope(root, end, members, parser_version="fit-summary-1")
    host = detail.DetailHost(root, end, scope["scope_sha256"])
    first = None
    for offset in range(20):
        result = host.read(
            helpers.request(
                start_offset_seconds=offset,
                end_offset_seconds=offset + 1,
                resolution_seconds=1,
            )
        )
        assert result["schema_version"] == "fit_detail_v1"
        if offset == 0:
            first = result
    before = (root / "trainlab-fit.db").read_bytes()
    moved = tmp_path / "moved"
    shutil.move(str(root), moved)
    monkeypatch.setattr(fit_parse, "VERSION", "fit-summary-2")
    assert detail.freeze_scope(moved, end, members) == scope
    resumed = detail.DetailHost(moved, end, scope["scope_sha256"])
    assert (
        resumed.read(helpers.request(end_offset_seconds=1, resolution_seconds=1))
        == first
    )
    with pytest.raises(ValueError, match="detail_budget_exceeded"):
        resumed.read(
            helpers.request(
                start_offset_seconds=30, end_offset_seconds=31, resolution_seconds=1
            )
        )
    assert resumed.usage() == {"requests": 20, "max_requests": 20}
    assert (moved / "trainlab-fit.db").read_bytes() == before
