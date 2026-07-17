# API v1 契约

TrainLab 的真实后端接口统一使用 `/api/v1` 前缀。当前开放登录会话和用户归属的本地 FIT 导入闭环；佳明在线同步、TCX/GPX、AI 等未列出的能力仍未接入真实后端。

## 端点

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| `GET` | `/healthz` | 进程存活检查 | 否 |
| `GET` | `/readyz` | 数据库就绪检查 | 否 |
| `POST` | `/api/v1/auth/login` | 登录并设置会话及 CSRF Cookie | 否 |
| `GET` | `/api/v1/auth/session` | 恢复当前登录状态 | 会话 Cookie |
| `POST` | `/api/v1/auth/logout` | 撤销当前会话 | 会话 Cookie、Origin、CSRF |
| `POST` | `/api/v1/imports/fit` | 上传、校验并解析当前用户的 FIT | 会话 Cookie、Origin、CSRF |
| `POST` | `/api/v1/imports/{importId}/retry` | 重试失败、部分或陈旧处理中导入 | 会话 Cookie、Origin、CSRF |
| `GET` | `/api/v1/activities` | 稳定游标分页列出当前用户活动 | 会话 Cookie |
| `GET` | `/api/v1/activities/{activityId}` | 读取当前用户活动及通用详情数据 | 会话 Cookie |
| `GET` | `/api/v1/activities/{activityId}/source` | 下载当前用户私有 FIT 原文件 | 会话 Cookie |
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

FIT 上传成功只返回 `complete` 或 `partial`，且 `activity` 必定存在。同一用户上传相同 SHA-256 的已完成文件返回 `200` 幂等结果；`pending` 或陈旧 `processing` 由同文件重传安全接管，只有新鲜 `processing` 返回 `409 import_in_progress`；失败记录返回可重试的 `422 fit_import_failed`。活动详情会保留圈、采样、训练组/攀岩分段、设备快照合并结果和未知扩展指标；无法证明的设备—指标关系保持 `null`。

列表游标为不透明字符串，调用方不得解析或构造；时间排序使用 UTC 开始时间与 UUID 稳定排序，显示日期优先使用 FIT 明确记录的本地时间。跨用户访问按资源不存在处理，返回 `404`，避免泄露对象是否存在。

版本与兼容策略：破坏性变更使用新的主版本前缀；同一 `/api/v1` 内只增加向后兼容字段或端点。字段废弃必须先记录并保留迁移窗口。

统一错误格式见 [error-model.md](error-model.md)。
