"""Restricted Layer-5 CLI parser and dispatch adapter.

The root CLI owns installation of these subparsers.  This module never opens a
provider, accepts an arbitrary path or command, nor writes lower-layer tables.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Protocol

from .operations import OperationReceipt, OperatorOperations


_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FORBIDDEN_KEYS = frozenset({"body", "html", "payload", "prompt", "token", "password", "secret", "recipient", "harness", "command", "sql", "path", "email"})


class OrchestrationCliApplication(Protocol):
    def supervisor_run(self) -> object: ...
    def doctor(self) -> object: ...
    def run_workflow(self, workflow_kind: str, *, logical_date: str | None, invocation_id: str | None) -> object: ...
    def retry(self, workflow_run_id: str) -> object: ...
    def reconcile(self, workflow_run_id: str | None) -> object: ...
    def status(self, workflow_run_id: str | None) -> object: ...


def add_root_subparsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Attach the fixed fifth-layer public surface to the root parser."""
    supervisor = subparsers.add_parser("supervisor")
    supervisor_sub = supervisor.add_subparsers(dest="supervisor_mode", required=True)
    supervisor_sub.add_parser("run")
    supervisor_sub.add_parser("doctor")

    orchestrate = subparsers.add_parser("orchestrate")
    orchestrate_sub = orchestrate.add_subparsers(dest="orchestrate_mode", required=True)
    run = orchestrate_sub.add_parser("run")
    run_sub = run.add_subparsers(dest="workflow_kind", required=True)
    morning = run_sub.add_parser("morning"); morning.add_argument("--date")
    weekly = run_sub.add_parser("weekly"); weekly.add_argument("--as-of")
    run_sub.add_parser("mail")
    run_sub.add_parser("health-check")
    for parser in (morning, weekly, run_sub.choices["mail"], run_sub.choices["health-check"]):
        parser.add_argument("--invocation-id")
    retry = orchestrate_sub.add_parser("retry"); retry.add_argument("--workflow-run-id", required=True)
    reconcile = orchestrate_sub.add_parser("reconcile"); reconcile.add_argument("--workflow-run-id")
    status = orchestrate_sub.add_parser("status"); status.add_argument("--workflow-run-id"); status.add_argument("--json", action="store_true")
    for name in ("acknowledge", "suppress"):
        action = orchestrate_sub.add_parser(name); action.add_argument("--incident-key", required=True)
    for name in ("resume", "takeover"):
        action = orchestrate_sub.add_parser(name); action.add_argument("--workflow-run-id", required=True)


def _safe(value: Any) -> Any:
    if hasattr(value, "as_json_dict"):
        value = value.as_json_dict()
    elif is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key).lower()
            if any(part in name for part in _FORBIDDEN_KEYS):
                continue
            result[str(key)] = _safe(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(type(value).__name__)


def _validate(value: str | None, *, date: bool = False) -> str | None:
    if value is None:
        return None
    expression = _DATE if date else _ID
    if not isinstance(value, str) or expression.fullmatch(value) is None:
        raise ValueError("orchestration_cli_argument_invalid")
    return value


def _receipt(status: str, *, error_code: str | None = None, result: object | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"schema_version": "1", "status": status, "error_code": error_code}
    if result is not None:
        payload["result"] = _safe(result)
    return payload


def _local_operator_id() -> str:
    """Bound manual audit identity to the invoking OS account, not CLI text."""
    uid = os.getuid()
    return f"uid-{uid}"


def dispatch(args: argparse.Namespace, *, application: OrchestrationCliApplication | None, operations: OperatorOperations | None = None) -> tuple[int, dict[str, Any]]:
    """Execute exactly one constrained operation and return a data-free receipt."""
    try:
        command = getattr(args, "command", None)
        if command == "supervisor":
            if application is None:
                return 2, _receipt("rejected", error_code="orchestration_application_required")
            if args.supervisor_mode == "run":
                return 0, _receipt("accepted", result=application.supervisor_run())
            if args.supervisor_mode == "doctor":
                return 0, _receipt("accepted", result=application.doctor())
        if command != "orchestrate":
            return 2, _receipt("rejected", error_code="orchestration_cli_command_invalid")
        mode = args.orchestrate_mode
        if mode == "run":
            if application is None:
                return 2, _receipt("rejected", error_code="orchestration_application_required")
            kind = args.workflow_kind
            date = _validate(getattr(args, "date", None) if kind == "morning" else getattr(args, "as_of", None), date=True)
            invocation = _validate(getattr(args, "invocation_id", None))
            return 0, _receipt("accepted", result=application.run_workflow(kind, logical_date=date, invocation_id=invocation))
        if mode in {"retry", "reconcile", "status"}:
            target = _validate(getattr(args, "workflow_run_id", None))
            if application is None:
                return 2, _receipt("rejected", error_code="orchestration_application_required")
            if mode in {"retry", "reconcile"}:
                if operations is None:
                    return 2, _receipt("rejected", error_code="operation_repository_required")
                action = operations.audit(mode, target_id=target or "all", operator_id=_local_operator_id())
                if action.status != "accepted":
                    return 2, _receipt("rejected", error_code=action.error_code, result=action)
            if mode == "retry":
                if target is None:
                    raise ValueError("orchestration_cli_argument_invalid")
                return 0, _receipt("accepted", result={"operation_audit": action.as_json_dict(), "workflow": application.retry(target)})
            if mode == "reconcile":
                return 0, _receipt("accepted", result={"operation_audit": action.as_json_dict(), "workflow": application.reconcile(target)})
            return 0, _receipt("accepted", result=application.status(target))
        if mode in {"acknowledge", "suppress", "resume", "takeover"}:
            if operations is None:
                return 2, _receipt("rejected", error_code="operation_repository_required")
            operator = _local_operator_id()
            target = _validate(getattr(args, "incident_key", None) or getattr(args, "workflow_run_id", None))
            if target is None:
                raise ValueError("orchestration_cli_argument_invalid")
            if mode == "acknowledge":
                outcome = operations.acknowledge(target, operator_id=operator)
            elif mode == "suppress":
                outcome = operations.suppress(target, operator_id=operator)
            else:
                action = "forced_takeover" if mode == "takeover" else "resume"
                outcome = operations.audit(action, target_id=target, operator_id=operator)
            return (0 if outcome.status == "accepted" else 2), _receipt(outcome.status, error_code=outcome.error_code, result=outcome)
        return 2, _receipt("rejected", error_code="orchestration_cli_mode_invalid")
    except (ValueError, AttributeError):
        return 2, _receipt("rejected", error_code="orchestration_cli_argument_invalid")
    except Exception:
        return 2, _receipt("failed", error_code="orchestration_cli_failed")


def execute(args: argparse.Namespace, *, application: OrchestrationCliApplication | None, operations: OperatorOperations | None = None, write: Callable[[str], object] | None = None) -> int:
    """Dispatch once and emit exactly one JSON receipt line."""
    code, receipt = dispatch(args, application=application, operations=operations)
    (write or print)(json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return code
