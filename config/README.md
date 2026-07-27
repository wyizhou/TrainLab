# TrainLab configuration

`config/trainlab.json` is the project-wide local user configuration file.
Future layers may add their own top-level sections to this same file.

The file is intentionally excluded from Git because it may contain personal
settings. Copy the structure from `config/trainlab.example.json` and set
`mail.recipient_email` to the one fixed address authorized to receive TrainLab
mail. `training_difficulty_level` is an integer from 1 through 5 and defaults
to 2 when omitted. `marathon_target_finish_time` and
`half_marathon_target_finish_time` accept `HH:MM` duration strings or `null`;
hours must use exactly two digits, minutes must be `00`–`59`, and `00:00` is
invalid. `null` means that race distance has no configured finish-time target.

These three training controls are authoritative user settings. Every analysis
AI invocation receives their explicit values and configuration sources in its
bounded context; they are not passive documentation. Operational settings such
as `mail.recipient_email` remain host-only authorization and never enter an AI
prompt. Credentials and OAuth tokens must never be stored in this file.
