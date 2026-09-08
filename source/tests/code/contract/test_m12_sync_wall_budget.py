"""Durable collection deadline: synthetic clocks and real cancellation only."""

import asyncio
import importlib
import json
import multiprocessing
import os
import time
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest

fixture = importlib.import_module("test_m12_fit_sync")


def test_total_budget_required_before_any_write(tmp_path, monkeypatch):
    root, token, spec = fixture.setup(tmp_path, monkeypatch)
    before = (root / "trainlab-fit.db").read_bytes()
    fake = fixture.FakeMCP(root, ())
    with pytest.raises(ValueError, match="budget"):
        fixture.run(root, token, replace(spec, total_timeout_seconds=None), fake)
    assert not fake.starts
    assert (root / "trainlab-fit.db").read_bytes() == before


@pytest.mark.parametrize("phase", ["initialize", "inventory", "download"])
def test_total_deadline_cancels_wait_and_keeps_session_audit(
    tmp_path, monkeypatch, phase
):
    root, token, spec = fixture.setup(tmp_path, monkeypatch)
    spec = replace(spec, total_timeout_seconds=0.15, timeout_seconds=2)
    fake = fixture.FakeMCP(root, ("101",))
    original = fake.call_tool

    async def slow_initialize():
        await asyncio.sleep(0.4)

    async def slow_call(name, arguments):
        if (phase == "inventory" and name == "get_activities_by_date") or (
            phase == "download" and name == "download_activity_file"
        ):
            await asyncio.sleep(0.4)
        return await original(name, arguments)

    if phase == "initialize":
        monkeypatch.setattr(fake, "initialize", slow_initialize)
    else:
        monkeypatch.setattr(fake, "call_tool", slow_call)
    with pytest.raises(ValueError):
        fixture.run(root, token, spec, fake)
    assert fake.starts == fake.closed == 1
    before = list(fake.calls)
    moved = root.with_name("moved")
    root.rename(moved)
    fake.root = moved
    with pytest.raises(ValueError, match="budget"):
        fixture.run(moved, token, spec, fake)
    assert fake.starts == 1 and fake.calls == before


def test_continuous_short_calls_share_one_deadline(tmp_path, monkeypatch):
    root, token, spec = fixture.setup(tmp_path, monkeypatch)
    spec = replace(spec, total_timeout_seconds=0.25, timeout_seconds=2)
    fake = fixture.FakeMCP(root)
    original = fake.call_tool

    async def slow(name, arguments):
        await asyncio.sleep(0.1)
        return await original(name, arguments)

    monkeypatch.setattr(fake, "call_tool", slow)
    with pytest.raises(ValueError):
        fixture.run(root, token, spec, fake)
    assert len(fake.calls) <= 2 and fake.closed == 1


def test_blocking_late_provider_return_is_not_saved_as_success(tmp_path, monkeypatch):
    root, token, spec = fixture.setup(tmp_path, monkeypatch)
    spec = replace(spec, total_timeout_seconds=0.15)
    fake = fixture.FakeMCP(root, ())
    original = fake.call_tool

    async def blocking(name, arguments):
        time.sleep(0.2)
        return await original(name, arguments)

    monkeypatch.setattr(fake, "call_tool", blocking)
    with pytest.raises(ValueError):
        fixture.run(root, token, spec, fake)
    assert fake.closed == 1
    with fixture.modules()[0].open_store(root) as db:
        journal = fixture.engine().Journal(db, root, spec)
        assert journal.recovered(journal.intents[-1])["status"] == "error"
        assert fixture.engine().document(db, journal.key + ":complete") is None


def test_required_guard_resources_are_in_closed_set():
    from pathlib import Path

    from skills._shared.fit_weekly import runtime_resources

    source = Path(__file__).resolve().parents[3]
    paths = {
        p.relative_to(source).as_posix()
        for p in runtime_resources.files(source, collection=True)
    }
    assert "skills/garmin-sync/scripts/mcp_server_guard.py" in paths
    assert "skills/garmin-sync/references/live-overrides.txt" in paths


@pytest.mark.parametrize("boundary", ["initialize_intent", "inventory_capture"])
def test_slow_durable_write_cannot_launch_next_provider(
    tmp_path, monkeypatch, boundary
):
    root, token, spec = fixture.setup(tmp_path, monkeypatch)
    spec = replace(spec, total_timeout_seconds=10)
    module = fixture.engine()
    now = [time.time()]
    mono = [time.monotonic()]
    monkeypatch.setattr(module.time, "time", lambda: now[0])
    monkeypatch.setattr(module.time, "monotonic", lambda: mono[0])
    original = module.put

    def slow(db, key, value):
        result = original(db, key, value)
        if (
            boundary == "initialize_intent" and value.get("call_kind") == "initialize"
        ) or (
            boundary == "inventory_capture" and "items" in (value.get("value") or {})
        ):
            # Wall-clock rollback in-process must not refresh the monotonic budget.
            mono[0] += 11
        return result

    monkeypatch.setattr(module, "put", slow)
    fake = fixture.FakeMCP(root, ("101",))
    with pytest.raises(ValueError):
        fixture.run(root, token, spec, fake)
    assert fake.starts == fake.closed == (0 if boundary == "initialize_intent" else 1)
    assert len(fake.calls) == (0 if boundary == "initialize_intent" else 1)


def test_slow_close_is_audited_but_cannot_refresh_retry_budget(tmp_path, monkeypatch):
    root, token, spec = fixture.setup(tmp_path, monkeypatch)
    spec = replace(spec, total_timeout_seconds=0.15)
    fake = fixture.FakeMCP(root, ("101",))
    fake.fail = "download_activity_file"
    original = fake.factory

    @asynccontextmanager
    async def slow_close(args):
        async with original(args) as session:
            try:
                yield session
            finally:
                await asyncio.sleep(0.2)

    monkeypatch.setattr(fake, "factory", slow_close)
    with pytest.raises(ValueError):
        fixture.run(root, token, spec, fake)
    assert fake.starts == fake.closed == 1
    with fixture.modules()[0].open_store(root) as db:
        journal = fixture.engine().Journal(db, root, spec)
        assert fixture.engine().document(
            db, journal.outcome_key(journal.intents[0])
        ) == {"status": "closed", "token_unchanged": True}
    with pytest.raises(ValueError, match="budget"):
        fixture.run(root, token, spec, fake)
    assert fake.starts == 1


def test_real_process_interruption_and_relocation_preserve_deadline(
    tmp_path, monkeypatch
):
    root, token, spec = fixture.setup(tmp_path, monkeypatch)
    spec = replace(spec, total_timeout_seconds=0.2)

    def child():
        fake = fixture.FakeMCP(root, ())

        async def crash():
            os._exit(91)

        fake.initialize = crash
        fixture.run(root, token, spec, fake)

    process = multiprocessing.get_context("fork").Process(target=child)
    process.start()
    process.join(5)
    if process.is_alive():
        process.kill()
        process.join()
    assert process.exitcode == 91
    time.sleep(0.25)
    moved = root.with_name("moved")
    root.rename(moved)
    fake = fixture.FakeMCP(moved, ())
    with pytest.raises(ValueError, match="budget"):
        fixture.run(moved, token, spec, fake)
    assert fake.starts == 0
    with fixture.modules()[0].open_store(moved) as db:
        journal = fixture.engine().Journal(db, moved, spec)
        assert journal.counts()["initialize"] == 1
        assert fixture.engine().document(db, journal.key + ":complete") is None


def test_budget_freezes_request_even_if_request_write_interrupted(
    tmp_path, monkeypatch
):
    root, token, spec = fixture.setup(tmp_path, monkeypatch)
    module = fixture.engine()
    original = module.put

    def fail(db, key, value):
        if key.endswith(":request"):
            raise OSError("synthetic write interruption")
        return original(db, key, value)

    monkeypatch.setattr(module, "put", fail)
    fake = fixture.FakeMCP(root, ())
    with pytest.raises(OSError):
        fixture.run(root, token, spec, fake)
    monkeypatch.setattr(module, "put", original)
    with pytest.raises(ValueError, match="conflict"):
        fixture.run(root, token, replace(spec, total_timeout_seconds=999), fake)
    assert fake.starts == 0
    assert fixture.run(root, token, spec, fake)["status"] == "complete"


@pytest.mark.parametrize("completed", [True, False])
def test_legacy_request_read_only_never_creates_new_allowance(
    tmp_path, monkeypatch, completed
):
    weekly = importlib.import_module("test_m12_weekly_evidence")
    module = fixture.engine()
    original = module.put

    def legacy(db, key, value):
        if key.endswith(":request"):
            value = json.loads(json.dumps(value))
            value["schema_version"] = "fit_sync_request_v1"
            value["request"].pop("total_timeout_seconds")
        if not completed and key.endswith(":complete"):
            raise OSError("synthetic old incomplete job")
        return original(db, key, value)

    monkeypatch.setattr(module, "put", legacy)
    if completed:
        root, job, _, _ = weekly.setup(tmp_path, monkeypatch)
    else:
        with pytest.raises(OSError):
            weekly.setup(tmp_path, monkeypatch)
        root, job = tmp_path / "instance", "weekly:2026-08-09"
    monkeypatch.setattr(module, "put", original)
    store = fixture.modules()[0]
    with store.open_store(root) as db:
        key = "fit-sync:" + store.digest(job.encode())
        request = module.document(db, key + ":request")
        spec = module.read_request(request)
        assert spec.total_timeout_seconds is None
        before = db.execute(
            "SELECT content_json,content_sha256 FROM documents WHERE logical_key=?",
            (key + ":request",),
        ).fetchone()
    fake = fixture.FakeMCP(root, ())
    if completed:
        database_before = (root / "trainlab-fit.db").read_bytes()
        assert (
            fixture.run(root, tmp_path / "absent-tokens", spec, fake)["status"]
            == "complete"
        )
        assert (root / "trainlab-fit.db").read_bytes() == database_before
        evidence = weekly.freeze(root, job)
        assert len(evidence["activities"]) == 2
    else:
        with pytest.raises(ValueError, match="budget_required"):
            fixture.run(root, tmp_path / "absent-tokens", spec, fake)
        with pytest.raises(ValueError, match="conflict"):
            fixture.run(
                root,
                tmp_path / "absent-tokens",
                replace(spec, total_timeout_seconds=100),
                fake,
            )
    with store.open_store(root) as db:
        after = db.execute(
            "SELECT content_json,content_sha256 FROM documents WHERE logical_key=?",
            (key + ":request",),
        ).fetchone()
        assert tuple(before) == tuple(after)
    assert fake.starts == 0
