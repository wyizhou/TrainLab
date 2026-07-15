---
id: "009c"
status: verified
source_design_rev: 4
supersedes: "009b"
superseded_by: null
contract_ref: "C-9"
branch: "feat/009c-health"
---

# 睡眠堆叠柱 + 健康子标签视觉契约（pixel-contract 返工）

## 背景 / 目标
落成 contract C-9（返工，design_rev 3，fidelity: pixel-contract）。为睡眠三段堆叠柱与健康子标签加 `data-vc` 锚点并锁定 computed 配色/圆角。原 009b 留 `completed/` 当 rev 2 历史，不改写。前序 rev 2 功能与响应式判据全部保留。

## 范围
- 做：`sleep-chart-bar-deep`、`sleep-chart-bar-light`、`sleep-chart-bar-rem`、`health-tab`、`health-tab-selected` 镜像到对应组件根元素；命中 computed 契约达 §A 值（见 contract C-9 AC-009c-1..2）。
- 不做：五子标签/习惯/数据量级/分页/睡眠柱数断点逻辑改动（rev 2 原样保留）。

## 涉及组件 / token
SleepChart（deep/light/rem 三段柱）/ HealthTab（选中/常态）。

**token 依据（design_rev 4 re-base）**：token 唯一事实源 = v3.1 三表（表 a 颜色 / b 圆角 / c 间距，见 contract「G-token 权威源与 token 表」节）；本版补全 token 基础、目标 computed rgb/px 不变，**不新增/不修改任何 AC 判定值**。sleepRem=rgb(143,193,242)、accentDeep=rgb(46,92,158)。

## 验收标准（来源：contract.md C-9，Validator 只认该条目）
- [ ] 前序 rev 2 判据（五子标签/习惯/数据量级/分页 unit、睡眠柱数断点 7/14、mobile 卡片重排 AC-009b-1/2）全部保留。
- [ ] **硬要求**：上列 5 个 `data-vc` 锚点镜像到对应组件根元素。
- [ ] AC-009c-1（e2e-browser，desktop，切睡眠子标签）：deep/light/rem 三段配色与圆角（deep 底圆角、light 无圆角、rem 顶圆角）。
- [ ] AC-009c-2（e2e-browser，desktop）：health-tab 选中 vs 常态配色。
- [ ] testing / lint / type。

## 备注
精确值见 contract C-9 各 AC-* 块。依赖 001c。
