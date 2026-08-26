#!/usr/bin/env python3
"""Single fail-closed gate for reader-visible Coaching Utility v2 text."""

from __future__ import annotations

import re
from collections.abc import Iterator

CHINESE_HEART_RATE_PRESCRIPTION_WORDS = (
    r"目标|最大|阈值|区间|分区|范围|区带|上下限|上限|下限|控制|提高|保持"
)

HEART_RATE_PRESCRIPTION_PATTERNS = (
    # ASCII lookarounds deliberately treat adjacent Chinese text as a separator.
    re.compile(
        r"(?<![A-Za-z0-9])(?:zone(?:[\s_-]*[1-5])?|z[\s_-]*[1-5])"
        r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<![A-Za-z0-9])(?:maximum|max|target|threshold)[\s_:\-]*"
        r"(?:heart[\s_:\-]*rate|hr)"
        r"(?![A-Za-z0-9])|"
        r"(?<![A-Za-z0-9])(?:heart[\s_:\-]*rate|hr)[\s_:\-]*"
        r"(?:maximum|max|target|threshold)"
        r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<![A-Za-z0-9])(?:\d{1,3}\s*%\s*)?"
        r"(?:hr[\s_-]*max|max[\s_-]*hr)"
        r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    ),
    re.compile(
        r"乳酸阈值|(?<![A-Za-z0-9])lactate[\s_-]*threshold(?![A-Za-z0-9])",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:{CHINESE_HEART_RATE_PRESCRIPTION_WORDS})心率|"
        rf"心率(?:{CHINESE_HEART_RATE_PRESCRIPTION_WORDS}|区)|"
        rf"(?:目标|建议|控制|提高|保持).{{0,8}}心率|"
        rf"心率.{{0,8}}(?:目标|建议|控制|提高|保持)",
        re.IGNORECASE,
    ),
    re.compile(
        r"heart_rate_zone|target_bpm|max_heart_rate|threshold_bpm", re.IGNORECASE
    ),
)
BPM_VALUE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:\d{2,3}(?:\.\d+)?\s*)?bpm(?:\s*\d{2,3}(?:\.\d+)?)?"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)
OBSERVED_BPM_FACT_PATTERN = re.compile(
    r"(?:静息心率|活动(?:平均|最高|最大)心率|平均心率|最高心率)"
    r"\s*(?:为|是|：|:)?\s*\d{2,3}(?:\.\d+)?"
    r"(?:\s*(?:至|[-~～–—])\s*\d{2,3}(?:\.\d+)?)?\s*bpm",
    re.IGNORECASE,
)
BPM_PRESCRIPTION_CONTEXT_PATTERN = re.compile(
    r"目标|建议|控制|保持在|不得超过|不低于|至少|上限|下限|区间|范围|处方|执行",
    re.IGNORECASE,
)
OBSERVED_BPM_PRESCRIPTION_SENTENCE_PATTERN = re.compile(
    r"目标|建议|控制|必须|应当|达到|保持|"
    r"不得超过|不低于|至少|上限|下限|区间|范围|处方|作为.{0,12}(?:目标|执行)",
    re.IGNORECASE,
)
ENGINEERING_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:schema_version|raw_file_id|evidence_ref|sha256|provider_calls|"
    r"output_id|content_json|skill_run_id|error_code|lineage_json|logical_key|"
    r"dedupe_key|workflow_key|revision_no|inventory_id|activity_inventory_id|"
    r"run_id|request_id)(?![A-Za-z0-9])|(?:/private/|/Volumes/)",
    re.IGNORECASE,
)
COURSE_HEART_RATE_PATTERN = re.compile(
    r"心率|(?<![A-Za-z0-9])(?:heart[\s_:\-]*rate|bpm|zone|z[1-5]|hr[\s_-]*max|"
    r"max[\s_-]*hr|target[\s_:\-]*hr|乳酸阈值|lactate[\s_-]*threshold)"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)
    elif isinstance(value, str):
        yield value


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    # A semicolon can still connect an observation to a prescription clause.
    separators = ".。!?！？\n"
    left = max((text.rfind(mark, 0, start) for mark in separators), default=-1) + 1
    right_candidates = [
        position for mark in separators if (position := text.find(mark, end)) >= 0
    ]
    right = min(right_candidates, default=len(text))
    return left, right


def _redact_allowed_observed_bpm(text: str) -> str:
    """Hide complete historical observations before scanning the remaining text."""
    residual = list(text)
    for match in OBSERVED_BPM_FACT_PATTERN.finditer(text):
        sentence_left, sentence_right = _sentence_bounds(
            text, match.start(), match.end()
        )
        nearby = text[
            max(sentence_left, match.start() - 24) : min(
                sentence_right, match.end() + 12
            )
        ]
        sentence = text[sentence_left:sentence_right]
        if BPM_PRESCRIPTION_CONTEXT_PATTERN.search(
            nearby
        ) or OBSERVED_BPM_PRESCRIPTION_SENTENCE_PATTERN.search(sentence):
            continue
        residual[match.start() : match.end()] = " " * (match.end() - match.start())
    return "".join(residual)


def validate_reader_visible_text(
    value: object, *, allow_observed_bpm: bool = False
) -> list[str]:
    """Reject prescription language and internal identifiers in visible values."""

    errors: set[str] = set()
    for text in _strings(value):
        prescription_text = (
            _redact_allowed_observed_bpm(text) if allow_observed_bpm else text
        )
        if any(
            pattern.search(prescription_text)
            for pattern in HEART_RATE_PRESCRIPTION_PATTERNS
        ) or BPM_VALUE_PATTERN.search(prescription_text):
            errors.add("heart_rate_prescription_forbidden")
        if ENGINEERING_IDENTIFIER_PATTERN.search(text):
            errors.add("engineering_content_forbidden")
    return sorted(errors)


def validate_health_visible_text(value: object) -> list[str]:
    """Allow labelled observed BPM facts only inside an explicit health field."""

    return validate_narrative_visible_text(value)


def validate_narrative_visible_text(value: object) -> list[str]:
    """Allow complete historical observations in non-course coaching narrative."""

    return validate_reader_visible_text(value, allow_observed_bpm=True)


def require_reader_visible_text(value: object) -> None:
    errors = validate_reader_visible_text(value)
    if errors:
        raise ValueError(errors[0])


def require_health_visible_text(value: object) -> None:
    errors = validate_health_visible_text(value)
    if errors:
        raise ValueError(errors[0])


def require_narrative_visible_text(value: object) -> None:
    errors = validate_narrative_visible_text(value)
    if errors:
        raise ValueError(errors[0])


def require_course_visible_text(value: object) -> None:
    """Course instructions never contain observed or prescribed heart-rate text."""

    if any(COURSE_HEART_RATE_PATTERN.search(text) for text in _strings(value)):
        raise ValueError("heart_rate_prescription_forbidden")
    require_reader_visible_text(value)
