"""UTC and China-time scheduling contracts for ADHOC-0031."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

CHINA_TZ = ZoneInfo("Asia/Shanghai")
DAILY_ACTIVITY_REPORT_LOCAL_TIME = time(hour=4, minute=0, second=0)
FIRST_SYNC_LOOKBACK = timedelta(days=7)
SYNC_INTERVAL = timedelta(hours=3)
NO_ACTIVITY_WEEKLY_SUMMARY = "本周无任何运动记录"
UTC_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def format_utc(value: datetime) -> str:
    return ensure_utc(value).strftime(UTC_TIMESTAMP_FORMAT)


def utc_fit_date(value: datetime | None) -> str | None:
    if value is None:
        return None
    return ensure_utc(value).strftime("%Y%m%d")


def initial_sync_window(now_utc: datetime) -> tuple[datetime, datetime]:
    end = ensure_utc(now_utc)
    return (end - FIRST_SYNC_LOOKBACK, end)


def next_activity_report_run_utc(now_utc: datetime) -> datetime:
    now_local = ensure_utc(now_utc).astimezone(CHINA_TZ)
    candidate_local = datetime.combine(
        now_local.date(),
        DAILY_ACTIVITY_REPORT_LOCAL_TIME,
        tzinfo=CHINA_TZ,
    )
    if now_local >= candidate_local:
        candidate_local = candidate_local + timedelta(days=1)
    return candidate_local.astimezone(UTC)


def weekly_window(run_time_utc: datetime) -> tuple[datetime, datetime]:
    end = ensure_utc(run_time_utc)
    return (end - FIRST_SYNC_LOOKBACK, end)
