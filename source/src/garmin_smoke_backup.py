"""Fail-closed, local-only E-04 backup preparation.

This creates evidence for backup, restore, and Foundation shadow copying only.
It deliberately makes no assertion about a legacy service, canonical ownership,
or an approved shadow window.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import sqlite3
import stat
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from .foundation import FoundationConfig, FoundationRequest, FoundationTool

_AUTH = re.compile(r"^authz-[0-9a-f]{32}$")
_VERSION = "1"


class GarminSmokeBackupError(ValueError):
    pass


def _fail(code: str) -> None:
    raise GarminSmokeBackupError(code)


def _walk_ancestors(path: Path) -> None:
    """Reject any unsafe non-system component without resolving symlinks."""
    current = path.absolute()
    while True:
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            _fail("unsafe_ancestor")
        # A user-owned mounted volume is also a trust boundary on macOS.  Such
        # mount roots are commonly 0775; accept that platform default only when
        # the mount is not world-writable.  Every project-controlled component
        # below the mount remains subject to the stricter owner/no-write check.
        if os.path.ismount(current):
            if (
                info.st_uid not in {0, os.getuid()}
                or stat.S_IMODE(info.st_mode) & 0o002
            ):
                _fail("unsafe_ancestor")
            return
        # A root-owned ancestor is the trusted system boundary.  Every
        # intervening, operator-controlled component is strict owner-only.
        if info.st_uid == 0:
            return
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
            _fail("unsafe_ancestor")
        if current.parent == current:
            return
        current = current.parent


def _safe_regular(
    path: Path, *, exact_mode: int | None = None
) -> tuple[int, int, int, int]:
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_uid != os.getuid()
    ):
        _fail("unsafe_source")
    if exact_mode is not None and stat.S_IMODE(before.st_mode) != exact_mode:
        _fail("unsafe_source")
    if exact_mode is None and stat.S_IMODE(before.st_mode) & 0o022:
        _fail("unsafe_source")
    return (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)


def _identity(path: Path) -> tuple[int, int, int, int]:
    return _safe_regular(path)


def _read_key(path: Path) -> bytes:
    before = _safe_regular(path, exact_mode=0o600)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != before:
            _fail("key_replaced")
        chunks = []
        while True:
            part = os.read(fd, 4096)
            if not part:
                break
            chunks.append(part)
        after = _safe_regular(path, exact_mode=0o600)
        if after != before:
            _fail("key_replaced")
    finally:
        os.close(fd)
    value = b"".join(chunks)
    if len(value) != 32:
        _fail("backup_key_invalid")
    return value


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _value(value: Any) -> Any:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bytes):
        return {"type": "blob", "sha256": sha256(value).hexdigest(), "size": len(value)}
    if isinstance(value, float):
        if math.isnan(value):
            return {"type": "float", "value": "nan"}
        if math.isinf(value):
            return {"type": "float", "value": "inf" if value > 0 else "-inf"}
        return {"type": "float", "value": value.hex()}
    return value


def _hash(domain: str, value: Any) -> str:
    material = {"version": _VERSION, "domain": domain, "material": value}
    return sha256(
        json.dumps(
            material, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


def _ro_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True)


def sqlite_aggregate_hash(path: Path, domain: str) -> str:
    """Versioned, domain-separated table aggregate; never returns table data."""
    identity = _safe_regular(path)
    conn = _ro_connection(path)
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            _fail("sqlite_integrity_failed")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            _fail("sqlite_foreign_key_failed")
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        tables = []
        for name in names:
            quoted = _quote(name)
            columns = [r[1] for r in conn.execute(f"PRAGMA table_info({quoted})")]
            rows = [
                [_value(v) for v in row]
                for row in conn.execute(f"SELECT * FROM {quoted}")
            ]
            rows.sort(
                key=lambda row: json.dumps(
                    row, sort_keys=True, separators=(",", ":"), ensure_ascii=True
                )
            )
            tables.append(
                {"name": name, "columns": columns, "count": len(rows), "rows": rows}
            )
        return _hash(domain, tables)
    finally:
        conn.close()
        if _safe_regular(path) != identity:
            _fail("source_changed")


def _new_sqlite(path: Path) -> None:
    fd = os.open(
        path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    os.close(fd)
    if stat.S_IMODE(path.lstat().st_mode) != 0o600:
        _fail("target_mode_unsafe")


def _online_backup(source: Path, destination: Path) -> None:
    source_id = _safe_regular(source)
    _new_sqlite(destination)
    left = _ro_connection(source)
    right = sqlite3.connect(destination)
    try:
        left.backup(right)
        if (
            right.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            or right.execute("PRAGMA foreign_key_check").fetchone() is not None
        ):
            _fail("sqlite_backup_invalid")
    finally:
        right.close()
        left.close()
        if _safe_regular(source) != source_id:
            _fail("source_changed")
    _safe_regular(destination, exact_mode=0o600)


def _raw_hash(tool: FoundationTool, raw: Path) -> str:
    return _hash("foundation-raw-v1", tool.raw_tree_fingerprints(raw))


def _reject_wal(path: Path) -> None:
    wal = path.with_name(path.name + "-wal")
    shm = path.with_name(path.name + "-shm")
    if wal.exists():
        wal_info = _safe_regular(wal)
        # Foundation verification can leave a zero-length WAL plus its SHM
        # after the connection closes.  There are no uncheckpointed frames in
        # that state; a non-empty WAL remains a hard failure.
        if wal_info[2] != 0:
            _fail("sqlite_not_quiescent")
    if shm.exists():
        _safe_regular(shm)


def _recheck_quiescence(config: FoundationConfig, db: Path, legacy: Path) -> None:
    """Recheck locks and observe sidecars after each read-only snapshot stage.

    Pre-existing WAL/SHM is rejected before work starts.  A sidecar created by
    SQLite/Foundation's own read-only snapshot handling is not treated as an
    external writer: the database identity and aggregate checks remain the
    fail-closed consistency proof for this non-adversarial boundary.
    """
    if (
        config.lock_path.exists()
        or (config.state_root / "locks" / "garmin.lock").exists()
    ):
        _fail("source_not_quiescent_or_ready")
    for path in (db, legacy):
        for suffix in ("-wal", "-shm"):
            sidecar = path.with_name(path.name + suffix)
            if sidecar.exists():
                _safe_regular(sidecar)


def _cleanup(root: Path, identity: tuple[int, int]) -> bool:
    try:
        now = root.lstat()
        if (
            (now.st_dev, now.st_ino) != identity
            or stat.S_ISLNK(now.st_mode)
            or now.st_uid != os.getuid()
        ):
            return False
        for item in root.rglob("*"):
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
                return False
        shutil.rmtree(root)
        return not root.exists()
    except OSError:
        return False


def _unchanged(
    db: Path,
    db_id: tuple[int, int, int, int],
    raw: Path,
    raw_hash: str,
    tool: FoundationTool,
    legacy: Path,
    legacy_id: tuple[int, int, int, int],
    f_hash: str,
    l_hash: str,
) -> None:
    if (
        _identity(db) != db_id
        or _identity(legacy) != legacy_id
        or _raw_hash(tool, raw) != raw_hash
        or sqlite_aggregate_hash(db, "foundation-db-v1") != f_hash
        or sqlite_aggregate_hash(legacy, "legacy-db-v1") != l_hash
    ):
        _fail("source_changed")


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_receipt(path: Path, receipt: dict[str, object]) -> None:
    fd = os.open(
        path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    try:
        os.write(
            fd,
            json.dumps(
                receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode(),
        )
        os.fsync(fd)
    finally:
        os.close(fd)


def prepare_backup(
    *,
    project_root: Path,
    output_root: Path,
    key_file: Path,
    authorization_id: str,
    operator_registered: bool,
    legacy_db: Path | None = None,
    config_loader: Callable[[Path], FoundationConfig] = FoundationConfig.load,
    failpoint: Callable[[str], None] | None = None,
) -> dict[str, object]:
    if not _AUTH.fullmatch(authorization_id) or operator_registered is not True:
        _fail("authorization_or_operator_invalid")
    output_root = output_root.absolute()
    if output_root.exists():
        _fail("backup_target_exists")
    _walk_ancestors(output_root.parent)
    _walk_ancestors(key_file.absolute().parent)
    config = config_loader(project_root)
    tool = FoundationTool(config)
    status = tool.execute(
        FoundationRequest("verify", "e04-backup-preflight", "2026-01-01T00:00:00Z")
    )
    if (
        status.status != "ready"
        or config.lock_path.exists()
        or (config.state_root / "locks" / "garmin.lock").exists()
    ):
        _fail("source_not_quiescent_or_ready")
    legacy = (legacy_db or project_root / "data.db").absolute()
    db = config.database_path
    _walk_ancestors(db.parent)
    _walk_ancestors(config.raw_root)
    _walk_ancestors(legacy.parent)
    _reject_wal(db)
    _reject_wal(legacy)
    db_id, legacy_id = _identity(db), _identity(legacy)
    raw_before = _raw_hash(tool, config.raw_root)
    foundation_before, legacy_before = (
        sqlite_aggregate_hash(db, "foundation-db-v1"),
        sqlite_aggregate_hash(legacy, "legacy-db-v1"),
    )
    key = _read_key(key_file)
    # mkdir atomically reserves the final directory name (directory O_EXCL).
    try:
        os.mkdir(output_root, 0o700)
    except FileExistsError:
        _fail("backup_target_exists")
    os.chmod(output_root, 0o700)
    workspace = output_root
    work_id = (workspace.lstat().st_dev, workspace.lstat().st_ino)
    try:
        encrypted = workspace / "foundation.tlfb"
        restored = workspace / "foundation-restored.db"
        legacy_backup = workspace / "legacy-backup.db"
        legacy_restored = workspace / "legacy-restored.db"
        tool.backup_encrypted(encrypted, lambda: key)
        _safe_regular(encrypted, exact_mode=0o600)
        _recheck_quiescence(config, db, legacy)
        _unchanged(
            db,
            db_id,
            config.raw_root,
            raw_before,
            tool,
            legacy,
            legacy_id,
            foundation_before,
            legacy_before,
        )
        if failpoint:
            failpoint("backup")
        FoundationTool.restore_encrypted(encrypted, restored, lambda: key)
        _safe_regular(restored, exact_mode=0o600)
        _online_backup(legacy, legacy_backup)
        _online_backup(legacy_backup, legacy_restored)
        if (
            sqlite_aggregate_hash(restored, "foundation-db-v1") != foundation_before
            or sqlite_aggregate_hash(legacy_restored, "legacy-db-v1") != legacy_before
        ):
            _fail("restore_aggregate_mismatch")
        _recheck_quiescence(config, db, legacy)
        _unchanged(
            db,
            db_id,
            config.raw_root,
            raw_before,
            tool,
            legacy,
            legacy_id,
            foundation_before,
            legacy_before,
        )
        if failpoint:
            failpoint("restore")
        shadow = tool.rebuild_into(workspace / "foundation-shadow")
        shadow_db = shadow / "data.db"
        shadow_raw = shadow / "raw"
        if (
            sqlite_aggregate_hash(shadow_db, "foundation-db-v1") != foundation_before
            or _raw_hash(tool, shadow_raw) != raw_before
        ):
            _fail("shadow_aggregate_mismatch")
        _recheck_quiescence(config, db, legacy)
        _unchanged(
            db,
            db_id,
            config.raw_root,
            raw_before,
            tool,
            legacy,
            legacy_id,
            foundation_before,
            legacy_before,
        )
        if failpoint:
            failpoint("shadow")
        receipt: dict[str, object] = {
            "schema_version": _VERSION,
            "authorization_id": authorization_id,
            "operator_registered": True,
            "foundation_backup_verified": True,
            "foundation_restore_verified": True,
            "foundation_shadow_copy_verified": True,
            "legacy_backup_restore_verified": True,
            "legacy_snapshot_scope": "online_snapshot_with_repeated_quiescence_checks",
            "foundation_source_aggregate_sha256": foundation_before,
            "foundation_restore_aggregate_sha256": sqlite_aggregate_hash(
                restored, "foundation-db-v1"
            ),
            "foundation_shadow_aggregate_sha256": sqlite_aggregate_hash(
                shadow_db, "foundation-db-v1"
            ),
            "legacy_source_aggregate_sha256": legacy_before,
            "legacy_restore_aggregate_sha256": sqlite_aggregate_hash(
                legacy_restored, "legacy-db-v1"
            ),
            "backup_artifacts_sha256": _hash(
                "backup-artifacts-v1",
                [
                    sha256(encrypted.read_bytes()).hexdigest(),
                    sha256(legacy_backup.read_bytes()).hexdigest(),
                ],
            ),
        }
        receipt["receipt_sha256"] = _hash("backup-receipt-v1", receipt)
        if failpoint:
            failpoint("publish")
        _write_receipt(workspace / "receipt.json", receipt)
        _fsync_directory(workspace)
        _fsync_directory(output_root.parent)
        return receipt
    except Exception:
        if not _cleanup(workspace, work_id):
            _fail("cleanup_failed")
        raise
