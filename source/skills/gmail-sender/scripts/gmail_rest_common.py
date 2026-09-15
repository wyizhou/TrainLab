#!/usr/bin/env python3
"""Owner-only primitives for explicit OAuth maintenance; no mail delivery executor."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[3]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
from skills._shared.fit_weekly import gmail_scopes  # noqa: E402

SCOPES = tuple(sorted(gmail_scopes.SCOPES))
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
    except BaseException:
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
    from skills._shared.fit_weekly import email_config

    try:
        normalized = email_config.read(path.parent, str(path))
    except ValueError:
        raise GmailRestError("gmail_rest_recipient_invalid") from None
    return normalized, sha256_text(normalized)


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


def require_gmail_message_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value) is None
    ):
        raise GmailRestError("gmail_rest_provider_message_id_invalid")
    return value


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
