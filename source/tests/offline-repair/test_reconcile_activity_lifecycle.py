import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

from tools.reconcile_activity_lifecycle import audit


def test_audit_and_candidate_repair_only_reactivate_seen_activity(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    raw = state / "raw" / "garmin"
    raw.mkdir(parents=True)
    payload = json.dumps(
        [{"activityId": 42, "startTimeGMT": "2026-08-08T00:00:00Z"}],
        separators=(",", ":"),
    ).encode()
    raw_file = raw / "inventory.json"
    raw_file.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    database = state / "data.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE raw_objects(
          id INTEGER PRIMARY KEY, sha256 TEXT, relative_path TEXT,
          resource_kind TEXT, provider TEXT, fetched_at_utc TEXT
        );
        CREATE TABLE source_revisions(
          id INTEGER PRIMARY KEY, provider TEXT, resource_kind TEXT,
          provider_object_id TEXT, raw_object_id INTEGER, payload_hash TEXT,
          parsed_at_utc TEXT
        );
        CREATE TABLE activities(
          id INTEGER PRIMARY KEY, provider TEXT, provider_activity_id TEXT,
          local_date TEXT, provider_state TEXT, first_missing_at_utc TEXT,
          last_missing_at_utc TEXT, provider_deleted_at_utc TEXT
        );
        """
    )
    connection.execute(
        "INSERT INTO raw_objects VALUES(1,?,?,?,?,?)",
        (
            digest,
            "raw/garmin/inventory.json",
            "activity_inventory",
            "garmin",
            "2026-08-11T00:00:00Z",
        ),
    )
    connection.execute(
        "INSERT INTO source_revisions VALUES(1,?,?,?,?,?,?)",
        (
            "garmin",
            "activity_inventory",
            "garmin:inventory:activities:repair:2026-08-08:2026-08-08:page:000000",
            1,
            digest,
            "2026-08-11T00:00:01Z",
        ),
    )
    connection.executemany(
        "INSERT INTO activities VALUES(?,?,?,?,?,?,?,?)",
        [
            (1, "garmin", "42", "2026-08-08", "suspected_missing", "x", "x", None),
            (2, "garmin", "99", "2026-08-08", "suspected_missing", "x", "x", None),
        ],
    )
    connection.commit()
    connection.close()

    report = audit(database, state, date(2026, 8, 8), date(2026, 8, 8), apply=True)
    assert report["status"] == "applied"
    assert report["reactivated_count"] == 1
    assert report["observations"] == [
        {
            "revision_id": 1,
            "observation_id": "garmin:inventory:activities:repair:2026-08-08:2026-08-08:page:000000",
            "mode": "repair",
            "start_local_date": "2026-08-08",
            "through_local_date": "2026-08-08",
            "observed_at_utc": "2026-08-11T00:00:00Z",
            "entry_count": 1,
            "seen_activity_count": 1,
            "absence_proven": False,
            "reason_codes": ["absence_proof_unavailable", "offline_inventory_only"],
            "payload_sha256": digest,
        }
    ]
    with sqlite3.connect(database) as check:
        assert (
            check.execute(
                "SELECT provider_state FROM activities WHERE id=1"
            ).fetchone()[0]
            == "active"
        )
        assert (
            check.execute(
                "SELECT provider_state FROM activities WHERE id=2"
            ).fetchone()[0]
            == "suspected_missing"
        )
