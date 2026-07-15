---
id: "010c"
status: verified
source_design_rev: 4
supersedes: "010b"
superseded_by: null
contract_ref: "C-10"
branch: "feat/010c-connector-card"
---

# 连接器网格·卡片·状态胶囊视觉契约（pixel-contract 返工）

## 背景 / 目标
落成 contract C-10（返工，design_rev 3，fidelity: pixel-contract）。为连接器网格/卡片/三态状态胶囊加 `data-vc` 锚点并锁定列数断点与配色。原 010b 留 `completed/` 当 rev 2 历史，不改写。前序 rev 2 功能与响应式判据全部保留。

## 范围
- 做：`connectors-grid`、`connector-card`、`status-pill-connected`、`status-pill-failed`、`status-pill-disconnected` 镜像到对应组件根元素；命中 computed 契约达 §A 值（见 contract C-10 AC-010c-1..2）。
- 不做：四状态集合/间隔选项/演示初始态逻辑改动（rev 2 原样保留）。

## 涉及组件 / token
ConnectorsGrid / ConnectorCard / StatusPill（connected/failed/disconnected 三态）。

**token 依据（design_rev 4 re-base）**：token 唯一事实源 = v3.1 三表（表 a 颜色 / b 圆角 / c 间距，见 contract「G-token 权威源与 token 表」节）；本版补全 token 基础、目标 computed rgb/px 不变，**不新增/不修改任何 AC 判定值**。三态派生半透明 success@0.12/0.35、danger@0.10/0.40、textMuted@0.10 具名集中定义。

## 验收标准（来源：contract.md C-10，Validator 只认该条目）
- [ ] 前序 rev 2 判据（四状态集合/间隔选项/演示初始态 unit、grid mobile 单列 AC-010b-1）全部保留。
- [ ] **硬要求**：上列 5 个 `data-vc` 锚点镜像到对应组件根元素。
- [ ] AC-010c-1（e2e-browser，mobile+desktop）：connectors-grid display grid + 断点列数（desktop 2 列同排 / mobile 1 列堆叠，按已填充列几何）、gap 16；connector-card bg/border/radius/padding。
- [ ] AC-010c-2（e2e-browser，desktop）：三态 status-pill 配色（connected 须触发一次同步成功后采集；failed/disconnected 为演示初始态）。
- [ ] testing / lint / type。

## 备注
connected 态承接 001c AC-001c-4 同步成功前置。grid auto-fit 判法见验法细则。依赖 001c。
