"""Pinned python-garminconnect adapter and credential/token boundary.

No credential is read from SQLite or logs.  Tests monkeypatch ``Garmin`` and
exercise this adapter without contacting Garmin Connect.
"""
from __future__ import annotations

import hashlib
import os
import socket
from pathlib import Path
from typing import Any, Callable

from .garmin import GarminError, ProductionBudgetGuard
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
    def fingerprint(self) -> tuple[tuple[str, int, int, str], ...]:
        self.verify()
        rows = []
        for path in sorted(self.directory.rglob("*")):
            if path.is_file():
                info = path.stat()
                rows.append(
                    (
                        str(path.relative_to(self.directory)),
                        info.st_mode & 0o777,
                        info.st_size,
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                )
        return tuple(rows)


class GarminConnectTransport:
    _MFA_FLOW_PATH = {"ios": "mobile", "portal": "portal", "widget": "portal"}
    _MFA_METHODS = frozenset({"email", "phone"})

    def __init__(
        self,
        email: str | None,
        password: str | None,
        token_store: TokenStore,
        *,
        region: str = "cn",
        mfa: Callable[[str], str] | None = None,
        client: Any = None,
        request_timeout_seconds: int = 30,
        budget_guard: ProductionBudgetGuard | None = None,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("invalid_request_timeout")
        if region not in {"global", "cn"}:
            raise ValueError("invalid_garmin_region")
        self.request_timeout_seconds = request_timeout_seconds
        self.region = region
        self._mfa_callback = mfa
        self._auth_flow_error: GarminError | None = None
        self.budget_guard = budget_guard
        token_store.prepare(); self.token_store = token_store
        if client is not None: self.client = client
        elif Garmin is None: raise GarminError("garminconnect_not_installed")
        else:
            # python-garminconnect 0.3.6 accepts these documented concepts;
            # retry_attempts=0 makes Layer 2 the only retry owner.
            self.client = Garmin(
                email,
                password,
                is_cn=(region == "cn"),
                prompt_mfa=self._prompt_mfa if mfa is not None else None,
                retry_attempts=0,
            )
        self._apply_request_timeout()
        self._apply_provider_budget()

    def _abort_mfa(self, error: GarminError) -> None:
        """Preserve one safe error across the provider facade's exception wrapping."""
        self._auth_flow_error = error
        raise error

    def _prompt_mfa(self) -> str:
        """Request delivery after MFA_REQUIRED, then ask for the received code.

        ``python-garminconnect==0.3.6`` invokes this callback only after its
        low-level client has stored the MFA session returned by Garmin.  The
        pinned library verifies codes but does not call Garmin's sendCode
        endpoint, so TrainLab completes that missing state transition here.
        """
        provider = getattr(self.client, "client", None)
        flow = str(getattr(provider, "_mfa_flow", "")).strip().lower()
        flow_path = self._MFA_FLOW_PATH.get(flow)
        method = str(getattr(provider, "_mfa_method", "email") or "email").strip().lower()
        session = getattr(provider, "_mfa_session", None)
        params = getattr(provider, "_mfa_login_params", None)
        headers = getattr(provider, "_mfa_post_headers", None)
        if (
            flow_path is None
            or method not in self._MFA_METHODS
            or session is None
            or not callable(getattr(session, "post", None))
            or not isinstance(params, dict)
            or not isinstance(headers, dict)
        ):
            self._abort_mfa(GarminError("mfa_code_delivery_unsupported"))

        domain = "garmin.cn" if self.region == "cn" else "garmin.com"
        endpoint = f"https://sso.{domain}/{flow_path}/api/mfa/sendCode"
        try:
            response = session.post(
                endpoint,
                params=params,
                headers=headers,
                json={"mfaMethod": method},
                timeout=self.request_timeout_seconds,
            )
        except Exception:
            self._abort_mfa(GarminError("mfa_code_delivery_failed"))

        status = getattr(response, "status_code", None)
        response_headers = getattr(response, "headers", {}) or {}
        retry_after = response_headers.get("Retry-After")
        try:
            retry_after = int(retry_after) if retry_after is not None else None
        except (TypeError, ValueError):
            retry_after = None
        if status == 429:
            self._abort_mfa(
                GarminError(
                    "mfa_code_delivery_rate_limited",
                    http_status=429,
                    retry_after=retry_after,
                )
            )
        if not isinstance(status, int) or not 200 <= status < 300:
            self._abort_mfa(
                GarminError("mfa_code_delivery_failed", http_status=status)
            )
        try:
            response_type = response.json()["responseStatus"]["type"]
        except (AttributeError, KeyError, TypeError, ValueError):
            self._abort_mfa(GarminError("mfa_code_delivery_failed"))
        if response_type != "MFA_CODE_SENT":
            self._abort_mfa(GarminError("mfa_code_delivery_failed"))
        if self._mfa_callback is None:
            self._abort_mfa(GarminError("mfa_prompt_not_configured"))
        return self._mfa_callback(method)

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
    def _apply_provider_budget(self) -> None:
        guard = self.budget_guard
        if guard is None:
            return
        inner = getattr(self.client, "client", None)
        request_owner = inner if inner is not None else self.client
        for name in ("cs", "_api_session"):
            session = getattr(request_owner, name, None)
            request = getattr(session, "request", None)
            if not callable(request):
                raise GarminError("unsupported_garmin_client_structure")
            def guarded_request(*args: Any, __request: Callable[..., Any] = request, **kwargs: Any) -> Any:
                guard.before_provider_entry()
                return __request(*args, **kwargs)
            setattr(session, "request", guarded_request)
    def login(self) -> None:
        self._auth_flow_error = None
        try:
            self.client.login(str(self.token_store.directory))
            self.token_store.verify()
        except Exception as exc:
            if self._auth_flow_error is not None:
                error, self._auth_flow_error = self._auth_flow_error, None
                raise error
            if isinstance(exc, GarminError):
                raise
            raise self._error(exc)
    def login_cached_only(self) -> None:
        """Load existing tokens while making every refresh/write path fail closed."""
        if self.budget_guard is None or not self.budget_guard.spec.cached_tokens_only:
            raise GarminError("cached_token_unusable")
        before = self.token_store.fingerprint()
        inner = getattr(self.client, "client", None)
        if inner is None:
            raise GarminError("unsupported_garmin_client_structure")
        loader = getattr(inner, "load", None)
        expires_soon = getattr(inner, "_token_expires_soon", None)
        profile_loader = getattr(self.client, "_load_profile_and_settings", None)
        if not callable(loader) or not callable(expires_soon) or not callable(profile_loader):
            raise GarminError("unsupported_garmin_client_structure")
        def refresh_forbidden(*_args: Any, **_kwargs: Any) -> None:
            raise GarminError("cached_token_refresh_forbidden")
        def token_write_forbidden(*_args: Any, **_kwargs: Any) -> None:
            raise GarminError("token_store_mutation_forbidden")
        try:
            loader(str(self.token_store.directory))
            inner._tokenstore_path = None
            inner._refresh_session = refresh_forbidden
            inner.dump = token_write_forbidden
            if expires_soon():
                raise GarminError("cached_token_refresh_forbidden")
            profile_loader()
            if self.token_store.fingerprint() != before:
                raise GarminError("token_store_mutation_forbidden")
        except GarminError:
            raise
        except Exception as exc:
            if self.token_store.fingerprint() != before:
                raise GarminError("token_store_mutation_forbidden") from None
            raise GarminError("cached_token_unusable", http_status=getattr(exc, "status_code", None)) from None
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
        if spec.resource_kind == "race_predictions":
            # garminconnect 0.3.6 accepts either no arguments (latest) or the
            # complete three-argument range form.  Passing only the two dates
            # raises ValueError before a provider request is made.
            return self._invoke(method, start_local_date, end_local_date, _type="daily")
        if spec.resource_kind == "endurance_score" and start_local_date == end_local_date:
            # The pinned client treats a one-argument call as a precise daily
            # observation; its two-argument form is weekly aggregation.
            return self._invoke(method, start_local_date)
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
