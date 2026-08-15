# 执行计划：source 开发、数据与数据库来源审计

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`ADHOC-0009`
- 阶段/子项目：`不适用`
- Batch ID：`read-only-audit`
- 返工来源：`无`
- 开始日期：2026-08-14
- 最后更新：2026-08-14

## 目标与验收标准

在停止继续优化工作流的前提下，只读核对 `source/` 当前开发状态、私有数据状态以及
Foundation v4 数据库的逐表来源，并梳理当前实际端到端流程、每个环节的输入/输出、写入点、
外部调用和下游用途。最终明确区分：直接登记 raw/FIT、由 raw/FIT 确定性派生、仅由生命
周期/覆盖证据派生、非 Garmin 运行数据、以及无法从现有离线证据证明的部分；给出保留、
可简化、可删除或待补证据的决策前分类。

## 范围与非目标

- 范围：Git/源码结构与未提交变更、`source/state` 文件元数据、SQLite schema/计数/外键/
  来源闭包、raw/FIT 登记与哈希对应、现有 M6 candidate 和审计证据的只读对照。
- 非目标：修复或删除工作流、重建/修改数据库、读取或展示健康正文、调用 Garmin/Gmail、
  运行正式分析、发送邮件、提交或推送。

## 适用规则与参考资料

- 已批准规则：A-001、A-004、A-007。
- 产品 Harness：`source/src/resources/harness/shared/HARNESS.md`。
- 按需读取的 references：无。

## 依赖与隔离

- 显式依赖：当前本地 `main`、Foundation v4 正式实例与已存在 M6 只读证据。
- 共享接口和冻结依据：SQLite `mode=ro&immutable=1`、文件 `lstat`/SHA-256、Git 事实。
- 任务分支：`不适用`
- Worktree：`不适用`
- 集成分支：`不适用`
- 允许写入范围：本计划、`memory.md`、M6 计划的暂停检查点。
- 禁止写入范围：`source/` 产品代码与测试、`source/state`、`source/config` 私有文件、
  `source/logs`、`data-backup`、数据库/WAL/SHM、raw/FIT、凭据、远端和外部服务。

## 功能与测试映射

`不适用——只读诊断任务`。

## 工具采用情况

- 可执行技术栈：Git、SQLite 只读 URI、Python 只读审计、文件元数据与 SHA-256。
- Linter 配置和命令：不修改代码，不运行完整产品门禁；审计脚本仅在仓库外临时执行。
- 测试框架、定向命令和完整命令：不运行正式分析或 Provider 测试。

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Worker / source 开发现状审计 | 跨模块结构与工作流识别 | `high` | `high` | 需区分已实现、未完成与历史残留 | 支持 | 只读 | 源码/CLI/测试/未提交范围清单 | `done` |
| 1 | Worker / 私有文件数据审计 | 私有数据元数据与哈希闭包 | `high` | `high` | 需避免读取或泄露正文 | 支持 | 只读 | raw/FIT/DB 文件计数、权限、哈希映射 | `done` |
| 1 | Worker / SQLite 来源血缘审计 | 高风险数据来源判定 | `high` | `high` | 需逐表区分直接来源、派生与非 Garmin 数据 | 支持 | 只读 | 表级来源矩阵、缺口与置信度 | `done` |

## 工作分解

| 步骤 | 状态（`pending`、`in_progress`、`blocked`、`done`） | 证据 |
| --- | --- | --- |
| 冻结开发动作并记录当前 Git/source 状态 | `done` | M6 保持 blocked；工作区现状保留 |
| 审计 source 开发与工作流结构 | `done` | 105 个生产 Python 文件、131 个测试模块、6 个正式顶层命令 |
| 审计文件数据、权限与登记哈希闭包 | `done` | 27,388 个 raw 文件与 raw_objects 路径/大小/SHA 全闭合 |
| 审计数据库逐表来源和非 raw/FIT 数据 | `done` | 55 表、21 视图；逐表来源矩阵完成 |
| 梳理当前端到端流、环节与可达性 | `done` | 15 环节输入/输出/写入/外部调用矩阵完成 |
| 交叉核对并形成决策前报告 | `done` | 结论与保留/简化/删除候选/待证据分类完成 |

## 当前检查点

- 当前 Loop：只读来源审计已经完成；M6 继续保持 blocked，不自动恢复。
- 最近完成：source、文件数据和 SQLite 血缘三路独立审计已交叉核对。
- 当前焦点：等待用户依据审计报告决定保留、简化或删除哪些流程。
- 下一动作：仅在用户明确选择后建立后续实现范围。
- 阻塞项：无。
- 已变更文件：仅本计划与治理状态记录。
- 待验证项：Garmin 当前上游是否完整、21 条 unresolved 活动的真实状态、4 个 legacy FIT 归属；均不在本次离线审计中猜测。

## 决策与发现

- `source/` 是一套已串通的手动单次运行产品，正式链路为：入口与 Foundation → Garmin
  raw/revision → 确定性活动/健康/FIT 投影 → coverage/cursor/gap/lifecycle → analysis
  context 与 deterministic safety → artifact/delivery → preview 或显式 Gmail；另有独立入站
  Mail Agent 路径。旧 Supervisor/产品 Orchestration 已不在公共命令面。
- 当前工作区的 M6 离线合同返修尚未获得覆盖最终快照的独立验证；真实
  `weekly → daily → preview` 没有成功证据，不能视为已交付。
- `source/state/raw` 有 27,388 个文件、171,278,307 字节：Garmin JSON 26,832、FIT
  510、TCX 1、GPX 1、backup-only JSON 44。文件与 `raw_objects` 的路径、大小、SHA-256
  完全闭合；44,467 个 revision 全部有 raw FK，所有 FIT 均被 revision 引用。
- Foundation v4 数据库有 55 表、21 视图；integrity/FK/schema manifest 均通过。数据库
  并非“全部直接来自 raw 健康数据和 FIT”：除 Garmin JSON/FIT/TCX/GPX 投影外，还包含
  coverage、cursor、gap、capability、生命周期、质量核对、身份和 schema 元数据。
- 明确的来源例外是 3 条 `physiology_records` 及其 9 条子指标没有 source revision；
  `source_field_catalog` 和 `activity_metric_sources` 只有实现级或活动级间接血缘。
- 当前 analysis、training plan、delivery、mail、conversation 和 user-fact 相关表全部为空；
  相关代码和 schema 仍存在，是否保留应按产品需求整体决定，不能只删空表。
- 生命周期状态为 active 2、suspected_missing 7、provider_deleted 503；当前视图仅 9 条。
  raw/FIT 物理完整不等于 Provider 当前成员状态正确，21 条 unresolved 会影响四周容量。
- 保留：Foundation、raw/revision、确定性投影、coverage/cursor/gap、lifecycle 核心、
  bounded context、安全门、artifact lineage 和只读 preview。
- 可简化：重复 CLI adapter、兼容 facade、超大模块、分析前 HR zone 写入职责、每次分析
  建 pending delivery 的策略。
- 可删除候选：`garmin_legacy.py`、确认无调用后的旧 facade、本地 caches；整套入站 Mail
  Agent、facts 与空 schema 表必须先确认是否仍需邮件双向教练功能。
- 待补证据：21 条 lifecycle unresolved、4 个 legacy FIT、3 条无 revision physiology、
  1 个孤立 device，以及 Garmin 当前上游完整性。

## 任务级独立验证

- 中性交接：不适用——本任务本身为多路只读审计，主协调执行交叉核对。
- 结果：`不适用——三路独立只读审计均完成，无产品修改需要释放`
- 未满足项与剩余风险：本审计不证明 Garmin 上游最新性，不遍历 `data-backup/` 内容，
  不替代 M6 最终 Validator。

## 集成级独立验证

- 结果：`不适用——无产品修改或并行集成`

## PLANS 回写清单

- [x] Exec plan 已归档到 `completed/`
- [x] Roadmap 回写不适用
- [x] 子项目和阶段状态回写不适用
- [x] `memory.md` 中的活动计划指针已删除

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-14 / start | 停止 M6 继续优化并建立只读来源审计 | 用户希望先判断现状，再决定删改工作流 | 并行完成 source、文件数据和 SQLite 血缘审计 |
| 2026-08-14 / audit-complete | 三路只读审计完成；文件哈希闭包、逐表来源和流程矩阵已交叉核对 | 物理 raw/FIT 完整，但数据库还含系统/派生元数据和 3 条无 revision 生理记录；活动生命周期仍是主要分析风险 | 归档本计划，等待用户选择后续范围 |
