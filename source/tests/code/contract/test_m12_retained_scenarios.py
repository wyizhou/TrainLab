from __future__ import annotations

import importlib
import io
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from skills._shared.fit_weekly import (
    coaching_contract,
    coaching_plan,
    coaching_summary,
    model_job,
    report_markdown,
    report_pdf,
    report_revisions,
    stage_context,
    weekly_context,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
f = importlib.import_module("m12_coaching_factory")
reports = importlib.import_module("m12_report_factory")
contexts = importlib.import_module("test_m12_weekly_context")


@pytest.fixture
def stage_inputs(tmp_path, monkeypatch):
    root, _, _ = contexts.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")
    materials = weekly_context.freeze(
        root, contexts.fixture.END, validate_report=contexts.valid_report
    )
    plan = stage_context.project(materials, "plan")
    summary = stage_context.project(
        materials,
        "summary",
        {
            "period_end_utc": contexts.fixture.END,
            "request_sha256": "a" * 64,
            "capture_sha256": "b" * 64,
            "result_sha256": "c" * 64,
            "plan": f.plan(),
        },
    )
    return root, plan, summary


@pytest.mark.parametrize(
    "text",
    [
        "建议 Zone 2",
        "目标心率 150 BPM",
        "按 maximum heart rate 的80%执行",
        "使用 Z3 完成主训练",
        "建议在Z2区完成",
        "把BPM控制稳定",
        "按80% HRmax执行",
        "本周采用Zone训练并据此控制强度。",
        "建议保持心率分区训练。",
        "建议按心率上下限控制强度。",
        "建议按心率范围控制强度。",
        "建议采用心率区带训练。",
        "建议依据心率最大控制强度。",
        "建议依据心率阈值控制强度。",
        "建议按Z-2完成主训练。",
        "目标写为BPM150。",
        "按HR-max的80%执行。",
        "使用target HR控制强度。",
        "heart_rate_zone",
        "target_bpm",
        "max_heart_rate",
        "threshold_bpm",
        "Z2",
        "150 BPM",
        "maximum heart rate at 80%",
        "目标心率150",
        "历史平均心率142 bpm，建议下周按目标心率150执行。",
    ],
)
def test_retained_heart_prescription_variants_never_enter_a_course(stage_inputs, text):
    root, plan_input, _ = stage_inputs
    plan = f.plan()
    plan["days"][0]["workout"]["technical_notes"] = text
    with pytest.raises(ValueError, match="coaching_heart_prescription"):
        coaching_plan.project(plan, plan_input, root=root)


@pytest.mark.parametrize(
    "text",
    [
        "建议 Zone 2",
        "按 maximum heart rate 的80%执行",
        "使用 Z3 完成主训练",
        "建议在Z2区完成",
        "把BPM控制稳定",
        "按80% HRmax执行",
        "本周采用Zone训练并据此控制强度。",
        "建议保持心率分区训练。",
        "建议按心率上下限控制强度。",
        "建议按心率范围控制强度。",
        "建议采用心率区带训练。",
        "建议依据心率最大控制强度。",
        "建议依据心率阈值控制强度。",
        "建议按Z-2完成主训练。",
        "目标写为BPM150。",
        "按HR-max的80%执行。",
        "使用target HR控制强度。",
    ],
)
def test_retained_summary_cannot_hide_future_heart_prescriptions(stage_inputs, text):
    root, _, summary_input = stage_inputs
    summary = f.summary(summary_input)
    summary["core_conclusions"] = [f.claim(text)]
    with pytest.raises(ValueError, match="coaching_heart_prescription"):
        coaching_summary.validate(summary, summary_input, root=root)


@pytest.mark.parametrize(
    "field", ["dose", "steps", "technical_notes", "stop_conditions"]
)
def test_retained_nonrest_course_requires_complete_actionable_details(
    stage_inputs, field
):
    root, plan_input, _ = stage_inputs
    plan = f.plan()
    del plan["days"][0]["workout"][field]
    with pytest.raises(ValueError, match="coaching_plan_schema_invalid"):
        coaching_plan.project(plan, plan_input, root=root)


@pytest.mark.parametrize(
    "field",
    [
        "date",
        "effective_course",
        "original_course",
        "downgrade_rule",
        "adjustment",
        "start_gate",
        "alternative_course",
    ],
)
def test_retained_fixed_plan_rejects_dynamic_or_model_owned_date_fields(
    stage_inputs, field
):
    root, plan_input, _ = stage_inputs
    plan = f.plan()
    plan["days"][0][field] = "unapproved"
    with pytest.raises(ValueError, match="coaching_plan_schema_invalid"):
        coaching_plan.project(plan, plan_input, root=root)


def test_retained_observed_heart_fact_is_valid_only_with_exact_activity_evidence(
    stage_inputs,
):
    root, plan_input, summary_input = stage_inputs
    activity = plan_input["running_activities"][0]
    ref = f.reference(activity, ["summary", "metrics", "heart_rate_bpm", "mean"])
    summary = f.summary(summary_input)
    summary["core_conclusions"] = [
        f.claim(f"设备记录的历史平均心率为{ref['value']} bpm。", [ref])
    ]
    coaching_summary.validate(summary, summary_input, root=root)
    changed = deepcopy(summary)
    changed["core_conclusions"][0]["evidence"][0]["value"] += 1
    with pytest.raises(ValueError, match="coaching_evidence_value_mismatch"):
        coaching_summary.validate(changed, summary_input, root=root)
    plan = f.plan()
    plan["days"][0]["workout"]["technical_notes"] = summary["core_conclusions"][0][
        "text"
    ]
    with pytest.raises(ValueError, match="coaching_heart_prescription"):
        coaching_plan.project(plan, plan_input, root=root)


@pytest.mark.parametrize(
    "suffix",
    [
        "，作为今天训练必须达到的目标。",
        "，今天训练达到这个数值即可。",
        "，这是今天训练应达到的数值。",
        "，训练时保持这个数值。",
        "；训练必须达到这个数值。",
        ";训练必须达到这个数值。",
    ],
)
@pytest.mark.parametrize("stage", ["summary", "plan"])
def test_retained_observed_heart_fact_cannot_become_a_referenced_training_target(
    stage_inputs, suffix, stage
):
    root, plan_input, summary_input = stage_inputs
    activity = plan_input["running_activities"][0]
    ref = f.reference(activity, ["summary", "metrics", "heart_rate_bpm", "mean"])
    assert ref["source"] == "current" and ref["value"] == 121.0
    claim = f.claim(f"本期设备记录活动平均心率{ref['value']} bpm" + suffix, [ref])
    if stage == "summary":
        summary = f.summary(summary_input)
        summary["core_conclusions"] = [claim]
        with pytest.raises(ValueError, match="^coaching_heart_prescription$"):
            coaching_summary.validate(summary, summary_input, root=root)
    else:
        plan = f.plan()
        plan["rationale"] = claim
        with pytest.raises(ValueError, match="^coaching_heart_prescription$"):
            coaching_plan.project(plan, plan_input, root=root)


@pytest.mark.parametrize(
    "suffix",
    [
        "。",
        "，这个数值只是历史记录。",
        "，今天训练保持RPE 3。",
        "，训练时保持动作稳定。",
        "，不要达到这个数值。",
        "，不作为今天训练必须达到的目标。",
        "，这不是今天训练应达到的数值。",
        "，不应保持这个数值。",
        "，若达到这个数值并感到不适时停止。",
        "，若达到这个数值时停止，但保持动作稳定。",
        "，热身10分钟，训练时保持这个数值。",
        "，训练使用RPE 3，保持这个数值。",
        "，这个数值仅作历史对照，先热身，随后保持RPE 3。",
        "。训练使用RPE 3，保持这个数值。",
        "\n训练使用RPE 3，保持这个数值。",
    ],
)
@pytest.mark.parametrize("stage", ["summary", "plan"])
def test_retained_heart_reference_preserves_facts_denials_stops_and_rpe(
    stage_inputs, suffix, stage
):
    root, plan_input, summary_input = stage_inputs
    activity = plan_input["running_activities"][0]
    ref = f.reference(activity, ["summary", "metrics", "heart_rate_bpm", "mean"])
    claim = f.claim(f"本期设备记录活动平均心率{ref['value']} bpm" + suffix, [ref])
    if stage == "summary":
        summary = f.summary(summary_input)
        summary["core_conclusions"] = [claim]
        before = model_job.clone(summary_input["fixed_plan"])
        coaching_summary.validate(summary, summary_input, root=root)
        assert summary_input["fixed_plan"] == before
    else:
        plan = f.plan()
        plan["rationale"] = claim
        assert coaching_plan.project(plan, plan_input, root=root)["rationale"] == claim


@pytest.mark.parametrize(
    "suffix",
    [
        "，不需要达到这个数值，但训练时保持这个数值。",
        "，不推算阈值，训练必须达到这个数值。",
        "，若达到这个数值时停止，但训练时保持这个数值。",
        "，不要达到这个数值，随后训练时保持这个数值。",
        "，训练时保持这个数值并在感到不适时停止。",
    ],
)
def test_retained_heart_reference_denial_or_stop_cannot_hide_later_target(
    stage_inputs, suffix
):
    root, plan_input, summary_input = stage_inputs
    activity = plan_input["running_activities"][0]
    ref = f.reference(activity, ["summary", "metrics", "heart_rate_bpm", "mean"])
    summary = f.summary(summary_input)
    summary["core_conclusions"] = [
        f.claim(f"本期设备记录活动平均心率{ref['value']} bpm" + suffix, [ref])
    ]
    with pytest.raises(ValueError, match="^coaching_heart_prescription$"):
        coaching_summary.validate(summary, summary_input, root=root)


@pytest.mark.parametrize("target", ["summary", "plan"])
def test_retained_editorial_heart_reference_rejects_target_without_saving(
    tmp_path, monkeypatch, target
):
    root, evidence, calls = reports.setup(tmp_path, monkeypatch)
    base = report_revisions.create(root, reports.END)
    activity = next(
        a for a in evidence["activities"] if a["sessions"][0]["sport"] == "running"
    )
    ref = f.reference(activity, ["summary", "metrics", "heart_rate_bpm", "mean"])
    claim = f.claim(f"本期设备记录活动平均心率{ref['value']} bpm。", [ref])
    content = deepcopy(base[target + "_content"])
    if target == "summary":
        content["core_conclusions"] = [claim]
    else:
        content["rationale"] = claim
    accepted = report_revisions.edit(
        root,
        reports.END,
        base_revision_id="ai",
        base_revision_sha256=model_job.sha(base),
        revision_id="heart-fact",
        target=target,
        content=content,
    )
    other = "plan_content" if target == "summary" else "summary_content"
    assert accepted[other] == base[other]
    before = (root / "trainlab-fit.db").read_bytes()
    claim["text"] = claim["text"][:-1] + "，训练时保持这个数值。"
    with pytest.raises(ValueError, match="^coaching_heart_prescription$"):
        report_revisions.edit(
            root,
            reports.END,
            base_revision_id="heart-fact",
            base_revision_sha256=model_job.sha(accepted),
            revision_id="heart-target",
            target=target,
            content=content,
        )
    assert (root / "trainlab-fit.db").read_bytes() == before
    assert [c.calls for c in calls] == [1, 1]


def test_retained_advice_cannot_claim_completed_adjustment_without_evidence(
    stage_inputs,
):
    root, _, summary_input = stage_inputs
    summary = f.summary(summary_input)
    summary["core_conclusions"] = [f.claim("本周已执行降级，训练负荷比原计划减少。")]
    with pytest.raises(ValueError, match="coaching_completion_evidence_missing"):
        coaching_summary.validate(summary, summary_input, root=root)
    activity = summary_input["current_week"]["activities"][0]
    summary["core_conclusions"] = [
        f.claim("本周记录并完成这次活动。", [f.reference(activity)])
    ]
    coaching_summary.validate(summary, summary_input, root=root)


@pytest.mark.parametrize("separator", ["至", "-", "~", "～", "–", "—"])
@pytest.mark.parametrize(
    "label,metric",
    [("活动平均心率", "mean"), ("活动最高心率", "max"), ("活动最大心率", "max")],
)
def test_retained_observed_activity_range_separators_keep_source_and_no_prescription(
    stage_inputs, separator, label, metric
):
    root, plan_input, summary_input = stage_inputs
    activity = plan_input["running_activities"][0]
    ref = f.reference(activity, ["summary", "metrics", "heart_rate_bpm", metric])
    text = f"本期设备历史{label}{ref['value']}{separator}{ref['value']} bpm。历史训练使用RPE。"
    summary = f.summary(summary_input)
    summary["core_conclusions"] = [f.claim(text, [ref])]
    coaching_summary.validate(summary, summary_input, root=root)
    plan = f.plan()
    plan["days"][0]["workout"]["technical_notes"] = text
    with pytest.raises(ValueError, match="coaching_heart_prescription"):
        coaching_plan.project(plan, plan_input, root=root)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "damaged",
        "noncanonical",
        "extra_field",
        "days",
        "host_field",
    ],
)
def test_retained_prompt_semantics_cannot_drift_from_current_schema(
    tmp_path, monkeypatch, mutation
):
    value = coaching_contract.prompt("plan")
    if mutation == "missing":
        changed = "No schema"
    elif mutation == "duplicate":
        changed = value + value
    elif mutation == "damaged":
        changed = value[:-1]
    elif mutation == "noncanonical":
        changed = value + "\n"
    else:
        schema = coaching_contract.schema("plan")
        if mutation == "extra_field":
            schema["invented"] = True
        elif mutation == "days":
            schema["properties"]["days"]["minItems"] = 6
        else:
            schema["properties"]["date"] = {"type": "string"}
        changed = (
            value.split("BUSINESS_SCHEMA\n")[0]
            + "BUSINESS_SCHEMA\n"
            + json.dumps(schema)
        )
    monkeypatch.setattr(coaching_contract, "PROMPTS", tmp_path)
    (tmp_path / "fit-running-plan-v1.txt").write_text(changed)
    with pytest.raises(ValueError, match="coaching_prompt_drift"):
        coaching_contract.check("plan")


def test_retained_renderer_treats_untrusted_markup_as_literal_text(
    tmp_path, monkeypatch
):
    from pypdf import PdfReader

    root, _, calls = reports.setup(tmp_path, monkeypatch)
    revision = report_revisions.create(root, reports.END)
    view = report_revisions.view(root, reports.END, "ai", model_job.sha(revision))
    text = "<script>alert(1)</script> [报告](javascript:alert(2)) <img src=x onerror=alert(3)>"
    view["core_conclusions"][0]["text"] = text
    markdown = report_markdown.render(view).decode()
    assert "<script>" not in markdown and "<img " not in markdown
    assert "&lt;script&gt;" in markdown and "\\[报告\\]" in markdown
    reader = PdfReader(io.BytesIO(report_pdf.render(view)))
    assert "alert(1)" in "".join(page.extract_text() for page in reader.pages)
    assert all(not page.get("/Annots") for page in reader.pages)
    assert [c.calls for c in calls] == [1, 1]
