# Garmin Layer Contract and Shadow Rollback Checklist

L2-17 is a provider-side boundary check. It does not authorize a migration,
real Garmin request, legacy daemon shutdown, fifth-layer scheduler, or any
change of canonical ownership.

## Contract boundary

- The fifth layer may build a typed Garmin invocation and consume only its exit
  code, schema-valid receipt, and public stable facts. It must not query or
  write `garmin_sync_*` tables.
- The analysis layer reads bounded stable views and quality facts only. It must
  not import a Garmin provider/client or make Garmin calls.
- The old `trainlab sync` and `trainlab ingest` commands remain available and
  unchanged while shadow evidence is collected.
- A reconciliation report is aggregate-only. It includes date windows, counts,
  hashes and controlled difference codes; it never includes raw payloads, FIT
  contents, GPS, health samples, tokens, account details, or email data.
- `canonical_owner: unchanged` is mandatory. A shadow report cannot select a
  winner or cause a write to either old or new canonical data.

## Shadow procedure

1. Capture separately retained legacy and Garmin snapshots for the same bounded
   Singapore-date window; record only each snapshot's SHA-256 in the report.
2. Generate the schema-valid aggregate report. Any controlled difference sets
   `decision: investigate`; do not paper over it with a tolerance.
3. Retain the receipt hash, report hash, input snapshot hashes and the exact
   invocation ID in the migration evidence store, outside user-visible logs.
4. Ask the total-control `X-02` task to perform cross-layer E2E validation.
   L2-17's fixture is intentionally not that test.

## Rollback / no-go checklist

- [ ] Legacy database/raw backup is verified and restorable.
- [ ] New Garmin state database/raw directory backup is verified and restorable.
- [ ] No `investigate` report is unresolved for the intended cutover window.
- [ ] Old `sync` and `ingest` commands have a passing offline regression.
- [ ] New collector is still disabled from production scheduling.
- [ ] Fifth layer has no direct Garmin-table write path.
- [ ] A named operator, approved time window and explicit cutover authorization exist.
- [ ] A tested rollback command/runbook restores scheduling to the legacy path
  without deleting Garmin raw evidence.

If any item is missing, remain in shadow mode. Do not delete data, change a
canonical owner, or stop the legacy daemon.
