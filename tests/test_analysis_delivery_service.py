from __future__ import annotations

from types import SimpleNamespace

from trainlab.analysis.delivery_service import AnalysisDeliveryService
from trainlab.analysis.gmail_delivery import GmailDeliveryError, GmailDeliveryReceipt


NOW = "2026-07-26T00:00:00Z"


class Repository:
    def __init__(self, status: str = "pending"):
        self.state = SimpleNamespace(
            delivery_id=1, subject_id=2, analysis_run_id=3, status=status,
            provider_message_id=None, provider_thread_id=None,
            sent_at_utc=None, last_verified_at_utc=None,
            error_code=None, error_summary=None,
        )
        self.calls = []

    def load_pending(self, delivery_id):
        assert delivery_id == 1
        return SimpleNamespace(
            delivery_id=1, subject_id=2, idempotency_key="analysis-delivery:v1:key"
        )

    def read_state(self, delivery_id, subject_id=None):
        assert delivery_id == 1 and subject_id == 2
        return self.state

    def load_rendered(self, delivery_id, subject_id=None):
        assert delivery_id == 1 and subject_id == 2
        return SimpleNamespace(subject="[TrainLab] analysis-delivery:v1:key", plain_text="plain", html="<p>html</p>")

    def _set(self, status, **values):
        for key, value in {"status": status, **values}.items():
            setattr(self.state, key, value)
        return self.state

    def claim_for_send(self, subject_id, delivery_id):
        self.calls.append("claim")
        return self._set("sending")

    def record_sent(self, subject_id, delivery_id, **values):
        self.calls.append("sent")
        return self._set("sent", **values)

    def record_search_match(self, subject_id, delivery_id, **values):
        self.calls.append("match")
        return self._set("already_sent", **values)

    def record_failed(self, subject_id, delivery_id, *, error_code):
        self.calls.append("failed")
        return self._set("failed", error_code=error_code)

    def record_delivery_unknown(self, subject_id, delivery_id, **values):
        self.calls.append("unknown")
        return self._set("delivery_unknown", **values)


class Gateway:
    def __init__(self, result=None, error=None, reconcile=None):
        self.result, self.error, self.reconcile_result = result, error, reconcile
        self.calls = []

    def deliver(self, **kwargs):
        self.calls.append(("deliver", kwargs))
        if self.error:
            raise self.error
        return self.result

    def reconcile(self, **kwargs):
        self.calls.append(("reconcile", kwargs))
        if self.error:
            raise self.error
        return self.reconcile_result


def service(repo, gateway):
    return AnalysisDeliveryService(repo, gateway, clock=lambda: NOW)


def test_retry_sends_exact_rendered_delivery_and_records_provider_evidence():
    repo = Repository()
    gateway = Gateway(GmailDeliveryReceipt("sent", "message-1", None, "label-1", None))
    result = service(repo, gateway).execute(1, "retry_delivery")
    assert result.status == "sent" and result.next_action == "none"
    assert repo.calls == ["claim", "sent"]
    assert gateway.calls[0][1]["idempotency_key"] == "analysis-delivery:v1:key"


def test_search_match_records_already_sent_with_provider_date():
    repo = Repository()
    gateway = Gateway(GmailDeliveryReceipt("already_sent", "message-1", None, "label-1", NOW))
    result = service(repo, gateway).execute(1, "retry_delivery")
    assert result.status == "already_sent" and repo.calls == ["claim", "match"]


def test_pre_send_failure_is_retryable_but_send_ambiguity_is_reconcile_only():
    repo = Repository()
    result = service(repo, Gateway(error=GmailDeliveryError("gmail_delivery_auth_required"))).execute(1, "retry_delivery")
    assert result.status == "failed" and result.next_action == "retry_delivery"

    repo = Repository()
    error = GmailDeliveryError("gmail_delivery_timeout", may_have_sent=True)
    result = service(repo, Gateway(error=error)).execute(1, "retry_delivery")
    assert result.status == "delivery_unknown" and result.next_action == "reconcile_delivery"


def test_unknown_retry_never_calls_provider_and_reconcile_not_found_never_sends():
    repo = Repository("delivery_unknown")
    gateway = Gateway()
    assert service(repo, gateway).execute(1, "retry_delivery").next_action == "reconcile_delivery"
    assert gateway.calls == []
    gateway.reconcile_result = GmailDeliveryReceipt("not_found", None, None, None, None)
    result = service(repo, gateway).execute(1, "reconcile_delivery")
    assert result.status == "delivery_unknown"
    assert [name for name, _ in gateway.calls] == ["reconcile"]


def test_reconcile_finds_existing_without_send_and_terminal_is_noop():
    repo = Repository("delivery_unknown")
    gateway = Gateway(reconcile=GmailDeliveryReceipt("already_sent", "message-1", None, "label-1", NOW))
    result = service(repo, gateway).execute(1, "reconcile_delivery")
    assert result.status == "already_sent" and repo.calls == ["match"]
    assert [name for name, _ in gateway.calls] == ["reconcile"]

    repo = Repository("sent")
    gateway = Gateway()
    assert service(repo, gateway).execute(1, "retry_delivery").status == "sent"
    assert gateway.calls == []
