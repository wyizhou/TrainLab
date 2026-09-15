from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path

import pytest

from skills._shared.fit_weekly import (
    run_authorization,
    run_config,
    run_daemon,
    run_sync,
    schedule_state,
    storage,
    sync_calendar,
)

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE / "tests/code/contract"))

entry = importlib.import_module("test_m12_entrypoint")
sync_fixture = importlib.import_module("test_m12_sync_command")
NOW = "2026-09-09T14:00:00Z"


def config(root, first="2026-09-09", grants=None):
    entry.private_json(
        root / "schedule.json",
        {
            "schema_version": "fit_schedule_config_v1",
            "first_day": first,
            "grants": grants or {},
        },
    )
    return run_daemon.load(root, "schedule.json", now=NOW)


def setup(tmp_path, monkeypatch):
    root, service, grant, _ = sync_fixture.setup(tmp_path, monkeypatch)
    value = grant.value()
    value["sync"]["dates"] = ["2026-09-08", "2026-09-09"]
    value["sync"]["as_of_utc"] = NOW
    provisional = run_authorization.parse(value, now=NOW)
    value["publication"]["action_keys"] = sync_fixture.mail_actions(
        run_sync.action_key(provisional)
    )
    grant = run_authorization.parse(value, now=NOW)
    entry.private_json(root / "authorization.json", value)
    schedule = config(root, grants={"daily:2026-09-09": "authorization.json"})
    return root, service, grant, schedule


@pytest.mark.parametrize(
    "now,daily,weekly",
    [
        ("2026-09-09T13:59:59Z", None, "2026-09-06T07:00:00Z"),
        ("2026-09-09T14:00:00Z", "2026-09-09", "2026-09-06T07:00:00Z"),
        ("2027-01-03T06:59:59Z", None, "2026-12-27T07:00:00Z"),
        ("2027-01-03T07:00:00Z", None, "2027-01-03T07:00:00Z"),
    ],
)
def test_hong_kong_calendar_boundaries(now, daily, weekly):
    slots = run_daemon.due_slots(now, "2022-01-01")
    assert slots == [f"weekly:{weekly}"] + ([f"daily:{daily}"] if daily else [])


def test_takeover_explicit_immutable_gaps_and_move(tmp_path):
    root = tmp_path / "instance"
    storage.initialize(root)
    with pytest.raises(ValueError):
        config(root, first="")
    schedule = config(root, first="2026-09-01")
    schedule_state.start(root, schedule.first_day, NOW)
    with storage.open_store(root) as db:
        assert sync_calendar.pending_days(db, NOW) == [
            f"2026-09-{d:02d}" for d in range(1, 10)
        ]
        assert not db.execute("SELECT * FROM sync_days").fetchall()
    moved = tmp_path / "moved"
    root.rename(moved)
    schedule_state.start(moved, schedule.first_day, NOW)
    assert schedule_state.read(moved)["first_day"] == "2026-09-01"
    with pytest.raises(ValueError, match="takeover_conflict"):
        schedule_state.start(moved, "2026-09-02", NOW)
    assert run_daemon.due_slots("2026-10-05T01:00:00Z", schedule.first_day) == [
        "weekly:2026-10-04T07:00:00Z"
    ]


@pytest.mark.parametrize(
    "bad", ["missing", "expired", "future", "reverse", "scope", "mail"]
)
def test_bad_authorization_zero_service_reads_and_calls(tmp_path, monkeypatch, bad):
    root, service, grant, schedule = setup(tmp_path, monkeypatch)
    value = grant.value()
    if bad == "missing":
        (root / "authorization.json").unlink()
    else:
        if bad == "expired":
            value["expires_utc"] = NOW
        elif bad == "future":
            value["starts_utc"] = "2026-09-10T00:00:00Z"
        elif bad == "reverse":
            value["sync"]["dates"].reverse()
        elif bad == "scope":
            value["sync"]["dates"].pop(0)
        else:
            value["publication"] = None
        entry.private_json(root / "authorization.json", value)
    reads = []
    monkeypatch.setattr(run_config.Config, "service", lambda *args: reads.append(args))
    scheduler = run_daemon.Scheduler(service, schedule, now=lambda: NOW)
    asyncio.run(scheduler.tick())
    asyncio.run(scheduler.tick())
    state = schedule_state.read(root)
    assert not reads
    assert state["blocked"]["daily:2026-09-09"]["status"] == "blocked"
    assert not state["claims"]


def test_future_slot_not_read_or_executed(tmp_path, monkeypatch):
    root, service, _, schedule = setup(tmp_path, monkeypatch)
    (root / "authorization.json").unlink()
    scheduler = run_daemon.Scheduler(
        service, schedule, now=lambda: "2026-09-09T13:59:59Z"
    )
    asyncio.run(scheduler.tick())
    assert schedule_state.read(root)["blocked"] == {}
    assert schedule_state.read(root)["claims"] == {}


def test_daily_original_chain_durable_claim_one_batch_and_no_tick_replay(
    tmp_path, monkeypatch
):
    import requests

    from skills._shared.fit_weekly import garmin_fit

    root, service, grant, schedule = setup(tmp_path, monkeypatch)
    fake, http = sync_fixture.MCP(root), sync_fixture.HTTP()
    original = fake.factory
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def checked(spec):
        state = schedule_state.read(root)
        claim = state["claims"]["daily:2026-09-09"]
        assert claim["authorization_sha256"] == storage.digest(grant._body.encode())
        assert state["attempts"]["daily:2026-09-09"] == 1
        async with original(spec) as client:
            yield client

    monkeypatch.setattr(garmin_fit, "sdk_session", checked)
    monkeypatch.setattr(requests, "Session", lambda: http)
    scheduler = run_daemon.Scheduler(service, schedule, now=lambda: NOW)
    asyncio.run(scheduler.tick())
    state = schedule_state.read(root)
    assert state["outcomes"]["daily:2026-09-09"]["status"] == "complete"
    assert fake.starts == fake.closed == 1
    assert len(fake.calls) == 1
    assert sum(url.endswith("/send") for _, url in http.calls) == 1
    counts = (fake.starts, len(fake.calls), len(http.calls))
    asyncio.run(scheduler.tick())
    asyncio.run(run_daemon.Scheduler(service, schedule, now=lambda: NOW).tick())
    assert (fake.starts, len(fake.calls), len(http.calls)) == counts
    value = grant.value()
    value["sync"]["max_pages"] += 1
    entry.private_json(root / "authorization.json", value)
    asyncio.run(run_daemon.Scheduler(service, schedule, now=lambda: NOW).tick())
    assert (
        schedule_state.read(root)["blocked"]["daily:2026-09-09"]["error_code"]
        == "schedule_authorization_conflict"
    )
    assert (fake.starts, len(fake.calls), len(http.calls)) == counts


def test_schedule_permissions_hash_and_pending_recovery(tmp_path):
    root = tmp_path / "instance"
    storage.initialize(root)
    schedule_state.start(root, "2026-09-09", NOW)
    folder = root / "runtime/schedule"
    assert folder.stat().st_mode & 0o777 == 0o700
    for path in folder.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
    pending = folder / ".pending-interrupted"
    pending.write_bytes(b"partial")
    pending.chmod(0o600)
    assert schedule_state.read(root)["first_day"] == "2026-09-09"
    path = sorted(folder.glob("*.json"))[-1]
    value = json.loads(path.read_text())
    value["event"]["now"] = "2026-09-10T00:00:00Z"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        schedule_state.read(root)


def test_discrete_gaps_and_original_unfinished_download_remain_visible(
    tmp_path, monkeypatch
):
    import requests

    from skills._shared.fit_weekly import garmin_fit

    root, service, grant, _ = setup(tmp_path, monkeypatch)
    with storage.open_store(root) as db:
        db.execute("INSERT INTO sync_gaps VALUES('2026-09-05',?)", (NOW,))
    value = grant.value()
    value["sync"]["dates"] = ["2026-09-05", "2026-09-08", "2026-09-09"]
    provisional = run_authorization.parse(value, now=NOW)
    value["publication"]["action_keys"] = sync_fixture.mail_actions(
        run_sync.action_key(provisional)
    )
    entry.private_json(root / "authorization.json", value)
    schedule = config(root, grants={"daily:2026-09-09": "authorization.json"})
    fake, http = sync_fixture.MCP(root, {"2026-09-08": ["101"]}), sync_fixture.HTTP()
    fake.fail = "download_activity_file"
    monkeypatch.setattr(garmin_fit, "sdk_session", fake.factory)
    monkeypatch.setattr(requests, "Session", lambda: http)
    scheduler = run_daemon.Scheduler(service, schedule, now=lambda: NOW)
    asyncio.run(scheduler.tick())
    state = schedule_state.read(root)
    assert state["claims"]["daily:2026-09-09"]["dates"] == value["sync"]["dates"]
    assert [
        (a["start_date"], a["end_date"])
        for n, a in fake.calls
        if n == "get_activities_by_date"
    ] == [("2026-09-05", "2026-09-05"), ("2026-09-08", "2026-09-09")]
    outcome = state["outcomes"]["daily:2026-09-09"]
    assert outcome["status"] == "failed" and len(outcome["unfinished_jobs"]) == 1
    original = outcome["unfinished_jobs"][0]["request"]["inventory"]["key"]
    with storage.open_store(root) as db:
        assert sync_calendar.day_status(db, "2026-09-08") == "complete"
    fake.fail = None
    calls = len(fake.calls), len(http.calls)
    asyncio.run(scheduler.tick())
    asyncio.run(run_daemon.Scheduler(service, schedule, now=lambda: NOW).tick())
    assert calls == (len(fake.calls), len(http.calls))
    assert (
        state["outcomes"]["daily:2026-09-09"]["unfinished_jobs"][0]["request"][
            "inventory"
        ]["key"]
        == original
    )
    assert not any("recovery:" in key for key in state["claims"])


def test_failed_slot_does_not_prevent_next_independently_authorized_day(
    tmp_path, monkeypatch
):
    import requests

    from skills._shared.fit_weekly import garmin_fit

    root, service, grant, _ = setup(tmp_path, monkeypatch)
    next_now = "2026-09-10T14:00:00Z"
    value = grant.value()
    value.update(key="next-day")
    value["sync"].update(dates=["2026-09-09", "2026-09-10"], as_of_utc=next_now)
    value["publication"]["action_keys"] = sync_fixture.mail_actions(
        run_sync.action_key(run_authorization.parse(value, now=next_now))
    )
    entry.private_json(root / "next.json", value)
    schedule = config(
        root,
        grants={
            "daily:2026-09-09": "authorization.json",
            "daily:2026-09-10": "next.json",
        },
    )
    fake, http = sync_fixture.MCP(root, {"2026-09-08": ["101"]}), sync_fixture.HTTP()
    fake.fail = "download_activity_file"
    monkeypatch.setattr(garmin_fit, "sdk_session", fake.factory)
    monkeypatch.setattr(requests, "Session", lambda: http)
    clock = [NOW]
    scheduler = run_daemon.Scheduler(service, schedule, now=lambda: clock[0])
    asyncio.run(scheduler.tick())
    assert (
        schedule_state.read(root)["outcomes"]["daily:2026-09-09"]["status"] == "failed"
    )
    fake.fail = None
    clock[0] = next_now
    asyncio.run(scheduler.tick())
    state = schedule_state.read(root)
    assert state["outcomes"]["daily:2026-09-10"]["status"] == "complete"
    assert state["outcomes"]["daily:2026-09-09"]["status"] == "failed"
    assert len(state["outcomes"]["daily:2026-09-10"]["unfinished_jobs"]) == 1
    assert state["claims"]["daily:2026-09-10"]["authorization_key"] == "next-day"
    assert state["attempts"] == {"daily:2026-09-09": 1, "daily:2026-09-10": 1}


def test_unknown_mail_and_clock_rollback_never_spend_again(tmp_path, monkeypatch):
    import requests

    from skills._shared.fit_weekly import garmin_fit

    root, service, _, schedule = setup(tmp_path, monkeypatch)
    fake, http = sync_fixture.MCP(root), sync_fixture.HTTP()
    http.lost = True
    monkeypatch.setattr(garmin_fit, "sdk_session", fake.factory)
    monkeypatch.setattr(requests, "Session", lambda: http)
    scheduler = run_daemon.Scheduler(service, schedule, now=lambda: NOW)
    asyncio.run(scheduler.tick())
    assert (
        schedule_state.read(root)["outcomes"]["daily:2026-09-09"]["status"] == "unknown"
    )
    counts = len(fake.calls), len(http.calls)
    asyncio.run(scheduler.tick())
    asyncio.run(run_daemon.Scheduler(service, schedule, now=lambda: NOW).tick())
    with pytest.raises(ValueError, match="clock_rollback"):
        run_daemon.Scheduler(service, schedule, now=lambda: "2026-09-09T13:59:59Z")
    assert counts == (len(fake.calls), len(http.calls))


def test_wrapper_exec_failure_and_business_exit_125_are_distinct(tmp_path):
    from skills._shared.fit_weekly import model_process

    failed = tmp_path / "executable-without-valid-format"
    failed.write_bytes(b"public invalid executable")
    failed.chmod(0o700)
    result = model_process.execute(
        [str(failed)], cwd=tmp_path, env={}, prompt=b"public", timeout=2
    )
    assert result.error_code == "process_start_failed"
    assert result.returncode is None and result.input_bytes == 0
    result = model_process.execute(
        [sys.executable, "-c", "import sys; sys.stdin.read(); sys.exit(125)"],
        cwd=tmp_path,
        env={},
        prompt=b"public",
        timeout=2,
    )
    assert result.error_code == "process_exit_nonzero"
    assert result.returncode == 125 and result.input_bytes == 6


def test_result_timestamp_is_a_durable_clock_high_water(tmp_path, monkeypatch):
    root, service, grant, schedule = setup(tmp_path, monkeypatch)
    schedule_state.start(root, schedule.first_day, NOW)
    run_daemon.claim(
        root, "daily:2026-09-09", "authorization.json", grant, NOW, late=False
    )
    schedule_state.append(
        root, {"kind": "attempt", "slot": "daily:2026-09-09", "now": NOW, "number": 1}
    )
    later = "2026-09-10T15:00:00Z"
    schedule_state.append(
        root,
        {
            "kind": "result",
            "slot": "daily:2026-09-09",
            "now": later,
            "value": {"status": "failed"},
        },
    )
    assert schedule_state.read(root)["last_seen_utc"] == later
    with pytest.raises(ValueError, match="clock_rollback"):
        run_daemon.Scheduler(service, schedule, now=lambda: "2026-09-10T14:00:00Z")


def test_unsettled_slot_and_actual_lifecycle_are_separate(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import lifecycle, run_state

    root, _, grant, schedule = setup(tmp_path, monkeypatch)
    with lifecycle.run(root, "daemon"):
        schedule_state.start(root, schedule.first_day, NOW)
        run_daemon.claim(
            root, "daily:2026-09-09", "authorization.json", grant, NOW, late=False
        )
        status = run_state.status(root)
        assert status["lifecycle"] == "running"
        assert status["schedule"]["slots"]["daily:2026-09-09"]["status"] == "unsettled"
    assert run_state.status(root)["lifecycle"] == "not_running"


def original_daily_slots(tmp_path, monkeypatch, *, expires="2026-09-10T00:00:00Z"):
    root, service, initial, _ = setup(tmp_path, monkeypatch)
    schedule_state.start(root, "2026-09-08", "2026-09-08T14:00:00Z")
    files = {}
    for day, dates in (
        ("2026-09-08", ["2026-09-07", "2026-09-08"]),
        ("2026-09-09", ["2026-09-08", "2026-09-09"]),
    ):
        now = day + "T14:00:00Z"
        schedule_state.observe(root, now)
        value = initial.value()
        value.update(
            key="original-" + day,
            starts_utc="2026-09-08T00:00:00Z",
            expires_utc=expires if day == "2026-09-08" else "2026-09-10T00:00:00Z",
        )
        value["sync"].update(dates=dates, as_of_utc=now)
        value["publication"]["action_keys"] = sync_fixture.mail_actions(
            run_sync.action_key(run_authorization.parse(value, now=now))
        )
        grant = run_authorization.parse(value, now=now)
        filename, slot = day + ".json", "daily:" + day
        entry.private_json(root / filename, value)
        run_daemon.claim(root, slot, filename, grant, now, late=False)
        files[slot] = filename
    return root, service, run_daemon.Schedule("2026-09-08", files)


@pytest.mark.parametrize("mail_lost", [False, True])
def test_original_slots_resume_after_business_time_advances_without_replay(
    tmp_path, monkeypatch, mail_lost
):
    from contextlib import asynccontextmanager

    import requests

    from skills._shared.fit_weekly import garmin_fit, lifecycle, publication_ledger

    root, service, schedule = original_daily_slots(tmp_path, monkeypatch)
    claims = schedule_state.read(root)["claims"]
    authorizations = {
        p.name: p.read_bytes() for p in (root / "authorizations").iterdir()
    }
    clock = [NOW]
    monkeypatch.setattr(publication_ledger, "utc_now", lambda: clock[0])
    fake, http = sync_fixture.MCP(root), sync_fixture.HTTP()
    http.lost = mail_lost

    @asynccontextmanager
    async def timed(spec):
        async with fake.factory(spec) as client:
            yield client
        clock[0] = "2026-09-09T14:00:01Z"

    monkeypatch.setattr(garmin_fit, "sdk_session", timed)
    monkeypatch.setattr(requests, "Session", lambda: http)
    scheduler = run_daemon.Scheduler(service, schedule, now=lambda: clock[0])
    with lifecycle.run(root, "daemon"):
        asyncio.run(scheduler.tick())
        state = schedule_state.read(root)
        assert state["claims"] == claims
        assert state["blocked"] == {}
        assert state["attempts"] == {slot: 1 for slot in claims}
        assert state["last_seen_utc"] == "2026-09-09T14:00:01Z"
        assert set(state["outcomes"]) == set(claims)
        for slot, outcome in state["outcomes"].items():
            assert outcome["status"] == ("unknown" if mail_lost else "complete")
            assert outcome["batch_key"] == claims[slot]["business_key"]
            assert outcome["unfinished_jobs"] == []
        assert fake.starts == fake.closed == len(fake.calls) == 2
        assert sum(url.endswith("/send") for _, url in http.calls) == 2
        assert [(args["start_date"], args["end_date"]) for _, args in fake.calls] == [
            ("2026-09-08", "2026-09-09"),
            ("2026-09-07", "2026-09-08"),
        ]
        counts = fake.starts, len(fake.calls), len(http.calls)
        asyncio.run(scheduler.tick())
    with lifecycle.run(root, "daemon"):
        asyncio.run(
            run_daemon.Scheduler(service, schedule, now=lambda: clock[0]).tick()
        )
    assert (fake.starts, len(fake.calls), len(http.calls)) == counts
    assert schedule_state.read(root)["claims"] == claims
    assert schedule_state.read(root)["attempts"] == state["attempts"]
    assert {
        p.name: p.read_bytes() for p in (root / "authorizations").iterdir()
    } == authorizations


@pytest.mark.parametrize("rollback", [False, True])
def test_later_original_slot_checks_current_deadline_and_real_rollback(
    tmp_path, monkeypatch, rollback
):
    from contextlib import asynccontextmanager

    import requests

    from skills._shared.fit_weekly import garmin_fit, publication_ledger

    later = "2026-09-09T14:00:01Z"
    root, service, schedule = original_daily_slots(tmp_path, monkeypatch, expires=later)
    claims = schedule_state.read(root)["claims"]
    clock = [NOW]

    def now():
        if rollback and schedule_state.read(root)["outcomes"]:
            return NOW
        return clock[0]

    monkeypatch.setattr(publication_ledger, "utc_now", now)
    fake, http = sync_fixture.MCP(root), sync_fixture.HTTP()

    @asynccontextmanager
    async def timed(spec):
        async with fake.factory(spec) as client:
            yield client
        clock[0] = later

    monkeypatch.setattr(garmin_fit, "sdk_session", timed)
    monkeypatch.setattr(requests, "Session", lambda: http)
    scheduler = run_daemon.Scheduler(service, schedule, now=now)
    if rollback:
        with pytest.raises(ValueError, match="schedule_clock_rollback"):
            asyncio.run(scheduler.tick())
    else:
        asyncio.run(scheduler.tick())
        asyncio.run(scheduler.tick())
        asyncio.run(run_daemon.Scheduler(service, schedule, now=now).tick())
    state = schedule_state.read(root)
    assert state["claims"] == claims
    assert state["last_seen_utc"] == later
    assert state["outcomes"]["daily:2026-09-09"]["status"] == "complete"
    assert "daily:2026-09-08" not in state["outcomes"]
    assert state["attempts"] == {"daily:2026-09-09": 1}
    assert fake.starts == fake.closed == len(fake.calls) == 1
    assert sum(url.endswith("/send") for _, url in http.calls) == 1
    if rollback:
        assert "daily:2026-09-08" not in scheduler.seen
        assert state["blocked"] == {}
        with pytest.raises(ValueError, match="schedule_clock_rollback"):
            run_daemon.Scheduler(service, schedule, now=now)
    else:
        assert state["blocked"]["daily:2026-09-08"]["status"] == "blocked"
        events = [
            json.loads(p.read_text())["event"]
            for p in (root / "runtime/schedule").glob("*.json")
        ]
        assert [event["now"] for event in events if event["kind"] == "blocked"] == [
            later
        ]


def test_daemon_uses_selected_configuration_for_email_preflight(tmp_path, monkeypatch):
    import requests

    from skills._shared.fit_weekly import garmin_fit

    root, service, _, schedule = setup(tmp_path, monkeypatch)
    (root / "config.json").rename(root / "selected.json")
    service = run_config.load(root, "selected.json")
    fake, http = sync_fixture.MCP(root), sync_fixture.HTTP()
    monkeypatch.setattr(garmin_fit, "sdk_session", fake.factory)
    monkeypatch.setattr(requests, "Session", lambda: http)
    asyncio.run(run_daemon.Scheduler(service, schedule, now=lambda: NOW).tick())
    assert (
        schedule_state.read(root)["outcomes"]["daily:2026-09-09"]["status"]
        == "complete"
    )
    assert sum(u.endswith("/send") for m, u in http.calls) == 1
    assert sum(u.endswith("/modify") for m, u in http.calls) == 1
