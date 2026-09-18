export const apiRoutes = [
  "/api/garmin/auth/session",
  "/api/garmin/auth/status",
  "/api/garmin/auth/login",
  "/api/garmin/auth/mfa",
  "/api/garmin/auth/cancel",
  "/api/garmin/auth/maintenance/retry",
  "/api/health",
  "/api/status",
  "/api/sync/status",
  "/api/activities",
  "/api/activities/{activity_id}",
  "/api/reports/activity/{activity_id}",
  "/api/reports/activity/{activity_id}/generate",
  "/api/reports/weekly",
  "/api/reports/weekly/{report_id}",
  "/api/reports/weekly/generate",
] as const;

const postRoutes: readonly string[] = [
  "/api/garmin/auth/login", "/api/garmin/auth/mfa", "/api/garmin/auth/cancel",
  "/api/garmin/auth/maintenance/retry", "/api/reports/activity/{activity_id}/generate",
  "/api/reports/weekly/generate",
];
export const apiRouteContracts = apiRoutes.map((path) => ({ path, method: postRoutes.includes(path) ? "POST" : "GET" }));

export const staticPolicy = {
  outputDir: "../skills/local-web/web",
  exposesStates: false,
  startsBackgroundJobsOnCreate: false,
  backgroundJobsOnLifespan: ["garmin_auth_maintenance"],
} as const;

export type ApiEnvelope<T> =
  | { ok: true; data: T; error: null }
  | { ok: false; data: null; error: { code: string; message: string; details: Record<string, unknown> } };

export interface StatusData {
  service: string;
  local_only: boolean;
  available_routes?: string[];
  database: { relative_path: string; exists: boolean };
  sync?: SyncState;
  ai_generation_configured: boolean;
}

export interface SyncState {
  last_attempt_at_utc: string | null;
  last_success_at_utc: string | null;
  due: boolean;
  interval_seconds: number;
  synced: Record<string, unknown>;
}

export interface ActivitySummary {
  activity_id: string;
  fit_path: string;
  sport: string | null;
  sub_sport: string | null;
  start_time_utc: string | null;
  end_time_utc: string | null;
  parsed_at_utc: string;
  record_count: number;
  has_activity_report: boolean;
  report_summary: string | null;
  fit_summary: Record<string, unknown>;
}

export interface ActivityListData {
  items: ActivitySummary[];
  total: number;
  limit: number;
  offset: number;
  empty: boolean;
}

export interface WeeklyReport {
  id: number;
  run_time_utc: string;
  summary: string;
}

export interface WeeklyListData {
  items: WeeklyReport[];
  total: number;
  limit: number;
  offset: number;
  empty: boolean;
}

export interface DashboardState {
  loading: boolean;
  error: string | null;
  status: StatusData | null;
  activities: ActivitySummary[];
  selectedActivityId: string | null;
  weeklyReports: WeeklyReport[];
  query: string;
}

export function allApiRoutesStayUnderPrefix(routes: readonly string[] = apiRoutes): boolean {
  return routes.length > 0 && routes.every((route) => route.startsWith("/api/"));
}
