"""Deterministic rendering for accepted fourth-layer replies.

Only the immutable, published response and its persisted trigger subject enter
this module.  The packaged template API escapes all visible values and rejects
unresolved design bindings before provider delivery.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from trainlab.email_templates import EmailTemplateError, render_template


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_KIND = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_RUN_MARKER = re.compile(r"\[\s*TrainLab(?:\s+idempotency)?\s*:[^\]]*\]", re.IGNORECASE)
_RUN_FIELD = re.compile(
    r"\b(?:run[- ]?id|idempotency(?:[- ]?key)?)\s*[:=]\s*[^\s|｜\]]+",
    re.IGNORECASE,
)
_RE_PREFIX = re.compile(r"^(?:\s*re\s*:\s*)+", re.IGNORECASE)
_MAX_TEXT_BYTES = 80_000
_MAX_SUBJECT_BYTES = 998
_REVISION_STATUSES = frozenset({"等待分析", "已生成修订建议", "需要用户补充信息"})

# These are the only structured values that may control the design.  They are
# published response content, not instructions or arbitrary template markup.
_STRING_FIELDS = frozenset({
    "preheader", "title", "subtitle", "subject_intent", "acknowledgement",
    "answer_summary",
    "explanation", "reply_text", "change_kind",
    "revision_status", "affected_dates", "effective_date",
    "change_constraints", "next_steps", "warnings", "safety_note",
    "data_limitations", "footer_note",
})


class MailRenderError(ValueError):
    """A content-free rendering validation error."""


@dataclass(frozen=True, slots=True)
class RenderedMail:
    """The safe deterministic representation passed to the restricted adapter."""

    delivery_run_id: str
    subject: str
    plain_text: str
    html: str
    requested_message_id: str
    content_sha256: str


def _require_identifier(value: object, *, code: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise MailRenderError(code)
    return value


def _require_visible_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value or "\r" in value:
        raise MailRenderError("mail_response_text_invalid")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise MailRenderError("mail_response_text_invalid") from exc
    if len(encoded) > _MAX_TEXT_BYTES:
        raise MailRenderError("mail_response_text_invalid")
    return value


def _safe_string(value: object) -> str:
    if not isinstance(value, str) or "\x00" in value or "\r" in value:
        raise MailRenderError("mail_response_structured_content_invalid")
    try:
        if len(value.encode("utf-8", errors="strict")) > _MAX_TEXT_BYTES:
            raise MailRenderError("mail_response_structured_content_invalid")
    except UnicodeError as exc:
        raise MailRenderError("mail_response_structured_content_invalid") from exc
    return value


def _reply_subject(value: object) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise MailRenderError("mail_original_subject_invalid")
    # Header injection is removed before prefix cleanup; provider validation is
    # still the final boundary for the resulting one-line value.
    cleaned = _RUN_MARKER.sub(" ", value.replace("\r", " ").replace("\n", " "))
    cleaned = _RUN_FIELD.sub(" ", cleaned)
    cleaned = _RE_PREFIX.sub("", cleaned).strip()
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        cleaned = "TrainLab 回复"
    while len(("Re: " + cleaned).encode("utf-8")) > _MAX_SUBJECT_BYTES:
        cleaned = cleaned[:-1]
        if not cleaned:
            raise MailRenderError("mail_original_subject_invalid")
    return "Re: " + cleaned


def _local_timestamp(value: object) -> tuple[str, str]:
    if value in (None, ""):
        return "", ""
    if not isinstance(value, str):
        raise MailRenderError("mail_response_timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise MailRenderError("mail_response_timestamp_invalid") from None
    if parsed.tzinfo is None:
        raise MailRenderError("mail_response_timestamp_invalid")
    local = parsed.astimezone(ZoneInfo("Asia/Singapore"))
    return f"{local.year}年{local.month}月{local.day}日", local.strftime("%Y-%m-%d %H:%M")


def _paragraphs(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", value) if part.strip()]


def _design_values(
    structured_content: object,
    user_visible_text: str,
    original_subject: object,
    generated_at_utc: object,
) -> tuple[dict[str, str], dict[str, object], dict[str, Sequence[str]]]:
    if structured_content is None:
        structured_content = {}
    if not isinstance(structured_content, Mapping) or any(
        not isinstance(key, str) for key in structured_content
    ):
        raise MailRenderError("mail_response_structured_content_invalid")
    structured = structured_content
    reply_date, generated_at_local = _local_timestamp(generated_at_utc)
    paragraphs = _paragraphs(user_visible_text)
    values: dict[str, str] = {
        "brand_name": "TrainLab",
        "preheader": user_visible_text,
        "title": "回复",
        "subtitle": "",
        "original_subject": _reply_subject(original_subject)[4:],
        "subject_intent": "回复当前邮件",
        "acknowledgement": "已收到你的邮件。",
        "answer_summary": paragraphs[0],
        "explanation": "\n\n".join(paragraphs[1:]),
        "change_kind": "",
        "revision_status": "",
        "affected_dates": "",
        "effective_date": "",
        "change_constraints": "",
        "next_steps": "",
        "warnings": "",
        "safety_note": "",
        "data_limitations": "",
        "reply_text": "",
        "footer_note": "TrainLab 会在信息充分时给出明确建议，在信息不足时保留不确定性。",
        "reply_date": reply_date,
        "generated_at_local": generated_at_local,
    }
    for key in _STRING_FIELDS:
        if key in structured:
            values[key] = _safe_string(structured[key])
    recommendations: list[str] = []
    if "recommendations" in structured:
        candidate = structured["recommendations"]
        if isinstance(candidate, (str, bytes)) or not isinstance(candidate, Sequence):
            raise MailRenderError("mail_response_structured_content_invalid")
        recommendations = [_safe_string(item) for item in candidate]
    if values["change_kind"] and values["revision_status"] not in _REVISION_STATUSES:
        raise MailRenderError("mail_response_revision_status_invalid")
    if values["revision_status"] and values["revision_status"] not in _REVISION_STATUSES:
        raise MailRenderError("mail_response_revision_status_invalid")
    for key in ("red_flag", "exercise_suspended"):
        if key in structured and not isinstance(structured[key], bool):
            raise MailRenderError("mail_response_structured_content_invalid")
    if (
        structured.get("red_flag") is True
        or structured.get("exercise_suspended") is True
    ) and not values["safety_note"]:
        raise MailRenderError("mail_response_safety_note_required")
    optional = {
        "change_kind": values["change_kind"],
        "recommendations": recommendations,
        "next_steps": values["next_steps"],
        "warnings": values["warnings"],
        "safety_note": values["safety_note"],
        "data_limitations": values["data_limitations"],
    }
    return values, optional, {"recommendations": recommendations}


def render_mail_response(
    *,
    response_artifact_id: int,
    response_kind: str,
    user_visible_text: str,
    delivery_run_id: str,
    structured_content: object = None,
    original_subject: str = "",
    generated_at_utc: str = "",
) -> RenderedMail:
    """Render the published reply in the fixed ``mail_reply`` design."""
    if not isinstance(response_artifact_id, int) or isinstance(response_artifact_id, bool) or response_artifact_id <= 0:
        raise MailRenderError("mail_response_artifact_id_invalid")
    if not isinstance(response_kind, str) or not _KIND.fullmatch(response_kind):
        raise MailRenderError("mail_response_kind_invalid")
    run_id = _require_identifier(delivery_run_id, code="mail_delivery_run_id_invalid")
    text = _require_visible_text(user_visible_text)
    fields, optional, repeats = _design_values(
        structured_content, text, original_subject, generated_at_utc
    )
    try:
        rendered_html = render_template(
            "mail_reply", fields=fields, optional=optional, repeats=repeats
        )
    except (EmailTemplateError, TypeError, ValueError) as exc:
        raise MailRenderError("mail_response_template_invalid") from exc
    subject = _reply_subject(original_subject)
    plain_parts = [
        fields["acknowledgement"],
        fields["answer_summary"],
        fields["explanation"],
    ]
    if fields["change_kind"]:
        plain_parts.append(
            "计划修改："
            + "；".join(
                value
                for value in (
                    fields["change_kind"],
                    fields["revision_status"],
                    fields["affected_dates"],
                    fields["effective_date"],
                    fields["change_constraints"],
                )
                if value
            )
        )
    plain_parts.extend(recommendations := list(repeats["recommendations"]))
    plain_parts.extend(
        fields[key]
        for key in (
            "next_steps",
            "reply_text",
            "warnings",
            "safety_note",
            "data_limitations",
        )
        if fields[key]
    )
    plain_text = "\n\n".join(
        dict.fromkeys(part for part in plain_parts if part)
    )
    if run_id in subject or run_id in plain_text or run_id in rendered_html:
        raise MailRenderError("mail_response_internal_identifier_visible")
    message_token = hashlib.sha256(
        f"mail-response:{response_artifact_id}:{run_id}".encode("ascii")
    ).hexdigest()[:32]
    requested_message_id = f"<trainlab.{message_token}@local>"
    digest = hashlib.sha256((subject + "\n" + plain_text + "\n" + rendered_html).encode("utf-8")).hexdigest()
    return RenderedMail(run_id, subject, plain_text, rendered_html, requested_message_id, digest)
