"""Offline checks for the M4-10..12 composition seam.

These tests deliberately do not create a Gmail MCP client or a Codex process.
"""
from __future__ import annotations

from trainlab.mail_agent.contracts import MailRequest
from trainlab.mail_agent.runtime import _recipient_email
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
