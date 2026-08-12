# Execution plan: move the sole TrainLab product source into product/

- Status: `completed`
- Roadmap ID: `M1-0002`
- Owner: coordinating Agent
- Dependency: M1-0001 completed and independently validated
- Started: 2026-08-12
- Updated: 2026-08-12

## Goal and acceptance

Make `product/` the sole Python project and product Harness root. Move tracked
product sources and local test fixtures, update CI/build paths, build from an
explicit allowlist, and pass all applicable product gates before runtime data
or supervisor paths change.

## Scope and exclusions

Tracked product tree, CI, root build tool, and local `test_data`. Do not move
production `state`, private config, logs, switch LaunchAgent, run providers,
analysis, or mail.

## Work

| Step | Status | Evidence |
| --- | --- | --- |
| Move product tree and test fixtures | done | tracked product tree and local `test_data` now under `product/`; production state/config/logs unchanged |
| Update CI/docs/build allowlist | done | CI uses `working-directory: product`; root build tool rejects private/development paths |
| Rebuild product venv | done | Python 3.12 venv, locked requirements, editable import resolves under `product/src` |
| Run product gates and package scans | done | focused 16 passed; full pytest exit 0 with atomic marker; Ruff/mypy/quality passed; wheel/bundle private scan and fresh install passed |
| Independent validation | done | fresh Validator PASS on staged product topology, final full-test marker, privacy scans and untouched runtime roots |

## Current checkpoint

- Current loop: completed
- Last completed: independent Validator PASS
- Next action: archive and activate M1-0003
- Blockers: none
- Changed paths: product tree, CI, root README/ignore/build tool, migration governance
- Pending validation: none

## Independent validation

- Neutral brief: verify product/ is the sole source root and generated artifacts exclude private/development material.
- Validator tier: `high/high`
- Result: `PASS`

## Iteration log

| Date/context | Evidence | Finding | Next action |
| --- | --- | --- | --- |
| 2026-08-12/current | M1-0001 independent PASS | dependencies satisfied | migrate product paths |
| 2026-08-12/current | initial focused packaging/quality gate | discovered flattened `docs/layers`, lockfile suffix misclassification, and two Ruff issues before runtime-data movement | restore hierarchy and repair the same-stage checks |
| 2026-08-12/current | first independent Validator proved all product/build gates except fixture directory metadata | FAIL: nested `test_data/new` was 0755; recommended explicit nested exec-plan rejection | set all fixture directories 0700, extend fail-closed build policy, and revalidate |
