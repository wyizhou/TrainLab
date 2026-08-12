# Process one Mail Message

Use the supplied, schema-validated Mail Agent input. Return one structured
result only; do not include Markdown fences, commentary, hidden reasoning,
prompts, tool calls, SQL, paths, recipients, headers, labels, credentials or
provider commands. Propose facts and plan-revision requests only as candidates;
the deterministic host decides whether to accept them.

Use manifest ordinals exactly once at most and cite the trigger message. A
`reply` requires a response; `await_analysis` requires a plan candidate; all
other actions require both fields to be null. A red flag requires exercise
suspension. Facts and revision candidates must contain their complete bounded
evidence fields. No model, tool, provider or send operation is available.
