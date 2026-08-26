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

## M11 readable email v2

`scripts/email_view.py` converts validated daily/weekly outputs into explicit `daily_email_view_v1` or
`weekly_email_view_v1`; it never evaluates arbitrary design templates and never exposes unclassified input
keys. AI-authored summaries, evidence claims and stop-condition prose remain in the private fact result; the
reader-facing summary, source labels and safety copy are derived only from validated status, metrics,
activities and course fields. `scripts/render_email_v2.py` then creates owner-only HTML, plain text and
deterministic 1248px PNG assets. Charts are allowed only when the input contains the corresponding real point
array. Missing HR zones, sleep stages or load series remain hidden rather than being inferred.

Daily VO₂ Max and weight cards must read a validated `recent_health_metrics_v1` and show
`更新于 YYYY-MM-DD`. A historical correction may bind a new deterministic snapshot to an unchanged
`daily_ai_result_v1`; the AI output SHA remains unchanged and the snapshot output is included in render
lineage. Other health cards do not receive historical fallback.

The HTML subject must equal its single `<title>` and single `<h1>`, remain at most 80 KiB, and include mobile, dark-mode and
table-based compatibility fallbacks. Inline images use the verified CID manifest; remote URLs, data URIs,
GPS fields, addresses, credentials and private paths are forbidden. This v2 path is preview-only until a
separate live Gmail canary is explicitly authorized.

## Coaching Utility v2 content

The v2 reader view preserves the original weekly course and today's adjustment as separate sections. Daily
mail includes yesterday interpretation, health/recovery interpretation and the full executable course. Weekly
mail includes health summary, activity/load summary, three to five observation→meaning→action insights and
all seven detailed courses. Course steps, gates, downgrade and stop conditions must not be replaced with generic
copy. Heart-rate zones and target BPM are forbidden; observed heart-rate facts are allowed as historical data.
Coaching Utility v2 uses new `daily_email_view_v2` and `weekly_email_view_v2` routes; it does not modify or
reinterpret the v1 ViewModel routes or any historical v1 artifact.

## Content-first v4 preview

The v4 preview consumes one explicit Reader Content Model and emits matching Markdown and unstyled low-fidelity
HTML. Daily order is completed-activity facts, health/sleep/recovery analysis, the exact weekly-plan course, then
limitations and safety alerts. Weekly order is conclusion, health/recovery, complete activity inventory, bounded
technical findings, short plan comparison, combined load and one fixed seven-day plan. Markdown and HTML must
have identical section IDs, text, values and conditional visibility. One business topic may have at most one
visible container; nested cards, high-fidelity branding, CID/MIME and Gmail delivery are out of scope.

VC-010 adds `weekly_reader_content_v2`, which consumes only a validated `weekly_ai_result_v4` plus its exact weekly
evidence. It maps `day_1..day_7` through Host-provided dates and renders historical RHR and completed-activity
average/maximum heart rate deterministically from typed evidence with date and raw lineage. It never accepts model
BPM prose, an arbitrary result path or an unverified Host envelope.
