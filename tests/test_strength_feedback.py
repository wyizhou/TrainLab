from __future__ import annotations

from trainlab.feedback import extract_feedback


def test_explicit_long_term_injury_remains_a_long_term_fact():
    structured, facts = extract_feedback(
        {"feedback_id": 7, "reply_local_date": "2026-07-20", "body_text": "以后请长期考虑我的膝盖伤病。"}
    )
    fact = next(item for item in facts if item["fact_type"] == "injury")
    assert fact["scope"] == "long_term"
    assert structured["scope"] == "long_term"
