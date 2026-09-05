"""Private, relocatable FIT store. No legacy database, Provider or AI imports.

The writer lock belongs to this new instance, never the formal legacy state.
Files become durable before their index transaction commits. An interrupted
import can leave a hash-named orphan; exact replay adopts it, never overwrites it.
"""

from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import re
import sqlite3
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA user_version=1;
CREATE TABLE fits (
 sha256 TEXT PRIMARY KEY CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
 relative_path TEXT NOT NULL UNIQUE,
 byte_size INTEGER NOT NULL CHECK(byte_size>0)
) STRICT;
CREATE TABLE activity_fits (
 activity_ref TEXT NOT NULL,
 fit_sha256 TEXT NOT NULL UNIQUE REFERENCES fits(sha256) ON DELETE RESTRICT,
 PRIMARY KEY(activity_ref,fit_sha256)
) STRICT;
CREATE TABLE parses (
 fit_sha256 TEXT NOT NULL REFERENCES fits(sha256) ON DELETE RESTRICT,
 parser_version TEXT NOT NULL,
 content_json TEXT NOT NULL CHECK(json_valid(content_json)),
 content_sha256 TEXT NOT NULL CHECK(length(content_sha256)=64),
 PRIMARY KEY(fit_sha256,parser_version)
) STRICT;
CREATE TABLE documents (
 kind TEXT NOT NULL CHECK(kind IN ('weekly_input','weekly_report','training_plan','sync_receipt','delivery_receipt')),
 logical_key TEXT NOT NULL,
 input_sha256 TEXT NOT NULL CHECK(length(input_sha256)=64 AND input_sha256 NOT GLOB '*[^0-9a-f]*'),
 content_json TEXT NOT NULL CHECK(json_valid(content_json)),
 content_sha256 TEXT NOT NULL CHECK(length(content_sha256)=64),
 PRIMARY KEY(kind,logical_key,input_sha256)
) STRICT;
"""
TABLES = ("fits", "activity_fits", "parses", "documents")
for _table in TABLES:
    for _operation in ("UPDATE", "DELETE"):
        SCHEMA += (
            f"CREATE TRIGGER {_table}_{_operation.lower()} BEFORE {_operation} ON {_table} "
            "BEGIN SELECT RAISE(ABORT,'immutable_record'); END;\n"
        )

SCHEMA_V1 = SCHEMA
SYNC_SCHEMA = """
CREATE TABLE sync_jobs (
 job_key TEXT PRIMARY KEY,
 input_json TEXT NOT NULL CHECK(json_valid(input_json)),
 input_sha256 TEXT NOT NULL CHECK(length(input_sha256)=64)
) STRICT;
CREATE TABLE sync_calls (
 job_key TEXT NOT NULL REFERENCES sync_jobs(job_key),
 ordinal INTEGER NOT NULL CHECK(ordinal>=1),
 page INTEGER NOT NULL CHECK(page>=0),
 request_json TEXT NOT NULL CHECK(json_valid(request_json)),
 PRIMARY KEY(job_key,ordinal)
) STRICT;
CREATE TABLE sync_results (
 job_key TEXT NOT NULL,
 ordinal INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('page','error')),
 content_json TEXT NOT NULL CHECK(json_valid(content_json)),
 content_sha256 TEXT NOT NULL CHECK(length(content_sha256)=64),
 PRIMARY KEY(job_key,ordinal),
 FOREIGN KEY(job_key,ordinal) REFERENCES sync_calls(job_key,ordinal)
) STRICT;
CREATE TABLE sync_days (
 day TEXT NOT NULL,
 job_key TEXT NOT NULL REFERENCES sync_jobs(job_key),
 status TEXT NOT NULL CHECK(status IN ('complete','provisional')),
 activity_count INTEGER NOT NULL CHECK(activity_count>=0),
 PRIMARY KEY(day,job_key)
) STRICT;
CREATE TABLE sync_gaps (
 day TEXT PRIMARY KEY,
 detected_at_utc TEXT NOT NULL
) STRICT;
"""
SYNC_TABLES = ("sync_jobs", "sync_calls", "sync_results", "sync_days", "sync_gaps")
for _table in SYNC_TABLES:
    for _operation in ("UPDATE", "DELETE"):
        SYNC_SCHEMA += (
            f"CREATE TRIGGER {_table}_{_operation.lower()} BEFORE {_operation} ON {_table} "
            "BEGIN SELECT RAISE(ABORT,'immutable_record'); END;\n"
        )
SYNC_SCHEMA += "PRAGMA user_version=2;\n"
SCHEMA = SCHEMA_V1 + SYNC_SCHEMA


def canonical(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def private_entry(
    path: Path, *, directory: bool = False, nonempty: bool = False
) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ValueError("store_missing") from exc
    kind = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (
        not kind
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
        or (not directory and info.st_nlink != 1)
        or (nonempty and info.st_size == 0)
    ):
        raise ValueError("store_private_entry_invalid")


def sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_file(path: Path, data: bytes) -> None:
    if not data:
        raise ValueError("store_empty_artifact")
    private_entry(path.parent, directory=True)
    if path.exists() or path.is_symlink():
        private_entry(path, nonempty=True)
        if path.read_bytes() != data:
            raise ValueError("store_file_conflict")
        # The previous attempt may have renamed the file but failed its barrier.
        # Reuse is successful only after both data and directory are durable.
        with path.open("rb") as existing_stream:
            os.fsync(existing_stream.fileno())
        sync_dir(path.parent)
        return
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    # A finite failure leaves the pending file for diagnosis, not a success path.
    try:
        stream = os.fdopen(fd, "wb")
    except BaseException:
        os.close(fd)
        raise
    with stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.rename(name, path)
    sync_dir(path.parent)


def schema_rows(db: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return [
        tuple(row)
        for row in db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        )
    ]


def require_schema(db: sqlite3.Connection, version: int = 2) -> None:
    actual_version = db.execute("PRAGMA user_version").fetchone()[0]
    if version == 2 and actual_version == 1:
        raise ValueError("store_upgrade_required")
    with sqlite3.connect(":memory:") as expected:
        expected.executescript(SCHEMA if version == 2 else SCHEMA_V1)
        expected_rows = schema_rows(expected)
    if (
        actual_version != version
        or schema_rows(db) != expected_rows
        or db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
        or db.execute("PRAGMA foreign_key_check").fetchall()
    ):
        raise ValueError("store_schema_or_integrity_invalid")


def initialize(root: Path) -> None:
    if (root / "trainlab-fit.db").exists():
        with open_store(root):
            return
    if root.exists():
        private_entry(root, directory=True)
        if list(root.iterdir()):
            raise ValueError("store_destination_not_empty")
    else:
        root.mkdir(mode=0o700)
    private_entry(root, directory=True)
    (root / "fits").mkdir(mode=0o700)
    fd = os.open(root / "writer.lock", os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        target = root / "trainlab-fit.db"
        db_fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(db_fd)
        db = sqlite3.connect(target)
        try:
            db.executescript(SCHEMA)
            require_schema(db)
        finally:
            db.close()
        with target.open("rb") as stream:
            os.fsync(stream.fileno())
        sync_dir(root / "fits")
        sync_dir(root)
        sync_dir(root.parent)
    finally:
        os.close(fd)


@contextmanager
def _locked_connection(root: Path) -> Iterator[sqlite3.Connection]:
    private_entry(root, directory=True)
    private_entry(root / "writer.lock")
    fd = os.open(root / "writer.lock", os.O_RDONLY)
    db: sqlite3.Connection | None = None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("store_busy") from exc
        private_entry(root / "trainlab-fit.db", nonempty=True)
        private_entry(root / "fits", directory=True)
        db = sqlite3.connect(
            (root / "trainlab-fit.db").resolve().as_uri() + "?mode=rw", uri=True
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA recursive_triggers=ON")
        db.execute("PRAGMA synchronous=FULL")
        if (
            not db.execute("PRAGMA foreign_keys").fetchone()[0]
            or not db.execute("PRAGMA recursive_triggers").fetchone()[0]
        ):
            raise ValueError("store_connection_unsafe")
        yield db
    except sqlite3.DatabaseError as exc:
        raise ValueError("store_database_invalid") from exc
    finally:
        if db is not None:
            db.close()  # Uncommitted work is rolled back on every failure path.
        os.close(fd)


@contextmanager
def open_store(root: Path) -> Iterator[sqlite3.Connection]:
    with _locked_connection(root) as db:
        require_schema(db)
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()


def upgrade(root: Path) -> None:
    """Explicit, atomic v1→v2 upgrade of the new store, never the legacy ledger."""
    with _locked_connection(root) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version == 2:
            require_schema(db)
            return
        require_schema(db, 1)
        db.execute("BEGIN IMMEDIATE")
        statement = ""
        for line in SYNC_SCHEMA.splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                db.execute(statement)
                statement = ""
        if statement.strip():
            raise ValueError("store_migration_invalid")
        require_schema(db)
        db.commit()


def require_sha(value: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("store_sha_invalid")


def require_instance(db: sqlite3.Connection, root: Path) -> None:
    main = [row for row in db.execute("PRAGMA database_list") if row[1] == "main"]
    if (
        len(main) != 1
        or Path(main[0][2]).resolve() != (root / "trainlab-fit.db").resolve()
    ):
        raise ValueError("store_instance_mismatch")


def require_fit(data: bytes) -> None:
    import fitdecode

    try:
        if len(data) < 16 or data[8:12] != b".FIT":
            raise ValueError("bad header")
        files = 0
        sessions = 0
        with fitdecode.FitReader(
            io.BytesIO(data),
            check_crc=fitdecode.CrcCheck.RAISE,
            error_handling=fitdecode.ErrorHandling.RAISE,
        ) as reader:
            for frame in reader:
                if isinstance(frame, fitdecode.FitDataMessage):
                    if frame.name == "file_id":
                        if frame.get_value("type") != "activity":
                            raise ValueError("not activity")
                        files += 1
                    elif frame.name == "session":
                        sessions += 1
        if files != 1 or sessions < 1:
            raise ValueError("activity session missing")
    except Exception as exc:
        raise ValueError("fit_invalid") from exc


def import_fit(
    db: sqlite3.Connection,
    root: Path,
    activity_ref: str,
    source: Path,
    expected_sha: str,
) -> str:
    require_instance(db, root)
    require_sha(expected_sha)
    if not re.fullmatch(r"[0-9]{1,32}", activity_ref):
        raise ValueError("fit_activity_invalid")
    private_entry(source, nonempty=True)
    data = source.read_bytes()
    if digest(data) != expected_sha:
        raise ValueError("fit_sha_mismatch")
    require_fit(data)
    binding = db.execute(
        "SELECT activity_ref FROM activity_fits WHERE fit_sha256=?", (expected_sha,)
    ).fetchone()
    if binding is not None and binding[0] != activity_ref:
        raise ValueError("fit_activity_conflict")
    relative = f"fits/{expected_sha}.fit"
    # File durability precedes the SQL commit. A matching orphan is safe to reuse.
    atomic_file(root / relative, data)
    old = db.execute(
        "SELECT relative_path,byte_size FROM fits WHERE sha256=?", (expected_sha,)
    ).fetchone()
    if old is not None and tuple(old) != (relative, len(data)):
        raise ValueError("fit_index_conflict")
    if old is None:
        db.execute(
            "INSERT INTO fits VALUES (?,?,?)", (expected_sha, relative, len(data))
        )
    if binding is None:
        db.execute(
            "INSERT INTO activity_fits VALUES (?,?)", (activity_ref, expected_sha)
        )
    return relative


def verify_fit_closure(db: sqlite3.Connection, root: Path) -> int:
    require_instance(db, root)
    rows = db.execute("SELECT sha256,relative_path,byte_size FROM fits").fetchall()
    expected = set()
    for row in rows:
        relative = f"fits/{row[0]}.fit"
        if relative != row[1]:
            raise ValueError("fit_index_conflict")
        p = root / relative
        private_entry(p, nonempty=True)
        data = p.read_bytes()
        if digest(data) != row[0] or len(data) != row[2]:
            raise ValueError("fit_sha_mismatch")
        expected.add(p.name)
    if {p.name for p in (root / "fits").iterdir()} != expected:
        raise ValueError("fit_files_not_closed")
    unbound = db.execute(
        "SELECT COUNT(*) FROM fits f LEFT JOIN activity_fits a ON f.sha256=a.fit_sha256 WHERE a.fit_sha256 IS NULL"
    ).fetchone()[0]
    if unbound:
        raise ValueError("fit_files_not_closed")
    return len(rows)


def put_parse(
    db: sqlite3.Connection, fit_sha: str, version: str, payload: dict[str, Any]
) -> str:
    require_sha(fit_sha)
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", version):
        raise ValueError("parser_version_invalid")
    text = canonical(payload)
    sha = digest(text.encode())
    old = db.execute(
        "SELECT content_json,content_sha256 FROM parses WHERE fit_sha256=? AND parser_version=?",
        (fit_sha, version),
    ).fetchone()
    if old is not None:
        if tuple(old) != (text, sha):
            raise ValueError("immutable_result_conflict")
        return sha
    db.execute("INSERT INTO parses VALUES (?,?,?,?)", (fit_sha, version, text, sha))
    return sha


def put_document(
    db: sqlite3.Connection, kind: str, key: str, input_sha: str, payload: dict[str, Any]
) -> str:
    require_sha(input_sha)
    if not key or len(key) > 200:
        raise ValueError("document_key_invalid")
    text = canonical(payload)
    sha = digest(text.encode())
    old = db.execute(
        "SELECT content_json,content_sha256 FROM documents WHERE kind=? AND logical_key=? AND input_sha256=?",
        (kind, key, input_sha),
    ).fetchone()
    if old is not None:
        if tuple(old) != (text, sha):
            raise ValueError("immutable_result_conflict")
        return sha
    db.execute(
        "INSERT INTO documents VALUES (?,?,?,?,?)", (kind, key, input_sha, text, sha)
    )
    return sha
