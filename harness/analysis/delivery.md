# Analysis delivery route

The host supplies an already accepted, exact artifact revision, deterministic
subject, plain text, inline HTML and idempotency key. Do not analyze health
data, read a mailbox/thread, access a database/local file/credential or change
the artifact content. First search the exact idempotency key, then only send to
the authenticated self and apply the TrainLab label.

Return only the delivery result schema: delivery ID, status, provider message
and thread IDs when available, applied label and a redacted error. Never return
mail body, recipient, arbitrary tool instructions or a claim about another
artifact revision.
