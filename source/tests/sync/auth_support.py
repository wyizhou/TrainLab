from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from tests.fit.fit_bytes import activity_data, frame
from tests.sync.test_garmin_sync import zip_payload

SECRET = "synthetic-au32-token-canary"
PASSWORD = "synthetic-au32-password-canary"
CODE = "987123"


class OfflineGarmin:
    def __init__(self, *, mfa: bool = False) -> None:
        self.mfa = mfa
        self.calls: list[str] = []
        self.exchange_count = 0
        self.failure_path = ""
        self.failure_status = 503
        self.bad_mfa = False
        self.expiry = 3600
        self.fit = frame(activity_data(start=1263000000))

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        url = str(request.url)
        path = urlparse(url).path
        self.calls.append(path)
        assert kwargs.get("timeout") == 15
        status = 200
        data: Any
        if self.failure_path and self.failure_path in url:
            status, data = self.failure_status, {"error": SECRET}
        elif "oauth_consumer.json" in url:
            data = {"consumer_key": "synthetic-consumer", "consumer_secret": SECRET}
        elif path == "/sso/embed":
            data = b'<title>Embed</title>'
        elif "/sso/signin" in url and request.method == "GET":
            data = b'<title>Sign In</title><input name="_csrf" value="synthetic-csrf">'
        elif "/sso/signin" in url:
            if self.mfa:
                data = b'<title>MFA</title><input name="_csrf" value="synthetic-csrf">'
            else:
                data = b'<title>Success</title><a href="embed?ticket=synthetic-ticket">'
        elif "/verifyMFA/" in url:
            data = b'<title>MFA</title>' if self.bad_mfa else b'<a href="embed?ticket=synthetic-ticket">'
        elif "/preauthorized" in url:
            data = f"oauth_token={SECRET}&oauth_token_secret={SECRET}".encode()
        elif "/exchange/user/2.0" in url:
            self.exchange_count += 1
            assert "OAuth" in str(request.headers.get("Authorization", ""))
            data = oauth_values()[1]
            data.pop("expires_at")
            data.pop("refresh_token_expires_at")
            data["expires_in"] = self.expiry
            data["access_token"] = SECRET + str(self.exchange_count)
        elif "user-settings" in url:
            data = {"userData": {"measurementSystem": "metric"}}
        elif "userprofile-service" in url:
            data = {"displayName": "synthetic", "fullName": "synthetic", "userName": "synthetic"}
        elif "activitylist-service" in url:
            params = parse_qs(urlparse(url).query)
            data = [{"activityId": 101, "startTimeGMT": "2030-01-07 12:00:00"}] if params["start"] == ["0"] else []
        elif "download-service" in url:
            data = zip_payload({"activity.FIT": self.fit})
        else:
            raise AssertionError("Unexpected offline SDK path")
        response = requests.Response()
        response.status_code = status
        response.url = url
        response.reason = SECRET if status != 200 else "OK"
        response.request = request
        response._content = data if isinstance(data, bytes) else json.dumps(data).encode()
        response._content_consumed = True
        return response


def oauth_values(*, expires_at: int | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    expiry = int(time.time()) + 3600 if expires_at is None else expires_at
    return ({"oauth_token": SECRET, "oauth_token_secret": SECRET, "domain": "garmin.com"}, {
        "scope": "", "jti": "", "token_type": "Bearer", "access_token": SECRET,
        "refresh_token": SECRET, "expires_in": 3600, "expires_at": expiry,
        "refresh_token_expires_in": 7200, "refresh_token_expires_at": expiry + 3600,
    })


def legacy_tokens(root: Path, *, expires_at: int | None = None) -> Path:
    directory = root / "old-tokens"
    directory.mkdir(parents=True)
    for name, token in zip(("oauth1", "oauth2"), oauth_values(expires_at=expires_at), strict=True):
        (directory / f"{name}_token.json").write_text(json.dumps(token))
    return directory
