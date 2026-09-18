"""Synthetic-testable Garmin sync orchestration for ADHOC-0031 B4."""

from __future__ import annotations

import hashlib
import json
import threading
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, Protocol

from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.paths import (
    ACTIVITIES_DIR,
    GARMIN_CONFIG_PATH,
    STATE_ROOT,
    activity_fit_name,
)
from trainlab.contracts.time import (
    SYNC_INTERVAL,
    ensure_utc,
    format_utc,
    initial_sync_window,
    utc_fit_date,
)
from trainlab.fit import import_fit_file

GARMIN_SYNC_STATE_PATH = STATE_ROOT / "garmin-sync.json"
_SYNC_LOCK = threading.Lock()


@dataclass(frozen=True)
class GarminActivity:
    remote_id: str
    start_time_utc: datetime | None


@dataclass(frozen=True)
class GarminActivityPage:
    activities: tuple[GarminActivity, ...]
    next_page_token: str | None = None


@dataclass(frozen=True)
class AuthRefreshResult:
    status: Literal["ok", "manual_required"]
    updated_config: Mapping[str, Any] | None = None

    @classmethod
    def ok(cls, updated_config: Mapping[str, Any] | None = None) -> AuthRefreshResult:
        return cls("ok", updated_config)

    @classmethod
    def manual_required(cls) -> AuthRefreshResult:
        return cls("manual_required")


class GarminSyncClient(Protocol):
    def refresh_auth(self, auth_config: Mapping[str, Any]) -> AuthRefreshResult: ...

    def list_activities(
        self,
        *,
        start_utc: datetime,
        end_utc: datetime,
        page_token: str | None,
    ) -> GarminActivityPage: ...

    def download_activity_fit(self, activity: GarminActivity) -> bytes: ...


class FitImporter(Protocol):
    def __call__(
        self,
        instance_root: Path,
        fit_path: Path,
        *,
        parsed_at_utc: datetime | None = None,
    ) -> str: ...


@dataclass(frozen=True)
class SyncedActivity:
    remote_id: str
    activity_id: str
    fit_path: str
    fit_sha256: str
    start_time_utc: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "remote_id": self.remote_id,
            "activity_id": self.activity_id,
            "fit_path": self.fit_path,
            "fit_sha256": self.fit_sha256,
            "start_time_utc": self.start_time_utc,
        }


@dataclass(frozen=True)
class GarminSyncState:
    last_attempt_at_utc: datetime | None = None
    last_success_at_utc: datetime | None = None
    synced: Mapping[str, SyncedActivity] = field(default_factory=dict)

    def sync_window(self, now_utc: datetime) -> tuple[datetime, datetime]:
        end = ensure_utc(now_utc)
        if self.last_success_at_utc is None:
            return initial_sync_window(end)
        return ensure_utc(self.last_success_at_utc), end

    def due(self, now_utc: datetime) -> bool:
        if self.last_attempt_at_utc is None:
            return True
        return ensure_utc(now_utc) - ensure_utc(self.last_attempt_at_utc) >= SYNC_INTERVAL

    def to_json(self) -> dict[str, Any]:
        return {
            "last_attempt_at_utc": None
            if self.last_attempt_at_utc is None
            else format_utc(self.last_attempt_at_utc),
            "last_success_at_utc": None
            if self.last_success_at_utc is None
            else format_utc(self.last_success_at_utc),
            "synced": {key: value.to_json() for key, value in sorted(self.synced.items())},
        }


@dataclass(frozen=True)
class GarminSyncResult:
    ok: bool
    code: ErrorCode | None
    message: str
    due: bool
    window_start_utc: str | None
    window_end_utc: str | None
    downloaded: tuple[SyncedActivity, ...] = ()
    skipped_remote_ids: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "code": None if self.code is None else self.code.value,
            "message": self.message,
            "due": self.due,
            "window_start_utc": self.window_start_utc,
            "window_end_utc": self.window_end_utc,
            "downloaded": [item.to_json() for item in self.downloaded],
            "skipped_remote_ids": list(self.skipped_remote_ids),
        }


class GarminSyncError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(code.value + ": " + message)
        self.code = code
        self.message = message


class PyGarminConnectAdapter:
    """Thin optional adapter; tests use fakes and this class performs no import until constructed."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def refresh_auth(self, auth_config: Mapping[str, Any]) -> AuthRefreshResult:
        refresh = getattr(self._client, "refresh", None)
        if refresh is None:
            return AuthRefreshResult.ok(auth_config)
        refreshed = refresh()
        if refreshed is False:
            return AuthRefreshResult.manual_required()
        if isinstance(refreshed, Mapping):
            return AuthRefreshResult.ok(refreshed)
        return AuthRefreshResult.ok(auth_config)

    def list_activities(
        self,
        *,
        start_utc: datetime,
        end_utc: datetime,
        page_token: str | None,
    ) -> GarminActivityPage:
        if page_token is not None:
            return GarminActivityPage(())
        raw = self._client.list_activities(start_utc, end_utc)
        return GarminActivityPage(tuple(_activity_from_mapping(item) for item in raw))

    def download_activity_fit(self, activity: GarminActivity) -> bytes:
        data = self._client.download_activity(activity.remote_id)
        if not isinstance(data, bytes):
            raise GarminSyncError(ErrorCode.EXTERNAL_SERVICE_FAILED, "Garmin download did not return bytes")
        return data


def should_run_sync(state: GarminSyncState, now_utc: datetime) -> bool:
    return state.due(now_utc)


def load_garmin_auth_config(instance_root: Path, relative_path: Path = GARMIN_CONFIG_PATH) -> dict[str, Any]:
    path = _inside_instance(instance_root, relative_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GarminSyncError(ErrorCode.CONFIG_UNAVAILABLE, "Garmin auth config is unavailable") from exc
    except json.JSONDecodeError as exc:
        raise GarminSyncError(ErrorCode.DATA_INVALID, "Garmin auth config is invalid JSON") from exc
    if not isinstance(data, dict):
        raise GarminSyncError(ErrorCode.DATA_INVALID, "Garmin auth config must be a JSON object")
    return data


def load_sync_state(instance_root: Path, relative_path: Path = GARMIN_SYNC_STATE_PATH) -> GarminSyncState:
    path = _inside_instance(instance_root, relative_path)
    if not path.exists():
        return GarminSyncState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GarminSyncError(ErrorCode.DATA_INVALID, "Garmin sync state is invalid JSON") from exc
    if not isinstance(data, dict):
        raise GarminSyncError(ErrorCode.DATA_INVALID, "Garmin sync state must be a JSON object")
    synced_raw = data.get("synced", {})
    if not isinstance(synced_raw, dict):
        raise GarminSyncError(ErrorCode.DATA_INVALID, "Garmin sync state synced map is invalid")
    synced: dict[str, SyncedActivity] = {}
    for key, value in synced_raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise GarminSyncError(ErrorCode.DATA_INVALID, "Garmin sync state synced item is invalid")
        try:
            synced[key] = SyncedActivity(
                remote_id=_require_str(value, "remote_id"),
                activity_id=_require_str(value, "activity_id"),
                fit_path=_require_str(value, "fit_path"),
                fit_sha256=_require_str(value, "fit_sha256"),
                start_time_utc=_optional_str(value, "start_time_utc"),
            )
        except KeyError as exc:
            raise GarminSyncError(ErrorCode.DATA_INVALID, "Garmin sync state synced item is incomplete") from exc
    return GarminSyncState(
        last_attempt_at_utc=_parse_optional_utc(data.get("last_attempt_at_utc")),
        last_success_at_utc=_parse_optional_utc(data.get("last_success_at_utc")),
        synced=synced,
    )


def save_sync_state(
    instance_root: Path,
    state: GarminSyncState,
    relative_path: Path = GARMIN_SYNC_STATE_PATH,
) -> None:
    path = _inside_instance(instance_root, relative_path)
    _write_json_atomic(path, state.to_json())


def run_garmin_sync(
    instance_root: Path,
    client: GarminSyncClient,
    *,
    now_utc: datetime,
    auth_config_path: Path = GARMIN_CONFIG_PATH,
    state_path: Path = GARMIN_SYNC_STATE_PATH,
    importer: FitImporter = import_fit_file,
    force: bool = False,
) -> GarminSyncResult:
    now = ensure_utc(now_utc)
    if not _SYNC_LOCK.acquire(blocking=False):
        return GarminSyncResult(False, ErrorCode.RUN_BUSY, "Garmin sync is already running", False, None, None)
    try:
        state = load_sync_state(instance_root, state_path)
        if not force and not state.due(now):
            start, end = state.sync_window(now)
            return GarminSyncResult(
                True,
                None,
                "Garmin sync is not due",
                False,
                format_utc(start),
                format_utc(end),
            )
        start, end = state.sync_window(now)
        attempted_state = GarminSyncState(now, state.last_success_at_utc, state.synced)
        current_state = attempted_state
        save_sync_state(instance_root, attempted_state, state_path)
        try:
            auth_config = load_garmin_auth_config(instance_root, auth_config_path)
            refreshed = client.refresh_auth(auth_config)
            if refreshed.status == "manual_required":
                return _sync_failure(
                    instance_root,
                    state_path,
                    current_state,
                    ErrorCode.AUTH_REFRESH_REQUIRED,
                    "Garmin authentication requires manual login or MFA",
                    start,
                    end,
                )
            if refreshed.updated_config is not None and dict(refreshed.updated_config) != auth_config:
                _write_json_atomic(_inside_instance(instance_root, auth_config_path), refreshed.updated_config)
            listed = _list_new_activities(client, start, end, attempted_state)
            downloaded: list[SyncedActivity] = []
            synced = dict(attempted_state.synced)
            for activity in listed.new_activities:
                item = _download_store_import(instance_root, client, activity, importer, now)
                synced[activity.remote_id] = item
                downloaded.append(item)
                current_state = GarminSyncState(now, attempted_state.last_success_at_utc, synced)
                save_sync_state(instance_root, current_state, state_path)
            final_state = GarminSyncState(now, now, synced)
            save_sync_state(instance_root, final_state, state_path)
            return GarminSyncResult(
                True,
                None,
                "Garmin sync completed",
                True,
                format_utc(start),
                format_utc(end),
                tuple(downloaded),
                listed.skipped_remote_ids,
            )
        except GarminSyncError as exc:
            return _sync_failure(instance_root, state_path, current_state, exc.code, exc.message, start, end)
        except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
            return _sync_failure(
                instance_root,
                state_path,
                current_state,
                ErrorCode.EXTERNAL_SERVICE_FAILED,
                exc.__class__.__name__,
                start,
                end,
            )
    finally:
        _SYNC_LOCK.release()


@dataclass(frozen=True)
class _ListedActivities:
    new_activities: tuple[GarminActivity, ...]
    skipped_remote_ids: tuple[str, ...]


def _list_new_activities(
    client: GarminSyncClient,
    start: datetime,
    end: datetime,
    state: GarminSyncState,
) -> _ListedActivities:
    page_token: str | None = None
    seen: set[str] = set()
    new: list[GarminActivity] = []
    skipped: list[str] = []
    while True:
        page = client.list_activities(start_utc=start, end_utc=end, page_token=page_token)
        for activity in page.activities:
            if activity.remote_id in seen:
                skipped.append(activity.remote_id)
                continue
            seen.add(activity.remote_id)
            if activity.remote_id in state.synced:
                skipped.append(activity.remote_id)
                continue
            new.append(activity)
        if page.next_page_token is None:
            return _ListedActivities(tuple(new), tuple(skipped))
        page_token = page.next_page_token


def _download_store_import(
    instance_root: Path,
    client: GarminSyncClient,
    activity: GarminActivity,
    importer: FitImporter,
    now: datetime,
) -> SyncedActivity:
    payload = client.download_activity_fit(activity)
    fit_bytes = extract_single_fit(payload)
    fit_sha = hashlib.sha256(fit_bytes).hexdigest()
    filename = activity_fit_name(utc_fit_date(activity.start_time_utc), fit_sha)
    relative_fit_path = ACTIVITIES_DIR / filename
    absolute_fit_path = _inside_instance(instance_root, relative_fit_path)
    if not absolute_fit_path.exists():
        _write_bytes_atomic(absolute_fit_path, fit_bytes)
    elif absolute_fit_path.read_bytes() != fit_bytes:
        raise GarminSyncError(ErrorCode.SOURCE_CONFLICT, "existing FIT filename has different bytes")
    activity_id = importer(instance_root, absolute_fit_path, parsed_at_utc=now)
    return SyncedActivity(
        remote_id=activity.remote_id,
        activity_id=activity_id,
        fit_path=relative_fit_path.as_posix(),
        fit_sha256=fit_sha,
        start_time_utc=None if activity.start_time_utc is None else format_utc(activity.start_time_utc),
    )


def extract_single_fit(payload: bytes) -> bytes:
    if not zipfile.is_zipfile(BytesIO(payload)):
        return payload
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        fits = [name for name in archive.namelist() if name.lower().endswith(".fit") and not name.endswith("/")]
        if len(fits) != 1:
            raise GarminSyncError(ErrorCode.DATA_INVALID, "Garmin ZIP must contain exactly one FIT file")
        return archive.read(fits[0])


def _sync_failure(
    instance_root: Path,
    state_path: Path,
    attempted_state: GarminSyncState,
    code: ErrorCode,
    message: str,
    start: datetime,
    end: datetime,
) -> GarminSyncResult:
    save_sync_state(instance_root, attempted_state, state_path)
    return GarminSyncResult(False, code, message, True, format_utc(start), format_utc(end))


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    try:
        temp.write_bytes(content)
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    try:
        temp.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def _inside_instance(instance_root: Path, relative_path: Path) -> Path:
    if relative_path.is_absolute():
        raise GarminSyncError(ErrorCode.INVALID_ARGUMENT, "path must be instance-relative")
    root = instance_root.resolve(strict=False)
    path = (root / relative_path).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise GarminSyncError(ErrorCode.INVALID_ARGUMENT, "path escapes instance root") from exc
    return path


def _parse_optional_utc(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GarminSyncError(ErrorCode.DATA_INVALID, "timestamp must be a string or null")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise GarminSyncError(ErrorCode.DATA_INVALID, "timestamp is not UTC format") from exc
    return parsed


def _require_str(value: Mapping[str, Any], key: str) -> str:
    item = value[key]
    if not isinstance(item, str):
        raise KeyError(key)
    return item


def _optional_str(value: Mapping[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None or isinstance(item, str):
        return item
    raise KeyError(key)


def _activity_from_mapping(value: Mapping[str, Any]) -> GarminActivity:
    remote_id = value.get("remote_id") or value.get("activity_id")
    if not isinstance(remote_id, str):
        raise GarminSyncError(ErrorCode.DATA_INVALID, "Garmin activity id is missing")
    raw_start = value.get("start_time_utc")
    if raw_start is None:
        start = None
    elif isinstance(raw_start, datetime):
        start = ensure_utc(raw_start)
    elif isinstance(raw_start, str):
        start = _parse_optional_utc(raw_start)
    else:
        raise GarminSyncError(ErrorCode.DATA_INVALID, "Garmin activity start time is invalid")
    return GarminActivity(remote_id, start)
