from __future__ import annotations

import asyncio
import importlib
import io
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def adapter():
    return importlib.import_module("skills._shared.fit_weekly.garmin_fit")


@pytest.fixture(autouse=True)
def fake_executable(monkeypatch):
    monkeypatch.setattr(adapter().shutil, "which", lambda _: "/synthetic/bin/uvx")


def response(value, *, error=False, extra=False):
    content = [
        SimpleNamespace(
            type="text", text=value if isinstance(value, str) else json.dumps(value)
        )
    ]
    if extra:
        content.append(SimpleNamespace(type="image", data="synthetic"))
    return SimpleNamespace(content=content, isError=error)


def inventory(*, full=False):
    value = {
        "count": 1,
        "page": 0,
        "page_size": 1 if full else 10,
        "has_more": full,
        "date_range": {"start": "2026-08-01", "end": "2026-08-01"},
        "activities": [
            {
                "id": 101,
                "start_time": "2026-08-01 09:12:00",
                "name": "private synthetic name",
                "type": "hiking",
                "avg_hr_bpm": 123,
            }
        ],
    }
    if full:
        value["next_page"] = 1
    return value


def paths(tmp_path):
    token = tmp_path / "tokens"
    token.mkdir(mode=0o700)
    p = token / "garmin_tokens.json"
    p.write_text('{"synthetic":"not a real credential"}')
    p.chmod(0o600)
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    return token, work


class FakeSession:
    def __init__(self, value=None):
        self.value = response(inventory()) if value is None else value
        self.calls = []
        self.tools = {"get_activities_by_date", "download_activity_file"}
        self.closed = False
        self.task = None

    async def initialize(self):
        self.task = asyncio.current_task()

    async def list_tools(self):
        return SimpleNamespace(
            tools=[SimpleNamespace(name=x) for x in self.tools], nextCursor=None
        )

    async def call_tool(self, name, arguments):
        assert self.task is asyncio.current_task()
        self.calls.append((name, arguments))
        if isinstance(self.value, BaseException):
            raise self.value
        if callable(self.value):
            return await self.value(name, arguments)
        return self.value

    @asynccontextmanager
    async def factory(self, spec):
        try:
            yield self
        finally:
            assert self.task is None or self.task is asyncio.current_task()
            self.closed = True


def test_launch_is_portable_pinned_offline_and_does_not_inherit_secrets(
    tmp_path, monkeypatch
):
    m = adapter()
    token, work = paths(tmp_path)
    monkeypatch.setattr(m.shutil, "which", lambda _: "/synthetic/bin/uvx")
    monkeypatch.setenv("GARMIN_PASSWORD", "must-not-inherit")
    monkeypatch.setenv("GARMIN_EMAIL_FILE", "/private/forbidden")
    spec = m.launch_spec(token, work, is_cn=False)
    assert spec["command"] == "/synthetic/bin/uvx"
    assert "--offline" in spec["args"]
    assert any(m.MCP_COMMIT in x for x in spec["args"])
    assert spec["environment"]["GARMIN_IS_CN"] == "false"
    assert set(spec["environment"]["GARMIN_ENABLED_TOOLS"].split(",")) == m.TOOLS
    assert not {
        "GARMIN_EMAIL",
        "GARMIN_EMAIL_FILE",
        "GARMIN_PASSWORD",
        "GARMIN_PASSWORD_FILE",
    } & set(spec["environment"])
    assert "health" not in str(spec["args"])


def test_missing_offline_runtime_stops_without_install(tmp_path, monkeypatch):
    m = adapter()
    token, work = paths(tmp_path)
    monkeypatch.setattr(m.shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="garmin_offline_runtime_unavailable"):
        m.launch_spec(token, work, is_cn=True)


@pytest.mark.parametrize("case", ["missing", "empty", "mode", "symlink", "hardlink"])
def test_bad_token_entry_is_rejected_before_session(tmp_path, case):
    m = adapter()
    token, work = paths(tmp_path)
    p = token / "garmin_tokens.json"
    if case == "missing":
        p.unlink()
    if case == "empty":
        p.write_bytes(b"")
    if case == "mode":
        p.chmod(0o644)
    if case == "symlink":
        p.rename(token / "original")
        p.symlink_to(token / "original")
    if case == "hardlink":
        os.link(p, token / "copy")
    fake = FakeSession()

    async def run():
        async with m.open_session(
            token, work, is_cn=True, timeout=1, factory=fake.factory
        ):
            pytest.fail("must not open")

    with pytest.raises(ValueError):
        asyncio.run(run())
    assert fake.task is None and fake.calls == []


def test_inventory_projection_discards_names_and_accepts_all_sports():
    m = adapter()
    out = m.inventory_page(
        json.dumps(inventory()).encode(), "2026-08-01", "2026-08-01", 0, 10
    )
    assert out == {
        "page": 0,
        "page_size": 10,
        "has_more": False,
        "items": [{"activity_ref": "101", "activity_date": "2026-08-01"}],
    }
    assert "name" not in json.dumps(out) and "123" not in json.dumps(out)
    assert m.inventory_page(
        json.dumps(inventory(full=True)).encode(), "2026-08-01", "2026-08-01", 0, 1
    )["has_more"]


@pytest.mark.parametrize(
    "case",
    [
        "page",
        "count",
        "range",
        "date",
        "id",
        "next",
        "short_more",
        "extra",
        "error_text",
        "duplicate_json",
    ],
)
def test_inventory_contract_drift_or_error_cannot_mean_empty(case):
    m = adapter()
    value = inventory()
    if case == "page":
        value["page"] = 1
    if case == "count":
        value["count"] = 2
    if case == "range":
        value["date_range"]["end"] = "2026-08-02"
    if case == "date":
        value["activities"][0]["start_time"] = "2026-08-02 09:00:00"
    if case == "id":
        value["activities"][0]["id"] = True
    if case == "next":
        value["next_page"] = 1
    if case == "short_more":
        value["has_more"] = True
        value["next_page"] = 1
    if case == "extra":
        value["route"] = "private"
    payload = json.dumps(value).encode()
    if case == "error_text":
        payload = b"Error retrieving activities by date: synthetic"
    if case == "duplicate_json":
        payload = payload.replace(b'"count": 1', b'"count": 0, "count": 1')
    with pytest.raises(ValueError):
        m.inventory_page(payload, "2026-08-01", "2026-08-01", 0, 10)


def downloaded(work: Path):
    p = work / "101.fit"
    p.write_bytes(importlib.import_module("test_m12_storage").synthetic_fit())
    p.chmod(0o600)
    value = {
        "activity_id": 101,
        "format": "fit",
        "file_path": str(p.resolve()),
        "size_bytes": p.stat().st_size,
        "message": "Activity file saved.",
    }
    return p, value


def test_download_is_original_crc_checked_and_no_fit_is_distinct(tmp_path):
    m = adapter()
    _, work = paths(tmp_path)
    p, value = downloaded(work)
    before = p.read_bytes()
    got = m.download_result(json.dumps(value).encode(), "101", work)
    assert got["status"] == "available" and got["sha256"] == m.storage.digest(before)
    assert got["byte_size"] == len(before) and got["relative_path"] == "101.fit"
    assert p.read_bytes() == before and str(tmp_path) not in json.dumps(got)
    p.unlink()
    assert m.download_result(b"No fit data returned for activity 101", "101", work) == {
        "status": "no_fit",
        "activity_ref": "101",
        "reason": "provider_no_original",
    }
    with pytest.raises(ValueError):
        m.download_result(b"No fit data returned for activity 102", "101", work)


@pytest.mark.parametrize(
    "case",
    [
        "id",
        "path",
        "format",
        "size",
        "empty",
        "crc",
        "mode",
        "symlink",
        "hardlink",
        "extra_file",
        "error",
        "no_fit_with_file",
    ],
)
def test_download_rejects_invalid_or_conflicting_artifacts(tmp_path, case):
    m = adapter()
    _, work = paths(tmp_path)
    p, value = downloaded(work)
    if case == "id":
        value["activity_id"] = 202
    if case == "path":
        value["file_path"] = str(work.parent / "101.fit")
    if case == "format":
        value["format"] = "gpx"
    if case == "size":
        value["size_bytes"] += 1
    if case == "empty":
        p.write_bytes(b"")
    if case == "crc":
        p.write_bytes(p.read_bytes()[:-1] + b"\xff")
    if case == "mode":
        p.chmod(0o644)
    if case == "symlink":
        target = work.parent / "original.fit"
        p.rename(target)
        p.symlink_to(target)
    if case == "hardlink":
        os.link(p, work.parent / "copy.fit")
    if case == "extra_file":
        (work / "other").write_text("unexpected")
    payload = json.dumps(value).encode()
    if case == "error":
        payload = b"Error downloading activity 101: synthetic network error"
    if case == "no_fit_with_file":
        payload = b"No fit data returned for activity 101"
    with pytest.raises(ValueError):
        m.download_result(payload, "101", work)


def test_session_calls_are_same_task_and_capture_preserves_original_payload(tmp_path):
    m = adapter()
    token, work = paths(tmp_path)
    fake = FakeSession()

    async def run():
        async with m.open_session(
            token, work, is_cn=True, timeout=1, factory=fake.factory
        ) as client:
            result = await client.inventory("2026-08-01", "2026-08-01", 0, 10)
            assert result.payload == json.dumps(inventory()).encode()
            assert result.value["items"][0]["activity_ref"] == "101"

    asyncio.run(run())
    assert fake.closed and len(fake.calls) == 1


@pytest.mark.parametrize(
    "case",
    ["extra_tool", "missing_tool", "error", "exit", "shape", "timeout", "token_change"],
)
def test_session_failure_is_closed_and_never_retries(tmp_path, case):
    m = adapter()
    token, work = paths(tmp_path)
    fake = FakeSession()
    if case == "extra_tool":
        fake.tools.add("create_workout")
    if case == "missing_tool":
        fake.tools.remove("download_activity_file")
    if case == "error":
        fake.value = response("synthetic", error=True)
    if case == "exit":
        fake.value = ConnectionError("private details not in public error")
    if case == "shape":
        fake.value = response("synthetic", extra=True)
    if case == "timeout":

        async def slow(*args):
            await asyncio.sleep(1)
            return response(inventory())

        fake.value = slow

    async def run():
        async with m.open_session(
            token, work, is_cn=True, timeout=0.02, factory=fake.factory
        ) as client:
            if case == "token_change":
                (token / "garmin_tokens.json").write_text("changed synthetic")
            await client.inventory("2026-08-01", "2026-08-01", 0, 10)

    with pytest.raises(ValueError) as exc:
        asyncio.run(run())
    assert str(tmp_path) not in str(exc.value) and "private details" not in str(
        exc.value
    )
    assert fake.closed and len(fake.calls) <= 1


def test_invalid_request_is_zero_calls_and_download_never_overwrites(tmp_path):
    m = adapter()
    token, work = paths(tmp_path)
    fake = FakeSession()

    async def run():
        async with m.open_session(
            token, work, is_cn=True, timeout=1, factory=fake.factory
        ) as client:
            for start, end, page, size in [
                ("2021-12-31", "2026-08-01", 0, 10),
                ("2026-08-02", "2026-08-01", 0, 10),
                ("2026-08-01", "2026-08-01", -1, 10),
                ("2026-08-01", "2026-08-01", 0, 201),
            ]:
                with pytest.raises(ValueError):
                    await client.inventory(start, end, page, size)
            downloaded(work)
            with pytest.raises(ValueError):
                await client.download("101", work)

    asyncio.run(run())
    assert fake.calls == []


def test_empty_page_is_explicit_complete_membership():
    m = adapter()
    value = inventory()
    value["count"] = 0
    value["activities"] = []
    assert (
        m.inventory_page(json.dumps(value).encode(), "2026-08-01", "2026-08-01", 0, 10)[
            "items"
        ]
        == []
    )


def test_download_sdk_response_then_import_is_closed(tmp_path):
    m = adapter()
    token, work = paths(tmp_path)

    async def download(name, arguments):
        assert name == "download_activity_file" and arguments["format"] == "fit"
        _, value = downloaded(Path(arguments["output_dir"]))
        return response(value)

    fake = FakeSession(download)
    root = tmp_path / "store"
    m.storage.initialize(root)

    async def run():
        async with m.open_session(
            token, work, is_cn=False, timeout=1, factory=fake.factory
        ) as client:
            captured = await client.download("101", work)
            with m.storage.open_store(root) as db:
                m.storage.import_fit(
                    db,
                    root,
                    "101",
                    work / captured.value["relative_path"],
                    captured.value["sha256"],
                )
                assert m.storage.verify_fit_closure(db, root) == 1

    asyncio.run(run())
    assert fake.closed and len(fake.calls) == 1


def test_error_capture_is_available_only_on_private_exception(tmp_path):
    m = adapter()
    token, work = paths(tmp_path)
    fake = FakeSession(response("Private synthetic error content", error=True))

    async def run():
        async with m.open_session(
            token, work, is_cn=True, timeout=1, factory=fake.factory
        ) as client:
            await client.inventory("2026-08-01", "2026-08-01", 0, 10)

    with pytest.raises(m.CallFailure) as exc:
        asyncio.run(run())
    assert exc.value.payload == b"Private synthetic error content"
    assert exc.value.is_error is True
    assert str(exc.value) == "garmin_mcp_error"


def test_initialization_failure_closes_same_task(tmp_path):
    m = adapter()
    token, work = paths(tmp_path)

    class Failed(FakeSession):
        async def initialize(self):
            await super().initialize()
            raise OSError("synthetic auth failure")

    fake = Failed()

    async def run():
        async with m.open_session(
            token, work, is_cn=True, timeout=1, factory=fake.factory
        ):
            pytest.fail("failed auth cannot yield client")

    with pytest.raises(ValueError, match="garmin_session_unavailable"):
        asyncio.run(run())
    assert fake.closed and fake.calls == []


def test_real_sdk_wrapper_is_exercised_without_process_or_network(
    tmp_path, monkeypatch
):
    m = adapter()
    token, work = paths(tmp_path)
    fake = FakeSession()
    observed = {}

    @asynccontextmanager
    async def stdio(params, errlog):
        observed["params"] = params
        assert not errlog.isatty()
        yield "synthetic_read", "synthetic_write"
        observed["stdio_closed"] = True

    @asynccontextmanager
    async def client(read, write):
        assert read == "synthetic_read" and write == "synthetic_write"
        async with fake.factory({}) as opened:
            yield opened

    modules = {
        "mcp": SimpleNamespace(
            StdioServerParameters=lambda **kw: kw, ClientSession=client
        ),
        "mcp.client.stdio": SimpleNamespace(stdio_client=stdio),
    }
    monkeypatch.setattr(m, "import_module", modules.__getitem__)

    async def run():
        async with m.open_session(token, work, is_cn=True, timeout=1) as opened:
            await opened.inventory("2026-08-01", "2026-08-01", 0, 10)

    asyncio.run(run())
    assert observed["stdio_closed"] and fake.closed
    assert observed["params"]["cwd"] == str(work.resolve())
    assert len(fake.calls) == 1


def test_missing_response_envelope_is_safe_failure(tmp_path):
    m = adapter()
    token, work = paths(tmp_path)
    fake = FakeSession()
    fake.value = SimpleNamespace(content=None)

    async def run():
        async with m.open_session(
            token, work, is_cn=True, timeout=1, factory=fake.factory
        ) as client:
            await client.inventory("2026-08-01", "2026-08-01", 0, 10)

    with pytest.raises(m.CallFailure, match="garmin_mcp_shape_invalid"):
        asyncio.run(run())
    assert fake.closed and len(fake.calls) == 1


@pytest.mark.parametrize("overlap", ["same", "token_inside_work", "work_inside_token"])
def test_token_and_download_roots_cannot_overlap(tmp_path, overlap):
    m = adapter()
    token, work = paths(tmp_path)
    if overlap == "same":
        work = token
    if overlap == "token_inside_work":
        work = tmp_path
    if overlap == "work_inside_token":
        work = token / "nested"
        work.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="garmin_private_roots_overlap"):
        m.launch_spec(token, work, is_cn=True)


def test_installed_sdk_malformed_stdout_cannot_log_raw_response(tmp_path, monkeypatch):
    import anyio
    import mcp.client.stdio as stdio

    m = adapter()
    token, work = paths(tmp_path)
    marker = "PRIVATE_SYNTHETIC_RESPONSE_MUST_NOT_LOG"

    class Stdout:
        finished = False

        async def receive(self, max_bytes=65536):
            if self.finished:
                raise anyio.EndOfStream
            self.finished = True
            return (marker + "\n").encode()

        async def aclose(self):
            pass

    class Stdin:
        async def send(self, data):
            pass

        async def aclose(self):
            pass

    class Process:
        stdout = Stdout()
        stdin = Stdin()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def wait(self):
            return 0

    async def fake_process(**kwargs):
        return Process()

    monkeypatch.setattr(stdio, "_create_platform_compatible_process", fake_process)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    sdk_logger = logging.getLogger("mcp.client.stdio")
    sdk_logger.addHandler(handler)
    old_factory = logging.getLogRecordFactory()

    async def run():
        async with m.open_session(token, work, is_cn=True, timeout=0.1):
            pytest.fail("malformed SDK output cannot initialize")

    try:
        with pytest.raises(ValueError):
            asyncio.run(run())
    finally:
        sdk_logger.removeHandler(handler)
    assert marker not in stream.getvalue()
    assert "garmin_sdk_diagnostic" in stream.getvalue()
    assert logging.getLogRecordFactory() is old_factory


def test_close_error_is_redacted_without_masking_a_success_as_sent(tmp_path):
    m = adapter()
    token, work = paths(tmp_path)
    fake = FakeSession()

    @asynccontextmanager
    async def failed_close(spec):
        async with fake.factory(spec) as session:
            yield session
        raise OSError("PRIVATE_SYNTHETIC_CLOSE_MUST_NOT_LEAK")

    async def run():
        async with m.open_session(
            token, work, is_cn=True, timeout=1, factory=failed_close
        ) as client:
            await client.inventory("2026-08-01", "2026-08-01", 0, 10)

    with pytest.raises(ValueError, match="^garmin_session_close_failed$") as exc:
        asyncio.run(run())
    assert "PRIVATE" not in str(exc.value)
    assert fake.closed and len(fake.calls) == 1


@pytest.mark.parametrize("phase", ["preflight", "after_session"])
def test_token_io_error_cannot_expose_private_paths(tmp_path, monkeypatch, phase):
    m = adapter()
    token, work = paths(tmp_path)
    fake = FakeSession()
    snapshot = m.token_snapshot

    def broken(path):
        if phase == "preflight" or fake.calls:
            raise OSError("PRIVATE_SYNTHETIC_TOKEN_PATH")
        return snapshot(path)

    monkeypatch.setattr(m, "token_snapshot", broken)

    async def run():
        async with m.open_session(
            token, work, is_cn=True, timeout=1, factory=fake.factory
        ) as client:
            await client.inventory("2026-08-01", "2026-08-01", 0, 10)

    with pytest.raises(ValueError) as exc:
        asyncio.run(run())
    assert "PRIVATE" not in str(exc.value)
    assert len(fake.calls) == int(phase == "after_session")
