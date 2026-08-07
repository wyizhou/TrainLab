# Isolated backup, restore, and rollback drill

This runbook proves only the backup/restore mechanism. It never authorizes an
operator to overwrite a production database, raw object, credential, or user
configuration. The drill generates schema-only SQLite databases below the
worktree's `state/test-tmp/` directory and makes no network, mailbox, Garmin,
or service call.

## What the drill admits

The command accepts only a new child directory of `state/test-tmp` and refuses
an existing directory. It creates two disposable backups: the current
Foundation schema and the immediately preceding published Foundation schema.
Each backup has a sidecar manifest binding the SHA-256 digest, schema version,
and `sanitized_generated` source classification.

Before promotion, the staged SQLite copy must pass all of these checks:

- manifest shape, generated-only classification, supported schema range, and
  digest match;
- `PRAGMA integrity_check` and `PRAGMA foreign_key_check`;
- the current Foundation manifest, or the exact published v2 compatibility
  fingerprint for the previous supported schema.

Only a fully admitted staging file can atomically replace the disposable
promotion target. A corrupt backup, missing manifest, unsupported newer or
older schema, or simulated interruption fails closed before promotion. The
interruption partition verifies that the target's digest is unchanged.

## Execute

From a clean source checkout, use the project virtual environment and an
explicit import path:

```bash
PYTHONPATH=src:. .venv/bin/python scripts/verify_restore_drill.py \
  --output-root state/test-tmp/restore-drill-$(uuidgen | tr A-Z a-z)
```

The command writes a data-free JSON receipt to stdout. Validate it against
`harness/schemas/restore_drill_receipt.schema.json`. The receipt must report
all seven exhaustive partitions:

1. `valid-current`
2. `valid-previous-supported`
3. `corrupt-backup`
4. `missing-manifest`
5. `newer-unsupported-schema`
6. `older-unsupported-schema`
7. `interrupted-restore`

The output directory is disposable test material. Do not point the command at
`state/`, `state/raw/`, a `data.db`, a backup archive, or any credential path.

## Compatibility and rollback limits

The supported rollback boundary is the current Foundation schema and exactly
one prior published schema (currently v2). The drill verifies admission of v2;
it does not automatically migrate, downgrade, or promote a real database.
Schemas newer than the running code and schemas older than v2 are rejected.
Any production recovery needs a separately approved, data-preserving
maintenance procedure: take an immutable backup, restore only into an
independent quarantine root, verify it, and obtain explicit authorization
before a release-specific migration or cutover. Never use this drill as a
production restore command.
