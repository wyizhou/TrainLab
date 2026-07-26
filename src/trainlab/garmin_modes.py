"""Pure planning primitives for Garmin full, incremental, and snapshot runs.

This module knows date and cursor semantics only.  Fetching, archiving, parsing,
and projection remain in the single collection pipeline in ``garmin.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal, Mapping, Sequence


CollectionMode = Literal["full", "incremental", "snapshot"]


@dataclass(frozen=True)
class ResourceDateWindow:
    resource_kind: str
    start: date
    through: date


@dataclass(frozen=True)
class CollectionModePlan:
    mode: CollectionMode
    health_windows: tuple[ResourceDateWindow, ...]
    activity_start: date
    activity_through: date
    activity_history_unbounded: bool
    effective_start: date
    effective_through: date
    snapshot: bool


def build_collection_mode_plan(
    *,
    mode: CollectionMode,
    today_local: date,
    history_start_date: str,
    requested_health_from: str | None,
    requested_through: str | None,
    requested_snapshot_date: str | None,
    health_resources: Sequence[str],
    complete_through_by_resource: Mapping[str, str | None],
    lookback_days: int,
) -> CollectionModePlan:
    """Build deterministic per-resource work windows.

    Completed-day modes are capped at yesterday.  Incremental lookback is
    anchored independently to each resource's continuous cursor; a resource
    without a cursor starts at the configured history boundary.
    """
    if lookback_days < 1:
        raise ValueError("lookback_days_out_of_range")
    history_start = date.fromisoformat(history_start_date)
    yesterday = today_local - timedelta(days=1)

    if mode == "snapshot":
        snapshot_day = date.fromisoformat(
            requested_snapshot_date or today_local.isoformat()
        )
        if snapshot_day > today_local:
            raise ValueError("snapshot_date_in_future")
        windows = tuple(
            ResourceDateWindow(resource, snapshot_day, snapshot_day)
            for resource in health_resources
        )
        return CollectionModePlan(
            mode=mode,
            health_windows=windows,
            activity_start=snapshot_day,
            activity_through=snapshot_day,
            activity_history_unbounded=False,
            effective_start=snapshot_day,
            effective_through=snapshot_day,
            snapshot=True,
        )

    through = date.fromisoformat(requested_through) if requested_through else yesterday
    if through > yesterday:
        raise ValueError("completed_mode_through_must_be_before_today")
    if history_start > through:
        raise ValueError("sync_range_start_after_through")

    if mode == "full":
        start = date.fromisoformat(requested_health_from) if requested_health_from else history_start
        if start > through:
            raise ValueError("sync_range_start_after_through")
        windows = tuple(
            ResourceDateWindow(resource, start, through)
            for resource in health_resources
        )
        return CollectionModePlan(
            mode=mode,
            health_windows=windows,
            activity_start=start,
            activity_through=through,
            activity_history_unbounded=True,
            effective_start=start,
            effective_through=through,
            snapshot=False,
        )

    windows_list: list[ResourceDateWindow] = []
    for resource in health_resources:
        cursor_value = complete_through_by_resource.get(resource)
        if cursor_value:
            cursor = min(date.fromisoformat(cursor_value), through)
            start = max(
                history_start,
                cursor - timedelta(days=lookback_days - 1),
            )
        else:
            start = history_start
        if start <= through:
            windows_list.append(ResourceDateWindow(resource, start, through))

    activity_start = max(
        history_start,
        through - timedelta(days=lookback_days - 1),
    )
    effective_candidates = [activity_start]
    effective_candidates.extend(window.start for window in windows_list)
    return CollectionModePlan(
        mode=mode,
        health_windows=tuple(windows_list),
        activity_start=activity_start,
        activity_through=through,
        activity_history_unbounded=False,
        effective_start=min(effective_candidates),
        effective_through=through,
        snapshot=False,
    )
