from __future__ import annotations

import fcntl
import logging
import os
import runpy
import socket
import termios
import time
from datetime import datetime, tzinfo
from typing import Any


def blocked(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("CLI real socket blocked")


socket.socket.connect = blocked  # type: ignore[method-assign]
socket.socket.connect_ex = blocked  # type: ignore[method-assign]

import requests

from tests.sync.auth_support import OfflineGarmin

if os.isatty(0):
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)

server = OfflineGarmin(mfa=os.getenv("AUTH_TEST_MODE") == "mfa")
if os.getenv("AUTH_TEST_NOW"):
    instant = float(os.environ["AUTH_TEST_NOW"])
    time.time = lambda: instant
    import trainlab.garmin_auth as auth
    import trainlab.garmin_auth_maintenance as maintenance

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> FrozenDateTime:
            return cls.fromtimestamp(instant, tz)

    auth.__dict__["datetime"] = FrozenDateTime
    maintenance.__dict__["datetime"] = FrozenDateTime


def send(self: Any, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
    return server.send(request, **kwargs)


requests.Session.send = send  # type: ignore[method-assign]
logging.basicConfig(level=logging.DEBUG)
runpy.run_module("trainlab.garmin_auth_cli", run_name="__main__")
