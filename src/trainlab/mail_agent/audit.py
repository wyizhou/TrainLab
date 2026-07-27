"""Offline M4-13 privacy and persistence-invariant audit helpers.

Inputs are already-collected, synthetic snapshots.  This module never opens a
database or an external transport; findings intentionally contain paths and
codes, never the offending value.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping


Severity = Literal["warning", "error"]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SECRET = re.compile(
    r"(?i)(?:bearer\s+\S+|(?:access_token|refresh_token|client_secret|password)\s*[:=]\s*\S+|AIza[\w-]{20,})"
)
_HIDDEN_REASONING = re.compile(
    r"(?i)(?:<analysis\b|chain[- ]of[- ]thought|hidden reasoning|internal reasoning|reasoning_content)"
)


@dataclass(frozen=True, slots=True)
class AuditFinding:
    code: str
    entity: str
    severity: Severity
    summary: str


@dataclass(frozen=True, slots=True)
class AuditReport:
    findings: tuple[AuditFinding, ...]

    @property
    def ok(self) -> bool:
        return not any(item.severity == "error" for item in self.findings)


def _finding(code: str, entity: str, severity: Severity = "error") -> AuditFinding:
    return AuditFinding(code, entity, severity, "mail audit rule failed")


def _strings(value: object, path: str) -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str):
                yield from _strings(item, f"{path}.{key}")
    elif isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            yield from _strings(item, f"{path}[{index}]")


def audit_privacy(
    *,
    receipt: Mapping[str, object] | None = None,
    errors: Iterable[Mapping[str, object]] = (),
    log_like_text: Iterable[str] = (),
    forbidden_bodies: Iterable[str] = (),
) -> AuditReport:
    """Find disclosures in public output without retaining their contents."""
    findings: list[AuditFinding] = []
    bodies = tuple(body for body in forbidden_bodies if isinstance(body, str) and body)
    sources: list[tuple[str, object]] = []
    if receipt is not None:
        sources.append(("receipt", receipt))
    sources.append(("errors", tuple(errors)))
    sources.append(("logs", tuple(log_like_text)))
    for root, document in sources:
        for path, text in _strings(document, root):
            if _SECRET.search(text):
                findings.append(_finding("secret_exposed", path))
            if _HIDDEN_REASONING.search(text):
                findings.append(_finding("hidden_reasoning_exposed", path))
            if any(body in text for body in bodies):
                findings.append(_finding("full_body_exposed", path))
    return AuditReport(tuple(findings))


def _row_id(row: Mapping[str, object], name: str) -> object:
    value = row.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def audit_mail_persistence(
    *,
    responses: Iterable[Mapping[str, object]],
    deliveries: Iterable[Mapping[str, object]],
    delivery_artifacts: Iterable[Mapping[str, object]],
    response_inputs: Iterable[Mapping[str, object]],
) -> AuditReport:
    """Validate the minimal immutable-response and exact-delivery invariants."""
    findings: list[AuditFinding] = []
    response_rows = tuple(responses)
    delivery_rows = tuple(deliveries)
    relation_rows = tuple(delivery_artifacts)
    input_rows = tuple(response_inputs)

    by_current: dict[tuple[object, object, object], int] = defaultdict(int)
    by_response_key: dict[tuple[object, object, object, object], Mapping[str, object]] = {}
    response_by_id: dict[object, Mapping[str, object]] = {}
    response_runs: set[object] = set()
    for index, row in enumerate(response_rows):
        entity = f"response[{index}]"
        response_id = _row_id(row, "id")
        revision = _row_id(row, "revision_no")
        subject, thread, kind = row.get("subject_id"), row.get("mail_thread_id"), row.get("response_kind")
        run_id = _row_id(row, "generated_by_mail_agent_run_id")
        if response_id is None or revision is None or _row_id(row, "subject_id") is None or not isinstance(kind, str) or not kind or run_id is None:
            findings.append(_finding("response_identity_invalid", entity)); continue
        key = (subject, thread, kind, revision)
        if key in by_response_key or response_id in response_by_id:
            findings.append(_finding("response_revision_duplicate", entity))
        by_response_key[key] = row
        response_by_id[response_id] = row
        response_runs.add(run_id)
        if row.get("is_current") is True or row.get("is_current") == 1:
            by_current[(subject, thread, kind)] += 1
        digest = row.get("content_sha256")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            findings.append(_finding("response_content_hash_invalid", entity))
        predecessor = row.get("supersedes_mail_response_artifact_id")
        if revision == 1 and predecessor is not None:
            findings.append(_finding("response_lineage_invalid", entity))
        if revision > 1:
            prior = by_response_key.get((subject, thread, kind, revision - 1))
            if prior is None or predecessor != prior.get("id"):
                findings.append(_finding("response_lineage_invalid", entity))
    for key, current_count in by_current.items():
        if current_count > 1:
            findings.append(_finding("response_current_ambiguous", f"response_current:{key}"))

    delivery_by_id: dict[object, Mapping[str, object]] = {}
    idempotency: set[str] = set()
    for index, row in enumerate(delivery_rows):
        entity = f"delivery[{index}]"
        delivery_id = _row_id(row, "id")
        key = row.get("idempotency_key")
        if delivery_id is None or not isinstance(key, str) or not key:
            findings.append(_finding("delivery_identity_invalid", entity)); continue
        if delivery_id in delivery_by_id or key in idempotency:
            findings.append(_finding("delivery_idempotency_duplicate", entity))
        delivery_by_id[delivery_id] = row; idempotency.add(key)
        if row.get("status") in {"sent", "already_sent"} and (
            _row_id(row, "mail_message_id") is None
            or not isinstance(row.get("provider_thread_id"), str)
            or not row.get("provider_thread_id")
            or not isinstance(row.get("sent_at_utc"), str)
            or not isinstance(row.get("last_verified_at_utc"), str)
        ):
            findings.append(_finding("delivery_evidence_missing", entity))

    relations: dict[object, list[Mapping[str, object]]] = defaultdict(list)
    for index, row in enumerate(relation_rows):
        delivery_id, response_id = _row_id(row, "mail_delivery_id"), _row_id(row, "mail_response_artifact_id")
        if delivery_id is None or response_id is None or delivery_id not in delivery_by_id or response_id not in response_by_id:
            findings.append(_finding("delivery_lineage_invalid", f"delivery_artifact[{index}]")); continue
        relations[delivery_id].append(row)
    for delivery_id in delivery_by_id:
        links = relations[delivery_id]
        if len(links) != 1 or links[0].get("content_role") != "mail_response" or links[0].get("ordinal") != 0:
            findings.append(_finding("delivery_lineage_invalid", f"delivery:{delivery_id}"))

    inputs_by_run: dict[object, list[Mapping[str, object]]] = defaultdict(list)
    for index, row in enumerate(input_rows):
        run_id = _row_id(row, "mail_agent_run_id")
        if run_id is None or run_id not in response_runs:
            findings.append(_finding("response_input_lineage_invalid", f"input[{index}]")); continue
        inputs_by_run[run_id].append(row)
    for run_id in response_runs:
        rows = inputs_by_run[run_id]
        ordinals = [row.get("ordinal") for row in rows]
        if not rows or sorted(ordinals) != list(range(len(rows))) or any(
            not isinstance(row.get("input_sha256"), str) or not _SHA256.fullmatch(row["input_sha256"])
            for row in rows
        ):
            findings.append(_finding("response_input_lineage_invalid", f"response_run:{run_id}"))
    return AuditReport(tuple(findings))
