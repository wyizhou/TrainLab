# 执行计划：Gmail 与 Garmin 认证健康检查

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`ADHOC-0005`
- 阶段/子项目：`不适用`
- Batch ID：`不适用`
- 返工来源：`无`
- 开始日期：2026-08-12
- 最后更新：2026-08-12

## 目标与验收标准

- 核验当前环境使用精确 Gmail MCP 绑定，并以不读取邮件正文的最小只读查询验证认证。
- 以 Garmin MCP 的个人资料与用户设置只读接口验证现有 cached token。
- 不发送邮件、不修改标签、不同步活动、不刷新或写入 token、不读取健康数据。
- 任一认证失败时立即停止，并向用户提供对应的重新认证指引。

## 范围与非目标

- 允许写入：本执行计划与 `memory.md` 活动指针。
- 禁止写入：生产 state/config/logs、凭据、邮箱、Garmin Provider 数据、Git、远端资源。
- 不执行 Garmin 同步、分析、邮件投递或凭据刷新。

## 适用规则与参考资料

- 已批准规则：A-001、A-002、A-003、A-004。
- 产品合同：`harness/shared/HARNESS.md`、`harness/mail/HARNESS.md`；本任务是运维认证探针，
  不调用 Mail Agent 模型路由。

## 依赖与隔离

- 显式依赖：当前 MCP 环境、现有本地认证状态。
- 共享接口和冻结依据：精确 `gmail` MCP、Garmin MCP 只读资料接口。
- 任务分支、Worktree、集成分支：不适用——只读检查。
- 允许/禁止写入范围：见上。

## 功能与测试映射

`不适用——只读运维检查`

## 工具采用情况

- Gmail：最小不命中 search 认证探针。
- Garmin：`get_full_name` 与 `get_userprofile_settings` 只读探针。
- 不运行产品测试或 linter；仅核验返回状态和零副作用。

## Subagent 派发

不适用——用户未要求并行或委派；任务严格串行。

## 工作分解

| 步骤 | 状态 | 证据 |
| --- | --- | --- |
| 核验精确 Gmail MCP 绑定 | `done` | `gmail` 指向 `@artymclabin/gmail-mcp` |
| Gmail 最小只读认证探针 | `done` | 不命中查询成功，认证有效 |
| Garmin 个人资料与设置探针 | `done` | MCP 默认凭证有效；项目 cached-only 副本需刷新 |
| 汇总结果并归档计划 | `done` | 已向用户提供无密码优先恢复方案 |

## 当前检查点

- 当前 Loop：完成归档。
- 最近完成：Gmail 和 Garmin MCP 认证通过；项目 Garmin token cached-only 检查失败关闭。
- 当前焦点：无。
- 下一动作：等待用户是否授权把已验证的 MCP 默认 token 同步到项目。
- 阻塞项：项目 token 恢复属于凭据写入，需要用户明确授权。
- 已变更文件：本计划、memory 活动指针。
- 待验证项：无。

## 决策与发现

- Gmail 认证不读取真实邮件，使用确定不会匹配的随机标记查询。
- Garmin 只读取账户资料元数据，不请求日期窗口或健康资源，因此不触发 A-001 同步预算。
- Gmail 精确绑定认证有效；未读取邮件正文或改变邮箱。
- Garmin MCP 默认路径认证有效；个人资料和设置读取成功。
- 项目 token 与默认 token 不同，cached-only 探针在 Provider entry=0 时以
  `cached_token_refresh_forbidden` 失败关闭，执行前后摘要一致。

## 任务级独立验证

- 结果：`不适用——只读状态检查`

## 集成级独立验证

- 结果：`不适用——无并行集成`

## PLANS 回写清单

非 Roadmap 任务，Roadmap 回写不适用；完成后归档计划并清除 memory 指针。

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-12 / Loop 1 | Git/规则/Harness 预检完成 | 只读检查无需触发产品 Mail Agent | 执行认证探针 |
| 2026-08-12 / Loop 2 | Gmail 与 Garmin MCP 通过；项目 Garmin token 失败关闭 | 推荐同步已验证默认 token，避免密码/MFA | 等待用户授权凭据写入 |
