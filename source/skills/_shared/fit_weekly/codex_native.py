from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import codex_boundary, codex_output, storage


def output(packet: dict[str, Any], index: int) -> list[str]:
    matches = [
        item["output"]
        for item in packet["input"]
        if item.get("type") == "custom_tool_call_output"
        and item.get("call_id") == f"call_{index}"
    ]
    if len(matches) != 1 or not isinstance(matches[0], list) or not matches[0]:
        raise ValueError("native_output_invalid")
    parts = matches[0]
    if any(set(p) != {"type", "text"} or p["type"] != "input_text" for p in parts):
        raise ValueError("native_output_invalid")
    if not re.fullmatch(
        r"Script completed\nWall time [0-9.]+ seconds\nOutput:\n", parts[0]["text"]
    ):
        raise ValueError("native_output_incomplete")
    return [p["text"] for p in parts[1:]]


def audit(
    body: dict[str, Any],
    *,
    instructions: str,
    prompt: str,
    cwd: Path,
    model: str,
    schema: dict[str, Any],
) -> None:
    if set(body) != {
        "model",
        "input",
        "tool_choice",
        "parallel_tool_calls",
        "reasoning",
        "store",
        "stream",
        "include",
        "prompt_cache_key",
        "text",
        "client_metadata",
    }:
        raise ValueError("native_request_fields")
    if (
        body["model"] != model
        or body["tool_choice"] != "auto"
        or body["parallel_tool_calls"] is not False
        or body["store"] is not False
        or body["stream"] is not True
        or body["include"] != ["reasoning.encrypted_content"]
        or body["text"].get("format") != codex_output.response_format(schema)
        or not isinstance(body["client_metadata"], dict)
        or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in body["client_metadata"].items()
        )
        or not re.fullmatch(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", body["prompt_cache_key"]
        )
    ):
        raise ValueError("native_request_options")
    messages = body["input"]
    if not isinstance(messages, list) or len(messages) != 5:
        raise ValueError("native_input")
    if storage.digest(storage.canonical(messages[0]).encode()) != SURFACE_SHA256:
        raise ValueError("native_tool_surface")
    texts: list[str] = []
    turn_id = None
    metadata_key = "internal_chat_message_metadata_passthrough"
    for message, role in zip(
        messages[1:], ("developer", "developer", "user", "user"), strict=True
    ):
        if (
            set(message) - {"type", "id", "role", "content", metadata_key}
            or message.get("type") != "message"
            or message.get("role") != role
            or not isinstance(message.get("content"), list)
            or len(message["content"]) != 1
        ):
            raise ValueError("native_input")
        if metadata_key in message:
            metadata = message[metadata_key]
            if (
                not texts
                or not isinstance(metadata, dict)
                or set(metadata) != {"turn_id"}
                or not isinstance(metadata["turn_id"], str)
                or not re.fullmatch(
                    r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", metadata["turn_id"]
                )
                or (turn_id is not None and metadata["turn_id"] != turn_id)
            ):
                raise ValueError("native_input")
            turn_id = metadata["turn_id"]
        part = message["content"][0]
        if (
            set(part) != {"type", "text"}
            or part["type"] != "input_text"
            or not isinstance(part["text"], str)
        ):
            raise ValueError("native_input")
        texts.append(part["text"])
    if (
        texts[0] != instructions.strip()
        or texts[1] != codex_boundary.PERMISSIONS_TEXT
        or texts[3] != prompt
    ):
        raise ValueError("native_input")
    codex_boundary.environment(texts[2], cwd)


def audit_probe(packet: dict[str, Any], index: int) -> None:
    calls = [
        x
        for x in packet["input"]
        if x.get("type") == "custom_tool_call" and x.get("call_id") == f"call_{index}"
    ]
    if (
        len(calls) != 1
        or calls[0].get("name") != "exec"
        or calls[0].get("namespace") != "functions"
        or calls[0].get("input") != PROBE_CODE
    ):
        raise ValueError("native_probe_call")
    if (
        storage.digest(storage.canonical(output(packet, index)).encode())
        != PROBE_SHA256
    ):
        raise ValueError("native_probe_result")


SURFACE_SHA256 = "16964170937db7558739007c275c9b7b60cc873778db933535cf14f4a1a23546"
PROBE_SHA256 = "55f36900b9e074351c522981cc32c1d21681a66b3fb6c42d23d6b08076d91fe0"
PROBE_CODE = 'text(ALL_TOOLS); text(Object.getOwnPropertyNames(globalThis).sort()); text(Object.getOwnPropertyNames(tools).sort());\nconst probes = {\n file: () => tools.read_file({path:"/public-sentinel"}),\n sql: () => tools.query({sql:"SELECT 1"}),\n shell: () => tools.exec_command({cmd:"touch /public-sentinel"}),\n patch: () => tools.apply_patch("*** Begin Patch\\n*** End Patch"),\n team: () => tools.spawn_agent({task_name:"probe",message:"probe"}),\n provider: () => tools.mcp__garmin__get_activities_by_date({}),\n node: () => require("node:fs").readFileSync("/public-sentinel"),\n process: () => process.cwd(),\n network: () => fetch("https://example.invalid"),\n dynamic_import: () => import("node:fs"),\n constructor: () => ({}).constructor.constructor("return process")(),\n resource: () => tools.read_mcp_resource({server:"fit",uri:"file:///public-sentinel"}),\n unknown_resource: () => tools.read_mcp_resource({server:"unconfigured",uri:"file:///public-sentinel"})\n};\nfor(const [name, action] of Object.entries(probes)) {try { text({name,result:await action()}); } catch(error) { text({name,error:String(error)}); }}\n'
