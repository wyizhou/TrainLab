from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))
ledger = importlib.import_module("test_m12_model_job")
boundary_fixture = importlib.import_module("test_m12_codex_boundary")
output_fixture = importlib.import_module("test_m12_codex_output")


def public_proof(runtime):
    from skills._shared.fit_weekly import (
        codex_capability,
        codex_output,
        process_capture,
    )
    from skills._shared.fit_weekly.model_process import ProcessResult

    body = boundary_fixture.packet()
    body["instructions"] = runtime.instructions
    body["model"] = runtime.model
    body["input"][-1]["content"][0]["text"] = codex_capability.PROMPT
    body["text"] = {"format": codex_output.response_format(codex_capability.SCHEMA)}
    events = output_fixture.stream(output_fixture.events({"ok": True}))
    result = ProcessResult(0, len(codex_capability.PROMPT.encode()), events, b"", None)
    return {
        "schema_version": "fit_codex_capability_v1",
        "runtime": runtime.identity(),
        "cwd": "/public/job",
        "initial_request": body,
        "process": process_capture.encode(
            result, codex_capability.binding(runtime.identity())
        ),
        "startup_messages": [],
        "refusals": dict(codex_capability.REFUSALS),
        "handoffs": [],
    }


def complete_probe(proof, tmp_path):
    from skills._shared.fit_weekly import (
        codex_capability,
        detail_transport,
        fit_detail,
        model_job,
        process_capture,
    )
    from skills._shared.fit_weekly.model_process import ProcessResult

    fixture = importlib.import_module("test_m12_fit_detail")
    probe_root = tmp_path / "probe-data"
    probe_root.mkdir(mode=0o700)
    root, end, members = fixture.instance(probe_root)
    scope = fit_detail.freeze_scope(root, end, members)
    host = fit_detail.DetailHost(root, end, scope["scope_sha256"])
    proof["handoffs"] = []
    for resolution in (1, 1, 5, 5):
        request = fixture.request(
            end_offset_seconds=1200, resolution_seconds=resolution
        )
        value = host.read(request)
        proof["handoffs"].append(
            {
                "request": request,
                "host_result": value,
                "model_output": json.dumps(
                    detail_transport.pack(value), separators=(",", ":")
                ),
                "charged_requests": host.usage()["requests"],
            }
        )
    assert model_job.sha(proof["handoffs"][0]["host_result"]) == model_job.sha(
        proof["handoffs"][1]["host_result"]
    )
    rows = output_fixture.events({"ok": True})
    tool_events = []
    for i, item in enumerate(proof["handoffs"]):
        pair = output_fixture.call(item_id=f"detail-{i}")
        for event in pair:
            event["item"]["arguments"] = item["request"]
        tool_events.extend(pair)
    for i, server in enumerate(("fit", "unconfigured")):
        pair = output_fixture.call(
            item_id=f"refusal-{i}", tool="read_mcp_resource", server=server, failed=True
        )
        for event in pair:
            event["item"]["arguments"] = {
                "server": server,
                "uri": "file:///public-sentinel",
            }
        pair[-1]["item"]["error"]["message"] = list(codex_capability.REFUSALS.values())[
            i + 1
        ]
        tool_events.extend(pair)
    rows[2:2] = tool_events
    result = ProcessResult(
        0, len(codex_capability.PROMPT.encode()), output_fixture.stream(rows), b"", None
    )
    proof["process"] = process_capture.encode(
        result, codex_capability.binding(proof["runtime"])
    )
    proof["requests"] = [copy.deepcopy(proof["initial_request"])]
    for i, output in enumerate(
        [
            *(x["model_output"] for x in proof["handoffs"]),
            *codex_capability.REFUSALS.values(),
        ]
    ):
        request = copy.deepcopy(proof["initial_request"])
        request["input"].append(
            {"type": "function_call_output", "call_id": f"call_{i}", "output": output}
        )
        proof["requests"].append(request)
    return proof
