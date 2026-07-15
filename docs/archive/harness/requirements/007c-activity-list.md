---
id: "007c"
status: verified
source_design_rev: 4
supersedes: "007b"
superseded_by: null
contract_ref: "C-7"
branch: "feat/007c-activity-list"
---

# 运动列表重排 + 类型胶囊视觉契约（pixel-contract 返工）

## 背景 / 目标
落成 contract C-7（返工，design_rev 3，fidelity: pixel-contract）。为运动表格/卡片列与类型胶囊加 `data-vc` 锚点并锁定断点重排 display 契约与配色。原 007b 留 `completed/` 当 rev 2 历史，不改写。前序 rev 2 功能与响应式判据全部保留。

## 范围
- 做：`activities-table`、`activities-card-list`、`type-chip`、`type-chip-selected` 镜像到对应组件根元素；命中 computed 契约达 §A 值（见 contract C-7 AC-007c-1..2）。
- 不做：列集/类型筛选/分页/批量计数逻辑改动（rev 2 原样保留）。

## 涉及组件 / token
ActivityTable / ActivityCardList / TypeChip（选中/常态）。

**token 依据（design_rev 4 re-base）**：token 唯一事实源 = v3.1 三表（表 a 颜色 / b 圆角 / c 间距，见 contract「G-token 权威源与 token 表」节）；本版补全 token 基础、目标 computed rgb/px 不变，**不新增/不修改任何 AC 判定值**。activities-card-list 单卡 padding 具名 token padCardListItem（`14 16`）。

## 验收标准（来源：contract.md C-7，Validator 只认该条目）
- [ ] 前序 rev 2 判据（列集/类型筛选/分页/批量计数 e2e、mobile 卡片重排 AC-007b-1）全部保留。
- [ ] **硬要求**：上列 4 个 `data-vc` 锚点镜像到对应组件根元素。
- [ ] AC-007c-1（e2e-browser，mobile+desktop）：desktop table 显示（bg/border/radius/overflow-x/内层 min-width 960）、card-list 不在 DOM；mobile table display none、card-list flex column gap 10。
- [ ] AC-007c-2（e2e-browser，desktop）：type-chip 选中 vs 常态配色。
- [ ] testing / lint / type。

## 备注
精确值见 contract C-7 各 AC-* 块。依赖 001c。

## 执行说明（Executor, awaiting_validation）
分支 `feat/007c-activity-list`（commit cdf5cca）。

- **data-vc 镜像（硬要求）**：`activities-table` → ActivityTable 根；`activities-card-list` → ActivityCardList 根；`type-chip` / `type-chip-selected` → 筛选胶囊按钮根（选中态切换）。
- **AC-007c-1**：ActivityTable 根改为滚动容器（bg `--color-panel` rgb(18,26,40) / border 1px `--color-border-panel` rgb(34,48,73) / radius `--radius-panel` 12 / overflow-x auto），内层 `.activity-table__grid` 保持 min-width 960。断点按 v3.1 A14 收窄为 **仅 mobile(<640) 隐藏表格**（tablet/desktop=block），避免 tablet 空档。卡片列改为**按 mobile 断点条件挂载**（`useBreakpoint()==='mobile'`），desktop 下不在 DOM；容器 flex column gap `--gap-card-mobile` 10；单卡 panel bg/borderPanel/radius12/pad `--pad-card-list-item` 14 16。
- **AC-007c-2**：type-chip 常态 = panel / borderPanel / textMuted；选中 = `--color-accent-16` 底 / accent 边 / accentText 字，radiusPill + padChipType `--pad-chip-type` 6 14。
- 新增 token：`--pad-chip-type` 6 14 / `--pad-card-list-item` 14 16 / `--gap-card-mobile` 10（off-scale 具名，CSS-only，与既往 pad/gap token 一致，不入 tokens.ts）。
- 前序 rev 2 判据保留：列集/类型筛选/分页/批量计数 e2e 与 AC-007b-1 均未改逻辑，绿。
- 验证：`npm run lint` / `typecheck` 绿；`vitest run` 183/183；`playwright test` 48/48（新增 AC-007c-1 mobile+desktop、AC-007c-2 desktop 于 `tests/e2e/activities-pixel.spec.ts`）。
