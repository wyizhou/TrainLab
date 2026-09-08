"""The approved scope change retires the old route, not its safety evidence."""

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_old_public_prompt_is_only_a_zero_action_retirement_notice() -> None:
    text = (ROOT / "skills/_shared/prompts/auto.txt").read_text()
    assert "legacy_runtime_retired" in text
    assert "不读取" in text
    assert "不调用" in text
    assert "offline_workflow.py" not in text
    assert "resolve_slot.py" not in text
    assert '"provider_calls":0' in text


def test_transition_does_not_claim_new_runtime_is_ready() -> None:
    text = (ROOT / "AGENTS.md").read_text()
    assert "M12" in text and "尚未" in text
    assert "旧运行入口已停用" in text
    assert "data-backup" in text
    assert "不得" in text


def test_every_legacy_scenario_has_an_explicit_current_disposition() -> None:
    manifest = json.loads((ROOT / "docs/legacy-test-mapping.json").read_text())
    assert manifest["schema_version"] == "m12_legacy_test_mapping_v2"
    assert manifest["contract_version"] == "VC-005"
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
            assert row["file_status"] in {"current", "temporary_migration"}
            assert path.is_file()
            assert (
                hashlib.sha256(path.read_bytes()).hexdigest() == row["current_sha256"]
            )
            if row["file_status"] == "temporary_migration":
                assert (
                    row["exit_task"].startswith("M12-000") and row["temporary_reason"]
                )
        for scenario in row["scenarios"]:
            identity = f"{row['path']}::{scenario['function']}"
            assert identity not in identities
            identities.add(identity)
            assert scenario["criterion_ids"] and scenario["reason"]
            assert scenario["disposition"] in {"retain", "migrate", "cancel", "pending"}
            for replacement in scenario["existing_nodes"]:
                assert replacement in known_nodes
            if scenario["disposition"] == "migrate":
                assert scenario["existing_nodes"]
            if scenario["disposition"] == "pending":
                assert scenario["exit_task"].startswith("M12-000")
                assert scenario["proposed_nodes"]
            if scenario["disposition"] == "cancel":
                assert (
                    "RET-004" in scenario["criterion_ids"]
                    or "RET-005" in scenario["criterion_ids"]
                )
    assert len(identities) == manifest["baseline_function_count"]


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
