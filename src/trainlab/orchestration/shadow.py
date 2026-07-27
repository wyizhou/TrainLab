"""Side-effect-free orchestration comparison used before production cutover."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Iterable, Protocol


class ShadowError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ShadowStep:
    workflow_key: str
    step_key: str
    layer: str
    mode: str
    logical_target: str


@dataclass(frozen=True, slots=True)
class ShadowDifference:
    category: str
    identity: str


@dataclass(frozen=True, slots=True)
class ShadowReport:
    status: str
    expected_count: int
    observed_count: int
    differences: tuple[ShadowDifference, ...]
    expected_sha256: str
    observed_sha256: str
    external_calls: int = 0


class ShadowSource(Protocol):
    shadow_safe: bool

    def expected_steps(self) -> Iterable[ShadowStep]: ...
    def observed_steps(self) -> Iterable[ShadowStep]: ...


def _canonical(items: tuple[ShadowStep, ...]) -> bytes:
    value = [asdict(item) for item in items]
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _normalize(items: Iterable[ShadowStep]) -> tuple[ShadowStep, ...]:
    result = tuple(items)
    if any(not isinstance(item, ShadowStep) for item in result):
        raise ShadowError("shadow_step_invalid")
    identities = [(item.workflow_key, item.step_key) for item in result]
    if len(identities) != len(set(identities)):
        raise ShadowError("shadow_step_duplicate")
    return tuple(sorted(result, key=lambda item: (item.workflow_key, item.step_key)))


class ShadowComparator:
    """Compare plans/receipts without accepting any live-capable adapter."""

    def compare(self, source: ShadowSource) -> ShadowReport:
        if getattr(source, "shadow_safe", False) is not True:
            raise ShadowError("shadow_live_adapter_forbidden")
        expected = _normalize(source.expected_steps())
        observed = _normalize(source.observed_steps())
        expected_map = {(item.workflow_key, item.step_key): item for item in expected}
        observed_map = {(item.workflow_key, item.step_key): item for item in observed}
        differences: list[ShadowDifference] = []
        for identity in sorted(expected_map.keys() - observed_map.keys()):
            differences.append(ShadowDifference("missing", ":".join(identity)))
        for identity in sorted(observed_map.keys() - expected_map.keys()):
            differences.append(ShadowDifference("unexpected", ":".join(identity)))
        for identity in sorted(expected_map.keys() & observed_map.keys()):
            if expected_map[identity] != observed_map[identity]:
                differences.append(ShadowDifference("mismatch", ":".join(identity)))
        expected_bytes, observed_bytes = _canonical(expected), _canonical(observed)
        return ShadowReport(
            "matched" if not differences else "different",
            len(expected),
            len(observed),
            tuple(differences),
            hashlib.sha256(expected_bytes).hexdigest(),
            hashlib.sha256(observed_bytes).hexdigest(),
        )
