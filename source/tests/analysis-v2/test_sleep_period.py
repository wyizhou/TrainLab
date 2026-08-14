from datetime import date, datetime, timezone

from src.analysis.sleep_period import attribute_samples, select_main_sleep


def _session(session_id, kind, start, end):
    return {
        "session_id": session_id,
        "session_type": kind,
        "start_time_utc": start,
        "end_time_utc": end,
    }


def test_cross_midnight_main_sleep_is_attributed_to_wake_date():
    episode, state = select_main_sleep(
        [_session(1, "main_sleep", "2026-08-12T15:00:00Z", "2026-08-13T00:30:00Z")],
        date(2026, 8, 13),
        as_of_utc=datetime(2026, 8, 13, 2, tzinfo=timezone.utc),
    )
    assert state == "complete"
    assert episode and episode.session_id == 1


def test_nap_future_and_multiple_main_sleep_are_not_merged():
    sessions = [
        _session(1, "nap", "2026-08-12T22:00:00Z", "2026-08-12T23:00:00Z"),
        _session(2, "main_sleep", "2026-08-12T15:00:00Z", "2026-08-13T00:30:00Z"),
        _session(3, "main_sleep", "2026-08-12T15:30:00Z", "2026-08-13T00:45:00Z"),
    ]
    episode, state = select_main_sleep(
        sessions,
        date(2026, 8, 13),
        as_of_utc=datetime(2026, 8, 13, 2, tzinfo=timezone.utc),
    )
    assert episode is None and state == "ambiguous"


def test_sleep_sample_interval_is_half_open():
    episode, state = select_main_sleep(
        [_session(1, "main_sleep", "2026-08-12T15:00:00Z", "2026-08-13T00:30:00Z")],
        date(2026, 8, 13),
        as_of_utc=datetime(2026, 8, 13, 2, tzinfo=timezone.utc),
    )
    inside, outside = attribute_samples(
        [
            {"observed_at_utc": "2026-08-12T15:00:00Z"},
            {"observed_at_utc": "2026-08-13T00:29:59Z"},
            {"observed_at_utc": "2026-08-13T00:30:00Z"},
        ],
        episode,
    )
    assert state == "complete"
    assert len(inside) == 2 and len(outside) == 1


def test_main_sleep_starting_after_midnight_is_attributed_to_same_wake_date():
    episode, state = select_main_sleep(
        [_session(4, "main_sleep", "2026-08-13T01:00:00Z", "2026-08-13T08:00:00Z")],
        date(2026, 8, 13),
        as_of_utc=datetime(2026, 8, 13, 9, tzinfo=timezone.utc),
    )
    assert state == "complete"
    assert episode and episode.session_id == 4
