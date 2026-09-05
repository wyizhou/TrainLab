#!/usr/bin/env python3
"""M11 owner-only live Gmail host for frozen readable-email batches."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

RUNTIME_SOURCE_ROOT = Path(__file__).resolve().parents[3]
if str(RUNTIME_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SOURCE_ROOT))
SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from gmail_readable_delivery import (  # noqa: E402
    ReadableMailTransport,
    deliver_once,
)
from gmail_rest_common import (  # noqa: E402
    AUTH_RECEIPT_NAME,
    GmailRestError,
    atomic_json,
    atomic_write,
    canonical_json,
    deterministic_mime_v2,
    private_directory,
    read_owner_json,
    read_recipient,
    require_owner_directory,
    require_owner_file,
    sha256_file,
    sha256_text,
    validate_schema,
)
from gmail_rest_delivery import (  # noqa: E402
    AUTH_API_CALLS,
    MAX_ACTION_CALLS,
    READ_PHASES,
    GmailRestClient,
)

from skills._shared.scripts.build_m8_candidate import (  # noqa: E402
    _formal_state_fingerprint as _m8_formal_state_fingerprint,
)
from skills._shared.scripts.build_m8_candidate import (  # noqa: E402
    _formal_state_lock as _m8_formal_state_lock,
)
from skills._shared.state import (  # noqa: E402
    begin_run,
    connect,
    finish_run,
    require_lastrowid,
    utc_now,
    workflow_lock,
)

BATCH_ID = "m11-live-canary"
WORKFLOW_KEY = "m11:live-canary:2026-08-12--2026-08-18"
TARGET_KEY_PREFIX = "m11:live-canary"
MARKER_NAME = "m11-live-canary.json"
MARKER_SCHEMA_NAME = "m11_live_canary_candidate_v1"
MARKER_SCHEMA_VERSION = "m11_live_canary_candidate_v1"
PRIVATE_SOURCE_ROOT = RUNTIME_SOURCE_ROOT
FORMAL_SOURCE_ROOT = RUNTIME_SOURCE_ROOT
FROZEN_R03_ROOT = Path("/private/tmp/trainlab-m11-preview-r03.1787298418179")
FROZEN_PARENT_DATABASE_SHA256 = (
    "f0da6907e5fe2cc12d9b4076f18c5eb1bab0cfab01bd1e83cec9b29a7ae08b9d"
)
FROZEN_BUILD_RECEIPT_SHA256 = (
    "1110524de8369428da2604acc91c6a598afaa40419d44c6266a47ffb9cc61259"
)
MAX_DELIVERY_API_CALLS = 32
MAX_PROVIDER_CALLS_WITH_AUTH = MAX_DELIVERY_API_CALLS + AUTH_API_CALLS
MAX_SEND_CALLS = 2
REQUIRE_MANUAL_CONFIRMATION = True
STRICT_SERIAL = False
PREVIEW_MANIFEST_MODE = "per_preview_receipt"
APPROVAL_SOURCE_REF = "m11-live-canary:user-approved-plan"
APPROVAL_REASON_CODE = "m11_live_two_email_style_canary_approved"
HISTORICAL_LIVE_ROOT: Path | None = None
FROZEN_HISTORICAL_MARKER_SHA256: str | None = None
FROZEN_HISTORICAL_DATABASE_SHA256: str | None = None


@dataclass(frozen=True)
class FrozenCanaryItem:
    kind: str
    preview_name: str
    output_id: int
    output_sha256: str
    render_sha256: str
    period_start: str
    period_end: str
    date_value: datetime
    item_key: str | None = None
    render_schema_name: str | None = None


def _frozen_item_key(item: FrozenCanaryItem) -> str:
    return item.item_key or item.kind


def _frozen_render_schema(item: FrozenCanaryItem) -> str:
    return item.render_schema_name or f"{item.kind}_email_render_v2"


FROZEN_ITEMS: tuple[FrozenCanaryItem, ...] = (
    FrozenCanaryItem(
        kind="daily",
        preview_name="daily-2026-08-12",
        output_id=114,
        output_sha256=(
            "dc40fefcda250192b48d49738e641604949267e9f53db3b512250f70e3b90fcc"
        ),
        render_sha256=(
            "85f53abac52681bf5c0b22ff8c47b6b620cdb5637332c5e4b89581efd4cb8af4"
        ),
        period_start="2026-08-12",
        period_end="2026-08-12",
        date_value=datetime(2026, 8, 12, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
    ),
    FrozenCanaryItem(
        kind="weekly",
        preview_name="weekly-2026-08-12--2026-08-18",
        output_id=128,
        output_sha256=(
            "6480cb7296bc62c91ff77e93473c5a28123bf05bfbd7140da614714489fa8c77"
        ),
        render_sha256=(
            "6fc2d884ce09cd8cdee0082c553b27c4d0bd876122e145d6e5ab214da41c3e90"
        ),
        period_start="2026-08-12",
        period_end="2026-08-18",
        date_value=datetime(2026, 8, 18, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
    ),
)

CORRECTION_PREVIEW_ROOT = Path(
    "/private/tmp/trainlab-m11-health-preview-r07.bzIRiG/candidate"
)
CORRECTION_PARENT_DATABASE_SHA256 = (
    "00f874b887120434368f80a31a377e048af6718a32ca4fe041feae7045022364"
)
CORRECTION_BUILD_RECEIPT_SHA256 = (
    "64a2f75afc2d9fb10c09de7c15578bf3ec0aa2665cdbab484dfc4dafa87767a7"
)
CORRECTION_ITEMS = (
    FrozenCanaryItem(
        kind="daily",
        preview_name="daily-2026-08-12",
        output_id=81,
        output_sha256=(
            "7ea032f63d260a67b18fee2d0be1f7c70cea3d3d3ac1d575831d7666eb8c84ba"
        ),
        render_sha256=(
            "f338219d10feb61769d6cc486b0804fa12bcc4d622e53e0b723ecb7e43f90c44"
        ),
        period_start="2026-08-12",
        period_end="2026-08-12",
        date_value=datetime(2026, 8, 12, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
    ),
    FrozenCanaryItem(
        kind="weekly",
        preview_name="weekly-2026-08-12--2026-08-18",
        output_id=83,
        output_sha256=(
            "f85b43fc746c6d62cbb98cda8446b54c54c1d23bf13055617cc93e11a46c7dd6"
        ),
        render_sha256=(
            "6fc2d884ce09cd8cdee0082c553b27c4d0bd876122e145d6e5ab214da41c3e90"
        ),
        period_start="2026-08-12",
        period_end="2026-08-18",
        date_value=datetime(2026, 8, 18, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
    ),
)
CORRECTION_HISTORICAL_LIVE_ROOT = Path(
    "/private/tmp/trainlab-m11-live-f06.MqMYR2/candidate"
)
CORRECTION_HISTORICAL_MARKER_SHA256 = (
    "36a39ddaa0f20e7af2c9c49df8a353a94374c51bf58583cb18b6f6b4d48e3c2f"
)
CORRECTION_HISTORICAL_DATABASE_SHA256 = (
    "396354de04ff5a71a6da19f42406241c933a353688f875e0a17eadb4c43578cb"
)

V3_PREVIEW_ROOT = Path("/private/tmp/trainlab-m11-v3-r06.T6nbtk")
V3_PARENT_DATABASE_SHA256 = (
    "f83792377a06002a5760f54ff5659086ddf968f5fcb0ec78f798891d64dd1c50"
)
V3_BUILD_RECEIPT_SHA256 = (
    "b40f732c7c689676315bc0bb3b96cf120df2e4ccbcfbc85b615453efbc637796"
)
V3_ITEMS = (
    FrozenCanaryItem(
        kind="daily",
        preview_name="daily-2026-08-12",
        output_id=118,
        output_sha256=(
            "aea3b07ea5a6e154554f7fe5d6dafc15505c930cf23a7aff1582a4fd82cb6d85"
        ),
        render_sha256=(
            "33b23714dc833aed29c8a8e35f262a153152ed6f04349899842765cd1efe5737"
        ),
        period_start="2026-08-12",
        period_end="2026-08-12",
        date_value=datetime(2026, 8, 12, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
        item_key="daily-2026-08-12",
        render_schema_name="daily_email_render_v3",
    ),
    FrozenCanaryItem(
        kind="daily",
        preview_name="daily-2026-08-13",
        output_id=120,
        output_sha256=(
            "bc86f1f417c4ab9b13aeace1d3944eaded05ad05c3081f2a1336c536cef4b351"
        ),
        render_sha256=(
            "38a7d6d0146320a15c02916271347ac1fa056e19969851c594700023c72ae9eb"
        ),
        period_start="2026-08-13",
        period_end="2026-08-13",
        date_value=datetime(2026, 8, 13, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
        item_key="daily-2026-08-13",
        render_schema_name="daily_email_render_v3",
    ),
    FrozenCanaryItem(
        kind="daily",
        preview_name="daily-2026-08-14",
        output_id=122,
        output_sha256=(
            "0f59955623ff020b61e6cc52533165427d69a42220ebc00ff89d430a9574d276"
        ),
        render_sha256=(
            "e8185cf6dc76c61cb83ad6687d2ed711e95256624bb9cdf51240fe22fcf86358"
        ),
        period_start="2026-08-14",
        period_end="2026-08-14",
        date_value=datetime(2026, 8, 14, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
        item_key="daily-2026-08-14",
        render_schema_name="daily_email_render_v3",
    ),
    FrozenCanaryItem(
        kind="daily",
        preview_name="daily-2026-08-15",
        output_id=124,
        output_sha256=(
            "5b78f386da55316bef1405c35ccc6215f4d7e5f96656f7cff813f13a4207caf1"
        ),
        render_sha256=(
            "a27dcd4cd8cde20129c8fe90e24c4180b08abca9484b4091374b3f2371f0c426"
        ),
        period_start="2026-08-15",
        period_end="2026-08-15",
        date_value=datetime(2026, 8, 15, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
        item_key="daily-2026-08-15",
        render_schema_name="daily_email_render_v3",
    ),
    FrozenCanaryItem(
        kind="daily",
        preview_name="daily-2026-08-16",
        output_id=126,
        output_sha256=(
            "02847ebde459236856c810f9dd42d8ae7a3c69addcdd45d66b9ec0edc09f3317"
        ),
        render_sha256=(
            "3c679693964adec2123f78379fbb75619a7dd749d8432359d996a49f9aa6eee1"
        ),
        period_start="2026-08-16",
        period_end="2026-08-16",
        date_value=datetime(2026, 8, 16, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
        item_key="daily-2026-08-16",
        render_schema_name="daily_email_render_v3",
    ),
    FrozenCanaryItem(
        kind="daily",
        preview_name="daily-2026-08-17",
        output_id=128,
        output_sha256=(
            "1662cd61cf64bc5db243557a82fe9722313bb33e743b7b1258c23fb0ad846dae"
        ),
        render_sha256=(
            "dafa190b5ae90715170d377e84e7ba2ad5764b341aaaca86c4423dbbdbbbb761"
        ),
        period_start="2026-08-17",
        period_end="2026-08-17",
        date_value=datetime(2026, 8, 17, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
        item_key="daily-2026-08-17",
        render_schema_name="daily_email_render_v3",
    ),
    FrozenCanaryItem(
        kind="daily",
        preview_name="daily-2026-08-18",
        output_id=130,
        output_sha256=(
            "0ef17eb2c7e555d2bbd9038edc7bba01cecf651a095386cf7aa1770267903053"
        ),
        render_sha256=(
            "dddae07d9e64dd5d015663e01938cd10ca012d2656f6ddd4066319c717a9f322"
        ),
        period_start="2026-08-18",
        period_end="2026-08-18",
        date_value=datetime(2026, 8, 18, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
        item_key="daily-2026-08-18",
        render_schema_name="daily_email_render_v3",
    ),
    FrozenCanaryItem(
        kind="weekly",
        preview_name="weekly-2026-08-12--2026-08-18",
        output_id=132,
        output_sha256=(
            "b83f32f870bd029b4d5b7f57ba78ce063207b524c8b0d5cba08c03dcd2645281"
        ),
        render_sha256=(
            "681d84104441c3cdd31f85b90dd2fd6cd1dd8fa0e70b6f5dfaea8d9ac57a57b7"
        ),
        period_start="2026-08-12",
        period_end="2026-08-18",
        date_value=datetime(2026, 8, 18, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
        item_key="weekly-2026-08-12--2026-08-18",
        render_schema_name="weekly_email_render_v3",
    ),
)


def _activate_health_correction_policy() -> None:
    """Select the frozen A-014 continuation without duplicating the sender."""

    global BATCH_ID, WORKFLOW_KEY, TARGET_KEY_PREFIX, MARKER_NAME
    global MARKER_SCHEMA_NAME, MARKER_SCHEMA_VERSION
    global FROZEN_R03_ROOT, FROZEN_PARENT_DATABASE_SHA256
    global FROZEN_BUILD_RECEIPT_SHA256, FROZEN_ITEMS
    global APPROVAL_SOURCE_REF, APPROVAL_REASON_CODE
    global HISTORICAL_LIVE_ROOT, FROZEN_HISTORICAL_MARKER_SHA256
    global FROZEN_HISTORICAL_DATABASE_SHA256
    BATCH_ID = "m11-health-correction-canary"
    WORKFLOW_KEY = "m11:health-correction:2026-08-12--2026-08-18"
    TARGET_KEY_PREFIX = "m11:health-correction"
    MARKER_NAME = "m11-health-correction-canary.json"
    MARKER_SCHEMA_NAME = "m11_live_canary_candidate_v2"
    MARKER_SCHEMA_VERSION = "m11_live_canary_candidate_v2"
    FROZEN_R03_ROOT = CORRECTION_PREVIEW_ROOT
    FROZEN_PARENT_DATABASE_SHA256 = CORRECTION_PARENT_DATABASE_SHA256
    FROZEN_BUILD_RECEIPT_SHA256 = CORRECTION_BUILD_RECEIPT_SHA256
    FROZEN_ITEMS = CORRECTION_ITEMS
    APPROVAL_SOURCE_REF = "m11-health-correction:user-approved-plan"
    APPROVAL_REASON_CODE = "m11_recent_health_corrected_daily_and_weekly_approved"
    HISTORICAL_LIVE_ROOT = CORRECTION_HISTORICAL_LIVE_ROOT
    FROZEN_HISTORICAL_MARKER_SHA256 = CORRECTION_HISTORICAL_MARKER_SHA256
    FROZEN_HISTORICAL_DATABASE_SHA256 = CORRECTION_HISTORICAL_DATABASE_SHA256


def _activate_v3_batch_policy() -> None:
    """Select the fixed A-017 eight-message batch without a dynamic date API."""

    global BATCH_ID, WORKFLOW_KEY, TARGET_KEY_PREFIX, MARKER_NAME
    global MARKER_SCHEMA_NAME, MARKER_SCHEMA_VERSION
    global FROZEN_R03_ROOT, FROZEN_PARENT_DATABASE_SHA256
    global FROZEN_BUILD_RECEIPT_SHA256, FROZEN_ITEMS
    global MAX_DELIVERY_API_CALLS, MAX_PROVIDER_CALLS_WITH_AUTH, MAX_SEND_CALLS
    global REQUIRE_MANUAL_CONFIRMATION, STRICT_SERIAL, PREVIEW_MANIFEST_MODE
    global APPROVAL_SOURCE_REF, APPROVAL_REASON_CODE
    global HISTORICAL_LIVE_ROOT, FROZEN_HISTORICAL_MARKER_SHA256
    global FROZEN_HISTORICAL_DATABASE_SHA256
    BATCH_ID = "m11-v3-live-batch"
    WORKFLOW_KEY = "m11:v3:live:2026-08-12--2026-08-18"
    TARGET_KEY_PREFIX = "m11:v3:live"
    MARKER_NAME = "m11-v3-live-batch.json"
    MARKER_SCHEMA_NAME = "m11_v3_live_batch_candidate_v1"
    MARKER_SCHEMA_VERSION = "m11_v3_live_batch_candidate_v1"
    FROZEN_R03_ROOT = V3_PREVIEW_ROOT
    FROZEN_PARENT_DATABASE_SHA256 = V3_PARENT_DATABASE_SHA256
    FROZEN_BUILD_RECEIPT_SHA256 = V3_BUILD_RECEIPT_SHA256
    FROZEN_ITEMS = V3_ITEMS
    MAX_DELIVERY_API_CALLS = 128
    MAX_PROVIDER_CALLS_WITH_AUTH = MAX_DELIVERY_API_CALLS + AUTH_API_CALLS
    MAX_SEND_CALLS = 8
    REQUIRE_MANUAL_CONFIRMATION = False
    STRICT_SERIAL = True
    PREVIEW_MANIFEST_MODE = "candidate_build_receipt"
    APPROVAL_SOURCE_REF = "m11-v3-live:user-approved-A-017"
    APPROVAL_REASON_CODE = "m11_v3_eight_email_batch_approved"
    HISTORICAL_LIVE_ROOT = None
    FROZEN_HISTORICAL_MARKER_SHA256 = None
    FROZEN_HISTORICAL_DATABASE_SHA256 = None


RUNTIME_FILES = (
    "requirements.txt",
    "skills/_shared/schemas/daily_email_render_v3.schema.json",
    "skills/_shared/schemas/email_inline_asset_manifest_v1.schema.json",
    "skills/_shared/schemas/gmail_readable_delivery_receipt_v1.schema.json",
    "skills/_shared/schemas/m11_live_canary_candidate_v1.schema.json",
    "skills/_shared/schemas/m11_live_canary_candidate_v2.schema.json",
    "skills/_shared/schemas/m11_v3_live_batch_candidate_v1.schema.json",
    "skills/_shared/schemas/m11_live_canary_confirmation_v1.schema.json",
    "skills/_shared/schemas/weekly_email_render_v3.schema.json",
    "skills/_shared/state.py",
    "skills/gmail-sender/SKILL.md",
    "skills/gmail-sender/scripts/gmail_readable_delivery.py",
    "skills/gmail-sender/scripts/gmail_readable_live.py",
    "skills/gmail-sender/scripts/gmail_rest_common.py",
    "skills/gmail-sender/scripts/gmail_rest_delivery.py",
)


def _formal_state_fingerprint(root: Path) -> dict[str, object]:
    return _m8_formal_state_fingerprint(root)


@contextmanager
def _hold_formal_state_lock() -> Iterator[None]:
    """Hold the cooperative formal lock only for a bounded fingerprint read."""

    try:
        with _m8_formal_state_lock(FORMAL_SOURCE_ROOT):
            yield
    except ValueError as exc:
        raise GmailRestError("gmail_live_formal_state_lock_unavailable") from exc


def _runtime_sha256() -> str:
    entries: dict[str, str] = {}
    for relative in RUNTIME_FILES:
        path = RUNTIME_SOURCE_ROOT / relative
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
        ):
            raise GmailRestError("gmail_live_runtime_file_invalid")
        entries[relative] = sha256_file(path)
    return sha256_text(canonical_json(entries))


def _secure_copy(source: Path, target: Path) -> None:
    require_owner_file(source)
    private_directory(target.parent)
    if target.exists() or target.is_symlink():
        raise GmailRestError("gmail_live_copy_target_exists")
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with source.open("rb") as incoming, os.fdopen(descriptor, "wb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
            outgoing.flush()
            os.fsync(outgoing.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    if sha256_file(source) != sha256_file(target):
        target.unlink(missing_ok=True)
        raise GmailRestError("gmail_live_copy_hash_mismatch")


def _preview_artifacts(preview: Path) -> dict[str, Path]:
    root = require_owner_directory(preview)
    receipt = read_owner_json(root / "preview-receipt.json")
    expected: dict[str, dict[str, Any]] = {}
    for item in receipt.get("artifacts", []):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise GmailRestError("gmail_live_preview_invalid")
        relative = Path(str(item["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise GmailRestError("gmail_live_preview_invalid")
        expected[relative.as_posix()] = item
    actual = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file() and path.name != "preview-receipt.json"
    }
    if not expected or set(actual) != set(expected):
        raise GmailRestError("gmail_live_preview_invalid")
    for name, path in actual.items():
        metadata = path.lstat()
        entry = expected[name]
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size <= 0
            or entry.get("mode") != "0600"
            or entry.get("byte_size") != metadata.st_size
            or entry.get("sha256") != sha256_file(path)
        ):
            raise GmailRestError("gmail_live_preview_invalid")
    return {**actual, "preview-receipt.json": root / "preview-receipt.json"}


def _candidate_preview_artifacts(
    parent: Path, item: FrozenCanaryItem
) -> dict[str, Path]:
    """Validate one r06 preview against the Candidate-level file manifest."""

    root = require_owner_directory(parent)
    receipt = read_owner_json(root / "build-receipt.json")
    if (
        receipt.get("schema_version") != "m11_v3_candidate_receipt_v1"
        or receipt.get("status") != "succeeded"
        or not isinstance(receipt.get("declared_files"), list)
    ):
        raise GmailRestError("gmail_live_preview_invalid")
    prefix = f"previews/{item.preview_name}/"
    expected: dict[str, dict[str, Any]] = {}
    for entry in receipt["declared_files"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise GmailRestError("gmail_live_preview_invalid")
        name = str(entry["path"])
        if not name.startswith(prefix):
            continue
        relative = Path(name.removeprefix(prefix))
        if relative.is_absolute() or ".." in relative.parts:
            raise GmailRestError("gmail_live_preview_invalid")
        expected[relative.as_posix()] = entry
    preview = require_owner_directory(root / "previews" / item.preview_name)
    actual = {
        path.relative_to(preview).as_posix(): path
        for path in preview.rglob("*")
        if path.is_file()
    }
    if not expected or set(actual) != set(expected):
        raise GmailRestError("gmail_live_preview_invalid")
    for name, path in actual.items():
        metadata = path.lstat()
        entry = expected[name]
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size <= 0
            or entry.get("byte_size") != metadata.st_size
            or entry.get("sha256") != sha256_file(path)
        ):
            raise GmailRestError("gmail_live_preview_invalid")
    return actual


def _frozen_preview_artifacts(parent: Path, item: FrozenCanaryItem) -> dict[str, Path]:
    if PREVIEW_MANIFEST_MODE == "per_preview_receipt":
        return _preview_artifacts(parent / "previews" / item.preview_name)
    if PREVIEW_MANIFEST_MODE == "candidate_build_receipt":
        return _candidate_preview_artifacts(parent, item)
    raise GmailRestError("gmail_live_preview_manifest_mode_invalid")


def _validated_render(parent: Path, item: FrozenCanaryItem) -> dict[str, Any]:
    files = _frozen_preview_artifacts(parent, item)
    render_path = require_owner_file(files["render.json"])
    if sha256_file(render_path) != item.render_sha256:
        raise GmailRestError("gmail_live_frozen_render_changed")
    render = read_owner_json(render_path)
    if (
        render.get("kind") != item.kind
        or render.get("schema_version") != _frozen_render_schema(item)
        or require_owner_file(files["report.html"]).read_text(encoding="utf-8")
        != render.get("html")
        or require_owner_file(files["report.txt"]).read_text(encoding="utf-8")
        != render.get("text")
    ):
        raise GmailRestError("gmail_live_frozen_render_changed")
    validate_schema(render, _frozen_render_schema(item))
    assets = render.get("asset_manifest", {}).get("assets", [])
    if not isinstance(assets, list):
        raise GmailRestError("gmail_live_frozen_render_changed")
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("filename"), str):
            raise GmailRestError("gmail_live_frozen_render_changed")
        path = files.get(f"assets/{asset['filename']}")
        if (
            path is None
            or asset.get("sha256") != sha256_file(path)
            or asset.get("byte_size") != path.stat().st_size
        ):
            raise GmailRestError("gmail_live_frozen_render_changed")
    return render


def _copy_preview(parent: Path, candidate: Path, item: FrozenCanaryItem) -> None:
    files = _frozen_preview_artifacts(parent, item)
    target = candidate / "inputs" / item.preview_name
    private_directory(target)
    for relative, path in sorted(files.items()):
        _secure_copy(path, target / relative)


def _backup_database(source: Path, target: Path) -> None:
    require_owner_file(source)
    private_directory(target.parent)
    if target.exists() or target.is_symlink():
        raise GmailRestError("gmail_live_candidate_database_exists")
    incoming = sqlite3.connect(f"file:{source.resolve()}?mode=ro&immutable=1", uri=True)
    outgoing = sqlite3.connect(target)
    try:
        incoming.backup(outgoing)
        outgoing.commit()
    finally:
        outgoing.close()
        incoming.close()
    target.chmod(0o600)
    check = sqlite3.connect(f"file:{target.resolve()}?mode=ro&immutable=1", uri=True)
    try:
        integrity = str(check.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key = check.execute("PRAGMA foreign_key_check").fetchone()
    finally:
        check.close()
    if integrity != "ok" or foreign_key is not None:
        raise GmailRestError("gmail_live_candidate_database_invalid")


def _token_snapshot() -> dict[str, Any]:
    path = require_owner_file(PRIVATE_SOURCE_ROOT / "gmail-api-token.json")
    metadata = path.lstat()
    return {
        "sha256": sha256_file(path),
        "mode": stat.S_IMODE(metadata.st_mode),
        "uid": metadata.st_uid,
        "size": metadata.st_size,
    }


def _auth_receipt_sha() -> str:
    path = PRIVATE_SOURCE_ROOT / AUTH_RECEIPT_NAME
    receipt = read_owner_json(path)
    validate_schema(receipt, "gmail_rest_auth_receipt_v1")
    if (
        receipt.get("status") != "succeeded"
        or receipt.get("account_matches") is not True
        or receipt.get("scopes_match") is not True
        or receipt.get("refresh_token_available") is not True
        or receipt.get("token_published") is not True
        or receipt.get("short_lived_testing_token") is not False
        or receipt.get("provider_calls") != AUTH_API_CALLS
    ):
        raise GmailRestError("gmail_live_auth_receipt_invalid")
    return sha256_file(require_owner_file(path))


def _historical_live_evidence() -> dict[str, Any] | None:
    if HISTORICAL_LIVE_ROOT is None:
        return None
    root = require_owner_directory(HISTORICAL_LIVE_ROOT)
    marker_path = require_owner_file(root / "m11-live-canary.json")
    database = require_owner_file(root / "source/state/trainlab.db")
    if (
        FROZEN_HISTORICAL_MARKER_SHA256 is None
        or FROZEN_HISTORICAL_DATABASE_SHA256 is None
        or sha256_file(marker_path) != FROZEN_HISTORICAL_MARKER_SHA256
        or sha256_file(database) != FROZEN_HISTORICAL_DATABASE_SHA256
    ):
        raise GmailRestError("gmail_live_historical_evidence_changed")
    marker = read_owner_json(marker_path)
    validate_schema(marker, "m11_live_canary_candidate_v1")
    action_ids = marker.get("action_ids")
    if (
        marker.get("api_calls") != 4
        or marker.get("send_calls") != 1
        or not isinstance(action_ids, list)
        or len(action_ids) != 2
    ):
        raise GmailRestError("gmail_live_historical_evidence_invalid")
    connection = connect(database, read_only=True, immutable=True)
    try:
        rows = connection.execute(
            "SELECT id,status,attempt_count,result_external_id FROM external_actions "
            "WHERE id IN (?,?) ORDER BY id",
            tuple(int(value) for value in action_ids),
        ).fetchall()
    finally:
        connection.close()
    if (
        len(rows) != 2
        or str(rows[0]["status"]) != "succeeded"
        or int(rows[0]["attempt_count"]) != 1
        or not rows[0]["result_external_id"]
        or str(rows[1]["status"]) != "prepared"
        or int(rows[1]["attempt_count"]) != 0
        or rows[1]["result_external_id"] is not None
    ):
        raise GmailRestError("gmail_live_historical_evidence_invalid")
    return {
        "historical_live_marker_sha256": FROZEN_HISTORICAL_MARKER_SHA256,
        "historical_live_database_sha256": FROZEN_HISTORICAL_DATABASE_SHA256,
        "historical_daily_gmail_id_sha256": sha256_text(
            str(rows[0]["result_external_id"])
        ),
        "historical_api_calls": 4,
        "historical_send_calls": 1,
        "cumulative_max_api_calls": 48,
        "cumulative_max_send_calls": 3,
    }


def _assets(
    candidate: Path, item: FrozenCanaryItem, render: dict[str, Any]
) -> list[dict[str, Any]]:
    assets = render.get("asset_manifest", {}).get("assets", [])
    if not isinstance(assets, list):
        raise GmailRestError("gmail_live_inline_asset_invalid")
    result: list[dict[str, Any]] = []
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("filename"), str):
            raise GmailRestError("gmail_live_inline_asset_invalid")
        path = require_owner_file(
            candidate / "inputs" / item.preview_name / "assets" / asset["filename"]
        )
        result.append({**asset, "data": path.read_bytes()})
    return result


def _message_request(
    candidate: Path,
    item: FrozenCanaryItem,
    recipient: str,
) -> dict[str, Any]:
    render_path = require_owner_file(
        candidate / "inputs" / item.preview_name / "render.json"
    )
    if sha256_file(render_path) != item.render_sha256:
        raise GmailRestError("gmail_live_frozen_render_changed")
    render = read_owner_json(render_path)
    validate_schema(render, _frozen_render_schema(item))
    return {
        "recipient": recipient,
        "subject": str(render["subject"]),
        "plain": str(render["text"]),
        "html": str(render["html"]),
        "source_sha256": str(render["view_sha256"]),
        "date_value": item.date_value,
        "inline_assets": _assets(candidate, item, render),
    }


def _request_record(
    request: dict[str, Any], item: FrozenCanaryItem, recipient_sha: str
) -> dict[str, Any]:
    raw, message_id, mime_sha = deterministic_mime_v2(**request)
    record = {
        "schema_version": "m11_live_canary_request_v1",
        "kind": item.kind,
        "period_start": item.period_start,
        "period_end": item.period_end,
        "render_output_id": item.output_id,
        "render_output_sha256": item.output_sha256,
        "render_sha256": item.render_sha256,
        "recipient_sha256": recipient_sha,
        "subject_sha256": sha256_text(str(request["subject"])),
        "requested_message_id": message_id,
        "mime_sha256": mime_sha,
        "mime_byte_size": len(raw),
        "max_api_calls": MAX_ACTION_CALLS,
        "max_send_calls": 1,
    }
    if item.item_key is not None:
        record["item_key"] = _frozen_item_key(item)
        record["preview_name"] = item.preview_name
    return record


def _source_output_valid(
    connection: sqlite3.Connection,
    item: FrozenCanaryItem,
    render: dict[str, Any],
) -> bool:
    row = connection.execute(
        "SELECT schema_name,period_start_date,period_end_date,title_text,content_json,"
        "content_text,content_html,content_sha256 FROM skill_outputs WHERE id=?",
        (item.output_id,),
    ).fetchone()
    if row is None:
        return False
    try:
        stored_json = json.loads(str(row[4]))
    except json.JSONDecodeError:
        return False
    return (
        str(row[0]) == _frozen_render_schema(item)
        and str(row[1]) == item.period_start
        and str(row[2]) == item.period_end
        and str(row[3]) == render["subject"]
        and stored_json == render
        and str(row[5]) == render["text"]
        and str(row[6]) == render["html"]
        and str(row[7]) == item.output_sha256
    )


def _prepare_actions(
    database: Path,
    candidate: Path,
    recipient: str,
    recipient_sha: str,
) -> list[dict[str, Any]]:
    connection = connect(database)
    try:
        manifest = {
            "schema_version": "m11_live_canary_prepare_v1",
            "batch_id": BATCH_ID,
            "renders": [item.render_sha256 for item in FROZEN_ITEMS],
            "recipient_sha256": recipient_sha,
            "max_actions": len(FROZEN_ITEMS),
        }
        digest = sha256_text(canonical_json(manifest))
        run_id = begin_run(
            connection,
            run_key=f"m11-live-prepare:{digest}:attempt-1",
            workflow_key=WORKFLOW_KEY,
            dedupe_key=digest,
            skill_name="gmail-sender",
            operation="send_email",
            trigger_kind="manual",
            input_manifest=manifest,
            target_from_date="2026-08-12",
            target_through_date="2026-08-18",
        )
        prepared: list[dict[str, Any]] = []
        for ordinal, item in enumerate(FROZEN_ITEMS, start=1):
            item_key = _frozen_item_key(item)
            render = read_owner_json(
                candidate / "inputs" / item.preview_name / "render.json"
            )
            if not _source_output_valid(connection, item, render):
                raise GmailRestError("gmail_live_source_output_changed")
            request = _message_request(candidate, item, recipient)
            record = _request_record(request, item, recipient_sha)
            request_text = canonical_json(record)
            request_sha = sha256_text(request_text)
            delivery_manifest = {
                "schema_version": "m11_live_canary_delivery_run_v1",
                "batch_id": BATCH_ID,
                "kind": item.kind,
                "item_key": item_key,
                "request_sha256": request_sha,
            }
            delivery_manifest_text = canonical_json(delivery_manifest)
            delivery_digest = sha256_text(delivery_manifest_text)
            delivery_run_id = require_lastrowid(
                connection.execute(
                    """INSERT INTO skill_runs
                    (run_key,workflow_key,dedupe_key,parent_run_id,skill_name,
                     operation,trigger_kind,target_from_date,target_through_date,
                     attempt_no,input_manifest_json,input_sha256,status,created_at_utc)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        f"m11-live-delivery:{item_key}:{request_sha}:attempt-1",
                        WORKFLOW_KEY,
                        delivery_digest,
                        run_id,
                        "gmail-sender",
                        "send_email",
                        "manual",
                        item.period_start,
                        item.period_end,
                        1,
                        delivery_manifest_text,
                        delivery_digest,
                        "pending",
                        utc_now(),
                    ),
                )
            )
            target_key = (
                f"{TARGET_KEY_PREFIX}:{item_key}:{item.period_end}:{request_sha[:16]}"
            )
            scope = {
                "provider": "gmail",
                "action_kind": "gmail_send",
                "entity_kind": "email",
                "target_key": target_key,
                "scope_kind": "gmail",
                "budget": {"max_actions": 1},
            }
            scope_text = canonical_json(scope)
            decided = utc_now()
            approval_id = require_lastrowid(
                connection.execute(
                    """INSERT INTO approvals
                    (approval_key,candidate_output_id,candidate_output_sha256,
                     authority_kind,decision,scope_kind,scope_json,scope_sha256,
                     source_ref,reason_code,decided_at_utc,valid_from_utc,valid_until_utc)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        sha256_text(
                            canonical_json(
                                {
                                    "batch": BATCH_ID,
                                    "item_key": item_key,
                                    "ordinal": ordinal,
                                }
                            )
                        ),
                        item.output_id,
                        item.output_sha256,
                        "user_explicit",
                        "approved",
                        "gmail",
                        scope_text,
                        sha256_text(scope_text),
                        APPROVAL_SOURCE_REF,
                        APPROVAL_REASON_CODE,
                        decided,
                        decided,
                        None,
                    ),
                )
            )
            action_id = require_lastrowid(
                connection.execute(
                    """INSERT INTO external_actions
                    (idempotency_key,skill_run_id,provider,entity_kind,action_kind,
                     source_output_id,source_output_sha256,approval_id,target_key,
                     request_json,request_sha256,status,attempt_count,prepared_at_utc)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        sha256_text(
                            canonical_json({"batch": BATCH_ID, "request": record})
                        ),
                        delivery_run_id,
                        "gmail",
                        "email",
                        "gmail_send",
                        item.output_id,
                        item.output_sha256,
                        approval_id,
                        target_key,
                        request_text,
                        request_sha,
                        "prepared",
                        0,
                        utc_now(),
                    ),
                )
            )
            stored_item = {
                "ordinal": ordinal,
                "kind": item.kind,
                "action_id": action_id,
                "delivery_run_id": delivery_run_id,
                "approval_id": approval_id,
                "request_sha256": request_sha,
                "requested_message_id": record["requested_message_id"],
                "mime_sha256": record["mime_sha256"],
                "render_sha256": item.render_sha256,
                "output_id": item.output_id,
                "output_sha256": item.output_sha256,
            }
            if item.item_key is not None:
                stored_item.update(
                    {
                        "item_key": item_key,
                        "preview_name": item.preview_name,
                        "period_start": item.period_start,
                        "period_end": item.period_end,
                    }
                )
            prepared.append(stored_item)
        finish_run(connection, run_id, status="succeeded")
        connection.commit()
        return prepared
    finally:
        connection.close()


def build_candidate(candidate_root: Path) -> dict[str, Any]:
    candidate = Path(os.path.abspath(candidate_root))
    repository = RUNTIME_SOURCE_ROOT.parent.resolve()
    if (
        candidate.exists()
        or candidate.is_symlink()
        or candidate == repository
        or candidate.is_relative_to(repository)
    ):
        raise GmailRestError("gmail_live_candidate_scope_invalid")
    parent = require_owner_directory(FROZEN_R03_ROOT)
    build_receipt = require_owner_file(parent / "build-receipt.json")
    database = require_owner_file(parent / "source/state/trainlab.db")
    if (
        sha256_file(build_receipt) != FROZEN_BUILD_RECEIPT_SHA256
        or sha256_file(database) != FROZEN_PARENT_DATABASE_SHA256
    ):
        raise GmailRestError("gmail_live_frozen_parent_changed")
    for item in FROZEN_ITEMS:
        _validated_render(parent, item)
    recipient, recipient_sha = read_recipient(PRIVATE_SOURCE_ROOT / "email.json")
    auth_sha = _auth_receipt_sha()
    _token_snapshot()
    historical = _historical_live_evidence()
    with _hold_formal_state_lock():
        formal_before = _formal_state_fingerprint(FORMAL_SOURCE_ROOT)

    candidate.mkdir(mode=0o700)
    private_directory(candidate / "source")
    private_directory(candidate / "source/state")
    private_directory(candidate / "inputs")
    _backup_database(database, candidate / "source/state/trainlab.db")
    for item in FROZEN_ITEMS:
        _copy_preview(parent, candidate, item)
    with _hold_formal_state_lock():
        formal_after_copy = _formal_state_fingerprint(FORMAL_SOURCE_ROOT)
    if formal_after_copy != formal_before:
        raise GmailRestError("gmail_live_formal_state_changed")
    atomic_json(candidate / "formal-state-before.json", formal_before)
    prepared = _prepare_actions(
        candidate / "source/state/trainlab.db", candidate, recipient, recipient_sha
    )
    action_ids = [int(item["action_id"]) for item in prepared]
    marker = {
        "schema_version": MARKER_SCHEMA_VERSION,
        "batch_id": BATCH_ID,
        "database": str(candidate / "source/state/trainlab.db"),
        "parent_database_sha256": FROZEN_PARENT_DATABASE_SHA256,
        "parent_build_receipt_sha256": FROZEN_BUILD_RECEIPT_SHA256,
        "runtime_sha256": _runtime_sha256(),
        "formal_state_sha256": str(formal_before["sha256"]),
        "recipient_sha256": recipient_sha,
        "auth_receipt_sha256": auth_sha,
        "auth_provider_calls": AUTH_API_CALLS,
        "items": prepared,
        "action_ids": action_ids,
        "action_api_calls": {str(action_id): 0 for action_id in action_ids},
        "action_phase_calls": {
            str(action_id): {phase: 0 for phase in READ_PHASES}
            for action_id in action_ids
        },
        "action_send_calls": {str(action_id): 0 for action_id in action_ids},
        "api_calls": 0,
        "send_calls": 0,
        "created_at_utc": utc_now(),
    }
    if REQUIRE_MANUAL_CONFIRMATION:
        marker.update(
            {
                "daily_confirmed": False,
                "daily_confirmation_sha256": None,
                "weekly_confirmed": False,
                "weekly_confirmation_sha256": None,
            }
        )
    else:
        marker.update(
            {
                "authorization_rule": "A-017",
                "strict_serial": True,
                "authorized_action_count": len(FROZEN_ITEMS),
            }
        )
    if historical is not None:
        marker.update(historical)
    validate_schema(marker, MARKER_SCHEMA_NAME)
    atomic_json(candidate / MARKER_NAME, marker)
    receipt = {
        "schema_version": "m11_live_canary_build_receipt_v1",
        "status": "succeeded",
        "candidate_root": str(candidate),
        "actions": len(FROZEN_ITEMS),
        "provider_calls": 0,
        "send_calls": 0,
    }
    atomic_json(candidate / "build-receipt.json", receipt)
    verify_candidate(candidate)
    return receipt


def _stored_item_key(item: dict[str, Any]) -> str:
    value = item.get("item_key", item.get("kind"))
    if not isinstance(value, str) or not value:
        raise GmailRestError("gmail_live_candidate_invalid")
    return value


def _load_marker(candidate_root: Path) -> dict[str, Any]:
    candidate = require_owner_directory(candidate_root)
    marker = read_owner_json(candidate / MARKER_NAME)
    validate_schema(marker, MARKER_SCHEMA_NAME)
    action_ids = marker["action_ids"]
    action_keys = {str(value) for value in action_ids}
    items = marker["items"]
    expected_count = len(FROZEN_ITEMS)
    expected_item_keys = [_frozen_item_key(item) for item in FROZEN_ITEMS]
    expected_kinds = [item.kind for item in FROZEN_ITEMS]
    if (
        marker["batch_id"] != BATCH_ID
        or marker["runtime_sha256"] != _runtime_sha256()
        or Path(os.path.abspath(marker["database"]))
        != candidate / "source/state/trainlab.db"
        or len(action_ids) != expected_count
        or len(set(action_ids)) != expected_count
        or [_stored_item_key(item) for item in items] != expected_item_keys
        or [item["kind"] for item in items] != expected_kinds
        or [item["ordinal"] for item in items] != list(range(1, expected_count + 1))
        or [item["action_id"] for item in items] != action_ids
        or any(int(item["delivery_run_id"]) < 1 for item in items)
        or set(marker["action_api_calls"]) != action_keys
        or set(marker["action_phase_calls"]) != action_keys
        or set(marker["action_send_calls"]) != action_keys
        or marker["api_calls"] != sum(marker["action_api_calls"].values())
        or marker["send_calls"] != sum(marker["action_send_calls"].values())
        or any(
            marker["action_api_calls"][key]
            != sum(marker["action_phase_calls"][key].values())
            + marker["action_send_calls"][key]
            for key in action_keys
        )
        or marker["api_calls"] > MAX_DELIVERY_API_CALLS
        or marker["send_calls"] > MAX_SEND_CALLS
        or marker["auth_provider_calls"] != AUTH_API_CALLS
        or marker["auth_receipt_sha256"] != _auth_receipt_sha()
        or (
            marker["schema_version"] == "m11_live_canary_candidate_v2"
            and (
                marker["historical_api_calls"] + marker["api_calls"] > 48
                or marker["historical_send_calls"] + marker["send_calls"] > 3
                or {
                    key: marker[key]
                    for key in (
                        "historical_live_marker_sha256",
                        "historical_live_database_sha256",
                        "historical_daily_gmail_id_sha256",
                        "historical_api_calls",
                        "historical_send_calls",
                        "cumulative_max_api_calls",
                        "cumulative_max_send_calls",
                    )
                }
                != _historical_live_evidence()
            )
        )
    ):
        raise GmailRestError("gmail_live_candidate_invalid")
    if REQUIRE_MANUAL_CONFIRMATION:
        if (
            marker["daily_confirmed"]
            != (marker["daily_confirmation_sha256"] is not None)
            or marker["weekly_confirmed"]
            != (marker["weekly_confirmation_sha256"] is not None)
            or (marker["weekly_confirmed"] and not marker["daily_confirmed"])
        ):
            raise GmailRestError("gmail_live_candidate_invalid")
    elif (
        marker.get("authorization_rule") != "A-017"
        or marker.get("strict_serial") is not True
        or marker.get("authorized_action_count") != expected_count
    ):
        raise GmailRestError("gmail_live_candidate_invalid")
    return marker


def _check_formal_state(candidate: Path, marker: dict[str, Any]) -> None:
    before = read_owner_json(candidate / "formal-state-before.json")
    with _hold_formal_state_lock():
        current = _formal_state_fingerprint(FORMAL_SOURCE_ROOT)
    if before != current or before.get("sha256") != marker.get("formal_state_sha256"):
        raise GmailRestError("gmail_live_formal_state_changed")


def _item(
    marker: dict[str, Any], item_key: str
) -> tuple[FrozenCanaryItem, dict[str, Any]]:
    frozen = next(
        (item for item in FROZEN_ITEMS if _frozen_item_key(item) == item_key), None
    )
    stored = next(
        (item for item in marker["items"] if _stored_item_key(item) == item_key), None
    )
    if frozen is None or stored is None:
        raise GmailRestError("gmail_live_action_invalid")
    return frozen, stored


def _action_row(connection: sqlite3.Connection, action_id: int) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM external_actions WHERE id=?", (action_id,)
    ).fetchone()
    if row is None:
        raise GmailRestError("gmail_live_action_invalid")
    return row


def _latest_delivery_run(connection: sqlite3.Connection, action_id: int) -> sqlite3.Row:
    row = connection.execute(
        """SELECT latest.* FROM external_actions action
        JOIN skill_runs initial ON initial.id=action.skill_run_id
        JOIN skill_runs latest ON latest.dedupe_key=initial.dedupe_key
        WHERE action.id=? ORDER BY latest.attempt_no DESC LIMIT 1""",
        (action_id,),
    ).fetchone()
    if row is None:
        raise GmailRestError("gmail_live_delivery_run_missing")
    return row


def _start_delivery_run(connection: sqlite3.Connection, action_id: int) -> int:
    latest = _latest_delivery_run(connection, action_id)
    status = str(latest["status"])
    if status == "running":
        interrupted_at = utc_now()
        connection.execute(
            """UPDATE skill_runs SET status='interrupted',finished_at_utc=?,
            heartbeat_at_utc=?,lease_expires_at_utc=NULL,
            error_code='gmail_live_interrupted',error_summary='prior process ended'
            WHERE id=?""",
            (interrupted_at, interrupted_at, int(latest["id"])),
        )
        connection.commit()
        latest = _latest_delivery_run(connection, action_id)
        status = str(latest["status"])
    if status == "pending":
        now_dt = datetime.now(timezone.utc).replace(microsecond=0)
        now = now_dt.isoformat().replace("+00:00", "Z")
        lease = (now_dt + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
        connection.execute(
            """UPDATE skill_runs SET status='running',started_at_utc=?,
            heartbeat_at_utc=?,lease_expires_at_utc=? WHERE id=? AND status='pending'""",
            (now, now, lease, int(latest["id"])),
        )
        connection.commit()
        return int(latest["id"])
    if status in {"interrupted", "blocked", "failed"}:
        manifest = json.loads(str(latest["input_manifest_json"]))
        run_id = begin_run(
            connection,
            run_key=str(latest["run_key"]).rsplit(":attempt-", 1)[0] + ":attempt-1",
            workflow_key=str(latest["workflow_key"]),
            dedupe_key=str(latest["dedupe_key"]),
            parent_run_id=int(latest["id"]),
            skill_name="gmail-sender",
            operation="reconcile_gmail",
            trigger_kind="recovery",
            input_manifest=manifest,
            target_from_date=latest["target_from_date"],
            target_through_date=latest["target_through_date"],
        )
        return run_id
    raise GmailRestError("gmail_live_delivery_run_invalid")


def _finish_delivery_run(
    connection: sqlite3.Connection,
    action_id: int,
    *,
    status: str,
    error_code: str | None,
    error_summary: str | None,
) -> None:
    latest = _latest_delivery_run(connection, action_id)
    if str(latest["status"]) in {"succeeded", "failed", "blocked", "cancelled"}:
        if str(latest["status"]) != status:
            raise GmailRestError("gmail_live_delivery_run_terminal_mismatch")
        return
    if str(latest["status"]) not in {"pending", "running"}:
        raise GmailRestError("gmail_live_delivery_run_invalid")
    now = utc_now()
    connection.execute(
        """UPDATE skill_runs SET status=?,finished_at_utc=?,heartbeat_at_utc=?,
        lease_expires_at_utc=NULL,error_code=?,error_summary=? WHERE id=?""",
        (status, now, now, error_code, error_summary, int(latest["id"])),
    )


class GmailReadableRestTransport:
    """Adapt the validated REST client to the readable single-send controller."""

    def __init__(self, *, client: Any, action_id: int, run_root: Path) -> None:
        self.client = client
        self.action_id = action_id
        self.run_root = require_owner_directory(run_root)
        self._raw_read = False

    def search_rfc822(self, message_id: str) -> list[str]:
        confirmation = self._raw_read
        return self.client.list_message(
            message_id,
            action_id=self.action_id,
            kind="readable-confirmation" if confirmation else "readable-lookup",
            retry_empty=confirmation or (self.run_root / "send-started.json").exists(),
            phase="confirmation" if confirmation else "lookup",
        )

    def send(self, raw: bytes) -> str:
        return str(self.client.send(raw, action_id=self.action_id))

    def get_raw(self, gmail_id: str) -> bytes:
        raw = bytes(self.client.get_raw(gmail_id, action_id=self.action_id))
        path = self.run_root / "provider.eml"
        if path.exists():
            if require_owner_file(path).read_bytes() != raw:
                raise GmailRestError("gmail_live_remote_raw_changed")
        else:
            atomic_write(path, raw)
        self._raw_read = True
        return raw

    def recover_sent_gmail_id(self, raw_sha256: str) -> str | None:
        return self.client.recover_sent_gmail_id(
            raw_sha256,
            action_id=self.action_id,
        )


def _live_transport(
    candidate: Path,
    marker: dict[str, Any],
    action_id: int,
    run_root: Path,
) -> ReadableMailTransport:
    private_directory(candidate / "gmail-rest")
    private_directory(candidate / "gmail-rest/captures")
    client = GmailRestClient(
        token_file=PRIVATE_SOURCE_ROOT / "gmail-api-token.json",
        candidate_root=candidate,
        marker=marker,
        marker_name=MARKER_NAME,
        max_provider_calls=MAX_PROVIDER_CALLS_WITH_AUTH,
        max_send_calls=MAX_SEND_CALLS,
    )
    return GmailReadableRestTransport(
        client=client, action_id=action_id, run_root=run_root
    )


def _terminal_status(result: dict[str, Any], run_root: Path) -> str:
    if result["status"] == "succeeded":
        return "succeeded"
    if (
        result["status"] == "blocked"
        and result.get("gmail_message_id") is None
        and result.get("error_code")
        in {"gmail_rest_auth_invalid", "gmail_rest_send_rejected"}
    ):
        return "failed_safe"
    if (
        result["status"] == "unknown"
        or (run_root / "send-started.json").exists()
        or (run_root / "send-response.json").exists()
    ):
        return "unknown"
    if result.get("send_calls") == 1 and result.get("error_code") not in {
        "gmail_rest_auth_invalid",
        "gmail_rest_send_rejected",
    }:
        return "unknown"
    return "failed_safe"


def _stable_error_code(
    result: dict[str, Any], external_status: str, run_root: Path
) -> str | None:
    if external_status == "succeeded":
        return None
    detail = str(result.get("error_code") or "")
    if "interrupted" in detail:
        return "gmail_live_interrupted"
    if "internal" in detail or "invariant" in detail:
        return "gmail_live_internal_invariant"
    if any(
        value in detail
        for value in (
            "mime_mismatch",
            "confirmation_mismatch",
            "multiple_matches",
            "remote_raw_changed",
        )
    ):
        return "gmail_live_remote_mismatch"
    if any(
        value in detail
        for value in (
            "query_transport_failed",
            "get_failed",
            "read_budget_exceeded",
            "provider_unavailable",
        )
    ):
        return "gmail_live_read_retry_exhausted"
    if external_status == "failed_safe":
        return "gmail_live_preflight_failed"
    if external_status == "unknown" or (run_root / "send-started.json").exists():
        return "gmail_live_send_result_unknown"
    return "gmail_live_preflight_failed"


def _record_action_result(
    database: Path,
    action_id: int,
    result: dict[str, Any],
    marker: dict[str, Any],
    run_root: Path,
) -> None:
    status = _terminal_status(result, run_root)
    error_code = _stable_error_code(result, status, run_root)
    provider_eml = run_root / "provider.eml"
    provider_eml_sha = (
        sha256_file(require_owner_file(provider_eml)) if provider_eml.exists() else None
    )
    summary = {
        "schema_version": "m11_live_canary_action_result_v1",
        "verified": result["status"] == "succeeded",
        "delivery_receipt_sha256": sha256_text(canonical_json(result)),
        "provider_eml_sha256": provider_eml_sha,
        "actual_rfc822_message_id": result.get("actual_rfc822_message_id"),
        "detail_error_code": result.get("error_code"),
        "high_level_provider_calls": result["provider_calls"],
        "actual_api_calls": marker["action_api_calls"][str(action_id)],
        "send_calls": marker["action_send_calls"][str(action_id)],
    }
    connection = connect(database)
    try:
        row = _action_row(connection, action_id)
        if str(row["status"]) in {"succeeded", "failed_safe", "unknown"}:
            return
        connection.execute(
            """UPDATE external_actions SET status=?,result_external_id=?,
            provider_marker=?,response_summary_json=?,error_code=?,error_summary=?,
            finished_at_utc=?,last_reconciled_at_utc=? WHERE id=?""",
            (
                status,
                result.get("gmail_message_id"),
                result.get("actual_rfc822_message_id"),
                canonical_json(summary),
                error_code,
                result.get("error_code"),
                utc_now(),
                utc_now(),
                action_id,
            ),
        )
        run_status = "succeeded" if status == "succeeded" else "blocked"
        if error_code == "gmail_live_internal_invariant":
            run_status = "failed"
        _finish_delivery_run(
            connection,
            action_id,
            status=run_status,
            error_code=error_code,
            error_summary=str(result.get("error_code") or "") or None,
        )
        connection.commit()
    finally:
        connection.close()


def _deliver_locked(
    *,
    candidate: Path,
    marker: dict[str, Any],
    action_id: int,
    database: Path,
    kind: str,
    request: dict[str, Any],
    before_token: dict[str, Any],
    transport: ReadableMailTransport | None,
) -> dict[str, Any]:
    private_directory(candidate / "gmail-readable")
    run_root = private_directory(candidate / "gmail-readable" / kind)
    connection = connect(database)
    try:
        row = _action_row(connection, action_id)
        status = str(row["status"])
    finally:
        connection.close()
    existing_result = run_root / "result.json"
    if status in {"succeeded", "failed_safe", "unknown"}:
        if not existing_result.exists():
            raise GmailRestError("gmail_live_result_missing")
        result = read_owner_json(existing_result)
        validate_schema(result, "gmail_readable_delivery_receipt_v1")
        return result
    if status not in {"prepared", "in_progress"}:
        raise GmailRestError("gmail_live_action_not_deliverable")

    atomic_json(run_root / "token-before.json", before_token)
    connection = connect(database)
    try:
        _start_delivery_run(connection, action_id)
        if status == "prepared":
            connection.execute(
                "UPDATE external_actions SET status='in_progress',attempt_count=1,"
                "started_at_utc=? WHERE id=?",
                (utc_now(), action_id),
            )
            connection.commit()
    finally:
        connection.close()
    selected_transport = transport or _live_transport(
        candidate, marker, action_id, run_root
    )
    result = deliver_once(run_root, request, selected_transport)
    marker = _load_marker(candidate)
    after_token = _token_snapshot()
    atomic_json(run_root / "token-after.json", after_token)
    validate_schema(marker, MARKER_SCHEMA_NAME)
    atomic_json(candidate / MARKER_NAME, marker)
    if (
        isinstance(selected_transport, GmailReadableRestTransport)
        and result["status"] == "succeeded"
    ):
        require_owner_file(run_root / "provider.eml")
    _record_action_result(database, action_id, result, marker, run_root)
    verify_candidate(candidate)
    return result


def _record_delivery_exception(
    *,
    candidate: Path,
    marker: dict[str, Any],
    database: Path,
    stored: dict[str, Any],
    kind: str,
    error: GmailRestError,
) -> None:
    action_id = int(stored["action_id"])
    run_root = private_directory(candidate / "gmail-readable" / kind)
    result_path = run_root / "result.json"
    current_marker = read_owner_json(candidate / MARKER_NAME)
    validate_schema(current_marker, MARKER_SCHEMA_NAME)
    if result_path.exists():
        result = read_owner_json(result_path)
        validate_schema(result, "gmail_readable_delivery_receipt_v1")
        _record_action_result(database, action_id, result, current_marker, run_root)
        return
    # This is the failure path for dynamic prerequisites such as the private
    # auth receipt itself.  Re-read only the durable Candidate ledger here;
    # calling _load_marker() would re-run the failed prerequisite and prevent
    # the external action and Skill run from reaching their paired terminal.
    send_calls = int(current_marker["action_send_calls"][str(action_id)])
    status = "unknown" if (run_root / "send-started.json").exists() else "blocked"
    result = {
        "schema_version": "gmail_readable_delivery_receipt_v1",
        "status": status,
        "error_code": str(error),
        "request_sha256": stored["request_sha256"],
        "requested_message_id": stored["requested_message_id"],
        "mime_sha256": stored["mime_sha256"],
        "gmail_message_id": None,
        "actual_rfc822_message_id": None,
        "provider_calls": 0,
        "send_calls": min(send_calls, 1),
    }
    validate_schema(result, "gmail_readable_delivery_receipt_v1")
    atomic_json(result_path, result)
    _record_action_result(database, action_id, result, current_marker, run_root)


def _require_serial_predecessors(
    marker: dict[str, Any], database: Path, item_key: str
) -> None:
    if not STRICT_SERIAL:
        return
    keys = [_stored_item_key(item) for item in marker["items"]]
    try:
        index = keys.index(item_key)
    except ValueError as exc:
        raise GmailRestError("gmail_live_action_invalid") from exc
    if index == 0:
        return
    prior = marker["items"][:index]
    placeholders = ",".join("?" for _ in prior)
    connection = connect(database, read_only=True, immutable=True)
    try:
        rows = connection.execute(
            f"SELECT id,status FROM external_actions WHERE id IN ({placeholders}) "
            "ORDER BY id",
            tuple(int(item["action_id"]) for item in prior),
        ).fetchall()
    finally:
        connection.close()
    if len(rows) != len(prior) or any(
        str(row["status"]) != "succeeded" for row in rows
    ):
        raise GmailRestError("gmail_live_prior_action_not_succeeded")


def _deliver(
    candidate_root: Path,
    item_key: str,
    *,
    transport: ReadableMailTransport | None = None,
) -> dict[str, Any]:
    candidate = require_owner_directory(candidate_root)
    raw_marker = read_owner_json(candidate / MARKER_NAME)
    validate_schema(raw_marker, MARKER_SCHEMA_NAME)
    database = Path(raw_marker["database"])
    stored = next(
        (item for item in raw_marker["items"] if _stored_item_key(item) == item_key),
        None,
    )
    if stored is None:
        raise GmailRestError("gmail_live_action_invalid")
    with workflow_lock(database):
        try:
            marker = _load_marker(candidate)
            _check_formal_state(candidate, marker)
            frozen, stored = _item(marker, item_key)
            _require_serial_predecessors(marker, database, item_key)
            if REQUIRE_MANUAL_CONFIRMATION and frozen.kind == "weekly":
                daily = next(
                    item for item in marker["items"] if item["kind"] == "daily"
                )
                connection = connect(
                    Path(marker["database"]), read_only=True, immutable=True
                )
                try:
                    daily_status = str(
                        _action_row(connection, int(daily["action_id"]))["status"]
                    )
                finally:
                    connection.close()
                if daily_status != "succeeded":
                    raise GmailRestError("gmail_live_daily_not_succeeded")
                if marker["daily_confirmed"] is not True:
                    raise GmailRestError("gmail_live_daily_confirmation_required")
                confirmation = read_owner_json(
                    candidate / "daily-user-confirmation.json"
                )
                validate_schema(confirmation, "m11_live_canary_confirmation_v1")
                if (
                    confirmation.get("web_confirmed") is not True
                    or confirmation.get("mobile_confirmed") is not True
                ):
                    raise GmailRestError("gmail_live_daily_confirmation_required")
            recipient, recipient_sha = read_recipient(
                PRIVATE_SOURCE_ROOT / "email.json"
            )
            if recipient_sha != marker["recipient_sha256"]:
                raise GmailRestError("gmail_live_recipient_changed")
            request = _message_request(candidate, frozen, recipient)
            record = _request_record(request, frozen, recipient_sha)
            if (
                sha256_text(canonical_json(record)) != stored["request_sha256"]
                or record["requested_message_id"] != stored["requested_message_id"]
                or record["mime_sha256"] != stored["mime_sha256"]
            ):
                raise GmailRestError("gmail_live_request_changed")
            before_token = _token_snapshot()
            action_id = int(stored["action_id"])
            return _deliver_locked(
                candidate=candidate,
                marker=marker,
                action_id=action_id,
                database=database,
                kind=item_key,
                request=request,
                before_token=before_token,
                transport=transport,
            )
        except (GmailRestError, OSError) as exc:
            stable_error = (
                exc
                if isinstance(exc, GmailRestError)
                else GmailRestError("gmail_live_local_io_failed")
            )
            if str(stable_error) not in {
                "gmail_live_daily_not_succeeded",
                "gmail_live_daily_confirmation_required",
                "gmail_live_prior_action_not_succeeded",
            }:
                _record_delivery_exception(
                    candidate=candidate,
                    marker=raw_marker,
                    database=database,
                    stored=stored,
                    kind=item_key,
                    error=stable_error,
                )
            if stable_error is exc:
                raise
            raise stable_error from exc


def deliver_daily(
    candidate_root: Path, *, transport: ReadableMailTransport | None = None
) -> dict[str, Any]:
    return _deliver(candidate_root, "daily", transport=transport)


def deliver_weekly(
    candidate_root: Path, *, transport: ReadableMailTransport | None = None
) -> dict[str, Any]:
    return _deliver(candidate_root, "weekly", transport=transport)


def deliver_batch(
    candidate_root: Path, *, transport: ReadableMailTransport | None = None
) -> dict[str, Any]:
    """Deliver the active frozen policy in ordinal order and stop on first non-success."""

    completed = 0
    for frozen in FROZEN_ITEMS:
        item_key = _frozen_item_key(frozen)
        result = _deliver(candidate_root, item_key, transport=transport)
        if result["status"] != "succeeded":
            marker = _load_marker(candidate_root)
            return {
                "status": result["status"],
                "completed_actions": completed,
                "stopped_item_key": item_key,
                "api_calls": marker["api_calls"],
                "send_calls": marker["send_calls"],
            }
        completed += 1
    marker = _load_marker(candidate_root)
    return {
        "status": "succeeded",
        "completed_actions": completed,
        "stopped_item_key": None,
        "api_calls": marker["api_calls"],
        "send_calls": marker["send_calls"],
    }


def _confirm(
    candidate_root: Path, kind: str, *, user_confirmed: bool
) -> dict[str, Any]:
    if not REQUIRE_MANUAL_CONFIRMATION:
        raise GmailRestError("gmail_live_confirmation_not_applicable")
    if not user_confirmed:
        raise GmailRestError("gmail_live_user_confirmation_required")
    candidate = require_owner_directory(candidate_root)
    marker = _load_marker(candidate)
    _check_formal_state(candidate, marker)
    database = Path(marker["database"])
    with workflow_lock(database):
        marker = _load_marker(candidate)
        _frozen, stored = _item(marker, kind)
        connection = connect(database, read_only=True, immutable=True)
        try:
            row = _action_row(connection, int(stored["action_id"]))
        finally:
            connection.close()
        if str(row["status"]) != "succeeded" or not row["result_external_id"]:
            raise GmailRestError(f"gmail_live_{kind}_not_succeeded")
        field = f"{kind}_confirmed"
        sha_field = f"{kind}_confirmation_sha256"
        path = candidate / f"{kind}-user-confirmation.json"
        if marker[field] is True:
            confirmation = read_owner_json(path)
            validate_schema(confirmation, "m11_live_canary_confirmation_v1")
            if marker[sha_field] != sha256_file(path):
                raise GmailRestError("gmail_live_confirmation_changed")
            return confirmation
        confirmation = {
            "schema_version": "m11_live_canary_confirmation_v1",
            "status": "succeeded",
            "kind": kind,
            "action_id": int(stored["action_id"]),
            "gmail_message_id_sha256": sha256_text(str(row["result_external_id"])),
            "web_confirmed": True,
            "mobile_confirmed": True,
            "provider_calls": 0,
            "confirmed_at_utc": utc_now(),
        }
        validate_schema(confirmation, "m11_live_canary_confirmation_v1")
        atomic_json(path, confirmation)
        marker[field] = True
        marker[sha_field] = sha256_file(path)
        validate_schema(marker, MARKER_SCHEMA_NAME)
        atomic_json(candidate / MARKER_NAME, marker)
        return confirmation


def confirm_daily(candidate_root: Path, *, user_confirmed: bool) -> dict[str, Any]:
    return _confirm(candidate_root, "daily", user_confirmed=user_confirmed)


def confirm_weekly(candidate_root: Path, *, user_confirmed: bool) -> dict[str, Any]:
    return _confirm(candidate_root, "weekly", user_confirmed=user_confirmed)


def logical_snapshot(candidate_root: Path) -> dict[str, Any]:
    candidate = require_owner_directory(candidate_root)
    marker = _load_marker(candidate)
    placeholders = ",".join("?" for _ in marker["action_ids"])
    connection = connect(Path(marker["database"]), read_only=True, immutable=True)
    try:
        actions = [
            dict(row)
            for row in connection.execute(
                "SELECT id,status,attempt_count,result_external_id,provider_marker,"
                "request_sha256,response_summary_json,error_code FROM external_actions "
                f"WHERE id IN ({placeholders}) ORDER BY id",
                tuple(marker["action_ids"]),
            ).fetchall()
        ]
        counts = {
            "skill_runs": int(
                connection.execute("SELECT COUNT(*) FROM skill_runs").fetchone()[0]
            ),
            "skill_outputs": int(
                connection.execute("SELECT COUNT(*) FROM skill_outputs").fetchone()[0]
            ),
            "approvals": int(
                connection.execute("SELECT COUNT(*) FROM approvals").fetchone()[0]
            ),
            "external_actions": int(
                connection.execute("SELECT COUNT(*) FROM external_actions").fetchone()[
                    0
                ]
            ),
        }
    finally:
        connection.close()
    files = {
        path.relative_to(candidate).as_posix(): sha256_file(path)
        for path in candidate.rglob("*")
        if path.is_file()
        and path.name
        in {
            "result.json",
            "reconciliation-result.json",
            "message.eml",
            "provider.eml",
        }
    }
    return {
        "actions": actions,
        "counts": counts,
        "files": files,
        "api_calls": marker["api_calls"],
        "send_calls": marker["send_calls"],
        "daily_confirmed": marker.get("daily_confirmed"),
        "weekly_confirmed": marker.get("weekly_confirmed"),
    }


def verify_candidate(candidate_root: Path, *, final: bool = False) -> dict[str, Any]:
    candidate = require_owner_directory(candidate_root)
    marker = _load_marker(candidate)
    _check_formal_state(candidate, marker)
    forbidden = {
        "email.json",
        "gmail-api-token.json",
        "gcp-oauth.keys.json",
        "credentials.json",
    }
    for path in candidate.rglob("*"):
        metadata = path.lstat()
        if (
            path.name in forbidden
            or path.is_symlink()
            or metadata.st_uid != os.getuid()
        ):
            raise GmailRestError("gmail_live_artifact_invalid")
        if path.is_dir():
            if stat.S_IMODE(metadata.st_mode) != 0o700:
                raise GmailRestError("gmail_live_artifact_invalid")
        elif (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or (metadata.st_size == 0 and path.name != "trainlab.lock")
        ):
            raise GmailRestError("gmail_live_artifact_invalid")
    database = require_owner_file(Path(marker["database"]))
    placeholders = ",".join("?" for _ in marker["action_ids"])
    expected_count = len(FROZEN_ITEMS)
    connection = connect(database, read_only=True, immutable=True)
    try:
        if str(connection.execute("PRAGMA integrity_check").fetchone()[0]) != "ok":
            raise GmailRestError("gmail_live_candidate_database_invalid")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise GmailRestError("gmail_live_candidate_database_invalid")
        rows = connection.execute(
            "SELECT id,status,attempt_count,result_external_id,provider_marker,"
            f"response_summary_json FROM external_actions WHERE id IN ({placeholders}) "
            "ORDER BY id",
            tuple(marker["action_ids"]),
        ).fetchall()
        run_chains = []
        for item in marker["items"]:
            chain = connection.execute(
                """SELECT id,status,attempt_no FROM skill_runs
                WHERE dedupe_key=(SELECT dedupe_key FROM skill_runs WHERE id=?)
                ORDER BY attempt_no""",
                (int(item["delivery_run_id"]),),
            ).fetchall()
            run_chains.append(chain)
    finally:
        connection.close()
    if len(rows) != expected_count or marker["send_calls"] > MAX_SEND_CALLS:
        raise GmailRestError("gmail_live_candidate_invalid")
    statuses = {
        _stored_item_key(item): str(rows[index]["status"])
        for index, item in enumerate(marker["items"])
    }
    status_sequence = list(statuses.values())
    if STRICT_SERIAL:
        found_non_success = False
        for status in status_sequence:
            if found_non_success and status != "prepared":
                raise GmailRestError("gmail_live_candidate_invalid")
            if status != "succeeded":
                found_non_success = True
    expected_run_status = {
        "prepared": {"pending"},
        "in_progress": {"running"},
        "succeeded": {"succeeded"},
        "failed_safe": {"blocked", "failed"},
        "unknown": {"blocked", "failed"},
    }
    for index, chain in enumerate(run_chains):
        action_status = str(rows[index]["status"])
        if (
            not chain
            or [int(run["attempt_no"]) for run in chain]
            != list(range(1, len(chain) + 1))
            or str(chain[-1]["status"])
            not in expected_run_status.get(action_status, set())
            or any(
                str(run["status"]) not in {"interrupted", "blocked", "failed"}
                for run in chain[:-1]
            )
        ):
            raise GmailRestError("gmail_live_candidate_run_state_invalid")
    if REQUIRE_MANUAL_CONFIRMATION:
        if marker["daily_confirmed"] and statuses["daily"] != "succeeded":
            raise GmailRestError("gmail_live_candidate_invalid")
        if statuses["weekly"] == "succeeded" and marker["daily_confirmed"] is not True:
            raise GmailRestError("gmail_live_candidate_invalid")
    if final:
        if any(status != "succeeded" for status in status_sequence):
            raise GmailRestError("gmail_live_final_incomplete")
        if REQUIRE_MANUAL_CONFIRMATION and (
            marker["daily_confirmed"] is not True
            or marker["weekly_confirmed"] is not True
        ):
            raise GmailRestError("gmail_live_final_incomplete")
        if marker["send_calls"] != expected_count or set(
            marker["action_send_calls"].values()
        ) != {1}:
            raise GmailRestError("gmail_live_final_incomplete")
        gmail_ids: set[str] = set()
        rfc822_ids: set[str] = set()
        for index, item in enumerate(marker["items"]):
            row = rows[index]
            gmail_id = str(row["result_external_id"] or "")
            rfc822_id = str(row["provider_marker"] or "")
            try:
                summary = json.loads(str(row["response_summary_json"]))
            except json.JSONDecodeError as exc:
                raise GmailRestError("gmail_live_final_incomplete") from exc
            provider_eml = require_owner_file(
                candidate / "gmail-readable" / _stored_item_key(item) / "provider.eml"
            )
            result = read_owner_json(
                candidate / "gmail-readable" / _stored_item_key(item) / "result.json"
            )
            validate_schema(result, "gmail_readable_delivery_receipt_v1")
            if (
                not gmail_id
                or not rfc822_id
                or result.get("status") != "succeeded"
                or result.get("gmail_message_id") != gmail_id
                or result.get("actual_rfc822_message_id") != rfc822_id
                or summary.get("verified") is not True
                or summary.get("provider_eml_sha256") != sha256_file(provider_eml)
                or summary.get("actual_rfc822_message_id") != rfc822_id
            ):
                raise GmailRestError("gmail_live_final_incomplete")
            gmail_ids.add(gmail_id)
            rfc822_ids.add(rfc822_id)
        if len(gmail_ids) != expected_count or len(rfc822_ids) != expected_count:
            raise GmailRestError("gmail_live_final_incomplete")
        _token_snapshot()
        with _hold_formal_state_lock():
            after = _formal_state_fingerprint(FORMAL_SOURCE_ROOT)
        if after != read_owner_json(candidate / "formal-state-before.json"):
            raise GmailRestError("gmail_live_formal_state_changed")
        atomic_json(candidate / "formal-state-after.json", after)
    return {
        "status": "succeeded",
        "final": final,
        "api_calls": marker["api_calls"],
        "send_calls": marker["send_calls"],
        "daily_confirmed": marker.get("daily_confirmed"),
        "weekly_confirmed": marker.get("weekly_confirmed"),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in (
        "build-candidate",
        "deliver-daily",
        "confirm-daily",
        "deliver-weekly",
        "confirm-weekly",
        "verify",
        "build-health-correction",
        "deliver-corrected-daily",
        "confirm-corrected-daily",
        "deliver-correction-weekly",
        "confirm-correction-weekly",
        "verify-health-correction",
        "build-v3-batch",
        "deliver-v3-batch",
        "verify-v3-batch",
    ):
        command = commands.add_parser(name)
        command.add_argument("--candidate-root", type=Path, required=True)
        if name.startswith("confirm-"):
            command.add_argument("--user-confirmed", action="store_true")
        if name in {"verify", "verify-health-correction", "verify-v3-batch"}:
            command.add_argument("--final", action="store_true")
    return result


def main() -> int:
    os.umask(0o077)
    args = parser().parse_args()
    correction = args.command in {
        "build-health-correction",
        "deliver-corrected-daily",
        "confirm-corrected-daily",
        "deliver-correction-weekly",
        "confirm-correction-weekly",
        "verify-health-correction",
    }
    if correction:
        _activate_health_correction_policy()
    v3_batch = args.command in {
        "build-v3-batch",
        "deliver-v3-batch",
        "verify-v3-batch",
    }
    if v3_batch:
        _activate_v3_batch_policy()
    if args.command in {
        "build-candidate",
        "build-health-correction",
        "build-v3-batch",
    }:
        result = build_candidate(args.candidate_root)
    elif args.command == "deliver-v3-batch":
        result = deliver_batch(args.candidate_root)
    elif args.command in {"deliver-daily", "deliver-corrected-daily"}:
        result = deliver_daily(args.candidate_root)
    elif args.command in {"confirm-daily", "confirm-corrected-daily"}:
        result = confirm_daily(args.candidate_root, user_confirmed=args.user_confirmed)
    elif args.command in {"deliver-weekly", "deliver-correction-weekly"}:
        result = deliver_weekly(args.candidate_root)
    elif args.command in {"confirm-weekly", "confirm-correction-weekly"}:
        result = confirm_weekly(args.candidate_root, user_confirmed=args.user_confirmed)
    else:
        result = verify_candidate(args.candidate_root, final=args.final)
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
