#!/usr/bin/env python3
"""Run the single public Structured Outputs canary authorized by M9-r07."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
SOURCE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

import codex_attempt_runtime as runtime  # noqa: E402

from skills._shared.scripts.canary_evidence import (  # noqa: E402
    PublicCanaryRootError,
    require_public_canary_root,
)
from skills._shared.scripts.schema_validation import require_valid_payload  # noqa: E402
from skills._shared.scripts.structured_outputs_validation import (  # noqa: E402
    require_supported_schema,
)

FINAL_DIRECTORY = "schema-canary-v2"
PENDING_DIRECTORY = "schema-canary-v2.pending"
TIMEOUT_SECONDS = 180.0
MAX_LOG_BYTES = 2 * 1024 * 1024
PUBLIC_PROMPT = b"""This is a public synthetic Structured Outputs canary.
Return a JSON object matching the supplied schema. Use exactly these synthetic values:
schema_version=daily_ai_result_v1; status=succeeded; error_code=null;
report_date=2026-01-02; review_date=2026-01-01; sleep_wake_date=2026-01-02;
safety=ready; summary=Synthetic schema canary only.;
bounded_metrics=[{name:synthetic metric,value:1,unit:unit,evidence_ref:1}];
stop_conditions=[Synthetic stop condition.];
evidence_refs=[{raw_file_id:1,sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,claim:Synthetic evidence.}];
recent_trend_sha256=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb;
today_course={}; provider_calls=0.
Do not read files or use tools. Output only the requested JSON.
"""


class CanaryBlocked(ValueError):
    """The canary cannot safely start, finish, or be reused."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode()
        + b"\n"
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _require_root(path: Path) -> Path:
    try:
        return require_public_canary_root(
            path, allowed_entries={FINAL_DIRECTORY, PENDING_DIRECTORY}
        )
    except PublicCanaryRootError as exc:
        raise CanaryBlocked("schema_canary_root_invalid") from exc


def _codex_version(executable: Path) -> str:
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CanaryBlocked("schema_canary_cli_unavailable") from exc
    version = result.stdout.decode("utf-8", errors="strict").strip()
    if not version:
        raise CanaryBlocked("schema_canary_cli_unavailable")
    return version


def _receipt(
    *,
    status: str,
    error_code: str | None,
    timeout_seconds: float,
    codex_version: str,
    executable_sha256: str,
    wire_schema_sha256: str,
    prompt_sha256: str,
    events_raw: bytes,
    stderr_raw: bytes,
    result_raw: bytes | None,
) -> dict[str, Any]:
    return {
        "schema_version": "codex_schema_canary_v1",
        "status": status,
        "error_code": error_code,
        "input_class": "public_synthetic",
        "codex_version": codex_version,
        "codex_executable_sha256": executable_sha256,
        "timeout_seconds": timeout_seconds,
        "command_contract": {
            "ephemeral": True,
            "ignore_user_config": True,
            "sandbox": "read-only",
            "json_events": True,
            "output_schema": "daily_ai_result_codex_v2",
        },
        "wire_schema_sha256": wire_schema_sha256,
        "prompt_sha256": prompt_sha256,
        "events_captured_bytes": len(events_raw),
        "events_sha256": _sha256(events_raw),
        "stderr_captured_bytes": len(stderr_raw),
        "stderr_sha256": _sha256(stderr_raw),
        "result_bytes": len(result_raw) if result_raw is not None else None,
        "result_sha256": _sha256(result_raw) if result_raw is not None else None,
        "provider_calls": 0,
        "external_actions": 0,
    }


def _verify_final(
    final: Path, wire_raw: bytes, executable_sha256: str
) -> dict[str, Any]:
    try:
        metadata = final.lstat()
    except OSError as exc:
        raise CanaryBlocked("schema_canary_evidence_invalid") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or final.is_symlink()
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o777 != 0o700
    ):
        raise CanaryBlocked("schema_canary_evidence_invalid")
    receipt_path = final / "canary-receipt.json"
    try:
        receipt = json.loads(
            runtime._require_owner_file(
                receipt_path, "schema_canary_evidence_invalid"
            ).read_bytes()
        )
        if not isinstance(receipt, dict):
            raise TypeError("canary_receipt_not_object")
        require_valid_payload(receipt, "codex_schema_canary_v1")
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        raise CanaryBlocked("schema_canary_evidence_invalid") from exc
    expected = {"prompt.txt", "events.jsonl", "stderr.log", "canary-receipt.json"}
    if receipt.get("status") == "succeeded":
        expected.add("canary-result.json")
    if {path.name for path in final.iterdir()} != expected:
        raise CanaryBlocked("schema_canary_evidence_invalid")
    if (
        receipt.get("wire_schema_sha256") != _sha256(wire_raw)
        or receipt.get("codex_executable_sha256") != executable_sha256
        or receipt.get("prompt_sha256")
        != _sha256(
            runtime._require_owner_file(
                final / "prompt.txt", "schema_canary_evidence_invalid"
            ).read_bytes()
        )
        or receipt.get("provider_calls") != 0
        or receipt.get("external_actions") != 0
    ):
        raise CanaryBlocked("schema_canary_evidence_invalid")
    for name, size_field, sha_field in (
        ("events.jsonl", "events_captured_bytes", "events_sha256"),
        ("stderr.log", "stderr_captured_bytes", "stderr_sha256"),
    ):
        raw = runtime._require_owner_file(
            final / name, "schema_canary_evidence_invalid"
        ).read_bytes()
        if len(raw) != receipt.get(size_field) or _sha256(raw) != receipt.get(
            sha_field
        ):
            raise CanaryBlocked("schema_canary_evidence_invalid")
    if receipt.get("status") == "succeeded":
        result_raw = runtime._require_owner_file(
            final / "canary-result.json", "schema_canary_evidence_invalid"
        ).read_bytes()
        if len(result_raw) != receipt.get("result_bytes") or _sha256(
            result_raw
        ) != receipt.get("result_sha256"):
            raise CanaryBlocked("schema_canary_evidence_invalid")
        try:
            result = json.loads(result_raw)
            if not isinstance(result, dict):
                raise TypeError("canary_result_not_object")
            require_valid_payload(result, "daily_ai_result_codex_v2")
            require_valid_payload(result, "daily_ai_result_v1")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise CanaryBlocked("schema_canary_evidence_invalid") from exc
    return receipt


def run_schema_canary(
    *,
    root: Path,
    codex_executable: Path | str,
    timeout_seconds: float = TIMEOUT_SECONDS,
    max_log_bytes: int = MAX_LOG_BYTES,
    version_reader: Callable[[Path], str] = _codex_version,
) -> dict[str, Any]:
    if timeout_seconds <= 0 or timeout_seconds > TIMEOUT_SECONDS:
        raise CanaryBlocked("schema_canary_timeout_invalid")
    if max_log_bytes <= 0 or max_log_bytes > MAX_LOG_BYTES:
        raise CanaryBlocked("schema_canary_log_budget_invalid")
    root = _require_root(root)
    executable = Path(os.path.realpath(codex_executable))
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise CanaryBlocked("schema_canary_cli_unavailable")
    executable_sha = _sha256(executable.read_bytes())
    wire_raw = runtime._require_schema(runtime.SCHEMA_V2_PATH).read_bytes()
    try:
        wire_schema = json.loads(wire_raw)
        require_supported_schema(wire_schema)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CanaryBlocked("schema_canary_schema_invalid") from exc
    version = version_reader(executable)
    final = root / FINAL_DIRECTORY
    pending = root / PENDING_DIRECTORY
    if final.exists() or final.is_symlink():
        if pending.exists() or pending.is_symlink():
            raise CanaryBlocked("schema_canary_history_invalid")
        return _verify_final(final, wire_raw, executable_sha)
    if pending.exists() or pending.is_symlink():
        raise CanaryBlocked("schema_canary_incomplete")

    pending.mkdir(mode=0o700)
    runtime._fsync_directory(root)
    runtime._atomic_owner_write(pending / "prompt.txt", PUBLIC_PROMPT)
    events_path = pending / "events.jsonl"
    stderr_path = pending / "stderr.log"
    for path in (events_path, stderr_path):
        descriptor = os.open(
            path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
        )
        os.close(descriptor)
    result_temporary = pending / ".canary-result.pending.json"
    schema_descriptor = runtime._anonymous_read_only_file(pending, wire_raw)
    process_started = time.monotonic()
    try:
        command = [
            str(executable),
            "exec",
            "-C",
            str(pending),
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--ignore-user-config",
            "--output-schema",
            f"/dev/fd/{schema_descriptor}",
            "--json",
            "--output-last-message",
            str(result_temporary),
            "-",
        ]
        outcome = runtime._run_process(
            command,
            PUBLIC_PROMPT,
            pending,
            events_path,
            stderr_path,
            process_started + timeout_seconds,
            max_log_bytes,
            pass_fds=(schema_descriptor,),
        )
    finally:
        os.close(schema_descriptor)
    (
        return_code,
        timed_out,
        overflow,
        launch_failed,
        prompt_complete,
        _elapsed,
        stopped,
    ) = outcome
    if not stopped:
        raise CanaryBlocked("schema_canary_process_stop_unconfirmed")
    events_raw = runtime._ensure_capture(events_path, runtime.EMPTY_EVENTS)
    stderr_raw = runtime._ensure_capture(stderr_path, runtime.EMPTY_STDERR)
    status = "failed"
    error_code: str | None = None
    result_raw: bytes | None = None
    if timed_out:
        error_code = "schema_canary_timeout"
    elif launch_failed:
        error_code = "schema_canary_launch_failed"
    elif overflow:
        error_code = "schema_canary_log_budget_exceeded"
    elif not prompt_complete:
        error_code = "schema_canary_prompt_incomplete"
    elif return_code != 0 or runtime._error_messages(events_raw):
        error_code = "schema_canary_codex_failed"
    elif not result_temporary.is_file() or result_temporary.is_symlink():
        error_code = "schema_canary_result_missing"
    else:
        try:
            metadata = result_temporary.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1
                or metadata.st_size <= 0
                or metadata.st_size > runtime.MAX_RESULT_BYTES
            ):
                raise ValueError("result_file_invalid")
            candidate_raw = result_temporary.read_bytes()
            result = json.loads(candidate_raw)
            if not isinstance(result, dict):
                raise TypeError("canary_result_not_object")
            require_valid_payload(result, "daily_ai_result_codex_v2")
            require_valid_payload(result, "daily_ai_result_v1")
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ):
            error_code = "schema_canary_result_invalid"
        else:
            status = "succeeded"
            result_raw = candidate_raw
    result_temporary.unlink(missing_ok=True)
    receipt = _receipt(
        status=status,
        error_code=error_code,
        timeout_seconds=timeout_seconds,
        codex_version=version,
        executable_sha256=executable_sha,
        wire_schema_sha256=_sha256(wire_raw),
        prompt_sha256=_sha256(PUBLIC_PROMPT),
        events_raw=events_raw,
        stderr_raw=stderr_raw,
        result_raw=result_raw,
    )
    require_valid_payload(receipt, "codex_schema_canary_v1")
    if result_raw is not None:
        runtime._atomic_owner_write(pending / "canary-result.json", result_raw)
    runtime._atomic_owner_write(pending / "canary-receipt.json", _json_bytes(receipt))
    runtime._fsync_directory(pending)
    os.rename(pending, final)
    runtime._fsync_directory(root)
    return _verify_final(final, wire_raw, executable_sha)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    executable = shutil.which("codex")
    if executable is None:
        print(
            json.dumps(
                {"status": "blocked", "error_code": "schema_canary_cli_unavailable"},
                sort_keys=True,
            )
        )
        return 2
    try:
        receipt = run_schema_canary(root=args.root, codex_executable=executable)
    except CanaryBlocked as exc:
        print(json.dumps({"status": "blocked", "error_code": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if receipt.get("status") == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
