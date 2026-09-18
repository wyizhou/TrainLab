import { expect, type BrowserContext, type Page } from "@playwright/test";
import type { AuthStatus } from "../../src/garminAuth";
import { ORIGIN, PREFIX, PASSWORD, CODE } from "./auth-process.js";
export { AuthHost, ORIGIN, PREFIX, CODE, attackServer } from "./auth-process.js";

export async function protect(context: BrowserContext): Promise<void> {
  await context.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin === ORIGIN || url.origin === "http://127.0.0.1:8081") await route.continue();
    else { await route.abort(); throw new Error("Unexpected browser external request"); }
  });
}
export async function authStatus(page: Page): Promise<AuthStatus> {
  return page.evaluate(async (prefix) => (await (await fetch(prefix + "/status", { headers: { "X-TrainLab-GUI": "1" } })).json()).data, PREFIX);
}
export async function ready(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: "账户区域" })).toBeEnabled();
}
export async function login(page: Page, region: "com" | "cn" = "com"): Promise<void> {
  await expect(page.getByLabel("账户区域")).toBeEnabled();
  await page.getByLabel("账户区域").selectOption(region);
  await page.getByLabel("账号", { exact: true }).fill("synthetic@example.invalid");
  await page.getByLabel("密码", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "登录并保存" }).click();
}
export async function mfa(page: Page): Promise<void> {
  await expect(page.getByLabel("验证码", { exact: true })).toBeEnabled();
  await page.getByLabel("验证码", { exact: true }).fill(CODE);
  await page.getByRole("button", { name: "提交验证码" }).click();
}
export async function saved(page: Page): Promise<void> {
  await expect(page.getByRole("status")).toHaveText("认证已安全保存");
  await expect.poll(async () => (await authStatus(page)).stored.saved).toBe(true);
}
export async function post(page: Page, action: string, body: Record<string, string>): Promise<number> {
  return page.evaluate(async ({ action, body, prefix }) => {
    const session = (await (await fetch(prefix + "/session", { headers: { "X-TrainLab-GUI": "1" } })).json()).data;
    return (await fetch(prefix + "/" + action, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": session.csrf }, body: JSON.stringify(body) })).status;
  }, { action, body, prefix: PREFIX });
}
