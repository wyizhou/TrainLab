"""Preserved OAuth/common safety on its standalone current maintenance path."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from skills._shared.fit_weekly.storage import canonical as canonical_json

SOURCE = Path(__file__).resolve().parents[3]


def load_script(name: str) -> ModuleType:
    path = SOURCE / f"skills/gmail-sender/scripts/{name}.py"
    spec = importlib.util.spec_from_file_location(f"trainlab_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


COMMON = load_script("gmail_rest_common")
AUTH = load_script("gmail_rest_auth")


def owner_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_bytes(payload)
    os.chmod(path, 0o600)


class FakeResponse:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status_code = status
        self._body = body
        self.content = b"x" if body else b""

    def json(self) -> dict[str, Any]:
        return self._body


class InvalidJsonResponse:
    status_code = 200
    content = b"invalid"

    def json(self) -> dict[str, Any]:
        raise ValueError("invalid json")


class FakeSession:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def _next(self, method: str, url: str) -> Any:
        self.calls.append((method, url))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def get(self, url: str, **_kwargs: Any) -> Any:
        return self._next("GET", url)

    def post(self, url: str, **_kwargs: Any) -> Any:
        return self._next("POST", url)


class FakeCredentials:
    def __init__(
        self, scopes: list[str], *, refresh_token: str | None = "refresh"
    ) -> None:
        self.granted_scopes = scopes
        self.scopes = scopes
        self.refresh_token = refresh_token

    def to_json(self) -> str:
        return json.dumps(
            {
                "token": "private",
                "refresh_token": self.refresh_token,
                "client_id": "desktop-client",
                "client_secret": "desktop-secret",
                "token_uri": "https://oauth2.googleapis.com/token",
                "scopes": self.scopes,
            }
        )


class FakeFlow:
    def __init__(
        self, credentials: FakeCredentials, lifetime: int | None = None
    ) -> None:
        self.credentials = credentials
        self.oauth2session = SimpleNamespace(token={})
        if lifetime is not None:
            self.oauth2session.token["refresh_token_expires_in"] = lifetime

    def run_local_server(self, **kwargs: Any) -> FakeCredentials:
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 0
        assert kwargs["open_browser"] is True
        assert kwargs["timeout_seconds"] == 300
        return self.credentials


def auth_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path, Path]:
    monkeypatch.setattr(AUTH, "SOURCE_ROOT", tmp_path)
    client = tmp_path / "gcp-oauth.keys.json"
    recipient = tmp_path / "email.json"
    token = tmp_path / "gmail-api-token.json"
    receipt = tmp_path / AUTH.AUTH_RECEIPT_NAME
    owner_write(
        client,
        json.dumps(
            {
                "installed": {
                    "client_id": "desktop-client",
                    "client_secret": "desktop-secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
        ).encode(),
    )
    owner_write(
        recipient,
        b'{"schema_version":"trainlab_email_recipient_v1","email":"owner@example.com"}',
    )
    return client, recipient, token, receipt


def test_auth_success_publishes_owner_only_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, recipient, token, receipt_file = auth_fixture(tmp_path, monkeypatch)
    credentials = FakeCredentials(list(COMMON.SCOPES))
    flow = FakeFlow(credentials)
    factory_calls: list[dict[str, Any]] = []

    def flow_factory(*_args: Any, **kwargs: Any) -> FakeFlow:
        factory_calls.append(kwargs)
        return flow

    receipt = AUTH.authorize(
        client_file=client,
        recipient_file=recipient,
        token_file=token,
        receipt_file=receipt_file,
        flow_factory=flow_factory,
        session_factory=lambda _credentials: FakeSession(
            [FakeResponse(200, {"emailAddress": "owner@example.com"})]
        ),
    )
    assert receipt["status"] == "succeeded"
    assert token.stat().st_mode & 0o777 == 0o600
    assert receipt_file.stat().st_mode & 0o777 == 0o600
    assert "owner@example.com" not in canonical_json(receipt)
    assert factory_calls == [
        {"scopes": list(COMMON.SCOPES), "autogenerate_code_verifier": True}
    ]


@pytest.mark.parametrize(
    ("profile", "scopes", "lifetime", "expected"),
    [
        ("other@example.com", list(COMMON.SCOPES), None, "account_matches"),
        ("owner@example.com", [COMMON.SCOPES[0]], None, "scopes_match"),
        ("owner@example.com", list(COMMON.SCOPES), 604799, "short_lived_testing_token"),
    ],
)
def test_auth_blocks_account_scope_or_testing_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    scopes: list[str],
    lifetime: int | None,
    expected: str,
) -> None:
    client, recipient, token, receipt_file = auth_fixture(tmp_path, monkeypatch)
    flow = FakeFlow(FakeCredentials(scopes), lifetime)
    receipt = AUTH.authorize(
        client_file=client,
        recipient_file=recipient,
        token_file=token,
        receipt_file=receipt_file,
        flow_factory=lambda *_args, **_kwargs: flow,
        session_factory=lambda _credentials: FakeSession(
            [FakeResponse(200, {"emailAddress": profile})]
        ),
    )
    assert receipt["status"] == "blocked"
    assert receipt[expected] is (expected == "short_lived_testing_token")
    assert not token.exists()


@pytest.mark.parametrize(
    "failure", [TimeoutError("timeout"), RuntimeError("cancelled")]
)
def test_auth_cancel_or_timeout_never_publishes_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    client, recipient, token, receipt_file = auth_fixture(tmp_path, monkeypatch)

    class FailedFlow:
        def run_local_server(self, **_kwargs: Any) -> None:
            raise failure

    with pytest.raises(RuntimeError, match="gmail_rest_authorization_failed"):
        AUTH.authorize(
            client_file=client,
            recipient_file=recipient,
            token_file=token,
            receipt_file=receipt_file,
            flow_factory=lambda *_args, **_kwargs: FailedFlow(),
            session_factory=lambda _credentials: FakeSession([]),
        )
    assert not token.exists()


def test_auth_rejects_web_client_before_browser_or_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, recipient, token, receipt = auth_fixture(tmp_path, monkeypatch)
    desktop = json.loads(client.read_text(encoding="utf-8"))["installed"]
    owner_write(client, json.dumps({"web": desktop}).encode())
    calls = 0

    def flow_factory(*_args: Any, **_kwargs: Any) -> None:
        nonlocal calls
        calls += 1

    with pytest.raises(RuntimeError, match="gmail_rest_oauth_client_not_desktop"):
        AUTH.authorize(
            client_file=client,
            recipient_file=recipient,
            token_file=token,
            receipt_file=receipt,
            flow_factory=flow_factory,
            session_factory=lambda _credentials: FakeSession([]),
        )
    assert calls == 0
    assert not token.exists()
    assert not receipt.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("auth_uri", "https://attacker.invalid/o/oauth2/auth"),
        ("token_uri", "https://attacker.invalid/token"),
    ],
)
def test_auth_rejects_non_google_oauth_endpoints_before_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    client, recipient, token, receipt = auth_fixture(tmp_path, monkeypatch)
    payload = json.loads(client.read_text(encoding="utf-8"))
    payload["installed"][field] = value
    owner_write(client, json.dumps(payload).encode())
    calls = 0

    def flow_factory(*_args: Any, **_kwargs: Any) -> None:
        nonlocal calls
        calls += 1

    with pytest.raises(RuntimeError, match="gmail_rest_oauth_endpoint_invalid"):
        AUTH.authorize(
            client_file=client,
            recipient_file=recipient,
            token_file=token,
            receipt_file=receipt,
            flow_factory=flow_factory,
            session_factory=lambda _credentials: FakeSession([]),
        )
    assert calls == 0
    assert not token.exists()
    assert not receipt.exists()


@pytest.mark.parametrize(
    ("response", "error_code"),
    [
        (ConnectionError("down"), "gmail_rest_profile_transport_failed"),
        (FakeResponse(500, {}), "gmail_rest_profile_http_failed"),
        (InvalidJsonResponse(), "gmail_rest_profile_invalid"),
    ],
)
def test_profile_failures_persist_owner_only_blocked_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: Any,
    error_code: str,
) -> None:
    client, recipient, token, receipt_file = auth_fixture(tmp_path, monkeypatch)
    receipt = AUTH.authorize(
        client_file=client,
        recipient_file=recipient,
        token_file=token,
        receipt_file=receipt_file,
        flow_factory=lambda *_args, **_kwargs: FakeFlow(
            FakeCredentials(list(COMMON.SCOPES))
        ),
        session_factory=lambda _credentials: FakeSession([response]),
    )
    assert receipt["status"] == "blocked"
    assert receipt["provider_calls"] == 1
    assert receipt["token_published"] is False
    assert receipt["error_code"] == error_code
    assert receipt_file.stat().st_mode & 0o777 == 0o600
    assert COMMON.read_owner_json(receipt_file) == receipt
    serialized = COMMON.canonical_json(receipt)
    assert "owner@example.com" not in serialized
    assert "private" not in serialized
    assert "desktop-secret" not in serialized
    assert not token.exists()


def test_profile_session_failure_records_zero_provider_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, recipient, token, receipt_file = auth_fixture(tmp_path, monkeypatch)

    def fail_session(_credentials: Any) -> Any:
        raise RuntimeError("session")

    receipt = AUTH.authorize(
        client_file=client,
        recipient_file=recipient,
        token_file=token,
        receipt_file=receipt_file,
        flow_factory=lambda *_args, **_kwargs: FakeFlow(
            FakeCredentials(list(COMMON.SCOPES))
        ),
        session_factory=fail_session,
    )
    assert receipt["status"] == "blocked"
    assert receipt["provider_calls"] == 0
    assert receipt["error_code"] == "gmail_rest_profile_session_failed"
    assert not token.exists()


def test_auth_receipt_path_is_unique_across_process_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, recipient, token, receipt_file = auth_fixture(tmp_path, monkeypatch)
    first = AUTH.authorize(
        client_file=client,
        recipient_file=recipient,
        token_file=token,
        receipt_file=receipt_file,
        flow_factory=lambda *_args, **_kwargs: FakeFlow(
            FakeCredentials(list(COMMON.SCOPES))
        ),
        session_factory=lambda _credentials: FakeSession([FakeResponse(500, {})]),
    )
    assert first["status"] == "blocked"
    assert first["provider_calls"] == 1
    flow_calls = 0

    def second_flow(*_args: Any, **_kwargs: Any) -> FakeFlow:
        nonlocal flow_calls
        flow_calls += 1
        return FakeFlow(FakeCredentials(list(COMMON.SCOPES)))

    with pytest.raises(RuntimeError, match="gmail_rest_auth_receipt_path_invalid"):
        AUTH.authorize(
            client_file=client,
            recipient_file=recipient,
            token_file=token,
            receipt_file=tmp_path / "alternate-auth-receipt.json",
            flow_factory=second_flow,
            session_factory=lambda _credentials: FakeSession([]),
        )
    assert flow_calls == 0
    assert COMMON.read_owner_json(receipt_file) == first
    assert not token.exists()


@pytest.mark.parametrize("field", ["client_file", "recipient_file", "token_file"])
def test_auth_rejects_alternate_private_contract_paths_before_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    client, recipient, token, receipt_file = auth_fixture(tmp_path, monkeypatch)
    paths = {
        "client_file": client,
        "recipient_file": recipient,
        "token_file": token,
        "receipt_file": receipt_file,
    }
    paths[field] = tmp_path / f"alternate-{field}.json"
    flow_calls = 0

    def flow_factory(*_args: Any, **_kwargs: Any) -> FakeFlow:
        nonlocal flow_calls
        flow_calls += 1
        return FakeFlow(FakeCredentials(list(COMMON.SCOPES)))

    with pytest.raises(RuntimeError, match="gmail_rest_auth_path_invalid"):
        AUTH.authorize(
            client_file=paths["client_file"],
            recipient_file=paths["recipient_file"],
            token_file=paths["token_file"],
            receipt_file=paths["receipt_file"],
            flow_factory=flow_factory,
            session_factory=lambda _credentials: FakeSession([]),
        )
    assert flow_calls == 0
    assert not receipt_file.exists()
    assert not token.exists()


def test_auth_rejects_nonrefreshable_token_before_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, recipient, token, receipt_file = auth_fixture(tmp_path, monkeypatch)
    session = FakeSession([])
    receipt = AUTH.authorize(
        client_file=client,
        recipient_file=recipient,
        token_file=token,
        receipt_file=receipt_file,
        flow_factory=lambda *_args, **_kwargs: FakeFlow(
            FakeCredentials(list(COMMON.SCOPES), refresh_token=None)
        ),
        session_factory=lambda _credentials: session,
    )
    assert receipt["status"] == "blocked"
    assert receipt["refresh_token_available"] is False
    assert receipt["provider_calls"] == 0
    assert session.calls == []
    assert not token.exists()
    assert COMMON.read_owner_json(receipt_file) == receipt


@pytest.mark.parametrize("gmail_id", ["../outside", "bad/id", "", True])
def test_provider_message_id_rejects_path_traversal(gmail_id: Any) -> None:
    with pytest.raises(RuntimeError, match="gmail_rest_provider_message_id_invalid"):
        COMMON.require_gmail_message_id(gmail_id)


def test_capture_has_no_authorization_header(tmp_path: Path) -> None:
    payload = COMMON.sanitize_capture(
        method="GET",
        url="https://gmail.googleapis.com/gmail/v1/users/me/messages",
        status_code=200,
        request_sha256="a" * 64,
        response={"messages": []},
    )
    assert "authorization" not in COMMON.canonical_json(payload).casefold()
    path = tmp_path / "capture.json"
    COMMON.atomic_json(path, payload)
    assert path.stat().st_mode & 0o777 == 0o600


def test_git_ignores_private_token_and_tracks_no_private_values() -> None:
    ignore = (SOURCE.parent / ".gitignore").read_text(encoding="utf-8")
    assert "/source/gmail-api-token.json" in ignore
    assert "/source/gmail-api-auth-receipt.json" in ignore
    requirements = (SOURCE / "requirements.txt").read_text(encoding="utf-8")
    assert "google-auth==2.56.2" in requirements
    assert "google-auth-oauthlib==1.4.0" in requirements
    assert "requests==2.34.2" in requirements
    assert importlib.metadata.version("google-auth") == "2.56.2"
    assert importlib.metadata.version("google-auth-oauthlib") == "1.4.0"
    assert importlib.metadata.version("requests") == "2.34.2"
