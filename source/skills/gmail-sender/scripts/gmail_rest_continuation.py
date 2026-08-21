#!/usr/bin/env python3
"""M10 Gmail REST continuation and corrected-title resend host."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sqlite3
import stat
import sys
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as datetime_time
from pathlib import Path
from types import ModuleType
from typing import Any
from zoneinfo import ZoneInfo

RUNTIME_SOURCE_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = RUNTIME_SOURCE_ROOT
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from gmail_rest_common import (  # noqa: E402
    GmailRestError,
    atomic_json,
    atomic_write,
    canonical_json,
    deterministic_mime,
    gmail_raw,
    private_directory,
    read_owner_json,
    read_recipient,
    require_gmail_message_id,
    require_owner_directory,
    require_owner_file,
    sha256_bytes,
    sha256_file,
    sha256_text,
    validate_schema,
    verify_mime_with_actual_message_id,
)
from gmail_rest_delivery import (  # noqa: E402
    AUTH_API_CALLS,
    MAX_API_CALLS,
    MAX_SEND_CALLS,
    READ_PHASES,
    GmailRestClient,
    _require_bound_auth_receipt,
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

BATCH_ID = "m10-r07-gmail-rest-continuation"
WORKFLOW_KEY = "m10:r07:gmail:2026-08-20"
MARKER_NAME = "m10-r07-candidate.json"
PARENT_MARKER_NAME = "m10-r06-candidate.json"
PARENT_R06_ROOT = Path("/private/tmp/trainlab-m10-gmail-r06-attempt-02.WvdBgv")
EXPECTED_PARENT_MARKER_SHA256 = (
    "03ba98cad49b1c58c770edb3b43beacc8e7401f5923a9fcf8917ef2720ccd47a"
)
EXPECTED_PARENT_DATABASE_SHA256 = (
    "c611353c18619b6066e09a3ad1d1180bd57a7073cdb9f32344783592c1d197a0"
)
EXPECTED_PARENT_TREE_SHA256 = (
    "70a9a05d9e28031508b85a0a8600b4eef64a890c10596258076f7250317646df"
)
EXPECTED_PRE_CANARY_BOUNDARY_SHA256 = (
    "1a6c4e0915f678a8c5f251038210ec829b46dbad6e67e44c932d3b6dbc004400"
)
EXPECTED_CANARY_EML_SHA256 = (
    "145ca420d3d7e90e8c208203ca256fe8e0004c514b9c21ce25fbd9ad087e01b8"
)
NEW_SUBJECTS = {
    2: "TrainLab-Date(2026-08-13)",
    3: "TrainLab-Date(2026-08-14)",
    4: "TrainLab-Date(2026-08-15)",
    5: "TrainLab-Date(2026-08-16)",
    6: "TrainLab-Date(2026-08-17)",
    7: "TrainLab-Date(2026-08-18)",
    8: "TrainLab-Week(2026-08-12~2026-08-18)",
}


@dataclass(frozen=True)
class ContinuationPolicy:
    """Versioned delivery identity; provider I/O stays in one shared state machine."""

    batch_id: str
    workflow_key: str
    marker_name: str
    schema_version: str
    preview_schema: str
    intent_schema: str
    result_schema: str
    storage_name: str
    logical_prefix: str
    title_prefix: str
    subjects: dict[int, str]
    ordinals: tuple[int, ...]
    prior_api_calls: int
    prior_send_calls: int
    delivery_api_budget: int
    send_budget: int
    provider_budget: int
    canary_ordinal: int | None


R07_POLICY = ContinuationPolicy(
    batch_id=BATCH_ID,
    workflow_key=WORKFLOW_KEY,
    marker_name=MARKER_NAME,
    schema_version="m10_gmail_rest_candidate_v2",
    preview_schema="m10_gmail_rest_preview_v2",
    intent_schema="m10_gmail_rest_intent_v2",
    result_schema="m10_gmail_rest_result_v2",
    storage_name="gmail-rest-r07",
    logical_prefix="m10:r07",
    title_prefix="M10 r07",
    subjects=NEW_SUBJECTS,
    ordinals=tuple(range(2, 9)),
    prior_api_calls=4,
    prior_send_calls=1,
    delivery_api_budget=128,
    send_budget=8,
    provider_budget=129,
    canary_ordinal=None,
)

R08_BATCH_ID = "m10-r08-gmail-rest-corrected-subjects"
R08_WORKFLOW_KEY = "m10:r08:gmail:2026-08-20"
R08_MARKER_NAME = "m10-r08-candidate.json"
R08_PARENT_ROOT = Path("/private/tmp/trainlab-m10-gmail-r07.hhBZC2/continuation")
R08_PARENT_MARKER_SHA256 = (
    "85977bd85cbc8bd7c489e033e2a028651f4b54c86880feb7a06776870c5695ca"
)
R08_PARENT_DATABASE_SHA256 = (
    "5bd6d51a95a0519eb2eb863032cfdc7b1805d8edb00eae47e773eb76c411fde5"
)
R08_PARENT_TREE_SHA256 = (
    "a0e1d384e744ec920f4a5eda5c1218dfa13334861f63326ff308751cce728ff3"
)
R08_SUBJECTS = {
    **{
        ordinal: f"TrainLab · 每日训练简报 · 2026-08-{ordinal + 11:02d}"
        for ordinal in range(1, 8)
    },
    8: "TrainLab · 每周总结 · 2026-08-12~2026-08-18",
}
R08_POLICY = ContinuationPolicy(
    batch_id=R08_BATCH_ID,
    workflow_key=R08_WORKFLOW_KEY,
    marker_name=R08_MARKER_NAME,
    schema_version="m10_gmail_rest_candidate_v3",
    preview_schema="m10_gmail_rest_preview_v3",
    intent_schema="m10_gmail_rest_intent_v3",
    result_schema="m10_gmail_rest_result_v3",
    storage_name="gmail-rest-r08",
    logical_prefix="m10:r08",
    title_prefix="M10 r08",
    subjects=R08_SUBJECTS,
    ordinals=tuple(range(1, 9)),
    prior_api_calls=32,
    prior_send_calls=8,
    delivery_api_budget=160,
    send_budget=16,
    provider_budget=161,
    canary_ordinal=1,
)
RUNTIME_FILES = (
    "requirements.txt",
    "skills/_shared/state.py",
    "skills/_shared/schemas/gmail_rest_auth_receipt_v1.schema.json",
    "skills/_shared/schemas/m10_gmail_rest_intent_v1.schema.json",
    "skills/_shared/schemas/m10_gmail_rest_intent_v2.schema.json",
    "skills/_shared/schemas/m10_gmail_rest_preview_v1.schema.json",
    "skills/_shared/schemas/m10_gmail_rest_preview_v2.schema.json",
    "skills/_shared/schemas/m10_gmail_rest_result_v1.schema.json",
    "skills/_shared/schemas/m10_gmail_rest_result_v2.schema.json",
    "skills/_shared/schemas/m10_gmail_rest_intent_v3.schema.json",
    "skills/_shared/schemas/m10_gmail_rest_preview_v3.schema.json",
    "skills/_shared/schemas/m10_gmail_rest_result_v3.schema.json",
    "skills/gmail-sender/SKILL.md",
    "skills/gmail-sender/scripts/gmail_rest_auth.py",
    "skills/gmail-sender/scripts/gmail_rest_common.py",
    "skills/gmail-sender/scripts/gmail_rest_delivery.py",
    "skills/gmail-sender/scripts/gmail_rest_continuation.py",
)


def _runtime_sha256() -> str:
    entries: dict[str, str] = {}
    for relative in RUNTIME_FILES:
        path = RUNTIME_SOURCE_ROOT / relative
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
        ):
            raise GmailRestError("gmail_rest_runtime_file_invalid")
        entries[relative] = sha256_file(path)
    return sha256_text(canonical_json(entries))


def _tree_sha256(root: Path) -> str:
    require_owner_directory(root)
    items: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        relative = path.relative_to(root).as_posix()
        base = {
            "path": relative,
            "mode": stat.S_IMODE(metadata.st_mode),
            "uid": metadata.st_uid,
            "nlink": metadata.st_nlink,
        }
        if stat.S_ISDIR(metadata.st_mode) and not path.is_symlink():
            items.append({**base, "type": "dir"})
        elif stat.S_ISREG(metadata.st_mode) and not path.is_symlink():
            items.append(
                {
                    **base,
                    "type": "file",
                    "size": metadata.st_size,
                    "sha256": sha256_file(path),
                }
            )
        else:
            raise GmailRestError("gmail_rest_parent_tree_invalid")
    return sha256_text(canonical_json(items))


def _secure_copy(source: Path, target: Path) -> None:
    require_owner_file(source, allow_empty=True)
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


def _clone_candidate_tree(parent: Path, target: Path) -> None:
    require_owner_directory(parent)
    target.mkdir(mode=0o700)
    excluded = {
        "source/state/trainlab.db",
        "source/state/trainlab.db-wal",
        "source/state/trainlab.db-shm",
        "source/state/trainlab.lock",
    }
    for current_root, directories, files in os.walk(parent, followlinks=False):
        current = Path(current_root)
        relative = current.relative_to(parent)
        destination = target / relative
        os.chmod(destination, 0o700)
        for name in list(directories):
            source_directory = current / name
            metadata = source_directory.lstat()
            if source_directory.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
                raise GmailRestError("gmail_rest_parent_tree_invalid")
            (destination / name).mkdir(mode=0o700)
        for name in files:
            source_file = current / name
            relative_file = source_file.relative_to(parent).as_posix()
            if relative_file in excluded:
                continue
            _secure_copy(source_file, destination / name)


def _backup_database(source: Path, target: Path) -> None:
    require_owner_file(source)
    wal = Path(f"{source}-wal")
    if wal.exists() and wal.stat().st_size != 0:
        raise GmailRestError("gmail_rest_parent_wal_nonempty")
    descriptor = os.open(
        target,
        os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    os.close(descriptor)
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


def _load_renderer() -> ModuleType:
    path = SOURCE_ROOT / "skills/training-report-publisher/scripts/render_report.py"
    spec = importlib.util.spec_from_file_location("trainlab_r07_renderer", path)
    if spec is None or spec.loader is None:
        raise GmailRestError("gmail_rest_renderer_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_period(
    connection: sqlite3.Connection, source_output_id: int, source_sha256: str
) -> tuple[str, str, str, dict[str, Any]]:
    row = connection.execute(
        "SELECT content_sha256,schema_name,period_start_date,period_end_date,content_json "
        "FROM skill_outputs WHERE id=?",
        (source_output_id,),
    ).fetchone()
    if row is None or str(row[0]) != source_sha256:
        raise GmailRestError("gmail_rest_retitle_lineage_invalid")
    try:
        payload = json.loads(str(row[4]))
    except (TypeError, json.JSONDecodeError) as exc:
        raise GmailRestError("gmail_rest_retitle_lineage_invalid") from exc
    if not isinstance(payload, dict):
        raise GmailRestError("gmail_rest_retitle_lineage_invalid")
    return str(row[1]), str(row[2]), str(row[3]), payload


def _retitle_email_render(
    connection: sqlite3.Connection,
    *,
    ordinal: int,
    old_item: dict[str, Any],
    candidate_root: Path,
    policy: ContinuationPolicy = R07_POLICY,
) -> tuple[int, str, dict[str, Any], Path]:
    old_output_id = int(old_item["source_output_id"])
    old_output_sha = str(old_item["source_output_sha256"])
    old_envelope = read_owner_json(
        candidate_root / str(old_item["envelope_relative_path"])
    )
    old = connection.execute(
        "SELECT content_sha256,content_json,content_text,content_html,title_text,"
        "schema_name,lineage_json FROM skill_outputs WHERE id=? AND output_kind='email_render'",
        (old_output_id,),
    ).fetchone()
    if old is None or str(old[0]) != old_output_sha:
        raise GmailRestError("gmail_rest_retitle_source_invalid")
    if (
        old_envelope.get("report_output_id") != old_output_id
        or old_envelope.get("report_output_sha256") != old_output_sha
        or old_envelope.get("subject") != old[4]
        or old_envelope.get("text") != old[2]
        or old_envelope.get("html") != old[3]
    ):
        raise GmailRestError("gmail_rest_retitle_source_invalid")
    try:
        old_payload = json.loads(str(old[1]))
    except (TypeError, json.JSONDecodeError) as exc:
        raise GmailRestError("gmail_rest_retitle_source_invalid") from exc
    if set(old_payload) != {"title", "period", "content"}:
        raise GmailRestError("gmail_rest_retitle_source_invalid")
    ai_id = int(old_envelope["source_output_id"])
    ai_sha = str(old_envelope["source_output_sha256"])
    schema_name, start, end, ai_payload = _source_period(connection, ai_id, ai_sha)
    expected_ai_schema = "daily_ai_result_v1" if ordinal < 8 else "weekly_ai_result_v1"
    if schema_name != expected_ai_schema or canonical_json(
        ai_payload
    ) != canonical_json(old_payload["content"]):
        raise GmailRestError("gmail_rest_retitle_lineage_invalid")
    expected_start = f"2026-08-{ordinal + 11:02d}" if ordinal < 8 else "2026-08-12"
    expected_end = f"2026-08-{ordinal + 11:02d}" if ordinal < 8 else "2026-08-18"
    if (start, end) != (expected_start, expected_end):
        raise GmailRestError("gmail_rest_retitle_period_invalid")
    subject = policy.subjects[ordinal]
    payload = {"title": subject, "period": old_payload["period"], "content": ai_payload}
    renderer = _load_renderer()
    kind = "daily" if ordinal < 8 else "weekly"
    template = (SOURCE_ROOT / f"templates/open-report/{kind}_report.html").read_text(
        encoding="utf-8"
    )
    html = renderer.render(
        template,
        subject,
        str(payload["period"]),
        renderer.body_html(ai_payload),
        fixed=False,
        payload=payload,
    )
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    digest = sha256_text(
        canonical_json(
            {
                "ordinal": ordinal,
                "old_output_id": old_output_id,
                "old_output_sha256": old_output_sha,
                "title": subject,
                "content": ai_payload,
            }
        )
    )
    run_id = begin_run(
        connection,
        run_key=f"{policy.logical_prefix}-retitle:{ordinal}:{digest}:attempt-1",
        workflow_key=policy.workflow_key,
        dedupe_key=digest,
        skill_name="training-report-publisher",
        operation="render_daily" if ordinal < 8 else "render_weekly",
        trigger_kind="manual",
        target_from_date=start,
        target_through_date=end,
        input_manifest={
            "m10_role": f"{policy.logical_prefix.replace(':', '_')}_gmail_retitle",
            "ordinal": ordinal,
            "prior_output_id": old_output_id,
        },
    )
    new_output_id = append_output(
        connection,
        skill_run_id=run_id,
        output_kind="email_render",
        logical_key=(
            f"training-report-publisher:{kind}:open_report:email:"
            f"{policy.logical_prefix.split(':')[1]}:{end}"
        ),
        schema_name=str(old[5]),
        schema_version="2",
        title_text=subject,
        content_json=payload,
        content_text=text,
        content_html=html,
        period_start_date=start,
        period_end_date=end,
        lineage=[
            {"output_id": old_output_id, "output_sha256": old_output_sha},
            {"output_id": ai_id, "output_sha256": ai_sha},
            {"input_sha256": digest},
        ],
    )
    finish_run(connection, run_id, status="succeeded")
    output = connection.execute(
        "SELECT content_sha256 FROM skill_outputs WHERE id=?", (new_output_id,)
    ).fetchone()
    if output is None:
        raise GmailRestError("gmail_rest_retitle_output_missing")
    output_sha = str(output[0])
    envelope = {
        "subject": subject,
        "text": text,
        "html": html,
        "source_output_id": ai_id,
        "source_output_sha256": ai_sha,
        "report_output_id": new_output_id,
        "report_output_sha256": output_sha,
    }
    storage_root = private_directory(candidate_root / policy.storage_name)
    input_root = private_directory(storage_root / "input")
    envelope_path = input_root / f"{ordinal:02d}-email-envelope.json"
    atomic_json(envelope_path, envelope)
    return new_output_id, output_sha, envelope, envelope_path


def _canary_evidence(
    connection: sqlite3.Connection,
    *,
    candidate_root: Path,
    parent_root: Path,
    parent_marker: dict[str, Any],
    parent_preview: dict[str, Any],
) -> dict[str, Any]:
    if (
        parent_marker.get("api_calls") != 4
        or parent_marker.get("send_calls") != 1
        or parent_marker.get("canary_confirmed") is not False
    ):
        raise GmailRestError("gmail_rest_canary_history_invalid")
    action_id = int(parent_marker["action_ids"][0])
    action = connection.execute(
        "SELECT status,attempt_count,result_external_id,provider_marker FROM external_actions WHERE id=?",
        (action_id,),
    ).fetchone()
    if action is None or action[0] != "unknown" or int(action[1]) != 1:
        raise GmailRestError("gmail_rest_canary_history_invalid")
    item = parent_preview["emails"][0]
    envelope = read_owner_json(candidate_root / item["envelope_relative_path"])
    send_capture = read_owner_json(
        candidate_root / f"gmail-rest/captures/002-{action_id}-send.json"
    )
    raw_one = read_owner_json(
        candidate_root / f"gmail-rest/captures/003-{action_id}-get-raw-1.json"
    )
    raw_two = read_owner_json(
        candidate_root / f"gmail-rest/captures/004-{action_id}-get-raw-2.json"
    )
    gmail_id = require_gmail_message_id(send_capture.get("response", {}).get("id"))
    if (
        send_capture.get("status_code") != 200
        or raw_one.get("status_code") != 200
        or raw_two.get("status_code") != 200
        or raw_one.get("response", {}).get("id") != gmail_id
        or raw_two.get("response", {}).get("id") != gmail_id
        or raw_one.get("response", {}).get("raw_sha256")
        != raw_two.get("response", {}).get("raw_sha256")
    ):
        raise GmailRestError("gmail_rest_canary_capture_invalid")
    provider_eml = require_owner_file(parent_root / "mismatch-canary-provider.eml")
    provider_eml_bytes = provider_eml.read_bytes()
    if sha256_bytes(provider_eml_bytes) != EXPECTED_CANARY_EML_SHA256 or raw_one.get(
        "response", {}
    ).get("raw_sha256") != sha256_text(gmail_raw(provider_eml_bytes)):
        raise GmailRestError("gmail_rest_canary_capture_invalid")
    evidence_root = private_directory(candidate_root / "gmail-rest-r07/evidence")
    eml_path = evidence_root / "canary-provider.eml"
    _secure_copy(provider_eml, eml_path)
    recipient, recipient_sha = read_recipient(SOURCE_ROOT / "email.json")
    if recipient_sha != item["recipient_sha256"]:
        raise GmailRestError("gmail_rest_recipient_changed")
    actual_message_id = verify_mime_with_actual_message_id(
        eml_path.read_bytes(),
        recipient=recipient,
        subject=str(envelope["subject"]),
        plain=str(envelope["text"]),
        html=str(envelope["html"]),
    )
    result = {
        "schema_version": "m10_gmail_rest_result_v2",
        "batch_id": BATCH_ID,
        "status": "succeeded",
        "action_id": action_id,
        "ordinal": 1,
        "requested_message_id": item["message_id"],
        "actual_message_id": actual_message_id,
        "gmail_message_id": gmail_id,
        "eml_relative_path": str(eml_path.relative_to(candidate_root)),
        "eml_sha256": sha256_file(eml_path),
        "content_verified": True,
        "confirmation_kind": "manual_user_confirmation",
        "provider_calls": 4,
        "send_calls": 1,
        "completed_at_utc": utc_now(),
    }
    validate_schema(result, "m10_gmail_rest_result_v2")
    digest = sha256_text(canonical_json(result))
    run_id = begin_run(
        connection,
        run_key=f"m10-r07-canary-reconcile:{digest}:attempt-1",
        workflow_key=WORKFLOW_KEY,
        dedupe_key=digest,
        skill_name="gmail-sender",
        operation="reconcile_gmail",
        trigger_kind="manual",
        input_manifest={
            "m10_role": "m10_gmail_canary_reconciliation_v2",
            "action_id": action_id,
            "provider_calls": 0,
            "user_confirmed": True,
        },
    )
    output_id = append_output(
        connection,
        skill_run_id=run_id,
        output_kind="execution_summary",
        logical_key="m10:r07:gmail-result:canary",
        schema_name="m10_gmail_rest_result_v2",
        schema_version="2",
        title_text="M10 r07 Gmail canary reconciliation",
        content_json=result,
        content_text=canonical_json(result),
        lineage=[
            {
                "output_id": int(parent_marker["preview_output_id"]),
                "output_sha256": str(parent_marker["preview_output_sha256"]),
            },
            {
                "output_id": int(item["source_output_id"]),
                "output_sha256": str(item["source_output_sha256"]),
            },
        ],
    )
    finish_run(connection, run_id, status="succeeded")
    output = connection.execute(
        "SELECT content_sha256 FROM skill_outputs WHERE id=?", (output_id,)
    ).fetchone()
    if output is None:
        raise GmailRestError("gmail_rest_canary_reconciliation_missing")
    connection.execute(
        "UPDATE external_actions SET status='succeeded',result_external_id=?,provider_marker=?,"
        "finished_at_utc=?,last_reconciled_at_utc=?,response_summary_json=?,"
        "error_code=NULL,error_summary=NULL WHERE id=? AND status='unknown'",
        (
            gmail_id,
            actual_message_id,
            utc_now(),
            utc_now(),
            canonical_json(
                {
                    "verified": True,
                    "user_confirmed": True,
                    "requested_message_id": item["message_id"],
                    "actual_message_id": actual_message_id,
                    "eml_sha256": result["eml_sha256"],
                }
            ),
            action_id,
        ),
    )
    if connection.execute("SELECT changes()").fetchone()[0] != 1:
        raise GmailRestError("gmail_rest_canary_reconciliation_invalid")
    connection.commit()
    return {
        "action_id": action_id,
        "requested_message_id": item["message_id"],
        "actual_message_id": actual_message_id,
        "gmail_message_id": gmail_id,
        "eml_relative_path": str(eml_path.relative_to(candidate_root)),
        "eml_sha256": result["eml_sha256"],
        "reconciliation_output_id": output_id,
        "reconciliation_output_sha256": str(output[0]),
        "user_confirmed": True,
        "provider_calls": 4,
        "send_calls": 1,
    }


def _cancel_prior_actions(
    connection: sqlite3.Connection, parent_marker: dict[str, Any]
) -> None:
    prior = [int(value) for value in parent_marker["action_ids"][1:]]
    if len(prior) != 7:
        raise GmailRestError("gmail_rest_prior_actions_invalid")
    placeholders = ",".join("?" for _ in prior)
    rows = connection.execute(
        f"SELECT id,status,attempt_count FROM external_actions WHERE id IN ({placeholders}) ORDER BY id",
        prior,
    ).fetchall()
    if len(rows) != 7 or any(row[1] != "prepared" or row[2] != 0 for row in rows):
        raise GmailRestError("gmail_rest_prior_actions_invalid")
    for action_id in prior:
        connection.execute(
            "UPDATE external_actions SET status='cancelled',finished_at_utc=?,error_code=?,"
            "error_summary=? WHERE id=? AND status='prepared'",
            (
                utc_now(),
                "gmail_rest_subject_superseded",
                "superseded_by_m10_r07_title_contract",
                action_id,
            ),
        )
    connection.commit()


def _email_request(
    email: dict[str, Any], policy: ContinuationPolicy = R07_POLICY
) -> dict[str, Any]:
    return {
        "transport": "gmail_rest",
        "batch_id": policy.batch_id,
        "ordinal": email["ordinal"],
        "requested_message_id": email["requested_message_id"],
        "mime_sha256": email["mime_sha256"],
        "recipient_sha256": email["recipient_sha256"],
        "source_output_id": email["source_output_id"],
        "source_output_sha256": email["source_output_sha256"],
    }


def _action_target(
    email: dict[str, Any], policy: ContinuationPolicy = R07_POLICY
) -> str:
    version = policy.logical_prefix.split(":")[1]
    return f"gmail-rest:m10-{version}:{email['requested_message_id'][10:74]}"


def _approval_scope(
    email: dict[str, Any], policy: ContinuationPolicy = R07_POLICY
) -> dict[str, Any]:
    return {
        "provider": "gmail",
        "action_kind": "gmail_send",
        "entity_kind": "email",
        "target_key": _action_target(email, policy),
        "scope_kind": "gmail",
        "budget": {"max_actions": 1},
    }


def _build_preview_and_actions(
    connection: sqlite3.Connection,
    *,
    candidate_root: Path,
    parent_marker_sha: str,
    parent_database_sha: str,
    parent_marker: dict[str, Any],
    parent_preview: dict[str, Any],
    canary: dict[str, Any],
) -> tuple[int, str, dict[str, Any], list[int]]:
    recipient, recipient_sha = read_recipient(SOURCE_ROOT / "email.json")
    emails: list[dict[str, Any]] = []
    for ordinal in range(2, 9):
        old_item = parent_preview["emails"][ordinal - 1]
        output_id, output_sha, envelope, envelope_path = _retitle_email_render(
            connection,
            ordinal=ordinal,
            old_item=old_item,
            candidate_root=candidate_root,
        )
        period_end = f"2026-08-{ordinal + 11:02d}" if ordinal < 8 else "2026-08-18"
        date_value = datetime.combine(
            date.fromisoformat(period_end),
            datetime_time(hour=12),
            ZoneInfo("Asia/Hong_Kong"),
        )
        raw, requested_id, mime_sha = deterministic_mime(
            recipient=recipient,
            subject=str(envelope["subject"]),
            plain=str(envelope["text"]),
            html=str(envelope["html"]),
            source_sha256=output_sha,
            date_value=date_value,
        )
        mime_path = candidate_root / f"gmail-rest-r07/input/{ordinal:02d}-message.eml"
        atomic_write(mime_path, raw)
        request = {
            "transport": "gmail_rest",
            "batch_id": BATCH_ID,
            "ordinal": ordinal,
            "requested_message_id": requested_id,
            "mime_sha256": mime_sha,
            "recipient_sha256": recipient_sha,
            "source_output_id": output_id,
            "source_output_sha256": output_sha,
        }
        emails.append(
            {
                "ordinal": ordinal,
                "prior_source_output_id": int(old_item["source_output_id"]),
                "prior_source_output_sha256": str(old_item["source_output_sha256"]),
                "source_output_id": output_id,
                "source_output_sha256": output_sha,
                "envelope_relative_path": str(
                    envelope_path.relative_to(candidate_root)
                ),
                "envelope_sha256": sha256_file(envelope_path),
                "recipient_sha256": recipient_sha,
                "subject": NEW_SUBJECTS[ordinal],
                "subject_sha256": sha256_text(NEW_SUBJECTS[ordinal]),
                "requested_message_id": requested_id,
                "mime_sha256": mime_sha,
                "request_sha256": sha256_text(canonical_json(request)),
            }
        )
    if (
        [item["ordinal"] for item in emails] != list(range(2, 9))
        or len({item["requested_message_id"] for item in emails}) != 7
        or len({item["source_output_id"] for item in emails}) != 7
    ):
        raise GmailRestError("gmail_rest_continuation_set_invalid")
    unsigned = {
        "schema_version": "m10_gmail_rest_preview_v2",
        "batch_id": BATCH_ID,
        "transport": "gmail_rest",
        "parent_marker_sha256": parent_marker_sha,
        "parent_database_sha256": parent_database_sha,
        "parent_preview_output_id": int(parent_marker["preview_output_id"]),
        "parent_preview_output_sha256": str(parent_marker["preview_output_sha256"]),
        "completed_canary": canary,
        "emails": emails,
        "prior_api_calls": 4,
        "prior_send_calls": 1,
        "gmail_api_budget": MAX_API_CALLS,
        "gmail_send_budget": MAX_SEND_CALLS,
    }
    preview = {**unsigned, "preview_sha256": sha256_text(canonical_json(unsigned))}
    validate_schema(preview, "m10_gmail_rest_preview_v2")
    digest = sha256_text(canonical_json(preview))
    run_id = begin_run(
        connection,
        run_key=f"m10-r07-preview:{digest}:attempt-1",
        workflow_key=WORKFLOW_KEY,
        dedupe_key=digest,
        skill_name="gmail-sender",
        operation="send_email",
        trigger_kind="manual",
        input_manifest={"m10_role": "m10_gmail_rest_prepare_v2", "batch_id": BATCH_ID},
    )
    preview_id = append_output(
        connection,
        skill_run_id=run_id,
        output_kind="execution_summary",
        logical_key="m10:r07:gmail-rest-preview",
        schema_name="m10_gmail_rest_preview_v2",
        schema_version="2",
        title_text="M10 r07 Gmail REST continuation preview",
        content_json=preview,
        content_text=canonical_json(preview),
        lineage=[
            {
                "output_id": int(parent_marker["preview_output_id"]),
                "output_sha256": str(parent_marker["preview_output_sha256"]),
            },
            {
                "output_id": int(canary["reconciliation_output_id"]),
                "output_sha256": str(canary["reconciliation_output_sha256"]),
            },
        ],
    )
    finish_run(connection, run_id, status="succeeded")
    preview_row = connection.execute(
        "SELECT content_sha256 FROM skill_outputs WHERE id=?", (preview_id,)
    ).fetchone()
    if preview_row is None:
        raise GmailRestError("gmail_rest_preview_missing")
    preview_sha = str(preview_row[0])
    action_ids: list[int] = []
    for item in emails:
        target_key = _action_target(item)
        scope = _approval_scope(item)
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
                f"m10-r07-preview:{preview['preview_sha256']}",
                "m10_r07_seven_email_delivery_approved",
                utc_now(),
                utc_now(),
                None,
            ),
        )
        approval_id = require_lastrowid(approval)
        request = _email_request(item)
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
        action_ids.append(require_lastrowid(action))
    connection.commit()
    return preview_id, preview_sha, preview, action_ids


def create_continuation(
    *,
    parent_root: Path,
    candidate_root: Path,
    confirm_canary_received: bool,
) -> dict[str, Any]:
    if not confirm_canary_received:
        raise GmailRestError("gmail_rest_canary_user_confirmation_required")
    parent_root = require_owner_directory(parent_root)
    parent_candidate = require_owner_directory(parent_root / "candidate")
    parent_marker_path = require_owner_file(parent_candidate / PARENT_MARKER_NAME)
    parent_database = require_owner_file(parent_candidate / "source/state/trainlab.db")
    pre_boundary = require_owner_file(parent_root / "pre-canary-boundary.json")
    parent_marker_sha = sha256_file(parent_marker_path)
    parent_database_sha = sha256_file(parent_database)
    if (
        parent_marker_sha != EXPECTED_PARENT_MARKER_SHA256
        or parent_database_sha != EXPECTED_PARENT_DATABASE_SHA256
        or sha256_file(pre_boundary) != EXPECTED_PRE_CANARY_BOUNDARY_SHA256
        or _tree_sha256(parent_candidate) != EXPECTED_PARENT_TREE_SHA256
    ):
        raise GmailRestError("gmail_rest_parent_r06_changed")
    parent_marker = read_owner_json(parent_marker_path)
    candidate_root = Path(os.path.abspath(candidate_root))
    if candidate_root.exists() or candidate_root.is_relative_to(SOURCE_ROOT.parent):
        raise GmailRestError("gmail_rest_candidate_scope_invalid")
    candidate_root.mkdir(mode=0o700)
    new_candidate = candidate_root / "candidate"
    with workflow_lock(parent_database):
        _clone_candidate_tree(parent_candidate, new_candidate)
        new_database = new_candidate / "source/state/trainlab.db"
        _backup_database(parent_database, new_database)
        if sha256_file(parent_database) != parent_database_sha:
            raise GmailRestError("gmail_rest_parent_changed_during_clone")
    descriptor = os.open(
        new_candidate / "source/state/trainlab.lock",
        os.O_CREAT | os.O_EXCL | os.O_RDWR,
        0o600,
    )
    os.close(descriptor)
    _secure_copy(pre_boundary, candidate_root / "pre-canary-boundary.json")
    for relative in RUNTIME_FILES:
        atomic_write(
            new_candidate / "source" / relative,
            (RUNTIME_SOURCE_ROOT / relative).read_bytes(),
        )
    if _tree_sha256(parent_candidate) != EXPECTED_PARENT_TREE_SHA256:
        raise GmailRestError("gmail_rest_parent_changed_during_clone")
    connection = connect(new_database)
    try:
        parent_preview_row = connection.execute(
            "SELECT content_json,content_sha256 FROM skill_outputs WHERE id=?",
            (int(parent_marker["preview_output_id"]),),
        ).fetchone()
        if (
            parent_preview_row is None
            or str(parent_preview_row[1]) != parent_marker["preview_output_sha256"]
        ):
            raise GmailRestError("gmail_rest_parent_preview_invalid")
        parent_preview = json.loads(str(parent_preview_row[0]))
        canary = _canary_evidence(
            connection,
            candidate_root=new_candidate,
            parent_root=parent_root,
            parent_marker=parent_marker,
            parent_preview=parent_preview,
        )
        _cancel_prior_actions(connection, parent_marker)
        preview_id, preview_sha, _preview, action_ids = _build_preview_and_actions(
            connection,
            candidate_root=new_candidate,
            parent_marker_sha=parent_marker_sha,
            parent_database_sha=parent_database_sha,
            parent_marker=parent_marker,
            parent_preview=parent_preview,
            canary=canary,
        )
    finally:
        connection.close()
    marker = {
        "schema_version": "m10_gmail_rest_candidate_v2",
        "batch_id": BATCH_ID,
        "candidate_source": str(new_candidate / "source"),
        "database": str(new_database),
        "parent_r06_root": str(parent_root),
        "parent_marker_sha256": parent_marker_sha,
        "parent_database_sha256": parent_database_sha,
        "runtime_sha256": _runtime_sha256(),
        "preview_output_id": preview_id,
        "preview_output_sha256": preview_sha,
        "completed_canary": canary,
        "action_ids": action_ids,
        "action_api_calls": {str(action_id): 0 for action_id in action_ids},
        "action_phase_calls": {
            str(action_id): {phase: 0 for phase in READ_PHASES}
            for action_id in action_ids
        },
        "action_send_calls": {str(action_id): 0 for action_id in action_ids},
        "auth_receipt_sha256": parent_marker["auth_receipt_sha256"],
        "auth_provider_calls": AUTH_API_CALLS,
        "canary_confirmed": True,
        "api_calls": 4,
        "send_calls": 1,
        "created_at_utc": utc_now(),
    }
    atomic_json(new_candidate / MARKER_NAME, marker)
    return {
        "status": "succeeded",
        "candidate_root": str(new_candidate),
        "completed_canary": 1,
        "remaining_actions": 7,
    }


def _load_marker(
    candidate_root: Path, policy: ContinuationPolicy = R07_POLICY
) -> dict[str, Any]:
    root = require_owner_directory(candidate_root)
    marker = read_owner_json(root / policy.marker_name)
    common_required = {
        "schema_version",
        "batch_id",
        "candidate_source",
        "database",
        "parent_marker_sha256",
        "parent_database_sha256",
        "runtime_sha256",
        "preview_output_id",
        "preview_output_sha256",
        "action_ids",
        "action_api_calls",
        "action_phase_calls",
        "action_send_calls",
        "auth_receipt_sha256",
        "auth_provider_calls",
        "canary_confirmed",
        "api_calls",
        "send_calls",
        "created_at_utc",
    }
    version_required = (
        {"parent_r06_root", "completed_canary"}
        if policy is R07_POLICY
        else {"parent_r07_root", "prior_results"}
    )
    required = common_required | version_required
    if set(marker) != required:
        raise GmailRestError("gmail_rest_continuation_marker_invalid")
    source = root / "source"
    action_keys = {str(value) for value in marker.get("action_ids", [])}
    if (
        marker["schema_version"] != policy.schema_version
        or marker["batch_id"] != policy.batch_id
        or marker["candidate_source"] != str(source)
        or marker["database"] != str(source / "state/trainlab.db")
        or marker["runtime_sha256"] != _runtime_sha256()
        or marker["parent_marker_sha256"]
        != (
            EXPECTED_PARENT_MARKER_SHA256
            if policy is R07_POLICY
            else R08_PARENT_MARKER_SHA256
        )
        or marker["parent_database_sha256"]
        != (
            EXPECTED_PARENT_DATABASE_SHA256
            if policy is R07_POLICY
            else R08_PARENT_DATABASE_SHA256
        )
        or not isinstance(marker["canary_confirmed"], bool)
        or marker["api_calls"] < policy.prior_api_calls
        or marker["send_calls"] < policy.prior_send_calls
        or len(marker["action_ids"]) != len(policy.ordinals)
        or len(set(marker["action_ids"])) != len(policy.ordinals)
        or set(marker["action_api_calls"]) != action_keys
        or set(marker["action_phase_calls"]) != action_keys
        or set(marker["action_send_calls"]) != action_keys
    ):
        raise GmailRestError("gmail_rest_continuation_marker_invalid")
    if policy is R07_POLICY and marker["canary_confirmed"] is not True:
        raise GmailRestError("gmail_rest_continuation_marker_invalid")
    if policy is R08_POLICY and (
        not isinstance(marker["prior_results"], list)
        or len(marker["prior_results"]) != 8
        or marker["api_calls"] > policy.delivery_api_budget
        or marker["send_calls"] > policy.send_budget
    ):
        raise GmailRestError("gmail_rest_continuation_marker_invalid")
    if policy is R08_POLICY and marker["canary_confirmed"] is True:
        confirmation = read_owner_json(
            root / policy.storage_name / "canary-user-confirmation.json"
        )
        if (
            set(confirmation)
            != {
                "schema_version",
                "action_id",
                "user_confirmed",
                "confirmed_at_utc",
            }
            or confirmation["schema_version"] != "m10_r08_canary_confirmation_v1"
            or confirmation["action_id"] != marker["action_ids"][0]
            or confirmation["user_confirmed"] is not True
        ):
            raise GmailRestError("gmail_rest_canary_confirmation_invalid")
    _require_bound_auth_receipt(root, marker)
    return marker


def _preview_and_action(
    connection: sqlite3.Connection,
    marker: dict[str, Any],
    action_id: int,
    policy: ContinuationPolicy = R07_POLICY,
) -> tuple[dict[str, Any], sqlite3.Row]:
    if action_id not in marker["action_ids"]:
        raise GmailRestError("gmail_rest_action_invalid")
    row = connection.execute(
        "SELECT content_json,content_sha256,schema_name,skill_run_id FROM skill_outputs WHERE id=?",
        (int(marker["preview_output_id"]),),
    ).fetchone()
    if (
        row is None
        or str(row[1]) != marker["preview_output_sha256"]
        or row[2] != policy.preview_schema
    ):
        raise GmailRestError("gmail_rest_action_invalid")
    preview = json.loads(str(row[0]))
    validate_schema(preview, policy.preview_schema)
    if [email["ordinal"] for email in preview["emails"]] != list(policy.ordinals):
        raise GmailRestError("gmail_rest_action_invalid")
    selected: tuple[dict[str, Any], sqlite3.Row] | None = None
    for index, expected_action_id in enumerate(marker["action_ids"]):
        email = preview["emails"][index]
        action = connection.execute(
            "SELECT * FROM external_actions WHERE id=?", (expected_action_id,)
        ).fetchone()
        if action is None:
            raise GmailRestError("gmail_rest_action_invalid")
        approval = connection.execute(
            "SELECT * FROM approvals WHERE id=?", (action["approval_id"],)
        ).fetchone()
        request = _email_request(email, policy)
        request_text = canonical_json(request)
        target_key = _action_target(email, policy)
        scope_text = canonical_json(_approval_scope(email, policy))
        approval_key = sha256_text(
            canonical_json({"batch": policy.batch_id, "ordinal": email["ordinal"]})
        )
        if (
            int(action["skill_run_id"]) != int(row[3])
            or action["provider"] != "gmail"
            or action["entity_kind"] != "email"
            or action["action_kind"] != "gmail_send"
            or int(action["source_output_id"]) != int(marker["preview_output_id"])
            or action["source_output_sha256"] != marker["preview_output_sha256"]
            or action["target_key"] != target_key
            or action["request_json"] != request_text
            or action["request_sha256"] != sha256_text(request_text)
            or action["idempotency_key"]
            != sha256_text(
                canonical_json({"batch": policy.batch_id, "request": request})
            )
            or approval is None
            or approval["approval_key"] != approval_key
            or int(approval["candidate_output_id"]) != int(marker["preview_output_id"])
            or approval["candidate_output_sha256"] != marker["preview_output_sha256"]
            or approval["authority_kind"] != "user_explicit"
            or approval["decision"] != "approved"
            or approval["scope_kind"] != "gmail"
            or approval["scope_json"] != scope_text
            or approval["scope_sha256"] != sha256_text(scope_text)
            or approval["source_ref"]
            != (
                f"m10-{policy.logical_prefix.split(':')[1]}-preview:"
                f"{preview['preview_sha256']}"
            )
            or approval["reason_code"]
            != (
                "m10_r07_seven_email_delivery_approved"
                if policy is R07_POLICY
                else "m10_r08_corrected_subject_resend_approved"
            )
        ):
            raise GmailRestError("gmail_rest_action_invalid")
        if expected_action_id == action_id:
            selected = email, action
    if selected is None:
        raise GmailRestError("gmail_rest_action_invalid")
    return selected


def _existing_result(
    connection: sqlite3.Connection,
    *,
    candidate_root: Path,
    action: sqlite3.Row,
    email: dict[str, Any],
    recipient: str,
    policy: ContinuationPolicy = R07_POLICY,
) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT content_json FROM skill_outputs WHERE logical_key=? ORDER BY revision_no DESC LIMIT 1",
        (f"{policy.logical_prefix}:gmail-result:{action['id']}",),
    ).fetchone()
    if row is None:
        return None
    result = json.loads(str(row[0]))
    validate_schema(result, policy.result_schema)
    eml_path = candidate_root / str(result["eml_relative_path"])
    eml = require_owner_file(eml_path)
    envelope = read_owner_json(candidate_root / email["envelope_relative_path"])
    actual_id = verify_mime_with_actual_message_id(
        eml.read_bytes(),
        recipient=recipient,
        subject=envelope["subject"],
        plain=envelope["text"],
        html=envelope["html"],
    )
    if (
        result["action_id"] != int(action["id"])
        or result["requested_message_id"] != email["requested_message_id"]
        or result["actual_message_id"] != actual_id
        or result["gmail_message_id"] != action["result_external_id"]
        or result["actual_message_id"] != action["provider_marker"]
        or result["eml_sha256"] != sha256_file(eml)
    ):
        raise GmailRestError("gmail_rest_result_invalid")
    return result


def _finalize_success(
    connection: sqlite3.Connection,
    *,
    candidate_root: Path,
    marker: dict[str, Any],
    action: sqlite3.Row,
    email: dict[str, Any],
    gmail_id: str,
    actual_message_id: str,
    eml_path: Path,
    reused: bool,
    policy: ContinuationPolicy = R07_POLICY,
) -> dict[str, Any]:
    result = {
        "schema_version": policy.result_schema,
        "batch_id": policy.batch_id,
        "status": "succeeded",
        "action_id": int(action["id"]),
        "ordinal": int(email["ordinal"]),
        "requested_message_id": email["requested_message_id"],
        "actual_message_id": actual_message_id,
        "gmail_message_id": gmail_id,
        "eml_relative_path": str(eml_path.relative_to(candidate_root)),
        "eml_sha256": sha256_file(eml_path),
        "content_verified": True,
        "confirmation_kind": "provider_query",
        "provider_calls": int(marker["action_api_calls"][str(action["id"])]),
        "send_calls": int(marker["action_send_calls"][str(action["id"])]),
        "completed_at_utc": utc_now(),
    }
    validate_schema(result, policy.result_schema)
    digest = sha256_text(canonical_json(result))
    run_id = begin_run(
        connection,
        run_key=f"{policy.logical_prefix}-delivery:{action['id']}:{digest}:attempt-1",
        workflow_key=policy.workflow_key,
        dedupe_key=sha256_text(
            f"{policy.batch_id}\0{action['id']}\0{email['request_sha256']}"
        ),
        skill_name="gmail-sender",
        operation="send_email",
        trigger_kind="manual",
        input_manifest={
            "m10_role": f"{policy.logical_prefix.replace(':', '_')}_gmail_delivery",
            "action_id": int(action["id"]),
        },
    )
    append_output(
        connection,
        skill_run_id=run_id,
        output_kind="execution_summary",
        logical_key=f"{policy.logical_prefix}:gmail-result:{action['id']}",
        schema_name=policy.result_schema,
        schema_version="2" if policy is R07_POLICY else "3",
        title_text=f"{policy.title_prefix} Gmail REST result {email['ordinal']}",
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
    connection.execute(
        "UPDATE external_actions SET status=?,result_external_id=?,provider_marker=?,"
        "finished_at_utc=?,last_reconciled_at_utc=?,response_summary_json=?,"
        "error_code=NULL,error_summary=NULL WHERE id=?",
        (
            "already_done" if reused else "succeeded",
            gmail_id,
            actual_message_id,
            utc_now(),
            utc_now(),
            canonical_json(
                {
                    "verified": True,
                    "requested_message_id": email["requested_message_id"],
                    "actual_message_id": actual_message_id,
                    "eml_sha256": result["eml_sha256"],
                }
            ),
            int(action["id"]),
        ),
    )
    connection.commit()
    return result


def deliver_action(
    *,
    candidate_root: Path,
    token_file: Path,
    action_id: int,
    session_factory: Any | None = None,
    policy: ContinuationPolicy = R07_POLICY,
) -> dict[str, Any]:
    root = require_owner_directory(candidate_root)
    marker = _load_marker(root, policy)
    database = require_owner_file(Path(marker["database"]))
    with workflow_lock(database):
        connection = connect(database)
        try:
            email, action = _preview_and_action(connection, marker, action_id, policy)
            if (
                policy.canary_ordinal is not None
                and int(email["ordinal"]) != policy.canary_ordinal
                and marker["canary_confirmed"] is not True
            ):
                raise GmailRestError("gmail_rest_canary_user_confirmation_required")
            recipient, recipient_sha = read_recipient(SOURCE_ROOT / "email.json")
            if recipient_sha != email["recipient_sha256"]:
                raise GmailRestError("gmail_rest_recipient_changed")
            existing = _existing_result(
                connection,
                candidate_root=root,
                action=action,
                email=email,
                recipient=recipient,
                policy=policy,
            )
            if action["status"] in {"succeeded", "already_done"} and existing:
                return existing
            if action["status"] not in {"prepared", "in_progress", "unknown"}:
                raise GmailRestError("gmail_rest_action_not_deliverable")
            envelope_path = require_owner_file(root / email["envelope_relative_path"])
            if sha256_file(envelope_path) != email["envelope_sha256"]:
                raise GmailRestError("gmail_rest_envelope_changed")
            envelope = read_owner_json(envelope_path)
            if (
                envelope.get("subject") != email["subject"]
                or sha256_text(str(envelope.get("subject"))) != email["subject_sha256"]
            ):
                raise GmailRestError("gmail_rest_envelope_changed")
            mime_path = require_owner_file(
                root
                / policy.storage_name
                / "input"
                / f"{email['ordinal']:02d}-message.eml"
            )
            raw = mime_path.read_bytes()
            if sha256_bytes(raw) != email["mime_sha256"]:
                raise GmailRestError("gmail_rest_mime_changed")
            strict_id = verify_mime_with_actual_message_id(
                raw,
                recipient=recipient,
                subject=envelope["subject"],
                plain=envelope["text"],
                html=envelope["html"],
            )
            if strict_id != email["requested_message_id"]:
                raise GmailRestError("gmail_rest_mime_changed")
            storage_root = private_directory(root / policy.storage_name)
            actions_root = private_directory(storage_root / "actions")
            intent_root = private_directory(actions_root / str(action_id))
            intent_path = intent_root / "intent.json"
            if intent_path.exists():
                intent = read_owner_json(intent_path)
                validate_schema(intent, policy.intent_schema)
            else:
                now = utc_now()
                intent = {
                    "schema_version": policy.intent_schema,
                    "batch_id": policy.batch_id,
                    "action_id": action_id,
                    "ordinal": email["ordinal"],
                    "requested_message_id": email["requested_message_id"],
                    "actual_message_id": None,
                    "gmail_message_id": None,
                    "mime_sha256": email["mime_sha256"],
                    "request_sha256": email["request_sha256"],
                    "send_started": False,
                    "provider_calls": 0,
                    "send_calls": 0,
                    "created_at_utc": now,
                    "updated_at_utc": now,
                }
                validate_schema(intent, policy.intent_schema)
                atomic_json(intent_path, intent)
            if (
                intent["action_id"] != action_id
                or intent["ordinal"] != email["ordinal"]
                or intent["requested_message_id"] != email["requested_message_id"]
                or intent["mime_sha256"] != email["mime_sha256"]
                or intent["request_sha256"] != email["request_sha256"]
            ):
                raise GmailRestError("gmail_rest_intent_invalid")
            client = GmailRestClient(
                token_file=token_file,
                candidate_root=root,
                marker=marker,
                marker_name=policy.marker_name,
                max_provider_calls=policy.provider_budget,
                max_send_calls=policy.send_budget,
                session_factory=session_factory,
            )
            if action["status"] == "prepared":
                connection.execute(
                    "UPDATE external_actions SET status='in_progress',started_at_utc=? WHERE id=?",
                    (utc_now(), action_id),
                )
                connection.commit()
            gmail_id: str | None = intent["gmail_message_id"]
            reused = False
            if not intent["send_started"]:
                matches = client.list_message(
                    email["requested_message_id"],
                    action_id=action_id,
                    kind=f"initial-query-{policy.logical_prefix.split(':')[1]}",
                    retry_empty=False,
                    phase="lookup",
                )
                if len(matches) > 1:
                    raise GmailRestError("gmail_rest_message_id_ambiguous")
                if matches:
                    gmail_id = matches[0]
                    reused = True
                else:
                    intent["send_started"] = True
                    intent["send_calls"] = 1
                    intent["updated_at_utc"] = utc_now()
                    validate_schema(intent, policy.intent_schema)
                    atomic_json(intent_path, intent)
                    connection.execute(
                        "UPDATE external_actions SET attempt_count=1 WHERE id=?",
                        (action_id,),
                    )
                    connection.commit()
                    gmail_id = client.send(raw, action_id=action_id)
                    intent["gmail_message_id"] = gmail_id
                    intent["updated_at_utc"] = utc_now()
                    atomic_json(intent_path, intent)
            elif gmail_id is None:
                connection.execute(
                    "UPDATE external_actions SET status='unknown',last_reconciled_at_utc=?,"
                    "error_code=?,error_summary=? WHERE id=?",
                    (
                        utc_now(),
                        "gmail_rest_send_unconfirmed",
                        "send_started_without_gmail_message_id",
                        action_id,
                    ),
                )
                connection.commit()
                raise GmailRestError("gmail_rest_send_unconfirmed")
            gmail_id = require_gmail_message_id(gmail_id)
            actual = client.get_raw(gmail_id, action_id=action_id)
            actual_message_id = verify_mime_with_actual_message_id(
                actual,
                recipient=recipient,
                subject=envelope["subject"],
                plain=envelope["text"],
                html=envelope["html"],
            )
            intent["gmail_message_id"] = gmail_id
            intent["actual_message_id"] = actual_message_id
            intent["updated_at_utc"] = utc_now()
            atomic_json(intent_path, intent)
            confirmation = client.list_message(
                actual_message_id,
                action_id=action_id,
                kind=f"confirmation-query-{policy.logical_prefix.split(':')[1]}",
                retry_empty=True,
                phase="confirmation",
            )
            if confirmation != [gmail_id]:
                raise GmailRestError("gmail_rest_confirmation_invalid")
            storage_root = private_directory(root / policy.storage_name)
            eml_root = private_directory(storage_root / "eml")
            eml_path = eml_root / f"{email['ordinal']:02d}-{gmail_id}.eml"
            if eml_path.exists():
                if sha256_file(require_owner_file(eml_path)) != sha256_bytes(actual):
                    raise GmailRestError("gmail_rest_eml_conflict")
            else:
                atomic_write(eml_path, actual)
            marker = client.marker
            intent["provider_calls"] = int(marker["action_api_calls"][str(action_id)])
            intent["updated_at_utc"] = utc_now()
            validate_schema(intent, policy.intent_schema)
            atomic_json(intent_path, intent)
            return _finalize_success(
                connection,
                candidate_root=root,
                marker=marker,
                action=action,
                email=email,
                gmail_id=gmail_id,
                actual_message_id=actual_message_id,
                eml_path=eml_path,
                reused=reused,
                policy=policy,
            )
        except GmailRestError as exc:
            row = connection.execute(
                "SELECT status FROM external_actions WHERE id=?", (action_id,)
            ).fetchone()
            if row is not None and row[0] in {"in_progress", "unknown"}:
                intent_path = (
                    root
                    / policy.storage_name
                    / "actions"
                    / str(action_id)
                    / "intent.json"
                )
                send_started = bool(
                    intent_path.exists()
                    and read_owner_json(intent_path).get("send_started") is True
                )
                connection.execute(
                    "UPDATE external_actions SET status=?,finished_at_utc=?,"
                    "last_reconciled_at_utc=?,error_code=?,error_summary=? WHERE id=?",
                    (
                        "unknown" if send_started else "failed_safe",
                        None if send_started else utc_now(),
                        utc_now(),
                        str(exc),
                        f"gmail_rest_{policy.logical_prefix.split(':')[1]}_delivery_stopped",
                        action_id,
                    ),
                )
                connection.commit()
            raise
        finally:
            connection.close()


def deliver_remaining(
    *,
    candidate_root: Path,
    token_file: Path,
    session_factory: Any | None = None,
    policy: ContinuationPolicy = R07_POLICY,
) -> dict[str, Any]:
    marker = _load_marker(candidate_root, policy)
    if policy.canary_ordinal is not None and marker["canary_confirmed"] is not True:
        raise GmailRestError("gmail_rest_canary_user_confirmation_required")
    results: list[dict[str, Any]] = []
    start = 1 if policy.canary_ordinal is not None else 0
    for action_id in marker["action_ids"][start:]:
        results.append(
            deliver_action(
                candidate_root=candidate_root,
                token_file=token_file,
                action_id=int(action_id),
                session_factory=session_factory,
                policy=policy,
            )
        )
    return {"status": "succeeded", "delivered": len(results)}


def _r08_prior_results(
    connection: sqlite3.Connection,
    *,
    candidate_root: Path,
    parent_marker: dict[str, Any],
) -> list[dict[str, Any]]:
    """Bind all eight immutable r06/r07 successes before authorizing a resend."""

    canary = parent_marker.get("completed_canary")
    if not isinstance(canary, dict):
        raise GmailRestError("gmail_rest_r08_parent_results_invalid")
    identities = [(1, int(canary["action_id"]))] + [
        (ordinal, int(action_id))
        for ordinal, action_id in zip(
            range(2, 9), parent_marker.get("action_ids", []), strict=True
        )
    ]
    if len(identities) != 8:
        raise GmailRestError("gmail_rest_r08_parent_results_invalid")
    results: list[dict[str, Any]] = []
    for ordinal, action_id in identities:
        logical_key = (
            "m10:r07:gmail-result:canary"
            if ordinal == 1
            else f"m10:r07:gmail-result:{action_id}"
        )
        row = connection.execute(
            "SELECT id,content_json,content_sha256 FROM skill_outputs "
            "WHERE logical_key=? AND schema_name='m10_gmail_rest_result_v2'",
            (logical_key,),
        ).fetchone()
        action = connection.execute(
            "SELECT status,result_external_id,provider_marker FROM external_actions WHERE id=?",
            (action_id,),
        ).fetchone()
        if (
            row is None
            or action is None
            or action[0] not in {"succeeded", "already_done"}
        ):
            raise GmailRestError("gmail_rest_r08_parent_results_invalid")
        result = json.loads(str(row[1]))
        validate_schema(result, "m10_gmail_rest_result_v2")
        eml = require_owner_file(candidate_root / str(result["eml_relative_path"]))
        if (
            result["ordinal"] != ordinal
            or result["action_id"] != action_id
            or result["gmail_message_id"] != action[1]
            or result["actual_message_id"] != action[2]
            or result["eml_sha256"] != sha256_file(eml)
        ):
            raise GmailRestError("gmail_rest_r08_parent_results_invalid")
        results.append(
            {
                "ordinal": ordinal,
                "action_id": action_id,
                "result_output_id": int(row[0]),
                "result_output_sha256": str(row[2]),
                "requested_message_id": result["requested_message_id"],
                "actual_message_id": result["actual_message_id"],
                "gmail_message_id": result["gmail_message_id"],
                "eml_sha256": result["eml_sha256"],
            }
        )
    if (
        [item["ordinal"] for item in results] != list(range(1, 9))
        or len({item["gmail_message_id"] for item in results}) != 8
        or len({item["actual_message_id"] for item in results}) != 8
        or len({item["requested_message_id"] for item in results}) != 8
    ):
        raise GmailRestError("gmail_rest_r08_parent_results_invalid")
    return results


def _r08_source_items(
    connection: sqlite3.Connection,
    *,
    candidate_root: Path,
    parent_marker: dict[str, Any],
    parent_preview: dict[str, Any],
) -> list[dict[str, Any]]:
    r06_marker = read_owner_json(candidate_root / PARENT_MARKER_NAME)
    r06_preview_row = connection.execute(
        "SELECT content_json,content_sha256 FROM skill_outputs WHERE id=?",
        (int(r06_marker["preview_output_id"]),),
    ).fetchone()
    if (
        r06_preview_row is None
        or str(r06_preview_row[1]) != r06_marker["preview_output_sha256"]
    ):
        raise GmailRestError("gmail_rest_r08_parent_preview_invalid")
    r06_preview = json.loads(str(r06_preview_row[0]))
    validate_schema(r06_preview, "m10_gmail_rest_preview_v1")
    validate_schema(parent_preview, "m10_gmail_rest_preview_v2")
    items = [r06_preview["emails"][0], *parent_preview["emails"]]
    if [int(item["ordinal"]) for item in items] != list(range(1, 9)):
        raise GmailRestError("gmail_rest_r08_parent_preview_invalid")
    return items


def _build_r08_preview_and_actions(
    connection: sqlite3.Connection,
    *,
    candidate_root: Path,
    parent_marker_sha: str,
    parent_database_sha: str,
    parent_marker: dict[str, Any],
    parent_preview: dict[str, Any],
    prior_results: list[dict[str, Any]],
) -> tuple[int, str, dict[str, Any], list[int]]:
    policy = R08_POLICY
    recipient, recipient_sha = read_recipient(SOURCE_ROOT / "email.json")
    source_items = _r08_source_items(
        connection,
        candidate_root=candidate_root,
        parent_marker=parent_marker,
        parent_preview=parent_preview,
    )
    emails: list[dict[str, Any]] = []
    old_requested = {item["requested_message_id"] for item in prior_results}
    for ordinal, old_item in enumerate(source_items, start=1):
        output_id, output_sha, envelope, envelope_path = _retitle_email_render(
            connection,
            ordinal=ordinal,
            old_item=old_item,
            candidate_root=candidate_root,
            policy=policy,
        )
        period_end = f"2026-08-{ordinal + 11:02d}" if ordinal < 8 else "2026-08-18"
        date_value = datetime.combine(
            date.fromisoformat(period_end),
            datetime_time(hour=12),
            ZoneInfo("Asia/Hong_Kong"),
        )
        raw, requested_id, mime_sha = deterministic_mime(
            recipient=recipient,
            subject=str(envelope["subject"]),
            plain=str(envelope["text"]),
            html=str(envelope["html"]),
            source_sha256=output_sha,
            date_value=date_value,
        )
        if requested_id in old_requested:
            raise GmailRestError("gmail_rest_r08_message_id_reused")
        mime_path = (
            candidate_root
            / policy.storage_name
            / "input"
            / f"{ordinal:02d}-message.eml"
        )
        atomic_write(mime_path, raw)
        email = {
            "ordinal": ordinal,
            "prior_source_output_id": int(old_item["source_output_id"]),
            "prior_source_output_sha256": str(old_item["source_output_sha256"]),
            "source_output_id": output_id,
            "source_output_sha256": output_sha,
            "envelope_relative_path": str(envelope_path.relative_to(candidate_root)),
            "envelope_sha256": sha256_file(envelope_path),
            "recipient_sha256": recipient_sha,
            "subject": policy.subjects[ordinal],
            "subject_sha256": sha256_text(policy.subjects[ordinal]),
            "requested_message_id": requested_id,
            "mime_sha256": mime_sha,
        }
        email["request_sha256"] = sha256_text(
            canonical_json(_email_request(email, policy))
        )
        emails.append(email)
    if (
        [item["ordinal"] for item in emails] != list(policy.ordinals)
        or len({item["requested_message_id"] for item in emails}) != 8
        or len({item["source_output_id"] for item in emails}) != 8
    ):
        raise GmailRestError("gmail_rest_r08_email_set_invalid")
    unsigned = {
        "schema_version": policy.preview_schema,
        "batch_id": policy.batch_id,
        "transport": "gmail_rest",
        "parent_marker_sha256": parent_marker_sha,
        "parent_database_sha256": parent_database_sha,
        "parent_preview_output_id": int(parent_marker["preview_output_id"]),
        "parent_preview_output_sha256": str(parent_marker["preview_output_sha256"]),
        "prior_results": prior_results,
        "emails": emails,
        "prior_api_calls": policy.prior_api_calls,
        "prior_send_calls": policy.prior_send_calls,
        "gmail_api_budget": policy.delivery_api_budget,
        "gmail_send_budget": policy.send_budget,
        "provider_budget": policy.provider_budget,
    }
    preview = {**unsigned, "preview_sha256": sha256_text(canonical_json(unsigned))}
    validate_schema(preview, policy.preview_schema)
    digest = sha256_text(canonical_json(preview))
    run_id = begin_run(
        connection,
        run_key=f"m10-r08-preview:{digest}:attempt-1",
        workflow_key=policy.workflow_key,
        dedupe_key=digest,
        skill_name="gmail-sender",
        operation="send_email",
        trigger_kind="manual",
        input_manifest={
            "m10_role": "m10_r08_gmail_rest_prepare",
            "batch_id": policy.batch_id,
        },
    )
    preview_id = append_output(
        connection,
        skill_run_id=run_id,
        output_kind="execution_summary",
        logical_key="m10:r08:gmail-rest-preview",
        schema_name=policy.preview_schema,
        schema_version="3",
        title_text="M10 r08 corrected-subject Gmail REST preview",
        content_json=preview,
        content_text=canonical_json(preview),
        lineage=[
            {
                "output_id": int(parent_marker["preview_output_id"]),
                "output_sha256": str(parent_marker["preview_output_sha256"]),
            },
            *[
                {
                    "output_id": int(item["result_output_id"]),
                    "output_sha256": str(item["result_output_sha256"]),
                }
                for item in prior_results
            ],
        ],
    )
    finish_run(connection, run_id, status="succeeded")
    preview_sha = str(
        connection.execute(
            "SELECT content_sha256 FROM skill_outputs WHERE id=?", (preview_id,)
        ).fetchone()[0]
    )
    action_ids: list[int] = []
    for email in emails:
        scope_text = canonical_json(_approval_scope(email, policy))
        approval_id = require_lastrowid(
            connection.execute(
                """INSERT INTO approvals
                (approval_key,candidate_output_id,candidate_output_sha256,authority_kind,
                 decision,scope_kind,scope_json,scope_sha256,source_ref,reason_code,
                 decided_at_utc,valid_from_utc,valid_until_utc)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    sha256_text(
                        canonical_json(
                            {"batch": policy.batch_id, "ordinal": email["ordinal"]}
                        )
                    ),
                    preview_id,
                    preview_sha,
                    "user_explicit",
                    "approved",
                    "gmail",
                    scope_text,
                    sha256_text(scope_text),
                    f"m10-r08-preview:{preview['preview_sha256']}",
                    "m10_r08_corrected_subject_resend_approved",
                    utc_now(),
                    utc_now(),
                    None,
                ),
            )
        )
        request = _email_request(email, policy)
        request_text = canonical_json(request)
        action_ids.append(
            require_lastrowid(
                connection.execute(
                    """INSERT INTO external_actions
                    (idempotency_key,skill_run_id,provider,entity_kind,action_kind,
                     source_output_id,source_output_sha256,approval_id,target_key,
                     request_json,request_sha256,status,attempt_count,prepared_at_utc)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        sha256_text(
                            canonical_json(
                                {"batch": policy.batch_id, "request": request}
                            )
                        ),
                        run_id,
                        "gmail",
                        "email",
                        "gmail_send",
                        preview_id,
                        preview_sha,
                        approval_id,
                        _action_target(email, policy),
                        request_text,
                        sha256_text(request_text),
                        "prepared",
                        0,
                        utc_now(),
                    ),
                )
            )
        )
    connection.commit()
    return preview_id, preview_sha, preview, action_ids


def create_r08_continuation(
    *, parent_root: Path, candidate_root: Path
) -> dict[str, Any]:
    parent_root = require_owner_directory(parent_root)
    parent_candidate = require_owner_directory(parent_root / "candidate")
    parent_marker_path = require_owner_file(parent_candidate / MARKER_NAME)
    parent_database = require_owner_file(parent_candidate / "source/state/trainlab.db")
    parent_marker_sha = sha256_file(parent_marker_path)
    parent_database_sha = sha256_file(parent_database)
    if (
        parent_marker_sha != R08_PARENT_MARKER_SHA256
        or parent_database_sha != R08_PARENT_DATABASE_SHA256
        or _tree_sha256(parent_candidate) != R08_PARENT_TREE_SHA256
    ):
        raise GmailRestError("gmail_rest_parent_r07_changed")
    parent_marker = read_owner_json(parent_marker_path)
    if (
        parent_marker.get("api_calls") != 32
        or parent_marker.get("send_calls") != 8
        or parent_marker.get("canary_confirmed") is not True
    ):
        raise GmailRestError("gmail_rest_parent_r07_incomplete")
    candidate_root = Path(os.path.abspath(candidate_root))
    if candidate_root.exists() or candidate_root.is_relative_to(SOURCE_ROOT.parent):
        raise GmailRestError("gmail_rest_candidate_scope_invalid")
    candidate_root.mkdir(mode=0o700)
    new_candidate = candidate_root / "candidate"
    with workflow_lock(parent_database):
        _clone_candidate_tree(parent_candidate, new_candidate)
        new_database = new_candidate / "source/state/trainlab.db"
        _backup_database(parent_database, new_database)
        if sha256_file(parent_database) != parent_database_sha:
            raise GmailRestError("gmail_rest_parent_changed_during_clone")
    descriptor = os.open(
        new_candidate / "source/state/trainlab.lock",
        os.O_CREAT | os.O_EXCL | os.O_RDWR,
        0o600,
    )
    os.close(descriptor)
    for relative in RUNTIME_FILES:
        atomic_write(
            new_candidate / "source" / relative,
            (RUNTIME_SOURCE_ROOT / relative).read_bytes(),
        )
    if _tree_sha256(parent_candidate) != R08_PARENT_TREE_SHA256:
        raise GmailRestError("gmail_rest_parent_changed_during_clone")
    connection = connect(new_database)
    try:
        preview_row = connection.execute(
            "SELECT content_json,content_sha256 FROM skill_outputs WHERE id=?",
            (int(parent_marker["preview_output_id"]),),
        ).fetchone()
        if (
            preview_row is None
            or str(preview_row[1]) != parent_marker["preview_output_sha256"]
        ):
            raise GmailRestError("gmail_rest_parent_preview_invalid")
        parent_preview = json.loads(str(preview_row[0]))
        prior_results = _r08_prior_results(
            connection,
            candidate_root=new_candidate,
            parent_marker=parent_marker,
        )
        preview_id, preview_sha, _preview, action_ids = _build_r08_preview_and_actions(
            connection,
            candidate_root=new_candidate,
            parent_marker_sha=parent_marker_sha,
            parent_database_sha=parent_database_sha,
            parent_marker=parent_marker,
            parent_preview=parent_preview,
            prior_results=prior_results,
        )
    finally:
        connection.close()
    marker = {
        "schema_version": R08_POLICY.schema_version,
        "batch_id": R08_POLICY.batch_id,
        "candidate_source": str(new_candidate / "source"),
        "database": str(new_database),
        "parent_r07_root": str(parent_root),
        "parent_marker_sha256": parent_marker_sha,
        "parent_database_sha256": parent_database_sha,
        "runtime_sha256": _runtime_sha256(),
        "preview_output_id": preview_id,
        "preview_output_sha256": preview_sha,
        "prior_results": prior_results,
        "action_ids": action_ids,
        "action_api_calls": {str(action_id): 0 for action_id in action_ids},
        "action_phase_calls": {
            str(action_id): {phase: 0 for phase in READ_PHASES}
            for action_id in action_ids
        },
        "action_send_calls": {str(action_id): 0 for action_id in action_ids},
        "auth_receipt_sha256": parent_marker["auth_receipt_sha256"],
        "auth_provider_calls": AUTH_API_CALLS,
        "canary_confirmed": False,
        "api_calls": R08_POLICY.prior_api_calls,
        "send_calls": R08_POLICY.prior_send_calls,
        "created_at_utc": utc_now(),
    }
    atomic_json(new_candidate / R08_POLICY.marker_name, marker)
    return {"status": "succeeded", "candidate_root": str(new_candidate), "actions": 8}


def deliver_r08_canary(
    *, candidate_root: Path, token_file: Path, session_factory: Any | None = None
) -> dict[str, Any]:
    marker = _load_marker(candidate_root, R08_POLICY)
    action_id = int(marker["action_ids"][0])
    return deliver_action(
        candidate_root=candidate_root,
        token_file=token_file,
        action_id=action_id,
        session_factory=session_factory,
        policy=R08_POLICY,
    )


def confirm_r08_canary(*, candidate_root: Path, user_confirmed: bool) -> dict[str, Any]:
    if not user_confirmed:
        raise GmailRestError("gmail_rest_canary_user_confirmation_required")
    root = require_owner_directory(candidate_root)
    marker = _load_marker(root, R08_POLICY)
    action_id = int(marker["action_ids"][0])
    database = require_owner_file(Path(marker["database"]))
    connection = connect(database, read_only=True, immutable=True)
    try:
        email, action = _preview_and_action(connection, marker, action_id, R08_POLICY)
        recipient, _recipient_sha = read_recipient(SOURCE_ROOT / "email.json")
        result = _existing_result(
            connection,
            candidate_root=root,
            action=action,
            email=email,
            recipient=recipient,
            policy=R08_POLICY,
        )
        if action["status"] not in {"succeeded", "already_done"} or result is None:
            raise GmailRestError("gmail_rest_canary_not_verified")
    finally:
        connection.close()
    if marker["canary_confirmed"] is not True:
        atomic_json(
            root / R08_POLICY.storage_name / "canary-user-confirmation.json",
            {
                "schema_version": "m10_r08_canary_confirmation_v1",
                "action_id": action_id,
                "user_confirmed": True,
                "confirmed_at_utc": utc_now(),
            },
        )
        marker["canary_confirmed"] = True
        atomic_json(root / R08_POLICY.marker_name, marker)
    return {"status": "succeeded", "canary_confirmed": True, "provider_calls": 0}


def verify_continuation(candidate_root: Path) -> dict[str, Any]:
    root = require_owner_directory(candidate_root)
    marker = _load_marker(root)
    database = require_owner_file(Path(marker["database"]))
    connection = connect(database, read_only=True, immutable=True)
    try:
        preview_row = connection.execute(
            "SELECT content_json FROM skill_outputs WHERE id=? AND content_sha256=?",
            (marker["preview_output_id"], marker["preview_output_sha256"]),
        ).fetchone()
        if preview_row is None:
            raise GmailRestError("gmail_rest_preview_missing")
        preview = json.loads(str(preview_row[0]))
        validate_schema(preview, "m10_gmail_rest_preview_v2")
        prior_action_ids = [
            int(value)
            for value in read_owner_json(root / PARENT_MARKER_NAME)["action_ids"][1:]
        ]
        old_actions = connection.execute(
            f"SELECT status,COUNT(*) FROM external_actions WHERE id IN "
            f"({','.join('?' for _ in prior_action_ids)}) GROUP BY status",
            prior_action_ids,
        ).fetchall()
        current = connection.execute(
            f"SELECT status,COUNT(*) FROM external_actions WHERE id IN ({','.join('?' for _ in marker['action_ids'])}) GROUP BY status",
            marker["action_ids"],
        ).fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    finally:
        connection.close()
    return {
        "status": "succeeded",
        "integrity": integrity,
        "foreign_key_errors": foreign_keys,
        "completed_canary": 1,
        "old_actions": {str(status): count for status, count in old_actions},
        "current_actions": {str(status): count for status, count in current},
        "api_calls": marker["api_calls"],
        "send_calls": marker["send_calls"],
    }


def verify_r08(candidate_root: Path) -> dict[str, Any]:
    root = require_owner_directory(candidate_root)
    marker = _load_marker(root, R08_POLICY)
    database = require_owner_file(Path(marker["database"]))
    connection = connect(database, read_only=True, immutable=True)
    try:
        preview_row = connection.execute(
            "SELECT content_json FROM skill_outputs WHERE id=? AND content_sha256=?",
            (marker["preview_output_id"], marker["preview_output_sha256"]),
        ).fetchone()
        if preview_row is None:
            raise GmailRestError("gmail_rest_preview_missing")
        preview = json.loads(str(preview_row[0]))
        validate_schema(preview, R08_POLICY.preview_schema)
        current = connection.execute(
            f"SELECT status,COUNT(*) FROM external_actions WHERE id IN "
            f"({','.join('?' for _ in marker['action_ids'])}) GROUP BY status",
            marker["action_ids"],
        ).fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        result_count = connection.execute(
            "SELECT COUNT(*) FROM skill_outputs WHERE schema_name=?",
            (R08_POLICY.result_schema,),
        ).fetchone()[0]
    finally:
        connection.close()
    return {
        "status": "succeeded",
        "integrity": integrity,
        "foreign_key_errors": foreign_keys,
        "prior_results": len(marker["prior_results"]),
        "current_actions": {str(status): count for status, count in current},
        "current_results": result_count,
        "canary_confirmed": marker["canary_confirmed"],
        "api_calls": marker["api_calls"],
        "send_calls": marker["send_calls"],
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build-continuation")
    build.add_argument("--parent-root", type=Path, default=PARENT_R06_ROOT)
    build.add_argument("--candidate-root", type=Path, required=True)
    build.add_argument("--confirm-canary-received", action="store_true")
    deliver = commands.add_parser("deliver-remaining")
    deliver.add_argument("--candidate-root", type=Path, required=True)
    deliver.add_argument(
        "--token-file", type=Path, default=SOURCE_ROOT / "gmail-api-token.json"
    )
    verify = commands.add_parser("verify")
    verify.add_argument("--candidate-root", type=Path, required=True)
    build_r08 = commands.add_parser("build-r08")
    build_r08.add_argument("--parent-root", type=Path, default=R08_PARENT_ROOT)
    build_r08.add_argument("--candidate-root", type=Path, required=True)
    canary_r08 = commands.add_parser("deliver-r08-canary")
    canary_r08.add_argument("--candidate-root", type=Path, required=True)
    canary_r08.add_argument(
        "--token-file", type=Path, default=SOURCE_ROOT / "gmail-api-token.json"
    )
    confirm_r08 = commands.add_parser("confirm-r08-canary")
    confirm_r08.add_argument("--candidate-root", type=Path, required=True)
    confirm_r08.add_argument("--user-confirmed", action="store_true")
    remaining_r08 = commands.add_parser("deliver-r08-remaining")
    remaining_r08.add_argument("--candidate-root", type=Path, required=True)
    remaining_r08.add_argument(
        "--token-file", type=Path, default=SOURCE_ROOT / "gmail-api-token.json"
    )
    verify_r08_parser = commands.add_parser("verify-r08")
    verify_r08_parser.add_argument("--candidate-root", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "build-continuation":
            value = create_continuation(
                parent_root=args.parent_root,
                candidate_root=args.candidate_root,
                confirm_canary_received=args.confirm_canary_received,
            )
        elif args.command == "deliver-remaining":
            value = deliver_remaining(
                candidate_root=args.candidate_root,
                token_file=args.token_file,
            )
        elif args.command == "verify":
            value = verify_continuation(args.candidate_root)
        elif args.command == "build-r08":
            value = create_r08_continuation(
                parent_root=args.parent_root,
                candidate_root=args.candidate_root,
            )
        elif args.command == "deliver-r08-canary":
            value = deliver_r08_canary(
                candidate_root=args.candidate_root,
                token_file=args.token_file,
            )
        elif args.command == "confirm-r08-canary":
            value = confirm_r08_canary(
                candidate_root=args.candidate_root,
                user_confirmed=args.user_confirmed,
            )
        elif args.command == "deliver-r08-remaining":
            value = deliver_remaining(
                candidate_root=args.candidate_root,
                token_file=args.token_file,
                policy=R08_POLICY,
            )
        else:
            value = verify_r08(args.candidate_root)
        print(json.dumps(value, ensure_ascii=False, sort_keys=True))
        return 0
    except (GmailRestError, OSError, sqlite3.Error, ValueError) as exc:
        print(json.dumps({"status": "blocked", "error_code": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
