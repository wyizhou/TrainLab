from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from collections.abc import Sequence
from typing import NoReturn

from skills._shared.fit_weekly import (
    lifecycle,
    publication_ledger,
    run_config,
    run_state,
)


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError("command_arguments_invalid")


def parser() -> Parser:
    result = Parser(prog="python -m skills._shared.fit_weekly", allow_abbrev=False)
    result.add_argument("--instance", default=str(run_config.DEFAULT_INSTANCE))
    result.add_argument("--config", default="config.json")
    result.add_argument("--authorization")
    subcommands = result.add_subparsers(
        dest="command", required=True, parser_class=Parser
    )
    for name in (
        "import-history",
        "sync",
        "weekly",
        "daemon",
        "status",
        "reconcile",
        "edit",
    ):
        command = subcommands.add_parser(name, allow_abbrev=False)
        if name == "import-history":
            command.add_argument("--archive", required=True)
        if name == "daemon":
            command.add_argument("--schedule", required=True)
        if name == "sync":
            command.add_argument("--date", action="append")
            command.add_argument("--recovery", type=int, default=0)
        if name in ("weekly", "edit"):
            command.add_argument("--period-end", required=True)
        if name == "weekly":
            command.add_argument(
                "--phase", choices=("all", "draft", "publish"), default="all"
            )
            command.add_argument("--revision-id")
            command.add_argument("--revision-sha")
            command.add_argument(
                "--late", action="store_const", const=True, default=None
            )
        if name == "reconcile":
            command.add_argument("--period-end")
            command.add_argument("--external", action="store_true")
            command.add_argument("--action-key", action="append", default=[])
        if name == "edit":
            for option in ("base-id", "base-sha", "revision-id", "content"):
                command.add_argument("--" + option, required=True)
            command.add_argument("--part", choices=("summary", "plan"), required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        root = run_config.instance_path(args.instance)
        if args.command == "status":
            value = run_state.status(root)
            print(json.dumps(value, ensure_ascii=False, sort_keys=True))
            return (
                3
                if "unreadable"
                in (value["instance"], value["database"], value["lifecycle"])
                or value.get("schedule", {}).get("state") == "unreadable"
                else 0
            )
        if args.command == "import-history":
            from pathlib import Path

            from skills._shared.fit_weekly import legacy_import

            archive = run_config.instance_path(Path(args.archive))
            if archive == root or archive in root.parents or root in archive.parents:
                raise ValueError("legacy_import_destination_invalid")
            with lifecycle.run(root, args.command, initialize=True):
                value = legacy_import.import_registered(archive, root)
            print(
                json.dumps(
                    {k: v for k, v in value.items() if k != "members"},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "daemon":
            from skills._shared.fit_weekly import run_daemon

            if args.authorization:
                raise ValueError("daemon_slot_authorizations_required")
            config = run_config.load(root, args.config)
            schedule = run_daemon.load(
                root, args.schedule, now=publication_ledger.utc_now()
            )
            with lifecycle.run(root, args.command):
                asyncio.run(
                    run_daemon.run(config, schedule, now=publication_ledger.utc_now)
                )
            return 0
        if args.command == "sync":
            from skills._shared.fit_weekly import run_authorization, run_sync

            if not args.authorization:
                raise ValueError("run_authorization_required")
            config = run_config.load(root, args.config)
            grant = run_authorization.load(
                root, args.authorization, now=publication_ledger.utc_now()
            )
            with lifecycle.run(root, args.command):
                batch = asyncio.run(
                    run_sync.collect(
                        config,
                        grant,
                        dates=args.date,
                        recovery=args.recovery,
                        now=publication_ledger.utc_now,
                    )
                )
                try:
                    mail = run_sync.notify(
                        config, grant, batch, now=publication_ledger.utc_now
                    )
                except ValueError:
                    mail = {
                        "status": "blocked",
                        "error_code": "sync_mail_unavailable_or_unauthorized",
                    }
                value = {
                    "batch_key": batch["batch_key"],
                    "status": batch["status"],
                    "dates": batch["dates"],
                    "mail": mail,
                }
            print(json.dumps(value, ensure_ascii=False, sort_keys=True))
            return (
                0
                if batch["status"] == "complete" and mail["status"] == "success"
                else 5
            )
        if args.command == "edit":
            from skills._shared.fit_weekly import model_job, report_revisions

            content = run_config.read_object(
                root,
                run_config.relative_path(root, args.content),
                limit=2 * 1024 * 1024,
            )
            with lifecycle.run(root, args.command):
                revision = report_revisions.edit(
                    root,
                    args.period_end,
                    base_revision_id=args.base_id,
                    base_revision_sha256=args.base_sha,
                    revision_id=args.revision_id,
                    target=args.part,
                    content=content,
                )
            print(
                json.dumps(
                    {
                        "status": "draft",
                        "revision_id": revision["revision_id"],
                        "revision_sha256": model_job.sha(revision),
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command in ("weekly", "reconcile"):
            from skills._shared.fit_weekly import (
                run_authorization,
                run_reconcile,
                run_weekly,
            )

            grant = (
                run_authorization.load(
                    root, args.authorization, now=publication_ledger.utc_now()
                )
                if args.authorization
                else None
            )
            if args.command == "reconcile" and not args.external:
                if args.action_key or args.authorization:
                    raise ValueError("reconcile_local_options_invalid")
                with lifecycle.run(root, args.command):
                    value = run_reconcile.local(root, args.period_end)
            else:
                config = run_config.load(root, args.config)
                with lifecycle.run(root, args.command):
                    if args.command == "weekly":
                        value = asyncio.run(
                            run_weekly.run(
                                config,
                                args.period_end,
                                grant,
                                phase=args.phase,
                                revision_id=args.revision_id,
                                revision_sha=args.revision_sha,
                                late=args.late,
                                now=publication_ledger.utc_now,
                            )
                        )
                    else:
                        if grant is None or args.period_end is not None:
                            raise ValueError("reconcile_external_options_invalid")
                        value = asyncio.run(
                            run_reconcile.external(
                                config,
                                grant,
                                args.action_key,
                                now=publication_ledger.utc_now,
                            )
                        )
            if args.command == "weekly" and value.get("stages"):
                value["stages"] = {
                    part: {
                        "status": value["stages"][part]["status"],
                        "invocation_adapter_calls": value["stages"][part][
                            "invocation_adapter_calls"
                        ],
                    }
                    if value["stages"][part]
                    else None
                    for part in ("plan", "summary")
                }
            elif value.get("mode") == "local":
                value["weeks"] = {
                    end: {
                        part: {"status": result["status"]}
                        for part, result in stages.items()
                    }
                    for end, stages in value["weeks"].items()
                }
            print(json.dumps(value, ensure_ascii=False, sort_keys=True))
            return 0 if value["status"] in ("complete", "draft") else 5
        raise NotImplementedError("command_not_implemented")
    except NotImplementedError:
        print("command_not_implemented", file=sys.stderr)
        return 4
    except (ValueError, OSError, TypeError, KeyError, sqlite3.Error):
        print("command_arguments_or_instance_invalid", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
