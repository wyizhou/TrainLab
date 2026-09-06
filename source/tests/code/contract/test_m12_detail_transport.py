from __future__ import annotations

import asyncio
import copy
import importlib
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))
details = importlib.import_module("test_m12_fit_detail")


def module():
    return importlib.import_module("skills._shared.fit_weekly.detail_transport")


def prepared(tmp_path):
    from skills._shared.fit_weekly import fit_detail

    root, end, members = details.instance(tmp_path)
    scope = fit_detail.freeze_scope(root, end, members)
    return fit_detail.DetailHost(root, end, scope["scope_sha256"])


@pytest.mark.parametrize("view", ["summary", "laps", "series"])
@pytest.mark.parametrize("resolution", [1, 5])
def test_twenty_minute_lossless_round_trip_and_cache(tmp_path, view, resolution):
    host = prepared(tmp_path)
    request = details.request(
        view=view, end_offset_seconds=1200, resolution_seconds=resolution
    )
    original = host.read(request)
    before = copy.deepcopy(original)
    packed = module().pack(original)
    assert module().unpack(packed) == original == before
    assert packed == module().pack(host.read(request))
    assert host.usage()["requests"] == 1
    assert packed["schema_version"] == "fit_detail_table_v1"
    assert len(packed["block_rows"]) == len(original["blocks"])
    if view == "series":
        assert len(original["blocks"]) == 1200 // resolution
        assert len(json.dumps(packed)) < len(json.dumps(original)) / 3


def test_dense_multisession_values_and_missing_metrics_are_not_rounded_or_dropped(
    tmp_path,
):
    host = prepared(tmp_path)
    original = host.read(details.request())
    for n, block in enumerate(original["blocks"]):
        block["session_ordinal"] = n // 3 + 1
        for metric in block["statistics"]["metrics"].values():
            metric["mean"] = n + 0.123456789012345
            metric["min"] = n - 0.876543210987655
            metric["max"] = n + 1.123456789012345
            metric["covered_seconds"] = 2.3456789012345
    original["blocks"][0]["statistics"]["metrics"]["power_w"]["mean"] = None
    packed = module().pack(original)
    assert module().unpack(packed) == original
    assert packed == module().pack(json.loads(json.dumps(original, sort_keys=True)))


@pytest.mark.parametrize("status", ["available", "unavailable"])
def test_empty_detail_is_lossless(tmp_path, status):
    original = prepared(tmp_path).read(details.request())
    original.update(
        blocks=[],
        status=status,
        error_code=None if status == "available" else "detail_read_failed",
    )
    packed = module().pack(original)
    assert packed["block_columns"] == [] and packed["block_defaults"] == {}
    assert module().unpack(packed) == original


@pytest.mark.parametrize(
    "change",
    [
        "column",
        "duplicate",
        "row",
        "default",
        "sha",
        "source",
        "extra",
        "version",
        "private",
    ],
)
def test_invalid_transport_never_returns_a_partial_result(tmp_path, change):
    body = module().pack(prepared(tmp_path).read(details.request()))
    if change == "column":
        body["block_columns"][0] = "statistics.gps"
    elif change == "duplicate":
        body["block_columns"].append(body["block_columns"][0])
    elif change == "row":
        body["block_rows"][0].pop()
    elif change == "default":
        body["block_defaults"]["session_ordinal"] = 100
    elif change == "sha":
        body["detail_sha256"] = "0" * 64
    elif change == "source":
        body["fit_sha256"] = "0" * 64
    elif change == "version":
        body["schema_version"] = "unknown"
    elif change == "private":
        body["block_defaults"]["gps"] = "/private/not-a-source.fit"
    else:
        body["unapproved"] = "extra"
    with pytest.raises(ValueError, match="detail_transport_invalid"):
        module().unpack(body)


@pytest.mark.parametrize(
    "change",
    [
        "truncate",
        "wrong_value_and_new_sha",
        "wrong_binding",
        "prefix",
        "suffix",
        "non_json",
    ],
)
def test_model_handoff_checks_full_body_against_host(tmp_path, change):
    from skills._shared.fit_weekly import storage

    original = prepared(tmp_path).read(details.request())
    packed = module().pack(original)
    text = "Wall time: 0.012 seconds\nOutput:\n" + storage.canonical(packed)
    if change == "truncate":
        text = text[:400] + "…22 chars truncated…" + text[-400:]
    elif change == "wrong_value_and_new_sha":
        altered = copy.deepcopy(original)
        altered["blocks"][0]["statistics"]["distance_m"] = 999
        text = "Wall time: 0.012 seconds\nOutput:\n" + storage.canonical(
            module().pack(altered)
        )
    elif change == "wrong_binding":
        original["fit_sha256"] = "0" * 64
    elif change == "prefix":
        text = "Extra prompt\n" + text
    elif change == "suffix":
        text += "\nExtra prompt"
    else:
        text = "unavailable"
    with pytest.raises(ValueError, match="detail_model_handoff_invalid"):
        module().audit_model_output(text, original)


def test_model_handoff_accepts_complete_json_not_only_sdk_result(tmp_path):
    from skills._shared.fit_weekly import storage

    original = prepared(tmp_path).read(details.request())
    packed = module().pack(original)
    for text in (
        storage.canonical(packed),
        "Wall time: 0.5 seconds\nOutput:\n" + json.dumps(packed),
    ):
        proof = module().audit_model_output(text, original)
        assert proof["status"] == "checked"
        assert proof["blocks"] == len(original["blocks"])
        assert proof["detail_sha256"] == packed["detail_sha256"]
        assert proof["model_calls"] == proof["provider_calls"] == 0


@pytest.mark.parametrize("where", ["top", "defaults", "escaped_key"])
def test_duplicate_json_keys_cannot_hide_extra_model_visible_text(tmp_path, where):
    from skills._shared.fit_weekly import storage

    original = prepared(tmp_path).read(details.request())
    text = storage.canonical(module().pack(original))
    if where == "top":
        text = '{"schema_version":"PUBLIC_EXTRA",' + text[1:]
    elif where == "escaped_key":
        text = '{"\\u0073chema_version":"PUBLIC_EXTRA",' + text[1:]
    else:
        text = text.replace(
            '"block_defaults":{',
            '"block_defaults":{"session_ordinal":"PUBLIC_EXTRA",',
            1,
        )
    with pytest.raises(ValueError, match="detail_model_handoff_invalid"):
        module().audit_model_output(text, original)


def test_compact_server_is_opt_in_and_codex_requests_it(tmp_path):
    from skills._shared.fit_weekly import codex_boundary, detail_server

    host = prepared(tmp_path)
    request = details.request()
    normal = detail_server.answer(host, "read_fit_detail", request)
    compact = detail_server.answer(host, "read_fit_detail", request, compact=True)
    assert module().unpack(compact.structuredContent) == normal.structuredContent
    assert json.loads(compact.content[0].text) == compact.structuredContent
    args = codex_boundary.configuration_arguments(
        source=SOURCE,
        instance=host.root,
        work=tmp_path,
        python=Path(sys.executable),
        period_end=host.key.removeprefix("detail:"),
        scope_sha256=host.scope_sha,
    )
    config = dict(
        (a.split("=", 1)[0], json.loads(a.split("=", 1)[1])) for a in args[1::2]
    )
    assert "--compact" in config["mcp_servers.fit.args"]
    assert config["tool_output_token_limit"] >= 1_000_000
    assert host.usage()["requests"] == 1


@pytest.mark.parametrize("resolution", [1, 5])
def test_real_compact_stdio_max_range_replay_is_lossless(tmp_path, resolution):
    server_tests = importlib.import_module("test_m12_detail_server")
    host = prepared(tmp_path)
    end = host.key.removeprefix("detail:")
    request = details.request(end_offset_seconds=1200, resolution_seconds=resolution)
    params = StdioServerParameters(
        command=sys.executable,
        args=server_tests.arguments(host.root, end, host.scope_sha) + ["--compact"],
        cwd=str(SOURCE),
        env={"PYTHONPATH": str(SOURCE), "PYTHONDONTWRITEBYTECODE": "1"},
    )

    async def run():
        fd = os.open(
            tmp_path / "compact-sdk.log", os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600
        )
        with os.fdopen(fd, "w") as log:
            async with stdio_client(params, errlog=log) as (reader, writer):
                async with ClientSession(
                    reader, writer, read_timeout_seconds=timedelta(seconds=20)
                ) as client:
                    await client.initialize()
                    result = await client.call_tool("read_fit_detail", request)
                    assert not result.isError
                    assert (
                        json.loads(result.content[0].text) == result.structuredContent
                    )
                    restored = module().unpack(result.structuredContent)
                    assert restored == host.read(request)
                    assert len(restored["blocks"]) == 1200 // resolution
                    return result.content[0].text

    first = asyncio.run(run())
    before = (host.root / "trainlab-fit.db").read_bytes()
    assert asyncio.run(run()) == first
    assert (host.root / "trainlab-fit.db").read_bytes() == before
    assert host.usage()["requests"] == 1


def test_compact_errors_do_not_echo_private_input_or_host_regressions(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import detail_server

    host = prepared(tmp_path)
    result = detail_server.answer(
        host, "read_fit_detail", details.request(gps="private-value"), compact=True
    )
    assert result.isError
    assert host.usage()["requests"] == 0
    assert "private-value" not in result.content[0].text
    body = host.read(details.request())
    body["blocks"][0]["gps"] = [12.3, 45.6]
    monkeypatch.setattr(host, "read", lambda _: body)
    result = detail_server.answer(
        host, "read_fit_detail", details.request(), compact=True
    )
    assert result.isError and "gps" not in result.content[0].text
