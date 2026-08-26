---
name: training-coach
description: Produce a deterministic-input Chinese daily review or weekly review plus running/climbing/rest course schedule, similar to Course Coach. Use when a user or another AI supplies bounded health/activity evidence; do not use it to sync providers or send messages.
---

# Training Coach

Read `source/AGENTS.md`, `goal.md`, SQLite history and this file. The caller may be a user or scheduled AI;
the input envelope must identify the source and exact evidence references.

## Modes

The caller must select an explicit versioned contract. The unversioned rules below describe legacy v1
behavior only; `Coaching Utility v2` governs v2 calls, and `Content-first v4` governs v4 calls. A v4 call
must not merge legacy or v2 course-assessment, downgrade, cancellation or replacement semantics into its
daily output.

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
- Content-first v4 parses `goal.md` only at the Host boundary against the frozen public title, five sections
  and 19 ordered fields. Intensity accepts an integer 1–5 or `N/5` plus a non-empty annotation; only integer
  `N` enters the model context. The annotation, source Markdown, filenames and paths never enter the prompt.
- Daily context includes `recent_health_metrics_v1`: VO₂ Max is the latest verified observation on or
  before the review date within a 30-calendar-day window; weight uses a 14-calendar-day window. Each value
  carries its actual observation date, age, exact/prior selection kind, raw ID/SHA, unit and
  `provider_calls=0`. Empty, conflicting, malformed, future, stale or unit-invalid raw is skipped. Sleep,
  RHR, HRV, all-day heart rate and activities remain exact-date.

## Coaching Utility v2

- Never calculate or prescribe heart-rate zones, target BPM, maximum heart rate, threshold, or Z1–Z5.
  Observed RHR, HRV, activity average heart rate and activity maximum heart rate remain historical facts.
- Prescribe running intensity primarily with RPE and plain-language feel/talk guidance. Add an optional
  historical reference pace only when a comparable verified activity exists; label it as reference, not target.
- A `hold` or `advance` week contains exactly one conditional SOS run, normally on Wednesday. A `deload`,
  red flag or evidence-backed clearly insufficient recovery may omit it with a reason. `caution` alone is
  not an omission reason.
- Each course includes purpose, type, dose, warm-up, main set, recovery, cool-down, cues, start gate,
  downgrade/replacement and stop conditions. Daily coaching may maintain, downgrade or cancel the planned
  course, but never increase, move or make up SOS work.
- Daily output shows both the original weekly course and today's effective adjustment. Weekly output includes
  health summary, activity/load summary, three to five observation→meaning→action insights and seven detailed days.
- For v2 weekly mode, never fall back to raw: accept exactly seven v2 daily outputs and at most four v2 weekly
  histories, otherwise block or disclose uncertainty. Hard-load dates differ by at least three days (Monday then
  Thursday at the earliest); moving SOS away from Wednesday requires a cited scheduling or recovery reason.
- Optional reference pace may only copy a Host-provided `comparable_pace_reference_v1` that satisfies A-015;
  it is limited to recovery/easy/long running and is never used by SOS.

## Content-first v4

- Daily health, sleep and recovery analysis remains separate from exercise facts. The visible activity section
  lists every completed activity objectively; it does not score execution or advise about the planned course.
- The planned course is attached by the Host from one verified weekly-plan output ID/SHA. Daily AI never emits
  an effective course, adjustment, replacement or make-up session. The athlete chooses whether to execute it.
- A deterministic red-flag alert may block external execution, but it does not mutate the stored plan identity.
- Weekly mode consumes exactly seven `daily_completed_observation_v1` records and at most four weekly histories.
  It analyzes every completed activity before a short plan comparison and never rereads raw.
- The Host parses the private six-heading, nineteen-field goal template into `training_goal_v1`. The model sees
  only that strict business object in Context v2, never goal Markdown, filenames, or relative/absolute paths.
- Every daily observation carries exactly six unique health facts: sleep, RHR, HRV, all-day heart-rate summary,
  VO2 Max and weight. Each fact is strictly `available`, `missing` or `insufficient_data`; missing has no value
  or raw lineage, while insufficient data retains the unusable raw ID/SHA and a fixed reason code.
- Technical findings use Host-computed bounded FIT metrics with method, exclusions, coverage, confidence,
  evidence and limitations. Every metric reference binds its own activity ID, raw ID, raw SHA and metric code;
  one activity cannot borrow another activity's evidence. Provider session heart-rate-zone durations follow
  A-016 and never become a future zone or BPM prescription.
- `training_plan_v3` is one fixed seven-day plan with purpose, dose, steps, RPE, technique notes and safety stop
  conditions. It has no start gate, downgrade course or alternative course.
- VC-010 weekly generation uses `weekly_model_decision_v1`: the model emits exactly `day_1` through `day_7`
  and never emits dates, periods or Host status. Running and climbing courses have required `warmup`, `main`,
  `recovery` and `cooldown` step objects; rest has only `checklist`. The Host injects verified dates/periods into
  `weekly_ai_result_v4` without inventing course content.
- Model-authored text must not repeat numeric BPM values or prescribe zones. Historical RHR and completed-activity
  average/maximum heart rate are rendered deterministically from typed evidence, including date and raw lineage.
- The business decision Schema is the structural source of truth. Its Codex wire projection may remove only
  `$schema`, `$id`, `minLength`, `maxLength`, `minItems`, `maxItems`, `pattern`, `format`, `minimum` and
  `maximum`; every other unsupported keyword blocks projection. Fields, required sets, variants, enums, consts
  and local-ref topology remain identical. A weekly run saves the wire result first and only publishes the Host
  envelope after business and Reader validation.
- The v4 Prompt contains one canonical JSON semantics block derived from the authoritative business and Host
  Schemas. Candidate building and Runner preflight compare its root fields, seven day slots, course variants,
  session types, phases and Host-owned forbidden fields before any model attempt.
- This section overrides the unversioned and v2 daily course rules above for every v4 call. In particular,
  v4 does not assess whether today's planned course should be performed and does not emit downgrade conditions
  for that course. Only the separate deterministic health alert may state a red flag and block automation.

## Scripts

- `scripts/parse_raw.py` creates bounded metadata and aggregate evidence from selected raw files. It never
  emits raw JSON, FIT samples or credentials.
- `scripts/build_context.py` selects and can persist the bounded recent-health snapshot deterministically;
  this operation invokes neither AI nor a Provider.
- `scripts/model_context_v4.py` revalidates the strict goal, evidence, privacy boundary and authoritative
  Context v2 contracts before any weekly model attempt can be created.
- `scripts/validate_course.py` validates the course contract before the result is written to SQLite.
- `scripts/run_codex_daily.py` is the thin M9 owner-only entry. `scripts/codex_attempt_runtime.py`
  holds the single-writer pending-to-terminal state machine, dual-Schema validation and evidence closure.
- `scripts/run_schema_canary.py` validates the versioned wire Schema once with public synthetic data before
  the one approved private attempt. It accepts no Candidate, goal, health, activity or token input.
- `scripts/run_rolling_week.py` is the M10-only coordinator for seven fixed daily reports plus one weekly
  report. It uses `--ignore-user-config`, performs no Provider writes and emits prepared email/GTS contracts.
- These scripts do not call Garmin, Gmail, Workout or Sites. A valid M9 downstream result requires the
  immutable `attempt 2 failed → attempt 3 failed → canary succeeded → attempt 4 succeeded` chain.

On malformed input return a stable domain error and persist the failed/blocked run in SQLite.
