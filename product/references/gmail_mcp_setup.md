# Gmail MCP environment binding

TrainLab always uses the Gmail MCP named `gmail` from the current Codex
execution environment. The supported implementation is
`@artymclabin/gmail-mcp`.

Authenticate the package:

```text
npx @artymclabin/gmail-mcp auth
```

Register it in the current Codex environment:

```text
codex mcp add gmail -- npx @artymclabin/gmail-mcp
```

Confirm the binding:

```text
codex mcp get gmail --json
```

The binding must be enabled stdio with command `npx`, the single argument
`@artymclabin/gmail-mcp`, no fixed working directory, and no copied environment
secrets. TrainLab must not store a machine-specific executable, OAuth path,
token path, host path, or duplicate Gmail credentials.

If `gmail` is absent, disabled, points to another package, or fails its read-only
authentication probe, TrainLab stops before every mailbox action and reports
the two setup commands above. It never installs, authenticates, or falls back to
another Gmail transport automatically.

The general package exposes more Gmail tools than TrainLab needs. Each layer
must place a route-specific allowlist in front of it. Codex analysis generation
never receives Gmail tools; deterministic mail/delivery adapters may call only
the operations required for that route.
