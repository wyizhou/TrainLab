from __future__ import annotations

import importlib.util
import json
import os
import sys
from contextlib import contextmanager, nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))
from skills._shared.state import (  # noqa: E402
    append_output,
    begin_run,
    connect,
    finish_run,
    init_database,
)


def _load(name: str, relative: str) -> Any:
    path = SOURCE / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


COMMON = _load(
    "trainlab_email_live_common_test",
    "skills/gmail-sender/scripts/gmail_rest_common.py",
)
DELIVERY = _load(
    "trainlab_email_live_delivery_test",
    "skills/gmail-sender/scripts/gmail_readable_delivery.py",
)
REST = _load(
    "trainlab_email_live_rest_delivery_test",
    "skills/gmail-sender/scripts/gmail_rest_delivery.py",
)
LIVE = _load(
    "trainlab_email_live_canary_test",
    "skills/gmail-sender/scripts/gmail_readable_live.py",
)


def _owner_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    path.write_bytes(payload)
    path.chmod(0o600)


def _render(kind: str) -> dict[str, Any]:
    if kind == "daily":
        subject = "TrainLab · 每日训练简报 · 2026-08-12"
        schema = "daily_email_render_v2"
    else:
        subject = "TrainLab · 每周总结 · 2026-08-12~2026-08-18"
        schema = "weekly_email_render_v2"
    return {
        "schema_version": schema,
        "kind": kind,
        "subject": subject,
        "text": f"{subject}\n可读内容",
        "html": (
            f"<html><head><title>{subject}</title></head>"
            f"<body><h1>{subject}</h1><p>可读内容</p></body></html>"
        ),
        "view_sha256": ("a" if kind == "daily" else "b") * 64,
        "asset_manifest": {
            "schema_version": "email_inline_asset_manifest_v1",
            "assets": [],
        },
        "provider_calls": 0,
    }


def _preview(root: Path, kind: str) -> Path:
    preview = root / (
        "daily-2026-08-12" if kind == "daily" else "weekly-2026-08-12--2026-08-18"
    )
    preview.mkdir(parents=True, mode=0o700)
    os.chmod(preview, 0o700)
    render = _render(kind)
    files = {
        "view.json": b'{"fixture":true}\n',
        "render.json": (COMMON.canonical_json(render) + "\n").encode(),
        "report.html": render["html"].encode(),
        "report.txt": render["text"].encode(),
        "browser-preview.html": render["html"].encode(),
    }
    artifacts = []
    for name, payload in files.items():
        path = preview / name
        _owner_write(path, payload)
        artifacts.append(
            {
                "path": name,
                "sha256": COMMON.sha256_bytes(payload),
                "byte_size": len(payload),
                "mode": "0600",
            }
        )
    receipt = {
        "schema_version": "m11_email_preview_receipt_v1",
        "status": "succeeded",
        "source_output_id": 1,
        "source_output_sha256": "c" * 64,
        "kind": kind,
        "view_sha256": render["view_sha256"],
        "asset_manifest": render["asset_manifest"],
        "output_ids": [1, 2],
        "files": sorted(files),
        "artifacts": sorted(artifacts, key=lambda item: str(item["path"])),
        "provider_calls": 0,
        "external_actions": 0,
    }
    _owner_write(
        preview / "preview-receipt.json",
        (COMMON.canonical_json(receipt) + "\n").encode(),
    )
    return preview


def _seed_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    parent = tmp_path / "r03"
    previews = parent / "previews"
    parent.mkdir(mode=0o700)
    previews.mkdir(mode=0o700)
    daily_preview = _preview(previews, "daily")
    weekly_preview = _preview(previews, "weekly")
    database = init_database(parent / "source/state/trainlab.db")
    connection = connect(database)
    items = []
    for kind, preview, start, end in (
        ("daily", daily_preview, "2026-08-12", "2026-08-12"),
        ("weekly", weekly_preview, "2026-08-12", "2026-08-18"),
    ):
        render = json.loads((preview / "render.json").read_text())
        run_id = begin_run(
            connection,
            run_key=f"m11-live-{kind}",
            workflow_key=f"m11:live:{kind}",
            dedupe_key=f"m11-live-{kind}",
            skill_name="training-report-publisher",
            operation="render_daily" if kind == "daily" else "render_weekly",
            trigger_kind="manual",
            input_manifest={"fixture": kind},
        )
        output_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind="email_render",
            logical_key=f"m11:live:{kind}:render",
            schema_name=f"{kind}_email_render_v2",
            schema_version="2",
            title_text=render["subject"],
            content_json=render,
            content_text=render["text"],
            content_html=render["html"],
            period_start_date=start,
            period_end_date=end,
            lineage=[],
        )
        finish_run(connection, run_id, status="succeeded")
        output_sha = str(
            connection.execute(
                "SELECT content_sha256 FROM skill_outputs WHERE id=?", (output_id,)
            ).fetchone()[0]
        )
        items.append(
            LIVE.FrozenCanaryItem(
                kind=kind,
                preview_name=preview.name,
                output_id=output_id,
                output_sha256=output_sha,
                render_sha256=COMMON.sha256_file(preview / "render.json"),
                period_start=start,
                period_end=end,
                date_value=datetime(2026, 8, 12, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
            )
        )
    connection.close()
    _owner_write(parent / "build-receipt.json", b'{"fixture":true}\n')

    private_source = tmp_path / "private-source"
    private_source.mkdir(mode=0o700)
    _owner_write(
        private_source / "email.json",
        b'{"schema_version":"trainlab_email_recipient_v1","email":"owner@example.com"}',
    )
    _owner_write(private_source / "gmail-api-token.json", b'{"token":"fixture"}')
    auth = {
        "schema_version": "gmail_rest_auth_receipt_v1",
        "status": "succeeded",
        "account_matches": True,
        "scopes_match": True,
        "refresh_token_available": True,
        "token_published": True,
        "short_lived_testing_token": False,
        "provider_calls": 1,
        "completed_at_utc": "2026-08-20T00:00:00Z",
    }
    _owner_write(
        private_source / COMMON.AUTH_RECEIPT_NAME,
        (COMMON.canonical_json(auth) + "\n").encode(),
    )
    formal = tmp_path / "formal-source"
    formal.mkdir(mode=0o700)
    monkeypatch.setattr(LIVE, "FROZEN_R03_ROOT", parent)
    monkeypatch.setattr(LIVE, "PRIVATE_SOURCE_ROOT", private_source)
    monkeypatch.setattr(LIVE, "FORMAL_SOURCE_ROOT", formal)
    monkeypatch.setattr(LIVE, "FROZEN_ITEMS", tuple(items))
    monkeypatch.setattr(
        LIVE, "FROZEN_PARENT_DATABASE_SHA256", COMMON.sha256_file(database)
    )
    monkeypatch.setattr(
        LIVE,
        "FROZEN_BUILD_RECEIPT_SHA256",
        COMMON.sha256_file(parent / "build-receipt.json"),
    )
    monkeypatch.setattr(
        LIVE,
        "_formal_state_fingerprint",
        lambda _root: {
            "schema_version": "formal_state_fingerprint_v1",
            "sha256": "f" * 64,
            "entries": [],
        },
    )
    monkeypatch.setattr(LIVE, "_hold_formal_state_lock", lambda: nullcontext())
    return parent, private_source


class FakeTransport:
    def __init__(self, *, lose_send: bool = False) -> None:
        self.messages: dict[str, bytes] = {}
        self.actual_ids: dict[str, str] = {}
        self.calls: list[str] = []
        self.lose_send = lose_send
        self.send_count = 0

    def search_rfc822(self, message_id: str) -> list[str]:
        self.calls.append("search")
        return [key for key, value in self.actual_ids.items() if value == message_id]

    def send(self, raw: bytes) -> str:
        self.calls.append("send")
        self.send_count += 1
        gmail_id = f"gmail-{self.send_count}"
        self.messages[gmail_id] = raw
        self.actual_ids[gmail_id] = DELIVERY.actual_message_id(raw)
        if self.lose_send:
            self.lose_send = False
            raise ConnectionError("lost")
        return gmail_id

    def get_raw(self, gmail_id: str) -> bytes:
        self.calls.append("get")
        return self.messages[gmail_id]


class _HttpResponse:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status_code = status
        self._body = body
        self.content = b"{}"

    def json(self) -> dict[str, Any]:
        return self._body


class _RewritingGmailSession:
    def __init__(self) -> None:
        self.messages: dict[str, bytes] = {}
        self.calls: list[str] = []
        self.queries: list[str] = []

    def get(self, url: str, **kwargs: Any) -> _HttpResponse:
        self.calls.append("GET")
        if url.endswith("/messages"):
            query = str(kwargs["params"]["q"])
            self.queries.append(query)
            message_id = query.removeprefix("rfc822msgid:")
            matches = [
                {"id": gmail_id}
                for gmail_id, raw in self.messages.items()
                if DELIVERY.actual_message_id(raw) == message_id
            ]
            return _HttpResponse(200, {"messages": matches} if matches else {})
        gmail_id = url.rsplit("/", 1)[-1]
        return _HttpResponse(
            200,
            {"id": gmail_id, "raw": COMMON.gmail_raw(self.messages[gmail_id])},
        )

    def post(self, _url: str, **kwargs: Any) -> _HttpResponse:
        self.calls.append("POST")
        gmail_id = f"gmail-{len(self.messages) + 1}"
        raw = COMMON.decode_gmail_raw(kwargs["json"]["raw"])
        requested_id = DELIVERY.actual_message_id(raw)
        actual_id = f"<provider-{gmail_id}@gmail.invalid>"
        rewritten = raw.replace(requested_id.encode(), actual_id.encode(), 1)
        assert rewritten != raw
        self.messages[gmail_id] = rewritten
        return _HttpResponse(200, {"id": gmail_id})


class _RejectingGmailSession(_RewritingGmailSession):
    def post(self, _url: str, **_kwargs: Any) -> _HttpResponse:
        self.calls.append("POST")
        return _HttpResponse(400, {"error": {"code": 400}})


def _install_rewriting_rest(
    monkeypatch: pytest.MonkeyPatch,
    private_source: Path,
    session: _RewritingGmailSession,
) -> None:
    real_client = REST.GmailRestClient
    monkeypatch.setattr(REST, "SOURCE_ROOT", private_source)
    monkeypatch.setattr(
        real_client,
        "_wait_before_retry",
        staticmethod(lambda _attempt: None),
    )

    def client_factory(**kwargs: Any) -> Any:
        return real_client(
            **kwargs,
            session_factory=lambda _credentials: session,
        )

    monkeypatch.setattr(LIVE, "GmailRestClient", client_factory)


def _delivery_ledger(
    candidate: Path, kind: str
) -> tuple[str, list[tuple[int, str, int, str, int | None]]]:
    marker = COMMON.read_owner_json(candidate / LIVE.MARKER_NAME)
    item = next(value for value in marker["items"] if value["kind"] == kind)
    connection = connect(
        candidate / "source/state/trainlab.db", read_only=True, immutable=True
    )
    try:
        action_status = str(
            connection.execute(
                "SELECT status FROM external_actions WHERE id=?",
                (int(item["action_id"]),),
            ).fetchone()[0]
        )
        rows = connection.execute(
            """SELECT id,status,attempt_no,operation,parent_run_id FROM skill_runs
            WHERE dedupe_key=(SELECT dedupe_key FROM skill_runs WHERE id=?)
            ORDER BY attempt_no""",
            (int(item["delivery_run_id"]),),
        ).fetchall()
    finally:
        connection.close()
    return action_status, [
        (int(row[0]), str(row[1]), int(row[2]), str(row[3]), row[4]) for row in rows
    ]


def test_builds_exact_two_action_candidate_without_copying_private_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"

    receipt = LIVE.build_candidate(candidate)

    assert receipt["status"] == "succeeded"
    assert receipt["actions"] == 2
    assert not list(candidate.rglob("gmail-api-token.json"))
    assert not list(candidate.rglob("email.json"))
    assert not list(candidate.rglob("gcp-oauth.keys.json"))
    marker = COMMON.read_owner_json(candidate / LIVE.MARKER_NAME)
    assert marker["api_calls"] == 0
    assert marker["send_calls"] == 0
    assert marker["daily_confirmed"] is False
    assert "owner@example.com" not in COMMON.canonical_json(marker)
    connection = connect(
        candidate / "source/state/trainlab.db", read_only=True, immutable=True
    )
    try:
        rows = connection.execute(
            "SELECT status,attempt_count FROM external_actions "
            "WHERE target_key LIKE 'm11:live-canary:%' ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    assert [tuple(row) for row in rows] == [("prepared", 0), ("prepared", 0)]
    assert _delivery_ledger(candidate, "daily")[1][0][1] == "pending"
    assert _delivery_ledger(candidate, "weekly")[1][0][1] == "pending"
    LIVE.verify_candidate(candidate)


def test_health_correction_candidate_binds_old_success_and_never_claims_old_weekly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, _private = _seed_parent(tmp_path, monkeypatch)
    historical = tmp_path / "historical-live"
    LIVE.build_candidate(historical)
    result = LIVE.deliver_daily(historical, transport=FakeTransport())
    assert result["status"] == "succeeded"
    old_marker_path = historical / LIVE.MARKER_NAME
    old_marker = COMMON.read_owner_json(old_marker_path)
    daily_key = str(old_marker["action_ids"][0])
    old_marker["action_phase_calls"][daily_key] = {
        "lookup": 1,
        "raw": 1,
        "confirmation": 1,
    }
    old_marker["action_api_calls"][daily_key] = 4
    old_marker["action_send_calls"][daily_key] = 1
    old_marker["api_calls"] = 4
    old_marker["send_calls"] = 1
    COMMON.atomic_json(old_marker_path, old_marker)
    old_database = historical / "source/state/trainlab.db"
    old_database_sha = COMMON.sha256_file(old_database)
    old_marker_sha = COMMON.sha256_file(old_marker_path)
    old_connection = connect(old_database, read_only=True, immutable=True)
    try:
        before_weekly = tuple(
            old_connection.execute(
                "SELECT status,attempt_count,result_external_id FROM external_actions "
                "WHERE id=?",
                (int(old_marker["action_ids"][1]),),
            ).fetchone()
        )
    finally:
        old_connection.close()
    names = (
        "BATCH_ID",
        "WORKFLOW_KEY",
        "TARGET_KEY_PREFIX",
        "MARKER_NAME",
        "MARKER_SCHEMA_NAME",
        "MARKER_SCHEMA_VERSION",
        "FROZEN_R03_ROOT",
        "FROZEN_PARENT_DATABASE_SHA256",
        "FROZEN_BUILD_RECEIPT_SHA256",
        "FROZEN_ITEMS",
        "APPROVAL_SOURCE_REF",
        "APPROVAL_REASON_CODE",
        "HISTORICAL_LIVE_ROOT",
        "FROZEN_HISTORICAL_MARKER_SHA256",
        "FROZEN_HISTORICAL_DATABASE_SHA256",
    )
    originals = {name: getattr(LIVE, name) for name in names}
    try:
        LIVE._activate_health_correction_policy()
        LIVE.FROZEN_R03_ROOT = parent
        LIVE.FROZEN_PARENT_DATABASE_SHA256 = COMMON.sha256_file(
            parent / "source/state/trainlab.db"
        )
        LIVE.FROZEN_BUILD_RECEIPT_SHA256 = COMMON.sha256_file(
            parent / "build-receipt.json"
        )
        LIVE.FROZEN_ITEMS = originals["FROZEN_ITEMS"]
        LIVE.HISTORICAL_LIVE_ROOT = historical
        LIVE.FROZEN_HISTORICAL_MARKER_SHA256 = old_marker_sha
        LIVE.FROZEN_HISTORICAL_DATABASE_SHA256 = old_database_sha
        correction = tmp_path / "health-correction"
        receipt = LIVE.build_candidate(correction)
        assert receipt["actions"] == 2
        marker = COMMON.read_owner_json(correction / LIVE.MARKER_NAME)
        assert marker["schema_version"] == "m11_live_canary_candidate_v2"
        assert marker["historical_api_calls"] == 4
        assert marker["historical_send_calls"] == 1
        assert marker["cumulative_max_api_calls"] == 48
        assert marker["cumulative_max_send_calls"] == 3
        LIVE.verify_candidate(correction)
    finally:
        for name, value in originals.items():
            setattr(LIVE, name, value)
    old_connection = connect(old_database, read_only=True, immutable=True)
    try:
        after_weekly = tuple(
            old_connection.execute(
                "SELECT status,attempt_count,result_external_id FROM external_actions "
                "WHERE id=?",
                (int(old_marker["action_ids"][1]),),
            ).fetchone()
        )
    finally:
        old_connection.close()
    assert before_weekly == after_weekly == ("prepared", 0, None)


def test_daily_confirmation_gates_weekly_and_success_replay_is_zero_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)
    daily = FakeTransport()
    weekly = FakeTransport()

    with pytest.raises(LIVE.GmailRestError, match="daily_not_succeeded"):
        LIVE.deliver_weekly(candidate, transport=daily)
    daily_result = LIVE.deliver_daily(candidate, transport=daily)
    assert daily_result["status"] == "succeeded"
    assert daily.send_count == 1
    with pytest.raises(LIVE.GmailRestError, match="confirmation_required"):
        LIVE.deliver_weekly(candidate, transport=weekly)
    assert weekly.calls == []
    confirmation = LIVE.confirm_daily(candidate, user_confirmed=True)
    assert confirmation["provider_calls"] == 0
    weekly_result = LIVE.deliver_weekly(candidate, transport=weekly)
    assert weekly_result["status"] == "succeeded"
    assert weekly.send_count == 1
    weekly_confirmation = LIVE.confirm_weekly(candidate, user_confirmed=True)
    assert weekly_confirmation["provider_calls"] == 0

    daily.calls.clear()
    weekly.calls.clear()
    before = LIVE.logical_snapshot(candidate)
    assert LIVE.deliver_daily(candidate, transport=daily) == daily_result
    assert LIVE.deliver_weekly(candidate, transport=weekly) == weekly_result
    assert LIVE.logical_snapshot(candidate) == before
    assert daily.calls == []
    assert weekly.calls == []


def test_unknown_send_never_resends_or_unlocks_weekly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)
    transport = FakeTransport(lose_send=True)

    first = LIVE.deliver_daily(candidate, transport=transport)
    assert first["status"] == "unknown"
    assert transport.send_count == 1
    action_status, runs = _delivery_ledger(candidate, "daily")
    assert action_status == "unknown"
    assert [row[1] for row in runs] == ["blocked"]
    LIVE.verify_candidate(candidate)
    transport.calls.clear()
    replay = LIVE.deliver_daily(candidate, transport=transport)
    assert replay == first
    assert transport.calls == []
    with pytest.raises(LIVE.GmailRestError, match="daily_not_succeeded"):
        LIVE.confirm_daily(candidate, user_confirmed=True)
    assert transport.send_count == 1


def test_rest_adapter_uses_lookup_confirmation_phases_and_saves_raw(
    tmp_path: Path,
) -> None:
    root = tmp_path / "action"
    root.mkdir(mode=0o700)
    raw = b"provider raw"

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[Any, ...]] = []

        def list_message(self, message_id: str, **kwargs: Any) -> list[str]:
            self.calls.append(("list", message_id, kwargs))
            return []

        def send(self, value: bytes, **kwargs: Any) -> str:
            self.calls.append(("send", value, kwargs))
            return "gmail-1"

        def get_raw(self, gmail_id: str, **kwargs: Any) -> bytes:
            self.calls.append(("raw", gmail_id, kwargs))
            return raw

    client = FakeClient()
    adapter = LIVE.GmailReadableRestTransport(client=client, action_id=7, run_root=root)
    assert adapter.search_rfc822("<before@trainlab.invalid>") == []
    assert adapter.send(b"requested") == "gmail-1"
    assert adapter.get_raw("gmail-1") == raw
    assert adapter.search_rfc822("<after@trainlab.invalid>") == []

    first = client.calls[0][2]
    last = client.calls[-1][2]
    assert first["phase"] == "lookup" and first["retry_empty"] is False
    assert last["phase"] == "confirmation" and last["retry_empty"] is True
    assert (root / "provider.eml").read_bytes() == raw
    assert (root / "provider.eml").stat().st_mode & 0o777 == 0o600


def test_live_transport_precreates_every_capture_directory_owner_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "candidate"
    run_root = candidate / "gmail-readable/daily"
    run_root.mkdir(parents=True, mode=0o700)
    for path in (candidate, candidate / "gmail-readable", run_root):
        path.chmod(0o700)

    class FakeClient:
        def __init__(self, **_kwargs: Any) -> None:
            pass

    monkeypatch.setattr(LIVE, "GmailRestClient", FakeClient)
    LIVE._live_transport(candidate, {}, 1, run_root)

    assert (candidate / "gmail-rest").stat().st_mode & 0o777 == 0o700
    assert (candidate / "gmail-rest/captures").stat().st_mode & 0o777 == 0o700


def test_formal_state_drift_blocks_before_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)
    monkeypatch.setattr(
        LIVE,
        "_formal_state_fingerprint",
        lambda _root: {
            "schema_version": "formal_state_fingerprint_v1",
            "sha256": "e" * 64,
            "entries": [],
        },
    )
    transport = FakeTransport()

    with pytest.raises(LIVE.GmailRestError, match="formal_state_changed"):
        LIVE.deliver_daily(candidate, transport=transport)

    assert transport.calls == []
    action_status, runs = _delivery_ledger(candidate, "daily")
    assert action_status == "failed_safe"
    assert [row[1] for row in runs] == ["blocked"]


def test_formal_state_lock_unavailable_dual_terminal_without_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)

    @contextmanager
    def unavailable_formal_lock() -> Any:
        raise LIVE.GmailRestError("gmail_live_formal_state_lock_unavailable")
        yield

    monkeypatch.setattr(LIVE, "_hold_formal_state_lock", unavailable_formal_lock)
    transport = FakeTransport()
    with pytest.raises(LIVE.GmailRestError, match="formal_state_lock_unavailable"):
        LIVE.deliver_daily(candidate, transport=transport)

    assert transport.calls == []
    action_status, runs = _delivery_ledger(candidate, "daily")
    assert action_status == "failed_safe"
    assert [row[1] for row in runs] == ["blocked"]


def test_invalid_private_token_dual_terminal_without_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _parent, private_source = _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)
    _owner_write(private_source / "gmail-api-token.json", b"{invalid")
    monkeypatch.setitem(
        LIVE.GmailRestClient.__init__.__globals__, "SOURCE_ROOT", private_source
    )

    with pytest.raises(LIVE.GmailRestError, match="auth_invalid"):
        LIVE.deliver_daily(candidate)

    action_status, runs = _delivery_ledger(candidate, "daily")
    assert action_status == "failed_safe"
    assert [row[1] for row in runs] == ["blocked"]
    marker = COMMON.read_owner_json(candidate / LIVE.MARKER_NAME)
    assert marker["api_calls"] == 0
    assert marker["send_calls"] == 0


def test_changed_auth_receipt_dual_terminal_without_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _parent, private_source = _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)
    auth_path = private_source / COMMON.AUTH_RECEIPT_NAME
    auth = COMMON.read_owner_json(auth_path)
    auth["account_matches"] = False
    _owner_write(auth_path, (COMMON.canonical_json(auth) + "\n").encode())

    with pytest.raises(LIVE.GmailRestError, match="auth_receipt_invalid"):
        LIVE.deliver_daily(candidate)

    action_status, runs = _delivery_ledger(candidate, "daily")
    assert action_status == "failed_safe"
    assert [row[1] for row in runs] == ["blocked"]
    marker = COMMON.read_owner_json(candidate / LIVE.MARKER_NAME)
    assert marker["api_calls"] == 0
    assert marker["send_calls"] == 0


def test_local_intent_write_failure_dual_terminal_without_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)
    delivery_globals = LIVE.deliver_once.__globals__
    real_atomic_json = delivery_globals["atomic_json"]
    failed = {"value": False}

    def fail_intent_once(path: Path, payload: dict[str, Any]) -> None:
        if path.name == "intent.json" and not failed["value"]:
            failed["value"] = True
            raise OSError("finite fixture failure")
        real_atomic_json(path, payload)

    monkeypatch.setitem(delivery_globals, "atomic_json", fail_intent_once)
    transport = FakeTransport()
    with pytest.raises(LIVE.GmailRestError, match="local_io_failed"):
        LIVE.deliver_daily(candidate, transport=transport)

    assert transport.calls == []
    action_status, runs = _delivery_ledger(candidate, "daily")
    assert action_status == "failed_safe"
    assert [row[1] for row in runs] == ["blocked"]
    LIVE.verify_candidate(candidate)


def test_post_result_audit_write_failure_closes_remote_success_without_resend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)
    real_atomic_json = LIVE.atomic_json
    failed = {"value": False}

    def fail_token_after_once(path: Path, payload: dict[str, Any]) -> None:
        if path.name == "token-after.json" and not failed["value"]:
            failed["value"] = True
            raise OSError("finite fixture failure")
        real_atomic_json(path, payload)

    monkeypatch.setattr(LIVE, "atomic_json", fail_token_after_once)
    transport = FakeTransport()
    with pytest.raises(LIVE.GmailRestError, match="local_io_failed"):
        LIVE.deliver_daily(candidate, transport=transport)

    assert transport.send_count == 1
    action_status, runs = _delivery_ledger(candidate, "daily")
    assert action_status == "succeeded"
    assert [row[1] for row in runs] == ["succeeded"]
    transport.calls.clear()
    replay = LIVE.deliver_daily(candidate, transport=transport)
    assert replay["status"] == "succeeded"
    assert transport.calls == []


def test_legitimate_token_refresh_after_candidate_build_does_not_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _parent, private_source = _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)
    _owner_write(private_source / "gmail-api-token.json", b'{"token":"refreshed"}')
    transport = FakeTransport()

    result = LIVE.deliver_daily(candidate, transport=transport)

    assert result["status"] == "succeeded"
    assert transport.send_count == 1
    marker = COMMON.read_owner_json(candidate / LIVE.MARKER_NAME)
    assert "token_build_sha256" not in marker
    assert "token_last_sha256" not in marker


def test_formal_state_drift_while_acquiring_candidate_lock_blocks_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)
    formal_sha = {"value": "f" * 64}
    monkeypatch.setattr(
        LIVE,
        "_formal_state_fingerprint",
        lambda _root: {
            "schema_version": "formal_state_fingerprint_v1",
            "sha256": formal_sha["value"],
            "entries": [],
        },
    )

    @contextmanager
    def drifting_lock(_database: Path) -> Any:
        formal_sha["value"] = "e" * 64
        yield

    monkeypatch.setattr(LIVE, "workflow_lock", drifting_lock)
    transport = FakeTransport()

    with pytest.raises(LIVE.GmailRestError, match="formal_state_changed"):
        LIVE.deliver_daily(candidate, transport=transport)

    assert transport.calls == []


def test_trusted_token_change_during_transport_does_not_rebind_frozen_mime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _parent, private_source = _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)
    transport = FakeTransport()

    def drifting_transport(*_args: Any, **_kwargs: Any) -> FakeTransport:
        _owner_write(private_source / "gmail-api-token.json", b'{"token":"drift"}')
        return transport

    monkeypatch.setattr(LIVE, "_live_transport", drifting_transport)

    result = LIVE.deliver_daily(candidate)

    assert result["status"] == "succeeded"
    assert transport.send_count == 1
    sent = next(iter(transport.messages.values()))
    assert b"TrainLab" in sent


def test_formal_state_drift_after_preflight_stops_audit_without_resending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)
    formal_sha = {"value": "f" * 64}
    monkeypatch.setattr(
        LIVE,
        "_formal_state_fingerprint",
        lambda _root: {
            "schema_version": "formal_state_fingerprint_v1",
            "sha256": formal_sha["value"],
            "entries": [],
        },
    )
    transport = FakeTransport()

    def drifting_transport(*_args: Any, **_kwargs: Any) -> FakeTransport:
        formal_sha["value"] = "e" * 64
        return transport

    monkeypatch.setattr(LIVE, "_live_transport", drifting_transport)

    with pytest.raises(LIVE.GmailRestError, match="formal_state_changed"):
        LIVE.deliver_daily(candidate)

    assert transport.send_count == 1
    with pytest.raises(LIVE.GmailRestError, match="formal_state_changed"):
        LIVE.deliver_daily(candidate, transport=transport)
    assert transport.send_count == 1


def test_token_refresh_uses_owner_only_atomic_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = tmp_path / "gmail-api-token.json"
    old = b'{"token":"old"}'
    _owner_write(token, old)

    class Credentials:
        token = "old"
        expired = True

        def refresh(self, _request: Any) -> None:
            self.token = "refreshed"
            self.expired = False

        def to_json(self) -> str:
            return '{"token":"refreshed"}'

    client = object.__new__(REST.GmailRestClient)
    client.credentials = Credentials()
    client.refresh_request = object()
    client.token_file = token
    client._token_sha256 = COMMON.sha256_bytes(old)

    client._refresh_token_if_needed()

    assert token.read_bytes() == b'{"token":"refreshed"}'
    assert token.stat().st_mode & 0o777 == 0o600
    assert client.token_sha256 == COMMON.sha256_bytes(token.read_bytes())
    assert not list(tmp_path.glob(f".{token.name}.*"))


@pytest.mark.parametrize("operation", ["lookup", "send", "raw"])
def test_trusted_token_path_change_after_reservation_keeps_single_frozen_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    source = tmp_path / f"source-{operation}"
    candidate = tmp_path / f"candidate-{operation}"
    source.mkdir(mode=0o700)
    candidate.mkdir(mode=0o700)
    token = source / "gmail-api-token.json"
    old = b'{"token":"old"}'
    _owner_write(token, old)
    marker = {
        "action_api_calls": {"1": 0},
        "action_phase_calls": {
            "1": {phase: 0 for phase in REST.READ_PHASES},
        },
        "action_send_calls": {"1": 0},
        "auth_provider_calls": 1,
        "api_calls": 0,
        "send_calls": 0,
    }

    class Response:
        def __init__(self, body: dict[str, Any]) -> None:
            self.status_code = 200
            self._body = body
            self.content = b"{}"

        def json(self) -> dict[str, Any]:
            return self._body

    class CountingSession:
        def __init__(self) -> None:
            self.get_calls = 0
            self.post_calls = 0

        def get(self, url: str, *_args: Any, **_kwargs: Any) -> Response:
            self.get_calls += 1
            if url.endswith("/gmail-1"):
                return Response(
                    {"id": "gmail-1", "raw": COMMON.gmail_raw(b"provider raw")}
                )
            return Response({})

        def post(self, *_args: Any, **_kwargs: Any) -> Response:
            self.post_calls += 1
            return Response({"id": "gmail-1"})

    session = CountingSession()
    monkeypatch.setattr(REST, "SOURCE_ROOT", source)
    real_atomic_json = REST.atomic_json

    def drift_after_reservation(path: Path, payload: dict[str, Any]) -> None:
        real_atomic_json(path, payload)
        if path == candidate / "marker.json" and payload["api_calls"] == 1:
            replacement = token.with_name(".drift.tmp")
            _owner_write(replacement, b'{"token":"drift"}')
            os.replace(replacement, token)

    monkeypatch.setattr(REST, "atomic_json", drift_after_reservation)
    client = REST.GmailRestClient(
        token_file=token,
        candidate_root=candidate,
        marker=marker,
        marker_name="marker.json",
        max_provider_calls=16,
        max_send_calls=1,
        session_factory=lambda _credentials: session,
    )

    if operation == "lookup":
        assert (
            client.list_message("<fixture@trainlab.invalid>", action_id=1, kind="test")
            == []
        )
    elif operation == "send":
        assert client.send(b"fixture", action_id=1) == "gmail-1"
    else:
        assert client.get_raw("gmail-1", action_id=1) == b"provider raw"

    assert session.get_calls + session.post_calls == 1
    assert session.post_calls <= 1
    assert token.read_bytes() == b'{"token":"drift"}'


def test_fake_http_rest_completes_both_messages_with_daily_confirmation_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _parent, private_source = _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)

    class Response:
        def __init__(self, status: int, body: dict[str, Any]) -> None:
            self.status_code = status
            self._body = body
            self.content = b"{}"

        def json(self) -> dict[str, Any]:
            return self._body

    class GmailSession:
        def __init__(self) -> None:
            self.messages: dict[str, bytes] = {}
            self.calls: list[str] = []

        def get(self, url: str, **kwargs: Any) -> Response:
            self.calls.append("GET")
            if url.endswith("/messages"):
                query = str(kwargs["params"]["q"])
                message_id = query.removeprefix("rfc822msgid:")
                matches = [
                    {"id": gmail_id}
                    for gmail_id, raw in self.messages.items()
                    if DELIVERY.actual_message_id(raw) == message_id
                ]
                return Response(200, {"messages": matches} if matches else {})
            gmail_id = url.rsplit("/", 1)[-1]
            raw = self.messages[gmail_id]
            return Response(
                200,
                {"id": gmail_id, "raw": COMMON.gmail_raw(raw)},
            )

        def post(self, _url: str, **kwargs: Any) -> Response:
            self.calls.append("POST")
            gmail_id = f"gmail-{len(self.messages) + 1}"
            self.messages[gmail_id] = COMMON.decode_gmail_raw(kwargs["json"]["raw"])
            return Response(200, {"id": gmail_id})

    session = GmailSession()
    real_client = REST.GmailRestClient
    monkeypatch.setattr(REST, "SOURCE_ROOT", private_source)

    def client_factory(**kwargs: Any) -> Any:
        return real_client(
            **kwargs,
            session_factory=lambda _credentials: session,
        )

    monkeypatch.setattr(LIVE, "GmailRestClient", client_factory)

    daily = LIVE.deliver_daily(candidate)
    assert daily["status"] == "succeeded"
    with pytest.raises(LIVE.GmailRestError, match="confirmation_required"):
        LIVE.deliver_weekly(candidate)
    assert session.calls.count("POST") == 1

    confirmation = LIVE.confirm_daily(candidate, user_confirmed=True)
    assert confirmation["web_confirmed"] is True
    assert confirmation["mobile_confirmed"] is True
    weekly = LIVE.deliver_weekly(candidate)
    assert weekly["status"] == "succeeded"
    LIVE.confirm_weekly(candidate, user_confirmed=True)

    marker = COMMON.read_owner_json(candidate / LIVE.MARKER_NAME)
    assert marker["api_calls"] == 8
    assert marker["send_calls"] == 2
    assert session.calls.count("POST") == 2
    assert len(session.messages) == 2
    assert LIVE.verify_candidate(candidate, final=True)["status"] == "succeeded"


def test_crash_before_send_started_can_retry_with_current_valid_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _parent, private_source = _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)
    _owner_write(private_source / "gmail-api-token.json", b'{"token":"refreshed"}')

    class CrashBeforeSend(FakeTransport):
        def search_rfc822(self, _message_id: str) -> list[str]:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        LIVE.deliver_daily(candidate, transport=CrashBeforeSend())
    run_root = candidate / "gmail-readable/daily"
    assert (run_root / "intent.json").exists()
    assert not (run_root / "send-started.json").exists()

    recovery = FakeTransport()
    result = LIVE.deliver_daily(candidate, transport=recovery)
    assert result["status"] == "succeeded"
    assert recovery.send_count == 1
    action_status, runs = _delivery_ledger(candidate, "daily")
    assert action_status == "succeeded"
    assert [row[1] for row in runs] == ["interrupted", "succeeded"]
    assert [row[2] for row in runs] == [1, 2]
    assert runs[1][3] == "reconcile_gmail"
    assert runs[1][4] == runs[0][0]


def test_crash_after_send_started_recovers_read_only_without_resend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)

    class CrashAfterSend(FakeTransport):
        def send(self, raw: bytes) -> str:
            super().send(raw)
            raise KeyboardInterrupt

    transport = CrashAfterSend()
    with pytest.raises(KeyboardInterrupt):
        LIVE.deliver_daily(candidate, transport=transport)
    assert transport.send_count == 1
    assert (candidate / "gmail-readable/daily/send-started.json").exists()

    result = LIVE.deliver_daily(candidate, transport=transport)
    assert result["status"] == "succeeded"
    assert transport.send_count == 1
    action_status, runs = _delivery_ledger(candidate, "daily")
    assert action_status == "succeeded"
    assert [row[1] for row in runs] == ["interrupted", "succeeded"]
    assert [row[2] for row in runs] == [1, 2]
    assert runs[1][3] == "reconcile_gmail"


@pytest.mark.parametrize("send_response_crashes", [1, 2])
def test_rewritten_message_id_recovers_durable_gmail_id_without_resend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    send_response_crashes: int,
) -> None:
    _parent, private_source = _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)
    session = _RewritingGmailSession()
    _install_rewriting_rest(monkeypatch, private_source, session)
    delivery_globals = LIVE.deliver_once.__globals__
    real_atomic_json = delivery_globals["atomic_json"]
    remaining = {"value": send_response_crashes}

    def crash_send_response(path: Path, payload: dict[str, Any]) -> None:
        if path.name == "send-response.json" and remaining["value"] > 0:
            remaining["value"] -= 1
            raise KeyboardInterrupt
        real_atomic_json(path, payload)

    monkeypatch.setitem(delivery_globals, "atomic_json", crash_send_response)
    for _index in range(send_response_crashes):
        with pytest.raises(KeyboardInterrupt):
            LIVE.deliver_daily(candidate)
    assert session.calls.count("POST") == 1
    assert not (candidate / "gmail-readable/daily/send-response.json").exists()

    delivery_globals["atomic_json"] = real_atomic_json
    result = LIVE.deliver_daily(candidate)

    assert result["status"] == "succeeded"
    assert result["gmail_message_id"] == "gmail-1"
    assert result["actual_rfc822_message_id"] == ("<provider-gmail-1@gmail.invalid>")
    assert session.calls.count("POST") == 1
    action_status, runs = _delivery_ledger(candidate, "daily")
    assert action_status == "succeeded"
    assert [row[1] for row in runs] == [
        *(["interrupted"] * send_response_crashes),
        "succeeded",
    ]
    requested_id = COMMON.read_owner_json(candidate / LIVE.MARKER_NAME)["items"][0][
        "requested_message_id"
    ]
    requested_query = f"rfc822msgid:{requested_id}"
    assert session.queries.count(requested_query) == 1
    assert session.queries[-1] == ("rfc822msgid:<provider-gmail-1@gmail.invalid>")


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "wrong_action",
        "wrong_request",
        "wrong_method",
        "wrong_url",
        "non_2xx",
        "invalid_id",
        "wide_mode",
    ],
)
def test_invalid_durable_send_capture_never_authorizes_resend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    _parent, private_source = _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)
    session = _RewritingGmailSession()
    _install_rewriting_rest(monkeypatch, private_source, session)
    delivery_globals = LIVE.deliver_once.__globals__
    real_atomic_json = delivery_globals["atomic_json"]
    crashed = {"value": False}

    def crash_once(path: Path, payload: dict[str, Any]) -> None:
        if path.name == "send-response.json" and not crashed["value"]:
            crashed["value"] = True
            raise KeyboardInterrupt
        real_atomic_json(path, payload)

    monkeypatch.setitem(delivery_globals, "atomic_json", crash_once)
    with pytest.raises(KeyboardInterrupt):
        LIVE.deliver_daily(candidate)
    delivery_globals["atomic_json"] = real_atomic_json
    capture_root = candidate / "gmail-rest/captures"
    capture = next(capture_root.glob("*-*-send.json"))
    payload = COMMON.read_owner_json(capture)
    if fault == "duplicate":
        COMMON.atomic_json(
            capture_root / f"999-{capture.name.split('-', 1)[1]}", payload
        )
    elif fault == "wrong_action":
        capture.rename(capture_root / capture.name.replace("-1-send", "-999-send"))
    elif fault == "wrong_request":
        payload["request_sha256"] = "0" * 64
        COMMON.atomic_json(capture, payload)
    elif fault == "wrong_method":
        payload["method"] = "GET"
        COMMON.atomic_json(capture, payload)
    elif fault == "wrong_url":
        payload["url"] = "https://example.invalid/messages/send"
        COMMON.atomic_json(capture, payload)
    elif fault == "non_2xx":
        payload["status_code"] = 500
        COMMON.atomic_json(capture, payload)
    elif fault == "invalid_id":
        payload["response"] = {"id": "invalid id"}
        COMMON.atomic_json(capture, payload)
    else:
        capture.chmod(0o644)

    if fault == "wide_mode":
        with pytest.raises(LIVE.GmailRestError, match="artifact_invalid"):
            LIVE.deliver_daily(candidate)
    else:
        result = LIVE.deliver_daily(candidate)
        assert result["status"] in {"blocked", "unknown"}
    assert session.calls.count("POST") == 1
    action_status, runs = _delivery_ledger(candidate, "daily")
    assert action_status == "unknown"
    assert [row[1] for row in runs] == ["interrupted", "blocked"]


def test_durable_gmail_id_raw_mismatch_is_unknown_without_resend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _parent, private_source = _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)
    session = _RewritingGmailSession()
    _install_rewriting_rest(monkeypatch, private_source, session)
    delivery_globals = LIVE.deliver_once.__globals__
    real_atomic_json = delivery_globals["atomic_json"]
    crashed = {"value": False}

    def crash_once(path: Path, payload: dict[str, Any]) -> None:
        if path.name == "send-response.json" and not crashed["value"]:
            crashed["value"] = True
            raise KeyboardInterrupt
        real_atomic_json(path, payload)

    monkeypatch.setitem(delivery_globals, "atomic_json", crash_once)
    with pytest.raises(KeyboardInterrupt):
        LIVE.deliver_daily(candidate)
    delivery_globals["atomic_json"] = real_atomic_json
    session.messages["gmail-1"] = session.messages["gmail-1"].replace(
        b"TrainLab", b"Altered!", 1
    )

    result = LIVE.deliver_daily(candidate)

    assert result["status"] == "blocked"
    assert session.calls.count("POST") == 1
    assert _delivery_ledger(candidate, "daily")[0] == "unknown"


@pytest.mark.parametrize("crash_file", ["send-response.json", "result.json"])
def test_crash_after_provider_response_or_raw_closure_never_resends(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_file: str,
) -> None:
    _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)
    transport = FakeTransport()
    delivery_globals = LIVE.deliver_once.__globals__
    real_atomic_json = delivery_globals["atomic_json"]
    crashed = {"value": False}

    def crash_once(path: Path, payload: dict[str, Any]) -> None:
        if path.name == crash_file and not crashed["value"]:
            crashed["value"] = True
            raise KeyboardInterrupt
        real_atomic_json(path, payload)

    monkeypatch.setitem(delivery_globals, "atomic_json", crash_once)
    with pytest.raises(KeyboardInterrupt):
        LIVE.deliver_daily(candidate, transport=transport)
    assert transport.send_count == 1

    delivery_globals["atomic_json"] = real_atomic_json
    result = LIVE.deliver_daily(candidate, transport=transport)
    assert result["status"] == "succeeded"
    assert transport.send_count == 1
    action_status, runs = _delivery_ledger(candidate, "daily")
    assert action_status == "succeeded"
    assert [row[1] for row in runs] == ["interrupted", "succeeded"]
    assert [row[2] for row in runs] == [1, 2]


def test_external_terminal_status_and_stable_error_families(tmp_path: Path) -> None:
    root = tmp_path / "run"
    root.mkdir(mode=0o700)
    succeeded = {"status": "succeeded", "error_code": None, "send_calls": 1}
    rejected = {
        "status": "blocked",
        "error_code": "gmail_rest_send_rejected",
        "send_calls": 1,
    }
    unknown = {
        "status": "unknown",
        "error_code": "gmail_rest_send_result_unknown",
        "send_calls": 1,
    }

    assert LIVE._terminal_status(succeeded, root) == "succeeded"
    assert LIVE._terminal_status(rejected, root) == "failed_safe"
    assert LIVE._terminal_status(unknown, root) == "unknown"
    assert LIVE._stable_error_code(rejected, "failed_safe", root) == (
        "gmail_live_preflight_failed"
    )
    assert LIVE._stable_error_code(unknown, "unknown", root) == (
        "gmail_live_send_result_unknown"
    )


def test_explicit_send_rejection_is_failed_safe_and_never_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _parent, private_source = _seed_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-candidate"
    LIVE.build_candidate(candidate)
    session = _RejectingGmailSession()
    _install_rewriting_rest(monkeypatch, private_source, session)

    result = LIVE.deliver_daily(candidate)

    assert result["status"] == "blocked"
    assert result["error_code"] == "gmail_rest_send_rejected"
    assert session.calls.count("POST") == 1
    action_status, runs = _delivery_ledger(candidate, "daily")
    assert action_status == "failed_safe"
    assert [row[1] for row in runs] == ["blocked"]
    assert [row[2] for row in runs] == [1]

    session.calls.clear()
    assert LIVE.deliver_daily(candidate) == result
    assert session.calls == []
    assert _delivery_ledger(candidate, "daily") == (action_status, runs)
