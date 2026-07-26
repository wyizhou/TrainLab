"""L2-14 repair routing, offline recovery, audit evidence, and local status."""
from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.garmin import (
    GarminCollectionTool, GarminConfig, SyncReceipt, SyncRequest, stable_json,
)


class RepairTransport:
    def __init__(self) -> None:
        self.login_calls = 0
        self.health_calls = 0
        self.steps = 1234

    def login(self) -> None:
        self.login_calls += 1

    def identity(self) -> str:
        return "l2-14-fixture"

    def fetch_account(self, *_args: object) -> list[object]:
        return []

    def fetch_health(self, resource: str, day: str) -> dict[str, object]:
        self.health_calls += 1
        assert resource == "steps"
        return {"calendarDate": day, "totalSteps": self.steps}

    def fetch_range(self, *_args: object) -> list[object]:
        return []

    def list_activities(self, *_args: object) -> list[object]:
        return []

    def activity_summary(self, _activity_id: str) -> dict[str, object]:
        raise AssertionError("no activity provider call expected")

    def activity_original(self, _activity_id: str) -> bytes:
        raise AssertionError("no FIT provider call expected")

    def activity_extra(self, _activity_id: str, _role: str) -> object:
        raise AssertionError("no enrichment provider call expected")


def _setup(tmp_path: Path) -> tuple[GarminConfig, GarminCollectionTool, RepairTransport]:
    root = tmp_path / "data"
    foundation = FoundationConfig(
        root, root / "data.db", root / "raw", root / "state",
        root / "state/ready.json", root / "state/locks/foundation.lock",
    )
    assert FoundationTool(foundation).execute(
        FoundationRequest("init", "l2-14", "2026-01-01T00:00:00Z")
    ).status == "initialized"
    config = GarminConfig(
        foundation.database_path, foundation.raw_root, foundation.state_root,
        "2026-04-01", request_min_interval_ms=0,
    )
    transport = RepairTransport()
    tool = GarminCollectionTool(
        config, transport, sleep=lambda _seconds: None,
        clock=lambda: datetime(2026, 4, 17, 7, 0, 0),
        monotonic=lambda: 1000.0,
    )
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    return config, tool, transport


def _refetch_steps(tool: GarminCollectionTool, invocation: str) -> None:
    result = tool.execute(SyncRequest(
        "repair", health_from_local_date="2026-04-15",
        through_local_date="2026-04-15", resource_kinds=("steps",),
        repair_strategy="refetch", invocation_id=invocation,
    ))
    assert result.status == "succeeded", result.json()


def _seed_steps_cursor(tool: GarminCollectionTool, day: str = "2026-04-14") -> int:
    """Create the historical cursor position from which a repair resumes."""
    result = tool.execute(SyncRequest(
        "repair", health_from_local_date=day, through_local_date=day,
        resource_kinds=("steps",), repair_strategy="refetch",
        invocation_id=f"seed-cursor-{day}",
    ))
    assert result.status == "succeeded", result.json()
    conn = tool.repo.connect()
    try:
        subject = tool.repo.subject(conn)
        return subject
    finally:
        conn.close()


def _steps_cursor(config: GarminConfig) -> str | None:
    with sqlite3.connect(config.database_path) as conn:
        row = conn.execute(
            "SELECT complete_through_local_date FROM garmin_sync_cursors "
            "WHERE resource_kind='steps'"
        ).fetchone()
    return row[0] if row else None


def test_repair_resolved_historical_health_gap_advances_cursor(tmp_path: Path) -> None:
    config, tool, _transport = _setup(tmp_path)
    subject = _seed_steps_cursor(tool)
    conn = tool.repo.connect()
    try:
        tool.repo.gap(
            conn, subject, "steps", "garmin:health:steps:2026-04-15",
            "2026-04-15", "project", "parse_or_project_failed",
        )
    finally:
        conn.close()

    _refetch_steps(tool, "cursor-repair-resolve")

    assert _steps_cursor(config) == "2026-04-15"


def test_repair_cursor_stops_at_unresolved_middle_health_gap(tmp_path: Path) -> None:
    config, tool, _transport = _setup(tmp_path)
    subject = _seed_steps_cursor(tool)
    conn = tool.repo.connect()
    try:
        # The normal observation for this day succeeds, but this independent
        # deferred observation remains unresolved and must block continuity.
        tool.repo.gap(
            conn, subject, "steps", "garmin:health:steps:2026-04-16:sibling",
            "2026-04-16", "project", "parse_or_project_failed",
        )
    finally:
        conn.close()

    result = tool.execute(SyncRequest(
        "repair", health_from_local_date="2026-04-15",
        through_local_date="2026-04-17", resource_kinds=("steps",),
        repair_strategy="refetch", invocation_id="cursor-repair-middle-gap",
    ))

    assert result.status == "succeeded", result.json()
    assert _steps_cursor(config) == "2026-04-15"


def test_repair_activity_fit_gap_does_not_block_health_cursor(tmp_path: Path) -> None:
    config, tool, _transport = _setup(tmp_path)
    subject = _seed_steps_cursor(tool)
    conn = tool.repo.connect()
    try:
        tool.repo.gap(
            conn, subject, "steps", "garmin:health:steps:2026-04-15",
            "2026-04-15", "project", "parse_or_project_failed",
        )
        tool.repo.gap(
            conn, subject, "activity_fit", "garmin:activity:fixture:fit",
            "2026-04-15", "extract", "fit_missing",
        )
    finally:
        conn.close()

    _refetch_steps(tool, "cursor-repair-unrelated-fit-gap")

    assert _steps_cursor(config) == "2026-04-15"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM garmin_sync_cursors WHERE resource_kind='activity_fit'"
        ).fetchone()[0] == 0


def test_unchanged_daily_success_resolves_only_its_exact_gap_key(tmp_path: Path) -> None:
    config, tool, _transport = _setup(tmp_path)
    _refetch_steps(tool, "unchanged-daily-baseline")
    day = "2026-04-15"
    key = f"garmin:health:steps:{day}"
    sibling = f"{key}:other-observation"
    conn = tool.repo.connect()
    try:
        subject = tool.repo.subject(conn)
        tool.repo.gap(conn, subject, "steps", key, day, "project", "parse_or_project_failed")
        tool.repo.gap(conn, subject, "steps", sibling, day, "project", "parse_or_project_failed")
    finally:
        conn.close()
    _refetch_steps(tool, "unchanged-daily-resolve")
    with sqlite3.connect(config.database_path) as conn:
        states = dict(conn.execute(
            "SELECT logical_object_key,status FROM garmin_sync_gaps WHERE resource_kind='steps'"
        ))
    assert states[key] == "resolved"
    assert states[sibling] == "open"


def test_unchanged_daily_success_promotes_latest_snapshot_partial_in_place(
    tmp_path: Path,
) -> None:
    config, tool, _transport = _setup(tmp_path)
    _refetch_steps(tool, "partial-daily-baseline")
    with sqlite3.connect(config.database_path) as conn:
        before = conn.execute(
            """SELECT id,record_count,source_revision_id FROM resource_coverage
               WHERE resource_kind='steps' ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        assert before is not None
        conn.execute(
            "UPDATE resource_coverage SET availability_state='partial' WHERE id=?",
            (before[0],),
        )
        conn.commit()

    _refetch_steps(tool, "partial-daily-promote")

    with sqlite3.connect(config.database_path) as conn:
        after = conn.execute(
            """SELECT id,availability_state,record_count,source_revision_id
               FROM resource_coverage WHERE resource_kind='steps'
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
    assert after == (before[0], "fetched", before[1], before[2])


def _archive_unparsed_range(
    tool: GarminCollectionTool, config: GarminConfig, resource: str,
    payload: object, start: str = "2026-04-15", end: str = "2026-04-15",
) -> tuple[str, int]:
    key = f"garmin:health:{resource}:{start}:{end}"
    conn = tool.repo.connect()
    try:
        subject = tool.repo.subject(conn)
        with pytest.raises(ValueError, match="controlled_range_failure"):
            tool.repo.archive(
                conn, resource, key, stable_json(payload), "json", "application/json",
                lambda _revision: (_ for _ in ()).throw(ValueError("controlled_range_failure")),
            )
        revision = conn.execute(
            "SELECT id FROM source_revisions WHERE resource_kind=? AND provider_object_id=? "
            "AND parsed_at_utc IS NULL ORDER BY id DESC LIMIT 1",
            (resource, key),
        ).fetchone()[0]
        tool.repo.gap(
            conn, subject, resource, key, start, "project", "parse_or_project_failed",
            end_day=end, revision=revision,
        )
        return key, revision
    finally:
        conn.close()


def _archive_unparsed_daily(
    tool: GarminCollectionTool, resource: str, key: str, payload: object,
) -> int:
    conn = tool.repo.connect()
    try:
        with pytest.raises(ValueError, match="controlled_daily_failure"):
            tool.repo.archive(
                conn, resource, key, stable_json(payload), "json", "application/json",
                lambda _revision: (_ for _ in ()).throw(ValueError("controlled_daily_failure")),
            )
        return conn.execute(
            "SELECT id FROM source_revisions WHERE resource_kind=? AND provider_object_id=? "
            "AND parsed_at_utc IS NULL ORDER BY id DESC LIMIT 1",
            (resource, key),
        ).fetchone()[0]
    finally:
        conn.close()


def _archive_activity_extra_revision(
    tool: GarminCollectionTool, provider_object_id: str,
) -> int:
    conn = tool.repo.connect()
    try:
        with pytest.raises(ValueError, match="controlled_activity_failure"):
            tool.repo.archive(
                conn, "activity_extra", provider_object_id,
                stable_json({"role": "fixture"}), "json", "application/json",
                lambda _revision: (_ for _ in ()).throw(ValueError("controlled_activity_failure")),
            )
        return conn.execute(
            "SELECT id FROM source_revisions WHERE resource_kind='activity_extra' "
            "AND provider_object_id=? AND parsed_at_utc IS NULL",
            (provider_object_id,),
        ).fetchone()[0]
    finally:
        conn.close()


def test_auto_routes_parse_gap_to_offline_reparse_without_login(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    _refetch_steps(tool, "seed")
    with sqlite3.connect(config.database_path) as conn:
        subject = conn.execute("SELECT id FROM data_subjects WHERE subject_key='default'").fetchone()[0]
        revision = conn.execute("SELECT id FROM source_revisions WHERE resource_kind='steps'").fetchone()[0]
        conn.execute(
            """INSERT INTO garmin_sync_gaps(subject_id,resource_kind,logical_object_key,
                       window_start_local_date,window_end_local_date,stage,reason_code,status,
                       first_seen_at_utc,source_revision_id)
                   VALUES(?,?,?,?,?,?,?,'open',?,?)""",
            (subject, "steps", "garmin:health:steps:2026-04-15", "2026-04-15",
             "2026-04-15", "project", "parse_or_project_failed",
             "2026-04-17T00:00:00Z", revision),
        )
    before_login, before_fetch = transport.login_calls, transport.health_calls
    result = tool.execute(SyncRequest(
        "repair", health_from_local_date="2026-04-15", through_local_date="2026-04-15",
        resource_kinds=("steps",), repair_strategy="auto", invocation_id="auto-reparse",
    ))
    assert result.status == "succeeded", result.json()
    assert transport.login_calls == before_login and transport.health_calls == before_fetch
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT status FROM garmin_sync_gaps WHERE reason_code='parse_or_project_failed'"
        ).fetchone()[0] == "resolved"


@pytest.mark.parametrize(
    "reason_code",
    (
        "fit_identity_mismatch", "fit_crc_invalid", "fit_no_session",
        "fit_ambiguous_session", "fit_missing", "fit_ambiguous",
        "fit_zip_invalid", "fit_zip_limits_exceeded", "fit_zip_unsafe_member",
    ),
)
def test_auto_routes_activity_fit_extraction_failures_to_refetch(
    tmp_path: Path, reason_code: str,
) -> None:
    config, tool, _transport = _setup(tmp_path)
    with sqlite3.connect(config.database_path) as conn:
        conn.row_factory = sqlite3.Row
        subject = conn.execute(
            "SELECT id FROM data_subjects WHERE subject_key='default'"
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO garmin_sync_gaps(
                   subject_id,resource_kind,logical_object_key,
                   window_start_local_date,window_end_local_date,stage,
                   reason_code,status,first_seen_at_utc
               ) VALUES(?,?,?,?,?,?,?,'open',?)""",
            (
                subject, "activity_fit", "garmin:activity:1", "2026-04-15",
                "2026-04-15", "extract", reason_code, "2026-04-17T00:00:00Z",
            ),
        )
        strategy = tool._repair_strategy(
            conn, subject,
            SyncRequest(
                "repair", health_from_local_date="2026-04-15",
                through_local_date="2026-04-15", resource_kinds=("activity_fit",),
                repair_strategy="auto",
            ),
            SyncReceipt(),
        )
    assert strategy == "refetch"


def test_reparse_recovers_health_date_from_raw_key_without_explicit_dates(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    _refetch_steps(tool, "seed")
    with sqlite3.connect(config.database_path) as conn:
        subject = conn.execute(
            "SELECT id FROM data_subjects WHERE subject_key='default'"
        ).fetchone()[0]
        revision = conn.execute(
            "SELECT id FROM source_revisions WHERE resource_kind='steps' AND is_current=1"
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO garmin_sync_gaps(
                   subject_id,resource_kind,logical_object_key,
                   window_start_local_date,window_end_local_date,stage,
                   reason_code,status,first_seen_at_utc,source_revision_id
               ) VALUES(?,?,?,?,?,?,?,'open',?,?)""",
            (
                subject, "steps", "garmin:health:steps:2026-04-15",
                "2026-04-15", "2026-04-15", "project",
                "parse_or_project_failed", "2026-04-17T00:00:00Z", revision,
            ),
        )
    before = (transport.login_calls, transport.health_calls)
    result = tool.execute(SyncRequest(
        "repair", resource_kinds=("steps",), repair_strategy="reparse",
        invocation_id="reparse-key-date",
    ))
    assert result.status == "succeeded", result.json()
    assert (transport.login_calls, transport.health_calls) == before


def test_reparse_selects_only_distinct_revision_linked_gaps(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    _refetch_steps(tool, "gap-selection-current")
    key = "garmin:health:steps:2026-04-15"
    gap_revision = _archive_unparsed_daily(
        tool, "steps", key,
        {"calendarDate": "2026-04-15", "totalSteps": 2345},
    )
    with sqlite3.connect(config.database_path) as conn:
        subject = conn.execute(
            "SELECT id FROM data_subjects WHERE subject_key='default'"
        ).fetchone()[0]
        current_before = conn.execute(
            "SELECT id FROM source_revisions WHERE resource_kind='steps' AND is_current=1"
        ).fetchone()[0]
        conn.executemany(
            """INSERT INTO garmin_sync_gaps(subject_id,resource_kind,logical_object_key,
                       window_start_local_date,window_end_local_date,stage,reason_code,status,
                       first_seen_at_utc,source_revision_id)
                   VALUES(?,?,?,?,?,?,?,'open',?,?)""",
            [
                (subject, "steps", key, "2026-04-15", "2026-04-15", stage,
                 "parse_or_project_failed", "2026-04-17T00:00:00Z", gap_revision)
                for stage in ("project", "validate")
            ],
        )
        raw_before = list(conn.execute("SELECT sha256 FROM raw_objects ORDER BY sha256"))
    before_calls = (transport.login_calls, transport.health_calls)
    receipt = tool.execute(SyncRequest(
        "repair", health_from_local_date="2026-04-15", through_local_date="2026-04-15",
        resource_kinds=("steps",), repair_strategy="reparse", invocation_id="gap-selection",
    ))
    assert receipt.status == "succeeded" and receipt.counts["revised"] == 1
    assert (transport.login_calls, transport.health_calls) == before_calls
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT id FROM source_revisions WHERE resource_kind='steps' AND is_current=1"
        ).fetchone()[0] == gap_revision != current_before
        assert conn.execute(
            "SELECT count(*) FROM garmin_sync_gaps WHERE source_revision_id=? AND status='resolved'",
            (gap_revision,),
        ).fetchone()[0] == 2
        assert list(conn.execute("SELECT sha256 FROM raw_objects ORDER BY sha256")) == raw_before


def test_explicit_reparse_without_revision_gap_rebuilds_current(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    _refetch_steps(tool, "explicit-current")
    with sqlite3.connect(config.database_path) as conn:
        current = conn.execute(
            "SELECT id FROM source_revisions WHERE resource_kind='steps' AND is_current=1"
        ).fetchone()[0]
        raw_before = list(conn.execute("SELECT sha256 FROM raw_objects ORDER BY sha256"))
    before_calls = (transport.login_calls, transport.health_calls)
    receipt = tool.execute(SyncRequest(
        "repair", health_from_local_date="2026-04-15", through_local_date="2026-04-15",
        resource_kinds=("steps",), repair_strategy="reparse", invocation_id="explicit-current-reparse",
    ))
    assert receipt.status == "succeeded" and receipt.counts["revised"] == 1
    assert (transport.login_calls, transport.health_calls) == before_calls
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT id FROM source_revisions WHERE resource_kind='steps' AND is_current=1"
        ).fetchone()[0] == current
        assert list(conn.execute("SELECT sha256 FROM raw_objects ORDER BY sha256")) == raw_before


@pytest.mark.parametrize("with_linked_gap", (True, False))
def test_activity_id_scope_does_not_match_prefix_ids_in_gap_or_fallback_paths(
    tmp_path: Path, with_linked_gap: bool,
) -> None:
    config, tool, _transport = _setup(tmp_path)
    revisions = {
        activity_id: _archive_activity_extra_revision(
            tool, f"garmin:activity:{activity_id}:extra",
        )
        for activity_id in ("1", "10", "100")
    }
    if with_linked_gap:
        conn = tool.repo.connect()
        try:
            subject = tool.repo.subject(conn)
            tool.repo.gap(
                conn, subject, "activity_extra", "garmin:activity:1:extra",
                "2026-04-15", "project", "parse_or_project_failed",
                revision=revisions["1"],
            )
        finally:
            conn.close()
    receipt = SyncReceipt()
    request = SyncRequest(
        "repair", health_from_local_date="2026-04-15", through_local_date="2026-04-15",
        resource_kinds=("activity_extra",), activity_ids=("1",),
        repair_strategy="reparse", invocation_id=f"activity-id-scope-{with_linked_gap}",
    )
    conn = tool.repo.connect()
    try:
        tool._offline_repair(conn, 0, tool.repo.subject(conn), request, receipt)
    finally:
        conn.close()
    assert receipt.counts["revised"] == 1
    with sqlite3.connect(config.database_path) as conn:
        parsed = dict(conn.execute(
            "SELECT provider_object_id,parsed_at_utc FROM source_revisions "
            "WHERE resource_kind='activity_extra' ORDER BY provider_object_id"
        ))
        assert parsed["garmin:activity:1:extra"] is not None
        assert parsed["garmin:activity:10:extra"] is None
        assert parsed["garmin:activity:100:extra"] is None


def test_reparse_range_revisions_offline_by_day_without_duplicate_canonical(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    payloads = {
        "weigh_ins": {
            "dailyWeightSummaries": [{
                "summaryDate": "2026-04-15",
                "latestWeight": {"calendarDate": "2026-04-15", "weight": 70.1},
                "allWeightMetrics": [{"calendarDate": "2026-04-15", "weight": 70.2}],
            }],
        },
        "lactate_threshold": {
            "heart_rate": [{"updatedDate": "2026-04-15", "value": 165}],
            "power": [{"updatedDate": "2026-04-15", "value": 240}],
            "speed": [{"updatedDate": "2026-04-15", "value": 3.8}],
        },
        "hill_score": {
            "hillScoreDTOList": [], "maxScore": None,
            "periodAvgScore": {"2026-04-15": None},
            "startDate": "2026-04-15", "endDate": "2026-04-15",
        },
    }
    for resource, payload in payloads.items():
        _archive_unparsed_range(tool, config, resource, payload)
    with sqlite3.connect(config.database_path) as conn:
        raw_before = list(conn.execute("SELECT sha256 FROM raw_objects ORDER BY sha256"))
    before_calls = (transport.login_calls, transport.health_calls)
    request = SyncRequest(
        "repair", health_from_local_date="2026-04-15", through_local_date="2026-04-15",
        resource_kinds=tuple(payloads), repair_strategy="reparse", invocation_id="range-reparse",
    )
    assert tool.execute(request).status == "succeeded"
    assert (transport.login_calls, transport.health_calls) == before_calls
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM body_measurements").fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM physiology_metrics WHERE metric_key LIKE 'garmin.lactate_threshold.%'"
        ).fetchone()[0] == 3
        assert conn.execute(
            "SELECT availability_state,record_count FROM resource_coverage "
            "WHERE resource_kind='hill_score'"
        ).fetchone() == ("empty", 0)
        assert conn.execute(
            "SELECT count(*) FROM garmin_sync_gaps WHERE resource_kind IN "
            "('weigh_ins','lactate_threshold','hill_score') AND status='open'"
        ).fetchone()[0] == 0
        assert list(conn.execute("SELECT sha256 FROM raw_objects ORDER BY sha256")) == raw_before
    assert tool.execute(replace(request, invocation_id="range-reparse-repeat")).status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM body_measurements").fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM physiology_metrics WHERE metric_key LIKE 'garmin.lactate_threshold.%'"
        ).fetchone()[0] == 3


def test_reparse_range_key_must_be_fully_within_requested_window(tmp_path: Path) -> None:
    _config, tool, _transport = _setup(tmp_path)
    request = SyncRequest(
        "repair", health_from_local_date="2026-04-15", through_local_date="2026-04-16",
        resource_kinds=("weigh_ins",), repair_strategy="reparse",
    )
    assert tuple(
        value.isoformat()
        for value in tool._repair_range_dates(
            "weigh_ins", "garmin:health:weigh_ins:2026-04-15:2026-04-16", request,
        )
    ) == ("2026-04-15", "2026-04-16")
    with pytest.raises(ValueError, match="repair_range_before_request"):
        tool._repair_range_dates(
            "weigh_ins", "garmin:health:weigh_ins:2026-04-14:2026-04-16", request,
        )
    with pytest.raises(ValueError, match="repair_range_after_request"):
        tool._repair_range_dates(
            "weigh_ins", "garmin:health:weigh_ins:2026-04-15:2026-04-17", request,
        )


def test_reparse_malformed_range_rolls_back_existing_current_projection(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    good = {"dailyWeightSummaries": [{"allWeightMetrics": [{"calendarDate": "2026-04-15", "weight": 70.2}]}]}
    transport.fetch_range = lambda resource, _start, _end: good if resource == "weigh_ins" else []  # type: ignore[method-assign]
    assert tool.execute(SyncRequest(
        "repair", health_from_local_date="2026-04-15", through_local_date="2026-04-15",
        resource_kinds=("weigh_ins",), repair_strategy="refetch", invocation_id="range-good-current",
    )).status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        before_current = conn.execute(
            "SELECT id FROM source_revisions WHERE resource_kind='weigh_ins' AND is_current=1"
        ).fetchone()[0]
        before_measurement = conn.execute(
            "SELECT values_json,source_revision_id FROM body_measurements"
        ).fetchone()
    key, revision = _archive_unparsed_range(
        tool, config, "weigh_ins",
        {"dailyWeightSummaries": [{"allWeightMetrics": [{"weight": 70.4}]}]},
    )
    with sqlite3.connect(config.database_path) as conn:
        raw_before = list(conn.execute(
            "SELECT sha256,relative_path FROM raw_objects ORDER BY sha256"
        ))
        raw_bytes_before = [
            (config.raw_root.parent / row[1]).read_bytes()
            for row in raw_before
        ]
    result = tool.execute(SyncRequest(
        "repair", health_from_local_date="2026-04-15", through_local_date="2026-04-15",
        resource_kinds=("weigh_ins",), repair_strategy="reparse", invocation_id="range-malformed",
    ))
    assert result.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT id FROM source_revisions WHERE resource_kind='weigh_ins' AND is_current=1"
        ).fetchone()[0] == before_current
        assert conn.execute(
            "SELECT values_json,source_revision_id FROM body_measurements"
        ).fetchone() == before_measurement
        assert conn.execute(
            "SELECT parsed_at_utc FROM source_revisions WHERE id=?", (revision,)
        ).fetchone()[0] is None
        raw_after = list(conn.execute(
            "SELECT sha256,relative_path FROM raw_objects ORDER BY sha256"
        ))
        assert raw_after == raw_before
        assert [
            (config.raw_root.parent / row[1]).read_bytes()
            for row in raw_after
        ] == raw_bytes_before


def test_reparse_failure_rolls_back_and_preserves_current_projection(
    tmp_path: Path, monkeypatch,
) -> None:
    config, tool, _transport = _setup(tmp_path)
    _refetch_steps(tool, "seed")
    with sqlite3.connect(config.database_path) as conn:
        before_revision = conn.execute(
            "SELECT id,parsed_at_utc FROM source_revisions WHERE resource_kind='steps' AND is_current=1"
        ).fetchone()
        before_health = conn.execute(
            "SELECT values_json,source_revision_id FROM daily_health WHERE local_date='2026-04-15' AND is_current=1"
        ).fetchone()

    monkeypatch.setattr(
        tool, "_project_health",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("synthetic parser failure")),
    )
    result = tool.execute(SyncRequest(
        "repair", resource_kinds=("steps",), repair_strategy="reparse",
        invocation_id="reparse-rollback",
    ))
    assert result.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT id,parsed_at_utc FROM source_revisions WHERE resource_kind='steps' AND is_current=1"
        ).fetchone() == before_revision
        assert conn.execute(
            "SELECT values_json,source_revision_id FROM daily_health WHERE local_date='2026-04-15' AND is_current=1"
        ).fetchone() == before_health


def test_refetch_is_noop_for_same_payload_and_revises_changed_payload(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    _refetch_steps(tool, "seed")
    _refetch_steps(tool, "same")
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM source_revisions WHERE resource_kind='steps'"
        ).fetchone()[0] == 1
    transport.steps = 2345
    _refetch_steps(tool, "changed")
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM source_revisions WHERE resource_kind='steps'"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT count(*) FROM source_revisions WHERE resource_kind='steps' AND is_current=1"
        ).fetchone()[0] == 1


def test_reconcile_is_offline_and_audit_records_raw_integrity_gap(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    _refetch_steps(tool, "seed")
    before_login = transport.login_calls
    reconciled = tool.execute(SyncRequest(
        "repair", health_from_local_date="2026-04-15", through_local_date="2026-04-15",
        resource_kinds=("steps",), repair_strategy="reconcile", invocation_id="reconcile",
    ))
    assert reconciled.status == "succeeded"
    assert transport.login_calls == before_login
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM reconciliation_results").fetchone()[0] >= 1
        original_path = conn.execute(
            "SELECT relative_path FROM raw_objects WHERE resource_kind='steps'"
        ).fetchone()[0]
        conn.execute("UPDATE raw_objects SET relative_path='outside/raw.json' WHERE resource_kind='steps'")
    audited = tool.execute(SyncRequest(
        "audit", health_from_local_date="2026-04-15", through_local_date="2026-04-15",
        invocation_id="audit-raw",
    ))
    assert audited.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM garmin_sync_gaps WHERE reason_code='raw_integrity' AND status='open'"
        ).fetchone()[0] == 1
        conn.execute(
            "UPDATE raw_objects SET relative_path=? WHERE resource_kind='steps'",
            (original_path,),
        )
    clean = tool.execute(SyncRequest(
        "audit", health_from_local_date="2026-04-15",
        through_local_date="2026-04-15", invocation_id="audit-raw-clean",
    ))
    assert clean.status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM garmin_sync_gaps WHERE reason_code='raw_integrity' AND status='resolved'"
        ).fetchone()[0] == 1


def test_audit_does_not_create_coverage_gap_outside_requested_window(tmp_path: Path) -> None:
    config, tool, _transport = _setup(tmp_path)
    with sqlite3.connect(config.database_path) as conn:
        subject = conn.execute(
            "SELECT id FROM data_subjects WHERE subject_key='default'"
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO resource_coverage(
                   subject_id,provider,resource_kind,local_date,
                   availability_state,record_count,observed_at_utc
               ) VALUES(?,'garmin','steps','2026-04-01','error',0,'2026-04-02T00:00:00Z')""",
            (subject,),
        )
    result = tool.execute(SyncRequest(
        "audit", health_from_local_date="2026-04-15",
        through_local_date="2026-04-15", invocation_id="audit-bounded",
    ))
    assert result.status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM garmin_sync_gaps WHERE reason_code='coverage_error'"
        ).fetchone()[0] == 0


def test_status_is_local_read_only_and_never_logs_in(tmp_path: Path) -> None:
    _config, tool, transport = _setup(tmp_path)
    before = transport.login_calls
    result = tool.execute(SyncRequest("status"))
    assert result.status == "succeeded"
    assert transport.login_calls == before
