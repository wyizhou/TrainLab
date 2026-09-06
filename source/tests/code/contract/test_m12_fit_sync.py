from __future__ import annotations

import asyncio
import importlib
import json
import sqlite3
import struct
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def engine():
    return importlib.import_module("skills._shared.fit_weekly.fit_sync")


def modules():
    return (
        importlib.import_module("skills._shared.fit_weekly.storage"),
        importlib.import_module("skills._shared.fit_weekly.sync_calendar"),
        importlib.import_module("skills._shared.fit_weekly.garmin_fit"),
    )


def fit_bytes(reference="101"):
    from fitdecode.utils import compute_crc

    raw = bytearray(importlib.import_module("test_m12_storage").synthetic_fit())
    struct.pack_into("<I", raw, len(raw) - 11, 1000003600 + int(reference))
    raw[-2:] = struct.pack("<H", compute_crc(raw[:-2]))
    return bytes(raw)


def setup(tmp_path, monkeypatch):
    store, calendar, adapter = modules()
    root = tmp_path / "instance"
    store.initialize(root)
    token = tmp_path / "tokens"
    token.mkdir(mode=0o700)
    p = token / "synthetic.json"
    p.write_text('{"synthetic":true}')
    p.chmod(0o600)
    monkeypatch.setattr(adapter.shutil, "which", lambda _: "/synthetic/uvx")
    request = calendar.InventoryRequest(
        "sync:2026-08-02", "2026-08-01", "2026-08-02", "2026-08-02T14:00:00Z", 2, 4
    )
    spec = engine().SyncSpec(
        request,
        max_download_calls=4,
        max_session_starts=3,
        timeout_seconds=1,
        is_cn=True,
    )
    return root, token, spec


class FakeMCP:
    def __init__(self, root, references=("101", "102", "103")):
        self.root = root
        self.references = references
        self.calls = []
        self.starts = 0
        self.closed = 0
        self.no_fit = set()
        self.fail = None
        self.after_download = None

    def committed_intents(self):
        with sqlite3.connect(self.root / "trainlab-fit.db") as db:
            return [
                json.loads(row[0])
                for row in db.execute("SELECT content_json FROM documents")
                if json.loads(row[0]).get("schema_version") == "fit_transport_intent_v1"
            ]

    @asynccontextmanager
    async def factory(self, spec):
        assert any(i["call_kind"] == "initialize" for i in self.committed_intents())
        self.starts += 1
        try:
            yield self
        finally:
            self.closed += 1

    async def initialize(self):
        pass

    async def list_tools(self):
        return SimpleNamespace(
            tools=[SimpleNamespace(name=n) for n in modules()[2].TOOLS], nextCursor=None
        )

    async def call_tool(self, name, arguments):
        assert any(i["tool"] == name for i in self.committed_intents())
        self.calls.append((name, dict(arguments)))
        if self.fail == name:
            raise ConnectionError("synthetic connection error")
        if name == "get_activities_by_date":
            page, size = arguments["page"], arguments["page_size"]
            selected = self.references[page * size : (page + 1) * size]
            more = len(selected) == size
            value = {
                "count": len(selected),
                "page": page,
                "page_size": size,
                "has_more": more,
                "date_range": {
                    "start": arguments["start_date"],
                    "end": arguments["end_date"],
                },
                "activities": [
                    {
                        "id": int(ref),
                        "start_time": "2026-08-01 10:00:00",
                        "name": "synthetic excluded name",
                    }
                    for ref in selected
                ],
            }
            if more:
                value["next_page"] = page + 1
            text = json.dumps(value)
        else:
            assert name == "download_activity_file" and arguments["format"] == "fit"
            ref = str(arguments["activity_id"])
            if ref in self.no_fit:
                text = f"No fit data returned for activity {ref}"
            else:
                p = Path(arguments["output_dir"]) / f"{ref}.fit"
                p.write_bytes(fit_bytes(ref))
                p.chmod(0o600)
                text = json.dumps(
                    {
                        "activity_id": int(ref),
                        "format": "fit",
                        "file_path": str(p),
                        "size_bytes": p.stat().st_size,
                        "message": "Activity file saved.",
                    }
                )
                if self.after_download:
                    self.after_download(p)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)], isError=False
        )


def run(root, token, spec, fake):
    return asyncio.run(
        engine().synchronize(root, spec, token_root=token, session_factory=fake.factory)
    )


def test_full_sync_pages_fits_and_replay_close_without_provider(tmp_path, monkeypatch):
    root, token, spec = setup(tmp_path, monkeypatch)
    fake = FakeMCP(root)
    result = run(root, token, spec, fake)
    assert result["status"] == "complete" and result["fit_count"] == 3
    assert result["activity_count"] == 3 and result["no_fit_count"] == 0
    assert result["provider_calls"] == {
        "initialize": 1,
        "inventory": 2,
        "download": 3,
        "total": 6,
    }
    assert result["external_actions"] == 0 and fake.starts == fake.closed == 1
    before = (root / "trainlab-fit.db").read_bytes()
    files = {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }
    assert run(root, token, spec, fake) == result
    assert (root / "trainlab-fit.db").read_bytes() == before
    assert {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    } == files
    assert fake.starts == 1 and len(fake.calls) == 5
    assert str(tmp_path) not in json.dumps(
        result
    ) and "synthetic excluded name" not in json.dumps(result)
    for p in [root, *root.rglob("*")]:
        assert p.stat().st_mode & 0o777 == (0o700 if p.is_dir() else 0o600)
        assert not p.is_symlink()
    with modules()[0].open_store(root) as db:
        assert modules()[0].verify_fit_closure(db, root) == 3


def test_existing_fit_is_reused_and_no_fit_is_not_no_activity(tmp_path, monkeypatch):
    root, token, spec = setup(tmp_path, monkeypatch)
    store = modules()[0]
    p = tmp_path / "existing.fit"
    p.write_bytes(fit_bytes())
    p.chmod(0o600)
    with store.open_store(root) as db:
        store.import_fit(db, root, "101", p, store.digest(p.read_bytes()))
    fake = FakeMCP(root, ("101", "102"))
    fake.no_fit.add("102")
    result = run(root, token, spec, fake)
    assert (
        result["activity_count"] == 2
        and result["fit_count"] == 1
        and result["no_fit_count"] == 1
    )
    assert [
        args["activity_id"]
        for name, args in fake.calls
        if name == "download_activity_file"
    ] == [102]


def test_complete_empty_query_does_not_download(tmp_path, monkeypatch):
    root, token, spec = setup(tmp_path, monkeypatch)
    fake = FakeMCP(root, ())
    result = run(root, token, spec, fake)
    assert result["activity_count"] == result["fit_count"] == 0
    assert len(fake.calls) == 1


def test_error_stops_then_recovery_preserves_budget_and_saved_pages(
    tmp_path, monkeypatch
):
    root, token, spec = setup(tmp_path, monkeypatch)
    fake = FakeMCP(root, ("101",))
    fake.fail = "download_activity_file"
    with pytest.raises(ValueError):
        run(root, token, spec, fake)
    assert fake.starts == fake.closed == 1
    fake.fail = None
    result = run(root, token, spec, fake)
    assert result["provider_calls"] == {
        "initialize": 2,
        "inventory": 1,
        "download": 2,
        "total": 5,
    }
    assert result["fit_count"] == 1
    assert sum(n == "get_activities_by_date" for n, _ in fake.calls) == 1


def test_download_budget_is_not_reset_by_restarting(tmp_path, monkeypatch):
    root, token, spec = setup(tmp_path, monkeypatch)
    from dataclasses import replace

    spec = replace(spec, max_download_calls=1)
    fake = FakeMCP(root, ("101",))
    fake.fail = "download_activity_file"
    with pytest.raises(ValueError):
        run(root, token, spec, fake)
    before_calls = list(fake.calls)
    with pytest.raises(ValueError, match="budget"):
        run(root, token, spec, fake)
    assert fake.calls == before_calls
    with pytest.raises(ValueError, match="conflict"):
        run(root, token, replace(spec, max_download_calls=10), fake)


def test_capture_write_failure_never_commits_success(tmp_path, monkeypatch):
    root, token, spec = setup(tmp_path, monkeypatch)
    fake = FakeMCP(root, ("101",))
    store = modules()[0]
    atomic = store.atomic_file

    def fail_capture(path, data):
        if path.suffix == ".mcp":
            raise OSError("synthetic capture write failure")
        return atomic(path, data)

    monkeypatch.setattr(store, "atomic_file", fail_capture)
    with pytest.raises((ValueError, OSError)):
        run(root, token, spec, fake)
    assert not any(n == "download_activity_file" for n, _ in fake.calls)
    with store.open_store(root) as db:
        assert not any(
            json.loads(r[0]).get("schema_version") == "fit_sync_receipt_v1"
            for r in db.execute("SELECT content_json FROM documents")
        )


def test_token_or_session_close_failure_prevents_overall_success(tmp_path, monkeypatch):
    root, token, spec = setup(tmp_path, monkeypatch)
    fake = FakeMCP(root, ("101",))
    fake.after_download = lambda _: (token / "synthetic.json").write_text(
        "changed synthetic"
    )
    with pytest.raises(ValueError):
        run(root, token, spec, fake)
    assert fake.starts == fake.closed == 1
    with modules()[0].open_store(root) as db:
        assert not any(
            json.loads(r[0]).get("schema_version") == "fit_sync_receipt_v1"
            for r in db.execute("SELECT content_json FROM documents")
        )


def test_completed_instance_can_move_without_restarting_provider(tmp_path, monkeypatch):
    root, token, spec = setup(tmp_path, monkeypatch)
    fake = FakeMCP(root, ("101",))
    result = run(root, token, spec, fake)
    moved = tmp_path / "moved"
    root.rename(moved)
    assert run(moved, token, spec, fake) == result
    assert fake.starts == 1


@pytest.mark.parametrize("kind", ["inventory", "download"])
def test_capture_before_sql_crash_recovers_without_repeat_call(
    tmp_path, monkeypatch, kind
):
    root, token, spec = setup(tmp_path, monkeypatch)
    fake = FakeMCP(root, ("101",))
    module = engine()
    original = module.put
    armed = True

    def crash(db, key, value):
        nonlocal armed
        target = value.get("value", {}) or {}
        match = (
            "items" in target
            if kind == "inventory"
            else target.get("status") == "available"
        )
        if armed and ":outcome:" in key and match:
            armed = False
            raise OSError("synthetic after capture before SQL")
        return original(db, key, value)

    monkeypatch.setattr(module, "put", crash)
    with pytest.raises(OSError):
        run(root, token, spec, fake)
    result = run(root, token, spec, fake)
    assert result["fit_count"] == 1
    assert sum(n == "get_activities_by_date" for n, _ in fake.calls) == 1
    assert sum(n == "download_activity_file" for n, _ in fake.calls) == 1


def test_final_receipt_failure_replays_locally_and_unfinished_jobs_are_visible(
    tmp_path, monkeypatch
):
    root, token, spec = setup(tmp_path, monkeypatch)
    fake = FakeMCP(root, ("101",))
    module = engine()
    original = module.put
    armed = True

    def crash(db, key, value):
        nonlocal armed
        if armed and key.endswith(":complete"):
            armed = False
            raise OSError("synthetic terminal write")
        return original(db, key, value)

    monkeypatch.setattr(module, "put", crash)
    with pytest.raises(OSError):
        run(root, token, spec, fake)
    with modules()[0].open_store(root) as db:
        assert modules()[1].day_status(db, "2026-08-01") == "complete"
        assert len(module.unfinished_jobs(db)) == 1
    calls = list(fake.calls)
    assert run(root, token, spec, fake)["fit_count"] == 1
    assert fake.calls == calls and fake.starts == 1
    with modules()[0].open_store(root) as db:
        assert module.unfinished_jobs(db) == []


def test_raw_without_error_envelope_cannot_be_promoted_to_success(
    tmp_path, monkeypatch
):
    root, token, spec = setup(tmp_path, monkeypatch)
    module, store = engine(), modules()[0]
    with store.open_store(root) as db:
        j = module.Journal(db, root, spec)
        module.private_directory(root / "sync")
        module.private_directory(j.work)
        args = {
            "start_date": spec.inventory.start_date,
            "end_date": spec.inventory.end_date,
            "page": 0,
            "page_size": 2,
        }
        intent = j.reserve("inventory", args)
        directory = j.directory(intent)
        module.private_directory(directory)
        payload = json.dumps(
            {
                "count": 0,
                "page": 0,
                "page_size": 2,
                "has_more": False,
                "date_range": {"start": args["start_date"], "end": args["end_date"]},
                "activities": [],
            }
        ).encode()
        store.atomic_file(directory / "response.mcp", payload)
        with pytest.raises(ValueError, match="incomplete"):
            j.recovered(intent)


def test_unknown_capture_file_prevents_completion(tmp_path, monkeypatch):
    root, token, spec = setup(tmp_path, monkeypatch)
    fake = FakeMCP(root, ("101",))

    def extra(path):
        target = path.parent.parent / "unexpected.txt"
        target.write_text("synthetic stray artifact")
        target.chmod(0o600)

    fake.after_download = extra
    with pytest.raises(ValueError, match="artifact"):
        run(root, token, spec, fake)


def test_completed_capture_drift_is_rejected_without_provider(tmp_path, monkeypatch):
    root, token, spec = setup(tmp_path, monkeypatch)
    fake = FakeMCP(root, ("101",))
    run(root, token, spec, fake)
    path = next((root / "sync").rglob("response.mcp"))
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="capture"):
        run(root, token, spec, fake)
    assert fake.starts == 1


def test_token_audit_failure_is_persistent_not_auto_retried(tmp_path, monkeypatch):
    root, token, spec = setup(tmp_path, monkeypatch)
    fake = FakeMCP(root, ("101",))
    fake.after_download = lambda _: (token / "synthetic.json").write_text("changed")
    with pytest.raises(ValueError):
        run(root, token, spec, fake)
    with pytest.raises(ValueError, match="audit_blocked"):
        run(root, token, spec, fake)
    assert fake.starts == 1
    with modules()[0].open_store(root) as db:
        assert engine().unfinished_jobs(db)[0]["blocked"] is True


def test_initialize_failure_spends_persistent_session_budget(tmp_path, monkeypatch):
    from dataclasses import replace

    root, token, spec = setup(tmp_path, monkeypatch)
    fake = FakeMCP(root, ())

    async def fail():
        raise ConnectionError("synthetic initialization error")

    monkeypatch.setattr(fake, "initialize", fail)
    spec = replace(spec, max_session_starts=1)
    with pytest.raises(ValueError, match="session"):
        run(root, token, spec, fake)
    with pytest.raises(ValueError, match="budget"):
        run(root, token, spec, fake)
    assert fake.starts == fake.closed == 1 and not fake.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_download_calls", -1),
        ("max_session_starts", 0),
        ("timeout_seconds", float("nan")),
        ("is_cn", "true"),
    ],
)
def test_invalid_spec_does_not_write_or_start_provider(
    tmp_path, monkeypatch, field, value
):
    from dataclasses import replace

    root, token, spec = setup(tmp_path, monkeypatch)
    fake = FakeMCP(root, ())
    before = (root / "trainlab-fit.db").read_bytes()
    with pytest.raises(ValueError):
        run(root, token, replace(spec, **{field: value}), fake)
    assert fake.starts == 0 and (root / "trainlab-fit.db").read_bytes() == before


@pytest.mark.parametrize("kind", ["inventory", "download"])
def test_real_process_exit_after_capture_preserves_closure(tmp_path, monkeypatch, kind):
    import multiprocessing
    import os

    root, token, spec = setup(tmp_path, monkeypatch)
    module = engine()

    def child():
        original = module.put

        def crash(db, key, value):
            target = value.get("value", {}) or {}
            match = (
                "items" in target
                if kind == "inventory"
                else target.get("status") == "available"
            )
            if ":outcome:" in key and match:
                os._exit(91)
            return original(db, key, value)

        module.put = crash
        run(root, token, spec, FakeMCP(root, ("101",)))

    process = multiprocessing.get_context("fork").Process(target=child)
    process.start()
    process.join(10)
    if process.is_alive():
        process.kill()
        process.join()
    assert process.exitcode == 91
    fake = FakeMCP(root, ("101",))
    result = run(root, token, spec, fake)
    assert result["fit_count"] == 1 and result["provider_calls"]["initialize"] == 2
    assert (
        result["provider_calls"]["inventory"]
        == result["provider_calls"]["download"]
        == 1
    )
    assert not any(n == "get_activities_by_date" for n, _ in fake.calls)
    assert len(fake.calls) == (1 if kind == "inventory" else 0)


def test_missing_capture_after_descriptor_is_not_adopted(tmp_path, monkeypatch):
    root, token, spec = setup(tmp_path, monkeypatch)
    fake = FakeMCP(root, ())
    store = modules()[0]
    original = store.atomic_file

    def fail(path, data):
        if path.suffix == ".mcp":
            raise OSError("synthetic disk error")
        return original(path, data)

    monkeypatch.setattr(store, "atomic_file", fail)
    with pytest.raises(OSError):
        run(root, token, spec, fake)
    monkeypatch.setattr(store, "atomic_file", original)
    with pytest.raises(ValueError):
        run(root, token, spec, fake)
    assert fake.starts == 1 and len(fake.calls) == 1


def test_error_envelope_survives_capture_before_sql_failure(tmp_path, monkeypatch):
    root, token, spec = setup(tmp_path, monkeypatch)
    fake = FakeMCP(root, ())
    original_call = fake.call_tool

    async def error(name, arguments):
        value = await original_call(name, arguments)
        value.isError = True
        return value

    monkeypatch.setattr(fake, "call_tool", error)
    module = engine()
    original_put = module.put

    def crash(db, key, value):
        if value.get("error_code") == "garmin_mcp_error":
            raise OSError("synthetic result SQL failure")
        return original_put(db, key, value)

    monkeypatch.setattr(module, "put", crash)
    with pytest.raises(OSError):
        run(root, token, spec, fake)
    monkeypatch.setattr(module, "put", original_put)
    with modules()[0].open_store(root) as db:
        journal = module.Journal(db, root, spec)
        saved = journal.recovered(journal.intents[-1])
        assert saved["status"] == "error" and saved["value"] is None
        assert module.document(db, journal.key + ":complete") is None


def test_recovered_capture_barrier_failure_cannot_finish(tmp_path, monkeypatch):
    root, token, spec = setup(tmp_path, monkeypatch)
    fake = FakeMCP(root, ())
    module = engine()
    original = module.put

    def crash(db, key, value):
        if value.get("schema_version") == "fit_transport_result_v1":
            raise OSError("synthetic SQL failure")
        return original(db, key, value)

    monkeypatch.setattr(module, "put", crash)
    with pytest.raises(OSError):
        run(root, token, spec, fake)
    monkeypatch.setattr(module, "put", original)

    def fail(_):
        raise OSError("synthetic directory barrier")

    monkeypatch.setattr(modules()[0], "sync_dir", fail)
    with pytest.raises(OSError):
        run(root, token, spec, fake)
    assert fake.starts == 1


def test_existing_fit_multiple_revisions_block_without_download(tmp_path, monkeypatch):
    root, token, spec = setup(tmp_path, monkeypatch)
    store = modules()[0]
    for number in (101, 102):
        path = tmp_path / f"{number}.fit"
        path.write_bytes(fit_bytes(str(number)))
        path.chmod(0o600)
        with store.open_store(root) as db:
            store.import_fit(db, root, "101", path, store.digest(path.read_bytes()))
    fake = FakeMCP(root, ("101",))
    with pytest.raises(ValueError, match="revision_conflict"):
        run(root, token, spec, fake)
    assert not any(n == "download_activity_file" for n, _ in fake.calls)


def test_directory_creation_barrier_must_be_retried(tmp_path, monkeypatch):
    root, _, _ = setup(tmp_path, monkeypatch)
    store, module = modules()[0], engine()

    def fail(_):
        raise OSError("synthetic parent barrier failure")

    monkeypatch.setattr(store, "sync_dir", fail)
    target = root / "sync"
    with pytest.raises(OSError):
        module.private_directory(target)
    assert target.is_dir()
    with pytest.raises(OSError):
        module.private_directory(target)


@pytest.mark.parametrize("initial_failures", [1, 2])
@pytest.mark.parametrize("interruption", ["capture_before_sql", "after_complete_page"])
def test_initialization_errors_and_later_interruption_reuse_each_page_once(
    tmp_path, monkeypatch, initial_failures, interruption
):
    from dataclasses import replace

    root, token, spec = setup(tmp_path, monkeypatch)
    spec = replace(spec, max_session_starts=5)
    fake = FakeMCP(root, ("101",))
    original_initialize = fake.initialize

    async def fail():
        raise ConnectionError("synthetic initialization failure")

    monkeypatch.setattr(fake, "initialize", fail)
    for _ in range(initial_failures):
        with pytest.raises(ValueError, match="session"):
            run(root, token, spec, fake)
    monkeypatch.setattr(fake, "initialize", original_initialize)
    module = engine()
    original_put = module.put
    if interruption == "capture_before_sql":

        def crash(db, key, value):
            if ":outcome:" in key and "items" in (value.get("value", {}) or {}):
                raise OSError("synthetic inventory SQL interruption")
            return original_put(db, key, value)

        monkeypatch.setattr(module, "put", crash)
        with pytest.raises(OSError):
            run(root, token, spec, fake)
        monkeypatch.setattr(module, "put", original_put)
    else:
        fake.fail = "download_activity_file"
        with pytest.raises(ValueError):
            run(root, token, spec, fake)
        fake.fail = None
    result = run(root, token, spec, fake)
    assert result["fit_count"] == 1
    assert result["provider_calls"]["inventory"] == 1
    assert result["provider_calls"]["initialize"] == initial_failures + 2
    with modules()[0].open_store(root) as db:
        rows = db.execute(
            "SELECT c.ordinal,c.page FROM sync_calls c JOIN sync_results r USING(job_key,ordinal) WHERE r.status='page'"
        ).fetchall()
        assert [tuple(row) for row in rows] == [(initial_failures + 1, 0)]
        assert module.unfinished_jobs(db) == []
        inventory = db.execute(
            "SELECT content_json FROM documents WHERE logical_key=?",
            ("inventory:" + spec.inventory.key,),
        ).fetchone()[0]
        assert json.loads(inventory)["unresolved_calls"] == initial_failures
    before = (root / "trainlab-fit.db").read_bytes()
    calls = list(fake.calls)
    assert run(root, token, spec, fake) == result
    assert before == (root / "trainlab-fit.db").read_bytes() and fake.calls == calls
