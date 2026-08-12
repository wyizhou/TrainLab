from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from trainlab.analysis.stable_views import StableViewError, StableViewRepository
from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool


UTC = "2026-07-24T00:00:00Z"


def _repository(tmp_path: Path) -> tuple[sqlite3.Connection, StableViewRepository]:
    root = tmp_path / "foundation"
    tool = FoundationTool(FoundationConfig(root, root / "data.db", root / "raw", root / "state", root / "state/foundation-ready.json", root / "state/locks/foundation.lock"))
    assert tool.execute(FoundationRequest("init", "a3-19-reason", UTC)).ready
    conn = sqlite3.connect(root / "data.db", isolation_level=None)
    conn.execute("INSERT INTO data_subjects(id,subject_key,created_at_utc) VALUES(1,'subject',?)", (UTC,))
    conn.execute("INSERT INTO subject_identities(subject_id,provider,identity_kind,identity_hmac,is_verified,first_seen_at_utc,last_seen_at_utc) VALUES(1,'garmin','account','hmac',1,?,?)", (UTC, UTC))
    conn.execute("INSERT INTO source_revisions(id,provider,resource_kind,provider_object_id,revision_no,payload_hash,is_current,parsed_at_utc) VALUES(1,'gmail','message_json','message-1',1,?,1,?)", ("a" * 64, UTC))
    conn.execute("INSERT INTO mail_threads(id,subject_id,provider_thread_id,is_current) VALUES(1,1,'thread-1',1)")
    conn.execute("INSERT INTO mail_messages(id,mail_thread_id,provider_message_id,direction,actor_role,received_at_utc,source_revision_id,processing_state) VALUES(1,1,'message-1','inbound','user',?,1,'awaiting_analysis')", (UTC,))
    return conn, StableViewRepository(conn)


def _event_payload(**changes: object) -> str:
    value: dict[str, object] = {
        "schema_version": "1", "policy_version": "1", "subject_id": 1,
        "run_key": "mail:1:process:fixture", "source_mail_message_id": 1,
        "source_mail_thread_id": 1, "source_revision_id": 1,
        "value_origin": "user_asserted", "content_instruction_trust": "untrusted_content",
        "change_kind": "availability", "affected_local_dates": ["2026-07-25"],
        "constraints": {"availability": "unavailable"},
        "effective_local_date": "2026-07-25", "current_plan_id": 9,
        "evidence_text_span": {"start": 0, "end": 3, "text": "原始邮件证据"},
    }
    value.update(changes)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _insert_event(conn: sqlite3.Connection, payload: str) -> None:
    conn.execute("INSERT INTO conversation_events(subject_id,event_type,actor_role,occurred_at_utc,mail_message_id,structured_payload_json,trust_level,created_by) VALUES(1,'plan_revision_reason_recorded','trainlab',?,1,?,'system_generated','mail_agent')", (UTC, payload))


def test_reason_dto_requires_current_awaiting_user_mail_and_hides_evidence(tmp_path: Path) -> None:
    conn, repo = _repository(tmp_path)
    _insert_event(conn, _event_payload())
    reason = repo.snapshot(1, "2026-07-24", "2026-07-25").plan_reasons[0]
    assert reason["change_kind"] == "availability"
    assert reason["effective_local_date"] == "2026-07-25"
    assert "evidence_text_span" not in reason
    assert "原始邮件证据" not in json.dumps(reason, ensure_ascii=False)


@pytest.mark.parametrize("changes", (
    {"source_revision_id": 2},
    {"current_plan_id": None},
    {"affected_local_dates": []},
    {"change_kind": "free_text"},
))
def test_reason_dto_rejects_malformed_or_unbound_payload(tmp_path: Path, changes: dict[str, object]) -> None:
    conn, repo = _repository(tmp_path)
    _insert_event(conn, _event_payload(**changes))
    with pytest.raises(StableViewError, match="analysis_plan_reason"):
        repo.snapshot(1, "2026-07-24", "2026-07-25")
