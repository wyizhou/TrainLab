#!/usr/bin/env python3
"""Run the one authorized M11 v4 weekly Codex call with durable evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.schema_validation import validate_payload
from skills._shared.scripts.structured_outputs_validation import (
    require_supported_schema,
)
from skills._shared.state import canonical_json

MODEL_TIMEOUT_SECONDS = 180
MAX_CAPTURE_BYTES = 2 * 1024 * 1024


def _load_coach() -> ModuleType:
    path = Path(__file__).with_name("content_first_v4.py")
    spec = importlib.util.spec_from_file_location(
        "trainlab_weekly_content_v4_contract", path
    )
    if spec is None or spec.loader is None:
        raise ValueError("weekly_model_contract_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


COACH = _load_coach()


def _load_model_context() -> ModuleType:
    path = Path(__file__).with_name("model_context_v4.py")
    spec = importlib.util.spec_from_file_location(
        "trainlab_weekly_model_context_v4_contract", path
    )
    if spec is None or spec.loader is None:
        raise ValueError("weekly_model_context_contract_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODEL_CONTEXT = _load_model_context()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _owner_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ValueError("weekly_model_directory_invalid")


def _owner_file(path: Path) -> None:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size <= 0
    ):
        raise ValueError("weekly_model_input_file_invalid")


def _existing_owner_directory(path: Path) -> None:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ValueError("weekly_model_work_directory_invalid")


def _atomic_write(path: Path, payload: bytes) -> None:
    if not payload:
        raise ValueError("weekly_model_artifact_empty")
    _owner_directory(path.parent)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _update_manifest(path: Path, values: dict[str, Any]) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update(values)
    _atomic_write(path, canonical_json(manifest).encode())
    return manifest


def _terminal_replay(final_root: Path) -> dict[str, Any] | None:
    receipt = final_root / "attempt-receipt.json"
    if not receipt.exists():
        return None
    _owner_file(receipt)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["reused"] = True
    return payload


def run_weekly_content(
    candidate_root: Path,
    *,
    executable: str = "codex",
    run_process: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Run at most once; terminal replays return the saved receipt."""

    final_root = candidate_root / "weekly-ai-attempt"
    replay = _terminal_replay(final_root) if final_root.exists() else None
    if replay is not None:
        return replay
    pending_root = candidate_root / "weekly-ai-attempt.pending"
    if pending_root.exists() or final_root.exists():
        raise ValueError("weekly_model_attempt_already_started")
    manifest_path = candidate_root / "candidate-manifest.json"
    _owner_file(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != "m11_v4_content_candidate_v2"
        or manifest.get("status") != "prepared"
        or manifest.get("model_calls_authorized") != 1
        or manifest.get("model_calls_completed") != 0
        or manifest.get("provider_calls") != 0
        or manifest.get("external_actions") != 0
    ):
        raise ValueError("weekly_model_candidate_not_prepared")
    work_root_value = manifest.get("ai_work_root")
    if not isinstance(work_root_value, str):
        raise ValueError("weekly_model_work_directory_missing")  # noqa: TRY004
    work_root = Path(work_root_value).resolve()
    resolved_candidate = candidate_root.resolve()
    if (
        work_root == resolved_candidate
        or resolved_candidate in work_root.parents
        or work_root in resolved_candidate.parents
    ):
        raise ValueError("weekly_model_work_directory_not_isolated")
    _existing_owner_directory(work_root)
    prompt_path = work_root / "prompt.txt"
    context_path = work_root / "context.json"
    schema_path = work_root / "weekly_ai_result_v3_codex.schema.json"
    for path in (prompt_path, context_path, schema_path):
        _owner_file(path)
    if {path.name for path in work_root.iterdir()} != {
        "prompt.txt",
        "context.json",
        "weekly_ai_result_v3_codex.schema.json",
    }:
        raise ValueError("weekly_model_work_directory_manifest_invalid")
    for path, key in (
        (prompt_path, "prompt_sha256"),
        (context_path, "context_sha256"),
        (schema_path, "wire_schema_sha256"),
    ):
        if file_sha256(path) != manifest.get(key):
            raise ValueError("weekly_model_frozen_input_drift")
    contracts = MODEL_CONTEXT.require_authoritative_contracts()
    authoritative_schema_path = Path(contracts["wire_schema_path"])
    authoritative_schema_sha256 = str(contracts["wire_schema_sha256"])
    context_contract_sha256 = str(contracts["context_schema_sha256"])
    training_goal_contract_sha256 = str(contracts["training_goal_schema_sha256"])
    weekly_evidence_contract_sha256 = str(contracts["weekly_evidence_schema_sha256"])
    health_fact_contract_sha256 = str(contracts["health_fact_schema_sha256"])
    if (
        manifest.get("repository_wire_schema_sha256") != authoritative_schema_sha256
        or manifest.get("context_contract_schema_sha256") != context_contract_sha256
        or manifest.get("training_goal_contract_schema_sha256")
        != training_goal_contract_sha256
        or manifest.get("weekly_evidence_contract_schema_sha256")
        != weekly_evidence_contract_sha256
        or manifest.get("health_fact_contract_schema_sha256")
        != health_fact_contract_sha256
        or schema_path.read_bytes() != authoritative_schema_path.read_bytes()
        or manifest.get("wire_schema_sha256") != authoritative_schema_sha256
    ):
        raise ValueError("weekly_model_wire_schema_source_drift")
    template_path = Path(contracts["prompt_template_path"])
    authoritative_prompt_template_sha256 = str(contracts["prompt_template_sha256"])
    if (
        manifest.get("prompt_template_sha256") != authoritative_prompt_template_sha256
        or manifest.get("repository_prompt_template_sha256")
        != authoritative_prompt_template_sha256
        or file_sha256(template_path) != authoritative_prompt_template_sha256
    ):
        raise ValueError("weekly_model_prompt_template_drift")
    goal_template_path = Path(contracts["goal_template_path"])
    authoritative_goal_template_sha256 = str(contracts["goal_template_sha256"])
    if (
        manifest.get("goal_template_sha256") != authoritative_goal_template_sha256
        or manifest.get("repository_goal_template_sha256")
        != authoritative_goal_template_sha256
        or file_sha256(goal_template_path) != authoritative_goal_template_sha256
    ):
        raise ValueError("weekly_model_goal_template_drift")
    try:
        context_value = json.loads(context_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("weekly_model_context_json_invalid") from exc
    try:
        context = MODEL_CONTEXT.require_model_context_v2(context_value)
    except ValueError as exc:
        raise ValueError("weekly_model_context_invalid") from exc
    expected_prompt = MODEL_CONTEXT.canonical_prompt(
        template_path.read_bytes(), context
    )
    if prompt_path.read_bytes() != expected_prompt:
        raise ValueError("weekly_model_prompt_context_mismatch")
    evidence = context["weekly_evidence"]
    schema = json.loads(authoritative_schema_path.read_text(encoding="utf-8"))
    require_supported_schema(schema)
    _owner_directory(pending_root)
    command = [
        executable,
        "exec",
        "-C",
        str(work_root),
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--sandbox",
        "read-only",
        "--output-schema",
        str(schema_path),
        "-",
    ]
    intent = {
        "schema_version": "m11_v4_weekly_attempt_intent_v2",
        "attempt": 1,
        "prompt_sha256": manifest["prompt_sha256"],
        "context_sha256": manifest["context_sha256"],
        "wire_schema_sha256": manifest["wire_schema_sha256"],
        "repository_wire_schema_sha256": authoritative_schema_sha256,
        "prompt_template_sha256": authoritative_prompt_template_sha256,
        "goal_template_sha256": authoritative_goal_template_sha256,
        "context_contract_schema_sha256": context_contract_sha256,
        "training_goal_contract_schema_sha256": training_goal_contract_sha256,
        "weekly_evidence_contract_schema_sha256": weekly_evidence_contract_sha256,
        "health_fact_contract_schema_sha256": health_fact_contract_sha256,
        "timeout_seconds": MODEL_TIMEOUT_SECONDS,
        "command_contract": {
            "ephemeral": True,
            "ignore_user_config": True,
            "sandbox": "read-only",
            "output_schema": "weekly_ai_result_v3_codex",
            "skip_git_repo_check": True,
        },
        "provider_calls": 0,
        "external_actions": 0,
    }
    _atomic_write(pending_root / "attempt-intent.json", canonical_json(intent).encode())
    result_status = "blocked"
    error_code: str | None = None
    stdout = b""
    stderr = b""
    try:
        completed = run_process(
            command,
            input=prompt_path.read_bytes(),
            cwd=work_root,
            capture_output=True,
            timeout=MODEL_TIMEOUT_SECONDS,
            check=False,
        )
        stdout = bytes(completed.stdout)[:MAX_CAPTURE_BYTES]
        stderr = bytes(completed.stderr)[:MAX_CAPTURE_BYTES]
        if completed.returncode != 0:
            error_code = "weekly_model_cli_failed"
        elif not stdout:
            error_code = "weekly_model_result_empty"
        else:
            try:
                payload = json.loads(stdout.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                error_code = "weekly_model_result_json_invalid"
            else:
                wire_errors = validate_payload(payload, "weekly_ai_result_v3_codex")
                business_errors = COACH.validate_weekly_ai_result_v3(payload, evidence)
                if wire_errors:
                    error_code = "weekly_model_wire_schema_invalid"
                elif business_errors:
                    error_code = "weekly_model_business_contract_invalid"
                else:
                    _atomic_write(
                        pending_root / "ai-result.json",
                        canonical_json(payload).encode(),
                    )
                    result_status = "succeeded"
    except subprocess.TimeoutExpired as exc:
        stdout = bytes(exc.stdout or b"")[:MAX_CAPTURE_BYTES]
        stderr = bytes(exc.stderr or b"")[:MAX_CAPTURE_BYTES]
        error_code = "weekly_model_timeout"
    except OSError:
        error_code = "weekly_model_cli_unavailable"
    _atomic_write(pending_root / "stdout.log", stdout or b"no stdout\n")
    _atomic_write(pending_root / "stderr.log", stderr or b"no stderr\n")
    receipt = {
        "schema_version": "m11_v4_weekly_attempt_receipt_v2",
        "status": result_status,
        "error_code": error_code,
        "attempt": 1,
        "model_calls": 1,
        "provider_calls": 0,
        "external_actions": 0,
    }
    _atomic_write(
        pending_root / "attempt-receipt.json", canonical_json(receipt).encode()
    )
    os.replace(pending_root, final_root)
    parent_fd = os.open(candidate_root, os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    _update_manifest(
        manifest_path,
        {
            "status": "model_succeeded"
            if result_status == "succeeded"
            else "model_failed",
            "model_calls_completed": 1,
            "model_attempt_receipt_sha256": file_sha256(
                final_root / "attempt-receipt.json"
            ),
        },
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--codex-executable", default="codex")
    args = parser.parse_args()
    try:
        result = run_weekly_content(
            args.candidate_root, executable=args.codex_executable
        )
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "error_code": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
