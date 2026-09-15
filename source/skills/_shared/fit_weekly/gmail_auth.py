"""Existing dedicated OAuth tokens; one normal refresh, no interactive login."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import email_config, gmail_message, gmail_scopes, storage

SCOPES = gmail_scopes.SCOPES
TOKEN_URI = "https://oauth2.googleapis.com/token"


def replace_token(path: Path, data: bytes) -> None:
    storage.private_entry(path.parent, directory=True)
    storage.private_entry(path, nonempty=True)
    old = path.read_bytes()
    fd, temporary = tempfile.mkstemp(prefix=".oauth-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        storage.sync_dir(path.parent)
        storage.private_entry(path, nonempty=True)
        if path.read_bytes() != data:
            raise ValueError("persist")
    except BaseException as exc:
        if not path.exists() or path.read_bytes() != old:
            # Inspect the actual target: an interrupt can land after rename
            # succeeds but before Python records that it returned.
            recovery_fd, recovery = tempfile.mkstemp(
                prefix=".oauth-restore-", dir=path.parent
            )
            try:
                with os.fdopen(recovery_fd, "wb") as stream:
                    stream.write(old)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(recovery, path)
                storage.sync_dir(path.parent)
            finally:
                if os.path.exists(recovery):
                    os.unlink(recovery)
        if not isinstance(exc, Exception):
            raise
        raise ValueError("gmail_token_refresh_persist_failed") from None
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Auth:
    def __init__(self, token_file: Path, account: str, *, session: Any = None):
        email_config.outside_repository(token_file)
        self.account = gmail_message.address(account)
        self.token_file = token_file
        storage.private_entry(token_file.parent, directory=True)
        storage.private_entry(token_file, nonempty=True)
        try:
            self._token = json.loads(token_file.read_bytes())
            if (
                not isinstance(self._token, dict)
                or not gmail_scopes.valid(self._token.get("scopes"), labels=False)
                or self._token.get("token_uri", TOKEN_URI) != TOKEN_URI
                or any(
                    not isinstance(self._token.get(k), str) or not self._token[k]
                    for k in ("client_id", "client_secret", "refresh_token")
                )
            ):
                raise ValueError("token")
        except Exception:
            raise ValueError("gmail_auth_invalid") from None
        if session is None:
            import requests

            session = requests.Session()
        self._session = session
        self._failed = False
        self._reauthorization_required = False

    def require_labels(self) -> None:
        if not gmail_scopes.valid(self._token["scopes"], labels=True):
            raise ValueError("gmail_label_scope_requires_reauthorization")

    def headers(
        self, timeout: float = 30, before_refresh: Any = None
    ) -> dict[str, str]:
        if self._failed:
            raise ValueError("gmail_auth_failed")
        try:
            expiry = datetime.fromisoformat(
                self._token.get("expiry", "1970-01-01T00:00:00Z").replace("Z", "+00:00")
            )
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if not self._token.get("token") or expiry <= datetime.now(
                timezone.utc
            ) + timedelta(seconds=30):
                if before_refresh is None:
                    raise ValueError("gmail_refresh_authorization_required")
                before_refresh()
                response = self._session.request(
                    "POST",
                    TOKEN_URI,
                    data={
                        "grant_type": "refresh_token",
                        **{
                            k: self._token[k]
                            for k in ("client_id", "client_secret", "refresh_token")
                        },
                    },
                    timeout=timeout,
                    allow_redirects=False,
                )
                value = response.json()
                if (
                    response.status_code in (400, 401, 403)
                    and isinstance(value, dict)
                    and value.get("error")
                    in ("invalid_grant", "invalid_client", "unauthorized_client")
                ):
                    self._reauthorization_required = True
                if (
                    response.status_code != 200
                    or not isinstance(value.get("access_token"), str)
                    or not value["access_token"]
                    or type(value.get("expires_in")) is not int
                    or value["expires_in"] <= 0
                    or value.get("token_type", "Bearer").lower() != "bearer"
                    or (
                        "scope" in value
                        and set(value["scope"].split()) != set(self._token["scopes"])
                    )
                ):
                    raise ValueError("refresh")
                refreshed = {
                    **self._token,
                    "token": value["access_token"],
                    "expiry": (
                        datetime.now(timezone.utc)
                        + timedelta(seconds=value["expires_in"])
                    ).isoformat(),
                }
                if "refresh_token" in value:
                    if (
                        not isinstance(value["refresh_token"], str)
                        or not value["refresh_token"]
                    ):
                        raise ValueError("refresh_token")
                    refreshed["refresh_token"] = value["refresh_token"]
                replace_token(self.token_file, storage.canonical(refreshed).encode())
                self._token = refreshed
            token = self._token["token"]
            if not isinstance(token, str) or any(c in token for c in "\r\n"):
                raise ValueError("token")
            return {"Authorization": "Bearer " + token}
        except BaseException as exc:
            self._failed = True
            if not isinstance(exc, Exception):
                raise
            raise ValueError("gmail_auth_or_refresh_failed") from None
