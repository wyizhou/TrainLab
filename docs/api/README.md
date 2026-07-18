# API v1 契约

TrainLab 的真实后端接口统一使用 `/api/v1` 前缀。当前开放登录会话、用户归属的本地 FIT 导入和数据生命周期闭环；佳明在线同步、TCX/GPX、AI 等未列出的能力仍未接入真实后端。

当前后端组件和 OpenAPI 版本为 `0.3.1`；产品发布版本独立为 `v0.1.1`，两者不互相替代。

## 端点

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| `GET` | `/healthz` | 进程存活检查 | 否 |
| `GET` | `/readyz` | 数据库就绪检查 | 否 |
| `POST` | `/api/v1/auth/login` | 登录并设置会话及 CSRF Cookie | 否 |
| `GET` | `/api/v1/auth/session` | 恢复当前登录状态 | 会话 Cookie |
| `POST` | `/api/v1/auth/logout` | 撤销当前会话 | 会话 Cookie、Origin、CSRF |
| `POST` | `/api/v1/imports/fit` | 上传、校验并解析当前用户的 FIT | 会话 Cookie、Origin、CSRF |
| `GET` | `/api/v1/imports` | 稳定游标分页列出当前用户导入记录 | 会话 Cookie |
| `DELETE` | `/api/v1/imports/{importId}` | 幂等删除当前用户导入及原文件 | 会话 Cookie、Origin、CSRF |
| `POST` | `/api/v1/imports/{importId}/retry` | 重试失败、部分或陈旧处理中导入 | 会话 Cookie、Origin、CSRF |
| `GET` | `/api/v1/activities` | 稳定游标分页列出当前用户活动 | 会话 Cookie |
| `GET` | `/api/v1/activities/{activityId}` | 读取当前用户活动及通用详情数据 | 会话 Cookie |
| `PATCH` | `/api/v1/activities/{activityId}` | 设置或清除当前用户的活动显示名 | 会话 Cookie、Origin、CSRF |
| `DELETE` | `/api/v1/activities/{activityId}` | 幂等删除活动对应导入及原文件 | 会话 Cookie、Origin、CSRF |
| `GET` | `/api/v1/activities/{activityId}/source` | 下载当前用户私有 FIT 原文件 | 会话 Cookie |
| `GET` | `/api/v1/storage/usage` | 查看当前用户已登记用量和配额 | 会话 Cookie |
| `GET` | `/api/v1/openapi.json` | 机器可读 OpenAPI | 否 |

登录请求：

```json
{ "username": "useradmin", "password": "useradmin" }
```

登录和会话响应：

```json
{
  "user": {
    "id": "00000000-0000-0000-0000-000000000000",
    "username": "useradmin",
    "displayName": "useradmin",
    "isOwner": true
  },
  "expiresAt": "2026-08-15T00:00:00Z"
}
```

浏览器应使用同源请求并携带 Cookie。修改状态的认证请求还必须把 `trainlab_csrf` Cookie 的值放入 `X-CSRF-Token` 请求头。当前不启用跨域 CORS。

FIT 上传成功只返回 `complete` 或 `partial`，且 `activity` 必定存在。同一用户上传相同 SHA-256 的已完成文件返回 `200` 幂等结果；`pending` 或陈旧 `processing` 由同文件重传安全接管，只有新鲜 `processing` 返回 `409 import_in_progress`；失败记录返回可重试的 `422 fit_import_failed`。活动详情会保留圈、采样、训练组/攀岩分段、设备快照合并结果和未知扩展指标；无法证明的设备—指标关系保持 `null`。

每个训练组/攀岩段在原 `extraData` 外提供可选的版本化 `semantic` 投影。版本 1 的 `sourceMessage` 只允许 `set`、`split` 或 `split_summary`；力量动作可提供已清洗的 `exercise.stepIndex/name`，攀岩 active 段提供 `climb.gradeStatus`。只有 `gradeStatus=available` 且有已证明的 `gradeSystem/grade` 时客户端才显示等级；当前 Garmin profile 未定义的 split 字段 69–73 保留在原始数据中，API 明确返回 `unavailable/unknown_profile_field`，客户端不得显示数字键或猜测等级。

已完成导入的批量重解析只通过本机管理员 CLI `trainlab reparse-fit` 提供，默认 dry-run，不新增 HTTP 端点。整批在一个数据库事务中就地替换投影并保留资源 UUID、归属、标题覆盖和原文件；详见 `docs/runbooks/local-development.md`。

用户配额默认 5 GiB、10,000 个文件。超过任一上限返回 `409 storage_quota_exceeded`，`details` 只包含当前用量和上限；重复上传不增加用量。活动名称覆盖与解析标题分别保存，`PATCH` 的 `name: null` 会恢复解析标题。两个 DELETE 均对不存在或跨用户对象返回 `204`，避免泄露对象是否存在；新鲜解析中的导入返回 `409 import_in_progress`，文件或数据库中途失败可以重复 DELETE 恢复。

列表游标为不透明字符串，调用方不得解析或构造；时间排序使用 UTC 开始时间与 UUID 稳定排序，显示日期优先使用 FIT 明确记录的本地时间。跨用户访问按资源不存在处理，返回 `404`，避免泄露对象是否存在。

版本与兼容策略：破坏性变更使用新的主版本前缀；同一 `/api/v1` 内只增加向后兼容字段或端点。字段废弃必须先记录并保留迁移窗口。

统一错误格式见 [error-model.md](error-model.md)。
