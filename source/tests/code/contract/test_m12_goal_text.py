from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest

from skills._shared.fit_weekly import (
    coaching_contract,
    coaching_evidence,
    model_job,
    run_config,
    stage_context,
    storage,
    weekly_context,
)
from skills._shared.scripts.schema_validation import validate_payload

helpers = importlib.import_module("test_m12_weekly_context")


def private_goal(tmp_path: Path, raw: bytes) -> Path:
    tmp_path.chmod(0o700)
    path = tmp_path / "Goal.md"
    path.write_bytes(raw)
    path.chmod(0o600)
    return path


@pytest.mark.parametrize(
    "text",
    [
        "最近希望稳定跑步。",
        "\n周末有空，周中时间不固定。\r\n\n先保持习惯。  ",
        "## 临时安排\n周三休息\n\n## 目标\n公园跑步，强度偏好 6，不参加比赛。",
        "不要求固定标题。\n周日和周二可训练；５：３０ min/km，Cafe\u0301。",
    ],
)
def test_free_goal_preserves_original_utf8_and_body(tmp_path, text):
    raw = text.encode()
    path = private_goal(tmp_path, raw)
    sha, snapshot = weekly_context.goal(tmp_path, allow_sports_location=True)
    assert sha == hashlib.sha256(raw).hexdigest()
    assert snapshot == {
        "sha256": model_job.sha(snapshot["goal"]),
        "goal": {"schema_version": "training_goal_text_v1", "text": text},
    }
    assert path.read_bytes() == raw
    assert not validate_payload(snapshot["goal"], "training_goal_text_v1")


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b" \r\n\t",
        b"\xff",
        b"token=synthetic-secret",
        b"Bearer synthetic-secret",
        b"device_id=synthetic-only",
        b"/private/synthetic.txt",
    ],
)
def test_invalid_or_private_goal_has_generic_error(tmp_path, raw):
    path = private_goal(tmp_path, raw)
    with pytest.raises(ValueError, match="^weekly_goal_invalid$"):
        weekly_context.goal(tmp_path, allow_sports_location=True)
    assert path.read_bytes() == raw


@pytest.mark.parametrize("mode", ["wide", "parent", "symlink", "hardlink"])
def test_goal_private_file_boundary(tmp_path, mode):
    path = private_goal(tmp_path, "希望周末跑步".encode())
    if mode == "wide":
        path.chmod(0o644)
    elif mode == "parent":
        tmp_path.chmod(0o755)
    else:
        target = tmp_path / "synthetic-text"
        path.rename(target)
        if mode == "symlink":
            path.symlink_to(target)
        else:
            path.hardlink_to(target)
    with pytest.raises(ValueError, match="^weekly_goal_invalid$"):
        weekly_context.goal(tmp_path)


def test_config_allows_explicit_external_private_goal(tmp_path):
    root = tmp_path / "instance"
    root.mkdir(mode=0o700)
    external = tmp_path / "external"
    external.mkdir(mode=0o700)
    path = private_goal(external, "希望保持训练习惯".encode())
    config = root / "config.json"
    config.write_text(
        json.dumps(
            {"schema_version": "fit_run_config_v1", "goal": str(path), "services": {}}
        )
    )
    config.chmod(0o600)
    loaded = run_config.load(root)
    assert loaded.goal_path == path
    assert (
        weekly_context.goal(root, path=loaded.goal_path)[1]["goal"]["text"]
        == "希望保持训练习惯"
    )


@pytest.mark.parametrize(
    "parser_version", ["fit-summary-1", "fit-summary-2", "fit-summary-3"]
)
def test_new_goal_version_is_independent_of_saved_fit_version(
    tmp_path, monkeypatch, parser_version
):
    root, evidence, _ = helpers.setup(
        tmp_path, monkeypatch, parser_version=parser_version
    )
    raw = "希望周二和周末跑步。\n\n其余时间先休息。 ".encode()
    private_goal(root, raw)
    body = helpers.frozen(root)
    assert body["schema_version"] == "fit_weekly_context_v4"
    assert body["current_week"]["activities"] == evidence["activities"]
    plan = stage_context.freeze(
        root, helpers.fixture.END, "plan", validate_history=helpers.valid_report
    )
    assert plan["schema_version"] == "fit_weekly_stage_input_v3"
    assert plan["goal_snapshot"] == body["goal_snapshot"]
    assert not validate_payload(plan, "fit_weekly_stage_input_v3")
    with storage.open_store(root) as db:
        from skills._shared.fit_weekly import fit_detail

        saved = fit_detail.get(db, "weekly-context:" + helpers.fixture.END)
        assert saved is not None
        assert saved[1]["goal_source_sha256"] == hashlib.sha256(raw).hexdigest()
    (root / "Goal.md").write_text("下周的不同目标")
    before = (root / "trainlab-fit.db").read_bytes()
    assert helpers.frozen(root) == body
    assert (root / "trainlab-fit.db").read_bytes() == before
    summary, validate, replay = helpers.summary_setup(root, body, helpers.valid_report)
    assert summary["goal_snapshot"] == plan["goal_snapshot"]
    validate(summary)
    replay()


def test_goal_evidence_references_original_text_only(tmp_path):
    goal = {"schema_version": "training_goal_text_v1", "text": "周二有空跑步"}
    payload = {"goal_snapshot": {"goal": goal}, "stage": "plan"}
    ref = {
        "source": "goal",
        "activity_ref": None,
        "fit_sha256": None,
        "session_ordinal": None,
        "period_end_utc": None,
        "request_sha256": None,
        "path": ["text"],
        "value": goal["text"],
    }
    assert coaching_evidence.resolve(ref, payload, root=tmp_path) == goal["text"]
    for path in (["weekly_availability", "tuesday"], ["schema_version"]):
        with pytest.raises(ValueError):
            coaching_evidence.resolve({**ref, "path": path}, payload, root=tmp_path)


@pytest.mark.parametrize("stage", ["plan", "summary"])
def test_prompt_explains_free_goal_without_expanding_authority(stage):
    prompt = coaching_contract.prompt(stage)
    assert 'path=["text"]' in prompt
    assert "does not authorize" in prompt
    coaching_contract.check(stage)


@pytest.mark.parametrize(
    "parser_version", ["fit-summary-1", "fit-summary-2", "fit-summary-3"]
)
def test_legacy_context_stage_sha_and_goal_paths_replay_unchanged(
    tmp_path, monkeypatch, parser_version
):
    from skills._shared.fit_weekly import fit_detail

    root, original, _ = helpers.setup(
        tmp_path, monkeypatch, parser_version=parser_version
    )
    goal = json.loads(
        (Path(__file__).parents[1] / "fixtures/m12_legacy_goal.json").read_text()
    )
    scope = fit_detail.freeze_scope(
        root,
        helpers.fixture.END,
        [
            {k: a[k] for k in ("activity_ref", "fit_sha256")}
            for a in original["activities"]
        ],
        parser_version=parser_version,
    )
    suffix = {"fit-summary-1": "v1", "fit-summary-2": "v2", "fit-summary-3": "v3"}[
        parser_version
    ]
    body = {
        "schema_version": "fit_weekly_context_" + suffix,
        "current_week": weekly_context.project_evidence(original),
        "goal_snapshot": {"sha256": model_job.sha(goal), "goal": goal},
        "history_reports": [],
        "scope_sha256": scope["scope_sha256"],
        "provider_calls": 0,
        "external_actions": 0,
    }
    record = {
        "schema_version": "fit_weekly_context_record_" + suffix,
        "evidence_sha256": model_job.sha(original),
        "goal_source_sha256": "a" * 64,
        "context": body,
    }
    with storage.open_store(root) as db:
        fit_detail.put(
            db, "weekly-context:" + helpers.fixture.END, model_job.sha(body), record
        )
    projected = stage_context.project(body, "plan")
    expected_version = (
        "fit_weekly_stage_input_v2" if suffix == "v3" else "fit_weekly_stage_input_v1"
    )
    assert projected["schema_version"] == expected_version
    assert projected["goal_snapshot"] == body["goal_snapshot"]
    assert not validate_payload(projected, expected_version)
    with storage.open_store(root) as db:
        fit_detail.put(
            db,
            "weekly-stage-input:" + helpers.fixture.END + ":plan",
            model_job.sha(projected),
            projected,
        )
    before = (root / "trainlab-fit.db").read_bytes()
    original_sha = model_job.sha(body)
    stage_sha = model_job.sha(projected)
    (root / "Goal.md").unlink()
    for _ in range(2):
        assert helpers.frozen(root) == body
        assert model_job.sha(helpers.frozen(root)) == original_sha
        actual = stage_context.freeze(
            root, helpers.fixture.END, "plan", validate_history=helpers.valid_report
        )
        assert actual == projected and model_job.sha(actual) == stage_sha
        stage_context.validator(
            root, helpers.fixture.END, "plan", validate_history=helpers.valid_report
        )(actual)
    ref = {
        "source": "goal",
        "activity_ref": None,
        "fit_sha256": None,
        "session_ordinal": None,
        "period_end_utc": None,
        "request_sha256": None,
        "path": ["training_preferences", "intensity_preference"],
        "value": 3,
    }
    assert coaching_evidence.resolve(ref, projected, root=root) == 3
    assert (root / "trainlab-fit.db").read_bytes() == before


def test_retired_fixed_goal_parser_is_not_a_runtime_dependency():
    from skills._shared.fit_weekly import runtime_resources

    source = Path(__file__).parents[3]
    paths = runtime_resources.files(source)
    assert not (source / "skills/_shared/scripts/training_goal_v1.py").exists()
    assert not (source / "skills/_shared/scripts/validate_goal.py").exists()
    assert source / "skills/_shared/schemas/training_goal_v1.schema.json" in paths
    assert source / "skills/_shared/schemas/training_goal_text_v1.schema.json" in paths


def test_goal_citation_and_report_edit_keep_original_goal(tmp_path, monkeypatch):
    reports = importlib.import_module("test_m12_report_revisions")
    original_goal = []

    def transform(stage, output, payload):
        if stage == "plan":
            text = payload["goal_snapshot"]["goal"]["text"]
            original_goal.append(text)
            ref = {
                "source": "goal",
                "activity_ref": None,
                "fit_sha256": None,
                "session_ordinal": None,
                "period_end_utc": None,
                "request_sha256": None,
                "path": ["text"],
                "value": text,
            }
            output["rationale"] = reports.f.coaching_fixture.claim(
                "依据用户原目标安排跑步。", [ref]
            )

    root, _, calls = reports.f.setup(tmp_path, monkeypatch, transform=transform)
    base = reports.revisions.create(root, reports.f.END)
    (root / "Goal.md").write_text("新的目标只用于以后新周")
    before = reports.original_rows(root)
    plan = model_job.clone(base["plan_content"])
    plan["rationale"]["text"] = "按已冻结的原目标安排跑步。"
    revised = reports.edit(root, base, "plan", plan)
    assert (
        revised["plan_content"]["rationale"]["evidence"][0]["value"] == original_goal[0]
    )
    assert revised["summary_content"] == base["summary_content"]
    assert reports.original_rows(root) == before
    plan["rationale"]["evidence"][0]["value"] = "新的目标只用于以后新周"
    with pytest.raises(ValueError):
        reports.edit(root, base, "plan", plan, "bad-goal")
    assert reports.original_rows(root) == before
    assert [call.calls for call in calls] == [1, 1]


def test_forged_source_sha_is_rejected_without_rewriting_snapshot(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import fit_detail

    root, _, _ = helpers.setup(tmp_path, monkeypatch, parser_version="fit-summary-3")
    body = helpers.frozen(root)
    before = (root / "trainlab-fit.db").read_bytes()
    with storage.open_store(root) as db:
        saved = fit_detail.get(db, "weekly-context:" + helpers.fixture.END)
        assert saved is not None
        sha, record = saved
        assert sha == model_job.sha(body)
        record["goal_source_sha256"] = "0" * 64
        with pytest.raises(ValueError, match="^weekly_context_invalid$"):
            weekly_context.checked(
                db, root, helpers.fixture.END, (sha, record), helpers.valid_report
            )
    assert (root / "trainlab-fit.db").read_bytes() == before
