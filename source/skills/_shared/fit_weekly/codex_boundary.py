"""Pure per-job configuration and inspection of a PUBLIC offline CLI probe.

This module never starts Codex or reads user configuration, skills or auth. It
does not authorize private inference. A launcher must also isolate global user
instructions and skills, and bind its actual binary/configuration to a fresh
offline capability probe. `--ignore-user-config` alone does not do that.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from skills._shared.fit_weekly import (
    codex_output,
    detail_server,
    stage_policy,
    storage,
    sync_calendar,
)

DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "apps",
    "multi_agent",
    "multi_agent_v2",
    "hooks",
    "memories",
    "plugins",
    "remote_plugin",
    "code_mode_host",
    "code_mode",
    "skill_search",
    "skill_mcp_dependency_install",
    "goals",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "image_generation",
    "workspace_dependencies",
    "shell_snapshot",
    "view_image",
    "in_app_browser",
    "auth_elicitation",
    "tool_call_mcp_elicitation",
    "tool_suggest",
    "guardian_approval",
    "fast_mode",
    "enable_request_compression",
)
DISCOVERY_TOOLS = frozenset(
    {"list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource"}
)
NEUTRAL_TOOLS = frozenset({"update_plan", "request_user_input"})
# Public codex-cli 0.147.0 offline probe, sorted by tool name. This binds every
# description and nested parameter, not merely the names. CLI drift requires a
# new public capability review; runtime never loads a test fixture.
LEGACY_TOOL_SURFACE_SHA256 = (
    "3c89c7c9bb62202af88d4966ce3869b33ccf28824c77f9c8d5f35ee957eb1608"
)
LOCATION_TOOL_SURFACE_SHA256 = (
    "5ebf0a3762ea0f7710cdeaefcd7476f8b30a7f4a9ebbda04cdbac093f16c5011"
)
TIME_TOOL_SURFACE_SHA256 = (
    "7ed6cc527ca5f06d26627083da899e5c3ff1f58f0745e5e365f78e7978494f41"
)
TOOL_SURFACE_SHA256 = TIME_TOOL_SURFACE_SHA256
PERMISSIONS_TEXT = (
    "<permissions instructions>\n"
    "Filesystem sandboxing defines which files can be read or written. "
    "`sandbox_mode` is `read-only`: The sandbox only permits reading files. "
    "Network access is restricted.\n"
    "Approval policy is currently never. Do not provide the `sandbox_permissions` "
    "for any reason, commands will be rejected.\n"
    "</permissions instructions>"
)


def configuration_arguments(
    *,
    source: Path,
    instance: Path,
    work: Path,
    python: Path,
    period_end: str,
    scope_sha256: str,
    stage: str = "plan",
) -> list[str]:
    """Host-only argv values; no shell interpolation, writes or model launch.

    Caller resolves source/instance/work against its explicit root. These paths
    configure the child process, never the five-argument model tool interface.
    Global-doc isolation is deliberately not claimed by these settings.
    """
    stage_policy.require(stage)
    if not isinstance(scope_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", scope_sha256
    ):
        raise ValueError("codex_scope_invalid")
    if sync_calendar.weekly_slot(period_end)["end_utc"] != period_end:
        raise ValueError("codex_scope_invalid")
    if any(not p.is_absolute() for p in (source, instance, work, python)):
        raise ValueError("codex_host_path_invalid")
    config: dict[str, Any] = {f"features.{name}": False for name in DISABLED_FEATURES}
    config.update(
        {
            "web_search": "disabled",
            "project_doc_max_bytes": 0,
            "history.persistence": "none",
            "tool_output_token_limit": 1_000_000,
            "approval_policy": "never",
            "check_for_update_on_startup": False,
            "feedback.enabled": False,
            "analytics.enabled": False,
            "suppress_unstable_features_warning": True,
            "model_instructions_file": str(work / "instructions.txt"),
            "log_dir": str(work / "logs"),
            "sqlite_home": str(work / "sqlite"),
            "mcp_servers.fit.command": str(python),
            "mcp_servers.fit.args": [
                "-m",
                "skills._shared.fit_weekly.detail_server",
                "--instance-root",
                str(instance),
                "--period-end",
                period_end,
                "--scope-sha256",
                scope_sha256,
                "--stage",
                stage,
                "--compact",
            ],
            "mcp_servers.fit.env.PYTHONPATH": str(source),
            "mcp_servers.fit.env.PYTHONDONTWRITEBYTECODE": "1",
            "mcp_servers.fit.enabled_tools": [detail_server.TOOL],
            "mcp_servers.fit.default_tools_approval_mode": "auto",
            "mcp_servers.fit.required": True,
            "mcp_servers.fit.startup_timeout_sec": 10,
            "mcp_servers.fit.tool_timeout_sec": 20,
        }
    )
    return [
        part
        for k, v in config.items()
        for part in ("-c", k + "=" + json.dumps(v, ensure_ascii=False))
    ]


def require_tool_surface(tools: Any, *, expected_sha256: str | None = None) -> None:
    expected_sha256 = (
        TOOL_SURFACE_SHA256 if expected_sha256 is None else expected_sha256
    )
    if expected_sha256 not in {
        LEGACY_TOOL_SURFACE_SHA256,
        LOCATION_TOOL_SURFACE_SHA256,
        TIME_TOOL_SURFACE_SHA256,
    }:
        raise ValueError("codex_capabilities_invalid")
    if not isinstance(tools, list) or len(tools) != 6:
        raise ValueError("codex_capabilities_invalid")
    found = set()
    for tool in tools:
        name = tool["name"]
        if name in found:
            raise ValueError("codex_capabilities_invalid")
        found.add(name)
        if name in DISCOVERY_TOOLS | NEUTRAL_TOOLS:
            if (
                tool["type"] != "function"
                or tool.get("strict") is not False
                or set(tool) != {"type", "name", "description", "strict", "parameters"}
                or tool["parameters"].get("type") != "object"
                or not isinstance(tool["description"], str)
            ):
                raise ValueError("codex_capabilities_invalid")
        elif name == "mcp__fit":
            if (
                set(tool) != {"type", "name", "description", "tools"}
                or tool["type"] != "namespace"
                or len(tool["tools"]) != 1
            ):
                raise ValueError("codex_capabilities_invalid")
            detail = tool["tools"][0]
            schema = json.loads(
                detail_server.schema_path(
                    "fit-summary-3"
                    if expected_sha256 == TIME_TOOL_SURFACE_SHA256
                    else "fit-summary-2"
                ).read_text()
            )
            # Current CLI preserves structure while removing unsupported scalar
            # constraints. The actual DetailHost still enforces every limit.
            properties = schema["properties"]
            for prop in properties.values():
                for key in ("minimum", "maximum", "pattern"):
                    prop.pop(key, None)
            expected = {
                "type": "object",
                "properties": properties,
                "required": schema["required"],
                "additionalProperties": False,
            }
            parameters = detail["parameters"]
            if (
                set(detail) != {"type", "name", "description", "strict", "parameters"}
                or detail["type"] != "function"
                or detail["name"] != detail_server.TOOL
                or detail["strict"] is not False
                or set(parameters.get("required", [])) != set(expected["required"])
                or len(parameters["required"]) != len(expected["required"])
            ):
                raise ValueError("codex_capabilities_invalid")
            parameters = {**parameters, "required": expected["required"]}
            if parameters != expected:
                raise ValueError("codex_capabilities_invalid")
        else:
            raise ValueError("codex_capabilities_invalid")
    if found != DISCOVERY_TOOLS | NEUTRAL_TOOLS | {"mcp__fit"}:
        raise ValueError("codex_capabilities_invalid")
    canonical = storage.canonical(sorted(tools, key=lambda t: t["name"]))
    if storage.digest(canonical.encode()) != expected_sha256:
        raise ValueError("codex_capabilities_invalid")


def environment(text: str, cwd: Path) -> None:
    # Only CLI-generated operating context is accepted here, not business data
    # or arbitrary XML. Reject declarations/entities before parsing.
    if len(text) > 8192 or "<!" in text or "<?" in text:
        raise ValueError("codex_context_invalid")
    element = ElementTree.fromstring(text)
    expected = {"cwd", "shell", "current_date", "timezone", "filesystem"}
    if (
        element.tag != "environment_context"
        or element.attrib
        or len(element) != len(expected)
        or {x.tag for x in element} != expected
        or element.findtext("cwd") != str(cwd)
    ):
        raise ValueError("codex_context_invalid")
    for child in element:
        if child.tag != "filesystem" and (child.attrib or len(child)):
            raise ValueError("codex_context_invalid")
    if element.findtext("shell") not in ("zsh", "bash", "sh", "fish"):
        raise ValueError("codex_context_invalid")
    day = element.findtext("current_date") or ""
    if date.fromisoformat(day).isoformat() != day:
        raise ValueError("codex_context_invalid")
    ZoneInfo(element.findtext("timezone") or "")
    fs = element.find("filesystem")
    assert fs is not None
    if (element.text or "").strip() or any((x.tail or "").strip() for x in element):
        raise ValueError("codex_context_invalid")
    fs.tail = None
    expected_fs = ElementTree.fromstring(
        "<filesystem><workspace_roots><root /></workspace_roots>"
        '<permission_profile type="managed"><file_system type="restricted">'
        '<entry access="read"><special>:root</special></entry></file_system>'
        "</permission_profile></filesystem>"
    )
    root = expected_fs.find("workspace_roots/root")
    assert root is not None
    root.text = str(cwd)
    if ElementTree.tostring(fs) != ElementTree.tostring(expected_fs):
        raise ValueError("codex_context_invalid")


def audit_initial_request(
    body: Any,
    *,
    instructions: str,
    prompt: str,
    cwd: Path,
    model: str,
    response_schema: dict[str, Any] | None = None,
    tool_surface_sha256: str | None = None,
) -> dict[str, Any]:
    """Inspect one public fake-endpoint request; never a remote PASS receipt.

    Generic discovery helpers can only address the registered FIT server, whose
    resource handlers do not exist. Offline launch verification must exercise
    that refusal and reject unknown built-ins, not infer it from names alone.
    """
    try:
        require_tool_surface(body["tools"], expected_sha256=tool_surface_sha256)
    except Exception:
        raise ValueError("codex_capabilities_invalid") from None
    try:
        # A first request cannot reference a prior response/conversation. Only
        # these observed request options are accepted; unknown fields may carry
        # additional model input even when the three messages remain unchanged.
        allowed_fields = {
            "model",
            "instructions",
            "input",
            "tools",
            "store",
            "stream",
            "tool_choice",
            "parallel_tool_calls",
            "reasoning",
            "include",
            "prompt_cache_key",
            "client_metadata",
        }
        if response_schema is not None:
            allowed_fields.add("text")
            expected_text = {"format": codex_output.response_format(response_schema)}
            if storage.canonical(body.get("text")) != storage.canonical(expected_text):
                raise ValueError("response_schema")
        if set(body) - allowed_fields:
            raise ValueError("invalid")
        for key, expected in (
            ("tool_choice", "auto"),
            ("parallel_tool_calls", False),
            ("reasoning", {"summary": "auto"}),
            ("include", ["reasoning.encrypted_content"]),
        ):
            if key in body and (
                type(body[key]) is not type(expected) or body[key] != expected
            ):
                raise ValueError("invalid")
        # Transport metadata is not model input; do not echo its values into
        # diagnostics. It cannot introduce a new API request field or message.
        if "client_metadata" in body and (
            not isinstance(body["client_metadata"], dict)
            or any(
                not isinstance(k, str) or not isinstance(v, str)
                for k, v in body["client_metadata"].items()
            )
        ):
            raise ValueError("invalid")
        if "prompt_cache_key" in body and not re.fullmatch(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", body["prompt_cache_key"]
        ):
            raise ValueError("invalid")
        if (
            body["model"] != model
            or body["instructions"] != instructions.strip()
            or body["store"] is not False
            or body["stream"] is not True
            or not instructions.strip()
            or not prompt
        ):
            raise ValueError("invalid")
        messages = body["input"]
        if not isinstance(messages, list) or len(messages) != 3:
            raise ValueError("invalid")
        texts = []
        for message, role in zip(messages, ("developer", "user", "user"), strict=True):
            if (
                set(message) - {"type", "id", "role", "content"}
                or message["type"] != "message"
                or message["role"] != role
                or len(message["content"]) != 1
            ):
                raise ValueError("invalid")
            part = message["content"][0]
            if (
                set(part) != {"type", "text"}
                or part["type"] != "input_text"
                or not isinstance(part["text"], str)
            ):
                raise ValueError("invalid")
            texts.append(part["text"])
        if texts[0] != PERMISSIONS_TEXT or texts[2] != prompt:
            raise ValueError("invalid")
        environment(texts[1], cwd)
    except Exception:
        raise ValueError("codex_context_invalid") from None
    return {
        "status": "checked",
        "request_sha256": storage.digest(storage.canonical(body).encode()),
        "fit_tools": [detail_server.TOOL],
        "model_calls": 0,
        "provider_calls": 0,
    }
