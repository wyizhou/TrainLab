"""Restricted Gmail MCP boundary for TrainLab's fourth layer.

The adapter accepts only a verified stdio MCP transport. It never exposes a
generic tool call, Gmail HTTP API, recipient, label, or provider query surface.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import yaml
from jsonschema import Draft202012Validator

from ..mcp import MCPResponseError, StdioMCPClient, dotted_get, format_template, normalize_tool_result

_TOOLS = {
    "get_self": "get_self",
    "search": "search_messages",
    "read_thread": "read_thread",
    "send_html_self": "send_html_self",
    "create_or_apply_label": "create_or_apply_label",
}
_READ_ONLY = frozenset({"get_self", "search", "read_thread"})
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_MAX_SEARCH_RESULTS = 100
_MAX_DISCOVERY_WINDOW_DAYS = 7
_ARGUMENT_KEYS = {
    "get_self": frozenset(),
    "search": frozenset({"query", "max_results"}),
    "read_thread": frozenset({"thread_id"}),
    "send_html_self": frozenset({"run_id", "subject", "plain_text", "html", "thread_id"}),
    "create_or_apply_label": frozenset({"label", "message_id", "thread_id"}),
}


class GmailAdapterError(RuntimeError):
    def __init__(self, code: str, *, retry_at_seconds: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retry_at_seconds = retry_at_seconds


class MCPCallError(RuntimeError):
    """Typed transport failure; never put raw provider text into a receipt."""

    def __init__(self, status_code: int | None = None, *, retry_after_seconds: int | None = None, kind: str = "transport") -> None:
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        self.kind = kind
        super().__init__(kind)


class RestrictedMCPTransport(Protocol):
    def list_tools(self) -> list[dict[str, Any]]: ...
    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...
    def close(self) -> None: ...


class RefreshableMCPTransport(RestrictedMCPTransport, Protocol):
    def refresh_auth(self) -> None: ...


@dataclass(frozen=True)
class GmailIdentity:
    email: str


@dataclass(frozen=True)
class GmailMessage:
    provider_message_id: str
    provider_thread_id: str
    received_at_utc: str | None
    sender: str | None
    recipients: tuple[str, ...]
    subject: str | None
    message_id_header: str | None
    in_reply_to: str | None
    references: tuple[str, ...]
    trainlab_run_id: str | None
    label_ids: tuple[str, ...]
    body_text: str
    has_html: bool
    attachments: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class GmailThread:
    provider_thread_id: str
    messages: tuple[GmailMessage, ...]


@dataclass(frozen=True)
class GmailThreadEvidence:
    """Normalized thread plus the exact fixed-tool MCP result for raw archive."""

    thread: GmailThread
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class SendReceipt:
    provider_message_id: str
    provider_thread_id: str
    already_sent: bool


@dataclass(frozen=True)
class GmailCapabilityProbe:
    """Persistable, non-secret evidence that the restricted boundary was probed."""

    mapping_schema_version: int
    config_path_sha256: str
    mapping_valid: bool
    credential_paths_checked: bool
    credential_permissions_ok: bool
    oauth_file_mode: int
    oauth_directory_mode: int
    token_file_mode: int
    token_directory_mode: int
    strict_tool_surface: bool
    authenticated_self_verified: bool


@dataclass(frozen=True)
class GmailMCPConfig:
    mapping: dict[str, Any]
    config_path: Path

    @classmethod
    def load(cls, config_path: Path, schema_path: Path) -> "GmailMCPConfig":
        value = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        schema = __import__("json").loads(schema_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or list(Draft202012Validator(schema).iter_errors(value)):
            raise GmailAdapterError("gmail_mapping_invalid")
        instance = cls(value, config_path)
        instance.validate()
        return instance

    def validate(self) -> None:
        value = self.mapping
        if not value.get("configured") or value.get("server_name") != "gmail" or value.get("provider") != "trainlab_gmail_v1":
            raise GmailAdapterError("gmail_mapping_invalid")
        transport = value.get("transport")
        if not isinstance(transport, dict) or transport.get("type") != "stdio" or not isinstance(transport.get("command"), str) or not isinstance(transport.get("args"), list) or transport.get("env") != {}:
            raise GmailAdapterError("gmail_mapping_invalid")
        requirements = value.get("requirements")
        if not isinstance(requirements, dict) or requirements.get("authenticated_self_only") is not True or requirements.get("label") != "TrainLab":
            raise GmailAdapterError("gmail_mapping_invalid")
        capabilities = value.get("capabilities")
        if not isinstance(capabilities, dict) or set(capabilities) != set(_TOOLS):
            raise GmailAdapterError("gmail_tool_mapping_invalid")
        for capability, expected_tool in _TOOLS.items():
            item = capabilities[capability]
            if not isinstance(item, dict) or item.get("tool") != expected_tool or not isinstance(item.get("arguments"), dict):
                raise GmailAdapterError("gmail_tool_mapping_invalid")
            if set(item["arguments"]) != _ARGUMENT_KEYS[capability]:
                raise GmailAdapterError("gmail_tool_mapping_invalid")
        if (
            capabilities["get_self"]["arguments"] != {}
            or capabilities["search"]["arguments"] != {"query": "{query}", "max_results": "{max_results}"}
            or capabilities["create_or_apply_label"]["arguments"].get("label") != "{label}"
        ):
            raise GmailAdapterError("gmail_tool_mapping_invalid")

    def credential_permission_modes(self) -> tuple[int, int, int, int]:
        """Stat credential paths only; this method never reads credential contents."""

        credentials = self.mapping["credentials"]
        modes: list[tuple[int, int]] = []
        for raw in (credentials["oauth_client_path"], credentials["token_path"]):
            path = Path(os.path.expandvars(os.path.expanduser(str(raw)))).absolute()
            try:
                # Check every extant ancestor without resolving symlinks: resolving
                # first would hide an escape through a symlinked credentials root.
                if any(ancestor.is_symlink() for ancestor in (path, *path.parents)):
                    raise GmailAdapterError("gmail_credential_path_invalid")
                if not path.is_file() or not path.parent.is_dir():
                    raise GmailAdapterError("gmail_credential_path_invalid")
                mode = path.stat().st_mode & 0o777
                parent_mode = path.parent.stat().st_mode & 0o777
            except GmailAdapterError:
                raise
            except OSError:
                raise GmailAdapterError("gmail_credential_path_invalid") from None
            if mode & 0o077 or parent_mode & 0o077:
                raise GmailAdapterError("gmail_credential_permissions_invalid")
            modes.append((mode, parent_mode))
        return modes[0][0], modes[0][1], modes[1][0], modes[1][1]


class StdioMailTransport:
    """Lazy wrapper so validation occurs before a stdio MCP process is launched."""

    def __init__(self, config: GmailMCPConfig, *, client_factory: Callable[..., Any] = StdioMCPClient) -> None:
        transport = config.mapping["transport"]
        try:
            self._client = client_factory(str(transport["command"]), [str(item) for item in transport["args"]], env={}, timeout=int(transport["timeout_seconds"]))
        except Exception as exc:
            raise self._translate(exc) from None

    def list_tools(self) -> list[dict[str, Any]]:
        try:
            return self._client.list_tools()
        except Exception as exc:
            raise self._translate(exc) from None

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        try:
            return self._client.call_tool(name, arguments)
        except Exception as exc:
            raise self._translate(exc) from None

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _translate(exc: Exception) -> MCPCallError:
        if isinstance(exc, MCPCallError):
            return exc
        if isinstance(exc, MCPResponseError):
            return MCPCallError(exc.status_code, retry_after_seconds=exc.retry_after_seconds, kind=exc.kind)
        if isinstance(exc, TimeoutError):
            return MCPCallError(kind="timeout")
        return MCPCallError(kind="transport")


class GmailMCPAdapter:
    def __init__(self, config: GmailMCPConfig, *, transport_factory: Callable[[GmailMCPConfig], RestrictedMCPTransport] = StdioMailTransport, identity_hmac: Callable[[str], str], sleep: Callable[[float], None] = time.sleep, inline_retry_after_seconds: int = 5) -> None:
        self.config = config
        self._transport_factory = transport_factory
        self._identity_hmac = identity_hmac
        self._sleep = sleep
        self._inline_retry_after_seconds = inline_retry_after_seconds
        self._transport: RestrictedMCPTransport | None = None
        self._identity: GmailIdentity | None = None
        self._identity_id: int | None = None
        self._capability_probe: GmailCapabilityProbe | None = None

    @property
    def capability_probe(self) -> GmailCapabilityProbe | None:
        """Return only safe-to-persist probe metadata, never config paths or secrets."""

        return self._capability_probe

    @property
    def verified_identity_id(self) -> int | None:
        return self._identity_id

    @property
    def verified_identity(self) -> GmailIdentity | None:
        return self._identity

    def prepare(self, connection: sqlite3.Connection, subject_id: int) -> GmailIdentity:
        # A failed/repeated prepare must never inherit a prior identity, probe, or
        # child process. This also makes recovery instantiate a clean boundary.
        self.close()
        try:
            self.config.validate()
            oauth_mode, oauth_dir_mode, token_mode, token_dir_mode = self.config.credential_permission_modes()
            self._transport = self._transport_factory(self.config)
            available = {str(item.get("name")) for item in self._transport.list_tools() if item.get("name")}
            # Strict rejection (rather than ignoring extras) keeps the provider process
            # itself within the fixed least-privilege capability surface.
            if set(_TOOLS.values()) != available:
                raise GmailAdapterError("gmail_tools_unavailable")
            identity = self._get_self()
            expected = str(self.config.mapping["authenticated_self"]).strip().lower()
            actual_hmac = self._identity_hmac(identity.email)
            row = connection.execute("SELECT id FROM subject_identities WHERE subject_id=? AND provider='gmail' AND identity_kind='email' AND identity_hmac=? AND is_verified=1", (subject_id, actual_hmac)).fetchone()
            if not expected or identity.email != expected or row is None:
                raise GmailAdapterError("identity_mismatch")
            self._identity = identity
            self._identity_id = int(row[0])
            self._capability_probe = GmailCapabilityProbe(
                mapping_schema_version=int(self.config.mapping["schema_version"]),
                config_path_sha256=hashlib.sha256(str(self.config.config_path.resolve()).encode("utf-8")).hexdigest(),
                mapping_valid=True,
                credential_paths_checked=True,
                credential_permissions_ok=True,
                oauth_file_mode=oauth_mode,
                oauth_directory_mode=oauth_dir_mode,
                token_file_mode=token_mode,
                token_directory_mode=token_dir_mode,
                strict_tool_surface=True,
                authenticated_self_verified=True,
            )
            return identity
        except MCPCallError as error:
            self.close()
            self._raise_terminal_transport_error(error)
        except GmailAdapterError:
            self.close()
            raise
        except Exception:
            self.close()
            raise GmailAdapterError("gmail_transport_failed") from None

    def close(self) -> None:
        if self._transport is not None:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None
        self._identity = None
        self._identity_id = None
        self._capability_probe = None

    @staticmethod
    def _raise_terminal_transport_error(error: MCPCallError) -> None:
        if error.status_code == 401:
            raise GmailAdapterError("auth_required") from None
        if error.status_code == 403:
            raise GmailAdapterError("forbidden") from None
        if error.status_code == 429:
            raise GmailAdapterError("rate_limited", retry_at_seconds=error.retry_after_seconds) from None
        raise GmailAdapterError("gmail_transport_failed") from None

    def __enter__(self) -> "GmailMCPAdapter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def search_run_id(self, *, run_id: str, max_results: int = 10) -> tuple[dict[str, Any], ...]:
        """Search the exact idempotency marker; no caller-supplied Gmail query is accepted."""

        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise GmailAdapterError("gmail_search_intent_invalid")
        return self._search(query=f'subject:"{run_id}"', max_results=max_results)

    def search_trainlab_window(self, *, start_date: date | datetime, end_date: date | datetime, max_results: int = 100) -> tuple[dict[str, Any], ...]:
        """Discover only TrainLab-labelled mail in a small, explicit calendar window."""

        if not isinstance(start_date, date) or not isinstance(end_date, date):
            raise GmailAdapterError("gmail_search_intent_invalid")
        if isinstance(start_date, datetime) != isinstance(end_date, datetime):
            raise GmailAdapterError("gmail_search_intent_invalid")
        if isinstance(start_date, datetime):
            if start_date.tzinfo is None or end_date.tzinfo is None:
                raise GmailAdapterError("gmail_search_intent_invalid")
            start = start_date.astimezone(timezone.utc)
            end = end_date.astimezone(timezone.utc)
            seconds = int((end - start).total_seconds())
            if seconds < 1 or seconds > _MAX_DISCOVERY_WINDOW_DAYS * 86_400:
                raise GmailAdapterError("gmail_search_intent_invalid")
            query = f"label:TrainLab after:{int(start.timestamp())} before:{int(end.timestamp())}"
        else:
            days = (end_date - start_date).days
            if days < 1 or days > _MAX_DISCOVERY_WINDOW_DAYS:
                raise GmailAdapterError("gmail_search_intent_invalid")
            query = f"label:TrainLab after:{start_date:%Y/%m/%d} before:{end_date:%Y/%m/%d}"
        return self._search(query=query, max_results=max_results)

    def _search(self, *, query: str, max_results: int) -> tuple[dict[str, Any], ...]:
        if not isinstance(max_results, int) or isinstance(max_results, bool) or not 1 <= max_results <= _MAX_SEARCH_RESULTS:
            raise GmailAdapterError("gmail_search_intent_invalid")
        result = self._call("search", {"query": query, "max_results": max_results})
        matches = result.get("matches", []) if isinstance(result, dict) else result if isinstance(result, list) else []
        return tuple(item for item in matches if isinstance(item, dict))

    def read_thread(self, provider_thread_id: str) -> GmailThread:
        return self.read_thread_evidence(provider_thread_id).thread

    def read_thread_evidence(self, provider_thread_id: str) -> GmailThreadEvidence:
        if not isinstance(provider_thread_id, str) or not provider_thread_id:
            raise GmailAdapterError("gmail_thread_id_invalid")
        result = self._call("read_thread", {"thread_id": provider_thread_id})
        if not isinstance(result, dict):
            raise GmailAdapterError("gmail_thread_result_invalid")
        raw_messages = result.get("messages", [])
        if not isinstance(raw_messages, list):
            raise GmailAdapterError("gmail_thread_result_invalid")
        messages = tuple(self._message(item, provider_thread_id) for item in raw_messages if isinstance(item, dict))
        return GmailThreadEvidence(GmailThread(provider_thread_id, messages), result)

    def send_html_self(self, *, run_id: str, subject: str, plain_text: str, html: str, thread_id: str | None = None) -> SendReceipt:
        result = self._call("send_html_self", {"run_id": run_id, "subject": subject, "plain_text": plain_text, "html": html, "thread_id": thread_id or ""}, read_only=False)
        if not isinstance(result, dict) or not result.get("message_id") or not result.get("thread_id"):
            raise GmailAdapterError("gmail_send_result_invalid")
        return SendReceipt(str(result["message_id"]), str(result["thread_id"]), bool(result.get("already_sent", False)))

    def apply_trainlab_label(self, *, message_id: str | None, thread_id: str | None) -> None:
        self._call("create_or_apply_label", {"label": "TrainLab", "message_id": message_id or "", "thread_id": thread_id or ""}, read_only=False)

    def _get_self(self) -> GmailIdentity:
        result = self._call("get_self", {})
        email = str(result.get("email", "")).strip().lower() if isinstance(result, dict) else str(result).strip().lower() if isinstance(result, str) else ""
        if not email:
            raise GmailAdapterError("gmail_identity_invalid")
        return GmailIdentity(email)

    def _call(self, capability: str, variables: dict[str, Any], *, read_only: bool | None = None) -> Any:
        if self._transport is None or self._identity is None and capability != "get_self":
            raise GmailAdapterError("gmail_adapter_not_prepared")
        mapping = self.config.mapping["capabilities"][capability]
        arguments = format_template(mapping["arguments"], variables)
        readonly = capability in _READ_ONLY if read_only is None else read_only
        attempts = 0
        refreshed = False
        while True:
            attempts += 1
            try:
                assert self._transport is not None
                return dotted_get(normalize_tool_result(self._transport.call_tool(mapping["tool"], arguments)), mapping.get("result_path"))
            except MCPCallError as error:
                if error.status_code == 401:
                    refresher = getattr(self._transport, "refresh_auth", None)
                    if refreshed or not callable(refresher):
                        raise GmailAdapterError("auth_required") from error
                    refreshed = True
                    try:
                        refresher()
                    except Exception:
                        raise GmailAdapterError("auth_required") from None
                    continue
                if error.status_code == 403:
                    raise GmailAdapterError("forbidden") from error
                if error.status_code == 429:
                    wait = error.retry_after_seconds
                    if wait is None or wait > self._inline_retry_after_seconds:
                        raise GmailAdapterError("rate_limited", retry_at_seconds=wait) from error
                    if not readonly or attempts >= 3:
                        raise GmailAdapterError("rate_limited", retry_at_seconds=wait) from error
                    self._sleep(float(wait))
                    continue
                if readonly and attempts < 3 and (error.kind in {"timeout", "transport"} or (error.status_code is not None and error.status_code >= 500)):
                    continue
                raise GmailAdapterError("gmail_transport_failed") from error
            except GmailAdapterError:
                raise
            except Exception:
                raise GmailAdapterError("gmail_transport_failed") from None

    @staticmethod
    def _message(value: dict[str, Any], fallback_thread_id: str) -> GmailMessage:
        headers = value.get("headers") if isinstance(value.get("headers"), dict) else {}
        attachments = value.get("attachments") if isinstance(value.get("attachments"), list) else []
        recipients = value.get("to") if isinstance(value.get("to"), list) else [value.get("to")] if value.get("to") else []
        references = headers.get("references", []) if isinstance(headers.get("references"), list) else []
        return GmailMessage(
            provider_message_id=str(value.get("message_id") or value.get("id") or ""),
            provider_thread_id=str(value.get("thread_id") or value.get("threadId") or fallback_thread_id),
            received_at_utc=value.get("received_at_utc") or value.get("internal_date_utc"),
            sender=value.get("from"), recipients=tuple(str(item) for item in recipients if item), subject=value.get("subject"),
            message_id_header=headers.get("message_id"), in_reply_to=headers.get("in_reply_to"), references=tuple(str(item) for item in references),
            trainlab_run_id=headers.get("x_trainlab_run_id"), label_ids=tuple(str(item) for item in value.get("label_ids", []) if item),
            body_text=str(value.get("plain_text") or value.get("body_text") or ""), has_html=bool(value.get("has_html")),
            attachments=tuple(item for item in attachments if isinstance(item, dict)),
        )
