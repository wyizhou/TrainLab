from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
f = importlib.import_module("m12_coaching_factory")
contexts = importlib.import_module("test_m12_weekly_context")


def contracts(root, *, invalid=None, plan_limitations=None):
    from skills._shared.fit_weekly import coaching, model_job

    adapters = []
    payloads = []

    def factory(stage):
        def prepare(payload, scope):
            output = f.plan() if stage == "plan" else f.summary(payload)
            if stage == "plan" and plan_limitations is not None:
                output["progression_limitations"] = list(plan_limitations)
            if invalid == stage:
                output = {}
            adapter = model_job.FakeAdapter(output, [])
            adapters.append(adapter)
            payloads.append(payload)
            return adapter

        return prepare

    return (
        coaching.stage_contract(root, "plan", factory("plan")),
        coaching.stage_contract(root, "summary", factory("summary")),
        adapters,
        payloads,
    )


@pytest.mark.parametrize("parser_version", ["fit-summary-1", "fit-summary-2"])
def test_business_stages_report_replay_archive_and_move(
    tmp_path, monkeypatch, parser_version
):
    from dataclasses import replace

    from skills._shared.fit_weekly import coaching, weekly_history, weekly_stages
    from skills._shared.scripts.schema_validation import validate_payload

    root, evidence, _ = contexts.setup(
        tmp_path, monkeypatch, parser_version=parser_version
    )
    p, s, adapters, inputs = contracts(root)
    result = weekly_stages.run(
        root,
        contexts.fixture.END,
        plan=p,
        summary=s,
        validate_history=coaching.validator(root),
    )
    assert result["publishable"]
    report = coaching.report(root, contexts.fixture.END)
    assert validate_payload(report, "fit_coaching_report_v1") == []
    assert [d["date"] for d in report["plan"]["days"]] == evidence["next_plan_dates"]
    assert report["facts"]["activity_count"] == len(evidence["activities"])
    assert report["facts"]["session_count"] == sum(
        len(a["sessions"]) for a in evidence["activities"]
    )
    assert (
        report["facts"]["inventory"][1]["sport"]
        == evidence["activities"][1]["sessions"][0]["sport"]
    )
    assert report["raw_plan_sha256"] == report["plan"]["original_plan_sha256"]
    archived = weekly_history.archive(
        root, contexts.fixture.END, validate_report=coaching.validator(root)
    )
    moved = tmp_path / "relocated"
    shutil.copytree(root, moved)

    def forbidden(*_):
        raise AssertionError("replay must not prepare")

    before = (moved / "trainlab-fit.db").read_bytes()
    repeated = weekly_stages.run(
        moved,
        contexts.fixture.END,
        plan=replace(
            p, prepare_adapter=forbidden, validate_result=coaching.validator(moved)
        ),
        summary=replace(
            s, prepare_adapter=forbidden, validate_result=coaching.validator(moved)
        ),
        validate_history=coaching.validator(moved),
    )
    assert repeated["report"] == result["report"]
    assert coaching.report(moved, contexts.fixture.END) == report
    assert (
        weekly_history.archive(
            moved, contexts.fixture.END, validate_report=coaching.validator(moved)
        )
        == archived
    )
    assert (moved / "trainlab-fit.db").read_bytes() == before
    assert [a.calls for a in adapters] == [1, 1]
    assert (
        repeated["plan"]["invocation_adapter_calls"]
        == repeated["summary"]["invocation_adapter_calls"]
        == 0
    )
    assert len(inputs) == 2 and "current_week" not in inputs[0]


@pytest.mark.parametrize("invalid", ["plan", "summary"])
def test_business_failure_preserves_stage_boundary(tmp_path, monkeypatch, invalid):
    from skills._shared.fit_weekly import coaching, fit_detail, storage, weekly_stages

    root, _, _ = contexts.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")
    p, s, adapters, _ = contracts(root, invalid=invalid)
    for _ in range(2):
        result = weekly_stages.run(
            root,
            contexts.fixture.END,
            plan=p,
            summary=s,
            validate_history=coaching.validator(root),
        )
        assert result["status"] == "failed" and not result["publishable"]
    assert len(adapters) == (1 if invalid == "plan" else 2)
    assert all(a.calls == 1 for a in adapters)
    if invalid == "plan":
        with storage.open_store(root) as db:
            assert (
                fit_detail.get(
                    db, "model-job:" + contexts.fixture.END + ":summary:intent"
                )
                is None
            )
    else:
        assert result["plan"]["status"] == "succeeded"
    with pytest.raises(ValueError):
        coaching.report(root, contexts.fixture.END)


def test_closed_runtime_business_report_without_tests_or_archive(tmp_path, monkeypatch):
    import json
    import os
    import subprocess

    from skills._shared.fit_weekly import runtime_resources

    root, evidence, _ = contexts.setup(
        tmp_path, monkeypatch, parser_version="fit-summary-2"
    )
    source = Path(__file__).resolve().parents[3]
    closed = tmp_path / "closed"
    for path in runtime_resources.files(source):
        target = closed / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    assert not (closed / "tests").exists() and not (closed / "data-backup").exists()
    program = """
import json,sys
from pathlib import Path
from skills._shared.fit_weekly import coaching,weekly_stages,model_job,weekly_history
root,end=Path(sys.argv[1]),sys.argv[2]
outputs=json.load(sys.stdin)
calls=[]
def factory(stage):
    def prepare(payload,scope):
        adapter=model_job.FakeAdapter(outputs[stage],[])
        calls.append(adapter)
        return adapter
    return prepare
def run(root):
    return weekly_stages.run(root,end,plan=coaching.stage_contract(root,"plan",factory("plan")),summary=coaching.stage_contract(root,"summary",factory("summary")),validate_history=coaching.validator(root))
assert run(root)["publishable"]
report=coaching.report(root,end)
history=weekly_history.archive(root,end,validate_report=coaching.validator(root))
moved=root.with_name("moved-closed")
root.rename(moved)
before=(moved/"trainlab-fit.db").read_bytes()
assert run(moved)["publishable"]
assert coaching.report(moved,end)==report
assert weekly_history.archive(moved,end,validate_report=coaching.validator(moved))==history
assert (moved/"trainlab-fit.db").read_bytes()==before
assert [a.calls for a in calls]==[1,1]
print(json.dumps({"calls":2,"replay_calls":0,"activities":report["facts"]["activity_count"]}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", program, str(root), contexts.fixture.END],
        input=json.dumps(
            {"plan": f.plan(), "summary": f.summary({"current_week": evidence})}
        ),
        cwd=closed,
        env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "calls": 2,
        "replay_calls": 0,
        "activities": len(evidence["activities"]),
    }


@pytest.mark.parametrize("activities", [[], [("103", 300, None)]])
def test_no_activity_and_no_fit_full_report_remain_distinct(
    tmp_path, monkeypatch, activities
):
    from skills._shared.fit_weekly import coaching, weekly_stages

    root, evidence, _ = contexts.setup(
        tmp_path, monkeypatch, activities, parser_version="fit-summary-1"
    )
    p, s, _, _ = contracts(root)
    assert weekly_stages.run(
        root,
        contexts.fixture.END,
        plan=p,
        summary=s,
        validate_history=coaching.validator(root),
    )["publishable"]
    report = coaching.report(root, contexts.fixture.END)
    assert report["facts"]["activity_count"] == 0
    assert len(report["facts"]["unplaced_no_fit"]) == len(activities)
    assert report["plan"]["progression"]["baseline"] is None


@pytest.mark.parametrize("text", ["保持140 bpm", "明天补跑", "排除健康风险"])
def test_plan_limitations_failure_never_starts_summary(tmp_path, monkeypatch, text):
    from skills._shared.fit_weekly import coaching, fit_detail, storage, weekly_stages

    root, _, _ = contexts.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")
    p, s, adapters, payloads = contracts(root, plan_limitations=[text])
    for _ in range(2):
        result = weekly_stages.run(
            root,
            contexts.fixture.END,
            plan=p,
            summary=s,
            validate_history=coaching.validator(root),
        )
        assert not result["publishable"]
        assert result["status"] == "failed"
        assert result["summary"] is None and result["report"] is None
        assert [a.calls for a in adapters] == [1]
        assert [p["stage"] for p in payloads] == ["plan"]
        with storage.open_store(root) as db:
            assert (
                fit_detail.get(
                    db, "model-job:" + contexts.fixture.END + ":summary:intent"
                )
                is None
            )
        with pytest.raises(ValueError, match="weekly_history_invalid"):
            coaching.report(root, contexts.fixture.END)


@pytest.mark.parametrize("text", ["保持140 bpm", "明天补跑", "排除健康风险"])
def test_saved_plan_limitations_revalidated_without_rewriting(
    tmp_path, monkeypatch, text
):
    from dataclasses import replace

    from skills._shared.fit_weekly import (
        coaching,
        coaching_plan,
        weekly_history,
        weekly_stages,
    )

    root, _, _ = contexts.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")
    p, s, adapters, _ = contracts(root, plan_limitations=[text])

    def shape_only(output, payload):
        # Seed an old shape-valid capture to exercise current revalidation.
        coaching_plan.validate_shape(output)

    assert weekly_stages.run(
        root,
        contexts.fixture.END,
        plan=replace(p, validate_result=shape_only),
        summary=s,
        validate_history=coaching.validator(root),
    )["publishable"]
    before = (root / "trainlab-fit.db").read_bytes()
    with pytest.raises(ValueError, match="model_capture_invalid"):
        weekly_stages.run(
            root,
            contexts.fixture.END,
            plan=p,
            summary=s,
            validate_history=coaching.validator(root),
        )
    with pytest.raises(ValueError, match="model_capture_invalid"):
        coaching.report(root, contexts.fixture.END)
    with pytest.raises(ValueError, match="weekly_history_invalid"):
        weekly_history.archive(
            root, contexts.fixture.END, validate_report=coaching.validator(root)
        )
    assert [a.calls for a in adapters] == [1, 1]
    assert (root / "trainlab-fit.db").read_bytes() == before
