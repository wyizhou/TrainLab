from __future__ import annotations

import json
import threading

import pytest

from trainlab.cli import main as root_main
from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.mail_agent.application import MailApplicationService, MailApplicationStages
from trainlab.mail_agent.cli import main as mail_main
from trainlab.mail_agent.contracts import MailCounts, MailReceipt, MailRequest, MailTool


NOW = "2026-07-27T00:00:00Z"


def request(mode="run", **changes):
    values = dict(mode=mode, subject_id=7, invocation_id="inv-1", requested_at_utc=NOW)
    values.update(changes)
    return MailRequest(**values)


def receipt(request, *, status="succeeded", **changes):
    values = dict(run_key=request.run_key if request.mode == "status" and request.run_key else request.stable_run_key, invocation_id=request.invocation_id, mode=request.mode, status=status, started_at_utc=NOW, completed_at_utc=NOW)
    values.update(changes)
    return MailReceipt(**values)


class Stage:
    def __init__(self, kind, outcomes=None): self.kind=kind; self.outcomes=outcomes or {}; self.requests=[]
    def execute(self, item):
        self.requests.append(item)
        key=item.mail_message_ids[0] if item.mail_message_ids else item.mail_response_artifact_ids[0] if item.mail_response_artifact_ids else item.mail_delivery_ids[0] if item.mail_delivery_ids else "default"
        value=self.outcomes.get(key, self.outcomes.get("default"))
        if isinstance(value, Exception): raise value
        if isinstance(value, MailReceipt): return value
        return receipt(item, **(value or {}))


class Queue:
    def __init__(self, items): self.items=items; self.calls=[]
    def queued_message_ids(self, *, subject_id, limit): self.calls.append((subject_id,limit)); return self.items


def app(*, queued=("m2","m1"), process=None, deliver=None, reconcile=None, status=None):
    poll=Stage("poll"); process_stage=Stage("process", process); delivery=Stage("delivery", deliver); recovery=Stage("reconcile", reconcile); local_status=Stage("status", status); queue=Queue(queued)
    service=MailApplicationService(MailApplicationStages(poll,process_stage,delivery,recovery,local_status,queue), monotonic=lambda: 0.0, clock=lambda: NOW)
    return service, (poll,process_stage,delivery,recovery,local_status,queue)


def test_run_polls_then_processes_stably_and_delivers_exact_response() -> None:
    service, stages = app(process={"m1":{"processed_message_ids":("m1",),"mail_response_artifact_ids":("r1",),"counts":MailCounts(processed=1,responses_accepted=1)}}, deliver={"r1":{"mail_delivery_ids":("d1",),"counts":MailCounts(deliveries_sent=1)}})
    result=service.execute(request(max_items=2,deadline_seconds=30))
    assert result.status == "succeeded" and result.counts.processed == 1
    assert [item.mail_message_ids for item in stages[1].requests] == [("m1",),("m2",)]
    assert stages[2].requests[0].mail_response_artifact_ids == ("r1",)
    assert result.mail_delivery_ids == ("d1",)


def test_run_continues_after_one_item_failure_and_reconciles_without_regeneration() -> None:
    service, stages = app(process={"m1":RuntimeError("x"),"m2":{"mail_response_artifact_ids":("r2",),"counts":MailCounts(processed=1)}}, deliver={"r2":{"mail_delivery_ids":("d2",),"next_action":"reconcile_delivery"}}, reconcile={"d2":{"counts":MailCounts(deliveries_already_sent=1)}})
    result=service.execute(request(max_items=2,deadline_seconds=30))
    assert result.status == "partial"
    assert [item.mail_message_ids for item in stages[1].requests] == [("m1",),("m2",)]
    assert [item.mail_delivery_ids for item in stages[3].requests] == [("d2",)]


def test_status_only_calls_local_status_stage() -> None:
    service, stages = app(status={"default":{"status":"unchanged"}})
    result=service.execute(request("status"))
    assert result.status == "unchanged"
    assert len(stages[4].requests) == 1
    assert all(not stage.requests for stage in stages[:4])


def test_invalid_stage_receipt_and_invalid_run_limits_fail_closed() -> None:
    service, stages = app()
    stages[4].outcomes["default"] = MailReceipt(run_key="wrong",invocation_id="bad",mode="status",status="succeeded",started_at_utc=NOW,completed_at_utc=NOW)
    assert service.execute(request("status")).status == "failed"
    with pytest.raises(Exception, match="mail_run_max_items_invalid"):
        service.execute(request(max_items=0))


def test_cli_stdout_is_one_receipt_and_root_registration_uses_injected_tool(capsys) -> None:
    service, _ = app(status={"default":{"status":"unchanged"}})
    tool=MailTool(service)
    assert mail_main(["--subject-id","7","--invocation-id","cli","status"],tool=tool) == 0
    assert list(json.loads(capsys.readouterr().out).keys())
    assert root_main(["mail","--subject-id","7","--invocation-id","root","status"],mail_tool=tool) == 0
    value=json.loads(capsys.readouterr().out)
    assert value["mode"] == "status" and value["status"] == "unchanged"


def test_root_status_needs_no_mail_configuration_or_background_thread(
    capsys, monkeypatch, tmp_path
) -> None:
    data_root = tmp_path / "foundation"
    foundation = FoundationConfig(
        data_root,
        data_root / "data.db",
        data_root / "raw",
        data_root / "state",
        data_root / "state" / "foundation-ready.json",
        data_root / "state" / "locks" / "foundation.lock",
    )
    assert FoundationTool(foundation).execute(
        FoundationRequest("init", "mail-status-fixture", NOW)
    ).ready
    monkeypatch.setattr(
        "trainlab.mail_agent.runtime.FoundationConfig.load",
        lambda _root: foundation,
    )
    before={item.ident for item in threading.enumerate()}
    code=root_main(["mail","--subject-id","7","--invocation-id","offline","status"])
    value=json.loads(capsys.readouterr().out)
    assert code == 0 and value["mode"] == "status"
    assert value["status"] in {"succeeded", "unchanged"}
    assert {item.ident for item in threading.enumerate()} == before


@pytest.mark.parametrize("argv", (
    ["mail","--subject-id","7","--invocation-id","x","run","--daemon"],
    ["mail","--subject-id","7","--invocation-id","x","poll","--deadline-seconds","2"],
))
def test_root_rejects_non_frozen_or_cross_mode_arguments(argv) -> None:
    with pytest.raises(SystemExit): root_main(argv)
