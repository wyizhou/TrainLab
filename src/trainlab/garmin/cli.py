"""Garmin-specific CLI parsing and execution."""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..foundation import FoundationConfig
from ..garmin_client import GarminConnectTransport, TokenStore
from ..garmin_config import load_garmin_config
from ..util import project_root
from . import (
    REQUEST_RESOURCE_KINDS,
    GarminCollectionTool,
    GarminError,
    ProductionBudgetGuard,
    ProductionBudgetSpec,
    SyncReceipt,
    SyncRequest,
)

_GARMIN_EXIT = {
    "succeeded": 0,
    "partial": 10,
    "deferred": 11,
    "lock_busy": 12,
    "auth_required": 20,
    "failed": 21,
}
_GARMIN_MODES = frozenset(
    {"auth", "full", "incremental", "snapshot", "repair", "audit", "status"}
)
_GARMIN_LOCAL_TZ = ZoneInfo("Asia/Hong_Kong")


def _garmin_failed_receipt(mode: str, code: str):
    safe_mode = mode if mode in _GARMIN_MODES else "status"
    completed_at_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return SyncReceipt(
        mode=safe_mode,
        status="failed",
        requested_range={"from": None, "through": None},
        effective_range={"from": None, "through": None},
        completed_at_utc=completed_at_utc,
        errors=[
            {
                "code": code,
                "resource": "cli",
                "logical_object_key": "garmin:cli",
                "summary": "request rejected",
            }
        ],
    )


def _garmin_mode(args: Any) -> str:
    return (
        getattr(args, "garmin_sync_mode", None)
        if getattr(args, "garmin_mode", None) == "sync"
        else getattr(args, "garmin_mode", "status")
    )


def _strict_local_date(value: str | None) -> date | None:
    """Accept only a calendar date, never a timestamp or a lenient spelling."""
    if value is None:
        return None
    if (
        len(value) != 10
        or value[4] != "-"
        or value[7] != "-"
        or not (value[:4] + value[5:7] + value[8:]).isdigit()
    ):
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
    bounded = bool(getattr(args, "bounded_production", False))
    budget_values = tuple(
        getattr(args, name, None)
        for name in (
            "max_provider_entries",
            "max_wall_seconds",
            "max_activities",
            "max_fit_downloads",
            "max_new_raw_objects",
        )
    )
    cached_tokens_only = bool(getattr(args, "cached_tokens_only", False))
    if invocation_id == "":
        raise ValueError("invalid_invocation_id")
    if (
        len(resources) != len(set(resources))
        or len(activities) != len(set(activities))
        or any(not item for item in resources + activities)
    ):
        raise ValueError("duplicate_or_empty_scope")
    if any(resource not in REQUEST_RESOURCE_KINDS for resource in resources):
        raise ValueError("invalid_resource_kind")
    if strategy not in {None, "auto", "refetch", "reparse", "reconcile"}:
        raise ValueError("invalid_repair_strategy")
    if bounded:
        if (
            mode not in {"full", "repair"}
            or health_from is None
            or through is None
            or not resources
            or not cached_tokens_only
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
                for value in budget_values
            )
        ):
            raise ValueError("invalid_production_budget")
    elif any(value is not None for value in budget_values) or cached_tokens_only:
        raise ValueError("production_budget_flag_requires_bounded_mode")
    if mode == "repair" and not (health_from or through or resources or activities):
        raise ValueError("repair_requires_scope")
    # The parser makes most incompatible combinations impossible.  Keep this
    # guard here because garmin_cli_execute is also a supported test adapter.
    if mode in {"auth", "status"} and any(
        (health_from, through, snapshot, resources, activities, strategy)
    ):
        raise ValueError("mode_requires_empty_scope")
    if mode in {"full", "incremental", "audit"} and any(
        (snapshot, activities, strategy)
    ):
        raise ValueError("mode_has_incompatible_parameters")
    if mode == "snapshot" and any(
        (health_from, through, resources, activities, strategy)
    ):
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


def garmin_cli_execute(
    args: Any,
    *,
    transport_factory=GarminConnectTransport,
    stdin=sys.stdin,
    stderr=sys.stderr,
):
    """CLI adapter: exactly one receipt is returned; stdout printing stays in main."""
    mode = _garmin_mode(args)
    try:
        _validate_garmin_cli_args(args)
    except (TypeError, ValueError):
        return _garmin_failed_receipt(mode, "invalid_request")
    try:
        foundation = FoundationConfig.load(project_root())
        config = load_garmin_config(project_root(), foundation)
        budget_spec = (
            ProductionBudgetSpec(
                max_provider_entries=args.max_provider_entries,
                max_wall_seconds=args.max_wall_seconds,
                max_activities=args.max_activities,
                max_fit_downloads=args.max_fit_downloads,
                max_new_raw_objects=args.max_new_raw_objects,
                cached_tokens_only=True,
            )
            if getattr(args, "bounded_production", False)
            else None
        )
        budget_guard = ProductionBudgetGuard(budget_spec) if budget_spec else None
        request = SyncRequest(
            mode=mode,
            health_from_local_date=getattr(args, "health_from", None),
            through_local_date=getattr(args, "through", None),
            snapshot_local_date=getattr(args, "date", None),
            resource_kinds=tuple(getattr(args, "resource", [])),
            activity_ids=tuple(getattr(args, "activity_id", [])),
            repair_strategy=getattr(args, "strategy", None),
            invocation_id=args.invocation_id,
            production_budget=budget_spec,
        )
        # status deliberately has no provider construction, token check, or login.
        if mode == "status":
            return GarminCollectionTool(config).execute(request)
        store = TokenStore(foundation.state_root / "secrets" / "garmin")
        if mode == "auth":
            if not stdin.isatty():
                return _garmin_failed_receipt(mode, "auth_requires_tty")
            print("Garmin email:", file=stderr, flush=True)
            email = stdin.readline().rstrip("\n")
            print("Garmin password:", file=stderr, flush=True)
            password = getpass.getpass("", stream=stderr)

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

            transport = transport_factory(
                email, password, store, region=config.region, mfa=mfa
            )
        else:
            transport_kwargs = {"region": config.region}
            if budget_guard is not None:
                transport_kwargs["budget_guard"] = budget_guard
            transport = transport_factory(None, None, store, **transport_kwargs)
        tool_kwargs = {"budget_guard": budget_guard} if budget_guard is not None else {}
        return GarminCollectionTool(config, transport, **tool_kwargs).execute(request)
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


def add_root_subparser(subparsers: argparse._SubParsersAction[Any]) -> None:
    """Register the complete stable ``trainlab garmin`` command tree."""
    garmin = subparsers.add_parser("garmin")
    garmin.add_argument("--invocation-id")
    garmin_sub = garmin.add_subparsers(dest="garmin_mode", required=True)
    garmin_sub.add_parser("auth")
    sync_garmin = garmin_sub.add_parser("sync")
    sync_sub = sync_garmin.add_subparsers(dest="garmin_sync_mode", required=True)
    full = sync_sub.add_parser("full")
    full.add_argument("--health-from")
    full.add_argument("--through")
    full.add_argument("--resource", action="append", default=[])
    full.add_argument("--bounded-production", action="store_true")
    full.add_argument("--cached-tokens-only", action="store_true")
    full.add_argument("--max-provider-entries", type=int)
    full.add_argument("--max-wall-seconds", type=int)
    full.add_argument("--max-activities", type=int)
    full.add_argument("--max-fit-downloads", type=int)
    full.add_argument("--max-new-raw-objects", type=int)
    incremental = sync_sub.add_parser("incremental")
    incremental.add_argument("--through")
    snapshot = sync_sub.add_parser("snapshot")
    snapshot.add_argument("--date")
    repair = garmin_sub.add_parser("repair")
    repair.add_argument("--from", dest="health_from")
    repair.add_argument("--through")
    repair.add_argument("--resource", action="append", default=[])
    repair.add_argument("--activity-id", action="append", default=[])
    repair.add_argument(
        "--strategy",
        choices=["auto", "refetch", "reparse", "reconcile"],
        default="auto",
    )
    repair.add_argument("--bounded-production", action="store_true")
    repair.add_argument("--cached-tokens-only", action="store_true")
    repair.add_argument("--max-provider-entries", type=int)
    repair.add_argument("--max-wall-seconds", type=int)
    repair.add_argument("--max-activities", type=int)
    repair.add_argument("--max-fit-downloads", type=int)
    repair.add_argument("--max-new-raw-objects", type=int)
    audit = garmin_sub.add_parser("audit")
    audit.add_argument("--from", dest="health_from")
    audit.add_argument("--through")
    garmin_sub.add_parser("status")


def execute(args: Any) -> int:
    receipt = garmin_cli_execute(args)
    print(receipt.json())
    return _GARMIN_EXIT[receipt.status]
