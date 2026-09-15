"""Narrow FIT-only MCP protocol adapter; no public command or online scheduler.

The caller must reserve durable budget before opening a session or making a
call, persist Captured/CallFailure evidence, then commit the business result.
This adapter neither retries nor claims that a response is already in SQLite.
MCP text is private capture, not Garmin HTTP raw and never an AI input.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import shutil
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import (
    AbstractAsyncContextManager,
    AsyncExitStack,
    asynccontextmanager,
    contextmanager,
)
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import parent_watch, storage
from skills._shared.fit_weekly.sync_calendar import (
    InventoryRequest,
    day_value,
    valid_page,
)

MCP_COMMIT = "3610be6feed93088d85b0f35aba9d7d07c2505a7"
TOOLS = {"get_activities_by_date", "download_activity_file"}
SOURCE = Path(__file__).resolve().parents[3]
MAX_CAPTURE_BYTES = 4 * 1024 * 1024
MAX_FIT_BYTES = 128 * 1024 * 1024
SessionFactory = Callable[[dict[str, Any]], AbstractAsyncContextManager[Any]]


def token_snapshot(root: Path) -> tuple[Any, ...]:
    """Private in-memory audit only. Never persist token bytes or digests."""
    storage.private_entry(root, directory=True)
    rows = []
    for path in [root, *sorted(root.rglob("*"))]:
        directory = path.is_dir() and not path.is_symlink()
        storage.private_entry(path, directory=directory, nonempty=not directory)
        info = path.lstat()
        rows.append(
            (
                path.relative_to(root).as_posix(),
                info.st_dev,
                info.st_ino,
                info.st_uid,
                info.st_mode,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
                None if directory else storage.digest(path.read_bytes()),
            )
        )
    if not any(row[-1] is not None for row in rows):
        raise ValueError("garmin_cached_token_unavailable")
    return tuple(rows)


def launch_spec(token_root: Path, work_root: Path, *, is_cn: bool) -> dict[str, Any]:
    token_snapshot(token_root)
    storage.private_entry(work_root, directory=True)
    token_path, work_path = token_root.resolve(), work_root.resolve()
    if token_path.is_relative_to(work_path) or work_path.is_relative_to(token_path):
        raise ValueError("garmin_private_roots_overlap")
    if type(is_cn) is not bool:
        raise ValueError("garmin_region_invalid")
    command = shutil.which("uvx")
    if command is None:
        raise ValueError("garmin_offline_runtime_unavailable")
    overrides = SOURCE / "skills/garmin-sync/references/live-overrides.txt"
    guard = SOURCE / "skills/garmin-sync/scripts/mcp_server_guard.py"
    if (
        overrides.read_bytes() != b"garminconnect==0.3.9\nmcp==1.29.0\n"
        or not guard.is_file()
    ):
        raise ValueError("garmin_runtime_contract_invalid")
    return {
        "command": command,
        "args": [
            "--offline",
            "--no-config",
            "--no-env-file",
            "--no-python-downloads",
            "--python",
            "3.12",
            "--overrides",
            str(overrides),
            "--from",
            f"git+https://github.com/Taxuspt/garmin_mcp@{MCP_COMMIT}",
            "python",
            "-I",
            "-B",
            "-c",
            "import os,runpy,sys;os.umask(0o077);runpy.run_path(sys.argv[1],run_name='__main__')",
            str(guard),
        ],
        "environment": {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "GARMIN_IS_CN": "true" if is_cn else "false",
            "GARMIN_ENABLED_TOOLS": ",".join(sorted(TOOLS)),
            "GARMIN_MCP_TRANSPORT": "stdio",
            "UV_OFFLINE": "1",
            "UV_NO_PROGRESS": "1",
            "GARMINTOKENS": str(token_root.resolve()),
            "GARMIN_FIT_DOWNLOAD_DIR": str(work_root.resolve()),
        },
        "cwd": str(work_root.resolve()),
    }


def strict_object(payload: bytes) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError("garmin_response_invalid")
            result[key] = value
        return result

    try:
        if not payload or len(payload) > MAX_CAPTURE_BYTES:
            raise ValueError("size")
        result = json.loads(payload, object_pairs_hook=pairs)
        if not isinstance(result, dict):
            raise ValueError("object")
        storage.canonical(result)  # Reject NaN and infinity anywhere in capture.
        return result
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("garmin_response_invalid") from exc


def inventory_arguments(start: str, end: str, page: int, size: int) -> dict[str, Any]:
    if (
        day_value(start) > day_value(end)
        or type(page) is not int
        or page < 0
        or type(size) is not int
        or not 1 <= size <= 100
    ):
        raise ValueError("garmin_inventory_request_invalid")
    return {"start_date": start, "end_date": end, "page": page, "page_size": size}


def inventory_page(
    payload: bytes, start: str, end: str, page: int, size: int
) -> dict[str, Any]:
    inventory_arguments(start, end, page, size)
    value = strict_object(payload)
    keys = {"count", "page", "page_size", "has_more", "date_range", "activities"}
    more = value.get("has_more")
    if more is True:
        keys.add("next_page")
    if (
        set(value) != keys
        or type(more) is not bool
        or type(value["page"]) is not int
        or value["page"] != page
        or type(value["page_size"]) is not int
        or value["page_size"] != size
        or value["date_range"] != {"start": start, "end": end}
        or type(value["count"]) is not int
        or not 0 <= value["count"] <= size
        or not isinstance(value["activities"], list)
        or len(value["activities"]) != value["count"]
        or more != (value["count"] == size)
        or (
            more
            and (type(value["next_page"]) is not int or value["next_page"] != page + 1)
        )
    ):
        raise ValueError("garmin_inventory_response_invalid")
    items = []
    for item in value["activities"]:
        if (
            not isinstance(item, dict)
            or type(item.get("id")) is not int
            or not 0 < item["id"] < 10**32
        ):
            raise ValueError("garmin_inventory_response_invalid")
        stamp = item.get("start_time")
        if not isinstance(stamp, str) or not re.fullmatch(
            r"\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(?:\.\d{1,6})?", stamp
        ):
            raise ValueError("garmin_inventory_response_invalid")
        try:
            observed = datetime.fromisoformat(stamp).date().isoformat()
        except ValueError as exc:
            raise ValueError("garmin_inventory_response_invalid") from exc
        items.append({"activity_ref": str(item["id"]), "activity_date": observed})
    normalized = {"page": page, "page_size": size, "has_more": more, "items": items}
    request = InventoryRequest("adapter", start, end, f"{end}T15:00:00Z", size, 1)
    return valid_page(normalized, request, page, set())


def activity_ref(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,31}", value):
        raise ValueError("garmin_activity_ref_invalid")


def download_result(payload: bytes, reference: str, directory: Path) -> dict[str, Any]:
    activity_ref(reference)
    storage.private_entry(directory, directory=True)
    members = {p.name for p in directory.iterdir()}
    if payload == f"No fit data returned for activity {reference}".encode():
        if members:
            raise ValueError("garmin_download_conflict")
        return {
            "status": "no_fit",
            "activity_ref": reference,
            "reason": "provider_no_original",
        }
    value = strict_object(payload)
    name = f"{reference}.fit"
    path = directory / name
    if (
        set(value) != {"activity_id", "format", "file_path", "size_bytes", "message"}
        or type(value["activity_id"]) is not int
        or value["activity_id"] != int(reference)
        or value["format"] != "fit"
        or value["file_path"] != str(path.absolute())
        or value["message"] != "Activity file saved."
        or type(value["size_bytes"]) is not int
        or not 0 < value["size_bytes"] <= MAX_FIT_BYTES
        or members != {name}
    ):
        raise ValueError("garmin_download_response_invalid")
    storage.private_entry(path, nonempty=True)
    if path.stat().st_size != value["size_bytes"]:
        raise ValueError("garmin_download_size_invalid")
    data = path.read_bytes()
    storage.require_fit(data)
    with path.open("rb") as stream:
        os.fsync(stream.fileno())
    storage.sync_dir(directory)
    return {
        "status": "available",
        "activity_ref": reference,
        "relative_path": name,
        "sha256": storage.digest(data),
        "byte_size": len(data),
    }


@dataclass(frozen=True)
class Captured:
    payload: bytes
    value: dict[str, Any]


class CallFailure(ValueError):
    def __init__(
        self, code: str, payload: bytes | None = None, *, is_error: bool = False
    ):
        super().__init__(code)
        self.payload = payload
        self.is_error = is_error


class FitClient:
    def __init__(
        self,
        session: Any,
        timeout: float,
        work_root: Path,
        remaining: Callable[[], float] | None = None,
    ):
        self._session = session
        self._timeout = timeout
        self._work_root = work_root
        self._remaining = remaining

    async def _call(
        self,
        name: str,
        arguments: dict[str, Any],
        decode: Callable[[bytes], dict[str, Any]],
    ) -> Captured:
        try:
            limit = (
                min(self._timeout, self._remaining())
                if self._remaining
                else self._timeout
            )
            async with asyncio.timeout(limit):
                result = await self._session.call_tool(name, arguments=arguments)
            if self._remaining:
                self._remaining()
        except Exception:
            raise CallFailure("garmin_call_failed") from None
        content = getattr(result, "content", None)
        if (
            not isinstance(content, list)
            or len(content) != 1
            or getattr(content[0], "type", None) != "text"
            or not isinstance(getattr(content[0], "text", None), str)
            or type(getattr(result, "isError", None)) is not bool
        ):
            raise CallFailure("garmin_mcp_shape_invalid")
        try:
            payload = content[0].text.encode("utf-8")
        except UnicodeError:
            raise CallFailure("garmin_mcp_shape_invalid") from None
        if not payload or len(payload) > MAX_CAPTURE_BYTES:
            raise CallFailure("garmin_capture_size_invalid")
        if result.isError:
            raise CallFailure("garmin_mcp_error", payload, is_error=True)
        try:
            value = decode(payload)
            if self._remaining:
                self._remaining()
            return Captured(payload, value)
        except Exception:
            raise CallFailure("garmin_response_invalid", payload) from None

    async def inventory(self, start: str, end: str, page: int, size: int) -> Captured:
        args = inventory_arguments(start, end, page, size)
        return await self._call(
            "get_activities_by_date",
            args,
            lambda p: inventory_page(p, start, end, page, size),
        )

    async def download(self, reference: str, directory: Path) -> Captured:
        activity_ref(reference)
        storage.private_entry(directory, directory=True)
        resolved = directory.resolve()
        if not resolved.is_relative_to(self._work_root.resolve()) or list(
            directory.iterdir()
        ):
            raise ValueError("garmin_download_destination_invalid")
        # The upstream downloader overwrites filenames: it only receives empty,
        # per-attempt staging directories, never the content-addressed FIT store.
        args = {
            "activity_id": int(reference),
            "format": "fit",
            "output_dir": str(resolved),
        }
        return await self._call(
            "download_activity_file",
            args,
            lambda p: download_result(p, reference, resolved),
        )


@contextmanager
def sdk_diagnostics() -> Iterator[None]:
    """Redact SDK records before any handler, for this single-writer session."""
    previous = logging.getLogRecordFactory()

    def safe_record(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        if record.name == "mcp" or record.name.startswith("mcp."):
            record.msg = "garmin_sdk_diagnostic"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return record

    logging.setLogRecordFactory(safe_record)
    try:
        yield
    finally:
        logging.setLogRecordFactory(previous)


@asynccontextmanager
async def sdk_session(spec: dict[str, Any]) -> AsyncIterator[Any]:
    mcp = import_module("mcp")
    stdio = import_module("mcp.client.stdio")
    guarded = parent_watch.command([spec["command"], *spec["args"]])
    parameters = mcp.StdioServerParameters(
        command=guarded[0],
        args=guarded[1:],
        env=spec["environment"],
        cwd=spec["cwd"],
    )
    # Upstream stderr can contain private paths/profile data. Only redacted
    # structured failures escape this adapter; raw MCP results stay in capture.
    with sdk_diagnostics(), open(os.devnull, "w") as errors:
        async with stdio.stdio_client(parameters, errlog=errors) as (read, write):
            async with mcp.ClientSession(read, write) as session:
                yield session


@asynccontextmanager
async def open_session(
    token_root: Path,
    work_root: Path,
    *,
    is_cn: bool,
    timeout: float,
    factory: SessionFactory = sdk_session,
    remaining: Callable[[], float] | None = None,
) -> AsyncIterator[FitClient]:
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("garmin_timeout_invalid")
    try:
        before = token_snapshot(token_root)
        spec = launch_spec(token_root, work_root, is_cn=is_cn)
    except Exception:
        raise ValueError("garmin_session_preflight_failed") from None
    stack = AsyncExitStack()
    try:
        try:
            limit = min(timeout, remaining()) if remaining else timeout
            async with asyncio.timeout(limit):
                session = await stack.enter_async_context(factory(spec))
                if remaining:
                    remaining()
                await session.initialize()
                if remaining:
                    remaining()
                tools = await session.list_tools()
                if remaining:
                    remaining()
                names = [str(t.name) for t in tools.tools]
                if (
                    len(names) != len(TOOLS)
                    or set(names) != TOOLS
                    or getattr(tools, "nextCursor", None)
                ):
                    raise ValueError("garmin_tool_contract_invalid")
        except Exception:
            raise ValueError("garmin_session_unavailable") from None
        yield FitClient(session, timeout, work_root, remaining)
    finally:
        try:
            # Enter, initialize, calls and exit remain in one asyncio task.
            try:
                async with asyncio.timeout(timeout):
                    await stack.aclose()
            except Exception:
                raise ValueError("garmin_session_close_failed") from None
        finally:
            try:
                after = token_snapshot(token_root)
            except Exception:
                raise ValueError("garmin_token_audit_failed") from None
            if after != before:
                raise ValueError("garmin_token_changed")
