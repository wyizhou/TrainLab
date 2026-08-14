from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.resources import resource_bytes
from tools import verify_restore_drill as drill


def test_restore_drill_runs_all_declared_partitions_in_an_isolated_root(
    isolated_test_subject: object,
) -> None:
    root = getattr(isolated_test_subject, "root") / "restore-drill"
    receipt = drill.run_drill(root)
    schema = json.loads(
        resource_bytes("harness/schemas/restore_drill_receipt.schema.json")
    )
    Draft202012Validator(schema).validate(receipt)
    assert receipt["partitions"] == list(drill.PARTITIONS)
    assert receipt["external_effects"] is False


@pytest.mark.parametrize("partition", drill.PARTITIONS)
def test_declared_restore_partition_is_exhaustively_accounted_for(
    partition: str,
) -> None:
    assert partition in drill.PARTITIONS


def test_restore_drill_rejects_any_non_disposable_output_root() -> None:
    outside_disposable_root = drill.PROJECT_ROOT.parent / "restore-drill-not-disposable"
    with pytest.raises(drill.RestoreDrillError, match="state_test_tmp"):
        drill.run_drill(outside_disposable_root)


@pytest.mark.parametrize(
    "unsafe_root",
    (drill.PROJECT_ROOT / "state", drill.PROJECT_ROOT / "state" / "raw"),
)
def test_restore_drill_rejects_production_state_paths_before_any_open(
    unsafe_root: Path,
) -> None:
    with pytest.raises(drill.RestoreDrillError, match="state_test_tmp"):
        drill.run_drill(unsafe_root)


def test_restore_drill_refuses_to_reuse_an_existing_root(
    isolated_test_subject: object,
) -> None:
    root = getattr(isolated_test_subject, "root") / "already-exists"
    root.mkdir()
    with pytest.raises(drill.RestoreDrillError, match="must_not_exist"):
        drill.run_drill(root)
