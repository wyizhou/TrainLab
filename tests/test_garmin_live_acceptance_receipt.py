"""Offline checks for redacted Garmin live-acceptance documents."""

from __future__ import annotations

import copy
import hashlib
import json
import os
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


def _requested_dates(mode: str) -> dict[str, str | None]:
    if mode == "incremental":
        return {"from": None, "through": "2026-08-06"}
    if mode == "snapshot":
        return {"from": None, "through": "2026-08-07"}
    if mode == "audit":
        return {"from": "2026-08-06", "through": "2026-08-06"}
    return {"from": None, "through": None}


def _effective_dates(mode: str) -> dict[str, str | None]:
    if mode == "incremental":
        return {"from": "2026-07-24", "through": "2026-08-06"}
    if mode == "snapshot":
        return {"from": "2026-08-07", "through": "2026-08-07"}
    return _requested_dates(mode)


def _checkpoint(
    tool: GarminCollectionTool, ordinal: int, mode: str
) -> dict[str, object]:
    requested_dates = _requested_dates(mode)
    document: dict[str, object] = {
        "schema_version": "1",
        "document_kind": "garmin_live_acceptance_checkpoint",
        "timezone": "Asia/Hong_Kong",
        "operation": {
            "ordinal": ordinal,
            "mode": mode,
            "status": "succeeded",
            "request_semantic_sha256": _hash(10 + ordinal),
            "requested_local_dates": requested_dates,
            "effective_local_dates": _effective_dates(mode),
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
            "changed_current_provenance_violation_count": 0,
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


def _auth_refresh_receipt(
    tool: GarminCollectionTool, token_digest: str
) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "1",
        "document_kind": "garmin_live_auth_refresh_receipt",
        "refresh_client_distribution": "python-garminconnect-0.3.6",
        "credential_serialization_sha256": token_digest,
        "counts": {
            "refresh_provider_entry_count": 1,
            "credential_replace_count": 1,
            "social_profile_http_count": 1,
            "user_settings_http_count": 1,
            "cached_identity_http_count": 0,
            "password_login_attempt_count": 0,
            "mfa_attempt_count": 0,
            "credential_fallback_attempt_count": 0,
            "library_token_dump_attempt_count": 0,
            "legacy_refresh_attempt_count": 0,
            "implicit_401_refresh_attempt_count": 0,
            "second_refresh_attempt_count": 0,
            "auth_profile_retry_attempt_count": 0,
            "unreviewed_profile_attempt_count": 0,
        },
        "credential_replaced_before_profile": True,
        "receipt_persisted_before_profile": True,
        "auth_refresh_receipt_sha256": ZERO_HASH,
    }
    document["auth_refresh_receipt_sha256"] = tool._canonical_live_acceptance_sha256(
        document
    )
    return document


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


@pytest.mark.parametrize(
    ("ordinal", "mode", "requested", "effective"),
    (
        (1, "auth", {"from": None, "through": None}, {"from": None, "through": None}),
        (
            2,
            "incremental",
            {"from": None, "through": "2026-08-06"},
            {"from": "2026-07-24", "through": "2026-08-06"},
        ),
        (
            3,
            "incremental",
            {"from": None, "through": "2026-08-06"},
            {"from": "2026-07-24", "through": "2026-08-06"},
        ),
        (
            4,
            "snapshot",
            {"from": None, "through": "2026-08-07"},
            {"from": "2026-08-07", "through": "2026-08-07"},
        ),
        (
            5,
            "audit",
            {"from": "2026-08-06", "through": "2026-08-06"},
            {"from": "2026-08-06", "through": "2026-08-06"},
        ),
    ),
)
def test_operation_dates_match_real_garmin_receipt_range_shape(
    tmp_path: Path,
    ordinal: int,
    mode: str,
    requested: dict[str, str | None],
    effective: dict[str, str | None],
) -> None:
    checkpoint = _checkpoint(_tool(tmp_path), ordinal, mode)
    operation = checkpoint["operation"]
    assert operation["requested_local_dates"] == requested
    assert operation["effective_local_dates"] == effective


@pytest.mark.parametrize(
    ("ordinal", "mode", "range_name", "field", "value"),
    (
        (2, "incremental", "effective_local_dates", "from", None),
        (4, "snapshot", "requested_local_dates", "through", "2026-08-06"),
        (4, "snapshot", "effective_local_dates", "from", None),
        (5, "audit", "requested_local_dates", "from", None),
        (1, "auth", "requested_local_dates", "through", "2026-08-06"),
    ),
)
def test_schema_and_semantic_validator_reject_non_receipt_range_shapes(
    tmp_path: Path,
    ordinal: int,
    mode: str,
    range_name: str,
    field: str,
    value: str | None,
) -> None:
    tool = _tool(tmp_path)
    checkpoint = _checkpoint(tool, ordinal, mode)
    checkpoint["operation"][range_name][field] = value
    assert _schema_errors(checkpoint)
    with pytest.raises(ValueError, match="schema"):
        tool._validate_live_acceptance_document(checkpoint)


@pytest.mark.parametrize("effective_from", ("2026-08-06", "2026-07-01"))
def test_incremental_accepts_real_dynamic_effective_start_dates(
    tmp_path: Path, effective_from: str
) -> None:
    tool = _tool(tmp_path)
    checkpoint = _checkpoint(tool, 2, "incremental")
    checkpoint["operation"]["effective_local_dates"]["from"] = effective_from
    _reseal_checkpoint(tool, checkpoint)
    assert _schema_errors(checkpoint) == []
    tool._validate_live_acceptance_document(checkpoint)


def test_incremental_requested_from_must_be_null_even_after_resealing(
    tmp_path: Path,
) -> None:
    tool = _tool(tmp_path)
    checkpoint = _checkpoint(tool, 2, "incremental")
    checkpoint["operation"]["requested_local_dates"]["from"] = "2026-08-01"
    _reseal_checkpoint(tool, checkpoint)
    assert _schema_errors(checkpoint)
    with pytest.raises(ValueError, match="schema"):
        tool._validate_live_acceptance_document(checkpoint)


def test_semantic_validator_rejects_resealed_reversed_real_date_ranges(
    tmp_path: Path,
) -> None:
    tool = _tool(tmp_path)
    checkpoint = _checkpoint(tool, 2, "incremental")
    checkpoint["operation"]["effective_local_dates"]["from"] = "2026-08-07"
    checkpoint["operation"]["effective_local_dates"]["through"] = "2026-08-06"
    _reseal_checkpoint(tool, checkpoint)
    assert _schema_errors(checkpoint) == []
    with pytest.raises(ValueError, match="date_range_reversed"):
        tool._validate_live_acceptance_document(checkpoint)


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


def test_formal_validator_rejects_resealed_wrong_mode_order(tmp_path: Path) -> None:
    tool = _tool(tmp_path)
    result = _result(tool)
    result["checkpoints"][1]["operation"]["mode"] = "snapshot"
    result["checkpoints"][1]["operation"]["requested_local_dates"] = _requested_dates(
        "snapshot"
    )
    result["checkpoints"][1]["operation"]["effective_local_dates"] = _effective_dates(
        "snapshot"
    )
    _reseal_checkpoint(tool, result["checkpoints"][1])
    _reseal_result(tool, result)
    assert _schema_errors(result) == []
    with pytest.raises(ValueError, match="mode"):
        tool._validate_live_acceptance_document(result)


def test_schema_rejects_false_receipt_schema_status(tmp_path: Path) -> None:
    checkpoint = _checkpoint(_tool(tmp_path), 1, "auth")
    checkpoint["operation"]["receipt_schema_valid"] = False
    assert _schema_errors(checkpoint)


@pytest.mark.parametrize("mutation", ("minimum", "history"))
def test_formal_validator_rejects_checkpoint_minimum_and_history_changes(
    tmp_path: Path, mutation: str
) -> None:
    tool = _tool(tmp_path)
    result = _result(tool)
    first = result["checkpoints"][0]
    second = result["checkpoints"][1]
    first["provider_entry_count"] = 2
    first["adjacent_controlled_provider_intervals_ns"] = [1_500_000_000]
    first["operation"]["provider_entry_ordinals"] = {"first": 1, "last": 2}
    _reseal_checkpoint(tool, first)
    second["previous_checkpoint_sha256"] = first["checkpoint_sha256"]
    second["prior_provider_entry_count"] = 2
    second["provider_entry_count"] = 2
    second["adjacent_controlled_provider_intervals_ns"] = [1_500_000_000]
    _reseal_checkpoint(tool, second)
    for checkpoint in result["checkpoints"][2:]:
        checkpoint["previous_checkpoint_sha256"] = second["checkpoint_sha256"]
        checkpoint["prior_provider_entry_count"] = 2
        checkpoint["provider_entry_count"] = 2
        checkpoint["adjacent_controlled_provider_intervals_ns"] = [1_500_000_000]
        _reseal_checkpoint(tool, checkpoint)
        second = checkpoint
    result["final_checkpoint_sha256"] = second["checkpoint_sha256"]
    result["provider_entry_count"] = 2
    result["adjacent_controlled_provider_intervals_ns"] = [1_500_000_000]
    if mutation == "minimum":
        result["checkpoints"][3]["configured_minimum_interval_ns"] = 1
    else:
        result["checkpoints"][3]["adjacent_controlled_provider_intervals_ns"] = [
            1_500_000_001
        ]
    previous = ZERO_HASH
    for checkpoint in result["checkpoints"]:
        checkpoint["previous_checkpoint_sha256"] = previous
        _reseal_checkpoint(tool, checkpoint)
        previous = checkpoint["checkpoint_sha256"]
    result["final_checkpoint_sha256"] = previous
    _reseal_result(tool, result)
    assert _schema_errors(result) == []
    with pytest.raises(ValueError):
        tool._validate_live_acceptance_document(result)


@pytest.mark.parametrize(
    "field",
    (
        "stable_repeat_violation_count",
        "changed_revision_violation_count",
        "changed_current_provenance_violation_count",
    ),
)
def test_formal_validator_rejects_drift_violations(tmp_path: Path, field: str) -> None:
    tool = _tool(tmp_path)
    result = _result(tool)
    result["drift_evidence"][field] = 1
    _reseal_result(tool, result)
    assert _schema_errors(result) == []
    with pytest.raises(ValueError, match="drift"):
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


def test_atomic_writer_retries_short_writes_and_rejects_zero_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool(tmp_path)
    checkpoint = _checkpoint(tool, 1, "auth")
    destination = tmp_path / "short-write.json"
    original_write = os.write
    calls = 0

    def short_write(fd: int, payload: bytes) -> int:
        nonlocal calls
        calls += 1
        return original_write(fd, payload[: max(1, len(payload) // 2)])

    monkeypatch.setattr("trainlab.garmin.base.os.write", short_write)
    tool._persist_live_acceptance_document(destination, checkpoint)
    assert calls > 1
    assert json.loads(destination.read_text(encoding="utf-8")) == checkpoint

    monkeypatch.setattr("trainlab.garmin.base.os.write", lambda _fd, _payload: 0)
    with pytest.raises(OSError, match="short_write"):
        tool._persist_live_acceptance_document(destination, checkpoint)
    assert json.loads(destination.read_text(encoding="utf-8")) == checkpoint


def test_atomic_writer_rejects_ancestor_symlink(tmp_path: Path) -> None:
    tool = _tool(tmp_path)
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match="ancestor_symlink"):
        tool._persist_live_acceptance_document(
            linked / "checkpoint.json", _checkpoint(tool, 1, "auth")
        )


def test_auth_refresh_receipt_is_redacted_and_schema_valid(tmp_path: Path) -> None:
    tool = _tool(tmp_path)
    receipt = _auth_refresh_receipt(tool, _hash(123))
    assert _schema_errors(receipt) == []
    tool._validate_live_acceptance_document(receipt)
    receipt["token"] = "forbidden"
    assert _schema_errors(receipt)


def test_single_refresh_replaces_existing_token_before_profiles(tmp_path: Path) -> None:
    tool = _tool(tmp_path)
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir(mode=0o700)
    token = credential_dir / "token"
    token.write_bytes(b"old")
    token.chmod(0o600)
    profile_calls: list[str] = []
    fresh = b"refreshed-token-bytes"
    receipt = _auth_refresh_receipt(tool, hashlib.sha256(fresh).hexdigest())
    result = tool._run_single_live_auth_refresh(
        token_path=token,
        token_is_expiring=True,
        has_refresh_credential=True,
        has_client_identity=True,
        refresh=lambda: profile_calls.append("refresh") or fresh,
        receipt_destination=tmp_path / "auth-refresh.json",
        receipt=receipt,
        social_profile=lambda: profile_calls.append("social"),
        user_settings=lambda: profile_calls.append("settings"),
        cached_identity="cached",
    )
    assert token.read_bytes() == fresh
    assert token.stat().st_mode & 0o777 == 0o600
    assert profile_calls == ["refresh", "social", "settings"]
    assert result["cached_identity"] == "cached"
    assert json.loads((tmp_path / "auth-refresh.json").read_text()) == receipt


@pytest.mark.parametrize("precondition", ("expired", "refresh", "client"))
def test_auth_refresh_preconditions_fail_before_provider_or_write(
    tmp_path: Path, precondition: str
) -> None:
    tool = _tool(tmp_path)
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir(mode=0o700)
    token = credential_dir / "token"
    token.write_bytes(b"old")
    token.chmod(0o600)
    calls: list[str] = []
    with pytest.raises(ValueError, match="precondition"):
        tool._run_single_live_auth_refresh(
            token_path=token,
            token_is_expiring=precondition != "expired",
            has_refresh_credential=precondition != "refresh",
            has_client_identity=precondition != "client",
            refresh=lambda: calls.append("refresh") or b"new",
            receipt_destination=tmp_path / "receipt.json",
            receipt=_auth_refresh_receipt(tool, _hash(1)),
            social_profile=lambda: calls.append("social"),
            user_settings=lambda: calls.append("settings"),
            cached_identity="cached",
        )
    assert calls == [] and token.read_bytes() == b"old"


def test_profile_failure_keeps_refreshed_token_and_stops_before_second_profile(
    tmp_path: Path,
) -> None:
    tool = _tool(tmp_path)
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir(mode=0o700)
    token = credential_dir / "token"
    token.write_bytes(b"old")
    token.chmod(0o600)
    fresh = b"new"
    calls: list[str] = []
    with pytest.raises(RuntimeError, match="profile"):
        tool._run_single_live_auth_refresh(
            token_path=token,
            token_is_expiring=True,
            has_refresh_credential=True,
            has_client_identity=True,
            refresh=lambda: fresh,
            receipt_destination=tmp_path / "receipt.json",
            receipt=_auth_refresh_receipt(tool, hashlib.sha256(fresh).hexdigest()),
            social_profile=lambda: (_ for _ in ()).throw(RuntimeError("profile")),
            user_settings=lambda: calls.append("settings"),
            cached_identity="cached",
        )
    assert token.read_bytes() == fresh and calls == []


def test_atomic_token_writer_completes_partial_writes_or_keeps_old_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool(tmp_path)
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir(mode=0o700)
    token = credential_dir / "token"
    token.write_bytes(b"old")
    token.chmod(0o600)
    original_write = os.write

    def partial_write(fd: int, payload: bytes) -> int:
        return original_write(fd, payload[:1])

    monkeypatch.setattr("trainlab.garmin.base.os.write", partial_write)
    assert (
        tool._atomic_replace_existing_token(token, b"fresh")
        == hashlib.sha256(b"fresh").hexdigest()
    )
    assert token.read_bytes() == b"fresh"

    monkeypatch.setattr("trainlab.garmin.base.os.write", lambda _fd, _payload: 0)
    with pytest.raises(OSError, match="short_write"):
        tool._atomic_replace_existing_token(token, b"newer")
    assert token.read_bytes() == b"fresh"
