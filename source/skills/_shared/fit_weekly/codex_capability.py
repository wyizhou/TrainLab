"""Check retained PUBLIC probe evidence; never run a probe or trust a PASS flag.

The probe producer is a trusted Host diagnostic, not model input. Local evidence
is not an unforgeable remote attestation. Its raw request, stopped process,
lossless FIT handoffs and refusals must all agree with this launch identity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    codex_boundary,
    codex_output,
    detail_transport,
    fit_detail,
    model_job,
    process_capture,
)

PROMPT = 'Public offline fixture. Return {"ok":true}. Do not call any tool.'
SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean", "const": True}},
    "required": ["ok"],
    "additionalProperties": False,
}
REFUSALS = {
    "shell": "unsupported call: exec_command",
    "file_resource": "resources/read failed: resources/read failed for `fit` "
    "(file:///public-sentinel): Mcp error: -32601: Method not found",
    "unregistered_resource": "resources/read failed: unknown MCP server 'unconfigured'",
    "provider": "unsupported call: mcp__garminget_activities_by_date",
}


def binding(identity: dict[str, Any]) -> dict[str, Any]:
    return process_capture.binding(PROMPT.encode(), model_job.sha(identity))


def validate(
    proof: Any, identity: dict[str, Any], instructions: str
) -> tuple[str, ...]:
    try:
        codex_output.keys(
            proof,
            {
                "schema_version",
                "runtime",
                "cwd",
                "initial_request",
                "process",
                "startup_messages",
                "refusals",
                "handoffs",
                "requests",
            },
        )
        if (
            proof["schema_version"] != "fit_codex_capability_v1"
            or proof["runtime"] != identity
        ):
            raise ValueError("identity")
        codex_boundary.audit_initial_request(
            proof["initial_request"],
            instructions=instructions,
            prompt=PROMPT,
            cwd=Path(proof["cwd"]),
            model=identity["model"],
            response_schema=SCHEMA,
            tool_surface_sha256=identity["tool_surface_sha256"],
        )
        messages = tuple(proof["startup_messages"])
        if not isinstance(proof["startup_messages"], list):
            raise ValueError("diagnostics")
        result = process_capture.decode(proof["process"], binding(identity))
        if not result.process_stopped:
            raise ValueError("probe_not_terminal")
        parsed = codex_output.parse_result(
            result, SCHEMA, prompt_bytes=len(PROMPT.encode()), startup_messages=messages
        )
        if (
            parsed.value != {"ok": True}
            or parsed.tool_calls != 6
            or proof["refusals"] != REFUSALS
        ):
            raise ValueError("refusal")
        handoffs = proof["handoffs"]
        if not isinstance(handoffs, list) or len(handoffs) != 4:
            raise ValueError("handoffs")
        for i, item in enumerate(handoffs):
            codex_output.keys(
                item, {"request", "host_result", "model_output", "charged_requests"}
            )
            request = item["request"]
            fit_detail.request_value(request, item["host_result"]["parser_version"])
            codex_output.keys(
                request,
                {
                    "activity_ref",
                    "view",
                    "start_offset_seconds",
                    "end_offset_seconds",
                    "resolution_seconds",
                },
            )
            if (
                request
                != {**handoffs[0]["request"], "resolution_seconds": (1, 1, 5, 5)[i]}
                or request["view"] != "series"
                or request["start_offset_seconds"] != 0
                or request["end_offset_seconds"] != 1200
                or item["charged_requests"] != i // 2 + 1
                or type(item["charged_requests"]) is not int
            ):
                raise ValueError("handoff_binding")
            detail_transport.audit_model_output(
                item["model_output"], item["host_result"]
            )
            host = item["host_result"]
            if (
                any(host[k] != v for k, v in request.items())
                or host["status"] != "available"
                or host["error_code"] is not None
                or len(host["blocks"]) != 1200 // request["resolution_seconds"]
                or any(
                    host[k] != handoffs[0]["host_result"][k]
                    for k in ("scope_sha256", "fit_sha256")
                )
                or host["request_sha256"]
                != model_job.sha(
                    {"scope_sha256": host["scope_sha256"], "request": request}
                )
            ):
                raise ValueError("host_result_binding")
            if i % 2 and item["host_result"] != handoffs[i - 1]["host_result"]:
                raise ValueError("cache")
        requests = proof["requests"]
        if (
            not isinstance(requests, list)
            or len(requests) != 9
            or requests[0] != proof["initial_request"]
        ):
            raise ValueError("transcript")
        for i, packet in enumerate(requests[1:]):
            if any(
                packet.get(k) != requests[0].get(k)
                for k in ("model", "instructions", "tools", "text")
            ):
                raise ValueError("request_drift")
            if packet["input"][:3] != requests[0]["input"]:
                raise ValueError("input_drift")
            outputs = [
                m
                for m in packet["input"]
                if m.get("type") == "function_call_output"
                and m.get("call_id") == f"call_{i}"
            ]
            expected_output = (
                handoffs[i]["model_output"] if i < 4 else list(REFUSALS.values())[i - 4]
            )
            if len(outputs) != 1 or outputs[0]["output"] != expected_output:
                raise ValueError("missing_tool_output")
        completed = [
            e["item"]
            for e in map(codex_output.strict_json, result.stdout.decode().splitlines())
            if e.get("type") == "item.completed"
            and e.get("item", {}).get("type") == "mcp_tool_call"
        ]
        for i, item in enumerate(completed):
            if i < 4:
                if (
                    item["server"] != "fit"
                    or item["tool"] != "read_fit_detail"
                    or item["status"] != "completed"
                    or item["arguments"] != handoffs[i]["request"]
                ):
                    raise ValueError("detail_event")
            else:
                server = ("fit", "unconfigured")[i - 4]
                if (
                    item["status"] != "failed"
                    or item["tool"] != "read_mcp_resource"
                    or item["server"] != server
                    or item["arguments"]
                    != {"server": server, "uri": "file:///public-sentinel"}
                    or item["error"]["message"] != list(REFUSALS.values())[i - 3]
                ):
                    raise ValueError("refusal_event")
        return messages
    except Exception:
        raise ValueError("codex_capability_invalid") from None


def read(path: Path, identity: dict[str, Any], instructions: str) -> dict[str, Any]:
    try:
        from skills._shared.fit_weekly import storage

        storage.private_entry(path.parent, directory=True)
        value = process_capture.read_json(path, 32 * 1024 * 1024)
        validate(value, identity, instructions)
        return value
    except Exception:
        raise ValueError("codex_capability_invalid") from None
