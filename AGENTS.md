# TrainLab production agent entry

Always load `harness/shared/HARNESS.md` and `AGREEMENTS.md`. For analysis work, also load
`harness/analysis/HARNESS.md`; for mail work, also load
`harness/mail/HARNESS.md`. `harness/runtime/HARNESS.md` is historical
compatibility evidence, not a default production Harness.
Never load files under `archive/` or any development Harness.
Run production analysis only through `trainlab run`.

## Hard requirements

1. All subagents must default to model `gpt-5.6-terra` with reasoning effort
   `medium`, unless the user explicitly requests a different model or effort.
2. Each task must modify only files and behavior directly required by the
   current user request. Do not change unrelated code, documents, configuration,
   data, or external state.
3. If the objective, scope, or user intent is unclear in a way that could affect
   the result, stop and ask the user for clarification. Do not guess the user's
   intent or make an unsupported unilateral decision.
4. Prefer using the `$orchestrate-parallel-work` skill whenever a task can
   reasonably benefit from decomposition, dependency management, isolated work
   units, or independent validation. Do not force parallelism for a trivial
   single-unit task. Every subagent created through this workflow must still
   comply with requirement 1 and use `gpt-5.6-terra` with reasoning effort
   `medium` by default.
5. The Gmail MCP server name is always `gmail`. New production code must use
   the `gmail` MCP registered in the current Codex execution environment and
   must never bind Gmail to a host-specific executable, working directory,
   credential path, or copied token. The supported server package is
   `@artymclabin/gmail-mcp`. If the current environment does not provide that
   exact enabled binding, stop before any mailbox action and tell the user to
   authenticate and register it; never install, authenticate, or fall back to
   another Gmail transport silently.
6. `AGREEMENTS.md` contains durable user-agent operating agreements and known
   failure-prevention rules. Treat every active entry as mandatory. Add a new
   entry only after the user and agent explicitly agree on it; never silently
   weaken, delete, or reinterpret an existing entry.
