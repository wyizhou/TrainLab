"""L2-13: unified full, incremental, and snapshot orchestration."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.garmin import (
    GarminCollectionTool,
    GarminConfig,
    GarminError,
    GarminRepository,
    SyncRequest,
)
from trainlab.garmin_modes import build_collection_mode_plan


class ModeTransport:
    def __init__(self) -> None:
        self.health_calls: list[tuple[str, str]] = []
        self.range_calls: list[tuple[str, str, str]] = []
        self.list_calls: list[tuple[str | None, str | None]] = []
        self.entries: list[dict[str, Any]] = []
        self.summary_calls: list[str] = []
        self.health_payloads: dict[str, Any] = {}
        self.interrupt_once: tuple[str, str] | None = None
        self.failures: dict[tuple[str, str], GarminError] = {}

    def login(self) -> None:
        return None

    def identity(self) -> str:
        return "l2-13-account"

    def fetch_account(
        self, _resource: str, _provider_device_id: str | None = None
    ) -> Any:
        return []

    def fetch_health(self, resource: str, local_date: str) -> Any:
        self.health_calls.append((resource, local_date))
        key = (resource, local_date)
        if self.interrupt_once == key:
            self.interrupt_once = None
            raise KeyboardInterrupt
        if key in self.failures:
            raise self.failures[key]
        payload = self.health_payloads.get(resource, [])
        if callable(payload):
            return payload(local_date)
        return payload

    def fetch_range(self, resource: str, start: str, through: str) -> Any:
        self.range_calls.append((resource, start, through))
        return []

    def list_activities(
        self, start: str | None, through: str | None
    ) -> list[dict[str, Any]]:
        self.list_calls.append((start, through))
        return list(self.entries)

    def activity_summary(self, activity_id: str) -> dict[str, Any]:
        self.summary_calls.append(activity_id)
        entry = next(
            item for item in self.entries
            if str(item.get("activityId")) == activity_id
        )
        day = str(entry["startTimeGMT"])[:10]
        return {
            "activityId": int(activity_id),
            "activityName": f"activity-{activity_id}",
            "activityType": {"typeKey": "running"},
            "startTimeGMT": f"{day}T00:00:00Z",
            "duration": 600,
        }

    def activity_original(self, _activity_id: str) -> bytes:
        raise GarminError("not_available", http_status=404)

    def activity_extra(self, _activity_id: str, _role: str) -> Any:
        return None


def _setup(
    tmp_path: Path,
    *,
    history_start: str = "2026-04-01",
    max_repairs: int = 100,
) -> tuple[GarminConfig, GarminCollectionTool, ModeTransport]:
    root = tmp_path / "data"
    foundation = FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state/ready.json",
        root / "state/locks/foundation.lock",
    )
    result = FoundationTool(foundation).execute(
        FoundationRequest("init", "l2-13", "2026-01-01T00:00:00Z")
    )
    assert result.status == "initialized"
    config = GarminConfig(
        foundation.database_path,
        foundation.raw_root,
        foundation.state_root,
        history_start,
        max_repair_items_per_incremental=max_repairs,
        request_min_interval_ms=0,
    )
    transport = ModeTransport()
    tool = GarminCollectionTool(
        config,
        transport,
        sleep=lambda _seconds: None,
        clock=lambda: datetime(2026, 4, 17, 7, 0, 0),
        monotonic=lambda: 1000.0,
    )
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    return config, tool, transport


def test_mode_planner_uses_full_history_independent_cursors_and_snapshot_day() -> None:
    full = build_collection_mode_plan(
        mode="full",
        today_local=date(2026, 4, 17),
        history_start_date="2026-01-01",
        requested_health_from=None,
        requested_through="2026-04-15",
        requested_snapshot_date=None,
        health_resources=("steps", "sleep"),
        complete_through_by_resource={},
        lookback_days=14,
    )
    assert full.activity_history_unbounded is True
    assert {(item.resource_kind, item.start, item.through) for item in full.health_windows} == {
        ("steps", date(2026, 1, 1), date(2026, 4, 15)),
        ("sleep", date(2026, 1, 1), date(2026, 4, 15)),
    }

    incremental = build_collection_mode_plan(
        mode="incremental",
        today_local=date(2026, 4, 17),
        history_start_date="2026-01-01",
        requested_health_from=None,
        requested_through="2026-04-15",
        requested_snapshot_date=None,
        health_resources=("steps", "sleep", "hrv"),
        complete_through_by_resource={
            "steps": "2026-04-10",
            "sleep": "2026-04-01",
        },
        lookback_days=14,
    )
    starts = {
        item.resource_kind: item.start for item in incremental.health_windows
    }
    assert starts == {
        "steps": date(2026, 3, 28),
        "sleep": date(2026, 3, 19),
        "hrv": date(2026, 1, 1),
    }
    assert incremental.activity_start == date(2026, 4, 2)

    snapshot = build_collection_mode_plan(
        mode="snapshot",
        today_local=date(2026, 4, 17),
        history_start_date="2026-01-01",
        requested_health_from=None,
        requested_through=None,
        requested_snapshot_date=None,
        health_resources=("steps", "sleep"),
        complete_through_by_resource={"steps": "2026-04-16"},
        lookback_days=14,
    )
    assert snapshot.snapshot is True
    assert snapshot.effective_start == snapshot.effective_through == date(2026, 4, 17)
    assert all(item.start == item.through == date(2026, 4, 17) for item in snapshot.health_windows)


def test_full_resumes_same_started_invocation_without_duplicate_revisions(
    tmp_path: Path,
) -> None:
    config, tool, transport = _setup(tmp_path)
    # Interrupt after one terminal work item already exists.  Replaying the
    # same invocation must accept terminal->running/terminal transitions while
    # immutable revisions remain no-op.
    transport.interrupt_once = ("steps", "2026-04-02")
    request = SyncRequest(
        "full",
        through_local_date="2026-04-15",
        resource_kinds=("steps",),
        invocation_id="full-resume",
    )
    with pytest.raises(KeyboardInterrupt):
        tool.execute(request)
    with sqlite3.connect(config.database_path) as connection:
        assert connection.execute(
            """SELECT count(*) FROM source_revisions
               WHERE resource_kind='steps'"""
        ).fetchone()[0] == 1

    resumed = tool.execute(request)
    assert resumed.status == "succeeded"
    assert resumed.coverage_state == "complete"
    assert resumed.effective_range == {
        "from": "2026-04-01",
        "through": "2026-04-15",
    }
    with sqlite3.connect(config.database_path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM garmin_sync_runs WHERE invocation_id='full-resume'"
        ).fetchone()[0] == 1
        assert connection.execute(
            """SELECT count(*) FROM source_revisions
               WHERE resource_kind='steps'"""
        ).fetchone()[0] == 15
        assert connection.execute(
            """SELECT complete_through_local_date FROM garmin_sync_cursors
               WHERE resource_kind='steps'"""
        ).fetchone()[0] == "2026-04-15"


def test_cursor_stops_at_gap_then_advances_after_same_pipeline_refetch(
    tmp_path: Path,
) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.failures[("steps", "2026-04-05")] = GarminError("network")
    first = tool.execute(
        SyncRequest(
            "full",
            through_local_date="2026-04-15",
            resource_kinds=("steps",),
            invocation_id="gap-first",
        )
    )
    assert first.status == "partial"
    with sqlite3.connect(config.database_path) as connection:
        assert connection.execute(
            """SELECT complete_through_local_date FROM garmin_sync_cursors
               WHERE resource_kind='steps'"""
        ).fetchone()[0] == "2026-04-04"

    transport.failures.clear()
    repaired = tool.execute(
        SyncRequest(
            "full",
            through_local_date="2026-04-15",
            resource_kinds=("steps",),
            invocation_id="gap-second",
        )
    )
    assert repaired.status == "succeeded"
    with sqlite3.connect(config.database_path) as connection:
        assert connection.execute(
            """SELECT complete_through_local_date FROM garmin_sync_cursors
               WHERE resource_kind='steps'"""
        ).fetchone()[0] == "2026-04-15"
        assert connection.execute(
            """SELECT count(*) FROM garmin_sync_gaps
               WHERE resource_kind='steps' AND status IN ('open','deferred')"""
        ).fetchone()[0] == 0


def test_incremental_retries_at_most_one_hundred_preexisting_due_gaps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, tool, transport = _setup(tmp_path, max_repairs=100)
    monkeypatch.setattr("trainlab.garmin.HEALTH_RESOURCES", ("steps",))
    repository = GarminRepository(config)
    connection = repository.connect()
    subject = repository.subject(connection)
    connection.execute(
        """INSERT INTO garmin_sync_cursors(
               subject_id,resource_kind,cursor_grain,complete_through_local_date,
               last_success_at_utc,catalog_version
           ) VALUES(?,?,'local_date',?,?,?)""",
        (
            subject, "steps", "2026-04-14",
            "2026-04-15T00:00:00Z", "garmin-v3",
        ),
    )
    first_gap_day = date(2025, 1, 1)
    for index in range(105):
        day = (first_gap_day + timedelta(days=index)).isoformat()
        repository.gap(
            connection, subject, "steps",
            f"garmin:health:steps:{day}", day, "fetch", "network",
        )
    connection.close()

    result = tool.execute(
        SyncRequest(
            "incremental",
            through_local_date="2026-04-15",
            invocation_id="bounded-gaps",
        )
    )
    assert result.status == "succeeded"
    with sqlite3.connect(config.database_path) as connection:
        counts = dict(connection.execute(
            """SELECT status,count(*) FROM garmin_sync_gaps
               WHERE resource_kind='steps' GROUP BY status"""
        ))
    assert counts == {"open": 5, "resolved": 100}
    historical_calls = [
        call for call in transport.health_calls if call[1] < "2026-04-01"
    ]
    assert len(historical_calls) == 100


def test_snapshot_is_partial_noop_then_revision_and_never_advances_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, tool, transport = _setup(tmp_path)
    monkeypatch.setattr("trainlab.garmin.HEALTH_RESOURCES", ("user_summary",))
    transport.health_payloads["user_summary"] = lambda local_date: {
        "calendarDate": local_date,
        "steps": 1,
    }
    first = tool.execute(
        SyncRequest(
            "snapshot",
            snapshot_local_date="2026-04-17",
            invocation_id="snapshot-one",
        )
    )
    second = tool.execute(
        SyncRequest(
            "snapshot",
            snapshot_local_date="2026-04-17",
            invocation_id="snapshot-two",
        )
    )
    transport.health_payloads["user_summary"] = lambda local_date: {
        "calendarDate": local_date,
        "steps": 2,
    }
    third = tool.execute(
        SyncRequest(
            "snapshot",
            snapshot_local_date="2026-04-17",
            invocation_id="snapshot-three",
        )
    )
    assert first.status == second.status == third.status == "succeeded"
    assert second.counts["unchanged"] >= 1
    assert third.counts["revised"] >= 1
    assert first.coverage_state == second.coverage_state == third.coverage_state == "partial"
    with sqlite3.connect(config.database_path) as connection:
        assert connection.execute(
            """SELECT count(*) FROM source_revisions
               WHERE resource_kind='user_summary'"""
        ).fetchone()[0] == 2
        assert connection.execute(
            """SELECT count(*) FROM resource_coverage
               WHERE resource_kind='user_summary'
                 AND local_date='2026-04-17'
                 AND availability_state='partial'"""
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM garmin_sync_cursors"
        ).fetchone()[0] == 0


def test_snapshot_revisits_uploaded_activity_until_fit_pipeline_can_fill_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, tool, transport = _setup(tmp_path)
    monkeypatch.setattr("trainlab.garmin.HEALTH_RESOURCES", ())
    transport.entries = [{
        "activityId": 71,
        "startTimeGMT": "2026-04-17T00:00:00Z",
    }]
    outcomes = iter(("not_available", "fit"))
    fit_calls: list[str] = []

    def staged_fit(
        _conn: sqlite3.Connection,
        _run: int,
        _subject: int,
        provider_id: str,
        _activity: int,
        _start_utc: str,
        _sport: str,
        _day: date,
        _receipt: Any,
    ) -> str:
        fit_calls.append(provider_id)
        return next(outcomes)

    monkeypatch.setattr(tool, "_collect_activity_fit", staged_fit)
    monkeypatch.setattr(
        tool, "_collect_activity_chart_fallback", lambda *_args: None
    )
    first = tool.execute(
        SyncRequest(
            "snapshot",
            snapshot_local_date="2026-04-17",
            invocation_id="activity-before-fit",
        )
    )
    second = tool.execute(
        SyncRequest(
            "snapshot",
            snapshot_local_date="2026-04-17",
            invocation_id="activity-after-fit",
        )
    )
    assert first.status == second.status == "succeeded"
    assert fit_calls == ["71", "71"]
    assert transport.list_calls == [
        ("2026-04-17", "2026-04-17"),
        ("2026-04-17", "2026-04-17"),
    ]
    with sqlite3.connect(config.database_path) as connection:
        assert connection.execute(
            """SELECT count(*) FROM activities
               WHERE provider_activity_id='71' AND provider_state='active'"""
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM garmin_sync_cursors"
        ).fetchone()[0] == 0


def test_completed_modes_reject_today_and_snapshot_rejects_future_without_login(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _config, tool, transport = _setup(tmp_path)

    def unexpected_login() -> None:
        raise AssertionError("invalid range reached provider")

    monkeypatch.setattr(transport, "login", unexpected_login)
    with pytest.raises(
        ValueError, match="completed_mode_through_must_be_before_today"
    ):
        tool.execute(
            SyncRequest(
                "incremental",
                through_local_date="2026-04-17",
                invocation_id="today-invalid",
            )
        )
    with pytest.raises(ValueError, match="snapshot_date_in_future"):
        tool.execute(
            SyncRequest(
                "snapshot",
                snapshot_local_date="2026-04-18",
                invocation_id="future-invalid",
            )
        )
