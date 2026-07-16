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

常见状态码：`401` 未登录或凭据错误，`403` Origin/CSRF 校验失败，`404` 资源或端点不存在，`422` 请求结构无效，`500` 未处理的服务错误，`503` 数据库未就绪。登录失败始终使用相同的 `401 invalid_credentials`，不通过响应暴露账号是否存在或当前失败计数。
