"""Offline L2-09B1 acceptance: reviewed account/device endpoints only."""
from __future__ import annotations

import copy
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.garmin import GarminCollectionTool, GarminConfig, GarminError, SyncReceipt, SyncRequest


class B1Transport:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.account_errors: dict[tuple[str, str | None], GarminError] = {}
        self.health_errors: dict[str, GarminError] = {}
        self.devices = [
            {"deviceId": "PRIVATE-DEVICE-A", "serialNumber": "PRIVATE-SERIAL-A", "manufacturer": "Garmin", "product": "Watch", "hardwareVersion": "hw-a"},
            {"deviceId": "PRIVATE-DEVICE-B", "serialNumber": "PRIVATE-SERIAL-B", "manufacturer": "Garmin", "product": "Bike", "hardwareVersion": "hw-b"},
        ]
        self.basic_payloads = {
            "user_profile": {"measurementSystem": "metric"},
            "user_profile_settings": {"timeFormat": "24h"},
        }
        self.account_payloads: dict[tuple[str, str | None], object] = {
            ("primary_device", None): {"deviceId": "PRIVATE-DEVICE-A"},
            ("device_last_used", None): {"deviceId": "PRIVATE-DEVICE-B"},
            ("device_settings", "PRIVATE-DEVICE-A"): {"softwareVersion": "software-a", "firmwareVersion": "firmware-a"},
            ("device_settings", "PRIVATE-DEVICE-B"): {"softwareVersion": "software-b", "batterySaveMode": True},
            ("personal_records", None): {"vo2Max": 42.0, "maxHeartRate": 181},
            ("cycling_ftp", None): {"ftp": 221, "ftpWatts": 221},
            ("pregnancy", None): {"pregnancyWeek": 18, "partnerName": "PRIVATE-PERSON"},
        }

    def login(self) -> None: self.calls.append("login")
    def identity(self) -> str: self.calls.append("identity"); return "b1-fixture-account"
    def fetch_health(self, resource: str, _day: str):
        self.calls.append(f"health:{resource}")
        if resource in self.health_errors: raise self.health_errors[resource]
        if resource == "devices": return copy.deepcopy(self.devices)
        return copy.deepcopy(self.basic_payloads.get(resource, []))
    def fetch_account(self, resource: str, provider_device_id: str | None = None):
        self.calls.append(f"account:{resource}:{provider_device_id or '-'}")
        error = self.account_errors.get((resource, provider_device_id))
        if error: raise error
        return copy.deepcopy(self.account_payloads.get((resource, provider_device_id), {}))
    def list_activities(self, *_args): raise AssertionError("account-only scope must not enumerate activities")
    def activity_summary(self, _id): raise AssertionError("no activities")
    def activity_original(self, _id): raise AssertionError("no activities")
    def activity_extra(self, _id, _role): raise AssertionError("no activities")


def _setup(tmp_path: Path):
    root = tmp_path / "data"
    foundation = FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state/ready.json", root / "state/locks/foundation.lock")
    assert FoundationTool(foundation).execute(FoundationRequest("init", "l2-09b1", "2026-01-01T00:00:00Z")).status == "initialized"
    config = GarminConfig(foundation.database_path, foundation.raw_root, foundation.state_root, "2026-04-15", request_min_interval_ms=0)
    transport = B1Transport()
    tool = GarminCollectionTool(config, transport, sleep=lambda _delay: None, clock=lambda: datetime(2026, 4, 17), monotonic=lambda: 1000.0)
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    return config, tool, transport


def _repair(tool: GarminCollectionTool, invocation: str, *resources: str):
    return tool.execute(SyncRequest("repair", through_local_date="2026-04-15", resource_kinds=resources, repair_strategy="refetch", invocation_id=invocation))


def test_device_settings_uses_only_this_run_devices_and_account_scope_is_closed(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.calls.clear()
    receipt = _repair(tool, "b1-settings", "device_settings")
    assert receipt.status == "succeeded"
    assert transport.calls == ["login", "identity", "health:devices", "account:device_settings:PRIVATE-DEVICE-A", "account:device_settings:PRIVATE-DEVICE-B"]
    with sqlite3.connect(config.database_path) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("SELECT count(*) FROM devices").fetchone()[0] == 2
        paths = dict(conn.execute("SELECT field_path,mapping_state FROM source_field_catalog WHERE resource_kind='device_settings'"))
        assert paths["/softwareVersion"] == "known_passthrough"
        assert paths["/firmwareVersion"] == "known_passthrough"
        payload = b"".join((config.raw_root.parent / row[0]).read_bytes() for row in conn.execute("SELECT relative_path FROM raw_objects"))
        assert b"PRIVATE-DEVICE" in payload and b"PRIVATE-SERIAL" in payload
        assert conn.execute("SELECT count(*) FROM physiology_records WHERE record_type='device_settings'").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM physiology_metrics WHERE metric_key='garmin.device.settings.softwareVersion'").fetchone()[0] == 2


def test_basic_fetch_stages_are_terminal_for_success_failure_noop_and_recovery(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    first = _repair(tool, "b1-basic", "user_profile", "user_profile_settings", "devices")
    assert first.status == "succeeded"
    repeat = _repair(tool, "b1-basic-repeat", "user_profile", "user_profile_settings", "devices")
    assert repeat.counts["unchanged"] == 3
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM garmin_sync_items WHERE status='running'").fetchone()[0] == 0

    # Invalid devices fail projection only after the successful fetch terminal
    # is durable; a later started-run recovery leaves no running item behind.
    transport.devices = [{}]
    failed = _repair(tool, "b1-basic-project-fails", "devices")
    assert failed.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("SELECT status FROM garmin_sync_items WHERE resource_kind='devices' AND stage='fetch' ORDER BY id DESC LIMIT 1").fetchone()[0] == "fetched"
        assert conn.execute("SELECT status FROM garmin_sync_items WHERE resource_kind='devices' AND stage='project' ORDER BY id DESC LIMIT 1").fetchone()[0] == "failed"
        run = conn.execute("SELECT id FROM garmin_sync_runs WHERE run_id=?", (failed.run_id,)).fetchone()[0]
        conn.execute("UPDATE garmin_sync_runs SET status='started',completed_at_utc=NULL WHERE id=?", (run,))
        conn.execute("INSERT INTO garmin_sync_items(garmin_sync_run_id,resource_kind,logical_object_key,stage,status,attempt_count,started_at_utc) VALUES(?,?,?,?,?,?,?)", (run, "devices", "garmin:recover", "validate", "running", 1, "2026-04-16T00:00:00Z"))
        conn.commit()
        subject = conn.execute("SELECT id FROM data_subjects WHERE subject_key='default'").fetchone()[0]
        recovery = SyncReceipt(mode="repair")
        tool.repo.start_run(conn, SyncRequest("repair", through_local_date="2026-04-15", resource_kinds=("devices",), repair_strategy="refetch", invocation_id="b1-basic-project-fails"), subject, recovery)
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM garmin_sync_items WHERE status='running'").fetchone()[0] == 0


def test_primary_last_used_have_fresh_devices_dependency_and_canonical_roles(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.calls.clear()
    first = _repair(tool, "b1-primary", "primary_device", "device_last_used")
    assert first.status == "succeeded"
    assert transport.calls == ["login", "identity", "health:devices", "account:primary_device:-", "account:device_last_used:-"]
    with sqlite3.connect(config.database_path) as conn:
        assert set(row[0] for row in conn.execute("SELECT metric_key FROM physiology_metrics WHERE metric_key LIKE 'garmin.device.role.%'")) == {"garmin.device.role.primary", "garmin.device.role.last_used"}
        assert all(b"PRIVATE" not in row[0] for row in conn.execute("SELECT extras_json FROM physiology_records WHERE record_type IN ('primary_device','device_last_used')"))
    # A later dependency failure must not re-use the first run's provider IDs.
    transport.calls.clear()
    transport.health_errors["devices"] = GarminError("not-here", http_status=404)
    second = _repair(tool, "b1-primary-no-devices", "primary_device")
    assert second.status == "partial" and second.counts["not_available"] == 2
    assert transport.calls == ["login", "identity", "health:devices"]
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM garmin_sync_gaps WHERE resource_kind='primary_device'").fetchone()[0] >= 1
    # Both reviewed wrapper forms normalise to the same de-identified roles.
    transport.health_errors.clear()
    transport.account_payloads[("primary_device", None)] = {"primaryTrainingDevice": {"deviceId": "PRIVATE-DEVICE-B"}}
    transport.account_payloads[("device_last_used", None)] = [{"deviceId": "PRIVATE-DEVICE-A"}]
    wrapped = _repair(tool, "b1-primary-wrapped", "primary_device", "device_last_used")
    assert wrapped.status == "succeeded"


def test_last_used_volatile_metadata_does_not_change_device_reference_revision(
    tmp_path: Path,
) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.account_payloads[("device_last_used", None)] = {
        "deviceId": "PRIVATE-DEVICE-B",
        "lastSyncTimestamp": "2026-04-17T00:00:00Z",
    }
    first = _repair(tool, "last-used-semantic-first", "device_last_used")
    assert first.status == "succeeded" and first.counts["revised"] >= 1
    with sqlite3.connect(config.database_path) as conn:
        revisions_before = conn.execute(
            """SELECT count(*) FROM source_revisions
               WHERE resource_kind='device_last_used'"""
        ).fetchone()[0]
        raw_before = conn.execute(
            "SELECT count(*) FROM raw_objects WHERE resource_kind='device_last_used'"
        ).fetchone()[0]

    transport.account_payloads[("device_last_used", None)][
        "lastSyncTimestamp"
    ] = "2026-04-17T00:01:00Z"
    repeated = _repair(
        tool,
        "last-used-semantic-volatile",
        "device_last_used",
    )
    assert repeated.counts["revised"] == 0
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            """SELECT count(*) FROM source_revisions
               WHERE resource_kind='device_last_used'"""
        ).fetchone()[0] == revisions_before
        assert conn.execute(
            "SELECT count(*) FROM raw_objects WHERE resource_kind='device_last_used'"
        ).fetchone()[0] == raw_before + 1
        assert conn.execute(
            """SELECT profile_version FROM source_revisions
               WHERE resource_kind='device_last_used' AND is_current=1"""
        ).fetchone()[0] == "device-reference-v1"

    transport.account_payloads[("device_last_used", None)][
        "deviceId"
    ] = "PRIVATE-DEVICE-A"
    changed = _repair(tool, "last-used-semantic-real-change", "device_last_used")
    assert changed.counts["revised"] == 1
    audited = tool.execute(
        SyncRequest(
            "audit",
            health_from_local_date="2026-04-15",
            through_local_date="2026-04-15",
            invocation_id="last-used-semantic-audit",
        )
    )
    assert audited.status == "succeeded" and audited.counts["failed"] == 0


@pytest.mark.parametrize("resource", ("primary_device", "device_last_used"))
def test_unchanged_b1_success_resolves_only_its_account_key(
    tmp_path: Path, resource: str,
) -> None:
    config, tool, _transport = _setup(tmp_path)
    _repair(tool, f"b1-unchanged-baseline-{resource}", resource)
    day = "2026-04-15"
    key = f"garmin:account:{resource}:account"
    sibling = f"{key}:sibling"
    conn = tool.repo.connect()
    try:
        subject = tool.repo.subject(conn)
        tool.repo.gap(conn, subject, resource, key, day, "project", "account_project_failed")
        tool.repo.gap(conn, subject, resource, sibling, day, "project", "account_project_failed")
    finally:
        conn.close()
    repeated = _repair(tool, f"b1-unchanged-resolve-{resource}", resource)
    assert repeated.counts["unchanged"] >= 1
    with sqlite3.connect(config.database_path) as conn:
        states = dict(conn.execute(
            "SELECT logical_object_key,status FROM garmin_sync_gaps WHERE resource_kind=?",
            (resource,),
        ))
    assert states[key] == "resolved"
    assert states[sibling] == "open"


def test_b1_physiology_is_redacted_revisioned_and_noop(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    resources = ("personal_records", "cycling_ftp", "pregnancy")
    first = _repair(tool, "b1-physiology", *resources)
    assert first.status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        metrics = set(conn.execute("SELECT metric_key,canonical_unit FROM physiology_metrics"))
        assert ("garmin.personal_records.vo2Max", "ml/kg/min") in metrics
        assert ("garmin.cycling_ftp.ftp", "W") in metrics
        assert ("garmin.pregnancy.pregnancyWeek", "week") in metrics
        before = dict(conn.execute("SELECT resource_kind,count(*) FROM source_revisions WHERE resource_kind IN ('personal_records','cycling_ftp','pregnancy') GROUP BY resource_kind"))
        everything = b"".join((config.raw_root.parent / row[0]).read_bytes() for row in conn.execute("SELECT relative_path FROM raw_objects")) + "\n".join(conn.iterdump()).encode() + first.json().encode()
        for marker in (b"PRIVATE-TOKEN", b"private@example"):
            assert marker not in everything
    again = _repair(tool, "b1-physiology-repeat", *resources)
    assert again.status == "succeeded" and again.counts["unchanged"] == 3
    transport.account_payloads[("cycling_ftp", None)] = {"ftp": 235}
    changed = _repair(tool, "b1-ftp-revised", "cycling_ftp")
    assert changed.counts["revised"] == 1
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM source_revisions WHERE resource_kind='cycling_ftp' AND is_current=1").fetchone()[0] == 1
        assert dict(conn.execute("SELECT resource_kind,count(*) FROM source_revisions WHERE resource_kind IN ('personal_records','pregnancy') GROUP BY resource_kind")) == {key: before[key] for key in ('personal_records','pregnancy')}


def test_b1_capabilities_unknown_device_and_snapshot_are_isolated(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.account_errors[("pregnancy", None)] = GarminError("not-here", http_status=404)
    transport.account_errors[("personal_records", None)] = GarminError("forbidden", http_status=403)
    result = _repair(tool, "b1-capability", "pregnancy", "personal_records")
    assert result.status == "partial"
    transport.account_errors.clear()
    transport.account_payloads[("primary_device", None)] = {"deviceId": "UNKNOWN-DEVICE"}
    unknown = _repair(tool, "b1-unknown", "primary_device")
    assert unknown.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        states = dict(conn.execute("SELECT resource_kind,capability_state FROM garmin_resource_capabilities WHERE resource_kind IN ('pregnancy','personal_records')"))
        assert states == {"pregnancy": "not_available", "personal_records": "forbidden"}
        assert conn.execute("SELECT count(*) FROM garmin_sync_gaps WHERE resource_kind='primary_device' AND reason_code='unknown_device_reference'").fetchone()[0] == 1
        # Raw-first publication keeps an unparsed received revision available
        # for a later alias/wrapper repair, without accepting it as canonical.
        assert conn.execute(
            """SELECT count(*) FROM source_revisions
               WHERE resource_kind='primary_device' AND is_current=0
                 AND parsed_at_utc IS NULL"""
        ).fetchone()[0] == 1
    # A disabled conditional endpoint is an immutable sanitized tombstone, not
    # a zero-valued physiology record, and is eligible for seven-day reprobe.
    transport.account_payloads[("pregnancy", None)] = {"availability_state": "not_enabled", "PRIVATE-PERSON": "must-not-persist"}
    disabled = _repair(tool, "b1-disabled", "pregnancy")
    assert disabled.status == "succeeded" and disabled.counts["not_enabled"] == 1
    with sqlite3.connect(config.database_path) as conn:
        state, probe = conn.execute(
            "SELECT capability_state,next_probe_at_utc "
            "FROM garmin_resource_capabilities "
            "WHERE resource_kind='pregnancy' AND environment_key=?",
            (config.region,),
        ).fetchone()
        assert state == "not_enabled" and probe == "2026-04-23T16:00:00Z"
        revision = conn.execute("SELECT id FROM source_revisions WHERE resource_kind='pregnancy' AND is_current=1").fetchone()[0]
        assert conn.execute("SELECT source_revision_id FROM resource_coverage WHERE resource_kind='pregnancy' ORDER BY id DESC LIMIT 1").fetchone()[0] == revision
        assert conn.execute("SELECT count(*) FROM physiology_records WHERE record_type='pregnancy'").fetchone()[0] == 0
    transport.account_payloads[("pregnancy", None)] = {"pregnancyWeek": 18}
    # Public snapshot requests deliberately have no resource filter.  Keep
    # this B1 acceptance focused on account coverage rather than the later
    # health/activity units.
    tool._health = lambda *_args: None  # type: ignore[method-assign]
    tool._activities = lambda *_args: None  # type: ignore[method-assign]
    transport.account_payloads[("primary_device", None)] = {"deviceId": "PRIVATE-DEVICE-A"}
    snap = tool.execute(SyncRequest("snapshot", snapshot_local_date="2026-04-15", invocation_id="b1-snapshot"))
    assert snap.status == "succeeded" and snap.coverage_state == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT availability_state FROM resource_coverage WHERE resource_kind='cycling_ftp' ORDER BY id DESC LIMIT 1").fetchone()[0] == "partial"
        assert conn.execute("SELECT count(*) FROM garmin_sync_cursors").fetchone()[0] == 0


def test_one_device_failure_does_not_rollback_other_device(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    # Deliberately reverse inventory order: a first-device failure must not be
    # overwritten by the later success in the aggregate resource coverage.
    transport.devices.reverse()
    transport.account_errors[("device_settings", "PRIVATE-DEVICE-B")] = GarminError("forbidden", http_status=403)
    receipt = _repair(tool, "b1-one-device-fails", "device_settings")
    assert receipt.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM source_revisions WHERE resource_kind='device_settings' AND is_current=1").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM garmin_sync_items WHERE resource_kind='device_settings' AND status='forbidden'").fetchone()[0] == 1
        # Per-device work is durable in items, but the aggregate account
        # resource makes exactly one worst-state date coverage claim.
        assert conn.execute("SELECT count(*) FROM resource_coverage WHERE resource_kind='device_settings' AND local_date='2026-04-15'").fetchone()[0] == 1
        assert conn.execute("SELECT availability_state FROM resource_coverage WHERE resource_kind='device_settings'").fetchone()[0] == "forbidden"
        assert conn.execute("SELECT count(*) FROM garmin_sync_items WHERE resource_kind='device_settings' AND stage='fetch' AND status='running'").fetchone()[0] == 0
        assert receipt.counts["failed"] == 1


def test_receipt_v1_folds_not_supported_into_unavailable_and_replays(tmp_path: Path) -> None:
    config, tool, _transport = _setup(tmp_path)
    # The public v1 receipt has no separate not_supported field.  The stable
    # documented mapping is not_supported -> not_available, never fetched.
    tool.transport.fetch_account = None  # type: ignore[method-assign]
    request = SyncRequest("repair", through_local_date="2026-04-15", resource_kinds=("cycling_ftp",), repair_strategy="refetch", invocation_id="b1-not-supported")
    first = tool.execute(request)
    second = tool.execute(request)
    assert first.status == "succeeded" and first.counts["not_available"] == 1 and first.counts["fetched"] == 0
    assert second.counts == first.counts
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT status FROM garmin_sync_items WHERE resource_kind='cycling_ftp' AND stage='fetch'").fetchone()[0] == "not_supported"
        assert conn.execute("SELECT capability_state FROM garmin_resource_capabilities WHERE resource_kind='cycling_ftp'").fetchone()[0] == "not_supported"
        assert conn.execute("SELECT availability_state FROM resource_coverage WHERE resource_kind='cycling_ftp'").fetchone()[0] == "not_supported"


def test_device_reference_aliases_resolve_to_inventory_canonical_hash(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.devices[0]["unitId"] = "PRIVATE-UNIT-A"
    transport.account_payloads[("primary_device", None)] = {
        "PrimaryTrainingDevice": {"serialNumber": "PRIVATE-SERIAL-A"}
    }
    transport.account_payloads[("device_last_used", None)] = {
        "userDeviceId": "PRIVATE-UNIT-A"
    }
    receipt = _repair(
        tool,
        "b1-reference-aliases",
        "primary_device",
        "device_last_used",
    )
    assert receipt.status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM physiology_records "
            "WHERE record_type IN ('primary_device','device_last_used')"
        ).fetchone()[0] == 2
