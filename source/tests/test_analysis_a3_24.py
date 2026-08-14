from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from src.analysis.shadow import (
    RedactedShadowEvidence,
    ShadowEvidenceError,
    compare_shadow_evidence,
)

HASH = "a" * 64


def evidence(role: str, **changes: object) -> RedactedShadowEvidence:
    value: dict[str, object] = {
        "role": role,
        "subject_id": "subject-1",
        "logical_local_date": "2026-07-26",
        "input_manifest_sha256": HASH,
        "output_sha256": HASH,
        "artifact_ids": ("artifact-1", "artifact-2"),
        "artifact_count": 2,
        "delivery_count": 0,
        "current_published": False,
        "email_sent": False,
    }
    value.update(changes)
    return RedactedShadowEvidence(**value)  # type: ignore[arg-type]


def test_shadow_comparison_requires_authorization_and_never_publishes() -> None:
    result = compare_shadow_evidence(evidence("legacy"), evidence("shadow"))
    assert result.decision == "no_go"
    assert result.codes == ("release_authorization_required",)
    approved = compare_shadow_evidence(
        evidence("legacy"), evidence("shadow"), release_authorization_declared=True
    )
    assert approved.decision == "go"
    assert approved.subject_id == "subject-1"
    with pytest.raises(ShadowEvidenceError, match="authorization_invalid"):
        compare_shadow_evidence(
            evidence("legacy"),
            evidence("shadow"),
            release_authorization_declared=1,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"current_published": True}, "shadow_side_effect_invariant_failed"),
        ({"email_sent": True}, "shadow_side_effect_invariant_failed"),
        ({"delivery_count": 1}, "shadow_email_forbidden"),
        (
            {"artifact_ids": ("artifact-1",), "artifact_count": 2},
            "shadow_artifact_count_invalid",
        ),
    ],
)
def test_shadow_side_effect_and_manifest_invariants(
    changes: dict[str, object], code: str
) -> None:
    shadow = evidence("shadow", **changes)
    if code == "shadow_email_forbidden":
        result = compare_shadow_evidence(
            evidence("legacy"), shadow, release_authorization_declared=True
        )
        assert result.decision == "no_go" and code in result.codes
    else:
        with pytest.raises(ShadowEvidenceError, match=code):
            compare_shadow_evidence(evidence("legacy"), shadow)


def test_collision_prevention_and_hash_differences_are_no_go() -> None:
    result = compare_shadow_evidence(
        evidence("legacy"),
        evidence("shadow", subject_id="subject-2", output_sha256="b" * 64),
        release_authorization_declared=True,
    )
    assert result.decision == "no_go"
    assert {"target_mismatch", "output_hash_mismatch"} <= set(result.codes)


def test_shadow_module_has_no_io_or_runner_imports() -> None:
    module = ast.parse(
        inspect.getsource(__import__("src.analysis.shadow", fromlist=["*"]))
    )
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(module)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not (
        {"sqlite3", "pathlib", "subprocess", "socket", "requests", "urllib"} & imported
    )
    source = Path(__file__).parents[1] / "src/analysis/shadow.py"
    assert "trainlab run" not in source.read_text(encoding="utf-8")
