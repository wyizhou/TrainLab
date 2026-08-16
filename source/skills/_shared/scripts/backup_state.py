#!/usr/bin/env python3
"""Create an owner-only SQLite Online Backup without touching the source DB."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from state import online_backup, state_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--backup-type", default="manual")
    parser.add_argument("--operation-id", default="runtime-backup")
    args = parser.parse_args()
    manifest = online_backup(
        args.database or state_path(),
        args.destination,
        backup_type=args.backup_type,
        operation_id=args.operation_id,
    )
    database = manifest.with_name(manifest.name.removesuffix(".manifest.json") + ".db")
    print(f"{database}\n{manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
