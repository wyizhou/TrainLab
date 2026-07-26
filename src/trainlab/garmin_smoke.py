"""Fail-closed validation for a redacted L2-18 Garmin smoke evidence file.

This module deliberately does not know how to create a Garmin client, execute a
TrainLab command, open a database, or inspect a token.  The operator collects
the real-account evidence under the runbook; this module accepts only the
small, payload-free attestation document that may be retained with the change
record.
"""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
import math
import re
from typing import Any, Mapping


SMOKE_EVIDENCE_SCHEMA_VERSION = "1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_AUTHORIZATION_ID = re.compile(r"^authz-[0-9a-f]{32}$")
_INVOCATION_ID = re.compile(r"^inv-[0-9a-f]{32}$")
_RUN_ID = re.compile(
    r"^gr-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_LOCAL_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MODES = frozenset({"auth", "incremental", "snapshot", "repair", "audit", "status"})
_OPERATION_SEQUENCE = (
    "auth", "incremental", "incremental", "snapshot", "snapshot", "repair", "audit", "status",
)
_RUN_STATUSES = frozenset({"succeeded", "partial", "deferred", "failed", "auth_required", "lock_busy"})
_EXIT_BY_STATUS = {
    "succeeded": 0,
    "partial": 10,
    "deferred": 11,
    "lock_busy": 12,
    "auth_required": 20,
    "failed": 21,
}
_FORBIDDEN_TERMS = frozenset(
    {
        "access_token", "account", "address", "altitude", "body", "body_battery",
        "credential", "email", "error_message", "fit", "gps", "heart_rate", "latitude",
        "longitude", "password", "payload", "raw", "refresh_token", "response", "route",
        "sleep_score", "source", "token", "vo2",
    }
)
_APPROVED_SECURITY_WORDS_IN_KEYS = frozenset({
    "fit_present",
    "credential_permissions_verified",
})
_DURATION_ROUNDING_TOLERANCE_SECONDS = 0.05


class GarminSmokeEvidenceError(ValueError):
    """Raised when evidence is incomplete, unsafe, or internally inconsistent."""


def evidence_sha256(evidence: Mapping[str, Any]) -> str:
    """Hash the canonical evidence document, excluding its self-hash field."""
    material = dict(evidence)
    material.pop("evidence_sha256", None)
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return sha256(encoded).hexdigest()


def _is_hash(value: object) -> bool:
    return type(value) is str and bool(_SHA256.fullmatch(value))


def _matches(value: object, pattern: re.Pattern[str]) -> bool:
    return type(value) is str and bool(pattern.fullmatch(value))


def _is_date(value: object) -> bool:
    if type(value) is not str or not _LOCAL_DATE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_nonnegative_finite_number(value: object) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


def _scan_forbidden(value: object, path: str = "$") -> list[str]:
    """Report forbidden key names even when schema validation is bypassed.

    Values are intentionally not echoed: callers receive only a JSON path and
    controlled code.  A schema with ``additionalProperties: false`` is the
    primary boundary; this scan makes direct module use fail closed as well.
    """
    problems: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered not in _APPROVED_SECURITY_WORDS_IN_KEYS and any(term in lowered for term in _FORBIDDEN_TERMS):
                problems.append(f"{path}.{key}")
            problems.extend(_scan_forbidden(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            problems.extend(_scan_forbidden(item, f"{path}[{index}]"))
    return problems


def validate_smoke_evidence(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Return stable, payload-free failure codes for a smoke attestation.

    JSON Schema validates the document shape.  These semantic checks deliberately
    repeat the security-critical invariants so callers cannot turn a syntactically
    valid but incomplete document into a passing L2-18 gate.
    """
    errors: list[str] = []
    if not isinstance(evidence, Mapping):
        return ("evidence_not_object",)
    forbidden = _scan_forbidden(evidence)
    if forbidden:
        errors.append("sensitive_or_payload_field_present")
    if evidence.get("schema_version") != SMOKE_EVIDENCE_SCHEMA_VERSION:
        errors.append("schema_version_invalid")
    if not _matches(evidence.get("authorization_id"), _AUTHORIZATION_ID):
        errors.append("authorization_id_invalid")
    modes = evidence.get("approved_modes")
    if (
        not isinstance(modes, list)
        or not modes
        or any(type(mode) is not str for mode in modes)
        or set(modes) - _MODES
        or len(set(modes)) != len(modes)
    ):
        errors.append("approved_modes_invalid")
        modes = []
    required_modes = set(_MODES)
    if not required_modes.issubset(set(modes)):
        errors.append("authorization_scope_incomplete")
    window = evidence.get("approved_window")
    if not isinstance(window, Mapping) or window.get("timezone") != "Asia/Singapore" or not _is_date(window.get("from_local_date")) or not _is_date(window.get("through_local_date")):
        errors.append("approved_window_invalid")
    else:
        window_start = date.fromisoformat(str(window["from_local_date"]))
        window_end = date.fromisoformat(str(window["through_local_date"]))
        if window_start > window_end:
            errors.append("approved_window_invalid")
        elif (window_end - window_start).days > 13:
            errors.append("approved_window_too_large")
    if not _is_hash(evidence.get("backup_evidence_sha256")):
        errors.append("backup_evidence_hash_invalid")
    prerequisites = evidence.get("prerequisites")
    prerequisite_keys = {
        "e01_e04_verified",
        "named_operator_registered",
        "backup_restore_verified",
        "shadow_window_registered",
        "legacy_path_independent_verified",
        "credential_permissions_verified",
        "bounded_activity_window_verified",
        "canonical_owner_unchanged",
    }
    if (
        not isinstance(prerequisites, Mapping)
        or any(prerequisites.get(key) is not True for key in prerequisite_keys)
    ):
        errors.append("prerequisites_incomplete")

    operations = evidence.get("operations")
    by_mode: dict[str, list[Mapping[str, Any]]] = {}
    by_run_id: dict[object, Mapping[str, Any]] = {}
    invocation_ids: set[object] = set()
    operation_durations: list[float] = []
    if not isinstance(operations, list) or not operations:
        errors.append("operations_missing")
        operations = []
    elif tuple(operation.get("mode") if isinstance(operation, Mapping) else None for operation in operations) != _OPERATION_SEQUENCE:
        errors.append("operation_sequence_invalid")
    for operation in operations:
        if not isinstance(operation, Mapping):
            errors.append("operation_invalid")
            continue
        mode = operation.get("mode")
        run_id = operation.get("run_id")
        invocation_id = operation.get("invocation_id")
        mode_valid = type(mode) is str and mode in _MODES
        run_id_valid = mode_valid and (
            run_id is None
            if mode in {"auth", "status"}
            else _matches(run_id, _RUN_ID)
        )
        if (
            not mode_valid
            or not run_id_valid
            or not _matches(invocation_id, _INVOCATION_ID)
            or not _is_hash(operation.get("request_sha256"))
            or not _is_hash(operation.get("receipt_sha256"))
        ):
            errors.append("operation_invalid")
            continue
        duration = operation.get("duration_seconds")
        if not _is_nonnegative_finite_number(duration):
            errors.append("operation_duration_invalid")
        else:
            operation_durations.append(float(duration))
        if (run_id is not None and run_id in by_run_id) or invocation_id in invocation_ids:
            errors.append("operation_identity_duplicate")
        if run_id is not None:
            by_run_id[run_id] = operation
        invocation_ids.add(invocation_id)
        status = operation.get("status")
        exit_code = operation.get("exit_code")
        if (
            type(status) is not str
            or status not in _RUN_STATUSES
            or type(exit_code) is not int
            or exit_code != _EXIT_BY_STATUS.get(str(status))
        ):
            errors.append("operation_outcome_invalid")
        if (
            operation.get("request_schema_valid") is not True
            or operation.get("receipt_schema_valid") is not True
        ):
            errors.append("operation_schema_unverified")
        if operation.get("within_approved_window") is not True:
            errors.append("operation_outside_approved_window")
        effective = operation.get("effective_window")
        if not isinstance(effective, Mapping):
            errors.append("operation_window_invalid")
        else:
            start, end = effective.get("from_local_date"), effective.get("through_local_date")
            if mode in {"incremental", "snapshot", "repair", "audit"}:
                if not _is_date(start) or not _is_date(end) or str(start) > str(end):
                    errors.append("operation_window_invalid")
                elif isinstance(window, Mapping) and _is_date(window.get("from_local_date")) and _is_date(window.get("through_local_date")) and (str(start) < str(window["from_local_date"]) or str(end) > str(window["through_local_date"])):
                    errors.append("operation_outside_approved_window")
                elif mode == "snapshot" and start != end:
                    errors.append("snapshot_window_invalid")
            elif start is not None or end is not None:
                errors.append("operation_window_invalid")
        if operation.get("status") != "succeeded" and operation.get("outcome_handed_off") is not True:
            errors.append("operation_follow_up_missing")
        by_mode.setdefault(str(mode), []).append(operation)
    if not required_modes.issubset(by_mode):
        errors.append("required_mode_evidence_missing")

    total_elapsed = evidence.get("total_elapsed_seconds")
    if not _is_nonnegative_finite_number(total_elapsed):
        errors.append("total_elapsed_seconds_invalid")
    elif len(operation_durations) == len(_OPERATION_SEQUENCE):
        # This is end-to-end elapsed time.  It may include local bookkeeping
        # between stages, but may not be shorter than their recorded total
        # beyond the documented decimal-rounding tolerance.
        if float(total_elapsed) + _DURATION_ROUNDING_TOLERANCE_SECONDS < sum(operation_durations):
            errors.append("total_elapsed_seconds_less_than_operations")

    repeat = evidence.get("repeat_no_op")
    if not isinstance(repeat, Mapping) or set(repeat) != {"incremental", "snapshot"}:
        errors.append("repeat_no_op_missing")
    else:
        for repeat_mode in ("incremental", "snapshot"):
            item = repeat.get(repeat_mode)
            if not isinstance(item, Mapping) or set(item) != {"first_run_id", "repeat_run_id", "same_request_hash", "no_op_confirmed"}:
                errors.append("repeat_no_op_missing"); continue
            first, second = item.get("first_run_id"), item.get("repeat_run_id")
            if not _matches(first, _RUN_ID) or not _matches(second, _RUN_ID) or first == second: errors.append("repeat_run_ids_invalid"); continue
            if item.get("same_request_hash") is not True or item.get("no_op_confirmed") is not True: errors.append("repeat_no_op_not_confirmed")
            if first not in by_run_id or second not in by_run_id: errors.append("repeat_run_not_recorded"); continue
            one,two=by_run_id[first],by_run_id[second]
            if one.get("mode") != repeat_mode or two.get("mode") != repeat_mode or one.get("request_sha256") != two.get("request_sha256") or one.get("status") != "succeeded" or two.get("status") != "succeeded": errors.append("repeat_request_mismatch")

    structure = evidence.get("activity_structure")
    structural_counts = ("segment_count", "sample_count", "enrichment_count")
    if not isinstance(structure, Mapping) or any(structure.get(key) is not True for key in ("summary_present", "fit_present", "segments_present", "samples_present", "enrichment_present")) or any(type(structure.get(key)) is not int or structure[key] < 1 for key in structural_counts):
        errors.append("activity_structure_incomplete")
    capability = evidence.get("capability_check")
    capability_state = capability.get("state") if isinstance(capability, Mapping) else None
    if not isinstance(capability, Mapping) or capability.get("checked") is not True or type(capability_state) is not str or capability_state not in {"not_available", "not_enabled", "not_supported", "available"}:
        errors.append("capability_check_incomplete")

    safety = evidence.get("safety_checks")
    safety_keys = {
        "receipt_log_scan_clean", "run_table_scan_clean", "temporary_zip_cleaned",
        "no_daemon", "no_background_threads", "no_timer", "no_listening_socket", "rollback_exercised",
    }
    if not isinstance(safety, Mapping) or any(safety.get(key) is not True for key in safety_keys):
        errors.append("safety_checks_incomplete")
    if evidence.get("acceptance_complete") is not True:
        errors.append("acceptance_not_complete")
    expected_hash = evidence_sha256(evidence)
    if evidence.get("evidence_sha256") != expected_hash:
        errors.append("evidence_hash_mismatch")
    return tuple(sorted(set(errors)))


def require_valid_smoke_evidence(evidence: Mapping[str, Any]) -> None:
    """Raise one safe error if the attestation cannot pass the L2-18 gate."""
    errors = validate_smoke_evidence(evidence)
    if errors:
        raise GarminSmokeEvidenceError(";".join(errors))
