"""Third-layer-only CLI adapter; intentionally not registered in src.cli."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import Callable, Sequence, TextIO

from .contracts import AnalysisRequest
from .service import AnalysisTool

EXIT_CODES = {
    "succeeded": 0,
    "unchanged": 0,
    "partial": 10,
    "deferred": 11,
    "lock_busy": 12,
    "rejected": 20,
    "failed": 21,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trainlab analyze")
    parser.add_argument("--subject-id", default="active_subject")
    sub = parser.add_subparsers(dest="mode", required=True)

    def command(name: str):
        item = sub.add_parser(name)
        item.add_argument("--invocation-id")
        return item

    daily = command("daily")
    daily.add_argument("--summary-date", dest="summary_local_date")
    daily.add_argument("--advice-date", dest="advice_local_date")
    weekly = command("weekly")
    weekly.add_argument("--as-of", dest="as_of_local_date")
    revise = command("revise-plan")
    revise.add_argument("--plan-id", required=True)
    revise.add_argument("--reason-event-id", required=True)
    revise.add_argument("--effective-date", dest="effective_local_date")
    regenerate = command("regenerate")
    regenerate.add_argument("--artifact-id", required=True)
    regenerate.add_argument("--reason", dest="regeneration_reason_code", required=True)
    retry = command("retry-delivery")
    retry.add_argument("--delivery-id", required=True)
    reconcile = command("reconcile-delivery")
    reconcile.add_argument("--delivery-id", required=True)
    status = sub.add_parser("status")
    status.add_argument("--run-key")
    return parser


def parse_request(
    argv: Sequence[str],
    *,
    subject_id: str | None = None,
    invocation_id_provider: Callable[[], str] | None = None,
    requested_at_utc: str | None = None,
) -> AnalysisRequest:
    args = vars(build_parser().parse_args(list(argv)))
    parsed_subject = args.pop("subject_id")
    mode = args.pop("mode").replace("-", "_")
    run_key = args.pop("run_key", None)
    invocation_id = args.pop("invocation_id", None)
    if mode != "status" and invocation_id is None:
        if invocation_id_provider is None:
            raise ValueError("analysis_invocation_id_required")
        invocation_id = invocation_id_provider()
    return AnalysisRequest.from_dict(
        {
            "schema_version": "1",
            "mode": mode,
            "subject_id": subject_id or parsed_subject,
            "invocation_id": invocation_id,
            "run_key": run_key,
            "requested_at_utc": requested_at_utc or _utc_now(),
            "summary_local_date": args.pop("summary_local_date", None),
            "advice_local_date": args.pop("advice_local_date", None),
            "as_of_local_date": args.pop("as_of_local_date", None),
            "plan_id": args.pop("plan_id", None),
            "reason_event_id": args.pop("reason_event_id", None),
            "effective_local_date": args.pop("effective_local_date", None),
            "artifact_id": args.pop("artifact_id", None),
            "delivery_id": args.pop("delivery_id", None),
            "regeneration_reason_code": args.pop("regeneration_reason_code", None),
        }
    )


def exit_code_for(status: str) -> int:
    return EXIT_CODES[status]


def main(
    argv: Sequence[str] | None = None,
    *,
    tool: AnalysisTool | None = None,
    subject_id: str = "active_subject",
    invocation_id_provider: Callable[[], str] | None = None,
    stdout: TextIO | None = None,
) -> int:
    request = parse_request(
        sys.argv[1:] if argv is None else argv,
        subject_id=subject_id,
        invocation_id_provider=invocation_id_provider,
    )
    receipt = (tool or AnalysisTool()).execute(request)
    (stdout or sys.stdout).write(receipt.to_json() + "\n")
    return exit_code_for(receipt.status)
