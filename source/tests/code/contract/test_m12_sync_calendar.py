from __future__ import annotations

import importlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def modules():
    return (
        importlib.import_module("skills._shared.fit_weekly.storage"),
        importlib.import_module("skills._shared.fit_weekly.sync_calendar"),
    )


def request(sync, **changes):
    values = dict(
        key="daily:2026-09-05",
        start_date="2026-09-04",
        end_date="2026-09-05",
        as_of_utc="2026-09-05T14:00:00Z",
        page_size=2,
        max_calls=5,
    )
    return sync.InventoryRequest(**(values | changes))


def page(number=0, *, items=None, more=False):
    return {
        "page": number,
        "page_size": 2,
        "has_more": more,
        "items": [] if items is None else items,
    }


def item(ref="101", day="2026-09-04"):
    return {"activity_ref": ref, "activity_date": day}


def test_new_schema_explicit_upgrade_preserves_v1_data(tmp_path: Path) -> None:
    store, sync = modules()
    root = tmp_path / "v1"
    root.mkdir(mode=0o700)
    (root / "fits").mkdir(mode=0o700)
    (root / "writer.lock").touch(mode=0o600)
    db_path = root / "trainlab-fit.db"
    fd = os.open(db_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with sqlite3.connect(db_path) as db:
        db.executescript(store.SCHEMA_V1)
        db.execute(
            "INSERT INTO documents VALUES('weekly_report','old',?,?,?)",
            ("a" * 64, '{"old":true}', store.digest(b'{"old":true}')),
        )
    before = db_path.read_bytes()
    with pytest.raises(ValueError, match="store_upgrade_required"):
        with store.open_store(root):
            pass
    assert db_path.read_bytes() == before
    store.upgrade(root)
    with store.open_store(root) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert (
            db.execute("SELECT content_json FROM documents").fetchone()[0]
            == '{"old":true}'
        )
    after = db_path.read_bytes()
    store.upgrade(root)
    assert db_path.read_bytes() == after


def test_complete_pagination_zero_activity_and_today_provisional(
    tmp_path: Path,
) -> None:
    store, sync = modules()
    root = tmp_path / "instance"
    store.initialize(root)
    calls = []

    def fetch(start, end, number, size):
        calls.append((start, end, number, size))
        return page(number)

    result = sync.collect_inventory(root, request(sync), fetch)
    assert result["inventory_complete"] is True
    assert result["activity_count"] == 0
    assert result["provider_calls"] == 1
    with store.open_store(root) as db:
        assert sync.day_status(db, "2026-09-04") == "complete"
        assert sync.day_status(db, "2026-09-05") == "provisional"
        assert sync.day_status(db, "2026-09-03") == "unqueried"
    before = (root / "trainlab-fit.db").read_bytes()
    assert sync.collect_inventory(root, request(sync), fetch) == result
    assert (root / "trainlab-fit.db").read_bytes() == before
    assert len(calls) == 1


def test_resume_uses_saved_pages_and_retains_spent_budget(tmp_path: Path) -> None:
    store, sync = modules()
    root = tmp_path / "instance"
    store.initialize(root)
    calls = []

    def failed(start, end, number, size):
        calls.append(number)
        if number == 1:
            raise ConnectionError("synthetic transient error")
        return page(items=[item()], more=True)

    with pytest.raises(ValueError, match="inventory_provider_failed"):
        sync.collect_inventory(root, request(sync), failed)
    with store.open_store(root) as db:
        assert sync.day_status(db, "2026-09-04") == "unqueried"

    def resumed(start, end, number, size):
        calls.append(number)
        return page(number, items=[item("202")])

    result = sync.collect_inventory(root, request(sync), resumed)
    assert calls == [0, 1, 1]
    assert result["provider_calls"] == 3 and result["activity_count"] == 2
    assert result["collection_complete"] is False


@pytest.mark.parametrize(
    "case",
    [
        "extra",
        "wrong_page",
        "wrong_size",
        "invalid_more",
        "empty_more",
        "duplicate",
        "cross_day",
        "name",
        "bad_id",
    ],
)
def test_invalid_page_never_marks_day_complete(tmp_path: Path, case: str) -> None:
    store, sync = modules()
    root = tmp_path / "instance"
    store.initialize(root)
    value = page(items=[item()])
    if case == "extra":
        value["unexpected"] = "x"
    if case == "wrong_page":
        value["page"] = 8
    if case == "wrong_size":
        value["page_size"] = 10
    if case == "invalid_more":
        value["has_more"] = "false"
    if case == "empty_more":
        value = page(more=True)
    if case == "duplicate":
        value["items"] = [item(), item()]
    if case == "cross_day":
        value["items"] = [item(day="2026-09-03")]
    if case == "name":
        value["items"] = [item() | {"activity_name": "synthetic name"}]
    if case == "bad_id":
        value["items"] = [item(ref="../file")]
    with pytest.raises(ValueError, match="inventory_page_invalid"):
        sync.collect_inventory(root, request(sync), lambda *args: value)
    with store.open_store(root) as db:
        assert sync.day_status(db, "2026-09-04") == "unqueried"


def test_budget_is_durable_before_provider_and_cannot_be_reset(tmp_path: Path) -> None:
    store, sync = modules()
    root = tmp_path / "instance"
    store.initialize(root)
    calls = []

    def fail(*args):
        with sqlite3.connect(
            (root / "trainlab-fit.db").as_uri() + "?mode=ro", uri=True
        ) as db:
            assert db.execute("SELECT COUNT(*) FROM sync_calls").fetchone()[0] == 1
        calls.append(1)
        raise ConnectionError("synthetic")

    req = request(sync, max_calls=1)
    with pytest.raises(ValueError, match="inventory_provider_failed"):
        sync.collect_inventory(root, req, fail)
    with pytest.raises(ValueError, match="inventory_budget_exhausted"):
        sync.collect_inventory(root, req, fail)
    with pytest.raises(ValueError, match="sync_job_conflict"):
        sync.collect_inventory(root, request(sync, max_calls=2), fail)
    assert len(calls) == 1


def test_duplicate_across_pages_is_not_complete(tmp_path: Path) -> None:
    store, sync = modules()
    root = tmp_path / "instance"
    store.initialize(root)
    with pytest.raises(ValueError, match="inventory_page_invalid"):
        sync.collect_inventory(
            root, request(sync), lambda a, b, n, s: page(n, items=[item()], more=n == 0)
        )
    with store.open_store(root) as db:
        assert sync.day_status(db, "2026-09-04") == "unqueried"


def test_startup_gaps_are_durable_and_empty_complete_days_are_not_gaps(
    tmp_path: Path,
) -> None:
    store, sync = modules()
    root = tmp_path / "instance"
    store.initialize(root)
    req = request(sync, end_date="2026-09-04")
    sync.collect_inventory(root, req, lambda *args: page())
    with store.open_store(root) as db:
        sync.record_gaps(db, "2026-09-02", "2026-09-06T01:00:00Z")
        assert sync.pending_days(db, "2026-09-06T01:00:00Z") == [
            "2026-09-02",
            "2026-09-03",
            "2026-09-05",
            "2026-09-06",
        ]
        assert sync.day_status(db, "2026-09-03") == "gap"
    with store.open_store(root) as db:
        sync.record_gaps(db, "2026-09-02", "2026-09-06T01:00:00Z")
        assert db.execute("SELECT COUNT(*) FROM sync_gaps").fetchone()[0] == 3


@pytest.mark.parametrize(
    "utc,expected",
    [
        ("2026-09-05T13:59:59Z", "2026-09-04"),
        ("2026-09-05T14:00:00Z", "2026-09-05"),
        ("2026-09-05T16:00:00Z", "2026-09-05"),
    ],
)
def test_daily_due_slot_hong_kong(utc: str, expected: str) -> None:
    assert modules()[1].daily_slot(utc) == expected


def test_weekly_cutoff_half_open_and_latest_makeup_only() -> None:
    sync = modules()[1]
    before = sync.weekly_slot("2026-09-06T06:59:59Z")
    after = sync.weekly_slot("2026-09-06T07:00:00Z")
    assert before["end_utc"] == "2026-08-30T07:00:00Z"
    assert after["start_utc"] == "2026-08-30T07:00:00Z"
    assert after["end_utc"] == "2026-09-06T07:00:00Z"
    assert after["plan_dates"] == [f"2026-09-{d:02d}" for d in range(7, 14)]
    assert sync.in_week("2026-08-30T07:00:00Z", after)
    assert not sync.in_week("2026-09-06T07:00:00Z", after)
    assert sync.weekly_slot("2026-09-09T08:00:00Z") == after


@pytest.mark.parametrize(
    "changes",
    [
        {"start_date": "2021-12-31"},
        {"end_date": "2026-09-06"},
        {"as_of_utc": "2026-09-05T14:00:00"},
        {"page_size": True},
        {"max_calls": 0},
        {"start_date": "20260904"},
    ],
)
def test_invalid_request_rejected_without_provider(tmp_path: Path, changes) -> None:
    store, sync = modules()
    root = tmp_path / "instance"
    store.initialize(root)
    calls = []
    with pytest.raises(ValueError):
        sync.collect_inventory(
            root, request(sync, **changes), lambda *args: calls.append(args)
        )
    assert calls == []
    with store.open_store(root) as db:
        assert db.execute("SELECT COUNT(*) FROM sync_jobs").fetchone()[0] == 0


def test_migration_failure_rolls_back_all_ddl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, sync = modules()
    root = tmp_path / "v1"
    root.mkdir(mode=0o700)
    (root / "fits").mkdir(mode=0o700)
    (root / "writer.lock").touch(mode=0o600)
    path = root / "trainlab-fit.db"
    path.touch(mode=0o600)
    with sqlite3.connect(path) as db:
        db.executescript(store.SCHEMA_V1)
    before = path.read_bytes()
    original = store.require_schema

    def fail_after_ddl(db, version=2):
        if version == 2:
            raise OSError("synthetic finite validation failure")
        return original(db, version)

    monkeypatch.setattr(store, "require_schema", fail_after_ddl)
    with pytest.raises(OSError):
        store.upgrade(root)
    assert path.read_bytes() == before
    monkeypatch.setattr(store, "require_schema", original)
    store.upgrade(root)
    with store.open_store(root) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_crash_after_durable_call_intent_resumes_with_remaining_budget(
    tmp_path: Path,
) -> None:
    store, sync = modules()
    root = tmp_path / "instance"
    store.initialize(root)
    script = """
import os,sys
from pathlib import Path
from skills._shared.fit_weekly.sync_calendar import InventoryRequest,collect_inventory
req=InventoryRequest('daily:2026-09-05','2026-09-04','2026-09-05','2026-09-05T14:00:00Z',2,2)
def crash(*args): os._exit(29)
collect_inventory(Path(sys.argv[1]),req,crash)
"""
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[3]),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    process = subprocess.run(
        [sys.executable, "-c", script, str(root)], env=env, capture_output=True
    )
    assert process.returncode == 29
    with store.open_store(root) as db:
        assert db.execute("SELECT COUNT(*) FROM sync_calls").fetchone()[0] == 1
        assert sync.day_status(db, "2026-09-04") == "unqueried"
    result = sync.collect_inventory(
        root, request(sync, max_calls=2), lambda *args: page()
    )
    assert result["provider_calls"] == 2
    assert result["unresolved_calls"] == 1
    assert result["inventory_complete"] is True


def test_crash_during_final_receipt_rebuilds_from_pages_without_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, sync = modules()
    root = tmp_path / "instance"
    store.initialize(root)
    calls = []
    original = store.put_document

    def fail(*args):
        raise OSError("synthetic receipt write failure")

    def fetch(*args):
        calls.append(1)
        return page()

    monkeypatch.setattr(store, "put_document", fail)
    with pytest.raises(OSError):
        sync.collect_inventory(root, request(sync), fetch)
    with store.open_store(root) as db:
        assert db.execute("SELECT COUNT(*) FROM sync_days").fetchone()[0] == 0
    monkeypatch.setattr(store, "put_document", original)
    result = sync.collect_inventory(root, request(sync), fetch)
    assert result["inventory_complete"] is True and len(calls) == 1
