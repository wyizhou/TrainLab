#!/usr/bin/env python3
"""Prepare and ledger the explicitly confirmed M10 Gmail/Garmin lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from skills._shared.m10_plan_contract import (
    M10PlanError,
    garmin_action_requests,
)
from skills._shared.m10_plan_contract import normalize_plan as _normalize_plan
from skills._shared.scripts.schema_validation import validate_payload
from skills._shared.state import (
    append_output,
    begin_run,
    canonical_json,
    connect,
    finish_run,
    require_lastrowid,
    sha256_file,
    sha256_text,
    utc_now,
)

TEST_TAG = "E2E-20260818"
PLAN_START = "2026-08-19"
PLAN_END = "2026-08-25"
GMAIL_MCP_CALL_BUDGET = 26
GARMIN_MCP_CALL_BUDGET = 20
EMAIL_CONFIG_SCHEMA_VERSION = "trainlab_email_recipient_v1"
EMAIL_CONFIG_MAX_BYTES = 1_024
MCP_TOOL_ALLOWLIST = {
    "gmail": {"send_email", "search_emails"},
    "garmin": {
        "get_workouts",
        "get_workout_by_id",
        "get_scheduled_workouts",
        "upload_workout",
        "upload_workouts",
        "schedule_workout",
        "schedule_workouts",
        "unschedule_workout",
        "unschedule_workouts",
        "delete_workout",
        "delete_workouts",
    },
}
MCP_WRITE_ACTION_KIND = {
    "gmail": {"send_email": "gmail_send"},
    "garmin": {
        "upload_workout": "garmin_workout_create",
        "upload_workouts": "garmin_workout_create",
        "schedule_workout": "garmin_calendar_schedule",
        "schedule_workouts": "garmin_calendar_schedule",
        "unschedule_workout": "garmin_calendar_unschedule",
        "unschedule_workouts": "garmin_calendar_unschedule",
        "delete_workout": "garmin_workout_delete",
        "delete_workouts": "garmin_workout_delete",
    },
}


class ExternalActionError(RuntimeError):
    """Stable M10 prewrite/action-ledger failure."""


def load_email_recipient(path: Path) -> tuple[str, str]:
    """Read one owner-only self-delivery address without following links."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or not 1 <= metadata.st_size <= EMAIL_CONFIG_MAX_BYTES
        ):
            raise ExternalActionError("m10_email_config_invalid")
        payload_bytes = os.read(descriptor, EMAIL_CONFIG_MAX_BYTES + 1)
    except (OSError, ValueError) as exc:
        raise ExternalActionError("m10_email_config_invalid") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not payload_bytes or len(payload_bytes) > EMAIL_CONFIG_MAX_BYTES:
        raise ExternalActionError("m10_email_config_invalid")
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalActionError("m10_email_config_invalid") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "email"}:
        raise ExternalActionError("m10_email_config_invalid")
    email = payload.get("email")
    local = r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
    label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    if (
        payload.get("schema_version") != EMAIL_CONFIG_SCHEMA_VERSION
        or not isinstance(email, str)
        or email != email.strip()
        or len(email) > 254
        or re.fullmatch(rf"{local}@{label}(?:\.{label})+", email) is None
    ):
        raise ExternalActionError("m10_email_config_invalid")
    return email, sha256_text(email)


def parse_garmin_workout_lookup(
    payload_text: str,
    *,
    expected_workout_id: str,
    expected_name: str,
) -> dict[str, Any]:
    """Normalize one bounded get_workout_by_id result without guessing identity."""

    if (
        not isinstance(payload_text, str)
        or not payload_text.strip()
        or len(payload_text.encode("utf-8")) > 1_000_000
        or "\x00" in payload_text
        or not isinstance(expected_workout_id, str)
        or not expected_workout_id
        or not isinstance(expected_name, str)
        or not expected_name.endswith(f"-{TEST_TAG}-GTS")
    ):
        raise ExternalActionError("m10_garmin_lookup_result_invalid")
    stripped = payload_text.strip()
    if stripped.startswith("Error retrieving workout:"):
        status_codes = re.findall(r"(?<!\d)([1-5]\d{2})(?!\d)", stripped)
        if (
            status_codes
            and set(status_codes) == {"404"}
            and stripped.count("NotFoundException") == 1
        ):
            return {
                "exists": False,
                "not_found": True,
                "workout_id": expected_workout_id,
                "name": expected_name,
            }
        raise ExternalActionError("m10_garmin_lookup_result_invalid")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ExternalActionError("m10_garmin_lookup_result_invalid") from exc
    if not isinstance(payload, dict):
        raise ExternalActionError("m10_garmin_lookup_result_invalid")
    workout_id = payload.get("id")
    name = payload.get("name")
    valid_workout_id = (
        isinstance(workout_id, int)
        and not isinstance(workout_id, bool)
        and workout_id > 0
    ) or (isinstance(workout_id, str) and bool(workout_id.strip()))
    if not valid_workout_id or not isinstance(name, str) or not name:
        raise ExternalActionError("m10_garmin_lookup_result_invalid")
    if str(workout_id) != expected_workout_id or name != expected_name:
        raise ExternalActionError("m10_garmin_lookup_identity_mismatch")
    return {
        "exists": True,
        "not_found": False,
        "workout_id": expected_workout_id,
        "name": expected_name,
    }


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ExternalActionError("m10_candidate_scope_required")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _assert_candidate_database(database: Path) -> Path:
    absolute = Path(os.path.abspath(database))
    source_root = absolute.parent.parent
    rolling = _load_module(
        "trainlab_m10_external_candidate_guard",
        Path(__file__).resolve().parents[2]
        / "garmin-sync/scripts/rolling_week_sync.py",
    )
    try:
        _root, verified = rolling._assert_candidate_for_reuse(source_root, absolute)
    except Exception as exc:
        raise ExternalActionError("m10_candidate_scope_required") from exc
    return Path(verified)


def _atomic_write(path: Path, payload: bytes) -> None:
    if not payload:
        raise ExternalActionError("m10_preview_empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
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
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def normalize_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        return _normalize_plan(plan)
    except M10PlanError as exc:
        raise ExternalActionError(str(exc)) from exc


def _bind_schedule_requests(schedule: list[dict[str, Any]]) -> None:
    for row in schedule:
        requests = garmin_action_requests(row)
        row["action_request_sha256"] = {
            phase: sha256_text(canonical_json(request))
            for phase, request in requests.items()
        }


def build_preview(database: Path, run_root: Path, email_config: Path) -> dict[str, Any]:
    database = _assert_candidate_database(database)
    recipient, recipient_sha256 = load_email_recipient(email_config)
    manifest_path = run_root / "prewrite-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExternalActionError("m10_prewrite_manifest_missing") from exc
    reports = manifest.get("reports")
    if not isinstance(reports, list) or len(reports) != 8:
        raise ExternalActionError("m10_email_batch_invalid")
    expected_reports = [("daily", f"2026-08-{day:02d}") for day in range(12, 19)] + [
        ("weekly", "2026-08-18")
    ]
    observed_reports = [
        (str(item.get("mode", "")), str(item.get("target", "")))
        for item in reports
        if isinstance(item, dict)
    ]
    if observed_reports != expected_reports:
        raise ExternalActionError("m10_email_batch_invalid")
    emails: list[dict[str, Any]] = []
    report_sources: list[dict[str, Any]] = []
    source_output_ids: set[int] = set()
    email_output_ids: set[int] = set()
    weekly_run_id: int | None = None
    connection = connect(database, read_only=True, immutable=True)
    for report in reports:
        if not isinstance(report, dict):
            raise ExternalActionError("m10_email_batch_invalid")
        path = Path(str(report.get("email_envelope", "")))
        if not path.is_file() or path.is_symlink() or not path.is_relative_to(run_root):
            raise ExternalActionError("m10_email_envelope_invalid")
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("subject") != report.get("subject"):
            raise ExternalActionError("m10_email_envelope_invalid")
        row = connection.execute(
            "SELECT output.content_sha256,output.title_text,output.content_text,"
            "output.content_html FROM skill_outputs output "
            "JOIN skill_runs run ON run.id=output.skill_run_id "
            "WHERE output.id=? AND output.output_kind='email_render' "
            "AND run.status='succeeded' AND run.skill_name='training-report-publisher'",
            (int(value.get("report_output_id", 0)),),
        ).fetchone()
        if (
            row is None
            or str(row[0]) != str(value.get("report_output_sha256"))
            or str(row[1]) != str(value.get("subject"))
            or str(row[2]) != str(value.get("text"))
            or str(row[3]) != str(value.get("html"))
        ):
            connection.close()
            raise ExternalActionError("m10_email_envelope_invalid")
        source_row = connection.execute(
            "SELECT output.content_sha256,output.schema_name,"
            "output.period_start_date,output.period_end_date,output.content_json,"
            "output.lineage_json,output.skill_run_id,run.status,run.operation "
            "FROM skill_outputs output JOIN skill_runs run ON run.id=output.skill_run_id "
            "WHERE output.id=? AND run.skill_name='training-coach'",
            (int(value.get("source_output_id", 0)),),
        ).fetchone()
        expected_schema = (
            "daily_ai_result_v1"
            if report.get("mode") == "daily"
            else "weekly_ai_result_v1"
        )
        if (
            source_row is None
            or str(source_row[0]) != str(value.get("source_output_sha256"))
            or str(source_row[1]) != expected_schema
            or int(value.get("source_output_id", 0))
            != int(report.get("source_output_id", 0))
            or str(source_row[7]) != "succeeded"
            or str(source_row[8])
            != ("daily_coach" if report.get("mode") == "daily" else "weekly_coach")
        ):
            connection.close()
            raise ExternalActionError("m10_email_envelope_invalid")
        source_payload = json.loads(str(source_row[4]))
        if validate_payload(source_payload, expected_schema):
            connection.close()
            raise ExternalActionError("m10_report_source_invalid")
        if report.get("mode") == "daily":
            source_period_valid = (
                str(source_row[2]) == str(report.get("target"))
                and str(source_row[3]) == str(report.get("target"))
                and source_payload.get("report_date") == report.get("target")
            )
        else:
            daily_refs = [
                {
                    "output_id": int(item["source_output_id"]),
                    "output_sha256": str(item["source_output_sha256"]),
                }
                for item in report_sources
            ]
            evidence_refs = source_payload.get("evidence_refs")
            source_period_valid = (
                str(source_row[2]) == "2026-08-12"
                and str(source_row[3]) == "2026-08-18"
                and source_payload.get("period") == "2026-08-12/2026-08-18"
                and source_payload.get("daily_input_sha256")
                == [item["output_sha256"] for item in daily_refs]
                and json.loads(str(source_row[5])) == daily_refs
                and isinstance(evidence_refs, list)
                and [
                    {
                        "output_id": item.get("output_id"),
                        "output_sha256": item.get("sha256"),
                    }
                    for item in evidence_refs
                    if isinstance(item, dict)
                ]
                == daily_refs
            )
            weekly_run_id = int(source_row[6])
        if not source_period_valid:
            connection.close()
            raise ExternalActionError("m10_email_envelope_invalid")
        report_sources.append(
            {
                "mode": str(report["mode"]),
                "target": str(report["target"]),
                "source_output_id": int(value["source_output_id"]),
                "source_output_sha256": str(value["source_output_sha256"]),
                "email_output_id": int(value["report_output_id"]),
                "email_output_sha256": str(value["report_output_sha256"]),
            }
        )
        source_output_ids.add(int(value["source_output_id"]))
        email_output_ids.add(int(value["report_output_id"]))
        request = {
            "to": [recipient],
            "subject": value["subject"],
            "body": value["text"],
            "htmlBody": value["html"],
            "mimeType": "multipart/alternative",
        }
        emails.append(
            {
                "subject": value["subject"],
                "marker": report["email_marker"],
                "verification_query": f'subject:"{value["subject"]}"',
                "envelope_path": str(path),
                "envelope_sha256": sha256_file(path),
                "request_sha256": sha256_text(canonical_json(request)),
                "recipient": recipient,
                "recipient_sha256": recipient_sha256,
                "source_output_id": int(value["report_output_id"]),
                "source_output_sha256": str(value["report_output_sha256"]),
            }
        )
    if (
        len({item["marker"] for item in emails}) != 8
        or len(source_output_ids) != 8
        or len(email_output_ids) != 8
    ):
        connection.close()
        raise ExternalActionError("m10_email_marker_conflict")
    try:
        plan_row = connection.execute(
            "SELECT output.id,output.content_json,output.content_sha256 "
            "FROM skill_outputs output JOIN skill_runs run ON run.id=output.skill_run_id "
            "WHERE output.id=? AND output.output_kind='training_plan' "
            "AND output.schema_name='training_plan_v1' "
            "AND output.period_start_date='2026-08-12' "
            "AND output.period_end_date='2026-08-18' "
            "AND output.skill_run_id=? AND run.status='succeeded' "
            "AND run.skill_name='training-coach' AND run.operation='weekly_coach'",
            (int(manifest.get("training_plan_output_id", 0)), weekly_run_id),
        ).fetchone()
    finally:
        connection.close()
    if plan_row is None:
        raise ExternalActionError("m10_training_plan_missing")
    plan = json.loads(str(plan_row[1]))
    if validate_payload(plan, "training_plan_v1"):
        raise ExternalActionError("m10_training_plan_invalid")
    schedule = normalize_plan(plan)
    _bind_schedule_requests(schedule)
    preview = {
        "schema_version": "m10_external_preview_v1",
        "status": "awaiting_user_confirmation",
        "email_retention": "keep",
        "emails": emails,
        "report_sources": report_sources,
        "schedule": schedule,
        "training_plan_output_id": int(plan_row[0]),
        "training_plan_output_sha256": str(plan_row[2]),
        "gmail_send_budget": 8,
        "gmail_tool_call_budget": GMAIL_MCP_CALL_BUDGET,
        "garmin_workout_budget": 4,
        "garmin_tool_call_budget": GARMIN_MCP_CALL_BUDGET,
        "sites_calls": 0,
        "cron_calls": 0,
    }
    preview["preview_sha256"] = sha256_text(canonical_json(preview))
    manifest_for_run = {
        "m10_role": "external_preview_v1",
        "preview_sha256": preview["preview_sha256"],
        "training_plan_output_id": int(plan_row[0]),
    }
    connection = connect(database)
    try:
        run_id = begin_run(
            connection,
            run_key=f"training-report-publisher:m10-preview:{preview['preview_sha256']}",
            workflow_key="m10:external-preview:2026-08-18",
            dedupe_key=str(preview["preview_sha256"]),
            skill_name="training-report-publisher",
            operation="render_weekly",
            trigger_kind="manual",
            input_manifest=manifest_for_run,
            input_sha256=sha256_text(canonical_json(manifest_for_run)),
            target_from_date="2026-08-12",
            target_through_date="2026-08-25",
        )
        existing = connection.execute(
            "SELECT id,content_sha256 FROM skill_outputs "
            "WHERE skill_run_id=? AND schema_name='m10_external_preview_v1'",
            (run_id,),
        ).fetchone()
        if existing is None:
            preview_output_id = append_output(
                connection,
                skill_run_id=run_id,
                output_kind="execution_summary",
                logical_key="m10:external-preview:2026-08-18",
                schema_name="m10_external_preview_v1",
                schema_version="1",
                title_text="M10 exact external preview",
                content_json=preview,
                content_text=json.dumps(preview, ensure_ascii=False, sort_keys=True),
                lineage=[
                    {
                        "output_id": int(plan_row[0]),
                        "output_sha256": str(plan_row[2]),
                    },
                    *[
                        {
                            "output_id": int(item["source_output_id"]),
                            "output_sha256": str(item["source_output_sha256"]),
                        }
                        for item in emails
                    ],
                ],
                period_start_date="2026-08-12",
                period_end_date="2026-08-25",
            )
            finish_run(connection, run_id, status="succeeded")
            preview_output_sha256 = str(
                connection.execute(
                    "SELECT content_sha256 FROM skill_outputs WHERE id=?",
                    (preview_output_id,),
                ).fetchone()[0]
            )
        else:
            preview_output_id = int(existing[0])
            preview_output_sha256 = str(existing[1])
    finally:
        connection.close()
    _atomic_write(
        run_root / "external-preview.json",
        (
            json.dumps(preview, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode(),
    )
    return {
        **preview,
        "preview_output_id": preview_output_id,
        "preview_output_sha256": preview_output_sha256,
    }


def gmail_send_requests(
    preview: dict[str, Any], email_config: Path
) -> list[dict[str, Any]]:
    recipient, recipient_sha256 = load_email_recipient(email_config)
    emails = preview.get("emails")
    if not isinstance(emails, list) or len(emails) != 8:
        raise ExternalActionError("m10_email_batch_invalid")
    requests: list[dict[str, Any]] = []
    for item in emails:
        if not isinstance(item, dict):
            raise ExternalActionError("m10_email_batch_invalid")
        path = Path(str(item.get("envelope_path", "")))
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExternalActionError("m10_email_envelope_invalid") from exc
        if envelope.get("subject") != item.get("subject") or sha256_file(
            path
        ) != item.get("envelope_sha256"):
            raise ExternalActionError("m10_email_envelope_invalid")
        request = {
            "to": [recipient],
            "subject": envelope["subject"],
            "body": envelope["text"],
            "htmlBody": envelope["html"],
            "mimeType": "multipart/alternative",
        }
        if (
            item.get("recipient") != recipient
            or item.get("recipient_sha256") != recipient_sha256
            or sha256_text(canonical_json(request)) != item.get("request_sha256")
        ):
            raise ExternalActionError("m10_email_envelope_invalid")
        requests.append(request)
    return requests


def _public_preview_receipt(preview: dict[str, Any]) -> dict[str, Any]:
    """Return only non-private identifiers and counts for command output."""

    emails = preview.get("emails")
    schedule = preview.get("schedule")
    preview_output_id = preview.get("preview_output_id")
    preview_sha256 = preview.get("preview_sha256")
    preview_output_sha256 = preview.get("preview_output_sha256")
    if (
        preview.get("status") != "awaiting_user_confirmation"
        or not isinstance(emails, list)
        or len(emails) != 8
        or not isinstance(schedule, list)
        or not isinstance(preview_output_id, int)
        or isinstance(preview_output_id, bool)
        or preview_output_id <= 0
        or re.fullmatch(r"[0-9a-f]{64}", str(preview_sha256)) is None
        or re.fullmatch(r"[0-9a-f]{64}", str(preview_output_sha256)) is None
    ):
        raise ExternalActionError("m10_preview_receipt_invalid")
    return {
        "schema_version": "m10_external_preview_cli_receipt_v1",
        "status": "awaiting_user_confirmation",
        "preview_sha256": str(preview_sha256),
        "preview_output_id": preview_output_id,
        "preview_output_sha256": str(preview_output_sha256),
        "email_count": len(emails),
        "schedule_count": len(schedule),
    }


def garmin_batch_requests(preview: dict[str, Any]) -> dict[str, Any]:
    schedule = preview.get("schedule")
    if not isinstance(schedule, list) or not 1 <= len(schedule) <= 4:
        raise ExternalActionError("m10_workout_budget_invalid")
    workouts = [item["workout_data"] for item in schedule if isinstance(item, dict)]
    if len(workouts) != len(schedule):
        raise ExternalActionError("m10_training_plan_invalid")
    return {
        "inspect_existing": {},
        "inspect_calendar": {"start_date": PLAN_START, "end_date": PLAN_END},
        "upload": {"workouts_data": workouts},
        "schedule": [
            {"calendar_date": item["date"], "workout_name": item["name"]}
            for item in schedule
        ],
        "required_phases": [
            "create",
            "verify_created",
            "schedule",
            "verify_scheduled",
            "unschedule",
            "verify_absent_after_unschedule",
            "delete",
            "verify_absent_after_delete",
        ],
    }


def _garmin_action_row(connection: Any, action_id: int) -> Any:
    row = connection.execute(
        "SELECT provider,entity_kind,action_kind,status,related_action_id,"
        "target_external_id,result_external_id,provider_object_name,request_json,"
        "response_summary_json FROM external_actions WHERE id=?",
        (action_id,),
    ).fetchone()
    if row is None:
        raise ExternalActionError("m10_garmin_predecessor_missing")
    return row


def _successful_phase(
    connection: Any,
    *,
    phase: str,
    related_action_id: int,
    required_flag: tuple[str, bool] | None = None,
) -> Any:
    rows = connection.execute(
        "SELECT id,status,response_summary_json FROM external_actions "
        "WHERE provider='garmin' AND related_action_id=? "
        "AND json_extract(request_json,'$.m10_phase')=? ORDER BY id",
        (related_action_id, phase),
    ).fetchall()
    for row in rows:
        if str(row[1]) not in {"succeeded", "already_done"}:
            continue
        summary = json.loads(str(row[2])) if row[2] is not None else {}
        if required_flag is None or summary.get(required_flag[0]) is required_flag[1]:
            return row
    raise ExternalActionError("m10_garmin_lifecycle_order_invalid")


def _validate_garmin_lifecycle(
    connection: Any,
    *,
    spec: dict[str, Any],
    request: dict[str, Any],
    related_action_id: int | None,
) -> None:
    phase = request.get("m10_phase")
    expected = {
        "create": ("garmin_workout_create", "workout"),
        "verify_created": ("garmin_workout_verify", "workout"),
        "schedule": ("garmin_calendar_schedule", "calendar_entry"),
        "verify_scheduled": ("garmin_workout_verify", "workout"),
        "unschedule": ("garmin_calendar_unschedule", "calendar_entry"),
        "verify_absent_after_unschedule": ("garmin_workout_verify", "workout"),
        "delete": ("garmin_workout_delete", "workout"),
        "verify_absent_after_delete": ("garmin_workout_verify", "workout"),
    }
    if phase not in expected or expected[phase] != (
        spec["action_kind"],
        spec["entity_kind"],
    ):
        raise ExternalActionError("m10_garmin_lifecycle_phase_invalid")
    if phase == "create":
        if related_action_id is not None:
            raise ExternalActionError("m10_garmin_lifecycle_order_invalid")
        created = int(
            connection.execute(
                "SELECT COUNT(*) FROM external_actions WHERE provider='garmin' "
                "AND action_kind='garmin_workout_create' "
                "AND provider_object_name LIKE ?",
                (f"%-{TEST_TAG}-GTS",),
            ).fetchone()[0]
        )
        if created >= 4:
            raise ExternalActionError("m10_workout_budget_invalid")
        return
    if related_action_id is None:
        raise ExternalActionError("m10_garmin_predecessor_missing")
    predecessor = _garmin_action_row(connection, related_action_id)
    if phase in {"verify_created", "schedule", "unschedule", "delete"}:
        if (
            str(predecessor[0]) != "garmin"
            or str(predecessor[2]) != "garmin_workout_create"
            or str(predecessor[3]) not in {"succeeded", "already_done"}
        ):
            raise ExternalActionError("m10_garmin_lifecycle_order_invalid")
    if phase == "schedule":
        _successful_phase(
            connection,
            phase="verify_created",
            related_action_id=related_action_id,
            required_flag=("exists", True),
        )
    elif phase == "verify_scheduled":
        if str(predecessor[2]) != "garmin_calendar_schedule" or str(
            predecessor[3]
        ) not in {"succeeded", "already_done"}:
            raise ExternalActionError("m10_garmin_lifecycle_order_invalid")
    elif phase == "unschedule":
        schedule = _successful_phase(
            connection, phase="schedule", related_action_id=related_action_id
        )
        _successful_phase(
            connection,
            phase="verify_scheduled",
            related_action_id=int(schedule[0]),
            required_flag=("exists", True),
        )
    elif phase == "verify_absent_after_unschedule":
        if str(predecessor[2]) != "garmin_calendar_unschedule" or str(
            predecessor[3]
        ) not in {"succeeded", "already_done"}:
            raise ExternalActionError("m10_garmin_lifecycle_order_invalid")
    elif phase == "delete":
        unschedule = _successful_phase(
            connection, phase="unschedule", related_action_id=related_action_id
        )
        _successful_phase(
            connection,
            phase="verify_absent_after_unschedule",
            related_action_id=int(unschedule[0]),
            required_flag=("absent", True),
        )
    elif phase == "verify_absent_after_delete":
        if str(predecessor[2]) != "garmin_workout_delete" or str(
            predecessor[3]
        ) not in {"succeeded", "already_done"}:
            raise ExternalActionError("m10_garmin_lifecycle_order_invalid")


def assert_garmin_cleanup_complete(database: Path, owner_action_ids: list[int]) -> None:
    database = _assert_candidate_database(database)
    if not 1 <= len(owner_action_ids) <= 4 or len(set(owner_action_ids)) != len(
        owner_action_ids
    ):
        raise ExternalActionError("m10_workout_budget_invalid")
    connection = connect(database, read_only=True, immutable=True)
    try:
        all_owners = {
            int(row[0])
            for row in connection.execute(
                "SELECT id FROM external_actions WHERE provider='garmin' "
                "AND action_kind='garmin_workout_create' "
                "AND provider_object_name LIKE ?",
                (f"%-{TEST_TAG}-GTS",),
            ).fetchall()
        }
        if all_owners != set(owner_action_ids) or len(all_owners) > 4:
            raise ExternalActionError("m10_garmin_cleanup_scope_mismatch")
        for owner_id in owner_action_ids:
            owner = _garmin_action_row(connection, owner_id)
            if str(owner[2]) != "garmin_workout_create" or str(owner[3]) not in {
                "succeeded",
                "already_done",
            }:
                raise ExternalActionError("m10_garmin_cleanup_incomplete")
            schedule = _successful_phase(
                connection, phase="schedule", related_action_id=owner_id
            )
            _successful_phase(
                connection,
                phase="verify_scheduled",
                related_action_id=int(schedule[0]),
                required_flag=("exists", True),
            )
            unschedule = _successful_phase(
                connection, phase="unschedule", related_action_id=owner_id
            )
            _successful_phase(
                connection,
                phase="verify_absent_after_unschedule",
                related_action_id=int(unschedule[0]),
                required_flag=("absent", True),
            )
            deletion = _successful_phase(
                connection, phase="delete", related_action_id=owner_id
            )
            _successful_phase(
                connection,
                phase="verify_absent_after_delete",
                related_action_id=int(deletion[0]),
                required_flag=("absent", True),
            )
    finally:
        connection.close()


def _approval_scope(spec: dict[str, Any], preview_sha256: str) -> dict[str, Any]:
    return {
        "provider": spec["provider"],
        "action_kind": spec["action_kind"],
        "entity_kind": spec["entity_kind"],
        "target_key": spec["target_key"],
        "scope_kind": spec["scope_kind"],
        "preview_sha256": preview_sha256,
        "budget": {"max_actions": 1},
    }


def _preview_target_exists(payload: dict[str, Any], spec: dict[str, Any]) -> bool:
    provider = spec.get("provider")
    target_key = spec.get("target_key")
    if provider == "gmail":
        return any(
            isinstance(item, dict) and target_key == f"m10:email:{item.get('marker')}"
            for item in payload.get("emails", [])
        )
    if provider != "garmin":
        return False
    for item in payload.get("schedule", []):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.endswith(f"-{TEST_TAG}-GTS"):
            continue
        for phase in item.get("action_request_sha256", {}):
            if target_key == f"m10:{phase}:{name}":
                return True
    return False


def _preview_request_matches(
    payload: dict[str, Any],
    *,
    spec: dict[str, Any],
    request_sha256: str,
    provider_object_name: str | None,
) -> bool:
    if spec.get("provider") == "gmail":
        return any(
            isinstance(item, dict)
            and spec.get("target_key") == f"m10:email:{item.get('marker')}"
            and request_sha256 == item.get("request_sha256")
            for item in payload.get("emails", [])
        )
    if spec.get("provider") != "garmin":
        return False
    for item in payload.get("schedule", []):
        if not isinstance(item, dict) or item.get("name") != provider_object_name:
            continue
        request_hashes = item.get("action_request_sha256")
        if not isinstance(request_hashes, dict):
            return False
        for phase, expected_sha256 in request_hashes.items():
            if (
                spec.get("target_key") == f"m10:{phase}:{provider_object_name}"
                and request_sha256 == expected_sha256
            ):
                return True
    return False


def _preview_payload(
    connection: Any, source_output_id: int, source_output_sha256: str
) -> dict[str, Any]:
    row = connection.execute(
        "SELECT content_json,content_sha256,schema_name FROM skill_outputs WHERE id=?",
        (source_output_id,),
    ).fetchone()
    if (
        row is None
        or str(row[1]) != source_output_sha256
        or str(row[2]) != "m10_external_preview_v1"
    ):
        raise ExternalActionError("m10_preview_confirmation_invalid")
    payload = json.loads(str(row[0]))
    valid = connection.execute(
        "SELECT trainlab_valid_m10_preview(?)", (str(row[0]),)
    ).fetchone()
    if not isinstance(payload, dict) or valid is None or int(valid[0]) != 1:
        raise ExternalActionError("m10_preview_confirmation_invalid")
    return payload


def _provider_id(value: Any) -> int | str:
    text = str(value)
    return int(text) if text.isdigit() else text


def _mcp_request_matches_actions(
    *,
    provider: str,
    tool_name: str,
    request: dict[str, Any],
    rows: list[Any],
) -> bool:
    """Bind a provider call to the exact prepared actions it is allowed to perform."""
    action_requests: list[dict[str, Any]] = []
    for row in rows:
        try:
            value = json.loads(str(row[4]))
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(value, dict):
            return False
        action_requests.append(value)
    if provider == "gmail" and tool_name == "send_email":
        return len(action_requests) == 1 and canonical_json(request) == canonical_json(
            action_requests[0]
        )
    if provider != "garmin":
        return False
    if tool_name == "upload_workout":
        return len(rows) == 1 and request == {
            "workout_data": action_requests[0].get("workout_data")
        }
    if tool_name == "upload_workouts":
        return request == {
            "workouts": [item.get("workout_data") for item in action_requests]
        }
    if tool_name == "schedule_workout":
        return len(rows) == 1 and request == {
            "workout_id": _provider_id(rows[0][5]),
            "calendar_date": action_requests[0].get("calendar_date"),
        }
    if tool_name == "schedule_workouts":
        return request == {
            "schedules": [
                {
                    "workout_id": _provider_id(row[5]),
                    "calendar_date": action_request.get("calendar_date"),
                }
                for row, action_request in zip(rows, action_requests, strict=True)
            ]
        }
    if tool_name == "unschedule_workout":
        return len(rows) == 1 and request == {
            "scheduled_workout_id": _provider_id(rows[0][5])
        }
    if tool_name == "unschedule_workouts":
        return request == {
            "scheduled_workout_ids": [_provider_id(row[5]) for row in rows]
        }
    if tool_name == "delete_workout":
        return len(rows) == 1 and request == {"workout_id": _provider_id(rows[0][5])}
    if tool_name == "delete_workouts":
        return request == {"workout_ids": [_provider_id(row[5]) for row in rows]}
    return False


def authorize_action(
    database: Path,
    *,
    spec: dict[str, Any],
    source_output_id: int,
    source_output_sha256: str,
    source_ref: str,
    preview_sha256: str,
) -> int:
    """Persist one exact user-explicit approval after the conversation gate."""
    database = _assert_candidate_database(database)
    if (
        not re.fullmatch(r"[0-9a-f]{64}", preview_sha256)
        or source_ref != f"m10-preview:{preview_sha256}"
    ):
        raise ExternalActionError("m10_preview_confirmation_invalid")
    connection = connect(database, read_only=True, immutable=True)
    try:
        source_payload = _preview_payload(
            connection, source_output_id, source_output_sha256
        )
    finally:
        connection.close()
    if source_payload.get(
        "preview_sha256"
    ) != preview_sha256 or not _preview_target_exists(source_payload, spec):
        raise ExternalActionError("m10_preview_confirmation_invalid")
    scope = _approval_scope(spec, preview_sha256)
    scope_json = canonical_json(scope)
    approval_key = sha256_text(
        canonical_json(
            {
                "m10": "external-approval-v1",
                "source_output_id": source_output_id,
                "source_output_sha256": source_output_sha256,
                "scope": scope,
                "source_ref": source_ref,
            }
        )
    )
    connection = connect(database)
    try:
        existing = connection.execute(
            "SELECT id FROM approvals WHERE approval_key=?", (approval_key,)
        ).fetchone()
        if existing is not None:
            return int(existing[0])
        now = datetime.now(timezone.utc).replace(microsecond=0)
        valid_until = now + timedelta(hours=6)
        cursor = connection.execute(
            """INSERT INTO approvals
            (approval_key,candidate_output_id,candidate_output_sha256,authority_kind,decision,
             scope_kind,scope_json,scope_sha256,source_ref,reason_code,decided_at_utc,
             valid_from_utc,valid_until_utc)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                approval_key,
                source_output_id,
                source_output_sha256,
                "user_explicit",
                "approved",
                spec["scope_kind"],
                scope_json,
                hashlib.sha256(scope_json.encode()).hexdigest(),
                source_ref,
                "m10_exact_preview_confirmed",
                now.isoformat().replace("+00:00", "Z"),
                now.isoformat().replace("+00:00", "Z"),
                valid_until.isoformat().replace("+00:00", "Z"),
            ),
        )
        connection.commit()
        return require_lastrowid(cursor)
    finally:
        connection.close()


def prepare_action(
    database: Path,
    *,
    spec: dict[str, Any],
    source_output_id: int,
    source_output_sha256: str,
    approval_id: int,
    request: dict[str, Any],
    related_action_id: int | None = None,
    target_external_id: str | None = None,
    provider_object_name: str | None = None,
) -> int:
    database = _assert_candidate_database(database)
    if spec.get("provider") == "garmin" and (
        not isinstance(provider_object_name, str)
        or not provider_object_name.endswith(f"-{TEST_TAG}-GTS")
    ):
        raise ExternalActionError("m10_garmin_object_not_owned")
    request_json = canonical_json(request)
    request_sha256 = hashlib.sha256(request_json.encode()).hexdigest()
    idempotency_key = sha256_text(
        canonical_json(
            {
                "m10": "external-action-v1",
                "source_output_id": source_output_id,
                "spec": spec,
                "request": request,
            }
        )
    )
    connection = connect(database)
    try:
        preview = _preview_payload(connection, source_output_id, source_output_sha256)
        if not _preview_request_matches(
            preview,
            spec=spec,
            request_sha256=request_sha256,
            provider_object_name=provider_object_name,
        ):
            raise ExternalActionError("m10_action_not_in_preview")
        if spec.get("provider") == "garmin":
            _validate_garmin_lifecycle(
                connection,
                spec=spec,
                request=request,
                related_action_id=related_action_id,
            )
        existing = connection.execute(
            "SELECT id FROM external_actions WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            return int(existing[0])
        run = connection.execute(
            "SELECT skill_run_id FROM skill_outputs WHERE id=? AND content_sha256=?",
            (source_output_id, source_output_sha256),
        ).fetchone()
        if run is None:
            raise ExternalActionError("m10_action_source_missing")
        cursor = connection.execute(
            """INSERT INTO external_actions
            (idempotency_key,skill_run_id,provider,entity_kind,action_kind,source_output_id,
             source_output_sha256,approval_id,related_action_id,target_key,target_external_id,
             provider_object_name,request_json,request_sha256,status,attempt_count,prepared_at_utc)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                idempotency_key,
                int(run[0]),
                spec["provider"],
                spec["entity_kind"],
                spec["action_kind"],
                source_output_id,
                source_output_sha256,
                approval_id,
                related_action_id,
                spec["target_key"],
                target_external_id,
                provider_object_name,
                request_json,
                request_sha256,
                "prepared",
                0,
                utc_now(),
            ),
        )
        connection.commit()
        return require_lastrowid(cursor)
    finally:
        connection.close()


def transition_action(
    database: Path,
    action_id: int,
    *,
    status: str,
    result_external_id: str | None = None,
    provider_marker: str | None = None,
    response_summary: dict[str, Any] | None = None,
    error_code: str | None = None,
    error_summary: str | None = None,
) -> None:
    database = _assert_candidate_database(database)
    if status not in {
        "in_progress",
        "succeeded",
        "already_done",
        "failed_safe",
        "unknown",
        "cancelled",
    }:
        raise ExternalActionError("m10_action_status_invalid")
    connection = connect(database)
    try:
        row = connection.execute(
            "SELECT provider,request_json,action_kind,attempt_count,target_key,"
            "source_output_id,source_output_sha256 "
            "FROM external_actions WHERE id=?",
            (action_id,),
        ).fetchone()
        if row is None:
            raise ExternalActionError("m10_action_missing")
        request = json.loads(str(row[1]))
        phase = request.get("m10_phase") if str(row[0]) == "garmin" else None
        if (
            status == "in_progress"
            and str(row[4]).startswith("m10:")
            and int(row[3]) >= 1
        ):
            raise ExternalActionError("m10_external_retry_forbidden")
        if status in {"succeeded", "already_done"}:
            if str(row[0]) == "gmail" and (
                not result_external_id
                or not provider_marker
                or provider_marker != str(row[4]).removeprefix("m10:email:")
                or response_summary is None
                or response_summary.get("verified") is not True
            ):
                raise ExternalActionError("m10_gmail_success_evidence_missing")
            if str(row[0]) == "gmail":
                marker = str(row[4]).removeprefix("m10:email:")
                preview = _preview_payload(connection, int(row[5]), str(row[6]))
                preview_email = next(
                    (
                        item
                        for item in preview.get("emails", [])
                        if isinstance(item, dict) and item.get("marker") == marker
                    ),
                    None,
                )
                expected_query = (
                    preview_email.get("verification_query")
                    if isinstance(preview_email, dict)
                    else None
                )
                expected_summary = {
                    "verified": True,
                    "match_count": 1,
                    "verification_query": expected_query,
                    "send_message_id": result_external_id,
                    "matched_message_id": result_external_id,
                }
                evidence_rows = connection.execute(
                    "SELECT json_extract(run.input_manifest_json,'$.tool_name'),"
                    "json_extract(run.input_manifest_json,'$.request_json.query'),"
                    "output.content_json FROM skill_runs run "
                    "JOIN skill_outputs output ON output.skill_run_id=run.id "
                    "JOIN json_each(run.input_manifest_json,'$.external_action_ids') member "
                    "WHERE run.status='succeeded' AND run.operation='mcp_tool_call' "
                    "AND json_extract(run.input_manifest_json,'$.m10_role')="
                    "'m10_external_mcp_call_v1' "
                    "AND json_extract(run.input_manifest_json,'$.provider')='gmail' "
                    "AND CAST(member.value AS INTEGER)=? "
                    "AND output.schema_name='m10_mcp_call_result_v1' ORDER BY run.id",
                    (action_id,),
                ).fetchall()
                send_results: list[dict[str, Any]] = []
                search_results: list[dict[str, Any]] = []
                for evidence in evidence_rows:
                    try:
                        payload = json.loads(str(evidence[2]))
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if str(evidence[0]) == "send_email":
                        send_results.append(payload)
                    elif (
                        str(evidence[0]) == "search_emails"
                        and evidence[1] == expected_query
                    ):
                        search_results.append(payload)
                evidence_valid = (
                    isinstance(expected_query, str)
                    and response_summary == expected_summary
                    and len(send_results) == 1
                    and len(search_results) == 1
                    and send_results[0].get("message_id") == result_external_id
                    and send_results[0].get("matched_message_ids") == []
                    and send_results[0].get("match_count") == 0
                    and search_results[0].get("message_id") is None
                    and search_results[0].get("matched_message_ids")
                    == [result_external_id]
                    and search_results[0].get("match_count") == 1
                )
                if not evidence_valid:
                    raise ExternalActionError("m10_gmail_success_evidence_missing")
            if phase in {"verify_created", "verify_scheduled"} and (
                response_summary is None or response_summary.get("exists") is not True
            ):
                raise ExternalActionError("m10_garmin_verification_missing")
            if phase in {
                "verify_absent_after_unschedule",
                "verify_absent_after_delete",
            } and (
                response_summary is None or response_summary.get("absent") is not True
            ):
                raise ExternalActionError("m10_garmin_verification_missing")
            if phase == "create" and not result_external_id:
                raise ExternalActionError("m10_garmin_create_id_missing")
            if phase == "create" and (
                response_summary is None
                or response_summary.get("created_new") is not True
                or response_summary.get("preexisting") is not False
            ):
                raise ExternalActionError("m10_garmin_create_evidence_missing")
            if phase == "schedule" and not result_external_id:
                raise ExternalActionError("m10_garmin_schedule_id_missing")
        if status == "in_progress":
            cursor = connection.execute(
                "UPDATE external_actions SET status='in_progress',attempt_count=attempt_count+1,started_at_utc=? WHERE id=?",
                (utc_now(), action_id),
            )
        else:
            finished = (
                utc_now()
                if status in {"succeeded", "already_done", "failed_safe", "cancelled"}
                else None
            )
            cursor = connection.execute(
                """UPDATE external_actions SET status=?,finished_at_utc=?,result_external_id=?,
                provider_marker=?,response_summary_json=?,error_code=?,error_summary=? WHERE id=?""",
                (
                    status,
                    finished,
                    result_external_id,
                    provider_marker,
                    canonical_json(response_summary)
                    if response_summary is not None
                    else None,
                    error_code,
                    error_summary,
                    action_id,
                ),
            )
        if cursor.rowcount != 1:
            raise ExternalActionError("m10_action_transition_failed")
        connection.commit()
    finally:
        connection.close()


def action_spec(
    provider: str, action_kind: str, entity_kind: str, target_key: str
) -> dict[str, str]:
    return {
        "provider": provider,
        "action_kind": action_kind,
        "entity_kind": entity_kind,
        "target_key": target_key,
        "scope_kind": "gmail" if provider == "gmail" else "garmin",
    }


def claim_mcp_tool_call(
    database: Path,
    *,
    provider: str,
    tool_name: str,
    request: dict[str, Any],
    preview_output_id: int,
    preview_output_sha256: str,
    external_action_ids: list[int] | None = None,
    reconcile_failed_run_id: int | None = None,
) -> tuple[int, bool]:
    """Persistently claim one M10 MCP invocation before touching the provider."""
    database = _assert_candidate_database(database)
    if tool_name not in MCP_TOOL_ALLOWLIST.get(provider, set()):
        raise ExternalActionError("m10_mcp_tool_not_allowed")
    connection = connect(database)
    try:
        preview = _preview_payload(connection, preview_output_id, preview_output_sha256)
        preview_sha256 = str(preview.get("preview_sha256", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", preview_sha256):
            raise ExternalActionError("m10_preview_confirmation_invalid")
        action_ids = list(external_action_ids or [])
        request_sha256 = sha256_text(canonical_json(request))
        base_manifest = {
            "m10_role": "m10_external_mcp_call_v1",
            "provider": provider,
            "tool_name": tool_name,
            "request_json": request,
            "request_sha256": request_sha256,
            "preview_output_id": preview_output_id,
            "preview_output_sha256": preview_output_sha256,
            "preview_sha256": preview_sha256,
            "external_action_ids": sorted(action_ids),
        }
        dedupe_key = sha256_text(canonical_json(base_manifest))
        manifest = dict(base_manifest)
        if reconcile_failed_run_id is not None:
            if (
                provider != "gmail"
                or tool_name != "search_emails"
                or isinstance(reconcile_failed_run_id, bool)
                or reconcile_failed_run_id <= 0
            ):
                raise ExternalActionError("m10_external_retry_forbidden")
            manifest.update(
                {
                    "reconciliation_mode": "user_approved_result_unpersisted",
                    "prior_run_id": reconcile_failed_run_id,
                }
            )
        valid_request = connection.execute(
            "SELECT trainlab_valid_m10_mcp_request(?,?)",
            (canonical_json(manifest), canonical_json(preview)),
        ).fetchone()
        if valid_request is None or int(valid_request[0]) != 1:
            code = (
                "m10_mcp_action_binding_invalid"
                if tool_name in MCP_WRITE_ACTION_KIND.get(provider, {})
                else "m10_mcp_read_scope_invalid"
            )
            raise ExternalActionError(code)
        expected_action_kind = MCP_WRITE_ACTION_KIND.get(provider, {}).get(tool_name)
        if expected_action_kind is not None:
            if not action_ids or len(action_ids) != len(set(action_ids)):
                raise ExternalActionError("m10_mcp_action_binding_invalid")
            placeholders = ",".join("?" for _ in action_ids)
            rows = connection.execute(
                f"SELECT action.id,action.action_kind,action.status,"
                f"action.source_output_id,action.request_json,"
                f"action.target_external_id,action.provider_object_name "
                f"FROM external_actions action JOIN approvals approval "
                f"ON approval.id=action.approval_id "
                f"WHERE action.id IN ({placeholders}) "
                f"AND action.source_output_sha256=? "
                f"AND approval.candidate_output_id=? "
                f"AND approval.candidate_output_sha256=? "
                f"AND approval.decision='approved' "
                f"AND approval.valid_from_utc<=? AND approval.valid_until_utc>=? "
                f"AND json_extract(approval.scope_json,'$.preview_sha256')=? "
                f"AND json_extract(approval.scope_json,'$.provider')=action.provider "
                f"AND json_extract(approval.scope_json,'$.action_kind')=action.action_kind "
                f"AND json_extract(approval.scope_json,'$.entity_kind')=action.entity_kind "
                f"AND json_extract(approval.scope_json,'$.target_key')=action.target_key "
                f"ORDER BY action.id",
                (
                    *action_ids,
                    preview_output_sha256,
                    preview_output_id,
                    preview_output_sha256,
                    utc_now(),
                    utc_now(),
                    preview_sha256,
                ),
            ).fetchall()
            if (
                len(rows) != len(action_ids)
                or any(
                    str(row[1]) != expected_action_kind
                    or str(row[2]) != "prepared"
                    or int(row[3]) != preview_output_id
                    for row in rows
                )
                or not _mcp_request_matches_actions(
                    provider=provider,
                    tool_name=tool_name,
                    request=request,
                    rows=rows,
                )
            ):
                raise ExternalActionError("m10_mcp_action_binding_invalid")
        elif tool_name in {"search_emails", "get_workout_by_id"}:
            if len(action_ids) != 1:
                raise ExternalActionError("m10_mcp_read_scope_invalid")
            now = utc_now()
            row = connection.execute(
                """SELECT action.provider,action.action_kind,action.status,
                          action.target_key,action.result_external_id
                   FROM external_actions action
                   JOIN approvals approval ON approval.id=action.approval_id
                   WHERE action.id=?
                     AND action.source_output_id=?
                     AND action.source_output_sha256=?
                     AND approval.candidate_output_id=action.source_output_id
                     AND approval.candidate_output_sha256=action.source_output_sha256
                     AND approval.decision='approved'
                     AND approval.valid_from_utc<=?
                     AND approval.valid_until_utc>=?
                     AND json_extract(approval.scope_json,'$.preview_sha256')=?""",
                (
                    action_ids[0],
                    preview_output_id,
                    preview_output_sha256,
                    now,
                    now,
                    preview_sha256,
                ),
            ).fetchone()
            valid_read = False
            if row is not None and tool_name == "search_emails":
                marker = str(row[3]).removeprefix("m10:email:")
                preview_email = next(
                    (
                        item
                        for item in preview.get("emails", [])
                        if isinstance(item, dict) and item.get("marker") == marker
                    ),
                    None,
                )
                valid_read = (
                    str(row[0]) == "gmail"
                    and str(row[1]) == "gmail_send"
                    and str(row[2])
                    in {
                        "prepared",
                        "in_progress",
                        "succeeded",
                        "already_done",
                        # An uncertain send may only use the exact preview-bound
                        # read query to reconcile; write claims still require
                        # the action to remain prepared above.
                        "unknown",
                    }
                    and preview_email is not None
                    and request["query"] == preview_email.get("verification_query")
                )
            elif row is not None and tool_name == "get_workout_by_id":
                valid_read = (
                    str(row[0]) == "garmin"
                    and str(row[1]) == "garmin_workout_create"
                    and str(row[2]) in {"succeeded", "already_done"}
                    and row[4] is not None
                    and str(row[4]) == str(request["workout_id"])
                )
            if not valid_read:
                raise ExternalActionError("m10_mcp_read_scope_invalid")
        elif action_ids:
            raise ExternalActionError("m10_mcp_read_scope_invalid")
        existing = connection.execute(
            "SELECT id,status,error_code,attempt_no FROM skill_runs "
            "WHERE dedupe_key=? ORDER BY attempt_no,id",
            (dedupe_key,),
        ).fetchall()
        if existing:
            if reconcile_failed_run_id is None and (
                len(existing) == 1 and str(existing[0][1]) == "succeeded"
            ):
                return int(existing[0][0]), True
            if reconcile_failed_run_id is not None:
                prior_valid = (
                    int(existing[0][0]) == reconcile_failed_run_id
                    and str(existing[0][1]) == "failed"
                    and str(existing[0][2]) == "gmail_search_result_unpersisted"
                    and int(existing[0][3]) == 1
                )
                if not prior_valid:
                    raise ExternalActionError("m10_external_retry_forbidden")
                if len(existing) == 2 and (
                    str(existing[1][1]) == "succeeded" and int(existing[1][3]) == 2
                ):
                    return int(existing[1][0]), True
                if len(existing) != 1:
                    raise ExternalActionError("m10_external_retry_forbidden")
            else:
                raise ExternalActionError("m10_external_retry_forbidden")
        run_id = begin_run(
            connection,
            run_key=f"m10-mcp:{provider}:{dedupe_key}:attempt-1",
            workflow_key=f"m10:external:{provider}:2026-08-18",
            dedupe_key=dedupe_key,
            skill_name=(
                "gmail-sender" if provider == "gmail" else "garmin-training-sender"
            ),
            operation="mcp_tool_call",
            trigger_kind="manual",
            input_manifest=manifest,
        )
        return run_id, False
    except Exception:
        connection.close()
        raise
    finally:
        if connection:
            connection.close()


def finish_mcp_tool_call(
    database: Path,
    run_id: int,
    *,
    status: str,
    error_code: str | None = None,
    result_summary: dict[str, Any] | None = None,
) -> None:
    database = _assert_candidate_database(database)
    if status not in {"succeeded", "failed", "blocked"}:
        raise ExternalActionError("m10_mcp_call_status_invalid")
    connection = connect(database)
    try:
        row = connection.execute(
            "SELECT input_manifest_json,status FROM skill_runs WHERE id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise ExternalActionError("m10_mcp_call_missing")
        manifest = json.loads(str(row[0]))
        if manifest.get("m10_role") != "m10_external_mcp_call_v1":
            raise ExternalActionError("m10_mcp_call_missing")
        if (
            status == "succeeded"
            and manifest.get("provider") == "gmail"
            and manifest.get("tool_name") in {"send_email", "search_emails"}
            and result_summary is None
        ):
            raise ExternalActionError("m10_mcp_result_invalid")
        if result_summary is not None:
            expected_base = {
                "schema_version": "m10_mcp_call_result_v1",
                "provider": manifest.get("provider"),
                "tool_name": manifest.get("tool_name"),
                "request_sha256": manifest.get("request_sha256"),
                "external_action_ids": manifest.get("external_action_ids"),
            }
            if (
                status != "succeeded"
                or manifest.get("provider") != "gmail"
                or manifest.get("tool_name") not in {"send_email", "search_emails"}
                or any(
                    result_summary.get(key) != value
                    for key, value in expected_base.items()
                )
                or validate_payload(result_summary, "m10_mcp_call_result_v1")
            ):
                raise ExternalActionError("m10_mcp_result_invalid")
            if manifest.get("tool_name") == "send_email":
                semantics_valid = (
                    isinstance(result_summary.get("message_id"), str)
                    and bool(result_summary.get("message_id"))
                    and result_summary.get("matched_message_ids") == []
                    and result_summary.get("match_count") == 0
                )
            else:
                matched = result_summary.get("matched_message_ids")
                semantics_valid = (
                    result_summary.get("message_id") is None
                    and isinstance(matched, list)
                    and len(matched) == 1
                    and len(set(matched)) == 1
                    and result_summary.get("match_count") == 1
                )
            if not semantics_valid:
                raise ExternalActionError("m10_mcp_result_invalid")
            append_output(
                connection,
                skill_run_id=run_id,
                output_kind="execution_summary",
                logical_key=f"m10:mcp-result:{run_id}",
                schema_name="m10_mcp_call_result_v1",
                schema_version="1",
                title_text=(
                    f"M10 {manifest['provider']} {manifest['tool_name']} result"
                ),
                content_json=result_summary,
                content_text=canonical_json(result_summary),
                lineage=[
                    {
                        "output_id": int(manifest["preview_output_id"]),
                        "output_sha256": str(manifest["preview_output_sha256"]),
                    }
                ],
            )
        finish_run(connection, run_id, status=status, error_code=error_code)
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    preview = subparsers.add_parser("preview")
    preview.add_argument("--database", type=Path, required=True)
    preview.add_argument("--run-root", type=Path, required=True)
    preview.add_argument("--email-config", type=Path, required=True)
    lookup = subparsers.add_parser("parse-garmin-workout-lookup")
    lookup.add_argument("--expected-workout-id", required=True)
    lookup.add_argument("--expected-name", required=True)
    args = parser.parse_args()
    if args.command == "preview":
        result = build_preview(
            args.database, args.run_root.resolve(), args.email_config
        )
        print(
            json.dumps(
                _public_preview_receipt(result), ensure_ascii=False, sort_keys=True
            )
        )
        return 0
    if args.command == "parse-garmin-workout-lookup":
        result = parse_garmin_workout_lookup(
            sys.stdin.read(1_000_001),
            expected_workout_id=str(args.expected_workout_id),
            expected_name=str(args.expected_name),
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
