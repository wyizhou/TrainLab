# ruff: noqa
"""One manually gated, redacted Garmin v4-a1 acceptance execution.

Importing this file and calling ``main([])`` are inert.  Only the exact
``--execute-once`` argument enters the code that can read a token, create an
isolated store, or make the explicitly reviewed provider requests.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any


WORKTREE = Path("/home/dev/Project/.orchestration/worktrees/n14-garmin-live-v4")
PRODUCTION_ROOT = Path("/home/dev/Project")
MARKER_ROOT = Path(__file__).resolve().parent
TASK_PATH = (
    PRODUCTION_ROOT
    / ".orchestration/runs/trainlab-reliability-20260808-v4/tasks/t14-garmin-live.json"
)
RUN_ROOT = TASK_PATH.parent.parent
APPROVED_TASK_SHA256 = (
    "06ea2b8f58e2ac20257b5859dbcd4d9a739884e70b2c2a290c9b307eb3ecf980"
)
T12_ARTIFACT_ID = "artifact-delivery-t12-integration-tests-v1"
T12_ARTIFACT_CONTRACT = "delivery-t12-integration-tests"
T12_ARTIFACT_VERSION = 1
T12_ARTIFACT_PRODUCER = {
    "node_id": "n12-integration-tests",
    "node_run_id": "run-n12-integration-tests-cf-v4",
    "attempt": 1,
    "agent_instance_id": "codex-root",
}
T12_ARTIFACT_RELATIVE_PATH = "artifact-payloads/delivery-t12-integration-tests.json"
T12_ARTIFACT_DIGEST = (
    "sha256:cdc50b0265c639f2e32dabca34c18c73c8bcdaf8577870017bc9851c66297767"
)
CANONICAL_PLAN_ID = "trainlab-reliability-21"
CANONICAL_PLAN_VERSION = 4
CANONICAL_PLAN_HASH = (
    "sha256:b08614d91555d0c6872d2042e78f964762c931ed4babe97f96b49c96886030b3"
)
CANONICAL_RUN_ID = "trainlab-reliability-20260808-v4"
FROZEN_CONTROL_MANIFEST_SHA256 = (
    "2438a53423139fedde71b478acdafb77a35f7f85013dfc14e8741c6b7e126d9f"
)
MARKER_SHA256 = "8aef04872eadbfe5b24014eb45c7181892ac8d3bcda00d86aadce41ca5119fe2"
FROZEN_SOURCE_MANIFEST_SHA256 = (
    "29711fc5aad4f5b69bd3c415f403797c49eb06e7010fe2f9333dbb7a23479b05"
)
FROZEN_HEAD_SHA1 = "29181f060a66388b6931007618c04c66377a3c30"
FROZEN_INDEX_MAP_SHA256 = (
    "77c4f47e72c431c5f4f4a10afd188397a37cf27c658b53d4ec9b9c63c4fa5c85"
)
DISTRIBUTION_RECORD_SHA256 = (
    "2d640ae8825806901c1fc328b77877a335193a510fd5f0c6654be3bcc45be76b"
)
SOURCE_SHA256 = "1218c122170b2bb701988a7d06fbf8217dc56e3e317b7028e606cc49a4012000"
RECORD_ENTRY_HASHES = {
    "garminconnect/__init__.py": "5d5DJl9MXIQ5z6eh9ejb6qsiebr9FpXoWoxKpiU5JNE",
    "garminconnect/client.py": "5QT1piuoTRYXvoZOZtok7N8B7JsKJ3h7h0-eaTbyoHQ",
}


class LiveGateError(RuntimeError):
    """A redacted stop condition; its text is safe to persist."""


def _sha256_file(path: Path) -> str:
    payload = _stable_file_bytes(path)
    return hashlib.sha256(payload).hexdigest()


def _file_signature(
    info: os.stat_result,
) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        stat.S_IMODE(info.st_mode),
        info.st_uid,
        info.st_gid,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _stable_file_bytes(path: Path, *, maximum_bytes: int = 33_554_432) -> bytes:
    """Read one regular file through a stable directory entry and recheck it."""
    directory_fd = os.open(
        path.parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    descriptor: int | None = None
    try:
        before = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise LiveGateError("stable_file_unsafe")
        descriptor = os.open(
            path.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        opened = os.fstat(descriptor)
        if _file_signature(opened) != _file_signature(before):
            raise LiveGateError("stable_file_replaced")
        chunks: list[bytes] = []
        total = 0
        while block := os.read(descriptor, 65_536):
            total += len(block)
            if total > maximum_bytes:
                raise LiveGateError("stable_file_too_large")
            chunks.append(block)
        after = os.fstat(descriptor)
        named_after = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        if not (
            _file_signature(before)
            == _file_signature(after)
            == _file_signature(named_after)
        ):
            raise LiveGateError("stable_file_changed")
        return b"".join(chunks)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory_fd)


def _driver_source_sha256() -> str:
    text = _stable_file_bytes(Path(__file__)).decode("utf-8")
    normalized = text.replace(
        f'SOURCE_SHA256 = "{SOURCE_SHA256}"', 'SOURCE_SHA256 = "<self>"'
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _source_manifest(root: Path) -> str:
    files: list[tuple[str, str]] = []
    for relative_root in ("src/trainlab", "harness/schemas"):
        base = root / relative_root
        for path in sorted(
            candidate
            for candidate in base.rglob("*")
            if candidate.is_file() and candidate.suffix in {".py", ".json", ".toml"}
        ):
            if path.is_symlink():
                raise LiveGateError("source_symlink")
            files.append((str(path.relative_to(root)), _sha256_file(path)))
    for relative in ("pyproject.toml",):
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise LiveGateError("source_binding_missing")
        files.append((relative, _sha256_file(path)))
    return hashlib.sha256(
        json.dumps(files, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _read_json_object(path: Path, code: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise LiveGateError(code)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        chunks: list[bytes] = []
        total = 0
        while block := os.read(descriptor, 65_536):
            total += len(block)
            if total > 8_388_608:
                raise LiveGateError(code)
            chunks.append(block)
    finally:
        os.close(descriptor)
    try:
        parsed = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveGateError(code) from exc
    if not isinstance(parsed, dict):
        raise LiveGateError(code)
    return parsed


def _control_manifest() -> str:
    relatives = [
        "graph-plan.json",
        "agent-types.json",
        "artifact-registry.json",
        "artifacts/catalog.json",
        *(
            str(path.relative_to(RUN_ROOT))
            for path in sorted((RUN_ROOT / "tasks").glob("*.json"))
        ),
    ]
    if len(relatives) != 29:
        raise LiveGateError("control_manifest_shape")
    files: list[tuple[str, str]] = []
    for relative in relatives:
        path = RUN_ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise LiveGateError("control_manifest_file")
        files.append((relative, _sha256_file(path)))
    return hashlib.sha256(
        json.dumps(files, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _verify_control_plane() -> None:
    """Require the exact approved v4 run as well as frozen control content."""
    if _control_manifest() != FROZEN_CONTROL_MANIFEST_SHA256:
        raise LiveGateError("control_manifest_mismatch")
    graph = _read_json_object(RUN_ROOT / "graph-plan.json", "graph_plan_invalid")
    approval = _read_json_object(RUN_ROOT / "approval.json", "approval_invalid")
    run = _read_json_object(RUN_ROOT / "run.json", "run_invalid")
    state = _read_json_object(RUN_ROOT / "state.json", "state_invalid")
    for document in (graph, approval, run, state):
        if (
            document.get("plan_id") != CANONICAL_PLAN_ID
            or document.get("plan_version") != CANONICAL_PLAN_VERSION
            or document.get("plan_hash") != CANONICAL_PLAN_HASH
        ):
            raise LiveGateError("canonical_plan_mismatch")
    if graph.get("status") != "running" or approval.get("status") != "approved":
        raise LiveGateError("approval_state_mismatch")
    for document in (run, state):
        if (
            document.get("execution_run_id") != CANONICAL_RUN_ID
            or document.get("phase") != "running"
        ):
            raise LiveGateError("run_state_mismatch")


def _verify_t12_edge_input() -> None:
    """Bind the required accepted t12 delivery to its registry bytes and payload."""
    registry = _read_json_object(
        RUN_ROOT / "artifact-registry.json", "artifact_registry_invalid"
    )
    entries = registry.get("artifacts")
    if not isinstance(entries, list):
        raise LiveGateError("artifact_registry_invalid")
    matches = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("artifact_id") == T12_ARTIFACT_ID
    ]
    if len(matches) != 1:
        raise LiveGateError("t12_artifact_missing")
    entry = matches[0]
    if (
        entry.get("artifact_contract_id") != T12_ARTIFACT_CONTRACT
        or entry.get("artifact_version") != T12_ARTIFACT_VERSION
        or entry.get("status") != "accepted"
        or entry.get("producer") != T12_ARTIFACT_PRODUCER
        or entry.get("uri") != T12_ARTIFACT_RELATIVE_PATH
        or entry.get("files") != [T12_ARTIFACT_RELATIVE_PATH]
        or entry.get("digest") != T12_ARTIFACT_DIGEST
    ):
        raise LiveGateError("t12_artifact_binding")
    payload = RUN_ROOT / T12_ARTIFACT_RELATIVE_PATH
    if _sha256_file(payload) != T12_ARTIFACT_DIGEST.removeprefix("sha256:"):
        raise LiveGateError("t12_artifact_digest")


def _git_context(worktree: Path) -> tuple[Path, Path]:
    dot_git = worktree / ".git"
    if dot_git.is_file():
        line = dot_git.read_text(encoding="utf-8").strip()
        if not line.startswith("gitdir: "):
            raise LiveGateError("git_head_invalid")
        git_dir = (worktree / line.removeprefix("gitdir: ")).resolve()
    elif dot_git.is_dir():
        git_dir = dot_git
    else:
        raise LiveGateError("git_head_missing")
    common = git_dir
    common_file = git_dir / "commondir"
    if common_file.exists():
        common = (git_dir / common_file.read_text(encoding="ascii").strip()).resolve()
    return git_dir, common


def _read_worktree_head(worktree: Path) -> tuple[str, Path, Path]:
    git_dir, common = _git_context(worktree)
    head = (git_dir / "HEAD").read_text(encoding="ascii").strip()
    if head.startswith("ref: "):
        reference = head.removeprefix("ref: ")
        ref_file = common / reference
        if ref_file.exists():
            head = ref_file.read_text(encoding="ascii").strip()
        else:
            packed = common / "packed-refs"
            matches = [
                line.split(" ", 1)[0]
                for line in packed.read_text(encoding="ascii").splitlines()
                if line
                and not line.startswith(("#", "^"))
                and line.endswith(f" {reference}")
            ]
            if len(matches) != 1:
                raise LiveGateError("git_head_missing")
            head = matches[0]
    if len(head) != 40 or any(
        character not in "0123456789abcdef" for character in head
    ):
        raise LiveGateError("git_head_invalid")
    return head, git_dir, common


def _index_entries(git_dir: Path) -> dict[str, str]:
    data = (git_dir / "index").read_bytes()
    if data[:4] != b"DIRC" or int.from_bytes(data[4:8], "big") not in {2, 3}:
        raise LiveGateError("git_index_invalid")
    count = int.from_bytes(data[8:12], "big")
    cursor = 12
    entries: dict[str, str] = {}
    for _ in range(count):
        entry_start = cursor
        if cursor + 62 > len(data):
            raise LiveGateError("git_index_invalid")
        object_id = data[cursor + 40 : cursor + 60].hex()
        flags = int.from_bytes(data[cursor + 60 : cursor + 62], "big")
        name_start = cursor + 62 + (2 if flags & 0x4000 else 0)
        name_end = data.find(b"\x00", name_start)
        if name_end < 0:
            raise LiveGateError("git_index_invalid")
        name = data[name_start:name_end].decode("utf-8", errors="strict")
        entries[name] = object_id
        cursor = ((name_end + 1 - entry_start + 7) // 8) * 8 + entry_start
    return entries


def _git_blob_sha1(path: Path) -> str:
    payload = path.read_bytes()
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _verify_head_clean_source(worktree: Path, manifest_paths: list[str]) -> None:
    head, git_dir, _common = _read_worktree_head(worktree)
    if head != FROZEN_HEAD_SHA1:
        raise LiveGateError("worktree_head_mismatch")
    index = _index_entries(git_dir)
    frozen_index = {
        relative: index.get(relative) for relative in sorted(manifest_paths)
    }
    if (
        None in frozen_index.values()
        or hashlib.sha256(
            json.dumps(frozen_index, separators=(",", ":"), sort_keys=True).encode(
                "utf-8"
            )
        ).hexdigest()
        != FROZEN_INDEX_MAP_SHA256
    ):
        raise LiveGateError("worktree_index_mismatch")
    for relative in manifest_paths:
        path = worktree / relative
        expected = index.get(relative)
        if expected is None or _git_blob_sha1(path) != expected:
            raise LiveGateError("worktree_not_head_clean")


def _verify_static_gate() -> None:
    """Bind this driver to the approved plan, source tree and 0.3.9 RECORD."""
    _verify_control_plane()
    _verify_t12_edge_input()
    if _sha256_file(TASK_PATH) != APPROVED_TASK_SHA256:
        raise LiveGateError("approved_plan_mismatch")
    if _driver_source_sha256() != SOURCE_SHA256:
        raise LiveGateError("driver_source_mismatch")
    manifest_paths = [
        str(path.relative_to(WORKTREE))
        for relative_root in ("src/trainlab", "harness/schemas")
        for path in (WORKTREE / relative_root).rglob("*")
        if path.is_file() and path.suffix in {".py", ".json", ".toml"}
    ] + ["pyproject.toml"]
    _verify_head_clean_source(WORKTREE, manifest_paths)
    if _source_manifest(WORKTREE) != FROZEN_SOURCE_MANIFEST_SHA256:
        raise LiveGateError("worktree_not_frozen")
    import base64
    import csv
    import importlib.metadata

    distribution = importlib.metadata.distribution("garminconnect")
    if distribution.version != "0.3.9":
        raise LiveGateError("garminconnect_version")
    record = Path(distribution.locate_file("garminconnect-0.3.9.dist-info/RECORD"))
    if _sha256_file(record) != DISTRIBUTION_RECORD_SHA256:
        raise LiveGateError("garminconnect_record")
    rows = {
        row[0]: row[1]
        for row in csv.reader(record.read_text(encoding="utf-8").splitlines())
    }
    for relative, expected in RECORD_ENTRY_HASHES.items():
        if rows.get(relative) != f"sha256={expected}":
            raise LiveGateError("garminconnect_record_entry")
        actual = _sha256_file(Path(distribution.locate_file(relative)))
        encoded = base64.urlsafe_b64encode(bytes.fromhex(actual)).decode().rstrip("=")
        if encoded != expected:
            raise LiveGateError("garminconnect_record_payload")


def _verify_marker(*, execution_locked: bool = False) -> None:
    root_info = MARKER_ROOT.lstat()
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or stat.S_IMODE(root_info.st_mode) != 0o700
    ):
        raise LiveGateError("marker_root")
    siblings = sorted(MARKER_ROOT.parent.glob("v4-a1-*"))
    if (
        siblings != [MARKER_ROOT]
        or _sha256_file(MARKER_ROOT / "marker.json") != MARKER_SHA256
    ):
        raise LiveGateError("marker_not_unique")
    expected = ["driver.py", "marker.json"]
    if execution_locked:
        expected.append("execution.lock")
    expected.sort()
    if sorted(path.name for path in MARKER_ROOT.iterdir()) != expected:
        raise LiveGateError("marker_not_pristine")
    for name in expected:
        info = (MARKER_ROOT / name).lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise LiveGateError("marker_unsafe")


def _acquire_once_lock() -> int:
    descriptor = os.open(
        MARKER_ROOT / "execution.lock",
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _read_owner_token(path: Path) -> bytes:
    before = path.lstat()
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o600
    ):
        raise LiveGateError("token_file_unsafe")
    payload = _stable_file_bytes(path, maximum_bytes=1_048_576)
    after = path.lstat()
    if _file_signature(before) != _file_signature(after):
        raise LiveGateError("token_file_changed")
    return payload


def _tree_digest(root: Path) -> str:
    root_info = root.lstat()
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise LiveGateError("authority_root_unsafe")
    expected_directories: dict[Path, tuple[int, int, int, int, int, int, int, int]] = {
        root: _file_signature(root_info)
    }
    entries: list[tuple[str, str, str]] = [(".", "directory", "")]
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in sorted((*directories, *files)):
            path = Path(parent) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise LiveGateError("authority_symlink")
            relative = str(path.relative_to(root))
            if stat.S_ISDIR(info.st_mode):
                expected_directories[path] = _file_signature(info)
                entries.append((relative, "directory", ""))
            elif stat.S_ISREG(info.st_mode):
                before = _file_signature(info)
                digest = _sha256_file(path)
                if _file_signature(path.lstat()) != before:
                    raise LiveGateError("authority_file_changed")
                entries.append((relative, "file", digest))
            else:
                raise LiveGateError("authority_entry_unsafe")
    for directory, before in expected_directories.items():
        if _file_signature(directory.lstat()) != before:
            raise LiveGateError("authority_tree_changed")
    return hashlib.sha256(
        json.dumps(entries, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _sqlite_authority_digest(database: Path) -> str:
    """Compare the database and every SQLite sidecar without opening it."""

    def entries_once() -> list[tuple[str, str, str]]:
        entries: list[tuple[str, str, str]] = []
        for suffix in ("", "-wal", "-shm"):
            path = Path(f"{database}{suffix}")
            try:
                info = path.lstat()
            except FileNotFoundError:
                if not suffix:
                    raise LiveGateError("authority_database_missing") from None
                entries.append((suffix or "database", "absent", ""))
                continue
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise LiveGateError("authority_database_unsafe")
            before = _file_signature(info)
            digest = _sha256_file(path)
            if _file_signature(path.lstat()) != before:
                raise LiveGateError("authority_database_changed")
            entries.append((suffix or "database", "file", digest))
        return entries

    entries = entries_once()
    if entries_once() != entries:
        raise LiveGateError("authority_database_changed")
    return hashlib.sha256(
        json.dumps(entries, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _production_quiescence_snapshot(
    config: Any, foundation_tool: Any
) -> tuple[str, str]:
    """Read-only repeated quiescence gate; it is evidence, not an exclusive lease."""
    from trainlab.foundation import FoundationRequest

    lock_paths = (
        config.state_root / "locks" / "garmin.lock",
        config.state_root / "locks" / "foundation.lock",
    )
    for lock_path in lock_paths:
        try:
            info = lock_path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise LiveGateError("production_lock_unsafe")
        raise LiveGateError("production_not_quiescent")
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{config.database_path}{suffix}")
        try:
            payload = _stable_file_bytes(sidecar, maximum_bytes=33_554_432)
        except FileNotFoundError:
            continue
        if suffix == "-wal" and payload:
            raise LiveGateError("production_not_quiescent")
    _require_foundation_ready(
        foundation_tool.execute(
            FoundationRequest(
                "status", "garmin-live-v4-a1-quiescence", "2026-08-08T00:00:00Z"
            )
        ),
        ("ready",),
    )
    return _sqlite_authority_digest(config.database_path), _tree_digest(config.raw_root)


def _isolate_loggers() -> list[tuple[logging.Logger, bool, list[logging.Handler]]]:
    previous: list[tuple[logging.Logger, bool, list[logging.Handler]]] = []
    for name in ("garminconnect", "garminconnect.client", "trainlab.garmin"):
        logger = logging.getLogger(name)
        previous.append((logger, logger.propagate, list(logger.handlers)))
        logger.propagate = False
        logger.handlers = [logging.NullHandler()]
    return previous


class _ProviderGate:
    """Exact low-level 0.3.9 boundary; no facade login or retry is available."""

    def __init__(self, client: Any, minimum_interval_ns: int) -> None:
        self.client = client
        self.minimum_interval_ns = minimum_interval_ns
        self.phase = "preflight"
        self.counts = {
            "refresh_provider_entry_count": 0,
            "credential_replace_count": 0,
            "social_profile_http_count": 0,
            "user_settings_http_count": 0,
            "cached_identity_http_count": 0,
            "password_login_attempt_count": 0,
            "mfa_attempt_count": 0,
            "credential_fallback_attempt_count": 0,
            "library_token_dump_attempt_count": 0,
            "legacy_refresh_attempt_count": 0,
            "implicit_401_refresh_attempt_count": 0,
            "second_refresh_attempt_count": 0,
            "auth_profile_retry_attempt_count": 0,
            "unreviewed_profile_attempt_count": 0,
        }
        self.ledger: list[dict[str, int | str]] = []
        self._previous_data_entry_ns: int | None = None
        required = ("_http_post", "_run_request", "_refresh_session", "dump")
        if any(not callable(getattr(client, name, None)) for name in required):
            raise LiveGateError("pinned_client_shape")
        if not callable(getattr(client._api_session, "request", None)):
            raise LiveGateError("pinned_api_session_shape")
        self._original_http_post = client._http_post
        self._original_run_request = client._run_request
        self._original_request = client._api_session.request
        self._original_dump = client.dump
        self._original_refresh_session = client._refresh_session
        self._original_cs_methods = {
            name: getattr(client.cs, name, None) for name in ("request", "get", "post")
        }
        if any(not callable(method) for method in self._original_cs_methods.values()):
            raise LiveGateError("pinned_sso_session_shape")
        self._original_client_methods = {
            name: getattr(client, name, None)
            for name in (
                "login",
                "resume_login",
                "_complete_mfa",
                "_complete_mfa_widget",
                "_do_mobile_login",
                "_do_portal_web_login",
                "_mobile_login_cffi",
                "_mobile_login_requests",
                "_portal_web_login_cffi",
                "_portal_web_login_requests",
                "_widget_web_login",
            )
        }
        self._original_facade_methods: dict[str, Any] = {}

    def _blocked(self, count_name: str, code: str) -> None:
        self.counts[count_name] += 1
        raise LiveGateError(code)

    def _enter_data(self) -> None:
        while self._previous_data_entry_ns is not None:
            now = time.monotonic_ns()
            remaining = self.minimum_interval_ns - (now - self._previous_data_entry_ns)
            if remaining <= 0:
                break
            time.sleep(remaining / 1_000_000_000)
        stamp = time.monotonic_ns()
        if (
            self._previous_data_entry_ns is not None
            and stamp - self._previous_data_entry_ns < self.minimum_interval_ns
        ):
            raise LiveGateError("data_pacing")
        self._previous_data_entry_ns = stamp
        self.ledger.append(
            {"ordinal": len(self.ledger) + 1, "phase": "data", "monotonic_ns": stamp}
        )

    def install(self, facade: Any) -> None:
        self._facade = facade

        def refresh_post(url: str, *args: Any, **kwargs: Any) -> Any:
            if self.phase != "refresh" or url != self.client._di_token_url:
                self._blocked("legacy_refresh_attempt_count", "refresh_path_blocked")
            if self.counts["refresh_provider_entry_count"]:
                self._blocked("second_refresh_attempt_count", "second_refresh_blocked")
            self.counts["refresh_provider_entry_count"] += 1
            return self._original_http_post(url, *args, **kwargs)

        def guarded_request(method: str, url: str, *args: Any, **kwargs: Any) -> Any:
            social = f"{self.client._connectapi}/userprofile-service/socialProfile"
            settings = f"{self.client._connectapi}/userprofile-service/userprofile/user-settings"
            if self.phase == "profiles":
                if method != "GET" or url not in {social, settings}:
                    self._blocked(
                        "unreviewed_profile_attempt_count", "profile_path_blocked"
                    )
                count_name = (
                    "social_profile_http_count"
                    if url == social
                    else "user_settings_http_count"
                )
                if self.counts[count_name]:
                    self._blocked(
                        "auth_profile_retry_attempt_count", "profile_retry_blocked"
                    )
                if url == settings and not self.counts["social_profile_http_count"]:
                    self._blocked(
                        "unreviewed_profile_attempt_count", "profile_order_blocked"
                    )
                self.counts[count_name] += 1
            elif self.phase == "data":
                if method not in {"GET", "POST", "PUT", "DELETE"} or not url.startswith(
                    f"{self.client._connectapi}/"
                ):
                    self._blocked(
                        "unreviewed_profile_attempt_count", "data_path_blocked"
                    )
                self._enter_data()
            else:
                self._blocked(
                    "unreviewed_profile_attempt_count", "provider_phase_blocked"
                )
            response = self._original_request(method, url, *args, **kwargs)
            if getattr(response, "status_code", None) == 401:
                self._blocked("implicit_401_refresh_attempt_count", "http_401_blocked")
            return response

        def guarded_run_request(
            method: str, path: str, *args: Any, **kwargs: Any
        ) -> Any:
            social_path = "/userprofile-service/socialProfile"
            settings_path = "/userprofile-service/userprofile/user-settings"
            normalized = f"/{path.lstrip('/')}"
            if self.phase == "profiles" and (
                method != "GET" or normalized not in {social_path, settings_path}
            ):
                self._blocked("unreviewed_profile_attempt_count", "run_request_blocked")
            if self.phase not in {"profiles", "data"}:
                self._blocked(
                    "unreviewed_profile_attempt_count", "run_request_phase_blocked"
                )
            return self._original_run_request(method, path, *args, **kwargs)

        def blocked_refresh() -> None:
            self._blocked("legacy_refresh_attempt_count", "implicit_refresh_blocked")

        def blocked_sso(*args: Any, **kwargs: Any) -> Any:
            self._blocked("credential_fallback_attempt_count", "sso_blocked")

        def blocked_login(*args: Any, **kwargs: Any) -> Any:
            self._blocked("password_login_attempt_count", "login_blocked")

        def blocked_mfa(*args: Any, **kwargs: Any) -> Any:
            self._blocked("mfa_attempt_count", "mfa_blocked")

        def blocked_dump(*args: Any, **kwargs: Any) -> Any:
            self._blocked("library_token_dump_attempt_count", "token_dump_blocked")

        self.client._http_post = refresh_post
        self.client._run_request = guarded_run_request
        self.client._api_session.request = guarded_request
        self.client.dump = blocked_dump
        for name in self._original_cs_methods:
            setattr(self.client.cs, name, blocked_sso)
        self.client._refresh_session = blocked_refresh
        for name, original in self._original_client_methods.items():
            if callable(original):
                blocked = (
                    blocked_mfa
                    if "mfa" in name or name == "resume_login"
                    else blocked_login
                )
                setattr(self.client, name, blocked)
        for name in ("login", "_load_profile_and_settings", "get_full_name"):
            original = getattr(facade, name, None)
            if callable(original):
                self._original_facade_methods[name] = original
                setattr(facade, name, blocked_login)

    def restore(self) -> None:
        self.client._http_post = self._original_http_post
        self.client._run_request = self._original_run_request
        self.client._api_session.request = self._original_request
        self.client.dump = self._original_dump
        for name, original in self._original_cs_methods.items():
            setattr(self.client.cs, name, original)
        self.client._refresh_session = self._original_refresh_session
        for name, original in self._original_client_methods.items():
            if callable(original):
                setattr(self.client, name, original)
        for name, original in self._original_facade_methods.items():
            setattr(self._facade, name, original)


def _intervals(ledger: list[dict[str, int | str]]) -> list[int]:
    return [
        int(ledger[index]["monotonic_ns"]) - int(ledger[index - 1]["monotonic_ns"])
        for index in range(1, len(ledger))
    ]


def _request_digest(request: Any) -> str:
    fields = {
        "mode": request.mode,
        "from": request.health_from_local_date,
        "through": request.through_local_date,
        "snapshot": request.snapshot_local_date,
        "resources": list(request.resource_kinds),
    }
    return hashlib.sha256(
        json.dumps(fields, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _checkpoint(
    tool: Any,
    request: Any,
    receipt: Any,
    ordinal: int,
    previous_digest: str,
    prior_count: int,
    minimum_interval_ns: int,
    ledger: list[dict[str, int | str]],
) -> dict[str, Any]:
    count = len(ledger)
    document: dict[str, Any] = {
        "schema_version": "1",
        "document_kind": "garmin_live_acceptance_checkpoint",
        "timezone": "Asia/Hong_Kong",
        "operation": {
            "ordinal": ordinal,
            "mode": request.mode,
            "status": receipt.status,
            "request_semantic_sha256": _request_digest(request),
            "requested_local_dates": receipt.requested_range,
            "effective_local_dates": receipt.effective_range,
            "receipt_schema_valid": True,
            "receipt_counts": receipt.counts,
            "provider_entry_ordinals": {
                "first": prior_count + 1 if count > prior_count else None,
                "last": count if count > prior_count else None,
            },
        },
        "prior_provider_entry_count": prior_count,
        "provider_entry_count": count,
        "configured_minimum_interval_ns": minimum_interval_ns,
        "adjacent_controlled_provider_intervals_ns": _intervals(ledger),
        "controlled_provider_entry_ledger": ledger,
        "previous_checkpoint_sha256": previous_digest,
        "checkpoint_sha256": "0" * 64,
    }
    document["checkpoint_sha256"] = tool._canonical_live_acceptance_sha256(document)
    tool._validate_live_acceptance_document(document)
    return document


def _stop_document(
    tool: Any,
    failure_stage: str,
    failure_outcome: str,
    auth_refresh: dict[str, Any],
    checkpoints: list[dict[str, Any]],
    minimum_interval_ns: int,
    ledger: list[dict[str, int | str]],
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": "1",
        "document_kind": "garmin_live_acceptance_stop",
        "timezone": "Asia/Hong_Kong",
        "failure_stage": failure_stage,
        "failure_evidence": {
            "outcome": failure_outcome,
            "last_checkpoint_preserved": True,
        },
        "auth_refresh": auth_refresh,
        "checkpoints": checkpoints,
        "provider_entry_count": len(ledger),
        "configured_minimum_interval_ns": minimum_interval_ns,
        "adjacent_controlled_provider_intervals_ns": _intervals(ledger),
        "controlled_provider_entry_ledger": ledger,
        "stop_sha256": "0" * 64,
    }
    document["stop_sha256"] = tool._canonical_live_acceptance_sha256(document)
    tool._validate_live_acceptance_document(document)
    return document


def _read_json_nofollow(path: Path) -> dict[str, Any]:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise LiveGateError("receipt_unsafe")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        chunks: list[bytes] = []
        total = 0
        while block := os.read(descriptor, 65_536):
            total += len(block)
            if total > 1_048_576:
                raise LiveGateError("receipt_too_large")
            chunks.append(block)
    finally:
        os.close(descriptor)
    try:
        parsed = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveGateError("receipt_invalid") from exc
    if not isinstance(parsed, dict):
        raise LiveGateError("receipt_invalid")
    return parsed


def _resolved_auth_evidence(tool: Any, auth: dict[str, Any]) -> dict[str, Any]:
    """Re-read durable redacted receipts rather than trusting return values."""
    prepared = _read_json_nofollow(MARKER_ROOT / "auth-prepared.json")
    checkpoint = _read_json_nofollow(MARKER_ROOT / "auth-rotation-checkpoint.json")
    final = _read_json_nofollow(MARKER_ROOT / "auth-final.json")
    for document, status in (
        (prepared, "prepared"),
        (checkpoint, "rotation_checkpoint"),
        (final, "succeeded"),
    ):
        tool._validate_live_acceptance_document(document)
        if document["status"] != status:
            raise LiveGateError("auth_receipt_status")
    if (
        checkpoint["previous_auth_receipt_sha256"]
        != prepared["auth_refresh_receipt_sha256"]
        or final["previous_auth_receipt_sha256"]
        != checkpoint["auth_refresh_receipt_sha256"]
        or auth["rotation_checkpoint"]["auth_refresh_receipt_sha256"]
        != checkpoint["auth_refresh_receipt_sha256"]
        or auth["final_receipt"]["auth_refresh_receipt_sha256"]
        != final["auth_refresh_receipt_sha256"]
    ):
        raise LiveGateError("auth_receipt_chain")
    progress = {name: dict(state) for name, state in final["progress"].items()}
    final_receipt_phase = progress["final_receipt"]
    if not (
        final_receipt_phase["attempted"]
        and final_receipt_phase["entered"]
        and not final_receipt_phase["completed"]
    ):
        raise LiveGateError("auth_final_receipt_progress")
    # A receipt cannot attest its own completed fsync before that fsync.  The
    # no-follow re-read above is the durable proof, so only the result-facing
    # projection advances this final persistence fact.
    final_receipt_phase["completed"] = True
    if auth["progress"] != progress:
        raise LiveGateError("auth_progress_recheck")
    return {
        "auth_rotation_checkpoint_sha256": checkpoint["auth_refresh_receipt_sha256"],
        "auth_refresh_receipt_sha256": final["auth_refresh_receipt_sha256"],
        "counts": final["counts"],
        "ordering": final["ordering"],
        "credential_authority": final["credential_authority"],
        "progress": progress,
    }


def _require_foundation_ready(receipt: Any, expected_statuses: tuple[str, ...]) -> None:
    if (
        getattr(receipt, "status", None) not in expected_statuses
        or getattr(receipt, "ready", None) is not True
    ):
        raise LiveGateError("foundation_not_ready")


def _require_sync_receipt(tool: Any, receipt: Any) -> Any:
    """Invoke TrainLab's real SyncReceipt schema validator before checkpointing."""
    validator = getattr(tool, "_validated_receipt", None)
    if not callable(validator):
        raise LiveGateError("sync_receipt_validator_missing")
    try:
        validated = validator(receipt)
    except Exception as exc:
        raise LiveGateError("sync_receipt_invalid") from exc
    if validated is not receipt:
        raise LiveGateError("sync_receipt_identity")
    return receipt


def _closed_adapter_invoke(
    error_mapper: Any, method: Any, *args: Any, **kwargs: Any
) -> Any:
    """Keep a gate failure outside generic transport exception translation."""
    try:
        return method(*args, **kwargs)
    except LiveGateError:
        raise
    except Exception as exc:
        raise error_mapper(exc) from exc


def _isolated_revision_snapshot(config: Any) -> dict[str, Any]:
    """Read only isolated metadata; returned raw identifiers never persist."""
    import sqlite3

    database_uri = config.database_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(database_uri, uri=True)
    try:
        raw_ids = {
            row[0]
            for row in connection.execute(
                "SELECT id FROM raw_objects WHERE provider='garmin'"
            )
        }
        history: dict[
            tuple[str, str, str], list[tuple[int, int, str, int | None, int]]
        ] = {}
        for row in connection.execute(
            """SELECT id,provider,resource_kind,provider_object_id,revision_no,
                      payload_hash,raw_object_id,is_current
                 FROM source_revisions WHERE provider='garmin'
                 ORDER BY provider,resource_kind,provider_object_id,revision_no,id"""
        ):
            key = (row[1], row[2], row[3])
            history.setdefault(key, []).append((row[0], row[4], row[5], row[6], row[7]))
    finally:
        connection.close()
    current = {
        key: [entry for entry in entries if entry[4] == 1]
        for key, entries in history.items()
    }
    return {
        "raw_ids": raw_ids,
        "history": history,
        "current": current,
        "raw_tree_digest": _tree_digest(config.raw_root),
    }


def _drift_evidence(first: dict[str, Any], second: dict[str, Any]) -> dict[str, int]:
    """Derive only count-level stable/change facts from isolated metadata."""
    stable = 0
    changed: list[tuple[str, str, str]] = []
    stable_violations = 0
    revision_violations = 0
    provenance_violations = 0
    first_current = first["current"]
    second_current = second["current"]
    for key in sorted(set(first_current) | set(second_current)):
        before = first_current.get(key, [])
        after = second_current.get(key, [])
        if len(before) == len(after) == 1 and before[0][2] == after[0][2]:
            stable += 1
            if first["history"].get(key, []) != second["history"].get(key, []):
                stable_violations += 1
            continue
        changed.append(key)
        before_history = {entry[0]: entry for entry in first["history"].get(key, [])}
        after_history = {entry[0]: entry for entry in second["history"].get(key, [])}
        new_entries = [
            entry
            for entry_id, entry in after_history.items()
            if entry_id not in before_history
        ]
        if len(before) != 1 or len(after) != 1 or len(new_entries) != 1:
            revision_violations += 1
            continue
        old_current = before[0]
        new_current = after[0]
        new_revision = new_entries[0]
        old_after = after_history.get(old_current[0])
        if (
            old_after is None
            or old_after[:4] != old_current[:4]
            or old_after[4] != 0
            or new_current != new_revision
            or new_revision[1] != old_current[1] + 1
            or new_revision[4] != 1
        ):
            revision_violations += 1
        if (
            new_revision[3] is None
            or new_revision[3] not in second["raw_ids"] - first["raw_ids"]
        ):
            provenance_violations += 1
    new_raw_ids = second["raw_ids"] - first["raw_ids"]
    if len(new_raw_ids) != len(changed):
        revision_violations += 1
    if bool(changed) == (first["raw_tree_digest"] == second["raw_tree_digest"]):
        provenance_violations += 1
    return {
        "stable_repeat_count": stable,
        "changed_payload_count": len(changed),
        "stable_repeat_violation_count": stable_violations,
        "changed_revision_violation_count": revision_violations,
        "changed_current_provenance_violation_count": provenance_violations,
    }


def _observed_partitions(
    checkpoints: list[dict[str, Any]],
    ledger: list[dict[str, int | str]],
    minimum_interval_ns: int,
    drift: dict[str, int],
) -> dict[str, list[str]]:
    idempotence = [
        "incremental-through-2026-08-06",
        "snapshot-2026-08-07",
        "audit-only-2026-08-06",
    ]
    if drift["stable_repeat_count"]:
        idempotence.append("stable-repeat-no-new-object")
    if drift["changed_payload_count"]:
        idempotence.append("provider-drift-one-distinct-revision")
    if any(
        checkpoint["operation"]["receipt_counts"]["empty"] for checkpoint in checkpoints
    ):
        idempotence.append("empty-delta")
    if any(
        checkpoint["operation"]["status"] == "deferred" for checkpoint in checkpoints
    ):
        idempotence.append("provider-deferred")
    intervals = _intervals(ledger)
    pacing = ["first-call"] if ledger else []
    if any(interval == minimum_interval_ns for interval in intervals):
        pacing.append("exact-minimum")
    durability = (
        ["completed-operation-integer-nanosecond-intervals"] if checkpoints else []
    )
    return {
        "idempotence": idempotence,
        "pacing": pacing,
        "durability": durability,
    }


def _isolated_config(marker_root: Path, production_config: Any) -> Any:
    from dataclasses import replace

    isolated = marker_root / "isolated"
    if isolated.exists():
        raise LiveGateError("isolated_root_exists")
    isolated.mkdir(mode=0o700)
    return replace(
        production_config,
        database_path=isolated / "data.db",
        raw_root=isolated / "raw",
        state_root=isolated / "state",
        max_attempts=1,
    )


def _execute_once() -> None:
    """Run the sole authorized path.  This function is never called implicitly."""
    _verify_static_gate()
    _verify_marker()
    lock = _acquire_once_lock()
    gate: _ProviderGate | None = None
    logging_state: list[tuple[logging.Logger, bool, list[logging.Handler]]] = []
    try:
        # Rebind every hash-then-use input after the exclusive attempt lock.
        _verify_static_gate()
        _verify_marker(execution_locked=True)
        sys.path.insert(0, str(WORKTREE / "src"))
        from trainlab.foundation import (
            FoundationConfig,
            FoundationRequest,
            FoundationTool,
        )
        from trainlab.garmin import GarminCollectionTool, SyncRequest
        from trainlab.garmin_client import GarminConnectTransport
        from trainlab.garmin_config import load_garmin_config
        from garminconnect import Garmin

        production_config = load_garmin_config(PRODUCTION_ROOT)
        production_foundation = FoundationConfig.load(PRODUCTION_ROOT)
        production_foundation_tool = FoundationTool(production_foundation)
        token_path = (
            production_config.state_root / "secrets" / "garmin" / "garmin_tokens.json"
        )
        (
            production_database_before,
            production_raw_before,
        ) = _production_quiescence_snapshot(
            production_config, production_foundation_tool
        )
        facade = Garmin(
            None,
            None,
            is_cn=production_config.region == "cn",
            retry_attempts=0,
        )
        low = facade.client
        gate = _ProviderGate(low, production_config.request_min_interval_ms * 1_000_000)
        gate.install(facade)
        logging_state = _isolate_loggers()
        tool = GarminCollectionTool(production_config)
        auth_evidence: dict[str, Any] | None = None
        checkpoints: list[dict[str, Any]] = []
        stop_written = False

        def persist_stop(stage: str, outcome: str) -> None:
            nonlocal stop_written
            if auth_evidence is None or stop_written:
                return
            stop = _stop_document(
                tool,
                stage,
                outcome,
                auth_evidence,
                checkpoints,
                gate.minimum_interval_ns,
                list(gate.ledger),
            )
            try:
                tool._persist_live_acceptance_document(MARKER_ROOT / "stop.json", stop)
            except Exception:
                raise LiveGateError("stop_receipt_persist_failed") from None
            stop_written = True

        try:

            def load_token_state() -> dict[str, bool]:
                low._clear_auth_state()
                low.loads(_read_owner_token(token_path).decode("utf-8"))
                return {
                    "proactive_expiring": bool(low._token_expires_soon()),
                    "has_di_refresh_credential": bool(low.di_refresh_token),
                    "has_di_client_identity": bool(low.di_client_id),
                }

            cached_identity = [""]

            def social_profile() -> Any:
                gate.phase = "profiles"
                return low.connectapi("/userprofile-service/socialProfile")

            def cache_identity(payload: Any) -> None:
                if not isinstance(payload, dict) or not isinstance(
                    payload.get("fullName"), str
                ):
                    raise LiveGateError("cached_identity_missing")
                cached_identity[0] = payload["fullName"]

            def user_settings() -> Any:
                return low.connectapi("/userprofile-service/userprofile/user-settings")

            gate.phase = "refresh"
            auth = tool._run_verified_live_auth_refresh(
                token_path=token_path,
                load_token_state=load_token_state,
                refresh_di_token=low._refresh_di_token,
                serialize_refreshed=lambda: low.dumps().encode("utf-8"),
                prepared_destination=MARKER_ROOT / "auth-prepared.json",
                checkpoint_destination=MARKER_ROOT / "auth-rotation-checkpoint.json",
                final_destination=MARKER_ROOT / "auth-final.json",
                stop_destination=MARKER_ROOT / "auth-stop.json",
                observed_counts=lambda: gate.counts,
                social_profile=social_profile,
                cache_identity=cache_identity,
                user_settings=user_settings,
            )
            gate.counts["credential_replace_count"] = auth["counts"][
                "credential_replace_count"
            ]
            auth_evidence = _resolved_auth_evidence(tool, auth)
            if gate.counts != auth_evidence["counts"]:
                persist_stop("authority_recheck", "post-provider-local")
                raise LiveGateError("auth_count_recheck")
            isolated_config = _isolated_config(MARKER_ROOT, production_config)
            isolated_root = isolated_config.database_path.parent
            foundation = FoundationConfig(
                isolated_root,
                isolated_config.database_path,
                isolated_config.raw_root,
                isolated_config.state_root,
                isolated_config.state_root / "ready.json",
                isolated_config.state_root / "locks" / "foundation.lock",
                MARKER_ROOT,
            )
            foundation_tool = FoundationTool(foundation)
            try:
                _require_foundation_ready(
                    foundation_tool.execute(
                        FoundationRequest(
                            "init", "garmin-live-v4-a1", "2026-08-08T00:00:00Z"
                        )
                    ),
                    ("initialized", "already_initialized"),
                )
                _require_foundation_ready(
                    foundation_tool.execute(
                        FoundationRequest(
                            "status",
                            "garmin-live-v4-a1-status",
                            "2026-08-08T00:00:00Z",
                        )
                    ),
                    ("ready",),
                )
            except Exception:
                persist_stop("foundation", "post-provider-local")
                raise

            class ClosedAdapter:
                fetch_health = GarminConnectTransport.fetch_health
                fetch_range = GarminConnectTransport.fetch_range
                fetch_account = GarminConnectTransport.fetch_account
                activity_count = GarminConnectTransport.activity_count
                activity_page = GarminConnectTransport.activity_page
                list_activities = GarminConnectTransport.list_activities
                activity_summary = GarminConnectTransport.activity_summary
                activity_original = GarminConnectTransport.activity_original
                activity_extra = GarminConnectTransport.activity_extra

                def __init__(self, client: Any, identity: str) -> None:
                    self.client = client
                    self._identity = identity

                def _invoke(self, method: Any, *args: Any, **kwargs: Any) -> Any:
                    return _closed_adapter_invoke(
                        GarminConnectTransport._error, method, *args, **kwargs
                    )

                def login(self) -> None:
                    return None

                def identity(self) -> str:
                    return self._identity

            collector = GarminCollectionTool(
                isolated_config, ClosedAdapter(facade, cached_identity[0])
            )
            collector._live_acceptance_no_retry = True
            requests = (
                SyncRequest("auth", invocation_id="v4-a1-auth"),
                SyncRequest(
                    "incremental",
                    through_local_date="2026-08-06",
                    invocation_id="v4-a1-incremental-1",
                ),
                SyncRequest(
                    "incremental",
                    through_local_date="2026-08-06",
                    invocation_id="v4-a1-incremental-2",
                ),
                SyncRequest(
                    "snapshot",
                    snapshot_local_date="2026-08-07",
                    invocation_id="v4-a1-snapshot",
                ),
                SyncRequest(
                    "audit",
                    health_from_local_date="2026-08-06",
                    through_local_date="2026-08-06",
                    invocation_id="v4-a1-audit",
                ),
            )
            gate.phase = "data"
            previous = "0" * 64
            prior_count = 0
            first_incremental_snapshot: dict[str, Any] | None = None
            second_incremental_snapshot: dict[str, Any] | None = None
            for ordinal, request in enumerate(requests, start=1):
                entries_before = len(gate.ledger)
                try:
                    receipt = _require_sync_receipt(
                        collector, collector.execute(request)
                    )
                except Exception:
                    persist_stop(
                        "data",
                        "pre-provider"
                        if len(gate.ledger) == entries_before
                        else "ambiguous",
                    )
                    raise
                try:
                    checkpoint = _checkpoint(
                        collector,
                        request,
                        receipt,
                        ordinal,
                        previous,
                        prior_count,
                        gate.minimum_interval_ns,
                        list(gate.ledger),
                    )
                    collector._persist_live_acceptance_document(
                        MARKER_ROOT / f"checkpoint-{ordinal}.json", checkpoint
                    )
                except Exception:
                    persist_stop("data", "post-provider-local")
                    raise
                checkpoints.append(checkpoint)
                previous = checkpoint["checkpoint_sha256"]
                prior_count = len(gate.ledger)
                if receipt.status != "succeeded":
                    persist_stop(
                        "data",
                        "ambiguous"
                        if len(gate.ledger) > entries_before
                        else "post-provider-local",
                    )
                    raise LiveGateError("data_operation_stopped")
                try:
                    if ordinal == 2:
                        first_incremental_snapshot = _isolated_revision_snapshot(
                            isolated_config
                        )
                    elif ordinal == 3:
                        second_incremental_snapshot = _isolated_revision_snapshot(
                            isolated_config
                        )
                except Exception:
                    persist_stop("data", "post-provider-local")
                    raise
            try:
                if (
                    first_incremental_snapshot is None
                    or second_incremental_snapshot is None
                ):
                    raise LiveGateError("repeat_snapshot_missing")
                drift = _drift_evidence(
                    first_incremental_snapshot, second_incremental_snapshot
                )
                if any(
                    drift[name]
                    for name in (
                        "stable_repeat_violation_count",
                        "changed_revision_violation_count",
                        "changed_current_provenance_violation_count",
                    )
                ):
                    raise LiveGateError("drift_evidence_invalid")
                (
                    production_database_after,
                    production_raw_after,
                ) = _production_quiescence_snapshot(
                    production_config, production_foundation_tool
                )
                authority_unchanged = {
                    "production_database": (
                        production_database_before == production_database_after
                    ),
                    "production_raw_root": production_raw_before
                    == production_raw_after,
                    "credential_permissions": all(
                        auth_evidence["credential_authority"].values()
                    ),
                }
                if not all(authority_unchanged.values()):
                    raise LiveGateError("production_authority_changed")
                if gate.counts != auth_evidence["counts"]:
                    raise LiveGateError("post_data_auth_count_changed")
            except Exception:
                persist_stop("data", "post-provider-local")
                raise
            result: dict[str, Any] = {
                "schema_version": "1",
                "document_kind": "garmin_live_acceptance_result",
                "timezone": "Asia/Hong_Kong",
                "checkpoints": checkpoints,
                "provider_entry_count": len(gate.ledger),
                "configured_minimum_interval_ns": gate.minimum_interval_ns,
                "adjacent_controlled_provider_intervals_ns": _intervals(gate.ledger),
                "controlled_provider_entry_ledger": gate.ledger,
                "auth_refresh": auth_evidence,
                "authority_unchanged": authority_unchanged,
                "token_dump_attempt_count": gate.counts[
                    "library_token_dump_attempt_count"
                ],
                "drift_evidence": drift,
                "failure_evidence": {
                    "outcome": "none",
                    "last_checkpoint_preserved": None,
                },
                "final_checkpoint_sha256": previous,
                "result_sha256": "0" * 64,
                "partition_coverage": _observed_partitions(
                    checkpoints, list(gate.ledger), gate.minimum_interval_ns, drift
                ),
            }
            try:
                result["result_sha256"] = collector._canonical_live_acceptance_sha256(
                    result
                )
                collector._persist_live_acceptance_document(
                    MARKER_ROOT / "result.json", result
                )
            except Exception:
                persist_stop("data", "post-provider-local")
                raise
        except Exception:
            persist_stop("data", "post-provider-local")
            raise
    finally:
        if gate is not None:
            gate.restore()
        for logger, propagate, handlers in logging_state:
            logger.propagate = propagate
            logger.handlers = handlers
        os.close(lock)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        return 0
    if arguments != ["--execute-once"]:
        return 2
    try:
        _execute_once()
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
