from __future__ import annotations

from types import SimpleNamespace

from trainlab.orchestration.operational_gmail import (
    CurrentEnvironmentOperationalGmail,
)


class Gateway:
    def __init__(self):
        self.calls = []

    def reconcile(self, **values):
        self.calls.append(("reconcile", values))
        return SimpleNamespace(status="not_found", provider_message_id=None)

    def deliver(self, **values):
        self.calls.append(("deliver", values))
        return SimpleNamespace(status="sent", provider_message_id="message-1")


def test_adapter_has_no_arbitrary_binding_or_recipient_surface() -> None:
    adapter = object.__new__(CurrentEnvironmentOperationalGmail)
    adapter._gateway = Gateway()
    adapter._last_delivery_message_id = None
    assert not adapter.search_alert(idempotency_key="ops-key", subject="[TrainLab] ops-key")
    result = adapter.send_html(
        recipient="configured@example.com", idempotency_key="ops-key",
        subject="[TrainLab] ops-key", html="<p>safe</p>",
    )
    assert result == {"provider_message_id": "message-1"}
    adapter.apply_trainlab_label("message-1")
    assert [name for name, _ in adapter._gateway.calls] == ["reconcile", "deliver"]
