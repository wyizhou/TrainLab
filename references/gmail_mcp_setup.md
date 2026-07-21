# Gmail MCP production binding

The production binding is TrainLab's restricted MCP server, not a general Gmail
tool surface. It reuses the already authenticated Gmail OAuth files but exposes
only current-account verification, search, thread read, multipart self-send and
TrainLab label application.

1. Copy `config/gmail_mcp.example.yaml` to the ignored mode-0600 file
   `config/gmail_mcp.yaml`.
2. Set `authenticated_self` and the two external credential paths. Never copy a
   client secret or token into YAML.
3. Use absolute production paths for the Python transport and mapping file.
4. Register `python -m trainlab.gmail_mcp_server --config <absolute mapping>` as
   the `gmail` stdio MCP in the dedicated `runner.codex_home`. Link the existing
   Codex `auth.json` into that owner-only home, but do not link or copy general
   custom skills or installed marketplace plugins. Codex-generated system skills
   and remote catalog caches are acceptable. Do not expose the general Gmail
   MCP to scheduled analysis.
5. Set `mail.mode: mcp` and `production.enabled: true` in the ignored production
   TrainLab config.
6. Run `trainlab doctor`. This is read-only and must verify self, search, tool
   names and credential permissions.
7. Run the explicit Codex real-send acceptance. Confirm multipart
   content, run-id headers, TrainLab label, thread read and idempotent re-search.

The complete operational and rollback procedure is in
`docs/runbooks/gmail-production.md`.
