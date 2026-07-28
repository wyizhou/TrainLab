from __future__ import annotations

import argparse
import json
from datetime import datetime

from .config import load_settings
from .context import build_runtime_input
from .db import connect, migrate, table_counts
from .doctor import run_doctor
from .deploy import finalize_harness, install_services
from .ingest import ingest_daemon, ingest_once
from .runner import prepare, run_analysis
from .scheduler import scheduler_daemon, scheduler_once
from .sync import drive_sync_daemon, sync_once
from .util import json_dumps
from .watchdog import watchdog_daemon, watchdog_once
from .foundation import main as foundation_main
from .garmin.cli import garmin_cli_execute


_GARMIN_EXIT = {
    "succeeded": 0,
    "partial": 10,
    "deferred": 11,
    "lock_busy": 12,
    "auth_required": 20,
    "failed": 21,
}


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None




def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trainlab", description="TrainLab agent harness")
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--development", action="store_true")
    doctor.add_argument("--no-auth", action="store_true")
    sync = subparsers.add_parser("sync")
    sync.add_argument("--daemon", action="store_true")
    ingest = subparsers.add_parser("ingest")
    ingest.add_argument("--daemon", action="store_true")
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--slot", choices=["morning", "evening"], required=True)
    prepare_parser.add_argument("--at")
    prepare_parser.add_argument("--print-json", action="store_true")
    run = subparsers.add_parser("run")
    run.add_argument("--slot", choices=["morning", "evening"], required=True)
    run.add_argument("--at")
    run.add_argument("--analysis-only", action="store_true")
    run.add_argument("--summary-date")
    analysis_route = run.add_mutually_exclusive_group()
    analysis_route.add_argument("--weekly", action="store_true")
    analysis_route.add_argument("--revise-plan", action="store_true")
    analysis_route.add_argument("--regenerate", action="store_true")
    analysis_route.add_argument("--status", action="store_true")
    run.add_argument("--as-of-date")
    run.add_argument("--plan-id", type=int)
    run.add_argument("--reason-event-id", type=int)
    run.add_argument("--effective-date")
    run.add_argument("--artifact-id", type=int)
    run.add_argument("--regenerate-reason")
    run.add_argument("--run-key")
    run.add_argument("--invocation-id")
    run.add_argument("--deliver", action="store_true")
    delivery_recovery = run.add_mutually_exclusive_group()
    delivery_recovery.add_argument("--retry-delivery", type=int)
    delivery_recovery.add_argument("--reconcile-delivery", type=int)
    scheduler = subparsers.add_parser("scheduler")
    scheduler.add_argument("--once", action="store_true")
    watchdog = subparsers.add_parser("watchdog")
    watchdog.add_argument("--once", action="store_true")
    deploy = subparsers.add_parser("deploy")
    deploy.add_argument("--platform", choices=["macos", "linux"])
    deploy.add_argument("--enable", action="store_true")
    subparsers.add_parser("finalize-production")
    subparsers.add_parser("status")
    foundation = subparsers.add_parser("foundation")
    foundation.add_argument("--invocation-id")
    foundation_sub = foundation.add_subparsers(dest="foundation_mode", required=True)
    foundation_sub.add_parser("init")
    foundation_sub.add_parser("status")
    foundation_sub.add_parser("verify")
    foundation_migrate = foundation_sub.add_parser("migrate")
    foundation_migrate.add_argument("--target-version", type=int, required=True)
    from .garmin.cli import add_root_subparser as add_garmin_subparser
    add_garmin_subparser(subparsers)
    from .mail_agent.cli import add_root_subparser
    add_root_subparser(subparsers)
    from .orchestration.cli import add_root_subparsers as add_orchestration_subparsers
    add_orchestration_subparsers(subparsers)
    return parser


def main(argv: list[str] | None = None, *, mail_tool=None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "foundation":
        forwarded = []
        if args.invocation_id:
            forwarded.extend(["--invocation-id", args.invocation_id])
        forwarded.append(args.foundation_mode)
        if args.foundation_mode == "migrate":
            forwarded.extend(["--target-version", str(args.target_version)])
        return foundation_main(forwarded)
    if args.command == "garmin":
        receipt = garmin_cli_execute(args)
        print(receipt.json())
        return _GARMIN_EXIT[receipt.status]
    if args.command == "mail":
        from .mail_agent.cli import mail_cli_execute
        from .mail_agent.contracts import MailTool, exit_code_for_status
        from .mail_agent.runtime import create_mail_application
        receipt = mail_cli_execute(
            args,
            tool=mail_tool or MailTool(create_mail_application()),
        )
        print(receipt.json())
        return exit_code_for_status(receipt.status)
    if args.command in {"supervisor", "orchestrate"}:
        from .orchestration.cli import execute as execute_orchestration
        from .orchestration.production import create_cli_runtime
        application, operations = create_cli_runtime()
        return execute_orchestration(
            args, application=application, operations=operations
        )
    if args.command == "run" and args.analysis_only:
        if args.slot != "morning":
            _parser().error("--analysis-only requires --slot morning")
        if not args.status and not args.invocation_id:
            _parser().error("--analysis-only requires --invocation-id")
        if args.status and args.invocation_id is not None:
            _parser().error("--status does not accept --invocation-id")
        if args.at is not None:
            _parser().error("--analysis-only does not accept --at")
        if args.status and any((
            args.summary_date is not None, args.weekly, args.revise_plan,
            args.regenerate, args.as_of_date is not None, args.plan_id is not None,
            args.reason_event_id is not None, args.effective_date is not None,
            args.artifact_id is not None, args.regenerate_reason is not None,
            args.deliver, args.retry_delivery is not None,
            args.reconcile_delivery is not None,
        )):
            _parser().error("--status does not accept analysis route options")
        if args.regenerate and (
            args.artifact_id is None or args.regenerate_reason is None
        ):
            _parser().error("--regenerate requires --artifact-id and --regenerate-reason")
        if not args.regenerate and (
            args.artifact_id is not None or args.regenerate_reason is not None
        ):
            _parser().error("regeneration options require --regenerate")
        if not args.status and args.run_key is not None:
            _parser().error("--run-key requires --status")
        if args.artifact_id is not None and args.artifact_id <= 0:
            _parser().error("artifact ID must be positive")
        recovery_id = (
            args.retry_delivery
            if args.retry_delivery is not None
            else args.reconcile_delivery
        )
        if recovery_id is not None and recovery_id <= 0:
            _parser().error("delivery ID must be positive")
        if recovery_id is not None and (
            args.summary_date is not None
            or args.weekly
            or args.revise_plan or args.regenerate or args.status
            or args.as_of_date is not None
            or args.plan_id is not None
            or args.reason_event_id is not None
            or args.effective_date is not None
            or args.artifact_id is not None
            or args.regenerate_reason is not None
            or args.run_key is not None
            or args.deliver
        ):
            _parser().error("delivery recovery does not accept analysis route options")
        if args.regenerate and any((
            args.summary_date is not None, args.as_of_date is not None,
            args.plan_id is not None, args.reason_event_id is not None,
            args.effective_date is not None,
        )):
            _parser().error("--regenerate does not accept other analysis route options")
        if args.weekly and args.summary_date is not None:
            _parser().error("--weekly does not accept --summary-date")
        if not args.weekly and args.as_of_date is not None:
            _parser().error("--as-of-date requires --weekly")
        if args.revise_plan and args.summary_date is not None:
            _parser().error("--revise-plan does not accept --summary-date")
        if args.revise_plan and (
            args.plan_id is None or args.reason_event_id is None
        ):
            _parser().error("--revise-plan requires --plan-id and --reason-event-id")
        if not args.revise_plan and (
            args.plan_id is not None
            or args.reason_event_id is not None
            or args.effective_date is not None
        ):
            _parser().error("plan revision options require --revise-plan")
        if (
            args.plan_id is not None
            and args.plan_id <= 0
            or args.reason_event_id is not None
            and args.reason_event_id <= 0
        ):
            _parser().error("plan and reason event IDs must be positive")
        try:
            from .analysis.runtime import (
                run_analysis_only,
                run_analysis_status,
                run_delivery_recovery,
                run_plan_revision_analysis,
                run_regeneration_analysis,
                run_weekly_analysis,
            )
            from .analysis.cli import exit_code_for

            if args.status:
                receipt = run_analysis_status(run_key=args.run_key)
            elif recovery_id is None:
                if args.weekly:
                    receipt = run_weekly_analysis(
                        invocation_id=args.invocation_id,
                        as_of_date=args.as_of_date,
                        deliver=args.deliver,
                    )
                elif args.revise_plan:
                    receipt = run_plan_revision_analysis(
                        invocation_id=args.invocation_id,
                        plan_id=str(args.plan_id),
                        reason_event_id=str(args.reason_event_id),
                        effective_date=args.effective_date,
                        deliver=args.deliver,
                    )
                elif args.regenerate:
                    receipt = run_regeneration_analysis(
                        invocation_id=args.invocation_id,
                        artifact_id=str(args.artifact_id),
                        reason_code=args.regenerate_reason,
                        deliver=args.deliver,
                    )
                else:
                    receipt = run_analysis_only(
                        invocation_id=args.invocation_id,
                        summary_date=args.summary_date,
                        deliver=args.deliver,
                    )
            else:
                receipt = run_delivery_recovery(
                    invocation_id=args.invocation_id,
                    delivery_id=recovery_id,
                    reconcile=args.reconcile_delivery is not None,
                )
        except ValueError as error:
            _parser().error(str(error))
        print(receipt.to_json())
        return exit_code_for(receipt.status)
    if args.command == "run" and (
        args.summary_date is not None or args.invocation_id is not None
        or args.weekly or args.revise_plan or args.regenerate or args.status
        or args.as_of_date is not None
        or args.plan_id is not None or args.reason_event_id is not None
        or args.effective_date is not None or args.artifact_id is not None
        or args.regenerate_reason is not None or args.run_key is not None
        or args.deliver or args.retry_delivery is not None
        or args.reconcile_delivery is not None
    ):
        _parser().error("analysis options require --analysis-only")
    settings = load_settings()
    connection = connect(settings.database_path, busy_timeout_ms=int(settings.values["sqlite"].get("busy_timeout_ms", 10_000)))
    migrate(connection)
    try:
        if args.command == "doctor":
            result = run_doctor(settings, production=not args.development, verify_auth=not args.no_auth)
            print(json_dumps(result, indent=2))
            return 0 if result["ok"] else 1
        if args.command == "sync":
            connection.close()
            if args.daemon:
                drive_sync_daemon(settings)
                return 0
            print(json_dumps(sync_once(settings), indent=2))
            return 0
        if args.command == "ingest":
            connection.close()
            if args.daemon:
                ingest_daemon(settings)
                return 0
            print(json_dumps(ingest_once(settings).as_dict(), indent=2))
            return 0
        if args.command == "prepare":
            payload, path = prepare(settings, connection, slot=args.slot, as_of=_datetime(args.at))
            print(json_dumps(payload if args.print_json else {"run_id": payload["run"]["run_id"], "path": str(path)}, indent=2))
            return 0
        if args.command == "run":
            result = run_analysis(settings, connection, slot=args.slot, as_of=_datetime(args.at))
            print(json_dumps(result))
            return 0 if result["status"] in {"sent", "already_sent"} else 1
        if args.command == "scheduler":
            if args.once:
                print(json_dumps(scheduler_once(settings, connection), indent=2))
                return 0
            connection.close()
            scheduler_daemon(settings, lambda: connect(settings.database_path))
            return 0
        if args.command == "watchdog":
            if args.once:
                print(json_dumps(watchdog_once(settings, connection), indent=2))
                return 0
            connection.close()
            watchdog_daemon(settings, lambda: connect(settings.database_path))
            return 0
        if args.command == "deploy":
            print(json_dumps(install_services(settings, system=args.platform, enable=args.enable), indent=2))
            return 0
        if args.command == "finalize-production":
            print(json_dumps(finalize_harness(settings), indent=2))
            return 0
        if args.command == "status":
            print(json_dumps(table_counts(connection), indent=2))
            return 0
    finally:
        try:
            connection.close()
        except Exception:
            pass
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
