from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.analysis.quality_gate import (
    QUALITY_GATE_POLICY_SHA256,
    QUALITY_GATE_POLICY_VERSION,
    QualityGate,
    QualityGateError,
    QualityGateRequest,
)
from src.analysis.stable_views import StableSnapshot, StableSubjectContext
from src.garmin_catalog import (
    CATALOG_VERSION,
    HEALTH_COLLECTION_ALLOWLIST,
    RESOURCE_CATALOG,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads(
    (ROOT / "src/analysis/quality_policy.json").read_text(encoding="utf-8")
)
REQUIRED = tuple(item["resource_kind"] for item in POLICY["required_resources"])
CONDITIONAL = tuple(item["resource_kind"] for item in POLICY["conditional_resources"])
ALL_RESOURCES = (*REQUIRED, *CONDITIONAL)
AS_OF = "2026-07-22T00:00:00Z"


def local_dates(start: str = "2026-07-16", count: int = 1) -> tuple[str, ...]:
    first = date.fromisoformat(start)
    return tuple((first + timedelta(days=index)).isoformat() for index in range(count))


def observed(day: str) -> str:
    return f"{day}T00:00:00Z"


def snapshot(
    *,
    window: tuple[str, ...] = local_dates(),
    coverage: tuple[dict[str, object], ...] | None = None,
    capabilities: tuple[dict[str, object], ...] | None = None,
    cursors: tuple[dict[str, object], ...] | None = None,
    activities: tuple[dict[str, object], ...] | None = None,
    gaps: tuple[dict[str, object], ...] = (),
    quality: tuple[dict[str, object], ...] = (),
    facts: tuple[dict[str, object], ...] = (),
    views: dict[str, tuple[dict[str, object], ...]] | None = None,
    reasons: tuple[dict[str, object], ...] = (),
    subject_context: StableSubjectContext | None = None,
) -> StableSnapshot:
    if capabilities is None:
        capabilities = tuple(
            {
                "environment_key": "global",
                "resource_kind": kind,
                "capability_state": "supported"
                if kind in REQUIRED
                else "not_supported",
                "last_checked_at_utc": "2026-07-21T23:00:00Z",
                "next_probe_at_utc": None,
            }
            for kind in ALL_RESOURCES
        )
    if coverage is None:
        coverage = tuple(
            {
                "resource_kind": kind,
                "local_date": day,
                "availability_state": "fetched"
                if kind in REQUIRED
                else "not_supported",
                "record_count": 1 if kind in REQUIRED else 0,
                "observed_at_utc": observed(day),
            }
            for kind in ALL_RESOURCES
            for day in window
        )
    if cursors is None:
        cursors = tuple(
            {
                "resource_kind": kind,
                "cursor_grain": "local_date",
                "complete_through_local_date": window[-1],
                "catalog_version": CATALOG_VERSION,
            }
            for kind in ("steps", "user_summary")
        )
    if activities is None:
        inventory_row = next(
            row
            for row in coverage
            if row["resource_kind"] == "activity_inventory"
            and row["local_date"] == window[0]
        )
        activities = (
            {
                "id": 1,
                "provider_activity_id": "synthetic-activity",
                "local_date": window[0],
                "provider_state": "active",
                "summary_ready": 1,
                "fit_core_ready": 1,
                "fallback_ready": 0,
                "inventory_coverage_state": inventory_row["availability_state"],
                "inventory_coverage_observed_at_utc": inventory_row["observed_at_utc"],
            },
        )
    if views is None:
        views = {
            "v_current_sleep_sessions": (),
            "v_current_training_plans": (),
            "v_training_plan_items": (),
            "v_current_analysis_artifacts": (),
        }
    return StableSnapshot(
        views,
        coverage,
        cursors,
        gaps,
        activities,
        quality,
        facts,
        capabilities,
        reasons,
        (),
        subject_context
        or StableSubjectContext(1, "Asia/Hong_Kong", "garmin", "account", True),
    )


def request(
    route: str = "daily_summary",
    start: str = "2026-07-16",
    end: str = "2026-07-16",
    *,
    as_of_utc: str = AS_OF,
    **kwargs: object,
) -> QualityGateRequest:
    return QualityGateRequest(
        route,
        1,
        start,
        end,
        as_of_utc,
        **kwargs,  # type: ignore[arg-type]
    )


def blocker_codes(result: object) -> tuple[str, ...]:
    return tuple(reason.code for reason in getattr(result, "blockers"))


def warning_codes(result: object) -> tuple[str, ...]:
    return tuple(reason.code for reason in getattr(result, "warnings"))


def coverage_with(
    source: StableSnapshot,
    kind: str,
    day: str,
    **changes: object,
) -> tuple[dict[str, object], ...]:
    return tuple(
        {**row, **changes}
        if row["resource_kind"] == kind and row["local_date"] == day
        else row
        for row in source.coverage
    )


def capability_with(
    source: StableSnapshot, kind: str, **changes: object
) -> tuple[dict[str, object], ...]:
    return tuple(
        {**row, **changes} if row["resource_kind"] == kind else row
        for row in source.capabilities
    )


def coverage_row(
    source: StableSnapshot,
    kind: str,
    day: str,
    **changes: object,
) -> dict[str, object]:
    current = next(
        row
        for row in source.coverage
        if row["resource_kind"] == kind and row["local_date"] == day
    )
    return {**current, **changes}


def test_policy_and_result_schema_are_versioned_and_match_collection_catalog() -> None:
    expected_conditionals = set(HEALTH_COLLECTION_ALLOWLIST)
    assert CATALOG_VERSION == POLICY["catalog_version"] == "garmin-v4"
    assert set(CONDITIONAL) == expected_conditionals
    assert all(
        RESOURCE_CATALOG[kind].requestable
        and RESOURCE_CATALOG[kind].scope in {"daily", "range"}
        and RESOURCE_CATALOG[kind].conditional
        for kind in CONDITIONAL
    )
    assert {"activity_inventory"} == set(REQUIRED)
    assert QUALITY_GATE_POLICY_VERSION == "5"
    assert (
        QUALITY_GATE_POLICY_SHA256
        == "9d0ba9a8774d2a3592d7f07c7794b7ea1be077185cf0eb23181d1ddf6d97b453"
    )
    result = QualityGate().evaluate(request(), snapshot())
    result.validate()
    assert result.as_dict()["schema_version"] == "1"


def test_request_requires_canonical_as_of_and_uses_hong_kong_date_at_23z() -> None:
    gate = QualityGate()
    crossing_as_of = "2026-07-15T23:30:00Z"  # 2026-07-16 in Hong Kong.
    source = snapshot(window=("2026-07-16",))
    source = replace(
        source,
        capabilities=tuple(
            {
                **row,
                "last_checked_at_utc": "2026-07-15T23:00:00Z",
                "next_probe_at_utc": "2026-07-15T23:59:00Z",
            }
            for row in source.capabilities
        ),
        coverage=tuple(
            {**row, "observed_at_utc": "2026-07-15T23:10:00Z"}
            for row in source.coverage
        ),
        activity_stages=tuple(
            {
                **row,
                "inventory_coverage_observed_at_utc": "2026-07-15T23:10:00Z",
            }
            for row in source.activity_stages
        ),
    )
    assert (
        gate.evaluate(request(as_of_utc=crossing_as_of), source).state
        == "ready_with_warnings"
    )

    stale_check = replace(
        source,
        capabilities=tuple(
            {**row, "last_checked_at_utc": "2026-07-15T15:59:59Z"}
            for row in source.capabilities
        ),
    )
    assert "capability_expired" in blocker_codes(
        gate.evaluate(request(as_of_utc=crossing_as_of), stale_check)
    )
    stale_probe = replace(
        source,
        capabilities=tuple(
            {**row, "next_probe_at_utc": "2026-07-15T15:59:59Z"}
            for row in source.capabilities
        ),
    )
    assert "capability_expired" in blocker_codes(
        gate.evaluate(request(as_of_utc=crossing_as_of), stale_probe)
    )
    for value in (
        "2026-07-15T23:30:00+00:00",
        "2026-07-15T23:30:00.000000Z",
        "not-a-time",
    ):
        with pytest.raises(QualityGateError, match="as_of_utc_invalid"):
            request(as_of_utc=value).dates()
    with pytest.raises(QualityGateError, match="window_after_as_of"):
        request(start="2026-07-17", end="2026-07-17", as_of_utc=crossing_as_of).dates()


def test_utc_timestamps_accept_fixed_microseconds_with_trailing_zeroes() -> None:
    base = snapshot()
    source = replace(
        base,
        capabilities=tuple(
            {**row, "last_checked_at_utc": "2026-07-21T23:00:00.752070Z"}
            for row in base.capabilities
        ),
    )

    assert (
        QualityGate()
        .evaluate(request(as_of_utc="2026-07-22T00:00:00.752070Z"), source)
        .state
        == "ready_with_warnings"
    )

    for value in (
        "2026-07-22T00:00:00.7520700Z",
        "2026-07-22T00:00:00.75200Z",
        "2026-07-22T00:00:00.000000Z",
        "2026-07-22T00:00:00+00:00",
    ):
        with pytest.raises(QualityGateError, match="as_of_utc_invalid"):
            request(as_of_utc=value).dates()


def test_capability_rows_must_use_one_consistent_environment() -> None:
    gate = QualityGate()
    base = snapshot()
    mixed = replace(
        base,
        capabilities=capability_with(base, "sleep", environment_key="CN"),
    )
    result = gate.evaluate(request(), mixed)
    assert "capability_conflict" in blocker_codes(result)
    assert any(
        reason.code == "capability_conflict" and reason.entity == "environment"
        for reason in result.blockers
    )


def test_optional_unavailable_requires_matching_coverage_for_every_day() -> None:
    gate = QualityGate()
    week = local_dates(count=7)
    base = snapshot(window=week)
    assert (
        gate.evaluate(request("weekly_summary", week[0], week[-1]), base).state
        == "ready_with_warnings"
    )

    missing = replace(
        base,
        coverage=tuple(
            row
            for row in base.coverage
            if not (row["resource_kind"] == "sleep" and row["local_date"] == week[3])
        ),
    )
    result = gate.evaluate(request("weekly_summary", week[0], week[-1]), missing)
    assert "coverage_missing" in blocker_codes(result)

    conflict = replace(
        base,
        coverage=coverage_with(
            base, "sleep", week[2], availability_state="not_enabled"
        ),
    )
    assert "capability_conflict" in blocker_codes(
        gate.evaluate(request("weekly_summary", week[0], week[-1]), conflict)
    )

    supported = replace(
        base,
        capabilities=capability_with(base, "sleep", capability_state="supported"),
        coverage=tuple(
            {
                **row,
                "availability_state": "empty",
            }
            if row["resource_kind"] == "sleep"
            else row
            for row in base.coverage
        ),
        cursors=base.cursors
        + (
            {
                "resource_kind": "sleep",
                "cursor_grain": "local_date",
                "complete_through_local_date": week[-1],
                "catalog_version": CATALOG_VERSION,
            },
        ),
    )
    supported_result = gate.evaluate(
        request("weekly_summary", week[0], week[-1]), supported
    )
    assert not any(
        reason.code == "coverage_optional" and reason.entity == "sleep"
        for reason in supported_result.warnings
    )


def test_required_activity_coverage_and_catalog_fail_closed() -> None:
    gate = QualityGate()
    base = snapshot()
    missing = replace(
        base,
        coverage=tuple(
            row for row in base.coverage if row["resource_kind"] != "activity_inventory"
        ),
    )
    assert "coverage_missing" in blocker_codes(gate.evaluate(request(), missing))
    partial = replace(
        base,
        coverage=coverage_with(
            base, "activity_inventory", "2026-07-16", availability_state="partial"
        ),
    )
    assert "coverage_partial" in blocker_codes(gate.evaluate(request(), partial))
    # Activity inventory is coverage-bound rather than cursor-bound.  Health
    # cursors are checked only when that optional resource is explicitly
    # supported and selected by a future route.
    forged = replace(
        base,
        coverage=(
            {
                "resource_kind": "invented",
                "local_date": "2026-07-16",
                "availability_state": "fetched",
                "record_count": 1,
                "observed_at_utc": "2026-07-16T00:00:00Z",
            },
        ),
    )
    assert {"coverage_missing"}.issubset(
        blocker_codes(gate.evaluate(request(), forged))
    )


@pytest.mark.parametrize(
    ("historical_state", "historical_count"),
    (("partial", 1), ("error", 0)),
)
def test_newer_completed_coverage_replaces_old_partial_or_error_history(
    historical_state: str,
    historical_count: int,
) -> None:
    gate = QualityGate()
    base = snapshot()
    historical = coverage_row(
        base,
        "activity_inventory",
        "2026-07-16",
        availability_state=historical_state,
        record_count=historical_count,
        observed_at_utc="2026-07-15T16:00:00Z",
    )
    source = replace(base, coverage=(historical, *base.coverage))
    result = gate.evaluate(request(), source)
    assert result.state == "ready_with_warnings"
    assert "coverage_partial" not in blocker_codes(result)
    assert "coverage_error" not in blocker_codes(result)
    assert "coverage_ambiguous" not in blocker_codes(result)


def test_newer_error_supersedes_old_fetched_coverage() -> None:
    gate = QualityGate()
    base = snapshot()
    newer_error = coverage_row(
        base,
        "activity_inventory",
        "2026-07-16",
        availability_state="error",
        record_count=0,
        observed_at_utc="2026-07-16T01:00:00Z",
    )
    source = replace(base, coverage=(*base.coverage, newer_error))
    result = gate.evaluate(request(), source)
    assert "coverage_error" in blocker_codes(result)
    assert "coverage_ambiguous" not in blocker_codes(result)


def test_repeated_semantically_identical_latest_coverage_coalesces() -> None:
    gate = QualityGate()
    base = snapshot()
    duplicate = coverage_row(base, "activity_inventory", "2026-07-16")
    source = replace(base, coverage=(*base.coverage, duplicate))
    result = gate.evaluate(request(), source)
    assert result.state == "ready_with_warnings"
    assert "coverage_ambiguous" not in blocker_codes(result)


def test_conflicting_latest_coverage_tie_blocks_ambiguous() -> None:
    gate = QualityGate()
    base = snapshot()
    conflicting = coverage_row(
        base,
        "activity_inventory",
        "2026-07-16",
        availability_state="error",
        record_count=0,
    )
    source = replace(base, coverage=(*base.coverage, conflicting))
    result = gate.evaluate(request(), source)
    assert "coverage_ambiguous" in blocker_codes(result)


def test_snapshot_partial_then_completed_sync_uses_latest_and_ignores_future() -> None:
    gate = QualityGate()
    base = snapshot()
    snapshot_partial = coverage_row(
        base,
        "activity_inventory",
        "2026-07-16",
        availability_state="partial",
        observed_at_utc="2026-07-15T16:00:00Z",
    )
    future_error = coverage_row(
        base,
        "activity_inventory",
        "2026-07-16",
        availability_state="error",
        record_count=0,
        observed_at_utc="2026-07-22T00:00:01Z",
    )
    source = replace(
        base,
        coverage=(snapshot_partial, *base.coverage, future_error),
    )
    result = gate.evaluate(request(), source)
    assert result.state == "ready_with_warnings"
    assert "coverage_partial" not in blocker_codes(result)
    assert "coverage_error" not in blocker_codes(result)


@pytest.mark.parametrize(
    "changes",
    (
        {"availability_state": "invalid-state"},
        {"record_count": -1},
    ),
)
def test_future_coverage_with_malformed_state_or_count_does_not_affect_current_as_of(
    changes: dict[str, object],
) -> None:
    gate = QualityGate()
    base = snapshot()
    future = coverage_row(
        base,
        "activity_inventory",
        "2026-07-16",
        observed_at_utc="2026-07-22T00:00:01Z",
        **changes,
    )
    source = replace(base, coverage=(*base.coverage, future))
    result = gate.evaluate(request(), source)
    assert result.state == "ready_with_warnings"
    assert "coverage_state_unknown" not in blocker_codes(result)


def test_future_coverage_with_malformed_local_date_is_ignored_before_date_validation() -> (
    None
):
    base = snapshot()
    future_bad_date = coverage_row(
        base,
        "activity_inventory",
        "2026-07-16",
        local_date="not-a-local-date",
        observed_at_utc="2026-07-15T00:00:01Z",
    )
    result = QualityGate().evaluate(
        request(), replace(base, coverage=(*base.coverage, future_bad_date))
    )
    assert result.state == "ready_with_warnings"
    assert "coverage_state_unknown" not in blocker_codes(result)

    blockers: list[object] = []
    warnings: list[object] = []
    QualityGate._coverage(
        replace(base, coverage=(future_bad_date,)),
        ("not-a-local-date",),
        datetime(2026, 7, 15, tzinfo=timezone.utc),
        {"activity_inventory": "supported"},
        blockers,  # type: ignore[arg-type]
        warnings,  # type: ignore[arg-type]
    )
    assert "coverage_missing" in tuple(reason.code for reason in blockers)
    assert "coverage_state_unknown" not in tuple(reason.code for reason in blockers)


def test_future_coverage_with_malformed_timestamp_remains_fail_closed() -> None:
    base = snapshot()
    malformed_timestamp = coverage_row(
        base,
        "activity_inventory",
        "2026-07-16",
        availability_state="invalid-state",
        observed_at_utc="not-a-timestamp",
    )
    result = QualityGate().evaluate(
        request(), replace(base, coverage=(*base.coverage, malformed_timestamp))
    )
    assert "coverage_state_unknown" in blocker_codes(result)


def test_activity_inventory_proof_binds_selected_latest_coverage() -> None:
    gate = QualityGate()
    base = snapshot()
    old_partial = coverage_row(
        base,
        "activity_inventory",
        "2026-07-16",
        availability_state="partial",
        observed_at_utc="2026-07-15T16:00:00Z",
    )
    source = replace(base, coverage=(old_partial, *base.coverage))
    result = gate.evaluate(request(), source)
    assert result.state == "ready_with_warnings"
    assert "activity_inventory_proof_missing" not in blocker_codes(result)


def test_every_activity_requires_summary_core_or_fallback_and_inventory_proof() -> None:
    gate = QualityGate()
    base = snapshot()
    no_summary = replace(
        base,
        activity_stages=tuple(
            {**row, "summary_ready": 0} for row in base.activity_stages
        ),
    )
    assert "activity_stage_incomplete" in blocker_codes(
        gate.evaluate(request(), no_summary)
    )
    no_detail = replace(
        base,
        activity_stages=tuple(
            {**row, "fit_core_ready": 0, "fallback_ready": 0}
            for row in base.activity_stages
        ),
    )
    assert "activity_stage_incomplete" in blocker_codes(
        gate.evaluate(request(), no_detail)
    )
    fallback = replace(
        base,
        activity_stages=tuple(
            {**row, "fit_core_ready": 0, "fallback_ready": 1}
            for row in base.activity_stages
        ),
    )
    assert gate.evaluate(request(), fallback).state == "ready_with_warnings"
    no_inventory_proof = replace(
        base,
        activity_stages=tuple(
            {**row, "inventory_coverage_observed_at_utc": "2026-07-16T01:00:00Z"}
            for row in base.activity_stages
        ),
    )
    assert "activity_inventory_proof_missing" in blocker_codes(
        gate.evaluate(request(), no_inventory_proof)
    )
    zero_inventory_count = replace(
        base,
        coverage=coverage_with(
            base, "activity_inventory", "2026-07-16", record_count=0
        ),
    )
    assert {
        "activity_inventory_proof_missing",
        "coverage_state_unknown",
    }.issubset(blocker_codes(gate.evaluate(request(), zero_inventory_count)))
    empty_inventory = replace(
        base,
        coverage=coverage_with(
            base, "activity_inventory", "2026-07-16", availability_state="empty"
        ),
        activity_stages=tuple(
            {**row, "inventory_coverage_state": "empty"} for row in base.activity_stages
        ),
    )
    assert "activity_inventory_proof_missing" in blocker_codes(
        gate.evaluate(request(), empty_inventory)
    )
    absent = replace(base, activity_stages=())
    assert "activity_absent_unconfirmed" in warning_codes(
        gate.evaluate(request(), absent)
    )


def test_every_fetched_sleep_date_requires_matching_singapore_end_date() -> None:
    gate = QualityGate()
    week = local_dates(count=7)
    base = snapshot(window=week)
    sleep_coverage = tuple(
        {**row, "availability_state": "fetched", "record_count": 1}
        if row["resource_kind"] == "sleep"
        else row
        for row in base.coverage
    )
    sessions = []
    for day in week[:-1]:
        end = date.fromisoformat(day)
        start = end - timedelta(days=1)
        sessions.append(
            {
                "subject_id": 1,
                "session_type": "main_sleep",
                "start_time_utc": f"{start.isoformat()}T16:00:00Z",
                "end_time_utc": f"{day}T00:00:00Z",
            }
        )
    source = replace(
        base,
        capabilities=capability_with(base, "sleep", capability_state="supported"),
        coverage=sleep_coverage,
        cursors=base.cursors
        + (
            {
                "resource_kind": "sleep",
                "cursor_grain": "local_date",
                "complete_through_local_date": week[-1],
                "catalog_version": CATALOG_VERSION,
            },
        ),
        views={**base.views, "v_current_sleep_sessions": tuple(sessions)},
    )
    result = gate.evaluate(request("weekly_summary", week[0], week[-1]), source)
    assert "sleep_evidence_missing" in blocker_codes(result)
    assert any(
        reason.entity == week[-1]
        for reason in result.blockers
        if reason.code == "sleep_evidence_missing"
    )
    final_start = date.fromisoformat(week[-1]) - timedelta(days=1)
    complete = replace(
        source,
        views={
            **source.views,
            "v_current_sleep_sessions": tuple(sessions)
            + (
                {
                    "subject_id": 1,
                    "session_type": "main_sleep",
                    "start_time_utc": f"{final_start.isoformat()}T16:00:00Z",
                    "end_time_utc": f"{week[-1]}T00:00:00Z",
                },
            ),
        },
    )
    assert (
        gate.evaluate(request("weekly_summary", week[0], week[-1]), complete).state
        == "ready_with_warnings"
    )


def revision_snapshot() -> StableSnapshot:
    base = snapshot(window=("2026-07-18",))
    views = {
        **base.views,
        "v_current_training_plans": (
            {
                "id": 7,
                "subject_id": 1,
                "analysis_artifact_id": 70,
                "plan_start_local_date": "2026-07-16",
                "plan_end_local_date": "2026-07-22",
                "timezone": "Asia/Hong_Kong",
                "status": "active",
                "objective_json": "{}",
                "constraints_json": "{}",
                "created_at_utc": "2026-07-15T23:00:00Z",
            },
        ),
        "v_training_plan_items": (
            {
                "id": 71,
                "subject_id": 1,
                "training_plan_id": 7,
                "item_index": 2,
                "local_date": "2026-07-18",
                "activity_kind": "rest",
                "prescription_json": "{}",
                "rationale_text": None,
            },
        ),
        "v_current_analysis_artifacts": (
            {
                "id": 70,
                "subject_id": 1,
                "artifact_kind": "weekly_training_plan",
                "period_start_local_date": "2026-07-16",
                "period_end_local_date": "2026-07-22",
                "revision_no": 1,
                "schema_version": "1",
                "content_sha256": "a" * 64,
                "created_at_utc": "2026-07-15T23:00:00Z",
            },
        ),
    }
    reasons = (
        {
            "id": 9,
            "event_type": "plan_revision_reason_recorded",
            "actor_role": "trainlab",
            "occurred_at_utc": "2026-07-17T00:00:00Z",
            "trust_level": "system_generated",
            "created_by": "mail_agent",
            "subject_id": 1,
            "source_mail_message_id": 11,
            "source_mail_thread_id": 12,
            "source_revision_id": 13,
            "change_kind": "availability",
            "affected_local_dates": ["2026-07-18"],
            "constraints": {},
            "effective_local_date": "2026-07-18",
            "current_plan_id": 7,
        },
    )
    return replace(base, views=views, plan_reasons=reasons)


def test_plan_reason_lineage_shape_and_subject_ownership_are_strict() -> None:
    gate = QualityGate()
    req = request(
        "revise_plan",
        "2026-07-18",
        "2026-07-18",
        plan_id=7,
        reason_event_id=9,
    )
    source = revision_snapshot()
    assert gate.evaluate(req, source).state == "ready_with_warnings"

    no_artifact = replace(
        source, views={**source.views, "v_current_analysis_artifacts": ()}
    )
    assert "plan_lineage_invalid" in blocker_codes(gate.evaluate(req, no_artifact))
    missing_item = replace(source, views={**source.views, "v_training_plan_items": ()})
    assert "plan_incomplete" in blocker_codes(gate.evaluate(req, missing_item))
    legacy_item_shape = replace(
        source,
        views={
            **source.views,
            "v_training_plan_items": tuple(
                {key: value for key, value in row.items() if key != "prescription_json"}
                for row in source.views["v_training_plan_items"]
            ),
        },
    )
    assert "plan_incomplete" in blocker_codes(gate.evaluate(req, legacy_item_shape))
    bad_reason = replace(
        source,
        plan_reasons=tuple(
            {**row, "actor_role": "user"} for row in source.plan_reasons
        ),
    )
    assert "plan_reason_invalid" in blocker_codes(gate.evaluate(req, bad_reason))
    revoked_shape = replace(
        source,
        plan_reasons=tuple({**row, "revoked": True} for row in source.plan_reasons),
    )
    assert "plan_reason_invalid" in blocker_codes(gate.evaluate(req, revoked_shape))
    cross_subject_plan = replace(
        source,
        views={
            **source.views,
            "v_current_training_plans": tuple(
                {**row, "subject_id": 2}
                for row in source.views["v_current_training_plans"]
            ),
        },
    )
    assert "subject_identity_invalid" in blocker_codes(
        gate.evaluate(req, cross_subject_plan)
    )
    cross_subject_reason = replace(
        source,
        plan_reasons=tuple({**row, "subject_id": 2} for row in source.plan_reasons),
    )
    assert "subject_identity_invalid" in blocker_codes(
        gate.evaluate(req, cross_subject_reason)
    )
    missing_identity = replace(source, subject_context=None)
    assert "subject_identity_invalid" in blocker_codes(
        gate.evaluate(req, missing_identity)
    )


@pytest.mark.parametrize("status", ("open", "acknowledged"))
def test_open_and_acknowledged_error_quality_issues_block(status: str) -> None:
    source = snapshot(
        quality=(
            {
                "entity_type": "daily_health",
                "entity_id": 1,
                "severity": "error",
                "status": status,
            },
        )
    )
    assert "quality_error" in blocker_codes(QualityGate().evaluate(request(), source))


def test_resolved_quality_issues_do_not_block_and_acknowledged_warning_warns() -> None:
    gate = QualityGate()
    inactive = snapshot(
        quality=(
            {
                "entity_type": "daily_health",
                "entity_id": 1,
                "severity": "error",
                "status": "resolved",
            },
            {
                "entity_type": "activity",
                "entity_id": 1,
                "severity": "warning",
                "status": "suppressed",
            },
        )
    )
    inactive_result = gate.evaluate(request(), inactive)
    assert "quality_error" not in blocker_codes(inactive_result)
    assert "quality_warning" not in warning_codes(inactive_result)
    acknowledged = replace(
        inactive,
        quality_issues=(
            {
                "entity_type": "daily_health",
                "entity_id": 1,
                "severity": "warning",
                "status": "acknowledged",
            },
        ),
    )
    assert "quality_warning" in warning_codes(gate.evaluate(request(), acknowledged))


def test_quality_issue_outside_requested_day_does_not_warn() -> None:
    source = snapshot(
        quality=(
            {
                "entity_type": "activity",
                "entity_id": 1,
                "local_date": "2026-07-15",
                "severity": "warning",
                "status": "open",
            },
        )
    )
    assert "quality_warning" not in warning_codes(
        QualityGate().evaluate(request(), source)
    )


def test_gap_and_next_action_mapping_are_deterministic() -> None:
    gate = QualityGate()
    collection = replace(
        snapshot(),
        gaps=(
            {
                "resource_kind": "steps",
                "window_start_local_date": "2026-07-16",
                "window_end_local_date": "2026-07-16",
                "status": "deferred",
            },
        ),
    )
    result = gate.evaluate(request(), collection)
    assert "gap_deferred" in blocker_codes(result)
    assert result.next_action == "rerun_collection"
    repair = replace(
        snapshot(),
        quality_issues=(
            {
                "entity_type": "daily_health",
                "entity_id": 1,
                "severity": "error",
                "status": "open",
            },
        ),
    )
    assert gate.evaluate(request(), repair).next_action == "repair_data"


def test_malformed_snapshot_rows_return_controlled_fail_closed_result() -> None:
    gate = QualityGate()
    base = snapshot()
    malformed_rows = (
        replace(base, coverage=("not-a-row",)),  # type: ignore[arg-type]
        replace(base, capabilities=({"resource_kind": []},)),
        replace(
            base,
            views={**base.views, "v_current_training_plans": ("not-a-row",)},  # type: ignore[dict-item]
        ),
        replace(
            base,
            quality_issues=(
                {
                    "entity_type": [],
                    "entity_id": {},
                    "severity": "error",
                    "status": "open",
                },
            ),
        ),
    )
    for source in malformed_rows:
        result = gate.evaluate(request(), source)
        assert result.state == "blocked"
        assert set(blocker_codes(result)) <= {
            "quality_state_unknown",
            "snapshot_malformed",
        }
        assert result.next_action == "repair_data"
        result.validate()


def test_reasons_are_sorted_deduplicated_bounded_and_fail_closed_on_overflow() -> None:
    gate = QualityGate()
    issues = tuple(
        {
            "entity_type": "daily_health",
            "entity_id": index,
            "severity": "error",
            "status": "open",
        }
        for index in range(1, 101)
    )
    result = gate.evaluate(request(), snapshot(quality=issues))
    assert result.state == "blocked"
    assert len(result.blockers) == POLICY["max_reasons_per_bucket"]
    assert "gate_evidence_limit_exceeded" in blocker_codes(result)
    assert result.blockers == tuple(sorted(set(result.blockers)))
    assert all(
        len(reason.entity) <= POLICY["max_entity_length"] for reason in result.blockers
    )
    result.validate()


def test_weekly_and_revision_request_shapes_are_controlled() -> None:
    week = local_dates(count=7)
    gate = QualityGate()
    assert (
        gate.evaluate(
            request("weekly_summary", week[0], week[-1]), snapshot(window=week)
        ).state
        == "ready_with_warnings"
    )
    with pytest.raises(QualityGateError, match="weekly_window_invalid"):
        gate.evaluate(
            request("weekly_plan", week[0], week[-2]),
            snapshot(window=week[:-1]),
        )
    with pytest.raises(QualityGateError, match="revision_request_invalid"):
        gate.evaluate(
            request("revise_plan", "2026-07-18", "2026-07-18"),
            snapshot(window=("2026-07-18",)),
        )
    with pytest.raises(QualityGateError, match="request_invalid"):
        request(plan_id=7).dates()
    with pytest.raises(QualityGateError, match="request_invalid"):
        QualityGate().evaluate(None, snapshot())  # type: ignore[arg-type]


def test_gate_is_pure_and_deterministic() -> None:
    gate = QualityGate()
    source = snapshot()
    first = gate.evaluate(request(), source)
    second = gate.evaluate(request(), source)
    assert first == second
    assert first.blockers == tuple(sorted(first.blockers))
    assert first.warnings == tuple(sorted(first.warnings))
    connection = sqlite3.connect(":memory:", isolation_level=None)
    before = connection.total_changes
    assert gate.evaluate(request(), source).snapshot_sha256 == first.snapshot_sha256
    assert connection.total_changes == before
    assert not connection.in_transaction
