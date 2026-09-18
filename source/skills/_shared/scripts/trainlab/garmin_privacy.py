from __future__ import annotations

import logging
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from types import TracebackType
from typing import Any

_ACTIVE: ContextVar[bool] = ContextVar("garmin_private_logs", default=False)
_DEPENDENCIES = ("garminconnect", "garth", "requests", "requests_oauthlib", "oauthlib", "urllib3")
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_ORIGINAL = logging.Logger.makeRecord


def _private_record(
    self: logging.Logger, name: str, level: int, fn: str, lno: int,
    msg: object, args: tuple[Any, ...] | Mapping[str, Any],
    exc_info: tuple[type[BaseException], BaseException, TracebackType | None] | tuple[None, None, None] | None,
    func: str | None = None, extra: Mapping[str, object] | None = None,
    sinfo: str | None = None,
) -> logging.LogRecord:
    if _ACTIVE.get() and name.split(".", 1)[0] in _DEPENDENCIES:
        return logging.LogRecord(
            name, level, fn, lno,
            "Garmin SDK diagnostic withheld; use the product error code", (), None, func,
        )
    return _ORIGINAL(self, name, level, fn, lno, msg, args, exc_info, func, extra, sinfo)


@contextmanager
def private_garmin_logs() -> Iterator[None]:
    global _INSTALLED
    with _INSTALL_LOCK:
        if not _INSTALLED:
            logging.Logger.makeRecord = _private_record  # type: ignore[method-assign]
            _INSTALLED = True
    token = _ACTIVE.set(True)
    try:
        yield
    finally:
        _ACTIVE.reset(token)
