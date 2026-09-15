#!/usr/bin/env python3
"""Create the six-table TrainLab runtime database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from state import init_database, state_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=None)
    args = parser.parse_args()
    database = init_database(args.database or state_path())
    print(database)
    return 0


if __name__ == "__main__":
    raise SystemExit("legacy_runtime_retired")
