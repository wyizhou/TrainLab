"""R4 explicit local editing preserves original captures and fixed host facts."""

import importlib
import shutil
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from skills._shared.fit_weekly import (
    coaching,
    fit_detail,
    model_job,
    storage,
)
from skills._shared.fit_weekly import (
    report_revisions as revisions,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
f = importlib.import_module("m12_report_factory")


def original_rows(root):
    with storage.open_store(root) as db:
        return [
            tuple(r)
            for r in db.execute("SELECT * FROM documents ORDER BY logical_key")
            if not r[1].startswith("report-")
        ]


def edit(root, base, target="summary", content=None, revision_id="edit-1"):
    return revisions.edit(
        root,
        f.END,
        base_revision_id=base["revision_id"],
        base_revision_sha256=model_job.sha(base),
        revision_id=revision_id,
        target=target,
        content=content if content is not None else f.edited_summary(base),
    )


def test_original_and_explicit_summary_revision_replay_and_move(tmp_path, monkeypatch):
    root, _, calls = f.setup(tmp_path, monkeypatch)
    before = original_rows(root)
    original = coaching.report(root, f.END)
    base = revisions.create(root, f.END)
    assert revisions.create(root, f.END) == base
    changed = edit(root, base)
    assert changed["plan_content"] == base["plan_content"]
    assert changed["source"] == base["source"]
    assert changed["summary_content"] != base["summary_content"]
    assert edit(root, base) == changed
    assert original_rows(root) == before
    assert coaching.report(root, f.END) == original
    moved = tmp_path / "moved"
    shutil.copytree(root, moved)
    assert revisions.read(moved, f.END, "edit-1", model_job.sha(changed)) == changed
    assert [c.calls for c in calls] == [1, 1]


@pytest.mark.parametrize(
    "field", ["facts", "plan", "raw_plan_sha256", "period_end_utc"]
)
def test_summary_edit_cannot_inject_host_facts_or_courses(tmp_path, monkeypatch, field):
    root, _, _ = f.setup(tmp_path, monkeypatch)
    base = revisions.create(root, f.END)
    candidate = f.edited_summary(base)
    candidate[field] = "unauthorized"
    before = (root / "trainlab-fit.db").read_bytes()
    with pytest.raises(ValueError):
        edit(root, base, content=candidate)
    assert (root / "trainlab-fit.db").read_bytes() == before


@pytest.mark.parametrize("text", ["保持140 bpm", "明天补跑", "排除健康风险"])
def test_invalid_editorial_prescription_is_not_saved(tmp_path, monkeypatch, text):
    root, _, _ = f.setup(tmp_path, monkeypatch)
    base = revisions.create(root, f.END)
    summary = f.edited_summary(base)
    summary["core_conclusions"][0]["text"] = text
    with pytest.raises(ValueError):
        edit(root, base, content=summary)
    with pytest.raises(ValueError):
        revisions.read(root, f.END, "edit-1", "a" * 64)


def test_plan_edit_uses_original_running_input_and_revalidates_dose(
    tmp_path, monkeypatch
):
    root, _, _ = f.setup(tmp_path, monkeypatch)
    before = original_rows(root)
    base = revisions.create(root, f.END)
    plan = deepcopy(base["plan_content"])
    plan["days"][0]["workout"]["technical_notes"] = "保持肩颈放松，观察动作。"
    changed = edit(root, base, "plan", plan)
    assert changed["summary_content"] == base["summary_content"]
    assert original_rows(root) == before
    view = revisions.view(root, f.END, changed["revision_id"], model_job.sha(changed))
    assert (
        view["facts"]["plan_dates"]
        == coaching.report(root, f.END)["facts"]["plan_dates"]
    )
    assert view["effective_plan_sha256"] == model_job.sha(plan)
    assert view["source"]["raw_plan_sha256"] == model_job.sha(base["plan_content"])
    plan["days"][0]["workout"]["dose"]["value"] += 1
    with pytest.raises(ValueError, match="dose"):
        edit(root, base, "plan", plan, "bad-dose")


def test_plan_edit_cannot_use_other_sport_source(tmp_path, monkeypatch):
    root, evidence, _ = f.setup(tmp_path, monkeypatch)
    base = revisions.create(root, f.END)
    plan = deepcopy(base["plan_content"])
    activity = next(
        a for a in evidence["activities"] if a["sessions"][0]["sport"] != "running"
    )
    ref = f.coaching_fixture.reference(activity)
    plan["rationale"] = f.coaching_fixture.claim("依据已记录的活动。", [ref])
    with pytest.raises(ValueError, match="evidence"):
        edit(root, base, "plan", plan)


@pytest.mark.parametrize("identifier", ["../escape", "/absolute", "", "x" * 65, "ai"])
def test_revision_identity_and_conflict(tmp_path, monkeypatch, identifier):
    root, _, _ = f.setup(tmp_path, monkeypatch)
    base = revisions.create(root, f.END)
    with pytest.raises(ValueError):
        edit(root, base, revision_id=identifier)
    first = edit(root, base)
    changed = f.edited_summary(base)
    changed["data_limitations"].append("另外的资料局限。")
    with pytest.raises(ValueError, match="conflict"):
        edit(root, base, content=changed)
    assert revisions.read(root, f.END, "edit-1", model_job.sha(first)) == first
    with pytest.raises(ValueError):
        revisions.read(root, f.END, "edit-1", "0" * 64)


def test_missing_corrupt_and_unknown_source_refused(tmp_path, monkeypatch):
    root, _, _ = f.setup(tmp_path, monkeypatch)
    base = revisions.create(root, f.END)
    path = model_job.capture_path(root, f.END, stage="summary")
    path.write_bytes(b"corrupt")
    for operation in (
        lambda: revisions.create(root, f.END),
        lambda: edit(root, base),
        lambda: revisions.read(root, f.END, "ai", model_job.sha(base)),
    ):
        with pytest.raises(ValueError):
            operation()


def test_missing_stage_never_creates_revision(tmp_path, monkeypatch):
    root, _, _ = f.contexts.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")
    with pytest.raises(ValueError):
        revisions.create(root, f.END)
    with storage.open_store(root) as db:
        assert fit_detail.get(db, "report-revision:" + f.END + ":ai") is None


def test_existing_detail_revision_does_not_read_fit_or_add_budget(
    tmp_path, monkeypatch
):
    root, evidence, _ = f.setup(tmp_path, monkeypatch)
    base = revisions.create(root, f.END)
    with storage.open_store(root) as db:
        scope = fit_detail.get(db, "detail:" + f.END + ":scope")[0]
    activity = next(
        a for a in evidence["activities"] if a["sessions"][0]["sport"] == "running"
    )
    result = fit_detail.DetailHost(root, f.END, scope, stage="plan").read(
        {
            "activity_ref": activity["activity_ref"],
            "view": "summary",
            "start_offset_seconds": 0,
            "end_offset_seconds": 60,
            "resolution_seconds": 5,
        }
    )
    ref = f.coaching_fixture.reference(activity)
    ref.update(
        source="detail",
        request_sha256=result["request_sha256"],
        path=["blocks", 0, "statistics", "distance_m"],
        value=result["blocks"][0]["statistics"]["distance_m"],
    )
    plan = deepcopy(base["plan_content"])
    plan["rationale"] = f.coaching_fixture.claim("依据已有跑步细读距离。", [ref])
    before = original_rows(root)

    def forbidden(*args, **kwargs):
        raise AssertionError("R4 revalidation cannot invoke detail or read FIT")

    monkeypatch.setattr(fit_detail.DetailHost, "read", forbidden)
    monkeypatch.setattr(fit_detail, "fit_bytes", forbidden)
    changed = edit(root, base, "plan", plan)
    assert (
        revisions.read(root, f.END, changed["revision_id"], model_job.sha(changed))
        == changed
    )
    assert original_rows(root) == before
