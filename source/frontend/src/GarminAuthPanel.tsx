import { useEffect, useRef, useState } from "react";
import { AuthError, authMessage, authRequest } from "./garminAuth";
import type { AuthSession, AuthStatus, Region } from "./garminAuth";

const maintenanceLabels: Record<string, string> = {
  starting: "尚未检查", scheduled: "已安排期限检查", running: "正在维护",
  retry_wait: "临时失败，等待有限重试", paused: "维护已暂停", manual_required: "需要本人登录",
  blocked: "维护受阻", stopping: "正在停服",
};
const loginLabels: Record<string, string> = {
  idle: "可开始登录", submitting: "正在登录", verifying: "正在验证", needs_mfa: "等待验证码",
  cancelled: "已取消验证", expired: "验证已过期", failed: "认证未完成", completed: "认证已安全保存",
  busy_elsewhere: "其他浏览器正在认证",
};

export function GarminAuthPanel(): React.ReactElement {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [region, setRegion] = useState<Region | "">("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const session = useRef<AuthSession | null>(null);
  const requestBusy = useRef(false);
  const version = useRef(0);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll(): Promise<void> {
      if (requestBusy.current) { timer = setTimeout(() => void poll(), 500); return; }
      const sequence = version.current;
      try {
        if (!session.current) {
          const next = await authRequest<AuthSession>("session");
          if (!active) return;
          session.current = next;
          if (next.session_replaced) setMessage(authMessage("browser_session_expired"));
          setReady(true);
        }
        const next = await authRequest<AuthStatus>("status");
        if (active && sequence === version.current) setStatus(next);
      } catch (error) {
        if (active && sequence === version.current) {
          setMessage(error instanceof AuthError ? error.message : authMessage("network_failed"));
          if (error instanceof AuthError && error.reason === "browser_session_expired") {
            session.current = null; setReady(false); setStatus(null);
          }
        }
      } finally {
        if (active) timer = setTimeout(() => void poll(), 1000);
      }
    }
    void poll();
    return () => { active = false; clearTimeout(timer); version.current++; };
  }, []);

  async function submit(action: string, body: Record<string, string>): Promise<void> {
    if (requestBusy.current || !session.current) return;
    requestBusy.current = true;
    const sequence = ++version.current;
    setBusy(true); setMessage("");
    setUsername(""); setPassword(""); setCode("");
    try {
      const next = await authRequest<AuthStatus>(action, session.current.csrf, body);
      if (sequence === version.current) setStatus(next);
    } catch (error) {
      if (sequence === version.current) {
        setMessage(error instanceof AuthError ? error.message : authMessage("network_failed"));
        if (error instanceof AuthError && error.reason === "browser_session_expired") {
          session.current = null; setReady(false); setStatus(null);
        }
      }
    } finally {
      for (const key of Object.keys(body)) delete body[key];
      requestBusy.current = false;
      if (sequence === version.current) setBusy(false);
    }
  }
  const waiting = status?.login.state === "needs_mfa";
  const disabled = busy || !ready || status?.login.operation_in_progress || ["submitting", "verifying", "busy_elsewhere"].includes(status?.login.state ?? "");
  return (
    <section className="auth-panel" aria-label="Garmin 登录与认证维护">
      <h2>Garmin 登录与认证维护</h2>
      <p>在此选择账户区域并本人验证。独立于数据库和 AI；不会自动重发密码或验证码。</p>
      <p role="status">{busy ? "认证操作中，结束后可取消或重来" : loginLabels[status?.login.state ?? ""] ?? "正在建立安全会话"}</p>
      {message && <p role="alert">{message}</p>}
      {status?.login.reason && <p>{authMessage(status.login.reason)}</p>}
      {waiting ? (
        <form onSubmit={(event) => { event.preventDefault(); void submit("mfa", { attempt_id: status.login.attempt_id!, code }); }}>
          <p>验证区域：{status.login.region === "cn" ? "中国区 (cn)" : "国际区 (com)"}；截止：{status.login.expires_at_utc}。刷新页面不延长期限。</p>
          <label>验证码<input type="password" autoComplete="off" maxLength={128} value={code} onChange={(event) => setCode(event.target.value)} required disabled={disabled} /></label>
          <button type="submit" disabled={disabled || !code.trim()}>提交验证码</button>
          <button type="button" disabled={disabled} onClick={() => void submit("cancel", { attempt_id: status.login.attempt_id! })}>取消验证</button>
        </form>
      ) : (
        <form onSubmit={(event) => { event.preventDefault(); void submit("login", { region, username, password }); }}>
          <label>账户区域<select value={region} required disabled={disabled} onChange={(event) => setRegion(event.target.value as Region | "")}>
            <option value="">请选择区域</option><option value="com">国际区 (com)</option><option value="cn">中国区 (cn)</option>
          </select></label>
          <label>账号<input type="password" autoComplete="off" maxLength={320} value={username} onChange={(event) => setUsername(event.target.value)} required disabled={disabled} /></label>
          <label>密码<input type="password" autoComplete="off" maxLength={1024} value={password} onChange={(event) => setPassword(event.target.value)} required disabled={disabled} /></label>
          <button type="submit" disabled={disabled || !region || !username.trim() || !password}>登录并保存</button>
        </form>
      )}
      <dl aria-label="认证保存状态">
        <dt>本地认证</dt><dd>{status?.stored.saved === true ? "已保存" : status?.stored.saved === false ? "未保存" : "尚未确认"}{status?.stored.stale ? "（缓存，操作中）" : ""}</dd>
        <dt>已保存区域</dt><dd>{status?.stored.region ?? "未知"}</dd>
        <dt>访问令牌期限（UTC）</dt><dd>{status?.stored.expires_at_utc ?? "未知"}</dd>
        <dt>建议维护时间（UTC）</dt><dd>{status?.stored.refresh_due_at_utc ?? "未知"}</dd>
        <dt>在线核验</dt><dd>未做本次在线核验（server_verified=false）；本地保存不代表服务器当前接受。</dd>
        <dt>维护状态</dt><dd data-testid="maintenance-state">{maintenanceLabels[status?.maintenance.state ?? ""] ?? "尚未检查"}</dd>
        <dt>上次真正刷新成功（UTC）</dt><dd data-testid="last-refreshed">{status?.maintenance.last_refreshed_at_utc ?? "本次服务尚无刷新成功记录"}</dd>
        <dt>下次检查（UTC）</dt><dd>{status?.maintenance.next_check_at_utc ?? "尚未安排"}</dd>
      </dl>
      {status?.maintenance.reason && <p>{authMessage(status.maintenance.reason)}</p>}
      <button disabled={disabled || status?.maintenance.state !== "paused"} onClick={() => void submit("maintenance/retry", {})}>重试维护</button>
      <p>仅 Web 运行时维护认证；停服、休眠或断网不保证刷新。不启动 AI 或活动同步后台任务。</p>
    </section>
  );
}
