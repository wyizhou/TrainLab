from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.sync.auth_support import PASSWORD, OfflineGarmin
from tests.web.test_auth_http import login, session
from trainlab.local_web.auth_security import PREFIX


@pytest.mark.parametrize("origin", [None, "null", "https://evil.invalid", "http://127.0.0.1:8081"])
def test_exact_origin_before_sdk(client: TestClient, offline: OfflineGarmin, origin: str | None) -> None:
    headers = session(client)
    headers.pop("Origin")
    if origin is not None:
        headers["Origin"] = origin
    assert login(client, headers).status_code == 403
    assert not offline.calls


@pytest.mark.parametrize("headers", [{}, {"X-TrainLab-GUI": "1", "Sec-Fetch-Site": "same-site"},
    {"X-TrainLab-GUI": "1", "Sec-Fetch-Site": "cross-site"}, {"X-TrainLab-GUI": "1", "Origin": "null"}])
def test_bootstrap_get_source_guard(client: TestClient, headers: dict[str, str]) -> None:
    assert client.get(PREFIX + "/session", headers=headers).status_code == 403


def test_host_csrf_preflight_headers_unknown_errors(client: TestClient, offline: OfflineGarmin) -> None:
    headers = session(client)
    headers["X-CSRF-Token"] = "wrong"
    assert login(client, headers).status_code == 403
    for path in ("/", "/api/health", PREFIX + "/session"):
        response = client.get(path, headers={"Host": "evil.invalid"})
        assert response.status_code == 403
    response = client.options(PREFIX + "/login", headers={"Origin": "https://evil.invalid", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in response.headers
    response = client.get(PREFIX + "/session", headers={"X-TrainLab-GUI": "1"})
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"
    response = client.get(PREFIX + "/session?secret=" + PASSWORD, headers={"X-TrainLab-GUI": "1"})
    assert response.status_code == 400 and PASSWORD not in response.text
    assert not offline.calls


@pytest.mark.parametrize("body", [[], None, {"region": True, "username": "x", "password": "x"},
    {"region": "COM", "username": "x", "password": "x"}, {"region": "com", "username": "x", "password": 1},
    {"region": "com", "username": "x", "password": "x", "force": True},
    {"region": "com", "username": "x", "password": "x" * 1025}])
def test_strict_body(client: TestClient, offline: OfflineGarmin, body: Any) -> None:
    headers = session(client)
    assert client.post(PREFIX + "/login", headers=headers, json=body).status_code == 400
    assert not offline.calls


def test_chunked_limit_and_json(client: TestClient, offline: OfflineGarmin) -> None:
    headers = session(client)
    for data, content, expected in (("{}", "text/plain", 400), ("{", "application/json", 400),
                                     ("x" * 16385, "application/json", 413)):
        result = client.post(PREFIX + "/login", headers={**headers, "Content-Type": content}, content=data)
        assert result.status_code == expected
    result = client.post(PREFIX + "/login", headers={**headers, "Content-Type": "application/json"}, content=iter([b" " * 8192] * 3))
    assert result.status_code == 413
    duplicate = '{"region":"com","region":"cn","username":"x","password":"x"}'
    assert client.post(PREFIX + "/login", headers={**headers, "Content-Type": "application/json"}, content=duplicate).status_code == 400
    assert not offline.calls


def test_auth_exception_never_echoes(client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    headers = session(client)
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise ValueError(PASSWORD)
    app: Any = client.app
    monkeypatch.setattr(app.state.auth.owner, "begin_login", fail)
    result = login(client, headers)
    assert result.status_code == 502
    assert PASSWORD not in result.text + caplog.text
