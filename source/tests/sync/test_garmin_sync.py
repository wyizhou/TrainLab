from __future__ import annotations

import hashlib
import importlib
import json
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from tests.fit.fit_bytes import activity_data, frame
from trainlab import garmin_sync
from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.paths import ACTIVITIES_DIR, GARMIN_CONFIG_PATH, activity_fit_name
from trainlab.contracts.time import FIRST_SYNC_LOOKBACK, SYNC_INTERVAL, format_utc
from trainlab.fit import import_fit_file
from trainlab.garmin_sync import (
    GarminActivity,
    GarminActivityPage,
    GarminSyncClient,
    GarminSyncError,
    GarminSyncState,
    extract_single_fit,
    load_sync_state,
    run_garmin_sync,
    save_sync_state,
    should_run_sync,
)


def write_auth(root: Path, value: dict[str, Any] | None = None) -> None:
    path = root / GARMIN_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"token": "secret"} if value is None else value), encoding="utf-8")


def zip_payload(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@dataclass
class FakeClient:
    pages: dict[str | None, GarminActivityPage]
    downloads: dict[str, bytes] = field(default_factory=dict)
    manual_required: bool = False
    sessions: int = 0
    list_calls: list[tuple[datetime, datetime, str | None]] = field(default_factory=list)
    downloaded_ids: list[str] = field(default_factory=list)

    @contextmanager
    def session(self) -> Iterator[GarminSyncClient]:
        self.sessions += 1
        if self.manual_required:
            raise GarminSyncError(ErrorCode.AUTH_REFRESH_REQUIRED, "Manual login required")
        yield self

    def list_activities(
        self,
        *,
        start_utc: datetime,
        end_utc: datetime,
        page_token: str | None,
    ) -> GarminActivityPage:
        self.list_calls.append((start_utc, end_utc, page_token))
        return self.pages[page_token]

    def download_activity_fit(self, activity: GarminActivity) -> bytes:
        self.downloaded_ids.append(activity.remote_id)
        return self.downloads[activity.remote_id]


def test_initial_sync_uses_seven_day_window_paginates_dedupes_refreshes_and_imports(tmp_path: Path) -> None:
    now = datetime(2030, 1, 8, 12, 0, tzinfo=UTC)
    write_auth(tmp_path, {"token": "old"})
    first_start = datetime(2030, 1, 7, 1, 2, 3, tzinfo=UTC)
    second_start = datetime(2030, 1, 8, 2, 3, 4, tzinfo=UTC)
    first = GarminActivity("remote-1", first_start)
    duplicate = GarminActivity("remote-1", first_start)
    second = GarminActivity("remote-2", second_start)
    fit_one = frame(activity_data(start=1263000000))
    fit_two = frame(activity_data(start=1264000000))
    client = FakeClient(
        pages={
            None: GarminActivityPage((first, duplicate), "next"),
            "next": GarminActivityPage((second,)),
        },
        downloads={"remote-1": fit_one, "remote-2": zip_payload({"payload/activity.fit": fit_two})},
    )

    result = run_garmin_sync(tmp_path, client, now_utc=now, importer=import_fit_file)

    assert result.ok is True
    assert result.due is True
    assert result.window_start_utc == format_utc(now - FIRST_SYNC_LOOKBACK)
    assert result.window_end_utc == format_utc(now)
    assert result.skipped_remote_ids == ("remote-1",)
    assert [call[2] for call in client.list_calls] == [None, "next"]
    assert client.list_calls[0][0] == now - FIRST_SYNC_LOOKBACK
    assert client.list_calls[0][1] == now
    assert client.sessions == 1
    assert json.loads((tmp_path / GARMIN_CONFIG_PATH).read_text(encoding="utf-8")) == {"token": "old"}
    assert client.downloaded_ids == ["remote-1", "remote-2"]
    assert len(result.downloaded) == 2
    for downloaded, fit_bytes, start in zip(result.downloaded, (fit_one, fit_two), (first_start, second_start), strict=True):
        expected_name = activity_fit_name(start.strftime("%Y%m%d"), downloaded.fit_sha256)
        assert downloaded.fit_path == (ACTIVITIES_DIR / expected_name).as_posix()
        assert (tmp_path / downloaded.fit_path).read_bytes() == fit_bytes
    state = load_sync_state(tmp_path)
    assert state.last_attempt_at_utc == now
    assert state.last_success_at_utc == now
    assert set(state.synced) == {"remote-1", "remote-2"}
    assert (tmp_path / "states/data.db").is_file()
    assert "secret" not in json.dumps(result.to_json(), ensure_ascii=False)


def test_three_hour_due_policy_and_already_synced_skip(tmp_path: Path) -> None:
    now = datetime(2030, 1, 8, 12, 0, tzinfo=UTC)
    earlier = now - timedelta(hours=1)
    save_sync_state(tmp_path, GarminSyncState(last_attempt_at_utc=earlier, last_success_at_utc=earlier))
    client = FakeClient(pages={None: GarminActivityPage(())})
    write_auth(tmp_path)

    assert should_run_sync(load_sync_state(tmp_path), now) is False
    not_due = run_garmin_sync(tmp_path, client, now_utc=now)

    assert not_due.ok is True
    assert not_due.due is False
    assert client.list_calls == []

    synced_item = next(iter(load_sync_state(tmp_path).synced.values()), None)
    assert synced_item is None
    save_sync_state(
        tmp_path,
        GarminSyncState(last_attempt_at_utc=now - SYNC_INTERVAL, last_success_at_utc=earlier, synced={}),
    )
    activity = GarminActivity("already", now)
    fit_bytes = b"not parsed because already synced"
    state = GarminSyncState(
        last_attempt_at_utc=now - SYNC_INTERVAL,
        last_success_at_utc=earlier,
        synced={
            "already": garmin_sync.SyncedActivity(
                "already", "a" * 64, "states/activities/old.fit", "b" * 64, format_utc(now)
            )
        },
    )
    save_sync_state(tmp_path, state)
    client = FakeClient(pages={None: GarminActivityPage((activity,))}, downloads={"already": fit_bytes})

    result = run_garmin_sync(tmp_path, client, now_utc=now, importer=lambda *_args, **_kwargs: "a" * 64)

    assert result.ok is True
    assert result.skipped_remote_ids == ("already",)
    assert result.downloaded == ()
    assert client.downloaded_ids == []


def test_unknown_date_zip_extraction_and_zip_errors(tmp_path: Path) -> None:
    now = datetime(2030, 1, 8, 12, 0, tzinfo=UTC)
    write_auth(tmp_path)
    fit_bytes = b"synthetic fit bytes"
    activity = GarminActivity("unknown", None)
    client = FakeClient(
        pages={None: GarminActivityPage((activity,))},
        downloads={"unknown": zip_payload({"one.FIT": fit_bytes})},
    )

    result = run_garmin_sync(
        tmp_path,
        client,
        now_utc=now,
        importer=lambda *_args, **_kwargs: "c" * 64,
    )

    assert result.ok is True
    assert len(result.downloaded) == 1
    assert Path(result.downloaded[0].fit_path).name == activity_fit_name(None, result.downloaded[0].fit_sha256)
    assert (tmp_path / result.downloaded[0].fit_path).read_bytes() == fit_bytes
    with pytest.raises(GarminSyncError) as no_fit:
        extract_single_fit(zip_payload({"readme.txt": b"no fit"}))
    with pytest.raises(GarminSyncError) as multi_fit:
        extract_single_fit(zip_payload({"a.fit": b"a", "b.fit": b"b"}))
    assert no_fit.value.code == ErrorCode.DATA_INVALID
    assert multi_fit.value.code == ErrorCode.DATA_INVALID


def test_import_failure_keeps_atomic_fit_file_but_does_not_mark_synced(tmp_path: Path) -> None:
    now = datetime(2030, 1, 8, 12, 0, tzinfo=UTC)
    write_auth(tmp_path)
    activity = GarminActivity("remote", now)
    fit_bytes = b"complete original bytes"
    client = FakeClient(pages={None: GarminActivityPage((activity,))}, downloads={"remote": fit_bytes})

    def failing_importer(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("parse failed")

    result = run_garmin_sync(tmp_path, client, now_utc=now, importer=failing_importer)

    assert result.ok is False
    assert result.code == ErrorCode.EXTERNAL_SERVICE_FAILED
    expected_name = activity_fit_name("20300108", hashlib.sha256(fit_bytes).hexdigest())
    final_path = tmp_path / ACTIVITIES_DIR / expected_name
    assert final_path.read_bytes() == fit_bytes
    assert not list(final_path.parent.glob("*.tmp"))
    assert load_sync_state(tmp_path).synced == {}


def test_partial_import_failure_preserves_previous_success_time(tmp_path: Path) -> None:
    previous = datetime(2031, 2, 7, 12, 0, tzinfo=UTC)
    now = previous + SYNC_INTERVAL
    write_auth(tmp_path)
    first = GarminActivity("remote-ok", now - timedelta(minutes=5))
    second = GarminActivity("remote-fail", now)
    first_fit = b"first complete fit bytes"
    second_fit = b"second complete fit bytes"
    client = FakeClient(
        pages={None: GarminActivityPage((first, second))},
        downloads={"remote-ok": first_fit, "remote-fail": second_fit},
    )
    save_sync_state(tmp_path, GarminSyncState(last_attempt_at_utc=previous, last_success_at_utc=previous))
    imported: list[str] = []

    def partly_failing_importer(
        instance_root: Path, fit_path: Path, *, parsed_at_utc: datetime | None = None
    ) -> str:
        _ = (instance_root, parsed_at_utc)
        if fit_path.read_bytes() == second_fit:
            raise RuntimeError("parse failed")
        imported.append(fit_path.name)
        return "a" * 64

    result = run_garmin_sync(
        tmp_path, client, now_utc=now, importer=partly_failing_importer, force=True
    )

    assert result.ok is False
    assert result.code == ErrorCode.EXTERNAL_SERVICE_FAILED
    first_name = activity_fit_name("20310207", hashlib.sha256(first_fit).hexdigest())
    second_name = activity_fit_name("20310207", hashlib.sha256(second_fit).hexdigest())
    assert imported == [first_name]
    assert (tmp_path / ACTIVITIES_DIR / first_name).read_bytes() == first_fit
    assert (tmp_path / ACTIVITIES_DIR / second_name).read_bytes() == second_fit
    state = load_sync_state(tmp_path)
    assert state.last_attempt_at_utc == now
    assert state.last_success_at_utc == previous
    assert set(state.synced) == {"remote-ok"}
    assert "remote-fail" not in state.synced


def test_auth_manual_missing_config_and_busy_are_explicit_failures(tmp_path: Path) -> None:
    now = datetime(2030, 1, 8, 12, 0, tzinfo=UTC)
    manual = FakeClient(pages={None: GarminActivityPage(())}, manual_required=True)
    write_auth(tmp_path)

    manual_result = run_garmin_sync(tmp_path, manual, now_utc=now)

    assert manual_result.ok is False
    assert manual_result.code == ErrorCode.AUTH_REFRESH_REQUIRED
    assert manual.list_calls == []

    missing_root = tmp_path / "missing"
    missing = garmin_sync.run_real_garmin_sync(missing_root, now_utc=now)
    assert missing.ok is False
    assert missing.code == ErrorCode.AUTH_REFRESH_REQUIRED

    assert garmin_sync._SYNC_LOCK.acquire(blocking=False) is True
    try:
        busy = run_garmin_sync(tmp_path, manual, now_utc=now, force=True)
    finally:
        garmin_sync._SYNC_LOCK.release()
    assert busy.ok is False
    assert busy.code == ErrorCode.RUN_BUSY


def test_state_and_auth_paths_must_stay_inside_instance(tmp_path: Path) -> None:
    now = datetime(2030, 1, 8, 12, 0, tzinfo=UTC)
    outside = Path("../secret.json")
    client = FakeClient(pages={None: GarminActivityPage(())})

    result = run_garmin_sync(tmp_path, client, now_utc=now, state_path=outside)

    assert result.ok is False
    assert result.code == ErrorCode.INVALID_ARGUMENT
    assert client.sessions == 0

def test_di_requires_login_without_constructing_sdk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_auth(tmp_path, {"di_token": "access-secret", "di_refresh_token": "refresh-secret", "di_client_id": "client-id"})
    before = (tmp_path / GARMIN_CONFIG_PATH).read_bytes()

    def forbidden(name: str) -> Any:
        pytest.fail("DI must not import SDK")

    monkeypatch.setattr(importlib, "import_module", forbidden)
    result = garmin_sync.run_real_garmin_sync(tmp_path, now_utc=datetime.now(UTC))
    assert result.code == ErrorCode.AUTH_REFRESH_REQUIRED
    assert (tmp_path / GARMIN_CONFIG_PATH).read_bytes() == before
    assert "secret" not in json.dumps(result.to_json())


def test_real_due_and_busy_precede_sdk_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    save_sync_state(tmp_path, GarminSyncState(now, now))

    def forbidden(name: str) -> Any:
        pytest.fail("Not-due or busy must not import SDK")

    monkeypatch.setattr(importlib, "import_module", forbidden)
    result = garmin_sync.run_real_garmin_sync(tmp_path, now_utc=now)
    assert result.ok and not result.due
    with garmin_sync._SYNC_LOCK:
        result = garmin_sync.run_real_garmin_sync(tmp_path, now_utc=now, force=True)
    assert result.code == ErrorCode.RUN_BUSY
    assert not (tmp_path / GARMIN_CONFIG_PATH).exists()
