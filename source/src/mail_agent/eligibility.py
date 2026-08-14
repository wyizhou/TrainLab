"""Deterministic inbound eligibility and loop-prevention policy (M4-05).

This module deliberately has no provider, database, or model dependency.  A
caller supplies the canonical message plus *local* evidence; a MIME header is
content supplied by the provider and is therefore never outbound evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

TRAINLAB_LABEL = "TrainLab"

# These strings are persisted only as bounded reason codes, never as provider
# content.  They are also the public, recomputable policy catalogue.
REASON_CODES = frozenset(
    {
        "eligible_tracked_thread_reply",
        "eligible_labeled_new_request",
        "local_trainlab_outbound",
        "forged_or_unverified_run_header",
        "identity_unverified",
        "ordinary_unlabeled_private_message",
        "subject_only_trainlab_reference",
        "excluded_mailbox_state",
        "automatic_response",
        "attachment_only_no_body",
        "empty_body_no_content",
        "acknowledgement_store_only",
        "already_terminal",
        "incomplete_provider_object",
    }
)


@dataclass(frozen=True)
class ActorEvidence:
    """Only ``local_outbound`` may establish the TrainLab actor."""

    local_outbound: bool = False
    tracked_thread: bool = False
    trainlab_label: bool = False
    has_run_header: bool = False


@dataclass(frozen=True)
class CanonicalMessage:
    provider_message_id: str
    sender_is_self: bool
    recipient_is_self: bool
    labels: frozenset[str]
    subject: str | None
    body_text: str | None
    attachment_count: int
    auto_submitted: str | None = None
    is_bounce: bool = False
    is_complete: bool = True


@dataclass(frozen=True)
class Classification:
    actor_role: str
    direction: str
    processing_state: str
    event_type: str
    reason_code: str
    eligible: bool


def _acknowledgement(text: str) -> bool:
    # Conservative exact acknowledgement policy.  Do not turn substantive
    # questions containing a polite word into store-only.
    normalized = "".join(text.strip().lower().split())
    return normalized in {
        "谢谢",
        "感谢",
        "收到",
        "好的",
        "好",
        "ok",
        "okay",
        "thanks",
        "thankyou",
    }


def _automatic(message: CanonicalMessage) -> bool:
    subject = (message.subject or "").strip().lower()
    auto = (message.auto_submitted or "").strip().lower()
    return (
        message.is_bounce
        or auto not in {"", "no"}
        or subject.startswith(
            (
                "automatic reply",
                "auto-reply",
                "out of office",
                "vacation",
                "undeliverable",
                "delivery status",
            )
        )
    )


def classify(message: CanonicalMessage, evidence: ActorEvidence) -> Classification:
    """Classify one normalized message without expanding discovery scope."""
    if not message.is_complete:
        return Classification(
            "unknown",
            "unknown",
            "quarantined",
            "mail_quarantined",
            "incomplete_provider_object",
            False,
        )
    if evidence.local_outbound:
        return Classification(
            "trainlab",
            "outbound",
            "ignored",
            "mail_ignored",
            "local_trainlab_outbound",
            False,
        )
    if not message.sender_is_self or not message.recipient_is_self:
        return Classification(
            "unknown",
            "unknown",
            "quarantined",
            "mail_quarantined",
            "identity_unverified",
            False,
        )
    lowered_labels = {label.lower() for label in message.labels}
    if {"draft", "spam", "trash"} & lowered_labels:
        return Classification(
            "user",
            "inbound",
            "ignored",
            "mail_ignored",
            "excluded_mailbox_state",
            False,
        )
    if _automatic(message):
        return Classification(
            "user", "inbound", "ignored", "mail_ignored", "automatic_response", False
        )
    body = (message.body_text or "").strip()
    if not body and message.attachment_count:
        return Classification(
            "user",
            "inbound",
            "ignored",
            "mail_ignored",
            "attachment_only_no_body",
            False,
        )
    if not body:
        return Classification(
            "user", "inbound", "ignored", "mail_ignored", "empty_body_no_content", False
        )
    if evidence.tracked_thread:
        if _acknowledgement(body):
            return Classification(
                "user",
                "inbound",
                "store_only",
                "reply_received",
                "acknowledgement_store_only",
                False,
            )
        return Classification(
            "user",
            "inbound",
            "queued",
            "reply_received",
            "eligible_tracked_thread_reply",
            True,
        )
    if evidence.trainlab_label:
        if evidence.has_run_header:
            # A label alone does not authenticate a purported run marker.
            return Classification(
                "unknown",
                "unknown",
                "quarantined",
                "mail_quarantined",
                "forged_or_unverified_run_header",
                False,
            )
        if _acknowledgement(body):
            return Classification(
                "user",
                "inbound",
                "store_only",
                "new_request_received",
                "acknowledgement_store_only",
                False,
            )
        return Classification(
            "user",
            "inbound",
            "queued",
            "new_request_received",
            "eligible_labeled_new_request",
            True,
        )
    if evidence.has_run_header:
        # The header is forgeable, even when it looks like an existing run.
        return Classification(
            "unknown",
            "unknown",
            "quarantined",
            "mail_quarantined",
            "forged_or_unverified_run_header",
            False,
        )
    if "trainlab" in (message.subject or "").lower():
        return Classification(
            "user",
            "inbound",
            "ignored",
            "mail_ignored",
            "subject_only_trainlab_reference",
            False,
        )
    return Classification(
        "user",
        "inbound",
        "ignored",
        "mail_ignored",
        "ordinary_unlabeled_private_message",
        False,
    )
