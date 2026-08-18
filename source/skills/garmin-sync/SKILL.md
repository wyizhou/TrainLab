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
- Fetch activity originals only within the active approved scope. M9 permits FIT only for at most two new
  or incomplete activities; GPX/TCX/CSV and `activity_summary` remain forbidden. Fetch weather once only
  after the FIT parser proves that the activity is outdoor.
- A backfill requires an explicit date, resource allowlist and A-001 approval.
- Store only raw bytes under `state/raw/garmin/health` or `state/raw/garmin/activities`; index every file in
  SQLite and never create health/activity fact tables.
- A live MCP call is allowed only when the active exec plan contains the exact date, tool list, budgets,
  pinned MCP revision and one-time authorization. Otherwise this Skill remains preparation-only.

## Script-first workflow

1. Run `scripts/plan_window.py --run-date YYYY-MM-DD` for ordinary offline planning. For the frozen M9
   window, `scripts/live_sync.py` constructs and validates the exact request internally; callers cannot
   change its date, resources or budgets.
2. Run `scripts/index_raw.py --source-root PATH --database PATH` before analysis to index existing raw
   bytes and verify their path, mode and SHA without contacting Garmin.
3. Verify the plan has no 14-day readback, no summary resource, and zero external calls in this stage.
4. Under an independently approved online run, `live_sync.py` starts the pinned MCP through
   `uvx --offline`, exposes only the approved tools, uses only the cached token directory and persists
   every call digest, duration, error, raw hash, `activity_inventory` row and final receipt in Candidate
   SQLite. Never transcribe MCP responses through the AI.
5. Any uncertain identity, path collision, missing date, budget overflow or unknown provider outcome is
   `blocked` and must be reconciled before another attempt.

Outputs are bounded JSON summaries only; never print tokens, raw payloads, routes or health samples.
MCP JSON files use provider `garmin_mcp` and `mcp_capture` filenames; they must never be described as
Garmin HTTP raw. A repeated successful request reuses its receipt without starting MCP.
