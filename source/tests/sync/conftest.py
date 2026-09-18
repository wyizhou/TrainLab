from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest
import requests

from tests.sync.auth_support import OfflineGarmin


@pytest.fixture(autouse=True)
def block_external_connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in ("GARTH_HOME", "GARTH_TOKEN", "GARMINTOKENS", "GARTH_TELEMETRY"):
        monkeypatch.delenv(name, raising=False)
    attempts: list[bool] = []

    def denied(*args: Any, **kwargs: Any) -> Any:
        attempts.append(True)
        raise AssertionError("External socket connection blocked")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    yield
    assert not attempts


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> OfflineGarmin:
    import garth.sso
    server = OfflineGarmin()
    monkeypatch.setattr(garth.sso, "OAUTH_CONSUMER", {})

    def send(self: Any, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        return server.send(request, **kwargs)

    monkeypatch.setattr(requests.Session, "send", send)
    return server
