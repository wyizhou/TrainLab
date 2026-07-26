from __future__ import annotations

import argparse
import json
import sys
import getpass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

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
from .foundation import FoundationConfig
from .garmin import GarminCollectionTool, GarminError, REQUEST_RESOURCE_KINDS, SyncRequest
from .garmin_config import load_garmin_config
from .garmin_client import GarminConnectTransport, TokenStore
from .util import project_root


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


_GARMIN_EXIT = {"succeeded": 0, "partial": 10, "deferred": 11, "lock_busy": 12, "auth_required": 20, "failed": 21}
_GARMIN_MODES = frozenset({"auth", "full", "incremental", "snapshot", "repair", "audit", "status"})
_GARMIN_LOCAL_TZ = ZoneInfo("Asia/Singapore")


def _garmin_failed_receipt(mode: str, code: str):
    from .garmin import SyncReceipt
    safe_mode = mode if mode in _GARMIN_MODES else "status"
    completed_at_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return SyncReceipt(mode=safe_mode, status="failed", requested_range={"from": None, "through": None}, effective_range={"from": None, "through": None}, completed_at_utc=completed_at_utc, errors=[{"code": code, "resource": "cli", "logical_object_key": "garmin:cli", "summary": "request rejected"}])


def _garmin_mode(args: Any) -> str:
    return getattr(args, "garmin_sync_mode", None) if getattr(args, "garmin_mode", None) == "sync" else getattr(args, "garmin_mode", "status")


def _strict_local_date(value: str | None) -> date | None:
    """Accept only a calendar date, never a timestamp or a lenient spelling."""
    if value is None:
        return None
    if len(value) != 10 or value[4] != "-" or value[7] != "-" or not (value[:4] + value[5:7] + value[8:]).isdigit():
        raise ValueError("invalid_local_date")
    return date.fromisoformat(value)


def _validate_garmin_cli_args(args: Any, *, today: date | None = None) -> None:
    """Reject unsafe CLI requests before loading config, credentials, or a provider."""
    mode = _garmin_mode(args)
    if mode not in _GARMIN_MODES:
        raise ValueError("invalid_mode")
    health_from = _strict_local_date(getattr(args, "health_from", None))
    through = _strict_local_date(getattr(args, "through", None))
    snapshot = _strict_local_date(getattr(args, "date", None))
    resources = tuple(getattr(args, "resource", ()) or ())
    activities = tuple(getattr(args, "activity_id", ()) or ())
    strategy = getattr(args, "strategy", None)
    invocation_id = getattr(args, "invocation_id", None)
    if invocation_id == "":
        raise ValueError("invalid_invocation_id")
    if len(resources) != len(set(resources)) or len(activities) != len(set(activities)) or any(not item for item in resources + activities):
        raise ValueError("duplicate_or_empty_scope")
    if any(resource not in REQUEST_RESOURCE_KINDS for resource in resources):
        raise ValueError("invalid_resource_kind")
    if strategy not in {None, "auto", "refetch", "reparse", "reconcile"}:
        raise ValueError("invalid_repair_strategy")
    if mode == "repair" and not (health_from or through or resources or activities):
        raise ValueError("repair_requires_scope")
    # The parser makes most incompatible combinations impossible.  Keep this
    # guard here because garmin_cli_execute is also a supported test adapter.
    if mode in {"auth", "status"} and any((health_from, through, snapshot, resources, activities, strategy)):
        raise ValueError("mode_requires_empty_scope")
    if mode in {"full", "incremental", "audit"} and any((snapshot, activities, strategy)):
        raise ValueError("mode_has_incompatible_parameters")
    if mode == "snapshot" and any((health_from, through, resources, activities, strategy)):
        raise ValueError("mode_has_incompatible_parameters")
    if mode == "repair" and snapshot:
        raise ValueError("mode_has_incompatible_parameters")
    local_today = today or datetime.now(_GARMIN_LOCAL_TZ).date()
    if mode in {"full", "incremental"}:
        effective_through = through or local_today - timedelta(days=1)
        if effective_through >= local_today:
            raise ValueError("completed_mode_through_must_be_before_today")
        if health_from and health_from > effective_through:
            raise ValueError("sync_range_start_after_through")
    if mode in {"repair", "audit"}:
        if through and through > local_today:
            raise ValueError("through_date_in_future")
        if health_from and health_from > (through or local_today):
            raise ValueError("sync_range_start_after_through")
    if mode == "snapshot" and snapshot and snapshot > local_today:
        raise ValueError("snapshot_date_in_future")


def garmin_cli_execute(args: Any, *, transport_factory=GarminConnectTransport, stdin=sys.stdin, stderr=sys.stderr):
    """CLI adapter: exactly one receipt is returned; stdout printing stays in main."""
    mode = _garmin_mode(args)
    try:
        _validate_garmin_cli_args(args)
    except (TypeError, ValueError):
        return _garmin_failed_receipt(mode, "invalid_request")
    try:
        foundation = FoundationConfig.load(project_root())
        config = load_garmin_config(project_root(), foundation)
        request = SyncRequest(mode=mode, health_from_local_date=getattr(args, "health_from", None), through_local_date=getattr(args, "through", None), snapshot_local_date=getattr(args, "date", None), resource_kinds=tuple(getattr(args, "resource", [])), activity_ids=tuple(getattr(args, "activity_id", [])), repair_strategy=getattr(args, "strategy", None), invocation_id=args.invocation_id)
        # status deliberately has no provider construction, token check, or login.
        if mode == "status": return GarminCollectionTool(config).execute(request)
        store = TokenStore(foundation.state_root / "secrets" / "garmin")
        if mode == "auth":
            if not stdin.isatty(): return _garmin_failed_receipt(mode, "auth_requires_tty")
            print("Garmin email:", file=stderr, flush=True); email=stdin.readline().rstrip("\n")
            print("Garmin password:", file=stderr, flush=True); password=getpass.getpass("", stream=stderr)
            def mfa(method: str) -> str:
                delivery = {"email": "email", "phone": "phone"}.get(
                    method,
                    "configured method",
                )
                print(
                    f"Garmin MFA code sent by {delivery}:",
                    file=stderr,
                    flush=True,
                )
                return getpass.getpass("", stream=stderr)
            transport=transport_factory(email,password,store,region=config.region,mfa=mfa)
        else: transport=transport_factory(None,None,store,region=config.region)
        return GarminCollectionTool(config, transport).execute(request)
    except GarminError as exc:
        allowed = {
            "mfa_code_delivery_failed",
            "mfa_code_delivery_rate_limited",
            "mfa_code_delivery_unsupported",
            "mfa_prompt_not_configured",
        }
        return _garmin_failed_receipt(
            mode,
            exc.code if exc.code in allowed else "provider_authentication_failed",
        )
    except ValueError:
        return _garmin_failed_receipt(mode, "invalid_configuration")
    except Exception:
        return _garmin_failed_receipt(mode, "cli_initialization_failed")


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
    run.add_argument("--invocation-id")
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
    garmin = subparsers.add_parser("garmin")
    garmin.add_argument("--invocation-id")
    garmin_sub = garmin.add_subparsers(dest="garmin_mode", required=True)
    garmin_sub.add_parser("auth")
    sync_garmin = garmin_sub.add_parser("sync")
    sync_sub = sync_garmin.add_subparsers(dest="garmin_sync_mode", required=True)
    full = sync_sub.add_parser("full"); full.add_argument("--health-from"); full.add_argument("--through")
    incremental = sync_sub.add_parser("incremental"); incremental.add_argument("--through")
    snapshot = sync_sub.add_parser("snapshot"); snapshot.add_argument("--date")
    repair = garmin_sub.add_parser("repair"); repair.add_argument("--from", dest="health_from"); repair.add_argument("--through"); repair.add_argument("--resource", action="append", default=[]); repair.add_argument("--activity-id", action="append", default=[]); repair.add_argument("--strategy", choices=["auto","refetch","reparse","reconcile"], default="auto")
    audit = garmin_sub.add_parser("audit"); audit.add_argument("--from", dest="health_from"); audit.add_argument("--through")
    garmin_sub.add_parser("status")
    return parser


def main(argv: list[str] | None = None) -> int:
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
    if args.command == "run" and args.analysis_only:
        if args.slot != "morning":
            _parser().error("--analysis-only requires --slot morning")
        if not args.invocation_id:
            _parser().error("--analysis-only requires --invocation-id")
        if args.at is not None:
            _parser().error("--analysis-only does not accept --at")
        try:
            from .analysis.runtime import run_analysis_only
            from .analysis.cli import exit_code_for

            receipt = run_analysis_only(
                invocation_id=args.invocation_id,
                summary_date=args.summary_date,
            )
        except ValueError as error:
            _parser().error(str(error))
        print(receipt.to_json())
        return exit_code_for(receipt.status)
    if args.command == "run" and (args.summary_date is not None or args.invocation_id is not None):
        _parser().error("--summary-date and --invocation-id require --analysis-only")
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
