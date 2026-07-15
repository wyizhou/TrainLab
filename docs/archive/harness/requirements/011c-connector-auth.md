---
id: "011c"
status: verified
source_design_rev: 4
supersedes: "011b"
superseded_by: null
contract_ref: "C-11"
branch: "feat/011c-connector-auth"
---

# 授权弹窗视觉/形态契约（pixel-contract 返工）

## 背景 / 目标
落成 contract C-11（返工，design_rev 3，fidelity: pixel-contract）。为授权弹窗与遮罩加 `data-vc` 锚点并锁定 desktop 居中定宽 vs mobile 全屏的 computed 契约。原 011b 留 `completed/` 当 rev 2 历史，不改写。前序 rev 2 功能与响应式判据全部保留。

## 范围
- 做：`modal-connector-auth`、`modal-overlay` 镜像到对应组件根元素；命中 computed 契约达 §A 值（见 contract C-11 AC-011c-1）。
- 不做：2FA 两段式逻辑改动（rev 2 原样保留）。

## 涉及组件 / token
ConnectorAuthModal / ModalOverlay。

**token 依据（design_rev 4 re-base）**：token 唯一事实源 = v3.1 三表（表 a 颜色 / b 圆角 / c 间距，见 contract「G-token 权威源与 token 表」节）；本版补全 token 基础、目标 computed rgb/px 不变，**不新增/不修改任何 AC 判定值**。遮罩 scrim@0.72=rgba(4,8,14,0.72)；modal width 390 属结构尺寸例外，仍由 AC-011c-1 e2e 锁。

## 验收标准（来源：contract.md C-11，Validator 只认该条目）
- [ ] 前序 rev 2 判据（2FA 两段式门禁#2、mobile 全屏 AC-011b-1）全部保留。
- [ ] **硬要求**：`modal-connector-auth`、`modal-overlay` 镜像到对应组件根元素。
- [ ] AC-011c-1（e2e-browser，mobile+desktop，打开 2FA 授权弹窗）：desktop width 390/border/radius 14/padding 24/bg；mobile 全屏（width 390/radius 0/无边框/overflow-y auto，authored 复核）；modal-overlay position fixed + bg rgba(4,8,14,0.72)。
- [ ] testing / lint / type。

## 备注
精确值见 contract C-11 AC-011c-1。依赖 001c、010c。
