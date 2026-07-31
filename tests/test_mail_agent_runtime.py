"""Offline checks for the M4-10..12 composition seam.

These tests deliberately do not create a Gmail MCP client or a Codex process.
"""
from __future__ import annotations

import sqlite3

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.mail_agent.contracts import MailRequest
from trainlab.mail_agent.runtime import (
    MailRuntimeDependencies,
    RuntimeMailApplicationService,
    _recipient_email,
)
from trainlab.integrations.project_config import configured_recipient_email
from trainlab.mail_agent.stages import MissingDependencyStage, PreparedStage


NOW = "2026-07-27T00:00:00Z"


def request(mode: str = "process") -> MailRequest:
    values: dict[str, object] = dict(
        mode=mode, subject_id=7, invocation_id="runtime-test", requested_at_utc=NOW,
    )
    if mode == "process":
        values["mail_message_ids"] = ("message-1",)
    return MailRequest(**values)  # type: ignore[arg-type]


def test_recipient_config_is_strict_and_not_an_environment_variable(tmp_path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "trainlab.json").write_text(
        '{"schema_version":1,"mail":{"recipient_email":"Authorized@Example.com"}}',
        encoding="utf-8",
    )
    assert _recipient_email(tmp_path) == "authorized@example.com"
    assert configured_recipient_email(tmp_path) == "authorized@example.com"
    (config / "trainlab.json").write_text(
        '{"schema_version":1,"mail":{"recipient_email":"bad address"}}', encoding="utf-8"
    )
    try:
        _recipient_email(tmp_path)
    except ValueError as error:
        assert str(error) == "mail_runtime_configuration_invalid"
    else:  # pragma: no cover - assertion shape is clearer than pytest.raises here
        raise AssertionError("invalid recipient must fail")


def test_missing_adapter_stage_is_a_standard_fail_closed_receipt() -> None:
    receipt = MissingDependencyStage().execute(request())
    assert receipt.status == "failed"
    assert receipt.errors[0]["code"] == "mail_environment_adapter_unavailable"


def test_fast_foundation_status_allows_read_only_mail_status_during_snapshot(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "project"
    data = root / "data"
    foundation = FoundationConfig(
        data,
        data / "data.db",
        data / "raw",
        data / "state",
        data / "state" / "foundation-ready.json",
        data / "state" / "locks" / "foundation.lock",
    )
    tool = FoundationTool(foundation)
    assert tool.execute(FoundationRequest("init", "mail-runtime-init", NOW)).ready
    writer = sqlite3.connect(foundation.database_path)
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute(
        "INSERT INTO data_subjects(subject_key,timezone,is_active,created_at_utc)"
        " VALUES('mail-runtime-subject','Asia/Singapore',1,?)",
        (NOW,),
    )
    writer.commit()
    holder = tool._connect(foundation.database_path, readonly=True)
    assert list(data.glob(".foundation-readonly-*"))
    monkeypatch.setattr(
        "trainlab.mail_agent.runtime.project_root", lambda supplied: root
    )
    monkeypatch.setattr(
        "trainlab.mail_agent.runtime.FoundationConfig.load", lambda supplied: foundation
    )
    adapter_calls = []
    service = RuntimeMailApplicationService(
        root=root,
        dependencies=MailRuntimeDependencies(
            environment_factory=lambda *args, **kwargs: adapter_calls.append(
                (args, kwargs)
            ),
            clock=lambda: "2026-07-27T00:02:00Z",
        ),
    )
    try:
        receipt = service.execute(request("status"))
    finally:
        holder.close()
        writer.close()
    assert receipt.status == "unchanged"
    assert receipt.next_action == "operator_review"
    assert receipt.next_retry_at_utc is None
    assert receipt.warnings == ()
    assert receipt.errors == ()
    assert adapter_calls == []


class _Adapter:
    verified_identity_id = 44
    def prepare(self, connection, subject_id):
        self.called = (connection, subject_id)


class _Sink:
    verified_identity_id = None


class _Stage:
    def execute(self, item):
        self.request = item
        return MissingDependencyStage("mail_test_stage").execute(item)


def test_prepared_stage_binds_verified_identity_without_provider_fallback() -> None:
    adapter, sink, stage = _Adapter(), _Sink(), _Stage()
    repository = type("Repository", (), {"connection": object()})()
    receipt = PreparedStage(stage, repository, adapter, sink).execute(request())
    assert adapter.called[1] == 7 and sink.verified_identity_id == 44
    assert stage.request.mode == "process"
    assert receipt.errors[0]["code"] == "mail_test_stage"
