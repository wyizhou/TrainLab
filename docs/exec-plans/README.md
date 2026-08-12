# Execution plans

Exec plans are the single task-state source. `PLANS.md` records future direction;
an exec plan records the current task's scope, steps, checkpoint, and evidence.

- Non-terminal plans stay in `active/`; completed or cancelled plans move to
  `completed/`.
- Use `<stage>-<initiative>-<sequence>-<slug>.md`; genuine rework appends
  `-r01`, `-r02`, and links the completed predecessor.
- Diagnostics, retries of a command, and Validator findings update the same plan
  and never create attempt-version directories.
- Only the coordinating Agent writes plans, Roadmap, and memory.
- Result-changing work needs a fresh, read-only independent Validator PASS.
- Parallel tasks additionally need non-overlapping scopes, isolated Git work,
  task-level validation, and integration-level validation.

Statuses: `planned`, `ready`, `active`, `blocked`, `validating`, `validated`,
`integrating`, `completed`, `rework`, `cancelled`.
