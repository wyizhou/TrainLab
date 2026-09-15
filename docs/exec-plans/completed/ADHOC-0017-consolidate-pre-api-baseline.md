# CONSOLIDATE-20260914：单目录整合与 API 改造前旧版基线

- 任务 ID：`ADHOC-0017`；功能编号：`CONSOLIDATE-20260914`
- 状态：`completed`；仅VC-002数据收尾完成，已获独立PASS及Main核对；不是VC-001旧系统整合/清理/提交完成。用户已打断澄清：旧代码大概率不再采用，可能直接进入新 API 模式；后续不再围绕旧代码和完整旧流程反复修复/验证，当前重点是收尾并保全 `data/` 中的数据与令牌。冻结合同的安全边界不变；执行重心收窄到数据/FIT/认证/配置/令牌保护、必要事实记录和避免丢失，不做产品替换、正式切换、清理、提交或远端动作。
- 负责人：主协调 Agent；执行方式：串行 Planner → Main 审核 → Developer → 全新只读 Validator → Main 验收及本地交付。
- 开始/更新日期：2026-09-14。
- 批准依据：用户已确认采用 TrainLab-next 现行两阶段 M12，整合回 `/Volumes/DiskOther/Code/TrainLab`；本轮要求按商定方案执行。原始交接事实见 next 的 `exec-plans/active/M12-fit-weekly.md` 2026-09-14 段；其产品版本与治理规则须分开核对。

## 当前收尾合同 VC-002

<!-- VC-002-BEGIN -->

- 版本：`VC-002`；状态：`frozen`；日期：2026-09-14。
- 人工批准：用户明确“之前的代码不会再要了，可能会直接采用新的API模式……主要是数据和令牌的data目录重要……不用反复修复”，随后要求“那么请你开始工作”。
- 范围：本次仅收尾保全主目录 `data/` 中的 FIT、必要 Garmin/Gmail 认证令牌、goal/email/配置和现有状态保全依据，给出可直接定位的私有目录说明。不再整合、修复或验收旧代码；API 仅为可能后续方向，本轮不实现。
- 替代关系：VC-001 的旧产品整合、旧代码质量门、恢复旧Git可运行性、清理和基线提交不再作为本次收尾交付条件；VC-001原文和历史证据原样保留，旧局部 verdict 不自动成为 VC-002 验收。不删除现存代码/测试/历史/数据来实现收尾，也不宣称旧缺陷已修复。

| 标准 | 当前要求及来源 |
| --- | --- |
| AC-D01 | 已保全 FIT 及其来源清单留在 `data/fit/` 和 `data/recovery/`，原字节不变、不下载、不重新导入；核现有目标摘要/大小与清单一致，不把去重数量当活动总数。无法覆盖的载体/链接保持原件并明确限制，不为交付擅自解包或跟随界外目标。来源：用户数据优先及原数据保护目标。 |
| AC-D02 | 将已知现用 Garmin/Gmail 令牌及 OAuth Client 原字节保全于 `data/verification/`，必要 goal/email/配置保全于 `data/config/`；有明确源→目标对应和摘要，异源冲突分开保留、不混合账户、不以测试样例充当真实认证。提供私有定位说明；不调用认证判断有效性。来源：用户 data/令牌目标、A-004/A-010。 |
| AC-D03 | 原正式数据/SQLite/sidecar、原令牌和既有保护证据不覆盖、不移动、不删除；已有状态字节保护可复用并记录定位，不重写成功/unknown/预算，不声称数据库一致性或业务恢复已经通过。来源：用户不丢数据目标、A-001/A-010/A-011。 |
| AC-D04 | `data/` 整体忽略、tracked data 为空；新私有目录0700/文件0600，无凭据或私人正文出现在公开记录/报告。只在明确相关 TrainLab 根或其已知保护清单中定位来源，不扫描无关用户目录。来源：A-004及用户原授权。 |
| AC-D05 | 本轮不修旧代码/Git、不建新迁移产品、不调整测试标准、不实现API、不安装依赖、不启动daemon、不调用模型/Garmin/Gmail或刷新/重认证、不清理、不暂存/提交/推送。只维护必要协调记录和私有数据保全材料。来源：最新用户澄清及随后开始工作授权。 |
| GATE-D01 | 操作前记录Git及精确来源/写入边界；复制校验源前后身份、摘要与目标权限/摘要；已有同SHA目标复用，不覆盖不同字节，发现漂移/越界停止受影响项。私有精确清单不公开。来源：根保护协议。 |
| GATE-D02 | 最后一次全新只读独立核对本合同、当前文件清单/SHA、必要来源匹配、权限/ignore及交付说明；不继承实施对话/旧verdict。只运行本次数据保全适用检查，不把未运行的旧产品pytest/lint/双平台门声称通过或要求修复旧代码。来源：A-019/A-020及用户收窄要求。 |

<!-- VC-002-END -->

### 本次执行步骤（唯一现行状态）

| 步骤 | 状态 | 范围 |
| --- | --- | --- |
| D-01 数据/令牌收尾 | done | Main已单独保全11份现用/旧版区分的令牌和配置，生成data/README及清单；核既有FIT目标和主DB保护索引，不改旧代码 |
| D-02 数据收尾独立核对 | done | 全新只读Validator 9a5c7d35按VC-002返回PASS，七项标准与80项最终检查通过；不外推旧产品/数据库一致性/在线认证 |
| D-03 交付 | done | Main复核21项受审私有文件与11对源/目标，保存独立证据、更新记录及归档；不提交/删除 |

### 2026-09-14 本次边界与恢复偏差

- Git实际为main/25e8b92，46 tracked修改、6 untracked，暂存空。较早检查点增加的C-07三文件属于已有工作，本轮不修改或验收。
- 先前仅修改步骤说明而未升级合同，现按用户明确收窄批准冻结VC-002；VC-001保留为历史，不再用旧门禁驱动新任务。
- Main仅写：`data/verification/`、`data/config/`中新的明确目录；`data/recovery/C09-*`证据与`data/README.md`私有索引；本计划/memory事实指针。`data/fit/`本轮只核摘要、不重命名或重跑。
- 来源：主/next的必要私有配置、TrainLab-data/m12现有auth/Goal/Email/garmin配置；既有C06/C06R1/C08清单用于核对已保护资料，其他既有工作树成果仍留原地。只解析本地结构/引用，不输出值；越界引用只记录而不跟随。

### D-01 实际结果与D-02派发

- 证据根：`data/recovery/C09-09efg58v/`；一次性私有脚本`preserve.py` SHA `35b691aa150391740918c41d824a919707ef72aa24e3c3e9ff0597f55680cb6a`。先运行7项合成复制/冲突/链接/FIFO/幂等检查，再保全11份明确源文件；不使用C-07产品helper，不新增/修改公开实现或测试。
- 已保全主Gmail Token/Client/历史收据、单独旧credentials、TrainLab-data/m12 Garmin Token、M12 Goal/Email/原Garmin配置和主旧goal/email/config。JSON结构及Token/Client配对只作本地布尔检查，不刷新、不显示秘密值。
- 复算既有FIT清单的566个目标SHA/大小/权限；13116为历史候选来源数，不是活动总数。本次未重扫所有源或解包；主DB/WAL/SHM只核现有保护目标和源lstat，SQLite一致性仍未声明。
- `private-delivery-snapshot.json`绑定21个新交付文件，SHA `cdc7e2c519da1ff6b7d04ca670ecda91efce08e91a2dc7c16827cfe5b90ff56a`；合同原文SHA `81120a0df06b93aebbaa66084b21b42b6608a9b1d540dd28c50deb0fecbbc696`。`public-before.json`绑定完整52项既有tracked/untracked内容/模式；计划只纳入VC-002合同段，其余为协调审计。
- Main执行`PYTHONDONTWRITEBYTECODE=1 python3 data/recovery/C09-09efg58v/preserve.py`退出0；新目标0600/目录0700，52项公开受审内容未漂移，暂存/ tracked data为空，ignore匹配。旧产品pytest/Ruff/mypy/Linux不在VC-002交付范围，不运行、不记PASS。
- D-02仅一个fresh只读native Validator；数据/令牌安全风险high，能力high/推理high，显式平台选档。只获逐字VC-002、适用规则、当前清单和来源定位，不传旧报告/实施对话；允许临时私有检查，禁止修改源/受审交付及旧代码/Git/认证操作。未提供OS只读沙箱，不作权限隔离保证。输出绑定`data-closeout-vc002-review.md`。实际async workflow `437963de-9689-4599-9561-e2821842c1cc`，唯一child key `data-closeout-vc002-review`；收到原生完成通知后由Main读取产物并收尾，不继续派发旧代码任务。

### D-02/D-03 最终交付事实（2026-09-14）

- workflow `437963de-9689-4599-9561-e2821842c1cc`、child `9a5c7d35-eba4-4014-948f-3bd3fc805ca8` 均complete。独立报告八字段为PASS，SHA `b73bdb820fd1309c69b2c9012e9a3b7e7f15739b14a693f77446fa880431471c`，已原样保存在 `data/recovery/C09-09efg58v/independent-review/data-closeout-vc002-review.md`。
- 实测：11对令牌/配置字节及独立inode一致；566个既有FIT目标SHA/大小/权限一致；三个主状态保护目标与定位一致（原DB只lstat）；data ignore/权限、52项公开快照及21项私有受审文件通过。最终检查器80项为true；检查器首轮自身错误及结果原样保留，未改交付迁就检查。
- Main在收口再次核对21项受审文件原SHA/模式及11对原件/副本相等；将报告、独立检查器/初始和最终结果/公开快照共5份原样保全于 `independent-review/`，目录0700/文件0600。
- 非阻塞记录勘误：状态索引的三个 `source_metadata_matches_prior=false` 源自mode整数与旧清单八进制字符串直接比较；独立统一类型后dev/ino/mode/size/mtime/ctime一致。原脚本和索引不改写、不重跑复制，不作为数据丢失或原件漂移。事实勘误写入 `closeout-receipt.json`，该收据SHA `604c5aef4aa9827985fda2302a46e6509c0fbfc99d85794e1ae73b8bcf1eec1d`。
- 使用位置见 `data/README.md`；Garmin/Gmail当前来源与legacy材料分开，必要配置在 `data/config/`。未改动原件、未调用服务/刷新认证、未修旧代码、未清理、未暂存/提交/推送。
- 剩余边界：令牌在线有效性、SQLite一致性/业务恢复未验；不透明载体/链接目标未展开；同设备副本不是离机灾备。旧产品检查不适用VC-002，不声称旧质量门通过。后续API需另行确认，不自动启动。
- 本计划移入completed仅归档VC-002数据收尾；以下旧合同/未完成项/历史失败继续原样保留，不自动恢复。

## 历史：VC-001 已确认目标与边界（已被收窄，非本轮指令）

1. 主目录唯一保留现行项目，以 next 产品实现为准，保护主目录、next、其他工作树的未提交成果与 Git 历史，不直接覆盖主目录 `.git`。
2. 主目录建立完全被 `.gitignore` 排除的 `data/`；`data/verification/` 保存必要 Garmin/Gmail 认证，`data/fit/` 保存按时间格式命名的全部 FIT 原字节。
3. 全部 FIT 保全不受旧导入器 2022 年起或旧库已登记条件限制；不得遗漏早期、未登记、重复或损坏原件。核对时间来源、重名冲突、无法读取时间的保全路径，不能把文件时间冒称活动时间或覆盖原件。
4. 清理与当前版本不符的旧数据、模块、注释和失效文档；必要兼容读取/迁移能力不能按名称删除。健康资料隔离保存在主项目，留用户手动删除；goal/email/凭据不混入可删除归档。
5. 数据原字节/来源、Git 恢复、必要配置与运行路径依赖全部闭合后才清除相关外围目录及工作树。目录迁移不能丢失成功/unknown/预算账本，不能产生重复模型、邮件或课程动作。
6. 验收后仅保存本地提交，描述为“API 改造前最后一个旧版基线”；不实现 API、不推送、不运行真实 Garmin/Gmail/模型业务、不重新认证、不恢复真实 R7，不声称 M12 真实验收已经完成。
7. 适用根 AGENTS/rules/执行协议，保留隐私权限及安全门；两仓治理版本差异须显式盘点，采用 next 产品不自动等于整体替换主目录开发 Harness。全新角色首次给齐材料，不续接旧会话；Main 独占协调记录。

## 历史冻结合同 VC-001（superseded，以下原文不改写）

<!-- VC-001-BEGIN -->

- 合同版本：`VC-001`；合同状态：`frozen`；冻结日期：2026-09-14，在本任务产品/配置/私人数据实施之前。
- 批准来源：用户已明确确认并要求执行本计划“已确认目标与边界”所述整合；Main 据该授权冻结初始合同，不将 Planner 实现建议变成额外要求。
- 范围：将 next 当前工作区的已确认两阶段 M12 整合回主目录，保护相关现存 Git/未提交成果和私人资料，核验后精确清理外围目录，只做本地旧版基线提交。
- 非目标：API 实现、真实 R7/正式业务验收、模型/Garmin/Gmail 调用及认证刷新/重认证、远端 Git/PR/发布/部署、全局 Skill/配置变更、恢复已取消业务、整体替换开发 Harness。
- 适用规则：主 AGENTS.md、rules.md 与 docs/exec-plans/README.md；产品受影响行为按用户明确采用的 next 现行合同及本次整合目标替代，其他安全和治理边界保持。next 产品来源为 `docs/product-contract.md`，当前 SHA-256 `8c1691d1c96746b81ea0389a7ff4e01223175d9605dc28049b1298c630fadd9a`；其中旧“另一开发路线不修改”、认证必须仓库外及开发流程措辞不反向否定本次明确整合/目录授权，主开发治理不由该来源替换。

| 标准 ID | 可验证要求 | 来源 |
| --- | --- | --- |
| AC-C01 | 采用 next 当前已确认产品（包括未提交实现而不只 HEAD），保留先跑步 plan 后全运动 summary、每阶段至多一次、共享每周20次细读/单次20分钟、阶段隔离与旧格式必要只读恢复；同批同步受影响产品要求。不实现 API、不恢复取消业务或原真实 R7；主开发 Harness 不整体覆盖。 | 用户采用 next 目标；next 当前产品合同；A-002/A-021/A-023 |
| AC-C02 | 修改/清除前保护确切相关仓库、工作树中当前仍存在的历史、Git 元数据、tracked/dirty/untracked 和必要原件/失败证据；保留 refs/objects/reflogs/index 等恢复材料及来源差异。完整 `.git` 不能仅用 HEAD、补丁或 bundle 替代；主活动 `.git` 不被 next 覆盖。相关来源清除前完成隔离恢复与原件摘要核验；不存在/坏入口不自动等于无成果。 | 用户保全目标；根 Git 门禁；A-004/A-023 |
| AC-C03 | 确认来源边界内全部 FIT 原字节落入主 `data/fit/`，不按2022起或旧登记筛选，不漏早期、未登记、重复或损坏原件；每个来源可追溯，SHA/大小/时间来源/冲突/无法解析情况闭合，不覆盖或修改原字节，不把文件或保全时间冒称活动时间。保全不等于活动解析或业务导入成功。 | 用户全部FIT及时间命名目标 |
| AC-C04 | 根 `data/` 整体忽略且不入 Git；必要 Garmin/Gmail 认证在 `data/verification/`，goal/email/必要配置及状态继续保留，不混入可删除健康/旧资料归档。私人目录0700、文件0600；不输出秘密或私人正文，不刷新/重认证，不把私人内容/结果混进提交或公开证据。 | 用户目录目标；A-004/A-010/A-023 |
| AC-C05 | 迁移保留原件、冻结输入/结果/SHA、成功/unknown、业务身份、预算/期限与恢复依据；不能因目录、版本或重启重获模型/邮件/课程资格，不重写历史成功失败。unknown 保持只读恢复，不触发任何真实外部动作或启动正式daemon。 | 用户不丢成果/迁移目标；A-001/A-010/A-011/A-021/A-023 |
| AC-C06 | 当前规则、代码、Schema、Prompt、配置、入口、测试、CI与文档按已确认方案同步。真实退役内容退出；必要读取/显式迁移能力按依赖及保存数据核对，不按旧名称删除；适用安全测试场景保留/迁移，有批准依据才取消业务专用用例。当前工程和合成离线链不依赖外围TrainLab目录、旧归档或原路径兜底。 | 用户清理目标；A-009/A-023 |
| AC-C07 | 数据 SHA/来源、必要配置与账本、Git 恢复和运行路径依赖全部核验后，才清除精确相关外围目录/工作树；不根据 prunable 或入口失效直接删。健康资料隔离留主项目由用户手动删，必要凭据/配置/唯一恢复证据不随健康资料清理。 | 用户有条件清理目标；A-001/A-023 |
| AC-C08 | 全新独立验证和 Main 验收后，仅对实际受验且不含私人/无关未验内容的公开文件做本地提交，记录为 API 改造前最后一个旧版基线。不推送/创建PR/远程资源/发布，不预写提交或清理成功，不声称真实M12完整验收通过。 | 用户本地旧版基线目标；根完成协议 |

| 门禁 ID | 检查和预期 | 来源 |
| --- | --- | --- |
| GATE-C01 | Main 修改前冻结合同、精确源边界和分步写入边界；保护前Git/文件来源有基线，一致性无法保证则停受影响步骤。 | 根合同/Git协议；A-001 |
| GATE-C02 | 适用功能/迁移及缺陷测试先固定合成正常、错误、冲突、损坏、早期/未登记、重复、中断和恢复预期再实现；实际发现的链接/载体边界受测，不读取正式私人资料作为代码测试或衍生夹具，不删弱正确检查。 | A-004/A-009；根测试先行 |
| GATE-C03 | 当前完整适用 pytest、Ruff/format/mypy、只读compile、Schema/JSON/metadata、布局/权限/隐私/ignore/链接/diff及必要完整离线集成，按主A-009实测macOS/Linux。仅AST/专项/单平台/历史通过不算全量通过；工具缺失如实未验，不以此降低要求。 | A-009；既有质量门 |
| GATE-C04 | 全新、未参与实施、只读 Validator 接收逐字本合同/适用规则/当前受审结果，自行核对完整tracked/untracked/删除/模式/链接及内容SHA，返回根协议八字段；Main再验收。后续语义变更重验，真实协调回写仅核差异。 | A-019/A-020；独立与快照协议 |
| GATE-C05 | 每个清理路径有授权/对象身份、原件与目标摘要、来源/状态闭合、隔离恢复和无外围依赖证据；删除前再核内容未变，未知阻塞保留来源，不先删再试。 | 用户安全清理目标；AC-C02–07 |
| GATE-C06 | 精确提交白名单和暂存内容与受验SHA一致、无私人或未验内容、无远端动作；提交后核对真实commit/tree及保留成果；交付状态只记录实况。 | 用户本地提交目标；根Git/完成协议 |

- INV-C01：本轮源数据只读保护优先；不能靠 checkpoint、删除数据库sidecar、reset/clean/stash、启用旧程序或重复动作制造一致性/绿灯。尚未安全保护的源不覆盖、不删。
- INV-C02：保全与业务导入分离；保留所有原件不授权扩大业务导入/真实下载，不改变已冻结运行实例的不可变身份与原始SHA路径。
- EX-C01：不保证复原任务开始前已不存在且无恢复信息的字节，不把此限制当丢弃现存对象/工作树管理区的许可；不要求任意无标签秘密/隐写识别或扫描无关用户目录。确有缺失、越界、加密/坏载体等未闭合项，报告并暂停受影响清除及完成宣称。
- EX-C02：真实服务、在线认证有效性和真实业务重跑不在本轮验收范围；零调用搬迁不等于它们已经通过。

| 版本 | 状态 | 修订与批准依据 |
| --- | --- | --- |
| VC-001 | frozen | 依据2026-09-14已明确整合目标形成初始合同；后续语义修订需用户批准，保留此原文。 |

<!-- VC-001-END -->

## 历史工作分解（停止驱动本轮；以D-01–03为准）

| 步骤 | 状态 | 输入、产物与门禁 |
| --- | --- | --- |
| C-01 全新 Planner 首次拆解 | done | child f4ee7d58-2917-4139-af84-cdcf7f7dc82c 完成；实际报告已完整读取，规划不是实施验收 |
| C-02 Main 审核及冻结 | done | 本节 VC-001；接受先保护/合成回归/保全/状态/产品/退役/验证/清理/提交的串行依赖，不接受额外产品命令或自动换治理要求 |
| C-03 保护及串行实施（汇总） | pending | C-06–12全部完成后更新，不作为第二写入任务 |
| C-06 来源冻结及保护副本 | blocked | Developer已返回PARTIAL；已复制原件和Git元数据，主隔离fsck异常、DB/分类/恢复语义未闭合；所有源仍留原地 |
| C-06V1 保护缺口独立复核 | done | 全新只读Validator返回INCONCLUSIVE：保护目标SHA/权限适用检查通过、未见仅副本丢对象，但有限Git候选、DB安全/分类/链接载体边界未闭合；非C-04全产品验收 |
| C-06R1 有限保护缺口补齐 | done | Developer返回PARTIAL：只写ignored data/recovery新批次，补齐有限缺失blob候选、6041项DB/sidecar字节保护和分类、嵌套Git形态证据；仍不声称DB一致性/整体C-06完成 |
| C-06R1V 有限补齐独立复核 | done | 全新只读Validator对C-06R1局部证据PASS；PASS仅限ignored证据根记录与字节层证据，不放行C-06/C-04完成、清理或提交 |
| C-07 合成迁移回归先行 | done | 已新增合成保护helper、fixture和contract测试；py_compile/manual harness/diff-check通过，pytest/ruff/mypy因当前解释器缺模块未运行；C-07V局部PASS |
| C-07V 合成迁移回归独立复核 | done | 全新只读Validator对C-07三文件局部PASS；完整pytest/ruff/mypy因环境缺模块仍未知，不冒充全质量门 |
| C-08 有界载体清查及FIT保全 | validating | Developer返回COMPLETE：13116 FIT候选/566唯一SHA保全到ignored data/fit，manifest和audit已生成；待全新只读Validator复核，不表示业务导入完成 |
| C-08V FIT保全独立复核 | done | 全新只读Validator对C-08保全证据PASS：13116候选/566唯一SHA、data/fit目标、manifest、权限/ignore和源边界可复核；仅限字节保全，不是业务导入 |
| C-09 认证/配置/状态搬迁 | blocked | VC-001整套搬迁停止，数据收尾转VC-002/D-01； 依赖C-08；按用户澄清优先保全 data/verification、必要令牌/配置/goal/email和状态账本事实；不合并冲突库，不重新签旧SHA或恢复真实调用 |
| C-10 选择性产品整合 | pending | 历史目标不再续跑； 用户澄清旧代码不重要；除非后续明确要求，不再做旧产品逐项修复/整合，只保留必要数据依赖和事实记录 |
| C-11 场景映射及退役文档 | pending | 历史目标不再续跑； 旧代码收尾降级为必要记录；不再反复验证旧流程，必要时只记录哪些旧能力/资料已被数据保护覆盖 |
| C-12 自检与无外围依赖副本 | pending | 历史目标不再续跑； 聚焦 data/FIT/令牌/配置保护、ignore/权限/manifest和无提交/无服务调用事实；不宣称旧产品完整质量门通过 |
| C-04 全新独立验证及Main验收 | pending | 依赖C-12；只给冻结合同/规则/当前快照，不给Planner推理或实施辩护；完整适用门与恢复核验 |
| C-13 精确清理 | pending | 依赖C-04；Main逐路径再核源与目标，健康/必要恢复资料留主项目，语义改变重新验证 |
| C-14 精确本地基线 | pending | 依赖C-13；Main白名单暂存与本地提交，不推送，核对真实commit/tree |
| C-05 清理及交付（汇总） | pending | C-13/14事实完成后归档，不预写删除/提交/PASS |

## 当前检查点与证据

- Git 门禁：macOS，Git 2.50.1，cwd 与实际根目录均为 `/Volumes/DiskOther/Code/TrainLab`，有效 worktree，分支 main，HEAD `25e8b92cd170809610d2e5feb4dbdb0033594ff2`。2026-09-14 本次复核仍有 45 tracked 修改、2 untracked 文件；没有暂存、提交或分支切换。
- next 已知基准 `7125a30f8d58e948516d72df39c1d5fb8d21d1d3`/codex/m12-completion，存在大量改动；必须由 Planner/Developer 重核，不将旧计数当当前快照。
- `git worktree list --porcelain` 显示 76b6 等既有树和多项 prunable 登记；存在性、未提交成果与共享 Git 元数据仍待完整核对。不能以 prunable 自动判定安全删除。
- 旧盘点仅为线索：主树松散 FIT 5615 份/515 种 SHA，TrainLab-data 有主树集合外 FIT；其余 next/handoffs/旧工作树及嵌套归档、链接和其他载体未闭合。未完成 CRC/时间解析，不声称全部保全。
- 子 Agent 接口恢复：已有 fresh delegate smoke `99563d59-058a-475e-8633-431e2d3a23cf` 实际返回主目录与 63，进程完成时间 `2026-09-14T01:56:43.656Z`，状态 complete/process terminal observed；本会话已再次列出可执行 native agents。`ENV-SUBAGENT-INTERFACE-001` 的接口缺失前提已解除，仅是接口证据，不是产品或独立验收。
- C-06后已建立ignored data/及原件保护副本；本轮只修改公开.gitignore，不覆盖产品、不删除或移动源、不切换正式实例、不调用真实服务、不暂存/提交/推送。保护副本不等于全部FIT及账本已迁移。
- 原 M12 续跑及 next 真实 R7 暂停，历史失败原判定与累计次数不变。
- 协调记录自检：`git diff --check -- memory.md docs/exec-plans/active/M12-fit-weekly-0001-rebuild.md` 与 Python 对新计划空白、唯一 in_progress 步骤、实际 dispatch ID 和本地链接的断言均退出 0。只核对本次协调记录，不是产品或迁移验收。
- blocker_type：`EVIDENCE_PENDING`；诊断状态：`not_triggered`。首次保护结果存在恢复和分类未知，C-06V1已独立复现为INCONCLUSIVE且无新增FAIL；尚无两种修法/三轮不收敛，不触发Failure Analyst。任何清理/覆盖/提交仍暂停。
- 下一动作：按用户澄清转入 C-09 数据与令牌收尾保护；先盘点并保全必要认证/配置/令牌/goal/email/状态账本到 ignored `data/verification`/`data/config` 等主内私有区，不再继续旧代码修复循环。
- 当前环境未知：Planner实测所查Python3.12与29个TrainLab命名临时解释器均缺pytest/Ruff/mypy/fitdecode，Linux只发现CLI而未证明运行环境。未安装、启动VM或放宽双平台门；先查现成环境，确需新增权限另报告。C-06原件保护不依赖真实业务或完整产品测试，完成不表示C-12/C-04已通过。
- 最新基线差异：Planner复核主树45 modified/3 untracked（新增本计划），next87 modified/226 deleted/93 untracked，76b6为17/17；3个可读树暂存为空。00e1/9fe4/e1c3/supervisor Git入口均128，指向旧Projects路径；9项登记路径不存在。主本次又核HEAD未变、暂存为空。

## Agent 派发记录

- C-01：Planner / 首次规划 / fresh context；复杂跨仓迁移及隐私/Git恢复风险，能力 high、推理 high；native 平台支持显式选档。只读仓库和授权外围资料，禁止修改产品/私人数据/协调记录、Git 写操作、服务调用、嵌套派发。报告由工具 output 绑定保存，Main 记录实际 run 与产物位置。
- C-01 已首次完整派发：async workflow `e66bfdbb-c240-4bb8-93c4-d9b41c4b992c`，child key `consolidate-planner-01`，fresh native delegate，单子 Agent/无并行写入；输出通过工具绑定 `consolidate-planner-01.md`，实际 artifact 路径待完成结果核实。原生完成通知唤醒 Main，不轮询等待、不追加提示或续接旧角色。
- Planner已完成：run `f4ee7d58-2917-4139-af84-cdcf7f7dc82c`，workflow完成，实际产物 `/Users/lucas/.pi/agent/sessions/--Volumes-DiskOther-Code-TrainLab--/subagent-artifacts/outputs/e66bfdbb-c240-4bb8-93c4-d9b41c4b992c/consolidate-planner-01.md`。Main完整读取385行；接受核心保全/依赖方案，未把报告中的建议配额/目录/长期迁移模块当新验收要求。
- C-06 Developer：全新native角色，跨仓Git/私人数据保护属high/high；只放行根ignore和主内明确私人保护/恢复位置，不改产品/规则/协调、不写源Git/源实例、不切换/删除/提交/推送。未提供OS沙箱，不声称工具可写权限等于已隔离。
- C-06首次完整派发包：child key `consolidate-developer-c06-01`，准备文件 `/tmp/trainlab-consolidate-c06-dispatch.WiR2Le/workflow.js`，SHA-256 `dc5355944cf7627e4290280184de26d12cb5ab80723888f3d3fa05da34e75e82`；工具静态validate返回ok/无errors。output绑定 `consolidate-developer-c06-01.md`；实际run/artifact在原生通知后的依赖关口回写，运行期间Main不写源仓以免干扰快照。
- 冻结段（BEGIN/END之间原字节）SHA-256：`a33a177a05e60215b1031b82b9286262d1c337864706b910329ebb0add6b338a`；派发脚本已逐字嵌入，不只传计划历史链接。Validator尚未派发。
- 派发准备一次内联Python读取stdin报编码SyntaxError，未启动child、未写迁移产物；核对主HEAD/dirty/暂存并保存协调差异后，改为UTF-8文件读取及ASCII转义生成同一native workflow，生成/摘要/静态validate均成功。未切换其他Agent或执行模式，未发生产品修复循环。

## C-06 实际结果与待复核缺口

- workflow `65523615-491c-459c-a630-e71f7c213905`、child `0355e83f-6d90-423e-b47c-9787179abd1b` 已完成；Developer产物 `/Users/lucas/.pi/agent/sessions/--Volumes-DiskOther-Code-TrainLab--/subagent-artifacts/outputs/65523615-491c-459c-a630-e71f7c213905/consolidate-developer-c06-01.md`。工具完成/ok仅表示进程交付报告，报告为PARTIAL/BLOCKED，不能视作验收通过。
- 私有证据根：`data/recovery/C06-65523615-491c-459c-a630-e71f7c213905/`；只有SEALED-PARTIAL，无完成授权。报告称111900条manifest、69988普通文件/6098312010字节及1058链接原文已保全，9项合成复制检查通过；Main当前仅核核心证据摘要及边界，不把这些数量直接改判独立PASS。
- 未闭合：6041个按名称识别的DB/sidecar条目尚未读取/复制，2特殊项，688名称分类候选，1058链接的目标依赖、7嵌套Git、11不透明容器。名称数量包含合成/缓存候选，不能说全是正式DB/凭据。原源保持，不把容器复制称作全部FIT落入data/fit。
- `C06-F001`：AC-C02/AC-C07；恢复副本主Git fsck exit10，3条cache-tree错误和5个missing blob。是否源既有、复制遗漏、缺失对象可在当前其他保全来源找到，以及影响当前refs还是旧管理区，待独立复核。实施修法0，Validator轮次0，不认定原始资料已被本轮丢失。
- `C06-U001`：INV-C01/AC-C02/AC-C05；DB安全停写/只读锁/零WAL前提尚未建立，保持元数据层；不能据文件名推断正在写入，也不能直接普通SQLite连接或删sidecar。
- `C06-U002`：AC-C04；名称分类和恢复语义需定向核实，不能将550认证类/1459配置类文件数当实际有效凭据或完成迁移；必要资料必须保留且不混入可删除区。
- `C06-U003`：AC-C02/EX-C01；权限映射/配置安全引用造成主与76b6恢复status不等；四个坏入口只能副本映射后读取，旧源status不可读。只保存链接原文/嵌套Git文件不等于全部依赖可恢复。
- Main实查：manifest SHA `d2dc1de9bdcaabe49d868722d99a6a72cd0aa073f0bd6da3339122605989eccb`、seal SHA `f022b93c83a3ff3d7960335773a82db5c5614c6bff379ed04e75cb54bd68e055`、final-audit SHA `cc7269778b010c726259ec1d22663b84d8791b4869ec5d59ccb57c34cafc0c4f`、fsck原证据SHA `aa9fa8c3fe237d4d1e40338eb994dd11157320cedbd457e2ee8b505cac579be1` 均与当前文件相等，均0600；data及三个子树0700；git ls-files data为空；公开.gitignore diff仅/data/及移除误导注释；git diff --check和暂存空检查退出0，HEAD仍25e8b92。未复读全部私有载荷，未执行产品门，不以摘要吻合当全部恢复验收。
- C-06V1派发为fresh/high-high native Validator，工具可执行临时只读检查但禁止改受审树/原保护证据；不提供OS沙箱保证。输入只有逐字VC-001、规则、当前源及客观证据入口/异常，不传此段判断或Developer报告。验证范围仅C-06事实与未完成条件，不把C-07–14未实施当新增当前要求。
- 受审清单 `data/recovery/MAIN-C06V1-m2zc4dbp/snapshot.json`，49项tracked/untracked/删除与模式/链接/内容摘要，SHA `17e4fe313d2ae98991f4eeef90aaf162f49e525ce212e7924beb0a9620432d63`；冻结段另存同目录contract.txt且摘要仍a33a177a…。计划仅合同段参与摘要，本次追加协调事实不改变合同。
- 首次完整派发key `consolidate-validator-c06v1`；workflow `09dfa15d-db7c-4002-acca-0cc46b09292e`、child `4cba20c5-39d6-41e1-b223-cc0acdf1b131` 已完成；报告 `/Users/lucas/.pi/agent/sessions/--Volumes-DiskOther-Code-TrainLab--/subagent-artifacts/outputs/09dfa15d-db7c-4002-acca-0cc46b09292e/consolidate-validator-c06v1.md`。裁决 INCONCLUSIVE：71,046保护目标SHA匹配、data权限/ignore通过；主Git fsck异常源/raw/restore一致且有有限当前候选；DB安全分类、链接/载体边界仍未知。报告不是C-06完成、不是清理或提交授权。
- C-06R1 Developer `cd612d6c-8e61-419d-9aee-faa8a20bb19a` 已完成，报告 `/Users/lucas/.pi/agent/sessions/--Volumes-DiskOther-Code-TrainLab--/subagent-artifacts/outputs/cd612d6c-8e61-419d-9aee-faa8a20bb19a/consolidate-developer-c06r1-01.md`，结果PARTIAL。证据根 `data/recovery/C06R1-20260914T035541Z-30296/`（ignored/private）：6133文件/6961目录，权限0例外；manifest SHA `066319e08044139c37bfc8158c86df8eb903052929501fdbd0781dca53ce7732`，final-audit SHA `142b17f9d303555376d55e19450e2f3be50bc0960044aadd230ae530658293fb`，commands SHA `46b3d98c318484976c096922e09049a6d090a43637ea78938a560ce2d046c506`，final-checks SHA `2bca0ad2fccaf87b5e7794bbdb2b56aef619ef07d3be66547335df9c959bdca8`；Main复核HEAD/branch/暂存空、`git ls-files data`空、ignore和4项SHA一致。剩余风险：DB一致性未知、源Git未修、界外链接和不透明载体未闭合；不是C-04/C-06完成或清理/提交授权。
- C-06R1V Validator `a223d13a-c8a6-44e1-80c4-0d68324f3042` 已完成，报告 `/Users/lucas/.pi/agent/sessions/--Volumes-DiskOther-Code-TrainLab--/subagent-artifacts/outputs/a223d13a-c8a6-44e1-80c4-0d68324f3042/consolidate-validator-c06r1v-01.md`，对C-06R1局部证据给出PASS：4控制SHA、权限/ignore、6125个copied target、6041 DB/sidecar、3个missing SQLite hash-object、U002/U003记录均可复核。unknown保留：DB一致性、C-06整体恢复依赖、原主Git异常、界外链接/opaque carriers和完整产品质量门。
- C-07 Developer `62923ada-1e62-4aea-93f3-7178ff8ac842` 已完成，报告 `/Users/lucas/.pi/agent/sessions/--Volumes-DiskOther-Code-TrainLab--/subagent-artifacts/outputs/62923ada-1e62-4aea-93f3-7178ff8ac842/consolidate-developer-c07-01.md`。新增 `source/skills/_shared/protection_manifest.py` SHA `ae808f03614c7aadd3bb0bff6a552c4d3f5ab33ed8f83317f5c6edd77946b827`、`source/tests/code/fixtures/consolidation_protection_fixture.py` SHA `eb5a5e3d061a958a25c0d38e7428ca7725669f03414dfd5e3c0809a35575f413`、`source/tests/code/contract/test_consolidation_protection_manifest.py` SHA `bbbdbfbd974cac1c07d865dd60b88ffdea706327f3ede8c9de1e482f3d8fd0b0`。自检：py_compile通过、手动执行新测试函数通过、git diff --check通过；pytest/ruff/mypy在当前python3.12环境缺模块退出1，未安装依赖。暂存空，未读取data私有内容。
- C-07V Validator `0a3eccd2-ca04-4f5d-864d-fca08b3911ed` 已完成，报告 `/Users/lucas/.pi/agent/sessions/--Volumes-DiskOther-Code-TrainLab--/subagent-artifacts/outputs/0a3eccd2-ca04-4f5d-864d-fca08b3911ed/consolidate-validator-c07v-01.md`，对C-07局部范围PASS：三文件SHA匹配、合成覆盖/显式source边界/隐私边界/无sqlite网络服务导入通过，py_compile和手动合成测试通过，pytest/ruff/mypy因环境缺模块未运行。
- C-08 Developer `ed00bf56-efb6-4368-a6dd-3f6d8149eba8` 已完成，报告 `/Users/lucas/.pi/agent/sessions/--Volumes-DiskOther-Code-TrainLab--/subagent-artifacts/outputs/ed00bf56-efb6-4368-a6dd-3f6d8149eba8/consolidate-developer-c08-01.md`，结果COMPLETE。证据根 `data/recovery/C08-20260914T042523Z-36541/`、FIT根 `data/fit/`；manifest SHA `00595bde3992cca790f41a94f7febe3ebc581dce7bbfb5548d2ac1a090f5f1de`、final-audit SHA `4b963b5d9bad7595d8e1be7420b8179685cfdf17799c96e846d6c4bb6d2cf43a`、commands SHA `153135041a881cac1a6df5c5e31fbb0a36867d040eb29aca4a917ecbf90a37e8`；Main复核HEAD/branch/暂存空、`git ls-files data`空、ignore和3项SHA一致。报告称13116候选、566唯一SHA、0 unclosed、opaque 12、links 828、special/excluded/unreadable 524。
- C-08V Validator `6e214d34-d196-4c56-a70b-5c9b218e7712` 已完成，报告 `/Users/lucas/.pi/agent/sessions/--Volumes-DiskOther-Code-TrainLab--/subagent-artifacts/outputs/6e214d34-d196-4c56-a70b-5c9b218e7712/consolidate-validator-c08v-01.md`，对C-08字节保全证据PASS：全量复算566个目标和13116候选，当前可读源13116/13116匹配，独立边界扫描集合一致；prior C08目录仅空tmp、0B，不构成重复或遗漏证据。

## Main 审核决策与分步边界

- 接受“全部时间命名原件库”和“原实例 fits/<sha>.fit”职责分离；同SHA来源不丢，无法确认活动时间显式标注未知/保全时间。JSON/DB只处理已发现格式和明确载体，不搞任意隐写搜索；解析限额触顶保留未闭合项，不借限额漏文件。
- 当前只放行C-06，Developer不得顺势整合产品、制作新业务入口、执行正式CLI或清除源目录。先用已存在的工具/临时只读验证和原件复制形成保护证据；不要求为了本轮搬迁新增永久产品CLI。后续需要维护的可执行代码按GATE-C02/03交付测试。
- 主内非可删除 `data/recovery/` 保存Git/工作区恢复与私有证据；`data/verification/` 保存松散认证原件，必要goal/email/配置另存 `data/config/`。认证/goal/email不得打进可删除健康归档；发现其已存在于不可拆分历史容器时保留原容器且严格标记非可删除/不公开，不改写旧原件，必要现用文件另行提取。
- 本步骤不触碰正式SQLite内容或sidecar，不执行status/daemon/reconcile。复制需要一致性：前后源摘要/身份或现行安全快照条件不能成立则保留源并停该项。源仍存、已复制、已核验、未闭合分开记录，不把基础Git副本称作全私人数据迁移完成。
- 根Main目前data-backup约35GiB，next约3.5GiB，handoffs约3.8GiB，主.git约45MiB，76b6约32MiB；只是容量线索。主内既有data-backup暂不再全量复制，自身不在本次自动删除对象，仍需后续FIT载体扫描与必要证据提取。保护工具不递归复制新data/recovery自身。
- 任何source/AGENTS中的旧“尚未交付/不复制私人配置进备份”等文字按本次已确认保全及必要配置迁移用途区分：松散认证/goal/email只进入必要配置区，不入恢复树的普通源码包；旧源不覆盖。产品/规则同批语义同步留C-10/11，不以此授权真实切换。
- 本地依赖安装/VM启停不是Planner检查结果中的已授权事实，本步骤仅查现成环境；不能伪称Linux或全部质量门可用。

## 迭代日志

2026-09-14 数据优先收尾上下文：按用户澄清冻结VC-002，Main保全11份明确令牌/配置，写data/README，核566个FIT目标及既有主DB字节保护定位；D-02独立PASS，Main复核并耐久保存证据，VC-002 completed归档。原件不动、调用0；不声称全部历史数据恢复或旧代码验收完成，不自动续跑旧任务。

| 日期/上下文 | 已完成与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-09-14 主目录恢复 | Planner审核/VC-001冻结；Developer C-06返回部分保护；Main实查核心证据SHA、权限/ignore/Git边界；C-06V1全新只读复核完成；C-06R1补齐ignored私有证据根，C-06R1V局部PASS；C-07新增合成保护helper与contract测试且C-07V局部PASS；C-08完成ignored FIT保全且C-08V字节保全PASS；用户澄清旧代码不重要，重点转为data/令牌收尾 | DB一致性仍未知，源Git未修；opaque/link业务闭合仍按边界未知；没有源删除/产品覆盖/提交 | 进入C-09数据/令牌保护收尾；暂停旧代码修复、产品整合、提交和真实服务 |
