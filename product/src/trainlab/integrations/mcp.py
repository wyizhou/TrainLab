"""Compatibility-neutral access to the project MCP transport primitives.

The concrete transport stays at :mod:`trainlab.mcp` for legacy callers; new
cross-layer integration code uses this stable package boundary instead.
"""

from ..mcp import (
    MCPResponseError,
    StdioMCPClient,
    dotted_get,
    format_template,
    normalize_tool_result,
)

__all__ = [
    "MCPResponseError",
    "StdioMCPClient",
    "dotted_get",
    "format_template",
    "normalize_tool_result",
]
