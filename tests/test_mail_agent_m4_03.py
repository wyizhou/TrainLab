from __future__ import annotations

import hashlib
import hmac
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.mail_agent.gmail_adapter import GmailAdapterError, GmailMCPAdapter, GmailMCPConfig, MCPCallError, StdioMailTransport
from trainlab.mcp import MCPResponseError, StdioMCPClient, _safe_error_metadata


NOW = "2026-07-23T00:00:00Z"


def hmac_identity(email: str) -> str:
    return hmac.new(b"mail-test-key", email.encode(), hashlib.sha256).hexdigest()


class FakeMCP:
    def __init__(self, *, email: str = "self@example.com", outcomes: dict[str, list[object]] | None = None, tool_names: set[str] | None = None) -> None:
        self.email = email
        self.outcomes = outcomes or {}
        self.tool_names = tool_names or {"get_self", "search_messages", "read_thread", "send_html_self", "create_or_apply_label"}
        self.calls: list[tuple[str, dict]] = []
        self.refreshes = 0
        self.closed = False

    def list_tools(self):
        return [{"name": name} for name in self.tool_names]

    def refresh_auth(self) -> None:
        self.refreshes += 1

    def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        scripted = self.outcomes.get(name, [])
        value = scripted.pop(0) if scripted else None
        if isinstance(value, Exception):
            raise value
        if value is not None:
            return {"structuredContent": value}
        defaults = {
            "get_self": {"email": self.email},
            "search_messages": {"matches": []},
            "read_thread": {"messages": [{"message_id": "m1", "thread_id": arguments.get("thread_id", "thread-1"), "internal_date_utc": NOW, "from": self.email, "to": [self.email], "subject": "test", "headers": {"message_id": "<m1>", "in_reply_to": "<p>", "references": ["<p>"], "x_trainlab_run_id": "run-1"}, "label_ids": ["Label_1"], "plain_text": "private body", "has_html": True, "attachments": [{"filename": "a.pdf"}]}]},
            "send_html_self": {"message_id": "out-1", "thread_id": "thread-1", "already_sent": False},
            "create_or_apply_label": {"applied": True},
        }
        return {"structuredContent": defaults[name]}

    def close(self) -> None:
        self.closed = True


class FakeStdioClient:
    """Protocol-level fake: it raises sanitized MCP client errors, never MCPCallError."""

    def __init__(self, *, list_error: Exception | None = None, call_outcomes: dict[str, list[object]] | None = None) -> None:
        self.list_error = list_error
        self.call_outcomes = call_outcomes or {}
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def list_tools(self):
        if self.list_error:
            raise self.list_error
        return [{"name": name} for name in {"get_self", "search_messages", "read_thread", "send_html_self", "create_or_apply_label"}]

    def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        scripted = self.call_outcomes.get(name, [])
        value = scripted.pop(0) if scripted else {"structuredContent": {"email": "self@example.com"}}
        if isinstance(value, Exception):
            raise value
        return value

    def close(self) -> None:
        self.closed = True


def config(tmp_path: Path, *, configured: bool = True) -> GmailMCPConfig:
    token_dir = tmp_path / "secrets"; token_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    oauth = token_dir / "oauth.json"; token = token_dir / "token.json"
    oauth.write_text("not-read"); token.write_text("not-read")
    oauth.chmod(0o600); token.chmod(0o600)
    value = {
        "schema_version": 1, "configured": configured, "server_name": "gmail", "provider": "trainlab_gmail_v1", "authenticated_self": "self@example.com",
        "credentials": {"oauth_client_path": str(oauth), "token_path": str(token)},
        "transport": {"type": "stdio", "command": "fake", "args": [], "env": {}, "timeout_seconds": 30},
        "capabilities": {
            "get_self": {"tool": "get_self", "arguments": {}, "result_path": "email"},
            "search": {"tool": "search_messages", "arguments": {"query": "{query}", "max_results": "{max_results}"}, "result_path": "matches"},
            "read_thread": {"tool": "read_thread", "arguments": {"thread_id": "{thread_id}"}, "result_path": None},
            "send_html_self": {"tool": "send_html_self", "arguments": {"run_id": "{run_id}", "subject": "{subject}", "plain_text": "{plain_text}", "html": "{html}", "thread_id": "{thread_id}"}, "result_path": None},
            "create_or_apply_label": {"tool": "create_or_apply_label", "arguments": {"label": "{label}", "message_id": "{message_id}", "thread_id": "{thread_id}"}, "result_path": None},
        },
        "requirements": {"authenticated_self_only": True, "html_and_plain_text": True, "label": "TrainLab", "idempotency_search_by_run_id": True},
    }
    instance = GmailMCPConfig(value, tmp_path / "gmail_mcp.yaml")
    instance.validate()
    return instance


def identity_db(tmp_path: Path, email: str = "self@example.com") -> tuple[sqlite3.Connection, int]:
    root = tmp_path / "foundation"
    foundation = FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state" / "foundation-ready.json", root / "state" / "locks" / "foundation.lock")
    assert FoundationTool(foundation).execute(FoundationRequest("init", "adapter-fixture", NOW)).status == "initialized"
    conn = sqlite3.connect(root / "data.db")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("INSERT INTO data_subjects(subject_key,created_at_utc) VALUES(?,?)", ("mail-subject", NOW))
    subject_id = conn.execute("SELECT id FROM data_subjects").fetchone()[0]
    conn.execute("INSERT INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) VALUES(?,?,?,?,1,?,?)", (subject_id, "gmail", "email", hmac_identity(email), NOW, NOW))
    conn.commit()
    return conn, subject_id


def adapter(tmp_path: Path, fake: FakeMCP) -> GmailMCPAdapter:
    return GmailMCPAdapter(config(tmp_path), transport_factory=lambda _: fake, identity_hmac=hmac_identity, sleep=lambda _: None, inline_retry_after_seconds=3)


def test_mapping_identity_and_dto_allow_only_verified_self(tmp_path: Path) -> None:
    conn, subject_id = identity_db(tmp_path)
    fake = FakeMCP(); instance = adapter(tmp_path, fake)
    assert instance.prepare(conn, subject_id).email == "self@example.com"
    assert instance.search_run_id(run_id="run-1") == ()
    evidence = instance.read_thread_evidence("thread-1")
    thread = evidence.thread
    assert thread.messages[0].provider_message_id == "m1"
    assert thread.messages[0].trainlab_run_id == "run-1"
    assert thread.messages[0].body_text == "private body"
    assert evidence.raw_payload["messages"][0]["plain_text"] == "private body"
    sent = instance.send_html_self(run_id="run-1", subject="subject", plain_text="plain", html="<p>html</p>", thread_id="thread-1")
    instance.apply_trainlab_label(message_id=sent.provider_message_id, thread_id=sent.provider_thread_id)
    assert [name for name, _ in fake.calls] == ["get_self", "search_messages", "read_thread", "send_html_self", "create_or_apply_label"]
    assert all("recipient" not in arguments for _, arguments in fake.calls)


@pytest.mark.parametrize("mutation", ["wrong_email", "missing_identity", "missing_tool", "bad_mapping"])
def test_prepare_failure_never_calls_search_read_or_send(tmp_path: Path, mutation: str) -> None:
    conn, subject_id = identity_db(tmp_path)
    fake = FakeMCP(email="other@example.com" if mutation == "wrong_email" else "self@example.com", tool_names={"get_self", "search_messages", "read_thread", "send_html_self"} if mutation == "missing_tool" else None)
    cfg = config(tmp_path)
    if mutation == "missing_identity":
        conn.execute("DELETE FROM subject_identities"); conn.commit()
    if mutation == "bad_mapping":
        cfg.mapping["capabilities"]["search"]["tool"] = "delete_messages"
    instance = GmailMCPAdapter(cfg, transport_factory=lambda _: fake, identity_hmac=hmac_identity, sleep=lambda _: None)
    with pytest.raises(GmailAdapterError):
        instance.prepare(conn, subject_id)
    assert [name for name, _ in fake.calls if name in {"search_messages", "read_thread", "send_html_self", "create_or_apply_label"}] == []


def test_read_only_errors_retry_at_most_three_and_401_refreshes_once(tmp_path: Path) -> None:
    conn, subject_id = identity_db(tmp_path)
    fake = FakeMCP(outcomes={"search_messages": [MCPCallError(401), MCPCallError(401)]})
    instance = adapter(tmp_path, fake); instance.prepare(conn, subject_id)
    with pytest.raises(GmailAdapterError, match="auth_required"):
        instance.search_run_id(run_id="run")
    assert fake.refreshes == 1
    assert [name for name, _ in fake.calls].count("search_messages") == 2
    fake = FakeMCP(outcomes={"search_messages": [MCPCallError(500), MCPCallError(kind="timeout"), {"matches": []}]})
    instance = adapter(tmp_path, fake); instance.prepare(conn, subject_id)
    assert instance.search_run_id(run_id="run") == ()
    assert [name for name, _ in fake.calls].count("search_messages") == 3


def test_rate_limit_and_forbidden_are_typed_and_do_not_retry_writes(tmp_path: Path) -> None:
    conn, subject_id = identity_db(tmp_path)
    waits: list[float] = []
    fake = FakeMCP(outcomes={"search_messages": [MCPCallError(429, retry_after_seconds=2), {"matches": []}]})
    instance = GmailMCPAdapter(config(tmp_path), transport_factory=lambda _: fake, identity_hmac=hmac_identity, sleep=waits.append, inline_retry_after_seconds=3)
    instance.prepare(conn, subject_id)
    assert instance.search_run_id(run_id="run") == ()
    assert waits == [2.0]
    assert [name for name, _ in fake.calls].count("search_messages") == 2
    fake = FakeMCP(outcomes={"search_messages": [MCPCallError(429, retry_after_seconds=9)]})
    instance = adapter(tmp_path, fake); instance.prepare(conn, subject_id)
    with pytest.raises(GmailAdapterError) as error:
        instance.search_run_id(run_id="run")
    assert error.value.code == "rate_limited" and error.value.retry_at_seconds == 9
    fake = FakeMCP(outcomes={"send_html_self": [MCPCallError(500)]})
    instance = adapter(tmp_path, fake); instance.prepare(conn, subject_id)
    with pytest.raises(GmailAdapterError, match="gmail_transport_failed"):
        instance.send_html_self(run_id="run", subject="s", plain_text="private body", html="<p>private body</p>")
    assert [name for name, _ in fake.calls].count("send_html_self") == 1
    fake = FakeMCP(outcomes={"read_thread": [MCPCallError(403)]})
    instance = adapter(tmp_path, fake); instance.prepare(conn, subject_id)
    with pytest.raises(GmailAdapterError, match="forbidden"):
        instance.read_thread("thread")


def test_bad_token_permissions_and_errors_do_not_disclose_token_or_body(tmp_path: Path) -> None:
    conn, subject_id = identity_db(tmp_path)
    cfg = config(tmp_path)
    token = Path(cfg.mapping["credentials"]["token_path"]); token.chmod(0o644)
    fake = FakeMCP()
    instance = GmailMCPAdapter(cfg, transport_factory=lambda _: fake, identity_hmac=hmac_identity)
    with pytest.raises(GmailAdapterError) as error:
        instance.prepare(conn, subject_id)
    rendered = str(error.value).lower()
    assert "token.json" not in rendered and "not-read" not in rendered and "private body" not in rendered
    assert fake.calls == []


def test_mapping_rejects_any_extra_or_unapproved_tool_surface(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    cfg.mapping["capabilities"]["delete"] = {"tool": "delete_messages", "arguments": {}}
    with pytest.raises(GmailAdapterError, match="gmail_tool_mapping_invalid"):
        cfg.validate()


def test_provider_extra_tool_is_strictly_rejected_before_get_self(tmp_path: Path) -> None:
    conn, subject_id = identity_db(tmp_path)
    fake = FakeMCP(tool_names={"get_self", "search_messages", "read_thread", "send_html_self", "create_or_apply_label", "delete_messages"})
    with pytest.raises(GmailAdapterError, match="gmail_tools_unavailable"):
        adapter(tmp_path, fake).prepare(conn, subject_id)
    assert fake.calls == []


@pytest.mark.parametrize(
    ("outcomes", "expected_code", "expected_calls", "expected_refreshes", "expected_waits"),
    [
        ([MCPCallError(401), {"email": "self@example.com"}], None, 2, 1, []),
        ([MCPCallError(401), MCPCallError(401)], "auth_required", 2, 1, []),
        ([MCPCallError(403)], "forbidden", 1, 0, []),
        ([MCPCallError(429, retry_after_seconds=2), {"email": "self@example.com"}], None, 2, 0, [2.0]),
        ([MCPCallError(429, retry_after_seconds=9)], "rate_limited", 1, 0, []),
        ([MCPCallError(500), MCPCallError(kind="timeout"), {"email": "self@example.com"}], None, 3, 0, []),
    ],
)
def test_get_self_uses_the_read_only_error_policy(
    tmp_path: Path,
    outcomes: list[object],
    expected_code: str | None,
    expected_calls: int,
    expected_refreshes: int,
    expected_waits: list[float],
) -> None:
    conn, subject_id = identity_db(tmp_path)
    waits: list[float] = []
    fake = FakeMCP(outcomes={"get_self": outcomes})
    instance = GmailMCPAdapter(config(tmp_path), transport_factory=lambda _: fake, identity_hmac=hmac_identity, sleep=waits.append, inline_retry_after_seconds=3)
    if expected_code is None:
        assert instance.prepare(conn, subject_id).email == "self@example.com"
    else:
        with pytest.raises(GmailAdapterError) as error:
            instance.prepare(conn, subject_id)
        assert error.value.code == expected_code
    assert [name for name, _ in fake.calls].count("get_self") == expected_calls
    assert fake.refreshes == expected_refreshes
    assert waits == expected_waits


def test_probe_is_persistable_and_contains_no_paths_or_secret_content(tmp_path: Path) -> None:
    conn, subject_id = identity_db(tmp_path)
    instance = adapter(tmp_path, FakeMCP())
    instance.prepare(conn, subject_id)
    probe = instance.capability_probe
    assert probe is not None
    assert probe.mapping_schema_version == 1
    assert len(probe.config_path_sha256) == 64
    assert probe.mapping_valid and probe.credential_paths_checked and probe.credential_permissions_ok
    assert probe.oauth_file_mode == probe.token_file_mode == 0o600
    assert probe.oauth_directory_mode == probe.token_directory_mode == 0o700
    assert probe.strict_tool_surface and probe.authenticated_self_verified
    rendered = repr(probe)
    assert str(tmp_path) not in rendered and "token.json" not in rendered and "not-read" not in rendered


def test_only_typed_search_intents_can_construct_queries(tmp_path: Path) -> None:
    conn, subject_id = identity_db(tmp_path)
    fake = FakeMCP()
    instance = adapter(tmp_path, fake)
    instance.prepare(conn, subject_id)
    assert not hasattr(instance, "search_messages")
    assert instance.search_run_id(run_id="mail:response:42") == ()
    assert fake.calls[-1][1] == {"query": 'subject:"mail:response:42"', "max_results": 10}
    assert instance.search_trainlab_window(start_date=date(2026, 7, 20), end_date=date(2026, 7, 23), max_results=50) == ()
    assert fake.calls[-1][1] == {"query": "label:TrainLab after:2026/07/20 before:2026/07/23", "max_results": 50}
    calls_before_rejection = list(fake.calls)
    with pytest.raises(GmailAdapterError, match="gmail_search_intent_invalid"):
        instance.search_run_id(run_id='run" OR label:Inbox')
    with pytest.raises(GmailAdapterError, match="gmail_search_intent_invalid"):
        instance.search_trainlab_window(start_date=date(2026, 7, 1), end_date=date(2026, 7, 10))
    with pytest.raises(TypeError):
        instance.search_trainlab_window(start_date=date(2026, 7, 20), end_date=date(2026, 7, 21), label="Inbox")  # type: ignore[call-arg]
    assert fake.calls == calls_before_rejection


@pytest.mark.parametrize(
    ("protocol_error", "status", "retry_after", "expected_kind"),
    [
        (MCPResponseError(status_code=401), 401, None, "protocol"),
        (MCPResponseError(status_code=403), 403, None, "protocol"),
        (MCPResponseError(status_code=429, retry_after_seconds=17, kind="tool"), 429, 17, "tool"),
        (MCPResponseError(status_code=503), 503, None, "protocol"),
        (TimeoutError("raw timeout secret"), None, None, "timeout"),
        (RuntimeError("provider stderr token=secret body=private"), None, None, "transport"),
    ],
)
def test_stdio_transport_preserves_only_structured_error_metadata(
    tmp_path: Path, protocol_error: Exception, status: int | None, retry_after: int | None, expected_kind: str
) -> None:
    client = FakeStdioClient(call_outcomes={"get_self": [protocol_error]})
    transport = StdioMailTransport(config(tmp_path), client_factory=lambda *_args, **_kwargs: client)
    with pytest.raises(MCPCallError) as raised:
        transport.call_tool("get_self", {})
    error = raised.value
    assert (error.status_code, error.retry_after_seconds, error.kind) == (status, retry_after, expected_kind)
    assert "secret" not in str(error).lower() and "private" not in str(error).lower()


def test_stdio_client_converts_jsonrpc_and_tool_iserror_without_provider_text(monkeypatch: pytest.MonkeyPatch) -> None:
    class Pipe:
        def write(self, _value: str) -> None: pass
        def flush(self) -> None: pass
        def readline(self) -> str: return '{"jsonrpc":"2.0","id":1,"error":{"message":"token=secret", "data":{"status":429,"retryAfter":12}}}\n'

    class Process:
        stdin = Pipe()
        stdout = Pipe()
        stderr = Pipe()
        def poll(self): return None

    client = object.__new__(StdioMCPClient)
    client.timeout = 1
    client.process = Process()
    client._next_id = 1
    monkeypatch.setattr("trainlab.mcp.select.select", lambda *_args: ([client.process.stdout], [], []))
    with pytest.raises(MCPResponseError) as json_rpc:
        client._request("tools/call", {})
    assert (json_rpc.value.status_code, json_rpc.value.retry_after_seconds) == (429, 12)
    assert "secret" not in str(json_rpc.value).lower()
    client._request = lambda *_args: {"isError": True, "structuredContent": {"status": 403, "message": "private body"}}  # type: ignore[method-assign]
    with pytest.raises(MCPResponseError) as tool_error:
        client.call_tool("get_self", {})
    assert tool_error.value.status_code == 403
    assert "private" not in str(tool_error.value).lower()


def test_stdio_client_allows_each_explicit_preamble_line_once(monkeypatch: pytest.MonkeyPatch) -> None:
    notice = "known startup notice"
    class Pipe:
        def __init__(self, lines: list[str]) -> None: self.lines = lines
        def write(self, _value: str) -> None: pass
        def flush(self) -> None: pass
        def readline(self) -> str: return self.lines.pop(0)
    class Process:
        def __init__(self, lines: list[str]) -> None: self.stdin = Pipe([]); self.stdout = Pipe(lines)
        def poll(self): return None
    def client(lines: list[str]) -> StdioMCPClient:
        value = object.__new__(StdioMCPClient); value.timeout = 1; value.process = Process(lines); value._next_id = 1; value._stdout_preamble_lines = {notice}; return value
    monkeypatch.setattr("trainlab.mcp.select.select", lambda value, *_args: ([value[0]], [], []))
    accepted = client([f"{notice}\n", '{"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n'])
    assert accepted._request("initialize", {}) == {"ok": True}
    repeated = client([f"{notice}\n", f"{notice}\n", '{"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n'])
    with pytest.raises(MCPResponseError) as raised: repeated._request("initialize", {})
    assert raised.value.kind == "protocol"


def test_stdio_client_keeps_successful_legacy_tool_results_unchanged() -> None:
    client = object.__new__(StdioMCPClient)
    expected = {"structuredContent": {"email": "self@example.com"}}
    client._request = lambda *_args: expected  # type: ignore[method-assign]
    assert client.call_tool("get_self", {}) is expected


def test_stdio_client_closes_child_when_initialize_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class Child:
        def __init__(self) -> None: self.terminated = False
        def poll(self): return 0 if self.terminated else None
        def terminate(self) -> None: self.terminated = True
        def wait(self, timeout: int) -> None: return None

    child = Child()
    monkeypatch.setattr("trainlab.mcp.subprocess.Popen", lambda *_args, **_kwargs: child)

    def fail_initialize(*_args, **_kwargs):
        raise MCPResponseError(status_code=403)

    monkeypatch.setattr(StdioMCPClient, "_request", fail_initialize)
    with pytest.raises(MCPResponseError) as error:
        StdioMCPClient("fake", [])
    assert error.value.status_code == 403
    assert child.terminated


class _PipeDouble:
    def __init__(self) -> None: self.closed = 0
    def close(self) -> None: self.closed += 1


class _ProcessDouble:
    def __init__(self, *, exited: bool = False, kill_after_timeout: bool = False) -> None:
        self.exited = exited
        self.kill_after_timeout = kill_after_timeout
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls: list[int] = []
        self.stdin = _PipeDouble(); self.stdout = _PipeDouble(); self.stderr = _PipeDouble()

    def poll(self): return 0 if self.exited else None
    def terminate(self) -> None: self.terminate_calls += 1
    def kill(self) -> None: self.kill_calls += 1; self.exited = True
    def wait(self, timeout: int) -> None:
        self.wait_calls.append(timeout)
        if self.kill_after_timeout and self.kill_calls == 0:
            raise __import__("subprocess").TimeoutExpired("fake", timeout)
        self.exited = True


@pytest.mark.parametrize(
    ("exited", "kill_after_timeout", "expected_terminate", "expected_kill", "expected_waits"),
    [
        (False, False, 1, 0, [3]),
        (False, True, 1, 1, [3, 3]),
        (True, False, 0, 0, []),
    ],
)
def test_stdio_client_close_reaps_and_closes_pipes_idempotently(
    exited: bool, kill_after_timeout: bool, expected_terminate: int, expected_kill: int, expected_waits: list[int]
) -> None:
    process = _ProcessDouble(exited=exited, kill_after_timeout=kill_after_timeout)
    client = object.__new__(StdioMCPClient); client.process = process
    client.close(); client.close()
    assert process.terminate_calls == expected_terminate and process.kill_calls == expected_kill
    assert process.wait_calls == expected_waits
    assert [process.stdin.closed, process.stdout.closed, process.stderr.closed] == [1, 1, 1]


def test_stdio_client_uses_devnull_for_provider_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _ProcessDouble(exited=True)
    popen_calls: list[dict] = []
    monkeypatch.setattr("trainlab.mcp.subprocess.Popen", lambda *_args, **kwargs: popen_calls.append(kwargs) or process)
    monkeypatch.setattr(StdioMCPClient, "_request", lambda *_args: {})
    monkeypatch.setattr(StdioMCPClient, "_notify", lambda *_args: None)
    StdioMCPClient("fake", [])
    assert popen_calls[0]["stderr"] == __import__("subprocess").DEVNULL


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"data": {"status": "401", "retryAfter": "12"}}, (401, 12)),
        ({"structuredContent": {"status": "503", "retry_after_seconds": "00003"}}, (503, 3)),
        ({"data": {"status": "2026-07-23", "retryAfter": "-1"}}, (None, None)),
        ({"data": {"status": "429oops", "retryAfter": "tomorrow"}}, (None, None)),
        ({"data": {"status": "600", "retryAfter": "86401"}}, (None, None)),
    ],
)
def test_safe_error_metadata_accepts_only_bounded_ascii_decimal_strings(payload: dict, expected: tuple[int | None, int | None]) -> None:
    assert _safe_error_metadata(payload) == expected


def test_prepare_closes_real_transport_on_list_and_get_self_failures(tmp_path: Path) -> None:
    conn, subject_id = identity_db(tmp_path)
    changes_before = conn.total_changes
    list_client = FakeStdioClient(list_error=RuntimeError("provider stderr token=secret"))
    list_transport = StdioMailTransport(config(tmp_path), client_factory=lambda *_args, **_kwargs: list_client)
    instance = GmailMCPAdapter(config(tmp_path), transport_factory=lambda _cfg: list_transport, identity_hmac=hmac_identity)
    with pytest.raises(GmailAdapterError, match="gmail_transport_failed") as list_error:
        instance.prepare(conn, subject_id)
    assert list_client.closed
    assert instance.capability_probe is None and instance._identity is None and instance._transport is None
    assert "secret" not in str(list_error.value).lower() and conn.total_changes == changes_before
    self_client = FakeStdioClient(call_outcomes={"get_self": [MCPResponseError(status_code=401)]})
    self_transport = StdioMailTransport(config(tmp_path), client_factory=lambda *_args, **_kwargs: self_client)
    instance = GmailMCPAdapter(config(tmp_path), transport_factory=lambda _cfg: self_transport, identity_hmac=hmac_identity)
    with pytest.raises(GmailAdapterError, match="auth_required"):
        instance.prepare(conn, subject_id)
    assert self_client.closed
    assert [name for name, _ in self_client.calls] == ["get_self"]


def test_close_and_failed_rebuild_clear_all_cached_boundary_state(tmp_path: Path) -> None:
    conn, subject_id = identity_db(tmp_path)
    healthy = FakeMCP()
    failing = FakeMCP(outcomes={"get_self": [MCPCallError(403)]})
    transports = iter((healthy, failing))
    instance = GmailMCPAdapter(config(tmp_path), transport_factory=lambda _cfg: next(transports), identity_hmac=hmac_identity)
    instance.prepare(conn, subject_id)
    assert instance.capability_probe is not None
    with pytest.raises(GmailAdapterError, match="forbidden"):
        instance.prepare(conn, subject_id)
    assert healthy.closed and failing.closed
    assert instance.capability_probe is None and instance._identity is None and instance._transport is None


def test_credential_paths_reject_symlink_non_file_and_non_directory_parent(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    token = Path(cfg.mapping["credentials"]["token_path"])
    token.unlink(); token.symlink_to(Path(cfg.mapping["credentials"]["oauth_client_path"]))
    with pytest.raises(GmailAdapterError, match="gmail_credential_path_invalid"):
        cfg.credential_permission_modes()
    cfg = config(tmp_path / "ancestor")
    alias = tmp_path / "credential-alias"; alias.symlink_to(tmp_path / "ancestor" / "secrets", target_is_directory=True)
    cfg.mapping["credentials"]["oauth_client_path"] = str(alias / "oauth.json")
    with pytest.raises(GmailAdapterError, match="gmail_credential_path_invalid"):
        cfg.credential_permission_modes()
    cfg = config(tmp_path / "second")
    non_file = tmp_path / "second" / "secrets"
    cfg.mapping["credentials"]["token_path"] = str(non_file)
    with pytest.raises(GmailAdapterError, match="gmail_credential_path_invalid"):
        cfg.credential_permission_modes()
    cfg = config(tmp_path / "third")
    parent_file = tmp_path / "not-a-directory"; parent_file.write_text("not-read")
    cfg.mapping["credentials"]["token_path"] = str(parent_file / "token.json")
    with pytest.raises(GmailAdapterError, match="gmail_credential_path_invalid"):
        cfg.credential_permission_modes()
