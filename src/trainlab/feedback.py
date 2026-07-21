from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from .util import iso_utc


LONG_TERM_MARKERS = ("长期", "以后", "今后", "目标改为", "permanently", "from now on", "long term")
INJURY_MARKERS = ("受伤", "伤病", "疼", "痛", "拉伤", "扭伤", "injury", "pain", "hurt")
RED_FLAG_MARKERS = ("胸痛", "胸部不适", "晕厥", "晕倒", "急性受伤", "异常气短", "chest pain", "faint", "acute injury")
COMPLETED_MARKERS = ("完成", "做了", "跑了", "攀岩了", "力量训练", "finished", "completed", "did a run")
FEELING_MARKERS = ("感觉", "感受", "疲劳", "酸", "状态", "felt", "feeling", "tired", "sore")


def extract_feedback(
    message: dict[str, Any],
    *,
    temporary_feeling_expiry_days: int = 7,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    body = str(message.get("body_text", "")).strip()
    lowered = body.lower()
    scope = "long_term" if any(marker in lowered for marker in LONG_TERM_MARKERS) else "temporary"
    local_date = str(message["reply_local_date"])
    facts: list[dict[str, Any]] = []
    categories: list[str] = []
    if any(marker in lowered for marker in INJURY_MARKERS):
        categories.append("injury")
        facts.append(
            {
                "fact_type": "injury",
                "fact_key": f"reported_injury_{message['feedback_id']}",
                "value": {"report": body, "red_flag": any(marker in lowered for marker in RED_FLAG_MARKERS)},
                "scope": scope,
                "effective_local_date": local_date,
                "expires_local_date": None,
                "source_feedback_id": message["feedback_id"],
                "source_gmail_message_id": message.get("gmail_message_id"),
            }
        )
    if any(marker in lowered for marker in FEELING_MARKERS):
        categories.append("feeling")
        expires = (
            None
            if scope == "long_term"
            else (date.fromisoformat(local_date) + timedelta(days=temporary_feeling_expiry_days)).isoformat()
        )
        facts.append(
            {
                "fact_type": "feeling",
                "fact_key": f"reported_feeling_{message['feedback_id']}",
                "value": {"report": body, "red_flag": False},
                "scope": scope,
                "effective_local_date": local_date,
                "expires_local_date": expires,
                "source_feedback_id": message["feedback_id"],
                "source_gmail_message_id": message.get("gmail_message_id"),
            }
        )
    if any(marker in lowered for marker in COMPLETED_MARKERS):
        categories.append("completed_activity")
        facts.append(
            {
                "fact_type": "completed_activity",
                "fact_key": f"reported_completed_{message['feedback_id']}",
                "value": {"report": body, "red_flag": False},
                "scope": "temporary",
                "effective_local_date": local_date,
                "expires_local_date": local_date,
                "source_feedback_id": message["feedback_id"],
                "source_gmail_message_id": message.get("gmail_message_id"),
            }
        )
    structured = {"categories": categories or ["general_note"], "original_text": body, "scope": scope}
    return structured, facts


def apply_result_feedback(connection, result: dict[str, Any]) -> None:
    for processed in result.get("processed_feedback", []):
        feedback_id = processed.get("feedback_id")
        if feedback_id is not None and connection.execute("SELECT 1 FROM feedback_messages WHERE id=?", (feedback_id,)).fetchone():
            connection.execute(
                "UPDATE feedback_messages SET structured_json=?, processed_at_utc=? WHERE id=?",
                (json.dumps(processed, ensure_ascii=False, sort_keys=True), iso_utc(), feedback_id),
            )
        else:
            connection.execute(
                """INSERT INTO feedback_messages(
                       gmail_message_id, gmail_thread_id, received_at_utc, reply_local_date,
                       subject, body_text, structured_json, processed_at_utc, injection_risk
                   ) VALUES(?,?,?,?,?,?,?,?,0)
                   ON CONFLICT(gmail_message_id) DO UPDATE SET
                       structured_json=excluded.structured_json, processed_at_utc=excluded.processed_at_utc""",
                (
                    processed["gmail_message_id"],
                    processed["gmail_thread_id"],
                    processed["received_at_utc"],
                    processed["reply_local_date"],
                    processed.get("subject"),
                    processed["body_text"],
                    json.dumps(processed, ensure_ascii=False, sort_keys=True),
                    iso_utc(),
                ),
            )
    for fact in result.get("fact_updates", []):
        scope = fact.get("scope", "temporary")
        if scope == "long_term":
            source_text = json.dumps(fact.get("value", {}), ensure_ascii=False).lower()
            if not any(marker in source_text for marker in LONG_TERM_MARKERS):
                scope = "temporary"
        source_feedback_id = fact.get("source_feedback_id")
        if source_feedback_id is None and fact.get("source_gmail_message_id"):
            source = connection.execute(
                "SELECT id FROM feedback_messages WHERE gmail_message_id=?", (fact["source_gmail_message_id"],)
            ).fetchone()
            source_feedback_id = int(source["id"]) if source else None
        connection.execute(
            """INSERT INTO user_facts(
                   fact_type, fact_key, value_json, effective_local_date, expires_local_date,
                   is_active, scope, source_feedback_id, created_at_utc
               ) VALUES(?,?,?,?,?,1,?,?,?)""",
            (
                fact.get("fact_type", "general_note"),
                fact.get("fact_key", f"fact_{iso_utc()}"),
                json.dumps(fact.get("value", {}), ensure_ascii=False, sort_keys=True),
                fact["effective_local_date"],
                fact.get("expires_local_date"),
                scope,
                source_feedback_id,
                iso_utc(),
            ),
        )
