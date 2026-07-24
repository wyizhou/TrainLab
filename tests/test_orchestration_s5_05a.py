from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Callable

import pytest

from trainlab.orchestration.state_projection import (
    DOMAIN_STATE_VERSION,
    MAX_STEPS,
    STEP_STORAGE,
    WORKFLOW_STORAGE,
    StateProjectionError,
    StepDefinition,
    WorkflowDefinition,
    decode,
    definition_sha256,
    encode,
    step_storage_state,
    validate,
    workflow_storage_state,
)


STARTED = datetime(2026, 7, 24, 1, 2, 3, 456789, tzinfo=UTC)
COMMAND_HASH = "a" * 64
EVIDENCE_HASH = "b" * 64
REQUEST_HASH = "c" * 64

EXPECTED_WORKFLOW_STORAGE = {
    "queued": "started",
    "running": "started",
    "succeeded": "succeeded",
    "partial": "partial",
    "deferred": "deferred",
    "attention_required": "partial",
    "failed": "failed",
    "cancelled": "cancelled",
}
EXPECTED_STEP_STORAGE = {
    "pending": "pending",
    "running": "running",
    "succeeded": "succeeded",
    "unchanged": "succeeded",
    "partial": "failed",
    "deferred": "deferred",
    "lock_busy": "failed",
    "auth_required": "failed",
    "rejected": "failed",
    "failed": "failed",
    "skipped": "skipped",
}


def workflow(**changes: object) -> WorkflowDefinition:
    values: dict[str, object] = {
        "workflow_key": "morning:42:2026-07-24",
        "workflow_kind": "morning",
        "subject_id": 42,
        "logical_local_date": "2026-07-24",
        "trigger_kind": "scheduled",
        "deadline_at_utc": STARTED + timedelta(hours=1),
        "parent_workflow_run_id": None,
        "started_at_utc": STARTED,
        "create_command_sha256": COMMAND_HASH,
        "create_evidence_sha256": EVIDENCE_HASH,
        "domain_state": "queued",
    }
    values.update(changes)
    return WorkflowDefinition(**values)  # type: ignore[arg-type]


def step(ordinal: int = 0, **changes: object) -> StepDefinition:
    values: dict[str, object] = {
        "step_key": f"step:{ordinal}",
        "ordinal": ordinal,
        "layer_no": 2,
        "tool_mode": "incremental",
        "request_sha256": REQUEST_HASH,
        "invocation_id": f"invoke:{ordinal}",
        "downstream_run_id": f"garmin:{ordinal}",
        "domain_state": "pending",
    }
    values.update(changes)
    return StepDefinition(**values)  # type: ignore[arg-type]


def canonical_document(raw: str) -> dict[str, object]:
    return json.loads(raw)


def canonical_dump(document: object) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


@pytest.mark.parametrize(
    ("domain_state", "storage_state"),
    EXPECTED_WORKFLOW_STORAGE.items(),
    ids=EXPECTED_WORKFLOW_STORAGE,
)
def test_exact_eight_workflow_domain_storage_mappings(
    domain_state: str,
    storage_state: str,
) -> None:
    assert len(WORKFLOW_STORAGE) == 8
    assert dict(WORKFLOW_STORAGE) == EXPECTED_WORKFLOW_STORAGE
    assert workflow_storage_state(domain_state) == storage_state


@pytest.mark.parametrize(
    ("domain_state", "storage_state"),
    EXPECTED_STEP_STORAGE.items(),
    ids=EXPECTED_STEP_STORAGE,
)
def test_exact_eleven_step_domain_storage_mappings(
    domain_state: str,
    storage_state: str,
) -> None:
    assert len(STEP_STORAGE) == 11
    assert dict(STEP_STORAGE) == EXPECTED_STEP_STORAGE
    assert step_storage_state(domain_state) == storage_state


@pytest.mark.parametrize("domain_state", EXPECTED_WORKFLOW_STORAGE)
def test_every_workflow_domain_state_round_trips(domain_state: str) -> None:
    original = workflow(domain_state=domain_state)
    raw = encode(original, (step(),))
    restored_workflow, restored_steps = decode(raw)
    assert restored_workflow == original
    assert restored_steps == (step(),)


@pytest.mark.parametrize("domain_state", EXPECTED_STEP_STORAGE)
def test_every_step_domain_state_round_trips(domain_state: str) -> None:
    original_step = step(domain_state=domain_state)
    raw = encode(workflow(), (original_step,))
    restored_workflow, restored_steps = decode(raw)
    assert restored_workflow == workflow()
    assert restored_steps == (original_step,)


@pytest.mark.parametrize(
    "changes",
    [
        {
            "subject_id": None,
            "logical_local_date": None,
            "deadline_at_utc": None,
            "parent_workflow_run_id": None,
        },
        {
            "trigger_kind": "recovery",
            "parent_workflow_run_id": 9,
        },
        {
            "workflow_kind": "health_check",
            "trigger_kind": "manual",
        },
        {
            "workflow_kind": "mail",
            "trigger_kind": "dependency",
        },
    ],
    ids=["all-optionals-none", "parent-recovery", "health-manual", "mail-dependency"],
)
def test_optional_and_enum_boundaries_round_trip(
    changes: dict[str, object],
) -> None:
    original = workflow(**changes)
    assert decode(encode(original, (step(),))) == (original, (step(),))


def test_dataclasses_are_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        workflow().workflow_key = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        step().step_key = "changed"  # type: ignore[misc]


def test_canonical_json_has_one_spelling_and_utc_z() -> None:
    raw = encode(workflow(), (step(),))
    assert raw == canonical_dump(canonical_document(raw))
    assert " " not in raw
    assert "+00:00" not in raw
    assert '"started_at_utc":"2026-07-24T01:02:03.456789Z"' in raw
    assert canonical_document(raw)["version"] == DOMAIN_STATE_VERSION


@pytest.mark.parametrize(
    ("workflow_state", "step_state"),
    [
        ("queued", "pending"),
        ("running", "running"),
        ("succeeded", "unchanged"),
        ("partial", "lock_busy"),
        ("deferred", "deferred"),
        ("attention_required", "auth_required"),
        ("failed", "rejected"),
        ("cancelled", "skipped"),
    ],
)
def test_definition_hash_excludes_both_mutable_domain_states(
    workflow_state: str,
    step_state: str,
) -> None:
    baseline = definition_sha256(workflow(), (step(),))
    changed = definition_sha256(
        workflow(domain_state=workflow_state),
        (step(domain_state=step_state),),
    )
    assert changed == baseline


@pytest.mark.parametrize(
    "change",
    [
        {"workflow_key": "morning:43:2026-07-24"},
        {"workflow_kind": "weekly"},
        {"subject_id": 43},
        {"logical_local_date": "2026-07-25"},
        {"trigger_kind": "manual"},
        {"deadline_at_utc": STARTED + timedelta(hours=2)},
        {"parent_workflow_run_id": 7},
        {"started_at_utc": STARTED + timedelta(microseconds=1)},
        {"create_command_sha256": "d" * 64},
        {"create_evidence_sha256": "e" * 64},
    ],
    ids=[
        "key",
        "kind",
        "subject",
        "logical-date",
        "trigger",
        "deadline",
        "parent",
        "started",
        "create-command-hash",
        "create-evidence-hash",
    ],
)
def test_definition_hash_covers_every_immutable_workflow_field(
    change: dict[str, object],
) -> None:
    baseline = definition_sha256(workflow(), (step(),))
    assert definition_sha256(workflow(**change), (step(),)) != baseline


@pytest.mark.parametrize(
    "change",
    [
        {"step_key": "different"},
        {"layer_no": 3},
        {"tool_mode": "repair"},
        {"request_sha256": "d" * 64},
        {"invocation_id": None},
        {"downstream_run_id": None},
    ],
    ids=["key", "layer", "tool", "request-hash", "invocation", "downstream-ref"],
)
def test_definition_hash_covers_each_nonordinal_immutable_step_field(
    change: dict[str, object],
) -> None:
    baseline = definition_sha256(workflow(), (step(),))
    assert definition_sha256(workflow(), (step(**change),)) != baseline


def test_definition_hash_covers_step_ordinal_and_order() -> None:
    original = (step(0), step(1))
    reordered = (
        replace(original[1], ordinal=0),
        replace(original[0], ordinal=1),
    )
    assert definition_sha256(workflow(), original) != definition_sha256(
        workflow(),
        reordered,
    )


def test_definition_hash_is_manual_canonical_hash_without_state_keys() -> None:
    raw = encode(workflow(), (step(),))
    document = canonical_document(raw)
    immutable = {
        "workflow": dict(document["workflow"]),  # type: ignore[arg-type]
        "steps": [dict(item) for item in document["steps"]],  # type: ignore[union-attr]
    }
    immutable["workflow"].pop("domain_state")
    for item in immutable["steps"]:
        item.pop("domain_state")
    expected = hashlib.sha256(canonical_dump(immutable).encode("utf-8")).hexdigest()
    assert document["definition_sha256"] == expected


@pytest.mark.parametrize(
    "bad_workflow",
    [
        workflow(subject_id=True),
        workflow(subject_id=0),
        workflow(subject_id=-1),
        workflow(subject_id="42"),
        workflow(parent_workflow_run_id=True),
        workflow(parent_workflow_run_id=0),
        workflow(logical_local_date=True),
        workflow(logical_local_date="2026-7-24"),
        workflow(logical_local_date="2026-02-29"),
        workflow(workflow_kind="bad kind"),
        workflow(trigger_kind="bad trigger"),
        workflow(domain_state="unknown"),
        workflow(create_command_sha256="A" * 64),
        workflow(create_evidence_sha256="b" * 63),
        workflow(workflow_key=""),
        workflow(workflow_key="x" * 129),
        workflow(workflow_key="contains space"),
        workflow(started_at_utc=datetime(2026, 7, 24, 1, 2, 3)),
        workflow(
            started_at_utc=datetime(
                2026,
                7,
                24,
                1,
                2,
                3,
                tzinfo=timezone(timedelta(hours=1)),
            )
        ),
        workflow(deadline_at_utc=STARTED - timedelta(microseconds=1)),
    ],
    ids=[
        "bool-subject",
        "zero-subject",
        "negative-subject",
        "string-subject",
        "bool-parent",
        "zero-parent",
        "bool-date",
        "noncanonical-date",
        "invalid-date",
        "malformed-kind",
        "malformed-trigger",
        "unknown-state",
        "uppercase-hash",
        "short-hash",
        "empty-key",
        "long-key",
        "space-key",
        "naive-started",
        "non-utc-started",
        "deadline-before-started",
    ],
)
def test_strict_workflow_boundaries_raise_controlled_projection_error(
    bad_workflow: WorkflowDefinition,
) -> None:
    with pytest.raises(StateProjectionError, match="domain_state_projection_invalid"):
        validate(bad_workflow, (step(),))


@pytest.mark.parametrize(
    "bad_step",
    [
        step(ordinal=True),
        step(ordinal=-1),
        step(layer_no=True),
        step(layer_no=0),
        step(layer_no=6),
        step(step_key=""),
        step(step_key="contains space"),
        step(tool_mode=""),
        step(request_sha256="C" * 64),
        step(request_sha256="c" * 63),
        step(invocation_id=True),
        step(invocation_id="contains space"),
        step(downstream_run_id=3),
        step(domain_state="unknown"),
    ],
    ids=[
        "bool-ordinal",
        "negative-ordinal",
        "bool-layer",
        "low-layer",
        "high-layer",
        "empty-key",
        "space-key",
        "empty-tool",
        "uppercase-hash",
        "short-hash",
        "bool-invocation",
        "space-invocation",
        "integer-downstream",
        "unknown-state",
    ],
)
def test_strict_step_boundaries_raise_controlled_projection_error(
    bad_step: StepDefinition,
) -> None:
    with pytest.raises(StateProjectionError, match="domain_state_projection_invalid"):
        validate(workflow(), (bad_step,))


@pytest.mark.parametrize(
    "steps",
    [
        (),
        [step()],  # type: ignore[list-item]
        (step(0), step(2)),
        (step(1), step(0)),
        (step(0), replace(step(1), step_key="step:0")),
        tuple(step(index) for index in range(MAX_STEPS + 1)),
    ],
    ids=[
        "empty",
        "list-not-tuple",
        "ordinal-gap",
        "out-of-order",
        "duplicate-key",
        "more-than-64",
    ],
)
def test_step_collection_boundaries_are_strict(
    steps: object,
) -> None:
    with pytest.raises(StateProjectionError, match="domain_state_projection_invalid"):
        validate(workflow(), steps)  # type: ignore[arg-type]


def test_exactly_64_contiguous_unique_steps_round_trip() -> None:
    steps = tuple(step(index) for index in range(MAX_STEPS))
    assert decode(encode(workflow(), steps)) == (workflow(), steps)


def _mutate_unknown_root(document: dict[str, object]) -> None:
    document["unknown"] = "value"


def _mutate_missing_root(document: dict[str, object]) -> None:
    document.pop("version")


def _mutate_unknown_workflow(document: dict[str, object]) -> None:
    document["workflow"]["unknown"] = "value"  # type: ignore[index]


def _mutate_missing_workflow(document: dict[str, object]) -> None:
    document["workflow"].pop("workflow_key")  # type: ignore[union-attr]


def _mutate_unknown_step(document: dict[str, object]) -> None:
    document["steps"][0]["unknown"] = "value"  # type: ignore[index]


def _mutate_missing_step(document: dict[str, object]) -> None:
    document["steps"][0].pop("step_key")  # type: ignore[index]


def _mutate_bad_hash(document: dict[str, object]) -> None:
    document["definition_sha256"] = "f" * 64


def _mutate_noncanonical_utc(document: dict[str, object]) -> None:
    document["workflow"]["started_at_utc"] = "2026-07-24T01:02:03+00:00"  # type: ignore[index]


def _mutate_short_fraction_utc(document: dict[str, object]) -> None:
    document["workflow"]["started_at_utc"] = "2026-07-24T01:02:03.1Z"  # type: ignore[index]


def _mutate_bool_ordinal(document: dict[str, object]) -> None:
    document["steps"][0]["ordinal"] = False  # type: ignore[index]


def _mutate_steps_object(document: dict[str, object]) -> None:
    document["steps"] = {}


@pytest.mark.parametrize(
    "mutation",
    [
        _mutate_unknown_root,
        _mutate_missing_root,
        _mutate_unknown_workflow,
        _mutate_missing_workflow,
        _mutate_unknown_step,
        _mutate_missing_step,
        _mutate_bad_hash,
        _mutate_noncanonical_utc,
        _mutate_short_fraction_utc,
        _mutate_bool_ordinal,
        _mutate_steps_object,
    ],
    ids=lambda mutation: mutation.__name__.removeprefix("_mutate_"),
)
def test_structurally_malformed_canonical_json_is_controlled(
    mutation: Callable[[dict[str, object]], None],
) -> None:
    document = canonical_document(encode(workflow(), (step(),)))
    mutation(document)
    with pytest.raises(StateProjectionError, match="domain_state_projection_invalid"):
        decode(canonical_dump(document))


@pytest.mark.parametrize(
    "raw",
    [
        None,
        b"{}",
        "",
        "{",
        "null",
        "[]",
        "{}",
        '{"version":NaN}',
        '{"a":1,"a":1}',
        " " + encode(workflow(), (step(),)),
        encode(workflow(), (step(),)) + "\n",
        json.dumps(canonical_document(encode(workflow(), (step(),))), indent=2),
    ],
    ids=[
        "none",
        "bytes",
        "empty",
        "broken-json",
        "null",
        "array",
        "empty-object",
        "nan",
        "duplicate-key",
        "leading-whitespace",
        "trailing-newline",
        "pretty-json",
    ],
)
def test_all_raw_decode_failures_use_controlled_projection_error(
    raw: object,
) -> None:
    with pytest.raises(StateProjectionError, match="domain_state_projection_invalid"):
        decode(raw)  # type: ignore[arg-type]


def test_valid_state_change_can_reuse_original_definition_hash() -> None:
    original = canonical_document(encode(workflow(), (step(),)))
    original_hash = original["definition_sha256"]
    original["workflow"]["domain_state"] = "running"  # type: ignore[index]
    original["steps"][0]["domain_state"] = "running"  # type: ignore[index]
    changed_raw = canonical_dump(original)
    changed_workflow, changed_steps = decode(changed_raw)
    assert changed_workflow.domain_state == "running"
    assert changed_steps[0].domain_state == "running"
    assert canonical_document(changed_raw)["definition_sha256"] == original_hash
