from __future__ import annotations

import asyncio
import importlib
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

fixture = importlib.import_module("test_m12_fit_detail")


def test_stage_cache_permission_precedes_cached_result(tmp_path):
    from skills._shared.fit_weekly import fit_detail

    f = fixture.fixture
    data = f.file_bytes(
        [f.record(t, t * 3, 123) for t in range(0, 1801, 10)]
        + [f.session(900), f.session(1800, start=900, sport=2)]
    )
    root, end, members = fixture.instance(tmp_path, data)
    scope = fit_detail.freeze_scope(root, end, members)["scope_sha256"]
    summary = fit_detail.DetailHost(root, end, scope, stage="summary")
    plan = fit_detail.DetailHost(root, end, scope, stage="plan")
    crossing = fixture.request(start_offset_seconds=850, end_offset_seconds=950)
    summary.read(crossing)
    with pytest.raises(ValueError, match="detail_stage_forbidden"):
        plan.read(crossing)
    running = fixture.request(end_offset_seconds=60)
    assert plan.read(running) == summary.read(running)
    assert plan.usage() == summary.usage() == {"requests": 2, "max_requests": 20}


def test_two_stages_share_twenty_reservations(tmp_path):
    from skills._shared.fit_weekly import fit_detail

    root, end, members = fixture.instance(tmp_path)
    scope = fit_detail.freeze_scope(root, end, members)["scope_sha256"]
    hosts = [
        fit_detail.DetailHost(root, end, scope, stage=s) for s in ("plan", "summary")
    ]
    for n in range(20):
        hosts[n % 2].read(
            fixture.request(start_offset_seconds=n, end_offset_seconds=n + 1)
        )
    with pytest.raises(ValueError, match="detail_budget_exceeded"):
        hosts[1].read(fixture.request(start_offset_seconds=30, end_offset_seconds=31))
    assert hosts[0].usage()["requests"] == 20


def test_plan_rejects_nonrunning_without_charge(tmp_path):
    from skills._shared.fit_weekly import fit_detail

    root, end, members = fixture.instance(
        tmp_path, fixture.fixture.regular_fit(1800, sport=2)
    )
    scope = fit_detail.freeze_scope(root, end, members)["scope_sha256"]
    host = fit_detail.DetailHost(root, end, scope, stage="plan")
    with pytest.raises(ValueError, match="detail_stage_forbidden"):
        host.read(fixture.request())
    assert host.usage()["requests"] == 0


def test_real_stdio_stage_permission_and_shared_cache(tmp_path):
    from skills._shared.fit_weekly import fit_detail

    f = fixture.fixture
    data = f.file_bytes(
        [f.record(t, t * 3, 123) for t in range(0, 1801, 10)]
        + [f.session(900), f.session(1800, start=900, sport=2)]
    )
    root, end, members = fixture.instance(tmp_path, data)
    scope = fit_detail.freeze_scope(root, end, members)["scope_sha256"]
    crossing = fixture.request(start_offset_seconds=850, end_offset_seconds=950)
    server = importlib.import_module("test_m12_detail_server")

    async def invoke(stage, request):
        args = server.arguments(root, end, scope)
        args[-1] = stage
        params = StdioServerParameters(
            command=sys.executable,
            args=args,
            cwd=str(fixture.SOURCE),
            env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(fixture.SOURCE)},
        )
        fd = os.open(
            tmp_path / "stderr.log", os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600
        )
        with os.fdopen(fd, "w") as errors:
            async with stdio_client(params, errlog=errors) as (reader, writer):
                async with ClientSession(reader, writer) as client:
                    await client.initialize()
                    return await client.call_tool("read_fit_detail", request)

    assert not asyncio.run(invoke("summary", crossing)).isError
    denied = asyncio.run(invoke("plan", crossing))
    assert (
        denied.isError
        and denied.structuredContent["error_code"] == "detail_stage_forbidden"
    )
    running = fixture.request()
    first = asyncio.run(invoke("plan", running))
    second = asyncio.run(invoke("summary", running))
    assert first.structuredContent == second.structuredContent
    assert (
        fit_detail.DetailHost(root, end, scope, stage="plan").usage()["requests"] == 2
    )
