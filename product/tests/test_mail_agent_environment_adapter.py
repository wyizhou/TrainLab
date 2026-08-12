from __future__ import annotations

import pytest

from trainlab.gmail_environment import GmailEnvironmentStatus
from trainlab.mail_agent.environment_adapter import (
    GmailEnvironmentAdapterError,
    GmailEnvironmentRecipientAdapter,
)
from trainlab.mcp import MCPResponseError


REQUIRED = {"search_emails", "get_thread", "send_email", "get_or_create_label", "modify_email"}
SELF = "self@example.com"
THREAD = "thread-1"
MESSAGE = "message-1"
KEY = "mail:response:23:thread-1"


def available() -> GmailEnvironmentStatus:
    return GmailEnvironmentStatus(True, None, "gmail_mcp_available", "safe")


class Client:
    def __init__(self, *, tools=REQUIRED, responses=(), failure=None):
        self.tools = tools
        self.responses = list(responses)
        self.failure = failure
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def list_tools(self):
        return [{"name": name} for name in self.tools]

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.failure is not None:
            raise self.failure
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


def adapter(client: Client, *, inspector=available):
    return GmailEnvironmentRecipientAdapter(
        SELF,
        inspector=inspector,
        client_factory=lambda *_args, **_kwargs: client,
        sleep=lambda _seconds: None,
        jitter=lambda _delay: 0.0,
    )


def send(value: GmailEnvironmentRecipientAdapter):
    return value.send_html_recipient(run_id=KEY, subject=f"Re: TrainLab · {KEY}", plain_text="plain", html="<p>html</p>", thread_id=THREAD, in_reply_to_provider_message_id=MESSAGE)


def self_thread(*, participants=True):
    sender = SELF if participants else "other@example.com"
    return {"threadId": THREAD, "messages": [{"messageId": MESSAGE, "threadId": THREAD, "from": sender, "to": SELF, "cc": []}]}


def test_exact_binding_is_checked_before_client_starts():
    client = Client()
    with pytest.raises(GmailEnvironmentAdapterError, match="^gmail_mcp_binding_invalid$"):
        send(adapter(client, inspector=lambda: GmailEnvironmentStatus(False, None, "gmail_mcp_binding_invalid", "secret")))
    assert client.calls == [] and client.closed is False


def test_no_match_verifies_exact_self_thread_and_uses_only_fixed_arguments():
    client = Client(responses=[
        "",
        self_thread(),
        "Email sent successfully with ID: sent-1",
        "Successfully found existing label:\nID: label-1\nName: TrainLab\nType: user",
        "Email sent-1 labels updated successfully",
    ])
    receipt = send(adapter(client))
    assert receipt.already_sent is False and receipt.provider_message_id == "sent-1" and receipt.provider_thread_id == THREAD
    marker = "[TrainLab idempotency: mail:response:23:thread-1]"
    assert client.calls == [
        ("search_emails", {"query": f'in:sent "{marker}"', "maxResults": 2}),
        ("get_thread", {"threadId": THREAD, "format": "full"}),
        ("send_email", {"to": [SELF], "subject": f"Re: TrainLab · {KEY}", "body": "plain", "htmlBody": f'<p>html</p><span style="display:none!important;max-height:0;overflow:hidden;opacity:0;mso-hide:all;">{marker}</span>', "mimeType": "multipart/alternative", "threadId": THREAD, "inReplyTo": MESSAGE}),
    ]
    assert client.closed and all(name in REQUIRED for name, _ in client.calls)
    assert all("attachments" not in arguments for _, arguments in client.calls)


def test_subject_need_not_expose_run_id_and_marker_is_html_only():
    client = Client(responses=["", self_thread(), "Email sent successfully with ID: sent-1"])
    value = adapter(client)
    value.send_html_recipient(
        run_id=KEY,
        subject="Re: 本周训练",
        plain_text="plain",
        html="<p>html</p>",
        thread_id=THREAD,
        in_reply_to_provider_message_id=MESSAGE,
    )
    payload = client.calls[-1][1]
    assert payload["subject"] == "Re: 本周训练" and KEY not in payload["subject"]
    assert payload["body"] == "plain" and KEY not in payload["body"]
    assert KEY in payload["htmlBody"] and "display:none!important" in payload["htmlBody"]


def test_caller_cannot_preinject_idempotency_marker() -> None:
    marker = f"[TrainLab idempotency: {KEY}]"
    client = Client(responses=[])
    value = adapter(client)
    with pytest.raises(GmailEnvironmentAdapterError, match="gmail_reply_idempotency_invalid"):
        value.send_html_recipient(
            run_id=KEY,
            subject="Re: 本周训练",
            plain_text="plain",
            html=f"<p>{marker}</p>",
            thread_id=THREAD,
            in_reply_to_provider_message_id=MESSAGE,
        )
    assert client.calls == []


def test_existing_marker_is_validated_in_exact_thread_and_never_sends():
    client = Client(responses=[f"ID: old-1\nSubject: any\nFrom: {SELF}\nDate: Fri, 24 Jul 2026 00:00:00 +0000\n", {"threadId": THREAD, "messages": [{"messageId": "old-1", "threadId": THREAD, "from": SELF, "to": SELF, "cc": [], "body": f"x [TrainLab idempotency: {KEY}]"}]}])
    result = send(adapter(client))
    assert result.already_sent and result.provider_message_id == "old-1"
    assert [name for name, _ in client.calls] == ["search_emails", "get_thread"] and client.closed


def test_preflight_search_returns_only_a_self_verified_exact_thread_match():
    client = Client(responses=[f"ID: old-1\nSubject: any\nFrom: {SELF}\nDate: Fri, 24 Jul 2026 00:00:00 +0000\n", {"threadId": THREAD, "messages": [{"messageId": "old-1", "threadId": THREAD, "from": [SELF], "to": [SELF], "cc": [], "body": f"x [TrainLab idempotency: {KEY}]"}]}])
    assert adapter(client).search_run_id(run_id=KEY) == ({"message_id": "old-1", "thread_id": THREAD},)
    assert [name for name, _ in client.calls] == ["search_emails", "get_thread"] and client.closed


def test_label_is_applied_only_to_the_new_provider_message_id():
    client = Client(responses=["Successfully found existing label:\nID: label-1\nName: TrainLab\nType: user", "Email sent-1 labels updated successfully"])
    adapter(client).apply_trainlab_label(message_id="sent-1", thread_id=THREAD)
    assert client.calls == [
        ("get_or_create_label", {"name": "TrainLab"}),
        ("modify_email", {"messageId": "sent-1", "addLabelIds": ["label-1"]}),
    ]
    assert client.closed


def test_poll_search_uses_only_search_result_id_then_fixed_read_email_for_thread_id():
    client = Client(
        tools=REQUIRED | {"read_email"},
        responses=[
            "ID: message-1\nSubject: any\nFrom: self@example.com\nDate: Fri, 24 Jul 2026 00:00:00 +0000\n",
            {"id": "message-1", "threadId": THREAD},
        ],
    )
    result = adapter(client).search_trainlab_window(
        start_date=__import__("datetime").date(2026, 7, 20),
        end_date=__import__("datetime").date(2026, 7, 21),
    )
    assert result == ({"thread_id": THREAD, "message_id": "message-1"},)
    assert client.calls == [
        ("search_emails", {"query": "label:TrainLab after:2026-07-20 before:2026-07-21", "maxResults": 100}),
        ("read_email", {"messageId": "message-1"}),
    ]


def test_multi_party_thread_is_rejected_before_send():
    thread = self_thread(participants=False)
    thread["messages"].append({"messageId": "message-2", "threadId": THREAD, "from": "third@example.com", "to": SELF, "cc": []})
    client = Client(responses=["", thread])
    with pytest.raises(GmailEnvironmentAdapterError, match="^gmail_reply_thread_participants_invalid$"):
        send(adapter(client))
    assert [name for name, _ in client.calls] == ["search_emails", "get_thread"] and client.closed


def test_target_and_thread_must_match_exactly():
    client = Client(responses=["", {"threadId": "other", "messages": []}])
    with pytest.raises(GmailEnvironmentAdapterError, match="^gmail_reply_thread_mismatch$"):
        send(adapter(client))
    assert [name for name, _ in client.calls] == ["search_emails", "get_thread"]


@pytest.mark.parametrize("field", ("from", "to"))
def test_exact_trigger_requires_nonempty_self_from_and_to(field):
    thread = self_thread()
    thread["messages"][0][field] = ""
    client = Client(responses=["", thread])
    with pytest.raises(GmailEnvironmentAdapterError, match="^gmail_reply_thread_participants_invalid$"):
        send(adapter(client))
    assert [name for name, _ in client.calls] == ["search_emails", "get_thread"]


@pytest.mark.parametrize(("failure", "code"), [
    (TimeoutError("provider secret"), "gmail_reply_timeout"),
    (MCPResponseError(status_code=401), "gmail_reply_auth_required"),
    (MCPResponseError(status_code=403), "gmail_reply_forbidden"),
    (MCPResponseError(status_code=429), "gmail_reply_rate_limited"),
    (MCPResponseError(status_code=500), "gmail_reply_provider_error"),
    (MCPResponseError(kind="protocol"), "gmail_reply_protocol_error"),
    (RuntimeError("provider secret"), "gmail_reply_transport_error"),
])
def test_provider_errors_are_redacted_and_transport_is_closed(failure, code):
    client = Client(failure=failure)
    with pytest.raises(GmailEnvironmentAdapterError, match=f"^{code}$") as raised:
        send(adapter(client))
    assert "secret" not in str(raised.value) and client.closed


def test_malformed_search_or_thread_protocol_fails_closed():
    client = Client(responses=["bad provider body"])
    with pytest.raises(GmailEnvironmentAdapterError, match="^gmail_reply_protocol_invalid$"):
        send(adapter(client))
    assert [name for name, _ in client.calls] == ["search_emails"] and client.closed


def test_missing_capability_closes_without_any_mail_call():
    client = Client(tools=REQUIRED - {"send_email"})
    with pytest.raises(GmailEnvironmentAdapterError, match="^gmail_reply_capability_mismatch$"):
        send(adapter(client))
    assert client.calls == [] and client.closed


def test_verified_registry_binding_is_used_to_start_the_client():
    client = Client(responses=["", self_thread(), "Email sent successfully with ID: sent-1"])
    started = []
    status = GmailEnvironmentStatus(True, None, "gmail_mcp_available", "safe", "/opt/runtime/npx", ("@artymclabin/gmail-mcp",))
    value = GmailEnvironmentRecipientAdapter(
        SELF, inspector=lambda: status,
        client_factory=lambda command, args, **kwargs: (started.append((command, args, kwargs)) or client),
    )
    send(value)
    assert started == [(
        "/opt/runtime/npx",
        ["@artymclabin/gmail-mcp"],
        {
            "timeout": 60,
            "stdout_preamble_lines": (
                "OAuth keys found in current directory, copied to global config.",
            ),
        },
    )]


def test_read_only_short_rate_limit_is_retried_but_send_is_not():
    client = Client(responses=[MCPResponseError(status_code=429, retry_after_seconds=1), "", self_thread(), "Email sent successfully with ID: sent-1"])
    pauses = []
    value = GmailEnvironmentRecipientAdapter(SELF, inspector=available, client_factory=lambda *_a, **_k: client, sleep=pauses.append)
    send(value)
    assert [name for name, _ in client.calls].count("search_emails") == 2
    assert pauses == [1.0]


def test_thread_evidence_has_poll_canonical_fields_and_keeps_provider_raw():
    provider = {"threadId": THREAD, "labelIds": ["TrainLab"], "messages": [{
        "id": MESSAGE, "threadId": THREAD, "receivedAt": "2026-07-24T00:00:00Z",
        "from": SELF, "to": [SELF], "subject": "TrainLab", "body": "hello",
        "labelIds": ["TrainLab"], "headers": {}, "attachments": [],
    }]}
    evidence = adapter(Client(responses=[provider])).read_thread_evidence(THREAD)
    raw_message = evidence.raw_payload["messages"][0]
    assert evidence.thread.messages[0].received_at_utc == "2026-07-24T00:00:00Z"
    assert raw_message["message_id"] == MESSAGE
    assert raw_message["internal_date_utc"] == "2026-07-24T00:00:00Z"
    assert raw_message["provider_raw"] == provider["messages"][0]


def test_thread_evidence_normalizes_provider_rfc2822_date_to_utc():
    provider = {
        "threadId": THREAD,
        "messages": [
            {
                "messageId": MESSAGE,
                "threadId": THREAD,
                "from": SELF,
                "to": SELF,
                "cc": "",
                "bcc": "",
                "subject": "TrainLab",
                "date": "Sun, 26 Jul 2026 05:45:49 -0700",
                "body": "hello",
                "labelIds": ["TrainLab"],
                "attachments": [],
            }
        ],
    }

    evidence = adapter(Client(responses=[provider])).read_thread_evidence(THREAD)

    assert evidence.raw_payload["messages"][0]["internal_date_utc"] == "2026-07-26T12:45:49Z"
    assert evidence.thread.messages[0].received_at_utc == "2026-07-26T12:45:49Z"
