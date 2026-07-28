# Google Drive bootstrap and OAuth rotation

This runbook is development/operations material. Scheduled analysis must never
load or execute it. It intentionally contains no account password, OAuth secret,
token, authorization URL or credential file content.

## Fixed contract

- rclone version is pinned by `config/trainlab.yaml`.
- The remote name is `trainlab_drive`.
- Scope is exactly `drive.readonly`.
- The OAuth client belongs to the TrainLab Google Cloud project; rclone's shared
  client ID is forbidden in production.
- Gmail and Drive may reuse that OAuth desktop client identity, but rclone must
  obtain its own Drive token. Never reuse the Gmail token.
- Only `Health Metrics_v5.xlsx` and `HealthFit/` are read. No Drive write,
  delete, sync-delete or root-wide copy is allowed.

## Bootstrap sequence

1. Confirm the Google Cloud project has the Drive API enabled and the OAuth
   desktop client is owned by TrainLab.
2. Back up the active rclone config to a new, explicit mode-0600 file.
3. Run rclone's browser authorization with the project client ID/secret and
   request only `drive.readonly`. On a headless host, use a temporary loopback
   SSH tunnel; close it after authorization.
4. Store the returned Drive token only in a mode-0700 temporary directory.
5. Build a candidate rclone config. Do not edit the live remote first.
6. Verify the candidate before promotion:
   - old and candidate remotes resolve to the same authenticated account;
   - the root contains exactly one `Health Metrics_v5.xlsx` and one `HealthFit/`;
   - the Sheet downloads and passes XLSX ZIP integrity validation;
   - the FIT file count and per-file SHA-256 match the existing source snapshot;
   - a refresh-token exchange returns a new access token;
   - no shared-client retirement warning is emitted.
7. Atomically replace the live config, keep the rollback copy at mode 0600, and
   repeat the exact-target download using the live remote.
8. Remove the temporary directory and authorization tunnel. Confirm no raw
   token copies remain.

## Runtime behavior

`trainlab sync` performs a one-way read into the fixed local source paths. It
uses `copyto` for the exported Sheet and `copy` with checksum/update checks for
FIT files. It never propagates Drive deletions and never removes local source
evidence. An authentication or target-visibility failure is reported and leaves
the previous local files intact.

## Rollback

Stop the sync daemon, copy the explicit pre-rotation backup over the active
rclone config, enforce mode 0600, and run the two exact-target read checks.
Rollback is temporary: a config using rclone's retiring shared client ID must not
be accepted by the production doctor or re-enabled for unattended service.
