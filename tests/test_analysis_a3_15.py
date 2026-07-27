from __future__ import annotations

import pytest

from trainlab.analysis.gmail_delivery import (
    GmailDeliveryError,
    GmailDeliveryGateway,
    canonical_self_recipient,
)
from trainlab.gmail_environment import GmailEnvironmentStatus
from trainlab.mcp import MCPResponseError


REQUIRED = {"search_emails", "send_email", "get_or_create_label", "modify_email"}
SUBJECT = "[TrainLab] daily | idempotency analysis-delivery:v1:abc"
DATE = "Fri, 24 Jul 2026 00:00:00 +0000"


def available() -> GmailEnvironmentStatus:
    return GmailEnvironmentStatus(True, None, "gmail_mcp_available", "safe")


class FakeClient:
    def __init__(self, *, tools=REQUIRED, responses=None, failure=None):
        self.tools = tools
        self.responses = list(responses or [])
        self.failure = failure
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def list_tools(self):
        return [{"name": item} for item in self.tools]

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.failure:
            raise self.failure
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def gateway(client: FakeClient, *, inspector=available) -> GmailDeliveryGateway:
    return GmailDeliveryGateway(
        "self@example.com",
        inspector=inspector,
        client_factory=lambda *args, **kwargs: client,
    )


def deliver(value: GmailDeliveryGateway):
    return value.deliver(
        subject=SUBJECT,
        idempotency_key="analysis-delivery:v1:abc",
        plain_text="plain",
        html="<p>html</p>",
    )


def test_rejects_noncanonical_or_multiple_recipient_forms():
    assert canonical_self_recipient("USER@example.com") == "user@example.com"
    for value in (" user@example.com", "a@localhost", "a@example.com\nother@example.com", ""):
        with pytest.raises(GmailDeliveryError, match="^gmail_delivery_recipient_invalid$"):
            canonical_self_recipient(value)


def test_invalid_current_environment_binding_fails_before_client_start():
    client = FakeClient()
    status = GmailEnvironmentStatus(False, None, "gmail_mcp_binding_invalid", "secret path")
    with pytest.raises(GmailDeliveryError, match="^gmail_mcp_binding_invalid$") as raised:
        deliver(gateway(client, inspector=lambda: status))
    assert "secret" not in str(raised.value)
    assert not client.calls and not client.closed


def test_verified_current_environment_binding_is_used_verbatim():
    client = FakeClient(tools=REQUIRED - {"modify_email"})
    calls = []
    status = GmailEnvironmentStatus(
        True, None, "gmail_mcp_available", "safe",
        "registered-npx", ("@artymclabin/gmail-mcp",),
    )
    value = GmailDeliveryGateway(
        "self@example.com",
        inspector=lambda: status,
        client_factory=lambda *args, **kwargs: (
            calls.append((args, kwargs)) or client
        ),
    )
    with pytest.raises(
        GmailDeliveryError,
        match="^gmail_delivery_capability_mismatch$",
    ):
        deliver(value)
    assert calls == [
        (
            ("registered-npx", ["@artymclabin/gmail-mcp"]),
            {"timeout": 60},
        )
    ]


def test_missing_required_capability_fails_closed_and_closes():
    client = FakeClient(tools=REQUIRED - {"modify_email"})
    with pytest.raises(GmailDeliveryError, match="^gmail_delivery_capability_mismatch$"):
        deliver(gateway(client))
    assert client.calls == [] and client.closed


def test_exact_complete_subject_query_and_one_match_is_labeled_then_returned():
    client = FakeClient(responses=[{"emails": [{"id": "message-1", "from": "TrainLab <self@example.com>", "subject": SUBJECT, "date": DATE}]}, {"id": "label-1"}, {"id": "message-1"}])
    receipt = deliver(gateway(client))
    assert receipt.status == "already_sent" and receipt.provider_message_id == "message-1"
    assert receipt.provider_sent_at_utc == "2026-07-24T00:00:00Z"
    assert [name for name, _ in client.calls] == ["search_emails", "get_or_create_label", "modify_email"]
    assert client.closed


def test_no_match_sends_multipart_then_creates_and_applies_trainlab_label():
    client = FakeClient(responses=[
        {"emails": []},
        {"id": "sent-1", "threadId": "thread-1"},
        {"id": "label-1"},
        {"id": "sent-1"},
    ])
    receipt = deliver(gateway(client))
    assert receipt.status == "sent"
    assert (receipt.provider_message_id, receipt.provider_thread_id, receipt.label_id) == ("sent-1", "thread-1", "label-1")
    assert client.calls == [
        ("search_emails", {"query": 'in:sent "analysis-delivery:v1:abc"', "maxResults": 2}),
        ("send_email", {"to": ["self@example.com"], "from": "self@example.com", "subject": SUBJECT, "body": "plain", "htmlBody": "<p>html</p>", "mimeType": "multipart/alternative"}),
        ("get_or_create_label", {"name": "TrainLab"}),
        ("modify_email", {"messageId": "sent-1", "addLabelIds": ["label-1"]}),
    ]
    assert all(name in REQUIRED for name, _ in client.calls)


def test_multiple_matches_are_ambiguous_and_never_send():
    client = FakeClient(responses=[{"messages": [{"id": "message-1", "from": "self@example.com", "subject": SUBJECT, "date": DATE}, {"id": "message-2", "from": "self@example.com", "subject": SUBJECT, "date": DATE}]}])
    with pytest.raises(GmailDeliveryError, match="^gmail_delivery_idempotency_ambiguous$"):
        deliver(gateway(client))
    assert [name for name, _ in client.calls] == ["search_emails"]


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (TimeoutError("do not disclose"), "gmail_delivery_timeout"),
        (MCPResponseError(status_code=401), "gmail_delivery_auth_required"),
        (MCPResponseError(status_code=403), "gmail_delivery_forbidden"),
        (MCPResponseError(status_code=429), "gmail_delivery_rate_limited"),
        (MCPResponseError(status_code=500), "gmail_delivery_provider_error"),
        (MCPResponseError(kind="protocol"), "gmail_delivery_protocol_error"),
        (RuntimeError("provider secret response"), "gmail_delivery_transport_error"),
    ],
)
def test_provider_errors_are_stable_and_redacted(failure, code):
    client = FakeClient(failure=failure)
    with pytest.raises(GmailDeliveryError, match=f"^{code}$") as raised:
        deliver(gateway(client))
    assert "secret" not in str(raised.value) and client.closed


def test_malformed_provider_payload_is_redacted_and_no_extra_tool_is_called():
    client = FakeClient(responses=[{"emails": [{"id": "not valid id!", "from": "self@example.com", "subject": SUBJECT, "date": DATE}]}])
    with pytest.raises(GmailDeliveryError, match="^gmail_delivery_protocol_invalid$"):
        deliver(gateway(client))
    assert [name for name, _ in client.calls] == ["search_emails"]


@pytest.mark.parametrize("sender", [None, "other@example.com", "Name <other@example.com>"])
def test_search_result_must_prove_sender_is_configured_self(sender):
    client = FakeClient(responses=[{"emails": [{"id": "message-1", "from": sender, "subject": SUBJECT, "date": DATE}]}])
    with pytest.raises(GmailDeliveryError, match="^gmail_delivery_search_identity_unverified$") as raised:
        deliver(gateway(client))
    assert "other@example" not in str(raised.value)
    assert [name for name, _ in client.calls] == ["search_emails"]


def test_search_result_must_also_prove_the_full_subject():
    client = FakeClient(responses=[{"emails": [{"id": "message-1", "from": "self@example.com", "subject": "other", "date": DATE}]}])
    with pytest.raises(GmailDeliveryError, match="^gmail_delivery_search_identity_unverified$"):
        deliver(gateway(client))
    assert [name for name, _ in client.calls] == ["search_emails"]


def test_actual_package_text_forms_are_parsed_strictly():
    client = FakeClient(responses=[
        "",
        "Email sent successfully with ID: sent-1",
        "Successfully found existing label:\nID: label-1\nName: TrainLab\nType: user",
        "Email sent-1 labels updated successfully",
    ])
    receipt = deliver(gateway(client))
    assert receipt.status == "sent" and receipt.provider_message_id == "sent-1"


def test_actual_search_text_requires_final_newline_and_rfc_date():
    client = FakeClient(responses=[f"ID: message-1\nSubject: {SUBJECT}\nFrom: TrainLab <self@example.com>\nDate: {DATE}\n", "Successfully found existing label:\nID: label-1\nName: TrainLab\nType: user", "Email message-1 labels updated successfully"])
    receipt = deliver(gateway(client))
    assert receipt.status == "already_sent" and receipt.provider_sent_at_utc == "2026-07-24T00:00:00Z"


def test_reconcile_never_sends_and_returns_typed_not_found():
    client = FakeClient(responses=[""])
    receipt = gateway(client).reconcile(subject=SUBJECT, idempotency_key="analysis-delivery:v1:abc")
    assert receipt.status == "not_found" and [name for name, _ in client.calls] == ["search_emails"]


def test_send_uncertainty_and_existing_label_failure_carry_safe_evidence():
    client = FakeClient(responses=[""], failure=None)
    # Make only the send call fail; the search must remain successful.
    original = client.call_tool
    def fail_send(name, arguments):
        if name == "send_email":
            raise TimeoutError("secret")
        return original(name, arguments)
    client.call_tool = fail_send  # type: ignore[method-assign]
    with pytest.raises(GmailDeliveryError) as raised:
        deliver(gateway(client))
    assert raised.value.code == "gmail_delivery_timeout" and raised.value.may_have_sent is True and raised.value.provider_message_id is None

    existing = FakeClient(responses=[{"emails": [{"id": "message-1", "from": "self@example.com", "subject": SUBJECT, "date": DATE}]}])
    with pytest.raises(GmailDeliveryError) as labeled:
        deliver(gateway(existing))
    assert labeled.value.may_have_sent is True and labeled.value.provider_message_id == "message-1"
