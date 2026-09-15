#!/usr/bin/env python3
"""Write a schema-valid owner-only workflow receipt atomically.

The SQLite output id is an internal database reference and must not be copied
into the public ``workflow_receipt_v1`` payload. Callers should keep that id
in host-side bookkeeping or in SQLite output lineage instead.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.scripts.schema_validation import require_valid_payload  # noqa: E402


def write_receipt(input_path: Path, output_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("workflow_receipt_input_invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("workflow_receipt_input_invalid")
    require_valid_payload(payload, "workflow_receipt_v1")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", dir=output_path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output_path)
        directory_fd = os.open(output_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = write_receipt(args.input_json, args.output)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "error_code": str(exc)}))
        return 2
    print(json.dumps({"status": "written", "workflow_key": payload["workflow_key"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit("legacy_runtime_retired")
