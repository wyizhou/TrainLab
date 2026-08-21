# 执行计划：M10 滚动七日真实端到端验收

- 状态：`completed`
- 负责人：主协调 Agent
- Roadmap ID：`M10-0001..M10-0005`
- 阶段/子项目：`M10/live-e2e`
- Batch ID：`serial-m10`
- 返工来源：`无`
- 开始日期：2026-08-18
- 最后更新：2026-08-20

## 目标与验收标准

在仓库外全新 Candidate 中，用 2026-08-11～17 的健康/活动和醒来日为 2026-08-12～18 的
主睡眠生成 7 份日报、1 份周报和 2026-08-19～25 周计划。全部离线输出通过后，自投递并验证
8 封 Gmail；最多创建、验证和排期 4 个本次测试独占的跑步 Workout，再解除本次排期并删除
本次 Workout。Code、AI、Data/Privacy 独立 Validator 全部 PASS 才完成。

## 范围与非目标

- 日报日期：2026-08-12～18；周报严格引用这 7 份日报；计划日期：2026-08-19～25。
- 正式库已有 2026-08-11～13 证据优先复用；`data-backup/` 下 M9 归档不作为当前数据源。
- 补齐 2026-08-14～17 的 RHR/HRV/全天心率/VO2 Max/称重、醒来日 2026-08-14～18 的
  主睡眠、2026-08-11～17 每日活动 inventory，最多 7 个新/不完整活动 FIT 与 7 个 weather。
- 禁止 activity summary、GPX、TCX、CSV、历史回退、自动 Provider 重试、Sites 和 cron。
- Gmail 仅发送给 `source/email.json` 中由用户填写的当前认证邮箱自己并保留；可提交的
  `source/email.module.json` 只保存相同结构的空模板，私有文件必须为 `0600` 且被 Git 忽略。
  邮箱地址只允许进入私有配置和仓库外 Candidate 的精确动作请求，
  不得进入 Git、报告正文或公开日志。邮件发出后不可撤回。
- Garmin 仅处理本次创建且 SQLite 证明归属的精确 `-GTS` Workout；既有课程允许同日并存，
  不采用、不复用、不替换、不解除、不删除任何既有 Workout 或日历条目。
- 不修改正式 `source/state/**`、`goal.md`、Garmin Token、旧 Gmail MCP 凭据，不提交、不推送。
  r06 只允许创建或正常刷新专用且被 Git 忽略的 `source/gmail-api-token.json`。

## 冻结预算

| 边界 | 上限 |
| --- | --- |
| Garmin 数据 Provider entry | 47 |
| 新 Garmin Capture/FIT 文件 | 46 |
| inventory 单日返回 ID | 10 |
| 新/不完整活动、FIT、weather | 各 7 |
| Garmin 数据采集墙钟 | 10 分钟 |
| 私人 AI 调用 | 8，自动重试 0 |
| Gmail 发送 | 8 |
| Gmail REST API 调用 | 总计129（认证profile固定1次、投递最多128次）；每封查询/恢复、RAW读取、最终确认各最多5次，`messages.send`最多1次，共最多16次 |
| Garmin Workout | 4 |
| Garmin Workout MCP 工具调用 | 20 |
| Gmail/Garmin 外部动作自动重试 | 0；unknown 只对账 |

任一日期缺失、分页、`has_more=true`、预算超限、Token 漂移、证据不完整或结果不确定都必须
fail closed。外部写入前全部 8 份报告和精确周计划必须已经生成并验证。

## 适用规则与参考资料

- 已批准规则：A-001、A-004、A-008、A-009；根/运行 AGENTS 的隐私、测试先行和 Validator 规则。
- Skills：`garmin-sync`、`training-coach`、`weekly-fitness-summary`、
  `training-report-publisher`、`gmail-sender`、`garmin-training-sender`。
- Garmin 参考：全局 `garmin-training-sender` 的 schedule contract 与 workout mapping。
- Gmail 按 A-010 使用官方 REST API；A-011 允许以 Gmail ID + RAW 实际
  Message-ID 闭合 Provider 改写的邮件身份。不得回退 Gmail MCP、SMTP 或 Connector。

## 依赖与隔离

- 显式依赖：M9 completed，本机 Garmin MCP 已配置；Gmail 使用现有 Desktop OAuth client 完成
  一次人工浏览器授权；正式 state 可只读建立 Candidate。
- 任务分支/Worktree/集成分支：不适用——严格串行，用户未授权 Git 提交或分支。
- 允许写入：本计划、`PLANS.md`、`memory.md`、`CHANGELOG.md`、`.gitignore`、`rules.md`、
  根/运行`AGENTS.md`、`source/requirements.txt`、
  `source/email.json`、`source/email.module.json`、`source/skills/**`、`source/tests/code/**`、必要的 `source/tests/ai/**`、
  私有且被 Git 忽略的 `source/gmail-api-token.json`、仓库外 owner-only Candidate/run root。
- 禁止写入：正式 state、goal、OAuth client、旧 Gmail MCP 凭据、Garmin Token、`data-backup/**`、
  既有 Garmin Workout/日历、远端 Git。
- 写入前确认门：用户已经批准原定 8 封；Code Validator PASS 后先完成人工 OAuth，再发送第一封
  canary。只有 Gmail API 内容核验与用户人工收件确认同时通过，才能发送其余 7 封。

## 功能与测试映射

| 功能 | Feature slug | 测试目录 | 必须满足的行为 |
| --- | --- | --- | --- |
| 七日有界补数 | `rolling-week-sync` | `source/tests/code/contract/`、`integration/` | 复用已有数据、固定窗口/资源/预算、分页和超限阻断 |
| 7 日报 + 周报 | `rolling-week-coach` | `source/tests/code/integration/`、`source/tests/ai/` | 精确 7 日、8 份 AI 输出、证据/安全/报告闭合 |
| Gmail 自投递 | `gmail-rest-send` | `source/tests/code/contract/`、`integration/` | 人工OAuth、确定性请求Message-ID、Gmail ID+RAW实际Message-ID、单次send；r08保留旧8封并新增8封更正标题邮件，先canary后7封，累计恰16封 |
| GTS 生命周期 | `gts-live-lifecycle` | `source/tests/code/contract/`、`integration/` | 独占命名、最多4项、验证后排期、仅本次对象清理 |
| 端到端收据 | `live-e2e-receipt` | `source/tests/code/integration/` | SQLite批准/动作/血缘、正式边界不变、清理闭合 |

## 工具采用情况

- Python 3.12、SQLite、JSON Schema、Garmin stdio MCP、Gmail REST、Codex CLI。
- `pytest tests/code`；Ruff check/format-check；mypy；只读 compile；Schema、Markdown、metadata、
  privacy/layout、HTML 安全和 `git diff --check`。
- 首次外部调用前由全新高风险 Code Validator PASS；真实动作后由全新 AI 与 Data/Privacy Validator。

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Code Validator / M10-0003 | high | high | high | 真实 Gmail/Garmin 写入前的状态机与边界验证 | supported | 只读 | 完整 code gates、Fake MCP、预算/所有权/清理回归 | FAIL：发现 Candidate、血缘、持久预算、复杂课、邮件哈希和清理状态机 6 项缺口 |
| 2 | Final Code Validator / M10-0003 | high | high | high | 合并修正后复验冻结范围内全部门禁 | supported | 只读 | 复现 attempt 1 全部缺口并运行完整门 | FAIL：滚动收据提交门、SQLite完整顺序/总量清理、预览授权绑定仍不闭合 |
| 3 | Final Code Validator / M10-0003 | high | high | high | 第二批收敛后复验全部冻结合同 | supported | 只读 | 端到端提交门、SQL直接绕过、最多4项、精确预览授权与完整门 | FAIL：省略 `m10_phase` 可绕过顺序/预算/清理；直接终态与 adopt 未被 M10 SQL 门拒绝 |
| 4 | Final Code Validator / M10-0003 | high | high | high | 第三批 SQL fail-closed 收敛后复验冻结合同 | supported | 只读 | 阶段必填、禁止 adopt、直接终态证据、独占名称预算/清理及完整门 | FAIL：具体动作未逐项绑定预览；Gmail终态证据/重试与MCP调用预算未闭合 |
| 5 | Final Code Validator / M10-0003 | high | high | high | 第四批逐项预览与外部预算收敛后复验 | supported | 只读 | 精确请求成员、邮件终态、零重试、独占命名、SQLite MCP预算及完整门 | FAIL：Candidate 边界、规范预览哈希/固定8份来源及MCP写请求到动作绑定未闭合 |
| 6 | Final Code Validator / M10-0003 | high | high | high | 第五批 Candidate、预览来源与MCP动作绑定收敛后复验 | supported | 只读 | Candidate guard、7日报+1周报、预览哈希、精确MCP写请求与完整门 | FAIL：SQLite仍可伪造无真实来源预览或无批准/动作的写调用账本 |
| 7 | Final Code Validator / M10-0003 | high | high | high | 第六批 SQLite 来源与写调用事实源收敛后复验 | supported | 只读 | 真实7日报+1周报/邮件/计划血缘与MCP写调用批准/action绑定；完整门 | FAIL：Schema/run/lineage、计划课表投影及Garmin请求仍可SQL绕过 |
| 8 | Final Code Validator / M10-0003 | high | high | high | 第七批统一课表投影和精确来源/请求绑定后复验 | supported | 只读 | 完整代码门、直写对抗、来源与请求闭包、零外部调用 | FAIL：错误 workflow、带额外字段的 Garmin 请求和无边界读取仍可绕过 MCP SQL 门 |
| 9 | Final Code Validator / M10-0003 | high | high | high | 第八批精确 workflow、完整请求对象和有界读取收敛后复验 | supported | 只读 | 29项 M10 回归、完整代码门、SQL直写与合法精确读取 | FAIL：同时省略角色和M10 workflow时，普通operation无法与真实MCP调用意图区分 |
| 10 | Final Code Validator / M10-0003 | high | high | high | 第九批独立MCP operation与完整信封收敛后复验 | supported | 只读 | 外部调用唯一operation、完整信封、持久预算、全部冻结合同与代码门 | PASS：29/29、236/236及全部静态门通过；合成合法账本成功、四类不完整身份均fail closed |
| 11 | Gmail/Garmin Release Validator / M10-0004 | high | high | high | 首次真实写入前复验 Gmail 唯一结果证据 | supported | 只读 | 结果总行数、终态追加、0/2命中和完整代码门 | FAIL：有效结果外仍可追加无效结果而成功终结 |
| 12 | Gmail/Garmin Release Validator / M10-0004 | high | high | high | 合并结果基数修正后复验完整 Schema | supported | 只读 | 单条结果完整 Schema、直接SQL和完整代码门 | FAIL：Schema-invalid 单条结果仍可直接SQL终结 |
| 13 | Final Gmail/Garmin Release Validator / M10-0004 | high | high | high | 最终释放前复验冻结写入合同 | supported | 只读 | 38项M10、245项全量测试、结果Schema/基数/ID绑定、预算和零重试 | PASS：全部代码与静态门通过，允许执行用户已确认的8封邮件和4项临时Workout生命周期 |
| 14 | Garmin Resume Code Validator / M10-0004 | high | high | high | r02真实写入前验证按ID读回解析和旧账本隔离 | supported | 只读 | 精确存在/404/身份不匹配/其他错误、CLI、现有冻结安全矩阵、44项M10与251项全量门 | FAIL：混合500/404错误可被误判为不存在；布尔值可冒充Workout ID；其余门禁通过，未创建r02 |
| 15 | Final Garmin Resume Code Validator / M10-0004 | high | high | high | 合并两项按ID读回缺口后最终释放前验收 | supported | 只读 | 混合状态码、畸形ID、精确404/存在、CLI、全部M10与代码门；不引入新威胁假设 | PASS：47项M10、254项全量及全部静态门通过；精确存在/404接受，混合状态与畸形ID均fail closed；未创建r02或调用外部服务 |
| 16 | Gmail Recipient Config Validator / M10-0004 | high | high | high | 私人收件地址配置进入真实发送前的隐私、账本和防篡改验收 | supported | 只读 | `email.json`权限/Git忽略、地址与预览/请求哈希绑定、链接拒绝、255项完整代码门 | FAIL：CLI标准输出泄漏完整收件地址；缺失、错属主、超限、非法格式及stdout脱敏回归未闭合 |
| 17 | Final Gmail Recipient Config Validator / M10-0004 | high | high | high | 合并隐私输出与文件异常矩阵后最终释放前验收 | supported | 只读 | CLI仅输出脱敏收据；全部配置异常、SQLite绑定、256项代码门和静态门 | PASS：M10 49项、全量256项及全部静态/隐私门通过；真实地址仍为空占位，外部调用0 |
| 18 | Email Module Privacy Validator / M10-0004 | high | high | high | 可提交空模板与永不提交私人配置的最终边界验收 | supported | 只读 | 模板结构/空值、private ignore/0600/untracked、257项代码门与静态门 | FAIL：测试仅检查ignore文本，未调用Git真实判定，未来宽泛规则可能漏检 |
| 19 | Final Email Module Privacy Validator / M10-0004 | high | high | high | Git真实ignore边界修正后的最终模板验收 | supported | 只读 | `git check-ignore`正反例、模板/私人边界、257项代码门与静态门 | PASS：M10 50项、全量257项及全部静态/隐私门通过；模板可跟踪、私人文件ignored/untracked |
| 20 | Final r05 Gmail Delivery Code Validator / M10-0004 | high | high | high | r05单进程真实发送前最终复验 | supported | 只读 | 人工对账证据、三步capture/EML/SQLite终态、274项完整门 | FAIL：伪search run仍可生成manual对账并把旧unknown改为failed_safe；伪reconciliation run/capture/result仍可把新动作改为succeeded |
| 21 | r06 Gmail REST Code Validator / M10-0004 | high | high | high | REST认证、单写者、幂等和崩溃恢复在真实发送前的冻结范围验收 | supported | 只读 | OAuth/Fake REST、确定性MIME、API预算、canary门、权限/隐私和完整代码门 | FAIL：Desktop类型、认证profile总账和可重载refresh token三项缺口 |
| 22 | Final r06 Gmail REST Code Validator / M10-0004 | high | high | high | 合并认证修正后的冻结范围最终复验 | supported | 只读 | 298项代码门、认证失败证据、官方端点和查询合同 | FAIL：profile失败无持久回执、OAuth端点未锁定Google；只读查询重试意见与批准计划冲突，不计为缺口 |
| 23 | r06 Gmail REST Authentication Closure Validator / M10-0004 | high | high | high | 用户批准的窄化认证门与5次只读恢复最终验收 | supported | 只读 | 官方端点、profile失败回执、每阶段5次持久查询预算、每封单次发送及完整代码门 | FAIL：失败profile回执路径可由调用方更换，重启后可重新获得profile预算；其余冻结门全部通过 |
| 24 | Final r06 Gmail REST Authentication Closure Validator / M10-0004 | high | high | high | 合并唯一profile账本路径后复验相同冻结范围 | supported | 只读 | 固定client/recipient/token/receipt路径、失败后跨进程Provider 0次、原冻结矩阵与完整代码门 | FAIL：Candidate/REST Client仍接受替代recipient/token；普通非连接异常也会重试；其余静态门通过 |
| 25 | Definitive r06 Gmail REST Authentication Closure Validator / M10-0004 | high | high | high | 合并投递路径和异常分类后最终复验冻结范围 | supported | 只读 | 全入口固定私有路径、仅连接/429/5xx重试、单次send、持久预算与完整代码门 | FAIL：批量入口绑定认证回执，但直接单封发送入口仍可在无成功认证回执时建立Provider会话；其余冻结门通过 |
| 26 | Final r06 Gmail REST Authentication Closure Validator / M10-0004 | high | high | high | 将认证门下沉到所有Provider入口后复验同一冻结范围 | supported | 只读 | 固定成功认证回执必须在任一发送入口、session与Provider调用前成立；315项代码门及原冻结矩阵 | PASS：定向57项、全量315项、Ruff/format/mypy/AST/33 Schema及隐私布局门全部通过；OAuth、浏览器、网络和Provider调用0 |
| 27 | r07 Gmail Subject Continuation Code Validator / M10-0004 | high | high | high | 新标题、canary零调用对账、实际Message-ID与剩余7封发送前验收 | supported | 只读 | 真实r06证据语义、MIME唯一性、marker/action/approval/request精确绑定与完整代码门 | FAIL：Gmail RAW Base64文本SHA被误当解码EML SHA；重复Message-ID/Subject及额外HTML part可通过；交换action ID后仍可进入Fake Provider |
| 28 | Final r07 Gmail Subject Continuation Code Validator / M10-0004 | high | high | high | 合并修正3项冻结缺陷后最终释放前验收 | supported | 只读 | 真实r06 capture、唯一MIME、7项action精确映射、重放/预算及全部代码门 | PASS：M10定向121项、全量328项、Ruff/format/mypy/AST/36 Schema/隐私布局/diff全部通过；真实r06证据闭合，外部调用0 |
| 29 | r08 Corrected Subject Code Validator / M10-0004 | high | high | high | 更正标题8封进入真实canary前验收 | supported | 只读 | A-012、旧8封不可变、v3标题/血缘/预算、canary门、单次send、重放及全部代码门 | PASS：331项全量、13项定向及全部静态门通过；合成build/canary/7封/预算/replay闭合，真实Provider调用0 |
| 30 | r08 AI Validator / M10-0005 | high | high | high | 更正标题8封后的语义、证据与训练安全最终验收 | supported | 只读 | 新旧16封身份、标题、正文、7日报+1周报、canary顺序和零外部调用 | PASS：8个v3结果和8个动作闭合；标题与正文顶部一致，训练内容/证据/安全和周计划未漂移 |
| 31 | r08 Data/Privacy Validator / M10-0005 | high | high | high | 更正批次正式边界、权限、预算与重放最终验收 | supported | 只读 | Candidate全树0700/0600、SQLite、16封身份、正式state/Token/Git隔离 | FAIL：其余全部通过，但`gmail-rest-r08/`与`gmail-rest-r08/actions/`为0755而非0700 |
| 32 | r08 Permission Remediation Code Validator / M10-0005 | high | high | high | 目录创建权限回归修正后的完整代码复验 | supported | 只读 | 新回归、331项全量、静态门、真实Candidate权限与零Provider | PASS：73目录/9634文件权限闭合；331项测试和全部静态门通过，账本与Provider计数无漂移 |
| 33 | r08 Final AI Validator / M10-0005 | high | high | high | 最终快照的日报/周报语义、证据、安全与邮件一致性 | supported | 只读 | 7日报+1周报、标题变更边界、16封身份、canary顺序和TD-0002 | PASS：训练内容/证据/安全与父输出一致，仅标题按批准变化；16封身份和RAW闭合 |
| 34 | r08 Final Delivery/Data-Privacy Validator / M10-0005 | high | high | high | 权限修正后最终数据、隐私、边界、预算与重放验收 | supported | 只读 | 全树权限、SQLite/raw、r07/r08、正式state/Token/Git和零越界 | PASS：73目录0700、9634文件0600；16封、API64/send16、正式state/Token/r07父证据与重放全部闭合 |
| 1 | AI Validator / M10-0005 | high | high | high | 私人日报/周报/课表语义与不编造验证 | supported | 只读 | 8 份报告、证据、安全与一致性 | validating：r07已累计投递8封，正做最终只读语义验收 |
| 1 | Data/Privacy Validator / M10-0005 | high | high | high | 正式边界、Token、邮件和 Workout 生命周期验证 | supported | 只读 | 指纹、闭包、预算、清理和零越界 | INCONCLUSIVE：正式state/权限/账本/预算通过；Gmail失效无法远端复核，Workout阶段后缺独立Token after指纹；Validator自身一次`mode=ro`只改变Candidate SHM元数据 |

## 工作分解

| 步骤 | 状态 | 证据 |
| --- | --- | --- |
| M10-0001 冻结治理、窗口与外部预算 | completed | Roadmap、exec plan、预算、写入边界和精确确认门已冻结 |
| M10-0002 七日 Candidate 补数和完整报告闭环 | validated | r01 Candidate 完成39次MCP只读、40次Provider进入、34个新文件、7日报+1周报及零AI确定性恢复；Final Validator 16 PASS，预览output 77已生成 |
| M10-0003 外部动作执行器与离线验证 | validated | Final Code Validator 10 PASS：M10 29项、全量236项、全部静态门及仓库外精确账本正反例通过；外部调用0 |
| M10-0004 精确确认与真实动作 | completed | r02 Garmin生命周期已完成并清理；r07旧标题8封完整保留；r08更正标题8封已全部投递并确定性重放，累计16封 |
| M10-0005 最终独立验收与归档 | completed | 最终Code、AI、Delivery/Data-Privacy三名全新只读Validator全部PASS；旧权限FAIL保留，最终快照已闭合 |

## 当前检查点

- 当前 Loop：M10-0005，`completed`。
- 最近完成：更正标题canary获用户确认后，其余7封严格串行投递成功；r08累计API64/send16，8个v3结果和动作全部成功，稳定重放Provider调用0。
- 当前焦点：无；目录权限返工后的最终Code、AI、Delivery/Data-Privacy Validator全部PASS。
- 下一动作：归档本计划并回写Roadmap和memory；TD-0002继续deferred，等待用户后续单独讨论样式。
- 阻塞项：无。
- 已变更文件：治理、CHANGELOG、滚动采集/AI/外部动作脚本、Schemas、Skills说明和code tests。
- 待验证项：无。

## 决策与发现

- 正式 state 只到 2026-08-13；归档 M9 Candidate 不可作为当前数据源，所以必须建立全新 Candidate。
- 周计划为滚动周期 2026-08-19～25；日历冲突采用“允许同日并存”，但绝不修改既有条目。
- 邮件发送后保留；Garmin 测试对象在验证后按 unschedule → verify absent → delete → verify absent 清理。

## 任务级独立验证

- 中性交接：M10 冻结合同、当前实现和代码门；不提供实现者推理。
- Validator 身份/上下文：r08最终快照由三名全新只读高风险Validator分别完成Code、AI与Delivery/Data-Privacy验收。
- 模型/推理档位：high/high。
- 命令与观察：331项全量测试、Ruff/format/mypy、62文件AST、39 Schema、metadata/Markdown/隐私/布局/diff全部PASS；最终Candidate 73目录0700、9634文件0600。
- 结果：历史FAIL全部保留；r08权限修正后的Code、AI、Delivery/Data-Privacy最终Validator均`PASS`。
- 未满足项与剩余风险：无当前阻塞；TD-0002为用户接受的deferred展示债，不授权长期自动发送、Sites或cron。

## 集成级独立验证

- 集成范围：单一串行任务，无并行集成。
- 结果：不适用——无并行集成；最终 AI/Data Validator 仍为完成门。

## PLANS 回写清单

- [x] Exec plan 已归档到 `completed/`
- [x] Roadmap 叶子任务已更新为 `[x] completed`
- [x] 子项目和阶段状态已重新计算
- [x] `memory.md` 中的活动计划指针已删除

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-18 / 创建 | 用户批准滚动七日、8封邮件、临时 Workout 生命周期；Git/Skills/规则已恢复 | 正式数据缺 8/14～18，外部执行器尚未接通 | 先测试后实现并交 Code Validator |
| 2026-08-18 / 实现 | 新增3个Schema、固定滚动采集器、七日AI编排、确认清单/动作账本和9项回归；复杂课程不会被压平为连续跑；完整219项pytest、Ruff、format、mypy已PASS | 真实Provider与外部写入仍为0；Code Validator尚未开始 | 跑完只读结构门并交全新Code Validator |
| 2026-08-18 / 验证返工 | 首次 Code Validator 在冻结范围内判 FAIL；合并修复 Candidate-only、精确7日报血缘、SQLite持久AI预算、严格简单课映射、邮件全文哈希与 Garmin 双 absent 验证；M10 定向18项、全量225项测试及静态门 PASS | 首次真实 Provider/Gmail/Garmin 写入仍为0 | 交全新 Final Code Validator，不继承首次结果 |
| 2026-08-18 / 第二次验证返工 | Final Code Validator 2 判 FAIL；提交门已支持滚动收据，预览成为不可变SQLite输出并绑定人工授权，新增完整Garmin SQL顺序、最多4项及全量cleanup约束；M10定向19项、全量226项与静态门PASS | 外部调用仍为0；旧FAIL不转为PASS | 交全新Final Code Validator 3 |
| 2026-08-18 / 第三次验证返工 | Final Code Validator 3 判 FAIL；补齐 M10 阶段必填、禁止 adopt、直接终态证据门，并让预算与 cleanup 只依赖独占名称而不依赖可省略阶段；新增直接 SQL 回归 | 真实 Provider、Gmail、Workout 写入仍为0；旧FAIL不转为PASS | 跑全量门并交全新 Final Code Validator 4 |
| 2026-08-18 / 第四次验证返工 | Final Code Validator 4 判 FAIL；预览逐项绑定每个邮件请求和Garmin阶段请求，独占名称由预览强制，新增Gmail终态证据/零重试与SQLite MCP调用预算；M10定向20项、全量227项和静态门PASS | 真实Provider、Gmail、Workout写入仍为0；旧FAIL不转为PASS | 交全新Final Code Validator 5 |
| 2026-08-18 / 第五次验证返工 | Final Code Validator 5 判 FAIL；外部动作API补齐Candidate guard，预览重算规范哈希并验证固定7日报+1周报唯一来源，SQLite拒绝不完整伪预览，MCP写调用精确绑定prepared动作；M10定向22项、全量229项和静态门PASS | 真实Provider、Gmail、Workout写入仍为0；旧FAIL不转为PASS | 交全新Final Code Validator 6 |
| 2026-08-19 / 第六次验证返工 | Final Code Validator 6 判 FAIL；SQLite approval 新增强制真实7日报、1周报、对应邮件渲染及周计划lineage，MCP写调用run必须引用有效预览、批准和prepared动作；新增直写对抗回归，M10定向23项、全量230项和静态门PASS | 真实Provider、Gmail、Workout写入仍为0；旧FAIL不转为PASS | 交全新Final Code Validator 7 |
| 2026-08-19 / 第七次验证返工 | Final Code Validator 7 判 FAIL；抽取唯一周计划到Garmin投影合同，SQLite approval 增加报告Schema、成功run、周报精确七日报血缘与计划课表一致性，MCP run 增加完整请求JSON和逐动作匹配；新增5项回归，M10定向28项、全量235项及静态门PASS | 外部调用仍为0；旧FAIL不转为PASS | 交全新Final Code Validator 8 |
| 2026-08-19 / 第八次验证返工 | Final Code Validator 8 判 FAIL；MCP 门改为同时捕获角色与 workflow，强制完整请求对象，并将 Gmail marker、Garmin 列表/日历窗口及按 ID 读取限制在预览和动作范围；新增 SQL 直写与合法读取回归；M10 29项、全量236项和全部静态门PASS | 外部调用仍为0；旧FAIL不转为PASS | 交全新Final Code Validator 9 |
| 2026-08-19 / 第九次验证返工 | Final Code Validator 9 判 FAIL；新增唯一 `mcp_tool_call` operation，SQLite 对该operation、M10角色或M10 workflow任一命中均强制完整合同；Provider host 明确拒绝普通离线run；M10 29项、全量236项及静态门PASS | 外部调用仍为0；旧FAIL不转为PASS | 交全新Final Code Validator 10 |
| 2026-08-19 / 真实只读与AI生成 | 建立 `/private/tmp/trainlab-m10-candidate-r01.bdmF6h`；有界Garmin读取成功，新增34个文件；`/private/tmp/m10-r01-real.U7NRI7/run` 完成7日报和1周报共8次AI调用 | 周报已规范化写入SQLite，但报告保存按校验前全文匹配而阻断；无第9次AI、无Gmail/Garmin写入 | 按已知输出ID绑定规范化结果，增加零AI恢复并交全新Validator |
| 2026-08-19 / 确定性恢复与确认门 | 收敛精确来源/title/period/HTML、唯一rolling receipt、全局8次AI身份及7+1基数；242项测试和Final Validator 16 PASS；零AI恢复生成preview output 77 | 8封邮件和4项测试Workout均尚未执行，external_actions=0 | 展示精确主题/课表并等待用户确认 |
| 2026-08-19 / 用户确认 | 用户明确确认执行8封邮件和4项Garmin测试课表 | 邮件保留；Garmin对象必须完整验证后清理，不得触碰既有对象 | 按SQLite批准、动作和MCP调用账本严格串行执行 |
| 2026-08-19 / 写入前核验修正 | Garmin只读预检确认本次4个独占名称均不存在；外部写入仍为0；发现marker未包含于实际邮件，原搜索无法验证投递 | 保持邮件字节不变，改为SQLite绑定的精确主题搜索，并强制搜索message ID等于send返回ID | 新增回归、运行门禁并交全新Code Validator后继续 |
| 2026-08-19 / Gmail核验Validator返工 | 独立Validator判FAIL：旧marker查询仍被接受，send/search ID未持久对账 | marker降为SQLite幂等键；send与精确主题search结果写入不可变output，动作成功必须唯一ID三方一致 | 合并修正后只交一次全新最终Code Validator |
| 2026-08-19 / 外部释放前最终验证 | 两次独立复验先后发现结果总行数和Schema-invalid直写缺口；合并修正后 Final Release Validator 以M10 38项、全量245项和全部静态门给出PASS | 旧FAIL永久保留，不转为PASS；冻结写入合同已闭合 | 按用户确认严格串行执行真实动作 |
| 2026-08-19 / 真实动作阻断与清理 | 首封 Gmail 调用返回 `invalid_grant`，3次精确主题诊断查询同样失败，确认0封投递并将动作记为`failed_safe`；Garmin创建并按ID确认1项4km测试Workout，因本地验证解析误记失败而停止其余3项，随后删除并按ID复核404；未排期日历 | Gmail认证失效，零重试合同要求停止；Garmin账本的首个验证动作已封为失败终态，不能伪造完整生命周期 | 保持M10 blocked，完成Data/Privacy只读核验；重新认证与后续续跑需用户新批准 |
| 2026-08-19 / Data与隐私复核 | Validator确认Candidate integrity/FK/六表/85触发器、正式state 9347项指纹、权限/Git隔离和预算；Gmail成功数0，Garmin账本仅1项且补偿删除 | 结论INCONCLUSIVE：邮箱无法远端复核、外部阶段后无独立Token after指纹；Validator一次`mode=ro`仅改变Candidate SHM元数据 | 不归档M10；保留blocked状态，后续只需认证恢复与新的有界续跑/证据批次，不重做已通过的离线报告 |
| 2026-08-19 / r02续跑授权与预检 | 用户明确要求继续M10外部续跑；精确`gmail`绑定仍返回`invalid_grant`，Garmin harmless read成功；旧r01仅1项且已删除 | 邮件不能重试；r01 append-only账本已含终态失败，不能伪造重跑 | 从无动作的已验证快照建立r02，先修复并验证Garmin读回解析，再独立完成Garmin生命周期 |
| 2026-08-19 / r02冲突预检 | 两项Garmin只读调用已先落账；精确4个测试名称不存在；21日已有`Easy-6KM-GTS`、23日已有`长跑-9KM-GTS`；正式state与Token前后不变 | 同日再排测试主课会产生冲突；原授权不包含改动既存课表 | 在首个Garmin写入前停止；请用户决定是否允许同日并存或另行批准日期调整 |
| 2026-08-19 / r02同日并存授权 | 用户明确批准两项测试课与21/23日既存课表同日并存，并要求完成后只删除本次创建对象 | 既存Workout和日历条目不在写入/删除范围 | 执行4项独占名称的创建、读回、排期、取消、删除和最终双空验证 |
| 2026-08-19 / r02回读证据阻塞 | 4项测试Workout创建成功，3项按ID精确回读成功；尚未排期，既存日历未改动 | 第一项按ID读取已调用但本地编码器在保存响应前失败，账本保持running/in_progress；自动重试0次合同禁止静默再读 | 请求用户单独批准一次额外只读回读；批准后闭合第一项并继续排期、取消、删除，未批准则进入仅清理流程 |
| 2026-08-19 / r02 Garmin完整生命周期 | 用户批准一次额外只读回读；4项测试Workout全部精确验证、同日排期、日历复核、取消、删除并逐项404确认；MCP账本20次、32项动作均终态成功；正式state与Token前后不变 | 21/23日既存课表及20日既存课表均保留；测试对象残留0 | 转入Gmail真实自投递 |
| 2026-08-19 / r02 Gmail自投递阻塞 | 第一封精确邮件已建立批准与调用账本；本地MCP在Provider发送前返回`Recipient email address is invalid: me`，动作记为`failed_safe`，确认0封发送 | Skill的自投递别名合同与当前MCP地址校验不兼容；不能静默保存或替换真实邮箱地址 | 修正并验证自投递收件人解析，使用新的零动作Candidate续跑8封邮件；不得重做Garmin或重复失败动作 |
| 2026-08-19 / 私人邮箱配置修正 | 用户批准新增`source/email.json`并由本人填写；文件已设`0600`且Git忽略，运行器校验普通文件/owner/单链接/地址格式，并把地址、地址SHA和精确邮件请求SHA绑定到私有Candidate预览；新增配置替换、空值、宽权限、symlink、hardlink和SQL预览缺字段回归；255项测试及Ruff/format/mypy/AST/Schema/隐私/布局/diff门通过 | 真实地址尚未填写，邮件仍0/8；地址不得打印或写入Git | 交全新只读Code Validator；PASS后请用户本机填写地址，再建立Gmail-only Candidate续跑 |
| 2026-08-19 / 邮箱配置隐私返工 | Validator 16判FAIL；CLI改为仅输出preview/output ID、SHA和数量的脱敏收据，不再打印完整预览；补齐缺失、错属主、超限、非法地址和CLI泄漏回归，保留原有空值/0644/symlink/hardlink/地址变化测试；256项完整测试和全部静态门通过 | 旧FAIL永久保留；真实地址仍未填写，邮件0/8 | 交全新Final Validator 17，不继承旧结论 |
| 2026-08-19 / 邮箱配置最终验证 | Final Validator 17 PASS：M10 49项、全量256项，Ruff/format/mypy/AST/Schema/metadata/Markdown/隐私/布局/diff全部通过；非测试跟踪文件未发现邮箱地址 | 配置仍为空占位，真实发送必须等待用户本机填写；外部调用仍为0 | 用户填写`source/email.json`后建立Gmail-only Candidate并发送/逐封复核8封邮件 |
| 2026-08-19 / 邮箱空模板 | 用户要求把可提交结构与私人值分离；新增可跟踪的`source/email.module.json`空模板，`source/email.json`继续保持`0600`、Git忽略且不进入后续提交；新增结构/ignore边界回归 | 模板故意保留空地址，不能直接用于发送 | 运行完整门并交全新只读Validator，随后仍等待用户只填写私人文件 |
| 2026-08-19 / 模板ignore回归返工 | Validator 18判FAIL：产品边界实际正确，但测试只读ignore文本；回归改为直接执行`git check-ignore`，强制私人文件返回ignored、模板返回not ignored；257项测试和全部静态门通过 | 旧FAIL保留；未改变模板或私人文件内容 | 交全新Final Validator 19 |
| 2026-08-19 / 模板最终验证 | Final Validator 19 PASS：模板精确为空结构且不被ignore；私人文件普通单链接、`0600`、被Git实际忽略且未跟踪；M10 50项、全量257项及全部静态/隐私门通过 | 邮件仍0/8，真实地址必须由用户只在私人文件中填写 | 用户填写后建立Gmail-only Candidate并真实发送/逐封复核8封邮件 |
| 2026-08-19 / r04首封结果未知 | 用户已填写私人邮箱并建立全新Gmail-only Candidate；首封发送只调用一次，但Provider返回未能确认，动作保持`unknown`，其余7封仍为`prepared` | 写入重试已被状态机禁止；现有只读门也误挡了精确搜索对账 | 仅放开preview绑定的`search_emails`对账，补“可查、不可重发、不可改查询”回归并交全新Validator；不得重做Garmin |
| 2026-08-19 / unknown对账首轮返工 | 独立Validator确认258项代码门通过，但实证`maxResults`可由10改为9 | 精确对账必须绑定完整请求，而不只是查询文字 | 将`maxResults`冻结为10，补Python API与SQLite直写两层反例，再交全新最终Validator；外部调用继续为0 |
| 2026-08-19 / r04精确对账未落账 | Final Validator确认258项及完整请求锁定全部PASS；随后只调用一次精确`search_emails`，但本地结果持久化进程未成功启动，原始结果未形成可审计证据；搜索run记为`failed`，首封动作继续`unknown`，其余7封仍`prepared` | 不能依据未持久化结果判断已发送或未发送，也不能盲目重查/重发 | 保持M10 blocked；若要再查必须由用户另行批准一次精确只读查询，仍不得重发首封或继续后续发送 |
| 2026-08-19 / 用户批准只读恢复 | 用户明确批准一次额外的相同精确搜索；若唯一命中，再读取该邮件核对正文；首封仍禁止重发 | 普通重试必须继续拒绝，额外读取只能绑定上一次`result_unpersisted`失败run和同一完整请求 | 新增显式attempt-2只读恢复合同、API/SQL/attempt-3反例并交全新Validator；PASS后才执行一次搜索 |
| 2026-08-19 / r04只读恢复结果 | Final Validator确认attempt-2只读恢复合同与258项代码门PASS；批准的额外精确搜索已执行并同步落账，返回0个匹配，run终态`blocked` | 0命中不能在现有合同下自动证明首次调用绝对未发送；首封仍`unknown`，其余7封仍`prepared`，不得自动重发或继续发送 | 保持M10 blocked；请求用户核对邮箱并明确批准下一恢复方案，或另建零动作Candidate重新开始Gmail批次 |
| 2026-08-19 / r05单进程投递批准 | 用户确认已在收件箱、已发送、所有邮件中按准确主题搜索且均无结果，并批准保留r04历史、人工对账首封、以单一host执行draft/send/download持久化；canary计入原8封 | 旧直接send与临时finalizer不能再承担M10投递；正常8封预算为24次，最多保留1次unknown查询和1次draft清理 | 先测试后实现；全新Code Validator PASS后建立r05并执行首封canary |
| 2026-08-19 / r05最终代码验证阻塞 | 单一host、owner-only staging、EML精确核验、人工对账输出和SQLite门已实现；274项pytest、Ruff、format、mypy、AST/Schema/隐私/布局/diff均PASS；Final Validator全程零外部调用 | 对抗验证仍可用非`mcp_tool_call`伪search run生成manual证据并转旧action为failed_safe；也可伪造reconciliation run/captures/result把新action改为succeeded | high/high验证失败后停止自动返工；保持M10 blocked，不建立r05、不发送邮件，等待用户批准新的窄化修正批次 |
| 2026-08-19 / r06 REST实现 | 用户批准停止修补Gmail MCP并采用可信owner-only单写者；新增A-010、Desktop OAuth、专用token、确定性MIME/Message-ID、Gmail REST查询/单次发送/RAW核验、持久调用预算、runtime与固定r04身份绑定、canary门和36项Fake REST回归；删除未交付r05投递器及其专用触发器/Schema；全量294项pytest、Ruff/format、mypy、AST/Schema/Markdown/隐私/布局/diff全部通过 | 尚未认证或调用Gmail REST；r04/r05历史原样保留，旧unknown未改写 | 冻结工作区并交全新r06 Code Validator；PASS后硬暂停引导人工OAuth |
| 2026-08-19 / r06首次独立验证返工 | 全新Code Validator只读确认294项测试和全部静态门PASS，但判定FAIL：OAuth工厂会接受`web` client、认证profile调用未纳入持久48次总账、无refresh token凭据会被误报成功 | 未打开浏览器、未认证、未调用Gmail；三个缺口均属冻结认证/预算范围 | 一次性补Desktop JSON门、强制认证回执与总预算绑定、可重载refresh token门及回归，再交唯一一名全新Final Code Validator |
| 2026-08-19 / r06合并修正 | 浏览器启动前仅接受完整Desktop `installed` JSON；认证回执成为必填owner-only证据并把profile 1次调用绑定总账，投递最多47次；无refresh token或不可重载token在profile前阻断；新增4项回归及Block映射 | 298项pytest、Ruff/format/mypy、60文件AST、34 JSON、Desktop实文件结构、隐私/布局/diff全部PASS；真实OAuth/Gmail调用仍为0 | 冻结工作区并交唯一一名全新Final Code Validator，不继承首次FAIL |
| 2026-08-19 / r06最终代码验证阻塞 | Final Validator确认298项与全部静态门PASS，但发现profile已调用后500/传输/坏JSON未形成持久失败回执，以及伪`attacker.invalid` installed端点可过本地门 | “查询最多两次额外只读重试”是最新用户计划明确授权，不属于缺陷；前两项属冻结认证范围且OAuth/Gmail仍0调用 | 按“任一步失败即停止”和不再逐轮验证要求将M10-0004标记blocked；等待用户批准窄化修订 |
| 2026-08-20 / r06窄化修复 | 用户批准并完成Google端点、profile失败回执、每阶段5次持久只读查询与每封单次发送；三名Validator依次发现认证账本可换路径、替代recipient/token与异常误重试、直接单封入口缺少认证门，均属原冻结范围并已合并修复；固定成功认证回执现于任一发送入口、session和Provider调用前验证；总预算129；Final Validator最终PASS：定向57项、全量315项、Ruff/format/mypy、60文件AST、33 Schema、metadata/Markdown/隐私/布局/diff全部通过 | 查询0命中只记录`unknown`并退出，人工重发需要新的明确授权；本批次OAuth/Gmail调用仍为0；旧Validator FAIL永久保留 | 按计划硬停止在人工OAuth前；等待用户另行明确要求开始认证 |
| 2026-08-20 / r06人工OAuth与canary | 用户完成Google Auth品牌发布与授权；账号/Scope/Profile/refresh token、owner-only Token/回执及正式state指纹通过。首个Candidate因日报渲染日期来源错误在Provider 0次安全阻断并永久保留；改用已绑定AI源日期、严格核对父preview/envelope SHA、成功email-render及三种正文后，318项代码门与全新Validator PASS。全新attempt执行canary：初查0、`messages.send`恰好1次并获Gmail ID、RAW两次读取均成功；收件人/主题/text/HTML完全一致，但Google改写预设RFC822 Message-ID，动作按合同保持`unknown`；其余7项仍`prepared/attempt=0` | Gmail API共4次、send 1次；正式state不变，Token文件在合法API使用期间变化且当前仍owner-only有效；不得重发canary或继续其余7封 | 等待用户人工确认是否收到；获批后版本化Message-ID合同，以Google实际ID完成已发送canary对账并再验证，不能发送第9封 |
| 2026-08-20 / r07标题与投递闭环 | 用户确认canary已收到并批准A-011与r07；首轮Code Validator发现3项冻结缺陷，合并修正真实capture SHA语义、唯一MIME与action/approval/request映射；Final Validator以121项M10、328项全量及全部静态门PASS。新r07 Candidate零调用闭合canary、取消旧7动作、建立7个新标题动作并严格串行投递成功 | 累计Gmail API 32次、send恰好8次；8个Gmail ID和8个实际Message-ID唯一；稳定重放Provider调用0、SQLite逻辑行/ID/SHA无增量；正式state 9347项指纹前后一致，Token仅合法刷新且仍0600 | 交全新AI Validator和Delivery/Data-Privacy Validator；两者PASS后归档M10，TD-0002保持deferred |
| 2026-08-20 / r08更正标题授权与实现 | 用户确认旧8封均已发送但标题设计错误，批准A-012：旧证据不动，新增8封更正标题邮件，完成后累计16封；日报固定`TrainLab · 每日训练简报 · 日期`，周报固定完整日期范围 | 不重跑Garmin/AI/报告；TD-0002继续deferred；发送前必须重建标题相关全链并通过全新Code Validator | 参数化r07状态机、增加v3合同和回归；PASS后只发送更正canary并等待用户确认 |
| 2026-08-20 / r08 Code PASS与更正canary | 全新Code Validator以331项全量、13项定向和全部静态门PASS；新Candidate `/private/tmp/trainlab-m10-gmail-r08.V7b9hC/continuation/candidate`绑定r07旧8封并建立8个新动作。更正日报8/12 canary单次send成功，Gmail ID、实际Message-ID、RAW与正文闭合 | r08累计API36/send9；当前动作1 succeeded+7 prepared；canary人工门仍为false。正式state和r07父证据不变，Token仅正常使用且保持0600 | 等待用户明确确认收到更正标题canary；确认后零Provider写人工收据，再严格串行发送余下7封 |
| 2026-08-20 / r08全部投递与权限返工 | 用户确认canary后剩余7封严格串行成功；累计16个不同Gmail ID，r08 API64/send16；重放Provider 0且SQLite行/ID/SHA无增量。AI Validator PASS；Data/Privacy Validator仅因两个中间目录0755判FAIL | `private_directory(..., parents=True)`只收紧最终目录，导致`gmail-rest-r08/`与`actions/`继承0755；邮件、SQLite、正式state、Token及r07证据均未受影响 | 先加全树权限回归，再显式创建/收紧storage与actions父目录；真实Candidate只chmod这两个目录为0700，完整门通过后交全新最终Validator，绝不重发 |
| 2026-08-20 / r08最终交付 | 目录权限回归先失败复现后修复；真实Candidate仅收紧两个目录到0700。全量331项、Ruff/format/mypy/AST/39 Schema与隐私布局门通过；全新Code、AI、Delivery/Data-Privacy Validator均PASS | 最终73目录0700、9634文件0600；16封身份/RAW闭合，API64/send16，总Provider65；正式state、Token、r07父证据和重放无漂移 | 归档M10；保留全部历史FAIL和TD-0002 deferred，不启用长期自动化或cron |
