from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from trainlab.contracts.errors import ErrorCode, ErrorEnvelope, success_envelope
from trainlab.contracts.time import format_utc
from trainlab.garmin_auth import GarminAuthService
from trainlab.garmin_auth_maintenance import (
    maintenance_check_delay,
    maintenance_retry_delay,
    maintenance_retryable,
)
from trainlab.local_web.auth_security import AuthHTTPError, Sessions


def utcnow() -> datetime:
    return datetime.now(UTC)


class AuthRuntime:
    def __init__(self, owner: GarminAuthService, *, enabled: bool = True,
                 clock: Callable[[], datetime] = utcnow,
                 monotonic: Callable[[], float] = time.monotonic,
                 sessions: Sessions | None = None) -> None:
        self.owner, self.enabled = owner, enabled
        self.clock, self.monotonic = clock, monotonic
        self.sessions = sessions if sessions is not None else Sessions(clock=monotonic)
        self.busy = False
        self.stopping = False
        self.wake = asyncio.Event()
        self.jobs: set[asyncio.Task[Any]] = set()
        self.loop_task: asyncio.Task[None] | None = None
        self.revision: str | None = None
        self.flow: dict[str, Any] | None = None
        self.logins: dict[str, dict[str, Any]] = {}
        self.stored: dict[str, Any] = {"state": "unavailable", "saved": None, "region": None,
            "expires_at_utc": None, "refresh_due_at_utc": None, "observed_at_utc": None,
            "stale": True, "server_verified": False, "reason": "not_observed"}
        self.maintenance: dict[str, Any] = {"enabled": enabled, "state": "starting",
            "last_attempt_at_utc": None, "last_refreshed_at_utc": None,
            "next_check_at_utc": None, "failures": 0, "result": None, "reason": None}
        self.retry_at = 0.0

    async def start(self) -> None:
        try:
            await self._admit(self._observe)
        except Exception:  # noqa: BLE001
            self.maintenance.update(state="blocked", reason="auth_observation_failed")
        if self.enabled:
            self.loop_task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self.stopping = True
        self.maintenance["state"] = "stopping"
        self.wake.set()
        if self.loop_task is not None:
            await self.loop_task
        while self.jobs:
            await asyncio.gather(*tuple(self.jobs), return_exceptions=True)
        try:
            await asyncio.to_thread(self.owner.close)
        except Exception:  # noqa: BLE001
            self.maintenance["reason"] = "auth_cleanup_failed"
        self.sessions.items.clear()
        self.logins.clear()
        self.flow = None

    async def _admit(self, call: Callable[[], Any]) -> Any:
        if self.stopping or self.busy:
            raise AuthHTTPError(ErrorCode.RUN_BUSY, "operation_in_progress", 409)
        self.busy = True

        async def run() -> Any:
            try:
                return await call()
            finally:
                self.busy = False
        task = asyncio.create_task(run())
        self.jobs.add(task)
        def finished(done: asyncio.Task[Any]) -> None:
            self.jobs.discard(done)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def _expire_sessions(self) -> None:
        self.sessions.sweep()
        self.logins = {key: value for key, value in self.logins.items() if key in self.sessions.items}
        if self.flow is not None and self.flow["session"] not in self.sessions.items:
            await asyncio.to_thread(self.owner.cancel_login, self.flow["flow_id"])
            self.flow = None

    async def _observe(self) -> None:
        await self._expire_sessions()
        observation = await asyncio.to_thread(self.owner.observe_status)
        result = observation.result
        if not result.ok:
            assert result.error is not None
            if result.error.code == ErrorCode.RUN_BUSY:
                self.stored["stale"] = True
                return
            self.stored = {**self.stored, "state": "invalid" if result.error.code == ErrorCode.DATA_INVALID else "unavailable",
                           "saved": None, "region": None, "expires_at_utc": None,
                           "refresh_due_at_utc": None, "stale": False,
                           "observed_at_utc": format_utc(self.clock()), "reason": result.error.details.get("reason")}
            self.maintenance.update(state="blocked", reason=self.stored["reason"])
            return
        data = result.data
        assert isinstance(data, dict)
        changed = self.revision != observation.revision
        if changed:
            self.revision = observation.revision
            self.maintenance.update(state="scheduled", failures=0, reason=None, result=None,
                                    last_refreshed_at_utc=None)
            self.retry_at = 0
        if self.flow is not None and observation.active_flow_id != self.flow["flow_id"]:
            expired = self.monotonic() >= self.flow["deadline"]
            self.logins[self.flow["session"]].update(state="expired" if expired else "failed",
                reason="mfa_expired" if expired else "auth_generation_changed")
            self.flow = None
        reason = data.get("reason")
        self.stored = {"state": "stored" if data["saved"] else ("legacy" if reason == "legacy_auth_requires_login" else "missing"),
            "saved": data["saved"], "region": data.get("region"), "server_verified": False,
            "expires_at_utc": data["expires_at_utc"], "refresh_due_at_utc": data["next_check_at_utc"],
            "observed_at_utc": format_utc(self.clock()), "stale": False, "reason": reason}
        if not data["saved"]:
            self.maintenance.update(state="manual_required", reason=reason, next_check_at_utc=None)
        elif self.maintenance["state"] in ("starting", "scheduled"):
            self.maintenance.update(state="scheduled", next_check_at_utc=data["next_check_at_utc"])

    def view(self, session: str) -> dict[str, Any]:
        login = self.logins.get(session, {"state": "idle"})
        if self.flow is not None and self.flow["session"] != session:
            login = {"state": "busy_elsewhere"}
        elif self.busy and login["state"] not in ("submitting", "verifying"):
            login = {**login, "operation_in_progress": True}
        return {"stored": {**self.stored, "stale": self.busy or self.stored["stale"]},
                "login": dict(login), "maintenance": dict(self.maintenance)}

    async def status(self, session: str) -> dict[str, Any]:
        if not self.busy and not self.stopping:
            await self._admit(self._observe)
        return self.view(session)

    async def action(self, session: str, action: str, body: dict[str, str]) -> ErrorEnvelope:
        async def perform() -> ErrorEnvelope:
            await self._expire_sessions()
            if action == "maintenance/retry":
                if self.maintenance["state"] == "paused":
                    self.maintenance.update(state="scheduled", failures=0, reason=None)
                    self.retry_at = 0
                return success_envelope(self.view(session))
            if action == "login":
                await self._observe()
                if self.flow is not None:
                    raise AuthHTTPError(ErrorCode.RUN_BUSY, "login_pending", 409)
                self.logins[session] = {"state": "submitting", "region": body["region"]}
                result = await asyncio.to_thread(self.owner.begin_login, body["username"], body["password"], is_cn=body["region"] == "cn")
                if result.ok and isinstance(result.data, dict) and result.data["state"] == "needs_mfa":
                    data = result.data
                    attempt = secrets.token_urlsafe(32)
                    self.flow = {"session": session, "flow_id": data["flow_id"], "attempt": attempt,
                                 "deadline": self.monotonic() + max(0, (datetime.fromisoformat(data["expires_at_utc"]) - self.clock()).total_seconds())}
                    self.logins[session].update(state="needs_mfa", attempt_id=attempt, expires_at_utc=data["expires_at_utc"])
                    return success_envelope(self.view(session))
            else:
                previous = self.logins.get(session, {})
                if self.flow is not None and self.flow["session"] != session:
                    raise AuthHTTPError(ErrorCode.TOOL_NOT_ALLOWED, "request_not_allowed", 403)
                if body["attempt_id"] != previous.get("attempt_id"):
                    raise AuthHTTPError(ErrorCode.INVALID_ARGUMENT, "unknown_attempt", 400)
                if action == "cancel" and previous.get("state") == "cancelled":
                    return success_envelope(self.view(session))
                if self.flow is None:
                    reason = previous.get("reason") or "unknown_attempt"
                    code = ErrorCode.TIMEOUT if reason == "mfa_expired" else (ErrorCode.SOURCE_CONFLICT if reason == "auth_generation_changed" else ErrorCode.INVALID_ARGUMENT)
                    raise AuthHTTPError(code, reason)
                flow = self.flow
                if action == "cancel":
                    result = await asyncio.to_thread(self.owner.cancel_login, flow["flow_id"])
                    if result.ok:
                        self.flow = None
                        previous.update(state="cancelled")
                        return success_envelope(self.view(session))
                else:
                    previous.update(state="verifying")
                    result = await asyncio.to_thread(self.owner.submit_mfa, flow["flow_id"], body["code"])
                    if result.error is not None and result.error.code == ErrorCode.RUN_BUSY:
                        previous.update(state="needs_mfa", reason=result.error.details.get("reason"))
                        return result
                    self.flow = None
            if result.ok:
                self.logins[session].update(state="completed", reason=None)
                await self._observe()
                return success_envelope(self.view(session))
            assert result.error is not None
            reason = result.error.details.get("reason")
            self.logins[session].update(state="expired" if reason == "mfa_expired" else "failed", reason=reason)
            return result
        try:
            result: ErrorEnvelope = await self._admit(perform)
        except Exception:
            current = self.logins.get(session)
            if not self.busy and current is not None and current["state"] in ("submitting", "verifying"):
                current.update(state="failed", reason="auth_request_failed")
            raise
        self.wake.set()
        return success_envelope(self.view(session)) if result.ok else result

    async def _maintain(self) -> None:
        await self._observe()
        if self.maintenance["state"] not in ("scheduled", "retry_wait"):
            return
        due = self.stored["refresh_due_at_utc"]
        if not due or datetime.fromisoformat(due) > self.clock() or self.monotonic() < self.retry_at:
            return
        self.maintenance.update(state="running", last_attempt_at_utc=format_utc(self.clock()))
        result = await asyncio.to_thread(self.owner.maintain_once, now_utc=self.clock())
        if result.ok:
            await self._observe()
            assert isinstance(result.data, dict)
            self.maintenance.update(state="scheduled", failures=0, reason=None, result=result.data["state"],
                                    next_check_at_utc=result.data["next_check_at_utc"])
            if result.data["state"] == "refreshed":
                self.maintenance["last_refreshed_at_utc"] = format_utc(self.clock())
        else:
            assert result.error is not None
            code = result.error.code
            failures = self.maintenance["failures"] + 1
            retryable = maintenance_retryable(result)
            delay = maintenance_retry_delay(result, failures)
            state = ("paused" if delay is None else "retry_wait") if retryable else ("manual_required" if code == ErrorCode.AUTH_REFRESH_REQUIRED else "blocked")
            self.retry_at = self.monotonic() + (delay or 0)
            self.maintenance.update(state=state, failures=failures, reason=result.error.details.get("reason"),
                result="not_executed" if code == ErrorCode.RUN_BUSY else "failed",
                next_check_at_utc=format_utc(self.clock() + timedelta(seconds=delay)) if delay is not None else None)

    async def _loop(self) -> None:
        while not self.stopping:
            self.wake.clear()
            if not self.busy:
                try:
                    await self._admit(self._maintain)
                except Exception:  # noqa: BLE001
                    self.maintenance.update(state="blocked", reason="auth_maintenance_failed")
                self.wake.clear()
            delay = 60.0
            due = self.maintenance["next_check_at_utc"]
            if due:
                delay = maintenance_check_delay(datetime.fromisoformat(due), self.clock())
            if self.stopping:
                break
            try:
                await asyncio.wait_for(self.wake.wait(), delay)
            except TimeoutError:
                pass
