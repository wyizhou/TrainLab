#!/usr/bin/env python3
"""Owner-only Gmail REST primitives shared by authentication and delivery."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import tempfile
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import format_datetime, getaddresses
from pathlib import Path
from typing import Any, cast

SOURCE_ROOT = Path(__file__).resolve().parents[3]
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
        from jsonschema import Draft202012Validator, FormatChecker

        schema_path = (
            SOURCE_ROOT / "skills/_shared/schemas" / f"{schema_name}.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = list(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
                payload
            )
        )
    except (OSError, json.JSONDecodeError) as exc:
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
