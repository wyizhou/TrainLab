import type { ApiEnvelope } from "./contracts";

export type Region = "com" | "cn";
export interface AuthStatus {
  stored: {
    state: string; saved: boolean | null; region: Region | null;
    expires_at_utc: string | null; refresh_due_at_utc: string | null;
    observed_at_utc: string | null; stale: boolean; server_verified: false;
    reason: string | null;
  };
  login: { state: string; attempt_id?: string; expires_at_utc?: string; region?: Region; reason?: string; operation_in_progress?: boolean };
  maintenance: { enabled: boolean; state: string; last_attempt_at_utc: string | null;
    last_refreshed_at_utc: string | null; next_check_at_utc: string | null;
    failures: number; reason: string | null; result: string | null };
}
export interface AuthSession { csrf: string; idle_timeout_seconds: number; session_replaced: boolean }

export class AuthError extends Error {
  constructor(public reason: string) { super(authMessage(reason)); }
}
export function authMessage(reason: string): string {
  const messages: Record<string, string> = {
    browser_session_expired: "服务重启或会话已失效，未完成验证请重新开始。",
    operation_in_progress: "认证操作中，请等结束后查看状态，不要重复提交。",
    auth_lock_busy: "认证操作中，其他进程持有锁；本次未执行，请稍后重试。",
    login_required: "尚无本地认证，请选择区域并登录。",
    legacy_auth_requires_login: "旧认证需要本人重新登录。",
    login_pending: "已有待完成验证，请先取消或完成。",
    server_rate_limited: "服务限流，请稍后重试。",
    server_auth_required: "服务要求重新登录，未确认密码或验证码是否正确。",
    authentication_incomplete: "认证未完成，请重新开始登录。",
    mfa_verification_incomplete: "验证码验证未完成，请重新开始登录。",
    mfa_expired: "验证码流程已过期，请重新开始登录。",
    sdk_timeout: "认证请求超时，先查看状态；不要自动重发。",
    auth_generation_changed: "认证已由其他操作更新，旧验证失效，请重新开始。",
    auth_storage_failed: "认证保存失败，未确认成功，请稍后重试。",
    request_not_allowed: "安全检查拒绝请求，请使用本机规范页面。",
    invalid_body: "输入无效，请检查区域、账号、密码或验证码。",
    network_failed: "网络请求未确认完成，请查看状态；不会自动重发秘密。",
  };
  return messages[reason] ?? "认证操作未完成，请检查状态后重新开始。";
}

export async function authRequest<T>(path: string, csrf?: string, body?: Record<string, string>): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/garmin/auth/${path}`, {
      method: body ? "POST" : "GET", credentials: "same-origin", cache: "no-store",
      headers: body ? { "Content-Type": "application/json", "X-CSRF-Token": csrf ?? "" } : { "X-TrainLab-GUI": "1" },
      body: body ? JSON.stringify(body) : undefined,
    });
    const envelope = await response.json() as ApiEnvelope<T>;
    if (!envelope.ok) throw new AuthError(String(envelope.error.details.reason ?? "request_failed"));
    return envelope.data;
  } catch (error) {
    if (error instanceof AuthError) throw error;
    throw new AuthError("network_failed");
  }
}
