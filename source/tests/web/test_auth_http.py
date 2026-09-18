from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest
import requests
from fastapi.testclient import TestClient

from tests.sync.auth_support import CODE, PASSWORD, SECRET, OfflineGarmin
from trainlab.contracts.web import API_ROUTES
from trainlab.garmin_auth import GarminAuthService
from trainlab.local_web.auth_security import COOKIE, ORIGIN, PREFIX
from trainlab.local_web.server import WebAppSettings, create_app


def session(client: TestClient) -> dict[str, str]:
    response = client.get(PREFIX + "/session", headers={"X-TrainLab-GUI": "1"})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=strict" in response.headers["set-cookie"]
    assert "Max-Age" not in response.headers["set-cookie"]
    return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["data"]["csrf"]}


def status(client: TestClient) -> dict[str, Any]:
    return client.get(PREFIX + "/status", headers={"X-TrainLab-GUI": "1"}).json()["data"]  # type: ignore[no-any-return]


def login(client: TestClient, headers: dict[str, str], region: str = "com") -> Any:
    return client.post(PREFIX + "/login", headers=headers, json={"region": region, "username": "synthetic@example.invalid", "password": PASSWORD})


@pytest.mark.parametrize("region", ["com", "cn"])
@pytest.mark.parametrize("mfa", [False, True])
def test_sdk_login_and_mfa_saved_with_exact_routes(client: TestClient, offline: OfflineGarmin, region: str, mfa: bool, tmp_path: Path) -> None:
    headers = session(client)
    offline.mfa = mfa
    result = login(client, headers, region)
    assert result.status_code == 200, result.text
    if mfa:
        flow = result.json()["data"]["login"]
        assert flow["state"] == "needs_mfa"
        assert status(client)["login"] == flow
        result = client.post(PREFIX + "/mfa", headers=headers, json={"attempt_id": flow["attempt_id"], "code": CODE})
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert data["stored"]["saved"] and data["stored"]["region"] == region
    assert data["stored"]["server_verified"] is False
    assert data["login"]["state"] == "completed"
    assert offline.exchange_count == 1
    stored = GarminAuthService(tmp_path).status().data
    assert isinstance(stored, dict) and stored["saved"]
    health = client.get("/api/health").json()["data"]
    assert {(r["method"], r["path"]) for r in health["routes"]} == {(r.method, r.path) for r in API_ROUTES}
    assert len(API_ROUTES) == 16
    app: Any = client.app
    registered = {(method, route.path) for route in app.routes if hasattr(route, "methods")
                  for method in route.methods if route.path.startswith("/api/") and route.path != "/api/{_path:path}"}
    assert registered == {(r.method, r.path) for r in API_ROUTES}
    assert all(secret not in result.text for secret in (SECRET, PASSWORD, CODE, "flow_id", "revision"))


@pytest.mark.parametrize("password", ["  synthetic secret  ", "   "])
def test_password_is_not_trimmed(client: TestClient, offline: OfflineGarmin, monkeypatch: pytest.MonkeyPatch, password: str) -> None:
    headers = session(client)
    observed: list[bool] = []
    original = offline.send
    def inspect(request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        if request.method == "POST" and "/sso/signin" in str(request.url):
            observed.append(parse_qs(str(request.body), keep_blank_values=True)["password"] == [password])
        return original(request, **kwargs)
    monkeypatch.setattr(offline, "send", inspect)
    response = client.post(PREFIX + "/login", headers=headers,
                           json={"region": "com", "username": "synthetic", "password": password})
    assert response.status_code == 200
    assert observed == [True]


def test_cancel_old_attempt_cross_session_and_duplicate(client: TestClient, offline: OfflineGarmin) -> None:
    headers = session(client)
    offline.mfa = True
    attempt = login(client, headers).json()["data"]["login"]["attempt_id"]
    cookie = client.cookies.get(COOKIE)
    client.cookies.clear()
    other = session(client)
    assert status(client)["login"] == {"state": "busy_elsewhere"}
    count = len(offline.calls)
    for action, extra in (("cancel", {}), ("mfa", {"code": CODE})):
        assert client.post(PREFIX + "/" + action, headers=other, json={"attempt_id": attempt, **extra}).status_code == 403
    assert len(offline.calls) == count
    client.cookies.clear()
    client.cookies.set(COOKIE, cookie or "", domain="127.0.0.1", path=PREFIX)
    assert client.post(PREFIX + "/cancel", headers=headers, json={"attempt_id": attempt}).status_code == 200
    assert client.post(PREFIX + "/cancel", headers=headers, json={"attempt_id": attempt}).status_code == 200
    new = login(client, headers).json()["data"]["login"]["attempt_id"]
    assert client.post(PREFIX + "/cancel", headers=headers, json={"attempt_id": attempt}).status_code == 400
    assert status(client)["login"]["attempt_id"] == new
    response = client.post(PREFIX + "/mfa", headers=headers, json={"attempt_id": new, "code": CODE})
    assert response.status_code == 200
    assert client.post(PREFIX + "/mfa", headers=headers, json={"attempt_id": new, "code": CODE}).status_code == 400
    assert sum("verifyMFA" in path for path in offline.calls) == 1


@pytest.mark.parametrize("failure,code", [(401,409), (403,409), (429,429), (503,502)])
def test_errors_private_old_saved_unchanged(client: TestClient, offline: OfflineGarmin, failure: int, code: int, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    headers = session(client)
    assert login(client, headers).status_code == 200
    pointer = tmp_path / "states/verification/garmin.json"
    before = pointer.read_bytes()
    offline.mfa = True
    attempt = login(client, headers).json()["data"]["login"]["attempt_id"]
    offline.failure_path, offline.failure_status = "user-settings", failure
    response = client.post(PREFIX + "/mfa", headers=headers, json={"attempt_id": attempt, "code": CODE})
    assert response.status_code == code
    assert not response.json()["ok"]
    assert pointer.read_bytes() == before
    assert status(client)["stored"]["saved"]
    assert all(secret not in response.text + caplog.text for secret in (SECRET, PASSWORD, CODE))


def test_no_construct_side_effect_and_restart(tmp_path: Path, offline: OfflineGarmin) -> None:
    config = WebAppSettings(instance_root=tmp_path, project_root=Path(__file__).parents[3], auth_maintenance=False)
    app = create_app(config)
    assert not list(tmp_path.iterdir()) and not offline.calls
    with TestClient(app, base_url=ORIGIN) as first:
        headers = session(first)
        login(first, headers, "cn")
        offline.mfa = True
        attempt = login(first, headers).json()["data"]["login"]["attempt_id"]
        cookie = first.cookies.get(COOKIE)
    config.auth_maintenance = True
    with TestClient(create_app(config), base_url=ORIGIN) as second:
        second.cookies.set(COOKIE, cookie or "", domain="127.0.0.1", path=PREFIX)
        assert second.post(PREFIX + "/mfa", headers=headers, json={"attempt_id": attempt, "code": CODE}).status_code == 409
        result = second.get(PREFIX + "/session", headers={"X-TrainLab-GUI": "1"})
        assert result.json()["data"]["session_replaced"]
        data = status(second)
        assert data["stored"]["saved"] and data["stored"]["region"] == "cn"
        assert data["login"]["state"] == "idle"
        assert data["maintenance"]["last_refreshed_at_utc"] is None
        assert second.get("/api/health").json()["data"]["starts_background_jobs"]


def test_canary_scanner_positive_control(client: TestClient, caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    headers = session(client)
    response = login(client, headers)
    canaries = [PASSWORD, CODE]
    def scan(text: str) -> bool:
        return any(value in text for value in canaries)
    assert scan(PASSWORD) and scan(CODE)
    assert not scan(response.text + caplog.text)
    for file in tmp_path.rglob("*"):
        if file.is_file():
            assert not scan(file.read_text())
    assert SECRET not in json.dumps(status(client))
