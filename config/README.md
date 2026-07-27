# TrainLab configuration

`config/trainlab.json` is the project-wide local user configuration file.
Future layers may add their own top-level sections to this same file.

The file is intentionally excluded from Git because it may contain personal
settings. Copy the structure from `config/trainlab.example.json` and set
`mail.recipient_email` to the one fixed address authorized to receive TrainLab
mail. Credentials and OAuth tokens must never be stored in this file.
