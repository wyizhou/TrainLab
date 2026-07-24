"""Pinned python-garminconnect adapter and credential/token boundary.

No credential is read from SQLite or logs.  Tests monkeypatch ``Garmin`` and
exercise this adapter without contacting Garmin Connect.
"""
from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any, Callable

from .garmin import GarminError
from .garmin_catalog import RESOURCE_CATALOG, health_call_arguments

try:  # Imported lazily in practice; package installation is deployment-owned.
    from garminconnect import Garmin  # type: ignore
except ImportError:  # pragma: no cover - exercised through monkeypatch
    Garmin = None  # type: ignore


class TokenStore:
    def __init__(self, directory: Path) -> None: self.directory = directory
    def prepare(self) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        for path in [self.directory, *self.directory.rglob("*")]:
            if path.is_symlink(): raise ValueError("token_store_symlink_rejected")
            if path.is_dir(): os.chmod(path, 0o700)
            elif path.is_file(): os.chmod(path, 0o600)
        return self.directory
    def verify(self) -> None:
        if self.directory.is_symlink() or self.directory.stat().st_mode & 0o777 != 0o700: raise ValueError("unsafe_token_directory")
        for path in self.directory.rglob("*"):
            if path.is_symlink(): raise ValueError("token_store_symlink_rejected")
            if path.is_dir() and path.stat().st_mode & 0o777 != 0o700: raise ValueError("unsafe_token_directory")
            if path.is_file() and path.stat().st_mode & 0o777 != 0o600: raise ValueError("unsafe_token_file")


class GarminConnectTransport:
    def __init__(self, email: str | None, password: str | None, token_store: TokenStore, *, region: str = "global", mfa: Callable[[], str] | None = None, client: Any = None, request_timeout_seconds: int = 30) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("invalid_request_timeout")
        self.request_timeout_seconds = request_timeout_seconds
        token_store.prepare(); self.token_store = token_store
        if client is not None: self.client = client
        elif Garmin is None: raise GarminError("garminconnect_not_installed")
        else:
            # python-garminconnect 0.3.6 accepts these documented concepts;
            # retry_attempts=0 makes Layer 2 the only retry owner.
            self.client = Garmin(email, password, is_cn=(region == "cn"), prompt_mfa=mfa, retry_attempts=0)
        self._apply_request_timeout()

    def _apply_request_timeout(self) -> None:
        """Force the configured timeout through 0.3.6's real Session calls.

        In 0.3.6, all normal API/download requests flow through
        ``Client._api_session.request`` and authentication calls use ``cs``.
        Wrapping each Session's instance ``request`` is synchronous, adds no
        worker/thread, and also covers provider methods that bypass
        ``connectapi``.  The marker prevents accidental wrapper stacking.
        """
        # ``Garmin`` is the public 0.3.6 facade.  Its actual HTTP client is
        # exactly one explicit hop below at ``Garmin.client``.  Tests may pass
        # that low-level Client directly, but no other object shape is probed.
        inner = getattr(self.client, "client", None)
        request_owner = inner if inner is not None else self.client
        sessions: list[tuple[str, Any]] = []
        for name in ("cs", "_api_session"):
            session = getattr(request_owner, name, None)
            request = getattr(session, "request", None)
            if not callable(request):
                raise GarminError("unsupported_garmin_client_structure")
            sessions.append((name, session))
        for _name, session in sessions:
            request = session.request
            if getattr(request, "_trainlab_timeout_seconds", None) == self.request_timeout_seconds:
                continue
            def bounded_request(*args: Any, __request: Callable[..., Any] = request, **kwargs: Any) -> Any:
                kwargs["timeout"] = self.request_timeout_seconds
                return __request(*args, **kwargs)
            setattr(bounded_request, "_trainlab_timeout_seconds", self.request_timeout_seconds)
            setattr(session, "request", bounded_request)
    def login(self) -> None:
        try: self.client.login(str(self.token_store.directory)); self.token_store.verify()
        except Exception as exc: raise self._error(exc)
    def identity(self) -> str:
        profile = self._invoke(getattr(self.client, "get_full_name"))
        return str(profile)
    def fetch_health(self, resource_kind: str, local_date: str) -> Any:
        spec = RESOURCE_CATALOG.get(resource_kind)
        if spec is None or not spec.requestable or spec.scope not in {"daily", "range", "account"}:
            raise GarminError("not_supported", http_status=404)
        method = getattr(self.client, spec.method or "", None)
        if method is None: raise GarminError("not_supported", http_status=404)
        try:
            args, kwargs = health_call_arguments(spec, local_date)
        except ValueError:
            raise GarminError("not_supported", http_status=404) from None
        return self._invoke(method, *args, **kwargs)
    def fetch_range(self, resource_kind: str, start_local_date: str, end_local_date: str) -> Any:
        spec = RESOURCE_CATALOG.get(resource_kind)
        if spec is None or not spec.requestable or spec.scope != "range":
            raise GarminError("not_supported", http_status=404)
        method = getattr(self.client, spec.method or "", None)
        if not callable(method):
            raise GarminError("not_supported", http_status=404)
        if spec.resource_kind == "lactate_threshold":
            return self._invoke(method, latest=False, start_date=start_local_date, end_date=end_local_date, aggregation="daily")
        if spec.resource_kind == "running_tolerance":
            return self._invoke(method, start_local_date, end_local_date, aggregation="weekly")
        return self._invoke(method, start_local_date, end_local_date)
    def fetch_account(self, resource_kind: str, provider_device_id: str | None = None) -> Any:
        """Call only a reviewed account endpoint from the versioned catalog."""
        spec = RESOURCE_CATALOG.get(resource_kind)
        if spec is None or not spec.requestable or spec.scope != "account":
            raise GarminError("not_supported", http_status=404)
        method = getattr(self.client, spec.method or "", None)
        if not callable(method):
            raise GarminError("not_supported", http_status=404)
        if spec.argument_shape == ("device_id",):
            if not provider_device_id:
                raise GarminError("not_available", http_status=404)
            return self._invoke(method, provider_device_id)
        if spec.argument_shape:
            raise GarminError("not_supported", http_status=404)
        if provider_device_id is not None:
            raise GarminError("not_supported", http_status=404)
        return self._invoke(method)
    def activity_count(self) -> int:
        return int(self._invoke(getattr(self.client, "count_activities")))
    def activity_page(self, offset: int, limit: int):
        return self._invoke(getattr(self.client, "get_activities"), offset, limit)
    def list_activities(self, start: str | None, through: str | None):
        if start is not None and through is not None:
            method = getattr(self.client, "get_activities_by_date", None)
            if not callable(method):
                raise GarminError("not_supported", http_status=404)
            return self._invoke(method, start, through, sortorder="asc")
        count = self.activity_count()
        pages = []
        for offset in range(0, count, 100):
            page = self.activity_page(offset, min(100, count - offset))
            pages.extend(page.get("activities", []) if isinstance(page, dict) else page)
        return pages
    def activity_summary(self, activity_id: str): return self._invoke(getattr(self.client, "get_activity"), activity_id)
    def activity_original(self, activity_id: str): return self._invoke(getattr(self.client, "download_activity"), activity_id, Garmin.ActivityDownloadFormat.ORIGINAL)
    def activity_extra(self, activity_id: str, role: str):
        mapping={"splits_json":"get_activity_splits","typed_splits_json":"get_activity_typed_splits","split_summaries_json":"get_activity_split_summaries","exercise_sets_json":"get_activity_exercise_sets","hr_zones_json":"get_activity_hr_in_timezones","power_zones_json":"get_activity_power_in_timezones","weather_json":"get_activity_weather","gear_json":"get_activity_gear","details_json_fallback":"get_activity_details"}
        method=getattr(self.client,mapping.get(role, ""),None)
        if not callable(method):
            raise GarminError("not_supported", http_status=404)
        if role == "details_json_fallback":
            return self._invoke(method, activity_id, maxchart=2000, maxpoly=4000)
        return self._invoke(method, activity_id)
    def _invoke(self, method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try: return method(*args, **kwargs)
        except Exception as exc: raise self._error(exc)
    @staticmethod
    def _error(exc: Exception) -> GarminError:
        status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
        headers = getattr(getattr(exc, "response", None), "headers", {}) or {}
        retry = headers.get("Retry-After")
        try: retry = int(retry) if retry is not None else None
        except (TypeError, ValueError): retry = None
        if isinstance(exc, (TimeoutError, socket.timeout)):
            code = "timeout"
        elif isinstance(exc, socket.gaierror):
            code = "dns"
        elif isinstance(exc, ConnectionResetError):
            code = "connection_reset"
        elif isinstance(exc, ConnectionError):
            code = "network"
        elif status is not None:
            code = f"http_{status}"
        else:
            code = "provider_error"
        return GarminError(code, http_status=status, retry_after=retry)
