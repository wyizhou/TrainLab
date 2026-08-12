# Capacity and retention observation

TrainLab capacity monitoring is a cheap, metadata-only health observation. It
checks a configured filesystem root, the SQLite database and its WAL sidecar,
and direct entries of the configured raw, log, and temporary directories. It
uses filesystem statistics and file/directory metadata only. It never opens
file content, recursively enumerates a directory, emits a path or file name,
or reads FIT, Garmin JSON, SQLite rows, logs, backups, credentials, or user
configuration.

## Fixed scope and bounds

Each observation returns a fixed target (`disk`, `sqlite`, `wal`, `raw`,
`logs`, or `temp`), a fixed code, a severity, numeric byte counts, and for a
directory only the count scanned plus whether that bounded scan completed. The
default direct-entry cap is 128 (configuration is rejected outside 1–1024).
Reaching the cap emits `capacity_<target>_scan_limit_reached`; it is a warning,
not a claim about the unscanned remainder.

Defaults are intentionally reviewable:

| Target | Warning | Critical | Exact threshold |
| --- | ---: | ---: | --- |
| Disk used capacity | 80% | 90% | Warning/critical respectively |
| SQLite database | 512 MiB | 2 GiB | Warning/critical respectively |
| SQLite WAL | 128 MiB | 512 MiB | Warning/critical respectively |
| Raw, log, temporary direct-entry total | 2 GiB | 8 GiB | Warning/critical respectively |

An unavailable, invalid, or inaccessible metadata result emits only
`capacity_<target>_metadata_unavailable` with no path, file name, or source
content. It is non-success evidence for the production stability contract.

## Action and retention boundary

`*_warning` means review the configured target and confirm planned capacity.
`*_critical`, scan-limit, or metadata-unavailable means stop treating the
capacity SLO as healthy, preserve data-free operational evidence, and have an
operator investigate the storage/environment before continuing the stability
interval.

The monitor has no delete, rotation, truncate, archive, backup, or migration
operation. In particular, it never removes or alters FIT files, raw Garmin
JSON, SQLite databases/WAL files, backups, logs, temporary files, credentials,
or state. Any retention action requires separate explicit operator
authorization, a reviewed target list, backup/recovery evidence, and an
approved maintenance attempt; it is outside this monitor and its 14-day
observation loop.
