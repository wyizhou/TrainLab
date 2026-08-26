# 执行计划：人类可读日报/周报与私有 CID 图表闭环

- 状态：`completed/offline-v3`
- 负责人：主协调 Agent
- Roadmap ID：`M11-0001..M11-0014`
- 阶段/子项目：`M11/email-presentation`
- Batch ID：`serial-m11`
- 返工来源：`无；提升 TD-0002`
- 开始日期：2026-08-21
- 最后更新：2026-08-23

## 目标与验收标准

将 M10 已验证的严格 AI 日报、周报、证据和课表转换为可日常阅读的中文邮件，同时保留底层
JSON 作为事实源。日报覆盖 ready/caution/blocked、缺失数据、跑步/攀岩/休息；周报覆盖
advance/hold/deload/blocked。只从明确数组生成真实图表，通过 CID PNG 嵌入 MIME v2；HTML、
纯文本、PNG manifest、SQLite 和 RAW 必须一致且确定性重放无增量。

完成代码、合成测试、owner-only 真实 Candidate 预览及 Code、Visual、Data/Privacy 三类全新
只读 Validator 后，用户于 2026-08-21 进一步批准两封真实 Gmail 样式 canary。当前严格按
`日报 2026-08-12 → 用户网页和手机确认 → 周报 2026-08-12~2026-08-18` 串行执行；两封均闭合并
技术投递与样式已闭合，但用户内容验收未通过。M11 进入 A-015 Coaching Utility v2 返工：日报
必须解释昨日与恢复状态并对照原周计划给出今日调整，周报必须总结健康和训练负荷；正常
`hold/advance` 周含一节条件性 SOS，`deload`/红旗/有证据的明显恢复不足可以为零并说明。
TrainLab 不计算心率区间；完成离线七日报/一周报预览和独立验证后交用户审核。用户于
2026-08-23 进一步批准 M11 v3：冻结既有 v2 AI/课表字节，恢复 OpenDesign 的卡片、KPI、
图表和七日时间轴；历史心率分区只允许使用 Garmin/FIT session 已记录时长，绝不用于课程
处方。部署仍需下一阶段单独批准。

## 范围与非目标

- 范围：版本化 ViewModel/Schema、显式 Python 组件渲染、确定性 PNG、CID manifest、MIME v2、
  RAW 核验、Fake REST 单消息恢复、设计映射审计、合成/私有预览，以及获批的两封 Gmail REST
  样式 canary。
- 非目标：重跑 Garmin、Codex 或读取新的 Provider 数据；修改正式 state；发送任何邮件；Workout、Sites、
  cron、公开托管图片、部署；修改 M10/M11 v1 历史输出与远端证据。
- Git：已获授权建立一个 M10 本地基线提交；M11 代码不提交、不推送。

## 适用规则与参考资料

- 已批准规则：A-004、A-008、A-009、A-010、A-011、A-013、A-014、A-015、A-016。
- M11-0006 的冻结验收章程：
  `source/tests/code/contract/m11-live-canary-validation-boundary.md`；章程只复述既有 A-010 信任边界，
  不新增或弱化规则。
- M11-0007 起的内容验收章程：
  `source/tests/code/contract/m11-coach-utility-v2-boundary.md`。
- 按需读取的 references：用户高保真交接包
  `/Volumes/DiskOther/Design/c8d5a31b-0a34-497d-9ef5-9598724331b5`；筛选后 41 文件 manifest
  SHA-256 为 `150399ae8cd96c6242ba70c3e342a593847c168f2050481e2c9dd725ea9e07d9`。
- 交接包的 `.open-design/**`、`*.artifact.json` 和示例 JSON 不作为运行时输入；外部原件只读。

## 依赖与隔离

- 显式依赖：M10 completed，本地基线 `b172f95`。
- 共享接口和冻结依据：`daily_ai_result_v1`、`weekly_ai_result_v1`、`training_plan_v1`、
  SQLite 六表、A-010/A-011 Gmail REST 状态机、A-013 MIME v2。
- 任务分支：`不适用——用户批准严格串行且不要求 M11 提交`
- Worktree：`不适用`
- 集成分支：`不适用`
- 允许写入范围：根治理/计划/变更日志；`source/skills/training-report-publisher/**`、
  `source/skills/training-coach/**`、`source/skills/weekly-fitness-summary/**`、
  `source/skills/_shared/schemas/**`、`source/templates/**`、`source/tests/code/**`、
  `source/tests/ai/**`、依赖与 CI；仓库外 owner-only 预览。
- 禁止写入范围：`source/state/**`、私人 goal/email/credentials、M10 Candidate、远端 Git、
  Garmin/Workout/Sites/cron。专用 Gmail Token 只允许正常原子刷新；Gmail 只允许本计划两封发送
  与对应只读核验。

## 功能与测试映射

| 功能 | Feature slug | 测试目录 | 必须满足的行为 |
| --- | --- | --- | --- |
| 日报/周报 ViewModel | `email-view-model` | `source/tests/code/{unit,contract}` | 显式字段、状态/缺失语义、单位、证据、课程绑定、无编造 |
| 人类可读 HTML/text | `readable-email-render` | `source/tests/code/{unit,contract}` | 转义、主题等于唯一 title/h1、80KiB、375px、dark/Outlook fallback |
| 确定性 PNG | `email-static-charts` | `source/tests/code/{unit,contract}` | 1248px、真实数组、稳定 SHA、alt/fallback、无敏感字段 |
| CID MIME v2 | `gmail-cid-mime` | `source/tests/code/contract` | alternative/related、manifest、RAW 闭合、无远程或孤立附件 |
| 通用 Fake 投递 | `gmail-generic-delivery` | `source/tests/code/integration` | 单次发送、只读恢复、重放零增量、旧 M10 不漂移 |
| v2 教练证据与 AI | `coach-utility-v2` | `source/tests/code/{unit,contract,integration}`、`source/tests/ai` | 无心率区间、RPE、SOS、安全门、证据引用、日/周因果解释 |
| v2 课程与展示 | `coach-course-view-v2` | `source/tests/code/{unit,contract,integration}` | 原课/调整、详细步骤、周健康/负荷/洞察、HTML/text无工程泄漏 |
| v3 展示证据 | `presentation-evidence-v3` | `source/tests/code/{unit,contract}` | FIT session分区、睡眠阶段、30秒序列、raw/SHA闭合；不从采样重新划区 |
| v3 OpenDesign 渲染 | `opendesign-email-v3` | `source/tests/code/{unit,contract,integration}` | 共享table/CID组件、日报/周报组件顺序、真实图表、672/375px、幂等与隐私 |

## 工具采用情况

- 可执行技术栈：Python 3.12、SQLite、HTML/CSS、Pillow 12.3.0、Gmail MIME/REST Fake。
- Linter 配置和命令：`ruff --config skills/_shared/ruff.toml check skills tests/code`；
  `ruff format --check skills tests/code`；`mypy --config-file skills/_shared/mypy.ini skills tests/code`。
- 测试框架、定向命令和完整命令：`pytest tests/code -q`、只读 compile、全部 JSON Schema、
  Skill metadata、Markdown 链接、权限/隐私/布局、`git diff --check`。

## Subagent 派发

| Attempt | Agent 角色/任务 ID | 风险与复杂度 | 模型档位 | 推理档位 | 选档理由 | 平台支持 | 写入边界 | 产物与门禁 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Code Validator / M11-0005 | 高：Schema、MIME、幂等、隐私 | high | high | 跨模块与投递安全 | available | 只读 | 完整代码门和冻结验收 | INCONCLUSIVE：返工前未收到最终结论；不复用 |
| 1 | Visual Validator / M11-0005 | 高：邮件客户端兼容与状态覆盖 | high | high | 需要独立视觉判断 | available | 只读 | 桌面/375px/状态矩阵 | FAIL：自由文本泄漏工程字段、缺少 title；进入原范围返工 |
| 1 | Data/Privacy Validator / M11-0005 | 高：私人预览与来源闭包 | high | high | 私人证据边界 | available | 只读 | state 不变、manifest/隐私/零 Provider | PASS：旧快照权限、SQLite、MIME/RAW、零外部调用和正式 state 边界闭合；代码变化后不沿用为最终 PASS |
| 2 | Code Validator / M11-0005 | 高：Schema、MIME、幂等、展示隔离 | high | high | 返工后跨模块最终复验 | available | 只读 | 385 tests、静态门、逻辑重放和泄漏回归 | FAIL：title 未在 MIME 层核验、课程停止条件直出、隐私门不全、持久化 ViewModel 纯文本键序不稳定 |
| 2 | Visual Validator / M11-0005 | 高：真实数据可读性与响应式 | high | high | 返工后独立视觉复验 | available | 只读 | 8份桌面/375px、title/h1、图表、工程字段0 | FAIL：weekly hold 被错误表达为绿色“可以训练” |
| 2 | Data/Privacy Validator / M11-0005 | 高：私人预览与来源闭包 | high | high | 新 Candidate 必须重新验收 | available | 只读 | state 不变、manifest/权限/隐私/零 Provider | PASS：r02 数据、权限、lineage、正式边界和零 Provider 闭合；代码变化后不沿用 |
| 3 | Code Validator / M11-0005 | 高：Schema、MIME、幂等、展示隔离 | high | high | r03 冻结结果最终复验 | available | 只读 | 396 tests、完整静态门、重放和冻结合同 | FAIL：发送成功后RAW核验失败时回执漏记send/get；未跟踪设计文件空白未被普通diff门发现 |
| 3 | Visual Validator / M11-0005 | 高：真实数据可读性与响应式 | high | high | r03 桌面/手机与状态语义终验 | available | 只读 | 8份桌面/375px、title/h1、图表、hold语义 | PASS：16次实际渲染、CID/PNG、hold中性语义和展示隐私闭合；代码变化后不沿用 |
| 3 | Data/Privacy Validator / M11-0005 | 高：私人预览与来源闭包 | high | high | r03 私有产物与正式边界终验 | available | 只读 | state不变、manifest/权限/隐私/零Provider | PASS：r03权限、SQLite、lineage、Git和正式state边界闭合；代码变化后不沿用 |
| 4 | Code Validator / M11-0005 | 高：发送账本、Schema、MIME、幂等 | high | high | attempt3阻断修正后最终复验 | available | 只读 | 397 tests、发送后失败账本、完整含未跟踪diff门 | FAIL：unknown只读恢复在RAW/确认失败时未发布reconciliation回执 |
| 4 | Visual Validator / M11-0005 | 高：真实数据可读性与响应式 | high | high | 最终源码与r03必须重新独立验收 | available | 只读 | 8份桌面/375px、title/h1、图表、hold语义 | PASS：16次实际渲染和展示闭包；代码变化后不沿用 |
| 4 | Data/Privacy Validator / M11-0005 | 高：私人预览与来源闭包 | high | high | 最终源码与r03必须重新独立验收 | available | 只读 | state不变、manifest/权限/隐私/零Provider | PASS：r03和正式边界闭合；代码变化后不沿用 |
| 5 | Code Validator / M11-0005 | 高：完整投递/恢复账本矩阵 | high | high | attempt4恢复分支收敛后最终复验 | available | 只读 | 401 tests、全部Provider失败分支和完整门 | FAIL：明确send错误归类、已知Gmail ID恢复、本地MIME断点三项缺口 |
| 5 | Visual Validator / M11-0005 | 高：真实数据可读性与响应式 | high | high | 最终源码与r03重新独立验收 | available | 只读 | 8份桌面/375px、title/h1、图表、hold语义 | PASS：16次实际渲染和展示闭包；代码变化后不沿用 |
| 5 | Data/Privacy Validator / M11-0005 | 高：私人预览与来源闭包 | high | high | 最终源码与r03重新独立验收 | available | 只读 | state不变、manifest/权限/隐私/零Provider | PASS：r03和正式边界闭合；代码变化后不沿用 |
| 6 | Code Validator / M11-0005 | 高：重排后的单写者完整状态机 | high | high | attempt5三项状态机缺口结构性收敛 | available | 只读 | 406 tests、有限I/O、改写Message-ID和禁止重发 | PASS：406 tests和全部静态门；有限I/O、改写Message-ID、send-started只读恢复、零调用重放均闭合 |
| 6 | Visual Validator / M11-0005 | 高：真实数据可读性与响应式 | high | high | 最终源码与r03重新独立验收 | available | 只读 | 8份桌面/375px、title/h1、图表、hold语义 | PASS：16次实际渲染、8图、MIME和展示隐私闭合 |
| 6 | Data/Privacy Validator / M11-0005 | 高：私人预览与来源闭包 | high | high | 最终源码与r03重新独立验收 | available | 只读 | state不变、manifest/权限/隐私/零Provider | PASS：r03权限/来源/SQLite/lineage/Git闭合，正式state前后不变 |
| 7 | Code Validator / M11-0006 | 高：真实 Gmail REST、单次发送、跨进程预算 | high | high | 新增外部动作适配器且发送前必须独立放行 | available | 只读 | 完整测试/静态门、两动作 Candidate、日报人工门、重放零发送 | INCONCLUSIVE：验证期间发现 capture 中间目录需显式 0700，源码冻结变化后主动中止；不复用 |
| 8 | Code Validator / M11-0006 | 高：真实 Gmail REST、单次发送、跨进程预算 | high | high | 目录权限回归补齐后重新完整独立放行 | available | 只读 | 412 tests与全部静态门、两动作Candidate、锁/预算/重放/隐私 | FAIL：Token 漂移会被覆盖接受；正式 state 检查位于 Candidate 锁外，存在先发送后发现漂移的窗口 |
| 9 | Code Validator / M11-0006 | 高：发送前冻结输入与 TOCTOU 回归 | high | high | attempt8 两项发送前 fail-closed 缺陷修复后必须重新完整独立放行 | available | 只读 | 414 tests与全部静态门；Token/state漂移均须 Gmail 调用为0 | FAIL：检查通过后至 transport 创建间仍可替换 Token/state；Fake Provider 已发生4次调用/1次send后才发现 |
| 10 | Code Validator / M11-0006 | 高：冻结文件身份、正式锁和调用前复核 | high | high | attempt9 定位的最后竞态窗口收敛后重新完整独立放行 | available | 只读 | 416 tests与全部静态门；已打开Token身份绑定、正式锁覆盖发送、transport后零调用复核 | FAIL：请求记账后至HTTP调用前缺最后身份核对；Token刷新检查与覆盖不是原子比较交换 |
| 11 | Code Validator / M11-0006 | 高：逐调用 Token 绑定与原子刷新 | high | high | attempt10 后本应继续复验，但已触发 high/high 停止规则 | available | 只读 | 未启动、无验收产物 | cancelled：用户批准恢复 A-010；不再用同 UID 任意篡改扩大威胁模型 |
| 1 | Design Validator / M11-0006 | 高：信任边界、线性化点与有限故障矩阵 | high | high | 先冻结设计合同，避免 Code Validator 逐轮增加威胁 | available | 只读 | A-010/A-011/A-013、F01-F12、历史 Block 分类、Validator 停止规则 | FAIL：F09布尔门、F08刷新崩溃前后、Skill/external双层状态、F06/F07错误分类四项未决；信任边界和停止规则PASS |
| 2 | Design Validator / M11-0006 closure | 高：四项章程澄清的最终设计放行 | high | high | 用户明确批准一次性澄清后必须由全新 Agent 复核 | available | 只读 | F09严格布尔门、F08阶段恢复、双层状态、F06/F07重试分类及F12 CID闭包 | PASS：候选澄清形成 decision-complete 有限故障矩阵；未扩张 A-010 信任边界 |
| 1 | Code Validator / M11-0006 closure | 高：简化后的 REST 状态机、正常刷新崩溃恢复 | high | high | Design PASS 后按冻结矩阵一次性验收 | available | 只读 | 426 tests、完整门、Fake HTTP REST 两封闭环、F01-F12 | FAIL：F01-F04 内的外部动作与 Skill run 未形成失败双终态，崩溃恢复也未形成 interrupted→recovery 运行链 |
| 2 | Final Code Validator / M11-0006 closure | 高：双终态与崩溃恢复汇总修正 | high | high | 冻结计划只允许一个汇总修正批次和一次最终复验 | available | 只读 | 431 tests、F01-F12、双终态、恢复运行链、完整门 | FAIL：F05/A-011 中 Gmail ID 已返回但 `send-response` 尚未发布即崩溃时，恢复未采用已有 durable capture 的 Gmail ID；遇实际 Message-ID 改写会停在 unknown |
| 3 | Code Validator / M11-0006 F05 recovery | 高：durable capture 身份绑定与只读恢复 | high | high | 用户明确批准仅修复冻结 F05/A-011 缺口并增加一次独立复验 | available | 只读 | F01-F12、capture 绑定、改写 Message-ID、单次发送、442 tests与完整门 | FAIL：F05与全部门PASS，但明确HTTP 400且无Gmail ID时 external action 被归为unknown而非F06/F07要求的failed_safe |
| 4 | Code Validator / M11-0006 F06/F07 classification | 高：明确send拒绝双终态与禁止重发 | high | high | 用户在停止后明确批准仅修正Validator定位的终态分类 | available | 只读 | 明确HTTP 4xx→failed_safe、Skill blocked、send=1、重放=0、443 tests与完整门 | PASS：64项定向、443项全量和全部静态门通过；4xx/unknown/F05恢复均闭合 |
| 5 | Code Validator / M11-0006 recent-health correction | 高：有界历史健康选择、旧证据隔离、累计发送预算 | high | high | A-014 改变日报确定性输入和新 Candidate，真实重发前必须重新独立放行 | available | 只读 | 30/14天边界、日期/单位/完整性、AI SHA不变、旧周报零调用、累计send3/API48及完整门 | FAIL：真实解析器忽略显式异常单位，且同一节点多个日期字段冲突时只读取第一个；455项与其余门通过 |
| 6 | Final Code Validator / M11-0006 recent-health parser closure | 高：真实 Garmin JSON 单位与日期冲突修正后的最终放行 | high | high | attempt5 定位 A-014 范围内真实缺口，修正实现和回归后必须由全新 Agent 复验 | available | 只读 | 真实解析器错误单位/日期冲突、r05c闭包、全部代码门及既有预算/旧证据 | FAIL：解析器与全部门通过，但修正版日报text/plain遗漏VO₂ Max和体重的实际测量日期，违反A-014展示合同 |
| 7 | Code Validator / M11-0006 text-date closure | 高：用户授权high/high停止后的单点展示修正复验 | high | high | 用户明确批准仅修正最终Validator定位的text/plain日期缺口 | available | 只读 | HTML/text日期一致、解析器回归、全门、r06预览与既有预算/旧证据 | FAIL：实现把全部日报metric detail写入text/plain，额外改变睡眠文字，超出仅VO₂ Max/体重日期的单点授权 |
| 8 | Final Code Validator / M11-0006 text-date scope closure | 高：用户再次确认严格限定两个指标后的最终放行 | high | high | 用户明确授权仅vo2_max/weight写入纯文本detail，其他纯文本必须不变 | available | 只读 | r05c→r07纯文本仅两行变化、全门、解析器、旧证据、预算与重放 | PASS：131项定向、463项全量及全部静态门通过；冻结范围无未满足项，旧M9时序抖动fail-closed且不阻断本范围 |
| 1 | Delivery/Data-Privacy Validator / M11-0006 | 高：两封真实远端证据与正式边界 | high | high | 真实发送完成后必须复验 RAW、权限、state/Token 和越界调用 | available | 只读 | 两 Gmail ID/RAW、正式state不变、零非授权Provider | 等待两封用户确认后派发 |
| 1 | Design Validator / M11-0007 | 高：跨Schema教练合同、安全与验收边界 | high | high | 先冻结无心率区间、SOS和内容可用性，避免实现后改变预期 | available | 只读 | A-015、v2章程、Skills/AGENTS/计划一致性 | FAIL：周报raw回退、硬负荷间隔、SOS零课、v2路由和可比配速存在歧义 |
| 2 | Final Design Validator / M11-0007 | 高：五项设计歧义收敛 | high | high | 以公式、版本名和Host选择合同形成唯一判定 | available | 只读 | 禁止raw、日期差≥3、零SOS证据、v2路由、42天参考配速 | PASS：五项均形成唯一判定；Provider 0、正式state 9345项指纹不变 |
| 1 | Code Validator / M11-0008..0009 | 高：v2 Schema、SOS、安全门、日周渲染与v1隔离 | high | high | 跨模块教练合同和内容安全 | available | 只读 | 484 tests、Ruff/format/mypy/compile/Schema、冻结章程 | FAIL：心率别名、SOS理由、工程字段、纯文本细节和v1 rubric五项缺口 |
| 2 | Final Code Validator / M11-0008..0009 | 高：五项缺口汇总收敛 | high | high | 只允许一次汇总修正后完整复验 | available | 只读 | 492 tests、反例门、v1映射、完整静态门 | FAIL：周总结自由文本仍可输出Zone/BPM处方；工程禁词遗漏output_id/content_json/skill_run_id等 |
| 3 | Authorized Final Code Validator / M11-0008..0009 | 高：统一读者文字安全门 | high | high | 用户明确授权仅闭合最终两项缺口 | available | 只读 | 503 tests、全部可见文字心率处方/工程字段反例、完整门 | FAIL：组合字段source_output_id等可利用下划线词边界绕过 |
| 4 | Composite Identifier Final Validator / M11-0008..0009 | 高：组合内部标识符闭合 | high | high | 用户要求问题在原目标内持续修复至真实完成 | available | 只读 | 组合字段反例、完整门、零Provider | FAIL：组合内部标识符已闭合；中文紧邻Z2、独立BPM及HRmax仍可绕过心率处方门 |
| 5 | Chinese Heart-rate Boundary Final Validator / M11-0008..0009 | 高：中文连接形式与心率别名闭合 | high | high | 只修复同一冻结读者安全门，不改变训练业务合同 | available | 只读 | 中文紧邻反例、完整门、零Provider | FAIL：中文紧邻Z2、BPM、HRmax均闭合；独立Zone仍可进入周报可见文字 |
| 6 | Standalone Zone Final Validator / M11-0008..0009 | 高：无数字Zone与中文心率分区闭合 | high | high | 同一冻结无心率区间合同的最后词法反例 | available | 只读 | 独立Zone/心率分区、完整门、零Provider | FAIL：独立Zone和已列形式闭合；合并写法“心率上下限”仍可见 |
| 7 | Chinese Range Synonym Final Validator / M11-0008..0009 | 高：中文心率范围同义表达闭合 | high | high | 只扩充同一冻结词法集合 | available | 只读 | 上下限/范围/区带、完整门、零Provider | FAIL：前置最大/阈值闭合，但倒装“心率最大/阈值”因两份词表不对称而遗漏 |
| 8 | Symmetric Chinese Term Final Validator / M11-0008..0009 | 高：中文词表前后置对称闭合 | high | high | 结构性消除同一词表的顺序遗漏 | available | 只读 | 双向词表、完整门、零Provider | FAIL：输入词法门闭合；周报模板自身硬编码免责声明含“心率区间”且最终HTML未二次校验 |
| 9 | Final Render Safety Validator / M11-0008..0009 | 高：模板常量与最终HTML/text安全闭合 | high | high | 同一冻结读者安全门覆盖最终产物 | available | 只读 | 最终产物安全门、完整门、零Provider | FAIL：模板产物闭合；Z-2、BPM150、HR-max、target HR及A-015明确禁止的乳酸阈值仍可绕过 |
| 10 | Separator and Threshold Final Validator / M11-0008..0009 | 高：分隔符、缩写和乳酸阈值闭合 | high | high | 冻结词法合同的结构化变体覆盖 | available | 只读 | 分隔/顺序变体、最终产物、完整门、零Provider | PASS：521 tests与全部静态门；174种心率变体、21种工程标识符零遗漏，Provider 0 |
| 1 | AI Validator / M11-0010 | 高：私人健康/训练语义、证据与课程可执行性 | high | high | 真实私人结果且不得自我认证 | available | 只读 | 7日报、1周报、证据引用、SOS、详细步骤、安全与不编造 | FAIL：8月12日原课来自本轮新生成的测试基准而非历史计划；周报把日报建议误写成已执行负荷；6份日报未单独解释昨日非睡眠健康数据 |
| 1 | Visual/Coach Utility Validator / M11-0010 | 高：8份真实邮件的桌面/375px可读性 | high | high | 需独立视觉和内容可用性判断 | available | 只读 | 8份HTML/text、响应式、无工程泄漏、课程层级与摘要可读 | FAIL：8月12日有效课缺少独立 recovery 阶段；其余课程、摘要和响应式检查通过 |
| 1 | Data/Privacy Validator / M11-0010 | 高：Candidate、血缘、权限与正式边界 | high | high | 私人证据和零外部调用终验 | available | 只读 | SQLite/manifest/SHA、权限、9次AI、Provider/external=0、正式state不变 | FAIL：只读审计错误使用普通SQLite连接，在r01创建SHM；其余完整性、血缘、权限、零外部调用和正式state边界通过。r01永久保留失败证据 |
| 1 | Code Validator / M11-0010 r02 | 高：原课身份、四阶段、健康分栏与建议/执行隔离 | high | high | 三项私人验收缺口已下沉为确定性合同 | available | 只读 | 526 tests、新回归、全部代码门、r01不变、Provider 0 | FAIL：来源缺失会默认verified_original；昨日健康缺失会回退睡眠文字；“本周已执行降级，训练负荷比原计划减少”可绕过建议/执行门 |
| 2 | Final Code Validator / M11-0010 r02 | 高：三项fail-closed缺口汇总修正 | high | high | 同一冻结范围只允许一次汇总修正后最终复验 | available | 只读 | 527 tests、缺字段拒绝、语义组合门、全部静态边界 | PASS：527项全量、64项定向及全部静态/隐私门通过；四项冻结合同和v1隔离独立闭合 |
| 3 | Phase Prompt Validator / M11-0010 r02 | 高：AI有效课四阶段和四种决策 | high | high | 首轮r02模型结果缺少独立recovery，需先闭合提示合同 | available | 只读 | keep/downgrade/rest/blocked、四阶段、527 tests与全部门 | FAIL：提示仅明确keep/downgrade，未完整覆盖rest/blocked |
| 4 | Final Phase Prompt Validator / M11-0010 r02 | 高：四决策与四阶段闭合 | high | high | 同一提示合同修正后全新复验 | available | 只读 | 四种决策、四阶段、527 tests与全部门 | PASS：提示与Schema/Host门一致，四种决策均不得省略recovery；完整门通过 |
| 5 | Observed BPM Validator / M11-0010 r02 | 高：历史观测与课程处方隔离 | high | high | r02真实健康摘要含RHR观测值，需允许事实但禁止课程心率 | available | 只读 | 观测上下文、课程零心率、处方同义表达、530 tests | FAIL：观测值可注入课程，且目标静息心率、提高平均心率、target heart rate等可绕过 |
| 6 | Course Render Final Validator / M11-0010 r02 | 高：最终渲染层课程零心率保证 | high | high | ViewModel可能被篡改，最终渲染必须独立保护课程 | available | 只读 | 24项课程篡改、16项处方/渲染探针、530 tests与全部门 | PASS：课程构建与最终渲染双层门闭合；历史观测只在明确健康上下文显示 |
| 2 | AI Validator / M11-0010 r02 | 高：修正后的七日报一周报语义终验 | high | high | 必须使用全新Candidate和全新Agent | available | 只读 | 测试基准披露、昨日健康/睡眠分栏、建议不冒充执行、训练合理性 | FAIL：8月18日Host将周均HRV 74覆盖为昨夜HRV字段；源证据实际为昨夜76、周均74，错误不能靠uncertainty变为有效 |
| 2 | Visual/Coach Utility Validator / M11-0010 r02 | 高：修正后8份真实邮件桌面/375px可用性 | high | high | 四阶段和展示语义发生修正 | available | 只读 | localhost实际渲染、课程层级、健康分栏、无工程泄漏 | PASS：8份×2视口共16次实际渲染；布局、课程四阶段、摘要层级和读者安全闭合 |
| 2 | Data/Privacy Validator / M11-0010 r02 | 高：全新Candidate、不可变只读审计与正式边界 | high | high | r01审计产生sidecar后不得复用 | available | 只读 | immutable SQLite、无sidecar、manifest/SHA、权限、Provider/external=0、正式state不变 | PASS：108项manifest、26项输出、7次AI、SQLite/权限/正式state/零外部动作闭合；未创建sidecar |
| 1 | Code Validator / M11-0010 r03 HRV binding | 高：低频健康指标语义绑定 | high | high | 唯一AI阻断来自确定性Host映射，真实发送前必须测试先行闭合 | available | 只读 | 昨夜/周均HRV顺序无关、真实7日字段名、全门、r02不变 | FAIL：顺序和真实字段均闭合，但任意后缀匹配仍接受伪造前缀other_/weekly_*_last_night，缺少拒绝测试 |
| 2 | Final Code Validator / M11-0010 r03 HRV allowlist | 高：昨夜HRV字段白名单 | high | high | 只收敛Validator定位的任意前缀缺口 | available | 只读 | 6个批准名称、2个恶意前缀拒绝、540 tests与全部门 | PASS：5040种顺序探针、6项allowlist/非法前缀、540 tests和全部静态/隐私门通过 |
| 3 | Weekly Evidence Prompt Validator / M11-0010 r03 | 高：周洞察只引用v2日报 | high | high | 首次周报模型误用嵌套legacy ID，重试前必须消除提示歧义 | available | 只读 | 顶层7个daily_input_refs、禁止digest/nested legacy/raw、541 tests与全门 | FAIL：提示歧义已消除，但refs校验接受bool ID和非hex SHA；非mapping输入未稳定拒绝 |
| 4 | Final Weekly Evidence Validator / M11-0010 r03 | 高：v2日报引用严格绑定 | high | high | 只闭合首次Validator定位的确定性输入校验缺口 | available | 只读 | 正整数ID、64位hex SHA、7项唯一refs、546 tests与全部门 | PASS：22类恶意ref探针、546 tests及全部门通过；放行预算内仅一次周报重试 |
| 5 | Observed HR Range Validator / M11-0010 r03 | 高：历史健康事实与心率处方隔离 | high | high | 周报成功后渲染安全门误拒绝历史静息心率范围 | available | 只读 | 历史范围允许、目标/控制范围拒绝、课程零心率、547 tests与全部门 | FAIL：远距离“必须达到的目标”可绕过，且历史BPM例外未限定health字段 |
| 6 | Final Health-context HR Validator / M11-0010 r03 | 高：字段级历史观测例外与整句处方阻断 | high | high | 只闭合Validator定位的两项同源fail-open | available | 只读 | health-only、整句目标/必须/控制、最终渲染绑定、549 tests与全部门 | FAIL：独立“达到/应达到”仍可绕过；en dash历史范围被误拒 |
| 7 | Final HR Sentence Validator / M11-0010 r03 | 高：达到词与范围分隔符闭合 | high | high | 仅补齐上一Validator一次性汇总的两个词法边界 | available | 只读 | 达到/应达到拒绝、6种范围允许、课程/非health严格、550 tests与全部门 | FAIL：活动最高心率允许，但同义“活动最大心率”被通用最大心率门误拒 |
| 8 | Final Observed-fragment Validator / M11-0010 r03 | 高：完整历史片段遮盖后再扫描剩余处方 | high | high | 结构性消除健康历史事实与通用禁词冲突 | available | 只读 | 3类标签×6分隔符、处方残余、非health/课程/最终渲染、550 tests与全部门 | FAIL：裸“保持”真实绕过；另三项中同句历史词、重复观测唯一性及平均心率限制均超出A-015 |
| 9 | Final A-015 Observed-fact Validator / M11-0010 r03 | 高：按批准规则冻结health字段与处方残余 | high | high | 修复真实保持绕过，并拒绝Validator临时扩张合同 | available | 只读 | health字段即历史上下文、平均/最高事实、保持拒绝、非health严格、551 tests与全部门 | FAIL：中文/英文分号被当句界，后半句“必须达到”可与前面BPM脱钩 |
| 10 | Final Semicolon Boundary Validator / M11-0010 r03 | 高：分号内处方关联闭合 | high | high | 只修复唯一剩余的句界词法漏洞 | available | 只读 | 中英文分号、合法多观测、A-015字段边界、551 tests与全部门 | PASS：131项定向、551项全量与全部门通过；放行现有92/93确定性渲染，零新模型/Provider |
| 11 | Final Narrative/Course Boundary Validator / M11-0010 r03 | 高：A-015历史事实与课程处方分层 | high | high | 真实日报调整理由含合法RHR事实，暴露先前health-only人为收窄 | available | 只读 | narrative历史事实、course零心率、可见HTML分块、551 tests与全部门 | PASS：120项定向、551项全量、端到端正负探针与全部门通过；放行现有r03确定性渲染 |
| 3 | AI Validator / M11-0010 r03 | 高：最终七日报一周报语义、证据和课程可执行性 | high | high | r02 AI FAIL后必须以全新r03完整复验 | available | 只读 | 7日报、1周报、证据、指标复算、SOS、四阶段、安全与不编造 | PASS：指标独立复算一致，7日报与周报证据闭合；下一周恰好1节条件性SOS，课程零心率处方，v2新增外部动作0 |
| 3 | Visual/Coach Utility Validator / M11-0010 r03 | 高：最终8份邮件桌面/375px可用性 | high | high | 最终内容和渲染必须重新实际检查 | available | 只读 | 8份HTML×2视口、层级、无溢出/断图/工程泄漏、课程可执行性 | PASS：16/16无溢出、裁切或断图；标题/章节/课程细节完整，历史BPM仅作事实展示 |
| 3 | Data/Privacy Validator / M11-0010 r03 | 高：DB-only Candidate、血缘、权限和正式边界 | high | high | r03为全新派生Candidate且必须immutable审计 | available | 只读 | SQLite/Schema/SHA、父库绑定、权限、重放、零v2外部动作、正式state不变 | PASS：26项v2输出和52条血缘闭合，7次AI/Provider0/v2外部动作0，正式9347项不变且无sidecar/隐私泄漏 |
| 1 | Code Validator / M11-0012..0014 v3 r01 | 高：FIT/睡眠解析、Schema、冻结输出、共享渲染、MIME与隐私 | high | high | v3跨模块与私人Candidate终验 | available | 只读 | 576 tests、84–93冻结、SQLite/raw/MIME/lineage、Provider/external=0 | FAIL：五个合法`training_plan_v2`课程类型缺少中文映射，最终HTML泄漏内部英文枚举；其余代码与Candidate闭包通过 |
| 2 | Final Code Validator / M11-0012..0014 v3 r02 | 高：完整课程枚举中文展示与既有v3合同 | high | high | 仅修正首次Validator定位的范围内显示缺口后完整复验 | available | 只读 | 577 tests、9种课程类型、r02完整门与Candidate闭包 | FAIL：多session FIT中非0 index在唯一性计数前被忽略，可把index0误当唯一分区；其余全部门通过 |
| 3 | Final Code Validator / M11-0012..0014 v3 r03 | 高：所有session候选先计数与完整v3合同 | high | high | 闭合A-016重复session fail-closed后完整复验 | available | 只读 | 578 tests、跨index重复/异常index、r03完整门与Candidate闭包 | FAIL：缺失/None/浮点index及字符串数值仍被接纳；其余全部门通过 |
| 4 | Final Code Validator / M11-0012..0014 v3 r04 | 高：FIT分区严格类型与完整v3合同 | high | high | 闭合A-016格式异常fail-closed后完整复验 | available | 只读 | 585 tests、32组额外恶意FIT探针、冻结84–93、r04 SQLite/raw/MIME/重放与零Provider闭包 | PASS：所有合法与异常分区输入均fail-closed；未从采样重划区；其余完整代码门与Candidate闭包通过 |
| 5 | Design-Fidelity Validator / M11-0014 v3 r04 | 高：OpenDesign日报/周报逐组件及672/375响应式终验 | high | high | 必须实际渲染两类邮件并独立比较完整交接规范 | available | 只读 | 八份预览、日报/周报顺序、卡片/KPI/图表/时间轴、九种课程中文化、状态与无数据分支 | FAIL：品牌外壳/颜色偏离交接；状态无图形标识；睡眠时间显示UTC原串；周报降级单位仍为英文；其余顺序、响应式、图表、隐私通过 |
| 6 | Code Validator / M11-0012..0014 v3 r05 | 高：四项视觉修正、CID品牌资产、MIME跨层合同和完整既有边界 | high | high | r04视觉返工修改生产代码与Schema后必须重新执行完整独立代码验收 | available | 只读 | 592 tests、四项显示回归、品牌/状态CID MIME、冻结84–93、r05 Candidate闭包 | FAIL：展示转换层以宽松相等接纳`False`和`0.0`为session index 0；其余代码、Candidate、视觉、MIME和隐私门全部通过 |
| 7 | Final Code Validator / M11-0012..0014 v3 r06 | 高：FIT session index双层严格类型与完整v3闭包 | high | high | r05 Validator定位原始解析后第二转换层的同范围类型缺口，修复后必须全新复验 | available | 只读 | 594 tests、`False`/`0.0`反例、冻结84–93、r06 Candidate、重放、MIME、正式state和零Provider | PASS：两层原生整数0、全部异常输入、冻结输出、七日报引用、9473文件/9370 raw/8 MIME、正式state及零外部调用全部闭合 |
| 8 | Design-Fidelity Validator / M11-0014 v3 r06 | 高：OpenDesign逐组件、真实图表和双视口响应式终验 | high | high | r04视觉FAIL后的四项修正及r06最终代码需由全新视觉Agent实际浏览器复验 | available | 只读 | 七日报一周报、672×1000/375×812、外壳/品牌/状态/KPI/图表/时间轴/缺失状态及文本降级 | PASS：16次实际渲染；OpenDesign组件/色彩/状态/HKT/中文单位/真实图表/响应式与缺失状态全部闭合 |
| 9 | Data/Privacy Validator / M11-0014 v3 r06 | 高：私人真实数组、血缘、权限、正式state及零外部调用终验 | high | high | Code与Design串行PASS后，最终私人Candidate仍需全新数据隐私Agent独立放行 | available | 只读 | SQLite/raw/SHA/manifest、84–93冻结、七日报聚合、权限/隐私、正式state、Provider/external=0 | PASS：9473文件/9370 raw、SQLite/86 triggers、84–93、真实数组、37 PNG/8 MIME、权限、正式state及零外部调用全部闭合 |

## 工作分解

| 步骤 | 状态（`pending`、`in_progress`、`blocked`、`done`） | 证据 |
| --- | --- | --- |
| M11-0001 M10 基线、设计快照与治理冻结 | done | M10 门 331 PASS；本地提交 `b172f95`；A-013、41 文件设计摘要和 183 行映射已冻结 |
| M11-0002 ViewModel、模板、字段映射与图表 | done | 显式 daily/weekly ViewModel、Pillow PNG、HTML/text、35 项定向测试通过 |
| M11-0003 CID MIME v2、RAW 核验与 Fake 投递 | done | MIME v2、实际 Message-ID RAW 闭合、Fake 单写者与只读恢复通过 |
| M11-0004 完整代码门与私有真实预览 | done | r03：8份预览/8份离线MIME，396 tests与完整静态门通过；桌面/375px全绿，确定性重放产物字节与16项业务输出不变 |
| M11-0005 三类全新只读 Validator | done | attempt6 Code、Visual、Data/Privacy 三类全新只读 Validator 全部 PASS |
| 停在真实 canary 授权前 | done | 已达到计划完成边界；未调用 Gmail，后续真实 canary 需单独授权 |
| M11-0006 真实 Gmail 样式 canary | done | 历史技术投递/RAW/CID闭合，内容与视觉验收失败证据保留；后续v2/v3替代旧展示，v3真实重发不在本计划 |
| M11-0007 Coaching Utility v2 治理和设计合同 | done | A-015、冻结章程与五项收敛修订经全新 Final Design Validator PASS |
| M11-0008 v2 证据、AI、课程与安全合同 | done | 521 tests；174种心率处方变体、SOS/硬负荷/七日报合同经全新Validator PASS |
| M11-0009 v2 ViewModel 与可读渲染 | done | ViewModel、模板常量、最终HTML/text共用安全门；21种工程标识符经Validator PASS |
| M11-0010 七日报一周报私有离线验收 | done | r03：7日报、1周报、2份计划、8份预览；551 tests与Code/AI/Visual/Data-Privacy全部PASS，重放零增量，Provider与v2外部动作均为0 |
| M11-0011 v3 规则与设计验收冻结 | done | A-016；三项只读审计确认交接完整、真实分区/睡眠字段存在，缺口位于解析及简化渲染路由 |
| M11-0012 v3 展示证据与共享高保真渲染 | done | 测试先行；冻结AI/课表84–93，新增五项版本化Schema并恢复日报/周报卡片、KPI、真实图表和时间轴；补齐9种课程中文映射与FIT严格类型，585 tests及全部静态门通过 |
| M11-0013 v3 owner-only 离线 Candidate | done | r01–r05及首个MIME白名单失败r05证据保留；全新 `/private/tmp/trainlab-m11-v3-r06.T6nbtk` 含七日报一周报、8份MIME，重放零增量且SQLite/raw/权限/正式state闭合 |
| M11-0014 三类全新只读 Validator | done | r06按 Code → Design-Fidelity → Data/Privacy 严格串行全部PASS；仅交付离线预览，真实邮件另行授权 |

## 当前检查点

- 当前 Loop：M11 v3 OpenDesign 设计一致性修复。
- 最近完成：旧版日报被用户判定为视觉验收失败；只读审计确认 OpenDesign 交接完整，固定窗口 FIT
  存在 session 级设备分区时长，睡眠 raw 存在阶段时长，而 v2 简化渲染路由未消费这些证据。
- 当前焦点：r06 Code、Design-Fidelity、Data/Privacy三类全新只读Validator全部PASS。
- 下一动作：归档M11并仅交付离线预览；真实Gmail重发或部署必须另建计划并精确授权。
- 阻塞项：无；旧周报保持 prepared/attempt=0 并退出活动发送路由。
- 已变更文件：治理/计划、requirements、版本化 Schema、两个 Skill 实现/文档、设计快照和测试。
- 待验证项：无；真实Gmail投递与部署不属于本计划。
- 当前代码门：594 tests；Ruff、format、mypy、compile、64 Schema、Skill/AI metadata、Markdown、权限、隐私、布局及 tracked/untracked diff 全部通过；r06 Candidate 9473文件、9370 raw、8份MIME、SQLite integrity/FK/86 triggers、冻结84–93、零外部动作和字节级重放闭合；正式state 9347项指纹与基线一致。

## 决策与发现

- 交接 HTML 是视觉规范而不是可直接执行模板；生产实现使用显式 Python 组件，禁止任意模板求值。
- 当前证据没有冻结的心率区间、完整睡眠阶段时长或训练负荷标尺，这些图表按 A-013 隐藏。
- 日报仅在存在唯一、已验证且日期相同的周计划课程时展示今日课；否则显示未安排，不采用宽松
  `today_course` 作为可执行课程来源。
- 设计交接的 SVG/PNG 仅作视觉样例；生产图表必须从当前输入重新确定性生成。

## 任务级独立验证

- 中性交接：只提供冻结目标、适用规则、最终仓库结果和 r06 Candidate，不提供实施者辩护。
- Validator 身份/上下文：三名全新只读 Final Code、Design-Fidelity、Data/Privacy Validator。
- 模型/推理档位：high/high。
- 命令与观察：Code 完整运行594 tests、Ruff/format/mypy/compile/64 Schema/metadata/Markdown/隐私/布局/diff、FIT恶意输入及Candidate闭包；Design-Fidelity实际渲染7日报和1周报的672×1000与375×812；Data/Privacy以immutable SQLite和正式lock完成9473文件、9370 raw、lineage、权限、Git及正式state审计。
- 结果：`PASS / PASS / PASS`
- 未满足项与剩余风险：无；真实 Gmail/Outlook/移动客户端和部署只留给另行授权的后续阶段。

## 集成级独立验证

- 集成范围：严格串行，无并行集成。
- 中性交接：不适用。
- Validator 身份/上下文：不适用。
- 模型/推理档位：不适用。
- 完整 lint/test 与回归观察：由三类任务级 Validator 覆盖。
- 结果：`不适用——无并行集成`
- 未满足项与剩余风险：无。

## PLANS 回写清单

- [x] Exec plan 已归档到 `completed/`
- [x] Roadmap 叶子任务已更新为 `[x] completed`
- [x] 子项目和阶段状态已重新计算
- [x] `memory.md` 中的活动计划指针已删除

M11 v3 按批准范围停在真实重发授权前；离线计划本身已完成并归档。

## 迭代日志

| 日期/上下文 | 已完成事项与证据 | 发现 | 下一动作 |
| --- | --- | --- | --- |
| 2026-08-21 / start | M10 331 tests、Ruff、format、mypy、compile、Schema/隐私/布局通过并提交 `b172f95` | 交接包筛选 manifest SHA 已冻结；生产图表不能复用样例数据 | 精简设计快照并实现 M11-0002 |
| 2026-08-21 / implementation | 新增 7 个 Schema、显式 ViewModel、HTML/text、PNG、CID MIME v2、Fake 投递；35 项定向测试 PASS | blocked 周报不能被迫伪造 progression；预览回执本身也必须 owner-only | 运行完整门并生成 8 份私有预览 |
| 2026-08-21 / private-preview | 最终 Candidate `/private/tmp/trainlab-m11-preview.1787288371540`：8 HTML/text/PNG/SQLite/RAW，8 不同 Message-ID，102 路径权限全绿，Provider/external=0；桌面/375px 全部无溢出/断图；373 tests PASS | 视觉验收发现并修复秒/小时单位、Garmin 攀岩标签、移动端半宽、中间目录0755及无图 MIME related 边界；7 个旧调试 Candidate 原样保留 | 交三类全新只读 Validator |
| 2026-08-21 / validator-rework | Visual Validator attempt 1 FAIL：部分日报正文复制 AI summary/claim，暴露 raw ID、SHA、字段名和原始秒数，且 HTML 缺少 title；Privacy attempt 1 对旧快照 PASS | 根因是严格事实层和用户展示层未彻底隔离，不是 AI 数据或 Gmail 发送问题 | 只修改展示实现与测试，建立全新 Candidate 后重新独立验证 |
| 2026-08-21 / validator-rework-closed | AI 自由文本摘要、claim、停止条件不再直接进入邮件；读者摘要/来源/安全文案从结构化状态确定性生成；新增 title 与 12 项泄漏回归。r01 因两份预览被安全门拒绝永久保留；r02 生成 8 份预览和 MIME，工程字段0，桌面/375px全绿，385 tests、Ruff/format/mypy/AST/46 Schema/隐私布局/diff全绿，重放产物与逻辑行摘要完全一致 | SQLite 正常连接会改变数据库文件头，因此幂等按业务行、output ID/SHA 和产物字节判断，不把文件头当业务输出 | 冻结 r02 与源码，交三名全新 Validator attempt 2 |
| 2026-08-21 / validator-attempt-2 | Code FAIL：MIME title、课程停止条件、隐私词表和持久化 ViewModel 键序共4项；Visual FAIL：weekly hold 被显示为“可以训练”；Data/Privacy PASS 仅适用于 r02 | 五项均属于冻结展示/MIME合同，不改变日期、数据、结论或发送边界 | 合并为一次原范围返工，r02 永久保留，建立全新 r03 并重新三类验证 |
| 2026-08-21 / r03-final-freeze | 补齐MIME唯一title门、课程安全文案规范化、隐私词表与错误码隐藏、纯文本固定键序和weekly hold中性语义；r03 8份预览/8份MIME、396 tests、完整静态门、权限/SQLite闭包和确定性重放通过 | 普通SQLite只读审计会在Candidate建立空sidecar；确认WAL为0后仅清理Candidate sidecar，后续统一使用immutable只读 | 冻结源码与r03，交三名全新只读Validator attempt 3 |
| 2026-08-21 / validator-attempt-3 | Visual与Data/Privacy PASS；Code FAIL定位发送后RAW核验失败回执少算send/get，以及未跟踪设计文件空白逃逸普通diff门 | 发送账本必须在Provider调用前计数；完整diff门必须覆盖未跟踪文本 | 引入统一调用账本、新增发送后RAW不匹配回归、清理4份设计文件空白，397 tests通过后交全新attempt4三类Validator |
| 2026-08-21 / validator-attempt-4 | Visual与Data/Privacy PASS；Code FAIL定位unknown恢复在RAW核验失败时异常逸出、两次只读调用无恢复回执 | 投递与恢复必须共用完整Provider调用账本和终态发布规则，不能只覆盖即时发送分支 | 收敛全部恢复结果，新增网络、RAW不符和确认不符回归；10项定向/401项完整测试通过后交全新attempt5三类Validator |
| 2026-08-21 / live-canary-attempt-8 | Code Validator FAIL：Candidate 建立后 Token 漂移被覆盖接受；正式 state 仅在锁外核对，存在先发送后发现漂移的窗口 | 发送前所有可变边界必须在 Candidate 单写者锁内重读，且 transport 创建前 fail-closed | 锁内重核正式 state、Token、收件人和冻结请求；新增两项零 Provider 对抗回归后交全新 attempt9 |
| 2026-08-21 / live-canary-attempt-9 | Code Validator FAIL：锁内检查与 transport 创建之间仍可发生 Token/state 替换，最终检查虽阻断但 Provider 已调用 | 单次哈希检查不能固定文件身份；需要把正式锁和已打开 Token 绑定延伸到实际调用边界 | 正式锁覆盖完整发送、Token 使用已打开内容并在每次请求前核对、transport 后再复核；新增两项竞态测试后交 attempt10 |
| 2026-08-21 / live-canary-attempt-10 | Code Validator FAIL：请求预算落账后至HTTP系统调用前仍少一次Token核对；刷新路径会在检查后覆盖并发替换 | 文件身份绑定还必须覆盖每次调用和刷新发布的最后原子边界 | list/send/get紧邻调用前复核；刷新采用原子交换后校验被替换旧值，不匹配则原子恢复；新增4项对抗后交attempt11 |
| 2026-08-21 / trust-boundary-reset | 两份独立只读审计确认 attempt8-10 逐步越过 A-010；另定位正常 Token 刷新后崩溃会因 Candidate SHA 落后而永久 Block | 未冻结故障矩阵和持续接受同 UID monkeypatch 是重复 Block 主因；high/high 连续失败后不应继续自动重试 | 用户批准 F01-F12、三个线性化点和两次 Code Validator 上限；先交全新 Design Validator |
| 2026-08-21 / design-validator-1 | 信任主体、排除主体、三个线性化点和 Validator 停止规则通过；F09布尔门、F08刷新崩溃阶段、双层状态、F06/F07错误分类FAIL | 这是冻结章程内部的确定性歧义，不是新威胁；按high/high停止规则不得自动重试 | 保留FAIL，停止实现；等待用户批准一次性章程澄清后再交全新Design Validator |
| 2026-08-21 / design-validator-2 | 用户批准四项澄清；全新只读 high/high Validator 对严格人工门、刷新阶段、双层状态、重试预算和F12 CID闭包返回PASS | 设计合同已 decision-complete，不再允许 Code Validator 临时扩张同 UID/root/内核威胁 | 直接进入实现收敛、完整代码门和冻结矩阵 Code Validator |
| 2026-08-21 / implementation-closure | 移除Token CAS/逐调用SHA/长正式锁；Token使用0600临时文件、fsync与原子改名；补齐真实GmailRestClient Fake HTTP双封闭环、刷新与四个崩溃点回归；426 tests和完整静态门PASS | Token SHA只作审计，恢复由intent/send-started/远端事实决定；正式state仅短暂预检与终验 | 交全新Code Validator，PASS前Provider保持0 |
| 2026-08-21 / code-validator-closure-1 | 全新 high/high Code Validator 对完整门与 F01-F12 返回FAIL；全部静态门及426 tests本身通过 | 冻结矩阵内的真实缺口是发送失败只终结 external action，未同步终结 Skill run；崩溃恢复也没有旧 interrupted 与新 recovery run | 按计划合并为唯一修正批次，不扩张威胁模型、不进入第三轮 |
| 2026-08-21 / dual-terminal-closure | 每个发送动作新增独立 pending delivery run；正常开始转 running，失败形成 external failed_safe/unknown + Skill blocked，崩溃后形成 interrupted→recovery→terminal；补齐 Token/认证/正式state锁与漂移/本地I/O/unknown/四崩溃点回归，431 tests及完整静态门PASS | 已有远端完整结果时即使后续审计写失败，也依据 Gmail/RAW 事实闭合且重放不重发 | 交唯一一名全新最终 Code Validator；PASS 后真实发送日报 |
| 2026-08-21 / final-code-validator | 全新最终 high/high Code Validator 运行100项M11定向、431项完整测试和全部静态门，随后返回FAIL | F05/A-011 可达缺口：Provider 返回 Gmail ID 后、`send-response` 发布前崩溃；durable REST capture 已含 Gmail ID，但恢复未读取，遇实际 Message-ID 改写只能 unknown；未重发且双终态正确 | 按停止规则保持blocked，不真实发送、不自动第三轮，等待用户决定 |
| 2026-08-21 / f05-durable-id-recovery | 新增严格capture恢复与11项回归；51项定向、442项全量及完整静态门PASS；全新high/high Validator确认F05闭合但总体返回FAIL | 明确HTTP 400且无Gmail ID时，发送器正确停止但external action被`send-started`优先判为unknown；按F06/F07应为failed_safe | 保持blocked且Provider=0；等待用户决定是否授权仅修正该终态分类 |
| 2026-08-22 / send-rejection-closure | 用户批准后新增真实REST端到端回归并修正4xx终态优先级；37项Live、443项全量与完整门PASS，全新high/high Validator PASS；新Candidate日报单次发送并以4次API完成RAW/text/HTML/CID闭合 | 明确拒绝与不确定结果现已分流；日报成功且周报调用0 | 等待用户确认日报网页端和手机端，确认后才发送周报 |
| 2026-08-22 / recent-health-correction | A-014测试先行新增recent_health_metrics_v1、30/14天选择、日期绑定解析、历史展示overlay与版本化Live续跑；r04a因lineage字段名错误失败保留，r04d最终VO₂=51/8-10、体重70.3/8-07，周报字节不变；455 tests及完整静态门PASS | 精确日空对象不应让低频健康指标永久缺失；历史AI无需重跑，只需确定性快照和展示lineage | 交全新high/high Code Validator，PASS前不建Live Candidate、不调用Gmail |
| 2026-08-22 / recent-health-validator-1 | 全新high/high Validator确认r04d数据、AI/周报/旧Live/预算均闭合，但总体FAIL；真实探针复现155lb被当155kg、watts被当VO₂单位，以及calendarDate与measurementDate冲突仍被接受 | 单位回归只覆盖FakeParser，没有穿过生产parse_raw；生产日期选择采用first-match，违反A-014异常单位和日期冲突拒绝条款 | 修正真实解析器并增加7项生产解析回归；以新源码建立r05c，输出数值与日报/周报字节保持不变，再跑完整门并交全新最终Validator |
| 2026-08-22 / recent-health-validator-2 | 生产解析器拒绝异常单位/日期冲突并接受kg/g/ml/kg/min和无单位真实格式；r05c闭合，462 tests及全部静态门PASS；全新最终Validator仍返回FAIL | HTML/ViewModel已显示更新日期，但text/plain健康卡片只输出数值，遗漏VO₂ Max和体重实际测量日期；这是A-014展示合同内缺口 | 按high/high停止规则标记blocked，不建立Live Candidate、不发送邮件；等待用户决定是否授权单点修正和新Validator |
| 2026-08-22 / recent-health-text-date-closure | 用户授权后仅在daily text/plain健康卡片追加已有detail；新增单元与真实预览断言，r06的HTML/text均显示8-10/8-07，周报字节不变；463 tests及全部静态门PASS | 展示层无需改变快照、AI、训练建议或周报，只需保持HTML与纯文本同一事实 | 交一名全新high/high Code Validator；PASS才建立Live Candidate并单次发送修正版日报 |
| 2026-08-22 / recent-health-text-date-validator | 全新Validator确认463 tests、解析器、r06日期、周报、旧Live、预算及重放均闭合，但总体FAIL | `_plain_text`对所有metric统一追加detail，导致睡眠新增入睡/醒来说明；超出仅VO₂ Max/体重日期的授权，且测试未冻结其他纯文本不变 | 按high/high停止规则标记blocked，不建立Live Candidate、不发送邮件；等待用户决定是否授权限定键集合并新增负向回归 |
| 2026-08-22 / recent-health-text-date-scope-closure | 用户确认后将detail严格限定为vo2_max/weight；r05c→r07 `report.txt`仅两行增加8-10/8-07日期，睡眠/RHR/HRV和周报不变；104项定向与最终463项完整套件PASS | 旧M9 log-budget进程终止时序用例在首轮完整门及5次重复中的第5次偶发失败，未跳过/弱化；格式化后完整重跑PASS | 如实携带偶发门证据交全新high/high Validator；由其独立决定PASS/FAIL，PASS前不发送 |
| 2026-08-22 / recent-health-text-date-final-pass | 全新high/high Validator完成131项定向、463项全量和全部静态/隐私/产物门，确认r05c→r07日报纯文本仅两行变化、周报字节与旧Live证据不变并返回PASS | 旧M9时序探针10次中第10次复现fail-closed，但实现/测试未被M11修改，规范全套通过，按冻结范围列为剩余风险不阻断 | 建立新的Live Candidate，单次发送修正版日报；RAW闭合后等待用户网页/手机确认 |
| 2026-08-22 / recent-health-corrected-daily-live | 新owner-only Live Candidate在0 Provider下建立并验证；修正版日报单次`messages.send`成功，4次Gmail API完成Gmail ID、实际Message-ID、RAW、HTML、text与CID闭合；周报仍prepared/0调用 | 远端内容与r07冻结产物一致，未进入unknown或重复命中 | 停止并等待用户在Gmail网页端和手机端确认；确认前不发送周报 |
| 2026-08-22 / correction-weekly-live | 用户确认修正版日报网页/手机可读；0 Provider写入人工确认后，原冻结周报单次`messages.send`成功，另4次Gmail API完成Gmail ID、实际Message-ID、RAW、HTML、text与3张CID闭合；本批次send2/API8，历史合计send3 | 日报与周报动作均succeeded，无unknown/in_progress；周报仍需用户双端确认 | 停止并等待用户确认周报；确认后执行零调用重放、final verify和最终Validator |
| 2026-08-21 / validator-attempt-5 | Visual与Data/Privacy PASS；Code FAIL定位明确send错误被误归unknown、恢复忽略send-response Gmail ID、本地intent/message有限I/O断点 | 安全恢复必须以持久Gmail ID为首选；本地MIME必须先闭合，send-started后禁止再次send | 重排单写者状态机，新增改写Message-ID、明确send错误、孤立intent、MIME写失败和started只读恢复回归；15项定向/406项完整测试通过后交全新attempt6三类Validator |
| 2026-08-21 / validator-attempt-6 | Code、Visual、Data/Privacy全部PASS；406 tests、完整静态门、16次实际渲染、r03 SQLite/权限/lineage和正式state指纹闭合 | 无当前实现阻断；真实邮件客户端兼容只可由后续canary验证 | M11保持active但状态设为validating/ready-for-canary；不归档、不提交、不发送，等待新授权 |
| 2026-08-22 / coach-utility-v2-freeze | 用户确认日报/周报技术内容齐全但无法指导训练，批准无心率区间的v2返工、七日报一周报离线预览及独立验收 | v1投递/样式证据永久保留；内容验收失败不能归档M11；Provider调用0 | 写入A-015与冻结章程，先交全新Design Validator，再测试先行实现 |
| 2026-08-22 / coach-utility-v2-design-pass | 首次Design Validator定位五项歧义；规则以禁止raw、日期差≥3、零SOS证据、v2路由和42天Host参考配速收敛；全新Final Design Validator PASS | 正式state 9345项指纹不变、Provider 0 | 进入M11-0008，先写v2合同测试再实现 |
| 2026-08-22 / coach-utility-v2-code-gates | 测试先行新增v2 evidence/digest/AI/plan/ViewModel/render和AI rubrics；484 tests、Ruff、format、mypy、AST/Schema及diff门通过 | 首轮完整测试有2项旧M9时序fail-closed抖动，单项复跑与完整第二轮均通过；未修改旧runner | 交全新Code Validator，只按A-015冻结范围验收 |
| 2026-08-22 / coach-utility-v2-code-rework | Code Validator FAIL定位五项范围内缺口；汇总修正Zone/BPM别名、结构化SOS证据、daily downgrade证据、外部Schema引用与渲染白名单、纯文本细节，并恢复v1 rubric | 未删除/跳过/弱化测试；新增9项反例，完整492 tests和静态门通过 | 交全新Final Code Validator；FAIL/INCONCLUSIVE即停止，不进入私人Candidate |
| 2026-08-22 / coach-utility-v2-final-code-fail | 全新Final Code Validator确认492 tests及全部静态门PASS，但独立探针仍可从weekly health_summary输出Zone 2/150 BPM，并从daily自由文本输出output_id/content_json/skill_run_id等工程字段 | 课程、SOS、纯文本细节、v1隔离均闭合；两项仍属A-015范围内真实缺口 | 按停止规则blocked；不读取私人Candidate、不调用Codex/Provider，等待用户窄授权 |
| 2026-08-22 / reader-safety-user-authorization | 用户明确批准仅修复两项最终缺口并继续 | 训练设计、日期、数据、SOS、v1和Provider边界不变 | 测试先行建立共享读者文字安全门，再交全新Validator |
| 2026-08-22 / reader-safety-code-gates | 新共享安全门同时保护日报/周报构建和最终HTML/text，覆盖Zone/BPM/最大心率与7类内部标识符；新增11项反例 | 503 tests、Ruff、format、mypy、AST/Schema和diff门全绿 | 交用户授权后的全新Final Code Validator |
| 2026-08-22 / reader-safety-composite-rework | Final Validator确认普通标识符均闭合但下划线组合字段可绕过 | source_output_id/supersedes_raw_file_id/delivery_skill_run_id均属冻结工程字段范围 | 改为字母数字边界，补3项反例并再次完整验证 |
| 2026-08-22 / reader-safety-chinese-boundary-rework | Composite Validator确认组合内部标识符已闭合；独立探针发现中文紧邻Z2、独立BPM及HRmax可绕过 | Unicode单词边界把中文与ASCII视为连续单词；仍属冻结的无心率处方合同 | 改用ASCII字母数字边界并补3项中文连接反例，再跑完整门与全新Validator |
| 2026-08-22 / reader-safety-standalone-zone-rework | Chinese Boundary Validator确认中文紧邻Z2、BPM、HRmax及组合字段闭合；独立Zone仍可见 | 无数字Zone和中文心率分区同样表达被禁止的心率区间处方 | Zone可不带数字命中，并补心率分区反例；完整重跑后交全新Validator |
| 2026-08-22 / reader-safety-chinese-range-rework | Standalone Zone Validator确认全部已列形式闭合，仅“心率上下限”合并写法遗漏 | 上下限、范围、区带均是同一禁止的处方范围表达 | 一次补齐中文范围同义词与回归，完整重跑后交全新Validator |
| 2026-08-22 / reader-safety-symmetric-terms-rework | Chinese Range Validator确认“心率最大/心率阈值”因前后置词表不对称遗漏 | 重复维护两份同义词表会继续产生顺序缺口 | 改为单一共享词表双向匹配，补倒装反例并完整重跑 |
| 2026-08-22 / final-render-safety-rework | Symmetric Term Validator确认输入词法门闭合；模板免责声明自身包含被禁用术语 | 只校验ViewModel不足以覆盖模板常量，最终HTML/text也必须通过同一安全门 | 改写为RPE/体感与Garmin职责说明，并在_payload发布前复验最终可见产物 |
| 2026-08-22 / reader-safety-separator-threshold-rework | Final Render Validator确认模板二次门有效；连字符、BPM前后数字、HR缩写及乳酸阈值仍遗漏 | A-015禁止具体处方语义，不能依赖单一空格拼写 | 统一接受空格/连字符/下划线分隔及双向缩写，增加乳酸阈值门与反例 |
| 2026-08-22 / coach-utility-v2-code-final-pass | 全新Separator and Threshold Validator运行521项全量与全部静态门，174种心率变体、21种工程标识符探针零遗漏并返回PASS | M11-0008/0009代码合同已闭合，剩余风险仅为尚未运行私人Candidate与AI语义验收 | 进入M11-0010，建立全新owner-only Candidate并生成七日报一周报 |
| 2026-08-22 / coach-utility-v2-private-candidate | r01在冻结的9次Codex上限内生成7份日报、1份周报和两份训练计划；保留2次bootstrap失败、1次超时及持久化失败/恢复证据，成功输出未冒充固定脚本；8份预览、Schema、reader safety、lineage、SQLite integrity/FK、权限、桌面/375px和重放均PASS | 失败来自首轮模型字段偏差、一次180秒超时及Candidate持久化合同适配，均在不改变A-015、日期、数据或正确预期的情况下闭合；Provider/external actions保持0，正式state指纹不变 | 交AI、Visual/Coach Utility和Data/Privacy三名全新只读Validator；全部PASS后进入两封真实Gmail发送 |
| 2026-08-22 / coach-utility-v2-private-validator-fail | r01三类全新Validator均FAIL；同时确认训练计划安全门、SOS、响应式、SQLite血缘、权限、零Provider/external和正式state边界均通过 | 测试基准被称为历史原课、有效课缺recovery、日报未单列昨日非睡眠健康、周报把调整建议冒充实际执行；Data审计使用普通SQLite连接创建SHM | r01永久保留失败证据；增加确定性身份/四阶段/健康分栏/建议执行隔离门，以immutable SQLite建立全新r02并完整重跑 |
| 2026-08-22 / coach-utility-v2-r02-code-closure | 首轮r02 Code Validator定位3项fail-open；汇总修正后527 tests与全门PASS，Final Code Validator返回PASS | 缺失身份/健康字段不得用默认值掩盖，建议和实际执行必须由确定性门区分 | 建立r02；模型有效课仍缺recovery时保留失败结果并修正冻结提示合同 |
| 2026-08-22 / coach-utility-v2-r02-prompt-closure | Phase Prompt Validator先FAIL，明确补齐keep/downgrade/rest/blocked四种决策的四阶段要求后，全新Final Validator PASS | Schema已有四阶段不足以保证模型始终生成，提示和Host安全门必须同一合同 | 使用相同日期和证据重新生成失败日报对，未改变正确预期 |
| 2026-08-22 / coach-utility-v2-r02-reader-safety-closure | r02真实摘要出现静息心率观测值；Observed BPM Validator定位课程注入和处方同义绕过；构建层与最终渲染层双重隔离后，530 tests及全门通过，全新Course Render Final Validator PASS | 历史观测事实可以在健康上下文显示，但课程、建议和最终渲染中不得出现任何心率目标或BPM | 冻结源码和r02结果，进入三类私人独立终验 |
| 2026-08-22 / coach-utility-v2-r02-offline-ready | r02在7次Codex调用内完成7日报、1周报和8份预览；26项输出84–109通过Schema/SHA/lineage，SQLite integrity/FK、manifest/权限、重放、Provider/external=0和正式state指纹闭合；根Agent实际浏览器检查1280/375px共16次页面 | 首次日报对的安全门失败永久保留；审计脚本最初使用错误表名和错误SHA口径，修正审计脚本后Candidate本身无需改动且通过 | 派发AI、Visual/Coach Utility、Data/Privacy三名全新只读Validator；全部PASS后才进入真实Gmail日报canary |
| 2026-08-22 / coach-utility-v2-r02-final-validation | Visual与Data/Privacy返回PASS；AI仅因8月18日昨夜/周均HRV绑定错误返回FAIL，其余七日报、周报、SOS省略理由、课程、安全和建议/执行隔离均通过 | 私有Harness用任意`hrv`包含匹配，周均74覆盖昨夜76；错误属于确定性Host映射而非模型、样式或Gmail | r02永久保留语义FAIL；下沉为产品级精确映射和回归后建立全新r03 |
| 2026-08-22 / coach-utility-v2-r03-hrv-validator | 首轮HRV Code Validator确认535 tests和真实5040种字段顺序均通过，但返回FAIL；伪造任意前缀仍可命中昨夜HRV后缀 | 合同只批准基础名及review_/review_date_前缀，通用后缀匹配仍过宽 | 改成6项显式allowlist，增加2项非法前缀拒绝；540 tests与全部静态门PASS后交全新Final Validator |
| 2026-08-22 / coach-utility-v2-r03-hrv-final-pass | 全新Final Code Validator对6项allowlist、非法前缀、5040种字段顺序和睡眠/RHR/体重/load回归返回PASS；540 tests与全部门通过 | 确定性Host映射已闭合，不再依赖任意`hrv`包含或后缀猜测 | 从原M10父Candidate建立全新owner-only r03，重新生成7日报、1周报和8预览 |
| 2026-08-22 / coach-utility-v2-r03-weekly-evidence-rework | r03 6次AI调用已生成基准计划和7日报；8月18日HRV=76绑定正确。首次周报被Host拒绝并永久保留，因为insights误引43/47等嵌套legacy ID而非85–91 | 提示写“daily output IDs”但同一上下文同时暴露digest.daily_refs，存在可消除的歧义；安全门正确阻止入库 | 提示明确只允许顶层daily_input_refs并禁止digest/nested legacy/raw；541 tests与全门通过后交全新Validator，再在9次预算内重试一次 |
| 2026-08-22 / coach-utility-v2-r03-weekly-ref-validator | Weekly Evidence Prompt Validator确认提示歧义已消除，但发现bool ID、非hex SHA和非mapping输入未稳定拒绝并返回FAIL | 属同一顶层v2日报引用绑定范围；不改变日期、数据、训练规则或正确预期 | 新增统一严格validator与5类反例，Candidate Harness复用同一门；546 tests、Ruff、format、mypy、AST、58 Schema、metadata/Markdown、隐私/布局/diff全PASS，交全新Final Validator |
| 2026-08-22 / coach-utility-v2-r03-weekly-ref-final-pass | 全新Final Validator以22类恶意ref探针、546 tests和全部门返回PASS；预算内第7次模型调用成功生成周报92与计划93 | 周洞察仅引用顶层85–91，首次legacy引用失败证据永久保留 | 进入确定性渲染；不重跑日报、不追加模型调用 |
| 2026-08-22 / coach-utility-v2-r03-observed-hr-range | 周报渲染拒绝历史事实“静息心率47至50 bpm”；测试先行确认安全门只接受单值，不接受明确历史范围 | 这是A-015允许历史观测事实的误拦截，不是课程含心率处方；目标/控制范围仍必须拒绝 | 扩展明确观测范围识别及本周上下文，增加正负回归；547 tests和全部门PASS后交全新Validator，PASS前不继续写Candidate |
| 2026-08-22 / coach-utility-v2-r03-health-context-rework | Observed HR Range Validator返回FAIL：远距离“必须达到的目标”可绕过短邻接窗口，且历史BPM例外可进入非健康字段 | 两项同源于无字段上下文的通用例外，仍属A-015允许历史事实但禁止处方的冻结范围 | 默认读者字段严格零BPM，仅daily/weekly健康摘要调用专用例外；按整句拒绝目标/必须/控制，最终HTML/text精确移除唯一健康片段后再复验其余内容；549 tests与全部门PASS |
| 2026-08-22 / coach-utility-v2-r03-hr-sentence-rework | Final Health-context HR Validator确认字段隔离闭合，但独立“达到/应达到”仍可绕过，合法en dash范围被误拒 | 属同一整句处方词与历史范围格式的两个词法边界，不改变健康/训练业务含义 | 整句任意“达到”均拒绝，历史范围接受至/-/~ /～/–/—六种分隔；42项定向、550项全量与全部静态门PASS，交全新Final Validator |
| 2026-08-22 / coach-utility-v2-r03-observed-fragment-rework | Final HR Sentence Validator确认达到词、字段隔离和六种范围闭合，但“活动最大心率”被通用最大心率门先行误拒 | 健康观测正则本已批准该标签，问题是检查顺序而非业务范围 | 先遮盖完整且无处方语义的历史观测片段，再扫描剩余文字；3类标签×6分隔符正例及非health负例通过，550 tests与全部门PASS |
| 2026-08-22 / coach-utility-v2-r03-a015-boundary-closure | Final Observed-fragment Validator发现裸“保持”可绕过，另要求同句历史词、观测唯一性并拒绝平均心率 | “保持”是A-015内真实处方缺口；其余三项越界：health字段本身提供上下文，A-015明确允许活动平均/最高心率，且未要求健康摘要只含一个观测 | 整句加入裸“保持”；保留health-only字段门、平均/最高历史事实及多观测；非health仍严格拒绝。43项定向、551项全量与全部静态门PASS |
| 2026-08-22 / coach-utility-v2-r03-semicolon-closure | Final A-015 Observed-fact Validator仅因分号后“必须达到”与前面BPM脱钩返回FAIL；其余A-015字段、观测和最终渲染门通过 | 分号属于同一句内部停顿，不能结束处方关联；句号/问号/感叹号/换行仍为句界 | 中英文分号从句界集合移除并补回归；43项定向、551项全量与全部静态门PASS |
| 2026-08-22 / coach-utility-v2-r03-narrative-course-boundary | Semicolon Validator PASS后，真实r03只读渲染发现日报85/86的decision_reasons含合法昨日RHR事实，被人为限定health-only的门误拒 | A-015允许RHR/HRV/活动平均最高心率作为历史事实，并未限定卡片；真正边界是非课程叙事可展示完整观测，课程/心率目标仍严格禁止 | 新增narrative与course双API；HTML先抽取分块可见文字避免跨卡片串句；r03只读探针8/8渲染成功。旧M9时序首轮fail-closed，单项5次和完整第二轮551 PASS；全部静态门PASS |
| 2026-08-22 / coach-utility-v2-r03-render-persist | Final Narrative/Course Validator返回PASS后，Candidate私有Harness持久化路径仍重复调用旧的全局零心率门，导致只读预检成功但正式渲染被阻断 | 私有Harness未同步产品层已批准的A-015叙事/课程分层；产品代码、AI结果与业务合同无漂移 | 将Candidate最终产物门切换为同一narrative gate，课程仍由渲染器严格零心率校验；8/8落库成功，重放数据库和32项文件字节不变，桌面1280与手机375均无溢出/断图 |
| 2026-08-22 / coach-utility-v2-r03-final-and-live-daily | r03 AI、Visual、Data/Privacy三类全新只读Validator全部PASS；建立全新owner-only Live Candidate并发送日报canary一次 | Gmail返回唯一远端ID，生产MIME规范化RAW校验通过；直接字符串比较受CRLF规范化影响而为false，不属于内容漂移 | 保持周报prepared/attempt0；等待用户网页端和手机端确认后继续，禁止确认前发送 |
| 2026-08-23 / opendesign-v3-offline-ready | A-016与五项v3 Schema落地；共享table/inline-CSS/CID引擎生成7日报、1周报和8份MIME；672/375px逐组件检查无溢出、图表完整；576 tests及全部静态门通过 | r01的AI/课表84–93原字节不变，SQLite integrity/FK、9370 raw、权限、重放、Provider/external=0和正式9347项指纹闭合 | 按Code、Design-Fidelity、Data/Privacy严格串行派发三名全新只读Validator；全部PASS后仅交付离线预览 |
| 2026-08-23 / opendesign-v3-code-validator-rework | 首名Code Validator确认解析、Schema、冻结输出、周报七日报lineage、MIME、raw及零外部动作全部闭合，但返回FAIL | 5种合法课程类型缺少中文映射，r01的可见HTML泄漏`recovery_run`等内部枚举；现有测试只覆盖2种课程 | r01永久失效；以Schema全部9种枚举建立测试，删除3个旧键并补齐中文映射；577 tests与全门通过后建立r02，重放、SQLite/raw/权限和正式state重新闭合，交全新Final Code Validator |
| 2026-08-23 / opendesign-v3-session-uniqueness-rework | Final Code Validator确认课程中文映射及r02其余全部门闭合，但返回FAIL | `reference_index!=0`的session分区在唯一性计数前被忽略，index0+1重复时错误显示index0，违反A-016重复session隐藏 | r02永久失效；全部session候选先计数，唯一候选再要求受支持index0；新增跨index重复与单独异常index回归。578 tests与全门通过后建立r03，重放、SQLite/raw/权限和正式state重新闭合，交全新Final Code Validator |
| 2026-08-23 / opendesign-v3-fit-type-rework | r03 Final Code Validator确认跨index重复已fail-closed，但返回FAIL | 唯一候选的缺失/None/浮点index以及字符串时长/边界会被宽松数值转换接纳，违反A-016格式异常隐藏 | r03永久失效；index严格为非bool整数0，分区向量严格为非bool有限原生数值；新增7类异常类型回归。585 tests与全门通过后建立r04，重放、SQLite/raw/权限和正式state重新闭合，交全新Final Code Validator |
| 2026-08-23 / opendesign-v3-code-final-pass | 全新Final Code Validator对r04当前最终字节运行585项全量、34项定向和32组额外恶意FIT探针并返回PASS；冻结84–93、SQLite/raw/MIME/权限/重放和零Provider全部闭合 | A-016已严格限定为唯一、类型合法的Garmin/FIT session分区时长；采样心率变化不会生成分区，课程仍无分区或BPM处方 | 保持源码和r04冻结，严格串行进入全新Design-Fidelity Validator |
| 2026-08-23 / opendesign-v3-design-fidelity-rework | 全新Design-Fidelity Validator实际检查7日报、1周报的672×1000与375×812渲染并返回FAIL；顺序、响应式、图表/CID、缺活动和隐私均通过 | 共享渲染仍偏离白色圆角品牌外壳和规范色；状态只有色块无图形；睡眠卡泄漏UTC ISO；周报图表降级单位为英文 | r04永久保留视觉FAIL；一次性修正四项展示合同、测试先行、建立全新Candidate后交全新Design-Fidelity Validator |
| 2026-08-23 / opendesign-v3-r05-visual-closure | 新增白色圆角品牌壳、准确设计色、确定性品牌/三状态PNG CID、香港睡眠时钟和中文图表时间单位；首个r05因Gmail MIME仍限定1248px图表而安全失败，保留后同步角色/尺寸白名单 | 渲染资产Schema和MIME规范必须共享品牌/状态与图表的精确尺寸合同，不能只更新显示层 | 全新r05成功生成8预览/8MIME；实际浏览器672/375无溢出、断图或英文时间单位。592 tests与全门通过后交全新Code Validator |
| 2026-08-23 / opendesign-v3-r06-strict-index-closure | r05 Code Validator确认视觉、MIME、Candidate及其余代码门闭合，但发现展示转换层将`False`/`0.0`宽松等同session index 0 | 原始FIT解析层已严格，但第二层展示转换仍须独立fail-closed，不能依赖Python数值相等语义 | 回归先红后绿，严格限定原生整数0；594 tests与全门通过，全新r06含8预览/8MIME、9473文件、重放零增量、正式state指纹一致，交全新Final Code Validator |
| 2026-08-23 / opendesign-v3-r06-code-pass | 全新Final Code Validator运行594项全量、两层FIT恶意输入、冻结84–93、七日报引用、8 MIME、9473文件和正式state审计并返回PASS | Code范围无未满足项；真实Gmail与部署按冻结范围排除 | 保持r06与源码冻结，严格串行进入全新Design-Fidelity Validator |
| 2026-08-23 / opendesign-v3-r06-design-pass | 全新Design-Fidelity Validator实际渲染7日报、1周报的672×1000与375×812并逐组件对照OpenDesign，返回PASS | 白色品牌壳、TL标志、状态图形、HKT时间、中文单位、真实图表、无数据分支和移动重排均闭合 | 严格串行进入最后一名全新Data/Privacy Validator |
| 2026-08-23 / opendesign-v3-r06-complete | 全新Data/Privacy Validator确认9473文件、9370 raw/122730679字节、SQLite/86 triggers、84–93冻结、7份展示证据、37张PNG、8 MIME、权限与正式9347项指纹全部闭合并返回PASS | 5项活动分区来自设备session时长；4种设备分区定义不一致，因此周报正确不聚合分区；Provider/external=0 | 三类最终Validator全部PASS；归档M11，仅交付离线预览，真实重发与部署另行授权 |
