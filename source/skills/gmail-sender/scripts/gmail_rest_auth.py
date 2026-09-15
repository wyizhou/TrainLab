#!/usr/bin/env python3
"""One-time owner-only Gmail REST installed-app authorization."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from gmail_rest_common import (  # noqa: E402
    API_ROOT,
    AUTH_RECEIPT_NAME,
    SCOPES,
    GmailRestError,
    atomic_json,
    atomic_write,
    fsync_directory,
    read_owner_json,
    read_recipient,
    require_owner_file,
    validate_schema,
)

SOURCE_ROOT = SCRIPT_ROOT.parents[2]
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _desktop_client_file(path: Path) -> Path:
    """Accept only an owner-only Google Desktop installed-app client."""

    client = require_owner_file(path)
    value = read_owner_json(client)
    if set(value) != {"installed"} or not isinstance(value["installed"], dict):
        raise GmailRestError("gmail_rest_oauth_client_not_desktop")
    installed = value["installed"]
    required_strings = ("client_id", "client_secret", "auth_uri", "token_uri")
    if any(
        not isinstance(installed.get(key), str) or not installed[key].strip()
        for key in required_strings
    ):
        raise GmailRestError("gmail_rest_oauth_client_not_desktop")
    if (
        installed["auth_uri"] != GOOGLE_AUTH_URI
        or installed["token_uri"] != GOOGLE_TOKEN_URI
    ):
        raise GmailRestError("gmail_rest_oauth_endpoint_invalid")
    redirect_uris = installed.get("redirect_uris")
    if (
        not isinstance(redirect_uris, list)
        or not redirect_uris
        or any(not isinstance(value, str) for value in redirect_uris)
        or not any(
            value.rstrip("/") in {"http://localhost", "http://127.0.0.1"}
            for value in redirect_uris
        )
    ):
        raise GmailRestError("gmail_rest_oauth_client_not_desktop")
    return client


def _refreshable_token_payload(credentials: Any) -> dict[str, Any] | None:
    """Return a runtime-reloadable authorized-user token, or fail closed."""

    try:
        value = json.loads(credentials.to_json())
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    for key in ("refresh_token", "client_id", "client_secret", "token_uri"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            return None
    scopes = value.get("scopes")
    from skills._shared.fit_weekly.gmail_scopes import valid

    if value.get("token_uri") != GOOGLE_TOKEN_URI or not valid(scopes, labels=True):
        return None
    try:
        from google.oauth2.credentials import Credentials

        reloaded = Credentials.from_authorized_user_info(value, list(SCOPES))
    except Exception:
        return None
    if not isinstance(reloaded.refresh_token, str) or not reloaded.refresh_token:
        return None
    return value


def _persist_receipt(path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    validate_schema(receipt, "gmail_rest_auth_receipt_v1")
    atomic_json(path, receipt)
    return receipt


def _profile_failure_receipt(
    *,
    receipt_file: Path,
    scopes_match: bool,
    short_lived: bool,
    provider_calls: int,
    error_code: str,
) -> dict[str, Any]:
    """Persist a redacted terminal receipt after the authorization flow."""

    return _persist_receipt(
        receipt_file,
        {
            "schema_version": "gmail_rest_auth_receipt_v1",
            "status": "blocked",
            "account_matches": False,
            "scopes_match": scopes_match,
            "refresh_token_available": True,
            "token_published": False,
            "short_lived_testing_token": short_lived,
            "provider_calls": provider_calls,
            "completed_at_utc": utc_now(),
            "error_code": error_code,
        },
    )


def authorize(
    *,
    instance_root: Path,
    client_file: Path,
    email_file: Path,
    token_file: Path,
    receipt_file: Path,
    flow_factory: Callable[..., Any] | None = None,
    session_factory: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    """Authorize, verify the account/scopes, then atomically publish the token."""

    from skills._shared.fit_weekly import email_config, run_config, storage

    try:
        instance_root = run_config.instance_path(instance_root)
        storage.private_entry(instance_root, directory=True)
        client_file = run_config.private_path(instance_root, str(client_file))
        email_file = run_config.private_path(instance_root, str(email_file))
        token_file = run_config.instance_path(
            token_file if token_file.is_absolute() else instance_root / token_file
        )
        receipt_file = run_config.instance_path(
            receipt_file if receipt_file.is_absolute() else instance_root / receipt_file
        )
        for path in (token_file, client_file, receipt_file):
            email_config.outside_repository(path)
            storage.private_entry(path.parent, directory=True)
        if len({client_file, email_file, token_file, receipt_file}) != 4:
            raise ValueError("overlap")
    except (ValueError, OSError):
        raise GmailRestError("gmail_rest_auth_path_invalid") from None
    if receipt_file != token_file.with_name(AUTH_RECEIPT_NAME):
        raise GmailRestError("gmail_rest_auth_receipt_path_invalid")
    client = _desktop_client_file(client_file)
    recipient, _recipient_sha = read_recipient(email_file)
    if token_file.exists() or token_file.is_symlink():
        require_owner_file(token_file)
        raise GmailRestError("gmail_rest_token_already_exists")
    if receipt_file.exists() or receipt_file.is_symlink():
        require_owner_file(receipt_file)
        raise GmailRestError("gmail_rest_auth_receipt_already_exists")
    if flow_factory is None:
        import google_auth_oauthlib.flow as oauth_flow  # type: ignore[import-untyped]

        flow_factory = oauth_flow.InstalledAppFlow.from_client_secrets_file
    if session_factory is None:
        from google.auth.transport.requests import AuthorizedSession

        session_factory = AuthorizedSession
    flow = flow_factory(
        str(client), scopes=list(SCOPES), autogenerate_code_verifier=True
    )
    try:
        credentials = flow.run_local_server(
            host="127.0.0.1",
            port=0,
            open_browser=True,
            timeout_seconds=300,
            login_hint=recipient,
            authorization_prompt_message="请在系统浏览器完成 TrainLab Gmail 授权。",
            success_message="TrainLab Gmail 授权完成，可以关闭此页面。",
        )
    except Exception as exc:
        raise GmailRestError("gmail_rest_authorization_failed") from exc
    token_payload = getattr(getattr(flow, "oauth2session", None), "token", {}) or {}
    short_lived = False
    refresh_lifetime = token_payload.get("refresh_token_expires_in")
    if (
        isinstance(refresh_lifetime, (int, float))
        and refresh_lifetime <= 7 * 24 * 3600 + 60
    ):
        short_lived = True
    granted = set(
        getattr(credentials, "granted_scopes", None)
        or getattr(credentials, "scopes", ())
        or ()
    )
    from skills._shared.fit_weekly.gmail_scopes import valid

    scopes_match = valid(granted, labels=True)
    serialized_token = _refreshable_token_payload(credentials)
    if serialized_token is None:
        return _persist_receipt(
            receipt_file,
            {
                "schema_version": "gmail_rest_auth_receipt_v1",
                "status": "blocked",
                "account_matches": False,
                "scopes_match": scopes_match,
                "refresh_token_available": False,
                "token_published": False,
                "short_lived_testing_token": short_lived,
                "provider_calls": 0,
                "completed_at_utc": utc_now(),
            },
        )
    try:
        session = session_factory(credentials)
    except Exception:
        return _profile_failure_receipt(
            receipt_file=receipt_file,
            scopes_match=scopes_match,
            short_lived=short_lived,
            provider_calls=0,
            error_code="gmail_rest_profile_session_failed",
        )
    try:
        response = session.get(f"{API_ROOT}/profile", timeout=30, allow_redirects=False)
    except Exception:
        return _profile_failure_receipt(
            receipt_file=receipt_file,
            scopes_match=scopes_match,
            short_lived=short_lived,
            provider_calls=1,
            error_code="gmail_rest_profile_transport_failed",
        )
    if int(getattr(response, "status_code", 0)) != 200:
        return _profile_failure_receipt(
            receipt_file=receipt_file,
            scopes_match=scopes_match,
            short_lived=short_lived,
            provider_calls=1,
            error_code="gmail_rest_profile_http_failed",
        )
    try:
        profile = response.json()
    except Exception:
        return _profile_failure_receipt(
            receipt_file=receipt_file,
            scopes_match=scopes_match,
            short_lived=short_lived,
            provider_calls=1,
            error_code="gmail_rest_profile_invalid",
        )
    if not isinstance(profile, dict):
        return _profile_failure_receipt(
            receipt_file=receipt_file,
            scopes_match=scopes_match,
            short_lived=short_lived,
            provider_calls=1,
            error_code="gmail_rest_profile_invalid",
        )
    account_matches = str(profile.get("emailAddress", "")).casefold() == recipient
    if short_lived or not scopes_match or not account_matches:
        receipt = {
            "schema_version": "gmail_rest_auth_receipt_v1",
            "status": "blocked",
            "account_matches": account_matches,
            "scopes_match": scopes_match,
            "refresh_token_available": True,
            "token_published": False,
            "short_lived_testing_token": short_lived,
            "provider_calls": 1,
            "completed_at_utc": utc_now(),
        }
        return _persist_receipt(receipt_file, receipt)
    token_bytes = (json.dumps(serialized_token, sort_keys=True) + "\n").encode("utf-8")
    receipt = {
        "schema_version": "gmail_rest_auth_receipt_v1",
        "status": "succeeded",
        "account_matches": True,
        "scopes_match": True,
        "refresh_token_available": True,
        "token_published": True,
        "short_lived_testing_token": False,
        "provider_calls": 1,
        "completed_at_utc": utc_now(),
    }
    try:
        atomic_write(token_file, token_bytes)
        os.chmod(token_file, 0o600)
        return _persist_receipt(receipt_file, receipt)
    except BaseException:
        token_file.unlink(missing_ok=True)
        receipt_file.unlink(missing_ok=True)
        fsync_directory(token_file.parent)
        raise


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--instance", type=Path, required=True)
    result.add_argument("--client-file", type=Path, required=True)
    result.add_argument("--email-file", type=Path, required=True)
    result.add_argument("--token-file", type=Path, required=True)
    result.add_argument("--receipt", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        receipt = authorize(
            instance_root=args.instance,
            client_file=args.client_file,
            email_file=args.email_file,
            token_file=args.token_file,
            receipt_file=args.receipt,
        )
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "account_matches": receipt["account_matches"],
                    "scopes_match": receipt["scopes_match"],
                }
            )
        )
        return 0 if receipt["status"] == "succeeded" else 2
    except (GmailRestError, OSError):
        print(
            json.dumps(
                {"status": "blocked", "error_code": "gmail_rest_authorization_blocked"}
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
