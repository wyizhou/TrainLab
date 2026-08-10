"""Synthetic boundary matrix for the repaired orchestration invariants."""

from __future__ import annotations

import pytest

from trainlab.orchestration.evidence_codes import (
    DOWNSTREAM_FAILURE_EVIDENCE_CODES,
    downstream_failure_evidence,
)
from trainlab.orchestration.subprocess_runner import (
    DownstreamCall,
    SubprocessBoundaryError,
    _argv,
)


@pytest.mark.parametrize(
    ("partition", "candidate", "expected"),
    (
        ("valid", "process_start_failed", "process_start_failed"),
        ("invalid", "sensitive-provider-detail", "downstream_execution_failed"),
        ("empty", "", "downstream_execution_failed"),
        ("missing", None, "downstream_execution_failed"),
        ("minimum", "a", "downstream_execution_failed"),
        ("maximum", "a" * 64, "downstream_execution_failed"),
        ("just-outside", "a" * 65, "downstream_execution_failed"),
    ),
)
def test_downstream_evidence_partitions_are_allowlisted(
    partition: str, candidate: object, expected: str
) -> None:
    assert partition
    assert downstream_failure_evidence(candidate) == expected
    assert expected in DOWNSTREAM_FAILURE_EVIDENCE_CODES


@pytest.mark.parametrize(
    ("partition", "max_items", "accepted"),
    (
        ("valid", 2, True),
        ("invalid", "2", False),
        ("empty", None, True),
        ("missing", None, True),
        ("minimum", 1, True),
        ("maximum", 10_000, True),
        ("just-outside", 10_001, False),
    ),
)
def test_mail_run_limit_partitions_are_static_and_fail_closed(
    partition: str, max_items: object, accepted: bool
) -> None:
    call = DownstreamCall(
        "mail",
        "run",
        "matrix-run",
        None,
        subject_id=1,
        max_items=max_items,
    )
    if accepted:
        argv = _argv(call)
        if max_items is None:
            assert "--max-items" not in argv
        else:
            assert argv[-2:] == ("--max-items", str(max_items))
    else:
        with pytest.raises(SubprocessBoundaryError, match="subprocess_limit_invalid"):
            _argv(call)
    assert partition


@pytest.mark.parametrize(
    ("partition", "identifiers", "accepted"),
    (
        ("valid", ("artifact-1",), True),
        ("invalid", ("bad id",), False),
        ("empty", (), True),
        ("missing", (), True),
        ("minimum", ("a",), True),
        ("maximum", tuple(f"artifact-{item}" for item in range(64)), True),
        (
            "just-outside",
            tuple(f"artifact-{item}" for item in range(65)),
            False,
        ),
    ),
)
def test_mail_process_identifier_collection_partitions(
    partition: str, identifiers: tuple[str, ...], accepted: bool
) -> None:
    call = DownstreamCall(
        "mail",
        "process",
        "matrix-process",
        None,
        subject_id=1,
        mail_message_id="message-1",
        dependency_analysis_artifact_ids=identifiers,
    )
    if accepted:
        argv = _argv(call)
        assert argv.count("--dependency-artifact-id") == len(identifiers)
    else:
        with pytest.raises(
            SubprocessBoundaryError, match="subprocess_collection_invalid"
        ):
            _argv(call)
    assert partition
