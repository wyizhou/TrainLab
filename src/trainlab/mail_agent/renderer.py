"""Deterministic, inert rendering for accepted fourth-layer responses.

This module deliberately accepts the *published* user-visible response only.
It never accepts raw Gmail HTML, model protocol output, recipients, or a
caller-provided subject.  Gmail-specific sending is kept in ``delivery.py``.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_KIND = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_MAX_TEXT_BYTES = 80_000


class MailRenderError(ValueError):
    """A content-free rendering validation error."""


@dataclass(frozen=True, slots=True)
class RenderedMail:
    """The safe, deterministic representation passed to the restricted adapter."""

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
    if not isinstance(value, str) or not value.strip():
        raise MailRenderError("mail_response_text_invalid")
    if "\x00" in value or "\r" in value:
        raise MailRenderError("mail_response_text_invalid")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise MailRenderError("mail_response_text_invalid") from exc
    if len(encoded) > _MAX_TEXT_BYTES:
        raise MailRenderError("mail_response_text_invalid")
    return value


def render_mail_response(
    *,
    response_artifact_id: int,
    response_kind: str,
    user_visible_text: str,
    delivery_run_id: str,
) -> RenderedMail:
    """Render one immutable accepted response without interpreting its text.

    The returned HTML is made exclusively from escaped plaintext and fixed
    inline styles.  ``delivery_run_id`` is the idempotency/run header value
    requested from the Gmail MCP adapter; the adapter contract intentionally
    owns actual MIME header construction.
    """

    if (
        not isinstance(response_artifact_id, int)
        or isinstance(response_artifact_id, bool)
        or response_artifact_id <= 0
    ):
        raise MailRenderError("mail_response_artifact_id_invalid")
    if not isinstance(response_kind, str) or not _KIND.fullmatch(response_kind):
        raise MailRenderError("mail_response_kind_invalid")
    run_id = _require_identifier(delivery_run_id, code="mail_delivery_run_id_invalid")
    text = _require_visible_text(user_visible_text)

    # The subject is fixed by response metadata and the provider-visible run
    # id.  It cannot be supplied by an email body or a CLI caller.
    subject = f"TrainLab 回复 · {response_kind} · {run_id}"
    escaped = html.escape(text, quote=True).replace("\n", "<br>\n")
    rendered_html = (
        '<!doctype html><html><body style="margin:0;padding:0;background:#ffffff;">'
        '<div style="max-width:680px;margin:0 auto;padding:24px;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;'
        'font-size:16px;line-height:1.65;color:#1f2937;white-space:normal;">'
        f"{escaped}</div></body></html>"
    )
    message_token = hashlib.sha256(
        f"mail-response:{response_artifact_id}:{run_id}".encode("ascii")
    ).hexdigest()[:32]
    requested_message_id = f"<trainlab.{message_token}@local>"
    digest = hashlib.sha256(
        (subject + "\n" + text + "\n" + rendered_html).encode("utf-8")
    ).hexdigest()
    return RenderedMail(
        delivery_run_id=run_id,
        subject=subject,
        plain_text=text,
        html=rendered_html,
        requested_message_id=requested_message_id,
        content_sha256=digest,
    )
