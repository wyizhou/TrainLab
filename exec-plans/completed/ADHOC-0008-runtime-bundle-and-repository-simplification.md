# 执行计划：简化 TrainLab 仓库并形成单一可部署产物

## 对应目标

- 功能编号：ADHOC-0008
- 功能状态：[completed]
- 总计划对应条目：[PLAN.md](../../PLAN.md) 的同编号/原Roadmap关联条目。
- 目标及范围和验收要求的引用：历史目标、范围、每个阶段/任务、验收要求及全部执行证据按对应原件保存；不是新的实施授权。
- 迁移说明：只保留原授权范围内的历史完成结论，不表示删除旧源码后仍能运行或本轮重新验收。 当前协作规则仅以[AGENTS.md](../../AGENTS.md)为准；原合同及旧规范在快照中仅作历史来源，不继续生效为第二套流程。

## 阶段与任务

以下逐项迁移原实施分解；任务名称、已有编号、结果及明确依赖保留。原无编号步骤按原表顺序首次赋予L编号，不重编号已有步骤。HISTORY仅是原单阶段的归组，不再替代实际任务。此表描述历史工作，不是当前可执行规范/示例或外部授权；暂停条件见检查点。

| 阶段编号 | 状态 | 预期成果 | 依赖 |
| --- | --- | --- | --- |
| HISTORY | [completed] | 工作分解；保留原逐项成果/未完成边界 | 原前置要求及总计划同编号依赖；未另列的依赖不新增 |

| 任务编号 | 所属阶段 | 状态 | 输入输出及错误边界 | 依赖 | 检查方法 | 结果与证据（检查命令或人工方式、退出结果及关键证据） |
| --- | --- | --- | --- | --- | --- | --- |
| L01 | HISTORY | [completed] | 停止旧生产监测与 Supervisor，冻结私有状态；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：heartbeat 已删除；LaunchAgent 未加载；Supervisor 进程 0；原完成范围不扩大；对应原执行计划 L83 |
| L02 | HISTORY | [completed] | 对照 agentForge 并审计目录、引用、运行依赖与发布边界；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：上游 v0.4.2/main 固定提交已核验；三项只读审计已返回；原完成范围不扩大；对应原执行计划 L84 |
| L03 | HISTORY | [completed] | 冻结目标目录与 bundle 合同，先补测试；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：wheel=代码+不可变资源；bundle=wheelhouse+部署资产；instance root=私有配置/状态/日志；已新增 runtime-resources 合同测试；原完成范围不扩大；对应原执行计划 L85 |
| L04 | HISTORY | [completed] | 串行迁移资源、清理历史、更新构建/CI/文档；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：产品资源已进入 wheel；临时 `product/`、旧 runtime Harness、egg-info、旧 live driver、legacy 文档和空 design 已移除；原完成范围不扩大；对应原执行计划 L86 |
| L05 | HISTORY | [completed] | 运行聚焦、静态、完整测试和全新 bundle 验证；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：最新返工聚焦 131 项通过；repository quality、Ruff/format、维护 mypy、31 个 `$schema` 项目 schema、shell/plist/diff 通过；双构建 wheel/bundle/verifier/manifest 字节一致；离线安装与仓库外启动通过；原完成范围不扩大；对应原执行计划 L87 |
| L06 | HISTORY | [completed] | 全新独立 Validator 与完成审计；边界不超出原目标/授权；定义：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原表未单列；沿用原功能前置条件，不按编号新增依赖；[原明示前置/依赖及对应时点](#原任务定义与验收) | 核对原记录的验证方式/实际结果及源文件同编号验收；本轮不执行历史命令；验收依据：[原目标、输入输出、排除范围及错误/验收定义](#原任务定义与验收) | 原记录：证据：第三位 Validator PASS：完整 pytest 唯一运行一次 exit 0；结构、隐私、静态、双构建、对抗解包和离线安装均通过；原完成范围不扩大；对应原执行计划 L88 |

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
| ISSUE-L75 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | &#124; 1 &#124; Validator / final &#124; 高风险结构迁移 &#124; high &#124; high &#124; 必须独立覆盖结构、测试与隐私 &#124; supported &#124; 只读 &#124; PASS/FAIL/INCONCLUSIVE &#124; FAIL；3728 passed/9 failed，并发现解包前资产白名单与 instance root cwd 回退两项边界缺口 &#124;；原件L75 |
| ISSUE-L138 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | &#124; 2026-08-13 / Loop 6 &#124; 首次 Validator 完成 3737 项完整测试、真实双构建/离线安装与对抗性 bundle/instance-root 检查 &#124; 9 项兼容测试失败；runtime asset 解包前白名单不完整；instance root 仍接受 cwd markers &#124; 在同一计划内修复三类缺口，重跑门禁并换新 Validator &#124;；原件L138 |
| ISSUE-L139 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | &#124; 2026-08-13 / Loop 7 &#124; 返工聚焦与静态门通过；双构建产物逐字节一致；全新外部实例离线安装、仓库外 CLI、cwd 拒绝和隔离 HOME LaunchAgent no-start 通过 &#124; 一次手工验收参数顺序错误在真实 HOME 生成未加载 plist；已立即移入 `/private/tmp` 隔离并确认服务未加载，随后隔离 HOME 验收通过 &#124; 启动第二位全新只读 Validator 做完整最终复核 &#124;；原件L139 |
| ISSUE-L141 | 原要求/观察/裁决逐条记录；见本行源原文，不将规则或下一动作当发生事实 | 原行未单列修法则不推断；全部尝试/动作保留于右列及原上下文 | 原行未给统一累计值；保留原次数表述，不置0或按索引条数计次数 | &#124; 2026-08-13 / Loop 9 &#124; 15 项失败对应聚焦 131 passed；静态门全绿；双构建 wheel `995b18…`、bundle `05c272…` 逐字节一致；显式匹配 Python 的离线安装/仓库外 CLI/隔离 LaunchAgent 通过 &#124; 一次 schema 枚举误用全仓 `rglob`，在解析到非 JSON 文件时停止；命令可能越过允许的产品 schema 目录读取未知 JSON，未输出内容，随后改为仅枚举 `src/tests/deploy/tools` 并确认 31 项 &#124; 第三位全新只读 Validator 做最终完整复核 &#124;；原件L141 |

## 历史目标与原编号索引

下文仅引用当时目标，不是现行规范或可运行示例；已经被新方案替代的业务不复活。原阶段/任务已在上表逐项迁移；原早期状态与最终范围不同的映射依据逐项标明，不借迁移扩大历史完成范围。

> - 对照 agentForge `v0.4.2` 固定提交 `ccc934ece6b7b64368c08bc3ce431678511ecfa3`，保持根开发 Harness 正确且职责单一。
> - 解释并收敛 `src/`、产品 Harness、配置、部署、脚本、文档和历史文件边界；删除或迁移无运行价值的生成物、重复物和过时物。
> - `src/trainlab/` 保持唯一 Python 产品实现；移除生成的第二目录 `src/trainlab.egg-info/`，并防止其再次污染源码树。
> - 不要求用户直接压缩裸 `src/`；由一个明确构建入口生成可直接部署、可验证、无私有数据的单一 runtime bundle，并同时保留标准 wheel。
> - runtime bundle 必须自包含运行所需的产品代码、产品 Harness、公开静态配置/模板、部署入口和锁定依赖说明；部署时不得再手工拼接根目录。
> - 私有 `state/`、日志、凭据和本机配置必须与 bundle 分离；构建和解包扫描遇到数据库、raw、FIT、token、凭据、开发计划或历史控制面即失败。
> - CI、README、runbook、质量脚本、测试和构建合同与最终边界一致；不存在第二份产品实现或已废弃的 `product/` 运行依赖。
> - 所有适用静态门、聚焦/完整测试、全新临时安装与 bundle smoke test 通过，并由全新只读独立 Validator `PASS`。

原阶段/任务及其结果见上表，原问题及计数见问题记录；额外来源标识仍可在迁移清单中检索，原件供逐行核对。

## 原任务定义与验收

本节承接原任务定义的全部内容，而非仅保留状态摘要或指向压缩包。上表每个原任务的输入输出/错误边界及检查方法均关联本节；原文有同编号专属标题时另外关联该精确段落，公共目标/范围/合同与其他定义完整保留在本节。不得把原表中的“已接入/PASS”当作完整定义。

**适用性：全部引文均属于该历史任务的原目标、合同修订和执行记录，不是当前开发协议、可运行示例或新的业务授权。** 多版本材料按原任务编号、版本和日期定位，不把后续规则回套早期结果。旧流程/命令/目录和“当前”措辞只描述原记录时点；根AGENTS是唯一现行协作规则，暂停/取消按本文件的新检查点处理，不恢复旧产品。

为保留可核查语义，原件按标题和源行完整投射为引用块；只增加引用前缀，并将旧Markdown导航链接显示为“原定位”文字，未更改原件。原字节/原哈希由history.zip及history-manifest.json证明，不把显示投射声称为原字节。全部源行连续覆盖，原始执行/协调记录也标为历史数据，不混入当前阶段状态。

### 原定义-L1

来源标题：原文导言；原件L1–L11。

> # 执行计划：简化 TrainLab 仓库并形成单一可部署产物
>
> - 状态：`completed`
> - 负责人：主协调 Agent
> - Roadmap ID：`ADHOC-0008`
> - 阶段/子项目：`不适用`
> - Batch ID：`audit-parallel-then-serial-implementation`
> - 返工来源：`无`
> - 开始日期：2026-08-13
> - 最后更新：2026-08-13
>

### 原定义-L12

来源标题：目标与验收标准；原件L12–L22。

> ## 目标与验收标准
>
> - 对照 agentForge `v0.4.2` 固定提交 `ccc934ece6b7b64368c08bc3ce431678511ecfa3`，保持根开发 Harness 正确且职责单一。
> - 解释并收敛 `src/`、产品 Harness、配置、部署、脚本、文档和历史文件边界；删除或迁移无运行价值的生成物、重复物和过时物。
> - `src/trainlab/` 保持唯一 Python 产品实现；移除生成的第二目录 `src/trainlab.egg-info/`，并防止其再次污染源码树。
> - 不要求用户直接压缩裸 `src/`；由一个明确构建入口生成可直接部署、可验证、无私有数据的单一 runtime bundle，并同时保留标准 wheel。
> - runtime bundle 必须自包含运行所需的产品代码、产品 Harness、公开静态配置/模板、部署入口和锁定依赖说明；部署时不得再手工拼接根目录。
> - 私有 `state/`、日志、凭据和本机配置必须与 bundle 分离；构建和解包扫描遇到数据库、raw、FIT、token、凭据、开发计划或历史控制面即失败。
> - CI、README、runbook、质量脚本、测试和构建合同与最终边界一致；不存在第二份产品实现或已废弃的 `product/` 运行依赖。
> - 所有适用静态门、聚焦/完整测试、全新临时安装与 bundle smoke test 通过，并由全新只读独立 Validator `PASS`。
>

### 原定义-L23

来源标题：范围与非目标；原件L23–L30。

> ## 范围与非目标
>
> - 允许写入：根开发 Harness 的事实性说明；`src/trainlab/` 资源加载；`harness/`、公开 `config/`、`deploy/`、`scripts/`、`tools/`、`tests/`、CI、README/runbook、ignore、项目描述和历史资料清理。
> - 允许删除/迁移：仓库内确认无用的生成物、缓存、旧布局残留、重复或过时文档与无消费者脚本；删除前必须有引用/运行依赖证据。
> - 禁止写入或展示：`state/` 数据、数据库内容、raw/FIT、token、凭据、邮件和健康内容；不改变这些文件字节。
> - 不启动 Supervisor，不执行 Garmin、分析或 Gmail 生产操作；不部署、不发布、不推送、不提交、不创建或切换分支。
> - 不把 agentForge 开发 Harness 打进产品 bundle，也不把所有运行资源粗暴塞进 Python 模块而破坏可维护性。
>

### 原定义-L31

来源标题：适用规则与参考资料；原件L31–L37。

> ## 适用规则与参考资料
>
> - 已批准规则：A-001、A-002（未被替代部分）、A-003、A-004。
> - 上游依据：agentForge `v0.4.2` README、AGENTS、exec-plan 模板与根 `src/`/`tests/` 布局。
> - 产品依据：`src/trainlab/resources/harness/shared/HARNESS.md`、项目 `pyproject.toml`、构建器、部署 runbook 和当前运行路径实现。
> - 按需读取的 references：无；根 references 保持用户主动维护原则。
>

### 原定义-L38

来源标题：依赖与隔离；原件L38–L47。

> ## 依赖与隔离
>
> - 显式依赖：M2 根布局迁移、M3 合成 FIT 迁移；当前未提交迁移结果必须完整保留。
> - 共享接口和冻结依据：Python 包资源 API、`TRAINLAB_INSTANCE_ROOT`、Foundation 配置 schema、wheel/runtime bundle manifest、现有 CLI。
> - 任务分支：`不适用——用户未授权创建或切换分支`
> - Worktree：`不适用——在当前未提交迁移结果上串行收口；只读审计可并行`
> - 集成分支：`不适用`
> - 允许写入范围：见“范围与非目标”。
> - 禁止写入范围：生产私有数据、仓库外凭据、全局 Skill、远端 Git 和发布系统。
>

### 原定义-L48

来源标题：功能与测试映射；原件L48–L55。

> ## 功能与测试映射
>
> | 功能 | Feature slug | 测试目录 | 必须满足的行为 |
> | --- | --- | --- | --- |
> | 产品资源与配置发现 | runtime-resources | `tests/runtime-resources/` 或既有相关测试 | 安装后不依赖开发仓库路径；私有配置仍外置且 fail closed |
> | 单一 runtime bundle | product-packaging | `tests/product_packaging/` | wheel 与 bundle 可在全新目录安装/运行；隐私和开发 Harness 扫描为零 |
> | 根目录边界 | root-layout | `tests/root-layout/` | 只有 `src/trainlab` 为实现；无 egg-info/product/历史控制面；CI/文档边界一致 |
>

### 原定义-L56

来源标题：工具采用情况；原件L56–L61。

> ## 工具采用情况
>
> - 可执行技术栈：Python 3.12、setuptools、POSIX shell、launchd/systemd 模板、GitHub Actions。
> - Linter 配置和命令：根 `pyproject.toml` 定义的 Ruff/format/mypy；shell `sh -n`；plist `plutil -lint`；repository quality。
> - 测试框架、定向命令和完整命令：pytest 聚焦目录；最终唯一完整 `.venv/bin/python -m pytest`；全新临时安装与 bundle smoke test。
>

### 原定义-L62

来源标题：Subagent 派发；原件L62–L78。

> ## Subagent 派发
>
> | Attempt | Agent 角色/任务 ID | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
> | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
> | 1 | Auditor / layout-history | 跨目录依赖与删除风险高 | high | high | 需区分历史、生成物与真实消费者 | supported | 只读 | 路径分类、引用证据、删除建议 | done；审计者额外读取了一份历史 Git FIT 示例文档开头，未读取当前私人数据，作为审计偏差保留 |
> | 1 | Auditor / runtime-boundary | 配置/Harness/运行根跨模块 | high | high | 需建立安装后资源依赖图 | supported | 只读 | 运行时必需清单与迁移建议 | done |
> | 1 | Auditor / packaging-deploy | 发布隐私与可移植性风险高 | high | high | 需验证 wheel/bundle/部署边界 | supported | 只读 | 构建差距、验收矩阵 | done |
> | 1 | Auditor / installed-runtime-followup | 安装后路径和旧控制面残留风险高 | high | high | 需在实现中期独立发现剩余源码回跳与旧编排依赖 | supported | 只读 | 剩余生产路径、旧控制面和部署缺口清单 | done；确认产品调度保留，定位旧 v4/v5 开发控制面夹具及 installed-runtime 缺口 |
> | 1 | Auditor / bundle-security-followup | 归档隐私、可复现性和安装合同风险高 | high | high | 需独立审计新构建器而不参与实现 | supported | 只读 | bundle 清单、wheelhouse、隐私和安全缺口清单 | done；定位 wheel/ZIP 成员验证、锁、manifest、安装原子性和 CI 真安装缺口 |
> | 1 | Worker / legacy-live-gate-cleanup | 旧开发控制面夹具横跨安全门测试 | high | high | 需保留安全回归同时彻底移除 Graph/.orchestration/handoff 语义 | supported | 仅 `tests/fixtures/garmin_live_gate.py`、`tests/fixtures/garmin_live_v4_driver.py`、`tests/fixtures/garmin_live_v5_driver.py`、`tests/test_garmin_l2_07.py` | 无私人数据的当前 live gate 夹具；聚焦 pytest、Ruff、旧控制面字符串扫描 | done；29 passed，Ruff/format 通过，旧 driver 已删除 |
> | 1 | Worker / ci-runtime-docs | CI 与使用文档需同时切换到真实安装产物 | high | high | 需把 source checkout 开发命令和 installed runtime 生产命令严格分开，并在 Linux/macOS CI 建立真实链路 | supported | 仅 `.github/workflows/ci.yml`、`README.md`、`deploy/runtime/README.md`、`docs/runbooks/macos-local-supervisor.md`、`docs/runbooks/orchestration-deployment.md`、`tests/root-layout/test_root_layout.py` | CI build→verify→extract→offline install→smoke；文档无生产 `.venv`/源码回跳；聚焦测试和 YAML/链接检查 | done；root-layout 6 passed，真实 bundle 安装链和链接门通过 |
> | 1 | Worker / installed-resource-verifier | 安装后资源完整性与已解包产物篡改风险高 | high | high | 需独立强化 runtime smoke 与 release role/path 合同，且不与构建器实现重叠 | supported | 仅 `deploy/runtime/verify-runtime`、`deploy/runtime/verify-release`、新增 `tests/runtime-resources/test_installed_runtime_verifier.py` | 遍历全部不可变资源、JSON 可解析、release role/path/extra/tamper 失败关闭；聚焦 pytest、Ruff/format、shell/Python 编译 | done；28 项 runtime-resources 通过，真实安装目录自检通过 |
> | 1 | Worker / legacy-runtime-path-cleanup | 剩余测试和恢复文档仍绑定源码 checkout/root harness | high | high | 需区分开发工具与安装后运行，清除已不存在路径而不改生产状态 | supported | 测试、restore drill 与 03～05 层文档的限定路径 | 包资源路径替换、恢复命令不依赖根 harness/PYTHONPATH/root venv；聚焦测试、repository quality、Ruff/format | done；相关可靠性/恢复测试 29 passed，冻结摘要已按最终字节更新 |
> | 1 | Validator / final | 高风险结构迁移 | high | high | 必须独立覆盖结构、测试与隐私 | supported | 只读 | PASS/FAIL/INCONCLUSIVE | FAIL；3728 passed/9 failed，并发现解包前资产白名单与 instance root cwd 回退两项边界缺口 |
> | 2 | Validator / final-recheck | 高风险结构迁移返工复核 | high | high | 首次 Validator 已定位完整测试与安装边界缺口，修复后必须由另一全新 Agent 独立复核 | supported | 只读 | 完整 pytest、解包前白名单、显式 instance root、真实双构建与离线安装 | FAIL；3724 passed/15 failed，安全/构建边界通过，剩余为 analysis snapshot 与 CLI 测试显式实例根适配 |
> | 3 | Validator / final-recheck-r02 | 高风险结构迁移最终复核 | high | high | 第二次结果已把问题收敛到测试和冻结清单兼容，修复后仍必须换新 Agent | supported | 只读 | 完整 pytest、全部静态门、真实双构建/离线安装与隐私边界 | PASS；完整 pytest 唯一运行一次 exit 0，静态/双构建/对抗解包/离线安装全部通过 |
>

### 原定义-L79

来源标题：工作分解；原件L79–L89。

> ## 工作分解
>
> | 步骤 | 状态（`pending`、`in_progress`、`blocked`、`done`） | 证据 |
> | --- | --- | --- |
> | 停止旧生产监测与 Supervisor，冻结私有状态 | `done` | heartbeat 已删除；LaunchAgent 未加载；Supervisor 进程 0 |
> | 对照 agentForge 并审计目录、引用、运行依赖与发布边界 | `done` | 上游 v0.4.2/main 固定提交已核验；三项只读审计已返回 |
> | 冻结目标目录与 bundle 合同，先补测试 | `done` | wheel=代码+不可变资源；bundle=wheelhouse+部署资产；instance root=私有配置/状态/日志；已新增 runtime-resources 合同测试 |
> | 串行迁移资源、清理历史、更新构建/CI/文档 | `done` | 产品资源已进入 wheel；临时 `product/`、旧 runtime Harness、egg-info、旧 live driver、legacy 文档和空 design 已移除 |
> | 运行聚焦、静态、完整测试和全新 bundle 验证 | `done` | 最新返工聚焦 131 项通过；repository quality、Ruff/format、维护 mypy、31 个 `$schema` 项目 schema、shell/plist/diff 通过；双构建 wheel/bundle/verifier/manifest 字节一致；离线安装与仓库外启动通过 |
> | 全新独立 Validator 与完成审计 | `done` | 第三位 Validator PASS：完整 pytest 唯一运行一次 exit 0；结构、隐私、静态、双构建、对抗解包和离线安装均通过 |
>

### 原定义-L90

来源标题：当前检查点；原件L90–L99。

> ## 当前检查点
>
> - 当前 Loop：完成归档。
> - 最近完成：第三位全新只读 Validator PASS；完整 pytest、静态、双构建、对抗解包、离线安装和仓库外运行全部通过。
> - 当前焦点：无。
> - 下一动作：等待用户决定是否提交当前迁移结果；不自动发布、部署或推送。
> - 阻塞项：无。用户确认只删除旧编排器遗留物；代码依赖审计证明 `src/trainlab/orchestration/` 是产品自动调度层而非开发编排控制面，因此保留。
> - 已变更文件：本计划；ADHOC-0007 终止状态；memory 活动指针待切换。
> - 待验证项：独立 Validator 的完整 pytest 与最终交付审计。
>

### 原定义-L100

来源标题：决策与发现；原件L100–L108。

> ## 决策与发现
>
> - agentForge 0.4.2 规定根 `src/` 与根 `tests/`，但不要求把非 Python 运行资产全部塞入 `src/`，也不预设 `dist/`；技术栈需要时应建立自己的构建产物。
> - 当前 `src/` 的第二个目录是生成的 `trainlab.egg-info`，不是第二套源码，应移除并通过构建/ignore 规则防止回归。
> - 当前 Git 状态仍处于旧 `product/` 删除、新根树未跟踪的迁移收口期；本任务必须保护这些已有改动，不把它们误判为可丢弃历史。
> - 不能直接压缩裸 `src/`：它缺少运行依赖、部署入口和实例目录合同；正式产物应为带 wheelhouse、部署资产和逐成员摘要的单一 runtime bundle。
> - `src/trainlab/resources/` 仅承载不可变产品 Harness/schema/policy/default；私有配置、state、logs、credentials 永远位于 bundle 外的 instance root。
> - 当前构建器依赖 `git ls-files --exclude-standard`，旧 `.gitignore` 的 `core.*` 会漏掉 `foundation/core.py`；已改为仅匹配仓库根 crash dump 的 `/core*`。
>

### 原定义-L109

来源标题：任务级独立验证；原件L109–L117。

> ## 任务级独立验证
>
> - 中性交接：最终目标结构、runtime bundle 合同、隐私边界和当前仓库结果。
> - Validator 身份/上下文：全新只读 Agent，未参与审计或实现。
> - 模型/推理档位：high/high。
> - 命令与观察：第三位 Validator 唯一运行完整 pytest 至 100%，exit 0；repository quality、Ruff/format、维护 mypy、31 个 `$schema` 项目 schema、shell/plist/diff 均 exit 0；双构建 wheel `995b1852…`、bundle `05c272fd…`、verifier `e56f9dea…` 逐字节一致；额外 asset 与 `state/private.db` 均在解包前拒绝；全新离线安装、仓库外 `env -i` CLI/资源 smoke 和 cwd fallback 拒绝通过。
> - 结果：`PASS`
> - 未满足项与剩余风险：本机仅验证 macOS arm64；Linux `systemd-analyze verify` 由 CI 覆盖。未提交、发布或部署。
>

### 原定义-L118

来源标题：集成级独立验证；原件L118–L121。

> ## 集成级独立验证
>
> - 结果：`不适用——只读审计并行，仓库修改由主协调 Agent 串行完成`
>

### 原定义-L122

来源标题：PLANS 回写清单；原件L122–L128。

> ## PLANS 回写清单
>
> - [x] Exec plan 已归档到 `completed/`
> - [ ] Roadmap 叶子任务：不适用——ADHOC
> - [ ] 子项目和阶段状态：不适用——ADHOC
> - [x] `memory.md` 中的活动计划指针已删除
>

### 原定义-L129

来源标题：迭代日志；原件L129–L142。

> ## 迭代日志
>
> | 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
> | --- | --- | --- | --- |
> | 2026-08-13 / Loop 1 | 停止旧 Supervisor/heartbeat；读取根与产品 Harness；核验 Git/上游 v0.4.2 | egg-info 是生成物；当前迁移未收口；裸 src 不是完整部署物 | 并行只读审计并冻结目标结构 |
> | 2026-08-13 / Loop 2 | 三项只读审计完成；新增包资源 API 与合同测试；迁移产品 Harness/schema/default；隔离 runtime Harness/egg-info | wheel 缺资源、部署依赖源码树、runtime zip 过宽；layout-history 审计存在一次历史 FIT 示例文档读取偏差 | 串行替换资源路径并重写 bundle/部署入口 |
> | 2026-08-13 / Loop 3 | Foundation/Garmin/Analysis/Mail 资源路径已切换；最小资源合同 24 项通过 | 用户表示旧 Orchestration 若不再使用可删除；产品 Layer 5 实际承担自动定时运行，不能与开发 Harness 混为一谈 | 等待是否取消产品自动调度的明确范围，同时继续非 Orchestration 路径迁移 |
> | 2026-08-13 / Loop 4 | 精确引用审计确认 `src/trainlab/orchestration/` 被 Supervisor、定时任务和跨层可靠性合同使用 | 用户的删除条件仅适用于旧 `.orchestration`/Graph/Dashboard/handoff 控制面；开发 Harness 不替代产品调度 | 保留产品调度层，继续完成安装后资源、bundle 与部署验证 |
> | 2026-08-13 / Loop 5 | 聚焦 212 passed；静态/schema/质量门全绿；同输入双构建完全一致；runtime bundle 20 wheels/35 成员；全新离线安装、全部资源 smoke、LaunchAgent no-start 和隐私扫描通过 | `src/` 现仅 `trainlab/`；bundle 不含源码 checkout、开发依赖或私有数据；旧 legacy 文档无消费者并已删除 | 启动全新只读 Validator 做完整测试与最终验收 |
> | 2026-08-13 / Loop 6 | 首次 Validator 完成 3737 项完整测试、真实双构建/离线安装与对抗性 bundle/instance-root 检查 | 9 项兼容测试失败；runtime asset 解包前白名单不完整；instance root 仍接受 cwd markers | 在同一计划内修复三类缺口，重跑门禁并换新 Validator |
> | 2026-08-13 / Loop 7 | 返工聚焦与静态门通过；双构建产物逐字节一致；全新外部实例离线安装、仓库外 CLI、cwd 拒绝和隔离 HOME LaunchAgent no-start 通过 | 一次手工验收参数顺序错误在真实 HOME 生成未加载 plist；已立即移入 `/private/tmp` 隔离并确认服务未加载，随后隔离 HOME 验收通过 | 启动第二位全新只读 Validator 做完整最终复核 |
> | 2026-08-13 / Loop 8 | 第二位 Validator：安全对抗、双构建、离线安装均通过；完整测试 3724 passed/15 failed | analysis A3-01 snapshot 未同步；Foundation/Garmin/Mail CLI 测试未提供新合同要求的显式实例根；裸 `python3.12` 可能选到平台不匹配解释器 | 同步冻结清单、向测试注入隔离实例根、文档显式 bootstrap Python，并换第三位 Validator |
> | 2026-08-13 / Loop 9 | 15 项失败对应聚焦 131 passed；静态门全绿；双构建 wheel `995b18…`、bundle `05c272…` 逐字节一致；显式匹配 Python 的离线安装/仓库外 CLI/隔离 LaunchAgent 通过 | 一次 schema 枚举误用全仓 `rglob`，在解析到非 JSON 文件时停止；命令可能越过允许的产品 schema 目录读取未知 JSON，未输出内容，随后改为仅枚举 `src/tests/deploy/tools` 并确认 31 项 | 第三位全新只读 Validator 做最终完整复核 |
> | 2026-08-13 / Loop 10 | 第三位 Validator 完整 pytest 唯一运行 exit 0；静态、31 schema、双构建、对抗解包、离线安装、仓库外运行全部 PASS | 无交付阻塞；Linux systemd 语义门留给已配置 CI | 归档计划、清除活动指针，等待用户决定是否提交 |

## 历史来源与证据

- [不可变原件快照](../evidence/ADHOC-0029/history.zip)，条目`docs/exec-plans/completed/ADHOC-0008-runtime-bundle-and-repository-simplification.md`，原SHA-256：`06390e176bd1b246b5b919b8ece115dd919062d0c998f56757f79e3ce8447c84`。
- [来源清单](../evidence/ADHOC-0029/history-manifest.json)、[迁移/编号映射](../evidence/ADHOC-0029/migration-manifest.json)、[原问题与失败计数索引](../evidence/ADHOC-0029/failure-index.json)。原记录中的绝对路径和失效外部证据只说明当时事实，不据此复建旧路径。
- 历史快照仅用于保真审查，不作为现行规范、产品导入、Schema、AI输入或CI运行依赖。当前实际迁移验收见[ADHOC-0029](../completed/ADHOC-0029-agentsmd-upgrade.md)。
