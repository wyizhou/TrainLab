# rclone setup

TrainLab pins rclone 1.74.4. Create a read-only Google Drive remote named
`trainlab_drive` and use a dedicated Google OAuth client ID before production;
rclone's shared Drive client ID is being retired during 2026.
`trainlab doctor` therefore rejects production when the remote lacks either the
`drive.readonly` scope or a dedicated client ID.

The source items live at the Drive root:

- Google Sheet `Health Metrics_v5` is exposed by rclone as
  `Health Metrics_v5.xlsx`. Each run uses `rclone copyto` with the XLSX export
  format and stores it as the fixed local path `source/Health.xlsx`.
- Directory `HealthFit/` is copied exactly to `source/HealthFit/` with checksum
  and update checks.

The daemon never copies the Drive root as a whole, does not propagate cloud
deletions, and never deletes local raw files. Credentials and rclone
configuration belong outside the repository with mode 0600.

The authorization, candidate-config validation, refresh check, atomic promotion,
cleanup and rollback procedure is maintained in
[google-drive-bootstrap.md](google-drive-bootstrap.md).
