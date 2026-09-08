from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))
sys.path.insert(0, str(SOURCE / "tests/code/fixtures"))
fixture = importlib.import_module("m12_fit_factory")


def module():
    return importlib.import_module("skills._shared.fit_weekly.fit_parse")


def parse(data: bytes) -> dict:
    from skills._shared.fit_weekly.storage import digest

    return module().summarize(data, "101", digest(data))


def test_real_fit_unknown_running_uses_two_minute_segments() -> None:
    result = parse(fixture.regular_fit())
    s = result["sessions"][0]
    assert s["sport"] == "running"
    assert s["running_kind"] == "unknown"
    assert [b["elapsed_seconds"] for b in s["segments"]] == [120] * 3
    assert s["elapsed_seconds"] == s["valid_seconds"] == 360
    assert s["summary"]["distance_m"] == 1080
    assert s["summary"]["pace_seconds_per_km"] == pytest.approx(1000 / 3)


@pytest.mark.parametrize("sport", [4, 10, 11, 17, 31])
def test_other_sports_use_five_minutes(sport: int) -> None:
    s = parse(fixture.regular_fit(600, sport=sport))["sessions"][0]
    assert [b["elapsed_seconds"] for b in s["segments"]] == [300, 300]


def test_explicit_interval_work_and_recovery_laps_stay_separate() -> None:
    laps = [
        fixture.lap(0, 60, 2),
        fixture.lap(60, 180, 5),
        fixture.lap(180, 240, 4),
        fixture.lap(240, 300, 5),
        fixture.lap(300, 360, 3),
    ]
    s = parse(fixture.regular_fit(laps=laps))["sessions"][0]
    assert s["running_kind"] == "sos_intervals"
    assert [b["role"] for b in s["segments"]] == [
        "warmup",
        "work",
        "recovery",
        "work",
        "cooldown",
    ]
    assert [b["elapsed_seconds"] for b in s["segments"]] == [60, 120, 60, 60, 60]


def test_continuous_explicit_work_is_one_minute_and_active_is_not_guessed() -> None:
    laps = [fixture.lap(0, 60, 2), fixture.lap(60, 300, 5), fixture.lap(300, 360, 3)]
    s = parse(fixture.regular_fit(laps=laps))["sessions"][0]
    assert s["running_kind"] == "sos_continuous"
    assert len([b for b in s["segments"] if b["role"] == "work"]) == 4
    laps[1] = fixture.lap(60, 300, 0)
    assert (
        parse(fixture.regular_fit(laps=laps))["sessions"][0]["running_kind"]
        == "unknown"
    )


def test_time_weighted_mean_not_sample_average_and_distance_based_pace() -> None:
    data = fixture.file_bytes(
        [
            fixture.record(0, 0, 100),
            fixture.record(1, 3, 180),
            fixture.record(10, 30, 140),
            fixture.session(10, timer=10),
        ]
    )
    m = parse(data)["sessions"][0]["summary"]
    assert m["metrics"]["heart_rate_bpm"]["mean"] == 172
    assert m["metrics"]["heart_rate_bpm"]["covered_seconds"] == 10
    assert m["pace_seconds_per_km"] == pytest.approx(1000 / 3)


def test_pause_is_excluded_from_metrics_and_distance() -> None:
    records = [
        fixture.record(t, t * 2, 210 if 10 <= t < 30 else 110) for t in range(0, 41, 10)
    ]
    data = fixture.file_bytes(
        records
        + [
            fixture.event(0, 0),
            fixture.event(10, 1),
            fixture.event(30, 0),
            fixture.event(40, 1),
            fixture.session(40, timer=20),
        ]
    )
    s = parse(data)["sessions"][0]
    assert s["valid_seconds"] == 20 and s["pause_seconds"] == 20
    assert s["summary"]["metrics"]["heart_rate_bpm"]["mean"] == 110
    assert s["summary"]["distance_m"] == 40


def test_missing_pause_location_does_not_invent_active_time() -> None:
    data = fixture.file_bytes(
        [
            fixture.record(0, 0, 120),
            fixture.record(20, 50, 120),
            fixture.session(20, timer=10),
        ]
    )
    s = parse(data)["sessions"][0]
    assert s["valid_seconds"] is None and s["pause_seconds"] is None
    assert s["summary"]["distance_m"] is None
    assert "timer_boundaries_unavailable" in s["limitations"]


def test_large_sample_gap_is_not_filled_or_averaged() -> None:
    data = fixture.file_bytes(
        [
            fixture.record(0, 0, 100),
            fixture.record(10, 20, 140),
            fixture.record(100, 250, 220),
            fixture.record(110, 280, 160),
            fixture.session(110, timer=110),
        ]
    )
    s = parse(data)["sessions"][0]
    assert s["sample_covered_seconds"] == 20 and s["gap_seconds"] == 90
    assert s["summary"]["metrics"]["heart_rate_bpm"]["mean"] == 160
    assert s["summary"]["distance_m"] == 50


def test_missing_and_reset_distance_never_invent_pace() -> None:
    data = fixture.file_bytes(
        [
            fixture.record(0, 50, 123),
            fixture.record(10, 20, 123),
            fixture.session(10, timer=10),
        ]
    )
    s = parse(data)["sessions"][0]
    assert s["summary"]["distance_m"] is None
    assert s["summary"]["pace_seconds_per_km"] is None
    assert "distance_reset_or_missing" in s["limitations"]


def test_lap_zone_durations_cannot_substitute_for_session() -> None:
    assert (
        parse(fixture.regular_fit(extras=[fixture.zones(19, [10, 20])]))["sessions"][0][
            "hr_zones"
        ]
        is None
    )
    result = parse(fixture.regular_fit(extras=[fixture.zones(18, [0, 60, 120, 180])]))
    z = result["sessions"][0]["hr_zones"]
    assert z["durations_seconds"] == [0, 60, 120, 180]
    assert z["percentages"] == pytest.approx([0, 100 / 6, 100 / 3, 50])
    assert z["derivation"] == "derived_from_provider_duration"
    assert z["fit_sha256"] == result["fit_sha256"] and z["activity_ref"] == "101"


@pytest.mark.parametrize("case", ["duplicate", "wrong_session", "too_long", "all_zero"])
def test_invalid_zone_data_is_hidden_not_rebuilt_from_hr(case: str) -> None:
    extras = [fixture.zones(18, [120, 240])]
    if case == "duplicate":
        extras *= 2
    if case == "wrong_session":
        extras = [fixture.zones(18, [120, 240], index=7)]
    if case == "too_long":
        extras = [fixture.zones(18, [600, 600])]
    if case == "all_zero":
        extras = [fixture.zones(18, [0, 0])]
    assert parse(fixture.regular_fit(extras=extras))["sessions"][0]["hr_zones"] is None


def test_no_zones_without_provider_arrays_and_raw_private_fields_are_removed() -> None:
    data = fixture.file_bytes(
        [
            fixture.record(0, 0, 120, extra=[(0, 0x85, 1234567), (1, 0x85, 2345678)]),
            fixture.record(10, 30, 120),
            fixture.message(26, [(8, 7, "Private Route owner@example.com")]),
            fixture.session(10, timer=10),
        ]
    )
    text = json.dumps(parse(data))
    for forbidden in [
        "Private Route",
        "owner@example.com",
        "87654321",
        "serial_number",
    ]:
        assert forbidden not in text
    assert parse(data)["sessions"][0]["hr_zones"] is None
    location = parse(data)["location"]
    assert location["valid_point_count"] == 1
    assert location["first_latitude"] == pytest.approx(1234567 * 180 / 2**31)


def test_running_dynamics_units_follow_decoded_fit_profile() -> None:
    extra = [(85, 0x84, 9870), (39, 0x84, 720), (41, 0x84, 2430)]
    data = fixture.file_bytes(
        [
            fixture.record(0, 0, 120, extra=extra),
            fixture.record(10, 30, 120),
            fixture.session(10, timer=10),
        ]
    )
    metrics = parse(data)["sessions"][0]["summary"]["metrics"]
    assert metrics["step_length_mm"]["mean"] == 987
    assert metrics["vertical_oscillation_mm"]["mean"] == 72
    assert metrics["stance_time_ms"]["mean"] == 243


def test_conflicting_timestamps_and_overlapping_sessions_rejected() -> None:
    data = fixture.file_bytes(
        [
            fixture.record(0, 0, 120),
            fixture.record(0, 0, 150),
            fixture.session(10, timer=10),
        ]
    )
    with pytest.raises(ValueError, match="fit_record_time_conflict"):
        parse(data)
    with pytest.raises(ValueError, match="fit_session_overlap"):
        parse(
            fixture.file_bytes(
                [fixture.session(20, timer=20), fixture.session(30, start=10, timer=20)]
            )
        )


def test_multisport_sessions_and_laps_are_not_mixed() -> None:
    data = fixture.file_bytes(
        [fixture.record(t, t * 3, 120) for t in range(0, 121, 10)]
        + [
            fixture.lap(0, 60, 5),
            fixture.session(60, timer=60),
            fixture.session(120, start=60, sport=2, timer=60),
        ]
    )
    s = parse(data)["sessions"]
    assert [i["sport"] for i in s] == ["running", "cycling"]
    assert [len(i["laps"]) for i in s] == [1, 0]


def test_registered_parse_is_immutable_and_relocatable(tmp_path: Path) -> None:
    from skills._shared.fit_weekly import storage

    root = tmp_path / "instance"
    storage.initialize(root)
    original = tmp_path / "input.fit"
    data = fixture.regular_fit()
    original.write_bytes(data)
    original.chmod(0o600)
    sha = storage.digest(data)
    with storage.open_store(root) as db:
        storage.import_fit(db, root, "101", original, sha)
        first = module().parse_registered(db, root, "101", sha)
        assert db.execute("SELECT COUNT(*) FROM parses").fetchone()[0] == 1
    before = (root / "trainlab-fit.db").read_bytes()
    moved = tmp_path / "moved"
    root.rename(moved)
    original.unlink()
    with storage.open_store(moved) as db:
        assert module().parse_registered(db, moved, "101", sha) == first
        assert db.execute("SELECT COUNT(*) FROM parses").fetchone()[0] == 1
        with pytest.raises(ValueError, match="fit_parse_binding_invalid"):
            module().parse_registered(db, moved, "202", sha)
    assert (moved / "trainlab-fit.db").read_bytes() == before
    assert "records" not in json.dumps(first)


def test_sha_and_crc_fail_before_parse_or_database(tmp_path: Path) -> None:
    data = fixture.regular_fit()
    with pytest.raises(ValueError, match="fit_sha_mismatch"):
        module().summarize(data, "101", "0" * 64)
    with pytest.raises(ValueError, match="fit_invalid"):
        parse(data[:-1] + bytes([data[-1] ^ 255]))


def test_pause_crossing_distance_is_not_spread_over_active_seconds() -> None:
    data = fixture.file_bytes(
        [
            fixture.record(0, 0, 120),
            fixture.record(30, 90, 120),
            fixture.event(0, 0),
            fixture.event(10, 1),
            fixture.event(20, 0),
            fixture.session(30, timer=20),
        ]
    )
    s = parse(data)["sessions"][0]
    assert s["valid_seconds"] == 20
    assert s["summary"]["distance_m"] is None
    assert s["summary"]["pace_seconds_per_km"] is None
    assert "distance_reset_or_missing" in s["limitations"]


def test_boundary_interpolation_preserves_full_distance_and_weight() -> None:
    data = fixture.file_bytes(
        [
            fixture.record(0, 0, 100),
            fixture.record(30, 90, 100),
            fixture.record(60, 180, 100),
            fixture.record(90, 270, 100),
            fixture.record(115, 345, 120),
            fixture.record(125, 375, 180),
            fixture.record(130, 390, 100),
            fixture.session(130, timer=130),
        ]
    )
    s = parse(data)["sessions"][0]
    assert s["summary"]["sample_count"] == 7
    assert sum(b["distance_m"] for b in s["segments"]) == 390
    assert [b["distance_m"] for b in s["segments"]] == [360, 30]
    assert s["segments"][1]["metrics"]["heart_rate_bpm"]["mean"] == 150


@pytest.mark.parametrize("case", ["missing", "duplicate", "total_conflict"])
def test_incomplete_or_conflicting_timer_never_infers_pauses(case: str) -> None:
    events = [fixture.event(10, 1)]
    timer = 10
    if case == "duplicate":
        events = [fixture.event(0, 0), fixture.event(5, 0), fixture.event(10, 1)]
    if case == "total_conflict":
        events = [fixture.event(0, 0), fixture.event(20, 1)]
    data = fixture.file_bytes(
        [fixture.record(0, 0, 120), fixture.record(20, 40, 120)]
        + events
        + [fixture.session(20, timer=timer)]
    )
    s = parse(data)["sessions"][0]
    assert s["valid_seconds"] is None
    assert s["summary"]["metrics"]["heart_rate_bpm"]["mean"] is None


def test_duplicate_laps_or_cross_session_lap_cannot_classify_sos() -> None:
    lap = fixture.lap(0, 360, 5)
    s = parse(fixture.regular_fit(laps=[lap, lap]))["sessions"][0]
    assert s["running_kind"] == "unknown"
    assert s["laps"] == [] and "laps_conflicting" in s["limitations"]
    data = fixture.file_bytes(
        [
            fixture.lap(0, 100, 5),
            fixture.session(60, timer=60),
            fixture.session(120, start=60, timer=60),
        ]
    )
    assert all(s["laps"] == [] for s in parse(data)["sessions"])


def test_duplicate_identical_records_are_reused_not_double_weighted() -> None:
    r = fixture.record(0, 0, 111)
    data = fixture.file_bytes(
        [r, r, fixture.record(10, 20, 111), fixture.session(10, timer=10)]
    )
    m = parse(data)["sessions"][0]["summary"]
    assert m["sample_count"] == 2
    assert m["metrics"]["heart_rate_bpm"]["covered_seconds"] == 10


def test_provider_totals_preserved_separately_when_series_unavailable() -> None:
    data = fixture.file_bytes(
        [
            fixture.message(
                18,
                [
                    (2, 0x86, fixture.BASE),
                    (253, 0x86, fixture.BASE + 600),
                    (5, 0, 1),
                    (9, 0x86, 432100),
                    (8, 0x86, 500000),
                    (16, 2, 134),
                    (17, 2, 167),
                ],
            )
        ]
    )
    s = parse(data)["sessions"][0]
    assert s["provider_summary"]["distance_m"] == 4321
    assert s["provider_summary"]["avg_heart_rate_bpm"] == 134
    assert s["provider_summary"]["max_heart_rate_bpm"] == 167
    assert s["summary"]["distance_m"] is None
    assert s["summary"]["sample_count"] == 0


def test_missing_metric_samples_have_independent_coverage() -> None:
    data = fixture.file_bytes(
        [
            fixture.record(0, 0, 100),
            fixture.record(10, 20, 255),
            fixture.record(20, 40, 180),
            fixture.session(20, timer=20),
        ]
    )
    m = parse(data)["sessions"][0]["summary"]["metrics"]
    assert m["heart_rate_bpm"]["mean"] == 100
    assert m["heart_rate_bpm"]["covered_seconds"] == 10
    assert m["power_w"]["mean"] is None and m["power_w"]["covered_seconds"] == 0


def test_schema_is_closed_and_forbids_private_extra_fields() -> None:
    import jsonschema

    result = parse(fixture.regular_fit())
    result["sessions"][0]["summary"]["metrics"]["heart_rate_bpm"]["raw_path"] = (
        "/private/example.fit"
    )
    with pytest.raises(jsonschema.ValidationError):
        module().validate(result)


def test_corrupted_registered_fit_never_publishes_parse(tmp_path: Path) -> None:
    from skills._shared.fit_weekly import storage

    root = tmp_path / "instance"
    storage.initialize(root)
    original = tmp_path / "input.fit"
    data = fixture.regular_fit()
    original.write_bytes(data)
    original.chmod(0o600)
    sha = storage.digest(data)
    with storage.open_store(root) as db:
        relative = storage.import_fit(db, root, "101", original, sha)
    (root / relative).write_bytes(data[:-1] + bytes([data[-1] ^ 255]))
    with storage.open_store(root) as db:
        with pytest.raises(ValueError, match="fit_sha_mismatch"):
            module().parse_registered(db, root, "101", sha)
        assert db.execute("SELECT COUNT(*) FROM parses").fetchone()[0] == 0


def test_registered_parse_sql_failure_rolls_back_and_replays(
    tmp_path: Path, monkeypatch
) -> None:
    from skills._shared.fit_weekly import storage

    root = tmp_path / "instance"
    storage.initialize(root)
    original = tmp_path / "input.fit"
    data = fixture.regular_fit()
    original.write_bytes(data)
    original.chmod(0o600)
    sha = storage.digest(data)
    with storage.open_store(root) as db:
        storage.import_fit(db, root, "101", original, sha)
    put = storage.put_parse

    def failed(*args):
        put(*args)
        raise OSError("synthetic interrupted commit")

    with monkeypatch.context() as m:
        m.setattr(storage, "put_parse", failed)
        with pytest.raises(OSError):
            with storage.open_store(root) as db:
                module().parse_registered(db, root, "101", sha)
    with storage.open_store(root) as db:
        assert db.execute("SELECT COUNT(*) FROM parses").fetchone()[0] == 0
        first = module().parse_registered(db, root, "101", sha)
        assert module().parse_registered(db, root, "101", sha) == first
        assert db.execute("SELECT COUNT(*) FROM parses").fetchone()[0] == 1


def test_duplicate_session_index_cannot_reuse_one_zone_vector() -> None:
    def indexed(start, end):
        return fixture.message(
            18,
            [
                (254, 0x84, 0),
                (2, 0x86, fixture.BASE + start),
                (253, 0x86, fixture.BASE + end),
                (5, 0, 1),
                (8, 0x86, (end - start) * 1000),
            ],
        )

    data = fixture.file_bytes(
        [indexed(0, 60), indexed(60, 120), fixture.zones(18, [20, 40])]
    )
    assert all(s["hr_zones"] is None for s in parse(data)["sessions"])


def test_fit_invalid_zone_sentinel_is_hidden() -> None:
    zone = fixture.message(
        216, [(0, 0x84, 18), (1, 0x84, 0), (2, 0x86, [10000, 0xFFFFFFFF])]
    )
    assert parse(fixture.regular_fit(extras=[zone]))["sessions"][0]["hr_zones"] is None


def test_foreign_instance_rejected_without_parse_rows(tmp_path: Path) -> None:
    from skills._shared.fit_weekly import storage

    a, b = tmp_path / "a", tmp_path / "b"
    storage.initialize(a)
    storage.initialize(b)
    with storage.open_store(a) as db:
        with pytest.raises(ValueError, match="store_instance_mismatch"):
            module().parse_registered(db, b, "101", "0" * 64)
        assert db.execute("SELECT COUNT(*) FROM parses").fetchone()[0] == 0
