# 本地 FIT 单工具服务

M12 内部 MCP stdio 桥，仅把[已验证细读接口](fit-detail.md)连接给模型客户端。
它不是同步、周报、守护进程或正式运行命令；未启用任何模型、网络监听端口或全局 MCP 配置。

## Host 与模型分别能做什么

Host 启动子进程时设置实例根、周截止时间和冻结 scope SHA。这些参数不属于工具输入，
服务的工具说明和调用结果不输出实例位置。相对根目录根据 Host 指定的子进程工作目录解析，不写死本机路径。
启动后不能通过工具请求切换实例、周范围或预算。

服务仅暴露 `read_fit_detail`，五个参数为：

| 参数 | 范围 |
| --- | --- |
| activity_ref | 已冻结的本周活动引用 |
| view | summary、laps、series |
| start_offset_seconds | 从活动开始算起的整数秒 |
| end_offset_seconds | 大于开始时间；单次最多 1200 秒，不超出活动 |
| resolution_seconds | 1 或 5；细粒度输出仍是时间加权统计 |

可返回已授权运动 GPS，但没有原 FIT 字节、任意文件、SQL、命令、资源、提示词或远端 Provider 工具。
新版工具说明明确定位只是真实窗口端点，不是完整路线；工具摘要随说明更新，旧证明不授权新启动。
工具元数据的 `openWorldHint=false`、`destructiveHint=false`、`idempotentHint=true`；
`readOnlyHint=false` 如实反映内部会追加预算/结果日志，不表示允许修改训练或外部数据。

每周 20 个不同请求、精确缓存及失败/重启恢复都由原 DetailHost 和新 SQLite 执行，
服务不另建一套额度，不因子进程重启而重置。成功内容同时放入一致的规范 JSON 文本和
MCP structuredContent；已缓存的解析失败保持失败。

## 错误与输出边界

SDK 默认的 Schema 错误可能回显参数，因此调用端关闭默认回显式检查，转交同一个
确定性 Host 请求校验器，保留固定错误码。`fit_detail_request_v1` 用于工具发现，
跨字段时间范围和活动归属仍由 Host 检查，并有 Schema/Host 一致性回归。

发送结果前再次校验完整输出 Schema、请求字段、scope 和请求 SHA。
未知工具不触发 Host；无效请求不占预算；异常只返回固定、无路径的错误信封。
启动失败时不进入 MCP 会话，仅输出 `fit_detail_server_unavailable` 并退出。

## 适用证明

`test_m12_detail_server.py` 使用实际 SDK ClientSession、stdio 子进程和合成 FIT/新库，
验证发现、三种视图、参数拒绝、未知工具、预算重启、成功/失败重放、私有输出拒绝和启动前检。
测试不会启动 Codex，也不使用用户 Token 或正式 FIT。

这只证明本服务的接口边界，**不证明 Codex 没有其他内置工具**。后续 AI Adapter 还须独立
关闭其他能力、检查实际工具清单和模型输入隔离；不得仅凭只读沙箱或本服务 PASS 开放私人任务。
