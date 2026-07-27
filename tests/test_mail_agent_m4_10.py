from __future__ import annotations

import pytest

from trainlab.mail_agent.delivery import (
    AcceptedDeliveryTarget,
    MailDeliveryError,
    MailResponseDeliveryService,
)
from trainlab.mail_agent.gmail_adapter import GmailAdapterError, SendReceipt
from trainlab.mail_agent.renderer import MailRenderError, render_mail_response


def target(**changes: object) -> AcceptedDeliveryTarget:
    value: dict[str, object] = {
        "subject_id": 7,
        "response_artifact_id": 23,
        "response_kind": "mail_reply",
        "user_visible_text": "你好 <script>alert(1)</script>\n第二行",
        "delivery_id": 99,
        "idempotency_key": "mail:response:23:thread-7",
        "provider_thread_id": "thread-7",
        "delivery_status": "pending",
        "thread_verified": True,
        "authenticated_self_verified": True,
    }
    value.update(changes)
    return AcceptedDeliveryTarget(**value)  # type: ignore[arg-type]


class Store:
    def __init__(self, value: AcceptedDeliveryTarget | None = None) -> None:
        self.value = value or target()
        self.calls: list[tuple] = []

    def load_accepted_delivery_target(self, *, subject_id: int, response_artifact_id: int):
        self.calls.append(("load", subject_id, response_artifact_id))
        return self.value

    def mark_delivery_sending(self, value): self.calls.append(("sending", value.delivery_id))
    def mark_delivery_sent(self, value, **kwargs): self.calls.append(("sent", value.delivery_id, kwargs))
    def mark_delivery_unknown(self, value, **kwargs): self.calls.append(("unknown", value.delivery_id, kwargs))
    def mark_label_pending(self, value, **kwargs): self.calls.append(("label_pending", value.delivery_id, kwargs))
    def mark_delivery_conflict(self, value, **kwargs): self.calls.append(("conflict", value.delivery_id, kwargs))


class Adapter:
    def __init__(self, *, matches=(), receipt=None, search_error=None, send_error=None, label_error=None) -> None:
        self.matches = tuple(matches); self.receipt = receipt or SendReceipt("message-1", "thread-7", False)
        self.search_error = search_error; self.send_error = send_error; self.label_error = label_error
        self.calls: list[tuple] = []

    def search_run_id(self, *, run_id: str, max_results: int = 10):
        self.calls.append(("search", run_id, max_results))
        if self.search_error: raise self.search_error
        return self.matches

    def send_html_self(self, **kwargs):
        self.calls.append(("send", kwargs))
        if self.send_error: raise self.send_error
        return self.receipt

    def apply_trainlab_label(self, **kwargs):
        self.calls.append(("label", kwargs))
        if self.label_error: raise self.label_error


def service(store=None, adapter=None):
    return MailResponseDeliveryService(store or Store(), adapter or Adapter())


def test_renderer_is_deterministic_plaintext_only_and_inert_html() -> None:
    first = render_mail_response(response_artifact_id=23, response_kind="mail_reply", user_visible_text="a <script>x</script>\n&", delivery_run_id="mail:response:23:thread-7")
    second = render_mail_response(response_artifact_id=23, response_kind="mail_reply", user_visible_text="a <script>x</script>\n&", delivery_run_id="mail:response:23:thread-7")
    assert first == second
    assert "<script>" not in first.html and "&lt;script&gt;" in first.html
    assert "javascript:" not in first.html and "onload=" not in first.html
    assert first.requested_message_id.startswith("<trainlab.")


@pytest.mark.parametrize("kwargs", (
    {"response_artifact_id": 0},
    {"response_kind": "bad\r\nBcc:x"},
    {"user_visible_text": "\r\n"},
    {"delivery_run_id": "bad\nvalue"},
))
def test_renderer_rejects_untrusted_metadata(kwargs) -> None:
    values = dict(response_artifact_id=23, response_kind="mail_reply", user_visible_text="ok", delivery_run_id="mail:response:23:thread-7")
    values.update(kwargs)
    with pytest.raises(MailRenderError):
        render_mail_response(**values)


def test_delivery_sends_only_exact_verified_target_and_labels_after_send() -> None:
    store, adapter = Store(), Adapter()
    result = service(store, adapter).deliver(subject_id=7, response_artifact_id=23)
    assert result.status == "sent" and result.next_action == "none"
    assert [call[0] for call in adapter.calls] == ["search", "send", "label"]
    sent = adapter.calls[1][1]
    assert sent["thread_id"] == "thread-7" and sent["run_id"] == "mail:response:23:thread-7"
    assert "<script>" not in sent["html"]
    assert [call[0] for call in store.calls] == ["load", "sending", "sent"]


def test_delivery_preflight_existing_message_labels_without_resend() -> None:
    store, adapter = Store(), Adapter(matches=({"message_id": "message-9", "thread_id": "thread-7"},))
    result = service(store, adapter).deliver(subject_id=7, response_artifact_id=23)
    assert result.status == "already_sent"
    assert [call[0] for call in adapter.calls] == ["search", "label"]
    assert [call[0] for call in store.calls] == ["load", "sent"]


def test_label_failure_never_resends_message() -> None:
    store, adapter = Store(), Adapter(label_error=GmailAdapterError("gmail_transport_failed"))
    result = service(store, adapter).deliver(subject_id=7, response_artifact_id=23)
    assert result.status == "label_pending" and result.next_action == "reconcile_delivery"
    assert [call[0] for call in adapter.calls] == ["search", "send", "label"]
    assert [call[0] for call in store.calls] == ["load", "sending", "label_pending"]


def test_send_error_becomes_unknown_without_resend() -> None:
    store, adapter = Store(), Adapter(send_error=GmailAdapterError("gmail_transport_failed"))
    result = service(store, adapter).deliver(subject_id=7, response_artifact_id=23)
    assert result.status == "delivery_unknown" and result.next_action == "reconcile_delivery"
    assert [call[0] for call in adapter.calls] == ["search", "send"]
    assert [call[0] for call in store.calls] == ["load", "sending", "unknown"]


def test_search_or_label_pending_never_authorizes_a_second_send() -> None:
    store, adapter = Store(), Adapter(search_error=GmailAdapterError("gmail_transport_failed"))
    result = service(store, adapter).deliver(subject_id=7, response_artifact_id=23)
    assert result.status == "delivery_unknown"
    assert [call[0] for call in adapter.calls] == ["search"]
    assert [call[0] for call in store.calls] == ["load", "unknown"]
    pending, second_adapter = Store(target(delivery_status="label_pending")), Adapter()
    result = service(pending, second_adapter).deliver(subject_id=7, response_artifact_id=23)
    assert result.status == "label_pending" and second_adapter.calls == []


@pytest.mark.parametrize("matches,code", (
    (({"message_id": "a", "thread_id": "thread-7"}, {"message_id": "b", "thread_id": "thread-7"}), "duplicate_delivery_conflict"),
    (({"message_id": "a", "thread_id": "other"},), "delivery_preflight_mismatch"),
))
def test_ambiguous_or_mismatched_preflight_never_sends(matches, code) -> None:
    store, adapter = Store(), Adapter(matches=matches)
    result = service(store, adapter).deliver(subject_id=7, response_artifact_id=23)
    assert result.status == "rejected" and result.error_code == code
    assert [call[0] for call in adapter.calls] == ["search"]
    assert store.calls[-1] == ("conflict", 99, {"error_code": code})


def test_existing_unknown_is_reconcile_only_and_invalid_target_is_rejected() -> None:
    unknown = Store(target(delivery_status="delivery_unknown")); adapter = Adapter()
    assert service(unknown, adapter).deliver(subject_id=7, response_artifact_id=23).next_action == "reconcile_delivery"
    assert adapter.calls == []
    with pytest.raises(MailDeliveryError, match="mail_delivery_target_invalid"):
        service(Store(target(thread_verified=False)), Adapter()).deliver(subject_id=7, response_artifact_id=23)
