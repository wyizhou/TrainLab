---
name: training-report-publisher
description: Render validated daily reviews, weekly reviews and course tables into safe email HTML and JSON outputs. Use after training-coach; open_report is the default and fixed_email is the compatibility fallback.
---

# Training Report Publisher

This Skill is presentation-only. It cannot change facts, course contracts, lineage, approvals or safety
decisions. It writes canonical output rows to SQLite before any Gmail action.

## Modes

- `open_report`: use the Data Analytics build-report result when available, then wrap it in the local
  self-contained email shell under `templates/open-report/`. Sites publishing is disabled in this stage.
- `fixed_email`: use `templates/fixed/daily_report.html` or `weekly_report.html` as a stable fallback.

Only one mode is selected per output. Keep JSON, plain text and HTML hashes bound to the same source output;
HTML must be static, safe for common mail clients and free of scripts or remote dependencies.

Run `scripts/render_report.py --input-json PATH --kind daily|weekly --output-dir PATH [--database PATH]`
for an explicit, owner-only preview. With `--database`, it appends `report_artifact` first and then
`email_render`; it does not change delivery state or contact Gmail.
