---
name: gmail-sender
description: Prepare bounded Gmail queries and send approved daily or weekly report emails through the exact local Gmail MCP binding. Use for self-delivery and mailbox reconciliation; never invent a recipient or bypass SQLite action state.
---

# Gmail Sender

Read `source/AGENTS.md`, the approved `skill_outputs` row and `external_actions` state. The default target
is the authenticated mailbox itself; no address is copied into reports or logs.

## Rules

- Query only when the request is within the recorded Gmail scope and marker contract.
- Send only the exact title/text/HTML SHA recorded by `training-report-publisher`; do not silently rewrite it.
- Use a stable marker and idempotency key. An existing marker is `already_sent`; ambiguity or a lost response
  is `unknown` and requires reconciliation, not a resend.
- The old `raw/gmail` namespace is not recreated by this Skill.
- This migration has no Gmail calls; `scripts/prepare_message.py` only validates a bounded message envelope.
