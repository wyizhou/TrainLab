from __future__ import annotations

import copy
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from trainlab.context import build_runtime_input
from trainlab.db import connect
from trainlab.mail import FakeGmail
from trainlab.runner import _prompt, _validate_result, codex_command, run_analysis


def test_codex_adapter_is_stateless_schema_bound_and_model_free(settings):
    codex = codex_command(settings, settings.path("state_directory") / "result.json")
    assert "--ephemeral" in codex and "--output-schema" in codex
    assert "--model" not in codex and "-m" not in codex
    assert "--skip-git-repo-check" in codex
    assert 'model_reasoning_effort="medium"' in codex
    assert "mcp_servers.gmail.required=true" in codex
    assert 'mcp_servers.gmail.tools.send_html_self.approval_mode="approve"' in codex
    enabled_tools = codex[codex.index("--config", codex.index("mcp_servers.gmail.required=true") + 1) + 1]
    assert "send_html_self" in enabled_tools and "get_self" in enabled_tools


def test_codex_output_schema_uses_strict_object_contract(settings):
    schema = json.loads((settings.root / "harness" / "schemas" / "runtime_result.schema.json").read_text())

    def check(node):
        if isinstance(node, dict):
            node_type = node.get("type")
            if node_type == "object" or isinstance(node_type, list) and "object" in node_type:
                assert node.get("additionalProperties") is False
                assert set(node.get("required", [])) == set(node.get("properties", {}))
            if "const" in node or "enum" in node:
                assert "type" in node
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    check(schema)


def test_runtime_prompt_embeds_only_shared_and_runtime_harness(settings):
    connection = connect(settings.database_path)
    payload = build_runtime_input(
        settings,
        connection,
        slot="morning",
        as_of=datetime(2026, 7, 20, 9, 0, tzinfo=ZoneInfo("Asia/Singapore")),
    )
    prompt = _prompt(settings, payload)
    assert "<shared-harness>" in prompt and "<runtime-harness>" in prompt
    assert "Development harness" not in prompt
    assert str(settings.database_path) not in prompt
    assert "course_type MUST be exactly 轻松跑" in prompt
    assert "MUST attempt gmail/get_self" in prompt
    assert prompt.rfind("MUST attempt gmail/get_self") > prompt.rfind("</runtime-input>")
    assert "explicitly authorized this scheduled send to authenticated self" in prompt
    connection.close()


def test_fake_gmail_html_label_run_id_and_idempotency(settings):
    connection = connect(settings.database_path)
    moment = datetime(2026, 7, 20, 9, 0, tzinfo=ZoneInfo("Asia/Singapore"))
    first = run_analysis(settings, connection, slot="morning", as_of=moment)
    second = run_analysis(settings, connection, slot="morning", as_of=moment)
    assert first == second
    assert first["mail"]["label"] == "TrainLab"
    state = FakeGmail(settings, connection)._load()
    matching = [item for item in state["messages"] if item.get("headers", {}).get("X-TrainLab-Run-ID") == first["run_id"]]
    assert len(matching) == 1
    assert matching[0]["plain_text"].strip()
    assert "style=" in matching[0]["html"]
    assert first["report_audit"]["primary_training_count"] == 1
    assert first["report_audit"]["running_plan"]["course_type"] == "轻松跑"
    assert first["report_audit"]["heart_rate_target_used"] is False
    assert first["report_audit"]["running_plan"]["heart_rate_target"] is None
    connection.close()


def test_failed_result_mislabeled_as_sent_does_not_poison_run_id(settings):
    connection = connect(settings.database_path)
    moment = datetime(2026, 7, 20, 20, 0, tzinfo=ZoneInfo("Asia/Singapore"))
    payload = build_runtime_input(settings, connection, slot="evening", as_of=moment)
    failed = {
        "schema_version": 1,
        "run_id": payload["run"]["run_id"],
        "status": "failed",
        "mail": {"message_id": None, "thread_id": None, "label": "TrainLab", "recipient": "self"},
        "report_audit": {
            "primary_training": None,
            "primary_training_count": 0,
            "running_plan": None,
            "climbing_text": None,
            "strength_items": [],
            "strength_stop_conditions": None,
            "technical_review_activity_ids": [],
            "heart_rate_target_used": False,
            "body_in_stdout": False,
        },
        "processed_feedback": [],
        "fact_updates": [],
        "compression_summaries": [],
        "warnings": ["simulated failure"],
    }
    connection.execute(
        """INSERT INTO analysis_runs(
               run_id, slot, scheduled_local_date, scheduled_local_time, started_at_utc, runner, status, result_json
           ) VALUES(?,?,?,?,?,?,?,?)""",
        (
            payload["run"]["run_id"],
            "evening",
            "2026-07-20",
            "20:00",
            "2026-07-20T12:00:00Z",
            "codex",
            "sent",
            json.dumps(failed),
        ),
    )
    connection.commit()

    result = run_analysis(settings, connection, slot="evening", as_of=moment)

    assert result["status"] == "sent"
    assert connection.execute("SELECT status FROM analysis_runs WHERE run_id=?", (result["run_id"],)).fetchone()[0] == "sent"
    connection.close()


def test_host_rejects_locked_or_excess_zone_5_prescription(settings):
    connection = connect(settings.database_path)
    moment = datetime(2026, 7, 22, 9, 0, tzinfo=ZoneInfo("Asia/Singapore"))
    result = run_analysis(settings, connection, slot="morning", as_of=moment)
    payload = build_runtime_input(settings, connection, slot="morning", as_of=moment)
    payload["policy"]["heart_rate_intensity"]["estimate"] = {
        "usable_for_prescription": True,
        "zones": {"zone_1": {}, "zone_2": {}, "zone_3": {}, "zone_4": {}, "zone_5": {}},
        "zone_5_unlocked": False,
    }
    candidate = copy.deepcopy(result)
    candidate["report_audit"]["heart_rate_target_used"] = True
    candidate["report_audit"]["running_plan"].update(
        {
            "course_type": "短间歇跑",
            "target_zone": "zone_5",
            "prescribed_rpe": 9,
            "work_intervals": {
                "repetitions": 4,
                "work_seconds": 60,
                "recovery_seconds": 120,
                "recovery_zone": "zone_1",
                "total_work_seconds": 240,
            },
            "heart_rate_target": "host-zone-5",
        }
    )
    with pytest.raises(ValueError, match="still locked"):
        _validate_result(settings, candidate, payload["run"]["run_id"], payload)

    payload["policy"]["heart_rate_intensity"]["estimate"]["zone_5_unlocked"] = True
    _validate_result(settings, candidate, payload["run"]["run_id"], payload)
    candidate["report_audit"]["running_plan"]["work_intervals"].update(
        {"repetitions": 5, "total_work_seconds": 300}
    )
    with pytest.raises(ValueError, match="currently authorized dose"):
        _validate_result(settings, candidate, payload["run"]["run_id"], payload)
    connection.close()


def test_host_enforces_movement_only_strength_session_and_resolved_links(settings):
    connection = connect(settings.database_path)
    moment = datetime(2026, 7, 23, 9, 0, tzinfo=ZoneInfo("Asia/Singapore"))
    result = run_analysis(settings, connection, slot="morning", as_of=moment)
    selected = ["goblet_squat", "romanian_deadlift", "pull_up", "dumbbell_floor_press", "pallof_press"]
    payload = build_runtime_input(settings, connection, slot="morning", as_of=moment)
    catalog = {item["key"]: item for item in payload["exercise_catalog"]}
    candidate = copy.deepcopy(result)
    candidate["report_audit"].update(
        {
            "primary_training": "strength_training",
            "primary_training_count": 1,
            "running_plan": None,
            "climbing_text": None,
            "heart_rate_target_used": False,
            "strength_stop_conditions": "出现疼痛、胸部不适、眩晕或异常气短时立即停止。",
            "strength_items": [],
        }
    )
    for exercise in selected:
        candidate["report_audit"]["strength_items"].append(
            {
                "exercise": exercise,
                "youtube_url": catalog[exercise]["resolved_youtube"]["url"],
                "youtube_kind": catalog[exercise]["resolved_youtube"]["kind"],
            }
        )
    _validate_result(settings, candidate, payload["run"]["run_id"], payload)
    candidate["report_audit"]["strength_items"][0]["weight_kg"] = 20
    with pytest.raises(Exception, match="Additional properties are not allowed"):
        _validate_result(settings, candidate, payload["run"]["run_id"], payload)
    connection.close()


def test_host_keeps_climbing_recommendation_brief_and_recovery_based(settings):
    connection = connect(settings.database_path)
    moment = datetime(2026, 7, 24, 9, 0, tzinfo=ZoneInfo("Asia/Singapore"))
    result = run_analysis(settings, connection, slot="morning", as_of=moment)
    payload = build_runtime_input(settings, connection, slot="morning", as_of=moment)
    candidate = copy.deepcopy(result)
    candidate["report_audit"].update(
        {
            "primary_training": "climbing",
            "primary_training_count": 1,
            "running_plan": None,
            "climbing_text": "今日攀岩。前臂、背部、肩部和核心恢复正常，可以安排。",
            "strength_items": [],
            "strength_stop_conditions": None,
            "heart_rate_target_used": False,
        }
    )
    _validate_result(settings, candidate, payload["run"]["run_id"], payload)
    candidate["report_audit"]["climbing_text"] = "今日攀岩。前臂、背部、肩部和核心恢复正常，安排30分钟。"
    with pytest.raises(ValueError, match="forbidden duration"):
        _validate_result(settings, candidate, payload["run"]["run_id"], payload)
    connection.close()


def test_labeled_thread_reply_is_deduplicated_and_recorded_by_reply_date(settings):
    connection = connect(settings.database_path)
    mailer = FakeGmail(settings, connection)
    first = run_analysis(
        settings,
        connection,
        slot="evening",
        as_of=datetime(2026, 7, 20, 20, 0, tzinfo=ZoneInfo("Asia/Singapore")),
    )
    mailer.inject_reply(
        thread_id=first["mail"]["thread_id"],
        body_text="今天完成了力量训练，肩膀感觉酸。",
        received_at_utc="2026-07-20T16:30:00Z",
    )
    result = run_analysis(
        settings,
        connection,
        slot="morning",
        as_of=datetime(2026, 7, 21, 9, 0, tzinfo=ZoneInfo("Asia/Singapore")),
    )
    assert len(result["processed_feedback"]) == 1
    row = connection.execute("SELECT reply_local_date, processed_at_utc FROM feedback_messages").fetchone()
    assert row["reply_local_date"] == "2026-07-21"
    assert row["processed_at_utc"]
    assert connection.execute("SELECT COUNT(*) FROM user_facts").fetchone()[0] >= 2
    rerun = run_analysis(settings, connection, slot="morning", as_of=datetime(2026, 7, 21, 9, 0, tzinfo=ZoneInfo("Asia/Singapore")))
    assert rerun == result
    assert connection.execute("SELECT COUNT(*) FROM feedback_messages").fetchone()[0] == 1
    connection.close()
