from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from skills._shared.state import canonical_json

SOURCE = Path(__file__).resolve().parents[3]
FIXTURES = SOURCE / "tests/code/fixtures"


def _load(name: str, relative: str) -> Any:
    path = SOURCE / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BUILDER = _load(
    "trainlab_m11_v4_r18_builder_v3_test",
    "skills/training-report-publisher/scripts/build_m11_v4_candidate_v3.py",
)
RUNNER = _load(
    "trainlab_m11_v4_r18_runner_v3_test",
    "skills/training-coach/scripts/run_weekly_content_v4_v3.py",
)


def _context() -> dict[str, Any]:
    return json.loads(
        (FIXTURES / "m11_v4_public_weekly_model_context_v3.json").read_text()
    )


def _decision() -> dict[str, Any]:
    return json.loads(
        (FIXTURES / "m11_v4_public_weekly_model_decision_v1.json").read_text()
    )


def _owner_write(path: Path, value: object) -> None:
    path.write_text(canonical_json(value), encoding="utf-8")
    path.chmod(0o600)


def _candidate(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    context_path = tmp_path / "context.json"
    _owner_write(context_path, _context())
    root = tmp_path / "candidate"
    BUILDER.prepare_public_candidate(context_path, root)
    return root


def test_public_canary_completes_four_layer_validation_and_replays(
    tmp_path: Path,
) -> None:
    root = _candidate(tmp_path)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            returncode=0,
            stdout=canonical_json(_decision()).encode(),
            stderr=b"",
        )

    receipt = RUNNER.run_weekly_content_v3(
        root, executable="codex", run_process=fake_run
    )
    assert receipt["status"] == "succeeded"
    assert calls == 1
    attempt = root / "weekly-ai-attempt-v3"
    assert {
        "attempt-intent.json",
        "wire-result.json",
        "ai-result.json",
        "reader-result.json",
        "stdout.log",
        "stderr.log",
        "attempt-receipt.json",
    } == {path.name for path in attempt.iterdir()}
    result = json.loads((attempt / "ai-result.json").read_text())
    assert result["period"]["plan_start_date"] == "2026-08-19"
    assert result["plan_dates"]["day_7"] == "2026-08-25"
    replay = RUNNER.run_weekly_content_v3(
        root,
        executable="codex",
        run_process=lambda *_args, **_kwargs: pytest.fail("model called on replay"),
    )
    assert replay["reused"] is True
    assert calls == 1


@pytest.mark.parametrize("field", ["period", "date", "status"])
def test_host_owned_fields_fail_wire_without_ai_result(
    tmp_path: Path, field: str
) -> None:
    root = _candidate(tmp_path)
    value = _decision()
    value[field] = "2026-08-11"
    receipt = RUNNER.run_weekly_content_v3(
        root,
        run_process=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=canonical_json(value).encode(), stderr=b""
        ),
    )
    assert receipt["error_code"] == "weekly_model_v3_wire_schema_invalid"
    attempt = root / "weekly-ai-attempt-v3"
    assert (attempt / "wire-result.json").is_file()
    assert not (attempt / "ai-result.json").exists()
    assert not (attempt / "reader-result.json").exists()


def test_r17_missing_recovery_is_closed_by_wire_schema(tmp_path: Path) -> None:
    root = _candidate(tmp_path)
    value = _decision()
    del value["training_plan"]["days"]["day_2"]["steps"]["recovery"]
    receipt = RUNNER.run_weekly_content_v3(
        root,
        run_process=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=canonical_json(value).encode(), stderr=b""
        ),
    )
    assert receipt["error_code"] == "weekly_model_v3_wire_schema_invalid"


def test_r17_free_text_historical_bpm_is_field_level_business_failure(
    tmp_path: Path,
) -> None:
    root = _candidate(tmp_path)
    value = _decision()
    value["health_review"] = "历史静息心率 48 bpm。"
    receipt = RUNNER.run_weekly_content_v3(
        root,
        run_process=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=canonical_json(value).encode(), stderr=b""
        ),
    )
    assert receipt["error_code"] == "weekly_model_v3_business_contract_invalid"
    reader = root / "weekly-ai-attempt-v3/reader-result.json"
    assert not reader.exists()


def test_preflight_drift_calls_no_model_and_creates_no_attempt(tmp_path: Path) -> None:
    root = _candidate(tmp_path)
    manifest_path = root / "candidate-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["business_schema_sha256"] = "0" * 64
    _owner_write(manifest_path, manifest)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="authoritative_contract_drift"):
        RUNNER.run_weekly_content_v3(root, run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt-v3.pending").exists()
    assert not (root / "weekly-ai-attempt-v3").exists()


def test_prompt_and_manifest_drift_still_calls_no_model_or_attempt(
    tmp_path: Path,
) -> None:
    root = _candidate(tmp_path)
    manifest_path = root / "candidate-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    prompt_path = Path(manifest["ai_work_root"]) / "prompt.txt"
    prompt_path.write_bytes(prompt_path.read_bytes().replace(b'"day_7"', b'"day_x"', 1))
    prompt_path.chmod(0o600)
    manifest["prompt_sha256"] = RUNNER.file_sha256(prompt_path)
    _owner_write(manifest_path, manifest)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="prompt_context_mismatch"):
        RUNNER.run_weekly_content_v3(root, run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt-v3.pending").exists()
    assert not (root / "weekly-ai-attempt-v3").exists()


def test_builder_parity_failure_creates_no_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context_path = tmp_path / "context.json"
    _owner_write(context_path, _context())
    root = tmp_path / "candidate"

    def fail_contracts() -> dict[str, Any]:
        raise BUILDER.CandidateV3Error("weekly_prompt_schema_semantic_parity_failed")

    monkeypatch.setattr(BUILDER, "_contracts", fail_contracts)
    with pytest.raises(
        BUILDER.CandidateV3Error,
        match="weekly_prompt_schema_semantic_parity_failed",
    ):
        BUILDER.prepare_public_candidate(context_path, root)
    assert not root.exists()


@pytest.mark.parametrize("marker_kind", ["directory", "file"])
def test_builder_rejects_git_ancestry_before_candidate_creation(
    tmp_path: Path, marker_kind: str
) -> None:
    git_root = tmp_path / "git-root"
    git_root.mkdir()
    marker = git_root / ".git"
    if marker_kind == "directory":
        marker.mkdir()
    else:
        marker.write_text("gitdir: /private/nonexistent\n", encoding="utf-8")
    context_path = git_root / "context.json"
    _owner_write(context_path, _context())
    root = git_root / "candidate"
    with pytest.raises(BUILDER.CandidateV3Error, match="work_root_git_forbidden"):
        BUILDER.prepare_public_candidate(context_path, root)
    assert not root.exists()


@pytest.mark.parametrize("marker_kind", ["directory", "file"])
def test_runner_rejects_git_ancestry_before_pending_or_model(
    tmp_path: Path, marker_kind: str
) -> None:
    root = _candidate(tmp_path)
    marker = tmp_path / ".git"
    if marker_kind == "directory":
        marker.mkdir()
    else:
        marker.write_text("gitdir: /private/nonexistent\n", encoding="utf-8")
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            returncode=0,
            stdout=canonical_json(_decision()).encode(),
            stderr=b"",
        )

    with pytest.raises(ValueError, match="work_root_git_forbidden"):
        RUNNER.run_weekly_content_v3(root, run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt-v3.pending").exists()
    assert not (root / "weekly-ai-attempt-v3").exists()


def test_synchronized_schema_prompt_drift_calls_no_model_or_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _candidate(tmp_path)
    schema_root = SOURCE / "skills/_shared/schemas"
    prompt_path = SOURCE / "skills/_shared/prompts/weekly-content-v4-v5.txt"
    business = json.loads(
        (schema_root / "weekly_model_decision_v1.schema.json").read_text()
    )
    host = json.loads((schema_root / "weekly_ai_result_v4.schema.json").read_text())
    business["$defs"]["text"]["maxLength"] = 200
    wire = RUNNER.DECISION.project_wire_schema(business)

    def reject_synchronized_drift() -> dict[str, Any]:
        RUNNER.DECISION.require_prompt_schema_semantic_parity(
            prompt_path.read_bytes(), business, wire, host
        )
        return {}

    monkeypatch.setattr(
        RUNNER.DECISION,
        "load_and_require_repository_schema_parity",
        reject_synchronized_drift,
    )
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="weekly_prompt_schema_semantic_parity"):
        RUNNER.run_weekly_content_v3(root, run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt-v3.pending").exists()
    assert not (root / "weekly-ai-attempt-v3").exists()


@pytest.mark.parametrize("field", ["technique_notes", "stop_conditions"])
def test_rest_empty_arrays_are_business_failures_without_final_results(
    tmp_path: Path, field: str
) -> None:
    root = _candidate(tmp_path)
    value = _decision()
    rest = value["training_plan"]["days"]["day_4"]
    assert rest["activity_kind"] == "rest"
    rest[field] = []
    receipt = RUNNER.run_weekly_content_v3(
        root,
        run_process=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=canonical_json(value).encode(),
            stderr=b"",
        ),
    )
    assert receipt["error_code"] == "weekly_model_v3_business_contract_invalid"
    attempt = root / "weekly-ai-attempt-v3"
    assert (attempt / "wire-result.json").is_file()
    assert not (attempt / "ai-result.json").exists()
    assert not (attempt / "reader-result.json").exists()


def test_private_finalizer_has_no_external_result_path() -> None:
    parameters = inspect.signature(BUILDER.finalize_private_candidate).parameters
    assert tuple(parameters) == ("candidate_root",)
    assert "ai_work_root" not in inspect.getsource(BUILDER.finalize_private_candidate)


def test_private_runner_requires_durable_public_canary_proof(
    tmp_path: Path,
) -> None:
    root = _candidate(tmp_path)
    manifest_path = root / "candidate-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["candidate_kind"] = "private_weekly"
    _owner_write(manifest_path, manifest)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            returncode=0,
            stdout=canonical_json(_decision()).encode(),
            stderr=b"",
        )

    with pytest.raises(ValueError, match="canary_proof_missing"):
        RUNNER.run_weekly_content_v3(root, run_process=fake_run)
    assert calls == 0
    assert not (root / "weekly-ai-attempt-v3.pending").exists()
    assert not (root / "weekly-ai-attempt-v3").exists()


def test_public_canary_proof_is_closed_and_tamper_evident(tmp_path: Path) -> None:
    root = _candidate(tmp_path)
    receipt = RUNNER.run_weekly_content_v3(
        root,
        run_process=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=canonical_json(_decision()).encode(),
            stderr=b"",
        ),
    )
    assert receipt["status"] == "succeeded"
    proof = BUILDER.verified_public_canary_proof(root)
    assert proof["status"] == "succeeded"
    assert proof["model_calls"] == 1
    attempt = root / "weekly-ai-attempt-v3"
    response_path = attempt / "ai-result.json"
    original = response_path.read_bytes()
    response_path.write_bytes(original + b"\n")
    with pytest.raises(BUILDER.CandidateV3Error, match="canary_result_drift"):
        BUILDER.verified_public_canary_proof(root)


def test_private_runner_accepts_candidate_internal_canary_proof(
    tmp_path: Path,
) -> None:
    canary = _candidate(tmp_path / "canary-source")
    receipt = RUNNER.run_weekly_content_v3(
        canary,
        run_process=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=canonical_json(_decision()).encode(),
            stderr=b"",
        ),
    )
    assert receipt["status"] == "succeeded"
    proof = BUILDER.verified_public_canary_proof(canary)

    private = _candidate(tmp_path / "private-source")
    proof_path = private / "canary-proof.json"
    _owner_write(proof_path, proof)
    manifest_path = private / "candidate-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["candidate_kind"] = "private_weekly"
    manifest["canary_proof_sha256"] = RUNNER.file_sha256(proof_path)
    _owner_write(manifest_path, manifest)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            returncode=0,
            stdout=canonical_json(_decision()).encode(),
            stderr=b"",
        )

    private_receipt = RUNNER.run_weekly_content_v3(
        private,
        expected_canary_proof_sha256=RUNNER.file_sha256(proof_path),
        run_process=fake_run,
    )
    assert private_receipt["status"] == "succeeded"
    assert calls == 1


def test_private_runner_requires_candidate_external_canary_proof_authority(
    tmp_path: Path,
) -> None:
    canary = _candidate(tmp_path / "canary-source")
    receipt = RUNNER.run_weekly_content_v3(
        canary,
        run_process=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=canonical_json(_decision()).encode(),
            stderr=b"",
        ),
    )
    assert receipt["status"] == "succeeded"
    proof = BUILDER.verified_public_canary_proof(canary)
    private = _candidate(tmp_path / "private-source")
    proof_path = private / "canary-proof.json"
    _owner_write(proof_path, proof)
    manifest_path = private / "candidate-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["candidate_kind"] = "private_weekly"
    manifest["canary_proof_sha256"] = RUNNER.file_sha256(proof_path)
    _owner_write(manifest_path, manifest)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="canary_proof_authority_required"):
        RUNNER.run_weekly_content_v3(private, run_process=fake_run)
    assert calls == 0
    assert not (private / "weekly-ai-attempt-v3.pending").exists()
    assert not (private / "weekly-ai-attempt-v3").exists()


def test_coordinated_canary_proof_and_manifest_rewrite_is_rejected(
    tmp_path: Path,
) -> None:
    canary = _candidate(tmp_path / "canary-source")
    receipt = RUNNER.run_weekly_content_v3(
        canary,
        run_process=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=canonical_json(_decision()).encode(),
            stderr=b"",
        ),
    )
    assert receipt["status"] == "succeeded"
    proof = BUILDER.verified_public_canary_proof(canary)
    private = _candidate(tmp_path / "private-source")
    proof_path = private / "canary-proof.json"
    _owner_write(proof_path, proof)
    trusted_proof_sha = RUNNER.file_sha256(proof_path)
    manifest_path = private / "candidate-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["candidate_kind"] = "private_weekly"
    manifest["canary_proof_sha256"] = trusted_proof_sha
    _owner_write(manifest_path, manifest)

    forged = dict(proof)
    for field in (
        "canary_manifest_sha256",
        "canary_receipt_sha256",
        "wire_result_sha256",
        "ai_result_sha256",
        "reader_result_sha256",
    ):
        forged[field] = "f" * 64
    _owner_write(proof_path, forged)
    manifest["canary_proof_sha256"] = RUNNER.file_sha256(proof_path)
    _owner_write(manifest_path, manifest)
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    with pytest.raises(ValueError, match="canary_proof_authority_mismatch"):
        RUNNER.run_weekly_content_v3(
            private,
            expected_canary_proof_sha256=trusted_proof_sha,
            run_process=fake_run,
        )
    assert calls == 0
    assert not (private / "weekly-ai-attempt-v3.pending").exists()
    assert not (private / "weekly-ai-attempt-v3").exists()


def test_business_text_change_cannot_change_host_dates(tmp_path: Path) -> None:
    root = _candidate(tmp_path)
    value = deepcopy(_decision())
    value["week_conclusion"] = "公开合成结论已更新，但日期仍由 Host 决定。"
    receipt = RUNNER.run_weekly_content_v3(
        root,
        run_process=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=canonical_json(value).encode(), stderr=b""
        ),
    )
    assert receipt["status"] == "succeeded"
    result = json.loads((root / "weekly-ai-attempt-v3/ai-result.json").read_text())
    assert result["period"]["activity_start_date"] == "2026-08-11"
    assert result["plan_dates"]["day_1"] == "2026-08-19"
