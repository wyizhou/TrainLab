#!/usr/bin/env python3
"""Build and finalize VC-010 public/private model Candidates."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.schema_validation import validate_payload
from skills._shared.state import canonical_json


class CandidateV3Error(ValueError):
    """The VC-010 Candidate cannot be safely built or finalized."""


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CandidateV3Error("m11_v4_v3_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SCRIPT_ROOT = Path(__file__).resolve().parents[2]
LEGACY = _load(
    "trainlab_m11_v4_candidate_v2_for_v3",
    Path(__file__).with_name("build_m11_v4_candidate.py"),
)
MODEL_CONTEXT = _load(
    "trainlab_m11_v4_context_for_candidate_v3",
    SCRIPT_ROOT / "training-coach/scripts/model_context_v4.py",
)
DECISION = _load(
    "trainlab_m11_v4_decision_for_candidate_v3",
    SCRIPT_ROOT / "training-coach/scripts/weekly_decision_v4.py",
)
READER = _load(
    "trainlab_m11_v4_reader_for_candidate_v3",
    Path(__file__).with_name("reader_content_v4.py"),
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        raise CandidateV3Error("m11_v4_v3_owner_file_invalid")


def _require_manifest(value: dict[str, Any]) -> None:
    errors = validate_payload(value, "m11_v4_content_candidate_v3")
    if errors:
        raise CandidateV3Error("m11_v4_v3_manifest_invalid:" + ",".join(errors[:3]))


def _contracts() -> dict[str, Any]:
    try:
        contracts = MODEL_CONTEXT.require_authoritative_contracts_v4()
        DECISION.load_and_require_repository_schema_parity()
    except (ValueError, TypeError) as exc:
        raise CandidateV3Error(str(exc)) from exc
    return contracts


def _remove_new_work_root(path: Path) -> None:
    """Remove only a work root created during this same Candidate build."""

    if path.exists():
        shutil.rmtree(path)


def _model_inputs(
    candidate_root: Path,
    context: dict[str, Any],
    *,
    candidate_kind: str,
    source_manifest_sha256: str | None,
    parent_candidate: str | None,
    private_values: dict[str, Any],
) -> dict[str, Any]:
    contracts = _contracts()
    try:
        validated_context = MODEL_CONTEXT.require_model_context_v2(context)
    except ValueError as exc:
        raise CandidateV3Error("m11_v4_v3_context_invalid") from exc
    work_root = LEGACY._separate_model_work_root(candidate_root)
    context_path = work_root / "context.json"
    prompt_path = work_root / "prompt.txt"
    wire_path = work_root / "weekly_model_decision_v1_codex.schema.json"
    prompt_template = Path(contracts["prompt_template_path"])
    LEGACY._atomic_owner_write(context_path, canonical_json(validated_context).encode())
    LEGACY._atomic_owner_write(
        prompt_path,
        MODEL_CONTEXT.canonical_prompt(prompt_template.read_bytes(), validated_context),
    )
    LEGACY._atomic_owner_write(
        wire_path, Path(contracts["wire_schema_path"]).read_bytes()
    )
    manifest = {
        "schema_version": "m11_v4_content_candidate_v3",
        "status": "prepared",
        "candidate_kind": candidate_kind,
        "ai_work_root": str(work_root),
        "prompt_sha256": _sha(prompt_path),
        "context_sha256": _sha(context_path),
        "wire_schema_sha256": _sha(wire_path),
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
        "source_manifest_sha256": source_manifest_sha256,
        "parent_candidate": parent_candidate,
        "candidate_database_sha256_before_ai": private_values.get("database_sha"),
        "candidate_database_sha256_after_ai": None,
        "raw_summary": private_values.get("raw_summary"),
        "daily_output_count": int(private_values.get("daily_output_count", 0)),
        "weekly_evidence_output_id": private_values.get("evidence_output_id"),
        "weekly_evidence_sha256": private_values.get("evidence_sha"),
        "weekly_ai_output_id": None,
        "weekly_reader_output_id": None,
        "canary_proof_sha256": private_values.get("canary_proof_sha"),
        "model_calls_authorized": 1,
        "model_calls_completed": 0,
        "model_attempt_receipt_sha256": None,
        "provider_calls": 0,
        "external_actions": 0,
    }
    _require_manifest(manifest)
    LEGACY._atomic_owner_write(
        candidate_root / "candidate-manifest.json",
        canonical_json(manifest).encode(),
    )
    return manifest


def prepare_public_candidate(
    context_path: Path, candidate_root: Path
) -> dict[str, Any]:
    if candidate_root.exists():
        raise CandidateV3Error("m11_v4_v3_candidate_exists")
    LEGACY._owner_directory(candidate_root)
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateV3Error("m11_v4_v3_public_context_invalid") from exc
    if not isinstance(context, dict):
        raise CandidateV3Error("m11_v4_v3_public_context_invalid")
    return _model_inputs(
        candidate_root,
        context,
        candidate_kind="public_canary",
        source_manifest_sha256=None,
        parent_candidate=None,
        private_values={},
    )


def verified_public_canary_proof(canary_candidate: Path) -> dict[str, Any]:
    """Close one successful public canary into a portable, hash-bound proof."""

    manifest_path = canary_candidate / "candidate-manifest.json"
    _owner_file(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _require_manifest(manifest)
    if (
        manifest["candidate_kind"] != "public_canary"
        or manifest["status"] != "model_succeeded"
        or manifest["model_calls_completed"] != 1
        or manifest["provider_calls"] != 0
        or manifest["external_actions"] != 0
        or manifest["canary_proof_sha256"] is not None
    ):
        raise CandidateV3Error("m11_v4_v3_canary_not_succeeded")
    attempt_root = canary_candidate / "weekly-ai-attempt-v3"
    receipt_path = attempt_root / "attempt-receipt.json"
    _owner_file(receipt_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if validate_payload(receipt, "m11_v4_weekly_attempt_receipt_v3") or (
        receipt["status"] != "succeeded"
        or receipt["model_calls"] != 1
        or receipt["provider_calls"] != 0
        or receipt["external_actions"] != 0
        or manifest["model_attempt_receipt_sha256"] != _sha(receipt_path)
    ):
        raise CandidateV3Error("m11_v4_v3_canary_receipt_invalid")
    artifact_fields = {
        "wire_result_sha256": attempt_root / "wire-result.json",
        "ai_result_sha256": attempt_root / "ai-result.json",
        "reader_result_sha256": attempt_root / "reader-result.json",
    }
    for field, path in artifact_fields.items():
        _owner_file(path)
        if receipt[field] != _sha(path):
            raise CandidateV3Error("m11_v4_v3_canary_result_drift")
    proof = {
        "schema_version": "m11_v4_public_canary_proof_v1",
        "status": "succeeded",
        "canary_manifest_sha256": _sha(manifest_path),
        "canary_receipt_sha256": _sha(receipt_path),
        **{field: str(receipt[field]) for field in artifact_fields},
        "model_calls": 1,
        "provider_calls": 0,
        "external_actions": 0,
    }
    if validate_payload(proof, "m11_v4_public_canary_proof_v1"):
        raise CandidateV3Error("m11_v4_v3_canary_proof_invalid")
    return proof


def prepare_private_candidate(
    parent_candidate: Path, canary_candidate: Path, candidate_root: Path
) -> dict[str, Any]:
    canary_proof = verified_public_canary_proof(canary_candidate)
    legacy_manifest = LEGACY.prepare_candidate(parent_candidate, candidate_root)
    legacy_manifest_path = candidate_root / "candidate-manifest.json"
    source_manifest_sha256 = _sha(legacy_manifest_path)
    old_work_root = Path(str(legacy_manifest["ai_work_root"]))
    context = json.loads((old_work_root / "context.json").read_text(encoding="utf-8"))
    _remove_new_work_root(old_work_root)
    proof_path = candidate_root / "canary-proof.json"
    LEGACY._atomic_owner_write(proof_path, canonical_json(canary_proof).encode())
    database = candidate_root / "source/state/trainlab.db"
    return _model_inputs(
        candidate_root,
        context,
        candidate_kind="private_weekly",
        source_manifest_sha256=source_manifest_sha256,
        parent_candidate=str(parent_candidate),
        private_values={
            "database_sha": LEGACY._sha(database),
            "raw_summary": legacy_manifest["raw_summary"],
            "daily_output_count": len(legacy_manifest["daily"]),
            "evidence_output_id": legacy_manifest["weekly_evidence_output_id"],
            "evidence_sha": legacy_manifest["weekly_evidence_sha256"],
            "canary_proof_sha": _sha(proof_path),
        },
    )


def finalize_private_candidate(candidate_root: Path) -> dict[str, Any]:
    manifest_path = candidate_root / "candidate-manifest.json"
    _owner_file(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _require_manifest(manifest)
    if manifest["candidate_kind"] != "private_weekly":
        raise CandidateV3Error("m11_v4_v3_private_candidate_required")
    if manifest["status"] == "ready_for_validation":
        return {**manifest, "reused": True}
    if (
        manifest["status"] != "model_succeeded"
        or manifest["model_calls_completed"] != 1
    ):
        raise CandidateV3Error("m11_v4_v3_model_result_unavailable")
    attempt_root = candidate_root / "weekly-ai-attempt-v3"
    receipt_path = attempt_root / "attempt-receipt.json"
    wire_path = attempt_root / "wire-result.json"
    result_path = attempt_root / "ai-result.json"
    reader_path = attempt_root / "reader-result.json"
    for path in (receipt_path, wire_path, result_path, reader_path):
        try:
            _owner_file(path)
        except (OSError, CandidateV3Error) as exc:
            raise CandidateV3Error("m11_v4_v3_internal_result_missing") from exc
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if validate_payload(receipt, "m11_v4_weekly_attempt_receipt_v3") or (
        receipt["status"] != "succeeded"
        or receipt["model_calls"] != 1
        or receipt["provider_calls"] != 0
        or receipt["external_actions"] != 0
        or manifest["model_attempt_receipt_sha256"] != _sha(receipt_path)
        or receipt["wire_result_sha256"] != _sha(wire_path)
        or receipt["ai_result_sha256"] != _sha(result_path)
        or receipt["reader_result_sha256"] != _sha(reader_path)
    ):
        raise CandidateV3Error("m11_v4_v3_internal_result_drift")
    wire_result = json.loads(wire_path.read_text(encoding="utf-8"))
    if validate_payload(wire_result, "weekly_model_decision_v1_codex"):
        raise CandidateV3Error("m11_v4_v3_wire_result_invalid")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    reader = json.loads(reader_path.read_text(encoding="utf-8"))
    database = candidate_root / "source/state/trainlab.db"
    evidence_rows = LEGACY._load_outputs(database, "weekly_training_evidence_v2")
    if (
        len(evidence_rows) != 1
        or evidence_rows[0]["output_id"] != manifest["weekly_evidence_output_id"]
        or evidence_rows[0]["sha256"] != manifest["weekly_evidence_sha256"]
    ):
        raise CandidateV3Error("m11_v4_v3_weekly_evidence_drift")
    evidence_row = evidence_rows[0]
    evidence = evidence_row["payload"]
    host_context = {"next_plan_dates": list(LEGACY.PLAN_DATES)}
    if DECISION.validate_weekly_ai_result_v4(result, evidence, host_context):
        raise CandidateV3Error("m11_v4_v3_ai_result_invalid")
    expected_reader = READER.build_weekly_reader_content_v2(result, evidence)
    if reader != expected_reader or validate_payload(
        reader, "weekly_reader_content_v2"
    ):
        raise CandidateV3Error("m11_v4_v3_reader_result_drift")
    weekly_id = LEGACY._append(
        database,
        skill_name="training-coach",
        operation="weekly_coach",
        schema_name="weekly_ai_result_v4",
        logical_key="training-coach:weekly-ai-v4:2026-08-11/2026-08-17",
        payload=result,
        output_kind="weekly_summary",
        period_start="2026-08-11",
        period_end="2026-08-17",
        lineage=[LEGACY._source_lineage(evidence_row)],
    )
    markdown = READER.render_reader_markdown(reader)
    lowfi = READER.render_lowfi_html(reader)
    reader_id = LEGACY._append(
        database,
        skill_name="training-report-publisher",
        operation="render_weekly",
        schema_name="weekly_reader_content_v2",
        logical_key="training-report-publisher:weekly-reader-v2:2026-08-11/2026-08-17",
        payload=reader,
        output_kind="report_artifact",
        period_start="2026-08-11",
        period_end="2026-08-17",
        lineage=[
            {
                "output_id": weekly_id,
                "output_sha256": LEGACY._output_sha(database, weekly_id),
            },
            LEGACY._source_lineage(evidence_row),
        ],
        text=markdown,
        html_text=lowfi,
    )
    artifact_root = candidate_root / "artifacts/weekly/2026-08-11--2026-08-17"
    LEGACY._atomic_owner_write(
        artifact_root / "reader.json", canonical_json(reader).encode()
    )
    LEGACY._atomic_owner_write(artifact_root / "report.md", markdown.encode())
    LEGACY._atomic_owner_write(artifact_root / "report.html", lowfi.encode())
    manifest.update(
        {
            "status": "ready_for_validation",
            "candidate_database_sha256_after_ai": LEGACY._sha(database),
            "weekly_ai_output_id": weekly_id,
            "weekly_reader_output_id": reader_id,
        }
    )
    _require_manifest(manifest)
    LEGACY._atomic_owner_write(manifest_path, canonical_json(manifest).encode())
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    public = subparsers.add_parser("prepare-public")
    public.add_argument("--context", type=Path, required=True)
    public.add_argument("--candidate-root", type=Path, required=True)
    private = subparsers.add_parser("prepare-private")
    private.add_argument("--parent-candidate", type=Path, required=True)
    private.add_argument("--canary-candidate", type=Path, required=True)
    private.add_argument("--candidate-root", type=Path, required=True)
    finalize = subparsers.add_parser("finalize-private")
    finalize.add_argument("--candidate-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare-public":
            result = prepare_public_candidate(args.context, args.candidate_root)
        elif args.command == "prepare-private":
            result = prepare_private_candidate(
                args.parent_candidate, args.canary_candidate, args.candidate_root
            )
        else:
            result = finalize_private_candidate(args.candidate_root)
    except (CandidateV3Error, OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "error_code": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {"status": result["status"], "provider_calls": 0, "external_actions": 0},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit("legacy_runtime_retired")
