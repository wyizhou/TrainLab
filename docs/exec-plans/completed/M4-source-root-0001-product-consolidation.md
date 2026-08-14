# 执行计划：M4 `source/` 工程、健康数据重建与教练 Harness v2

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`M4`
- 批次：严格串行（M4-0001 → M4-0002 → M4-0003 → M4-0004）
- 开始日期：2026-08-13
- 最后更新：2026-08-14

## 目标

建立单一 `source/` 产品工程：根目录只保留 agentForge 开发 Harness、Git/CI 元数据和
项目治理文件；`source/src/` 是唯一产品包，`source/index.py` 是唯一直接入口；旧
Orchestration/Supervisor/后台部署和 wheel/bundle 构建链不再属于产品。旧运行数据不删除，
而是完整归档到被 Git 忽略的 `data-backup/`。在此基础上建立不含 Orchestration 表的
Foundation v4 离线重建库，并把运行时教练 Harness 升级为课程、睡眠、负荷和进阶均有
结构化合同的 v2。

## 硬边界

- 不加载或调用 `orchestrate-parallel-work`，不创建 Graph、Dashboard、handoff digest 或
  连续审批版本。
- 本计划不调用 Garmin/Gmail，不认证、不补数、不分析、不发邮件、不启动 Supervisor，
  不提交、不推送、不部署。
- 私有 `source/config`、`source/state`、`source/logs`、凭据、数据库、raw、FIT 和
  `data-backup/` 只做受控本地迁移或候选重建，内容不输出、不进 Git。
- 旧 Orchestration 数据不在本计划物理删除；归档目录保留回滚和审计证据。新库不创建
  七张 Orchestration 表和两个视图。
- 运行时 Harness 只能接收有界、带 schema 和来源 lineage 的 JSON；模型不得自行读取
  数据库、FIT、聊天、网络或凭据。

## 串行任务与验收

### M4-0001：工程布局与历史运行层清理

- `src/trainlab/*` 已迁入 `source/src/*`，不建立 `source/src/trainlab/`。
- `source/index.py` 预先设置默认 `TRAINLAB_INSTANCE_ROOT=source/`，尊重显式覆盖，并
  校验实际 `src.__file__` 来自 `source/src/`。
- 删除产品 Orchestration、Supervisor、自动调度 CLI、相关 schema/config/docs/deploy
  和专属测试；保留 Foundation/Garmin/Analysis/Mail 的手动一次性命令。
- 删除 wheel/runtime bundle 构建器、安装器、`dist/build/deploy` 与仓库 `.venv` 依赖。
- CI、质量脚本和文档均从 `source/` 工作；锁文件仅为 `source/requirements.lock`。
- `.gitignore` 只忽略私有配置、state、logs、数据库、raw、FIT、token、凭据及整个
  `data-backup/`，反向允许 README、examples、`.gitkeep`。

### M4-0002：Foundation v4 离线 Garmin 重建

- 候选库只读取 `active raw ∪ backup-only raw ∪ legacy FIT`，按字节 SHA-256 去重，按
  Provider 身份和 revision 顺序重放 inventory、summary、FIT、weather、健康、睡眠和
  physiology。
- 新库只保留 Garmin 健康/活动事实、覆盖/cursor/gap/lifecycle 和必要来源闭包；不迁移
  旧 AI 报告、计划、邮件、用户事实、交付或运行历史。
- 无法唯一绑定的 legacy FIT 只归档并登记缺口，禁止猜测。
- 完整性、外键、哈希、来源闭包、权限和只读验证通过后，旧 `state/config/logs` 与旧库
  原子归档到 `data-backup/<timestamp>/`；正式配置/凭据只迁入 `source/`，
  `orchestration.yaml` 仅归档。

### M4-0003：运行时教练 Harness v2

- 运行时资源位于 `source/src/resources/harness/`；跑步、攀岩、休息统一进入七日计划，
  每日最多一项主课，首版不单独安排力量课。
- 新增 `coaching_profile_contract_v1` 和 `course_contract_v2`：课程剂量、步骤唯一结束
  条件、数值配速/心率/RPE、目标、guardrail、停止/降级、恢复成本和 Garmin 映射状态
  均为结构化字段；攀岩始终 `unsupported_skip`。
- 日报严格区分 D-1 非睡眠复盘、D 夜间唯一已结束主睡眠和 D 当日周计划 item；睡眠样本
  采用半开区间，nap/未结束/多主睡眠明确缺失或歧义，日报只评估不修改正式计划。
- 周报覆盖完整周一至周日，缺少周日数据则延后；输出 `advance/hold/deload`，一次只
  改变容量或强度一个维度。

### M4-0004：原子切换与独立验证

- 在没有产品写进程时完成候选切换前后的路径、权限、属主、摘要、SQLite 完整性、入口、
  schema、隐私和 Git ignore 验证。
- 在仓库外全新 Python 3.12 环境中从锁文件安装依赖；从任意工作目录运行 `source/index.py`
  的帮助和只读 Foundation 状态，不执行 Garmin/Gmail/分析/邮件/Supervisor。
- 完整 pytest、repository quality、Ruff/format、mypy、compile、schema、shell 和隐私
  扫描全部通过；由全新只读 Validator 最终 `PASS` 后才归档计划。

## 当前状态

| 任务 | 状态 | 证据/下一步 |
| --- | --- | --- |
| M4-0001 | `completed` | source 迁移、入口、CI、ignore 和历史运行层清理已完成；独立 Validator PASS |
| M4-0002 | `completed` | Foundation v4 候选已重建：active raw 27344 + backup-only 44，4 个 legacy FIT 登记为 unresolved 缺口；schema/完整性/来源闭包/权限检查通过 |
| M4-0003 | `completed` | course/profile/sleep/负荷合同已接入结果 schema 与生产 Validator；独立 Validator PASS |
| M4-0004 | `completed` | source/state 已原子切换，入口、只读状态、静态门和完整 pytest 已通过；独立 Validator PASS |

## 变更范围

允许写入根治理/CI 文件，以及 `source/` 产品代码、测试、配置说明、脚本和工具；允许将
旧私有实例目录移动到 `data-backup/` 或候选临时目录。禁止写入用户级 Skill、远端 Git、
Garmin/Gmail、生产服务和正式邮件。

## 独立验证

任务级和最终级 Validator 必须是未参与实现的全新只读 Agent。Validator 返回 `PASS`、
`FAIL` 或 `INCONCLUSIVE`，并提供实际命令、观察和未满足项；主协调 Agent 不得以自检替代。

## 迭代日志

| 日期 | 事实 | 下一动作 |
| --- | --- | --- |
| 2026-08-13 | 根布局、source 入口、历史层清理和 Foundation v4 候选已完成 | 修复兼容迁移门禁并完成 Harness v2 回归 |
| 2026-08-13 | 重建器补齐 backup-only raw、legacy FIT 缺口与递归权限；课程合同接入结果校验；完整 pytest 明确 exit=0 | 等待全新只读 Validator；不以历史 mypy 错误为绿灯 |
| 2026-08-13 | 教练 profile 已进入所有分析控制上下文，weekly/revision 安全门读取 host profile 并以 host 证据生成进阶决定；安全归一化后重新生成 course contract；完整 pytest r04 exit=0，静态门通过；根凭据原字节迁入 source/ 并保持 0600，source/state 与 data-backup 普通节点均收紧为 owner-only | 等待全新 Validator；全量 mypy 仍记录为 656 条既有诊断，不修改配置隐藏 |
| 2026-08-13 | 日报新增主机侧今日计划绑定与无计划保守回退；修订路径接入 profile 驱动的硬负荷/进阶门；课程合同生成器补齐热身、主训练、恢复/冷身步骤和可用配速/距离字段；离线重建库清空旧 Garmin 采集 run/item 历史；smoke worker 改由 `source/index.py` 隐藏路由启动；新活动数据库已验证 schema4、raw 27388 闭包、采集历史 0 行；完整 pytest r06 到 100% 并退出 0（2550 个通过标记），Ruff/format/quality/schema/layout/compile 通过 | 交给全新只读 Validator；全量 mypy 仍报告 658 条诊断，不能豁免 |
| 2026-08-13 | 独立 Validator 复核全量 mypy：`mypy src tools` 660 项、`mypy .` 1180 项诊断；归档原有 125 个测试临时软链接已封存为 `legacy-symlinks.tar` 并从活动归档树移除，主库与 source/state 未改动 | 保持 M4 blocked；不得用排除、忽略或删测弱化 mypy；等待用户决定是否批准专门的类型修复阶段 |
| 2026-08-14 | 按批准的 M4 运行源码类型门禁修复完成：`mypy src` 从 658 项降为 0；新增边界收窄、畸形分析输入领域错误、SQLite lastrowid 校验、Garmin Host/Protocol、第三方最小类型声明及锁文件更新；聚焦回归与唯一最终完整 pytest 均通过（2555 passed，exit 0），静态门全部通过 | 交给全新只读 Validator；不扩大到 tests/tools 的约 522 项类型债，不调用外部服务，不提交或推送 |
| 2026-08-14 | 独立 Validator PASS：`mypy src` 100 个源码文件 0 diagnostics；当前快照唯一完整 pytest r02 为 2555 passed、exit 0；Ruff/format/compile/schema/quality/pip/layout 全绿；新增 `PendingDeliveryFactory` 精确 Protocol 无 `cast(Any)`，tests/tools 类型债仅登记 TD-0001 | 归档 M4 计划，清除活动计划指针；等待用户另行决定是否提交 |
