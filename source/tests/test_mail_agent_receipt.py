from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from src.mail_agent.contracts import MailCounts
from src.mail_agent.gmail_adapter import GmailAdapterError
from src.mail_agent.locks import MailWriteLock
from tests.test_mail_agent_m4_04 import NOW, FakePollAdapter, env, message, request


class PrepareFailureAdapter(FakePollAdapter):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error
        self.prepare_calls = 0
        self.close_calls = 0

    def prepare(self, connection: sqlite3.Connection, subject_id: int):
        self.prepare_calls += 1
        raise self.error

    def close(self) -> None:
        self.close_calls += 1


class IdentityMissingAdapter(FakePollAdapter):
    def prepare(self, connection: sqlite3.Connection, subject_id: int):
        return self._identity


def _run_row(conn: sqlite3.Connection, invocation: str) -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM mail_agent_runs WHERE invocation_id=?", (invocation,)
    ).fetchone()
    assert row is not None
    return row


def _assert_request_identity_only(row: sqlite3.Row, poll_request: object) -> None:
    assert json.loads(row["context_snapshot_json"]) == {
        "mail_request_identity": poll_request.to_dict()
    }


def test_receipt_terminal_replay_is_exact_and_provider_noop(tmp_path: Path) -> None:
    raw = {
        "messages": [message("replay-message", "replay-thread", labels=["TrainLab"])]
    }
    adapter = FakePollAdapter(
        label_matches=[{"thread_id": "replay-thread"}], threads={"replay-thread": raw}
    )
    service, conn, subject, _ = env(tmp_path, adapter)
    first = service.execute(request(subject, "replay"))
    provider_calls = (len(adapter.search_calls), len(adapter.read_calls))
    second = service.execute(request(subject, "replay"))
    assert second.json() == first.json()
    assert (len(adapter.search_calls), len(adapter.read_calls)) == provider_calls
    row = _run_row(conn, "replay")
    assert row["status"] == "succeeded" and row["context_snapshot_json"]


def test_unchanged_and_auth_required_preserve_distinct_public_status_on_replay(
    tmp_path: Path,
) -> None:
    adapter = FakePollAdapter()
    service, conn, subject, _ = env(tmp_path / "unchanged", adapter)
    first = service.execute(request(subject, "unchanged"))
    assert first.status == "unchanged"
    assert _run_row(conn, "unchanged")["status"] == "succeeded"
    assert service.execute(request(subject, "unchanged")).json() == first.json()

    auth_adapter = PrepareFailureAdapter(GmailAdapterError("auth_required"))
    auth_service, auth_conn, auth_subject, _ = env(tmp_path / "auth", auth_adapter)
    auth = auth_service.execute(request(auth_subject, "auth"))
    assert (
        auth.status == "auth_required"
        and _run_row(auth_conn, "auth")["status"] == "failed"
    )
    assert auth_service.execute(request(auth_subject, "auth")).json() == auth.json()
    assert auth_adapter.prepare_calls == 1


@pytest.mark.parametrize(
    ("public_status", "db_status"),
    (
        ("succeeded", "succeeded"),
        ("unchanged", "succeeded"),
        ("partial", "partial"),
        ("deferred", "deferred"),
        ("failed", "failed"),
        ("auth_required", "failed"),
    ),
)
def test_all_terminal_public_statuses_commit_and_replay_exactly(
    tmp_path: Path, public_status: str, db_status: str
) -> None:
    service, conn, subject, _ = env(tmp_path / public_status, FakePollAdapter())
    invocation = f"terminal-{public_status}"
    poll_request = request(subject, invocation)
    run = service.repository.start_or_resume_run(poll_request)
    windows = (
        {
            "stream": "trainlab_label",
            "status": "succeeded",
            "window_start_utc": NOW,
            "window_end_utc": NOW,
        },
        {
            "stream": "tracked_threads",
            "status": "succeeded",
            "window_start_utc": NOW,
            "window_end_utc": NOW,
        },
    )
    counts, states, errors, retry = MailCounts(), windows, (), None
    if public_status == "partial":
        counts = MailCounts(deferred=1)
        states = ({**windows[0], "status": "partial"}, windows[1])
        errors = (
            {"stage": "discover", "code": "max_threads_reached", "summary": "ignored"},
        )
    elif public_status == "deferred":
        counts = MailCounts(deferred=1)
        states = ()
        errors = (
            {"stage": "discover", "code": "max_threads_reached", "summary": "ignored"},
        )
        retry = "2026-07-23T08:00:00Z"
    elif public_status == "auth_required":
        counts = MailCounts(failed=1)
        states = ()
        errors = ({"stage": "prepare", "code": "auth_required", "summary": "ignored"},)
    elif public_status == "failed":
        counts = MailCounts(failed=1)
        states = ()
        errors = ({"stage": "poll", "code": "poll_failed", "summary": "ignored"},)
    receipt = service._persist_terminal(
        poll_request, run.id, public_status, counts, states, (), errors, NOW, retry
    )
    assert (
        receipt.status == public_status
        and _run_row(conn, invocation)["status"] == db_status
    )
    assert service.execute(poll_request).json() == receipt.json()


def test_rejected_receipt_is_not_persistable_before_m4_rejection_publisher(
    tmp_path: Path,
) -> None:
    service, conn, subject, _ = env(tmp_path, FakePollAdapter())
    poll_request = request(subject, "rejected")
    run = service.repository.start_or_resume_run(poll_request)
    with pytest.raises(Exception):
        service._persist_terminal(
            poll_request,
            run.id,
            "rejected",
            MailCounts(failed=1),
            (),
            (),
            ({"stage": "poll", "code": "poll_failed", "summary": "ignored"},),
            NOW,
        )
    assert _run_row(conn, "rejected")["status"] == "started"


def test_terminal_missing_or_malformed_receipt_fails_closed_without_provider(
    tmp_path: Path,
) -> None:
    adapter = FakePollAdapter()
    service, conn, subject, _ = env(tmp_path, adapter)
    first = service.execute(request(subject, "broken"))
    row = _run_row(conn, "broken")
    snapshot = json.loads(row["context_snapshot_json"])
    snapshot["mail_poll_receipt"] = {"wrong": 1}
    conn.execute(
        "UPDATE mail_agent_runs SET context_snapshot_json=? WHERE invocation_id=?",
        (json.dumps(snapshot), "broken"),
    )
    conn.commit()
    calls = (len(adapter.search_calls), len(adapter.read_calls))
    replay = service.execute(request(subject, "broken"))
    assert first.status == "unchanged"
    assert (
        replay.status == "failed"
        and replay.errors[0]["code"] == "terminal_receipt_invalid"
    )
    assert (len(adapter.search_calls), len(adapter.read_calls)) == calls


@pytest.mark.parametrize(
    "tamper",
    (
        "nested_secret",
        "safe_health_text",
        "poll_state",
        "duplicate_stream",
        "reverse_window",
        "counts",
        "time",
        "unchanged_error",
        "failed_none_action",
        "deferred_all_succeeded",
        "rejected_poll_failed",
        "failed_auth",
        "extra_key",
    ),
)
def test_nested_terminal_receipt_tampering_fails_closed_without_provider(
    tmp_path: Path, tamper: str
) -> None:
    adapter = FakePollAdapter()
    service, conn, subject, _ = env(tmp_path / tamper, adapter)
    assert service.execute(request(subject, "tampered")).status == "unchanged"
    row = _run_row(conn, "tampered")
    snapshot = json.loads(row["context_snapshot_json"])
    receipt = snapshot["mail_poll_receipt"]
    if tamper == "nested_secret":
        receipt["errors"] = [
            {"stage": "poll", "code": "poll_failed", "summary": "secret@example.com"}
        ]
    elif tamper == "safe_health_text":
        receipt["errors"] = [
            {
                "stage": "poll",
                "code": "poll_failed",
                "summary": "ÅLÎÇÉ weighs 55kg private health details",
            }
        ]
    elif tamper == "poll_state":
        receipt["poll_state"] = [
            {
                "stream": "evil",
                "status": "succeeded",
                "window_start_utc": NOW,
                "window_end_utc": NOW,
            }
        ]
    elif tamper == "duplicate_stream":
        receipt["poll_state"] = [
            {
                "stream": "trainlab_label",
                "status": "succeeded",
                "window_start_utc": NOW,
                "window_end_utc": NOW,
            },
            {
                "stream": "trainlab_label",
                "status": "succeeded",
                "window_start_utc": NOW,
                "window_end_utc": NOW,
            },
        ]
    elif tamper == "reverse_window":
        receipt["poll_state"] = [
            {
                "stream": "trainlab_label",
                "status": "succeeded",
                "window_start_utc": "2026-07-23T08:00:00Z",
                "window_end_utc": NOW,
            },
            {
                "stream": "tracked_threads",
                "status": "succeeded",
                "window_start_utc": NOW,
                "window_end_utc": NOW,
            },
        ]
    elif tamper == "counts":
        receipt["counts"]["unknown"] = 1
    elif tamper == "time":
        receipt["completed_at_utc"] = "2026-07-23T07:00:00+00:00"
    elif tamper == "unchanged_error":
        receipt["errors"] = [
            {"stage": "poll", "code": "poll_failed", "summary": "poll did not complete"}
        ]
    elif tamper == "failed_none_action":
        receipt["status"] = "failed"
        receipt["counts"] = {**receipt["counts"], "failed": 1}
        receipt["poll_state"] = []
        receipt["errors"] = [
            {"stage": "poll", "code": "poll_failed", "summary": "poll did not complete"}
        ]
        receipt["next_action"] = "none"
    elif tamper == "deferred_all_succeeded":
        receipt["status"] = "deferred"
        receipt["counts"] = {**receipt["counts"], "deferred": 1}
        receipt["errors"] = [
            {
                "stage": "discover",
                "code": "rate_limited",
                "summary": "label discovery failed",
            }
        ]
        receipt["next_action"] = "continue_poll"
        receipt["next_retry_at_utc"] = "2026-07-23T08:00:00Z"
    elif tamper == "rejected_poll_failed":
        receipt["status"] = "rejected"
        receipt["counts"] = {**receipt["counts"], "failed": 1}
        receipt["poll_state"] = []
        receipt["errors"] = [
            {"stage": "poll", "code": "poll_failed", "summary": "poll did not complete"}
        ]
        receipt["next_action"] = "operator_review"
    elif tamper == "failed_auth":
        receipt["status"] = "failed"
        receipt["counts"] = {**receipt["counts"], "failed": 1}
        receipt["poll_state"] = []
        receipt["errors"] = [
            {
                "stage": "prepare",
                "code": "auth_required",
                "summary": "gmail adapter unavailable",
            }
        ]
        receipt["next_action"] = "operator_review"
    else:
        receipt["extra"] = "body"
    conn.execute(
        "UPDATE mail_agent_runs SET context_snapshot_json=? WHERE id=?",
        (json.dumps(snapshot), row["id"]),
    )
    conn.commit()
    calls = (len(adapter.search_calls), len(adapter.read_calls))
    replay = service.execute(request(subject, "tampered"))
    assert (
        replay.status == "failed"
        and replay.errors[0]["code"] == "terminal_receipt_invalid"
    )
    assert (len(adapter.search_calls), len(adapter.read_calls)) == calls
    assert (
        "secret@example.com" not in replay.json()
        and "55kg" not in replay.json()
        and "ÅLÎÇÉ" not in replay.json()
    )


@pytest.mark.parametrize(
    "error,status",
    (
        (RuntimeError("secret@example.com https://bad.invalid"), "failed"),
        (GmailAdapterError("auth_required"), "auth_required"),
    ),
)
def test_prepare_and_normal_errors_are_terminal_and_sanitized(
    tmp_path: Path, error: Exception, status: str
) -> None:
    adapter = PrepareFailureAdapter(error)
    service, conn, subject, _ = env(tmp_path, adapter)
    receipt = service.execute(request(subject, f"prepare-{status}"))
    row = _run_row(conn, f"prepare-{status}")
    assert (
        receipt.status == status
        and row["status"] == "failed"
        and row["completed_at_utc"]
    )
    assert (
        "secret@example.com" not in receipt.json()
        and "https://bad.invalid" not in receipt.json()
    )


def test_unknown_adapter_code_is_replaced_before_receipt_or_db_write(
    tmp_path: Path,
) -> None:
    marker = "provider_secret_token_abc"
    adapter = PrepareFailureAdapter(GmailAdapterError(marker))
    service, conn, subject, _ = env(tmp_path, adapter)
    receipt = service.execute(request(subject, "unknown-code"))
    row = _run_row(conn, "unknown-code")
    assert (
        receipt.status == "failed"
        and receipt.errors[0]["code"] == "gmail_adapter_failed"
    )
    assert marker not in receipt.json() and marker not in row["context_snapshot_json"]


def test_repository_rejects_nested_receipt_and_rolls_back_to_started(
    tmp_path: Path,
) -> None:
    service, conn, subject, _ = env(tmp_path, FakePollAdapter())
    poll_request = request(subject, "repository-reject")
    run = service.repository.start_or_resume_run(poll_request)
    receipt = service._receipt(
        poll_request,
        "failed",
        MailCounts(failed=1),
        (),
        (),
        ({"stage": "poll", "code": "poll_failed", "summary": "poll did not complete"},),
        NOW,
        run.id,
    ).to_dict()
    receipt["errors"] = [{"private": "secret@example.com"}]
    with pytest.raises(Exception):
        service.repository.finish_poll_with_receipt(run.id, "failed", receipt)
    row = _run_row(conn, "repository-reject")
    assert row["status"] == "started"
    _assert_request_identity_only(row, poll_request)


@pytest.mark.parametrize(
    "case", ("deferred_all_succeeded", "rejected_poll_failed", "failed_auth")
)
def test_repository_rejects_semantic_terminal_contradictions_and_rolls_back(
    tmp_path: Path, case: str
) -> None:
    service, conn, subject, _ = env(tmp_path / case, FakePollAdapter())
    poll_request = request(subject, "semantic-reject")
    run = service.repository.start_or_resume_run(poll_request)
    if case == "deferred_all_succeeded":
        states = (
            {
                "stream": "trainlab_label",
                "status": "succeeded",
                "window_start_utc": NOW,
                "window_end_utc": NOW,
            },
            {
                "stream": "tracked_threads",
                "status": "succeeded",
                "window_start_utc": NOW,
                "window_end_utc": NOW,
            },
        )
        receipt = service._receipt(
            poll_request,
            "deferred",
            MailCounts(deferred=1),
            states,
            (),
            ({"stage": "discover", "code": "rate_limited", "summary": "ignored"},),
            NOW,
            run.id,
            "2026-07-23T08:00:00Z",
        ).to_dict()
        db_status = "deferred"
    else:
        receipt = service._receipt(
            poll_request,
            "failed",
            MailCounts(failed=1),
            (),
            (),
            ({"stage": "poll", "code": "poll_failed", "summary": "ignored"},),
            NOW,
            run.id,
        ).to_dict()
        db_status = "rejected" if case == "rejected_poll_failed" else "failed"
        if case == "rejected_poll_failed":
            receipt["status"] = "rejected"
        else:
            receipt["errors"] = [
                {
                    "stage": "prepare",
                    "code": "auth_required",
                    "summary": "gmail adapter unavailable",
                }
            ]
    with pytest.raises(Exception):
        service.repository.finish_poll_with_receipt(run.id, db_status, receipt)
    row = _run_row(conn, "semantic-reject")
    assert row["status"] == "started"
    _assert_request_identity_only(row, poll_request)


def test_identity_missing_is_terminal_with_receipt(tmp_path: Path) -> None:
    service, conn, subject, _ = env(tmp_path, IdentityMissingAdapter())
    receipt = service.execute(request(subject, "identity-missing"))
    assert (
        receipt.status == "failed"
        and receipt.errors[0]["code"] == "verified_identity_required"
    )
    assert _run_row(conn, "identity-missing")["status"] == "failed"


def test_terminal_persistence_failure_never_creates_terminal_without_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FakePollAdapter()
    service, conn, subject, _ = env(tmp_path, adapter)
    original = service.repository.finish_poll_with_receipt

    def fail(*_args: object, **_kwargs: object):
        raise sqlite3.OperationalError("receipt transaction failed")

    monkeypatch.setattr(service.repository, "finish_poll_with_receipt", fail)
    poll_request = request(subject, "finish-fail")
    receipt = service.execute(poll_request)
    row = _run_row(conn, "finish-fail")
    assert receipt.status == "failed" and row["status"] == "started"
    _assert_request_identity_only(row, poll_request)
    monkeypatch.setattr(service.repository, "finish_poll_with_receipt", original)


def test_close_error_cannot_overwrite_committed_terminal_receipt(
    tmp_path: Path,
) -> None:
    adapter = FakePollAdapter()
    adapter.close = lambda: (_ for _ in ()).throw(RuntimeError("close provider secret"))  # type: ignore[method-assign]
    service, conn, subject, _ = env(tmp_path, adapter)
    receipt = service.execute(request(subject, "close"))
    assert receipt.status == "unchanged"
    assert _run_row(conn, "close")["status"] == "succeeded"


def test_release_error_cannot_overwrite_committed_terminal_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, conn, subject, _ = env(tmp_path, FakePollAdapter())
    original_release = MailWriteLock.release

    def release_then_fail(lock: MailWriteLock) -> None:
        original_release(lock)
        raise RuntimeError("release failure")

    monkeypatch.setattr(MailWriteLock, "release", release_then_fail)
    before = len(os.listdir("/dev/fd"))
    receipt = service.execute(request(subject, "release"))
    assert (
        receipt.status == "unchanged"
        and _run_row(conn, "release")["status"] == "succeeded"
    )
    assert len(os.listdir("/dev/fd")) <= before + 1
