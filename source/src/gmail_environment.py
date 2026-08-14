"""Portable discovery and read-only probing of TrainLab's Gmail MCP binding."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .mcp import StdioMCPClient

GMAIL_MCP_SERVER_NAME = "gmail"
GMAIL_MCP_PACKAGE = "@artymclabin/gmail-mcp"
GMAIL_MCP_AUTH_COMMAND = ("npx", GMAIL_MCP_PACKAGE, "auth")
GMAIL_MCP_REGISTER_COMMAND = (
    "codex",
    "mcp",
    "add",
    GMAIL_MCP_SERVER_NAME,
    "--",
    "npx",
    GMAIL_MCP_PACKAGE,
)
GMAIL_MCP_SETUP_HINT = (
    "Run `npx @artymclabin/gmail-mcp auth`, then register the current Codex "
    "environment with `codex mcp add gmail -- npx @artymclabin/gmail-mcp`."
)
# The installed provider emits this informational line on stdout when it finds
# a project-local OAuth key file.  It is not an MCP message, but is a known,
# bounded preamble that the stdio client may safely discard.
GMAIL_MCP_OAUTH_COPY_NOTICE = (
    "OAuth keys found in current directory, copied to global config."
)


class GmailEnvironmentError(RuntimeError):
    """A stable, non-secret environment binding failure."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class GmailEnvironmentStatus:
    available: bool
    authenticated: bool | None
    code: str
    detail: str
    # These defaults retain compatibility for injected status objects while
    # allowing the inspected, verified registry binding to be used verbatim.
    command: str = "npx"
    args: tuple[str, ...] = (GMAIL_MCP_PACKAGE,)


class _CompletedProcess(Protocol):
    returncode: int
    stdout: str
    stderr: str


def _run_get(
    executable: str,
    *,
    runner: Callable[..., _CompletedProcess],
) -> _CompletedProcess:
    return runner(
        [executable, "mcp", "get", GMAIL_MCP_SERVER_NAME, "--json"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def inspect_gmail_environment(
    *,
    executable: str = "codex",
    runner: Callable[..., _CompletedProcess] = subprocess.run,
) -> GmailEnvironmentStatus:
    """Validate the current environment's portable `gmail` registration."""

    try:
        process = _run_get(executable, runner=runner)
    except (OSError, subprocess.SubprocessError):
        return GmailEnvironmentStatus(
            False, None, "gmail_mcp_not_configured", GMAIL_MCP_SETUP_HINT
        )
    if process.returncode != 0:
        return GmailEnvironmentStatus(
            False, None, "gmail_mcp_not_configured", GMAIL_MCP_SETUP_HINT
        )
    try:
        value = json.loads(process.stdout)
    except (TypeError, json.JSONDecodeError):
        return GmailEnvironmentStatus(
            False, None, "gmail_mcp_binding_invalid", GMAIL_MCP_SETUP_HINT
        )
    if not isinstance(value, dict):
        return GmailEnvironmentStatus(
            False, None, "gmail_mcp_binding_invalid", GMAIL_MCP_SETUP_HINT
        )
    transport = value.get("transport")
    command = transport.get("command") if isinstance(transport, dict) else None
    args = transport.get("args") if isinstance(transport, dict) else None
    env = transport.get("env") if isinstance(transport, dict) else None
    cwd = transport.get("cwd") if isinstance(transport, dict) else None
    portable = (
        value.get("name") == GMAIL_MCP_SERVER_NAME
        and value.get("enabled") is True
        and isinstance(transport, dict)
        and transport.get("type") == "stdio"
        and isinstance(command, str)
        and command in {"npx", "npx.cmd"}
        and args == [GMAIL_MCP_PACKAGE]
        and env in (None, {})
        and cwd is None
    )
    if not portable:
        return GmailEnvironmentStatus(
            False, None, "gmail_mcp_binding_invalid", GMAIL_MCP_SETUP_HINT
        )
    if (
        not isinstance(command, str)
        or not isinstance(args, list)
        or not all(isinstance(item, str) for item in args)
    ):
        return GmailEnvironmentStatus(
            False, None, "gmail_mcp_binding_invalid", GMAIL_MCP_SETUP_HINT
        )
    return GmailEnvironmentStatus(
        True,
        None,
        "gmail_mcp_available",
        f"current environment provides `{GMAIL_MCP_SERVER_NAME}` via `{GMAIL_MCP_PACKAGE}`",
        command,
        tuple(args),
    )


def probe_gmail_environment(
    *,
    executable: str = "codex",
    runner: Callable[..., _CompletedProcess] = subprocess.run,
    client_factory: Callable[..., Any] = StdioMCPClient,
    timeout: int = 60,
) -> GmailEnvironmentStatus:
    """Perform a read-only authenticated probe without returning mailbox data."""

    status = inspect_gmail_environment(executable=executable, runner=runner)
    if not status.available:
        return status
    client = None
    try:
        client = client_factory(
            status.command,
            list(status.args),
            timeout=timeout,
            stdout_preamble_lines=(GMAIL_MCP_OAUTH_COPY_NOTICE,),
        )
        tools = {
            str(item.get("name"))
            for item in client.list_tools()
            if isinstance(item, dict) and item.get("name")
        }
        required = {
            "list_email_labels",
            "search_emails",
            "read_email",
            "get_thread",
            "send_email",
            "reply_all",
            "get_or_create_label",
            "modify_email",
            "modify_thread",
        }
        if not required.issubset(tools):
            return GmailEnvironmentStatus(
                False,
                False,
                "gmail_mcp_capability_mismatch",
                GMAIL_MCP_SETUP_HINT,
            )
        # The result is deliberately discarded. Success proves that the token
        # can make a harmless authenticated Gmail API call.
        client.call_tool("list_email_labels", {})
    except Exception:
        return GmailEnvironmentStatus(
            False, False, "gmail_mcp_auth_required", GMAIL_MCP_SETUP_HINT
        )
    finally:
        if client is not None:
            client.close()
    return GmailEnvironmentStatus(
        True,
        True,
        "gmail_mcp_authenticated",
        "current environment Gmail MCP passed a read-only authentication probe",
    )
