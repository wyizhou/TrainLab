"""Manual, one-shot TrainLab command line interface.

The historical supervisor/orchestration command tree is intentionally absent.
Each product layer is invoked explicitly and returns one JSON receipt.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import uuid
from datetime import date, timedelta

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


def _invocation_id(prefix: str) -> str:
    return f"cli-{prefix}-{uuid.uuid4().hex}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trainlab", description="TrainLab manual one-shot tools"
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

    analysis = subparsers.add_parser("analysis")
    analysis_sub = analysis.add_subparsers(dest="analysis_mode", required=True)
    daily = analysis_sub.add_parser("daily")
    daily.add_argument("--report-date", required=True)
    daily.add_argument("--invocation-id")
    daily.add_argument("--deliver", action="store_true")
    weekly = analysis_sub.add_parser("weekly")
    weekly.add_argument("--week-ending", required=True)
    weekly.add_argument("--invocation-id")
    weekly.add_argument("--deliver", action="store_true")
    revise = analysis_sub.add_parser("revise-plan")
    revise.add_argument("--plan-id", required=True)
    revise.add_argument("--reason-event-id", required=True)
    revise.add_argument("--effective-date")
    revise.add_argument("--invocation-id")
    revise.add_argument("--deliver", action="store_true")
    status = analysis_sub.add_parser("status")
    status.add_argument("--run-key")
    regenerate = analysis_sub.add_parser("regenerate")
    regenerate.add_argument("--artifact-id", required=True)
    regenerate.add_argument("--reason", required=True)
    regenerate.add_argument("--invocation-id")
    regenerate.add_argument("--deliver", action="store_true")

    from .mail_agent.cli import add_root_subparser as add_mail_subparser

    add_mail_subparser(subparsers)
    facts = subparsers.add_parser("facts", help="read-only user-fact browser")
    facts.add_argument("--subject-id", type=int, required=True)
    facts.add_argument(
        "--status",
        choices=["all", "active", "pending", "future", "expired", "revoked"],
        default="all",
    )
    facts.add_argument("--as-of-utc")
    return parser


def _analysis_main(args: argparse.Namespace) -> int:
    from .analysis.cli import exit_code_for
    from .analysis.runtime import (
        run_analysis_only,
        run_analysis_status,
        run_plan_revision_analysis,
        run_regeneration_analysis,
        run_weekly_analysis,
    )

    invocation_id = getattr(args, "invocation_id", None)
    if args.analysis_mode == "status":
        receipt = run_analysis_status(run_key=args.run_key)
    elif args.analysis_mode == "daily":
        report_date = date.fromisoformat(args.report_date)
        summary_date = (report_date - timedelta(days=1)).isoformat()
        receipt = run_analysis_only(
            invocation_id=invocation_id or _invocation_id("daily"),
            summary_date=summary_date,
            deliver=args.deliver,
        )
    elif args.analysis_mode == "weekly":
        week_ending = date.fromisoformat(args.week_ending)
        if week_ending.weekday() != 6:
            raise ValueError("analysis_weekly_week_ending_sunday_required")
        # The runtime route is anchored on the Monday that starts the next
        # plan.  The public CLI is intentionally friendlier: users provide
        # the Sunday review boundary.
        plan_start = (week_ending + timedelta(days=1)).isoformat()
        receipt = run_weekly_analysis(
            invocation_id=invocation_id or _invocation_id("weekly"),
            as_of_date=plan_start,
            deliver=args.deliver,
        )
    elif args.analysis_mode == "revise-plan":
        receipt = run_plan_revision_analysis(
            invocation_id=invocation_id or _invocation_id("revise-plan"),
            plan_id=args.plan_id,
            reason_event_id=args.reason_event_id,
            effective_date=args.effective_date,
            deliver=args.deliver,
        )
    elif args.analysis_mode == "regenerate":
        receipt = run_regeneration_analysis(
            invocation_id=invocation_id or _invocation_id("regenerate"),
            artifact_id=args.artifact_id,
            reason_code=args.reason,
            deliver=args.deliver,
        )
    else:  # pragma: no cover - argparse enforces this
        raise AssertionError(args.analysis_mode)
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
    if args.command == "analysis":
        try:
            return _analysis_main(args)
        except (ValueError, OSError) as error:
            _parser().error(str(error))
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
            rows = list(
                MailRepository(connection).browse_facts(
                    args.subject_id, status=args.status, as_of_utc=args.as_of_utc
                )
            )
            print(json.dumps(rows, ensure_ascii=False, sort_keys=True))
            return 0
        finally:
            connection.close()
    raise AssertionError(f"unhandled command: {args.command}")
