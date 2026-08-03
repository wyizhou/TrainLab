"""Finite, testable Supervisor runtime loop for Layer 5.

This is deliberately a small driver around the S5-04 lease and S5-07 queue.
It owns no daemon installation, provider client, or unbounded worker thread.
Production services can call :meth:`run`; tests use :meth:`run_once`.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import socket
import threading
from typing import Callable, Protocol

from .lease import LeaseError


_EXPOSED_LEASE_ERROR_CODES = frozenset({"lease_clock_anomaly"})


class Lease(Protocol):
    state: str
    def start(self): ...
    def heartbeat(self): ...
    def request_stop(self, signum: int | None = None) -> None: ...
    def stop(self): ...


class Queue(Protocol):
    def tick(self, config): ...
    def stop(self) -> None: ...


class WatchdogNotifier(Protocol):
    """A deployment adapter may notify systemd; tests use an in-memory fake."""
    def notify(self, state: str) -> None: ...


class SystemdNotifier:
    """Minimal sd_notify adapter; inert outside a systemd service."""

    def __init__(self, address: str | None = None) -> None:
        candidate = os.environ.get("NOTIFY_SOCKET") if address is None else address
        self._address = candidate if isinstance(candidate, str) and candidate else None
        self._ready = False

    def notify(self, state: str) -> None:
        if self._address is None:
            return
        active = state in {"active", "idle", "claimed"}
        fields = [f"STATUS=TrainLab Supervisor {state}"]
        if active and not self._ready:
            fields.append("READY=1")
            self._ready = True
        if active:
            fields.append("WATCHDOG=1")
        address = "\0" + self._address[1:] if self._address.startswith("@") else self._address
        client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            client.connect(address)
            client.sendall("\n".join(fields).encode("utf-8"))
        finally:
            client.close()


@dataclass(frozen=True, slots=True)
class SupervisorReceipt:
    status: str
    cycles: int
    dispatched: int
    error_code: str | None = None
    failure_phase: str | None = None

    def as_json_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"schema_version": "1", "status": self.status, "cycles": self.cycles, "dispatched": self.dispatched, "error_code": self.error_code}
        if self.failure_phase is not None:
            result["failure_phase"] = self.failure_phase
        return result


@dataclass(frozen=True, slots=True)
class BusinessIncidentEvents:
    """Durable incident changes emitted by one completed business workflow."""

    opened: tuple[str, ...] = ()
    recovered: tuple[str, ...] = ()


class SupervisorRuntime:
    """Cooperatively driven Supervisor with no hidden background lifecycle."""

    def __init__(
        self,
        supervisor: Lease,
        queue: Queue,
        config: object,
        *,
        dispatch: Callable[[object], object],
        watchdog: WatchdogNotifier | None = None,
        incident_notifier: Callable[[str], None] | None = None,
        incident_recovery_notifier: Callable[[str], None] | None = None,
        business_failure_handler: Callable[
            [object, object], str | BusinessIncidentEvents | None
        ] | None = None,
    ) -> None:
        self._supervisor, self._queue, self._config = supervisor, queue, config
        self._dispatch, self._watchdog = dispatch, watchdog
        self._incident_notifier = incident_notifier
        self._incident_recovery_notifier = incident_recovery_notifier
        self._business_failure_handler = business_failure_handler
        self._stopped = False
        self._started = False

    def request_stop(self, signum: int | None = None) -> None:
        self._stopped = True
        self._queue.stop()
        self._supervisor.request_stop(signum)

    def run_once(self) -> SupervisorReceipt:
        if self._stopped:
            return SupervisorReceipt("stopped", 0, 0)
        try:
            if not self._started:
                try:
                    lease = self._supervisor.start()
                except LeaseError as exc:
                    return self._lease_failure(exc, "lease_start")
                self._started = True
                if getattr(lease, "state", None) != "active":
                    self._notify("passive")
                    return SupervisorReceipt("passive", 0, 0)
            try:
                heartbeat = self._supervisor.heartbeat()
            except LeaseError as exc:
                return self._lease_failure(exc, "lease_heartbeat")
            if getattr(heartbeat, "state", None) != "active":
                self._notify("lease_lost")
                return SupervisorReceipt("lease_lost", 1, 0)
            tick = self._queue.tick(self._config)
            self._notify_incidents(getattr(tick, "incidents", ()))
            if getattr(tick, "status", None) == "claimed" and getattr(tick, "claim", None) is not None:
                outcome = self._dispatch_with_keepalive(tick.claim)
                if outcome == "stopped":
                    self._notify("stopped")
                    return SupervisorReceipt("stopped", 1, 1)
                if outcome == "lease_lost":
                    self._notify("lease_lost")
                    return SupervisorReceipt("lease_lost", 1, 1)
                if outcome == "dispatch_failed":
                    self._notify("error")
                    return SupervisorReceipt("failed", 1, 1, "supervisor_dispatch_failed")
                if outcome == "keepalive_failed":
                    self._notify("error")
                    return SupervisorReceipt("failed", 1, 1, "supervisor_keepalive_failed")
                self._notify("active")
                return SupervisorReceipt("active", 1, 1)
            self._notify(str(getattr(tick, "status", "idle")))
            return SupervisorReceipt(str(getattr(tick, "status", "idle")), 1, 0)
        except Exception:
            self._notify("error")
            return SupervisorReceipt("failed", 1, 0, "supervisor_cycle_failed")

    def _lease_failure(self, exc: LeaseError, phase: str) -> SupervisorReceipt:
        self._notify("error")
        error_code = exc.args[0] if len(exc.args) == 1 and exc.args[0] in _EXPOSED_LEASE_ERROR_CODES else "supervisor_lease_failed"
        return SupervisorReceipt("failed", 1, 0, error_code, phase)

    def _dispatch_with_keepalive(self, claim: object) -> str:
        """Dispatch exactly one synchronous claim while renewing its lease.

        The helper thread has authority only to heartbeat this existing lease.
        It never dispatches business work and is joined before this method
        returns, so no keepalive survives a completed, failed, or stopped run.
        """
        interval = self._keepalive_interval()
        if interval is None:
            return "keepalive_failed"
        stop = threading.Event()
        lease_lost = threading.Event()
        keepalive_failed = threading.Event()

        def renew() -> None:
            while not stop.wait(interval):
                if self._stopped:
                    return
                try:
                    renewed = self._supervisor.heartbeat()
                except Exception:
                    keepalive_failed.set()
                    return
                if getattr(renewed, "state", None) != "active":
                    lease_lost.set()
                    return

        worker = threading.Thread(target=renew, name="trainlab-lease-keepalive", daemon=False)
        worker.start()
        dispatch_failed = False
        try:
            result = self._dispatch(claim)
            if self._business_failure_handler is not None:
                events = self._business_failure_handler(claim, result)
                if isinstance(events, str):
                    self._notify_incident_key(events)
                elif isinstance(events, BusinessIncidentEvents):
                    for key in events.opened:
                        self._notify_incident_key(key)
                    for key in events.recovered:
                        self._notify_recovery_key(key)
        except Exception:
            dispatch_failed = True
        finally:
            stop.set()
            worker.join()
        if self._stopped:
            return "stopped"
        if lease_lost.is_set():
            return "lease_lost"
        if keepalive_failed.is_set():
            return "keepalive_failed"
        if dispatch_failed:
            return "dispatch_failed"
        return "active"

    def _keepalive_interval(self) -> float | None:
        interval = getattr(self._config, "heartbeat_interval_seconds", None)
        ttl = getattr(self._config, "lease_ttl_seconds", None)
        if (
            isinstance(interval, bool)
            or isinstance(ttl, bool)
            or not isinstance(interval, (int, float))
            or not isinstance(ttl, (int, float))
            or not 0 < interval < ttl
        ):
            return None
        return float(interval)

    def run(self, *, max_cycles: int | None = None, wait: Callable[[float], None] | None = None, wait_seconds: float = 1.0) -> SupervisorReceipt:
        if max_cycles is not None and (type(max_cycles) is not int or max_cycles < 1):
            return SupervisorReceipt("failed", 0, 0, "supervisor_cycle_limit_invalid")
        if not isinstance(wait_seconds, (int, float)) or wait_seconds <= 0:
            return SupervisorReceipt("failed", 0, 0, "supervisor_wait_invalid")
        cycles = dispatched = 0
        last = SupervisorReceipt("stopped", 0, 0)
        while not self._stopped and (max_cycles is None or cycles < max_cycles):
            last = self.run_once(); cycles += 1; dispatched += last.dispatched
            if last.status in {"failed", "passive", "lease_lost", "stopped"}:
                break
            if wait is not None and not self._stopped and (max_cycles is None or cycles < max_cycles):
                wait(float(wait_seconds))
        return SupervisorReceipt(last.status, cycles, dispatched, last.error_code, last.failure_phase)

    def stop(self) -> SupervisorReceipt:
        self.request_stop()
        try:
            self._supervisor.stop()
        except Exception:
            return SupervisorReceipt("failed", 0, 0, "supervisor_stop_failed")
        self._notify("stopped")
        return SupervisorReceipt("stopped", 0, 0)

    def _notify(self, state: str) -> None:
        if self._watchdog is None:
            return
        try:
            self._watchdog.notify(state)
        except Exception:
            # A notifier is observational; it must not make a valid lease unsafe.
            return

    def _notify_incidents(self, incidents: object) -> None:
        if self._incident_notifier is None or not isinstance(
            incidents, (tuple, list)
        ):
            return
        for incident in incidents:
            key = getattr(incident, "incident_key", None)
            if not isinstance(key, str):
                continue
            self._notify_incident_key(key)

    def _notify_incident_key(self, key: str) -> None:
        if self._incident_notifier is None:
            return
        try:
            self._incident_notifier(key)
        except Exception:
            # The incident is already durable. Alert failure is reconciled
            # later and must not break lease safety.
            return

    def _notify_recovery_key(self, key: str) -> None:
        if self._incident_recovery_notifier is None:
            return
        try:
            self._incident_recovery_notifier(key)
        except Exception:
            # Recovery is already durable and the alert has its own
            # idempotency key, so notification failure cannot undo it.
            return
