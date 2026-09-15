from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path

import pytest

from skills._shared.fit_weekly import (
    codex_native,
    command_capability,
    command_catalog,
    command_runtime,
    storage,
)

SOURCE = Path(__file__).resolve().parents[3]


def native_packet():
    fixture = json.loads(
        (SOURCE / "tests/code/fixtures/m12_codex_native_surface_v1.json").read_text()
    )
    body = importlib.import_module("test_m12_codex_boundary").packet()
    body["model"] = "environment-model"
    instructions = body.pop("instructions")
    body.pop("tools")
    body["input"] = [
        fixture["additional_tools"],
        {
            "type": "message",
            "role": "developer",
            "content": [{"type": "input_text", "text": instructions}],
        },
    ] + body["input"]
    from skills._shared.fit_weekly import codex_output

    body["text"] = {"format": codex_output.response_format(command_capability.SCHEMA)}
    body.setdefault("parallel_tool_calls", False)
    body.setdefault("tool_choice", "auto")
    body.setdefault("reasoning", {})
    body.setdefault("include", ["reasoning.encrypted_content"])
    body.setdefault("prompt_cache_key", "00000000-0000-0000-0000-000000000000")
    body.setdefault("client_metadata", {})
    return body, instructions, body["input"][-1]["content"][0]["text"]


def test_native_complete_protocol_accepts_public_surface():
    body, instructions, prompt = native_packet()
    codex_native.audit(
        body,
        instructions=instructions,
        prompt=prompt,
        cwd=Path("/public/job"),
        model="environment-model",
        schema=command_capability.SCHEMA,
    )


@pytest.mark.parametrize(
    "mutation",
    ["extra_tool", "missing_fit", "instruction", "input", "field", "model", "schema"],
)
def test_native_protocol_rejects_extra_or_changed_model_input(mutation):
    body, instructions, prompt = native_packet()
    if mutation == "extra_tool":
        body["input"][0]["tools"].append({"name": "shell"})
    elif mutation == "missing_fit":
        body["input"][0]["tools"][0]["tools"][0]["description"] = "FIT missing"
    elif mutation == "instruction":
        body["input"][1]["content"][0]["text"] += "ambient instruction"
    elif mutation == "input":
        body["input"].append(copy.deepcopy(body["input"][-1]))
    elif mutation == "field":
        body["tools"] = []
    elif mutation == "model":
        body["model"] = "different-model"
    else:
        body["text"]["format"]["schema"] = {}
    with pytest.raises(ValueError):
        codex_native.audit(
            body,
            instructions=instructions,
            prompt=prompt,
            cwd=Path("/public/job"),
            model="environment-model",
            schema=command_capability.SCHEMA,
        )


@pytest.mark.parametrize("indices", [(2, 3, 4), (2,), (3,), (4,)])
def test_native_turn_metadata_preserves_complete_request(indices):
    body, instructions, prompt = native_packet()
    for index in indices:
        body["input"][index]["internal_chat_message_metadata_passthrough"] = {
            "turn_id": "00000000-0000-7000-8000-000000000001"
        }
    original = copy.deepcopy(body)
    codex_native.audit(
        body,
        instructions=instructions,
        prompt=prompt,
        cwd=Path("/public/job"),
        model="environment-model",
        schema=command_capability.SCHEMA,
    )
    assert body == original


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        [],
        "turn",
        {},
        {"turn_id": None},
        {"turn_id": 1},
        {"turn_id": True},
        {"turn_id": []},
        {"turn_id": ""},
        {"turn_id": "not-a-uuid"},
        {"turn_id": "00000000-0000-7000-8000-000000000001\n"},
        {"turn_id": "00000000-0000-7000-8000-000000000001", "text": "extra"},
    ],
)
def test_native_turn_metadata_rejects_unknown_structure_and_values(metadata):
    body, instructions, prompt = native_packet()
    body["input"][2]["internal_chat_message_metadata_passthrough"] = metadata
    with pytest.raises(ValueError, match="native_input"):
        codex_native.audit(
            body,
            instructions=instructions,
            prompt=prompt,
            cwd=Path("/public/job"),
            model="environment-model",
            schema=command_capability.SCHEMA,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_field",
        "instructions_metadata",
        "different_turn",
        "instructions",
        "permissions",
        "environment",
        "prompt",
        "tool",
        "content_field",
    ],
)
def test_native_metadata_does_not_bypass_message_or_tool_audit(mutation):
    body, instructions, prompt = native_packet()
    for index in (2, 3, 4):
        body["input"][index]["internal_chat_message_metadata_passthrough"] = {
            "turn_id": "00000000-0000-7000-8000-000000000001"
        }
    if mutation == "unknown_field":
        body["input"][2]["unknown_metadata"] = {}
    elif mutation == "instructions_metadata":
        body["input"][1]["internal_chat_message_metadata_passthrough"] = copy.deepcopy(
            body["input"][2]["internal_chat_message_metadata_passthrough"]
        )
    elif mutation == "different_turn":
        body["input"][4]["internal_chat_message_metadata_passthrough"]["turn_id"] = (
            "00000000-0000-7000-8000-000000000002"
        )
    elif mutation == "environment":
        body["input"][3]["content"][0]["text"] = body["input"][3]["content"][0][
            "text"
        ].replace("/public/job", "/public/other")
    elif mutation in ("instructions", "permissions", "prompt"):
        index = ("instructions", "permissions", "environment", "prompt").index(
            mutation
        ) + 1
        body["input"][index]["content"][0]["text"] += "unexpected instruction"
    elif mutation == "tool":
        body["input"][0]["tools"].append({"name": "shell"})
    else:
        body["input"][4]["content"][0]["unknown"] = "extra"
    with pytest.raises(ValueError):
        codex_native.audit(
            body,
            instructions=instructions,
            prompt=prompt,
            cwd=Path("/public/job"),
            model="environment-model",
            schema=command_capability.SCHEMA,
        )


def test_catalog_preserves_order_and_every_other_field():
    original = {
        "models": [
            {
                "slug": "second",
                "priority": 9,
                "tool_mode": "code_mode_only",
                "use_responses_lite": True,
                "apply_patch_tool_type": "freeform",
                "arbitrary_public_metadata": {"nested": [1, 2]},
            },
            {"slug": "first", "priority": 1},
        ]
    }
    raw, changes = command_catalog.derive(json.dumps(original))
    derived = json.loads(raw)
    assert len(changes) == 2
    assert [m["slug"] for m in derived["models"]] == ["second", "first"]
    for before, after in zip(original["models"], derived["models"], strict=True):
        assert after["apply_patch_tool_type"] is None
        assert {k: v for k, v in before.items() if k != "apply_patch_tool_type"} == {
            k: v for k, v in after.items() if k != "apply_patch_tool_type"
        }


def test_native_host_regression_and_frozen_source_binding(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    path = tmp_path / "source-catalog.json"
    original = '{"models":[{"slug":"public","tool_mode":"code_mode_only","use_responses_lite":true,"apply_patch_tool_type":"freeform"}]}'
    path.write_text(original)
    catalog = command_catalog.resolve(Path("/public/codex"), str(path))
    runtime = command_runtime.Runtime(
        command_runtime.CommandSpec("codex", Path("/public/codex")),
        SOURCE,
        "public",
        "public",
        settings={"native_catalog": catalog},
    )
    args = runtime.command(tmp_path, "2026-08-09T07:00:00Z", "0" * 64, tmp_path)
    flags = {
        args[i + 1].split("=", 1)[0]: args[i + 1].split("=", 1)[1]
        for i, x in enumerate(args)
        if x == "-c"
    }
    assert flags["features.code_mode_host"] == "true"
    assert flags["features.code_mode"] == "true"
    assert flags["agents.enabled"] == "false"
    assert flags["features.tool_search"] == "false"
    assert (tmp_path / "models.original.json").read_text() == original
    assert (
        storage.digest((tmp_path / "models.json").read_bytes())
        == catalog["derived_sha256"]
    )
    broken = copy.deepcopy(catalog)
    broken["original"] = original.replace("public", "other")
    with pytest.raises(ValueError):
        command_catalog.validate(broken)


def test_native_denials_bind_actual_catalog_globals_and_executed_code():
    fixture = json.loads(
        (SOURCE / "tests/code/fixtures/m12_codex_native_surface_v1.json").read_text()
    )
    packet = {
        "input": [
            {
                "type": "custom_tool_call",
                "call_id": "call_11",
                "name": "exec",
                "namespace": "functions",
                "input": fixture["probe_code"],
            },
            {
                "type": "custom_tool_call_output",
                "call_id": "call_11",
                "output": [
                    {
                        "type": "input_text",
                        "text": "Script completed\nWall time 0.1 seconds\nOutput:\n",
                    },
                    *[
                        {"type": "input_text", "text": x}
                        for x in fixture["probe_output"]
                    ],
                ],
            },
        ]
    }
    codex_native.audit_probe(packet, 11)
    packet["input"][1]["output"].pop()
    with pytest.raises(ValueError):
        codex_native.audit_probe(packet, 11)
