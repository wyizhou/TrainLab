"""M4-08 deterministic mail fact, action, and plan-dependency gate.

The gate is deliberately pure: it receives an already-built bounded context,
the model result, and immutable repository evidence.  It never opens a
database, calls a provider, changes a plan, or publishes a response.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from src.resources import resource_bytes, resource_root

from .runner import MailResultValidator, MailRunnerError

_ROOT = resource_root()
_POLICY_PATH = "harness/mail/fact-gate-policy.json"
_POLICY_SCHEMA_PATH = "harness/schemas/mail_fact_gate_policy.schema.json"
_UTC = timezone.utc
_SAFE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
_SENTENCE = re.compile(r"[^.!?\n。！？]+[.!?。！？]?")


class MailFactGateError(RuntimeError):
    """Stable, content-free failure from the deterministic M4-08 gate."""

    def __init__(
        self,
        code: str,
        *,
        disposition: str = "rejected",
        field_path: tuple[str | int, ...] = (),
    ) -> None:
        safe = (
            code
            if isinstance(code, str) and code.startswith("mail_fact_gate_")
            else "mail_fact_gate_internal"
        )
        super().__init__(safe)
        self.code = safe
        self.disposition = (
            disposition
            if disposition in {"rejected", "operator_review", "dependency_wait"}
            else "rejected"
        )
        self.field_path = field_path


# Friendly short alias for callers that do not need the Mail prefix.
FactGateError = MailFactGateError


@dataclass(frozen=True)
class ActiveFactEvidence:
    id: int
    subject_id: int
    fact_key: str
    fact_value: Any
    scope: str
    effective_from_utc: str | None
    expires_at_utc: str | None
    source_event_id: int | None
    source_mail_message_id: int | None
    is_active: bool
    superseded_by_fact_id: int | None


@dataclass(frozen=True)
class AnalysisDependencyEvidence:
    artifact_id: int
    subject_id: int
    artifact_kind: str
    period_start_local_date: str
    period_end_local_date: str
    is_current: bool
    analysis_run_id: int
    analysis_kind: str
    analysis_status: str
    target_start_local_date: str | None
    target_end_local_date: str | None
    training_plan_id: int | None
    training_plan_status: str | None
    plan_start_local_date: str | None
    plan_end_local_date: str | None
    reason_event_id: int | None
    reason_mail_message_id: int | None
    reason_actor_role: str | None
    reason_trust_level: str | None


@dataclass(frozen=True)
class FactGateEvidence:
    subject_id: int
    run_id: int
    run_key: str
    request_kind: str
    run_status: str
    requested_provider_message_ids: tuple[str, ...]
    mail_message_id: int
    provider_message_id: str
    mail_thread_id: int
    provider_thread_id: str
    source_revision_id: int
    source_revision_is_current: bool
    actor_role: str
    direction: str
    processing_state: str
    eligibility_event_type: str
    accepted_response_id: int | None
    as_of_utc: str
    active_facts: tuple[ActiveFactEvidence, ...] = ()
    dependency: AnalysisDependencyEvidence | None = None


@dataclass(frozen=True)
class GatedEvent:
    event_type: str
    actor_role: str
    occurred_at_utc: str
    mail_message_id: int
    related_run_key: str
    trust_level: str
    structured_payload_json: str


@dataclass(frozen=True)
class GatedFact:
    fact_key: str
    fact_value_json: str
    scope: str
    effective_from_utc: str | None
    expires_at_utc: str | None
    confidence: float
    source_event_type: str
    supersedes_fact_id: int | None
    persist: bool
    replay_fact_id: int | None = None


@dataclass(frozen=True)
class FactGateDecision:
    policy_version: str
    status: str
    action: str
    reason_code: str
    subject_id: int
    run_id: int
    run_key: str
    mail_message_id: int
    mail_thread_id: int
    source_revision_id: int
    event: GatedEvent | None
    facts: tuple[GatedFact, ...]
    dependency_artifact_id: int | None = None
    reason_event_id: int | None = None


def _strict_document(
    value: bytes | str | Mapping[str, Any],
    *,
    max_bytes: int,
    max_depth: int,
    max_nodes: int,
    code: str,
) -> tuple[dict[str, Any], str]:
    if isinstance(value, Mapping):
        try:
            raw = json.dumps(
                dict(value),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8", errors="strict")
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise MailFactGateError(code) from None
    elif isinstance(value, str):
        try:
            raw = value.encode("utf-8", errors="strict")
        except UnicodeError:
            raise MailFactGateError(code) from None
    elif isinstance(value, bytes):
        raw = value
    else:
        raise MailFactGateError(code)
    if not raw or len(raw) > max_bytes or raw.startswith(b"\xef\xbb\xbf"):
        raise MailFactGateError(code)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise MailFactGateError(code) from None

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        record: dict[str, Any] = {}
        for key, item in items:
            if key in record:
                raise ValueError("duplicate")
            record[key] = item
        return record

    def nonfinite(_: str) -> Any:
        raise ValueError("nonfinite")

    try:
        decoder = json.JSONDecoder(
            object_pairs_hook=pairs,
            parse_constant=nonfinite,
        )
        parsed, end = decoder.raw_decode(text)
        if text[end:].strip() or not isinstance(parsed, dict):
            raise ValueError("not one object")
    except (TypeError, ValueError, RecursionError):
        raise MailFactGateError(code) from None
    nodes = 0

    def walk(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > max_nodes or depth > max_depth:
            raise MailFactGateError(code)
        if item is None or isinstance(item, (str, bool)):
            return
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            if isinstance(item, float) and not math.isfinite(item):
                raise MailFactGateError(code)
            return
        if isinstance(item, list):
            for child in item:
                walk(child, depth + 1)
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise MailFactGateError(code)
                walk(child, depth + 1)
            return
        raise MailFactGateError(code)

    walk(parsed, 0)
    try:
        canonical = json.dumps(
            parsed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError):
        raise MailFactGateError(code) from None
    return parsed, canonical


def _utc(value: Any, code: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z") or len(value) > 40:
        raise MailFactGateError(code)
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise MailFactGateError(code) from None
    if (
        instant.tzinfo is None
        or instant.astimezone(_UTC).isoformat().replace("+00:00", "Z") != value
    ):
        raise MailFactGateError(code)
    return instant.astimezone(_UTC)


def _local_date(value: Any, code: str) -> date:
    if not isinstance(value, str):
        raise MailFactGateError(code)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise MailFactGateError(code) from None
    if parsed.isoformat() != value:
        raise MailFactGateError(code)
    return parsed


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _has_phrase(value: str, phrases: tuple[str, ...]) -> bool:
    normalized = _normalized(value)
    return any(_normalized(phrase) in normalized for phrase in phrases)


def _json_type(value: Any) -> str | None:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    return None


def _iter_keys(value: Any) -> tuple[str, ...]:
    keys: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                keys.append(key)
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return tuple(keys)


def _iter_strings(value: Any) -> tuple[str, ...]:
    strings: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, str):
            strings.append(item)
        elif isinstance(item, dict):
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return tuple(strings)


class MailFactGate:
    """Validate one M4-07 result against exact repository evidence."""

    def __init__(
        self,
        root: Path = _ROOT,
        *,
        policy_bytes: bytes | None = None,
        policy_schema_bytes: bytes | None = None,
        result_validator: MailResultValidator | None = None,
    ) -> None:
        try:
            raw_policy = (
                policy_bytes
                if policy_bytes is not None
                else resource_bytes(_POLICY_PATH)
            )
            raw_schema = (
                policy_schema_bytes
                if policy_schema_bytes is not None
                else resource_bytes(_POLICY_SCHEMA_PATH)
            )
            schema, _ = _strict_document(
                raw_schema,
                max_bytes=1_000_000,
                max_depth=16,
                max_nodes=100_000,
                code="mail_fact_gate_policy_unavailable",
            )
            policy, _ = _strict_document(
                raw_policy,
                max_bytes=262_144,
                max_depth=16,
                max_nodes=100_000,
                code="mail_fact_gate_policy_unavailable",
            )
            Draft202012Validator.check_schema(schema)
            errors = list(
                Draft202012Validator(
                    schema, format_checker=FormatChecker()
                ).iter_errors(policy)
            )
            if errors:
                raise ValueError("policy schema")
        except MailFactGateError:
            raise
        except (OSError, TypeError, ValueError, KeyError, RecursionError):
            raise MailFactGateError("mail_fact_gate_policy_unavailable") from None
        self.policy = policy
        self.policy_version = str(policy["policy_version"])
        self.reason_codes = frozenset(policy["reason_codes"])
        self.result_validator = result_validator or MailResultValidator(root)
        self.fact_keys: dict[str, dict[str, Any]] = policy["fact_keys"]
        self.long_term_markers = tuple(policy["long_term_markers"])
        self.supersession_markers = tuple(policy["supersession_markers"])
        self.medical_phrases = tuple(policy["medical_diagnosis_phrases"])
        self.medical_conditions = tuple(policy["medical_condition_terms"])
        self.provider_markers = tuple(policy["provider_markers"])
        self.provider_metrics = tuple(policy["provider_metric_terms"])
        self.provider_limitations = tuple(policy["provider_limitation_markers"])
        self.privileged_phrases = tuple(policy["privileged_claim_phrases"])
        self.forbidden_keys = frozenset(policy["forbidden_structured_keys"])
        self.plan_constraint_keys = frozenset(policy["plan_constraint_keys"])

    def _identity(
        self,
        result: dict[str, Any],
        context: dict[str, Any],
        evidence: FactGateEvidence,
    ) -> None:
        try:
            trigger = context["trigger_message"]
            run = context["run"]
            plan = context["current_training_plan"]
            if (
                evidence.subject_id <= 0
                or evidence.run_id <= 0
                or evidence.mail_message_id <= 0
                or evidence.mail_thread_id <= 0
                or evidence.source_revision_id <= 0
                or run["id"] != evidence.run_id
                or run["run_key"] != evidence.run_key
                or run["request_kind"] != "process"
                or (plan is not None and plan["subject_id"] != evidence.subject_id)
                or evidence.request_kind != "process"
                or evidence.run_status not in {"started", "partial", "deferred"}
                or trigger["id"] != evidence.mail_message_id
                or trigger["provider_message_id"] != evidence.provider_message_id
                or trigger["thread_id"] != evidence.mail_thread_id
                or trigger["provider_thread_id"] != evidence.provider_thread_id
                or trigger["source_revision_id"] != evidence.source_revision_id
                or trigger["value_origin"] != "user_asserted"
                or trigger["content_instruction_trust"] != "untrusted_content"
                or evidence.provider_message_id
                not in evidence.requested_provider_message_ids
                or evidence.actor_role != "user"
                or evidence.direction != "inbound"
                or evidence.processing_state
                not in {"queued", "analyzing", "awaiting_analysis"}
                or not evidence.source_revision_is_current
                or evidence.eligibility_event_type
                not in {"new_request_received", "reply_received"}
                or evidence.accepted_response_id is not None
                or result["run_key"] != evidence.run_key
                or result["trigger_message_id"] != evidence.mail_message_id
            ):
                raise MailFactGateError("mail_fact_gate_identity_invalid")
            _utc(evidence.as_of_utc, "mail_fact_gate_identity_invalid")
            _utc(
                trigger["timestamp_utc"],
                "mail_fact_gate_identity_invalid",
            )
        except (KeyError, TypeError, AttributeError):
            raise MailFactGateError("mail_fact_gate_identity_invalid") from None

    def _action(self, result: dict[str, Any]) -> None:
        intent, action = result["intent"], result["action"]
        allowed = self.policy["intent_actions"].get(intent)
        if not isinstance(allowed, list) or action not in allowed:
            raise MailFactGateError(
                "mail_fact_gate_action_invalid",
                disposition="operator_review",
                field_path=("action",),
            )
        if intent == "acknowledgement" and (
            result["fact_candidates"] or result["response"] is not None
        ):
            raise MailFactGateError("mail_fact_gate_acknowledgement_loop")
        if intent == "non_trainlab_or_unsupported" and (
            action != "ignore"
            or result["fact_candidates"]
            or result["response"] is not None
        ):
            raise MailFactGateError("mail_fact_gate_irrelevant_action")
        if action == "operator_review" and (
            result["response"] is not None
            or result["fact_candidates"]
            or result["plan_revision_request"] is not None
        ):
            raise MailFactGateError("mail_fact_gate_operator_review_side_effect")

    def _content(self, result: dict[str, Any], context: dict[str, Any]) -> None:
        response = result["response"]
        if response is None:
            return
        combined = "\n".join(
            (
                response["subject_intent"],
                response["user_visible_text"],
                *_iter_strings(response["structured_content"]),
            )
        )
        diagnosis_attribution = _has_phrase(
            combined,
            (
                "you have",
                "you are suffering from",
                "diagnosed with",
                "diagnosis is",
                "你患有",
                "确诊为",
                "诊断为",
            ),
        )
        if _has_phrase(combined, self.medical_phrases) or (
            diagnosis_attribution and _has_phrase(combined, self.medical_conditions)
        ):
            raise MailFactGateError(
                "mail_fact_gate_medical_diagnosis",
                disposition="operator_review",
            )
        if _has_phrase(combined, self.privileged_phrases):
            raise MailFactGateError("mail_fact_gate_privileged_claim")
        for key in _iter_keys(response["structured_content"]):
            if key.casefold() in self.forbidden_keys:
                raise MailFactGateError("mail_fact_gate_privileged_structure")

        provider_sentences = tuple(
            sentence
            for sentence in _SENTENCE.findall(combined)
            if _has_phrase(sentence, self.provider_markers)
        )
        if not provider_sentences:
            return
        manifest = {item["ordinal"]: item for item in context["input_manifest"]}
        used_provider_ids = {
            (
                item["input_role"],
                item["source_entity_id"],
            )
            for item in result["source_usage"]
            if manifest[item["ordinal"]]["input_role"]
            in {"health_fact", "activity_fact"}
        }
        provider_sources: list[Any] = []
        for role, source_id in used_provider_ids:
            collection = (
                context["current_health_context"]
                if role == "health_fact"
                else context["current_activity_context"]
            )
            provider_sources.extend(row for row in collection if row["id"] == source_id)
        if not provider_sources:
            raise MailFactGateError("mail_fact_gate_provider_claim_unbound")
        source_text = _normalized(
            json.dumps(
                provider_sources,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        ).replace("_", " ")
        for sentence in provider_sentences:
            numbers = _NUMBER.findall(sentence)
            limitation = _has_phrase(sentence, self.provider_limitations)
            metrics = tuple(
                metric
                for metric in self.provider_metrics
                if _normalized(metric) in _normalized(sentence)
            )
            if (
                not numbers
                and not limitation
                or numbers
                and (
                    not metrics
                    or any(_normalized(metric) not in source_text for metric in metrics)
                    or any(number not in source_text for number in numbers)
                )
            ):
                raise MailFactGateError("mail_fact_gate_provider_claim_unbound")

    def _active_facts(
        self, evidence: FactGateEvidence, as_of: datetime
    ) -> dict[str, tuple[ActiveFactEvidence, ...]]:
        grouped: dict[str, list[ActiveFactEvidence]] = {}
        for fact in evidence.active_facts:
            if (
                fact.id <= 0
                or fact.subject_id != evidence.subject_id
                or not fact.is_active
                or fact.superseded_by_fact_id is not None
                or not _SAFE_KEY.fullmatch(fact.fact_key)
                or fact.scope not in {"temporary", "long_term"}
                or (
                    fact.effective_from_utc is not None
                    and _utc(
                        fact.effective_from_utc,
                        "mail_fact_gate_active_fact_invalid",
                    )
                    > as_of
                )
                or (
                    fact.expires_at_utc is not None
                    and _utc(
                        fact.expires_at_utc,
                        "mail_fact_gate_active_fact_invalid",
                    )
                    <= as_of
                )
            ):
                raise MailFactGateError("mail_fact_gate_active_fact_invalid")
            grouped.setdefault(fact.fact_key, []).append(fact)
        return {key: tuple(rows) for key, rows in grouped.items()}

    def _facts(
        self,
        result: dict[str, Any],
        context: dict[str, Any],
        evidence: FactGateEvidence,
    ) -> tuple[GatedFact, ...]:
        trigger = context["trigger_message"]
        authored = trigger["latest_authored_text"]
        as_of = _utc(evidence.as_of_utc, "mail_fact_gate_identity_invalid")
        active = self._active_facts(evidence, as_of)
        seen: set[str] = set()
        accepted: list[GatedFact] = []
        forbidden_prefixes = tuple(self.policy["forbidden_fact_prefixes"])
        for ordinal, candidate in enumerate(result["fact_candidates"]):
            path = ("fact_candidates", ordinal)
            key = candidate["fact_key"]
            spec = self.fact_keys.get(key)
            span = candidate["evidence_text_span"]
            value = candidate["fact_value"]
            value_type = _json_type(value)
            if (
                spec is None
                or key in seen
                or any(key.startswith(prefix) for prefix in forbidden_prefixes)
                or candidate["source_mail_message_id"] != evidence.mail_message_id
                or span["start"] >= span["end"]
                or span["end"] > len(authored)
                or authored[span["start"] : span["end"]] != span["text"]
                or candidate["scope"] not in spec["scopes"]
                or value_type not in spec["value_types"]
            ):
                raise MailFactGateError(
                    "mail_fact_gate_fact_candidate_invalid",
                    field_path=path,
                )
            seen.add(key)
            if value_type == "string" and _normalized(value) not in _normalized(
                span["text"]
            ):
                raise MailFactGateError(
                    "mail_fact_gate_fact_not_explicit",
                    field_path=path + ("fact_value",),
                )
            if value_type != "string" and str(value).casefold() not in _normalized(
                span["text"]
            ):
                raise MailFactGateError(
                    "mail_fact_gate_fact_not_explicit",
                    field_path=path + ("fact_value",),
                )
            scope = candidate["scope"]
            effective = candidate["effective_from"]
            expires = candidate["expires_at"]
            effective_at = (
                None
                if effective is None
                else _utc(effective, "mail_fact_gate_fact_time_invalid")
            )
            expires_at = (
                None
                if expires is None
                else _utc(expires, "mail_fact_gate_fact_time_invalid")
            )
            if scope == "message_only":
                if effective is not None or expires is not None:
                    raise MailFactGateError("mail_fact_gate_fact_scope_invalid")
            elif scope == "temporary":
                if (
                    effective_at is None
                    or expires_at is None
                    or effective_at >= expires_at
                    or expires_at <= as_of
                    or expires_at - effective_at
                    > timedelta(days=self.policy["limits"]["max_temporary_days"])
                ):
                    raise MailFactGateError("mail_fact_gate_fact_scope_invalid")
            elif (
                effective_at is None
                or expires_at is not None
                or not _has_phrase(span["text"], self.long_term_markers)
            ):
                raise MailFactGateError("mail_fact_gate_long_term_not_explicit")

            canonical_value = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            exact = tuple(
                row
                for row in active.get(key, ())
                if json.dumps(
                    row.fact_value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                == canonical_value
                and row.scope == scope
                and row.effective_from_utc == effective
                and row.expires_at_utc == expires
            )
            if len(exact) > 1:
                raise MailFactGateError("mail_fact_gate_fact_identity_ambiguous")
            if exact:
                accepted.append(
                    GatedFact(
                        key,
                        canonical_value,
                        scope,
                        effective,
                        expires,
                        candidate["confidence"],
                        "feedback_recorded",
                        None,
                        False,
                        exact[0].id,
                    )
                )
                continue
            conflicts = active.get(key, ())
            supersedes: int | None = None
            if conflicts:
                if len(conflicts) != 1 or not _has_phrase(
                    span["text"], self.supersession_markers
                ):
                    raise MailFactGateError(
                        "mail_fact_gate_fact_conflict",
                        disposition="operator_review",
                    )
                supersedes = conflicts[0].id
            accepted.append(
                GatedFact(
                    key,
                    canonical_value,
                    scope,
                    effective,
                    expires,
                    candidate["confidence"],
                    "feedback_recorded",
                    supersedes,
                    scope != "message_only",
                )
            )
        return tuple(accepted)

    def _plan_request(
        self,
        request: dict[str, Any],
        context: dict[str, Any],
        evidence: FactGateEvidence,
    ) -> GatedEvent:
        trigger = context["trigger_message"]
        plan = context["current_training_plan"]
        if plan is None:
            raise MailFactGateError(
                "mail_fact_gate_current_plan_missing",
                disposition="operator_review",
            )
        span = request["evidence_text_span"]
        authored = trigger["latest_authored_text"]
        if (
            request["source_mail_message_id"] != evidence.mail_message_id
            or request["trust_level"] != "user_asserted"
            or request["current_plan_id"] != plan["id"]
            or plan["subject_id"] != evidence.subject_id
            or span["start"] >= span["end"]
            or span["end"] > len(authored)
            or authored[span["start"] : span["end"]] != span["text"]
        ):
            raise MailFactGateError("mail_fact_gate_plan_request_invalid")
        start = _local_date(
            plan["plan_start_local_date"],
            "mail_fact_gate_plan_request_invalid",
        )
        end = _local_date(
            plan["plan_end_local_date"],
            "mail_fact_gate_plan_request_invalid",
        )
        dates = tuple(
            _local_date(item, "mail_fact_gate_plan_request_invalid")
            for item in request["affected_local_dates"]
        )
        effective = _local_date(
            request["effective_local_date"],
            "mail_fact_gate_plan_request_invalid",
        )
        if (
            len(set(dates)) != len(dates)
            or any(item < start or item > end for item in dates)
            or effective < start
            or effective > end
            or effective not in dates
            or any(
                key not in self.plan_constraint_keys
                for key in _iter_keys(request["constraints"])
            )
        ):
            raise MailFactGateError("mail_fact_gate_plan_request_invalid")
        explicit_text = _normalized(span["text"])
        trigger_day = (
            _utc(trigger["timestamp_utc"], "mail_fact_gate_plan_request_invalid")
            .astimezone(timezone(timedelta(hours=8)))
            .date()
        )
        relative_dates = {
            trigger_day + timedelta(days=1)
            if any(term in explicit_text for term in ("tomorrow", "明天"))
            else trigger_day
        }
        if any(
            item.isoformat() not in authored and item not in relative_dates
            for item in dates
        ):
            raise MailFactGateError("mail_fact_gate_plan_date_not_explicit")
        for item in _iter_strings(request["constraints"]):
            if (
                item not in request["affected_local_dates"]
                and _normalized(item) not in explicit_text
            ):
                raise MailFactGateError("mail_fact_gate_plan_constraint_not_explicit")
        payload = {
            "schema_version": "1",
            "policy_version": self.policy_version,
            "subject_id": evidence.subject_id,
            "run_key": evidence.run_key,
            "source_mail_message_id": evidence.mail_message_id,
            "source_mail_thread_id": evidence.mail_thread_id,
            "source_revision_id": evidence.source_revision_id,
            "value_origin": "user_asserted",
            "content_instruction_trust": "untrusted_content",
            "change_kind": request["change_kind"],
            "affected_local_dates": list(request["affected_local_dates"]),
            "constraints": request["constraints"],
            "effective_local_date": request["effective_local_date"],
            "current_plan_id": request["current_plan_id"],
            "evidence_text_span": request["evidence_text_span"],
        }
        return GatedEvent(
            "plan_revision_reason_recorded",
            "trainlab",
            trigger["timestamp_utc"],
            evidence.mail_message_id,
            evidence.run_key,
            "system_generated",
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )

    def _dependency(
        self,
        result: dict[str, Any],
        context: dict[str, Any],
        evidence: FactGateEvidence,
    ) -> tuple[bool, int | None, str]:
        dependency = evidence.dependency
        if dependency is None:
            return False, None, "mail_fact_gate_dependency_missing"
        plan = context["current_training_plan"]
        if (
            plan is None
            or dependency.subject_id != evidence.subject_id
            or dependency.artifact_id != plan["analysis_artifact_id"]
            or dependency.training_plan_id != plan["id"]
            or dependency.artifact_kind != "weekly_training_plan"
            or dependency.analysis_kind != "plan_revision"
            or dependency.analysis_status != "succeeded"
            or not dependency.is_current
            or dependency.training_plan_status not in {"active", "proposed"}
            or dependency.period_start_local_date != plan["plan_start_local_date"]
            or dependency.period_end_local_date != plan["plan_end_local_date"]
            or dependency.target_start_local_date != plan["plan_start_local_date"]
            or dependency.target_end_local_date != plan["plan_end_local_date"]
            or dependency.plan_start_local_date != plan["plan_start_local_date"]
            or dependency.plan_end_local_date != plan["plan_end_local_date"]
            or dependency.reason_event_id is None
            or dependency.reason_mail_message_id != evidence.mail_message_id
            or dependency.reason_actor_role != "trainlab"
            or dependency.reason_trust_level != "system_generated"
        ):
            code = (
                "mail_fact_gate_dependency_failed"
                if dependency.analysis_status in {"failed", "rejected"}
                else "mail_fact_gate_dependency_invalid"
            )
            return False, None, code
        manifest = {item["ordinal"]: item for item in context["input_manifest"]}
        used = {
            (item["input_role"], item["source_entity_id"])
            for item in result["source_usage"]
            if item["ordinal"] in manifest
        }
        if ("analysis_artifact", dependency.artifact_id) not in used or (
            "current_plan",
            dependency.training_plan_id,
        ) not in used:
            return False, None, "mail_fact_gate_dependency_source_missing"
        return True, dependency.artifact_id, "mail_fact_gate_dependency_ready"

    def evaluate(
        self,
        result_document: bytes | str | Mapping[str, Any],
        context: dict[str, Any],
        evidence: FactGateEvidence,
    ) -> FactGateDecision:
        limits = self.policy["limits"]
        result, _ = _strict_document(
            result_document,
            max_bytes=limits["max_result_bytes"],
            max_depth=limits["max_json_depth"],
            max_nodes=limits["max_json_nodes"],
            code="mail_fact_gate_result_invalid",
        )
        try:
            self.result_validator.input_context(context)
            self.result_validator.result(result, context)
        except MailRunnerError as exc:
            raise MailFactGateError(
                "mail_fact_gate_result_invalid",
                field_path=exc.field_path,
            ) from None
        self._identity(result, context, evidence)
        self._action(result)
        self._content(result, context)
        facts = self._facts(result, context, evidence)
        action = result["action"]
        event: GatedEvent | None = None
        dependency_id: int | None = None
        status = "accepted"
        reason = "mail_fact_gate_accepted"
        if action == "await_analysis":
            if result["intent"] != "plan_change_request":
                raise MailFactGateError("mail_fact_gate_plan_action_invalid")
            event = self._plan_request(
                result["plan_revision_request"], context, evidence
            )
            status = "dependency_wait"
            reason = "mail_fact_gate_dependency_requested"
        elif result["intent"] == "plan_change_request":
            if action != "reply":
                raise MailFactGateError("mail_fact_gate_plan_action_invalid")
            ready, dependency_id, reason = self._dependency(result, context, evidence)
            if not ready:
                status = "dependency_wait"
                action = "await_analysis"
        if reason not in self.reason_codes:
            raise MailFactGateError("mail_fact_gate_internal")
        return FactGateDecision(
            self.policy_version,
            status,
            action,
            reason,
            evidence.subject_id,
            evidence.run_id,
            evidence.run_key,
            evidence.mail_message_id,
            evidence.mail_thread_id,
            evidence.source_revision_id,
            event,
            facts,
            dependency_id,
        )


# Backward-neutral short name for M4-08 callers and fixtures.
FactGate = MailFactGate


def bind_reason_event(
    decision: FactGateDecision, reason_event_id: int
) -> FactGateDecision:
    if (
        decision.status != "dependency_wait"
        or decision.event is None
        or not isinstance(reason_event_id, int)
        or isinstance(reason_event_id, bool)
        or reason_event_id <= 0
    ):
        raise MailFactGateError("mail_fact_gate_reason_event_invalid")
    return replace(decision, reason_event_id=reason_event_id)
