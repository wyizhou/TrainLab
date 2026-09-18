from __future__ import annotations

import hashlib
import importlib
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any

from trainlab.contracts.errors import ErrorCode
from trainlab.garmin_auth_types import GarminAuthError
from trainlab.garmin_privacy import private_garmin_logs

_CONSUMER_LOCK = threading.Lock()
_TIMEOUT = 15


def check_environment() -> None:
    if any(name in os.environ for name in ("GARTH_HOME", "GARTH_TOKEN", "GARMINTOKENS")) or os.environ.get("GARTH_TELEMETRY", "").lower() == "true":
        raise GarminAuthError(ErrorCode.CONFIG_UNAVAILABLE, "sdk_environment_conflict")


def external_error(exc: Exception, *, mfa: bool = False) -> GarminAuthError:
    chain: list[BaseException] = [exc]
    seen: set[int] = set()
    names: set[str] = set()
    statuses: set[int] = set()
    while chain:
        item = chain.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        names.update(cls.__name__ for cls in type(item).__mro__)
        status = getattr(getattr(item, "response", None), "status_code", None)
        if isinstance(status, int):
            statuses.add(status)
        for nested in (item.__cause__, item.__context__, getattr(item, "error", None)):
            if isinstance(nested, BaseException):
                chain.append(nested)
    if statuses & {401, 403}:
        return GarminAuthError(ErrorCode.AUTH_REFRESH_REQUIRED, "server_auth_required")
    if 429 in statuses:
        return GarminAuthError(ErrorCode.RESOURCE_LIMIT, "server_rate_limited")
    if names & {"Timeout", "TimeoutError"}:
        return GarminAuthError(ErrorCode.TIMEOUT, "sdk_timeout")
    if "GarminConnectAuthenticationError" in names and not statuses:
        return GarminAuthError(ErrorCode.AUTH_REFRESH_REQUIRED, "authentication_incomplete")
    if "GarminConnectTooManyRequestsError" in names:
        return GarminAuthError(ErrorCode.RESOURCE_LIMIT, "server_rate_limited")
    if mfa and "GarthException" in names and not statuses:
        return GarminAuthError(ErrorCode.AUTH_REFRESH_REQUIRED, "mfa_verification_incomplete")
    return GarminAuthError(ErrorCode.EXTERNAL_SERVICE_FAILED, "sdk_request_failed")


@contextmanager
def sdk_boundary(*, local: bool = False, mfa: bool = False) -> Iterator[None]:
    check_environment()
    try:
        with private_garmin_logs():
            yield
    except GarminAuthError:
        raise
    except ImportError:
        raise GarminAuthError(ErrorCode.CONFIG_UNAVAILABLE, "sdk_dependency_unavailable") from None
    except Exception as exc:  # noqa: BLE001
        if local:
            raise GarminAuthError(ErrorCode.DATA_INVALID, "token_format_invalid") from None
        raise external_error(exc, mfa=mfa) from None


class GarminSDK:
    def __init__(self, *, is_cn: bool) -> None:
        with sdk_boundary():
            if version("garminconnect") != "0.2.40" or version("garth") != "0.6.3":
                raise GarminAuthError(ErrorCode.CONFIG_UNAVAILABLE, "unsupported_sdk_version")
            self._module = importlib.import_module("garminconnect")
            self._tokens = importlib.import_module("garth.auth_tokens")
            self._sso: Any = importlib.import_module("garth.sso")
            self._client = self._module.Garmin(is_cn=is_cn, return_on_mfa=True)
            self._client.garth.configure(timeout=_TIMEOUT, retries=0, telemetry_enabled=False)
        self.is_cn = is_cn
        self._mfa: dict[str, Any] | None = None

    def _consumer(self) -> None:
        with _CONSUMER_LOCK:
            if not self._sso.OAUTH_CONSUMER:
                requests = importlib.import_module("requests")
                parent = self._client.garth.sess
                response = requests.get(
                    self._sso.OAUTH_CONSUMER_URL, timeout=_TIMEOUT,
                    proxies=parent.proxies, verify=parent.verify,
                )
                try:
                    response.raise_for_status()
                    value = response.json()
                finally:
                    response.close()
                if not isinstance(value, dict) or any(
                    not isinstance(value.get(key), str) or not value[key]
                    for key in ("consumer_key", "consumer_secret")
                ):
                    raise GarminAuthError(ErrorCode.DATA_INVALID, "consumer_config_invalid")
                self._sso.OAUTH_CONSUMER = value

    def begin(self, username: str, password: str) -> bool:
        with sdk_boundary():
            self._consumer()
            self._client.username, self._client.password = username, password
            try:
                result = self._client.login()
            finally:
                self._client.username = self._client.password = None
                self._forget_request()
            if not isinstance(result, tuple) or len(result) != 2:
                raise GarminAuthError(ErrorCode.DATA_INVALID, "login_result_invalid")
            if result[0] == "needs_mfa" and isinstance(result[1], dict):
                if result[1].get("client") is not self._client.garth or not isinstance(result[1].get("signin_params"), dict):
                    raise GarminAuthError(ErrorCode.DATA_INVALID, "login_result_invalid")
                self._mfa = result[1]
                return False
            if not isinstance(result[0], self._tokens.OAuth1Token) or not isinstance(result[1], self._tokens.OAuth2Token):
                raise GarminAuthError(ErrorCode.DATA_INVALID, "login_result_invalid")
            self._validate()
            return True

    def submit(self, code: str) -> None:
        with sdk_boundary(mfa=True):
            if self._mfa is None:
                raise GarminAuthError(ErrorCode.INVALID_ARGUMENT, "unknown_flow")
            try:
                self._client.resume_login(self._mfa, code)
                self._validate()
            finally:
                self._mfa = None
                self._forget_request()

    def _forget_request(self) -> None:
        response = getattr(self._client.garth, "last_resp", None)
        if response is not None:
            response.request = None
            response.history.clear()

    def _validate(self) -> None:
        one, two = self._client.garth.oauth1_token, self._client.garth.oauth2_token
        if not isinstance(one, self._tokens.OAuth1Token) or not isinstance(two, self._tokens.OAuth2Token):
            raise GarminAuthError(ErrorCode.DATA_INVALID, "token_pair_invalid")
        if not one.oauth_token or not one.oauth_token_secret or not two.access_token or not two.refresh_token:
            raise GarminAuthError(ErrorCode.DATA_INVALID, "token_pair_incomplete")
        if one.domain != ("garmin.cn" if self.is_cn else "garmin.com"):
            raise GarminAuthError(ErrorCode.DATA_INVALID, "token_region_mismatch")
        if type(two.expires_in) is not int or two.expires_in <= 0 or type(two.expires_at) is not int or two.expires_at <= 0:
            raise GarminAuthError(ErrorCode.DATA_INVALID, "expiry_unavailable")
        datetime.fromtimestamp(two.expires_at, UTC)

    def times(self) -> tuple[datetime, datetime]:
        with sdk_boundary(local=True):
            self._validate()
            token = self._client.garth.oauth2_token
            expires = datetime.fromtimestamp(token.expires_at, UTC)
            return expires, expires - timedelta(seconds=min(300, max(1, token.expires_in * 0.1)))

    def fingerprint(self) -> str:
        with sdk_boundary(local=True):
            self._validate()
            return hashlib.sha256(self._client.garth.dumps().encode()).hexdigest()

    def load(self, directory: Path) -> None:
        with sdk_boundary(local=True):
            self._client.garth.load(str(directory))
            self._validate()

    def loads(self, encoded: str) -> None:
        with sdk_boundary(local=True):
            self._client.garth.loads(encoded)
            self._validate()

    def dump(self, directory: Path) -> None:
        with sdk_boundary(local=True):
            self._validate()
            self._client.garth.dump(str(directory))

    def refresh(self) -> None:
        with sdk_boundary():
            self._consumer()
            self._client.garth.refresh_oauth2()
            self._validate()

    def data_call(self, operation: str, *args: str) -> Any:
        with sdk_boundary():
            self._validate()
            if self._client.garth.oauth2_token.expired:
                self._consumer()
            if operation == "list":
                return self._client.get_activities_by_date(*args)
            if operation == "download":
                return self._client.download_activity(args[0], self._module.Garmin.ActivityDownloadFormat.ORIGINAL)
            raise GarminAuthError(ErrorCode.INVALID_ARGUMENT, "unknown_operation")

    def close(self) -> None:
        self._mfa = None
        self._client.username = self._client.password = None
        self._client.garth.oauth1_token = self._client.garth.oauth2_token = None
        self._client.garth.last_resp = None
        self._client.garth.sess.cookies.clear()
        self._client.garth.sess.close()


SDKFactory = Callable[..., GarminSDK]
