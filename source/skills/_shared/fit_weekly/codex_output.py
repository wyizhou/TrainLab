"""Pure Structured Outputs projection and one-turn CLI result inspection.

No launcher, auth, file writes or retry. Business Schema remains authoritative;
wire projection removes only local constraints/metadata, never object topology.
An event result does not prove the launcher's capability or privacy boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from skills._shared.fit_weekly import (
    detail_transport,
    model_job,
    model_process,
    storage,
)
from skills._shared.scripts.structured_outputs_validation import (
    ALLOWED_KEYWORDS,
    require_supported_schema,
)

REMOVABLE = frozenset(
    {
        "$schema",
        "$id",
        "$comment",
        "title",
        "description",
        "examples",
        "default",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "uniqueItems",
        "pattern",
        "format",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
    }
)
DISCOVERY = frozenset(
    {"list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource"}
)


def wire_schema(business: dict[str, Any]) -> dict[str, Any]:
    """Single projection; unknown composition must be redesigned, not discarded."""
    try:
        source = model_job.clone(business)
        model_job.schema_validator(source)

        def project(node: Any) -> Any:
            if not isinstance(node, dict) or set(node) - ALLOWED_KEYWORDS - REMOVABLE:
                raise ValueError("schema")
            target: dict[str, Any] = {}
            for key, value in node.items():
                if key in REMOVABLE:
                    continue
                if key in ("properties", "$defs"):
                    target[key] = {
                        name: project(child) for name, child in value.items()
                    }
                elif key == "items":
                    target[key] = project(value)
                elif key == "anyOf":
                    target[key] = [project(child) for child in value]
                else:
                    target[key] = value
            return target

        wire = project(source)
        require_supported_schema(wire)
        return wire
    except Exception:
        raise ValueError("codex_response_schema_invalid") from None


def response_format(business: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "strict": True,
        "name": "codex_output_schema",
        "schema": wire_schema(business),
    }


def invalid_constant(value: str) -> Any:
    raise ValueError("nonfinite_json")


def strict_json(text: str) -> Any:
    value = json.loads(
        text,
        object_pairs_hook=detail_transport.unique_object,
        parse_constant=invalid_constant,
    )
    return model_job.clone(value)


@dataclass(frozen=True)
class ParsedOutput:
    value: dict[str, Any] = field(repr=False)
    events_sha256: str
    startup_diagnostics: int
    tool_calls: int


class DeclaredTurnFailure(Exception):
    """A typed CLI failure, not a Python parser/runtime exception."""


def keys(value: Any, expected: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("event_shape")


def check_item(item: Any) -> None:
    base = {"id", "type"}
    if (
        not isinstance(item, dict)
        or not isinstance(item.get("id"), str)
        or not item["id"]
    ):
        raise ValueError("item")
    kind = item["type"]
    if kind in ("agent_message", "reasoning"):
        keys(item, base | {"text"})
        if not isinstance(item["text"], str):
            raise ValueError("text")
    elif kind == "error":
        keys(item, base | {"message"})
        if not isinstance(item["message"], str):
            raise ValueError("error")
    elif kind == "todo_list":
        keys(item, base | {"items"})
        if not isinstance(item["items"], list):
            raise ValueError("todo")
        for todo in item["items"]:
            keys(todo, {"text", "completed"})
            if not isinstance(todo["text"], str) or type(todo["completed"]) is not bool:
                raise ValueError("todo")
    elif kind == "mcp_tool_call":
        keys(item, base | {"server", "tool", "arguments", "status", "result", "error"})
        if any(
            not isinstance(item[k], str) or not item[k] for k in ("server", "tool")
        ) or not isinstance(item["arguments"], dict):
            raise ValueError("tool")
        if item["tool"] not in DISCOVERY and (item["server"], item["tool"]) != (
            "fit",
            "read_fit_detail",
        ):
            raise ValueError("tool")
        status = item["status"]
        if status == "in_progress":
            if item["result"] is not None or item["error"] is not None:
                raise ValueError("tool_pending")
        elif status == "completed":
            if (
                item["server"] != "fit"
                or not isinstance(item["result"], dict)
                or item["error"] is not None
            ):
                raise ValueError("tool_result")
        elif status == "failed":
            keys(item["error"], {"message"})
            if item["result"] is not None or not isinstance(
                item["error"]["message"], str
            ):
                raise ValueError("tool_error")
        else:
            raise ValueError("tool_status")
    else:
        raise ValueError("unexpected_item")


def final_message(
    raw: bytes, startup_messages: tuple[str, ...]
) -> tuple[str, int, int]:
    """Validate one closed turn. Never search backwards for parseable JSON."""
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= 67_108_864:
            raise ValueError("stream")
        if (
            type(startup_messages) is not tuple
            or len(set(startup_messages)) != len(startup_messages)
            or any(not isinstance(m, str) or not m for m in startup_messages)
        ):
            raise ValueError("startup_binding")
        # JSONL is separated by ASCII LF, not Unicode separators inside text.
        rows = raw.decode("utf-8").split("\n")
        if rows[-1] == "":
            rows.pop()
        if not rows or len(rows) > 100_000:
            raise ValueError("stream")
        state = "new"
        pending: dict[str, Any] = {}
        completed: set[str] = set()
        message: str | None = None
        last_kind = ""
        diagnostic_count = tool_count = 0
        for row in rows:
            event = strict_json(row)
            kind = event["type"]
            if state == "done":
                raise ValueError("after_terminal")
            if kind in ("error", "turn.failed"):
                raise DeclaredTurnFailure()
            if kind == "thread.started":
                keys(event, {"type", "thread_id"})
                if (
                    state != "new"
                    or not isinstance(event["thread_id"], str)
                    or not event["thread_id"]
                ):
                    raise ValueError("thread")
                state = "thread"
            elif kind == "turn.started":
                keys(event, {"type"})
                if state != "thread":
                    raise ValueError("turn")
                state = "running"
            elif kind == "turn.completed":
                keys(event, {"type", "usage"})
                usage = event["usage"]
                if (
                    state != "running"
                    or pending
                    or message is None
                    or last_kind != "agent_message"
                    or not isinstance(usage, dict)
                ):
                    raise ValueError("terminal")
                if (
                    set(usage)
                    - {
                        "input_tokens",
                        "cached_input_tokens",
                        "cache_write_input_tokens",
                        "output_tokens",
                        "reasoning_output_tokens",
                    }
                    or not {"input_tokens", "cached_input_tokens", "output_tokens"}
                    <= set(usage)
                    or any(type(v) is not int or v < 0 for v in usage.values())
                ):
                    raise ValueError("usage")
                state = "done"
            elif kind in ("item.started", "item.updated", "item.completed"):
                keys(event, {"type", "item"})
                item = event["item"]
                check_item(item)
                identity, item_kind = item["id"], item["type"]
                if identity in completed or state not in ("thread", "running"):
                    raise ValueError("item_lifecycle")
                if state == "thread":
                    if (
                        kind != "item.completed"
                        or item_kind != "error"
                        or item["message"] not in startup_messages
                    ):
                        raise ValueError("startup_diagnostic")
                    completed.add(identity)
                    diagnostic_count += 1
                    continue
                if item_kind == "error":
                    raise ValueError("running_error")
                if kind == "item.started":
                    if identity in pending or (
                        item_kind == "mcp_tool_call" and item["status"] != "in_progress"
                    ):
                        raise ValueError("item_started")
                    pending[identity] = item
                    continue
                previous = pending.get(identity)
                if kind == "item.updated" and previous is None:
                    raise ValueError("item_update")
                if previous is not None and previous["type"] != item_kind:
                    raise ValueError("item_type_changed")
                if item_kind == "mcp_tool_call":
                    if (
                        previous is None
                        or any(
                            storage.canonical(previous[k]) != storage.canonical(item[k])
                            for k in ("server", "tool", "arguments")
                        )
                        or (kind == "item.completed")
                        != (item["status"] in ("completed", "failed"))
                    ):
                        raise ValueError("tool_lifecycle")
                if kind == "item.updated":
                    pending[identity] = item
                    continue
                pending.pop(identity, None)
                completed.add(identity)
                last_kind = item_kind
                if item_kind == "agent_message":
                    message = item["text"]
                elif item_kind == "mcp_tool_call":
                    tool_count += 1
            else:
                raise ValueError("event_type")
        if state != "done" or message is None:
            raise ValueError("incomplete_stream")
        return message, diagnostic_count, tool_count
    except DeclaredTurnFailure:
        raise ValueError("codex_turn_failed") from None
    except Exception:
        raise ValueError("codex_events_invalid") from None


def parse_result(
    process: model_process.ProcessResult,
    business_schema: dict[str, Any],
    *,
    prompt_bytes: int,
    startup_messages: tuple[str, ...] = (),
) -> ParsedOutput:
    """Caller persists private evidence; this function never upgrades unknown.

    startup_messages must be exact diagnostics already bound by Host's public
    capability check, not strings discovered from this attempt or model output.
    Default is none. Result validity never substitutes for launcher isolation.
    """
    if process.process_stopped is not True:
        raise model_process.ProcessInterrupted(process)
    if (
        type(prompt_bytes) is not int
        or not 0 < prompt_bytes <= 16_777_216
        or type(process.returncode) is not int
        or process.returncode != 0
        or process.error_code is not None
        or type(process.input_bytes) is not int
        or process.input_bytes != prompt_bytes
    ):
        raise ValueError("codex_process_invalid")
    wire = wire_schema(business_schema)
    message, diagnostics, calls = final_message(process.stdout, startup_messages)
    try:
        value = strict_json(message)
        model_job.schema_validator(wire).validate(value)
        model_job.schema_validator(business_schema).validate(value)
        if not isinstance(value, dict):
            raise ValueError("result")
    except Exception:
        raise ValueError("codex_result_invalid") from None
    return ParsedOutput(value, storage.digest(process.stdout), diagnostics, calls)
