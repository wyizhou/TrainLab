---
name: training-report-publisher
description: Convert a validated TrainLab daily summary, weekly summary, or training plan into one reviewable report and an email-safe HTML rendering. Use for scheduled or manual TrainLab report presentation, fixed-template rendering, open-form Data Analytics reports, or an explicitly authorized Sites snapshot; do not use to analyze raw health data, change a training decision, send email, or publish without authorization.
---

# Training Report Publisher

## Required boundaries

- Read the repository root instructions and `source/AGENTS.md` first. If the runtime file does not
  exist yet, return `runtime_harness_unavailable` before reading private inputs or rendering.
- Accept only a validated, hash-bound TrainLab output whose schema is explicitly supported. Bounded
  aggregate health and training metrics may appear in that output; do not read raw point sequences,
  health raw, FIT, GPX, TCX, credentials, or Gmail.
- Preserve the input facts, course contract, safety decision, provenance, and approval state exactly.
- Write outputs and run state through the approved SQLite contract. If that contract is not yet
  implemented, return `runtime_state_contract_unavailable`; do not create a second authoritative
  artifact store.
- Leave email transport to `gmail-sender`.

## Select one primary mode

Read [references/report-modes.md](references/report-modes.md), then select exactly one mode:

- Prefer `open_report` when the installed `$data-analytics:build-report` skill is available. Build one self-contained HTML report from the bounded structured input, then derive an email-safe HTML rendering from the same canonical content.
- Use `fixed_email` when the caller requests the TrainLab fixed style or when an explicitly approved fallback permits it.
- Never combine both report bodies in one email.

If `open_report` is selected but its dependency is unavailable, return
`report_builder_unavailable`. Fall back to `fixed_email` only when the caller's request or
preauthorization explicitly permits fallback.

## Open report workflow

1. Verify every source output ID, full SHA-256, schema version, report kind, period, and lineage.
2. Invoke `$data-analytics:build-report` in portable HTML mode because email conversion requires an
   HTML source. This project-level downstream requirement overrides that dependency's normal Sites
   routing; do not select `sites-app` here.
3. Keep one audience and one report delivery mode. Use visible sections, bounded evidence, caveats, and source metadata.
4. Inspect the rendered report and reject missing, altered, or unsupported claims.
5. Save the validated canonical report first as an immutable `report_artifact` revision with its
   structured JSON, readable text, self-contained HTML, lineage, and content hash.
6. Derive an email-safe rendering from that persisted report, with no scripts, forms, remote
   interactive dependency, hidden tracking, or credential-bearing links.
7. Save the derivative as a separate immutable `email_render` revision bound to the exact
   `report_artifact` ID and SHA-256. Never combine or reverse these two persistence stages.

## Fixed email workflow

1. Verify the same input contract as `open_report`.
2. Select exactly one tracked template from `source/templates/fixed/`.
3. Fill only declared placeholders; escape untrusted text and reject unknown required fields.
4. Save the fixed-style canonical `report_artifact` first, with structured JSON, readable text,
   self-contained HTML, and the exact template hash.
5. Derive and save a separate email-safe `email_render` revision from that same validated content.
   Both revisions must bind the same source facts; neither may be skipped or silently combined.

## Optional Sites snapshot

Use `$data-analytics:publish-artifact-to-sites` only as a separate, optional action after the canonical report validates and a
separate approval covers the exact report hash, Sites publication, access boundary, and validity
window. Treat the Site as a published snapshot, not a live health-data connection. Record the
external action before publication and reconcile an unknown outcome before any retry.

The email body must remain independently readable. A Sites URL may be an optional link; it must
never be required to view the report.

## Output contract

Return bounded fields suitable for the planned SQLite `skill_outputs` record:

- `mode`: `open_report` or `fixed_email`
- `report_kind`: `daily` or `weekly`
- `source_outputs`: an ordered list of exact output IDs, roles, schemas, and full SHA-256 values
- `canonical_report` with structured JSON, readable text, and self-contained HTML
- `email_render` with subject, plain text, email-safe HTML, and content hash
- `lineage` with input, template or report-builder version, and transformation hashes
- `sites_snapshot`: absent unless separately authorized; otherwise only bounded IDs, URL, snapshot time, and status
- `status` and a stable, sanitized `error_code`

Do not include recipients, credentials, raw health values, raw file contents, hidden reasoning, or
full Provider responses.

Use only these initial failure codes:

- `blocked`: `runtime_harness_unavailable`, `runtime_state_contract_unavailable`,
  `input_hash_mismatch`, `dependency_output_missing`, `state_lock_unavailable`,
  `dependency_outcome_unknown`, `report_builder_unavailable`, `fixed_template_unavailable`,
  `sites_not_authorized`, and `sites_outcome_unknown`.
- `failed`: `input_contract_invalid`, `state_persistence_failed`,
  `report_validation_failed`, `fixed_template_invalid`, `email_render_unsafe`,
  `output_persistence_failed`, and `sites_publish_failed_safe`.
- `interrupted`: `run_interrupted`.
- `cancelled`: `run_cancelled`.

When `sites_outcome_unknown` is returned, keep the Sites external action at `unknown` and reconcile
it before retrying. Use `sites_publish_failed_safe` only when the provider explicitly rejected the
write and no Site was created or changed.
