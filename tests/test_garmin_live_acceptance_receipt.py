"""Offline checks for redacted Garmin live-acceptance documents."""

from __future__ import annotations

import copy
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
        "controlled_provider_entry_ledger": [],
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
    auth_checkpoint = _auth_refresh_receipt(tool, status="rotation_checkpoint")
    auth_final = _auth_refresh_receipt(
        tool,
        status="succeeded",
        previous=auth_checkpoint["auth_refresh_receipt_sha256"],
    )
    auth_progress = copy.deepcopy(auth_final["progress"])
    auth_progress["final_receipt"]["completed"] = True
    document: dict[str, object] = {
        "schema_version": "1",
        "document_kind": "garmin_live_acceptance_result",
        "timezone": "Asia/Hong_Kong",
        "checkpoints": checkpoints,
        "provider_entry_count": 0,
        "configured_minimum_interval_ns": 1_500_000_000,
        "adjacent_controlled_provider_intervals_ns": [],
        "controlled_provider_entry_ledger": [],
        "auth_refresh": {
            "auth_rotation_checkpoint_sha256": auth_checkpoint[
                "auth_refresh_receipt_sha256"
            ],
            "auth_refresh_receipt_sha256": auth_final["auth_refresh_receipt_sha256"],
            "counts": auth_final["counts"],
            "ordering": auth_final["ordering"],
            "credential_authority": auth_final["credential_authority"],
            "progress": auth_progress,
        },
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
    tool: GarminCollectionTool,
    *,
    status: str = "succeeded",
    previous: str = ZERO_HASH,
) -> dict[str, object]:
    counts = {
        "refresh_provider_entry_count": 1,
        "credential_replace_count": 1,
        "social_profile_http_count": 1 if status == "succeeded" else 0,
        "user_settings_http_count": 1 if status == "succeeded" else 0,
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
    }
    completed = {
        "precondition",
        "prepared_receipt",
        "refresh",
        "credential_replace",
        "parent_fsync",
        "reload",
        "authority_recheck",
    }
    entered = set(completed)
    if status == "rotation_checkpoint":
        entered.add("rotation_checkpoint_receipt")
    elif status == "succeeded":
        completed.update(
            {
                "rotation_checkpoint_receipt",
                "social_profile",
                "cached_identity",
                "user_settings",
            }
        )
        entered.update(completed)
        entered.add("final_receipt")
    document: dict[str, object] = {
        "schema_version": "1",
        "document_kind": "garmin_live_auth_refresh_receipt",
        "status": status,
        "failure_stage": "none",
        "refresh_client_distribution": "python-garminconnect-0.3.6",
        "counts": counts,
        "ordering": {
            "refresh_before_credential_replace": True,
            "credential_replaced_before_profile": True,
            "checkpoint_persisted_before_profile": True,
            "first_profile_stops_second_on_error": True,
            "cached_identity_zero_http": True,
        },
        "credential_authority": {
            "token_path_unchanged": True,
            "token_directory_unchanged": True,
            "owner_unchanged": True,
            "group_unchanged": True,
            "directory_mode_0700": True,
            "file_mode_0600": True,
            "structure_unchanged": True,
            "content_changed_exactly_once": True,
            "reloaded_nonexpiring": True,
        },
        "progress": {
            name: {
                "attempted": name in entered,
                "entered": name in entered,
                "completed": name in completed,
            }
            for name in (
                "precondition",
                "prepared_receipt",
                "refresh",
                "credential_replace",
                "parent_fsync",
                "reload",
                "authority_recheck",
                "rotation_checkpoint_receipt",
                "social_profile",
                "cached_identity",
                "user_settings",
                "final_receipt",
            )
        },
        "previous_auth_receipt_sha256": previous,
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


def test_partition_coverage_records_only_observed_membership(tmp_path: Path) -> None:
    tool = _tool(tmp_path)
    result = _result(tool)
    result["partition_coverage"] = {
        "idempotence": ["incremental-through-2026-08-06"],
        "pacing": ["first-call"],
        "durability": ["completed-operation-integer-nanosecond-intervals"],
    }
    _reseal_result(tool, result)
    assert _schema_errors(result) == []
    tool._validate_live_acceptance_document(result)
    result["partition_coverage"]["pacing"].append("first-call")
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


def test_final_result_cannot_claim_a_failure_outcome(tmp_path: Path) -> None:
    tool = _tool(tmp_path)
    result = _result(tool)
    result["failure_evidence"] = {
        "outcome": "post-provider-local",
        "last_checkpoint_preserved": True,
    }
    _reseal_result(tool, result)
    assert _schema_errors(result) == []
    with pytest.raises(ValueError, match="result_failure_evidence"):
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
    receipt = _auth_refresh_receipt(tool)
    assert _schema_errors(receipt) == []
    tool._validate_live_acceptance_document(receipt)
    receipt["token"] = "forbidden"
    assert _schema_errors(receipt)


def _observed_counts(calls: list[str]) -> dict[str, int]:
    counts = GarminCollectionTool._empty_auth_refresh_counts()
    counts["refresh_provider_entry_count"] = calls.count("refresh")
    counts["social_profile_http_count"] = calls.count("social")
    counts["user_settings_http_count"] = calls.count("settings")
    return counts


def test_verified_refresh_replaces_existing_token_before_profiles(
    tmp_path: Path,
) -> None:
    tool = _tool(tmp_path)
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir(mode=0o700)
    token = credential_dir / "token"
    token.write_bytes(b"old")
    token.chmod(0o600)
    profile_calls: list[str] = []
    fresh = b"refreshed-token-bytes"
    result = tool._run_verified_live_auth_refresh(
        token_path=token,
        load_token_state=lambda: {
            "proactive_expiring": token.read_bytes() == b"old",
            "has_di_refresh_credential": True,
            "has_di_client_identity": True,
        },
        refresh_di_token=lambda: profile_calls.append("refresh"),
        serialize_refreshed=lambda: fresh,
        prepared_destination=tmp_path / "auth-prepared.json",
        checkpoint_destination=tmp_path / "rotation-checkpoint.json",
        final_destination=tmp_path / "auth-final.json",
        stop_destination=tmp_path / "auth-stop.json",
        observed_counts=lambda: _observed_counts(profile_calls),
        social_profile=lambda: profile_calls.append("social"),
        cache_identity=lambda _profile: None,
        user_settings=lambda: profile_calls.append("settings"),
    )
    assert token.read_bytes() == fresh
    assert token.stat().st_mode & 0o777 == 0o600
    assert token.stat().st_uid == credential_dir.stat().st_uid
    assert token.stat().st_gid == credential_dir.stat().st_gid
    assert profile_calls == ["refresh", "social", "settings"]
    checkpoint = json.loads((tmp_path / "rotation-checkpoint.json").read_text())
    final = json.loads((tmp_path / "auth-final.json").read_text())
    prepared = json.loads((tmp_path / "auth-prepared.json").read_text())
    assert prepared["status"] == "prepared"
    assert prepared["progress"]["prepared_receipt"] == {
        "attempted": True,
        "entered": True,
        "completed": False,
    }
    assert checkpoint["progress"]["prepared_receipt"]["completed"] is True
    assert checkpoint["progress"]["rotation_checkpoint_receipt"]["completed"] is False
    assert checkpoint["counts"]["social_profile_http_count"] == 0
    assert checkpoint["counts"]["user_settings_http_count"] == 0
    assert final["counts"]["social_profile_http_count"] == 1
    assert final["counts"]["user_settings_http_count"] == 1
    assert final["progress"]["rotation_checkpoint_receipt"]["completed"] is True
    assert final["progress"]["final_receipt"] == {
        "attempted": True,
        "entered": True,
        "completed": False,
    }
    assert result["progress"]["parent_fsync"] == {
        "attempted": True,
        "entered": True,
        "completed": True,
    }
    assert result["progress"]["final_receipt"]["completed"] is True
    assert result["final_receipt"] == final


@pytest.mark.parametrize("precondition", ("expired", "refresh", "client"))
def test_verified_auth_preconditions_fail_before_provider_or_write(
    tmp_path: Path, precondition: str
) -> None:
    tool = _tool(tmp_path)
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir(mode=0o700)
    token = credential_dir / "token"
    token.write_bytes(b"old")
    token.chmod(0o600)
    calls: list[str] = []
    with pytest.raises(RuntimeError, match="precondition"):
        tool._run_verified_live_auth_refresh(
            token_path=token,
            load_token_state=lambda: {
                "proactive_expiring": precondition != "expired",
                "has_di_refresh_credential": precondition != "refresh",
                "has_di_client_identity": precondition != "client",
            },
            refresh_di_token=lambda: calls.append("refresh"),
            serialize_refreshed=lambda: b"new",
            prepared_destination=tmp_path / "prepared.json",
            checkpoint_destination=tmp_path / "checkpoint.json",
            final_destination=tmp_path / "final.json",
            stop_destination=tmp_path / "stop.json",
            observed_counts=lambda: _observed_counts(calls),
            social_profile=lambda: calls.append("social"),
            cache_identity=lambda _profile: None,
            user_settings=lambda: calls.append("settings"),
        )
    assert calls == [] and token.read_bytes() == b"old"
    stopped = json.loads((tmp_path / "stop.json").read_text())
    assert stopped["failure_stage"] == "preflight"


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
    with pytest.raises(RuntimeError, match="social_profile"):
        tool._run_verified_live_auth_refresh(
            token_path=token,
            load_token_state=lambda: {
                "proactive_expiring": token.read_bytes() == b"old",
                "has_di_refresh_credential": True,
                "has_di_client_identity": True,
            },
            refresh_di_token=lambda: calls.append("refresh"),
            serialize_refreshed=lambda: fresh,
            prepared_destination=tmp_path / "prepared.json",
            checkpoint_destination=tmp_path / "checkpoint.json",
            final_destination=tmp_path / "final.json",
            stop_destination=tmp_path / "stop.json",
            observed_counts=lambda: _observed_counts(calls),
            social_profile=lambda: (
                calls.append("social") or (_ for _ in ()).throw(RuntimeError("profile"))
            ),
            cache_identity=lambda _profile: None,
            user_settings=lambda: calls.append("settings"),
        )
    stop = json.loads((tmp_path / "stop.json").read_text())
    assert token.read_bytes() == fresh and calls == ["refresh", "social"]
    assert stop["status"] == "stopped"
    assert stop["counts"]["social_profile_http_count"] == 1


def test_refresh_failure_writes_no_token_and_persists_true_prefix_stop(
    tmp_path: Path,
) -> None:
    tool = _tool(tmp_path)
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir(mode=0o700)
    token = credential_dir / "token"
    token.write_bytes(b"old")
    token.chmod(0o600)
    calls: list[str] = []
    with pytest.raises(RuntimeError, match="rotation"):
        tool._run_verified_live_auth_refresh(
            token_path=token,
            load_token_state=lambda: {
                "proactive_expiring": True,
                "has_di_refresh_credential": True,
                "has_di_client_identity": True,
            },
            refresh_di_token=lambda: (
                calls.append("refresh")
                or (_ for _ in ()).throw(RuntimeError("provider"))
            ),
            serialize_refreshed=lambda: b"new",
            prepared_destination=tmp_path / "prepared.json",
            checkpoint_destination=tmp_path / "checkpoint.json",
            final_destination=tmp_path / "final.json",
            stop_destination=tmp_path / "stop.json",
            observed_counts=lambda: _observed_counts(calls),
            social_profile=lambda: calls.append("social"),
            cache_identity=lambda _profile: None,
            user_settings=lambda: calls.append("settings"),
        )
    stopped = json.loads((tmp_path / "stop.json").read_text())
    assert token.read_bytes() == b"old"
    assert calls == ["refresh"]
    assert stopped["counts"]["refresh_provider_entry_count"] == 1
    assert stopped["counts"]["credential_replace_count"] == 0


def test_reload_expiry_failure_preserves_rotated_credential_in_stop(
    tmp_path: Path,
) -> None:
    tool = _tool(tmp_path)
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir(mode=0o700)
    token = credential_dir / "token"
    token.write_bytes(b"old")
    token.chmod(0o600)
    calls: list[str] = []
    with pytest.raises(RuntimeError, match="rotation"):
        tool._run_verified_live_auth_refresh(
            token_path=token,
            load_token_state=lambda: {
                "proactive_expiring": True,
                "has_di_refresh_credential": True,
                "has_di_client_identity": True,
            },
            refresh_di_token=lambda: calls.append("refresh"),
            serialize_refreshed=lambda: b"new",
            prepared_destination=tmp_path / "prepared.json",
            checkpoint_destination=tmp_path / "checkpoint.json",
            final_destination=tmp_path / "final.json",
            stop_destination=tmp_path / "stop.json",
            observed_counts=lambda: _observed_counts(calls),
            social_profile=lambda: calls.append("social"),
            cache_identity=lambda _profile: None,
            user_settings=lambda: calls.append("settings"),
        )
    stopped = json.loads((tmp_path / "stop.json").read_text())
    assert token.read_bytes() == b"new"
    assert stopped["credential_authority"]["content_changed_exactly_once"] is True
    assert stopped["credential_authority"]["reloaded_nonexpiring"] is False


def test_parent_fsync_stop_preserves_actual_replacement_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool(tmp_path)
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir(mode=0o700)
    token = credential_dir / "token"
    token.write_bytes(b"old")
    token.chmod(0o600)
    calls: list[str] = []
    original_fsync = os.fsync
    fsync_calls = 0
    credential_inode = credential_dir.stat().st_ino

    def fail_only_parent_fsync(descriptor: int) -> None:
        nonlocal fsync_calls
        if os.fstat(descriptor).st_ino == credential_inode:
            fsync_calls += 1
            raise OSError("parent fsync fixture")
        original_fsync(descriptor)

    monkeypatch.setattr("trainlab.garmin.base.os.fsync", fail_only_parent_fsync)
    with pytest.raises(RuntimeError, match="rotation"):
        tool._run_verified_live_auth_refresh(
            token_path=token,
            load_token_state=lambda: {
                "proactive_expiring": token.read_bytes() == b"old",
                "has_di_refresh_credential": True,
                "has_di_client_identity": True,
            },
            refresh_di_token=lambda: calls.append("refresh"),
            serialize_refreshed=lambda: b"new",
            prepared_destination=tmp_path / "prepared.json",
            checkpoint_destination=tmp_path / "checkpoint.json",
            final_destination=tmp_path / "final.json",
            stop_destination=tmp_path / "stop.json",
            observed_counts=lambda: _observed_counts(calls),
            social_profile=lambda: calls.append("social"),
            cache_identity=lambda _profile: None,
            user_settings=lambda: calls.append("settings"),
        )
    stopped = json.loads((tmp_path / "stop.json").read_text())
    assert token.read_bytes() == b"new" and calls == ["refresh"] and fsync_calls == 1
    assert stopped["failure_stage"] == "parent_fsync"
    assert stopped["counts"]["credential_replace_count"] == 1
    assert stopped["progress"]["credential_replace"]["completed"] is True
    assert stopped["progress"]["parent_fsync"] == {
        "attempted": True,
        "entered": True,
        "completed": False,
    }


def test_rotation_failure_before_directory_fsync_never_enters_parent_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool(tmp_path)
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir(mode=0o700)
    token = credential_dir / "token"
    token.write_bytes(b"old")
    token.chmod(0o600)
    calls: list[str] = []

    def fail_before_parent_fsync(
        _destination: Path, _serialized: bytes, *, stage_callback: object = None
    ) -> None:
        assert stage_callback is not None
        raise OSError("write fixture")

    monkeypatch.setattr(
        tool, "_atomic_replace_existing_token", fail_before_parent_fsync
    )
    with pytest.raises(RuntimeError, match="rotation"):
        tool._run_verified_live_auth_refresh(
            token_path=token,
            load_token_state=lambda: {
                "proactive_expiring": True,
                "has_di_refresh_credential": True,
                "has_di_client_identity": True,
            },
            refresh_di_token=lambda: calls.append("refresh"),
            serialize_refreshed=lambda: b"new",
            prepared_destination=tmp_path / "prepared.json",
            checkpoint_destination=tmp_path / "checkpoint.json",
            final_destination=tmp_path / "final.json",
            stop_destination=tmp_path / "stop.json",
            observed_counts=lambda: _observed_counts(calls),
            social_profile=lambda: calls.append("social"),
            cache_identity=lambda _profile: None,
            user_settings=lambda: calls.append("settings"),
        )
    stopped = json.loads((tmp_path / "stop.json").read_text())
    assert token.read_bytes() == b"old" and calls == ["refresh"]
    assert stopped["progress"]["parent_fsync"] == {
        "attempted": False,
        "entered": False,
        "completed": False,
    }


def test_prepared_receipt_failure_stops_before_refresh_or_token_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool(tmp_path)
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir(mode=0o700)
    token = credential_dir / "token"
    token.write_bytes(b"old")
    token.chmod(0o600)
    original_persist = tool._persist_live_auth_refresh_receipt
    calls: list[str] = []

    def fail_prepared(destination: Path, document: dict[str, object]) -> None:
        if destination.name == "prepared.json":
            raise OSError("fixture")
        original_persist(destination, document)

    monkeypatch.setattr(tool, "_persist_live_auth_refresh_receipt", fail_prepared)
    with pytest.raises(RuntimeError, match="prepared_receipt"):
        tool._run_verified_live_auth_refresh(
            token_path=token,
            load_token_state=lambda: {
                "proactive_expiring": True,
                "has_di_refresh_credential": True,
                "has_di_client_identity": True,
            },
            refresh_di_token=lambda: calls.append("refresh"),
            serialize_refreshed=lambda: b"new",
            prepared_destination=tmp_path / "prepared.json",
            checkpoint_destination=tmp_path / "checkpoint.json",
            final_destination=tmp_path / "final.json",
            stop_destination=tmp_path / "stop.json",
            observed_counts=lambda: _observed_counts(calls),
            social_profile=lambda: calls.append("social"),
            cache_identity=lambda _profile: None,
            user_settings=lambda: calls.append("settings"),
        )
    stopped = json.loads((tmp_path / "stop.json").read_text())
    assert calls == [] and token.read_bytes() == b"old"
    assert stopped["failure_stage"] == "prepared_receipt_persist"


@pytest.mark.parametrize(
    ("failed_name", "stage", "expected_calls"),
    (
        ("checkpoint.json", "checkpoint_persist", ["refresh"]),
        ("final.json", "final_receipt_persist", ["refresh", "social", "settings"]),
    ),
)
def test_later_auth_receipt_persist_failures_preserve_true_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_name: str,
    stage: str,
    expected_calls: list[str],
) -> None:
    tool = _tool(tmp_path)
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir(mode=0o700)
    token = credential_dir / "token"
    token.write_bytes(b"old")
    token.chmod(0o600)
    original_persist = tool._persist_live_auth_refresh_receipt
    calls: list[str] = []

    def fail_selected(destination: Path, document: dict[str, object]) -> None:
        if destination.name == failed_name:
            raise OSError("fixture")
        original_persist(destination, document)

    monkeypatch.setattr(tool, "_persist_live_auth_refresh_receipt", fail_selected)
    with pytest.raises(RuntimeError):
        tool._run_verified_live_auth_refresh(
            token_path=token,
            load_token_state=lambda: {
                "proactive_expiring": token.read_bytes() == b"old",
                "has_di_refresh_credential": True,
                "has_di_client_identity": True,
            },
            refresh_di_token=lambda: calls.append("refresh"),
            serialize_refreshed=lambda: b"new",
            prepared_destination=tmp_path / "prepared.json",
            checkpoint_destination=tmp_path / "checkpoint.json",
            final_destination=tmp_path / "final.json",
            stop_destination=tmp_path / "stop.json",
            observed_counts=lambda: _observed_counts(calls),
            social_profile=lambda: calls.append("social"),
            cache_identity=lambda _profile: None,
            user_settings=lambda: calls.append("settings"),
        )
    stopped = json.loads((tmp_path / "stop.json").read_text())
    assert token.read_bytes() == b"new" and calls == expected_calls
    assert stopped["failure_stage"] == stage
    assert stopped["progress"]["prepared_receipt"]["completed"] is True
    assert stopped["progress"]["rotation_checkpoint_receipt"]["completed"] is (
        failed_name == "final.json"
    )
    assert stopped["progress"]["final_receipt"]["entered"] is (
        failed_name == "final.json"
    )


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
    tool._atomic_replace_existing_token(token, b"fresh")
    assert token.read_bytes() == b"fresh"

    monkeypatch.setattr("trainlab.garmin.base.os.write", lambda _fd, _payload: 0)
    with pytest.raises(OSError):
        tool._atomic_replace_existing_token(token, b"newer")
    assert token.read_bytes() == b"fresh"
