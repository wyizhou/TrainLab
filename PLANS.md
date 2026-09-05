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
- 完成条件遵循执行协议：串行正式任务独立 PASS；实际并行任务另需集成级 PASS；轻量/只读任务按适用证据结束。只有满足适用条件才能标为 `[x] completed`。
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

### [ ] `M12` FIT 运动数据与每周跑步教练重建 — `active`

用户于 2026-09-05 批准：仅采集 2022 年起全部运动 FIT，复用已有文件，建立新 SQLite；
每日 22:00 同步当日、昨日和已知缺口，周日 15:00 进行一次周分析并发布 PDF、邮件与 Garmin
跑步课程。旧非核心代码/数据统一归档且不能成为新运行依赖；根开发 Harness 保留，旧运行
Harness 和每日健康/AI 路径退出新方向。M11 未完成部分由 M12 替代，不追溯改写旧失败记录。

阶段严格串行；手动启动 Python，不安装 cron 或开机启动。离线验收后首份真实周报选择下个
正常周日 15:00，多周错过只补最新一期并注明原统计周期和“补发”。内容、数据和验收范围以
[M12 执行计划](docs/exec-plans/active/M12-fit-weekly-0001-rebuild.md) 为准。

唯一新增交付要求：每个小功能/模块通过适用测试与独立验证后，提交并正常推送现有远程分支；
当前先保存“新方向替代旧方向”的检查点。此授权不包含私人数据、强制推送、部署或跳过验证。

| 任务 | 状态 | 显式依赖 | Batch | 预期成果 |
| --- | --- | --- | --- | --- |
| [x] `M12-0001` 保护检查点、冻结与统一归档 | completed | 用户批准 | serial-m12 | 检查点及恢复归档完成；旧入口退役/测试映射独立PASS；旧物理代码随替代模块迁移 |
| [ ] `M12-0002` FIT 新库与同步 | planned | M12-0001 | serial-m12 | 历史导入、分页、每日同步表与缺口恢复 |
| [ ] `M12-0003` 解析与 AI 边界 | planned | M12-0002 | serial-m12 | 分段摘要、脱敏细读、无状态可替换接口 |
| [ ] `M12-0004` 周分析与发布 | planned | M12-0003 | serial-m12 | 固定跑步计划、Markdown/PDF、Gmail REST/Garmin |
| [ ] `M12-0005` Python 调度与离线验收 | planned | M12-0004 | serial-m12 | 定时、补发、恢复、完整独立验收 |
| [ ] `M12-0006` 真实验收与切换 | planned | M12-0005 | serial-m12 | 历史同步及下个正常周日真实闭环、正式切换 |

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

### [x] `M10` 滚动七日真实端到端验收 — `completed`

用户于 2026-08-18 批准。M10 使用仓库外全新 Candidate，复用正式库已有证据并有界补齐
2026-08-11～17 的活动/健康与醒来日为 2026-08-12～18 的主睡眠，生成 7 份日报、1 份周报和
2026-08-19～25 周计划。全部离线结果通过后，自投递 8 封 Gmail；最多创建、验证并排期 4 个
本次独占命名的 Garmin 跑步 Workout，随后解除本次排期并删除本次 Workout。正式 state、既有
Workout/日历课程、goal、凭据和远端 Git 不修改。

| 任务 | 状态 | 优先级 | 显式依赖 | Batch | 预期写入范围 | Exec plan |
| --- | --- | --- | --- | --- | --- | --- |
| [x] `M10-0001` 冻结治理、窗口与外部预算 | `completed` | high | M9 | serial-m10 | Roadmap、exec plan、运行合同 | [`completed`](docs/exec-plans/completed/M10-live-e2e-0001-rolling-week.md) |
| [x] `M10-0002` 七日 Candidate 补数和完整报告闭环 | `completed` | high | M10-0001 | serial-m10 | Garmin sync、教练/报告运行器、Schemas、Candidate | 同一 exec plan |
| [x] `M10-0003` Gmail/Garmin 外部动作执行器与离线验证 | `completed` | high | M10-0002 | serial-m10 | Gmail/GTS Skills、共享状态、code tests | 同一 exec plan |
| [x] `M10-0004` 精确写入确认、真实发送和 Workout 生命周期 | `completed` | high | M10-0003 | serial-m10 | Garmin测试生命周期完成且残留0；r07旧标题8封和r08更正标题8封全部闭合，累计16封 | 同一 exec plan |
| [x] `M10-0005` AI、数据/隐私与清理独立验收 | `completed` | high | M10-0004 | serial-m10 | Code、AI、Delivery/Data-Privacy最终Validator均PASS；正式state/Token和重放闭合 | 同一 exec plan |

### [ ] `M11` 人类可读邮件与 CID 图表闭环 — `cancelled/content-first-v4`

2026-09-05：用户批准 M12 新方向，未完成的 v4 返工取消；已完成的历史叶子和失败证据保留。
以下为原批准范围记录，不是当前运行目标或新的在线授权。

用户于 2026-08-21 批准。M11 以 M10 已验证的 AI 结果、证据和 Gmail REST 单次发送状态机为
基础，把日报与周报转换为中文人类可读邮件；仅从明确、已验证的数据数组生成静态 PNG 图表，
并通过私有 CID 附件嵌入邮件。阶段先完成仓库外真实 Candidate 预览和三类独立验证，停在真实
canary 授权之前。用户随后批准真实 Gmail 样式 canary；首封日报已成功送达但暴露 VO₂ Max/
体重仅按精确日期读取的缺口。2026-08-22 用户进一步批准 A-014：使用 30/14 天有界最近值、
重发一封确定性修正版日报，确认后再发送原周报。用户随后确认邮件技术投递和样式闭合，但内容
无法直接指导训练，因此批准 A-015 内容返工：不计算心率区间，以 RPE/体感组织 SOS 与详细课程，
先离线生成七份日报和一份周报供审核。M11 不修改正式 `source/state`、不提交、不推送、不启用
cron、Sites 或新的外部动作。2026-08-23 用户判定 v2 邮件与 OpenDesign 高保真设计不一致，
批准 A-016 与 v3 离线返工：冻结既有 AI/课表，恢复共享卡片、KPI、真实图表和七日时间轴；
历史心率分区只展示 Garmin/FIT session 已记录时长，不由 TrainLab 重新划区或用于课程处方。
最终 r06 以 594 项测试和 Code、Design-Fidelity、Data/Privacy 三类全新只读 Validator 全部
`PASS` 完成离线交付；真实 Gmail 重发、部署与定时运行仍需后续单独批准。
2026-08-23用户进一步明确授权将v3的7份日报和1份周报一次性真实自投递；该批次只复用官方
Gmail REST单写者并逐封完成RAW/CID闭合，不重跑数据或AI，不授权部署和定时运行。
M11-0015已严格串行完成32次Gmail REST调用与8次发送；8个Gmail ID、实际Message-ID、RAW、
text、HTML和CID全部闭合，零调用重放及全新Delivery/Data-Privacy Validator均为`PASS`。
2026-08-24 用户确认 v3 内容仍不能支持实际决策，批准 A-018 与 content-first v4：日报只保留
健康/恢复分析、昨日全部运动事实和今日固定课程；周报分析连续七日全部实际运动与健康，加入
有界 FIT 技术复盘并生成唯一固定周计划。先交付 Markdown 与扁平低保真 HTML；允许一次隔离
真实周报 Codex 调用，但不调用 Garmin/Gmail/Workout/Sites/cron，不发送邮件或修改正式 state。
2026-08-24 根开发 Harness 升级到 agentForge v0.4.4 后，M11 以 legacy transition 建立面向
后续工作的冻结合同；独立 Failure Analyst 已完成归因，用户批准 VC-002 六类健康三状态、
逐活动证据身份和路径边界。当前先进行全新 Contract Validator 验收，PASS 前不得修改产品实现
或执行真实模型调用。

| 任务 | 状态 | 优先级 | 显式依赖 | Batch | 预期写入范围 | Exec plan |
| --- | --- | --- | --- | --- | --- | --- |
| [x] `M11-0001` 保存 M10 基线并冻结设计与治理 | `completed` | high | M10 | serial-m11 | 本地基线提交、A-013、设计快照、Roadmap/exec plan | [`completed`](docs/exec-plans/completed/M11-email-presentation-0001-readable-cid.md) |
| [x] `M11-0002` 建立日报/周报 ViewModel 与可读模板 | `completed` | high | M11-0001 | serial-m11 | `training-report-publisher`、Schemas、模板、映射测试 | 同一 exec plan |
| [x] `M11-0003` 建立 CID MIME v2 与通用 Fake 投递路径 | `completed` | high | M11-0002 | serial-m11 | `gmail-sender`、MIME/RAW 验证、Fake REST 测试 | 同一 exec plan |
| [x] `M11-0004` 真实 Candidate 私有预览与完整质量门 | `completed` | high | M11-0003 | serial-m11 | 仓库外 owner-only 预览、视觉/隐私/幂等验证 | 同一 exec plan |
| [x] `M11-0005` 三类独立验证并停在 canary 授权前 | `completed` | high | M11-0004 | serial-m11 | Code、Visual、Data/Privacy Validator 全部PASS；等待另行授权真实canary | 同一 exec plan |
| [x] `M11-0006` 真实 Gmail 样式 canary 与收口 | `completed/technical-only` | high | M11-0005 | serial-m11-live | 历史RAW/HTML/text/CID技术闭合；内容失败证据保留并由v2/v3替代 | 同一 exec plan |
| [x] `M11-0007` 冻结 Coaching Utility v2 治理和设计合同 | `completed` | high | M11-0006 | serial-m11-v2 | A-015、设计章程、Skills/AGENTS、Design Validator | 同一 exec plan |
| [x] `M11-0008` v2 证据、AI、课程与安全合同 | `completed` | high | M11-0007 | serial-m11-v2 | 用户授权统一读者自由文本心率处方门 | 同一 exec plan |
| [x] `M11-0009` v2 日报/周报 ViewModel 与渲染 | `completed` | high | M11-0008 | serial-m11-v2 | 用户授权工程字段显示白名单闭包 | 同一 exec plan |
| [x] `M11-0010` 七日报一周报私有离线验收 | `completed` | high | M11-0009 | serial-m11-v2 | owner-only Candidate、最多9次Codex、三类Validator、用户审核 | 同一 exec plan |
| [x] `M11-0011` 冻结 v3 设计一致性与历史分区展示边界 | `completed` | high | M11-0010 | serial-m11-v3 | A-016、交接/解析/验收只读审计 | 同一 exec plan |
| [x] `M11-0012` 建立展示证据与共享 OpenDesign 渲染引擎 | `completed` | high | M11-0011 | serial-m11-v3 | 五项Schema、FIT/睡眠解析、日报/周报View与共享渲染 | 同一 exec plan |
| [x] `M11-0013` 生成七日报一周报 v3 离线 Candidate | `completed` | high | M11-0012 | serial-m11-v3 | owner-only Candidate、真实图表、672/375px逐组件验收 | 同一 exec plan |
| [x] `M11-0014` v3 三类独立验证与离线交付 | `completed` | high | M11-0013 | serial-m11-v3 | r06 Code、Design-Fidelity、Data/Privacy Validator全部PASS | 同一 exec plan |
| [x] `M11-0015` v3七日报一周报真实Gmail投递 | `completed` | high | M11-0014 | serial-m11-v3-live-r01 | 版本化8项Live Candidate、REST串行投递、RAW/CID与最终独立验收全部PASS | [`completed`](docs/exec-plans/completed/M11-email-presentation-0001-readable-cid-r01.md) |
| [x] `M11-0016` 冻结内容优先治理与日期/安全合同 | `completed` | high | M11-0015 | serial-m11-v4 | A-018、AGENTS/Skills、内容与技术矩阵；全新最终Contract Validator PASS | [`cancelled`](docs/exec-plans/completed/M11-email-presentation-0001-readable-cid-r02.md) |
| [x] `M11-0017` 建立全量观察证据、新版AI与固定课表合同 | `completed/VC-008` | high | M11-0016 | serial-m11-v4 | Contract与Closure Code Validator均PASS；869项及全部静态门独立闭合 | 同一 exec plan |
| [ ] `M11-0018` 生成Markdown、低保真HTML与真实周报预览 | `cancelled` | high | M11-0017 | serial-m11-v4 | 用户批准 M12 替代；r19 业务校验失败/私人调用0历史保留，不改写为成功 | 同一 exec plan |
| [ ] `M11-0019` 内容/信息架构/数据隐私验证与OpenDesign交接 | `cancelled` | high | M11-0018 | serial-m11-v4 | 用户批准 M12 替代，未执行的旧交接不再续跑 | 同一 exec plan |
