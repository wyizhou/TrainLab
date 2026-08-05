"""S5-06 fixed-command, fail-closed downstream process boundary."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import re
import threading
import time
from datetime import date, datetime, timedelta
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from trainlab.process_liveness import process_group_has_live_members
from trainlab.runtime_environment import bounded_runtime_path


Layer = Literal["foundation", "garmin", "analysis", "mail"]
ResultKind = Literal["accepted", "untrusted", "timeout_unknown"]

_ROOT = Path(__file__).resolve().parents[3]
_EXECUTABLE = _ROOT / ".venv/bin/trainlab"
_PYTHON = _ROOT / ".venv/bin/python"
_MAX_OUTPUT = 1_048_576
_GRACE_SECONDS = 2
_ENV = {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "Asia/Hong_Kong"}
_SCHEMAS = {
    "foundation": _ROOT / "harness/schemas/foundation_receipt.schema.json",
    "garmin": _ROOT / "harness/schemas/garmin_sync_receipt.schema.json",
    "analysis": _ROOT / "src/trainlab/analysis/schemas/analysis_receipt.schema.json",
    "mail": _ROOT / "harness/schemas/mail_receipt.schema.json",
}
_MANIFEST = _ROOT / "harness/schemas/orchestration_interface_manifest.json"
_MODES = {
    "foundation": frozenset({"init", "status", "verify"}),
    "garmin": frozenset({"full", "incremental", "snapshot", "repair", "audit", "status"}),
    "analysis": frozenset({"daily", "weekly", "revise_plan", "regenerate", "retry_delivery", "reconcile_delivery", "status"}),
    "mail": frozenset({"run", "poll", "process", "deliver_response", "reconcile", "status"}),
}
_REQUEST_REQUIRED = {
    "foundation": frozenset({"mode", "invocation_id", "target_schema_version", "requested_at_utc"}),
    "garmin": frozenset({
        "mode", "health_from_local_date", "through_local_date",
        "snapshot_local_date", "resource_kinds", "activity_ids",
        "repair_strategy", "invocation_id",
    }),
    "analysis": frozenset({
        "mode", "subject_id", "invocation_id", "summary_local_date",
        "advice_local_date", "as_of_local_date", "plan_id",
        "reason_event_id", "effective_local_date", "artifact_id",
        "delivery_id", "regeneration_reason_code", "requested_at_utc",
    }),
    "mail": frozenset({
        "mode", "subject_id", "invocation_id", "mail_message_ids",
        "mail_response_artifact_ids", "dependency_analysis_artifact_ids",
        "mail_delivery_ids", "thread_id", "max_items", "max_threads",
        "deadline_seconds", "regeneration_reason_code", "requested_at_utc",
    }),
}
_EXIT_BY_LAYER = {
    "foundation": {"initialized": 0, "already_initialized": 0, "ready": 0, "incompatible": 10, "lock_busy": 11, "failed": 20},
    "garmin": {"succeeded": 0, "partial": 10, "deferred": 11, "lock_busy": 12, "auth_required": 20, "failed": 21},
    "analysis": {"succeeded": 0, "unchanged": 0, "partial": 10, "deferred": 11, "lock_busy": 12, "rejected": 20, "failed": 21},
    "mail": {"succeeded": 0, "unchanged": 0, "partial": 10, "deferred": 11, "lock_busy": 12, "auth_required": 20, "rejected": 21, "failed": 22},
}
_TIMEOUTS = {
    "foundation": {mode: 60 for mode in _MODES["foundation"]},
    "garmin": {
        "full": 86_400,
        "incremental": 3_600,
        "snapshot": 900,
        "repair": 3_600,
        "audit": 1_800,
        "status": 60,
    },
    "analysis": {mode: 900 for mode in _MODES["analysis"]},
    "mail": {mode: 300 for mode in _MODES["mail"]},
}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$")
_INVOCATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SUBJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MODE_FIELDS = {
    ("garmin", "full"): frozenset({"health_from_local_date", "through_local_date"}),
    ("garmin", "incremental"): frozenset({"through_local_date"}),
    ("garmin", "snapshot"): frozenset({"snapshot_local_date"}),
    ("garmin", "repair"): frozenset({"health_from_local_date", "through_local_date", "resource_kinds", "activity_ids", "repair_strategy"}),
    ("garmin", "audit"): frozenset({"health_from_local_date", "through_local_date"}),
    ("analysis", "daily"): frozenset({"subject_id", "summary_local_date", "advice_local_date"}),
    ("analysis", "weekly"): frozenset({"subject_id", "as_of_local_date"}),
    ("analysis", "revise_plan"): frozenset({"subject_id", "plan_id", "reason_event_id", "effective_local_date"}),
    ("analysis", "regenerate"): frozenset({"subject_id", "artifact_id", "regeneration_reason_code"}),
    ("analysis", "retry_delivery"): frozenset({"subject_id", "delivery_id"}),
    ("analysis", "reconcile_delivery"): frozenset({"subject_id", "delivery_id"}),
    ("analysis", "status"): frozenset({"subject_id", "run_key"}),
    ("mail", "run"): frozenset({"subject_id", "max_items", "deadline_seconds"}),
    ("mail", "poll"): frozenset({"subject_id", "max_threads"}),
    ("mail", "process"): frozenset({"subject_id", "mail_message_id", "dependency_analysis_artifact_ids", "regeneration_reason_code"}),
    ("mail", "deliver_response"): frozenset({"subject_id", "mail_response_artifact_id"}),
    ("mail", "reconcile"): frozenset({"subject_id", "delivery_id"}),
    ("mail", "status"): frozenset({"subject_id", "run_key", "mail_message_id"}),
}
_REQUIRED_FIELDS = {
    ("analysis", "revise_plan"): frozenset({"plan_id", "reason_event_id"}),
    ("analysis", "regenerate"): frozenset({"artifact_id", "regeneration_reason_code"}),
    ("analysis", "retry_delivery"): frozenset({"delivery_id"}),
    ("analysis", "reconcile_delivery"): frozenset({"delivery_id"}),
    ("mail", "process"): frozenset({"mail_message_id"}),
    ("mail", "deliver_response"): frozenset({"mail_response_artifact_id"}),
    ("mail", "reconcile"): frozenset({"delivery_id"}),
}
_PROGRESS_STATUSES = frozenset({"succeeded", "unchanged", "partial"})
_FAILURE_STATUSES = frozenset({"deferred", "lock_busy", "auth_required", "rejected", "failed"})
_MAX_MAIL_RECEIPT_IDS = 64


class SubprocessBoundaryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DownstreamCall:
    layer: Layer
    mode: str
    invocation_id: str | None
    request_sha256: str | None
    timeout_seconds: int | None = None
    # Only static, typed identity arguments are admitted; no command/cwd/env.
    subject_id: str | int | None = None
    logical_local_date: str | None = None
    health_from_local_date: str | None = None
    through_local_date: str | None = None
    snapshot_local_date: str | None = None
    resource_kinds: tuple[str, ...] = ()
    activity_ids: tuple[str, ...] = ()
    repair_strategy: str | None = None
    summary_local_date: str | None = None
    advice_local_date: str | None = None
    as_of_local_date: str | None = None
    plan_id: str | None = None
    reason_event_id: str | None = None
    effective_local_date: str | None = None
    artifact_id: str | None = None
    delivery_id: str | None = None
    mail_message_id: str | None = None
    mail_response_artifact_id: str | None = None
    max_items: int | None = None
    max_threads: int | None = None
    deadline_seconds: int | None = None
    dependency_analysis_artifact_ids: tuple[str, ...] = ()
    regeneration_reason_code: str | None = None
    run_key: str | None = None


@dataclass(frozen=True, slots=True)
class DownstreamResult:
    kind: ResultKind
    error_code: str | None
    receipt: Mapping[str, Any] | None
    receipt_sha256: str | None
    request_sha256: str
    exit_code: int | None


def canonical_request_sha256(call: DownstreamCall) -> str:
    """Hash the complete typed request, never a caller asserted opaque value."""
    if type(call) is not DownstreamCall:
        raise SubprocessBoundaryError("subprocess_call_invalid")
    document = asdict(call)
    document["request_sha256"] = None
    try:
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise SubprocessBoundaryError("subprocess_request_json_invalid") from error
    return hashlib.sha256(canonical).hexdigest()


def _argv(call: DownstreamCall) -> tuple[str, ...]:
    """The only command builder: no caller-provided fragment is executable."""
    if call.layer not in _MODES or call.mode not in _MODES[call.layer]:
        raise SubprocessBoundaryError("subprocess_mode_not_allowed")
    if call.timeout_seconds is not None:
        raise SubprocessBoundaryError("subprocess_timeout_static_only")
    allowed = _MODE_FIELDS.get((call.layer, call.mode), frozenset())
    common = {"layer", "mode", "invocation_id", "request_sha256", "timeout_seconds"}
    values = asdict(call)
    for name, value in values.items():
        if name in common or name in allowed: continue
        if value not in (None, (), ""):
            raise SubprocessBoundaryError("subprocess_field_forbidden")
    for name in _REQUIRED_FIELDS.get((call.layer, call.mode), frozenset()):
        if values[name] in (None, (), ""):
            raise SubprocessBoundaryError("subprocess_field_required")
    computed_hash = canonical_request_sha256(call)
    if call.request_sha256 is not None and (type(call.request_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", call.request_sha256) or call.request_sha256 != computed_hash):
        raise SubprocessBoundaryError("subprocess_request_hash_invalid")
    if call.invocation_id is not None and (
        type(call.invocation_id) is not str
        or not _INVOCATION_ID.fullmatch(call.invocation_id)
    ):
        raise SubprocessBoundaryError("subprocess_invocation_invalid")
    for value in (call.max_items, call.max_threads, call.deadline_seconds):
        if value is not None and (type(value) is not int or not 1 <= value <= 10_000):
            raise SubprocessBoundaryError("subprocess_limit_invalid")
    if call.repair_strategy is not None and call.repair_strategy not in {"auto", "refetch", "reparse", "reconcile"}:
        raise SubprocessBoundaryError("subprocess_repair_strategy_invalid")
    for collection in (call.resource_kinds, call.activity_ids, call.dependency_analysis_artifact_ids):
        if type(collection) is not tuple or len(collection) > 64 or len(set(collection)) != len(collection):
            raise SubprocessBoundaryError("subprocess_collection_invalid")
        if any(type(item) is not str or not _ID.fullmatch(item) for item in collection):
            raise SubprocessBoundaryError("subprocess_collection_invalid")
    if call.regeneration_reason_code is not None and (type(call.regeneration_reason_code) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", call.regeneration_reason_code) is None):
        raise SubprocessBoundaryError("subprocess_reason_invalid")
    for value in (call.health_from_local_date, call.through_local_date, call.snapshot_local_date, call.summary_local_date, call.advice_local_date, call.as_of_local_date, call.effective_local_date):
        if value is not None and (type(value) is not str or not _DATE.fullmatch(value)):
            raise SubprocessBoundaryError("subprocess_date_invalid")
        if value is not None:
            try: date.fromisoformat(value)
            except ValueError: raise SubprocessBoundaryError("subprocess_date_invalid")
    if call.health_from_local_date is not None and call.through_local_date is not None and call.health_from_local_date > call.through_local_date:
        raise SubprocessBoundaryError("subprocess_date_range_invalid")
    def require(value: str | None, name: str) -> str:
        if type(value) is not str or not _ID.fullmatch(value):
            raise SubprocessBoundaryError(f"subprocess_{name}_required")
        return value
    def require_invocation(value: str | None) -> str:
        if type(value) is not str or not _INVOCATION_ID.fullmatch(value):
            raise SubprocessBoundaryError("subprocess_invocation_required")
        return value
    # The project entrypoint and every positional mode are frozen literals.
    prefix = (str(_EXECUTABLE),)
    if call.layer == "foundation":
        return (*prefix, "foundation", "--invocation-id", require(call.invocation_id, "invocation"), call.mode)
    if call.layer == "garmin":
        direct = call.mode in {"repair", "audit", "status"}
        base = (*prefix, "garmin", "--invocation-id", require(call.invocation_id, "invocation"), call.mode) if direct else (*prefix, "garmin", "--invocation-id", require(call.invocation_id, "invocation"), "sync", call.mode)
        if call.mode == "incremental" and call.through_local_date: return (*base, "--through", call.through_local_date)
        if call.mode == "full":
            args = list(base)
            if call.health_from_local_date: args.extend(("--health-from", call.health_from_local_date))
            if call.through_local_date: args.extend(("--through", call.through_local_date))
            return tuple(args)
        if call.mode == "snapshot" and call.snapshot_local_date: return (*base, "--date", call.snapshot_local_date)
        if call.mode == "repair":
            args = list(base)
            if call.health_from_local_date: args.extend(("--from", call.health_from_local_date))
            if call.through_local_date: args.extend(("--through", call.through_local_date))
            for item in call.resource_kinds: args.extend(("--resource", item))
            for item in call.activity_ids: args.extend(("--activity-id", item))
            if call.repair_strategy: args.extend(("--strategy", call.repair_strategy))
            return tuple(args)
        if call.mode == "audit":
            args = list(base)
            if call.health_from_local_date: args.extend(("--from", call.health_from_local_date))
            if call.through_local_date: args.extend(("--through", call.through_local_date))
            return tuple(args)
        return base
    if call.layer == "analysis":
        if type(call.subject_id) is not str or not _SUBJECT_ID.fullmatch(call.subject_id): raise SubprocessBoundaryError("subprocess_subject_required")
        if call.mode == "status":
            if call.invocation_id is not None:
                raise SubprocessBoundaryError("subprocess_status_invocation_forbidden")
            base = [str(_EXECUTABLE), "run", "--slot", "morning", "--analysis-only", "--status"]
            if call.run_key is not None:
                base.extend(("--run-key", require(call.run_key, "run_key")))
            return tuple(base)
        invocation = require(call.invocation_id, "invocation")
        base = [str(_EXECUTABLE), "run", "--slot", "morning", "--analysis-only", "--invocation-id", invocation]
        if call.mode == "daily":
            if call.summary_local_date is not None:
                base.extend(("--summary-date", call.summary_local_date))
                if call.advice_local_date is not None and (
                    date.fromisoformat(call.advice_local_date)
                    != date.fromisoformat(call.summary_local_date) + timedelta(days=1)
                ):
                    raise SubprocessBoundaryError("subprocess_advice_date_mismatch")
            elif call.advice_local_date is not None:
                raise SubprocessBoundaryError("subprocess_advice_date_mismatch")
            base.append("--deliver")
            return tuple(base)
        if call.mode == "weekly":
            base.append("--weekly")
            if call.as_of_local_date is not None:
                base.extend(("--as-of-date", call.as_of_local_date))
            base.append("--deliver")
            return tuple(base)
        if call.mode == "revise_plan":
            if (
                not isinstance(call.plan_id, str)
                or re.fullmatch(r"[1-9][0-9]{0,18}", call.plan_id) is None
                or not isinstance(call.reason_event_id, str)
                or re.fullmatch(r"[1-9][0-9]{0,18}", call.reason_event_id) is None
            ):
                raise SubprocessBoundaryError(
                    "subprocess_plan_revision_target_required"
                )
            base.extend(
                (
                    "--revise-plan",
                    "--plan-id",
                    call.plan_id,
                    "--reason-event-id",
                    call.reason_event_id,
                )
            )
            if call.effective_local_date is not None:
                base.extend(("--effective-date", call.effective_local_date))
            base.append("--deliver")
            return tuple(base)
        if call.mode in {"retry_delivery", "reconcile_delivery"}:
            if not isinstance(call.delivery_id, str) or re.fullmatch(r"[1-9][0-9]{0,18}", call.delivery_id) is None:
                raise SubprocessBoundaryError("subprocess_delivery_id_required")
            base.extend((
                "--retry-delivery" if call.mode == "retry_delivery" else "--reconcile-delivery",
                call.delivery_id,
            ))
            return tuple(base)
        if call.mode == "regenerate":
            if (
                not isinstance(call.artifact_id, str)
                or re.fullmatch(r"[1-9][0-9]{0,18}", call.artifact_id) is None
            ):
                raise SubprocessBoundaryError("subprocess_artifact_id_required")
            reason = require(call.regeneration_reason_code, "regeneration_reason")
            return (
                str(_EXECUTABLE), "run", "--slot", "morning", "--analysis-only",
                "--regenerate", "--artifact-id", call.artifact_id,
                "--regenerate-reason", reason, "--invocation-id", invocation,
                "--deliver",
            )
        raise SubprocessBoundaryError("subprocess_mode_not_allowed")
    if type(call.subject_id) is not int or call.subject_id <= 0: raise SubprocessBoundaryError("subprocess_subject_required")
    base = [str(_PYTHON), "-m", "trainlab.mail_agent.cli", "--subject-id", str(call.subject_id), "--invocation-id", require_invocation(call.invocation_id), call.mode.replace("_", "-")]
    fields = {"process": (("--message-id", call.mail_message_id),), "deliver_response": (("--response-id", call.mail_response_artifact_id),), "reconcile": (("--delivery-id", call.delivery_id),)}.get(call.mode, ())
    for flag, value in fields:
        base.extend((flag, require(value, "target")))
    if call.mode == "run":
        if call.max_items is not None: base.extend(("--max-items", str(call.max_items)))
        if call.deadline_seconds is not None: base.extend(("--deadline-seconds", str(call.deadline_seconds)))
    if call.mode == "poll" and call.max_threads is not None: base.extend(("--max-threads", str(call.max_threads)))
    if call.mode == "process":
        for artifact in call.dependency_analysis_artifact_ids: base.extend(("--dependency-artifact-id", require(artifact, "target")))
        if call.regeneration_reason_code is not None: base.extend(("--regenerate-reason", call.regeneration_reason_code))
    if call.mode == "status" and call.run_key is not None: base.extend(("--run-key", require(call.run_key, "run_key")))
    if call.mode == "status" and call.mail_message_id is not None: base.extend(("--message-id", require(call.mail_message_id, "target")))
    return tuple(base)


def _load_interface(layer: Layer) -> tuple[Mapping[str, Any] | None, str | None]:
    try:
        raw = _MANIFEST.read_bytes()
    except (OSError, MemoryError):
        return None, "interface_manifest_unavailable"
    if len(raw) > _MAX_OUTPUT:
        return None, "interface_manifest_invalid"
    try:
        document = _parse_receipt_json(raw)
        if (
            type(document) is not dict
            or document.get("schema_version") != "1"
            or type(document.get("interfaces")) is not dict
        ):
            raise ValueError("interface_manifest_shape")
        interfaces = document["interfaces"]
        for known_layer in _MODES:
            candidate = interfaces.get(known_layer)
            if type(candidate) is not dict:
                raise ValueError("interface_manifest_shape")
            for field in ("modes", "statuses", "request_required", "receipt_required"):
                items = candidate.get(field)
                if (
                    type(items) is not list
                    or any(type(item) is not str for item in items)
                    or len(items) != len(set(items))
                ):
                    raise ValueError("interface_manifest_shape")
        interface = interfaces[layer]
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, RecursionError):
        return None, "interface_manifest_invalid"
    return interface, None


def _load_receipt_validator(layer: Layer) -> tuple[Draft202012Validator | None, str | None]:
    try:
        raw = _SCHEMAS[layer].read_bytes()
    except (KeyError, OSError, MemoryError):
        return None, "receipt_schema_unavailable"
    if len(raw) > _MAX_OUTPUT:
        return None, "receipt_schema_invalid"
    try:
        schema = _parse_receipt_json(raw)
        if type(schema) is not dict:
            raise ValueError("receipt_schema_shape")
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        required = schema.get("required")
        if type(required) is not list or any(type(item) is not str for item in required) or len(required) != len(set(required)):
            raise ValueError("receipt_schema_shape")
    except Exception:
        # jsonschema can raise SchemaError, and maliciously deep local JSON can
        # raise RecursionError. Neither local contents nor paths cross this
        # boundary.
        return None, "receipt_schema_invalid"
    return validator, None


def _validate_receipt(call: DownstreamCall, value: object, exit_code: int) -> tuple[Mapping[str, Any] | None, str | None]:
    interface, interface_error = _load_interface(call.layer)
    if interface is None:
        return None, interface_error
    try:
        manifest_modes = set(interface["modes"])
        manifest_statuses = set(interface["statuses"])
        manifest_request_required = set(interface["request_required"])
        manifest_required = set(interface["receipt_required"])
    except (KeyError, TypeError, ValueError, RecursionError):
        return None, "interface_manifest_invalid"
    if call.layer == "foundation":
        manifest_modes.discard("migrate")  # supervisor bootstrap never migrates
    if call.layer == "garmin":
        manifest_modes.discard("auth")  # interactive owner operation, never supervisor
    if (
        manifest_modes != set(_MODES[call.layer])
        or manifest_statuses != set(_EXIT_BY_LAYER[call.layer])
        or manifest_request_required != set(_REQUEST_REQUIRED[call.layer])
    ):
        return None, "interface_manifest_mismatch"
    if type(value) is not dict:
        return None, "receipt_not_object"
    validator, schema_error = _load_receipt_validator(call.layer)
    if validator is None:
        return None, schema_error
    try:
        schema_required = set(validator.schema["required"])
        errors = list(validator.iter_errors(value))
    except (KeyError, TypeError, ValueError, RecursionError):
        return None, "receipt_schema_invalid"
    except Exception:
        return None, "receipt_schema_invalid"
    if manifest_required != schema_required:
        return None, "interface_schema_mismatch"
    if errors:
        return None, "receipt_schema_invalid"
    if value.get("schema_version") != "1":
        return None, "receipt_schema_version_mismatch"
    if value.get("mode") != call.mode:
        return None, "receipt_mode_mismatch"
    parsed_times: dict[str, datetime] = {}
    for field in ("started_at_utc", "completed_at_utc"):
        stamp = value.get(field)
        if stamp is not None:
            if type(stamp) is not str or not stamp.endswith("Z"):
                return None, "receipt_time_invalid"
            try: parsed_times[field] = datetime.fromisoformat(stamp[:-1] + "+00:00")
            except ValueError: return None, "receipt_time_invalid"
    if len(parsed_times) == 2 and parsed_times["completed_at_utc"] < parsed_times["started_at_utc"]:
        return None, "receipt_time_order_invalid"
    if call.layer in {"foundation", "analysis", "mail"} and value.get("invocation_id") != call.invocation_id:
        return None, "receipt_invocation_mismatch"
    if call.layer == "garmin":
        requested = value.get("requested_range")
        effective = value.get("effective_range")
        if type(requested) is not dict:
            return None, "receipt_target_mismatch"
        if type(effective) is not dict:
            return None, "receipt_target_mismatch"
        if call.through_local_date is not None and requested.get("through") != call.through_local_date:
            return None, "receipt_target_mismatch"
        if call.health_from_local_date is not None and requested.get("from") != call.health_from_local_date:
            return None, "receipt_target_mismatch"
        if call.snapshot_local_date is not None:
            # Garmin records the user-requested snapshot date in ``through``;
            # ``from`` remains null because snapshot has no range-style CLI
            # argument.  The effective range, once work made progress, must
            # still prove that exactly the requested local date was handled.
            if requested.get("from") is not None or requested.get("through") != call.snapshot_local_date:
                return None, "receipt_target_mismatch"
            if value.get("status") in _PROGRESS_STATUSES and (
                effective.get("from") != call.snapshot_local_date
                or effective.get("through") != call.snapshot_local_date
            ):
                return None, "receipt_target_mismatch"
        for bounds in (requested, effective):
            left, right = bounds.get("from"), bounds.get("through")
            if left is not None and right is not None and (type(left) is not str or type(right) is not str or left > right):
                return None, "receipt_range_invalid"
    if call.layer == "analysis":
        run_key = value.get("run_key")
        escape = lambda item: str(item).replace(":", "%3A")
        target = (call.summary_local_date or "default") if call.mode == "daily" else (call.as_of_local_date or "default") if call.mode == "weekly" else f"{escape(call.plan_id)}:{escape(call.reason_event_id)}" if call.mode == "revise_plan" else escape(call.artifact_id or "missing") if call.mode == "regenerate" else escape(call.delivery_id or "missing")
        expected_key = call.run_key if call.mode == "status" and call.run_key else f"analysis:{call.subject_id}:status:current:read_only" if call.mode == "status" else f"analysis:{call.subject_id}:{call.mode}:{target}:{escape(call.invocation_id)}"
        if run_key != expected_key:
            return None, "receipt_run_key_mismatch"
        periods = value.get("target_periods")
        if type(periods) is not dict: return None, "receipt_target_mismatch"
        def exact(name: str, start: str, end: str) -> bool:
            item = periods.get(name)
            return type(item) is dict and item.get("start_local_date") == start and item.get("end_local_date") == end
        if call.mode == "daily":
            for name, target_date in (("summary", call.summary_local_date), ("advice", call.advice_local_date)):
                if target_date is not None and not exact(name, target_date, target_date): return None, "receipt_target_mismatch"
        elif call.mode == "weekly" and call.as_of_local_date is not None:
            anchor = date.fromisoformat(call.as_of_local_date)
            if not exact("review", (anchor - timedelta(days=7)).isoformat(), (anchor - timedelta(days=1)).isoformat()) or not exact("plan", anchor.isoformat(), (anchor + timedelta(days=6)).isoformat()): return None, "receipt_target_mismatch"
        elif call.mode == "revise_plan" and call.effective_local_date is not None and not exact("plan", call.effective_local_date, periods.get("plan", {}).get("end_local_date") if type(periods.get("plan")) is dict else ""):
            return None, "receipt_target_mismatch"
        if call.artifact_id is not None and call.mode != "regenerate" and call.artifact_id not in set(value.get("artifact_ids", ())):
            return None, "receipt_artifact_mismatch"
        delivery = value.get("delivery")
        if call.delivery_id is not None and (type(delivery) is not dict or delivery.get("delivery_id") != call.delivery_id):
            return None, "receipt_delivery_mismatch"
    if call.layer == "mail":
        expected_key = call.run_key if call.mode == "status" and call.run_key else f"mail:{call.subject_id}:{call.mode}:{call.invocation_id}"
        if value.get("run_key") != expected_key: return None, "receipt_run_key_mismatch"
        claimed = {
            "processed_message_ids": (call.mail_message_id,),
            "mail_response_artifact_ids": (call.mail_response_artifact_id,),
            "mail_delivery_ids": (call.delivery_id,),
        }
        status = value.get("status")
        required_target = {
            "process": ("processed_message_ids", call.mail_message_id),
            "deliver_response": ("mail_response_artifact_ids", call.mail_response_artifact_id),
            "reconcile": ("mail_delivery_ids", call.delivery_id),
        }.get(call.mode)
        for field, requested in claimed.items():
            identifiers = value.get(field)
            if type(identifiers) is not list or len(identifiers) > _MAX_MAIL_RECEIPT_IDS:
                return None, "receipt_message_identity_invalid"
            if any(type(item) is not str or _ID.fullmatch(item) is None for item in identifiers):
                return None, "receipt_message_identity_invalid"
            if len(identifiers) != len(set(identifiers)):
                return None, "receipt_message_identity_invalid"
            if status in _FAILURE_STATUSES and identifiers:
                return None, "receipt_failure_identity_invalid"
            if status in _PROGRESS_STATUSES:
                # Targeted write/recovery calls have an exact one-ID receipt
                # contract. Other output fields may contain newly-created,
                # controlled IDs from the lower layer.
                if required_target is not None and field == required_target[0] and identifiers != [required_target[1]]:
                    return None, "receipt_message_mismatch"
    status = value.get("status")
    expected = _EXIT_BY_LAYER[call.layer].get(status)
    if expected is None or exit_code != expected:
        return None, "receipt_exit_mismatch"
    try:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError):
        return None, "receipt_json_invalid"
    return value, hashlib.sha256(canonical).hexdigest()


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("receipt_duplicate_key")
        value[key] = item
    return value


def _reject_json_constant(_value: str) -> None:
    raise ValueError("receipt_non_finite_number")


def _parse_receipt_json(payload: bytes) -> object:
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError("receipt_utf8_bom")
    text = payload.decode("utf-8")
    return json.loads(
        text,
        object_pairs_hook=_strict_json_object,
        parse_constant=_reject_json_constant,
    )


class SubprocessRunner:
    """Runs a frozen argv in a separate process group and never returns raw IO."""

    def __init__(self, *, output_limit: int = _MAX_OUTPUT, grace_seconds: int = _GRACE_SECONDS) -> None:
        if type(output_limit) is not int or not 1_024 <= output_limit <= _MAX_OUTPUT:
            raise SubprocessBoundaryError("subprocess_output_limit_invalid")
        if type(grace_seconds) is not int or not 1 <= grace_seconds <= 30:
            raise SubprocessBoundaryError("subprocess_grace_invalid")
        self._root = _ROOT
        self._limit = output_limit
        self._grace = grace_seconds

    def run(self, call: DownstreamCall) -> DownstreamResult:
        argv = _argv(call)
        request_hash = canonical_request_sha256(call)
        try:
            process = subprocess.Popen(argv, cwd=self._root, env=self._environment(), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, close_fds=True,
                start_new_session=True, text=False)
        except OSError:
            return DownstreamResult("untrusted", "process_start_failed", None, None, request_hash, None)
        try:
            stdout, stderr = self._communicate_bounded(process, _TIMEOUTS[call.layer][call.mode])
        except subprocess.TimeoutExpired:
            if not self._terminate_group(process):
                return DownstreamResult("untrusted", "process_group_unreaped", None, None, request_hash, process.returncode)
            # Send/receipt outcomes are unknowable; the planner will reconcile.
            return DownstreamResult("timeout_unknown", "process_timeout_unknown", None, None, request_hash, None)
        except ValueError as exc:
            error = str(exc)
            if error == "process_group_unreaped":
                return DownstreamResult("untrusted", "process_group_unreaped", None, None, request_hash, process.returncode)
            # _communicate_bounded performs this cleanup itself for real pipes,
            # but keep the public boundary defensive for controlled doubles and
            # future branches: never downgrade an unconfirmed kill to a normal
            # cap/read failure.
            if error in {"process_output_limit", "process_reader_error", "process_reader_unreaped"} and not self._terminate_group(process):
                return DownstreamResult("untrusted", "process_group_unreaped", None, None, request_hash, process.returncode)
            if error == "process_output_limit":
                return DownstreamResult("untrusted", "process_output_limit", None, None, request_hash, process.returncode)
            if error == "process_reader_error":
                return DownstreamResult("untrusted", "process_reader_error", None, None, request_hash, process.returncode)
            return DownstreamResult("untrusted", "process_io_invalid", None, None, request_hash, process.returncode)
        if len(stdout) > self._limit or len(stderr) > self._limit:
            if not self._terminate_group(process):
                return DownstreamResult("untrusted", "process_group_unreaped", None, None, request_hash, process.returncode)
            return DownstreamResult("untrusted", "process_output_limit", None, None, request_hash, process.returncode)
        try:
            # json.loads accepts surrounding whitespace but rejects a second
            # document or any diagnostic prefix/suffix.
            item = _parse_receipt_json(stdout)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            return DownstreamResult("untrusted", "receipt_json_invalid", None, None, request_hash, process.returncode)
        receipt, digest = _validate_receipt(call, item, process.returncode)
        if receipt is None:
            return DownstreamResult("untrusted", digest, None, None, request_hash, process.returncode)
        return DownstreamResult("accepted", None, receipt, digest, request_hash, process.returncode)

    @staticmethod
    def _environment() -> dict[str, str]:
        """Create the only environment inherited by lower-layer tools."""
        return {"PATH": bounded_runtime_path(), **_ENV}

    def _communicate_bounded(self, process: subprocess.Popen[bytes], timeout: int) -> tuple[bytes, bytes]:
        """Drain both pipes concurrently and kill before an unbounded buffer forms."""
        if not hasattr(process, "stdout") or process.stdout is None:  # deterministic test-double protocol
            return process.communicate(timeout=timeout)
        chunks: list[list[bytes]] = [[], []]
        exceeded = threading.Event()
        reader_failed = threading.Event()
        def drain(stream: Any, bucket: list[bytes]) -> None:
            try:
                total = 0
                while True:
                    part = stream.read(min(65_536, self._limit + 1))
                    if not part: return
                    total += len(part)
                    if total > self._limit:
                        exceeded.set(); return
                    bucket.append(part)
            except Exception:
                # Pipe/decoder details are untrusted child output.  The caller
                # receives only this stable category after the group is gone.
                reader_failed.set()
        threads = [threading.Thread(target=drain, args=(process.stdout, chunks[0]), name=f"trainlab-reader-{process.pid}-stdout"), threading.Thread(target=drain, args=(process.stderr, chunks[1]), name=f"trainlab-reader-{process.pid}-stderr")]
        for thread in threads: thread.start()
        end = time.monotonic() + timeout
        while process.poll() is None:
            if exceeded.is_set():
                self._reclaim_abnormal_group(process, threads)
                raise ValueError("process_output_limit")
            if reader_failed.is_set():
                self._reclaim_abnormal_group(process, threads)
                raise ValueError("process_reader_error")
            if time.monotonic() >= end:
                self._reclaim_abnormal_group(process, threads)
                raise subprocess.TimeoutExpired("trainlab", timeout)
            time.sleep(0.01)
        for thread in threads: thread.join(timeout=self._grace)
        # A child inheriting either pipe can keep readers alive after its parent
        # exits normally.  Parent exit is therefore not completion: reclaim the
        # whole process group before returning any result.
        if reader_failed.is_set():
            self._reclaim_abnormal_group(process, threads)
            raise ValueError("process_reader_error")
        if any(thread.is_alive() for thread in threads):
            self._reclaim_abnormal_group(process, threads)
            raise ValueError("process_reader_unreaped")
        if exceeded.is_set():
            self._reclaim_abnormal_group(process, threads)
            raise ValueError("process_output_limit")
        # A descendant can detach all stdio while remaining in the child's
        # process group. Reader completion is not proof that the group is
        # empty, so reclaim it before any receipt is trusted.
        if self._process_group_exists(process.pid) and not self._terminate_group(process):
            raise ValueError("process_group_unreaped")
        self._close_process_streams(process)
        return b"".join(chunks[0]), b"".join(chunks[1])

    def _reclaim_abnormal_group(self, process: subprocess.Popen[bytes], threads: list[threading.Thread]) -> None:
        """Terminate an abnormal child and prove no group/reader survives.

        A timeout or output cap is only safe to classify after cleanup succeeds.
        In particular, do not let a failed kill turn into an apparently ordinary
        timeout: a non-idempotent downstream side effect may still be running.
        """
        terminated = self._terminate_group(process)
        for thread in threads:
            thread.join(timeout=self._grace)
        if not terminated or self._process_group_exists(process.pid):
            raise ValueError("process_group_unreaped")
        if any(thread.is_alive() for thread in threads):
            raise ValueError("process_reader_unreaped")

    @staticmethod
    def _close_process_streams(process: subprocess.Popen[bytes]) -> None:
        for stream in (getattr(process, "stdout", None), getattr(process, "stderr", None)):
            if stream is not None:
                try: stream.close()
                except OSError: pass

    @staticmethod
    def _process_group_exists(pgid: int) -> bool:
        return process_group_has_live_members(pgid)

    def _wait_process_group_gone(self, pgid: int) -> bool:
        deadline = time.monotonic() + self._grace
        while time.monotonic() < deadline:
            if not self._process_group_exists(pgid):
                return True
            time.sleep(0.01)
        return not self._process_group_exists(pgid)

    def _terminate_group(self, process: subprocess.Popen[bytes]) -> bool:
        # Real pipes are owned by _communicate_bounded's reader threads.  Do not
        # call communicate here: concurrent readers would race and lose bytes.
        if hasattr(process, "stdout") and process.stdout is not None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except OSError:
                pass
            try:
                process.wait(timeout=self._grace)
            except (OSError, subprocess.TimeoutExpired):
                try: os.killpg(process.pid, signal.SIGKILL)
                except OSError: pass
                try: process.wait(timeout=self._grace)
                except (OSError, subprocess.TimeoutExpired): pass
            # Reaping the parent is not proof that its descendants left the
            # group. Give the whole group a bounded TERM grace, then KILL and
            # explicitly confirm that no reachable member remains.
            if not self._wait_process_group_gone(process.pid):
                try: os.killpg(process.pid, signal.SIGKILL)
                except OSError: pass
                self._wait_process_group_gone(process.pid)
            gone = not self._process_group_exists(process.pid)
            self._close_process_streams(process)
            return gone
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.communicate(timeout=self._grace)
        except (OSError, subprocess.TimeoutExpired):
            pass
        else:
            return not self._process_group_exists(process.pid)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            process.communicate(timeout=self._grace)
        except (OSError, subprocess.TimeoutExpired):
            pass
        # The no-pipe branch is used only by deterministic process doubles, but
        # it retains the same contract: a successful wait is not sufficient if
        # a descendant remains in the isolated process group.
        return not self._process_group_exists(process.pid)
