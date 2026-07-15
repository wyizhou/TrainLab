---
proposal_for_design_rev: 1
design_version: "1.0"
impact: mixed            # structural + scope（见分级判定）
planner_ack: true
validator_ack: true
validator_ack_at: 2026-07-10
created_at: 2026-07-10
source:
  update: "交接/update.md (design_rev 1)"
  detail: "交接/v1.0-设计文档.md"
  prototype: "运动分析系统.dc.html"
# 技术栈决策（用户 2026-07-10 确认，非设计侧数据）
stack:
  app: "React + TypeScript + Vite（纯前端，无后端；同步/下载/AI/API 全部前端模拟）"
  verify: "Vitest + Testing Library + ESLint/Prettier + Playwright E2E"
---

# 提案 — design_rev 1（TrainLab v1.0 首个定版）

> 本文件是 `pending/` 协商稿，**不是** contract。双方 `planner_ack` + `validator_ack` 后，
> 由 Planner 把下方条目落成到 `docs/contract/contract.md`，再拆需求到 `active/`、更新 `backlog.md`、
> 追加 `changelog.md`，最后删除 `docs/executor/.blocked`。

## 0. 分级判定

- `design_rev` 0 → 1，首次定版。
- 变更清单 14 行含 `structural`（#1、#4、#5、#6、#8、#9、#10、#13、#14）与 `scope`（#2、#3、#7、#11、#12）。
- 混合档 → 走 **contract 协商 + 失效检查** 全流程。`.blocked` 已于 `blocked_at=2026-07-10T04:30:39Z` 创建。

## 1. 失效检查结果

- 遍历 `docs/executor/active/`：**空**（仅 `.gitkeep`）。无 `source_design_rev < 1` 的在飞行需求。
- 结论：**无返工 / 无废弃 / 无告警**。本 rev 全部为 **新增（新建需求）**。

## 2. 全局验证基线（G-*，每条 contract 条目默认继承，不逐条重复）

命令以最终 `package.json` scripts 为准；提案先固定语义，Executor 落地脚本、Validator 据此验收。

- **G-lint**：`npm run lint`（ESLint + Prettier check）0 error、0 warning。
- **G-type**：`npm run typecheck`（`tsc --noEmit`）0 error。
- **G-unit**：`npm run test`（Vitest run）全绿；本条目新增/触及的组件须有对应 `*.test.tsx`（Testing Library）。
- **G-e2e**：`npm run e2e`（Playwright）本条目指定 spec 通过（仅对标注了 e2e 的条目要求）。
- **G-token**：颜色/圆角/间距只引用设计 token（视觉 tokens 见设计文档 §视觉 tokens），不出现脱离 token 的裸值。
- **G-nums**：所有数值展示走 `font-variant-numeric: tabular-nums`；数值列用 ui-monospace。
- **G-resp**：平板断点 `<980px` 行为符合各条目「平板」条款。
- **G-mock**：同步、下载、AI 回复、API 测试均为前端模拟，不发真实网络请求（设置页 AI 接口「测试连接」按钮的真实探测可选，默认亦可 mock）。

> **待 Validator 确认**：G-e2e 覆盖哪些流程为「必须」（提案默认：登录、连接器授权 2FA、双账号合并、运动详情双模式切换、分析对话生成图表卡片）。

## 3. 提案条目（清单行 ↔ contract 条目 ↔ 需求，1:1:1）

> 每条落成后编号为 `C-<n>`；「拟需求」为 ack 后写入 `active/` 的槽位。所有条目 `impact` 沿用变更清单，`决议 = 新增`。

### C-1 — 全局基础：脚手架 + 设计系统 + 顶部导航（清单 #1，structural）
- 拟需求：`001`　组件/token：TopNav、色板 tokens、路由 shell
- 可验证标准（+ G-lint/type/unit/token/nums/resp）：
  - [ ] Vite + React + TS 工程可 `npm run build` 成功产出静态包；`npm run dev` 起服务。
  - [ ] 顶部导航含五项且顺序为 **分析(默认页) / 运动记录 / 健康记录 / 连接器 / 设置**；`/` 默认路由指向分析页。
  - [ ] 深色视觉系统 token 以常量集中定义（背景 #0A0F18 / 面板 #121A28 / 深面板 #0B1220 / 强调 `oklch(0.65 0.15 230)` 等），全局 `tabular-nums` 生效。
  - [ ] 平板 `<980px`：导航缩小内边距/字号、隐藏「上次同步」胶囊、可横向滑动（隐藏滚动条）。
  - [ ] e2e：五个路由均可导航到位、默认落在分析页。

### C-2 — 登录页 LoginForm（清单 #2，scope）
- 拟需求：`002`　组件：LoginForm
- 可验证标准：
  - [ ] 居中卡片，字段 = 用户名 / 密码 / 4 位验证码（点击刷新）；回车提交；错误提示可见。
  - [ ] 演示校验规则：任意用户名 + 密码 ≥4 位 + 验证码正确 → 通过并进入分析页；任一不满足 → 报错、不跳转。
  - [ ] 无营销元素。
  - [ ] e2e：错误验证码被拒 → 正确输入后登录成功跳转分析页。

### C-3 — 分析·多会话 SessionRail（清单 #3，scope）
- 拟需求：`003`　组件：SessionRail
- 可验证标准：
  - [ ] 桌面左侧 212px 会话栏：新建会话主按钮、会话项（名称 + 消息数、选中态左侧强调色条）。
  - [ ] 行内重命名（Enter 确认 / Esc 取消）；删除当前会话切到第一个；删空自动新建。
  - [ ] 平板 `<980px`：降级为顶部下拉选择 + 新建按钮。
  - [ ] e2e：新建 → 重命名 → 删除至空自动新建 的完整链路。

### C-4 — 分析·数据范围选择器 ScopeBar（清单 #4，structural）
- 拟需求：`004`　组件：ScopeBar
- 可验证标准：
  - [ ] 3(默认)/7/15/30 天胶囊；「选择运动 (n)」展开勾选列表，勾选后覆盖时间范围。
  - [ ] 「附带健康记录」「附带习惯记录」两开关，**默认均开**。
  - [ ] 底部实时显示当前范围摘要（随选择更新）。

### C-5 — 分析·图表卡片四态 ChartCard（清单 #5，structural）
- 拟需求：`005`　组件：ChartCard
- 可验证标准：
  - [ ] 四态齐全且可判定：**加载**（spinner + shimmer，回复文本先到、约 1.1s 后卡片就绪）/ **空态**（范围内 <2 次运动，图标 + 文案，不可展开）/ **折叠**（📊 + 标题 + 一行等宽摘要 + 展开）/ **展开**（轴说明行 + 340×112 折线图，Y 轴 3 档、X 轴首/中/末刻度 + 逐条数据行）。
  - [ ] 视觉层级：用户消息（实心蓝右对齐）> AI 气泡（面板色左对齐，最小宽 46%）> 卡片（气泡内下沉层 #0B1220）。
  - [ ] 平板 `<980px`：展开态隐藏数据明细行，仅保留带轴标签图表。
  - [ ] unit：给定 <2 次运动数据 → 渲染空态；≥2 次 → 可进入折叠/展开。

### C-6 — 分析·AI 回复 HTML + 隐藏系统提示词（清单 #6，structural）
- 拟需求：`006`　组件：ChatMessage、SysPrompt
- 可验证标准：
  - [ ] AI 回复以 HTML 渲染（表格 / 有序列表）；含「计划」提问输出 7 天课表表格；附带健康/习惯时追加解读段落。
  - [ ] 隐藏系统提示词随每次请求发送、不显示在对话流；设置 → AI 接口可查看/收起。
  - [ ] HTML 渲染做转义/白名单，禁止注入脚本执行（安全基线）。
  - [ ] unit：mock 一次分析请求 → 输出含数据表格与结论；系统提示词不出现在消息流 DOM。

### C-7 — 运动记录·列表 ActivityTable + Pager（清单 #7，scope）
- 拟需求：`007`　组件：ActivityTable、Pager
- 可验证标准：
  - [ ] 列：复选框/日期/类型色点/名称/距离/时长/平均心率/配速或功率/来源(佳明CN·佳明国际·FIT上传)/单条 FIT 下载。
  - [ ] 类型筛选胶囊（全部/跑步/骑行/游泳/力量/越野跑）实时过滤；分页 20(默认)/50/100。
  - [ ] 批量「下载选中 FIT (n)」计数随勾选更新（下载为前端模拟）。
  - [ ] e2e：筛选 + 翻页 + 批量勾选计数。

### C-8 — 运动记录·详情 ActivityDetail + 时序双模式（清单 #8，structural）
- 拟需求：`008`　组件：ActivityDetail、TimeSeriesChart、RecordTable
- 可验证标准：
  - [ ] 字段集 = 真实 FIT（`uploads/614797758_ACTIVITY.fit`，`@garmin/fitsdk` 解析）∩ 佳明 Connect 详情页；列表第一条「晨间轻松跑」为该真实数据；缺失字段显示「--」。
  - [ ] 指标分区各标注 FIT 字段名；训练效果为 FIT 原始存储值（非系统计算）。
  - [ ] 时序双模式：降采样曲线（跑步 8 图/骑行 6/游泳 2/力量 1，Y 轴 3 档 + X 轴 5 档 + 来源字段标注）⇄ 逐秒数据表（分页 20/50/100，行数 = 运动秒数）。
  - [ ] 心率区间条形图（`time_in_hr_zone`）边界取自设置页区间设定（C-14 未落成前用默认边界，落成后接入）。
  - [ ] Laps 分段表含平均功率列；「下载 FIT 文件」主按钮（模拟）。
  - [ ] unit：解析真实 FIT → 首条详情关键字段与佳明详情一致（选取若干字段断言）。
  - [ ] e2e：曲线 ⇄ 逐秒表 模式切换。

### C-9 — 健康记录 HealthTabs + HabitPicker（清单 #9，structural）
- 拟需求：`009`　组件：HealthTabs、HabitPicker
- 可验证标准：
  - [ ] 五子标签：睡眠（深/浅/REM 堆叠柱 + 明细含静息心率）/ 体重（曲线 + 体重/体脂/肌肉/水分）/ 静息心率 / HRV / 习惯。
  - [ ] 习惯：日期选择（默认当天）+ 已记录计数；早/中/晚/全天四组因子胶囊勾选，按日期存储。
  - [ ] 表格统一分页 20/50/100；数据量级覆盖设计所述窗口（体重/RHR/HRV 30 天、睡眠 14 天、习惯量级）。

### C-10 — 连接器·卡片状态集合 ConnectorCard（清单 #10，structural）
- 拟需求：`010`　组件：ConnectorCard
- 可验证标准：
  - [ ] 状态集合齐全：已连接（绿）/ 未连接（灰 + 连接账号）/ 同步中（按钮 spinner）/ 同步失败（红 + 错误块：失败时间 + 原因，按钮变「重试同步」）。
  - [ ] 显示上次成功同步时间、已同步数量、自动同步间隔（30 分钟/1 小时/6 小时/仅手动）。
  - [ ] 演示初始态：中国区 = 同步失败(ETIMEDOUT)，国际区 = 未连接。
  - [ ] unit：四种状态各渲染出对应胶囊与按钮文案。

### C-11 — 连接器·授权登录弹窗 ConnectorAuthModal（清单 #11，scope）
- 拟需求：`011`　组件：ConnectorAuthModal
- 可验证标准：
  - [ ] 字段：账号 / 密码 / 「启用了 2FA」勾选。未勾选：一次登录接入。
  - [ ] 勾选 2FA：第一次登录校验账密 → 出现 6 位验证码输入区（勾选锁定）→ 再次登录后台（模拟）验证；校验与 busy 态齐全。
  - [ ] e2e：2FA 两段式流程直到接入成功。

### C-12 — 连接器·双账号合并 ConflictBanner + ConflictModal（清单 #12，scope）
- 拟需求：`012`　组件：ConflictBanner、ConflictModal
- 可验证标准：
  - [ ] 去重规则：按「开始时间 + 时长」自动去重，来源标注保留。
  - [ ] 无法自动判定 → 页顶警示横幅「发现 n 组疑似重复运动」+「处理重复」→ 弹窗逐组选「保留中国区 / 保留国际区」→ 确认合并。
  - [ ] 演示：连接国际区后出现 2 组冲突。
  - [ ] e2e：触发冲突 → 逐组选择 → 合并后横幅消失。

### C-13 — 连接器·文件上传 FileUpload（清单 #13，structural）
- 拟需求：`013`　组件：FileUpload
- 可验证标准：
  - [ ] 本页内上传区：FIT/TCX/GPX 多选、单文件 ≤50MB（超限拒绝并提示）。
  - [ ] 「已解析文件」列表（名称/大小/时间/已入库）；入库后出现在运动记录，来源标「FIT上传」。
  - [ ] unit：>50MB 或非法扩展名被拒；合法文件进入已解析列表。

### C-14 — 设置 SettingsSections（清单 #14，structural）
- 拟需求：`014`　组件：SettingsSections
- 可验证标准：
  - [ ] 五分组齐全：账户信息（新密码×2 一致性校验）/ 单位制（距离海拔·配速·体重）/ 区间设定（MaxHR/LTHR/FTP + Z1–Z4 上界）/ 数据保留策略（占用统计 + 保留期限 + 到期自动清理开关）/ AI 接口（base_url 默认 `https://api.deepseek.com` / API Key / 模型名 / 测试连接 / 隐藏系统提示词查看）。
  - [ ] 区间设定仅作原始数据标注边界（供 C-8 心率区间图 + AI 对话附带），系统不用于计算。
  - [ ] unit：密码不一致报错；区间设定写入后被详情页读取（与 C-8 联调）。

## 4. 拟需求分解与执行顺序（ack 后写入 backlog）

字典序执行。此处未使用字母后缀（全为新增，无返工）。

| 序号 | contract | source_design_rev | 分支 | 摘要 | 依赖 |
|---|---|---|---|---|---|
| 001 | C-1 | 1 | feat/001-foundation | 脚手架 + 设计 token + 顶部导航 + 路由 shell + 工具链 | — |
| 002 | C-2 | 1 | feat/002-login | 登录页 | 001 |
| 003 | C-3 | 1 | feat/003-session-rail | 分析·会话栏 | 001 |
| 004 | C-4 | 1 | feat/004-scope-bar | 分析·范围选择器 | 001 |
| 005 | C-5 | 1 | feat/005-chart-card | 分析·图表卡片四态 | 004 |
| 006 | C-6 | 1 | feat/006-chat-html | 分析·AI 回复 HTML + 系统提示词 | 005 |
| 007 | C-7 | 1 | feat/007-activity-list | 运动记录列表 | 001 |
| 008 | C-8 | 1 | feat/008-activity-detail | 运动记录详情 + 时序双模式 | 007（心率区间边界待 014，先用默认） |
| 009 | C-9 | 1 | feat/009-health | 健康记录五标签 | 001 |
| 010 | C-10 | 1 | feat/010-connector-card | 连接器卡片状态 | 001 |
| 011 | C-11 | 1 | feat/011-connector-auth | 连接器授权弹窗 | 010 |
| 012 | C-12 | 1 | feat/012-conflict-merge | 双账号合并 | 010, 011 |
| 013 | C-13 | 1 | feat/013-file-upload | 文件上传入库 | 007, 010 |
| 014 | C-14 | 1 | feat/014-settings | 设置五分组 | 001（被 006/008 反向消费） |

**跨条目依赖备注**（供 backlog 保留）：
- C-8 心率区间图 与 C-6 系统提示词查看 反向消费 C-14 的区间设定 / AI 接口；因全前端可共享 settings store：先落默认值，C-14 落成后接入，不阻塞先行条目。

## 5. 待 Validator 协商的开放点

1. **G-e2e 必测流程集合** —— 提案默认：登录、连接器 2FA 授权、双账号合并、运动详情双模式、分析对话生成图表卡片。是否增删？
2. **G-token 判定方式** —— 是否接受「集中 token 常量文件 + lint 规则禁裸色值」作为客观判据，还是需视觉快照测试？
3. **FIT 真实解析断言粒度**（C-8）—— 需断言哪些关键字段与佳明详情一致才算通过？建议给出一份字段白名单。
4. **数据量级验收**（C-9）—— 用「明细表行数 ≥ 设计窗口天数」这类可数判据，还是仅检查渲染不报错？
5. **条目粒度** —— 是否接受 14 条 1:1:1（清单行↔contract↔需求）拆分；分析页是否需进一步细分或合并。

## 6. Ack

- `planner_ack: true`（本文件 frontmatter）——分级、失效检查、条目与拆分、验证基线由 Planner 提出。
- `validator_ack: true`（2026-07-10）——Validator 已就 §5 五个开放点逐条给出可验证判据，见 §7。协商一致。

---

## 7. Validator 协商回复（2026-07-10，validator_ack: true）

先行确认：同意 §1 失效检查结论（`active/` 空，全部 **新增**，无返工/废弃/告警）；同意 §2 全局基线 G-lint/type/unit/e2e/token/nums/resp/mock 语义。以下逐条闭合 §5 开放点，作为落成 contract 时各条目 `可验证标准` 的判据补充。

### 7.1 开放点#1 — G-e2e 必测流程集合（闭合）
- **接受**提案默认 5 条为**门禁必过**冒烟集，不增删：
  1. 登录：错误验证码被拒 → 正确输入登录成功跳分析页（C-2）。
  2. 连接器 2FA 两段式授权直到接入成功（C-11）。
  3. 双账号合并：触发冲突 → 逐组选择 → 合并后横幅消失（C-12）。
  4. 运动详情：降采样曲线 ⇄ 逐秒表 模式切换（C-8）。
  5. 分析对话生成图表卡片：发送分析提问 → AI 气泡文本先到 → 卡片由**加载→折叠**就绪 → 展开显示折线图（C-5＋C-6 联合流）。
- **判定**：各条目 frontmatter/正文已写的 `[ ] e2e` 行同时成立，是该条目验收的一部分（C-1 五路由导航、C-3 会话增改删至空、C-7 筛选+翻页+批量计数 亦须各自 e2e 通过）。
- **不做**：C-4/C-9/C-10/C-13/C-14 不要求 e2e（unit 覆盖即可），避免 e2e 面过宽导致脆弱。
- **测法**：`npm run e2e`（Playwright），上述 spec 全绿。设置页 AI「测试连接」真实探测仍可 mock。

### 7.2 开放点#2 — G-token 判定方式（闭合）
- **接受**「集中 token 常量文件 + lint 规则禁裸值」为客观判据，**不引入视觉快照测试**（mock 演示应用，快照过脆、维护成本高于收益）。
- **判定**：(a) 颜色/圆角/间距 token 集中定义于单一模块（如 `src/design/tokens.ts` 及/或 CSS 变量），(b) ESLint（JS/TS 内联样式）+ Stylelint（CSS/样式）规则对 token 文件之外出现的裸 `#hex` / `rgb()` / `oklch()` / 裸像素间距值报 **error**。
- **测法**：`npm run lint` 0 error 0 warning 即视为 G-token 通过；验收时抽查——在非 token 文件植入一处裸色值应使 lint 失败（Executor 自证或 Validator 抽验 `grep` token 文件外的裸值命中为 0）。

### 7.3 开放点#3 — FIT 真实解析断言粒度（C-8，闭合，含前置条件）
- **前置条件（硬）**：真实样本 `uploads/614797758_ACTIVITY.fit` **必须随 C-8 分支提交入库**。**该文件当前不在仓库中**——C-8 验收前若仍缺失，C-8 判定为 **blocked**（非通过、非返工），由 Executor 补齐样本后再验。此前置不阻塞其余条目先行。
- **字段白名单（断言首条「晨间轻松跑」`@garmin/fitsdk` 解析值 == 佳明 Connect 详情，至少下列 8 项）**：
  1. `sport`（+ `sub_sport` 若存在）
  2. `start_time`（开始时间，时间戳精确相等）
  3. `total_timer_time`（总时长）
  4. `total_distance`（总距离）
  5. `avg_heart_rate`（平均心率）
  6. `max_heart_rate`（最大心率）
  7. `total_calories`（卡路里）
  8. `avg_speed`（→ 配速换算后一致）
  - 额外：`total_ascent`（总爬升，若佳明详情展示则纳入）；训练效果 `total_training_effect` / `total_anaerobic_training_effect` 断言为 **FIT 原始存储值**（存在且等于存储值，非系统重算）。
- **容差**：整数/时间戳精确相等；浮点按详情页展示精度四舍五入后相等。缺失字段渲染「--」并允许不参与断言。
- **测法**：`npm run test` 中 C-8 的 `*.test.tsx`/解析单测对上述白名单逐项断言通过。

### 7.4 开放点#4 — 数据量级验收（C-9，闭合）
- **接受**可数判据，非「仅渲染不报错」。明细表行数须满足设计窗口：
  - 体重 / 静息心率 / HRV：各 **≥ 30 行**。
  - 睡眠：**≥ 14 行**。
  - 习惯：按日期存储，抽样某日 早/中/晚/全天 四组因子胶囊可勾选并计入「已记录计数」。
  - 各表分页控件含 20/50/100 三档。
- **测法**：`npm run test` 中对上述行数下界与分页档位断言；渲染无错。

### 7.5 开放点#5 — 条目粒度（闭合）
- **接受** 14 条 1:1:1（清单行 ↔ contract 条目 ↔ 需求）拆分，**分析页不再细分或合并**。序号 001–014、依赖关系与 §4 执行表一致。

### 7.6 ack 范围声明
- 本 ack 覆盖**可验证标准**本身。设计侧源文档（`交接/*`、`运动分析系统.dc.html` 原型）不在仓库内，属设计/Planner 输入，非 Validator 验收物，故不影响本 ack；**唯一被提升为验收前置的产物是 7.3 的真实 FIT 样本**。
- Ack 齐备（`planner_ack` + `validator_ack`）后，请 Planner 按强制路径落成 `contract.md`（各条目继承 G-* 并纳入 §7 判据）、拆 `active/001–014`、更新 `backlog.md`、追加 `changelog.md`，最后删除 `docs/executor/.blocked`。**落成的 C-8 条目须显式写入 7.3 的 FIT 前置与字段白名单。**

> Ack 齐备前：**不动** `contract.md` / `backlog.md` / `active/`；`.blocked` 保持存在。
