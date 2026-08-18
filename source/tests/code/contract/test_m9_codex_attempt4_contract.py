from __future__ import annotations

from typing import Any

from skills._shared.scripts.schema_validation import validate_payload


def _command_contract() -> dict[str, Any]:
    return {
        "ephemeral": True,
        "ignore_user_config": True,
        "sandbox": "read-only",
        "json_events": True,
        "output_schema": "daily_ai_result_codex_v2",
    }


def test_attempt4_intent_v2_binds_prior_canary_and_frozen_inputs() -> None:
    payload = {
        "schema_version": "codex_ai_attempt_intent_v2",
        "attempt": 4,
        "created_at_utc": "2026-08-18T00:00:00Z",
        "timeout_seconds": 180,
        "max_log_bytes": 2097152,
        "command_contract": _command_contract(),
        "prior_attempt_receipt_sha256": "a" * 64,
        "canary_receipt_sha256": "b" * 64,
        "context_sha256": "c" * 64,
        "prompt_sha256": "d" * 64,
        "wire_schema_sha256": "e" * 64,
        "business_schema_sha256": "f" * 64,
        "provider_calls": 0,
        "external_actions": 0,
    }
    assert validate_payload(payload, "codex_ai_attempt_intent_v2") == []

    payload["attempt"] = 5
    assert validate_payload(payload, "codex_ai_attempt_intent_v2")


def test_attempt4_receipt_v2_rejects_attempt5_and_wrong_wire() -> None:
    payload = {
        "schema_version": "codex_ai_attempt_v2",
        "attempt": 4,
        "status": "failed",
        "error_code": "ai_codex_exit_nonzero",
        "error_category": "schema_non_retryable",
        "exit_code": 1,
        "started_at_utc": "2026-08-18T00:00:00Z",
        "finished_at_utc": "2026-08-18T00:00:01Z",
        "elapsed_milliseconds": 1000,
        "timeout_seconds": 180,
        "max_log_bytes": 2097152,
        "command_contract": _command_contract(),
        "context_sha256": "a" * 64,
        "prompt_sha256": "b" * 64,
        "schema_sha256": "c" * 64,
        "intent_bytes": 1,
        "intent_sha256": "d" * 64,
        "events_captured_bytes": 1,
        "events_sha256": "e" * 64,
        "stderr_captured_bytes": 1,
        "stderr_sha256": "f" * 64,
        "result_bytes": None,
        "result_sha256": None,
        "provider_calls": 0,
        "external_actions": 0,
    }
    assert validate_payload(payload, "codex_ai_attempt_v2") == []

    payload["attempt"] = 5
    assert validate_payload(payload, "codex_ai_attempt_v2")
    payload["attempt"] = 4
    command_contract = payload["command_contract"]
    assert isinstance(command_contract, dict)
    command_contract["output_schema"] = "daily_ai_result_codex_v1"
    assert validate_payload(payload, "codex_ai_attempt_v2")


def test_canary_receipt_contract_is_private_data_free_and_bounded() -> None:
    payload = {
        "schema_version": "codex_schema_canary_v1",
        "status": "succeeded",
        "error_code": None,
        "input_class": "public_synthetic",
        "codex_version": "codex-cli 0.147.0",
        "codex_executable_sha256": "f" * 64,
        "timeout_seconds": 180,
        "command_contract": _command_contract(),
        "wire_schema_sha256": "a" * 64,
        "prompt_sha256": "b" * 64,
        "events_captured_bytes": 1,
        "events_sha256": "c" * 64,
        "stderr_captured_bytes": 1,
        "stderr_sha256": "d" * 64,
        "result_bytes": 1,
        "result_sha256": "e" * 64,
        "provider_calls": 0,
        "external_actions": 0,
    }
    assert validate_payload(payload, "codex_schema_canary_v1") == []
    assert "context_sha256" not in payload
    assert "candidate" not in payload
