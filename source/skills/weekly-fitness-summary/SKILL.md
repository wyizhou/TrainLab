---
name: weekly-fitness-summary
description: Summarize a completed running and climbing week from SQLite daily outputs and bounded raw evidence, including recovery, load, pacing and next-week considerations. Use inside weekly coaching when trend evidence is needed.
---

# Weekly Fitness Summary

Read only the seven current daily outputs and up to four previous weekly outputs by default. Use raw-file
parsing only for a missing summary, a conflict or a specifically requested FIT detail. Do not call Garmin,
read Gmail or create a second activity-summary dependency.

Produce a compact Chinese JSON/text review with completed running, climbing and rest counts, load and recovery
observations, uncertainty disclosures, and source output IDs/SHA-256 for the coaching Skill.

Run `scripts/select_history.py --database PATH --week-ending YYYY-MM-DD` to select the bounded history.
The selected evidence is also appended as a `bounded_evidence` output in SQLite; it never changes raw
files, facts, external systems or prior output revisions.
