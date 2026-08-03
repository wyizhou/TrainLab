from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sqlite3
import tempfile
import time
import re
import secrets
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
import yaml
from jsonschema import Draft202012Validator
from .backup import decrypt_container, encrypt_container, require_key
from .config import read_owner_only_bytes
from .readiness import (
    read_full_verification,
    read_published_status,
    verify_foundation,
)
from .schema import validate_schema_manifest as _validate_schema_manifest


class _PinnedConnection(sqlite3.Connection):
    """A SQLite connection whose pathname is pinned to a checked fd."""
    _foundation_fd: int = -1
    _foundation_parent_fd: int = -1
    _foundation_snapshot_name: str | None = None
    _foundation_snapshot_children: dict[str, tuple[int, int]] | None = None

    def close(self) -> None:  # pragma: no cover - exercised through callers
        """Close SQLite and the two descriptors exactly once.

        A failure from SQLite must never strand the descriptor pair which pins
        the checked database object.  Conversely, a close failure while an
        earlier safety check is unwinding is deliberately handled by the
        caller, so this method preserves the first close failure only after
        attempting both descriptor closes.
        """
        failure: BaseException | None = None
        try:
            super().close()
        except BaseException as exc:  # sqlite extension errors are not always OSError
            failure = exc
        # A nonempty WAL is read through an owner-only short-lived snapshot on
        # platforms where SQLite's ``mode=ro`` still mutates the source shm
        # mapping.  The snapshot lives beneath the already-held parent fd and
        # only its fixed filenames are removed; an unexpected object is left
        # in place rather than being guessed at and deleted.
        snapshot = self._foundation_snapshot_name
        if snapshot and self._foundation_parent_fd >= 0:
            snapshot_fd = -1
            try:
                snapshot_fd = os.open(snapshot, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0), dir_fd=self._foundation_parent_fd)
                expected = self._foundation_snapshot_children or {}
                # Rename each expected child to a private claim first.  A
                # replacement at the canonical child name is thereby never
                # unlinked: it either remains at the canonical name or is
                # restored from an untrusted claim and leaves a blocker.
                for child, identity in expected.items():
                    before = os.stat(child, dir_fd=snapshot_fd, follow_symlinks=False)
                    if not (
                        stat.S_ISREG(before.st_mode)
                        and (before.st_dev, before.st_ino) == identity
                    ):
                        raise OSError("foundation_snapshot_unexpected_object")
                    claim=f".foundation-snapshot-cleanup-{secrets.token_hex(16)}"
                    os.rename(child, claim, src_dir_fd=snapshot_fd, dst_dir_fd=snapshot_fd)
                    claimed=os.stat(claim, dir_fd=snapshot_fd, follow_symlinks=False)
                    if not (stat.S_ISREG(claimed.st_mode) and (claimed.st_dev, claimed.st_ino) == identity):
                        try:
                            os.rename(claim, child, src_dir_fd=snapshot_fd, dst_dir_fd=snapshot_fd)
                        except OSError:
                            pass
                        raise OSError("foundation_snapshot_replaced")
                    # The unlink operates only on the private claim.  A
                    # canonical child created after rename survives; an
                    # unexpected claim replacement is caught by this second
                    # identity check and left as fail-closed evidence.
                    rechecked=os.stat(claim, dir_fd=snapshot_fd, follow_symlinks=False)
                    if (rechecked.st_dev,rechecked.st_ino) != identity:
                        raise OSError("foundation_snapshot_claim_replaced")
                    os.unlink(claim, dir_fd=snapshot_fd)
                if os.listdir(snapshot_fd):
                    raise OSError("foundation_snapshot_unexpected_object")
                os.close(snapshot_fd); snapshot_fd = -1
                os.rmdir(snapshot, dir_fd=self._foundation_parent_fd)
            except BaseException as exc:
                if failure is None:
                    failure = exc
            finally:
                if snapshot_fd >= 0:
                    try:
                        os.close(snapshot_fd)
                    except BaseException as exc:
                        if failure is None:
                            failure = exc
            self._foundation_snapshot_name = None
            self._foundation_snapshot_children = None
        for attribute in ("_foundation_fd", "_foundation_parent_fd"):
            descriptor = getattr(self, attribute, -1)
            if descriptor >= 0:
                setattr(self, attribute, -1)
                try:
                    os.close(descriptor)
                except BaseException as exc:
                    if failure is None:
                        failure = exc
        if failure is not None:
            raise failure

FOUNDATION_SCHEMA_VERSION = 3
RECEIPT_SCHEMA_VERSION = "1"
BACKUP_MAGIC = b"TLFB"
BACKUP_VERSION = b"\x01"
_ALLOWED = {"init", "status", "verify", "migrate"}
_SUCCESS = {"initialized", "already_initialized", "ready"}
_INVOCATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_UTC_RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
_FOUNDATION_V1_MIGRATION_SHA256 = hashlib.sha256(b"foundation-v1").hexdigest()
_PHASE1_DDL = {
    "foundation_state": "CREATE TABLE foundation_state (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL CHECK(state IN ('initializing','ready')), schema_version INTEGER NOT NULL, manifest_sha256 TEXT NOT NULL, initialized_at_utc TEXT, updated_at_utc TEXT NOT NULL, implementation_version TEXT NOT NULL)",
    "schema_migrations": "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at_utc TEXT NOT NULL, code_revision TEXT NOT NULL DEFAULT 'foundation-v1', content_sha256 TEXT NOT NULL)",
}
# These are the exact published v1 contract fingerprints immediately before
# the mail processing-state correction.  They are literals, rather than being
# derived from the current manifest/DDL, so an arbitrary v1-shaped database
# cannot be silently blessed as a migration source.
LEGACY_V1_MANIFEST_SHA256 = "e406492dc044dcc17c5e08776614b9f73ec08580b6c56c14898d9085708e6e88"
LEGACY_V2_MANIFEST_SHA256 = "24b94ca0cffbc61a512fd29a968917020724c276c15e82413485549564b01c4c"
LEGACY_V2_SCHEMA_OBJECTS_SHA256 = "80a3fd0508d31d1bf60d0a3329dee325bdf28d1f8d4a9951a8699a31f623cee5"
LEGACY_V2_FROM_V1_SCHEMA_OBJECTS_SHA256 = "d4538219f96a856a611898bf3349f55a6489793412b0f6018af4e5811c4c4cf2"
LEGACY_V1_SCHEMA_OBJECTS_SHA256 = "781db677d022d7f7904aaea3569662c025d76c659da224ae5876486eeade6732"
LEGACY_V2_ANALYSIS_ARTIFACT_INPUTS_DDL = "id INTEGER PRIMARY KEY, analysis_run_id INTEGER NOT NULL REFERENCES analysis_runs(id), input_role TEXT NOT NULL, source_entity_type TEXT NOT NULL, source_entity_id INTEGER, source_revision_id INTEGER REFERENCES source_revisions(id), source_window_start_utc TEXT, source_window_end_utc TEXT, input_sha256 TEXT NOT NULL, trust_class TEXT NOT NULL CHECK(trust_class IN ('provider_fact','user_asserted','derived_statistic','prior_model_output')), ordinal INTEGER NOT NULL, UNIQUE(analysis_run_id,ordinal)"
LEGACY_V1_MAIL_MESSAGES_DDL = "id INTEGER PRIMARY KEY, mail_thread_id INTEGER NOT NULL REFERENCES mail_threads(id), provider_message_id TEXT NOT NULL UNIQUE, direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound','self_copy','unknown')), actor_role TEXT NOT NULL CHECK(actor_role IN ('user','trainlab','unknown')), sent_at_utc TEXT, received_at_utc TEXT, subject TEXT, body_text TEXT, body_sha256 TEXT, in_reply_to_provider_message_id TEXT, labels_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(labels_json)), source_revision_id INTEGER REFERENCES source_revisions(id), processing_state TEXT NOT NULL DEFAULT 'new' CHECK(processing_state IN ('new','processed','ignored','error'))"
MAIL_PROCESSING_STATES = (
    # Fourth-layer frozen state machine.
    "discovered", "archived", "normalized", "queued", "analyzing",
    "response_accepted", "ready_to_send", "sending", "sent", "store_only",
    "ignored", "quarantined", "awaiting_analysis", "deferred", "rejected",
    "failed", "delivery_unknown",
    # v1 compatibility values: retained for existing rows and old callers; no
    # Foundation migration rewrites business state.
    "new", "processed", "error",
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_utc(value: Any) -> bool:
    if not isinstance(value, str) or _UTC_RFC3339_RE.fullmatch(value) is None:
        return False
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").isoformat().replace("+00:00", "Z") == value
    except ValueError:
        return False


@dataclass(frozen=True)
class FoundationRequest:
    mode: Literal["init", "status", "verify", "migrate"]
    invocation_id: str
    requested_at_utc: str
    target_schema_version: int | None = None


@dataclass(frozen=True)
class FoundationConfig:
    data_root: Path
    database_path: Path
    raw_root: Path
    state_root: Path
    ready_marker: Path
    lock_path: Path
    allowed_root: Path | None = None

    @staticmethod
    def _secure_config_bytes(path: Path) -> bytes:
        """Read a configuration/schema file without accepting a symlink swap.

        The deployed configuration is authority, not a user supplied CLI
        argument.  It may be readable by the owner, but neither it nor its
        containing directory may be group/other writable.
        """
        return read_owner_only_bytes(path)

    @classmethod
    def load(cls, project_root: Path) -> "FoundationConfig":
        project_root=project_root.absolute()
        root_info=project_root.lstat()
        if not (stat.S_ISDIR(root_info.st_mode) and not stat.S_ISLNK(root_info.st_mode) and root_info.st_uid==os.getuid() and stat.S_IMODE(root_info.st_mode)&0o022==0):
            raise ValueError("unsafe_foundation_configuration")
        config_path = project_root / "config" / "foundation.yaml"
        schema_path = project_root / "harness" / "schemas" / "foundation.schema.json"
        for directory in (config_path.parent, schema_path.parent):
            current=project_root
            for component in directory.relative_to(project_root).parts:
                current=current/component; info=current.lstat()
                if not (stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)&0o022==0):
                    raise ValueError("unsafe_foundation_configuration")
        payload = yaml.safe_load(cls._secure_config_bytes(config_path).decode("utf-8"))
        schema = json.loads(cls._secure_config_bytes(schema_path).decode("utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(payload))
        if errors:
            raise ValueError("invalid_foundation_configuration")
        raw = payload["foundation"]
        allowed = project_root
        def relative(value: str, *, role: str) -> Path:
            candidate = Path(value)
            if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
                raise ValueError(f"unsafe_foundation_{role}_path")
            return candidate
        root_rel = relative(raw["data_root"], role="data_root")
        root = allowed / root_rel
        def inside(value: str, *, role: str) -> Path:
            return root / relative(value, role=role)
        result = cls(root, inside(raw["database_path"], role="database"), inside(raw["raw_root"], role="raw"), inside(raw["state_root"], role="state"), inside(raw["ready_marker"], role="marker"), inside(raw["lock_path"], role="lock"), allowed)
        result.validate_paths()
        return result

    def validate_paths(self) -> None:
        root = self.data_root
        allowed = self.allowed_root or root.parent
        if not root.is_absolute() or root == Path("/") or not allowed.is_absolute():
            raise ValueError("unsafe_data_root")
        try:
            root.relative_to(allowed)
        except ValueError as exc:
            raise ValueError("foundation_data_root_outside_allowed_root") from exc
        if root == allowed:
            raise ValueError("foundation_data_root_is_allowed_root")
        targets = {"database": self.database_path, "raw": self.raw_root, "state": self.state_root, "marker": self.ready_marker, "lock": self.lock_path}
        for role, path in targets.items():
            if not path.is_absolute() or path == root:
                raise ValueError(f"unsafe_foundation_{role}_path")
            try:
                relative = path.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"foundation_{role}_outside_data_root") from exc
            if any(part in {"", ".", ".."} for part in relative.parts):
                raise ValueError(f"unsafe_foundation_{role}_path")
        if self.database_path in {self.raw_root, self.state_root} or self.raw_root == self.state_root:
            raise ValueError("foundation_path_role_conflict")
        # A role may not contain another role.  Accepting e.g. data.db under
        # raw would let an otherwise valid-looking config cross trust domains.
        role_paths = {"database": self.database_path, "raw": self.raw_root, "state": self.state_root,
                      "marker": self.ready_marker, "lock": self.lock_path}
        for left, left_path in role_paths.items():
            for right, right_path in role_paths.items():
                if left >= right:
                    continue
                if left_path == right_path or left_path in right_path.parents or right_path in left_path.parents:
                    allowed_pair = {left, right} in ({"state", "marker"}, {"state", "lock"}, {"marker", "lock"})
                    if not allowed_pair:
                        raise ValueError("foundation_path_role_conflict")
        if self.ready_marker.parent != self.state_root:
            raise ValueError("foundation_state_path_role_conflict")
        try:
            self.lock_path.relative_to(self.state_root)
        except ValueError as exc:
            raise ValueError("foundation_state_path_role_conflict") from exc
        # Existing components must be safe before any mode reaches a create or
        # SQLite open.  Missing descendants remain valid for first init.
        for target in (root, *targets.values()):
            current=allowed
            try:
                parts=target.relative_to(allowed).parts
            except ValueError as exc:
                raise ValueError("foundation_path_outside_allowed_root") from exc
            for part in parts:
                current=current/part
                try: info=current.lstat()
                except FileNotFoundError: break
                if stat.S_ISLNK(info.st_mode) or (current != target and not stat.S_ISDIR(info.st_mode)):
                    raise ValueError("unsafe_foundation_ancestor")
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode)&0o022:
                    raise ValueError("unsafe_foundation_ancestor")


@dataclass
class FoundationReceipt:
    schema_version: str = RECEIPT_SCHEMA_VERSION
    invocation_id: str = ""
    mode: str = ""
    status: str = "failed"
    foundation_schema_version: int | None = None
    ready: bool = False
    created_count: int = 0
    existing_count: int = 0
    verified_count: int = 0
    migration_start_version: int | None = None
    migration_end_version: int | None = None
    applied_migration_ids: list[int] = field(default_factory=list)
    next_action: str = "operator_review"
    warnings: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    started_at_utc: str = field(default_factory=lambda: _utc())
    completed_at_utc: str | None = None

    def json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


# Explicit columns for cross-layer stable storage. Domain payloads remain bounded JSON,
# while identity/revision/current/delivery constraints are relational.
TABLES: dict[str, str] = {
    "foundation_state": "id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL CHECK(state IN ('initializing','ready')), schema_version INTEGER NOT NULL, manifest_sha256 TEXT NOT NULL, initialized_at_utc TEXT, updated_at_utc TEXT NOT NULL, implementation_version TEXT NOT NULL",
    "data_subjects": "id INTEGER PRIMARY KEY, subject_key TEXT NOT NULL UNIQUE, timezone TEXT NOT NULL DEFAULT 'Asia/Hong_Kong', is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)), created_at_utc TEXT NOT NULL",
    "subject_identities": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), provider TEXT NOT NULL, identity_kind TEXT NOT NULL, identity_hmac TEXT NOT NULL, is_verified INTEGER NOT NULL DEFAULT 0 CHECK(is_verified IN (0,1)), first_seen_at_utc TEXT NOT NULL, last_seen_at_utc TEXT NOT NULL, UNIQUE(provider,identity_kind,identity_hmac)",
    "raw_objects": "id INTEGER PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-fA-F]*'), relative_path TEXT NOT NULL UNIQUE CHECK(relative_path NOT LIKE '/%' AND relative_path NOT GLOB '../*' AND relative_path NOT LIKE '%/../%' AND relative_path != '..'), media_type TEXT NOT NULL, size_bytes INTEGER NOT NULL CHECK(size_bytes>=0), provider TEXT NOT NULL, resource_kind TEXT NOT NULL, original_name TEXT, fetched_at_utc TEXT NOT NULL CHECK(fetched_at_utc GLOB '*Z')",
    "source_revisions": "id INTEGER PRIMARY KEY, provider TEXT NOT NULL, resource_kind TEXT NOT NULL, provider_object_id TEXT NOT NULL, revision_no INTEGER NOT NULL CHECK(revision_no>0), raw_object_id INTEGER REFERENCES raw_objects(id), payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64 AND payload_hash NOT GLOB '*[^0-9a-fA-F]*'), parser_name TEXT, parser_version TEXT, profile_version TEXT, is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0,1)), parsed_at_utc TEXT, UNIQUE(provider,resource_kind,provider_object_id,revision_no)",
    "resource_coverage": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), provider TEXT NOT NULL, resource_kind TEXT NOT NULL, window_start_utc TEXT, window_end_utc TEXT, local_date TEXT, availability_state TEXT NOT NULL CHECK(availability_state IN ('fetched','partial','empty','not_enabled','not_available','forbidden','not_supported','error')), record_count INTEGER NOT NULL DEFAULT 0, source_revision_id INTEGER REFERENCES source_revisions(id), observed_at_utc TEXT NOT NULL",
    # Layer 2 owns every runtime write to these tables.  Foundation owns only
    # their DDL, schema validation, backup and synthetic-fixture setup.
    "garmin_sync_runs": "id INTEGER PRIMARY KEY, run_id TEXT NOT NULL UNIQUE CHECK(length(run_id)>0), invocation_id TEXT NOT NULL UNIQUE CHECK(length(invocation_id)>0), subject_id INTEGER NOT NULL REFERENCES data_subjects(id), mode TEXT NOT NULL CHECK(mode IN ('full','incremental','snapshot','repair','audit')), requested_from_local_date TEXT, requested_through_local_date TEXT, actual_from_local_date TEXT, actual_through_local_date TEXT, resource_catalog_version TEXT NOT NULL, collector_version TEXT NOT NULL, garminconnect_version TEXT, parser_version TEXT, status TEXT NOT NULL CHECK(status IN ('started','succeeded','partial','deferred','failed','auth_required','lock_busy')), fetched_count INTEGER NOT NULL DEFAULT 0 CHECK(fetched_count>=0), empty_count INTEGER NOT NULL DEFAULT 0 CHECK(empty_count>=0), unchanged_count INTEGER NOT NULL DEFAULT 0 CHECK(unchanged_count>=0), revised_count INTEGER NOT NULL DEFAULT 0 CHECK(revised_count>=0), failed_count INTEGER NOT NULL DEFAULT 0 CHECK(failed_count>=0), deferred_count INTEGER NOT NULL DEFAULT 0 CHECK(deferred_count>=0), next_retry_at_utc TEXT, error_summary TEXT, started_at_utc TEXT NOT NULL, completed_at_utc TEXT",
    "garmin_sync_items": "id INTEGER PRIMARY KEY, garmin_sync_run_id INTEGER NOT NULL REFERENCES garmin_sync_runs(id), resource_kind TEXT NOT NULL, logical_object_key TEXT NOT NULL, stage TEXT NOT NULL CHECK(stage IN ('discover','fetch','archive','extract','parse','project','reconcile','validate')), status TEXT NOT NULL CHECK(status IN ('pending','running','fetched','empty','unchanged','revised','succeeded','failed','deferred','not_available','not_enabled','not_supported','forbidden')), attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0), http_status INTEGER, error_code TEXT, error_summary TEXT, next_retry_at_utc TEXT, source_revision_id INTEGER REFERENCES source_revisions(id), started_at_utc TEXT, completed_at_utc TEXT, UNIQUE(garmin_sync_run_id,resource_kind,logical_object_key,stage)",
    "garmin_sync_cursors": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), resource_kind TEXT NOT NULL, cursor_grain TEXT NOT NULL CHECK(cursor_grain='local_date'), complete_through_local_date TEXT, last_success_at_utc TEXT, last_run_id INTEGER REFERENCES garmin_sync_runs(id), catalog_version TEXT NOT NULL, UNIQUE(subject_id,resource_kind,cursor_grain)",
    "garmin_sync_gaps": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), resource_kind TEXT NOT NULL, logical_object_key TEXT NOT NULL DEFAULT '', window_start_local_date TEXT NOT NULL DEFAULT '', window_end_local_date TEXT NOT NULL DEFAULT '', stage TEXT NOT NULL DEFAULT '', reason_code TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('open','deferred','resolved','ignored_with_reason')), priority INTEGER NOT NULL DEFAULT 0, attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0), next_retry_at_utc TEXT, first_seen_at_utc TEXT NOT NULL, last_attempt_at_utc TEXT, resolved_at_utc TEXT, source_revision_id INTEGER REFERENCES source_revisions(id)",
    "garmin_resource_capabilities": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), environment_key TEXT NOT NULL, resource_kind TEXT NOT NULL, capability_state TEXT NOT NULL CHECK(capability_state IN ('supported','not_enabled','not_available','not_supported','forbidden','unknown')), reason_code TEXT, reason_summary TEXT, first_checked_at_utc TEXT NOT NULL, last_checked_at_utc TEXT NOT NULL, next_probe_at_utc TEXT, source_revision_id INTEGER REFERENCES source_revisions(id), UNIQUE(subject_id,environment_key,resource_kind)",
    "source_field_catalog": "id INTEGER PRIMARY KEY, provider TEXT NOT NULL, resource_kind TEXT NOT NULL, field_path TEXT NOT NULL, observed_type TEXT NOT NULL, first_seen_at_utc TEXT NOT NULL, last_seen_at_utc TEXT NOT NULL, mapping_state TEXT NOT NULL CHECK(mapping_state IN ('mapped','known_passthrough','unknown','ignored_with_reason')), canonical_metric_key TEXT, example_redacted_json TEXT CHECK(json_valid(example_redacted_json)), UNIQUE(provider,resource_kind,field_path)",
    "devices": "id INTEGER PRIMARY KEY, device_uid_hash TEXT NOT NULL UNIQUE, manufacturer TEXT, product TEXT, device_type TEXT, hardware_version TEXT, first_seen_at_utc TEXT NOT NULL, last_seen_at_utc TEXT NOT NULL",
    "activities": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), provider TEXT NOT NULL, provider_activity_id TEXT NOT NULL, name TEXT, sport TEXT, sub_sport TEXT, start_time_utc TEXT NOT NULL, end_time_utc TEXT, local_date TEXT NOT NULL, elapsed_seconds REAL, timer_seconds REAL, distance_m REAL, extras_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(extras_json)), source_map_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(source_map_json)), primary_revision_id INTEGER REFERENCES source_revisions(id), provider_state TEXT NOT NULL DEFAULT 'active' CHECK(provider_state IN ('active','suspected_missing','provider_deleted')), first_missing_at_utc TEXT, last_missing_at_utc TEXT, provider_deleted_at_utc TEXT, UNIQUE(provider,provider_activity_id)",
    "activity_devices": "id INTEGER PRIMARY KEY, activity_id INTEGER NOT NULL REFERENCES activities(id), device_id INTEGER NOT NULL REFERENCES devices(id), device_role TEXT NOT NULL CHECK(device_role IN ('main_device','heart_rate_sensor','power_sensor','developer_app','unknown')), source_revision_id INTEGER REFERENCES source_revisions(id), UNIQUE(activity_id,device_id,device_role,source_revision_id)",
    "activity_metric_sources": "id INTEGER PRIMARY KEY, activity_id INTEGER NOT NULL REFERENCES activities(id), metric_key TEXT NOT NULL, valid_from_utc TEXT, valid_to_utc TEXT, source_kind TEXT NOT NULL, device_id INTEGER REFERENCES devices(id), developer_data_index INTEGER, attribution_method TEXT NOT NULL CHECK(attribution_method IN ('explicit_device','explicit_developer','provider_metadata','inferred','unknown')), confidence REAL CHECK(confidence IS NULL OR (confidence>=0 AND confidence<=1)), CHECK(valid_to_utc IS NULL OR valid_from_utc IS NULL OR valid_to_utc>=valid_from_utc)",
    "activity_source_revisions": "id INTEGER PRIMARY KEY, activity_id INTEGER NOT NULL REFERENCES activities(id), source_revision_id INTEGER NOT NULL REFERENCES source_revisions(id), source_role TEXT NOT NULL CHECK(source_role IN ('summary_json','activity_fit','splits_json','typed_splits_json','split_summaries_json','exercise_sets_json','hr_zones_json','power_zones_json','weather_json','gear_json','details_json_fallback','legacy_fit','manual')), is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)), UNIQUE(activity_id,source_revision_id,source_role)",
    "daily_health": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), local_date TEXT NOT NULL CHECK(local_date GLOB '????-??-??'), values_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(values_json)), extras_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(extras_json)), source_map_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(source_map_json)), source_revision_id INTEGER REFERENCES source_revisions(id), is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0,1))",
    "health_samples": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), observed_at_utc TEXT NOT NULL CHECK(observed_at_utc GLOB '*Z'), local_date TEXT NOT NULL CHECK(local_date GLOB '????-??-??'), metric_key TEXT NOT NULL, value_number REAL, value_text TEXT, raw_value_json TEXT CHECK(json_valid(raw_value_json)), raw_unit TEXT, canonical_unit TEXT, device_id INTEGER REFERENCES devices(id), source_revision_id INTEGER REFERENCES source_revisions(id), CHECK((value_number IS NOT NULL) + (value_text IS NOT NULL) <= 1), CHECK((value_number IS NOT NULL) + (value_text IS NOT NULL) + (raw_value_json IS NOT NULL) >= 1)",
    "physiology_records": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), domain TEXT NOT NULL, record_type TEXT NOT NULL, provider_record_id TEXT, effective_at_utc TEXT, period_start_utc TEXT, period_end_utc TEXT, local_date TEXT, value_origin TEXT NOT NULL CHECK(value_origin IN ('sensor_observed','user_entered','provider_derived','provider_predicted','profile_setting','unknown')), status_key TEXT, status_text TEXT, extras_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(extras_json)), source_revision_id INTEGER REFERENCES source_revisions(id)",
    "physiology_metrics": "id INTEGER PRIMARY KEY, physiology_record_id INTEGER NOT NULL REFERENCES physiology_records(id), metric_key TEXT NOT NULL, value_number REAL, value_text TEXT, value_boolean INTEGER CHECK(value_boolean IN (0,1)), value_json TEXT CHECK(json_valid(value_json)), raw_unit TEXT, canonical_unit TEXT, value_origin TEXT NOT NULL CHECK(value_origin IN ('sensor_observed','user_entered','provider_derived','provider_predicted','profile_setting','unknown')), source_path TEXT, CHECK((value_number IS NOT NULL)+(value_text IS NOT NULL)+(value_boolean IS NOT NULL)+(value_json IS NOT NULL)<=1), UNIQUE(physiology_record_id,metric_key)",
    "sleep_sessions": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), session_type TEXT NOT NULL CHECK(session_type IN ('main_sleep','nap','unknown')), start_time_utc TEXT NOT NULL, end_time_utc TEXT NOT NULL, values_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(values_json)), extras_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(extras_json)), source_map_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(source_map_json)), source_revision_id INTEGER REFERENCES source_revisions(id)",
    "sleep_stages": "id INTEGER PRIMARY KEY, sleep_session_id INTEGER NOT NULL REFERENCES sleep_sessions(id), stage_index INTEGER NOT NULL, stage_type TEXT NOT NULL, start_time_utc TEXT NOT NULL, end_time_utc TEXT NOT NULL, duration_seconds REAL NOT NULL, source_revision_id INTEGER REFERENCES source_revisions(id), UNIQUE(sleep_session_id,stage_index)",
    "body_measurements": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), observed_at_utc TEXT, local_date TEXT, values_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(values_json)), extras_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(extras_json)), source_revision_id INTEGER REFERENCES source_revisions(id)",
    "activity_segments": "id INTEGER PRIMARY KEY, activity_id INTEGER NOT NULL REFERENCES activities(id), segment_type TEXT NOT NULL CHECK(segment_type IN ('lap','split','climb_active','climb_rest','strength_active','strength_rest','workout_step','length','interval')), segment_index INTEGER NOT NULL CHECK(segment_index>=0), parent_segment_id INTEGER REFERENCES activity_segments(id), start_time_utc TEXT, end_time_utc TEXT, duration_seconds REAL CHECK(duration_seconds IS NULL OR duration_seconds>=0), distance_m REAL CHECK(distance_m IS NULL OR distance_m>=0), extras_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(extras_json)), source_revision_id INTEGER NOT NULL REFERENCES source_revisions(id), UNIQUE(activity_id,source_revision_id,segment_type,segment_index)",
    "activity_samples": "id INTEGER PRIMARY KEY, activity_id INTEGER NOT NULL REFERENCES activities(id), source_revision_id INTEGER NOT NULL REFERENCES source_revisions(id), stream_kind TEXT NOT NULL, sample_index INTEGER NOT NULL, timestamp_utc TEXT, latitude REAL, longitude REAL, distance_m REAL, speed_mps REAL, altitude_m REAL, heart_rate_bpm REAL, cadence_rpm REAL, power_w REAL, temperature_c REAL, extras_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(extras_json)), UNIQUE(activity_id,source_revision_id,stream_kind,sample_index)",
    "fit_metric_definitions": "id INTEGER PRIMARY KEY, source_revision_id INTEGER NOT NULL REFERENCES source_revisions(id), developer_data_index INTEGER NOT NULL, native_mesg_num INTEGER, field_definition_number INTEGER NOT NULL, field_name TEXT, base_type TEXT, raw_unit TEXT, canonical_metric_key TEXT, UNIQUE(source_revision_id,developer_data_index,field_definition_number)",
    "activity_aux_messages": "id INTEGER PRIMARY KEY, activity_id INTEGER NOT NULL REFERENCES activities(id), source_revision_id INTEGER NOT NULL REFERENCES source_revisions(id), global_message_number INTEGER NOT NULL, message_name TEXT, message_index INTEGER NOT NULL, timestamp_utc TEXT, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), UNIQUE(activity_id,source_revision_id,global_message_number,message_index)",
    "fit_unknown_message_catalog": "id INTEGER PRIMARY KEY, source_revision_id INTEGER NOT NULL REFERENCES source_revisions(id), global_message_number INTEGER NOT NULL, message_count INTEGER NOT NULL, field_signature_json TEXT NOT NULL CHECK(json_valid(field_signature_json)), first_timestamp_utc TEXT, last_timestamp_utc TEXT, UNIQUE(source_revision_id,global_message_number)",
    "course_points": "id INTEGER PRIMARY KEY, activity_id INTEGER NOT NULL REFERENCES activities(id), course_identity TEXT NOT NULL DEFAULT '', point_index INTEGER NOT NULL CHECK(point_index>=0), name TEXT, point_type TEXT, distance_m REAL, latitude REAL, longitude REAL, route_time_utc TEXT, UNIQUE(activity_id,course_identity,point_index)",
    "climbing_routes": "id INTEGER PRIMARY KEY, segment_id INTEGER NOT NULL UNIQUE REFERENCES activity_segments(id), grade_raw TEXT, grade_system TEXT, grade_display TEXT, completed INTEGER CHECK(completed IN (0,1)), falls INTEGER, ascent_meters REAL",
    "strength_sets": "id INTEGER PRIMARY KEY, segment_id INTEGER NOT NULL UNIQUE REFERENCES activity_segments(id), workout_step_index INTEGER, set_type TEXT, exercise_category TEXT, raw_exercise_number INTEGER, exercise_name TEXT, repetitions INTEGER, weight_kg REAL, duration_seconds REAL",
    "mail_threads": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), provider_thread_id TEXT NOT NULL, normalized_subject TEXT, first_message_at_utc TEXT, last_message_at_utc TEXT, message_count INTEGER NOT NULL DEFAULT 0, trainlab_label_state TEXT, is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0,1)), UNIQUE(subject_id,provider_thread_id)",
    "mail_messages": "id INTEGER PRIMARY KEY, mail_thread_id INTEGER NOT NULL REFERENCES mail_threads(id), provider_message_id TEXT NOT NULL UNIQUE, direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound','self_copy','unknown')), actor_role TEXT NOT NULL CHECK(actor_role IN ('user','trainlab','unknown')), sent_at_utc TEXT, received_at_utc TEXT, subject TEXT, body_text TEXT, body_sha256 TEXT, in_reply_to_provider_message_id TEXT, labels_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(labels_json)), source_revision_id INTEGER REFERENCES source_revisions(id), processing_state TEXT NOT NULL DEFAULT 'discovered' CHECK(processing_state IN ('discovered','archived','normalized','queued','analyzing','response_accepted','ready_to_send','sending','sent','store_only','ignored','quarantined','awaiting_analysis','deferred','rejected','failed','delivery_unknown','new','processed','error'))",
    "mail_attachments": "id INTEGER PRIMARY KEY, mail_message_id INTEGER NOT NULL REFERENCES mail_messages(id), provider_attachment_id TEXT, filename TEXT, media_type TEXT, size_bytes INTEGER, raw_object_id INTEGER REFERENCES raw_objects(id), content_disposition TEXT",
    "conversation_events": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), event_type TEXT NOT NULL, actor_role TEXT NOT NULL CHECK(actor_role IN ('user','trainlab','unknown')), occurred_at_utc TEXT NOT NULL CHECK(occurred_at_utc GLOB '*Z'), mail_message_id INTEGER REFERENCES mail_messages(id), analysis_artifact_id INTEGER REFERENCES analysis_artifacts(id), mail_response_artifact_id INTEGER REFERENCES mail_response_artifacts(id), analysis_delivery_id INTEGER REFERENCES analysis_deliveries(id), mail_delivery_id INTEGER REFERENCES mail_deliveries(id), related_run_key TEXT, content_text TEXT, structured_payload_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(structured_payload_json)), trust_level TEXT NOT NULL CHECK(trust_level IN ('untrusted_content','system_generated')), created_by TEXT NOT NULL, UNIQUE(mail_message_id,event_type)",
    "user_facts": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), fact_key TEXT NOT NULL, fact_value_json TEXT NOT NULL CHECK(json_valid(fact_value_json)), scope TEXT NOT NULL CHECK(scope IN ('message_only','temporary','long_term')), effective_from_utc TEXT, expires_at_utc TEXT, source_event_id INTEGER REFERENCES conversation_events(id), confidence REAL, is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)), superseded_by_fact_id INTEGER REFERENCES user_facts(id)",
    "mail_agent_runs": "id INTEGER PRIMARY KEY, run_key TEXT NOT NULL UNIQUE, invocation_id TEXT NOT NULL UNIQUE, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), mail_thread_id INTEGER REFERENCES mail_threads(id), request_kind TEXT NOT NULL CHECK(request_kind IN ('run','poll','process','deliver_response','reconcile','status')), status TEXT NOT NULL CHECK(status IN ('started','succeeded','partial','failed','deferred','rejected')), shared_harness_version TEXT, mail_harness_version TEXT, input_schema_version TEXT, output_schema_version TEXT, context_snapshot_json TEXT CHECK(json_valid(context_snapshot_json)), context_snapshot_sha256 TEXT, next_retry_at_utc TEXT, started_at_utc TEXT NOT NULL, completed_at_utc TEXT",
    "mail_agent_items": "id INTEGER PRIMARY KEY, mail_agent_run_id INTEGER NOT NULL REFERENCES mail_agent_runs(id), logical_item_kind TEXT NOT NULL, logical_item_id TEXT NOT NULL, mail_message_id INTEGER REFERENCES mail_messages(id), dependency_analysis_artifact_id INTEGER REFERENCES analysis_artifacts(id), mail_response_artifact_id INTEGER REFERENCES mail_response_artifacts(id), mail_delivery_id INTEGER REFERENCES mail_deliveries(id), stage TEXT NOT NULL CHECK(stage IN ('discover','archive','normalize','classify','context','generate','validate','publish','render','send','verify')), status TEXT NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0), error_code TEXT, error_summary TEXT, next_retry_at_utc TEXT, started_at_utc TEXT, completed_at_utc TEXT, UNIQUE(mail_agent_run_id,logical_item_kind,logical_item_id,stage)",
    "mail_poll_cursors": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), identity_id INTEGER NOT NULL REFERENCES subject_identities(id), stream_kind TEXT NOT NULL CHECK(stream_kind IN ('trainlab_label','tracked_threads')), observed_through_utc TEXT, overlap_start_utc TEXT, last_successful_run_id INTEGER REFERENCES mail_agent_runs(id), updated_at_utc TEXT NOT NULL, UNIQUE(subject_id,identity_id,stream_kind)",
    "mail_response_artifacts": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), mail_thread_id INTEGER REFERENCES mail_threads(id), in_reply_to_mail_message_id INTEGER REFERENCES mail_messages(id), response_kind TEXT NOT NULL, revision_no INTEGER NOT NULL CHECK(revision_no>0), generated_by_mail_agent_run_id INTEGER NOT NULL REFERENCES mail_agent_runs(id), schema_version TEXT NOT NULL, structured_content_json TEXT NOT NULL CHECK(json_valid(structured_content_json)), user_visible_text TEXT NOT NULL, content_sha256 TEXT NOT NULL, is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0,1)), supersedes_mail_response_artifact_id INTEGER REFERENCES mail_response_artifacts(id), created_at_utc TEXT NOT NULL, UNIQUE(subject_id,mail_thread_id,response_kind,revision_no)",
    "mail_response_inputs": "id INTEGER PRIMARY KEY, mail_agent_run_id INTEGER NOT NULL REFERENCES mail_agent_runs(id), input_role TEXT NOT NULL, source_entity_type TEXT NOT NULL, source_entity_id INTEGER, source_revision_id INTEGER REFERENCES source_revisions(id), input_sha256 TEXT NOT NULL, trust_class TEXT NOT NULL CHECK(trust_class IN ('provider_fact','user_asserted','derived_statistic','prior_model_output')), ordinal INTEGER NOT NULL, UNIQUE(mail_agent_run_id,ordinal)",
    "mail_deliveries": "id INTEGER PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE, delivery_kind TEXT NOT NULL CHECK(delivery_kind='mail_response'), related_run_key TEXT, mail_message_id INTEGER REFERENCES mail_messages(id), provider_thread_id TEXT, status TEXT NOT NULL CHECK(status IN ('pending','sending','sent','already_sent','delivery_unknown','failed')), sent_at_utc TEXT, last_verified_at_utc TEXT, error_code TEXT, error_summary TEXT, created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL",
    "mail_delivery_artifacts": "id INTEGER PRIMARY KEY, mail_delivery_id INTEGER NOT NULL REFERENCES mail_deliveries(id), mail_response_artifact_id INTEGER NOT NULL REFERENCES mail_response_artifacts(id), content_role TEXT NOT NULL CHECK(content_role='mail_response'), ordinal INTEGER NOT NULL, UNIQUE(mail_delivery_id,mail_response_artifact_id,content_role,ordinal)",
    "analysis_runs": "id INTEGER PRIMARY KEY, run_key TEXT NOT NULL UNIQUE, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), analysis_kind TEXT NOT NULL CHECK(analysis_kind IN ('daily','weekly','plan_revision','regeneration')), target_start_local_date TEXT, target_end_local_date TEXT, status TEXT NOT NULL CHECK(status IN ('started','succeeded','failed','rejected')), harness_version TEXT, input_schema_version TEXT, output_schema_version TEXT, context_snapshot_json TEXT CHECK(json_valid(context_snapshot_json)), context_snapshot_sha256 TEXT, generator_metadata_json TEXT CHECK(json_valid(generator_metadata_json)), started_at_utc TEXT NOT NULL, completed_at_utc TEXT",
    "analysis_artifacts": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), artifact_kind TEXT NOT NULL CHECK(artifact_kind IN ('daily_summary','daily_training_advice','weekly_summary','weekly_training_plan')), period_start_local_date TEXT NOT NULL, period_end_local_date TEXT NOT NULL, revision_no INTEGER NOT NULL, generated_by_run_id INTEGER NOT NULL REFERENCES analysis_runs(id), schema_version TEXT NOT NULL, structured_content_json TEXT NOT NULL CHECK(json_valid(structured_content_json)), user_visible_text TEXT NOT NULL, content_sha256 TEXT NOT NULL, is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0,1)), supersedes_artifact_id INTEGER REFERENCES analysis_artifacts(id), created_at_utc TEXT NOT NULL, UNIQUE(subject_id,artifact_kind,period_start_local_date,period_end_local_date,revision_no)",
    "analysis_artifact_inputs": "id INTEGER PRIMARY KEY, analysis_run_id INTEGER NOT NULL REFERENCES analysis_runs(id), input_role TEXT NOT NULL, source_entity_type TEXT NOT NULL, source_entity_id INTEGER, source_revision_id INTEGER REFERENCES source_revisions(id), source_window_start_utc TEXT, source_window_end_utc TEXT, input_sha256 TEXT NOT NULL, trust_class TEXT NOT NULL CHECK(trust_class IN ('provider_fact','provider_derived','provider_predicted','user_asserted','derived_statistic','prior_model_output','unknown')), ordinal INTEGER NOT NULL, UNIQUE(analysis_run_id,ordinal)",
    "analysis_artifact_relations": "id INTEGER PRIMARY KEY, from_artifact_id INTEGER NOT NULL REFERENCES analysis_artifacts(id), to_artifact_id INTEGER NOT NULL REFERENCES analysis_artifacts(id), relation_type TEXT NOT NULL CHECK(relation_type IN ('supersedes','derived_from','paired_with','references_prior_summary','references_prior_plan')), created_at_utc TEXT NOT NULL, UNIQUE(from_artifact_id,to_artifact_id,relation_type)",
    "training_plans": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), analysis_artifact_id INTEGER NOT NULL UNIQUE REFERENCES analysis_artifacts(id), plan_start_local_date TEXT NOT NULL, plan_end_local_date TEXT NOT NULL, timezone TEXT NOT NULL CHECK(timezone='Asia/Hong_Kong'), status TEXT NOT NULL CHECK(status IN ('proposed','active','completed','superseded','cancelled')), objective_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(objective_json)), constraints_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(constraints_json)), created_at_utc TEXT NOT NULL, CHECK(julianday(plan_end_local_date)-julianday(plan_start_local_date)=6)",
    "training_plan_items": "id INTEGER PRIMARY KEY, training_plan_id INTEGER NOT NULL REFERENCES training_plans(id), item_index INTEGER NOT NULL, local_date TEXT NOT NULL, activity_kind TEXT NOT NULL CHECK(activity_kind IN ('running','climbing','strength','rest')), prescription_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(prescription_json)), rationale_text TEXT, stop_conditions_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(stop_conditions_json)), UNIQUE(training_plan_id,item_index)",
    "analysis_deliveries": "id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES data_subjects(id), idempotency_key TEXT NOT NULL UNIQUE, analysis_run_id INTEGER NOT NULL REFERENCES analysis_runs(id), delivery_kind TEXT NOT NULL CHECK(delivery_kind IN ('daily_report','weekly_report','plan_revision')), status TEXT NOT NULL CHECK(status IN ('pending','sending','sent','already_sent','delivery_unknown','failed')), provider_message_id TEXT, provider_thread_id TEXT, sent_at_utc TEXT, last_verified_at_utc TEXT, error_code TEXT, error_summary TEXT, created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL",
    "analysis_delivery_artifacts": "id INTEGER PRIMARY KEY, analysis_delivery_id INTEGER NOT NULL REFERENCES analysis_deliveries(id), analysis_artifact_id INTEGER NOT NULL REFERENCES analysis_artifacts(id), content_role TEXT NOT NULL CHECK(content_role IN ('daily_summary','daily_advice','weekly_summary','weekly_plan','plan_revision')), ordinal INTEGER NOT NULL, UNIQUE(analysis_delivery_id,analysis_artifact_id,content_role)",
    "data_quality_issues": "id INTEGER PRIMARY KEY, entity_type TEXT NOT NULL, entity_id INTEGER, issue_code TEXT NOT NULL, severity TEXT NOT NULL CHECK(severity IN ('info','warning','error')), details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)), status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','acknowledged','resolved','suppressed')), first_seen_at_utc TEXT NOT NULL, last_seen_at_utc TEXT NOT NULL, resolved_at_utc TEXT, source_revision_id INTEGER REFERENCES source_revisions(id)",
    "reconciliation_results": "id INTEGER PRIMARY KEY, entity_type TEXT NOT NULL, entity_id INTEGER, field_key TEXT NOT NULL, left_source_revision_id INTEGER REFERENCES source_revisions(id), right_source_revision_id INTEGER REFERENCES source_revisions(id), left_value_json TEXT CHECK(json_valid(left_value_json)), right_value_json TEXT CHECK(json_valid(right_value_json)), absolute_difference REAL, relative_difference REAL, tolerance REAL CHECK(tolerance IS NULL OR tolerance>=0), result TEXT NOT NULL CHECK(result IN ('match','within_tolerance','mismatch','not_comparable')), checked_at_utc TEXT NOT NULL",
    "scheduler_jobs": "id INTEGER PRIMARY KEY, job_key TEXT NOT NULL UNIQUE, workflow_kind TEXT NOT NULL, timezone TEXT NOT NULL, schedule_spec_json TEXT NOT NULL CHECK(json_valid(schedule_spec_json)), is_enabled INTEGER NOT NULL CHECK(is_enabled IN (0,1)), misfire_policy TEXT NOT NULL, last_due_at_utc TEXT, next_due_at_utc TEXT, config_sha256 TEXT NOT NULL, updated_at_utc TEXT NOT NULL",
    "scheduler_leases": "id INTEGER PRIMARY KEY, lease_key TEXT NOT NULL UNIQUE, owner_instance_id TEXT NOT NULL, owner_pid INTEGER NOT NULL, acquired_at_utc TEXT NOT NULL, heartbeat_at_utc TEXT NOT NULL, expires_at_utc TEXT NOT NULL",
    "orchestrator_runs": "id INTEGER PRIMARY KEY, workflow_key TEXT NOT NULL UNIQUE, workflow_kind TEXT NOT NULL, subject_id INTEGER REFERENCES data_subjects(id), logical_local_date TEXT, trigger_kind TEXT NOT NULL CHECK(trigger_kind IN ('scheduled','manual','recovery','reconcile')), status TEXT NOT NULL CHECK(status IN ('started','succeeded','partial','failed','deferred','cancelled')), deadline_at_utc TEXT, parent_workflow_run_id INTEGER REFERENCES orchestrator_runs(id), started_at_utc TEXT NOT NULL, completed_at_utc TEXT, result_summary_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(result_summary_json))",
    "orchestrator_steps": "id INTEGER PRIMARY KEY, orchestrator_run_id INTEGER NOT NULL REFERENCES orchestrator_runs(id), step_key TEXT NOT NULL, ordinal INTEGER NOT NULL CHECK(ordinal>=0), layer_no INTEGER NOT NULL CHECK(layer_no BETWEEN 1 AND 5), tool_mode TEXT NOT NULL, request_sha256 TEXT NOT NULL, invocation_id TEXT, downstream_run_id TEXT, receipt_sha256 TEXT, status TEXT NOT NULL CHECK(status IN ('pending','running','succeeded','failed','deferred','skipped')), attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0), next_retry_at_utc TEXT, started_at_utc TEXT, completed_at_utc TEXT, UNIQUE(orchestrator_run_id,step_key)",
    "service_health_checks": "id INTEGER PRIMARY KEY, check_kind TEXT NOT NULL, target_kind TEXT NOT NULL, target_id TEXT, status TEXT NOT NULL, metrics_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metrics_json)), threshold_version TEXT, checked_at_utc TEXT NOT NULL",
    "operational_incidents": "id INTEGER PRIMARY KEY, incident_key TEXT NOT NULL UNIQUE, category TEXT NOT NULL, severity TEXT NOT NULL CHECK(severity IN ('info','warning','error','critical')), state TEXT NOT NULL CHECK(state IN ('open','acknowledged','resolved','suppressed')), related_workflow_run_id INTEGER REFERENCES orchestrator_runs(id), related_step_id INTEGER REFERENCES orchestrator_steps(id), first_seen_at_utc TEXT NOT NULL, last_seen_at_utc TEXT NOT NULL, occurrence_count INTEGER NOT NULL DEFAULT 1, resolved_at_utc TEXT, error_code TEXT, error_summary TEXT, next_action TEXT",
    "operational_alert_deliveries": "id INTEGER PRIMARY KEY, operational_incident_id INTEGER NOT NULL REFERENCES operational_incidents(id), idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL CHECK(status IN ('pending','sending','sent','already_sent','delivery_unknown','failed')), provider_message_id TEXT, provider_thread_id TEXT, sent_at_utc TEXT, last_verified_at_utc TEXT, error_code TEXT, error_summary TEXT",
}

VIEWS = {
    "v_current_daily_health": "SELECT * FROM daily_health WHERE is_current=1",
    "v_current_physiology_records": "SELECT * FROM physiology_records WHERE source_revision_id IS NULL OR source_revision_id IN (SELECT id FROM source_revisions WHERE is_current=1)",
    "v_current_physiology_metrics": "SELECT m.* FROM physiology_metrics m JOIN physiology_records r ON r.id=m.physiology_record_id WHERE r.source_revision_id IS NULL OR r.source_revision_id IN (SELECT id FROM source_revisions WHERE is_current=1)",
    "v_current_sleep_sessions": "SELECT * FROM sleep_sessions WHERE source_revision_id IS NULL OR source_revision_id IN (SELECT id FROM source_revisions WHERE is_current=1)",
    "v_current_activities": "SELECT * FROM activities WHERE provider_state != 'provider_deleted'",
    "v_activity_segments": "SELECT * FROM activity_segments",
    "v_activity_metric_sources": "SELECT * FROM activity_metric_sources",
    "v_current_mail_threads": "SELECT * FROM mail_threads WHERE is_current=1",
    "v_current_mail_messages": "SELECT * FROM mail_messages",
    "v_conversation_context": "SELECT * FROM conversation_events ORDER BY occurred_at_utc,id",
    "v_active_user_facts": "SELECT * FROM user_facts WHERE is_active=1",
    "v_current_analysis_artifacts": "SELECT * FROM analysis_artifacts WHERE is_current=1",
    "v_current_weekly_summaries": "SELECT * FROM analysis_artifacts WHERE is_current=1 AND artifact_kind='weekly_summary'",
    "v_current_training_plans": "SELECT * FROM training_plans WHERE status IN ('proposed','active')",
    "v_training_plan_items": "SELECT * FROM training_plan_items",
    "v_analysis_history_context": "SELECT *, 'prior_model_output' AS trust_class FROM analysis_artifacts",
    "v_current_analysis_deliveries": "SELECT * FROM analysis_deliveries",
    "v_current_mail_response_artifacts": "SELECT * FROM mail_response_artifacts WHERE is_current=1",
    "v_mail_response_history_context": "SELECT *, 'prior_model_output' AS trust_class FROM mail_response_artifacts",
    "v_plan_revision_reason_events": "SELECT * FROM conversation_events WHERE event_type='plan_revision_reason_recorded'",
    "v_open_data_quality_issues": "SELECT * FROM data_quality_issues WHERE status IN ('open','acknowledged')",
    "v_recent_orchestrator_runs": "SELECT * FROM orchestrator_runs ORDER BY started_at_utc DESC",
    "v_open_operational_incidents": "SELECT * FROM operational_incidents WHERE state IN ('open','acknowledged')",
}


def validate_schema_manifest(conn: sqlite3.Connection, manifest: dict[str, Any]) -> list[str]:
    """Compatibility export for the schema module's read-only validator."""
    return _validate_schema_manifest(conn, manifest)


class FoundationTool:
    def __init__(self, config: FoundationConfig, failpoint: Any = None) -> None:
        self.config = config
        self.data_root = config.data_root
        self.failpoint = failpoint

    def execute(self, request: FoundationRequest) -> FoundationReceipt:
        # Do not dereference an untrusted request before the validation guard:
        # API callers get the same one-receipt/no-I/O failure behavior as CLI.
        raw_invocation = getattr(request, "invocation_id", "")
        raw_mode = getattr(request, "mode", "")
        safe_invocation = raw_invocation if isinstance(raw_invocation, str) and _INVOCATION_RE.fullmatch(raw_invocation) else ""
        receipt = FoundationReceipt(invocation_id=safe_invocation, mode=raw_mode if raw_mode in _ALLOWED else "")
        try:
            self._validate_request(request)
            self.config.validate_paths()
            root = self.data_root
            self._validate_root(root)
            if request.mode == "status":
                self._read_status(root, receipt)
            elif request.mode == "verify":
                self._verify(root, receipt)
            elif request.mode == "init":
                self._init(root, receipt)
            else:
                self._migrate(root, request.target_schema_version, receipt)
        except BlockingIOError:
            receipt.status, receipt.next_action = "lock_busy", "none"
        except IncompatibleError as exc:
            receipt.status = "incompatible"
            receipt.next_action = "explicit_migrate" if str(exc).startswith("higher_schema_version") else "operator_review"
            receipt.errors.append({"code": "incompatible", "summary": str(exc)})
        except CorruptFoundationError as exc:
            receipt.status, receipt.next_action = "failed", "operator_review"
            receipt.errors.append({"code": "corrupt_sqlite", "summary": str(exc)})
        except Exception as exc:
            receipt.status, receipt.next_action = "failed", "operator_review"
            receipt.errors.append({"code": type(exc).__name__, "summary": "foundation_operation_failed"})
        receipt.completed_at_utc = _utc()
        return receipt

    @staticmethod
    def _validate_request(request: FoundationRequest) -> None:
        """Enforce the public Request contract before any filesystem access."""
        if not isinstance(request, FoundationRequest) or request.mode not in _ALLOWED or not isinstance(request.invocation_id, str) or _INVOCATION_RE.fullmatch(request.invocation_id) is None or not isinstance(request.requested_at_utc, str):
            raise ValueError("invalid_foundation_request")
        if _UTC_RFC3339_RE.fullmatch(request.requested_at_utc) is None:
            raise ValueError("requested_at_must_be_utc_z")
        try:
            parsed=datetime.fromisoformat(request.requested_at_utc[:-1] + "+00:00")
        except ValueError as exc:
            raise ValueError("requested_at_must_be_utc_z") from exc
        if parsed.isoformat().replace("+00:00","Z") != request.requested_at_utc:
            raise ValueError("requested_at_must_be_utc_z")
        target = request.target_schema_version
        if request.mode == "migrate":
            if isinstance(target, bool) or not isinstance(target, int):
                raise ValueError("migrate_requires_integer_target_schema_version")
        elif target is not None:
            raise ValueError("non_migrate_requires_null_target_schema_version")

    def _paths(self, root: Path) -> dict[str, Path]:
        return {"root": root, "db": self.config.database_path, "raw": self.config.raw_root, "state": self.config.state_root, "ready": self.config.ready_marker, "lock": self.config.lock_path}

    def _validate_root(self, root: Path) -> None:
        self.config.validate_paths()
        # Lexical containment is not enough: an existing symlink component can
        # redirect a later create/open outside the approved root.
        allowed = self.config.allowed_root or root.parent
        for target in (root, self.config.database_path, self.config.raw_root, self.config.state_root, self.config.ready_marker, self.config.lock_path):
            try:
                rel = target.relative_to(allowed)
            except ValueError as exc:
                raise ValueError("foundation_path_outside_allowed_root") from exc
            current = allowed
            for part in rel.parts:
                current = current / part
                try:
                    info = current.lstat()
                except FileNotFoundError:
                    break
                if stat.S_ISLNK(info.st_mode) or (current != target and not stat.S_ISDIR(info.st_mode)):
                    raise ValueError("unsafe_foundation_ancestor")

    @staticmethod
    def _lstat_kind(path: Path, directory: bool) -> str | None:
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode):
            return "symlink"
        if info.st_uid != os.getuid():
            return "wrong_owner"
        if directory and not stat.S_ISDIR(info.st_mode):
            return "not_directory"
        if not directory and not stat.S_ISREG(info.st_mode):
            return "not_regular"
        expected = 0o700 if directory else 0o600
        if stat.S_IMODE(info.st_mode) != expected:
            return "unsafe_permissions"
        return "ok"

    @staticmethod
    def _write_all(fd: int, payload: bytes) -> None:
        offset = 0
        while offset < len(payload):
            count = os.write(fd, payload[offset:])
            if count <= 0:
                raise OSError("short_foundation_write")
            offset += count

    def _open_checked_directory(self, directory: Path, *, create: bool = False) -> int:
        """Open `directory` from the configured trusted anchor, componentwise."""
        anchor = self.config.allowed_root
        if anchor is None:
            # Programmatic configs may name a nested not-yet-created data
            # root.  Anchor only at the nearest *existing* safe ancestor;
            # never fall back to /, HOME, or a writable broad directory.
            anchor = self.data_root.parent
            while not anchor.exists():
                anchor = anchor.parent
            if anchor in {Path('/'), Path.home()}:
                raise OSError("unsafe_foundation_anchor")
        try:
            relative = directory.relative_to(anchor)
        except ValueError as exc:
            raise OSError("foundation_directory_outside_anchor") from exc
        def acceptable(info: os.stat_result, location: Path) -> bool:
            strict = location == self.data_root or self.data_root in location.parents
            return (stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                    and info.st_uid == os.getuid()
                    and (stat.S_IMODE(info.st_mode) == 0o700 if strict else not (stat.S_IMODE(info.st_mode) & 0o022)))
        before = anchor.lstat()
        if not acceptable(before, anchor):
            raise OSError("unsafe_foundation_directory")
        fd = os.open(anchor, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino): raise OSError("foundation_directory_replaced")
            current = anchor
            for part in relative.parts:
                # `current` is lexical only; fd is the actual security anchor.
                current = current / part
                try:
                    named = os.stat(part, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    if not create or (self.config.allowed_root is not None and not (current == self.data_root or self.data_root in current.parents)): raise OSError("foundation_directory_missing")
                    os.mkdir(part, 0o700, dir_fd=fd)
                    named = os.stat(part, dir_fd=fd, follow_symlinks=False)
                child = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
                child_info = os.fstat(child)
                if not (acceptable(child_info, current) and (child_info.st_dev, child_info.st_ino) == (named.st_dev, named.st_ino)):
                    os.close(child); raise OSError("unsafe_foundation_directory")
                os.close(fd); fd = child
            return fd
        except Exception:
            os.close(fd)
            raise

    def _fsync_directory(self, directory: Path) -> None:
        fd = self._open_checked_directory(directory)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _secure_read_file(self, path: Path, limit: int = 8192) -> bytes:
        parent_fd = self._open_checked_directory(path.parent)
        fd = -1
        try:
            try: before = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError: raise OSError("foundation_file_missing")
            if not (stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and stat.S_IMODE(before.st_mode) == 0o600): raise OSError("unsafe_foundation_file")
            fd = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)

            opened = os.fstat(fd)
            if opened.st_ino != before.st_ino or opened.st_dev != before.st_dev or opened.st_uid != os.getuid() or stat.S_IMODE(opened.st_mode) != 0o600:
                raise OSError("foundation_file_replaced")
            data = b""
            while len(data) <= limit:
                part = os.read(fd, min(4096, limit + 1 - len(data)))
                if not part:
                    break
                data += part
            if len(data) > limit:
                raise OSError("foundation_file_too_large")
            after = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino): raise OSError("foundation_file_replaced")
            return data
        finally:
            if fd >= 0: os.close(fd)
            os.close(parent_fd)

    def _ensure_dir_chain(self, base: Path, target: Path) -> None:
        """Create only direct components, never traversing a symlink."""
        try:
            relative = target.relative_to(base)
        except ValueError as exc:
            raise ValueError("foundation_directory_outside_base") from exc
        fd = self._open_checked_directory(base, create=True)
        try:
            for part in relative.parts:
                try:
                    child = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
                except FileNotFoundError:
                    os.mkdir(part, 0o700, dir_fd=fd)
                    child = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
                info = os.fstat(child)
                named = os.stat(part, dir_fd=fd, follow_symlinks=False)
                if not (stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700 and (info.st_dev,info.st_ino)==(named.st_dev,named.st_ino)):
                    os.close(child); raise ValueError("unsafe_foundation_directory")
                os.close(fd); fd = child
        finally:
            os.close(fd)

    def _raw_directory_paths(self, paths: dict[str, Path]) -> tuple[Path, ...]:
        raw = paths["raw"]
        return (raw, raw / "garmin", raw / "garmin" / "fit", raw / "garmin" / "json", raw / "gmail", raw / "gmail" / "json", raw / "gmail" / "attachments", raw / "legacy", raw / "legacy" / "health_xlsx", raw / "legacy" / "fit")

    def _read_lock_at(self, parent_fd: int, name: str) -> tuple[dict[str, Any], tuple[int, int], bytes]:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not (stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and stat.S_IMODE(before.st_mode) == 0o600): raise BlockingIOError("foundation_lock_busy")
        fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        try:
            opened=os.fstat(fd); raw=b""
            if not (stat.S_ISREG(opened.st_mode) and opened.st_uid == os.getuid() and stat.S_IMODE(opened.st_mode) == 0o600): raise BlockingIOError("foundation_lock_busy")
            while len(raw)<=512:
                part=os.read(fd, min(513-len(raw), 512))
                if not part: break
                raw += part
        finally: os.close(fd)
        after=os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        ident=(before.st_dev,before.st_ino)
        if len(raw)>512 or (opened.st_dev,opened.st_ino)!=ident or (after.st_dev,after.st_ino)!=ident: raise BlockingIOError("foundation_lock_busy")
        try: payload=json.loads(raw.decode("utf-8"))
        except Exception as exc: raise BlockingIOError("foundation_lock_busy") from exc
        if set(payload)!={"pid","started_at_utc","uid"} or payload.get("uid")!=os.getuid() or not isinstance(payload.get("pid"),int) or payload["pid"]<=0 or not isinstance(payload.get("started_at_utc"),str) or _UTC_RFC3339_RE.fullmatch(payload["started_at_utc"]) is None: raise BlockingIOError("foundation_lock_busy")
        return payload,ident,raw

    def _claim_lock_at(self, parent_fd:int,name:str,identity:tuple[int,int],raw:bytes,kind:str)->str:
        claim=f".{name}.claim-{kind}-{secrets.token_hex(16)}"
        os.rename(name,claim,src_dir_fd=parent_fd,dst_dir_fd=parent_fd)
        try:
            _,actual,actual_raw=self._read_lock_at(parent_fd,claim)
            if actual!=identity or actual_raw!=raw: raise BlockingIOError("foundation_lock_replaced")
            return claim
        except Exception:
            # Never delete an unproven claim.  Restore only if canonical name
            # remains absent; otherwise leave forensic quarantine in place.
            try:
                os.link(claim,name,src_dir_fd=parent_fd,dst_dir_fd=parent_fd,follow_symlinks=False)
                os.fsync(parent_fd)
            except OSError: pass
            raise BlockingIOError("foundation_lock_busy")

    def _delete_owned_claim_at(self,parent_fd:int,claim:str,identity:tuple[int,int],raw:bytes)->None:
        _,actual,seen=self._read_lock_at(parent_fd,claim)
        if actual != identity or seen != raw: raise BlockingIOError("foundation_lock_replaced")
        os.unlink(claim,dir_fd=parent_fd); os.fsync(parent_fd)

    @staticmethod
    def _claim_created_inode_at(parent_fd:int,name:str,identity:tuple[int,int])->str:
        claim=f".{name}.claim-create-failed-{secrets.token_hex(16)}"
        os.rename(name,claim,src_dir_fd=parent_fd,dst_dir_fd=parent_fd)
        info=os.stat(claim,dir_fd=parent_fd,follow_symlinks=False)
        if not (stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)==0o600 and (info.st_dev,info.st_ino)==identity):
            # The canonical entry belonged to another writer.  Restore a
            # create-only hardlink so every later acquire remains blocked;
            # never overwrite a third writer which recreated canonical.
            try:
                os.link(claim,name,src_dir_fd=parent_fd,dst_dir_fd=parent_fd,follow_symlinks=False)
                os.fsync(parent_fd)
            except OSError:
                pass
            raise BlockingIOError("foundation_lock_replaced")
        return claim

    def _append_lock_audit(self, paths: dict[str, Path]) -> None:
        state_fd = self._open_checked_directory(paths["state"]); audit_fd=-1; name="foundation-lock-recoveries.jsonl"
        try:
            try: before=os.stat(name,dir_fd=state_fd,follow_symlinks=False)
            except FileNotFoundError: before=None
            if before and not (stat.S_ISREG(before.st_mode) and before.st_uid==os.getuid() and stat.S_IMODE(before.st_mode)==0o600): raise BlockingIOError("foundation_lock_busy")
            audit_fd=os.open(name,os.O_CREAT|os.O_APPEND|os.O_WRONLY|getattr(os,"O_NOFOLLOW",0),0o600,dir_fd=state_fd)
            opened=os.fstat(audit_fd); after=os.stat(name,dir_fd=state_fd,follow_symlinks=False)
            if not (stat.S_ISREG(opened.st_mode) and opened.st_uid==os.getuid() and stat.S_IMODE(opened.st_mode)==0o600 and (opened.st_dev,opened.st_ino)==(after.st_dev,after.st_ino) and (before is None or (before.st_dev,before.st_ino)==(opened.st_dev,opened.st_ino))): raise BlockingIOError("foundation_lock_busy")
            self._write_all(audit_fd,json.dumps({"recovered_at_utc":_utc(),"event":"stale_lock_recovered"},sort_keys=True).encode()+b"\n"); os.fsync(audit_fd); os.fsync(state_fd)
        finally:
            if audit_fd>=0: os.close(audit_fd)
            os.close(state_fd)

    @staticmethod
    def _has_unresolved_lock_claim_at(parent_fd: int, name: str) -> bool:
        prefix = f".{name}.claim-"
        try:
            entries = os.listdir(parent_fd)
        except OSError as exc:
            raise BlockingIOError("foundation_lock_busy") from exc
        # Exact prefix plus a nonempty suffix prevents unrelated dotfiles from
        # becoming a false lock while retaining every failed recovery claim.
        return any(entry.startswith(prefix) and len(entry) > len(prefix) for entry in entries)

    @contextmanager
    def _lock(self, root: Path):
        paths = self._paths(root)
        try:
            self._ensure_dir_chain(root.parent, paths["lock"].parent)
        except ValueError as exc:
            raise BlockingIOError("foundation_lock_busy") from exc
        parent_fd = self._open_checked_directory(paths["lock"].parent)
        name = paths["lock"].name
        if self._has_unresolved_lock_claim_at(parent_fd, name):
            os.close(parent_fd)
            raise BlockingIOError("foundation_lock_busy")
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(name, flags, 0o600, dir_fd=parent_fd)
        except FileExistsError as exc:
            try:
                payload,identity,data = self._read_lock_at(parent_fd,name); datetime.fromisoformat(payload["started_at_utc"][:-1] + "+00:00")
                try:
                    os.kill(payload["pid"], 0)
                except ProcessLookupError:
                    claimed=self._claim_lock_at(parent_fd,name,identity,data,"stale")
                    self._append_lock_audit(paths)
                    self._delete_owned_claim_at(parent_fd,claimed,identity,data)
                    with self._lock(root):
                        yield
                    return
                raise BlockingIOError("foundation_lock_busy")
            except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError, BlockingIOError) as error:
                raise BlockingIOError("foundation_lock_busy") from error
            finally:
                os.close(parent_fd)
        inode: tuple[int, int] | None = None
        record = json.dumps({"pid": os.getpid(), "started_at_utc": _utc(), "uid": os.getuid()}, sort_keys=True).encode()
        try:
            opened = os.fstat(fd)
            if not (stat.S_ISREG(opened.st_mode) and opened.st_uid == os.getuid() and stat.S_IMODE(opened.st_mode) == 0o600):
                raise OSError("foundation_lock_create_unsafe")
            inode = (opened.st_dev, opened.st_ino)
            self._write_all(fd, record)
            os.fsync(fd)
            os.fsync(parent_fd)
            _,verified,seen=self._read_lock_at(parent_fd,name)
            if verified != inode or seen != record: raise BlockingIOError("foundation_lock_replaced")
        except Exception as exc:
            try:
                os.close(fd)
            except OSError: pass
            try:
                if inode is not None:
                    claim=self._claim_created_inode_at(parent_fd,name,inode)
                    os.unlink(claim,dir_fd=parent_fd); os.fsync(parent_fd)
            except Exception as cleanup:
                os.close(parent_fd)
                raise BlockingIOError("foundation_lock_replaced") from cleanup
            os.close(parent_fd)
            raise BlockingIOError("foundation_lock_create_failed") from exc
        try:
            yield
        finally:
            os.close(fd)
            try:
                _,identity,raw=self._read_lock_at(parent_fd,name)
                if identity != inode or raw != record: raise BlockingIOError("foundation_lock_replaced")
                released=self._claim_lock_at(parent_fd,name,inode,record,"release")
                self._delete_owned_claim_at(parent_fd,released,inode,record)
            finally:
                os.close(parent_fd)

    def _connect(self, path: Path, *, readonly: bool = False) -> sqlite3.Connection:
        # Never hand SQLite an unchecked pathname.  `/dev/fd/N` names the
        # already O_NOFOLLOW-opened inode; name rechecks fail closed if an
        # attacker swaps the directory entry around the open.
        parent_fd = self._open_checked_directory(path.parent); fd=-1; conn: _PinnedConnection | None=None; name=path.name
        cleanup_prefix=f".{name}.create-cleanup-"; intent_prefix=f".{name}.create-intent-"
        snapshot_prefix=".foundation-readonly-"
        try:
            if any((entry.startswith(cleanup_prefix) or entry.startswith(intent_prefix) or entry.startswith(snapshot_prefix)) for entry in os.listdir(parent_fd)):
                os.close(parent_fd); raise IncompatibleError("sqlite_create_cleanup_blocker")
        except OSError as exc:
            os.close(parent_fd); raise IncompatibleError("sqlite_create_cleanup_scan_failed") from exc
        def checked_stat(item: str) -> os.stat_result:
            value=os.stat(item,dir_fd=parent_fd,follow_symlinks=False)
            if not (stat.S_ISREG(value.st_mode) and value.st_uid==os.getuid() and stat.S_IMODE(value.st_mode)==0o600): raise IncompatibleError("sqlite_path_unsafe")
            return value
        def copy_to_snapshot(source_fd: int, destination_fd: int) -> None:
            os.lseek(source_fd, 0, os.SEEK_SET)
            while True:
                block=os.read(source_fd, 1024 * 1024)
                if not block:
                    return
                offset=0
                while offset < len(block):
                    written=os.write(destination_fd,block[offset:])
                    if written <= 0:
                        raise OSError("foundation_snapshot_short_write")
                    offset += written
        def _digest_fd(source_fd: int) -> tuple[bytes, int]:
            os.lseek(source_fd,0,os.SEEK_SET); digest=hashlib.sha256(); total=0
            while True:
                block=os.read(source_fd,1024*1024)
                if not block: return digest.digest(), total
                digest.update(block); total += len(block)
        def _strict_source(source_name: str, source_fd: int | None = None) -> tuple[int, tuple[int,int,int,int,int,bytes]]:
            """Bind an opened source fd to a stable name and full evidence."""
            pre=checked_stat(source_name)
            owned=False
            if source_fd is None:
                source_fd=os.open(source_name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0),dir_fd=parent_fd); owned=True
            opened=os.fstat(source_fd); post=checked_stat(source_name)
            if not (stat.S_ISREG(opened.st_mode) and opened.st_uid==os.getuid() and stat.S_IMODE(opened.st_mode)==0o600):
                if owned: os.close(source_fd)
                raise IncompatibleError("sqlite_wal_state_unsafe")
            if (pre.st_dev,pre.st_ino)!=(opened.st_dev,opened.st_ino) or (post.st_dev,post.st_ino)!=(opened.st_dev,opened.st_ino):
                if owned: os.close(source_fd)
                raise IncompatibleError("sqlite_wal_state_unsafe")
            digest,size=_digest_fd(source_fd)
            return source_fd,(opened.st_dev,opened.st_ino,size,opened.st_mtime_ns,opened.st_ctime_ns,digest)
        def _snapshot_children(snapshot_fd: int) -> dict[str,tuple[int,int]]:
            values: dict[str,tuple[int,int]]={}
            for child in os.listdir(snapshot_fd):
                info=os.stat(child,dir_fd=snapshot_fd,follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode): raise IncompatibleError("sqlite_snapshot_unsafe")
                values[child]=(info.st_dev,info.st_ino)
            return values
        def _discard_snapshot(snapshot_name: str, snapshot_fd: int, expected: dict[str,tuple[int,int]]) -> bool:
            """Remove only expected inodes; otherwise retain a blocker."""
            try:
                for child, identity in expected.items():
                    claim=f".foundation-snapshot-cleanup-{secrets.token_hex(16)}"
                    os.rename(child,claim,src_dir_fd=snapshot_fd,dst_dir_fd=snapshot_fd)
                    info=os.stat(claim,dir_fd=snapshot_fd,follow_symlinks=False)
                    if not(stat.S_ISREG(info.st_mode) and (info.st_dev,info.st_ino)==identity):
                        try: os.rename(claim,child,src_dir_fd=snapshot_fd,dst_dir_fd=snapshot_fd)
                        except OSError: pass
                        return False
                    os.unlink(claim,dir_fd=snapshot_fd)
                if os.listdir(snapshot_fd): return False
                os.close(snapshot_fd); snapshot_fd=-1
                os.rmdir(snapshot_name,dir_fd=parent_fd); os.fsync(parent_fd)
                return True
            except Exception:
                return False
            finally:
                if snapshot_fd>=0:
                    try: os.close(snapshot_fd)
                    except OSError: pass
        def make_wal_snapshot() -> tuple[str, Path, dict[str,tuple[int,int]], dict[str,tuple[int,int,int,int,int,bytes]]]:
            """Create a stable, source-zero-write read-only WAL snapshot."""
            snapshot_name=f".foundation-readonly-{secrets.token_hex(16)}"; snapshot_fd=-1; sources: list[int]=[]
            source_evidence: dict[str,tuple[int,int,int,int,int,bytes]]={}
            try:
                os.mkdir(snapshot_name,0o700,dir_fd=parent_fd); os.fsync(parent_fd)
                snapshot_fd=os.open(snapshot_name,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0),dir_fd=parent_fd)
                # Copy all three source members under a fixed evidence window.
                # The SHM copy is snapshot-local; it is never opened writable
                # at the source path.
                for source_name, source_fd in ((name,fd),(name+"-wal",None),(name+"-shm",None)):
                    actual_fd,evidence=_strict_source(source_name,source_fd); sources.append(actual_fd) if source_fd is None else None
                    source_evidence[source_name]=evidence
                    if source_name == name+"-wal":
                        os.lseek(actual_fd,0,os.SEEK_SET); header=os.read(actual_fd,32)
                        if len(header)!=32 or header[:4] not in {b"7\x7f\x06\x82",b"7\x7f\x06\x83"}:
                            raise IncompatibleError("sqlite_wal_state_unsafe")
                    destination=os.open(source_name,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,"O_NOFOLLOW",0),0o600,dir_fd=snapshot_fd)
                    try:
                        os.fchmod(destination,0o600); copy_to_snapshot(actual_fd,destination); os.fsync(destination)
                    finally: os.close(destination)
                os.fsync(snapshot_fd)
                # Repeat full descriptor/name evidence after the copy.  This
                # catches checkpoint/commit and same-size in-place mutation,
                # not merely a final WAL inode/size change.
                for source_name, source_fd in ((name,fd),(name+"-wal",None),(name+"-shm",None)):
                    actual_fd=source_fd
                    if actual_fd is None:
                        actual_fd=next(item for item in sources if (os.fstat(item).st_dev,os.fstat(item).st_ino)==source_evidence[source_name][:2])
                    _,evidence=_strict_source(source_name,actual_fd)
                    if evidence != source_evidence[source_name]: raise IncompatibleError("sqlite_wal_state_unsafe")
                children=_snapshot_children(snapshot_fd)
                os.close(snapshot_fd); snapshot_fd=-1
                return snapshot_name,path.parent/snapshot_name/name,children,source_evidence
            except Exception:
                if snapshot_fd>=0:
                    try:
                        expected=_snapshot_children(snapshot_fd)
                    except Exception:
                        # The directory may already be hostile.  Preserve it
                        # as the prefix-scanned fail-closed blocker, but never
                        # leak its descriptor.
                        os.close(snapshot_fd); snapshot_fd=-1
                    else:
                        _discard_snapshot(snapshot_name,snapshot_fd,expected); snapshot_fd=-1
                raise
            finally:
                for source_fd in sources:
                    try: os.close(source_fd)
                    except OSError: pass
        snapshot_name: str | None = None
        snapshot_children: dict[str,tuple[int,int]] | None = None
        snapshot_evidence: dict[str,tuple[int,int,int,int,int,bytes]] | None = None
        try:
            try: before=checked_stat(name)
            except FileNotFoundError:
                if readonly: raise IncompatibleError("sqlite_path_unsafe")
                created: tuple[int,int] | None=None
                created_raw: bytes | None=None
                created_name_owned=False; parent_persisted=False
                intent: str | None=None
                try:
                    fd=os.open(name,os.O_CREAT|os.O_EXCL|os.O_RDWR|getattr(os,"O_NOFOLLOW",0),0o600,dir_fd=parent_fd)
                    created_name_owned=True
                    intent=intent_prefix+secrets.token_hex(16)
                    os.link(name,intent,src_dir_fd=parent_fd,dst_dir_fd=parent_fd,follow_symlinks=False); os.fsync(parent_fd)
                    info=os.fstat(fd); created=(info.st_dev,info.st_ino)
                    os.lseek(fd,0,os.SEEK_SET); created_raw=os.read(fd,1024)
                    if created_raw != b"" or os.fstat(fd).st_size != 0: raise IncompatibleError("sqlite_create_initial_content_unsafe")
                    os.fchmod(fd,0o600); os.fsync(fd); os.fsync(parent_fd); parent_persisted=True; before=checked_stat(name); os.close(fd); fd=-1
                except Exception as exc:
                    if fd>=0: os.close(fd); fd=-1
                    if created_name_owned:
                        claim=cleanup_prefix+secrets.token_hex(16)
                        try:
                            os.rename(name,claim,src_dir_fd=parent_fd,dst_dir_fd=parent_fd)
                            if created is None or created_raw is None or not parent_persisted:
                                # Cannot prove bytes or durable publication:
                                # retain the claim as the fail-closed record.
                                raise IncompatibleError("sqlite_create_cleanup_blocker")
                            claim_info=os.stat(claim,dir_fd=parent_fd,follow_symlinks=False)
                            cfd=os.open(claim,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0),dir_fd=parent_fd)
                            try:
                                opened=os.fstat(cfd); raw=os.read(cfd,1025); after=os.stat(claim,dir_fd=parent_fd,follow_symlinks=False)
                            finally: os.close(cfd)
                            if not(stat.S_ISREG(claim_info.st_mode) and claim_info.st_uid==os.getuid() and stat.S_IMODE(claim_info.st_mode)==0o600 and (claim_info.st_dev,claim_info.st_ino)==created and (opened.st_dev,opened.st_ino)==created and (after.st_dev,after.st_ino)==created and raw==created_raw and claim_info.st_size==len(created_raw)): raise IncompatibleError("sqlite_create_replaced")
                            os.unlink(claim,dir_fd=parent_fd); os.fsync(parent_fd)
                        except Exception as cleanup:
                            raise IncompatibleError("sqlite_create_cleanup_blocker") from cleanup
                    raise IncompatibleError("sqlite_create_failed") from exc
                # Creation is now durably complete; only remove the intent
                # after all checks above have passed.
                completion=intent_prefix+"complete-"+secrets.token_hex(16)
                os.rename(intent,completion,src_dir_fd=parent_fd,dst_dir_fd=parent_fd)
                # If this fsync fails, completion remains a persistent
                # blocker; it is removed only after durability is known.
                os.fsync(parent_fd)
                os.unlink(completion,dir_fd=parent_fd)
                try:
                    os.fsync(parent_fd)
                except OSError as exc:
                    # The unlink may not be durable; recreate a visible
                    # blocker from canonical before surfacing the failure.
                    blocker=intent_prefix+"post-fsync-"+secrets.token_hex(16)
                    try:
                        os.link(name,blocker,src_dir_fd=parent_fd,dst_dir_fd=parent_fd,follow_symlinks=False)
                    except OSError:
                        try:
                            os.rename(name,blocker,src_dir_fd=parent_fd,dst_dir_fd=parent_fd)
                        except OSError as fallback:
                            raise IncompatibleError("sqlite_create_cleanup_blocker") from fallback
                    raise IncompatibleError("sqlite_create_cleanup_blocker") from exc
            flags=(os.O_RDONLY if readonly else os.O_RDWR)|getattr(os,"O_NOFOLLOW",0)
            fd=os.open(name,flags,dir_fd=parent_fd); opened=os.fstat(fd); after=checked_stat(name)
            identity=(before.st_dev,before.st_ino)
            if (opened.st_dev,opened.st_ino)!=identity or (after.st_dev,after.st_ino)!=identity: raise IncompatibleError("sqlite_path_replaced")
            # SQLite on macOS cannot create its rollback journal through an
            # already-open `/dev/fd` descriptor.  Read-only routes remain
            # descriptor-bound; maintenance routes keep the checked fd open
            # and recheck the canonical name immediately around SQLite open.
            if readonly:
                # immutable=1 intentionally ignores WAL.  A committed crash
                # or uncheckpointed WAL must instead be read through SQLite's
                # canonical read-only path so no accepted data disappears.
                wal_identity: tuple[int,int,int] | None = None
                try:
                    wal=checked_stat(name+"-wal"); wal_nonempty=wal.st_size>0
                    if wal_nonempty: wal_identity=(wal.st_dev,wal.st_ino,wal.st_size)
                except FileNotFoundError: wal_nonempty=False
                if wal_nonempty:
                    snapshot_name, snapshot_path, snapshot_children, snapshot_evidence=make_wal_snapshot()
                    target=f"file:{snapshot_path}?mode=ro"
                else:
                    target=f"file:/dev/fd/{fd}?mode=ro&immutable=1"
                conn = sqlite3.connect(target, isolation_level=None, uri=True, factory=_PinnedConnection)
            else:
                conn = sqlite3.connect(str(path), isolation_level=None, factory=_PinnedConnection)
            # From this point every failure is unwound through the connection,
            # which owns both descriptors.  Do this before any post-connect
            # namespace/PRAGMA check: a canonical-name race must not leak the
            # parent or database fd merely because SQLite did open first.
            conn._foundation_fd = fd
            conn._foundation_parent_fd = parent_fd
            if readonly and 'snapshot_name' in locals() and snapshot_name is not None:
                conn._foundation_snapshot_name = snapshot_name
                conn._foundation_snapshot_children = snapshot_children
            fd = -1
            if not readonly:
                try: final=checked_stat(name)
                except FileNotFoundError as exc: raise IncompatibleError("sqlite_path_replaced") from exc
                if (final.st_dev,final.st_ino)!=identity:
                    raise IncompatibleError("sqlite_path_replaced")
            try: post=checked_stat(name)
            except FileNotFoundError as exc: raise IncompatibleError("sqlite_path_replaced") from exc
            if (post.st_dev,post.st_ino)!=identity: raise IncompatibleError("sqlite_path_replaced")
            # `database_list` is part of the pathname binding, not diagnostic
            # metadata.  Reject malformed rows and attachments rather than
            # accepting a convenient first ``main`` row from an altered
            # connection object.
            try:
                database_list = conn.execute("PRAGMA database_list").fetchall()
            except Exception as exc:
                raise IncompatibleError("sqlite_database_list_unsafe") from exc
            if not isinstance(database_list, (list, tuple)):
                raise IncompatibleError("sqlite_database_list_unsafe")
            mains: list[str] = []
            for row in database_list:
                if not isinstance(row, (tuple, list)) or len(row) != 3:
                    raise IncompatibleError("sqlite_database_list_unsafe")
                sequence, database_name, database_file = row
                if not isinstance(sequence, int) or not isinstance(database_name, str) or not isinstance(database_file, str):
                    raise IncompatibleError("sqlite_database_list_unsafe")
                # Foundation opens exactly one database.  An attached database
                # could otherwise make a forged/aliased metadata result look
                # acceptable, so it is incompatible with this primitive.
                if database_name != "main":
                    raise IncompatibleError("sqlite_database_list_unsafe")
                mains.append(database_file)
            main=mains[0] if len(mains)==1 else None
            if readonly and 'wal_nonempty' in locals() and wal_nonempty:
                expected_main = snapshot_path.resolve()
            elif readonly:
                expected_main = Path(f"/dev/fd/{conn._foundation_fd}").resolve()
            else:
                expected_main = path.resolve()
            if not isinstance(main,str) or not main or not Path(main).is_absolute() or Path(main).resolve() != expected_main: raise IncompatibleError("sqlite_database_list_unsafe")
            if readonly and 'wal_identity' in locals() and wal_identity is not None:
                try: after_wal=checked_stat(name+"-wal")
                except (FileNotFoundError, IncompatibleError) as exc: raise IncompatibleError("sqlite_wal_state_unsafe") from exc
                if (after_wal.st_dev,after_wal.st_ino,after_wal.st_size)!=wal_identity: raise IncompatibleError("sqlite_wal_state_unsafe")
                # A source commit/checkpoint can retain an inode and size.
                # Recompute full fd-bound evidence after SQLite has opened the
                # snapshot, and reject any mixed source window.
                assert snapshot_evidence is not None
                for source_name, expected in snapshot_evidence.items():
                    source_fd=-1
                    try:
                        source_fd, observed=_strict_source(source_name)
                        if observed != expected: raise IncompatibleError("sqlite_wal_state_unsafe")
                    finally:
                        if source_fd >= 0: os.close(source_fd)
            conn.row_factory = sqlite3.Row; conn.execute("PRAGMA foreign_keys=ON")
            if readonly and snapshot_name is not None:
                try:
                    integrity=conn.execute("PRAGMA integrity_check").fetchone()
                except Exception as exc:
                    raise IncompatibleError("sqlite_snapshot_integrity_unsafe") from exc
                if integrity is None or len(integrity)!=1 or integrity[0] != "ok":
                    raise IncompatibleError("sqlite_snapshot_integrity_unsafe")
            if not readonly: conn.execute("PRAGMA journal_mode=WAL"); conn.execute("PRAGMA busy_timeout=10000")
            return conn
        except Exception:
            if conn is not None:
                try: conn.close()
                except Exception: pass
            else:
                if snapshot_name is not None and snapshot_children is not None:
                    snapshot_fd=-1
                    try:
                        snapshot_fd=os.open(snapshot_name,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0),dir_fd=parent_fd)
                        _discard_snapshot(snapshot_name,snapshot_fd,snapshot_children); snapshot_fd=-1
                    except Exception:
                        if snapshot_fd>=0:
                            try: os.close(snapshot_fd)
                            except OSError: pass
                if fd>=0: os.close(fd)
                os.close(parent_fd)
            raise

    @staticmethod
    def _manifest_path() -> Path:
        return Path(__file__).resolve().parents[3] / "harness" / "schemas" / "foundation_schema_manifest.json"

    def _manifest(self) -> dict[str, Any]:
        return json.loads(self._manifest_path().read_text(encoding="utf-8"))

    def _manifest_hash(self) -> str:
        # The marker and migration bind the database to the reviewed static
        # manifest, not to Python dict ordering or the implementation source.
        canonical = json.dumps(self._manifest(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _required_relative_raw() -> tuple[str, ...]:
        return ("garmin/fit", "garmin/json", "gmail/json", "gmail/attachments", "legacy/health_xlsx", "legacy/fit")

    def _required_objects_and_permissions(self, paths: dict[str, Path]) -> list[str]:
        required = [paths["root"], *self._raw_directory_paths(paths), paths["state"], paths["lock"].parent, paths["db"], paths["ready"]]
        errors: list[str] = []
        for path in required:
            directory = path == paths["root"] or path in self._raw_directory_paths(paths) or path in {paths["state"], paths["lock"].parent}
            kind = self._lstat_kind(path, directory)
            if kind is None:
                errors.append(f"missing:{path.name}")
                continue
            if kind != "ok":
                errors.append(f"{kind}:{path.name}")
        return errors

    def _marker_error(self, paths: dict[str, Path], expected_hash: str) -> str | None:
        if self._lstat_kind(paths["ready"], False) != "ok":
            return "marker_unsafe_or_missing"
        try:
            marker = json.loads(self._secure_read_file(paths["ready"]).decode("utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return "marker_missing_or_invalid"
        if not isinstance(marker,dict) or set(marker) != {"schema_version","manifest_sha256","ready","initialized_at_utc"}:
            return "marker_shape_mismatch"
        if marker.get("ready") is not True:
            return "marker_not_ready"
        if marker.get("schema_version") != FOUNDATION_SCHEMA_VERSION:
            return "marker_schema_version_mismatch"
        if marker.get("manifest_sha256") != expected_hash:
            return "marker_manifest_mismatch"
        if not _canonical_utc(marker.get("initialized_at_utc")):
            return "marker_timestamp_mismatch"
        return None

    @staticmethod
    def _migration_receipt_valid(conn: sqlite3.Connection, manifest_hash: str) -> bool:
        rows=[tuple(row) for row in conn.execute("SELECT version,description,applied_at_utc,code_revision,content_sha256 FROM schema_migrations ORDER BY version")]
        if len(rows)!=3: return False
        expected=(
            (1,"foundation_v1","foundation-v1",{_FOUNDATION_V1_MIGRATION_SHA256,LEGACY_V1_MANIFEST_SHA256}),
            (2,"mail_processing_state_v2","foundation-v2",{LEGACY_V2_MANIFEST_SHA256}),
            (3,"analysis_input_trust_v3","foundation-v3",{manifest_hash}),
        )
        for row, wanted in zip(rows,expected):
            version,description,applied,revision,content=row
            expected_version,expected_description,expected_revision,expected_contents=wanted
            if (version,description,revision) != (expected_version,expected_description,expected_revision) or content not in expected_contents or not _canonical_utc(applied):
                return False
        return True

    def _read_foundation_state(self, conn: sqlite3.Connection) -> sqlite3.Row:
        try:
            state = conn.execute("SELECT state,schema_version,manifest_sha256,initialized_at_utc,updated_at_utc,implementation_version FROM foundation_state WHERE id=1").fetchone()
        except sqlite3.DatabaseError as exc:
            if "no such table" in str(exc).lower():
                raise IncompatibleError("foundation_state_missing") from exc
            raise CorruptFoundationError("cannot_read_foundation_state") from exc
        if state is None:
            raise IncompatibleError("foundation_state_missing")
        return state

    def _read_status(self, root: Path, receipt: FoundationReceipt) -> None:
        """Read the bounded published-readiness summary without opening SQLite.

        ``status`` is used on every ordinary consumer invocation.  Its frozen
        contract is therefore deliberately limited to the owner-controlled
        ready marker, supported schema version, and fixed path permissions.
        Page, relational, migration-receipt, and complete manifest checks
        belong to the explicit ``verify`` maintenance path.
        """
        read_published_status(
            self,
            root,
            receipt,
            supported_schema_version=FOUNDATION_SCHEMA_VERSION,
            canonical_utc=_canonical_utc,
        )

    def _read_verification(
        self, root: Path, receipt: FoundationReceipt
    ) -> None:
        """Run the complete, explicit Foundation compatibility verification."""
        read_full_verification(
            self,
            root,
            receipt,
            supported_schema_version=FOUNDATION_SCHEMA_VERSION,
            canonical_utc=_canonical_utc,
            validate_manifest=validate_schema_manifest,
            incompatible_error=IncompatibleError,
            corrupt_error=CorruptFoundationError,
        )

    def _verify(self, root: Path, receipt: FoundationReceipt) -> None:
        verify_foundation(
            self,
            root,
            receipt,
            supported_schema_version=FOUNDATION_SCHEMA_VERSION,
            verified_object_count=len(TABLES) + len(VIEWS) + 1,
            canonical_utc=_canonical_utc,
            validate_manifest=validate_schema_manifest,
            incompatible_error=IncompatibleError,
            corrupt_error=CorruptFoundationError,
        )

    def _init(self, root: Path, receipt: FoundationReceipt) -> None:
        paths = self._paths(root)
        # A compatible ready database is the common bootstrap path. Its
        # preflight is read-only and lock-free, but deliberately performs the
        # complete verification before a long-running Supervisor starts.
        if paths["db"].exists():
            self._verify(root, receipt)
            if any(
                warning.get("summary") == "marker_missing"
                for warning in receipt.warnings
            ):
                # A missing marker can be either an exact interrupted init
                # checkpoint or operator evidence from a previously ready
                # store.  Inspect the database deeply before deciding whether
                # acquiring the writer lock is permitted.
                receipt.warnings.clear()
                self._read_verification(root, receipt)
            if receipt.ready:
                receipt.status, receipt.next_action = "already_initialized", "none"
                return
            if self._lstat_kind(paths["db"], False) not in {None, "ok"}:
                return
            if receipt.status == "incompatible" and receipt.next_action == "explicit_migrate":
                # A ready, older schema is a maintenance concern.  Do not take
                # the writer lock or open SQLite read-write merely because a
                # normal bootstrap invoked init.
                return
            recoverable_summaries = {"database_not_ready", "marker_missing"}
            if (
                receipt.status == "incompatible"
                and receipt.next_action == "operator_review"
                and not any(
                    warning.get("summary") in recoverable_summaries
                    for warning in receipt.warnings
                )
            ):
                # Any inconsistent ready environment is operator evidence, not
                # an init recovery checkpoint. Preserve it without a writer lock.
                return
        with self._lock(root):
            # Re-check only after acquiring the single writer lock.  A second
            # initializer can therefore never run CREATE TABLE after the first
            # one has published a database or a recoverable initializing state.
            if paths["db"].exists():
                self._resume_or_reject_existing(paths, receipt)
                return
            # Phase 1: independently committed and intentionally observable.
            # It is never combined with the schema DDL transaction.
            self._ensure_dir_chain(root.parent, root)
            self._ensure_dir_chain(root, paths["raw"])
            for directory in self._raw_directory_paths(paths):
                self._ensure_dir_chain(root, directory)
            self._ensure_dir_chain(root, paths["state"])
            conn = self._connect(paths["db"])
            try:
                manifest_hash = self._manifest_hash()
                conn.execute(_PHASE1_DDL["foundation_state"])
                conn.execute(_PHASE1_DDL["schema_migrations"])
                conn.execute("INSERT INTO foundation_state VALUES(1,'initializing',?,?,?,?,?)", (FOUNDATION_SCHEMA_VERSION, manifest_hash, None, _utc(), "foundation-v1"))
                conn.commit()
            finally:
                conn.close()
            os.chmod(paths["db"], 0o600)
            self._fire_failpoint("before_schema")

            # Phase 2: all application objects and the migration receipt commit
            # together. A crash here leaves phase 1 recoverable only after exact
            # admissibility validation, followed by deterministic phase-2 resume.
            conn = self._connect(paths["db"])
            transaction_open = False
            try:
                conn.execute("BEGIN IMMEDIATE")
                transaction_open = True
                self._apply_phase2_schema(conn,manifest_hash,emit_failpoint=True)
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("sqlite_integrity_failed")
                conn.execute("COMMIT")
                transaction_open = False
            except Exception:
                if transaction_open:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()
            self._fire_failpoint("after_schema")

            # Do not publish readiness merely because DDL committed.  The
            # exact reviewed manifest, migration receipt and SQLite integrity
            # must all be readable before the marker can become visible.
            audit=self._connect(paths["db"],readonly=True)
            try:
                schema_errors=validate_schema_manifest(audit,self._manifest())
                if schema_errors or not self._migration_receipt_valid(audit,manifest_hash):
                    raise IncompatibleError("initial_schema_verification_failed")
                if audit.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise CorruptFoundationError("initial_sqlite_integrity_failed")
            finally:
                audit.close()

            # Phase 3: marker publication precedes the ready state transition.
            self._atomic_json(paths["ready"], {"schema_version": FOUNDATION_SCHEMA_VERSION, "manifest_sha256": manifest_hash, "ready": True, "initialized_at_utc": _utc()})
            self._fire_failpoint("after_marker")
            conn = self._connect(paths["db"])
            try:
                conn.execute("UPDATE foundation_state SET state='ready', initialized_at_utc=?, updated_at_utc=?, implementation_version='foundation-v3' WHERE id=1", (_utc(), _utc()))
            finally:
                conn.close()
            receipt.status, receipt.ready, receipt.next_action = "initialized", True, "none"
            receipt.foundation_schema_version = FOUNDATION_SCHEMA_VERSION
            receipt.created_count = len(TABLES) + len(VIEWS) + 10
            receipt.applied_migration_ids = [1, 2, 3]
            receipt.migration_start_version, receipt.migration_end_version = 0, FOUNDATION_SCHEMA_VERSION

    def _fire_failpoint(self, phase: str) -> None:
        if self.failpoint is not None:
            self.failpoint(phase)

    def _phase1_admissible(self, conn: sqlite3.Connection, paths: dict[str, Path], expected_hash: str) -> bool:
        """Recognise only our committed phase-1 checkpoint, never a lookalike."""
        row=conn.execute("SELECT id,state,schema_version,manifest_sha256,initialized_at_utc,updated_at_utc,implementation_version FROM foundation_state WHERE id=1").fetchone()
        if row is None or tuple(row[:5]) != (1,"initializing",FOUNDATION_SCHEMA_VERSION,expected_hash,None) or row[6] != "foundation-v1":
            return False
        updated=row[5]
        if not isinstance(updated,str) or _UTC_RFC3339_RE.fullmatch(updated) is None:
            return False
        try:
            if datetime.fromisoformat(updated[:-1]+"+00:00").isoformat().replace("+00:00","Z") != updated: return False
        except ValueError: return False
        entries=[tuple(item) for item in conn.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")]
        if {(kind,name) for kind,name,_ in entries} != {("table","foundation_state"),("table","schema_migrations")}:
            return False
        def canonical(sql: str | None) -> str:
            return "".join((sql or "").lower().split())
        actual={name:sql for kind,name,sql in entries if kind=="table"}
        if any(canonical(actual.get(name)) != canonical(ddl) for name,ddl in _PHASE1_DDL.items()):
            return False
        # Redundant PRAGMA checks make column affinity, NOT NULL, PK/default
        # drift explicit even if a future SQLite renderer changes whitespace.
        expected_columns={
            "foundation_state":[("id","INTEGER",0,1,None),("state","TEXT",1,0,None),("schema_version","INTEGER",1,0,None),("manifest_sha256","TEXT",1,0,None),("initialized_at_utc","TEXT",0,0,None),("updated_at_utc","TEXT",1,0,None),("implementation_version","TEXT",1,0,None)],
            "schema_migrations":[("version","INTEGER",0,1,None),("description","TEXT",1,0,None),("applied_at_utc","TEXT",1,0,None),("code_revision","TEXT",1,0,"'foundation-v1'"),("content_sha256","TEXT",1,0,None)],
        }
        for table, expected in expected_columns.items():
            rows=[(row[1],row[2],row[3],row[5],row[4]) for row in conn.execute(f"PRAGMA table_info({table})")]
            if rows != expected: return False
        if conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] != 0:
            return False
        if conn.execute("SELECT COUNT(*) FROM foundation_state").fetchone()[0] != 1:
            return False
        if self._lstat_kind(paths["ready"],False) is not None:
            return False
        required=self._required_objects_and_permissions(paths)
        return not [item for item in required if not item.endswith(paths["ready"].name)] and conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    def _apply_phase2_schema(self, conn: sqlite3.Connection, manifest_hash: str, *, emit_failpoint: bool) -> None:
        """The sole reviewed phase-2 DDL/migration builder for init and resume."""
        for ordinal,(name,columns) in enumerate(TABLES.items()):
            if name != "foundation_state": conn.execute(f"CREATE TABLE {name} ({columns})")
            if emit_failpoint and ordinal == 1: self._fire_failpoint("during_schema")
        for name,query in VIEWS.items(): conn.execute(f"CREATE VIEW {name} AS {query}")
        for statement in (
            "CREATE INDEX idx_source_revisions_current ON source_revisions(provider,resource_kind,provider_object_id,is_current)","CREATE UNIQUE INDEX ux_source_revision_current ON source_revisions(provider,resource_kind,provider_object_id) WHERE is_current=1","CREATE UNIQUE INDEX ux_activity_source_role_active ON activity_source_revisions(activity_id,source_role) WHERE is_active=1","CREATE UNIQUE INDEX ux_daily_health_current ON daily_health(subject_id,local_date) WHERE is_current=1","CREATE UNIQUE INDEX ux_analysis_artifact_current ON analysis_artifacts(subject_id,artifact_kind,period_start_local_date,period_end_local_date) WHERE is_current=1","CREATE UNIQUE INDEX ux_mail_response_current ON mail_response_artifacts(subject_id,mail_thread_id,response_kind) WHERE is_current=1","CREATE UNIQUE INDEX ux_garmin_sync_gap_unresolved ON garmin_sync_gaps(subject_id,resource_kind,logical_object_key,window_start_local_date,window_end_local_date,stage) WHERE status IN ('open','deferred')","CREATE INDEX idx_coverage_resource_date ON resource_coverage(resource_kind,local_date)","CREATE INDEX idx_activity_samples_stream ON activity_samples(activity_id,stream_kind,sample_index)",
            "CREATE TRIGGER trg_training_plan_item_window BEFORE INSERT ON training_plan_items FOR EACH ROW WHEN NEW.local_date < (SELECT plan_start_local_date FROM training_plans WHERE id=NEW.training_plan_id) OR NEW.local_date > (SELECT plan_end_local_date FROM training_plans WHERE id=NEW.training_plan_id) BEGIN SELECT RAISE(ABORT,'training_plan_item_outside_plan_window'); END","CREATE TRIGGER trg_training_plan_artifact_insert BEFORE INSERT ON training_plans FOR EACH ROW WHEN (SELECT artifact_kind FROM analysis_artifacts WHERE id=NEW.analysis_artifact_id) != 'weekly_training_plan' BEGIN SELECT RAISE(ABORT,'training_plan_requires_weekly_training_plan'); END","CREATE TRIGGER trg_training_plan_artifact_update BEFORE UPDATE OF analysis_artifact_id ON training_plans FOR EACH ROW WHEN (SELECT artifact_kind FROM analysis_artifacts WHERE id=NEW.analysis_artifact_id) != 'weekly_training_plan' BEGIN SELECT RAISE(ABORT,'training_plan_requires_weekly_training_plan'); END","CREATE TRIGGER trg_climbing_route_segment_insert BEFORE INSERT ON climbing_routes FOR EACH ROW WHEN (SELECT segment_type FROM activity_segments WHERE id=NEW.segment_id) != 'climb_active' BEGIN SELECT RAISE(ABORT,'climbing_route_requires_climb_active'); END","CREATE TRIGGER trg_climbing_route_segment_update BEFORE UPDATE OF segment_id ON climbing_routes FOR EACH ROW WHEN (SELECT segment_type FROM activity_segments WHERE id=NEW.segment_id) != 'climb_active' BEGIN SELECT RAISE(ABORT,'climbing_route_requires_climb_active'); END","CREATE TRIGGER trg_strength_set_segment_insert BEFORE INSERT ON strength_sets FOR EACH ROW WHEN (SELECT segment_type FROM activity_segments WHERE id=NEW.segment_id) NOT IN ('strength_active','strength_rest') BEGIN SELECT RAISE(ABORT,'strength_set_requires_strength_segment'); END","CREATE TRIGGER trg_strength_set_segment_update BEFORE UPDATE OF segment_id ON strength_sets FOR EACH ROW WHEN (SELECT segment_type FROM activity_segments WHERE id=NEW.segment_id) NOT IN ('strength_active','strength_rest') BEGIN SELECT RAISE(ABORT,'strength_set_requires_strength_segment'); END"):
            conn.execute(statement)
        conn.execute("INSERT INTO schema_migrations VALUES(1,?,?,?,?)",("foundation_v1",_utc(),"foundation-v1",_FOUNDATION_V1_MIGRATION_SHA256))
        conn.execute("INSERT INTO schema_migrations VALUES(2,?,?,?,?)",("mail_processing_state_v2",_utc(),"foundation-v2",LEGACY_V2_MANIFEST_SHA256))
        conn.execute("INSERT INTO schema_migrations VALUES(3,?,?,?,?)",("analysis_input_trust_v3",_utc(),"foundation-v3",manifest_hash))

    def _complete_phase1_recovery(self, paths: dict[str, Path], expected_hash: str, receipt: FoundationReceipt) -> None:
        """Continue, without recreating metadata, from the exact phase-1 checkpoint."""
        conn=self._connect(paths["db"]); transaction=False
        try:
            conn.execute("BEGIN IMMEDIATE"); transaction=True
            self._apply_phase2_schema(conn,expected_hash,emit_failpoint=True)
            conn.execute("COMMIT"); transaction=False
        except Exception:
            if transaction: conn.execute("ROLLBACK")
            raise
        finally: conn.close()
        audit=self._connect(paths["db"],readonly=True)
        try:
            if validate_schema_manifest(audit,self._manifest()) or not self._migration_receipt_valid(audit,expected_hash) or audit.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise IncompatibleError("initial_schema_verification_failed")
        finally: audit.close()
        self._atomic_json(paths["ready"],{"schema_version":FOUNDATION_SCHEMA_VERSION,"manifest_sha256":expected_hash,"ready":True,"initialized_at_utc":_utc()})
        conn=self._connect(paths["db"])
        try: conn.execute("UPDATE foundation_state SET state='ready', initialized_at_utc=?,updated_at_utc=?,implementation_version='foundation-v3' WHERE id=1",(_utc(),_utc()))
        finally: conn.close()
        receipt.status,receipt.ready,receipt.next_action="initialized",True,"none"
        receipt.foundation_schema_version=FOUNDATION_SCHEMA_VERSION; receipt.applied_migration_ids=[1,2,FOUNDATION_SCHEMA_VERSION]
        receipt.warnings.append({"code":"initialization_recovered","summary":"continued verified phase-1 initialization"})

    def _resume_or_reject_existing(self, paths: dict[str, Path], receipt: FoundationReceipt) -> None:
        """Finish only the one provably complete initializing state.

        This deliberately has no repair/recreate branch.  Any missing object,
        unknown object, migration mismatch, marker disagreement, or unsafe
        permission means an operator must examine the preserved evidence.
        """
        try:
            conn = self._connect(paths["db"])
        except sqlite3.DatabaseError as exc:
            raise CorruptFoundationError("cannot_open_sqlite") from exc
        try:
            state = self._read_foundation_state(conn)
            schema_version = int(state["schema_version"])
            if schema_version > FOUNDATION_SCHEMA_VERSION:
                raise IncompatibleError("higher_schema_version")
            if schema_version != FOUNDATION_SCHEMA_VERSION:
                if state["state"] == "ready" and schema_version < FOUNDATION_SCHEMA_VERSION:
                    conn.close()
                    self._verify(self.data_root, receipt)
                    return
                raise IncompatibleError("unsupported_initializing_schema_version")
            expected_hash = self._manifest_hash()
            if state["state"] == "ready":
                # init is a strict no-op only for an entirely valid ready store.
                conn.close()
                self._verify(self.data_root, receipt)
                if receipt.ready:
                    receipt.status, receipt.next_action = "already_initialized", "none"
                    return
                raise IncompatibleError("ready_environment_inconsistent")
            if state["state"] != "initializing" or state["manifest_sha256"] != expected_hash:
                raise IncompatibleError("initializing_metadata_mismatch")
            # Phase 1 is intentionally observable and contains only the
            # exact metadata checkpoint.  It is a recoverable own checkpoint,
            # not an operator error, provided no other object was introduced.
            if self._phase1_admissible(conn,paths,expected_hash):
                conn.close(); conn=None
                self._complete_phase1_recovery(paths,expected_hash,receipt)
                return
            errors = validate_schema_manifest(conn, self._manifest())
            if not self._migration_receipt_valid(conn,expected_hash):
                errors.append("migration_receipt_mismatch")
            # The marker may be absent after phase 2.  If present it must be
            # exactly the marker that phase 3 would have published.
            marker_kind = self._lstat_kind(paths["ready"], False)
            if marker_kind is not None and self._marker_error(paths, expected_hash):
                errors.append("marker_mismatch")
            # Recovery does not fix permissions or directories.  The marker is
            # optional at this point, so check every other required object.
            required_errors = self._required_objects_and_permissions(paths)
            # The marker is deliberately optional in phase 2 only.
            errors.extend(error for error in required_errors if not error.endswith(paths["ready"].name))
            if errors:
                raise IncompatibleError("initializing_not_recoverable:" + errors[0])
            if marker_kind is None:
                self._atomic_json(paths["ready"], {"schema_version": FOUNDATION_SCHEMA_VERSION, "manifest_sha256": expected_hash, "ready": True, "initialized_at_utc": _utc()})
            conn.execute("UPDATE foundation_state SET state='ready', initialized_at_utc=COALESCE(initialized_at_utc,?), updated_at_utc=?, implementation_version='foundation-v3' WHERE id=1", (_utc(), _utc()))
            receipt.status, receipt.ready, receipt.next_action = "initialized", True, "none"
            receipt.foundation_schema_version = FOUNDATION_SCHEMA_VERSION
            receipt.applied_migration_ids = [1, FOUNDATION_SCHEMA_VERSION]
            receipt.warnings.append({"code": "initialization_recovered", "summary": "completed verified initializing state"})
        except sqlite3.DatabaseError as exc:
            raise CorruptFoundationError("sqlite_recovery_read_failed") from exc
        finally:
            if conn:
                conn.close()

    def _migrate(self, root: Path, target: int | None, receipt: FoundationReceipt) -> None:
        if target != FOUNDATION_SCHEMA_VERSION:
            raise IncompatibleError("unsupported_target_schema_version")
        paths = self._paths(root)
        with self._lock(root):
            if not paths["db"].exists():
                raise IncompatibleError("migration_database_missing")
            # Source admission is genuinely read-only.  In particular, do not
            # enable WAL or start a transaction before proving the source is
            # an exact published Foundation contract.
            audit = self._connect(paths["db"], readonly=True)
            try:
                state = self._read_foundation_state(audit)
                current = int(state["schema_version"])
                if current > FOUNDATION_SCHEMA_VERSION:
                    raise IncompatibleError("higher_schema_version")
                if current == 1:
                    source_error = self._published_v1_source_error(audit, paths)
                    if source_error:
                        raise IncompatibleError(source_error)
                elif current == 2:
                    source_error = self._published_v2_source_error(audit, paths)
                    if source_error:
                        raise IncompatibleError(source_error)
            finally:
                audit.close()

            conn = self._connect(paths["db"])
            try:
                state = self._read_foundation_state(conn)
                current = int(state["schema_version"])
                if current == FOUNDATION_SCHEMA_VERSION:
                    errors = validate_schema_manifest(conn, self._manifest())
                    if state["state"] != "ready":
                        errors.append("database_not_ready")
                    manifest_hash = self._manifest_hash()
                    if state["manifest_sha256"] != manifest_hash:
                        errors.append("database_manifest_mismatch")
                    if state["implementation_version"] != "foundation-v3":
                        errors.append("database_implementation_version_mismatch")
                    if not _canonical_utc(state["initialized_at_utc"]) or not _canonical_utc(state["updated_at_utc"]):
                        errors.append("database_timestamp_mismatch")
                    if not self._migration_receipt_valid(conn, manifest_hash):
                        errors.append("migration_receipt_mismatch")
                    errors.extend(self._required_objects_and_permissions(paths))
                    if [row[0] for row in conn.execute("PRAGMA integrity_check")] != ["ok"]:
                        errors.append("sqlite_integrity_mismatch")
                    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                        errors.append("sqlite_foreign_key_mismatch")
                    if errors:
                        raise IncompatibleError("migration_v3_" + errors[0])
                    marker_error = self._marker_error(paths, self._manifest_hash())
                    if marker_error is None:
                        receipt.status, receipt.ready, receipt.next_action = "already_initialized", True, "none"
                        receipt.foundation_schema_version = FOUNDATION_SCHEMA_VERSION
                        return
                    if not self._is_supported_v2_marker(paths):
                        raise IncompatibleError("migration_marker_inconsistent")
                    # A completed DB transaction may have crashed before marker
                    # publication.  Only an explicit maintenance request may
                    # publish the v3 marker; init remains a strict no-op/reject.
                    self._atomic_json(paths["ready"], {"schema_version": FOUNDATION_SCHEMA_VERSION, "manifest_sha256": self._manifest_hash(), "ready": True, "initialized_at_utc": _utc()}, expected_existing={"schema_version": 2, "manifest_sha256": LEGACY_V2_MANIFEST_SHA256, "ready": True})
                    receipt.status, receipt.ready, receipt.next_action = "initialized", True, "none"
                    receipt.foundation_schema_version = FOUNDATION_SCHEMA_VERSION
                    receipt.applied_migration_ids = [FOUNDATION_SCHEMA_VERSION]
                    receipt.warnings.append({"code": "migration_marker_republished", "summary": "completed explicit migration publication"})
                    return
                if current not in {1, 2} or state["state"] != "ready":
                    raise IncompatibleError("unsupported_migration_source_state")
                # The writer is opened only after read-only admission while
                # holding the Foundation maintenance lock.  Re-check the
                # immutable published-contract proof to catch an out-of-band
                # schema mutation after the read-only admission.
                source_error = self._published_v1_source_error(conn, paths) if current == 1 else self._published_v2_source_error(conn, paths)
                if source_error:
                    raise IncompatibleError(source_error)
                if current == 1:
                    self._migrate_v1_mail_processing_state(conn, paths, receipt)
                    conn.close()
                    conn = None
                    self._migrate_v2_analysis_input_trust(paths, receipt, migration_start=1)
                else:
                    conn.close()
                    conn = None
                    self._migrate_v2_analysis_input_trust(paths, receipt, migration_start=2)
            finally:
                if conn is not None:
                    conn.close()

    @staticmethod
    def _mail_message_columns() -> tuple[str, ...]:
        return ("id", "mail_thread_id", "provider_message_id", "direction", "actor_role", "sent_at_utc", "received_at_utc", "subject", "body_text", "body_sha256", "in_reply_to_provider_message_id", "labels_json", "source_revision_id", "processing_state")

    def _is_supported_v1_marker(self, paths: dict[str, Path]) -> bool:
        try:
            marker = json.loads(self._secure_read_file(paths["ready"]).decode("utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return False
        return (
            set(marker) == {"schema_version", "manifest_sha256", "ready", "initialized_at_utc"}
            and marker.get("ready") is True
            and marker.get("schema_version") == 1
            and marker.get("manifest_sha256") == LEGACY_V1_MANIFEST_SHA256
            and _canonical_utc(marker.get("initialized_at_utc"))
        )

    def _is_supported_v2_marker(self, paths: dict[str, Path]) -> bool:
        """Accept only the marker published by the reviewed v2 release."""
        try:
            marker = json.loads(self._secure_read_file(paths["ready"]).decode("utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return False
        return (
            set(marker) == {"schema_version", "manifest_sha256", "ready", "initialized_at_utc"}
            and marker.get("ready") is True
            and marker.get("schema_version") == 2
            and marker.get("manifest_sha256") == LEGACY_V2_MANIFEST_SHA256
            and _canonical_utc(marker.get("initialized_at_utc"))
        )

    @staticmethod
    def _schema_objects_sha256(conn: sqlite3.Connection) -> str:
        rows = conn.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        normalized = [(kind, name, re.sub(r"\s+", "", statement).lower()) for kind, name, statement in rows]
        return hashlib.sha256(json.dumps(normalized, separators=(",", ":")).encode("utf-8")).hexdigest()

    def _published_v1_source_error(self, conn: sqlite3.Connection, paths: dict[str, Path]) -> str | None:
        """Prove the input is the released v1 store before a migration writes.

        This validates the historical marker, migration receipt and every
        non-internal SQLite object.  It intentionally does not accept merely
        a `schema_version=1` database or a hand-authored compatible CHECK.
        """
        if not self._is_supported_v1_marker(paths):
            return "legacy_v1_marker_unrecognized"
        try:
            state = conn.execute("SELECT state,schema_version,manifest_sha256,initialized_at_utc,updated_at_utc,implementation_version FROM foundation_state WHERE id=1").fetchone()
            migrations = [tuple(row) for row in conn.execute("SELECT version,description,applied_at_utc,code_revision,content_sha256 FROM schema_migrations ORDER BY version")]
        except sqlite3.DatabaseError:
            return "legacy_v1_metadata_unreadable"
        if state is None:
            return "legacy_v1_foundation_state_unrecognized"
        if (
            state["state"] != "ready"
            or int(state["schema_version"]) != 1
            or state["manifest_sha256"] != LEGACY_V1_MANIFEST_SHA256
            or state["implementation_version"] != "foundation-v1"
            or not _canonical_utc(state["initialized_at_utc"])
            or not _canonical_utc(state["updated_at_utc"])
        ):
            return "legacy_v1_foundation_state_unrecognized"
        if (
            len(migrations) != 1
            or migrations[0][:2] != (1, "foundation_v1")
            or not _canonical_utc(migrations[0][2])
            or migrations[0][3:] != ("foundation-v1", LEGACY_V1_MANIFEST_SHA256)
        ):
            return "legacy_v1_migration_receipt_unrecognized"
        if self._schema_objects_sha256(conn) != LEGACY_V1_SCHEMA_OBJECTS_SHA256:
            return "legacy_v1_schema_objects_unrecognized"
        return None

    def _published_v2_source_error(self, conn: sqlite3.Connection, paths: dict[str, Path]) -> str | None:
        """Prove the input is the exact released v2 store before v3 writes."""
        if not (self._is_supported_v2_marker(paths) or self._is_supported_v1_marker(paths)):
            return "legacy_v2_marker_unrecognized"
        try:
            state = conn.execute(
                "SELECT state,schema_version,manifest_sha256,initialized_at_utc,updated_at_utc,implementation_version FROM foundation_state WHERE id=1"
            ).fetchone()
            migrations = [tuple(row) for row in conn.execute(
                "SELECT version,description,applied_at_utc,code_revision,content_sha256 FROM schema_migrations ORDER BY version"
            )]
        except sqlite3.DatabaseError:
            return "legacy_v2_metadata_unreadable"
        if state is None or (
            state["state"] != "ready"
            or int(state["schema_version"]) != 2
            or state["manifest_sha256"] != LEGACY_V2_MANIFEST_SHA256
            or state["implementation_version"] != "foundation-v2"
            or not _canonical_utc(state["initialized_at_utc"])
            or not _canonical_utc(state["updated_at_utc"])
        ):
            return "legacy_v2_foundation_state_unrecognized"
        if (
            len(migrations) != 2
            or migrations[0][0:2] != (1, "foundation_v1")
            or migrations[0][3:] not in (("foundation-v1", _FOUNDATION_V1_MIGRATION_SHA256), ("foundation-v1", LEGACY_V1_MANIFEST_SHA256))
            or not _canonical_utc(migrations[0][2])
            or migrations[1][0:2] != (2, "mail_processing_state_v2")
            or migrations[1][3:] != ("foundation-v2", LEGACY_V2_MANIFEST_SHA256)
            or not _canonical_utc(migrations[1][2])
        ):
            return "legacy_v2_migration_receipt_unrecognized"
        if self._schema_objects_sha256(conn) not in {LEGACY_V2_SCHEMA_OBJECTS_SHA256, LEGACY_V2_FROM_V1_SCHEMA_OBJECTS_SHA256}:
            return "legacy_v2_schema_objects_unrecognized"
        return None

    def _tighten_released_v1_directories(self, paths: dict[str, Path]) -> list[Path]:
        """The sole permitted filesystem repair: known v1 0755 raw parents.

        This runs only after the immutable released-v1 fingerprint passed and
        while the maintenance lock is held.  It never creates, follows, or
        accepts an unknown object.
        """
        changed: list[Path] = []
        try:
            for directory in (paths["raw"], paths["raw"] / "garmin", paths["raw"] / "gmail", paths["raw"] / "legacy"):
                info = directory.lstat()
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                    raise IncompatibleError("migration_environment_unsafe")
                mode = stat.S_IMODE(info.st_mode)
                if mode == 0o755:
                    os.chmod(directory, 0o700, follow_symlinks=False)
                    if self._lstat_kind(directory, True) != "ok":
                        raise IncompatibleError("migration_directory_tighten_failed")
                    changed.append(directory)
                elif mode != 0o700:
                    raise IncompatibleError("migration_environment_unsafe")
        except Exception:
            self._restore_released_v1_directories(changed)
            raise
        return changed

    def _restore_released_v1_directories(self, changed: list[Path]) -> None:
        """Rollback pre-transaction permission tightening after migration failure."""
        for directory in reversed(changed):
            info = directory.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise IncompatibleError("migration_directory_rollback_failed")
            os.chmod(directory, 0o755, follow_symlinks=False)

    def _migrate_v1_mail_processing_state(self, conn: sqlite3.Connection, paths: dict[str, Path], receipt: FoundationReceipt) -> None:
        """Explicit, transactional v1→v2 rebuild of only mail_messages.

        SQLite cannot alter a CHECK constraint in place.  The replacement table
        copies every existing column and value verbatim, including v1 state
        values, before atomically replacing the schema inside the maintenance
        transaction.
        """
        tightened = self._tighten_released_v1_directories(paths)
        if self._required_objects_and_permissions(paths):
            raise IncompatibleError("migration_environment_unsafe")
        columns = self._mail_message_columns()
        actual = [row[1] for row in conn.execute("PRAGMA table_info(mail_messages)")]
        if actual != list(columns):
            raise IncompatibleError("migration_mail_messages_columns_unrecognized")
        conn.execute("PRAGMA foreign_keys=OFF")
        transaction_open = False
        try:
            self._fire_failpoint("before_migration_transaction")
            conn.execute("BEGIN IMMEDIATE")
            transaction_open = True
            before_count = conn.execute("SELECT COUNT(*) FROM mail_messages").fetchone()[0]
            conn.execute(f"CREATE TABLE mail_messages__foundation_v2 ({TABLES['mail_messages']})")
            fields = ",".join(columns)
            conn.execute(f"INSERT INTO mail_messages__foundation_v2 ({fields}) SELECT {fields} FROM mail_messages")
            if conn.execute("SELECT COUNT(*) FROM mail_messages__foundation_v2").fetchone()[0] != before_count:
                raise RuntimeError("migration_mail_message_row_count_mismatch")
            # SQLite validates dependent view definitions while renaming a
            # table.  Views are schema-only stable projections, so they are
            # dropped and recreated inside this same maintenance transaction;
            # no business row or view definition is lost.
            for name in VIEWS:
                conn.execute(f"DROP VIEW IF EXISTS {name}")
            conn.execute("DROP TABLE mail_messages")
            conn.execute("ALTER TABLE mail_messages__foundation_v2 RENAME TO mail_messages")
            for name, definition in TABLES.items():
                if name not in {"foundation_state", "mail_messages"}:
                    conn.execute(f"CREATE TABLE IF NOT EXISTS {name} ({definition})")
            for name, query in VIEWS.items():
                conn.execute(f"CREATE VIEW {name} AS {query}")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source_revisions_current ON source_revisions(provider,resource_kind,provider_object_id,is_current)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_source_revision_current ON source_revisions(provider,resource_kind,provider_object_id) WHERE is_current=1")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_activity_source_role_active ON activity_source_revisions(activity_id,source_role) WHERE is_active=1")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_daily_health_current ON daily_health(subject_id,local_date) WHERE is_current=1")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_analysis_artifact_current ON analysis_artifacts(subject_id,artifact_kind,period_start_local_date,period_end_local_date) WHERE is_current=1")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_mail_response_current ON mail_response_artifacts(subject_id,mail_thread_id,response_kind) WHERE is_current=1")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_garmin_sync_gap_unresolved ON garmin_sync_gaps(subject_id,resource_kind,logical_object_key,window_start_local_date,window_end_local_date,stage) WHERE status IN ('open','deferred')")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_coverage_resource_date ON resource_coverage(resource_kind,local_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_samples_stream ON activity_samples(activity_id,stream_kind,sample_index)")
            conn.execute("UPDATE foundation_state SET schema_version=?,manifest_sha256=?,updated_at_utc=?,implementation_version=? WHERE id=1", (2, LEGACY_V2_MANIFEST_SHA256, _utc(), "foundation-v2"))
            conn.execute("INSERT OR IGNORE INTO schema_migrations(version,description,applied_at_utc,code_revision,content_sha256) VALUES(2,?,?,?,?)", ("mail_processing_state_v2", _utc(), "foundation-v2", LEGACY_V2_MANIFEST_SHA256))
            self._fire_failpoint("during_migration_transaction")
            if (
                self._schema_objects_sha256(conn) not in {LEGACY_V2_SCHEMA_OBJECTS_SHA256, LEGACY_V2_FROM_V1_SCHEMA_OBJECTS_SHA256}
                or [row[0] for row in conn.execute("PRAGMA integrity_check")] != ["ok"]
                or conn.execute("PRAGMA foreign_key_check").fetchone() is not None
            ):
                raise RuntimeError("migration_integrity_or_foreign_key_failed")
            conn.execute("COMMIT")
            transaction_open = False
        except Exception:
            if transaction_open:
                conn.execute("ROLLBACK")
            self._restore_released_v1_directories(tightened)
            raise
        finally:
            conn.execute("PRAGMA foreign_keys=ON")
        self._fire_failpoint("after_migration_transaction")
        self._atomic_json(paths["ready"], {"schema_version": 2, "manifest_sha256": LEGACY_V2_MANIFEST_SHA256, "ready": True, "initialized_at_utc": _utc()}, expected_existing={"schema_version": 1, "manifest_sha256": LEGACY_V1_MANIFEST_SHA256, "ready": True})
        self._fire_failpoint("after_migration_marker")
        receipt.status, receipt.ready, receipt.next_action = "initialized", True, "none"
        receipt.foundation_schema_version = 2
        receipt.migration_start_version, receipt.migration_end_version = 1, 2
        receipt.applied_migration_ids = [2]
        if tightened:
            receipt.warnings.append({"code": "legacy_directory_permissions_tightened", "summary": "secured released v1 raw directories"})

    @staticmethod
    def _analysis_artifact_input_columns() -> tuple[str, ...]:
        return (
            "id", "analysis_run_id", "input_role", "source_entity_type",
            "source_entity_id", "source_revision_id", "source_window_start_utc",
            "source_window_end_utc", "input_sha256", "trust_class", "ordinal",
        )

    @classmethod
    def _analysis_artifact_input_evidence(cls, conn: sqlite3.Connection, table: str) -> tuple[int, str]:
        """Return deterministic evidence for every value in the small rebuilt table."""
        columns = cls._analysis_artifact_input_columns()
        digest = hashlib.sha256()
        count = 0
        for row in conn.execute(f"SELECT {','.join(columns)} FROM {table} ORDER BY id"):
            digest.update(json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            digest.update(b"\n")
            count += 1
        return count, digest.hexdigest()

    def _migrate_v2_analysis_input_trust(self, paths: dict[str, Path], receipt: FoundationReceipt, *, migration_start: int) -> None:
        """Explicit v2→v3 migration that rebuilds only analysis_artifact_inputs.

        SQLite cannot modify a CHECK constraint in place.  The transaction copies
        every column verbatim, proves the copied ordered rows are identical, and
        never rebuilds raw data or any other business table.
        """
        # A v1→v2 commit may have crashed before its marker publication.  Its
        # exact v2 database was admitted above, so explicit maintenance may
        # complete only that known marker transition before starting v3 work.
        republished_v2_marker = self._is_supported_v1_marker(paths)
        if republished_v2_marker:
            self._atomic_json(
                paths["ready"],
                {"schema_version": 2, "manifest_sha256": LEGACY_V2_MANIFEST_SHA256, "ready": True, "initialized_at_utc": _utc()},
                expected_existing={"schema_version": 1, "manifest_sha256": LEGACY_V1_MANIFEST_SHA256, "ready": True},
            )
        conn = self._connect(paths["db"])
        transaction_open = False
        manifest_hash = self._manifest_hash()
        columns = self._analysis_artifact_input_columns()
        try:
            actual = [row[1] for row in conn.execute("PRAGMA table_info(analysis_artifact_inputs)")]
            if actual != list(columns):
                raise IncompatibleError("migration_analysis_artifact_inputs_columns_unrecognized")
            if conn.execute(
                "SELECT 1 FROM analysis_artifact_inputs WHERE trust_class NOT IN ('provider_fact','user_asserted','derived_statistic','prior_model_output') LIMIT 1"
            ).fetchone() is not None:
                raise IncompatibleError("migration_analysis_artifact_inputs_values_unrecognized")
            before = self._analysis_artifact_input_evidence(conn, "analysis_artifact_inputs")
            conn.execute("PRAGMA foreign_keys=OFF")
            self._fire_failpoint("before_v3_migration_transaction")
            conn.execute("BEGIN IMMEDIATE")
            transaction_open = True
            conn.execute(f"CREATE TABLE analysis_artifact_inputs__foundation_v3 ({TABLES['analysis_artifact_inputs']})")
            fields = ",".join(columns)
            conn.execute(
                f"INSERT INTO analysis_artifact_inputs__foundation_v3 ({fields}) SELECT {fields} FROM analysis_artifact_inputs"
            )
            after_copy = self._analysis_artifact_input_evidence(conn, "analysis_artifact_inputs__foundation_v3")
            if after_copy != before:
                raise RuntimeError("migration_analysis_artifact_inputs_evidence_mismatch")
            conn.execute("DROP TABLE analysis_artifact_inputs")
            conn.execute("ALTER TABLE analysis_artifact_inputs__foundation_v3 RENAME TO analysis_artifact_inputs")
            if self._analysis_artifact_input_evidence(conn, "analysis_artifact_inputs") != before:
                raise RuntimeError("migration_analysis_artifact_inputs_publish_mismatch")
            conn.execute(
                "UPDATE foundation_state SET schema_version=?,manifest_sha256=?,updated_at_utc=?,implementation_version=? WHERE id=1",
                (FOUNDATION_SCHEMA_VERSION, manifest_hash, _utc(), "foundation-v3"),
            )
            conn.execute(
                "INSERT INTO schema_migrations(version,description,applied_at_utc,code_revision,content_sha256) VALUES(3,?,?,?,?)",
                ("analysis_input_trust_v3", _utc(), "foundation-v3", manifest_hash),
            )
            self._fire_failpoint("during_v3_migration_transaction")
            if (
                validate_schema_manifest(conn, self._manifest())
                or not self._migration_receipt_valid(conn, manifest_hash)
                or [row[0] for row in conn.execute("PRAGMA integrity_check")] != ["ok"]
                or conn.execute("PRAGMA foreign_key_check").fetchone() is not None
            ):
                raise RuntimeError("migration_integrity_or_foreign_key_failed")
            conn.execute("COMMIT")
            transaction_open = False
        except Exception:
            if transaction_open:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.close()
        self._fire_failpoint("after_v3_migration_transaction")
        self._atomic_json(
            paths["ready"],
            {"schema_version": FOUNDATION_SCHEMA_VERSION, "manifest_sha256": manifest_hash, "ready": True, "initialized_at_utc": _utc()},
            expected_existing={"schema_version": 2, "manifest_sha256": LEGACY_V2_MANIFEST_SHA256, "ready": True},
        )
        self._fire_failpoint("after_v3_migration_marker")
        receipt.status, receipt.ready, receipt.next_action = "initialized", True, "none"
        receipt.foundation_schema_version = FOUNDATION_SCHEMA_VERSION
        receipt.migration_start_version, receipt.migration_end_version = migration_start, FOUNDATION_SCHEMA_VERSION
        receipt.applied_migration_ids = [2, 3] if migration_start == 1 else [3]
        if republished_v2_marker:
            receipt.warnings.append({"code": "migration_marker_republished", "summary": "completed explicit migration publication"})

    def _atomic_json(self, path: Path, payload: dict[str, Any], *, expected_existing: dict[str, Any] | None = None) -> None:
        parent_fd=self._open_checked_directory(path.parent); target=path.name; temp=f".{target}.tmp-{secrets.token_hex(16)}"; fd=-1
        def read_at(name:str)->tuple[dict[str,Any],tuple[int,int],bytes]:
            before=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
            if not(stat.S_ISREG(before.st_mode) and before.st_uid==os.getuid() and stat.S_IMODE(before.st_mode)==0o600): raise IncompatibleError("atomic_json_target_unsafe")
            rfd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0),dir_fd=parent_fd)
            try:
                raw=b""
                while len(raw)<=8192:
                    part=os.read(rfd,min(8193-len(raw),4096))
                    if not part: break
                    raw+=part
                opened=os.fstat(rfd)
            finally: os.close(rfd)
            after=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
            if len(raw)>8192 or (opened.st_dev,opened.st_ino)!=(before.st_dev,before.st_ino) or (after.st_dev,after.st_ino)!=(before.st_dev,before.st_ino): raise IncompatibleError("atomic_json_target_replaced")
            try:
                parsed=json.loads(raw.decode())
            except Exception as exc: raise IncompatibleError("atomic_json_invalid_json") from exc
            if not isinstance(parsed,dict): raise IncompatibleError("atomic_json_invalid_json")
            return parsed,(before.st_dev,before.st_ino),raw
        prefix=f".{target}.marker-"
        try:
            if any(entry.startswith(prefix) and len(entry)>len(prefix) for entry in os.listdir(parent_fd)):
                os.close(parent_fd); raise IncompatibleError("atomic_json_unresolved_claim")
        except OSError as exc:
            os.close(parent_fd); raise IncompatibleError("atomic_json_claim_scan_failed") from exc
        # Initial publication is create-only.  A replacement is reserved for
        # explicit migration publication after the caller has authenticated
        # the existing marker.
        try: old,existing_inode,old_raw=read_at(target); existing="ok"
        except FileNotFoundError: existing=None; existing_inode=None; old=None; old_raw=None
        except (OSError, ValueError, json.JSONDecodeError, IncompatibleError) as exc:
            os.close(parent_fd); raise IncompatibleError("atomic_json_target_unrecognized") from exc
        if existing == "ok":
            if expected_existing is None:
                os.close(parent_fd); raise IncompatibleError("atomic_json_target_exists")
            if any(old.get(key) != value for key, value in expected_existing.items()):
                os.close(parent_fd); raise IncompatibleError("atomic_json_target_unrecognized")
        name = temp
        try:
            fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600,dir_fd=parent_fd)
            encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
            self._write_all(fd, encoded)
            os.fsync(fd); os.lseek(fd,0,os.SEEK_SET)
            readback=b""
            while len(readback)<len(encoded):
                part=os.read(fd,len(encoded)-len(readback))
                if not part: raise OSError("atomic_json_temp_readback_short")
                readback+=part
            if readback != encoded: raise OSError("atomic_json_temp_readback_failed")
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid() or stat.S_IMODE(opened.st_mode) != 0o600:
                raise OSError("atomic_json_temp_unsafe")
            temp_inode=(opened.st_dev,opened.st_ino)
            named=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
            if (named.st_dev,named.st_ino)!=temp_inode: raise IncompatibleError("atomic_json_temp_replaced")
            # Do not replace a concurrently introduced unsafe object.
            try: _,now_inode,_=read_at(target)
            except FileNotFoundError: now_inode=None
            if (existing is None and now_inode is not None) or (existing == "ok" and now_inode != existing_inode):
                raise IncompatibleError("atomic_json_target_replaced")
            if existing is None:
                # hard-link publication is create-only: unlike replace it
                # cannot overwrite a concurrently created marker.
                os.link(name,target,src_dir_fd=parent_fd,dst_dir_fd=parent_fd,follow_symlinks=False)
                os.unlink(name,dir_fd=parent_fd)
                _,final_inode,final_raw=read_at(target)
                if final_inode!=temp_inode or final_raw!=encoded: raise IncompatibleError("atomic_json_publish_failed")
            else:
                oldclaim=f".{target}.marker-old-{secrets.token_hex(16)}"; os.rename(target,oldclaim,src_dir_fd=parent_fd,dst_dir_fd=parent_fd)
                claimed,claim_inode,claim_raw=read_at(oldclaim)
                if claim_inode!=existing_inode or claim_raw!=old_raw: raise IncompatibleError("atomic_json_old_replaced")
                os.link(name,target,src_dir_fd=parent_fd,dst_dir_fd=parent_fd,follow_symlinks=False)
                final,final_inode,final_raw=read_at(target)
                if final_inode!=temp_inode or final_raw!=encoded: raise IncompatibleError("atomic_json_publish_failed")
                os.unlink(name,dir_fd=parent_fd)
            if read_at(target)[0] != payload:
                raise IncompatibleError("atomic_json_publish_failed")
            os.fsync(parent_fd)
            if existing == "ok":
                _,again_inode,again_raw=read_at(oldclaim)
                if again_inode != existing_inode or again_raw != old_raw: raise IncompatibleError("atomic_json_old_replaced")
                os.unlink(oldclaim,dir_fd=parent_fd); os.fsync(parent_fd)
        finally:
            if fd >= 0: os.close(fd)
            try:
                # Never stat→unlink a name which an attacker may have
                # replaced. Move it to a random claim then verify identity.
                cleanup=f".{target}.marker-cleanup-{secrets.token_hex(16)}"
                os.rename(name,cleanup,src_dir_fd=parent_fd,dst_dir_fd=parent_fd)
                _,cleanup_inode,cleanup_raw=read_at(cleanup)
                if 'temp_inode' in locals() and cleanup_inode==temp_inode and cleanup_raw==encoded:
                    os.unlink(cleanup,dir_fd=parent_fd); os.fsync(parent_fd)
                # otherwise leave the named claim: next attempt fail-closed.
            except Exception:
                pass
            os.close(parent_fd)

    def backup_database(self, destination: Path) -> Path:
        """Create an explicit SQLite backup; never changes the foundation database."""
        root = self.data_root
        status = FoundationReceipt(invocation_id="backup-preflight", mode="verify")
        self._verify(root, status)
        if status.status != "ready":
            raise IncompatibleError("foundation_not_ready_for_backup")
        destination = destination.resolve()
        if destination == self._paths(root)["db"]:
            raise ValueError("backup_destination_must_differ")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # SQLite's backup API supports a read-only source.  Do not set WAL,
        # busy-timeout, or any journal metadata on the protected database.
        source = self._connect(self._paths(root)["db"], readonly=True)
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("backup_integrity_failed")
        finally:
            target.close()
            source.close()
        os.chmod(destination, 0o600)
        return destination

    def backup_encrypted(self, destination: Path, key: bytes | Any) -> Path:
        """Authenticated encrypted backup; key is injected only as 32-byte bytes/callable."""
        require_key(key)
        destination = destination.resolve()
        if destination.exists():
            raise FileExistsError("backup_destination_exists")
        with tempfile.TemporaryDirectory(dir=destination.parent if destination.parent.exists() else None) as temporary:
            plain = Path(temporary) / "backup.sqlite"
            self.backup_database(plain)
            container = encrypt_container(plain.read_bytes(), key, os.urandom(12))
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, name = tempfile.mkstemp(dir=destination.parent, prefix=".backup-")
            try:
                os.chmod(name, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(container)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.link(name, destination, follow_symlinks=False)
                except FileExistsError as exc:
                    raise FileExistsError("backup_destination_exists") from exc
                os.chmod(destination, 0o600)
                parent_fd=os.open(destination.parent,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0))
                try: os.fsync(parent_fd)
                finally: os.close(parent_fd)
            finally:
                Path(name).unlink(missing_ok=True)
        return destination

    @staticmethod
    def restore_encrypted(source: Path, destination: Path, key: bytes | Any) -> Path:
        require_key(key)
        if destination.exists():
            raise FileExistsError("restore_destination_exists")
        payload = source.read_bytes()
        plain = decrypt_container(payload, key)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(dir=destination.parent, prefix=".restore-")
        try:
            os.chmod(name, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(plain)
                handle.flush()
                os.fsync(handle.fileno())
            check = sqlite3.connect(name)
            try:
                if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("restored_database_integrity_failed")
                if check.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise RuntimeError("restored_database_fk_failed")
            finally:
                check.close()
            try:
                os.link(name, destination, follow_symlinks=False)
            except FileExistsError as exc:
                raise FileExistsError("restore_destination_exists") from exc
            os.chmod(destination, 0o600)
            parent_fd=os.open(destination.parent,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0))
            try: os.fsync(parent_fd)
            finally: os.close(parent_fd)
        finally:
            Path(name).unlink(missing_ok=True)
        return destination

    @staticmethod
    def _canonical_sqlite_rows(rows: list[tuple[Any, ...]]) -> bytes:
        def encode(value: Any) -> Any:
            if isinstance(value, bytes):
                return {"__bytes__": value.hex()}
            return value
        normalized=[[encode(value) for value in row] for row in rows]
        normalized.sort(key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

    @classmethod
    def relational_fingerprints(cls, conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
        """Return deterministic row/content/reference evidence for every table."""
        result: dict[str, dict[str, Any]] = {}
        for table in ("schema_migrations", *sorted(TABLES)):
            columns=[row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
            rows=[tuple(row) for row in conn.execute(f'SELECT * FROM "{table}"')]
            content=cls._canonical_sqlite_rows(rows)
            foreign=sorted(
                (row[2],row[3],row[4],row[5],row[6])
                for row in conn.execute(f'PRAGMA foreign_key_list("{table}")')
            )
            foreign_columns=sorted({item[1] for item in foreign})
            reference_rows: list[tuple[Any, ...]] = []
            if foreign_columns:
                selected=",".join(f'"{column}"' for column in foreign_columns)
                reference_rows=[tuple(row) for row in conn.execute(f'SELECT {selected} FROM "{table}"')]
            reference_payload=json.dumps(
                {
                    "constraints":foreign,
                    "columns":foreign_columns,
                    "rows":json.loads(cls._canonical_sqlite_rows(reference_rows)),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            result[table]={
                "columns":columns,
                "row_count":len(rows),
                "content_sha256":hashlib.sha256(content).hexdigest(),
                "reference_sha256":hashlib.sha256(reference_payload).hexdigest(),
            }
        return result

    @staticmethod
    def raw_tree_fingerprints(raw_root: Path) -> dict[str, dict[str, Any]]:
        """Hash a checked raw tree without reading outside the configured root."""
        result: dict[str, dict[str, Any]] = {}
        for path in [raw_root, *raw_root.rglob("*")]:
            relative="." if path == raw_root else str(path.relative_to(raw_root))
            info=path.lstat()
            if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
                raise IncompatibleError("rebuild_raw_tree_unsafe")
            if stat.S_ISDIR(info.st_mode):
                if stat.S_IMODE(info.st_mode) != 0o700:
                    raise IncompatibleError("rebuild_raw_tree_unsafe")
                result[relative]={"kind":"directory","mode":0o700}
                continue
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                raise IncompatibleError("rebuild_raw_tree_unsafe")
            fd=os.open(path,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0))
            try:
                opened=os.fstat(fd)
                digest=hashlib.sha256(); size=0
                while True:
                    block=os.read(fd,1024*1024)
                    if not block: break
                    digest.update(block); size += len(block)
                after=path.lstat()
            finally:
                os.close(fd)
            if (opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns) != (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
                raise IncompatibleError("rebuild_raw_tree_changed")
            result[relative]={"kind":"file","mode":0o600,"size_bytes":size,"sha256":digest.hexdigest()}
        return result

    @staticmethod
    def _copy_raw_tree(source: Path, destination: Path) -> None:
        """Copy only checked owner-only raw objects into an isolated shadow."""
        FoundationTool.raw_tree_fingerprints(source)
        for path in sorted(source.rglob("*"),key=lambda item:(len(item.parts),str(item))):
            relative=path.relative_to(source); target=destination / relative
            info=path.lstat()
            if stat.S_ISDIR(info.st_mode):
                target.mkdir(mode=0o700,parents=True,exist_ok=True)
                os.chmod(target,0o700)
                continue
            target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            os.chmod(target.parent,0o700)
            source_fd=os.open(path,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0))
            target_fd=-1
            try:
                opened=os.fstat(source_fd)
                if not (stat.S_ISREG(opened.st_mode) and opened.st_uid==os.getuid() and stat.S_IMODE(opened.st_mode)==0o600):
                    raise IncompatibleError("rebuild_raw_file_unsafe")
                target_fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
                while True:
                    block=os.read(source_fd,1024*1024)
                    if not block: break
                    FoundationTool._write_all(target_fd,block)
                os.fchmod(target_fd,0o600); os.fsync(target_fd)
                after=path.lstat()
                if (opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns) != (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
                    raise IncompatibleError("rebuild_raw_file_changed")
            finally:
                if target_fd>=0: os.close(target_fd)
                os.close(source_fd)

    def rebuild_into(self, destination_root: Path) -> Path:
        """Build and atomically publish a reconciled shadow without replacing source."""
        destination_root = destination_root.resolve()
        if destination_root == self.data_root:
            raise ValueError("rebuild_destination_must_differ")
        if destination_root.exists():
            raise FileExistsError("rebuild_destination_exists")
        source_status=FoundationReceipt(invocation_id="rebuild-source-verify",mode="verify")
        self._verify(self.data_root,source_status)
        if source_status.status != "ready":
            raise IncompatibleError("rebuild_source_not_ready")
        destination_root.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        parent_info=destination_root.parent.lstat()
        if not (stat.S_ISDIR(parent_info.st_mode) and not stat.S_ISLNK(parent_info.st_mode) and parent_info.st_uid==os.getuid() and not (stat.S_IMODE(parent_info.st_mode)&0o022)):
            raise IncompatibleError("rebuild_destination_parent_unsafe")
        with tempfile.TemporaryDirectory(prefix=".foundation-shadow-",dir=destination_root.parent) as workspace:
            shadow=Path(workspace) / "candidate"
            candidate=FoundationTool(FoundationConfig(shadow,shadow/"data.db",shadow/"raw",shadow/"state",shadow/"state/foundation-ready.json",shadow/"state/locks/foundation.lock"))
            receipt=candidate.execute(FoundationRequest("init","explicit-shadow-rebuild",_utc()))
            if receipt.status != "initialized":
                raise RuntimeError("rebuild_candidate_failed")
            self._fire_failpoint("shadow_after_schema")
            source=self._connect(self._paths(self.data_root)["db"],readonly=True)
            target=candidate._connect(shadow/"data.db")
            transaction_open=False
            try:
                source_fingerprints=self.relational_fingerprints(source)
                source_has_sequences=source.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
                ).fetchone() is not None
                source_sequences=(
                    [
                        tuple(row)
                        for row in source.execute("SELECT name,seq FROM sqlite_sequence ORDER BY name")
                    ]
                    if source_has_sequences else []
                )
                target.execute("PRAGMA foreign_keys=OFF")
                target.execute("BEGIN IMMEDIATE"); transaction_open=True
                for ordinal,table in enumerate(("schema_migrations",*sorted(TABLES))):
                    columns=[row[1] for row in source.execute(f'PRAGMA table_info("{table}")')]
                    if table in {"schema_migrations","foundation_state"}:
                        target.execute(f'DELETE FROM "{table}"')
                    rows=[tuple(row) for row in source.execute(f'SELECT * FROM "{table}"')]
                    if rows:
                        names=",".join(f'"{column}"' for column in columns)
                        placeholders=",".join("?" for _ in columns)
                        target.executemany(f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})',rows)
                    if ordinal == 1:
                        self._fire_failpoint("shadow_during_copy")
                if source_has_sequences:
                    target.execute("DELETE FROM sqlite_sequence")
                    target.executemany(
                        "INSERT INTO sqlite_sequence(name,seq) VALUES(?,?)",
                        source_sequences,
                    )
                target.execute("COMMIT"); transaction_open=False
                target.execute("PRAGMA foreign_keys=ON")
                if self.relational_fingerprints(target) != source_fingerprints:
                    raise RuntimeError("rebuild_relational_reconciliation_failed")
                target_sequences=(
                    [
                        tuple(row)
                        for row in target.execute("SELECT name,seq FROM sqlite_sequence ORDER BY name")
                    ]
                    if source_has_sequences else []
                )
                if target_sequences != source_sequences:
                    raise RuntimeError("rebuild_sequence_reconciliation_failed")
                if [row[0] for row in target.execute("PRAGMA integrity_check")] != ["ok"] or target.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise RuntimeError("rebuild_integrity_or_foreign_key_failed")
            except Exception:
                if transaction_open: target.execute("ROLLBACK")
                raise
            finally:
                target.close(); source.close()
            self._copy_raw_tree(self._paths(self.data_root)["raw"],shadow/"raw")
            if self.raw_tree_fingerprints(self._paths(self.data_root)["raw"]) != self.raw_tree_fingerprints(shadow/"raw"):
                raise RuntimeError("rebuild_raw_reconciliation_failed")
            self._fire_failpoint("shadow_after_copy")
            verification=candidate.execute(FoundationRequest("verify","explicit-shadow-rebuild-verify",_utc()))
            if verification.status != "ready":
                raise RuntimeError("rebuild_candidate_not_ready")
            self._fire_failpoint("shadow_before_publish")
            if destination_root.exists():
                raise FileExistsError("rebuild_destination_exists")
            os.replace(shadow,destination_root)
            parent_fd=os.open(destination_root.parent,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0))
            try: os.fsync(parent_fd)
            finally: os.close(parent_fd)
        self._fire_failpoint("shadow_after_publish")
        return destination_root


class IncompatibleError(RuntimeError):
    pass


class CorruptFoundationError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trainlab foundation")
    sub = parser.add_subparsers(dest="mode", required=True)
    for name in ("init", "status", "verify"):
        sub.add_parser(name)
    migrate = sub.add_parser("migrate")
    migrate.add_argument("--target-version", type=int, required=True)
    parser.add_argument("--invocation-id", default=f"foundation-{int(time.time()*1000)}")
    args = parser.parse_args(argv)
    from ..util import project_root
    safe_invocation=args.invocation_id if isinstance(args.invocation_id,str) and _INVOCATION_RE.fullmatch(args.invocation_id) else ""
    try:
        tool=FoundationTool(FoundationConfig.load(project_root()))
    except Exception:
        receipt=FoundationReceipt(invocation_id=safe_invocation,mode=args.mode,status="failed",next_action="operator_review",errors=[{"code":"invalid_configuration","summary":"foundation_configuration_rejected"}],completed_at_utc=_utc())
        print(receipt.json())
        return 20
    receipt = tool.execute(FoundationRequest(mode=args.mode, invocation_id=args.invocation_id, requested_at_utc=_utc(), target_schema_version=getattr(args, "target_version", None)))
    print(receipt.json())
    return 0 if receipt.status in _SUCCESS else {"incompatible": 10, "lock_busy": 11}.get(receipt.status, 20)
