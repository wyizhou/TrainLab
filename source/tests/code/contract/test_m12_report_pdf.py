"""Readable seven-part content, complete long courses and faithful missingness."""

import importlib
import io
import sys
from pathlib import Path

import pytest

from skills._shared.fit_weekly import (
    model_job,
)
from skills._shared.fit_weekly import (
    report_artifacts as artifacts,
)
from skills._shared.fit_weekly import (
    report_revisions as revisions,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
f = importlib.import_module("m12_report_factory")

# Independent expected names and units for the parser's actual public keys.
METRIC_NAMES = {
    "heart_rate_bpm": "历史心率（BPM）",
    "cadence_rpm": "设备节律（转/分）",
    "power_w": "功率（瓦）",
    "altitude_m": "海拔（米）",
    "temperature_c": "温度（摄氏度）",
    "speed_m_s": "速度（米/秒）",
    "step_length_mm": "步长（毫米）",
    "vertical_oscillation_mm": "垂直振幅（毫米）",
    "stance_time_ms": "触地时间（毫秒）",
    "vertical_ratio_percent": "垂直比（%）",
}
PROVIDER_NAMES = {
    "distance_m": "距离（米）",
    "timer_seconds": "设备计时时长（秒）",
    "elapsed_seconds": "经过时长（秒）",
    "avg_heart_rate_bpm": "历史平均心率（BPM）",
    "max_heart_rate_bpm": "历史最高心率（BPM）",
    "avg_cadence_rpm": "设备平均节律（转/分）",
    "avg_power_w": "平均功率（瓦）",
}


def metric_label_view(view):
    """Synthetic renderer boundary only, not a validated business result."""
    from copy import deepcopy

    from skills._shared.fit_weekly import fit_parse

    assert set(METRIC_NAMES) == set(fit_parse.METRICS)
    assert set(PROVIDER_NAMES) == set(fit_parse.PROVIDER_FIELDS)
    view = deepcopy(view)
    refs = []
    for names, prefix in (
        (METRIC_NAMES, ["summary", "metrics"]),
        (PROVIDER_NAMES, ["provider_summary"]),
    ):
        for index, key in enumerate(names):
            refs.append(
                {
                    "source": "current",
                    "activity_ref": "101",
                    "session_ordinal": 1,
                    "fit_sha256": "a" * 64,
                    "period_end_utc": None,
                    "request_sha256": None,
                    "path": prefix
                    + [key]
                    + (["mean"] if names is METRIC_NAMES else []),
                    "value": index + 81.25,
                }
            )
    refs.append(
        dict(
            refs[0],
            path=["provider_summary"],
            value={key: index + 81.25 for index, key in enumerate(PROVIDER_NAMES)},
        )
    )
    # Existing legal, unmapped fields must remain distinguishable, including
    # dictionary references; they may not collapse to a generic label.
    refs.append(
        dict(
            refs[0],
            path=["summary", "sample_count"],
            value={"sample_count": 0, "distance_covered_seconds": None},
        )
    )
    view["core_conclusions"] = [
        f.coaching_fixture.claim(
            "公开合成显示边界样例：仅检查字段名称与单位，不代表已验证业务来源。", refs
        )
    ]
    return view


def test_actual_metric_names_units_and_unmapped_fields_survive_both_formats(
    tmp_path, monkeypatch
):
    from pypdf import PdfReader

    from skills._shared.fit_weekly import report_markdown, report_pdf

    root, _, _ = f.setup(tmp_path, monkeypatch)
    base = revisions.create(root, f.END)
    view = metric_label_view(revisions.view(root, f.END, "ai", model_job.sha(base)))
    markdown = report_markdown.render(view).decode()
    text = "".join(
        p.extract_text() for p in PdfReader(io.BytesIO(report_pdf.render(view))).pages
    )
    for content in (markdown, text):
        # PDF line wraps are layout, not missing content; Markdown escapes keys.
        content = content.replace("\n", "").replace("\\_", "_")
        for names, prefix in (
            (METRIC_NAMES, "摘要 / 采样指标 / "),
            (PROVIDER_NAMES, "设备摘要 / "),
        ):
            for index, expected in enumerate(names.values()):
                suffix = " / 平均值" if names is METRIC_NAMES else ""
                assert (
                    f"字段 {prefix}{expected}{suffix}；记录值 {index + 81.25}"
                    in content
                )
        assert "字段 摘要 / sample_count" in content
        for index, expected in enumerate(PROVIDER_NAMES.values()):
            assert f"{expected}：{index + 81.25}" in content
        assert "sample_count：0" in content
        assert "distance_covered_seconds：缺失 / 未知" in content
        assert "来源字段" not in content


def test_regular_font_readable_times_and_supported_sources(tmp_path, monkeypatch):
    from pypdf import PdfReader
    from reportlab.pdfbase.ttfonts import TTFont

    from skills._shared.fit_weekly import report_pdf

    assert report_pdf.FONT.name == "TrainLabReportSans-Regular.ttf"
    face = TTFont("CheckReportRegular", str(report_pdf.FONT)).face
    assert face.name == b"TrainLabReportSans-Regular"
    root, _, _ = f.setup(
        tmp_path, monkeypatch, transform=f.supported_content, with_cadence=True
    )
    base = revisions.create(root, f.END)
    artifacts.render(root, f.END, "ai", model_job.sha(base))
    bundle = artifacts.read(root, f.END, "ai", model_job.sha(base))
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(bundle.pdf)).pages)
    for content in (bundle.markdown.decode(), text):
        assert "2026-08-02 07:00:00 UTC" in content
        assert "起点包含，终点不包含" in content
        assert "设备节律（转/分）" in content and "平均值" in content
        assert "记录值 88" in content
        assert "有来源支持" in content and "重复 2 次" in content
        assert "source_observation" not in content and "cadence_rpm" not in content
        assert "2026-08-02T07:00:00Z" not in content
        assert "{'" not in content and '"source"' not in content


def long_content(stage, output, payload):
    if stage == "summary":
        output["core_conclusions"][0]["text"] = (
            "公开合成长中文：现有记录可供观察，仍需结合适用条件。" * 30
        )
    else:
        w = output["days"][0]["workout"]
        w["steps"] = [
            {
                "repeat": 2,
                "steps": [
                    dict(
                        w["steps"][0]["steps"][0],
                        value=100,
                        instructions="公开合成长步骤，请在适用条件内观察动作。" * 35,
                    )
                ],
            }
            for _ in range(6)
        ]
        w["technical_notes"] = "课程末尾技术备注：放松肩颈。"
        w["stop_conditions"] = ["课程末尾停止条件：不适时停止。"]


def test_long_chinese_pdf_contains_complete_courses_and_embedded_font(
    tmp_path, monkeypatch
):
    from pypdf import PdfReader

    root, _, _ = f.setup(
        tmp_path,
        monkeypatch,
        transform=long_content,
        activity_name="公开合成长活动名称：河边步道与山谷观察" * 20,
    )
    base = revisions.create(root, f.END)
    artifacts.render(root, f.END, "ai", model_job.sha(base))
    bundle = artifacts.read(root, f.END, "ai", model_job.sha(base))
    pdf = PdfReader(io.BytesIO(bundle.pdf))
    text = "".join(p.extract_text() for p in pdf.pages)
    md = bundle.markdown.decode()
    for phrase in (
        "一、核心结论",
        "二、全运动清单与统计",
        "三、重点跑技",
        "四、其他运动",
        "五、计划对比",
        "六、固定七日计划",
        "七、数据局限与安全",
        "课程末尾技术备注",
        "课程末尾停止条件",
    ):
        assert phrase in text and phrase in md
    for day in bundle.plan["days"]:
        assert day["date"] in text and day["date"] in md
    assert "公开合成长活动名称" in text and "公开合成长活动名称" in md
    assert "source_observation" not in text
    assert "Explicit planned dose" not in text
    assert text.count("重复 2 次") == 6
    assert len(pdf.pages) >= 3
    assert any(
        "/FontFile2" in font.get_object().get("/FontDescriptor", {})
        for p in pdf.pages
        for font in p["/Resources"]["/Font"].values()
    )


@pytest.mark.parametrize("activities", [[], [("103", 300, None)]])
def test_no_activity_does_not_invent_zero_coverage_or_a_chart(
    tmp_path, monkeypatch, activities
):
    root, _, _ = f.setup(tmp_path, monkeypatch, activities=activities)
    base = revisions.create(root, f.END)
    artifacts.render(root, f.END, "ai", model_job.sha(base))
    bundle = artifacts.read(root, f.END, "ai", model_job.sha(base))
    md = bundle.markdown.decode()
    assert "已归属 FIT 活动：0" in md
    assert "无 FIT、归属待定：" + str(len(activities)) in md
    assert "没有可用运动统计" in md


def test_statistical_missingness_and_zero_are_distinct_in_both_formats(
    tmp_path, monkeypatch
):
    from copy import deepcopy

    from pypdf import PdfReader

    from skills._shared.fit_weekly import report_markdown, report_pdf

    root, _, _ = f.setup(tmp_path, monkeypatch)
    base = revisions.create(root, f.END)
    view = revisions.view(root, f.END, "ai", model_job.sha(base))
    # Public synthetic renderer boundary: already-projected statistics with
    # distinct observed zero, partial known total, and wholly unknown total.
    view = deepcopy(view)
    stats = view["facts"]["statistics"]
    stats[0]["distance_m"] = {
        "value": 0,
        "available_count": 1,
        "missing_count": 0,
        "status": "complete",
    }
    stats[0]["timer_seconds"] = {
        "value": 0,
        "available_count": 1,
        "missing_count": 0,
        "status": "complete",
    }
    stats[1]["distance_m"] = {
        "value": 250,
        "available_count": 1,
        "missing_count": 1,
        "status": "partial",
    }
    stats[1]["timer_seconds"] = {
        "value": None,
        "available_count": 0,
        "missing_count": 2,
        "status": "unknown",
    }
    markdown = report_markdown.render(view).decode()
    text = "".join(
        p.extract_text() for p in PdfReader(io.BytesIO(report_pdf.render(view))).pages
    )
    for content in (markdown, text):
        assert "0 米" in content and "250 米" in content
        assert "部分已知" in content and "缺失 / 未知" in content
        assert "完整" in content and "缺失 2" in content
