from __future__ import annotations

import io
import json
import os
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.garmin import GarminCollectionTool, GarminConfig, GarminError, SyncRequest


class FakeGarmin:
    def __init__(self, fit: bytes, *, fail: str | None = None) -> None:
        self.fit, self.fail, self.calls = fit, fail, 0

    def identity(self) -> str:
        return "fake-account"
    def login(self) -> None:
        return None

    def fetch_health(self, resource_kind: str, local_date: str):
        self.calls += 1
        if self.fail == "429":
            raise GarminError("rate_limited", http_status=429, retry_after=121)
        if resource_kind == "user_summary":
            return {"steps": 1234, "restingHeartRate": 50, "calendarDate": local_date}
        if resource_kind == "sleep":
            return {"timestamp": f"{local_date}T00:00:00Z", "sleepScore": 80}
        return []

    def list_activities(self, start: str | None, through: str | None):
        return [{"activityId": 7}]

    def activity_summary(self, activity_id: str):
        return {"activityId": int(activity_id), "activityName": "synthetic", "activityType": {"typeKey": "running"}, "startTimeGMT": "2026-04-15T00:00:00Z", "duration": 10, "distance": 1000}

    def activity_original(self, activity_id: str) -> bytes:
        return self.fit

    def activity_extra(self, activity_id: str, role: str):
        return {"role": role, "value": 1} if role == "weather_json" else None


@pytest.fixture
def garmin_env(tmp_path: Path) -> tuple[GarminConfig, bytes]:
    root = tmp_path / "data"
    foundation = FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state/foundation-ready.json", root / "state/locks/foundation.lock")
    receipt = FoundationTool(foundation).execute(FoundationRequest("init", "foundation-test", "2026-01-01T00:00:00Z"))
    assert receipt.status == "initialized"
    fit = next((Path(__file__).resolve().parents[1] / "test_data" / "new").glob("Running.fit")).read_bytes()
    return GarminConfig(foundation.database_path, foundation.raw_root, foundation.state_root, "2026-04-15"), fit


def test_full_archives_projects_cursors_and_is_idempotent(garmin_env: tuple[GarminConfig, bytes]) -> None:
    config, fit = garmin_env
    tool = GarminCollectionTool(config, FakeGarmin(fit), sleep=lambda _: None, clock=lambda: datetime(2026, 4, 17))
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    first = tool.execute(SyncRequest("full", through_local_date="2026-04-15", resource_kinds=("activity_summary",), invocation_id="full-1"))
    assert first.status == "succeeded"
    assert first.counts["revised"] > 0
    conn = sqlite3.connect(config.database_path)
    assert conn.execute("SELECT count(*) FROM garmin_sync_runs").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM activities WHERE provider='garmin'").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM activity_samples").fetchone()[0] == 0
    # Cursor resources derive from the reviewed catalog rather than an
    # unversioned hand-maintained tuple.
    from trainlab.garmin_catalog import HEALTH_RESOURCES
    assert conn.execute("SELECT count(*) FROM garmin_sync_cursors").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM raw_objects WHERE resource_kind='activity_fit'").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM raw_objects WHERE resource_kind='activity_inventory'").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM source_field_catalog WHERE provider='garmin'").fetchone()[0] > 0
    conn.close()
    second = tool.execute(SyncRequest("full", through_local_date="2026-04-15", resource_kinds=("activity_summary",), invocation_id="full-2"))
    assert second.status == "succeeded"
    assert second.counts["unchanged"] > 0


def test_snapshot_does_not_advance_cursor_and_long_429_is_deferred(garmin_env: tuple[GarminConfig, bytes]) -> None:
    config, fit = garmin_env
    normal = GarminCollectionTool(config, FakeGarmin(fit), sleep=lambda _: None, clock=lambda: datetime(2026, 4, 17))
    assert normal.execute(SyncRequest("auth")).status == "succeeded"
    normal._activities = lambda *_args: None  # type: ignore[method-assign]
    normal.execute(SyncRequest("incremental", through_local_date="2026-04-15", invocation_id="inc"))
    conn = sqlite3.connect(config.database_path); before = conn.execute("SELECT max(complete_through_local_date) FROM garmin_sync_cursors").fetchone()[0]; conn.close()
    snap = normal.execute(SyncRequest("snapshot", snapshot_local_date="2026-04-17", invocation_id="snapshot"))
    assert snap.status == "succeeded" and snap.coverage_state == "partial"
    conn = sqlite3.connect(config.database_path); after = conn.execute("SELECT max(complete_through_local_date) FROM garmin_sync_cursors").fetchone()[0]; partial = conn.execute("SELECT count(*) FROM resource_coverage WHERE local_date='2026-04-17' AND availability_state='partial'").fetchone()[0]; conn.close()
    assert before == after and partial > 0
    deferred = GarminCollectionTool(config, FakeGarmin(fit, fail="429"), sleep=lambda _: None, clock=lambda: datetime(2026, 4, 17)).execute(SyncRequest("incremental", through_local_date="2026-04-16", invocation_id="limited"))
    assert deferred.status == "deferred" and deferred.next_retry_at_utc


def test_l2_10_does_not_open_zip_and_status_is_local_only(garmin_env: tuple[GarminConfig, bytes]) -> None:
    config, fit = garmin_env
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("../escape.fit", fit)
    tool = GarminCollectionTool(config, FakeGarmin(bad.getvalue()), sleep=lambda _: None, clock=lambda: datetime(2026, 4, 17))
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    result = tool.execute(SyncRequest("full", through_local_date="2026-04-15", resource_kinds=("activity_summary",), invocation_id="bad-zip"))
    assert result.status == "succeeded"
    lock = config.state_root / "locks" / "garmin.lock"; lock.parent.mkdir(parents=True, exist_ok=True); lock.write_text("{}")
    locked = tool.execute(SyncRequest("incremental", through_local_date="2026-04-15"))
    assert locked.status == "lock_busy"
    lock.unlink()
    status = GarminCollectionTool(config, None).execute(SyncRequest("status"))
    assert status.status == "succeeded"


def test_request_boundaries() -> None:
    with pytest.raises(ValueError, match="history_start_date_required"):
        GarminCollectionTool(GarminConfig(Path("x"), Path("x"), Path("x"), None)).execute(SyncRequest("full"))
    with pytest.raises(ValueError, match="repair_requires_scope"):
        GarminCollectionTool(GarminConfig(Path("x"), Path("x"), Path("x"), "2026-01-01")).execute(SyncRequest("repair"))


def test_l2_10_never_downloads_representative_fit_files(garmin_env: tuple[GarminConfig, bytes]) -> None:
    config, _ = garmin_env
    root = Path(__file__).resolve().parents[1] / "test_data" / "new"
    first_tool = GarminCollectionTool(config, FakeGarmin(next(root.glob("*.fit")).read_bytes()), sleep=lambda _: None, clock=lambda: datetime(2026, 4, 17))
    assert first_tool.execute(SyncRequest("auth")).status == "succeeded"
    for number, path in enumerate(sorted(root.glob("*.fit"))):
        result = GarminCollectionTool(config, FakeGarmin(path.read_bytes()), sleep=lambda _: None, clock=lambda: datetime(2026, 4, 17)).execute(
            SyncRequest("full", through_local_date="2026-04-15", resource_kinds=("activity_summary",), invocation_id=f"fit-{number}")
        )
        assert result.status == "succeeded", path.name
    conn = sqlite3.connect(config.database_path)
    assert conn.execute("SELECT count(*) FROM raw_objects WHERE resource_kind='activity_fit'").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM fit_unknown_message_catalog").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM fit_metric_definitions").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM strength_sets").fetchone()[0] == 0
    conn.close()


def test_auth_and_offline_repair_do_not_network(garmin_env: tuple[GarminConfig, bytes]) -> None:
    config, fit = garmin_env
    provider = FakeGarmin(fit)
    tool = GarminCollectionTool(config, provider, sleep=lambda _: None, clock=lambda: datetime(2026, 4, 17))
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    assert tool.execute(SyncRequest("full", through_local_date="2026-04-15", resource_kinds=("activity_summary",), invocation_id="repair-source")).status == "succeeded"
    calls = provider.calls
    repaired = tool.execute(SyncRequest("repair", through_local_date="2026-04-15", resource_kinds=("user_summary",), repair_strategy="reparse", invocation_id="reparse"))
    assert repaired.status == "succeeded" and provider.calls == calls
    reconciled = tool.execute(SyncRequest("repair", resource_kinds=("user_summary",), repair_strategy="reconcile", invocation_id="reconcile"))
    assert reconciled.status == "succeeded"
