"""Public synthetic coaching results, never derived from private activity data."""

from copy import deepcopy


def claim(text="资料不足，无法判断。", evidence=None):
    return {
        "status": "supported" if evidence else "unknown",
        "text": text,
        "evidence": evidence or [],
        "conditions": "仅适用于所引记录。",
        "method": "source_observation",
        "limitations": ["样本有限。"],
    }


def reference(activity, path=None, value=None):
    session = activity["sessions"][0]
    path = path or ["summary", "distance_m"]
    if value is None:
        value = session
        for part in path:
            value = value[part]
    return {
        "source": "current",
        "activity_ref": activity["activity_ref"],
        "fit_sha256": activity["fit_sha256"],
        "session_ordinal": session["session_ordinal"],
        "period_end_utc": None,
        "request_sha256": None,
        "path": path,
        "value": value,
    }


def workout(kind="easy", unit="seconds", value=1200):
    effort = "hard" if kind in ("tempo", "intervals", "long") else "easy"
    return {
        "kind": kind,
        "hard_load": effort == "hard",
        "purpose": "练习平稳跑步。",
        "dose": {"unit": unit, "value": value},
        "steps": [
            {
                "repeat": 1,
                "steps": [
                    {
                        "phase": "run",
                        "unit": unit,
                        "value": value,
                        "effort": effort,
                        "rpe": 3,
                        "instructions": "保持动作自然。",
                    }
                ],
            }
        ],
        "technical_notes": "放松肩颈。",
        "stop_conditions": ["不适时停止。"],
    }


def plan():
    return {
        "schema_version": "fit_running_plan_v1",
        "rationale": claim(),
        "days": [
            {"kind": "run", "workout": workout()}
            if i in (0, 3, 6)
            else {"kind": "rest", "workout": None}
            for i in range(7)
        ],
        "progression_limitations": ["无可比较历史，距离与强度变化未知。"],
        "policy": {
            "fixed_seven_days": True,
            "make_up_sessions": False,
            "daily_adjustments": False,
        },
    }


def summary(payload):
    other = [
        {
            "activity_ref": a["activity_ref"],
            "session_ordinal": s["session_ordinal"],
            "explanation": claim(),
        }
        for a in payload["current_week"]["activities"]
        for s in a["sessions"]
        if s["sport"] != "running"
    ]
    return {
        "schema_version": "fit_sports_summary_v1",
        "core_conclusions": [claim()],
        "running_analysis": {
            "overview": claim(),
            "technique": [],
            "plan_comparison": claim(),
        },
        "other_sports": other,
        "data_limitations": ["只包含已冻结记录。"],
        "safety": {
            "performance_is_not_health_clearance": True,
            "note": "运动表现不能证明没有健康风险。",
        },
    }


def clone(value):
    return deepcopy(value)
