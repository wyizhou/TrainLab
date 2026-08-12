# TrainLab Roadmap

This file records approved stages, dependencies, write scopes, and delivery
state. Implementation details and validation evidence belong only in exec plans.

## Governance

- A Roadmap change requires explicit human approval.
- Detailed plans are created only when a task is ready to start.
- Status values are `planned`, `ready`, `active`, `blocked`, `validating`,
  `validated`, `integrating`, `completed`, `rework`, and `cancelled`.
- Completion requires the applicable independent Validator PASS.
- This migration is deliberately serial; it has no parallel batch.

## Approved Roadmap

### [x] `M1` agentForge and product-root migration — `completed`

Approved by the user on 2026-08-12. The repository root becomes the development
Harness, `product/` becomes the only TrainLab product root, and `dist/` contains
only allowlisted, data-free build outputs.

| Task | Status | Dependency | Write scope | Exec plan |
| --- | --- | --- | --- | --- |
| [x] `M1-0001` Install the development Harness | `completed` | none | root governance files; old `.orchestration` cleanup | `docs/exec-plans/completed/M1-agentforge-migration-0001-development-harness.md` |
| [x] `M1-0002` Move the product source into `product/` | `completed` | M1-0001 | tracked product tree, CI, build tool | `docs/exec-plans/completed/M1-product-root-0002-source-migration.md` |
| [x] `M1-0003` Move local runtime data and switch runtime root | `completed` | M1-0002 | local state/config/logs, LaunchAgent path | `docs/exec-plans/completed/M1-runtime-root-0003-data-switch.md` |
