---
name: garmin-sync
description: Run the bounded Garmin raw synchronization workflow. Use for the daily 12:00 Asia/Hong_Kong sync, an explicitly approved date backfill, or raw-file completeness checks; never use it for unbounded history or Garmin writes.
---

# Garmin Sync

Read `source/AGENTS.md`, `config.json`, SQLite state and this file before acting.

## Contract

- Normal date is D-1: RHR, HRV, all-day heart rate, VO2 Max and weigh-ins.
- Fetch only the completed main sleep whose wake date is D.
- Query yesterday's activity inventory once. Do not request `activity_summary` or read back 14 days.
- Fetch FIT/GPX/TCX only for new or incomplete activities; fetch weather once for new outdoor activities.
- A backfill requires an explicit date, resource allowlist and A-001 approval.
- Store only raw bytes under `state/raw/garmin/health` or `state/raw/garmin/activities`; index every file in
  SQLite and never create health/activity fact tables.
- The local adapter may prepare MCP calls, but this Skill does not call Garmin during this migration.

## Script-first workflow

1. Run `scripts/plan_window.py --run-date YYYY-MM-DD` to produce the bounded request plan.
2. Verify the plan has no 14-day readback, no summary resource, and zero external calls in this stage.
3. Under an independently approved online run, the host may execute the exact MCP calls and then persist
   raw hashes, `activity_inventory`, `skill_runs` and errors in SQLite.
4. Any uncertain identity, path collision, missing date, budget overflow or unknown provider outcome is
   `blocked` and must be reconciled before another attempt.

Outputs are bounded JSON summaries only; never print tokens, raw payloads, routes or health samples.
