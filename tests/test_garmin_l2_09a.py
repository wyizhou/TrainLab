"""Offline acceptance for L2-09A account identity, profile and devices."""
from __future__ import annotations

import copy
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.garmin import GarminCollectionTool, GarminConfig, GarminError, SyncRequest


class AccountTransport:
    def __init__(self) -> None:
        self.account = "fixture-account"
        self.errors: dict[str, GarminError] = {}
        self.calls: list[str] = []
        self.payloads: dict[str, object] = {
            "user_profile": {
                "displayName": "PRIVATE DISPLAY", "email": "private@example.invalid",
                "measurementSystem": "metric", "birthDate": "1990-01-01",
            },
            "user_profile_settings": {
                "timeFormat": "24h", "weekStartDay": "monday",
            },
            "devices": [{
                "serialNumber": "PRIVATE-SERIAL-1", "manufacturer": "Garmin", "productName": "Forerunner",
                "deviceType": "watch", "hardwareVersion": "v1",
            }],
        }

    def login(self) -> None: self.calls.append("login")
    def identity(self) -> str: self.calls.append("identity"); return self.account
    def fetch_health(self, resource_kind: str, _day: str):
        self.calls.append(f"fetch:{resource_kind}")
        if resource_kind in self.errors:
            raise self.errors[resource_kind]
        return copy.deepcopy(self.payloads.get(resource_kind, []))
    def list_activities(self, _start, _through): self.calls.append("activities"); return []
    def activity_summary(self, _activity_id): raise AssertionError("no activity")
    def activity_original(self, _activity_id): raise AssertionError("no activity")
    def activity_extra(self, _activity_id, _role): raise AssertionError("no activity")


def _setup(tmp_path: Path):
    root = tmp_path / "data"
    foundation = FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state/ready.json", root / "state/locks/foundation.lock")
    assert FoundationTool(foundation).execute(FoundationRequest("init", "l2-09a", "2026-01-01T00:00:00Z")).status == "initialized"
    # This test deliberately creates one record per provider environment.
    # Production defaults to CN, so the first leg must request global explicitly.
    config = GarminConfig(
        foundation.database_path,
        foundation.raw_root,
        foundation.state_root,
        "2026-04-15",
        region="global",
        request_min_interval_ms=0,
    )
    transport = AccountTransport()
    tool = GarminCollectionTool(config, transport, sleep=lambda _: None, clock=lambda: datetime(2026, 4, 17), monotonic=lambda: 1_000.0)
    assert tool.execute(SyncRequest("auth")).status == "succeeded"
    return config, tool, transport


def _account_sync(tool: GarminCollectionTool, invocation: str, *resources: str, mode: str = "repair"):
    return tool.execute(SyncRequest(mode, through_local_date="2026-04-15" if mode == "repair" else None, resource_kinds=resources, repair_strategy="refetch" if mode == "repair" else None, invocation_id=invocation))


def test_account_profile_devices_are_redacted_revisioned_and_idempotent(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    first = _account_sync(tool, "account-one", "user_profile", "user_profile_settings", "devices")
    assert first.status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM devices").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM physiology_records WHERE record_type IN ('user_profile','user_profile_settings')").fetchone()[0] == 2
        raw = b"".join((config.raw_root.parent / row[0]).read_bytes() for row in conn.execute("SELECT relative_path FROM raw_objects WHERE resource_kind IN ('user_profile','user_profile_settings','devices')"))
        assert b"PRIVATE DISPLAY" in raw and b"private@example" in raw and b"PRIVATE-SERIAL" in raw and b"PRIVATE_TOKEN" not in raw
        assert b"PRIVATE DISPLAY" not in "\n".join(conn.iterdump()).encode()
        before = dict(conn.execute("SELECT resource_kind,count(*) FROM source_revisions WHERE resource_kind IN ('user_profile','user_profile_settings','devices') GROUP BY resource_kind"))
        uid = conn.execute("SELECT device_uid_hash FROM devices").fetchone()[0]
        assert len(uid) == 64
        assert conn.execute("SELECT mapping_state,canonical_metric_key FROM source_field_catalog WHERE resource_kind='devices' AND field_path='/devices/*/hardwareVersion'").fetchone() == ("mapped", "garmin.device.hardware_version")
    second = _account_sync(tool, "account-repeat", "user_profile", "user_profile_settings", "devices")
    assert second.status == "succeeded" and second.counts["unchanged"] == 3
    with sqlite3.connect(config.database_path) as conn:
        assert dict(conn.execute("SELECT resource_kind,count(*) FROM source_revisions WHERE resource_kind IN ('user_profile','user_profile_settings','devices') GROUP BY resource_kind")) == before
    transport.payloads["devices"].append({"deviceId": "new-device", "manufacturer": "Garmin", "product": "Edge", "deviceType": "bike", "hardwareVersion": "v2"})
    changed = _account_sync(tool, "account-device-change", "devices")
    assert changed.status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM devices").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM source_revisions WHERE resource_kind='devices' AND is_current=1").fetchone()[0] == 1


def test_user_profile_volatile_raw_fields_do_not_create_semantic_revisions(
    tmp_path: Path,
) -> None:
    config, tool, transport = _setup(tmp_path)
    first = _account_sync(tool, "profile-semantic-first", "user_profile")
    assert first.status == "succeeded" and first.counts["revised"] == 1
    with sqlite3.connect(config.database_path) as conn:
        revisions_before = conn.execute(
            "SELECT count(*) FROM source_revisions WHERE resource_kind='user_profile'"
        ).fetchone()[0]
        raw_before = conn.execute(
            "SELECT count(*) FROM raw_objects WHERE resource_kind='user_profile'"
        ).fetchone()[0]

    transport.payloads["user_profile"]["lastLoginTimestamp"] = (
        "2026-04-17T00:00:00Z"
    )
    second = _account_sync(tool, "profile-semantic-volatile-one", "user_profile")
    transport.payloads["user_profile"]["lastLoginTimestamp"] = (
        "2026-04-17T00:01:00Z"
    )
    third = _account_sync(tool, "profile-semantic-volatile-two", "user_profile")
    assert second.counts["unchanged"] == 1
    assert third.counts["unchanged"] == 1
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM source_revisions WHERE resource_kind='user_profile'"
        ).fetchone()[0] == revisions_before
        assert conn.execute(
            "SELECT count(*) FROM raw_objects WHERE resource_kind='user_profile'"
        ).fetchone()[0] == raw_before + 2
        assert conn.execute(
            """SELECT profile_version FROM source_revisions
               WHERE resource_kind='user_profile' AND is_current=1"""
        ).fetchone()[0] == "account-profile-v1"

    transport.payloads["user_profile"]["measurementSystem"] = "statute"
    changed = _account_sync(tool, "profile-semantic-real-change", "user_profile")
    assert changed.counts["revised"] == 1
    audited = tool.execute(
        SyncRequest(
            "audit",
            health_from_local_date="2026-04-15",
            through_local_date="2026-04-15",
            invocation_id="profile-semantic-audit",
        )
    )
    assert audited.status == "succeeded" and audited.counts["failed"] == 0


@pytest.mark.parametrize(
    "credential_key",
    ["access-token", "CLIENT_SECRET", "session.cookie", "api/key", "oauthCredentials"],
)
def test_account_json_credentials_are_quarantined_before_all_payload_writes(
    tmp_path: Path,
    credential_key: str,
) -> None:
    config, tool, transport = _setup(tmp_path)
    marker = "QUARANTINE_ACCOUNT"
    transport.payloads["user_profile"] = {
        "measurementSystem": "metric",
        credential_key: marker,
    }
    invocation = "account-quarantine-" + "".join(
        character for character in credential_key.casefold() if character.isalnum()
    )
    receipt = _account_sync(tool, invocation, "user_profile")
    assert receipt.status in {"partial", "failed"}
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM raw_objects").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM source_revisions").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM physiology_records").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM physiology_metrics").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM source_field_catalog").fetchone()[0] == 0
        assert conn.execute(
            """SELECT count(*) FROM garmin_sync_items
               WHERE resource_kind='user_profile' AND status='failed'
               AND error_code='provider_payload_quarantined'"""
        ).fetchone()[0] == 1
        raw_files = b"".join(
            path.read_bytes() for path in config.raw_root.rglob("*") if path.is_file()
        )
        durable = "\n".join(conn.iterdump()) + receipt.json() + raw_files.decode(errors="ignore")
        assert marker not in durable


def test_explicit_account_repair_is_closed_scope_and_software_never_becomes_hardware(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.calls.clear()
    transport.payloads["devices"] = [{"deviceId": "device-only", "softwareVersion": "software-99"}]
    receipt = _account_sync(tool, "account-only", "devices")
    assert receipt.status == "succeeded"
    assert transport.calls == ["login", "identity", "fetch:devices"]
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT hardware_version FROM devices").fetchone()[0] is None
        raw = b"".join((config.raw_root.parent / row[0]).read_bytes() for row in conn.execute("SELECT relative_path FROM raw_objects WHERE resource_kind='devices'"))
        assert b"softwareVersion" in raw and b"software-99" in raw
        mappings = dict(conn.execute("SELECT field_path,mapping_state FROM source_field_catalog WHERE resource_kind='devices'"))
        assert mappings["/devices/*/softwareVersion"] == "known_passthrough"
        assert "/devices/*/device_uid_hash" not in mappings


def test_account_clock_and_sensitive_errors_are_deterministic(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    first = _account_sync(tool, "clock-one", "user_profile_settings")
    assert first.status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        stamp = conn.execute("SELECT effective_at_utc FROM physiology_records WHERE record_type='user_profile_settings'").fetchone()[0]
    assert stamp == "2026-04-16T16:00:00Z"
    repeat = _account_sync(tool, "clock-repeat", "user_profile_settings")
    assert repeat.counts["unchanged"] == 1
    markers = ("PRIVATE_TOKEN_PRIVATE_SERIAL", "private_payload_alice")
    receipts = []
    for index, marker in enumerate(markers):
        transport.errors["user_profile"] = GarminError(marker, http_status=403)
        receipt = _account_sync(tool, f"private-error-{index}", "user_profile", "devices")
        assert receipt.status == "partial" and marker not in receipt.json()
        receipts.append(receipt)
    with sqlite3.connect(config.database_path) as conn:
        raw = b"".join((config.raw_root.parent / row[0]).read_bytes() for row in conn.execute("SELECT relative_path FROM raw_objects"))
        dump = "\n".join(conn.iterdump()).encode()
        scanned = raw + dump + b"".join(receipt.json().encode() for receipt in receipts)
        assert all(marker.encode() not in scanned for marker in markers)
        assert set(row[0] for row in conn.execute("SELECT error_code FROM garmin_sync_items WHERE error_code IS NOT NULL")) <= {"provider_error"}
        assert set(row[0] for row in conn.execute("SELECT reason_code FROM garmin_sync_gaps WHERE resource_kind='user_profile'")) <= {"provider_error"}
        assert set(row[0] for row in conn.execute("SELECT reason_code FROM garmin_resource_capabilities WHERE resource_kind='user_profile'")) <= {"provider_error"}
        assert set(row[0] for row in conn.execute("SELECT error_summary FROM garmin_sync_runs WHERE error_summary IS NOT NULL")) <= {"provider_error"}


def test_account_identity_conflict_and_hmac_secret_isolation(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    same = tool._identity_hmac("fixture-account")
    other_state = config.state_root / "other-secret"
    other = GarminCollectionTool(GarminConfig(config.database_path, config.raw_root, other_state, "2026-04-15"), transport)
    assert same == tool._identity_hmac("fixture-account")
    assert same != other._identity_hmac("fixture-account")
    with sqlite3.connect(config.database_path) as conn:
        conn.execute("INSERT INTO data_subjects(subject_key,timezone,created_at_utc) VALUES('other','Asia/Singapore','2026-01-01T00:00:00Z')")
        other_subject = conn.execute("SELECT id FROM data_subjects WHERE subject_key='other'").fetchone()[0]
        conn.execute("DELETE FROM subject_identities WHERE provider='garmin'")
        conn.execute("INSERT INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) VALUES(?, 'garmin','account',?,1,'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')", (other_subject, same))
        conn.commit()
    assert tool.execute(SyncRequest("auth")).status == "failed"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM raw_objects WHERE provider='garmin'").fetchone()[0] == 0


def test_capability_reprobe_single_failure_and_snapshot_partial(tmp_path: Path) -> None:
    config, tool, transport = _setup(tmp_path)
    transport.errors["user_profile_settings"] = GarminError("missing", http_status=404)
    failed = _account_sync(tool, "settings-missing", "user_profile", "user_profile_settings", "devices")
    assert failed.status == "partial"
    with sqlite3.connect(config.database_path) as conn:
        state, probe = conn.execute("SELECT capability_state,next_probe_at_utc FROM garmin_resource_capabilities WHERE resource_kind='user_profile_settings'").fetchone()
        assert state == "not_available" and probe is not None
        assert conn.execute("SELECT count(*) FROM source_revisions WHERE resource_kind='devices'").fetchone()[0] == 1
    transport.errors.pop("user_profile_settings")
    restored = _account_sync(tool, "settings-restored", "user_profile_settings")
    assert restored.status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT capability_state,next_probe_at_utc FROM garmin_resource_capabilities WHERE resource_kind='user_profile_settings'").fetchone() == ("supported", None)

    cn = GarminCollectionTool(
        GarminConfig(config.database_path, config.raw_root, config.state_root, "2026-04-15", region="cn", request_min_interval_ms=0),
        transport, sleep=lambda _: None, clock=lambda: datetime(2026, 4, 17), monotonic=lambda: 1_000.0,
    )
    assert cn.execute(SyncRequest("auth")).status == "succeeded"
    assert _account_sync(cn, "cn-devices", "devices").status == "succeeded"
    with sqlite3.connect(config.database_path) as conn:
        assert {row[0] for row in conn.execute("SELECT environment_key FROM garmin_resource_capabilities WHERE resource_kind='devices'")} == {"global", "cn"}

    snap = tool.execute(SyncRequest("snapshot", snapshot_local_date="2026-04-15", invocation_id="account-snapshot"))
    assert snap.coverage_state == "partial"
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM resource_coverage WHERE resource_kind='devices' AND availability_state='partial'").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM garmin_sync_cursors").fetchone()[0] == 0
