"""Deterministic overnight sleep attribution for the daily analysis contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable


@dataclass(frozen=True)
class SleepEpisode:
    session_id: int | str
    session_type: str
    start_utc: datetime
    end_utc: datetime


def _utc(value: str | datetime) -> datetime:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        raise ValueError("sleep_timestamp_requires_timezone")
    return parsed.astimezone(timezone.utc)


def select_main_sleep(
    sessions: Iterable[dict[str, Any] | SleepEpisode],
    report_date: date,
    *,
    as_of_utc: datetime,
    timezone_offset_hours: int = 8,
) -> tuple[SleepEpisode | None, str]:
    """Select exactly one completed main sleep ending on ``report_date``.

    The local interval normally starts on the previous local date and ends on
    the report date.  A main sleep that begins after midnight on the report
    date and ends later that morning is also valid.  Naps, future/unfinished
    episodes and multiple matches are never silently merged.
    """

    as_of = _utc(as_of_utc)
    from datetime import timedelta

    offset = timezone(timedelta(hours=timezone_offset_hours))
    matches: list[SleepEpisode] = []
    for raw in sessions:
        if isinstance(raw, SleepEpisode):
            episode = raw
        else:
            try:
                episode = SleepEpisode(
                    raw["session_id"],
                    str(raw["session_type"]),
                    _utc(raw["start_time_utc"]),
                    _utc(raw["end_time_utc"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
        if episode.session_type != "main_sleep":
            continue
        if not episode.start_utc < episode.end_utc <= as_of:
            continue
        start_local = episode.start_utc.astimezone(offset).date()
        end_local = episode.end_utc.astimezone(offset).date()
        previous_local = report_date.fromordinal(report_date.toordinal() - 1)
        if end_local == report_date and start_local in {previous_local, report_date}:
            matches.append(episode)
    if not matches:
        return None, "missing"
    if len(matches) > 1:
        return None, "ambiguous"
    return matches[0], "complete"


def attribute_samples(
    samples: Iterable[dict[str, Any]], episode: SleepEpisode | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split samples into the half-open sleep interval and ordinary-day rows."""

    if episode is None:
        return [], list(samples)
    inside: list[dict[str, Any]] = []
    outside: list[dict[str, Any]] = []
    for sample in samples:
        try:
            observed = _utc(sample["observed_at_utc"])
        except (KeyError, TypeError, ValueError):
            outside.append(sample)
            continue
        (inside if episode.start_utc <= observed < episode.end_utc else outside).append(
            sample
        )
    return inside, outside
