from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from skills._shared.fit_weekly import fit_detail, model_job, report_artifacts, storage

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE / "tests/code/fixtures"))
sys.path.insert(0, str(SOURCE / "tests/code/contract"))
fixture = importlib.import_module("m12_weekly_factory")


def test_real_entrypoint_complete_week_process_pdf_rest_mcp_and_move(
    tmp_path, monkeypatch, capsys
):
    root, _, _, provider, http = fixture.setup(tmp_path, monkeypatch)
    result = fixture.cli(
        root,
        monkeypatch,
        "--authorization",
        "authorization.json",
        "weekly",
        "--period-end",
        fixture.END,
    )
    output = capsys.readouterr()
    assert result == 0, output
    value = json.loads(output.out)
    assert value["status"] == "complete"
    assert value["publication"]["late"] is False
    assert [v["status"] for v in value["stages"].values()] == ["succeeded", "succeeded"]
    assert provider.starts == provider.closed == [False, True, True, True]
    assert len(provider.workouts) == len(provider.calendar) == 3
    assert sum(url.endswith("/send") for _, url, _ in http.calls) == 1
    first = provider.workouts[100]["workoutSegments"][0]["workoutSteps"][0]
    assert first["type"] == "RepeatGroupDTO" and first["numberOfIterations"] == 2
    bundle = report_artifacts.read_sealed(root, fixture.END)
    assert bundle.pdf.startswith(b"%PDF") and "运动表现" in bundle.markdown.decode()
    for stage in ("plan", "summary"):
        work = model_job.capture_path(root, fixture.END, stage=stage).parent / "command"
        prepared = json.loads((work / "prepared.json").read_text())
        assert prepared["runtime"]["timeout_seconds"] == 30
        assert (work / "process/capture.json").is_file()
    with storage.open_store(root) as db:
        from skills._shared.fit_weekly import coaching, weekly_history

        history = weekly_history.recent(db, root, fixture.END, coaching.validator(root))
        assert len(history) == 1 and history[0]["period_end_utc"] == fixture.END
        plan = fit_detail.get(db, f"model-job:{fixture.END}:plan:intent")[1]
        summary = fit_detail.get(db, f"model-job:{fixture.END}:summary:intent")[1]
        assert [a["activity_ref"] for a in plan["payload"]["running_activities"]] == [
            "101"
        ]
        assert len(summary["payload"]["current_week"]["activities"]) == 2
    moved = tmp_path / "moved"
    root.rename(moved)
    counts = (len(provider.calls), len(http.calls))
    (moved / "model.json").unlink()
    (moved / "weekly-goal.md").unlink()
    assert fixture.cli(moved, monkeypatch, "weekly", "--period-end", fixture.END) == 0
    capsys.readouterr()
    assert (len(provider.calls), len(http.calls)) == counts
    assert fixture.cli(moved, monkeypatch, "reconcile") == 0
    capsys.readouterr()
    assert fixture.cli(moved, monkeypatch, "status") == 0
    state = json.loads(capsys.readouterr().out)
    assert state["business"] == {"failed": 0, "pending": 0, "unknown": 0}


@pytest.mark.parametrize("stage", ["plan", "summary"])
def test_failed_model_stops_later_stage_or_publication(
    tmp_path, monkeypatch, capsys, stage
):
    root, _, _, provider, http = fixture.setup(tmp_path, monkeypatch, fail_stage=stage)
    assert (
        fixture.cli(
            root,
            monkeypatch,
            "--authorization",
            "authorization.json",
            "weekly",
            "--period-end",
            fixture.END,
        )
        == 5
    )
    value = json.loads(capsys.readouterr().out)
    assert value["stages"][stage]["status"] == "failed"
    assert value["publication"] is None
    if stage == "plan":
        assert value["stages"]["summary"] is None
    assert not http.calls and not provider.workouts


def test_pre_cutoff_and_incomplete_sync_never_start_models(
    tmp_path, monkeypatch, capsys
):
    root, _, _, provider, http = fixture.setup(tmp_path, monkeypatch)
    provider.close_failure = True
    assert (
        fixture.cli(
            root,
            monkeypatch,
            "--authorization",
            "authorization.json",
            "weekly",
            "--period-end",
            fixture.END,
        )
        == 2
    )
    capsys.readouterr()
    assert not (root / "models").exists() and not http.calls
    with storage.open_store(root) as db:
        assert fit_detail.get(db, "weekly-evidence:" + fixture.END) is None


def test_authorized_timeout_reaches_actual_supervised_process(
    tmp_path, monkeypatch, capsys
):
    root, _, _, _, http = fixture.setup(
        tmp_path, monkeypatch, timeout_stage="plan", timeout=0.3
    )
    assert (
        fixture.cli(
            root,
            monkeypatch,
            "--authorization",
            "authorization.json",
            "weekly",
            "--period-end",
            fixture.END,
        )
        == 5
    )
    value = json.loads(capsys.readouterr().out)
    assert value["stages"]["plan"]["status"] == "failed"
    capture = json.loads(
        (
            model_job.capture_path(root, fixture.END, stage="plan").parent
            / "command/process/capture.json"
        ).read_text()
    )
    assert capture["process"]["error_code"] == "process_timeout"
    assert capture["process"]["process_stopped"] is True
    assert not http.calls


def invoke(root, monkeypatch, capsys, *args, expected=0):
    code = fixture.cli(root, monkeypatch, *args)
    output = capsys.readouterr()
    assert code == expected, output
    return json.loads(output.out) if output.out else None


def save_grant(root, value):
    path = root / "authorization.json"
    path.write_text(json.dumps(value))
    path.chmod(0o600)


def readonly_grant(grant, *, key="public-readonly"):
    from skills._shared.fit_weekly import publication_ledger

    value = grant.value()
    value.update(key=key, sync=None, models=[])
    value["publication"]["max_calls"] = {
        k: v
        for k, v in value["publication"]["max_calls"].items()
        if k not in publication_ledger.WRITE_TOOLS
    }
    return value


def test_draft_edit_publish_seal_and_token_free_local_operations(
    tmp_path, monkeypatch, capsys
):
    from skills._shared.fit_weekly import report_revisions, run_reconcile

    root, config, _, provider, http = fixture.setup(tmp_path, monkeypatch)
    draft = invoke(
        root,
        monkeypatch,
        capsys,
        "--authorization",
        "authorization.json",
        "weekly",
        "--period-end",
        fixture.END,
        "--phase",
        "draft",
    )
    assert not http.calls and not provider.workouts
    original = report_revisions.read(root, fixture.END, "ai", draft["revision_sha256"])
    content = importlib.import_module("m12_report_factory").edited_summary(original)
    (root / "edit.json").write_text(json.dumps(content))
    (root / "edit.json").chmod(0o600)
    (root / "model.json").unlink()
    (root / "weekly-goal.md").unlink()
    token = config.service("gmail")["token_file"]
    token_path = Path(token)
    token_path.rename(token_path.with_suffix(".saved"))
    edited = invoke(
        root,
        monkeypatch,
        capsys,
        "edit",
        "--period-end",
        fixture.END,
        "--base-id",
        "ai",
        "--base-sha",
        draft["revision_sha256"],
        "--revision-id",
        "local-edit",
        "--part",
        "summary",
        "--content",
        "edit.json",
    )
    assert run_reconcile.local(root)["status"] == "complete"
    revision = report_revisions.read(
        root, fixture.END, "local-edit", edited["revision_sha256"]
    )
    assert revision["plan_content"] == original["plan_content"]
    assert (
        report_revisions.read(root, fixture.END, "ai", draft["revision_sha256"])
        == original
    )
    token_path.with_suffix(".saved").rename(token_path)
    published = invoke(
        root,
        monkeypatch,
        capsys,
        "--authorization",
        "authorization.json",
        "weekly",
        "--period-end",
        fixture.END,
        "--phase",
        "publish",
        "--revision-id",
        "local-edit",
        "--revision-sha",
        edited["revision_sha256"],
    )
    assert (
        published["publication"]["seal"]["revision_sha256"] == edited["revision_sha256"]
    )
    assert (
        published["pdf_sha256"]
        == published["publication"]["mail"]["evidence"]["pdf_sha256"]
    )
    invoke(
        root,
        monkeypatch,
        capsys,
        "edit",
        "--period-end",
        fixture.END,
        "--base-id",
        "local-edit",
        "--base-sha",
        edited["revision_sha256"],
        "--revision-id",
        "sealed-edit",
        "--part",
        "summary",
        "--content",
        "edit.json",
        expected=2,
    )


@pytest.mark.parametrize(
    "lost", ["mail", "send_response", "upload_workout", "schedule_workout"]
)
def test_partial_publication_and_readonly_reconcile_never_replay_writes(
    tmp_path, monkeypatch, capsys, lost
):
    from skills._shared.fit_weekly import publication_ledger

    root, _, grant, provider, http = fixture.setup(tmp_path, monkeypatch)
    if lost == "mail":
        http.fail = "/messages/abc123"
    elif lost == "send_response":
        http.rewrite = False
        request = http.request

        def lost_response(method, url, **kwargs):
            value = request(method, url, **kwargs)
            if url.endswith("/send"):
                raise OSError("public synthetic accepted send response lost")
            return value

        monkeypatch.setattr(http, "request", lost_response)
    else:
        provider.lost = lost
    invoke(
        root,
        monkeypatch,
        capsys,
        "--authorization",
        "authorization.json",
        "weekly",
        "--period-end",
        fixture.END,
        expected=5,
    )
    initial = (len(http.sent), len(provider.workouts), len(provider.calendar))
    http.fail = provider.lost = None
    if lost == "mail":
        assert len(provider.workouts) == len(provider.calendar) == 3
    value = readonly_grant(grant)
    save_grant(root, value)
    args = [x for a in value["publication"]["action_keys"] for x in ("--action-key", a)]
    result = invoke(
        root,
        monkeypatch,
        capsys,
        "--authorization",
        "authorization.json",
        "reconcile",
        "--external",
        *args,
        expected=5 if lost in ("upload_workout", "mail", "send_response") else 0,
    )
    assert (len(http.sent), len(provider.workouts), len(provider.calendar)) == initial
    if lost == "upload_workout":
        creates = [v for k, v in result["actions"].items() if ":create:" in k]
        assert all(v["status"] == "unknown" for v in creates)
    elif lost in ("mail", "send_response"):
        action = f"weekly:{fixture.END}:gmail"
        assert result["status"] == "pending"
        assert result["actions"][action]["mail"]["status"] == "success"
        assert result["actions"][action + ":label"]["status"] == "prepared"
        assert all(
            v["status"] == "success"
            for k, v in result["actions"].items()
            if k not in (action, action + ":label")
        )
    else:
        assert all(v["status"] == "success" for v in result["actions"].values())
    assert all(name != "delete_workout" for name, _ in provider.calls)
    assert sum(url.endswith("/send") for _, url, _ in http.calls) == 1
    before = (len(http.calls), len(provider.calls))
    value["models"] = grant.value()["models"]
    save_grant(root, value)
    invoke(
        root,
        monkeypatch,
        capsys,
        "--authorization",
        "authorization.json",
        "reconcile",
        "--external",
        *args,
        expected=2,
    )
    assert before == (len(http.calls), len(provider.calls))
    assert (
        publication_ledger.status(root, f"weekly:{fixture.END}:gmail")["status"]
        == "success"
    )


def test_late_publication_skips_past_courses_and_keeps_original_selection(
    tmp_path, monkeypatch, capsys
):
    from skills._shared.fit_weekly import publication_ledger

    root, _, _, provider, http = fixture.setup(tmp_path, monkeypatch)
    draft = invoke(
        root,
        monkeypatch,
        capsys,
        "--authorization",
        "authorization.json",
        "weekly",
        "--period-end",
        fixture.END,
        "--phase",
        "draft",
    )
    monkeypatch.setattr(publication_ledger, "utc_now", lambda: "2026-08-14T00:00:00Z")
    result = invoke(
        root,
        monkeypatch,
        capsys,
        "--authorization",
        "authorization.json",
        "weekly",
        "--period-end",
        fixture.END,
        "--phase",
        "publish",
    )
    assert result["publication"]["late"] is True
    assert result["revision_sha256"] == draft["revision_sha256"]
    assert [v["schedule"]["status"] for v in result["publication"]["workouts"]] == [
        "skipped",
        "skipped",
        "success",
    ]
    assert [v["date"] for v in provider.calendar] == ["2026-08-16"]
    bundle = report_artifacts.read_sealed(root, fixture.END)
    assert [d["date"] for d in bundle.plan["days"]] == [
        f"2026-08-{day:02d}" for day in range(10, 17)
    ]
    before = (len(http.calls), len(provider.calls))
    again = invoke(
        root,
        monkeypatch,
        capsys,
        "weekly",
        "--period-end",
        fixture.END,
        "--phase",
        "publish",
    )
    assert (
        again["publication"] == result["publication"]
        and (len(http.calls), len(provider.calls)) == before
    )


def test_model_unknown_capture_restores_without_configuration_or_new_entitlement(
    tmp_path, monkeypatch, capsys
):
    from skills._shared.fit_weekly import command_output, run_reconcile

    root, _, _, provider, http = fixture.setup(tmp_path, monkeypatch)
    parse = command_output.parse_result

    def crash(result, schema, **kwargs):
        if (
            schema.get("properties", {}).get("schema_version", {}).get("const")
            == "fit_running_plan_v1"
        ):
            raise model_job.AdapterInterrupted("public crash after process capture")
        return parse(result, schema, **kwargs)

    monkeypatch.setattr(command_output, "parse_result", crash)
    with pytest.raises(model_job.AdapterInterrupted):
        fixture.cli(
            root,
            monkeypatch,
            "--authorization",
            "authorization.json",
            "weekly",
            "--period-end",
            fixture.END,
        )
    capsys.readouterr()
    monkeypatch.setattr(command_output, "parse_result", parse)
    (root / "model.json").unlink()
    (root / "weekly-goal.md").unlink()
    (root / "config.json").unlink()
    recovered = run_reconcile.local(root)
    assert recovered["weeks"][fixture.END]["plan"]["status"] == "succeeded"
    assert recovered["weeks"][fixture.END]["summary"]["status"] == "not_started"
    assert not provider.workouts and not http.calls


def test_authorization_calendar_and_frozen_grant_rejections_precede_calls(
    tmp_path, monkeypatch, capsys
):
    import asyncio
    import copy

    from skills._shared.fit_weekly import run_weekly

    root, config, grant, provider, http = fixture.setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="before_cutoff"):
        asyncio.run(
            run_weekly.collect(
                config, grant, fixture.END, now=lambda: "2026-08-09T06:59:59Z"
            )
        )
    original = grant.value()
    for change in ("coverage", "as_of", "model", "timeout"):
        value = copy.deepcopy(original)
        if change == "coverage":
            value["sync"]["dates"].pop(0)
        elif change == "as_of":
            value["sync"]["as_of_utc"] = "2026-08-09T06:59:59Z"
        elif change == "model":
            value["models"][0]["command_sha256"] = "f" * 64
        else:
            value["models"][0]["timeout_seconds"] = 0
        save_grant(root, value)
        invoke(
            root,
            monkeypatch,
            capsys,
            "--authorization",
            "authorization.json",
            "weekly",
            "--period-end",
            fixture.END,
            expected=2,
        )
        assert not http.calls
        if change in ("coverage", "as_of"):
            assert not provider.calls
    assert not (
        model_job.capture_path(root, fixture.END, stage="plan").parent
        / "command/process"
    ).exists()
    before = (len(provider.calls), len(http.calls))
    save_grant(root, original)
    invoke(
        root,
        monkeypatch,
        capsys,
        "--authorization",
        "authorization.json",
        "weekly",
        "--period-end",
        fixture.END,
        expected=2,
    )
    assert (len(provider.calls), len(http.calls)) == before


def test_external_reconcile_prepared_zero_services_and_zero_writes(
    tmp_path, monkeypatch, capsys
):
    from skills._shared.fit_weekly import publication

    root, config, grant, provider, http = fixture.setup(tmp_path, monkeypatch)
    draft = invoke(
        root,
        monkeypatch,
        capsys,
        "--authorization",
        "authorization.json",
        "weekly",
        "--period-end",
        fixture.END,
        "--phase",
        "draft",
    )
    publication.prepare_weekly(
        root,
        fixture.END,
        "ai",
        draft["revision_sha256"],
        recipient="owner@example.invalid",
        sender="owner@example.invalid",
        late=False,
    )
    for name in ("model", "gmail", "garmin"):
        config.service_path(name).unlink()
    value = readonly_grant(grant)
    save_grant(root, value)
    before = (len(provider.calls), len(http.calls))
    args = [
        x
        for action in value["publication"]["action_keys"]
        for x in ("--action-key", action)
    ]
    result = invoke(
        root,
        monkeypatch,
        capsys,
        "--authorization",
        "authorization.json",
        "reconcile",
        "--external",
        *args,
        expected=5,
    )
    assert all(v["status"] == "prepared" for v in result["actions"].values())
    assert (len(provider.calls), len(http.calls)) == before


def test_durable_publication_selection_blocks_edit_and_keeps_late_after_crash(
    tmp_path, monkeypatch, capsys
):
    from skills._shared.fit_weekly import (
        publication_ledger,
        report_revisions,
        run_weekly,
    )

    root, _, _, _, _ = fixture.setup(tmp_path, monkeypatch)
    draft = invoke(
        root,
        monkeypatch,
        capsys,
        "--authorization",
        "authorization.json",
        "weekly",
        "--period-end",
        fixture.END,
        "--phase",
        "draft",
    )
    original = report_revisions.read(root, fixture.END, "ai", draft["revision_sha256"])
    run_weekly.record(
        root,
        fixture.END,
        "publication",
        {
            "revision_id": "ai",
            "revision_sha256": draft["revision_sha256"],
            "sender": "owner@example.invalid",
            "recipient": "reader@example.invalid",
            "late": False,
        },
    )
    content = importlib.import_module("m12_report_factory").edited_summary(original)
    with pytest.raises(ValueError, match="period_sealed"):
        report_revisions.edit(
            root,
            fixture.END,
            base_revision_id="ai",
            base_revision_sha256=draft["revision_sha256"],
            revision_id="after-selection",
            target="summary",
            content=content,
        )
    monkeypatch.setattr(publication_ledger, "utc_now", lambda: "2026-08-14T00:00:00Z")
    result = invoke(
        root,
        monkeypatch,
        capsys,
        "--authorization",
        "authorization.json",
        "weekly",
        "--period-end",
        fixture.END,
        "--phase",
        "publish",
    )
    assert result["publication"]["late"] is False
    assert result["revision_sha256"] == draft["revision_sha256"]


@pytest.mark.parametrize("label_state", ["unknown", "prepared"])
def test_weekly_label_state_survives_unauthorized_and_unconfigured_replay(
    tmp_path, monkeypatch, capsys, label_state
):
    from skills._shared.fit_weekly import publication_ledger, run_publication

    root, config, grant, provider, http = fixture.setup(tmp_path, monkeypatch)
    original_request = http.request
    original_label = run_publication.label

    def unavailable_label(config, action, grant, **kwargs):
        if action.endswith(":label"):
            raise ValueError("public synthetic service unavailable")
        return original_label(config, action, grant, **kwargs)

    def lost_modify(method, url, **kwargs):
        if url.endswith("/modify"):
            raise ConnectionError("public synthetic unknown before remote acceptance")
        return original_request(method, url, **kwargs)

    if label_state == "unknown":
        monkeypatch.setattr(http, "request", lost_modify)
    else:
        monkeypatch.setattr(run_publication, "label", unavailable_label)
    first = invoke(
        root,
        monkeypatch,
        capsys,
        "--authorization",
        "authorization.json",
        "weekly",
        "--period-end",
        fixture.END,
        expected=5,
    )
    expected = "unknown" if label_state == "unknown" else "pending"
    action = f"weekly:{fixture.END}:gmail"
    sent = publication_ledger.status(root, action)
    assert sent["status"] == "success"
    assert publication_ledger.status(root, action + ":label")["status"] == label_state
    assert first["status"] == expected
    assert first["publication"]["mail"]["mail"] == sent
    before = (len(http.calls), len(provider.calls))
    captures = {
        stage: model_job.capture_path(root, fixture.END, stage=stage).read_bytes()
        for stage in ("plan", "summary")
    }
    for configured in (True, False):
        if not configured:
            config.service_path("gmail").rename(root / "gmail.saved")
        repeated = invoke(
            root,
            monkeypatch,
            capsys,
            "weekly",
            "--period-end",
            fixture.END,
            expected=5,
        )
        assert repeated["status"] == expected
        mail = repeated["publication"]["mail"]
        assert mail["mail"] == sent and mail["label"]["status"] == label_state
        assert mail["ensure_label"]["status"] == "success"
        assert "schema_version" not in mail
        assert (len(http.calls), len(provider.calls)) == before
        state = invoke(root, monkeypatch, capsys, "status")
        assert state["business"] == {
            "failed": 0,
            "pending": int(label_state == "prepared"),
            "unknown": int(label_state == "unknown"),
        }
    (root / "gmail.saved").rename(config.service_path("gmail"))
    monkeypatch.setattr(http, "request", original_request)
    monkeypatch.setattr(run_publication, "label", original_label)
    value = readonly_grant(grant)
    save_grant(root, value)
    recovered = invoke(
        root,
        monkeypatch,
        capsys,
        "--authorization",
        "authorization.json",
        "reconcile",
        "--external",
        "--action-key",
        action,
        expected=5,
    )
    assert recovered["status"] == expected
    assert all(method == "GET" for method, _, _ in http.calls[before[0] :])
    if label_state == "unknown":
        http.applied_labels = ["Label_synthetic"]
        invoke(
            root,
            monkeypatch,
            capsys,
            "--authorization",
            "authorization.json",
            "reconcile",
            "--external",
            "--action-key",
            action,
        )
    else:
        save_grant(root, grant.value())
        invoke(
            root,
            monkeypatch,
            capsys,
            "--authorization",
            "authorization.json",
            "weekly",
            "--period-end",
            fixture.END,
        )
    writes = sum(method == "POST" for method, _, _ in http.calls)
    before = (len(http.calls), len(provider.calls))
    complete = invoke(root, monkeypatch, capsys, "weekly", "--period-end", fixture.END)
    assert complete["status"] == "complete"
    assert complete["publication"]["mail"]["mail"] == sent
    assert (len(http.calls), len(provider.calls)) == before
    assert sum(url.endswith("/send") for _, url, _ in http.calls) == 1
    assert sum(method == "POST" for method, _, _ in http.calls) == writes
    for stage, capture in captures.items():
        assert (
            model_job.capture_path(root, fixture.END, stage=stage).read_bytes()
            == capture
        )
