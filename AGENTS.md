# TrainLab development agent entry

This file is the repository-wide authority for development work. Higher-priority
system and user instructions still take precedence.

## Context startup

For every repository analysis or change:

1. Verify Git availability, repository root, branch, tracked/untracked changes,
   and preserve unrelated work.
2. Read `rules.md`, `memory.md`, and `PLANS.md` completely.
3. Restore the single matching plan under `docs/exec-plans/active/`.
4. Read only task-relevant files under `references/` and `skills/`.
5. For TrainLab product work, always read `product/harness/shared/HARNESS.md`.
   Also read `product/harness/analysis/HARNESS.md` for analysis work and
   `product/harness/mail/HARNESS.md` for mail work.

`product/harness/runtime/HARNESS.md` is historical compatibility evidence, not
a default production Harness. Never load files under `product/archive/` or any
development Harness as production instructions. Run production analysis only
through `product/.venv/bin/trainlab run` with `TRAINLAB_PROJECT_ROOT` set to the
absolute `product/` directory.

## Development governance

- `PLANS.md` is the approved long-term Roadmap. Detailed steps and evidence live
  only in the matching exec plan.
- Every non-trivial repository task creates or restores one exec plan. Ordinary
  diagnostics update that plan; they do not create plan versions.
- The main coordinating Agent is the sole writer of `PLANS.md`, `memory.md`, and
  exec-plan state. Workers and Validators return structured findings.
- Tasks in the same parallel batch require approved, non-overlapping scopes,
  satisfied dependencies, and frozen shared interfaces. Conflicts force serial
  execution.
- Product tests live under `product/tests/`. Existing tests retain their current
  layout; new feature suites use `product/tests/<feature-slug>/`.
- Result-changing work requires a fresh, independent, read-only Validator.
  Parallel work additionally requires task-level and integration-level PASS.
- Ordinary work does not create releases. A release requires an explicitly
  approved version and updates `CHANGELOG.md`.

## Hard boundaries

- Never load or invoke `orchestrate-parallel-work` for this repository.
- Never create `.orchestration`, Graph/Dashboard control state, hash-bound
  handoffs, or attempt-number plan directories.
- The prohibition above does not apply to TrainLab's product package
  `product/src/trainlab/orchestration` or its runtime schemas.
- Do not install, remove, copy, or link project skills into user/global skill
  directories. Project skills remain under `skills/<name>/SKILL.md`.
- Modify only files and external state directly required by the current request.
- Stop and ask when unresolved intent would materially change the result.
- The Gmail MCP server is exactly `gmail`, enabled in the current Codex
  environment, using `@artymclabin/gmail-mcp`. Never silently install,
  authenticate, or fall back to a host-specific transport.
- Never commit credentials, tokens, account data, personal health data, raw
  provider payloads, FIT contents, private configuration, or mail content.

## Agent selection and validation

Use the lowest sufficient abstract capability/reasoning tier: `low`, `medium`,
or `high`. Record the tier and reason in the exec plan, not a vendor model name.
Validators must be at least as capable as their Worker and use at least medium
reasoning. If the platform cannot select a tier, record `platform-default` and
compensate with tighter scope and complete checks.

## Delivery

Report the outcome, important changed paths, lint/test commands and results,
Validator status, skipped checks and reasons, and residual risk. A task still
`blocked` or `validating` must not be described as complete.
