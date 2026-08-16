#!/usr/bin/env python3
"""Validate a self-delivery email envelope without calling Gmail."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.state import record_skill_result  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json", type=Path)
    parser.add_argument("--database", type=Path, default=None)
    args = parser.parse_args()
    value = json.loads(args.input_json.read_text(encoding="utf-8"))
    errors: list[str] = []
    if not isinstance(value, dict):
        errors.append("email_render_invalid")
    else:
        if not isinstance(value.get("subject"), str) or not value["subject"].strip():
            errors.append("email_render_invalid")
        if not isinstance(value.get("text"), str):
            errors.append("email_render_invalid")
        if not isinstance(value.get("html"), str) or "<script" in value["html"].lower():
            errors.append("email_render_invalid")
    marker = hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    payload = {
        "status": "prepared" if not errors else "blocked",
        "errors": sorted(set(errors)),
        "recipient_mode": "authenticated_self",
        "marker": marker,
        "provider_calls": 0,
    }
    if args.database:
        record_skill_result(
            args.database,
            skill_name="gmail-sender",
            operation="send_email",
            output_kind="bounded_evidence",
            logical_key=f"gmail-sender:message:{args.input_json.resolve()}",
            payload=payload,
            status="succeeded" if not errors else "blocked",
            error_code=errors[0] if errors else None,
        )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
