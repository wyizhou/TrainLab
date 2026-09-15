from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
f = importlib.import_module("m12_coaching_factory")
contexts = importlib.import_module("test_m12_weekly_context")


@pytest.fixture
def evidence_input(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import stage_context, weekly_context

    root, _, _ = contexts.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")
    materials = weekly_context.freeze(
        root, contexts.fixture.END, validate_report=contexts.valid_report
    )
    return root, stage_context.project(
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


def test_exact_session_value_and_nonrunning_isolation(evidence_input):
    from skills._shared.fit_weekly import coaching_evidence

    root, payload = evidence_input
    running = next(
        a
        for a in payload["current_week"]["activities"]
        if a["sessions"][0]["sport"] == "running"
    )
    nonrun = next(
        a
        for a in payload["current_week"]["activities"]
        if a["sessions"][0]["sport"] != "running"
    )
    good = f.claim("记录距离。", [f.reference(running)])
    coaching_evidence.validate_claim(good, payload, root=root, running_only=True)
    for key, value in (
        ("fit_sha256", "0" * 64),
        ("session_ordinal", 9),
        ("value", -1),
        ("activity_ref", "999"),
    ):
        bad = f.clone(good)
        bad["evidence"][0][key] = value
        with pytest.raises(ValueError):
            coaching_evidence.validate_claim(bad, payload, root=root, running_only=True)
    with pytest.raises(ValueError):
        coaching_evidence.validate_claim(
            f.claim("骑行记录。", [f.reference(nonrun)]),
            payload,
            root=root,
            running_only=True,
        )


def test_summary_sections_technique_limit_and_no_second_plan(evidence_input):
    from skills._shared.fit_weekly import coaching_summary

    root, payload = evidence_input
    good = f.summary(payload)
    coaching_summary.validate(good, payload, root=root)
    for mutation in (
        "omit_other",
        "four_techniques",
        "second_plan",
        "health_clearance",
    ):
        bad = f.clone(good)
        if mutation == "omit_other":
            bad["other_sports"] = []
        if mutation == "four_techniques":
            bad["running_analysis"]["technique"] = [f.claim()] * 4
        if mutation == "second_plan":
            bad["plan"] = f.plan()
        if mutation == "health_clearance":
            bad["safety"]["performance_is_not_health_clearance"] = False
        with pytest.raises(ValueError):
            coaching_summary.validate(bad, payload, root=root)


def test_detail_evidence_revalidation_never_reads_fit(evidence_input, monkeypatch):
    from skills._shared.fit_weekly import (
        coaching_evidence,
        fit_detail,
        storage,
    )

    root, payload = evidence_input
    with storage.open_store(root) as db:
        scope = fit_detail.get(db, "detail:" + contexts.fixture.END + ":scope")[0]
    a = next(
        a
        for a in payload["current_week"]["activities"]
        if a["sessions"][0]["sport"] == "running"
    )
    host = fit_detail.DetailHost(root, contexts.fixture.END, scope, stage="plan")
    result = host.read(
        {
            "activity_ref": a["activity_ref"],
            "view": "summary",
            "start_offset_seconds": 0,
            "end_offset_seconds": 60,
            "resolution_seconds": 5,
        }
    )
    ref = f.reference(a)
    ref.update(
        source="detail",
        request_sha256=result["request_sha256"],
        path=["blocks", 0, "statistics", "distance_m"],
        value=result["blocks"][0]["statistics"]["distance_m"],
    )

    def forbidden(*_):
        raise AssertionError("must only read saved successful evidence")

    monkeypatch.setattr(fit_detail.DetailHost, "read", forbidden)
    monkeypatch.setattr(fit_detail, "fit_bytes", forbidden)
    coaching_evidence.validate_claim(
        f.claim("细读距离。", [ref]), payload, root=root, running_only=True
    )
    ref["request_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        coaching_evidence.validate_claim(
            f.claim("细读。", [ref]), payload, root=root, running_only=True
        )


def test_missing_metric_and_unknown_claim_cannot_fabricate_sources(evidence_input):
    from skills._shared.fit_weekly import coaching_evidence

    root, payload = evidence_input
    activity = payload["current_week"]["activities"][0]
    ref = f.reference(activity, ["provider_summary", "distance_m"], 1)
    assert activity["sessions"][0]["provider_summary"]["distance_m"] is None
    with pytest.raises(ValueError, match="coaching_evidence_unavailable"):
        coaching_evidence.validate_claim(
            f.claim("虚构距离。", [ref]), payload, root=root
        )
    unknown = f.claim()
    unknown["evidence"] = [f.reference(activity)]
    with pytest.raises(ValueError):
        coaching_evidence.validate_claim(unknown, payload, root=root)


def test_history_reference_in_running_analysis_cannot_reach_mixed_report(
    evidence_input,
):
    from skills._shared.fit_weekly import coaching_evidence, model_job

    root, payload = evidence_input
    report = {
        "running": {"analysis": {"observation": "跑步资料。"}, "plan": f.plan()},
        "summary": {"other_sport": "骑行资料。"},
    }
    payload["history_reports"] = [
        {
            "schema_version": "fit_weekly_history_v2",
            "period_end_utc": payload["period_start_utc"],
            "report": report,
            "report_sha256": model_job.sha(report),
        }
    ]
    ref = {
        "source": "history",
        "activity_ref": None,
        "fit_sha256": None,
        "session_ordinal": None,
        "period_end_utc": payload["period_start_utc"],
        "request_sha256": None,
        "path": ["analysis", "observation"],
        "value": "跑步资料。",
    }
    coaching_evidence.validate_claim(
        f.claim("跑步。", [ref]), payload, root=root, running_only=True
    )
    ref.update(path=["summary", "other_sport"], value="骑行资料。")
    with pytest.raises(ValueError):
        coaching_evidence.validate_claim(
            f.claim("混合。", [ref]), payload, root=root, running_only=True
        )
    ref["period_end_utc"] = payload["period_end_utc"]
    with pytest.raises(ValueError):
        coaching_evidence.validate_claim(f.claim("跨周。", [ref]), payload, root=root)


def test_historical_heart_fact_allowed_but_future_prescription_rejected(evidence_input):
    from skills._shared.fit_weekly import coaching_summary

    root, payload = evidence_input
    a = payload["current_week"]["activities"][0]
    ref = f.reference(a, ["summary", "metrics", "heart_rate_bpm", "mean"])
    good = f.summary(payload)
    good["core_conclusions"] = [f.claim("历史设备心率记录。", [ref])]
    coaching_summary.validate(good, payload, root=root)
    good["core_conclusions"][0]["text"] = "下周保持140 bpm"
    with pytest.raises(ValueError, match="coaching_heart_prescription"):
        coaching_summary.validate(good, payload, root=root)
