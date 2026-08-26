"""Small state layer shared by the runtime Skills.

The database stores control state and immutable outputs only. Health and activity
facts stay in raw files and are referenced by SHA-256.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from skills._shared.m10_plan_contract import (
        M10PlanError,
        garmin_action_requests,
        normalize_plan,
    )
except ModuleNotFoundError:  # Direct execution from skills/_shared/scripts.
    from m10_plan_contract import (
        M10PlanError,
        garmin_action_requests,
        normalize_plan,
    )

SCHEMA_VERSION = "1"
EXPECTED_TABLES = {
    "skill_runs",
    "activity_inventory",
    "raw_files",
    "skill_outputs",
    "approvals",
    "external_actions",
}


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_lastrowid(cursor: sqlite3.Cursor) -> int:
    """Return a SQLite insert id, failing closed if SQLite did not provide one."""
    if cursor.lastrowid is None:
        raise RuntimeError("sqlite_lastrowid_missing")
    return int(cursor.lastrowid)


def _valid_date(value: object) -> int:
    if value is None:
        return 1
    try:
        parsed = str(value)
        return int(datetime.strptime(parsed, "%Y-%m-%d").strftime("%Y-%m-%d") == parsed)
    except (TypeError, ValueError):
        return 0


def _valid_utc(value: object) -> int:
    if value is None:
        return 1
    try:
        datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ")
        return 1
    except (TypeError, ValueError):
        return 0


def _json_sha(value: object) -> str:
    """Hash a JSON value after the same canonicalization used by the host."""
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return ""
    return sha256_text(canonical_json(parsed))


def _valid_schema_payload(value: object, schema_name: object) -> int:
    """Validate the bounded M10 schemas used by SQLite safety gates."""
    allowed = {
        "daily_ai_result_v1",
        "weekly_ai_result_v1",
        "training_plan_v1",
        "daily_ai_result_v2",
        "weekly_ai_result_v2",
        "training_plan_v2",
        "daily_evidence_rollup_v1",
        "weekly_evidence_digest_v1",
        "activity_technical_evidence_v1",
        "daily_completed_observation_v1",
        "daily_health_analysis_v3",
        "weekly_training_evidence_v2",
        "training_plan_v3",
        "weekly_ai_result_v3",
        "daily_reader_content_v1",
        "weekly_reader_content_v1",
        "m10_mcp_call_result_v1",
        "m10_gmail_rest_preview_v1",
        "m10_gmail_rest_intent_v1",
        "m10_gmail_rest_result_v1",
        "m10_gmail_rest_preview_v2",
        "m10_gmail_rest_intent_v2",
        "m10_gmail_rest_result_v2",
        "m10_gmail_rest_preview_v3",
        "m10_gmail_rest_intent_v3",
        "m10_gmail_rest_result_v3",
    }
    name = str(schema_name)
    if name not in allowed:
        return 0
    try:
        payload = json.loads(str(value))
        from skills._shared.scripts.schema_validation import validate_payload

        return int(not validate_payload(payload, name))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return 0


def _valid_m10_plan_schedule(plan_value: object, schedule_value: object) -> int:
    """Require the approved Garmin rows to be the exact plan projection."""
    try:
        plan = json.loads(str(plan_value))
        schedule = json.loads(str(schedule_value))
        if not isinstance(plan, dict) or not isinstance(schedule, list):
            return 0
        expected = normalize_plan(plan)
        for row in expected:
            row["action_request_sha256"] = {
                phase: sha256_text(canonical_json(request))
                for phase, request in garmin_action_requests(row).items()
            }
        return int(canonical_json(expected) == canonical_json(schedule))
    except (M10PlanError, TypeError, ValueError, json.JSONDecodeError):
        return 0


def _valid_m10_preview(value: object) -> int:
    """Validate the exact M10 confirmation artifact used by SQL safety gates."""
    try:
        payload = json.loads(str(value))
        if not isinstance(payload, dict):
            return 0
        claimed = payload.get("preview_sha256")
        unsigned = {
            key: item for key, item in payload.items() if key != "preview_sha256"
        }
        if not isinstance(claimed, str) or claimed != sha256_text(
            canonical_json(unsigned)
        ):
            return 0
        emails = payload.get("emails")
        report_sources = payload.get("report_sources")
        schedule = payload.get("schedule")
        if (
            payload.get("schema_version") != "m10_external_preview_v1"
            or payload.get("status") != "awaiting_user_confirmation"
            or payload.get("email_retention") != "keep"
            or not isinstance(emails, list)
            or len(emails) != 8
            or not isinstance(report_sources, list)
            or len(report_sources) != 8
            or not isinstance(schedule, list)
            or not 1 <= len(schedule) <= 4
            or payload.get("gmail_send_budget") != 8
            or payload.get("gmail_tool_call_budget") != 26
            or payload.get("garmin_workout_budget") != 4
            or payload.get("garmin_tool_call_budget") != 20
            or payload.get("sites_calls") != 0
            or payload.get("cron_calls") != 0
            or not isinstance(payload.get("training_plan_output_id"), int)
            or isinstance(payload.get("training_plan_output_id"), bool)
            or int(payload.get("training_plan_output_id", 0)) <= 0
            or re.fullmatch(
                r"[0-9a-f]{64}",
                str(payload.get("training_plan_output_sha256", "")),
            )
            is None
        ):
            return 0
        markers: set[str] = set()
        email_output_ids: set[int] = set()
        recipients: set[str] = set()
        for email in emails:
            if not isinstance(email, dict):
                return 0
            marker = email.get("marker")
            request_sha = email.get("request_sha256")
            output_id = email.get("source_output_id")
            output_sha = email.get("source_output_sha256")
            subject = email.get("subject")
            verification_query = email.get("verification_query")
            recipient = email.get("recipient")
            recipient_sha = email.get("recipient_sha256")
            local = r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
            label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
            if (
                not isinstance(marker, str)
                or not marker
                or marker in markers
                or not isinstance(request_sha, str)
                or re.fullmatch(r"[0-9a-f]{64}", request_sha) is None
                or not isinstance(output_id, int)
                or isinstance(output_id, bool)
                or output_id <= 0
                or output_id in email_output_ids
                or not isinstance(output_sha, str)
                or re.fullmatch(r"[0-9a-f]{64}", output_sha) is None
                or not isinstance(recipient, str)
                or recipient != recipient.strip()
                or len(recipient) > 254
                or re.fullmatch(rf"{local}@{label}(?:\.{label})+", recipient) is None
                or not isinstance(recipient_sha, str)
                or recipient_sha != sha256_text(recipient)
                or (
                    (subject is not None or verification_query is not None)
                    and (
                        not isinstance(subject, str)
                        or not subject
                        or '"' in subject
                        or "\\" in subject
                        or verification_query != f'subject:"{subject}"'
                    )
                )
            ):
                return 0
            markers.add(marker)
            email_output_ids.add(output_id)
            recipients.add(recipient)
        if len(recipients) != 1:
            return 0
        expected_reports = [
            ("daily", f"2026-08-{day:02d}") for day in range(12, 19)
        ] + [("weekly", "2026-08-18")]
        source_output_ids: set[int] = set()
        report_email_ids: set[int] = set()
        for report, email, expected in zip(
            report_sources, emails, expected_reports, strict=True
        ):
            if not isinstance(report, dict):
                return 0
            source_id = report.get("source_output_id")
            email_id = report.get("email_output_id")
            if (
                (report.get("mode"), report.get("target")) != expected
                or not isinstance(source_id, int)
                or isinstance(source_id, bool)
                or source_id <= 0
                or source_id in source_output_ids
                or not isinstance(email_id, int)
                or isinstance(email_id, bool)
                or email_id <= 0
                or email_id in report_email_ids
                or email_id not in email_output_ids
                or not isinstance(email, dict)
                or email.get("source_output_id") != email_id
                or email.get("source_output_sha256")
                != report.get("email_output_sha256")
                or re.fullmatch(
                    r"[0-9a-f]{64}", str(report.get("source_output_sha256", ""))
                )
                is None
                or re.fullmatch(
                    r"[0-9a-f]{64}", str(report.get("email_output_sha256", ""))
                )
                is None
            ):
                return 0
            source_output_ids.add(source_id)
            report_email_ids.add(email_id)
        if report_email_ids != email_output_ids:
            return 0
        names: set[str] = set()
        required_phases = {
            "create",
            "verify_created",
            "schedule",
            "verify_scheduled",
            "unschedule",
            "verify_absent_after_unschedule",
            "delete",
            "verify_absent_after_delete",
        }
        for course in schedule:
            if not isinstance(course, dict):
                return 0
            name = course.get("name")
            day = course.get("date")
            hashes = course.get("action_request_sha256")
            if (
                not isinstance(name, str)
                or not name.endswith("-E2E-20260818-GTS")
                or name in names
                or not isinstance(day, str)
                or day < "2026-08-19"
                or day > "2026-08-25"
                or not isinstance(course.get("workout_data"), dict)
                or not isinstance(hashes, dict)
                or set(hashes) != required_phases
                or any(
                    not isinstance(item, str)
                    or re.fullmatch(r"[0-9a-f]{64}", item) is None
                    for item in hashes.values()
                )
            ):
                return 0
            names.add(name)
        return 1
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0


def _valid_m10_mcp_request(manifest_value: object, preview_value: object) -> int:
    """Validate the complete M10 MCP envelope and its bounded tool request."""
    try:
        manifest = json.loads(str(manifest_value))
        preview = json.loads(str(preview_value))
        if not isinstance(manifest, dict) or not isinstance(preview, dict):
            return 0
        required_manifest = {
            "m10_role",
            "provider",
            "tool_name",
            "request_json",
            "request_sha256",
            "preview_output_id",
            "preview_output_sha256",
            "preview_sha256",
            "external_action_ids",
        }
        reconciliation_fields = {"reconciliation_mode", "prior_run_id"}
        if set(manifest) not in {
            frozenset(required_manifest),
            frozenset(required_manifest | reconciliation_fields),
        }:
            return 0
        provider = manifest.get("provider")
        tool = manifest.get("tool_name")
        request = manifest.get("request_json")
        action_ids = manifest.get("external_action_ids")
        if (
            manifest.get("m10_role") != "m10_external_mcp_call_v1"
            or provider not in {"gmail", "garmin"}
            or not isinstance(request, dict)
            or not isinstance(action_ids, list)
            or any(
                not isinstance(item, int) or isinstance(item, bool) or item <= 0
                for item in action_ids
            )
            or len(action_ids) != len(set(action_ids))
        ):
            return 0
        if provider == "gmail":
            if tool == "send_email":
                return int(
                    len(action_ids) == 1
                    and bool(request)
                    and not reconciliation_fields.intersection(manifest)
                )
            if tool != "search_emails" or len(action_ids) != 1:
                return 0
            if reconciliation_fields.intersection(manifest) and (
                manifest.get("reconciliation_mode")
                != "user_approved_result_unpersisted"
                or not isinstance(manifest.get("prior_run_id"), int)
                or isinstance(manifest.get("prior_run_id"), bool)
                or int(manifest["prior_run_id"]) <= 0
            ):
                return 0
            if set(request) != {"query", "maxResults"}:
                return 0
            query = request.get("query")
            maximum = request.get("maxResults")
            queries = {
                item.get("verification_query")
                for item in preview.get("emails", [])
                if isinstance(item, dict)
                and isinstance(item.get("verification_query"), str)
            }
            return int(
                isinstance(query, str)
                and query in queries
                and isinstance(maximum, int)
                and not isinstance(maximum, bool)
                and maximum == 10
            )
        if tool == "get_workouts":
            return int(not request and not action_ids)
        if tool == "get_scheduled_workouts":
            return int(
                not action_ids
                and request == {"start_date": "2026-08-19", "end_date": "2026-08-25"}
            )
        if tool == "get_workout_by_id":
            return int(
                len(action_ids) == 1
                and set(request) == {"workout_id"}
                and isinstance(request.get("workout_id"), (int, str))
                and not isinstance(request.get("workout_id"), bool)
                and str(request.get("workout_id")) != ""
            )
        single_shapes = {
            "upload_workout": {"workout_data"},
            "schedule_workout": {"workout_id", "calendar_date"},
            "unschedule_workout": {"scheduled_workout_id"},
            "delete_workout": {"workout_id"},
        }
        if tool in single_shapes:
            return int(len(action_ids) == 1 and set(request) == single_shapes[tool])
        array_shapes = {
            "upload_workouts": ("workouts", None),
            "schedule_workouts": (
                "schedules",
                {"workout_id", "calendar_date"},
            ),
            "unschedule_workouts": ("scheduled_workout_ids", None),
            "delete_workouts": ("workout_ids", None),
        }
        if tool not in array_shapes or not 1 <= len(action_ids) <= 4:
            return 0
        key, member_keys = array_shapes[tool]
        members = request.get(key)
        if set(request) != {key} or not isinstance(members, list):
            return 0
        if len(members) != len(action_ids):
            return 0
        if member_keys is not None and any(
            not isinstance(item, dict) or set(item) != member_keys for item in members
        ):
            return 0
        return 1
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0


def _output_sha(
    title: object,
    content_json: object,
    content_text: object,
    content_html: object,
    lineage_json: object,
) -> str:
    try:
        parsed_json = (
            json.loads(str(content_json)) if content_json is not None else None
        )
        parsed_lineage = json.loads(str(lineage_json))
    except (TypeError, json.JSONDecodeError):
        return ""
    return sha256_text(
        canonical_json(
            {
                "title": title,
                "json": parsed_json,
                "text": content_text,
                "html": content_html,
                "lineage": parsed_lineage,
            }
        )
    )


def source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def state_path(root: Path | None = None) -> Path:
    return (root or source_root()) / "state" / "trainlab.db"


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS skill_runs (
  id INTEGER PRIMARY KEY,
  run_key TEXT NOT NULL UNIQUE,
  workflow_key TEXT NOT NULL,
  dedupe_key TEXT NOT NULL,
  parent_run_id INTEGER REFERENCES skill_runs(id) ON DELETE RESTRICT,
  skill_name TEXT NOT NULL CHECK (skill_name IN (
    'garmin-sync','training-coach','weekly-fitness-summary',
    'garmin-training-sender','training-report-publisher','gmail-sender'
  )),
  operation TEXT NOT NULL CHECK (operation IN (
    'index_existing_raw','daily_sync','manual_backfill','reconcile_sync',
    'daily_coach','weekly_coach','validate_plan','summarize_week',
    'apply_weekly_plan','reconcile_garmin','adopt_existing_workout',
    'render_daily','render_weekly','publish_sites','reconcile_sites',
    'send_email','query_email','reconcile_gmail','mcp_tool_call'
  )),
  trigger_kind TEXT NOT NULL CHECK (trigger_kind IN ('cron_daily','cron_weekly','manual','recovery','skill')),
  target_from_date TEXT CHECK (target_from_date IS NULL OR (length(target_from_date)=10 AND target_from_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(target_from_date)=target_from_date)),
  target_through_date TEXT CHECK (target_through_date IS NULL OR (length(target_through_date)=10 AND target_through_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(target_through_date)=target_through_date)),
  attempt_no INTEGER NOT NULL CHECK (attempt_no >= 1),
  input_manifest_json TEXT NOT NULL CHECK (json_valid(input_manifest_json)),
  input_sha256 TEXT NOT NULL CHECK (length(input_sha256)=64 AND input_sha256 NOT GLOB '*[^0-9a-f]*'),
  status TEXT NOT NULL CHECK (status IN ('pending','running','succeeded','failed','blocked','interrupted','cancelled')),
  created_at_utc TEXT NOT NULL CHECK (length(created_at_utc)=20 AND substr(created_at_utc,11,1)='T' AND substr(created_at_utc,20,1)='Z' AND datetime(substr(created_at_utc,1,19))=replace(substr(created_at_utc,1,19),'T',' ')),
  started_at_utc TEXT CHECK (started_at_utc IS NULL OR (length(started_at_utc)=20 AND substr(started_at_utc,11,1)='T' AND substr(started_at_utc,20,1)='Z' AND datetime(substr(started_at_utc,1,19))=replace(substr(started_at_utc,1,19),'T',' '))),
  heartbeat_at_utc TEXT CHECK (heartbeat_at_utc IS NULL OR (length(heartbeat_at_utc)=20 AND substr(heartbeat_at_utc,11,1)='T' AND substr(heartbeat_at_utc,20,1)='Z' AND datetime(substr(heartbeat_at_utc,1,19))=replace(substr(heartbeat_at_utc,1,19),'T',' '))),
  lease_expires_at_utc TEXT CHECK (lease_expires_at_utc IS NULL OR (length(lease_expires_at_utc)=20 AND substr(lease_expires_at_utc,11,1)='T' AND substr(lease_expires_at_utc,20,1)='Z' AND datetime(substr(lease_expires_at_utc,1,19))=replace(substr(lease_expires_at_utc,1,19),'T',' '))),
  finished_at_utc TEXT CHECK (finished_at_utc IS NULL OR (length(finished_at_utc)=20 AND substr(finished_at_utc,11,1)='T' AND substr(finished_at_utc,20,1)='Z' AND datetime(substr(finished_at_utc,1,19))=replace(substr(finished_at_utc,1,19),'T',' '))),
  error_code TEXT,
  error_summary TEXT,
  UNIQUE(dedupe_key, attempt_no)
) STRICT;
CREATE TABLE IF NOT EXISTS activity_inventory (
  id INTEGER PRIMARY KEY,
  provider TEXT NOT NULL,
  provider_activity_id TEXT NOT NULL,
  activity_hash TEXT NOT NULL CHECK (length(activity_hash)=64 AND activity_hash NOT GLOB '*[^0-9a-f]*'),
  activity_hash_version TEXT NOT NULL CHECK (activity_hash_version='provider-nul-id-sha256-v1'),
  activity_date TEXT NOT NULL CHECK (length(activity_date)=10 AND activity_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(activity_date)=activity_date),
  expected_formats_json TEXT NOT NULL CHECK (json_valid(expected_formats_json)),
  collection_state TEXT NOT NULL CHECK (collection_state IN ('discovered','collecting','complete','incomplete','failed')),
  weather_state TEXT NOT NULL CHECK (weather_state IN ('not_requested','pending','complete','incomplete','not_available')),
  collection_policy_version TEXT NOT NULL,
  first_seen_at_utc TEXT NOT NULL CHECK (length(first_seen_at_utc)=20 AND substr(first_seen_at_utc,11,1)='T' AND substr(first_seen_at_utc,20,1)='Z' AND datetime(substr(first_seen_at_utc,1,19))=replace(substr(first_seen_at_utc,1,19),'T',' ')),
  last_seen_at_utc TEXT NOT NULL CHECK (length(last_seen_at_utc)=20 AND substr(last_seen_at_utc,11,1)='T' AND substr(last_seen_at_utc,20,1)='Z' AND datetime(substr(last_seen_at_utc,1,19))=replace(substr(last_seen_at_utc,1,19),'T',' ')),
  last_collection_at_utc TEXT CHECK (last_collection_at_utc IS NULL OR (length(last_collection_at_utc)=20 AND substr(last_collection_at_utc,11,1)='T' AND substr(last_collection_at_utc,20,1)='Z' AND datetime(substr(last_collection_at_utc,1,19))=replace(substr(last_collection_at_utc,1,19),'T',' '))),
  discovered_by_run_id INTEGER NOT NULL REFERENCES skill_runs(id) ON DELETE RESTRICT,
  last_collection_run_id INTEGER REFERENCES skill_runs(id) ON DELETE RESTRICT,
  last_error_code TEXT,
  updated_at_utc TEXT NOT NULL CHECK (length(updated_at_utc)=20 AND substr(updated_at_utc,11,1)='T' AND substr(updated_at_utc,20,1)='Z' AND datetime(substr(updated_at_utc,1,19))=replace(substr(updated_at_utc,1,19),'T',' ')),
  UNIQUE(provider, provider_activity_id),
  UNIQUE(provider, activity_hash)
) STRICT;
CREATE TABLE IF NOT EXISTS raw_files (
  id INTEGER PRIMARY KEY,
  provider TEXT NOT NULL,
  data_class TEXT NOT NULL CHECK (data_class IN ('health','activity')),
  resource_kind TEXT NOT NULL,
  logical_key TEXT NOT NULL,
  revision_no INTEGER NOT NULL CHECK (revision_no >= 1),
  supersedes_raw_file_id INTEGER REFERENCES raw_files(id) ON DELETE RESTRICT,
  activity_inventory_id INTEGER REFERENCES activity_inventory(id) ON DELETE RESTRICT,
  activity_binding_state TEXT NOT NULL CHECK (
    activity_binding_state IN ('not_applicable','unresolved','bound')
    AND (
      (data_class='health' AND activity_binding_state='not_applicable'
       AND activity_inventory_id IS NULL AND bound_by_run_id IS NULL AND binding_evidence_json IS NULL)
      OR
      (data_class='activity' AND (
        (activity_binding_state='unresolved' AND activity_inventory_id IS NULL
         AND bound_by_run_id IS NULL AND binding_evidence_json IS NULL)
        OR
        (activity_binding_state='bound' AND activity_inventory_id IS NOT NULL
         AND bound_by_run_id IS NOT NULL AND binding_evidence_json IS NOT NULL)
      ))
    )
  ),
  bound_by_run_id INTEGER REFERENCES skill_runs(id) ON DELETE RESTRICT,
  binding_evidence_json TEXT CHECK (binding_evidence_json IS NULL OR json_valid(binding_evidence_json)),
  data_date TEXT NOT NULL CHECK (length(data_date)=10 AND data_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(data_date)=data_date),
  relative_path TEXT NOT NULL UNIQUE,
  file_format TEXT NOT NULL CHECK (file_format IN ('json','fit','gpx','tcx')),
  byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
  sha256 TEXT NOT NULL CHECK (length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
  registered_by_run_id INTEGER NOT NULL REFERENCES skill_runs(id) ON DELETE RESTRICT,
  integrity_state TEXT NOT NULL CHECK (integrity_state IN ('verified','missing','hash_mismatch','quarantined')),
  captured_at_utc TEXT CHECK (captured_at_utc IS NULL OR (length(captured_at_utc)=20 AND substr(captured_at_utc,11,1)='T' AND substr(captured_at_utc,20,1)='Z' AND datetime(substr(captured_at_utc,1,19))=replace(substr(captured_at_utc,1,19),'T',' '))),
  registered_at_utc TEXT NOT NULL CHECK (length(registered_at_utc)=20 AND substr(registered_at_utc,11,1)='T' AND substr(registered_at_utc,20,1)='Z' AND datetime(substr(registered_at_utc,1,19))=replace(substr(registered_at_utc,1,19),'T',' ')),
  last_verified_at_utc TEXT NOT NULL CHECK (length(last_verified_at_utc)=20 AND substr(last_verified_at_utc,11,1)='T' AND substr(last_verified_at_utc,20,1)='Z' AND datetime(substr(last_verified_at_utc,1,19))=replace(substr(last_verified_at_utc,1,19),'T',' ')),
  UNIQUE(logical_key, revision_no),
  UNIQUE(logical_key, sha256),
  UNIQUE(supersedes_raw_file_id),
  CHECK (revision_no=1 OR supersedes_raw_file_id IS NOT NULL)
) STRICT;
CREATE TABLE IF NOT EXISTS skill_outputs (
  id INTEGER PRIMARY KEY,
  skill_run_id INTEGER NOT NULL REFERENCES skill_runs(id) ON DELETE RESTRICT,
  output_kind TEXT NOT NULL CHECK (output_kind IN (
    'sync_summary','bounded_evidence','daily_summary','weekly_fitness_review','weekly_summary','training_plan',
    'report_artifact','email_render','garmin_workout_contract','execution_summary'
  )),
  logical_key TEXT NOT NULL,
  revision_no INTEGER NOT NULL CHECK (revision_no >= 1),
  supersedes_output_id INTEGER REFERENCES skill_outputs(id) ON DELETE RESTRICT,
  period_start_date TEXT CHECK (period_start_date IS NULL OR (length(period_start_date)=10 AND period_start_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(period_start_date)=period_start_date)),
  period_end_date TEXT CHECK (period_end_date IS NULL OR (length(period_end_date)=10 AND period_end_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(period_end_date)=period_end_date)),
  schema_name TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  title_text TEXT,
  content_json TEXT CHECK (content_json IS NULL OR json_valid(content_json)),
  content_text TEXT,
  content_html TEXT,
  lineage_json TEXT NOT NULL CHECK (json_valid(lineage_json) AND json_type(lineage_json)='array'),
  content_sha256 TEXT NOT NULL CHECK (length(content_sha256)=64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'),
  created_at_utc TEXT NOT NULL CHECK (length(created_at_utc)=20 AND substr(created_at_utc,11,1)='T' AND substr(created_at_utc,20,1)='Z' AND datetime(substr(created_at_utc,1,19))=replace(substr(created_at_utc,1,19),'T',' ')),
  CHECK (content_json IS NOT NULL OR content_text IS NOT NULL OR content_html IS NOT NULL),
  CHECK (
    output_kind NOT IN ('daily_summary','weekly_summary')
    OR (content_json IS NOT NULL AND content_text IS NOT NULL)
  ),
  CHECK (
    output_kind NOT IN ('report_artifact','email_render')
    OR (content_json IS NOT NULL AND content_text IS NOT NULL AND content_html IS NOT NULL)
  ),
  UNIQUE(logical_key, revision_no),
  UNIQUE(logical_key, content_sha256),
  UNIQUE(supersedes_output_id),
  CHECK (revision_no=1 OR supersedes_output_id IS NOT NULL)
) STRICT;
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY,
  approval_key TEXT NOT NULL UNIQUE,
  recorded_by_run_id INTEGER REFERENCES skill_runs(id) ON DELETE RESTRICT,
  candidate_output_id INTEGER REFERENCES skill_outputs(id) ON DELETE RESTRICT,
  candidate_output_sha256 TEXT CHECK (candidate_output_sha256 IS NULL OR (length(candidate_output_sha256)=64 AND candidate_output_sha256 NOT GLOB '*[^0-9a-f]*')),
  authority_approval_id INTEGER REFERENCES approvals(id) ON DELETE RESTRICT,
  supersedes_approval_id INTEGER REFERENCES approvals(id) ON DELETE RESTRICT,
  authority_kind TEXT NOT NULL CHECK (authority_kind IN ('user_explicit','scheduled_ai')),
  decision TEXT NOT NULL CHECK (decision IN ('approved','rejected','revoked')),
  scope_kind TEXT NOT NULL CHECK (scope_kind IN ('cron','plan','garmin','gmail','sites')),
  scope_json TEXT NOT NULL CHECK (
    json_valid(scope_json)
    AND json_type(scope_json)='object'
    AND json_type(scope_json,'$.provider')='text'
    AND json_type(scope_json,'$.action_kind')='text'
    AND json_type(scope_json,'$.entity_kind')='text'
    AND json_type(scope_json,'$.target_key')='text'
    AND json_type(scope_json,'$.scope_kind')='text'
    AND json_extract(scope_json,'$.scope_kind')=scope_kind
    AND json_type(scope_json,'$.budget')='object'
  ),
  scope_sha256 TEXT NOT NULL CHECK (length(scope_sha256)=64 AND scope_sha256 NOT GLOB '*[^0-9a-f]*'),
  source_ref TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  decided_at_utc TEXT NOT NULL CHECK (length(decided_at_utc)=20 AND substr(decided_at_utc,11,1)='T' AND substr(decided_at_utc,20,1)='Z' AND datetime(substr(decided_at_utc,1,19))=replace(substr(decided_at_utc,1,19),'T',' ')),
  valid_from_utc TEXT NOT NULL CHECK (length(valid_from_utc)=20 AND substr(valid_from_utc,11,1)='T' AND substr(valid_from_utc,20,1)='Z' AND datetime(substr(valid_from_utc,1,19))=replace(substr(valid_from_utc,1,19),'T',' ')),
  valid_until_utc TEXT CHECK (valid_until_utc IS NULL OR (length(valid_until_utc)=20 AND substr(valid_until_utc,11,1)='T' AND substr(valid_until_utc,20,1)='Z' AND datetime(substr(valid_until_utc,1,19))=replace(substr(valid_until_utc,1,19),'T',' '))),
  CHECK ((candidate_output_id IS NULL) = (candidate_output_sha256 IS NULL)),
  CHECK (decision <> 'revoked' OR supersedes_approval_id IS NOT NULL),
  CHECK (
    COALESCE(json_type(scope_json,'$.budget.max_actions'),'')='integer'
    AND COALESCE(json_extract(scope_json,'$.budget.max_actions'),0) >= 1
  ),
  CHECK (authority_kind <> 'scheduled_ai' OR (
    candidate_output_id IS NOT NULL AND authority_approval_id IS NOT NULL
  ))
) STRICT;
CREATE TABLE IF NOT EXISTS external_actions (
  id INTEGER PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  skill_run_id INTEGER NOT NULL REFERENCES skill_runs(id) ON DELETE RESTRICT,
  provider TEXT NOT NULL CHECK (provider IN ('gmail','garmin','sites')),
  entity_kind TEXT NOT NULL CHECK (entity_kind IN ('email','workout','calendar_entry','site_snapshot')),
  action_kind TEXT NOT NULL CHECK (action_kind IN (
    'gmail_send','sites_publish','garmin_workout_adopt','garmin_workout_create',
    'garmin_workout_verify','garmin_calendar_schedule','garmin_calendar_unschedule',
    'garmin_workout_delete'
  )),
  source_output_id INTEGER NOT NULL REFERENCES skill_outputs(id) ON DELETE RESTRICT,
  source_output_sha256 TEXT NOT NULL CHECK (length(source_output_sha256)=64 AND source_output_sha256 NOT GLOB '*[^0-9a-f]*'),
  approval_id INTEGER NOT NULL REFERENCES approvals(id) ON DELETE RESTRICT,
  related_action_id INTEGER REFERENCES external_actions(id) ON DELETE RESTRICT,
  target_key TEXT NOT NULL,
  target_external_id TEXT,
  result_external_id TEXT,
  provider_object_name TEXT,
  provider_marker TEXT,
  request_json TEXT NOT NULL CHECK (json_valid(request_json)),
  request_sha256 TEXT NOT NULL CHECK (length(request_sha256)=64 AND request_sha256 NOT GLOB '*[^0-9a-f]*'),
  status TEXT NOT NULL CHECK (status IN ('prepared','in_progress','succeeded','already_done','failed_safe','unknown','cancelled')),
  attempt_count INTEGER NOT NULL CHECK (attempt_count >= 0),
  prepared_at_utc TEXT NOT NULL CHECK (length(prepared_at_utc)=20 AND substr(prepared_at_utc,11,1)='T' AND substr(prepared_at_utc,20,1)='Z' AND datetime(substr(prepared_at_utc,1,19))=replace(substr(prepared_at_utc,1,19),'T',' ')),
  started_at_utc TEXT CHECK (started_at_utc IS NULL OR (length(started_at_utc)=20 AND substr(started_at_utc,11,1)='T' AND substr(started_at_utc,20,1)='Z' AND datetime(substr(started_at_utc,1,19))=replace(substr(started_at_utc,1,19),'T',' '))),
  finished_at_utc TEXT CHECK (finished_at_utc IS NULL OR (length(finished_at_utc)=20 AND substr(finished_at_utc,11,1)='T' AND substr(finished_at_utc,20,1)='Z' AND datetime(substr(finished_at_utc,1,19))=replace(substr(finished_at_utc,1,19),'T',' '))),
  last_reconciled_at_utc TEXT CHECK (last_reconciled_at_utc IS NULL OR (length(last_reconciled_at_utc)=20 AND substr(last_reconciled_at_utc,11,1)='T' AND substr(last_reconciled_at_utc,20,1)='Z' AND datetime(substr(last_reconciled_at_utc,1,19))=replace(substr(last_reconciled_at_utc,1,19),'T',' '))),
  response_summary_json TEXT CHECK (response_summary_json IS NULL OR json_valid(response_summary_json)),
  error_code TEXT,
  error_summary TEXT,
  CHECK (status NOT IN ('succeeded','already_done','failed_safe','cancelled') OR finished_at_utc IS NOT NULL)
) STRICT;
CREATE INDEX IF NOT EXISTS idx_skill_runs_dedupe ON skill_runs(dedupe_key, created_at_utc);
CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_runs_active_dedupe
  ON skill_runs(dedupe_key)
  WHERE status IN ('pending','running');
CREATE INDEX IF NOT EXISTS idx_skill_outputs_kind ON skill_outputs(output_kind, period_end_date);
CREATE INDEX IF NOT EXISTS idx_raw_files_date ON raw_files(data_class, data_date);
CREATE INDEX IF NOT EXISTS idx_actions_status ON external_actions(provider, status);
CREATE TRIGGER IF NOT EXISTS trg_external_action_approval_match_insert
BEFORE INSERT ON external_actions
BEGIN
  SELECT CASE
    WHEN (SELECT candidate_output_id FROM approvals WHERE id=NEW.approval_id) IS NULL
      OR (SELECT candidate_output_id FROM approvals WHERE id=NEW.approval_id) <> NEW.source_output_id
      OR (SELECT candidate_output_sha256 FROM approvals WHERE id=NEW.approval_id) <>
         (SELECT content_sha256 FROM skill_outputs WHERE id=NEW.source_output_id)
      OR NEW.source_output_sha256 <> (SELECT content_sha256 FROM skill_outputs WHERE id=NEW.source_output_id)
    THEN RAISE(ABORT, 'external_action_output_approval_mismatch')
  END;
END;
CREATE TRIGGER IF NOT EXISTS trg_external_action_approval_match_update
BEFORE UPDATE OF approval_id, source_output_id, source_output_sha256 ON external_actions
BEGIN
  SELECT CASE
    WHEN (SELECT candidate_output_id FROM approvals WHERE id=NEW.approval_id) IS NULL
      OR (SELECT candidate_output_id FROM approvals WHERE id=NEW.approval_id) <> NEW.source_output_id
      OR (SELECT candidate_output_sha256 FROM approvals WHERE id=NEW.approval_id) <>
         (SELECT content_sha256 FROM skill_outputs WHERE id=NEW.source_output_id)
      OR NEW.source_output_sha256 <> (SELECT content_sha256 FROM skill_outputs WHERE id=NEW.source_output_id)
    THEN RAISE(ABORT, 'external_action_output_approval_mismatch')
  END;
END;
CREATE TRIGGER IF NOT EXISTS trg_approval_output_match_insert
BEFORE INSERT ON approvals
WHEN NEW.candidate_output_id IS NOT NULL
BEGIN
  SELECT CASE
    WHEN NEW.candidate_output_sha256 <> (SELECT content_sha256 FROM skill_outputs WHERE id=NEW.candidate_output_id)
    THEN RAISE(ABORT, 'approval_output_sha256_mismatch')
  END;
END;
CREATE TRIGGER IF NOT EXISTS trg_approval_output_match_update
BEFORE UPDATE OF candidate_output_id, candidate_output_sha256 ON approvals
WHEN NEW.candidate_output_id IS NOT NULL
BEGIN
  SELECT CASE
    WHEN NEW.candidate_output_sha256 <> (SELECT content_sha256 FROM skill_outputs WHERE id=NEW.candidate_output_id)
    THEN RAISE(ABORT, 'approval_output_sha256_mismatch')
  END;
END;
CREATE TRIGGER IF NOT EXISTS trg_raw_revision_lineage_insert
BEFORE INSERT ON raw_files
WHEN NEW.supersedes_raw_file_id IS NOT NULL
BEGIN
  SELECT CASE
    WHEN (SELECT logical_key FROM raw_files WHERE id=NEW.supersedes_raw_file_id) IS NULL
      OR (SELECT logical_key FROM raw_files WHERE id=NEW.supersedes_raw_file_id) <> NEW.logical_key
      OR (SELECT revision_no FROM raw_files WHERE id=NEW.supersedes_raw_file_id) + 1 <> NEW.revision_no
    THEN RAISE(ABORT, 'raw_revision_lineage_mismatch')
  END;
END;
CREATE TRIGGER IF NOT EXISTS trg_raw_revision_lineage_update
BEFORE UPDATE OF logical_key, revision_no, supersedes_raw_file_id ON raw_files
WHEN NEW.supersedes_raw_file_id IS NOT NULL
BEGIN
  SELECT CASE
    WHEN (SELECT logical_key FROM raw_files WHERE id=NEW.supersedes_raw_file_id) IS NULL
      OR (SELECT logical_key FROM raw_files WHERE id=NEW.supersedes_raw_file_id) <> NEW.logical_key
      OR (SELECT revision_no FROM raw_files WHERE id=NEW.supersedes_raw_file_id) + 1 <> NEW.revision_no
    THEN RAISE(ABORT, 'raw_revision_lineage_mismatch')
  END;
END;
CREATE TRIGGER IF NOT EXISTS trg_output_revision_lineage_insert
BEFORE INSERT ON skill_outputs
WHEN NEW.supersedes_output_id IS NOT NULL
BEGIN
  SELECT CASE
    WHEN (SELECT logical_key FROM skill_outputs WHERE id=NEW.supersedes_output_id) IS NULL
      OR (SELECT logical_key FROM skill_outputs WHERE id=NEW.supersedes_output_id) <> NEW.logical_key
      OR (SELECT revision_no FROM skill_outputs WHERE id=NEW.supersedes_output_id) + 1 <> NEW.revision_no
    THEN RAISE(ABORT, 'output_revision_lineage_mismatch')
  END;
END;
CREATE TRIGGER IF NOT EXISTS trg_output_revision_lineage_update
BEFORE UPDATE OF logical_key, revision_no, supersedes_output_id ON skill_outputs
WHEN NEW.supersedes_output_id IS NOT NULL
BEGIN
  SELECT CASE
    WHEN (SELECT logical_key FROM skill_outputs WHERE id=NEW.supersedes_output_id) IS NULL
      OR (SELECT logical_key FROM skill_outputs WHERE id=NEW.supersedes_output_id) <> NEW.logical_key
      OR (SELECT revision_no FROM skill_outputs WHERE id=NEW.supersedes_output_id) + 1 <> NEW.revision_no
    THEN RAISE(ABORT, 'output_revision_lineage_mismatch')
  END;
END;
CREATE TRIGGER IF NOT EXISTS trg_external_action_approved_insert
BEFORE INSERT ON external_actions
WHEN (SELECT decision FROM approvals WHERE id=NEW.approval_id) <> 'approved'
BEGIN
  SELECT RAISE(ABORT, 'external_action_requires_approved_decision');
END;
CREATE TRIGGER IF NOT EXISTS trg_external_action_approved_update
BEFORE UPDATE OF approval_id ON external_actions
WHEN (SELECT decision FROM approvals WHERE id=NEW.approval_id) <> 'approved'
BEGIN
  SELECT RAISE(ABORT, 'external_action_requires_approved_decision');
END;
CREATE TRIGGER IF NOT EXISTS trg_activity_hash_insert
BEFORE INSERT ON activity_inventory
WHEN NEW.activity_hash <> lower(trainlab_sha256(NEW.provider || char(31) || NEW.provider_activity_id))
BEGIN
  SELECT RAISE(ABORT, 'activity_hash_mismatch');
END;
CREATE TRIGGER IF NOT EXISTS trg_activity_hash_update
BEFORE UPDATE OF provider, provider_activity_id, activity_hash ON activity_inventory
WHEN NEW.activity_hash <> lower(trainlab_sha256(NEW.provider || char(31) || NEW.provider_activity_id))
BEGIN
  SELECT RAISE(ABORT, 'activity_hash_mismatch');
END;
CREATE TRIGGER IF NOT EXISTS trg_temporal_skill_runs_insert
BEFORE INSERT ON skill_runs
WHEN trainlab_valid_date(NEW.target_from_date)=0
  OR trainlab_valid_date(NEW.target_through_date)=0
  OR trainlab_valid_utc(NEW.created_at_utc)=0
  OR trainlab_valid_utc(NEW.started_at_utc)=0
  OR trainlab_valid_utc(NEW.heartbeat_at_utc)=0
  OR trainlab_valid_utc(NEW.lease_expires_at_utc)=0
  OR trainlab_valid_utc(NEW.finished_at_utc)=0
BEGIN
  SELECT RAISE(ABORT, 'skill_run_temporal_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_temporal_skill_runs_update
BEFORE UPDATE ON skill_runs
WHEN trainlab_valid_date(NEW.target_from_date)=0
  OR trainlab_valid_date(NEW.target_through_date)=0
  OR trainlab_valid_utc(NEW.created_at_utc)=0
  OR trainlab_valid_utc(NEW.started_at_utc)=0
  OR trainlab_valid_utc(NEW.heartbeat_at_utc)=0
  OR trainlab_valid_utc(NEW.lease_expires_at_utc)=0
  OR trainlab_valid_utc(NEW.finished_at_utc)=0
BEGIN
  SELECT RAISE(ABORT, 'skill_run_temporal_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_temporal_activity_insert
BEFORE INSERT ON activity_inventory
WHEN trainlab_valid_date(NEW.activity_date)=0
  OR trainlab_valid_utc(NEW.first_seen_at_utc)=0
  OR trainlab_valid_utc(NEW.last_seen_at_utc)=0
  OR trainlab_valid_utc(NEW.last_collection_at_utc)=0
  OR trainlab_valid_utc(NEW.updated_at_utc)=0
BEGIN
  SELECT RAISE(ABORT, 'activity_temporal_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_temporal_activity_update
BEFORE UPDATE ON activity_inventory
WHEN trainlab_valid_date(NEW.activity_date)=0
  OR trainlab_valid_utc(NEW.first_seen_at_utc)=0
  OR trainlab_valid_utc(NEW.last_seen_at_utc)=0
  OR trainlab_valid_utc(NEW.last_collection_at_utc)=0
  OR trainlab_valid_utc(NEW.updated_at_utc)=0
BEGIN
  SELECT RAISE(ABORT, 'activity_temporal_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_temporal_raw_insert
BEFORE INSERT ON raw_files
WHEN trainlab_valid_date(NEW.data_date)=0
  OR trainlab_valid_utc(NEW.captured_at_utc)=0
  OR trainlab_valid_utc(NEW.registered_at_utc)=0
  OR trainlab_valid_utc(NEW.last_verified_at_utc)=0
BEGIN
  SELECT RAISE(ABORT, 'raw_temporal_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_temporal_raw_update
BEFORE UPDATE ON raw_files
WHEN trainlab_valid_date(NEW.data_date)=0
  OR trainlab_valid_utc(NEW.captured_at_utc)=0
  OR trainlab_valid_utc(NEW.registered_at_utc)=0
  OR trainlab_valid_utc(NEW.last_verified_at_utc)=0
BEGIN
  SELECT RAISE(ABORT, 'raw_temporal_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_temporal_output_insert
BEFORE INSERT ON skill_outputs
WHEN trainlab_valid_date(NEW.period_start_date)=0
  OR trainlab_valid_date(NEW.period_end_date)=0
  OR trainlab_valid_utc(NEW.created_at_utc)=0
BEGIN
  SELECT RAISE(ABORT, 'output_temporal_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_temporal_output_update
BEFORE UPDATE ON skill_outputs
WHEN trainlab_valid_date(NEW.period_start_date)=0
  OR trainlab_valid_date(NEW.period_end_date)=0
  OR trainlab_valid_utc(NEW.created_at_utc)=0
BEGIN
  SELECT RAISE(ABORT, 'output_temporal_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_temporal_approval_insert
BEFORE INSERT ON approvals
WHEN trainlab_valid_utc(NEW.decided_at_utc)=0
  OR trainlab_valid_utc(NEW.valid_from_utc)=0
  OR trainlab_valid_utc(NEW.valid_until_utc)=0
BEGIN
  SELECT RAISE(ABORT, 'approval_temporal_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_temporal_approval_update
BEFORE UPDATE ON approvals
WHEN trainlab_valid_utc(NEW.decided_at_utc)=0
  OR trainlab_valid_utc(NEW.valid_from_utc)=0
  OR trainlab_valid_utc(NEW.valid_until_utc)=0
BEGIN
  SELECT RAISE(ABORT, 'approval_temporal_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_temporal_action_insert
BEFORE INSERT ON external_actions
WHEN trainlab_valid_utc(NEW.prepared_at_utc)=0
  OR trainlab_valid_utc(NEW.started_at_utc)=0
  OR trainlab_valid_utc(NEW.finished_at_utc)=0
  OR trainlab_valid_utc(NEW.last_reconciled_at_utc)=0
BEGIN
  SELECT RAISE(ABORT, 'external_action_temporal_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_temporal_action_update
BEFORE UPDATE ON external_actions
WHEN trainlab_valid_utc(NEW.prepared_at_utc)=0
  OR trainlab_valid_utc(NEW.started_at_utc)=0
  OR trainlab_valid_utc(NEW.finished_at_utc)=0
  OR trainlab_valid_utc(NEW.last_reconciled_at_utc)=0
BEGIN
  SELECT RAISE(ABORT, 'external_action_temporal_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_approval_revoke_guard
BEFORE UPDATE OF decision, valid_until_utc, scope_json ON approvals
WHEN EXISTS (SELECT 1 FROM external_actions WHERE approval_id=NEW.id)
  AND (NEW.decision <> 'approved'
       OR (NEW.valid_until_utc IS NOT NULL
           AND (datetime(replace(NEW.valid_until_utc,'T',' ')) IS NULL
                OR datetime(replace(NEW.valid_until_utc,'T',' ')) <= datetime('now')))
       OR EXISTS (
         SELECT 1 FROM external_actions ea
         WHERE ea.approval_id=NEW.id
           AND json_extract(NEW.scope_json,'$.provider') IS NOT NULL
           AND json_extract(NEW.scope_json,'$.provider') <> ea.provider
       ))
BEGIN
  SELECT RAISE(ABORT, 'approval_in_use_cannot_revoke');
END;
CREATE TRIGGER IF NOT EXISTS trg_external_action_approval_scope_insert
BEFORE INSERT ON external_actions
WHEN (SELECT decision FROM approvals WHERE id=NEW.approval_id) <> 'approved'
  OR (SELECT valid_until_utc FROM approvals WHERE id=NEW.approval_id) IS NOT NULL
     AND (datetime(replace((SELECT valid_until_utc FROM approvals WHERE id=NEW.approval_id),'T',' ')) IS NULL
          OR datetime(replace((SELECT valid_until_utc FROM approvals WHERE id=NEW.approval_id),'T',' ')) <= datetime('now'))
  OR (SELECT json_extract(scope_json,'$.provider') FROM approvals WHERE id=NEW.approval_id) IS NOT NULL
     AND (SELECT json_extract(scope_json,'$.provider') FROM approvals WHERE id=NEW.approval_id) <> NEW.provider
BEGIN
  SELECT RAISE(ABORT, 'external_action_approval_scope_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_external_action_approval_scope_update
BEFORE UPDATE OF approval_id, provider ON external_actions
WHEN (SELECT decision FROM approvals WHERE id=NEW.approval_id) <> 'approved'
  OR (SELECT valid_until_utc FROM approvals WHERE id=NEW.approval_id) IS NOT NULL
     AND (datetime(replace((SELECT valid_until_utc FROM approvals WHERE id=NEW.approval_id),'T',' ')) IS NULL
          OR datetime(replace((SELECT valid_until_utc FROM approvals WHERE id=NEW.approval_id),'T',' ')) <= datetime('now'))
  OR (SELECT json_extract(scope_json,'$.provider') FROM approvals WHERE id=NEW.approval_id) IS NOT NULL
     AND (SELECT json_extract(scope_json,'$.provider') FROM approvals WHERE id=NEW.approval_id) <> NEW.provider
BEGIN
  SELECT RAISE(ABORT, 'external_action_approval_scope_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_raw_append_only_delete
BEFORE DELETE ON raw_files
BEGIN
  SELECT RAISE(ABORT, 'raw_files_append_only');
END;
CREATE TRIGGER IF NOT EXISTS trg_raw_append_only_update
BEFORE UPDATE ON raw_files
WHEN NOT (
  OLD.data_class='activity'
  AND OLD.activity_binding_state='unresolved'
  AND NEW.activity_binding_state='bound'
  AND OLD.id IS NEW.id
  AND OLD.provider IS NEW.provider
  AND OLD.resource_kind IS NEW.resource_kind
  AND OLD.logical_key IS NEW.logical_key
  AND OLD.revision_no IS NEW.revision_no
  AND OLD.supersedes_raw_file_id IS NEW.supersedes_raw_file_id
  AND OLD.data_date IS NEW.data_date
  AND OLD.relative_path IS NEW.relative_path
  AND OLD.file_format IS NEW.file_format
  AND OLD.byte_size IS NEW.byte_size
  AND OLD.sha256 IS NEW.sha256
  AND OLD.registered_by_run_id IS NEW.registered_by_run_id
  AND OLD.integrity_state IS NEW.integrity_state
  AND OLD.captured_at_utc IS NEW.captured_at_utc
  AND OLD.registered_at_utc IS NEW.registered_at_utc
  AND OLD.last_verified_at_utc IS NEW.last_verified_at_utc
  AND NEW.activity_inventory_id IS NOT NULL
  AND NEW.bound_by_run_id IS NOT NULL
  AND NEW.binding_evidence_json IS NOT NULL
)
BEGIN
  SELECT RAISE(ABORT, 'raw_files_append_only');
END;
CREATE TRIGGER IF NOT EXISTS trg_output_append_only_delete
BEFORE DELETE ON skill_outputs
BEGIN
  SELECT RAISE(ABORT, 'skill_outputs_append_only');
END;
CREATE TRIGGER IF NOT EXISTS trg_output_append_only_update
BEFORE UPDATE ON skill_outputs
BEGIN
  SELECT RAISE(ABORT, 'skill_outputs_append_only');
END;
CREATE TRIGGER IF NOT EXISTS trg_output_append_only_insert
BEFORE INSERT ON skill_outputs
WHEN EXISTS (
  SELECT 1 FROM skill_outputs
  WHERE logical_key=NEW.logical_key AND revision_no=NEW.revision_no
)
BEGIN
  SELECT RAISE(ABORT, 'skill_outputs_revision_exists');
END;
CREATE TRIGGER IF NOT EXISTS trg_raw_append_only_insert
BEFORE INSERT ON raw_files
WHEN EXISTS (
  SELECT 1 FROM raw_files
  WHERE logical_key=NEW.logical_key AND revision_no=NEW.revision_no
)
BEGIN
  SELECT RAISE(ABORT, 'raw_files_revision_exists');
END;
CREATE TRIGGER IF NOT EXISTS trg_approval_append_only_insert
BEFORE INSERT ON approvals
WHEN EXISTS (SELECT 1 FROM approvals WHERE approval_key=NEW.approval_key)
BEGIN
  SELECT RAISE(ABORT, 'approval_exists');
END;
CREATE TRIGGER IF NOT EXISTS trg_external_action_append_only_insert
BEFORE INSERT ON external_actions
WHEN EXISTS (SELECT 1 FROM external_actions WHERE idempotency_key=NEW.idempotency_key)
BEGIN
  SELECT RAISE(ABORT, 'external_action_exists');
END;
CREATE TRIGGER IF NOT EXISTS trg_skill_run_append_only_insert
BEFORE INSERT ON skill_runs
WHEN EXISTS (
  SELECT 1 FROM skill_runs
  WHERE run_key=NEW.run_key OR (dedupe_key=NEW.dedupe_key AND attempt_no=NEW.attempt_no)
)
BEGIN
  SELECT RAISE(ABORT, 'skill_run_exists');
END;
CREATE TRIGGER IF NOT EXISTS trg_skill_run_identity_immutable
BEFORE UPDATE ON skill_runs
WHEN NOT (
  OLD.id IS NEW.id
  AND OLD.run_key IS NEW.run_key
  AND OLD.workflow_key IS NEW.workflow_key
  AND OLD.dedupe_key IS NEW.dedupe_key
  AND OLD.parent_run_id IS NEW.parent_run_id
  AND OLD.skill_name IS NEW.skill_name
  AND OLD.operation IS NEW.operation
  AND OLD.trigger_kind IS NEW.trigger_kind
  AND OLD.target_from_date IS NEW.target_from_date
  AND OLD.target_through_date IS NEW.target_through_date
  AND OLD.attempt_no IS NEW.attempt_no
  AND OLD.input_manifest_json IS NEW.input_manifest_json
  AND OLD.input_sha256 IS NEW.input_sha256
  AND OLD.created_at_utc IS NEW.created_at_utc
)
BEGIN
  SELECT RAISE(ABORT, 'skill_run_identity_immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_approval_append_only_delete
BEFORE DELETE ON approvals
BEGIN
  SELECT RAISE(ABORT, 'approvals_append_only');
END;
CREATE TRIGGER IF NOT EXISTS trg_approval_append_only_update
BEFORE UPDATE ON approvals
BEGIN
  SELECT RAISE(ABORT, 'approvals_append_only');
END;
CREATE TRIGGER IF NOT EXISTS trg_run_input_sha_insert
BEFORE INSERT ON skill_runs
WHEN NEW.input_sha256 <> trainlab_json_sha(NEW.input_manifest_json)
BEGIN
  SELECT RAISE(ABORT, 'run_input_sha256_mismatch');
END;
CREATE TRIGGER IF NOT EXISTS trg_run_input_sha_update
BEFORE UPDATE OF input_manifest_json, input_sha256 ON skill_runs
WHEN NEW.input_sha256 <> trainlab_json_sha(NEW.input_manifest_json)
BEGIN
  SELECT RAISE(ABORT, 'run_input_sha256_mismatch');
END;
CREATE TRIGGER IF NOT EXISTS trg_scope_sha_insert
BEFORE INSERT ON approvals
WHEN NEW.scope_sha256 <> trainlab_json_sha(NEW.scope_json)
BEGIN
  SELECT RAISE(ABORT, 'approval_scope_sha256_mismatch');
END;
CREATE TRIGGER IF NOT EXISTS trg_scope_sha_update
BEFORE UPDATE OF scope_json, scope_sha256 ON approvals
WHEN NEW.scope_sha256 <> trainlab_json_sha(NEW.scope_json)
BEGIN
  SELECT RAISE(ABORT, 'approval_scope_sha256_mismatch');
END;
CREATE TRIGGER IF NOT EXISTS trg_request_sha_insert
BEFORE INSERT ON external_actions
WHEN NEW.request_sha256 <> trainlab_json_sha(NEW.request_json)
BEGIN
  SELECT RAISE(ABORT, 'external_action_request_sha256_mismatch');
END;
CREATE TRIGGER IF NOT EXISTS trg_request_sha_update
BEFORE UPDATE OF request_json, request_sha256 ON external_actions
WHEN NEW.request_sha256 <> trainlab_json_sha(NEW.request_json)
BEGIN
  SELECT RAISE(ABORT, 'external_action_request_sha256_mismatch');
END;
CREATE TRIGGER IF NOT EXISTS trg_output_sha_insert
BEFORE INSERT ON skill_outputs
WHEN NEW.content_sha256 <> trainlab_output_sha(
  NEW.title_text, NEW.content_json, NEW.content_text, NEW.content_html, NEW.lineage_json
)
BEGIN
  SELECT RAISE(ABORT, 'skill_output_sha256_mismatch');
END;
CREATE TRIGGER IF NOT EXISTS trg_output_sha_update
BEFORE UPDATE OF title_text, content_json, content_text, content_html, lineage_json, content_sha256
ON skill_outputs
WHEN NEW.content_sha256 <> trainlab_output_sha(
  NEW.title_text, NEW.content_json, NEW.content_text, NEW.content_html, NEW.lineage_json
)
BEGIN
  SELECT RAISE(ABORT, 'skill_output_sha256_mismatch');
END;
CREATE TRIGGER IF NOT EXISTS trg_output_lineage_refs_insert
BEFORE INSERT ON skill_outputs
WHEN EXISTS (
  SELECT 1 FROM json_each(NEW.lineage_json)
  WHERE json_type(value) <> 'object'
     OR (json_type(value,'$.raw_file_id') IS NULL
         AND json_type(value,'$.output_id') IS NULL
         AND json_type(value,'$.input_sha256') IS NULL)
     OR (json_type(value,'$.raw_file_id') IS NULL
         AND json_type(value,'$.raw_sha256') IS NOT NULL)
     OR (json_type(value,'$.output_id') IS NULL
         AND json_type(value,'$.output_sha256') IS NOT NULL)
     OR (json_type(value,'$.input_sha256') IS NOT NULL AND (
          json_type(value,'$.input_sha256') <> 'text'
          OR length(json_extract(value,'$.input_sha256')) <> 64
          OR json_extract(value,'$.input_sha256') GLOB '*[^0-9a-f]*'
        ))
     OR (json_type(value,'$.raw_file_id') IS NOT NULL AND (
          json_type(value,'$.raw_file_id') <> 'integer'
          OR json_type(value,'$.raw_sha256') <> 'text'
          OR NOT EXISTS (
               SELECT 1 FROM raw_files
               WHERE id=json_extract(value,'$.raw_file_id')
                 AND sha256=json_extract(value,'$.raw_sha256')
             )
        ))
     OR (json_type(value,'$.output_id') IS NOT NULL AND (
          json_type(value,'$.output_id') <> 'integer'
          OR json_type(value,'$.output_sha256') <> 'text'
          OR NOT EXISTS (
               SELECT 1 FROM skill_outputs
               WHERE id=json_extract(value,'$.output_id')
                 AND content_sha256=json_extract(value,'$.output_sha256')
             )
        ))
)
BEGIN
  SELECT RAISE(ABORT, 'skill_output_lineage_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_approval_authority_insert
BEFORE INSERT ON approvals
WHEN NEW.authority_kind='scheduled_ai' AND NOT EXISTS (
  SELECT 1 FROM approvals authority
  WHERE authority.id=NEW.authority_approval_id
    AND authority.authority_kind='user_explicit'
    AND authority.decision='approved'
    AND trainlab_valid_utc(authority.valid_from_utc)=1
    AND datetime(replace(authority.valid_from_utc,'T',' ')) <= datetime('now')
    AND (authority.valid_until_utc IS NULL
         OR datetime(replace(authority.valid_until_utc,'T',' ')) > datetime('now'))
)
BEGIN
  SELECT RAISE(ABORT, 'scheduled_ai_authority_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_external_action_approval_scope_exact_insert
BEFORE INSERT ON external_actions
WHEN NOT EXISTS (
  SELECT 1
  FROM approvals approval
  WHERE approval.id=NEW.approval_id
    AND approval.decision='approved'
    AND trainlab_valid_utc(approval.valid_from_utc)=1
    AND datetime(replace(approval.valid_from_utc,'T',' ')) <= datetime('now')
    AND (approval.valid_until_utc IS NULL
         OR datetime(replace(approval.valid_until_utc,'T',' ')) > datetime('now'))
    AND json_extract(approval.scope_json,'$.provider')=NEW.provider
    AND json_extract(approval.scope_json,'$.action_kind')=NEW.action_kind
    AND json_extract(approval.scope_json,'$.entity_kind')=NEW.entity_kind
    AND json_extract(approval.scope_json,'$.target_key')=NEW.target_key
    AND json_extract(approval.scope_json,'$.scope_kind')=approval.scope_kind
    AND (
      approval.authority_kind='user_explicit'
      OR EXISTS (
        SELECT 1 FROM approvals authority
        WHERE authority.id=approval.authority_approval_id
          AND authority.authority_kind='user_explicit'
          AND authority.decision='approved'
          AND trainlab_valid_utc(authority.valid_from_utc)=1
          AND datetime(replace(authority.valid_from_utc,'T',' ')) <= datetime('now')
          AND (authority.valid_until_utc IS NULL
               OR datetime(replace(authority.valid_until_utc,'T',' ')) > datetime('now'))
          AND json_extract(authority.scope_json,'$.provider')=NEW.provider
          AND json_extract(authority.scope_json,'$.action_kind')=NEW.action_kind
          AND json_extract(authority.scope_json,'$.entity_kind')=NEW.entity_kind
          AND json_extract(authority.scope_json,'$.target_key')=NEW.target_key
      )
    )
)
BEGIN
  SELECT RAISE(ABORT, 'external_action_approval_scope_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_external_action_approval_scope_exact_update
BEFORE UPDATE OF approval_id, provider, action_kind, entity_kind, target_key ON external_actions
WHEN NOT EXISTS (
  SELECT 1
  FROM approvals approval
  WHERE approval.id=NEW.approval_id
    AND approval.decision='approved'
    AND trainlab_valid_utc(approval.valid_from_utc)=1
    AND datetime(replace(approval.valid_from_utc,'T',' ')) <= datetime('now')
    AND (approval.valid_until_utc IS NULL
         OR datetime(replace(approval.valid_until_utc,'T',' ')) > datetime('now'))
    AND json_extract(approval.scope_json,'$.provider')=NEW.provider
    AND json_extract(approval.scope_json,'$.action_kind')=NEW.action_kind
    AND json_extract(approval.scope_json,'$.entity_kind')=NEW.entity_kind
    AND json_extract(approval.scope_json,'$.target_key')=NEW.target_key
    AND json_extract(approval.scope_json,'$.scope_kind')=approval.scope_kind
    AND (
      approval.authority_kind='user_explicit'
      OR EXISTS (
        SELECT 1 FROM approvals authority
        WHERE authority.id=approval.authority_approval_id
          AND authority.authority_kind='user_explicit'
          AND authority.decision='approved'
          AND trainlab_valid_utc(authority.valid_from_utc)=1
          AND datetime(replace(authority.valid_from_utc,'T',' ')) <= datetime('now')
          AND (authority.valid_until_utc IS NULL
               OR datetime(replace(authority.valid_until_utc,'T',' ')) > datetime('now'))
          AND json_extract(authority.scope_json,'$.provider')=NEW.provider
          AND json_extract(authority.scope_json,'$.action_kind')=NEW.action_kind
          AND json_extract(authority.scope_json,'$.entity_kind')=NEW.entity_kind
          AND json_extract(authority.scope_json,'$.target_key')=NEW.target_key
          AND json_extract(authority.scope_json,'$.scope_kind')=approval.scope_kind
      )
    )
)
BEGIN
  SELECT RAISE(ABORT, 'external_action_approval_scope_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_external_action_semantics_insert
BEFORE INSERT ON external_actions
WHEN NOT (
  (NEW.provider='gmail' AND NEW.entity_kind='email' AND NEW.action_kind='gmail_send')
  OR (NEW.provider='sites' AND NEW.entity_kind='site_snapshot' AND NEW.action_kind='sites_publish')
  OR (NEW.provider='garmin' AND NEW.entity_kind='workout'
      AND NEW.action_kind IN ('garmin_workout_adopt','garmin_workout_create',
                              'garmin_workout_verify','garmin_workout_delete'))
  OR (NEW.provider='garmin' AND NEW.entity_kind='calendar_entry'
      AND NEW.action_kind IN ('garmin_calendar_schedule','garmin_calendar_unschedule'))
)
BEGIN
  SELECT RAISE(ABORT, 'external_action_semantics_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_external_action_semantics_update
BEFORE UPDATE OF provider, action_kind, entity_kind ON external_actions
WHEN NOT (
  (NEW.provider='gmail' AND NEW.entity_kind='email' AND NEW.action_kind='gmail_send')
  OR (NEW.provider='sites' AND NEW.entity_kind='site_snapshot' AND NEW.action_kind='sites_publish')
  OR (NEW.provider='garmin' AND NEW.entity_kind='workout'
      AND NEW.action_kind IN ('garmin_workout_adopt','garmin_workout_create',
                              'garmin_workout_verify','garmin_workout_delete'))
  OR (NEW.provider='garmin' AND NEW.entity_kind='calendar_entry'
      AND NEW.action_kind IN ('garmin_calendar_schedule','garmin_calendar_unschedule'))
)
BEGIN
  SELECT RAISE(ABORT, 'external_action_semantics_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_external_action_append_only_update
BEFORE UPDATE ON external_actions
WHEN NOT (
  OLD.id IS NEW.id
  AND OLD.idempotency_key IS NEW.idempotency_key
  AND OLD.skill_run_id IS NEW.skill_run_id
  AND OLD.provider IS NEW.provider
  AND OLD.entity_kind IS NEW.entity_kind
  AND OLD.action_kind IS NEW.action_kind
  AND OLD.source_output_id IS NEW.source_output_id
  AND OLD.source_output_sha256 IS NEW.source_output_sha256
  AND OLD.approval_id IS NEW.approval_id
  AND OLD.related_action_id IS NEW.related_action_id
  AND OLD.target_key IS NEW.target_key
  AND OLD.target_external_id IS NEW.target_external_id
  AND OLD.provider_object_name IS NEW.provider_object_name
  AND OLD.request_json IS NEW.request_json
  AND OLD.request_sha256 IS NEW.request_sha256
  AND OLD.prepared_at_utc IS NEW.prepared_at_utc
)
BEGIN
  SELECT RAISE(ABORT, 'external_actions_append_only');
END;
CREATE TRIGGER IF NOT EXISTS trg_external_action_append_only_delete
BEFORE DELETE ON external_actions
BEGIN
  SELECT RAISE(ABORT, 'external_actions_append_only');
END;
CREATE TRIGGER IF NOT EXISTS trg_external_action_terminal_immutability
BEFORE UPDATE ON external_actions
WHEN OLD.status IN ('succeeded','already_done','failed_safe','cancelled')
  AND (OLD.result_external_id IS NOT NEW.result_external_id
       OR OLD.provider_marker IS NOT NEW.provider_marker)
BEGIN
  SELECT RAISE(ABORT, 'external_action_terminal_immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_external_action_status_transition
BEFORE UPDATE OF status ON external_actions
WHEN NOT (
  OLD.status IS NEW.status
  OR (OLD.status='prepared' AND NEW.status IN ('in_progress','failed_safe','unknown','cancelled'))
  OR (OLD.status='in_progress' AND NEW.status IN ('succeeded','already_done','failed_safe','unknown','cancelled'))
  OR (OLD.status='failed_safe' AND NEW.status IN ('prepared','in_progress','unknown','cancelled'))
  OR (OLD.status='unknown' AND NEW.status IN ('succeeded','already_done','failed_safe','cancelled'))
)
BEGIN
  SELECT RAISE(ABORT, 'external_action_status_transition_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_garmin_delete_ownership_insert
BEFORE INSERT ON external_actions
WHEN NEW.provider='garmin' AND NEW.action_kind='garmin_workout_delete'
  AND NOT EXISTS (
    SELECT 1
    FROM external_actions owner
    JOIN external_actions unschedule
      ON unschedule.related_action_id=owner.id
     AND unschedule.provider='garmin'
     AND unschedule.entity_kind='calendar_entry'
     AND unschedule.action_kind='garmin_calendar_unschedule'
     AND unschedule.status IN ('succeeded','already_done')
    WHERE owner.provider='garmin'
      AND owner.action_kind IN ('garmin_workout_create','garmin_workout_adopt')
      AND owner.status IN ('succeeded','already_done')
      AND owner.result_external_id=NEW.target_external_id
      AND owner.provider_object_name IS NOT NULL
      AND substr(owner.provider_object_name,-4)='-GTS'
      AND NEW.target_external_id IS NOT NULL
      AND NEW.provider_object_name IS NOT NULL
      AND substr(NEW.provider_object_name,-4)='-GTS'
      AND owner.provider_object_name=NEW.provider_object_name
  )
BEGIN
  SELECT RAISE(ABORT, 'garmin_delete_ownership_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_garmin_delete_absent_verify_insert
BEFORE INSERT ON external_actions
WHEN NEW.provider='garmin' AND NEW.action_kind='garmin_workout_delete'
  AND json_extract(NEW.request_json,'$.m10_phase')='delete'
  AND NOT EXISTS (
    SELECT 1
    FROM external_actions owner
    JOIN external_actions unschedule
      ON unschedule.related_action_id=owner.id
     AND unschedule.provider='garmin'
     AND unschedule.action_kind='garmin_calendar_unschedule'
     AND unschedule.status IN ('succeeded','already_done')
     AND json_extract(unschedule.request_json,'$.m10_phase')='unschedule'
    JOIN external_actions verification
      ON verification.related_action_id=unschedule.id
     AND verification.provider='garmin'
     AND verification.action_kind='garmin_workout_verify'
     AND verification.status IN ('succeeded','already_done')
     AND json_extract(verification.request_json,'$.m10_phase')='verify_absent_after_unschedule'
     AND json_extract(verification.response_summary_json,'$.absent')=1
    WHERE owner.id=NEW.related_action_id
      AND owner.provider='garmin'
      AND owner.action_kind='garmin_workout_create'
      AND owner.status IN ('succeeded','already_done')
      AND owner.result_external_id=NEW.target_external_id
      AND owner.provider_object_name=NEW.provider_object_name
  )
BEGIN
  SELECT RAISE(ABORT, 'm10_garmin_delete_verification_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_approval_preview_sources_insert
BEFORE INSERT ON approvals
WHEN NEW.source_ref LIKE 'm10-preview:%'
  AND NOT EXISTS (
    SELECT 1
    FROM skill_outputs preview
    JOIN skill_outputs plan
      ON plan.id=json_extract(preview.content_json,'$.training_plan_output_id')
     AND plan.content_sha256=
         json_extract(preview.content_json,'$.training_plan_output_sha256')
     AND plan.output_kind='training_plan'
     AND plan.schema_name='training_plan_v1'
     AND plan.period_start_date='2026-08-12'
     AND plan.period_end_date='2026-08-18'
    JOIN skill_runs plan_run
      ON plan_run.id=plan.skill_run_id
     AND plan_run.status='succeeded'
     AND plan_run.skill_name='training-coach'
     AND plan_run.operation='weekly_coach'
     AND plan_run.workflow_key='weekly:2026-08-18'
    WHERE preview.id=NEW.candidate_output_id
      AND preview.content_sha256=NEW.candidate_output_sha256
      AND preview.schema_name='m10_external_preview_v1'
      AND trainlab_valid_m10_preview(preview.content_json)=1
      AND NEW.source_ref='m10-preview:' ||
          json_extract(preview.content_json,'$.preview_sha256')
      AND trainlab_valid_schema_payload(plan.content_json,plan.schema_name)=1
      AND trainlab_valid_m10_plan_schedule(
            plan.content_json,
            json_extract(preview.content_json,'$.schedule'))=1
      AND json_array_length(plan.lineage_json)=7
      AND NOT EXISTS (
        SELECT 1
        FROM json_each(preview.content_json,'$.report_sources') report
        WHERE NOT EXISTS (
          SELECT 1 FROM skill_outputs source
          JOIN skill_runs source_run ON source_run.id=source.skill_run_id
          WHERE source.id=json_extract(report.value,'$.source_output_id')
            AND source.content_sha256=
                json_extract(report.value,'$.source_output_sha256')
            AND source.schema_name=CASE json_extract(report.value,'$.mode')
              WHEN 'daily' THEN 'daily_ai_result_v1'
              ELSE 'weekly_ai_result_v1' END
            AND source.output_kind=CASE json_extract(report.value,'$.mode')
              WHEN 'daily' THEN 'daily_summary'
              ELSE 'weekly_summary' END
            AND source.period_end_date=json_extract(report.value,'$.target')
            AND source.period_start_date=CASE json_extract(report.value,'$.mode')
              WHEN 'daily' THEN json_extract(report.value,'$.target')
              ELSE '2026-08-12' END
            AND trainlab_valid_schema_payload(
                  source.content_json,source.schema_name)=1
            AND source_run.status='succeeded'
            AND source_run.skill_name='training-coach'
            AND source_run.operation=CASE json_extract(report.value,'$.mode')
              WHEN 'daily' THEN 'daily_coach' ELSE 'weekly_coach' END
            AND source_run.workflow_key=CASE json_extract(report.value,'$.mode')
              WHEN 'daily' THEN 'daily:' || json_extract(report.value,'$.target')
              ELSE 'weekly:2026-08-18' END
        )
        OR NOT EXISTS (
          SELECT 1 FROM skill_outputs email
          JOIN skill_runs email_run ON email_run.id=email.skill_run_id
          WHERE email.id=json_extract(report.value,'$.email_output_id')
            AND email.content_sha256=
                json_extract(report.value,'$.email_output_sha256')
            AND email.output_kind='email_render'
            AND json_extract(
                  preview.content_json,
                  '$.emails[' || report.key || '].source_output_id')=email.id
            AND json_extract(
                  preview.content_json,
                  '$.emails[' || report.key || '].source_output_sha256')=
                email.content_sha256
            AND json_extract(
                  preview.content_json,
                  '$.emails[' || report.key || '].request_sha256')=
                trainlab_json_sha(json_object(
                  'to',json_array(json_extract(
                    preview.content_json,
                    '$.emails[' || report.key || '].recipient')),
                  'subject',email.title_text,
                  'body',email.content_text,
                  'htmlBody',email.content_html,
                  'mimeType','multipart/alternative'
                ))
            AND json_extract(email.lineage_json,'$[0].source_output_id')=
                json_extract(report.value,'$.source_output_id')
            AND json_extract(email.lineage_json,'$[0].source_output_sha256')=
                json_extract(report.value,'$.source_output_sha256')
            AND email_run.status='succeeded'
            AND email_run.skill_name='training-report-publisher'
        )
        OR (
          json_extract(report.value,'$.mode')='daily'
          AND NOT EXISTS (
            SELECT 1 FROM json_each(plan.lineage_json) lineage
            WHERE json_extract(lineage.value,'$.output_id')=
                  json_extract(report.value,'$.source_output_id')
              AND json_extract(lineage.value,'$.output_sha256')=
                  json_extract(report.value,'$.source_output_sha256')
          )
        )
      )
      AND NOT EXISTS (
        SELECT 1
        FROM json_each(preview.content_json,'$.report_sources') weekly_report
        WHERE json_extract(weekly_report.value,'$.mode')='weekly'
          AND NOT EXISTS (
            SELECT 1 FROM skill_outputs weekly_source
            WHERE weekly_source.id=json_extract(
                    weekly_report.value,'$.source_output_id')
              AND weekly_source.skill_run_id=plan.skill_run_id
              AND json_array_length(weekly_source.lineage_json)=7
              AND json_array_length(
                    weekly_source.content_json,'$.daily_input_sha256')=7
              AND json_array_length(
                    weekly_source.content_json,'$.evidence_refs')=7
              AND NOT EXISTS (
                SELECT 1
                FROM json_each(preview.content_json,'$.report_sources') daily_report
                WHERE json_extract(daily_report.value,'$.mode')='daily'
                  AND (
                    NOT EXISTS (
                      SELECT 1 FROM json_each(weekly_source.lineage_json) lineage
                      WHERE json_extract(lineage.value,'$.output_id')=
                            json_extract(daily_report.value,'$.source_output_id')
                        AND json_extract(lineage.value,'$.output_sha256')=
                            json_extract(daily_report.value,'$.source_output_sha256')
                    )
                    OR NOT EXISTS (
                      SELECT 1 FROM json_each(
                        weekly_source.content_json,'$.daily_input_sha256') digest
                      WHERE digest.value=json_extract(
                        daily_report.value,'$.source_output_sha256')
                    )
                    OR NOT EXISTS (
                      SELECT 1 FROM json_each(
                        weekly_source.content_json,'$.evidence_refs') evidence
                      WHERE json_extract(evidence.value,'$.output_id')=
                            json_extract(daily_report.value,'$.source_output_id')
                        AND json_extract(evidence.value,'$.sha256')=
                            json_extract(daily_report.value,'$.source_output_sha256')
                    )
                  )
              )
          )
      )
  )
BEGIN
  SELECT RAISE(ABORT, 'm10_preview_sources_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_external_preview_scope_insert
BEFORE INSERT ON external_actions
WHEN (NEW.target_key LIKE 'm10:%'
      OR NEW.provider_object_name LIKE '%-E2E-20260818-GTS')
  AND NOT EXISTS (
    SELECT 1
    FROM approvals approval
    JOIN skill_outputs preview ON preview.id=approval.candidate_output_id
    WHERE approval.id=NEW.approval_id
      AND preview.schema_name='m10_external_preview_v1'
      AND trainlab_valid_m10_preview(preview.content_json)=1
      AND length(json_extract(approval.scope_json,'$.preview_sha256'))=64
      AND json_extract(preview.content_json,'$.preview_sha256')=
          json_extract(approval.scope_json,'$.preview_sha256')
      AND approval.source_ref='m10-preview:' ||
          json_extract(approval.scope_json,'$.preview_sha256')
  )
BEGIN
  SELECT RAISE(ABORT, 'm10_external_preview_scope_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_external_preview_member_insert
BEFORE INSERT ON external_actions
WHEN (NEW.target_key LIKE 'm10:%'
      OR NEW.provider_object_name LIKE '%-E2E-20260818-GTS')
  AND NOT EXISTS (
    SELECT 1
    FROM approvals approval
    JOIN skill_outputs preview ON preview.id=approval.candidate_output_id
    WHERE approval.id=NEW.approval_id
      AND preview.schema_name='m10_external_preview_v1'
      AND trainlab_valid_m10_preview(preview.content_json)=1
      AND (
        (NEW.provider='gmail'
         AND NEW.action_kind='gmail_send'
         AND EXISTS (
           SELECT 1 FROM json_each(preview.content_json,'$.emails') email
           WHERE NEW.target_key='m10:email:' || json_extract(email.value,'$.marker')
             AND NEW.request_sha256=json_extract(email.value,'$.request_sha256')
         ))
        OR
        (NEW.provider='garmin'
         AND NEW.provider_object_name LIKE '%-E2E-20260818-GTS'
         AND EXISTS (
           SELECT 1 FROM json_each(preview.content_json,'$.schedule') course
           WHERE NEW.provider_object_name=json_extract(course.value,'$.name')
             AND NEW.target_key='m10:' ||
                 COALESCE(json_extract(NEW.request_json,'$.m10_phase'),'') || ':' ||
                 NEW.provider_object_name
             AND NEW.request_sha256=json_extract(
               course.value,
               '$.action_request_sha256.' ||
               COALESCE(json_extract(NEW.request_json,'$.m10_phase'),'')
             )
         ))
      )
  )
BEGIN
  SELECT RAISE(ABORT, 'm10_external_preview_member_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_gmail_send_budget_insert
BEFORE INSERT ON external_actions
WHEN NEW.provider='gmail' AND NEW.action_kind='gmail_send'
  AND NEW.target_key LIKE 'm10:email:%'
  AND (SELECT COUNT(*) FROM external_actions prior
       WHERE prior.provider='gmail'
         AND prior.action_kind='gmail_send'
         AND prior.target_key LIKE 'm10:email:%') >= 8
BEGIN
  SELECT RAISE(ABORT, 'm10_gmail_send_budget_exceeded');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_garmin_phase_required_insert
BEFORE INSERT ON external_actions
WHEN NEW.provider='garmin'
  AND (NEW.target_key LIKE 'm10:%'
       OR NEW.provider_object_name LIKE '%-E2E-20260818-GTS')
  AND NOT (
    (NEW.action_kind='garmin_workout_create'
      AND COALESCE(json_extract(NEW.request_json,'$.m10_phase'),'')='create')
    OR
    (NEW.action_kind='garmin_workout_verify'
      AND COALESCE(json_extract(NEW.request_json,'$.m10_phase'),'') IN
        ('verify_created','verify_scheduled','verify_absent_after_unschedule',
         'verify_absent_after_delete'))
    OR
    (NEW.action_kind='garmin_calendar_schedule'
      AND COALESCE(json_extract(NEW.request_json,'$.m10_phase'),'')='schedule')
    OR
    (NEW.action_kind='garmin_calendar_unschedule'
      AND COALESCE(json_extract(NEW.request_json,'$.m10_phase'),'')='unschedule')
    OR
    (NEW.action_kind='garmin_workout_delete'
      AND COALESCE(json_extract(NEW.request_json,'$.m10_phase'),'')='delete')
  )
BEGIN
  SELECT RAISE(ABORT, 'm10_garmin_phase_required');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_garmin_create_budget_insert
BEFORE INSERT ON external_actions
WHEN NEW.provider='garmin'
  AND NEW.action_kind='garmin_workout_create'
  AND json_extract(NEW.request_json,'$.m10_phase')='create'
  AND (SELECT COUNT(*) FROM external_actions prior
       WHERE prior.provider='garmin'
         AND prior.action_kind='garmin_workout_create'
         AND prior.provider_object_name LIKE '%-E2E-20260818-GTS') >= 4
BEGIN
  SELECT RAISE(ABORT, 'm10_garmin_create_budget_exceeded');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_garmin_verify_created_order_insert
BEFORE INSERT ON external_actions
WHEN NEW.provider='garmin'
  AND json_extract(NEW.request_json,'$.m10_phase')='verify_created'
  AND NOT EXISTS (
    SELECT 1 FROM external_actions owner
    WHERE owner.id=NEW.related_action_id
      AND owner.provider='garmin'
      AND owner.action_kind='garmin_workout_create'
      AND owner.status IN ('succeeded','already_done')
      AND owner.result_external_id=NEW.target_external_id
      AND owner.provider_object_name=NEW.provider_object_name
  )
BEGIN
  SELECT RAISE(ABORT, 'm10_garmin_verify_created_order_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_garmin_schedule_order_insert
BEFORE INSERT ON external_actions
WHEN NEW.provider='garmin'
  AND json_extract(NEW.request_json,'$.m10_phase')='schedule'
  AND NOT EXISTS (
    SELECT 1
    FROM external_actions owner
    JOIN external_actions verification
      ON verification.related_action_id=owner.id
     AND verification.provider='garmin'
     AND verification.action_kind='garmin_workout_verify'
     AND verification.status IN ('succeeded','already_done')
     AND json_extract(verification.request_json,'$.m10_phase')='verify_created'
     AND json_extract(verification.response_summary_json,'$.exists')=1
    WHERE owner.id=NEW.related_action_id
      AND owner.provider='garmin'
      AND owner.action_kind='garmin_workout_create'
      AND owner.status IN ('succeeded','already_done')
      AND owner.result_external_id=NEW.target_external_id
      AND owner.provider_object_name=NEW.provider_object_name
  )
BEGIN
  SELECT RAISE(ABORT, 'm10_garmin_schedule_order_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_garmin_verify_scheduled_order_insert
BEFORE INSERT ON external_actions
WHEN NEW.provider='garmin'
  AND json_extract(NEW.request_json,'$.m10_phase')='verify_scheduled'
  AND NOT EXISTS (
    SELECT 1 FROM external_actions schedule
    WHERE schedule.id=NEW.related_action_id
      AND schedule.provider='garmin'
      AND schedule.action_kind='garmin_calendar_schedule'
      AND schedule.status IN ('succeeded','already_done')
      AND schedule.result_external_id=NEW.target_external_id
      AND schedule.provider_object_name=NEW.provider_object_name
  )
BEGIN
  SELECT RAISE(ABORT, 'm10_garmin_verify_scheduled_order_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_garmin_unschedule_order_insert
BEFORE INSERT ON external_actions
WHEN NEW.provider='garmin'
  AND json_extract(NEW.request_json,'$.m10_phase')='unschedule'
  AND NOT EXISTS (
    SELECT 1
    FROM external_actions owner
    JOIN external_actions schedule
      ON schedule.related_action_id=owner.id
     AND schedule.provider='garmin'
     AND schedule.action_kind='garmin_calendar_schedule'
     AND schedule.status IN ('succeeded','already_done')
    JOIN external_actions verification
      ON verification.related_action_id=schedule.id
     AND verification.provider='garmin'
     AND verification.action_kind='garmin_workout_verify'
     AND verification.status IN ('succeeded','already_done')
     AND json_extract(verification.request_json,'$.m10_phase')='verify_scheduled'
     AND json_extract(verification.response_summary_json,'$.exists')=1
    WHERE owner.id=NEW.related_action_id
      AND owner.action_kind='garmin_workout_create'
      AND owner.status IN ('succeeded','already_done')
      AND schedule.result_external_id=NEW.target_external_id
      AND owner.provider_object_name=NEW.provider_object_name
  )
BEGIN
  SELECT RAISE(ABORT, 'm10_garmin_unschedule_order_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_garmin_verify_absent_unschedule_order_insert
BEFORE INSERT ON external_actions
WHEN NEW.provider='garmin'
  AND json_extract(NEW.request_json,'$.m10_phase')='verify_absent_after_unschedule'
  AND NOT EXISTS (
    SELECT 1 FROM external_actions unschedule
    WHERE unschedule.id=NEW.related_action_id
      AND unschedule.provider='garmin'
      AND unschedule.action_kind='garmin_calendar_unschedule'
      AND unschedule.status IN ('succeeded','already_done')
      AND unschedule.target_external_id=NEW.target_external_id
      AND unschedule.provider_object_name=NEW.provider_object_name
  )
BEGIN
  SELECT RAISE(ABORT, 'm10_garmin_verify_absent_unschedule_order_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_garmin_verify_absent_delete_order_insert
BEFORE INSERT ON external_actions
WHEN NEW.provider='garmin'
  AND json_extract(NEW.request_json,'$.m10_phase')='verify_absent_after_delete'
  AND NOT EXISTS (
    SELECT 1 FROM external_actions deletion
    WHERE deletion.id=NEW.related_action_id
      AND deletion.provider='garmin'
      AND deletion.action_kind='garmin_workout_delete'
      AND deletion.status IN ('succeeded','already_done')
      AND deletion.target_external_id=NEW.target_external_id
      AND deletion.provider_object_name=NEW.provider_object_name
  )
BEGIN
  SELECT RAISE(ABORT, 'm10_garmin_verify_absent_delete_order_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_garmin_terminal_evidence_update
BEFORE UPDATE OF status ON external_actions
WHEN NEW.provider='garmin'
  AND NEW.status IN ('succeeded','already_done')
  AND (
    (json_extract(NEW.request_json,'$.m10_phase')='create'
      AND (NEW.result_external_id IS NULL
           OR json_extract(NEW.response_summary_json,'$.created_new') IS NOT 1
           OR json_extract(NEW.response_summary_json,'$.preexisting') IS NOT 0))
    OR
    (json_extract(NEW.request_json,'$.m10_phase') IN ('verify_created','verify_scheduled')
      AND json_extract(NEW.response_summary_json,'$.exists') IS NOT 1)
    OR
    (json_extract(NEW.request_json,'$.m10_phase') IN
       ('verify_absent_after_unschedule','verify_absent_after_delete')
      AND json_extract(NEW.response_summary_json,'$.absent') IS NOT 1)
    OR
    (json_extract(NEW.request_json,'$.m10_phase')='schedule'
      AND NEW.result_external_id IS NULL)
  )
BEGIN
  SELECT RAISE(ABORT, 'm10_garmin_terminal_evidence_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_garmin_terminal_evidence_insert
BEFORE INSERT ON external_actions
WHEN NEW.provider='garmin'
  AND NEW.status IN ('succeeded','already_done')
  AND (NEW.target_key LIKE 'm10:%'
       OR NEW.provider_object_name LIKE '%-E2E-20260818-GTS')
  AND (
    (NEW.action_kind='garmin_workout_create'
      AND (NEW.result_external_id IS NULL
           OR json_extract(NEW.response_summary_json,'$.created_new') IS NOT 1
           OR json_extract(NEW.response_summary_json,'$.preexisting') IS NOT 0))
    OR
    (NEW.action_kind='garmin_workout_verify'
      AND json_extract(NEW.request_json,'$.m10_phase') IN
          ('verify_created','verify_scheduled')
      AND json_extract(NEW.response_summary_json,'$.exists') IS NOT 1)
    OR
    (NEW.action_kind='garmin_workout_verify'
      AND json_extract(NEW.request_json,'$.m10_phase') IN
          ('verify_absent_after_unschedule','verify_absent_after_delete')
      AND json_extract(NEW.response_summary_json,'$.absent') IS NOT 1)
    OR
    (NEW.action_kind='garmin_calendar_schedule'
      AND NEW.result_external_id IS NULL)
  )
BEGIN
  SELECT RAISE(ABORT, 'm10_garmin_terminal_evidence_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_gmail_terminal_evidence_update
BEFORE UPDATE OF status ON external_actions
WHEN NEW.provider='gmail'
  AND NEW.target_key LIKE 'm10:email:%'
  AND NEW.status IN ('succeeded','already_done')
  AND (NEW.result_external_id IS NULL OR NEW.result_external_id=''
       OR NEW.provider_marker IS NULL OR NEW.provider_marker=''
       OR NEW.provider_marker<>substr(NEW.target_key,11)
       OR json_extract(NEW.response_summary_json,'$.verified') IS NOT 1
       OR json_extract(NEW.response_summary_json,'$.match_count')<>1
       OR json_extract(NEW.response_summary_json,'$.send_message_id')<>
          NEW.result_external_id
       OR json_extract(NEW.response_summary_json,'$.matched_message_id')<>
          NEW.result_external_id
       OR NOT EXISTS (
         SELECT 1
         FROM skill_runs send_run
         JOIN skill_outputs send_result ON send_result.skill_run_id=send_run.id
         JOIN json_each(send_run.input_manifest_json,'$.external_action_ids') member
         WHERE send_run.status='succeeded'
           AND send_run.operation='mcp_tool_call'
           AND json_extract(send_run.input_manifest_json,'$.m10_role')=
               'm10_external_mcp_call_v1'
           AND json_extract(send_run.input_manifest_json,'$.provider')='gmail'
           AND json_extract(send_run.input_manifest_json,'$.tool_name')='send_email'
           AND CAST(member.value AS INTEGER)=NEW.id
           AND send_result.schema_name='m10_mcp_call_result_v1'
           AND json_extract(send_result.content_json,'$.message_id')=
               NEW.result_external_id
           AND json_extract(send_result.content_json,'$.match_count')=0
           AND json_array_length(
                 json_extract(send_result.content_json,'$.matched_message_ids'))=0
       )
       OR NOT EXISTS (
         SELECT 1
         FROM skill_runs search_run
         JOIN skill_outputs search_result ON search_result.skill_run_id=search_run.id
         JOIN json_each(search_run.input_manifest_json,'$.external_action_ids') member
         WHERE search_run.status='succeeded'
           AND search_run.operation='mcp_tool_call'
           AND json_extract(search_run.input_manifest_json,'$.m10_role')=
               'm10_external_mcp_call_v1'
           AND json_extract(search_run.input_manifest_json,'$.provider')='gmail'
           AND json_extract(search_run.input_manifest_json,'$.tool_name')='search_emails'
           AND CAST(member.value AS INTEGER)=NEW.id
           AND json_extract(search_run.input_manifest_json,'$.request_json.query')=
               json_extract(NEW.response_summary_json,'$.verification_query')
           AND search_result.schema_name='m10_mcp_call_result_v1'
           AND json_extract(search_result.content_json,'$.match_count')=1
           AND json_array_length(
                 json_extract(search_result.content_json,'$.matched_message_ids'))=1
           AND json_extract(search_result.content_json,'$.matched_message_ids[0]')=
               NEW.result_external_id
       ))
BEGIN
  SELECT RAISE(ABORT, 'm10_gmail_terminal_evidence_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_gmail_terminal_evidence_insert
BEFORE INSERT ON external_actions
WHEN NEW.provider='gmail'
  AND NEW.target_key LIKE 'm10:email:%'
  AND NEW.status IN ('succeeded','already_done')
  AND (NEW.result_external_id IS NULL OR NEW.result_external_id=''
       OR NEW.provider_marker IS NULL OR NEW.provider_marker=''
       OR NEW.provider_marker<>substr(NEW.target_key,11)
       OR json_extract(NEW.response_summary_json,'$.verified') IS NOT 1
       OR json_extract(NEW.response_summary_json,'$.match_count')<>1
       OR json_extract(NEW.response_summary_json,'$.send_message_id')<>
          NEW.result_external_id
       OR json_extract(NEW.response_summary_json,'$.matched_message_id')<>
          NEW.result_external_id
       OR NOT EXISTS (
         SELECT 1
         FROM skill_runs send_run
         JOIN skill_outputs send_result ON send_result.skill_run_id=send_run.id
         JOIN json_each(send_run.input_manifest_json,'$.external_action_ids') member
         WHERE send_run.status='succeeded'
           AND send_run.operation='mcp_tool_call'
           AND json_extract(send_run.input_manifest_json,'$.tool_name')='send_email'
           AND CAST(member.value AS INTEGER)=NEW.id
           AND send_result.schema_name='m10_mcp_call_result_v1'
           AND json_extract(send_result.content_json,'$.message_id')=
               NEW.result_external_id
           AND json_extract(send_result.content_json,'$.match_count')=0
           AND json_array_length(
                 json_extract(send_result.content_json,'$.matched_message_ids'))=0
       )
       OR NOT EXISTS (
         SELECT 1
         FROM skill_runs search_run
         JOIN skill_outputs search_result ON search_result.skill_run_id=search_run.id
         JOIN json_each(search_run.input_manifest_json,'$.external_action_ids') member
         WHERE search_run.status='succeeded'
           AND search_run.operation='mcp_tool_call'
           AND json_extract(search_run.input_manifest_json,'$.tool_name')='search_emails'
           AND CAST(member.value AS INTEGER)=NEW.id
           AND search_result.schema_name='m10_mcp_call_result_v1'
           AND json_extract(search_result.content_json,'$.match_count')=1
           AND json_array_length(
                 json_extract(search_result.content_json,'$.matched_message_ids'))=1
           AND json_extract(search_result.content_json,'$.matched_message_ids[0]')=
               NEW.result_external_id
       ))
BEGIN
  SELECT RAISE(ABORT, 'm10_gmail_terminal_evidence_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_old_gmail_unknown_history_immutable
BEFORE UPDATE OF status ON external_actions
WHEN OLD.provider='gmail'
  AND OLD.action_kind='gmail_send'
  AND OLD.target_key LIKE 'm10:email:%'
  AND OLD.status='unknown'
  AND NEW.status IS NOT OLD.status
BEGIN
  SELECT RAISE(ABORT, 'm10_old_gmail_reconciliation_missing');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_external_no_retry_update
BEFORE UPDATE OF status ON external_actions
WHEN (NEW.target_key LIKE 'm10:%'
      OR NEW.provider_object_name LIKE '%-E2E-20260818-GTS')
  AND ((NEW.status='in_progress' AND OLD.attempt_count >= 1)
       OR (OLD.status='failed_safe' AND NEW.status IS NOT OLD.status))
BEGIN
  SELECT RAISE(ABORT, 'm10_external_retry_forbidden');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_mcp_run_contract_insert
BEFORE INSERT ON skill_runs
WHEN (NEW.workflow_key LIKE 'm10:external:%'
  OR json_extract(NEW.input_manifest_json,'$.m10_role')=
     'm10_external_mcp_call_v1'
  OR NEW.operation='mcp_tool_call')
  AND COALESCE((
    json_extract(NEW.input_manifest_json,'$.m10_role')='m10_external_mcp_call_v1'
    AND json_extract(NEW.input_manifest_json,'$.provider') IN ('gmail','garmin')
    AND json_extract(NEW.input_manifest_json,'$.tool_name') IN (
      'send_email','search_emails',
      'get_workouts','get_workout_by_id','get_scheduled_workouts',
      'upload_workout','upload_workouts','schedule_workout','schedule_workouts',
      'unschedule_workout','unschedule_workouts','delete_workout','delete_workouts'
    )
    AND NEW.workflow_key='m10:external:' ||
        json_extract(NEW.input_manifest_json,'$.provider') || ':2026-08-18'
    AND length(json_extract(NEW.input_manifest_json,'$.request_sha256'))=64
    AND json_type(NEW.input_manifest_json,'$.request_json')='object'
    AND trainlab_json_sha(json_extract(
          NEW.input_manifest_json,'$.request_json'))=
        json_extract(NEW.input_manifest_json,'$.request_sha256')
    AND length(json_extract(NEW.input_manifest_json,'$.preview_output_sha256'))=64
    AND length(json_extract(NEW.input_manifest_json,'$.preview_sha256'))=64
    AND json_type(NEW.input_manifest_json,'$.external_action_ids')='array'
    AND (
      (NEW.attempt_no=1
       AND json_type(NEW.input_manifest_json,'$.reconciliation_mode') IS NULL
       AND json_type(NEW.input_manifest_json,'$.prior_run_id') IS NULL)
      OR
      (NEW.attempt_no=2
       AND json_extract(NEW.input_manifest_json,'$.provider')='gmail'
       AND json_extract(NEW.input_manifest_json,'$.tool_name')='search_emails'
       AND json_extract(NEW.input_manifest_json,'$.reconciliation_mode')=
           'user_approved_result_unpersisted'
       AND json_type(NEW.input_manifest_json,'$.prior_run_id')='integer'
       AND EXISTS (
         SELECT 1 FROM skill_runs prior
         WHERE prior.id=json_extract(NEW.input_manifest_json,'$.prior_run_id')
           AND prior.dedupe_key=NEW.dedupe_key
           AND prior.attempt_no=1
           AND prior.status='failed'
           AND prior.error_code='gmail_search_result_unpersisted'
           AND prior.operation='mcp_tool_call'
           AND json_extract(prior.input_manifest_json,'$.m10_role')=
               'm10_external_mcp_call_v1'
           AND json_extract(prior.input_manifest_json,'$.provider')='gmail'
           AND json_extract(prior.input_manifest_json,'$.tool_name')='search_emails'
           AND json_extract(prior.input_manifest_json,'$.request_sha256')=
               json_extract(NEW.input_manifest_json,'$.request_sha256')
           AND json_extract(prior.input_manifest_json,'$.preview_output_id')=
               json_extract(NEW.input_manifest_json,'$.preview_output_id')
           AND json_extract(prior.input_manifest_json,'$.preview_output_sha256')=
               json_extract(NEW.input_manifest_json,'$.preview_output_sha256')
           AND json_extract(prior.input_manifest_json,'$.external_action_ids')=
               json_extract(NEW.input_manifest_json,'$.external_action_ids')
       ))
    )
    AND NEW.operation='mcp_tool_call'
    AND ((json_extract(NEW.input_manifest_json,'$.provider')='gmail'
          AND NEW.skill_name='gmail-sender')
         OR
         (json_extract(NEW.input_manifest_json,'$.provider')='garmin'
          AND NEW.skill_name='garmin-training-sender'))
    AND EXISTS (
      SELECT 1 FROM skill_outputs preview
      WHERE preview.id=json_extract(
              NEW.input_manifest_json,'$.preview_output_id')
        AND preview.content_sha256=json_extract(
              NEW.input_manifest_json,'$.preview_output_sha256')
        AND preview.schema_name='m10_external_preview_v1'
        AND trainlab_valid_m10_preview(preview.content_json)=1
        AND trainlab_valid_m10_mcp_request(
              NEW.input_manifest_json,preview.content_json)=1
        AND json_extract(preview.content_json,'$.preview_sha256')=
            json_extract(NEW.input_manifest_json,'$.preview_sha256')
    )
    AND (
      (json_extract(NEW.input_manifest_json,'$.tool_name') IN (
         'get_workouts','get_scheduled_workouts'
       )
       AND json_array_length(
             json_extract(NEW.input_manifest_json,'$.external_action_ids'))=0)
      OR
      (json_extract(NEW.input_manifest_json,'$.tool_name') IN (
         'search_emails','get_workout_by_id'
       )
       AND json_array_length(
             json_extract(NEW.input_manifest_json,'$.external_action_ids'))=1
       AND NOT EXISTS (
         SELECT 1
         FROM json_each(NEW.input_manifest_json,'$.external_action_ids') member
         WHERE NOT EXISTS (
           SELECT 1
           FROM external_actions action
           JOIN approvals approval ON approval.id=action.approval_id
           WHERE action.id=CAST(member.value AS INTEGER)
             AND action.source_output_id=json_extract(
                   NEW.input_manifest_json,'$.preview_output_id')
             AND action.source_output_sha256=json_extract(
                   NEW.input_manifest_json,'$.preview_output_sha256')
             AND approval.candidate_output_id=action.source_output_id
             AND approval.candidate_output_sha256=action.source_output_sha256
             AND approval.decision='approved'
             AND approval.valid_from_utc<=NEW.created_at_utc
             AND approval.valid_until_utc>=NEW.created_at_utc
             AND json_extract(approval.scope_json,'$.preview_sha256')=
                 json_extract(NEW.input_manifest_json,'$.preview_sha256')
             AND (
               (json_extract(NEW.input_manifest_json,'$.tool_name')='search_emails'
                AND action.provider='gmail'
                AND action.action_kind='gmail_send'
                AND action.status IN
                    ('prepared','in_progress','succeeded','already_done','unknown')
                AND EXISTS (
                    SELECT 1
                    FROM skill_outputs search_preview,
                         json_each(search_preview.content_json,'$.emails') email
                    WHERE search_preview.id=json_extract(
                            NEW.input_manifest_json,'$.preview_output_id')
                      AND search_preview.content_sha256=json_extract(
                            NEW.input_manifest_json,'$.preview_output_sha256')
                      AND search_preview.schema_name='m10_external_preview_v1'
                      AND action.target_key='m10:email:' ||
                          json_extract(email.value,'$.marker')
                      AND json_extract(email.value,'$.verification_query')=
                          json_extract(
                            NEW.input_manifest_json,'$.request_json.query')
                  ))
               OR
               (json_extract(NEW.input_manifest_json,'$.tool_name')=
                    'get_workout_by_id'
                AND action.provider='garmin'
                AND action.action_kind='garmin_workout_create'
                AND action.status IN ('succeeded','already_done')
                AND action.result_external_id IS NOT NULL
                AND CAST(json_extract(
                      NEW.input_manifest_json,'$.request_json.workout_id') AS TEXT)=
                    action.result_external_id)
             )
         )
       ))
      OR
      (json_extract(NEW.input_manifest_json,'$.tool_name') IN (
         'send_email','upload_workout','upload_workouts','schedule_workout',
         'schedule_workouts','unschedule_workout','unschedule_workouts',
         'delete_workout','delete_workouts'
       )
       AND json_array_length(
             json_extract(NEW.input_manifest_json,'$.external_action_ids')) BETWEEN 1 AND 4
       AND (
         json_extract(NEW.input_manifest_json,'$.tool_name') IN (
           'upload_workouts','schedule_workouts','unschedule_workouts','delete_workouts')
         OR json_array_length(json_extract(
              NEW.input_manifest_json,'$.external_action_ids'))=1
       )
       AND (SELECT COUNT(*) FROM json_each(
              NEW.input_manifest_json,'$.external_action_ids'))=
           (SELECT COUNT(DISTINCT value) FROM json_each(
              NEW.input_manifest_json,'$.external_action_ids'))
       AND NOT EXISTS (
         SELECT 1
         FROM json_each(NEW.input_manifest_json,'$.external_action_ids') member
         WHERE NOT EXISTS (
           SELECT 1
           FROM external_actions action
           JOIN approvals approval ON approval.id=action.approval_id
           WHERE action.id=CAST(member.value AS INTEGER)
             AND action.status='prepared'
             AND action.source_output_id=json_extract(
                   NEW.input_manifest_json,'$.preview_output_id')
             AND action.source_output_sha256=json_extract(
                   NEW.input_manifest_json,'$.preview_output_sha256')
             AND action.provider=json_extract(
                   NEW.input_manifest_json,'$.provider')
             AND action.action_kind=CASE
               WHEN json_extract(NEW.input_manifest_json,'$.tool_name')='send_email'
                 THEN 'gmail_send'
               WHEN json_extract(NEW.input_manifest_json,'$.tool_name') IN
                    ('upload_workout','upload_workouts')
                 THEN 'garmin_workout_create'
               WHEN json_extract(NEW.input_manifest_json,'$.tool_name') IN
                    ('schedule_workout','schedule_workouts')
                 THEN 'garmin_calendar_schedule'
               WHEN json_extract(NEW.input_manifest_json,'$.tool_name') IN
                    ('unschedule_workout','unschedule_workouts')
                 THEN 'garmin_calendar_unschedule'
               ELSE 'garmin_workout_delete' END
             AND approval.candidate_output_id=action.source_output_id
             AND approval.candidate_output_sha256=action.source_output_sha256
             AND approval.decision='approved'
             AND approval.valid_from_utc<=NEW.created_at_utc
             AND approval.valid_until_utc>=NEW.created_at_utc
             AND json_extract(approval.scope_json,'$.preview_sha256')=
                 json_extract(NEW.input_manifest_json,'$.preview_sha256')
             AND (
               (json_extract(NEW.input_manifest_json,'$.tool_name')='send_email'
                AND action.request_sha256=json_extract(
                      NEW.input_manifest_json,'$.request_sha256'))
               OR
               (json_extract(NEW.input_manifest_json,'$.tool_name')='upload_workout'
                AND trainlab_json_sha(json_extract(
                      action.request_json,'$.workout_data'))=
                    trainlab_json_sha(json_extract(
                      NEW.input_manifest_json,'$.request_json.workout_data')))
               OR
               (json_extract(NEW.input_manifest_json,'$.tool_name')='upload_workouts'
                AND json_array_length(json_extract(
                      NEW.input_manifest_json,'$.request_json.workouts'))=
                    json_array_length(json_extract(
                      NEW.input_manifest_json,'$.external_action_ids'))
                AND trainlab_json_sha(json_extract(
                      action.request_json,'$.workout_data'))=
                    trainlab_json_sha(json_extract(
                      NEW.input_manifest_json,
                      '$.request_json.workouts[' || member.key || ']')))
               OR
               (json_extract(NEW.input_manifest_json,'$.tool_name')='schedule_workout'
                AND CAST(json_extract(
                      NEW.input_manifest_json,'$.request_json.workout_id') AS TEXT)=
                    action.target_external_id
                AND json_extract(
                      NEW.input_manifest_json,'$.request_json.calendar_date')=
                    json_extract(action.request_json,'$.calendar_date'))
               OR
               (json_extract(NEW.input_manifest_json,'$.tool_name')='schedule_workouts'
                AND json_array_length(json_extract(
                      NEW.input_manifest_json,'$.request_json.schedules'))=
                    json_array_length(json_extract(
                      NEW.input_manifest_json,'$.external_action_ids'))
                AND CAST(json_extract(
                      NEW.input_manifest_json,
                      '$.request_json.schedules[' || member.key || '].workout_id'
                    ) AS TEXT)=action.target_external_id
                AND json_extract(
                      NEW.input_manifest_json,
                      '$.request_json.schedules[' || member.key || '].calendar_date'
                    )=json_extract(action.request_json,'$.calendar_date'))
               OR
               (json_extract(NEW.input_manifest_json,'$.tool_name')='unschedule_workout'
                AND CAST(json_extract(
                      NEW.input_manifest_json,
                      '$.request_json.scheduled_workout_id') AS TEXT)=
                    action.target_external_id)
               OR
               (json_extract(NEW.input_manifest_json,'$.tool_name')='unschedule_workouts'
                AND json_array_length(json_extract(
                      NEW.input_manifest_json,
                      '$.request_json.scheduled_workout_ids'))=
                    json_array_length(json_extract(
                      NEW.input_manifest_json,'$.external_action_ids'))
                AND CAST(json_extract(
                      NEW.input_manifest_json,
                      '$.request_json.scheduled_workout_ids[' || member.key || ']'
                    ) AS TEXT)=action.target_external_id)
               OR
               (json_extract(NEW.input_manifest_json,'$.tool_name')='delete_workout'
                AND CAST(json_extract(
                      NEW.input_manifest_json,'$.request_json.workout_id') AS TEXT)=
                    action.target_external_id)
               OR
               (json_extract(NEW.input_manifest_json,'$.tool_name')='delete_workouts'
                AND json_array_length(json_extract(
                      NEW.input_manifest_json,'$.request_json.workout_ids'))=
                    json_array_length(json_extract(
                      NEW.input_manifest_json,'$.external_action_ids'))
                AND CAST(json_extract(
                      NEW.input_manifest_json,
                      '$.request_json.workout_ids[' || member.key || ']'
                    ) AS TEXT)=action.target_external_id)
             )
         )
       ))
    )
  ),0)=0
BEGIN
  SELECT RAISE(ABORT, 'm10_mcp_run_contract_invalid');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_gmail_mcp_result_insert
BEFORE INSERT ON skill_runs
WHEN NEW.operation='mcp_tool_call'
  AND json_extract(NEW.input_manifest_json,'$.m10_role')=
      'm10_external_mcp_call_v1'
  AND json_extract(NEW.input_manifest_json,'$.provider')='gmail'
  AND json_extract(NEW.input_manifest_json,'$.tool_name') IN
      ('send_email','search_emails')
  AND NEW.status='succeeded'
BEGIN
  SELECT RAISE(ABORT, 'm10_gmail_mcp_result_missing');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_gmail_mcp_result_update
BEFORE UPDATE OF status ON skill_runs
WHEN NEW.operation='mcp_tool_call'
  AND json_extract(NEW.input_manifest_json,'$.m10_role')=
      'm10_external_mcp_call_v1'
  AND json_extract(NEW.input_manifest_json,'$.provider')='gmail'
  AND json_extract(NEW.input_manifest_json,'$.tool_name') IN
      ('send_email','search_emails')
  AND NEW.status='succeeded'
  AND (
    (SELECT COUNT(*)
     FROM skill_outputs output
     WHERE output.skill_run_id=NEW.id
       AND output.schema_name='m10_mcp_call_result_v1')<>1
    OR
    (SELECT COUNT(*)
     FROM skill_outputs output
     WHERE output.skill_run_id=NEW.id
       AND output.schema_name='m10_mcp_call_result_v1'
       AND output.output_kind='execution_summary'
       AND output.logical_key='m10:mcp-result:' || NEW.id
       AND output.schema_version='1'
       AND output.title_text='M10 gmail ' ||
           json_extract(NEW.input_manifest_json,'$.tool_name') || ' result'
       AND json_valid(output.content_text)=1
       AND json(output.content_text)=json(output.content_json)
       AND trainlab_valid_schema_payload(
             output.content_json,'m10_mcp_call_result_v1')=1
       AND json_array_length(output.lineage_json)=1
       AND json_extract(output.lineage_json,'$[0].output_id')=
           json_extract(NEW.input_manifest_json,'$.preview_output_id')
       AND json_extract(output.lineage_json,'$[0].output_sha256')=
           json_extract(NEW.input_manifest_json,'$.preview_output_sha256')
       AND json_extract(output.content_json,'$.schema_version')=
           'm10_mcp_call_result_v1'
       AND json_extract(output.content_json,'$.provider')='gmail'
       AND json_extract(output.content_json,'$.tool_name')=
           json_extract(NEW.input_manifest_json,'$.tool_name')
       AND json_extract(output.content_json,'$.request_sha256')=
           json_extract(NEW.input_manifest_json,'$.request_sha256')
       AND json_extract(output.content_json,'$.external_action_ids')=
           json_extract(NEW.input_manifest_json,'$.external_action_ids')
       AND (
         (json_extract(NEW.input_manifest_json,'$.tool_name')='send_email'
          AND json_type(output.content_json,'$.message_id')='text'
          AND json_extract(output.content_json,'$.message_id')<>''
          AND json_extract(output.content_json,'$.match_count')=0
          AND json_array_length(json_extract(
                output.content_json,'$.matched_message_ids'))=0)
         OR
         (json_extract(NEW.input_manifest_json,'$.tool_name')='search_emails'
          AND json_type(output.content_json,'$.message_id')='null'
          AND json_extract(output.content_json,'$.match_count')=1
          AND json_array_length(json_extract(
                output.content_json,'$.matched_message_ids'))=1)
       ))<>1
  )
BEGIN
  SELECT RAISE(ABORT, 'm10_gmail_mcp_result_missing');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_gmail_mcp_result_output_insert
BEFORE INSERT ON skill_outputs
WHEN NEW.schema_name='m10_mcp_call_result_v1'
  AND EXISTS (
    SELECT 1 FROM skill_runs run
    WHERE run.id=NEW.skill_run_id
      AND run.operation='mcp_tool_call'
      AND json_extract(run.input_manifest_json,'$.m10_role')=
          'm10_external_mcp_call_v1'
      AND json_extract(run.input_manifest_json,'$.provider')='gmail'
      AND json_extract(run.input_manifest_json,'$.tool_name') IN
          ('send_email','search_emails')
  )
  AND EXISTS (
    SELECT 1 FROM skill_outputs prior
    WHERE prior.skill_run_id=NEW.skill_run_id
      AND prior.schema_name='m10_mcp_call_result_v1'
  )
BEGIN
  SELECT RAISE(ABORT, 'm10_gmail_mcp_result_duplicate');
END;
CREATE TRIGGER IF NOT EXISTS trg_m10_mcp_run_budget_insert
BEFORE INSERT ON skill_runs
WHEN json_extract(NEW.input_manifest_json,'$.m10_role')='m10_external_mcp_call_v1'
  AND (
    (json_extract(NEW.input_manifest_json,'$.provider')='gmail'
     AND (SELECT COUNT(*) FROM skill_runs prior
          WHERE json_extract(prior.input_manifest_json,'$.m10_role')=
                'm10_external_mcp_call_v1'
            AND json_extract(prior.input_manifest_json,'$.provider')='gmail') >= 26)
    OR
    (json_extract(NEW.input_manifest_json,'$.provider')='garmin'
     AND (SELECT COUNT(*) FROM skill_runs prior
          WHERE json_extract(prior.input_manifest_json,'$.m10_role')=
                'm10_external_mcp_call_v1'
            AND json_extract(prior.input_manifest_json,'$.provider')='garmin') >= 20)
  )
BEGIN
  SELECT RAISE(ABORT, 'm10_mcp_tool_call_budget_exceeded');
END;
CREATE TRIGGER IF NOT EXISTS trg_external_action_budget_insert
BEFORE INSERT ON external_actions
WHEN (SELECT COUNT(*) FROM external_actions prior
      WHERE prior.approval_id=NEW.approval_id)
     >= COALESCE(json_extract(
       (SELECT scope_json FROM approvals WHERE id=NEW.approval_id),
       '$.budget.max_actions'
     ), 0)
BEGIN
  SELECT RAISE(ABORT, 'external_action_budget_exceeded');
END;
CREATE TRIGGER IF NOT EXISTS trg_external_action_revoked_approval_insert
BEFORE INSERT ON external_actions
WHEN EXISTS (
  SELECT 1 FROM approvals revoked
  WHERE revoked.supersedes_approval_id=NEW.approval_id
    AND revoked.decision='revoked'
)
BEGIN
  SELECT RAISE(ABORT, 'external_action_approval_revoked');
END;
CREATE TRIGGER IF NOT EXISTS trg_activity_complete_requires_raw
AFTER INSERT ON activity_inventory
WHEN NEW.collection_state='complete'
  AND NOT EXISTS (
    SELECT 1 FROM raw_files
    WHERE activity_inventory_id=NEW.id
      AND integrity_state='verified'
      AND file_format IN ('fit','gpx','tcx')
  )
BEGIN
  SELECT RAISE(ABORT, 'activity_complete_without_verified_raw');
END;
CREATE TRIGGER IF NOT EXISTS trg_activity_complete_requires_raw_update
AFTER UPDATE OF collection_state ON activity_inventory
WHEN NEW.collection_state='complete'
  AND NOT EXISTS (
    SELECT 1 FROM raw_files
    WHERE activity_inventory_id=NEW.id
      AND integrity_state='verified'
      AND file_format IN ('fit','gpx','tcx')
  )
BEGIN
  SELECT RAISE(ABORT, 'activity_complete_without_verified_raw');
END;
"""


def connect(
    path: Path | None = None,
    *,
    read_only: bool = False,
    immutable: bool = False,
) -> sqlite3.Connection:
    db_path = path or state_path()
    if not read_only:
        if not db_path.is_file():
            raise FileNotFoundError("state_missing")
    if read_only:
        if immutable:
            uri = f"file:{db_path.resolve()}?mode=ro&immutable=1"
        else:
            uri = f"file:{db_path.resolve()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    else:
        connection = sqlite3.connect(db_path)
    connection.create_function(
        "trainlab_sha256",
        1,
        lambda value: hashlib.sha256(
            str(value).replace("\x1f", "\x00").encode("utf-8")
        ).hexdigest(),
    )
    connection.create_function("trainlab_valid_date", 1, _valid_date)
    connection.create_function("trainlab_valid_utc", 1, _valid_utc)
    connection.create_function("trainlab_json_sha", 1, _json_sha)
    connection.create_function(
        "trainlab_valid_schema_payload", 2, _valid_schema_payload
    )
    connection.create_function("trainlab_valid_m10_preview", 1, _valid_m10_preview)
    connection.create_function(
        "trainlab_valid_m10_mcp_request", 2, _valid_m10_mcp_request
    )
    connection.create_function(
        "trainlab_valid_m10_plan_schedule", 2, _valid_m10_plan_schedule
    )
    connection.create_function("trainlab_output_sha", 5, _output_sha)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA recursive_triggers=ON")
    if connection.execute("PRAGMA recursive_triggers").fetchone()[0] != 1:
        connection.close()
        raise RuntimeError("sqlite_recursive_triggers_unavailable")
    connection.execute("PRAGMA busy_timeout=5000")
    if not read_only:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(SCHEMA_SQL)
        connection.execute("PRAGMA user_version=1")
        connection.commit()
    return connection


@contextmanager
def workflow_lock(database: Path):
    """Hold the owner-only workflow lock for one complete candidate run."""
    lock_path = database.parent / "trainlab.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.chmod(lock_path, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(lock_fd)
        raise RuntimeError("state_lock_unavailable") from exc
    try:
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def init_database(path: Path | None = None) -> Path:
    db_path = path or state_path()
    for directory in (
        db_path.parent,
        db_path.parent / "raw",
        db_path.parent / "raw/garmin",
        db_path.parent / "raw/garmin/health",
        db_path.parent / "raw/garmin/activities",
    ):
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
    db_path.touch(mode=0o600, exist_ok=True)
    connection = connect(db_path)
    connection.close()
    os.chmod(db_path, 0o600)
    return db_path


def begin_run(
    connection: sqlite3.Connection,
    *,
    run_key: str,
    workflow_key: str,
    dedupe_key: str,
    skill_name: str,
    operation: str,
    trigger_kind: str,
    input_manifest: Mapping[str, Any] | list[Any],
    input_sha256: str | None = None,
    target_from_date: str | None = None,
    target_through_date: str | None = None,
    parent_run_id: int | None = None,
) -> int:
    now_dt = datetime.now(timezone.utc).replace(microsecond=0)
    now = now_dt.isoformat().replace("+00:00", "Z")
    lease_expires = (now_dt + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    manifest_text = canonical_json(input_manifest)
    digest = input_sha256 or sha256_text(manifest_text)
    connection.execute("BEGIN IMMEDIATE")
    row = connection.execute(
        "SELECT id, status, lease_expires_at_utc FROM skill_runs WHERE run_key=?",
        (run_key,),
    ).fetchone()
    if row and row[1] in {"pending", "running", "succeeded"}:
        if row[1] == "running" and row[2] is not None:
            try:
                expired = (
                    datetime.strptime(str(row[2]), "%Y-%m-%dT%H:%M:%SZ").replace(
                        tzinfo=timezone.utc
                    )
                    <= now_dt
                )
            except ValueError:
                expired = True
            if expired:
                connection.execute(
                    "UPDATE skill_runs SET status='interrupted', finished_at_utc=?, "
                    "heartbeat_at_utc=?, lease_expires_at_utc=NULL, "
                    "error_code='lease_expired' WHERE id=?",
                    (now, now, int(row[0])),
                )
            else:
                connection.commit()
                return int(row[0])
        else:
            connection.commit()
            return int(row[0])
    same_input = connection.execute(
        "SELECT id FROM skill_runs WHERE dedupe_key=? AND input_sha256=? "
        "AND status='succeeded' ORDER BY attempt_no DESC LIMIT 1",
        (dedupe_key, digest),
    ).fetchone()
    if same_input:
        connection.commit()
        return int(same_input[0])
    attempt_no = int(
        connection.execute(
            "SELECT COALESCE(MAX(attempt_no), 0) + 1 FROM skill_runs WHERE dedupe_key=?",
            (dedupe_key,),
        ).fetchone()[0]
    )
    if attempt_no > 1:
        run_key = run_key.removesuffix(":attempt-1") + f":attempt-{attempt_no}"
    cursor = connection.execute(
        """INSERT INTO skill_runs
        (run_key, workflow_key, dedupe_key, parent_run_id, skill_name, operation,
         trigger_kind, target_from_date, target_through_date, attempt_no,
         input_manifest_json, input_sha256, status, created_at_utc,
         started_at_utc, heartbeat_at_utc, lease_expires_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?)""",
        (
            run_key,
            workflow_key,
            dedupe_key,
            parent_run_id,
            skill_name,
            operation,
            trigger_kind,
            target_from_date,
            target_through_date,
            attempt_no,
            manifest_text,
            digest,
            now,
            now,
            now,
            lease_expires,
        ),
    )
    connection.commit()
    return require_lastrowid(cursor)


def finish_run(
    connection: sqlite3.Connection,
    run_id: int,
    *,
    status: str,
    error_code: str | None = None,
    error_summary: str | None = None,
) -> None:
    if status not in {"succeeded", "failed", "blocked", "interrupted", "cancelled"}:
        raise ValueError(f"invalid terminal run status: {status}")
    current = connection.execute(
        "SELECT status FROM skill_runs WHERE id=?", (run_id,)
    ).fetchone()
    if current is None:
        raise ValueError("unknown_run")
    if current[0] not in {"pending", "running"}:
        if current[0] != status:
            raise ValueError("terminal_run_immutable")
        return
    now = utc_now()
    connection.execute(
        "UPDATE skill_runs SET status=?, finished_at_utc=?, heartbeat_at_utc=?, "
        "lease_expires_at_utc=NULL, error_code=?, error_summary=? WHERE id=?",
        (status, now, now, error_code, error_summary, run_id),
    )
    connection.commit()


def heartbeat_run(connection: sqlite3.Connection, run_id: int) -> None:
    """Refresh a running workflow lease without changing its identity."""
    now_dt = datetime.now(timezone.utc).replace(microsecond=0)
    now = now_dt.isoformat().replace("+00:00", "Z")
    lease = (now_dt + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    connection.execute(
        "UPDATE skill_runs SET heartbeat_at_utc=?, lease_expires_at_utc=? "
        "WHERE id=? AND status='running'",
        (now, lease, run_id),
    )
    connection.commit()


def record_skill_result(
    database: Path,
    *,
    skill_name: str,
    operation: str,
    output_kind: str,
    logical_key: str,
    payload: Mapping[str, Any],
    status: str = "succeeded",
    error_code: str | None = None,
    title_text: str | None = None,
    content_text: str | None = None,
    content_html: str | None = None,
    lineage: Iterable[Mapping[str, Any]] = (),
) -> int:
    """Persist one bounded script result and its terminal run state."""

    connection = connect(database)
    try:
        input_manifest = {
            "operation": operation,
            "logical_key": logical_key,
            "payload": dict(payload),
        }
        dedupe_key = sha256_text(canonical_json(input_manifest))
        run_id = begin_run(
            connection,
            run_key=f"{dedupe_key}:attempt-1",
            workflow_key=str(payload.get("workflow_key", logical_key)),
            dedupe_key=dedupe_key,
            skill_name=skill_name,
            operation=operation,
            trigger_kind="skill",
            input_manifest=input_manifest,
        )
        output_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind=output_kind,
            logical_key=logical_key,
            schema_name=f"{skill_name}_{operation}",
            schema_version="1",
            title_text=title_text,
            content_json=dict(payload),
            content_text=(
                content_text
                if content_text is not None
                else json.dumps(payload, ensure_ascii=False, sort_keys=True)
            ),
            content_html=content_html,
            lineage=lineage,
        )
        finish_run(
            connection,
            run_id,
            status=status,
            error_code=error_code,
        )
        return output_id
    finally:
        connection.close()


def append_output(
    connection: sqlite3.Connection,
    *,
    skill_run_id: int,
    output_kind: str,
    logical_key: str,
    schema_name: str,
    schema_version: str,
    content_json: Any | None = None,
    content_text: str | None = None,
    content_html: str | None = None,
    title_text: str | None = None,
    lineage: Iterable[Mapping[str, Any]] = (),
    period_start_date: str | None = None,
    period_end_date: str | None = None,
    supersedes_output_id: int | None = None,
) -> int:
    content_text_json = (
        canonical_json(content_json) if content_json is not None else None
    )
    lineage_items = list(lineage)
    lineage_json = canonical_json(lineage_items)
    digest = sha256_text(
        canonical_json(
            {
                "title": title_text,
                "json": content_json,
                "text": content_text,
                "html": content_html,
                "lineage": lineage_items,
            }
        )
    )
    existing = connection.execute(
        "SELECT id FROM skill_outputs WHERE logical_key=? AND content_sha256=?",
        (logical_key, digest),
    ).fetchone()
    if existing:
        return int(existing[0])
    previous = connection.execute(
        "SELECT id, revision_no FROM skill_outputs WHERE logical_key=? "
        "ORDER BY revision_no DESC LIMIT 1",
        (logical_key,),
    ).fetchone()
    next_revision = int(previous[1]) + 1 if previous else 1
    if previous and supersedes_output_id is None:
        supersedes_output_id = int(previous[0])
    cursor = connection.execute(
        """INSERT INTO skill_outputs
        (skill_run_id, output_kind, logical_key, revision_no, supersedes_output_id,
         period_start_date, period_end_date, schema_name, schema_version, title_text,
         content_json, content_text, content_html, lineage_json, content_sha256, created_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            skill_run_id,
            output_kind,
            logical_key,
            int(next_revision),
            supersedes_output_id,
            period_start_date,
            period_end_date,
            schema_name,
            schema_version,
            title_text,
            content_text_json,
            content_text,
            content_html,
            lineage_json,
            digest,
            utc_now(),
        ),
    )
    connection.commit()
    return require_lastrowid(cursor)


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _online_backup_unlocked(
    source: Path,
    destination: Path,
    *,
    backup_type: str = "manual",
    operation_id: str = "runtime-backup",
) -> Path:
    """Create a verified single-file backup plus a paired private manifest."""

    if backup_type not in {
        "workflow_daily",
        "workflow_weekly",
        "manual",
        "pre_change",
        "external_barrier",
        "pre_restore",
        "post_restore",
    }:
        raise ValueError(f"invalid backup type: {backup_type}")
    source = source.resolve()
    destination = destination.resolve()
    if source.is_symlink() or not source.is_file():
        raise ValueError("backup source must be a regular file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(destination.parent, 0o700)
    manifest = destination.with_suffix(".manifest.json")
    if destination.exists() or manifest.exists():
        raise FileExistsError(destination)
    nonce = secrets.token_hex(8)
    temporary = destination.with_name(f".{destination.name}.{nonce}.tmp")
    temporary_manifest = temporary.with_suffix(".manifest.json")
    source_wal = Path(f"{source}-wal")
    source_can_be_immutable = not source_wal.exists() or source_wal.stat().st_size == 0
    source_connection = connect(
        source,
        read_only=True,
        immutable=source_can_be_immutable,
    )
    target_connection = sqlite3.connect(temporary)
    try:
        source_connection.backup(target_connection)
        target_connection.commit()
        integrity = target_connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = list(target_connection.execute("PRAGMA foreign_key_check"))
        version = target_connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in target_connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        counts = {
            table: target_connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in sorted(EXPECTED_TABLES & tables)
        }
        highest_ids = {
            table: target_connection.execute(
                f"SELECT COALESCE(MAX(id), 0) FROM {table}"
            ).fetchone()[0]
            for table in sorted(EXPECTED_TABLES & tables)
        }
        nonterminal_actions = target_connection.execute(
            "SELECT COUNT(*) FROM external_actions "
            "WHERE status IN ('prepared','in_progress','unknown')"
        ).fetchone()[0]
        raw_index = target_connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(byte_size), 0), "
            "SUM(CASE WHEN integrity_state='verified' THEN 1 ELSE 0 END) "
            "FROM raw_files"
        ).fetchone()
    finally:
        target_connection.close()
        source_connection.close()
    if integrity != "ok" or foreign_keys or version != 1 or tables != EXPECTED_TABLES:
        temporary.unlink(missing_ok=True)
        raise ValueError("backup_validation_failed")
    os.chmod(temporary, 0o600)
    _fsync_file(temporary)
    database_sha = sha256_file(temporary)
    filename_match = re.fullmatch(
        r"trainlab-(?P<stamp>\d{8}T\d{6}Z)-(?P<operation>[A-Za-z0-9._-]+)-(?P<digest>[0-9a-f]{12,64})\.db",
        destination.name,
    )
    if not filename_match:
        temporary.unlink(missing_ok=True)
        raise ValueError("backup_filename_invalid")
    if not database_sha.startswith(filename_match.group("digest")):
        destination = destination.with_name(
            f"trainlab-{filename_match.group('stamp')}-{filename_match.group('operation')}-{database_sha}.db"
        )
        manifest = destination.with_suffix(".manifest.json")
        if destination.exists() or manifest.exists():
            temporary.unlink(missing_ok=True)
            raise FileExistsError(destination)
    expected_created = (
        datetime.strptime(filename_match.group("stamp"), "%Y%m%dT%H%M%SZ")
        .replace(tzinfo=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    created_at = expected_created
    manifest_payload = {
        "schema_version": "1",
        "backup_type": backup_type,
        "operation_id": operation_id,
        "database_sha256": database_sha,
        "database_size": temporary.stat().st_size,
        "user_version": version,
        "table_counts": counts,
        "highest_ids": highest_ids,
        "nonterminal_external_actions": nonterminal_actions,
        "raw_index": {
            "file_count": int(raw_index[0]),
            "byte_size": int(raw_index[1]),
            "verified_count": int(raw_index[2] or 0),
        },
        "code_version": "ai-skills-runtime-v1",
        "skill_versions": {
            "garmin-sync": "1",
            "training-coach": "1",
            "weekly-fitness-summary": "1",
            "garmin-training-sender": "1",
            "training-report-publisher": "1",
            "gmail-sender": "1",
        },
        "integrity_check": integrity,
        "foreign_key_errors": len(foreign_keys),
        "raw_validation_level": "index_only",
        "created_at_utc": created_at,
    }
    temporary_manifest.write_text(
        canonical_json(manifest_payload) + "\n", encoding="utf-8"
    )
    os.chmod(temporary_manifest, 0o600)
    _fsync_file(temporary_manifest)
    _fsync_directory(destination.parent)
    os.replace(temporary, destination)
    os.replace(temporary_manifest, manifest)
    _fsync_directory(destination.parent)
    return manifest


def online_backup(
    source: Path,
    destination: Path,
    *,
    backup_type: str = "manual",
    operation_id: str = "runtime-backup",
) -> Path:
    """Create a backup while holding the same exclusive state lock as restore/cron."""
    source = source.resolve()
    lock_path = source.parent / "trainlab.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.chmod(lock_path, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(lock_fd)
        raise ValueError("state_lock_unavailable") from exc
    try:
        return _online_backup_unlocked(
            source,
            destination,
            backup_type=backup_type,
            operation_id=operation_id,
        )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
