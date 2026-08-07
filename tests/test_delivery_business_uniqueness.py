from __future__ import annotations

import sqlite3

import pytest

from trainlab.analysis.delivery import (
    AnalysisDeliveryError,
    AnalysisDeliveryFactory,
    ResendAuthorization,
)
from trainlab.mail_agent.delivery import (
    AcceptedDeliveryTarget,
    MailResponseDeliveryService,
)
from trainlab.orchestration.incident_alerts import alert_idempotency_key

from .test_analysis_a3_14 import database, published


def _next_run_with_same_business_dates(
    connection: sqlite3.Connection, *, delivery_kind: str
) -> dict[str, object]:
    rows = connection.execute("SELECT * FROM analysis_artifacts ORDER BY id").fetchall()
    connection.execute(
        "INSERT INTO analysis_runs(id,run_key,subject_id,analysis_kind,status) "
        "VALUES(2,?,1,?,'started')",
        (f"analysis:1:{delivery_kind}:repeat", delivery_kind),
    )
    artifact_ids: dict[str, int] = {}
    kinds = (
        ("daily_summary", "daily_training_advice")
        if delivery_kind == "daily_report"
        else ("weekly_summary", "weekly_training_plan")
    )
    for source, kind in zip(rows, kinds, strict=True):
        cursor = connection.execute(
            "INSERT INTO analysis_artifacts(subject_id,artifact_kind,period_start_local_date,"
            "period_end_local_date,revision_no,generated_by_run_id,schema_version,"
            "structured_content_json,user_visible_text,content_sha256,is_current,"
            "supersedes_artifact_id,created_at_utc) VALUES(?,?,?,?,?,2,?,?,?,?,?,?,?)",
            (
                1,
                kind,
                source["period_start_local_date"],
                source["period_end_local_date"],
                2,
                source["schema_version"],
                source["structured_content_json"],
                source["user_visible_text"],
                source["content_sha256"],
                0,
                source["id"],
                source["created_at_utc"],
            ),
        )
        artifact_ids[kind] = int(cursor.lastrowid)
    connection.commit()
    return {"run_id": 2, "artifact_ids": artifact_ids}


def test_daily_first_and_duplicate_share_one_subject_and_logical_date_delivery() -> (
    None
):
    connection = database()
    first_receipt = published(connection)
    factory = AnalysisDeliveryFactory(connection)
    first = factory.create_pending(
        publish_receipt=first_receipt, delivery_kind="daily_report"
    )
    repeated = factory.create_pending(
        publish_receipt=_next_run_with_same_business_dates(
            connection, delivery_kind="daily_report"
        ),
        delivery_kind="daily_report",
    )
    assert repeated.delivery_id == first.delivery_id
    assert repeated.analysis_run_id == first.analysis_run_id
    assert repeated.idempotency_key == first.idempotency_key
    assert (
        connection.execute("SELECT count(*) FROM analysis_deliveries").fetchone()[0]
        == 1
    )


def test_weekly_first_and_duplicate_share_one_subject_and_logical_date_delivery() -> (
    None
):
    connection = database()
    # Reuse safe fixture content: delivery uniqueness is about formal dates,
    # ownership and roles, not a second model invocation.
    published(connection)
    weekly_first = _next_run_with_same_business_dates(
        connection, delivery_kind="weekly_report"
    )
    factory = AnalysisDeliveryFactory(connection)
    first = factory.create_pending(
        publish_receipt=weekly_first, delivery_kind="weekly_report"
    )
    connection.execute("DELETE FROM analysis_artifacts WHERE generated_by_run_id=2")
    connection.execute("DELETE FROM analysis_runs WHERE id=2")
    connection.commit()
    repeated_receipt = _next_run_with_same_business_dates(
        connection, delivery_kind="weekly_report"
    )
    repeated = factory.create_pending(
        publish_receipt=repeated_receipt, delivery_kind="weekly_report"
    )
    assert repeated.delivery_id == first.delivery_id
    assert repeated.analysis_run_id == first.analysis_run_id


def test_unauthorized_resend_reuses_original_without_provider_permission() -> None:
    connection = database()
    factory = AnalysisDeliveryFactory(connection)
    first = factory.create_pending(
        publish_receipt=published(connection), delivery_kind="daily_report"
    )
    rejected = factory.create_pending(
        publish_receipt=_next_run_with_same_business_dates(
            connection, delivery_kind="daily_report"
        ),
        delivery_kind="daily_report",
    )
    assert rejected.delivery_id == first.delivery_id
    assert (
        connection.execute("SELECT count(*) FROM analysis_deliveries").fetchone()[0]
        == 1
    )


def test_authorized_resend_has_immutable_explicit_audit_key() -> None:
    connection = database()
    factory = AnalysisDeliveryFactory(connection)
    factory.create_pending(
        publish_receipt=published(connection), delivery_kind="daily_report"
    )
    receipt = _next_run_with_same_business_dates(
        connection, delivery_kind="daily_report"
    )
    authorization = ResendAuthorization("user-confirmed-20260807")
    resend = factory.create_pending(
        publish_receipt=receipt,
        delivery_kind="daily_report",
        resend_authorization=authorization,
    )
    replay = factory.create_pending(
        publish_receipt=receipt,
        delivery_kind="daily_report",
        resend_authorization=authorization,
    )
    assert replay.delivery_id == resend.delivery_id
    assert resend.idempotency_key.endswith(":resend:user-confirmed-20260807")
    assert (
        connection.execute("SELECT count(*) FROM analysis_deliveries").fetchone()[0]
        == 2
    )
    empty = database()
    empty_receipt = published(empty)
    with pytest.raises(AnalysisDeliveryError, match="resend_not_required"):
        AnalysisDeliveryFactory(empty).create_pending(
            publish_receipt=empty_receipt,
            delivery_kind="daily_report",
            resend_authorization=authorization,
        )


def test_ops_open_and_recovery_keys_are_distinct_event_scoped_business_keys() -> None:
    incident = "workflow:failed:morning:fixed"
    assert alert_idempotency_key(incident, "open") == alert_idempotency_key(
        incident, "open"
    )
    assert alert_idempotency_key(incident, "recovery") == alert_idempotency_key(
        incident, "recovery"
    )
    assert alert_idempotency_key(incident, "open") != alert_idempotency_key(
        incident, "recovery"
    )


class _NoProviderStore:
    def load_accepted_delivery_target(self, **_kwargs):
        return AcceptedDeliveryTarget(
            subject_id=1,
            response_artifact_id=2,
            response_kind="reply",
            user_visible_text="safe",
            delivery_id=3,
            idempotency_key="mail:response:2:thread-1",
            provider_thread_id="thread-1",
            in_reply_to_provider_message_id="message-1",
            delivery_status="failed",
            thread_verified=True,
            authenticated_self_verified=True,
        )


class _NoProviderAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def search_run_id(self, **_kwargs):
        self.calls += 1
        raise AssertionError("provider I/O is forbidden for unauthorized resend")

    def send_html_recipient(self, **_kwargs):
        self.calls += 1
        raise AssertionError("provider I/O is forbidden for unauthorized resend")

    def apply_trainlab_label(self, **_kwargs):
        self.calls += 1
        raise AssertionError("provider I/O is forbidden for unauthorized resend")


def test_unauthorized_mail_resend_is_rejected_before_any_provider_io() -> None:
    adapter = _NoProviderAdapter()
    result = MailResponseDeliveryService(_NoProviderStore(), adapter).deliver(
        subject_id=1, response_artifact_id=2
    )
    assert (result.status, result.error_code, adapter.calls) == (
        "rejected",
        "mail_delivery_state_not_sendable",
        0,
    )
