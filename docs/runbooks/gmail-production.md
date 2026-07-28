# Gmail MCP production binding

TrainLab's Gmail MCP server name is always `gmail`. It is supplied by the
current Codex execution environment and implemented by
`@artymclabin/gmail-mcp`; the project does not launch a machine-specific Gmail
server or store OAuth/token paths.

## Setup

```text
npx @artymclabin/gmail-mcp auth
codex mcp add gmail -- npx @artymclabin/gmail-mcp
codex mcp get gmail --json
```

Run these commands independently in each deployment environment. Do not copy a
token, credential file, Codex home, executable path, or working directory from
another machine.

Use `codex mcp get gmail --json` to verify the exact enabled binding before
running a mailbox workflow. Missing, disabled, differently named, or
incompatible bindings fail closed with the setup instructions above.

## Permission boundary

The package provides a broad Gmail surface, but TrainLab does not grant that
surface wholesale:

- analysis generation has no Gmail tools;
- each delivery or inbox route uses a fixed adapter allowlist;
- recipients remain authenticated-self only;
- labels remain fixed to `TrainLab`;
- sending always performs an exact idempotency search first;
- delete, Trash, spam, forwarding and unrelated mailbox changes are forbidden.

Third-, fourth- and fifth-layer code uses the environment binding directly; the
retired TrainLab-specific Gmail wrapper is not part of the shipped project.

## Acceptance

1. Missing-server test returns `gmail_mcp_not_configured` without starting a
   provider process.
2. Wrong package, fixed cwd/env, or disabled server fails closed.
3. Read-only authentication probe succeeds without printing mailbox data.
4. A separately authorized self-send acceptance verifies exact run ID,
   multipart content, TrainLab label, provider IDs and idempotent replay.
