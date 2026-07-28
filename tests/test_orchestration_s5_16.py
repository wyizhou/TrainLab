from __future__ import annotations

import argparse
import json

from trainlab.orchestration.cli import _supervisor_exit_code, add_root_subparsers, dispatch, execute
from trainlab.orchestration.operations import OperatorOperations, RedactingAuditLogger
from trainlab.orchestration.supervisor import SupervisorRuntime, SystemdNotifier


class App:
    def __init__(self): self.calls = []
    def supervisor_run(self): self.calls.append(("supervisor",)); return {"status": "active", "body": "must not print"}
    def doctor(self): self.calls.append(("doctor",)); return {"status": "ready", "token": "secret"}
    def run_workflow(self, kind, *, logical_date, invocation_id): self.calls.append(("run", kind, logical_date, invocation_id)); return {"workflow_kind": kind, "status": "queued"}
    def retry(self, target): self.calls.append(("retry", target)); return {"status": "queued"}
    def reconcile(self, target): self.calls.append(("reconcile", target)); return {"status": "checked"}
    def status(self, target): self.calls.append(("status", target)); return {"status": "ready", "payload": "hidden"}


def parser():
    root = argparse.ArgumentParser(); sub = root.add_subparsers(dest="command", required=True); add_root_subparsers(sub); return root


def test_public_surface_is_fixed_and_output_is_payload_free() -> None:
    value = parser().parse_args(["orchestrate", "run", "morning", "--date", "2026-07-27", "--invocation-id", "fixed-1"])
    app = App(); code, receipt = dispatch(value, application=app)
    assert code == 0 and app.calls == [("run", "morning", "2026-07-27", "fixed-1")]
    assert receipt["result"] == {"workflow_kind": "morning", "status": "queued"}
    output = []; assert execute(parser().parse_args(["supervisor", "doctor"]), application=app, write=output.append) == 0
    assert len(output) == 1 and "secret" not in output[0] and "token" not in output[0]


def test_supervisor_exit_code_distinguishes_clean_stop_from_abnormal_termination() -> None:
    for status in ("active", "claimed", "idle", "stopped"):
        assert _supervisor_exit_code({"status": status}) == 0
    for status in ("failed", "passive", "lease_lost", "blocked", "unknown"):
        assert _supervisor_exit_code({"status": status}) == 1
    assert _supervisor_exit_code(None) == 1

    args = parser().parse_args(["supervisor", "run"])
    app = App()
    app.supervisor_run = lambda: {"status": "lease_lost"}  # type: ignore[method-assign]
    code, receipt = dispatch(args, application=app)
    assert code == 1 and receipt["result"] == {"status": "lease_lost"}


def test_invalid_inputs_and_unknown_command_are_rejected_without_application_call() -> None:
    app = App()
    args = parser().parse_args(["orchestrate", "run", "weekly", "--as-of", "not-a-date"])
    code, receipt = dispatch(args, application=app)
    assert code == 2 and receipt["error_code"] == "orchestration_cli_argument_invalid" and not app.calls
    bad = argparse.Namespace(command="other")
    assert dispatch(bad, application=app)[1]["status"] == "rejected"


class AuditRepo:
    def __init__(self): self.records = []; self.transitions = []
    def record_health_check(self, **values): self.records.append(values); return len(self.records)
    def transition_incident(self, key, state, *, at_utc): self.transitions.append((key, state))


def test_manual_actions_are_audited_or_rejected_without_repository() -> None:
    rejected = OperatorOperations(None).audit("retry", target_id="workflow-1", operator_id="operator-1")
    assert rejected.status == "rejected" and rejected.error_code == "operation_repository_required"
    repo = AuditRepo(); operations = OperatorOperations(repo)
    accepted = operations.acknowledge("incident-1", operator_id="operator-1")
    assert accepted.status == "accepted" and repo.records[0]["check_kind"] == "operator_action"
    assert repo.transitions == [("incident-1", "acknowledged")]
    suppressed = operations.suppress("incident-2", operator_id="operator-1")
    assert suppressed.status == "accepted"
    assert repo.transitions[-1] == ("incident-2", "suppressed")
    args = parser().parse_args(["orchestrate", "takeover", "--workflow-run-id", "workflow-1"])
    code, receipt = dispatch(args, application=None, operations=operations)
    assert code == 0 and receipt["result"]["action"] == "forced_takeover"
    app = App()
    retry = parser().parse_args(["orchestrate", "retry", "--workflow-run-id", "workflow-1"])
    assert dispatch(retry, application=app, operations=operations)[0] == 0
    assert app.calls == [("retry", "workflow-1")] and len(repo.records) == 4


class LeaseResult:
    def __init__(self, state): self.state = state


class Lease:
    state = "new"
    def __init__(self): self.stopped = False
    def start(self): self.state = "active"; return LeaseResult("active")
    def heartbeat(self): return LeaseResult("active")
    def request_stop(self, signum=None): pass
    def stop(self): self.stopped = True; return LeaseResult("stopped")


class Queue:
    def __init__(self): self.stopped = False; self.claimed = False
    def tick(self, config):
        if not self.claimed:
            self.claimed = True
            incident = type(
                "Incident", (), {"incident_key": "scheduler:test"}
            )()
            return type(
                "Tick", (),
                {
                    "status": "claimed",
                    "claim": "fixed-workflow",
                    "incidents": (incident,),
                },
            )()
        return type(
            "Tick", (), {"status": "idle", "claim": None, "incidents": ()}
        )()
    def stop(self): self.stopped = True


class Watchdog:
    def __init__(self): self.states = []
    def notify(self, value): self.states.append(value)


def test_supervisor_is_cooperative_and_has_no_hidden_background_loop() -> None:
    lease, queue, watchdog, calls, incidents = (
        Lease(), Queue(), Watchdog(), [], []
    )
    runtime = SupervisorRuntime(
        lease, queue, object(), dispatch=calls.append, watchdog=watchdog,
        incident_notifier=incidents.append,
    )
    result = runtime.run(max_cycles=2, wait=lambda _: None)
    assert result.cycles == 2 and result.dispatched == 1 and calls == ["fixed-workflow"]
    assert incidents == ["scheduler:test"]
    assert watchdog.states and runtime.stop().status == "stopped" and lease.stopped and queue.stopped


def test_log_schema_rejects_secrets_and_rotates(tmp_path) -> None:
    logger = RedactingAuditLogger(tmp_path / "logs", max_bytes=1024)
    logger.write("operation", action="retry", status="accepted")
    assert "retry" in (tmp_path / "logs/orchestrator.jsonl").read_text()
    try:
        logger.write("operation", token="secret")
    except ValueError as exc:
        assert str(exc) == "operation_log_field_invalid"
    else:
        raise AssertionError("secret log field accepted")


def test_systemd_notifier_is_inert_without_notify_socket(monkeypatch) -> None:
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    SystemdNotifier().notify("active")
