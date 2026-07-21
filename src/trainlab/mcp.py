from __future__ import annotations

import json
import os
import select
import subprocess
import time
from pathlib import Path
from typing import Any


class StdioMCPClient:
    """Small deterministic MCP client used by watchdog and idempotency checks."""

    def __init__(self, command: str, args: list[str], env: dict[str, str] | None = None, timeout: int = 30):
        actual_env = os.environ.copy()
        actual_env.update(env or {})
        self.timeout = timeout
        self.process = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=actual_env,
        )
        self._next_id = 1
        self._request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "trainlab-watchdog", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized", {})

    def _write(self, message: dict[str, Any]) -> None:
        if not self.process.stdin:
            raise RuntimeError("MCP stdin is unavailable")
        self.process.stdin.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        request_id = self._next_id
        self._next_id += 1
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                stderr = self.process.stderr.read() if self.process.stderr else ""
                raise RuntimeError(f"MCP server exited: {stderr[-2000:]}")
            if not self.process.stdout:
                break
            ready, _, _ = select.select([self.process.stdout], [], [], min(0.25, deadline - time.monotonic()))
            if not ready:
                continue
            line = self.process.stdout.readline()
            if not line:
                continue
            message = json.loads(line)
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(f"MCP error: {message['error']}")
            return message.get("result")
        raise TimeoutError(f"MCP request timed out: {method}")

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return self._request("tools/call", {"name": name, "arguments": arguments})

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {})
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise RuntimeError("MCP server returned an invalid tools/list response")
        return result["tools"]

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def __enter__(self) -> "StdioMCPClient":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def format_template(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, str):
        if value.startswith("{") and value.endswith("}") and value[1:-1] in variables:
            return variables[value[1:-1]]
        return value.format_map({key: str(item) for key, item in variables.items()})
    if isinstance(value, list):
        return [format_template(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: format_template(item, variables) for key, item in value.items()}
    return value


def normalize_tool_result(result: Any) -> Any:
    if isinstance(result, dict) and isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    if isinstance(result, dict) and isinstance(result.get("content"), list):
        texts = [item.get("text", "") for item in result["content"] if item.get("type") == "text"]
        if len(texts) == 1:
            try:
                return json.loads(texts[0])
            except json.JSONDecodeError:
                return texts[0]
        return texts
    return result


def dotted_get(value: Any, path: str | None) -> Any:
    if not path:
        return value
    current = value
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise KeyError(path)
    return current
