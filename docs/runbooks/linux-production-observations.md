# Linux production observations

Status: non-normative compatibility notes
Observed environment: Ubuntu 24.04, systemd user services, Codex CLI 0.144.6,
Gmail API and rclone 1.74.4
Last verified: 2026-07-21

This document records issues encountered during the first TrainLab production
deployment. It is evidence for maintainers, not a cross-runner contract. Future
Codex versions, other agents and other mail providers may behave differently;
keep the shared Harness safety boundaries, then validate each adapter separately.

## Agent and schema observations

- The observed Codex output-schema validator accepted a strict JSON Schema
  subset: object properties needed explicit types, every declared property was
  required, and objects needed `additionalProperties: false`. `uniqueItems` was
  rejected in this toolchain. This belongs to the current Codex adapter only.
- The server's default reasoning setting did not reliably complete this report
  workflow. The current Codex adapter uses medium reasoning effort without
  naming a model. A future runner should choose and test its own setting.
- A general Gmail plugin in the user's normal Codex home could expose tools
  beyond TrainLab's five-operation boundary. The production adapter therefore
  uses a dedicated Codex home and an exact MCP tool allowlist. This is a
  Codex-specific isolation measure, not a requirement that every runner use the
  same directory layout.
- In the observed Codex CLI, external MCP writes were cancelled until approval
  was enabled only for `send_html_self` and `create_or_apply_label`. Broad
  approval or sandbox bypass was neither needed nor enabled. Other runners must
  be tested against their own write-approval behavior.
- A failed agent result must never be converted into a sent result merely
  because it contains report-shaped fields. Delivery state comes from Gmail
  evidence: the custom run-id, Gmail message/thread identifiers and an exact
  search result.

## Gmail observations

- Gmail replaced the submitted standard `Message-ID`. The stable idempotency
  key is `X-TrainLab-Run-ID`, reinforced by the subject run-id and Gmail's own
  message/thread identifiers. Do not depend on the provider preserving a custom
  standard `Message-ID`.
- Watchdog failure and recovery run-ids should contain ASCII state tokens. Human
  language belongs in the subject and body, not in the machine idempotency key.
- Real acceptance should verify self-recipient, text and HTML parts, inline
  styles, the TrainLab label, exact custom run-id, thread readability and exactly
  one search match.

## systemd and watchdog observations

- A transient runtime mask did not override an existing user unit in the first
  fault simulation. The successful, recoverable acceptance test first backed up
  the user unit, then applied a same-priority persistent mask and reloaded the
  user manager. This is an acceptance technique, not a production restart rule.
- Watchdog acceptance must observe three failed restart attempts, one failure
  email, restoration, one recovery email and cleared incident state. Restore the
  original unit immediately after the test.
- The deployment required the distribution's Python virtual-environment package
  and `bubblewrap`. `doctor` should report their absence instead of assuming all
  Linux images include them.

## Google Drive and packaging observations

- The rclone shared Google OAuth client emitted a retirement warning. Production
  uses the project's own desktop OAuth client, a separate Drive token and exact
  `drive.readonly` scope.
- `Health Metrics_v5` is a Google Sheet, so the sync path exports it to the fixed
  local XLSX target `source/Health.xlsx`; FIT files remain byte-identical and are
  checked by SHA-256.
- Archives created on macOS can carry AppleDouble or extended-attribute entries.
  When a Mac is only the editing mirror, create transfer archives without those
  entries, or build the release archive on Linux. This affects packaging hygiene,
  not TrainLab's runtime contract.
- A Git ignore rule does not automatically exclude a file from an operational
  transfer archive. Inspect the archive member list before transfer and explicitly
  exclude `.env*`, credentials, OAuth/rclone configuration, personal source data,
  the database, state, logs, caches and generated package metadata.
