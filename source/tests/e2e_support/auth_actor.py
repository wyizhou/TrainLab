from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, cast

from tests.e2e_support.auth_transport import AuthTransport, ControlledClock
from tests.sync.auth_support import PASSWORD


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("action", choices=("login", "maintain", "sync-once", "lock"))
    parser.add_argument("--offset", type=float, default=0)
    args = parser.parse_args()
    transport = AuthTransport()
    transport.block_network()
    transport.install()
    clock = ControlledClock()
    clock.offset = args.offset
    clock.install()
    if args.action == "lock":
        from trainlab.garmin_auth_store import GarminAuthStore
        with GarminAuthStore(args.root).locked():
            print("locked", flush=True)
            sys.stdin.readline()
        return 0
    import trainlab.garmin_auth_cli as cli
    from trainlab.garmin_auth import GarminAuthService
    cast(Any, cli).GarminAuthService = lambda root: GarminAuthService(root, clock=clock.now, monotonic=clock.monotonic)
    cast(Any, cli).run_maintenance.__kwdefaults__["clock"] = clock.now
    values = iter(("synthetic@example.invalid", PASSWORD))
    cli._hidden = lambda prompt: next(values)
    cast(Any, sys.stdin).isatty = lambda: True
    cast(Any, sys.stderr).isatty = lambda: True
    argv = [args.action, "--instance-root", str(args.root)]
    if args.action == "login":
        argv += ["--region", "com"]
    elif args.action == "maintain":
        argv += ["--once"]
    result: Any = cli.main(argv)
    assert transport.external_attempts == 0
    return int(result)


if __name__ == "__main__":
    raise SystemExit(main())
