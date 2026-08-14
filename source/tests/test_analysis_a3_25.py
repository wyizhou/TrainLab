from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_controlled_acceptance_protocol_is_authorization_only_and_redacted() -> None:
    text = (
        (ROOT / "docs/runbooks/analysis-controlled-acceptance.md")
        .read_text(encoding="utf-8")
        .lower()
    )
    for required in (
        "separate written real-environment authorization",
        "does not execute",
        "go/no-go",
        "same invocation",
        "already_sent",
        "reconcile",
        "no residual process",
    ):
        assert required in text
    for prohibited in (
        "token=",
        "password=",
        "authorization:",
        "client_secret",
        "@gmail.com",
    ):
        assert prohibited not in text


def test_shadow_protocol_requires_release_authorization_and_no_side_effects() -> None:
    text = (
        (ROOT / "docs/runbooks/analysis-shadow-migration.md")
        .read_text(encoding="utf-8")
        .lower()
    )
    for required in (
        "separate release authorization",
        "non-current",
        "no email",
        "rollback",
        "collision",
        "does not execute",
    ):
        assert required in text
    assert "trainlab analyze" not in text
    assert "trainlab run " not in text
