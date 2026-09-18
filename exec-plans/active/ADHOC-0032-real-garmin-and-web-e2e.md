# 执行计划：ADHOC-0032 真实 Garmin 与 Playwright Chrome Web 验收

## 对应目标

- 功能编号：ADHOC-0032。
- 功能状态：[exec]。
- 总计划对应条目：[功能总览](../../PLAN.md#功能总览)。
- 目标及范围和验收要求的引用：用户2026-09-18确认：AI模型参数先暂停；可以开始真实Garmin；Web必须使用Playwright操作Chrome测试每一个功能是否正确，不能停留在代码或curl。承接ADHOC-0031 PR #21及[真实检查失败记录](../evidence/ADHOC-0031/real-check-2026-09-18.md)。
- 范围：补受控Playwright Chrome E2E入口与实际浏览器验证；补真实Garmin客户端依赖/适配入口并做有界真实同步/下载/入库检查。AI真实Provider检查暂停，不修改`states/ai.json`，不发起真实AI请求。

## 新增认证维护目标（用户2026-09-18确认，Planner拆解已审核）

- AU32-01：使用pygarminconnect完成账号登录，或明确进入等待2FA状态。
- AU32-02：分离提交验证码的接口，覆盖成功、错误及超时；密码和验证码不落盘、不进入返回或日志。
- AU32-03：认证成功及刷新后的令牌安全持久化、重启复用，不伪造有效期。
- AU32-04：在到期前通过服务支持的机制刷新并保存；需要重新登录时明确提示，不承诺无限延长授权。
- AU32-05：现有同步与Web共用一个认证维护模块。T4～T8已交付基础模块/CLI；用户最新纠正要求现在接入Web GUI，不再仅把Web作为未来事项。不安装系统调度，Web生命周期中的认证维护按新增GUI目标规划，导入/构造仍无外部副作用。
- AU32-06：正常/错误/边界、2FA、刷新、重启、并发/隐私与实际操作入口经独立验证和主验收；基础CLI证据保留，新增GUI必须经过实际Chrome验证，真实登录由用户在完成的本机Web页面协助，开发测试使用合成实例。

## Web GUI认证目标（用户最新纠正，增量规划已审核）

用户原话：『你应该提供国际和中国区，然后你实现完成后，应该提供到web界面，web界面提供GUI的登陆验证。』此次不再向用户询问账号区域作为开发前置条件，也不要求先CLI登录。

- GUI32-01：页面提供国际区(com)/中国区(cn)，用户在页面选择，传入SDK正确。
- GUI32-02：可操作GUI完成账号密码登录及需要时的2FA，含取消/重来、忙碌、错误、过期；无数据库或AI配置也能使用认证入口。
- GUI32-03：显示认证保存/实际期限/维护/需重新登录状态，页面刷新或后端重启复用持久认证；不把仅存文件称为已在线核验。
- GUI32-04：Web运行生命周期复用唯一认证所有者进行提前刷新与持久化，无需另跑CLI维护；导入/构造不启动外部行为，不安装系统守护或顺带启用AI/同步调度。
- GUI32-05：敏感提交不进入URL、日志、浏览器持久存储或服务器密码文件；OAuth留后端；MFA会话绑定、跨站/同源/本机Host及安全错误边界随HTTP接入落实。
- GUI32-06：前端→真实产品HTTP→认证服务→锁定SDK离线传输链，用Playwright/系统Chrome验证两区与正常/错误/边界，并经全新独立验证和主验收；真实账户后续由用户在GUI输入，不进聊天。

本轮见[GUI规划](../evidence/ADHOC-0032/auth-web-plan.md)和[主Agent审核](../evidence/ADHOC-0032/auth-web-plan-review.md)。原CLI及旧浏览器验收只代表各自既有范围，不等于新GUI完成。

## 阶段与任务

| 阶段编号 | 状态 | 预期成果 | 依赖 |
| --- | --- | --- | --- |
| G1 | [completed] | 受控Playwright Chrome E2E脚本/夹具及全功能浏览器验收 | 默认入口及全功能合成场景经独立复验、主Agent实际Chrome验收通过；整体PR交付留G3 |
| G2 | [completed] | 真实Garmin接线及认证维护模块：登录/2FA、令牌持久化和主动刷新；有界真实同步/下载/入库 | T4～T8认证本地验收完成；用户GUI登录后真实有界同步成功 |
| G3 | [exec] | 独立验证、主验收、记录与PR更新；AI暂停状态记录 | 认证基础模块和新增GUI本地验收/页面交付完成；真实Garmin及整体交付未完成，不合并 |
| G4 | [completed] | 两区可选的Garmin登录/2FA GUI、认证HTTP接线与Web生命周期维护、实际Chrome验收 | GUI32-01～06独立及主验收通过；T10～T15完成，正式本机页面已启动，真实账户操作留T9/T2 |

| 任务编号 | 所属阶段 | 状态 | 输入输出及错误边界 | 依赖 | 检查方法 | 结果与证据（检查命令或人工方式、退出结果及关键证据） |
| --- | --- | --- | --- | --- | --- | --- |
| 0032-T1 | G1 | [completed] | 输入合成SQLite/状态夹具；输出Playwright用Chrome操作8080的E2E测试。必须覆盖状态卡、服务卡、活动搜索、列表选择、详情、活动报告文本安全显示、周总结、空态、错误态、API envelope与SPA fallback分离。不读取真实`states/`或secret。 | 当前前端/后端静态服务 | `npm run e2e`或等价命令实际启动本地Web并用Playwright channel=chrome；断言所有场景通过 | RV-002修复后，独立及主Agent均实际执行默认Chrome 2项＋额外10场景通过；搜索/详情/全文安全/周总结/错误/空态/竞态/API-SPA全部有断言。见[独立报告](../evidence/ADHOC-0032/rv-fix-validator-report.md)、[主验收](../evidence/ADHOC-0032/parent-acceptance/report.md)。 |
| 0032-T2 | G2 | [completed] | 输入真实Garmin认证文件；输出产品级真实client适配和一次有界真实检查。不得打印token/secret，不绕过MFA，不猜私有HTTP；若库不能使用现有配置，应明确`AUTH_REFRESH_REQUIRED`或配置错误。 | Python依赖与Garmin库API核对 | 单元/合成回归＋真实最小list/download/import；失败有错误码和脱敏证据 | RV-001已修复，实际锁定SDK的21项独立离线场景和主复跑通过。2026-09-18用户GUI登录后，`maintain --once`退出0且未到刷新期保持unchanged；`sync-once`退出0，最近7天真实下载5个FIT并入库，`states/data.db`核得activities=5、records=22995。证据：[脱敏摘要](../evidence/ADHOC-0032/live-garmin-2026-09-18/redacted-summary.json)；原始本地日志含真实活动ID/文件名，不提交。 |
| 0032-T3 | G3 | [exec] | AI暂停只记录；不补模型、不发请求。固定版本做独立验证和主验收；若真实检查未全过，不询问合并。 | G1/G2 | 全新Validator复验；主Agent核对命令、证据、Git状态 | 全新Validator通过本轮本地/离线范围；主Agent新建环境亲自复跑214个Python、21个额外SDK、11个前端单测、默认Chrome2项＋额外10项、全部静态/架构门通过。78个source文件与独立受验快照一致。真实Garmin及整体交付未完成，不宣告整体通过。 |

### 认证维护增量任务

已审核的具体接口、落点、依赖、失败边界及验收映射见[Planner规划](../evidence/ADHOC-0032/auth-maintenance-plan.md)和[主Agent审核](../evidence/ADHOC-0032/auth-maintenance-plan-review.md)。原T1/T2/T3及失败编号不改。

| 任务编号 | 阶段 | 状态 | 对应目标、输入输出及错误边界 | 依赖 | 检查方法与预期 | 实际证据 |
| --- | --- | --- | --- | --- | --- | --- |
| 0032-T4 | G2 | [completed] | AU32-03/05/06；锁定SDK/路径合同→唯一认证所有者、SDK边界、私有代次仓储；原子提交、互斥、权限、旧配置保全，无导入联网/环境隐式认证 | 当前78文件受验快照 | 实际SDK离线序列化/刷新、存储故障注入/重启/并发/隐私；无令牌外泄或部分提交 | 唯一所有者/仓储经纯客观副本独立检查与主复跑通过；[主验收](../evidence/ADHOC-0032/auth-maintenance-parent/report.md) |
| 0032-T5 | G2 | [completed] | AU32-01/02/03；所有者→begin_login/submit_mfa/cancel/status；内存挑战TTL、重复/并发/代次冲突受控，不持久化密码/验证码 | T4 | 实际SDK普通登录/MFA返回、错误/超时/取消、成功提交与失败不改旧认证 | 普通/分步MFA离线SDK与实际CLI/PTY经独立及主验收；真实认证留T9 |
| 0032-T6 | G2 | [completed] | AU32-01～04/06；通用接口→显式CLI登录/状态/维护单次及循环，按真实有效期刷新保存；不接Web生命周期/系统任务 | T4/T5 | 假时钟边界/退避、真实CLI子进程与PTY、无TTY/EOF/SIGINT、重启复用，主动维护入口实际执行 | 显式循环/单次、刷新落盘/重启与退出离线验收通过；正式维护未启动，真实期限刷新留T9 |
| 0032-T7 | G2 | [completed] | AU32-03/04/05；新所有者→同步唯一认证接线、旧DI迁移提示、CLI sync-once；due/busy先行、隐式刷新保存、原FIT/事务/错误合同不变 | T4～T6 | 实际SDK离线认证→列表/ZIP/FIT/SQLite及并发；迁移原隐私覆盖，不把DI伪装OAuth1 | 统一认证接线、隐式刷新和FIT/SQLite合成闭环经独立及主验收；真实成功留T2/T9 |
| 0032-T8 | G3 | [completed] | AU32-01～06；冻结T4～T7当前source→全新只读Validator独立正常/错误/边界/集成结论，不接收开发裁决 | T4～T7自查结束 | 全部本地门、独立CLI/SDK/存储/并发/隐私，受审版本前后核对，真实服务未执行单列 | 材料隔离/完备性已闭合；认证独立与完整正常回归通过。新增两个既有Web问题经主复现、未修改且不属于认证退化，单列AU32-V1-002/003；[裁决](../evidence/ADHOC-0032/auth-maintenance-parent/report.md) |
| 0032-T9 | G3 | [completed] | AU32-01～06及原T2/T3；独立通过→主Agent亲自离线验收、用户本人真实认证、真实维护/重启/有界同步收据；不造到期时间、不公开秘密 | T8 | 主复跑适用门与默认Chrome；本人Web GUI登录/必要MFA、按真实期限刷新及重启/同步，实服务缺证据不标通过 | 主Agent新环境复跑282项、11前端、Chrome2项及全部门；40项额外检查37通过/3个已确认既有Web断言失败。基础模块离线验收完成。2026-09-18正式GUI状态显示已保存cn认证、真实期限至2026-09-19；CLI状态可重载持久认证；维护单次退出0且未到期不刷新；有界真实同步退出0，最近7天下载5个FIT并入库，未输出密码/验证码/token。证据见T2真实同步目录。 |

### Web GUI增量任务

具体路由/DTO/会话/维护生命周期及Chrome C01～C12验收矩阵以[已审核规划](../evidence/ADHOC-0032/auth-web-plan.md)和[审核边界](../evidence/ADHOC-0032/auth-web-plan-review.md)为准；原T1～T9及问题编号不改。

| 任务编号 | 阶段 | 状态 | 对应目标、输入输出、错误边界 | 依赖 | 检查方法与预期 | 实际证据 |
| --- | --- | --- | --- | --- | --- | --- |
| 0032-T10 | G4 | [completed] | GUI32-03/04/05；认证服务→安全区域/内部代次观察、Web运行态/可停止维护与真实产品启动命令；无构造副作用，关服不遗留在途写者 | 原T4～T8 | 生命周期/线程/取消/重启/代次/限流及CLI启动；逐请求超时不冒充总时限 | 所有者观察/运行态/产品CLI经独立及主验收；[主报告](../evidence/ADHOC-0032/auth-web-parent/report.md) |
| 0032-T11 | G4 | [completed] | GUI32-01～05；T10→6条安全HTTP路由、严格DTO/会话绑定/Origin-CSRF-Host门；OAuth不出后端，外会话不能使用他人MFA | T10 | API正常/错误/请求上限/双提交/并发/隐私，SDK前拒绝；不借共享handler修改暂停业务 | 6条认证HTTP/安全门、16条精确路由、会话/跨站/并发经独立及主验收 |
| 0032-T12 | G4 | [completed] | GUI32-01/02/03/05；HTTP合同→独立React两区登录/2FA/认证维护面板；仪表盘失败仍可用，不缓存敏感输入/重放提交 | T11接口 | 两区普通/MFA、取消/过期/忙/网络错误/恢复，标签与安全状态正确 | 两区普通/MFA独立面板经独立及主Chrome真实操作/可视复核；正式页面交付 |
| 0032-T13 | G4 | [completed] | GUI32-06；完整GUI→真实HTTP＋实际SDK离线传输Chrome宿主/测试；生产无测试控制路由，认证trace/HAR/video关闭 | T10～T12 | C01～C12系统Chrome＋Python边界，所有子进程阻断外连；旧仪表盘/CLI/同步回归 | 开发、独立和主Agent均实际运行；主验收318＋独立13 Python、14前端、原2＋认证24＋独立6 Chrome通过，原失败保留 |
| 0032-T14 | G4 | [completed] | GUI32-01～06；冻结完整source＋references＋客观材料→全新只读Validator独立验收，不接收开发裁决 | T10～T13自查结束 | 源/安装文件匹配、先build再完整门、独立实际Chrome、安全/生命周期/版本冻结 | 全新Validator离线GUI范围通过，主核133冻结文件未变、JUnit318＋独立13通过、Chrome2＋24＋独立产品CLI6通过；[独立报告](../evidence/ADHOC-0032/auth-web-validator-report.md)，测试脚本两轮原失败与脱敏记录保留 |
| 0032-T15 | G4 | [completed] | GUI32-01～06；独立通过→主Agent亲自Chrome验收及可启动本机GUI交付；真实本人操作转原T9/T2，不在本轮开发读取凭据 | T14 | 主复跑C01～C12关键完整流程/错误/安全/重启、产品启动说明/清理，实际证据后才交付 | 主Agent新环境完成318＋独立13 Python、14前端、32 Chrome及全部门，另亲自GUI可视操作通过；[主验收](../evidence/ADHOC-0032/auth-web-parent/report.md)。源/安装/构建一致，正式本机GUI已启动，页面/session/status均200；[交付收据](../evidence/ADHOC-0032/auth-web-parent/delivery.json) |

## 当前检查点

- 工作目录与分支：项目根`.`；分支`work/adhoc-0031-local-web-system`，PR #21。
- 验收要求与受验版本及未提交改动：当前HEAD `a5893ac6eb8295cd8a60d8f2537bc213d1412885`；有前端E2E、Garmin接线和依赖等未提交改动，保留不回退。恢复前公开文件清单见[快照](../evidence/ADHOC-0032/restart-review-snapshot.json)，私人states不包含在内。
- 最近完成：认证模块T4～T8已完成本地交付和独立验证，T9离线主验收完成。主Agent亲自新建非editable环境、重装核对42个产品/Schema文件，复跑282个Python、11前端、默认Chrome2项、全部静态门和40个额外检查（37通过/3个既有Web边界失败），96个source＋4个references未变，无8080残留。见[主验收及问题范围裁决](../evidence/ADHOC-0032/auth-maintenance-parent/report.md)。历史RV、基础设施、材料失败及所有原始报告保留。
- 本轮新增结果：Developer `31cfbba7-2d9d-46dd-86d7-317d7514c958`完成T10～T13实现/自查，主Agent核116个source/4资料及结果原件、原未提交内容保全，完整中性副本重新安装/先build再pytest318项退出0，原数据不复制。该次开发自查不代替验收；后续T14/T15已实际完成，见任务表。[材料核对](../evidence/ADHOC-0032/auth-web-review-packet/report.md)。
- 下一动作：T14 workflow `eee22d31-30c6-4cfc-874b-76483f6f842d`、全新Validator `bd3aac01-1cea-4f12-997c-49e3e9a9fc26`已结束，GUI32-01～06离线范围通过；主Agent核真实证据/冻结后采纳。T15新环境全部门、32 Chrome及额外可视操作已通过，116源码/4资料/46安装文件及原构建核对相符。一次工具中断和安装元数据检查脚本失败已保留且恢复，无产品修改。正式GUI曾启动于http://127.0.0.1:8080且认证维护启用；为跑E2E已停止该本地服务。2026-09-18恢复后核状态为已保存cn认证，CLI可重载持久认证；`maintain --once`退出0且未到刷新期；`sync-once`退出0，最近7天真实下载5个FIT并入库，activities=5、records=22995。AU32-V1-002/003已按用户授权修复并主验收通过。PR #21已推送更新且可干净合并；下一步等待用户确认无问题后开始AI相关。
- 暂停原因：AI仍单独暂停；GUI已独立及主验收、真实本人认证与有界同步已成功；AU32-V1-002/003已修复；PR已更新且可干净合并。正式Web运行维护已验证到未到期unchanged，尚未等到真实到期前刷新时刻。当前等待用户确认无问题后开始AI相关。
- 恢复条件：已满足本次全新派发条件；模型与推理按当前会话设置。AI恢复需另行讨论；合并仍待用户确认。
- 新增修复授权（2026-09-18）：用户要求开始修复AU32-V1-002/003，修复后提交并更新PR；提交后达到可合并状态，用户确认无问题后再开始AI相关工作。验收边界：不暴露绝对路径，资料缺失/逃逸等Context错误通过公共JSON错误壳返回；补正常/错误/边界测试并复跑适用门；AI真实调用仍暂停；不合并main。
- AU32-V1-002/003修复验收：Developer `5dd4ce01-14e4-472f-b90a-9caad251d6f7`完成修复，Validator `3b753846-c97e-490c-8798-50e6960bb1a1`静态审阅无问题但因工具只读不能运行命令，结论BLOCK仅因无实际命令证据。主Agent补跑并采纳：目标10项pytest通过、web+ai 62项通过、全量pytest 326项通过、ruff通过、非editable mypy 42文件通过、前端14项/typecheck/build通过、默认Chrome E2E 2项通过、认证Chrome E2E 24项通过。两次E2E环境失败已记录：一次8080已有正式服务占用，停止PID后重跑；一次/一次相对`UV_PROJECT_ENVIRONMENT`错误，改绝对路径后通过。证据在[修复主验收目录](../evidence/ADHOC-0032/au32-v1-fix-parent/)。
- PR 与交付情况：PR #21已打开并已更新到提交`4126ead`，PR评论[记录](https://github.com/wyizhou/TrainLab/pull/21#issuecomment-5730764617)，GitHub显示`mergeStateStatus=CLEAN`。前轮RV、认证模块及两区GUI均完成适用本地验收，正式GUI已运行；真实Garmin成功链已验并留下脱敏收据；AU32-V1-002/003已修复并主验收通过。AI暂停，等待用户确认无问题后再开始AI相关；不合并main。

## 问题记录

| 稳定问题编号 | 对应要求与实际问题 | 已尝试修法 | 累计失败次数 | 证据及处理结果 |
| --- | --- | --- | --- | --- |
| GUI32-PARENT-001 | 主安装核对受测试PYTHONPATH中source生成egg-info遮蔽，读取direct_url得到None | 证明两个metadata来源；仅核对命令去掉source路径后重跑，46安装文件与原工作区一致 | 检查脚本失败1、修正1；产品修复失败0 | [原错/探针/修正](../evidence/ADHOC-0032/auth-web-parent/report.md) |
| GUI32-VAL-001 | 独立脚本未等待允许的后台观察完成/把stale缓存当立即结果 | 仅补明确等待，不修改产品或验收断言 | 脚本首轮13失败；同步原因修正1，最终13通过；产品修复失败0 | [独立原记录](../evidence/ADHOC-0032/auth-web-validator/execution-notes.md)，两轮失败日志/XML保留 |
| GUI32-VAL-002 | 独立时钟推进3300秒跨越1800秒会话TTL，误把会话失效当维护失败 | 离线SDK给1000秒真实期限、在900秒维护点测；原1800秒过期边界仍保留 | 脚本第二轮2通过/11失败；时钟设计修正1，最终13通过；产品修复失败0 | 同上；不同根因，不重算产品修复轮次 |
| GUI32-VAL-003 | 独立pytest失败诊断包含固定合成输入/随机attempt，非产品日志泄漏 | 明示仅诊断脱敏并保留统计；之后short traceback；扫描阳性对照与0命中 | 2份失败轮次产物受影响；真实秘密0；产品修法0 | [扫描/脱敏计数](../evidence/ADHOC-0032/auth-web-validator/safety-freeze-summary.json) |
| GUI32-V1-001 | 成功DTO操作门未释放而错误带busy | 门释放后取视图，开发已补检查 | 首次2个断言失败；修法1；后续自查失败0；独立及主验收通过 | [原事实与日志](../evidence/ADHOC-0032/auth-web-developer/results.md) |
| GUI32-V1-002 | 4个settings故障测试注入错SDK分支；1个测试撞启动观察门 | settings改真实MFA后注入；单一重启场景显式隔离调度，维护专门覆盖保留 | 测试材料修正，各原因1次；不是降低行为要求；独立及主验收通过 | 同上，pytest-target首轮失败保留 |
| GUI32-V1-003 | Chrome首轮12失败/10通过：11处定位器错误、1处锁忙文案不足 | 修正定位器与固定锁忙文案，原强断言保留 | 首轮失败1轮；各原因修正1；最终24项自查、独立及主验收通过 | 同上及chrome-auth-1原日志/产物 |
| GUI32-V1-004 | MFA尚未执行SDK而遇磁盘锁忙，不应丢Web映射 | 保留待MFA并补真实进程锁Chrome场景 | 人工发现1；修法1；自查失败0，独立及主验收通过 | 同上，C10 |
| GUI32-V1-005 | 隐私测试未接离线传输；首轮全量316通过＋1 teardown error，socket门拦到1次外连尝试 | fixture先统一装离线传输再SDK | 测试安全接线失败1；实际外部请求0；修正1，主预检318通过 | 同上及pytest-full-1日志；不隐藏被阻断的尝试 |
| GUI32-V1-006 | 原Chrome仍断言10条，与新增16条合同不符 | 按批准精确路由集合改16，其他断言保留 | 测试失败1轮；修正1；最终原Chrome2项自查通过 | 同上，chrome-default两轮日志 |
| GUI32-V1-007 | 全空格密码应原样交SDK，不应误判空输入 | 不trim，补首尾/全空格两种真实SDK回归 | 人工发现1；修法1；自查失败0，独立及主验收通过 | 同上；主验收含回归318项通过 |
| AU32-V1-001 | AU32-06/T8输入独立且材料完备；先接触业务PLAN历史汇总，首个纯客观副本又漏references | 方式1隔离但材料不全；方式2完整副本/4个资料/客观协调视图/预构建，已由全新Validator及主Agent核对通过 | 材料失败累计2；处理方式2通过；产品修复失败新增0，历史不清零 | [材料恢复](../evidence/ADHOC-0032/auth-maintenance-isolation/incident.md)；材料问题关闭 |
| AU32-V1-002 | 既有受限资料链接逃逸被拒绝，但ValueError经Web响应暴露绝对路径；未发现读取外部内容 | 首次修法：reference路径逃逸/绝对路径/符号链接逃逸统一转公共不可用错误，工具/Web响应不带路径；补AI工具与Web生成测试 | 首次发现1；主复现1；修法1；完成修复复验失败0 | [主裁决](../evidence/ADHOC-0032/auth-maintenance-parent/report.md)；[修复主验收](../evidence/ADHOC-0032/au32-v1-fix-parent/)通过，问题关闭 |
| AU32-V1-003 | 既有Context资料缺失时Web生成返回纯文本500，不满足公共JSON错误壳 | 首次修法：Context资料读取OSError转ContextError(CONFIG_UNAVAILABLE, `context material is unavailable`)，Web入口经公共JSON错误壳返回；补Context/Web测试 | 首次发现1；主复现1；修法1；完成修复复验失败0；不改材料问题累计2 | [来源映射/主裁决](../evidence/ADHOC-0032/auth-maintenance-parent/report.md)；[修复主验收](../evidence/ADHOC-0032/au32-v1-fix-parent/)通过，问题关闭 |
| D31-LIVE-001 | 真实AI检查缺`model`配置 | 用户决定AI模型参数先暂停 | 真实检查失败1；当前暂停不修 | [真实检查](../evidence/ADHOC-0031/real-check-2026-09-18.md)；本计划不处理 |
| D31-LIVE-002 | 真实Garmin成功同步原未验收；已有401且当前访问令牌exp声明曾过期；产品默认有效期及DI/OAuth1刷新映射不匹配 | 原客户端接线后完成只读诊断；用户新增认证维护要求后，T4～T7标准登录/2FA/主动刷新和唯一所有者接线已完成独立及主验收，退出DI拼装。2026-09-18用户GUI登录后重试真实维护/同步 | 原真实检查失败1、接线尝试1保留；新增认证实现1、本地验收通过；真实成功链路重试1次通过，问题关闭 | [只读诊断](../evidence/ADHOC-0032/garmin-401-diagnosis.md)；[真实同步脱敏摘要](../evidence/ADHOC-0032/live-garmin-2026-09-18/redacted-summary.json) |
| D31-LIVE-003 | Web必须用Playwright操作Chrome，不能以HTTP代替 | 默认入口及额外完整场景已独立和主验收通过 | 原无法判断1；新增E2E实现1；历史保留，本轮默认2＋额外10场景通过 | [主验收](../evidence/ADHOC-0032/parent-acceptance/report.md)；G1/0032-T1完成 |
| ADHOC-0032-V1-001 | mypy在editable安装后找不到trainlab；需按已确认的非editable包检查核实是否存在实现缺陷 | 新Developer按原合同通过检查，并用独立editable环境复现旧错误；无产品修法，无需扩大安装要求，独立非editable门也已通过；不宣称editable路径修复 | 检查失败记录1；修复派发被中止1；完成修复及修复复验失败0；另记本次诊断复现1，不计修复失败 | [核实报告](../evidence/ADHOC-0032/restart-developer-report.md)、[mypy日志](../evidence/ADHOC-0032/restart-developer/mypy.log)；主Agent核对公开文件未变 |
| ADHOC-0032-INFRA-001 | 工作流emit可选字段undefined导致结果传递失败，未启动Validator | 移除不必要emit，仅同协议重派尚未执行的全新Validator；不更换执行模式 | 基础设施失败1；产品修复失败不变 | [精确错误与现场保全](../evidence/ADHOC-0032/workflow-recovery/incident.md)；修正脚本静态校验通过且成功启动Validator，后继网络故障另记INFRA-002 |
| ADHOC-0032-INFRA-003 | T14从中性副本根绑定原项目mission失败；子Agent尚未启动、无run ID | 冻结与原diff已保全；按工具文档显式mission:false，仅隔离验证不绑定跨项目mission，原mission不改；同协议脚本静态校验通过 | 基础设施启动失败1；产品修法/验证失败新增0 | [精确错误、现场与恢复依据](../evidence/ADHOC-0032/auth-web-mission-recovery/incident.md)；同协议workflow `eee22d31-30c6-4cfc-874b-76483f6f842d`已结束、独立验证通过，启动绑定故障闭合 |
| ADHOC-0032-INFRA-002 | Validator报告落盘后网络fetch failed，未获得成功终态 | 用户明确继续；已保全现场并恢复报告/原始证据，不续聊 | 网络失败1；不计产品修复失败 | [恢复记录](../evidence/ADHOC-0032/network-recovery/incident.md) |
| ADHOC-0032-RV-001 | T2要求失败不泄密；畸形tokenstore经真实SDK的ERROR traceback泄露合成认证值 | 首次修法：上下文限定的依赖安全日志＋隐藏上游异常链；补实际SDK离线回归；全新独立复验与主验收通过（锁定SDK受测边界） | 首次发现1；已实施修法1；完成修复复验失败0；开发自查失败/夹具修正保留报告 | [失败证据](../evidence/ADHOC-0032/network-recovery/parent-rv001-reproduction.log)、[修复报告](../evidence/ADHOC-0032/rv-fix-developer-report.md) |
| ADHOC-0032-RV-002 | T3要求独立非editable安装；默认E2E命令硬编码环境覆盖调用者变量 | 首次修法：直接调用指定环境Python，不隐式安装；补缺失/无效/含空格和引号环境回归，默认Chrome入口经全新独立复验与主验收通过 | 首次发现1；已实施修法1；完成修复复验失败0；开发自查失败/修正保留报告 | [环境探针](../evidence/ADHOC-0032/restart-validator/e2e-environment-probe.log)、[修复报告](../evidence/ADHOC-0032/rv-fix-developer-report.md) |
