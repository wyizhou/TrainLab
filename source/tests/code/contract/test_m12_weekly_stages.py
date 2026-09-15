from __future__ import annotations

import copy
import importlib
import shutil

import pytest

jobs = importlib.import_module("test_m12_model_job")
contexts = importlib.import_module("test_m12_weekly_context")


def contracts():
    from skills._shared.fit_weekly import model_job, weekly_stages

    plan_output = {"schedule": ["synthetic running day"] * 7}
    summary_output = {
        "running_analysis": {"finding": "synthetic running only"},
        "all_sports": "synthetic cycling and running summary",
    }
    plan_schema = {
        "type": "object",
        "required": ["schedule"],
        "additionalProperties": False,
        "properties": {"schedule": {"type": "array", "items": {"type": "string"}}},
    }
    summary_schema = {
        "type": "object",
        "required": ["running_analysis", "all_sports"],
        "additionalProperties": False,
        "properties": {
            "running_analysis": {
                "type": "object",
                "required": ["finding"],
                "additionalProperties": False,
                "properties": {"finding": {"type": "string"}},
            },
            "all_sports": {"type": "string"},
        },
    }
    adapters = [
        model_job.FakeAdapter(plan_output, []),
        model_job.FakeAdapter(summary_output, []),
    ]
    inputs = []

    def check(output, payload):
        assert payload["stage"] in ("plan", "summary")
        assert output == (plan_output if payload["stage"] == "plan" else summary_output)

    def factory(index):
        def prepare(payload, scope):
            inputs.append(copy.deepcopy(payload))
            return adapters[index]

        return prepare

    return (
        weekly_stages.StageContract(plan_schema, check, factory(0)),
        weekly_stages.StageContract(summary_schema, check, factory(1)),
        check,
        adapters,
        inputs,
    )


def test_two_stage_projection_fixed_plan_replay_and_move(tmp_path, monkeypatch):
    from dataclasses import replace

    from skills._shared.fit_weekly import storage, weekly_history, weekly_stages

    root, evidence, _ = contexts.setup(
        tmp_path, monkeypatch, parser_version="fit-summary-2"
    )
    p, s, history, adapters, inputs = contracts()
    result = weekly_stages.run(
        root, contexts.fixture.END, plan=p, summary=s, validate_history=history
    )
    assert result["publishable"] is True
    assert len(inputs) == 2 and [x["stage"] for x in inputs] == ["plan", "summary"]
    assert "counts" not in str(inputs[0]) and "current_week" not in inputs[0]
    assert all(
        session["sport"] == "running"
        for a in inputs[0]["running_activities"]
        for session in a["sessions"]
    )
    assert inputs[1]["current_week"]["activities"] == evidence["activities"]
    assert inputs[1]["fixed_plan"]["plan"] == result["plan"]["result"]
    assert result["report"]["running"] == {
        "analysis": result["summary"]["result"]["running_analysis"],
        "plan": result["plan"]["result"],
    }
    archived = weekly_history.archive(
        root, contexts.fixture.END, validate_report=history
    )
    assert archived["report"] == result["report"]
    with storage.open_store(root) as db:
        assert weekly_history.read(db, root, contexts.fixture.END, history) == archived
    moved = tmp_path / "moved"
    shutil.copytree(root, moved)
    (moved / "Goal.md").write_text("edited after freeze")

    def forbidden(*_):
        raise AssertionError("closed stage must not prepare or probe")

    repeated = weekly_stages.run(
        moved,
        contexts.fixture.END,
        plan=replace(p, prepare_adapter=forbidden),
        summary=replace(s, prepare_adapter=forbidden),
        validate_history=history,
    )
    assert repeated["report"] == result["report"]
    assert [a.calls for a in adapters] == [1, 1]
    assert (
        repeated["plan"]["invocation_adapter_calls"]
        == repeated["summary"]["invocation_adapter_calls"]
        == 0
    )


@pytest.mark.parametrize("failed_stage", ["plan", "summary"])
def test_stage_failure_never_publishes_or_retries(tmp_path, monkeypatch, failed_stage):
    from skills._shared.fit_weekly import fit_detail, storage, weekly_stages

    root, _, _ = contexts.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")
    p, s, history, adapters, inputs = contracts()
    adapters[0 if failed_stage == "plan" else 1].output = {}
    for _ in range(2):
        result = weekly_stages.run(
            root, contexts.fixture.END, plan=p, summary=s, validate_history=history
        )
        assert (
            result["status"] == "failed"
            and result["publishable"] is False
            and result["report"] is None
        )
    with storage.open_store(root) as db:
        assert (
            fit_detail.get(db, "weekly-stages-result:" + contexts.fixture.END) is None
        )
        if failed_stage == "plan":
            assert (
                fit_detail.get(
                    db, "model-job:" + contexts.fixture.END + ":summary:intent"
                )
                is None
            )
        else:
            assert result["plan"]["status"] == "succeeded"
    assert [a.calls for a in adapters] == ([1, 0] if failed_stage == "plan" else [1, 1])


def test_old_history_not_forwarded_to_plan_and_occupied_week_not_reauthorized(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import (
        fit_detail,
        model_job,
        stage_context,
        weekly_stages,
    )

    root, _, _ = contexts.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")
    contexts.record(root, contexts.end_before(1))
    plan_input = stage_context.freeze(
        root, contexts.fixture.END, "plan", validate_history=contexts.valid_report
    )
    assert plan_input["running_history"] == []
    contexts.record(root, contexts.fixture.END, archive=False)
    p, s, _, adapters, _ = contracts()
    with pytest.raises(ValueError, match="model_legacy_week_occupied"):
        weekly_stages.run(
            root,
            contexts.fixture.END,
            plan=p,
            summary=s,
            validate_history=contexts.valid_report,
        )
    assert [a.calls for a in adapters] == [0, 0]
    scope = fit_detail.freeze_scope(root, contexts.end_before(2), [])
    recovered = model_job.recover(
        root,
        contexts.end_before(2),
        scope["scope_sha256"],
        {"public": True},
        {"type": "object"},
        model_job.FakeAdapter({"ok": True}, []),
        validate_input=jobs.valid_input,
        validate_result=jobs.valid_result,
        read_completed=lambda _: None,
    )
    assert (
        recovered["status"] == "unknown" and recovered["invocation_adapter_calls"] == 0
    )


def test_missing_stage_never_creates_old_job(tmp_path):
    from skills._shared.fit_weekly import model_job

    args = jobs.setup(tmp_path)
    with pytest.raises(ValueError, match="model_stage_required"):
        model_job.run(
            *args, validate_input=jobs.valid_input, validate_result=jobs.valid_result
        )
    assert args[-1].calls == 0


def test_parameterized_model_stage_once_and_separate_capture(tmp_path):
    from skills._shared.fit_weekly import model_job

    args = jobs.setup(tmp_path)
    for stage in ("plan", "summary"):
        first = model_job.run(
            *args,
            stage=stage,
            validate_input=jobs.valid_input,
            validate_result=jobs.valid_result,
        )
        assert first["status"] == "succeeded"
        assert first["receipt"]["stage"] == stage
        assert (
            model_job.run(
                *args,
                stage=stage,
                validate_input=jobs.valid_input,
                validate_result=jobs.valid_result,
            )["invocation_adapter_calls"]
            == 0
        )
    assert args[-1].calls == 2
    assert model_job.capture_path(
        args[0], args[1], stage="plan"
    ) != model_job.capture_path(args[0], args[1], stage="summary")


def test_next_week_history_has_only_bound_running_analysis_and_plan(
    tmp_path, monkeypatch
):
    import asyncio
    from datetime import timedelta

    from skills._shared.fit_weekly import (
        fit_sync,
        stage_context,
        sync_calendar,
        weekly_evidence,
        weekly_history,
        weekly_stages,
    )

    root, _, _ = contexts.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")
    p, s, history, _, _ = contracts()
    first = weekly_stages.run(
        root, contexts.fixture.END, plan=p, summary=s, validate_history=history
    )
    weekly_history.archive(root, contexts.fixture.END, validate_report=history)
    next_end = (
        sync_calendar.utc_time(contexts.fixture.END) + timedelta(weeks=1)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    request = sync_calendar.InventoryRequest(
        key="synthetic-next-week",
        start_date="2026-08-09",
        end_date="2026-08-16",
        as_of_utc="2026-08-16T07:00:10Z",
        page_size=20,
        max_calls=2,
    )
    sdk = contexts.fixture.FakeSDK([])
    asyncio.run(
        fit_sync.synchronize(
            root,
            fit_sync.SyncSpec(request, 20, 2, 2, True, 120),
            token_root=tmp_path / "tokens",
            session_factory=sdk.session,
        )
    )
    weekly_evidence.freeze(root, next_end, request.key)
    next_plan = stage_context.freeze(root, next_end, "plan", validate_history=history)
    assert next_plan["running_activities"] == []
    assert next_plan["running_history"][0]["running"] == first["report"]["running"]
    assert "cycling" not in str(next_plan)
    assert "all_sports" not in str(next_plan)
    with pytest.raises(ValueError, match="weekly_plan_missing"):
        stage_context.freeze(
            root,
            next_end,
            "summary",
            validate_history=history,
            plan=first["report"]["plan_binding"],
            validate_plan=p.validate_result,
        )
    next_result = weekly_stages.run(
        root, next_end, plan=p, summary=s, validate_history=history
    )
    next_summary = stage_context.freeze(
        root,
        next_end,
        "summary",
        validate_history=history,
        plan=next_result["report"]["plan_binding"],
        validate_plan=p.validate_result,
    )
    assert "cycling" in str(next_summary["history_reports"])


@pytest.mark.parametrize("stage", ["plan", "summary"])
def test_unknown_stage_stops_and_local_callback_cannot_claim_success(
    tmp_path, monkeypatch, stage
):
    from dataclasses import replace

    from skills._shared.fit_weekly import model_job, weekly_stages

    root, _, _ = contexts.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")
    p, s, history, adapters, inputs = contracts()

    def interrupt(*_):
        raise model_job.AdapterInterrupted()

    adapters[0 if stage == "plan" else 1].run = interrupt
    with pytest.raises(model_job.AdapterInterrupted):
        weekly_stages.run(
            root, contexts.fixture.END, plan=p, summary=s, validate_history=history
        )

    def forbidden(*_):
        raise AssertionError("unknown never prepares again")

    p = replace(
        p, prepare_adapter=forbidden, recover=lambda *_: {"status": "succeeded"}
    )
    s = replace(
        s, prepare_adapter=forbidden, recover=lambda *_: {"status": "succeeded"}
    )
    result = weekly_stages.run(
        root, contexts.fixture.END, plan=p, summary=s, validate_history=history
    )
    assert result["status"] == "unknown" and result["publishable"] is False
    assert len(inputs) == (1 if stage == "plan" else 2)


def test_nonrunning_evidence_changes_do_not_change_plan_projection(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import stage_context, weekly_context

    root, _, _ = contexts.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")
    materials = weekly_context.freeze(
        root, contexts.fixture.END, validate_report=contexts.valid_report
    )
    original = stage_context.project(materials, "plan")
    modified = copy.deepcopy(materials)
    modified["current_week"]["activities"] = [
        a
        for a in modified["current_week"]["activities"]
        if any(s["sport"] == "running" for s in a["sessions"])
    ]
    modified["current_week"]["counts"] = {"synthetic": 999}
    modified["current_week"]["unplaced_no_fit"] = [{"synthetic": "non-running unknown"}]
    modified["scope_sha256"] = "f" * 64
    assert stage_context.project(modified, "plan") == original


def test_mixed_fit_projection_has_only_running_sessions(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import (
        fit_parse,
        stage_context,
        storage,
        weekly_context,
    )

    root, _, _ = contexts.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")
    materials = weekly_context.freeze(
        root, contexts.fixture.END, validate_report=contexts.valid_report
    )
    detail = jobs.fixture
    f = detail.fixture
    data = f.file_bytes(
        [f.record(t, t * 3, 123) for t in range(0, 1801, 10)]
        + [f.session(900), f.session(1800, start=900, sport=2)]
    )
    folder = tmp_path / "mixed"
    folder.mkdir(mode=0o700)
    mixed, _, members = detail.instance(folder, data)
    with storage.open_store(mixed) as db:
        activity = fit_parse.parse_registered(
            db, mixed, members[0]["activity_ref"], members[0]["fit_sha256"]
        )
    materials["current_week"]["activities"] = [activity]
    projected = stage_context.project(materials, "plan")["running_activities"][0]
    assert projected["sessions"] == activity["sessions"][:1]
    assert "location" not in projected
    assert "end_utc" not in projected
    assert "cycling" not in str(projected)
    assert projected["fit_sha256"] == members[0]["fit_sha256"]


@pytest.mark.parametrize("field", ["analysis", "plan"])
def test_history_running_field_cannot_be_replaced(tmp_path, monkeypatch, field):
    from skills._shared.fit_weekly import (
        model_job,
        storage,
        weekly_history,
        weekly_stages,
    )

    root, _, _ = contexts.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")
    p, s, history, _, _ = contracts()
    weekly_stages.run(
        root, contexts.fixture.END, plan=p, summary=s, validate_history=history
    )
    archived = weekly_history.archive(
        root, contexts.fixture.END, validate_report=history
    )
    archived["report"]["running"][field] = {"synthetic": "substitution"}
    archived["report_sha256"] = model_job.sha(archived["report"])
    text = storage.canonical(archived)
    with pytest.raises(ValueError, match="store_database_invalid"):
        with storage.open_store(root) as db:
            db.execute(
                "UPDATE documents SET content_json=?,content_sha256=? WHERE kind='weekly_report'",
                (text, storage.digest(text.encode())),
            )
    # The SQL layer already prevents replacement. Inject only the stored-row
    # read to also exercise independent reconstruction from original captures.
    monkeypatch.setattr(weekly_history, "stored", lambda *_: archived)
    with storage.open_store(root) as db:
        with pytest.raises(ValueError, match="weekly_history_invalid"):
            weekly_history.read(db, root, contexts.fixture.END, history)


def test_summary_requires_current_plan_binding_and_schema_callback(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    from skills._shared.fit_weekly import stage_context, weekly_stages

    root, _, _ = contexts.setup(tmp_path, monkeypatch, parser_version="fit-summary-2")
    p, s, history, adapters, _ = contracts()
    for invalid in (
        replace(s, validate_result=None),
        replace(s, response_schema=p.response_schema),
    ):
        with pytest.raises(ValueError):
            weekly_stages.run(
                root,
                contexts.fixture.END,
                plan=p,
                summary=invalid,
                validate_history=history,
            )
    assert [a.calls for a in adapters] == [0, 0]
    result = weekly_stages.run(
        root, contexts.fixture.END, plan=p, summary=s, validate_history=history
    )
    fixed = copy.deepcopy(result["report"]["plan_binding"])
    fixed["plan"]["schedule"][0] = "replaced"
    with pytest.raises(ValueError, match="weekly_plan_binding_invalid"):
        stage_context.freeze(
            root,
            contexts.fixture.END,
            "summary",
            validate_history=history,
            plan=fixed,
            validate_plan=p.validate_result,
        )
