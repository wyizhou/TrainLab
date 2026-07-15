---
proposal_for_design_rev: 2
design_version: "2.0"
impact: mixed            # structural + scope（见 §0 分级判定）
planner_ack: true
validator_ack: true
created_at: 2026-07-11
source:
  update: "design/v2.0/交接/update.md (design_rev 2)"
  detail: "design/v2.0/交接/v2.0-设计文档.md"
  prototype: "运动分析系统.dc.html（v2.0；不在 repo，属设计侧输入）"
---

# 提案 — design_rev 2（TrainLab v2.0：全设备响应式 + 视觉保真返工 + 删除数据保留）

> 本文件是 `pending/` 协商稿，**不是** contract。双方 `planner_ack` + `validator_ack` 后，
> 由 Planner 把下方条目落成到 `docs/contract/contract.md`（返工原 C-1…C-14 条目），
> 按决议做文件操作（原 completed/ 文档留原地当历史、在 active/ 新建 001b…014b 返工需求），
> 更新 `backlog.md`、追加 `changelog.md`，最后删除 `docs/executor/.blocked`。

## 0. 分级判定

- `design_rev` 1 → 2。变更清单 14 行：
  - `structural` ×12：#1 BreakpointState、#3 TopNav/BottomTabBar、#4 Header/Main、#5 ChatMessage、#6 ChartCard/SessionRail、#7 ActivityTable/ActivityCardList、#8 LapsTable/RecordTable/TimeSeriesChart、#9 HealthTables/SleepChart、#10 ConnectorCard/FileUpload、#11 ConnectorAuthModal/ConflictModal、#12 SettingsSections。
  - `scope` ×1：#13 删除「数据保留策略」分组（五分组 → 四分组）。
  - `cosmetic` ×1：#2 全组件视觉保真返工（精确参数固化到 token 与组件参数表）——**吸收进各返工条目的 G-token / 保真判据**，不单列 changelog（因整 rev 已走 structural+scope 全流程）。
- 混合档（最高 scope）→ 走 **contract 协商 + 失效检查** 全流程。`.blocked` 已于 `created_at=2026-07-11T23:07:11+08:00` 创建。

## 1. 失效检查结果

遍历 `docs/executor/active/`（**空**）与 `docs/executor/completed/`（001–014，全部 `verified`，`source_design_rev: 1`）。
`source_design_rev 1 < 2` 且涉及组件命中变更清单的需求 → 分状态处理。全部命中项均为 `verified`，走**返工已 verified 流程**：不动 `completed/` 原文档（rev 1 历史事实），在 `active/` 新建返工需求（`<原号>b`，`supersedes` 原号，`source_design_rev: 2`，带更严可验证标准）。

| 原需求 | contract | 命中清单行 | 组件 | 决议 | 返工槽位 |
|---|---|---|---|---|---|
| 001 | C-1 | #1 #3 #4 | BreakpointState / TopNav / **BottomTabBar(新)** / Header / Main | 返工 | 001b |
| 002 | C-2 | #2 + G-resp 基线升级 | LoginForm | 返工（轻，见 §5-1） | 002b |
| 003 | C-3 | #6 | SessionRail | 返工 | 003b |
| 004 | C-4 | #2 + §3.4 mobile 换行 + G-resp 升级 | ScopeBar | 返工（轻，见 §5-1） | 004b |
| 005 | C-5 | #6 | ChartCard | 返工 | 005b |
| 006 | C-6 | #5 | ChatMessage | 返工 | 006b |
| 007 | C-7 | #7 | ActivityTable / **ActivityCardList(新)** | 返工 | 007b |
| 008 | C-8 | #8 | LapsTable / RecordTable / TimeSeriesChart | 返工 | 008b |
| 009 | C-9 | #9 | HealthTables / SleepChart | 返工 | 009b |
| 010 | C-10 | #10 | ConnectorCard | 返工 | 010b |
| 011 | C-11 | #11 | ConnectorAuthModal | 返工 | 011b |
| 012 | C-12 | #11 | ConflictModal | 返工 | 012b |
| 013 | C-13 | #10 | FileUpload | 返工 | 013b |
| 014 | C-14 | #12 #13(scope) | SettingsSections（-RetentionGroup） | 返工 | 014b |

- **无废弃、无新增独立 C 条目**：新组件 BottomTabBar / ActivityCardList 是既有 C-1 / C-7 的移动端形态，折进对应返工条目，不另开 C-15/C-16。
- **fixture 前置检查**：C-8 返工仍引用 `tests/fixtures/614797758_ACTIVITY.fit`（`fixture_owner: human`）——**已在 repo**（rev 1 已入库），无新增 human fixture。**无 fixture 死锁**，全部条目可照常落地。
- **告警段落**：`active/` 无 `in_progress` / `awaiting_validation` 需求，无需追加「设计变更告警」段落。

## 2. 全局验证基线变更（G-*）

沿用 rev 1 全部 G-*，**仅升级 G-resp**，并新增一条门禁冒烟（见 §4）：

- **G-resp（升级）**：断点矩阵由「平板 `<980px`」升级为四档 **mobile <640 / tablet 640–979 / desktop 980–1439 / wide ≥1440**（`window.innerWidth` 驱动，resize 生效）。新增硬不变量：**所有断点、全部 7 个可达路由（`/login`、`/`、`/activities`、`/activities/1`、`/health`、`/connectors`、`/settings`），`document.documentElement.scrollWidth <= window.innerWidth`（无横向溢出）**。（Validator R1：溢出不变量覆盖含 `/login` 在内的全部 7 路由；导航模式断言另行分离，见 §4 门禁#6。）
- G-lint / G-type / G-unit / G-e2e / G-token / G-nums / G-mock 语义不变。#2 视觉保真的精确 token/圆角/间距值经 G-token（token 文件外裸值 lint error）承接；结构性/重排参数（宽度、display、grid 列、圆角非对称）由各条目 e2e-browser 承接。

## 3. 返工条目（拟落成到 contract.md，返工原 C-1…C-14）

> 每条 `impact` 沿用清单、`决议: 返工`、`design_rev: 2`、`受影响需求: <原号>, <原号>b`。条目继承升级后 G-*，正文只写增量。
> 判据取自 `design/v2.0/交接/v2.0-设计文档.md` §2–§9，均为客观可断言粒度。视口取自 G-resp 基准：mobile 390×844 / tablet 768×1024 / desktop 1280×800 / wide 1920×1080。

### C-1 返工 — 全局响应式基线 + 双模导航（清单 #1 #3 #4，structural）
- 返工需求：`001b`（supersedes 001）　组件：BreakpointState、TopNav、BottomTabBar、Header、Main
- 可验证标准（+ G-*）：
  - [ ] BreakpointState：`innerWidth` 落 mobile/tablet/desktop/wide 四区间，resize 切换即时生效（unit）。
  - id: AC-001b-1
    描述: mobile 隐藏顶部导航，底部固定 tab 栏 5 项
    验证方式: e2e-browser
    路径: /
    视口: [mobile]
    判定: `nav.top-nav` 不在 DOM；存在 `position:fixed; bottom:0` 高 60px 的 nav，直接子项 5 个（图标+文字）
  - id: AC-001b-2
    描述: tablet 显示顶部导航、隐藏底部 tab 与同步胶囊
    验证方式: e2e-browser
    路径: /
    视口: [tablet]
    判定: top-nav 存在；底部 fixed tab 不存在；「上次同步」胶囊不存在
  - id: AC-001b-3
    描述: desktop 显示同步胶囊
    验证方式: e2e-browser
    路径: /
    视口: [desktop]
    判定: 存在文本以「上次同步」开头的胶囊元素
  - id: AC-001b-4
    描述: 主内容区 padding 按断点分级
    验证方式: e2e-browser
    路径: /
    视口: [mobile, tablet, desktop]
    判定: 主内容容器 computed padding = mobile `14px 12px 76px` / tablet `18px 16px` / desktop `22px 24px`
  - id: AC-001b-5
    描述: 五路由双模导航均可达、默认落分析页、无横向溢出
    验证方式: e2e-browser
    路径: /
    视口: [mobile, desktop]
    判定: 经底部 tab（mobile）/ 顶部导航（desktop）可导航到 5 路由；`/` 默认落分析页；每路由每视口 `documentElement.scrollWidth <= innerWidth`

### C-2 返工 — 登录页响应式 + 保真（清单 #2 + G-resp 升级，structural-轻）
- 返工需求：`002b`（supersedes 002）　组件：LoginForm　**无功能/API 变更**，仅保真 + 移动视口再验
- 可验证标准（+ G-*）：
  - [ ] rev 1 登录功能判据全部保留（字段/演示校验/无营销/门禁#1 e2e）。
  - id: AC-002b-1
    描述: mobile 登录卡由外层 padding 收窄、无横向溢出
    验证方式: e2e-browser
    路径: /login
    视口: [mobile]
    判定: 卡片 offsetWidth = 342（390−48）；`documentElement.scrollWidth <= 390`

### C-3 返工 — 会话栏响应式（清单 #6，structural）
- 返工需求：`003b`（supersedes 003）　组件：SessionRail
- 可验证标准（+ G-*）：
  - [ ] rev 1 会话增改删至空自动新建功能判据全部保留（含 e2e）。
  - id: AC-003b-1
    描述: desktop 左栏 212px aside；mobile/tablet 降级为顶部下拉
    验证方式: e2e-browser
    路径: /
    视口: [mobile, tablet, desktop]
    判定: desktop 存在 offsetWidth≈212 的会话 aside；mobile/tablet 该 aside 不存在且存在会话 `select` + 新建按钮

### C-4 返工 — 范围选择器响应式 + 保真（清单 #2 + §3.4，structural-轻）
- 返工需求：`004b`（supersedes 004）　组件：ScopeBar　逻辑无变更，仅移动重排 + 保真
- 可验证标准（+ G-*）：
  - [ ] rev 1 胶囊/选择运动/两开关默认开/摘要联动 判据全部保留（unit）。
  - id: AC-004b-1
    描述: mobile 勾选项组（附带健康/习惯）flex-wrap 换行、无横向溢出
    验证方式: e2e-browser
    路径: /
    视口: [mobile]
    判定: 「附带健康记录」「附带习惯记录」两开关不在同一水平行（第二项 top 大于第一项）；`documentElement.scrollWidth <= 390`

### C-5 返工 — 图表卡片响应式（清单 #6，structural）
- 返工需求：`005b`（supersedes 005）　组件：ChartCard
- 可验证标准（+ G-*）：
  - [ ] rev 1 四态（加载/空态/折叠/展开）判据全部保留（unit + 门禁#5 e2e）。
  - [ ] **视觉层级判据更新**：用户消息（实心蓝右对齐）> AI 气泡（面板色左对齐）> 卡片（气泡内下沉层 #0B1220）。**删除「AI 气泡最小宽 46%」**（移交 C-6 气泡返工；见 C-6）。
  - id: AC-005b-1
    描述: 展开态数据明细行仅 desktop/wide 渲染
    验证方式: e2e-browser
    路径: /
    视口: [tablet, desktop]
    前置数据: 在分析页发送一条会生成图表卡片的分析提问，待卡片就绪（折叠态）后点击展开该卡片
    判定: 展开卡片内，tablet 不存在明细行容器（仅轴说明+图表）；desktop 存在，行字号 computed 12px、mono
  - id: AC-005b-2
    描述: 展开态图表 svg 宽度自适应容器不溢出
    验证方式: e2e-browser
    路径: /
    视口: [mobile, desktop]
    前置数据: 在分析页发送一条会生成图表卡片的分析提问，待卡片就绪后点击展开该卡片
    判定: 展开态 svg viewBox=`0 0 340 112`，渲染宽度 ≤ 其容器宽度

### C-6 返工 — 对话气泡返工（清单 #5，structural）
- 返工需求：`006b`（supersedes 006）　组件：ChatMessage、SysPrompt
- 可验证标准（+ G-*）：
  - [ ] rev 1 AI HTML 渲染 / 计划表格 / 隐藏系统提示词不入流 / 转义白名单禁脚本 判据全部保留（unit）。
  - id: AC-006b-1
    描述: 用户/AI 气泡尾角不对称 4px
    验证方式: e2e-browser
    路径: /
    视口: [desktop]
    前置数据: 发送一条分析消息
    判定: 用户气泡 computed `border-bottom-right-radius = 4px`、其余三角 14px；AI 气泡 `border-bottom-left-radius = 4px`、其余三角 14px
  - id: AC-006b-2
    描述: AI 气泡移除 46% 最小宽度、max-width 按断点分级
    验证方式: e2e-browser
    路径: /
    视口: [mobile, desktop]
    前置数据: 发送一条 AI 回复（任意长度，仅需气泡入 DOM）
    判定: AI 气泡 computed `min-width` 解析为 auto/0（无 46% 下限）；mobile 下 computed `max-width` 解析为容器 100%（无低于 100% 的上限）。两者均直接读 computed 值、与回复内容长度无关

### C-7 返工 — 运动列表响应式（清单 #7，structural）
- 返工需求：`007b`（supersedes 007）　组件：ActivityTable、ActivityCardList、Pager
- 可验证标准（+ G-*）：
  - [ ] rev 1 列集/类型筛选/分页 20-50-100/批量计数 判据全部保留（含 e2e）。
  - id: AC-007b-1
    描述: mobile 表格隐藏、渲染卡片列；desktop 反之
    验证方式: e2e-browser
    路径: /activities
    视口: [mobile, desktop]
    判定: mobile 下 `min-width:960px` 表格容器 computed display=none，卡片数 = min(每页条数, 剩余条数)；desktop 下表格 display≠none 且无卡片列；两视口均无横向溢出（表格容器内横滚不外溢页面）

### C-8 返工 — 运动详情响应式（清单 #8，structural）
- 返工需求：`008b`（supersedes 008）　组件：ActivityDetail、TimeSeriesChart、RecordTable、LapsTable
- **验收前置（承接 rev 1 §7.3，已满足）**：真实样本 `tests/fixtures/614797758_ACTIVITY.fit` 已在 repo；FIT 字段白名单断言（≥8 项）判据原样保留。
- 可验证标准（+ G-*）：
  - [ ] rev 1 FIT 字段白名单 / 时序双模式 / 心率区间图 / Laps 平均功率 / 门禁#4 e2e 判据全部保留。
  - id: AC-008b-1
    描述: mobile 逐秒表 / Laps 行转卡片，无 min-width 大表溢出
    验证方式: e2e-browser
    路径: /activities/1
    视口: [mobile]
    前置数据: 将时序区从降采样曲线切换至「逐秒数据表」模式（Laps 分段表默认可见，无需切换）
    判定: 逐秒表卡片模式下不存在 `min-width:820px` 元素；Laps 每圈一卡；`documentElement.scrollWidth <= 390`
  - id: AC-008b-2
    描述: 时序图表 X 轴刻度按断点分档、图表不溢出
    验证方式: e2e-browser
    路径: /activities/1
    视口: [mobile, desktop]
    判定: desktop X 轴 5 档刻度、mobile 3 档（首/中/末）、Y 轴恒 3 档；每张 svg 渲染宽 ≤ 容器宽

### C-9 返工 — 健康记录响应式（清单 #9，structural）
- 返工需求：`009b`（supersedes 009）　组件：HealthTabs、HealthTables、SleepChart、HabitPicker
- 可验证标准（+ G-*）：
  - [ ] rev 1 五子标签 / 习惯记录 / 数据量级（体重·RHR·HRV ≥30、睡眠 ≥14）/ 分页档 判据全部保留（unit）。
  - id: AC-009b-1
    描述: 睡眠柱数按断点：desktop/tablet 14 根，mobile 7 根
    验证方式: e2e-browser
    路径: /health
    视口: [mobile, tablet]
    判定: mobile 睡眠柱 = 7 根（标题含「近 7 天」）；tablet = 14 根（标题含「近 14 天」）
  - id: AC-009b-2
    描述: mobile 四张明细表行转卡片、无大表溢出
    验证方式: e2e-browser
    路径: /health
    视口: [mobile]
    判定: 四表卡片模式下不存在 min-width 表格元素；`documentElement.scrollWidth <= 390`

### C-10 返工 — 连接器卡片响应式（清单 #10，structural）
- 返工需求：`010b`（supersedes 010）　组件：ConnectorCard
- 可验证标准（+ G-*）：
  - [ ] rev 1 四状态集合 / 间隔选项 / 演示初始态 判据全部保留（unit）。
  - id: AC-010b-1
    描述: 卡片 grid `minmax(min(320px,100%),1fr)`，mobile 单列堆叠不溢出
    验证方式: e2e-browser
    路径: /connectors
    视口: [mobile, desktop]
    判定: mobile 两连接器卡纵向堆叠（第二卡 top 大于第一卡）；desktop 两卡同排（第二卡 top == 第一卡、left 不同）；两视口 `documentElement.scrollWidth <= innerWidth`

### C-11 返工 — 授权弹窗 mobile 全屏（清单 #11，structural）
- 返工需求：`011b`（supersedes 011）　组件：ConnectorAuthModal
- 可验证标准（+ G-*）：
  - [ ] rev 1 2FA 两段式流程 判据全部保留（门禁#2 e2e）。
  - id: AC-011b-1
    描述: mobile 弹窗全屏化，desktop 居中定宽
    验证方式: e2e-browser
    路径: /connectors
    视口: [mobile, desktop]
    前置数据: 打开 2FA 授权弹窗
    判定: mobile 面板 offsetWidth=390（=视口宽）、computed `border-radius=0px`；desktop 面板宽 390px、居中、`border-radius=14px`

### C-12 返工 — 合并弹窗 mobile 全屏（清单 #11，structural）
- 返工需求：`012b`（supersedes 012）　组件：ConflictBanner、ConflictModal
- 可验证标准（+ G-*）：
  - [ ] rev 1 去重规则 / 横幅 / 逐组选择 / 合并后横幅消失 判据全部保留（门禁#3 e2e）。
  - id: AC-012b-1
    描述: mobile 合并弹窗全屏，desktop 居中 620px
    验证方式: e2e-browser
    路径: /connectors
    视口: [mobile, desktop]
    前置数据: 触发冲突并打开合并弹窗
    判定: mobile 面板 offsetWidth=390、`border-radius=0px`、内部可 overflow-y 滚动；desktop 面板宽 620px、居中、`border-radius=14px`

### C-13 返工 — 文件上传响应式（清单 #10，structural）
- 返工需求：`013b`（supersedes 013）　组件：FileUpload
- 可验证标准（+ G-*）：
  - [ ] rev 1 多选/≤50MB 拒超限/已解析列表入库/来源标注 判据全部保留（unit）。
  - id: AC-013b-1
    描述: 上传区与已解析列表同 grid 规则，mobile 单列不溢出
    验证方式: e2e-browser
    路径: /connectors
    视口: [mobile]
    判定: 上传区与「已解析文件」列表 mobile 单列堆叠；`documentElement.scrollWidth <= 390`

### C-14 返工 — 设置：删除数据保留 + 响应式（清单 #12 #13，**scope**）
- 返工需求：`014b`（supersedes 014）　组件：SettingsSections（−RetentionGroup）
- 可验证标准（+ G-*）：
  - [ ] **分组由五 → 四**：账户信息 / 单位制 / 区间设定 / AI 接口。rev 1 中「数据保留策略」分组（占用统计 / 保留期限 / 到期自动清理开关）**删除**。
  - [ ] 区间设定仍仅作原始数据标注边界（供 C-8 心率区间图 + AI 对话），系统不用于计算；账户密码一致性校验保留（unit）。
  - id: AC-014b-1
    描述: 任何断点页面不含「数据保留策略」文案与到期清理控件
    验证方式: e2e-browser
    路径: /settings
    视口: [mobile, desktop]
    判定: 页面不存在文本「数据保留策略」「到期自动清理」「保留期限」；无对应控件
  - [ ] 系统不提供整体删除 / 到期自动清理数据的功能（无相关 action，unit 断言无此调用路径）。
  - id: AC-014b-2
    描述: mobile 心率区间输入为 2×2 网格
    验证方式: e2e-browser
    路径: /settings
    视口: [mobile]
    判定: 心率区间输入区 mobile `repeat(2,1fr)`——首行 2 个输入框 top 相同，第 3 个换行；desktop/tablet `repeat(4,minmax(80px,1fr))`
  - [ ] unit：密码不一致报错；区间设定写入后被 C-8 详情页读取（联调保留）。

## 4. E2E 门禁冒烟集（design_rev 2）

- **rev 1 的 5 条门禁不增删**（登录 / 2FA / 合并 / 详情双模式 / 分析卡片流），语义随各返工条目沿用。门禁#1 登录在双模导航下仍以「错误验证码被拒 → 正确登录跳分析页」为准（与导航模式无关）。
- **新增门禁#6 —— 响应式无溢出冒烟**（升级后 G-resp 的门禁化）：
  - **无横向溢出**：遍历全部 7 个可达路由（/login、/、/activities、/activities/1、/health、/connectors、/settings，均稳定可达；/activities/1 取运动列表首条「晨间轻松跑」），在 4 视口（390 / 768 / 1280 / 1920）断言 `document.documentElement.scrollWidth <= window.innerWidth`。
  - **双模导航**（仅对 6 个 in-app 路由，**排除 /login**——`/login` 渲染在 `AppLayout` 之外、无任何导航 chrome，`App.tsx` 已证实）：mobile 断言底部 tab 5 项可见、顶部导航不在 DOM；desktop 断言顶部导航在、底部 tab 不在。
  - **/login 单独断言**（避免误判）：mobile 与 desktop 下 `/login` 均**无** top-nav、**无**底部固定 tab（login 页两种导航都不应存在）。
- C-4 / C-9 / C-10 / C-13 / C-14 仍不要求「功能 e2e」，但其**响应式 e2e-browser 断言**（上表 AC-*）为该条目验收组成部分——响应式是 v2.0 的交付主体，必须自动验，不下放 visual/manual。

## 5. 待 Validator 协商的开放点

1. **返工范围：全 14 vs 002/004 降级 cosmetic-only** —— Planner 主张 **全 14 返工**。理由：G-resp 升级为四断点 + 新增「所有路由所有断点无横向溢出」硬不变量，而 002/004 在 rev 1 **从未在 mobile 视口 e2e 验过**（rev 1 只验 ≥980px）；标低会让 v1.0 登录/范围条在 390px 溢出却照旧通过、污染 main。002b/004b 已标注为「无功能/API 变更、仅保真 + 移动视口再验」的轻返工。Validator 若确信 v1.0 代码已满足新 G-resp，可将 002/004 降为 cosmetic（仅追加 changelog、不建返工需求）——请明确裁定。
2. **G-resp 基线升级** —— 接受把「平板 `<980px`」替换为四断点矩阵 + 「6 路由 × 4 视口 `scrollWidth<=innerWidth`」硬不变量作为 G-resp 新定义？
3. **门禁#6 响应式冒烟** —— 接受新增门禁#6（视口集 [390,768,1280,1920]、路由集如上、双模导航切换断言）？路由集是否要增删（如是否纳入 /activities/1 详情）？
4. **视觉保真（#2 cosmetic）的验法边界** —— Planner 主张：**结构性/重排参数**（宽度、display none/flex、grid 列数、圆角非对称、padding 分级）走 e2e-browser（上表 AC-*）；**纯色值/纯间距保真**走 G-token（token 文件外裸值 lint error）+ 少量关键 computed-style 抽点，不做逐参数 e2e（过脆、体量爆炸）、不引入视觉快照。接受此边界？还是要求追加特定 computed-style 断言（如气泡背景色、按钮 padding）？
5. **C-8 FIT 前置** —— 样本已在 repo，无新增 human fixture；返工原样保留 rev 1 字段白名单（≥8 项）。确认无需新 fixture、无 blocked 风险？
6. **编号与文件操作** —— 接受 001b…014b（b 后缀继承槽位、`supersedes` 原号、`source_design_rev: 2`）、原 001–014 文档留 `completed/` 当历史（不移回、不改写）、新返工需求建于 `active/`？依赖顺序沿用 rev 1 执行表（001b 打底，余者依赖 001b）。

## 6. Ack

- `planner_ack: true`（本文件 frontmatter）——分级、失效检查、返工条目与 e2e-browser 判据、G-resp 升级与门禁#6 由 Planner 提出。
- `validator_ack: true`（2026-07-13）—— §5 六个开放点已逐条裁定（全接受 Planner 主张，见 §7），并对判据做 5 处客观可断言性修订（R1–R5，见 §7）。

> 双方 ack 齐备。Planner 可据此落成 contract.md（返工 C-1…C-14，纳入 R1–R5 修订）、建 001b–014b、更新 backlog/changelog/design-state，删除 `.blocked`。

## 7. Validator 协商裁定与修订（2026-07-13）

### 7.1 §5 六开放点裁定（全接受 Planner 主张）

1. **返工范围**：**全 14 返工**。002b/004b 保留为「无功能/API 变更、仅保真 + 移动视口再验」的轻返工，**不降 cosmetic**。理由认可：rev 1 只在 ≥980px 验过，002/004 从未在 mobile e2e 验证，降级会让 390px 溢出照旧通过、污染 main。
2. **G-resp 基线升级**：接受四断点矩阵 + 「全部路由 × 4 视口无横向溢出」硬不变量作为 G-resp 新定义（路由集见 R1）。
3. **门禁#6 响应式冒烟**：接受新增。路由集与导航断言按 R1 明确化。
4. **视觉保真验法边界**：接受——结构性/重排参数走 e2e-browser（AC-*），纯色值/纯间距走 G-token（token 文件外裸值 lint error）+ 少量关键 computed-style 抽点；**不做逐参数 e2e、不引视觉快照**。R3 是这一边界内对既有 computed 抽点判据的客观化，非追加新参数。
5. **C-8 FIT 前置**：确认 `tests/fixtures/614797758_ACTIVITY.fit` 已在 repo（复核：245KB 真实 FIT），无新增 human fixture、无 blocked 风险；返工原样保留 rev 1 字段白名单（≥8 项）。
6. **编号与文件操作**：接受 001b–014b（b 后缀继承槽位、`supersedes` 原号、`source_design_rev: 2`），原 001–014 留 `completed/` 当历史，返工需求建于 `active/`，依赖顺序沿用 rev 1（001b 打底）。

### 7.2 可验证判据修订（R1–R5，客观可断言性）

- **R1（门禁#6 / §2 G-resp，材料级）**：`/login` 渲染在 `AppLayout` 之外，**既无 TopNav 也无 BottomTabBar**（`src/App.tsx:16`、`src/components/AppLayout.tsx` 证实）。原「6 路由 … 取其中稳定可达者」既与 §2「6 路由」计数不一致，又会让门禁#6 的「mobile 底部 tab 5 项 / desktop 顶部导航」断言在 `/login` 误判失败。已拆分：**无横向溢出**覆盖全部 **7** 路由（含 `/login`）；**双模导航**仅对 **6** 个 in-app 路由，`/login` 单独断言「两种导航均不存在」。删除不可断言的「取其中稳定可达者」。
- **R2（AC-005b-1 / AC-005b-2，材料级）**：展开态图表卡片须经「发送分析提问 → 卡片就绪 → 展开」才可达，原判据无 `前置数据`，validator 须自行发明步骤（违反「协商阶段把话说死」）。已补 `前置数据`（与门禁#5 流程一致）。
- **R3（AC-006b-2，材料级）**：「mobile 下气泡可达容器 100% 宽」用「发送一条短 AI 回复」无法客观证明——短回复宽度由内容决定。已改为直接读 computed `min-width`（auto/0）与 computed `max-width`（mobile 解析为 100%），内容长度无关。
- **R4（AC-008b-1，材料级）**：详情页时序区默认降采样曲线模式，检查「逐秒表卡片模式」须先切换。已补 `前置数据`（切换至逐秒数据表；Laps 表默认可见无需切换）。
- **R5（AC-010b-1，轻微）**：desktop「两列并排」无客观测法，已改为「第二卡 top == 第一卡、left 不同」。

### 7.3 复核结论

其余全部 AC-*（001b-1…014b-2）判据经逐条复核，均为客观可断言粒度（DOM 存在性、computed 样式精确值、offsetWidth/top/left 几何关系、`scrollWidth<=innerWidth`），`验证方式` 均为 `e2e-browser` 或 `unit`（无 `visual`/`manual` 下放）；`路径`/`视口`/（含状态者）`前置数据` 齐备。继承的 rev 1 功能判据与 5 条门禁语义沿用无冲突。**无遗漏、无歧义遗留**，可落成。
