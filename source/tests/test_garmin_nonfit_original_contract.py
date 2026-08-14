"""Offline contract for ORIGINAL archives that Garmin labels as non-FIT."""

from __future__ import annotations

import copy
import io
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import fitdecode
import pytest

from src.foundation import FoundationConfig, FoundationRequest, FoundationTool
from src.garmin import GarminCollectionTool, GarminConfig, SyncRequest
from tests.fixtures.synthetic_fit import SYNTHETIC_FITS

FIT_BYTES = SYNTHETIC_FITS["Running.fit"]


def _fit_start() -> str:
    with fitdecode.FitReader(io.BytesIO(FIT_BYTES), check_crc=True) as reader:
        for frame in reader:
            if isinstance(frame, fitdecode.FitDataMessage) and frame.name == "session":
                return (
                    next(
                        field.value
                        for field in frame.fields
                        if field.name == "start_time"
                    )
                    .isoformat()
                    .replace("+00:00", "Z")
                )
    raise AssertionError("running fixture has no session")


class NonFitOriginalTransport:
    """A TCX-labelled activity that later becomes FIT-labelled by Connect."""

    def __init__(self, format_key: str) -> None:
        self.start = _fit_start()
        self.summary: dict[str, Any] = {
            "activityId": 1,
            "activityName": "non-fit-original-fixture",
            "activityType": {"typeKey": "running"},
            "startTimeGMT": self.start,
            "duration": 600,
            "movingDuration": 590,
            "distance": 2_000,
            "metadataDTO": {"fileFormat": {"formatKey": format_key}},
        }
        self.original_calls = 0
        # This is deliberately not a FIT/ZIP payload.  It is nevertheless
        # immutable ORIGINAL evidence and must be retained by its real format.
        self.original = (
            b"<TrainingCenterDatabase/>" if format_key == "tcx" else b"<gpx/>"
        )

    def login(self) -> None:
        return None

    def identity(self) -> str:
        return "l2-nonfit-original"

    def fetch_health(self, *_args: Any) -> list[Any]:
        return []

    def fetch_range(self, *_args: Any) -> list[Any]:
        return []

    def fetch_account(self, *_args: Any) -> list[Any]:
        return []

    def list_activities(self, *_args: Any) -> list[dict[str, Any]]:
        return [{"activityId": 1, "startTimeGMT": self.start}]

    def activity_summary(self, _activity_id: str) -> dict[str, Any]:
        return copy.deepcopy(self.summary)

    def activity_original(self, _activity_id: str) -> bytes:
        self.original_calls += 1
        return self.original

    def activity_extra(self, _activity_id: str, role: str) -> Any:
        assert role == "details_json_fallback"
        start_ms = (
            datetime.fromisoformat(self.start.replace("Z", "+00:00")).timestamp() * 1000
        )
        return {
            "activityId": 1,
            "points": [
                {"directTimestamp": start_ms, "directHeartRate": 120},
                {"directTimestamp": start_ms + 1_000, "directHeartRate": 121},
            ],
        }


def _setup(
    tmp_path: Path,
    format_key: str,
) -> tuple[GarminCollectionTool, NonFitOriginalTransport, FoundationConfig]:
    root = tmp_path / "data"
    foundation = FoundationConfig(
        root,
        root / "data.db",
        root / "raw",
        root / "state",
        root / "state/ready",
        root / "state/locks/foundation.lock",
    )
    assert (
        FoundationTool(foundation)
        .execute(
            FoundationRequest("init", "l2-nonfit-original", "2026-01-01T00:00:00Z")
        )
        .status
        == "initialized"
    )
    transport = NonFitOriginalTransport(format_key)
    tool = GarminCollectionTool(
        GarminConfig(
            foundation.database_path,
            foundation.raw_root,
            foundation.state_root,
            "2026-01-01",
            request_min_interval_ms=0,
        ),
        transport,
        sleep=lambda _seconds: None,
        clock=lambda: datetime(2026, 7, 20),
        monotonic=lambda: 1_000.0,
    )
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    return tool, transport, foundation


def _sync(tool: GarminCollectionTool, invocation: str, resources: tuple[str, ...]):
    return tool.execute(
        SyncRequest(
            "repair",
            through_local_date="2026-07-19",
            activity_ids=("1",),
            resource_kinds=resources,
            invocation_id=invocation,
        )
    )


@pytest.mark.parametrize("format_key", ("tcx", "gpx"))
def test_nonfit_original_is_retained_without_a_fit_gap_and_later_fit_metadata_can_promote(
    tmp_path: Path,
    format_key: str,
) -> None:
    """A TCX/GPX ORIGINAL is evidence, not a failed FIT download."""
    tool, transport, foundation = _setup(tmp_path, format_key)

    first = _sync(
        tool,
        f"{format_key}-nonfit-first",
        ("activity_fit", "activity_details_fallback"),
    )
    # The activity remains deliberately partial because Connect chart data is
    # the bounded fallback rather than a FIT sensor stream.
    assert first.status == "partial"
    assert first.counts["not_available"] == 1
    assert transport.original_calls == 1
    with sqlite3.connect(foundation.database_path) as conn:
        assert (
            conn.execute(
                "SELECT status FROM garmin_sync_items WHERE resource_kind='activity_fit'"
            ).fetchone()[0]
            == "not_available"
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM garmin_sync_gaps WHERE resource_kind='activity_fit'"
            ).fetchone()[0]
            == 0
        )
        raw_paths = conn.execute(
            "SELECT relative_path FROM raw_objects WHERE relative_path LIKE ?",
            (f"%.{format_key}",),
        ).fetchall()
        assert len(raw_paths) == 1
        assert not conn.execute(
            "SELECT 1 FROM raw_objects WHERE relative_path LIKE '%.zip'"
        ).fetchone()
        assert (
            conn.execute(
                "SELECT count(*) FROM source_revisions WHERE resource_kind='activity_summary'"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM activity_samples WHERE stream_kind='connect_chart'"
            ).fetchone()[0]
            == 2
        )

    repeated = _sync(
        tool,
        f"{format_key}-nonfit-repeat",
        ("activity_fit", "activity_details_fallback"),
    )
    assert repeated.status == "partial"
    assert transport.original_calls == 1
    with sqlite3.connect(foundation.database_path) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM garmin_sync_gaps WHERE resource_kind='activity_fit'"
            ).fetchone()[0]
            == 0
        )

    transport.summary["metadataDTO"]["fileFormat"]["formatKey"] = "fit"
    transport.original = FIT_BYTES
    promoted = _sync(
        tool, f"{format_key}-fit-promote-after-metadata-change", ("activity_fit",)
    )
    assert promoted.status == "succeeded"
    assert transport.original_calls == 2
    with sqlite3.connect(foundation.database_path) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM activity_source_revisions "
                "WHERE source_role='activity_fit' AND is_active=1"
            ).fetchone()[0]
            == 1
        )
        # Existing fallback evidence stays immutable after FIT becomes canonical.
        assert (
            conn.execute(
                "SELECT count(*) FROM activity_samples WHERE stream_kind='connect_chart'"
            ).fetchone()[0]
            == 2
        )
