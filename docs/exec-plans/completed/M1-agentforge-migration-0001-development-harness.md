# Execution plan: install the agentForge development Harness

- Status: `completed`
- Roadmap ID: `M1-0001`
- Owner: coordinating Agent
- Dependency: none
- Started: 2026-08-12
- Updated: 2026-08-12

## Goal and acceptance

Install the root development Harness, preserve A-001 without weakening it,
disable the old skill workflow for TrainLab, and remove the old local control
plane without changing product behavior or global skills.

## Scope and exclusions

Root governance files and exact `.orchestration` cleanup only. No product code,
production data, Garmin, analysis, mail, remote Git, or global skill mutation.

## Work

| Step | Status | Evidence |
| --- | --- | --- |
| Verify Git and mandatory contracts | done | clean main at migration start; shared Harness and A-001 read |
| Stop old Dashboard and unregister old worktree | done | exact 8089 process stopped; clean `/Volumes/DiskOther/Code/TrainLab/.orchestration/worktrees/trainlab-cross-device-integration`, branch `codex/cross-device-integration`, commit `e9da33be70d7b3627be3ad31dae3a7f59ef253ad`; `git merge-base --is-ancestor e9da33be70d7b3627be3ad31dae3a7f59ef253ad main` succeeded before `git worktree remove` |
| Remove old control plane | done | moved to same-volume Trash; project path absent |
| Install adapted agentForge files | done | adapted root scaffold and approved rules present |
| Validate and archive | done | fresh independent Validator PASS after maintenance-rule restoration |

## Current checkpoint

- Current loop: completed
- Last completed: independent Validator PASS
- Next action: archive plan and activate M1-0002
- Blockers: none
- Changed paths: root governance and `docs/exec-plans/`
- Pending validation: none

## Independent validation

- Neutral brief: verify the root development Harness and old-control-plane removal against approved requirements.
- Validator tier: `high/high`
- Result: `PASS`

## Iteration log

| Date/context | Evidence | Finding | Next action |
| --- | --- | --- | --- |
| 2026-08-12/current | Git clean; old Dashboard stopped; exact worktree path/branch/commit recorded above; directory trashed | first Validator INCONCLUSIVE because the initial plan omitted exact worktree identity; all other checks passed | preserve the same plan, add evidence, request a fresh Validator |
| 2026-08-12/current | second Validator independently proved the worktree identity and all structural checks | FAIL: the five maintenance rules above A-001 had been over-compressed | restore all five rules explicitly and request a fresh Validator |
