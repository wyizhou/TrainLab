from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings, load_yaml
from .db import transaction
from .mcp import StdioMCPClient, dotted_get, format_template, normalize_tool_result
from .util import atomic_write_json, iso_utc, utc_now


INJECTION_PATTERNS = (
    r"ignore (all |the )?(previous|prior) instructions",
    r"system prompt",
    r"developer message",
    r"忽略.{0,10}(之前|以上).{0,10}(指令|要求)",
)


class FakeGmail:
    def __init__(self, settings: Settings, connection):
        self.settings = settings
        self.connection = connection
        self.path = settings.path("state_directory") / "fake_gmail.json"

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"account": "authenticated-self@fake.local", "labels": ["TrainLab"], "messages": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, state: dict[str, Any]) -> None:
        atomic_write_json(self.path, state)

    def get_self(self) -> str:
        return str(self._load()["account"])

    def search_run_id(self, run_id: str) -> dict[str, Any] | None:
        for message in self._load()["messages"]:
            if message.get("direction") == "out" and message.get("headers", {}).get("X-TrainLab-Run-ID") == run_id:
                return message
        return None

    def send_self(
        self,
        *,
        run_id: str,
        subject: str,
        plain_text: str,
        html: str,
        label: str = "TrainLab",
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        existing = self.search_run_id(run_id)
        if existing:
            return {**existing, "already_sent": True}
        _validate_message(subject, plain_text, html, run_id)
        state = self._load()
        message_id = f"fake-msg-{uuid.uuid4().hex[:16]}"
        actual_thread = thread_id or f"fake-thread-{uuid.uuid4().hex[:16]}"
        message = {
            "message_id": message_id,
            "thread_id": actual_thread,
            "direction": "out",
            "from": state["account"],
            "to": state["account"],
            "subject": subject,
            "plain_text": plain_text,
            "html": html,
            "labels": [label],
            "headers": {"X-TrainLab-Run-ID": run_id, "Message-ID": f"<{run_id}@trainlab.local>"},
            "sent_at_utc": iso_utc(),
        }
        state["messages"].append(message)
        if label not in state["labels"]:
            state["labels"].append(label)
        self._save(state)
        return message

    def inject_reply(self, *, thread_id: str, body_text: str, received_at_utc: str | None = None) -> dict[str, Any]:
        state = self._load()
        parents = [message for message in state["messages"] if message["thread_id"] == thread_id]
        if not parents:
            raise ValueError(f"Unknown fake Gmail thread: {thread_id}")
        message = {
            "message_id": f"fake-reply-{uuid.uuid4().hex[:16]}",
            "thread_id": thread_id,
            "direction": "in",
            "from": state["account"],
            "to": state["account"],
            "subject": f"Re: {parents[-1]['subject']}",
            "plain_text": body_text,
            "labels": [],
            "headers": {},
            "received_at_utc": received_at_utc or iso_utc(),
        }
        state["messages"].append(message)
        self._save(state)
        return message

    def poll_replies(self) -> list[dict[str, Any]]:
        state = self._load()
        trainlab_threads = {
            message["thread_id"]
            for message in state["messages"]
            if message.get("direction") == "out" and "TrainLab" in message.get("labels", [])
        }
        return [
            message
            for message in state["messages"]
            if message.get("direction") == "in" and message["thread_id"] in trainlab_threads
        ]


class MappedGmailMCP:
    def __init__(self, settings: Settings):
        config_path = settings.root / settings.values["mail"]["gmail_config"]
        self.config = load_yaml(config_path)
        if not self.config.get("configured"):
            raise RuntimeError("Gmail MCP mapping is not configured")
        transport = self.config.get("transport", {})
        if transport.get("type") != "stdio" or not transport.get("command"):
            raise RuntimeError("Deterministic Gmail MCP requires a configured stdio transport")
        env = {key: str(value) for key, value in transport.get("env", {}).items()}
        self.client = StdioMCPClient(
            str(transport["command"]),
            [str(item) for item in transport.get("args", [])],
            env=env,
            timeout=int(transport.get("timeout_seconds", 30)),
        )

    def _call(self, capability: str, variables: dict[str, Any]) -> Any:
        mapping = self.config["capabilities"][capability]
        result = self.client.call_tool(mapping["tool"], format_template(mapping.get("arguments", {}), variables))
        return dotted_get(normalize_tool_result(result), mapping.get("result_path"))

    def get_self(self) -> str:
        return str(self._call("get_self", {}))

    def available_tools(self) -> set[str]:
        return {str(item.get("name")) for item in self.client.list_tools() if item.get("name")}

    def search_run_id(self, run_id: str) -> Any:
        return self._call("search", {"query": f'"{run_id}"', "run_id": run_id, "label": "TrainLab"})

    def send_self(self, *, run_id: str, subject: str, plain_text: str, html: str, label: str = "TrainLab", thread_id: str | None = None) -> Any:
        _validate_message(subject, plain_text, html, run_id)
        recipient = self.get_self()
        result = self._call(
            "send_html_self",
            {
                "recipient": recipient,
                "subject": subject,
                "plain_text": plain_text,
                "html": html,
                "run_id": run_id,
                "label": label,
                "thread_id": thread_id or "",
            },
        )
        self._call("create_or_apply_label", {"label": label, "message_id": _extract_id(result, "message_id"), "thread_id": _extract_id(result, "thread_id")})
        return result

    def close(self) -> None:
        self.client.close()


def _extract_id(value: Any, key: str) -> str | None:
    if isinstance(value, dict):
        return value.get(key) or value.get(key.replace("_", ""))
    return None


def _validate_message(subject: str, plain_text: str, html: str, run_id: str) -> None:
    if run_id not in subject:
        raise ValueError("Mail subject must contain run-id")
    if not plain_text.strip() or not html.strip():
        raise ValueError("Both plain text and HTML bodies are required")
    if re.search(r"<script\b|javascript:", html, flags=re.IGNORECASE):
        raise ValueError("Unsafe HTML content")
    if "style=" not in html:
        raise ValueError("Gmail HTML must use inline styles")


def gateway(settings: Settings, connection):
    if settings.values["mail"].get("mode") == "fake":
        return FakeGmail(settings, connection)
    return MappedGmailMCP(settings)


def poll_and_store_feedback(settings: Settings, connection) -> int:
    mailer = gateway(settings, connection)
    if not isinstance(mailer, FakeGmail):
        # Production replies are read by the runtime agent through its configured
        # Gmail MCP. A normalized result is then persisted by apply_result().
        close = getattr(mailer, "close", None)
        if close:
            close()
        return 0
    inserted = 0
    timezone = ZoneInfo(settings.timezone)
    with transaction(connection):
        for message in mailer.poll_replies():
            if connection.execute("SELECT 1 FROM feedback_messages WHERE gmail_message_id=?", (message["message_id"],)).fetchone():
                continue
            received = datetime.fromisoformat(message["received_at_utc"].replace("Z", "+00:00"))
            injection_risk = any(re.search(pattern, message["plain_text"], re.IGNORECASE) for pattern in INJECTION_PATTERNS)
            connection.execute(
                """INSERT INTO feedback_messages(
                       gmail_message_id, gmail_thread_id, received_at_utc, reply_local_date,
                       subject, body_text, structured_json, injection_risk
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    message["message_id"],
                    message["thread_id"],
                    iso_utc(received),
                    received.astimezone(timezone).date().isoformat(),
                    message.get("subject"),
                    message["plain_text"],
                    None,
                    int(injection_risk),
                ),
            )
            inserted += 1
    return inserted


def record_delivery(connection, *, run_id: str, receipt: dict[str, Any], subject: str, transport: str, status: str = "sent") -> None:
    connection.execute(
        """INSERT INTO mail_deliveries(
               run_id, gmail_message_id, gmail_thread_id, recipient, label, subject,
               transport, status, sent_at_utc, mime_headers_json
           ) VALUES(?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(run_id) DO UPDATE SET
               gmail_message_id=excluded.gmail_message_id,
               gmail_thread_id=excluded.gmail_thread_id,
               status=excluded.status,
               sent_at_utc=excluded.sent_at_utc""",
        (
            run_id,
            receipt.get("message_id"),
            receipt.get("thread_id"),
            "self",
            "TrainLab",
            subject,
            transport,
            status,
            iso_utc() if status == "sent" else None,
            json.dumps({"X-TrainLab-Run-ID": run_id, "Message-ID": f"<{run_id}@trainlab.local>"}),
        ),
    )
