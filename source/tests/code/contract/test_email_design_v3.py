from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from skills._shared.scripts.schema_validation import validate_payload
from skills._shared.state import canonical_json

SOURCE = Path(__file__).resolve().parents[3]


def _load(name: str, relative: str) -> Any:
    path = SOURCE / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V3 = _load(
    "trainlab_email_view_v3_contract",
    "skills/training-report-publisher/scripts/email_view_v3.py",
)
RENDER = _load(
    "trainlab_email_design_renderer_v3_contract",
    "skills/training-report-publisher/scripts/email_design_renderer.py",
)


def _step(phase: str) -> dict[str, Any]:
    return {
        "phase": phase,
        "name": phase,
        "instruction": f"完成{phase}阶段",
        "end_condition": f"{phase}完成",
        "duration_minutes": 5,
        "rpe_min": 2,
        "rpe_max": 3,
    }


def _course(day: str, session_type: str = "easy_run") -> dict[str, Any]:
    is_rest = session_type == "rest"
    return {
        "date": day,
        "activity_kind": "rest" if is_rest else "running",
        "session_type": session_type,
        "name": "完全恢复" if is_rest else "轻松跑",
        "purpose": "恢复" if is_rest else "维持跑步连续性",
        "load_level": "low",
        "garmin_mapping_status": "unsupported_skip" if is_rest else "candidate",
        "duration_minutes": 30,
        "rpe_min": 1 if is_rest else 2,
        "rpe_max": 2 if is_rest else 4,
        "feel_guidance": "轻松舒适，可以完整交谈",
        "steps": [_step(item) for item in ("warmup", "main", "recovery", "cooldown")],
        "start_gate": ["没有持续疼痛或明显不适"],
        "technique_notes": ["动作自然，不追求速度"],
        "downgrade_rule": "恢复不足时改为休息",
        "stop_conditions": ["疼痛、胸闷、眩晕或异常气短时停止"],
    }


def _plan() -> dict[str, Any]:
    sessions = [
        "easy_run",
        "rest",
        "sos_threshold",
        "rest",
        "easy_run",
        "long_easy",
        "rest",
    ]
    items = [
        _course(f"2026-08-{19 + index:02d}", value)
        for index, value in enumerate(sessions)
    ]
    items[2]["name"] = "条件式节奏跑（SOS）"
    items[2]["load_level"] = "hard"
    items[2]["rpe_min"] = 6
    items[2]["rpe_max"] = 7
    return {
        "schema_version": "training_plan_v2",
        "status": "succeeded",
        "progression_rule": "hold",
        "progression_dimension": "none",
        "sos_omission_reason": None,
        "sos_schedule_reason": "按默认星期三安排",
        "items": items,
        "provider_calls": 0,
    }


def _daily_ai() -> dict[str, Any]:
    course = _course("2026-08-12")
    return {
        "schema_version": "daily_ai_result_v2",
        "status": "succeeded",
        "error_code": None,
        "report_date": "2026-08-12",
        "review_date": "2026-08-11",
        "sleep_wake_date": "2026-08-12",
        "safety": "caution",
        "planned_course_ref": {"output_id": 84, "sha256": "1" * 64},
        "planned_course_context": "verified_original",
        "planned_course": course,
        "adjustment": "modified",
        "effective_course": _course("2026-08-12", "rest"),
        "yesterday_summary": "昨日完成一项训练，负荷需要结合恢复判断。",
        "review_health_summary": "昨日静息心率为47 bpm，昨夜HRV为76 ms。",
        "recovery_summary": "主睡眠约7小时，今日先保持谨慎。",
        "decision_reasons": ["昨日训练较长，今天降低负荷。"],
        "adjustment_reason_codes": ["insufficient_recovery"],
        "health_observations": {"sleep_hours": 7, "resting_heart_rate_bpm": 47},
        "daily_load": {"activity_count": 1, "running_distance_km": 5.8},
        "uncertainty": [],
        "stop_conditions": ["出现疼痛、胸闷、眩晕或异常气短时停止"],
        "evidence_refs": [{"output_id": 43, "sha256": "2" * 64, "claim": "日报证据"}],
        "provider_calls": 0,
    }


def _payload_sha(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def _presentation(
    day: str = "2026-08-12", *, daily_result: dict[str, Any] | None = None
) -> dict[str, Any]:
    bound_daily = daily_result or _daily_ai()
    return {
        "schema_version": "daily_presentation_evidence_v1",
        "status": "ready",
        "report_date": day,
        "review_date": "2026-08-11",
        "sleep_wake_date": day,
        "safety": "caution",
        "source_daily_result": {
            "output_id": 85,
            "sha256": "3" * 64,
            "content_json_sha256": _payload_sha(bound_daily),
        },
        "activities": [
            {
                "activity_inventory_id": 7,
                "raw_file_id": 9335,
                "raw_sha256": "4" * 64,
                "activity_kind": "running",
                "distance_km": 5.8,
                "duration_seconds": 3060,
                "pace_seconds_per_km": 527.6,
                "heart_rate_average_bpm": 136,
                "heart_rate_maximum_bpm": 152,
                "heart_rate_series": [
                    {"offset_seconds": 0, "value": 118},
                    {"offset_seconds": 30, "value": 130},
                    {"offset_seconds": 60, "value": 136},
                ],
                "observed_heart_rate_zones": {
                    "source": "fit_session_time_in_hr_zone",
                    "definition_sha256": "5" * 64,
                    "percentage_source": "derived_from_provider_duration",
                    "segments": [
                        {"label": "低于Z1", "duration_seconds": 420, "percentage": 14},
                        {"label": "Z1", "duration_seconds": 900, "percentage": 30},
                        {"label": "Z2", "duration_seconds": 1050, "percentage": 35},
                        {"label": "Z3", "duration_seconds": 480, "percentage": 16},
                        {"label": "Z4", "duration_seconds": 150, "percentage": 5},
                        {"label": "Z5", "duration_seconds": 0, "percentage": 0},
                        {"label": "高于Z5", "duration_seconds": 0, "percentage": 0},
                    ],
                },
            }
        ],
        "sleep": {
            "raw_file_id": 8429,
            "raw_sha256": "6" * 64,
            "start": "2026-08-11T22:56:00+08:00",
            "end": "2026-08-12T06:44:00+08:00",
            "duration_seconds": 28080,
            "completeness": "complete",
            "stages": [
                {"label": "深睡", "duration_seconds": 6480, "percentage": 23.08},
                {"label": "浅睡", "duration_seconds": 14100, "percentage": 50.21},
                {"label": "REM", "duration_seconds": 5400, "percentage": 19.23},
                {"label": "清醒", "duration_seconds": 2100, "percentage": 7.48},
            ],
        },
        "health": {
            "rhr": {
                "value": 47,
                "unit": "bpm",
                "observed_date": "2026-08-11",
                "raw_file_id": 7001,
                "raw_sha256": "7" * 64,
            },
            "hrv": {
                "value": 76,
                "unit": "ms",
                "observed_date": "2026-08-11",
                "raw_file_id": 7002,
                "raw_sha256": "8" * 64,
            },
            "vo2_max": {
                "value": 51,
                "unit": "ml/kg/min",
                "observed_date": "2026-08-10",
                "raw_file_id": 7003,
                "raw_sha256": "9" * 64,
            },
            "weight": {
                "value": 70.3,
                "unit": "kg",
                "observed_date": "2026-08-07",
                "raw_file_id": 7004,
                "raw_sha256": "a" * 64,
            },
        },
        "recent_trend": {
            "days_available": 7,
            "sleep_average_hours": 6.8,
            "running_distance_km": 18.3,
        },
        "provider_calls": 0,
    }


def _weekly_ai() -> dict[str, Any]:
    refs = [
        {"output_id": 85 + index, "sha256": f"{index + 3:x}" * 64} for index in range(7)
    ]
    return {
        "schema_version": "weekly_ai_result_v2",
        "status": "succeeded",
        "error_code": None,
        "period": "2026-08-12/2026-08-18",
        "progression_rule": "hold",
        "health_summary": "本周睡眠波动，恢复余量需要谨慎管理。",
        "activity_summary": "本周完成跑步和攀岩，负荷总体维持。",
        "insights": [
            {
                "observation": "睡眠波动",
                "meaning": "恢复不稳定",
                "action": "SOS前检查",
                "evidence_refs": [85],
            },
            {
                "observation": "跑量稳定",
                "meaning": "无需加量",
                "action": "维持距离",
                "evidence_refs": [86],
            },
            {
                "observation": "攀岩较长",
                "meaning": "跨日疲劳",
                "action": "错开硬课",
                "evidence_refs": [87],
            },
        ],
        "uncertainty": ["硬负荷分类证据有限"],
        "daily_input_refs": refs,
        "training_plan": _plan(),
        "provider_calls": 0,
    }


def _weekly_inputs() -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]
]:
    weekly = _weekly_ai()
    daily: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for index in range(7):
        item = _presentation(f"2026-08-{12 + index:02d}")
        item["review_date"] = f"2026-08-{11 + index:02d}"
        item["sleep_wake_date"] = item["report_date"]
        item["source_daily_result"] = {
            "output_id": 85 + index,
            "sha256": f"{index + 3:x}" * 64,
            "content_json_sha256": f"{index + 1:x}" * 64,
        }
        daily.append(item)
        outputs.append(
            {
                "report_date": item["report_date"],
                "output_id": 101 + index,
                "sha256": f"{index + 9:x}" * 64,
                "content_json_sha256": _payload_sha(item),
            }
        )
    source = {
        "output_id": 92,
        "sha256": "d" * 64,
        "content_json_sha256": _payload_sha(weekly),
    }
    return daily, outputs, source


def test_daily_v3_restores_opendesign_components_and_cid_charts() -> None:
    view = V3.build_daily_view_v3(_daily_ai(), _presentation())
    assert validate_payload(view, "daily_email_view_v3") == []
    rendered = RENDER.render_email_v3(view)
    assert validate_payload(rendered.payload, "daily_email_render_v3") == []
    components = [
        "Header",
        "SafetyHero",
        "TrainingInterpretation",
        "HealthInterpretation",
        "RecoveryInterpretation",
        "CourseComparison",
        "CourseDetails",
        "ActivityKPI",
        "SleepCard",
        "RecoveryCard",
        "HealthSnapshot",
        "StaticCharts",
        "TrendSummary",
        "Evidence",
        "Privacy",
    ]
    positions = [
        rendered.payload["html"].index(f'data-component="{name}"')
        for name in components
    ]
    assert positions == sorted(positions)
    chart_assets = [
        asset for asset in rendered.assets if asset.role in RENDER._ROLE_CONTRACTS
    ]
    assert len(chart_assets) == 3
    assert all(asset.width_px == 1248 for asset in chart_assets)
    assert 'style="width:100%;max-width:672px;' in rendered.payload["html"]
    assert "@media only screen and (max-width:375px)" in rendered.payload["html"]
    assert "bounded_metrics" not in rendered.payload["html"]
    assert "raw_file_id" not in rendered.payload["html"]


def test_historical_provider_zones_are_allowed_but_course_zone_prescription_is_not() -> (
    None
):
    view = V3.build_daily_view_v3(_daily_ai(), _presentation())
    rendered = RENDER.render_email_v3(view)
    assert "Z1" in rendered.payload["html"]
    assert "derived_from_provider_duration" not in rendered.payload["html"]
    bad = copy.deepcopy(view)
    bad["effective_course"]["steps"][1]["instruction"] = "主训练保持Z2，目标150 bpm"
    with pytest.raises(ValueError):
        RENDER.render_email_v3(bad)


def test_weekly_v3_consumes_exactly_seven_daily_presentation_items() -> None:
    daily, outputs, weekly_source = _weekly_inputs()
    for index, item in enumerate(daily):
        item["health"]["rhr"]["value"] = 47 + index % 3
        item["health"]["hrv"]["value"] = 68 + index
        item["sleep"]["duration_seconds"] = 24000 + index * 600
        item["activities"][0]["raw_file_id"] = 9335 + index
        item["activities"][0]["raw_sha256"] = f"{index + 1:x}" * 64
        if index == 1:
            item["activities"] = []
        outputs[index]["content_json_sha256"] = _payload_sha(item)
    view = V3.build_weekly_view_v3(_weekly_ai(), daily, outputs, weekly_source)
    assert validate_payload(view, "weekly_email_view_v3") == []
    roles = {chart["role"] for chart in view["charts"]}
    assert {
        "weekly_sleep",
        "weekly_rhr",
        "weekly_hrv",
        "weekly_running_distance",
        "weekly_activity_duration",
    }.issubset(roles)
    running = next(
        chart for chart in view["charts"] if chart["role"] == "weekly_running_distance"
    )
    assert len(running["points"]) == 7
    assert running["points"][1]["y"] == 0
    assert len(running["source_refs"]) == 7
    assert all(
        set(ref) == {"output_id", "output_sha256"} for ref in running["source_refs"]
    )
    assert all(len(chart["source_refs"]) == 7 for chart in view["charts"])
    assert len(view["daily_presentation_refs"]) == 7
    with pytest.raises(ValueError, match="weekly_presentation_daily_count_invalid"):
        V3.build_weekly_view_v3(_weekly_ai(), daily[:6], outputs[:6], weekly_source)


def test_weekly_v3_restores_kpis_charts_insights_and_detailed_timeline() -> None:
    daily, outputs, weekly_source = _weekly_inputs()
    view = V3.build_weekly_view_v3(_weekly_ai(), daily, outputs, weekly_source)
    rendered = RENDER.render_email_v3(view)
    components = [
        "Header",
        "WeeklyDecisionHero",
        "WeeklyKPI",
        "WeekComparison",
        "StaticCharts",
        "InsightCards",
        "PlanTimeline",
        "DataLimits",
        "Evidence",
        "Privacy",
    ]
    positions = [
        rendered.payload["html"].index(f'data-component="{name}"')
        for name in components
    ]
    assert positions == sorted(positions)
    assert "条件式节奏跑（SOS）" in rendered.payload["html"]
    for label in (
        "热身",
        "主训练",
        "恢复",
        "放松",
        "开始前检查",
        "执行提示",
        "降级方案",
        "停止条件",
    ):
        assert label in rendered.payload["html"]
    assert len(rendered.assets) >= 5


def test_every_training_plan_v2_session_type_has_a_human_readable_label() -> None:
    schema = json.loads(
        (SOURCE / "skills/_shared/schemas/training_plan_v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    session_types = set(schema["$defs"]["course"]["properties"]["session_type"]["enum"])
    assert set(RENDER._SESSION_LABELS) == session_types
    for session_type in sorted(session_types):
        html = RENDER._course_html(_course("2026-08-19", session_type), detailed=False)
        assert session_type not in html
        assert RENDER._SESSION_LABELS[session_type] in html


@pytest.mark.parametrize("safety", ["ready", "caution", "blocked"])
def test_daily_v3_supports_all_safety_states_and_missing_optional_charts(
    safety: str,
) -> None:
    ai = _daily_ai()
    ai["safety"] = safety
    if safety == "blocked":
        ai["status"] = "blocked"
        ai["error_code"] = "daily_sleep_evidence_missing"
    evidence = _presentation(daily_result=ai)
    evidence["safety"] = safety
    evidence["status"] = "blocked" if safety == "blocked" else "ready"
    evidence["error_code"] = (
        "daily_sleep_evidence_missing" if safety == "blocked" else None
    )
    evidence["activities"] = []
    evidence["sleep"].pop("stages")
    view = V3.build_daily_view_v3(ai, evidence)
    rendered = RENDER.render_email_v3(view)
    assert 'data-component="SafetyHero"' in rendered.payload["html"]
    assert "昨日没有已验证活动" in rendered.payload["html"]
    assert all(
        asset.role not in {"daily_activity_hr_zones", "daily_sleep_stages"}
        for asset in rendered.assets
    )
    if safety == "blocked":
        assert 'data-component="CourseComparison"' not in rendered.payload["html"]
        assert 'data-component="CourseDetails"' not in rendered.payload["html"]
        assert "今天怎么练" not in rendered.payload["text"]


def test_weekly_zone_definitions_must_match_before_aggregation() -> None:
    daily, outputs, weekly_source = _weekly_inputs()
    daily[1]["activities"][0]["observed_heart_rate_zones"]["definition_sha256"] = (
        "f" * 64
    )
    outputs[1]["content_json_sha256"] = _payload_sha(daily[1])
    view = V3.build_weekly_view_v3(_weekly_ai(), daily, outputs, weekly_source)
    assert "weekly_activity_hr_zones" not in {chart["role"] for chart in view["charts"]}
    assert any("不同的设备心率分区定义" in item for item in view["data_limits"])


def test_renderer_recomputes_duration_percentages_and_keeps_core_styles_inline() -> (
    None
):
    view = V3.build_daily_view_v3(_daily_ai(), _presentation())
    bad = copy.deepcopy(view)
    bad["charts"][0]["segments"][0]["percentage"] += 1
    with pytest.raises(ValueError, match="email_chart_percentage_mismatch"):
        RENDER.render_email_v3(bad)
    html = RENDER.render_email_v3(view).payload["html"]
    assert 'style="width:100%;max-width:672px;' in html
    assert 'data-component="ActivityKPI"' in html
    kpi_tables = re.findall(
        r'<table[^>]*class="kpi-table"[^>]*>.*?</table>', html, flags=re.DOTALL
    )
    assert kpi_tables
    assert all(
        max(row.count("<td") for row in table.split("</tr>")) <= 4
        for table in kpi_tables
    )


def test_blocked_weekly_hides_plan_timeline_and_charts() -> None:
    weekly = _weekly_ai()
    weekly["status"] = "blocked"
    weekly["error_code"] = "weekly_daily_inputs_missing"
    daily, outputs, _source = _weekly_inputs()
    source = {
        "output_id": 92,
        "sha256": "d" * 64,
        "content_json_sha256": _payload_sha(weekly),
    }
    view = V3.build_weekly_view_v3(weekly, daily, outputs, source)
    rendered = RENDER.render_email_v3(view)
    assert not [
        asset for asset in rendered.assets if asset.role in RENDER._ROLE_CONTRACTS
    ]
    assert [asset.role for asset in rendered.assets] == ["email_brand_mark"]
    assert 'data-component="PlanTimeline"' not in rendered.payload["html"]
    assert 'data-component="StaticCharts"' not in rendered.payload["html"]
    assert "七日详细计划" not in rendered.payload["text"]


def test_long_activity_uses_concise_text_fallback_without_gmail_clipping() -> None:
    view = V3.build_daily_view_v3(_daily_ai(), _presentation())
    series = next(
        chart
        for chart in view["charts"]
        if chart["role"] == "daily_activity_heart_rate"
    )
    series["points"] = [
        {"x": index * 30, "y": 100 + index % 60} for index in range(600)
    ]
    rendered = RENDER.render_email_v3(view)
    html = rendered.payload["html"]
    assert len(html.encode()) <= RENDER.MAX_HTML_BYTES
    assert "600个实测点" in html
    assert "起点 0:00 100 bpm" in html
    assert "终点 299:30 159 bpm" in html
    assert "最高 159 bpm" in html


def test_v3_render_is_byte_deterministic() -> None:
    view = V3.build_daily_view_v3(_daily_ai(), _presentation())
    first = RENDER.render_email_v3(view)
    second = RENDER.render_email_v3(copy.deepcopy(view))
    assert first.payload == second.payload
    assert [(item.sha256, item.data) for item in first.assets] == [
        (item.sha256, item.data) for item in second.assets
    ]


def test_opendesign_shell_header_and_brand_assets_use_frozen_tokens() -> None:
    daily = RENDER.render_email_v3(V3.build_daily_view_v3(_daily_ai(), _presentation()))
    weekly_inputs, output_refs, weekly_source = _weekly_inputs()
    weekly = RENDER.render_email_v3(
        V3.build_weekly_view_v3(_weekly_ai(), weekly_inputs, output_refs, weekly_source)
    )
    for rendered in (daily, weekly):
        html = rendered.payload["html"]
        assert "background:#F4F8F8" in html
        assert "color:#17323B" in html
        assert "border:1px solid #D7E4E6;border-radius:20px;overflow:hidden" in html
        assert "background:#EEF4F3" not in html
        assert "#17333A" not in html
        assert "background:#163D53" not in html
        assert 'data-asset-role="email_brand_mark"' in html
        assert 'alt="TrainLab"' in html
        brand = [asset for asset in rendered.assets if asset.role == "email_brand_mark"]
        assert len(brand) == 1
        assert (brand[0].width_px, brand[0].height_px) == (96, 96)


@pytest.mark.parametrize(
    ("safety", "role", "label"),
    [
        ("ready", "email_status_ready", "可以训练"),
        ("caution", "email_status_caution", "需要谨慎"),
        ("blocked", "email_status_blocked", "报告已阻断"),
    ],
)
def test_daily_status_uses_graphic_text_and_color(
    safety: str, role: str, label: str
) -> None:
    ai = _daily_ai()
    ai["safety"] = safety
    if safety == "blocked":
        ai["status"] = "blocked"
        ai["error_code"] = "daily_sleep_evidence_missing"
    evidence = _presentation(daily_result=ai)
    evidence["safety"] = safety
    evidence["status"] = "blocked" if safety == "blocked" else "ready"
    evidence["error_code"] = (
        "daily_sleep_evidence_missing" if safety == "blocked" else None
    )
    rendered = RENDER.render_email_v3(V3.build_daily_view_v3(ai, evidence))
    assert f'data-asset-role="{role}"' in rendered.payload["html"]
    assert f'alt="{label}"' in rendered.payload["html"]
    status_assets = [asset for asset in rendered.assets if asset.role == role]
    assert len(status_assets) == 1
    assert (status_assets[0].width_px, status_assets[0].height_px) == (64, 64)


def test_sleep_card_formats_hong_kong_clock_without_raw_iso_timestamps() -> None:
    evidence = _presentation()
    evidence["sleep"]["start"] = "2026-08-11T16:56:00Z"
    evidence["sleep"]["end"] = "2026-08-11T22:44:00Z"
    rendered = RENDER.render_email_v3(V3.build_daily_view_v3(_daily_ai(), evidence))
    html = rendered.payload["html"]
    assert "00:56–06:44" in html
    assert "2026-08-11T16:56:00Z" not in html
    assert "2026-08-11T22:44:00Z" not in html


def test_weekly_chart_alt_and_text_fallback_localize_time_units() -> None:
    daily, outputs, weekly_source = _weekly_inputs()
    rendered = RENDER.render_email_v3(
        V3.build_weekly_view_v3(_weekly_ai(), daily, outputs, weekly_source)
    )
    chart_assets = [
        asset for asset in rendered.assets if asset.role in RENDER._ROLE_CONTRACTS
    ]
    sleep = next(asset for asset in chart_assets if asset.role == "weekly_sleep")
    activity = next(
        asset for asset in chart_assets if asset.role == "weekly_activity_duration"
    )
    assert "小时" in sleep.alt
    assert "分钟" in activity.alt
    visible = rendered.payload["html"] + rendered.payload["text"]
    assert re.search(r"\b(hours|minutes)\b", visible, flags=re.IGNORECASE) is None
