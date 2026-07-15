---
id: "012c"
status: verified
source_design_rev: 4
supersedes: "012b"
superseded_by: null
contract_ref: "C-12"
branch: "feat/012c-conflict-merge"
---

# 合并弹窗视觉/形态契约（pixel-contract 返工）

## 背景 / 目标
落成 contract C-12（返工，design_rev 3，fidelity: pixel-contract）。为合并弹窗与遮罩加 `data-vc` 锚点并锁定 desktop 620px 居中 vs mobile 全屏的 computed 契约。原 012b 留 `completed/` 当 rev 2 历史，不改写。前序 rev 2 功能与响应式判据全部保留。

## 范围
- 做：`modal-conflict`、`modal-overlay` 镜像到对应组件根元素；命中 computed 契约达 §A 值（见 contract C-12 AC-012c-1）。
- 不做：去重/横幅/逐组选择/合并逻辑改动（rev 2 原样保留）。

## 涉及组件 / token
ConflictModal / ModalOverlay。

**token 依据（design_rev 4 re-base）**：token 唯一事实源 = v3.1 三表（表 a 颜色 / b 圆角 / c 间距，见 contract「G-token 权威源与 token 表」节）；本版补全 token 基础、目标 computed rgb/px 不变，**不新增/不修改任何 AC 判定值**。modal width 620 / max-height 688 属结构尺寸例外，仍由 AC-012c-1 e2e 锁。

## 验收标准（来源：contract.md C-12，Validator 只认该条目）
- [ ] 前序 rev 2 判据（去重/横幅/逐组选择/合并后横幅消失门禁#3、mobile 全屏 AC-012b-1）全部保留。
- [ ] **硬要求**：`modal-conflict`、`modal-overlay` 镜像到对应组件根元素。
- [ ] AC-012c-1（e2e-browser，mobile+desktop，触发冲突开合并弹窗）：desktop width 620/radius 14/padding 24/max-height 688px（round(0.86×800) ±1px）/居中；mobile 全屏（width 390/radius 0/overflow-y auto，authored 复核）。
- [ ] testing / lint / type。

## 备注
max-height vh 验法（desktop 800 → 688px）见 contract C-12 AC-012c-1 + 验法细则。依赖 001c、010c、011c。
