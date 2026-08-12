# Foundation final acceptance and cutover gate

This runbook is a specification and approval gate. Running the synthetic
acceptance below does not authorize a real migration, backup, restore, shadow
publication, configuration change, or cutover.

## Offline synthetic acceptance

Use a new owner-only disposable directory outside every production, legacy,
source, and configured Foundation path:

```text
python scripts/verify_foundation_acceptance.py \
  --output-root /tmp/trainlab-foundation-fnd12-acceptance
```

Accept only a JSON result with `status=passed`, `tables_verified` covering all
Foundation tables plus `schema_migrations`, `views_verified=23`,
`fit_shapes_verified=6`, `privacy_findings=0`, repeat init
`already_initialized`, and status/verify both `ready`. Retain the reported
acceptance manifest SHA-256 with the test evidence. The disposable directory
contains the source sample, authenticated encrypted container, isolated
restored database, and shadow root. A second invocation against the same path
must fail rather than overwrite evidence.

This acceptance is projection-only and offline. It must not receive a
production configuration, provider credential, real FIT or email content,
health/GPS data, authorization URL, prompt/model payload, or access to a
Garmin, Gmail, Codex, network, daemon, scheduler, thread, or subprocess.

## Reconciliation gate

Before any separately approved real cutover, an operator-owned tool must record
and compare:

- a row count and canonical content SHA-256 for every table;
- a foreign-key constraint/value reference SHA-256 for every table;
- a row count and canonical content SHA-256 for all 23 stable views;
- checked raw-relative paths, file sizes, modes, and SHA-256 values;
- `PRAGMA integrity_check=ok` and an empty `PRAGMA foreign_key_check`;
- Foundation state, migration ledger, schema manifest, ready marker, and exact
  source/target schema versions.

Any mismatch blocks cutover. Do not normalize, drop, truncate, rewrite, or
silently skip a mismatching row to make reconciliation pass.

## Authenticated backup and isolated recovery

Create an explicit AES-256-GCM backup before an approved migration. Inject the
32-byte key through the approved secret mechanism; never pass or persist it in
a command line, environment variable, log, receipt, fixture, or repository.
The backup target must not already exist. Verify authentication, restore into a
new owner-only isolated target, and run the full reconciliation gate there.

A wrong key, changed container, existing restore target, integrity failure, FK
failure, or hash mismatch is a hard failure. Preserve the source and container
for investigation. Never recover by deleting the active database or data root,
and never run `init` to reconstruct an existing Foundation.

## Separately authorized real cutover checklist

No item below is permission to execute it. A named operator and change approval
must supply the exact source, destination, target schema version, maintenance
window, rollback owner, and injected backup key.

1. Freeze and confirm all writers, schedulers, collectors, analysis jobs, mail
   workers, delivery workers, and orchestration workers are stopped.
2. Resolve owner-only Foundation configuration and prove every path is the
   approved path; reject symlinks, aliases, writable ancestors, and overlap
   with legacy/source paths.
3. Capture read-only `status` and `verify` receipts. Stop if either is not
   `ready` or if state, marker, migration ledger, manifest, integrity, FK, or
   filesystem gates disagree.
4. Create and authenticate an encrypted backup into a new target; restore it
   into an isolated new target and complete the reconciliation gate.
5. Build a new shadow without replacing the source. Reconcile every table,
   reference, view, and raw object and verify the shadow is `ready`.
6. If a schema change is approved, invoke only explicit `migrate` with the
   exact approved target. Preserve its exact migration receipt. Never rely on
   `init`, bootstrap, or a consumer to migrate.
7. On any pre-publication failure, leave the active source unchanged and keep
   the last known-good source, backup, receipts, and failed evidence. On a
   post-commit/marker interruption, follow the deterministic same-target
   explicit migration recovery; do not improvise repair.
8. Switch configuration only after an independent reviewer signs the
   reconciliation and recovery evidence. Start one writer family at a time,
   verify read/write ownership and delivery-family isolation, then start the
   next layer.
9. Observe health and incident evidence through the approved window. Retain the
   prior source unchanged until rollback expiry.

Rollback means switching back to the preserved last known-good source under the
approved writer freeze. It never means deleting data, overwriting evidence,
re-initializing a path, or modifying legacy data to resemble the new schema.
