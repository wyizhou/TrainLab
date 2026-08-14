# Analysis shadow migration and rollback gate

This runbook is an offline protocol and evidence checklist. It does not execute
either legacy or new analysis path, open a database, send email, publish an
artifact, change configuration, or authorize a cutover.

## Preconditions

- A3-22 and A3-23 evidence is complete and independently reviewed.
- The legacy production entry remains unchanged.
- A separate release authorization names the operator, approved window, target
  subject/date scope, backup owner, rollback owner, and evidence location.
- The approved evidence collector produces redacted manifests only: hashes,
  opaque IDs, counts, route status, and timestamps. It must exclude health
  payloads, artifact bodies, prompt text, addresses, credentials, and logs.

## Offline comparison protocol

1. Obtain one redacted legacy manifest and one redacted non-current shadow
   manifest for the same subject and logical local date.
2. Verify the shadow manifest records `current_published=false`,
   `email_sent=false`, and delivery count zero. No email is permitted.
3. Compare only input/output hashes, opaque artifact IDs, and counts using the
   offline `trainlab.analysis.shadow` DTO. A mismatch is a no-go for review.
4. Enforce collision prevention: a shadow result for a subject/logical date
   cannot be a current publication for that same target.
5. Preserve the comparison result as redacted evidence. A `go` result means
   eligible for human review only; it is not permission to execute shadow or
   cutover work.

## Backup and rollback checklist for a separately authorized operation

- [ ] Record approved source and target identities without copying sensitive
  values into this runbook or evidence package.
- [ ] Confirm all relevant writers and schedulers are frozen by the approved
  operator before backup or cutover work.
- [ ] Create and verify a recoverable backup through the approved operational
  procedure; retain its redacted integrity evidence.
- [ ] Verify no shadow artifact is current and no shadow delivery exists.
- [ ] Keep the legacy entry intact; do not rename, delete, or replace it.
- [ ] Define rollback as returning invocation ownership to the preserved legacy
  entry under the approved writer freeze, without deleting records or evidence.
- [ ] Stop at any mismatch, failed verification, collision, or missing approval.

## Cutover decision record

The reviewer records `go` or `no-go`, the redacted evidence hashes, comparison
codes, approval reference, backup verification reference, rollback owner, and
timestamp. Actual shadow execution, backup/restore, configuration changes, and
cutover each require separate release authorization.
