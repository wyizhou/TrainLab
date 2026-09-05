# 执行计划：适配 agentForge 最新开发脚手架

- 任务 ID：`ADHOC-0016`
- 状态：`completed`（治理实现与独立验证已完成；归档时尚未执行用户要求的后置提交/一次推送，实际结果由最终交付报告与 Git 核实）
- 负责人：主协调 Agent
- 执行方式：串行
- 开始日期：2026-09-05
- 最后更新：2026-09-05
- 批准依据：用户确认更新 TrainLab 开发脚手架，随后要求执行至完成、本地提交并向远端推送一次。
- 来源：agentForge `9964970d38df95bbd8fab53166c27c2e5648b82e`；v0.4.4 之后 main 更新，不创建新版本。

## 冻结验证合同

- 合同版本：`VC-001`
- 合同状态：`frozen`
- 冻结依据与时点：2026-09-05 用户批准本次升级计划及提交/一次推送；早于治理实现修改。
- 允许范围：根开发 AGENTS、exec-plan 协议/模板/目录说明、README、CHANGELOG、规则中的治理替代条目、memory/PLANS 的治理事实、本计划、第三方来源说明。
- 非目标：不修改 `source/`、私人文件、正式 state、M11 计划与历史输出；不执行产品重构或业务模型/Provider；不改上游，不创建分支/worktree、发布或部署。
- 适用规则：A-001～A-019 中的既有项目边界；用户本次批准的新治理流程由 A-020 明确替代旧版本与强制完整合同要求。禁止以升级名义改变训练或产品规则。

| ID | 可验证要求 | 来源 |
| --- | --- | --- |
| AC-001 | 固定上游提交；全部十项上游文件差异有采用、适配或不适用结论，不复制上游历史任务或默认 src/tests。 | 批准的升级计划 |
| AC-002 | 采用角色输入隔离、轻量/正式流程、按需模板、直接能力升级、受审快照与协调回写免重验；详细协议为唯一流程来源。 | 批准的升级计划 |
| AC-003 | 保留 source、隐私、Git、Skills、测试和外部授权边界；不改变 M11 合同、失败记录、实现或私人数据。 | 批准的升级计划 |
| AC-004 | 原工作区有仓库外 owner-only 备份与恢复清单；不丢失或纳入无关未提交产品工作。 | 批准的升级计划 |
| AC-005 | 同步来源和许可，不把 main 更新称为正式新版本；文档、链接和治理场景一致。 | 批准的升级计划 |
| AC-006 | 独立 PASS 后，只把治理更新及必要治理基线纳入本地提交，并普通推送 origin/main 一次；不强推，不将未提交产品工作一起提交。 | 用户最新提交与推送授权 |

| ID | 不变量/范围 |
| --- | --- |
| INV-001 | source、正式 state、M11 历史与无关未提交文件相对本次开始的内容和权限不变。 |
| INV-002 | 业务模型、Garmin、Gmail、Workout、Sites、cron 调用为零；允许升级来源读取、独立开发验证和明确批准的一次 Git push。 |
| TM-001 | 脏工作树覆盖/混入提交、上游默认布局覆盖项目适配、角色/合同/回写规则互相矛盾。 |
| EX-001 | 不通过本次升级重新裁决 M11 或验收任何未提交产品功能；不扩张同 UID 对抗等威胁假设。 |

| ID | 门禁 | 预期 |
| --- | --- | --- |
| GATE-001 | 上游 HEAD/差异、十文件映射、MIT 来源 | 绑定固定提交且完整 |
| GATE-002 | 工作区备份恢复、无关文件及正式 state 前后指纹 | 完全一致，备份 owner-only |
| GATE-003 | 只读/正式任务、验证输入、快照、诊断、归档六类静态场景；Markdown/围栏/链接 | 语义一致；不得降低授权、测试和独立性 |
| GATE-004 | 现有 pytest tests/code、专用 Ruff、format-check、mypy、只读 compile、全部 Schema、metadata/AI 布局 | 全部适用检查通过；不改产品以消除既有失败 |
| GATE-005 | Git 范围、隐私、ignore、权限、tracked/untracked diff；提交树及待推送历史私人文件检查 | 无私人文件、无本任务产品差异 |
| GATE-006 | 全新只读 high/high Validator，固定八字段报告 | PASS；FAIL/INCONCLUSIVE 停止，不自动扩大合同 |

| 修订 | 状态 | 内容与依据 |
| --- | --- | --- |
| VC-001 | frozen | 本次升级计划及用户随后明确授权本地提交、远程推送一次。 |

## 工作分解

| 步骤 | 状态 | 证据 |
| --- | --- | --- |
| 保护现场并固定来源 | done | 317 个跟踪/非忽略文件记录、147 项原改动保护、9350 项正式 state 指纹与恢复演练闭合 |
| 三方适配与项目约束合并 | done | 十文件映射、A-020、来源/许可；source 与 M11 历史不变 |
| 完整检查、提交树隔离与独立验证 | done | 全新最终Validator PASS；工作区909项、提交树331项及静态门全部通过 |
| 治理归档 | done | 用户要求完成后提交推送；本归档保存已完成的治理结果，不预写Git成功 |

后置 Git 交付：准备本地提交并普通推送 origin/main 一次；归档时尚未执行。实际提交ID、远端HEAD与结果在私人交付回执及最终回复核实，不为补写远端确认再次推送；失败时报告未完成的Git交付，不预称成功。

## 当前检查点

- Git 基准：`b172f95b9c6d1c01b71f3c00e447facffa55540b`；main；index 初始为空。
- 正式远端 main：`e8c13c713a41ca39cc6edf437cafc73d191b8c20`，是本地 HEAD 的祖先；有 54 个既有本地提交。普通推送将携带这些已存在历史，已向用户说明，先检查私人路径。
- 备份：仓库外 `trainlab-harness-update.*`；精确路径只记录在私人审计清单及交付消息。
- 部分根文档含旧 M11 未提交内容；工作树保持其原文，暂存以治理段精确分离。既有未提交产品功能不在本次发布范围。
- 提交包含必要的旧治理基线 A-019 与 MIT 声明，但不包含未提交 M11 产品规则 A-013～A-018、产品实现、产品状态与其历史计划；这些内容原样留在工作树。
- 阻塞项与 blocker_type：`none`；诊断状态：`not_triggered`。

## 上游差异映射

| 上游文件 | 结论 | 适配 |
| --- | --- | --- |
| AGENTS.md | adapted | 缩短入口，保留 TrainLab source、测试、Git、隐私和 Provider 边界 |
| docs/exec-plans/README.md | adapted | 采用集中执行协议与受审快照；保留项目禁用旧控制面 |
| docs/exec-plans/template.md | adapted | 必填核心加按需章节；产品测试仍是 source/tests 双层布局 |
| README.md | adapted | 只更新开发说明；保留 TrainLab 产品介绍 |
| CHANGELOG.md | adapted | 仅记录 TrainLab Unreleased，不复制上游发布历史 |
| PLANS.md | adapted | 只对齐适用完成条件，不变更产品阶段或状态 |
| memory.md | adapted | 更新稳定治理事实，不复制上游项目状态 |
| docs/exec-plans/active/README.md | adopted | 非终态目录及角色恢复边界 |
| docs/exec-plans/completed/README.md | adopted | 串行/并行/只读的适用归档条件 |
| 上游 ADHOC-0011-governance-simplification.md | not_applicable | 上游自身历史，不复制 |

## 验证与结论处理

- Validator：待派发全新只读 Agent；high/high，复杂治理适配；不继承实施上下文，只接收冻结合同、适用规则和当前结果。
- 受审快照：冻结段 SHA、HEAD、全部 tracked/untracked 清单与内容 SHA、删除/模式差异；在私人审计文件保存，Validator 独立复核。
- 返回：contract_version、overall_verdict、criterion_results、blocking_findings、advisories、scope_change_candidates、unknowns、commands_and_evidence。
- 本任务串行，不创建第二层集成验证。PASS 后真实结果/状态/归档回写不改变已验收语义。

### 最终独立验证

- `contract_version`：VC-001；冻结段SHA-256为0ebce560d43fee28074c89ebe47f2535e4630d4e3bdbdd3ab4adc0409fd8075e。算法不包含合同标题，保留标题后原始空行，止于工作分解标题前，不strip。
- `overall_verdict`：PASS。
- `criterion_results`：AC-001～005、INV-001～002、TM-001、GATE-001～006全部PASS；EX-001遵守；AC-006提交前准备、范围与安全PASS，真实Git交付留到本报告之后执行。
- `blocking_findings`：[]。
- `advisories`：既有CI的无尾斜杠data-backup目录探针在目录不存在时可返回1，尾斜杠及子文件探针正确命中；属于未修改CI的问题，非本次阻塞。不把模式扫描当作绝对秘密不存在证明；提交前再次复核范围。
- `scope_change_candidates`：[]。
- `unknowns`：报告时未提交/推送；平台没有操作系统级只读沙箱，使用只读命令、禁止修复选项、外置缓存与隔离导出；不证明历史所有进程外部调用状态。
- `commands_and_evidence`：2026-09-05，全新只读adhoc0016_final_validator，high/high；基准b172f95b9c6d1c01b71f3c00e447facffa55540b，受审树97a64fe71afc8ed103e13d35e6d1bb3740c61344；manifest SHA为b8cef6d39e5d7d80af8d3477231e8e7581bae12d06fbd4469189eb50c11c0b68，工作区清单SHA为65c709ea1ab79fec92cabe107457eae1f439fcdb420f99dd865824c0d5e6714e。全部200个提交树文件、12项治理增量、318项工作区清单核对通过。工作区909 tests（156.89秒）、提交树331 tests（75.60秒）；两套Ruff/check/format（125/74）、mypy（107/63）、compile（106/62）、JSON/Schema（90/87、40/39）、AI cases/metadata（11/6、8/6）通过；链接34/31与diff通过。149份备份恢复文件、正式state9350项验证前后不变；54个既有提交760个blob路径与强秘密模式命中0。导出使用隔离临时Git环境标记，不注册worktree，不更改交付文件。
- 主协调处理：接受当前PASS，首轮FAIL原样保留；仅归档、记录真实检查结果和移除本任务活动指针，不改变合同或交付语义。后置提交/推送前再核对scope、state、index和远端。

### 主协调 Agent 实测记录（不作为 Validator 结论输入）

- 工作区：909 tests passed；Ruff check PASS、125 files format unchanged、mypy 107 files PASS；只读 compile 106、JSON 90/Schema 87、九类治理场景、metadata/AI布局、12份Markdown/34个本地链接、MIT逐字相同、ignore/diff/正式state全部通过。
- 提交树：12 个治理文件，无 source 增量。导出快照 Ruff PASS、74 files format unchanged、mypy 63 files PASS；compile 62、JSON 40/Schema 39、Markdown/许可/治理场景全部通过。
- 额外非 Git 导出目录的 pytest 探针为 329 PASS、2 FAIL：`test_m10_email_module_is_safe_tracked_template` 的 git check-ignore 返回128；`test_candidate_builder_rejects_destination_inside_git_repository` 因导出目录没有.git，落入缺goal的下一检查。原始失败证据保留。这不是正式工作区 GATE-004 的失败；不改测试、生产代码或创建新Git工作树来迎合探针。核对两项测试、对应Builder和.gitignore与HEAD的字节一致性，在实际Git工作区重新执行对应测试；不得声称导出目录331项全部通过。

### 首轮独立报告与同合同修正

- `contract_version`：VC-001。
- `overall_verdict`：FAIL（永久保留，不改写）。
- `criterion_results`：AC-001～004、INV-001～002、GATE-001～002/004～005通过；AC-005、TM-001、GATE-003因B-001失败；GATE-006尚未满足PASS；AC-006等待交付。
- `blocking_findings`：B-001，绑定AC-005/GATE-003/TM-001；受审提交树memory.md第22～32行同时存在main 9964970与旧v0.4.2固定事实，第63～66行同时存在活动指针与“无”。复现为基准b172f95到受审树54dc1161的memory差异检查。
- `advisories`：普通推送包含54个既有本地提交；秘密模式扫描不证明任意私人自然语言均不存在；初次非Git导出测试的两项环境失败保留。
- `scope_change_candidates`：无。
- `unknowns`：尚未提交/推送；当前检查不能证明历史所有进程的外部行为；平台模型内部档位不可独立读取。
- `commands_and_evidence`：全新只读adhoc0016_validator按VC-001独立运行；合同SHA为0ebce560d43fee28074c89ebe47f2535e4630d4e3bdbdd3ab4adc0409fd8075e，受审树54dc1161f08b18956233888467a2d70cc155fe14；工作区909项通过（167.79秒），补足隔离Git检查环境的提交树331项通过（74.30秒）；两套Ruff/format/mypy、compile106/62、Schema87/39、metadata/AI布局与链接34/31通过；772个blob私人路径/可识别秘密命中0；149份备份恢复匹配，正式state9350项不变，真实index为空。
- 修正依据：唯一范围内实施缺陷，尚未触发两种修法/三轮诊断门。停止原提交动作，保留首轮导出树、index、manifest与patch；只修正提交内容组装，不改VC-001、产品或正确预期。补充新版固定事实唯一及活动状态不矛盾的断言，重新生成快照，交另一名全新Validator；不得把本报告交给新Validator作裁决输入。

## 迭代日志

| 日期 | 完成与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-09-05 | Git 与上游目标固定，冻结 VC-001 | 保留既有 M11 脏工作区；远端落后 54 个既有提交 | 备份、三方适配、检查、独立验证、提交与一次推送 |
