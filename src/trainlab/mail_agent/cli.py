"""Fourth-layer CLI adapter.

It is intentionally not wired into the legacy global CLI during M4-01.  The
adapter is testable independently and delegates every request to ``MailTool``.
"""

from __future__ import annotations

import argparse
import sys
from typing import TextIO

from .contracts import MailReceipt, MailRequest, MailTool, exit_code_for_status, utc_now


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trainlab mail", description="TrainLab fourth-layer mail tool")
    parser.add_argument("--subject-id", type=int, required=True)
    parser.add_argument("--invocation-id", required=True)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--max-items", type=int)
    run.add_argument("--deadline-seconds", type=int)
    poll = subparsers.add_parser("poll")
    poll.add_argument("--max-threads", type=int)
    process = subparsers.add_parser("process")
    process.add_argument("--message-id", required=True)
    process.add_argument("--dependency-artifact-id", action="append", default=[])
    process.add_argument("--regenerate-reason")
    deliver = subparsers.add_parser("deliver-response")
    deliver.add_argument("--response-id", required=True)
    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("--delivery-id")
    status = subparsers.add_parser("status")
    status.add_argument("--run-key")
    status.add_argument("--message-id")
    return parser


def request_from_args(args: argparse.Namespace, *, requested_at_utc: str | None = None) -> MailRequest:
    common = {
        "subject_id": args.subject_id,
        "invocation_id": args.invocation_id,
        "requested_at_utc": requested_at_utc or utc_now(),
    }
    if args.mode == "run":
        return MailRequest(mode="run", max_items=args.max_items, deadline_seconds=args.deadline_seconds, **common)
    if args.mode == "poll":
        return MailRequest(mode="poll", max_threads=args.max_threads, **common)
    if args.mode == "process":
        return MailRequest(mode="process", mail_message_ids=(args.message_id,), dependency_analysis_artifact_ids=tuple(args.dependency_artifact_id), regeneration_reason_code=args.regenerate_reason, **common)
    if args.mode == "deliver-response":
        return MailRequest(mode="deliver_response", mail_response_artifact_ids=(args.response_id,), **common)
    if args.mode == "reconcile":
        identifiers = (args.delivery_id,) if args.delivery_id else ()
        return MailRequest(mode="reconcile", mail_delivery_ids=identifiers, **common)
    if args.mode == "status":
        message_ids = (args.message_id,) if args.message_id else ()
        return MailRequest(mode="status", mail_message_ids=message_ids, run_key=args.run_key, **common)
    raise ValueError("invalid_mail_mode")


def mail_cli_execute(args: argparse.Namespace, *, tool: MailTool | None = None, requested_at_utc: str | None = None) -> MailReceipt:
    return (tool or MailTool()).execute(request_from_args(args, requested_at_utc=requested_at_utc))


def main(argv: list[str] | None = None, *, tool: MailTool | None = None, stdout: TextIO | None = None) -> int:
    args = _parser().parse_args(argv)
    receipt = mail_cli_execute(args, tool=tool)
    print(receipt.json(), file=stdout or sys.stdout)
    return exit_code_for_status(receipt.status)
