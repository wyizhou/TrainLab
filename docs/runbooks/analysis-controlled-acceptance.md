# Analysis controlled acceptance and delivery gate

This is a checklist and evidence template only. It does not execute real
analysis, a provider call, a model call, email delivery, database access, or a
production command. It is not authorization to perform any of those actions.

## Required authorization and scope

Before a real-environment smoke test, obtain separate written real-environment authorization
that identifies the controlled self-only account, approved
operator, small local-date range, maintenance window, rollback owner, and
evidence custodian. Confirm A3-22 through A3-24 and EXT-01 through EXT-05 are
complete. Absence of any item is a no-go.

## Authorized smoke checklist

The approved operator, not this document, must record the following results:

- [ ] A successful second-layer short-window collection receipt precedes daily.
- [ ] Daily proves accepted-before-send and records only redacted revision and
  delivery identifiers.
- [ ] Repeating the same invocation returns unchanged without a duplicate
  delivery.
- [ ] A Sunday-like weekly input verifies past review dates and future plan
  dates.
- [ ] A delivery retry proves already_sent when the exact existing delivery is
  found; uncertain delivery is reconciled before any retry.
- [ ] A failed delivery preserves the accepted artifact and plan; no automatic
  resend or regeneration is allowed.
- [ ] The process exits with no residual process, timer, daemon, thread, or
  listening port.

## Redacted evidence package template

Record only: approval reference; run and delivery opaque IDs; route; local-date
range; receipt status and exit code; artifact/plan revision IDs; idempotency
outcome; reconciliation outcome; counts; timestamps; Harness/schema/policy
hashes; process-cleanup result; and reviewer decision. Do not include health
data, body text, prompts, account addresses, credentials, or provider logs.

## Go/no-go record

Decision: `go` / `no-go`

Required attachments: written authorization reference, redacted receipts,
revision/delivery reconciliation evidence, sensitive-log review result,
process-cleanup evidence, reviewer signature, and rollback decision. Any
unexpected send, unreconciled delivery, missing evidence, sensitive-data
finding, or failed invariant is `no-go`; retain evidence and leave the legacy
entry and production configuration unchanged.
