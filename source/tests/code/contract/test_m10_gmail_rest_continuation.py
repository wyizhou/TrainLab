from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from types import ModuleType
from typing import Any
from zoneinfo import ZoneInfo

import pytest

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE))

from skills._shared.state import (  # noqa: E402
    append_output,
    begin_run,
    canonical_json,
    connect,
    finish_run,
    init_database,
)


def load_script(name: str) -> ModuleType:
    path = SOURCE / f"skills/gmail-sender/scripts/{name}.py"
    spec = importlib.util.spec_from_file_location(f"trainlab_r07_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R07 = load_script("gmail_rest_continuation")
COMMON = sys.modules["gmail_rest_common"]
DELIVERY = sys.modules["gmail_rest_delivery"]


def owner_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    path.write_bytes(payload)
    os.chmod(path, 0o600)


def assert_private_tree_permissions(root: Path) -> None:
    assert (root.stat().st_mode & 0o777) == 0o700
    for path in root.rglob("*"):
        if path.is_dir():
            assert (path.stat().st_mode & 0o777) == 0o700, path
        elif path.is_file():
            assert (path.stat().st_mode & 0o777) == 0o600, path


class FakeResponse:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status_code = status
        self._body = body
        self.content = b"x" if body else b""

    def json(self) -> dict[str, Any]:
        return self._body


class FakeSession:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def _next(self, method: str, url: str) -> Any:
        self.calls.append((method, url))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def get(self, url: str, **_kwargs: Any) -> Any:
        return self._next("GET", url)

    def post(self, url: str, **_kwargs: Any) -> Any:
        return self._next("POST", url)


def _rewritten_message_id(raw: bytes, requested: str, actual: str) -> bytes:
    assert raw.count(requested.encode()) == 1
    return raw.replace(requested.encode(), actual.encode())


def _auth_receipt() -> dict[str, Any]:
    return {
        "schema_version": "gmail_rest_auth_receipt_v1",
        "status": "succeeded",
        "account_matches": True,
        "scopes_match": True,
        "refresh_token_available": True,
        "token_published": True,
        "short_lived_testing_token": False,
        "provider_calls": 1,
        "completed_at_utc": "2026-08-20T00:00:00Z",
    }


def seed_r06_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, bytes]:
    parent_root = tmp_path / "parent-r06"
    candidate = parent_root / "candidate"
    source = candidate / "source"
    candidate.mkdir(parents=True, mode=0o700)
    source.mkdir(mode=0o700)
    database = init_database(source / "state/trainlab.db")
    owner_write(source / "state/trainlab.lock", b"")
    input_root = candidate / "gmail-rest/input"
    input_root.mkdir(parents=True, mode=0o700)
    connection = connect(database)
    items: list[dict[str, Any]] = []
    first_raw = b""
    first_requested = ""
    for ordinal in range(1, 9):
        start = "2026-08-12" if ordinal == 8 else f"2026-08-{ordinal + 11:02d}"
        end = "2026-08-18" if ordinal == 8 else start
        ai_payload = {"ordinal": ordinal, "verified_metric": ordinal * 10}
        ai_run = begin_run(
            connection,
            run_key=f"r07-fixture-ai-{ordinal}",
            workflow_key=f"r07-fixture:{ordinal}",
            dedupe_key=f"r07-fixture-ai-{ordinal}",
            skill_name="training-coach",
            operation="daily_coach" if ordinal < 8 else "weekly_coach",
            trigger_kind="manual",
            input_manifest={"fixture": ordinal},
        )
        ai_id = append_output(
            connection,
            skill_run_id=ai_run,
            output_kind="daily_summary" if ordinal < 8 else "weekly_summary",
            logical_key=f"r07-fixture-ai:{ordinal}",
            schema_name=(
                "daily_ai_result_v1" if ordinal < 8 else "weekly_ai_result_v1"
            ),
            schema_version="1",
            content_json=ai_payload,
            content_text=canonical_json(ai_payload),
            period_start_date=start,
            period_end_date=end,
            lineage=[],
        )
        finish_run(connection, ai_run, status="succeeded")
        ai_sha = str(
            connection.execute(
                "SELECT content_sha256 FROM skill_outputs WHERE id=?", (ai_id,)
            ).fetchone()[0]
        )
        title = f"Old report {ordinal}"
        period = start if start == end else f"{start}/{end}"
        payload = {"title": title, "period": period, "content": ai_payload}
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
        html = f"<html><body><h1>{title}</h1><p>{ordinal}</p></body></html>"
        report_run = begin_run(
            connection,
            run_key=f"r07-fixture-report-{ordinal}",
            workflow_key=f"r07-fixture:{ordinal}",
            dedupe_key=f"r07-fixture-report-{ordinal}",
            skill_name="training-report-publisher",
            operation="render_daily" if ordinal < 8 else "render_weekly",
            trigger_kind="manual",
            input_manifest={"fixture": ordinal},
        )
        report_id = append_output(
            connection,
            skill_run_id=report_run,
            output_kind="email_render",
            logical_key=f"r07-fixture-report:{ordinal}",
            schema_name="daily_email_render" if ordinal < 8 else "weekly_email_render",
            schema_version="1",
            title_text=title,
            content_json=payload,
            content_text=text,
            content_html=html,
            lineage=[{"output_id": ai_id, "output_sha256": ai_sha}],
        )
        finish_run(connection, report_run, status="succeeded")
        report_sha = str(
            connection.execute(
                "SELECT content_sha256 FROM skill_outputs WHERE id=?", (report_id,)
            ).fetchone()[0]
        )
        envelope = {
            "subject": title,
            "text": text,
            "html": html,
            "source_output_id": ai_id,
            "source_output_sha256": ai_sha,
            "report_output_id": report_id,
            "report_output_sha256": report_sha,
        }
        envelope_path = input_root / f"{ordinal:02d}-email-envelope.json"
        owner_write(envelope_path, (canonical_json(envelope) + "\n").encode())
        raw, requested_id, mime_sha = COMMON.deterministic_mime(
            recipient="owner@example.com",
            subject=title,
            plain=text,
            html=html,
            source_sha256=report_sha,
            date_value=datetime(
                2026, 8, int(end[-2:]), 12, tzinfo=ZoneInfo("Asia/Hong_Kong")
            ),
        )
        owner_write(input_root / f"{ordinal:02d}-message.eml", raw)
        if ordinal == 1:
            first_raw = raw
            first_requested = requested_id
        request = {
            "transport": "gmail_rest",
            "ordinal": ordinal,
            "message_id": requested_id,
            "mime_sha256": mime_sha,
            "recipient_sha256": COMMON.sha256_text("owner@example.com"),
            "source_output_id": report_id,
            "source_output_sha256": report_sha,
        }
        items.append(
            {
                "ordinal": ordinal,
                "source_output_id": report_id,
                "source_output_sha256": report_sha,
                "envelope_relative_path": str(envelope_path.relative_to(candidate)),
                "envelope_sha256": COMMON.sha256_file(envelope_path),
                "recipient_sha256": COMMON.sha256_text("owner@example.com"),
                "subject_sha256": COMMON.sha256_text(title),
                "message_id": requested_id,
                "mime_sha256": mime_sha,
                "request_sha256": COMMON.sha256_text(COMMON.canonical_json(request)),
            }
        )
    unsigned = {
        "schema_version": "m10_gmail_rest_preview_v1",
        "batch_id": DELIVERY.BATCH_ID,
        "transport": "gmail_rest",
        "parent_preview_output_id": items[0]["source_output_id"],
        "parent_preview_output_sha256": items[0]["source_output_sha256"],
        "emails": items,
        "gmail_api_budget": DELIVERY.MAX_API_CALLS,
        "gmail_send_budget": DELIVERY.MAX_SEND_CALLS,
    }
    preview = {
        **unsigned,
        "preview_sha256": COMMON.sha256_text(COMMON.canonical_json(unsigned)),
    }
    preview_run = begin_run(
        connection,
        run_key="r07-fixture-r06-preview",
        workflow_key=DELIVERY.WORKFLOW_KEY,
        dedupe_key="r07-fixture-r06-preview",
        skill_name="gmail-sender",
        operation="send_email",
        trigger_kind="manual",
        input_manifest={"fixture": True},
    )
    preview_id = append_output(
        connection,
        skill_run_id=preview_run,
        output_kind="execution_summary",
        logical_key="m10:r06:gmail-rest-preview",
        schema_name="m10_gmail_rest_preview_v1",
        schema_version="1",
        content_json=preview,
        content_text=canonical_json(preview),
        lineage=[
            {
                "output_id": items[0]["source_output_id"],
                "output_sha256": items[0]["source_output_sha256"],
            }
        ],
    )
    finish_run(connection, preview_run, status="succeeded")
    preview_sha = str(
        connection.execute(
            "SELECT content_sha256 FROM skill_outputs WHERE id=?", (preview_id,)
        ).fetchone()[0]
    )
    action_ids = DELIVERY._prepare_actions(connection, preview_id, preview_sha, preview)
    first_action = action_ids[0]
    connection.execute(
        "UPDATE external_actions SET status='in_progress',attempt_count=1,started_at_utc=? WHERE id=?",
        ("2026-08-20T00:00:00Z", first_action),
    )
    connection.execute(
        "UPDATE external_actions SET status='unknown',error_code='gmail_rest_mime_mismatch',"
        "error_summary='fixture' WHERE id=?",
        (first_action,),
    )
    connection.commit()
    connection.close()
    runtime = tmp_path / "runtime-source"
    runtime.mkdir(mode=0o700)
    owner_write(
        runtime / "email.json",
        b'{"schema_version":"trainlab_email_recipient_v1","email":"owner@example.com"}',
    )
    owner_write(
        runtime / "gmail-api-auth-receipt.json",
        (canonical_json(_auth_receipt()) + "\n").encode(),
    )
    owner_write(runtime / "gmail-api-token.json", b'{"token":"fake"}')
    monkeypatch.setitem(DELIVERY.__dict__, "SOURCE_ROOT", runtime)
    monkeypatch.setattr(
        R07,
        "read_recipient",
        lambda _path: ("owner@example.com", COMMON.sha256_text("owner@example.com")),
    )
    provider_id = "gmail-canary"
    actual_id = "<provider-canary@mail.gmail.com>"
    provider_raw = _rewritten_message_id(first_raw, first_requested, actual_id)
    capture_root = candidate / "gmail-rest/captures"
    capture_root.mkdir(parents=True, mode=0o700)
    owner_write(
        capture_root / f"001-{first_action}-initial-query-1.json",
        (
            canonical_json({"status_code": 200, "response": {"resultSizeEstimate": 0}})
            + "\n"
        ).encode(),
    )
    owner_write(
        capture_root / f"002-{first_action}-send.json",
        (
            canonical_json({"status_code": 200, "response": {"id": provider_id}}) + "\n"
        ).encode(),
    )
    for index in (3, 4):
        owner_write(
            capture_root / f"{index:03d}-{first_action}-get-raw-{index - 2}.json",
            (
                canonical_json(
                    {
                        "status_code": 200,
                        "response": {
                            "id": provider_id,
                            "raw_sha256": COMMON.sha256_text(
                                COMMON.gmail_raw(provider_raw)
                            ),
                        },
                    }
                )
                + "\n"
            ).encode(),
        )
    owner_write(parent_root / "mismatch-canary-provider.eml", provider_raw)
    owner_write(parent_root / "pre-canary-boundary.json", b'{"fixture":true}')
    marker = {
        "schema_version": "m10_gmail_rest_candidate_v1",
        "batch_id": DELIVERY.BATCH_ID,
        "candidate_source": str(source),
        "database": str(database),
        "parent_database_sha256": "a" * 64,
        "runtime_sha256": "b" * 64,
        "preview_output_id": preview_id,
        "preview_output_sha256": preview_sha,
        "action_ids": action_ids,
        "action_api_calls": {
            str(value): (4 if value == first_action else 0) for value in action_ids
        },
        "action_phase_calls": {
            str(value): {
                "lookup": 1 if value == first_action else 0,
                "raw": 2 if value == first_action else 0,
                "confirmation": 0,
            }
            for value in action_ids
        },
        "action_send_calls": {
            str(value): (1 if value == first_action else 0) for value in action_ids
        },
        "auth_receipt_sha256": COMMON.sha256_file(
            runtime / "gmail-api-auth-receipt.json"
        ),
        "auth_provider_calls": 1,
        "canary_confirmed": False,
        "api_calls": 4,
        "send_calls": 1,
        "created_at_utc": "2026-08-20T00:00:00Z",
    }
    owner_write(
        candidate / R07.PARENT_MARKER_NAME, (canonical_json(marker) + "\n").encode()
    )
    monkeypatch.setattr(
        R07,
        "EXPECTED_PARENT_MARKER_SHA256",
        COMMON.sha256_file(candidate / R07.PARENT_MARKER_NAME),
    )
    monkeypatch.setattr(
        R07, "EXPECTED_PARENT_DATABASE_SHA256", COMMON.sha256_file(database)
    )
    monkeypatch.setattr(
        R07,
        "EXPECTED_PRE_CANARY_BOUNDARY_SHA256",
        COMMON.sha256_file(parent_root / "pre-canary-boundary.json"),
    )
    monkeypatch.setattr(
        R07,
        "EXPECTED_CANARY_EML_SHA256",
        COMMON.sha256_file(parent_root / "mismatch-canary-provider.eml"),
    )
    monkeypatch.setattr(R07, "EXPECTED_PARENT_TREE_SHA256", R07._tree_sha256(candidate))
    monkeypatch.setattr(R07, "PARENT_R06_ROOT", parent_root)
    return parent_root, runtime, provider_raw


def seed_r07_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    r06_root, runtime, _provider_raw = seed_r06_parent(tmp_path, monkeypatch)
    r07_root = tmp_path / "parent-r07"
    R07.create_continuation(
        parent_root=r06_root,
        candidate_root=r07_root,
        confirm_canary_received=True,
    )
    candidate = r07_root / "candidate"
    marker = COMMON.read_owner_json(candidate / R07.MARKER_NAME)
    connection = connect(Path(marker["database"]), read_only=True, immutable=True)
    preview = json.loads(
        connection.execute(
            "SELECT content_json FROM skill_outputs WHERE id=?",
            (marker["preview_output_id"],),
        ).fetchone()[0]
    )
    connection.close()
    responses: list[Any] = []
    for item in preview["emails"]:
        raw = (
            candidate / f"gmail-rest-r07/input/{item['ordinal']:02d}-message.eml"
        ).read_bytes()
        gmail_id = f"historic-gmail-{item['ordinal']}"
        actual_id = f"<historic-provider-{item['ordinal']}@mail.gmail.com>"
        provider_raw = _rewritten_message_id(
            raw, item["requested_message_id"], actual_id
        )
        responses.extend(
            [
                FakeResponse(200, {}),
                FakeResponse(200, {"id": gmail_id}),
                FakeResponse(
                    200, {"id": gmail_id, "raw": COMMON.gmail_raw(provider_raw)}
                ),
                FakeResponse(200, {"messages": [{"id": gmail_id}]}),
            ]
        )
    session = FakeSession(responses)
    assert R07.deliver_remaining(
        candidate_root=candidate,
        token_file=runtime / "gmail-api-token.json",
        session_factory=lambda _credentials: session,
    ) == {"status": "succeeded", "delivered": 7}
    marker_path = candidate / R07.MARKER_NAME
    database = candidate / "source/state/trainlab.db"
    monkeypatch.setattr(R07, "R08_PARENT_ROOT", r07_root)
    monkeypatch.setattr(
        R07, "R08_PARENT_MARKER_SHA256", COMMON.sha256_file(marker_path)
    )
    monkeypatch.setattr(R07, "R08_PARENT_DATABASE_SHA256", COMMON.sha256_file(database))
    monkeypatch.setattr(R07, "R08_PARENT_TREE_SHA256", R07._tree_sha256(candidate))
    return r07_root, runtime


def test_actual_message_id_contract_accepts_provider_rewrite() -> None:
    raw, requested, _sha = COMMON.deterministic_mime(
        recipient="owner@example.com",
        subject="subject",
        plain="plain",
        html="<p>html</p>",
        source_sha256="a" * 64,
        date_value=datetime(2026, 8, 20, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
    )
    actual = "<provider-rewrite@mail.gmail.com>"
    rewritten = _rewritten_message_id(raw, requested, actual)
    assert (
        COMMON.verify_mime_with_actual_message_id(
            rewritten,
            recipient="owner@example.com",
            subject="subject",
            plain="plain",
            html="<p>html</p>",
        )
        == actual
    )
    with pytest.raises(RuntimeError, match="gmail_rest_mime_mismatch"):
        COMMON.verify_mime(
            rewritten,
            recipient="owner@example.com",
            subject="subject",
            plain="plain",
            html="<p>html</p>",
            message_id=requested,
        )


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_to", "duplicate_subject", "duplicate_message_id", "extra_html"],
)
def test_actual_message_id_contract_rejects_ambiguous_mime(mutation: str) -> None:
    raw, requested, _sha = COMMON.deterministic_mime(
        recipient="owner@example.com",
        subject="subject",
        plain="plain",
        html="<p>html</p>",
        source_sha256="a" * 64,
        date_value=datetime(2026, 8, 20, 12, tzinfo=ZoneInfo("Asia/Hong_Kong")),
    )
    if mutation == "extra_html":
        message = BytesParser(policy=policy.SMTP).parsebytes(raw)
        extra = EmailMessage(policy=policy.SMTP)
        extra.set_content("<p>extra</p>", subtype="html")
        message.attach(extra)
        changed = message.as_bytes(policy=policy.SMTP)
    else:
        header = {
            "duplicate_to": "To: other@example.com",
            "duplicate_subject": "Subject: subject",
            "duplicate_message_id": f"Message-ID: {requested}",
        }[mutation]
        changed = raw.replace(b"\r\n\r\n", f"\r\n{header}\r\n\r\n".encode(), 1)
    with pytest.raises(RuntimeError, match="gmail_rest_mime_mismatch"):
        COMMON.verify_mime_with_actual_message_id(
            changed,
            recipient="owner@example.com",
            subject="subject",
            plain="plain",
            html="<p>html</p>",
        )


def test_r07_action_order_drift_stops_before_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_root, runtime, _provider_raw = seed_r06_parent(tmp_path, monkeypatch)
    output_root = tmp_path / "r07-order-drift"
    R07.create_continuation(
        parent_root=parent_root,
        candidate_root=output_root,
        confirm_canary_received=True,
    )
    candidate = output_root / "candidate"
    marker_path = candidate / R07.MARKER_NAME
    marker = COMMON.read_owner_json(marker_path)
    marker["action_ids"][0], marker["action_ids"][1] = (
        marker["action_ids"][1],
        marker["action_ids"][0],
    )
    COMMON.atomic_json(marker_path, marker)
    session = FakeSession([])
    with pytest.raises(RuntimeError, match="gmail_rest_action_invalid"):
        R07.deliver_action(
            candidate_root=candidate,
            token_file=runtime / "gmail-api-token.json",
            action_id=marker["action_ids"][0],
            session_factory=lambda: session,
        )
    assert session.calls == []


def test_r07_build_reconciles_canary_retitles_and_cancels_old_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_root, _runtime, _provider_raw = seed_r06_parent(tmp_path, monkeypatch)
    output_root = tmp_path / "r07-output"
    parent_marker_before = COMMON.sha256_file(
        parent_root / "candidate" / R07.PARENT_MARKER_NAME
    )
    result = R07.create_continuation(
        parent_root=parent_root,
        candidate_root=output_root,
        confirm_canary_received=True,
    )
    assert result["completed_canary"] == 1
    assert result["remaining_actions"] == 7
    assert (
        COMMON.sha256_file(parent_root / "candidate" / R07.PARENT_MARKER_NAME)
        == parent_marker_before
    )
    candidate = output_root / "candidate"
    marker = COMMON.read_owner_json(candidate / R07.MARKER_NAME)
    assert marker["api_calls"] == 4
    assert marker["send_calls"] == 1
    assert len(marker["action_ids"]) == 7
    connection = connect(Path(marker["database"]), read_only=True, immutable=True)
    preview = json.loads(
        str(
            connection.execute(
                "SELECT content_json FROM skill_outputs WHERE id=?",
                (marker["preview_output_id"],),
            ).fetchone()[0]
        )
    )
    assert [item["subject"] for item in preview["emails"]] == list(
        R07.NEW_SUBJECTS.values()
    )
    assert [item["ordinal"] for item in preview["emails"]] == list(range(2, 9))
    old_ids = COMMON.read_owner_json(candidate / R07.PARENT_MARKER_NAME)["action_ids"]
    assert (
        connection.execute(
            f"SELECT COUNT(*) FROM external_actions WHERE id IN ({','.join('?' for _ in old_ids[1:])}) AND status='cancelled'",
            old_ids[1:],
        ).fetchone()[0]
        == 7
    )
    assert (
        connection.execute(
            "SELECT status FROM external_actions WHERE id=?", (old_ids[0],)
        ).fetchone()[0]
        == "succeeded"
    )
    assert (
        connection.execute(
            f"SELECT COUNT(*) FROM external_actions WHERE id IN ({','.join('?' for _ in marker['action_ids'])}) AND status='prepared'",
            marker["action_ids"],
        ).fetchone()[0]
        == 7
    )
    for item in preview["emails"]:
        new_output = connection.execute(
            "SELECT content_json,lineage_json FROM skill_outputs WHERE id=? AND content_sha256=?",
            (item["source_output_id"], item["source_output_sha256"]),
        ).fetchone()
        old_output = connection.execute(
            "SELECT content_json FROM skill_outputs WHERE id=? AND content_sha256=?",
            (item["prior_source_output_id"], item["prior_source_output_sha256"]),
        ).fetchone()
        assert (
            json.loads(new_output[0])["content"] == json.loads(old_output[0])["content"]
        )
        assert item["prior_source_output_id"] in {
            entry["output_id"]
            for entry in json.loads(new_output[1])
            if "output_id" in entry
        }
    connection.close()


def test_r07_delivery_binds_actual_ids_and_replay_is_zero_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_root, runtime, _provider_raw = seed_r06_parent(tmp_path, monkeypatch)
    output_root = tmp_path / "r07-delivery"
    R07.create_continuation(
        parent_root=parent_root,
        candidate_root=output_root,
        confirm_canary_received=True,
    )
    candidate = output_root / "candidate"
    marker = COMMON.read_owner_json(candidate / R07.MARKER_NAME)
    connection = connect(Path(marker["database"]), read_only=True, immutable=True)
    preview = json.loads(
        connection.execute(
            "SELECT content_json FROM skill_outputs WHERE id=?",
            (marker["preview_output_id"],),
        ).fetchone()[0]
    )
    connection.close()
    responses: list[Any] = []
    for item in preview["emails"]:
        raw = (
            candidate / f"gmail-rest-r07/input/{item['ordinal']:02d}-message.eml"
        ).read_bytes()
        gmail_id = f"gmail-{item['ordinal']}"
        actual_id = f"<provider-{item['ordinal']}@mail.gmail.com>"
        provider_raw = _rewritten_message_id(
            raw, item["requested_message_id"], actual_id
        )
        responses.extend(
            [
                FakeResponse(200, {}),
                FakeResponse(200, {"id": gmail_id}),
                FakeResponse(
                    200, {"id": gmail_id, "raw": COMMON.gmail_raw(provider_raw)}
                ),
                FakeResponse(200, {"messages": [{"id": gmail_id}]}),
            ]
        )
    session = FakeSession(responses)
    result = R07.deliver_remaining(
        candidate_root=candidate,
        token_file=runtime / "gmail-api-token.json",
        session_factory=lambda _credentials: session,
    )
    assert result == {"status": "succeeded", "delivered": 7}
    assert [method for method, _url in session.calls].count("POST") == 7
    marker = COMMON.read_owner_json(candidate / R07.MARKER_NAME)
    assert marker["send_calls"] == 8
    connection = connect(Path(marker["database"]), read_only=True, immutable=True)
    rows = connection.execute(
        f"SELECT status,result_external_id,provider_marker FROM external_actions WHERE id IN ({','.join('?' for _ in marker['action_ids'])}) ORDER BY id",
        marker["action_ids"],
    ).fetchall()
    assert all(row[0] == "succeeded" for row in rows)
    assert len({row[1] for row in rows}) == 7
    assert all(str(row[2]).endswith("@mail.gmail.com>") for row in rows)
    counts_before = tuple(
        connection.execute(
            "SELECT (SELECT COUNT(*) FROM skill_runs),(SELECT COUNT(*) FROM skill_outputs)"
        ).fetchone()
    )
    connection.close()
    replay_session = FakeSession([])
    replay = R07.deliver_remaining(
        candidate_root=candidate,
        token_file=runtime / "gmail-api-token.json",
        session_factory=lambda _credentials: replay_session,
    )
    assert replay == {"status": "succeeded", "delivered": 7}
    assert replay_session.calls == []
    connection = connect(Path(marker["database"]), read_only=True, immutable=True)
    counts_after = tuple(
        connection.execute(
            "SELECT (SELECT COUNT(*) FROM skill_runs),(SELECT COUNT(*) FROM skill_outputs)"
        ).fetchone()
    )
    connection.close()
    assert counts_after == counts_before


def test_r07_send_response_loss_stays_unknown_and_never_resends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_root, runtime, _provider_raw = seed_r06_parent(tmp_path, monkeypatch)
    output_root = tmp_path / "r07-loss"
    R07.create_continuation(
        parent_root=parent_root,
        candidate_root=output_root,
        confirm_canary_received=True,
    )
    candidate = output_root / "candidate"
    marker = COMMON.read_owner_json(candidate / R07.MARKER_NAME)
    action_id = marker["action_ids"][0]
    first = FakeSession([FakeResponse(200, {}), ConnectionError("lost")])
    with pytest.raises(RuntimeError):
        R07.deliver_action(
            candidate_root=candidate,
            token_file=runtime / "gmail-api-token.json",
            action_id=action_id,
            session_factory=lambda _credentials: first,
        )
    assert [method for method, _url in first.calls] == ["GET", "POST"]
    second = FakeSession([])
    with pytest.raises(RuntimeError, match="gmail_rest_send_unconfirmed"):
        R07.deliver_action(
            candidate_root=candidate,
            token_file=runtime / "gmail-api-token.json",
            action_id=action_id,
            session_factory=lambda _credentials: second,
        )
    assert second.calls == []
    current = COMMON.read_owner_json(candidate / R07.MARKER_NAME)
    assert current["action_send_calls"][str(action_id)] == 1


def test_r07_refuses_title_or_mime_drift_before_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_root, runtime, _provider_raw = seed_r06_parent(tmp_path, monkeypatch)
    output_root = tmp_path / "r07-drift"
    R07.create_continuation(
        parent_root=parent_root,
        candidate_root=output_root,
        confirm_canary_received=True,
    )
    candidate = output_root / "candidate"
    marker = COMMON.read_owner_json(candidate / R07.MARKER_NAME)
    connection = connect(Path(marker["database"]), read_only=True, immutable=True)
    preview = json.loads(
        connection.execute(
            "SELECT content_json FROM skill_outputs WHERE id=?",
            (marker["preview_output_id"],),
        ).fetchone()[0]
    )
    connection.close()
    envelope_path = candidate / preview["emails"][0]["envelope_relative_path"]
    envelope = COMMON.read_owner_json(envelope_path)
    envelope["subject"] = "tampered"
    owner_write(envelope_path, (canonical_json(envelope) + "\n").encode())
    session = FakeSession([])
    with pytest.raises(RuntimeError, match="gmail_rest_envelope_changed"):
        R07.deliver_action(
            candidate_root=candidate,
            token_file=runtime / "gmail-api-token.json",
            action_id=marker["action_ids"][0],
            session_factory=lambda _credentials: session,
        )
    assert session.calls == []


def test_r08_builds_exact_corrected_subject_batch_and_preserves_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_root, _runtime = seed_r07_parent(tmp_path, monkeypatch)
    parent_candidate = parent_root / "candidate"
    parent_marker_before = COMMON.sha256_file(parent_candidate / R07.MARKER_NAME)
    parent_database_before = COMMON.sha256_file(
        parent_candidate / "source/state/trainlab.db"
    )
    output_root = tmp_path / "r08-output"
    result = R07.create_r08_continuation(
        parent_root=parent_root, candidate_root=output_root
    )
    assert result["actions"] == 8
    candidate = output_root / "candidate"
    marker = COMMON.read_owner_json(candidate / R07.R08_MARKER_NAME)
    assert marker["api_calls"] == 32
    assert marker["send_calls"] == 8
    assert marker["canary_confirmed"] is False
    assert len(marker["prior_results"]) == 8
    assert len(marker["action_ids"]) == 8
    connection = connect(Path(marker["database"]), read_only=True, immutable=True)
    preview = json.loads(
        connection.execute(
            "SELECT content_json FROM skill_outputs WHERE id=?",
            (marker["preview_output_id"],),
        ).fetchone()[0]
    )
    assert [item["subject"] for item in preview["emails"]] == list(
        R07.R08_SUBJECTS.values()
    )
    assert [item["ordinal"] for item in preview["emails"]] == list(range(1, 9))
    assert not {item["requested_message_id"] for item in preview["emails"]} & {
        item["requested_message_id"] for item in preview["prior_results"]
    }
    assert (
        connection.execute(
            f"SELECT COUNT(*) FROM external_actions WHERE id IN "
            f"({','.join('?' for _ in marker['action_ids'])}) AND status='prepared'",
            marker["action_ids"],
        ).fetchone()[0]
        == 8
    )
    for item in preview["emails"]:
        new_payload = json.loads(
            connection.execute(
                "SELECT content_json FROM skill_outputs WHERE id=? AND content_sha256=?",
                (item["source_output_id"], item["source_output_sha256"]),
            ).fetchone()[0]
        )
        old_payload = json.loads(
            connection.execute(
                "SELECT content_json FROM skill_outputs WHERE id=? AND content_sha256=?",
                (item["prior_source_output_id"], item["prior_source_output_sha256"]),
            ).fetchone()[0]
        )
        assert new_payload["content"] == old_payload["content"]
        assert {**new_payload, "title": old_payload["title"]} == old_payload
    connection.close()
    assert (
        COMMON.sha256_file(parent_candidate / R07.MARKER_NAME) == parent_marker_before
    )
    assert (
        COMMON.sha256_file(parent_candidate / "source/state/trainlab.db")
        == parent_database_before
    )
    assert_private_tree_permissions(output_root)


def test_r08_canary_gate_delivery_and_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_root, runtime = seed_r07_parent(tmp_path, monkeypatch)
    output_root = tmp_path / "r08-delivery"
    R07.create_r08_continuation(parent_root=parent_root, candidate_root=output_root)
    candidate = output_root / "candidate"
    marker = COMMON.read_owner_json(candidate / R07.R08_MARKER_NAME)
    connection = connect(Path(marker["database"]), read_only=True, immutable=True)
    preview = json.loads(
        connection.execute(
            "SELECT content_json FROM skill_outputs WHERE id=?",
            (marker["preview_output_id"],),
        ).fetchone()[0]
    )
    connection.close()
    blocked_session = FakeSession([])
    with pytest.raises(
        RuntimeError, match="gmail_rest_canary_user_confirmation_required"
    ):
        R07.deliver_remaining(
            candidate_root=candidate,
            token_file=runtime / "gmail-api-token.json",
            session_factory=lambda _credentials: blocked_session,
            policy=R07.R08_POLICY,
        )
    assert blocked_session.calls == []

    def responses_for(items: list[dict[str, Any]]) -> list[Any]:
        responses: list[Any] = []
        for item in items:
            raw = (
                candidate / f"gmail-rest-r08/input/{item['ordinal']:02d}-message.eml"
            ).read_bytes()
            gmail_id = f"corrected-gmail-{item['ordinal']}"
            actual_id = f"<corrected-provider-{item['ordinal']}@mail.gmail.com>"
            provider_raw = _rewritten_message_id(
                raw, item["requested_message_id"], actual_id
            )
            responses.extend(
                [
                    FakeResponse(200, {}),
                    FakeResponse(200, {"id": gmail_id}),
                    FakeResponse(
                        200,
                        {"id": gmail_id, "raw": COMMON.gmail_raw(provider_raw)},
                    ),
                    FakeResponse(200, {"messages": [{"id": gmail_id}]}),
                ]
            )
        return responses

    canary_session = FakeSession(responses_for(preview["emails"][:1]))
    canary = R07.deliver_r08_canary(
        candidate_root=candidate,
        token_file=runtime / "gmail-api-token.json",
        session_factory=lambda _credentials: canary_session,
    )
    assert canary["status"] == "succeeded"
    assert [method for method, _url in canary_session.calls].count("POST") == 1
    marker = COMMON.read_owner_json(candidate / R07.R08_MARKER_NAME)
    assert marker["send_calls"] == 9
    assert marker["canary_confirmed"] is False
    assert R07.confirm_r08_canary(candidate_root=candidate, user_confirmed=True) == {
        "status": "succeeded",
        "canary_confirmed": True,
        "provider_calls": 0,
    }
    remaining_session = FakeSession(responses_for(preview["emails"][1:]))
    assert R07.deliver_remaining(
        candidate_root=candidate,
        token_file=runtime / "gmail-api-token.json",
        session_factory=lambda _credentials: remaining_session,
        policy=R07.R08_POLICY,
    ) == {"status": "succeeded", "delivered": 7}
    assert [method for method, _url in remaining_session.calls].count("POST") == 7
    marker = COMMON.read_owner_json(candidate / R07.R08_MARKER_NAME)
    assert marker["api_calls"] == 64
    assert marker["send_calls"] == 16
    connection = connect(Path(marker["database"]), read_only=True, immutable=True)
    before = tuple(
        connection.execute(
            "SELECT (SELECT COUNT(*) FROM skill_runs),(SELECT COUNT(*) FROM skill_outputs),"
            "(SELECT COUNT(*) FROM external_actions)"
        ).fetchone()
    )
    connection.close()
    replay_session = FakeSession([])
    assert R07.deliver_remaining(
        candidate_root=candidate,
        token_file=runtime / "gmail-api-token.json",
        session_factory=lambda _credentials: replay_session,
        policy=R07.R08_POLICY,
    ) == {"status": "succeeded", "delivered": 7}
    assert replay_session.calls == []
    connection = connect(Path(marker["database"]), read_only=True, immutable=True)
    after = tuple(
        connection.execute(
            "SELECT (SELECT COUNT(*) FROM skill_runs),(SELECT COUNT(*) FROM skill_outputs),"
            "(SELECT COUNT(*) FROM external_actions)"
        ).fetchone()
    )
    connection.close()
    assert after == before
    assert_private_tree_permissions(output_root)


def test_r08_canary_unknown_never_sends_remaining_or_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_root, runtime = seed_r07_parent(tmp_path, monkeypatch)
    output_root = tmp_path / "r08-canary-loss"
    R07.create_r08_continuation(parent_root=parent_root, candidate_root=output_root)
    candidate = output_root / "candidate"
    first = FakeSession([FakeResponse(200, {}), ConnectionError("lost")])
    with pytest.raises(RuntimeError):
        R07.deliver_r08_canary(
            candidate_root=candidate,
            token_file=runtime / "gmail-api-token.json",
            session_factory=lambda _credentials: first,
        )
    assert [method for method, _url in first.calls] == ["GET", "POST"]
    second = FakeSession([])
    with pytest.raises(RuntimeError, match="gmail_rest_send_unconfirmed"):
        R07.deliver_r08_canary(
            candidate_root=candidate,
            token_file=runtime / "gmail-api-token.json",
            session_factory=lambda _credentials: second,
        )
    assert second.calls == []
    with pytest.raises(
        RuntimeError, match="gmail_rest_canary_user_confirmation_required"
    ):
        R07.deliver_remaining(
            candidate_root=candidate,
            token_file=runtime / "gmail-api-token.json",
            session_factory=lambda _credentials: second,
            policy=R07.R08_POLICY,
        )
    marker = COMMON.read_owner_json(candidate / R07.R08_MARKER_NAME)
    assert marker["send_calls"] == 9
    assert marker["action_send_calls"][str(marker["action_ids"][0])] == 1
    assert all(
        marker["action_api_calls"][str(action_id)] == 0
        for action_id in marker["action_ids"][1:]
    )
