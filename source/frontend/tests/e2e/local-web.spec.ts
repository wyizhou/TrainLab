import { expect, test, type Page } from "@playwright/test";

const forbiddenPrivatePath = /\/(states|verification|health)(\/|$)|data\.db|\.fit(\?|$)/i;

function trackPrivateRequests(page: Page): string[] {
  const requested: string[] = [];
  page.on("request", (request) => {
    requested.push(new URL(request.url()).pathname);
  });
  return requested;
}

function expectNoPrivateRequests(requested: string[]): void {
  expect(requested.filter((path) => forbiddenPrivatePath.test(path))).toEqual([]);
}

test("Chrome renders every local web function and keeps private files behind the API", async ({ page }) => {
  const requested = trackPrivateRequests(page);
  await page.goto("/", { waitUntil: "networkidle" });

  await expect(page.getByRole("heading", { name: "本地训练数据与 AI 总结" })).toBeVisible();
  await expect(page.getByText("仅连接本机 /api")).toBeVisible();

  await expect(page.getByRole("heading", { name: "同步状态" })).toBeVisible();
  await expect(page.getByText("2030-01-05T00:00:00.000000Z").first()).toBeVisible();
  await expect(page.getByText("是否到期")).toBeVisible();

  await expect(page.getByRole("heading", { name: "本地服务" })).toBeVisible();
  await expect(page.getByText("API 路由：16")).toBeVisible();
  await expect(page.getByText("数据库：已找到")).toBeVisible();
  await expect(page.getByText("AI 生成：未配置")).toBeVisible();
  await expect(page.getByText("静态输出：../skills/local-web/web")).toBeVisible();

  await expect(page.getByRole("heading", { name: "活动搜索" })).toBeVisible();
  const activityButtons = page.locator(".activity-list button");
  await expect(activityButtons).toHaveCount(2);
  await expect(activityButtons.nth(0)).toContainText("cycling");
  await expect(activityButtons.nth(1)).toContainText("running");
  await expect(page.locator(".detail-card")).toContainText("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb");
  await expect(page.locator(".detail-card")).toContainText("暂无活动报告。");

  await activityButtons.nth(1).click();
  await expect(page.locator(".detail-card")).toContainText("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
  await expect(page.locator(".detail-card")).toContainText("running");
  await expect(page.locator(".detail-card")).toContainText("安全文本 <strong>不会当 HTML</strong>");
  await expect(page.locator(".detail-card pre strong")).toHaveCount(0);

  await expect(page.getByRole("heading", { name: "周总结" })).toBeVisible();
  await expect(page.locator(".report-block")).toContainText("2030-01-08T15:00:00.000000Z");
  await expect(page.locator(".report-block")).toContainText("周总结全文");

  const search = page.getByRole("textbox", { name: "搜索" });
  await search.fill("running");
  await expect(page.locator(".activity-list button")).toHaveCount(1);
  await expect(page.locator(".activity-list button")).toContainText("running");
  await search.fill("not-present");
  await expect(page.getByText("没有匹配活动。")).toBeVisible();

  const api404 = await page.evaluate(async () => {
    const response = await fetch("/api/not-present");
    return { status: response.status, body: await response.json() };
  });
  expect(api404.status).toBe(404);
  expect(api404.body).toMatchObject({ ok: false, error: { code: "ACTIVITY_NOT_FOUND" } });

  const spaResponse = await page.goto("/not-a-real-spa-route");
  expect(spaResponse?.status()).toBe(200);
  await expect(page.getByRole("heading", { name: "本地训练数据与 AI 总结" })).toBeVisible();
  expectNoPrivateRequests(requested);
});

test("Chrome shows API error state without reading private files", async ({ page }) => {
  const requested = trackPrivateRequests(page);
  await page.route("**/api/activities?**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: false,
        data: null,
        error: { code: "DATA_INVALID", message: "forced activity failure", details: {} },
      }),
    });
  });

  await page.goto("/", { waitUntil: "networkidle" });

  await expect(page.getByText("DATA_INVALID: forced activity failure")).toBeVisible();
  await expect(page.locator(".activity-list button")).toHaveCount(0);
  expectNoPrivateRequests(requested);
});
