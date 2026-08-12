#!/usr/bin/env python3
"""Run L2-18 only in a disposable E-04 shadow clone."""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
from trainlab.garmin_smoke_runtime import (
    SMOKE_RUNTIME_ERROR_CODES,
    SmokeRuntimeError,
    SmokeRuntimeRequest,
    run_smoke,
)

def main() -> int:
    started_at = time.monotonic()
    def progress(event: dict[str, object]) -> None:
        print(json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False), file=sys.stderr, flush=True)
    parser = argparse.ArgumentParser(prog="run_garmin_smoke")
    for name in ("isolated-root", "production-token-store", "production-garmin-config"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--from-date", required=True); parser.add_argument("--through-date", required=True)
    parser.add_argument("--invocation-id", action="append", required=True); parser.add_argument("--authorization-id", required=True)
    parser.add_argument("--e04-backup-receipt-sha256", required=True); parser.add_argument("--operator-registered", action="store_true")
    parser.add_argument("--shadow-attested", action="store_true"); parser.add_argument("--canonical-owner-unchanged", action="store_true")
    parser.add_argument("--bounded-activity-window-authorized", action="store_true")
    args = parser.parse_args()
    try:
        result = run_smoke(SmokeRuntimeRequest(args.isolated_root, args.production_token_store, args.from_date, args.through_date, tuple(args.invocation_id), args.production_garmin_config, args.authorization_id, ("auth", "incremental", "snapshot", "repair", "audit", "status"), args.bounded_activity_window_authorized, args.e04_backup_receipt_sha256, args.operator_registered, args.shadow_attested, args.canonical_owner_unchanged), progress=progress)
    except Exception as exc:
        code = (
            str(exc)
            if isinstance(exc, SmokeRuntimeError)
            and str(exc) in SMOKE_RUNTIME_ERROR_CODES
            else "smoke_runtime_failed"
        )
        progress({
            "event": "smoke_failed",
            "code": code,
            "total_elapsed_seconds": round(
                max(0.0, time.monotonic() - started_at),
                3,
            ),
        })
        print(json.dumps({"status": "failed", "code": "smoke_runtime_failed"}, sort_keys=True)); return 2
    print(json.dumps(result, sort_keys=True)); return 0

if __name__ == "__main__": raise SystemExit(main())
