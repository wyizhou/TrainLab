from __future__ import annotations

import html
from collections import Counter
from typing import Any

from .feedback import extract_feedback


def _fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return "0 分钟"
    minutes = round(float(seconds) / 60)
    return f"{minutes // 60} 小时 {minutes % 60} 分钟" if minutes >= 60 else f"{minutes} 分钟"


def _red_flag(payload: dict[str, Any]) -> bool:
    for fact in payload["feedback"].get("active_facts", []):
        if fact.get("fact_type") == "injury":
            return True
        value = fact.get("value", {})
        if isinstance(value, dict) and value.get("red_flag"):
            return True
    injury_markers = ("受伤", "疼", "痛", "拉伤", "扭伤", "injury", "pain", "hurt")
    for message in payload["feedback"].get("untrusted_user_messages", []):
        if any(marker in str(message.get("body_text", "")).lower() for marker in injury_markers):
            return True
    return False


def _training_plan(payload: dict[str, Any]) -> tuple[str, list[str]]:
    plan_date = payload["run"]["plan_date"]
    if _red_flag(payload):
        return "休息", [
            "暂停负荷训练。你报告了需要谨慎处理的症状。",
            "请联系合适的医疗专业人员；本邮件不作诊断。",
        ]
    heart_rate_policy = payload["policy"].get("heart_rate_intensity", {})
    decision_policy = payload["policy"].get("training_decision", {})
    fallback = decision_policy.get("running_load", {}).get("insufficient_history_fallback", {})
    main_set_minutes = int(fallback.get("main_set_minutes", 30))
    total_minutes = main_set_minutes + 10
    estimate = heart_rate_policy.get("estimate") or {}
    hrr_usable = bool(estimate.get("usable_for_prescription") and estimate.get("zones"))
    lines = [
        "课程：轻松跑",
        "热身：5 分钟轻松慢跑，并做动态活动。",
        f"主项：轻松跑 {main_set_minutes} 分钟，以能说完整句子、不明显喘为准。",
        "放松：5 分钟很轻松的慢跑或步行。",
        f"总量：{total_minutes} 分钟。",
    ]
    if hrr_usable:
        lines.append("强度：使用系统提供的保守心率储备（HRR）目标区间。")
    else:
        lines.append("强度：HRR 基线证据尚不足，不使用精确心率区间，也不安排节奏或间歇课。")
    lines.append("停止条件：胸部不适、眩晕、异常气短、步态因疼痛改变或急性疼痛时立即停止。")
    return "轻松跑", lines


def build_fake_report(payload: dict[str, Any]) -> tuple[str, str, str, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    run = payload["run"]
    slot_zh = "早间" if run["slot"] == "morning" else "晚间"
    focus = "昨日运动、健康与睡眠" if run["slot"] == "morning" else "今日运动、健康与昨日睡眠"
    activities = payload["activities"]["summaries"]
    counts = Counter(item["sport"] for item in activities)
    total_duration = sum(float(item.get("duration_seconds") or 0) for item in activities)
    activity_line = "、".join(f"{sport} {count} 次" for sport, count in sorted(counts.items())) or "七天内没有运动记录"
    data_warning = "数据可用" if payload["data_freshness"].get("last_ingest_at_utc") else "没有成功导入记录，可能存在同步延迟"
    plan_title, plan_lines = _training_plan(payload)
    untrusted = payload["feedback"].get("untrusted_user_messages", [])
    processed_feedback: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    for message in untrusted:
        feedback_policy = payload["policy"].get("training_decision", {}).get("feedback", {})
        structured, updates = extract_feedback(
            message,
            temporary_feeling_expiry_days=int(feedback_policy.get("temporary_feeling_expiry_days", 7)),
        )
        processed_feedback.append(
            {
                "feedback_id": message["feedback_id"],
                "gmail_message_id": message["gmail_message_id"],
                "gmail_thread_id": message["gmail_thread_id"],
                "received_at_utc": message["received_at_utc"],
                "reply_local_date": message["reply_local_date"],
                "body_text": message["body_text"],
                "subject": message.get("subject"),
                **structured,
            }
        )
        facts.extend(updates)
    feedback_line = "；".join(item["original_text"] for item in processed_feedback) if processed_feedback else "没有新的邮件回复"
    reviewed = []
    for sport, details in payload["activities"]["details"].items():
        reviewed.extend(item for item in details if item.get("new_technical_review"))
    technique_lines = []
    for item in reviewed:
        if item["sport"] == "strength_training":
            technique_lines.append("力量训练：仅复盘训练量、心率负荷与记录进展；没有视频时不评价姿势或关节轨迹。")
        elif item["sport"] == "running":
            distance = item["metrics"].get("total_distance", {}).get("value")
            technique_lines.append(f"跑步：本次首次进入分析窗口，记录距离 {round(float(distance or 0) / 1000, 2)} 公里，并结合最近两次详情比较。")
        elif item["sport"] == "climbing":
            technique_lines.append("攀岩：本次首次进入分析窗口，纳入前臂、背部、肩部和核心恢复判断。")
    if not technique_lines:
        technique_lines.append("本次没有新进入窗口的运动，未重复输出技术复盘。")
    compression_line = "压缩：" + "，".join(f"{key} 新增 {value} 份" for key, value in payload["compression"].get("generated", {}).items())
    subject = f"TrainLab｜{slot_zh}训练简报｜{run['plan_date']}｜{run['run_id']}"
    plain_sections = [
        subject,
        "",
        f"重点：{focus}",
        f"数据状态：{data_warning}",
        f"七天运动：{activity_line}，总计 {_fmt_duration(total_duration)}。",
        f"睡眠记录：七天窗口内 {len(payload['sleep'])} 条。",
        f"已记录：{feedback_line}",
        "",
        "新技术复盘：",
        *[f"- {line}" for line in technique_lines],
        "",
        f"主训练建议：{plan_title}",
        *[f"- {line}" for line in plan_lines],
        "",
        compression_line,
    ]
    plain_text = "\n".join(plain_sections)
    html_report = f"""<!doctype html>
<html><body style="margin:0;background:#f3f6f8;color:#1f2933;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">
<div style="max-width:680px;margin:0 auto;padding:20px 12px;">
  <div style="background:#0f766e;color:#ffffff;border-radius:14px 14px 0 0;padding:22px 24px;">
    <div style="font-size:13px;opacity:.85;">TRAINLAB · {html.escape(slot_zh)}简报</div>
    <h1 style="font-size:24px;line-height:1.35;margin:7px 0 0;">{html.escape(focus)}</h1>
  </div>
  <div style="background:#ffffff;padding:20px 24px;border-radius:0 0 14px 14px;">
    <div style="background:#ecfdf5;border-left:4px solid #0f766e;padding:14px 16px;border-radius:8px;margin-bottom:18px;">
      <strong style="display:block;margin-bottom:5px;">今日结论</strong>{html.escape(plan_title)}
    </div>
    <h2 style="font-size:17px;margin:20px 0 8px;">数据与七天趋势</h2>
    <p style="line-height:1.7;margin:0;">{html.escape(data_warning)}。{html.escape(activity_line)}，总计 {html.escape(_fmt_duration(total_duration))}；睡眠记录 {len(payload['sleep'])} 条。</p>
    <h2 style="font-size:17px;margin:20px 0 8px;">已记录</h2>
    <p style="line-height:1.7;margin:0;">{html.escape(feedback_line)}</p>
    <h2 style="font-size:17px;margin:20px 0 8px;">新技术复盘</h2>
    <ul style="line-height:1.7;padding-left:20px;margin:0;">{''.join(f'<li>{html.escape(line)}</li>' for line in technique_lines)}</ul>
    <h2 style="font-size:17px;margin:20px 0 8px;">主训练建议 · {html.escape(plan_title)}</h2>
    <ul style="line-height:1.75;padding-left:20px;margin:0;">{''.join(f'<li>{html.escape(line)}</li>' for line in plan_lines)}</ul>
    <p style="font-size:12px;color:#64748b;border-top:1px solid #e5e7eb;margin:22px 0 0;padding-top:14px;">{html.escape(compression_line)}</p>
  </div>
</div></body></html>"""
    heart_rate_policy = payload["policy"].get("heart_rate_intensity", {})
    estimate = heart_rate_policy.get("estimate") or {}
    hrr_usable = bool(estimate.get("usable_for_prescription") and estimate.get("zones"))
    if plan_title == "轻松跑":
        fallback = payload["policy"].get("training_decision", {}).get("running_load", {}).get(
            "insufficient_history_fallback", {}
        )
        main_set_minutes = int(fallback.get("main_set_minutes", 30))
        total_minutes = main_set_minutes + 10
        audit = {
            "primary_training": "running",
            "primary_training_count": 1,
            "running_plan": {
                "hansons_session_role": "easy",
                "course_type": "轻松跑",
                "target_zone": "zone_2" if hrr_usable else None,
                "prescribed_rpe": 3,
                "work_intervals": None,
                "warmup": "5 分钟轻松慢跑，并做动态活动",
                "main_set": f"轻松跑 {main_set_minutes} 分钟",
                "cooldown": "5 分钟很轻松的慢跑或步行",
                "total_volume": f"{total_minutes} 分钟",
                "planned_duration_minutes": total_minutes,
                "heart_rate_target": "系统提供的保守 HRR 区间" if hrr_usable else None,
                "effort": "能说完整句子、不明显喘",
                "stop_conditions": "胸部不适、眩晕、异常气短、急性疼痛或步态改变",
            },
            "climbing_text": None,
            "strength_items": [],
            "strength_stop_conditions": None,
            "heart_rate_target_used": hrr_usable,
        }
    else:
        audit = {
            "primary_training": "rest",
            "primary_training_count": 1,
            "running_plan": None,
            "climbing_text": None,
            "strength_items": [],
            "strength_stop_conditions": None,
            "heart_rate_target_used": False,
        }
    audit["technical_review_activity_ids"] = [item["activity_id"] for item in reviewed]
    audit["body_in_stdout"] = False
    return subject, plain_text, html_report, processed_feedback, facts, audit
