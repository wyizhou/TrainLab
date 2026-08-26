from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

SOURCE = Path(__file__).resolve().parents[3]


def _load(name: str, relative: str) -> Any:
    path = SOURCE / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


VIEW = _load(
    "trainlab_email_view_v2_test",
    "skills/training-report-publisher/scripts/email_view.py",
)
RENDER = _load(
    "trainlab_email_render_v2_test",
    "skills/training-report-publisher/scripts/render_email_v2.py",
)


def _daily_payload(
    *, safety: str = "ready", status: str = "succeeded"
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "daily_ai_result_v1",
        "status": status,
        "error_code": None if status == "succeeded" else "daily_sleep_evidence_missing",
        "report_date": "2026-08-21",
        "review_date": "2026-08-20",
        "sleep_wake_date": "2026-08-21",
        "safety": safety if status == "succeeded" else "blocked",
        "summary": "恢复平稳，可以按计划训练。",
        "bounded_metrics": [
            {
                "name": "main_sleep_duration",
                "value": 7.5,
                "unit": "hours",
                "evidence_ref": 101,
            },
            {
                "name": "resting_heart_rate",
                "value": 48,
                "unit": "bpm",
                "evidence_ref": 102,
            },
            {
                "name": "last_night_average_hrv",
                "value": 61,
                "unit": "ms",
                "evidence_ref": 103,
            },
        ],
        "stop_conditions": ["胸痛、眩晕或异常气短时停止。"],
        "evidence_refs": [
            {"raw_file_id": 101, "sha256": "a" * 64, "claim": "主睡眠"},
            {"raw_file_id": 102, "sha256": "b" * 64, "claim": "静息心率"},
            {"raw_file_id": 103, "sha256": "c" * 64, "claim": "HRV"},
            {"raw_file_id": 104, "sha256": "d" * 64, "claim": "跑步活动"},
        ],
        "recent_trend_sha256": "e" * 64,
        "today_course": {"name": "不得直接采用的宽松课程"},
        "provider_calls": 0,
    }
    if status == "blocked":
        payload.pop("bounded_metrics")
        payload.pop("stop_conditions")
    return payload


def _daily_context() -> dict[str, Any]:
    return {
        "schema_version": "daily_ai_context_v1",
        "status": "ready",
        "report_date": "2026-08-21",
        "review_date": "2026-08-20",
        "sleep_wake_date": "2026-08-21",
        "health": [
            {
                "raw_file_id": 101,
                "sha256": "a" * 64,
                "resource": "sleep",
                "data_date": "2026-08-21",
                "metrics": {
                    "resource": "sleep",
                    "duration_seconds": 27000,
                    "sleep_start": "2026-08-20T16:00:00Z",
                    "sleep_end": "2026-08-20T23:30:00Z",
                    "sleep_wake_date": "2026-08-21",
                    "completeness": "complete",
                },
            },
            {
                "raw_file_id": 102,
                "sha256": "b" * 64,
                "resource": "rhr",
                "data_date": "2026-08-20",
                "metrics": {"resource": "rhr", "resting_heart_rate_bpm": 48},
            },
            {
                "raw_file_id": 103,
                "sha256": "c" * 64,
                "resource": "hrv",
                "data_date": "2026-08-20",
                "metrics": {
                    "resource": "hrv",
                    "last_night_average": 61,
                    "weekly_average": 59,
                },
            },
        ],
        "activities": [
            {
                "schema_version": "activity_overview_v1",
                "status": "ready",
                "activity_inventory_id": 7,
                "raw_file_id": 104,
                "raw_sha256": "d" * 64,
                "data_date": "2026-08-20",
                "format": "fit",
                "summary": {
                    "activity_kind": "running",
                    "distance_km": 8.2,
                    "duration_seconds": 3020,
                    "lap_count": 3,
                },
                "sequence_resolution_seconds": 30,
                "sequence": [
                    {
                        "offset_seconds": 0,
                        "sample_count": 30,
                        "metrics": {"heart_rate_bpm": 118},
                    },
                    {
                        "offset_seconds": 30,
                        "sample_count": 30,
                        "metrics": {"heart_rate_bpm": 128},
                    },
                    {
                        "offset_seconds": 60,
                        "sample_count": 30,
                        "metrics": {"heart_rate_bpm": 136},
                    },
                ],
                "gps_included": False,
                "provider_calls": 0,
            }
        ],
        "recent_trend": {
            "schema_version": "recent_trend_v1",
            "days_available": 12,
            "sleep": {
                "average_hours": 7.2,
                "insufficient_days": 2,
                "consecutive_insufficient_days": 0,
            },
            "recovery": {
                "caution_days": 1,
                "rhr_average": 49.2,
                "rhr_change": -1.0,
                "hrv_average": 58.4,
                "hrv_change": 2.0,
            },
            "running": {"distance_km": 30.5, "activity_count": 4, "activity_days": 4},
            "data_gaps": [],
            "sha256": "e" * 64,
        },
        "recent_health_metrics": {
            "schema_version": "recent_health_metrics_v1",
            "status": "ready",
            "report_date": "2026-08-21",
            "review_date": "2026-08-20",
            "metrics": {
                "vo2_max": {
                    "resource": "max_metrics",
                    "status": "ready",
                    "value": 51.0,
                    "unit": "ml/kg/min",
                    "observed_date": "2026-08-18",
                    "age_days": 3,
                    "selection_kind": "latest_prior",
                    "lookback_days": 30,
                    "raw_file_id": 105,
                    "sha256": "f" * 64,
                },
                "weight": {
                    "resource": "weigh_ins",
                    "status": "ready",
                    "value": 70.3,
                    "unit": "kg",
                    "observed_date": "2026-08-20",
                    "age_days": 1,
                    "selection_kind": "exact_date",
                    "lookback_days": 14,
                    "raw_file_id": 106,
                    "sha256": "1" * 64,
                },
            },
            "provider_calls": 0,
        },
        "errors": [],
        "provider_calls": 0,
    }


def _plan() -> dict[str, Any]:
    return {
        "schema_version": "training_plan_v1",
        "status": "succeeded",
        "progression_rule": "hold",
        "progression_dimension": "none",
        "provider_calls": 0,
        "items": [
            {
                "date": f"2026-08-{day:02d}",
                "activity_kind": "rest" if day != 21 else "running",
                "name": "休息" if day != 21 else "轻松跑",
                "purpose": "恢复" if day != 21 else "维持有氧",
                "load_level": "low",
                "garmin_mapping_status": "unsupported_skip"
                if day != 21
                else "candidate",
                **({"duration_minutes": 45} if day == 21 else {}),
                "rpe": 2 if day != 21 else 4,
                "downgrade_rule": "疲劳则休息",
                "stop_conditions": ["疼痛时停止"],
            }
            for day in range(19, 26)
        ],
    }


def test_daily_view_uses_explicit_context_and_validated_course_only() -> None:
    view = VIEW.build_daily_view(_daily_payload(), _daily_context(), _plan())
    assert view["schema_version"] == "daily_email_view_v1"
    assert view["title"] == "TrainLab · 每日训练简报 · 2026-08-21"
    assert view["status"] == "ready"
    assert view["today_course"]["name"] == "轻松跑"
    assert view["metrics"]["sleep"]["value"] == "7小时30分"
    assert view["metrics"]["rhr"]["value"] == "48 bpm"
    assert view["metrics"]["hrv"]["value"] == "61 ms"
    assert view["metrics"]["vo2_max"] == {
        "key": "vo2_max",
        "label": "VO₂ Max",
        "value": "51 ml/kg/min",
        "missing": False,
        "detail": "更新于 2026-08-18",
        "source_refs": [105],
    }
    assert view["metrics"]["weight"]["value"] == "70.3 kg"
    assert view["metrics"]["weight"]["detail"] == "更新于 2026-08-20"
    assert view["activities"][0]["distance"] == "8.2 km"
    assert view["charts"][0]["role"] == "daily_activity_heart_rate"
    assert view["charts"][0]["points"][0] == {"x": 0, "y": 118.0}
    assert "heart_rate_zones" not in view
    assert "sleep_stages" not in view
    assert "不得直接采用" not in json.dumps(view, ensure_ascii=False)


def test_daily_view_does_not_backfill_other_health_metrics() -> None:
    context = _daily_context()
    context["health"] = [
        item for item in context["health"] if item["resource"] == "sleep"
    ]
    view = VIEW.build_daily_view(_daily_payload(), context, _plan())
    assert view["metrics"]["rhr"]["missing"] is True
    assert view["metrics"]["hrv"]["missing"] is True
    assert view["metrics"]["vo2_max"]["value"] == "51 ml/kg/min"
    assert view["metrics"]["weight"]["value"] == "70.3 kg"


def test_daily_view_recent_health_does_not_mutate_ai_result() -> None:
    payload = _daily_payload()
    before = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    VIEW.build_daily_view(payload, _daily_context(), _plan())
    assert json.dumps(payload, ensure_ascii=False, sort_keys=True) == before


def test_daily_plain_text_includes_recent_health_observed_dates() -> None:
    view = VIEW.build_daily_view(_daily_payload(), _daily_context(), _plan())
    text = RENDER.render_email(view).payload["text"]
    assert "VO₂ Max：51 ml/kg/min｜更新于 2026-08-18" in text
    assert "体重：70.3 kg｜更新于 2026-08-20" in text
    assert "主睡眠：7小时30分\n" in text
    assert "主睡眠：7小时30分｜" not in text
    assert "静息心率：48 bpm｜" not in text
    assert "HRV：61 ms｜" not in text


def test_course_free_text_safety_rules_are_not_reader_visible() -> None:
    plan = _plan()
    course = next(item for item in plan["items"] if item["date"] == "2026-08-21")
    course["downgrade_rule"] = "sentinel-course-downgrade"
    course["stop_conditions"] = ["sentinel-course-stop"]
    view = VIEW.build_daily_view(_daily_payload(), _daily_context(), plan)
    rendered = RENDER.render_email(view)
    visible = rendered.payload["html"] + rendered.payload["text"]
    assert "sentinel-course-downgrade" not in visible
    assert "sentinel-course-stop" not in visible
    assert (
        view["today_course"]["downgrade_rule"] == "恢复不足或状态明显变差时，改为休息。"
    )


def test_daily_course_is_hidden_without_unique_validated_same_date_item() -> None:
    plan = _plan()
    plan["items"].append(dict(plan["items"][2]))
    view = VIEW.build_daily_view(_daily_payload(), _daily_context(), plan)
    assert view["today_course"] is None
    assert view["course_notice"] == "今日未安排已验证课程"


def test_daily_displayed_activity_adds_host_evidence_reference() -> None:
    payload = _daily_payload()
    payload["evidence_refs"] = payload["evidence_refs"][:-1]
    view = VIEW.build_daily_view(payload, _daily_context(), _plan())
    host_ref = next(item for item in view["evidence"]["refs"] if item["id"] == 104)
    assert host_ref["sha256"] == "d" * 64
    assert host_ref["claim"] == "跑步活动证据"


def test_daily_missing_health_climbing_and_rest_are_honest() -> None:
    context = _daily_context()
    context["health"] = [context["health"][0]]
    context["activities"][0]["summary"] = {
        "activity_kind": "climbing",
        "duration_seconds": 5400,
        "lap_count": 0,
    }
    context["activities"][0]["sequence"] = []
    plan = _plan()
    course = next(item for item in plan["items"] if item["date"] == "2026-08-21")
    course.update(
        {
            "activity_kind": "rest",
            "name": "休息",
            "purpose": "恢复",
            "garmin_mapping_status": "unsupported_skip",
            "rpe": 2,
        }
    )
    course.pop("duration_minutes")
    view = VIEW.build_daily_view(_daily_payload(), context, plan)
    assert view["metrics"]["rhr"]["value"] == "暂无数据"
    assert view["metrics"]["rhr"]["missing"] is True
    assert view["activities"][0]["label"] == "攀岩"
    assert view["activities"][0]["distance"] is None
    assert view["today_course"]["activity_kind"] == "rest"
    assert view["charts"] == []


def test_activity_label_understands_garmin_climbing_variants() -> None:
    context = _daily_context()
    context["activities"][0]["summary"]["activity_kind"] = "indoor_bouldering"
    view = VIEW.build_daily_view(_daily_payload(), context, _plan())
    assert view["activities"][0]["label"] == "攀岩"


def test_blocked_daily_hides_course_and_charts_but_keeps_error_and_evidence() -> None:
    payload = _daily_payload(status="blocked")
    context = _daily_context()
    context["status"] = "blocked"
    context["errors"] = ["daily_sleep_evidence_missing"]
    view = VIEW.build_daily_view(payload, context, _plan())
    assert view["status"] == "blocked"
    assert view["error_code"] == "daily_sleep_evidence_missing"
    assert view["today_course"] is None
    assert view["charts"] == []
    assert view["evidence"]["refs"]
    rendered = RENDER.render_email(view)
    assert "daily_sleep_evidence_missing" not in rendered.payload["html"]
    assert "错误代码" not in rendered.payload["html"]
    assert "阻断原因：</strong>主睡眠证据缺失" in rendered.payload["html"]


def test_renderer_is_readable_escaped_bounded_and_deterministic() -> None:
    payload = _daily_payload()
    payload["summary"] = "<img src=x onerror=alert(1)> 今天状态不错"
    view = VIEW.build_daily_view(payload, _daily_context(), _plan())
    first = RENDER.render_email(view)
    second = RENDER.render_email(view)
    persisted = json.loads(json.dumps(view, ensure_ascii=False, sort_keys=True))
    restored = RENDER.render_email(persisted)
    assert first.payload == second.payload
    assert first.payload == restored.payload
    assert [item.data for item in first.assets] == [item.data for item in second.assets]
    html = first.payload["html"]
    assert len(html.encode("utf-8")) <= 80 * 1024
    assert html.count("<h1") == 1
    assert html.count("<title>") == 1
    assert f"<title>{first.payload['subject']}</title>" in html
    assert first.payload["subject"] in html
    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" not in html
    assert "恢复信号稳定" in html
    assert "bounded_metrics" not in html
    assert "evidence_ref" not in html
    assert "a" * 64 not in html
    assert "来源 101" not in html
    assert "完整 ID 与哈希保存在私有验证记录中" in html
    assert "@media" in html and "max-width:375px" in html
    assert "width:100%!important;box-sizing:border-box!important" in html
    assert ".metric-grid tbody,.metric-grid tr{display:block!important" in html
    assert "prefers-color-scheme:dark" in html
    assert 'role="presentation"' in html
    assert "cid:" in html
    assert first.assets[0].width_px == 1248
    assert first.assets[0].height_px > 0
    assert first.payload["asset_manifest"]["assets"][0]["byte_size"] > 0
    assert first.assets[0].data.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize(
    "leak",
    [
        "raw_file_id=101",
        "sha256=" + "a" * 64,
        "bounded_metrics",
        "evidence_ref=101",
        "review_date / report_date",
        "主睡眠 24506秒",
    ],
)
def test_ai_prose_cannot_leak_engineering_fields_to_reader(leak: str) -> None:
    payload = _daily_payload()
    payload["summary"] = f"AI 原始摘要 {leak}"
    payload["evidence_refs"][0]["claim"] = f"AI 原始证据 {leak}"
    payload["stop_conditions"][0] = f"AI 原始停止条件 {leak}"
    view = VIEW.build_daily_view(payload, _daily_context(), _plan())
    rendered = RENDER.render_email(view)
    visible = rendered.payload["html"] + rendered.payload["text"]
    assert leak not in visible
    assert "AI 原始摘要" not in visible
    assert "AI 原始证据" not in visible
    assert "AI 原始停止条件" not in visible
    assert view["evidence"]["refs"][0]["claim"] == "主睡眠证据"


@pytest.mark.parametrize(
    "leak",
    ["raw_file_id", "sha256", "bounded_metrics", "review_date", "report_date"],
)
def test_renderer_rejects_engineering_tokens_in_mutated_visible_view(leak: str) -> None:
    view = VIEW.build_daily_view(_daily_payload(), _daily_context(), _plan())
    view["summary"] = leak
    with pytest.raises(
        RENDER.EmailRenderError, match="email_engineering_content_forbidden"
    ):
        RENDER.render_email(view)


@pytest.mark.parametrize(
    "private_value",
    [
        "latitude",
        "longitude",
        "GPS route",
        "私人路线",
        "source/state/trainlab.db",
        "file:///private/tmp/a",
        "/Users/person/private.txt",
        "password",
        "api_key",
        "Bearer credential",
        "https://example.com/private",
    ],
)
def test_renderer_rejects_private_or_location_content(private_value: str) -> None:
    view = VIEW.build_daily_view(_daily_payload(), _daily_context(), _plan())
    view["summary"] = private_value
    with pytest.raises(
        RENDER.EmailRenderError, match="email_private_content_forbidden"
    ):
        RENDER.render_email(view)


def test_no_explicit_series_means_no_chart_or_fake_zero_values() -> None:
    context = _daily_context()
    context["activities"][0]["sequence"] = []
    view = VIEW.build_daily_view(_daily_payload(), context, _plan())
    rendered = RENDER.render_email(view)
    assert view["charts"] == []
    assert rendered.assets == ()
    assert "cid:" not in rendered.payload["html"]
    assert "0 km" not in rendered.payload["html"]


def test_long_explicit_series_uses_bounded_accessible_summary() -> None:
    context = _daily_context()
    context["activities"][0]["sequence"] = [
        {
            "offset_seconds": index * 30,
            "sample_count": 30,
            "metrics": {"heart_rate_bpm": 110.123 + index % 45},
        }
        for index in range(2880)
    ]
    view = VIEW.build_daily_view(_daily_payload(), context, _plan())
    rendered = RENDER.render_email(view)
    asset = rendered.payload["asset_manifest"]["assets"][0]
    assert len(asset["alt"]) < 2000
    assert "共 2880 个实测点" in asset["alt"]
    assert "最低 110.1" in asset["alt"]
    assert "110.123" not in asset["alt"]
    assert len(rendered.payload["html"].encode("utf-8")) <= 80 * 1024


def test_field_mapping_snapshot_has_183_classified_rows() -> None:
    root = SOURCE / "skills/training-report-publisher/references/email-design-v1"
    classification = json.loads((root / "field-classification.json").read_text())
    assert classification["row_count"] == 183
    assert len(classification["rows"]) == 183
    assert {row["disposition"] for row in classification["rows"]} == {
        "direct",
        "derived",
        "unsupported",
    }
    assert [row["ordinal"] for row in classification["rows"]] == list(range(1, 184))
    source_rows = sum(
        1
        for line in (root / "FIELD-MAPPING.md").read_text().splitlines()
        if line.startswith("| `")
    )
    assert source_rows == 183


def test_pillow_runtime_is_pinned_for_deterministic_charts() -> None:
    requirements = (
        (SOURCE / "requirements.txt").read_text(encoding="utf-8").splitlines()
    )
    assert "pillow==12.3.0" in requirements
    assert importlib.metadata.version("Pillow") == "12.3.0"


@pytest.mark.parametrize("decision", ["advance", "hold", "deload"])
def test_weekly_view_and_render_cover_each_decision(decision: str) -> None:
    dailies = []
    for offset, day in enumerate(range(15, 22)):
        content = _daily_payload(safety="caution" if offset == 2 else "ready")
        content["report_date"] = f"2026-08-{day:02d}"
        content["review_date"] = f"2026-08-{day - 1:02d}"
        content["sleep_wake_date"] = content["report_date"]
        content["bounded_metrics"] = [
            {
                "name": "main_sleep_duration",
                "value": 7 + offset / 10,
                "unit": "hours",
                "evidence_ref": 101,
            },
            {
                "name": "resting_heart_rate",
                "value": 48 + offset,
                "unit": "bpm",
                "evidence_ref": 102,
            },
            {
                "name": "last_night_average_hrv",
                "value": 60 - offset,
                "unit": "ms",
                "evidence_ref": 103,
            },
            {
                "name": "running_distance",
                "value": offset + 1,
                "unit": "km",
                "evidence_ref": 104,
            },
            {
                "name": "activity_duration",
                "value": 30 + offset,
                "unit": "minutes",
                "evidence_ref": 104,
            },
        ]
        if offset == 0:
            content["bounded_metrics"][0].update(value=25200, unit="seconds")
            content["bounded_metrics"][3].update(value=1000, unit="meters")
            content["bounded_metrics"][4].update(value=1800, unit="seconds")
        dailies.append(
            {
                "output_id": 200 + offset,
                "sha256": f"{offset + 1:x}" * 64,
                "content": content,
            }
        )
    plan = _plan()
    plan["progression_rule"] = decision
    plan["items"][0]["downgrade_rule"] = "sentinel-weekly-downgrade"
    plan["items"][0]["stop_conditions"] = ["sentinel-weekly-stop"]
    weekly: dict[str, Any] = {
        "schema_version": "weekly_ai_result_v1",
        "status": "succeeded",
        "error_code": None,
        "period": "2026-08-15/2026-08-21",
        "daily_input_sha256": [item["sha256"] for item in dailies],
        "summary": "本周训练稳定，下周按恢复情况执行。",
        "evidence_refs": [
            {"output_id": item["output_id"], "sha256": item["sha256"], "claim": "日报"}
            for item in dailies
        ],
        "goal_sha256": "f" * 64,
        "training_plan": plan,
        "provider_calls": 0,
    }
    context = {
        "schema_version": "weekly_ai_context_v1",
        "status": "ready",
        "period": weekly["period"],
        "daily_reports": dailies,
        "missing_dates": [],
        "provider_calls": 0,
    }
    view = VIEW.build_weekly_view(weekly, context)
    assert view["schema_version"] == "weekly_email_view_v1"
    assert view["decision"] == decision
    assert len(view["plan_items"]) == 7
    assert view["plan_items"][0]["downgrade_rule"] == "继续休息，不补偿错过的训练。"
    assert "sentinel-weekly-stop" not in json.dumps(view, ensure_ascii=False)
    assert {chart["role"] for chart in view["charts"]} == {
        "weekly_sleep",
        "weekly_rhr",
        "weekly_hrv",
        "weekly_activity_duration",
    }
    charts = {chart["role"]: chart for chart in view["charts"]}
    assert charts["weekly_sleep"]["points"][0]["y"] == 7
    assert charts["weekly_activity_duration"]["points"][0]["y"] == 30
    assert view["stats"]["running_distance_km"] == 28
    rendered = RENDER.render_email(view)
    assert rendered.payload["subject"] == "TrainLab · 每周总结 · 2026-08-15~2026-08-21"
    assert rendered.payload["html"].count("<h1") == 1
    assert rendered.payload["html"].count("<title>") == 1
    if decision == "hold":
        assert "<strong>维持</strong>" in rendered.payload["html"]
        assert "可以训练" not in rendered.payload["html"]
        assert "background:#EDF1F2" in rendered.payload["html"]
    elif decision == "advance":
        assert "<strong>进阶" in rendered.payload["html"]
    else:
        assert "<strong>减量</strong>" in rendered.payload["html"]
    assert len(rendered.assets) == 4
    assert "结束 7.6 小时" in rendered.assets[0].alt
    if decision == "hold":
        weekly["evidence_refs"] = weekly["evidence_refs"][:-1]
        with pytest.raises(
            VIEW.EmailViewError, match="weekly_email_evidence_lineage_mismatch"
        ):
            VIEW.build_weekly_view(weekly, context)


def test_blocked_weekly_does_not_invent_plan_or_decision() -> None:
    dailies = []
    for offset, day in enumerate(range(15, 22)):
        content = _daily_payload()
        content["report_date"] = f"2026-08-{day:02d}"
        content["review_date"] = f"2026-08-{day - 1:02d}"
        content["sleep_wake_date"] = content["report_date"]
        dailies.append(
            {
                "output_id": 300 + offset,
                "sha256": f"{offset + 1:x}" * 64,
                "content": content,
            }
        )
    weekly = {
        "schema_version": "weekly_ai_result_v1",
        "status": "blocked",
        "error_code": "weekly_daily_inputs_missing",
        "period": "2026-08-15/2026-08-21",
        "daily_input_sha256": [item["sha256"] for item in dailies],
        "summary": "周总结因证据不完整而阻断。",
        "evidence_refs": [
            {
                "output_id": item["output_id"],
                "sha256": item["sha256"],
                "claim": "日报",
            }
            for item in dailies
        ],
        "training_plan": {},
        "provider_calls": 0,
    }
    context = {
        "schema_version": "weekly_ai_context_v1",
        "status": "blocked",
        "period": weekly["period"],
        "daily_reports": dailies,
        "missing_dates": [],
        "provider_calls": 0,
    }
    view = VIEW.build_weekly_view(weekly, context)
    assert view["status"] == "blocked"
    assert view["decision"] is None
    assert view["progression_dimension"] is None
    assert view["plan_items"] == []
    assert view["charts"] == []
    rendered = RENDER.render_email(view)
    assert "<strong>报告已阻断</strong>" in rendered.payload["html"]
    assert "阻断原因：</strong>七份日报证据不完整" in rendered.payload["html"]
    assert "weekly_daily_inputs_missing" not in rendered.payload["html"]


def test_weekly_ai_summary_and_claims_are_not_reader_visible() -> None:
    dailies = []
    for offset, day in enumerate(range(15, 22)):
        content = _daily_payload()
        content["report_date"] = f"2026-08-{day:02d}"
        content["review_date"] = f"2026-08-{day - 1:02d}"
        content["sleep_wake_date"] = content["report_date"]
        dailies.append(
            {
                "output_id": 400 + offset,
                "sha256": f"{offset + 1:x}" * 64,
                "content": content,
            }
        )
    weekly = {
        "schema_version": "weekly_ai_result_v1",
        "status": "succeeded",
        "error_code": None,
        "period": "2026-08-15/2026-08-21",
        "daily_input_sha256": [item["sha256"] for item in dailies],
        "summary": "raw_file_id bounded_metrics report_date",
        "evidence_refs": [
            {
                "output_id": item["output_id"],
                "sha256": item["sha256"],
                "claim": "sha256 evidence_ref review_date",
            }
            for item in dailies
        ],
        "goal_sha256": "f" * 64,
        "training_plan": _plan(),
        "provider_calls": 0,
    }
    context = {
        "schema_version": "weekly_ai_context_v1",
        "status": "ready",
        "period": weekly["period"],
        "daily_reports": dailies,
        "missing_dates": [],
        "provider_calls": 0,
    }
    view = VIEW.build_weekly_view(weekly, context)
    rendered = RENDER.render_email(view)
    visible = rendered.payload["html"] + rendered.payload["text"]
    assert "raw_file_id" not in visible
    assert "bounded_metrics" not in visible
    assert "review_date" not in visible
    assert view["evidence"]["refs"][0]["claim"] == "2026-08-15 日报"
