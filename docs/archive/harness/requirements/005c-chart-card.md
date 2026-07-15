---
id: "005c"
status: verified
source_design_rev: 4
supersedes: "005b"
superseded_by: null
contract_ref: "C-5"
branch: "feat/005c-chart-card"
---

# 图表卡片容器视觉契约（pixel-contract 返工）

## 背景 / 目标
落成 contract C-5（返工，design_rev 3，fidelity: pixel-contract）。为图表卡片容器加 `data-vc` 锚点并锁定下沉层 computed 契约。原 005b 留 `completed/` 当 rev 2 历史，不改写。前序 rev 2 功能与响应式判据全部保留。

## 范围
- 做：`chart-card` 镜像到图表卡片组件根元素；命中 computed 契约达 §A 值（见 contract C-5 AC-005c-1），含层级校验（#0B1220 深于 AI 气泡 #121A28）。
- 不做：四态/展开明细行门控/svg 自适应逻辑改动（rev 2 原样保留）。

## 涉及组件 / token
ChartCard（容器根元素）。

**token 依据（design_rev 4 re-base）**：token 唯一事实源 = v3.1 三表（表 a 颜色 / b 圆角 / c 间距，见 contract「G-token 权威源与 token 表」节）；本版补全 token 基础、目标 computed rgb/px 不变，**不新增/不修改任何 AC 判定值**。

## 验收标准（来源：contract.md C-5，Validator 只认该条目）
- [ ] 前序 rev 2 判据（四态、展开明细行仅 desktop/wide、门禁#5、svg 不溢出、AC-005b-1/2）全部保留。
- [ ] **硬要求**：`chart-card` 镜像到图表卡片组件根元素。
- [ ] AC-005c-1（e2e-browser，desktop，需发提问生成卡片折叠态）：容器 bg #0B1220 / border / radius / overflow hidden，层级深于 AI 气泡。
- [ ] testing / lint / type。

## 备注
精确值见 contract C-5 AC-005c-1。依赖 001c、004c、006c（发提问链路）。
