"""M4-09 immutable response publication boundary.

The gate is intentionally evaluated before this module is called.  This module
only translates the already-approved decision and the ordered context manifest
into one durable, auditable response revision; it has no Gmail or Codex access.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .fact_gate import FactGateDecision
from .repository import (
    AcceptedResponseDraft,
    DeliveryDraft,
    EventDraft,
    FactDraft,
    InputDraft,
    MailRepository,
    PublishedResponse,
)

_AUTO_DELIVERY_KEY = "mail:response:auto"


class MailPublicationError(RuntimeError):
    """Stable, content-free M4-09 publication failure."""


@dataclass(frozen=True)
class MailResponsePublication:
    response_artifact_id: int
    delivery_id: int
    unchanged: bool


class MailResponsePublisher:
    """Publish one validated reply and its complete ordered input lineage."""

    def __init__(self, repository: MailRepository) -> None:
        self._repository = repository

    def publish(
        self,
        decision: FactGateDecision,
        context: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> MailResponsePublication:
        draft = self._draft(decision, context, result)
        existing = self._repository.connection.execute(
            "SELECT id FROM mail_response_artifacts WHERE generated_by_mail_agent_run_id=?",
            (decision.run_id,),
        ).fetchone()
        published = self._repository.publish_accepted_response(
            decision.run_id,
            draft,
            advance_processing_state=True,
        )
        if published.delivery_id is None:
            raise MailPublicationError("mail_publication_delivery_missing")
        return MailResponsePublication(
            published.response_artifact_id,
            published.delivery_id,
            existing is not None,
        )

    def _draft(
        self,
        decision: FactGateDecision,
        context: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> AcceptedResponseDraft:
        if (
            decision.status != "accepted"
            or decision.action != "reply"
            or not isinstance(decision.run_id, int)
            or decision.run_id <= 0
            or not isinstance(decision.mail_message_id, int)
            or decision.mail_message_id <= 0
            or not isinstance(decision.mail_thread_id, int)
            or decision.mail_thread_id <= 0
        ):
            raise MailPublicationError("mail_publication_decision_invalid")
        try:
            run = context["run"]
            trigger = context["trigger_message"]
            manifest = context["input_manifest"]
            response = result["response"]
            schema_version = result["schema_version"]
        except (KeyError, TypeError) as exc:
            raise MailPublicationError("mail_publication_input_invalid") from None
        if (
            not isinstance(run, Mapping)
            or run.get("id") != decision.run_id
            or run.get("run_key") != decision.run_key
            or result.get("run_key") != decision.run_key
            or result.get("trigger_message_id") != decision.mail_message_id
            or not isinstance(trigger, Mapping)
            or trigger.get("id") != decision.mail_message_id
            or trigger.get("thread_id") != decision.mail_thread_id
            or not isinstance(response, Mapping)
            or not isinstance(schema_version, str)
            or not schema_version
        ):
            raise MailPublicationError("mail_publication_identity_invalid")
        provider_thread_id = trigger.get("provider_thread_id")
        if not isinstance(provider_thread_id, str) or not provider_thread_id:
            raise MailPublicationError("mail_publication_thread_invalid")
        try:
            response_kind = response["response_kind"]
            structured = response["structured_content"]
            user_visible_text = response["user_visible_text"]
            requires_thread_reply = response["requires_thread_reply"]
        except (KeyError, TypeError) as exc:
            raise MailPublicationError("mail_publication_response_invalid") from None
        if (
            not isinstance(response_kind, str)
            or not isinstance(user_visible_text, str)
            or not user_visible_text
            or requires_thread_reply is not True
        ):
            raise MailPublicationError("mail_publication_response_invalid")
        try:
            structured_content_json = json.dumps(
                structured,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise MailPublicationError("mail_publication_response_invalid") from None
        inputs = self._ordered_inputs(manifest)
        events: tuple[EventDraft, ...] = ()
        facts: list[FactDraft] = []
        persistent = tuple(item for item in decision.facts if item.persist)
        if persistent:
            timestamp = trigger.get("timestamp_utc")
            if not isinstance(timestamp, str):
                raise MailPublicationError("mail_publication_timestamp_invalid")
            events = (
                EventDraft(
                    "feedback_recorded",
                    "user",
                    timestamp,
                    decision.mail_message_id,
                    "untrusted_content",
                    related_run_key=decision.run_key,
                ),
            )
            for item in persistent:
                if item.source_event_type != "feedback_recorded":
                    raise MailPublicationError("mail_publication_fact_source_invalid")
                facts.append(
                    FactDraft(
                        item.fact_key,
                        item.fact_value_json,
                        item.scope,
                        item.source_event_type,
                        item.confidence,
                        item.effective_from_utc,
                        item.expires_at_utc,
                        True,
                        item.supersedes_fact_id,
                    )
                )
        return AcceptedResponseDraft(
            mail_thread_id=decision.mail_thread_id,
            in_reply_to_mail_message_id=decision.mail_message_id,
            response_kind=response_kind,
            schema_version=schema_version,
            structured_content_json=structured_content_json,
            user_visible_text=user_visible_text,
            inputs=inputs,
            events=events,
            facts=tuple(facts),
            delivery=DeliveryDraft(_AUTO_DELIVERY_KEY, provider_thread_id),
        )

    @staticmethod
    def _ordered_inputs(value: object) -> tuple[InputDraft, ...]:
        if not isinstance(value, list):
            raise MailPublicationError("mail_publication_manifest_invalid")
        ordered: list[InputDraft] = []
        for ordinal, item in enumerate(value):
            if (
                not isinstance(item, Mapping)
                or item.get("ordinal") != ordinal
                or not isinstance(item.get("input_role"), str)
                or not isinstance(item.get("source_entity_type"), str)
                or not isinstance(item.get("source_entity_id"), int)
                or isinstance(item.get("source_entity_id"), bool)
                or not isinstance(item.get("input_sha256"), str)
                or not isinstance(item.get("trust_class"), str)
            ):
                raise MailPublicationError("mail_publication_manifest_invalid")
            revision = item.get("source_revision_id")
            if revision is not None and (
                not isinstance(revision, int) or isinstance(revision, bool)
            ):
                raise MailPublicationError("mail_publication_manifest_invalid")
            ordered.append(
                InputDraft(
                    item["input_role"],
                    item["source_entity_type"],
                    item["input_sha256"],
                    item["trust_class"],
                    item["source_entity_id"],
                    revision,
                )
            )
        if not ordered or ordered[0].input_role != "trigger_message":
            raise MailPublicationError("mail_publication_manifest_invalid")
        return tuple(ordered)
