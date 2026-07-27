from __future__ import annotations

import json
import subprocess
import sys
import threading

import pytest
from jsonschema import Draft202012Validator

from trainlab.mail_agent import MailReceipt, MailRequest, MailTool, exit_code_for_status
from trainlab.mail_agent.cli import _parser, main, request_from_args


FIXED_TIME = "2026-07-23T00:00:00Z"


def request(mode: str, **overrides) -> MailRequest:
    values = {"mode": mode, "subject_id": 7, "invocation_id": "inv-01", "requested_at_utc": FIXED_TIME}
    values.update(overrides)
    return MailRequest(**values)


@pytest.mark.parametrize(
    ("mode", "kwargs"),
    [
        ("run", {"max_items": 3, "deadline_seconds": 20}),
        ("poll", {"max_threads": 3}),
        ("process", {"mail_message_ids": ("message-1",)}),
        ("deliver_response", {"mail_response_artifact_ids": ("response-1",)}),
        ("reconcile", {"mail_delivery_ids": ("delivery-1",)}),
        ("status", {"mail_message_ids": ("message-1",)}),
    ],
)
def test_request_modes_are_valid_and_have_stable_run_keys(mode: str, kwargs: dict[str, object]) -> None:
    first = request(mode, **kwargs)
    second = request(mode, **kwargs)
    assert first.stable_run_key == second.stable_run_key == f"mail:7:{mode}:inv-01"


@pytest.mark.parametrize(
    ("mode", "kwargs", "error"),
    [
        ("run", {"mail_message_ids": ("message-1",)}, "mail_message_ids_not_allowed_for_run"),
        ("poll", {"deadline_seconds": 1}, "deadline_seconds_not_allowed_for_poll"),
        ("process", {}, "process_requires_exactly_one_mail_message_id"),
        ("deliver_response", {}, "deliver_response_requires_exactly_one_mail_response_artifact_id"),
        ("reconcile", {"mail_delivery_ids": ("a", "b")}, "reconcile_accepts_at_most_one_mail_delivery_id"),
        ("status", {"mail_message_ids": ("a", "b")}, "status_accepts_at_most_one_mail_message_id"),
    ],
)
def test_request_mode_fields_are_mutually_exclusive(mode: str, kwargs: dict[str, object], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        request(mode, **kwargs)


def test_status_run_key_is_a_read_only_selector_not_a_write_run_identity() -> None:
    selected = request("status", run_key="mail:7:poll:historical-invocation")
    assert selected.run_key == "mail:7:poll:historical-invocation"
    assert selected.stable_run_key == "mail:7:status:inv-01"
    assert MailTool().execute(selected).run_key == selected.run_key
    with pytest.raises(ValueError, match="run_key_not_allowed_for_poll"):
        request("poll", run_key="mail:7:poll:historical-invocation")


def test_request_surface_rejects_forbidden_provider_and_content_fields() -> None:
    with pytest.raises(TypeError):
        MailRequest(mode="status", subject_id=7, invocation_id="inv", requested_at_utc=FIXED_TIME, recipient="outside@example.invalid")  # type: ignore[call-arg]
    payload = request("status").to_dict()
    for forbidden in ("recipient", "label", "query", "mcp_tool", "harness_path", "body", "deliver_artifacts"):
        assert forbidden not in payload


@pytest.mark.parametrize(
    ("status", "code"),
    [("succeeded", 0), ("unchanged", 0), ("partial", 10), ("deferred", 11), ("lock_busy", 12), ("auth_required", 20), ("rejected", 21), ("failed", 22)],
)
def test_receipt_exit_codes_are_frozen(status: str, code: int) -> None:
    assert exit_code_for_status(status) == code


class SpyService:
    def __init__(self) -> None:
        self.requests: list[MailRequest] = []

    def execute(self, item: MailRequest) -> MailReceipt:
        self.requests.append(item)
        return MailReceipt(
            run_key=item.run_key if item.mode == "status" and item.run_key else item.stable_run_key,
            invocation_id=item.invocation_id,
            mode=item.mode,
            status="unchanged",
            started_at_utc=item.requested_at_utc,
            completed_at_utc=FIXED_TIME,
        )


def test_api_and_cli_share_the_same_mail_tool_service_boundary(capsys: pytest.CaptureFixture[str]) -> None:
    spy = SpyService()
    tool = MailTool(spy)
    api_request = request("status")
    assert tool.execute(api_request).status == "unchanged"
    code = main(["--subject-id", "7", "--invocation-id", "inv-cli", "status"], tool=tool)
    stdout = capsys.readouterr().out
    assert code == 0
    assert len(spy.requests) == 2
    assert spy.requests[0] == api_request
    assert spy.requests[1].mode == "status"
    assert json.loads(stdout)["run_key"] == "mail:7:status:inv-cli"


def test_mail_cli_module_is_an_executable_entrypoint() -> None:
    process = subprocess.run(
        [sys.executable, "-m", "trainlab.mail_agent.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert process.returncode == 0
    assert "TrainLab fourth-layer mail tool" in process.stdout


def test_cli_parser_exposes_only_frozen_arguments_and_builds_one_request() -> None:
    parser = _parser()
    args = parser.parse_args(["--subject-id", "7", "--invocation-id", "inv-02", "process", "--message-id", "message-1", "--dependency-artifact-id", "artifact-1"])
    built = request_from_args(args, requested_at_utc=FIXED_TIME)
    assert built.mail_message_ids == ("message-1",)
    assert built.dependency_analysis_artifact_ids == ("artifact-1",)
    help_text = parser.format_help()
    for forbidden in ("--recipient", "--label", "--query", "--mcp-tool", "--harness", "--body", "deliver-artifacts", "--daemon", "--watch", "--schedule", "--interval"):
        assert forbidden not in help_text
    status = request_from_args(parser.parse_args(["--subject-id", "7", "--invocation-id", "status-inv", "status", "--run-key", "mail:7:poll:historical-invocation"]), requested_at_utc=FIXED_TIME)
    assert status.run_key == "mail:7:poll:historical-invocation"
    assert status.stable_run_key == "mail:7:status:status-inv"


def test_boundary_tool_has_no_background_lifecycle() -> None:
    before = {thread.ident for thread in threading.enumerate()}
    receipt = MailTool().execute(request("status"))
    after = {thread.ident for thread in threading.enumerate()}
    assert receipt.status == "failed"
    assert receipt.errors[0]["code"] == "mail_agent_not_implemented"
    assert after == before


def test_request_and_receipt_schemas_are_strict_and_match_serialization() -> None:
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    request_schema = json.loads((root / "harness/schemas/mail_request.schema.json").read_text())
    receipt_schema = json.loads((root / "harness/schemas/mail_receipt.schema.json").read_text())
    item = request("status")
    receipt = MailTool().execute(item)
    assert not list(Draft202012Validator(request_schema).iter_errors(item.to_dict()))
    assert not list(Draft202012Validator(receipt_schema).iter_errors(receipt.to_dict()))
    invalid = {**item.to_dict(), "recipient": "outside@example.invalid"}
    assert list(Draft202012Validator(request_schema).iter_errors(invalid))
