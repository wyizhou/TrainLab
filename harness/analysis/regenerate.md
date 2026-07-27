# Regenerate route

This route regenerates one explicitly selected current analysis artifact for a
controlled reason code.  It uses the supplied bounded context as authoritative:
current canonical facts, accepted user facts, policy, and Harness take priority.
The selected artifact is historical `prior_model_output` lineage only.

The current default evidence window is the supplied 30 completed dates of
aggregated health/sleep/physiology and activity summaries. Regeneration does
not reopen raw payloads, FIT records, segments or sensor samples.

Regenerated running content must use the current fixed Hansons contract and the
current explicit race-goal controls. Do not preserve a superseded method,
silently reuse an old target time or infer one race goal from the other. Every
regenerated running prescription declares its controlled
`hansons_session_role`.

Return only one JSON object matching the analysis result schema.  Its top-level
`mode` is `regenerate`.  Preserve the host-provided target periods and produce
the source shape requested by the deterministic regeneration contract.  Do not
retry delivery, infer a reason, use tools, or expose source records. Apply the
current project-wide training difficulty contract rather than copying an old
route-specific default from the source artifact.
