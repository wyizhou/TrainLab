#!/usr/bin/env python3
"""Validate a redacted L2-18 smoke-evidence JSON document without running Garmin.

This program intentionally has no ``trainlab garmin`` subprocess, provider
client, database, config, token, socket, or network code.  It reads exactly the
operator-supplied JSON file and prints only status plus controlled error codes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jsonschema import Draft202012Validator

from src.garmin_smoke import validate_smoke_evidence
from src.resources import resource_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify_garmin_smoke")
    parser.add_argument(
        "--evidence",
        required=True,
        type=Path,
        help="redacted evidence JSON; never a receipt, log, FIT, or raw response",
    )
    args = parser.parse_args(argv)
    try:
        loaded = json.loads(args.evidence.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        print(
            json.dumps(
                {"status": "failed", "codes": ["evidence_unreadable"]}, sort_keys=True
            )
        )
        return 2
    try:
        schema = json.loads(
            resource_bytes("harness/schemas/garmin_smoke_evidence.schema.json")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        print(
            json.dumps(
                {"status": "failed", "codes": ["verifier_schema_unreadable"]},
                sort_keys=True,
            )
        )
        return 2
    schema_codes = (
        ["evidence_schema_invalid"]
        if list(Draft202012Validator(schema).iter_errors(loaded))
        else []
    )
    semantic_codes = list(validate_smoke_evidence(loaded))
    codes = sorted(set(schema_codes + semantic_codes))
    print(
        json.dumps(
            {"status": "passed" if not codes else "failed", "codes": codes},
            sort_keys=True,
        )
    )
    return 0 if not codes else 1


if __name__ == "__main__":
    raise SystemExit(main())
