# 执行计划：厘清辅助目录职责并迁移第三方许可声明

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`ADHOC-0004`
- 阶段/子项目：`不适用`
- Batch ID：`不适用`
- 返工来源：`无`
- 开始日期：2026-08-12
- 最后更新：2026-08-12

## 目标与验收标准

- 依据 agentForge 0.4.2 与当前仓库引用解释 `tools/`、`scripts/`、`tests/`、`test_data/` 的职责。
- 根 `THIRD_PARTY_NOTICES.md` 消失；agentForge MIT 必需声明迁入 `docs/legal/`，不把 TrainLab 整体改为 MIT。
- 构建器白名单和文档链接适配新许可路径，repository quality、打包聚焦测试与静态门通过。
- 不移动、读取或删除私人测试数据；形成后续“合成夹具替代私人样本”的明确建议，但不擅自扩大实施范围。
- 全新独立只读 Validator `PASS`。

## 范围与非目标

- 允许写入：第三方声明路径、直接构建白名单、计划与 memory 状态。
- 禁止写入：`test_data/` 内容和路径、产品业务语义、测试断言、生产数据、全局 Skill、远端和运行服务。
- 本任务不将 scripts/tools 机械搬入 tests，不删除私人样本；这些属于需单独批准的后续重构。

## 适用规则与参考资料

- 已批准规则：A-001、A-002 未被替代条款、A-003。
- 上游依据：agentForge v0.4.2 `ccc934ece6b7b64368c08bc3ce431678511ecfa3`。

## 依赖与隔离

- 显式依赖：M2、ADHOC-0002、ADHOC-0003 已完成。
- 共享接口和冻结依据：当前 CI/README/tests 的直接引用；MIT 许可原文。
- 任务分支、Worktree、集成分支：不适用。
- 允许/禁止写入范围：见上。

## 功能与测试映射

| 功能 | Feature slug | 测试目录 | 必须满足的行为 |
| --- | --- | --- | --- |
| 发布白名单许可路径 | `product-packaging` | `tests/product_packaging/` | 新许可路径可发布，旧根路径不存在 |

## 工具采用情况

- 可执行技术栈：Python 3.12、pytest、Ruff、repository quality。
- 门禁：打包聚焦测试、构建器 Ruff/format-check、repository quality、diff-check。

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 独立 Validator / `ADHOC-0004-validator` | 许可合规和目录职责 | `medium` | `medium` | 需独立确认许可未丢失及分类不误导 | 支持 | 只读 | 许可路径、构建、引用和边界 | `PASS` |

## 工作分解

| 步骤 | 状态（`pending`、`in_progress`、`blocked`、`done`） | 证据 |
| --- | --- | --- |
| 审计 agentForge 和当前目录引用 | `done` | 上游只规定 src/tests；项目额外工具按实际技术栈决定 |
| 迁移第三方许可声明并更新白名单 | `done` | 根文件消失；声明迁入 docs/legal；白名单与回归测试更新 |
| 运行适用门禁 | `done` | 23 tests passed；Ruff/format、repository quality、diff-check 全绿 |
| 独立 Validator 复核 | `done` | 许可、构建白名单、目录职责和适用门禁全部 `PASS` |
| 归档计划和清除 memory 指针 | `done` | 计划归档；memory 活动指针清除 |

## 当前检查点

- 当前 Loop：完成归档。
- 最近完成：全新独立 Validator 返回 `PASS`。
- 当前焦点：无；任务完成。
- 下一动作：等待用户决定是否启动“合成 FIT 夹具替代私人 test_data”重构，以及是否保留发布构建能力。
- 阻塞项：无。
- 已变更文件：本计划、memory、docs/legal notice、构建器和打包测试。
- 待验证项：无。

## 决策与发现

- agentForge 0.4.2 规定生产实现为根 `src/`、测试为根 `tests/<feature-slug>/`，但不禁止项目按技术栈增加 `scripts/` 或 `tools/`。
- 当前 7 个 scripts 中 6 个被 CI/文档/测试直接调用，另 1 个是隔离备份入口；它们是可执行流程，不是测试内部帮助函数。
- `tools/build_product.py` 是发布构建器，CI 和打包测试均调用；其测试属于 tests，但实现本身不属于 tests。
- 私人 FIT/表格不宜移入跟踪的 tests；目标结构应是 tests/fixtures 中的合成、可公开测试夹具，私人样本依赖归零后再删除 test_data。
- MIT 要求在软件副本或实质部分中保留版权和许可声明；可调整文件位置，但不应静默删除声明。

## 任务级独立验证

- 中性交接：仅提供用户目标、适用规则和最终仓库结果。
- Validator 身份/上下文：全新只读 Agent `ADHOC-0004-validator`，未参与实施。
- 模型/推理档位：`medium/medium`。
- 命令与观察：许可文本、构建白名单、scripts/tools/test_data 引用分类独立核验；
  23 项打包测试、Ruff/format、repository quality 和 diff-check 通过。
- 结果：`PASS`
- 未满足项与剩余风险：许可文件当前未跟踪，后续提交需纳入；私人 test_data 需由合成夹具替代后才能删除。

## 集成级独立验证

- 集成范围：不适用——单一串行任务。
- 结果：`不适用——无并行集成`

## PLANS 回写清单

- [x] Exec plan 已归档到 `completed/`
- [x] Roadmap 叶子任务已更新（不适用——ADHOC）
- [x] 子项目和阶段状态已重新计算（不适用——ADHOC）
- [x] `memory.md` 中的活动计划指针已删除

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-12 / Loop 1 | agentForge 与当前引用审计完成 | 根 notice 可移走，但许可声明应保留 | 迁入 docs/legal 并验证 |
| 2026-08-12 / Loop 1 续 | notice 迁入 docs/legal；构建白名单与测试适配；Validator `PASS` | 私人样本仍有 7 个测试依赖 | 归档并报告 |
