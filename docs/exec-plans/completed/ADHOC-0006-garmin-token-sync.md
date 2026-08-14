# 执行计划：同步已验证的 Garmin token

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`ADHOC-0006`
- 阶段/子项目：`不适用`
- Batch ID：`不适用`
- 返工来源：`无`
- 开始日期：2026-08-12
- 最后更新：2026-08-12

## 目标与验收标准

- 将已通过 Garmin MCP 资料/设置探针的默认 token 同步到 TrainLab 项目凭证目录。
- 覆盖前保留权限受限、可恢复的项目旧 token 备份。
- 源 token 摘要保持不变，目标摘要与源一致；目录 0700、文件 0600、当前用户所有。
- 同步后以 cached-only 资料探针确认项目 token 可用，禁止刷新和凭证写入。

## 范围与非目标

- 允许写入：`state/secrets/garmin/garmin_tokens.json`、受限临时备份、本计划和 memory 指针。
- 禁止写入：其他凭据、生产数据库/raw/FIT、邮箱、Garmin 活动、分析、邮件、Git 或远端。
- 不使用密码/MFA，不执行 Garmin 同步，不刷新 token。

## 适用规则与参考资料

- 已批准规则：A-001、A-002、A-003、A-004。
- 用户授权：2026-08-12 “允许同步 Garmin token”。

## 依赖与隔离

- 显式依赖：ADHOC-0005 已确认 Gmail 有效、Garmin MCP 默认 token 有效、项目副本过期。
- 共享接口和冻结依据：`garminconnect` 默认 tokenstore 与 TrainLab `TokenStore`。
- 分支/Worktree/集成分支：不适用——本地运维凭据操作。
- 写入边界：仅上述目标与证据计划。

## 功能与测试映射

`不适用——本地运维凭据同步`

## 工具采用情况

- SHA-256、权限/属主检查、原子替换、TrainLab cached-only 登录探针。
- Provider 上限 6、墙钟 30 秒、活动/FIT/raw 上限均为 0。

## Subagent 派发

不适用——用户未要求委派，任务严格串行。

## 工作分解

| 步骤 | 状态 | 证据 |
| --- | --- | --- |
| 冻结源/目标元数据并备份旧 token | `done` | 旧项目 token 已保存至 0700/0600 临时备份 |
| 原子同步并校验权限/摘要 | `done` | 源未变、目标等于源、目录 0700/文件 0600/当前用户所有 |
| cached-only 资料探针 | `done` | 认证成功；2/6 Provider entries；token 摘要不变 |
| 归档计划并报告 | `done` | 无阻塞 |

## 当前检查点

- 当前 Loop：完成归档。
- 最近完成：项目 token 同步及 cached-only 验证成功。
- 当前焦点：无。
- 下一动作：无。
- 阻塞项：无。
- 已变更文件：项目 token、本计划、memory 活动指针。
- 待验证项：无。

## 决策与发现

- 不重新登录 Garmin；优先复用已经独立验证有效的默认 token。
- 不输出任何 token 内容或摘要值，只报告布尔验证结果。
- 旧项目 token 备份位于 `/tmp/trainlab-garmin-token-backup.4qUOG5`，目录 0700、文件 0600。
- cached-only 资料探针使用 2/6 Provider entries，活动/FIT/raw 均为 0，token 前后不变。

## 任务级独立验证

- 结果：`不适用——本地凭据运维操作`

## 集成级独立验证

- 结果：`不适用——无并行集成`

## PLANS 回写清单

非 Roadmap 任务；完成后归档计划并清除 memory 指针。

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-12 / Loop 1 | 用户授权同步 | 仅同步已验证默认 token | 备份、同步、验证 |
| 2026-08-12 / Loop 2 | 原子同步、权限/摘要与 cached-only 探针均通过 | 无阻塞 | 归档完成 |
