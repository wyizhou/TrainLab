#!/usr/bin/env python3
"""Validate a self-delivery email envelope without calling Gmail."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.state import connect, record_skill_result  # noqa: E402


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
        if args.database:
            report_id = value.get("report_output_id")
            report_sha = value.get("report_output_sha256")
            source_id = value.get("source_output_id")
            source_sha = value.get("source_output_sha256")
            connection = connect(args.database, read_only=True, immutable=True)
            try:
                report = connection.execute(
                    "SELECT content_sha256,title_text,content_text,content_html,lineage_json "
                    "FROM skill_outputs WHERE id=? AND output_kind='email_render'",
                    (report_id,),
                ).fetchone()
                source = (
                    connection.execute(
                        "SELECT content_sha256 FROM skill_outputs WHERE id=? "
                        "AND output_kind IN ('daily_summary','weekly_summary')",
                        (source_id,),
                    ).fetchone()
                    if source_id is not None
                    else None
                )
            finally:
                connection.close()
            if report is None or report[0] != report_sha:
                errors.append("email_source_unbound")
            else:
                if (
                    value.get("subject") != report[1]
                    or value.get("text") != report[2]
                    or value.get("html") != report[3]
                ):
                    errors.append("email_content_mismatch")
                if source is None or source[0] != source_sha:
                    errors.append("email_source_unbound")
                else:
                    try:
                        lineage = json.loads(str(report[4]))
                    except json.JSONDecodeError:
                        lineage = []
                    if not any(
                        isinstance(item, dict)
                        and (
                            (
                                item.get("source_output_id") == source_id
                                and item.get("source_output_sha256") == source_sha
                            )
                            or (
                                item.get("output_id") == source_id
                                and item.get("output_sha256") == source_sha
                            )
                        )
                        for item in lineage
                    ):
                        errors.append("email_source_unbound")
    marker = hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    payload = {
        "status": "prepared" if not errors else "blocked",
        "errors": sorted(set(errors)),
        "recipient_mode": "authenticated_self",
        "marker": marker,
        "subject": value.get("subject") if isinstance(value, dict) else None,
        "text": value.get("text") if isinstance(value, dict) else None,
        "html": value.get("html") if isinstance(value, dict) else None,
        "report_output_id": value.get("report_output_id")
        if isinstance(value, dict)
        else None,
        "report_output_sha256": value.get("report_output_sha256")
        if isinstance(value, dict)
        else None,
        "source_output_id": value.get("source_output_id")
        if isinstance(value, dict)
        else None,
        "source_output_sha256": value.get("source_output_sha256")
        if isinstance(value, dict)
        else None,
        "provider_calls": 0,
    }
    if args.database:
        record_skill_result(
            args.database,
            skill_name="gmail-sender",
            operation="send_email",
            output_kind="bounded_evidence",
            logical_key=f"gmail-sender:message:{marker}",
            payload=payload,
            status="succeeded" if not errors else "blocked",
            error_code=errors[0] if errors else None,
            lineage=(
                [
                    {
                        "output_id": value["report_output_id"],
                        "output_sha256": value["report_output_sha256"],
                    },
                    {
                        "output_id": value["source_output_id"],
                        "output_sha256": value["source_output_sha256"],
                    },
                ]
                if isinstance(value, dict)
                and isinstance(value.get("report_output_id"), int)
                and isinstance(value.get("report_output_sha256"), str)
                and isinstance(value.get("source_output_id"), int)
                and isinstance(value.get("source_output_sha256"), str)
                else []
            ),
        )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit("legacy_runtime_retired")
