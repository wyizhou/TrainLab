# Foundation synthetic sample

Generate only into a new disposable directory:

```text
python scripts/generate_foundation_sample.py --output-root /tmp/trainlab-foundation-sample
```

The command refuses an existing output directory. It first uses `FoundationTool`
to initialize an isolated database, then writes projection-only synthetic rows.
Its raw files are explicitly placeholder evidence, not FIT, email, Garmin, or
Gmail payloads. The fixture contains no account addresses, credentials, real
GPS, device identifiers, or health data. It never reads project `data.db`,
`source/`, `test_data/new/`, or any network service.

The deterministic fixture includes every Foundation table and all 23 stable
views. It covers running, bouldering, indoor climbing, cycling, hiking, and
strength FIT projection shapes; health current/history; mail revisions and
deliveries; analysis, advice, plans and reason events; all three delivery
families; workflows, incidents, and lineage/current/history relationships.
`sample-acceptance.json` records row counts plus content/reference/raw hashes.
Generation fails if its privacy scan finds credentials, account addresses,
authorization URLs, raw HTML, full payloads/model responses, or hidden
reasoning.

For backup validation, inject a 32-byte key through the Python API and use
`backup_encrypted` / `restore_encrypted`; keys must never enter command lines,
environment variables, logs, receipts, or fixture metadata.

Run the complete FND-12 offline acceptance only in another new disposable
directory:

```text
python scripts/verify_foundation_acceptance.py \
  --output-root /tmp/trainlab-foundation-fnd12-acceptance
```

The command verifies repeat init/status/verify strict no-op behavior, an
authenticated encrypted backup and isolated restore, an atomic shadow rebuild,
SQLite integrity and foreign keys, exact row/content/reference/raw hashes, all
23 views, six FIT shapes, and a zero-finding privacy scan. It refuses to reuse
an output directory. This command does not authorize or perform a production
migration, restore, cutover, provider request, model request, or network call.

The production decision and recovery checklist is maintained separately in
`docs/runbooks/foundation-final-acceptance.md`.
