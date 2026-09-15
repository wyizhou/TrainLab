"""Durable, bounded process evidence inside a reserved model job.

This Host-only component neither prepares a Codex command nor authorizes model
capabilities. Its supplied callable must use the configured launcher and existing
model_process supervisor. Raw bytes stay private; incomplete local evidence is
AdapterInterrupted, never an ordinary exception that could become a terminal
model_job failure. There is no second launch, including after a crash at mkdir.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import detail_transport, model_job, storage
from skills._shared.fit_weekly.model_process import ProcessInterrupted, ProcessResult

ERRORS = frozenset(
    {
        "process_start_failed",
        "process_authorization_expired",
        "process_input_incomplete",
        "process_timeout",
        "process_exit_nonzero",
        "process_stdout_limit",
        "process_stderr_limit",
        "process_io_failed",
        "process_stop_unconfirmed",
    }
)


class EvidenceUnavailable(model_job.AdapterInterrupted):
    """Only a fixed status escapes; private streams remain in the work directory."""


def binding(
    prompt: bytes,
    request_sha256: str,
    *,
    stdout_limit: int = 67_108_864,
    stderr_limit: int = 1_048_576,
) -> dict[str, Any]:
    if type(prompt) is not bytes:
        raise ValueError("process_capture_binding_invalid")
    return check_binding(
        {
            "request_sha256": request_sha256,
            "prompt_sha256": storage.digest(prompt),
            "prompt_bytes": len(prompt),
            "stdout_limit": stdout_limit,
            "stderr_limit": stderr_limit,
        }
    )


def check_binding(value: dict[str, Any]) -> dict[str, Any]:
    try:
        if not isinstance(value, dict) or set(value) != {
            "request_sha256",
            "prompt_sha256",
            "prompt_bytes",
            "stdout_limit",
            "stderr_limit",
        }:
            raise ValueError("shape")
        for key in ("request_sha256", "prompt_sha256"):
            storage.require_sha(value[key])
        for key, maximum in (
            ("prompt_bytes", 16_777_216),
            ("stdout_limit", 67_108_864),
            ("stderr_limit", 67_108_864),
        ):
            if type(value[key]) is not int or not 0 < value[key] <= maximum:
                raise ValueError("limit")
        return model_job.clone(value)
    except Exception:
        raise ValueError("process_capture_binding_invalid") from None


def encode_stream(raw: bytes) -> dict[str, Any]:
    return {
        "byte_size": len(raw),
        "sha256": storage.digest(raw),
        "base64": base64.b64encode(raw).decode("ascii"),
    }


def encode(result: ProcessResult, expected: dict[str, Any]) -> dict[str, Any]:
    if (
        type(result) is not ProcessResult
        or type(result.input_bytes) is not int
        or not 0 <= result.input_bytes <= expected["prompt_bytes"]
        or (result.returncode is not None and type(result.returncode) is not int)
        or type(result.process_stopped) is not bool
        or type(result.stdout) is not bytes
        or type(result.stderr) is not bytes
        or len(result.stdout) > expected["stdout_limit"]
        or len(result.stderr) > expected["stderr_limit"]
        or result.error_code is not None
        and result.error_code not in ERRORS
        or (not result.process_stopped)
        != (result.error_code == "process_stop_unconfirmed")
        or result.error_code is None
        and (result.returncode != 0 or result.input_bytes != expected["prompt_bytes"])
    ):
        raise ValueError("process_capture_result_invalid")
    return {
        "schema_version": "fit_process_capture_v1",
        "binding": expected,
        "process": {
            "returncode": result.returncode,
            "input_bytes": result.input_bytes,
            "stdout": encode_stream(result.stdout),
            "stderr": encode_stream(result.stderr),
            "error_code": result.error_code,
            "process_stopped": result.process_stopped,
        },
    }


def read_json(path: Path, limit: int) -> Any:
    storage.private_entry(path, nonempty=True)
    if path.stat().st_size > limit:
        raise ValueError("size")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ValueError("size")
    value = json.loads(raw, object_pairs_hook=detail_transport.unique_object)
    if storage.canonical(value).encode() != raw:
        raise ValueError("canonical")
    return value


def decode(value: Any, expected: dict[str, Any]) -> ProcessResult:
    node = value["process"]
    result = ProcessResult(
        node["returncode"],
        node["input_bytes"],
        base64.b64decode(node["stdout"]["base64"], validate=True),
        base64.b64decode(node["stderr"]["base64"], validate=True),
        node["error_code"],
        node["process_stopped"],
    )
    if storage.canonical(encode(result, expected)) != storage.canonical(value):
        raise ValueError("binding")
    return result


def read_terminal(work: Path, expected: dict[str, Any]) -> ProcessResult:
    storage.private_entry(work, directory=True)
    if {p.name for p in work.iterdir()} != {"intent.json", "capture.json"}:
        raise ValueError("incomplete")
    intent = {"schema_version": "fit_process_intent_v1", "binding": expected}
    if read_json(work / "intent.json", 4096) != intent:
        raise ValueError("intent")
    limit = 4096 + 4 * ((expected["stdout_limit"] + expected["stderr_limit"] + 4) // 3)
    value = read_json(work / "capture.json", limit)
    result = decode(value, expected)
    if not result.process_stopped:
        raise ValueError("not_stopped")
    # A visible rename is not proof that its prior directory fsync succeeded.
    storage.atomic_file(work / "intent.json", storage.canonical(intent).encode())
    storage.atomic_file(work / "capture.json", storage.canonical(value).encode())
    return result


def run(
    work: Path,
    expected: dict[str, Any],
    launch: Callable[[], ProcessResult],
) -> ProcessResult:
    """Run at most once; only fully durable, confirmed-stop capture can return.

    The dedicated directory contains intent and either terminal or interrupted
    evidence. An existing directory without a closed terminal is never reclaimed.
    The outer weekly model ledger provides the once-per-week business identity;
    this additional local reservation protects the process/evidence transition.
    """
    expected = check_binding(expected)
    if not isinstance(work, Path) or not work.is_absolute() or not callable(launch):
        raise ValueError("process_capture_binding_invalid")
    try:
        storage.private_entry(work.parent, directory=True)
        try:
            work.mkdir(mode=0o700)
        except FileExistsError:
            return read_terminal(work, expected)
        storage.private_entry(work, directory=True)
        storage.sync_dir(work.parent)
        intent = {"schema_version": "fit_process_intent_v1", "binding": expected}
        storage.atomic_file(work / "intent.json", storage.canonical(intent).encode())
        if read_json(work / "intent.json", 4096) != intent:
            raise ValueError("intent")
    except Exception:
        raise EvidenceUnavailable("process_capture_unavailable") from None

    try:
        result = launch()
    except ProcessInterrupted as exc:
        try:
            payload = encode(exc.capture, expected)
            if exc.capture.process_stopped:
                raise ValueError("inconsistent_interruption")
            storage.atomic_file(
                work / "interrupted.json", storage.canonical(payload).encode()
            )
        except Exception:
            raise EvidenceUnavailable("process_capture_unavailable") from None
        raise EvidenceUnavailable("process_capture_stop_unconfirmed") from None
    except BaseException:
        # A callable that fails without a ProcessResult has supplied no stopping
        # proof. Do not invent empty terminal logs or allow a second invocation.
        raise EvidenceUnavailable("process_capture_unavailable") from None

    try:
        payload = encode(result, expected)
        name = "capture.json" if result.process_stopped else "interrupted.json"
        storage.atomic_file(work / name, storage.canonical(payload).encode())
        if not result.process_stopped:
            raise ValueError("not_stopped")
        return read_terminal(work, expected)
    except Exception:
        raise EvidenceUnavailable("process_capture_unavailable") from None
