"""A3-15 restricted self-delivery gateway for the current Gmail MCP environment.

This boundary has no SQLite knowledge and never exposes a generic Gmail tool
surface.  Its only purpose is to reconcile one complete, idempotency-bearing
subject and, if absent, send a self-addressed multipart message then apply the
``TrainLab`` label.  Provider payloads are parsed in memory and are never
included in exceptions or receipts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from html import escape
from typing import Any, Callable, Literal, Protocol

from .gmail_environment import (
    GmailEnvironmentStatus,
    inspect_gmail_environment,
)
from .mcp import MCPResponseError, StdioMCPClient, normalize_tool_result

_REQUIRED_TOOLS = frozenset(
    {"search_emails", "send_email", "get_or_create_label", "modify_email"}
)
_LABEL_NAME = "TrainLab"
_OAUTH_COPY_NOTICE = "OAuth keys found in current directory, copied to global config."
_EMAIL = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+\Z"
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_PROVIDER_ID = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")
_ANGLE_ADDRESS = re.compile(r"[^<>\r\n]*<([^<>\s]+)>\Z")


class GmailDeliveryError(RuntimeError):
    """Stable, non-secret provider-boundary failure."""

    def __init__(
        self,
        code: str,
        *,
        may_have_sent: bool = False,
        provider_message_id: str | None = None,
        provider_thread_id: str | None = None,
    ) -> None:
        self.code = code
        self.may_have_sent = may_have_sent
        self.provider_message_id = (
            _provider_id(provider_message_id)
            if provider_message_id is not None
            else None
        )
        self.provider_thread_id = (
            _provider_id(provider_thread_id) if provider_thread_id is not None else None
        )
        super().__init__(code)


class GmailDeliveryClient(Protocol):
    def list_tools(self) -> list[dict[str, Any]]: ...
    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class GmailDeliveryReceipt:
    """Safe evidence for a caller-owned delivery state machine."""

    status: Literal["sent", "already_sent", "not_found"]
    provider_message_id: str | None
    provider_thread_id: str | None
    label_id: str | None
    provider_sent_at_utc: str | None


@dataclass(frozen=True)
class _SearchMatch:
    provider_message_id: str
    provider_thread_id: str | None
    provider_sent_at_utc: str


def canonical_self_recipient(value: str) -> str:
    """Accept exactly one explicit, canonical email address supplied at runtime."""

    if (
        not isinstance(value, str)
        or value != value.strip()
        or not _EMAIL.fullmatch(value)
    ):
        raise GmailDeliveryError("gmail_delivery_recipient_invalid")
    return value.lower()


def _safe_text(
    value: object, *, code: str, allow_empty: bool = False, maximum: int = 1_000_000
) -> str:
    if (
        not isinstance(value, str)
        or (not allow_empty and not value)
        or len(value) > maximum
    ):
        raise GmailDeliveryError(code)
    if "\x00" in value:
        raise GmailDeliveryError(code)
    return value


def _safe_header(value: object, *, code: str) -> str:
    text = _safe_text(value, code=code, maximum=998)
    if "\r" in text or "\n" in text:
        raise GmailDeliveryError(code)
    return text


def _query_for_key(key: str) -> str:
    # Gmail does not reliably index a complete subject as one phrase. Search the
    # unique transport marker in HTML, then require the returned metadata to
    # match the complete user-visible subject and self sender.
    if '"' in key:
        raise GmailDeliveryError("gmail_delivery_idempotency_invalid")
    return f'in:sent "{key}"'


def _with_transport_marker(html: str, key: str) -> str:
    """Add a searchable but visually-hidden idempotency marker to HTML only."""
    marker = (
        '<div style="display:none!important;max-height:0;max-width:0;overflow:hidden;'
        'opacity:0;color:transparent;font-size:0;line-height:0;mso-hide:all" '
        'aria-hidden="true">TrainLab transport marker: '
        f"{escape(key, quote=False)}</div>"
    )
    closing = re.search(r"</body\s*>", html, flags=re.IGNORECASE)
    return (
        html + marker
        if closing is None
        else html[: closing.start()] + marker + html[closing.start() :]
    )


def _result_payload(value: Any) -> Any:
    """Normalize MCP content without ever reflecting raw payloads."""

    try:
        normalized = normalize_tool_result(value)
    except Exception:
        raise GmailDeliveryError("gmail_delivery_protocol_invalid") from None
    if isinstance(normalized, str):
        try:
            normalized = json.loads(normalized)
        except (TypeError, json.JSONDecodeError):
            # The installed package returns plain text.  Individual tool
            # parsers below allow only their exact documented grammars.
            pass
    return normalized


def _provider_id(value: object) -> str | None:
    if isinstance(value, str) and _PROVIDER_ID.fullmatch(value):
        return value
    return None


def _sender_matches(value: object, recipient: str) -> bool:
    """Compare a provider sender slot without preserving its display name."""

    if not isinstance(value, str) or "\r" in value or "\n" in value:
        return False
    candidate = value.strip()
    match = _ANGLE_ADDRESS.fullmatch(candidate)
    if match is not None:
        candidate = match.group(1)
    try:
        return canonical_self_recipient(candidate) == recipient
    except GmailDeliveryError:
        return False


def _rfc_date_utc(value: object) -> str:
    if not isinstance(value, str) or not value or "\r" in value or "\n" in value:
        raise GmailDeliveryError("gmail_delivery_search_identity_unverified")
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        raise GmailDeliveryError("gmail_delivery_search_identity_unverified") from None
    if parsed is None or parsed.tzinfo is None:
        raise GmailDeliveryError("gmail_delivery_search_identity_unverified")
    return (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _search_match(row: object, *, recipient: str, subject: str) -> _SearchMatch:
    if not isinstance(row, dict):
        raise GmailDeliveryError("gmail_delivery_protocol_invalid")
    candidate = (
        _provider_id(row.get("id"))
        or _provider_id(row.get("messageId"))
        or _provider_id(row.get("message_id"))
    )
    if candidate is None:
        raise GmailDeliveryError("gmail_delivery_protocol_invalid")
    if row.get("subject") != subject or not _sender_matches(
        row.get("from", row.get("fromEmail", row.get("sender"))), recipient
    ):
        raise GmailDeliveryError("gmail_delivery_search_identity_unverified")
    return _SearchMatch(
        candidate,
        _provider_id(row.get("threadId")) or _provider_id(row.get("thread_id")),
        _rfc_date_utc(row.get("date", row.get("Date"))),
    )


def _search_matches(
    value: Any, *, recipient: str, subject: str
) -> tuple[_SearchMatch, ...]:
    """Parse structured test fixtures or exact plain-text package output."""

    if isinstance(value, str):
        if value == "":
            return ()
        if not value.endswith("\n") or value.endswith("\n\n"):
            raise GmailDeliveryError("gmail_delivery_protocol_invalid")
        blocks = value[:-1].split("\n\n")
        if not blocks or any(not block for block in blocks):
            raise GmailDeliveryError("gmail_delivery_protocol_invalid")
        parsed_rows: list[dict[str, str]] = []
        for block in blocks:
            plain_match = re.fullmatch(
                r"ID: ([A-Za-z0-9_-]{1,256})\nSubject: ([^\r\n]*)\nFrom: ([^\r\n]*)\nDate: ([^\r\n]+)",
                block,
            )
            if plain_match is None:
                raise GmailDeliveryError("gmail_delivery_protocol_invalid")
            parsed_rows.append(
                {
                    "id": plain_match.group(1),
                    "subject": plain_match.group(2),
                    "from": plain_match.group(3),
                    "date": plain_match.group(4),
                }
            )
        value = {"emails": parsed_rows}
    if not isinstance(value, dict):
        raise GmailDeliveryError("gmail_delivery_protocol_invalid")
    raw_rows = value.get("emails", value.get("messages", value.get("results")))
    if not isinstance(raw_rows, list):
        raise GmailDeliveryError("gmail_delivery_protocol_invalid")
    rows: list[object] = raw_rows
    result: list[_SearchMatch] = []
    for row_value in rows:
        match = _search_match(row_value, recipient=recipient, subject=subject)
        if match.provider_message_id not in {
            match.provider_message_id for match in result
        }:
            result.append(match)
    return tuple(result)


def _sent_message(value: Any) -> tuple[str, str | None]:
    if isinstance(value, str):
        match = re.fullmatch(
            r"Email sent successfully with ID: ([A-Za-z0-9_-]{1,256})", value
        )
        if match is None:
            raise GmailDeliveryError("gmail_delivery_protocol_invalid")
        return match.group(1), None
    if not isinstance(value, dict):
        raise GmailDeliveryError("gmail_delivery_protocol_invalid")
    message_id = (
        _provider_id(value.get("id"))
        or _provider_id(value.get("messageId"))
        or _provider_id(value.get("message_id"))
    )
    if message_id is None:
        raise GmailDeliveryError("gmail_delivery_protocol_invalid")
    thread_id = _provider_id(value.get("threadId")) or _provider_id(
        value.get("thread_id")
    )
    return message_id, thread_id


def _label_id(value: Any) -> str:
    if isinstance(value, str):
        match = re.fullmatch(
            r"Successfully (?:created|retrieved|found existing) label:\nID: ([A-Za-z0-9_-]{1,256})\nName: TrainLab\nType: ([A-Za-z_]+)",
            value,
        )
        if match is None:
            raise GmailDeliveryError("gmail_delivery_protocol_invalid")
        return match.group(1)
    if not isinstance(value, dict):
        raise GmailDeliveryError("gmail_delivery_protocol_invalid")
    label_id = (
        _provider_id(value.get("id"))
        or _provider_id(value.get("labelId"))
        or _provider_id(value.get("label_id"))
    )
    if label_id is None:
        raise GmailDeliveryError("gmail_delivery_protocol_invalid")
    return label_id


def _modified_message(value: Any, *, expected_message_id: str) -> None:
    if isinstance(value, str):
        if value != f"Email {expected_message_id} labels updated successfully":
            raise GmailDeliveryError("gmail_delivery_protocol_invalid")
        return
    if not isinstance(value, dict):
        raise GmailDeliveryError("gmail_delivery_protocol_invalid")
    actual = (
        _provider_id(value.get("id"))
        or _provider_id(value.get("messageId"))
        or _provider_id(value.get("message_id"))
    )
    if actual != expected_message_id:
        raise GmailDeliveryError("gmail_delivery_protocol_invalid")


class GmailDeliveryGateway:
    """Strict, injectable A3-15 Gmail gateway.

    The caller supplies the already-approved self address.  The default client
    always starts the exact portable package after validating the current Codex
    environment registration; it never uses a local credential path or config.
    """

    def __init__(
        self,
        recipient: str,
        *,
        inspector: Callable[[], GmailEnvironmentStatus] = inspect_gmail_environment,
        client_factory: Callable[..., GmailDeliveryClient] = StdioMCPClient,
        timeout_seconds: int = 60,
    ) -> None:
        self._recipient = canonical_self_recipient(recipient)
        if (
            not isinstance(timeout_seconds, int)
            or isinstance(timeout_seconds, bool)
            or not 1 <= timeout_seconds <= 300
        ):
            raise GmailDeliveryError("gmail_delivery_timeout_invalid")
        self._inspector = inspector
        self._client_factory = client_factory
        self._timeout_seconds = timeout_seconds

    def deliver(
        self,
        *,
        subject: str,
        idempotency_key: str,
        plain_text: str,
        html: str,
    ) -> GmailDeliveryReceipt:
        """Reconcile by complete subject, then send and label exactly once."""

        subject = _safe_header(subject, code="gmail_delivery_subject_invalid")
        key = _safe_header(idempotency_key, code="gmail_delivery_idempotency_invalid")
        if not _IDENTIFIER.fullmatch(key):
            raise GmailDeliveryError("gmail_delivery_idempotency_invalid")
        plain_text = _safe_text(plain_text, code="gmail_delivery_body_invalid")
        html = _safe_text(html, code="gmail_delivery_body_invalid")
        if key in plain_text or key in html:
            raise GmailDeliveryError("gmail_delivery_idempotency_invalid")
        html = _with_transport_marker(html, key)
        query = _query_for_key(key)

        status = self._inspector()
        if not isinstance(status, GmailEnvironmentStatus) or not status.available:
            code = (
                status.code
                if isinstance(status, GmailEnvironmentStatus)
                and status.code
                in {"gmail_mcp_not_configured", "gmail_mcp_binding_invalid"}
                else "gmail_delivery_binding_invalid"
            )
            raise GmailDeliveryError(code)

        client: GmailDeliveryClient | None = None
        send_started = False
        sent_id: str | None = None
        sent_thread_id: str | None = None
        try:
            client = self._client_factory(
                status.command,
                list(status.args),
                timeout=self._timeout_seconds,
                stdout_preamble_lines=(_OAUTH_COPY_NOTICE,),
            )
            available = self._available_tools(client)
            if not _REQUIRED_TOOLS.issubset(available):
                raise GmailDeliveryError("gmail_delivery_capability_mismatch")

            existing = _search_matches(
                _result_payload(
                    client.call_tool("search_emails", {"query": query, "maxResults": 2})
                ),
                recipient=self._recipient,
                subject=subject,
            )
            if len(existing) == 1:
                item = existing[0]
                try:
                    label_id = self._apply_label(client, item.provider_message_id)
                except GmailDeliveryError as exc:
                    raise GmailDeliveryError(
                        exc.code,
                        may_have_sent=True,
                        provider_message_id=item.provider_message_id,
                        provider_thread_id=item.provider_thread_id,
                    ) from None
                except Exception as exc:
                    raise self._translate(
                        exc,
                        may_have_sent=True,
                        provider_message_id=item.provider_message_id,
                        provider_thread_id=item.provider_thread_id,
                    ) from None
                return GmailDeliveryReceipt(
                    "already_sent",
                    item.provider_message_id,
                    item.provider_thread_id,
                    label_id,
                    item.provider_sent_at_utc,
                )
            if len(existing) > 1:
                raise GmailDeliveryError("gmail_delivery_idempotency_ambiguous")

            send_started = True
            sent_id, sent_thread_id = _sent_message(
                _result_payload(
                    client.call_tool(
                        "send_email",
                        {
                            "to": [self._recipient],
                            "from": self._recipient,
                            "subject": subject,
                            "body": plain_text,
                            "htmlBody": html,
                            "mimeType": "multipart/alternative",
                        },
                    )
                )
            )
            label_id = self._apply_label(client, sent_id)
            return GmailDeliveryReceipt("sent", sent_id, sent_thread_id, label_id, None)
        except GmailDeliveryError as exc:
            if send_started and not exc.may_have_sent:
                raise GmailDeliveryError(
                    exc.code,
                    may_have_sent=True,
                    provider_message_id=sent_id,
                    provider_thread_id=sent_thread_id,
                ) from None
            raise
        except Exception as exc:
            raise self._translate(
                exc,
                may_have_sent=send_started,
                provider_message_id=sent_id,
                provider_thread_id=sent_thread_id,
            ) from None
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    def reconcile(self, *, subject: str, idempotency_key: str) -> GmailDeliveryReceipt:
        """Look up and label an existing self-send; this method never sends."""

        subject = _safe_header(subject, code="gmail_delivery_subject_invalid")
        key = _safe_header(idempotency_key, code="gmail_delivery_idempotency_invalid")
        if not _IDENTIFIER.fullmatch(key):
            raise GmailDeliveryError("gmail_delivery_idempotency_invalid")
        status = self._inspector()
        if not isinstance(status, GmailEnvironmentStatus) or not status.available:
            code = (
                status.code
                if isinstance(status, GmailEnvironmentStatus)
                and status.code
                in {"gmail_mcp_not_configured", "gmail_mcp_binding_invalid"}
                else "gmail_delivery_binding_invalid"
            )
            raise GmailDeliveryError(code)
        client: GmailDeliveryClient | None = None
        try:
            client = self._client_factory(
                status.command,
                list(status.args),
                timeout=self._timeout_seconds,
                stdout_preamble_lines=(_OAUTH_COPY_NOTICE,),
            )
            if not _REQUIRED_TOOLS.issubset(self._available_tools(client)):
                raise GmailDeliveryError("gmail_delivery_capability_mismatch")
            matches = _search_matches(
                _result_payload(
                    client.call_tool(
                        "search_emails", {"query": _query_for_key(key), "maxResults": 2}
                    )
                ),
                recipient=self._recipient,
                subject=subject,
            )
            if not matches:
                return GmailDeliveryReceipt("not_found", None, None, None, None)
            if len(matches) > 1:
                raise GmailDeliveryError("gmail_delivery_idempotency_ambiguous")
            item = matches[0]
            try:
                label_id = self._apply_label(client, item.provider_message_id)
            except GmailDeliveryError as exc:
                raise GmailDeliveryError(
                    exc.code,
                    may_have_sent=True,
                    provider_message_id=item.provider_message_id,
                    provider_thread_id=item.provider_thread_id,
                ) from None
            except Exception as exc:
                raise self._translate(
                    exc,
                    may_have_sent=True,
                    provider_message_id=item.provider_message_id,
                    provider_thread_id=item.provider_thread_id,
                ) from None
            return GmailDeliveryReceipt(
                "already_sent",
                item.provider_message_id,
                item.provider_thread_id,
                label_id,
                item.provider_sent_at_utc,
            )
        except GmailDeliveryError:
            raise
        except Exception as exc:
            raise self._translate(exc) from None
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    @staticmethod
    def _apply_label(client: GmailDeliveryClient, message_id: str) -> str:
        label_id = _label_id(
            _result_payload(
                client.call_tool("get_or_create_label", {"name": _LABEL_NAME})
            )
        )
        # This has no destructive remove or replacement labels: it only adds
        # the dedicated TrainLab label to the specific already-known message.
        _modified_message(
            _result_payload(
                client.call_tool(
                    "modify_email",
                    {
                        "messageId": message_id,
                        "addLabelIds": [label_id],
                    },
                )
            ),
            expected_message_id=message_id,
        )
        return label_id

    @staticmethod
    def _available_tools(client: GmailDeliveryClient) -> frozenset[str]:
        try:
            values = client.list_tools()
        except Exception as exc:
            raise GmailDeliveryGateway._translate(exc) from None
        if not isinstance(values, list):
            raise GmailDeliveryError("gmail_delivery_protocol_invalid")
        result: set[str] = set()
        for item in values:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise GmailDeliveryError("gmail_delivery_protocol_invalid")
            result.add(item["name"])
        return frozenset(result)

    @staticmethod
    def _translate(
        exc: Exception,
        *,
        may_have_sent: bool = False,
        provider_message_id: str | None = None,
        provider_thread_id: str | None = None,
    ) -> GmailDeliveryError:
        def error(code: str) -> GmailDeliveryError:
            return GmailDeliveryError(
                code,
                may_have_sent=may_have_sent,
                provider_message_id=provider_message_id,
                provider_thread_id=provider_thread_id,
            )

        if isinstance(exc, TimeoutError):
            return error("gmail_delivery_timeout")
        if isinstance(exc, MCPResponseError):
            if exc.status_code == 401:
                return error("gmail_delivery_auth_required")
            if exc.status_code == 403:
                return error("gmail_delivery_forbidden")
            if exc.status_code == 429:
                return error("gmail_delivery_rate_limited")
            if exc.status_code is not None and 500 <= exc.status_code <= 599:
                return error("gmail_delivery_provider_error")
            return error(
                "gmail_delivery_protocol_error"
                if exc.kind in {"protocol", "tool"}
                else "gmail_delivery_transport_error"
            )
        return error("gmail_delivery_transport_error")
