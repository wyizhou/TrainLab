"""Host-launched stdio bridge for one pre-bound, budgeted FIT detail tool.

This is not the weekly command or proof of a model client's capability limits.
No resources, prompts, sampling, Provider tools or arbitrary file tools exist.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from skills._shared.fit_weekly import detail_transport, fit_detail, storage

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas/fit_detail_request_v1.schema.json"
)
TOOL = "read_fit_detail"
SAFE_ERRORS = frozenset(
    {
        "detail_request_invalid",
        "detail_activity_outside_scope",
        "detail_range_outside_activity",
        "detail_budget_exceeded",
        "detail_scope_binding_invalid",
        "detail_parse_drift",
        "fit_sha_mismatch",
        "detail_stage_forbidden",
    }
)


def response(body: dict[str, Any], *, failed: bool) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=storage.canonical(body))],
        structuredContent=body,
        isError=failed,
    )


def failure(code: str) -> types.CallToolResult:
    return response(
        {"status": "unavailable", "error_code": code, "provider_calls": 0}, failed=True
    )


def answer(
    host: fit_detail.DetailHost,
    name: str,
    arguments: dict[str, Any],
    *,
    compact: bool = False,
) -> types.CallToolResult:
    if name != TOOL:
        return failure("fit_detail_tool_unknown")
    try:
        request = fit_detail.request_value(arguments)
        body = host.read(request)
        # Validate before serializing so an accidental Host regression cannot
        # turn private exception strings or undeclared data into model input.
        fit_detail.validate_result(body)
        expected_sha = storage.digest(
            storage.canonical(
                {"scope_sha256": host.scope_sha, "request": request}
            ).encode()
        )
        if (
            body["scope_sha256"] != host.scope_sha
            or body["request_sha256"] != expected_sha
            or any(body[k] != v for k, v in request.items())
        ):
            raise ValueError("fit_detail_output_binding_invalid")
        return response(
            detail_transport.pack(body) if compact else body,
            failed=body["status"] != "available",
        )
    except Exception as exc:
        code = str(exc)
        return failure(code if code in SAFE_ERRORS else "fit_detail_unavailable")


TOOL_DESCRIPTION = "Read a pre-bound weekly activity summary, laps or time-weighted series. Only supplied activity references are accepted. Offsets are seconds from activity start; start < end, range <= 1200 seconds, resolution 1 or 5. At most 20 distinct requests per week; identical requests reuse results. Authorized sport location is available when recorded. GPS endpoints are actual timestamped fixes, not averaged or interpolated, and are not the whole route. No raw FIT bytes, credentials, arbitrary files, SQL or commands. Sport bins are aggregates, not invented device samples."


def create_server(host: fit_detail.DetailHost, *, compact: bool = False) -> Server:
    server: Server = Server("TrainLab FIT Detail", version="1")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=TOOL,
                description=TOOL_DESCRIPTION,
                inputSchema=json.loads(SCHEMA_PATH.read_text()),
                annotations=types.ToolAnnotations(
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
            )
        ]

    # The SDK's default validation error echoes user-supplied values. Use the
    # same deterministic Host validator and the fixed redacted error envelope.
    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        return answer(host, name, arguments, compact=compact)

    return server


async def serve(host: fit_detail.DetailHost, *, compact: bool = False) -> None:
    server = create_server(host, compact=compact)
    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    logging.basicConfig(handlers=[logging.NullHandler()], force=True)
    parser = argparse.ArgumentParser(
        description="Internal pre-bound FIT detail stdio service"
    )
    parser.add_argument("--instance-root", required=True, type=Path)
    parser.add_argument("--period-end", required=True)
    parser.add_argument("--scope-sha256", required=True)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--stage", choices=("plan", "summary"), required=True)
    args = parser.parse_args(argv)
    try:
        # Do not resolve away symlinks before the private-instance entry check.
        root = args.instance_root
        host = fit_detail.DetailHost(
            root, args.period_end, args.scope_sha256, stage=args.stage
        )
        with storage.open_store(root) as db:
            host.scope(db)
        asyncio.run(serve(host, compact=args.compact))
        return 0
    except Exception:
        print("fit_detail_server_unavailable", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
