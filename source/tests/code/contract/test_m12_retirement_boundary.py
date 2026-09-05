"""The approved scope change retires the old route, not its safety evidence."""

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


def test_every_legacy_test_has_a_byte_preserving_migration_mapping() -> None:
    manifest = json.loads((ROOT / "docs/legacy-test-mapping.json").read_text())
    assert manifest["schema_version"] == "m12_legacy_test_mapping_v1"
    rows = manifest["files"]
    assert len({row["path"] for row in rows}) == len(rows)
    actual = {
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "tests/code").rglob("test_*.py")
        if not p.name.startswith("test_m12_")
    }
    assert actual == {row["path"] for row in rows}
    for row in rows:
        assert row["current_action"] == "keep_executing"
        assert row["target"] in {"M12-0002", "M12-0003", "M12-0004", "M12-0005"}
        assert row["applicable_safety"]
        assert row["retired_behavior"]
        assert (
            hashlib.sha256((ROOT / row["path"]).read_bytes()).hexdigest()
            == row["sha256"]
        )
