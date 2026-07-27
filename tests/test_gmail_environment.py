from __future__ import annotations

import json
from types import SimpleNamespace

from trainlab.gmail_environment import (
    GMAIL_MCP_PACKAGE,
    GMAIL_MCP_SETUP_HINT,
    inspect_gmail_environment,
    probe_gmail_environment,
)


def binding(**overrides):
    value = {
        "name": "gmail",
        "enabled": True,
        "transport": {
            "type": "stdio",
            "command": "npx",
            "args": [GMAIL_MCP_PACKAGE],
            "env": None,
            "cwd": None,
        },
    }
    value.update(overrides)
    return value


def runner(value, returncode=0):
    def invoke(*args, **kwargs):
        return SimpleNamespace(
            returncode=returncode,
            stdout=json.dumps(value) if not isinstance(value, str) else value,
            stderr="provider detail must not surface",
        )

    return invoke


class Client:
    def __init__(self, *_args, **_kwargs):
        self.closed = False
        self.calls = []

    def list_tools(self):
        return [
            {"name": name}
            for name in (
                "list_email_labels",
                "search_emails",
                "read_email",
                "get_thread",
                "send_email",
                "reply_all",
                "get_or_create_label",
                "modify_email",
                "modify_thread",
            )
        ]

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"content": [{"text": "must not be returned"}]}

    def close(self):
        self.closed = True


def test_exact_current_environment_binding_is_accepted():
    status = inspect_gmail_environment(runner=runner(binding()))
    assert status.available is True
    assert status.code == "gmail_mcp_available"
    assert GMAIL_MCP_PACKAGE in status.detail
    assert status.command == "npx" and status.args == (GMAIL_MCP_PACKAGE,)


def test_host_specific_registry_command_is_rejected():
    status = inspect_gmail_environment(runner=runner(binding(transport={**binding()["transport"], "command": "/opt/runtime/npx"})))
    assert status.available is False
    assert status.code == "gmail_mcp_binding_invalid"


def test_missing_binding_has_actionable_standard_setup_hint():
    status = inspect_gmail_environment(runner=runner({}, returncode=1))
    assert status.available is False
    assert status.code == "gmail_mcp_not_configured"
    assert status.detail == GMAIL_MCP_SETUP_HINT
    assert "codex mcp add gmail -- npx @artymclabin/gmail-mcp" in status.detail


def test_wrong_name_package_host_binding_or_disabled_state_fails_closed():
    mutations = (
        binding(name="other"),
        binding(enabled=False),
        binding(transport={**binding()["transport"], "args": ["other-package"]}),
        binding(transport={**binding()["transport"], "cwd": "/machine/path"}),
        binding(transport={**binding()["transport"], "env": {"TOKEN": "secret"}}),
        binding(transport={**binding()["transport"], "command": "/opt/custom/server"}),
    )
    for value in mutations:
        status = inspect_gmail_environment(runner=runner(value))
        assert status.available is False
        assert status.code == "gmail_mcp_binding_invalid"
        assert "secret" not in status.detail


def test_non_object_registry_payload_fails_closed():
    status = inspect_gmail_environment(runner=runner([]))
    assert status.available is False
    assert status.code == "gmail_mcp_binding_invalid"


def test_read_only_probe_discards_mailbox_payload_and_closes_client():
    clients = []

    def factory(*args, **kwargs):
        client = Client(*args, **kwargs)
        clients.append(client)
        return client

    status = probe_gmail_environment(
        runner=runner(binding()),
        client_factory=factory,
    )
    assert status.available is True and status.authenticated is True
    assert status.code == "gmail_mcp_authenticated"
    assert clients[0].calls == [("list_email_labels", {})]
    assert clients[0].closed is True
    assert "must not be returned" not in status.detail


def test_probe_never_starts_provider_when_registration_is_missing():
    started = False

    def factory(*_args, **_kwargs):
        nonlocal started
        started = True

    status = probe_gmail_environment(
        runner=runner({}, returncode=1),
        client_factory=factory,
    )
    assert status.code == "gmail_mcp_not_configured"
    assert started is False
