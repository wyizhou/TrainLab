# Foundation initialization and maintenance

Status: FND-11 operator draft

This runbook covers only the one-shot Foundation lifecycle and explicit schema
maintenance. It does not authorize production migration, backup, restore,
shadow rebuild, data import, or deletion.

## Command contract

All commands load the owner-controlled Foundation configuration. They do not
accept a data-root override and never start a daemon, worker, thread, timer, or
network listener.

| Command | Permitted effect | Successful status | Exit |
|---|---|---|---:|
| `trainlab foundation init` | Create an empty Foundation or resume an exact reviewed initialization checkpoint | `initialized`; `already_initialized` when ready | 0 |
| `trainlab foundation status` | Fast read-only ready marker, supported schema version, fixed path, and permission summary; does not open SQLite | `ready` | 0 |
| `trainlab foundation verify` | Full read-only database, schema manifest, migration receipt, integrity, and foreign-key verification | `ready` | 0 |
| `trainlab foundation migrate --target-version VERSION` | Explicit schema maintenance under the single-writer lock | `initialized` or `already_initialized` | 0 |

Other exit mappings are `incompatible` → 10, `lock_busy` → 11, and `failed` →
20. Standard output is exactly one redacted `FoundationReceipt`.

## Initial provisioning and bootstrap

1. On an empty, isolated Foundation root, run `trainlab foundation init`.
2. Require `status=initialized`, `ready=true`, and the supported
   `foundation_schema_version`.
3. Run `trainlab foundation verify` and require `status=ready`.
4. A later Layer-5 startup bootstrap calls `foundation init` once and proceeds
   only when it receives `already_initialized` for the supported ready schema.

Repeated init on a ready Foundation does not mutate it or acquire the writer
lock, but it deliberately performs the full read-only compatibility
verification before Supervisor startup. It may therefore scan a large
database. Any ready marker, filesystem, migration receipt, schema, integrity,
or foreign-key anomaly returns `incompatible/operator_review`; init does not
repair it.

Ordinary consumer calls and each Supervisor health cycle use the bounded
`status`/SQLite readiness paths. They must not substitute `verify` for every
poll. The health workflow runs a full SQLite integrity and foreign-key check
on its first observation and then only when the latest recorded attempt is at
least 24 hours old. Explicit migration, restore, acceptance, or incident
investigation may still require an immediate `verify`.

## Explicit migration

1. Stop normal writers through the deployment procedure.
2. Record the current `status` and `verify` receipts.
3. Run only the exact released target:
   `trainlab foundation migrate --target-version VERSION`.
4. Require a successful migration receipt, then run `status` and `verify`
   again before allowing consumers to start.

The migration authenticates the exact released source before opening it
read-write. Schema changes and migration receipts commit in one SQLite
transaction. A failure before commit rolls back the schema and restores the
known historical directory modes. The ready marker is published only after
the committed database passes manifest, receipt, integrity, and foreign-key
checks.

If the database transaction committed but marker publication did not, ordinary
init remains fail-closed. Only a repeated explicit migration to the same target
may validate the completed database and republish the marker. If the marker was
published before the command failed, `status` and `verify` must independently
prove the environment ready before it is used.

## Failure handling

- `lock_busy`: do not remove or rewrite the lock manually; retry through the
  controlled maintenance procedure after identifying the active owner.
- `incompatible`: preserve the database, raw tree, marker, sidecars, and
  receipt; route to operator review. Use `explicit_migrate` only when the
  receipt names that action.
- `failed`: preserve all evidence and stop. Do not rerun init to repair a ready
  environment.

Backup, restore, rebuild, production cutover, and data reconciliation remain
outside FND-11.
