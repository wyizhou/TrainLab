---
name: garmin-training-sender
description: Prepare and, only under an approved external-action run, manage TrainLab-owned Garmin Connect My Workouts templates and calendar entries. Use for a validated weekly course table, never for completed activities or unrelated workouts.
---

# Garmin Training Sender

The target is Garmin Connect **My Workouts**, not completed activity history. Read the exact course output,
SQLite approvals and this file before any action.

## Ownership and order

- A template is owned only when its exact name ends in `-GTS` and the SQLite ownership/adoption record is
  present. Existing names alone are not enough for first-time adoption.
- Un-schedule future owned GTS entries, delete only owned unexecuted GTS templates, create new templates,
  read back and validate structure, then schedule them on the calendar.
- Never delete completed activities, non-GTS workouts or a name containing `GTS` in the middle.
- Every action uses `prepared → external_barrier → call → verify/reconcile`, an idempotency key and a
  persisted `external_actions` row. Crash or uncertain outcome is `unknown`, never an automatic retry.

Run `scripts/prepare_gts.py` first. It validates `-GTS` names and emits a no-network action plan. This
migration does not call Garmin and does not grant approval automatically.
