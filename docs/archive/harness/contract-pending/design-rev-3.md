---
proposal_for_design_rev: 3
design_version: "3.0"
impact: structural            # 全 13 条 structural / fidelity: pixel-contract
planner_ack: true
validator_ack: true
created_at: 2026-07-13
source:
  update: "design/v3.0/交接/update.md (design_rev 3)"
  detail: "design/v3.0/交接/v3.0-设计文档.md（§A 视觉契约清单 + §B 交互契约）"
  prototype: "design/v3.0/运动分析系统.dc.html（v3.0；导出副本，属设计侧输入）"
---

# 提案 — design_rev 3（TrainLab v3.0：视觉契约显式化 / pixel-contract）

> 本文件是 `pending/` 协商稿，**不是** contract。双方 `planner_ack` + `validator_ack` 后，
> 由 Planner 把下方条目落成到 `docs/contract/contract.md`（返工命中的 C 条目），
> 按决议做文件操作（原 001b–014b 留 `completed/` 当历史、在 `active/` 新建 00Xc 返工需求），
> 更新 `backlog.md`、追加 `changelog.md`，最后删除 `docs/executor/.blocked`。

## 0. 分级判定

- `design_rev` 2 → 3。变更清单 13 行，**全部 `impact: structural` / `fidelity: pixel-contract`**。
- v3.0 **无任何视觉设计变更**（色板/字号/间距 token 以 v2.0 为准）。本版只做两件事：
  1. 为每个「真正定义长相且可能被搞错」的视觉/布局对象加**稳定 `data-vc` 锚点**；
  2. 逐锚点声明以浏览器 **computed 值**为准的契约属性与断点差异（§A）+ 交互契约（§B）。
- 判据：组件契约面（背景/边框/圆角/关键间距/配色/布局列数/断点显隐/弹窗形态）从「未声明是要求」升级为「pixel-contract 硬契约」——属 `structural`（改的是**契约本身**，不是像素微调）。按 planner CLAUDE.md「视觉契约（fidelity: pixel-contract 的落成）」节走 contract 协商 + 失效检查全流程。`.blocked` 已于 `created_at=2026-07-13T17:30:00+08:00` 创建。
- **无 `cosmetic`、无 `scope`**：不新增/删除功能、不移动需求边界、不改信息架构。纯保真契约硬化。

### 0.1 取值三级与缺料前置检查（planner CLAUDE.md「取值三级」）

- §A 值分两级：**实测**（desktop/wide 渲染实采，rgb/px）与 **authored**（tablet/mobile 专属值，由组件 `bp/isMobile` 分支决定、源码推断）。
- **实测** → 直接落成 e2e-browser 断言。
- **authored** → 可落成，但**该 AC 注明「该视口值源码 authored，Validator 实测复核」**（值仍照抄，复核以对应视口实测为准）。
- **`待渲染确认`**（无可断言值）→ 逐锚点扫描 v3.0 设计文档，**未发现任何标此级的锚点**。无「缺值不落成」条目。
- **fixture 前置检查**：本版为纯视觉契约，**无新增 `fixture_owner: human` 资产**（C-8 仍复用既在 repo 的 `tests/fixtures/614797758_ACTIVITY.fit`）。**无 fixture 死锁**，全部命中条目可照常落地。

## 1. 失效检查结果

遍历 `docs/executor/active/`（**空**）与 `docs/executor/completed/`（001–014 + 001b–014b，共 28 份）。
live 档为 **001b–014b**（001–014 已被 b 变体 supersede），全部 `verified`、`source_design_rev: 2`、**零 `data-vc` 锚点**（Explore 复核确认）。
`source_design_rev 2 < 3` 且涉及组件命中 §A 锚点的 live 需求 → 走**返工已 verified 流程**：不动 `completed/` 原文档（rev 2 历史事实），在 `active/` 新建 `<原号>c` 返工需求（`supersedes` 原 b 号、`source_design_rev: 3`、带 pixel-contract 更严标准 + 强制 `data-vc` 镜像）。

### 1.1 锚点 → C 条目 → 返工槽位映射

| §A 锚点 | 契约面 | C 条目 | live 需求 | 返工槽位 | 组件 |
|---|---|---|---|---|---|
| A20 top-nav / top-nav-item-active / sync-chip / bottom-nav / bottom-nav-item-active / toast / btn-primary | 顶栏·导航·主按钮·toast | C-1 | 001b | **001c** | TopNav / BottomTabBar / SyncChip / Toast / BtnPrimary |
| A7 session-rail / A8 session-rail-item(-active) / A9 analysis-main / A10 analysis-input | 会话栏 + 分析布局 | C-3 | 003b | **003c** | SessionRail / AnalysisLayout / AnalysisInput |
| A11 scope-chip(-selected) | 范围胶囊 | C-4 | 004b | **004c** | ScopeBar |
| A3 chart-card | 图表卡片容器 | C-5 | 005b | **005c** | ChartCard |
| A1 chat-bubble-ai / A2 chat-bubble-user | 对话气泡 | C-6 | 006b | **006c** | ChatMessage |
| A14 activities-table / activities-card-list · A12 type-chip(-selected) | 运动列表重排 + 类型胶囊 | C-7 | 007b | **007c** | ActivityTable / ActivityCardList / TypeChip |
| A4 metric-card / A5 hr-zone-bar | 指标卡 + 心率区间条 | C-8 | 008b | **008c** | MetricCard / HrZoneBar |
| A6 sleep-chart-bar-deep/-light/-rem · A13 health-tab(-selected) | 睡眠堆叠柱 + 健康子标签 | C-9 | 009b | **009c** | SleepChart / HealthTab |
| A15 connectors-grid / connector-card · A16 status-pill-connected/-failed/-disconnected | 连接器网格·卡片·状态胶囊 | C-10 | 010b | **010c** | ConnectorsGrid / ConnectorCard / StatusPill |
| A19 modal-connector-auth / modal-overlay | 授权弹窗 | C-11 | 011b | **011c** | ConnectorAuthModal / ModalOverlay |
| A19 modal-conflict / modal-overlay | 合并弹窗 | C-12 | 012b | **012c** | ConflictModal / ModalOverlay |
| A17 settings-page / settings-group · A18 settings-account-grid / settings-zone-grid | 设置布局 | C-14 | 014b | **014c** | SettingsPage / SettingsGroup / SettingsGrids |

**返工 12 条**：001c / 003c / 004c / 005c / 006c / 007c / 008c / 009c / 010c / 011c / 012c / 014c。

### 1.2 未命中（保留，不返工）

| C 条目 | live 需求 | 组件 | §A 有无锚点 | 决议 |
|---|---|---|---|---|
| C-2 | 002b | LoginForm | 无（§A 未声明登录页任何视觉契约锚点） | **保留**（source_design_rev 停 2，不建 002c） |
| C-13 | 013b | FileUpload | 无（A15 `connectors-grid` 仅覆盖两张连接器卡；上传区双栏 grid 未单独锚定） | **保留**（见开放点 §5-3，待 Validator 裁定） |

- **无废弃、无新增独立 C 条目**：v3.0 全部锚点都落在既有 C-1…C-14 组件上，均折进对应返工条目，不另开 C-15+。
- **告警段落**：`active/` 无 `in_progress` / `awaiting_validation` 需求，无需追加「设计变更告警」段落。

## 2. 全局验证基线变更（G-*）

沿用 rev 2 全部 G-*（含升级后 G-resp、门禁#1–#6），**新增一条 G-fidelity**：

- **G-fidelity（新增，design_rev 3）**：原型（`design/v3.0/运动分析系统.dc.html`）为**像素级保真契约源**，非结构示意图。§A 每个 `data-vc` 锚点的契约属性以**浏览器 computed 值**为准（rgb/rgba、px），下游实现必须：
  1. 把 `data-vc="<锚点名>"` 镜像到实现对应组件的**根元素**（否则 Validator 的 `[data-vc=…]` 选空、断言全废——**这是每条返工需求的硬要求**）；
  2. 命中锚点的 computed 契约属性与 §A 值**直接相等**（同为浏览器 computed，同格式，无需换算）。
- G-fidelity 的**验法边界**（承接 rev 2 §7.1-4）：pixel-contract 契约属性走 **e2e-browser computed-style 断言**（下 §3 各 AC-*）；纯 token 集中定义仍由 **G-token**（token 文件外裸值 lint error）承接。**不引入视觉快照测试**（沿用 G-token 明文）。
- **锚点名一经落成不再变更**（v3.0 update.md §详细设计约定）：下游按 `[data-vc="<锚点名>"]` 选择器镜像。

## 3. 返工条目（拟落成 contract.md，返工命中的 C 条目）

> 每条 `impact: structural`、`fidelity: pixel-contract`、`决议: 返工`、`design_rev: 3`、`受影响需求: <原号>, <原号>b, <原号>c`。
> 条目继承 rev 2 全部功能 + 响应式判据（决议为返工，前序判据**全部保留**），正文只写 pixel-contract 增量。
> 每条含一条**硬要求（data-vc 镜像）** + 若干 pixel-contract AC-*（e2e-browser computed 断言）。
> 视口基准沿用 G-resp：mobile 390×844 / tablet 768×1024 / desktop 1280×800 / wide 1920×1080。颜色断言用 computed rgb/rgba 精确相等；authored 值注明「Validator 实测复核」。

### C-1 返工（→ 001c）— 顶栏·导航·主按钮·toast 视觉契约
- **硬要求（data-vc 镜像）**：Executor 把 `top-nav`、`top-nav-item-active`、`sync-chip`、`bottom-nav`、`bottom-nav-item-active`、`toast`、`btn-primary`（发送按钮为代表）镜像到对应组件根元素。
- 前序判据（001/001b：四断点 BreakpointState、双模导航、门禁#6）**全部保留**。
- pixel-contract AC：
  - id: AC-001c-1
    描述: top-nav 项选中态配色（A20）
    验证方式: e2e-browser
    路径: /
    视口: [desktop]
    判定: `[data-vc="top-nav-item-active"]` computed `background-color==rgba(66,146,224,0.16)`、`color==rgb(230,235,244)`、`font-weight==600`、`border-radius==8px`、`padding==8px 13px`
  - id: AC-001c-2
    描述: sync-chip 视觉契约（仅 desktop/wide 显示）
    验证方式: e2e-browser
    路径: /
    视口: [desktop]
    判定: `[data-vc="sync-chip"]` computed `background-color==rgb(18,26,40)`、`border==1px solid rgb(34,48,73)`、`border-radius==99px`、`padding==6px 14px`
  - id: AC-001c-3
    描述: bottom-nav 视觉契约（仅 mobile 显示）
    验证方式: e2e-browser
    路径: /
    视口: [mobile]
    判定: `[data-vc="bottom-nav"]` computed `position==fixed`、`bottom==0px`、`height==60px`、`background-color==rgb(13,20,32)`、`border-top==1px solid rgb(28,39,57)`；`[data-vc="bottom-nav-item-active"]` computed `color==rgb(94,163,232)`、`border-top==2px solid rgb(66,146,224)`
  - id: AC-001c-4
    描述: toast 视觉契约
    验证方式: e2e-browser
    路径: /connectors
    视口: [desktop]
    前置数据: 触发一次同步成功（点击「立即同步/重试同步」，等 toast 出现）
    判定: `[data-vc="toast"]` computed `position==fixed`、`bottom==28px`、`background-color==rgb(26,36,54)`、`border==1px solid rgb(58,78,112)`、`border-radius==10px`、`padding==11px 22px`、`font-size==13px`
  - id: AC-001c-5
    描述: btn-primary（发送按钮）视觉契约
    验证方式: e2e-browser
    路径: /
    视口: [desktop]
    判定: `[data-vc="btn-primary"]` computed `background-color==rgb(66,146,224)`、`color==rgb(6,16,30)`、`border-style==none`、`border-radius==10px`、`padding==11px 22px`、`font-weight==700`

### C-3 返工（→ 003c）— 会话栏 + 分析布局视觉契约
- **硬要求（data-vc 镜像）**：`session-rail`、`session-rail-item`、`session-rail-item-active`、`analysis-main`、`analysis-input`。
- 前序判据（003/003b：会话增改删至空自动新建 e2e、desktop 212px aside / mobile-tablet 顶部下拉）**全部保留**。
- pixel-contract AC：
  - id: AC-003c-1
    描述: session-rail 布局契约（desktop）
    验证方式: e2e-browser
    路径: /
    视口: [desktop]
    判定: `[data-vc="session-rail"]` computed `width==212px`、`flex-shrink==0`、`background-color==rgb(13,20,32)`、`border==1px solid rgb(28,39,57)`、`border-radius==12px`、`padding==12px 10px`
  - id: AC-003c-2
    描述: session-rail-item 选中/常态契约
    验证方式: e2e-browser
    路径: /
    视口: [desktop]
    判定: `[data-vc="session-rail-item-active"]` computed `background-color==rgba(66,146,224,0.12)`、`border-left==3px solid rgb(66,146,224)`、`border-radius==8px`、`padding==9px 10px`；`[data-vc="session-rail-item"]`（常态）computed `border-left==3px solid rgba(0,0,0,0)`（透明占位不跳动）、`background-color==rgba(0,0,0,0)`
  - id: AC-003c-3
    描述: analysis-main 布局契约
    验证方式: e2e-browser
    路径: /
    视口: [desktop]
    判定: `[data-vc="analysis-main"]` computed `display==flex`、`gap==18px`、`max-width==1200px`、左右 margin 相等（居中，`margin-left==margin-right`）
  - id: AC-003c-4
    描述: analysis-input 契约 + 流内定位（非 fixed）
    验证方式: e2e-browser
    路径: /
    视口: [desktop]
    判定: `[data-vc="analysis-input"]` computed `background-color==rgb(18,26,40)`、`border==1px solid rgb(34,48,73)`、`border-radius==14px`、`padding==12px 14px`、`position!=fixed`（流内末尾，非浮动遮挡）

### C-4 返工（→ 004c）— 范围胶囊选择态契约
- **硬要求**：`scope-chip`、`scope-chip-selected`。
- 前序判据（004/004b：胶囊/选择运动/两开关默认开/摘要联动 unit、mobile flex-wrap AC）**全部保留**。
- pixel-contract AC：
  - id: AC-004c-1
    描述: scope-chip 选中 vs 常态配色
    验证方式: e2e-browser
    路径: /
    视口: [desktop]
    判定: `[data-vc="scope-chip-selected"]` computed `background-color==rgba(66,146,224,0.18)`、`border==1px solid rgb(66,146,224)`、`color==rgb(94,163,232)`、`border-radius==99px`、`padding==5px 13px`；`[data-vc="scope-chip"]`（常态）computed `background-color==rgb(11,18,32)`、`border==1px solid rgb(42,58,85)`、`color==rgb(138,148,168)`

### C-5 返工（→ 005c）— 图表卡片容器契约
- **硬要求**：`chart-card`。
- 前序判据（005/005b：四态、展开明细行仅 desktop/wide、门禁#5、svg 不溢出）**全部保留**。
- pixel-contract AC：
  - id: AC-005c-1
    描述: chart-card 容器视觉契约（下沉层 #0B1220）
    验证方式: e2e-browser
    路径: /
    视口: [desktop]
    前置数据: 在分析页发送一条会生成图表卡片的分析提问，待卡片就绪（折叠态）
    判定: `[data-vc="chart-card"]` computed `background-color==rgb(11,18,32)`、`border==1px solid rgb(42,58,85)`、`border-radius==10px`、`overflow==hidden`；层级校验：其值 #0B1220 深于 AI 气泡 #121A28

### C-6 返工（→ 006c）— 对话气泡视觉契约
- **硬要求**：`chat-bubble-ai`、`chat-bubble-user`。
- 前序判据（006/006b：HTML 渲染/计划表格/系统提示不入流/转义白名单 unit、尾角不对称 4px、移除 46% 最小宽 AC）**全部保留**。
- pixel-contract AC：
  - id: AC-006c-1
    描述: AI 气泡完整视觉契约（独立面板背景+边框，非裸文字）
    验证方式: e2e-browser
    路径: /
    视口: [desktop]
    前置数据: 发送一条分析消息，待 AI 气泡入 DOM
    判定: `[data-vc="chat-bubble-ai"]` computed `background-color==rgb(18,26,40)`、`border==1px solid rgb(34,48,73)`、`border-radius==14px 14px 14px 4px`、`padding==13px 16px`、`color==rgb(230,235,244)`
  - id: AC-006c-2
    描述: 用户气泡视觉契约（实心蓝、无边框）
    验证方式: e2e-browser
    路径: /
    视口: [desktop]
    前置数据: 发送一条用户消息
    判定: `[data-vc="chat-bubble-user"]` computed `background-color==rgb(46,92,158)`、`border-style==none`、`border-radius==14px 14px 4px 14px`、`padding==12px 14px`、`color==rgb(230,235,244)`
  - id: AC-006c-3
    描述: 气泡 max-width 按断点分级
    验证方式: e2e-browser
    路径: /
    视口: [mobile, tablet, desktop]
    前置数据: 发送用户 + AI 各一条消息
    判定: `[data-vc="chat-bubble-ai"]` computed `max-width` = desktop 容器 82%（实测）/ tablet 92%（authored，Validator 实测复核）/ mobile 100%（authored，复核）；`[data-vc="chat-bubble-user"]` = desktop 68%（实测）/ tablet 80%（authored）/ mobile 94%（authored）

### C-7 返工（→ 007c）— 运动列表重排 + 类型胶囊契约
- **硬要求**：`activities-table`、`activities-card-list`、`type-chip`、`type-chip-selected`。
- 前序判据（007/007b：列集/类型筛选/分页/批量计数 e2e、mobile 卡片重排 AC）**全部保留**。
- pixel-contract AC：
  - id: AC-007c-1
    描述: activities-table / card-list 断点重排（display 契约）
    验证方式: e2e-browser
    路径: /activities
    视口: [mobile, desktop]
    判定: desktop `[data-vc="activities-table"]` computed `display!=none`（block）、`background-color==rgb(18,26,40)`、`border==1px solid rgb(34,48,73)`、`border-radius==12px`、`overflow-x==auto`、内层 `min-width==960px`；`[data-vc="activities-card-list"]` 不在 DOM。mobile `[data-vc="activities-table"]` computed `display==none`、`[data-vc="activities-card-list"]` 存在且 computed `display==flex`、`flex-direction==column`、`gap==10px`
  - id: AC-007c-2
    描述: type-chip 选中 vs 常态配色
    验证方式: e2e-browser
    路径: /activities
    视口: [desktop]
    判定: `[data-vc="type-chip-selected"]` computed `background-color==rgba(66,146,224,0.16)`、`border==1px solid rgb(66,146,224)`、`color==rgb(94,163,232)`、`border-radius==99px`、`padding==6px 14px`；`[data-vc="type-chip"]`（常态）`background-color==rgb(18,26,40)`、`border==1px solid rgb(34,48,73)`、`color==rgb(138,148,168)`

### C-8 返工（→ 008c）— 指标卡 + 心率区间条契约
- **硬要求**：`metric-card`、`hr-zone-bar`。
- **验收前置**：真实样本 `tests/fixtures/614797758_ACTIVITY.fit`（`fixture_owner: human`）已在 repo，无新增 human fixture。
- 前序判据（008/008b：FIT 字段白名单 ≥8 项、时序双模式、门禁#4、Laps、心率区间图边界取自设置区间设定、mobile 重排 AC）**全部保留**。
- pixel-contract AC：
  - id: AC-008c-1
    描述: metric-card 视觉契约 + grid 自适应
    验证方式: e2e-browser
    路径: /activities/1
    视口: [desktop]
    判定: `[data-vc="metric-card"]` computed `background-color==rgb(18,26,40)`、`border==1px solid rgb(34,48,73)`、`border-radius==10px`、`padding==14px`；所在 grid computed `grid-template-columns` 解析为 `repeat(auto-fit,minmax(130px,1fr))` 展开（各列 ≥130px）
  - id: AC-008c-2
    描述: hr-zone-bar 高度/圆角 + 五区配色
    验证方式: e2e-browser
    路径: /activities/1
    视口: [desktop]
    判定: `[data-vc="hr-zone-bar"]` computed `height==16px`、`border-radius==4px`；五区 background 依次 Z1 `rgb(92,104,126)` / Z2 `rgb(66,146,224)` / Z3 `rgb(63,191,143)` / Z4 `rgb(224,160,64)` / Z5 `rgb(224,96,96)`

### C-9 返工（→ 009c）— 睡眠堆叠柱 + 健康子标签契约
- **硬要求**：`sleep-chart-bar-deep`、`sleep-chart-bar-light`、`sleep-chart-bar-rem`、`health-tab`、`health-tab-selected`。
- 前序判据（009/009b：五子标签/习惯/数据量级/分页 unit、睡眠柱数断点 7/14、mobile 重排 AC）**全部保留**。
- pixel-contract AC：
  - id: AC-009c-1
    描述: 睡眠堆叠柱三段配色与圆角
    验证方式: e2e-browser
    路径: /health
    视口: [desktop]
    前置数据: 切至睡眠子标签
    判定: `[data-vc="sleep-chart-bar-deep"]` computed `background-color==rgb(46,92,158)`、`border-radius==0px 0px 3px 3px`；`-light` `background-color==rgb(66,146,224)`、`border-radius==0px`；`-rem` `background-color==rgb(143,193,242)`、`border-radius==3px 3px 0px 0px`
  - id: AC-009c-2
    描述: health-tab 选中 vs 常态配色
    验证方式: e2e-browser
    路径: /health
    视口: [desktop]
    判定: `[data-vc="health-tab-selected"]` computed `background-color==rgba(66,146,224,0.16)`、`border==1px solid rgb(66,146,224)`、`color==rgb(94,163,232)`、`border-radius==8px`、`padding==7px 18px`、`font-size==13px`；`[data-vc="health-tab"]`（常态）`background-color==rgb(18,26,40)`、`border==1px solid rgb(34,48,73)`、`color==rgb(138,148,168)`

### C-10 返工（→ 010c）— 连接器网格·卡片·状态胶囊契约
- **硬要求**：`connectors-grid`、`connector-card`、`status-pill-connected`、`status-pill-failed`、`status-pill-disconnected`。
- 前序判据（010/010b：四状态集合/间隔选项/演示初始态 unit、grid mobile 单列 AC）**全部保留**。
- pixel-contract AC：
  - id: AC-010c-1
    描述: connectors-grid 列数断点 + connector-card 视觉契约
    验证方式: e2e-browser
    路径: /connectors
    视口: [mobile, desktop]
    判定: desktop `[data-vc="connectors-grid"]` computed `display==grid`、`grid-template-columns` 解析为 2 列（两卡同排）、`gap==16px`；mobile 解析为 1 列。`[data-vc="connector-card"]` computed `background-color==rgb(18,26,40)`、`border==1px solid rgb(34,48,73)`、`border-radius==12px`、`padding==20px`
  - id: AC-010c-2
    描述: status-pill 三态配色
    验证方式: e2e-browser
    路径: /connectors
    视口: [desktop]
    判定: 公共 `border-radius==99px`、`padding==4px 12px`、`font-size==11px`、`border-width==1px`；`status-pill-connected` `color==rgb(63,191,143)`、`background-color==rgba(63,191,143,0.12)`、`border-color==rgba(63,191,143,0.35)`（authored，Validator 实测复核）；`status-pill-failed` `color==rgb(224,96,96)`、`background-color==rgba(224,96,96,0.1)`、`border-color==rgba(224,96,96,0.4)`；`status-pill-disconnected` `color==rgb(138,148,168)`、`background-color==rgba(138,148,168,0.1)`、`border-color==rgb(42,58,85)`
    说明: 演示初始态为「中国区同步失败 / 国际区未连接」；connected 态须触发一次同步成功后采集（承接 C-1 AC-001c-4 前置流程）。

### C-11 返工（→ 011c）— 授权弹窗视觉/形态契约
- **硬要求**：`modal-connector-auth`、`modal-overlay`。
- 前序判据（011/011b：2FA 两段式 门禁#2、mobile 全屏 AC）**全部保留**。
- pixel-contract AC：
  - id: AC-011c-1
    描述: modal-connector-auth desktop 居中定宽 vs mobile 全屏
    验证方式: e2e-browser
    路径: /connectors
    视口: [mobile, desktop]
    前置数据: 打开 2FA 授权弹窗
    判定: desktop `[data-vc="modal-connector-auth"]` computed `width==390px`、`border==1px solid rgb(42,58,85)`、`border-radius==14px`、`padding==24px`、`background-color==rgb(18,26,40)`；mobile computed `width` == 视口宽 390px、`border-radius==0px`、`border-style==none`、`overflow-y==auto`（authored，Validator 实测复核）。`[data-vc="modal-overlay"]` computed `position==fixed`、`background-color==rgba(4,8,14,0.72)`

### C-12 返工（→ 012c）— 合并弹窗视觉/形态契约
- **硬要求**：`modal-conflict`、`modal-overlay`。
- 前序判据（012/012b：去重/横幅/逐组选择/合并后横幅消失 门禁#3、mobile 全屏 AC）**全部保留**。
- pixel-contract AC：
  - id: AC-012c-1
    描述: modal-conflict desktop 620px 居中 vs mobile 全屏
    验证方式: e2e-browser
    路径: /connectors
    视口: [mobile, desktop]
    前置数据: 触发冲突并打开合并弹窗
    判定: desktop `[data-vc="modal-conflict"]` computed `width==620px`、`border-radius==14px`、`padding==24px`、`max-height==86vh`（或解析像素 ≈0.86×视口高）、居中（左右 margin/offset 相等）；mobile computed `width`==390px、`border-radius==0px`、`overflow-y==auto`（authored，复核）

### C-14 返工（→ 014c）— 设置布局契约
- **硬要求**：`settings-page`、`settings-group`、`settings-account-grid`、`settings-zone-grid`。
- 前序判据（014/014b：四分组、删数据保留 e2e、区间边界供 C-8、mobile 2×2 区间网格 AC、密码一致性 unit）**全部保留**。
- pixel-contract AC：
  - id: AC-014c-1
    描述: settings-page 760 居中 + settings-group 单列堆叠契约
    验证方式: e2e-browser
    路径: /settings
    视口: [desktop]
    判定: `[data-vc="settings-page"]` computed `max-width==760px` 且左右 margin 相等（居中）；`[data-vc="settings-group"]` computed `background-color==rgb(18,26,40)`、`border==1px solid rgb(34,48,73)`、`border-radius==12px`、`padding==22px`，四分组纵向单列堆叠（各占满 760px、逐组 top 递增、left 相同）
  - id: AC-014c-2
    描述: settings-account-grid / settings-zone-grid 断点列数
    验证方式: e2e-browser
    路径: /settings
    视口: [mobile, desktop]
    判定: desktop `[data-vc="settings-account-grid"]` computed `grid-template-columns` 解析 2 列、`[data-vc="settings-zone-grid"]` 解析 4 列（`repeat(4,minmax(80px,1fr))`）；mobile account-grid 解析 1 列、zone-grid 解析 2 列（`repeat(2,1fr)`，authored，Validator 实测复核）

## 4. 编号与文件操作（拟落地动作）

1. 落成上 §3 十二条返工到 `contract.md`（更新 C-1/C-3/C-4/C-5/C-6/C-7/C-8/C-9/C-10/C-11/C-12/C-14：追加 `design_rev: 3`、`fidelity: pixel-contract`、`受影响需求` 追加 `00Xc`、追加 pixel-contract AC-* 与 data-vc 硬要求；前序判据保留）。
2. 新增 G-fidelity 到 contract.md「全局验证基线」。
3. `active/` 新建 12 份返工需求 `001c / 003c / 004c / 005c / 006c / 007c / 008c / 009c / 010c / 011c / 012c / 014c`，frontmatter：`status: contracted`、`source_design_rev: 3`、`supersedes: "<原 b 号>"`；对应 `completed/00Xb` 文档**保持原样**（rev 2 历史，不移回、不改写，其 `superseded_by` 由本轮不追改——溯源以新需求 `supersedes` 记）。
4. C-2 / C-13 **不建返工需求**（未命中，保留）。
5. 依赖顺序：001c（全局 chrome/nav 契约）建议先行，其余 pixel-contract 条目相互独立、可并行取件。
6. 更新 `backlog.md`（列 12 条 pixel-contract 返工）、追加 `changelog.md`（design_rev 3、structural/pixel-contract、受影响需求、决议：返工×12 + 保留×2）、更新 `design-state.json`（`last_seen_design_rev: 3`、`last_seen_version: "v3.0"`）、**删除 `.blocked`**。

## 5. 待 Validator 协商的开放点

1. **分析布局锚点归属（A9/A10 → C-3）**：`analysis-main`/`analysis-input` 是分析页外层 flex 三栏 shell + 输入区，未必天然属「会话栏」需求。Planner 主张折进 **C-3**（与 session-rail 同属分析布局，v3.0 变更清单 #4 也把三者并列）。Validator 认可归 C-3，还是要求另立 C 条目 / 归 C-5/C-6？
2. **btn-primary / toast 归属（A20 → C-1）**：这两者是跨页全局 chrome（发送按钮在分析页、toast 在同步成功时）。Planner 折进 **C-1**（全局 chrome/nav 契约），e2e 路径分别取 `/`（btn-primary）与 `/connectors`（toast）。接受？
3. **C-13 文件上传是否需锚点**：§A A15 `connectors-grid` 仅覆盖两张连接器卡；上传区双栏 grid 无独立 data-vc。Planner 主张 **C-13 保留、不返工**（无锚点即无 pixel-contract 契约面）。Validator 若认为上传区也应受 grid 契约约束 → 需设计侧补锚点（回流设计修订），本轮不硬拆。裁定？
4. **C-2 登录页保留**：§A 未声明登录页任何视觉锚点 → C-2 保留、不建 002c。确认登录页视觉不纳入本版 pixel-contract？
5. **authored 值的落成姿态**：mobile/tablet 专属值（气泡 max-width、status-pill connected 边框色、modal mobile 全屏、zone-grid mobile 2 列等）为源码 authored、非实测。Planner 主张**照抄值 + AC 注明「Validator 实测复核」**（同 rev 2 惯例）。接受？还是要求对 authored 值降级为「结构断言」（只验 display/列数/是否全屏，不验精确 rgb/px）？
6. **computed 相等的容差**：颜色 rgb/rgba 要求精确相等；`max-width` 百分比类（气泡 82%/68% 等）实际 computed 为像素——判定按「computed 像素 == round(容器宽 × 百分比)」还是允许 ±1px 容差？Planner 建议 **±1px 容差**（浏览器亚像素舍入），rgb/rgba 精确相等。裁定容差口径。
7. **门禁是否新增**：本版为保真契约硬化，Planner 主张**不新增 e2e 门禁**（沿用 rev 2 门禁#1–#6），pixel-contract AC-* 作为各返工条目的 e2e-browser 验收项即可。接受？

## 6. Ack

- `planner_ack: true`（本文件 frontmatter）——分级（全 structural/pixel-contract）、失效检查（12 返工 + 2 保留）、锚点→C 映射、G-fidelity 新增、逐锚点 e2e-browser computed AC 与 data-vc 硬要求由 Planner 提出。
- `validator_ack: true`（2026-07-13）——逐条复核 AC-* 客观可断言性（computed 属性名/值格式、`[data-vc]` 可命中性、authored 验法、容差口径）完毕，§5 七点全部接受 Planner 主张，裁定与验法细则见 §7。

> 双方 ack 齐备前，Planner **不落成 contract、不建 00Xc、不动 backlog/changelog/design-state、不删 `.blocked`**。

## 7. Validator 裁定与验法细则（validator_ack: true）

> 本段由 Validator 回填（design_rev 3 协商）。Planner `planner_ack: true` 已覆盖分级 / 失效检查 / 锚点→C 映射 / G-fidelity 新增 / 值照抄；本段依 §6 授权补齐「可命中性 · computed 值格式 · authored 验法 · 容差口径」，并裁定 §5 七个开放点。落成时下述验法细则随对应 AC 一并写入 contract（均属「如何测」，非新增验收标准）。

### 7.1 §5 七个开放点裁定（全部接受 Planner 主张）

1. **分析布局锚点 A9/A10 归 C-3**：接受。`analysis-main` / `analysis-input` 与 `session-rail` 同属分析布局 shell，同条目验收，不另立 C。
2. **btn-primary / toast（A20）归 C-1**：接受。属跨页全局 chrome；e2e 路径 `/`（btn-primary）、`/connectors`（toast）成立。
3. **C-13 文件上传保留、不返工**：接受。§A 无上传区 `data-vc`，无 pixel-contract 契约面；若要约束须回流设计补锚点，本轮不硬拆。
4. **C-2 登录页保留、不建 002c**：接受。§A 未声明登录页任何视觉锚点，登录页视觉不纳入本版 pixel-contract。
5. **authored 值落成姿态**：接受。照抄值 + AC 注明「Validator 实测复核」，不降级为纯结构断言；authored 视口以对应视口实测为准复核。
6. **容差口径**：接受。颜色 rgb/rgba 归一后**精确相等**（通道值零容差）；像素及百分比换算像素类 **±1px**（浏览器亚像素舍入）。
7. **不新增 e2e 门禁**：接受。沿用 rev 2 门禁 #1–#6，pixel-contract AC-* 作为各返工条目的 e2e-browser 验收项。

### 7.2 独立复核结论

- **锚点覆盖无遗漏**：§A A1–A20 全部映射到返工 AC（A19 拆 C-11/C-12，A20 归 C-1）；复核 §A 确无 login/upload 锚点，故 C-2/C-13 保留与 §A 一致。
- **值照抄忠实**：逐条比对 §A 与 §3 各 AC 的 rgb/rgba/px/圆角/padding/font-weight，无转写错误（含 A16 三态 pill、A20 五锚点、A5 五区色、A6 三段睡眠色）。
- **[data-vc] 可命中性**：各返工条目均声明 data-vc 镜像硬要求；断言视口与 §A 断点显隐一致（sync-chip/top-nav 仅 desktop、bottom-nav 仅 mobile、session-rail 仅 desktop、activities-card-list 仅 mobile 等）。前置态锚点（toast、connected pill、各弹窗）均带触发前置数据，可命中。

### 7.3 落成时随 AC 生效的验法细则（「如何测」补充）

- **颜色比较**：读 computed 后归一化到 sRGB 8-bit `rgb()/rgba()` 再精确相等比。rev 1 token 将强调色描述为 `oklch(0.65 0.15 230)`；若实现以 `oklch()` 等非 sRGB 语法 authored 且 computed 未序列化为 rgb，先归一再比，契约目标值以 §A 的 rgb/rgba 为准（承接 validator CLAUDE.md「颜色必要时 rgb 归一」+ 裁定 #6）。
- **简写属性比较**（`border` / `padding` / `border-radius`）：computed 简写序列化不稳定时改比对应 longhand 元组（border-width/style/color、四向 padding、四角 radius），空白与 `0`/`0px` 归一后等值判定。
- **max-width 百分比锚点**（AC-006c-3）：computed `max-width` 保留百分比序列化，按 computed 百分比字符串与契约百分比等值比（desktop/wide 实测、tablet/mobile authored 复核）；若实现以像素 authored，则按 `computed_px == round(容器内容宽 × 百分比)` ±1px 比。
- **max-height vh 锚点**（AC-012c-1）：computed `max-height` 解析为像素，按 `computed_px == round(0.86 × window.innerHeight)` ±1px 判定（desktop 800 → **688px**），取代原文「≈0.86×视口高」的模糊表述。
- **hr-zone-bar 五区配色**（AC-008c-2）：§A5 仅锚定容器 `hr-zone-bar`，五区段无独立 `data-vc`；按 `[data-vc="hr-zone-bar"]` 的直接子元素 DOM 顺序取 Z1–Z5 逐段比 computed background-color。落成 AC 判定文案据此写明「按容器内五段子元素顺序」。
- **grid 列数**：显式 `repeat(N,…)` 网格（settings-zone-grid 4/2 列）按 computed 像素轨道串计数判列。**`auto-fit` 网格**（connectors-grid、settings-account-grid、metric grid）computed 会把空轨道折叠为 `0px`，故：列数主张按**已填充列的几何**判定（同排 = 各卡 offsetTop 相等、堆叠 = offsetTop 递增，参 AC-010c-1「两卡同排」/AC-014c-2），并对已填充轨道校验各列像素 ≥ minmax 下限（130/240/80px）；不以原始轨道数为准。

### 7.4 必要修订（补前置数据，保证可命中）

- **AC-003c-2** 增补前置数据：**确保存在 ≥2 会话**（默认种子或先点「+ 新建会话」建一个），使 `session-rail-item-active` 与常态 `session-rail-item` 同屏共存、均可命中；否则仅 1 会话时常态选择器选空，常态半条无法断言。此为可命中性补丁，不改任何契约值。落成 AC-003c-2 时在其 `前置数据` 字段写入此条。

### 7.5 记录不阻断项（次要 authored 差异）

- A20 `top-nav-item-active` tablet padding `7px 9px`（authored）与 top-nav 常态项 color `rgb(138,148,168)` 未落 AC（AC-001c-1 仅断 desktop active）。属次要 authored 增量，本版不强制；后续可增补，不影响 ack。
- A6 睡眠图例色块 9×9px、A5 轨道底色 `#0B1220` 为装饰性附属，未单列 AC，接受。

以上复核完毕，无阻断性歧义。`validator_ack: true`。
