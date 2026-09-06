from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))


def module():
    return importlib.import_module("skills._shared.fit_weekly.codex_output")


def schema():
    return {
        "type": "object",
        "properties": {
            "report": {"type": "string", "maxLength": 512},
            "n": {"type": "integer", "minimum": 1},
        },
        "required": ["report", "n"],
        "additionalProperties": False,
    }


def events(value=None):
    return [
        {"type": "thread.started", "thread_id": "public-thread"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {
                "id": "answer",
                "type": "agent_message",
                "text": json.dumps(value or {"report": "完成", "n": 1}),
            },
        },
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 2},
        },
    ]


def stream(items):
    return ("\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n").encode()


def parse(items, **kwargs):
    from skills._shared.fit_weekly.model_process import ProcessResult

    capture = ProcessResult(0, 2, stream(items), b"stderr 500 is not a response", None)
    return module().parse_result(capture, schema(), prompt_bytes=2, **kwargs)


def call(item_id="detail", tool="read_fit_detail", server="fit", failed=False):
    item = {
        "id": item_id,
        "type": "mcp_tool_call",
        "server": server,
        "tool": tool,
        "arguments": {"activity_ref": "101"},
        "result": None,
        "error": None,
        "status": "in_progress",
    }
    done = {
        **item,
        "status": "failed" if failed else "completed",
        "result": None if failed else {"content": [], "structured_content": None},
        "error": {"message": "public refusal"} if failed else None,
    }
    return [
        {"type": "item.started", "item": item},
        {"type": "item.completed", "item": done},
    ]


def test_completed_result_and_body_error_words_are_not_transport_errors():
    output: dict[str, Any] = {"report": "500 ERROR failed 是原文说明", "n": 1}
    result = parse(events(output))
    assert result.value == output
    assert result.tool_calls == result.startup_diagnostics == 0
    assert len(result.events_sha256) == 64
    assert output["report"] not in repr(result)


def test_current_cli_cache_write_usage_is_nonnegative_accounting_not_extra_input():
    rows = events()
    rows[-1]["usage"]["cache_write_input_tokens"] = 0
    assert parse(rows).value["n"] == 1
    rows[-1]["usage"]["cache_write_input_tokens"] = -1
    with pytest.raises(ValueError, match="codex_events_invalid"):
        parse(rows)


def test_only_last_message_not_last_parseable_json_is_used():
    rows = events()
    rows.insert(
        -1,
        {
            "type": "item.completed",
            "item": {"id": "last", "type": "agent_message", "text": '{"n":'},
        },
    )
    with pytest.raises(ValueError, match="codex_result_invalid"):
        parse(rows)
    rows[-2]["item"]["text"] = '{"report":"最终", "n":2}'
    assert parse(rows).value["n"] == 2


@pytest.mark.parametrize(
    "text",
    [
        '```json\n{"report":"x","n":1}\n```',
        '{"report":"x","n":1,"n":2}',
        '{"report":"x","n":NaN}',
        '[{"report":"x","n":1}]',
        '{"report":"x","n":0}',
        '{"report":"x"}',
        '{"report":"x","n":1,"extra":true}',
    ],
)
def test_final_json_is_strict_and_business_constraints_still_apply(text):
    rows = events()
    rows[2]["item"]["text"] = text
    with pytest.raises(ValueError, match="codex_result_invalid"):
        parse(rows)


@pytest.mark.parametrize(
    "change",
    [
        "no_thread",
        "no_start",
        "no_finish",
        "two_threads",
        "two_starts",
        "two_finishes",
        "after_finish",
        "no_answer",
        "duplicate_answer",
        "unknown_event",
        "error_event",
        "turn_failed",
        "negative_usage",
        "extra_root",
        "extra_item",
    ],
)
def test_bad_event_state_never_uses_an_earlier_valid_answer(change):
    rows = events()
    if change == "no_thread":
        rows.pop(0)
    elif change == "no_start":
        rows.pop(1)
    elif change == "no_finish":
        rows.pop()
    elif change == "two_threads":
        rows.insert(1, copy.deepcopy(rows[0]))
    elif change == "two_starts":
        rows.insert(2, {"type": "turn.started"})
    elif change == "two_finishes":
        rows.append(copy.deepcopy(rows[-1]))
    elif change == "after_finish":
        rows.append(
            {
                "type": "item.completed",
                "item": {"id": "late", "type": "agent_message", "text": "{}"},
            }
        )
    elif change == "no_answer":
        rows.pop(2)
    elif change == "duplicate_answer":
        rows.insert(3, copy.deepcopy(rows[2]))
    elif change == "unknown_event":
        rows.insert(2, {"type": "future.event"})
    elif change == "error_event":
        rows.insert(2, {"type": "error", "message": "public 503"})
    elif change == "turn_failed":
        rows.insert(2, {"type": "turn.failed", "error": {"message": "public"}})
    elif change == "negative_usage":
        rows[-1]["usage"]["input_tokens"] = -1
    elif change == "extra_root":
        rows[2]["extra"] = True
    else:
        rows[2]["item"]["extra"] = True
    with pytest.raises(ValueError, match="codex_(events_invalid|turn_failed)"):
        parse(rows)


def test_only_explicit_host_bound_startup_diagnostic_is_advisory():
    diagnostic = "Public capability probe bound startup diagnostic."
    rows = events()
    error: dict[str, Any] = {
        "type": "item.completed",
        "item": {"id": "startup", "type": "error", "message": diagnostic},
    }
    rows.insert(1, error)
    with pytest.raises(ValueError, match="codex_events_invalid"):
        parse(rows)
    assert parse(rows, startup_messages=(diagnostic,)).startup_diagnostics == 1
    rows[1]["item"]["message"] += " drift"
    with pytest.raises(ValueError, match="codex_events_invalid"):
        parse(rows, startup_messages=(diagnostic,))
    rows.pop(1)
    rows.insert(2, error)
    error["item"]["message"] = diagnostic
    with pytest.raises(ValueError, match="codex_events_invalid"):
        parse(rows, startup_messages=(diagnostic,))


def test_detail_calls_are_not_answers_and_refusals_are_not_turn_failures():
    rows = events()
    rows[2:2] = call() + call("refused", failed=True)
    result = parse(rows)
    assert result.tool_calls == 2 and result.value["n"] == 1
    rows.pop(-2)
    with pytest.raises(ValueError, match="codex_events_invalid"):
        parse(rows)


@pytest.mark.parametrize(
    "change",
    [
        "open",
        "args_changed",
        "wrong_server",
        "wrong_tool",
        "result_missing",
        "error_on_success",
        "duplicate_complete",
        "update_without_start",
    ],
)
def test_tool_lifecycle_is_closed_and_consistent(change):
    rows = events()
    pair = call()
    if change == "open":
        pair.pop()
    elif change == "args_changed":
        pair[1]["item"]["arguments"] = {"activity_ref": "102"}
    elif change == "wrong_server":
        pair = call(server="garmin")
    elif change == "wrong_tool":
        pair = call(tool="send_email")
    elif change == "result_missing":
        pair[1]["item"]["result"] = None
    elif change == "error_on_success":
        pair[1]["item"]["error"] = {"message": "error"}
    elif change == "duplicate_complete":
        pair.append(copy.deepcopy(pair[1]))
    else:
        pair[0]["type"] = "item.updated"
    rows[2:2] = pair
    with pytest.raises(ValueError, match="codex_events_invalid"):
        parse(rows)


def test_denied_discovery_is_recorded_without_claiming_resource_access():
    rows = events()
    rows[2:2] = call(tool="read_mcp_resource", server="not-configured", failed=True)
    assert parse(rows).tool_calls == 1
    rows[3]["item"].update(
        status="completed",
        error=None,
        result={"content": [], "structured_content": None},
    )
    with pytest.raises(ValueError, match="codex_events_invalid"):
        parse(rows)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xff\n",
        b'{"type":"turn.started","type":"turn.completed"}\n',
        b"{}\nnot-json\n",
        b'{"type":',
    ],
)
def test_malformed_jsonl_is_not_skipped(raw):
    from skills._shared.fit_weekly.model_process import ProcessResult

    with pytest.raises(ValueError, match="codex_events_invalid"):
        module().parse_result(
            ProcessResult(0, 2, raw, b"", None), schema(), prompt_bytes=2
        )


def test_complete_last_line_does_not_require_extra_newline():
    from skills._shared.fit_weekly.model_process import ProcessResult

    raw = stream(events()).rstrip(b"\n")
    assert (
        module()
        .parse_result(ProcessResult(0, 2, raw, b"", None), schema(), prompt_bytes=2)
        .value["n"]
        == 1
    )


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
def test_unicode_business_text_is_not_split_as_jsonl_record_boundary(separator):
    value = {"report": "普通文本" + separator + "不应变成协议换行", "n": 1}
    rows = events()
    rows[2]["item"]["text"] = json.dumps(value, ensure_ascii=False)
    assert parse(rows).value == value


def test_reasoning_and_message_updates_preserve_the_completed_final_text():
    rows = events()
    rows[2:2] = [
        {
            "type": "item.completed",
            "item": {"id": "reason", "type": "reasoning", "text": "public reasoning"},
        },
        {
            "type": "item.started",
            "item": {"id": "answer", "type": "agent_message", "text": ""},
        },
        {
            "type": "item.updated",
            "item": {"id": "answer", "type": "agent_message", "text": '{"report":'},
        },
    ]
    assert parse(rows).value["n"] == 1


def test_unfinished_tool_after_an_old_answer_is_not_a_final_answer():
    rows = events()
    rows[-1:-1] = call()
    with pytest.raises(ValueError, match="codex_events_invalid"):
        parse(rows)


def test_excessive_json_nesting_is_protocol_error_not_a_declared_turn_failure():
    from skills._shared.fit_weekly.model_process import ProcessResult

    raw = b"[" * 2000 + b"0" + b"]" * 2000
    with pytest.raises(ValueError, match="codex_events_invalid"):
        module().parse_result(
            ProcessResult(0, 2, raw, b"", None), schema(), prompt_bytes=2
        )


@pytest.mark.parametrize("change", ["exit", "incomplete", "overflow", "not_stopped"])
def test_process_failure_cannot_be_overridden_by_valid_json(change):
    from skills._shared.fit_weekly.model_process import (
        ProcessInterrupted,
        ProcessResult,
    )

    result = ProcessResult(
        1 if change == "exit" else 0,
        1 if change == "incomplete" else 2,
        stream(events()),
        b"",
        "process_stdout_limit" if change == "overflow" else None,
        change != "not_stopped",
    )
    with pytest.raises(ProcessInterrupted if change == "not_stopped" else ValueError):
        module().parse_result(result, schema(), prompt_bytes=2)


def test_schema_projection_keeps_topology_and_does_not_mutate_business():
    business = schema()
    before = copy.deepcopy(business)
    business["$defs"] = {
        "part": {"type": "array", "items": {"type": "string"}, "minItems": 1}
    }
    business["properties"]["parts"] = {"$ref": "#/$defs/part"}
    business["required"].append("parts")
    wire = module().wire_schema(business)
    assert wire["required"] == business["required"]
    assert wire["properties"]["parts"] == business["properties"]["parts"]
    assert "minItems" not in wire["$defs"]["part"]
    assert business["properties"]["n"] == before["properties"]["n"]
    assert business["$defs"]["part"]["minItems"] == 1
    assert module().response_format(business) == {
        "type": "json_schema",
        "strict": True,
        "name": "codex_output_schema",
        "schema": wire,
    }


@pytest.mark.parametrize(
    "change",
    [
        "extra_schema",
        "open_object",
        "optional",
        "bad_ref",
        "no_type",
        "nonfinite",
        "nested_id",
    ],
)
def test_unsupported_schema_stops_before_output_processing(change):
    business = schema()
    if change == "extra_schema":
        business["allOf"] = [{"type": "object"}]
    elif change == "open_object":
        business["additionalProperties"] = True
    elif change == "optional":
        business["required"].pop()
    elif change == "bad_ref":
        business["properties"]["n"] = {"$ref": "https://invalid.example/schema"}
    elif change == "no_type":
        business["properties"]["n"] = {"const": 1}
    elif change == "nonfinite":
        business["properties"]["n"]["minimum"] = float("nan")
    else:
        business["properties"]["n"]["$id"] = "urn:other"
    with pytest.raises(ValueError, match="codex_response_schema_invalid"):
        module().wire_schema(business)


@pytest.mark.parametrize(
    "change",
    [
        None,
        "missing_text",
        "changed_schema",
        "strict_integer",
        "extra_format",
        "text_without_binding",
    ],
)
def test_actual_output_schema_request_is_bound_not_silently_discarded(change):
    boundary_fixture = importlib.import_module("test_m12_codex_boundary")

    from skills._shared.fit_weekly import codex_boundary

    body = boundary_fixture.packet()
    body["text"] = {"format": module().response_format(schema())}
    expected = schema()
    if change == "missing_text":
        body.pop("text")
    elif change == "changed_schema":
        body["text"]["format"]["schema"]["properties"]["n"]["type"] = "string"
    elif change == "strict_integer":
        body["text"]["format"]["strict"] = 1
    elif change == "extra_format":
        body["text"]["format"]["extra"] = "injected"
    elif change == "text_without_binding":
        expected = None

    def run():
        return codex_boundary.audit_initial_request(
            body,
            instructions="Public Host instructions.",
            prompt='Public fixture {"ok":true}',
            cwd=Path("/public/job"),
            model="public-model",
            response_schema=expected,
        )

    if change is None:
        assert run()["status"] == "checked"
    else:
        with pytest.raises(ValueError, match="codex_context_invalid"):
            run()


@pytest.mark.parametrize("invalid", [False, True])
def test_model_job_replays_parsed_success_and_failure_without_second_call(
    tmp_path, invalid
):
    fixture = importlib.import_module("test_m12_model_job")

    args = fixture.setup(tmp_path)

    class Adapter:
        profile = {
            "kind": "fake",
            "name": "event-fixture",
            "configuration_sha256": "a" * 64,
        }
        calls = 0

        def run(self, payload, detail, response_schema):
            self.calls += 1
            value = parse(events({"report": "fixture", "n": 0 if invalid else 1})).value
            return {"ok": value["n"] == 1}

    adapter = Adapter()
    args = (*args[:-1], adapter)
    first = fixture.run(args)
    second = fixture.run(args)
    assert adapter.calls == 1 and second["invocation_adapter_calls"] == 0
    assert first["status"] == second["status"] == ("failed" if invalid else "succeeded")
    assert second["receipt"]["model_attempts"] == 0
