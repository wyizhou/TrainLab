from __future__ import annotations

import os
import socket
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import urlparse

import requests

from tests.sync.auth_support import SECRET, OfflineGarmin


class ControlledClock:
    def __init__(self) -> None:
        self.offset = 0.0

    def timestamp(self) -> float:
        return time.time() + self.offset

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp(), UTC)

    def monotonic(self) -> float:
        return time.monotonic() + self.offset

    def install(self) -> None:
        import garth.auth_tokens
        import garth.sso
        clock = SimpleNamespace(time=self.timestamp)
        cast(Any, garth.sso).time = clock
        cast(Any, garth.auth_tokens).time = clock
        garth.sso.OAUTH_CONSUMER = {}


class AuthTransport(OfflineGarmin):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, str]] = []
        self.mode = "normal"
        self.timeout_path = ""
        self.gate = threading.Event()
        self.gate.set()
        self.entered = threading.Event()
        self.delay_path = ""
        self.save_failure = False
        self.external_attempts = 0

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        parsed = urlparse(str(request.url))
        assert parsed.scheme == "https"
        assert parsed.hostname in {"thegarth.s3.amazonaws.com", "sso.garmin.com", "sso.garmin.cn", "connectapi.garmin.com", "connectapi.garmin.cn"}
        self.events.append({"method": str(request.method), "host": str(parsed.hostname), "path": parsed.path})
        if self.delay_path and self.delay_path in parsed.path:
            self.entered.set()
            assert self.gate.wait(20)
        if (self.mode == "timeout" and "signin" in parsed.path) or (self.timeout_path and self.timeout_path in parsed.path):
            raise requests.Timeout(SECRET)
        result = super().send(request, **kwargs)
        if self.mode == "html" and "signin" in parsed.path:
            result._content = b"<html>synthetic-private-page</html>"
        return result

    def install(self) -> None:
        server = self
        def send(session: Any, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
            return server.send(request, **kwargs)
        cast(Any, requests.Session).send = send
        original_replace = os.replace
        def replace(source: Any, target: Any, *args: Any, **kwargs: Any) -> None:
            if self.save_failure and Path(target).name == "garmin.json":
                raise OSError(SECRET)
            original_replace(source, target, *args, **kwargs)
        cast(Any, os).replace = replace

    def block_network(self) -> None:
        original = socket.socket.connect
        original_ex = socket.socket.connect_ex
        def allowed(address: Any) -> bool:
            return isinstance(address, tuple) and address[0] == "127.0.0.1" and address[1] in (8080, 8081)
        def connect(sock: socket.socket, address: Any) -> Any:
            if not allowed(address):
                self.external_attempts += 1
                raise AssertionError("external socket denied")
            return original(sock, address)
        def connect_ex(sock: socket.socket, address: Any) -> Any:
            if not allowed(address):
                self.external_attempts += 1
                raise AssertionError("external socket denied")
            return original_ex(sock, address)
        cast(Any, socket.socket).connect = connect
        cast(Any, socket.socket).connect_ex = connect_ex
