# Gmail MCP production binding

This runbook contains no credentials. The production server reuses the OAuth
files created by the authenticated Gmail MCP, but the TrainLab MCP server exposes
only the narrow operations required by this project.

## Required tools

- Resolve and verify the authenticated account.
- Search Gmail using an exact TrainLab run-id.
- Read a tracked thread and return normalized messages.
- Send multipart plain text plus inline-styled HTML to authenticated self only.
- Create/find the `TrainLab` label and apply it to the sent thread.

The self-send tool rejects any other recipient, requires the run-id in the
subject, sets `X-TrainLab-Run-ID` and requests a stable Message-ID, searches
before sending, and applies the label before returning its receipt. Gmail can
replace the standard Message-ID; production acceptance therefore requires an
exact preserved `X-TrainLab-Run-ID`, a nonempty Gmail message ID and an exact
run-id subject rather than equality on the provider-rewritten Message-ID.

## Credential boundary

The ignored production mapping points to the existing Gmail OAuth client and
token files outside the repository. Both files and their parent directory must
be owner-only. Credential values must never be printed, copied into YAML, passed
in prompts or included in acceptance evidence.

Scheduled Codex runs use the dedicated `runner.codex_home`. It links only the
existing Codex `auth.json`, registers only the TrainLab-restricted Gmail MCP, and
must not contain custom skills or installed marketplace plugins. Codex-created
system skills and remote catalog caches are allowed because they are not active
marketplace installations. This prevents a user-wide Gmail plugin from
shadowing the project MCP during stateless runs.
The runner sets a model-name-free `medium` reasoning effort because the bounded
health context, deterministic safety policy, HTML rendering and MCP sequence are
a multi-step task. Runner diagnostics retain only MCP start/completion event
names and exit status, never the prompt, report or tool payload.
The Codex command also marks the MCP server required, allowlists exactly the five
TrainLab tools, and sets per-tool `approval_mode = "approve"` only for
`send_html_self` and `create_or_apply_label`. This is the narrow unattended-write
mechanism documented in the official Codex configuration reference; it does not
disable the read-only sandbox or approve shell commands.

## Acceptance

`trainlab doctor` is read-only: it verifies the account, search capability, MCP
tool contract and local credential permissions without sending a message. The
explicit real-run acceptance then verifies multipart rendering, self recipient,
run-id headers, TrainLab label, search idempotency and thread readability. Codex
acceptance is recorded separately from watchdog acceptance; development Harness
expiry and production timer enablement require both.
