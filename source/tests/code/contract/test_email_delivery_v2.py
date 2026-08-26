from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

SOURCE = Path(__file__).resolve().parents[3]


def _load(name: str, relative: str) -> Any:
    path = SOURCE / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


COMMON = _load(
    "trainlab_gmail_common_delivery_v2_test",
    "skills/gmail-sender/scripts/gmail_rest_common.py",
)
DELIVERY = _load(
    "trainlab_gmail_delivery_v2_test",
    "skills/gmail-sender/scripts/gmail_readable_delivery.py",
)


def _request() -> dict[str, Any]:
    data = b"\x89PNG\r\n\x1a\nchart"
    cid = "trainlab-daily-123@trainlab.invalid"
    subject = "TrainLab · 每日训练简报 · 2026-08-21"
    return {
        "recipient": "owner@example.com",
        "subject": subject,
        "plain": "可读纯文本",
        "html": f'<html><head><title>{subject}</title></head><body><h1>{subject}</h1><img src="cid:{cid}"></body></html>',
        "source_sha256": "a" * 64,
        "date_value": datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
        "inline_assets": [
            {
                "role": "daily_activity_heart_rate",
                "cid": cid,
                "filename": "chart.png",
                "media_type": "image/png",
                "width_px": 1248,
                "height_px": 520,
                "sha256": COMMON.sha256_bytes(data),
                "byte_size": len(data),
                "alt": "真实心率变化",
                "data": data,
            }
        ],
    }


class FakeTransport:
    def __init__(
        self,
        *,
        lose_send_response: bool = False,
        raw_override: bytes | None = None,
        search_error: bool = False,
        get_error: bool = False,
        drop_confirmation: bool = False,
        send_error: Exception | None = None,
        invalid_send_id: bool = False,
        rewrite_message_id: bool = False,
    ) -> None:
        self.messages: dict[str, bytes] = {}
        self.actual_ids: dict[str, str] = {}
        self.calls: list[str] = []
        self.lose_send_response = lose_send_response
        self.raw_override = raw_override
        self.search_error = search_error
        self.get_error = get_error
        self.drop_confirmation = drop_confirmation
        self.send_error = send_error
        self.invalid_send_id = invalid_send_id
        self.rewrite_message_id = rewrite_message_id
        self.search_count = 0
        self.send_count = 0

    def search_rfc822(self, message_id: str) -> list[str]:
        self.calls.append("search")
        self.search_count += 1
        if self.search_error:
            raise ConnectionError("search unavailable")
        if self.drop_confirmation and self.search_count >= 3:
            return []
        return [key for key, value in self.actual_ids.items() if value == message_id]

    def send(self, raw: bytes) -> str:
        self.calls.append("send")
        self.send_count += 1
        if self.send_error is not None:
            raise self.send_error
        gmail_id = f"gmail-{self.send_count}"
        stored = raw
        if self.rewrite_message_id:
            requested = DELIVERY.actual_message_id(raw)
            stored = raw.replace(
                f"Message-ID: {requested}\r\n".encode(),
                b"Message-ID: <gmail.rewritten@trainlab.invalid>\r\n",
            )
        self.messages[gmail_id] = stored
        self.actual_ids[gmail_id] = DELIVERY.actual_message_id(stored)
        if self.lose_send_response:
            self.lose_send_response = False
            raise ConnectionError("response lost")
        if self.invalid_send_id:
            return "invalid provider id"
        return gmail_id

    def get_raw(self, gmail_id: str) -> bytes:
        self.calls.append("get")
        if self.get_error:
            raise ConnectionError("raw unavailable")
        if self.raw_override is not None:
            return self.raw_override
        return self.messages[gmail_id]


def test_fake_delivery_sends_once_verifies_raw_and_replays_without_calls(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    root = tmp_path / "delivery"
    first = DELIVERY.deliver_once(root, _request(), transport)
    assert first["status"] == "succeeded"
    assert first["provider_calls"] == 4
    assert transport.calls == ["search", "send", "get", "search"]
    assert transport.send_count == 1
    before = sorted((path.name, path.read_bytes()) for path in root.iterdir())
    transport.calls.clear()
    second = DELIVERY.deliver_once(root, _request(), transport)
    after = sorted((path.name, path.read_bytes()) for path in root.iterdir())
    assert second == first
    assert transport.calls == []
    assert before == after


def test_existing_matching_message_is_reused_without_send(tmp_path: Path) -> None:
    request = _request()
    raw, message_id, _sha = COMMON.deterministic_mime_v2(**request)
    transport = FakeTransport()
    transport.messages["gmail-existing"] = raw
    transport.actual_ids["gmail-existing"] = message_id
    result = DELIVERY.deliver_once(tmp_path / "delivery", request, transport)
    assert result["status"] == "succeeded"
    assert transport.send_count == 0
    assert transport.calls == ["search", "get", "search"]


def test_lost_send_response_becomes_unknown_and_reconcile_never_resends(
    tmp_path: Path,
) -> None:
    request = _request()
    transport = FakeTransport(lose_send_response=True)
    root = tmp_path / "delivery"
    first = DELIVERY.deliver_once(root, request, transport)
    assert first["status"] == "unknown"
    assert transport.send_count == 1
    transport.calls.clear()
    unchanged = DELIVERY.deliver_once(root, request, transport)
    assert unchanged["status"] == "unknown"
    assert transport.calls == []
    recovered = DELIVERY.reconcile_unknown(root, request, transport)
    assert recovered["status"] == "succeeded"
    assert transport.send_count == 1
    assert "send" not in transport.calls


def test_multiple_matches_or_content_mismatch_blocks_without_send(
    tmp_path: Path,
) -> None:
    request = _request()
    raw, message_id, _sha = COMMON.deterministic_mime_v2(**request)
    for mode in ("duplicate", "mismatch"):
        transport = FakeTransport()
        if mode == "duplicate":
            transport.messages = {"a": raw, "b": raw}
            transport.actual_ids = {"a": message_id, "b": message_id}
        else:
            changed = dict(request)
            changed["plain"] = "正文被改变"
            changed_raw, _changed_id, _changed_sha = COMMON.deterministic_mime_v2(
                **changed
            )
            transport.messages = {"a": changed_raw}
            transport.actual_ids = {"a": message_id}
        result = DELIVERY.deliver_once(tmp_path / mode, request, transport)
        assert result["status"] == "blocked"
        assert transport.send_count == 0


def test_post_send_raw_mismatch_records_attempted_send_and_all_provider_calls(
    tmp_path: Path,
) -> None:
    request = _request()
    changed = dict(request)
    changed["plain"] = "正文被改变"
    changed_raw, _message_id, _sha = COMMON.deterministic_mime_v2(**changed)
    transport = FakeTransport(raw_override=changed_raw)

    result = DELIVERY.deliver_once(tmp_path / "post-send-mismatch", request, transport)

    assert result["status"] == "blocked"
    assert result["error_code"] == "gmail_rest_mime_mismatch"
    assert result["send_calls"] == 1
    assert result["provider_calls"] == 3
    assert transport.calls == ["search", "send", "get"]
    assert transport.send_count == 1


def test_provider_failures_publish_closed_receipts_with_accurate_ledgers(
    tmp_path: Path,
) -> None:
    request = _request()
    before_send = FakeTransport(search_error=True)
    before_result = DELIVERY.deliver_once(
        tmp_path / "search-failure", request, before_send
    )
    assert before_result["status"] == "blocked"
    assert before_result["error_code"] == "gmail_rest_provider_unavailable"
    assert before_result["provider_calls"] == 1
    assert before_result["send_calls"] == 0

    after_send = FakeTransport(get_error=True)
    after_result = DELIVERY.deliver_once(
        tmp_path / "post-send-get-failure", request, after_send
    )
    assert after_result["status"] == "unknown"
    assert after_result["error_code"] == "gmail_rest_send_result_unknown"
    assert after_result["provider_calls"] == 3
    assert after_result["send_calls"] == 1
    assert after_send.calls == ["search", "send", "get"]


@pytest.mark.parametrize("failure", ["raw_mismatch", "get_error"])
def test_unknown_reconciliation_failure_persists_read_only_attempt_ledger(
    tmp_path: Path,
    failure: str,
) -> None:
    request = _request()
    transport = FakeTransport(lose_send_response=True)
    root = tmp_path / failure
    first = DELIVERY.deliver_once(root, request, transport)
    assert first["status"] == "unknown"
    assert first["send_calls"] == 1

    if failure == "raw_mismatch":
        changed = dict(request)
        changed["plain"] = "正文被改变"
        transport.raw_override = COMMON.deterministic_mime_v2(**changed)[0]
    else:
        transport.get_error = True
    transport.calls.clear()
    result = DELIVERY.reconcile_unknown(root, request, transport)

    assert result["status"] == ("blocked" if failure == "raw_mismatch" else "unknown")
    assert result["error_code"] == (
        "gmail_rest_mime_mismatch"
        if failure == "raw_mismatch"
        else "gmail_rest_provider_unavailable"
    )
    assert result["provider_calls"] == 2
    assert result["send_calls"] == 0
    assert transport.calls == ["search", "get"]
    assert (root / "reconciliation-result.json").is_file()
    assert transport.send_count == 1


def test_unknown_reconciliation_confirmation_mismatch_is_persisted(
    tmp_path: Path,
) -> None:
    request = _request()
    transport = FakeTransport(lose_send_response=True)
    root = tmp_path / "confirmation-mismatch"
    assert DELIVERY.deliver_once(root, request, transport)["status"] == "unknown"
    transport.drop_confirmation = True
    transport.calls.clear()

    result = DELIVERY.reconcile_unknown(root, request, transport)

    assert result["status"] == "blocked"
    assert result["error_code"] == "gmail_rest_confirmation_mismatch"
    assert result["provider_calls"] == 3
    assert result["send_calls"] == 0
    assert transport.calls == ["search", "get", "search"]
    assert (root / "reconciliation-result.json").is_file()
    assert transport.send_count == 1


def test_explicit_send_error_and_invalid_provider_id_keep_specific_outcomes(
    tmp_path: Path,
) -> None:
    request = _request()
    auth = FakeTransport(send_error=DELIVERY.GmailRestError("gmail_rest_auth_invalid"))
    auth_result = DELIVERY.deliver_once(tmp_path / "auth", request, auth)
    assert auth_result["status"] == "blocked"
    assert auth_result["error_code"] == "gmail_rest_auth_invalid"
    assert auth_result["provider_calls"] == 2
    assert auth_result["send_calls"] == 1

    invalid = FakeTransport(invalid_send_id=True)
    invalid_result = DELIVERY.deliver_once(tmp_path / "invalid-id", request, invalid)
    assert invalid_result["status"] == "unknown"
    assert invalid_result["error_code"] == "gmail_rest_provider_message_id_invalid"
    assert invalid_result["provider_calls"] == 2
    assert invalid_result["send_calls"] == 1


def test_reconciliation_prefers_persisted_gmail_id_when_message_id_is_rewritten(
    tmp_path: Path,
) -> None:
    request = _request()
    transport = FakeTransport(rewrite_message_id=True, get_error=True)
    root = tmp_path / "rewritten-id"
    first = DELIVERY.deliver_once(root, request, transport)
    assert first["status"] == "unknown"
    assert first["send_calls"] == 1
    assert (root / "send-response.json").is_file()

    transport.get_error = False
    transport.calls.clear()
    recovered = DELIVERY.reconcile_unknown(root, request, transport)

    assert recovered["status"] == "succeeded"
    assert recovered["actual_rfc822_message_id"] == (
        "<gmail.rewritten@trainlab.invalid>"
    )
    assert recovered["provider_calls"] == 2
    assert recovered["send_calls"] == 0
    assert transport.calls == ["get", "search"]
    assert transport.send_count == 1


def test_orphan_intent_repairs_mime_before_any_provider_call(tmp_path: Path) -> None:
    request = _request()
    root = tmp_path / "orphan-intent"
    root.mkdir(mode=0o700)
    raw, requested_id, mime_sha = COMMON.deterministic_mime_v2(**request)
    intent = {
        "schema_version": "gmail_readable_delivery_intent_v1",
        "request_sha256": DELIVERY._request_sha(request),
        "requested_message_id": requested_id,
        "mime_sha256": mime_sha,
        "send_limit": 1,
    }
    COMMON.atomic_json(root / "intent.json", intent)
    transport = FakeTransport()

    result = DELIVERY.deliver_once(root, request, transport)

    assert result["status"] == "succeeded"
    assert (root / "message.eml").read_bytes() == raw
    assert transport.calls == ["search", "send", "get", "search"]


def test_message_write_failure_stops_before_intent_and_retries_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    root = tmp_path / "message-write-failure"
    transport = FakeTransport()
    original = DELIVERY.atomic_write
    failed = False

    def fail_message_once(path: Path, payload: bytes) -> None:
        nonlocal failed
        if path.name == "message.eml" and not failed:
            failed = True
            raise OSError("disk unavailable")
        original(path, payload)

    monkeypatch.setattr(DELIVERY, "atomic_write", fail_message_once)
    with pytest.raises(OSError, match="disk unavailable"):
        DELIVERY.deliver_once(root, request, transport)
    assert transport.calls == []
    assert not (root / "intent.json").exists()
    assert not (root / "message.eml").exists()

    result = DELIVERY.deliver_once(root, request, transport)
    assert result["status"] == "succeeded"
    assert (root / "intent.json").is_file()
    assert (root / "message.eml").is_file()


def test_started_attempt_without_result_recovers_read_only_and_never_resends(
    tmp_path: Path,
) -> None:
    request = _request()
    transport = FakeTransport(lose_send_response=True)
    root = tmp_path / "started-recovery"
    assert DELIVERY.deliver_once(root, request, transport)["status"] == "unknown"
    (root / "result.json").unlink()
    transport.calls.clear()

    recovered = DELIVERY.deliver_once(root, request, transport)

    assert recovered["status"] == "succeeded"
    assert recovered["send_calls"] == 0
    assert transport.calls == ["search", "get", "search"]
    assert transport.send_count == 1


def test_offline_preview_packages_and_replays_exact_cid_mime(tmp_path: Path) -> None:
    preview = tmp_path / "preview"
    preview.mkdir(mode=0o700)
    assets_dir = preview / "assets"
    assets_dir.mkdir(mode=0o700)
    request = _request()
    asset = request["inline_assets"][0]
    asset_path = assets_dir / asset["filename"]
    asset_path.write_bytes(asset["data"])
    asset_path.chmod(0o600)
    render = {
        "schema_version": "daily_email_render_v2",
        "kind": "daily",
        "subject": request["subject"],
        "text": request["plain"],
        "html": request["html"],
        "view_sha256": request["source_sha256"],
        "asset_manifest": {
            "schema_version": "email_inline_asset_manifest_v1",
            "assets": [{key: value for key, value in asset.items() if key != "data"}],
        },
        "provider_calls": 0,
    }
    COMMON.atomic_json(preview / "render.json", render)
    output = tmp_path / "mime-previews" / "daily"
    first = DELIVERY.package_offline_preview(preview, output, request["date_value"])
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    second = DELIVERY.package_offline_preview(preview, output, request["date_value"])
    assert first == second
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before
    assert first["requested_message_id"] == first["actual_message_id"]
    assert first["provider_calls"] == 0
    assert first["external_actions"] == 0
    assert DELIVERY.verify_offline_preview(output) == first
    assert (output.parent.stat().st_mode & 0o777) == 0o700
    render["text"] = "drifted"
    COMMON.atomic_json(preview / "render.json", render)
    with pytest.raises(DELIVERY.GmailRestError, match="gmail_rest_request_changed"):
        DELIVERY.package_offline_preview(preview, output, request["date_value"])
