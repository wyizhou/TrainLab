import { useEffect, useMemo, useState } from "react";
import type { ActivityListData, ActivitySummary, ApiEnvelope, DashboardState, StatusData, WeeklyListData } from "./contracts";
import { apiRoutes, staticPolicy } from "./contracts";

const initialDashboardState: DashboardState = {
  loading: true,
  error: null,
  status: null,
  activities: [],
  selectedActivityId: null,
  weeklyReports: [],
  query: "",
};

async function readEnvelope<T>(response: Response): Promise<T> {
  const envelope = (await response.json()) as ApiEnvelope<T>;
  if (!envelope.ok) {
    throw new Error(`${envelope.error.code}: ${envelope.error.message}`);
  }
  return envelope.data;
}

async function fetchDashboard(query: string): Promise<Omit<DashboardState, "loading" | "query">> {
  const params = new URLSearchParams({ limit: "20", offset: "0" });
  if (query.trim() !== "") {
    params.set("q", query.trim());
  }
  const [statusResponse, activitiesResponse, weeklyResponse] = await Promise.all([
    fetch("/api/status"),
    fetch(`/api/activities?${params.toString()}`),
    fetch("/api/reports/weekly?limit=5&offset=0"),
  ]);
  const [status, activities, weekly] = await Promise.all([
    readEnvelope<StatusData>(statusResponse),
    readEnvelope<ActivityListData>(activitiesResponse),
    readEnvelope<WeeklyListData>(weeklyResponse),
  ]);
  return {
    error: null,
    status,
    activities: activities.items,
    selectedActivityId: activities.items[0]?.activity_id ?? null,
    weeklyReports: weekly.items,
  };
}

export function App(): React.ReactElement {
  const [state, setState] = useState<DashboardState>(initialDashboardState);
  const [queryDraft, setQueryDraft] = useState("");

  useEffect(() => {
    let cancelled = false;
    setState((current) => ({ ...current, loading: true, error: null, query: queryDraft }));
    fetchDashboard(queryDraft)
      .then((next) => {
        if (!cancelled) {
          setState({ ...next, loading: false, query: queryDraft });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState((current) => ({
            ...current,
            loading: false,
            error: error instanceof Error ? error.message : "加载失败",
            activities: [],
            selectedActivityId: null,
          }));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [queryDraft]);

  return (
    <DashboardView
      state={state}
      queryDraft={queryDraft}
      onQueryDraftChange={setQueryDraft}
      onSelectActivity={(activityId) => setState((current) => ({ ...current, selectedActivityId: activityId }))}
    />
  );
}

interface DashboardViewProps {
  state: DashboardState;
  queryDraft: string;
  onQueryDraftChange: (value: string) => void;
  onSelectActivity: (activityId: string) => void;
}

export function DashboardView({
  state,
  queryDraft,
  onQueryDraftChange,
  onSelectActivity,
}: DashboardViewProps): React.ReactElement {
  const selected = useMemo(
    () => state.activities.find((activity) => activity.activity_id === state.selectedActivityId) ?? null,
    [state.activities, state.selectedActivityId],
  );

  return (
    <main className="shell">
      <section className="hero">
        <p className="eyebrow">TrainLab Local</p>
        <h1>本地训练数据与 AI 总结</h1>
        <p>仅连接本机 /api；前端不包含密钥，不读取 states、FIT 原件或数据库文件。</p>
      </section>

      <section className="status-grid" aria-label="状态">
        <InfoCard title="同步状态">
          {state.status?.sync ? (
            <dl>
              <dt>上次尝试</dt>
              <dd>{state.status.sync.last_attempt_at_utc ?? "尚未同步"}</dd>
              <dt>上次成功</dt>
              <dd>{state.status.sync.last_success_at_utc ?? "尚未成功"}</dd>
              <dt>是否到期</dt>
              <dd>{state.status.sync.due ? "是" : "否"}</dd>
            </dl>
          ) : (
            <p>正在读取同步状态…</p>
          )}
        </InfoCard>
        <InfoCard title="本地服务">
          <ul>
            <li>API 路由：{apiRoutes.length}</li>
            <li>数据库：{state.status?.database.exists ? "已找到" : "未找到或未加载"}</li>
            <li>AI 生成：{state.status?.ai_generation_configured ? "已显式配置" : "未配置"}</li>
            <li>静态输出：{staticPolicy.outputDir}</li>
          </ul>
        </InfoCard>
      </section>

      <section className="panel" aria-label="活动搜索">
        <div className="panel-header">
          <div>
            <h2>活动搜索</h2>
            <p>按 activity id、路径、运动类型或子类型搜索；结果固定按开始时间倒序。</p>
          </div>
          <form
            role="search"
            onSubmit={(event) => {
              event.preventDefault();
              onQueryDraftChange(queryDraft);
            }}
          >
            <label htmlFor="activity-search">搜索</label>
            <input
              id="activity-search"
              value={queryDraft}
              onChange={(event) => onQueryDraftChange(event.currentTarget.value)}
              placeholder="running / activity id"
            />
          </form>
        </div>

        {state.loading ? <p className="state">加载中…</p> : null}
        {state.error ? <p className="state error">{state.error}</p> : null}
        {!state.loading && !state.error && state.activities.length === 0 ? (
          <p className="state">没有匹配活动。</p>
        ) : null}

        <div className="activity-layout">
          <ol className="activity-list">
            {state.activities.map((activity) => (
              <li key={activity.activity_id}>
                <button
                  type="button"
                  className={activity.activity_id === selected?.activity_id ? "selected" : ""}
                  onClick={() => onSelectActivity(activity.activity_id)}
                >
                  <span>{activity.sport ?? "unknown"}</span>
                  <strong>{activity.start_time_utc ?? "未知时间"}</strong>
                  <small>{activity.activity_id.slice(0, 12)}</small>
                </button>
              </li>
            ))}
          </ol>
          <ActivityDetail activity={selected} />
        </div>
      </section>

      <section className="panel" aria-label="周总结">
        <h2>周总结</h2>
        {state.weeklyReports.length === 0 ? (
          <p className="state">暂无周总结。</p>
        ) : (
          state.weeklyReports.map((report) => (
            <article key={report.id} className="report-block">
              <h3>{report.run_time_utc}</h3>
              <pre>{report.summary}</pre>
            </article>
          ))
        )}
      </section>
    </main>
  );
}

function ActivityDetail({ activity }: { activity: ActivitySummary | null }): React.ReactElement {
  if (activity === null) {
    return (
      <article className="detail-card">
        <h2>活动详情</h2>
        <p className="state">请选择一条活动。</p>
      </article>
    );
  }
  return (
    <article className="detail-card">
      <h2>活动详情</h2>
      <dl>
        <dt>Activity ID</dt>
        <dd>{activity.activity_id}</dd>
        <dt>运动类型</dt>
        <dd>{activity.sport ?? "unknown"}</dd>
        <dt>采样数量</dt>
        <dd>{activity.record_count}</dd>
        <dt>FIT 路径</dt>
        <dd>{activity.fit_path}</dd>
      </dl>
      <h3>活动报告</h3>
      {activity.report_summary ? <pre>{activity.report_summary}</pre> : <p className="state">暂无活动报告。</p>}
    </article>
  );
}

function InfoCard({ title, children }: { title: string; children: React.ReactNode }): React.ReactElement {
  return (
    <article className="info-card">
      <h2>{title}</h2>
      {children}
    </article>
  );
}
