import { test as base, expect } from "@playwright/test";
import { AuthHost, CODE, ORIGIN, PREFIX, attackServer, authStatus, login, mfa, post, protect, ready, saved } from "./auth-host";

const test = base.extend<{ host: AuthHost }>({
  host: async ({ context }, use, info) => {
    const host = new AuthHost();
    await host.start();
    await protect(context);
    try { await use(host); }
    finally {
      await info.attach("safe-sdk-receipt", { body: JSON.stringify(await host.command("inspect")), contentType: "application/json" });
      await host.close();
    }
  },
});

for (const region of ["com", "cn"] as const) {
  for (const needsMfa of [false, true]) {
    test(`C01-C03 ${region} ${needsMfa ? "MFA reload" : "ordinary"} real SDK`, async ({ page, host }) => {
      await host.configure({ mfa: needsMfa });
      await ready(page);
      await expect(page.getByText("DATABASE_UNAVAILABLE: database is unavailable", { exact: true })).toBeVisible();
      await login(page, region);
      if (needsMfa) {
        await expect(page.getByRole("status")).toHaveText("等待验证码");
        const before = (await authStatus(page)).login;
        await page.reload();
        await expect(page.getByRole("status")).toHaveText("等待验证码");
        expect((await authStatus(page)).login.expires_at_utc).toBe(before.expires_at_utc);
        await mfa(page);
      }
      await saved(page);
      const status = await authStatus(page);
      expect(status.stored.region).toBe(region);
      expect(status.stored.server_verified).toBe(false);
      expect(await page.getByLabel("密码", { exact: true }).inputValue()).toBe("");
      expect(await page.getByLabel("账号", { exact: true }).inputValue()).toBe("");
      const receipt = await host.command("inspect");
      expect(receipt.exchange_count).toBe(1);
      const hosts = receipt.events.filter((event) => !event.path.includes("oauth_consumer")).map((event) => event.host);
      expect(hosts.every((value) => value.endsWith(`garmin.${region}`))).toBe(true);
      if (needsMfa) {
        expect(receipt.events.filter((event) => event.path.includes("verifyMFA"))).toHaveLength(1);
        expect(receipt.events.some((event) => event.path.includes("user-settings"))).toBe(true);
        expect(receipt.events.some((event) => event.path.includes("userprofile"))).toBe(true);
      }
      expect(await page.evaluate(async () => ({ local: localStorage.length, session: sessionStorage.length, dbs: (await indexedDB.databases()).length, sw: (await navigator.serviceWorker.getRegistrations()).length }))).toEqual({ local: 0, session: 0, dbs: 0, sw: 0 });
      expect((await page.context().cookies()).every((cookie) => cookie.httpOnly && cookie.sameSite === "Strict" && cookie.path === PREFIX)).toBe(true);
    });
  }
}

for (const failure of ["401", "403", "429", "timeout", "html", "bad-mfa", "settings"] as const) {
  test(`C04 actual SDK failure ${failure}`, async ({ page, host }) => {
    const mfaFailure = failure === "bad-mfa" || failure === "settings";
    await host.configure(mfaFailure ? { mfa: true } : failure === "timeout" || failure === "html" ? { mode: failure } : { failure_path: "/sso/signin", failure_status: Number(failure) });
    await ready(page);
    await login(page);
    if (mfaFailure) {
      await expect(page.getByRole("status")).toHaveText("等待验证码");
      await host.configure(failure === "settings" ? { failure_path: "user-settings", failure_status: 503 } : { bad_mfa: true });
      await mfa(page);
    }
    await expect(page.getByRole("alert").filter({ hasText: /认证|服务|验证码/ })).toBeVisible();
    await expect(page.getByRole("status")).toHaveText("认证未完成");
    expect((await authStatus(page)).stored.saved).toBe(false);
    expect((await host.command("inspect")).pointer).toBeNull();
  });
}

test("C05 cancel/restart old attempt, expired challenge and session", async ({ page, host }) => {
  await ready(page); await login(page); await saved(page);
  const pointer = (await host.command("inspect")).pointer;
  await host.configure({ mfa: true });
  await login(page, "cn");
  await expect(page.getByRole("status")).toHaveText("等待验证码");
  const old = (await authStatus(page)).login.attempt_id!;
  await page.getByRole("button", { name: "取消验证" }).click();
  await expect(page.getByRole("status")).toHaveText("已取消验证");
  expect((await host.command("inspect")).pointer).toBe(pointer);
  await login(page);
  await expect(page.getByRole("status")).toHaveText("等待验证码");
  expect(await post(page, "cancel", { attempt_id: old })).toBe(400);
  await host.command("advance", { seconds: 301 });
  await expect(page.getByRole("status")).toHaveText("验证已过期");
  await login(page, "cn");
  await expect(page.getByRole("status")).toHaveText("等待验证码");
  await host.command("advance", { seconds: 1801 });
  await expect(page.getByRole("alert").filter({ hasText: "会话已失效" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "账户区域" })).toBeEnabled();
});

test("C05 delayed real status response cannot replace a newer attempt", async ({ page, host }) => {
  await host.configure({ mfa: true });
  await ready(page); await login(page, "com");
  await expect(page.getByRole("status")).toHaveText("等待验证码");
  const old = (await authStatus(page)).login.attempt_id;
  await host.command("hold_status");
  await expect.poll(async () => (await host.command("inspect")).status_entered).toBe(true);
  await page.getByRole("button", { name: "取消验证" }).click();
  await expect(page.getByRole("status")).toHaveText("已取消验证");
  await login(page, "cn");
  await expect(page.getByRole("status")).toHaveText("等待验证码");
  const current = (await authStatus(page)).login.attempt_id;
  expect(current).not.toBe(old);
  await host.command("release");
  await expect(page.getByText(/验证区域：中国区/)).toBeVisible();
  await mfa(page); await saved(page);
  expect((await authStatus(page)).stored.region).toBe("cn");
});

test("C06 simultaneous submit, other browser cannot cancel or answer", async ({ page, browser, host }) => {
  await host.configure({ mfa: true });
  await ready(page); await login(page);
  await expect(page.getByRole("status")).toHaveText("等待验证码");
  const attempt = (await authStatus(page)).login.attempt_id!;
  const other = await browser.newContext(); await protect(other);
  const second = await other.newPage(); await second.goto(ORIGIN);
  await expect(second.getByRole("status")).toHaveText("其他浏览器正在认证");
  expect(await post(second, "cancel", { attempt_id: attempt })).toBe(403);
  expect(await post(second, "mfa", { attempt_id: attempt, code: CODE })).toBe(403);
  await host.configure({ delay_path: "verifyMFA" }); await host.command("hold");
  await mfa(page);
  await expect.poll(async () => (await host.command("inspect")).entered).toBe(true);
  expect(await post(page, "mfa", { attempt_id: attempt, code: CODE })).toBe(409);
  expect((await page.request.get(ORIGIN + "/api/health")).status()).toBe(200);
  expect((await page.request.get(ORIGIN)).status()).toBe(200);
  await expect(page.getByRole("button", { name: "提交验证码" })).toBeDisabled();
  await host.command("release"); await saved(page);
  expect((await host.command("inspect")).events.filter((event) => event.path.includes("verifyMFA"))).toHaveLength(1);
  await other.close();
});

test("C07 real process restart preserves saved auth but invalidates challenge/session", async ({ page, host }) => {
  await ready(page); await login(page, "cn"); await saved(page);
  const stored = (await authStatus(page)).stored;
  await host.configure({ mfa: true }); await login(page);
  await expect(page.getByRole("status")).toHaveText("等待验证码");
  await host.stop(); await host.start(); await page.reload();
  await expect(page.getByRole("alert").filter({ hasText: "会话已失效" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("可开始登录");
  const after = (await authStatus(page)).stored;
  expect(after.saved).toBe(true); expect(after.region).toBe("cn");
  expect(after.expires_at_utc).toBe(stored.expires_at_utc);
});

test("C08 runtime maintenance before expiry commits, restart reads renewed generation", async ({ page, host }) => {
  await host.configure({ expiry: 20 });
  await ready(page); await login(page); await saved(page);
  const before = (await authStatus(page)).stored;
  const pointer = (await host.command("inspect")).pointer;
  expect((await host.command("inspect")).exchange_count).toBe(1);
  await host.command("advance", { seconds: 18 });
  await expect.poll(async () => (await host.command("inspect")).exchange_count).toBe(2);
  await expect(page.getByTestId("last-refreshed")).not.toHaveText("本次服务尚无刷新成功记录");
  expect((await host.command("inspect")).pointer).not.toBe(pointer);
  const maintained = await authStatus(page);
  const renewed = maintained.stored;
  expect(Date.parse(maintained.maintenance.last_refreshed_at_utc!)).toBeLessThan(Date.parse(before.expires_at_utc!));
  expect(renewed.expires_at_utc).not.toBe(before.expires_at_utc);
  const offset = (await host.command("inspect")).offset;
  await host.stop(); await host.start(offset); await page.reload();
  await expect.poll(async () => (await authStatus(page)).stored.expires_at_utc).toBe(renewed.expires_at_utc);
  expect((await authStatus(page)).stored.server_verified).toBe(false);
});

for (const failure of [503, 429, 401, 403, "timeout"] as const) {
  test(`C09 maintenance ${failure} sticky state and bounded retry`, async ({ page, host }) => {
    await host.configure({ expiry: 20 }); await ready(page); await login(page); await saved(page);
    await host.configure(failure === "timeout" ? { timeout_path: "/exchange/user/2.0" } : { failure_path: "/exchange/user/2.0", failure_status: failure });
    await host.command("advance", { seconds: 18 });
    if (failure === "timeout" || failure >= 500 || failure === 429) {
      await expect.poll(async () => (await authStatus(page)).maintenance.failures).toBe(1);
      await host.command("advance", { seconds: 5 });
      await expect.poll(async () => (await authStatus(page)).maintenance.failures).toBe(2);
      await host.command("advance", { seconds: 10 });
      await expect(page.getByTestId("maintenance-state")).toHaveText("维护已暂停");
      const count = (await host.command("inspect")).events.length;
      await page.reload();
      await expect(page.getByTestId("maintenance-state")).toHaveText("维护已暂停");
      expect((await host.command("inspect")).events.length).toBe(count);
      await host.configure({ failure_path: "", timeout_path: "" });
      await page.getByRole("button", { name: "重试维护" }).click();
      await expect(page.getByTestId("maintenance-state")).toHaveText("已安排期限检查");
      await expect(page.getByTestId("last-refreshed")).not.toHaveText("本次服务尚无刷新成功记录");
    } else {
      await expect(page.getByTestId("maintenance-state")).toHaveText("需要本人登录");
      await page.reload();
      await expect(page.getByTestId("maintenance-state")).toHaveText("需要本人登录");
      expect((await authStatus(page)).stored.saved).toBe(true);
      await expect(page.getByRole("button", { name: "重试维护" })).toBeDisabled();
    }
  });
}

test("C10 CLI generation wins, lock busy, storage failure keeps old pointer", async ({ page, host }) => {
  await ready(page); await login(page); await saved(page);
  await host.configure({ mfa: true }); await login(page);
  await expect(page.getByRole("status")).toHaveText("等待验证码");
  const attempt = (await authStatus(page)).login.attempt_id!;
  await host.command("lock");
  await mfa(page);
  await expect(page.getByRole("alert").filter({ hasText: "本次未执行" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("等待验证码");
  expect((await host.command("inspect")).events.filter((event) => event.path.includes("verifyMFA"))).toHaveLength(0);
  await host.command("unlock");
  expect((await host.command("actor", { action: "login" })).exit).toBe(0);
  await expect(page.getByRole("status")).toHaveText("认证未完成");
  expect(await post(page, "mfa", { attempt_id: attempt, code: CODE })).toBe(409);
  const pointer = (await host.command("inspect")).pointer;
  await host.command("lock"); await login(page);
  await expect(page.getByRole("alert").filter({ hasText: "认证操作中" })).toBeVisible();
  await host.command("unlock");
  await host.configure({ mfa: false, save_failure: true });
  await login(page);
  await expect(page.getByRole("alert").filter({ hasText: "保存失败" })).toBeVisible();
  expect((await host.command("inspect")).pointer).toBe(pointer);
  expect((await authStatus(page)).stored.saved).toBe(true);
  await host.configure({ save_failure: false });
  expect((await host.command("actor", { action: "maintain" })).exit).toBe(0);
  expect((await host.command("actor", { action: "sync-once" })).exit).toBe(0);
});

test("C11 actual cross-port browser attack is blocked before SDK", async ({ page, host, browser }) => {
  await ready(page);
  const closeServer = await attackServer();
  const attacker = await browser.newContext(); await protect(attacker);
  try {
    const attack = await attacker.newPage(); await attack.goto("http://127.0.0.1:8081");
    const result = await attack.evaluate(async ({ origin, prefix }) => {
      const results = [];
      for (const path of ["session", "cancel", "maintenance/retry"]) {
        try { await fetch(origin + prefix + "/" + path, { credentials: "include", method: path === "session" ? "GET" : "POST", headers: { "X-TrainLab-GUI": "1", "Content-Type": "application/json" }, body: path === "session" ? undefined : "{}" }); results.push("readable"); }
        catch { results.push("blocked"); }
      }
      return results;
    }, { origin: ORIGIN, prefix: PREFIX });
    expect(result).toEqual(["blocked", "blocked", "blocked"]);
    expect((await host.command("inspect")).events).toEqual([]);
    await login(page); await saved(page);
  } finally { await attacker.close(); await closeServer(); }
});

test("C12 shutdown in-flight waits for commit and restart has no writer left", async ({ page, host }) => {
  await host.configure({ delay_path: "/sso/signin" }); await host.command("hold");
  await ready(page); await login(page);
  await expect.poll(async () => (await host.command("inspect")).entered).toBe(true);
  await page.getByLabel("密码", { exact: true }).press("Enter");
  await page.getByLabel("密码", { exact: true }).press("Enter");
  const stopping = host.stop();
  await new Promise((resolve) => setTimeout(resolve, 300));
  expect(host.process.exitCode).toBeNull();
  await host.command("release"); await stopping;
  await host.start(); await ready(page);
  expect((await authStatus(page)).stored.saved).toBe(true);
});
