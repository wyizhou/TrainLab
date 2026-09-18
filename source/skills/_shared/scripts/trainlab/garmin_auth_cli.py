from __future__ import annotations

import argparse
import getpass
import json
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

from trainlab.contracts.errors import ErrorCode, ErrorEnvelope
from trainlab.garmin_auth import GarminAuthService
from trainlab.garmin_auth_maintenance import run_maintenance
from trainlab.garmin_auth_types import GarminAuthError


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, "命令参数无效；使用 --help 查看用法。勿把密码或验证码放入命令参数。\n")


def _emit(result: ErrorEnvelope) -> None:
    print(json.dumps(result.to_json(), ensure_ascii=False), flush=True)


def _hidden(prompt: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(prompt)


def _login(service: GarminAuthService, *, is_cn: bool) -> ErrorEnvelope:
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        return GarminAuthError(ErrorCode.CONFIG_UNAVAILABLE, "interactive_terminal_required").envelope()
    username = password = code = ""
    try:
        username = _hidden("Garmin 账号（不回显）：")
        password = _hidden("密码（不回显）：")
        result = service.begin_login(username, password, is_cn=is_cn)
        username = password = ""
        if result.ok and isinstance(result.data, dict) and result.data.get("state") == "needs_mfa":
            code = _hidden("验证码（不回显）：")
            result = service.submit_mfa(result.data["flow_id"], code)
        return result
    finally:
        username = password = code = ""
        service.close()


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description="Garmin 本机认证；密码和验证码仅在本人终端输入。")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("login", "status", "maintain", "sync-once"):
        sub = commands.add_parser(command)
        sub.add_argument("--instance-root", type=Path, default=Path("."))
        if command == "login":
            sub.add_argument("--region", choices=("com", "cn"), required=True)
        if command == "maintain":
            sub.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    service = GarminAuthService(args.instance_root)
    try:
        if args.command == "login":
            result = _login(service, is_cn=args.region == "cn")
        elif args.command == "status":
            result = service.status()
        elif args.command == "maintain":
            result = run_maintenance(service, once=args.once, emit=_emit)
            return 0 if result.ok else 1
        else:
            from trainlab.garmin_sync import run_real_garmin_sync
            synced = run_real_garmin_sync(args.instance_root, now_utc=datetime.now(UTC))
            print(json.dumps(synced.to_json(), ensure_ascii=False))
            return 0 if synced.ok else 1
        _emit(result)
        return 0 if result.ok else 1
    except (EOFError, KeyboardInterrupt):
        _emit(GarminAuthError(ErrorCode.AUTH_REFRESH_REQUIRED, "operation_cancelled").envelope())
        return 130
    except getpass.GetPassWarning:
        _emit(GarminAuthError(ErrorCode.CONFIG_UNAVAILABLE, "interactive_terminal_required").envelope())
        return 1
    except Exception:  # noqa: BLE001
        _emit(GarminAuthError(ErrorCode.EXTERNAL_SERVICE_FAILED, "operation_failed").envelope())
        return 1
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
