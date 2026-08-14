from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.analysis.features import (
    CONFLICT_POLICY_SHA256,
    FeatureError,
    activity_distribution,
    adherence_statistics,
    match_plan_items,
    quality_session_intervals,
    reject_prohibited_metric,
    resolve_conflict,
    revision_impact,
    snapshot_metric_statistics,
    snapshot_plan_matches,
    stable_hash,
    window_statistics,
)
from tests.test_analysis_a3_06 import repository


def rows():
    return tuple(
        {
            "local_date": f"2026-02-{day:02d}",
            "value_number": day,
            "canonical_unit": "steps",
            "source_revision_id": day,
        }
        for day in range(1, 8)
    )


def test_window_statistics_is_exact_and_missing_never_zero():
    values = {
        x.key: x
        for x in window_statistics(
            rows(),
            metric="steps",
            unit="steps",
            end_local_date="2026-02-07",
            window_days=7,
        )
    }
    assert values["steps.count.7d"].value == 7
    assert values["steps.sum.7d"].value == 28
    assert values["steps.mean.7d"].value == 4
    assert values["steps.median.7d"].value == 4
    assert values["steps.change.7d"].value == 6
    assert values["steps.missing_rate.7d"].value == 0
    sparse = window_statistics(
        rows()[:1],
        metric="steps",
        unit="steps",
        end_local_date="2026-02-07",
        window_days=7,
    )
    sparse_values = {x.key: x for x in sparse}
    assert sparse_values["steps.sum.7d"].value == 1
    assert sparse_values["steps.missing_rate.7d"].value == pytest.approx(6 / 7)


@pytest.mark.parametrize(
    "operation",
    [
        "simulate_provider_algorithm",
        "derive_hr_boundaries_from_time_in_zone",
        "derive_max_hr_from_single_sample",
    ],
)
def test_prohibited_algorithms_fail_closed(operation):
    with pytest.raises(FeatureError, match="prohibited"):
        window_statistics(
            (),
            metric="Body Battery",
            unit="score",
            end_local_date="2026-02-07",
            window_days=7,
            operation_kind=operation,
        )


def coverage(days):
    return tuple(
        {
            "id": f"c-{day}",
            "subject_id": 1,
            "provider": "garmin",
            "resource_kind": "activity_inventory",
            "local_date": day,
            "availability_state": "fetched",
            "record_count": 0,
            "source_revision_id": f"cr-{day}",
            "observed_at_utc": f"{day}T23:00:00Z",
        }
        for day in days
    )


def metric_coverage(
    days,
    *,
    fetched_date="2026-02-01",
    resource="body_battery",
    subject_id=1,
    provider="garmin",
):
    return tuple(
        {
            "id": f"metric-{day}",
            "subject_id": subject_id,
            "provider": provider,
            "resource_kind": resource,
            "local_date": day,
            "availability_state": "fetched" if day == fetched_date else "empty",
            "source_revision_id": "bb" if day == fetched_date else None,
            "source_revision_current": 1,
        }
        for day in days
    )


def test_window_rejects_unit_bool_duplicate_and_nonfinite():
    base = {
        "local_date": "2026-02-07",
        "value_number": 1,
        "canonical_unit": "m",
        "source_revision_id": 1,
    }
    for row in (
        {**base, "value_number": True},
        {**base, "value_number": float("nan")},
        {**base, "canonical_unit": "km"},
    ):
        with pytest.raises(FeatureError):
            window_statistics(
                (row,),
                metric="distance",
                unit="m",
                end_local_date="2026-02-07",
                window_days=7,
            )
    with pytest.raises(FeatureError, match="duplicate"):
        window_statistics(
            (base, base),
            metric="distance",
            unit="m",
            end_local_date="2026-02-07",
            window_days=7,
        )
    with pytest.raises(FeatureError, match="future"):
        window_statistics(
            ({**base, "local_date": "2026-02-08"},),
            metric="distance",
            unit="m",
            end_local_date="2026-02-07",
            window_days=7,
        )
    with pytest.raises(FeatureError, match="cross_subject"):
        window_statistics(
            (
                {**base, "subject_id": 1},
                {**base, "local_date": "2026-02-06", "subject_id": 2},
            ),
            metric="distance",
            unit="m",
            end_local_date="2026-02-07",
            window_days=7,
        )


@pytest.mark.parametrize("window", [7, 14, 28])
def test_all_contract_windows_have_exact_boundaries(window):
    start = 1
    source = tuple(
        {
            "local_date": f"2026-01-{day:02d}",
            "value_number": 1,
            "canonical_unit": "x",
            "source_revision_id": day,
        }
        for day in range(start, start + window)
    )
    result = window_statistics(
        source,
        metric="x",
        unit="x",
        end_local_date=f"2026-01-{window:02d}",
        window_days=window,
    )
    assert result[0].window_start_local_date == "2026-01-01"
    assert result[0].expected_count == window


def test_distribution_needs_coverage_before_zero_and_is_stable():
    days = tuple(f"2026-02-{x:02d}" for x in range(1, 8))
    out = activity_distribution(
        (
            {
                "id": 1,
                "local_date": "2026-02-02",
                "sport": "run",
                "elapsed_seconds": 60,
                "distance_m": 100,
                "primary_revision_id": 2,
                "is_formal_training": True,
            },
        ),
        end_local_date="2026-02-07",
        window_days=7,
        coverage_complete_dates=coverage(days),
    )
    assert next(x for x in out if x.key == "activity.climbing.count.7d").value == 0
    assert all(
        x.sample_count == 7 and x.expected_count == 7 and x.missing_count == 0
        for x in out
        if x.key.endswith("count.7d")
    )
    with pytest.raises(FeatureError, match="coverage"):
        activity_distribution(
            (),
            end_local_date="2026-02-07",
            window_days=7,
            coverage_complete_dates=coverage(days[:-1]),
        )
    assert stable_hash([x.as_dict() for x in out]) == stable_hash(
        [x.as_dict() for x in out]
    )


def test_matching_global_assignment_and_no_activity_is_unconfirmed():
    plans = (
        {
            "id": "p1",
            "local_date": "2026-02-01",
            "activity_kind": "running",
            "planned_duration_seconds": 100,
            "source_revision_id": 11,
        },
        {
            "id": "p2",
            "local_date": "2026-02-01",
            "activity_kind": "running",
            "planned_duration_seconds": 200,
            "source_revision_id": 12,
        },
    )
    activities = (
        {
            "id": "a",
            "local_date": "2026-02-01",
            "sport": "run",
            "elapsed_seconds": 200,
            "primary_revision_id": 1,
        },
        {
            "id": "b",
            "local_date": "2026-02-01",
            "sport": "run",
            "elapsed_seconds": 100,
            "primary_revision_id": 2,
        },
    )
    matched = match_plan_items(plans, activities)
    assert [(x["plan_item_id"], x["activity_id"]) for x in matched] == [
        ("p1", "b"),
        ("p2", "a"),
    ]
    assert match_plan_items((plans[0],), ())[0]["status"] == "unconfirmed"
    event = {
        "id": "e",
        "source_revision_id": "er",
        "plan_item_id": "p1",
        "accepted": True,
        "current_revision": True,
        "declaration": "cancelled",
    }
    assert (
        match_plan_items((plans[0],), (), user_events=(event,))[0]["status"]
        == "not_completed_user_confirmed"
    )


def test_match_substitution_intervals_revision_impact_and_conflict():
    plan = {
        "id": "p",
        "local_date": "2026-02-01",
        "activity_kind": "running",
        "source_revision_id": 1,
    }
    climbing = {
        "id": "c",
        "local_date": "2026-02-01",
        "sport": "climbing",
        "primary_revision_id": 2,
    }
    assert match_plan_items((plan,), (climbing,))[0]["status"] == "substituted"
    intervals = quality_session_intervals(
        (
            {
                "id": 1,
                "sport": "run",
                "quality_session": True,
                "start_time_utc": "2024-02-28T16:00:00Z",
                "local_date": "2024-02-29",
                "primary_revision_id": 1,
                "current_revision": True,
                "is_formal_training": True,
            },
            {
                "id": 2,
                "sport": "run",
                "quality_session": True,
                "start_time_utc": "2024-02-29T16:00:00Z",
                "local_date": "2024-03-01",
                "primary_revision_id": 2,
                "current_revision": True,
                "is_formal_training": True,
            },
        )
    )
    assert intervals[0]["hours"] == 24
    impact = revision_impact(
        old_revision_id="old",
        new_revision_id="new",
        changed_metrics=("training_readiness",),
        artifact_inputs=(
            {
                "artifact_id": "a",
                "input_revision_ids": ["old"],
                "metric": "training_readiness",
                "period_start_local_date": "2026-01-01",
                "period_end_local_date": "2026-01-07",
            },
        ),
        plan_inputs=(),
    )
    assert impact["impact"] == "artifact_stale"
    base = {"subject_id": 1, "metric": "x", "observed_at_utc": "2026-02-01T00:00:00Z"}
    assert (
        resolve_conflict(
            (
                {
                    **base,
                    "id": "p",
                    "source_revision_id": 1,
                    "value_origin": "provider_fact",
                    "current_revision": True,
                    "value": 1,
                    "unit": "m",
                },
                {
                    **base,
                    "id": "m",
                    "source_revision_id": 2,
                    "value_origin": "prior_model_output",
                    "value": 2,
                    "unit": "m",
                },
            )
        )["status"]
        == "resolved"
    )
    assert (
        resolve_conflict(
            (
                {
                    **base,
                    "id": "a",
                    "source_revision_id": 1,
                    "value_origin": "provider_fact",
                    "current_revision": True,
                    "value": 1,
                    "unit": "m",
                },
                {
                    **base,
                    "id": "b",
                    "source_revision_id": 2,
                    "value_origin": "provider_fact",
                    "current_revision": True,
                    "value": 1,
                    "unit": "s",
                },
            )
        )["status"]
        == "blocked"
    )


def test_golden_matching_permutation_global_multisolution_and_lineage():
    golden = json.loads(
        (Path(__file__).parent / "fixtures" / "a3_08_golden.json").read_text()
    )
    plan, activities = (
        golden["matching"]["plan"],
        tuple(golden["matching"]["activities"]),
    )
    first = match_plan_items((plan,), activities)
    second = match_plan_items((plan,), tuple(reversed(activities)))
    assert first == second
    assert first[0]["ambiguous"] is True
    assert {x["activity_id"] for x in first[0]["candidates"]} == {"a1", "a2"}
    assert first[0]["window_start_local_date"] == "2026-02-01"
    assert first[0]["input_revision_ids"] == ("pr", "r1", "r2")
    assert json.loads(json.dumps(first)) == golden["matching"]["expected_result"]
    assert stable_hash(first) == golden["matching"]["expected_sha256"]


def test_conflict_policy_artifact_hash_and_versions_do_not_drift():
    policy_path = (
        Path(__file__).parents[1] / "src/analysis/feature_conflict_policy.json"
    )
    policy = json.loads(policy_path.read_text())
    import hashlib

    assert (
        hashlib.sha256(policy_path.read_bytes()).hexdigest() == CONFLICT_POLICY_SHA256
    )
    assert policy["version"] == golden_policy_version() == "2"


def golden_policy_version():
    return json.loads(
        (Path(__file__).parent / "fixtures" / "a3_08_golden.json").read_text()
    )["conflict_policy_version"]


def test_conflict_policy_is_order_independent_and_same_rank_conflicts_block():
    base = {
        "subject_id": 1,
        "metric": "steps",
        "observed_at_utc": "2026-02-01T00:00:00Z",
        "unit": "count",
        "value_origin": "provider_fact",
        "current_revision": True,
    }
    a, b = (
        {**base, "id": "a", "source_revision_id": "new", "value": 1},
        {**base, "id": "b", "source_revision_id": "old", "value": 2},
    )
    assert resolve_conflict((a, b)) == resolve_conflict((b, a))
    assert resolve_conflict((a, b))["status"] == "blocked"
    user = {
        "id": "u",
        "subject_id": 1,
        "metric": "steps",
        "observed_at_utc": "2026-02-01T00:00:00Z",
        "unit": "count",
        "value": 99,
        "value_origin": "user_asserted",
        "scope": "symptom",
        "source_revision_id": "u1",
    }
    result = resolve_conflict((a, user))
    assert (
        result["device_fact"]["id"] == "a" and result["user_assertions"][0]["id"] == "u"
    )


@pytest.mark.parametrize(
    "metric",
    [
        "BodyBattery",
        "body battery",
        "TrainingEffect",
        "VO2Max",
        "VO₂Max",
        "Recovery Time",
    ],
)
def test_provider_metric_aggregate_is_allowed(metric):
    reject_prohibited_metric(metric)


def test_provider_body_battery_current_aggregate_is_allowed():
    row = {
        "subject_id": 1,
        "provider": "garmin",
        "resource_kind": "body_battery",
        "local_date": "2026-02-01",
        "value_number": 50,
        "canonical_unit": "score",
        "source_revision_id": "bb",
        "value_origin": "provider_derived",
        "current_revision": True,
    }
    evidence = metric_coverage(tuple(f"2026-02-{day:02d}" for day in range(1, 8)))
    result = window_statistics(
        (row,),
        metric="BodyBattery",
        unit="score",
        end_local_date="2026-02-07",
        window_days=7,
        evidence_verified=True,
        coverage_rows=evidence,
    )
    assert next(x for x in result if x.key == "BodyBattery.mean.7d").value == 50


def test_invalid_match_shapes_zero_and_infinite_iterable_are_bounded():
    p = {
        "id": "p",
        "local_date": "2026-02-01",
        "activity_kind": "running",
        "planned_duration_seconds": 0,
        "source_revision_id": "p",
    }
    a = {
        "id": "a",
        "local_date": "2026-02-01",
        "sport": "run",
        "elapsed_seconds": 1,
        "primary_revision_id": "a",
    }
    with pytest.raises(FeatureError):
        match_plan_items((p,), (a,))

    def endless():
        while True:
            yield {
                "local_date": "2026-02-01",
                "value_number": 1,
                "canonical_unit": "x",
                "source_revision_id": 1,
            }

    with pytest.raises(FeatureError, match="unbounded"):
        window_statistics(
            endless(), metric="x", unit="x", end_local_date="2026-02-07", window_days=7
        )


def test_adherence_has_coverage_gate_window_lineage_and_missing_days():
    days = tuple(f"2026-02-{i:02d}" for i in range(1, 8))
    matches = (
        {
            "window_end_local_date": "2026-02-01",
            "status": "completed_as_planned",
            "input_revision_ids": ("p", "a"),
        },
    )
    values = adherence_statistics(
        matches,
        end_local_date="2026-02-07",
        window_days=7,
        coverage_complete_dates=coverage(days),
    )
    assert {"a", "p"} <= set(values[0].input_revision_ids) and values[
        0
    ].missing_count == 0
    with pytest.raises(FeatureError, match="coverage"):
        adherence_statistics(
            matches,
            end_local_date="2026-02-07",
            window_days=7,
            coverage_complete_dates=coverage(days[:-1]),
        )


def test_generic_climb_is_as_planned_and_missing_measure_is_not_zero():
    plan = {
        "id": 1,
        "local_date": "2026-02-01",
        "activity_kind": "climbing",
        "source_revision_id": "p",
    }
    climb = {
        "id": 2,
        "local_date": "2026-02-01",
        "sport": "climbing",
        "primary_revision_id": "a",
    }
    assert match_plan_items((plan,), (climb,))[0]["status"] == "completed_as_planned"
    days = tuple(f"2026-02-{i:02d}" for i in range(1, 8))
    distribution = activity_distribution(
        ({**climb, "is_formal_training": True},),
        end_local_date="2026-02-07",
        window_days=7,
        coverage_complete_dates=coverage(days),
    )
    duration = next(x for x in distribution if x.key == "activity.climbing.duration.7d")
    assert (
        duration.value is None
        and duration.sample_count == 0
        and duration.expected_count == 1
        and duration.missing_count == 1
    )


def test_cancelled_plan_does_not_consume_activity_and_event_lineage_is_retained():
    plans = (
        {
            "id": 1,
            "local_date": "2026-02-01",
            "activity_kind": "running",
            "source_revision_id": "p1",
        },
        {
            "id": 2,
            "local_date": "2026-02-01",
            "activity_kind": "running",
            "source_revision_id": "p2",
        },
    )
    activity = {
        "id": 3,
        "local_date": "2026-02-01",
        "sport": "run",
        "primary_revision_id": "a",
    }
    event = {
        "id": 4,
        "source_revision_id": "e",
        "plan_item_id": 1,
        "accepted": True,
        "current_revision": True,
        "declaration": "cancelled",
    }
    result = match_plan_items(plans, (activity,), user_events=(event,))
    assert result[0]["status"] == "not_completed_user_confirmed"
    assert result[1]["activity_id"] == "3"
    assert "e" in result[0]["input_revision_ids"]


def test_text_symptom_and_old_current_provider_revision_are_supported():
    old = {
        "id": "old",
        "subject_id": 1,
        "metric": "steps",
        "observed_at_utc": "2026-01-01T00:00:00Z",
        "unit": "count",
        "value": 1,
        "value_origin": "provider_fact",
        "current_revision": False,
        "source_revision_id": "r1",
    }
    current = {
        **old,
        "id": "new",
        "observed_at_utc": "2026-02-01T00:00:00Z",
        "value": 2,
        "current_revision": True,
        "source_revision_id": "r2",
    }
    symptom = {
        "id": "u",
        "subject_id": 1,
        "metric": "symptom",
        "observed_at_utc": "2026-02-01T00:01:00Z",
        "unit": None,
        "value": "knee pain",
        "value_origin": "user_asserted",
        "scope": "symptom",
        "source_revision_id": "u1",
    }
    result = resolve_conflict((symptom, old, current))
    assert result["device_fact"]["id"] == "new"
    assert result["user_assertions"][0]["value"] == "knee pain"


def test_snapshot_metric_adapter_uses_real_a3_06_coverage_revision(tmp_path):
    conn, repo = repository(tmp_path)
    conn.execute(
        "UPDATE physiology_metrics SET metric_key='BodyBattery',canonical_unit='score' WHERE physiology_record_id=1"
    )
    conn.execute(
        "UPDATE resource_coverage SET resource_kind='x',source_revision_id=1 WHERE subject_id=1 AND resource_kind='daily'"
    )
    conn.executemany(
        "INSERT INTO resource_coverage(subject_id,provider,resource_kind,local_date,availability_state,observed_at_utc) VALUES(1,'garmin','x',?,'empty',?)",
        [
            (f"2026-07-{day:02d}", f"2026-07-{day:02d}T23:00:00Z")
            for day in range(16, 22)
        ],
    )
    snapshot = repo.snapshot(1, "2026-07-16", "2026-07-22")
    features = snapshot_metric_statistics(
        snapshot,
        metric="BodyBattery",
        unit="score",
        end_local_date="2026-07-22",
        window_days=7,
    )
    assert next(x for x in features if x.key == "BodyBattery.mean.7d").value == 1
    conn.close()


def test_declared_measure_missing_is_modified_with_explicit_missing_evidence():
    plan = {
        "id": 1,
        "local_date": "2026-02-01",
        "activity_kind": "running",
        "planned_duration_seconds": 3600,
        "source_revision_id": "p",
    }
    activity = {
        "id": 2,
        "local_date": "2026-02-01",
        "sport": "run",
        "primary_revision_id": "a",
    }
    result = match_plan_items((plan,), (activity,))[0]
    assert result["status"] == "completed_modified"
    assert (
        next(
            x
            for x in result["component_evidence"]
            if x["component"] == "planned_duration_seconds"
        )["state"]
        == "missing"
    )


def test_rest_never_assigns_and_unmatched_plan_in_other_optimum_is_ambiguous():
    rest = {
        "id": 1,
        "local_date": "2026-02-01",
        "activity_kind": "rest",
        "source_revision_id": "r",
    }
    run1 = {
        "id": 2,
        "local_date": "2026-02-01",
        "activity_kind": "running",
        "source_revision_id": "p1",
    }
    run2 = {
        "id": 3,
        "local_date": "2026-02-01",
        "activity_kind": "running",
        "source_revision_id": "p2",
    }
    activity = {
        "id": 4,
        "local_date": "2026-02-01",
        "sport": "run",
        "primary_revision_id": "a",
    }
    result = match_plan_items((rest, run1, run2), (activity,))
    assert result[0]["activity_id"] is None and result[0]["candidates"] == ()
    assert result[1]["ambiguous"] is True and result[2]["ambiguous"] is True
    assert "a" in result[2]["input_revision_ids"]


def test_partial_event_retains_activity_and_unknown_or_revoked_event_fails():
    plan = {
        "id": 1,
        "local_date": "2026-02-01",
        "activity_kind": "running",
        "source_revision_id": "p",
    }
    activity = {
        "id": 2,
        "local_date": "2026-02-01",
        "sport": "run",
        "primary_revision_id": "a",
    }
    event = {
        "id": 3,
        "source_revision_id": "e",
        "plan_item_id": 1,
        "accepted": True,
        "current_revision": True,
        "declaration": "partial",
    }
    result = match_plan_items((plan,), (activity,), user_events=(event,))[0]
    assert result["status"] == "partially_completed" and result["activity_id"] == "2"
    assert {"a", "e", "p"} <= set(result["input_revision_ids"])
    with pytest.raises(FeatureError, match="unknown_plan"):
        match_plan_items((plan,), (), user_events=({**event, "plan_item_id": 99},))
    with pytest.raises(FeatureError, match="event_invalid"):
        match_plan_items((plan,), (), user_events=({**event, "revoked": True},))


def test_duplicate_and_out_of_window_coverage_fail_closed():
    days = tuple(f"2026-02-{i:02d}" for i in range(1, 8))
    with pytest.raises(FeatureError, match="duplicate_coverage"):
        activity_distribution(
            (),
            end_local_date="2026-02-07",
            window_days=7,
            coverage_complete_dates=(*coverage(days), coverage(days)[0]),
        )
    with pytest.raises(FeatureError, match="out_of_window"):
        activity_distribution(
            (),
            end_local_date="2026-02-07",
            window_days=7,
            coverage_complete_dates=(*coverage(days[:-1]), *coverage(("2026-02-08",))),
        )
    cross_activity = {
        "id": 1,
        "subject_id": 2,
        "local_date": "2026-02-01",
        "sport": "run",
        "primary_revision_id": "a",
        "is_formal_training": True,
    }
    with pytest.raises(FeatureError, match="cross_subject"):
        activity_distribution(
            (cross_activity,),
            end_local_date="2026-02-07",
            window_days=7,
            coverage_complete_dates=coverage(days),
        )


def test_real_artifact_input_revision_impact_needs_no_entity_revision():
    row = {
        "analysis_run_id": 5,
        "subject_id": 1,
        "input_role": "health",
        "source_revision_id": "old",
        "source_window_start_utc": "2026-02-01T00:00:00Z",
        "source_window_end_utc": "2026-02-02T00:00:00Z",
        "ordinal": 0,
    }
    result = revision_impact(
        old_revision_id="old",
        new_revision_id="new",
        changed_metrics=(),
        artifact_inputs=(row,),
        plan_inputs=(),
        subject_id=1,
    )
    assert result["impact"] == "context_refresh"
    assert result["context_impacts"][0]["analysis_run_id"] == "5"
    assert result["input_revision_ids"] == ("new", "old")


def test_different_metrics_coexist_and_provider_derived_current_wins_old():
    base = {"subject_id": 1, "observed_at_utc": "2026-02-01T00:00:00Z"}
    steps = {
        **base,
        "id": 1,
        "metric": "steps",
        "unit": "count",
        "value": 3,
        "value_origin": "provider_fact",
        "current_revision": True,
        "source_revision_id": "s",
    }
    readiness_old = {
        **base,
        "id": 2,
        "metric": "training_readiness",
        "unit": "score",
        "value": 40,
        "value_origin": "provider_derived",
        "current_revision": False,
        "source_revision_id": "o",
    }
    readiness_new = {
        **readiness_old,
        "id": 3,
        "value": 50,
        "current_revision": True,
        "source_revision_id": "n",
    }
    result = resolve_conflict((readiness_old, steps, readiness_new))
    assert result["status"] == "resolved"
    assert {x["metric"] for x in result["provider_conclusions"]} == {
        "training_readiness"
    }


def test_real_snapshot_prescription_and_commute_do_not_claim_completion(tmp_path):
    conn, repo = repository(tmp_path)
    conn.execute(
        "UPDATE training_plan_items SET activity_kind='running',prescription_json=? WHERE training_plan_id=1",
        ('{"planned_duration_seconds":3600}',),
    )
    conn.execute(
        "UPDATE activities SET name='通勤跑',sport='run',sub_sport='commuting',provider_state='active',primary_revision_id=3 WHERE id=1"
    )
    snapshot = repo.snapshot(1, "2026-07-22", "2026-07-22")
    result = snapshot_plan_matches(snapshot)
    assert result[0]["status"] == "unconfirmed" and result[0]["activity_id"] is None
    conn.close()


def test_snapshot_matching_ignores_unrelated_dates_before_candidate_bound(
    tmp_path,
):
    conn, repo = repository(tmp_path)
    snapshot = repo.snapshot(1, "2026-07-22", "2026-07-22")
    unrelated = tuple(
        {
            "id": 100 + index,
            "subject_id": 1,
            "local_date": "2026-07-21",
            "sport": "run",
            "provider_state": "active",
            "primary_revision_id": 100 + index,
        }
        for index in range(17)
    )
    stages = tuple(
        {
            "id": row["id"],
            "summary_ready": 1,
            "fit_core_ready": 1,
            "fallback_ready": 0,
            "active_fit_revision_id": None,
        }
        for row in unrelated
    )
    widened = replace(
        snapshot,
        views={
            **snapshot.views,
            "v_current_activities": (
                *snapshot.views["v_current_activities"],
                *unrelated,
            ),
        },
        activity_stages=(*snapshot.activity_stages, *stages),
    )

    result = snapshot_plan_matches(widened)

    assert len(result) == 1 and result[0]["plan_item_id"] == "1"
    conn.close()


def test_planned_start_missing_is_candidate_evidence_not_exception():
    plan = {
        "id": 1,
        "local_date": "2026-02-01",
        "activity_kind": "running",
        "planned_start_time_utc": "2026-02-01T00:00:00Z",
        "source_revision_id": "p",
    }
    activity = {
        "id": 2,
        "local_date": "2026-02-01",
        "sport": "run",
        "primary_revision_id": "a",
    }
    result = match_plan_items((plan,), (activity,))[0]
    assert result["status"] == "completed_modified"
    assert (
        next(x for x in result["component_evidence"] if x["component"] == "start_time")[
            "state"
        ]
        == "missing"
    )


@pytest.mark.parametrize(
    ("declaration", "status", "warning"),
    [
        ("substituted", "substituted", "user_event_conflicts_with_activity_evidence"),
        (
            "device_not_recorded",
            "unconfirmed",
            "user_event_conflicts_with_activity_evidence",
        ),
        ("partial", "partially_completed", None),
    ],
)
def test_event_declaration_controls_status_without_false_conflict(
    declaration, status, warning
):
    plan = {
        "id": 1,
        "local_date": "2026-02-01",
        "activity_kind": "running",
        "source_revision_id": "p",
    }
    activity = {
        "id": 2,
        "local_date": "2026-02-01",
        "sport": "run",
        "primary_revision_id": "a",
    }
    event = {
        "id": 3,
        "plan_item_id": 1,
        "accepted": True,
        "current_revision": True,
        "declaration": declaration,
        "source_revision_id": "e",
    }
    result = match_plan_items((plan,), (activity,), user_events=(event,))[0]
    assert result["status"] == status and result["activity_id"] == "2"
    assert result["warning"] == warning


def test_snapshot_minutes_and_active_fit_revision_exclude_historical_interval(tmp_path):
    conn, repo = repository(tmp_path)
    conn.execute(
        "UPDATE training_plan_items SET activity_kind='running',prescription_json=? WHERE training_plan_id=1",
        ('{"planned_duration_minutes":60,"requires_intervals":true}',),
    )
    conn.execute(
        "UPDATE activities SET sport='run',elapsed_seconds=3600,provider_state='active',primary_revision_id=3 WHERE id=1"
    )
    conn.execute(
        "INSERT INTO activity_segments(activity_id,segment_type,segment_index,source_revision_id) VALUES(1,'interval',0,2)"
    )
    result = snapshot_plan_matches(repo.snapshot(1, "2026-07-22", "2026-07-22"))[0]
    assert result["status"] == "completed_modified"
    assert (
        next(
            x for x in result["component_evidence"] if x["component"] == "interval_lap"
        )["matched"]
        is False
    )
    assert (
        "1" in result["input_revision_ids"] and "2" not in result["input_revision_ids"]
    )
    conn.close()


def test_revision_impact_skips_null_revision_and_projects_singapore_window():
    rows = (
        {
            "artifact_id": 7,
            "analysis_run_id": 5,
            "subject_id": 1,
            "source_revision_id": None,
            "source_window_start_utc": "2026-01-31T16:00:00Z",
            "source_window_end_utc": "2026-02-01T15:59:59Z",
            "ordinal": 0,
        },
        {
            "artifact_id": 7,
            "analysis_run_id": 5,
            "subject_id": 1,
            "source_revision_id": "old",
            "source_window_start_utc": "2026-01-31T16:00:00Z",
            "source_window_end_utc": "2026-02-01T15:59:59Z",
            "ordinal": 1,
        },
    )
    result = revision_impact(
        old_revision_id="old",
        new_revision_id="new",
        changed_metrics=(),
        artifact_inputs=rows,
        plan_inputs=(),
        subject_id=1,
    )
    impact = result["artifact_impacts"][0]
    assert impact["artifact_id"] == "7" and impact["analysis_run_id"] == "5"
    assert (
        impact["period_start_local_date"] == "2026-02-01"
        and impact["period_end_local_date"] == "2026-02-01"
    )


def test_quality_interval_rejects_wrong_singapore_local_date():
    activity = {
        "id": 1,
        "sport": "run",
        "quality_session": True,
        "start_time_utc": "2026-02-01T16:30:00Z",
        "local_date": "2026-02-01",
        "primary_revision_id": 1,
        "current_revision": True,
        "is_formal_training": True,
    }
    with pytest.raises(FeatureError, match="local_date_mismatch"):
        quality_session_intervals((activity,))


def test_provider_direct_aggregate_requires_current_and_coverage():
    row = {
        "subject_id": 1,
        "provider": "garmin",
        "resource_kind": "body_battery",
        "local_date": "2026-02-01",
        "value_number": 50,
        "canonical_unit": "score",
        "source_revision_id": "bb",
        "value_origin": "provider_derived",
    }
    evidence = metric_coverage(tuple(f"2026-02-{day:02d}" for day in range(1, 8)))
    with pytest.raises(FeatureError, match="noncurrent"):
        window_statistics(
            (row,),
            metric="BodyBattery",
            unit="score",
            end_local_date="2026-02-07",
            window_days=7,
            evidence_verified=True,
            coverage_rows=evidence,
        )


def test_adherence_empty_plan_present_blocks_but_no_prior_is_explicit():
    days = tuple(f"2026-02-{i:02d}" for i in range(1, 8))
    with pytest.raises(FeatureError, match="plan_evidence_missing"):
        adherence_statistics(
            (),
            end_local_date="2026-02-07",
            window_days=7,
            coverage_complete_dates=coverage(days),
        )
    result = adherence_statistics(
        (),
        end_local_date="2026-02-07",
        window_days=7,
        coverage_complete_dates=coverage(days),
        plan_applicability="no_prior_plan",
    )
    assert next(x for x in result if "minimum_evidence" in x.key).value == 1


def test_missing_declared_measure_counts_against_match_confidence():
    plan = {
        "id": 1,
        "local_date": "2026-02-01",
        "activity_kind": "running",
        "planned_duration_seconds": 3600,
        "source_revision_id": "p",
    }
    activity = {
        "id": 2,
        "local_date": "2026-02-01",
        "sport": "run",
        "primary_revision_id": "a",
    }
    result = match_plan_items((plan,), (activity,))[0]
    # Date + sport are 65 of the 80 available evidence points, not 65/65.
    assert result["confidence"] == 0.81


def test_snapshot_fallback_does_not_claim_missing_fit_structure_is_zero(tmp_path):
    conn, repo = repository(tmp_path)
    conn.execute(
        "UPDATE training_plan_items SET activity_kind='running',prescription_json=? WHERE training_plan_id=1",
        ('{"requires_intervals":true}',),
    )
    conn.execute(
        "UPDATE activities SET sport='run',provider_state='active',primary_revision_id=3 WHERE id=1"
    )
    conn.execute(
        "UPDATE activity_source_revisions SET is_active=0 WHERE activity_id=1 AND source_role='activity_fit'"
    )
    conn.execute(
        "INSERT INTO source_revisions(id,provider,resource_kind,provider_object_id,revision_no,payload_hash,is_current,parsed_at_utc) VALUES(4,'garmin','activity_details_fallback','one',1,?,1,'2026-07-22T02:00:00Z')",
        ("d" * 64,),
    )
    conn.execute(
        "INSERT INTO activity_source_revisions(activity_id,source_revision_id,source_role,is_active) VALUES(1,4,'details_json_fallback',1)"
    )
    result = snapshot_plan_matches(repo.snapshot(1, "2026-07-22", "2026-07-22"))[0]
    evidence = next(
        x for x in result["component_evidence"] if x["component"] == "interval_lap"
    )
    assert evidence["state"] == "missing"
    conn.close()


def test_active_fit_without_segments_remains_structure_lineage(tmp_path):
    conn, repo = repository(tmp_path)
    conn.execute(
        "UPDATE training_plan_items SET activity_kind='running',prescription_json=? WHERE training_plan_id=1",
        ('{"requires_intervals":true}',),
    )
    conn.execute(
        "UPDATE activities SET sport='run',provider_state='active',primary_revision_id=3 WHERE id=1"
    )
    conn.execute(
        "DELETE FROM activity_segments WHERE activity_id=1 AND source_revision_id=1"
    )
    result = snapshot_plan_matches(repo.snapshot(1, "2026-07-22", "2026-07-22"))[0]
    candidate = result["candidates"][0]
    assert "1" in candidate["input_revision_ids"]
    assert (
        next(
            x for x in result["component_evidence"] if x["component"] == "interval_lap"
        )["matched"]
        is False
    )
    conn.close()


def test_provider_coverage_current_and_unique_are_required_for_direct_aggregate():
    row = {
        "subject_id": 1,
        "provider": "garmin",
        "resource_kind": "body_battery",
        "local_date": "2026-02-01",
        "value_number": 50,
        "canonical_unit": "score",
        "source_revision_id": "bb",
        "value_origin": "provider_derived",
        "current_revision": True,
    }
    full = metric_coverage(tuple(f"2026-02-{day:02d}" for day in range(1, 8)))
    stale = ({**full[0], "source_revision_current": 0}, *full[1:])
    with pytest.raises(FeatureError, match="noncurrent_coverage"):
        window_statistics(
            (row,),
            metric="BodyBattery",
            unit="score",
            end_local_date="2026-02-07",
            window_days=7,
            evidence_verified=True,
            coverage_rows=stale,
        )
    with pytest.raises(FeatureError, match="duplicate_coverage"):
        window_statistics(
            (row,),
            metric="BodyBattery",
            unit="score",
            end_local_date="2026-02-07",
            window_days=7,
            evidence_verified=True,
            coverage_rows=(*full, {**full[0], "source_revision_id": "other"}),
        )


def test_provider_aggregate_requires_complete_window_and_retains_coverage_lineage():
    days = tuple(f"2026-02-{day:02d}" for day in range(1, 8))
    row = {
        "subject_id": 1,
        "provider": "garmin",
        "resource_kind": "body_battery",
        "local_date": days[0],
        "value_number": 50,
        "canonical_unit": "score",
        "source_revision_id": "bb",
        "value_origin": "provider_derived",
        "current_revision": True,
    }
    full = metric_coverage(days)
    with pytest.raises(FeatureError, match="coverage_incomplete"):
        window_statistics(
            (row,),
            metric="BodyBattery",
            unit="score",
            end_local_date=days[-1],
            window_days=7,
            evidence_verified=True,
            coverage_rows=full[:1],
        )
    result = window_statistics(
        (row,),
        metric="BodyBattery",
        unit="score",
        end_local_date=days[-1],
        window_days=7,
        evidence_verified=True,
        coverage_rows=full,
    )
    missing = next(x for x in result if x.key == "BodyBattery.missing_rate.7d")
    assert missing.value == pytest.approx(6 / 7)
    assert missing.input_revision_ids == (
        "bb",
        *(f"coverage:metric-{day}" for day in days[1:]),
    )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("subject_id", 2, "cross_subject"),
        ("provider", "other", "coverage_scope_invalid"),
        ("resource_kind", "stress", "coverage_scope_invalid"),
    ],
)
def test_provider_aggregate_rejects_wrong_coverage_scope(field, value, error):
    days = tuple(f"2026-02-{day:02d}" for day in range(1, 8))
    row = {
        "subject_id": 1,
        "provider": "garmin",
        "resource_kind": "body_battery",
        "local_date": days[0],
        "value_number": 50,
        "canonical_unit": "score",
        "source_revision_id": "bb",
        "value_origin": "provider_derived",
        "current_revision": True,
    }
    evidence = list(metric_coverage(days))
    evidence[1] = {**evidence[1], field: value}
    with pytest.raises(FeatureError, match=error):
        window_statistics(
            (row,),
            metric="BodyBattery",
            unit="score",
            end_local_date=days[-1],
            window_days=7,
            evidence_verified=True,
            coverage_rows=evidence,
        )


@pytest.mark.parametrize("missing_field", ["subject_id", "provider", "resource_kind"])
def test_provider_aggregate_rejects_incomplete_row_identity(missing_field):
    days = tuple(f"2026-02-{day:02d}" for day in range(1, 8))
    row = {
        "subject_id": 1,
        "provider": "garmin",
        "resource_kind": "body_battery",
        "local_date": days[0],
        "value_number": 50,
        "canonical_unit": "score",
        "source_revision_id": "bb",
        "value_origin": "provider_derived",
        "current_revision": True,
    }
    del row[missing_field]
    with pytest.raises(FeatureError, match="provider_identity_invalid"):
        window_statistics(
            (row,),
            metric="BodyBattery",
            unit="score",
            end_local_date=days[-1],
            window_days=7,
            evidence_verified=True,
            coverage_rows=metric_coverage(days),
        )


def test_provider_aggregate_rejects_empty_row_out_of_window_and_nonclosed_coverage():
    days = tuple(f"2026-02-{day:02d}" for day in range(1, 8))
    row = {
        "subject_id": 1,
        "provider": "garmin",
        "resource_kind": "body_battery",
        "local_date": days[0],
        "value_number": 50,
        "canonical_unit": "score",
        "source_revision_id": "bb",
        "value_origin": "provider_derived",
        "current_revision": True,
    }
    full = list(metric_coverage(days))
    empty_conflict = [
        {**x, "availability_state": "empty", "source_revision_id": None}
        if x["local_date"] == days[0]
        else x
        for x in full
    ]
    with pytest.raises(FeatureError, match="provider_coverage_invalid"):
        window_statistics(
            (row,),
            metric="BodyBattery",
            unit="score",
            end_local_date=days[-1],
            window_days=7,
            evidence_verified=True,
            coverage_rows=empty_conflict,
        )
    out_of_window = [
        *full[:-1],
        {**full[-1], "local_date": "2026-02-08", "id": "metric-outside"},
    ]
    with pytest.raises(FeatureError, match="out_of_window"):
        window_statistics(
            (row,),
            metric="BodyBattery",
            unit="score",
            end_local_date=days[-1],
            window_days=7,
            evidence_verified=True,
            coverage_rows=out_of_window,
        )
    partial = [
        {**x, "availability_state": "partial"} if x["local_date"] == days[1] else x
        for x in full
    ]
    with pytest.raises(FeatureError, match="provider_coverage_invalid"):
        window_statistics(
            (row,),
            metric="BodyBattery",
            unit="score",
            end_local_date=days[-1],
            window_days=7,
            evidence_verified=True,
            coverage_rows=partial,
        )


def test_provider_aggregate_rejects_mixed_resource_rows_and_boolean_current_marker():
    days = tuple(f"2026-02-{day:02d}" for day in range(1, 8))
    row = {
        "subject_id": 1,
        "provider": "garmin",
        "resource_kind": "body_battery",
        "local_date": days[0],
        "value_number": 50,
        "canonical_unit": "score",
        "source_revision_id": "bb",
        "value_origin": "provider_derived",
        "current_revision": True,
    }
    other = {
        **row,
        "resource_kind": "stress",
        "local_date": days[1],
        "source_revision_id": "stress",
    }
    with pytest.raises(FeatureError, match="provider_scope_mixed"):
        window_statistics(
            (row, other),
            metric="score",
            unit="score",
            end_local_date=days[-1],
            window_days=7,
            evidence_verified=True,
            coverage_rows=metric_coverage(days),
        )
    boolean_marker = [
        {**x, "source_revision_current": True} if x["local_date"] == days[1] else x
        for x in metric_coverage(days)
    ]
    with pytest.raises(FeatureError, match="noncurrent_coverage"):
        window_statistics(
            (row,),
            metric="BodyBattery",
            unit="score",
            end_local_date=days[-1],
            window_days=7,
            evidence_verified=True,
            coverage_rows=boolean_marker,
        )


def test_same_sport_explicit_substitution_does_not_conflict_with_obvious_dose_change():
    plan = {
        "id": 1,
        "local_date": "2026-02-01",
        "activity_kind": "running",
        "planned_duration_seconds": 3600,
        "source_revision_id": "p",
    }
    activity = {
        "id": 2,
        "local_date": "2026-02-01",
        "sport": "run",
        "elapsed_seconds": 1800,
        "primary_revision_id": "a",
    }
    event = {
        "id": 3,
        "plan_item_id": 1,
        "accepted": True,
        "current_revision": True,
        "declaration": "substituted",
        "source_revision_id": "e",
    }
    result = match_plan_items((plan,), (activity,), user_events=(event,))[0]
    assert result["status"] == "substituted" and result["warning"] is None


def test_snapshot_rejects_conflicting_duration_units_and_accepts_equal_values(tmp_path):
    conn, repo = repository(tmp_path)
    conn.execute(
        "UPDATE activities SET sport='run',provider_state='active',primary_revision_id=3 WHERE id=1"
    )
    conn.execute(
        "UPDATE training_plan_items SET activity_kind='running',prescription_json=? WHERE training_plan_id=1",
        ('{"planned_duration_seconds":3600,"planned_duration_minutes":30}',),
    )
    with pytest.raises(FeatureError, match="duration_ambiguous"):
        snapshot_plan_matches(repo.snapshot(1, "2026-07-22", "2026-07-22"))
    conn.execute(
        "UPDATE training_plan_items SET prescription_json=? WHERE training_plan_id=1",
        ('{"planned_duration_seconds":3600,"planned_duration_minutes":60}',),
    )
    assert (
        snapshot_plan_matches(repo.snapshot(1, "2026-07-22", "2026-07-22"))[0][
            "plan_item_id"
        ]
        == "1"
    )
    conn.close()
