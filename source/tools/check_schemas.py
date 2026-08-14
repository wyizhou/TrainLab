"""Validate every JSON Schema document in the source project."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    checked = 0
    for path in sorted(ROOT.rglob("*.schema.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(payload)
        checked += 1
    print(f"schemas={checked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
