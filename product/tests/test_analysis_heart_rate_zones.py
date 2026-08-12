from datetime import date, timedelta

from trainlab.analysis.heart_rate_zones import calculate_zone_candidates
from trainlab.analysis.heart_rate_zones_store import (
    append_confirmed_zone_revision,
    ensure_zone_candidate,
    latest_confirmed_zone_revision,
    latest_zone_candidate,
    zone_evidence_from_snapshot,
)
from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.analysis.stable_views import StableSnapshot, StableSubjectContext


def test_hrr_requires_two_sustained_runs_and_returns_three_comparable_methods():
    end = date(2026, 8, 3)
    rhr = [
        {"local_date": (end - timedelta(days=index)).isoformat(), "bpm": 50 + index % 2}
        for index in range(28)
    ]
    runs = [
        {
            "activity_id": "r1",
            "local_date": (end - timedelta(days=10)).isoformat(),
            "sport": "running",
            "heart_rate_bpm": [170] * 40,
            "duration_seconds": 600,
            "sample_interval_seconds": 1,
            "source_quality": "chest_strap",
        },
        {
            "activity_id": "r2",
            "local_date": (end - timedelta(days=3)).isoformat(),
            "sport": "running",
            "heart_rate_bpm": [172] * 40,
            "duration_seconds": 600,
            "sample_interval_seconds": 1,
            "source_quality": "chest_strap",
        },
    ]
    result = calculate_zone_candidates(rhr, runs, as_of=end, age_years=40)
    assert result["primary_method"] == "hrr"
    assert result["requires_user_confirmation"] is True
    assert result["accepted"] is False
    assert result["hrr"]["status"] == "available"
    assert result["hrr"]["max_heart_rate_bpm"] == 170
    assert len(result["hrr"]["zones"]) == 5
    assert result["tanaka_low_confidence"]["predicted_max_heart_rate_bpm"] == 180


def test_single_spike_does_not_unlock_hrr():
    result = calculate_zone_candidates(
        [{"local_date": "2026-08-03", "bpm": 50}] * 5,
        [{
            "activity_id": "spike",
            "local_date": "2026-08-03",
            "sport": "running",
            "heart_rate_bpm": [190, 100, 100, 100, 100],
            "duration_seconds": 600,
            "sample_interval_seconds": 1,
            "source_quality": "chest_strap",
        }],
        as_of="2026-08-03",
        age_years=40,
    )
    assert result["hrr"]["status"] == "unavailable"


def test_confirmed_revision_is_append_only_and_exposes_safety_evidence(tmp_path):
    root = tmp_path / "foundation"
    tool = FoundationTool(
        FoundationConfig(
            root,
            root / "data.db",
            root / "raw",
            root / "state",
            root / "state/foundation-ready.json",
            root / "state/locks/foundation.lock",
        )
    )
    assert tool.execute(FoundationRequest("init", "hrr-test", "2026-08-03T00:00:00Z")).status == "initialized"
    import sqlite3

    connection = sqlite3.connect(root / "data.db")
    connection.row_factory = sqlite3.Row
    candidate = calculate_zone_candidates(
        [{"local_date": (date(2026, 8, 3) - timedelta(days=index)).isoformat(), "bpm": 50} for index in range(28)],
        [
            {"activity_id": "r1", "local_date": "2026-07-20", "sport": "running", "heart_rate_bpm": [170] * 40, "duration_seconds": 600, "source_quality": "chest_strap"},
            {"activity_id": "r2", "local_date": "2026-07-30", "sport": "running", "heart_rate_bpm": [172] * 40, "duration_seconds": 600, "source_quality": "chest_strap"},
        ],
        as_of="2026-08-03",
        age_years=40,
    )
    candidate = {**candidate, "accepted": True}
    record_id = append_confirmed_zone_revision(
        connection, 1, candidate, effective_from_utc="2026-08-03T00:00:00Z", confirmation_event_id=9
    )
    connection.commit()
    stored = latest_confirmed_zone_revision(connection, 1)
    assert stored and stored["id"] == record_id and set(stored["methods"]) == {"hrr", "historical_threshold_proxy", "tanaka_low_confidence"}
    records = tuple(dict(row) for row in connection.execute("SELECT * FROM physiology_records WHERE id=?", (record_id,)))
    metrics = tuple(dict(row) for row in connection.execute("SELECT * FROM physiology_metrics WHERE physiology_record_id=?", (record_id,)))
    snapshot = StableSnapshot(
        views={
            "v_current_physiology_records": records,
            "v_current_physiology_metrics": metrics,
        },
        coverage=(), cursors=(), gaps=(), activity_stages=(), quality_issues=(), facts=(), capabilities=(), plan_reasons=(), audit=(),
        subject_context=StableSubjectContext(1, "Asia/Hong_Kong", "garmin", "account", True),
    )
    evidence = zone_evidence_from_snapshot(snapshot)
    assert len(evidence) == 1 and evidence[0]["source_kind"] == "user_zones"
    assert evidence[0]["measurement_method"] == "user_verified"
    assert len(evidence[0]["zones"]) == 5
    connection.close()


def test_candidate_bootstrap_is_idempotent_and_remains_unconfirmed(tmp_path):
    root = tmp_path / "foundation"
    tool = FoundationTool(FoundationConfig(
        root, root / "data.db", root / "raw", root / "state",
        root / "state/foundation-ready.json", root / "state/locks/foundation.lock",
    ))
    assert tool.execute(FoundationRequest("init", "hrr-candidate", "2026-08-03T00:00:00Z")).status == "initialized"
    import sqlite3
    connection = sqlite3.connect(root / "data.db")
    connection.row_factory = sqlite3.Row
    first = ensure_zone_candidate(
        connection, 1, as_of_local_date="2026-08-03",
        effective_at_utc="2026-08-04T01:00:00Z", weekly_refresh=False,
    )
    second = ensure_zone_candidate(
        connection, 1, as_of_local_date="2026-08-03",
        effective_at_utc="2026-08-04T01:00:01Z", weekly_refresh=False,
    )
    connection.commit()
    assert first["status"] == "created"
    assert second["status"] == "unchanged"
    assert latest_zone_candidate(connection, 1)["id"] == first["record_id"]
    assert latest_confirmed_zone_revision(connection, 1) is None
    connection.close()
