#!/usr/bin/env python3
"""Run one VC-010 weekly model decision and assemble Host-owned facts."""

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
from skills._shared.state import canonical_json

MODEL_TIMEOUT_SECONDS = 180
MAX_CAPTURE_BYTES = 2 * 1024 * 1024


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("weekly_model_v3_dependency_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


DECISION = _load(
    "trainlab_m11_v4_runner_v3_decision",
    Path(__file__).with_name("weekly_decision_v4.py"),
)
MODEL_CONTEXT = _load(
    "trainlab_m11_v4_runner_v3_context",
    Path(__file__).with_name("model_context_v4.py"),
)
READER = _load(
    "trainlab_m11_v4_runner_v3_reader",
    Path(__file__).resolve().parents[2]
    / "training-report-publisher/scripts/reader_content_v4.py",
)


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
        raise ValueError("weekly_model_v3_directory_invalid")


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
        raise ValueError("weekly_model_v3_file_invalid")


def _atomic_write(path: Path, payload: bytes) -> None:
    if not payload:
        raise ValueError("weekly_model_v3_artifact_empty")
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


def _validated_manifest(path: Path) -> dict[str, Any]:
    _owner_file(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_payload(value, "m11_v4_content_candidate_v3")
    if errors:
        raise ValueError("weekly_model_v3_manifest_invalid")
    return value


def _update_manifest(path: Path, values: dict[str, Any]) -> dict[str, Any]:
    manifest = _validated_manifest(path)
    manifest.update(values)
    errors = validate_payload(manifest, "m11_v4_content_candidate_v3")
    if errors:
        raise ValueError("weekly_model_v3_manifest_update_invalid")
    _atomic_write(path, canonical_json(manifest).encode())
    return manifest


def _terminal_replay(final_root: Path) -> dict[str, Any] | None:
    receipt_path = final_root / "attempt-receipt.json"
    if not receipt_path.exists():
        return None
    _owner_file(receipt_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if validate_payload(receipt, "m11_v4_weekly_attempt_receipt_v3"):
        raise ValueError("weekly_model_v3_receipt_invalid")
    return {**receipt, "reused": True}


def _preflight(candidate_root: Path) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    manifest = _validated_manifest(candidate_root / "candidate-manifest.json")
    if (
        manifest["status"] != "prepared"
        or manifest["model_calls_authorized"] != 1
        or manifest["model_calls_completed"] != 0
        or manifest["provider_calls"] != 0
        or manifest["external_actions"] != 0
    ):
        raise ValueError("weekly_model_v3_candidate_not_prepared")
    contracts = MODEL_CONTEXT.require_authoritative_contracts_v4()
    DECISION.load_and_require_repository_schema_parity()
    expected_hashes = {
        "wire_schema_sha256": contracts["wire_schema_sha256"],
        "business_schema_sha256": contracts["business_schema_sha256"],
        "ai_result_schema_sha256": contracts["ai_result_schema_sha256"],
        "reader_schema_sha256": contracts["reader_schema_sha256"],
        "prompt_template_sha256": contracts["prompt_template_sha256"],
        "context_contract_schema_sha256": contracts["context_schema_sha256"],
        "training_goal_contract_schema_sha256": contracts[
            "training_goal_schema_sha256"
        ],
        "weekly_evidence_contract_schema_sha256": contracts[
            "weekly_evidence_schema_sha256"
        ],
        "health_fact_contract_schema_sha256": contracts["health_fact_schema_sha256"],
        "goal_template_sha256": contracts["goal_template_sha256"],
    }
    if any(manifest[key] != value for key, value in expected_hashes.items()):
        raise ValueError("weekly_model_v3_authoritative_contract_drift")
    proof_path = candidate_root / "canary-proof.json"
    if manifest["candidate_kind"] == "public_canary":
        if manifest["canary_proof_sha256"] is not None or proof_path.exists():
            raise ValueError("weekly_model_v3_canary_proof_unexpected")
    else:
        if manifest["canary_proof_sha256"] is None or not proof_path.exists():
            raise ValueError("weekly_model_v3_canary_proof_missing")
        _owner_file(proof_path)
        if file_sha256(proof_path) != manifest["canary_proof_sha256"]:
            raise ValueError("weekly_model_v3_canary_proof_drift")
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        if validate_payload(proof, "m11_v4_public_canary_proof_v1") or (
            proof["status"] != "succeeded"
            or proof["model_calls"] != 1
            or proof["provider_calls"] != 0
            or proof["external_actions"] != 0
        ):
            raise ValueError("weekly_model_v3_canary_proof_invalid")
    work_root = Path(manifest["ai_work_root"]).resolve()
    resolved_candidate = candidate_root.resolve()
    if (
        work_root == resolved_candidate
        or resolved_candidate in work_root.parents
        or work_root in resolved_candidate.parents
    ):
        raise ValueError("weekly_model_v3_work_root_not_isolated")
    metadata = work_root.lstat()
    if (
        work_root.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ValueError("weekly_model_v3_work_root_invalid")
    prompt_path = work_root / "prompt.txt"
    context_path = work_root / "context.json"
    wire_path = work_root / "weekly_model_decision_v1_codex.schema.json"
    if {path.name for path in work_root.iterdir()} != {
        prompt_path.name,
        context_path.name,
        wire_path.name,
    }:
        raise ValueError("weekly_model_v3_work_manifest_invalid")
    for path in (prompt_path, context_path, wire_path):
        _owner_file(path)
    if (
        file_sha256(prompt_path) != manifest["prompt_sha256"]
        or file_sha256(context_path) != manifest["context_sha256"]
        or file_sha256(wire_path) != manifest["wire_schema_sha256"]
        or wire_path.read_bytes() != Path(contracts["wire_schema_path"]).read_bytes()
    ):
        raise ValueError("weekly_model_v3_frozen_input_drift")
    context = MODEL_CONTEXT.require_model_context_v2(
        json.loads(context_path.read_text(encoding="utf-8"))
    )
    expected_prompt = MODEL_CONTEXT.canonical_prompt(
        Path(contracts["prompt_template_path"]).read_bytes(), context
    )
    if prompt_path.read_bytes() != expected_prompt:
        raise ValueError("weekly_model_v3_prompt_context_mismatch")
    return manifest, work_root, context


def run_weekly_content_v3(
    candidate_root: Path,
    *,
    executable: str = "codex",
    run_process: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Call the model once, then validate wire, Host envelope and Reader."""

    final_root = candidate_root / "weekly-ai-attempt-v3"
    if final_root.exists():
        replay = _terminal_replay(final_root)
        if replay is not None:
            return replay
    pending_root = candidate_root / "weekly-ai-attempt-v3.pending"
    if pending_root.exists() or final_root.exists():
        raise ValueError("weekly_model_v3_attempt_already_started")
    manifest, work_root, context = _preflight(candidate_root)
    manifest_path = candidate_root / "candidate-manifest.json"
    prompt_path = work_root / "prompt.txt"
    wire_path = work_root / "weekly_model_decision_v1_codex.schema.json"
    _owner_directory(pending_root)
    intent = {
        "schema_version": "m11_v4_weekly_attempt_intent_v3",
        "attempt": 1,
        "candidate_kind": manifest["candidate_kind"],
        "prompt_sha256": manifest["prompt_sha256"],
        "context_sha256": manifest["context_sha256"],
        "wire_schema_sha256": manifest["wire_schema_sha256"],
        "business_schema_sha256": manifest["business_schema_sha256"],
        "ai_result_schema_sha256": manifest["ai_result_schema_sha256"],
        "reader_schema_sha256": manifest["reader_schema_sha256"],
        "prompt_template_sha256": manifest["prompt_template_sha256"],
        "canary_proof_sha256": manifest["canary_proof_sha256"],
        "timeout_seconds": MODEL_TIMEOUT_SECONDS,
        "command_contract": {
            "ephemeral": True,
            "ignore_user_config": True,
            "sandbox": "read-only",
            "output_schema": "weekly_model_decision_v1_codex",
            "skip_git_repo_check": True,
        },
        "provider_calls": 0,
        "external_actions": 0,
    }
    if validate_payload(intent, "m11_v4_weekly_attempt_intent_v3"):
        raise ValueError("weekly_model_v3_intent_invalid")
    _atomic_write(pending_root / "attempt-intent.json", canonical_json(intent).encode())
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
        str(wire_path),
        "-",
    ]
    status = "blocked"
    error_code: str | None = None
    stdout = b""
    stderr = b""
    wire_sha: str | None = None
    ai_sha: str | None = None
    reader_sha: str | None = None
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
            error_code = "weekly_model_v3_cli_failed"
        elif not stdout:
            error_code = "weekly_model_v3_result_empty"
        else:
            try:
                decision = json.loads(stdout.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                error_code = "weekly_model_v3_result_json_invalid"
            else:
                wire_result_path = pending_root / "wire-result.json"
                _atomic_write(wire_result_path, canonical_json(decision).encode())
                wire_sha = file_sha256(wire_result_path)
                wire_errors = validate_payload(
                    decision, "weekly_model_decision_v1_codex"
                )
                business_errors = DECISION.validate_weekly_model_decision_v1(
                    decision, context["weekly_evidence"]
                )
                if wire_errors:
                    error_code = "weekly_model_v3_wire_schema_invalid"
                elif business_errors:
                    error_code = "weekly_model_v3_business_contract_invalid"
                else:
                    result = DECISION.assemble_weekly_ai_result_v4(decision, context)
                    reader = READER.build_weekly_reader_content_v2(
                        result, context["weekly_evidence"]
                    )
                    if validate_payload(result, "weekly_ai_result_v4"):
                        error_code = "weekly_model_v3_host_envelope_invalid"
                    elif validate_payload(reader, "weekly_reader_content_v2"):
                        error_code = "weekly_model_v3_reader_invalid"
                    else:
                        result_path = pending_root / "ai-result.json"
                        reader_path = pending_root / "reader-result.json"
                        _atomic_write(result_path, canonical_json(result).encode())
                        _atomic_write(reader_path, canonical_json(reader).encode())
                        ai_sha = file_sha256(result_path)
                        reader_sha = file_sha256(reader_path)
                        status = "succeeded"
    except subprocess.TimeoutExpired as exc:
        stdout = bytes(exc.stdout or b"")[:MAX_CAPTURE_BYTES]
        stderr = bytes(exc.stderr or b"")[:MAX_CAPTURE_BYTES]
        error_code = "weekly_model_v3_timeout"
    except OSError:
        error_code = "weekly_model_v3_cli_unavailable"
    _atomic_write(pending_root / "stdout.log", stdout or b"no stdout\n")
    _atomic_write(pending_root / "stderr.log", stderr or b"no stderr\n")
    receipt = {
        "schema_version": "m11_v4_weekly_attempt_receipt_v3",
        "status": status,
        "error_code": error_code,
        "attempt": 1,
        "model_calls": 1,
        "wire_result_sha256": wire_sha,
        "ai_result_sha256": ai_sha,
        "reader_result_sha256": reader_sha,
        "provider_calls": 0,
        "external_actions": 0,
    }
    if validate_payload(receipt, "m11_v4_weekly_attempt_receipt_v3"):
        raise ValueError("weekly_model_v3_receipt_invalid")
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
            "status": "model_succeeded" if status == "succeeded" else "model_failed",
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
        result = run_weekly_content_v3(
            args.candidate_root, executable=args.codex_executable
        )
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "error_code": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
