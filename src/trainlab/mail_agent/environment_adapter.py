"""Restricted portable Gmail adapter for fourth-layer reply delivery.

This module deliberately admits only the current Codex ``gmail`` binding and
the fixed tools offered by ``@artymclabin/gmail-mcp``.  It has no generic
recipient, query, attachment, credential, or provider-payload surface.  The
adapter is injectable so all validation can be exercised without opening a
mailbox or starting a provider process.
"""

from __future__ import annotations

import json
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import stat
import time
from datetime import date, datetime, timezone
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Protocol

from ..integrations.gmail_environment import (
    GMAIL_MCP_OAUTH_COPY_NOTICE,
    GMAIL_MCP_PACKAGE,
    GmailEnvironmentStatus,
    inspect_gmail_environment,
)
from ..integrations.mcp import MCPResponseError, StdioMCPClient, normalize_tool_result
from .gmail_adapter import (
    GmailAdapterError,
    GmailIdentity,
    GmailMessage,
    GmailThread,
    GmailThreadEvidence,
    SendReceipt,
)
from .contracts import utc_now


_REQUIRED_TOOLS = frozenset(
    {
        "search_emails",
        "get_thread",
        "send_email",
        "get_or_create_label",
        "modify_email",
    }
)
_EMAIL = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+\Z"
)
_ID = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_MARKER_PREFIX = "[TrainLab idempotency: "
_IDENTITY_KEY_FILENAME = "gmail-recipient-identity.key"
_IDENTITY_KEY_BYTES = 32
_MAIL_SUBJECT_ID = 1


class GmailEnvironmentAdapterError(GmailAdapterError):
    """Stable, content-free boundary error."""

    def __init__(self, code: str, *, retry_at_seconds: int | None = None) -> None:
        super().__init__(code, retry_at_seconds=retry_at_seconds)


class GmailEnvironmentClient(Protocol):
    def list_tools(self) -> list[dict[str, Any]]: ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...

    def close(self) -> None: ...


def canonical_recipient_email(value: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not _EMAIL.fullmatch(value):
        raise GmailEnvironmentAdapterError("gmail_reply_self_invalid")
    return value.lower()


def _identifier(value: object, *, code: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise GmailEnvironmentAdapterError(code)
    return value


def _text(value: object, *, code: str, maximum: int = 80_000) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8", errors="strict")) > maximum:
        raise GmailEnvironmentAdapterError(code)
    if "\x00" in value or "\r" in value:
        raise GmailEnvironmentAdapterError(code)
    return value


def _marker(key: str) -> str:
    if not _KEY.fullmatch(key):
        raise GmailEnvironmentAdapterError("gmail_reply_idempotency_invalid")
    return f"{_MARKER_PREFIX}{key}]"


def _result(value: Any) -> Any:
    try:
        result = normalize_tool_result(value)
    except Exception:
        raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid") from None
    if isinstance(result, str):
        try:
            return json.loads(result)
        except (TypeError, json.JSONDecodeError):
            return result
    return result


def _search_ids(value: Any) -> tuple[str, ...]:
    """Accept only the package's documented search text or synthetic JSON DTO."""

    if isinstance(value, str):
        if value == "":
            return ()
        if not value.endswith("\n") or value.endswith("\n\n"):
            raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
        rows = value[:-1].split("\n\n")
        values: list[str] = []
        for row in rows:
            match = re.fullmatch(
                r"ID: ([A-Za-z0-9_-]{1,256})\nSubject: [^\r\n]*\nFrom: [^\r\n]*\nDate: [^\r\n]+",
                row,
            )
            if match is None:
                raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
            values.append(match.group(1))
        return tuple(dict.fromkeys(values))
    if not isinstance(value, dict):
        raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
    rows = value.get("emails", value.get("messages", value.get("results")))
    if not isinstance(rows, list):
        raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
    values = []
    for row in rows:
        if not isinstance(row, dict):
            raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
        candidate = row.get("id", row.get("messageId", row.get("message_id")))
        values.append(_identifier(candidate, code="gmail_reply_protocol_invalid"))
    return tuple(dict.fromkeys(values))


def _addresses(value: object, *, required: bool = False) -> tuple[str, ...]:
    """Parse a provider header but preserve no display-name or header content."""

    if value in (None, "") or value == []:
        if required:
            raise GmailEnvironmentAdapterError("gmail_reply_thread_participants_invalid")
        return ()
    entries = value if isinstance(value, list) else [value]
    if not isinstance(entries, list) or not entries or any(not isinstance(item, str) or "\r" in item or "\n" in item for item in entries):
        raise GmailEnvironmentAdapterError("gmail_reply_thread_participants_invalid")
    parsed = getaddresses(entries)
    if not parsed or any(not address for _, address in parsed):
        raise GmailEnvironmentAdapterError("gmail_reply_thread_participants_invalid")
    values: list[str] = []
    for _, address in parsed:
        try:
            candidate = canonical_recipient_email(address)
        except GmailEnvironmentAdapterError:
            raise GmailEnvironmentAdapterError("gmail_reply_thread_participants_invalid") from None
        values.append(candidate)
    return tuple(values)


def _thread_has_authorized_recipient_target(
    value: Any, *, thread_id: str, message_id: str, recipient_email: str, marker: str | None = None
) -> None:
    if not isinstance(value, dict) or value.get("threadId", value.get("thread_id")) != thread_id:
        raise GmailEnvironmentAdapterError("gmail_reply_thread_mismatch")
    messages = value.get("messages")
    if not isinstance(messages, list) or not messages:
        raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
    exact_found = False
    participants: set[str] = set()
    for message in messages:
        if not isinstance(message, dict):
            raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
        observed_thread = message.get("threadId", message.get("thread_id"))
        observed_message = message.get("messageId", message.get("message_id", message.get("id")))
        _identifier(observed_thread, code="gmail_reply_protocol_invalid")
        _identifier(observed_message, code="gmail_reply_protocol_invalid")
        if observed_thread != thread_id:
            raise GmailEnvironmentAdapterError("gmail_reply_thread_mismatch")
        sender = _addresses(message.get("from"), required=observed_message == message_id)
        recipients = _addresses(message.get("to"), required=observed_message == message_id)
        if _addresses(message.get("cc")) or _addresses(message.get("bcc")):
            raise GmailEnvironmentAdapterError("gmail_reply_thread_participants_invalid")
        participants.update(sender); participants.update(recipients)
        if observed_message == message_id:
            exact_found = True
            if marker is not None:
                # Search alone is not proof: require the exact marker in an
                # provider representation of this exact message.  The Gmail
                # MCP may normalize the sent HTML into ``body`` on reads.
                bodies = (
                    message.get("htmlBody"), message.get("html_body"),
                    message.get("body"),
                )
                if not any(isinstance(body, str) and marker in body for body in bodies):
                    raise GmailEnvironmentAdapterError("gmail_reply_idempotency_unverified")
    if not exact_found:
        raise GmailEnvironmentAdapterError("gmail_reply_target_not_in_thread")
    # The fixed recipient is allowed to converse only with one consistent
    # mailbox counterpart.  The provider login account is not inspected or
    # assumed to equal the configured recipient.
    if recipient_email not in participants or len(participants) > 2:
        raise GmailEnvironmentAdapterError("gmail_reply_thread_participants_invalid")


def _sent_message(value: Any) -> str:
    if isinstance(value, str):
        match = re.fullmatch(
            r"Email sent successfully with ID: ([A-Za-z0-9_-]{1,256})",
            value,
        )
        if match is None:
            raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
        return match.group(1)
    if not isinstance(value, dict):
        raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
    return _identifier(value.get("id", value.get("messageId", value.get("message_id"))), code="gmail_reply_protocol_invalid")


def _label_id(value: Any) -> str:
    if isinstance(value, str):
        match = re.fullmatch(
            r"Successfully (?:created|retrieved|found existing) label:\nID: ([A-Za-z0-9_-]{1,256})\nName: TrainLab\nType: [A-Za-z_]+",
            value,
        )
        if match is None:
            raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
        return match.group(1)
    if not isinstance(value, dict):
        raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
    return _identifier(value.get("id", value.get("labelId", value.get("label_id"))), code="gmail_reply_protocol_invalid")


def _modified(value: Any, *, message_id: str) -> None:
    if isinstance(value, str):
        if value != f"Email {message_id} labels updated successfully":
            raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
        return
    if not isinstance(value, dict) or value.get("id", value.get("messageId", value.get("message_id"))) != message_id:
        raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")


class GmailEnvironmentRecipientAdapter:
    """Fixed-recipient, no-attachment adapter around the current ``gmail`` MCP."""

    def __init__(
        self,
        canonical_recipient: str,
        *,
        inspector: Callable[[], GmailEnvironmentStatus] = inspect_gmail_environment,
        client_factory: Callable[..., GmailEnvironmentClient] = StdioMCPClient,
        timeout_seconds: int = 60,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float], float] = lambda _delay: 0.0,
        identity_state_root: Path | None = None,
    ) -> None:
        self._recipient = canonical_recipient_email(canonical_recipient)
        if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= 300:
            raise GmailEnvironmentAdapterError("gmail_reply_timeout_invalid")
        self._inspector = inspector
        self._client_factory = client_factory
        self._timeout_seconds = timeout_seconds
        self._sleep = sleep
        self._jitter = jitter
        self._identity_state_root = identity_state_root
        self._verified_identity_id: int | None = None

    @property
    def verified_identity_id(self) -> int | None:
        """The pre-provisioned Foundation identity; no MCP identity is read."""
        return self._verified_identity_id

    def prepare(self, connection: sqlite3.Connection, subject_id: int) -> GmailIdentity:
        """Bind the configured recipient to exactly one local verified identity.

        This intentionally does not call ``get_self`` (or any equivalent MCP
        endpoint).  The deployment's fixed recipient is its only authority;
        the local identity row is merely the relational foreign-key anchor
        required by Foundation's mail tables.
        """
        if subject_id != _MAIL_SUBJECT_ID:
            raise GmailEnvironmentAdapterError("gmail_reply_subject_invalid")
        if self._identity_state_root is None:
            raise GmailEnvironmentAdapterError("gmail_reply_identity_unavailable")
        self._verified_identity_id = self._provision_identity(connection)
        return GmailIdentity(self._recipient)

    def _provision_identity(self, connection: sqlite3.Connection) -> int:
        """Atomically register the configured recipient as Foundation subject 1.

        The configured address is used only to derive an HMAC in process.  It
        is never persisted in plaintext or included in an error value.
        """
        if connection.in_transaction:
            raise GmailEnvironmentAdapterError("gmail_reply_identity_unavailable")
        try:
            digest = hmac.new(self._identity_key(), self._recipient.encode("ascii"), hashlib.sha256).hexdigest()
            connection.execute("BEGIN IMMEDIATE")
            subject = connection.execute("SELECT id FROM data_subjects WHERE id=?", (_MAIL_SUBJECT_ID,)).fetchone()
            if subject is None:
                raise GmailEnvironmentAdapterError("gmail_reply_identity_unavailable")
            conflicting = connection.execute(
                "SELECT subject_id FROM subject_identities WHERE provider='gmail' "
                "AND identity_kind='email' AND identity_hmac=?",
                (digest,),
            ).fetchone()
            if conflicting is not None and conflicting[0] != _MAIL_SUBJECT_ID:
                raise GmailEnvironmentAdapterError("gmail_reply_identity_conflict")
            other = connection.execute(
                "SELECT id FROM subject_identities WHERE subject_id=? AND provider='gmail' "
                "AND identity_kind='email' AND identity_hmac<>?",
                (_MAIL_SUBJECT_ID, digest),
            ).fetchone()
            if other is not None:
                raise GmailEnvironmentAdapterError("gmail_reply_identity_conflict")
            now = utc_now()
            connection.execute(
                "INSERT INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) "
                "VALUES(?,'gmail','email',?,1,?,?) "
                "ON CONFLICT(provider,identity_kind,identity_hmac) DO UPDATE SET "
                "is_verified=1,last_seen_at_utc=excluded.last_seen_at_utc",
                (_MAIL_SUBJECT_ID, digest, now, now),
            )
            row = connection.execute(
                "SELECT id FROM subject_identities WHERE subject_id=? AND provider='gmail' "
                "AND identity_kind='email' AND identity_hmac=? AND is_verified=1",
                (_MAIL_SUBJECT_ID, digest),
            ).fetchone()
            if row is None or not isinstance(row[0], int):
                raise GmailEnvironmentAdapterError("gmail_reply_identity_unavailable")
            connection.commit()
            return int(row[0])
        except GmailEnvironmentAdapterError:
            if connection.in_transaction:
                connection.rollback()
            raise
        except (OSError, sqlite3.Error, UnicodeError):
            if connection.in_transaction:
                connection.rollback()
            raise GmailEnvironmentAdapterError("gmail_reply_identity_unavailable") from None

    def _identity_key(self) -> bytes:
        root = self._identity_state_root
        if root is None:
            raise GmailEnvironmentAdapterError("gmail_reply_identity_unavailable")
        try:
            secrets_dir = root / "secrets"
            try:
                metadata = os.lstat(secrets_dir)
            except FileNotFoundError:
                try:
                    secrets_dir.mkdir(mode=0o700, parents=False)
                except FileExistsError:
                    # Another one-shot invocation created the directory after
                    # our lstat. Re-validate that winner instead of failing a
                    # safe concurrent first start.
                    pass
                metadata = os.lstat(secrets_dir)
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                raise OSError("secrets_directory_invalid")
            os.chmod(secrets_dir, 0o700)
            key_path = secrets_dir / _IDENTITY_KEY_FILENAME
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(key_path, flags)
            except FileNotFoundError:
                temporary = secrets_dir / f".{_IDENTITY_KEY_FILENAME}.{secrets.token_hex(16)}.tmp"
                temporary_created = False
                try:
                    descriptor = os.open(
                        temporary,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                        0o600,
                    )
                    temporary_created = True
                    try:
                        key = os.urandom(_IDENTITY_KEY_BYTES)
                        offset = 0
                        while offset < len(key):
                            written = os.write(descriptor, key[offset:])
                            if written <= 0:
                                raise OSError("identity_key_write_failed")
                            offset += written
                        os.fsync(descriptor)
                        os.fchmod(descriptor, 0o600)
                    finally:
                        os.close(descriptor)
                    try:
                        os.link(temporary, key_path, follow_symlinks=False)
                    except FileExistsError:
                        pass
                    finally:
                        os.unlink(temporary)
                        temporary_created = False
                    descriptor = os.open(key_path, flags)
                finally:
                    if temporary_created:
                        try:
                            os.unlink(temporary)
                        except OSError:
                            pass
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise OSError("identity_key_invalid")
                os.fchmod(descriptor, 0o600)
                key = os.read(descriptor, _IDENTITY_KEY_BYTES + 1)
                if len(key) != _IDENTITY_KEY_BYTES:
                    raise OSError("identity_key_invalid")
                return key
            finally:
                os.close(descriptor)
        except OSError:
            raise GmailEnvironmentAdapterError("gmail_reply_identity_unavailable") from None

    def close(self) -> None:
        self._verified_identity_id = None

    def search_trainlab_window(
        self, *, start_date: date | datetime, end_date: date | datetime, max_results: int = 100
    ) -> tuple[dict[str, Any], ...]:
        if not isinstance(max_results, int) or isinstance(max_results, bool) or not 1 <= max_results <= 100:
            raise GmailEnvironmentAdapterError("gmail_reply_search_invalid")
        start = start_date.date() if isinstance(start_date, datetime) else start_date
        end = end_date.date() if isinstance(end_date, datetime) else end_date
        if not isinstance(start, date) or not isinstance(end, date) or start > end:
            raise GmailEnvironmentAdapterError("gmail_reply_search_invalid")
        client = self._open_client()
        try:
            if "read_email" not in self._available_tools(client):
                raise GmailEnvironmentAdapterError("gmail_reply_capability_mismatch")
            value = _result(self._read_call(client, "search_emails", {
                "query": f"label:TrainLab after:{start.isoformat()} before:{end.isoformat()}",
                "maxResults": max_results,
            }))
            return self._thread_search_results(client, value)
        except GmailEnvironmentAdapterError:
            raise
        except Exception as error:
            raise self._translate(error) from None
        finally:
            self._close(client)

    def read_thread_evidence(self, provider_thread_id: str) -> GmailThreadEvidence:
        thread_id = _identifier(provider_thread_id, code="gmail_reply_thread_id_invalid")
        client = self._open_client()
        try:
            raw = _result(self._read_call(client, "get_thread", {"threadId": thread_id, "format": "full"}))
            if not isinstance(raw, dict):
                raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
            canonical_raw = self._canonical_raw_thread(raw, expected_thread_id=thread_id)
            return GmailThreadEvidence(self._normalized_thread(canonical_raw, expected_thread_id=thread_id), canonical_raw)
        except GmailEnvironmentAdapterError:
            raise
        except Exception as error:
            raise self._translate(error) from None
        finally:
            self._close(client)

    def search_run_id(self, *, run_id: str, max_results: int = 10) -> tuple[dict[str, Any], ...]:
        marker = _marker(run_id)
        expected_thread = self._thread_from_run_id(run_id)
        if not isinstance(max_results, int) or isinstance(max_results, bool) or not 1 <= max_results <= 10:
            raise GmailEnvironmentAdapterError("gmail_reply_search_invalid")
        client = self._open_client()
        try:
            matches = _search_ids(
                _result(self._read_call(client, "search_emails", {"query": f'in:sent "{marker}"', "maxResults": max_results}))
            )
            if len(matches) > 1:
                raise GmailEnvironmentAdapterError("gmail_reply_idempotency_ambiguous")
            if not matches:
                return ()
            self._validate_thread(client, thread_id=expected_thread, message_id=matches[0], marker=marker)
            return ({"message_id": matches[0], "thread_id": expected_thread},)
        except GmailEnvironmentAdapterError:
            raise
        except Exception as error:
            raise self._translate(error) from None
        finally:
            self._close(client)

    def send_html_recipient(
        self,
        *,
        run_id: str,
        subject: str,
        plain_text: str,
        html: str,
        thread_id: str | None = None,
        in_reply_to_provider_message_id: str | None = None,
    ) -> SendReceipt:
        message_id = _identifier(in_reply_to_provider_message_id, code="gmail_reply_message_id_invalid")
        exact_thread = _identifier(thread_id, code="gmail_reply_thread_id_invalid")
        title = _text(subject, code="gmail_reply_subject_invalid", maximum=998)
        if "\n" in title:
            raise GmailEnvironmentAdapterError("gmail_reply_subject_invalid")
        plain = _text(plain_text, code="gmail_reply_body_invalid")
        rendered_html = _text(html, code="gmail_reply_body_invalid")
        marker = _marker(run_id)
        if marker in plain or marker in rendered_html:
            raise GmailEnvironmentAdapterError("gmail_reply_idempotency_invalid")
        # The marker remains searchable in the sent HTML but is never exposed
        # in the subject or multipart plain-text alternative.
        marked_plain = plain
        marked_html = (
            f'{rendered_html}<span style="display:none!important;max-height:0;'
            f'overflow:hidden;opacity:0;mso-hide:all;">{marker}</span>'
        )
        client = self._open_client()
        try:
            matches = _search_ids(
                _result(self._read_call(client, "search_emails", {"query": f'in:sent "{marker}"', "maxResults": 2}))
            )
            if len(matches) > 1:
                raise GmailEnvironmentAdapterError("gmail_reply_idempotency_ambiguous")
            if len(matches) == 1:
                self._validate_thread(client, thread_id=exact_thread, message_id=matches[0], marker=marker)
                return SendReceipt(matches[0], exact_thread, True)
            self._validate_thread(client, thread_id=exact_thread, message_id=message_id)
            sent_id = _sent_message(_result(client.call_tool("send_email", {
                "to": [self._recipient],
                "subject": title,
                "body": marked_plain,
                "htmlBody": marked_html,
                "mimeType": "multipart/alternative",
                "threadId": exact_thread,
                "inReplyTo": message_id,
            })))
            return SendReceipt(sent_id, exact_thread, False)
        except GmailEnvironmentAdapterError:
            raise
        except Exception as error:
            raise self._translate(error) from None
        finally:
            self._close(client)

    def apply_trainlab_label(self, *, message_id: str | None, thread_id: str | None) -> None:
        exact_message = _identifier(message_id, code="gmail_reply_message_id_invalid")
        _identifier(thread_id, code="gmail_reply_thread_id_invalid")
        client = self._open_client()
        try:
            label = _label_id(_result(client.call_tool("get_or_create_label", {"name": "TrainLab"})))
            _modified(_result(client.call_tool("modify_email", {"messageId": exact_message, "addLabelIds": [label]})), message_id=exact_message)
        except GmailEnvironmentAdapterError:
            raise
        except Exception as error:
            raise self._translate(error) from None
        finally:
            self._close(client)

    def _open_client(self) -> GmailEnvironmentClient:
        status = self._inspector()
        if not isinstance(status, GmailEnvironmentStatus) or not status.available:
            if isinstance(status, GmailEnvironmentStatus) and status.code in {"gmail_mcp_not_configured", "gmail_mcp_binding_invalid"}:
                raise GmailEnvironmentAdapterError(status.code)
            raise GmailEnvironmentAdapterError("gmail_reply_binding_invalid")
        client: GmailEnvironmentClient | None = None
        try:
            # The validator has already established that this is the enabled,
            # package-exact current `gmail` binding.  Never replace it with a
            # host-specific or hard-coded executable.
            client = self._client_factory(
                status.command,
                list(status.args),
                timeout=self._timeout_seconds,
                stdout_preamble_lines=(GMAIL_MCP_OAUTH_COPY_NOTICE,),
            )
            if not _REQUIRED_TOOLS.issubset(self._available_tools(client)):
                self._close(client)
                raise GmailEnvironmentAdapterError("gmail_reply_capability_mismatch")
            return client
        except GmailEnvironmentAdapterError:
            self._close(client)
            raise
        except Exception as error:
            self._close(client)
            raise self._translate(error) from None

    def _validate_thread(self, client: GmailEnvironmentClient, *, thread_id: str, message_id: str, marker: str | None = None) -> None:
        thread = _result(self._read_call(client, "get_thread", {"threadId": thread_id, "format": "full"}))
        _thread_has_authorized_recipient_target(thread, thread_id=thread_id, message_id=message_id, recipient_email=self._recipient, marker=marker)

    def _thread_search_results(self, client: GmailEnvironmentClient, value: Any) -> tuple[dict[str, Any], ...]:
        rows = value.get("emails", value.get("messages", value.get("results"))) if isinstance(value, dict) else None
        if rows is None:
            ids = _search_ids(value)
            rows = [{"id": item} for item in ids]
        if not isinstance(rows, list):
            raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
        output: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
            message = _identifier(row.get("id", row.get("messageId", row.get("message_id"))), code="gmail_reply_protocol_invalid")
            candidate_thread = row.get("threadId", row.get("thread_id"))
            if candidate_thread is None:
                detail = _result(self._read_call(client, "read_email", {"messageId": message}))
                if isinstance(detail, dict):
                    candidate_thread = detail.get("threadId", detail.get("thread_id"))
                elif isinstance(detail, str):
                    match = re.search(r"^Thread ID: ([A-Za-z0-9_-]{1,256})$", detail, re.MULTILINE)
                    candidate_thread = None if match is None else match.group(1)
            thread = _identifier(candidate_thread, code="gmail_reply_protocol_invalid")
            output.append({"thread_id": thread, "message_id": message})
        return tuple(output)

    @staticmethod
    def _normalized_thread(raw: dict[str, Any], *, expected_thread_id: str) -> GmailThread:
        thread_id = _identifier(raw.get("threadId", raw.get("thread_id")), code="gmail_reply_protocol_invalid")
        if thread_id != expected_thread_id or not isinstance(raw.get("messages"), list):
            raise GmailEnvironmentAdapterError("gmail_reply_thread_mismatch")
        messages: list[GmailMessage] = []
        for row in raw["messages"]:
            if not isinstance(row, dict):
                raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
            message_id = _identifier(row.get("messageId", row.get("message_id", row.get("id"))), code="gmail_reply_protocol_invalid")
            row_thread = _identifier(row.get("threadId", row.get("thread_id")), code="gmail_reply_protocol_invalid")
            if row_thread != thread_id:
                raise GmailEnvironmentAdapterError("gmail_reply_thread_mismatch")
            received = row.get("internal_date_utc", row.get("received_at_utc"))
            if received is not None and not isinstance(received, str):
                raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
            sender = row.get("from")
            recipients = row.get("to", ())
            recipient_values = (recipients,) if isinstance(recipients, str) else tuple(recipients) if isinstance(recipients, list) else ()
            if sender is not None and not isinstance(sender, str) or any(not isinstance(item, str) for item in recipient_values):
                raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
            body = row.get("plain_text", row.get("body_text", ""))
            if not isinstance(body, str):
                raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
            labels = row.get("labelIds", row.get("label_ids", ()))
            label_values = tuple(labels) if isinstance(labels, list) and all(isinstance(item, str) for item in labels) else ()
            messages.append(GmailMessage(
                message_id, row_thread, received, sender, recipient_values,
                row.get("subject") if isinstance(row.get("subject"), str) else None,
                row.get("headers", {}).get("message_id") if isinstance(row.get("headers", {}).get("message_id"), str) else None,
                row.get("headers", {}).get("in_reply_to") if isinstance(row.get("headers", {}).get("in_reply_to"), str) else None,
                tuple(row.get("headers", {}).get("references", ())) if isinstance(row.get("headers", {}).get("references", ()), list) else (),
                row.get("headers", {}).get("x_trainlab_run_id") if isinstance(row.get("headers", {}).get("x_trainlab_run_id"), str) else None,
                label_values, body, bool(row.get("has_html")), (),
            ))
        return GmailThread(thread_id, tuple(messages))

    def _canonical_raw_thread(self, raw: dict[str, Any], *, expected_thread_id: str) -> dict[str, Any]:
        """Make the archive DTO satisfy poll's canonical/raw correspondence.

        ``provider_raw`` is retained exactly as returned, while the sibling
        fields are the narrow projection consumed by the mail poller.
        """
        thread_id = _identifier(raw.get("threadId", raw.get("thread_id")), code="gmail_reply_protocol_invalid")
        rows = raw.get("messages")
        if thread_id != expected_thread_id or not isinstance(rows, list) or not rows:
            raise GmailEnvironmentAdapterError("gmail_reply_thread_mismatch")
        output: list[dict[str, Any]] = []
        participants: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
            message_id = _identifier(row.get("messageId", row.get("message_id", row.get("id"))), code="gmail_reply_protocol_invalid")
            row_thread = _identifier(row.get("threadId", row.get("thread_id")), code="gmail_reply_protocol_invalid")
            received = row.get("internal_date_utc", row.get("received_at_utc", row.get("receivedAt", row.get("date"))))
            if row_thread != thread_id or not isinstance(received, str):
                raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
            try:
                parsed = datetime.fromisoformat(received.replace("Z", "+00:00"))
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(received)
                except (TypeError, ValueError):
                    parsed = None
            canonical_time = (
                parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                if parsed is not None and parsed.tzinfo is not None
                else ""
            )
            if not canonical_time:
                raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
            sender = row.get("from")
            to = row.get("to", [])
            recipients = [to] if isinstance(to, str) else to
            labels = row.get("label_ids", row.get("labelIds", []))
            headers = row.get("headers", {})
            if (sender is not None and not isinstance(sender, str)) or not isinstance(recipients, list) or any(not isinstance(v, str) for v in recipients) or not isinstance(labels, list) or any(not isinstance(v, str) or not v for v in labels) or not isinstance(headers, dict):
                raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
            if _addresses(row.get("cc")) or _addresses(row.get("bcc")):
                raise GmailEnvironmentAdapterError("gmail_reply_thread_participants_invalid")
            participants.update(_addresses(sender))
            participants.update(_addresses(recipients))
            message_header = headers.get("message_id", row.get("messageIdHeader"))
            in_reply_to = headers.get("in_reply_to", row.get("inReplyTo"))
            references = headers.get("references", row.get("references", []))
            run_id = headers.get("x_trainlab_run_id", row.get("trainlabRunId"))
            if ((message_header is not None and not isinstance(message_header, str))
                    or (in_reply_to is not None and not isinstance(in_reply_to, str))
                    or not isinstance(references, list) or any(not isinstance(v, str) for v in references)
                    or (run_id is not None and not isinstance(run_id, str))
                    or not isinstance(row.get("attachments", []), list)
                    or any(not isinstance(v, dict) for v in row.get("attachments", []))):
                raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
            body = row.get("plain_text", row.get("body_text", row.get("body", "")))
            if not isinstance(body, str):
                raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
            output.append({
                "message_id": message_id, "thread_id": thread_id,
                "internal_date_utc": canonical_time, "from": sender, "to": recipients,
                "subject": row.get("subject") if isinstance(row.get("subject"), str) else None,
                "headers": {
                    "message_id": message_header, "in_reply_to": in_reply_to,
                    "references": references, "x_trainlab_run_id": run_id,
                },
                "label_ids": labels, "plain_text": body, "has_html": bool(row.get("has_html", row.get("htmlBody"))),
                "attachments": row.get("attachments", []), "provider_raw": row,
            })
        if self._recipient not in participants or len(participants) > 2:
            raise GmailEnvironmentAdapterError("gmail_reply_thread_participants_invalid")
        labels = raw.get("label_ids", raw.get("labelIds", []))
        if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
            raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
        return {"thread_id": thread_id, "label_ids": labels, "messages": output, "provider_raw": raw}

    def _read_call(self, client: GmailEnvironmentClient, name: str, arguments: dict[str, Any]) -> Any:
        """At most five read-only attempts; never use this for mutation."""
        for attempt in range(5):
            try:
                return client.call_tool(name, arguments)
            except Exception as error:
                translated = self._translate(error)
                retryable = translated.code in {"gmail_reply_transport_error", "gmail_reply_timeout", "gmail_reply_rate_limited", "gmail_reply_provider_error"}
                wait = translated.retry_at_seconds
                if not retryable or attempt == 4 or (translated.code == "gmail_reply_rate_limited" and (wait is None or wait > 120)):
                    raise translated from None
                if translated.code == "gmail_reply_rate_limited" and wait:
                    self._sleep(float(wait))
                elif translated.code != "gmail_reply_rate_limited":
                    self._sleep(float(2 ** attempt) + max(0.0, float(self._jitter(float(2 ** attempt)))))
        raise GmailEnvironmentAdapterError("gmail_reply_transport_error")

    @staticmethod
    def _thread_from_run_id(run_id: str) -> str:
        match = re.fullmatch(r"mail:response:[1-9][0-9]*:([A-Za-z0-9_-]{1,256})", run_id)
        if match is None:
            raise GmailEnvironmentAdapterError("gmail_reply_idempotency_invalid")
        return match.group(1)

    @staticmethod
    def _close(client: GmailEnvironmentClient | None) -> None:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    @staticmethod
    def _available_tools(client: GmailEnvironmentClient) -> frozenset[str]:
        try:
            values = client.list_tools()
        except Exception as error:
            raise GmailEnvironmentRecipientAdapter._translate(error) from None
        if not isinstance(values, list) or any(not isinstance(item, dict) or not isinstance(item.get("name"), str) for item in values):
            raise GmailEnvironmentAdapterError("gmail_reply_protocol_invalid")
        return frozenset(item["name"] for item in values)

    @staticmethod
    def _translate(error: Exception) -> GmailEnvironmentAdapterError:
        if isinstance(error, TimeoutError):
            return GmailEnvironmentAdapterError("gmail_reply_timeout")
        if isinstance(error, MCPResponseError):
            if error.status_code == 401:
                return GmailEnvironmentAdapterError("gmail_reply_auth_required")
            if error.status_code == 403:
                return GmailEnvironmentAdapterError("gmail_reply_forbidden")
            if error.status_code == 429:
                return GmailEnvironmentAdapterError("gmail_reply_rate_limited", retry_at_seconds=error.retry_after_seconds)
            if error.status_code is not None:
                return GmailEnvironmentAdapterError("gmail_reply_provider_error")
            return GmailEnvironmentAdapterError("gmail_reply_protocol_error")
        return GmailEnvironmentAdapterError("gmail_reply_transport_error")


def create_environment_adapter(
    foundation: object, *, recipient_address: str
) -> GmailEnvironmentRecipientAdapter:
    """Runtime factory used by the Mail composition root.

    ``recipient_address`` is the locally configured authorized recipient, not a
    provider identity lookup.  The current environment's ``gmail`` binding is
    validated lazily on the first fixed tool call.
    """
    state_root = getattr(foundation, "state_root", None)
    if not isinstance(state_root, Path):
        raise GmailEnvironmentAdapterError("gmail_reply_identity_unavailable")
    return GmailEnvironmentRecipientAdapter(recipient_address, identity_state_root=state_root)
