from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import requests

from tests.sync.auth_support import PASSWORD, OfflineGarmin
from trainlab.garmin_auth import GarminAuthService
from trainlab.local_web.auth_runtime import AuthRuntime
from trainlab.local_web.auth_security import AuthHTTPError, BrowserSession, Sessions


def test_due_refresh_bounded_retry_and_manual_generation(tmp_path: Path, offline: OfflineGarmin) -> None:
    async def run() -> None:
        now = [datetime.now(UTC)]
        mono = [0.0]
        owner = GarminAuthService(tmp_path)
        assert owner.begin_login("synthetic", PASSWORD, is_cn=False).ok
        runtime = AuthRuntime(owner, enabled=False, clock=lambda: now[0], monotonic=lambda: mono[0])
        await runtime.start()
        await runtime._admit(runtime._maintain)
        assert offline.exchange_count == 1
        due = datetime.fromisoformat(runtime.stored["refresh_due_at_utc"])
        now[0] = due - timedelta(microseconds=1)
        await runtime._admit(runtime._maintain)
        assert offline.exchange_count == 1
        now[0] = due
        offline.failure_path = "/exchange/user/2.0"
        for i, delay in enumerate((5, 10, 0)):
            await runtime._admit(runtime._maintain)
            assert runtime.maintenance["failures"] == i + 1
            count = len(offline.calls)
            await runtime.status("unused")
            if i < 2:
                await runtime._admit(runtime._maintain)
                assert len(offline.calls) == count
            mono[0] += delay
            now[0] += timedelta(seconds=delay)
        assert runtime.maintenance["state"] == "paused"
        calls = len(offline.calls)
        await runtime._admit(runtime._maintain)
        assert len(offline.calls) == calls
        await runtime.action("unused", "maintenance/retry", {})
        offline.failure_status = 401
        await runtime._admit(runtime._maintain)
        assert runtime.maintenance["state"] == "manual_required"
        await runtime.status("unused")
        assert runtime.maintenance["state"] == "manual_required"
        calls = len(offline.calls)
        await runtime.action("unused", "maintenance/retry", {})
        await runtime._admit(runtime._maintain)
        assert len(offline.calls) == calls
        offline.failure_path = ""
        assert GarminAuthService(tmp_path).begin_login("synthetic", PASSWORD, is_cn=True).ok
        now[0] = datetime.now(UTC)
        await runtime.status("unused")
        assert runtime.maintenance["state"] == "scheduled"
        assert runtime.stored["region"] == "cn"
        assert runtime.maintenance["last_refreshed_at_utc"] is None
        await runtime.stop()
    asyncio.run(run())


@pytest.mark.parametrize("delta,expected", [(299.999, True), (300, False), (300.001, False)])
def test_exact_mfa_ttl_and_session_expiry(tmp_path: Path, offline: OfflineGarmin, delta: float, expected: bool) -> None:
    async def run() -> None:
        mono = [0.0]
        owner = GarminAuthService(tmp_path, monotonic=lambda: mono[0])
        runtime = AuthRuntime(owner, enabled=False, monotonic=lambda: mono[0], sessions=Sessions(clock=lambda: mono[0]))
        await runtime.start()
        session = BrowserSession(touched=0)
        runtime.sessions.items[session.identity] = session
        offline.mfa = True
        result = await runtime.action(session.identity, "login", {"region": "com", "username": "synthetic", "password": PASSWORD})
        assert isinstance(result.data, dict)
        attempt = result.data["login"]["attempt_id"]
        mono[0] = delta
        result = await runtime.action(session.identity, "mfa", {"attempt_id": attempt, "code": "synthetic-code"})
        assert result.ok is expected
        if not expected:
            assert result.error is not None and result.error.details["reason"] == "mfa_expired"
        await runtime.stop()
    asyncio.run(run())


def test_disconnect_shutdown_waits_for_worker_and_rejects_new(tmp_path: Path, offline: OfflineGarmin, monkeypatch: pytest.MonkeyPatch) -> None:
    entered, release = threading.Event(), threading.Event()
    original = offline.send
    def blocked(request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        if "/sso/signin" in str(request.url):
            entered.set()
            assert release.wait(10)
        return original(request, **kwargs)
    monkeypatch.setattr(offline, "send", blocked)
    async def run() -> None:
        owner = GarminAuthService(tmp_path)
        runtime = AuthRuntime(owner)
        await runtime.start()
        await asyncio.sleep(0.05)
        session = BrowserSession(touched=runtime.monotonic())
        runtime.sessions.items[session.identity] = session
        task = asyncio.create_task(runtime.action(session.identity, "login", {"region": "com", "username": "synthetic", "password": PASSWORD}))
        assert await asyncio.to_thread(entered.wait, 5)
        assert (await runtime.status(session.identity))["stored"]["stale"]
        with pytest.raises(AuthHTTPError):
            await runtime.action(session.identity, "login", {})
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        stop = asyncio.create_task(runtime.stop())
        await asyncio.sleep(0.05)
        assert not stop.done() and runtime.jobs
        with pytest.raises(AuthHTTPError):
            await runtime.action(session.identity, "maintenance/retry", {})
        release.set()
        await stop
        assert not runtime.jobs and not runtime.sessions.items
        stored = GarminAuthService(tmp_path).status().data
        assert isinstance(stored, dict) and stored["saved"]
    asyncio.run(run())
