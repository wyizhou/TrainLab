# TrainLab project memory

## Maintenance

- Store stable preferences, verified facts, established validation commands,
  and the current active-plan link only.
- Task steps and checkpoints belong in the exec plan.
- Never store credentials, personal health data, raw payloads, mail content, or
  unverified assumptions here.

## User preferences

- Project-facing documentation defaults to Chinese; protocol identifiers,
  paths, commands, and status values retain their technical spelling.
- Development uses the root agentForge Harness. TrainLab runtime behavior is
  governed independently by the product Harness under `product/harness/`.
- `orchestrate-parallel-work` is disabled only for this repository; the global
  installation is not modified.

## Verified project facts

- TrainLab is Python 3.12 with a setuptools `src/` layout.
- The product timezone contract uses `Asia/Hong_Kong`.
- Private `state`, `logs`, `test_data`, FIT, raw data, databases, credentials,
  and private configuration must never enter Git or `dist/`.
- `product/` is the approved sole product source/runtime root after migration.
- `dist/` is generated from an explicit allowlist and is never a source tree.

## Established validation commands

- `product/.venv/bin/python product/scripts/verify_repository_quality.py all`
- `cd product && .venv/bin/python -m pytest`
- The maintained Ruff and mypy target lists are documented in
  `product/README.md` and CI.

## Active plan

No active plan.
