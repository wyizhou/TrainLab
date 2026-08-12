from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.mail_agent.contracts import MailRequest
from trainlab.mail_agent.gmail_adapter import GmailIdentity, GmailMessage, GmailThread, GmailThreadEvidence
from trainlab.mail_agent.poll import MailPollConfig, MailPollService
from trainlab.mail_agent.repository import MailRepository


NOW = "2026-07-23T07:00:00Z"


def _hmac(value: str) -> str:
    return hmac.new(b"m4-04", value.encode(), hashlib.sha256).hexdigest()


def message(message_id: str = "m1", thread_id: str = "t1", *, body: str = "hello", labels: list[str] | None = None, when: str = "2026-07-22T08:00:00Z", html: str | None = None) -> dict:
    value = {
        "message_id": message_id, "thread_id": thread_id, "internal_date_utc": when,
        "from": "self@example.com", "to": ["self@example.com"], "subject": "TrainLab",
        "headers": {"message_id": f"<{message_id}>"}, "label_ids": labels or [],
        "plain_text": body, "has_html": html is not None, "attachments": [{"attachment_id": "a1", "filename": "x.pdf", "mime_type": "application/pdf", "size": 10}],
    }
    if html is not None: value["html"] = html
    return value


class FakePollAdapter:
    def __init__(self, *, label_matches: list[dict] | None = None, threads: dict[str, dict] | None = None, fail_threads: set[str] | None = None, page_limit: bool = False) -> None:
        self.label_matches = label_matches or []
        self.threads = threads or {}
        self.fail_threads = fail_threads or set()
        self.page_limit = page_limit
        self._identity = GmailIdentity("self@example.com")
        self.verified_identity_id: int | None = None
        self.search_calls: list[tuple[datetime, datetime]] = []
        self.read_calls: list[str] = []

    @property
    def verified_identity(self): return self._identity

    def prepare(self, connection: sqlite3.Connection, subject_id: int) -> GmailIdentity:
        self.verified_identity_id = connection.execute("SELECT id FROM subject_identities WHERE subject_id=?", (subject_id,)).fetchone()[0]
        return self._identity

    def close(self) -> None: pass

    def search_trainlab_window(self, *, start_date: datetime, end_date: datetime, max_results: int):
        self.search_calls.append((start_date, end_date))
        if self.page_limit:
            return [{"thread_id": f"t{i}"} for i in range(max_results)]
        return self.label_matches

    def read_thread_evidence(self, thread_id: str) -> GmailThreadEvidence:
        self.read_calls.append(thread_id)
        if thread_id in self.fail_threads:
            raise RuntimeError("provider payload secret")
        raw = self.threads[thread_id]
        values = []
        for item in raw["messages"]:
            headers = item.get("headers", {})
            values.append(GmailMessage(str(item["message_id"]), str(item["thread_id"]), item.get("internal_date_utc"), item.get("from"), tuple(item.get("to", [])), item.get("subject"), headers.get("message_id"), headers.get("in_reply_to"), tuple(headers.get("references", [])), headers.get("x_trainlab_run_id"), tuple(item.get("label_ids", [])), item.get("plain_text", ""), bool(item.get("has_html")), tuple(item.get("attachments", []))))
        return GmailThreadEvidence(GmailThread(thread_id, tuple(values)), raw)


def env(tmp_path: Path, adapter: FakePollAdapter) -> tuple[MailPollService, sqlite3.Connection, int, Path]:
    root = tmp_path / "data"
    config = FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state" / "foundation-ready.json", root / "state" / "locks" / "foundation.lock")
    assert FoundationTool(config).execute(FoundationRequest("init", "m4-04", NOW)).status == "initialized"
    conn = sqlite3.connect(root / "data.db"); conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("INSERT INTO data_subjects(subject_key,created_at_utc) VALUES('subject',?)", (NOW,)); subject = conn.execute("SELECT id FROM data_subjects").fetchone()[0]
    conn.execute("INSERT INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) VALUES(?, 'gmail','email',?,1,?,?)", (subject, _hmac("self@example.com"), NOW, NOW)); conn.commit()
    service = MailPollService(MailRepository(conn, clock=lambda: NOW), adapter, MailPollConfig(root / "raw", root / "state" / "locks" / "mail.lock", provider_page_limit=3), clock=lambda: NOW)
    return service, conn, subject, root


def request(subject: int, invocation: str, *, max_threads: int | None = None) -> MailRequest:
    return MailRequest("poll", subject, invocation, NOW, max_threads=max_threads)


def test_two_streams_archive_normalize_cursor_and_repeat_noop(tmp_path: Path) -> None:
    raw = {"messages": [message("m1", "t1", labels=["TrainLab"])]}
    adapter = FakePollAdapter(label_matches=[{"thread_id": "t1"}], threads={"t1": raw})
    service, conn, subject, root = env(tmp_path, adapter)
    first = service.execute(request(subject, "one"))
    assert first.status == "succeeded" and {row["stream"] for row in first.poll_state} == {"trainlab_label", "tracked_threads"}
    assert conn.execute("SELECT count(*) FROM raw_objects").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM mail_messages").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM mail_poll_cursors").fetchone()[0] == 2
    final = next((root / "raw" / "gmail" / "json").rglob("*.json")); assert final.stat().st_mode & 0o077 == 0
    second = service.execute(request(subject, "two"))
    assert second.status == "unchanged" and second.counts.unchanged >= 1
    assert conn.execute("SELECT count(*) FROM source_revisions").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM raw_objects").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM mail_messages").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM mail_attachments").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM conversation_events").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM user_facts").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM mail_response_artifacts").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM mail_deliveries").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM mail_delivery_artifacts").fetchone()[0] == 0
    assert {tuple(row) for row in conn.execute("SELECT stage,status FROM mail_agent_items")} >= {("discover", "succeeded"), ("archive", "succeeded"), ("normalize", "succeeded")}


def test_initial_window_then_48_hour_overlap_and_max_threads_never_marks_complete(tmp_path: Path) -> None:
    raw = {"messages": [message("m-overlap", "toverlap", labels=["TrainLab"])]}
    adapter = FakePollAdapter(label_matches=[{"thread_id": "toverlap"}], threads={"toverlap": raw})
    service, conn, subject, _ = env(tmp_path, adapter)
    assert service.execute(request(subject, "initial")).status == "succeeded"
    initial_start, initial_end = adapter.search_calls[0]
    assert int((initial_end - initial_start).total_seconds()) == 48 * 3600
    service._clock = lambda: "2026-07-24T07:00:00Z"  # type: ignore[method-assign]
    assert service.execute(MailRequest("poll", subject, "overlap", "2026-07-24T07:00:00Z")).status == "unchanged"
    overlap_start, overlap_end = adapter.search_calls[-1]
    assert overlap_start == datetime(2026, 7, 21, 7, tzinfo=timezone.utc) and overlap_end == datetime(2026, 7, 24, 7, tzinfo=timezone.utc)
    limited = FakePollAdapter(label_matches=[{"thread_id": "toverlap"}], threads={"toverlap": raw})
    limited_service, limited_conn, limited_subject, _ = env(tmp_path / "limited", limited)
    receipt = limited_service.execute(request(limited_subject, "limited", max_threads=0))
    assert receipt.status == "partial" and limited_conn.execute("SELECT count(*) FROM mail_poll_cursors").fetchone()[0] == 1


def test_tracked_reply_without_label_and_one_stream_failure_do_not_cross_cursor(tmp_path: Path) -> None:
    tracked = {"messages": [message("m2", "tracked", labels=[])]}
    adapter = FakePollAdapter(threads={"tracked": tracked}, fail_threads={"tracked"})
    service, conn, subject, _ = env(tmp_path, adapter)
    conn.execute("INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) VALUES(?, 'tracked',1)", (subject,)); conn.commit()
    receipt = service.execute(request(subject, "failure"))
    states = {item["stream"]: item["status"] for item in receipt.poll_state}
    assert receipt.status == "partial" and states == {"trainlab_label": "succeeded", "tracked_threads": "partial"}
    assert conn.execute("SELECT count(*) FROM mail_poll_cursors WHERE stream_kind='trainlab_label'").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM mail_poll_cursors WHERE stream_kind='tracked_threads'").fetchone()[0] == 0


def test_label_page_limit_splits_and_unsplittable_window_is_partial(tmp_path: Path) -> None:
    adapter = FakePollAdapter(page_limit=True)
    service, conn, subject, _ = env(tmp_path, adapter)
    receipt = service.execute(request(subject, "split"))
    assert receipt.status == "partial" and len(adapter.search_calls) > 1
    assert conn.execute("SELECT count(*) FROM mail_poll_cursors WHERE stream_kind='trainlab_label'").fetchone()[0] == 0


def test_full_page_splits_into_complete_subwindows_with_shared_dedupe(tmp_path: Path) -> None:
    raws = {
        "early": {"messages": [message("m-early", "early", labels=["TrainLab"])]},
        "late": {"messages": [message("m-late", "late", labels=["TrainLab"])]},
    }

    class SplitAdapter(FakePollAdapter):
        def search_trainlab_window(self, *, start_date: datetime, end_date: datetime, max_results: int):
            self.search_calls.append((start_date, end_date))
            if int((end_date - start_date).total_seconds()) == 48 * 3600:
                return [{"thread_id": "overflow-1"}, {"thread_id": "overflow-2"}, {"thread_id": "overflow-3"}]
            if end_date <= datetime(2026, 7, 22, 7, tzinfo=timezone.utc):
                return [{"thread_id": "early"}]
            return [{"thread_id": "late"}, {"thread_id": "early"}]

    adapter = SplitAdapter(threads=raws)
    service, conn, subject, _ = env(tmp_path, adapter)
    receipt = service.execute(request(subject, "split-complete"))
    assert receipt.status == "succeeded"
    assert adapter.read_calls == ["early", "late"]
    assert len(adapter.search_calls) == 3
    assert conn.execute(
        "SELECT count(*) FROM mail_poll_cursors WHERE stream_kind='trainlab_label'"
    ).fetchone()[0] == 1


def test_long_cursor_gap_is_split_into_provider_bounded_windows(tmp_path: Path) -> None:
    adapter = FakePollAdapter()
    service, conn, subject, _ = env(tmp_path, adapter)
    identity_id = conn.execute("SELECT id FROM subject_identities").fetchone()[0]
    run = service.repository.start_or_resume_run(
        MailRequest("poll", subject, "cursor-seed", "2026-06-20T07:00:00Z")
    )
    service.repository.advance_poll_cursor(
        run.id,
        subject,
        identity_id,
        "trainlab_label",
        "2026-06-20T07:00:00Z",
        "2026-06-18T07:00:00Z",
    )
    service.repository.finish_run(run.id, "succeeded")
    receipt = service.execute(request(subject, "long-gap"))
    assert receipt.status == "unchanged"
    assert len(adapter.search_calls) > 1
    assert all((end - start).total_seconds() <= 7 * 86_400 for start, end in adapter.search_calls)


def test_stream_stops_after_first_failed_thread_and_does_not_scan_later_items(tmp_path: Path) -> None:
    threads = {
        "a-fails": {"messages": [message("m-a", "a-fails", labels=["TrainLab"])]},
        "b-private": {"messages": [message("m-b", "b-private", labels=["TrainLab"])]},
    }
    adapter = FakePollAdapter(
        label_matches=[{"thread_id": "b-private"}, {"thread_id": "a-fails"}],
        threads=threads,
        fail_threads={"a-fails"},
    )
    service, conn, subject, _ = env(tmp_path, adapter)
    receipt = service.execute(request(subject, "stop-on-failure"))
    assert receipt.status == "partial"
    assert adapter.read_calls == ["a-fails"]
    assert conn.execute(
        "SELECT count(*) FROM mail_poll_cursors WHERE stream_kind='trainlab_label'"
    ).fetchone()[0] == 0


def test_shared_budget_stops_both_streams_without_reading_past_limit(tmp_path: Path) -> None:
    threads = {
        "a": {"messages": [message("m-a", "a", labels=["TrainLab"])]},
        "b": {"messages": [message("m-b", "b", labels=["TrainLab"])]},
    }
    adapter = FakePollAdapter(
        label_matches=[{"thread_id": "b"}, {"thread_id": "a"}],
        threads=threads,
    )
    service, conn, subject, _ = env(tmp_path, adapter)
    conn.execute(
        "INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) VALUES(?, 'a',1)",
        (subject,),
    )
    conn.execute(
        "INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) VALUES(?, 'b',1)",
        (subject,),
    )
    conn.commit()
    receipt = service.execute(request(subject, "shared-budget", max_threads=1))
    assert receipt.status == "partial"
    assert adapter.read_calls == ["a"]
    assert conn.execute("SELECT count(*) FROM mail_poll_cursors").fetchone()[0] == 0


def test_labeled_continuation_with_budget_one_eventually_processes_union_and_advances(
    tmp_path: Path,
) -> None:
    threads = {
        "a": {"messages": [message("m-a", "a", labels=["TrainLab"])]},
        "b": {"messages": [message("m-b", "b", labels=["TrainLab"])]},
    }
    adapter = FakePollAdapter(
        label_matches=[{"thread_id": "b"}, {"thread_id": "a"}],
        threads=threads,
    )
    service, conn, subject, _ = env(tmp_path, adapter)
    for ordinal in range(1, 7):
        service.execute(request(subject, f"label-progress-{ordinal}", max_threads=1))
        if (
            conn.execute("SELECT count(*) FROM mail_messages").fetchone()[0] == 2
            and conn.execute("SELECT count(*) FROM mail_poll_cursors").fetchone()[0] == 2
        ):
            break
    assert set(adapter.read_calls) >= {"a", "b"}
    assert conn.execute("SELECT count(*) FROM mail_messages").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM mail_poll_cursors").fetchone()[0] == 2


def test_label_continuation_keeps_deferred_candidate_when_next_search_omits_it(
    tmp_path: Path,
) -> None:
    threads = {
        "a": {"messages": [message("m-a", "a", labels=["TrainLab"])]},
        "b": {"messages": [message("m-b", "b", labels=["TrainLab"])]},
    }
    adapter = FakePollAdapter(
        label_matches=[{"thread_id": "a"}, {"thread_id": "b"}], threads=threads
    )
    service, conn, subject, _ = env(tmp_path, adapter)
    assert service.execute(request(subject, "candidate-first", max_threads=1)).status == "partial"
    # ``b`` was discovered but deferred.  It need not remain in the provider's
    # later overlap result for the exact partial window to finish safely.
    adapter.label_matches = [{"thread_id": "a"}]
    assert service.execute(request(subject, "candidate-resume", max_threads=2)).status == "succeeded"
    assert adapter.read_calls.count("b") == 1
    assert conn.execute("SELECT count(*) FROM mail_messages").fetchone()[0] == 2
    assert conn.execute(
        "SELECT count(*) FROM mail_poll_cursors WHERE stream_kind='trainlab_label'"
    ).fetchone()[0] == 1


def test_tracked_continuation_over_budget_makes_stable_progress_across_invocations(
    tmp_path: Path,
) -> None:
    threads = {
        name: {"messages": [message(f"m-{name}", name, labels=[])]}
        for name in ("a", "b", "c")
    }
    adapter = FakePollAdapter(threads=threads)
    service, conn, subject, _ = env(tmp_path, adapter)
    for name in ("a", "b", "c"):
        conn.execute(
            "INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) VALUES(?,?,1)",
            (subject, name),
        )
    conn.commit()
    for ordinal in range(1, 5):
        service.execute(request(subject, f"tracked-progress-{ordinal}", max_threads=1))
        if conn.execute(
            "SELECT count(*) FROM mail_poll_cursors WHERE stream_kind='tracked_threads'"
        ).fetchone()[0]:
            break
    assert adapter.read_calls[:3] == ["a", "b", "c"]
    assert conn.execute("SELECT count(*) FROM mail_messages").fetchone()[0] == 3
    assert conn.execute(
        "SELECT count(*) FROM mail_poll_cursors WHERE stream_kind='tracked_threads'"
    ).fetchone()[0] == 1


def test_failed_thread_is_retried_after_unseen_threads_without_starving_them(
    tmp_path: Path,
) -> None:
    threads = {
        name: {"messages": [message(f"m-{name}", name, labels=[])]}
        for name in ("a", "b", "c")
    }
    adapter = FakePollAdapter(threads=threads, fail_threads={"b"})
    service, conn, subject, _ = env(tmp_path, adapter)
    for name in ("a", "b", "c"):
        conn.execute(
            "INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) VALUES(?,?,1)",
            (subject, name),
        )
    conn.commit()
    service.execute(request(subject, "failure-progress-1", max_threads=1))
    service.execute(request(subject, "failure-progress-2", max_threads=1))
    service.execute(request(subject, "failure-progress-3", max_threads=1))
    assert adapter.read_calls[:3] == ["a", "b", "c"]
    assert conn.execute(
        "SELECT count(*) FROM mail_messages WHERE provider_message_id='m-c'"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT count(*) FROM mail_poll_cursors WHERE stream_kind='tracked_threads'"
    ).fetchone()[0] == 0
    adapter.fail_threads.clear()
    service.execute(request(subject, "failure-progress-4", max_threads=1))
    assert adapter.read_calls[3] == "b"
    assert conn.execute(
        "SELECT count(*) FROM mail_poll_cursors WHERE stream_kind='tracked_threads'"
    ).fetchone()[0] == 1


def test_completed_window_is_scanned_fresh_and_detects_overlap_update(tmp_path: Path) -> None:
    raw = {"messages": [message("m-overlap-refresh", "overlap-refresh", labels=["TrainLab"])]}
    adapter = FakePollAdapter(
        label_matches=[{"thread_id": "overlap-refresh"}],
        threads={"overlap-refresh": raw},
    )
    service, conn, subject, _ = env(tmp_path, adapter)
    assert service.execute(
        request(subject, "overlap-refresh-initial", max_threads=1)
    ).status == "succeeded"
    first_revision = conn.execute(
        "SELECT source_revision_id FROM mail_messages "
        "WHERE provider_message_id='m-overlap-refresh'"
    ).fetchone()[0]
    raw["messages"][0]["plain_text"] = "updated inside overlap"
    raw["messages"][0]["label_ids"].append("later")
    service.execute(request(subject, "overlap-refresh-next", max_threads=1))
    second_revision = conn.execute(
        "SELECT source_revision_id FROM mail_messages "
        "WHERE provider_message_id='m-overlap-refresh'"
    ).fetchone()[0]
    assert second_revision != first_revision


def test_same_partial_invocation_replays_without_search_or_thread_read(tmp_path: Path) -> None:
    threads = {
        "a": {"messages": [message("m-a", "a", labels=["TrainLab"])]},
        "b": {"messages": [message("m-b", "b", labels=["TrainLab"])]},
    }
    adapter = FakePollAdapter(
        label_matches=[{"thread_id": "a"}, {"thread_id": "b"}],
        threads=threads,
    )
    service, _, subject, _ = env(tmp_path, adapter)
    selected = request(subject, "terminal-partial-replay", max_threads=1)
    first = service.execute(selected)
    before = (len(adapter.search_calls), len(adapter.read_calls))
    replay = service.execute(selected)
    assert first.status == "partial"
    assert replay.to_dict() == first.to_dict()
    assert (len(adapter.search_calls), len(adapter.read_calls)) == before


def test_cross_stream_cached_failure_stops_tracked_stream_without_second_read(tmp_path: Path) -> None:
    threads = {
        "a-fails": {"messages": [message("m-a", "a-fails", labels=["TrainLab"])]},
        "b-later": {"messages": [message("m-b", "b-later", labels=[])]},
    }
    adapter = FakePollAdapter(
        label_matches=[{"thread_id": "a-fails"}],
        threads=threads,
        fail_threads={"a-fails"},
    )
    service, conn, subject, _ = env(tmp_path, adapter)
    for thread_id in ("a-fails", "b-later"):
        conn.execute(
            "INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) VALUES(?,?,1)",
            (subject, thread_id),
        )
    conn.commit()
    receipt = service.execute(request(subject, "shared-failure"))
    assert receipt.status == "partial"
    assert adapter.read_calls == ["a-fails"]
    assert conn.execute("SELECT count(*) FROM mail_poll_cursors").fetchone()[0] == 0


def test_unlabeled_untracked_private_thread_is_never_read(tmp_path: Path) -> None:
    private = {"messages": [message("private-message", "private")]}
    adapter = FakePollAdapter(
        threads={"private": private}
    )
    service, conn, subject, _ = env(tmp_path, adapter)
    receipt = service.execute(request(subject, "private-out-of-scope"))
    assert receipt.status == "unchanged"
    assert adapter.read_calls == []
    assert conn.execute("SELECT count(*) FROM mail_messages").fetchone()[0] == 0
    private["messages"][0]["label_ids"] = ["TrainLab"]
    adapter.label_matches = [{"thread_id": "private"}]
    labeled = service.execute(request(subject, "private-later-labeled"))
    assert labeled.status == "succeeded"
    assert adapter.read_calls == ["private"]
    assert conn.execute("SELECT count(*) FROM mail_messages").fetchone()[0] == 1


def test_invalid_or_ambiguous_search_ids_stop_before_provider_read(tmp_path: Path) -> None:
    adapter = FakePollAdapter(
        label_matches=[{"thread_id": "one", "threadId": "two"}],
        threads={},
    )
    service, conn, subject, _ = env(tmp_path, adapter)
    receipt = service.execute(request(subject, "ambiguous-id"))
    assert receipt.status == "partial"
    assert adapter.read_calls == []
    assert conn.execute(
        "SELECT count(*) FROM mail_poll_cursors WHERE stream_kind='trainlab_label'"
    ).fetchone()[0] == 0


def test_read_result_cannot_substitute_another_thread(tmp_path: Path) -> None:
    raw = {"messages": [message("wrong-message", "wrong-thread", labels=["TrainLab"])]}

    class SubstitutionAdapter(FakePollAdapter):
        def read_thread_evidence(self, thread_id: str) -> GmailThreadEvidence:
            self.read_calls.append(thread_id)
            values = FakePollAdapter(threads={"wrong-thread": raw}).read_thread_evidence("wrong-thread")
            return values

    adapter = SubstitutionAdapter(
        label_matches=[{"thread_id": "requested-thread"}],
        threads={},
    )
    service, conn, subject, root = env(tmp_path, adapter)
    receipt = service.execute(request(subject, "thread-substitution"))
    assert receipt.status == "partial"
    assert adapter.read_calls == ["requested-thread"]
    assert conn.execute("SELECT count(*) FROM mail_threads").fetchone()[0] == 0
    assert not list((root / "raw").rglob("*.json"))


def test_html_attachment_and_changed_payload_create_revision(tmp_path: Path) -> None:
    raw = {"messages": [message("m3", "t3", body="", html="<p>Hello <b>world</b><script>secret()</script></p>", labels=["TrainLab"])]}
    raw["messages"][0]["headers"].update(
        {
            "in_reply_to": "<prior>",
            "references": ["<root>", "<prior>"],
            "x_trainlab_run_id": "external-untrusted-marker",
        }
    )
    adapter = FakePollAdapter(label_matches=[{"thread_id": "t3"}], threads={"t3": raw})
    service, conn, subject, _ = env(tmp_path, adapter)
    assert service.execute(request(subject, "first")).status == "succeeded"
    canonical = conn.execute(
        "SELECT body_text,in_reply_to_provider_message_id,labels_json "
        "FROM mail_messages WHERE provider_message_id='m3'"
    ).fetchone()
    assert tuple(canonical) == ("Hello world", "<prior>", '["TrainLab"]')
    attachment = conn.execute(
        "SELECT provider_attachment_id,filename,media_type,size_bytes,raw_object_id "
        "FROM mail_attachments"
    ).fetchone()
    assert tuple(attachment) == ("a1", "x.pdf", "application/pdf", 10, None)
    raw["messages"][0]["plain_text"] = "changed"; raw["messages"][0]["label_ids"] = ["TrainLab", "later"]
    assert service.execute(request(subject, "changed")).status == "succeeded"
    assert conn.execute("SELECT count(*) FROM source_revisions").fetchone()[0] == 4
    assert conn.execute("SELECT body_text FROM mail_messages WHERE provider_message_id='m3'").fetchone()[0] == "changed"


def test_later_label_and_delayed_message_create_only_affected_message_revisions(tmp_path: Path) -> None:
    raw = {"messages": [message("m-current", "t-late", labels=["TrainLab"])]}
    adapter = FakePollAdapter(label_matches=[{"thread_id": "t-late"}], threads={"t-late": raw})
    service, conn, subject, _ = env(tmp_path, adapter)
    assert service.execute(request(subject, "baseline")).status == "succeeded"
    baseline = dict(conn.execute(
        "SELECT provider_message_id,source_revision_id FROM mail_messages"
    ))
    service._clock = lambda: "2026-07-24T07:00:00Z"  # type: ignore[method-assign]
    raw["messages"].insert(
        0,
        message(
            "m-delayed",
            "t-late",
            labels=["TrainLab"],
            when="2026-07-21T08:00:00Z",
        ),
    )
    delayed = service.execute(
        MailRequest("poll", subject, "delayed", "2026-07-24T07:00:00Z")
    )
    assert delayed.status == "succeeded"
    after_delayed = dict(conn.execute(
        "SELECT provider_message_id,source_revision_id FROM mail_messages"
    ))
    assert after_delayed["m-current"] == baseline["m-current"]
    assert "m-delayed" in after_delayed
    raw["messages"][1]["label_ids"].append("later-label")
    labeled = service.execute(
        MailRequest("poll", subject, "later-label", "2026-07-24T07:00:00Z")
    )
    after_label = dict(conn.execute(
        "SELECT provider_message_id,source_revision_id FROM mail_messages"
    ))
    assert labeled.status == "succeeded"
    assert after_label["m-current"] != after_delayed["m-current"]
    assert after_label["m-delayed"] == after_delayed["m-delayed"]


def test_message_id_cannot_be_reparented_to_another_thread(tmp_path: Path) -> None:
    first = {"messages": [message("stable-message", "thread-one", labels=["TrainLab"])]}
    adapter = FakePollAdapter(
        label_matches=[{"thread_id": "thread-one"}],
        threads={"thread-one": first},
    )
    service, conn, subject, root = env(tmp_path, adapter)
    assert service.execute(request(subject, "first-parent")).status == "succeeded"
    original = conn.execute(
        "SELECT m.source_revision_id,t.provider_thread_id "
        "FROM mail_messages m JOIN mail_threads t ON t.id=m.mail_thread_id "
        "WHERE m.provider_message_id='stable-message'"
    ).fetchone()
    second = {"messages": [message("stable-message", "thread-two", labels=["TrainLab"])]}
    adapter.label_matches = [{"thread_id": "thread-two"}]
    adapter.threads["thread-two"] = second
    receipt = service.execute(request(subject, "second-parent"))
    current = conn.execute(
        "SELECT m.source_revision_id,t.provider_thread_id "
        "FROM mail_messages m JOIN mail_threads t ON t.id=m.mail_thread_id "
        "WHERE m.provider_message_id='stable-message'"
    ).fetchone()
    assert receipt.status == "partial"
    assert tuple(current) == tuple(original)
    assert len(list((root / "raw" / "gmail" / "json").rglob("*.json"))) > 2


def test_invalid_attachment_metadata_rolls_back_projection(tmp_path: Path) -> None:
    raw = {"messages": [message("bad-attachment", "attachment-thread", labels=["TrainLab"])]}
    raw["messages"][0]["attachments"][0]["size"] = -1
    adapter = FakePollAdapter(
        label_matches=[{"thread_id": "attachment-thread"}],
        threads={"attachment-thread": raw},
    )
    service, conn, subject, root = env(tmp_path, adapter)
    receipt = service.execute(request(subject, "bad-attachment"))
    assert receipt.status == "partial"
    assert list((root / "raw" / "gmail" / "json").rglob("*.json"))
    assert conn.execute("SELECT count(*) FROM source_revisions").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM mail_messages").fetchone()[0] == 0


def test_message_revisions_are_independent_of_thread_snapshot(tmp_path: Path) -> None:
    raw = {"thread_metadata": {"topic": "one"}, "messages": [message("m1", "tm", labels=["TrainLab"]), message("m2", "tm", labels=["TrainLab"])]}
    adapter = FakePollAdapter(label_matches=[{"thread_id": "tm"}], threads={"tm": raw})
    service, conn, subject, _ = env(tmp_path, adapter)
    assert service.execute(request(subject, "initial")).status == "succeeded"
    initial = dict(conn.execute("SELECT provider_message_id,source_revision_id FROM mail_messages"))
    attachment = conn.execute("SELECT id FROM mail_attachments WHERE mail_message_id=(SELECT id FROM mail_messages WHERE provider_message_id='m1')").fetchone()[0]
    raw["messages"].append(message("m3", "tm", labels=["TrainLab"]))
    assert service.execute(request(subject, "add-one")).status == "succeeded"
    after_add = dict(conn.execute("SELECT provider_message_id,source_revision_id FROM mail_messages"))
    assert after_add["m1"] == initial["m1"] and after_add["m2"] == initial["m2"] and "m3" in after_add
    assert conn.execute("SELECT id FROM mail_attachments WHERE mail_message_id=(SELECT id FROM mail_messages WHERE provider_message_id='m1')").fetchone()[0] == attachment
    raw["messages"][1]["plain_text"] = "revised"
    raw["messages"][1]["label_ids"].append("later")
    raw["messages"][1]["headers"]["x_extra"] = "changed"
    assert service.execute(request(subject, "revise-second")).status == "succeeded"
    revised = dict(conn.execute("SELECT provider_message_id,source_revision_id FROM mail_messages"))
    assert revised["m1"] == initial["m1"] and revised["m2"] != initial["m2"] and revised["m3"] == after_add["m3"]
    raw["thread_metadata"] = {"topic": "two"}
    receipt = service.execute(request(subject, "thread-only"))
    after_thread = dict(conn.execute("SELECT provider_message_id,source_revision_id FROM mail_messages"))
    assert receipt.status == "succeeded" and after_thread == revised


def test_shared_read_budget_deduplicates_label_and_preexisting_tracked(tmp_path: Path) -> None:
    raw = {"messages": [message("m-budget", "tb", labels=["TrainLab"])]}
    adapter = FakePollAdapter(label_matches=[{"thread_id": "tb"}], threads={"tb": raw})
    service, conn, subject, _ = env(tmp_path, adapter)
    conn.execute("INSERT INTO mail_threads(subject_id,provider_thread_id,is_current) VALUES(?, 'tb',1)", (subject,)); conn.commit()
    receipt = service.execute(request(subject, "one-read", max_threads=1))
    assert receipt.status == "succeeded" and adapter.read_calls == ["tb"]


def test_raw_survives_transaction_failure_but_never_becomes_canonical(tmp_path: Path, monkeypatch) -> None:
    raw = {"messages": [message("m4", "t4", labels=["TrainLab"])]}
    service, conn, subject, root = env(tmp_path, FakePollAdapter(label_matches=[{"thread_id": "t4"}], threads={"t4": raw}))
    monkeypatch.setattr(service, "_project", lambda *_args: (_ for _ in ()).throw(sqlite3.IntegrityError("no provider text")))
    receipt = service.execute(request(subject, "tx-fail"))
    assert receipt.status == "partial"
    assert list((root / "raw" / "gmail" / "json").rglob("*.json"))
    assert conn.execute("SELECT count(*) FROM source_revisions").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM mail_messages").fetchone()[0] == 0


def test_invalid_evidence_and_symlink_raw_root_are_partial_without_final_file(tmp_path: Path) -> None:
    invalid = {"messages": [message("", "t5", labels=["TrainLab"])]}
    service, conn, subject, root = env(tmp_path / "invalid", FakePollAdapter(label_matches=[{"thread_id": "t5"}], threads={"t5": invalid}))
    assert service.execute(request(subject, "invalid")).status == "partial"
    assert not list((root / "raw").rglob("*.json"))
    raw = {"messages": [message("m6", "t6", labels=["TrainLab"])]}
    service, conn, subject, root = env(tmp_path / "symlink", FakePollAdapter(label_matches=[{"thread_id": "t6"}], threads={"t6": raw}))
    outside = tmp_path / "outside"; outside.mkdir()
    year_link = root / "raw" / "gmail" / "json" / "2026"; year_link.symlink_to(outside, target_is_directory=True)
    assert service.execute(request(subject, "symlink")).status == "partial"
    assert not list(outside.iterdir())


def test_existing_raw_tamper_fails_closed_without_canonical_change(tmp_path: Path) -> None:
    raw = {"messages": [message("m7", "t7", labels=["TrainLab"])]}
    service, conn, subject, root = env(tmp_path, FakePollAdapter(label_matches=[{"thread_id": "t7"}], threads={"t7": raw}))
    assert service.execute(request(subject, "good")).status == "succeeded"
    final = next((root / "raw" / "gmail" / "json").rglob("*.json"))
    os.chmod(final, 0o644)
    receipt = service.execute(request(subject, "tampered"))
    assert receipt.status == "partial"
    assert conn.execute("SELECT count(*) FROM mail_messages").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM source_revisions WHERE resource_kind='message_json'").fetchone()[0] == 1
