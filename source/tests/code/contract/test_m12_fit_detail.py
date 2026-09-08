from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))
sys.path.insert(0, str(SOURCE / "tests/code/fixtures"))
fixture = importlib.import_module("m12_fit_factory")


def module():
    return importlib.import_module("skills._shared.fit_weekly.fit_detail")


def instance(tmp_path: Path, data: bytes | None = None):
    from skills._shared.fit_weekly import fit_parse, storage, sync_calendar

    root = tmp_path / "instance"
    storage.initialize(root)
    data = data if data is not None else fixture.regular_fit(1800)
    p = tmp_path / "input.fit"
    p.write_bytes(data)
    p.chmod(0o600)
    sha = storage.digest(data)
    with storage.open_store(root) as db:
        storage.import_fit(db, root, "101", p, sha)
        parsed = fit_parse.parse_registered(db, root, "101", sha)
    week = sync_calendar.weekly_slot(
        (datetime.fromisoformat(parsed["end_utc"]) + timedelta(days=7)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    )
    return root, week["end_utc"], [{"activity_ref": "101", "fit_sha256": sha}]


def request(**changes):
    return {
        "activity_ref": "101",
        "view": "series",
        "start_offset_seconds": 0,
        "end_offset_seconds": 60,
        "resolution_seconds": 5,
        **changes,
    }


def test_scope_and_request_replay_are_identical_and_zero_increment(tmp_path) -> None:
    root, end, members = instance(tmp_path)
    scope = module().freeze_scope(root, end, members)
    assert module().freeze_scope(root, end, members) == scope
    host = module().DetailHost(root, end, scope["scope_sha256"])
    result = host.read(request())
    assert result["status"] == "available" and result["provider_calls"] == 0
    assert (
        result["representation"] == "time_weighted_bins_with_actual_location_endpoints"
    )
    assert len(result["blocks"]) == 12
    assert result["fit_sha256"] == members[0]["fit_sha256"]
    before = (root / "trainlab-fit.db").read_bytes()
    assert host.read(request()) == result
    assert (root / "trainlab-fit.db").read_bytes() == before
    assert host.usage() == {"requests": 1, "max_requests": 20}


@pytest.mark.parametrize("view", ["summary", "laps", "series"])
def test_all_views_use_same_scope_and_sanitized_projection(tmp_path, view) -> None:
    root, end, members = instance(tmp_path)
    scope = module().freeze_scope(root, end, members)
    host = module().DetailHost(root, end, scope["scope_sha256"])
    result = host.read(request(view=view))
    assert result["view"] == view
    assert result["request_sha256"]
    text = json.dumps(result)
    for fragment in [
        str(root),
        "serial_number",
        "input.fit",
    ]:
        assert fragment not in text


def test_budget_persists_across_host_restart_and_exact_cache_does_not_spend(
    tmp_path,
) -> None:
    root, end, members = instance(tmp_path)
    scope = module().freeze_scope(root, end, members)
    for n in range(20):
        host = module().DetailHost(root, end, scope["scope_sha256"])
        assert (
            host.read(
                request(
                    start_offset_seconds=n,
                    end_offset_seconds=n + 1,
                    resolution_seconds=1,
                )
            )["status"]
            == "available"
        )
    assert (
        host.read(request(end_offset_seconds=1, resolution_seconds=1))["status"]
        == "available"
    )
    with pytest.raises(ValueError, match="detail_budget_exceeded"):
        host.read(
            request(
                start_offset_seconds=30, end_offset_seconds=31, resolution_seconds=1
            )
        )
    assert host.usage()["requests"] == 20


@pytest.mark.parametrize(
    "changes",
    [
        {"start_offset_seconds": -1},
        {"end_offset_seconds": 0},
        {"end_offset_seconds": 1201},
        {"start_offset_seconds": 1799, "end_offset_seconds": 1801},
        {"resolution_seconds": 2},
        {"resolution_seconds": True},
        {"start_offset_seconds": 0.5},
        {"view": "raw"},
        {"activity_ref": "999"},
        {"path": "/private/secret.fit"},
        {"sql": "SELECT * FROM fits"},
        {"command": "pwd"},
        {"gps": True},
    ],
)
def test_invalid_or_out_of_scope_input_is_rejected_before_budget(
    tmp_path, changes
) -> None:
    root, end, members = instance(tmp_path)
    scope = module().freeze_scope(root, end, members)
    host = module().DetailHost(root, end, scope["scope_sha256"])
    with pytest.raises(ValueError, match="detail_"):
        host.read(request(**changes))
    assert host.usage()["requests"] == 0


def test_twenty_minute_boundary_is_inclusive(tmp_path) -> None:
    root, end, members = instance(tmp_path)
    scope = module().freeze_scope(root, end, members)
    result = (
        module()
        .DetailHost(root, end, scope["scope_sha256"])
        .read(request(end_offset_seconds=1200))
    )
    assert len(result["blocks"]) == 240


def test_scope_change_wrong_sha_or_wrong_week_does_not_get_new_budget(tmp_path) -> None:
    root, end, members = instance(tmp_path)
    scope = module().freeze_scope(root, end, members)
    with pytest.raises(ValueError, match="detail_scope_conflict"):
        module().freeze_scope(root, end, [])
    with pytest.raises(ValueError, match="detail_scope_binding_invalid"):
        module().DetailHost(root, end, "0" * 64).read(request())
    previous = (datetime.fromisoformat(end) - timedelta(days=7)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    with pytest.raises(ValueError, match="detail_activity_outside_week"):
        module().freeze_scope(root, previous, members)
    host = module().DetailHost(root, end, scope["scope_sha256"])
    assert host.usage()["requests"] == 0


def test_failed_extraction_has_stable_cached_error_and_spends_once(
    tmp_path, monkeypatch
) -> None:
    root, end, members = instance(tmp_path)
    scope = module().freeze_scope(root, end, members)
    host = module().DetailHost(root, end, scope["scope_sha256"])

    def failure(*args):
        raise OSError("private provider text /some/path")

    with monkeypatch.context() as m:
        m.setattr(module(), "extract", failure)
        first = host.read(request())
    assert (
        first["status"] == "unavailable" and first["error_code"] == "detail_read_failed"
    )
    assert "private provider text" not in json.dumps(first)
    assert host.read(request()) == first
    assert host.usage()["requests"] == 1


def test_interruption_after_durable_intent_cannot_reset_budget(
    tmp_path, monkeypatch
) -> None:
    root, end, members = instance(tmp_path)
    scope = module().freeze_scope(root, end, members)
    host = module().DetailHost(root, end, scope["scope_sha256"])

    def interrupt(*args):
        raise KeyboardInterrupt()

    with monkeypatch.context() as m:
        m.setattr(module(), "extract", interrupt)
        with pytest.raises(KeyboardInterrupt):
            host.read(request())
    assert host.usage()["requests"] == 1
    result = module().DetailHost(root, end, scope["scope_sha256"]).read(request())
    assert result["status"] == "available"
    assert host.usage()["requests"] == 1


def test_completed_detail_relocation_is_zero_increment(tmp_path) -> None:
    root, end, members = instance(tmp_path)
    scope = module().freeze_scope(root, end, members)
    first = module().DetailHost(root, end, scope["scope_sha256"]).read(request())
    before = (root / "trainlab-fit.db").read_bytes()
    moved = tmp_path / "moved"
    root.rename(moved)
    assert (
        module().DetailHost(moved, end, scope["scope_sha256"]).read(request()) == first
    )
    assert (moved / "trainlab-fit.db").read_bytes() == before


def test_raw_drift_is_not_served_even_from_cache(tmp_path) -> None:
    root, end, members = instance(tmp_path)
    scope = module().freeze_scope(root, end, members)
    host = module().DetailHost(root, end, scope["scope_sha256"])
    host.read(request())
    fit = root / "fits" / (members[0]["fit_sha256"] + ".fit")
    fit.write_bytes(b"drift")
    with pytest.raises(ValueError, match="fit_sha_mismatch"):
        host.read(request())


def test_empty_week_has_no_readable_activity(tmp_path) -> None:
    root, end, _ = instance(tmp_path)
    scope = module().freeze_scope(root, end, [])
    host = module().DetailHost(root, end, scope["scope_sha256"])
    with pytest.raises(ValueError, match="detail_activity_outside_scope"):
        host.read(request())
    assert host.usage()["requests"] == 0


def test_one_second_view_discloses_real_sample_count(tmp_path) -> None:
    root, end, members = instance(tmp_path)
    scope = module().freeze_scope(root, end, members)
    result = (
        module()
        .DetailHost(root, end, scope["scope_sha256"])
        .read(
            request(start_offset_seconds=1, end_offset_seconds=2, resolution_seconds=1)
        )
    )
    statistics = result["blocks"][0]["statistics"]
    assert statistics["sample_count"] == 0
    assert statistics["metrics"]["heart_rate_bpm"]["covered_seconds"] == 1
    assert (
        result["representation"] == "time_weighted_bins_with_actual_location_endpoints"
    )


def test_single_week_scope_member_order_is_irrelevant(tmp_path) -> None:
    from skills._shared.fit_weekly import storage

    root, end, members = instance(tmp_path)
    second = fixture.regular_fit(1900)
    source = tmp_path / "second.fit"
    source.write_bytes(second)
    source.chmod(0o600)
    sha = storage.digest(second)
    with storage.open_store(root) as db:
        storage.import_fit(db, root, "102", source, sha)
    members.append({"activity_ref": "102", "fit_sha256": sha})
    scope = module().freeze_scope(root, end, members)
    assert module().freeze_scope(root, end, list(reversed(members))) == scope
    with pytest.raises(ValueError, match="detail_scope_invalid"):
        module().freeze_scope(root, end, members + members)


def test_result_sql_failure_recovers_from_one_reserved_request(
    tmp_path, monkeypatch
) -> None:
    root, end, members = instance(tmp_path)
    scope = module().freeze_scope(root, end, members)
    host = module().DetailHost(root, end, scope["scope_sha256"])
    put = module().put

    def failed(db, key, sha, body):
        put(db, key, sha, body)
        if ":result:" in key:
            raise OSError("synthetic result commit interruption")

    with monkeypatch.context() as m:
        m.setattr(module(), "put", failed)
        with pytest.raises(OSError):
            host.read(request())
    assert host.usage()["requests"] == 1
    result = host.read(request())
    assert result["status"] == "available" and host.usage()["requests"] == 1


def test_real_process_exit_after_intent_keeps_budget(tmp_path) -> None:
    import os
    import subprocess

    root, end, members = instance(tmp_path)
    scope = module().freeze_scope(root, end, members)
    code = """
import json,os,sys
from pathlib import Path
from skills._shared.fit_weekly import fit_detail
def crash(*args): os._exit(37)
fit_detail.extract=crash
fit_detail.DetailHost(Path(sys.argv[1]),sys.argv[2],sys.argv[3]).read(json.loads(sys.argv[4]))
"""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(root),
            end,
            scope["scope_sha256"],
            json.dumps(request()),
        ],
        cwd=SOURCE,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        timeout=20,
    )
    assert proc.returncode == 37
    host = module().DetailHost(root, end, scope["scope_sha256"])
    assert host.usage()["requests"] == 1
    assert host.read(request())["status"] == "available"
    assert host.usage()["requests"] == 1


def test_concurrent_requests_cannot_exceed_shared_budget(tmp_path) -> None:
    import os
    import subprocess

    root, end, members = instance(tmp_path)
    scope = module().freeze_scope(root, end, members)
    host = module().DetailHost(root, end, scope["scope_sha256"])
    for n in range(19):
        host.read(
            request(
                start_offset_seconds=n, end_offset_seconds=n + 1, resolution_seconds=1
            )
        )
    code = """
import json,sys
from pathlib import Path
from skills._shared.fit_weekly import fit_detail
try:
    fit_detail.DetailHost(Path(sys.argv[1]),sys.argv[2],sys.argv[3]).read(json.loads(sys.argv[4]))
except ValueError as exc:
    assert str(exc) in {'store_busy','detail_budget_exceeded'}
"""
    children = []
    for n in range(30, 34):
        children.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    code,
                    str(root),
                    end,
                    scope["scope_sha256"],
                    json.dumps(
                        request(
                            start_offset_seconds=n,
                            end_offset_seconds=n + 1,
                            resolution_seconds=1,
                        )
                    ),
                ],
                cwd=SOURCE,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        )
    for proc in children:
        out, err = proc.communicate(timeout=20)
        assert proc.returncode == 0, (out, err)
    assert host.usage()["requests"] == 20


def test_lap_view_keeps_role_and_marks_partial_interval(tmp_path) -> None:
    data = fixture.regular_fit(
        1800, laps=[fixture.lap(0, 600, 5), fixture.lap(600, 1800, 4)]
    )
    root, end, members = instance(tmp_path, data)
    scope = module().freeze_scope(root, end, members)
    result = (
        module()
        .DetailHost(root, end, scope["scope_sha256"])
        .read(request(view="laps", start_offset_seconds=500, end_offset_seconds=700))
    )
    assert [b["role"] for b in result["blocks"]] == ["work", "recovery"]
    assert all(b["clipped_lap"] for b in result["blocks"])
    assert [b["statistics"]["valid_seconds"] for b in result["blocks"]] == [100, 100]


def test_multisport_detail_keeps_session_gaps_and_identity(tmp_path) -> None:
    data = fixture.file_bytes(
        [fixture.record(t, t * 3, 120) for t in [0, 10, 20, 30, 90, 100, 110, 120]]
        + [
            fixture.session(30, timer=30),
            fixture.session(120, start=90, sport=2, timer=30),
        ]
    )
    root, end, members = instance(tmp_path, data)
    scope = module().freeze_scope(root, end, members)
    result = (
        module()
        .DetailHost(root, end, scope["scope_sha256"])
        .read(request(view="summary", end_offset_seconds=120))
    )
    assert [b["session_ordinal"] for b in result["blocks"]] == [1, 2]
    assert [b["start_offset_seconds"] for b in result["blocks"]] == [0, 90]
    assert sum(b["statistics"]["valid_seconds"] for b in result["blocks"]) == 60


def test_changed_view_or_resolution_is_a_new_request(tmp_path) -> None:
    root, end, members = instance(tmp_path)
    scope = module().freeze_scope(root, end, members)
    host = module().DetailHost(root, end, scope["scope_sha256"])
    outputs = [
        host.read(request()),
        host.read(request(resolution_seconds=1)),
        host.read(request(view="summary")),
    ]
    assert len({o["request_sha256"] for o in outputs}) == 3
    assert host.usage()["requests"] == 3


@pytest.mark.parametrize(
    "member",
    [
        {"activity_ref": [], "fit_sha256": "0" * 64},
        {"activity_ref": "101", "fit_sha256": "../sample.fit"},
        {"activity_ref": "101", "fit_sha256": "0" * 64, "path": "elsewhere"},
    ],
)
def test_bad_scope_member_shape_is_rejected_without_changes(tmp_path, member) -> None:
    root, end, _ = instance(tmp_path)
    before = (root / "trainlab-fit.db").read_bytes()
    with pytest.raises(ValueError, match="detail_scope_invalid"):
        module().freeze_scope(root, end, [member])
    assert (root / "trainlab-fit.db").read_bytes() == before
