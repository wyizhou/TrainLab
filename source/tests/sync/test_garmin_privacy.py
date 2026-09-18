from __future__ import annotations

import base64
import json
import logging
import sqlite3
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.sync.auth_support import SECRET, OfflineGarmin, oauth_values
from tests.sync.test_garmin_sync import write_auth
from trainlab import garmin_sync as sync
from trainlab.contracts.errors import ErrorCode
from trainlab.contracts.paths import GARMIN_CONFIG_PATH
from trainlab.garmin_auth import GarminAuthService
from trainlab.garmin_auth_types import GarminAuthError
from trainlab.garmin_privacy import private_garmin_logs

MARKER = SECRET
NOW = datetime(2030, 1, 8, 12, tzinfo=UTC)


def tokenstore(root: Path, values: tuple[dict[str, Any], dict[str, Any]], kind: str) -> str:
    if kind == "encoded":
        return base64.b64encode(json.dumps(values).encode()).decode()
    root.mkdir()
    for name, value in zip(("oauth1", "oauth2"), values, strict=True):
        (root / f"{name}_token.json").write_text(json.dumps(value))
    return str(root)


def captured_text(caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]) -> str:
    output = capsys.readouterr()
    text = caplog.text + repr([r.__dict__ for r in caplog.records]) + output.out + output.err
    caplog.clear()
    return text


@pytest.mark.parametrize("kind", ["directory", "encoded"])
@pytest.mark.parametrize("invalid_token", [0, 1])
def test_malformed_real_tokenstore_no_log_traceback_or_result_leak(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str],
    kind: str, invalid_token: int,
) -> None:
    values = oauth_values()
    values[invalid_token]["oauth_token" if invalid_token == 0 else "access_token"] = {"bad": MARKER}
    write_auth(tmp_path, {"tokenstore": tokenstore(tmp_path / "tokens", values, kind)})
    with caplog.at_level(logging.DEBUG):
        result = sync.run_real_garmin_sync(tmp_path, now_utc=NOW)
        with pytest.raises(GarminAuthError) as failure, GarminAuthService(tmp_path)._session():
            pytest.fail("Invalid tokens accepted")
    trace = "".join(traceback.format_exception(failure.value))
    leaked = MARKER in captured_text(caplog, capsys) + trace + json.dumps(result.to_json())
    assert not result.ok and result.code == ErrorCode.DATA_INVALID
    assert failure.value.code == result.code
    assert not leaked, "Sensitive token value escaped the Garmin call boundary"
    assert not (tmp_path / "states/data.db").exists()


def test_invalid_di_config_has_sanitized_exception_chain(tmp_path: Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]) -> None:
    write_auth(tmp_path, {"di_token": MARKER, "di_refresh_token": MARKER, "di_client_id": MARKER, "expires_in": MARKER})
    with pytest.raises(GarminAuthError) as failure, GarminAuthService(tmp_path)._session():
        pytest.fail("DI cannot be OAuth1")
    leaked = MARKER in "".join(traceback.format_exception(failure.value)) + captured_text(caplog, capsys)
    assert failure.value.code == ErrorCode.AUTH_REFRESH_REQUIRED
    assert failure.value.reason == "legacy_auth_requires_login"
    assert not leaked, "Sensitive DI config value escaped in exception chain"


@pytest.mark.parametrize("mode", ["tokenstore", "encoded", "expired-tokenstore"])
def test_actual_sdk_list_download_import_and_refresh_still_work(
    tmp_path: Path, offline: OfflineGarmin, mode: str,
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str],
) -> None:
    values = oauth_values()
    if mode == "expired-tokenstore":
        values[1]["expires_at"] = int(time.time()) - 60
    original = tokenstore(tmp_path / "tokens", values, "encoded" if mode == "encoded" else "directory")
    write_auth(tmp_path, {"garth_tokenstore": original})
    with caplog.at_level(logging.DEBUG):
        result = sync.run_real_garmin_sync(tmp_path, now_utc=NOW)
    leaked = MARKER in captured_text(caplog, capsys) + json.dumps(result.to_json())
    assert result.ok and len(result.downloaded) == 1
    assert not leaked
    assert (tmp_path / result.downloaded[0].fit_path).read_bytes() == offline.fit
    with sqlite3.connect(tmp_path / "states/data.db") as db:
        assert db.execute("SELECT COUNT(*) FROM activities").fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM records").fetchone()[0] > 0
    assert offline.exchange_count == (1 if mode == "expired-tokenstore" else 0)
    assert any("download-service" in path for path in offline.calls)
    assert MARKER not in (tmp_path / "states/garmin-sync.json").read_text()
    config = json.loads((tmp_path / GARMIN_CONFIG_PATH).read_text())
    assert config["version"] == 1 and MARKER not in json.dumps(config)
    if mode == "expired-tokenstore":
        token = json.loads((tmp_path / config["tokenstore"] / "oauth2_token.json").read_text())
        assert token["access_token"] == SECRET + "1"
    again = sync.run_real_garmin_sync(tmp_path, now_utc=NOW, force=True)
    assert again.ok and not again.downloaded
    assert again.skipped_remote_ids == ("101",)


@pytest.mark.parametrize("operation", ["list", "download"])
@pytest.mark.parametrize("status,code", [(401, ErrorCode.AUTH_REFRESH_REQUIRED), (429, ErrorCode.RESOURCE_LIMIT), (503, ErrorCode.EXTERNAL_SERVICE_FAILED)])
def test_actual_sdk_service_failure_mapping_and_privacy(
    tmp_path: Path, offline: OfflineGarmin, caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str], operation: str, status: int, code: ErrorCode,
) -> None:
    write_auth(tmp_path, {"tokenstore": tokenstore(tmp_path / "tokens", oauth_values(), "directory")})
    offline.failure_path = "activitylist-service" if operation == "list" else "download-service"
    offline.failure_status = status
    adapter = sync.GarminConnectClientAdapter(GarminAuthService(tmp_path))
    with caplog.at_level(logging.DEBUG), pytest.raises(GarminAuthError) as failure, adapter.session():
        if operation == "list":
            adapter.list_activities(start_utc=NOW, end_utc=NOW, page_token=None)
        else:
            adapter.download_activity_fit(sync.GarminActivity("101", NOW))
    leaked = MARKER in captured_text(caplog, capsys) + "".join(traceback.format_exception(failure.value))
    assert failure.value.code == code
    assert not leaked, "SDK HTTP error leaked sensitive response text"


def test_log_boundary_is_context_local_nested_and_keeps_error_signal(caplog: pytest.LogCaptureFixture) -> None:
    sdk = logging.getLogger("garminconnect")
    unrelated = logging.getLogger("trainlab.unrelated")
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ValueError), private_garmin_logs():
            with private_garmin_logs():
                sdk.warning("%s", MARKER, extra={"token": MARKER}, stack_info=True)
            try:
                raise ValueError(MARKER)
            except ValueError:
                sdk.exception("%s", MARKER)
            unrelated.warning("unrelated diagnostic retained")
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(sdk.warning, "other-thread diagnostic retained").result()
            raise ValueError("leave boundary")
        sdk.warning("outside diagnostic retained")
    records = list(caplog.records)
    leaked = MARKER in caplog.text + repr([r.__dict__ for r in records])
    caplog.clear()
    assert not leaked
    assert [r.levelno for r in records[:2]] == [logging.WARNING, logging.ERROR]
    assert all(r.exc_info is None and r.stack_info is None for r in records[:2])
    assert [r.getMessage() for r in records[2:]] == ["unrelated diagnostic retained", "other-thread diagnostic retained", "outside diagnostic retained"]


def test_implicit_refresh_saved_even_when_data_request_fails(tmp_path: Path, offline: OfflineGarmin) -> None:
    values = oauth_values(expires_at=int(time.time()) - 60)
    write_auth(tmp_path, {"tokenstore": tokenstore(tmp_path / "tokens", values, "directory")})
    offline.failure_path = "activitylist-service"
    result = sync.run_real_garmin_sync(tmp_path, now_utc=NOW)
    assert result.code == ErrorCode.EXTERNAL_SERVICE_FAILED
    config = json.loads((tmp_path / GARMIN_CONFIG_PATH).read_text())
    saved = json.loads((tmp_path / config["tokenstore"] / "oauth2_token.json").read_text())
    assert saved["access_token"] == SECRET + "1"
    assert offline.exchange_count == 1
    assert sync.load_sync_state(tmp_path).last_success_at_utc is None
    assert not (tmp_path / "states/data.db").exists()
