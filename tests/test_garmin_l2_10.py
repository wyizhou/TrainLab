"""Offline L2-10 acceptance: activity inventory, summary, and remote state."""
from __future__ import annotations

import copy
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.garmin import GarminCollectionTool, GarminConfig, GarminError, SyncRequest
from trainlab.garmin_client import GarminConnectTransport, TokenStore


def _entry(activity_id: int, day: str) -> dict[str, object]:
    return {"activityId": activity_id, "startTimeGMT": f"{day}T00:00:00Z"}


def _summary(activity_id: int, day: str) -> dict[str, object]:
    return {
        "activityId": activity_id,
        "activityName": f"synthetic-{activity_id}",
        "activityType": {"typeKey": "running"},
        "startTimeGMT": f"{day}T00:00:00Z",
        "duration": 600,
        "movingDuration": 590,
        "distance": 2000,
    }


class ActivityTransport:
    def __init__(self, entries: list[dict[str, object]]) -> None:
        self.entries = copy.deepcopy(entries)
        self.summaries = {
            str(entry["activityId"]): _summary(
                int(entry["activityId"]), str(entry["startTimeGMT"])[:10]
            )
            for entry in entries
        }
        self.count_values: list[int] = []
        self.page_payloads: dict[int, object] = {}
        self.page_errors: dict[int, GarminError] = {}
        self.count_calls = 0
        self.page_calls: list[tuple[int, int]] = []
        self.list_calls: list[tuple[str | None, str | None]] = []
        self.summary_calls: list[str] = []

    def login(self) -> None:
        return None

    def identity(self) -> str:
        return "l2-10-fixture"

    def fetch_health(self, _resource: str, _day: str):
        return []

    def fetch_range(self, _resource: str, _start: str, _end: str):
        return []

    def fetch_account(self, _resource: str, _provider_device_id: str | None = None):
        return []

    def activity_count(self) -> int:
        self.count_calls += 1
        return self.count_values.pop(0) if self.count_values else len(self.entries)

    def activity_page(self, offset: int, limit: int):
        self.page_calls.append((offset, limit))
        if offset in self.page_errors:
            raise self.page_errors[offset]
        if offset in self.page_payloads:
            return copy.deepcopy(self.page_payloads[offset])
        return copy.deepcopy(self.entries[offset:offset + limit])

    def list_activities(self, start: str | None, through: str | None):
        self.list_calls.append((start, through))
        return copy.deepcopy(self.entries)

    def activity_summary(self, activity_id: str):
        self.summary_calls.append(activity_id)
        return copy.deepcopy(self.summaries[activity_id])

    def activity_original(self, _activity_id: str):
        raise AssertionError("L2-10 must not download FIT")

    def activity_extra(self, _activity_id: str, _role: str):
        raise AssertionError("L2-10 must not fetch enrichments")


def _setup(tmp_path: Path, entries: list[dict[str, object]]):
    root = tmp_path / "data"
    foundation = FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state/ready.json",
        root / "state/locks/foundation.lock",
    )
    assert FoundationTool(foundation).execute(
        FoundationRequest("init", "l2-10", "2026-01-01T00:00:00Z")
    ).status == "initialized"
    config = GarminConfig(
        foundation.database_path,
        foundation.raw_root,
        foundation.state_root,
        "2026-04-01",
        request_min_interval_ms=0,
    )
    transport = ActivityTransport(entries)
    tool = GarminCollectionTool(
        config,
        transport,
        sleep=lambda _seconds: None,
        clock=lambda: datetime(2026, 4, 17),
        monotonic=lambda: 1000.0,
    )
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    return config, tool, transport


def _full(tool: GarminCollectionTool, invocation: str):
    return tool.execute(
        SyncRequest("full", through_local_date="2026-04-15", resource_kinds=("activity_summary",), invocation_id=invocation)
    )


def test_full_uses_count_complete_pages_all_history_filters_through_and_replays_noop(
    tmp_path: Path,
) -> None:
    entries = [_entry(index, "2020-01-01") for index in range(1, 205)]
    entries.append(_entry(205, "2026-04-16"))
    config, tool, transport = _setup(tmp_path, entries)
    first = _full(tool, "inventory-full-one")
    assert first.status == "succeeded"
    assert transport.count_calls == 2
    assert transport.page_calls == [(0, 100), (100, 100), (200, 5)]
    assert len(transport.summary_calls) == 204
    assert "205" not in transport.summary_calls
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM raw_objects WHERE resource_kind='activity_inventory'"
        ).fetchone()[0] == 3
        assert conn.execute(
            "SELECT count(*) FROM source_revisions WHERE resource_kind='activity_inventory'"
        ).fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM activities").fetchone()[0] == 204
        assert conn.execute(
            "SELECT min(local_date) FROM activities"
        ).fetchone()[0] == "2020-01-01"
        assert conn.execute(
            "SELECT count(*) FROM raw_objects WHERE resource_kind='activity_fit'"
        ).fetchone()[0] == 0
        revisions_before = conn.execute(
            "SELECT count(*) FROM source_revisions"
        ).fetchone()[0]
    transport.summary_calls.clear()
    second = _full(tool, "inventory-full-two")
    assert second.status == "succeeded"
    assert second.counts["unchanged"] == 207
    assert len(transport.summary_calls) == 204
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM source_revisions").fetchone()[0] == revisions_before
        assert conn.execute("SELECT count(*) FROM activities").fetchone()[0] == 204


def test_complete_full_runs_advance_missing_and_invocation_replay_does_not(
    tmp_path: Path,
) -> None:
    config, tool, transport = _setup(tmp_path, [_entry(1, "2026-04-15")])
    assert _full(tool, "state-present").status == "succeeded"
    transport.entries = []
    assert _full(tool, "state-missing-one").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT provider_state FROM activities WHERE provider_activity_id='1'"
        ).fetchone()[0] == "suspected_missing"
        raw_count = conn.execute("SELECT count(*) FROM raw_objects").fetchone()[0]
    # Replaying the same invocation returns the durable run receipt before
    # inventory processing, so it cannot count as another observation.
    assert _full(tool, "state-missing-one").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT provider_state FROM activities WHERE provider_activity_id='1'"
        ).fetchone()[0] == "suspected_missing"
    transport.entries = [_entry(99, "2026-04-15")]
    transport.page_errors[0] = GarminError("network")
    interrupted = _full(tool, "state-interrupted")
    assert interrupted.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT provider_state FROM activities WHERE provider_activity_id='1'"
        ).fetchone()[0] == "suspected_missing"
    transport.page_errors.clear()
    # A new successful full invocation is a second observation even when its
    # complete inventory page has the exact same empty payload.
    transport.entries = []
    assert _full(tool, "state-missing-two").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        state, deleted = conn.execute(
            """SELECT provider_state,provider_deleted_at_utc FROM activities
               WHERE provider_activity_id='1'"""
        ).fetchone()
        assert state == "provider_deleted" and deleted is not None
        assert conn.execute("SELECT count(*) FROM raw_objects").fetchone()[0] >= raw_count
    # A terminal exact replay is a no-op: it creates no third observation and
    # does not alter the already deleted state.
    assert _full(tool, "state-missing-two").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT provider_state FROM activities WHERE provider_activity_id='1'"
        ).fetchone()[0] == "provider_deleted"
    transport.entries = [_entry(1, "2026-04-15")]
    assert _full(tool, "state-reappeared").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            """SELECT provider_state,first_missing_at_utc,last_missing_at_utc,
                      provider_deleted_at_utc FROM activities
               WHERE provider_activity_id='1'"""
        ).fetchone() == ("active", None, None, None)


def test_incremental_is_window_bounded_and_snapshot_absence_never_marks_missing(
    tmp_path: Path,
) -> None:
    entries = [_entry(1, "2020-01-01"), _entry(2, "2026-04-15")]
    config, tool, transport = _setup(tmp_path, entries)
    assert _full(tool, "bounded-seed").status == "succeeded"
    transport.count_calls = 0
    transport.page_calls.clear()
    transport.list_calls.clear()
    transport.entries = []
    incremental = tool.execute(
        SyncRequest(
            "incremental",
            through_local_date="2026-04-15",
            invocation_id="bounded-incremental",
        )
    )
    assert incremental.status == "succeeded"
    assert transport.count_calls == 0 and transport.page_calls == []
    assert transport.list_calls == [("2026-04-02", "2026-04-15")]
    with sqlite3.connect(config.database_path) as conn:
        assert dict(conn.execute(
            "SELECT provider_activity_id,provider_state FROM activities ORDER BY provider_activity_id"
        )) == {"1": "active", "2": "active"}

    transport.entries = [_entry(3, "2026-04-17")]
    transport.summaries["3"] = _summary(3, "2026-04-17")
    # L2-10 state-machine isolation: L2-11 FIT transport is separately tested.
    original_activities = tool._activities
    tool._activities = lambda *args: original_activities(*args[:-1], False)  # type: ignore[method-assign]
    present = tool.execute(
        SyncRequest("snapshot", snapshot_local_date="2026-04-17", invocation_id="snapshot-present")
    )
    assert present.status == "succeeded"
    transport.entries = []
    absent = tool.execute(
        SyncRequest("snapshot", snapshot_local_date="2026-04-17", invocation_id="snapshot-absent")
    )
    assert absent.status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT provider_state FROM activities WHERE provider_activity_id='3'"
        ).fetchone()[0] == "active"


def test_count_drift_and_duplicate_ids_are_partial_and_never_mark_absence(
    tmp_path: Path,
) -> None:
    config, tool, transport = _setup(
        tmp_path, [_entry(1, "2026-04-15"), _entry(2, "2026-04-15")]
    )
    assert _full(tool, "drift-seed").status == "succeeded"
    transport.entries = [_entry(1, "2026-04-15")]
    transport.count_values = [1, 2]
    drift = _full(tool, "count-drift")
    assert drift.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT provider_state FROM activities WHERE provider_activity_id='2'"
        ).fetchone()[0] == "active"
        assert conn.execute(
            """SELECT count(*) FROM garmin_sync_gaps
               WHERE reason_code='activity_inventory_count_drift'"""
        ).fetchone()[0] == 1

    transport.count_values = []
    transport.entries = [_entry(1, "2026-04-15"), _entry(1, "2026-04-15")]
    transport.summary_calls.clear()
    duplicate = _full(tool, "duplicate-inventory")
    assert duplicate.status == "partial"
    assert transport.summary_calls == ["1"]
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT provider_state FROM activities WHERE provider_activity_id='2'"
        ).fetchone()[0] == "active"


@pytest.mark.parametrize(
    ("summary", "reason"),
    [
        (
            {
                "activityId": 2,
                "activityType": {"typeKey": "running"},
                "startTimeGMT": "2026-04-15T00:00:00Z",
            },
            "activity_summary_identity_mismatch",
        ),
        (
            {
                "activityId": 1,
                "activityType": {"typeKey": "running"},
                "startTimeGMT": "not-a-time",
            },
            "activity_summary_time_invalid",
        ),
        (
            {"activityId": 1, "startTimeGMT": "2026-04-15T00:00:00Z"},
            "activity_summary_type_invalid",
        ),
    ],
)
def test_summary_validation_failure_keeps_raw_revision_without_canonical(
    tmp_path: Path,
    summary: dict[str, object],
    reason: str,
) -> None:
    config, tool, transport = _setup(tmp_path, [_entry(1, "2026-04-15")])
    transport.summaries["1"] = summary
    receipt = _full(tool, f"summary-{reason}")
    assert receipt.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM activities").fetchone()[0] == 0
        assert conn.execute(
            """SELECT count(*) FROM source_revisions
               WHERE resource_kind='activity_summary' AND is_current=0
                 AND parsed_at_utc IS NULL"""
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM garmin_sync_gaps WHERE reason_code=?", (reason,)
        ).fetchone()[0] == 1


def test_malformed_page_and_paging_loop_keep_evidence_but_never_scan_missing(
    tmp_path: Path,
) -> None:
    config, tool, transport = _setup(tmp_path, [_entry(1, "2026-04-15")])
    transport.page_payloads[0] = {"unexpected": []}
    malformed = _full(tool, "malformed-page")
    assert malformed.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM activities").fetchone()[0] == 0
        assert conn.execute(
            """SELECT count(*) FROM source_revisions
               WHERE resource_kind='activity_inventory' AND is_current=0
                 AND parsed_at_utc IS NULL"""
        ).fetchone()[0] == 1
        assert conn.execute(
            """SELECT stage FROM garmin_sync_gaps
               WHERE reason_code='activity_inventory_page_invalid'"""
        ).fetchone()[0] == "validate"

    config_size, tool_size, transport_size = _setup(
        tmp_path / "size", [_entry(1, "2026-04-15"), _entry(2, "2026-04-15")]
    )
    transport_size.page_payloads[0] = [_entry(1, "2026-04-15")]
    assert _full(tool_size, "short-page").status == "partial"
    with sqlite3.connect(config_size.database_path) as conn:
        assert conn.execute(
            """SELECT count(*) FROM garmin_sync_gaps
               WHERE reason_code='activity_inventory_page_size_mismatch'
                 AND stage='validate'"""
        ).fetchone()[0] == 1

    config_id, tool_id, transport_id = _setup(
        tmp_path / "id", [_entry(1, "2026-04-15")]
    )
    transport_id.page_payloads[0] = [{"activityId": ""}]
    assert _full(tool_id, "invalid-id").status == "partial"
    with sqlite3.connect(config_id.database_path) as conn:
        assert conn.execute(
            """SELECT count(*) FROM garmin_sync_gaps
               WHERE reason_code='activity_inventory_id_invalid'
                 AND stage='validate'"""
        ).fetchone()[0] == 1

    loop_entries = [_entry(index, "2026-04-15") for index in range(1, 101)]
    config2, tool2, transport2 = _setup(tmp_path / "loop", loop_entries * 2)
    transport2.page_payloads[0] = loop_entries
    transport2.page_payloads[100] = loop_entries
    looped = _full(tool2, "paging-loop")
    assert looped.status == "partial"
    with sqlite3.connect(config2.database_path) as conn:
        assert conn.execute(
            """SELECT count(*) FROM garmin_sync_gaps
               WHERE reason_code='activity_inventory_paging_loop'"""
        ).fetchone()[0] == 1


def test_full_through_filter_skips_future_summary_fetch(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path, [_entry(1, "2026-04-16")])
    receipt = _full(tool, "through-filter")
    assert receipt.status == "succeeded"
    assert transport.summary_calls == []
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM activities").fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM raw_objects WHERE resource_kind='activity_inventory'"
        ).fetchone()[0] == 1


def test_pinned_transport_exposes_count_pages_and_bounded_date_inventory(tmp_path: Path) -> None:
    class Session:
        def request(self, *_args, **_kwargs):
            return object()

    class Client:
        def __init__(self) -> None:
            self.cs = Session()
            self._api_session = Session()
            self.calls: list[tuple[object, ...]] = []

        def count_activities(self):
            self.calls.append(("count",))
            return 2

        def get_activities(self, offset: int, limit: int):
            self.calls.append(("page", offset, limit))
            return {"activities": [_entry(1, "2026-04-15")]}

        def get_activities_by_date(
            self,
            start: str,
            through: str,
            *,
            sortorder: str,
        ):
            self.calls.append(("bounded", start, through, sortorder))
            return [_entry(1, "2026-04-15")]

    client = Client()
    transport = GarminConnectTransport(
        None,
        None,
        TokenStore(tmp_path / "tokens"),
        client=client,
    )
    assert transport.activity_count() == 2
    assert transport.activity_page(0, 1) == {
        "activities": [_entry(1, "2026-04-15")]
    }
    assert transport.list_activities("2026-04-02", "2026-04-15") == [
        _entry(1, "2026-04-15")
    ]
    assert client.calls == [
        ("count",),
        ("page", 0, 1),
        ("bounded", "2026-04-02", "2026-04-15", "asc"),
    ]
