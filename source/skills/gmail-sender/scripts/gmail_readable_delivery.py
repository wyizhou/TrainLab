#!/usr/bin/env python3
"""Generic send-once/reconcile controller for readable CID email.

M11 exercises this controller only with a fake transport.  It deliberately has
no OAuth or network client entrypoint; a later, separately approved canary must
bind it to the already validated Gmail REST client.
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from gmail_rest_common import (  # noqa: E402
    GmailRestError,
    atomic_json,
    atomic_write,
    canonical_json,
    deterministic_mime_v2,
    private_directory,
    read_owner_json,
    require_gmail_message_id,
    require_owner_directory,
    require_owner_file,
    sha256_bytes,
    sha256_text,
    validate_schema,
    verify_mime_v2_with_actual_message_id,
)

from skills._shared.scripts.schema_validation import require_valid_payload  # noqa: E402


class ReadableMailTransport(Protocol):
    def search_rfc822(self, message_id: str) -> list[str]: ...

    def send(self, raw: bytes) -> str: ...

    def get_raw(self, gmail_id: str) -> bytes: ...


@runtime_checkable
class DurableSendRecoveryTransport(Protocol):
    """Optional local-only recovery for a durably captured send response."""

    def recover_sent_gmail_id(self, raw_sha256: str) -> str | None: ...


@dataclass
class _ProviderLedger:
    provider_calls: int = 0
    send_calls: int = 0


class _ProviderUnavailable(RuntimeError):
    """A transport call failed before a trustworthy response was available."""


def _search(
    transport: ReadableMailTransport,
    message_id: str,
    ledger: _ProviderLedger,
) -> list[str]:
    ledger.provider_calls += 1
    try:
        return transport.search_rfc822(message_id)
    except GmailRestError:
        raise
    except Exception as exc:
        raise _ProviderUnavailable from exc


def _send(
    transport: ReadableMailTransport,
    raw: bytes,
    ledger: _ProviderLedger,
) -> str:
    ledger.provider_calls += 1
    ledger.send_calls += 1
    try:
        return transport.send(raw)
    except GmailRestError:
        raise
    except Exception as exc:
        raise _ProviderUnavailable from exc


def _get_raw(
    transport: ReadableMailTransport,
    gmail_id: str,
    ledger: _ProviderLedger,
) -> bytes:
    ledger.provider_calls += 1
    try:
        return transport.get_raw(gmail_id)
    except GmailRestError:
        raise
    except Exception as exc:
        raise _ProviderUnavailable from exc


def actual_message_id(raw: bytes) -> str:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    values = message.get_all("message-id", [])
    if len(values) != 1:
        raise GmailRestError("gmail_rest_mime_mismatch")
    return str(values[0])


def _root(path: Path) -> Path:
    if path.exists():
        return require_owner_directory(path)
    return private_directory(path)


def _ensure_private_parent(path: Path) -> None:
    parent = Path(os.path.abspath(path.parent))
    if not parent.exists():
        parent.mkdir(mode=0o700)
    metadata = parent.lstat()
    if (
        parent.is_symlink()
        or not parent.is_dir()
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise GmailRestError("gmail_rest_owner_directory_required")


def _asset_dicts(request: dict[str, Any]) -> list[dict[str, Any]]:
    assets = request.get("inline_assets")
    if not isinstance(assets, list):
        raise GmailRestError("gmail_rest_inline_asset_invalid")
    return [dict(item) for item in assets if isinstance(item, dict)]


def _request_sha(request: dict[str, Any]) -> str:
    safe = dict(request)
    safe["date_value"] = str(request.get("date_value"))
    safe["inline_assets"] = [
        {key: value for key, value in item.items() if key != "data"}
        for item in _asset_dicts(request)
    ]
    return sha256_text(canonical_json(safe))


def _receipt(
    *,
    status: str,
    request_sha256: str,
    requested_message_id: str,
    mime_sha256: str,
    provider_calls: int,
    send_calls: int,
    error_code: str | None = None,
    gmail_message_id: str | None = None,
    actual_rfc822_message_id: str | None = None,
) -> dict[str, Any]:
    value = {
        "schema_version": "gmail_readable_delivery_receipt_v1",
        "status": status,
        "error_code": error_code,
        "request_sha256": request_sha256,
        "requested_message_id": requested_message_id,
        "mime_sha256": mime_sha256,
        "gmail_message_id": gmail_message_id,
        "actual_rfc822_message_id": actual_rfc822_message_id,
        "provider_calls": provider_calls,
        "send_calls": send_calls,
    }
    validate_schema(value, "gmail_readable_delivery_receipt_v1")
    return value


def _verify_remote(
    transport: ReadableMailTransport,
    gmail_id: str,
    request: dict[str, Any],
    ledger: _ProviderLedger,
) -> str:
    raw = _get_raw(transport, gmail_id, ledger)
    actual_id = verify_mime_v2_with_actual_message_id(
        raw,
        recipient=str(request["recipient"]),
        subject=str(request["subject"]),
        plain=str(request["plain"]),
        html=str(request["html"]),
        inline_assets=_asset_dicts(request),
    )
    matches = _search(transport, actual_id, ledger)
    if matches != [gmail_id]:
        raise GmailRestError("gmail_rest_confirmation_mismatch")
    return actual_id


def _existing_result(root: Path, request_sha: str) -> dict[str, Any] | None:
    for name in ("reconciliation-result.json", "result.json"):
        path = root / name
        if not path.exists():
            continue
        value = read_owner_json(path)
        validate_schema(value, "gmail_readable_delivery_receipt_v1")
        if value.get("request_sha256") != request_sha:
            raise GmailRestError("gmail_rest_request_changed")
        return value
    return None


def _ensure_local_evidence(
    root: Path,
    intent: dict[str, Any],
    raw: bytes,
    mime_sha: str,
) -> None:
    intent_path = root / "intent.json"
    if intent_path.exists() and read_owner_json(intent_path) != intent:
        raise GmailRestError("gmail_rest_request_changed")
    message_path = root / "message.eml"
    if message_path.exists():
        if sha256_bytes(require_owner_file(message_path).read_bytes()) != mime_sha:
            raise GmailRestError("gmail_rest_mime_changed")
    else:
        atomic_write(message_path, raw)
    if not intent_path.exists():
        atomic_json(intent_path, intent)


def _send_started_payload(
    request_sha: str,
    requested_id: str,
    mime_sha: str,
) -> dict[str, Any]:
    return {
        "schema_version": "gmail_readable_send_started_v1",
        "request_sha256": request_sha,
        "requested_message_id": requested_id,
        "mime_sha256": mime_sha,
    }


def _known_gmail_id(
    root: Path,
    request_sha: str,
    mime_sha: str,
    transport: ReadableMailTransport,
) -> str | None:
    response_path = root / "send-response.json"
    if response_path.exists():
        response = read_owner_json(response_path)
        if (
            set(response)
            != {
                "schema_version",
                "request_sha256",
                "gmail_message_id",
            }
            or response.get("schema_version") != "gmail_readable_send_response_v1"
        ):
            raise GmailRestError("gmail_rest_send_response_invalid")
        if response.get("request_sha256") != request_sha:
            raise GmailRestError("gmail_rest_request_changed")
        return require_gmail_message_id(response.get("gmail_message_id"))
    if not isinstance(transport, DurableSendRecoveryTransport):
        return None
    gmail_id = transport.recover_sent_gmail_id(mime_sha)
    if gmail_id is None:
        return None
    gmail_id = require_gmail_message_id(gmail_id)
    atomic_json(
        response_path,
        {
            "schema_version": "gmail_readable_send_response_v1",
            "request_sha256": request_sha,
            "gmail_message_id": gmail_id,
        },
    )
    return gmail_id


def _read_only_reconciliation(
    root: Path,
    request: dict[str, Any],
    transport: ReadableMailTransport,
    *,
    request_sha: str,
    requested_id: str,
    mime_sha: str,
) -> dict[str, Any]:
    ledger = _ProviderLedger()
    try:
        gmail_id = _known_gmail_id(
            root,
            request_sha,
            mime_sha,
            transport,
        )
        if gmail_id is None:
            matches = _search(transport, requested_id, ledger)
            if len(matches) != 1:
                return _receipt(
                    status="unknown" if not matches else "blocked",
                    error_code=(
                        "gmail_rest_send_result_unknown"
                        if not matches
                        else "gmail_rest_multiple_matches"
                    ),
                    request_sha256=request_sha,
                    requested_message_id=requested_id,
                    mime_sha256=mime_sha,
                    provider_calls=ledger.provider_calls,
                    send_calls=ledger.send_calls,
                )
            gmail_id = require_gmail_message_id(matches[0])
        actual_id = _verify_remote(transport, gmail_id, request, ledger)
        return _receipt(
            status="succeeded",
            request_sha256=request_sha,
            requested_message_id=requested_id,
            mime_sha256=mime_sha,
            gmail_message_id=gmail_id,
            actual_rfc822_message_id=actual_id,
            provider_calls=ledger.provider_calls,
            send_calls=ledger.send_calls,
        )
    except GmailRestError as exc:
        return _receipt(
            status="blocked",
            error_code=str(exc),
            request_sha256=request_sha,
            requested_message_id=requested_id,
            mime_sha256=mime_sha,
            provider_calls=ledger.provider_calls,
            send_calls=ledger.send_calls,
        )
    except _ProviderUnavailable:
        return _receipt(
            status="unknown",
            error_code="gmail_rest_provider_unavailable",
            request_sha256=request_sha,
            requested_message_id=requested_id,
            mime_sha256=mime_sha,
            provider_calls=ledger.provider_calls,
            send_calls=ledger.send_calls,
        )


def deliver_once(
    run_root: Path,
    request: dict[str, Any],
    transport: ReadableMailTransport,
) -> dict[str, Any]:
    """Send once, or safely reuse a matching remote message."""

    root = _root(run_root)
    request_sha = _request_sha(request)
    raw, requested_id, mime_sha = deterministic_mime_v2(**request)
    intent = {
        "schema_version": "gmail_readable_delivery_intent_v1",
        "request_sha256": request_sha,
        "requested_message_id": requested_id,
        "mime_sha256": mime_sha,
        "send_limit": 1,
    }
    _ensure_local_evidence(root, intent, raw, mime_sha)
    existing = _existing_result(root, request_sha)
    if existing is not None:
        return existing
    started = _send_started_payload(request_sha, requested_id, mime_sha)
    started_path = root / "send-started.json"
    if started_path.exists():
        if read_owner_json(started_path) != started:
            raise GmailRestError("gmail_rest_request_changed")
        result = _read_only_reconciliation(
            root,
            request,
            transport,
            request_sha=request_sha,
            requested_id=requested_id,
            mime_sha=mime_sha,
        )
        atomic_json(root / "result.json", result)
        return result
    if (root / "send-response.json").exists():
        raise GmailRestError("gmail_rest_send_response_invalid")
    ledger = _ProviderLedger()
    try:
        matches = _search(transport, requested_id, ledger)
        if len(matches) > 1:
            raise GmailRestError("gmail_rest_multiple_matches")
        if len(matches) == 1:
            gmail_id = require_gmail_message_id(matches[0])
            actual_id = _verify_remote(transport, gmail_id, request, ledger)
            result = _receipt(
                status="succeeded",
                request_sha256=request_sha,
                requested_message_id=requested_id,
                mime_sha256=mime_sha,
                gmail_message_id=gmail_id,
                actual_rfc822_message_id=actual_id,
                provider_calls=ledger.provider_calls,
                send_calls=ledger.send_calls,
            )
            atomic_json(root / "result.json", result)
            return result
        atomic_json(started_path, started)
        try:
            provider_id = _send(transport, raw, ledger)
        except GmailRestError as exc:
            result = _receipt(
                status="blocked",
                error_code=str(exc),
                request_sha256=request_sha,
                requested_message_id=requested_id,
                mime_sha256=mime_sha,
                provider_calls=ledger.provider_calls,
                send_calls=ledger.send_calls,
            )
            atomic_json(root / "result.json", result)
            return result
        except _ProviderUnavailable:
            result = _receipt(
                status="unknown",
                error_code="gmail_rest_send_result_unknown",
                request_sha256=request_sha,
                requested_message_id=requested_id,
                mime_sha256=mime_sha,
                provider_calls=ledger.provider_calls,
                send_calls=ledger.send_calls,
            )
            atomic_json(root / "result.json", result)
            return result
        try:
            gmail_id = require_gmail_message_id(provider_id)
        except GmailRestError as exc:
            result = _receipt(
                status="unknown",
                error_code=str(exc),
                request_sha256=request_sha,
                requested_message_id=requested_id,
                mime_sha256=mime_sha,
                provider_calls=ledger.provider_calls,
                send_calls=ledger.send_calls,
            )
            atomic_json(root / "result.json", result)
            return result
        atomic_json(
            root / "send-response.json",
            {
                "schema_version": "gmail_readable_send_response_v1",
                "request_sha256": request_sha,
                "gmail_message_id": gmail_id,
            },
        )
        actual_id = _verify_remote(transport, gmail_id, request, ledger)
        result = _receipt(
            status="succeeded",
            request_sha256=request_sha,
            requested_message_id=requested_id,
            mime_sha256=mime_sha,
            gmail_message_id=gmail_id,
            actual_rfc822_message_id=actual_id,
            provider_calls=ledger.provider_calls,
            send_calls=ledger.send_calls,
        )
    except GmailRestError as exc:
        result = _receipt(
            status="blocked",
            error_code=str(exc),
            request_sha256=request_sha,
            requested_message_id=requested_id,
            mime_sha256=mime_sha,
            provider_calls=ledger.provider_calls,
            send_calls=ledger.send_calls,
        )
    except _ProviderUnavailable:
        result = _receipt(
            status="unknown" if ledger.send_calls else "blocked",
            error_code=(
                "gmail_rest_send_result_unknown"
                if ledger.send_calls
                else "gmail_rest_provider_unavailable"
            ),
            request_sha256=request_sha,
            requested_message_id=requested_id,
            mime_sha256=mime_sha,
            provider_calls=ledger.provider_calls,
            send_calls=ledger.send_calls,
        )
    atomic_json(root / "result.json", result)
    return result


def reconcile_unknown(
    run_root: Path,
    request: dict[str, Any],
    transport: ReadableMailTransport,
) -> dict[str, Any]:
    """Explicit read-only recovery for an unknown send; never calls send."""

    root = require_owner_directory(run_root)
    request_sha = _request_sha(request)
    existing = read_owner_json(root / "result.json")
    validate_schema(existing, "gmail_readable_delivery_receipt_v1")
    if existing.get("request_sha256") != request_sha:
        raise GmailRestError("gmail_rest_request_changed")
    reconciled = root / "reconciliation-result.json"
    if reconciled.exists():
        prior = read_owner_json(reconciled)
        validate_schema(prior, "gmail_readable_delivery_receipt_v1")
        if prior.get("request_sha256") != request_sha:
            raise GmailRestError("gmail_rest_request_changed")
        return prior
    if existing.get("status") != "unknown":
        return existing
    raw = require_owner_file(root / "message.eml").read_bytes()
    if sha256_bytes(raw) != existing.get("mime_sha256"):
        raise GmailRestError("gmail_rest_mime_changed")
    requested_id = str(existing["requested_message_id"])
    result = _read_only_reconciliation(
        root,
        request,
        transport,
        request_sha=request_sha,
        requested_id=requested_id,
        mime_sha=str(existing["mime_sha256"]),
    )
    atomic_json(reconciled, result)
    return result


def verify_owner_run_root(run_root: Path) -> None:
    """Reject undeclared types, links, wide permissions, and empty artifacts."""

    root = require_owner_directory(run_root)
    allowed = {
        "intent.json",
        "message.eml",
        "provider.eml",
        "send-started.json",
        "send-response.json",
        "result.json",
        "reconciliation-result.json",
    }
    for path in root.iterdir():
        metadata = path.lstat()
        if (
            path.name not in allowed
            or path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size == 0
        ):
            raise GmailRestError("gmail_rest_artifact_invalid")


def _preview_assets(preview_root: Path, render: dict[str, Any]) -> list[dict[str, Any]]:
    manifest = render.get("asset_manifest")
    assets = manifest.get("assets") if isinstance(manifest, dict) else None
    if not isinstance(assets, list):
        raise GmailRestError("gmail_rest_inline_asset_invalid")
    result = []
    for item in assets:
        if not isinstance(item, dict):
            raise GmailRestError("gmail_rest_inline_asset_invalid")
        filename = item.get("filename")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise GmailRestError("gmail_rest_inline_asset_invalid")
        data = require_owner_file(preview_root / "assets" / filename).read_bytes()
        result.append({**item, "data": data})
    return result


def verify_offline_preview(run_root: Path) -> dict[str, Any]:
    root = require_owner_directory(run_root)
    receipt = read_owner_json(root / "mime-receipt.json")
    validate_schema(receipt, "offline_email_preview_receipt_v1")
    message = require_owner_file(root / "message.eml")
    if sha256_bytes(message.read_bytes()) != receipt["mime_sha256"]:
        raise GmailRestError("gmail_rest_mime_changed")
    allowed = {"message.eml", "mime-receipt.json"}
    if {path.name for path in root.iterdir()} != allowed:
        raise GmailRestError("gmail_rest_artifact_invalid")
    for path in root.iterdir():
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size <= 0
        ):
            raise GmailRestError("gmail_rest_artifact_invalid")
    return receipt


def package_offline_preview(
    preview_root: Path, run_root: Path, date_value: datetime
) -> dict[str, Any]:
    """Package one readable render as a private, non-deliverable RAW MIME preview."""

    preview = require_owner_directory(preview_root)
    render_path = require_owner_file(preview / "render.json")
    render = read_owner_json(render_path)
    kind = render.get("kind")
    if kind not in {"daily", "weekly"}:
        raise GmailRestError("gmail_rest_render_invalid")
    schema_version = render.get("schema_version")
    if schema_version not in {
        f"{kind}_email_render_v2",
        f"{kind}_email_render_v3",
    }:
        raise GmailRestError("gmail_rest_render_invalid")
    require_valid_payload(render, str(schema_version))
    if date_value.tzinfo is None or date_value.utcoffset() is None:
        raise GmailRestError("gmail_rest_date_invalid")
    _ensure_private_parent(run_root)
    root = _root(run_root)
    assets = _preview_assets(preview, render)
    receipt_path = root / "mime-receipt.json"
    if receipt_path.exists():
        receipt = verify_offline_preview(root)
        if sha256_bytes(render_path.read_bytes()) != receipt["render_sha256"]:
            raise GmailRestError("gmail_rest_request_changed")
        raw = require_owner_file(root / "message.eml").read_bytes()
        actual_id = verify_mime_v2_with_actual_message_id(
            raw,
            recipient="preview@trainlab.invalid",
            subject=str(render["subject"]),
            plain=str(render["text"]),
            html=str(render["html"]),
            inline_assets=assets,
        )
        if actual_id != receipt["actual_message_id"]:
            raise GmailRestError("gmail_rest_mime_mismatch")
        return receipt
    if any(root.iterdir()):
        raise GmailRestError("gmail_rest_artifact_invalid")
    raw, requested_id, mime_sha = deterministic_mime_v2(
        recipient="preview@trainlab.invalid",
        subject=str(render["subject"]),
        plain=str(render["text"]),
        html=str(render["html"]),
        source_sha256=str(render["view_sha256"]),
        date_value=date_value,
        inline_assets=assets,
    )
    actual_id = verify_mime_v2_with_actual_message_id(
        raw,
        recipient="preview@trainlab.invalid",
        subject=str(render["subject"]),
        plain=str(render["text"]),
        html=str(render["html"]),
        inline_assets=assets,
    )
    if actual_id != requested_id:
        raise GmailRestError("gmail_rest_mime_mismatch")
    receipt = {
        "schema_version": "offline_email_preview_receipt_v1",
        "status": "succeeded",
        "render_sha256": sha256_bytes(render_path.read_bytes()),
        "mime_sha256": mime_sha,
        "requested_message_id": requested_id,
        "actual_message_id": actual_id,
        "files": ["message.eml"],
        "provider_calls": 0,
        "external_actions": 0,
    }
    validate_schema(receipt, "offline_email_preview_receipt_v1")
    atomic_write(root / "message.eml", raw)
    atomic_json(receipt_path, receipt)
    return verify_offline_preview(root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    try:
        date_value = datetime.fromisoformat(args.date)
    except ValueError as exc:
        raise GmailRestError("gmail_rest_date_invalid") from exc
    receipt = package_offline_preview(args.preview_root, args.output_dir, date_value)
    print(canonical_json(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
