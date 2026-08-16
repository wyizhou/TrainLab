#!/usr/bin/env python3
"""Render an explicit, owner-only HTML/JSON preview from a validated output."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills._shared.state import (  # noqa: E402
    append_output,
    begin_run,
    canonical_json,
    connect,
    finish_run,
    sha256_text,
)


def body_html(value: object) -> str:
    if isinstance(value, dict):
        blocks = []
        for key, item in value.items():
            label = escape(str(key))
            text = (
                escape(json.dumps(item, ensure_ascii=False, indent=2))
                if isinstance(item, (dict, list))
                else escape(str(item))
            )
            blocks.append(
                f'<section class="section"><h2>{label}</h2><div>{text.replace(chr(10), "<br>")}</div></section>'
            )
        return "".join(blocks)
    return f'<section class="section"><div>{escape(str(value))}</div></section>'


_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")


def _field_values(payload: dict[str, object]) -> dict[str, object]:
    """Expose report fields without making the fixed template stateful.

    ``content`` is the normal report payload, while the top-level fields hold
    metadata such as title and period.  Leaf-key lookup keeps the fixed
    template useful for both the compact and open report contracts.
    """

    values: dict[str, object] = dict(payload)
    content = payload.get("content")
    if isinstance(content, dict):
        values.update(content)
    return values


def _fill_placeholders(template: str, payload: dict[str, object]) -> str:
    values = _field_values(payload)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = values.get(key)
        if value is None:
            return "—"
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return escape(str(value))

    return _PLACEHOLDER_RE.sub(replace, template)


def render(
    template: str,
    title: str,
    period: str,
    body: str,
    *,
    fixed: bool,
    payload: dict[str, object],
) -> str:
    if not fixed:
        return (
            template.replace("{{ title }}", escape(title))
            .replace("{{ period }}", escape(period))
            .replace("{{ body_html }}", body)
        )
    rendered = template.replace(
        "<title>TrainLab · 每日训练简报</title>", f"<title>{escape(title)}</title>"
    )
    rendered = rendered.replace(
        "<title>TrainLab · 每周训练总结</title>", f"<title>{escape(title)}</title>"
    )
    rendered = _fill_placeholders(rendered, payload)
    insertion = f'<div data-trainlab-render="fixed">{body}</div>'
    return rendered.replace("</body>", insertion + "</body>")


def persist_outputs(
    database: Path,
    *,
    kind: str,
    mode: str,
    payload: dict[str, object],
    html: str,
) -> dict[str, int]:
    period = str(payload.get("period") or "")
    content_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    input_digest = sha256_text(canonical_json(payload) + "\n" + html)
    logical_base = f"training-report-publisher:{kind}:{mode}"
    lineage = [{"input_sha256": input_digest}]
    connection = connect(database)
    try:
        existing = connection.execute(
            "SELECT id, output_kind FROM skill_outputs "
            "WHERE logical_key IN (?, ?) AND lineage_json LIKE ?",
            (
                f"{logical_base}:report",
                f"{logical_base}:email",
                f'%"input_sha256":"{input_digest}"%',
            ),
        ).fetchall()
        if len(existing) == 2:
            return {str(row[1]): int(row[0]) for row in existing}
        run_id = begin_run(
            connection,
            run_key=f"{logical_base}:{input_digest}",
            workflow_key=f"{kind}:{period}",
            dedupe_key=f"{logical_base}:{input_digest}",
            skill_name="training-report-publisher",
            operation="render_daily" if kind == "daily" else "render_weekly",
            trigger_kind="skill",
            input_manifest={"kind": kind, "mode": mode, "input_sha256": input_digest},
            target_from_date=period.split("/", 1)[0] if "/" in period else None,
            target_through_date=period.split("/", 1)[-1] if "/" in period else None,
        )
        report_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind="report_artifact",
            logical_key=f"{logical_base}:report",
            schema_name=f"{kind}_report_artifact",
            schema_version="1",
            title_text=str(payload.get("title") or ""),
            content_json=payload,
            content_text=content_text,
            content_html=html,
            lineage=lineage,
            period_start_date=period.split("/", 1)[0] if "/" in period else None,
            period_end_date=period.split("/", 1)[-1] if "/" in period else None,
        )
        report_sha = str(
            connection.execute(
                "SELECT content_sha256 FROM skill_outputs WHERE id=?", (report_id,)
            ).fetchone()[0]
        )
        email_id = append_output(
            connection,
            skill_run_id=run_id,
            output_kind="email_render",
            logical_key=f"{logical_base}:email",
            schema_name=f"{kind}_email_render",
            schema_version="1",
            title_text=str(payload.get("title") or ""),
            content_json=payload,
            content_text=content_text,
            content_html=html,
            lineage=[
                {
                    "output_id": report_id,
                    "output_sha256": report_sha,
                    "input_sha256": input_digest,
                }
            ],
            period_start_date=period.split("/", 1)[0] if "/" in period else None,
            period_end_date=period.split("/", 1)[-1] if "/" in period else None,
        )
        finish_run(connection, run_id, status="succeeded")
        return {"report_artifact": report_id, "email_render": email_id}
    except Exception:
        try:
            if "run_id" in locals():
                finish_run(
                    connection, run_id, status="failed", error_code="render_failed"
                )
        finally:
            connection.close()
        raise
    finally:
        if connection is not None:
            connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--kind", choices=("daily", "weekly"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--mode", choices=("open_report", "fixed_email"), default="open_report"
    )
    parser.add_argument("--database", type=Path, default=None)
    args = parser.parse_args()
    payload = json.loads(args.input_json.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("report input must be an object")
    title = str(
        payload.get("title")
        or (
            "TrainLab · 每日训练简报"
            if args.kind == "daily"
            else "TrainLab · 每周训练总结"
        )
    )
    period = str(payload.get("period") or "")
    template_root = Path(__file__).resolve().parents[3] / "templates"
    if args.mode == "fixed_email":
        template_path = template_root / "fixed" / f"{args.kind}_report.html"
    else:
        template_path = template_root / "open-report" / f"{args.kind}_report.html"
    template = template_path.read_text(encoding="utf-8")
    html = render(
        template,
        title,
        period,
        body_html(payload.get("content", payload)),
        fixed=args.mode == "fixed_email",
        payload=payload,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(args.output_dir, 0o700)
    (args.output_dir / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "report.html").write_text(html, encoding="utf-8")
    os.chmod(args.output_dir / "report.json", 0o600)
    os.chmod(args.output_dir / "report.html", 0o600)
    output_ids = None
    if args.database:
        output_ids = persist_outputs(
            args.database,
            kind=args.kind,
            mode=args.mode,
            payload=payload,
            html=html,
        )
    print(
        json.dumps(
            {
                "status": "passed",
                "mode": args.mode,
                "output_dir": str(args.output_dir),
                "provider_calls": 0,
                "output_ids": output_ids,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
