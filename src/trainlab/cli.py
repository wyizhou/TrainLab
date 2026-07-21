from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any

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
    scheduler = subparsers.add_parser("scheduler")
    scheduler.add_argument("--once", action="store_true")
    watchdog = subparsers.add_parser("watchdog")
    watchdog.add_argument("--once", action="store_true")
    deploy = subparsers.add_parser("deploy")
    deploy.add_argument("--platform", choices=["macos", "linux"])
    deploy.add_argument("--enable", action="store_true")
    subparsers.add_parser("finalize-production")
    subparsers.add_parser("status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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
