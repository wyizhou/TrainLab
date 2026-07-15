---
id: "014c"
status: verified
source_design_rev: 4
supersedes: "014b"
superseded_by: null
contract_ref: "C-14"
branch: "feat/014c-settings"
---

# 设置布局视觉契约（pixel-contract 返工）

## 背景 / 目标
落成 contract C-14（返工，design_rev 3，fidelity: pixel-contract）。为设置页布局与分组、两组网格加 `data-vc` 锚点并锁定 760 居中、分组堆叠、断点列数的 computed 契约。原 014b 留 `completed/` 当 rev 2 历史，不改写。前序 rev 2 功能（四分组、删数据保留、区间边界供 C-8）与响应式判据全部保留。

## 范围
- 做：`settings-page`、`settings-group`、`settings-account-grid`、`settings-zone-grid` 镜像到对应组件根元素；命中 computed 契约达 §A 值（见 contract C-14 AC-014c-1..2）。
- 不做：四分组集合/删数据保留/区间边界/密码一致性逻辑改动（rev 2 原样保留）。

## 涉及组件 / token
SettingsPage / SettingsGroup / SettingsAccountGrid / SettingsZoneGrid。

**token 依据（design_rev 4 re-base）**：token 唯一事实源 = v3.1 三表（表 a 颜色 / b 圆角 / c 间距，见 contract「G-token 权威源与 token 表」节）；本版补全 token 基础、目标 computed rgb/px 不变，**不新增/不修改任何 AC 判定值**。settings-page max-width 760 属结构尺寸例外，仍由 AC-014c-1 e2e 锁。

## 验收标准（来源：contract.md C-14，Validator 只认该条目）
- [ ] 前序 rev 2 判据（四分组、删数据保留 e2e、区间边界供 C-8、mobile 2×2 区间网格、密码一致性 unit、AC-014b-1/2）全部保留。
- [ ] **硬要求**：上列 4 个 `data-vc` 锚点镜像到对应组件根元素。
- [ ] AC-014c-1（e2e-browser，desktop）：settings-page max-width 760 居中；settings-group bg/border/radius/padding 22，四分组单列堆叠（top 递增、left 相同）。
- [ ] AC-014c-2（e2e-browser，mobile+desktop）：desktop account-grid 2 列（auto-fit 几何）/ zone-grid 4 列（显式 repeat 轨道）；mobile account-grid 1 列 / zone-grid 2 列（authored 复核）。
- [ ] testing / lint / type。

## 备注
grid 列数判法（auto-fit 几何 vs 显式 repeat）见 contract C-14 AC-014c-2 + 验法细则。依赖 001c。
