"""Stable access to the current-environment ``gmail`` MCP binding.

The root module remains a legacy-compatible import location.  This module is
the shared boundary for new integration code and preserves the exact server
name and package validation rules.
"""

from ..gmail_environment import (
    GMAIL_MCP_AUTH_COMMAND,
    GMAIL_MCP_OAUTH_COPY_NOTICE,
    GMAIL_MCP_PACKAGE,
    GMAIL_MCP_REGISTER_COMMAND,
    GMAIL_MCP_SERVER_NAME,
    GMAIL_MCP_SETUP_HINT,
    GmailEnvironmentError,
    GmailEnvironmentStatus,
    inspect_gmail_environment,
    probe_gmail_environment,
)

__all__ = [
    "GMAIL_MCP_AUTH_COMMAND",
    "GMAIL_MCP_PACKAGE",
    "GMAIL_MCP_OAUTH_COPY_NOTICE",
    "GMAIL_MCP_REGISTER_COMMAND",
    "GMAIL_MCP_SERVER_NAME",
    "GMAIL_MCP_SETUP_HINT",
    "GmailEnvironmentError",
    "GmailEnvironmentStatus",
    "inspect_gmail_environment",
    "probe_gmail_environment",
]
