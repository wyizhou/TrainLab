---
name: trainlab-development
version: 1
status: expired
purpose: development-only
expired_at_utc: 2026-07-21T12:56:33.051768Z
---

---
name: trainlab-development
version: 1
status: awaiting-production-acceptance
expires_when: production-gmail-codex-and-watchdog-acceptance-pass
archive_target: archive/development-HARNESS.md
---

# Development harness

Build and verify the database, importers, compression, bounded context, report
contract, fake Gmail path, runner adapters, scheduler and watchdog. Use the real
sample files in `source/` and `test_data/` as golden fixtures without modifying
them.

Google Drive bootstrap and OAuth client rotation follow
`docs/runbooks/google-drive-bootstrap.md`. Development acceptance must prove all
of the following before production: the remote uses `drive.readonly` and a
project-owned client ID; the shared-client retirement warning is absent; the
exact Sheet exports to a valid XLSX; every FIT file matches by SHA-256; and a
refresh-token exchange succeeds. Build and test a candidate rclone config before
atomically replacing the active config, keep one mode-0600 rollback copy, and
remove every temporary authorization file after verification. Never place a
credential value in the repository or agent output.

The production Gmail binding follows `docs/runbooks/gmail-production.md`. It
must expose only authenticated-self send, exact run-id search, thread read and
TrainLab label operations. A real send is not implied by `doctor`; it belongs to
the explicit production acceptance run.

This harness must remain active until all production gates pass, including real
Gmail MCP send/search/read/label tests from Codex and the watchdog failure/recovery test. No secondary runner is active. On completion,
move this directory to its archive target, change its status to `expired`, record
the completion timestamp, and update AGENTS.md/CLAUDE.md to reference only the
runtime harness. Production tests must reject active references to `archive/`.
