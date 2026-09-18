import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { GarminAuthPanel } from "../src/GarminAuthPanel";
import { AuthError, authMessage, authRequest } from "../src/garminAuth";
import { apiRouteContracts } from "../src/contracts";

describe("Garmin independent GUI contract", () => {
  it("renders labelled two-region masked credentials without dashboard or database", () => {
    const html = renderToStaticMarkup(<GarminAuthPanel />);
    expect(html).toContain("国际区 (com)"); expect(html).toContain("中国区 (cn)");
    expect(html.match(/type="password"/g)).toHaveLength(2);
    expect(html).toContain("server_verified=false");
    expect(html).toContain("尚未确认"); expect(html).toContain("不启动 AI 或活动同步后台任务");
  });
  it("keeps exact route methods in sync", () => {
    expect(apiRouteContracts.map(({ method, path }) => `${method} ${path}`).sort()).toEqual([
      "GET /api/health", "GET /api/status", "GET /api/sync/status", "GET /api/activities", "GET /api/activities/{activity_id}",
      "GET /api/reports/activity/{activity_id}", "POST /api/reports/activity/{activity_id}/generate",
      "GET /api/reports/weekly", "GET /api/reports/weekly/{report_id}", "POST /api/reports/weekly/generate",
      "GET /api/garmin/auth/session", "GET /api/garmin/auth/status", "POST /api/garmin/auth/login",
      "POST /api/garmin/auth/mfa", "POST /api/garmin/auth/cancel", "POST /api/garmin/auth/maintenance/retry",
    ].sort());
  });
  it("uses fixed errors not server HTML or raw exception, never replays", async () => {
    const mock = vi.fn().mockResolvedValue({ json: async () => { throw new Error("synthetic-secret"); } });
    vi.stubGlobal("fetch", mock);
    try {
      await expect(authRequest("login", "synthetic-csrf", { password: "synthetic-secret" })).rejects.toThrow(authMessage("network_failed"));
      expect(mock).toHaveBeenCalledTimes(1);
      const [url, options] = mock.mock.calls[0];
      expect(url).toBe("/api/garmin/auth/login");
      expect(options.cache).toBe("no-store");
      expect(options.credentials).toBe("same-origin");
      expect(new AuthError("synthetic-secret").message).not.toContain("synthetic-secret");
    } finally { vi.unstubAllGlobals(); }
  });
});
