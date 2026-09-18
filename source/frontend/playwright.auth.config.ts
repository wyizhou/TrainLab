import { defineConfig } from "@playwright/test";
import "./tests/e2e/auth-artifacts.js";

export default defineConfig({
  testDir: "./tests/e2e", testMatch: "**/*.auth.spec.ts", workers: 1,
  timeout: 60_000, fullyParallel: false, forbidOnly: true,
  reporter: [["list"], ["json", { outputFile: "../../exec-plans/evidence/ADHOC-0032/auth-web-developer/playwright-auth-results.json" }]],
  outputDir: "../../exec-plans/evidence/ADHOC-0032/auth-web-developer/playwright-auth-output",
  use: { baseURL: "http://127.0.0.1:8080", channel: "chrome", trace: "off", video: "off", screenshot: "off" },
});
