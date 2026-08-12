# Execution plan: move local runtime data and switch product root

- Status: `completed`
- Roadmap ID: `M1-0003`
- Owner: coordinating Agent
- Dependency: M1-0002 completed and independently validated
- Started: 2026-08-12
- Updated: 2026-08-12

## Goal and acceptance

Move the local runtime roots into `product/` without byte, permission, or owner
drift; switch the local supervisor to the product root; verify read-only product
status; retain a reversible pre-switch manifest; and pass independent validation.

## Scope and exclusions

Local `state`, private config, logs, ignored fixture metadata, local LaunchAgent,
and obsolete root venv. No Garmin provider call, analysis, mail, remote Git,
release, or publication.

## Work

| Step | Status | Evidence |
| --- | --- | --- |
| Stop supervisor and prove no writers | done | old failing LaunchAgent booted out; no TrainLab writer process |
| Freeze metadata/hash manifest | done | 0600 `/tmp` evidence for 70,167 state files, 4 private configs, and 7 logs |
| Atomically move runtime roots | done | same-volume moves; every file hash/mode/owner matched; state/log root inodes preserved |
| Switch and verify LaunchAgent/product root | done | status/verify/doctor exits 0; plist points to `product/`; installed with `--no-start` because startup can dispatch unauthorized due business work |
| Independent validation | done | fresh read-only Validator PASS; migration accepted, activation explicitly separate |

## Current checkpoint

- Current loop: completed
- Last completed: independent Validator PASS
- Next action: archive plan and close M1 Roadmap
- Blockers: none
- Changed paths: local runtime roots, LaunchAgent plist, deploy no-start control and migration governance
- Pending validation: none; business supervisor remains intentionally unloaded pending separate authorization to dispatch due work

## Independent validation

- Neutral brief: validate only metadata, process paths, Git/privacy boundaries, and read-only product status; never inspect private contents.
- Validator tier: `high/high`
- Result: `PASS`

## Iteration log

| Date/context | Evidence | Finding | Next action |
| --- | --- | --- | --- |
| 2026-08-12/current | M1-0002 final Validator PASS | runtime switch dependency satisfied | preflight and freeze evidence |
| 2026-08-12/current | all migration manifests compare equal; read-only status/verify/doctor exit 0 | starting Supervisor can claim due Garmin/analysis/mail work, conflicting with this migration's zero-business-effect boundary | install product-root plist with `--no-start`; require separate authorization for activation |
| 2026-08-12/current | independent Validator confirmed data parity, read-only receipts, LaunchAgent target, inactive safety state, Git/privacy and dist boundaries | PASS; activation remains separate | archive and close Roadmap |
