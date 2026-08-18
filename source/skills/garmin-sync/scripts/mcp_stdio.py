#!/usr/bin/env python3
"""Narrow stdio adapter for the one approved M9 Garmin MCP session."""

from __future__ import annotations

import os
from contextlib import AsyncExitStack
from importlib import import_module
from pathlib import Path
from types import TracebackType
from typing import Any, NamedTuple, Self

MCP_COMMIT = "3610be6feed93088d85b0f35aba9d7d07c2505a7"
RUNTIME_ROOT = Path(__file__).resolve().parents[3]
ALLOWED_TOOLS = {
    "download_activity_file",
    "get_activities_by_date",
    "get_activity_weather",
    "get_heart_rates",
    "get_hrv_data",
    "get_rhr_day",
    "get_sleep_data",
    "get_vo2max_trend",
    "get_weigh_ins",
}


class ToolResponse(NamedTuple):
    payload: bytes
    is_error: bool


def server_command(
    *, token_dir: Path | None = None, download_dir: Path | None = None
) -> dict[str, Any]:
    """Return the exact offline command and sanitized environment."""
    overrides = (
        RUNTIME_ROOT / "skills/garmin-sync/references/live-overrides.txt"
    ).resolve()
    environment = {
        "GARMIN_IS_CN": "true",
        "GARMIN_ENABLED_TOOLS": ",".join(sorted(ALLOWED_TOOLS)),
        "GARMIN_MCP_TRANSPORT": "stdio",
        "UV_OFFLINE": "1",
        "UV_NO_PROGRESS": "1",
    }
    if token_dir is not None:
        environment["GARMINTOKENS"] = str(token_dir.resolve())
    if download_dir is not None:
        environment["GARMIN_FIT_DOWNLOAD_DIR"] = str(download_dir.resolve())
    return {
        "command": "/opt/homebrew/bin/uvx",
        "args": [
            "--offline",
            "--python",
            "3.12",
            "--overrides",
            str(overrides),
            "--from",
            f"git+https://github.com/Taxuspt/garmin_mcp@{MCP_COMMIT}",
            "python",
            str(
                (
                    RUNTIME_ROOT / "skills/garmin-sync/scripts/mcp_server_guard.py"
                ).resolve()
            ),
        ],
        "environment": environment,
    }


class StdioGarminClient:
    """Small client exposing only list_tools and call_tool."""

    def __init__(self, token_dir: Path, download_dir: Path) -> None:
        self.token_dir = token_dir
        self.download_dir = download_dir
        self._stack: AsyncExitStack | None = None
        self._session: Any = None

    async def __aenter__(self) -> Self:
        try:
            mcp_module = import_module("mcp")
            stdio_module = import_module("mcp.client.stdio")
        except ImportError as exc:  # pragma: no cover - exercised by live host
            raise RuntimeError("mcp_runtime_unavailable") from exc

        command = server_command(
            token_dir=self.token_dir, download_dir=self.download_dir
        )
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            **command["environment"],
        }
        parameters = mcp_module.StdioServerParameters(
            command=command["command"],
            args=command["args"],
            env=environment,
        )
        self._stack = AsyncExitStack()
        read_stream, write_stream = await self._stack.enter_async_context(
            stdio_module.stdio_client(parameters)
        )
        self._session = await self._stack.enter_async_context(
            mcp_module.ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._stack is not None:
            await self._stack.__aexit__(exc_type, exc_value, traceback)

    async def list_tools(self) -> set[str]:
        result = await self._session.list_tools()
        return {str(tool.name) for tool in result.tools}

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResponse:
        result = await self._session.call_tool(name, arguments=arguments)
        texts = [
            str(item.text)
            for item in result.content
            if getattr(item, "type", None) == "text"
        ]
        if len(texts) != 1 or len(texts) != len(result.content):
            raise RuntimeError("mcp_response_shape_invalid")
        return ToolResponse(texts[0].encode("utf-8"), bool(result.isError))
