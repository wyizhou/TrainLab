from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import sys
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))

from skills._shared.state import (  # noqa: E402
    append_output,
    begin_run,
    canonical_json,
    connect,
    finish_run,
    init_database,
)


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
DELIVERY = load_script("gmail_rest_delivery")


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


def test_deterministic_mime_and_message_id_ignore_output_directory(
    tmp_path: Path,
) -> None:
    kwargs = {
        "recipient": "owner@example.com",
        "subject": "日报",
        "plain": "plain",
        "html": "<p>html</p>",
        "source_sha256": "a" * 64,
        "date_value": datetime(2026, 8, 12, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
    }
    first = COMMON.deterministic_mime(**kwargs)
    second = COMMON.deterministic_mime(**kwargs)
    assert first == second
    assert first[1].startswith("<trainlab.")
    assert tmp_path.as_posix().encode() not in first[0]
    COMMON.verify_mime(
        first[0],
        recipient=kwargs["recipient"],
        subject=kwargs["subject"],
        plain=kwargs["plain"],
        html=kwargs["html"],
        message_id=first[1],
    )


@pytest.mark.parametrize(
    "field", ["recipient", "subject", "plain", "html", "message_id"]
)
def test_mime_verifier_rejects_each_mismatch(field: str) -> None:
    data = {
        "recipient": "owner@example.com",
        "subject": "subject",
        "plain": "plain",
        "html": "<p>html</p>",
        "source_sha256": "b" * 64,
        "date_value": datetime(2026, 8, 12, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
    }
    raw, message_id, _digest = COMMON.deterministic_mime(**data)
    expected = {key: data[key] for key in ("recipient", "subject", "plain", "html")}
    expected["message_id"] = message_id
    expected[field] = "wrong@example.com" if field == "recipient" else "wrong"
    with pytest.raises(COMMON.GmailRestError, match="gmail_rest_mime_mismatch"):
        COMMON.verify_mime(raw, **expected)


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


def seed_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, list[int], bytes, str]:
    candidate = tmp_path / "candidate"
    source = candidate / "source"
    candidate.mkdir(mode=0o700)
    source.mkdir(mode=0o700)
    database = init_database(source / "state/trainlab.db")
    email_file = tmp_path / "runtime-source/email.json"
    owner_write(
        email_file,
        b'{"schema_version":"trainlab_email_recipient_v1","email":"owner@example.com"}',
    )
    monkeypatch.setattr(DELIVERY, "SOURCE_ROOT", email_file.parent)
    input_root = candidate / "gmail-rest/input"
    input_root.mkdir(parents=True, mode=0o700)
    connection = connect(database)
    source_run = begin_run(
        connection,
        run_key="m10-r06-source",
        workflow_key="daily:2026-08-12",
        dedupe_key="m10-r06-source",
        skill_name="training-report-publisher",
        operation="render_daily",
        trigger_kind="manual",
        input_manifest={"fixture": True},
        target_from_date="2026-08-12",
        target_through_date="2026-08-12",
    )
    source_id = append_output(
        connection,
        skill_run_id=source_run,
        output_kind="execution_summary",
        logical_key="m10:r06:source",
        schema_name="synthetic_report_v1",
        schema_version="1",
        title_text="source",
        content_json={"fixture": True},
        content_text="source",
        period_start_date="2026-08-12",
        period_end_date="2026-08-12",
        lineage=[],
    )
    finish_run(connection, source_run, status="succeeded")
    source_sha = str(
        connection.execute(
            "SELECT content_sha256 FROM skill_outputs WHERE id=?", (source_id,)
        ).fetchone()[0]
    )
    emails = []
    raw_first = b""
    message_first = ""
    for ordinal in range(1, 9):
        envelope = {
            "subject": f"Report {ordinal}",
            "text": f"Plain {ordinal}",
            "html": f"<p>HTML {ordinal}</p>",
            "source_output_id": source_id,
            "source_output_sha256": source_sha,
            "report_output_id": source_id,
            "report_output_sha256": source_sha,
        }
        envelope_path = input_root / f"{ordinal:02d}-email-envelope.json"
        owner_write(envelope_path, (canonical_json(envelope) + "\n").encode())
        raw, message_id, mime_sha = COMMON.deterministic_mime(
            recipient="owner@example.com",
            subject=envelope["subject"],
            plain=envelope["text"],
            html=envelope["html"],
            source_sha256=source_sha,
            date_value=datetime(2026, 8, 12, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
        )
        owner_write(input_root / f"{ordinal:02d}-message.eml", raw)
        if ordinal == 1:
            raw_first, message_first = raw, message_id
        request = {
            "transport": "gmail_rest",
            "ordinal": ordinal,
            "message_id": message_id,
            "mime_sha256": mime_sha,
            "recipient_sha256": COMMON.sha256_text("owner@example.com"),
            "source_output_id": source_id,
            "source_output_sha256": source_sha,
        }
        emails.append(
            {
                "ordinal": ordinal,
                "source_output_id": source_id,
                "source_output_sha256": source_sha,
                "envelope_relative_path": str(envelope_path.relative_to(candidate)),
                "envelope_sha256": COMMON.sha256_file(envelope_path),
                "recipient_sha256": COMMON.sha256_text("owner@example.com"),
                "subject_sha256": COMMON.sha256_text(envelope["subject"]),
                "message_id": message_id,
                "mime_sha256": mime_sha,
                "request_sha256": COMMON.sha256_text(COMMON.canonical_json(request)),
            }
        )
    unsigned = {
        "schema_version": "m10_gmail_rest_preview_v1",
        "batch_id": DELIVERY.BATCH_ID,
        "transport": "gmail_rest",
        "parent_preview_output_id": source_id,
        "parent_preview_output_sha256": source_sha,
        "emails": emails,
        "gmail_api_budget": DELIVERY.MAX_API_CALLS,
        "gmail_send_budget": 8,
    }
    preview = {
        **unsigned,
        "preview_sha256": COMMON.sha256_text(COMMON.canonical_json(unsigned)),
    }
    preview_run = begin_run(
        connection,
        run_key="m10-r06-preview",
        workflow_key=DELIVERY.WORKFLOW_KEY,
        dedupe_key="m10-r06-preview",
        skill_name="gmail-sender",
        operation="send_email",
        trigger_kind="manual",
        input_manifest={"fixture": True},
    )
    preview_id = append_output(
        connection,
        skill_run_id=preview_run,
        output_kind="execution_summary",
        logical_key="m10:r06:gmail-rest-preview",
        schema_name="m10_gmail_rest_preview_v1",
        schema_version="1",
        title_text="M10 r06 Gmail REST delivery preview",
        content_json=preview,
        content_text=canonical_json(preview),
        lineage=[{"output_id": source_id, "output_sha256": source_sha}],
    )
    finish_run(connection, preview_run, status="succeeded")
    preview_sha = str(
        connection.execute(
            "SELECT content_sha256 FROM skill_outputs WHERE id=?", (preview_id,)
        ).fetchone()[0]
    )
    action_ids = DELIVERY._prepare_actions(connection, preview_id, preview_sha, preview)
    connection.close()
    auth_receipt = {
        "schema_version": "gmail_rest_auth_receipt_v1",
        "status": "succeeded",
        "account_matches": True,
        "scopes_match": True,
        "refresh_token_available": True,
        "token_published": True,
        "short_lived_testing_token": False,
        "provider_calls": 1,
        "completed_at_utc": "2026-08-19T00:00:00Z",
    }
    auth_receipt_file = DELIVERY.SOURCE_ROOT / COMMON.AUTH_RECEIPT_NAME
    COMMON.atomic_json(auth_receipt_file, auth_receipt)
    marker = {
        "schema_version": "m10_gmail_rest_candidate_v1",
        "batch_id": DELIVERY.BATCH_ID,
        "candidate_source": str(source),
        "database": str(database),
        "parent_database_sha256": "a" * 64,
        "runtime_sha256": DELIVERY._runtime_sha256(),
        "preview_output_id": preview_id,
        "preview_output_sha256": preview_sha,
        "action_ids": action_ids,
        "action_api_calls": {str(action_id): 0 for action_id in action_ids},
        "action_phase_calls": {
            str(action_id): {phase: 0 for phase in DELIVERY.READ_PHASES}
            for action_id in action_ids
        },
        "action_send_calls": {str(action_id): 0 for action_id in action_ids},
        "auth_receipt_sha256": COMMON.sha256_file(auth_receipt_file),
        "auth_provider_calls": 1,
        "canary_confirmed": False,
        "api_calls": 0,
        "send_calls": 0,
        "created_at_utc": "2026-08-19T00:00:00Z",
    }
    COMMON.atomic_json(candidate / DELIVERY.MARKER_NAME, marker)
    token = DELIVERY.SOURCE_ROOT / "gmail-api-token.json"
    owner_write(token, b'{"token":"fake"}')
    return candidate, token, action_ids, raw_first, message_first


def seed_parent_for_builder(
    tmp_path: Path,
    *,
    envelope_matches_report: bool = True,
    first_report_schema: str | None = None,
) -> tuple[Path, Path, Path]:
    parent_root = tmp_path / "parent"
    parent_source = parent_root / "source"
    parent_run = tmp_path / "parent-run"
    parent_root.mkdir(mode=0o700)
    parent_source.mkdir(mode=0o700)
    parent_run.mkdir(mode=0o700)
    database = init_database(parent_source / "state/trainlab.db")
    owner_write(parent_source / "state/trainlab.lock", b"")
    owner_write(parent_root / "formal-state-fingerprint.json", b'{"fixture":true}')
    owner_write(parent_source / "credentials.json", b'{"legacy":"secret"}')
    owner_write(parent_source / "gcp-oauth.keys.json", b'{"installed":{}}')
    connection = connect(database)
    preview_emails = []
    for ordinal in range(1, 9):
        period_start = "2026-08-12" if ordinal == 8 else f"2026-08-{11 + ordinal:02d}"
        period_end = "2026-08-18" if ordinal == 8 else period_start
        source_run_id = begin_run(
            connection,
            run_key=f"builder-ai-source-{ordinal}",
            workflow_key=f"daily:2026-08-{11 + ordinal:02d}",
            dedupe_key=f"builder-ai-source-{ordinal}",
            skill_name="training-coach",
            operation="daily_coach" if ordinal < 8 else "weekly_coach",
            trigger_kind="manual",
            input_manifest={"ordinal": ordinal},
        )
        source_output_id = append_output(
            connection,
            skill_run_id=source_run_id,
            output_kind="execution_summary",
            logical_key=f"builder-ai-source:{ordinal}",
            schema_name=(
                "daily_ai_result_v1" if ordinal < 8 else "weekly_ai_result_v1"
            ),
            schema_version="1",
            title_text=f"AI source {ordinal}",
            content_json={"ordinal": ordinal},
            content_text=f"AI source {ordinal}",
            period_start_date=period_start,
            period_end_date=period_end,
            lineage=[],
        )
        finish_run(connection, source_run_id, status="succeeded")
        source_output_sha = str(
            connection.execute(
                "SELECT content_sha256 FROM skill_outputs WHERE id=?",
                (source_output_id,),
            ).fetchone()[0]
        )
        report_run_id = begin_run(
            connection,
            run_key=f"builder-report-{ordinal}",
            workflow_key=f"daily:2026-08-{11 + ordinal:02d}",
            dedupe_key=f"builder-report-{ordinal}",
            skill_name="training-report-publisher",
            operation="render_daily" if ordinal < 8 else "render_weekly",
            trigger_kind="manual",
            input_manifest={"ordinal": ordinal},
        )
        report_output_id = append_output(
            connection,
            skill_run_id=report_run_id,
            output_kind="email_render",
            logical_key=f"builder-report:{ordinal}",
            schema_name=(
                first_report_schema
                if ordinal == 1 and first_report_schema is not None
                else ("daily_email_render" if ordinal < 8 else "weekly_email_render")
            ),
            schema_version="1",
            title_text=f"Report {ordinal}",
            content_json={"ordinal": ordinal},
            content_text=f"Plain {ordinal}",
            content_html=f"<p>HTML {ordinal}</p>",
            period_start_date=period_start if ordinal == 8 else None,
            period_end_date=period_end if ordinal == 8 else None,
            lineage=[
                {
                    "output_id": source_output_id,
                    "output_sha256": source_output_sha,
                    "source_output_id": source_output_id,
                    "source_output_sha256": source_output_sha,
                }
            ],
        )
        finish_run(connection, report_run_id, status="succeeded")
        report_output_sha = str(
            connection.execute(
                "SELECT content_sha256 FROM skill_outputs WHERE id=?",
                (report_output_id,),
            ).fetchone()[0]
        )
        envelope_path = parent_run / f"{ordinal:02d}-email-envelope.json"
        owner_write(
            envelope_path,
            (
                canonical_json(
                    {
                        "subject": f"Report {ordinal}",
                        "text": (
                            f"Plain {ordinal}"
                            if envelope_matches_report
                            else f"Altered {ordinal}"
                        ),
                        "html": f"<p>HTML {ordinal}</p>",
                        "source_output_id": source_output_id,
                        "source_output_sha256": source_output_sha,
                        "report_output_id": report_output_id,
                        "report_output_sha256": report_output_sha,
                    }
                )
                + "\n"
            ).encode(),
        )
        preview_emails.append(
            {
                "envelope_path": str(envelope_path),
                "envelope_sha256": COMMON.sha256_file(envelope_path),
                "marker": f"m10-r04-{ordinal}",
                "recipient": "owner@example.com",
                "recipient_sha256": COMMON.sha256_text("owner@example.com"),
                "request_sha256": str(ordinal) * 64,
                "source_output_id": report_output_id,
                "source_output_sha256": report_output_sha,
                "subject": f"Report {ordinal}",
                "verification_query": f"rfc822msgid:m10-r04-{ordinal}",
            }
        )
    preview_run = begin_run(
        connection,
        run_key="builder-parent-preview",
        workflow_key="m10:external-preview:2026-08-18",
        dedupe_key="builder-parent-preview",
        skill_name="training-report-publisher",
        operation="render_weekly",
        trigger_kind="manual",
        input_manifest={"fixture": True},
    )
    append_output(
        connection,
        skill_run_id=preview_run,
        output_kind="execution_summary",
        logical_key="builder-parent-preview",
        schema_name="m10_external_preview_v1",
        schema_version="1",
        title_text="parent preview",
        content_json={"emails": preview_emails},
        content_text="parent preview",
        lineage=[],
    )
    finish_run(connection, preview_run, status="succeeded")
    connection.close()
    email = tmp_path / "runtime/source/email.json"
    owner_write(
        email,
        b'{"schema_version":"trainlab_email_recipient_v1","email":"owner@example.com"}',
    )
    return parent_source, parent_run, email


def pin_builder_parent(monkeypatch: pytest.MonkeyPatch, parent_source: Path) -> Path:
    database = parent_source / "state/trainlab.db"
    connection = connect(database, read_only=True, immutable=True)
    preview = connection.execute(
        "SELECT id,content_sha256 FROM skill_outputs "
        "WHERE schema_name='m10_external_preview_v1'"
    ).fetchone()
    connection.close()
    assert preview is not None
    monkeypatch.setattr(
        DELIVERY, "EXPECTED_PARENT_DATABASE_SHA256", COMMON.sha256_file(database)
    )
    monkeypatch.setattr(
        DELIVERY,
        "EXPECTED_PARENT_FINGERPRINT_SHA256",
        COMMON.sha256_file(parent_source.parent / "formal-state-fingerprint.json"),
    )
    monkeypatch.setattr(DELIVERY, "EXPECTED_PARENT_PREVIEW_ID", int(preview[0]))
    monkeypatch.setattr(DELIVERY, "EXPECTED_PARENT_PREVIEW_SHA256", str(preview[1]))
    return database


def test_frozen_email_period_rejects_source_hash_or_date_drift(
    tmp_path: Path,
) -> None:
    parent_source, parent_run, _email = seed_parent_for_builder(tmp_path)
    envelope = COMMON.read_owner_json(parent_run / "01-email-envelope.json")
    connection = connect(
        parent_source / "state/trainlab.db", read_only=True, immutable=True
    )
    try:
        with pytest.raises(RuntimeError, match="gmail_rest_envelope_lineage_invalid"):
            DELIVERY._period_date(
                connection,
                ordinal=1,
                source_output_id=int(envelope["source_output_id"]),
                source_output_sha256="0" * 64,
                report_output_id=int(envelope["report_output_id"]),
            )
        with pytest.raises(RuntimeError, match="gmail_rest_report_period_missing"):
            DELIVERY._period_date(
                connection,
                ordinal=2,
                source_output_id=int(envelope["source_output_id"]),
                source_output_sha256=str(envelope["source_output_sha256"]),
                report_output_id=int(envelope["report_output_id"]),
            )
    finally:
        connection.close()


def test_candidate_builder_preserves_parent_and_excludes_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_source, parent_run, email = seed_parent_for_builder(tmp_path)
    monkeypatch.setattr(DELIVERY, "SOURCE_ROOT", email.parent)
    database = pin_builder_parent(monkeypatch, parent_source)
    before = COMMON.sha256_file(database)
    candidate = tmp_path / "candidate-r06"
    result = DELIVERY.create_candidate(
        parent_source=parent_source,
        parent_run_root=parent_run,
        candidate_root=candidate,
        email_file=email,
    )
    assert result["actions"] == 8
    assert COMMON.sha256_file(database) == before
    assert not (candidate / "source/credentials.json").exists()
    assert not (candidate / "source/gcp-oauth.keys.json").exists()
    assert not (candidate / "source/gmail-api-token.json").exists()
    marker = COMMON.read_owner_json(candidate / DELIVERY.MARKER_NAME)
    assert marker["api_calls"] == 0
    assert marker["send_calls"] == 0
    assert marker["auth_provider_calls"] == 0
    assert marker["auth_receipt_sha256"] is None
    assert marker["runtime_sha256"] == DELIVERY._runtime_sha256()
    first_message = BytesParser(policy=policy.default).parsebytes(
        (candidate / "gmail-rest/input/01-message.eml").read_bytes()
    )
    weekly_message = BytesParser(policy=policy.default).parsebytes(
        (candidate / "gmail-rest/input/08-message.eml").read_bytes()
    )
    assert parsedate_to_datetime(first_message["Date"]) == datetime(
        2026, 8, 12, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")
    )
    assert parsedate_to_datetime(weekly_message["Date"]) == datetime(
        2026, 8, 18, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")
    )
    connection = connect(Path(marker["database"]), read_only=True, immutable=True)
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM external_actions WHERE target_key LIKE 'gmail-rest:m10-r06:%'"
        ).fetchone()[0]
        == 8
    )
    connection.close()
    second_candidate = tmp_path / "candidate-r06-second"
    DELIVERY.create_candidate(
        parent_source=parent_source,
        parent_run_root=parent_run,
        candidate_root=second_candidate,
        email_file=email,
    )
    second_marker = COMMON.read_owner_json(second_candidate / DELIVERY.MARKER_NAME)
    first_preview = COMMON.read_owner_json(
        candidate / "gmail-rest/input/01-email-envelope.json"
    )
    second_preview = COMMON.read_owner_json(
        second_candidate / "gmail-rest/input/01-email-envelope.json"
    )
    assert first_preview == second_preview
    assert marker["preview_output_sha256"] == second_marker["preview_output_sha256"]
    for ordinal in range(1, 9):
        name = f"{ordinal:02d}-message.eml"
        assert COMMON.sha256_file(candidate / "gmail-rest/input" / name) == (
            COMMON.sha256_file(second_candidate / "gmail-rest/input" / name)
        )


def test_candidate_builder_rejects_envelope_content_not_in_email_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_source, parent_run, email = seed_parent_for_builder(
        tmp_path, envelope_matches_report=False
    )
    monkeypatch.setattr(DELIVERY, "SOURCE_ROOT", email.parent)
    pin_builder_parent(monkeypatch, parent_source)
    candidate = tmp_path / "candidate-envelope-mismatch"
    with pytest.raises(RuntimeError, match="gmail_rest_envelope_content_invalid"):
        DELIVERY.create_candidate(
            parent_source=parent_source,
            parent_run_root=parent_run,
            candidate_root=candidate,
            email_file=email,
        )
    assert not (candidate / DELIVERY.MARKER_NAME).exists()


def test_candidate_builder_rejects_parent_sha_or_report_contract_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sha_root = tmp_path / "sha"
    sha_root.mkdir()
    sha_parent, sha_run, sha_email = seed_parent_for_builder(sha_root)
    monkeypatch.setattr(DELIVERY, "SOURCE_ROOT", sha_email.parent)
    pin_builder_parent(monkeypatch, sha_parent)
    envelope_path = sha_run / "01-email-envelope.json"
    envelope = COMMON.read_owner_json(envelope_path)
    envelope["text"] = "tampered after preview"
    owner_write(envelope_path, (canonical_json(envelope) + "\n").encode())
    with pytest.raises(RuntimeError, match="gmail_rest_parent_preview_invalid"):
        DELIVERY.create_candidate(
            parent_source=sha_parent,
            parent_run_root=sha_run,
            candidate_root=tmp_path / "sha-candidate",
            email_file=sha_email,
        )

    schema_root = tmp_path / "schema"
    schema_root.mkdir()
    schema_parent, schema_run, schema_email = seed_parent_for_builder(
        schema_root, first_report_schema="unexpected_email_render"
    )
    monkeypatch.setattr(DELIVERY, "SOURCE_ROOT", schema_email.parent)
    pin_builder_parent(monkeypatch, schema_parent)
    with pytest.raises(RuntimeError, match="gmail_rest_envelope_lineage_invalid"):
        DELIVERY.create_candidate(
            parent_source=schema_parent,
            parent_run_root=schema_run,
            candidate_root=tmp_path / "schema-candidate",
            email_file=schema_email,
        )


def test_candidate_builder_rejects_unpinned_parent_before_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_source, parent_run, email = seed_parent_for_builder(tmp_path)
    monkeypatch.setattr(DELIVERY, "SOURCE_ROOT", email.parent)
    monkeypatch.setattr(DELIVERY, "EXPECTED_PARENT_DATABASE_SHA256", "0" * 64)
    candidate = tmp_path / "candidate-untrusted"
    with pytest.raises(RuntimeError, match="gmail_rest_parent_database_invalid"):
        DELIVERY.create_candidate(
            parent_source=parent_source,
            parent_run_root=parent_run,
            candidate_root=candidate,
            email_file=email,
        )
    assert not candidate.exists()


def test_candidate_builder_rejects_alternate_recipient_path_before_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_source, parent_run, email = seed_parent_for_builder(tmp_path)
    monkeypatch.setattr(DELIVERY, "SOURCE_ROOT", email.parent)
    alternate = tmp_path / "alternate-email.json"
    owner_write(alternate, email.read_bytes())
    candidate = tmp_path / "candidate-alternate-recipient"
    with pytest.raises(RuntimeError, match="gmail_rest_recipient_path_invalid"):
        DELIVERY.create_candidate(
            parent_source=parent_source,
            parent_run_root=parent_run,
            candidate_root=candidate,
            email_file=alternate,
        )
    assert not candidate.exists()


def test_candidate_runtime_drift_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, _token, _actions, _raw, _message_id = seed_candidate(
        tmp_path, monkeypatch
    )
    marker_path = candidate / DELIVERY.MARKER_NAME
    marker = COMMON.read_owner_json(marker_path)
    marker["runtime_sha256"] = "0" * 64
    COMMON.atomic_json(marker_path, marker)
    with pytest.raises(RuntimeError, match="gmail_rest_candidate_invalid"):
        DELIVERY._load_marker(candidate)


def test_delivery_rejects_alternate_token_path_before_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, _token, _actions, _raw, _message_id = seed_candidate(
        tmp_path, monkeypatch
    )
    alternate = tmp_path / "alternate-gmail-api-token.json"
    owner_write(alternate, b'{"token":"fake"}')
    session_calls = 0

    def session_factory(_credentials: Any) -> FakeSession:
        nonlocal session_calls
        session_calls += 1
        return FakeSession([])

    with pytest.raises(RuntimeError, match="gmail_rest_token_path_invalid"):
        DELIVERY.GmailRestClient(
            token_file=alternate,
            candidate_root=candidate,
            marker=DELIVERY._load_marker(candidate),
            session_factory=session_factory,
        )
    assert session_calls == 0


def test_delivery_requires_and_persists_successful_auth_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, _token, _actions, _raw, _message_id = seed_candidate(
        tmp_path, monkeypatch
    )
    marker_path = candidate / DELIVERY.MARKER_NAME
    marker = COMMON.read_owner_json(marker_path)
    marker["auth_receipt_sha256"] = None
    marker["auth_provider_calls"] = 0
    COMMON.atomic_json(marker_path, marker)
    with pytest.raises(RuntimeError, match="gmail_rest_auth_receipt_required"):
        DELIVERY.deliver_batch(
            candidate_root=candidate,
            token_file=tmp_path / "unused-token.json",
            remaining=False,
            session_factory=lambda _credentials: FakeSession([]),
        )
    receipt_file = DELIVERY.SOURCE_ROOT / COMMON.AUTH_RECEIPT_NAME
    receipt = {
        "schema_version": "gmail_rest_auth_receipt_v1",
        "status": "succeeded",
        "account_matches": True,
        "scopes_match": True,
        "refresh_token_available": True,
        "token_published": True,
        "short_lived_testing_token": False,
        "provider_calls": 1,
        "completed_at_utc": "2026-08-19T00:00:00Z",
    }
    alternate_receipt = tmp_path / "alternate-auth-receipt.json"
    COMMON.atomic_json(alternate_receipt, receipt)
    with pytest.raises(RuntimeError, match="gmail_rest_auth_receipt_path_invalid"):
        DELIVERY._bind_auth_receipt(
            candidate, DELIVERY._load_marker(candidate), alternate_receipt
        )
    COMMON.atomic_json(receipt_file, receipt)
    bound = DELIVERY._bind_auth_receipt(
        candidate, DELIVERY._load_marker(candidate), receipt_file
    )
    assert bound["auth_provider_calls"] == 1
    assert bound["auth_receipt_sha256"] == COMMON.sha256_file(receipt_file)


def test_direct_delivery_entry_requires_bound_successful_auth_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, token, actions, _raw, _message_id = seed_candidate(tmp_path, monkeypatch)
    marker_path = candidate / DELIVERY.MARKER_NAME
    marker = COMMON.read_owner_json(marker_path)
    marker["auth_receipt_sha256"] = None
    marker["auth_provider_calls"] = 0
    COMMON.atomic_json(marker_path, marker)
    session_calls = 0

    def session_factory(_credentials: Any) -> FakeSession:
        nonlocal session_calls
        session_calls += 1
        return FakeSession([])

    with pytest.raises(RuntimeError, match="gmail_rest_auth_receipt_required"):
        DELIVERY.deliver_action(
            candidate_root=candidate,
            token_file=token,
            action_id=actions[0],
            session_factory=session_factory,
        )
    assert session_calls == 0


def test_auth_receipt_profile_call_plus_delivery_cannot_exceed_129(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, token, actions, _raw, message_id = seed_candidate(tmp_path, monkeypatch)
    marker = DELIVERY._load_marker(candidate)
    counts = [DELIVERY.MAX_ACTION_CALLS] * 8
    marker["action_api_calls"] = {
        str(action_id): count for action_id, count in zip(actions, counts, strict=True)
    }
    marker["action_phase_calls"] = {
        str(action_id): {
            phase: DELIVERY.MAX_READ_ATTEMPTS for phase in DELIVERY.READ_PHASES
        }
        for action_id in actions
    }
    marker["action_send_calls"] = {str(action_id): 1 for action_id in actions}
    marker["api_calls"] = sum(counts)
    marker["send_calls"] = len(actions)
    COMMON.atomic_json(candidate / DELIVERY.MARKER_NAME, marker)
    session = FakeSession([FakeResponse(200, {})])
    client = DELIVERY.GmailRestClient(
        token_file=token,
        candidate_root=candidate,
        marker=DELIVERY._load_marker(candidate),
        session_factory=lambda _credentials: session,
    )
    with pytest.raises(RuntimeError, match="gmail_rest_api_budget_exceeded"):
        client.list_message(
            message_id,
            action_id=actions[-1],
            kind="total-budget",
            phase="lookup",
        )
    assert session.calls == []


def test_canary_send_raw_verify_and_replay_zero_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, token, actions, raw, message_id = seed_candidate(tmp_path, monkeypatch)
    session = FakeSession(
        [
            FakeResponse(200, {}),
            FakeResponse(200, {"id": "gmail-1"}),
            FakeResponse(200, {"id": "gmail-1", "raw": COMMON.gmail_raw(raw)}),
            FakeResponse(200, {"messages": [{"id": "gmail-1"}]}),
        ]
    )
    result = DELIVERY.deliver_batch(
        candidate_root=candidate,
        token_file=token,
        remaining=False,
        session_factory=lambda _credentials: session,
    )
    assert result == {"status": "succeeded", "delivered": 1}
    assert [method for method, _url in session.calls] == ["GET", "POST", "GET", "GET"]
    connection = connect(
        candidate / "source/state/trainlab.db", read_only=True, immutable=True
    )
    row = connection.execute(
        "SELECT status,result_external_id,provider_marker FROM external_actions WHERE id=?",
        (actions[0],),
    ).fetchone()
    assert tuple(row) == ("succeeded", "gmail-1", message_id)
    lineage = json.loads(
        str(
            connection.execute(
                "SELECT lineage_json FROM skill_outputs WHERE logical_key=?",
                (f"m10:r06:gmail-result:{actions[0]}",),
            ).fetchone()[0]
        )
    )
    assert len(lineage) == 2
    assert {item["output_id"] for item in lineage} == {
        int(
            connection.execute(
                "SELECT source_output_id FROM external_actions WHERE id=?",
                (actions[0],),
            ).fetchone()[0]
        ),
        int(
            json.loads(
                str(
                    connection.execute(
                        "SELECT content_json FROM skill_outputs WHERE logical_key='m10:r06:gmail-rest-preview'"
                    ).fetchone()[0]
                )
            )["emails"][0]["source_output_id"]
        ),
    }
    connection.close()
    database = candidate / "source/state/trainlab.db"
    before_counts = connect(database, read_only=True, immutable=True)
    counts = tuple(
        before_counts.execute(
            "SELECT (SELECT COUNT(*) FROM skill_runs),(SELECT COUNT(*) FROM skill_outputs),"
            "(SELECT COUNT(*) FROM external_actions)"
        ).fetchone()
    )
    before_counts.close()
    replay = FakeSession([])
    DELIVERY.deliver_action(
        candidate_root=candidate,
        token_file=token,
        action_id=actions[0],
        session_factory=lambda _credentials: replay,
    )
    assert replay.calls == []
    after_counts = connect(database, read_only=True, immutable=True)
    assert (
        tuple(
            after_counts.execute(
                "SELECT (SELECT COUNT(*) FROM skill_runs),(SELECT COUNT(*) FROM skill_outputs),"
                "(SELECT COUNT(*) FROM external_actions)"
            ).fetchone()
        )
        == counts
    )
    after_counts.close()


def test_success_replay_rejects_missing_eml_without_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, token, actions, raw, _message_id = seed_candidate(tmp_path, monkeypatch)
    session = FakeSession(
        [
            FakeResponse(200, {}),
            FakeResponse(200, {"id": "gmail-1"}),
            FakeResponse(200, {"id": "gmail-1", "raw": COMMON.gmail_raw(raw)}),
            FakeResponse(200, {"messages": [{"id": "gmail-1"}]}),
        ]
    )
    DELIVERY.deliver_action(
        candidate_root=candidate,
        token_file=token,
        action_id=actions[0],
        session_factory=lambda _credentials: session,
    )
    eml = next((candidate / "gmail-rest/eml").glob("*.eml"))
    eml.rename(candidate / "gmail-rest/eml/missing.eml")
    replay = FakeSession([])
    with pytest.raises(FileNotFoundError):
        DELIVERY.deliver_action(
            candidate_root=candidate,
            token_file=token,
            action_id=actions[0],
            session_factory=lambda _credentials: replay,
        )
    assert replay.calls == []


def test_send_response_loss_recovers_by_query_without_resend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, token, actions, raw, _message_id = seed_candidate(tmp_path, monkeypatch)
    lost = FakeSession([FakeResponse(200, {}), ConnectionError("lost")])
    with pytest.raises(RuntimeError, match="gmail_rest_send_result_unknown"):
        DELIVERY.deliver_action(
            candidate_root=candidate,
            token_file=token,
            action_id=actions[0],
            session_factory=lambda _credentials: lost,
        )
    recovery = FakeSession(
        [
            FakeResponse(200, {"messages": [{"id": "gmail-1"}]}),
            FakeResponse(200, {"id": "gmail-1", "raw": COMMON.gmail_raw(raw)}),
            FakeResponse(200, {"messages": [{"id": "gmail-1"}]}),
        ]
    )
    result = DELIVERY.deliver_action(
        candidate_root=candidate,
        token_file=token,
        action_id=actions[0],
        session_factory=lambda _credentials: recovery,
    )
    assert result["status"] == "succeeded"
    assert all(method == "GET" for method, _url in recovery.calls)


def test_confirmation_allows_four_read_only_empty_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, token, actions, raw, _message_id = seed_candidate(tmp_path, monkeypatch)
    delays: list[float] = []
    monkeypatch.setattr(DELIVERY.time, "sleep", delays.append)
    session = FakeSession(
        [
            FakeResponse(200, {}),
            FakeResponse(200, {"id": "gmail-1"}),
            FakeResponse(200, {"id": "gmail-1", "raw": COMMON.gmail_raw(raw)}),
            FakeResponse(200, {}),
            FakeResponse(200, {}),
            FakeResponse(200, {}),
            FakeResponse(200, {}),
            FakeResponse(200, {"messages": [{"id": "gmail-1"}]}),
        ]
    )
    result = DELIVERY.deliver_action(
        candidate_root=candidate,
        token_file=token,
        action_id=actions[0],
        session_factory=lambda _credentials: session,
    )
    assert result["status"] == "succeeded"
    assert len(session.calls) == 8
    assert delays == [1, 2, 4, 8]


@pytest.mark.parametrize(
    "responses",
    [
        [FakeResponse(200, {"messages": [{"id": "a"}, {"id": "b"}]})],
        [FakeResponse(401, {})],
        [FakeResponse(403, {})],
    ],
)
def test_ambiguous_or_auth_failure_stops_before_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, responses: list[FakeResponse]
) -> None:
    candidate, token, actions, _raw, _message_id = seed_candidate(tmp_path, monkeypatch)
    session = FakeSession(responses)
    with pytest.raises(RuntimeError):
        DELIVERY.deliver_action(
            candidate_root=candidate,
            token_file=token,
            action_id=actions[0],
            session_factory=lambda _credentials: session,
        )
    assert all(method != "POST" for method, _url in session.calls)


def test_read_only_query_retries_5xx_but_send_never_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, token, actions, _raw, _message_id = seed_candidate(tmp_path, monkeypatch)
    delays: list[float] = []
    monkeypatch.setattr(DELIVERY.time, "sleep", delays.append)
    session = FakeSession(
        [
            FakeResponse(429, {}),
            FakeResponse(500, {}),
            FakeResponse(502, {}),
            FakeResponse(503, {}),
            FakeResponse(200, {}),
            ConnectionError("send lost"),
        ]
    )
    with pytest.raises(RuntimeError, match="gmail_rest_send_result_unknown"):
        DELIVERY.deliver_action(
            candidate_root=candidate,
            token_file=token,
            action_id=actions[0],
            session_factory=lambda _credentials: session,
        )
    assert [method for method, _url in session.calls].count("POST") == 1
    assert delays == [1, 2, 4, 8]


@pytest.mark.parametrize(
    ("operation", "error_code"),
    [
        ("lookup", "gmail_rest_query_failed"),
        ("raw", "gmail_rest_get_failed"),
    ],
)
def test_non_connection_read_error_stops_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    error_code: str,
) -> None:
    candidate, token, actions, _raw, message_id = seed_candidate(tmp_path, monkeypatch)
    delays: list[float] = []
    monkeypatch.setattr(DELIVERY.time, "sleep", delays.append)
    session = FakeSession([RuntimeError("application failure")])
    client = DELIVERY.GmailRestClient(
        token_file=token,
        candidate_root=candidate,
        marker=DELIVERY._load_marker(candidate),
        session_factory=lambda _credentials: session,
    )
    with pytest.raises(RuntimeError, match=error_code):
        if operation == "lookup":
            client.list_message(
                message_id,
                action_id=actions[0],
                kind="non-connection",
                phase="lookup",
            )
        else:
            client.get_raw("gmail-1", action_id=actions[0])
    assert len(session.calls) == 1
    assert delays == []


def test_per_email_api_budget_stops_before_seventeenth_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, token, actions, _raw, message_id = seed_candidate(tmp_path, monkeypatch)
    marker = DELIVERY._load_marker(candidate)
    action_key = str(actions[0])
    marker["action_phase_calls"][action_key] = {
        phase: DELIVERY.MAX_READ_ATTEMPTS for phase in DELIVERY.READ_PHASES
    }
    marker["action_send_calls"][action_key] = 1
    marker["action_api_calls"][action_key] = DELIVERY.MAX_ACTION_CALLS
    marker["api_calls"] = DELIVERY.MAX_ACTION_CALLS
    marker["send_calls"] = 1
    COMMON.atomic_json(candidate / DELIVERY.MARKER_NAME, marker)
    session = FakeSession([FakeResponse(200, {})])
    client = DELIVERY.GmailRestClient(
        token_file=token,
        candidate_root=candidate,
        marker=DELIVERY._load_marker(candidate),
        session_factory=lambda _credentials: session,
    )
    with pytest.raises(RuntimeError, match="gmail_rest_action_api_budget_exceeded"):
        client.list_message(
            message_id,
            action_id=actions[0],
            kind="action-budget",
            phase="lookup",
        )
    assert session.calls == []


def test_read_phase_budget_persists_across_client_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, token, actions, _raw, message_id = seed_candidate(tmp_path, monkeypatch)
    monkeypatch.setattr(DELIVERY.time, "sleep", lambda _seconds: None)
    first_counts = (3, 2)
    for response_count in first_counts:
        marker = DELIVERY._load_marker(candidate)
        session = FakeSession(
            [FakeResponse(500, {}) for _index in range(response_count - 1)]
            + [FakeResponse(400, {})]
        )
        client = DELIVERY.GmailRestClient(
            token_file=token,
            candidate_root=candidate,
            marker=marker,
            session_factory=lambda _credentials, current=session: current,
        )
        with pytest.raises(RuntimeError, match="gmail_rest_query_failed"):
            client.list_message(
                message_id,
                action_id=actions[0],
                kind="budget",
                phase="lookup",
            )
        assert len(session.calls) == response_count
    final_session = FakeSession([FakeResponse(200, {})])
    final_client = DELIVERY.GmailRestClient(
        token_file=token,
        candidate_root=candidate,
        marker=DELIVERY._load_marker(candidate),
        session_factory=lambda _credentials: final_session,
    )
    with pytest.raises(RuntimeError, match="gmail_rest_read_budget_exceeded"):
        final_client.list_message(
            message_id,
            action_id=actions[0],
            kind="budget",
            phase="lookup",
        )
    assert final_session.calls == []


def test_provider_call_is_reserved_before_transport_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, token, actions, _raw, message_id = seed_candidate(tmp_path, monkeypatch)
    monkeypatch.setattr(DELIVERY.time, "sleep", lambda _seconds: None)
    client = DELIVERY.GmailRestClient(
        token_file=token,
        candidate_root=candidate,
        marker=DELIVERY._load_marker(candidate),
        session_factory=lambda _credentials: FakeSession(
            [ConnectionError("down") for _index in range(5)]
        ),
    )
    with pytest.raises(RuntimeError, match="gmail_rest_query_transport_failed"):
        client.list_message(
            message_id,
            action_id=actions[0],
            kind="reserve",
            phase="lookup",
        )
    marker = DELIVERY._load_marker(candidate)
    assert marker["api_calls"] == 5
    assert marker["action_api_calls"][str(actions[0])] == 5
    assert marker["action_phase_calls"][str(actions[0])]["lookup"] == 5


def test_raw_read_retries_four_temporary_failures_without_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, token, actions, raw, _message_id = seed_candidate(tmp_path, monkeypatch)
    delays: list[float] = []
    monkeypatch.setattr(DELIVERY.time, "sleep", delays.append)
    session = FakeSession(
        [
            FakeResponse(200, {"messages": [{"id": "gmail-1"}]}),
            ConnectionError("down"),
            FakeResponse(429, {}),
            FakeResponse(500, {}),
            FakeResponse(503, {}),
            FakeResponse(200, {"id": "gmail-1", "raw": COMMON.gmail_raw(raw)}),
            FakeResponse(200, {"messages": [{"id": "gmail-1"}]}),
        ]
    )
    result = DELIVERY.deliver_action(
        candidate_root=candidate,
        token_file=token,
        action_id=actions[0],
        session_factory=lambda _credentials: session,
    )
    assert result["status"] == "succeeded"
    assert [method for method, _url in session.calls].count("POST") == 0
    assert delays == [1, 2, 4, 8]


def test_five_empty_confirmation_queries_leave_unknown_without_resend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, token, actions, raw, _message_id = seed_candidate(tmp_path, monkeypatch)
    monkeypatch.setattr(DELIVERY.time, "sleep", lambda _seconds: None)
    session = FakeSession(
        [
            FakeResponse(200, {}),
            FakeResponse(200, {"id": "gmail-1"}),
            FakeResponse(200, {"id": "gmail-1", "raw": COMMON.gmail_raw(raw)}),
            *[FakeResponse(200, {}) for _index in range(5)],
        ]
    )
    with pytest.raises(RuntimeError, match="gmail_rest_confirmation_invalid"):
        DELIVERY.deliver_action(
            candidate_root=candidate,
            token_file=token,
            action_id=actions[0],
            session_factory=lambda _credentials: session,
        )
    assert [method for method, _url in session.calls].count("POST") == 1
    connection = connect(
        candidate / "source/state/trainlab.db", read_only=True, immutable=True
    )
    assert (
        connection.execute(
            "SELECT status FROM external_actions WHERE id=?", (actions[0],)
        ).fetchone()[0]
        == "unknown"
    )
    connection.close()


def test_intent_is_durable_before_first_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, token, actions, _raw, _message_id = seed_candidate(tmp_path, monkeypatch)

    class InspectingSession(FakeSession):
        def get(self, url: str, **kwargs: Any) -> Any:
            intent = candidate / f"gmail-rest/actions/{actions[0]}/intent.json"
            assert COMMON.require_owner_file(intent).stat().st_size > 0
            return super().get(url, **kwargs)

    session = InspectingSession([FakeResponse(401, {})])
    with pytest.raises(RuntimeError, match="gmail_rest_auth_invalid"):
        DELIVERY.deliver_action(
            candidate_root=candidate,
            token_file=token,
            action_id=actions[0],
            session_factory=lambda _credentials: session,
        )


def test_token_refresh_publish_failure_preserves_old_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = tmp_path / "gmail-api-token.json"
    owner_write(token, b'{"token":"old"}')

    class RefreshCredentials:
        token = "old"
        expired = True

        def refresh(self, _request: Any) -> None:
            self.token = "new"
            self.expired = False

        def to_json(self) -> str:
            return '{"token":"new"}'

    client = object.__new__(DELIVERY.GmailRestClient)
    client.credentials = RefreshCredentials()
    client.refresh_request = object()
    client.token_file = token

    def fail_write(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("disk")

    monkeypatch.setattr(DELIVERY, "atomic_write", fail_write)
    with pytest.raises(RuntimeError, match="gmail_rest_token_refresh_persist_failed"):
        client._refresh_token_if_needed()
    assert token.read_bytes() == b'{"token":"old"}'


@pytest.mark.parametrize("gmail_id", ["../outside", "bad/id", "", True])
def test_provider_message_id_rejects_path_traversal(gmail_id: Any) -> None:
    with pytest.raises(RuntimeError, match="gmail_rest_provider_message_id_invalid"):
        COMMON.require_gmail_message_id(gmail_id)


def test_raw_content_mismatch_never_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, token, actions, raw, _message_id = seed_candidate(tmp_path, monkeypatch)
    altered = raw.replace(b"Plain 1", b"Wrong 1")
    session = FakeSession(
        [
            FakeResponse(200, {"messages": [{"id": "gmail-1"}]}),
            FakeResponse(200, {"id": "gmail-1", "raw": COMMON.gmail_raw(altered)}),
        ]
    )
    with pytest.raises(RuntimeError, match="gmail_rest_mime_mismatch"):
        DELIVERY.deliver_action(
            candidate_root=candidate,
            token_file=token,
            action_id=actions[0],
            session_factory=lambda _credentials: session,
        )
    connection = connect(
        candidate / "source/state/trainlab.db", read_only=True, immutable=True
    )
    status = connection.execute(
        "SELECT status FROM external_actions WHERE id=?", (actions[0],)
    ).fetchone()[0]
    connection.close()
    assert status == "unknown"


def test_canary_failure_or_no_confirmation_keeps_remaining_zero_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, token, _actions, _raw, _message_id = seed_candidate(
        tmp_path, monkeypatch
    )
    session = FakeSession([])
    with pytest.raises(RuntimeError, match="gmail_rest_canary_confirmation_required"):
        DELIVERY.deliver_batch(
            candidate_root=candidate,
            token_file=token,
            remaining=True,
            session_factory=lambda _credentials: session,
        )
    assert session.calls == []


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
