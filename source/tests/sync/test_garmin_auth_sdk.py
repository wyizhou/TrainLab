from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

import pytest
import requests

from tests.sync.auth_support import CODE, PASSWORD, SECRET, OfflineGarmin
from trainlab.contracts.errors import ErrorCode
from trainlab.garmin_auth_sdk import GarminSDK
from trainlab.garmin_auth_types import GarminAuthError
from trainlab.garmin_privacy import private_garmin_logs


@pytest.mark.parametrize("is_cn", [False, True])
def test_actual_login_mfa_refresh_and_serialize(tmp_path: Path, offline: OfflineGarmin, is_cn: bool) -> None:
    sdk = GarminSDK(is_cn=is_cn)
    assert sdk.begin("synthetic@example.invalid", PASSWORD)
    before = sdk.fingerprint()
    sdk.refresh()
    assert sdk.fingerprint() != before
    sdk.dump(tmp_path)
    other = GarminSDK(is_cn=is_cn)
    other.load(tmp_path)
    assert sdk.fingerprint() == other.fingerprint()
    sdk.close()
    other.close()
    offline.mfa = True
    sdk = GarminSDK(is_cn=is_cn)
    assert not sdk.begin("synthetic@example.invalid", PASSWORD)
    with pytest.raises(GarminAuthError):
        sdk.times()
    sdk.submit(CODE)
    sdk.times()
    assert offline.exchange_count == 3
    sdk.close()


@pytest.mark.parametrize("env", ["GARTH_HOME", "GARTH_TOKEN", "GARMINTOKENS", "GARTH_TELEMETRY"])
def test_first_import_and_environment_conflict_is_offline(env: str, tmp_path: Path) -> None:
    code = '''
import socket, sys
socket.socket.connect = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("network"))
socket.socket.connect_ex = socket.socket.connect
from trainlab.garmin_auth import GarminAuthService
from trainlab.garmin_auth_sdk import GarminSDK
from trainlab.garmin_auth_types import GarminAuthError
assert 'garminconnect' not in sys.modules and 'garth' not in sys.modules
GarminAuthService(__import__('pathlib').Path(sys.argv[1]))
assert 'garth' not in sys.modules
try:
    GarminSDK(is_cn=False)
except GarminAuthError as error:
    assert error.reason == 'sdk_environment_conflict'
else:
    raise AssertionError('environment accepted')
assert 'garth' not in sys.modules
print('lazy import, no private read or network')
'''
    child_env = {k: v for k, v in os.environ.items() if k not in {"GARTH_HOME", "GARTH_TOKEN", "GARMINTOKENS", "GARTH_TELEMETRY"}}
    child_env[env] = "true" if env == "GARTH_TELEMETRY" else SECRET
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], env=child_env, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    assert SECRET not in result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == []


def test_new_logger_during_boundary_is_safe_with_positive_control(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        with private_garmin_logs():
            log = logging.getLogger("garth.new-during-boundary")
            try:
                raise ValueError(SECRET)
            except ValueError:
                log.exception("%s", SECRET, extra={"password": PASSWORD}, stack_info=True)
        assert SECRET not in caplog.text + repr([r.__dict__ for r in caplog.records])
        log.warning(SECRET)
        assert SECRET in caplog.text
    caplog.clear()


@pytest.mark.parametrize("status,code", [(401, ErrorCode.AUTH_REFRESH_REQUIRED), (403, ErrorCode.AUTH_REFRESH_REQUIRED), (429, ErrorCode.RESOURCE_LIMIT), (503, ErrorCode.EXTERNAL_SERVICE_FAILED)])
def test_sdk_http_failure_safe_chains(offline: OfflineGarmin, status: int, code: ErrorCode, caplog: pytest.LogCaptureFixture) -> None:
    offline.failure_path = "/sso/signin"
    offline.failure_status = status
    with caplog.at_level(logging.DEBUG), pytest.raises(GarminAuthError) as error:
        GarminSDK(is_cn=False).begin("synthetic@example.invalid", PASSWORD)
    assert error.value.code == code
    assert SECRET not in caplog.text + "".join(traceback.format_exception(error.value)) + repr(error.value)
    caplog.clear()


def test_consumer_timeout_and_local_expiry_missing_are_controlled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import garth.sso
    monkeypatch.setattr(garth.sso, "OAUTH_CONSUMER", {})
    seen: list[Any] = []

    def timeout(self: Any, request: requests.PreparedRequest, **kwargs: Any) -> Any:
        seen.append(kwargs.get("timeout"))
        raise requests.Timeout(SECRET)

    monkeypatch.setattr(requests.Session, "send", timeout)
    sdk = GarminSDK(is_cn=False)
    with pytest.raises(GarminAuthError) as error:
        sdk.begin("synthetic@example.invalid", PASSWORD)
    assert error.value.code == ErrorCode.TIMEOUT and seen == [15]
    (tmp_path / "oauth1_token.json").write_text(json.dumps({"oauth_token": SECRET, "oauth_token_secret": SECRET}))
    (tmp_path / "oauth2_token.json").write_text(json.dumps({"access_token": SECRET}))
    with pytest.raises(GarminAuthError) as invalid:
        sdk.load(tmp_path)
    assert invalid.value.code == ErrorCode.DATA_INVALID
    assert SECRET not in "".join(traceback.format_exception(invalid.value))
    sdk.close()
