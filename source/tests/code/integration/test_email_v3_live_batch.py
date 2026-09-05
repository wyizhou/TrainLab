from __future__ import annotations

import importlib.util
import os
import sys
from contextlib import nullcontext
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
    "trainlab_email_v3_live_common_test",
    "skills/gmail-sender/scripts/gmail_rest_common.py",
)
DELIVERY = _load(
    "trainlab_email_v3_live_delivery_test",
    "skills/gmail-sender/scripts/gmail_readable_delivery.py",
)
LIVE = _load(
    "trainlab_email_v3_live_batch_test",
    "skills/gmail-sender/scripts/gmail_readable_live.py",
)


def _owner_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    path.write_bytes(payload)
    path.chmod(0o600)


def _render(kind: str, period_start: str, period_end: str) -> dict[str, Any]:
    if kind == "daily":
        subject = f"TrainLab · 每日训练简报 · {period_end}"
    else:
        subject = f"TrainLab · 每周总结 · {period_start}~{period_end}"
    return {
        "schema_version": f"{kind}_email_render_v3",
        "kind": kind,
        "subject": subject,
        "text": f"{subject}\n合成可读内容",
        "html": (
            f"<html><head><title>{subject}</title></head>"
            f"<body><h1>{subject}</h1><p>合成可读内容</p></body></html>"
        ),
        "view_sha256": ("a" if kind == "daily" else "b") * 64,
        "asset_manifest": {
            "schema_version": "email_inline_asset_manifest_v1",
            "assets": [],
        },
        "provider_calls": 0,
    }


def _seed_v3_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    parent = tmp_path / "r06"
    previews = parent / "previews"
    previews.mkdir(parents=True, mode=0o700)
    database = init_database(parent / "source/state/trainlab.db")
    connection = connect(database)
    declared: list[dict[str, Any]] = []
    items = []
    periods = [
        ("daily", f"2026-08-{day:02d}", f"2026-08-{day:02d}") for day in range(12, 19)
    ] + [("weekly", "2026-08-12", "2026-08-18")]
    for ordinal, (kind, start, end) in enumerate(periods, start=1):
        key = f"daily-{end}" if kind == "daily" else f"weekly-{start}--{end}"
        preview = previews / key
        preview.mkdir(mode=0o700)
        render = _render(kind, start, end)
        files = {
            "view.json": b'{"fixture":true}\n',
            "render.json": (COMMON.canonical_json(render) + "\n").encode(),
            "report.html": render["html"].encode(),
            "report.txt": render["text"].encode(),
            "browser-preview.html": render["html"].encode(),
        }
        for name, payload in files.items():
            path = preview / name
            _owner_write(path, payload)
            declared.append(
                {
                    "path": path.relative_to(parent).as_posix(),
                    "sha256": COMMON.sha256_bytes(payload),
                    "byte_size": len(payload),
                }
            )
        run_id = begin_run(
            connection,
            run_key=f"m11-v3-live-{key}",
            workflow_key=f"m11:v3:live:{key}",
            dedupe_key=f"m11-v3-live-{key}",
            skill_name="training-report-publisher",
            operation="render_daily" if kind == "daily" else "render_weekly",
            trigger_kind="manual",
            input_manifest={"fixture": key},
        )
        output_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind="email_render",
            logical_key=f"m11:v3:live:{key}:render",
            schema_name=f"{kind}_email_render_v3",
            schema_version="3",
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
                preview_name=key,
                output_id=output_id,
                output_sha256=output_sha,
                render_sha256=COMMON.sha256_file(preview / "render.json"),
                period_start=start,
                period_end=end,
                date_value=datetime.fromisoformat(f"{end}T12:00:00").replace(
                    tzinfo=ZoneInfo("Asia/Hong_Kong")
                ),
                item_key=key,
                render_schema_name=f"{kind}_email_render_v3",
            )
        )
    connection.close()
    receipt = {
        "schema_version": "m11_v3_candidate_receipt_v1",
        "status": "succeeded",
        "declared_files": sorted(declared, key=lambda item: str(item["path"])),
    }
    _owner_write(
        parent / "build-receipt.json",
        (COMMON.canonical_json(receipt) + "\n").encode(),
    )

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
    settings = {
        "BATCH_ID": "m11-v3-live-batch",
        "WORKFLOW_KEY": "m11:v3:live:2026-08-12--2026-08-18",
        "TARGET_KEY_PREFIX": "m11:v3:live",
        "MARKER_NAME": "m11-v3-live-batch.json",
        "MARKER_SCHEMA_NAME": "m11_v3_live_batch_candidate_v1",
        "MARKER_SCHEMA_VERSION": "m11_v3_live_batch_candidate_v1",
        "FROZEN_R03_ROOT": parent,
        "FROZEN_PARENT_DATABASE_SHA256": COMMON.sha256_file(database),
        "FROZEN_BUILD_RECEIPT_SHA256": COMMON.sha256_file(
            parent / "build-receipt.json"
        ),
        "FROZEN_ITEMS": tuple(items),
        "PRIVATE_SOURCE_ROOT": private_source,
        "FORMAL_SOURCE_ROOT": formal,
        "MAX_DELIVERY_API_CALLS": 128,
        "MAX_PROVIDER_CALLS_WITH_AUTH": 129,
        "MAX_SEND_CALLS": 8,
        "REQUIRE_MANUAL_CONFIRMATION": False,
        "STRICT_SERIAL": True,
        "PREVIEW_MANIFEST_MODE": "candidate_build_receipt",
        "APPROVAL_SOURCE_REF": "m11-v3-live:user-approved-A-017",
        "APPROVAL_REASON_CODE": "m11_v3_eight_email_batch_approved",
    }
    for name, value in settings.items():
        monkeypatch.setattr(LIVE, name, value)
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
    def __init__(self, *, lose_on_send: int | None = None) -> None:
        self.messages: dict[str, bytes] = {}
        self.actual_ids: dict[str, str] = {}
        self.calls: list[str] = []
        self.send_count = 0
        self.lose_on_send = lose_on_send

    def search_rfc822(self, message_id: str) -> list[str]:
        self.calls.append("search")
        return [key for key, value in self.actual_ids.items() if value == message_id]

    def send(self, raw: bytes) -> str:
        self.calls.append("send")
        self.send_count += 1
        gmail_id = f"gmail-{self.send_count}"
        self.messages[gmail_id] = raw
        self.actual_ids[gmail_id] = DELIVERY.actual_message_id(raw)
        if self.lose_on_send == self.send_count:
            raise ConnectionError("lost provider response")
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


class _GmailHttpSession:
    def __init__(self) -> None:
        self.messages: dict[str, bytes] = {}
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> _HttpResponse:
        self.calls.append("GET")
        if url.endswith("/messages"):
            query = str(kwargs["params"]["q"])
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
        self.messages[gmail_id] = COMMON.decode_gmail_raw(kwargs["json"]["raw"])
        return _HttpResponse(200, {"id": gmail_id})


def _install_fake_rest(
    monkeypatch: pytest.MonkeyPatch, private_source: Path, session: _GmailHttpSession
) -> None:
    real_client = LIVE.GmailRestClient
    monkeypatch.setitem(real_client.__init__.__globals__, "SOURCE_ROOT", private_source)

    def client_factory(**kwargs: Any) -> Any:
        return real_client(
            **kwargs,
            session_factory=lambda _credentials: session,
        )

    monkeypatch.setattr(LIVE, "GmailRestClient", client_factory)


def _statuses(candidate: Path) -> list[tuple[str, str, int]]:
    marker = COMMON.read_owner_json(candidate / LIVE.MARKER_NAME)
    placeholders = ",".join("?" for _ in marker["action_ids"])
    connection = connect(
        candidate / "source/state/trainlab.db", read_only=True, immutable=True
    )
    try:
        rows = connection.execute(
            f"SELECT status,attempt_count FROM external_actions "
            f"WHERE id IN ({placeholders}) ORDER BY id",
            tuple(marker["action_ids"]),
        ).fetchall()
    finally:
        connection.close()
    return [
        (str(item["item_key"]), str(rows[index][0]), int(rows[index][1]))
        for index, item in enumerate(marker["items"])
    ]


def test_v3_builds_exact_ordered_eight_without_private_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_v3_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-v3"

    receipt = LIVE.build_candidate(candidate)

    assert receipt == {
        "schema_version": "m11_live_canary_build_receipt_v1",
        "status": "succeeded",
        "candidate_root": str(candidate),
        "actions": 8,
        "provider_calls": 0,
        "send_calls": 0,
    }
    marker = COMMON.read_owner_json(candidate / LIVE.MARKER_NAME)
    assert marker["schema_version"] == "m11_v3_live_batch_candidate_v1"
    assert marker["strict_serial"] is True
    assert marker["authorization_rule"] == "A-017"
    assert [item["item_key"] for item in marker["items"]] == [
        *(f"daily-2026-08-{day:02d}" for day in range(12, 19)),
        "weekly-2026-08-12--2026-08-18",
    ]
    assert [item["kind"] for item in marker["items"]] == [
        *("daily" for _ in range(7)),
        "weekly",
    ]
    assert _statuses(candidate) == [
        (item["item_key"], "prepared", 0) for item in marker["items"]
    ]
    assert not list(candidate.rglob("email.json"))
    assert not list(candidate.rglob("gmail-api-token.json"))
    assert not list(candidate.rglob("gcp-oauth.keys.json"))
    assert LIVE.verify_candidate(candidate)["status"] == "succeeded"


def test_v3_strict_serial_delivery_and_success_replay_are_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _parent, private_source = _seed_v3_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-v3"
    LIVE.build_candidate(candidate)
    preflight_transport = FakeTransport()

    with pytest.raises(LIVE.GmailRestError, match="prior_action_not_succeeded"):
        LIVE._deliver(candidate, "daily-2026-08-13", transport=preflight_transport)
    assert preflight_transport.calls == []
    assert _statuses(candidate)[1] == ("daily-2026-08-13", "prepared", 0)

    session = _GmailHttpSession()
    _install_fake_rest(monkeypatch, private_source, session)
    result = LIVE.deliver_batch(candidate)
    assert result["status"] == "succeeded"
    assert result["completed_actions"] == 8
    assert session.calls.count("POST") == 8
    assert [status for _key, status, _attempts in _statuses(candidate)] == [
        "succeeded"
    ] * 8
    assert LIVE.verify_candidate(candidate, final=True)["send_calls"] == 8

    before = LIVE.logical_snapshot(candidate)
    session.calls.clear()
    replay = LIVE.deliver_batch(candidate)
    assert replay["status"] == "succeeded"
    assert replay["completed_actions"] == 8
    assert session.calls == []
    assert LIVE.logical_snapshot(candidate) == before


def test_v3_unknown_halts_batch_and_never_claims_remaining_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_v3_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-v3"
    LIVE.build_candidate(candidate)
    transport = FakeTransport(lose_on_send=4)

    result = LIVE.deliver_batch(candidate, transport=transport)

    assert result["status"] == "unknown"
    assert result["completed_actions"] == 3
    assert result["stopped_item_key"] == "daily-2026-08-15"
    assert transport.send_count == 4
    states = _statuses(candidate)
    assert [state[1] for state in states] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "unknown",
        "prepared",
        "prepared",
        "prepared",
        "prepared",
    ]
    transport.calls.clear()
    assert LIVE.deliver_batch(candidate, transport=transport) == result
    assert transport.calls == []
    assert transport.send_count == 4


def test_v3_root_manifest_or_render_drift_is_rejected_before_candidate_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, _private = _seed_v3_parent(tmp_path, monkeypatch)
    render = parent / "previews/daily-2026-08-12/render.json"
    render.chmod(0o600)
    render.write_bytes(render.read_bytes() + b" ")

    with pytest.raises(LIVE.GmailRestError, match="preview_invalid|render_changed"):
        LIVE.build_candidate(tmp_path / "live-v3")


def test_v3_marker_rejects_reordered_or_duplicate_item_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_v3_parent(tmp_path, monkeypatch)
    candidate = tmp_path / "live-v3"
    LIVE.build_candidate(candidate)
    marker_path = candidate / LIVE.MARKER_NAME
    marker = COMMON.read_owner_json(marker_path)
    marker["items"][1]["item_key"] = marker["items"][0]["item_key"]
    COMMON.atomic_json(marker_path, marker)

    with pytest.raises(LIVE.GmailRestError, match="candidate_invalid"):
        LIVE.verify_candidate(candidate)


def test_v3_policy_activation_keeps_frozen_dates_and_no_dynamic_cli_arguments() -> None:
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
        "MAX_DELIVERY_API_CALLS",
        "MAX_PROVIDER_CALLS_WITH_AUTH",
        "MAX_SEND_CALLS",
        "REQUIRE_MANUAL_CONFIRMATION",
        "STRICT_SERIAL",
        "PREVIEW_MANIFEST_MODE",
        "APPROVAL_SOURCE_REF",
        "APPROVAL_REASON_CODE",
    )
    originals = {name: getattr(LIVE, name) for name in names}
    try:
        LIVE._activate_v3_batch_policy()
        assert [item.item_key for item in LIVE.FROZEN_ITEMS] == [
            *(f"daily-2026-08-{day:02d}" for day in range(12, 19)),
            "weekly-2026-08-12--2026-08-18",
        ]
        assert len(LIVE.FROZEN_ITEMS) == 8
        assert LIVE.MAX_SEND_CALLS == 8
        assert LIVE.MAX_DELIVERY_API_CALLS == 128
        parsed = LIVE.parser().parse_args(
            ["build-v3-batch", "--candidate-root", "/private/tmp/fixture"]
        )
        assert vars(parsed) == {
            "command": "build-v3-batch",
            "candidate_root": Path("/private/tmp/fixture"),
        }
    finally:
        for name, value in originals.items():
            setattr(LIVE, name, value)
