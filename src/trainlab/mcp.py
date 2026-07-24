from __future__ import annotations

import json
import os
import re
import select
import subprocess
import time
from pathlib import Path
from typing import Any


class MCPResponseError(RuntimeError):
    """Sanitized structured MCP failure metadata.

    Provider messages, JSON-RPC data and stderr deliberately never become the
    exception text. Existing callers that catch ``RuntimeError`` remain
    compatible while boundary adapters can use the structured fields.
    """

    def __init__(self, *, status_code: int | None = None, retry_after_seconds: int | None = None, kind: str = "protocol") -> None:
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        self.kind = kind
        super().__init__("MCP response error")


def _safe_error_metadata(value: Any) -> tuple[int | None, int | None]:
    """Extract only numeric status/retry metadata from trusted protocol slots."""

    candidates = [value]
    if isinstance(value, dict):
        candidates.extend(item for item in (value.get("data"), value.get("structuredContent")) if isinstance(item, dict))
    status: int | None = None
    retry_after: int | None = None
    for item in candidates:
        if not isinstance(item, dict):
            continue
        if status is None:
            raw_status = next((item.get(key) for key in ("status", "status_code", "statusCode", "http_status", "httpStatus") if key in item), None)
            status = _bounded_protocol_integer(raw_status, 100, 599)
        if retry_after is None:
            raw_retry = next((item.get(key) for key in ("retry_after_seconds", "retryAfterSeconds", "retry_after", "retryAfter") if key in item), None)
            retry_after = _bounded_protocol_integer(raw_retry, 0, 86_400)
    return status, retry_after


def _bounded_protocol_integer(value: Any, minimum: int, maximum: int) -> int | None:
    """Accept only bounded integers or short ASCII decimal strings."""

    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        if not re.fullmatch(r"[0-9]{1,6}", value):
            return None
        value = int(value)
    if isinstance(value, int) and minimum <= value <= maximum:
        return value
    return None


class StdioMCPClient:
    """Small deterministic MCP client used by watchdog and idempotency checks."""

    def __init__(self, command: str, args: list[str], env: dict[str, str] | None = None, timeout: int = 30):
        actual_env = os.environ.copy()
        actual_env.update(env or {})
        self.timeout = timeout
        self._closed = False
        self.process = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # Provider stderr is neither useful to the deterministic protocol nor
            # safe to surface. DEVNULL prevents a full stderr pipe from blocking
            # the child while ensuring it cannot enter parent exceptions/logs.
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=actual_env,
        )
        self._next_id = 1
        try:
            self._request(
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "trainlab-watchdog", "version": "0.1.0"},
                },
            )
            self._notify("notifications/initialized", {})
        except BaseException:
            self.close()
            raise

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
                raise MCPResponseError(kind="transport")
            if not self.process.stdout:
                break
            ready, _, _ = select.select([self.process.stdout], [], [], min(0.25, deadline - time.monotonic()))
            if not ready:
                continue
            line = self.process.stdout.readline()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                raise MCPResponseError(kind="protocol") from None
            if message.get("id") != request_id:
                continue
            if "error" in message:
                status, retry_after = _safe_error_metadata(message["error"])
                raise MCPResponseError(status_code=status, retry_after_seconds=retry_after)
            return message.get("result")
        raise TimeoutError("MCP request timed out")

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if isinstance(result, dict) and result.get("isError") is True:
            status, retry_after = _safe_error_metadata(result)
            raise MCPResponseError(status_code=status, retry_after_seconds=retry_after, kind="tool")
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {})
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise RuntimeError("MCP server returned an invalid tools/list response")
        return result["tools"]

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        self._closed = True
        process = getattr(self, "process", None)
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        # Reap after kill as well: kill alone can leave a zombie.
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        pass
        except Exception:
            # Closing is best-effort and idempotent; it must not disclose or mask
            # a prior protocol failure.
            pass
        finally:
            for name in ("stdin", "stdout", "stderr"):
                stream = getattr(process, name, None)
                try:
                    if stream is not None:
                        stream.close()
                except Exception:
                    pass

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
