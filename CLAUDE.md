# TrainLab production agent entry

Follow the repository-wide rules in `AGENTS.md`.

Always load `harness/shared/HARNESS.md`; load the analysis or mail Harness only
for that route. `harness/runtime/HARNESS.md` is historical evidence, not a
production Harness. Never load files under `archive/` or any development
Harness. Run production analysis only through `trainlab run`.
