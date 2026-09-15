"""R7-FIT-TIMEBOUND-001: elapsed bounds, precision, and frozen-version replay."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(SOURCE),
    str(SOURCE / "tests/code/fixtures"),
    str(Path(__file__).parent),
]
factory = importlib.import_module("m12_fit_factory")
fixture = importlib.import_module("m12_fit_time_factory")
fit_parse = importlib.import_module("skills._shared.fit_weekly.fit_parse")
fit_detail = importlib.import_module("skills._shared.fit_weekly.fit_detail")
storage = importlib.import_module("skills._shared.fit_weekly.storage")
detail_fixture = importlib.import_module("test_m12_fit_detail")
week_fixture = importlib.import_module("test_m12_weekly_evidence")


def parse(data, version=None):
    return fit_parse.summarize(
        data, "101", storage.digest(data), parser_version=version
    )


@pytest.mark.parametrize("first", [True, False])
@pytest.mark.parametrize("stamp", [-300, 0, 60, 6000])
def test_summary_order_and_timestamp_do_not_determine_bounds(first, stamp):
    result = parse(fixture.activity(first=first, stamp=stamp, timer_ms=60417))
    assert result["parser_version"] == "fit-summary-3"
    assert result["schema_version"] == "fit_activity_v3"
    s = result["sessions"][0]
    assert s["elapsed_seconds"] == pytest.approx(60.417, abs=1e-6)
    assert s["end_utc"].endswith(".417000Z")
    assert s["valid_seconds"] == s["elapsed_seconds"]
    assert s["summary"]["sample_covered_seconds"] == 60
    assert s["gap_seconds"] == pytest.approx(0.417, abs=1e-6)
    assert result["location"]["valid_point_count"] == 3
    assert "87654321" not in json.dumps(result)


@pytest.mark.parametrize("kind", [18, 19])
@pytest.mark.parametrize("duration", [None, 0, 0xFFFFFFFF])
def test_missing_or_invalid_elapsed_never_uses_timestamp_or_timer(kind, duration):
    messages = [fixture.summary(kind, elapsed_ms=duration, stamp=60, timer_ms=60000)]
    if kind == 19:
        messages.append(fixture.summary(elapsed_ms=60000, stamp=60))
    with pytest.raises(ValueError, match="fit_time_bounds_invalid"):
        parse(factory.file_bytes(messages))


@pytest.mark.parametrize("elapsed", [True, False, -1, float("nan"), float("inf"), "60"])
def test_elapsed_scalar_validation_does_not_accept_coercions(elapsed):
    fields = {
        "start_time": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "total_elapsed_time": elapsed,
    }
    frame = SimpleNamespace(
        get_value=lambda name, fallback=None: fields.get(name, fallback)
    )
    with pytest.raises(ValueError, match="fit_time_bounds_invalid"):
        fit_parse.boundaries(frame, parser_version="fit-summary-3")


def test_pause_events_keep_point_time_and_unknown_timer_stays_unknown():
    data = factory.file_bytes(
        [
            fixture.summary(elapsed_ms=60417, timer_ms=40417),
            factory.event(0, 0),
            factory.event(10, 1),
            factory.event(30, 0),
            *[
                factory.record(t, t * 3, 200 if t == 10 else 120)
                for t in (0, 10, 30, 60)
            ],
        ]
    )
    s = parse(data)["sessions"][0]
    assert s["valid_seconds"] == pytest.approx(40.417, abs=1e-6)
    assert s["pause_seconds"] == 20
    assert s["summary"]["metrics"]["heart_rate_bpm"]["mean"] == 120
    assert "timer_total_precision_difference" not in s["limitations"]
    unknown = parse(fixture.activity(timer_ms=40417))["sessions"][0]
    assert unknown["valid_seconds"] is None
    assert "timer_boundaries_unavailable" in unknown["limitations"]


@pytest.mark.parametrize("overlap_ms", [999, 1000, 1001])
def test_adjacent_lap_precision_is_strictly_less_than_one_second(overlap_ms):
    data = fixture.activity(
        elapsed_ms=60000,
        timer_ms=60000,
        laps=[
            fixture.summary(19, elapsed_ms=30000 + overlap_ms, role=5),
            fixture.summary(19, start=30, elapsed_ms=30000, role=4),
        ],
    )
    s = parse(data)["sessions"][0]
    assert s["running_kind"] == "unknown"
    if overlap_ms < 1000:
        assert len(s["laps"]) == 2
        assert s["laps"][0]["end_offset_seconds"] == pytest.approx(30.999, abs=1e-6)
        assert "lap_time_precision_compatible" in s["limitations"]
    else:
        assert s["laps"] == []
        assert "laps_conflicting" in s["limitations"]


@pytest.mark.parametrize("overflow_ms", [999, 1000, 1001])
def test_terminal_lap_retains_formula_end_and_bounds_statistics(overflow_ms):
    data = fixture.activity(
        elapsed_ms=60000,
        timer_ms=60000,
        laps=[fixture.summary(19, elapsed_ms=60000 + overflow_ms)],
    )
    s = parse(data)["sessions"][0]
    if overflow_ms < 1000:
        lap = s["laps"][0]
        assert lap["end_offset_seconds"] == pytest.approx(60.999, abs=1e-6)
        assert lap["valid_seconds"] == 60
        assert lap["sample_count"] == 3
        blocks = fit_detail.extract(data, detail_fixture.request(view="laps"))
        assert len(blocks) == 1 and blocks[0]["clipped_lap"] is True
        assert blocks[0]["lap_time_precision_compatible"] is True
        assert blocks[0]["end_offset_seconds"] == 60
    else:
        assert s["laps"] == [] and "laps_conflicting" in s["limitations"]


@pytest.mark.parametrize(
    "case", ["duplicate", "same_start", "cross_session", "backwards"]
)
def test_precision_does_not_hide_real_lap_conflicts(case):
    laps = [fixture.summary(19, elapsed_ms=30999)]
    if case == "duplicate":
        laps *= 2
    elif case == "same_start":
        laps.append(fixture.summary(19, elapsed_ms=30000))
    elif case == "backwards":
        laps = [fixture.summary(19, start=30, elapsed_ms=30000), *laps]
    else:
        laps = [fixture.summary(19, start=59, elapsed_ms=2000)]
    messages = [fixture.summary(elapsed_ms=60000), *laps]
    if case == "cross_session":
        messages.append(fixture.summary(start=60, elapsed_ms=60000, sport=2))
    assert all(
        "laps_conflicting" in s["limitations"]
        for s in parse(factory.file_bytes(messages))["sessions"]
    )


def test_fractional_detail_tail_uses_host_budget_and_lossless_transport(tmp_path):
    from skills._shared.fit_weekly import detail_server, detail_transport, stage_policy

    data = fixture.activity(
        timer_ms=60417, laps=[fixture.summary(19, elapsed_ms=61364)]
    )
    root, end, members = detail_fixture.instance(tmp_path, data)
    scope = fit_detail.freeze_scope(root, end, members)
    host = fit_detail.DetailHost(root, end, scope["scope_sha256"], stage="plan")
    req = detail_fixture.request(
        start_offset_seconds=60, end_offset_seconds=60.417, resolution_seconds=1
    )
    result = host.read(req)
    assert (
        result["schema_version"] == "fit_detail_v3" and result["status"] == "available"
    )
    assert result["blocks"][0]["end_offset_seconds"] == pytest.approx(60.417, abs=1e-6)
    assert result["blocks"][0]["statistics"]["elapsed_seconds"] == pytest.approx(
        0.417, abs=1e-6
    )
    assert detail_transport.unpack(detail_transport.pack(result)) == result
    assert (
        detail_server.answer(host, "read_fit_detail", req, compact=True).isError
        is False
    )
    stage_policy.authorize("plan", parse(data), req)
    assert host.read(req) == result and host.usage()["requests"] == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"start_offset_seconds": -0.001},
        {"start_offset_seconds": True},
        {"end_offset_seconds": float("nan")},
        {"end_offset_seconds": float("inf")},
        {"end_offset_seconds": 60.4171},
        {"end_offset_seconds": 60.418},
        {"end_offset_seconds": 1200.001},
        {"resolution_seconds": 1.0},
    ],
)
def test_fractional_detail_invalid_values_rejected_before_budget(tmp_path, changes):
    root, end, members = detail_fixture.instance(tmp_path, fixture.activity())
    scope = fit_detail.freeze_scope(root, end, members)
    host = fit_detail.DetailHost(root, end, scope["scope_sha256"])
    with pytest.raises(ValueError, match="detail_"):
        host.read(detail_fixture.request(**changes))
    assert host.usage()["requests"] == 0


@pytest.mark.parametrize("delta_ms, included", [(-1, True), (0, False), (1, False)])
def test_week_cutoff_compares_exact_activity_end(delta_ms, included):
    from skills._shared.fit_weekly import sync_calendar

    slot = sync_calendar.weekly_slot(week_fixture.END)
    end = datetime.fromisoformat(week_fixture.END) + timedelta(milliseconds=delta_ms)
    assert (
        sync_calendar.in_week(end.isoformat().replace("+00:00", "Z"), slot) is included
    )
    with pytest.raises(ValueError, match="sync_time_invalid"):
        sync_calendar.utc_time("2026-08-09T07:00:00.001Z")


@pytest.mark.parametrize("version", ["fit-summary-1", "fit-summary-2"])
def test_legacy_summary_and_uncached_detail_replay_exactly(tmp_path, version):
    data = fixture.activity(stamp=61, elapsed_ms=60417, timer_ms=61000)
    expected = json.loads(
        (SOURCE / "tests/code/fixtures/m12_fit_time_legacy_hashes.json").read_text()
    )[version]
    parsed = parse(data, version)
    assert storage.digest(storage.canonical(parsed).encode()) == expected["summary"]
    blocks = fit_detail.extract(data, detail_fixture.request(), version)
    assert storage.digest(storage.canonical(blocks).encode()) == expected["detail"]
    root, end, members = detail_fixture.instance(tmp_path, data)
    scope = fit_detail.freeze_scope(root, end, members, parser_version=version)
    host = fit_detail.DetailHost(root, end, scope["scope_sha256"])
    first = host.read(detail_fixture.request())
    assert first["blocks"] == blocks
    before = host.usage()
    assert fit_detail.freeze_scope(root, end, members) == scope
    assert host.read(detail_fixture.request()) == first and host.usage() == before
    second = host.read(detail_fixture.request(view="summary"))
    assert second["blocks"] == fit_detail.extract(
        data, detail_fixture.request(view="summary"), version
    )
    assert host.usage()["requests"] == 2
    with pytest.raises(ValueError, match="detail_request_invalid"):
        host.read(detail_fixture.request(end_offset_seconds=60.417))
    with storage.open_store(root) as db:
        assert (
            fit_parse.parse_registered(
                db, root, "101", members[0]["fit_sha256"], parser_version=version
            )
            == parsed
        )
        versions = {row[0] for row in db.execute("SELECT parser_version FROM parses")}
        assert versions == {"fit-summary-3", version}


def test_fractional_timer_total_difference_is_disclosed_without_invented_pause():
    data = factory.file_bytes(
        [
            fixture.summary(elapsed_ms=60417, timer_ms=60417),
            factory.event(0, 0),
            factory.event(60, 1),
            factory.record(0, 0, 120),
            factory.record(30, 90, 120),
            factory.record(60, 180, 120),
        ]
    )
    s = parse(data)["sessions"][0]
    assert s["valid_seconds"] == 60
    assert s["provider_summary"]["timer_seconds"] == 60.417
    assert s["pause_seconds"] == pytest.approx(0.417, abs=1e-6)
    assert "timer_total_precision_difference" in s["limitations"]


def test_lap_points_belong_only_to_their_session_and_gap_is_not_filled():
    data = factory.file_bytes(
        [
            fixture.summary(elapsed_ms=60000, timer_ms=60000),
            fixture.summary(start=60, elapsed_ms=30000, timer_ms=30000, sport=2),
            fixture.summary(19, elapsed_ms=29999),
            fixture.summary(19, start=30, elapsed_ms=30000, role=4),
            *[
                factory.record(t, t * 3, 240 if t >= 60 else 120)
                for t in (0, 10, 20, 30, 40, 50, 60, 70, 80, 90)
            ],
        ]
    )
    s = parse(data)["sessions"][0]
    assert s["running_kind"] == "unknown"
    assert s["laps"][0]["end_offset_seconds"] == pytest.approx(29.999, abs=1e-6)
    assert s["laps"][1]["start_offset_seconds"] == 30
    assert s["laps"][1]["sample_count"] == 3
    assert s["laps"][1]["location"]["sample_count"] == 3
    blocks = fit_detail.extract(data, detail_fixture.request(view="laps"))
    assert blocks[1]["statistics"]["sample_count"] == 3
    assert blocks[1]["statistics"]["metrics"]["heart_rate_bpm"]["mean"] == 120


@pytest.mark.parametrize("version", ["fit-summary-1", "fit-summary-2"])
def test_frozen_legacy_week_context_and_scope_replay_after_default_upgrade(
    tmp_path, monkeypatch, version
):
    from skills._shared.fit_weekly import stage_context, weekly_context

    helpers = importlib.import_module("test_m12_weekly_context")
    root, week, sdk = helpers.setup(tmp_path, monkeypatch, parser_version=version)
    context = weekly_context.freeze(
        root, week_fixture.END, validate_report=helpers.valid_report
    )
    plan = stage_context.freeze(
        root, week_fixture.END, "plan", validate_history=helpers.valid_report
    )
    host = fit_detail.DetailHost(
        root, week_fixture.END, context["scope_sha256"], stage="plan"
    )
    first = host.read(detail_fixture.request())
    calls = list(sdk.calls)
    monkeypatch.setattr(fit_parse, "VERSION", "fit-summary-3")
    before = (root / "trainlab-fit.db").read_bytes()
    assert week_fixture.freeze(root, week["sources"]["sync_job_key"]) == week
    assert (
        weekly_context.freeze(
            root, week_fixture.END, validate_report=helpers.valid_report
        )
        == context
    )
    assert (
        stage_context.freeze(
            root, week_fixture.END, "plan", validate_history=helpers.valid_report
        )
        == plan
    )
    assert host.read(detail_fixture.request()) == first
    assert (root / "trainlab-fit.db").read_bytes() == before
    assert (
        host.read(detail_fixture.request(view="summary"))["parser_version"] == version
    )
    assert host.usage()["requests"] == 2 and sdk.calls == calls


def test_week_precision_order_context_tool_and_coaching_reference(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import (
        coaching_evidence,
        detail_server,
        stage_context,
        weekly_context,
    )
    from skills._shared.scripts.schema_validation import validate_payload

    helpers = importlib.import_module("test_m12_weekly_context")
    epoch = datetime(1989, 12, 31, tzinfo=timezone.utc)
    monkeypatch.setattr(
        factory,
        "BASE",
        int((datetime.fromisoformat(week_fixture.START) - epoch).total_seconds()),
    )
    edge = 7 * 86400
    activities = [
        (
            ref,
            start,
            factory.file_bytes(
                [fixture.summary(start=start, elapsed_ms=elapsed, timer_ms=elapsed)]
            ),
        )
        for ref, start, elapsed in [
            ("101", 3600, 60001),
            ("102", 3600, 60000),
            ("103", edge - 60, 59999),
            ("104", edge - 60, 60000),
            ("105", edge - 60, 60001),
        ]
    ]
    root, key, sdk, _ = week_fixture.setup(tmp_path, monkeypatch, activities)
    calls = list(sdk.calls)
    week = week_fixture.freeze(root, key)
    assert [a["activity_ref"] for a in week["activities"]] == ["102", "101", "103"]
    goal = root / "Goal.md"
    goal.write_text(helpers.goal_text())
    goal.chmod(0o600)
    context = weekly_context.freeze(
        root, week_fixture.END, validate_report=helpers.valid_report
    )
    plan = stage_context.freeze(
        root, week_fixture.END, "plan", validate_history=helpers.valid_report
    )
    assert context["schema_version"] == "fit_weekly_context_v4"
    assert plan["schema_version"] == "fit_weekly_stage_input_v3"
    assert validate_payload(plan, plan["schema_version"]) == []
    assert all(
        a["parser_version"] == "fit-summary-3" for a in plan["running_activities"]
    )
    assert all(
        s["activity_name"]["source"] is not None for s in week["activity_sources"]
    )
    host = fit_detail.DetailHost(
        root, week_fixture.END, context["scope_sha256"], stage="plan"
    )
    request = detail_fixture.request(
        start_offset_seconds=60, end_offset_seconds=60.001, resolution_seconds=1
    )
    result = host.read(request)
    ref = {
        "source": "detail",
        "activity_ref": "101",
        "fit_sha256": result["fit_sha256"],
        "session_ordinal": 1,
        "period_end_utc": None,
        "request_sha256": result["request_sha256"],
        "path": ["blocks", 0, "statistics", "elapsed_seconds"],
    }
    assert coaching_evidence.resolve(ref, plan, root=root) == pytest.approx(
        0.001, abs=1e-6
    )
    schema = json.loads(detail_server.schema_path(host.parser_version()).read_text())
    assert schema["properties"]["end_offset_seconds"]["type"] == "number"
    assert detail_server.answer(host, detail_server.TOOL, request).isError is False
    assert sdk.calls == calls and host.usage()["requests"] == 1


@pytest.mark.parametrize("version", ["fit-summary-1", "fit-summary-2", "fit-summary-3"])
def test_report_projects_time_method_without_changing_report_contract(
    tmp_path, monkeypatch, version
):
    from skills._shared.fit_weekly import (
        coaching,
        coaching_facts,
        model_job,
        report_view,
        weekly_stages,
    )
    from skills._shared.scripts.schema_validation import validate_payload

    contexts = importlib.import_module("test_m12_weekly_context")
    content = importlib.import_module("m12_coaching_factory")
    root, evidence, _ = contexts.setup(tmp_path, monkeypatch, parser_version=version)

    def prepare(stage):
        def adapter(payload, scope):
            output = content.plan() if stage == "plan" else content.summary(payload)
            return model_job.FakeAdapter(output, [])

        return adapter

    stages = weekly_stages.run(
        root,
        contexts.fixture.END,
        plan=coaching.stage_contract(root, "plan", prepare("plan")),
        summary=coaching.stage_contract(root, "summary", prepare("summary")),
        validate_history=coaching.validator(root),
    )
    assert stages["publishable"]
    with storage.open_store(root) as db:
        saved = fit_detail.get(
            db, "weekly-stage-input:" + contexts.fixture.END + ":summary"
        )
    payload = saved[1]
    before = storage.canonical(payload)
    coaching_facts.build(payload)
    assert storage.canonical(payload) == before
    report = coaching.report(root, contexts.fixture.END)
    assert report["schema_version"] == "fit_coaching_report_v1"
    assert validate_payload(report, "fit_coaching_report_v1") == []
    row = report["facts"]["inventory"][0]
    activity = evidence["activities"][0]
    methods = dict(activity["methods"])
    limitations = list(activity["sessions"][0]["limitations"])
    if version == "fit-summary-3":
        assert (
            methods.pop("summary_time_bounds") == "start_time_plus_total_elapsed_time"
        )
        limitations.append("session_lap_end_start_plus_elapsed")
        assert "开始时间加经过时长" in report_view.label(limitations[-1])
    assert row["methods"] == methods
    assert row["limitations"] == limitations
    assert row["end_utc"] == activity["sessions"][0]["end_utc"]


def test_fractional_requests_keep_twenty_request_budget_after_move(tmp_path):
    from skills._shared.fit_weekly import detail_server
    from skills._shared.scripts.schema_validation import validate_payload

    root, end, members = detail_fixture.instance(
        tmp_path, fixture.activity(timer_ms=60417)
    )
    scope = fit_detail.freeze_scope(root, end, members)
    host = fit_detail.DetailHost(root, end, scope["scope_sha256"])
    first = None
    for n in range(20):
        req = detail_fixture.request(
            start_offset_seconds=n / 1000, end_offset_seconds=1.001
        )
        assert validate_payload(req, "fit_detail_request_v2") == []
        result = detail_server.answer(host, detail_server.TOOL, req)
        assert result.isError is False
        if n == 0:
            first = host.read(req)
    moved = tmp_path / "relocated"
    root.rename(moved)
    host = fit_detail.DetailHost(moved, end, scope["scope_sha256"])
    assert (
        host.read(
            detail_fixture.request(start_offset_seconds=0, end_offset_seconds=1.001)
        )
        == first
    )
    with pytest.raises(ValueError, match="detail_budget_exceeded"):
        host.read(
            detail_fixture.request(start_offset_seconds=0.021, end_offset_seconds=1.001)
        )
    assert host.usage()["requests"] == 20


@pytest.mark.parametrize(
    "version,filename,constant",
    [
        ("fit-summary-1", "m12_codex_cli_tools.json", "LEGACY_TOOL_SURFACE_SHA256"),
        (
            "fit-summary-2",
            "m12_codex_cli_tools_v2.json",
            "LOCATION_TOOL_SURFACE_SHA256",
        ),
        ("fit-summary-3", "m12_codex_cli_tools_v3.json", "TIME_TOOL_SURFACE_SHA256"),
    ],
)
def test_tool_schema_and_surface_are_version_bound(version, filename, constant):
    from skills._shared.fit_weekly import codex_boundary, detail_server

    tools = json.loads((SOURCE / "tests/code/fixtures" / filename).read_text())
    codex_boundary.require_tool_surface(
        tools, expected_sha256=getattr(codex_boundary, constant)
    )
    schema = json.loads(detail_server.schema_path(version).read_text())
    assert schema["properties"]["end_offset_seconds"]["type"] == (
        "number" if version == "fit-summary-3" else "integer"
    )
    if version != "fit-summary-3":
        with pytest.raises(ValueError, match="codex_capabilities_invalid"):
            codex_boundary.require_tool_surface(tools)
