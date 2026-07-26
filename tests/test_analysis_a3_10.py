from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from trainlab.analysis.context import (
    ANALYSIS_INPUT_SCHEMA_SHA256,
    ANALYSIS_INPUT_SCHEMA_VERSION,
    CONTEXT_POLICY_SHA256,
    CONTEXT_POLICY_VERSION,
    AnalysisContextBuilder,
    ContextBuildError,
    ContextBuildRequest,
    ContextSource,
    TechnicalSampleRequest,
    load_context_source,
    parse_canonical_context_json,
    parse_canonical_json,
    validate_analysis_context,
)
from trainlab.analysis.harness import HarnessBundle, SchemaEvidence
from trainlab.analysis.quality_gate import QualityGateResult
from trainlab.analysis.stable_views import StableSnapshot, StableSubjectContext


VIEW_NAMES = (
    "v_current_daily_health",
    "v_current_physiology_records",
    "v_current_physiology_metrics",
    "v_current_sleep_sessions",
    "v_current_activities",
    "v_activity_segments",
    "v_activity_metric_sources",
    "v_active_user_facts",
    "v_current_analysis_artifacts",
    "v_current_weekly_summaries",
    "v_current_training_plans",
    "v_training_plan_items",
    "v_analysis_history_context",
)


def snapshot(
    *,
    subject_id=1,
    views=None,
    coverage=(),
    cursors=(),
    gaps=(),
    activity_stages=(),
    quality_issues=(),
    facts=(),
    capabilities=(),
    plan_reasons=(),
):
    data = {name: () for name in VIEW_NAMES}
    data.update(views or {})
    return StableSnapshot(
        views=data,
        coverage=tuple(coverage),
        cursors=tuple(cursors),
        gaps=tuple(gaps),
        activity_stages=tuple(activity_stages),
        quality_issues=tuple(quality_issues),
        facts=tuple(facts),
        capabilities=tuple(capabilities),
        plan_reasons=tuple(plan_reasons),
        audit=(),
        subject_context=StableSubjectContext(
            subject_id, "Asia/Singapore", "garmin", "account", True
        ),
    )


def snapshot_hash(value):
    encoded = json.dumps(
        asdict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return sha256(encoded).hexdigest()


def gate(value):
    return QualityGateResult("ready", snapshot_hash(value), (), (), "none")


def bundle(route):
    return HarnessBundle(
        route=route,
        harness_version="1" * 64,
        files=(),
        schema_evidence=SchemaEvidence(
            ANALYSIS_INPUT_SCHEMA_VERSION,
            ANALYSIS_INPUT_SCHEMA_SHA256,
            "future-output-v1",
            "2" * 64,
        ),
    )


def daily(**overrides):
    values = dict(
        route="daily",
        run_key="analysis:1:daily:2026-07-23:fixture",
        subject_id=1,
        as_of_utc="2026-07-24T00:00:00Z",
        summary_local_date="2026-07-23",
        advice_local_date="2026-07-24",
    )
    values.update(overrides)
    return ContextBuildRequest(**values)


def weekly(**overrides):
    values = dict(
        route="weekly",
        run_key="analysis:1:weekly:2026-07-20:fixture",
        subject_id=1,
        as_of_utc="2026-07-24T00:00:00Z",
        review_end_local_date="2026-07-20",
    )
    values.update(overrides)
    return ContextBuildRequest(**values)


def health(identity, day, revision, **extra):
    row = {
        "id": identity,
        "subject_id": 1,
        "local_date": day,
        "values_json": '{"resting_heart_rate":50}',
        "source_revision_id": revision,
    }
    row.update(extra)
    return row


def activity(identity, day, revision, **extra):
    row = {
        "id": identity,
        "subject_id": 1,
        "provider_activity_id": f"provider-{identity}",
        "name": f"Run {identity}",
        "sport": "running",
        "sub_sport": "road",
        "start_time_utc": f"{day}T01:00:00Z",
        "end_time_utc": f"{day}T02:00:00Z",
        "local_date": day,
        "elapsed_seconds": 3600,
        "timer_seconds": 3500,
        "distance_m": 10000,
        "primary_revision_id": revision,
        "provider_state": "active",
    }
    row.update(extra)
    return row


def artifact(identity, kind, start, end, revision=1, trust="prior_model_output"):
    return {
        "id": identity,
        "subject_id": 1,
        "artifact_kind": kind,
        "period_start_local_date": start,
        "period_end_local_date": end,
        "revision_no": revision,
        "schema_version": "1",
        "content_sha256": f"{identity:064x}",
        "is_current": True,
        "created_at_utc": "2026-07-20T00:00:00Z",
        "trust_class": trust,
    }


def build(request, value, *, features=(), adherence=(), samples=()):
    return AnalysisContextBuilder().build(
        request,
        ContextSource(value, tuple(samples)),
        quality_gate=gate(value),
        harness_bundle=bundle(request.source_route()),
        deterministic_features=features,
        plan_adherence=adherence,
    )


def test_static_schema_and_context_policy_are_versioned_and_frozen():
    root = Path(__file__).parents[1]
    schema_path = root / "harness/schemas/analysis_input.schema.json"
    policy_path = root / "src/trainlab/analysis/context_policy.json"
    schema = json.loads(schema_path.read_text())
    policy = json.loads(policy_path.read_text())
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert ANALYSIS_INPUT_SCHEMA_VERSION == "1"
    assert ANALYSIS_INPUT_SCHEMA_SHA256 == "aa4faf89d324ea2d8ca228a131e144dca05e47609e37d716714b176e10b46329"
    assert ANALYSIS_INPUT_SCHEMA_SHA256 == sha256(schema_path.read_bytes()).hexdigest()
    assert CONTEXT_POLICY_VERSION == "1.0.0-a3-10"
    assert CONTEXT_POLICY_SHA256 == "3b189416ac59460320c81bf31589119093fb19ed55e52cd53f0a4ad73a08d3b3"
    assert CONTEXT_POLICY_SHA256 == sha256(policy_path.read_bytes()).hexdigest()
    assert policy["default_max_context_bytes"] == 1_000_000
    assert policy["pruning_order"] == [
        "optional_activity_extras",
        "old_activity_details",
        "old_daily_history",
        "optional_provider_display",
    ]


def test_fixed_route_windows_daily_weekly_revise_and_regenerate():
    assert daily().validated_periods() == {
        "summary": {
            "start_local_date": "2026-07-23",
            "end_local_date": "2026-07-23",
        },
        "advice": {
            "start_local_date": "2026-07-24",
            "end_local_date": "2026-07-24",
        },
        "review": None,
        "plan": None,
        "baseline": {
            "start_local_date": "2026-07-09",
            "end_local_date": "2026-07-22",
        },
        "effective_local_date": None,
    }
    weekly_periods = weekly().validated_periods()
    assert weekly_periods["review"] == {
        "start_local_date": "2026-07-14",
        "end_local_date": "2026-07-20",
    }
    assert weekly_periods["plan"] == {
        "start_local_date": "2026-07-21",
        "end_local_date": "2026-07-27",
    }
    assert weekly_periods["baseline"]["start_local_date"] == "2026-06-16"
    revise = ContextBuildRequest(
        "revise_plan",
        "analysis:1:revise_plan:10:fixture",
        1,
        "2026-07-24T00:00:00Z",
        plan_start_local_date="2026-07-21",
        plan_end_local_date="2026-07-27",
        effective_local_date="2026-07-24",
    )
    assert revise.validated_periods()["baseline"] == {
        "start_local_date": "2026-06-26",
        "end_local_date": "2026-07-23",
    }
    regenerated = replace(
        weekly(),
        route="regenerate",
        regenerate_source_route="weekly",
    )
    assert regenerated.validated_periods() == weekly_periods


@pytest.mark.parametrize(
    "build_request",
    [
        daily(advice_local_date="2026-07-25"),
        weekly(review_end_local_date="2026-07-24"),
        daily(max_context_bytes=True),
        daily(subject_id=True),
        replace(daily(), route="regenerate"),
    ],
)
def test_invalid_windows_bool_limits_and_unbound_regenerate_fail_closed(build_request):
    with pytest.raises(ContextBuildError):
        build_request.validated_periods()


def test_repository_seam_uses_only_bounded_snapshot_and_sample_summary():
    value = snapshot(
        views={
            "v_current_activities": (
                activity(1, "2026-07-23", "activity-rev"),
            )
        }
    )

    class Repository:
        calls = []

        def snapshot(self, subject_id, start_local_date, end_local_date):
            self.calls.append(("snapshot", subject_id, start_local_date, end_local_date))
            return value

        def technical_samples(
            self, subject_id, activity_id, metric, start_utc, end_utc, *, limit
        ):
            self.calls.append(
                ("samples", subject_id, activity_id, metric, start_utc, end_utc, limit)
            )
            return {
                "activity_id": activity_id,
                "metric": metric,
                "start_utc": start_utc,
                "end_utc": end_utc,
                "count": 2,
                "minimum": 100,
                "maximum": 120,
                "latest": 120,
                "truncated": False,
            }

    repository = Repository()
    sample = TechnicalSampleRequest(
        1,
        "heart_rate_bpm",
        "2026-07-23T01:00:00Z",
        "2026-07-23T02:00:00Z",
        10,
    )
    source = load_context_source(repository, daily(), (sample,))
    assert source.snapshot is value and len(source.technical_samples) == 1
    assert repository.calls == [
        ("snapshot", 1, "2026-07-09", "2026-07-24"),
        (
            "samples",
            1,
            1,
            "heart_rate_bpm",
            "2026-07-23T01:00:00Z",
            "2026-07-23T02:00:00Z",
            10,
        ),
    ]


def test_manifest_is_one_to_one_recomputable_and_permutation_stable():
    rows = (
        health(2, "2026-07-22", "health-2"),
        health(1, "2026-07-23", "health-1"),
    )
    first_snapshot = snapshot(views={"v_current_daily_health": rows})
    second_snapshot = snapshot(views={"v_current_daily_health": tuple(reversed(rows))})
    first = build(daily(), first_snapshot)
    # The quality gate binds to the immutable snapshot ordering.  Perturb a
    # separately supplied derived-record order while keeping that snapshot fixed.
    features = (
        {
            "key": "b",
            "value": 2,
            "value_origin": "derived_statistic",
            "algorithm_version": "2",
            "input_revision_ids": ["health-2"],
        },
        {
            "key": "a",
            "value": 1,
            "value_origin": "derived_statistic",
            "algorithm_version": "2",
            "input_revision_ids": ["health-1"],
        },
    )
    ordered = build(daily(), first_snapshot, features=features)
    reversed_features = build(
        daily(), first_snapshot, features=tuple(reversed(features))
    )
    assert ordered.context_snapshot_sha256 == reversed_features.context_snapshot_sha256
    assert ordered.canonical_json == reversed_features.canonical_json
    assert first.context_snapshot_sha256 == build(daily(), second_snapshot).context_snapshot_sha256
    manifests = first.context["input_manifest"]
    items = [first.context["quality_gate"]]
    for section in (
        "coverage",
        "gaps",
        "health",
        "sleep",
        "physiology",
        "activities",
        "technical_samples",
        "deterministic_features",
        "current_plan",
        "plan_adherence",
        "prior_artifacts",
        "user_facts",
        "policies",
    ):
        items.extend(first.context[section])
    by_ordinal = {item["ordinal"]: item for item in items}
    assert [row["ordinal"] for row in manifests] == list(range(len(manifests)))
    for manifest in manifests:
        encoded = json.dumps(
            by_ordinal[manifest["ordinal"]]["content"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        assert manifest["input_sha256"] == sha256(encoded).hexdigest()


def test_input_change_changes_snapshot_hash_and_context_is_never_printed(capsys):
    first = build(
        daily(),
        snapshot(views={"v_current_daily_health": (health(1, "2026-07-23", "r1"),)}),
    )
    second = build(
        daily(),
        snapshot(
            views={
                "v_current_daily_health": (
                    health(
                        1,
                        "2026-07-23",
                        "r1",
                        values_json='{"resting_heart_rate":51}',
                    ),
                )
            }
        ),
    )
    assert first.context_snapshot_sha256 != second.context_snapshot_sha256
    assert capsys.readouterr().out == "" and capsys.readouterr().err == ""


def test_cross_subject_noncurrent_and_future_sources_fail_closed():
    with pytest.raises(ContextBuildError, match="cross_subject"):
        build(
            daily(),
            snapshot(
                views={
                    "v_current_daily_health": (
                        health(
                            1,
                            "2026-07-23",
                            "r1",
                            subject_id=2,
                        ),
                    )
                }
            ),
        )
    with pytest.raises(ContextBuildError, match="noncurrent"):
        build(
            daily(),
            snapshot(
                coverage=(
                    {
                        "id": 1,
                        "subject_id": 1,
                        "provider": "garmin",
                        "resource_kind": "steps",
                        "local_date": "2026-07-23",
                        "availability_state": "fetched",
                        "record_count": 1,
                        "source_revision_id": 9,
                        "source_revision_current": 0,
                        "observed_at_utc": "2026-07-23T03:00:00Z",
                    },
                )
            ),
        )
    with pytest.raises(ContextBuildError, match="future_source"):
        build(
            daily(),
            snapshot(
                views={
                    "v_current_daily_health": (
                        health(
                            1,
                            "2026-07-23",
                            "r1",
                            created_at_utc="2026-07-24T01:00:00Z",
                        ),
                    )
                }
            ),
        )


def test_active_fact_scope_and_validity_are_filtered_without_promoting_history():
    facts = (
        {
            "id": 1,
            "subject_id": 1,
            "fact_key": "goal",
            "fact_value_json": '{"distance_km":10}',
            "scope": "long_term",
            "effective_from_utc": "2026-07-01T00:00:00Z",
            "expires_at_utc": None,
            "confidence": 1.0,
        },
        {
            "id": 2,
            "subject_id": 1,
            "fact_key": "expired",
            "fact_value_json": '{"active":false}',
            "scope": "temporary",
            "effective_from_utc": "2026-07-01T00:00:00Z",
            "expires_at_utc": "2026-07-23T00:00:00Z",
            "confidence": 1.0,
        },
        {
            "id": 3,
            "subject_id": 1,
            "fact_key": "future",
            "fact_value_json": '{"active":true}',
            "scope": "temporary",
            "effective_from_utc": "2026-07-25T00:00:00Z",
            "expires_at_utc": None,
            "confidence": 1.0,
        },
        {
            "id": 4,
            "subject_id": 1,
            "fact_key": "message",
            "fact_value_json": '{"only":"mail"}',
            "scope": "message_only",
            "effective_from_utc": "2026-07-01T00:00:00Z",
            "expires_at_utc": None,
            "confidence": 1.0,
        },
    )
    prior = artifact(10, "weekly_summary", "2026-07-07", "2026-07-13")
    value = snapshot(
        views={
            "v_active_user_facts": facts,
            "v_analysis_history_context": (prior,),
        }
    )
    result = build(daily(), value)
    assert [row["content"]["fact_key"] for row in result.context["user_facts"]] == [
        "goal"
    ]
    prior_manifest = next(
        row
        for row in result.context["input_manifest"]
        if row["source_entity_type"] == "analysis_artifact"
    )
    assert (
        prior_manifest["trust_class"]
        == prior_manifest["value_origin"]
        == "prior_model_output"
    )

    invalid = dict(prior, trust_class="provider_fact")
    with pytest.raises(ContextBuildError, match="prior_output_trust"):
        build(
            daily(),
            snapshot(views={"v_analysis_history_context": (invalid,)}),
        )


def test_duplicate_lineage_and_self_reported_hash_or_raw_mail_are_rejected():
    duplicate = health(1, "2026-07-23", "same")
    with pytest.raises(ContextBuildError, match="duplicate_lineage"):
        build(
            daily(),
            snapshot(
                views={"v_current_daily_health": (duplicate, dict(duplicate))}
            ),
        )
    for forbidden in (
        {"input_sha256": "0" * 64},
        {"body_text": "untrusted mail"},
        {"values_json": '{"nested":{"refresh_token":"secret"}}'},
    ):
        row = health(1, "2026-07-23", "r1")
        row.update(forbidden)
        with pytest.raises(ContextBuildError, match="forbidden_field"):
            build(
                daily(),
                snapshot(views={"v_current_daily_health": (row,)}),
            )


def test_canonical_json_rejects_duplicate_noncanonical_and_nonfinite_bypasses():
    with pytest.raises(ContextBuildError, match="duplicate_json_key"):
        parse_canonical_json('{"a":1,"a":2}')
    with pytest.raises(ContextBuildError, match="not_canonical"):
        parse_canonical_json('{"b":2, "a":1}')
    for value in ('{"a":NaN}', '{"a":Infinity}', '{"a":-Infinity}'):
        with pytest.raises(ContextBuildError, match="nonfinite"):
            parse_canonical_json(value)
    assert parse_canonical_json('{"a":1,"b":"测"}') == {"a": 1, "b": "测"}


def test_context_accepts_fixed_six_digit_utc_with_trailing_zeroes():
    value = snapshot(
        coverage=(
            {
                "id": 1,
                "subject_id": 1,
                "provider": "garmin",
                "resource_kind": "steps",
                "local_date": "2026-07-23",
                "availability_state": "fetched",
                "record_count": 1,
                "source_revision_id": 9,
                "source_revision_current": 1,
                "observed_at_utc": "2026-07-23T03:00:00.752070Z",
            },
        )
    )

    assert build(daily(), value).context["coverage"]


def test_context_canonicalizes_valid_foundation_json_but_rejects_duplicate_keys():
    valid = snapshot(
        views={
            "v_current_daily_health": (
                health(1, "2026-07-23", "health-1", values_json='{ "z": 2, "a": 1 }'),
            )
        }
    )
    result = build(daily(), valid)
    assert result.context["health"][0]["content"]["values"] == {"a": 1, "z": 2}

    duplicate = snapshot(
        views={
            "v_current_daily_health": (
                health(1, "2026-07-23", "health-1", values_json='{"a":1,"a":2}'),
            )
        }
    )
    with pytest.raises(ContextBuildError, match="duplicate_json_key"):
        build(daily(), duplicate)


@pytest.mark.parametrize(
    ("foundation_origin", "context_origin"),
    (
        ("sensor_observed", "provider_fact"),
        ("user_entered", "user_asserted"),
        ("profile_setting", "user_asserted"),
    ),
)
def test_foundation_value_origins_map_to_context_trust_classes(
    foundation_origin, context_origin
):
    value = snapshot(
        views={
            "v_current_physiology_records": (
                {
                    "id": 1,
                    "subject_id": 1,
                    "domain": "profile",
                    "record_type": "setting",
                    "effective_at_utc": "2026-07-23T00:00:00Z",
                    "period_start_utc": None,
                    "period_end_utc": None,
                    "local_date": "2026-07-23",
                    "value_origin": foundation_origin,
                    "status_key": None,
                    "status_text": None,
                    "source_revision_id": "profile-1",
                },
            )
        }
    )

    result = build(daily(), value)
    physiology = result.context["physiology"][0]
    manifest = {
        item["ordinal"]: item for item in result.context["input_manifest"]
    }[physiology["ordinal"]]
    assert manifest["value_origin"] == context_origin


def test_canonical_context_parser_rejects_whitespace_and_manifest_tampering():
    result = build(daily(), snapshot())
    assert parse_canonical_context_json(result.canonical_json) == result.context
    with pytest.raises(ContextBuildError, match="not_canonical"):
        parse_canonical_context_json(result.canonical_json + "\n")
    tampered = json.loads(result.canonical_json)
    tampered["input_manifest"][0]["input_sha256"] = "0" * 64
    with pytest.raises(ContextBuildError, match="manifest_hash_invalid"):
        validate_analysis_context(tampered)


def test_technical_samples_are_summary_only_activity_bound_and_hard_bounded():
    value = snapshot(
        views={
            "v_current_activities": (
                activity(1, "2026-07-23", "activity-rev"),
            )
        }
    )
    sample = {
        "activity_id": 1,
        "metric": "heart_rate_bpm",
        "start_utc": "2026-07-23T01:00:00Z",
        "end_utc": "2026-07-23T02:00:00Z",
        "count": 100,
        "minimum": 100,
        "maximum": 180,
        "latest": 150,
        "truncated": True,
    }
    result = build(daily(), value, samples=(sample,))
    content = result.context["technical_samples"][0]["content"]
    assert set(content) == {
        "activity_id",
        "metric",
        "start_utc",
        "end_utc",
        "count",
        "minimum",
        "maximum",
        "latest",
        "truncated",
    }
    with pytest.raises(ContextBuildError, match="sample_lineage"):
        build(daily(), value, samples=(dict(sample, activity_id=2),))
    with pytest.raises(ContextBuildError, match="sample_result"):
        build(daily(), value, samples=(dict(sample, count=True),))
    with pytest.raises(ContextBuildError, match="sample_limit"):
        load_context_source(
            object(),
            daily(),
            tuple(
                TechnicalSampleRequest(
                    1,
                    "heart_rate_bpm",
                    "2026-07-23T01:00:00Z",
                    "2026-07-23T02:00:00Z",
                    100,
                )
                for _ in range(17)
            ),
        )


def test_unprunable_single_byte_over_limit_fails_without_json_truncation():
    initial = build(daily(max_context_bytes=100_000), snapshot())
    # Rebuilding with the exact smaller limit changes only the decimal limit
    # field.  First find that fixed structural size, then miss by one byte.
    sized = build(
        daily(max_context_bytes=initial.utf8_bytes),
        snapshot(),
    )
    with pytest.raises(ContextBuildError, match="unprunable_limit_exceeded"):
        build(
            daily(max_context_bytes=sized.utf8_bytes - 1),
            snapshot(),
        )


def test_utf8_limit_counts_multibyte_bytes_not_python_characters():
    value = snapshot(
        views={
            "v_current_daily_health": (
                health(
                    1,
                    "2026-07-23",
                    "r1",
                    values_json='{"note":"攀岩恢复良好"}',
                ),
            )
        }
    )
    result = build(daily(max_context_bytes=100_000), value)
    assert result.utf8_bytes == len(result.canonical_json.encode("utf-8"))
    assert result.utf8_bytes > len(result.canonical_json)


def pruning_snapshot():
    activities = tuple(
        activity(
            index,
            f"2026-07-{13 + index:02d}",
            f"activity-{index}",
            name=("Older activity display " + "x" * 700),
        )
        for index in range(1, 8)
    )
    segments = tuple(
        {
            "id": 1000 + index,
            "subject_id": 1,
            "activity_id": activities[index % len(activities)]["id"],
            "segment_type": "lap",
            "segment_index": index,
            "start_time_utc": activities[index % len(activities)][
                "start_time_utc"
            ],
            "end_time_utc": activities[index % len(activities)]["end_time_utc"],
            "duration_seconds": 60,
            "distance_m": 200,
            "source_revision_id": activities[index % len(activities)][
                "primary_revision_id"
            ],
        }
        for index in range(24)
    )
    daily_history = tuple(
        artifact(
            100 + index,
            "daily_summary",
            f"2026-07-{7 + index:02d}",
            f"2026-07-{7 + index:02d}",
        )
        for index in range(7)
    )
    prior_summary = artifact(
        200, "weekly_summary", "2026-07-07", "2026-07-13"
    )
    prior_plan = artifact(
        201, "weekly_training_plan", "2026-07-14", "2026-07-20"
    )
    plan = {
        "id": 50,
        "subject_id": 1,
        "analysis_artifact_id": 201,
        "plan_start_local_date": "2026-07-14",
        "plan_end_local_date": "2026-07-20",
        "timezone": "Asia/Singapore",
        "status": "active",
        "created_at_utc": "2026-07-13T00:00:00Z",
    }
    plan_items = tuple(
        {
            "id": 500 + index,
            "subject_id": 1,
            "training_plan_id": 50,
            "item_index": index,
            "local_date": f"2026-07-{14 + index:02d}",
            "activity_kind": "running" if index % 2 else "rest",
            "prescription_json": '{"kind":"duration_only"}',
            "rationale_text": "prior plan output",
        }
        for index in range(7)
    )
    return snapshot(
        views={
            "v_current_activities": activities,
            "v_activity_segments": segments,
            "v_current_physiology_records": (
                {
                    "id": 900,
                    "subject_id": 1,
                    "domain": "training",
                    "record_type": "training_status",
                    "effective_at_utc": "2026-07-20T00:00:00Z",
                    "period_start_utc": "2026-07-20T00:00:00Z",
                    "period_end_utc": "2026-07-20T01:00:00Z",
                    "local_date": "2026-07-20",
                    "value_origin": "provider_derived",
                    "status_key": "productive",
                    "status_text": "provider display " + "显" * 3000,
                    "source_revision_id": "physiology-display",
                },
            ),
            "v_current_training_plans": (plan,),
            "v_training_plan_items": plan_items,
            "v_analysis_history_context": (
                *daily_history,
                prior_summary,
                prior_plan,
            ),
        },
        gaps=(
            {
                "resource_kind": "sleep",
                "logical_object_key": "2026-07-19",
                "window_start_local_date": "2026-07-19",
                "window_end_local_date": "2026-07-19",
                "stage": "fetch",
                "reason_code": "deferred",
                "status": "deferred",
                "priority": 1,
                "next_retry_at_utc": "2026-07-24T01:00:00Z",
            },
        ),
    )


def pruning_features():
    return tuple(
        {
            "key": f"activity.{index}",
            "value": index,
            "value_origin": "derived_statistic",
            "algorithm_version": "2",
            "input_revision_ids": [f"activity-{index}"],
        }
        for index in range(1, 8)
    )


def test_pruning_is_deterministic_ordered_and_records_recomputable_omissions():
    value = pruning_snapshot()
    features = pruning_features()
    full = build(
        weekly(max_context_bytes=1_000_000),
        value,
        features=features,
    )
    observed = {}
    for ratio in (0.95, 0.85, 0.75, 0.70):
        result = build(
            weekly(max_context_bytes=int(full.utf8_bytes * ratio)),
            value,
            features=features,
        )
        observed[
            tuple(result.context["context_limits"]["applied_pruning_stages"])
        ] = result
    assert set(observed) == {
        (1,),
        (1, 2),
        (1, 2, 3),
        (1, 2, 3, 4),
    }
    result = observed[(1, 2, 3, 4)]
    omissions = result.context["context_limits"]["omissions"]
    assert [row["stage"] for row in omissions] == sorted(
        row["stage"] for row in omissions
    )
    assert len(omissions) == result.context["context_limits"]["omission_count"]
    for omission in omissions:
        assert omission["reason_code"] == (
            "optional_activity_extras",
            "old_activity_details",
            "old_daily_history",
            "optional_provider_display",
        )[omission["stage"] - 1]
        assert len(omission["before_sha256"]) == 64
        if omission["stage"] == 4:
            manifest = next(
                row
                for row in result.context["input_manifest"]
                if row["input_role"] == omission["input_role"]
                and row["source_entity_id"] == omission["source_entity_id"]
                and row["source_revision_id"] == omission["source_revision_id"]
            )
            assert manifest["input_sha256"] == omission["after_sha256"]
    reversed_value = pruning_snapshot()
    reversed_value.views["v_activity_segments"] = tuple(
        reversed(reversed_value.views["v_activity_segments"])
    )
    reversed_result = build(
        weekly(max_context_bytes=result.context["context_limits"]["max_utf8_bytes"]),
        reversed_value,
        features=tuple(reversed(features)),
    )
    assert result.context_snapshot_sha256 == reversed_result.context_snapshot_sha256
    assert [
        (
            item["stage"],
            item["input_role"],
            item["source_entity_id"],
            item["source_revision_id"],
        )
        for item in omissions
    ] == [
        (
            item["stage"],
            item["input_role"],
            item["source_entity_id"],
            item["source_revision_id"],
        )
        for item in reversed_result.context["context_limits"]["omissions"]
    ]


def test_pruning_never_removes_quality_gaps_current_plan_prior_week_or_policies():
    value = pruning_snapshot()
    features = pruning_features()
    full = build(weekly(max_context_bytes=1_000_000), value, features=features)
    chosen = build(
        weekly(max_context_bytes=int(full.utf8_bytes * 0.70)),
        value,
        features=features,
    )
    assert chosen.context["quality_gate"]["content"]["state"] == "ready"
    assert chosen.context["gaps"]
    assert chosen.context["current_plan"]
    prior_kinds = {
        item["content"]["artifact_kind"]
        for item in chosen.context["prior_artifacts"]
    }
    current_plan_kinds = {
        item["content"].get("artifact_kind")
        for item in chosen.context["current_plan"]
    }
    assert "weekly_summary" in prior_kinds
    assert "weekly_training_plan" in current_plan_kinds
    policy_names = {item["content"]["name"] for item in chosen.context["policies"]}
    assert {
        "context_policy",
        "analysis_input_schema",
        "quality_gate_policy",
        "feature_library",
        "feature_conflict_policy",
        "training_safety_policy",
        "harness_bundle",
        "analysis_output_schema",
    } == policy_names


def test_feature_lineage_must_be_unique_current_snapshot_evidence():
    value = snapshot(
        views={
            "v_current_daily_health": (
                health(1, "2026-07-23", "health-rev"),
            )
        }
    )
    duplicate = {
        "key": "feature",
        "value": 1,
        "value_origin": "derived_statistic",
        "algorithm_version": "2",
        "input_revision_ids": ["health-rev", "health-rev"],
    }
    with pytest.raises(ContextBuildError, match="feature_lineage"):
        build(daily(), value, features=(duplicate,))
    stale = dict(duplicate, input_revision_ids=["missing-revision"])
    with pytest.raises(ContextBuildError, match="feature_lineage"):
        build(daily(), value, features=(stale,))


def test_conflict_unknown_and_prior_output_origins_are_preserved_not_promoted():
    value = snapshot(
        views={
            "v_current_daily_health": (
                health(1, "2026-07-23", "health-rev"),
            )
        }
    )
    records = tuple(
        {
            "key": f"conflict.{origin}",
            "value": None,
            "warning": "conflict_unresolved",
            "value_origin": origin,
            "algorithm_version": "2",
            "input_revision_ids": ["health-rev"],
        }
        for origin in ("unknown", "prior_model_output")
    )
    result = build(daily(), value, features=records)
    manifest_by_ordinal = {
        row["ordinal"]: row for row in result.context["input_manifest"]
    }
    observed = {
        item["content"]["value_origin"]: (
            manifest_by_ordinal[item["ordinal"]]["trust_class"],
            manifest_by_ordinal[item["ordinal"]]["value_origin"],
        )
        for item in result.context["deterministic_features"]
    }
    assert observed == {
        "unknown": ("unknown", "unknown"),
        "prior_model_output": ("prior_model_output", "prior_model_output"),
    }
