# Analysis delivery route

The host supplies an already accepted, exact artifact revision, deterministic
subject, plain text, inline HTML, idempotency key and operator-approved fixed
self address. Do not analyze health data, read a mailbox/thread, access a
database/local file/credential or change the artifact content.

The provider boundary is the current Codex environment's enabled `gmail`
registration using exactly `@artymclabin/gmail-mcp`. Search
`in:sent subject:"<complete deterministic subject>"` before every possible
send. A single exact result counts only when its full subject and From address
match the approved self address; multiple results are ambiguous. With no
result, send one multipart/alternative message with both From and To equal to
that approved address. Apply the TrainLab label to a newly sent or reconciled
message. Reconcile mode searches and labels only and must never send.

Return only the delivery result schema: delivery ID, status, provider message
and thread IDs when available, applied label and a redacted error. Never return
mail body, recipient, arbitrary tool instructions or a claim about another
artifact revision. A send timeout or post-send label failure is unknown and
must be reconciled before any retry.
