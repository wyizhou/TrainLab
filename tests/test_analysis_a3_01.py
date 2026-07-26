from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from trainlab.analysis.boundary import (
    CURRENT_PRODUCTION_ENTRYPOINT,
    FROZEN_CONTRACT_SHA256,
    INITIAL_MIGRATION_BASELINE,
    AnalysisBoundaryError,
    build_module_manifest,
    verify_contract_snapshot,
    verify_import_boundary,
)


PROJECT_ROOT = Path(__file__).parents[1]
ANALYSIS_PACKAGE = PROJECT_ROOT / "src" / "trainlab" / "analysis"


def test_manifest_records_frozen_contracts_and_migration_baseline() -> None:
    manifest = build_module_manifest(PROJECT_ROOT)
    checked_in = json.loads((ANALYSIS_PACKAGE / "module_manifest.json").read_text(encoding="utf-8"))

    assert {item.relative_path: item.sha256 for item in manifest.contracts} == FROZEN_CONTRACT_SHA256
    assert checked_in["contracts"] == FROZEN_CONTRACT_SHA256
    assert checked_in["production_entrypoint"] == CURRENT_PRODUCTION_ENTRYPOINT == "trainlab run"
    assert {item.relative_path: item.sha256 for item in manifest.migration_baseline} == INITIAL_MIGRATION_BASELINE
    assert checked_in["migration_baseline"] == INITIAL_MIGRATION_BASELINE
    assert checked_in["capabilities"] == {
        "network": False,
        "database_read": False,
        "database_write": False,
        "subprocess": False,
        "codex": False,
        "gmail_mcp": False,
        "scheduler": False,
    }
    assert json.loads(manifest.to_json())["layer"] == "analysis"


def test_initial_migration_baseline_is_not_recomputed_from_current_harness(tmp_path: Path) -> None:
    """A3-01 baseline is immutable historical evidence, not active state."""
    for relative_path in FROZEN_CONTRACT_SHA256:
        source = PROJECT_ROOT / relative_path
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for relative_path in INITIAL_MIGRATION_BASELINE:
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("intentionally different current content", encoding="utf-8")

    manifest = build_module_manifest(tmp_path)

    assert {item.relative_path: item.sha256 for item in manifest.migration_baseline} == INITIAL_MIGRATION_BASELINE


def test_contract_hash_mismatch_blocks_the_boundary(tmp_path: Path) -> None:
    relative_path = next(iter(FROZEN_CONTRACT_SHA256))
    contract = tmp_path / relative_path
    contract.parent.mkdir(parents=True)
    contract.write_text("changed", encoding="utf-8")

    with pytest.raises(AnalysisBoundaryError, match="analysis_contract_hash_mismatch"):
        verify_contract_snapshot(tmp_path)


def test_import_boundary_is_empty_and_reproducible() -> None:
    first = verify_import_boundary(ANALYSIS_PACKAGE)
    second = verify_import_boundary(ANALYSIS_PACKAGE)

    assert first == second
    assert set(first) == {
        "__init__.py",
        "boundary.py",
        "cli.py",
        "config.py",
        "context.py",
        "contracts.py",
        "daily.py",
        "delivery.py",
        "delivery_service.py",
        "features.py",
        "gmail_delivery.py",
        "harness.py",
        "publisher.py",
        "quality_gate.py",
        "result_validation.py",
        "run_state.py",
        "runner.py",
        "runtime.py",
        "safety_rules.py",
        "service.py",
        "stable_views.py",
        "weekly.py",
    }
    assert all(not imported for imported in first.values())


def test_import_boundary_blocks_legacy_adapter_import(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("from trainlab import ingest\n", encoding="utf-8")

    with pytest.raises(AnalysisBoundaryError, match="analysis_forbidden_import:.*trainlab.ingest"):
        verify_import_boundary(tmp_path)


def test_shared_mcp_exception_is_limited_to_gmail_delivery_module(tmp_path: Path) -> None:
    (tmp_path / "daily.py").write_text(
        "from trainlab.mcp import StdioMCPClient\n", encoding="utf-8"
    )
    with pytest.raises(AnalysisBoundaryError, match="analysis_forbidden_import:.*trainlab.mcp"):
        verify_import_boundary(tmp_path)
