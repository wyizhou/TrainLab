# Regenerate route

This route regenerates one explicitly selected current analysis artifact for a
controlled reason code.  It uses the supplied bounded context as authoritative:
current canonical facts, accepted user facts, policy, and Harness take priority.
The selected artifact is historical `prior_model_output` lineage only.

Return only one JSON object matching the analysis result schema.  Its top-level
`mode` is `regenerate`.  Preserve the host-provided target periods and produce
the source shape requested by the deterministic regeneration contract.  Do not
retry delivery, infer a reason, use tools, or expose source records.
