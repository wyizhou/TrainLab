from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import yaml

from .util import atomic_write_json


GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


TOOLS = [
    {
        "name": "get_self",
        "description": "Return and verify the authenticated Gmail account used by TrainLab.",
        "inputSchema": {"type": "object", "additionalProperties": False},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "search_messages",
        "description": "Search the authenticated Gmail account using Gmail search syntax.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            },
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "read_thread",
        "description": "Read a tracked Gmail thread with normalized message bodies and metadata.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["thread_id"],
            "properties": {"thread_id": {"type": "string", "minLength": 1}},
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "send_html_self",
        "description": "Perform the user-authorized scheduled TrainLab send. Idempotently send multipart mail only to authenticated self and apply TrainLab.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["run_id", "subject", "plain_text", "html"],
            "properties": {
                "run_id": {"type": "string", "minLength": 1},
                "subject": {"type": "string", "minLength": 1},
                "plain_text": {"type": "string", "minLength": 1},
                "html": {"type": "string", "minLength": 1},
                "thread_id": {"type": ["string", "null"]},
            },
        },
        "annotations": {"destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "name": "create_or_apply_label",
        "description": "Create/find TrainLab and apply it to one Gmail thread.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["label"],
            "properties": {
                "label": {"const": "TrainLab"},
                "thread_id": {"type": ["string", "null"]},
                "message_id": {"type": ["string", "null"]},
            },
        },
        "annotations": {"destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
]


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected mapping in {path}")
    return value


def _credential_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def _decode_body(data: str | None) -> str:
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="replace")


def _message_bodies(payload: dict[str, Any]) -> tuple[str, str]:
    plain: list[str] = []
    html: list[str] = []

    def visit(part: dict[str, Any]) -> None:
        mime = str(part.get("mimeType", "")).lower()
        body = _decode_body((part.get("body") or {}).get("data"))
        if body and mime == "text/plain":
            plain.append(body)
        elif body and mime == "text/html":
            html.append(body)
        for child in part.get("parts") or []:
            visit(child)

    visit(payload)
    return "\n".join(plain).strip(), "\n".join(html).strip()


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    return {
        str(item.get("name", "")).lower(): str(item.get("value", ""))
        for item in payload.get("headers") or []
        if item.get("name")
    }


class GmailAPI:
    def __init__(self, config: dict[str, Any], *, timeout: int | None = None):
        self.config = config
        credentials = config["credentials"]
        self.oauth_client_path = _credential_path(str(credentials["oauth_client_path"]))
        self.token_path = _credential_path(str(credentials["token_path"]))
        self.authenticated_self = str(config["authenticated_self"]).strip().lower()
        self.label = str(config.get("requirements", {}).get("label", "TrainLab"))
        self.timeout = int(timeout or config.get("transport", {}).get("timeout_seconds", 30))
        self._assert_private(self.oauth_client_path)
        self._assert_private(self.token_path)

    @staticmethod
    def _assert_private(path: Path) -> None:
        if not path.is_file():
            raise RuntimeError(f"Missing Gmail credential file: {path}")
        if path.stat().st_mode & 0o077:
            raise RuntimeError(f"Gmail credential file must be owner-only: {path}")

    def _oauth_client(self) -> dict[str, Any]:
        value = json.loads(self.oauth_client_path.read_text(encoding="utf-8"))
        client = value.get("installed") or value.get("web")
        if not isinstance(client, dict) or not client.get("client_id") or not client.get("client_secret"):
            raise RuntimeError("Invalid Google OAuth client file")
        return client

    def _saved_credentials(self) -> dict[str, Any]:
        value = json.loads(self.token_path.read_text(encoding="utf-8"))
        if not isinstance(value.get("tokens"), dict):
            raise RuntimeError("Invalid Gmail token file")
        return value

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif form is not None:
            data = urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as error:
            raw = error.read()
            try:
                detail = json.loads(raw.decode("utf-8")).get("error", {})
                message = detail.get("message") if isinstance(detail, dict) else str(detail)
            except Exception:
                message = f"HTTP {error.code}"
            raise RuntimeError(f"Gmail API request failed (HTTP {error.code}): {message or 'request rejected'}") from error
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _access_token(self, *, force_refresh: bool = False) -> str:
        saved = self._saved_credentials()
        tokens = saved["tokens"]
        expiry_ms = int(tokens.get("expiry_date") or 0)
        if not force_refresh and tokens.get("access_token") and expiry_ms > int((time.time() + 60) * 1000):
            return str(tokens["access_token"])
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("Gmail refresh token is missing")
        client = self._oauth_client()
        refreshed = self._request_json(
            "POST",
            TOKEN_ENDPOINT,
            form={
                "grant_type": "refresh_token",
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "refresh_token": refresh_token,
            },
        )
        if not refreshed.get("access_token"):
            raise RuntimeError("Google did not return a Gmail access token")
        tokens.update({key: value for key, value in refreshed.items() if key != "expires_in"})
        tokens["refresh_token"] = refresh_token
        tokens["expiry_date"] = int((time.time() + int(refreshed.get("expires_in", 3600))) * 1000)
        atomic_write_json(self.token_path, saved)
        os.chmod(self.token_path, 0o600)
        return str(tokens["access_token"])

    def _api(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{GMAIL_API}/{path.lstrip('/')}"
        if query:
            url += "?" + urlencode(query, doseq=True)
        try:
            return self._request_json(method, url, body=body, token=self._access_token())
        except RuntimeError as error:
            if "401" not in str(error) and "invalid authentication" not in str(error).lower():
                raise
            return self._request_json(method, url, body=body, token=self._access_token(force_refresh=True))

    def get_self(self) -> dict[str, Any]:
        profile = self._api("GET", "profile")
        actual = str(profile.get("emailAddress", "")).strip().lower()
        if not actual or actual != self.authenticated_self:
            raise RuntimeError("Configured Gmail self does not match the authenticated account")
        return {"email": actual, "verified": True}

    def search_messages(self, query: str, max_results: int = 10) -> dict[str, Any]:
        listed = self._api("GET", "messages", query={"q": query, "maxResults": max(1, min(50, int(max_results)))})
        matches: list[dict[str, Any]] = []
        for item in listed.get("messages") or []:
            message_id = str(item.get("id", ""))
            if not message_id:
                continue
            detail = self._api(
                "GET",
                f"messages/{quote(message_id, safe='')}",
                query={
                    "format": "metadata",
                    "metadataHeaders": [
                        "Subject",
                        "From",
                        "To",
                        "Date",
                        "Message-ID",
                        "X-TrainLab-Run-ID",
                    ],
                },
            )
            headers = _headers(detail.get("payload") or {})
            matches.append(
                {
                    "message_id": message_id,
                    "thread_id": str(detail.get("threadId", item.get("threadId", ""))),
                    "subject": headers.get("subject", ""),
                    "from": headers.get("from", ""),
                    "to": headers.get("to", ""),
                    "date": headers.get("date", ""),
                    "message_id_header": headers.get("message-id", ""),
                    "run_id_header": headers.get("x-trainlab-run-id", ""),
                }
            )
        return {"query": query, "matches": matches}

    def read_thread(self, thread_id: str) -> dict[str, Any]:
        thread = self._api("GET", f"threads/{quote(thread_id, safe='')}", query={"format": "full"})
        messages: list[dict[str, Any]] = []
        for item in thread.get("messages") or []:
            payload = item.get("payload") or {}
            headers = _headers(payload)
            plain, html = _message_bodies(payload)
            internal = item.get("internalDate")
            received_at = None
            if internal:
                received_at = datetime.fromtimestamp(int(internal) / 1000, tz=UTC).isoformat().replace("+00:00", "Z")
            messages.append(
                {
                    "message_id": str(item.get("id", "")),
                    "thread_id": str(item.get("threadId", thread_id)),
                    "from": headers.get("from", ""),
                    "to": headers.get("to", ""),
                    "subject": headers.get("subject", ""),
                    "date": headers.get("date", ""),
                    "received_at_utc": received_at,
                    "body_text": plain or html,
                    "body_html": html or None,
                    "label_ids": item.get("labelIds") or [],
                }
            )
        return {"thread_id": str(thread.get("id", thread_id)), "messages": messages}

    def _ensure_label(self, label: str) -> str:
        if label != self.label or label != "TrainLab":
            raise ValueError("Only the TrainLab label is allowed")
        labels = self._api("GET", "labels").get("labels") or []
        for item in labels:
            if item.get("name") == label:
                return str(item["id"])
        created = self._api(
            "POST",
            "labels",
            body={"name": label, "messageListVisibility": "show", "labelListVisibility": "labelShow"},
        )
        return str(created["id"])

    def apply_label(self, *, label: str, thread_id: str | None, message_id: str | None = None) -> dict[str, Any]:
        actual_thread = str(thread_id or "")
        if not actual_thread and message_id:
            message = self._api("GET", f"messages/{quote(message_id, safe='')}", query={"format": "minimal"})
            actual_thread = str(message.get("threadId", ""))
        if not actual_thread:
            raise ValueError("thread_id or message_id is required")
        label_id = self._ensure_label(label)
        self._api(
            "POST",
            f"threads/{quote(actual_thread, safe='')}/modify",
            body={"addLabelIds": [label_id], "removeLabelIds": []},
        )
        return {"label": label, "label_id": label_id, "thread_id": actual_thread, "applied": True}

    def send_self(
        self,
        *,
        run_id: str,
        subject: str,
        plain_text: str,
        html: str,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        if not RUN_ID_PATTERN.fullmatch(run_id) or run_id not in subject:
            raise ValueError("A safe run-id must appear in the subject")
        if not plain_text.strip() or not html.strip() or "style=" not in html:
            raise ValueError("Multipart plain text and inline-styled HTML are required")
        if re.search(r"<script\b|javascript:", html, flags=re.IGNORECASE):
            raise ValueError("Unsafe HTML content")
        existing = self.search_messages(f'subject:"{run_id}"', 10)["matches"]
        exact = next((item for item in existing if run_id in item.get("subject", "")), None)
        if exact:
            if exact.get("thread_id"):
                self.apply_label(label="TrainLab", thread_id=str(exact["thread_id"]))
            return {
                "message_id": exact.get("message_id"),
                "thread_id": exact.get("thread_id"),
                "recipient": "self",
                "label": "TrainLab",
                "already_sent": True,
            }
        account = self.get_self()["email"]
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = account
        message["To"] = account
        message["Message-ID"] = f"<{run_id}@trainlab.local>"
        message["X-TrainLab-Run-ID"] = run_id
        message.set_content(plain_text)
        message.add_alternative(html, subtype="html")
        raw = base64.urlsafe_b64encode(message.as_bytes(policy=SMTP)).decode("ascii").rstrip("=")
        request_body: dict[str, Any] = {"raw": raw}
        if thread_id:
            request_body["threadId"] = thread_id
        sent = self._api("POST", "messages/send", body=request_body)
        message_id = str(sent.get("id", ""))
        actual_thread = str(sent.get("threadId", thread_id or ""))
        if not message_id or not actual_thread:
            raise RuntimeError("Gmail send did not return message and thread IDs")
        self.apply_label(label="TrainLab", thread_id=actual_thread)
        return {
            "message_id": message_id,
            "thread_id": actual_thread,
            "recipient": "self",
            "label": "TrainLab",
            "already_sent": False,
        }

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "get_self":
            return self.get_self()
        if name == "search_messages":
            return self.search_messages(str(arguments["query"]), int(arguments.get("max_results", 10)))
        if name == "read_thread":
            return self.read_thread(str(arguments["thread_id"]))
        if name == "send_html_self":
            return self.send_self(
                run_id=str(arguments["run_id"]),
                subject=str(arguments["subject"]),
                plain_text=str(arguments["plain_text"]),
                html=str(arguments["html"]),
                thread_id=str(arguments.get("thread_id") or "") or None,
            )
        if name == "create_or_apply_label":
            return self.apply_label(
                label=str(arguments["label"]),
                thread_id=str(arguments.get("thread_id") or "") or None,
                message_id=str(arguments.get("message_id") or "") or None,
            )
        raise ValueError(f"Unknown Gmail MCP tool: {name}")


def _response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve(config_path: Path) -> None:
    gmail = GmailAPI(_load_yaml(config_path))
    for line in sys.stdin:
        message: dict[str, Any] | None = None
        try:
            message = json.loads(line)
            request_id = message.get("id")
            method = message.get("method")
            if request_id is None:
                continue
            if method == "initialize":
                result = {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "trainlab-gmail", "version": "1"},
                }
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = message.get("params") or {}
                value = gmail.call_tool(str(params.get("name", "")), dict(params.get("arguments") or {}))
                result = {
                    "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, sort_keys=True)}],
                    "structuredContent": value,
                }
            else:
                raise ValueError(f"Unsupported MCP method: {method}")
            output = _response(request_id, result)
        except Exception as error:
            output = {
                "jsonrpc": "2.0",
                "id": message.get("id") if message else None,
                "error": {"code": -32000, "message": f"{type(error).__name__}: {error}"},
            }
        sys.stdout.write(json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trainlab-gmail-mcp")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    serve(Path(args.config).expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
