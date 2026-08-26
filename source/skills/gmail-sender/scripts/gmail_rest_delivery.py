#!/usr/bin/env python3
"""M10 r06 owner-only Gmail REST candidate builder and delivery host."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import time
from collections.abc import Callable
from datetime import date, datetime
from datetime import time as datetime_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from requests import exceptions as requests_exceptions

RUNTIME_SOURCE_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = RUNTIME_SOURCE_ROOT
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from gmail_rest_common import (  # noqa: E402
    API_ROOT,
    AUTH_RECEIPT_NAME,
    SCOPES,
    GmailRestError,
    atomic_json,
    atomic_write,
    canonical_json,
    decode_gmail_raw,
    deterministic_mime,
    gmail_raw,
    private_directory,
    read_owner_json,
    read_recipient,
    require_gmail_message_id,
    require_owner_directory,
    require_owner_file,
    sanitize_capture,
    sha256_bytes,
    sha256_file,
    sha256_text,
    validate_schema,
    verify_mime,
)

from skills._shared.state import (  # noqa: E402
    append_output,
    begin_run,
    connect,
    finish_run,
    require_lastrowid,
    utc_now,
    workflow_lock,
)

BATCH_ID = "m10-r06-gmail-rest"
WORKFLOW_KEY = "m10:r06:gmail:2026-08-19"
MARKER_NAME = "m10-r06-candidate.json"
PARENT_SOURCE = Path("/private/tmp/trainlab-m10-candidate-r04.2S54J0/source")
PARENT_RUN_ROOT = Path("/private/tmp/m10-r04-real.S0eqCa/run")
EXPECTED_PARENT_DATABASE_SHA256 = (
    "ea49faaff60eb8dad06a96086c1a34744a91ee6150db5ff0bad0c9ab217abe92"
)
EXPECTED_PARENT_FINGERPRINT_SHA256 = (
    "e8daa61d300ad66859e99a5ec20836f8981e099805150a357f421e2be33c7ff6"
)
EXPECTED_PARENT_PREVIEW_ID = 78
EXPECTED_PARENT_PREVIEW_SHA256 = (
    "f1fe99867102f90e9c8d374494683a62e1072fa3a4b0aa182e61b5af95355728"
)
MAX_API_CALLS = 129
AUTH_API_CALLS = 1
MAX_SEND_CALLS = 8
MAX_ACTION_CALLS = 16
MAX_READ_ATTEMPTS = 5
READ_PHASES = ("lookup", "raw", "confirmation")
RETRY_DELAYS = (1, 2, 4, 8)
EXPECTED_EMAIL_PERIODS = (
    ("daily_ai_result_v1", "2026-08-12", "2026-08-12"),
    ("daily_ai_result_v1", "2026-08-13", "2026-08-13"),
    ("daily_ai_result_v1", "2026-08-14", "2026-08-14"),
    ("daily_ai_result_v1", "2026-08-15", "2026-08-15"),
    ("daily_ai_result_v1", "2026-08-16", "2026-08-16"),
    ("daily_ai_result_v1", "2026-08-17", "2026-08-17"),
    ("daily_ai_result_v1", "2026-08-18", "2026-08-18"),
    ("weekly_ai_result_v1", "2026-08-12", "2026-08-18"),
)


RETRYABLE_TRANSPORT_ERRORS = (
    ConnectionError,
    TimeoutError,
    requests_exceptions.ConnectionError,
    requests_exceptions.Timeout,
)
RUNTIME_FILES = (
    "requirements.txt",
    "skills/_shared/state.py",
    "skills/_shared/schemas/gmail_rest_auth_receipt_v1.schema.json",
    "skills/_shared/schemas/m10_gmail_rest_intent_v1.schema.json",
    "skills/_shared/schemas/m10_gmail_rest_preview_v1.schema.json",
    "skills/_shared/schemas/m10_gmail_rest_result_v1.schema.json",
    "skills/gmail-sender/SKILL.md",
    "skills/gmail-sender/scripts/gmail_rest_auth.py",
    "skills/gmail-sender/scripts/gmail_rest_common.py",
    "skills/gmail-sender/scripts/gmail_rest_delivery.py",
)


def _runtime_sha256() -> str:
    entries: dict[str, str] = {}
    for relative in RUNTIME_FILES:
        runtime_file = RUNTIME_SOURCE_ROOT / relative
        metadata = runtime_file.lstat()
        if (
            runtime_file.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
        ):
            raise GmailRestError("gmail_rest_runtime_file_invalid")
        entries[relative] = sha256_file(runtime_file)
    return sha256_text(canonical_json(entries))


def _secure_copy(source: Path, target: Path) -> None:
    require_owner_file(source)
    private_directory(target.parent)
    if target.exists():
        raise GmailRestError("gmail_rest_copy_target_exists")
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
        raise GmailRestError("gmail_rest_copy_hash_mismatch")


def _copy_source_tree(parent: Path, target: Path) -> None:
    require_owner_directory(parent)
    target.mkdir(mode=0o700)
    excluded = {
        "state/trainlab.db",
        "state/trainlab.db-wal",
        "state/trainlab.db-shm",
        "state/trainlab.lock",
        "credentials.json",
        "gcp-oauth.keys.json",
        "gmail-api-token.json",
        "email.json",
    }
    for current_root, directories, files in os.walk(parent, followlinks=False):
        current = Path(current_root)
        relative = current.relative_to(parent)
        destination = target / relative
        os.chmod(destination, 0o700)
        for directory_name in list(directories):
            source_directory = current / directory_name
            metadata = source_directory.lstat()
            if source_directory.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
                raise GmailRestError("gmail_rest_copy_source_invalid")
            (destination / directory_name).mkdir(mode=0o700)
        for filename in files:
            source_file = current / filename
            relative_file = source_file.relative_to(parent)
            if relative_file.as_posix() in excluded:
                continue
            _secure_copy(source_file, target / relative_file)


def _backup_database(source: Path, target: Path) -> None:
    require_owner_file(source)
    private_directory(target.parent)
    if target.exists():
        raise GmailRestError("gmail_rest_candidate_exists")
    source_connection = sqlite3.connect(f"file:{source}?mode=ro&immutable=1", uri=True)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
        target_connection.commit()
    finally:
        target_connection.close()
        source_connection.close()
    os.chmod(target, 0o600)
    require_owner_file(target)


def _parent_lock(database: Path):
    lock_path = require_owner_file(database.parent / "trainlab.lock", allow_empty=True)
    descriptor = os.open(lock_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(descriptor)
        raise GmailRestError("gmail_rest_parent_lock_unavailable") from exc
    return descriptor


def _unlock(descriptor: int) -> None:
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)


def _parent_preview(connection: sqlite3.Connection) -> tuple[int, str, dict[str, Any]]:
    rows = connection.execute(
        "SELECT id,content_sha256,content_json FROM skill_outputs "
        "WHERE schema_name='m10_external_preview_v1' ORDER BY id"
    ).fetchall()
    if len(rows) != 1:
        raise GmailRestError("gmail_rest_parent_preview_invalid")
    if (
        int(rows[0][0]) != EXPECTED_PARENT_PREVIEW_ID
        or str(rows[0][1]) != EXPECTED_PARENT_PREVIEW_SHA256
    ):
        raise GmailRestError("gmail_rest_parent_preview_invalid")
    payload = json.loads(str(rows[0][2]))
    emails = payload.get("emails")
    if not isinstance(emails, list) or len(emails) != 8:
        raise GmailRestError("gmail_rest_parent_preview_invalid")
    return int(rows[0][0]), str(rows[0][1]), payload


def _period_date(
    connection: sqlite3.Connection,
    *,
    ordinal: int,
    source_output_id: int,
    source_output_sha256: str,
    report_output_id: int,
) -> datetime:
    """Use the frozen AI source period while retaining report output lineage."""

    try:
        expected_schema, expected_start, expected_end = EXPECTED_EMAIL_PERIODS[
            ordinal - 1
        ]
    except IndexError as exc:
        raise GmailRestError("gmail_rest_report_period_missing") from exc
    source = connection.execute(
        "SELECT content_sha256,schema_name,period_start_date,period_end_date "
        "FROM skill_outputs WHERE id=?",
        (source_output_id,),
    ).fetchone()
    if source is None or str(source[0]) != source_output_sha256:
        raise GmailRestError("gmail_rest_envelope_lineage_invalid")
    if str(source[1]) != expected_schema:
        raise GmailRestError("gmail_rest_envelope_lineage_invalid")
    if source[2] != expected_start or source[3] != expected_end:
        raise GmailRestError("gmail_rest_report_period_missing")
    report = connection.execute(
        "SELECT period_start_date,period_end_date FROM skill_outputs WHERE id=?",
        (report_output_id,),
    ).fetchone()
    if report is None or tuple(report) not in {
        (None, None),
        (expected_start, expected_end),
    }:
        raise GmailRestError("gmail_rest_report_period_missing")
    try:
        date.fromisoformat(expected_start)
        value = date.fromisoformat(expected_end)
    except ValueError as exc:
        raise GmailRestError("gmail_rest_report_period_missing") from exc
    return datetime.combine(value, datetime_time(hour=12), ZoneInfo("Asia/Hong_Kong"))


def _build_preview(
    connection: sqlite3.Connection,
    *,
    candidate_root: Path,
    parent_run_root: Path,
    email_file: Path,
) -> tuple[int, str, dict[str, Any]]:
    parent_id, parent_sha, parent = _parent_preview(connection)
    recipient, recipient_sha = read_recipient(email_file)
    input_root = private_directory(candidate_root / "gmail-rest/input")
    items: list[dict[str, Any]] = []
    for ordinal, source in enumerate(parent["emails"], start=1):
        if set(source) != {
            "envelope_path",
            "envelope_sha256",
            "marker",
            "recipient",
            "recipient_sha256",
            "request_sha256",
            "source_output_id",
            "source_output_sha256",
            "subject",
            "verification_query",
        }:
            raise GmailRestError("gmail_rest_parent_preview_invalid")
        original = require_owner_file(Path(str(source.get("envelope_path", ""))))
        try:
            original.relative_to(parent_run_root)
        except ValueError as exc:
            raise GmailRestError("gmail_rest_envelope_scope_invalid") from exc
        if sha256_file(original) != source.get("envelope_sha256"):
            raise GmailRestError("gmail_rest_parent_preview_invalid")
        envelope = read_owner_json(original)
        required = {
            "subject",
            "text",
            "html",
            "source_output_id",
            "source_output_sha256",
            "report_output_id",
            "report_output_sha256",
        }
        if set(envelope) != required:
            raise GmailRestError("gmail_rest_envelope_invalid")
        output_id = int(envelope["report_output_id"])
        output_sha = str(envelope["report_output_sha256"])
        if (
            isinstance(source.get("source_output_id"), bool)
            or source.get("source_output_id") != output_id
            or source.get("source_output_sha256") != output_sha
            or source.get("subject") != envelope["subject"]
        ):
            raise GmailRestError("gmail_rest_parent_preview_invalid")
        output_row = connection.execute(
            "SELECT o.content_sha256,o.output_kind,o.schema_name,o.title_text,"
            "o.content_text,o.content_html,o.lineage_json,r.skill_name,r.operation,"
            "r.status FROM skill_outputs o JOIN skill_runs r ON r.id=o.skill_run_id "
            "WHERE o.id=?",
            (output_id,),
        ).fetchone()
        expected_report_schema = (
            "daily_email_render" if ordinal < 8 else "weekly_email_render"
        )
        expected_operation = "render_daily" if ordinal < 8 else "render_weekly"
        if output_row is None or str(output_row[0]) != output_sha:
            raise GmailRestError("gmail_rest_envelope_lineage_invalid")
        source_output_id = int(envelope["source_output_id"])
        source_output_sha = str(envelope["source_output_sha256"])
        try:
            report_lineage = json.loads(str(output_row[6]))
        except (TypeError, ValueError) as exc:
            raise GmailRestError("gmail_rest_envelope_lineage_invalid") from exc
        if (
            output_row[1] != "email_render"
            or output_row[2] != expected_report_schema
            or output_row[7] != "training-report-publisher"
            or output_row[8] != expected_operation
            or output_row[9] != "succeeded"
            or not isinstance(report_lineage, list)
            or not any(
                isinstance(item, dict)
                and item.get("source_output_id") == source_output_id
                and item.get("source_output_sha256") == source_output_sha
                for item in report_lineage
            )
        ):
            raise GmailRestError("gmail_rest_envelope_lineage_invalid")
        if (
            output_row[3] != envelope["subject"]
            or output_row[4] != envelope["text"]
            or output_row[5] != envelope["html"]
        ):
            raise GmailRestError("gmail_rest_envelope_content_invalid")
        period_date = _period_date(
            connection,
            ordinal=ordinal,
            source_output_id=source_output_id,
            source_output_sha256=source_output_sha,
            report_output_id=output_id,
        )
        destination = input_root / f"{ordinal:02d}-email-envelope.json"
        _secure_copy(original, destination)
        raw, message_id, mime_sha = deterministic_mime(
            recipient=recipient,
            subject=str(envelope["subject"]),
            plain=str(envelope["text"]),
            html=str(envelope["html"]),
            source_sha256=output_sha,
            date_value=period_date,
        )
        mime_path = input_root / f"{ordinal:02d}-message.eml"
        atomic_write(mime_path, raw)
        request = {
            "transport": "gmail_rest",
            "ordinal": ordinal,
            "message_id": message_id,
            "mime_sha256": mime_sha,
            "recipient_sha256": recipient_sha,
            "source_output_id": output_id,
            "source_output_sha256": output_sha,
        }
        items.append(
            {
                "ordinal": ordinal,
                "source_output_id": output_id,
                "source_output_sha256": output_sha,
                "envelope_relative_path": str(destination.relative_to(candidate_root)),
                "envelope_sha256": sha256_file(destination),
                "recipient_sha256": recipient_sha,
                "subject_sha256": sha256_text(str(envelope["subject"])),
                "message_id": message_id,
                "mime_sha256": mime_sha,
                "request_sha256": sha256_text(canonical_json(request)),
            }
        )
    if (
        len({item["source_output_id"] for item in items}) != 8
        or len({item["message_id"] for item in items}) != 8
        or len({item["request_sha256"] for item in items}) != 8
    ):
        raise GmailRestError("gmail_rest_email_set_not_unique")
    unsigned = {
        "schema_version": "m10_gmail_rest_preview_v1",
        "batch_id": BATCH_ID,
        "transport": "gmail_rest",
        "parent_preview_output_id": parent_id,
        "parent_preview_output_sha256": parent_sha,
        "emails": items,
        "gmail_api_budget": MAX_API_CALLS,
        "gmail_send_budget": MAX_SEND_CALLS,
    }
    preview = {**unsigned, "preview_sha256": sha256_text(canonical_json(unsigned))}
    validate_schema(preview, "m10_gmail_rest_preview_v1")
    digest = sha256_text(canonical_json(preview))
    run_id = begin_run(
        connection,
        run_key=f"m10-r06-preview:{digest}:attempt-1",
        workflow_key=WORKFLOW_KEY,
        dedupe_key=digest,
        skill_name="gmail-sender",
        operation="send_email",
        trigger_kind="manual",
        input_manifest={"m10_role": "m10_gmail_rest_prepare_v1", "batch_id": BATCH_ID},
    )
    output_id = append_output(
        connection,
        skill_run_id=run_id,
        output_kind="execution_summary",
        logical_key="m10:r06:gmail-rest-preview",
        schema_name="m10_gmail_rest_preview_v1",
        schema_version="1",
        title_text="M10 r06 Gmail REST delivery preview",
        content_json=preview,
        content_text=canonical_json(preview),
        lineage=[{"output_id": parent_id, "output_sha256": parent_sha}],
    )
    finish_run(connection, run_id, status="succeeded")
    row = connection.execute(
        "SELECT content_sha256 FROM skill_outputs WHERE id=?", (output_id,)
    ).fetchone()
    if row is None:
        raise GmailRestError("gmail_rest_preview_missing")
    return output_id, str(row[0]), preview


def _prepare_actions(
    connection: sqlite3.Connection,
    preview_id: int,
    preview_sha: str,
    preview: dict[str, Any],
) -> list[int]:
    run_id = int(
        connection.execute(
            "SELECT skill_run_id FROM skill_outputs WHERE id=?", (preview_id,)
        ).fetchone()[0]
    )
    ids: list[int] = []
    for item in preview["emails"]:
        target_key = f"gmail-rest:m10-r06:{item['message_id'][10:74]}"
        scope = {
            "provider": "gmail",
            "action_kind": "gmail_send",
            "entity_kind": "email",
            "target_key": target_key,
            "scope_kind": "gmail",
            "budget": {"max_actions": 1},
        }
        scope_text = canonical_json(scope)
        approval = connection.execute(
            """INSERT INTO approvals
            (approval_key,candidate_output_id,candidate_output_sha256,authority_kind,
             decision,scope_kind,scope_json,scope_sha256,source_ref,reason_code,
             decided_at_utc,valid_from_utc,valid_until_utc)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sha256_text(
                    canonical_json({"batch": BATCH_ID, "ordinal": item["ordinal"]})
                ),
                preview_id,
                preview_sha,
                "user_explicit",
                "approved",
                "gmail",
                scope_text,
                sha256_text(scope_text),
                f"m10-r06-preview:{preview['preview_sha256']}",
                "m10_r06_eight_email_delivery_approved",
                utc_now(),
                utc_now(),
                None,
            ),
        )
        approval_id = require_lastrowid(approval)
        request = {
            "transport": "gmail_rest",
            "ordinal": item["ordinal"],
            "message_id": item["message_id"],
            "mime_sha256": item["mime_sha256"],
            "recipient_sha256": item["recipient_sha256"],
            "source_output_id": item["source_output_id"],
            "source_output_sha256": item["source_output_sha256"],
        }
        request_text = canonical_json(request)
        action = connection.execute(
            """INSERT INTO external_actions
            (idempotency_key,skill_run_id,provider,entity_kind,action_kind,
             source_output_id,source_output_sha256,approval_id,target_key,
             request_json,request_sha256,status,attempt_count,prepared_at_utc)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sha256_text(canonical_json({"batch": BATCH_ID, "request": request})),
                run_id,
                "gmail",
                "email",
                "gmail_send",
                preview_id,
                preview_sha,
                approval_id,
                target_key,
                request_text,
                sha256_text(request_text),
                "prepared",
                0,
                utc_now(),
            ),
        )
        ids.append(require_lastrowid(action))
    connection.commit()
    return ids


def create_candidate(
    *,
    parent_source: Path,
    parent_run_root: Path,
    candidate_root: Path,
    email_file: Path,
) -> dict[str, Any]:
    email_file = Path(os.path.abspath(email_file))
    if email_file != Path(os.path.abspath(SOURCE_ROOT / "email.json")):
        raise GmailRestError("gmail_rest_recipient_path_invalid")
    parent_source = require_owner_directory(parent_source)
    parent_run_root = require_owner_directory(parent_run_root)
    parent_database = require_owner_file(parent_source / "state/trainlab.db")
    email_file = require_owner_file(email_file)
    candidate_root = Path(os.path.abspath(candidate_root))
    if candidate_root.exists() or candidate_root.is_relative_to(SOURCE_ROOT.parent):
        raise GmailRestError("gmail_rest_candidate_scope_invalid")
    lock = _parent_lock(parent_database)
    try:
        wal = Path(f"{parent_database}-wal")
        if wal.exists() and wal.stat().st_size != 0:
            raise GmailRestError("gmail_rest_parent_wal_nonempty")
        parent_db_sha = sha256_file(parent_database)
        if parent_db_sha != EXPECTED_PARENT_DATABASE_SHA256:
            raise GmailRestError("gmail_rest_parent_database_invalid")
        candidate_root.mkdir(mode=0o700)
        candidate_source = candidate_root / "source"
        _copy_source_tree(parent_source, candidate_source)
        parent_fingerprint = require_owner_file(
            parent_source.parent / "formal-state-fingerprint.json"
        )
        if sha256_file(parent_fingerprint) != EXPECTED_PARENT_FINGERPRINT_SHA256:
            raise GmailRestError("gmail_rest_parent_fingerprint_invalid")
        _secure_copy(
            parent_fingerprint,
            candidate_root / "parent-formal-state-fingerprint.json",
        )
        database = candidate_source / "state/trainlab.db"
        _backup_database(parent_database, database)
        if sha256_file(parent_database) != parent_db_sha:
            raise GmailRestError("gmail_rest_parent_changed_during_clone")
    finally:
        _unlock(lock)
    descriptor = os.open(
        candidate_source / "state/trainlab.lock",
        os.O_CREAT | os.O_EXCL | os.O_RDWR,
        0o600,
    )
    os.close(descriptor)
    connection = connect(database)
    try:
        preview_id, preview_sha, preview = _build_preview(
            connection,
            candidate_root=candidate_root,
            parent_run_root=parent_run_root,
            email_file=email_file,
        )
        action_ids = _prepare_actions(connection, preview_id, preview_sha, preview)
    finally:
        connection.close()
    marker = {
        "schema_version": "m10_gmail_rest_candidate_v1",
        "batch_id": BATCH_ID,
        "candidate_source": str(candidate_source),
        "database": str(database),
        "parent_database_sha256": parent_db_sha,
        "parent_fingerprint_sha256": sha256_file(
            candidate_root / "parent-formal-state-fingerprint.json"
        ),
        "runtime_sha256": _runtime_sha256(),
        "preview_output_id": preview_id,
        "preview_output_sha256": preview_sha,
        "action_ids": action_ids,
        "action_api_calls": {str(action_id): 0 for action_id in action_ids},
        "action_phase_calls": {
            str(action_id): {phase: 0 for phase in READ_PHASES}
            for action_id in action_ids
        },
        "action_send_calls": {str(action_id): 0 for action_id in action_ids},
        "auth_receipt_sha256": None,
        "auth_provider_calls": 0,
        "canary_confirmed": False,
        "api_calls": 0,
        "send_calls": 0,
        "created_at_utc": utc_now(),
    }
    atomic_json(candidate_root / MARKER_NAME, marker)
    return {"status": "succeeded", "candidate_root": str(candidate_root), "actions": 8}


class GmailRestClient:
    def __init__(
        self,
        *,
        token_file: Path,
        candidate_root: Path,
        marker: dict[str, Any],
        marker_name: str = MARKER_NAME,
        max_provider_calls: int = MAX_API_CALLS,
        max_send_calls: int = MAX_SEND_CALLS,
        session_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        token_file = Path(os.path.abspath(token_file))
        if token_file != Path(os.path.abspath(SOURCE_ROOT / "gmail-api-token.json")):
            raise GmailRestError("gmail_rest_token_path_invalid")
        self.token_file = require_owner_file(token_file)
        descriptor = os.open(
            self.token_file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            metadata = os.fstat(descriptor)
            current = self.token_file.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_nlink != 1
                or (metadata.st_dev, metadata.st_ino)
                != (current.st_dev, current.st_ino)
            ):
                raise GmailRestError("gmail_rest_token_file_invalid")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(descriptor, 65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > 1024 * 1024:
                    raise GmailRestError("gmail_rest_token_file_invalid")
                chunks.append(chunk)
            token_payload = b"".join(chunks)
        finally:
            os.close(descriptor)
        self._token_sha256 = sha256_bytes(token_payload)
        self.candidate_root = require_owner_directory(candidate_root)
        self.marker = marker
        self.marker_name = marker_name
        if max_provider_calls < AUTH_API_CALLS or max_send_calls < 1:
            raise GmailRestError("gmail_rest_budget_invalid")
        self.max_provider_calls = max_provider_calls
        self.max_send_calls = max_send_calls
        self.session: Any
        self.credentials: Any
        self.refresh_request: Any
        if session_factory is None:
            import requests
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials

            try:
                token_info = json.loads(token_payload.decode("utf-8"))
                credentials = Credentials.from_authorized_user_info(
                    token_info, list(SCOPES)
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise GmailRestError("gmail_rest_auth_invalid") from exc
            if not set(SCOPES).issubset(set(credentials.scopes or ())):
                raise GmailRestError("gmail_rest_scope_invalid")
            self.credentials = credentials
            self.refresh_request = Request()
            self.session = requests.Session()
        else:
            self.credentials = None
            self.refresh_request = None
            self.session = session_factory(None)

    @property
    def token_sha256(self) -> str:
        """Private audit observation; never a cross-process recovery identity."""

        return self._token_sha256

    def _reserve_call(
        self, *, action_id: int, send: bool = False, phase: str | None = None
    ) -> int:
        action_key = str(action_id)
        if action_key not in self.marker["action_api_calls"]:
            raise GmailRestError("gmail_rest_action_invalid")
        if send:
            if phase is not None:
                raise GmailRestError("gmail_rest_read_phase_invalid")
        elif phase not in READ_PHASES:
            raise GmailRestError("gmail_rest_read_phase_invalid")
        next_call = int(self.marker["api_calls"]) + 1
        if (
            next_call + int(self.marker["auth_provider_calls"])
            > self.max_provider_calls
        ):
            raise GmailRestError("gmail_rest_api_budget_exceeded")
        action_calls = int(self.marker["action_api_calls"][action_key]) + 1
        if action_calls > MAX_ACTION_CALLS:
            raise GmailRestError("gmail_rest_action_api_budget_exceeded")
        action_sends = int(self.marker["action_send_calls"][action_key])
        if send:
            if (
                int(self.marker["send_calls"]) >= self.max_send_calls
                or action_sends >= 1
            ):
                raise GmailRestError("gmail_rest_send_budget_exceeded")
            self.marker["send_calls"] = int(self.marker["send_calls"]) + 1
            self.marker["action_send_calls"][action_key] = action_sends + 1
        else:
            phase_calls = int(self.marker["action_phase_calls"][action_key][phase])
            if phase_calls >= MAX_READ_ATTEMPTS:
                raise GmailRestError("gmail_rest_read_budget_exceeded")
            self.marker["action_phase_calls"][action_key][phase] = phase_calls + 1
        self.marker["api_calls"] = next_call
        self.marker["action_api_calls"][action_key] = action_calls
        atomic_json(self.candidate_root / self.marker_name, self.marker)
        return next_call

    def _phase_attempt(self, action_id: int, phase: str) -> int:
        return int(self.marker["action_phase_calls"][str(action_id)][phase])

    @staticmethod
    def _wait_before_retry(attempt: int) -> None:
        if 1 <= attempt < MAX_READ_ATTEMPTS:
            time.sleep(RETRY_DELAYS[attempt - 1])

    def _capture(
        self,
        *,
        kind: str,
        action_id: int,
        request: Any,
        response: Any,
        status: int | None,
        call_index: int,
    ) -> None:
        capture_root = private_directory(self.candidate_root / "gmail-rest/captures")
        payload = sanitize_capture(
            method=str(request["method"]),
            url=str(request["url"]),
            status_code=status,
            request_sha256=sha256_text(canonical_json(request)),
            response=response,
        )
        try:
            atomic_json(
                capture_root / f"{call_index:03d}-{action_id}-{kind}.json", payload
            )
        except (GmailRestError, OSError) as exc:
            raise GmailRestError("gmail_rest_capture_failed") from exc

    def recover_sent_gmail_id(
        self,
        raw_sha256: str,
        *,
        action_id: int,
    ) -> str | None:
        """Recover one Gmail ID from the durable, sanitized send capture."""

        action_key = str(action_id)
        if (
            len(raw_sha256) != 64
            or any(character not in "0123456789abcdef" for character in raw_sha256)
            or action_key not in self.marker["action_send_calls"]
            or action_key not in self.marker["action_api_calls"]
            or int(self.marker["action_send_calls"][action_key]) != 1
            or int(self.marker["action_api_calls"][action_key]) < 1
        ):
            raise GmailRestError("gmail_rest_send_capture_invalid")
        capture_root = self.candidate_root / "gmail-rest/captures"
        if not capture_root.exists():
            return None
        try:
            capture_root = require_owner_directory(capture_root)
            candidates = sorted(capture_root.glob(f"*-{action_id}-send.json"))
            if not candidates:
                return None
            if len(candidates) != 1:
                raise GmailRestError("gmail_rest_send_capture_invalid")
            capture_path = candidates[0]
            match = re.fullmatch(
                rf"(\d{{3}})-{action_id}-send\.json",
                capture_path.name,
            )
            if match is None:
                raise GmailRestError("gmail_rest_send_capture_invalid")
            call_index = int(match.group(1))
            if not 1 <= call_index <= int(self.marker["api_calls"]):
                raise GmailRestError("gmail_rest_send_capture_invalid")
            capture = read_owner_json(capture_path)
            request = {
                "method": "POST",
                "url": f"{API_ROOT}/messages/send",
                "raw_sha256": raw_sha256,
            }
            expected_request_sha256 = sha256_text(canonical_json(request))
            status = capture.get("status_code")
            response = capture.get("response")
            if (
                set(capture)
                != {
                    "method",
                    "url",
                    "status_code",
                    "request_sha256",
                    "response",
                }
                or capture.get("method") != "POST"
                or capture.get("url") != request["url"]
                or type(status) is not int
                or not 200 <= status < 300
                or capture.get("request_sha256") != expected_request_sha256
                or not isinstance(response, dict)
            ):
                raise GmailRestError("gmail_rest_send_capture_invalid")
            return require_gmail_message_id(response.get("id"))
        except GmailRestError as exc:
            if str(exc) == "gmail_rest_send_capture_invalid":
                raise
            raise GmailRestError("gmail_rest_send_capture_invalid") from exc

    def _refresh_token_if_needed(self) -> None:
        if self.credentials is None:
            return
        if not self.credentials.token or self.credentials.expired:
            try:
                self.credentials.refresh(self.refresh_request)
            except Exception as exc:
                raise GmailRestError("gmail_rest_auth_invalid") from exc
        serialized = self.credentials.to_json().encode("utf-8")
        serialized_sha256 = sha256_bytes(serialized)
        current_sha256 = getattr(
            self,
            "_token_sha256",
            sha256_file(require_owner_file(self.token_file)),
        )
        if serialized_sha256 != current_sha256:
            try:
                # A-010 trusts the owner-only single writer. atomic_write uses a
                # 0600 sibling, fsync, same-filesystem rename and parent fsync.
                atomic_write(self.token_file, serialized)
            except OSError as exc:
                raise GmailRestError("gmail_rest_token_refresh_persist_failed") from exc
            except GmailRestError as exc:
                raise GmailRestError("gmail_rest_token_refresh_persist_failed") from exc
            published_sha256 = sha256_file(require_owner_file(self.token_file))
            if published_sha256 != serialized_sha256:
                raise GmailRestError("gmail_rest_token_refresh_persist_failed")
            self._token_sha256 = serialized_sha256

    def _request_headers(self) -> dict[str, str]:
        if self.credentials is None:
            return {}
        self._refresh_token_if_needed()
        return {"Authorization": f"Bearer {self.credentials.token}"}

    def list_message(
        self,
        message_id: str,
        *,
        action_id: int,
        kind: str,
        retry_empty: bool = False,
        phase: str = "lookup",
    ) -> list[str]:
        request: dict[str, Any] = {
            "method": "GET",
            "url": f"{API_ROOT}/messages",
            "q": f"rfc822msgid:{message_id}",
            "maxResults": 2,
        }
        while True:
            headers = self._request_headers()
            call_index = self._reserve_call(action_id=action_id, phase=phase)
            attempt = self._phase_attempt(action_id, phase)
            try:
                response = self.session.get(
                    request["url"],
                    params={"q": request["q"], "maxResults": 2},
                    headers=headers,
                    timeout=30,
                )
                status = int(response.status_code)
            except RETRYABLE_TRANSPORT_ERRORS as exc:
                self._capture(
                    kind=f"{kind}-transport-{attempt}",
                    action_id=action_id,
                    request=request,
                    response={"error": "transport"},
                    status=None,
                    call_index=call_index,
                )
                if attempt < MAX_READ_ATTEMPTS:
                    self._wait_before_retry(attempt)
                    continue
                raise GmailRestError("gmail_rest_query_transport_failed") from exc
            except Exception as exc:
                self._capture(
                    kind=f"{kind}-request-error-{attempt}",
                    action_id=action_id,
                    request=request,
                    response={"error": "request"},
                    status=None,
                    call_index=call_index,
                )
                raise GmailRestError("gmail_rest_query_failed") from exc
            try:
                body = response.json() if getattr(response, "content", b"") else {}
            except Exception as exc:
                self._capture(
                    kind=f"{kind}-invalid-json-{attempt}",
                    action_id=action_id,
                    request=request,
                    response={"error": "invalid_json"},
                    status=status,
                    call_index=call_index,
                )
                if (status == 429 or status >= 500) and attempt < MAX_READ_ATTEMPTS:
                    self._wait_before_retry(attempt)
                    continue
                raise GmailRestError("gmail_rest_query_invalid") from exc
            self._capture(
                kind=f"{kind}-{attempt}",
                action_id=action_id,
                request=request,
                response=body,
                status=status,
                call_index=call_index,
            )
            if status in {401, 403}:
                raise GmailRestError("gmail_rest_auth_invalid")
            if status == 429 or status >= 500:
                if attempt < MAX_READ_ATTEMPTS:
                    self._wait_before_retry(attempt)
                    continue
                raise GmailRestError("gmail_rest_query_failed")
            if status != 200:
                raise GmailRestError("gmail_rest_query_failed")
            if not isinstance(body, dict):
                raise GmailRestError("gmail_rest_query_invalid")
            messages = body.get("messages", [])
            if not isinstance(messages, list):
                raise GmailRestError("gmail_rest_query_invalid")
            ids = [item.get("id") for item in messages if isinstance(item, dict)]
            if len(ids) != len(messages) or len(ids) > 2:
                raise GmailRestError("gmail_rest_query_invalid")
            normalized = [require_gmail_message_id(value) for value in ids]
            if not normalized and retry_empty and attempt < MAX_READ_ATTEMPTS:
                self._wait_before_retry(attempt)
                continue
            return normalized

    def send(self, raw: bytes, *, action_id: int) -> str:
        request = {
            "method": "POST",
            "url": f"{API_ROOT}/messages/send",
            "raw_sha256": sha256_bytes(raw),
        }
        headers = self._request_headers()
        call_index = self._reserve_call(action_id=action_id, send=True)
        try:
            response = self.session.post(
                request["url"],
                json={"raw": gmail_raw(raw)},
                headers=headers,
                timeout=30,
            )
            status = int(response.status_code)
        except RETRYABLE_TRANSPORT_ERRORS as exc:
            self._capture(
                kind="send-transport",
                action_id=action_id,
                request=request,
                response={"error": "transport"},
                status=None,
                call_index=call_index,
            )
            raise GmailRestError("gmail_rest_send_result_unknown") from exc
        except Exception as exc:
            self._capture(
                kind="send-request-error",
                action_id=action_id,
                request=request,
                response={"error": "request"},
                status=None,
                call_index=call_index,
            )
            raise GmailRestError("gmail_rest_send_result_unknown") from exc
        try:
            body = response.json() if getattr(response, "content", b"") else {}
        except Exception as exc:
            self._capture(
                kind="send-invalid-json",
                action_id=action_id,
                request=request,
                response={"error": "invalid_json"},
                status=status,
                call_index=call_index,
            )
            if status < 200 or status >= 300:
                raise GmailRestError("gmail_rest_send_rejected") from exc
            raise GmailRestError("gmail_rest_send_result_unknown") from exc
        self._capture(
            kind="send",
            action_id=action_id,
            request=request,
            response=body,
            status=status,
            call_index=call_index,
        )
        if status in {401, 403}:
            raise GmailRestError("gmail_rest_auth_invalid")
        if status < 200 or status >= 300:
            raise GmailRestError("gmail_rest_send_rejected")
        if not isinstance(body, dict) or not isinstance(body.get("id"), str):
            raise GmailRestError("gmail_rest_send_result_unknown")
        return require_gmail_message_id(body["id"])

    def get_raw(self, gmail_id: str, *, action_id: int) -> bytes:
        gmail_id = require_gmail_message_id(gmail_id)
        url = f"{API_ROOT}/messages/{gmail_id}"
        request = {"method": "GET", "url": url, "format": "raw"}
        while True:
            headers = self._request_headers()
            call_index = self._reserve_call(action_id=action_id, phase="raw")
            attempt = self._phase_attempt(action_id, "raw")
            try:
                response = self.session.get(
                    url,
                    params={"format": "raw"},
                    headers=headers,
                    timeout=30,
                )
                status = int(response.status_code)
            except RETRYABLE_TRANSPORT_ERRORS as exc:
                self._capture(
                    kind=f"get-raw-transport-{attempt}",
                    action_id=action_id,
                    request=request,
                    response={"error": "transport"},
                    status=None,
                    call_index=call_index,
                )
                if attempt < MAX_READ_ATTEMPTS:
                    self._wait_before_retry(attempt)
                    continue
                raise GmailRestError("gmail_rest_get_failed") from exc
            except Exception as exc:
                self._capture(
                    kind=f"get-raw-request-error-{attempt}",
                    action_id=action_id,
                    request=request,
                    response={"error": "request"},
                    status=None,
                    call_index=call_index,
                )
                raise GmailRestError("gmail_rest_get_failed") from exc
            try:
                body = response.json() if getattr(response, "content", b"") else {}
            except Exception as exc:
                self._capture(
                    kind=f"get-raw-invalid-json-{attempt}",
                    action_id=action_id,
                    request=request,
                    response={"error": "invalid_json"},
                    status=status,
                    call_index=call_index,
                )
                if (status == 429 or status >= 500) and attempt < MAX_READ_ATTEMPTS:
                    self._wait_before_retry(attempt)
                    continue
                raise GmailRestError("gmail_rest_get_failed") from exc
            if not isinstance(body, dict):
                capture_body: dict[str, Any] = {"error": "invalid_body"}
            else:
                capture_body = {
                    key: value for key, value in body.items() if key != "raw"
                }
                if isinstance(body.get("raw"), str):
                    capture_body["raw_sha256"] = sha256_text(str(body["raw"]))
            self._capture(
                kind=f"get-raw-{attempt}",
                action_id=action_id,
                request=request,
                response=capture_body,
                status=status,
                call_index=call_index,
            )
            if status in {401, 403}:
                raise GmailRestError("gmail_rest_auth_invalid")
            if status == 429 or status >= 500:
                if attempt < MAX_READ_ATTEMPTS:
                    self._wait_before_retry(attempt)
                    continue
                raise GmailRestError("gmail_rest_get_failed")
            if (
                status != 200
                or not isinstance(body, dict)
                or str(body.get("id", "")) != gmail_id
            ):
                raise GmailRestError("gmail_rest_get_failed")
            return decode_gmail_raw(str(body.get("raw", "")))


def _load_marker(candidate_root: Path) -> dict[str, Any]:
    root = require_owner_directory(candidate_root)
    marker = read_owner_json(root / MARKER_NAME)
    source = Path(os.path.abspath(str(marker.get("candidate_source", ""))))
    database = Path(os.path.abspath(str(marker.get("database", ""))))
    action_ids = marker.get("action_ids")
    action_api_calls = marker.get("action_api_calls")
    action_phase_calls = marker.get("action_phase_calls")
    action_send_calls = marker.get("action_send_calls")
    auth_receipt_sha = marker.get("auth_receipt_sha256")
    auth_provider_calls = marker.get("auth_provider_calls")
    if (
        marker.get("batch_id") != BATCH_ID
        or marker.get("runtime_sha256") != _runtime_sha256()
        or source != root / "source"
        or database != source / "state/trainlab.db"
        or not isinstance(action_ids, list)
        or len(action_ids) != 8
        or len(set(action_ids)) != 8
        or any(not isinstance(value, int) or value < 1 for value in action_ids)
        or not isinstance(action_api_calls, dict)
        or not isinstance(action_phase_calls, dict)
        or not isinstance(action_send_calls, dict)
        or set(action_api_calls) != {str(value) for value in action_ids}
        or set(action_phase_calls) != {str(value) for value in action_ids}
        or set(action_send_calls) != {str(value) for value in action_ids}
        or any(
            not isinstance(value, int) or not 0 <= value <= MAX_ACTION_CALLS
            for value in action_api_calls.values()
        )
        or any(
            not isinstance(value, dict)
            or set(value) != set(READ_PHASES)
            or any(
                not isinstance(count, int) or not 0 <= count <= MAX_READ_ATTEMPTS
                for count in value.values()
            )
            for value in action_phase_calls.values()
        )
        or any(
            not isinstance(value, int) or not 0 <= value <= 1
            for value in action_send_calls.values()
        )
        or marker.get("api_calls") != sum(action_api_calls.values())
        or marker.get("send_calls") != sum(action_send_calls.values())
        or any(
            int(action_api_calls[key])
            != sum(int(value) for value in action_phase_calls[key].values())
            + int(action_send_calls[key])
            for key in action_api_calls
        )
        or auth_provider_calls not in {0, AUTH_API_CALLS}
        or (auth_provider_calls == 0 and auth_receipt_sha is not None)
        or (
            auth_provider_calls == AUTH_API_CALLS
            and (
                not isinstance(auth_receipt_sha, str)
                or len(auth_receipt_sha) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in auth_receipt_sha
                )
            )
        )
        or int(marker.get("api_calls", -1)) + int(auth_provider_calls) > MAX_API_CALLS
    ):
        raise GmailRestError("gmail_rest_candidate_invalid")
    return marker


def _bind_auth_receipt(
    candidate_root: Path, marker: dict[str, Any], receipt_file: Path
) -> dict[str, Any]:
    receipt_file = Path(os.path.abspath(receipt_file))
    if receipt_file != Path(os.path.abspath(SOURCE_ROOT / AUTH_RECEIPT_NAME)):
        raise GmailRestError("gmail_rest_auth_receipt_path_invalid")
    receipt = read_owner_json(receipt_file)
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
        raise GmailRestError("gmail_rest_auth_receipt_invalid")
    digest = sha256_file(require_owner_file(receipt_file))
    existing = marker.get("auth_receipt_sha256")
    if existing is not None and existing != digest:
        raise GmailRestError("gmail_rest_auth_receipt_changed")
    marker["auth_receipt_sha256"] = digest
    marker["auth_provider_calls"] = AUTH_API_CALLS
    atomic_json(require_owner_directory(candidate_root) / MARKER_NAME, marker)
    return _load_marker(candidate_root)


def _require_bound_auth_receipt(
    candidate_root: Path, marker: dict[str, Any]
) -> dict[str, Any]:
    """Require the fixed successful auth receipt at every Provider entry point."""

    if marker.get("auth_provider_calls") != AUTH_API_CALLS:
        raise GmailRestError("gmail_rest_auth_receipt_required")
    receipt_file = Path(os.path.abspath(SOURCE_ROOT / AUTH_RECEIPT_NAME))
    receipt = read_owner_json(receipt_file)
    validate_schema(receipt, "gmail_rest_auth_receipt_v1")
    if (
        receipt.get("status") != "succeeded"
        or receipt.get("account_matches") is not True
        or receipt.get("scopes_match") is not True
        or receipt.get("refresh_token_available") is not True
        or receipt.get("token_published") is not True
        or receipt.get("short_lived_testing_token") is not False
        or receipt.get("provider_calls") != AUTH_API_CALLS
        or marker.get("auth_receipt_sha256")
        != sha256_file(require_owner_file(receipt_file))
    ):
        raise GmailRestError("gmail_rest_auth_receipt_invalid")
    return marker


def _email_for_action(
    connection: sqlite3.Connection, marker: dict[str, Any], action_id: int
) -> tuple[dict[str, Any], sqlite3.Row]:
    if action_id not in marker["action_ids"]:
        raise GmailRestError("gmail_rest_action_invalid")
    preview = connection.execute(
        "SELECT content_json FROM skill_outputs WHERE id=? AND content_sha256=?",
        (marker["preview_output_id"], marker["preview_output_sha256"]),
    ).fetchone()
    action = connection.execute(
        "SELECT * FROM external_actions WHERE id=?", (action_id,)
    ).fetchone()
    if preview is None or action is None:
        raise GmailRestError("gmail_rest_action_invalid")
    payload = json.loads(str(preview[0]))
    index = marker["action_ids"].index(action_id)
    return payload["emails"][index], action


def _validated_existing_result(
    *,
    candidate_root: Path,
    result_row: sqlite3.Row,
    action: sqlite3.Row,
    email: dict[str, Any],
    envelope: dict[str, Any],
    recipient: str,
) -> dict[str, Any]:
    try:
        result = json.loads(str(result_row[0]))
    except (TypeError, json.JSONDecodeError) as exc:
        raise GmailRestError("gmail_rest_result_invalid") from exc
    if not isinstance(result, dict):
        raise GmailRestError("gmail_rest_result_invalid")
    validate_schema(result, "m10_gmail_rest_result_v1")
    gmail_id = require_gmail_message_id(result.get("gmail_message_id"))
    relative = Path(str(result.get("eml_relative_path", "")))
    if relative.is_absolute():
        raise GmailRestError("gmail_rest_result_invalid")
    eml_path = Path(os.path.abspath(candidate_root / relative))
    try:
        eml_path.relative_to(candidate_root)
    except ValueError as exc:
        raise GmailRestError("gmail_rest_result_invalid") from exc
    eml = require_owner_file(eml_path)
    if (
        result.get("action_id") != int(action["id"])
        or result.get("message_id") != email["message_id"]
        or result.get("eml_sha256") != sha256_file(eml)
        or action["result_external_id"] != gmail_id
        or action["provider_marker"] != email["message_id"]
    ):
        raise GmailRestError("gmail_rest_result_invalid")
    verify_mime(
        eml.read_bytes(),
        recipient=recipient,
        subject=str(envelope["subject"]),
        plain=str(envelope["text"]),
        html=str(envelope["html"]),
        message_id=email["message_id"],
    )
    return result


def _finalize_success(
    connection: sqlite3.Connection,
    *,
    action: sqlite3.Row,
    email: dict[str, Any],
    gmail_id: str,
    eml_path: Path,
    marker: dict[str, Any],
    reused: bool,
) -> dict[str, Any]:
    duplicate = connection.execute(
        "SELECT id FROM external_actions WHERE provider='gmail' AND result_external_id=? AND id<>?",
        (gmail_id, int(action["id"])),
    ).fetchone()
    if duplicate is not None:
        raise GmailRestError("gmail_rest_provider_message_id_reused")
    result = {
        "schema_version": "m10_gmail_rest_result_v1",
        "batch_id": BATCH_ID,
        "status": "succeeded",
        "action_id": int(action["id"]),
        "ordinal": int(email["ordinal"]),
        "message_id": email["message_id"],
        "gmail_message_id": gmail_id,
        "eml_relative_path": str(
            eml_path.relative_to(Path(marker["candidate_source"]).parent)
        ),
        "eml_sha256": sha256_file(eml_path),
        "content_verified": True,
        "provider_calls": int(marker["action_api_calls"][str(action["id"])]),
        "send_calls": int(marker["action_send_calls"][str(action["id"])]),
        "completed_at_utc": utc_now(),
    }
    validate_schema(result, "m10_gmail_rest_result_v1")
    digest = sha256_text(canonical_json(result))
    run_id = begin_run(
        connection,
        run_key=f"m10-r06-delivery:{action['id']}:{digest}:attempt-1",
        workflow_key=WORKFLOW_KEY,
        dedupe_key=sha256_text(
            f"{BATCH_ID}\0{action['id']}\0{email['request_sha256']}"
        ),
        skill_name="gmail-sender",
        operation="send_email",
        trigger_kind="manual",
        input_manifest={
            "m10_role": "m10_gmail_rest_delivery_v1",
            "action_id": int(action["id"]),
        },
    )
    append_output(
        connection,
        skill_run_id=run_id,
        output_kind="execution_summary",
        logical_key=f"m10:r06:gmail-result:{action['id']}",
        schema_name="m10_gmail_rest_result_v1",
        schema_version="1",
        title_text=f"M10 r06 Gmail REST result {email['ordinal']}",
        content_json=result,
        content_text=canonical_json(result),
        lineage=[
            {
                "output_id": int(action["source_output_id"]),
                "output_sha256": str(action["source_output_sha256"]),
            },
            {
                "output_id": int(email["source_output_id"]),
                "output_sha256": str(email["source_output_sha256"]),
            },
        ],
    )
    finish_run(connection, run_id, status="succeeded")
    status = "already_done" if reused else "succeeded"
    connection.execute(
        "UPDATE external_actions SET status=?,result_external_id=?,provider_marker=?,finished_at_utc=?,"
        "last_reconciled_at_utc=?,response_summary_json=?,error_code=NULL,error_summary=NULL WHERE id=?",
        (
            status,
            gmail_id,
            email["message_id"],
            utc_now(),
            utc_now(),
            canonical_json(
                {
                    "verified": True,
                    "eml_sha256": result["eml_sha256"],
                    "message_id": email["message_id"],
                }
            ),
            int(action["id"]),
        ),
    )
    connection.commit()
    return result


def _deliver_action(
    *,
    candidate_root: Path,
    token_file: Path,
    action_id: int,
    session_factory: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    root = require_owner_directory(candidate_root)
    marker = _require_bound_auth_receipt(root, _load_marker(root))
    database = require_owner_file(Path(marker["database"]))
    with workflow_lock(database):
        connection = connect(database)
        try:
            email, action = _email_for_action(connection, marker, action_id)
            existing = connection.execute(
                "SELECT content_json FROM skill_outputs WHERE logical_key=? ORDER BY revision_no DESC LIMIT 1",
                (f"m10:r06:gmail-result:{action_id}",),
            ).fetchone()
            envelope = read_owner_json(root / email["envelope_relative_path"])
            recipient, recipient_sha = read_recipient(SOURCE_ROOT / "email.json")
            if recipient_sha != email["recipient_sha256"]:
                raise GmailRestError("gmail_rest_recipient_changed")
            if (
                action["status"] in {"succeeded", "already_done"}
                and existing is not None
            ):
                return _validated_existing_result(
                    candidate_root=root,
                    result_row=existing,
                    action=action,
                    email=email,
                    envelope=envelope,
                    recipient=recipient,
                )
            if action["status"] not in {"prepared", "in_progress", "unknown"}:
                raise GmailRestError("gmail_rest_action_not_deliverable")
            mime_path = (
                root / "gmail-rest/input" / f"{email['ordinal']:02d}-message.eml"
            )
            raw = require_owner_file(mime_path).read_bytes()
            if sha256_bytes(raw) != email["mime_sha256"]:
                raise GmailRestError("gmail_rest_mime_changed")
            intent_root = private_directory(root / f"gmail-rest/actions/{action_id}")
            intent_path = intent_root / "intent.json"
            if intent_path.exists():
                intent = read_owner_json(intent_path)
            else:
                now = utc_now()
                intent = {
                    "schema_version": "m10_gmail_rest_intent_v1",
                    "batch_id": BATCH_ID,
                    "action_id": action_id,
                    "ordinal": email["ordinal"],
                    "message_id": email["message_id"],
                    "mime_sha256": email["mime_sha256"],
                    "request_sha256": email["request_sha256"],
                    "send_started": False,
                    "provider_calls": 0,
                    "send_calls": 0,
                    "created_at_utc": now,
                    "updated_at_utc": now,
                }
                validate_schema(intent, "m10_gmail_rest_intent_v1")
                atomic_json(intent_path, intent)
            client = GmailRestClient(
                token_file=token_file,
                candidate_root=root,
                marker=marker,
                session_factory=session_factory,
            )
            if action["status"] == "prepared":
                connection.execute(
                    "UPDATE external_actions SET status='in_progress',started_at_utc=? WHERE id=?",
                    (utc_now(), action_id),
                )
                connection.commit()
            matches = client.list_message(
                email["message_id"],
                action_id=action_id,
                kind="initial-query",
                retry_empty=bool(intent["send_started"]),
                phase="lookup",
            )
            reused = bool(matches)
            if len(matches) > 1:
                raise GmailRestError("gmail_rest_message_id_ambiguous")
            gmail_id: str
            if matches:
                gmail_id = matches[0]
            elif intent["send_started"]:
                connection.execute(
                    "UPDATE external_actions SET status='unknown',last_reconciled_at_utc=?,error_code=?,error_summary=? WHERE id=?",
                    (
                        utc_now(),
                        "gmail_rest_send_unconfirmed",
                        "message_id_not_found",
                        action_id,
                    ),
                )
                connection.commit()
                raise GmailRestError("gmail_rest_send_unconfirmed")
            else:
                intent["send_started"] = True
                intent["send_calls"] = 1
                intent["updated_at_utc"] = utc_now()
                validate_schema(intent, "m10_gmail_rest_intent_v1")
                atomic_json(intent_path, intent)
                connection.execute(
                    "UPDATE external_actions SET attempt_count=1 WHERE id=?",
                    (action_id,),
                )
                connection.commit()
                try:
                    gmail_id = client.send(raw, action_id=action_id)
                except GmailRestError:
                    connection.execute(
                        "UPDATE external_actions SET status='unknown',error_code=?,error_summary=? WHERE id=?",
                        (
                            "gmail_rest_send_unconfirmed",
                            "send_response_unavailable",
                            action_id,
                        ),
                    )
                    connection.commit()
                    raise
            actual = client.get_raw(gmail_id, action_id=action_id)
            verify_mime(
                actual,
                recipient=recipient,
                subject=str(envelope["subject"]),
                plain=str(envelope["text"]),
                html=str(envelope["html"]),
                message_id=email["message_id"],
            )
            confirmation = client.list_message(
                email["message_id"],
                action_id=action_id,
                kind="confirmation-query",
                retry_empty=True,
                phase="confirmation",
            )
            if confirmation != [gmail_id]:
                raise GmailRestError("gmail_rest_confirmation_invalid")
            eml_root = private_directory(root / "gmail-rest/eml")
            eml_path = eml_root / f"{email['ordinal']:02d}-{gmail_id}.eml"
            if eml_path.exists():
                if sha256_file(require_owner_file(eml_path)) != sha256_bytes(actual):
                    raise GmailRestError("gmail_rest_eml_conflict")
            else:
                atomic_write(eml_path, actual)
            marker = client.marker
            intent["provider_calls"] = int(marker["action_api_calls"][str(action_id)])
            intent["updated_at_utc"] = utc_now()
            validate_schema(intent, "m10_gmail_rest_intent_v1")
            atomic_json(intent_path, intent)
            return _finalize_success(
                connection,
                action=action,
                email=email,
                gmail_id=gmail_id,
                eml_path=eml_path,
                marker=marker,
                reused=reused,
            )
        finally:
            connection.close()


def _record_delivery_failure(
    candidate_root: Path, action_id: int, error_code: str
) -> None:
    """Move a started action to the only safe local terminal/unknown state."""

    try:
        marker = _load_marker(candidate_root)
        database = require_owner_file(Path(marker["database"]))
        with workflow_lock(database):
            connection = connect(database)
            try:
                row = connection.execute(
                    "SELECT status FROM external_actions WHERE id=?", (action_id,)
                ).fetchone()
                if row is None or row[0] not in {"in_progress", "unknown"}:
                    return
                intent_path = (
                    candidate_root / f"gmail-rest/actions/{action_id}/intent.json"
                )
                send_started = bool(
                    intent_path.exists()
                    and read_owner_json(intent_path).get("send_started") is True
                )
                uncertain = send_started or error_code in {
                    "gmail_rest_message_id_ambiguous",
                    "gmail_rest_mime_mismatch",
                    "gmail_rest_confirmation_invalid",
                    "gmail_rest_get_failed",
                    "gmail_rest_send_result_unknown",
                    "gmail_rest_send_unconfirmed",
                }
                status = "unknown" if uncertain else "failed_safe"
                connection.execute(
                    "UPDATE external_actions SET status=?,finished_at_utc=?,"
                    "last_reconciled_at_utc=?,error_code=?,error_summary=? WHERE id=?",
                    (
                        status,
                        utc_now() if status == "failed_safe" else None,
                        utc_now(),
                        error_code,
                        "gmail_rest_delivery_stopped",
                        action_id,
                    ),
                )
                connection.commit()
            finally:
                connection.close()
    except (GmailRestError, OSError, sqlite3.Error):
        return


def deliver_action(
    *,
    candidate_root: Path,
    token_file: Path,
    action_id: int,
    session_factory: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    try:
        return _deliver_action(
            candidate_root=candidate_root,
            token_file=token_file,
            action_id=action_id,
            session_factory=session_factory,
        )
    except GmailRestError as exc:
        _record_delivery_failure(candidate_root, action_id, str(exc))
        raise


def confirm_canary(candidate_root: Path) -> dict[str, Any]:
    root = require_owner_directory(candidate_root)
    marker = _load_marker(root)
    database = require_owner_file(Path(marker["database"]))
    connection = connect(database, read_only=True, immutable=True)
    try:
        row = connection.execute(
            "SELECT status FROM external_actions WHERE id=?", (marker["action_ids"][0],)
        ).fetchone()
    finally:
        connection.close()
    if row is None or row[0] not in {"succeeded", "already_done"}:
        raise GmailRestError("gmail_rest_canary_not_succeeded")
    marker["canary_confirmed"] = True
    marker["canary_confirmed_at_utc"] = utc_now()
    atomic_json(root / MARKER_NAME, marker)
    return {"status": "succeeded", "canary_confirmed": True}


def deliver_batch(
    *,
    candidate_root: Path,
    token_file: Path,
    auth_receipt_file: Path | None = None,
    remaining: bool,
    session_factory: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    marker = _load_marker(candidate_root)
    if marker["auth_provider_calls"] == 0:
        if auth_receipt_file is None:
            raise GmailRestError("gmail_rest_auth_receipt_required")
        marker = _bind_auth_receipt(candidate_root, marker, auth_receipt_file)
    elif auth_receipt_file is not None:
        marker = _bind_auth_receipt(candidate_root, marker, auth_receipt_file)
    ids = marker["action_ids"][1:] if remaining else marker["action_ids"][:1]
    if remaining and not marker.get("canary_confirmed"):
        raise GmailRestError("gmail_rest_canary_confirmation_required")
    results = []
    for action_id in ids:
        results.append(
            deliver_action(
                candidate_root=candidate_root,
                token_file=token_file,
                action_id=int(action_id),
                session_factory=session_factory,
            )
        )
    return {"status": "succeeded", "delivered": len(results)}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build-candidate")
    build.add_argument("--parent-source", type=Path, default=PARENT_SOURCE)
    build.add_argument("--parent-run-root", type=Path, default=PARENT_RUN_ROOT)
    build.add_argument("--candidate-root", type=Path, required=True)
    build.add_argument("--email-file", type=Path, default=SOURCE_ROOT / "email.json")
    for name in ("deliver-canary", "deliver-remaining"):
        command = commands.add_parser(name)
        command.add_argument("--candidate-root", type=Path, required=True)
        command.add_argument(
            "--token-file", type=Path, default=SOURCE_ROOT / "gmail-api-token.json"
        )
        command.add_argument(
            "--auth-receipt", type=Path, default=SOURCE_ROOT / AUTH_RECEIPT_NAME
        )
    confirm = commands.add_parser("confirm-canary")
    confirm.add_argument("--candidate-root", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "build-candidate":
            result = create_candidate(
                parent_source=args.parent_source,
                parent_run_root=args.parent_run_root,
                candidate_root=args.candidate_root,
                email_file=args.email_file,
            )
        elif args.command == "confirm-canary":
            result = confirm_canary(args.candidate_root)
        else:
            result = deliver_batch(
                candidate_root=args.candidate_root,
                token_file=args.token_file,
                auth_receipt_file=args.auth_receipt,
                remaining=args.command == "deliver-remaining",
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (GmailRestError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"status": "blocked", "error_code": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
