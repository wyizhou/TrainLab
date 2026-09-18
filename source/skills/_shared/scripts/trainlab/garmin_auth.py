from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any

from trainlab.contracts.errors import ErrorCode, ErrorEnvelope, success_envelope
from trainlab.contracts.time import ensure_utc, format_utc
from trainlab.garmin_auth_sdk import GarminSDK, SDKFactory, check_environment
from trainlab.garmin_auth_store import AuthSnapshot, GarminAuthStore
from trainlab.garmin_auth_types import GarminAuthError


def _public(method: Callable[..., ErrorEnvelope]) -> Callable[..., ErrorEnvelope]:
    @wraps(method)
    def call(*args: Any, **kwargs: Any) -> ErrorEnvelope:
        try:
            return method(*args, **kwargs)
        except GarminAuthError as exc:
            return exc.envelope()
        except (ValueError, TypeError, OverflowError):
            return GarminAuthError(ErrorCode.INVALID_ARGUMENT, "invalid_input").envelope()
        except OSError:
            return GarminAuthError(ErrorCode.EXTERNAL_SERVICE_FAILED, "auth_storage_failed").envelope()
    return call


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(repr=False)
class _Flow:
    flow_id: str = field(repr=False)
    sdk: GarminSDK = field(repr=False)
    revision: str
    deadline: float
    expires: datetime


@dataclass(frozen=True, repr=False)
class AuthObservation:
    result: ErrorEnvelope
    revision: str | None = field(repr=False)
    active_flow_id: str | None = field(repr=False)


class GarminAuthService:
    def __init__(
        self, instance_root: Path, *, sdk_factory: SDKFactory = GarminSDK,
        clock: Callable[[], datetime] = _now, monotonic: Callable[[], float] = time.monotonic,
        mfa_ttl: float = 300,
    ) -> None:
        if not 0 < mfa_ttl <= 3600:
            raise ValueError("mfa_ttl must be positive and at most one hour")
        self._store = GarminAuthStore(instance_root)
        self._factory = sdk_factory
        self._clock = clock
        self._monotonic = monotonic
        self._ttl = mfa_ttl
        self._operation = threading.Lock()
        self._flow: _Flow | None = None

    @contextmanager
    def _guard(self) -> Iterator[None]:
        if not self._operation.acquire(blocking=False):
            raise GarminAuthError(ErrorCode.RUN_BUSY, "operation_in_progress")
        try:
            yield
        finally:
            self._operation.release()

    def _clear_flow(self) -> None:
        if self._flow is not None:
            self._flow.sdk.close()
            self._flow = None

    def _expire(self) -> None:
        if self._flow is not None and self._monotonic() >= self._flow.deadline:
            self._clear_flow()

    @_public
    def begin_login(self, username: str, password: str, *, is_cn: bool) -> ErrorEnvelope:
        if not isinstance(username, str) or not username.strip() or not isinstance(password, str) or not password or type(is_cn) is not bool:
            raise GarminAuthError(ErrorCode.INVALID_ARGUMENT, "credentials_required")
        with self._guard(), self._store.locked():
            check_environment()
            self._expire()
            if self._flow is not None:
                raise GarminAuthError(ErrorCode.RUN_BUSY, "login_pending")
            snapshot = self._store.snapshot()
            sdk = self._factory(is_cn=is_cn)
            try:
                if sdk.begin(username, password):
                    self._require_fresh(sdk, ensure_utc(self._clock()))
                    self._store.commit(sdk, snapshot.revision, self._factory)
                    return self._authenticated(sdk)
                now = ensure_utc(self._clock())
                flow = _Flow(secrets.token_urlsafe(32), sdk, snapshot.revision,
                             self._monotonic() + self._ttl, now + timedelta(seconds=self._ttl))
                self._flow = flow
                return success_envelope({"state": "needs_mfa", "flow_id": flow.flow_id,
                                         "expires_at_utc": format_utc(flow.expires)})
            finally:
                if self._flow is None or self._flow.sdk is not sdk:
                    sdk.close()

    @_public
    def submit_mfa(self, flow_id: str, code: str) -> ErrorEnvelope:
        with self._guard():
            flow = self._flow
            if flow is None or not isinstance(flow_id, str) or not secrets.compare_digest(flow.flow_id, flow_id):
                raise GarminAuthError(ErrorCode.INVALID_ARGUMENT, "unknown_flow")
            if self._monotonic() >= flow.deadline:
                self._clear_flow()
                raise GarminAuthError(ErrorCode.TIMEOUT, "mfa_expired")
            if not isinstance(code, str) or not code.strip():
                raise GarminAuthError(ErrorCode.INVALID_ARGUMENT, "mfa_code_required")
            with self._store.locked():
                try:
                    if self._store.snapshot().revision != flow.revision:
                        raise GarminAuthError(ErrorCode.SOURCE_CONFLICT, "auth_generation_changed")
                    flow.sdk.submit(code)
                    self._require_fresh(flow.sdk, ensure_utc(self._clock()))
                    self._store.commit(flow.sdk, flow.revision, self._factory)
                    return self._authenticated(flow.sdk)
                finally:
                    self._clear_flow()

    @_public
    def cancel_login(self, flow_id: str) -> ErrorEnvelope:
        with self._guard():
            if self._flow is not None and self._flow.flow_id == flow_id:
                self._clear_flow()
            return success_envelope({"state": "cancelled"})

    def close(self) -> None:
        with self._guard():
            self._clear_flow()

    def status(self) -> ErrorEnvelope:
        return self.observe_status().result

    def observe_status(self) -> AuthObservation:
        try:
            with self._guard(), self._store.locked():
                self._expire()
                snapshot = self._store.snapshot()
                if self._flow is not None and self._flow.revision != snapshot.revision:
                    self._clear_flow()
                flow_id = self._flow.flow_id if self._flow is not None else None
                try:
                    sdk = self._store.load(snapshot, self._factory)
                except GarminAuthError as exc:
                    if exc.code != ErrorCode.AUTH_REFRESH_REQUIRED:
                        raise
                    result = success_envelope({"state": "manual_required", "saved": False,
                        "region": None, "server_verified": False, "manual_required": True,
                        "reason": exc.reason, "expires_at_utc": None, "next_check_at_utc": None})
                else:
                    try:
                        expires, maintain = sdk.times()
                        result = success_envelope({"state": "stored", "saved": True,
                            "region": "cn" if sdk.is_cn else "com",
                            "server_verified": False, "manual_required": False,
                            "migration_required": snapshot.config.get("version") != 1,
                            "expires_at_utc": format_utc(expires), "next_check_at_utc": format_utc(maintain)})
                    finally:
                        sdk.close()
                return AuthObservation(result, snapshot.revision, flow_id)
        except GarminAuthError as exc:
            result = exc.envelope()
        except (ValueError, TypeError, OverflowError):
            result = GarminAuthError(ErrorCode.DATA_INVALID, "invalid_input").envelope()
        except OSError:
            result = GarminAuthError(ErrorCode.EXTERNAL_SERVICE_FAILED, "auth_storage_failed").envelope()
        return AuthObservation(result, None, None)

    @_public
    def maintain_once(self, *, now_utc: datetime) -> ErrorEnvelope:
        now = ensure_utc(now_utc)
        with self._guard(), self._store.locked():
            self._expire()
            snapshot = self._store.snapshot()
            sdk = self._store.load(snapshot, self._factory)
            try:
                _, due = sdk.times()
                refreshed = now >= due
                if refreshed:
                    sdk.refresh()
                    self._require_fresh(sdk, now)
                if refreshed or snapshot.config.get("version") != 1:
                    self._store.commit(sdk, snapshot.revision, self._factory)
                expires, due = sdk.times()
                return success_envelope({"state": "refreshed" if refreshed else "unchanged",
                    "expires_at_utc": format_utc(expires), "next_check_at_utc": format_utc(due)})
            finally:
                sdk.close()

    def _require_fresh(self, sdk: GarminSDK, now: datetime) -> None:
        expires, due = sdk.times()
        if expires <= now or due <= now:
            raise GarminAuthError(ErrorCode.AUTH_REFRESH_REQUIRED, "new_token_already_due")

    def _authenticated(self, sdk: GarminSDK) -> ErrorEnvelope:
        expires, due = sdk.times()
        return success_envelope({"state": "authenticated", "saved": True,
            "expires_at_utc": format_utc(expires), "next_check_at_utc": format_utc(due)})

    @contextmanager
    def _session(self) -> Iterator[_AuthLease]:
        with self._guard(), self._store.locked():
            self._expire()
            snapshot = self._store.snapshot()
            sdk = self._store.load(snapshot, self._factory)
            try:
                if snapshot.config.get("version") != 1:
                    self._store.commit(sdk, snapshot.revision, self._factory)
                    snapshot = self._store.snapshot()
                yield _AuthLease(self, sdk, snapshot)
            finally:
                sdk.close()


class _AuthLease:
    def __init__(self, owner: GarminAuthService, sdk: GarminSDK, snapshot: AuthSnapshot) -> None:
        self._owner = owner
        self._sdk = sdk
        self._revision = snapshot.revision

    def call(self, operation: str, *args: str) -> Any:
        before = self._sdk.fingerprint()
        try:
            return self._sdk.data_call(operation, *args)
        finally:
            after = self._sdk.fingerprint()
            if after != before:
                self._owner._require_fresh(self._sdk, ensure_utc(self._owner._clock()))
                self._revision = self._owner._store.commit(self._sdk, self._revision, self._owner._factory)
