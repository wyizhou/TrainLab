# TrainLab Roadmap

本文件回答“接下来准备开发什么”，长期保存产品和工程方向、阶段、子项目、叶子任务、
显式依赖与并行批次。具体步骤、命令、检查点和证据只写入 `docs/exec-plans/`。

## 治理约定

- 主协调 Agent 可依据用户目标和仓库事实提出候选阶段、任务、顺序、依赖和批次。
- 阶段目标、范围、任务增删、排序和并行拓扑必须经人工明确批准后才能生效。
- 远期阶段只记录目标、依赖和预期成果，不提前设计详细实现。
- 当前阶段准备启动时，才展开批准的叶子任务、验收目标、写入范围和批次。
- 任务进入 ready batch、即将修改仓库时才建立 exec plan；不得批量创建尚未就绪的计划。
- 主协调 Agent 可依据执行事实自动同步状态、勾选、exec-plan 链接和汇总进度，
  但不得借状态同步改变批准范围。

## ID、状态与链接

- 阶段使用稳定 ID，例如 `P1`、`M1` 或 `Q1`。
- 叶子任务使用阶段内全局递增 ID，例如 `P1-0001`；编号只表示排序和优先级，不表示依赖。
- 依赖通过任务表“显式依赖”列声明。
- 状态使用 `planned`、`ready`、`active`、`blocked`、`validating`、`validated`、
  `integrating`、`completed`、`rework` 或 `cancelled`。
- 只有通过全部适用任务级和集成级验证的任务才可标为 `[x] completed`；其他状态保持 `[ ]`。
- 子项目或阶段只有在批准范围内全部非取消叶子任务完成后才能勾选。
- 任务启动后链接 `active/` 计划；完成后更新为 `completed/` 链接。

## 批次与本地 Git 授权

- 同一 ready batch 必须依赖已满足、写入不重叠、接口已冻结，且不会并发修改同一迁移、
  配置入口或集成文件。
- 阶段批准记录必须列明允许创建的本地任务分支、worktree、任务提交和集成分支；
  该批准不包含远程推送、主分支合并、发布或部署。
- 发现依赖或写入冲突时停止受影响任务并降为串行。降低并行度不扩大授权；
  新增范围、任务或外部影响必须重新批准。
- 本仓库不使用 `orchestrate-parallel-work`、`.orchestration`、Graph/Dashboard 或
  hash-bound handoff 承载 Roadmap 和批次。

## 阶段批准记录模板

| 字段 | 内容 |
| --- | --- |
| 阶段 ID | `<stage-id>` |
| 目标与预期成果 | `<outcome>` |
| 范围与非目标 | `<scope>` |
| 前置阶段/外部依赖 | `<dependencies>` |
| 本地 Git 操作 | `<branches/worktrees/integration branch>` |
| 批准人和日期 | `<human approval>` |
| 状态 | `planned` |

## 阶段与任务模板

### [ ] `<stage-id>` `<阶段名称>` — `planned`

目标、依赖和预期成果：`<summary>`

#### [ ] `<initiative-id>` `<子项目名称>` — `planned`

| 任务 | 状态 | 优先级 | 显式依赖 | Batch | 预期写入范围 | Exec plan |
| --- | --- | --- | --- | --- | --- | --- |
| [ ] `<stage>-0001 <任务名称>` | `planned` | `<priority>` | `none` | `<batch-id>` | `<paths>` | 尚未创建 |

## 当前已批准 Roadmap

### [x] `M1` agentForge 与 product-root 迁移 — `completed`

用户于 2026-08-12 批准。仓库根成为开发 Harness，`product/` 成为唯一 TrainLab 产品
源码与运行根，`dist/` 只包含白名单、无私有数据的生成产物。该阶段严格串行，无并行批次。

| 任务 | 状态 | 优先级 | 显式依赖 | Batch | 预期写入范围 | Exec plan |
| --- | --- | --- | --- | --- | --- | --- |
| [x] `M1-0001` 落地开发 Harness | `completed` | high | none | serial | 根治理文件；旧 `.orchestration` 清理 | [`completed`](docs/exec-plans/completed/M1-agentforge-migration-0001-development-harness.md) |
| [x] `M1-0002` 建立唯一产品源码 | `completed` | high | M1-0001 | serial | `product/`、CI、构建工具 | [`completed`](docs/exec-plans/completed/M1-product-root-0002-source-migration.md) |
| [x] `M1-0003` 迁移运行数据并切换根路径 | `completed` | high | M1-0002 | serial | 本地 state/config/logs、LaunchAgent 路径 | [`completed`](docs/exec-plans/completed/M1-runtime-root-0003-data-switch.md) |

该阶段当时没有未完成的已批准 Roadmap 任务；非 Roadmap 的 agentForge 0.4.2 升级
曾由已归档的 `ADHOC-0001` exec plan 管理，不改变本表批准范围。

### [x] `M2` agentForge 0.4.2 根项目布局迁移 — `completed`

用户于 2026-08-12 明确要求纠正上一阶段的 `product/` 适配，严格采用 agentForge
0.4.2 的根 `src/` 与根 `tests/` 项目布局，并同步迁移项目描述、产品 Harness、文档、
质量门、构建、运行数据与本地运行入口。本阶段为单一原子迁移任务，严格串行。

| 任务 | 状态 | 优先级 | 显式依赖 | Batch | 预期写入范围 | Exec plan |
| --- | --- | --- | --- | --- | --- | --- |
| [x] `M2-0001` 将 TrainLab 完整迁移到 agentForge 根项目布局 | `completed` | high | M1、ADHOC-0001 | serial | `product/` → 根项目树；治理、CI、构建、本地运行路径 | [`completed`](docs/exec-plans/completed/M2-agentforge-root-layout-0001-project-migration.md) |

### [x] `M3` 私人测试数据脱敏迁移 — `completed`

用户于 2026-08-12 批准：以可提交、可重复生成且不含个人信息的合成 FIT 夹具替代
`test_data/` 中的私人历史样本；验证通过后删除 `test_data/`，消除跨设备测试依赖。

| 任务 | 状态 | 优先级 | 显式依赖 | Batch | 预期写入范围 | Exec plan |
| --- | --- | --- | --- | --- | --- | --- |
| [x] `M3-0001` 用合成 FIT 夹具替代私人 test_data | `completed` | high | M2 | serial | `tests/fixtures/`、7 个 Garmin 测试模块、测试支持代码、`test_data/` 清理 | [`completed`](docs/exec-plans/completed/M3-test-fixtures-0001-synthetic-fit-migration.md) |

### [x] `M4` source 工程、健康数据重建与教练 Harness v2 — `completed`

用户于 2026-08-13 批准以一个 Roadmap、四个严格串行任务完成迁移。根目录只保留
agentForge 开发 Harness；产品代码和实例入口位于 `source/`；旧运行数据保留在完全
忽略的 `data-backup/`；不使用旧编排插件、Graph/Dashboard、Supervisor、wheel/bundle
或仓库 `.venv`。本阶段不调用 Garmin/Gmail、不发送邮件、不提交或推送。

| 任务 | 状态 | 优先级 | 显式依赖 | Batch | 预期写入范围 | Exec plan |
| --- | --- | --- | --- | --- | --- | --- |
| [x] `M4-0001` source 工程与历史运行层清理 | `completed` | high | M3、ADHOC-0008 | serial | `source/`、CI、ignore、旧 Orchestration 清理 | [`completed`](docs/exec-plans/completed/M4-source-root-0001-product-consolidation.md) |
| [x] `M4-0002` Foundation v4 离线 Garmin 重建 | `completed` | high | M4-0001 | serial | `source/tools`、候选 state、`data-backup` 归档 | 同一 completed plan |
| [x] `M4-0003` 运行时教练 Harness v2 与课程合同 | `completed` | high | M4-0002 | serial | `source/src/resources/harness`、analysis 合同/测试 | 同一 completed plan |
| [x] `M4-0004` 原子切换私人数据与独立验收 | `completed` | high | M4-0003 | serial | source 实例入口、验证证据、计划归档 | 同一 completed plan |

### [x] `M5` 自适应教练画像与本地报告校准 — `completed`

用户于 2026-08-14 批准。M5 在已提交的 M4 基线之上严格串行执行：先保存基线，随后建立
AI 提案/用户确认的教练画像管理，按近期完整周动态评估容量，最后只在仓库外隔离实例中
生成周报、日报及 HTML/JSON 预览。M5 不调用 Garmin/Gmail、不补数、不发送邮件、不修改
正式 `source/state`，不推送远端；M5 已按批准保存为本地基线，未推送远端。

| 任务 | 状态 | 优先级 | 显式依赖 | Batch | 预期写入范围 | Exec plan |
| --- | --- | --- | --- | --- | --- | --- |
| [x] `M5-0001` 保存 M4 单一本地基线 | `completed` | high | M4 | serial | Git 基线提交 | [`completed`](docs/exec-plans/completed/M5-adaptive-coaching-0001-profile-and-preview.md) |
| [x] `M5-0002` AI 教练画像管理与确认应用 | `completed` | high | M5-0001 | serial | `source/src/coaching`、CLI、私有 profile state、画像测试 | [`completed`](docs/exec-plans/completed/M5-adaptive-coaching-0001-profile-and-preview.md) |
| [x] `M5-0003` 动态周容量与排课合同 | `completed` | high | M5-0002 | serial | `source/src/analysis`、运行时 schema、容量/排课测试 | 同一 completed plan |
| [x] `M5-0004` 隔离数据库报告预览 | `completed` | high | M5-0003 | serial | `source/src/analysis`、预览 CLI、隔离预览测试 | 同一 completed plan |

### [ ] `M6` 活动证据一致性与真实报告预览 — `cancelled/superseded`

用户于 2026-08-14 批准离线优先路径。M6 先保存 M5 本地基线，再审计并修复 inventory
生命周期证据，在仓库外 candidate 中生成真实周报、日报和 HTML/JSON 预览。正式
`source/state`、Garmin、Gmail、邮件和远端 Git 均不触碰；在线核验另立阶段。

| 任务 | 状态 | 优先级 | 显式依赖 | Batch | 预期写入范围 | Exec plan |
| --- | --- | --- | --- | --- | --- | --- |
| [ ] `M6-0001` 保存 M5 单一本地基线 | `cancelled/superseded` | high | M5 | serial-m6 | 本地 Git 提交 | [`completed`](docs/exec-plans/completed/M6-activity-evidence-0001-lifecycle-and-preview.md) |
| [ ] `M6-0002` 审计并统一 inventory 生命周期证据 | `cancelled/superseded` | high | M6-0001 | serial-m6 | `source/src/garmin`、`source/tools`、生命周期测试 | 同一 completed plan |
| [ ] `M6-0003` candidate 离线修复与完整性验证 | `cancelled/superseded` | high | M6-0002 | serial-m6 | candidate-only 数据工具和测试 | 同一 completed plan |
| [ ] `M6-0004` 真实周报、日报和 HTML/JSON 预览 | `cancelled/superseded` | high | M6-0003 | serial-m6 | candidate-only 预览证据和测试 | 同一 completed plan |

### [x] `ADHOC-0011` AI + Skills 运行架构 — `completed`

用户于 2026-08-15 批准。严格串行保存当前工作区保护提交，建立 `source/` 运行 Harness、
六个本地 Skills、六表 SQLite 状态和两个 cron 配置；在仓库外 candidate 重组可证明 raw，
将旧 state 完整归档后再原子切换。Garmin、Gmail、Sites、cron 安装和新架构代码提交均不在
本阶段授权范围内。

| 任务 | 状态 | 优先级 | 显式依赖 | Batch | 预期写入范围 | Exec plan |
| --- | --- | --- | --- | --- | --- | --- |
| [x] `ADHOC-0011-0001` 保存当前 M6 工作区保护提交 | `completed` | high | M6 | serial-adhoc-0011 | Git 本地保护提交 | [`completed`](docs/exec-plans/completed/ADHOC-0011-state-raw-retention-and-tuning.md) |
| [x] `ADHOC-0011-0002` 建立 source Harness、Skills、模板和 SQLite 工具 | `completed` | high | ADHOC-0011-0001 | serial-adhoc-0011 | `source/AGENTS.md`、`source/skills`、模板、共享脚本、SQLite Schema | [`completed`](docs/exec-plans/completed/ADHOC-0011-state-raw-retention-and-tuning.md) |
| [x] `ADHOC-0011-0003` candidate raw 重组和新数据库建立 | `completed` | high | ADHOC-0011-0002 | serial-adhoc-0011 | 仓库外 candidate、脱敏迁移收据 | [`completed`](docs/exec-plans/completed/ADHOC-0011-state-raw-retention-and-tuning.md) |
| [x] `ADHOC-0011-0004` 归档旧 state、原子切换和离线验证 | `completed` | high | ADHOC-0011-0003 | serial-adhoc-0011 | `data-backup` 归档、`source/state`、只读 cron 配置 | [`completed`](docs/exec-plans/completed/ADHOC-0011-state-raw-retention-and-tuning.md) |

### [x] `M7` AI + Skills 执行闭环与双层测试体系 — `completed`

用户于 2026-08-16 批准。M7 在 ADHOC-0011 的本地 AI + Skills 运行树上继续严格串行，先保存
基线，再修复 SQLite 状态与自动槽位判定，完成不调用外部服务的日报/周报离线闭环，并建立
确定性代码测试与按需 AI 语义验收两层测试。正式 `source/state`、Garmin、Gmail、Sites、cron
安装和远程 Git 均不触碰；仅在仓库外合成 candidate 中验证闭环。

| 任务 | 状态 | 优先级 | 显式依赖 | Batch | 预期写入范围 | Exec plan |
| --- | --- | --- | --- | --- | --- | --- |
| [x] `M7-0001` 保存基线并更新测试治理 | `completed` | high | ADHOC-0011 | serial-m7 | 本地基线提交、A-009、AGENTS/CI/计划 | [`completed`](docs/exec-plans/completed/M7-ai-skills-0001-runtime-closure.md) |
| [x] `M7-0002` 状态合同与唯一自动入口 | `completed` | high | M7-0001 | serial-m7 | `source/skills/_shared`、SQLite 测试 | 同一 exec plan |
| [x] `M7-0003` 六个 Skills 离线业务闭环 | `completed` | high | M7-0002 | serial-m7 | Skill 脚本、schemas、candidate-only workflow | 同一 exec plan |
| [x] `M7-0004` code 与 AI 双层测试 | `completed` | high | M7-0003 | serial-m7 | `source/tests/code`、`source/tests/ai` | 同一 exec plan |
| [x] `M7-0005` 独立验证与第二个本地提交 | `completed` | high | M7-0004 | serial-m7 | 验证收据、最终本地提交、计划归档 | 同一 exec plan |

### [x] `M8` 真实私人数据离线 AI 教练闭环 — `completed`

用户于 2026-08-16 批准。M8 在 M7 离线合成闭环之上，使用真实 Garmin raw、私人 goal 和仓库外
candidate 验证真正由 AI 生成的日报、周报与课表。健康只提供资源专用总览；活动提供 30 秒序列，
AI 可在固定预算内按需细读活动片段。禁止向 AI 提供 GPS、原始文件字节、凭据或完整历史日报正文。
不修改正式 `source/state`，不调用 Garmin/Gmail/Sites，不发送邮件、不操作 Workout、不安装 cron、
不提交、不推送。冻结计划后不得为得到 PASS 修改目标、日期、Schema、阈值、测试预期或失败语义。

| 任务 | 状态 | 优先级 | 显式依赖 | Batch | 预期写入范围 | Exec plan |
| --- | --- | --- | --- | --- | --- | --- |
| [x] `M8-0001` 冻结基线、Roadmap 与反绿灯规则 | `completed` | high | M7 | serial-m8 | Roadmap、active exec plan、治理记录 | [`completed`](docs/exec-plans/completed/M8-real-data-0001-ai-coach-closure.md) |
| [x] `M8-0002` 真实健康/活动解析与片段证据 | `completed` | high | M8-0001 | serial-m8 | `source/skills`、Schemas、code tests | 同一 exec plan |
| [x] `M8-0003` 真正 AI 日报/周报提交与幂等 | `completed` | high | M8-0002 | serial-m8 | `source/skills`、AI tests | 同一 exec plan |
| [x] `M8-0004` Candidate 真实日期闭环 | `completed` | high | M8-0003 | serial-m8 | 仓库外 candidate、私有报告 | 同一 exec plan |
| [x] `M8-0005` Code、AI、数据/隐私独立验证 | `completed` | high | M8-0004 | serial-m8 | 验证证据、计划回写 | 同一 exec plan |

### [x] `M9` 单日 Garmin MCP 有界真实只读闭环 — `completed`

用户于 2026-08-17 批准。M9 先将已验证 M8 保存为本地提交，再以固定香港时区单日窗口在
仓库外 candidate 中接通本地 Garmin MCP，只读采集 2026-08-16 健康与活动和醒来日为
2026-08-17 的主睡眠，并生成离线日报。Provider、工具、日期、数量和墙钟预算均冻结；失败不自动
重试或扩大范围。正式 `source/state`、Gmail、Workout、Sites、cron 和远程 Git 均不触碰。

| 任务 | 状态 | 优先级 | 显式依赖 | Batch | 预期写入范围 | Exec plan |
| --- | --- | --- | --- | --- | --- | --- |
| [x] `M9-0001` 保存 M8 本地基线 | `completed` | high | M8 | serial-m9 | 本地 Git 提交 | [`completed`](docs/exec-plans/completed/M9-garmin-live-0001-bounded-daily-sync.md) |
| [x] `M9-0002` Garmin MCP 有界只读采集器 | `completed` | high | M9-0001 | serial-m9 | `source/skills/garmin-sync`、共享 Schema、code tests | 同一 exec plan |
| [x] `M9-0003` 冻结在线范围与离线预验 | `completed` | high | M9-0002 | serial-m9 | fake MCP、预算/Token/幂等验证 | 同一 exec plan |
| [x] `M9-0004` Candidate 真实采集与离线日报 | `completed` | high | M9-0003 | serial-m9 | r04 真实只读采集、r07 公开 canary、唯一 attempt 4、日报/报告/receipt 与幂等重放 | 同一 exec plan |
| [x] `M9-0005` Code、AI、数据/隐私独立验证 | `completed` | high | M9-0004 | serial-m9 | 207 项代码门与三类全新只读 Validator 均 PASS；正式 state/Token 不变、外部动作 0 | 同一 exec plan |
