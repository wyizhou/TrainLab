"""Reply-loop contract test using a fake Gmail transport only."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from trainlab.orchestration.fakes import FakeMail

ROOT = Path(__file__).resolve().parents[1]


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(
        json.loads((ROOT / "harness/schemas" / name).read_text(encoding="utf-8"))
    )


def _request() -> dict[str, object]:
    return {
        "mode": "process",
        "subject_id": 1,
        "invocation_id": "integration-reply-loop-001",
        "requested_at_utc": "2026-08-03T00:00:00Z",
        "mail_message_ids": ["synthetic-message-001"],
        "mail_response_artifact_ids": [],
        "dependency_analysis_artifact_ids": ["synthetic-artifact-001"],
        "mail_delivery_ids": [],
        # FakeMail only permits a run_key for its status operation.  A process
        # request is still schema-valid without one.
        "run_key": None,
        "thread_id": "synthetic-thread-001",
        "max_items": 1,
        "max_threads": None,
        "deadline_seconds": 120,
        "regeneration_reason_code": None,
    }


def _receipt() -> dict[str, object]:
    return {
        "schema_version": "1",
        "run_key": "mail:1:process:synthetic-message-001",
        "mail_agent_run_id": "synthetic-mail-run-001",
        "invocation_id": "integration-reply-loop-001",
        "mode": "process",
        "status": "succeeded",
        "counts": {
            "discovered": 0,
            "archived": 0,
            "unchanged": 0,
            "queued": 0,
            "processed": 1,
            "ignored": 0,
            "responses_accepted": 1,
            "deliveries_sent": 0,
            "deliveries_already_sent": 0,
            "failed": 0,
            "deferred": 0,
        },
        "processed_message_ids": ["synthetic-message-001"],
        "mail_response_artifact_ids": ["synthetic-response-001"],
        "mail_delivery_ids": [],
        "pending_dependencies": [],
        "poll_state": [],
        "next_action": "none",
        "next_retry_at_utc": None,
        "warnings": [],
        "errors": [],
        "started_at_utc": "2026-08-03T00:00:00Z",
        "completed_at_utc": "2026-08-03T00:00:01Z",
    }


def test_reply_loop_runs_twice_with_one_synthetic_response_effect() -> None:
    request, receipt = _request(), _receipt()
    assert not list(_validator("mail_request.schema.json").iter_errors(request))
    assert not list(_validator("mail_receipt.schema.json").iter_errors(receipt))

    fake = FakeMail({"process": receipt})
    first, second = fake.execute(request), fake.execute(request)

    assert first == second == receipt
    assert len(fake.invocations) == 2
    assert first["mail_response_artifact_ids"] == ["synthetic-response-001"]
