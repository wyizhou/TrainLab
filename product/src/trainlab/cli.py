from __future__ import annotations

import argparse
import json
import sqlite3

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


def _add_analysis_only_arguments(run: argparse.ArgumentParser) -> None:
    """Register the production third-layer route and nothing from the retired runtime."""
    run.add_argument("--slot", choices=["morning", "evening"], required=True)
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
    run.add_argument("--resend-authorization")
    delivery_recovery = run.add_mutually_exclusive_group()
    delivery_recovery.add_argument("--retry-delivery", type=int)
    delivery_recovery.add_argument("--reconcile-delivery", type=int)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trainlab", description="TrainLab five-layer tools"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

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

    run = subparsers.add_parser("run")
    _add_analysis_only_arguments(run)

    from .mail_agent.cli import add_root_subparser as add_mail_subparser
    from .orchestration.cli import add_root_subparsers as add_orchestration_subparsers

    add_mail_subparser(subparsers)
    facts = subparsers.add_parser("facts", help="read-only user-fact browser")
    facts.add_argument("--subject-id", type=int, required=True)
    facts.add_argument(
        "--status",
        choices=["all", "active", "pending", "future", "expired", "revoked"],
        default="all",
    )
    facts.add_argument("--as-of-utc")
    add_orchestration_subparsers(subparsers)
    return parser


def _analysis_receipt(args: argparse.Namespace):
    if not args.analysis_only:
        _parser().error("run requires --analysis-only")
    if args.slot != "morning":
        _parser().error("--analysis-only requires --slot morning")
    if not args.status and not args.invocation_id:
        _parser().error("--analysis-only requires --invocation-id")
    if args.status and args.invocation_id is not None:
        _parser().error("--status does not accept --invocation-id")
    if args.status and any(
        (
            args.summary_date is not None,
            args.weekly,
            args.revise_plan,
            args.regenerate,
            args.as_of_date is not None,
            args.plan_id is not None,
            args.reason_event_id is not None,
            args.effective_date is not None,
            args.artifact_id is not None,
            args.regenerate_reason is not None,
            args.deliver,
            args.resend_authorization is not None,
            args.retry_delivery is not None,
            args.reconcile_delivery is not None,
        )
    ):
        _parser().error("--status does not accept analysis route options")
    if args.regenerate and (args.artifact_id is None or args.regenerate_reason is None):
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
        or args.revise_plan
        or args.regenerate
        or args.status
        or args.as_of_date is not None
        or args.plan_id is not None
        or args.reason_event_id is not None
        or args.effective_date is not None
        or args.artifact_id is not None
        or args.regenerate_reason is not None
        or args.run_key is not None
        or args.deliver
        or args.resend_authorization is not None
    ):
        _parser().error("delivery recovery does not accept analysis route options")
    if args.regenerate and any(
        (
            args.summary_date is not None,
            args.as_of_date is not None,
            args.plan_id is not None,
            args.reason_event_id is not None,
            args.effective_date is not None,
        )
    ):
        _parser().error("--regenerate does not accept other analysis route options")
    if args.weekly and args.summary_date is not None:
        _parser().error("--weekly does not accept --summary-date")
    if args.resend_authorization is not None:
        if not args.weekly:
            _parser().error("--resend-authorization requires --weekly")
        if args.as_of_date is None:
            _parser().error("--resend-authorization requires --as-of-date")
        if args.deliver:
            _parser().error("--resend-authorization does not accept --deliver")
        from .analysis.delivery import ResendAuthorization

        try:
            ResendAuthorization(args.resend_authorization)
        except ValueError as error:
            _parser().error(str(error))
    if not args.weekly and args.as_of_date is not None:
        _parser().error("--as-of-date requires --weekly")
    if args.revise_plan and args.summary_date is not None:
        _parser().error("--revise-plan does not accept --summary-date")
    if args.revise_plan and (args.plan_id is None or args.reason_event_id is None):
        _parser().error("--revise-plan requires --plan-id and --reason-event-id")
    if not args.revise_plan and (
        args.plan_id is not None
        or args.reason_event_id is not None
        or args.effective_date is not None
    ):
        _parser().error("plan revision options require --revise-plan")
    if (args.plan_id is not None and args.plan_id <= 0) or (
        args.reason_event_id is not None and args.reason_event_id <= 0
    ):
        _parser().error("plan and reason event IDs must be positive")

    try:
        from .analysis.cli import exit_code_for
        from .analysis.runtime import (
            run_analysis_only,
            run_analysis_status,
            run_delivery_recovery,
            run_plan_revision_analysis,
            run_regeneration_analysis,
            run_weekly_analysis,
        )

        if args.status:
            receipt = run_analysis_status(run_key=args.run_key)
        elif recovery_id is not None:
            receipt = run_delivery_recovery(
                invocation_id=args.invocation_id,
                delivery_id=recovery_id,
                reconcile=args.reconcile_delivery is not None,
            )
        elif args.weekly:
            weekly_kwargs = dict(
                invocation_id=args.invocation_id,
                as_of_date=args.as_of_date,
                deliver=args.deliver,
            )
            if args.resend_authorization is not None:
                weekly_kwargs["resend_authorization_id"] = args.resend_authorization
            receipt = run_weekly_analysis(**weekly_kwargs)
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
    except ValueError as error:
        _parser().error(str(error))
    print(receipt.to_json())
    return exit_code_for(receipt.status)


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
            args, tool=mail_tool or MailTool(create_mail_application())
        )
        print(receipt.json())
        return exit_code_for_status(receipt.status)
    if args.command == "facts":
        from .foundation import FoundationConfig
        from .mail_agent.repository import MailRepository
        from .util import project_root

        root = project_root()
        foundation = FoundationConfig.load(root)
        connection = sqlite3.connect(foundation.database_path)
        try:
            rows = MailRepository(connection).browse_facts(
                args.subject_id, status=args.status, as_of_utc=args.as_of_utc
            )
            print(json.dumps(list(rows), ensure_ascii=False, sort_keys=True))
            return 0
        finally:
            connection.close()
    if args.command in {"supervisor", "orchestrate"}:
        from .orchestration.cli import execute as execute_orchestration
        from .orchestration.production import create_cli_runtime

        application, operations = create_cli_runtime()
        return execute_orchestration(
            args, application=application, operations=operations
        )
    if args.command == "run":
        return _analysis_receipt(args)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
