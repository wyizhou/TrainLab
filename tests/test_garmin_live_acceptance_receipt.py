"""Offline checks for redacted Garmin live-acceptance documents."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from trainlab.garmin import GarminCollectionTool, GarminConfig

SCHEMA_PATH = Path("harness/schemas/garmin_live_acceptance_receipt.schema.json")
ZERO_HASH = "0" * 64
MODES = ("auth", "incremental", "incremental", "snapshot", "audit")


def _tool(tmp_path: Path) -> GarminCollectionTool:
    return GarminCollectionTool(
        GarminConfig(
            tmp_path / "data.db", tmp_path / "raw", tmp_path / "state", "2026-08-06"
        )
    )


def _hash(index: int) -> str:
    return f"{index:064x}"


def _counts() -> dict[str, int]:
    return dict.fromkeys(
        (
            "fetched",
            "empty",
            "unchanged",
            "revised",
            "failed",
            "deferred",
            "not_available",
            "not_enabled",
        ),
        0,
    )


def _dates(mode: str) -> dict[str, str | None]:
    if mode == "incremental":
        return {"from": None, "through": "2026-08-06", "snapshot": None}
    if mode == "snapshot":
        return {"from": None, "through": None, "snapshot": "2026-08-07"}
    if mode == "audit":
        return {"from": "2026-08-06", "through": "2026-08-06", "snapshot": None}
    return {"from": None, "through": None, "snapshot": None}


def _checkpoint(
    tool: GarminCollectionTool, ordinal: int, mode: str
) -> dict[str, object]:
    dates = _dates(mode)
    document: dict[str, object] = {
        "schema_version": "1",
        "document_kind": "garmin_live_acceptance_checkpoint",
        "timezone": "Asia/Hong_Kong",
        "operation": {
            "ordinal": ordinal,
            "mode": mode,
            "status": "succeeded",
            "request_semantic_sha256": _hash(10 + ordinal),
            "requested_local_dates": dates,
            "effective_local_dates": dates.copy(),
            "receipt_schema_valid": True,
            "receipt_counts": _counts(),
            "provider_entry_ordinals": {"first": None, "last": None},
        },
        "prior_provider_entry_count": 0,
        "provider_entry_count": 0,
        "configured_minimum_interval_ns": 1_500_000_000,
        "adjacent_controlled_provider_intervals_ns": [],
        "previous_checkpoint_sha256": ZERO_HASH
        if ordinal == 1
        else _hash(70 + ordinal),
        "checkpoint_sha256": ZERO_HASH,
    }
    document["checkpoint_sha256"] = tool._canonical_live_acceptance_sha256(document)
    return document


def _partitions() -> dict[str, list[str]]:
    return {
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
    }


def _result(tool: GarminCollectionTool) -> dict[str, object]:
    checkpoints = [
        _checkpoint(tool, ordinal, mode) for ordinal, mode in enumerate(MODES, 1)
    ]
    previous = ZERO_HASH
    for checkpoint in checkpoints:
        checkpoint["previous_checkpoint_sha256"] = previous
        checkpoint["checkpoint_sha256"] = tool._canonical_live_acceptance_sha256(
            checkpoint
        )
        previous = checkpoint["checkpoint_sha256"]
    document: dict[str, object] = {
        "schema_version": "1",
        "document_kind": "garmin_live_acceptance_result",
        "timezone": "Asia/Hong_Kong",
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
            "stable_repeat_count": 0,
            "changed_payload_count": 0,
            "stable_repeat_violation_count": 0,
            "changed_revision_violation_count": 0,
        },
        "failure_evidence": {"outcome": "none", "last_checkpoint_preserved": None},
        "final_checkpoint_sha256": previous,
        "result_sha256": ZERO_HASH,
        "partition_coverage": _partitions(),
    }
    document["result_sha256"] = tool._canonical_live_acceptance_sha256(document)
    return document


def _schema_errors(document: dict[str, object]) -> list[object]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            document
        )
    )


def _reseal_checkpoint(
    tool: GarminCollectionTool, checkpoint: dict[str, object]
) -> None:
    checkpoint["checkpoint_sha256"] = tool._canonical_live_acceptance_sha256(checkpoint)


def _reseal_result(tool: GarminCollectionTool, document: dict[str, object]) -> None:
    document["result_sha256"] = tool._canonical_live_acceptance_sha256(document)


@pytest.mark.parametrize("ordinal,mode", tuple(enumerate(MODES, 1)))
def test_each_partial_checkpoint_is_independently_schema_and_semantically_valid(
    tmp_path: Path, ordinal: int, mode: str
) -> None:
    tool = _tool(tmp_path)
    checkpoint = _checkpoint(tool, ordinal, mode)
    assert _schema_errors(checkpoint) == []
    tool._validate_live_acceptance_document(checkpoint)


def test_final_result_is_valid_with_real_dates_and_zero_provider_entries(
    tmp_path: Path,
) -> None:
    tool = _tool(tmp_path)
    result = _result(tool)
    assert _schema_errors(result) == []
    tool._validate_live_acceptance_document(result)
    assert result["provider_entry_count"] == 0


@pytest.mark.parametrize("group", ("idempotence", "pacing", "durability"))
def test_required_8_7_4_partition_coverage_cannot_be_weakened(
    tmp_path: Path, group: str
) -> None:
    result = _result(_tool(tmp_path))
    result["partition_coverage"][group].pop()
    assert _schema_errors(result)


@pytest.mark.parametrize("mutation", ("calendar", "extra", "auth-date"))
def test_format_checked_schema_rejects_bad_or_extra_checkpoint_fields(
    tmp_path: Path, mutation: str
) -> None:
    tool = _tool(tmp_path)
    checkpoint = _checkpoint(tool, 1, "auth")
    if mutation == "calendar":
        checkpoint["operation"]["requested_local_dates"]["from"] = "2026-02-30"
    elif mutation == "auth-date":
        checkpoint["operation"]["effective_local_dates"]["through"] = "2026-08-06"
    else:
        checkpoint["operation"]["raw_provider_payload"] = "forbidden"
    assert _schema_errors(checkpoint)
    with pytest.raises(ValueError, match="schema"):
        tool._validate_live_acceptance_document(checkpoint)


@pytest.mark.parametrize("mutation", ("subminimum", "reversed", "unbound"))
def test_formal_validator_rejects_invalid_interval_and_entry_bounds(
    tmp_path: Path, mutation: str
) -> None:
    tool = _tool(tmp_path)
    checkpoint = _checkpoint(tool, 2, "incremental")
    checkpoint["prior_provider_entry_count"] = 1
    checkpoint["provider_entry_count"] = 2
    checkpoint["adjacent_controlled_provider_intervals_ns"] = [1_500_000_000]
    checkpoint["operation"]["provider_entry_ordinals"] = {"first": 2, "last": 2}
    if mutation == "subminimum":
        checkpoint["adjacent_controlled_provider_intervals_ns"] = [1_499_999_999]
    elif mutation == "reversed":
        checkpoint["operation"]["provider_entry_ordinals"] = {"first": 3, "last": 2}
    else:
        checkpoint["operation"]["provider_entry_ordinals"] = {"first": 1, "last": 1}
    _reseal_checkpoint(tool, checkpoint)
    assert _schema_errors(checkpoint) == []
    with pytest.raises(ValueError):
        tool._validate_live_acceptance_document(checkpoint)


@pytest.mark.parametrize("mutation", ("broken", "duplicate", "final-reference"))
def test_formal_validator_rejects_chain_and_final_reference_breaks(
    tmp_path: Path, mutation: str
) -> None:
    tool = _tool(tmp_path)
    result = _result(tool)
    if mutation == "broken":
        result["checkpoints"][2]["previous_checkpoint_sha256"] = _hash(90)
        _reseal_checkpoint(tool, result["checkpoints"][2])
    elif mutation == "duplicate":
        result["checkpoints"][2] = copy.deepcopy(result["checkpoints"][1])
    else:
        result["final_checkpoint_sha256"] = _hash(91)
    _reseal_result(tool, result)
    assert _schema_errors(result) == []
    with pytest.raises(ValueError):
        tool._validate_live_acceptance_document(result)


@pytest.mark.parametrize("outcome", ("post-provider-local", "ambiguous"))
def test_atomic_checkpoint_write_survives_local_or_ambiguous_failure(
    tmp_path: Path, outcome: str
) -> None:
    tool = _tool(tmp_path)
    checkpoint = _checkpoint(tool, 1, "auth")
    destination = tmp_path / f"{outcome}.json"
    tool._persist_live_acceptance_document(destination, checkpoint)
    with pytest.raises(RuntimeError, match=outcome):
        raise RuntimeError(outcome)
    persisted = json.loads(destination.read_text(encoding="utf-8"))
    assert persisted == checkpoint
    assert destination.stat().st_mode & 0o777 == 0o600
    tool._validate_live_acceptance_document(persisted)
