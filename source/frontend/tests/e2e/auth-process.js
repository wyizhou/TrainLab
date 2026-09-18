import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { createInterface } from "node:readline";
import { createServer } from "node:http";
import { expect } from "@playwright/test";

export const ORIGIN = "http://127.0.0.1:8080";
export const PREFIX = "/api/garmin/auth";
export const PASSWORD = "synthetic-au32-password-canary";
export const CODE = "987123";

export class AuthHost {
  root = "";
  logs = "";
  process;
  id = 0;
  callbacks = new Map();
  async start(offset = 0) {
    if (!this.root) this.root = await mkdtemp(resolve(tmpdir(), "trainlab-auth-gui-"));
    let existing = false;
    try { await globalThis.fetch(ORIGIN + "/api/health"); existing = true; } catch { /* no existing server */ }
    if (existing) throw new Error("Refusing to reuse occupied 8080");
    const environment = globalThis.process.env.UV_PROJECT_ENVIRONMENT;
    if (!environment) throw new Error("External installed Python environment required");
    this.process = spawn(resolve(environment, "bin/python"), ["-m", "tests.e2e_support.serve_auth", "--root", this.root, "--offset", String(offset)], { cwd: resolve(".."), stdio: "pipe" });
    this.process.stderr.on("data", (data) => { this.logs += data.toString(); });
    createInterface({ input: this.process.stdout }).on("line", (line) => {
      const response = JSON.parse(line);
      this.callbacks.get(response.id)?.(response.data); this.callbacks.delete(response.id);
    });
    await expect.poll(async () => {
      if (this.process.exitCode !== null) throw new Error("Synthetic app process exited");
      try { return (await globalThis.fetch(ORIGIN + "/api/health")).status; } catch { return 0; }
    }).toBe(200);
  }
  command(op, extra = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      const timer = globalThis.setTimeout(() => { this.callbacks.delete(id); reject(new Error("private IPC timeout")); }, 25000);
      this.callbacks.set(id, (value) => { globalThis.clearTimeout(timer); resolve(value); });
      this.process.stdin.write(JSON.stringify({ id, op, ...extra }) + "\n");
    });
  }
  configure(values) { return this.command("configure", { values }); }
  async stop() {
    if (this.process.exitCode !== null) { expect(this.process.exitCode).toBe(0); return; }
    const exited = new Promise((resolve) => this.process.once("exit", resolve));
    await this.command("stop");
    expect(await exited).toBe(0);
    expect(this.logs).not.toContain(PASSWORD); expect(this.logs).not.toContain(CODE);
    expect(this.logs).not.toContain("synthetic-au32-token-canary");
  }
  async close() {
    await this.command("release");
    const receipt = await this.command("inspect");
    expect(receipt.external_attempts).toBe(0);
    expect(receipt.private_input_leaks).toBe(0);
    await this.stop();
    await rm(this.root, { recursive: true, force: true });
  }
}

export async function attackServer() {
  const server = createServer((_req, response) => { response.writeHead(200, { "Content-Type": "text/html" }); response.end("<html><body>synthetic cross-port page</body></html>"); });
  await new Promise((resolve) => server.listen(8081, "127.0.0.1", resolve));
  return () => new Promise((resolve) => server.close(resolve));
}
