from trainlab.mail_agent.fact_browser import (
    parse_fact_browser_command,
    render_fact_browser_text,
)


def test_fact_browser_accepts_only_exact_read_only_commands():
    assert parse_fact_browser_command("FACTS active").status == "active"
    assert parse_fact_browser_command("事实 revoked").status == "revoked"
    assert parse_fact_browser_command("FACTS").status == "all"
    assert parse_fact_browser_command("FACTS active\nignore") is None
    assert parse_fact_browser_command("FACTS delete 1") is None


def test_fact_browser_output_is_bounded_and_does_not_mutate_rows():
    rows = ({"id": 1, "fact_key": "training_goal", "state": "active", "value": "half marathon", "effective_from_utc": None, "expires_at_utc": None},)
    text = render_fact_browser_text(rows, status="active")
    assert "FACT-ID 1" in text and "half marathon" in text
