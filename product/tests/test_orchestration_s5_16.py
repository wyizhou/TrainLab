from __future__ import annotations

import argparse
import json
import threading

from trainlab.orchestration.cli import (
    _supervisor_exit_code,
    add_root_subparsers,
    dispatch,
    execute,
)
from trainlab.orchestration.lease import LeaseError
from trainlab.orchestration.operations import OperatorOperations, RedactingAuditLogger
from trainlab.orchestration.supervisor import (
    BusinessIncidentEvents,
    SupervisorRuntime,
    SystemdNotifier,
)


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


class RuntimeConfig:
    lease_ttl_seconds = 90
    heartbeat_interval_seconds = 1


def test_supervisor_is_cooperative_and_has_no_hidden_background_loop() -> None:
    lease, queue, watchdog, calls, incidents = (
        Lease(), Queue(), Watchdog(), [], []
    )
    runtime = SupervisorRuntime(
        lease, queue, RuntimeConfig(), dispatch=calls.append, watchdog=watchdog,
        incident_notifier=incidents.append,
    )
    result = runtime.run(max_cycles=2, wait=lambda _: None)
    assert result.cycles == 2 and result.dispatched == 1 and calls == ["fixed-workflow"]
    assert incidents == ["scheduler:test"]
    assert watchdog.states and runtime.stop().status == "stopped" and lease.stopped and queue.stopped


class FailingLease(Lease):
    def __init__(self, phase: str, error: Exception):
        super().__init__()
        self.phase = phase
        self.error = error

    def start(self):
        if self.phase == "lease_start":
            raise self.error
        return super().start()

    def heartbeat(self):
        if self.phase == "lease_heartbeat":
            raise self.error
        return super().heartbeat()


def test_controlled_lease_clock_anomaly_preserves_failure_phase() -> None:
    for phase in ("lease_start", "lease_heartbeat"):
        queue, watchdog, dispatched = Queue(), Watchdog(), []
        runtime = SupervisorRuntime(
            FailingLease(phase, LeaseError("lease_clock_anomaly")),
            queue,
            RuntimeConfig(),
            dispatch=dispatched.append,
            watchdog=watchdog,
        )

        result = runtime.run(max_cycles=3, wait=lambda _: None)

        assert result.status == "failed"
        assert result.cycles == 1 and result.dispatched == 0
        assert result.error_code == "lease_clock_anomaly"
        assert result.failure_phase == phase
        assert result.as_json_dict()["failure_phase"] == phase
        assert watchdog.states == ["error"]
        assert not queue.claimed and not dispatched


def test_safe_operational_lease_errors_preserve_failure_phase() -> None:
    for error_code in ("lease_database_unavailable", "lease_ownership_lost"):
        result = SupervisorRuntime(
            FailingLease("lease_heartbeat", LeaseError(error_code)),
            Queue(),
            RuntimeConfig(),
            dispatch=lambda _: None,
        ).run_once()

        assert result.status == "failed"
        assert result.error_code == error_code
        assert result.failure_phase == "lease_heartbeat"


def test_untrusted_lease_error_is_redacted_and_other_errors_stay_generic() -> None:
    result = SupervisorRuntime(
        FailingLease("lease_start", LeaseError("untrusted-detail")),
        Queue(),
        RuntimeConfig(),
        dispatch=lambda _: None,
    ).run_once()
    assert result.error_code == "supervisor_lease_failed"
    assert "untrusted-detail" not in json.dumps(result.as_json_dict())

    generic = SupervisorRuntime(
        FailingLease("lease_start", RuntimeError("private detail")),
        Queue(),
        RuntimeConfig(),
        dispatch=lambda _: None,
    ).run_once()
    assert generic.error_code == "supervisor_cycle_failed"
    assert generic.failure_phase is None


class BlockingLease(Lease):
    def __init__(self, *, lose_on: int | None = None, raise_on: int | None = None):
        super().__init__(); self.count = 0; self.lose_on = lose_on; self.raise_on = raise_on; self.renewed = threading.Event(); self.second_heartbeat = threading.Event()
    def heartbeat(self):
        self.count += 1
        if self.count >= 2:
            self.second_heartbeat.set()
        if self.raise_on == self.count:
            raise RuntimeError("renewal failed")
        if self.lose_on == self.count:
            return LeaseResult("passive")
        if self.count >= 3:
            self.renewed.set()
        return LeaseResult("active")


class SingleClaimQueue(Queue):
    def tick(self, config):
        if self.claimed:
            return type("Tick", (), {"status": "idle", "claim": None, "incidents": ()})()
        self.claimed = True
        return type("Tick", (), {"status": "claimed", "claim": "one", "incidents": ()})()


class FastRuntimeConfig:
    lease_ttl_seconds = 90
    heartbeat_interval_seconds = 0.001


def _no_keepalive_thread() -> bool:
    return not any(item.name == "trainlab-lease-keepalive" and item.is_alive() for item in threading.enumerate())


def test_dispatch_keepalive_renews_while_a_synchronous_dispatch_is_blocked() -> None:
    lease, queue = BlockingLease(), SingleClaimQueue()
    release = threading.Event()
    dispatched: list[object] = []
    def dispatch(claim):
        dispatched.append(claim)
        assert lease.renewed.wait(1)
        release.set()
    result = SupervisorRuntime(lease, queue, FastRuntimeConfig(), dispatch=dispatch).run_once()
    assert result.status == "active" and result.dispatched == 1 and dispatched == ["one"]
    assert lease.count >= 3 and release.is_set() and _no_keepalive_thread()


def test_keepalive_lease_loss_or_failure_stops_after_current_dispatch_and_reaps_thread() -> None:
    for lease, expected, error_code in (
        (BlockingLease(lose_on=2), "lease_lost", None),
        (BlockingLease(raise_on=2), "failed", "supervisor_keepalive_failed"),
    ):
        queue = SingleClaimQueue()
        completed = threading.Event()
        def dispatch(_claim):
            assert lease.second_heartbeat.wait(1)
            completed.set()
        runtime = SupervisorRuntime(lease, queue, FastRuntimeConfig(), dispatch=dispatch)
        result = runtime.run(max_cycles=2, wait=lambda _: None)
        assert result.status == expected and result.error_code == error_code
        assert result.dispatched == 1 and completed.is_set()
        assert _no_keepalive_thread() and queue.claimed


def test_dispatch_exception_and_stop_reap_the_keepalive_thread() -> None:
    for action, expected, error_code in (
        ("raise", "failed", "supervisor_dispatch_failed"),
        ("stop", "stopped", None),
    ):
        lease, queue = BlockingLease(), SingleClaimQueue()
        runtime: SupervisorRuntime
        def dispatch(_claim):
            if action == "raise":
                raise RuntimeError("dispatch failed")
            runtime.request_stop()
        runtime = SupervisorRuntime(lease, queue, FastRuntimeConfig(), dispatch=dispatch)
        result = runtime.run_once()
        assert result.status == expected and result.error_code == error_code
        assert result.dispatched == 1 and _no_keepalive_thread()


def test_completed_business_failure_is_recorded_and_does_not_stop_supervisor() -> None:
    lease, queue = Lease(), SingleClaimQueue()
    observed: list[tuple[object, object]] = []
    incidents: list[str] = []
    runtime = SupervisorRuntime(
        lease,
        queue,
        RuntimeConfig(),
        dispatch=lambda _claim: {"status": "failed"},
        business_failure_handler=lambda claim, outcome: (
            observed.append((claim, outcome)) or "workflow:failed:morning:fixed"
        ),
        incident_notifier=incidents.append,
    )

    result = runtime.run(max_cycles=2, wait=lambda _: None)

    assert result.status == "idle" and result.cycles == 2 and result.dispatched == 1
    assert observed == [("one", {"status": "failed"})]
    assert incidents == ["workflow:failed:morning:fixed"]


def test_business_incident_open_and_recovery_notifications_are_routed_separately() -> None:
    opened: list[str] = []
    recovered: list[str] = []
    runtime = SupervisorRuntime(
        Lease(),
        SingleClaimQueue(),
        RuntimeConfig(),
        dispatch=lambda _claim: {"status": "succeeded"},
        business_failure_handler=lambda _claim, _outcome: BusinessIncidentEvents(
            opened=("workflow:failed:mail:one",),
            recovered=("workflow:failed:mail:older",),
        ),
        incident_notifier=opened.append,
        incident_recovery_notifier=recovered.append,
    )

    result = runtime.run_once()

    assert result.status == "active"
    assert opened == ["workflow:failed:mail:one"]
    assert recovered == ["workflow:failed:mail:older"]


def test_business_failure_persistence_error_remains_a_supervisor_failure() -> None:
    runtime = SupervisorRuntime(
        Lease(),
        SingleClaimQueue(),
        RuntimeConfig(),
        dispatch=lambda _claim: {"status": "failed"},
        business_failure_handler=lambda _claim, _outcome: (_ for _ in ()).throw(RuntimeError()),
    )

    result = runtime.run_once()

    assert result.status == "failed"


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
