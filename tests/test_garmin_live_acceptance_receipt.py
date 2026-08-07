"""Offline validation for the redacted Garmin live-acceptance receipt contract."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path("harness/schemas/garmin_live_acceptance_receipt.schema.json")
ZERO_HASH = "0" * 64


def _hash(index: int) -> str:
    return f"{index:064x}"


def _counts() -> dict[str, int]:
    return {
        "fetched": 0,
        "empty": 0,
        "unchanged": 0,
        "revised": 0,
        "failed": 0,
        "deferred": 0,
        "not_available": 0,
        "not_enabled": 0,
    }


def _dates(mode: str) -> dict[str, str | None]:
    if mode == "incremental":
        return {"from": None, "through": "2026-08-06", "snapshot": None}
    if mode == "snapshot":
        return {"from": None, "through": None, "snapshot": "2026-08-07"}
    if mode == "audit":
        return {"from": "2026-08-06", "through": "2026-08-06", "snapshot": None}
    return {"from": None, "through": None, "snapshot": None}


def _receipt() -> dict[str, object]:
    modes = ("auth", "incremental", "incremental", "snapshot", "audit")
    checkpoints = []
    operations = []
    previous = ZERO_HASH
    for ordinal, mode in enumerate(modes, start=1):
        checkpoint_hash = _hash(ordinal)
        dates = _dates(mode)
        operations.append(
            {
                "ordinal": ordinal,
                "mode": mode,
                "status": "succeeded",
                "request_semantic_sha256": _hash(10 + ordinal),
                "requested_local_dates": dates,
                "effective_local_dates": dates.copy(),
                "receipt_schema_valid": True,
                "receipt_counts": _counts(),
                "provider_entry_ordinals": {"first": 0, "last": 0},
                "checkpoint_sha256": checkpoint_hash,
            }
        )
        checkpoints.append(
            {
                "operation_ordinal": ordinal,
                "previous_checkpoint_sha256": previous,
                "checkpoint_sha256": checkpoint_hash,
                "schema_valid": True,
                "provider_entry_count": 0,
                "adjacent_controlled_provider_intervals_ns": [],
            }
        )
        previous = checkpoint_hash
    return {
        "schema_version": "1",
        "receipt_kind": "garmin_live_acceptance",
        "timezone": "Asia/Hong_Kong",
        "operations": operations,
        "checkpoints": checkpoints,
        "provider_entry_count": 0,
        "configured_minimum_interval_ns": 1_500_000_000,
        "adjacent_controlled_provider_intervals_ns": [],
        "authority_unchanged": {
            "production_database": True,
            "production_raw_root": True,
            "credential_permissions": True,
        },
        "token_dump_attempt_count": 0,
        "drift_evidence": {
            "stable_repeat": {
                "same_payload_hash": True,
                "raw_object_delta": 0,
                "source_revision_delta": 0,
            },
            "changed_payload": {
                "payload_hash_changed": True,
                "raw_object_delta": 1,
                "source_revision_delta": 1,
                "current_version_provenance": True,
            },
        },
        "failure_evidence": {
            "pre_provider_failure": {
                "provider_entry_count": 0,
                "receipt_schema_valid": True,
            },
            "post_provider_local_gate_failure_preserves_checkpoint": True,
            "ambiguous_in_flight_provider_preserves_last_checkpoint": True,
        },
        "final_checkpoint_sha256": previous,
        "result_sha256": _hash(99),
        "partition_coverage": {
            "idempotence": [
                "incremental-through-2026-08-06",
                "stable-repeat-no-new-object",
                "provider-drift-one-distinct-revision",
                "snapshot-2026-08-07",
                "audit-only-2026-08-06",
                "empty-delta",
                "provider-deferred",
                "rate-limit-boundary",
            ],
            "pacing": [
                "first-call",
                "exact-minimum",
                "just-below-minimum",
                "pre-call-persistence-delay",
                "early-sleep-return",
                "retry-call",
                "long-provider-call",
            ],
            "durability": [
                "pre-provider-failure-zero-entry-receipt",
                "completed-operation-integer-nanosecond-intervals",
                "post-provider-local-gate-failure-preserves-checkpoint",
                "ambiguous-in-flight-provider-preserves-last-checkpoint",
            ],
        },
    }


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))


def _errors(receipt: dict[str, object]) -> list[object]:
    return list(_validator().iter_errors(receipt))


def _assert_chain_continuity(receipt: dict[str, object]) -> None:
    operations = receipt["operations"]
    checkpoints = receipt["checkpoints"]
    assert isinstance(operations, list)
    assert isinstance(checkpoints, list)
    assert [operation["ordinal"] for operation in operations] == list(
        range(1, len(operations) + 1)
    )
    assert [checkpoint["operation_ordinal"] for checkpoint in checkpoints] == [
        operation["ordinal"] for operation in operations
    ]
    previous = ZERO_HASH
    for operation, checkpoint in zip(operations, checkpoints, strict=True):
        assert checkpoint["previous_checkpoint_sha256"] == previous
        assert operation["checkpoint_sha256"] == checkpoint["checkpoint_sha256"]
        previous = checkpoint["checkpoint_sha256"]
    assert receipt["final_checkpoint_sha256"] == previous


def test_offline_redacted_receipt_is_schema_valid_and_has_continuous_digest_chain() -> (
    None
):
    receipt = _receipt()
    assert _errors(receipt) == []
    _assert_chain_continuity(receipt)
    assert receipt["provider_entry_count"] == 0


@pytest.mark.parametrize("partition_group", ("idempotence", "pacing", "durability"))
def test_partition_coverage_rejects_missing_partition(partition_group: str) -> None:
    receipt = _receipt()
    coverage = receipt["partition_coverage"]
    assert isinstance(coverage, dict)
    entries = coverage[partition_group]
    assert isinstance(entries, list)
    entries.pop()
    assert _errors(receipt)


@pytest.mark.parametrize(
    "mutation",
    (
        "extra-top-level",
        "extra-operation-field",
        "wrong-frozen-date",
        "non-integer-interval",
        "token-dump-attempt",
        "authority-changed",
        "stable-repeat-revision",
        "changed-payload-not-revised",
        "pre-provider-nonzero-entry",
        "bad-checkpoint-hash",
    ),
)
def test_invalid_or_extra_receipt_fields_fail_schema_validation(mutation: str) -> None:
    receipt = _receipt()
    if mutation == "extra-top-level":
        receipt["raw_provider_payload"] = "forbidden"
    elif mutation == "extra-operation-field":
        receipt["operations"][0]["raw_token"] = "forbidden"
    elif mutation == "wrong-frozen-date":
        receipt["operations"][1]["effective_local_dates"]["through"] = "2026-08-05"
    elif mutation == "non-integer-interval":
        receipt["adjacent_controlled_provider_intervals_ns"] = [1.5]
    elif mutation == "token-dump-attempt":
        receipt["token_dump_attempt_count"] = 1
    elif mutation == "authority-changed":
        receipt["authority_unchanged"]["production_raw_root"] = False
    elif mutation == "stable-repeat-revision":
        receipt["drift_evidence"]["stable_repeat"]["source_revision_delta"] = 1
    elif mutation == "changed-payload-not-revised":
        receipt["drift_evidence"]["changed_payload"]["raw_object_delta"] = 0
    elif mutation == "pre-provider-nonzero-entry":
        receipt["failure_evidence"]["pre_provider_failure"]["provider_entry_count"] = 1
    else:
        receipt["checkpoints"][0]["checkpoint_sha256"] = "not-a-digest"
    assert _errors(receipt)


@pytest.mark.parametrize(
    "mutation", ("ordinal-gap", "digest-break", "final-digest-break")
)
def test_ordinal_and_digest_continuity_are_checked_offline(mutation: str) -> None:
    receipt = copy.deepcopy(_receipt())
    if mutation == "ordinal-gap":
        receipt["checkpoints"][2]["operation_ordinal"] = 4
    elif mutation == "digest-break":
        receipt["checkpoints"][2]["previous_checkpoint_sha256"] = _hash(81)
    else:
        receipt["final_checkpoint_sha256"] = _hash(82)
    assert _errors(receipt) == []
    with pytest.raises(AssertionError):
        _assert_chain_continuity(receipt)


def test_integer_nanosecond_pacing_is_recomputable_without_provider_access() -> None:
    receipt = _receipt()
    receipt["provider_entry_count"] = 3
    receipt["adjacent_controlled_provider_intervals_ns"] = [
        1_500_000_000,
        1_500_000_001,
    ]
    receipt["operations"][1]["provider_entry_ordinals"] = {"first": 1, "last": 2}
    receipt["operations"][2]["provider_entry_ordinals"] = {"first": 3, "last": 3}
    receipt["checkpoints"][1]["provider_entry_count"] = 2
    receipt["checkpoints"][1]["adjacent_controlled_provider_intervals_ns"] = [
        1_500_000_000
    ]
    receipt["checkpoints"][2]["provider_entry_count"] = 3
    receipt["checkpoints"][2]["adjacent_controlled_provider_intervals_ns"] = [
        1_500_000_000,
        1_500_000_001,
    ]
    assert _errors(receipt) == []
    assert all(
        interval >= receipt["configured_minimum_interval_ns"]
        for interval in receipt["adjacent_controlled_provider_intervals_ns"]
    )
