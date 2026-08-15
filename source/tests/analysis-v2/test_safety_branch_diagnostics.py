from __future__ import annotations

from copy import deepcopy

import pytest

from src.analysis.daily import daily_primary_item_contract
from src.analysis.result_validation import (
    _candidate_for_safety,
    _safety_candidate_error_code,
)
from src.analysis.safety_rules import SafetyRuleError, evaluate_training_safety


def _request(item: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "1",
        "subject_id": 1,
        "advice_local_date": "2026-07-24",
        "as_of_utc": "2026-07-24T00:00:00Z",
        "zone_evidence": [],
        "safety_signals": [],
        "quality_sessions": [],
        "substitution": None,
        "primary_items": [item],
    }


def _message(item: dict[str, object]) -> str:
    with pytest.raises(SafetyRuleError) as caught:
        evaluate_training_safety(_request(item))
    return str(caught.value)


def test_branch_diagnostics_identify_climbing_required_and_pattern_errors() -> None:
    missing = _message({"activity_kind": "climbing"})
    invalid_token = _message({"activity_kind": "climbing", "rationale": "用户自由文本"})
    assert missing.endswith("primary_items.0.rationale:required")
    assert invalid_token.endswith("primary_items.0.rationale:pattern")
    assert "用户自由文本" not in invalid_token


def test_branch_diagnostics_identify_running_type_errors() -> None:
    running = _candidate_for_safety(daily_primary_item_contract()["running_template"])
    malformed = deepcopy(running)
    malformed["planned_duration_minutes"] = "30"
    message = _message(malformed)
    assert message.endswith("primary_items.0.planned_duration_minutes:type")
    assert "30" not in message


def test_result_error_codes_preserve_schema_reason_without_candidate_content() -> None:
    messages = [
        _message({"activity_kind": "climbing"}),
        _message({"activity_kind": "climbing", "rationale": "自由文本"}),
    ]
    codes = [
        _safety_candidate_error_code(SafetyRuleError(message)) for message in messages
    ]
    assert codes[0] != codes[1]
    assert codes[0].endswith("_required")
    assert codes[1].endswith("_pattern")
    assert all("自由文本" not in code for code in codes)
