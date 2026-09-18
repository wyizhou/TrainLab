import { spawnSync } from "node:child_process";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import config from "../playwright.config";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const tempDirs = [];

function tempDir() {
  const path = mkdtempSync(join(tmpdir(), "trainlab-e2e-env-"));
  tempDirs.push(path);
  return path;
}

function runServer(environment) {
  const env = { ...process.env };
  const blockedBin = tempDir();
  writeFileSync(join(blockedBin, "uv"), '#!/bin/sh\necho "Unexpected implicit installation blocked" >&2\nexit 97\n', { mode: 0o700 });
  env.PATH = `${blockedBin}:${env.PATH}`;
  delete env.UV_PROJECT_ENVIRONMENT;
  if (environment !== undefined) env.UV_PROJECT_ENVIRONMENT = environment;
  const server = config.webServer;
  if (!server || Array.isArray(server)) throw new Error("Expected one E2E web server");
  return spawnSync("/bin/sh", ["-c", server.command], {
    cwd: frontend,
    env,
    encoding: "utf8",
    timeout: 10_000,
  });
}

afterEach(() => {
  for (const path of tempDirs.splice(0)) rmSync(path, { recursive: true, force: true });
});

describe("default Playwright web server environment", () => {
  it.each(["venv", "venv with spaces and 'quotes'"])("uses caller interpreter without installing: %s", (name) => {
    const root = tempDir();
    const environment = join(root, name);
    mkdirSync(join(environment, "bin"), { recursive: true });
    const python = join(environment, "bin/python");
    writeFileSync(python, '#!/bin/sh\nprintf "%s\\n" "$UV_PROJECT_ENVIRONMENT" "$PWD" "$@" > "$UV_PROJECT_ENVIRONMENT/invocation"\n');
    chmodSync(python, 0o700);
    const result = runServer(environment);
    expect(result.error).toBeUndefined();
    expect(result.status, result.stderr).toBe(0);
    expect(readFileSync(join(environment, "invocation"), "utf8").split("\n")).toEqual([
      environment, resolve(frontend, ".."), "-m", "tests.e2e_support.serve_web", "",
    ]);
  });

  it("fails explicitly when environment is missing", () => {
    const result = runServer();
    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("UV_PROJECT_ENVIRONMENT");
  });

  it.each(["missing", "not-executable"])("fails without fallback for %s interpreter", (kind) => {
    const environment = tempDir();
    if (kind === "not-executable") {
      mkdirSync(join(environment, "bin"));
      writeFileSync(join(environment, "bin/python"), "not executable", { mode: 0o600 });
    }
    const result = runServer(environment);
    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("bin/python");
  });

  it("keeps system Chrome, port 8080 and no existing-server reuse", () => {
    expect(config.use?.channel).toBe("chrome");
    expect(config.use?.baseURL).toBe("http://127.0.0.1:8080");
    expect(config.webServer).toMatchObject({
      url: "http://127.0.0.1:8080/api/health", reuseExistingServer: false,
    });
  });
});
