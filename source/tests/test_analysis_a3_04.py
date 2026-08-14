from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from src.analysis.config import AnalysisConfig
from src.analysis.harness import (
    HarnessResolutionError,
    SchemaEvidence,
    resolve_harness_bundle,
)
from src.resources import resource_path

PROJECT_ROOT = Path(__file__).parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analysis_config(root: Path) -> AnalysisConfig:
    return AnalysisConfig(
        schema_version="1",
        project_root=root,
        timezone="Asia/Hong_Kong",
        harness_root=root / "harness",
        input_schema=root / "harness/schemas/analysis_input.schema.json",
        output_schema=root / "harness/schemas/analysis_result.schema.json",
        max_context_bytes=1_000_000,
        daily_baseline_days=14,
        weekly_baseline_days=28,
        max_recent_daily_artifacts=7,
        codex_timeout_seconds=600,
        delivery_timeout_seconds=180,
        lock_path=root / "state/locks/analysis.lock",
        temp_root=root / "state/tmp/analysis",
    )


def fixture_root(tmp_path: Path) -> tuple[AnalysisConfig, SchemaEvidence]:
    shutil.copytree(resource_path("harness"), tmp_path / "harness")
    schemas = tmp_path / "harness/schemas"
    input_schema = schemas / "analysis_input.schema.json"
    output_schema = schemas / "analysis_result.schema.json"
    input_schema.write_text('{"schema_version":"input-fixture"}', encoding="utf-8")
    output_schema.write_text('{"schema_version":"output-fixture"}', encoding="utf-8")
    evidence = SchemaEvidence(
        "input-v1", digest(input_schema), "output-v1", digest(output_schema)
    )
    return analysis_config(tmp_path), evidence


@pytest.mark.parametrize(
    "route,expected",
    [
        ("daily", "harness/analysis/daily.md"),
        ("weekly", "harness/analysis/weekly.md"),
        ("revise_plan", "harness/analysis/revise-plan.md"),
        ("delivery", "harness/analysis/delivery.md"),
    ],
)
def test_fixed_allowlist_and_manifest_are_stable(
    tmp_path: Path, route: str, expected: str
) -> None:
    config, evidence = fixture_root(tmp_path)
    first = resolve_harness_bundle(config, route, evidence)  # type: ignore[arg-type]
    second = resolve_harness_bundle(config, route, evidence)  # type: ignore[arg-type]
    assert first == second
    assert [item.path_id for item in first.files] == [
        "harness/shared/HARNESS.md",
        "harness/analysis/HARNESS.md",
        expected,
    ]
    record = first.audit_record()
    assert "prompt" not in json.dumps(record) and set(record) >= {
        "harness_version",
        "files",
        "input_schema_sha256",
        "output_schema_sha256",
    }


def test_product_harness_excludes_retired_runtime_authority() -> None:
    shared = resource_path("harness/shared/HARNESS.md").read_text(encoding="utf-8")
    assert not resource_path("harness/runtime/HARNESS.md").exists()
    for required in ("UTC", "Asia/Hong_Kong", "Never pin a model name"):
        assert required in shared
    for retired in ("source/Health.xlsx", "source/HealthFit", "root `data.db`"):
        assert retired not in shared


def test_active_shared_hash_is_fixed_by_analysis_harness_manifest() -> None:
    manifest = json.loads(
        (PROJECT_ROOT / "src/analysis/harness_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    expected = digest(resource_path("harness/shared/HARNESS.md"))
    assert (
        expected != "847ec27f06e4d3955aa6064777c15870054ed9fcc61e3d406ec89f8c5fca15c9"
    )
    for bundle in manifest["bundles"].values():
        assert bundle[0] == {"path": "harness/shared/HARNESS.md", "sha256": expected}


def test_weekly_harness_requires_available_prior_artifacts_in_source_usage() -> None:
    text = resource_path("harness/analysis/weekly.md").read_text(encoding="utf-8")
    assert "prior_artifact_state.summary` is `available`" in text
    assert "artifact.prior_model_output" in text
    assert "prior_artifact_state.plan` is `available`" in text
    assert "plan.current_revision" in text
    for forbidden_device_term in (
        "Body Battery",
        "训练准备度",
        "睡眠评分",
        "睡眠秒数",
        "POOR",
        "BEHIND",
    ):
        assert forbidden_device_term in text


@pytest.mark.parametrize("route", ["daily", "weekly", "revise_plan", "delivery"])
def test_analysis_bundle_excludes_legacy_runtime_rules_and_keeps_shared_safety(
    tmp_path: Path, route: str
) -> None:
    config, evidence = fixture_root(tmp_path)
    bundle = resolve_harness_bundle(config, route, evidence)
    text = "\n".join(
        (config.project_root / item.path_id).read_text(encoding="utf-8")
        for item in bundle.files
    )
    for required in (
        "UTC",
        "Asia/Hong_Kong",
        "untrusted",
        "Do not diagnose medical conditions",
        "Never pin a model name",
    ):
        assert required in text
    for forbidden in (
        "source/Health.xlsx",
        "source/HealthFit",
        "root `data.db`",
        "rclone",
        "Google Drive",
        "runtime_input.schema",
        "runtime_result.schema",
        "Check configured TrainLab Gmail threads",
        "tracked_thread_ids",
        "send_html_self",
        "X-TrainLab-Run-ID",
    ):
        assert forbidden not in text


@pytest.mark.parametrize("route", ["mail", "runtime", "../daily", "archive"])
def test_rejects_non_analysis_routes_before_loading(tmp_path: Path, route: str) -> None:
    config, evidence = fixture_root(tmp_path)
    with pytest.raises(
        HarnessResolutionError, match="analysis_harness_route_not_allowed"
    ):
        resolve_harness_bundle(config, route, evidence)  # type: ignore[arg-type]


def test_rejects_content_drift_and_schema_hash_mismatch(tmp_path: Path) -> None:
    config, evidence = fixture_root(tmp_path)
    (tmp_path / "harness/analysis/daily.md").write_text("changed", encoding="utf-8")
    with pytest.raises(HarnessResolutionError, match="analysis_harness_content_drift"):
        resolve_harness_bundle(config, "daily", evidence)
    config, evidence = fixture_root(tmp_path / "schema")
    bad = SchemaEvidence(
        evidence.input_schema_version,
        "0" * 64,
        evidence.output_schema_version,
        evidence.output_schema_sha256,
    )
    with pytest.raises(
        HarnessResolutionError,
        match="analysis_harness_schema_hash_mismatch:input_schema",
    ):
        resolve_harness_bundle(config, "daily", bad)


def test_rejects_missing_schema_and_missing_harness_file(tmp_path: Path) -> None:
    config, evidence = fixture_root(tmp_path)
    config.output_schema.unlink()
    with pytest.raises(
        HarnessResolutionError,
        match="analysis_harness_file_missing_or_not_regular:output_schema",
    ):
        resolve_harness_bundle(config, "daily", evidence)
    config, evidence = fixture_root(tmp_path / "harness-file")
    (config.harness_root / "analysis/daily.md").unlink()
    with pytest.raises(
        HarnessResolutionError,
        match="analysis_harness_file_missing_or_not_regular:harness/analysis/daily.md",
    ):
        resolve_harness_bundle(config, "daily", evidence)


@pytest.mark.skipif(not hasattr(Path, "symlink_to"), reason="symlinks unavailable")
def test_rejects_symlink_escape_and_unsafe_harness_permissions(tmp_path: Path) -> None:
    config, evidence = fixture_root(tmp_path)
    daily = tmp_path / "harness/analysis/daily.md"
    daily.unlink()
    daily.symlink_to(tmp_path / "outside.md")
    (tmp_path / "outside.md").write_text("outside", encoding="utf-8")
    with pytest.raises(
        HarnessResolutionError, match="analysis_harness_symlink_rejected"
    ):
        resolve_harness_bundle(config, "daily", evidence)
    config, evidence = fixture_root(tmp_path / "permissions")
    (config.harness_root / "analysis/daily.md").chmod(0o666)
    with pytest.raises(
        HarnessResolutionError, match="analysis_harness_file_writable_by_group_or_other"
    ):
        resolve_harness_bundle(config, "daily", evidence)
