from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from skills._shared.state import canonical_json

SOURCE = Path(__file__).resolve().parents[3]
SCHEMAS = SOURCE / "skills/_shared/schemas"
PROMPTS = SOURCE / "skills/_shared/prompts"


def _load(name: str, relative: str) -> Any:
    path = SOURCE / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


DECISION = _load(
    "trainlab_m11_v4_r19_prompt_parity_test",
    "skills/training-coach/scripts/weekly_decision_v4.py",
)


def _schemas() -> tuple[dict[str, Any], dict[str, Any]]:
    business = json.loads(
        (SCHEMAS / "weekly_model_decision_v1.schema.json").read_text()
    )
    host = json.loads((SCHEMAS / "weekly_ai_result_v4.schema.json").read_text())
    return business, host


def _prompt() -> bytes:
    return (PROMPTS / "weekly-content-v4-v4.txt").read_bytes()


def _render_semantics(prompt: bytes, value: dict[str, Any]) -> bytes:
    begin = DECISION.PROMPT_SEMANTICS_BEGIN.encode()
    end = DECISION.PROMPT_SEMANTICS_END.encode()
    prefix, remainder = prompt.split(begin, 1)
    _, suffix = remainder.split(end, 1)
    return (
        prefix + begin + b"\n" + canonical_json(value).encode() + b"\n" + end + suffix
    )


def test_v4_prompt_semantics_match_authoritative_schemas() -> None:
    business, host = _schemas()
    expected = DECISION.prompt_semantics_from_schemas(business, host)
    parsed = DECISION.parse_prompt_semantics(_prompt())
    assert parsed == expected
    DECISION.require_prompt_schema_semantic_parity(_prompt(), business, host)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["day_slots"].remove("day_7"),
        lambda value: value["course_variants"]["running"]["session_types"].pop(),
        lambda value: value["course_variants"]["running"]["phase_keys"].remove(
            "recovery"
        ),
        lambda value: value["course_variants"]["rest"]["phase_keys"].remove(
            "checklist"
        ),
        lambda value: value["forbidden_host_fields"].remove("period"),
    ],
)
def test_prompt_semantic_drift_is_rejected(mutation: Any) -> None:
    business, host = _schemas()
    changed = deepcopy(DECISION.prompt_semantics_from_schemas(business, host))
    mutation(changed)
    prompt = _render_semantics(_prompt(), changed)
    with pytest.raises(ValueError, match="weekly_prompt_"):
        DECISION.require_prompt_schema_semantic_parity(prompt, business, host)


@pytest.mark.parametrize("mode", ["missing", "duplicate", "damaged", "noncanonical"])
def test_prompt_semantic_block_must_be_unique_valid_and_canonical(mode: str) -> None:
    business, host = _schemas()
    prompt = _prompt()
    begin = DECISION.PROMPT_SEMANTICS_BEGIN.encode()
    end = DECISION.PROMPT_SEMANTICS_END.encode()
    if mode == "missing":
        prompt = prompt.replace(begin, b"REMOVED", 1)
    elif mode == "duplicate":
        prompt += b"\n" + begin + b"\n{}\n" + end + b"\n"
    elif mode == "damaged":
        prefix, remainder = prompt.split(begin, 1)
        _, suffix = remainder.split(end, 1)
        prompt = prefix + begin + b"\n{bad json}\n" + end + suffix
    else:
        value = DECISION.prompt_semantics_from_schemas(business, host)
        prefix, remainder = prompt.split(begin, 1)
        _, suffix = remainder.split(end, 1)
        pretty = json.dumps(value, ensure_ascii=False, indent=2).encode()
        prompt = prefix + begin + b"\n" + pretty + b"\n" + end + suffix
    with pytest.raises(ValueError, match="weekly_prompt_semantics"):
        DECISION.require_prompt_schema_semantic_parity(prompt, business, host)


def test_prompt_semantic_block_rejects_extra_fields() -> None:
    business, host = _schemas()
    changed = DECISION.prompt_semantics_from_schemas(business, host)
    changed["extra"] = []
    with pytest.raises(ValueError, match="weekly_prompt_semantics_invalid"):
        DECISION.parse_prompt_semantics(_render_semantics(_prompt(), changed))


def test_day_ref_topology_must_be_identical() -> None:
    business, host = _schemas()
    changed = deepcopy(business)
    changed["$defs"]["training_plan"]["properties"]["days"]["properties"]["day_7"][
        "anyOf"
    ].pop()
    with pytest.raises(ValueError, match="weekly_prompt_schema_topology_invalid"):
        DECISION.prompt_semantics_from_schemas(changed, host)
