from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

SOURCE = Path(__file__).resolve().parents[3]


def _load() -> Any:
    path = SOURCE / "skills/training-report-publisher/scripts/reader_content_v4.py"
    spec = importlib.util.spec_from_file_location(
        "trainlab_reader_content_v4_test", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


READER = _load()


def _daily() -> dict[str, Any]:
    return {
        "schema_version": "daily_reader_content_v1",
        "status": "ready",
        "title": "TrainLab 日报 2026-08-12",
        "report_date": "2026-08-12",
        "activity_date": "2026-08-11",
        "sleep_wake_date": "2026-08-12",
        "fixed_course_ref": {
            "plan_output_id": 1,
            "plan_output_sha256": "a" * 64,
            "course_sha256": "b" * 64,
        },
        "sections": [
            {
                "section_code": "completed_activities",
                "heading": "昨日全部运动",
                "paragraphs": ["跑步 5.0 km，45 分钟。"],
                "items": [],
            },
            {
                "section_code": "health_recovery",
                "heading": "健康、睡眠与恢复",
                "paragraphs": ["睡眠 7.5 小时。"],
                "items": [],
            },
            {
                "section_code": "fixed_course",
                "heading": "今日固定课程",
                "paragraphs": ["轻松跑 45 分钟。"],
                "items": [],
            },
            {
                "section_code": "limitations_alerts",
                "heading": "数据缺失与安全警告",
                "paragraphs": ["无数据缺口。"],
                "items": [],
            },
        ],
        "charts": [],
        "provider_calls": 0,
    }


def test_daily_markdown_and_html_share_exact_section_order() -> None:
    content = _daily()
    markdown = READER.render_reader_markdown(content)
    html = READER.render_lowfi_html(content)
    headings = [item["heading"] for item in content["sections"]]
    assert all(
        markdown.index(heading) < markdown.index(headings[index + 1])
        for index, heading in enumerate(headings[:-1])
    )
    assert all(
        html.index(heading) < html.index(headings[index + 1])
        for index, heading in enumerate(headings[:-1])
    )
    assert "<section" in html
    assert "<section" not in html.split("<section", 1)[1].split("</section>", 1)[0]


def test_daily_reader_persists_exact_fixed_course_reference() -> None:
    course = {
        "date": "2026-08-12",
        "name": "固定轻松跑",
        "purpose": "保持连续性",
        "rpe_min": 3,
        "rpe_max": 4,
        "feel_guidance": "按原周计划执行与否由用户决定",
        "steps": [],
        "technique_notes": ["动作自然"],
        "stop_conditions": ["尖锐疼痛时停止"],
    }
    reference = {
        "plan_output_id": 77,
        "plan_output_sha256": "a" * 64,
        "course_sha256": READER._canonical_sha256(course),
    }
    observation = {
        "report_date": "2026-08-12",
        "activity_date": "2026-08-11",
        "sleep_wake_date": "2026-08-12",
        "activities": [],
    }
    health: dict[str, Any] = {
        "health_summary": "健康事实。",
        "sleep_analysis": "睡眠事实。",
        "recovery_analysis": "恢复事实。",
        "uncertainty": [],
        "health_alert": None,
    }
    result = READER.build_daily_reader_content_v1(
        observation,
        health,
        planned_course=course,
        planned_course_ref=reference,
    )
    assert result["fixed_course_ref"] == reference


def test_lowfi_html_has_five_supported_viewports_and_no_nested_cards() -> None:
    html = READER.render_lowfi_html(_daily())
    for width in (375, 390, 430, 600, 672):
        assert f"/* viewport:{width} */" in html
    assert 'class="card' not in html


def test_chart_limits_are_enforced() -> None:
    content = _daily()
    content["charts"] = [
        {"chart_code": f"c{index}", "title": "图", "alt_text": "说明", "data": []}
        for index in range(3)
    ]
    try:
        READER.render_reader_markdown(content)
    except ValueError as exc:
        assert str(exc) == "daily_chart_limit_exceeded"
    else:
        raise AssertionError("daily chart limit was not enforced")


def test_tracked_public_samples_are_synthetic_and_renderable() -> None:
    fixtures = SOURCE / "tests/code/fixtures"
    for name in (
        "m11_v4_public_daily_reader.json",
        "m11_v4_public_weekly_reader.json",
    ):
        payload = json.loads((fixtures / name).read_text())
        assert "公开合成" in payload["title"]
        assert payload["provider_calls"] == 0
        assert "@" not in json.dumps(payload, ensure_ascii=False)
        assert READER.render_reader_markdown(payload).startswith("# TrainLab")
        assert "<section" in READER.render_lowfi_html(payload)
