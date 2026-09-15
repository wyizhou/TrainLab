"""The approved scope change retires the old route, not its safety evidence."""

import ast
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_old_public_prompt_and_executors_have_left_the_active_tree() -> None:
    for relative in (
        "skills/_shared/prompts/auto.txt",
        "skills/_shared/state.py",
        "skills/_shared/scripts/archive_legacy.py",
        "skills/_shared/scripts/offline_workflow.py",
        "skills/_shared/scripts/resolve_slot.py",
        "config.json",
    ):
        assert not (ROOT / relative).exists()
    from skills._shared.fit_weekly import history_archive, legacy_import

    assert not hasattr(legacy_import, "main")
    assert not any(
        hasattr(history_archive, name)
        for name in ("main", "create_archive", "restore_archive")
    )
    assert (ROOT / "skills/_shared/fit_weekly/__main__.py").is_file()


def test_transition_does_not_claim_new_runtime_is_ready() -> None:
    text = (ROOT / "AGENTS.md").read_text()
    assert "M12" in text and "尚未" in text
    assert "旧运行入口已停用" in text
    assert "data-backup" in text
    assert "不得" in text


def test_every_legacy_scenario_has_an_explicit_current_disposition() -> None:
    manifest = json.loads((ROOT / "docs/legacy-test-mapping.json").read_text())
    assert manifest["schema_version"] == "m12_legacy_test_mapping_v3"
    assert manifest["contract_version"] == "RUN-VC-001"
    assert manifest["baseline_contract_version"] == "VC-005"
    rows = manifest["files"]
    assert len({row["path"] for row in rows}) == len(rows)
    known_nodes = {}
    for path in (ROOT / "tests/code").rglob("test_*.py"):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                known_nodes[f"{path.relative_to(ROOT)}::{node.name}"] = node
    identities = set()
    for row in rows:
        assert len(row["baseline_sha256"]) == 64
        assert row["scenarios"]
        assert len(row["scenarios"]) == row["baseline_function_count"]
        path = ROOT / row["path"]
        if row["file_status"] == "retired":
            assert not path.exists()
        else:
            assert row["file_status"] == "current"
            assert path.is_file()
            assert (
                hashlib.sha256(path.read_bytes()).hexdigest() == row["current_sha256"]
            )
        for scenario in row["scenarios"]:
            identity = f"{row['path']}::{scenario['function']}"
            assert identity not in identities
            identities.add(identity)
            assert scenario["criterion_ids"] and scenario["reason"]
            assert scenario["disposition"] in {"retain", "migrate", "cancel"}
            assert scenario["exit_task"] == "M12-R6-5"
            assert not scenario["proposed_nodes"]
            assert {"RET-001", "RET-002", "A-023"} <= set(scenario["criterion_ids"])
            assert not {"RET-004", "RET-005"} & set(scenario["criterion_ids"])
            review = scenario["r6_review"]
            assert len(review["original_function_sha256"]) == 64
            assert review["original_assertions_and_exception_contexts"]
            assert review["parameter_scope"]
            for replacement in scenario["existing_nodes"]:
                assert replacement in known_nodes
            if scenario["disposition"] in {"retain", "migrate"}:
                assert scenario["existing_nodes"]
            assert {target["node"] for target in review["targets"]} == set(
                scenario["existing_nodes"]
            )
            for target in review["targets"]:
                path, _ = target["node"].split("::")
                source = ast.get_source_segment(
                    (ROOT / path).read_text(), known_nodes[target["node"]]
                )
                assert source is not None
                assert (
                    hashlib.sha256(source.encode()).hexdigest()
                    == target["function_sha256"]
                )
                delegates = target["delegated_assertions"]
                assert target["assertions_and_exception_contexts"] or delegates
                for delegate in delegates:
                    path, name = delegate["node"].split("::")
                    assert name in source
                    called = ast.get_source_segment(
                        (ROOT / path).read_text(), known_nodes[delegate["node"]]
                    )
                    assert called is not None
                    assert (
                        hashlib.sha256(called.encode()).hexdigest()
                        == delegate["function_sha256"]
                    )
                    assert delegate["assertions_and_exception_contexts"]
    assert len(identities) == manifest["baseline_function_count"]
    assert len(rows) == 39 and len(identities) == 528


def test_current_test_inventory_does_not_infer_business_from_filename() -> None:
    manifest = json.loads((ROOT / "docs/legacy-test-mapping.json").read_text())
    actual = sorted(
        p.relative_to(ROOT).as_posix() for p in (ROOT / "tests/code").rglob("test_*.py")
    )
    assert actual == manifest["active_test_files"]
    assert "tests/code/unit/test_garmin_cached_auth.py" in actual
    assert "tests/code/unit/test_structured_outputs_contract.py" in actual
    assert "tests/code/unit/test_gmail_auth.py" in actual


def test_retired_resources_cannot_remain_as_a_second_runtime() -> None:
    manifest = json.loads((ROOT / "docs/legacy-test-mapping.json").read_text())
    assert manifest["retired_resources"]
    for resource in manifest["retired_resources"]:
        assert len(resource["sha256"]) == 64
        assert resource["criterion_ids"] and resource["reason"]
        assert not (ROOT / resource["path"]).exists()


def test_only_manual_ci_trigger_preserves_complete_quality_jobs() -> None:
    text = (ROOT.parent / ".github/workflows/ci.yml").read_text()
    assert "on:\n  workflow_dispatch:\n" in text
    assert not any(
        value in text
        for value in (
            "  push:",
            "  pull_request:",
            "  schedule:",
            "continue-on-error",
            "if: false",
        )
    )
    assert "name: trainlab-source" in text
    assert "os: [ubuntu-latest, macos-latest]" in text
    for name in (
        "Test",
        "Ruff",
        "Ruff format",
        "Mypy",
        "Compile",
        "JSON and agent metadata",
        "Source and privacy boundaries",
        "Diff check",
    ):
        assert "- name: " + name in text


def check_running_stage_current_hashes(rows, root):
    assert rows
    assert len({row["path"] for row in rows}) == len(rows)
    for row in rows:
        assert (
            hashlib.sha256((root / row["path"]).read_bytes()).hexdigest()
            == row["current_sha256"]
        )


def test_running_stage_migration_current_hashes_match():
    manifest = json.loads((ROOT / "docs/legacy-test-mapping.json").read_text())
    check_running_stage_current_hashes(
        manifest["running_stage_migration"]["files"], ROOT
    )


@pytest.mark.parametrize("mutation", ["content", "hash", "missing", "duplicate"])
def test_running_stage_hash_check_rejects_stale_or_invalid_rows(tmp_path, mutation):
    path = tmp_path / "test_public.py"
    path.write_text("assert True\n")
    rows = [
        {
            "path": path.name,
            "current_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    ]
    check_running_stage_current_hashes(rows, tmp_path)
    if mutation == "content":
        path.write_text("assert False\n")
    elif mutation == "hash":
        rows[0]["current_sha256"] = "0" * 64
    elif mutation == "missing":
        path.unlink()
    else:
        rows.append(dict(rows[0]))
    with pytest.raises((AssertionError, FileNotFoundError)):
        check_running_stage_current_hashes(rows, tmp_path)


def mapping_history_fields(value, path=""):
    fields = {}
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}/{key}"
            if "previous" in key or {"source", "original", "baseline"} & set(
                key.split("_")
            ):
                fields[child_path] = child
            else:
                fields.update(mapping_history_fields(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            fields.update(mapping_history_fields(child, f"{path}/{index}"))
    return fields


def check_mapping_history(manifest, baseline):
    fields = mapping_history_fields(manifest)
    assert len(fields) == baseline["historical_field_count"]
    serialized = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    assert (
        hashlib.sha256(serialized.encode()).hexdigest()
        == baseline["historical_fields_sha256"]
    )


def mapping_history_baseline():
    baseline = json.loads(
        (ROOT / "tests/code/fixtures/m12_mapping_history_baseline.json").read_text()
    )
    assert baseline["source_sha256"] == (
        "15d4eeab82c487e735331b55f87cc7b857a70e5d734f26afae9d67935ad0fcd7"
    )
    return baseline


def test_mapping_history_matches_pre_email_original():
    manifest = json.loads((ROOT / "docs/legacy-test-mapping.json").read_text())
    check_mapping_history(manifest, mapping_history_baseline())


@pytest.mark.parametrize(
    "mutation",
    [
        "function_sha256",
        "assertion",
        "missing",
        "original",
        "baseline",
        "named_scenario",
    ],
)
def test_mapping_history_rejects_rewritten_or_missing_evidence(mutation):
    manifest = json.loads((ROOT / "docs/legacy-test-mapping.json").read_text())
    baseline = mapping_history_baseline()
    check_mapping_history(manifest, baseline)
    row = manifest["files"][0]
    scenario = row["scenarios"][0]
    historical = scenario["r7_runner_previous_targets"][0]
    if mutation == "function_sha256":
        historical["function_sha256"] = "0" * 64
    elif mutation == "assertion":
        historical["assertions_and_exception_contexts"][0] = "assert True"
    elif mutation == "missing":
        del scenario["r7_runner_previous_targets"]
    elif mutation == "original":
        scenario["r6_review"]["original_function_sha256"] = "0" * 64
    elif mutation == "baseline":
        row["baseline_sha256"] = "0" * 64
    else:
        del manifest["r5_publication_tests"]["migrated_scenarios"][
            "token save failure retains previous"
        ]
    with pytest.raises(AssertionError):
        check_mapping_history(manifest, baseline)
