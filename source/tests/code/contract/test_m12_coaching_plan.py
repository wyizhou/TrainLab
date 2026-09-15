from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
f = importlib.import_module("m12_coaching_factory")
contexts = importlib.import_module("test_m12_weekly_context")


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import stage_context

    root, _, _ = contexts.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")
    return root, stage_context.freeze(
        root, contexts.fixture.END, "plan", validate_history=contexts.valid_report
    )


def test_seven_days_host_dates_rest_and_unknown_baseline(inputs):
    from skills._shared.fit_weekly import coaching_plan

    root, payload = inputs
    result = coaching_plan.project(f.plan(), payload, root=root)
    assert [d["date"] for d in result["days"]] == payload["next_plan_dates"]
    assert result["days"][1]["workout"] is None
    assert result["progression"]["distance_change"] == "unknown"
    assert result["progression"]["intensity_change"] == "unknown"


@pytest.mark.parametrize(
    "mutation",
    [
        "six",
        "date",
        "rest_workout",
        "dose",
        "repeat",
        "bpm",
        "zones",
        "four_hard",
        "two_day_gap",
    ],
)
def test_invalid_course_rejected(inputs, mutation):
    from skills._shared.fit_weekly import coaching_plan

    root, payload = inputs
    p = f.plan()
    if mutation == "six":
        p["days"].pop()
    if mutation == "date":
        p["days"][0]["date"] = "2000-01-01"
    if mutation == "rest_workout":
        p["days"][1]["workout"] = f.workout()
    if mutation == "dose":
        p["days"][0]["workout"]["dose"]["value"] += 1
    if mutation == "repeat":
        p["days"][0]["workout"]["steps"][0]["repeat"] = 2
    if mutation == "bpm":
        p["days"][0]["workout"]["technical_notes"] = "保持140 bpm"
    if mutation == "zones":
        p["days"][0]["workout"]["technical_notes"] = "心率保持二区"
    if mutation in ("four_hard", "two_day_gap"):
        for i in (0, 2, 4, 6) if mutation == "four_hard" else (0, 2):
            p["days"][i] = {"kind": "run", "workout": f.workout("long")}
    with pytest.raises(ValueError):
        coaching_plan.project(p, payload, root=root)


def test_three_hard_spacing_three_and_repeat_groups(inputs):
    from skills._shared.fit_weekly import coaching_plan

    root, payload = inputs
    p = f.plan()
    for i in (0, 3, 6):
        p["days"][i]["workout"] = f.workout("long")
    w = p["days"][0]["workout"]
    w["steps"][0]["repeat"] = 2
    w["steps"][0]["steps"][0]["value"] = 600
    assert coaching_plan.project(p, payload, root=root)["hard_load_count"] == 3


def test_no_unsupported_sos(inputs):
    from skills._shared.fit_weekly import coaching_plan

    root, payload = inputs
    p = f.plan()
    p["days"][0]["workout"] = f.workout("intervals")
    with pytest.raises(ValueError, match="coaching_sos_evidence_missing"):
        coaching_plan.project(p, payload, root=root)


def test_double_progression_rejected(inputs):
    from skills._shared.fit_weekly import coaching_plan, model_job

    root, payload = inputs
    before = f.plan()
    for day in before["days"]:
        if day["workout"]:
            day["workout"] = f.workout(unit="meters", value=1000)
    historical = {"analysis": {}, "plan": before}
    payload["running_history"] = [
        {
            "period_end_utc": contexts.end_before(1),
            "running": historical,
            "running_sha256": model_job.sha(historical),
        }
    ]
    after = f.clone(before)
    for day in after["days"]:
        if day["workout"]:
            day["workout"] = f.workout("long", unit="meters", value=2000)
    with pytest.raises(ValueError, match="coaching_double_progression"):
        coaching_plan.project(after, payload, root=root)


def test_empty_running_is_disclosed_not_fabricated(inputs):
    from skills._shared.fit_weekly import coaching_plan

    root, payload = inputs
    payload["running_activities"] = []
    assert (
        coaching_plan.project(f.plan(), payload, root=root)["progression"]["baseline"]
        is None
    )


def test_first_sos_can_use_running_evidence_without_existing_sos_label(inputs):
    from skills._shared.fit_weekly import coaching_plan

    root, payload = inputs
    p = f.plan()
    activity = payload["running_activities"][0]
    assert activity["sessions"][0]["running_kind"] == "unknown"
    p["rationale"] = f.claim(
        "按所引跑步表现尝试，适用性仍有限。", [f.reference(activity)]
    )
    p["days"][0]["workout"] = f.workout("tempo")
    assert coaching_plan.project(p, payload, root=root)["hard_load_count"] == 1


def test_negative_safety_instructions_are_not_prescriptions(inputs):
    from skills._shared.fit_weekly import coaching_plan

    root, payload = inputs
    p = f.plan()
    p["days"][0]["workout"]["stop_conditions"] = ["心率异常并感到不适时停止。"]
    p["days"][0]["workout"]["technical_notes"] = "不设定目标心率。不推算阈值。不补课。"
    coaching_plan.project(p, payload, root=root)


@pytest.mark.parametrize("field", ["hard_count", "peak_rpe", "hard_seconds"])
def test_known_intensity_component_increase_never_hidden(inputs, field):
    from skills._shared.fit_weekly import coaching_plan, model_job

    root, payload = inputs
    before = f.plan()
    after = f.clone(before)
    if field == "hard_count":
        after["days"][0]["workout"] = f.workout("long")
    if field == "peak_rpe":
        after["days"][0]["workout"]["steps"][0]["steps"][0]["rpe"] = 4
    if field == "hard_seconds":
        before["days"][0]["workout"] = f.workout("long")
        after["days"][0]["workout"] = f.workout("long", value=1500)
    running = {"analysis": {}, "plan": before}
    payload["running_history"] = [
        {
            "period_end_utc": payload["period_start_utc"],
            "running": running,
            "running_sha256": model_job.sha(running),
        }
    ]
    projected = coaching_plan.project(after, payload, root=root)
    assert projected["progression"]["dimensions"][field]["change"] == "increased"
    assert projected["progression"]["intensity_change"] == "increased"


def test_incompatible_units_remain_unknown(inputs):
    from skills._shared.fit_weekly import coaching_plan, model_job

    root, payload = inputs
    before = f.plan()
    before["days"][0]["workout"] = f.workout("long", unit="meters", value=1000)
    after = f.clone(before)
    after["days"][0]["workout"] = f.workout("long", unit="seconds", value=1000)
    running = {"analysis": {}, "plan": before}
    payload["running_history"] = [
        {
            "period_end_utc": payload["period_start_utc"],
            "running": running,
            "running_sha256": model_job.sha(running),
        }
    ]
    assert (
        coaching_plan.project(after, payload, root=root)["progression"][
            "intensity_change"
        ]
        == "unknown"
    )


@pytest.mark.parametrize(
    "text",
    [
        "不计算心率阈值，但本课目标为140 bpm。",
        "不要补课，但明天补跑。",
        "不设定心率阈值并保持140 bpm。",
    ],
)
def test_prohibition_cannot_hide_later_prescription(inputs, text):
    from skills._shared.fit_weekly import coaching_plan

    root, payload = inputs
    p = f.plan()
    p["days"][0]["workout"]["technical_notes"] = text
    with pytest.raises(ValueError):
        coaching_plan.project(p, payload, root=root)


@pytest.mark.parametrize(
    "text,error",
    [
        ("保持140 bpm", "coaching_heart_prescription"),
        ("明天补跑", "coaching_dynamic_plan"),
        ("排除健康风险", "coaching_health_clearance"),
    ],
)
def test_progression_limitations_reject_obvious_violations(inputs, text, error):
    from skills._shared.fit_weekly import coaching_plan

    root, payload = inputs
    p = f.plan()
    p["progression_limitations"] = [text]
    with pytest.raises(ValueError, match=error):
        coaching_plan.project(p, payload, root=root)


@pytest.mark.parametrize(
    "text",
    [
        "不设定目标心率。不推算阈值。不补课。",
        "心率异常时停止。",
        "运动表现不能证明没有健康风险。",
    ],
)
def test_progression_limitations_preserve_prohibitions_and_stops(inputs, text):
    from skills._shared.fit_weekly import coaching_plan

    root, payload = inputs
    p = f.plan()
    p["progression_limitations"] = [text]
    result = coaching_plan.project(p, payload, root=root)
    assert result["progression_limitations"] == [text]


def test_plan_rationale_preserves_sourced_historical_heart_fact(inputs):
    from skills._shared.fit_weekly import coaching_plan

    root, payload = inputs
    p = f.plan()
    activity = payload["running_activities"][0]
    ref = f.reference(activity, ["summary", "metrics", "heart_rate_bpm", "mean"])
    p["rationale"] = f.claim(f"设备记录的历史平均心率为{ref['value']} bpm。", [ref])
    assert coaching_plan.project(p, payload, root=root)["rationale"] == p["rationale"]
