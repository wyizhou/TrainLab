import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { App, DashboardView } from "../src/App";
import type { DashboardState } from "../src/contracts";
import { allApiRoutesStayUnderPrefix, apiRoutes, staticPolicy } from "../src/contracts";

const baseState: DashboardState = {
  loading: false,
  error: null,
  status: {
    service: "trainlab-local-web",
    local_only: true,
    database: { relative_path: "states/data.db", exists: true },
    sync: {
      last_attempt_at_utc: null,
      last_success_at_utc: "2030-01-01T00:00:00.000000Z",
      due: false,
      interval_seconds: 10800,
      synced: {},
    },
    ai_generation_configured: false,
  },
  activities: [],
  selectedActivityId: null,
  weeklyReports: [],
  query: "",
};

describe("TrainLab B6 React frontend", () => {
  it("keeps all public API routes under /api", () => {
    expect(apiRoutes.length).toBeGreaterThanOrEqual(10);
    expect(allApiRoutesStayUnderPrefix()).toBe(true);
  });

  it("documents the static output and privacy boundary", () => {
    expect(staticPolicy.outputDir).toBe("../skills/local-web/web");
    expect(staticPolicy.exposesStates).toBe(false);
    expect(staticPolicy.startsBackgroundJobs).toBe(false);
  });

  it("renders loading, empty and status areas", () => {
    const html = renderToStaticMarkup(<App />);
    expect(html).toContain("TrainLab Local");
    expect(html).toContain("本地训练数据与 AI 总结");
    expect(html).toContain("加载中");
  });

  it("renders empty and error states", () => {
    const empty = renderToStaticMarkup(
      <DashboardView
        state={baseState}
        queryDraft=""
        onQueryDraftChange={() => undefined}
        onSelectActivity={() => undefined}
      />,
    );
    expect(empty).toContain("没有匹配活动");
    expect(empty).toContain("暂无周总结");

    const error = renderToStaticMarkup(
      <DashboardView
        state={{ ...baseState, error: "DATABASE_UNAVAILABLE: database is unavailable" }}
        queryDraft=""
        onQueryDraftChange={() => undefined}
        onSelectActivity={() => undefined}
      />,
    );
    expect(error).toContain("DATABASE_UNAVAILABLE");
  });

  it("renders selected report text as escaped text", () => {
    const malicious = "<img src=x onerror=alert(1)>安全文本";
    const html = renderToStaticMarkup(
      <DashboardView
        state={{
          ...baseState,
          activities: [
            {
              activity_id: "a".repeat(64),
              fit_path: "states/activities/a.fit",
              sport: "running",
              sub_sport: null,
              start_time_utc: "2030-01-02T00:00:00.000000Z",
              end_time_utc: null,
              parsed_at_utc: "2030-01-02T01:00:00.000000Z",
              record_count: 1,
              has_activity_report: true,
              report_summary: malicious,
              fit_summary: {},
            },
          ],
          selectedActivityId: "a".repeat(64),
          weeklyReports: [{ id: 1, run_time_utc: "2030-01-08T00:00:00.000000Z", summary: malicious }],
        }}
        queryDraft="run"
        onQueryDraftChange={() => undefined}
        onSelectActivity={() => undefined}
      />,
    );
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;安全文本");
    expect(html).not.toContain("<img src=x");
  });
});
