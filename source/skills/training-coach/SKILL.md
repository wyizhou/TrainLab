---
name: training-coach
description: Produce a deterministic-input Chinese daily review or weekly review plus running/climbing/rest course schedule, similar to Course Coach. Use when a user or another AI supplies bounded health/activity evidence; do not use it to sync providers or send messages.
---

# Training Coach

Read `source/AGENTS.md`, `goal.md`, SQLite history and this file. The caller may be a user or scheduled AI;
the input envelope must identify the source and exact evidence references.

## Modes

- `daily`: yesterday's completed activity/non-sleep health plus the main sleep ending this morning, then
  assess today's plan without silently rewriting a weekly plan. Reuse up to 14 prior daily outputs.
- `weekly`: seven daily outputs plus up to four prior weekly outputs, then produce a review and the next
  seven-day running/climbing/rest course table. Read raw only when a summary is missing, conflicting or
  a requested detail needs verification.

## Deterministic rules

- Hansons is a scaling reference; Easy and SOS remain distinct.
- One primary item per day; running SOS and hard climbing share a maximum of three hard loads with two
  calendar days between them. Do not compensate missed quality work or increase distance and intensity
  in the same week.
- Red flags and recovery gates override preferences. No race-pace anchor exists when `goal.md` has no race goal.
- The output is JSON plus concise text. It must include lineage, safety decision, course dose, pace/HR/RPE
  guardrails, downgrade and stop conditions. It must not send mail or write Garmin.
- Temporary requests affect the current output only; never modify `goal.md`.

## Scripts

- `scripts/parse_raw.py` creates bounded metadata and aggregate evidence from selected raw files. It never
  emits raw JSON, FIT samples or credentials.
- `scripts/validate_course.py` validates the course contract before the result is written to SQLite.
- `scripts/run_codex_daily.py` is the thin M9 owner-only entry. `scripts/codex_attempt_runtime.py`
  holds the single-writer pending-to-terminal state machine, dual-Schema validation and evidence closure.
- `scripts/run_schema_canary.py` validates the versioned wire Schema once with public synthetic data before
  the one approved private attempt. It accepts no Candidate, goal, health, activity or token input.
- These scripts do not call Garmin, Gmail, Workout or Sites. A valid M9 downstream result requires the
  immutable `attempt 2 failed → attempt 3 failed → canary succeeded → attempt 4 succeeded` chain.

On malformed input return a stable domain error and persist the failed/blocked run in SQLite.
