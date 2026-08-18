"""Single-writer state machine for the one approved M9 Codex attempt."""

from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterator, NamedTuple

from skills._shared.scripts.canary_evidence import (
    PublicCanaryRootError,
    require_public_canary_root,
)
from skills._shared.scripts.schema_validation import require_valid_payload
from skills._shared.scripts.structured_outputs_validation import (
    require_supported_schema,
)

SOURCE_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = (
    SOURCE_ROOT / "skills/_shared/schemas/daily_ai_result_codex_v1.schema.json"
)
SCHEMA_V2_PATH = (
    SOURCE_ROOT / "skills/_shared/schemas/daily_ai_result_codex_v2.schema.json"
)
BUSINESS_SCHEMA_PATH = (
    SOURCE_ROOT / "skills/_shared/schemas/daily_ai_result_v1.schema.json"
)
ATTEMPT_NUMBER = 3
PENDING_DIRECTORY = "ai-attempt-3.pending"
ATTEMPT_DIRECTORY = "ai-attempt-3"
TIMEOUT_SECONDS = 180.0
MAX_LOG_BYTES = 2 * 1024 * 1024
MAX_RESULT_BYTES = 1024 * 1024
EXPECTED_RUN_ROOT_NAME = "daily-20260817"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EMPTY_EVENTS = b'{"type":"trainlab.capture.empty_stdout"}\n'
EMPTY_STDERR = b"NO_STDERR\n"


class AttemptPolicy(NamedTuple):
    number: int
    pending_directory: str
    attempt_directory: str
    wire_schema_path: Path
    wire_schema_name: str
    intent_schema_name: str
    receipt_schema_name: str
    history_before: frozenset[str]
    history_after: frozenset[str]


ATTEMPT3_POLICY = AttemptPolicy(
    number=3,
    pending_directory=PENDING_DIRECTORY,
    attempt_directory=ATTEMPT_DIRECTORY,
    wire_schema_path=SCHEMA_PATH,
    wire_schema_name="daily_ai_result_codex_v1",
    intent_schema_name="codex_ai_attempt_intent_v1",
    receipt_schema_name="codex_ai_attempt_v1",
    history_before=frozenset({"ai-attempt-2"}),
    history_after=frozenset({"ai-attempt-2", "ai-attempt-3"}),
)
ATTEMPT4_POLICY = AttemptPolicy(
    number=4,
    pending_directory="ai-attempt-4.pending",
    attempt_directory="ai-attempt-4",
    wire_schema_path=SCHEMA_V2_PATH,
    wire_schema_name="daily_ai_result_codex_v2",
    intent_schema_name="codex_ai_attempt_intent_v2",
    receipt_schema_name="codex_ai_attempt_v2",
    history_before=frozenset({"ai-attempt-2", "ai-attempt-3"}),
    history_after=frozenset({"ai-attempt-2", "ai-attempt-3", "ai-attempt-4"}),
)


class RunnerBlocked(ValueError):
    """The frozen attempt cannot safely start, finish, or be repeated."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode()
        + b"\n"
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_hash(value: str, field: str) -> None:
    if SHA256_PATTERN.fullmatch(value) is None:
        raise RunnerBlocked(f"{field}_invalid")


def _require_directory(path: Path, error_code: str) -> Path:
    absolute = Path(os.path.abspath(path))
    try:
        metadata = absolute.lstat()
    except OSError as exc:
        raise RunnerBlocked(error_code) from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or absolute.is_symlink()
        or absolute.resolve(strict=True) != absolute
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o777 != 0o700
        or metadata.st_nlink < 1
    ):
        raise RunnerBlocked(error_code)
    return absolute


def _require_owner_file(path: Path, error_code: str) -> Path:
    absolute = Path(os.path.abspath(path))
    try:
        metadata = absolute.lstat()
    except OSError as exc:
        raise RunnerBlocked(error_code) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or absolute.is_symlink()
        or absolute.resolve(strict=True) != absolute
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o777 != 0o600
        or metadata.st_nlink != 1
        or metadata.st_size <= 0
    ):
        raise RunnerBlocked(error_code)
    return absolute


def _require_schema(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    try:
        metadata = absolute.lstat()
    except OSError as exc:
        raise RunnerBlocked("frozen_schema_unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or absolute.is_symlink()
        or absolute.resolve(strict=True) != absolute
        or metadata.st_nlink != 1
        or metadata.st_size <= 0
    ):
        raise RunnerBlocked("frozen_schema_unavailable")
    return absolute


@contextmanager
def _run_root_lock(run_root: Path) -> Iterator[Path]:
    root = _require_directory(run_root, "ai_run_root_invalid")
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RunnerBlocked("ai_attempt_lock_unavailable") from exc
        yield root
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _atomic_owner_write(path: Path, payload: bytes) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _anonymous_read_only_file(directory: Path, payload: bytes) -> int:
    writable, name = tempfile.mkstemp(prefix=".schema.", dir=directory)
    temporary = Path(name)
    readable = -1
    try:
        os.fchmod(writable, 0o400)
        remaining = memoryview(payload)
        while remaining:
            written = os.write(writable, remaining)
            if written <= 0:
                raise OSError("anonymous_schema_write_failed")
            remaining = remaining[written:]
        os.fsync(writable)
        readable = os.open(temporary, os.O_RDONLY | os.O_NOFOLLOW)
        metadata = os.fstat(readable)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o777 != 0o400:
            raise OSError("anonymous_schema_identity_mismatch")
        temporary.unlink()
        _fsync_directory(directory)
        os.close(writable)
        writable = -1
        return readable
    except Exception:
        if readable >= 0:
            os.close(readable)
        temporary.unlink(missing_ok=True)
        raise
    finally:
        if writable >= 0:
            os.close(writable)


def _read_prior_attempt(run_root: Path) -> tuple[dict[str, Any], str]:
    prior = _require_directory(
        run_root / "ai-attempt-2", "prior_attempt_evidence_invalid"
    )
    allowed = {"attempt-receipt.json", "events.jsonl", "stderr.log"}
    if {path.name for path in prior.iterdir()} != allowed:
        raise RunnerBlocked("prior_attempt_evidence_invalid")
    receipt_path = _require_owner_file(
        prior / "attempt-receipt.json", "prior_attempt_evidence_invalid"
    )
    try:
        receipt_raw = receipt_path.read_bytes()
        receipt = json.loads(receipt_raw)
        if not isinstance(receipt, dict):
            raise TypeError("prior_attempt_receipt_not_object")
        require_valid_payload(receipt, "codex_ai_attempt_v1")
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        raise RunnerBlocked("prior_attempt_evidence_invalid") from exc
    if (
        receipt.get("attempt") != 2
        or receipt.get("status") != "failed"
        or receipt.get("provider_calls") != 0
        or receipt.get("external_actions") != 0
    ):
        raise RunnerBlocked("prior_attempt_evidence_invalid")
    for name, size_field, sha_field in (
        ("events.jsonl", "events_captured_bytes", "events_sha256"),
        ("stderr.log", "stderr_captured_bytes", "stderr_sha256"),
    ):
        path = _require_owner_file(prior / name, "prior_attempt_evidence_invalid")
        raw = path.read_bytes()
        if len(raw) != receipt.get(size_field) or _sha256_bytes(raw) != receipt.get(
            sha_field
        ):
            raise RunnerBlocked("prior_attempt_evidence_invalid")
    return receipt, _sha256_bytes(receipt_raw)


def _read_attempt3(run_root: Path) -> tuple[dict[str, Any], str]:
    """Verify the immutable failed attempt 3 before authorizing attempt 4."""

    _prior, prior_sha = _read_prior_attempt(run_root)
    attempt = _require_directory(
        run_root / "ai-attempt-3", "prior_attempt_evidence_invalid"
    )
    allowed = {
        "attempt-intent.json",
        "attempt-receipt.json",
        "events.jsonl",
        "stderr.log",
    }
    if {path.name for path in attempt.iterdir()} != allowed:
        raise RunnerBlocked("prior_attempt_evidence_invalid")
    files = {
        name: _require_owner_file(attempt / name, "prior_attempt_evidence_invalid")
        for name in allowed
    }
    try:
        intent_raw = files["attempt-intent.json"].read_bytes()
        receipt_raw = files["attempt-receipt.json"].read_bytes()
        intent = json.loads(intent_raw)
        receipt = json.loads(receipt_raw)
        if not isinstance(intent, dict) or not isinstance(receipt, dict):
            raise TypeError("attempt3_evidence_not_object")
        require_valid_payload(intent, "codex_ai_attempt_intent_v1")
        require_valid_payload(receipt, "codex_ai_attempt_v1")
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        raise RunnerBlocked("prior_attempt_evidence_invalid") from exc
    context_raw = _require_owner_file(
        run_root / "context.json", "prior_attempt_evidence_invalid"
    ).read_bytes()
    prompt_raw = _require_owner_file(
        run_root / "prompt.txt", "prior_attempt_evidence_invalid"
    ).read_bytes()
    wire_raw = _require_schema(SCHEMA_PATH).read_bytes()
    business_raw = _require_schema(BUSINESS_SCHEMA_PATH).read_bytes()
    if (
        intent.get("attempt") != 3
        or receipt.get("attempt") != 3
        or receipt.get("status") != "failed"
        or receipt.get("result_bytes") is not None
        or receipt.get("result_sha256") is not None
        or receipt.get("provider_calls") != 0
        or receipt.get("external_actions") != 0
        or intent.get("prior_attempt_receipt_sha256") != prior_sha
        or intent.get("context_sha256") != _sha256_bytes(context_raw)
        or intent.get("prompt_sha256") != _sha256_bytes(prompt_raw)
        or intent.get("wire_schema_sha256") != _sha256_bytes(wire_raw)
        or intent.get("business_schema_sha256") != _sha256_bytes(business_raw)
        or receipt.get("context_sha256") != _sha256_bytes(context_raw)
        or receipt.get("prompt_sha256") != _sha256_bytes(prompt_raw)
        or receipt.get("schema_sha256") != _sha256_bytes(wire_raw)
        or receipt.get("intent_bytes") != len(intent_raw)
        or receipt.get("intent_sha256") != _sha256_bytes(intent_raw)
        or receipt.get("command_contract") != intent.get("command_contract")
    ):
        raise RunnerBlocked("prior_attempt_evidence_invalid")
    for name, size_field, sha_field in (
        ("events.jsonl", "events_captured_bytes", "events_sha256"),
        ("stderr.log", "stderr_captured_bytes", "stderr_sha256"),
    ):
        raw = files[name].read_bytes()
        if receipt.get(size_field) != len(raw) or receipt.get(
            sha_field
        ) != _sha256_bytes(raw):
            raise RunnerBlocked("prior_attempt_evidence_invalid")
    return receipt, _sha256_bytes(receipt_raw)


def _read_canary_receipt(
    receipt_path: Path, wire_raw: bytes, executable: Path | None = None
) -> tuple[dict[str, Any], str]:
    receipt_file = _require_owner_file(receipt_path, "schema_canary_invalid")
    bundle = _require_directory(receipt_file.parent, "schema_canary_invalid")
    if bundle.name != "schema-canary-v2":
        raise RunnerBlocked("schema_canary_invalid")
    try:
        require_public_canary_root(bundle.parent, allowed_entries={"schema-canary-v2"})
    except PublicCanaryRootError as exc:
        raise RunnerBlocked("schema_canary_invalid") from exc
    allowed = {
        "prompt.txt",
        "events.jsonl",
        "stderr.log",
        "canary-result.json",
        "canary-receipt.json",
    }
    if (
        receipt_file.name != "canary-receipt.json"
        or {path.name for path in bundle.iterdir()} != allowed
    ):
        raise RunnerBlocked("schema_canary_invalid")
    files = {
        name: _require_owner_file(bundle / name, "schema_canary_invalid")
        for name in allowed
    }
    try:
        receipt_raw = files["canary-receipt.json"].read_bytes()
        receipt = json.loads(receipt_raw)
        result = json.loads(files["canary-result.json"].read_bytes())
        if not isinstance(receipt, dict) or not isinstance(result, dict):
            raise TypeError("canary_not_object")
        require_valid_payload(receipt, "codex_schema_canary_v1")
        require_valid_payload(result, "daily_ai_result_codex_v2")
        require_valid_payload(result, "daily_ai_result_v1")
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        raise RunnerBlocked("schema_canary_invalid") from exc
    executable_sha: str | None = None
    if executable is not None:
        executable_path = Path(os.path.realpath(executable))
        try:
            executable_sha = _sha256_bytes(executable_path.read_bytes())
        except OSError as exc:
            raise RunnerBlocked("schema_canary_invalid") from exc
    if (
        receipt.get("status") != "succeeded"
        or receipt.get("error_code") is not None
        or receipt.get("wire_schema_sha256") != _sha256_bytes(wire_raw)
        or (
            executable_sha is not None
            and receipt.get("codex_executable_sha256") != executable_sha
        )
        or receipt.get("prompt_sha256")
        != _sha256_bytes(files["prompt.txt"].read_bytes())
        or receipt.get("provider_calls") != 0
        or receipt.get("external_actions") != 0
    ):
        raise RunnerBlocked("schema_canary_invalid")
    for name, size_field, sha_field in (
        ("events.jsonl", "events_captured_bytes", "events_sha256"),
        ("stderr.log", "stderr_captured_bytes", "stderr_sha256"),
        ("canary-result.json", "result_bytes", "result_sha256"),
    ):
        raw = files[name].read_bytes()
        if receipt.get(size_field) != len(raw) or receipt.get(
            sha_field
        ) != _sha256_bytes(raw):
            raise RunnerBlocked("schema_canary_invalid")
    return receipt, _sha256_bytes(receipt_raw)


def _load_frozen_inputs(
    run_root: Path,
    *,
    policy: AttemptPolicy = ATTEMPT3_POLICY,
    expected_context_sha256: str,
    expected_prompt_sha256: str,
    expected_schema_sha256: str,
) -> tuple[dict[str, Any], bytes, bytes, bytes, str]:
    context_path = _require_owner_file(
        run_root / "context.json", "frozen_context_unavailable"
    )
    prompt_path = _require_owner_file(
        run_root / "prompt.txt", "frozen_prompt_unavailable"
    )
    wire_path = _require_schema(policy.wire_schema_path)
    business_path = _require_schema(BUSINESS_SCHEMA_PATH)
    try:
        context_raw = context_path.read_bytes()
        prompt_raw = prompt_path.read_bytes()
        wire_raw = wire_path.read_bytes()
        business_raw = business_path.read_bytes()
    except OSError as exc:
        raise RunnerBlocked("frozen_input_read_failed") from exc
    if _sha256_bytes(context_raw) != expected_context_sha256:
        raise RunnerBlocked("frozen_context_sha256_mismatch")
    if _sha256_bytes(prompt_raw) != expected_prompt_sha256:
        raise RunnerBlocked("frozen_prompt_sha256_mismatch")
    if _sha256_bytes(wire_raw) != expected_schema_sha256:
        raise RunnerBlocked("frozen_schema_sha256_mismatch")
    try:
        context = json.loads(context_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnerBlocked("frozen_context_invalid") from exc
    if not isinstance(context, dict):
        raise RunnerBlocked("frozen_context_invalid")
    prior, prior_sha = (
        _read_prior_attempt(run_root)
        if policy.number == 3
        else _read_attempt3(run_root)
    )
    if (
        prior.get("context_sha256") != expected_context_sha256
        or prior.get("prompt_sha256") != expected_prompt_sha256
        or (
            policy.number == 3
            and prior.get("schema_sha256") != _sha256_bytes(business_raw)
        )
    ):
        raise RunnerBlocked("prior_attempt_input_mismatch")
    if any(
        context.get(field) != expected
        for field, expected in (
            ("status", "ready"),
            ("report_date", "2026-08-17"),
            ("review_date", "2026-08-16"),
            ("sleep_wake_date", "2026-08-17"),
        )
    ):
        raise RunnerBlocked("frozen_context_invalid")
    return context, prompt_raw, wire_raw, business_raw, prior_sha


def _load_live_sync_module() -> Any:
    path = SOURCE_ROOT / "skills/garmin-sync/scripts/live_sync.py"
    spec = importlib.util.spec_from_file_location("trainlab_m9_live_preflight", path)
    if spec is None or spec.loader is None:
        raise RunnerBlocked("ai_environment_preflight_failed")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (ImportError, OSError, ValueError) as exc:
        raise RunnerBlocked("ai_environment_preflight_failed") from exc
    return module


def _production_environment_check(run_root: Path, token_dir: Path) -> str:
    """Validate formal provenance and return an in-memory token fingerprint."""

    candidate_root = run_root.parents[1]
    candidate_source = candidate_root / "source"
    database = candidate_source / "state/trainlab.db"
    module = _load_live_sync_module()
    try:
        module._assert_candidate_scope(candidate_source, database)
        fingerprint = module._token_fingerprint(token_dir)
    except (OSError, ValueError) as exc:
        raise RunnerBlocked("ai_environment_preflight_failed") from exc
    if (
        not isinstance(fingerprint, str)
        or SHA256_PATTERN.fullmatch(fingerprint) is None
    ):
        raise RunnerBlocked("ai_environment_preflight_failed")
    return fingerprint


def _error_messages(events: bytes) -> list[str]:
    messages: list[str] = []
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if not isinstance(event_type, str) or not (
            event_type == "error" or event_type.endswith(".failed")
        ):
            continue
        for value in (event.get("message"), event.get("error")):
            if isinstance(value, str):
                messages.append(value)
            elif isinstance(value, dict):
                messages.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return messages


def _classify(messages: list[str], stderr: bytes) -> str:
    structured = "\n".join(messages).lower()
    cli_stderr = stderr.decode("utf-8", errors="replace").lower()
    combined = f"{structured}\n{cli_stderr}"
    if re.search(
        r"output[- _]schema|invalid[- _](?:json[- _])?schema|schema validation|did not match.*schema|invalid schema|allof.*not permitted",
        combined,
    ):
        return "schema_non_retryable"
    if re.search(r"\b(?:401|403)\b|authenticat|not logged in|login required", combined):
        return "auth_non_retryable"
    if re.search(r"sandbox|permission denied|operation not permitted", combined):
        return "sandbox_non_retryable"
    if re.search(
        r"unexpected argument|unknown (?:argument|option)|usage:|no such file|command not found",
        cli_stderr,
    ):
        return "cli_non_retryable"
    if re.search(r"\b(?:http(?: status)?[ :=]*)?5[0-9]{2}\b|server error", combined):
        return "server_5xx_retryable"
    if re.search(
        r"connection (?:reset|closed|refused)|stream (?:closed|disconnected)|network error|transport error|timed? out|timeout",
        combined,
    ):
        return "transport_retryable"
    return "unknown_non_retryable"


def _process_group_exists(process_group_id: int) -> bool | None:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return None
    except OSError as exc:
        return False if exc.errno == errno.ESRCH else None
    return True


def _wait_for_process_group_exit(
    process_group_id: int,
    timeout: float,
    *,
    permission_after_kill_means_replaced: bool = False,
) -> bool:
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        exists = _process_group_exists(process_group_id)
        if exists is False:
            return True
        if exists is None:
            if permission_after_kill_means_replaced:
                try:
                    os.killpg(process_group_id, 0)
                except PermissionError:
                    # A same-UID child cannot become uninspectable.  After a
                    # successful SIGKILL this means the original group is gone
                    # and the numeric PGID has already been reused.
                    return True
                except ProcessLookupError:
                    return True
                except OSError:
                    return False
            return False
        time.sleep(0.01)
    return _process_group_exists(process_group_id) is False


def _terminate_and_confirm(process: subprocess.Popen[bytes]) -> bool:
    """Stop and confirm the whole Codex process group, not only its leader."""

    process_group_id = process.pid
    group_exists = _process_group_exists(process_group_id)
    if group_exists is False:
        return process.poll() is not None
    if group_exists is None:
        return False
    leader_already_exited = process.poll() is not None
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        return process.poll() is not None
    except PermissionError:
        return False
    except OSError as exc:
        return process.poll() is not None if exc.errno == errno.ESRCH else False
    if leader_already_exited:
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        except OSError as exc:
            return exc.errno == errno.ESRCH
        return _wait_for_process_group_exit(
            process_group_id,
            5.0,
            permission_after_kill_means_replaced=True,
        )
    try:
        process.wait(timeout=2.0)
    except (subprocess.TimeoutExpired, PermissionError, OSError):
        pass
    if _wait_for_process_group_exit(process_group_id, 0.25):
        return process.poll() is not None
    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        return process.poll() is not None
    except PermissionError:
        return False
    except OSError as exc:
        return process.poll() is not None if exc.errno == errno.ESRCH else False
    try:
        process.wait(timeout=5.0)
    except (subprocess.TimeoutExpired, PermissionError, OSError):
        pass
    return process.poll() is not None and _wait_for_process_group_exit(
        process_group_id,
        5.0,
        permission_after_kill_means_replaced=True,
    )


def _run_process(
    command: list[str],
    prompt: bytes,
    run_root: Path,
    events_path: Path,
    stderr_path: Path,
    deadline_monotonic: float,
    max_log_bytes: int,
    *,
    pass_fds: tuple[int, ...] = (),
) -> tuple[int, bool, bool, bool, bool, float, bool]:
    started = time.monotonic()
    timed_out = False
    overflow = False
    launch_failed = False
    prompt_complete = False
    stopped = True
    with (
        events_path.open("wb") as events_handle,
        stderr_path.open("wb") as stderr_handle,
    ):
        try:
            process = subprocess.Popen(
                command,
                cwd=run_root,
                stdin=subprocess.PIPE,
                stdout=events_handle,
                stderr=stderr_handle,
                start_new_session=True,
                umask=0o077,
                pass_fds=pass_fds,
            )
        except OSError as exc:
            launch_failed = True
            return_code = 127
            model_finished = time.monotonic()
            stderr_handle.write(f"codex launch failed: {type(exc).__name__}\n".encode())
        else:
            assert process.stdin is not None
            descriptor = process.stdin.fileno()
            os.set_blocking(descriptor, False)
            remaining = memoryview(prompt)
            stdin_open = True
            try:
                while process.poll() is None:
                    if time.monotonic() >= deadline_monotonic:
                        timed_out = True
                        break
                    events_handle.flush()
                    stderr_handle.flush()
                    if (
                        events_path.stat().st_size > max_log_bytes
                        or stderr_path.stat().st_size > max_log_bytes
                    ):
                        overflow = True
                        break
                    if remaining and stdin_open:
                        try:
                            written = os.write(descriptor, remaining[:65536])
                        except BlockingIOError:
                            written = 0
                        except BrokenPipeError:
                            stdin_open = False
                            written = 0
                        if written > 0:
                            remaining = remaining[written:]
                    if not remaining and stdin_open:
                        try:
                            process.stdin.close()
                        except (BrokenPipeError, OSError):
                            pass
                        stdin_open = False
                    time.sleep(0.01)
            except Exception:
                if process.poll() is None and not _terminate_and_confirm(process):
                    raise RunnerBlocked("ai_process_stop_unconfirmed") from None
                raise
            finally:
                if stdin_open:
                    try:
                        process.stdin.close()
                    except (BrokenPipeError, OSError):
                        pass
                    stdin_open = False
            prompt_complete = not remaining
            if time.monotonic() >= deadline_monotonic and process.poll() is None:
                timed_out = True
            # Even when the session leader has already exited, descendants may
            # still hold stdout/stderr descriptors.  Final publication is safe
            # only after the entire process group is gone.
            stopped = _terminate_and_confirm(process)
            model_finished = time.monotonic()
            if model_finished >= deadline_monotonic:
                timed_out = True
            polled = process.poll()
            return_code = int(polled) if polled is not None else 124
        for handle in (events_handle, stderr_handle):
            handle.flush()
            os.fsync(handle.fileno())
    for path in (events_path, stderr_path):
        if path.stat().st_size > max_log_bytes:
            overflow = True
            with path.open("r+b") as truncate_handle:
                truncate_handle.truncate(max_log_bytes)
                truncate_handle.flush()
                os.fsync(truncate_handle.fileno())
    return (
        return_code,
        timed_out,
        overflow,
        launch_failed,
        prompt_complete,
        model_finished - started,
        stopped,
    )


def _ensure_capture(path: Path, placeholder: bytes) -> bytes:
    if path.stat().st_size == 0:
        with path.open("wb") as handle:
            handle.write(placeholder)
            handle.flush()
            os.fsync(handle.fileno())
    os.chmod(path, 0o600)
    return path.read_bytes()


def _intent(
    *,
    policy: AttemptPolicy = ATTEMPT3_POLICY,
    timeout_seconds: float,
    max_log_bytes: int,
    prior_receipt_sha: str,
    context_sha: str,
    prompt_sha: str,
    wire_schema_sha: str,
    business_schema_sha: str,
    canary_receipt_sha: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": (
            "codex_ai_attempt_intent_v1"
            if policy.number == 3
            else "codex_ai_attempt_intent_v2"
        ),
        "attempt": policy.number,
        "created_at_utc": _utc_now(),
        "timeout_seconds": timeout_seconds,
        "max_log_bytes": max_log_bytes,
        "command_contract": {
            "ephemeral": True,
            "ignore_user_config": True,
            "sandbox": "read-only",
            "json_events": True,
            "output_schema": policy.wire_schema_name,
        },
        "prior_attempt_receipt_sha256": prior_receipt_sha,
        "context_sha256": context_sha,
        "prompt_sha256": prompt_sha,
        "wire_schema_sha256": wire_schema_sha,
        "business_schema_sha256": business_schema_sha,
        "provider_calls": 0,
        "external_actions": 0,
    }
    if policy.number == 4:
        if canary_receipt_sha is None:
            raise RunnerBlocked("schema_canary_invalid")
        payload["canary_receipt_sha256"] = canary_receipt_sha
    return payload


def _receipt(
    *,
    policy: AttemptPolicy = ATTEMPT3_POLICY,
    intent_raw: bytes,
    status: str,
    error_code: str | None,
    error_category: str | None,
    return_code: int,
    started_at: str,
    elapsed_seconds: float,
    context_sha: str,
    prompt_sha: str,
    schema_sha: str,
    events_raw: bytes,
    stderr_raw: bytes,
    result_raw: bytes | None,
    timeout_seconds: float,
    max_log_bytes: int,
) -> dict[str, Any]:
    return {
        "schema_version": (
            "codex_ai_attempt_v1" if policy.number == 3 else "codex_ai_attempt_v2"
        ),
        "attempt": policy.number,
        "status": status,
        "error_code": error_code,
        "error_category": error_category,
        "exit_code": return_code,
        "started_at_utc": started_at,
        "finished_at_utc": _utc_now(),
        "elapsed_milliseconds": round(elapsed_seconds * 1000),
        "timeout_seconds": timeout_seconds,
        "max_log_bytes": max_log_bytes,
        "command_contract": {
            "ephemeral": True,
            "ignore_user_config": True,
            "sandbox": "read-only",
            "json_events": True,
            "output_schema": policy.wire_schema_name,
        },
        "context_sha256": context_sha,
        "prompt_sha256": prompt_sha,
        "schema_sha256": schema_sha,
        "intent_bytes": len(intent_raw),
        "intent_sha256": _sha256_bytes(intent_raw),
        "events_captured_bytes": len(events_raw),
        "events_sha256": _sha256_bytes(events_raw),
        "stderr_captured_bytes": len(stderr_raw),
        "stderr_sha256": _sha256_bytes(stderr_raw),
        "result_bytes": len(result_raw) if result_raw is not None else None,
        "result_sha256": _sha256_bytes(result_raw) if result_raw is not None else None,
        "provider_calls": 0,
        "external_actions": 0,
    }


def _publish_terminal(
    pending: Path, final: Path, receipt: dict[str, Any], result_raw: bytes | None
) -> None:
    if result_raw is not None:
        _atomic_owner_write(pending / "ai-result.json", result_raw)
    _atomic_owner_write(pending / "attempt-receipt.json", _json_bytes(receipt))
    allowed = {
        "attempt-intent.json",
        "events.jsonl",
        "stderr.log",
        "attempt-receipt.json",
    }
    if result_raw is not None:
        allowed.add("ai-result.json")
    if {path.name for path in pending.iterdir()} != allowed:
        raise RunnerBlocked("ai_attempt_bundle_invalid")
    for path in pending.iterdir():
        _require_owner_file(path, "ai_attempt_bundle_invalid")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    _fsync_directory(pending)
    if final.exists() or final.is_symlink():
        raise RunnerBlocked("ai_attempt_history_invalid")
    os.rename(pending, final)
    _fsync_directory(final.parent)


def _verify_terminal_locked(
    run_root: Path,
    *,
    policy: AttemptPolicy = ATTEMPT3_POLICY,
    expected_context_sha256: str,
    expected_prompt_sha256: str,
    expected_schema_sha256: str,
    expected_canary_receipt_sha256: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    attempt_names = {
        path.name for path in run_root.iterdir() if path.name.startswith("ai-attempt-")
    }
    if attempt_names != policy.history_after:
        raise RunnerBlocked("ai_attempt_history_invalid")
    pending = run_root / policy.pending_directory
    final = run_root / policy.attempt_directory
    if pending.exists() or pending.is_symlink():
        raise RunnerBlocked("ai_attempt_incomplete")
    final = _require_directory(final, "ai_attempt_terminal_invalid")
    names = {path.name for path in final.iterdir()}
    base = {"attempt-intent.json", "events.jsonl", "stderr.log", "attempt-receipt.json"}
    if names not in (base, base | {"ai-result.json"}):
        raise RunnerBlocked("ai_attempt_terminal_invalid")
    files = {
        name: _require_owner_file(final / name, "ai_attempt_terminal_invalid")
        for name in names
    }
    try:
        intent_raw = files["attempt-intent.json"].read_bytes()
        receipt = json.loads(files["attempt-receipt.json"].read_bytes())
        intent = json.loads(intent_raw)
        if not isinstance(intent, dict) or not isinstance(receipt, dict):
            raise TypeError("terminal_not_object")
        require_valid_payload(intent, policy.intent_schema_name)
        require_valid_payload(receipt, policy.receipt_schema_name)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        raise RunnerBlocked("ai_attempt_terminal_invalid") from exc
    prior, prior_sha = (
        _read_prior_attempt(run_root)
        if policy.number == 3
        else _read_attempt3(run_root)
    )
    context_raw = _require_owner_file(
        run_root / "context.json", "ai_attempt_terminal_invalid"
    ).read_bytes()
    prompt_raw = _require_owner_file(
        run_root / "prompt.txt", "ai_attempt_terminal_invalid"
    ).read_bytes()
    wire_raw = _require_schema(policy.wire_schema_path).read_bytes()
    business_raw = _require_schema(BUSINESS_SCHEMA_PATH).read_bytes()
    if (
        intent.get("prior_attempt_receipt_sha256") != prior_sha
        or _sha256_bytes(context_raw) != expected_context_sha256
        or _sha256_bytes(prompt_raw) != expected_prompt_sha256
        or intent.get("context_sha256") != expected_context_sha256
        or intent.get("prompt_sha256") != expected_prompt_sha256
        or intent.get("wire_schema_sha256") != expected_schema_sha256
        or intent.get("business_schema_sha256") != _sha256_bytes(business_raw)
        or _sha256_bytes(wire_raw) != expected_schema_sha256
        or (
            policy.number == 3
            and prior.get("schema_sha256") != _sha256_bytes(business_raw)
        )
        or prior.get("context_sha256") != expected_context_sha256
        or prior.get("prompt_sha256") != expected_prompt_sha256
        or intent.get("attempt") != policy.number
        or receipt.get("attempt") != policy.number
        or receipt.get("intent_bytes") != len(intent_raw)
        or receipt.get("intent_sha256") != _sha256_bytes(intent_raw)
        or receipt.get("context_sha256") != expected_context_sha256
        or receipt.get("prompt_sha256") != expected_prompt_sha256
        or receipt.get("schema_sha256") != expected_schema_sha256
        or receipt.get("timeout_seconds") != intent.get("timeout_seconds")
        or receipt.get("max_log_bytes") != intent.get("max_log_bytes")
        or receipt.get("command_contract") != intent.get("command_contract")
        or (
            policy.number == 4
            and intent.get("canary_receipt_sha256") != expected_canary_receipt_sha256
        )
    ):
        raise RunnerBlocked("ai_attempt_terminal_invalid")
    for name, size_field, sha_field in (
        ("events.jsonl", "events_captured_bytes", "events_sha256"),
        ("stderr.log", "stderr_captured_bytes", "stderr_sha256"),
    ):
        raw = files[name].read_bytes()
        if receipt.get(size_field) != len(raw) or receipt.get(
            sha_field
        ) != _sha256_bytes(raw):
            raise RunnerBlocked("ai_attempt_terminal_invalid")
    result: dict[str, Any] | None = None
    if receipt.get("status") == "succeeded":
        if "ai-result.json" not in files:
            raise RunnerBlocked("ai_attempt_terminal_invalid")
        result_raw = files["ai-result.json"].read_bytes()
        if receipt.get("result_bytes") != len(result_raw) or receipt.get(
            "result_sha256"
        ) != _sha256_bytes(result_raw):
            raise RunnerBlocked("ai_attempt_terminal_invalid")
        try:
            result = json.loads(result_raw)
            if not isinstance(result, dict):
                raise TypeError("result_not_object")
            require_valid_payload(result, policy.wire_schema_name)
            require_valid_payload(result, "daily_ai_result_v1")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RunnerBlocked("ai_attempt_terminal_invalid") from exc
    elif "ai-result.json" in files:
        raise RunnerBlocked("ai_attempt_terminal_invalid")
    return receipt, result


def load_succeeded_result(
    *,
    run_root: Path,
    canary_receipt_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    with _run_root_lock(run_root) as locked_root:
        try:
            context_raw = _require_owner_file(
                locked_root / "context.json", "ai_attempt_terminal_invalid"
            ).read_bytes()
            prompt_raw = _require_owner_file(
                locked_root / "prompt.txt", "ai_attempt_terminal_invalid"
            ).read_bytes()
            wire_raw = _require_schema(SCHEMA_V2_PATH).read_bytes()
            context = json.loads(context_raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RunnerBlocked("ai_attempt_terminal_invalid") from exc
        if not isinstance(context, dict):
            raise RunnerBlocked("ai_attempt_terminal_invalid")
        _canary, canary_sha = _read_canary_receipt(canary_receipt_path, wire_raw)
        receipt, result = _verify_terminal_locked(
            locked_root,
            policy=ATTEMPT4_POLICY,
            expected_context_sha256=_sha256_bytes(context_raw),
            expected_prompt_sha256=_sha256_bytes(prompt_raw),
            expected_schema_sha256=_sha256_bytes(wire_raw),
            expected_canary_receipt_sha256=canary_sha,
        )
        if receipt.get("status") != "succeeded" or result is None:
            raise RunnerBlocked("ai_attempt_not_succeeded")
        return receipt, result, context


def _run_codex_daily_impl(
    *,
    policy: AttemptPolicy = ATTEMPT3_POLICY,
    run_root: Path,
    expected_context_sha256: str,
    expected_prompt_sha256: str,
    expected_schema_sha256: str,
    codex_executable: Path | str,
    canary_receipt_path: Path | None = None,
    token_dir: Path | None = None,
    environment_check: Callable[[], str] | None = None,
    timeout_seconds: float = TIMEOUT_SECONDS,
    max_log_bytes: int = MAX_LOG_BYTES,
) -> dict[str, Any]:
    for value, field in (
        (expected_context_sha256, "expected_context_sha256"),
        (expected_prompt_sha256, "expected_prompt_sha256"),
        (expected_schema_sha256, "expected_schema_sha256"),
    ):
        _require_hash(value, field)
    if timeout_seconds <= 0 or timeout_seconds > TIMEOUT_SECONDS:
        raise RunnerBlocked("ai_timeout_invalid")
    if max_log_bytes <= 0 or max_log_bytes > MAX_LOG_BYTES:
        raise RunnerBlocked("ai_log_budget_invalid")
    if environment_check is None:
        if token_dir is None:
            raise RunnerBlocked("ai_environment_preflight_failed")

        def production_environment_check() -> str:
            return _production_environment_check(run_root, token_dir)

        check_environment = production_environment_check
    else:
        check_environment = environment_check

    with _run_root_lock(run_root) as locked_root:
        if (
            locked_root.name != EXPECTED_RUN_ROOT_NAME
            or locked_root.parent.name != "run"
        ):
            raise RunnerBlocked("ai_run_root_invalid")
        _require_directory(locked_root.parent, "ai_run_root_invalid")
        _require_directory(locked_root.parents[1], "ai_run_root_invalid")
        environment_fingerprint = check_environment()
        if check_environment() != environment_fingerprint:
            raise RunnerBlocked("ai_environment_changed")
        attempt_names = {
            path.name
            for path in locked_root.iterdir()
            if path.name.startswith("ai-attempt-")
        }
        if policy.pending_directory in attempt_names:
            if policy.attempt_directory in attempt_names:
                raise RunnerBlocked("ai_attempt_history_invalid")
            raise RunnerBlocked("ai_attempt_incomplete")
        if policy.attempt_directory in attempt_names:
            if attempt_names != policy.history_after:
                raise RunnerBlocked("ai_attempt_history_invalid")
            replay_canary_sha = None
            if policy.number == 4:
                if canary_receipt_path is None:
                    raise RunnerBlocked("schema_canary_invalid")
                wire_raw = _require_schema(policy.wire_schema_path).read_bytes()
                _canary, replay_canary_sha = _read_canary_receipt(
                    canary_receipt_path, wire_raw
                )
            receipt, _result = _verify_terminal_locked(
                locked_root,
                policy=policy,
                expected_context_sha256=expected_context_sha256,
                expected_prompt_sha256=expected_prompt_sha256,
                expected_schema_sha256=expected_schema_sha256,
                expected_canary_receipt_sha256=replay_canary_sha,
            )
            return receipt
        if attempt_names != policy.history_before:
            raise RunnerBlocked("ai_attempt_history_invalid")

        _context, prompt_raw, wire_raw, business_raw, prior_sha = _load_frozen_inputs(
            locked_root,
            policy=policy,
            expected_context_sha256=expected_context_sha256,
            expected_prompt_sha256=expected_prompt_sha256,
            expected_schema_sha256=expected_schema_sha256,
        )
        executable = Path(codex_executable)
        if not executable.exists() or not os.access(executable, os.X_OK):
            raise RunnerBlocked("codex_cli_unavailable")
        canary_sha: str | None = None
        if policy.number == 4:
            try:
                wire_schema = json.loads(wire_raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RunnerBlocked("frozen_schema_invalid") from exc
            try:
                require_supported_schema(wire_schema)
            except ValueError as exc:
                raise RunnerBlocked("frozen_schema_invalid") from exc
            if canary_receipt_path is None:
                raise RunnerBlocked("schema_canary_invalid")
            _canary, canary_sha = _read_canary_receipt(
                canary_receipt_path, wire_raw, executable
            )

        pending = locked_root / policy.pending_directory
        final = locked_root / policy.attempt_directory
        pending.mkdir(mode=0o700)
        _fsync_directory(locked_root)
        intent = _intent(
            policy=policy,
            timeout_seconds=timeout_seconds,
            max_log_bytes=max_log_bytes,
            prior_receipt_sha=prior_sha,
            context_sha=expected_context_sha256,
            prompt_sha=expected_prompt_sha256,
            wire_schema_sha=expected_schema_sha256,
            business_schema_sha=_sha256_bytes(business_raw),
            canary_receipt_sha=canary_sha,
        )
        require_valid_payload(intent, policy.intent_schema_name)
        intent_raw = _json_bytes(intent)
        _atomic_owner_write(pending / "attempt-intent.json", intent_raw)
        _fsync_directory(locked_root)

        events_path = pending / "events.jsonl"
        stderr_path = pending / "stderr.log"
        result_temporary = pending / ".ai-result.pending.json"
        for path in (events_path, stderr_path):
            descriptor = os.open(
                path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
            )
            os.close(descriptor)
        schema_descriptor = _anonymous_read_only_file(pending, wire_raw)
        started_at = _utc_now()
        process_started = time.monotonic()
        try:
            command = [
                str(executable),
                "exec",
                "-C",
                str(locked_root),
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
            outcome = _run_process(
                command,
                prompt_raw,
                locked_root,
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
            elapsed,
            stopped,
        ) = outcome
        if elapsed >= timeout_seconds:
            timed_out = True
        if not stopped:
            raise RunnerBlocked("ai_process_stop_unconfirmed")

        events_raw = _ensure_capture(events_path, EMPTY_EVENTS)
        stderr_raw = _ensure_capture(stderr_path, EMPTY_STDERR)
        try:
            environment_stable = check_environment() == environment_fingerprint
        except RunnerBlocked:
            environment_stable = False
        status = "failed"
        error_code: str | None = None
        error_category: str | None = None
        result_raw: bytes | None = None
        if not environment_stable:
            error_code, error_category = (
                "ai_environment_changed",
                "unknown_non_retryable",
            )
        elif timed_out:
            error_code, error_category = "ai_codex_timeout", "transport_retryable"
        elif launch_failed:
            error_code, error_category = "ai_codex_launch_failed", "cli_non_retryable"
        elif overflow:
            error_code, error_category = "ai_log_budget_exceeded", "cli_non_retryable"
        elif not prompt_complete:
            error_code, error_category = "ai_prompt_incomplete", "cli_non_retryable"
        elif return_code != 0:
            error_code = "ai_codex_exit_nonzero"
            error_category = _classify(_error_messages(events_raw), stderr_raw)
        elif _error_messages(events_raw):
            error_code = "ai_codex_error_event"
            error_category = _classify(_error_messages(events_raw), stderr_raw)
        elif not result_temporary.is_file() or result_temporary.is_symlink():
            error_code, error_category = "ai_result_missing", "cli_non_retryable"
        else:
            metadata = result_temporary.lstat()
            if (
                metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1
                or metadata.st_size <= 0
                or metadata.st_size > MAX_RESULT_BYTES
            ):
                error_code, error_category = (
                    "ai_result_file_invalid",
                    "schema_non_retryable",
                )
            else:
                candidate_raw = result_temporary.read_bytes()
                try:
                    payload = json.loads(candidate_raw)
                    if not isinstance(payload, dict):
                        raise TypeError("ai_result_not_object")
                    require_valid_payload(payload, policy.wire_schema_name)
                    require_valid_payload(payload, "daily_ai_result_v1")
                except (
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                    TypeError,
                    ValueError,
                ):
                    error_code, error_category = (
                        "ai_result_schema_invalid",
                        "schema_non_retryable",
                    )
                else:
                    status = "succeeded"
                    result_raw = candidate_raw
        result_temporary.unlink(missing_ok=True)
        _fsync_directory(pending)
        receipt = _receipt(
            policy=policy,
            intent_raw=intent_raw,
            status=status,
            error_code=error_code,
            error_category=error_category,
            return_code=return_code,
            started_at=started_at,
            elapsed_seconds=elapsed,
            context_sha=expected_context_sha256,
            prompt_sha=expected_prompt_sha256,
            schema_sha=expected_schema_sha256,
            events_raw=events_raw,
            stderr_raw=stderr_raw,
            result_raw=result_raw,
            timeout_seconds=timeout_seconds,
            max_log_bytes=max_log_bytes,
        )
        require_valid_payload(receipt, policy.receipt_schema_name)
        try:
            _publish_terminal(pending, final, receipt, result_raw)
        except Exception as exc:
            raise RunnerBlocked("ai_attempt_incomplete") from exc
        # This invocation already validated the frozen bytes and bundle while holding
        # the lock. Replays and downstream consumers perform a fresh closure check.
        return receipt


def _run_codex_daily_with_policy(
    *,
    policy: AttemptPolicy,
    run_root: Path,
    expected_context_sha256: str,
    expected_prompt_sha256: str,
    expected_schema_sha256: str,
    codex_executable: Path | str,
    canary_receipt_path: Path | None = None,
    token_dir: Path | None = None,
    environment_check: Callable[[], str] | None = None,
    timeout_seconds: float = TIMEOUT_SECONDS,
    max_log_bytes: int = MAX_LOG_BYTES,
) -> dict[str, Any]:
    """Run the frozen attempt and convert finite local I/O faults to blocked."""

    absolute_root = Path(os.path.abspath(run_root))
    try:
        return _run_codex_daily_impl(
            policy=policy,
            run_root=absolute_root,
            expected_context_sha256=expected_context_sha256,
            expected_prompt_sha256=expected_prompt_sha256,
            expected_schema_sha256=expected_schema_sha256,
            codex_executable=codex_executable,
            canary_receipt_path=canary_receipt_path,
            token_dir=token_dir,
            environment_check=environment_check,
            timeout_seconds=timeout_seconds,
            max_log_bytes=max_log_bytes,
        )
    except RunnerBlocked:
        raise
    except OSError as exc:
        try:
            started = (absolute_root / policy.pending_directory).exists() or (
                absolute_root / policy.attempt_directory
            ).exists()
        except OSError:
            started = True
        code = "ai_attempt_incomplete" if started else "ai_attempt_preflight_io_failed"
        raise RunnerBlocked(code) from exc


def run_codex_daily(
    *,
    run_root: Path,
    expected_context_sha256: str,
    expected_prompt_sha256: str,
    expected_schema_sha256: str,
    codex_executable: Path | str,
    token_dir: Path | None = None,
    environment_check: Callable[[], str] | None = None,
    timeout_seconds: float = TIMEOUT_SECONDS,
    max_log_bytes: int = MAX_LOG_BYTES,
) -> dict[str, Any]:
    """Replay the frozen attempt 3 policy for historical regression tests."""

    return _run_codex_daily_with_policy(
        policy=ATTEMPT3_POLICY,
        run_root=run_root,
        expected_context_sha256=expected_context_sha256,
        expected_prompt_sha256=expected_prompt_sha256,
        expected_schema_sha256=expected_schema_sha256,
        codex_executable=codex_executable,
        token_dir=token_dir,
        environment_check=environment_check,
        timeout_seconds=timeout_seconds,
        max_log_bytes=max_log_bytes,
    )


def run_codex_daily_v4(
    *,
    run_root: Path,
    expected_context_sha256: str,
    expected_prompt_sha256: str,
    expected_schema_sha256: str,
    codex_executable: Path | str,
    canary_receipt_path: Path,
    token_dir: Path | None = None,
    environment_check: Callable[[], str] | None = None,
    timeout_seconds: float = TIMEOUT_SECONDS,
    max_log_bytes: int = MAX_LOG_BYTES,
) -> dict[str, Any]:
    """Run or replay the single approved attempt 4."""

    return _run_codex_daily_with_policy(
        policy=ATTEMPT4_POLICY,
        run_root=run_root,
        expected_context_sha256=expected_context_sha256,
        expected_prompt_sha256=expected_prompt_sha256,
        expected_schema_sha256=expected_schema_sha256,
        codex_executable=codex_executable,
        canary_receipt_path=canary_receipt_path,
        token_dir=token_dir,
        environment_check=environment_check,
        timeout_seconds=timeout_seconds,
        max_log_bytes=max_log_bytes,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--expected-context-sha256", required=True)
    parser.add_argument("--expected-prompt-sha256", required=True)
    parser.add_argument("--expected-schema-sha256", required=True)
    parser.add_argument("--canary-receipt", type=Path, required=True)
    parser.add_argument("--token-dir", type=Path, required=True)
    args = parser.parse_args()
    executable = shutil.which("codex")
    if executable is None:
        print(
            json.dumps(
                {"status": "blocked", "error_code": "codex_cli_unavailable"},
                sort_keys=True,
            )
        )
        return 2
    try:
        result = run_codex_daily_v4(
            run_root=args.run_root,
            expected_context_sha256=args.expected_context_sha256,
            expected_prompt_sha256=args.expected_prompt_sha256,
            expected_schema_sha256=args.expected_schema_sha256,
            codex_executable=executable,
            canary_receipt_path=args.canary_receipt,
            token_dir=args.token_dir,
        )
    except RunnerBlocked as exc:
        print(json.dumps({"status": "blocked", "error_code": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": result["status"],
                "error_code": result["error_code"],
                "error_category": result["error_category"],
                "provider_calls": 0,
                "external_actions": 0,
            },
            sort_keys=True,
        )
    )
    return 0 if result["status"] == "succeeded" else 2
