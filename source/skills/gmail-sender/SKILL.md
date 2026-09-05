---
name: gmail-sender
description: Prepare bounded Gmail self-delivery and send approved reports through the official Gmail REST API with deterministic Message-ID reconciliation. Never invent a recipient or bypass the owner-only Candidate ledger.
---

# Gmail Sender

Read `source/AGENTS.md`, the approved `skill_outputs` row and `external_actions` state. The default target
is the authenticated mailbox itself. Use tracked `source/email.module.json` only as an empty structural
template, and resolve the real address only from owner-only `source/email.json`; no address is copied into
tracked files, reports, or public logs.

## Rules

- Query only when the request is within the recorded Gmail scope and marker contract.
- Require `email.json` schema `trainlab_email_recipient_v1`, one valid `email` value, mode `0600`, current
  owner, one hard link and no symlink before preparing or sending.
- Send only the exact title/text/HTML SHA recorded by `training-report-publisher`; do not silently rewrite it.
- Use a deterministic requested RFC822 `Message-ID` and idempotency key. Gmail may replace that header;
  success then binds the Gmail message ID and the actual RAW RFC822 `Message-ID` while rechecking recipient,
  subject, text and HTML. Ambiguity or a lost send response is `unknown`, never a resend.
- The old `raw/gmail` namespace is not recreated by this Skill.
- Ordinary workflows remain provider-disabled; `scripts/prepare_message.py` only validates a bounded message
  envelope.
- The explicitly approved M10 r06 batch uses `scripts/gmail_rest_delivery.py` and the official Gmail REST API.
  It must persist an owner-only intent before `messages.send`, save sanitized REST captures, read back RAW MIME,
  and verify recipient, subject, text, HTML and Message-ID before SQLite success.
- Gmail MCP, SMTP and Codex Gmail Connector are forbidden for this path. A send response loss may only be
  reconciled with the exact Message-ID; it never authorizes a second send.
- The approved M10 r07 continuation uses `scripts/gmail_rest_continuation.py`: it preserves the delivered
  ordinal-1 canary, cancels the seven superseded r06 actions and creates exactly seven newly titled actions.
  It must never create or send a replacement ordinal 1.
- The approved M10 r08 corrected-title batch reuses that parameterized host. It preserves all eight r06/r07
  successes, creates exactly eight new corrected-title actions, and blocks ordinals 2–8 until the user
  confirms receipt of the corrected ordinal-1 canary.
- M11 readable-email v2 uses `multipart/alternative` with a nested `multipart/related` HTML part and verified
  CID PNG attachments. `scripts/gmail_readable_delivery.py` is a provider-neutral Fake REST harness for the
  single-send/reconcile state machine. The separately approved M11 live-canary batch binds that state machine
  through `scripts/gmail_readable_live.py` to the existing Gmail REST host for exactly two messages: daily
  `2026-08-12`, then only after user confirmation in Gmail web and mobile, weekly
  `2026-08-12~2026-08-18`. It is not an ordinary runtime entrypoint.
- The same script can package owner-only offline RAW previews from a validated render and its exact PNG files.
  It always uses the non-deliverable synthetic recipient `preview@trainlab.invalid`; this operation has zero
  Provider calls and cannot be interpreted as Gmail authorization.

## M11 live canary

Only after the M11 code gate and a fresh Code Validator PASS, create a new owner-only Candidate from the
frozen r03 preview and send the daily canary:

If `send-started.json` exists but `send-response.json` does not, the live adapter first checks the single
owner-only sanitized `messages.send` capture for the same action and frozen MIME SHA. A unique 2xx response
from the official endpoint may restore its Gmail ID and continue with RAW verification; a missing capture
falls back to Message-ID lookup, while any conflicting or invalid capture remains `unknown`. This recovery
path is local and must never call `messages.send` again.

```bash
python3 skills/gmail-sender/scripts/gmail_readable_live.py build-candidate \
  --candidate-root /private/tmp/OWNER_ONLY_M11_LIVE_ROOT
python3 skills/gmail-sender/scripts/gmail_readable_live.py deliver-daily \
  --candidate-root /private/tmp/OWNER_ONLY_M11_LIVE_ROOT
```

Do not run `confirm-daily` until the user confirms the exact message in both Gmail web and mobile. Only then
may `deliver-weekly` run. After the same two-client confirmation for the weekly message, `confirm-weekly` and
`verify --final` close the Candidate. Each action has at most one send and sixteen Gmail API calls; the batch
has at most two sends and thirty-two delivery calls. Any `unknown`, authentication error, duplicate match or
RAW mismatch stops the batch and never authorizes another send.

The A-014 health-correction continuation is a versioned batch, not a retry of the first daily action. It
binds the first Candidate's one successful daily and untouched prepared weekly, then creates exactly two new
actions from the frozen corrected preview. The cumulative ceilings are three sends and 48 Gmail API calls.
Only the dedicated internal commands `build-health-correction`, `deliver-corrected-daily`,
`confirm-corrected-daily`, `deliver-correction-weekly`, `confirm-correction-weekly` and
`verify-health-correction` may operate this batch. The corrected daily must be confirmed on web and mobile
before the weekly action can be claimed.

### M11 v3 eight-message batch

A-017 authorizes one fixed, strictly serial batch from the validated r06 v3 Candidate: seven daily reports
for `2026-08-12` through `2026-08-18`, followed by the weekly report for
`2026-08-12~2026-08-18`. The user approved all eight at once, so this batch has no per-message manual
confirmation gate. It still requires each prior action to have a closed Gmail ID, actual RFC822 Message-ID,
RAW, text, HTML and CID result before the next action can be claimed.

```bash
python3 skills/gmail-sender/scripts/gmail_readable_live.py build-v3-batch \
  --candidate-root /private/tmp/OWNER_ONLY_M11_V3_LIVE_ROOT
python3 skills/gmail-sender/scripts/gmail_readable_live.py deliver-v3-batch \
  --candidate-root /private/tmp/OWNER_ONLY_M11_V3_LIVE_ROOT
python3 skills/gmail-sender/scripts/gmail_readable_live.py verify-v3-batch \
  --candidate-root /private/tmp/OWNER_ONLY_M11_V3_LIVE_ROOT --final
```

The commands accept no date, daily/weekly mode or request ID. Every item has a unique `item_key`; `kind`
only selects the daily or weekly render contract. The batch permits at most eight sends and 128 delivery API
calls. Any `unknown` stops the batch and leaves all later actions prepared; rerunning the command may only
reuse succeeded or terminal evidence and must not send that unknown action again.

## M10 r06 manual sequence

Code validation must pass before these commands are used. Authentication opens the system browser and sends no
mail:

```bash
python3 skills/gmail-sender/scripts/gmail_rest_auth.py
```

The client JSON must be a Google Desktop `installed` client using the exact official Google authorization and
token endpoints. Authorization succeeds only with a reloadable refresh token. The owner-only auth receipt is
fixed at ignored `source/gmail-api-auth-receipt.json`; changing its path is rejected so a failed process cannot
silently regain the one profile-call budget. It binds that profile call into the total 129-call budget, leaving
at most 128 delivery calls.
Each message may use at most five lookup/recovery calls, five RAW reads, five confirmation calls and one send.
Temporary read failures use 1/2/4/8-second waits; a message is never sent more than once.

After an owner-only r06 Candidate is built, `deliver-canary` sends only ordinal 1. `confirm-canary` is allowed
only after the user reports that exact canary visible in Gmail; `deliver-remaining` then sends ordinals 2–8
strictly one at a time. Never run the confirmation command on an assumption or solely from the local ledger.

For the frozen M10 r07 continuation, the user confirmation and existing send/RAW evidence reconcile the
already received canary with zero Provider calls. After code validation, build and deliver through:

```bash
python3 skills/gmail-sender/scripts/gmail_rest_continuation.py build-continuation \
  --candidate-root /private/tmp/OWNER_ONLY_R07_ROOT --confirm-canary-received
python3 skills/gmail-sender/scripts/gmail_rest_continuation.py deliver-remaining \
  --candidate-root /private/tmp/OWNER_ONLY_R07_ROOT/candidate
```

The remaining subjects are the six `TrainLab-Date(YYYY-MM-DD)` values for 2026-08-13 through 2026-08-18,
followed by `TrainLab-Week(2026-08-12~2026-08-18)`. The total remains exactly eight messages including the
old-title canary.

For M10 r08, use `build-r08`, `deliver-r08-canary`, `confirm-r08-canary --user-confirmed`, and only then
`deliver-r08-remaining`. Daily subjects are `TrainLab · 每日训练简报 · YYYY-MM-DD`; the weekly subject is
`TrainLab · 每周总结 · 2026-08-12~2026-08-18`. The old eight messages remain immutable and the combined
upper bound is sixteen.
