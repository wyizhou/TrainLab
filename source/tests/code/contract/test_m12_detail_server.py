from __future__ import annotations

import asyncio
import importlib
import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))
detail_tests = importlib.import_module("test_m12_fit_detail")


def module():
    return importlib.import_module("skills._shared.fit_weekly.detail_server")


def prepared(tmp_path):
    from skills._shared.fit_weekly import fit_detail

    root, end, members = detail_tests.instance(tmp_path)
    scope = fit_detail.freeze_scope(root, end, members)
    return root, end, scope["scope_sha256"]


def arguments(root, end, sha):
    return [
        "-m",
        "skills._shared.fit_weekly.detail_server",
        "--instance-root",
        str(root),
        "--period-end",
        end,
        "--scope-sha256",
        sha,
        "--stage",
        "summary",
    ]


@asynccontextmanager
async def session(tmp_path, root, end, sha):
    module()
    parameters = StdioServerParameters(
        command=sys.executable,
        args=arguments(root, end, sha),
        cwd=str(SOURCE),
        env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(SOURCE)},
    )
    path = tmp_path / "sdk-stderr.log"
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
    with os.fdopen(fd, "w") as errlog:
        async with stdio_client(parameters, errlog=errlog) as (reader, writer):
            async with ClientSession(
                reader, writer, read_timeout_seconds=timedelta(seconds=5)
            ) as client:
                initialized = await client.initialize()
                yield client, initialized


def result_body(result):
    assert len(result.content) == 1 and result.content[0].type == "text"
    value = json.loads(result.content[0].text)
    assert value == result.structuredContent
    return value


def test_real_stdio_discovery_has_one_prebound_tool_no_resources_or_prompts(tmp_path):
    root, end, sha = prepared(tmp_path)

    async def run():
        async with session(tmp_path, root, end, sha) as (client, info):
            assert info.capabilities.resources is None
            assert info.capabilities.prompts is None
            tools = await client.list_tools()
            assert [t.name for t in tools.tools] == ["read_fit_detail"]
            tool = tools.tools[0]
            assert set(tool.inputSchema["properties"]) == set(detail_tests.request())
            assert set(tool.inputSchema["required"]) == set(
                tool.inputSchema["properties"]
            )
            assert tool.inputSchema["additionalProperties"] is False
            assert tool.annotations.openWorldHint is False
            assert str(root) not in tool.model_dump_json()
            answer = await client.call_tool("read_fit_detail", detail_tests.request())
            body = result_body(answer)
            assert not answer.isError and body["status"] == "available"
            assert body["scope_sha256"] == sha and body["provider_calls"] == 0
            assert len(body["blocks"]) == 12
            assert str(root) not in json.dumps(body)

    asyncio.run(run())


@pytest.mark.parametrize("view", ["summary", "laps", "series"])
def test_wire_views_equal_direct_host_and_replay_across_server_process(tmp_path, view):
    from skills._shared.fit_weekly import fit_detail

    root, end, sha = prepared(tmp_path)
    request = detail_tests.request(view=view)
    host = fit_detail.DetailHost(root, end, sha)
    expected = host.read(request)
    before = (root / "trainlab-fit.db").read_bytes()

    async def run():
        async with session(tmp_path, root, end, sha) as (client, _):
            assert (
                result_body(await client.call_tool("read_fit_detail", request))
                == expected
            )

    asyncio.run(run())
    asyncio.run(run())
    assert host.usage()["requests"] == 1
    assert (root / "trainlab-fit.db").read_bytes() == before


@pytest.mark.parametrize(
    "change",
    [
        {"path": "/private/no-leak.fit"},
        {"sql": "SELECT secret"},
        {"command": "cat secret"},
        {"gps": True},
        {"activity_ref": "999"},
        {"end_offset_seconds": 1201},
        {"resolution_seconds": 2},
        {"start_offset_seconds": True},
        {"view": "raw"},
    ],
)
def test_invalid_wire_input_cannot_reserve_or_echo_private_values(tmp_path, change):
    from skills._shared.fit_weekly import fit_detail

    root, end, sha = prepared(tmp_path)

    async def run():
        async with session(tmp_path, root, end, sha) as (client, _):
            answer = await client.call_tool(
                "read_fit_detail", detail_tests.request(**change)
            )
            body = result_body(answer)
            assert answer.isError and body["status"] == "unavailable"
            assert set(body) == {"status", "error_code", "provider_calls"}
            assert body["provider_calls"] == 0
            for value in ("no-leak", "SELECT", "cat secret", str(root)):
                assert value not in json.dumps(body)

    asyncio.run(run())
    assert fit_detail.DetailHost(root, end, sha).usage()["requests"] == 0


def test_unknown_tool_is_rejected_without_using_fit_host(tmp_path):
    from skills._shared.fit_weekly import fit_detail

    root, end, sha = prepared(tmp_path)

    async def run():
        async with session(tmp_path, root, end, sha) as (client, _):
            answer = await client.call_tool("run_command", {"command": "ignored"})
            assert answer.isError
            assert result_body(answer)["error_code"] == "fit_detail_tool_unknown"

    asyncio.run(run())
    assert fit_detail.DetailHost(root, end, sha).usage()["requests"] == 0


def test_server_restarts_do_not_reset_twenty_request_budget(tmp_path):
    from skills._shared.fit_weekly import fit_detail

    root, end, sha = prepared(tmp_path)
    host = fit_detail.DetailHost(root, end, sha)
    for n in range(20):
        host.read(
            detail_tests.request(start_offset_seconds=n, end_offset_seconds=n + 1)
        )

    async def run():
        async with session(tmp_path, root, end, sha) as (client, _):
            extra = await client.call_tool(
                "read_fit_detail",
                detail_tests.request(start_offset_seconds=50, end_offset_seconds=51),
            )
            assert extra.isError
            assert result_body(extra)["error_code"] == "detail_budget_exceeded"
            old = await client.call_tool(
                "read_fit_detail", detail_tests.request(end_offset_seconds=1)
            )
            assert not old.isError and result_body(old)["status"] == "available"

    asyncio.run(run())
    asyncio.run(run())
    assert host.usage()["requests"] == 20


@pytest.mark.parametrize("change", ["sha", "root", "permission"])
def test_invalid_binding_exits_before_stdio_and_logs_no_paths(tmp_path, change):
    module()
    root, end, sha = prepared(tmp_path)
    if change == "sha":
        sha = "0" * 64
    elif change == "root":
        root = tmp_path / "private-secret-instance"
    else:
        root.chmod(0o755)
    result = subprocess.run(
        [sys.executable, *arguments(root, end, sha)],
        cwd=SOURCE,
        env={"PYTHONPATH": str(SOURCE), "PYTHONDONTWRITEBYTECODE": "1"},
        input=b"",
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 2 and result.stdout == b""
    assert result.stderr == b"fit_detail_server_unavailable\n"
    assert str(root).encode() not in result.stderr


def test_unexpected_host_error_never_leaks_exception_or_path(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import fit_detail

    root, end, sha = prepared(tmp_path)
    host = fit_detail.DetailHost(root, end, sha)

    def fail(_):
        raise OSError("/private/secret/raw.fit token:synthetic-secret")

    monkeypatch.setattr(host, "read", fail)
    answer = module().answer(host, "read_fit_detail", detail_tests.request())
    assert answer.isError
    assert result_body(answer) == {
        "status": "unavailable",
        "error_code": "fit_detail_unavailable",
        "provider_calls": 0,
    }


def test_output_validation_rejects_host_regression_without_echo(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import fit_detail

    root, end, sha = prepared(tmp_path)
    host = fit_detail.DetailHost(root, end, sha)
    value = host.read(detail_tests.request())
    value["gps"] = [12.3, 45.6]
    monkeypatch.setattr(host, "read", lambda _: value)
    answer = module().answer(host, "read_fit_detail", detail_tests.request())
    assert answer.isError
    assert result_body(answer)["error_code"] == "fit_detail_unavailable"
    assert "gps" not in answer.content[0].text


@pytest.mark.parametrize(
    "field,value",
    [
        ("activity_ref", "999"),
        ("scope_sha256", "0" * 64),
        ("request_sha256", "0" * 64),
        ("view", "summary"),
    ],
)
def test_output_from_another_request_is_not_returned(
    tmp_path, monkeypatch, field, value
):
    from skills._shared.fit_weekly import fit_detail

    root, end, sha = prepared(tmp_path)
    host = fit_detail.DetailHost(root, end, sha)
    body = host.read(detail_tests.request())
    body[field] = value
    monkeypatch.setattr(host, "read", lambda _: body)
    answer = module().answer(host, "read_fit_detail", detail_tests.request())
    assert (
        answer.isError and result_body(answer)["error_code"] == "fit_detail_unavailable"
    )


def test_real_stdio_preserves_cached_extraction_failure(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import fit_detail

    root, end, sha = prepared(tmp_path)

    def fail(*args):
        raise OSError("/private/secret")

    with monkeypatch.context() as patch:
        patch.setattr(fit_detail, "extract", fail)
        expected = fit_detail.DetailHost(root, end, sha).read(detail_tests.request())
    assert expected["status"] == "unavailable"
    before = (root / "trainlab-fit.db").read_bytes()

    async def run():
        async with session(tmp_path, root, end, sha) as (client, _):
            answer = await client.call_tool("read_fit_detail", detail_tests.request())
            assert answer.isError and result_body(answer) == expected

    asyncio.run(run())
    assert (root / "trainlab-fit.db").read_bytes() == before


def test_actual_server_does_not_expose_resource_or_prompt_routes(tmp_path):
    from mcp.shared.exceptions import McpError

    root, end, sha = prepared(tmp_path)

    async def run():
        async with session(tmp_path, root, end, sha) as (client, _):
            for action in (
                client.list_resources,
                client.list_resource_templates,
                client.list_prompts,
            ):
                with pytest.raises(McpError):
                    await action()

    asyncio.run(run())


def test_request_schema_and_host_share_valid_shape_and_rejections():
    import jsonschema

    from skills._shared.fit_weekly import fit_detail

    schema = json.loads(module().SCHEMA_PATH.read_text())
    validator = jsonschema.Draft202012Validator(schema)
    for view in ("summary", "laps", "series"):
        for resolution in (1, 5):
            request = detail_tests.request(view=view, resolution_seconds=resolution)
            validator.validate(request)
            assert fit_detail.request_value(request) == request
    for change in (
        {"path": "x"},
        {"view": "raw"},
        {"resolution_seconds": 2},
        {"end_offset_seconds": 0},
        {"start_offset_seconds": True},
    ):
        request = detail_tests.request(**change)
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(request)
        with pytest.raises(ValueError):
            fit_detail.request_value(request)
