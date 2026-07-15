---
id: "001c"
status: verified
source_design_rev: 4
supersedes: "001b"
superseded_by: null
contract_ref: "C-1"
branch: "feat/001c-foundation"
---

# 全局 chrome·导航·主按钮·toast 视觉契约（pixel-contract 返工）

## 背景 / 目标
落成 contract C-1（返工，design_rev 3，fidelity: pixel-contract）。v3.0 把 v2.0 隐式视觉契约显式化：为顶栏/导航/同步胶囊/底部 tab/toast/主按钮加稳定 `data-vc` 锚点，并以浏览器 computed 值锁定配色/边框/圆角/间距。原 001b 留 `completed/` 当 rev 2 历史，不改写、不移回。前序 rev 2 功能与响应式判据全部保留。

## 范围
- 做：把 `top-nav`、`top-nav-item-active`、`sync-chip`、`bottom-nav`、`bottom-nav-item-active`、`toast`、`btn-primary`（发送按钮为代表）镜像为对应组件**根元素**的 `data-vc`；命中锚点的 computed 契约属性达 §A 值（见 contract C-1 AC-001c-1..5）。
- 不做：改动任何 pixel-contract AC 的目标 computed 值（design_rev 4 为纯 token 交底补全、零视觉设计变更，token 依据迁至 v3.1 三表但目标 rgb/px 不变）；业务逻辑改动；各业务页内部 pixel-contract（各自 00Xc 负责）。

## 涉及组件 / token
TopNav / BottomTabBar / SyncChip / Toast / BtnPrimary（发送按钮）。

**token 依据（design_rev 4 re-base）**：token 唯一事实源 = v3.1 三表（表 a 颜色 / b 圆角 / c 间距，见 contract「G-token 权威源与 token 表」节）；本版补全 token 基础、目标 computed rgb/px 不变，**不新增/不修改任何 AC 判定值**。accent 强调色以固化后 #4292E0（rgb(66,146,224)）为准；top-nav-item-active 底 = accent@0.16（AC-001c-1）。

## 验收标准（来源：contract.md C-1，Validator 只认该条目）
- [ ] 前序 rev 2 判据（四断点 BreakpointState、双模导航、门禁#6、AC-001b-1..5）全部保留。
- [ ] **硬要求**：上列 7 个 `data-vc` 锚点镜像到对应组件根元素，否则 Validator `[data-vc=…]` 选空、断言全废（G-fidelity）。
- [ ] AC-001c-1..5（e2e-browser）：top-nav-item-active 选中态配色 / sync-chip（desktop）/ bottom-nav（mobile）/ toast（同步成功后）/ btn-primary 视觉契约，computed 值精确相等（颜色零容差、像素 ±1px）。
- [ ] testing / lint / type。

## 备注
精确 computed 值与视口见 contract C-1 各 AC-* 块 + 「pixel-contract 验法细则」。依赖：本条为全局 chrome/nav 契约，建议先行；其余 00Xc 相互独立可并行。
