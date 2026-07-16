# API v1 契约

TrainLab 的真实后端接口统一使用 `/api/v1` 前缀。当前基础版本只开放登录会话；未列出的业务能力仍由前端模拟，不应假定已有后端接口。

## 端点

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| `GET` | `/healthz` | 进程存活检查 | 否 |
| `GET` | `/readyz` | 数据库就绪检查 | 否 |
| `POST` | `/api/v1/auth/login` | 登录并设置会话及 CSRF Cookie | 否 |
| `GET` | `/api/v1/auth/session` | 恢复当前登录状态 | 会话 Cookie |
| `POST` | `/api/v1/auth/logout` | 撤销当前会话 | 会话 Cookie、Origin、CSRF |
| `GET` | `/api/v1/openapi.json` | 机器可读 OpenAPI | 否 |

登录请求：

```json
{ "username": "owner-user", "password": "correct-password" }
```

登录和会话响应：

```json
{
  "user": {
    "id": "00000000-0000-0000-0000-000000000000",
    "username": "owner-user",
    "displayName": "Owner",
    "isOwner": true
  },
  "expiresAt": "2026-08-15T00:00:00Z"
}
```

浏览器应使用同源请求并携带 Cookie。修改状态的认证请求还必须把 `trainlab_csrf` Cookie 的值放入 `X-CSRF-Token` 请求头。当前不启用跨域 CORS。

版本与兼容策略：破坏性变更使用新的主版本前缀；同一 `/api/v1` 内只增加向后兼容字段或端点。字段废弃必须先记录并保留迁移窗口。

统一错误格式见 [error-model.md](error-model.md)。
