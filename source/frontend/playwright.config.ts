import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  testIgnore: "**/*.auth.spec.ts",
  timeout: 30_000,
  fullyParallel: false,
  forbidOnly: true,
  reporter: [["list"], ["json", { outputFile: "../../exec-plans/evidence/ADHOC-0032/auth-web-developer/playwright-default-results.json" }]],
  outputDir: "../../exec-plans/evidence/ADHOC-0032/auth-web-developer/playwright-default-output",
  use: {
    baseURL: "http://127.0.0.1:8080",
    channel: "chrome",
    trace: "off",
    video: "off",
    screenshot: "off",
  },
  webServer: {
    command: 'cd .. && : "${UV_PROJECT_ENVIRONMENT:?Set UV_PROJECT_ENVIRONMENT to an installed external Python environment}" && "$UV_PROJECT_ENVIRONMENT/bin/python" -m tests.e2e_support.serve_web',
    url: "http://127.0.0.1:8080/api/health",
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
