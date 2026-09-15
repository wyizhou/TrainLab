from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    codex_boundary,
    codex_native,
    codex_output,
    command_catalog,
    command_output,
    detail_server,
    detail_transport,
    model_job,
    process_capture,
    storage,
)

PROMPT = 'Public offline fixture. Return {"ok":true}. Do not call any tool.'
SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean", "const": True}},
    "required": ["ok"],
    "additionalProperties": False,
}
CODEX_REFUSALS = {
    "shell": "unsupported call: exec_command",
    "file_resource": "resources/read failed: resources/read failed for `fit` (file:///public-sentinel): Mcp error: -32601: Method not found",
    "unregistered_resource": "resources/read failed: unknown MCP server 'unconfigured'",
    "provider": "unsupported call: mcp__garminget_activities_by_date",
}
NATIVE_REFUSALS = {
    **CODEX_REFUSALS,
    "shell": "TypeError: tools.exec_command is not a function",
    "provider": "TypeError: tools.mcp__garmin__get_activities_by_date is not a function",
}
CLAUDE_REFUSALS = {
    name: "<tool_use_error>Error: No such tool available: "
    + tool
    + (
        ". "
        + tool
        + " exists but is not enabled in this context. Use one of the available tools instead."
        if name != "provider"
        else ""
    )
    + "</tool_use_error>"
    for name, tool in {
        "shell": "Bash",
        "file_resource": "ReadMcpResourceTool",
        "unregistered_resource": "ReadMcpResourceTool",
        "provider": "mcp__garmin__get_activities_by_date",
    }.items()
}


def binding(identity: dict[str, Any]) -> dict[str, Any]:
    return process_capture.binding(PROMPT.encode(), model_job.sha(identity))


def tool_output(packet: dict[str, Any], adapter: str, index: int) -> str:
    if adapter == "codex":
        if any(v.get("type") == "custom_tool_call_output" for v in packet["input"]):
            return "\n".join(codex_native.output(packet, index))
        matches = [
            v["output"]
            for v in packet["input"]
            if v.get("type") == "function_call_output"
            and v.get("call_id") == f"call_{index}"
        ]
    else:
        matches = [
            v["content"]
            for msg in packet["messages"]
            if msg["role"] == "user" and isinstance(msg["content"], list)
            for v in msg["content"]
            if v.get("type") == "tool_result"
            and v.get("tool_use_id") == f"call_{index}"
        ]
        matches = [
            "\n".join(v["text"] for v in x) if isinstance(x, list) else x
            for x in matches
        ]
    if len(matches) != 1 or not isinstance(matches[0], str):
        raise ValueError("tool_output")
    return matches[0]


def audit_handoff(item: Any, scope: str) -> None:
    codex_output.keys(
        item, {"request", "host_result", "model_output", "charged_requests"}
    )
    host = item["host_result"]
    detail_transport.audit_model_output(item["model_output"], host)
    if (
        host["scope_sha256"] != scope
        or any(host[k] != v for k, v in item["request"].items())
        or host["request_sha256"]
        != model_job.sha({"scope_sha256": scope, "request": item["request"]})
    ):
        raise ValueError("binding")


def validate(proof: Any, identity: dict[str, Any], instructions: str) -> None:
    try:
        codex_output.keys(
            proof,
            {
                "schema_version",
                "runtime",
                "cwd",
                "initial_request",
                "process",
                "handoffs",
                "refusals",
                "requests",
                "retry_processes",
                "retry_requests",
                "budget_scope_checks",
            },
        )
        if (
            proof["schema_version"] != "fit_command_capability_v1"
            or proof["runtime"] != identity
        ):
            raise ValueError("identity")
        adapter = identity["command"]["adapter"]
        initial = proof["initial_request"]
        settings = identity["environment_settings"]
        native = adapter == "codex" and any(
            x.get("type") == "additional_tools" for x in initial["input"]
        )
        if adapter == "codex":
            reasoning = initial.get("reasoning", {})
            if not isinstance(reasoning, dict) or set(reasoning) - {
                "summary",
                "effort",
                "context",
            }:
                raise ValueError("reasoning")
            if "effort" in reasoning and reasoning["effort"] not in {
                "none",
                "minimal",
                "low",
                "medium",
                "high",
                "xhigh",
            }:
                raise ValueError("reasoning")
            if "summary" in reasoning and reasoning["summary"] not in {
                "auto",
                "concise",
                "detailed",
            }:
                raise ValueError("reasoning")
            if "context" in reasoning and reasoning["context"] != "all_turns":
                raise ValueError("reasoning")
            for field, setting in (
                ("effort", "model_reasoning_effort"),
                ("summary", "model_reasoning_summary"),
            ):
                if setting in settings and (
                    reasoning.get(field) != settings[setting]
                    and not (settings[setting] == "none" and field not in reasoning)
                ):
                    raise ValueError("reasoning")
            text_options = initial.get("text", {})
            if set(text_options) - {"format", "verbosity"} or (
                "verbosity" in text_options
                and text_options["verbosity"] not in {"low", "medium", "high"}
            ):
                raise ValueError("verbosity")
            if (
                "model_verbosity" in settings
                and text_options.get("verbosity") != settings["model_verbosity"]
            ):
                raise ValueError("verbosity")
            if native:
                command_catalog.validate(settings["native_catalog"])
                host = identity["native_host"]
                if not isinstance(host, dict) or not re.fullmatch(
                    r"[0-9a-f]{64}", host["sha256"]
                ):
                    raise ValueError("native_host")
                codex_native.audit(
                    initial,
                    instructions=instructions,
                    prompt=PROMPT,
                    cwd=Path(proof["cwd"]),
                    model=settings.get("model", initial["model"]),
                    schema=SCHEMA,
                )
            else:
                projected = model_job.clone(initial)
                projected["reasoning"] = {"summary": "auto"}
                projected["text"].pop("verbosity", None)
                codex_boundary.audit_initial_request(
                    projected,
                    instructions=instructions,
                    prompt=PROMPT,
                    cwd=Path(proof["cwd"]),
                    model=settings.get("model", initial["model"]),
                    response_schema=SCHEMA,
                )
        elif adapter == "claude":
            system = initial["system"]
            expected = (
                instructions
                + "\nReturn exactly one JSON object matching this response schema:\n"
                + storage.canonical(codex_output.wire_schema(SCHEMA))
            )
            if (
                len(system) != 3
                or not re.fullmatch(
                    r"x-anthropic-billing-header: cc_version=[0-9]+\.[0-9]+\.[0-9]+\.[a-z0-9]+; cc_entrypoint=sdk-cli;",
                    system[0]["text"],
                )
                or system[1]["text"]
                != "You are a Claude agent, built on Anthropic's Claude Agent SDK."
                or system[2]["text"] != expected
            ):
                raise ValueError("input")
            messages = initial["messages"]
            if (
                len(messages) != 1
                or messages[0]["role"] != "user"
                or len(messages[0]["content"]) != 2
                or messages[0]["content"][1]["text"] != PROMPT
            ):
                raise ValueError("input")
            context = messages[0]["content"][0]["text"]
            match = re.fullmatch(
                r"<system-reminder>\nAs you answer the user's questions, you can use the following context:\n# currentDate\nToday's date is (\d{4}-\d{2}-\d{2})\.\n\n      IMPORTANT: this context may or may not be relevant to your tasks. You should not respond to this context unless it is highly relevant to your task.\n</system-reminder>\n\n",
                context,
            )
            if (
                match is None
                or date.fromisoformat(match[1]).isoformat() != match[1]
                or set(initial)
                - {
                    "model",
                    "messages",
                    "system",
                    "tools",
                    "metadata",
                    "max_tokens",
                    "thinking",
                    "context_management",
                    "output_config",
                    "stream",
                }
            ):
                raise ValueError("context")
            tools = initial["tools"]
            if (
                len(tools) != 1
                or tools[0]["name"] != "mcp__fit__read_fit_detail"
                or tools[0]["description"] != detail_server.TOOL_DESCRIPTION
            ):
                raise ValueError("tools")
            schema = codex_output.strict_json(
                detail_server.schema_path("fit-summary-3").read_text()
            )
            parameters = tools[0]["input_schema"]
            if parameters != schema:
                raise ValueError("tool_schema")
            chosen = settings.get("inherited_environment", {}).get(
                "ANTHROPIC_MODEL", settings.get("model")
            )
            if chosen and initial["model"] != chosen:
                raise ValueError("model")
            effort = settings.get("inherited_environment", {}).get(
                "CLAUDE_CODE_EFFORT_LEVEL", settings.get("effortLevel")
            )
            if effort and initial.get("output_config", {}).get("effort") != effort:
                raise ValueError("effort")
        else:
            raise ValueError("adapter")
        captured = process_capture.decode(
            proof["process"],
            process_capture.binding(PROMPT.encode(), model_job.sha(identity)),
        )
        if captured.process_stopped is not True:
            raise ValueError("capability_process_not_stopped")
        if command_output.parse_result(
            captured, SCHEMA, prompt_bytes=len(PROMPT.encode()), adapter=adapter
        ) != {"ok": True}:
            raise ValueError("output")
        handoffs = proof["handoffs"]
        if not isinstance(handoffs, list) or len(handoffs) != 3:
            raise ValueError("handoff")
        for item in handoffs:
            codex_output.keys(
                item, {"request", "host_result", "model_output", "charged_requests"}
            )
            detail_transport.audit_model_output(
                item["model_output"], item["host_result"]
            )
            host = item["host_result"]
            if any(host[k] != v for k, v in item["request"].items()) or host[
                "request_sha256"
            ] != model_job.sha(
                {"scope_sha256": host["scope_sha256"], "request": item["request"]}
            ):
                raise ValueError("binding")
        if (
            any(
                handoffs[0][k] != handoffs[1][k]
                for k in ("request", "host_result", "charged_requests")
            )
            or handoffs[0]["charged_requests"] != 1
            or handoffs[2]["charged_requests"] != 2
            or handoffs[0]["request"]["end_offset_seconds"] != 1200
            or handoffs[0]["request"]["start_offset_seconds"] != 0
            or handoffs[0]["request"]["resolution_seconds"] != 1
            or len(handoffs[0]["host_result"]["blocks"]) != 1200
            or handoffs[-1]["request"]["end_offset_seconds"] % 1 == 0
            or handoffs[-1]["host_result"]["parser_version"] != "fit-summary-3"
        ):
            raise ValueError("cache_tail")
        expected_refusals = (
            NATIVE_REFUSALS
            if native
            else (CODEX_REFUSALS if adapter == "codex" else CLAUDE_REFUSALS)
        )
        if set(proof["refusals"]) != set(expected_refusals) | {
            "outside_scope",
            "over_range",
            "stage_scope",
            "over_budget",
        }:
            raise ValueError("refusals")
        for name, text in expected_refusals.items():
            if proof["refusals"][name] != text:
                raise ValueError("refusal")
        for name, error in (
            ("outside_scope", "detail_activity_outside_scope"),
            ("over_range", "detail_request_invalid"),
            ("over_budget", "detail_budget_exceeded"),
        ):
            text = re.sub(
                r"\AWall time: [0-9]+(?:\.[0-9]+)? seconds\nOutput:\n",
                "",
                proof["refusals"][name],
            )
            if codex_output.strict_json(text) != {
                "status": "unavailable",
                "error_code": error,
                "provider_calls": 0,
            }:
                raise ValueError("refusal")
        requests = proof["requests"]
        if len(requests) != (13 if native else 12) or requests[0] != initial:
            raise ValueError("transcript")
        if native:
            codex_native.audit_probe(requests[-1], 11)
            for index, packet in enumerate(requests[1:], 1):
                if (
                    packet["input"][:5] != initial["input"]
                    or len(packet["input"]) != 5 + index * 2
                    or any(
                        packet.get(k) != initial.get(k)
                        for k in ("model", "text", "reasoning")
                    )
                ):
                    raise ValueError("native_transcript")
                for position, item in enumerate(packet["input"][5:]):
                    expected_type = (
                        "custom_tool_call"
                        if position % 2 == 0
                        else "custom_tool_call_output"
                    )
                    if (
                        item.get("type") != expected_type
                        or item.get("call_id") != f"call_{position // 2}"
                    ):
                        raise ValueError("native_transcript")
        expected_outputs = [x["model_output"] for x in handoffs] + [
            proof["refusals"][k]
            for k in (
                *expected_refusals,
                "outside_scope",
                "over_range",
                "stage_scope",
                "over_budget",
            )
        ]
        for index, packet in enumerate(requests[1:12]):
            shared = (
                ("model", "instructions", "tools", "text", "reasoning")
                if adapter == "codex"
                else ("model", "system", "tools", "output_config")
            )
            if (
                any(packet.get(k) != initial.get(k) for k in shared)
                or native
                and packet["input"][:5] != initial["input"]
                or tool_output(packet, adapter, index) != expected_outputs[index]
            ):
                raise ValueError("transcript")
        for mode in ("http_error", "stream_error"):
            if len(proof["retry_requests"][mode]) != 1:
                raise ValueError("retry")
            failed = process_capture.decode(
                proof["retry_processes"][mode], binding(identity)
            )
            if (
                failed.process_stopped is not True
                or failed.returncode == 0
                or failed.input_bytes != len(PROMPT.encode())
                or failed.error_code != "process_exit_nonzero"
            ):
                raise ValueError("retry_process")
        checks = proof["budget_scope_checks"]
        codex_output.keys(checks, {"stage_handoff", "fill_handoffs", "cache_handoff"})
        scope = handoffs[0]["host_result"]["scope_sha256"]
        for item in handoffs:
            audit_handoff(item, scope)
        stage = identity["stage"]
        if stage == "plan":
            if checks["stage_handoff"] is not None or codex_output.strict_json(
                re.sub(
                    r"\AWall time: [0-9]+(?:\.[0-9]+)? seconds\nOutput:\n",
                    "",
                    proof["refusals"]["stage_scope"],
                )
            ) != {
                "status": "unavailable",
                "error_code": "detail_stage_forbidden",
                "provider_calls": 0,
            }:
                raise ValueError("stage_scope")
            charged = 2
        elif stage == "summary":
            item = checks["stage_handoff"]
            audit_handoff(item, scope)
            if (
                item["model_output"] != proof["refusals"]["stage_scope"]
                or item["charged_requests"] != 3
                or item["request"]["activity_ref"]
                == handoffs[0]["request"]["activity_ref"]
            ):
                raise ValueError("stage_scope")
            charged = 3
        else:
            raise ValueError("stage")
        fill = checks["fill_handoffs"]
        if len(fill) != 20 - charged:
            raise ValueError("budget_scope")
        seen = {x["host_result"]["request_sha256"] for x in handoffs}
        if checks["stage_handoff"]:
            seen.add(checks["stage_handoff"]["host_result"]["request_sha256"])
        for index, item in enumerate(fill, charged + 1):
            audit_handoff(item, scope)
            key = item["host_result"]["request_sha256"]
            if item["charged_requests"] != index or key in seen:
                raise ValueError("budget_scope")
            seen.add(key)
        cache = checks["cache_handoff"]
        audit_handoff(cache, scope)
        if cache["charged_requests"] != 20 or any(
            cache[k] != handoffs[0][k] for k in ("request", "host_result")
        ):
            raise ValueError("cache_budget")

    except Exception:
        raise ValueError("command_capability_invalid") from None


def read(path: Path, identity: dict[str, Any], instructions: str) -> dict[str, Any]:
    storage.private_entry(path.parent, directory=True)
    value = process_capture.read_json(path, 32 * 1024 * 1024)
    validate(value, identity, instructions)
    return value
