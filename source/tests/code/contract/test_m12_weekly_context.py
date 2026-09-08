from __future__ import annotations

import copy
import importlib
import json
import shutil
import sys
import unicodedata
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))
fixture = importlib.import_module("test_m12_weekly_evidence")
legacy_saved = importlib.import_module("test_m12_model_job").legacy_saved


def modules():
    return (
        importlib.import_module("skills._shared.fit_weekly.weekly_context"),
        importlib.import_module("skills._shared.fit_weekly.weekly_history"),
    )


def summary_setup(root, body, business):
    """Reach all-sport input through a real, Host-validated synthetic plan."""
    from skills._shared.fit_weekly import model_job, stage_context, weekly_stages

    end = fixture.END
    planning = stage_context.freeze(root, end, "plan", validate_history=business)
    assert "current_week" not in planning and "history_reports" not in planning
    assert "counts" not in planning and planning["running_history"] == []
    assert planning["goal_snapshot"] == body["goal_snapshot"]
    assert planning["running_activities"] == [
        {
            **{
                key: activity[key]
                for key in (
                    "activity_ref",
                    "fit_sha256",
                    "parser_version",
                    "start_utc",
                    "methods",
                )
            },
            "sessions": [s for s in activity["sessions"] if s["sport"] == "running"],
        }
        for activity in body["current_week"]["activities"]
        if any(s["sport"] == "running" for s in activity["sessions"])
    ]
    plan_output = {"schedule": ["synthetic running day"] * 7}
    plan_adapter = model_job.FakeAdapter(plan_output, [])

    def check_plan(output, payload):
        assert output == plan_output and payload == planning

    def run_plan():
        return model_job.run(
            root,
            end,
            body["scope_sha256"],
            planning,
            {
                "type": "object",
                "required": ["schedule"],
                "additionalProperties": False,
                "properties": {
                    "schedule": {"type": "array", "items": {"type": "string"}}
                },
            },
            plan_adapter,
            stage="plan",
            validate_input=stage_context.validator(
                root, end, "plan", validate_history=business
            ),
            validate_result=check_plan,
        )

    first = run_plan()
    assert first["status"] == "succeeded" and plan_adapter.calls == 1
    assert first["invocation_adapter_calls"] == 1
    binding = weekly_stages.plan_binding(root, end, first)
    summary = stage_context.freeze(
        root,
        end,
        "summary",
        validate_history=business,
        plan=binding,
        validate_plan=check_plan,
    )
    assert summary["current_week"] == body["current_week"]
    assert summary["history_reports"] == body["history_reports"]
    assert summary["goal_snapshot"] == body["goal_snapshot"]
    assert summary["fixed_plan"]["plan"] == plan_output
    validate_summary = stage_context.validator(
        root,
        end,
        "summary",
        validate_history=business,
        plan=binding,
        validate_plan=check_plan,
    )

    def replay_plan():
        assert run_plan() == {**first, "invocation_adapter_calls": 0}
        assert plan_adapter.calls == 1

    return summary, validate_summary, replay_plan


def goal_text():
    from skills._shared.scripts.training_goal_v1 import SECTION_FIELDS

    lines = ["# 我的训练目标"]
    for heading, labels in SECTION_FIELDS:
        lines.append(heading)
        for label in labels:
            value = (
                "3" if label == "训练强度偏好" else "按运动表现安排跑步，保留攀岩时间"
            )
            lines.append(f"- {label}：{value}")
    return "\n".join(lines)


def setup(tmp_path, monkeypatch, activities=None, *, parser_version="fit-summary-1"):
    # This module retains the pre-A-022 frozen-context regression matrix.
    # Active v2 entrypoints and the new admission matrix are exercised separately.
    from skills._shared.fit_weekly import fit_parse

    monkeypatch.setattr(fit_parse, "VERSION", parser_version)
    root, key, sdk, _ = fixture.setup(tmp_path, monkeypatch, activities)
    evidence = fixture.freeze(root, key)
    path = root / "goal.md"
    path.write_text(goal_text())
    path.chmod(0o600)
    return root, evidence, sdk


def end_before(n):
    from skills._shared.fit_weekly.sync_calendar import utc_time

    return (utc_time(fixture.END) - timedelta(weeks=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


def report_schema():
    return {
        "type": "object",
        "required": ["conclusion", "plan", "goal"],
        "additionalProperties": False,
        "properties": {
            "conclusion": {"type": "string"},
            "plan": {"type": "array", "items": {"type": "string"}},
            "goal": {"type": "string"},
        },
    }


def valid_report(body, payload):
    assert payload["synthetic"] is True
    assert set(body) == {"conclusion", "plan", "goal"}
    assert len(body["plan"]) == 7
    assert body["conclusion"] == "完整合成周报：" + payload["period_end_utc"]


def record(root, end, *, archive=True, failed=False, goal_value="公开合成训练目标"):
    from skills._shared.fit_weekly import fit_detail, model_job, storage

    with storage.open_store(root) as db:
        evidence = fit_detail.get(db, "weekly-evidence:" + end)
    members = (
        []
        if evidence is None
        else [
            {k: a[k] for k in ("activity_ref", "fit_sha256")}
            for a in evidence[1]["activities"]
        ]
    )
    scope = fit_detail.freeze_scope(root, end, members)
    output = {
        "conclusion": "完整合成周报：" + end,
        "plan": ["公开合成课程备注" + str(i) for i in range(7)],
        "goal": goal_value,
    }
    adapter = model_job.FakeAdapter({} if failed else output, [])
    result = legacy_saved(
        root,
        end,
        scope["scope_sha256"],
        {"synthetic": True, "period_end_utc": end},
        report_schema(),
        adapter,
        validate_input=lambda v: v["synthetic"] is True,
        validate_result=valid_report,
    )
    if archive:
        modules()[1].archive(root, end, validate_report=valid_report)
    return output, adapter, result


def frozen(root):
    return modules()[0].freeze(root, fixture.END, validate_report=valid_report)


def counts(root):
    from skills._shared.fit_weekly import storage

    with storage.open_store(root) as db:
        return db.execute("SELECT count(*) FROM documents").fetchone()[0]


def test_full_activities_goal_and_no_invented_history(tmp_path, monkeypatch):
    root, evidence, sdk = setup(tmp_path, monkeypatch)
    before = list(sdk.calls)
    body = frozen(root)
    assert body["current_week"]["activities"] == evidence["activities"]
    assert body["current_week"]["activity_sources"] == evidence["activity_sources"]
    assert body["history_reports"] == []
    assert (
        body["goal_snapshot"]["goal"]["training_preferences"]["intensity_preference"]
        == 3
    )
    assert body["provider_calls"] == body["external_actions"] == 0
    assert sdk.calls == before
    text = json.dumps(body)
    for omitted in (
        str(root),
        "goal.md",
        "sync_job_key",
        "relative_path",
        "activity_name",
        "position_lat",
        "87654321",
    ):
        assert omitted not in text
    modules()[0].validator(root, fixture.END, validate_report=valid_report)(body)


@pytest.mark.parametrize("n", [0, 1, 3, 4, 6])
def test_history_newest_four_full_reports_not_row_order_or_current_future(
    tmp_path, monkeypatch, n
):
    root, _, _ = setup(tmp_path, monkeypatch)
    expected = {}
    for offset in reversed(range(1, n + 1)):
        expected[end_before(offset)] = record(root, end_before(offset))[0]
    record(root, fixture.END)
    record(root, end_before(-1))
    history = frozen(root)["history_reports"]
    assert [h["period_end_utc"] for h in history] == sorted(expected, reverse=True)[:4]
    assert [h["report"] for h in history] == [
        expected[h["period_end_utc"]] for h in history
    ]


def test_frozen_goal_history_replay_and_move_without_new_documents(
    tmp_path, monkeypatch
):
    root, _, _ = setup(tmp_path, monkeypatch)
    record(root, end_before(2))
    first = frozen(root)
    (root / "goal.md").write_text(goal_text().replace("运动表现", "近期跑量"))
    record(root, end_before(1))
    before = (root / "trainlab-fit.db").read_bytes()
    assert frozen(root) == first
    assert (root / "trainlab-fit.db").read_bytes() == before
    (root / "goal.md").unlink()
    moved = tmp_path / "moved"
    shutil.move(str(root), moved)
    assert frozen(moved) == first
    assert (moved / "trainlab-fit.db").read_bytes() == before


@pytest.mark.parametrize(
    "state",
    [
        "failed",
        "unfinished",
        "missing_capture",
        "wide_capture",
        "changed_capture",
        "invalid_business",
    ],
)
def test_archive_requires_successful_bound_capture_and_business_check(
    tmp_path, monkeypatch, state
):
    from skills._shared.fit_weekly import model_job

    root, _, _ = setup(tmp_path, monkeypatch)
    end = end_before(1)
    record(root, end, archive=False, failed=state == "failed")
    p = model_job.capture_path(root, end)
    validator = valid_report
    if state == "missing_capture":
        p.unlink()
    elif state == "wide_capture":
        p.chmod(0o644)
    elif state == "changed_capture":
        p.write_text("{}")
    elif state == "unfinished":
        end = end_before(2)
    elif state == "invalid_business":

        def validator(*args):
            raise ValueError("synthetic invalid business")

    before = counts(root)
    with pytest.raises(ValueError, match="weekly_history_invalid"):
        modules()[1].archive(root, end, validate_report=validator)
    assert counts(root) == before


def test_archiving_and_model_replay_do_not_repeat_adapter(tmp_path, monkeypatch):
    root, _, _ = setup(tmp_path, monkeypatch)
    end = end_before(1)
    output, adapter, _ = record(root, end)
    before = (root / "trainlab-fit.db").read_bytes()
    first = modules()[1].archive(root, end, validate_report=valid_report)
    assert first["report"] == output
    assert modules()[1].archive(root, end, validate_report=valid_report) == first
    assert adapter.calls == 1
    assert (root / "trainlab-fit.db").read_bytes() == before


@pytest.mark.parametrize(
    "mode", ["missing", "empty", "wide", "symlink", "hardlink", "malformed"]
)
def test_invalid_goal_stops_before_context_or_model_intent(tmp_path, monkeypatch, mode):
    root, _, _ = setup(tmp_path, monkeypatch)
    p = root / "goal.md"
    if mode == "missing":
        p.unlink()
    elif mode in ("empty", "malformed"):
        p.write_text("" if mode == "empty" else "not a training goal")
    elif mode == "wide":
        p.chmod(0o644)
    else:
        moved = tmp_path / "private-goal"
        p.rename(moved)
        if mode == "symlink":
            p.symlink_to(moved)
        else:
            p.hardlink_to(moved)
    before = counts(root)
    with pytest.raises(ValueError, match="weekly_goal_invalid"):
        frozen(root)
    assert counts(root) == before
    assert not (root / "model-results").exists()


@pytest.mark.parametrize(
    "text",
    [
        "owner@example.com",
        "token=private-secret",
        "Bearer abc123",
        "/private/goal.md",
        r"C:\private\goal.md",
        "latitude=12.3 longitude=45.6",
        "activity_name=private title",
    ],
)
def test_sensitive_goal_never_enters_model_context(tmp_path, monkeypatch, text):
    root, _, _ = setup(tmp_path, monkeypatch)
    (root / "goal.md").write_text(
        goal_text().replace("按运动表现安排跑步，保留攀岩时间", text, 1)
    )
    before = counts(root)
    with pytest.raises(ValueError, match="weekly_goal_invalid"):
        frozen(root)
    assert counts(root) == before


def test_normal_goal_slashes_and_units_remain_business_text(tmp_path, monkeypatch):
    root, _, _ = setup(tmp_path, monkeypatch)
    (root / "goal.md").write_text(
        goal_text().replace(
            "按运动表现安排跑步，保留攀岩时间", "跑步/攀岩，以 min/km 回顾历史配速", 1
        )
    )
    assert (
        "跑步/攀岩"
        in frozen(root)["goal_snapshot"]["goal"]["current_goal"][
            "competition_goal_and_date"
        ]
    )


@pytest.mark.parametrize(
    "change", ["goal", "history", "activity", "extra", "period", "scope"]
)
def test_model_preflight_rejects_changed_context_without_attempt(
    tmp_path, monkeypatch, change
):
    from skills._shared.fit_weekly import model_job

    root, _, _ = setup(tmp_path, monkeypatch)
    record(root, end_before(1))
    body = copy.deepcopy(frozen(root))
    if change == "goal":
        body["goal_snapshot"]["goal"]["current_goal"]["training_focus"] = "changed"
    elif change == "history":
        body["history_reports"][0]["report"]["goal"] = "changed"
    elif change == "activity":
        body["current_week"]["activities"].pop()
    elif change == "period":
        body["current_week"]["period_end_utc"] = end_before(-1)
    elif change == "scope":
        body["scope_sha256"] = "0" * 64
    else:
        body["gps"] = "hidden"
    adapter = model_job.FakeAdapter(
        {"conclusion": "synthetic", "plan": [], "goal": "public"}, []
    )
    with pytest.raises(ValueError, match="model_job_input_invalid"):
        model_job.run(
            root,
            fixture.END,
            body["scope_sha256"],
            body,
            report_schema(),
            adapter,
            stage="plan",
            validate_input=modules()[0].validator(
                root, fixture.END, validate_report=valid_report
            ),
            validate_result=valid_report,
        )
    assert adapter.calls == 0
    assert not model_job.capture_path(root, fixture.END, stage="plan").parent.exists()


def test_frozen_context_sql_failure_retries_locally_without_model(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import storage

    root, _, _ = setup(tmp_path, monkeypatch)
    original = storage.put_document

    def fail(db, kind, key, sha, body):
        if key.startswith("weekly-context:"):
            raise OSError("synthetic sqlite failure")
        return original(db, kind, key, sha, body)

    with monkeypatch.context() as patch:
        patch.setattr(storage, "put_document", fail)
        with pytest.raises(OSError):
            frozen(root)
    assert frozen(root)["history_reports"] == []
    assert not (root / "model-results").exists()


@pytest.mark.parametrize("activities", [[], [("201", 3600, None)]])
def test_zero_activity_and_no_fit_limitations_are_not_rewritten(
    tmp_path, monkeypatch, activities
):
    root, evidence, _ = setup(tmp_path, monkeypatch, activities)
    body = frozen(root)
    assert body["current_week"]["counts"] == evidence["counts"]
    assert body["current_week"]["unplaced_no_fit"] == evidence["unplaced_no_fit"]


def test_frozen_history_missing_receipt_is_not_trusted(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import model_job

    root, _, _ = setup(tmp_path, monkeypatch)
    end = end_before(1)
    record(root, end)
    body = frozen(root)
    model_job.capture_path(root, end).unlink()
    with pytest.raises(ValueError):
        modules()[0].validator(root, fixture.END, validate_report=valid_report)(body)


def test_valid_context_enters_fake_once_and_replays_without_database_increment(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import model_job

    root, _, _ = setup(tmp_path, monkeypatch)
    record(root, end_before(1))
    body = frozen(root)
    output = {
        "conclusion": "本周全部运动的合成结论",
        "running_analysis": "本周跑步的合成分析",
        "goal": "目标快照",
    }
    summary, validate_summary, replay_plan = summary_setup(root, body, valid_report)
    schema = {
        "type": "object",
        "required": ["conclusion", "running_analysis", "goal"],
        "additionalProperties": False,
        "properties": {key: {"type": "string"} for key in output},
    }
    adapter = model_job.FakeAdapter(output, [])

    def result_validator(value, payload):
        assert value == output
        assert payload == summary

    args = (root, fixture.END, body["scope_sha256"], summary, schema, adapter)
    kwargs = {
        "validate_input": validate_summary,
        "validate_result": result_validator,
    }
    first = model_job.run(*args, stage="summary", **kwargs)
    before = (root / "trainlab-fit.db").read_bytes()
    assert first["status"] == "succeeded"
    replay_plan()
    assert (
        model_job.run(*args, stage="summary", **kwargs)["invocation_adapter_calls"] == 0
    )
    assert adapter.calls == 1
    assert (root / "trainlab-fit.db").read_bytes() == before


@pytest.mark.parametrize("change", ["boolean", "raw", "missing_evidence"])
def test_revalidation_preserves_json_types_and_source_binding(
    tmp_path, monkeypatch, change
):
    from skills._shared.fit_weekly import fit_detail, model_job

    root, _, _ = setup(tmp_path, monkeypatch)
    body = frozen(root)
    if change == "boolean":
        body["provider_calls"] = False
    elif change == "raw":
        p = (
            root
            / "fits"
            / (body["current_week"]["activities"][0]["fit_sha256"] + ".fit")
        )
        p.write_bytes(p.read_bytes() + b"corrupt")
    else:
        original = fit_detail.get
        monkeypatch.setattr(
            fit_detail,
            "get",
            lambda db, key: (
                None if key.startswith("weekly-evidence:") else original(db, key)
            ),
        )
    adapter = model_job.FakeAdapter({}, [])
    with pytest.raises(ValueError, match="model_job_input_invalid"):
        model_job.run(
            root,
            fixture.END,
            body["scope_sha256"],
            body,
            report_schema(),
            adapter,
            stage="plan",
            validate_input=modules()[0].validator(
                root, fixture.END, validate_report=valid_report
            ),
            validate_result=valid_report,
        )
    assert adapter.calls == 0
    assert not model_job.capture_path(root, fixture.END, stage="plan").parent.exists()


def test_history_duplicate_revision_or_untrusted_document_rejected(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import storage

    root, _, _ = setup(tmp_path, monkeypatch)
    end = end_before(1)
    record(root, end)
    with storage.open_store(root) as db:
        storage.put_document(
            db,
            "weekly_report",
            "weekly-report:" + end,
            "0" * 64,
            {"report": "untrusted"},
        )
    with pytest.raises(ValueError, match="weekly_history_invalid"):
        frozen(root)
    assert not any(p.name == "prepared.json" for p in root.rglob("*"))


def test_history_sensitive_content_not_transferred_even_if_shape_valid(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import fit_detail, model_job

    root, _, _ = setup(tmp_path, monkeypatch)
    end = end_before(1)
    scope = fit_detail.freeze_scope(root, end, [])
    output = {
        "conclusion": "完整合成周报：" + end,
        "plan": ["备注"] * 7,
        "goal": "owner@example.com",
    }
    adapter = model_job.FakeAdapter(output, [])
    legacy_saved(
        root,
        end,
        scope["scope_sha256"],
        {"synthetic": True, "period_end_utc": end},
        report_schema(),
        adapter,
        validate_input=lambda value: None,
        validate_result=valid_report,
    )
    modules()[1].archive(root, end, validate_report=valid_report)
    before = counts(root)
    with pytest.raises(ValueError, match="weekly_private_text"):
        frozen(root)
    assert counts(root) == before


def test_archive_sql_failure_keeps_model_success_for_local_recovery(
    tmp_path, monkeypatch
):
    from skills._shared.fit_weekly import storage

    root, _, _ = setup(tmp_path, monkeypatch)
    end = end_before(1)
    output, adapter, _ = record(root, end, archive=False)
    original = storage.put_document

    def fail(db, kind, key, sha, body):
        if kind == "weekly_report":
            raise OSError("synthetic archive failure")
        return original(db, kind, key, sha, body)

    with monkeypatch.context() as patch:
        patch.setattr(storage, "put_document", fail)
        with pytest.raises(OSError):
            modules()[1].archive(root, end, validate_report=valid_report)
    assert (
        modules()[1].archive(root, end, validate_report=valid_report)["report"]
        == output
    )
    assert adapter.calls == 1


def test_context_requires_business_validator_even_with_no_history(
    tmp_path, monkeypatch
):
    root, _, _ = setup(tmp_path, monkeypatch)
    before = counts(root)
    for f in (modules()[0].freeze, modules()[0].validator):
        with pytest.raises(ValueError, match="weekly_context_validator_missing"):
            f(root, fixture.END, validate_report=None)
    assert counts(root) == before


@pytest.mark.parametrize("entry", ["goal", "history"])
@pytest.mark.parametrize(
    "text",
    [
        "device_id=synthetic-device-123",
        "device_serial_number: synthetic-device-123",
        "设备编号：synthetic-device-123",
        '{"serialNumber": "synthetic-device-123"}',
        "athlete_id=synthetic-athlete-123",
        "用户ID：synthetic-user-123",
        '{"account_id": "synthetic-account-123"}',
        "file:///private/synthetic/goal.md",
        "FILE://synthetic-host/share/report.md",
        "file:/private/synthetic/goal.md",
        '{"token": "synthetic-secret"}',
        '{"password": "synthetic-secret"}',
        "{'client_secret': 'synthetic-secret'}",
        '{"activity_name": "synthetic-activity"}',
        '{"latitude": 10.0}',
        '{"密码": "synthetic-secret"}',
    ],
)
def test_explicit_identity_and_file_uri_rejected_in_all_free_text(
    tmp_path, monkeypatch, entry, text
):
    from skills._shared.fit_weekly import model_job

    root, _, _ = setup(tmp_path, monkeypatch)
    if entry == "goal":
        (root / "goal.md").write_text(
            goal_text().replace("按运动表现安排跑步，保留攀岩时间", text, 1)
        )
    else:
        record(root, end_before(1), goal_value=text)
    adapter = model_job.FakeAdapter({}, [])
    before = counts(root)
    with pytest.raises(ValueError, match="weekly_goal_invalid|weekly_private_text"):
        body = frozen(root)
        model_job.run(
            root,
            fixture.END,
            body["scope_sha256"],
            body,
            report_schema(),
            adapter,
            stage="plan",
            validate_input=modules()[0].validator(
                root, fixture.END, validate_report=valid_report
            ),
            validate_result=valid_report,
        )
    assert adapter.calls == 0
    assert counts(root) == before
    assert not model_job.capture_path(root, fixture.END, stage="plan").parent.exists()


@pytest.mark.parametrize(
    "text",
    [
        "设备记录的跑步数据",
        "不需要提供设备编号",
        "跑步/攀岩，以 min/km 描述历史",
        "学习 device ID 的含义，不填写具体编号",
    ],
)
def test_identity_topics_without_identifiers_are_not_private_values(
    tmp_path, monkeypatch, text
):
    root, _, _ = setup(tmp_path, monkeypatch)
    (root / "goal.md").write_text(
        goal_text().replace("按运动表现安排跑步，保留攀岩时间", text, 1)
    )
    assert (
        unicodedata.normalize("NFKC", text)
        == frozen(root)["goal_snapshot"]["goal"]["current_goal"][
            "competition_goal_and_date"
        ]
    )


@pytest.mark.parametrize(
    "label",
    [
        "token",
        "password",
        "client_secret",
        "authorization",
        "latitude",
        "activity_name",
        "device_id",
        "serialNumber",
        "设备编号",
        "密码",
    ],
)
def test_private_assignment_grammar_uses_one_rule(label):
    check = modules()[0].check_text
    for separator in (":", "：", "="):
        for opening, closing in (
            ("", ""),
            ('"', '"'),
            ("'", "'"),
            ("“", "”"),
            ("‘", "’"),
        ):
            for space in ("", " ", "\t"):
                text = (
                    f"{opening}{label}{closing}{space}{separator}{space}synthetic-value"
                )
                with pytest.raises(ValueError, match="weekly_private_text"):
                    check(text)


@pytest.mark.parametrize(
    "label",
    [
        "token",
        "access_token",
        "accessToken",
        "refresh_token",
        "refreshToken",
        "api_key",
        "apiKey",
        "client_secret",
        "clientSecret",
        "password",
        "credential",
        "authorization",
        "device_id",
        "latitude",
        "活动名称",
    ],
)
def test_private_keys_keep_their_value_association(label):
    check = modules()[0].check_text
    for value in ("synthetic-value", 0, {"nested": "synthetic-value"}):
        with pytest.raises(ValueError, match="weekly_private_text"):
            check({"observations": [{label: value}]})


def flexible_synthetic_history(root, field, value):
    """Closed synthetic report variants exercise this ledger's callback interface."""
    from skills._shared.fit_weekly import fit_detail, model_job

    end = end_before(1)
    scope = fit_detail.freeze_scope(root, end, [])
    output: dict[str, Any] = {
        "conclusion": "公开合成结论",
        "plan": ["公开合成课程"] * 7,
        "goal": "公开合成目标",
    }
    schema = report_schema()
    if field == "structured":
        output["goal"] = {"notes": [{"access_token": value}]}
        schema["properties"]["goal"] = {
            "type": "object",
            "required": ["notes"],
            "additionalProperties": False,
            "properties": {
                "notes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["access_token"],
                        "additionalProperties": False,
                        "properties": {"access_token": {"type": "string"}},
                    },
                }
            },
        }
    elif field == "plan":
        output["plan"][0] = value
    else:
        output[field] = value
    payload = {"synthetic": True, "period_end_utc": end}

    def business(body, context):
        assert model_job.sha(context) == model_job.sha(payload)
        assert model_job.sha(body) == model_job.sha(output)

    adapter = model_job.FakeAdapter(output, [])
    result = legacy_saved(
        root,
        end,
        scope["scope_sha256"],
        payload,
        schema,
        adapter,
        validate_input=lambda v: v == payload,
        validate_result=business,
    )
    assert result["status"] == "succeeded"
    modules()[1].archive(root, end, validate_report=business)
    return business, output, adapter


@pytest.mark.parametrize(
    "entry", ["goal", "history_goal", "history_conclusion", "history_plan"]
)
@pytest.mark.parametrize(
    "text",
    [
        "token：synthetic-value",
        "latitude：10.0 longitude：20.0",
        "“token”: synthetic-value",
        "‘password’：synthetic-value",
        "access_token=synthetic-value",
        "refreshToken: synthetic-value",
        '{"apiKey"："synthetic-value"}',
        "{“clientSecret”: “synthetic-value”}",
    ],
)
def test_common_private_forms_stop_every_entry_before_model(
    tmp_path, monkeypatch, entry, text
):
    from skills._shared.fit_weekly import model_job

    root, _, _ = setup(tmp_path, monkeypatch)
    business = valid_report
    if entry == "goal":
        (root / "goal.md").write_text(
            goal_text().replace("按运动表现安排跑步，保留攀岩时间", text, 1)
        )
    else:
        business, _, _ = flexible_synthetic_history(
            root, entry.removeprefix("history_"), text
        )
    before = counts(root)
    adapter = model_job.FakeAdapter({}, [])
    context = modules()[0]
    with pytest.raises(ValueError, match="weekly_goal_invalid|weekly_private_text"):
        body = context.freeze(root, fixture.END, validate_report=business)
        model_job.run(
            root,
            fixture.END,
            body["scope_sha256"],
            body,
            report_schema(),
            adapter,
            stage="plan",
            validate_input=context.validator(
                root, fixture.END, validate_report=business
            ),
            validate_result=business,
        )
    assert adapter.calls == 0
    assert counts(root) == before
    assert not model_job.capture_path(root, fixture.END, stage="plan").parent.exists()


def test_structured_private_history_stops_before_current_intent(tmp_path, monkeypatch):
    from skills._shared.fit_weekly import model_job

    root, _, _ = setup(tmp_path, monkeypatch)
    business, _, _ = flexible_synthetic_history(root, "structured", "synthetic-value")
    before = counts(root)
    with pytest.raises(ValueError, match="weekly_private_text"):
        modules()[0].freeze(root, fixture.END, validate_report=business)
    assert counts(root) == before
    assert not model_job.capture_path(root, fixture.END, stage="plan").parent.exists()


@pytest.mark.parametrize("entry", ["goal", "history"])
@pytest.mark.parametrize("stage", ["replay", "validator", "model"])
def test_old_frozen_private_text_must_be_rechecked(tmp_path, monkeypatch, entry, stage):
    from skills._shared.fit_weekly import model_job

    root, _, _ = setup(tmp_path, monkeypatch)
    context = modules()[0]
    if entry == "goal":
        (root / "goal.md").write_text(
            goal_text().replace(
                "按运动表现安排跑步，保留攀岩时间", "refresh_token：synthetic-value", 1
            )
        )
    else:
        record(root, end_before(1), goal_value="refresh_token：synthetic-value")
    # Construct only a synthetic snapshot accepted by an earlier checker version.
    with monkeypatch.context() as patch:
        patch.setattr(context, "check_text", lambda _, **_policy: None)
        body = frozen(root)
    before = counts(root)
    adapter = model_job.FakeAdapter({}, [])
    validator = context.validator(root, fixture.END, validate_report=valid_report)
    with pytest.raises(
        ValueError, match="weekly_context_invalid|model_job_input_invalid"
    ):
        if stage == "replay":
            frozen(root)
        elif stage == "validator":
            validator(body)
        else:
            model_job.run(
                root,
                fixture.END,
                body["scope_sha256"],
                body,
                report_schema(),
                adapter,
                stage="plan",
                validate_input=validator,
                validate_result=valid_report,
            )
    assert adapter.calls == 0
    assert counts(root) == before
    assert not model_job.capture_path(root, fixture.END, stage="plan").parent.exists()


@pytest.mark.parametrize(
    "text",
    [
        "跑步/攀岩，以 min/km、km/h 和 m/s 描述历史；RPE 3/5",
        "步频 170 次/分，配速 5:30 min/km，强度 3/5",
        "学习 device ID 的含义，不填写具体编号；不需要提供密码",
    ],
)
def test_normal_full_history_preserved_and_model_replay_has_no_increment(
    tmp_path, monkeypatch, text
):
    from skills._shared.fit_weekly import model_job

    root, _, _ = setup(tmp_path, monkeypatch)
    _, _, _ = record(root, end_before(1), goal_value=text)
    body = frozen(root)
    original = copy.deepcopy(body)
    assert body["history_reports"][0]["report"]["goal"] == text
    summary, validate_summary, replay_plan = summary_setup(root, body, valid_report)
    output = {"ok": True}
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean", "const": True}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    adapter = model_job.FakeAdapter(output, [])

    def business(result, context):
        assert result == output
        assert context == summary

    def run():
        replay_plan()
        return model_job.run(
            root,
            fixture.END,
            body["scope_sha256"],
            summary,
            schema,
            adapter,
            stage="summary",
            validate_input=validate_summary,
            validate_result=business,
        )

    assert run()["status"] == "succeeded"
    before = counts(root)
    assert run()["status"] == "succeeded"
    assert adapter.calls == 1
    assert counts(root) == before
    assert frozen(root) == original


def test_private_text_scan_does_not_rewrite_valid_structures():
    value = {
        "activity_ref": "9001",
        "report_sha256": "a" * 64,
        "scope_sha256": "b" * 64,
        "notes": [
            "token",
            "device ID",
            "apiKey",
            "min/km",
            "RPE 3/5",
            "５：３０ min/km",
        ],
    }
    original = copy.deepcopy(value)
    modules()[0].check_text(value)
    assert value == original
