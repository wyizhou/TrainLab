---
name: weekly-fitness-summary
description: Summarize a completed running and climbing week from SQLite daily outputs and bounded raw evidence, including recovery, load, pacing and next-week considerations. Use inside weekly coaching when trend evidence is needed.
---

# Weekly Fitness Summary

Read only the seven current daily outputs and up to four previous weekly outputs by default. Use raw-file
parsing only for a missing summary, a conflict or a specifically requested FIT detail. Do not call Garmin,
read Gmail or create a second activity-summary dependency.

For Coaching Utility v2 this fallback is disabled: read exactly seven v2 daily outputs and at most four v2
weekly outputs, and never read raw. Missing or conflicting evidence must remain blocked or explicitly uncertain.

Produce a compact Chinese JSON/text review with completed running, climbing and rest counts, load and recovery
observations, uncertainty disclosures, and source output IDs/SHA-256 for the coaching Skill.

For Coaching Utility v2, the compact review must still contain a decision-useful health summary, an activity
and load summary, and three to five explicit observation→meaning→action insights. It must not derive heart-rate
zones, target BPM, maximum heart rate, threshold or Z1–Z5. Observed heart-rate facts may be cited with lineage.
The next-week plan uses RPE as its primary intensity contract and follows A-015 SOS and hard-load spacing rules.

For A-018 content-first v4, consume exactly seven complete daily observations rather than the compressed v2
load totals. Include every planned and unplanned activity, then keep plan comparison secondary. At most three
eligible running activities receive detailed FIT analysis; all others remain in the complete activity inventory.
Every derived metric carries its frozen method, exclusions, coverage, confidence, evidence and limitations.
Each metric reference must bind the same activity ID, raw ID, raw SHA and metric code as its activity; evidence
from one activity cannot support a finding about another. The seven health days each contain exactly six unique
three-state facts (`available`, `missing`, `insufficient_data`) and the weekly Skill must preserve those states.
Provider session heart-rate-zone durations may be described as historical distribution under A-016, but may not
define future training zones. Climbing intensity remains unknown unless a Provider field or user RPE supports it.
The weekly model receives the user goal only as the Host-parsed `training_goal_v1` business object; it never
receives goal Markdown, a project-relative path, an absolute path, or a filename.
VC-006 also binds the public goal template and weekly prompt template to repository-owned SHA-256 values;
input drift or a frozen privacy-matrix violation must stop before pending intent creation with zero model calls.
The next-week plan is fixed and contains no downgrade or alternative course; daily runs cannot rewrite it. This
v4 section overrides the introductory raw fallback: v4 weekly execution must not open or parse any raw file,
even when an observation is missing, conflicting or lacks a requested FIT detail. It must block or disclose the
bounded uncertainty instead.

Under VC-010 the model decision contains seven named day slots but no dates or periods. Host mapping is the only
source of the final activity/sleep/plan periods and course dates. Model prose does not repeat numeric BPM; the
Reader may display historical RHR and completed-activity average/maximum heart rate only from validated evidence
with date and raw lineage. Course and planning text remains free of BPM and heart-rate-zone prescriptions.
The weekly Prompt's only machine-format description is its canonical Schema-derived semantics block. Builder and
Runner both reject Prompt/business/wire/Host semantic drift before creating an attempt.

Run `scripts/select_history.py --database PATH --week-ending YYYY-MM-DD` to select the bounded history.
The selected evidence is also appended as a `bounded_evidence` output in SQLite; it never changes raw
files, facts, external systems or prior output revisions.
