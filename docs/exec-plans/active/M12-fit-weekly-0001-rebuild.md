# 执行计划：M12 FIT 运动数据与每周跑步教练重建

- 任务 ID：`M12-0001..M12-0006`
- 状态：`active`
- 负责人：主协调 Agent
- 执行方式：严格串行；独立只读审查不属于并行开发
- 开始日期：2026-09-05
- 最后更新：2026-09-06
- 当前实施合同：VC-003；下方 VC-002 保留为已完成检查点的历史合同。
- 批准依据：用户批准 M12 后要求开始执行；随后明确增加“每个小功能、模块完成后提交并推送”，并要求立即测试、提交和推送当前项目检查点。除 Git 交付规则外，原 M12 计划不变。
- Roadmap：M12；M11 未完成部分由新方向替代，历史失败不改写为成功。

## 冻结验证合同

- 合同版本：`VC-002`
- 合同状态：`frozen`
- 冻结依据与时点：2026-09-05 用户批准的 M12，以及同日模块提交/推送补充；在本次文件修改前冻结。
- 范围：保留根开发 Harness；在 `source/` 建立 FIT-only、新 SQLite、Python 同步/解析/定时、无状态周 AI、PDF、Gmail REST 和 Garmin 课程发布。旧非核心部分归档，不作为新运行依赖。
- 非目标：健康 API、日报 AI、高保真 HTML 邮件、运行时旧 Harness、cron、开机启动安装、公开私人数据、自动删除旧归档、强制推送、远程分支改写。
- 适用规则：A-004 的合成测试及私人数据边界、A-010/A-011 的 REST-only/单次发送/远端核验、A-016 的设备分区事实边界、A-019/A-020 的冻结验证与诊断纪律继续生效。M12 已批准的新数据源、周频率、Python 调度、固定跑步计划及可删除归档，仅替代旧运行规则中与这些目标直接冲突的要求；不追溯修改历史批次。
- 当前先验收 CP 检查点；下列 M12 功能标准在对应模块实现时验收，不要求尚未实施的模块在检查点提交前已经完成。

| 标准 ID | 可验证要求 | 来源 |
| --- | --- | --- |
| AC-001 | 先保护未提交工作、旧代码和数据；新库独立；现有 FIT 逐字复制、SHA/身份闭合；旧库和非核心部分统一归档，归档不存在时新系统仍可运行 | 原 M12 数据与归档要求 |
| AC-002 | 收集 2022-01-01 起全部运动 FIT；先复用已有文件，完整分页、进度恢复、下载去重；Provider 明确无 FIT 不等于查询失败或无活动 | 原 M12 历史同步要求 |
| AC-003 | 新 SQLite 保存 FIT 索引/解析版本、活动摘要/分段/圈段、同步日状态与缺口、周任务输入/结果、历史周报/课表及外部动作回执；不批量落库所有原始秒级点 | 原 M12 数据落地要求 |
| AC-004 | Easy 跑 2 分钟；SOS 使用明确 work/recovery 圈段、连续主训练 1 分钟；未知跑步 2 分钟且不猜类型；其他运动 5 分钟。区分有效时长、经过时长、暂停、缺口；连续指标按有效时间加权，配速按距离与有效时间计算 | 原 M12 分段规则 |
| AC-005 | AI 只接收本期全部活动摘要/分段、最多前四份完整结构化周报和训练目标快照；没有四周时使用已有份数，不伪造历史报告。所有运动均纳入，不按计划过滤 | 原 M12 周报输入规则 |
| AC-006 | 统一本地细读工具只接受当前任务活动引用、视图和范围/粒度；默认每周最多 20 次、单次最多 20 分钟，相同请求复用。不能读取 SQL/任意路径/命令；不向 AI 提供原 FIT 字节、GPS、路线、活动名称、个人/设备标识或凭据 | 原 M12 有界细读与隐私要求 |
| AC-007 | 一个周任务使用一个全新无状态 AI job，可在该 job 内多次使用本地细读；不依赖会话/resume。Codex 与 Fake 适配实现相同接口；受限工作目录及实际能力限制不能仅由“只读沙箱”或 owner-only 权限假定 | 原 M12 AI 可替换要求 |
| AC-008 | Asia/Hong_Kong 每日 22:00 同步当日、昨日及已知缺口，生成一封简单同步邮件。启动时把停机期间未查询日登记为缺口，待 22:00 补跑；当日未结束仅 provisional，完整分页才可证明无活动 | 原 M12 每日同步要求 |
| AC-009 | 周日 15:00 额外同步并冻结本期，统计上周日 15:00 至本周日 15:00 的半开窗口；活动按结束时间归属且不拆分；之后的运动归下期。下周计划为周一至周日，发布后不因迟到数据重做已发布报告 | 原 M12 周期要求 |
| AC-010 | 多周错过只补最新一期，标题注明原统计时间与“补发”；历史 FIT 继续补齐，不补发历年周报/邮件，不排过去课程、不整体平移计划 | 原 M12 补发选择 |
| AC-011 | 周报包含结论、全部运动清单与统计、最多三项重点跑步技术分析、其他运动影响、简短计划/实际对比、唯一固定七日跑步计划和局限。课程含目的、剂量、步骤、RPE、技术备注及停止条件；没有依据不强行计算指标或安排 SOS | 原 M12 内容与课程要求 |
| AC-012 | 硬负荷最多三次且相隔至少两个完整日历日；不同时增加距离和强度，不补偿漏课，无每日调整/替代课；已知攀岩/力量安排作为负荷约束。运动表现不是健康诊断，不能据此证明没有健康风险 | 原 M12 安全要求 |
| AC-013 | 只展示设备已记录的活动心率/分区时长，可计算时长占比；不从采样重新划区、不推断阈值/目标 BPM。天气仅为已有或 Garmin 按活动 ID 提供的可选背景，不引入 GPS 天气查询 | 原 M12 证据边界 |
| AC-014 | 同一已验证 JSON 生成 Markdown/PDF 与 Garmin 合同；简单邮件包含 PDF 附件；编辑仅在本地发送前，不创建云端草稿。PDF 全页渲染检查中文、图表和课程；RAW 核验收件人、主题、正文和解码 PDF SHA | 原 M12 发布要求 |
| AC-015 | Garmin 保留真实步骤/重复组，读回核对内容和日期；仅按新库记录的精确 ID 管理自己创建的课程，不凭名称删除既有课程。邮件和各 Garmin 动作独立，成功项不因别项失败重做，unknown 只读对账，不盲目重发/重建 | 原 M12 外部幂等要求 |
| AC-016 | Python 提供 import-history、sync、weekly、daemon、status、reconcile 和本地编辑入口；用户每次手动启动，无 launchd/cron/登录启动项；进程退出后不假称仍受守护。业务身份和资源不写死本机绝对路径 | 原 M12 部署选择 |
| AC-017 | 离线验收通过后才进行历史同步与真实验收；首份真实周报在验收后的下个正常周日 15:00。首轮为一次同步及同步邮件、一次周 AI/PDF 邮件、该计划实际跑步课最多每天一项/七项；模型失败不自动重试 | 原 M12 首次真实运行选择 |
| AC-018 | 验收后切换新库、停用旧入口，提供手动启动、状态、停止、补数、对账和回滚说明；回滚不自动删除远端邮件/课程或启用旧程序 | 原 M12 切换要求 |
| AC-GIT-001 | 每个可独立交付的小功能/模块完成适用测试和独立验证后，做边界清楚的本地提交，并正常推送已配置远程分支；不混入未验证的其他工作、私人数据或测试产物。记录提交 ID、模块和推送核验；失败如实保留未推送状态 | 本次用户明确补充 |
| AC-CP-001 | 本次立即保存当前非私人工作为“新方向替代旧方向”的检查点；保持既有代码、测试和失败证据，不宣称 M11 成功或 M12 实现完成；计划只增加 Git 交付规则 | 本次用户检查点要求 |
| AC-CP-002 | 检查当前全部拟提交 tracked/untracked 文件，排除 goal、email 私有配置、凭据、Token、state/raw/FIT/SQLite、Candidate、测试结果、缓存及 data-backup；推送前核对目标、待推历史和受审内容，无强推/分支改写 | 用户要求与项目隐私/Git 边界 |

| 门禁 ID | 检查及预期 | 来源 |
| --- | --- | --- |
| GATE-001 | `cd source && python -m pytest tests/code -q`、专用 Ruff check、format-check、mypy、只读 AST/compile、全部 JSON Schema、Skill metadata、AI 布局全部通过 | 已有质量门与原 M12 |
| GATE-002 | Markdown 链接/围栏、权限、隐私、Git ignore、布局、tracked/untracked 差异和 `git diff --check`；拟提交内容及待推历史无私人数据 | 原 M12 与本次检查点 |
| GATE-003 | 实现后的迁移、归档不可用、完整分页/缺口、解析/细读、安全、PDF 全页、响应丢失/重放、定时补发回归通过 | 原 M12；适用模块完成时执行 |
| GATE-004 | 全新只读独立验证绑定合同、基准与当前文件摘要；检查点只验 AC-GIT/AC-CP 及 GATE-001/002，后续按对应模块及最终完整合同验收 | 执行协议与原 M12 |

| ID | 不变量、威胁与排除项 | 来源 |
| --- | --- | --- |
| INV-001 | 当前检查点不写正式 state/私人配置、不调用业务 Provider/真实模型、不安装调度；M12 后续正式切换与在线动作仍须先满足已批准前置门 | 检查点范围及原 M12 |
| INV-002 | 不删失败记录、不改正确预期制造 PASS；退役测试必须按已取消的业务范围逐项归档，适用安全测试保留/迁移 | 原 M12 测试分类要求 |
| TM-001 | 正常崩溃、网络/认证错误、分页不全、重复执行、损坏 FIT/输入、跨活动证据、隐私越界和外部结果丢失 | 原 M12 有限风险 |
| EX-001 | 恶意同 UID/root、永久内核/硬件故障不作为应用层绝对保证；不因新检查临时扩大验收 | A-010 与原 M12 |
| EX-002 | 检查点不是修复旧 M11 canary 的任务，不运行旧真实模型/投递批次，也不是 M12 功能交付完成证明 | 用户“其他不改”与当前检查点 |

### Git 条款修订原文

- `VC-001` 原 M12 条款：本阶段不提交、不推送；其余业务、测试、归档与真实验收要求为上表 AC-001..018 及适用门禁。
- `VC-002` 仅替代上述 Git 禁止条款：每个小功能、模块完成适用测试和独立验证后提交并推送；立即对当前项目检查、提交和推送一份新方向检查点。未改变原任务内容、顺序或验收。

| 版本 | 状态 | 变更 | 人工批准依据 |
| --- | --- | --- | --- |
| VC-001 | superseded | 原 M12 初始批准，禁止提交/推送 | 用户“开始执行上面的计划，直到完成” |
| VC-002 | frozen | 仅增加模块提交/推送与当前检查点授权 | 用户“每一个小功能、模块已经完成后，应该提交并推送至远程”及“真正提交远程” |

## VC-003：原计划执行续批

- 状态：frozen；依据用户 2026-09-05 批准《M12：FIT-only 每周训练系统重建执行计划》并要求执行直到完成。
- VC-002 原文保留为检查点历史；VC-003 继承 AC-001..018、AC-GIT-001、INV-002 和有限威胁边界，检查点专用 AC-CP/INV-001/EX-002 不作为新功能完成要求。
- 新增已批准验收：归档旧功能时逐项映射保留/迁移/退役测试；新保留运行路径应支持 macOS/Linux，不继承旧 Darwin 专用接口；在线清单未完整冻结或缺授权时保持零调用。
- 原六任务顺序不变。每个可独立交付模块通过当前适用完整门和全新只读 Validator 后，正常提交并推送 origin/main；未验证模块不混入提交。
- 当前子模块 `M12-0001a` 为独立归档工具及真实备份，不删除/移动旧源码，不切换正式 state，不运行任何业务 Provider/模型。后续 `M12-0001b` 才完成测试退役映射和旧入口退出。

| 当前模块标准 | 冻结要求与来源 |
| --- | --- |
| ARC-001 | 用既有只读锁、零 WAL、immutable SQLite Backup 保护正式数据；源码及 state 生成逐文件清单和 SHA；正式输入前后完整指纹一致。来源 AC-001 与本次批准的只读备份要求。 |
| ARC-002 | 归档位于被忽略的统一 data-backup/m12-legacy-时间目录，目录 0700/文件 0600；不复制凭据、Token、goal、邮箱配置或其他私人运行配置；它们留在当前私有位置。来源本次批准的归档/配置边界。 |
| ARC-003 | 归档只在清单、SHA、SQLite integrity/FK 和隔离恢复演练通过后发布成功；失败保留未完成证据，不覆盖既有归档；旧数据不删除。来源 AC-001。 |
| ARC-004 | 非零 WAL、锁缺失/竞争、非法路径、链接/特殊文件、复制中断和源漂移必须安全失败；成功副本可恢复且不依赖原目录。来源 TM-001 与 AC-001。 |
| ARC-GATE | 先写合成回归；执行对应 pytest、Ruff、format、mypy、compile/Schema、Markdown、隐私和 diff；复验当前完整 suite，保留既有时序和 Linux 失败事实；全新独立归档 Validator 后才提交/推送。来源 GATE-001/002/004 与 AC-GIT-001。 |

## 工作分解

| 步骤 | 状态 | 依赖/证据 |
| --- | --- | --- |
| M12-0001 当前检查点：计划补充、完整代码门、隐私/范围审查、提交及推送 | completed | `0decf99` 已核对 `origin/main`；143 项公开工作检查点；不重做 M11 |
| M12-0001a 只读归档工具、备份清单与恢复演练 | completed | VC-003；独立 PASS，9612 文件恢复通过；Git 交付记录见下 |
| M12-0001b 旧规则替代映射、旧入口及测试同步退役 | completed | 独立 PASS；旧入口退出，38 份旧测试继续执行，物理清理随替代模块验收进行 |
| M12-0002 新库、已有 FIT 复制与分页/每日缺口同步 | completed | 0002a–e 独立PASS并已推送；仅内部离线功能，真实全历史同步留0006，邮件/调度留0004/0005 |
| M12-0003 分段解析、统一细读、AI 输入隔离与可替换接口 | in_progress | M12-0002；先完成0003a纯FIT解析/分段与不可变解析落库 |
| M12-0004 周报、固定计划、Markdown/PDF、Gmail/Garmin 通用发布 | pending | M12-0003 |
| M12-0005 Python 定时与恢复、完整离线验收 | pending | M12-0004 |
| M12-0006 历史同步、下个正常周日真实验收及切换 | pending | M12-0005；未来时点未到不得冒称完成 |

每个模块在上表相应任务内细分提交，不新增并行分支/worktree。旧测试按保留、迁移、随退役范围归档分类；不要求永久保留已经明确取消的全部旧功能测试，也不得借归档删除适用安全场景。

## 当前检查点

- 当前焦点：M12-0003c完整周活动证据独立PASS，准备Git交付；仅合成输入，不切换正式库或联网。
- 基准：`db8a3ab7ec31c6bebe32742e785760df4650c97f`，`main`；刚完成的开发 Harness 更新属于已有工作，不覆盖。
- 下一动作：提交推送周证据模块；继续前四份周报/目标及模型适配，实际工具隔离另行验收，当前不提供模型或在线命令。
- 阻塞项：无；`blocker_type=none`，`diagnosis_status=not_triggered`。
- 未交付：完整周输入、模型适配、周报告/发布、调度和在线切换；FIT解析/分段和受限细读已独立PASS，同步编排、MCP协议适配、同步日期及分页、新库和已有FIT复制已交付。

## Agent 派发

| 角色/任务 | 目标与合同 | 风险/档位 | 写入边界 | 产物与门禁 |
| --- | --- | --- | --- | --- |
| 只读提交范围审计 / M12-0001 | 当前拟推文件/历史的隐私与范围，AC-CP-002 | high/high；跨文件私人数据边界；平台支持显式选择 | 不修改文件或 Git，不读凭据内容 | 路径/风险/复核依据；不是产品功能 Validator |
| 全新只读 Checkpoint Validator / M12-0001 | 逐字 AC-GIT/AC-CP、INV-001/002、EX-002 与 GATE-001/002/004 | high/high；正式提交前完整独立核验 | 不修改文件、Git、正式 state 或 Provider | 协议八字段结论及当前快照证据 |

## 验证与交付记录

### M12-0003c 本周完整活动证据

- 全新只读high/high `m12_weekly_evidence_validator` 返回当前模块PASS，无blocker；独立完整1197 passed / 173.91秒、专项33项、全静态门通过。另测真实适配器/Fake SDK两页21活动三运动、四处嵌套隐私、锁竞争及重放；9356项私人指纹两次不变。六文件结束与清单SHA `a8438709d7ed858676cf1123172d1659c2c055597f1721c1a4f982bf6f9d4e85` 完全一致，基准91381c8。PASS不涵盖模型输入历史/目标、实际能力隔离、Linux实测或在线。
- Validator首次快照脚本未指定Git根、首次分页探针缺next_page，均为检查方法错误；分别修正检查命令/合成探针后通过，未修改产品/测试/合同。本段仅真实验收结果回写，随后执行授权提交推送。
- 协调者补验M12合计288项通过；9356项私人指纹不变。后续Codex能力边界只读核对使用OpenAI官方配置文档及本机CLI帮助/feature list；无真实模型job或Provider调用，不把帮助参数存在当作实际隔离证明。
- 先新增15项回归；首次Fake SDK参数误用save_dir/无FIT结果形式，按实际固定MCP协议改正后全部因缺少待实现模块失败。实施后追加18项覆盖；其中按结束时间排序先失败后修正。现33项专项、完整1197 passed / 169.03秒；旧测试未修改，未调用真实模型或Provider。
- Ruff/format147、mypy129、127 AST/compile、100 JSON/90 Schema、91 Markdown/57链接及全部静态门通过。安排全新只读high/high Validator，风险为同步分页到FIT的完整来源、日期归属与冻结恢复；只接收逐字VC-003、适用规则及当前结果，不继承历史verdict。
- 按既有AC-003/005/009实施：从新库已完成同步及所有登记FIT选取本周结束的活动，不按课表过滤；保留Provider明确无FIT的未知结束时间说明，不把它当作无活动或编造指标。半开窗口、长期活动跨起点、所有运动类型、来源/权限/SHA及搬迁重放先写合成回归。
- 本子模块只冻结运动证据，不读取goal/历史AI正文、不创建模型attempt，不宣称最终模型输入已完成。首次冻结后迟到数据留后续任务处理，不改写已经冻结的同一期；历史报告与目标会在后续模型输入模块接入。

### M12-0003b 预绑定周范围与受限细读

- 已核对该提交Linux CI [34004085434](https://github.com/wyizhou/TrainLab/actions/runs/34004085434)：M12 portable module tests通过；旧完整Test失败，后续门跳过，Linux整体尚未PASS。
- Git交付：`91381c83d2c66993cc5b864644d4a04ff20eb30c`（`feat: add bounded resumable weekly FIT detail host`）已正常推送origin/main，ls-remote完全一致。
- 全新只读high/high `m12_fit_detail_validator` 返回当前内部模块PASS，无blocker；独立完整1164 passed / 171.61秒、专项36项、Ruff/format145、mypy127及全部静态门通过。额外三视图隐私、Schema、暂停加权、跨活动绑定与周边界探针通过，9356项私人指纹不变。六文件结束摘要与清单SHA `d471c554a4f35966a83a444f5aaeb6d4e05208031c6867f4170b6e7efc0a5865` 一致，基准1598af1。当前PASS不代表完整周inventory、模型能力隔离、Linux实测或在线运行。
- Validator首次使用直接pytest出现3项ModuleNotFoundError收集错误，改用冻结门禁python -m pytest后完整通过；未修改产品、测试或预期。本段仅真实验收结果回写，随后按授权提交推送。
- 完整1164 passed / 173.06秒；专项36项/M12合计255项、全部静态门通过，9356项私人指纹不变。当前冻结六文件，安排全新只读high/high细读Validator；高风险为跨重启预算、并发及输入/输出权限边界。仅提供逐字VC-003、适用规则及当前结果，不读取历史verdict；没有实际模型、Provider或外部动作。
- 25项失败测试先行后实现，现36项专项、255项M12通过。新接口只接受当前范围活动/视图/整数范围/1或5秒粒度；共享新库持久化scope、intent和结果，20次/每次1200秒预算不因重启或搬迁重置。成功及确定性失败缓存、真实进程退出、并发最后额度、结果SQL中断和原FIT漂移已有合成回归。
- 细粒度输出明确是time_weighted_bins_not_raw_samples；记录实际采样数，不把插值窗口冒充设备每秒记录。复用已验证解析器和本地注册统计Schema，不接旧每日细读器或旧库；当前没有模型工具暴露或完整周输入构建。
- Ruff/format145、mypy127、125 AST/compile、99 JSON/89 Schema、90 Markdown/54链接及静态门通过；正在完整回归，尚未独立验证/提交本模块。后续全新只读high/high Validator仅按VC-003当前AC-006、存储/隐私/恢复与适用门验收，不继承历史结论。

### M12-0003a FIT解析与分段

- 已核对解析提交Linux CI [34003035898](https://github.com/wyizhou/TrainLab/actions/runs/34003035898)：M12 portable module tests通过；旧完整Test失败、后续门跳过，Linux整体尚未PASS。
- Git交付：`1598af1f1408f1f73e77f3a83356aea404751d97`（`feat: parse FIT into private time-weighted activity summaries`）已正常推送origin/main，ls-remote完全一致。
- 全新只读high/high `m12_fit_parse_validator` 返回当前模块PASS，无blocker；独立39项解析、完整1128 passed / 191.30秒、Ruff/format143、mypy125及全部静态门通过。额外暂停跨段/多session逆序分区、真实profile单位检查通过；9356项私人指纹不变。基准9f8fb76、八文件清单SHA `200f290547c1f2be2bb513ad3543ced12fdc0fecf9a9757e5a74ed4ec67d5cb9`，结束逐项无漂移。
- Validator单位检查首次误用不存在的FitDataMessage.get，检查脚本退出1；改用实际frame.fields后通过，未修改产品或测试，不作为产品失败。当前PASS不涵盖细读/AI/真实运行；提交推送尚待实际核验。本段仅真实结果回写。
- 同快照旧M9失败单项1 passed / 0.64秒；随后没有并行测试的完整复跑1128 passed / 209.54秒。未改旧测试或调用器，首次失败仍保留为根因未定的时序现象。当前冻结八文件后交全新Validator，不将自检当作独立结论。
- 先写24项真实CRC合成FIT失败回归后实现，再补暂停跨界距离、端点计数、损坏/重复圈段、多session分区唯一绑定与存储回滚，现39项专项及219项M12通过。只持久化摘要、圈段、分段与方法，不存原始点；旧测试原字节未改，未读取私人FIT。
- 首次完整结果为1127 passed / 1 failed（182.68秒），失败为未修改的旧M9 `test_log_budget_is_bounded_and_result_is_not_published`，`ai_process_stop_unconfirmed`；保留实测，不删除测试或调整断言。将单项确认后串行复跑同快照完整门，尚不声明全量通过。
- Ruff/format143文件、mypy125文件、123 AST/compile、98 JSON/88 Schema、89 Markdown/52链接及静态门通过；9356项私人指纹不变。后续需全新只读high/high解析Validator，风险为时间积分、证据归属及私人字段投影；只接受VC-003、适用规则及当前结果，不继承历史裁决。

### M12-0002e FIT同步编排

- 已核对同步提交Linux CI [34001692108](https://github.com/wyizhou/TrainLab/actions/runs/34001692108)：M12 portable module tests通过；旧完整Test失败、后续lint跳过，不声明Linux整体PASS。
- Git交付：`9f8fb76cac78319dc4f9479c52b048635a919d0a`（`feat: complete resumable FIT-only sync orchestration`）已正常推送origin/main，ls-remote完全一致。
- 全新只读high/high `m12_fit_sync_closure_validator` 返回当前模块PASS；独立59项编排/日历、180项M12、完整1089 passed / 213.29秒与全部静态门通过，9356项私人指纹不变。基准d501494、六文件清单SHA `2dd6b49d09f5626e4b8a8a387f04eb6dfcc4cc096459c856d4f7cbae0c894385`；源码和合同逐项复核不变。本段仅真实结果回写，未将旧FAIL改写。
- 非阻断观察：合成initialize主动写Token再抛错时，初始化错误统一为session_unavailable，而退出审计失败会持久化blocked。固定实际guard禁用登录/刷新，当前没有合同内正常写入的证据；按EX-001保留观察，不据此临时扩展永久阻断要求或自动再修一轮。真实在线、Linux整套、AI/PDF/发送与M12整体仍未验收。
- 原合同内修正完成：四项认证失败叠加中断回归先全部失败，修正后31项编排/180项M12与完整1089 passed（232.88秒）；成功页仅采用一次，较早未确认领取保留unresolved_calls。Ruff/format140/mypy122、120 AST/97 JSON/87 Schema、88 Markdown/49链接、metadata/AI/ignore/layout/diff通过；私人9356项不变。重新冻结六文件，交另一名全新只读high/high最终Validator，不提供本节历史结论作为输入。
- 首次全新 `m12_fit_sync_validator` 返回FAIL：认证初始化失败遗留未完成page0领取，再在capture后SQL前中断，restore_inventory把同一capture写给两个ordinal，第三次恢复出现inventory_saved_page_invalid。关联AC-002/008、TM-001、GATE-003；独立1085项通过不抵消缺陷。原六文件清单SHA `1a697a420308d1845b316aa369e7920d3b951e73f612d3795db5b1bbbcc9e9e5` 永久保留；本模块未提交。
- 当前在原VC-003内合并修复首次发现的恢复特征，新增认证失败＋capture中断、已完成分页＋下载失败等组合；不改变合同，不继承旧PASS。这是该特征首个修正批次，未触发两种修法或三轮不收敛诊断门。
- 最终完整1085 passed / 226.65秒，27项编排/176项M12通过；Ruff、format140、mypy122、AST/Schema/metadata/AI/Markdown/ignore/layout/diff通过，私人9356项指纹不变。当前六项文件冻结后交全新只读high/high Validator，读取逐字合同摘录、适用规则与当前结果，不加载历史verdict或协调记忆；高风险为跨模块持久状态和恢复，明确禁止任何仓库写入、真实Provider、模型或Git变更。本段不是独立PASS或已提交声明。
- 首轮1084 passed / 183.14秒；额外目录mkdir后fsync失败重放回归先失败后修复，现27项专项通过，正在新快照最终完整门。Ruff、format140文件、mypy122文件、120 AST/compile、97 JSON/87 Schema和88 Markdown/49链接通过；9356项私人指纹未变。未用前一快照结果替代最终验证。
- 首批8项失败测试后实现，新增持久化和真实进程退出等回归至26项；保留日历28项及所有旧测试。共用分页生成器，SDK生命周期保持同一Task；每次Provider前先提交intent、capture与判定闭合后才进入SQLite。
- 当前合成验收覆盖已知FIT复用、明确无FIT、跨重启预算、Token审计阻断、完整查询但未收集完的任务、capture恢复、权限/清单与可搬迁重放。正在完整门禁；尚未独立验证或提交本模块，不调用真实Provider或模型。

### M12-0002d FIT-only MCP协议适配

- 已核对该提交Linux CI [33999404939](https://github.com/wyizhou/TrainLab/actions/runs/33999404939)：M12 portable module tests通过，旧完整Test失败，后续lint跳过；保持分开记录，不声明Linux整体PASS。
- Git交付：`d501494e324d24f1e43050bb115cfed1c88f90a8`（`feat: add private FIT-only Garmin MCP adapter`）已正常推送origin/main，ls-remote完全一致。
- 全新只读high/high `m12_garmin_closure_validator` 返回当前范围PASS；独立1058 passed / 207.95秒，53项适配/149项M12及全部静态门通过。21种非法响应额外探针、诊断保留等级/删除私有内容/恢复工厂/其他logger不受影响通过；固定MCP源码独立核对一致。
- 验证绑定基准6cfc315与五项清单SHA `2a4fa03025f36a5565ceda79373984828cd5571b093fd5262cecc402378f32ec`；VC-003不变。未将旧FAIL改写，未调用真实Provider；本段只回写结果，随后正常提交推送，不预判下一模块或Linux整体通过。
- 原合同内修正后：53项适配/149项M12/完整1058 passed（188.49秒）；Ruff、format138文件、mypy120文件及118 AST/compile、97 JSON/87 Schema、87 Markdown/46链接和静态门全部通过；9356项私人指纹不变。宿主SDK记录在handler前脱敏且恢复原工厂，关闭/认证文件IO错误统一固定码；四项新回归先失败后通过。当前重新冻结，旧FAIL永久保留，尚未提交/推送。
- 首次全新 `m12_garmin_adapter_validator` 返回FAIL：实际MCP SDK解析非JSON时宿主logger包含原文，且关闭factory异常直接向外抛出私有文本。关联AC-006/TM-001/GATE-002/003；其余49项及独立1054项通过不抵消该发现。原清单SHA `07089a04be784b942f83a7b87f9b395a5db17c1d34abebd5f075ce35a726f4ef`，未提交本模块。
- 按原合同合并为一次错误边界修正：先用真实SDK＋内存合成流和关闭故障新增失败回归，再收敛宿主诊断与固定关闭错误。当前是该失败特征首个修正批次，未触发失败诊断门，不改变VC-003或扩大威胁模型；完成后重新完整门和全新Validator。
- 最终完整1054 passed / 192.59秒；M12专项145项、适配49项通过，Ruff/format138文件、mypy120文件、118 AST/compile、97 JSON/87 Schema、87 Markdown/46链接、metadata/AI/ignore/layout/diff通过。五项当前文件冻结，进入全新只读high/high协议适配Validator；代码审查与后续真实采集授权分开。
- 依据本地固定commit源码核对分页和下载原始合同；新增40项失败回归后实施，再补SDK生命周期、完整合成下载入库、错误capture、缺失响应及Token/暂存隔离后49项通过。此层仅内部协议，不提供在线命令、不自动启动MCP、不承担后续SQLite编排。
- 先前1051项全量通过（160.89秒）；追加3项目录隔离回归后重新运行最终完整门，不能将先前快照当作最终验收。保留原通用认证保护/精确依赖，没有恢复健康工具或旧日报流程。
- 当前只使用合成Token和Fake SDK/MCP；真实Provider、模型及external action均为0；正式/private9356项指纹未变。当前尚未独立验证、提交或推送本模块。

### M12-0002c 同步日历与分页账本

- 已核对该提交Linux CI [33997751723](https://github.com/wyizhou/TrainLab/actions/runs/33997751723)：M12专项通过，后续旧完整Test为48 failed/957 passed，含既有candidate_atomic_swap_unavailable；不将整体CI声明为PASS，也未删改旧平台测试。
- Git交付：`6cfc315de9157fa22a0f347df1d58598e848630d`（`feat: add resumable FIT inventory and sync calendar`）已正常推送origin/main，ls-remote完全一致。
- 全新只读 high/high `m12_sync_validator` 返回当前范围PASS，无blocker；独立完整1005 passed / 172.18秒、28项专项和96项M12测试及全部静态门通过。独立额外验证了v1四表保留、升级锁、第二页崩溃预算、重放、缺口、不可变表和跨年/闰日。
- 受审基准57e2641，七项清单SHA `4ebef046724458946791e4ac157530637cd7cd9305aed762674a66540a12a13a`，逐字VC-003摘要不变。Provider调用数为已领取预算的保守上界，未落响应用unresolved_calls披露；Linux动态与真实MCP不属于该次本机验收。以下历史“待验证”文字保持为过程记录，本段仅真实结果回写。
- 先写25项失败回归，再实现新库v2显式事务升级与同步模块；追加真实进程退出、升级DDL回滚和末页回执恢复后28项通过。M12全部96项、完整1005 passed / 160.69秒，Ruff/format136文件、mypy118文件、116 AST/compile、97 JSON/87 Schema、86 Markdown/43链接及全部静态门通过。
- 当前只实现内部查询发现接口，不调用Garmin MCP、不下载新FIT、不发送同步邮件。完整分页才写complete/provisional；缺口持久化，预算领取先落账，恢复不重置预算；非空inventory的collection_complete保持false。
- v1实例不自动迁移；新库upgrade为事务性显式操作，失败不留下部分Schema。之前510FIT的真实v1实例及正式旧state保持不变。冻结本模块后安排全新只读high/high Validator，当前未提交。

### M12-0002b 一次性登记 FIT 导入

- Git交付：`57e264114a4442391ba749a574f5072eac8bf1f6`（`feat: import registered legacy FIT files into independent store`）已正常推送origin/main，ls-remote完全一致。
- 先写14项失败回归，再实现迁移器；补充相对路径CLI/脱敏错误后15项通过。只读取已验证归档的登记FIT白名单；不导入健康/未登记文件/旧AI/动作，不把复制成功当作完整历史覆盖。
- 完整976 passed / 166.33秒；Ruff、format134文件、mypy116文件、114 AST/compile、97 JSON/87 Schema、85 Markdown/42链接、metadata/AI/ignore/layout/diff通过。旧38份测试未改；当前无真实复制、在线或模型调用。
- 下一步为全新只读high/high导入Validator，VC-003当前AC-001/002/003与适用门；通过后才在仓库外新实例进行真实本地复制并复核不依赖归档。当前尚未提交本模块。
- 协调者继续核对旧build_candidate/verify_state时发现路径适配错误：raw_files.relative_path相对state/raw，而初版实现和fixture误按state处理。首轮审查取消（不得作为PASS），审查者回收自建全量进程；没有真实复制。先改正合成fixture并新增失败回归，再修复固定raw根连接；这是AC-001实施修正，不变更合同或放宽路径要求。
- 修正后16项专项、完整977 passed / 162.68秒和全部静态门通过。已验证归档的只读前检确认510 FIT、71,257,974字节，全部登记/身份/日期/大小/SHA/CRC有效；未创建新实例或调用Provider。重新冻结5项文件，另交全新Validator。
- 全新只读 high/high `m12_import_closure_validator` 代码/合成预检PASS：独立977 passed / 165.66秒及全静态门；5项清单SHA `7bd570be404d77f82e80b5357a16f460d47ace385a37d923a774723525b28da0`，基准30ad925，VC-003摘要不变。
- 通过后已将510个FIT、71,257,974字节复制到仓库外owner-only新实例；未切换正式库。完整重放回执相同、DB字节SHA/行数/文件均零增量，parses=0、documents=1；没有生成AI内容或调用Provider。
- 2026-09-06同一只读验收角色完成真实结果补验PASS：逐文件原字节/SHA/CRC/身份、SQLite integrity/FK、0700/0600/无链接、新实例及源前后指纹全部通过；原归档9664项、正式/private9356项不变。私有结果绑定SHA `24663017b1b4b0672c9356ec8b1ad5a3afaca967a27132085b9baf8743ebba7a`；历史分页覆盖仍为not_established。准备本模块正常提交/推送。

### M12-0002a 独立存储基础

- Git交付：`30ad925321f5f764d6ad3eb9ba2acc50e19d05cd`（`feat: add portable immutable FIT storage`）已正常推送origin/main，ls-remote完全一致。
- 该提交的Linux CI [33971956269](https://github.com/wyizhou/TrainLab/actions/runs/33971956269) 中M12专项成功；后续旧完整Test为48 failed/913 passed，含既有Darwin candidate_atomic_swap_unavailable，后续lint步骤未运行。新模块Linux专项与整套CI结论明确分开，未隐藏旧失败。
- 先写失败回归后实现独立 storage；24 项新测试通过，包含真实 CRC 合成 FIT、SHA/身份冲突、跨实例错误、不可变解析/文档、SQL 回滚孤立文件重放、锁、权限、Schema/文件漂移与有限 IO 失败。
- 当前仅实现 fits/activity_fits/parses/documents 四张基础表；没有复制旧数据库，也未建立正式新实例或导入真实 FIT。同步日期、分页、在线采集和任务动作状态留在本任务后续子模块，不把通用存储当作这些功能已完成。
- 实际 fitdecode 类型接口已从本地安装包核对并补齐 stub；未屏蔽 mypy。完整 958 passed / 165.34 秒，Ruff/format 132 文件、mypy 114 文件、112 AST/compile、97 JSON/87 Schema、84 Markdown/42 链接及 metadata/AI/ignore/layout/diff 通过；9356 项正式/private指纹不变。
- CI 新增 M12 专项 Linux 测试步骤，原完整 Test 门不删除或忽略；YAML 解析通过。当前尚未推送本模块，不能预判 Linux 动态结果。全新只读存储 Validator 待执行。
- 第一名独立存储 Validator 返回 FAIL（TM-001/GATE-003）：rename 后目录 fsync 有限失败留下目标文件，精确重放直接返回并提交索引，未补持久化确认。受审清单 SHA `14a2687657edf99df8f391fb8e9dad4062e46e6f44ee8fae67cb14b31b8688c2`；独立 958 项和额外真实进程退出/搬迁检查通过不抵消该发现。
- 原合同内修复一次：先新增3个重放/文件fsync失败/目录fsync失败回归，旧实现全部实测失败；复用路径补文件及目录 fsync，失败不提交 SQL。未触发“两种修法/三轮不收敛/合同冲突”诊断门，VC-003 不变；等待完整复验与全新 Validator，不沿用旧 PASS。
- 修复后：专项27项、完整961项（159.70秒）、Ruff/format132文件、mypy114文件与全部静态门通过；进入全新只读最终存储验证，当前仍未提交该模块。
- 最终存储审查第1次未形成实现裁决：Validator定位合同时对计划全文搜索，意外读取旧结论/修复叙述，自报GATE-004输入隔离失效并返回INCONCLUSIVE；未发现新的实现阻塞。保持validating、代码和合同不变，另给全新Validator逐字合同摘录，避免再次搜索完整历史。这不计为新的实现失败修法。
- 全新只读 high/high `m12_storage_closure_validator` 返回当前范围 PASS；专项27项，独立最终全量961 passed / 158.84秒，完整静态门及真实进程退出、带数据搬迁、四表不可变检查通过。首次全量960 passed/1 failed（旧M9 log-budget测试 ai_process_stop_unconfirmed），同快照单项和再次全量通过；保留未确定根因的时序不稳定事实，未修改旧测试。
- 受审基准 `1ec7cbbfebf0f8c918082a7297ccc2511fac220c`，10项清单SHA `28ec6b0da1cc8b656703c8478486532696b52868670dc7afdbe40567981dc425`，VC-003摘要不变。9356项正式/private指纹零变化；本段仅真实结果回写，随后执行该模块提交/推送，不预判Linux动态结果。

### M12-0001b 旧入口及迁移清单

- Git 交付：`1ec7cbbfebf0f8c918082a7297ccc2511fac220c`（`refactor: retire legacy daily route for FIT-only weekly system`）已正常推送 origin/main，并用 ls-remote 核对一致。

- 三项回归先失败后实现；旧 auto.txt 只返回零动作退役通知，source/AGENTS 与索引不再引导旧日报流程。A-021 记录用户已批准的新方向替代关系，M11 v4 未完成部分取消归档，未改写旧失败。
- 38 份旧测试原字节/SHA 保留，逐文件登记继续执行、适用安全场景、取消业务和目标模块；未在新等价测试完成前删除通用 Gmail/Garmin/解析能力。物理移除在对应替代模块验收后执行，不把本阶段称为旧代码已全部清理。
- 完整 934 passed / 155.26 秒；Ruff、format 128 文件、mypy 110 文件、109 AST/compile、97 JSON/87 Schema、83 Markdown/42 链接、6 metadata、AI/ignore/layout/diff 通过；9356 项正式/private 指纹未变。
- 全新只读 high/high `m12_retirement_validator` 返回 VC-003 当前范围 PASS；独立完整 934 passed / 153.96 秒、专项3项及全部静态门通过。38份旧测试字节和M11原失败正文保持不变；未运行Linux/Provider/模型，不预判后续新功能完成。
- 受审基准 `afdb8c06436949b1f1608133b03366c28e5bf55b`，15项清单 SHA `9d8faa9b0b2d5b94e9437f7631ff83bf97b21b399fd3199ea12bdc9146b39ad7`，VC-003 SHA不变。本段及Roadmap仅真实结果回写，不变更受审合同/产品语义。

### M12-0001a 归档模块

- Git 交付：`afdb8c06436949b1f1608133b03366c28e5bf55b`（`feat: add verified legacy archive for FIT-only rebuild`），正常推送 origin/main 成功；`git ls-remote` 已核对完全一致。

- 2026-09-05：先新增失败回归，缺少实现时实测失败；随后实现独立标准库归档器，22 项合成回归通过，全部现有用例仍保留。
- 完整 pytest：931 passed / 151.68 秒；Ruff check、format 127 文件和 mypy 109 文件通过。新增工具只用标准库，不引入平台专用 rename swap、旧 state 模块或 Provider。
- 真实归档：`data-backup/m12-legacy-20260905T130010249612Z/`，9612 文件；完整清单、SQLite integrity/FK/逻辑摘要、源码/state 原字节、隔离恢复演练通过；正式来源前后指纹一致，Provider/external action 均为 0。只清理成功演练的临时副本，归档及原始数据完整保留。
- 当前设备 Docker/Colima 未运行，未启动或安装；本模块的 Linux 实测待现有 Linux CI 验证，不把 macOS 通过冒称 Linux 通过。旧完整 CI 的平台依赖属于待退役路径，失败记录保留。
- 独立归档 Validator：全新只读 high/high `m12_archive_validator`，VC-003 当前归档范围 `PASS`，无 blocker；独立完整 931 passed / 161.06 秒、专项 22 passed，Ruff/format/mypy/AST/87 Schema/链接/隐私门及真实恢复通过。Linux 动态实测未执行，未将该限制改写为通过。
- 验证绑定：基准 `1d156484ed65bb729a860928029e431e0756ce88`，四项文件清单 SHA `46ffb7e4c9b9eba22df6df264e7a5fbb2cf68173011269d2ff35afc66af9d10b`，VC-003 标题行后至工作分解标题前原文 SHA `9a83e184196ccb1382114dccfaa6c10d6f2ed01c583aee789ce46f54d80b889d`。本次仅真实结果协调回写，合同与受审实现不变；提交/推送将在实际执行后记录。

- 原始现场保护：owner-only `trainlab-m12-checkpoint` 私有备份保存 319 项文件、binary diff、清单和恢复演练；完整原文继续保留，不作为新产品依赖。9356 项正式 state/私人配置指纹在检查期间无变化。
- 原始工作区完整门：909 tests（151.60 秒）；Ruff check、125 文件 format-check、mypy 107 文件、106 AST/compile、96 JSON/87 Schema、6 Skill metadata、11 AI cases、81 Markdown/35 本地链接、ignore/layout/diff 通过。
- 提交隐私收敛：历史 M11 completed 计划五处明确个人指标已在提交副本省略，原文保留在上述私有备份；四份测试中与真实数值重合的样例改为独立合成值，输入/等值断言同步，不删场景或弱化断言。101 项相关测试通过，产品实现与本次原始快照逐字不变；脱敏后完整 909 项再次通过（151.84 秒），Ruff、format、mypy、AST/Schema、metadata、链接、隐私及 diff 门均通过。
- 提交目标：`origin/main`，现有私有 `wyizhou/TrainLab` 仓库；fetch 后 HEAD 与远程均为基准提交，待推旧历史 0；禁止 force。
- 独立 Validator：`m12_checkpoint_validator`，全新只读 high/high；`PASS`，仅限当前检查点提交前准备，不沿用 M11 历史 verdict。
- 受审快照：基准 `db8a3ab7ec31c6bebe32742e785760df4650c97f`，完整 143 项文件；私有 `review-manifest.json` SHA 为 `92ec60bb92e3cf0aeadba89352e5cf07a28f42490a0b5553fd7394ec595f4372`。合同正文 SHA 为 `cede30ef05c985f4ab5dfcfbf78cee9b58ae6437de61ac332af926f0954f6cb2`，仅计算起始标题换行后至下一标题前原文；本段为真实结果协调回写，不改变冻结合同或受审实现。
- 本地提交：`0decf995a8949909f805dcf2d211f7cc9be98d8e`，`chore: checkpoint legacy work for FIT-only weekly direction`；143 文件，34464 行新增/71 行删除；不是发布或 M12 完成声明。
- 远端推送：正常 `git push origin main` 成功；`git ls-remote origin refs/heads/main` 与上述本地提交完全一致，ahead/behind 均为 0，工作树当时干净；未 force 或修改远程历史。
- 暂存核验：143 项 index blob 与受审清单逐项相符；计划仅追加真实结果协调回写，合同摘要不变。私有 `precommit-manifest.json` SHA 为 `06f11f704935a7dec4f9303ef02ab3b7110dbcca54132925350f43a17def737f`；提交前 9356 项私人指纹仍完全一致。
- 新检查点 [GitHub Actions](https://github.com/wyizhou/TrainLab/actions/runs/33966429663) 已触发，回写时 `in_progress`，不预判通过。下列基准 Linux CI 失败记录仍然有效。

### 独立验证固定输出

- `contract_version`：VC-002。
- `overall_verdict`：PASS；只验证检查点提交前准备，不预判提交/推送成功或 M12 功能完成。
- `criterion_results`：AC-GIT-001 当前适用部分、AC-CP-001/002、INV-001/002、GATE-001/002/004 均 PASS；遵守 EX-002。AC-001..018/GATE-003 留待对应 M12 模块实现。
- `blocking_findings`：空。
- `advisories`：首次全量实测为 908 passed / 1 failed，旧 `test_m9_codex_daily_runner.py::test_late_process_group_child_is_stopped_before_final_publish` 抛 `ai_process_stop_unconfirmed`；相同快照单项通过，随后串行全量 909 passed。实现和测试相对基准均未改变，具体原因未定，保留时序稳定性观察。两个已有 raw 目录 `.gitkeep` 为空标记，不含私人数据。
- `scope_change_candidates`：空。
- `unknowns`：提交/推送当时尚未发生；没有运行新 M12 功能或真实 AI/Gmail/Garmin 验收。
- `commands_and_evidence`：Darwin arm64 / Python 3.12.13；离线 `python -m pytest tests/code -q -p no:cacheprovider` 最终退出 0，909 passed / 152.11 秒；专用 Ruff、format 125 文件、mypy 107 文件、只读 AST/compile 106 Python、87 Schema、6 metadata、AI 布局均退出 0；143 项快照/模式与合同摘要独立匹配，30 个受审 Markdown 链接/围栏通过，9 个 ignore 探针通过，9356 项私人指纹最终零差异，`git diff --check` 退出 0，远端仍为受审基准且旧待推历史为 0。

### 提交前已知环境限制

- 主协调另查到远端已有基准提交的 [Linux CI](https://github.com/wyizhou/TrainLab/actions/runs/33964137736) 为失败：旧 Candidate 构建器依赖 Darwin `renamex_np`，Linux 报 `candidate_atomic_swap_unavailable`。该实现、对应测试及 CI 配置均未由本次检查点修改。
- 本次本机质量门及独立验证通过不代表云端 Linux 或新方向部署通过；当前仅保存经隐私审查的工作检查点，不借此修改旧产品、放宽测试或宣称跨平台交付。

## 迭代日志

| 日期/上下文 | 完成与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-09-05 / M12-checkpoint | 恢复最新开发协议，落地原批准 M12 与唯一 Git 补充；319 文件私有备份恢复通过，脱敏后主协调与独立 Validator 全量 909 项通过，检查点 PASS；`0decf99` 已正常推送并核对远端 | 五处历史真实指标与四份疑似派生测试已安全处理；独立测试首次时序失败保留；现有远端 Linux CI 有旧平台依赖问题，不冒称已修复 | 回写真实 Git 结果后，继续 M12-0001 统一归档与新旧规则映射；不宣称新系统已实现 |
| 2026-09-05 / M12-archive | 冻结 VC-003；归档器先测试后实现；22 项新增和完整 931 项通过；9612 文件归档及恢复演练完成，正式数据未变 | 无业务 Provider 调用；Linux 本机容器不可用，未自动启动 | 独立归档验证、提交/推送，然后进入退役映射 |
