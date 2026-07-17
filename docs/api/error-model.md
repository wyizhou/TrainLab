# API 错误模型

API 错误统一返回：

```json
{
  "code": "invalid_credentials",
  "message": "账号或密码错误",
  "details": null,
  "requestId": "c47e3c9d-25de-4d36-9c13-80241ad498d4"
}
```

- `code`：稳定、可供程序判断的机器码。
- `message`：可显示给用户的简短信息，不包含内部异常或敏感数据。
- `details`：可选的结构化校验详情。
- `requestId`：用于从日志关联一次请求，同时通过 `X-Request-ID` 响应头返回。

常见状态码：`401` 未登录或凭据错误，`403` Origin/CSRF 校验失败，`404` 资源或端点不存在，`409` 导入正在处理或状态冲突，`410` 私有原文件已不可用，`413` 文件超限，`415` 不是受支持的 FIT，`422` 请求无效或 FIT 已保存但解析失败，`500` 导入登记/持久化/状态保存等内部失败，`503` 数据库或私有文件存储暂不可用。

FIT 导入的稳定错误码包括：`fit_format_required`、`fit_content_type_invalid`、`fit_file_empty`、`fit_file_too_large`、`fit_import_failed`、`fit_import_unavailable`、`fit_parse_failed`、`fit_persistence_failed`、`import_in_progress`、`import_not_retryable`、`import_registration_failed`、`import_state_invalid`、`import_state_persistence_failed`、`import_state_unavailable`、`invalid_cursor`、`private_storage_unavailable` 和 `raw_file_unavailable`。失败详情只返回导入 ID、状态和安全错误码，不返回原文件内容、GPS、设备序列号、存储绝对路径或底层异常；底层数据库、文件系统和解析异常也不会作为异常链进入请求日志。

登录失败始终使用相同的 `401 invalid_credentials`，不通过响应暴露账号是否存在或当前失败计数。跨用户读取 FIT、活动或原文件统一返回 `404`，不区分“存在但不属于当前用户”。
