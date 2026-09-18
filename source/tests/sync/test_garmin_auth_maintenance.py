from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.sync.auth_support import PASSWORD, OfflineGarmin
from tests.sync.test_garmin_auth import data
from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.paths import GARMIN_CONFIG_PATH
from trainlab.contracts.time import UTC_TIMESTAMP_FORMAT
from trainlab.garmin_auth import GarminAuthService
from trainlab.garmin_auth_maintenance import run_maintenance


def parse(value: str) -> datetime:
    return datetime.strptime(value, UTC_TIMESTAMP_FORMAT).replace(tzinfo=UTC)


@pytest.mark.parametrize("offset", [-1, 0, 301, 86400])
def test_maintenance_boundary_refresh_restart(
    tmp_path: Path, offline: OfflineGarmin, monkeypatch: pytest.MonkeyPatch, offset: int,
) -> None:
    import time
    service = GarminAuthService(tmp_path)
    login = data(service.begin_login("synthetic@example.invalid", PASSWORD, is_cn=False))
    now = parse(login["next_check_at_utc"]) + timedelta(seconds=offset)
    monkeypatch.setattr(time, "time", lambda: now.timestamp())
    before = (tmp_path / GARMIN_CONFIG_PATH).read_bytes()
    result = data(service.maintain_once(now_utc=now))
    assert result["state"] == ("unchanged" if offset < 0 else "refreshed")
    assert offline.exchange_count == (1 if offset < 0 else 2)
    after = (tmp_path / GARMIN_CONFIG_PATH).read_bytes()
    assert (before == after) == (offset < 0)
    fresh = data(GarminAuthService(tmp_path).status())
    assert fresh["expires_at_utc"] == result["expires_at_utc"]


@pytest.mark.parametrize("status,attempts,delays", [(503, 3, [5, 10]), (429, 3, [5, 10]), (401, 1, [])])
def test_loop_real_exchange_bounded_retry_and_manual_stop(
    tmp_path: Path, offline: OfflineGarmin, status: int, attempts: int, delays: list[int],
) -> None:
    service = GarminAuthService(tmp_path)
    login = data(service.begin_login("synthetic@example.invalid", PASSWORD, is_cn=False))
    due = parse(login["next_check_at_utc"])
    before = (tmp_path / GARMIN_CONFIG_PATH).read_bytes()
    offline.failure_path = "/exchange/"
    offline.failure_status = status
    observed: list[float] = []
    result = run_maintenance(service, clock=lambda: due, sleep=observed.append)
    assert not result.ok and result.error is not None
    assert result.error.code == {503: ErrorCode.EXTERNAL_SERVICE_FAILED, 429: ErrorCode.RESOURCE_LIMIT, 401: ErrorCode.AUTH_REFRESH_REQUIRED}[status]
    assert observed == delays
    assert sum("/exchange/" in path for path in offline.calls) == attempts + 1
    assert (tmp_path / GARMIN_CONFIG_PATH).read_bytes() == before


def test_loop_waits_rechecks_clock_and_other_owner_can_operate(
    tmp_path: Path, offline: OfflineGarmin, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time
    now = [datetime.now(UTC)]
    service = GarminAuthService(tmp_path, clock=lambda: now[0])
    login = data(service.begin_login("synthetic@example.invalid", PASSWORD, is_cn=False))
    due = parse(login["next_check_at_utc"])
    sleeps: list[float] = []
    states: list[str] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        assert data(GarminAuthService(tmp_path).status())["saved"]
        if len(sleeps) == 1:
            now[0] = due - timedelta(seconds=1)
        elif len(sleeps) == 2:
            now[0] = due
        else:
            raise KeyboardInterrupt

    monkeypatch.setattr(time, "time", lambda: now[0].timestamp())
    with pytest.raises(KeyboardInterrupt):
        run_maintenance(service, clock=lambda: now[0], sleep=sleep, emit=lambda result: states.append(data(result)["state"]))
    assert sleeps == [60, 1, 60]
    assert states == ["unchanged", "unchanged", "refreshed"]
    assert offline.exchange_count == 2


def test_immediately_due_refresh_stops_without_overwrite(tmp_path: Path, offline: OfflineGarmin) -> None:
    service = GarminAuthService(tmp_path)
    login = data(service.begin_login("synthetic@example.invalid", PASSWORD, is_cn=False))
    before = (tmp_path / GARMIN_CONFIG_PATH).read_bytes()
    offline.expiry = 1
    result = service.maintain_once(now_utc=parse(login["next_check_at_utc"]))
    assert result.error is not None and result.error.code == ErrorCode.AUTH_REFRESH_REQUIRED
    assert (tmp_path / GARMIN_CONFIG_PATH).read_bytes() == before
    assert "access_token" not in json.dumps(result.to_json())
