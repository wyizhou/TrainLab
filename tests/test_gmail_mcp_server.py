from __future__ import annotations

import base64
import json
from email import policy
from email.parser import BytesParser

from jsonschema import Draft202012Validator

from trainlab.gmail_mcp_server import TOOLS, GmailAPI
from trainlab.mail import MappedGmailMCP


class FakeGmailAPI(GmailAPI):
    def __init__(self, *, existing: list[dict] | None = None):
        self.authenticated_self = "self@example.com"
        self.label = "TrainLab"
        self.timeout = 1
        self.existing = existing or []
        self.calls: list[tuple[str, str, dict | None]] = []
        self.raw_message: bytes | None = None

    def get_self(self):
        return {"email": self.authenticated_self, "verified": True}

    def search_messages(self, query: str, max_results: int = 10):
        return {"query": query, "matches": self.existing}

    def _api(self, method: str, path: str, *, query=None, body=None):
        self.calls.append((method, path, body))
        if path == "messages/send":
            encoded = str(body["raw"])
            self.raw_message = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            return {"id": "message-1", "threadId": "thread-1"}
        if path == "labels" and method == "GET":
            return {"labels": [{"id": "Label_TrainLab", "name": "TrainLab"}]}
        if path.endswith("/modify"):
            return {}
        raise AssertionError(f"Unexpected API call: {method} {path}")


class FakeSearchGmailAPI(GmailAPI):
    def _api(self, method: str, path: str, *, query=None, body=None):
        if path == "messages":
            return {"messages": [{"id": "message-1", "threadId": "thread-1"}]}
        if path == "messages/message-1":
            assert query["format"] == "metadata"
            assert "X-TrainLab-Run-ID" in query["metadataHeaders"]
            return {
                "id": "message-1",
                "threadId": "thread-1",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "TrainLab report"},
                        {"name": "Message-ID", "value": "<run-1@trainlab.local>"},
                        {"name": "X-TrainLab-Run-ID", "value": "run-1"},
                    ]
                },
            }
        raise AssertionError(f"Unexpected API call: {method} {path}")


def test_self_send_builds_multipart_headers_and_applies_label():
    gmail = FakeGmailAPI()
    result = gmail.send_self(
        run_id="trainlab-2026-07-21-morning-v1",
        subject="TrainLab｜trainlab-2026-07-21-morning-v1",
        plain_text="Plain fallback",
        html='<div style="font-family:Arial">HTML report</div>',
    )

    assert result == {
        "message_id": "message-1",
        "thread_id": "thread-1",
        "recipient": "self",
        "label": "TrainLab",
        "already_sent": False,
    }
    message = BytesParser(policy=policy.default).parsebytes(gmail.raw_message)
    assert message["To"] == "self@example.com"
    assert message["From"] == "self@example.com"
    assert message["X-TrainLab-Run-ID"] == "trainlab-2026-07-21-morning-v1"
    assert message["Message-ID"] == "<trainlab-2026-07-21-morning-v1@trainlab.local>"
    assert message.get_content_type() == "multipart/alternative"
    assert [part.get_content_type() for part in message.iter_parts()] == ["text/plain", "text/html"]
    assert any(path == "threads/thread-1/modify" for _, path, _ in gmail.calls)


def test_self_send_tool_is_idempotent_and_non_destructive():
    tool = next(item for item in TOOLS if item["name"] == "send_html_self")
    assert tool["annotations"]["destructiveHint"] is False
    assert tool["annotations"]["idempotentHint"] is True


def test_search_exposes_idempotency_headers_for_acceptance_checks():
    gmail = object.__new__(FakeSearchGmailAPI)
    result = gmail.search_messages('subject:"run-1"')

    assert result["matches"][0]["message_id_header"] == "<run-1@trainlab.local>"
    assert result["matches"][0]["run_id_header"] == "run-1"


def test_self_send_is_idempotent_before_gmail_write():
    gmail = FakeGmailAPI(
        existing=[
            {
                "message_id": "existing-message",
                "thread_id": "existing-thread",
                "subject": "TrainLab trainlab-2026-07-21-evening-v1",
            }
        ]
    )
    result = gmail.send_self(
        run_id="trainlab-2026-07-21-evening-v1",
        subject="TrainLab trainlab-2026-07-21-evening-v1",
        plain_text="Plain fallback",
        html='<div style="font-family:Arial">HTML report</div>',
    )

    assert result["already_sent"] is True
    assert result["message_id"] == "existing-message"
    assert not any(path == "messages/send" for _, path, _ in gmail.calls)
    assert any(path == "threads/existing-thread/modify" for _, path, _ in gmail.calls)


class FakeMCPClient:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        values = {
            "get_self": {"email": "self@example.com", "verified": True},
            "search_messages": {"matches": []},
            "send_html_self": {"message_id": "m1", "thread_id": "t1", "already_sent": False},
            "create_or_apply_label": {"thread_id": "t1", "applied": True},
        }
        return {"structuredContent": values[name]}

    def list_tools(self):
        return [{"name": name} for name in ("get_self", "search_messages", "read_thread", "send_html_self", "create_or_apply_label")]

    def close(self):
        return None


def test_mapped_gateway_matches_trainlab_mcp_contract(base_settings):
    # Frozen legacy mapping fixture. New production paths use the environment
    # binding declared by config/gmail_mcp.example.yaml.
    config = {
        "capabilities": {
            "get_self": {"tool": "get_self", "arguments": {}, "result_path": "email"},
            "search": {
                "tool": "search_messages",
                "arguments": {"query": 'subject:"{run_id}"', "max_results": 10},
                "result_path": "matches",
            },
            "send_html_self": {
                "tool": "send_html_self",
                "arguments": {
                    "run_id": "{run_id}",
                    "subject": "{subject}",
                    "plain_text": "{plain_text}",
                    "html": "{html}",
                    "thread_id": "{thread_id}",
                },
                "result_path": None,
            },
            "create_or_apply_label": {
                "tool": "create_or_apply_label",
                "arguments": {
                    "label": "{label}",
                    "message_id": "{message_id}",
                    "thread_id": "{thread_id}",
                },
                "result_path": None,
            },
        }
    }
    gateway = object.__new__(MappedGmailMCP)
    gateway.config = config
    gateway.client = FakeMCPClient()

    assert gateway.get_self() == "self@example.com"
    assert gateway.search_run_id("trainlab-test") == []
    receipt = gateway.send_self(
        run_id="trainlab-test",
        subject="TrainLab trainlab-test",
        plain_text="plain",
        html='<div style="display:block">html</div>',
    )
    assert receipt["message_id"] == "m1"
    assert gateway.client.calls[-1] == (
        "create_or_apply_label",
        {"label": "TrainLab", "message_id": "m1", "thread_id": "t1"},
    )


def test_gmail_mapping_example_matches_schema(base_settings):
    root = base_settings.root
    schema = json.loads((root / "harness" / "schemas" / "gmail_mcp.schema.json").read_text())
    value = __import__("yaml").safe_load((root / "config" / "gmail_mcp.example.yaml").read_text())
    Draft202012Validator(schema).validate(value)
