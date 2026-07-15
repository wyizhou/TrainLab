---
proposal_for_design_rev: 4
design_version: "3.1"
impact: structural            # 全 structural / fidelity: pixel-contract；纯 token 补全纠错、零视觉设计变更
planner_ack: true
validator_ack: true           # 已回填（见 §8）：接受 Planner 全部主张，off-scale 采 (a)
created_at: 2026-07-14
source:
  update: "design/v3.1/交接/update.md (design_rev 4)"
  detail: "design/v3.1/交接/v3.1-设计文档.md（表 a 颜色 / 表 b 圆角 / 表 c 间距 三张 token 表 + 引用化 §A + §B 交互契约）"
  prototype: "design/v3.1/运动分析系统.dc.html（v3.1；导出副本，属设计侧输入）"
---

# 提案 — design_rev 4（TrainLab v3.1：完整 token 交底 / 补全纠错，零视觉设计变更）

> 本文件是 `pending/` 协商稿，**不是** contract。双方 `planner_ack` + `validator_ack` 后，
> 由 Planner 把下方动作落成到 `docs/contract/contract.md`（G-token 基线补全 + 例外声明）与
> `active/` 的 001c–014c（就地 re-base，见 §1），更新 `backlog.md`、追加 `changelog.md`、
> 更新 `design-state.json`，最后删除 `docs/executor/.blocked`。
> **本轮只产出本提案 + 创建 `.blocked`，不落成 contract、不改 active/、不动 backlog/changelog/design-state。**

## 0. 分级判定

- `design_rev` 3 → 4。变更清单 7 行（#1–#7），设计侧全部标 `impact: structural` / `fidelity: pixel-contract`；**无 structural-only、无 scope 行**。
- v3.1 的性质：**对 rev-3 残缺 token 交底的补全纠错，零视觉设计变更**。它做四件事，均不移动任何组件契约面的目标值：
  1. 提供**完整三张 token 表**（表 a 颜色 / 表 b 圆角 / 表 c 间距）作为视觉参数**唯一事实源**；
  2. §A 全部锚点契约属性由**散列裸值改为引用 token 名**，与 token 表交叉核对；
  3. **废止 v3.0「色板/间距 token 以 v2.0 为准」「无 token 值变更」的表述**（该表述自相矛盾：既要求实现产出 rgb(66,146,224) 等 pixel-contract 值，又说 token 以 v2.0 为准、无值变更，而 v2.0 token 基础无法产出这些值）；
  4. 把 accent 及 success/warn/danger 由 v2.0 的 `oklch()` 定义**固化为原型实测 rgb**（accent #4292E0、success #3FBF8F、warn #E0A040、danger #E06060），并把 **typography 与固定结构尺寸显式声明为 token 化范围外例外**。
- **为什么仍判 `structural`（不判 cosmetic）**：本版改动的是 **G-token 全局验证基线的权威源与口径**（token 唯一事实源从「v2.0 实现」迁到「v3.1 表」、新增 typography/结构尺寸例外边界、off-scale 间距口径待定），以及 12 条 active 需求的 token 依据。G-* 基线变更按 planner 分级不属「仅 token 值/文案/图标」的 cosmetic，且误判代价不对称——**不确定选高档**。故走 contract 协商 + 失效检查全流程，`.blocked` 已创建冻结 Executor。
- **零 AC 值变更（已逐条核对）**：v3.1 token 表的 rgb/px 与既有 contract 各 AC-* 目标值**逐条相等**——accent=rgb(66,146,224)（AC-001c-1/003c-2/004c-1/007c-2/…）、accentDeep=rgb(46,92,158)（AC-006c-2/009c-1）、accentText=rgb(94,163,232)、success=rgb(63,191,143)（AC-010c-2/008c-2 Z3）、warn=rgb(224,160,64)（Z4）、danger=rgb(224,96,96)（AC-010c-2 failed / Z5）、sleepRem=rgb(143,193,242)（AC-009c-1）、radiusZone=4px（AC-008c-2 hr-zone-bar）、五区色 Z1–Z5 依次匹配 AC-008c-2。**rev-3 各 AC 的目标 rgb 本就正确；本版只补齐能产出这些值的 token 基础 + 废止自相矛盾表述，不动任何目标值。** 因此本版**不新增/不修改任何 pixel-contract AC 的判定值**。

## 1. 失效检查结果（含用户裁定：就地 re-base）

`.blocked` 创建时刻 `2026-07-14T16:30:00+08:00`（见文件）。遍历：

- **`docs/executor/active/`**：001c / 003c / 004c / 005c / 006c / 007c / 008c / 009c / 010c / 011c / 012c / 014c 共 **12 份**，全部 `status: contracted`、`source_design_rev: 3`、**从未执行、无 `feat/00Xc-*` 分支**（Executor 因 rev-3 落地后再未取件，且本轮 `.blocked` 继续冻结）。全部涉及组件命中 v3.1 §A 引用化锚点。
- **`docs/executor/completed/`**：001–014 + 001b–014b 共 28 份，`verified`（rev-1 / rev-2 历史）。C-1 各 pixel-contract 层在 rev-3 才立、对应 001c 从未 build——**completed/ 内无任何已交付实现引用 v3.1 固化后的 token**，故**不触发返工已 verified 流程**，completed/ 一律不动。

### 1.1 处置（用户已裁定：**就地 re-base，不新建 001d、不加 SUPERSEDED- 墓碑**）

对 active/ 的 001c–014c：**落地时（下一轮）就地把 `source_design_rev: 3 → 4`，更新其 token 依据与 AC 的 token 引用表述，目标 rgb/px 不变。** 不改名、不建 001d、不留墓碑。

**裁定理由（承接用户，写入本提案作依据）**：

1. **不触发「返工已 verified」新后缀流程**——该流程（planner CLAUDE.md「替代与编号」）的适用前提是命中需求**已 verified**（在 completed/，有已交付实现需按更严标准重做）。001c–014c 仍 `contracted`、从未 build，无已交付实现可失效，前提不成立。
2. **墓碑规则的唯一适用动机已就地满足**——墓碑（SUPERSEDED- + 序号断档保留）存在的理由是「contract 修订条目要引用需求编号、序号断档会被下个 Planner 误判为漏写、已存在的 feat 分支要靠文档归属判去留」。而本例：contract 对编号 001c 的引用**就地保留**（re-base 不改编号）、序号无断档、**无 feat 分支**。三条动机全不成立，故无须造墓碑。
3. **本版零 AC 值变更**——re-base 不改任何 pixel-contract 判定值，只把 token 依据从「v2.0 表述」指到「v3.1 表」。对 Executor 而言取件标的不变、验收标准的目标值不变，只是 token 基础从「无法产出」变为「可产出且集中定义」。

> 与 rev-2/rev-3 的对比：rev-2/rev-3 命中的是 completed/ 的 verified 需求（有已交付 rev-1/rev-2 实现），故走「原文档留 completed/、active/ 新建 <原号>b/<原号>c」。rev-4 命中的是 active/ 的 contracted 未开工需求，性质不同——**就地 re-base 是 contracted 未开工需求遇 token 基础补全的正确处置**。

### 1.2 未命中 / 不受返工影响

| C 条目 | live 需求 | §A 锚点 | 决议 |
|---|---|---|---|
| C-2（登录） | 002b（completed，verified） | 无 | 保留，无 active 返工需求，不动 |
| C-13（上传） | 013b（completed，verified） | 无 | 保留，无 active 返工需求，不动 |

- C-2 / C-13 无 §A 锚点、无 active/00Xc 文档 → 本版对其无处置动作。G-token 基线补全对全局生效，但两者已 verified、不重开。
- **告警段落**：`active/` 无 `in_progress` / `awaiting_validation` 需求（全为 contracted 且被 `.blocked` 冻结），无需追加「设计变更告警」段落。

### 1.3 fixture 前置检查

本版为纯 token 交底，**无新增 `fixture_owner: human` 资产**。C-8 仍复用既在 repo 的 `tests/fixtures/614797758_ACTIVITY.fit`。**无 fixture 死锁**。

## 2. 拟落成的 G-token 基线补全（下一轮写入 contract.md「全局验证基线」）

> 本节是本版 contract 变更的**主体**：更新 G-token 的权威源与口径边界；不新增 pixel-contract AC（AC 值未变）。

### 2.1 权威源迁移（承接 v3.1 权威性声明）

- **token 唯一事实源改为 v3.1 三表**：颜色/圆角/间距 token 集中定义于单一模块（`src/design/tokens.ts` 及/或 CSS 变量），其值 **1:1 对齐 `design/v3.1/交接/v3.1-设计文档.md` 表 (a)/(b)/(c) 的 computed 值**。
- **废止旧表述**：删除 / 作废 contract 及 001c–014c 中「色板/间距 token 以 v2.0 为准」「无 token 值变更」的措辞。落地时**一并修订 C-1 rev-1 功能判据行**中「强调 `oklch(0.65 0.15 230)`」的遗留描述，改述为固化后的 accent = `#4292E0`（rgb(66,146,224)），使 contract 内部对强调色的描述与 pixel-contract AC 自洽（消除 rev-3 遗留的「token 描述用 oklch、AC 却要 rgb(66,146,224)」的自相矛盾）。
- **语义色 oklch→rgb 固化（有意为之，非笔误）**：success/warn/danger 由 v2.0 `oklch()` 定义固化为原型实测 rgb（#3FBF8F / #E0A040 / #E06060）；accent 同理（v2.0 oklch 渲染值 ≠ 原型实测，原型实为 #4292E0）。下游以 v3.1 表实测 rgb 为准。**这些 rgb 与既有各 AC 目标值一致，属实现向原型对齐、非目标值变更。**

### 2.2 补齐的 token（下游据以集中定义，值见 v3.1 三表）

- 颜色补齐：3 种边框色（borderPanel/borderInput/borderWeak，另 borderToast）、panelNav、accentDeep、accentText、textFaint、sleepRem、toastBg、scrim（遮罩）、hoverRow，及派生半透明（accent@0.12/0.16/0.18、success@0.12/0.35、danger@0.10/0.40、textMuted@0.10、scrim@0.72）。
- 圆角补齐：radiusHairline(2)、radiusXs(3)、radiusInput(8)、radiusCard(12)、**radiusZone(4)**（补 hr-zone-bar 4px 圆角档，清 A5 编辑残留）及非对称值（radiusBubbleAI `14 14 14 4`、radiusBubbleUser `14 14 4 14`、radiusSleepDeep `0 0 3 3`、radiusSleepRem `3 3 0 0`）。
- 间距补齐：表 (c) 全部 padding/gap/margin，含 **padCardListItem(14 16)** 使 A14 无裸值。off-scale 值（5/9/11/13/18/22px、6.5px gap）口径见 §5（本轮核心开放点）。

## 3. §A 引用化的落地含义（不改 AC 判定值）

v3.1 §A 把每个锚点契约属性改写为 `{tokenName}` 引用（如 A1 `background {panel} · border 1px solid {borderPanel} · border-radius {radiusBubbleAI} · padding {padBubbleAI}`）。落地时：

- contract 各 pixel-contract AC 的 **computed 目标值（rgb/px）保持不变**——它们本就是 §A token 展开后的 computed 值。§A 引用化只是把「同一个值」的来源从散列裸值收敛到具名 token，**不改 Validator 的断言目标**。
- 001c–014c 的「涉及组件 / token」段与「不做：任何 token 值变更」措辞在 re-base 时更新为「token 依据 = v3.1 三表；本版补全 token 基础、不改目标 computed 值」。

## 4. 本轮落地动作清单（下一轮，双 ack 后执行）

1. **G-token 基线补全**写入 contract.md「全局验证基线」（§2.1 权威源迁移 + 废止旧表述 + 修订 C-1 oklch 遗留描述 + §2.2 补齐 token 引用 + §6 例外声明）。
2. **不新增/不修改任何 pixel-contract AC 判定值**（zero AC value change）。
3. **就地 re-base** active/ 001c–014c：`source_design_rev: 3 → 4`，更新 token 依据表述，目标 rgb/px 不变；**不改名、不建 001d、不留墓碑**（§1.1）。
4. C-2 / C-13 及 completed/ 全部文档**不动**。
5. off-scale 间距口径按 §5 Validator 裁定落成（可能追加一条 G-token 口径细则）。
6. 更新 `backlog.md`（12 条 source_design_rev 3→4、摘要不变）、追加 `changelog.md`（design_rev 4、structural、受影响=001c–014c、决议=就地 re-base）、更新 `design-state.json`（`last_seen_design_rev: 4`、`last_seen_version: "v3.1"`）、**删除 `.blocked`**。

## 5. 核心开放点（待 Validator 敲定）：off-scale 间距 G-token 口径

v3.1 表 (c) 照实交底了原型手调的 off-scale 值：**5 / 9 / 11 / 13 / 18 / 22px 及 6.5px gap**（如 padChip `5 13`、padRailItem `9 10`、padBtnPrimary/toast `11 22`、padBubbleAI `13 16`、padMainTablet `18 16`、padGroup `22`、gapLegend `6.5`），未凑 8pt scale。当前 G-token 明文对「token 文件之外的**裸像素间距值**」报 error。三选一：

- **(a) 全部纳入 space token**：把每个 off-scale 值作为**具名 token**定义进 token 模块（v3.1 已给名：padChip/padRailItem/padBtnPrimary/…），G-token 口径**不变**、继续对 token 文件外裸间距值报 error。tokens 不必落在 8pt scale 上——`padChip = '5px 13px'` 是合法具名 token。
- **(b) G-token 对间距开口子**：颜色/圆角仍强制走 token（裸 hex/rgb/oklch/裸圆角报 error），**padding 允许受控裸值**（放宽间距 lint 为 warning 或豁免）。
- **(c) padding 降级为结构容差**：颜色/边框/圆角保 pixel-contract 精确断言，**padding 不逐像素锁**（只验存在/量级，不验精确 px）。

**Planner 建议采 (a)。理由**：
1. **零口径放宽**——v3.1 已为每个 off-scale 值提供具名 token，「凑不进 8pt scale」不是「不能当 token」的理由；具名 token 本就允许任意值。选 (a) 则 G-token 一字不改，唯一事实源与 pixel-contract 强度全保。
2. **(b)/(c) 均削弱既有验收**——现有 contract 已有 padding 类 pixel-contract AC（AC-001c-1 `padding==8px 13px`、AC-004c-1 `padding==5px 13px`、AC-011c-1 `padding==24px` 等，逐条 e2e-browser 精确断言）。选 (b)/(c) 会与这些**已 ack 的 AC 冲突**（一边精确断言 padding、一边放行裸 padding / 不锁 padding），自相矛盾。
3. **误判代价**——放宽间距口径后，Executor 可能散布未集中定义的裸间距，正是 v3.1 交底要消除的「散列裸值」，与本版目标背离。

> **裁定请 Validator 回填**：`off_scale_spacing_verdict: a | b | c`，并确认是否需在 contract「G-token」下增补一条「off-scale 间距一律具名 token、口径不放宽」的细则。

## 6. Token 化范围外例外（承接设计显式声明，避免 Validator 误判）

v3.1 §A「范围与例外声明」显式把以下两类列为**本版 token 化范围外**，§A 中以字面值出现属**显式例外、非无声裸值**。本提案承接此边界，请 Validator 在落成时确认写入 contract「G-token」口径，**明确 G-token 不 lint 这两类**：

- **Typography（字号/字重/行高）**：如 `font-size: 13px/11px`、`font-weight: 600/700`。本版未纳入 token 化，留待后续 typography 档位；当前以字面 computed 值内联记录。**裸 font-size / font-weight 不算 G-token 违规。**
- **固定结构尺寸（width/height/min-width/border-width 等）**：如 session-rail `width: 212px`、bottom-nav `height: 60px`、modal `width: 390/620px`、settings-page `max-width: 760px`、analysis-main `max-width: 1200px`、activities-table 内层 `min-width: 960px`、边框宽度 `1px/2px/3px`。为逐元素结构测量值，本版以字面 computed 值内联记录，不纳入 token 表。**裸结构尺寸不算 G-token 违规。**

> **为什么必须显式承接**：现在有了权威 token 表，Validator 若过度解读「所有 px 都得是 token」，会把裸 font-size / 结构尺寸误判为 G-token 违规、卡住本可通过的 Executor。显式声明例外边界，把「可能误判的隐含歧义」变成「显式规则」。这两类的具体值仍由既有 pixel-contract AC（如 AC-003c-1 `width==212px`、AC-006c-1 含 `font-size` 等）逐条 e2e-browser 断言锁住——**不 token 化 ≠ 不验**，只是验的通道是 e2e computed 断言而非 lint。

> **裁定请 Validator 回填**：`typography_exception_ack: true/false`、`structural_dimension_exception_ack: true/false`。

## 7. Ack

- `planner_ack: true`（本文件 frontmatter）——分级（structural，非 cosmetic）、零 AC 值变更核对、失效检查（active/ 12 条 contracted 未开工 → **就地 re-base**，理由见 §1.1）、G-token 权威源迁移与补齐 token（§2）、§A 引用化不改判定值（§3）、off-scale 间距建议 (a)（§5）、typography/结构尺寸例外承接（§6）由 Planner 提出。
- `validator_ack: false`——**待 Validator 回填**：核对零 AC 值变更、就地 re-base 处置、G-token 权威源迁移文案、并**裁定 §5 off-scale 间距口径 (a/b/c)** 与 §6 两条例外边界 ack。

> 双方 ack 齐备前，Planner **不落成 contract、不改 001c–014c、不动 backlog/changelog/design-state、不删 `.blocked`**。

## 8. 待 Validator 回填字段（协商锚点）

```yaml
# Validator 回填（design_rev 4 协商，2026-07-14）
zero_ac_value_change_confirmed: true   # 已独立逐条抽验 v3.1 三表 rgb/px == 既有各 AC 目标值，全部相等（见下 verification）
inplace_rebase_ack: true               # 认可 active/ 001c–014c 就地 re-base、不建 001d、不留墓碑
gtoken_authority_migration_ack: true   # 认可 token 唯一事实源迁到 v3.1 三表、废止「以 v2.0 为准」、C-1 oklch 遗留改 #4292E0
off_scale_spacing_verdict: a           # 全部 off-scale 值纳入具名 space token，G-token 口径不放宽
typography_exception_ack: true         # G-token 不 lint 裸 font-size/weight（仍由既有 e2e computed AC 锁）
structural_dimension_exception_ack: true  # G-token 不 lint 裸 width/height/min-width/border-width（仍由既有 e2e computed AC 锁）
notes: |
  ## 独立复核记录（zero AC value change）

  逐条抽验「v3.1 三表值 == 既有 contract 各 AC-* 目标值」，全部相等，无一例外：
  - 颜色：accent=rgb(66,146,224)(AC-003c-2/004c-1/007c-2/008c-2Z2/009c-1light/001c-5)、
    accentDeep=rgb(46,92,158)(006c-2/009c-1deep)、accentText=rgb(94,163,232)(004c-1/007c-2/009c-2/001c-3)、
    success=rgb(63,191,143)(010c-2connected/008c-2Z3)、warn=rgb(224,160,64)(008c-2Z4)、
    danger=rgb(224,96,96)(010c-2failed/008c-2Z5)、sleepRem=rgb(143,193,242)(009c-1)、
    hr-zone Z1–Z5=textFaint/accent/success/warn/danger(008c-2)；
    panel/panelDeep/panelNav/borderPanel/borderInput/borderWeak/borderToast/toastBg/scrim/onAccent/text/textMuted
    及派生 accent@0.12/0.16/0.18、success@0.12/0.35、danger@0.10/0.40、textMuted@0.10、scrim@0.72 逐一命中各 AC。
  - 圆角：radiusZone=4px(008c-2)、radiusCard=12/radiusCardSm=10/radiusInput=8/radiusPanelLg=14/
    radiusBtnPrimary=10/radiusPill=99、非对称 radiusBubbleAI/User、radiusSleepDeep/Rem 全部命中。
  - 间距：padNavItem(8 13)/padSyncChip(6 14)/padRail(12 10)/padRailItem(9 10)/padInputBox(12 14)/
    padChip(5 13)/padChipType(6 14)/padTab(7 18)/padCard(20)/padGroup(22)/padModal(24)/padMetric(14)/
    padPill(4 12)/padBtnPrimary(11 22)/gapAnalysis(18)/gapGrid(16)/gapCardMobile(10) 全部命中。
  → zero_ac_value_change_confirmed = true。

  ## 需 Planner 落地时一并修正的设计文档内部注记笔误（不改任何 AC 值，非否决项）

  表 (a) 派生半透明「用途」列把 `top-nav-item-active 底` 误列在 **accent@0.12** 下；而 §A20 与
  contract AC-001c-1 均取 **accent@0.16=rgba(66,146,224,0.16)**。两个 alpha token 值都在表内、§A（权威锚点契约）
  与 contract 目标一致，故不构成 AC 值变更，仅「用途」列注记错位。请 Planner 落地补齐 token 时以 §A20 / AC-001c-1
  为准（top-nav-item-active 底 = accent@0.16），勿据派生表「用途」列把 top-nav 选中底接成 @0.12，以免误导 Executor。

  ## off-scale 间距 (a) 的 lint 细则（请写入 contract「G-token」下一条口径细则）

  - 采 (a)：5/9/11/13/18/22px 及 6.5px gap 一律作为**具名 space token**定义进 token 模块（v3.1 已给名
    padChip/padRailItem/padBtnPrimary/padBubbleAI/padMainTablet/padGroup/gapLegend 等），G-token 口径**不放宽**：
    继续对 token 文件之外的裸像素间距值报 **error**，抽验 token 文件外裸间距命中数须为 **0**。
    「凑不进 8pt scale」不是「不能当 token」的理由——具名 token 允许任意值，`padChip='5px 13px'` 合法。
  - gapLegend 6.5px：作为具名 token 集中定义即满足 G-token；当前**无任何 AC 断言 gapLegend 的 computed 值**，
    故不涉及 e2e 逐像素判定，本轮无 ±1px 问题。若后续新增针对该值的 computed AC，按既有 pixel-contract
    「像素及百分比换算像素类 ±1px」容差口径判定（6.5px 亚像素舍入落入 ±1px 内）。

  ## 例外边界（§6）的验法确认

  typography（裸 font-size/font-weight）与固定结构尺寸（裸 width/height/min-width/border-width）**不算 G-token 违规、
  不 lint**；此两类的具体值仍由既有各 pixel-contract e2e-browser computed AC 逐条锁死（如 AC-003c-1 width==212px、
  AC-006c-1 含 font-size、AC-010c-2 border-width==1px 等）——**不 token 化 ≠ 不验**，验的通道是 e2e computed 断言而非 lint。
```
