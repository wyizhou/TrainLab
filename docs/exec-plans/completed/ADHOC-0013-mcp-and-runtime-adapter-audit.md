# 执行计划：Garmin/Gmail MCP 与运行适配状态核对

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`ADHOC-0013`
- 阶段/子项目：`不适用`
- Batch ID：`read-only-audit`
- 返工来源：`无`
- 开始日期：2026-08-16
- 最后更新：2026-08-16

## 目标与验收标准

- 核对 `codex mcp list` 中 Garmin/Gmail 的配置、启用状态与当前会话可见工具。
- 用无副作用方式判断认证是否可用；不发送邮件、不写 Garmin、不刷新 token。
- 解释“已安装 MCP”与“项目 Skill 只是准备器”的区别。
- 核对用户删除 `source/state/backups` 与 `recovery-quarantine` 后的当前状态影响。

## 范围与非目标

- 范围：Codex MCP 配置、当前会话工具、两个运行 Skill、state 目录存在性和只读验证。
- 非目标：不修改产品代码或正式 state；不重建已删除目录；不调用任何写工具；不提交或推送。

## 适用规则与参考资料

- 已批准规则：A-001、A-002、A-004、A-008。
- 官方参考：OpenAI Docs 的 Codex MCP 配置说明。

## 依赖与隔离

- 显式依赖：ADHOC-0011、ADHOC-0012。
- 任务分支/Worktree/集成分支：`不适用——只读审计`
- 允许写入范围：本 exec plan 与 `memory.md` 活动指针。
- 禁止写入范围：`source/**`、`source/state/**`、`data-backup/**`、Git index、外部服务写入。

## 功能与测试映射

`不适用——只读任务`。

## 工具采用情况

- `codex mcp list/get`、当前会话工具清单、只读 MCP smoke、Git/文件系统检查。
- 不执行发送、删除、创建、同步、token refresh 或 MFA。

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | MCP/Skill 接线复核 | medium | medium | medium | 配置存在与项目调用链需分层核对 | supported | 只读 | 配置、工具、适配缺口 | PASS |

## 工作分解

| 步骤 | 状态 | 证据 |
| --- | --- | --- |
| 1. 核对 MCP 配置和当前工具 | `done` | Garmin/Gmail 均 enabled，当前会话工具可见 |
| 2. 只读认证 smoke | `done` | Garmin 单位制、Gmail 标签清单调用成功；未输出正文或账户值 |
| 3. 核对项目 Skill 调用链 | `done` | 仅 no-network 准备器，无 MCP 调用代码 |
| 4. 说明目录删除影响并交付 | `done` | 两目录不存在；当前无备份，恢复时会按需重建 |

## 当前检查点

- 当前 Loop：审计结束。
- 最近完成：配置、认证、当前会话工具和项目接线均已核对。
- 当前焦点：无。
- 下一动作：等待用户决定是否规划项目 adapter/runner。
- 阻塞项：当前 state verifier 因 `state/raw/.DS_Store` 报 `raw_unregistered_file`；与目录删除无关。
- 已变更文件：本计划、`memory.md` 状态事实；未修改 source/state。
- 待验证项：无。

## 决策与发现

- `garmin` 与 `gmail` 均为 enabled 的 STDIO MCP；Garmin 使用 Taxuspt `garmin-mcp` 且配置
  `GARMIN_IS_CN`，Gmail 使用 `@artymclabin/gmail-mcp`。
- 当前会话暴露两组工具；两次最小只读认证探测成功。CLI 中 `Auth=Unsupported` 表示 STDIO
  服务没有由 Codex 管理的 OAuth 状态，不表示凭据失效。
- MCP 已安装/认证，只证明“工具可用”；项目 Skill 还需要决定调用顺序、验证输入、写 raw/SQLite、
  处理幂等、错误和对账。当前 `plan_window.py` 与 `prepare_message.py` 均固定零 Provider 调用，
  全 Skill 脚本没有 `mcp__garmin`/`mcp__gmail` 调用，因此仍只是准备器。
- 用户已删除 `state/backups` 和 `recovery-quarantine`。当前 DB/raw/lock 仍在，删除不影响只读准备器；
  但已无本地 SQLite 备份或恢复隔离证据。初始化/备份/恢复代码将来会按需重建这些目录。
- 当前 `verify_state` 显示 DB integrity/FK/schema 正常，但因 `state/raw/.DS_Store` 未登记而整体返回
  `raw_unregistered_file`；这是独立的 raw 树杂项问题。

## 任务级独立验证

- 中性交接：只读核对当前 MCP、项目调用链和目录删除影响。
- Validator 身份/上下文：全新只读 Subagent；未接收实施者预期结论。
- 模型/推理档位：medium/medium。
- 命令与观察：独立复核 `codex mcp list/get`、当前会话工具、两个 Skill 与 state 目录。
- 结果：`PASS——配置/认证/接线事实已充分核对`

## 集成级独立验证

- 结果：`不适用——无代码集成`

## PLANS 回写清单

- [x] Exec plan 已归档到 `completed/`
- [x] Roadmap 叶子任务：不适用
- [x] 子项目和阶段状态：不适用
- [x] `memory.md` 中的活动计划指针已删除

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-16 / audit | MCP 配置、认证、工具、Skill 接线和目录删除影响全部核对 | MCP 可用；项目 adapter 未实现；当前无备份 | 已交付结论，等待用户决定后续 |
