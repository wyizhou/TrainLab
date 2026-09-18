from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import requests

from tests.sync.auth_support import CODE, PASSWORD, SECRET, OfflineGarmin
from trainlab.contracts.errors import ErrorCode, ErrorEnvelope
from trainlab.contracts.paths import GARMIN_CONFIG_PATH
from trainlab.garmin_auth import GarminAuthService


def data(result: ErrorEnvelope) -> dict[str, Any]:
    assert result.ok, result.to_json()
    assert isinstance(result.data, dict)
    return result.data


def test_login_status_restart_and_safe_results(tmp_path: Path, offline: OfflineGarmin, caplog: pytest.LogCaptureFixture) -> None:
    service = GarminAuthService(tmp_path)
    assert data(service.status())["state"] == "manual_required"
    result = service.begin_login("synthetic@example.invalid", PASSWORD, is_cn=False)
    assert data(result)["state"] == "authenticated"
    calls = len(offline.calls)
    status = data(GarminAuthService(tmp_path).status())
    assert status["saved"] and not status["server_verified"]
    assert len(offline.calls) == calls
    assert all(secret not in json.dumps(result.to_json()) + repr(service) + caplog.text for secret in (SECRET, PASSWORD, CODE))
    assert all(PASSWORD.encode() not in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())


def test_mfa_complete_cancel_unknown_empty_and_consumed(tmp_path: Path, offline: OfflineGarmin) -> None:
    offline.mfa = True
    service = GarminAuthService(tmp_path)
    flow = data(service.begin_login("synthetic@example.invalid", PASSWORD, is_cn=False))
    assert flow["state"] == "needs_mfa"
    assert service._flow is not None
    assert service._flow.sdk._client.username is None
    assert service._flow.sdk._client.password is None
    assert service._flow.sdk._client.garth.last_resp.request is None
    assert not (tmp_path / GARMIN_CONFIG_PATH).exists()
    assert not data(service.status())["saved"]
    count = len(offline.calls)
    assert not service.submit_mfa("unknown", CODE).ok
    assert not service.submit_mfa(flow["flow_id"], "").ok
    assert not service.begin_login("synthetic@example.invalid", PASSWORD, is_cn=False).ok
    assert len(offline.calls) == count
    assert data(service.submit_mfa(flow["flow_id"], CODE))["state"] == "authenticated"
    count = len(offline.calls)
    assert not service.submit_mfa(flow["flow_id"], CODE).ok
    data(service.cancel_login(flow["flow_id"]))
    data(service.cancel_login(flow["flow_id"]))
    assert len(offline.calls) == count
    flow = data(service.begin_login("synthetic@example.invalid", PASSWORD, is_cn=False))
    data(service.cancel_login(flow["flow_id"]))
    assert not service.submit_mfa(flow["flow_id"], CODE).ok
    assert data(service.status())["saved"]


@pytest.mark.parametrize("mode", ["expired", "bad-code", "settings-failed", "timeout", "generation"])
def test_mfa_failures_consume_flow_without_replacing_old(
    tmp_path: Path, offline: OfflineGarmin, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    clock = [10.0]
    service = GarminAuthService(tmp_path, monotonic=lambda: clock[0])
    data(service.begin_login("synthetic@example.invalid", PASSWORD, is_cn=False))
    offline.mfa = True
    flow = data(service.begin_login("synthetic@example.invalid", PASSWORD, is_cn=False))
    if mode == "generation":
        offline.mfa = False
        data(GarminAuthService(tmp_path).begin_login("synthetic@example.invalid", PASSWORD, is_cn=False))
    before = (tmp_path / GARMIN_CONFIG_PATH).read_bytes()
    calls = len(offline.calls)
    if mode == "expired":
        clock[0] += 300
    elif mode == "bad-code":
        offline.bad_mfa = True
    elif mode == "settings-failed":
        offline.failure_path = "user-settings"
    elif mode == "timeout":
        def timeout(*args: Any, **kwargs: Any) -> Any:
            raise requests.Timeout(SECRET)
        monkeypatch.setattr(requests.Session, "send", timeout)
    result = service.submit_mfa(flow["flow_id"], CODE)
    assert not result.ok and result.error is not None
    expected = {"expired": ErrorCode.TIMEOUT, "timeout": ErrorCode.TIMEOUT, "generation": ErrorCode.SOURCE_CONFLICT, "bad-code": ErrorCode.AUTH_REFRESH_REQUIRED}
    if mode == "bad-code":
        assert result.error.details["reason"] == "mfa_verification_incomplete"
        assert "验证未完成" in result.error.message
    assert result.error.code == expected.get(mode, ErrorCode.EXTERNAL_SERVICE_FAILED)
    if mode in {"generation", "expired"}:
        assert len(offline.calls) == calls
    assert (tmp_path / GARMIN_CONFIG_PATH).read_bytes() == before
    assert not service.submit_mfa(flow["flow_id"], CODE).ok
    assert SECRET not in json.dumps(result.to_json())


def test_mfa_concurrent_submit_is_once(tmp_path: Path, offline: OfflineGarmin, monkeypatch: pytest.MonkeyPatch) -> None:
    offline.mfa = True
    service = GarminAuthService(tmp_path)
    flow = data(service.begin_login("synthetic@example.invalid", PASSWORD, is_cn=False))
    entered, release = threading.Event(), threading.Event()
    original = offline.send

    def blocked(request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        if "/verifyMFA/" in str(request.url):
            entered.set()
            assert release.wait(10)
        return original(request, **kwargs)

    monkeypatch.setattr(offline, "send", blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.submit_mfa, flow["flow_id"], CODE)
        assert entered.wait(10)
        busy = service.submit_mfa(flow["flow_id"], CODE)
        assert busy.error is not None and busy.error.code == ErrorCode.RUN_BUSY
        release.set()
        assert future.result().ok
    assert offline.exchange_count == 1


def test_construct_is_side_effect_free_and_naive_time_rejected(tmp_path: Path) -> None:
    root = tmp_path / "absent"
    service = GarminAuthService(root)
    assert not root.exists()
    result = service.maintain_once(now_utc=datetime(2030, 1, 1))  # noqa: DTZ001
    assert result.error is not None and result.error.code == ErrorCode.INVALID_ARGUMENT
    assert not root.exists()
    assert service.maintain_once(now_utc=datetime.now(UTC)).error is not None
