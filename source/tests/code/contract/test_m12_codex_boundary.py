from __future__ import annotations

import copy
import importlib
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))


def module():
    return importlib.import_module("skills._shared.fit_weekly.codex_boundary")


def packet():
    tools = json.loads(
        (SOURCE / "tests/code/fixtures/m12_codex_cli_tools_v3.json").read_text()
    )
    tools.sort(key=lambda t: (t["name"] == "mcp__fit", t["name"]))
    text = (
        "<environment_context>\n  <cwd>/public/job</cwd>\n"
        "  <shell>bash</shell>\n  <current_date>2026-09-06</current_date>\n"
        "  <timezone>Asia/Hong_Kong</timezone>\n"
        "  <filesystem><workspace_roots><root>/public/job</root></workspace_roots>"
        '<permission_profile type="managed"><file_system type="restricted">'
        '<entry access="read"><special>:root</special></entry></file_system>'
        "</permission_profile></filesystem>\n</environment_context>"
    )
    return {
        "model": "public-model",
        "instructions": "Public Host instructions.",
        "tools": tools,
        "input": [
            {
                "type": "message",
                "role": role,
                "content": [{"type": "input_text", "text": value}],
            }
            for role, value in (
                ("developer", module().PERMISSIONS_TEXT),
                ("user", text),
                ("user", 'Public fixture {"ok":true}'),
            )
        ],
        "stream": True,
        "store": False,
    }


def audit(body):
    return module().audit_initial_request(
        body,
        instructions="Public Host instructions.",
        prompt='Public fixture {"ok":true}',
        cwd=Path("/public/job"),
        model="public-model",
    )


def test_current_request_surface_has_no_general_file_or_provider_access():
    result = audit(packet())
    assert result["status"] == "checked"
    assert result["fit_tools"] == ["read_fit_detail"]
    assert result["model_calls"] == result["provider_calls"] == 0
    assert result == audit(packet())


@pytest.mark.parametrize(
    "name",
    ["exec_command", "shell", "apply_patch", "view_image", "web_search", "send_email"],
)
def test_extra_builtin_is_rejected(name):
    body = packet()
    tool = copy.deepcopy(body["tools"][0])
    tool["name"] = name
    body["tools"].append(tool)
    with pytest.raises(ValueError, match="codex_capabilities_invalid"):
        audit(body)


@pytest.mark.parametrize(
    "change", ["extra_server", "extra_tool", "missing", "duplicate", "path_argument"]
)
def test_detail_and_discovery_surface_cannot_expand(change):
    body = packet()
    if change == "extra_server":
        body["tools"].append({"type": "namespace", "name": "mcp__garmin", "tools": []})
    elif change == "extra_tool":
        tool = copy.deepcopy(body["tools"][-1]["tools"][0])
        tool["name"] = "read_file"
        body["tools"][-1]["tools"].append(tool)
    elif change == "missing":
        body["tools"].pop()
    elif change == "duplicate":
        body["tools"].append(copy.deepcopy(body["tools"][0]))
    else:
        body["tools"][-1]["tools"][0]["parameters"]["properties"]["path"] = {
            "type": "string"
        }
    with pytest.raises(ValueError, match="codex_capabilities_invalid"):
        audit(body)


@pytest.mark.parametrize(
    "where",
    [
        "instructions",
        "developer",
        "user_agents",
        "user_skill",
        "extra_message",
        "image",
        "prompt",
        "cwd",
        "model",
        "writable",
        "environment_extra",
    ],
)
def test_unexpected_context_is_rejected_before_any_execution(
    where, tmp_path, monkeypatch
):
    body = packet()
    if where == "instructions":
        body["instructions"] += " Extra history."
    elif where == "developer":
        body["input"][0]["content"][0]["text"] += " Skills: private catalog"
    elif where in ("user_agents", "user_skill"):
        body["input"][1]["content"].append({"type": "input_text", "text": where})
    elif where == "extra_message":
        body["input"].append(copy.deepcopy(body["input"][-1]))
    elif where == "image":
        body["input"][1]["content"].append(
            {"type": "input_image", "image_url": "data:fixture"}
        )
    elif where == "prompt":
        body["input"][-1]["content"][0]["text"] += " altered"
    elif where == "model":
        body["model"] = "different-model"
    else:
        text = body["input"][1]["content"][0]["text"]
        if where == "cwd":
            text = text.replace("/public/job", "/another/job")
        elif where == "writable":
            text = text.replace('access="read"', 'access="write"')
        else:
            text = text.replace(
                "</environment_context>",
                "<extra>private data</extra></environment_context>",
            )
        body["input"][1]["content"][0]["text"] = text
    import subprocess

    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: pytest.fail("model started")
    )
    with pytest.raises(ValueError, match="codex_(context|capabilities)_invalid"):
        audit(body)
    assert list(tmp_path.iterdir()) == []


def test_feature_and_mcp_configuration_is_per_invocation_not_global(tmp_path):
    args = module().configuration_arguments(
        source=SOURCE,
        instance=tmp_path / "instance",
        work=tmp_path / "job",
        python=Path(sys.executable),
        period_end="2026-09-06T07:00:00Z",
        scope_sha256="a" * 64,
    )
    assert all(args[i] == "-c" for i in range(0, len(args), 2))
    parsed = {}
    for i in range(1, len(args), 2):
        key, value = args[i].split("=", 1)
        parsed[key] = tomllib.loads("value=" + value)["value"]
    assert all(parsed["features." + f] is False for f in module().DISABLED_FEATURES)
    assert parsed["mcp_servers.fit.enabled_tools"] == ["read_fit_detail"]
    assert parsed["mcp_servers.fit.command"] == sys.executable
    assert parsed["web_search"] == "disabled"
    assert parsed["project_doc_max_bytes"] == 0
    assert parsed["model_instructions_file"] == str(tmp_path / "job/instructions.txt")
    assert parsed["history.persistence"] == "none"
    assert parsed["approval_policy"] == "never"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("scope", ["", "A" * 64, "a" * 63, "a; touch file"])
def test_bad_scope_is_rejected_without_files(scope, tmp_path):
    with pytest.raises(ValueError, match="codex_scope_invalid"):
        module().configuration_arguments(
            source=SOURCE,
            instance=tmp_path / "instance",
            work=tmp_path / "job",
            python=Path(sys.executable),
            period_end="2026-09-06T07:00:00Z",
            scope_sha256=scope,
        )
    assert list(tmp_path.iterdir()) == []


def test_none_or_malformed_request_has_stable_error():
    bodies: list[Any] = [None, [], {}, {"input": "private contents"}]
    for body in bodies:
        with pytest.raises(ValueError, match="codex_(context|capabilities)_invalid"):
            audit(body)


def test_host_instruction_file_outer_whitespace_matches_cli_loading():
    module().audit_initial_request(
        packet(),
        instructions="Public Host instructions.\n",
        prompt='Public fixture {"ok":true}',
        cwd=Path("/public/job"),
        model="public-model",
    )


@pytest.mark.parametrize(
    "key", ["previous_response_id", "conversation", "prompt", "text", "extra"]
)
@pytest.mark.parametrize("value", ["public_previous_context", None])
def test_root_context_extensions_never_pass_first_request(key, value, tmp_path):
    body = packet()
    body[key] = value
    with pytest.raises(ValueError, match="codex_context_invalid"):
        audit(body)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "where",
    ["builtin", "fit_namespace", "fit_tool", "builtin_parameter", "nested_parameter"],
)
def test_all_tool_definition_text_is_bound(where):
    body = packet()
    if where == "builtin":
        target = body["tools"][0]
    elif where == "fit_namespace":
        target = body["tools"][-1]
    elif where == "fit_tool":
        target = body["tools"][-1]["tools"][0]
    elif where == "builtin_parameter":
        target = body["tools"][0]["parameters"]["properties"]["cursor"]
    else:
        tool = next(t for t in body["tools"] if t["name"] == "request_user_input")
        target = tool["parameters"]["properties"]["questions"]["items"]["properties"][
            "header"
        ]
    target["description"] += " PUBLIC_UNAPPROVED_CONTEXT_SENTINEL"
    with pytest.raises(ValueError, match="codex_capabilities_invalid"):
        audit(body)


@pytest.mark.parametrize(
    "extra",
    [
        "<?public PUBLIC_UNAPPROVED_CONTEXT_SENTINEL?>",
        "<!--PUBLIC_UNAPPROVED_CONTEXT_SENTINEL-->",
    ],
)
@pytest.mark.parametrize("location", ["prefix", "shell", "filesystem"])
def test_xml_non_element_content_cannot_hide_in_model_input(extra, location):
    body = packet()
    text = body["input"][1]["content"][0]["text"]
    if location == "prefix":
        text = extra + text
    else:
        text = text.replace("</" + location + ">", extra + "</" + location + ">")
    body["input"][1]["content"][0]["text"] = text
    with pytest.raises(ValueError, match="codex_context_invalid"):
        audit(body)


@pytest.mark.parametrize(
    "key,value",
    [
        ("tool_choice", "required"),
        ("parallel_tool_calls", True),
        ("reasoning", {"instructions": "extra"}),
        ("include", ["extra"]),
    ],
)
def test_model_option_context_cannot_expand(key, value):
    body = packet()
    body[key] = value
    with pytest.raises(ValueError, match="codex_context_invalid"):
        audit(body)


def test_known_cli_transport_options_and_tool_order_are_accepted():
    body = packet()
    body.update(
        tool_choice="auto",
        parallel_tool_calls=False,
        reasoning={"summary": "auto"},
        include=["reasoning.encrypted_content"],
        prompt_cache_key="00000000-0000-4000-8000-000000000001",
        client_metadata={"session_id": "00000000-0000-4000-8000-000000000001"},
    )
    body["tools"].reverse()
    assert audit(body)["status"] == "checked"


@pytest.mark.parametrize("stage", ["plan", "summary"])
def test_fit_startup_is_required_before_initial_model_tool_catalog(tmp_path, stage):
    args = module().configuration_arguments(
        source=SOURCE,
        instance=tmp_path / "instance",
        work=tmp_path / "job",
        python=Path(sys.executable),
        period_end="2026-09-06T07:00:00Z",
        scope_sha256="a" * 64,
        stage=stage,
    )
    settings = dict(value.split("=", 1) for value in args[1::2])
    assert json.loads(settings.get("mcp_servers.fit.required", "false")) is True
    assert json.loads(settings["mcp_servers.fit.startup_timeout_sec"]) == 10
    assert json.loads(settings["mcp_servers.fit.enabled_tools"]) == ["read_fit_detail"]
    assert json.loads(settings["mcp_servers.fit.args"])[-2:] == [stage, "--compact"]
    assert list(tmp_path.iterdir()) == []
