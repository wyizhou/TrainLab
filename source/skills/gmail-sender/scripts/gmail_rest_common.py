#!/usr/bin/env python3
"""Owner-only Gmail REST primitives shared by authentication and delivery."""

from __future__ import annotations

import base64
import hashlib
import html as html_module
import json
import os
import re
import stat
import sys
import tempfile
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import format_datetime, getaddresses
from pathlib import Path
from typing import Any, cast

SOURCE_ROOT = Path(__file__).resolve().parents[3]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
SCOPES = (
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
)
API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"
AUTH_RECEIPT_NAME = "gmail-api-auth-receipt.json"


class GmailRestError(RuntimeError):
    """Stable, non-secret Gmail REST error."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_owner_file(path: Path, *, allow_empty: bool = False) -> Path:
    absolute = Path(os.path.abspath(path))
    metadata = absolute.lstat()
    if (
        absolute.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or (not allow_empty and metadata.st_size == 0)
    ):
        raise GmailRestError("gmail_rest_owner_file_required")
    return absolute


def require_owner_directory(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    metadata = absolute.lstat()
    if (
        absolute.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise GmailRestError("gmail_rest_owner_directory_required")
    return absolute


def private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return require_owner_directory(path)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path: Path, payload: bytes) -> None:
    if not payload:
        raise GmailRestError("gmail_rest_empty_artifact")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = Path(os.path.abspath(path.parent))
    metadata = parent.lstat()
    if (
        parent.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise GmailRestError("gmail_rest_owner_directory_required")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
        require_owner_file(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write(path, (canonical_json(payload) + "\n").encode("utf-8"))


def read_owner_json(path: Path) -> dict[str, Any]:
    absolute = require_owner_file(path)
    try:
        value = json.loads(absolute.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GmailRestError("gmail_rest_json_invalid") from exc
    if not isinstance(value, dict):
        raise GmailRestError("gmail_rest_json_invalid")
    return value


def validate_schema(payload: dict[str, Any], schema_name: str) -> None:
    try:
        from skills._shared.scripts.schema_validation import validate_payload

        errors = validate_payload(
            payload, schema_name, root=SOURCE_ROOT / "skills/_shared/schemas"
        )
        if errors == ["schema_not_found"]:
            raise ValueError("schema_not_found")
    except (OSError, ValueError) as exc:
        raise GmailRestError("gmail_rest_schema_unavailable") from exc
    if errors:
        raise GmailRestError(f"gmail_rest_schema_invalid:{schema_name}")


def read_recipient(path: Path) -> tuple[str, str]:
    value = read_owner_json(path)
    if (
        set(value) != {"schema_version", "email"}
        or value.get("schema_version") != "trainlab_email_recipient_v1"
    ):
        raise GmailRestError("gmail_rest_recipient_invalid")
    email = value.get("email")
    if (
        not isinstance(email, str)
        or len(email) > 254
        or re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) is None
    ):
        raise GmailRestError("gmail_rest_recipient_invalid")
    normalized = email.strip().casefold()
    return normalized, sha256_text(normalized)


def deterministic_mime(
    *,
    recipient: str,
    subject: str,
    plain: str,
    html: str,
    source_sha256: str,
    date_value: Any,
) -> tuple[bytes, str, str]:
    business = {
        "recipient": recipient.casefold(),
        "subject": subject,
        "plain": plain,
        "html": html,
        "source_sha256": source_sha256,
    }
    business_sha = sha256_text(canonical_json(business))
    message_id = f"<trainlab.{business_sha}@trainlab.invalid>"
    message = EmailMessage(policy=policy.SMTP)
    message["To"] = recipient
    message["Subject"] = subject
    message["Date"] = format_datetime(date_value)
    message["Message-ID"] = message_id
    message.set_content(plain)
    message.add_alternative(html, subtype="html")
    message.set_boundary(f"trainlab-{business_sha[:32]}")
    raw = message.as_bytes(policy=policy.SMTP)
    return raw, message_id, sha256_bytes(raw)


_INLINE_ASSET_KEYS = {
    "role",
    "cid",
    "filename",
    "media_type",
    "width_px",
    "height_px",
    "sha256",
    "byte_size",
    "alt",
    "data",
}
_INLINE_ASSET_DIMENSIONS: dict[str, tuple[int, int | None]] = {
    "email_brand_mark": (96, 96),
    "email_status_ready": (64, 64),
    "email_status_caution": (64, 64),
    "email_status_blocked": (64, 64),
    "daily_activity_hr_zones": (1248, None),
    "daily_sleep_stages": (1248, None),
    "daily_activity_heart_rate": (1248, None),
    "weekly_sleep": (1248, None),
    "weekly_rhr": (1248, None),
    "weekly_hrv": (1248, None),
    "weekly_running_distance": (1248, None),
    "weekly_activity_duration": (1248, None),
    "weekly_activity_hr_zones": (1248, None),
}


def _normalize_inline_assets(
    inline_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    cids: set[str] = set()
    filenames: set[str] = set()
    for item in inline_assets:
        if not isinstance(item, dict) or set(item) != _INLINE_ASSET_KEYS:
            raise GmailRestError("gmail_rest_inline_asset_invalid")
        data = item.get("data")
        cid = item.get("cid")
        filename = item.get("filename")
        role = item.get("role")
        dimensions = (
            _INLINE_ASSET_DIMENSIONS.get(role) if isinstance(role, str) else None
        )
        if (
            not isinstance(data, bytes)
            or not data
            or not isinstance(cid, str)
            or re.fullmatch(r"[A-Za-z0-9._-]+@trainlab\.invalid", cid) is None
            or not isinstance(filename, str)
            or re.fullmatch(r"[A-Za-z0-9._-]+\.png", filename) is None
            or item.get("media_type") != "image/png"
            or dimensions is None
            or not isinstance(item.get("width_px"), int)
            or item.get("width_px") != dimensions[0]
            or not isinstance(item.get("height_px"), int)
            or not 1 <= int(item["height_px"]) <= 1248
            or (dimensions[1] is not None and item.get("height_px") != dimensions[1])
            or item.get("byte_size") != len(data)
            or item.get("sha256") != sha256_bytes(data)
            or not isinstance(item.get("alt"), str)
            or not item["alt"]
            or cid in cids
            or filename in filenames
        ):
            raise GmailRestError("gmail_rest_inline_asset_invalid")
        cids.add(cid)
        filenames.add(filename)
        normalized.append(dict(item))
    return normalized


def _validate_cid_html(
    html: str, subject: str, inline_assets: list[dict[str, Any]]
) -> None:
    if len(html.encode("utf-8")) > 80 * 1024:
        raise GmailRestError("gmail_rest_html_too_large")
    titles = re.findall(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    headings = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    if (
        len(titles) != 1
        or html_module.unescape(titles[0]).strip() != subject
        or len(headings) != 1
        or html_module.unescape(headings[0]).strip() != subject
    ):
        raise GmailRestError("gmail_rest_subject_heading_mismatch")
    image_sources = re.findall(
        r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']",
        html,
        flags=re.IGNORECASE,
    )
    if any(not source.startswith("cid:") for source in image_sources):
        raise GmailRestError("gmail_rest_remote_image_forbidden")
    referenced = [source[4:] for source in image_sources]
    expected = [str(item["cid"]) for item in inline_assets]
    if len(referenced) != len(set(referenced)) or set(referenced) != set(expected):
        raise GmailRestError("gmail_rest_inline_asset_unclosed")


def deterministic_mime_v2(
    *,
    recipient: str,
    subject: str,
    plain: str,
    html: str,
    source_sha256: str,
    date_value: Any,
    inline_assets: list[dict[str, Any]],
) -> tuple[bytes, str, str]:
    """Build MIME v2: text plus HTML and its exact private CID PNG assets."""

    assets = _normalize_inline_assets(inline_assets)
    _validate_cid_html(html, subject, assets)
    manifest = [
        {key: value for key, value in item.items() if key != "data"} for item in assets
    ]
    business = {
        "mime_version": "trainlab_cid_mime_v2",
        "recipient": recipient.casefold(),
        "subject": subject,
        "plain": plain,
        "html": html,
        "source_sha256": source_sha256,
        "inline_assets": manifest,
    }
    business_sha = sha256_text(canonical_json(business))
    message_id = f"<trainlab.v2.{business_sha}@trainlab.invalid>"
    message = EmailMessage(policy=policy.SMTP)
    message["To"] = recipient
    message["Subject"] = subject
    message["Date"] = format_datetime(date_value)
    message["Message-ID"] = message_id
    message.set_content(plain)
    message.make_alternative()

    related = EmailMessage(policy=policy.SMTP)
    related.set_content(html, subtype="html")
    for item in assets:
        related.add_related(
            item["data"],
            maintype="image",
            subtype="png",
            cid=f"<{item['cid']}>",
            filename=item["filename"],
            disposition="inline",
        )
    if not assets:
        related.make_related()
    related.set_boundary(f"trainlab-related-{business_sha[:24]}")
    message.attach(related)
    message.set_boundary(f"trainlab-alternative-{business_sha[:24]}")
    raw = message.as_bytes(policy=policy.SMTP)
    return raw, message_id, sha256_bytes(raw)


def gmail_raw(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_gmail_raw(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise GmailRestError("gmail_rest_raw_missing")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise GmailRestError("gmail_rest_raw_invalid") from exc


def require_gmail_message_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value) is None
    ):
        raise GmailRestError("gmail_rest_provider_message_id_invalid")
    return value


def verify_mime(
    actual: bytes,
    *,
    recipient: str,
    subject: str,
    plain: str,
    html: str,
    message_id: str,
) -> None:
    actual_message_id = verify_mime_with_actual_message_id(
        actual,
        recipient=recipient,
        subject=subject,
        plain=plain,
        html=html,
    )
    if actual_message_id != message_id:
        raise GmailRestError("gmail_rest_mime_mismatch")


def verify_mime_with_actual_message_id(
    actual: bytes,
    *,
    recipient: str,
    subject: str,
    plain: str,
    html: str,
) -> str:
    """Verify the immutable business content and return Gmail's RFC822 ID."""

    try:
        message = BytesParser(policy=policy.default).parsebytes(actual)
        to_headers = message.get_all("to", [])
        subject_headers = message.get_all("subject", [])
        message_id_headers = message.get_all("message-id", [])
        recipients = [address.casefold() for _name, address in getaddresses(to_headers)]
        payload = message.get_payload()
        parts = cast(list[Any], payload) if isinstance(payload, list) else None
        exact_alternative = (
            message.get_content_type() == "multipart/alternative"
            and isinstance(parts, list)
            and len(parts) == 2
            and [part.get_content_type() for part in parts]
            == ["text/plain", "text/html"]
            and all(not part.is_multipart() for part in parts)
            and all(part.get_filename() is None for part in parts)
            and all(part.get_content_disposition() != "attachment" for part in parts)
        )
        plain_part = parts[0] if exact_alternative and parts is not None else None
        html_part = parts[1] if exact_alternative and parts is not None else None

        def normalize(text: str) -> str:
            return text.replace("\r\n", "\n").rstrip("\n")

        actual_message_id = (
            str(message_id_headers[0]) if len(message_id_headers) == 1 else ""
        )
        valid = (
            not message.defects
            and len(to_headers) == 1
            and len(subject_headers) == 1
            and len(message_id_headers) == 1
            and recipients == [recipient.casefold()]
            and str(subject_headers[0]) == subject
            and re.fullmatch(r"<[^<>\s@]+@[^<>\s@]+>", actual_message_id) is not None
            and exact_alternative
            and plain_part is not None
            and html_part is not None
            and normalize(plain_part.get_content()) == normalize(plain)
            and normalize(html_part.get_content()) == normalize(html)
        )
    except Exception as exc:
        raise GmailRestError("gmail_rest_mime_invalid") from exc
    if not valid:
        raise GmailRestError("gmail_rest_mime_mismatch")
    return actual_message_id


def verify_mime_v2_with_actual_message_id(
    actual: bytes,
    *,
    recipient: str,
    subject: str,
    plain: str,
    html: str,
    inline_assets: list[dict[str, Any]],
) -> str:
    """Verify MIME v2 business content and every CID image byte."""

    assets = _normalize_inline_assets(inline_assets)
    _validate_cid_html(html, subject, assets)
    expected = {str(item["cid"]): item for item in assets}
    try:
        message = BytesParser(policy=policy.default).parsebytes(actual)
        to_headers = message.get_all("to", [])
        subject_headers = message.get_all("subject", [])
        message_id_headers = message.get_all("message-id", [])
        recipients = [address.casefold() for _name, address in getaddresses(to_headers)]
        outer = list(message.iter_parts()) if message.is_multipart() else []
        exact_outer = (
            message.get_content_type() == "multipart/alternative"
            and len(outer) == 2
            and outer[0].get_content_type() == "text/plain"
            and outer[1].get_content_type() == "multipart/related"
        )
        related_parts = list(outer[1].iter_parts()) if exact_outer else []
        exact_related = (
            len(related_parts) == len(assets) + 1
            and related_parts[0].get_content_type() == "text/html"
        )

        def normalize(text: str) -> str:
            return text.replace("\r\n", "\n").rstrip("\n")

        actual_message_id = (
            str(message_id_headers[0]) if len(message_id_headers) == 1 else ""
        )
        valid = (
            not message.defects
            and len(to_headers) == 1
            and len(subject_headers) == 1
            and len(message_id_headers) == 1
            and recipients == [recipient.casefold()]
            and str(subject_headers[0]) == subject
            and re.fullmatch(r"<[^<>\s@]+@[^<>\s@]+>", actual_message_id) is not None
            and exact_outer
            and exact_related
            and normalize(outer[0].get_content()) == normalize(plain)
            and normalize(related_parts[0].get_content()) == normalize(html)
        )
        seen: set[str] = set()
        if valid:
            for part in related_parts[1:]:
                cid_header = str(part.get("Content-ID", ""))
                cid = cid_header[1:-1] if cid_header.startswith("<") else ""
                item = expected.get(cid)
                payload = part.get_content()
                if (
                    item is None
                    or cid in seen
                    or part.get_content_type() != "image/png"
                    or part.get_content_disposition() != "inline"
                    or part.get_filename() != item["filename"]
                    or not isinstance(payload, bytes)
                    or payload != item["data"]
                    or sha256_bytes(payload) != item["sha256"]
                ):
                    valid = False
                    break
                seen.add(cid)
        valid = bool(valid and seen == set(expected))
    except Exception as exc:
        raise GmailRestError("gmail_rest_mime_invalid") from exc
    if not valid:
        raise GmailRestError("gmail_rest_mime_mismatch")
    return actual_message_id


def sanitize_capture(
    *,
    method: str,
    url: str,
    status_code: int | None,
    request_sha256: str,
    response: Any,
) -> dict[str, Any]:
    return {
        "method": method,
        "url": url,
        "status_code": status_code,
        "request_sha256": request_sha256,
        "response": response,
    }
