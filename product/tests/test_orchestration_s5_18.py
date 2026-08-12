from __future__ import annotations

import pytest

from trainlab.orchestration.shadow import (
    ShadowComparator,
    ShadowError,
    ShadowStep,
)


def morning(date: str) -> tuple[ShadowStep, ...]:
    key = f"morning:7:{date}"
    return (
        ShadowStep(key, "collection", "garmin", "incremental", date),
        ShadowStep(key, "daily", "analysis", "daily", date),
    )


class Source:
    shadow_safe = True

    def __init__(self, expected, observed):
        self._expected, self._observed = expected, observed

    def expected_steps(self):
        return self._expected

    def observed_steps(self):
        return self._observed


def test_consecutive_morning_restart_replay_matches_without_external_calls() -> None:
    steps = morning("2026-07-26") + morning("2026-07-27")
    report = ShadowComparator().compare(Source(steps, reversed(steps)))
    assert report.status == "matched"
    assert report.external_calls == 0
    assert report.expected_sha256 == report.observed_sha256


def test_sunday_collection_is_single_and_daily_weekly_are_independent() -> None:
    key = "weekly:7:2026-07-26"
    steps = (
        ShadowStep(key, "collection", "garmin", "incremental", "2026-07-26"),
        ShadowStep(key, "daily", "analysis", "daily", "2026-07-26"),
        ShadowStep(key, "weekly", "analysis", "weekly", "2026-07-26"),
    )
    assert ShadowComparator().compare(Source(steps, steps)).status == "matched"


def test_mail_or_deferred_difference_is_explicit_not_silently_accepted() -> None:
    expected = (
        ShadowStep("mail-poll:7:window-1", "mail", "mail", "run", "window-1"),
        ShadowStep("mail-poll:7:window-1", "revision", "analysis", "revise_plan", "91"),
    )
    report = ShadowComparator().compare(Source(expected, expected[:1]))
    assert report.status == "different"
    assert report.differences[0].category == "missing"


def test_live_capable_adapter_is_rejected() -> None:
    source = Source((), ())
    source.shadow_safe = False
    with pytest.raises(ShadowError, match="shadow_live_adapter_forbidden"):
        ShadowComparator().compare(source)
