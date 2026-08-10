from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from trainlab import cli as root_cli
from trainlab import garmin_client
from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.garmin import (
    GarminCollectionTool,
    GarminConfig,
    GarminError,
    SyncReceipt,
    SyncRequest,
    cli,
)
from trainlab.garmin_client import GarminConnectTransport, TokenStore

from .garmin_fakes import DeterministicClock, FakeGarminTransport


def receipt(status: str) -> SyncReceipt:
    return SyncReceipt(
        mode="incremental",
        status=status,
        requested_range={"from": None, "through": "2026-04-15"},
        effective_range={"from": "2026-04-02", "through": "2026-04-15"},
        coverage_state="complete",
        completed_at_utc="2026-04-16T00:00:00Z",
    )


@pytest.mark.parametrize(
    ("status", "code"),
    [
        ("succeeded", 0),
        ("partial", 10),
        ("deferred", 11),
        ("lock_busy", 12),
        ("auth_required", 20),
        ("failed", 21),
    ],
)
def test_main_exit_matrix_one_receipt_json(monkeypatch, capsys, status, code):
    args = SimpleNamespace(
        command="garmin", garmin_mode="sync", garmin_sync_mode="incremental"
    )
    monkeypatch.setattr(
        root_cli, "_parser", lambda: SimpleNamespace(parse_args=lambda _: args)
    )
    monkeypatch.setattr(root_cli, "garmin_cli_execute", lambda _: receipt(status))
    assert root_cli.main([]) == code
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    schema = json.loads(
        (
            Path(__file__).parents[1]
            / "harness/schemas/garmin_sync_receipt.schema.json"
        ).read_text()
    )
    assert not list(Draft202012Validator(schema).iter_errors(json.loads(lines[0])))


def test_status_never_constructs_transport(monkeypatch, tmp_path):
    foundation = SimpleNamespace(state_root=tmp_path / "state")
    config = GarminConfig(
        tmp_path / "missing.db", tmp_path / "raw", tmp_path / "state", "2026-01-01"
    )
    args = SimpleNamespace(
        garmin_mode="status",
        garmin_sync_mode=None,
        health_from=None,
        through=None,
        date=None,
        resource=[],
        activity_id=[],
        strategy=None,
        invocation_id=None,
    )
    monkeypatch.setattr(cli.FoundationConfig, "load", lambda _: foundation)
    monkeypatch.setattr(cli, "load_garmin_config", lambda *_: config)

    class Tool:
        def __init__(self, *a):
            pass

        def execute(self, r):
            return receipt("succeeded")

    monkeypatch.setattr(cli, "GarminCollectionTool", Tool)
    assert (
        cli.garmin_cli_execute(
            args,
            transport_factory=lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("transport")
            ),
        ).status
        == "succeeded"
    )


def test_auth_prompts_stderr_and_secret_is_not_receipt(monkeypatch, tmp_path):
    foundation = SimpleNamespace(state_root=tmp_path / "state")
    config = GarminConfig(
        tmp_path / "db", tmp_path / "raw", tmp_path / "state", "2026-01-01"
    )
    args = SimpleNamespace(
        garmin_mode="auth",
        garmin_sync_mode=None,
        health_from=None,
        through=None,
        date=None,
        resource=[],
        activity_id=[],
        strategy=None,
        invocation_id=None,
    )
    monkeypatch.setattr(cli.FoundationConfig, "load", lambda _: foundation)
    monkeypatch.setattr(cli, "load_garmin_config", lambda *_: config)
    monkeypatch.setattr(cli.getpass, "getpass", lambda *a, **k: "PASSWORD_SECRET")

    class Tool:
        def __init__(self, *a):
            pass

        def execute(self, r):
            return receipt("failed")

    monkeypatch.setattr(cli, "GarminCollectionTool", Tool)

    class TTY(io.StringIO):
        def isatty(self):
            return True

    err = io.StringIO()
    out = cli.garmin_cli_execute(
        args,
        transport_factory=lambda *a, **k: object(),
        stdin=TTY("mail@example.test\n"),
        stderr=err,
    )
    assert "Garmin email" in err.getvalue() and "PASSWORD_SECRET" not in out.json()


def test_mfa_delivery_occurs_only_after_required_and_before_prompt(
    monkeypatch,
    tmp_path,
):
    events = []

    class Response:
        status_code = 200
        headers = {}

        def json(self):
            return {"responseStatus": {"type": "MFA_CODE_SENT"}}

    class Session:
        def request(self, *_args, **_kwargs):
            return Response()

    class MfaSession:
        def post(self, url, **kwargs):
            events.append(("send", url, kwargs))
            return Response()

    class LowClient:
        def __init__(self):
            self.cs = Session()
            self._api_session = Session()
            self._mfa_flow = "ios"
            self._mfa_method = "email"
            self._mfa_session = MfaSession()
            self._mfa_login_params = {"clientId": "synthetic"}
            self._mfa_post_headers = {"Origin": "synthetic"}

    class Facade:
        def __init__(self, *_args, **kwargs):
            self.client = LowClient()
            self.prompt_mfa = kwargs["prompt_mfa"]

        def login(self, _token_store):
            events.append(("required",))
            code = self.prompt_mfa()
            events.append(("verify", code))

    monkeypatch.setattr(garmin_client, "Garmin", Facade)
    prompted = []
    transport = GarminConnectTransport(
        "synthetic@example.test",
        "synthetic-password",
        TokenStore(tmp_path / "tokens"),
        region="cn",
        mfa=lambda method: prompted.append(method) or "synthetic-code",
    )

    assert events == [] and prompted == []
    transport.login()

    assert [event[0] for event in events] == ["required", "send", "verify"]
    send = events[1]
    assert send[1] == "https://sso.garmin.cn/mobile/api/mfa/sendCode"
    assert send[2]["json"] == {"mfaMethod": "email"}
    assert send[2]["timeout"] == 30
    assert prompted == ["email"]


def test_mfa_delivery_failure_never_prompts_for_code(monkeypatch, tmp_path):
    class Response:
        status_code = 200
        headers = {}

        def json(self):
            return {"responseStatus": {"type": "SESSION_EXPIRED"}}

    class Session:
        def request(self, *_args, **_kwargs):
            return Response()

        def post(self, *_args, **_kwargs):
            return Response()

    class LowClient:
        def __init__(self):
            self.cs = Session()
            self._api_session = Session()
            self._mfa_flow = "portal"
            self._mfa_method = "email"
            self._mfa_session = Session()
            self._mfa_login_params = {}
            self._mfa_post_headers = {}

    class Facade:
        def __init__(self, *_args, **kwargs):
            self.client = LowClient()
            self.prompt_mfa = kwargs["prompt_mfa"]

        def login(self, _token_store):
            self.prompt_mfa()

    monkeypatch.setattr(garmin_client, "Garmin", Facade)
    prompted = []
    transport = GarminConnectTransport(
        "synthetic@example.test",
        "synthetic-password",
        TokenStore(tmp_path / "tokens"),
        mfa=lambda method: prompted.append(method) or "synthetic-code",
    )

    with pytest.raises(GarminError, match="mfa_code_delivery_failed"):
        transport.login()
    assert prompted == []


def test_factory_secret_and_nested_sync_are_sanitized(monkeypatch, tmp_path):
    foundation = SimpleNamespace(state_root=tmp_path / "state")
    config = GarminConfig(
        tmp_path / "db", tmp_path / "raw", tmp_path / "state", "2026-01-01"
    )
    args = SimpleNamespace(
        garmin_mode="sync",
        garmin_sync_mode="incremental",
        health_from=None,
        through=None,
        date=None,
        resource=[],
        activity_id=[],
        strategy=None,
        invocation_id=None,
    )
    monkeypatch.setattr(cli.FoundationConfig, "load", lambda _: foundation)
    monkeypatch.setattr(cli, "load_garmin_config", lambda *_: config)
    result = cli.garmin_cli_execute(
        args,
        transport_factory=lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("TOP_SECRET")
        ),
    )
    assert (
        result.mode == "incremental"
        and "TOP_SECRET" not in result.json()
        and result.errors[0]["code"] == "cli_initialization_failed"
    )


def test_token_permissions_symlink_identity_and_final_401(tmp_path):
    store = TokenStore(tmp_path / "tokens")
    nested = store.prepare() / "nested"
    nested.mkdir()
    token = nested / "token"
    token.write_text("x")
    token.chmod(0o644)
    store.prepare()
    assert token.stat().st_mode & 0o777 == 0o600
    link = store.directory / "link"
    link.symlink_to(token)
    with pytest.raises(ValueError, match="symlink"):
        store.prepare()
    root = tmp_path / "data"
    f = FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state/r.json",
        root / "state/l.lock",
    )
    FoundationTool(f).execute(FoundationRequest("init", "f", "2026-01-01T00:00:00Z"))
    # This path reaches the injected 401 before a FIT payload is parsed or stored.
    # Keep the auth-boundary test independent of an untracked health-data fixture.
    fit = b"synthetic-fit-not-parsed"
    c = GarminConfig(f.database_path, f.raw_root, f.state_root, "2026-04-15")
    fake = FakeGarminTransport(fit)
    tool = GarminCollectionTool(
        c, fake, sleep=lambda _: None, clock=DeterministicClock(datetime(2026, 4, 17))
    )
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    fake.identity = lambda: "different-account"
    mismatch = tool.execute(
        SyncRequest(
            "incremental", through_local_date="2026-04-15", invocation_id="mismatch"
        )
    )
    assert mismatch.status == "failed"
    conn = sqlite3.connect(c.database_path)
    assert (
        conn.execute(
            "select count(*) from raw_objects where provider='garmin'"
        ).fetchone()[0]
        == 0
    )
    conn.close()
    fake.identity = lambda: "fake-account"
    fake.faults["health:sleep"] = [
        GarminError("a", http_status=401),
        GarminError("b", http_status=401),
    ]
    result = tool.execute(
        SyncRequest("incremental", through_local_date="2026-04-15", invocation_id="401")
    )
    assert result.status == "auth_required"
    conn = sqlite3.connect(c.database_path)
    assert (
        conn.execute(
            "select status from garmin_sync_runs where invocation_id='401'"
        ).fetchone()[0]
        == "auth_required"
    )
    conn.close()
