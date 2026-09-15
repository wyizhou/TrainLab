# 执行计划：M4 `source/` 工程、健康数据重建与教练 Harness v2

## 对应目标

- 功能编号：M4
- 功能状态：[completed]
- 总计划对应条目：[PLAN.md](../../PLAN.md) 的同编号/原Roadmap关联条目。
- 目标及范围和验收要求的引用：历史目标、范围、每个阶段/任务、验收要求及全部执行证据按对应原件保存；不是新的实施授权。
- 迁移说明：只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 当前协作规则仅以[AGENTS.md](../../AGENTS.md)为准；原合同及旧规范在快照中仅作历史来源，不继续生效为第二套流程。

## 阶段与任务

以下逐项迁移原实施分解；任务名称、已有编号、结果及明确依赖保留。原无编号步骤按原表顺序首次赋予L编号，不重编号已有步骤。HISTORY仅是原单阶段的归组，不再替代实际任务。此表描述历史工作，不是当前可执行规范/示例或外部授权；暂停条件见检查点。

| 阶段编号 | 状态 | 预期成果 | 依赖 |
| --- | --- | --- | --- |
| HISTORY | [completed] | 当前状态；保留原逐项成果/未完成边界 | 原前置要求及总计划同编号依赖；未另列的依赖不新增 |

| 任务编号 | 所属阶段 | 状态 | 输入输出及错误边界 | 依赖 | 检查方法 | 结果与证据（检查命令或人工方式、退出结果及关键证据） |
| --- | --- | --- | --- | --- | --- | --- |
| M4-0001 | HISTORY | [completed] | M4-0001；原任务标题：M4-0001：工程布局与历史运行层清理；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收)；[本任务原定义L34](#原定义-l34) | 原Roadmap同编号依赖：M3、ADHOC-0008；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收)；[本任务原定义L34](#原定义-l34) | 原记录：证据/下一步：source 迁移、入口、CI、ignore 和历史运行层清理已完成；独立 Validator PASS；原完成范围不扩大；对应原执行计划 L83 |
| M4-0002 | HISTORY | [completed] | M4-0002；原任务标题：M4-0002：Foundation v4 离线 Garmin 重建；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收)；[本任务原定义L46](#原定义-l46) | 原Roadmap同编号依赖：M4-0001；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收)；[本任务原定义L46](#原定义-l46) | 原记录：证据/下一步：Foundation v4 候选已重建：active raw 27344 + backup-only 44，4 个 legacy FIT 登记为 unresolved 缺口；schema/完整性/来源闭包/权限检查通过；原完成范围不扩大；对应原执行计划 L84 |
| M4-0003 | HISTORY | [completed] | M4-0003；原任务标题：M4-0003：运行时教练 Harness v2；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收)；[本任务原定义L58](#原定义-l58) | 原Roadmap同编号依赖：M4-0002；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收)；[本任务原定义L58](#原定义-l58) | 原记录：证据/下一步：course/profile/sleep/负荷合同已接入结果 schema 与生产 Validator；独立 Validator PASS；原完成范围不扩大；对应原执行计划 L85 |
| M4-0004 | HISTORY | [completed] | M4-0004；原任务标题：M4-0004：原子切换与独立验证；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收)；[本任务原定义L70](#原定义-l70) | 原Roadmap同编号依赖：M4-0003；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收)；[本任务原定义L70](#原定义-l70) | 原记录：证据/下一步：source/state 已原子切换，入口、只读状态、静态门和完整 pytest 已通过；独立 Validator PASS；原完成范围不扩大；对应原执行计划 L86 |

## 当前检查点

- 工作目录与分支：项目根；本次格式迁移在work/adhoc-0029-agentsmd-upgrade，原执行目录/分支仅见历史证据。
- 验收要求与受验版本及未提交改动：本轮迁移基准ec36ce7bbdf9d70a509238dd771b155eb6f84261；原受验版本/未提交内容/合同全文保留于快照。不得把迁移HEAD当作原产品受验版本。
- 最近完成：仅迁移当前记录结构与路径；只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。
- 下一动作：保留历史定位，不恢复原业务或重判历史结果。
- 暂停原因：无新的暂停；历史已完成范围只作记录，不是当前运行证明。
- 恢复条件：已完成范围不需重做；已取消/暂停部分不在当前待办，恢复前须用户另行明确目标/授权并核对原失败次数。
- PR 与交付情况：本轮只迁移记录，不提交/推送/PR。原Git交付事实及未知项保留于原件，不推断后续远端状态。

## 问题记录

原有明确问题编号保留；无编号记录首次按不可变源行号分配ISSUE-L编号。每行是原记录索引，可能含规范、观察、裁决或后续动作；重复引用不重新累计事件，也不把原未量化的计数清零。

| 稳定问题编号 | 对应要求与实际问题 | 已尝试修法 | 累计失败次数 | 证据及处理结果 |
| --- | --- | --- | --- | --- |
| ISSUE-L97 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | `FAIL` 或 `INCONCLUSIVE`，并提供实际命令、观察和未满足项；主协调 Agent 不得以自检替代。；原件L97 |

## 历史目标与原编号索引

下文仅引用当时目标，不是现行规范或可运行示例；已经被新方案替代的业务不复活。原阶段/任务已在上表逐项迁移；原早期状态与最终范围不同的映射依据逐项标明，不借迁移扩大历史完成范围。

> 建立单一 `source/` 产品工程：根目录只保留 agentForge 开发 Harness、Git/CI 元数据和
> 项目治理文件；`source/src/` 是唯一产品包，`source/index.py` 是唯一直接入口；旧
> Orchestration/Supervisor/后台部署和 wheel/bundle 构建链不再属于产品。旧运行数据不删除，
> 而是完整归档到被 Git 忽略的 `data-backup/`。在此基础上建立不含 Orchestration 表的
> Foundation v4 离线重建库，并把运行时教练 Harness 升级为课程、睡眠、负荷和进阶均有
> 结构化合同的 v2。

原阶段/任务及其结果见上表，原问题及计数见问题记录；额外来源标识仍可在迁移清单中检索，原件供逐行核对。

## 原任务定义与验收

本节承接原任务定义的全部内容，而非仅保留状态摘要或指向压缩包。上表每个原任务的输入输出/错误边界及检查方法均关联本节；原文有同编号专属标题时另外关联该精确段落，公共目标/范围/合同与其他定义完整保留在本节。不得把原表中的“已接入/PASS”当作完整定义。

**适用性：全部引文均属于该历史任务的原目标、合同修订和执行记录，不是当前开发协议、可运行示例或新的业务授权。** 多版本材料按原任务编号、版本和日期定位，不把后续规则回套早期结果。旧流程/命令/目录和“当前”措辞只描述原记录时点；根AGENTS是唯一现行协作规则，暂停/取消按本文件的新检查点处理，不恢复旧产品。

为保留可核查语义，原件按标题和源行完整投射为引用块；只增加引用前缀，并将旧Markdown导航链接显示为“原定位”文字，未更改原件。原字节/原哈希由history.zip及history-manifest.json证明，不把显示投射声称为原字节。全部源行连续覆盖，原始执行/协调记录也标为历史数据，不混入当前阶段状态。

### 原定义-L1

来源标题：原文导言；原件L1–L9。

> # 执行计划：M4 `source/` 工程、健康数据重建与教练 Harness v2
>
> - 状态：`completed`
> - 负责人：主协调 Agent
> - Roadmap ID：`M4`
> - 批次：严格串行（M4-0001 → M4-0002 → M4-0003 → M4-0004）
> - 开始日期：2026-08-13
> - 最后更新：2026-08-14
>

### 原定义-L10

来源标题：目标；原件L10–L18。

> ## 目标
>
> 建立单一 `source/` 产品工程：根目录只保留 agentForge 开发 Harness、Git/CI 元数据和
> 项目治理文件；`source/src/` 是唯一产品包，`source/index.py` 是唯一直接入口；旧
> Orchestration/Supervisor/后台部署和 wheel/bundle 构建链不再属于产品。旧运行数据不删除，
> 而是完整归档到被 Git 忽略的 `data-backup/`。在此基础上建立不含 Orchestration 表的
> Foundation v4 离线重建库，并把运行时教练 Harness 升级为课程、睡眠、负荷和进阶均有
> 结构化合同的 v2。
>

### 原定义-L19

来源标题：硬边界；原件L19–L31。

> ## 硬边界
>
> - 不加载或调用 `orchestrate-parallel-work`，不创建 Graph、Dashboard、handoff digest 或
>   连续审批版本。
> - 本计划不调用 Garmin/Gmail，不认证、不补数、不分析、不发邮件、不启动 Supervisor，
>   不提交、不推送、不部署。
> - 私有 `source/config`、`source/state`、`source/logs`、凭据、数据库、raw、FIT 和
>   `data-backup/` 只做受控本地迁移或候选重建，内容不输出、不进 Git。
> - 旧 Orchestration 数据不在本计划物理删除；归档目录保留回滚和审计证据。新库不创建
>   七张 Orchestration 表和两个视图。
> - 运行时 Harness 只能接收有界、带 schema 和来源 lineage 的 JSON；模型不得自行读取
>   数据库、FIT、聊天、网络或凭据。
>

### 原定义-L32

来源标题：串行任务与验收；原件L32–L33。

> ## 串行任务与验收
>

### 原定义-L34

来源标题：M4-0001：工程布局与历史运行层清理；原件L34–L45。

> ### M4-0001：工程布局与历史运行层清理
>
> - `src/trainlab/*` 已迁入 `source/src/*`，不建立 `source/src/trainlab/`。
> - `source/index.py` 预先设置默认 `TRAINLAB_INSTANCE_ROOT=source/`，尊重显式覆盖，并
>   校验实际 `src.__file__` 来自 `source/src/`。
> - 删除产品 Orchestration、Supervisor、自动调度 CLI、相关 schema/config/docs/deploy
>   和专属测试；保留 Foundation/Garmin/Analysis/Mail 的手动一次性命令。
> - 删除 wheel/runtime bundle 构建器、安装器、`dist/build/deploy` 与仓库 `.venv` 依赖。
> - CI、质量脚本和文档均从 `source/` 工作；锁文件仅为 `source/requirements.lock`。
> - `.gitignore` 只忽略私有配置、state、logs、数据库、raw、FIT、token、凭据及整个
>   `data-backup/`，反向允许 README、examples、`.gitkeep`。
>

### 原定义-L46

来源标题：M4-0002：Foundation v4 离线 Garmin 重建；原件L46–L57。

> ### M4-0002：Foundation v4 离线 Garmin 重建
>
> - 候选库只读取 `active raw ∪ backup-only raw ∪ legacy FIT`，按字节 SHA-256 去重，按
>   Provider 身份和 revision 顺序重放 inventory、summary、FIT、weather、健康、睡眠和
>   physiology。
> - 新库只保留 Garmin 健康/活动事实、覆盖/cursor/gap/lifecycle 和必要来源闭包；不迁移
>   旧 AI 报告、计划、邮件、用户事实、交付或运行历史。
> - 无法唯一绑定的 legacy FIT 只归档并登记缺口，禁止猜测。
> - 完整性、外键、哈希、来源闭包、权限和只读验证通过后，旧 `state/config/logs` 与旧库
>   原子归档到 `data-backup/<timestamp>/`；正式配置/凭据只迁入 `source/`，
>   `orchestration.yaml` 仅归档。
>

### 原定义-L58

来源标题：M4-0003：运行时教练 Harness v2；原件L58–L69。

> ### M4-0003：运行时教练 Harness v2
>
> - 运行时资源位于 `source/src/resources/harness/`；跑步、攀岩、休息统一进入七日计划，
>   每日最多一项主课，首版不单独安排力量课。
> - 新增 `coaching_profile_contract_v1` 和 `course_contract_v2`：课程剂量、步骤唯一结束
>   条件、数值配速/心率/RPE、目标、guardrail、停止/降级、恢复成本和 Garmin 映射状态
>   均为结构化字段；攀岩始终 `unsupported_skip`。
> - 日报严格区分 D-1 非睡眠复盘、D 夜间唯一已结束主睡眠和 D 当日周计划 item；睡眠样本
>   采用半开区间，nap/未结束/多主睡眠明确缺失或歧义，日报只评估不修改正式计划。
> - 周报覆盖完整周一至周日，缺少周日数据则延后；输出 `advance/hold/deload`，一次只
>   改变容量或强度一个维度。
>

### 原定义-L70

来源标题：M4-0004：原子切换与独立验证；原件L70–L78。

> ### M4-0004：原子切换与独立验证
>
> - 在没有产品写进程时完成候选切换前后的路径、权限、属主、摘要、SQLite 完整性、入口、
>   schema、隐私和 Git ignore 验证。
> - 在仓库外全新 Python 3.12 环境中从锁文件安装依赖；从任意工作目录运行 `source/index.py`
>   的帮助和只读 Foundation 状态，不执行 Garmin/Gmail/分析/邮件/Supervisor。
> - 完整 pytest、repository quality、Ruff/format、mypy、compile、schema、shell 和隐私
>   扫描全部通过；由全新只读 Validator 最终 `PASS` 后才归档计划。
>

### 原定义-L79

来源标题：当前状态；原件L79–L87。

> ## 当前状态
>
> | 任务 | 状态 | 证据/下一步 |
> | --- | --- | --- |
> | M4-0001 | `completed` | source 迁移、入口、CI、ignore 和历史运行层清理已完成；独立 Validator PASS |
> | M4-0002 | `completed` | Foundation v4 候选已重建：active raw 27344 + backup-only 44，4 个 legacy FIT 登记为 unresolved 缺口；schema/完整性/来源闭包/权限检查通过 |
> | M4-0003 | `completed` | course/profile/sleep/负荷合同已接入结果 schema 与生产 Validator；独立 Validator PASS |
> | M4-0004 | `completed` | source/state 已原子切换，入口、只读状态、静态门和完整 pytest 已通过；独立 Validator PASS |
>

### 原定义-L88

来源标题：变更范围；原件L88–L93。

> ## 变更范围
>
> 允许写入根治理/CI 文件，以及 `source/` 产品代码、测试、配置说明、脚本和工具；允许将
> 旧私有实例目录移动到 `data-backup/` 或候选临时目录。禁止写入用户级 Skill、远端 Git、
> Garmin/Gmail、生产服务和正式邮件。
>

### 原定义-L94

来源标题：独立验证；原件L94–L98。

> ## 独立验证
>
> 任务级和最终级 Validator 必须是未参与实现的全新只读 Agent。Validator 返回 `PASS`、
> `FAIL` 或 `INCONCLUSIVE`，并提供实际命令、观察和未满足项；主协调 Agent 不得以自检替代。
>

### 原定义-L99

来源标题：迭代日志；原件L99–L109。

> ## 迭代日志
>
> | 日期 | 事实 | 下一动作 |
> | --- | --- | --- |
> | 2026-08-13 | 根布局、source 入口、历史层清理和 Foundation v4 候选已完成 | 修复兼容迁移门禁并完成 Harness v2 回归 |
> | 2026-08-13 | 重建器补齐 backup-only raw、legacy FIT 缺口与递归权限；课程合同接入结果校验；完整 pytest 明确 exit=0 | 等待全新只读 Validator；不以历史 mypy 错误为绿灯 |
> | 2026-08-13 | 教练 profile 已进入所有分析控制上下文，weekly/revision 安全门读取 host profile 并以 host 证据生成进阶决定；安全归一化后重新生成 course contract；完整 pytest r04 exit=0，静态门通过；根凭据原字节迁入 source/ 并保持 0600，source/state 与 data-backup 普通节点均收紧为 owner-only | 等待全新 Validator；全量 mypy 仍记录为 656 条既有诊断，不修改配置隐藏 |
> | 2026-08-13 | 日报新增主机侧今日计划绑定与无计划保守回退；修订路径接入 profile 驱动的硬负荷/进阶门；课程合同生成器补齐热身、主训练、恢复/冷身步骤和可用配速/距离字段；离线重建库清空旧 Garmin 采集 run/item 历史；smoke worker 改由 `source/index.py` 隐藏路由启动；新活动数据库已验证 schema4、raw 27388 闭包、采集历史 0 行；完整 pytest r06 到 100% 并退出 0（2550 个通过标记），Ruff/format/quality/schema/layout/compile 通过 | 交给全新只读 Validator；全量 mypy 仍报告 658 条诊断，不能豁免 |
> | 2026-08-13 | 独立 Validator 复核全量 mypy：`mypy src tools` 660 项、`mypy .` 1180 项诊断；归档原有 125 个测试临时软链接已封存为 `legacy-symlinks.tar` 并从活动归档树移除，主库与 source/state 未改动 | 保持 M4 blocked；不得用排除、忽略或删测弱化 mypy；等待用户决定是否批准专门的类型修复阶段 |
> | 2026-08-14 | 按批准的 M4 运行源码类型门禁修复完成：`mypy src` 从 658 项降为 0；新增边界收窄、畸形分析输入领域错误、SQLite lastrowid 校验、Garmin Host/Protocol、第三方最小类型声明及锁文件更新；聚焦回归与唯一最终完整 pytest 均通过（2555 passed，exit 0），静态门全部通过 | 交给全新只读 Validator；不扩大到 tests/tools 的约 522 项类型债，不调用外部服务，不提交或推送 |
> | 2026-08-14 | 独立 Validator PASS：`mypy src` 100 个源码文件 0 diagnostics；当前快照唯一完整 pytest r02 为 2555 passed、exit 0；Ruff/format/compile/schema/quality/pip/layout 全绿；新增 `PendingDeliveryFactory` 精确 Protocol 无 `cast(Any)`，tests/tools 类型债仅登记 TD-0001 | 归档 M4 计划，清除活动计划指针；等待用户另行决定是否提交 |

## 历史来源与证据

- [不可变原件快照](../evidence/ADHOC-0029/history.zip)，条目`docs/exec-plans/completed/M4-source-root-0001-product-consolidation.md`，原SHA-256：`73f3d5d6a30dc57f414d32e05eb3539ad17fcd4ac9c6a86a6ca96659156c548d`。
- [来源清单](../evidence/ADHOC-0029/history-manifest.json)、[迁移/编号映射](../evidence/ADHOC-0029/migration-manifest.json)、[原问题与失败计数索引](../evidence/ADHOC-0029/failure-index.json)。原记录中的绝对路径和失效外部证据只说明当时事实，不据此复建旧路径。
- 历史快照仅用于保真审查，不作为现行规范、产品导入、Schema、AI输入或CI运行依赖。当前实际迁移验收见[ADHOC-0029](../completed/ADHOC-0029-agentsmd-upgrade.md)。
