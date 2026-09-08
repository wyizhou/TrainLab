# M12：跑步独立规划分支与三角色协作

- 状态：active；当前步骤：R1已完成双平台交付，R2独立/Main实际验收通过，分支交付与双平台CI待完成。
- 分支：work/m12-running-only-planning；基准 b307e90efca7e1f1f65d0a22842aa1f685447e42。
- 批准来源：2026-09-08 用户逐字批准《TrainLab 跑步独立规划分支：三角色协作实施计划》。
- 当前完整合同：RUN-VC-001，frozen；本分支实施前冻结。仅替代本分支受影响规则，另一条开发路线不变。
- 原 M12 同一 Roadmap 和活动计划继续；[原路线历史快照](../completed/M12-fit-weekly-0001-rebuild-before-running-only.md)不作当前裁决，不改写旧失败。
- 本轮授权：离线实现、合成测试、全新三角色子 Agent、每模块验收后提交并正常推送 origin/work/m12-running-only-planning；不合并/推送 main。

## 当前完整冻结合同 RUN-VC-001

所有条款均来自上述用户批准计划及其明确保持的 M12 目标。未实现模块只作为后续验收，不要求前置模块提前完成。没有待确认的离线实施范围；真实业务调用预算与用户确认另行取得。

| ID | 可验证要求 |
| --- | --- |
| COL-001 | 当前聊天为主 Agent，只有 Planner、Developer、Validator 三种子角色。每次派发、修复、复验使用全新 Agent，不继承旧聊天，只接收角色模板、当前目标/输入输出/错误边界、必要接口代码/写界、检查及交付要求。 |
| COL-002 | Planner 拆解下级预期，主 Agent只审核遗漏、矛盾、未经批准需求和模块衔接；Developer测试实现；Validator独立检查并可在隔离位置自建测试，不改交付/正确预期，不继承旧裁决或实施者辩护。 |
| COL-003 | 主 Agent保存任务/失败/证据和累计次数，实际验收完整功能及适用质量门。两种实质修法仍失败、三轮不收敛或直接合同冲突时汇总诊断请求用户，不派第四角色、不无限换Agent或清零。 |
| COL-004 | 三份通用Markdown角色模板和通用启动Prompt落在docs/exec-plans/roles/；可跨项目复用、不含产品/本机绑定。不修改全局Agent配置。 |
| AC-001 | 收集2022-01-01起全部运动FIT，优先复用已有原字节。新SQLite独立保存索引/身份/SHA/版本/摘要/分段/同步/输入结果/历史计划/动作，不批量保存全部秒级点，不恢复健康API。 |
| AC-002 | 完整分页才证明无活动；当日provisional、查询失败、缺口、无FIT与下载完成分别记录。历史导入不代表查询完整。明确日期/工具/数量/墙钟，重启不重置预算。 |
| AC-003 | Easy/未知跑步2分钟，明确SOS保留work/recovery圈段且连续主训练1分钟，其他运动5分钟；不猜间歇。保留有效/经过时长、暂停、缺口、覆盖率和真实来源。 |
| AC-004 | 本期全部运动进入周总结，不按计划过滤；最多前四份完整成功结构化M12周报及目标快照，不足按实际，不用M11充数。同周原活动/历史/目标快照不被后续编辑改变。 |
| AC-005 | 有来源运动GPS/路线/地点/名称可以进入选定AI，不公开或进Git。来自真实FIT点/时间/活动/SHA，不平均插值、不冒称完整路线；坏定位不丢正常运动，GPS不证明坡度天气，不自动新增地图/天气服务。 |
| AC-006 | 显式字段投影和统一检查；禁止原FIT字节、凭据/认证信息、无关身份、任意文件/SQL/命令。失败在模型intent/调用之前停止且不回显秘密。 |
| AC-007 | 每周先跑步规划、后全运动总结，两次独立无状态AI调用，各最多一次且无自动重试；复用一套监督/耐久恢复实现。每阶段独立输入/intent/结果，版本/搬迁/重启不能重获额度。 |
| AC-008 | 规划只读本期跑步、最多四份历史中可验证跑步分析/计划、用户目标/限制/可训练时间及跑步细读；不读非跑步活动、混合总结全文或越界细读。无独立跑步字段的历史不整篇传入。 |
| AC-009 | 总结读全部运动/最多四完整历史/目标/本次已验证固定计划；不得修改计划、提出替代或以非跑步负荷调整跑课。合并输出一份周报与唯一计划。 |
| AC-010 | 两阶段共享每周20次细读、每次最多20分钟，同请求缓存；规划阶段仅跑步权限。第一阶段失败不启动第二阶段，第二阶段失败保留计划但不发布；成功阶段不重跑。旧单阶段只读兼容，不转成新授权。 |
| AC-011 | 周报：核心结论、全运动清单统计、最多3项重点跑技、其他运动说明/不确定性、简短计划对比、固定7日计划、数据局限/安全。技术判断带来源和适用条件，不强行计算。 |
| AC-012 | 计划为下一周一至周日，只依据跑步与目标；每课目的/剂量/完整步骤/重复组/RPE/技术备注/停止条件，休息不建Workout。硬负荷≤3、日期差≥3天，不同时加距离强度、不补课/每日改课，无依据不强制SOS。 |
| AC-013 | 仅展示设备历史心率/session分区时长事实，不处方BPM、不自行划区/阈值。运动表现不证明没有健康风险。Host提供日期/周期/统计；业务Schema统一派生wire并检查Prompt。 |
| AC-014 | 同一验证结果生成Markdown/PDF/邮件/Garmin。PDF逐页检查中文/图表/完整课程；不恢复复杂HTML。仅发布前显式编辑入口产生新修订、重验/渲染，不覆盖AI/已发内容、不重跑模型、不通过总结编辑偷改计划。 |
| AC-015 | Gmail仅官方REST/现有认证/正常原子Token刷新。简单同步邮件与PDF周邮件，每封durable intent后send最多一次；核验实际Gmail ID/Message-ID/收件人/正文/解码PDF SHA，unknown只读恢复不重发。 |
| AC-016 | Garmin真实步骤/重复组，创建读回后排期并核对日期。仅新库精确自有ID；不按名删旧课。邮件/创建/排期独立记账，成功不重做、unknown只读对账。 |
| AC-017 | Python统一import-history/sync/weekly/daemon/status/reconcile/本地编辑。香港22:00同步当日/昨日/已知缺口并邮件；启动登记停机缺口晚间补。 |
| AC-018 | 周日15:00先同步，窗口[上周日15:00,本周日15:00)，活动按结束时间归属。错过仅下次启动补最近一期，原周期+补发；不排过去、不整体平移、不改写已发布报告。 |
| AC-019 | 单进程锁/退出/恢复/status真实。路径相对source或显式实例根，用户手动启动daemon；不安装cron/开机项，退出不声称仍守护。 |
| RET-001 | 保护tracked/untracked/失败原文与SHA及恢复；必要能力复用。旧业务/专用测试逐场景映射保留/迁移/取消，适用安全断言不删除弱化skip/xfail；旧归档可删除且不是运行依赖。 |
| RET-002 | 批准的新要求同批更新有效规则、实现、Schema、Prompt、配置、入口、测试、CI、文档；退出旧路径后才宣称替换完成。历史只存证不裁决，兼容只保留必要只读/显式迁移，不丢成功/unknown/预算。 |
| GATE-001 | 当前活动产品完整pytest、Ruff/format/mypy、只读compile、活动Schema、metadata/文档/权限/隐私/ignore/布局/diff；macOS/Linux实际验证，不专项冒称全量。纯治理模块用适用文档/规则检查，不虚构产品测试。 |
| GATE-002 | 每模块全新Planner→Main审核→全新Developer→全新Validator→Main实际验收。Validator按固定八字段给证据，只读当前合同/适用规则/受审结果，不读旧裁决。 |
| GATE-003 | 每模块验收后精确提交并正常推送origin/work/m12-running-only-planning，核对远端及CI后再进依赖；不main、不强推、不夹带私人/无关/未验收内容。 |
| LIVE-001 | 离线完整验收后先提交精确真实日期/同步范围/工具/模型/邮件/课程数量/墙钟预算，另获授权后执行；本计划不立即调用业务服务。首份真实周任务在其后下个正常周日15:00，两阶段AI、PDF邮件、实际跑课每天≤1项/首轮≤7项。 |
| INV-001 | 不改变另一开发路线，不修改旧正式state/FIT/私人目标/凭据；切换需用户确认PDF与课程后另行执行。历史成功失败不改写，回滚不删远端动作或自启旧程序。 |
| INV-002 | 不恢复健康API、日报AI、高保真邮件、旧产品Harness、Sites、cron、开机项或模型自动重试；不公开私人运动/Token。 |
| TM-001 | 正常崩溃、网络/认证失败、损坏FIT/输入、分页不全、跨活动证据、越界访问、超预算、重放、Provider响应丢失。 |
| EX-001 | 不承诺抵抗同UID恶意/root/永久内核磁盘硬件故障，不新增任意无标签秘密或隐写识别。 |

## 工作分解与模块门

| 步骤 | 状态 | 内容/依赖 | 本步主要条款 |
| --- | --- | --- | --- |
| R0 | done | 现场保护、三角色协作、当前分支目标/模板、继承基线核对；已提交/推送/双平台CI | COL全部、RET、GATE、INV |
| R1 | done | 现有底座接线/同步预算/无归档独立运行；5c67ead已推送且双平台CI通过 | AC001–006、RET |
| R2 | in_progress | 两阶段输入、共享细读及一次调用恢复；独立/Main验收通过，分支CI待完成 | AC004–010 |
| R3 | pending | 周报/固定课程业务校验；依赖R2 | AC011–013 |
| R4 | pending | Markdown/PDF/本地修订；依赖R3 | AC014 |
| R5 | pending | Gmail/Garmin新库动作与读回；依赖R4 | AC015–016 |
| R6 | pending | 统一入口/调度/彻底退役/全链离线；依赖R5 | AC017–019、RET、全部集成门 |
| R7 | pending | 精确预算授权、正常周日真实验收和用户确认；依赖R6 | LIVE001、INV |

## 当前检查点

- 2026-09-08 Git门通过，56项tracked改动/删除、23项untracked均保留。
- 仓库外保护目录：/private/tmp/trainlab-running-branch-prechange.dI6pvD；410份公共文件/5项删除记录，tree和restore逐字节核对、0700/0600；manifest SHA 57b3df394c3da96f110253a01d3ceb920c7dee0ee9d714b5e0287ee7ca667991。未读取正式数据/凭据。
- 既有VC-005受审树410文件当前仅活动计划协调记录不同，产品源与测试未变；既有PASS仅覆盖原底座，不能代替本分支新要求验收。
- 阻塞：R2无已证实合同不符合，独立本机PASS；诊断状态not_triggered。R1及R2各自集中修正批次1已消除，R2独立Validator失败轮次0。额外真实CLI本机探针能力未确认，保留限制，不作为真实可运行证明。
- 下一动作：精确分支提交/推送并核对同SHA的macOS/Linux全量CI；依赖门完成前不启动R3。CLI能力未知须在后续完整运行及真实阶段前明确核实，不以R2内部接线PASS代替。
- 实际业务Provider/周模型/邮件/课程调用0；本轮R0已提交并推送当前分支d525a39561dde62e286b988cf3978f67daf95841，远端SHA已读回一致。开发子Agent不是产品周模型调用。

## 派发、验证与迭代

- R0 Planner：planner_governance_bootstrap，fork_turns=none，平台默认模型/推理，纯只读；输入为本次批准约定/必要规则与仓库，不读历史裁决。
- 主Agent已审核R0拆解：只处理角色/生命周期/失败门/通用模板和本分支目标，没有新增业务需求或第四角色。Developer白名单为协议、模板、roles四文件、active/completed入口说明、根README和source/AGENTS；Main独占AGENTS/rules/PLANS/memory/CHANGELOG及本计划；无交叉写入。
- R0 Developer：developer_governance_bootstrap，fork_turns=none，平台默认；仅实现上述文档并自检，不改产品源码/测试/CI/历史计划，不提交推送。
- 继承基线当前与既有受审410文件相比，仅活动计划协调记录不同；根已启动当前完整pytest。当前Ruff check/format-check及mypy已退出0（180格式文件、162类型文件），这不是独立Validator结论。
- 本计划以协调记录保存任务预期、文件边界、命令、结果和失败次数；Validator只读取上方当前冻结合同及受审差异，不接收本节历史。
- R0预期：三个通用模板+启动Prompt可直接复用；不再派第四角色；Main最终功能验收不能被独立PASS替代；旧联合排课/单周一次模型/main推送不再是本分支当前要求；不声称后续代码已交付。
- R0检查：适用Markdown链接/围栏/角色与规则一致性、Git范围及diff；继承基线按原受审摘要核对。产品变更在其模块运行完整双平台门。
- 本轮正式实施始于用户逐字批准之后。快照与恢复已完成；其余结果待实际执行后记录。
- R0 Developer已停止写入并交付10份白名单文档。其隔离检查10文件/18相对链接与锚点通过；检查器一次同义表述匹配错误已纠正，不曾据此改需求。Main自检17文档/49本地链接、通用性与diff通过，从开工快照到本轮产品代码漂移0；开始冻结R0文档给新Validator，尚未判定完成。

## R0 独立验证与主 Agent 验收（2026-09-08）

contract_version: RUN-VC-001；冻结SHA 06b78e945db2e730f6eafd4b4f525ae26b05c168b5107f6eba65fcea7ba180b8。

overall_verdict: PASS，仅R0治理及适用保护边界，不代表R1–R7、继承产品改动或最终Git交付。

criterion_results:

| 标准 | 独立结果与证据 |
| --- | --- |
| COL-001 | PASS：协议及四模板只有三子角色、全新无聊天、最小当前任务包。 |
| COL-002 | PASS：Planner只读拆解、Main四项审核、Developer实现测试、Validator隔离检查且不改交付/正确预期。 |
| COL-003 | PASS：原两种修法/三轮不收敛/直接冲突阈值保留，Main汇总请求用户，无第四角色/自动修复/换Agent清零。 |
| COL-004 | PASS：三个Markdown角色模板与通用Prompt齐全，全文和绑定扫描未发现产品/本机/厂商绑定。 |
| RET-001 | PASS适用部分：415项开工清单完好，无新增丢失；5项删除保持；历史计划14818字节原文完整嵌入说明后，末尾仅另加换行。 |
| RET-002 | PASS治理部分：有效规则与入口退出旧角色和main推送，两阶段标为尚未实现。 |
| GATE-001 | PASS治理门：摘要、权限/链接类型、文档链接/锚点、围栏、ignore、diff通过，不虚构双平台产品结果。 |
| GATE-002 | PASS本次独立检查：八字段、中性输入及Main后续实际验收明确；未参与实施/读取旧裁决。 |
| GATE-003 | PASS约束部分：仅允许模块验收后推本分支，未执行或冒称Git交付。 |
| INV-001 | PASS受审范围：相对开工仅17治理文档变化，产品/测试/CI新增变化0，历史原文未改。 |
| INV-002 | PASS适用部分：未新增禁止路线或业务调用、私人文件。 |

blocking_findings: 无。

advisories: Main仍须实际验收同一快照并完成提交/推送/CI，不能把此PASS扩大到开工产品改动。

scope_change_candidates: 无。

unknowns: 不认证协调历史中的派发/累计次数；未跑产品pytest/Ruff/mypy/compile/Schema/Linux，纯治理没有产品变化；未读真实state/凭据/其他分支，未调用业务Provider/真实周模型/远端服务。

commands_and_evidence:

- Validator身份validator_r0_three_roles，fork_turns=none；high/high，未参与实施。Darwin、Git2.50.1，基准b307e90。
- 独立Git根/分支/status/untracked核对；r0-review/manifest.json的17项及唯一冻结合同匹配，manifest SHA70da4781f3f42679794efe75200a11db3d6c8f4b2d504b486209bafbf2b9d96a。
- 开工清单415项：摘要错误0、新增丢失0、越界变化0；12既有文档变化+5新文档。历史原文完整出现一次且有说明。
- 本地MD链接/锚点26项、围栏、模式/symlink检查通过；仅以diff审计memory/PLANS/CHANGELOG，不用历史裁决。
- 旧新协议失败门阈值比对、当前残留扫描通过；8项私人路径git check-ignore通过；git diff --check退出0，最终FINAL_SNAPSHOT_MATCH 17/17。
- git diff --cached --name-only为空；Validator无任何交付写入或Git操作。

Main实际验收：已通读角色模板、有效指引和流程，核对用户四项规划审核、修复证据传递、独立输入、触发后暂停和最终实际验收均落实；独立PASS后再次运行check_governance.py及受审SHA复核。提交前等待当前完整产品测试结束，并单独核对继承产品的既有验收范围。

### R0 本机验收完成与提交前范围

- Main当前完整回归：`PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/uv run --offline --no-project --with-requirements requirements.txt python -m pytest tests/code -q -p no:cacheprovider`，3049 passed in 1608.27s，进程退出0。没有选择性跳过或仅运行M12前缀。
- 当前Ruff check、format-check（180文件）、mypy（162文件）、只读compile（160文件）、12活动Schema闭包、109公开JSON、metadata/AI布局/ignore/diff均通过。Main治理检查17文档/49本地链接及通用模板通过，相对开工产品漂移0。
- 继承79项改动使用独立已完成的VC-005受审清单逐字节绑定（清单SHA4126194ffe37161f43fca2ea39bd3f8305bd0fa1e41cf5c27230ae3c1c15cb21），该受审结果包含3049项macOS及Linux完整回归。本轮新增治理17文件另经全新R0 Validator及Main验收；两个范围分开，不继承其结论证明新业务。
- 当前88项实际改动全部属于继承清单与R0白名单的并集；非R0文件保持原受审内容、删除状态及Git可执行位。没有将FIT、数据库、凭据、Token或私人结果加入提交范围。
- 精确暂存前检查另发现一项开工前的公开源码权限差异：`gmail_rest_common.py`原私有受审副本为0700，当前worktree及本轮开工快照均为0755，内容SHA和Git可执行位相同。保留当前已有权限；其余非R0文件权限一致，不将公开源码的worktree检出权限误记为私人Token权限或本轮内容漂移。首次暂存检查因此拒绝，尚无暂存写入；核对原件/开工证据后仅纠正该检查的公开文件权限比较方式。
- 提交/推送尚未执行；下一步仅推`origin/work/m12-running-only-planning`，再核对该提交的双平台全量CI。M12及R1–R7仍未完成。
- 暂存后的完整diff检查补获此前untracked历史副本EOF多余空行；按执行协议纯排版边界，仅删除Main建立副本时追加的一行，原14818字节历史现为完整后缀、出现一次。最终历史副本SHA为a0e62a03880b50b135d72e201c7269d5d826387eeeb5fe783f72fe174792ab0c；原Validator受审清单不覆盖/重写，其余16项摘要仍一致。该格式勘误不改变合同或产品结论。Git将一组已批准迁移测试显示为重命名，所以88个路径对应87项默认diff，不是遗漏删除源路径；精确范围使用`--no-renames`核对。
- R0提交已发生：d525a39561dde62e286b988cf3978f67daf95841，`feat: establish running-only branch baseline and three-role workflow`。正常推送`origin/work/m12-running-only-planning`退出0；`ls-remote`精确分支SHA一致，未合并/推送main。提交后工作树原为clean，当前仅协调结果回写。
- 对应远端全量工作流[trainlab-source 34186552115](https://github.com/wyizhou/TrainLab/actions/runs/34186552115)绑定同一提交。macOS job 101935947580已成功：3049 passed in 1460.07s；Ruff通过、format180文件、mypy162文件，后续全部步骤success。Main通过单job日志读回实际输出。Linux job 101935947703仍在Test，尚无完整结论，不预写双平台PASS，不进入R1。macOS仅有平台将旧action的Node20切到Node24的非阻塞弃用提示，未据此增加实现范围。
- 远端最终结论已返回success：Linux job 101935947703为3049 passed in 2192.78s，Ruff/format180/mypy162及后续全部步骤成功；两job均completed/success，工作流headSha=d525a39561dde62e286b988cf3978f67daf95841。Main分别读取单job日志及最终工作流JSON核对。没有重跑CI、绕过失败或推main；R0至此completed。

## R1 派发与实施记录

- Planner：planner_r1_data_foundation，全新fork_turns=none，high/high（跨模块接口/预算/恢复，平台映射gpt-6-astra与high）。只接收RUN-VC-001逐字合同、AC001–006/RET及适用治理安全规则和当前底座源码/测试；不接收旧裁决，不读取协调历史。依赖基准为已完成双平台CI的d525a39。
- 本步只补现有数据底座接线和对应测试，不提前实现两阶段模型、周报/PDF、发布或调度。Main同时仅记录真实协调事实，未修改产品文件。沿用项目garmin-sync的FIT-only/缓存认证/预算边界，不启动真实MCP。
- Planner完成只读拆解；Main四项审核通过其最小接线方向：保留导入/分页/下载/解析/细读，补整任务耐久时间预算、旧同步记录只读解码、当前同步资源闭包及空实例合成串联测试。没有新业务或新外部服务。
- 未采纳方法建议中的独立活动总量参数作为新增标准：现有page_size×max_calls及下载/会话上限已提供可验证数量上界，只要求沿用并证明实际生效，不再额外维护一份预算答案。整任务时间限制约束采集工作及后续Provider发起/等待，超过期限不得继续新采集或宣称越限采集成功；正常关闭与同步证据收尾必须完成，不把每个磁盘系统调用都必须准点返回提升为合同要求，也不得取消审计来取得时间绿灯。

| R1子预期 | 对应合同 | 正确结果/错误边界 | 实现与检查定位 |
| --- | --- | --- | --- |
| 复用与状态区分 | AC001–003 | 导入不证明查完整；登记FIT不下载；完整分页、provisional、gap、no_fit、下载完成不同；预算耗尽不初始化 | 既有storage/legacy_import/sync_calendar/fit_sync；合成串联回归 |
| 整任务预算 | AC002/TM/EX | 明确总时间、首次耐久冻结、进程内剩余时间；慢调用累计超限停止；重启/搬迁不补发完整额度；成功重放零调用 | fit_sync/garmin_fit及小型必要内部辅助；真实等待/中断与可控时间回归 |
| 旧记录读取 | AC002/RET | 旧已完成请求及来源继续只读核对且SHA不变；缺少总时间凭证的旧未完成请求不静默联网或补额度 | 统一请求解码、weekly_evidence两处重建、对应版本回归 |
| 当前独立同步 | AC001–006/RET | 明确保留guard/overrides；不带旧代码/库/归档/测试的副本从空实例完成合成同步、解析、全运动证据及细读；搬迁零重复 | 当前资源清单与独立子进程集成，不从原仓库补缺 |
| 说明与迁移 | RET/GATE | 只回写已接替能力和当前接口；适用安全断言不降低，不前置R2–R6 | 对应docs、旧场景映射、完整门和全新Validator |

- Developer：developer_r1_data_foundation，全新fork_turns=none，high/high（异步预算/恢复/跨模块兼容），仅产品白名单与对应测试/文档；Main独占协调文件，当前本模块实施修复次数0。
- Developer已记录首轮6项新增失败回归，再补耐久总预算、进程内单调剩余时间、统一v1/v2请求读取和采集资源闭包；其定向70项自测通过，正在补真实进程中断、慢收尾、旧成功只读和空实例独立串联。该结果仅是实施自检，不是独立PASS或本模块完成。采集资源由显式collection范围收集，不把无关Garmin资源加入模型默认身份。
- 当前R1交付已停止功能/测试改动：115项定向自检、Ruff/format181/mypy163及只读QA通过。Main冻结19项实际改动，r1-review/manifest.json SHA de22559b9578792b935a837709f8fc518a8847d9ff270a7d4328de01c86927de；RUN-VC-001原文SHA未变，当前下级预期另存r1-expectations.md供中性派发。再次逐项核对19项一致，尚未独立验收。
- 自检命令曾直接使用pytest导致3个既有导入收集错误；按CI改为python -m pytest，无代码/预期绕过。第二轮收集后另补4项边界，为绑定最终清单，Main要求正常中断Developer自建进程；936 passed/238.30s、退出2仅作为中断片段。其uv/pytest已确认停止，再按不变清单运行全量；不将不同收集批次拼成一次全量PASS。详细自检摘录位于/private/tmp/trainlab-r1-developer.Dmo0cu/check-evidence.md，不是独立验收报告。
- 冻结全量实际退出1：3069 passed、1 failed，712.36s。唯一失败为test_m12_retirement_boundary.py第85行的active_test_files一致性断言：新增test_m12_sync_wall_budget.py未登记清单。Main单节点独立复现退出1/0.02s，确认是本次登记遗漏，不是同步实现失败，也不把全量改写为PASS。完整stdout保留在/private/tmp/trainlab-r1-developer.Dmo0cu/full-pytest.stdout.txt；原r1-review清单原样留存。
- 范围内修复派发developer_r1_inventory_fix，全新fork_turns=none，low/low（单项机械清单登记，平台gpt-5.6-luna/low）；只允许补active_test_files唯一缺项，不改测试/功能/其他映射，完成后由全新Validator验收。失败特征R1/RUN-VC-001/RET-002+GATE-001/test_inventory_missing；当前集中修复批次1，独立Validator失败轮次0，诊断门未触发；换Agent未清零。
- Main对冻结源码已实际运行Ruff、format181、mypy163、只读编译161/100JSON、活动Schema/metadata/布局/权限/ignore/Markdown及映射检查并通过；这些静态结果不覆盖上述清单失败，也不代表独立验收。
- 新Developer只补一行active_test_files；实际清单67/67一致，完整retirement_boundary为5 passed；JSON与diff通过，未声称全量。Main核对相对原r1-review的唯一产品差异就是该清单行；新r1-review2保存19项当前快照，manifest SHA776b38580ad7ca10dab5288c0ad1f89a503d34488dc1cbcc7e24f03daac09754，原失败快照不覆盖。
- 独立派发validator_r1_data_foundation，全新fork_turns=none，high/high（与主实现同档，采集预算/恢复/隔离）；仅当前RUN-VC-001、R1中性下级预期、适用规则、基准d525a39和当前19项快照。未提供旧裁决或Developer通过声明。当前validating，等待其完整本机回归及独立功能证据，尚未PASS/提交/推送。

## R1 独立验证与Main验收

contract_version: RUN-VC-001；R1，合同SHA06b78e945db2e730f6eafd4b4f525ae26b05c168b5107f6eba65fcea7ba180b8。

overall_verdict: PASS。仅当前R1本机独立验证，不代表Linux CI、真实业务或整体M12已完成。

criterion_results:

| 标准 | 独立结果 |
| --- | --- |
| AC-001 | PASS：登记FIT原字节/身份/SHA/CRC复用、导入后分页不重复下载、新库独立，空实例副本实际解析FIT。 |
| AC-002 | PASS：分页/provisional/缺口/no_fit/下载分开；数量和总时间持续，慢启动/连续调用/同步写入/关闭/实际中断/搬迁通过，旧未完成不获新额度。 |
| AC-003 | PASS：跑步120秒、其他300秒、明确SOS圈段/work60秒，暂停/缺口/覆盖与来源，不猜间歇。 |
| AC-004 | PASS当前底座：全运动、最多四完整成功历史、目标/原周冻结及搬迁；未前置两阶段业务。 |
| AC-005/006 | PASS：来源位置/名称允许、坏定位/跨活动/SHA和片段边界；实际上下文/历史/细读非法输入在模型intent前阻断，真实模型0。 |
| RET-001/002 | PASS当前范围：67项活动测试清单一致，未删弱或skip/xfail；无旧库/归档的独立副本通过，缺资源失败，历史SHA直接复算。 |
| COL/GATE-002/INV | 本Validator全新只读，无交付修改、业务调用、正式私人数据读取或另一分支操作。 |
| GATE-001/TM/EX | PASS本机完整质量与适用故障边界；未增加同UID/root/永久硬件要求。Linux尚待Main远端验收。 |
| GATE-003/LIVE-001 | 后续交付和真实授权门，未预写完成。 |

blocking_findings: 无。

advisories: 协调状态需同步PLANS中R1进展，步骤枚举R0使用done；本机PASS不代替Main实际验收、分支SHA和双平台CI。Main按真实状态同步，不改要求。

scope_change_candidates: 无。

unknowns: 当前Linux CI和真实Garmin/历史完整性/真实模型邮件课程未验证；只读是实际操作边界，不声称平台提供了OS级只读沙箱。

commands_and_evidence:

- validator_r1_data_foundation，全新high/high；Darwin25.5.0 arm64，Python3.12.13/pytest8.4.2，现有离线环境，无安装或.venv。
- 基准d525a39561dde62e286b988cf3978f67daf95841；manifest SHA776b38580ad7ca10dab5288c0ad1f89a503d34488dc1cbcc7e24f03daac09754。开始和结束19项路径/摘要/模式一致；唯一patch差异是允许的计划协调追加，合同不变。
- 完整`python -m pytest tests/code -q -p no:cacheprovider`退出0：3070 passed in 773.77s。未拼接或中断。
- 11相关模块专项1208 passed/121.05s；自建5项边界加闭合/墙钟回归22 passed/2.97s。自建检查位于/private/tmp/trainlab-r1-validator.uMhgBq/test_independent_boundaries.py。
- Ruff、format181、mypy163、只读compile161、100JSON、12活动Schema、metadata/AI布局/source/ignore/隐私/权限、11项变动Markdown链接和diff通过。
- 附加隐私检查曾误把跟踪的空.gitkeep当作私人文件，Validator只纠正检查方法，未据此改交付或正确测试。

Main实际验收：独立PASS后，在同一快照重新运行清单、总预算全文件、空实例合成同步/全部运动解析/细读/搬迁、缺资源拒绝和旧FIT复用组合，23 passed in 3.07s。结合前述Main实际Ruff/format/mypy/只读QA及受审摘要复核，确认底座完整接线。只剩本模块授权分支交付/CI；未执行真实业务。

R1分支交付已发生：Main再次核对19路径完整范围、15产品摘要/模式及合同不变，仅另有获准的真实协调回写；无暂存遗留/私人或无关文件。提交5c67ead6144b6b5c20df69a60cb73139d80ae91c，`fix: enforce durable FIT sync limits and isolated replay`，正常推送origin/work/m12-running-only-planning退出0，ls-remote精确SHA一致。提交后工作树clean；当前仅结果回写。对应[CI 34192371917](https://github.com/wyizhou/TrainLab/actions/runs/34192371917)绑定同一SHA，状态in_progress；未预写双平台PASS或进入R2。

CI观察进程曾因GitHub状态请求EOF退出1；Main只读重新查询同一run成功，确认两个job仍in_progress/Test，headSha未变。这是观察连接中断，不是CI失败；仅恢复只读观察，未重触发工作流、改代码或重置任何业务预算。

macOS job 101952870032已completed/success，Main读取原job日志：3070 passed in 1341.82s，Ruff通过、format181、mypy163及后续步骤全部success。观察连接另一次EOF后再次成功读取同一run；Linux job 101952869874仍in_progress，完整结论尚未返回，故R1仍待双平台交付门，不提前进入R2。

最终同一工作流34192371917已completed/success。Linux job 101952869874：3070 passed in 2070.10s，Ruff通过、format181、mypy163及其余步骤全部success。Main复核workflow headSha及ls-remote都为5c67ead6144b6b5c20df69a60cb73139d80ae91c；未重触发CI或修改测试。R1至此done，原登记遗漏失败及观察连接EOF历史保留。

## R2 派发与实施记录

- Planner任务planner_r2_two_stage_weekly：全新fork_turns=none，high/high（跨模块输入权限、共享预算、耐久恢复），平台映射gpt-6-astra/high。合同RUN-VC-001原文不变，主要AC004–010，适用COL/RET/GATE/INV/TM/EX；只读当前接口和必要测试，不读协调历史或旧裁决。基准5c67ead，R1提交/双平台依赖已满足。
- 本步先拆解两阶段接线和R3接口，不要求提前完成R3训练业务、R4渲染、R5发布或R6调度。Main独占计划/规则/状态；R2当前实施修复次数0、Validator失败轮次0。尚未修改R2产品代码或启动真实模型。

- Planner已完成只读拆解，Main四项审核通过：复用单执行器；按session投影跑步；权限与周预算分离；两阶段串行、原计划不可替换；旧单阶段只读及当前资源/Skill同批退出旧说明。没有新增需求或模型调用授权。共享历史提取/结果Schema及强制业务验证接口与R3衔接，不把合成回调当真实课程安全已实现。

| R2下级预期 | 对应标准 | 当前验收证据要求 |
| --- | --- | --- |
| 原周材料与阶段投影 | AC004–009 | 原目标/历史不漂移，plan仅running session及可验证历史字段，summary保留全部运动；无跑步不补造 |
| 混合FIT与共享细读 | AC006/008/010 | 跑步区间/来源授权先于缓存；两阶段20次/1200秒及同请求一次计数；非跑步不能借混合FIT越界 |
| 单一执行与阶段恢复 | AC007/010/RET | plan/summary独立intent/capture/结果，失败无重试、成功不重跑、跨阶段材料拒绝、搬迁预算不返还 |
| 顺序与不可变计划 | AC007/009/010 | plan失败无summary intent，summary失败保留计划不发布；合并唯一原计划，R3强制业务校验接口不可省略 |
| 真实适配与旧路径退出 | AC006–010/RET | Codex prepare/实际参数/stdio/恢复均绑定阶段，旧单阶段只读，适用安全测试迁移、Skill/docs/资源/清单同步 |

- 当前中性任务包在/private/tmp/trainlab-r2-packet.xFp6SK/，0700/0600：contract.md带当前标题的SHA bad6c0410925590d34c8718966f2ac7790d917bbb5fe2ca7e819b0d670129f1a，与既有逐字合同仅多标题，正文SHA仍06b78e94…ba180b8；expectations.md SHA58c061f92af939664c04bacf90fcd26a3fc289d30588cc2c74973362e96698b4。该包仅当前合同、正确预期、接口/写界/检查，不包含旧裁决。
- Developer任务developer_r2_two_stage_weekly，全新fork_turns=none，high/high（跨模块阶段权限、崩溃恢复、缓存及兼容）；白名单见当前任务包，Main独占协调/治理文件，先新增失败回归再实施，保留旧安全场景迁移证据。本步不提交推送或业务调用；完成后新Validator和Main实际验收，再分支交付/双平台CI。
- Developer提出在已允许的小型stage_policy.py/weekly_stages.py之外使用stage_context.py承载两种投影与来源复验，避免修改旧weekly_context保存格式含义。Main确认该拆分属于原白名单的必要接口申报，不新增执行器或业务；同意实施并保留R3强制结果校验/旧记录本地恢复边界。API精确签名和实际测试结果待交付，不预记完成。
- 首批测试先行证据：Developer以现有离线环境运行test_m12_stage_detail.py及test_m12_weekly_stages.py，原实现退出1/5 failed（stage参数、无stage新建及阶段账本未接入）；补对应实现后同命令退出0/5 passed。此为开发红绿自检，不是Validator结论或全量通过。接口已开始实现StageContract(response_schema,validate_result,prepare_adapter,recover)和weekly_stages.run(...,plan,summary,validate_history)；本地重放先查原intent，unknown才走原证据恢复，不直接信任回调结果。其余R2预期仍在实施。
- 历史接口的范围内选择：总结结果顶层使用独立running_analysis，合并running={analysis:原总结该字段,plan:原已验证计划}，从双阶段捕获重新验证来源；不增加project_running/HistoryContract可选机制。R3保留字段内容/逐证据语义和按版本阶段的必填业务校验职责。Main已将当前接口确认保存到中性任务包interface.md；这是原AC008/009的接口衔接，不增加训练要求、不修改RUN-VC-001。
- Developer已接入上述历史字段，继续贯通实际Codex阶段参数。Main同意仅更新已列明的`tests/ai/templates/m12_codex_probe.py`阶段与runtime identity接口；只用公开合成材料/本地假端点，不读取真实认证或执行真实模型。开发定向首轮279项中4项失败：3项嵌入子进程迁移重复stage关键字、1项测试与源码写入并发导致identity漂移；停止写入后4项重跑通过。完整门尚未执行，不拼接为全量PASS；独立Validator轮次仍0。
- Main独立验收脚本已保存于中性任务包同目录`test_main_acceptance.py`，只用公开合成FIT：检查计划仅跑步、总结全运动、共享细读缓存、搬迁零重跑及任一阶段失败不发布。当前未运行，待交付冻结与独立验收后实际检查；不是既有PASS证明。
- Developer完成主体接线及文档迁移，最新定向128项通过后停止产品写入，开始完整门；日志目录/private/tmp/trainlab-r2-dev-gates.KbFdtX（0700/0600）。开发过程曾从错误cwd运行mypy得到导入诊断，按原命令从source重跑168文件通过，未改变配置或屏蔽检查；残留测试变量亦按两阶段接口修正，不改变正确预期。
- Main冻结R2当前49项受审清单于/private/tmp/trainlab-r2-review.sqqbes79，基准5c67ead，manifest SHA ae560ed5a1bae03f6554ccdd961a1e9c5d828225b0d8f271031031b9a08123b3，合同正文SHA不变。此为初次完整受审冻结，不含旧裁决；后续协调追加依协议单独检查。
- Main在同一冻结产品上实际运行Ruff退出0、format186文件退出0、mypy168文件退出0、只读compile166/103JSON/15活动Schema根及必要闭包/69本地链接/metadata/AI布局/权限/ignore/diff通过。完整pytest尚在执行，不能据静态结果称R2已通过。
- Main另跑三项自建合成集成预检，3 passed/2.39s；这些不是独立验收，完成最终独立验证后仍复验同一快照。
- R2首次完整冻结pytest最终退出1：227 failed、2862 passed、712.97s；全部失败仅两个文件：retired_runner_safety的6函数共30项读取旧无stage intent，sports_input的2函数共197项仍无stage新建。Main读取当前源码与最小复现trace核对；实际子进程因此未启动或被model_stage_required拒绝，未发现需要放宽产品门的证据。对应AC007/010及RET/GATE，运动输入另涉及AC005/006/008/009。原日志、最小复现6 failed和初次49项清单不改写。
- 为完整保留未跟踪新文件，Main另存49项原字节tree于/private/tmp/trainlab-r2-review.g44yavc4，manifest SHA632d13307f237cec095558b480998805aef2b0b9cda023f0d10e22e14d6dff71；与初次冻结逐项合同/内容摘要/模式49/49相同，仅允许的计划协调追加。原产品无漂移，两个失败文件尚未尝试修法。
- 原Developer已结束且停止写入。Main批准原范围内集中修正：仅两个测试文件、legacy-test-mapping.json和必要迁移说明；完整运动场景迁入summary并通过真实当前接线创建合成已验证plan前置，不能直接标plan绕过隔离。当前repair-expectations.md仅包含有效合同/接口、原始复现和正确预期；不改变业务、不恢复旧入口。下一派发使用全新Developer，high/high（安全场景迁移与双阶段输入衔接），保留当前累计，不启动第四角色。
- 已派发developer_r2_stage_test_migration，fork_turns=none，平台gpt-6-astra/high，high/high档位不低于本步原实现；只读当前任务包与原始复现，不读取旧裁决。当前为R2集中修正批次1，尚未交付；不把测试迁移错误解释为业务隐私/训练目标需变更，也不将第一次全量失败改写为PASS。
- 当前集中修正的分类核对补充发现：input_privacy、route_fragments及weekly_context的四个合法完整输入正向用例虽未失败，仍将全周body配plan标签直接交Fake。Main已直接核实对应调用，批准同一批次仅迁移这些正向用例及必要共享合成helper/映射到summary＋已验证plan；不改产品、不改旧历史格式、不扩大低层单元测试的验收范围。此为原RET测试接线补齐，修正计数仍1，不把原失败改名重置。

## R2 独立验收

contract_version: RUN-VC-001；正文SHA06b78e945db2e730f6eafd4b4f525ae26b05c168b5107f6eba65fcea7ba180b8。

overall_verdict: PASS，限定R2内部两阶段接线与本机离线质量门，不代表真实CLI当前能力、双平台交付或R3–R6完整业务通过。

criterion_results:

| 标准 | 本次独立结果 |
| --- | --- |
| AC004–006 | PASS：全运动总结、四份历史上限与原快照；位置来源允许，禁止字段在intent前拒绝。 |
| AC007–008 | PASS：单一阶段账本、各一次与恢复；规划仅running/可验证历史，混合FIT边界与缓存前权限，plan/summary实际假程序Adapter链路。 |
| AC009–010 | PASS本步：原计划SHA/来源复验与不可变合并；20次/1200秒共享、失败占额、搬迁不返还、阶段失败不发布、旧单阶段零新授权。完整训练语义留R3。 |
| RET001/002 | PASS：13份阶段迁移摘要及函数一致，11份旧测试修改未删函数或加skip/xfail，安全场景迁移、无归档与旧格式回归。 |
| COL/GATE002/INV/TM/EX | 适用部分PASS：全新只读、合成检查，未扩同UID/root边界、未改受审文件或调用真实业务。Main验收仍待。 |
| GATE001 | macOS完整门PASS；Linux待提交后同SHA CI。 |
| GATE003/LIVE001 | 未执行分支交付或真实业务，不预记通过。 |

blocking_findings: 无已证实的R2合同不符合。

advisories: 额外真实Codex CLI plan/summary各一次合成本机探针在HTTP请求交付前退出，returncode=1、process_stopped=true、accepted_http=0，localhost发送错误。相同限制下curl可连接；不足以归因R2代码，不能宣称CLI当前能力验证成功。未扩大权限或继续重试。

scope_change_candidates: 无。

unknowns: Main实际验收、Linux同SHA CI、当前实际CLI能力及R3–R6尚未完成；真实模型/业务服务/正式私人资料访问0。CLI限制保留至完整运行前核实，不自动接受为部署债务。

commands_and_evidence:

- validator_r2_independent_stages，全新high/high，Darwin25.5.0 arm64。基准5c67ead，受审50项manifest SHA6e9c3b994383b67b6ed928ec0c37f97ccf48cfc15cf8c4869e7e121eb8cd7f30；开始/结束41 tracked与9 untracked范围、SHA/mode一致，无暂存；计划仅真实协调追加、逐字合同一致。
- 指定离线环境完整pytest：3089 passed/874.41s，退出0；Ruff通过、format186、mypy168通过；只读compile166、103JSON、15Schema根闭包、6metadata、AI/隐私/ignore/布局、46本地文档链接、tracked/untracked diff通过。
- 自建test_independent.py：7 passed/19.50s；test_summary_raw_recovery.py：1 passed/24.09s，实际假程序总结完成后外层落盘中断，搬迁并移走原二进制后从原capture恢复、零prepare/模型新调用。证据/private/tmp/trainlab-r2-validator.l3OKG0。
- CLI限制证据同目录cli-plan-0lv01y3a与cli-summary-vjgb5qmg。初次辅助diff脚本误读no-index正常差异退出码1，修正检查方法后通过，未修改交付。合同标题/正文摘要采用明确提取规则独立复算一致，未改合同。

R2首次独立验收派发：validator_r2_independent_stages，fork_turns=none，high/high，平台gpt-6-astra/high，不低于Developer。仅当前50项中性快照、逐字RUN-VC-001、接口/预期与适用规则；未提供旧裁决、修复包或开发通过声明。允许仓库外只读自建合成检查，禁止受审改动、业务调用及自行修复；Linux留获批分支提交后的同SHA远端CI，当前不预判。

本上下文检查点：集中修正仅7个获批测试/映射文件变化；原产品与旧历史fixture不变。Developer最终9文件定向1383 passed/245.24s，完整3089 passed/867.09s，Ruff/format186/mypy168及静态门通过；结束后369个source文件SHA/mode与冻结清单相同。Main复核分支/未暂存范围，并只读compile166/103JSON/15Schema根/69链接及布局门通过。50项中性快照/private/tmp/trainlab-r2-review.8w3odmhj，manifest SHA6e9c3b994383b67b6ed928ec0c37f97ccf48cfc15cf8c4869e7e121eb8cd7f30，当前逐项SHA/mode再次一致；原失败快照不覆盖。派发全新high/high Validator，尚无独立结论，不预先提交/推送。

## 完成条件

R2 Main实际验收：独立PASS后，同一冻结产品运行自建3项合成链路加完整两阶段、阶段细读、旧监督安全迁移文件，54 passed/24.00s。重新实际运行Ruff通过、format186通过、mypy168通过，只读compile166/103JSON/15Schema根/69链接及布局/隐私/diff通过。全过程公开合成、真实业务0；CLI额外探针未知保持记录，不被这些结果覆盖。仅按已发生事实同步6项协调/入口说明，合同与产品/测试不变，下一步精确当前分支交付。

全部离线模块及独立/主Agent验收、分支提交/推送/CI完成后才进入真实预算授权。真实邮件/课程读回及用户PDF可读/课程可执行确认之前，M12不归档、不称正式可用；不预写后台运行或完整交付。
