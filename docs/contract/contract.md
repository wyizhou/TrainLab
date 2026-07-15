# Contract — rev 4 历史功能与验收基线

本文件保存 design_rev 1～4 已交付功能和验收标准，供 Codex 在后续开发中防止既有行为回归。

自 2026-07-15 起，项目不再运行 Planner / Executor / Validator 三角色状态机。本文件不再负责调度，也不是 v3.2 的完整视觉标准。当前任务按根 `AGENTS.md` 的“规划 → 实现 → 验收”流程执行；视觉事实以 `design/v3.2/交接/` 为准。

文中仍出现的角色、ack 和返工编号属于历史落成记录，不代表当前还需要启动对应角色。旧提案已归档到 `docs/archive/harness/contract-pending/`。

---

## 条目格式

每条正式条目形如：

```
### C-<n> — <标题>
- design_rev: <落成时的 design_rev>
- impact: cosmetic | structural | scope
- 受影响需求: 003, 003b
- 决议: 保留 | 返工 | 废弃 | 新增
- 可验证标准:
  - [ ] <一条可客观判定通过/失败的标准>
  - [ ] <做什么 / 不做什么 / 如何 test / 如何 lint>
```

**每条可验证标准必须标注验证方式**，否则验收阶段无法客观判断。凡涉及浏览器交互的标准，用如下逐条元数据（规划阶段就把话说清，「卡片要好看」这种无法标 `e2e-browser` 的表述不得作为完成条件）：

```yaml
- id: AC-<需求号>-<序>
  描述: ConnectorCard 在 token 过期时展示"重新授权"按钮
  验证方式: e2e-browser        # unit | lint | e2e-browser | visual | manual
  路径: /connectors            # e2e-browser 必填
  视口: [desktop, tablet]      # e2e-browser 必填，取自 G-resp 断点
  前置数据: fixture:expired-token
  判定: 按钮可见且可点击，点击后导航至 /auth/reauth
  fixture: uploads/xxx.fit     # 该标准依赖的测试资产（若有）
  fixture_owner: implementation # human | implementation —— 谁负责把 fixture 放进 repo
```

- `验证方式` 取值：`unit` / `lint` → 跑 vitest / eslint；`e2e-browser` → Playwright，按 `路径` / `视口` / `前置数据` 执行；`visual` / `manual` → 记为待人工确认。
- `fixture_owner: human` 表示该资产须由人在实现前放进 repo；`fixture_owner: implementation` 表示在实现阶段产出。规划阶段必须先检查所需 fixture 是否存在。

---

## 全局验证基线（G-*）

每条正式条目**默认继承**下列基线；条目正文只写增量，不重复 G-*。命令以工程 `package.json` scripts 为准。

- **G-lint**：`npm run lint`（ESLint + Prettier check + Stylelint）0 error、0 warning。
- **G-type**：`npm run typecheck`（`tsc --noEmit`）0 error。
- **G-unit**：`npm run test`（Vitest run）全绿；条目新增/触及组件须有对应 `*.test.tsx`（Testing Library）。
- **G-e2e**：`npm run e2e`（Playwright）条目指定 spec 通过（仅标注 e2e 的条目要求，见下「E2E 门禁冒烟集」）。
- **G-token**：颜色/圆角/间距 token 集中定义于单一模块（如 `src/design/tokens.ts` 及/或 CSS 变量）；ESLint（JS/TS 内联样式）+ Stylelint（CSS）对 token 文件之外的裸 `#hex` / `rgb()` / `oklch()` / 裸像素间距值报 **error**。`npm run lint` 0 error 即判 G-token 通过；抽验 token 文件外裸值命中数须为 0。**不引入视觉快照测试。**（**design_rev 4 升级**：token 唯一事实源迁至 v3.1 三表，off-scale 间距口径〔裁定 (a)〕与 typography/结构尺寸例外边界见下「G-token 权威源与 token 表（design_rev 4 补全）」节。）
- **G-nums**：所有数值展示走 `font-variant-numeric: tabular-nums`；数值列用 ui-monospace。
- **G-resp（design_rev 2 升级）**：断点矩阵由 rev 1 的「平板 `<980px`」升级为四档 **mobile `<640` / tablet `640–979` / desktop `980–1439` / wide `≥1440`**（`window.innerWidth` 驱动，resize 即时生效）。新增硬不变量：**全部 7 个可达路由（`/login`、`/`、`/activities`、`/activities/1`、`/health`、`/connectors`、`/settings`）在所有断点下 `document.documentElement.scrollWidth <= window.innerWidth`（无横向溢出）**。基准视口：mobile 390×844 / tablet 768×1024 / desktop 1280×800 / wide 1920×1080。#2 视觉保真的精确 token/圆角/间距值经 G-token（token 文件外裸值 lint error）承接；结构性/重排参数（宽度、display、grid 列、圆角非对称、padding 分级）由各条目 e2e-browser 承接。
- **G-mock**：同步、下载、AI 回复、API 测试均为前端模拟，不发真实网络请求（设置页 AI「测试连接」真实探测可选，默认亦 mock）。
- **G-fidelity（新增，design_rev 3）**：原型（`design/v3.0/运动分析系统.dc.html`）为**像素级保真契约源**，非结构示意图。设计文档 §A 每个 `data-vc` 锚点的契约属性以**浏览器 computed 值**为准（rgb/rgba、px）。命中锚点的返工条目必须：(1) 把 `data-vc="<锚点名>"` 镜像到实现对应组件的**根元素**（否则 `[data-vc=…]` 选空、断言全废）；(2) 命中锚点的 computed 契约属性与 §A 值**直接相等**。验法边界：pixel-contract 契约属性走 **e2e-browser computed-style 断言**；纯 token 集中定义仍由 **G-token** 承接，**不引入视觉快照测试**。锚点名一经落成不再变更。v3.2 开始还必须结合整页截图与几何基线检查。

技术栈（用户 2026-07-10 确认）：**React + TypeScript + Vite**（纯前端，无后端）；验证链 **Vitest + Testing Library + ESLint/Prettier/Stylelint + Playwright**。

## G-token 权威源与 token 表（design_rev 4 补全）

> design_rev 4（TrainLab v3.1）经历史提案 `docs/archive/harness/contract-pending/design-rev-4.md` 落成。本节补全 G-token 的**权威源与口径边界**——**不新增/不修改任何 pixel-contract AC 判定值（零 AC 值变更）**。v3.1 性质：对 rev-3 残缺 token 交底的补全纠错，零视觉设计变更。

**权威源迁移（唯一事实源）**：颜色/圆角/间距 token 的唯一事实源为 `design/v3.1/交接/v3.1-设计文档.md` 三表——表 (a) 颜色 / 表 (b) 圆角 / 表 (c) 间距。token 模块（`src/design/tokens.ts` 及/或 CSS 变量）的值须 **1:1 对齐三表 computed 值**。v3.0「色板/间距 token 以 v2.0 为准」「无 token 值变更」的表述**作废**——其自相矛盾（既要求实现产出 rgb(66,146,224) 等 pixel-contract 值，又称 token 以 v2.0 为准、无值变更，而 v2.0 token 基础无法产出这些值）。下游一律以 v3.1 三表实测 rgb/px 为准。

**语义色 oklch→rgb 固化（有意为之，非笔误）**：accent 及 success/warn/danger 由 v2.0 的 `oklch()` 定义固化为原型实测 rgb——accent `#4292E0`（rgb(66,146,224)）、success `#3FBF8F`（rgb(63,191,143)）、warn `#E0A040`（rgb(224,160,64)）、danger `#E06060`（rgb(224,96,96)）。v2.0 oklch 渲染值 ≠ 原型实测（accent oklch 渲染为 rgb(0,158,216)，原型实为 #4292E0）；本固化为实现向原型对齐，**与既有各 AC 目标值一致**，非目标值变更。

**补齐的 token（下游据以集中定义，值见 v3.1 三表，不改任何 AC 判定值）**：
- 颜色：三种边框色 borderPanel(rgb(34,48,73)) / borderInput(rgb(42,58,85)) / borderWeak(rgb(28,39,57)) 及 borderToast(rgb(58,78,112))、panelNav(rgb(13,20,32))、accentDeep(rgb(46,92,158))、accentText(rgb(94,163,232))、textFaint(rgb(92,104,126))、sleepRem(rgb(143,193,242))、toastBg(rgb(26,36,54))、scrim(rgb(4,8,14))、hoverRow(rgb(22,32,47))，及派生半透明 accent@0.12 / accent@0.16 / accent@0.18、success@0.12 / success@0.35、danger@0.10 / danger@0.40、textMuted@0.10、scrim@0.72。
- 圆角：radiusHairline(2) / radiusXs(3) / **radiusZone(4，hr-zone-bar，AC-008c-2)** / radiusSm(6) / radiusInput(8) / radiusCardSm(10) / radiusBtnPrimary(10) / radiusCard(12) / radiusPanelLg(14) / radiusPill(99)，及非对称值 radiusBubbleAI(`14 14 14 4`) / radiusBubbleUser(`14 14 4 14`) / radiusSleepDeep(`0 0 3 3`) / radiusSleepRem(`3 3 0 0`)。
- 间距：表 (c) 全部 padding/gap/margin，含 **padCardListItem(`14 16`，activities-card-list 单卡)** 使 A14 无裸值。

**top-nav-item-active 底 = accent@0.16（承接历史复核）**：v3.1 表 (a) 派生半透明「用途」列把 `top-nav-item-active 底` 误列在 accent@0.12 下；以 §A20 与 **AC-001c-1** 为准，top-nav-item-active 底 = **accent@0.16 = rgba(66,146,224,0.16)**。两 alpha token 值均在表内、§A（权威锚点契约）与 contract 目标一致，故**非 AC 值变更**，仅「用途」列注记错位。下游补 token 时勿据派生表被带偏到 @0.12。

**off-scale 间距口径（裁定 (a)：全部纳入具名 token，口径不放宽）**：v3.1 表 (c) 照实交底的手调 off-scale 值——**5 / 9 / 11 / 13 / 18 / 22px 及 6.5px gap**（如 padChip `5 13`、padRailItem `9 10`、padBtnPrimary/toast `11 22`、padBubbleAI `13 16`、padMainTablet `18 16`、padGroup `22`、gapLegend `6.5`）——**一律作为具名 space token 定义进 token 模块**（v3.1 已给名）。G-token 口径**不放宽**：继续对 token 文件之外的裸像素间距值报 **error**，抽验 token 文件外裸间距命中数须为 **0**。「凑不进 8pt scale」不是「不能当 token」的理由——具名 token 允许任意值，`padChip='5px 13px'` 合法。gapLegend 6.5px 作具名 token 集中定义即满足 G-token；当前无 AC 断言其 computed 值，不涉逐像素判定；若后续新增，按 pixel-contract「像素类 ±1px」容差判定（6.5px 亚像素舍入落入 ±1px）。

**Token 化范围外例外（不 lint，但不等于不验）**：以下两类本版**不纳入 token 化**，§A 中以字面值出现属**显式例外**，G-token **不 lint**：
- **Typography**（字号/字重/行高）：如 `font-size: 13px/11px`、`font-weight: 600/700`。裸 font-size / font-weight **不算 G-token 违规**。
- **固定结构尺寸**（width/height/min-width/border-width 等）：如 session-rail `width:212px`、bottom-nav `height:60px`、modal `width:390/620px`、settings-page `max-width:760px`、analysis-main `max-width:1200px`、activities-table 内层 `min-width:960px`、边框宽 `1px/2px/3px`。裸结构尺寸**不算 G-token 违规**。
- 两类的具体值仍由既有各 pixel-contract **e2e-browser computed AC** 逐条锁死（如 AC-003c-1 `width==212px`、AC-006c-1 含 `font-size`、AC-010c-2 `border-width==1px`）——**不 token 化 ≠ 不验**，验的通道是 e2e computed 断言而非 lint。

## pixel-contract 验法细则（design_rev 3，随各 AC 生效）

下列为 pixel-contract AC-* 的「如何测」补充（非新增验收标准），落成时随对应 AC 一并生效（历史依据见 `docs/archive/harness/contract-pending/design-rev-3.md` §7.3/7.4）：

- **容差口径**：颜色 rgb/rgba 归一到 sRGB 8-bit 后**精确相等**（通道零容差）；像素及百分比换算像素类 **±1px**（浏览器亚像素舍入）。
- **颜色比较**：读 computed 后归一化到 sRGB 8-bit `rgb()/rgba()` 再比；若实现以 `oklch()` 等非 sRGB 语法 authored、computed 未序列化为 rgb，先归一再比，目标值以 §A 的 rgb/rgba 为准。
- **简写属性比较**（`border` / `padding` / `border-radius`）：computed 简写序列化不稳定时改比对应 longhand 元组（border-width/style/color、四向 padding、四角 radius），`0`/`0px` 与空白归一后等值判定。
- **grid 列数**：显式 `repeat(N,…)` 网格（settings-zone-grid）按 computed 像素轨道串计数判列；**`auto-fit` 网格**（connectors-grid、settings-account-grid、metric grid）computed 会把空轨道折叠为 `0px`，故按**已填充列几何**判列（同排＝各卡 offsetTop 相等、堆叠＝offsetTop 递增），并对已填充轨道校验各列像素 ≥ minmax 下限（130 / 240 / 80px），不以原始轨道数为准。
- **authored 值**：mobile/tablet 专属 authored 值照抄落成，AC 注明「验收阶段实测复核」，复核以对应视口实测为准，不降级为纯结构断言。

## E2E 门禁冒烟集（design_rev 2）

`npm run e2e` 下列为**门禁必过**冒烟集。

rev 1 的 5 条门禁**不增删**，语义随各返工条目沿用：
1. 登录：错误验证码被拒 → 正确输入登录成功跳分析页（C-2）。门禁#1 在双模导航下仍以「错误验证码被拒 → 正确登录跳分析页」为准（与导航模式无关）。
2. 连接器 2FA 两段式授权直到接入成功（C-11）。
3. 双账号合并：触发冲突 → 逐组选择 → 合并后横幅消失（C-12）。
4. 运动详情：降采样曲线 ⇄ 逐秒表 模式切换（C-8）。
5. 分析对话生成图表卡片：发送分析提问 → AI 气泡文本先到 → 卡片加载→折叠就绪 → 展开显示折线图（C-5＋C-6 联合流）。

**新增门禁#6 —— 响应式无溢出冒烟**（升级后 G-resp 的门禁化）：
- **无横向溢出**：遍历全部 **7** 个可达路由（`/login`、`/`、`/activities`、`/activities/1`、`/health`、`/connectors`、`/settings`，均稳定可达；`/activities/1` 取运动列表首条「晨间轻松跑」），在 4 视口（390 / 768 / 1280 / 1920）断言 `document.documentElement.scrollWidth <= window.innerWidth`。
- **双模导航**（仅对 **6** 个 in-app 路由，**排除 `/login`**——`/login` 渲染在 `AppLayout` 之外、无任何导航 chrome，`src/App.tsx:16` 已证实）：mobile 断言底部 tab 5 项可见、顶部导航不在 DOM；desktop 断言顶部导航在、底部 tab 不在。
- **`/login` 单独断言**（避免误判）：mobile 与 desktop 下 `/login` 均**无** top-nav、**无**底部固定 tab（login 页两种导航都不应存在）。

此外各条目正文标注的 `e2e` 行须各自通过（C-1 五路由、C-3 会话增改删至空、C-7 筛选+翻页+批量计数）。**C-4 / C-9 / C-10 / C-13 / C-14 不要求「功能 e2e」，但其响应式 `e2e-browser` 断言（下列各条 AC-*）为该条目验收组成部分**——响应式是 v2.0 的交付主体，必须自动验，不下放 visual/manual。

---

## 正式条目

> design_rev 2（TrainLab v2.0：全设备响应式 + 视觉保真返工 + 删除数据保留）经历史提案 `docs/archive/harness/contract-pending/design-rev-2.md` 落成。
> 分级：structural + scope（混合，最高 scope）。失效检查：`active/` 空、`completed/` 001–014 全部 `verified`（`source_design_rev: 1`），全部命中变更清单 → 走**返工已 verified 流程**：不动 `completed/` 原文档（rev 1 历史事实），在 `active/` 新建 001b–014b 返工需求。溯源见 `changelog.md`。
> 下列各条继承升级后 G-*；正文保留 rev 1 功能判据（决议为「返工」，功能面沿用）并叠加 v2.0 响应式/保真增量。新组件 BottomTabBar / ActivityCardList 是既有 C-1 / C-7 的移动端形态，折进对应返工条目，不另开新 C 条目。

### C-1 — 全局响应式基线 + 双模导航（返工）
- design_rev: 3
- impact: structural
- fidelity: pixel-contract
- 受影响需求: 001, 001b, 001c
- 决议: 返工
- 可验证标准（继承升级后 G-*）：
  - [ ] rev 1 功能判据保留：Vite+React+TS 工程 `npm run build` 成功、`npm run dev` 起服务；顶部导航含五项且顺序为 **分析(默认页) / 运动记录 / 健康记录 / 连接器 / 设置**，`/` 默认路由指向分析页；深色视觉 token 集中定义（背景 #0A0F18 / 面板 #121A28 / 深面板 #0B1220 / 强调 accent = **#4292E0**（rgb(66,146,224)，design_rev 4 由 v2.0 `oklch` 固化为原型实测 rgb，见「G-token 权威源与 token 表」节）等），全局 `tabular-nums` 生效（G-token / G-nums）。
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

- **pixel-contract 增量（design_rev 3，返工 001c；前序 rev 2 判据全部保留）**：
  - [ ] **硬要求（data-vc 镜像）**：实现时把 `top-nav`、`top-nav-item-active`、`sync-chip`、`bottom-nav`、`bottom-nav-item-active`、`toast`、`btn-primary`（发送按钮为代表）镜像到对应组件根元素；否则下列 `[data-vc=…]` 断言全废。
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

### C-2 — 登录页响应式 + 保真（返工）
- design_rev: 2
- impact: structural
- 受影响需求: 002, 002b
- 决议: 返工（轻：无功能/API 变更，仅保真 + 移动视口再验）
- 可验证标准（继承升级后 G-*）：
  - [ ] rev 1 功能判据保留：居中卡片，字段 = 用户名 / 密码 / 4 位验证码（点击刷新）；回车提交；错误提示可见；无营销元素。演示校验：任意用户名 + 密码 ≥4 位 + 验证码正确 → 进入分析页；任一不满足 → 报错不跳转。
  - [ ] e2e（门禁#1）：错误验证码被拒 → 正确输入登录成功跳分析页。
  - id: AC-002b-1
    描述: mobile 登录卡由外层 padding 收窄、无横向溢出
    验证方式: e2e-browser
    路径: /login
    视口: [mobile]
    判定: 卡片 offsetWidth = 342（390−48）；`documentElement.scrollWidth <= 390`

### C-3 — 分析·会话栏响应式（返工）
- design_rev: 3
- impact: structural
- fidelity: pixel-contract
- 受影响需求: 003, 003b, 003c
- 决议: 返工
- 可验证标准（继承升级后 G-*）：
  - [ ] rev 1 功能判据保留：桌面左侧 212px 会话栏（新建会话主按钮、会话项含名称 + 消息数、选中态左侧强调色条）；行内重命名（Enter 确认 / Esc 取消）；删除当前会话切到第一个；删空自动新建。
  - [ ] e2e：新建 → 重命名 → 删除至空自动新建 完整链路。
  - id: AC-003b-1
    描述: desktop 左栏 212px aside；mobile/tablet 降级为顶部下拉
    验证方式: e2e-browser
    路径: /
    视口: [mobile, tablet, desktop]
    判定: desktop 存在 offsetWidth≈212 的会话 aside；mobile/tablet 该 aside 不存在且存在会话 `select` + 新建按钮

- **pixel-contract 增量(design_rev 3，返工 003c；前序 rev 2 判据全部保留)**：
  - [ ] **硬要求（data-vc 镜像）**：`session-rail`、`session-rail-item`、`session-rail-item-active`、`analysis-main`、`analysis-input` 镜像到对应组件根元素。
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
    前置数据: 确保存在 ≥2 会话（默认种子或先点「+ 新建会话」建一个），使 `session-rail-item-active` 与常态 `session-rail-item` 同屏共存、均可命中（承接 §7.4 可命中性补丁）
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

### C-4 — 分析·范围选择器响应式 + 保真（返工）
- design_rev: 3
- impact: structural
- fidelity: pixel-contract
- 受影响需求: 004, 004b, 004c
- 决议: 返工（轻：逻辑无变更，仅移动重排 + 保真）
- 可验证标准（继承升级后 G-*；不要求功能 e2e，unit 覆盖 + 响应式 AC-*）：
  - [ ] rev 1 功能判据保留：3(默认)/7/15/30 天胶囊；「选择运动 (n)」展开勾选列表，勾选后覆盖时间范围；「附带健康记录」「附带习惯记录」两开关默认均开；底部实时显示当前范围摘要（随选择更新）。
  - [ ] unit：切换胶囊 / 勾选运动 / 开关 → 摘要与生效范围随之更新。
  - id: AC-004b-1
    描述: mobile 勾选项组（附带健康/习惯）flex-wrap 换行、无横向溢出
    验证方式: e2e-browser
    路径: /
    视口: [mobile]
    判定: 「附带健康记录」「附带习惯记录」两开关不在同一水平行（第二项 top 大于第一项）；`documentElement.scrollWidth <= 390`

- **pixel-contract 增量（design_rev 3，返工 004c；前序 rev 2 判据全部保留）**：
  - [ ] **硬要求（data-vc 镜像）**：`scope-chip`、`scope-chip-selected` 镜像到对应组件根元素。
  - id: AC-004c-1
    描述: scope-chip 选中 vs 常态配色
    验证方式: e2e-browser
    路径: /
    视口: [desktop]
    判定: `[data-vc="scope-chip-selected"]` computed `background-color==rgba(66,146,224,0.18)`、`border==1px solid rgb(66,146,224)`、`color==rgb(94,163,232)`、`border-radius==99px`、`padding==5px 13px`；`[data-vc="scope-chip"]`（常态）computed `background-color==rgb(11,18,32)`、`border==1px solid rgb(42,58,85)`、`color==rgb(138,148,168)`

### C-5 — 分析·图表卡片响应式（返工）
- design_rev: 3
- impact: structural
- fidelity: pixel-contract
- 受影响需求: 005, 005b, 005c
- 决议: 返工
- 可验证标准（继承升级后 G-*）：
  - [ ] rev 1 功能判据保留：四态可判定——**加载**（spinner + shimmer，回复文本先到、约 1.1s 后卡片就绪）/ **空态**（范围内 <2 次运动，图标+文案，不可展开）/ **折叠**（📊+标题+一行等宽摘要+展开）/ **展开**（轴说明行 + 340×112 折线图，Y 轴 3 档、X 轴首/中/末刻度 + 逐条数据行）。unit：<2 次运动 → 空态；≥2 次 → 可进入折叠/展开。
  - [ ] **视觉层级判据更新**：用户消息（实心蓝右对齐）> AI 气泡（面板色左对齐）> 卡片（气泡内下沉层 #0B1220）。**删除「AI 气泡最小宽 46%」**（移交 C-6 气泡返工；见 C-6）。
  - [ ] e2e（门禁#5，与 C-6 联合）：分析提问 → 文本先到 → 卡片加载→折叠 → 展开显示折线图。
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

- **pixel-contract 增量（design_rev 3，返工 005c；前序 rev 2 判据全部保留）**：
  - [ ] **硬要求（data-vc 镜像）**：`chart-card` 镜像到图表卡片组件根元素。
  - id: AC-005c-1
    描述: chart-card 容器视觉契约（下沉层 #0B1220）
    验证方式: e2e-browser
    路径: /
    视口: [desktop]
    前置数据: 在分析页发送一条会生成图表卡片的分析提问，待卡片就绪（折叠态）
    判定: `[data-vc="chart-card"]` computed `background-color==rgb(11,18,32)`、`border==1px solid rgb(42,58,85)`、`border-radius==10px`、`overflow==hidden`；层级校验：其值 #0B1220 深于 AI 气泡 #121A28

### C-6 — 分析·对话气泡返工（返工）
- design_rev: 3
- impact: structural
- fidelity: pixel-contract
- 受影响需求: 006, 006b, 006c
- 决议: 返工
- 可验证标准（继承升级后 G-*）：
  - [ ] rev 1 功能判据保留：AI 回复以 HTML 渲染（表格 / 有序列表），含「计划」提问输出 7 天课表表格，附带健康/习惯时追加解读段落；隐藏系统提示词随每次请求发送、不显示在对话流，设置 → AI 接口可查看/收起；HTML 渲染做转义/白名单，禁止注入脚本执行（安全基线）。unit：mock 分析请求 → 含数据表格与结论；系统提示词不入消息流 DOM；注入 `<script>` 不执行。
  - [ ] e2e：见 C-5 门禁#5 联合流。
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

- **pixel-contract 增量（design_rev 3，返工 006c；前序 rev 2 判据全部保留）**：
  - [ ] **硬要求（data-vc 镜像）**：`chat-bubble-ai`、`chat-bubble-user` 镜像到对话气泡组件根元素。
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
    判定: `[data-vc="chat-bubble-ai"]` computed `max-width` = desktop 容器 82%（实测）/ tablet 92%（authored，验收阶段实测复核）/ mobile 100%（authored，复核）；`[data-vc="chat-bubble-user"]` = desktop 68%（实测）/ tablet 80%（authored）/ mobile 94%（authored）。验法：computed 保留百分比序列化则按百分比等值比；若实现以像素 authored 则按 `computed_px == round(容器内容宽 × 百分比)` ±1px 比（承接 §7.3 max-width 细则）

### C-7 — 运动列表响应式（返工）
- design_rev: 3
- impact: structural
- fidelity: pixel-contract
- 受影响需求: 007, 007b, 007c
- 决议: 返工
- 可验证标准（继承升级后 G-*）：
  - [ ] rev 1 功能判据保留：列 = 复选框/日期/类型色点/名称/距离/时长/平均心率/配速或功率/来源(佳明CN·佳明国际·FIT上传)/单条 FIT 下载；类型筛选胶囊（全部/跑步/骑行/游泳/力量/越野跑）实时过滤；分页 20(默认)/50/100；批量「下载选中 FIT (n)」计数随勾选更新（下载模拟）。
  - [ ] e2e：筛选 + 翻页 + 批量勾选计数。
  - id: AC-007b-1
    描述: mobile 表格隐藏、渲染卡片列；desktop 反之
    验证方式: e2e-browser
    路径: /activities
    视口: [mobile, desktop]
    判定: mobile 下 `min-width:960px` 表格容器 computed display=none，卡片数 = min(每页条数, 剩余条数)；desktop 下表格 display≠none 且无卡片列；两视口均无横向溢出（表格容器内横滚不外溢页面）

- **pixel-contract 增量（design_rev 3，返工 007c；前序 rev 2 判据全部保留）**：
  - [ ] **硬要求（data-vc 镜像）**：`activities-table`、`activities-card-list`、`type-chip`、`type-chip-selected` 镜像到对应组件根元素。
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

### C-8 — 运动详情响应式（返工）
- design_rev: 3
- impact: structural
- fidelity: pixel-contract
- 受影响需求: 008, 008b, 008c
- 决议: 返工
- **验收前置（承接 rev 1 §7.3，已满足）**：真实样本 `tests/fixtures/614797758_ACTIVITY.fit`（`fixture_owner: human`）已在 repo（复核 245KB 真实 FIT），无新增 human fixture、无 blocked 风险；FIT 字段白名单断言（≥8 项）判据原样保留。
- 可验证标准（继承升级后 G-*）：
  - [ ] rev 1 功能判据保留：字段集 = 真实 FIT（`tests/fixtures/614797758_ACTIVITY.fit`，`@garmin/fitsdk` 解析）∩ 佳明 Connect 详情页，列表第一条「晨间轻松跑」为该真实数据，缺失字段显示「--」；指标分区各标注 FIT 字段名，训练效果为 FIT 原始存储值（非系统计算）；时序双模式（降采样曲线：跑步 8 图/骑行 6/游泳 2/力量 1，Y 轴 3 档 + X 轴 5 档 + 来源字段标注 ⇄ 逐秒数据表：分页 20/50/100，行数 = 运动秒数）；心率区间条形图（`time_in_hr_zone`）边界取自设置页区间设定；Laps 分段表含平均功率列 + 「下载 FIT 文件」主按钮（模拟）。
  - [ ] **FIT 字段白名单断言（unit，首条「晨间轻松跑」解析值 == 佳明详情，≥8 项）**：`sport`(+`sub_sport` 若有) / `start_time`(时间戳精确相等) / `total_timer_time` / `total_distance` / `avg_heart_rate` / `max_heart_rate` / `total_calories` / `avg_speed`(→配速换算一致)；`total_ascent`（若详情展示则纳入）；`total_training_effect` / `total_anaerobic_training_effect` 断言为 FIT 原始存储值。容差：整数/时间戳精确相等，浮点按展示精度四舍五入相等；缺失字段渲染「--」可不参与断言。
  - [ ] e2e（门禁#4）：降采样曲线 ⇄ 逐秒表 模式切换。
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

- **pixel-contract 增量（design_rev 3，返工 008c；前序 rev 2 判据全部保留）**：
  - [ ] **硬要求（data-vc 镜像）**：`metric-card`、`hr-zone-bar` 镜像到对应组件根元素。
  - id: AC-008c-1
    描述: metric-card 视觉契约 + grid 自适应
    验证方式: e2e-browser
    路径: /activities/1
    视口: [desktop]
    判定: `[data-vc="metric-card"]` computed `background-color==rgb(18,26,40)`、`border==1px solid rgb(34,48,73)`、`border-radius==10px`、`padding==14px`；所在 grid 意图为 `repeat(auto-fit,minmax(130px,1fr))`——按已填充列几何判定（各列像素 ≥130px；参 pixel-contract 验法细则「grid 列数」auto-fit 段）
  - id: AC-008c-2
    描述: hr-zone-bar 高度/圆角 + 五区配色
    验证方式: e2e-browser
    路径: /activities/1
    视口: [desktop]
    判定: `[data-vc="hr-zone-bar"]` computed `height==16px`、`border-radius==4px`；五区无独立 data-vc，按 `[data-vc="hr-zone-bar"]` 直接子元素 DOM 顺序取 Z1–Z5 逐段比 computed background-color，依次 Z1 `rgb(92,104,126)` / Z2 `rgb(66,146,224)` / Z3 `rgb(63,191,143)` / Z4 `rgb(224,160,64)` / Z5 `rgb(224,96,96)`（承接 §7.3 hr-zone-bar 细则）

### C-9 — 健康记录响应式（返工）
- design_rev: 3
- impact: structural
- fidelity: pixel-contract
- 受影响需求: 009, 009b, 009c
- 决议: 返工
- 可验证标准（继承升级后 G-*；不要求功能 e2e，unit 覆盖 + 响应式 AC-*）：
  - [ ] rev 1 功能判据保留：五子标签（睡眠：深/浅/REM 堆叠柱 + 明细含静息心率 / 体重：曲线 + 体重/体脂/肌肉/水分 / 静息心率 / HRV / 习惯）；习惯 = 日期选择（默认当天）+ 已记录计数，早/中/晚/全天四组因子胶囊勾选按日期存储；数据量级——体重 / 静息心率 / HRV 明细各 **≥30 行**，睡眠 **≥14 行**，习惯抽样某日四组因子可勾选并计入已记录计数，各表分页含 20/50/100 三档。
  - [ ] unit：对上述行数下界与分页档位断言；渲染无错。
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

- **pixel-contract 增量（design_rev 3，返工 009c；前序 rev 2 判据全部保留）**：
  - [ ] **硬要求（data-vc 镜像）**：`sleep-chart-bar-deep`、`sleep-chart-bar-light`、`sleep-chart-bar-rem`、`health-tab`、`health-tab-selected` 镜像到对应组件根元素。
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

### C-10 — 连接器卡片响应式（返工）
- design_rev: 3
- impact: structural
- fidelity: pixel-contract
- 受影响需求: 010, 010b, 010c
- 决议: 返工
- 可验证标准（继承升级后 G-*；不要求功能 e2e，unit 覆盖 + 响应式 AC-*）：
  - [ ] rev 1 功能判据保留：状态集合齐全（已连接绿 / 未连接灰+连接账号 / 同步中按钮 spinner / 同步失败红+错误块含失败时间+原因、按钮变「重试同步」）；显示上次成功同步时间、已同步数量、自动同步间隔（30 分钟/1 小时/6 小时/仅手动）；演示初始态 = 中国区同步失败(ETIMEDOUT)、国际区未连接。
  - [ ] unit：四种状态各渲染对应胶囊与按钮文案。
  - id: AC-010b-1
    描述: 卡片 grid `minmax(min(320px,100%),1fr)`，mobile 单列堆叠不溢出
    验证方式: e2e-browser
    路径: /connectors
    视口: [mobile, desktop]
    判定: mobile 两连接器卡纵向堆叠（第二卡 top 大于第一卡）；desktop 两卡同排（第二卡 top == 第一卡、left 不同）；两视口 `documentElement.scrollWidth <= innerWidth`

- **pixel-contract 增量（design_rev 3，返工 010c；前序 rev 2 判据全部保留）**：
  - [ ] **硬要求（data-vc 镜像）**：`connectors-grid`、`connector-card`、`status-pill-connected`、`status-pill-failed`、`status-pill-disconnected` 镜像到对应组件根元素。
  - id: AC-010c-1
    描述: connectors-grid 列数断点 + connector-card 视觉契约
    验证方式: e2e-browser
    路径: /connectors
    视口: [mobile, desktop]
    判定: desktop `[data-vc="connectors-grid"]` computed `display==grid`、按已填充列几何解析为 2 列（两卡同排，参 auto-fit 验法细则）、`gap==16px`；mobile 解析为 1 列（堆叠）。`[data-vc="connector-card"]` computed `background-color==rgb(18,26,40)`、`border==1px solid rgb(34,48,73)`、`border-radius==12px`、`padding==20px`
  - id: AC-010c-2
    描述: status-pill 三态配色
    验证方式: e2e-browser
    路径: /connectors
    视口: [desktop]
    前置数据: 演示初始态为「中国区同步失败 / 国际区未连接」；connected 态须触发一次同步成功后采集（承接 AC-001c-4 前置流程）
    判定: 公共 `border-radius==99px`、`padding==4px 12px`、`font-size==11px`、`border-width==1px`；`status-pill-connected` `color==rgb(63,191,143)`、`background-color==rgba(63,191,143,0.12)`、`border-color==rgba(63,191,143,0.35)`（authored，验收阶段实测复核）；`status-pill-failed` `color==rgb(224,96,96)`、`background-color==rgba(224,96,96,0.1)`、`border-color==rgba(224,96,96,0.4)`；`status-pill-disconnected` `color==rgb(138,148,168)`、`background-color==rgba(138,148,168,0.1)`、`border-color==rgb(42,58,85)`

### C-11 — 授权弹窗 mobile 全屏（返工）
- design_rev: 3
- impact: structural
- fidelity: pixel-contract
- 受影响需求: 011, 011b, 011c
- 决议: 返工
- 可验证标准（继承升级后 G-*）：
  - [ ] rev 1 功能判据保留：字段 = 账号 / 密码 / 「启用了 2FA」勾选，未勾选一次登录接入；勾选 2FA 时第一次登录校验账密 → 出现 6 位验证码输入区（勾选锁定）→ 再次登录后台（模拟）验证，校验与 busy 态齐全。
  - [ ] e2e（门禁#2）：2FA 两段式流程直到接入成功。
  - id: AC-011b-1
    描述: mobile 弹窗全屏化，desktop 居中定宽
    验证方式: e2e-browser
    路径: /connectors
    视口: [mobile, desktop]
    前置数据: 打开 2FA 授权弹窗
    判定: mobile 面板 offsetWidth=390（=视口宽）、computed `border-radius=0px`；desktop 面板宽 390px、居中、`border-radius=14px`

- **pixel-contract 增量（design_rev 3，返工 011c；前序 rev 2 判据全部保留）**：
  - [ ] **硬要求（data-vc 镜像）**：`modal-connector-auth`、`modal-overlay` 镜像到对应组件根元素。
  - id: AC-011c-1
    描述: modal-connector-auth desktop 居中定宽 vs mobile 全屏
    验证方式: e2e-browser
    路径: /connectors
    视口: [mobile, desktop]
    前置数据: 打开 2FA 授权弹窗
    判定: desktop `[data-vc="modal-connector-auth"]` computed `width==390px`、`border==1px solid rgb(42,58,85)`、`border-radius==14px`、`padding==24px`、`background-color==rgb(18,26,40)`；mobile computed `width` == 视口宽 390px、`border-radius==0px`、`border-style==none`、`overflow-y==auto`（authored，验收阶段实测复核）。`[data-vc="modal-overlay"]` computed `position==fixed`、`background-color==rgba(4,8,14,0.72)`

### C-12 — 合并弹窗 mobile 全屏（返工）
- design_rev: 3
- impact: structural
- fidelity: pixel-contract
- 受影响需求: 012, 012b, 012c
- 决议: 返工
- 可验证标准（继承升级后 G-*）：
  - [ ] rev 1 功能判据保留：去重规则按「开始时间 + 时长」自动去重、来源标注保留；无法自动判定 → 页顶警示横幅「发现 n 组疑似重复运动」+「处理重复」→ 弹窗逐组选「保留中国区 / 保留国际区」→ 确认合并；演示连接国际区后出现 2 组冲突。
  - [ ] e2e（门禁#3）：触发冲突 → 逐组选择 → 合并后横幅消失。
  - id: AC-012b-1
    描述: mobile 合并弹窗全屏，desktop 居中 620px
    验证方式: e2e-browser
    路径: /connectors
    视口: [mobile, desktop]
    前置数据: 触发冲突并打开合并弹窗
    判定: mobile 面板 offsetWidth=390、`border-radius=0px`、内部可 overflow-y 滚动；desktop 面板宽 620px、居中、`border-radius=14px`

- **pixel-contract 增量（design_rev 3，返工 012c；前序 rev 2 判据全部保留）**：
  - [ ] **硬要求（data-vc 镜像）**：`modal-conflict`、`modal-overlay` 镜像到对应组件根元素。
  - id: AC-012c-1
    描述: modal-conflict desktop 620px 居中 vs mobile 全屏
    验证方式: e2e-browser
    路径: /connectors
    视口: [mobile, desktop]
    前置数据: 触发冲突并打开合并弹窗
    判定: desktop `[data-vc="modal-conflict"]` computed `width==620px`、`border-radius==14px`、`padding==24px`、`max-height` 解析为像素按 `computed_px == round(0.86 × window.innerHeight)` ±1px 判定（desktop 800 → **688px**，承接 §7.3 max-height 细则）、居中（左右 margin/offset 相等）；mobile computed `width`==390px、`border-radius==0px`、`overflow-y==auto`（authored，复核）

### C-13 — 文件上传响应式（返工）
- design_rev: 2
- impact: structural
- 受影响需求: 013, 013b
- 决议: 返工
- 可验证标准（继承升级后 G-*；不要求功能 e2e，unit 覆盖 + 响应式 AC-*）：
  - [ ] rev 1 功能判据保留：本页内上传区 FIT/TCX/GPX 多选、单文件 ≤50MB（超限拒绝并提示）；「已解析文件」列表（名称/大小/时间/已入库），入库后出现在运动记录、来源标「FIT上传」。
  - [ ] unit：>50MB 或非法扩展名被拒；合法文件进入已解析列表。
  - id: AC-013b-1
    描述: 上传区与已解析列表同 grid 规则，mobile 单列不溢出
    验证方式: e2e-browser
    路径: /connectors
    视口: [mobile]
    判定: 上传区与「已解析文件」列表 mobile 单列堆叠；`documentElement.scrollWidth <= 390`

### C-14 — 设置：删除数据保留 + 响应式（返工）
- design_rev: 3
- impact: structural
- fidelity: pixel-contract
- 受影响需求: 014, 014b, 014c
- 决议: 返工
- 可验证标准（继承升级后 G-*；不要求功能 e2e，unit 覆盖 + 响应式 AC-*）：
  - [ ] **分组由五 → 四**：账户信息（新密码×2 一致性校验）/ 单位制（距离海拔·配速·体重）/ 区间设定（MaxHR/LTHR/FTP + Z1–Z4 上界）/ AI 接口（base_url 默认 `https://api.deepseek.com` / API Key / 模型名 / 测试连接 / 隐藏系统提示词查看）。rev 1 中「数据保留策略」分组（占用统计 / 保留期限 / 到期自动清理开关）**删除**。
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
- **pixel-contract 增量（design_rev 3，返工 014c；前序 rev 2 判据全部保留）**：
  - [ ] **硬要求（data-vc 镜像）**：`settings-page`、`settings-group`、`settings-account-grid`、`settings-zone-grid` 镜像到对应组件根元素。
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
    判定: desktop `[data-vc="settings-account-grid"]`（auto-fit）按已填充列几何解析 2 列、`[data-vc="settings-zone-grid"]`（显式 `repeat(4,minmax(80px,1fr))`）按像素轨道串解析 4 列；mobile account-grid 解析 1 列、zone-grid 解析 2 列（`repeat(2,1fr)`，authored，验收阶段实测复核）。grid 列数判法见 pixel-contract 验法细则
