from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator
import pytest

from trainlab.garmin_smoke import GarminSmokeEvidenceError, evidence_sha256, require_valid_smoke_evidence, validate_smoke_evidence


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "harness/schemas/garmin_smoke_evidence.schema.json").read_text())
H = "a" * 64


def _run_id(index: int) -> str:
    return f"gr-00000000-0000-4000-8000-{index:012x}"


def _invocation_id(index: int) -> str:
    return f"inv-{index:032x}"


def _evidence() -> dict[str, object]:
    def operation(index: int, mode: str, start: str | None = None, end: str | None = None) -> dict[str, object]:
        return {
            "mode": mode,
            "run_id": None if mode in {"auth", "status"} else _run_id(index),
            "invocation_id": _invocation_id(index),
            "request_sha256": H,
            "receipt_sha256": H,
            "request_schema_valid": True,
            "receipt_schema_valid": True,
            "status": "succeeded",
            "exit_code": 0,
            "duration_seconds": float(index),
            "within_approved_window": True,
            "effective_window": {"from_local_date": start, "through_local_date": end},
            "outcome_handed_off": False,
        }

    operations = [
        operation(1, "auth"),
        operation(2, "incremental", "2026-07-20", "2026-07-22"),
        operation(3, "incremental", "2026-07-20", "2026-07-22"),
        operation(4, "snapshot", "2026-07-22", "2026-07-22"),
        operation(5, "snapshot", "2026-07-22", "2026-07-22"),
        operation(6, "repair", "2026-07-20", "2026-07-22"),
        operation(7, "audit", "2026-07-20", "2026-07-22"),
        operation(8, "status"),
    ]
    result: dict[str, object] = {
        "schema_version": "1", "authorization_id": "authz-" + "a" * 32, "approved_modes": ["auth", "incremental", "snapshot", "repair", "audit", "status"],
        "approved_window": {"timezone": "Asia/Singapore", "from_local_date": "2026-07-20", "through_local_date": "2026-07-22"}, "backup_evidence_sha256": H,
        "prerequisites": {"e01_e04_verified": True, "named_operator_registered": True, "backup_restore_verified": True, "shadow_window_registered": True, "legacy_path_independent_verified": True, "credential_permissions_verified": True, "bounded_activity_window_verified": True, "canonical_owner_unchanged": True},
        "operations": operations,
        "total_elapsed_seconds": 36.2,
        "repeat_no_op": {
            "incremental": {"first_run_id": _run_id(2), "repeat_run_id": _run_id(3), "same_request_hash": True, "no_op_confirmed": True},
            "snapshot": {"first_run_id": _run_id(4), "repeat_run_id": _run_id(5), "same_request_hash": True, "no_op_confirmed": True},
        },
        "activity_structure": {"summary_present": True, "fit_present": True, "segments_present": True, "samples_present": True, "enrichment_present": True, "segment_count": 2, "sample_count": 100, "enrichment_count": 1},
        "capability_check": {"checked": True, "state": "not_available"},
        "safety_checks": {"receipt_log_scan_clean": True, "run_table_scan_clean": True, "temporary_zip_cleaned": True, "no_daemon": True, "no_background_threads": True, "no_timer": True, "no_listening_socket": True, "rollback_exercised": True},
        "acceptance_complete": True,
    }
    result["evidence_sha256"] = evidence_sha256(result)
    return result


def test_valid_evidence_is_schema_and_semantically_valid() -> None:
    evidence = _evidence()
    assert not list(Draft202012Validator(SCHEMA).iter_errors(evidence))
    assert validate_smoke_evidence(evidence) == ()
    require_valid_smoke_evidence(evidence)


@pytest.mark.parametrize("path", [("authorization_id",), ("approved_window", "through_local_date"), ("backup_evidence_sha256",)])
def test_missing_authorization_material_fails_closed(path: tuple[str, ...]) -> None:
    evidence = _evidence()
    current = evidence
    for key in path[:-1]:
        current = current[key]  # type: ignore[index]
    current.pop(path[-1])  # type: ignore[union-attr]
    assert list(Draft202012Validator(SCHEMA).iter_errors(evidence))
    assert validate_smoke_evidence(evidence)


def test_expanded_or_unapproved_window_and_operation_are_rejected() -> None:
    evidence = _evidence()
    evidence["operations"][0]["within_approved_window"] = False  # type: ignore[index]
    evidence["evidence_sha256"] = evidence_sha256(evidence)
    assert "operation_outside_approved_window" in validate_smoke_evidence(evidence)


def test_effective_date_range_cannot_expand_authorized_window() -> None:
    evidence = _evidence()
    evidence["operations"][1]["effective_window"]["through_local_date"] = "2026-07-23"  # type: ignore[index]
    evidence["evidence_sha256"] = evidence_sha256(evidence)
    assert "operation_outside_approved_window" in validate_smoke_evidence(evidence)


def test_approved_window_is_one_to_fourteen_days_and_snapshot_is_one_day() -> None:
    evidence = _evidence()
    evidence["approved_window"]["from_local_date"] = "2026-07-08"  # type: ignore[index]
    evidence["operations"][3]["effective_window"]["from_local_date"] = "2026-07-20"  # type: ignore[index]
    evidence["evidence_sha256"] = evidence_sha256(evidence)
    codes = validate_smoke_evidence(evidence)
    assert "approved_window_too_large" in codes
    assert "snapshot_window_invalid" in codes


def test_invalid_calendar_date_and_malformed_objects_fail_without_crashing() -> None:
    evidence = _evidence()
    evidence["approved_window"]["from_local_date"] = "2026-02-30"  # type: ignore[index]
    evidence["evidence_sha256"] = evidence_sha256(evidence)
    assert "approved_window_invalid" in validate_smoke_evidence(evidence)
    assert validate_smoke_evidence({"operations": [None]})
    assert validate_smoke_evidence({"approved_modes": [{}], "operations": []})
    malformed = _evidence()
    malformed["operations"][0]["status"] = []  # type: ignore[index]
    malformed["capability_check"]["state"] = []  # type: ignore[index]
    malformed["evidence_sha256"] = evidence_sha256(malformed)
    assert validate_smoke_evidence(malformed)


@pytest.mark.parametrize("key", ["token", "raw_response", "activity_payload", "heart_rate"])
def test_sensitive_or_real_payload_shapes_are_rejected(key: str) -> None:
    evidence = _evidence()
    evidence[key] = {"anything": "never retained"}
    evidence["evidence_sha256"] = evidence_sha256(evidence)
    assert "sensitive_or_payload_field_present" in validate_smoke_evidence(evidence)
    assert list(Draft202012Validator(SCHEMA).iter_errors(evidence))


@pytest.mark.parametrize(
    "field,value",
    [
        ("authorization_id", "access_token-very-secret"),
        ("run_id", "account-private-user"),
        ("invocation_id", "refresh_token-private"),
    ],
)
def test_free_text_cannot_hide_in_evidence_identifiers(field: str, value: str) -> None:
    evidence = _evidence()
    if field == "authorization_id":
        evidence[field] = value
    else:
        evidence["operations"][1][field] = value  # type: ignore[index]
    evidence["evidence_sha256"] = evidence_sha256(evidence)
    assert validate_smoke_evidence(evidence)
    assert list(Draft202012Validator(SCHEMA).iter_errors(evidence))


def test_incomplete_acceptance_and_hash_mismatch_fail() -> None:
    evidence = _evidence()
    evidence["acceptance_complete"] = False
    codes = validate_smoke_evidence(evidence)
    assert "acceptance_not_complete" in codes and "evidence_hash_mismatch" in codes
    with pytest.raises(GarminSmokeEvidenceError):
        require_valid_smoke_evidence(evidence)


def test_prerequisites_schema_exit_and_repeat_identity_are_enforced() -> None:
    evidence = _evidence()
    evidence["prerequisites"]["bounded_activity_window_verified"] = False  # type: ignore[index]
    evidence["operations"][1]["exit_code"] = 10  # type: ignore[index]
    evidence["operations"][2]["request_sha256"] = "b" * 64  # type: ignore[index]
    evidence["evidence_sha256"] = evidence_sha256(evidence)
    codes = validate_smoke_evidence(evidence)
    assert "prerequisites_incomplete" in codes
    assert "operation_outcome_invalid" in codes
    assert "repeat_request_mismatch" in codes
    assert list(Draft202012Validator(SCHEMA).iter_errors(evidence))


def test_fixed_eight_operation_sequence_and_both_repeat_modes_are_required() -> None:
    evidence = _evidence()
    evidence["operations"][1]["mode"] = "snapshot"  # type: ignore[index]
    evidence["repeat_no_op"].pop("snapshot")  # type: ignore[index]
    evidence["evidence_sha256"] = evidence_sha256(evidence)
    codes = validate_smoke_evidence(evidence)
    assert "operation_sequence_invalid" in codes
    assert "repeat_no_op_missing" in codes
    assert list(Draft202012Validator(SCHEMA).iter_errors(evidence))


def test_full_is_not_a_real_smoke_mode() -> None:
    evidence = _evidence()
    evidence["approved_modes"].append("full")  # type: ignore[index]
    evidence["evidence_sha256"] = evidence_sha256(evidence)
    assert "approved_modes_invalid" in validate_smoke_evidence(evidence)
    assert list(Draft202012Validator(SCHEMA).iter_errors(evidence))


@pytest.mark.parametrize("value", [-0.01, float("inf"), float("nan"), True, "1.0"])
def test_operation_duration_must_be_a_nonnegative_finite_number(value: object) -> None:
    evidence = _evidence()
    evidence["operations"][0]["duration_seconds"] = value  # type: ignore[index]
    evidence["evidence_sha256"] = evidence_sha256(evidence)
    assert "operation_duration_invalid" in validate_smoke_evidence(evidence)
    if value == -0.01 or value is True or value == "1.0":
        assert list(Draft202012Validator(SCHEMA).iter_errors(evidence))


def test_total_elapsed_must_cover_all_eight_stage_durations_with_rounding_tolerance() -> None:
    evidence = _evidence()
    evidence["total_elapsed_seconds"] = 35.94
    evidence["evidence_sha256"] = evidence_sha256(evidence)
    assert "total_elapsed_seconds_less_than_operations" in validate_smoke_evidence(evidence)

    evidence = _evidence()
    evidence["total_elapsed_seconds"] = 35.95
    evidence["evidence_sha256"] = evidence_sha256(evidence)
    assert "total_elapsed_seconds_less_than_operations" not in validate_smoke_evidence(evidence)


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan"), False, "36"])
def test_total_elapsed_must_be_a_nonnegative_finite_number(value: object) -> None:
    evidence = _evidence()
    evidence["total_elapsed_seconds"] = value
    evidence["evidence_sha256"] = evidence_sha256(evidence)
    assert "total_elapsed_seconds_invalid" in validate_smoke_evidence(evidence)


def test_activity_structure_requires_nonzero_reviewed_rows() -> None:
    evidence = _evidence()
    evidence["activity_structure"]["sample_count"] = 0  # type: ignore[index]
    evidence["evidence_sha256"] = evidence_sha256(evidence)
    assert "activity_structure_incomplete" in validate_smoke_evidence(evidence)
    assert list(Draft202012Validator(SCHEMA).iter_errors(evidence))


def test_verifier_reads_only_supplied_evidence_and_returns_safe_codes(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(_evidence()), encoding="utf-8")
    completed = subprocess.run([sys.executable, str(ROOT / "scripts/verify_garmin_smoke.py"), "--evidence", str(evidence_path)], cwd=ROOT, check=False, capture_output=True, text=True)
    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"codes": [], "status": "passed"}

    unsafe = deepcopy(_evidence())
    unsafe["raw"] = "not allowed"
    unsafe["evidence_sha256"] = evidence_sha256(unsafe)
    evidence_path.write_text(json.dumps(unsafe), encoding="utf-8")
    completed = subprocess.run([sys.executable, str(ROOT / "scripts/verify_garmin_smoke.py"), "--evidence", str(evidence_path)], cwd=ROOT, check=False, capture_output=True, text=True)
    assert completed.returncode == 1
    result = json.loads(completed.stdout)
    assert result["status"] == "failed" and "sensitive_or_payload_field_present" in result["codes"]
    assert "not allowed" not in completed.stdout
