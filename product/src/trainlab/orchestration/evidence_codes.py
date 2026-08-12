"""Bounded, data-free downstream failure evidence shared by Layer 5."""

from __future__ import annotations

DOWNSTREAM_FAILURE_EVIDENCE_CODES = frozenset(
    {
        "downstream_execution_failed",
        "interface_manifest_invalid",
        "interface_manifest_mismatch",
        "interface_manifest_unavailable",
        "interface_schema_mismatch",
        "process_group_unreaped",
        "process_io_invalid",
        "process_output_limit",
        "process_reader_error",
        "process_reader_unreaped",
        "process_start_failed",
        "process_timeout_unknown",
        "receipt_artifact_mismatch",
        "receipt_delivery_mismatch",
        "receipt_exit_mismatch",
        "receipt_failure_identity_invalid",
        "receipt_invocation_mismatch",
        "receipt_json_invalid",
        "receipt_message_identity_invalid",
        "receipt_message_mismatch",
        "receipt_mode_mismatch",
        "receipt_not_object",
        "receipt_range_invalid",
        "receipt_run_key_mismatch",
        "receipt_schema_invalid",
        "receipt_schema_unavailable",
        "receipt_schema_version_mismatch",
        "receipt_target_mismatch",
        "receipt_time_invalid",
        "receipt_time_order_invalid",
    }
)


def downstream_failure_evidence(code: object) -> str:
    """Return an allowlisted diagnostic code without exposing child output."""

    return (
        code
        if isinstance(code, str) and code in DOWNSTREAM_FAILURE_EVIDENCE_CODES
        else "downstream_execution_failed"
    )
