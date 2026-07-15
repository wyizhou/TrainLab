---
id: "004c"
status: verified
source_design_rev: 4
supersedes: "004b"
superseded_by: null
contract_ref: "C-4"
branch: "feat/004c-scope-bar"
---

# 范围胶囊选择态视觉契约（pixel-contract 返工）

## 背景 / 目标
落成 contract C-4（返工，design_rev 3，fidelity: pixel-contract）。为范围胶囊选中/常态加 `data-vc` 锚点并锁定 computed 配色。原 004b 留 `completed/` 当 rev 2 历史，不改写。前序 rev 2 功能与响应式判据全部保留。

## 范围
- 做：`scope-chip`、`scope-chip-selected` 镜像到对应组件根元素；命中 computed 契约达 §A 值（见 contract C-4 AC-004c-1）。
- 不做：逻辑改动（胶囊/选择运动/两开关默认开/摘要联动 rev 2 原样保留）。

## 涉及组件 / token
ScopeBar（scope-chip 选中/常态两态）。

**token 依据（design_rev 4 re-base）**：token 唯一事实源 = v3.1 三表（表 a 颜色 / b 圆角 / c 间距，见 contract「G-token 权威源与 token 表」节）；本版补全 token 基础、目标 computed rgb/px 不变，**不新增/不修改任何 AC 判定值**。

## 验收标准（来源：contract.md C-4，Validator 只认该条目）
- [ ] 前序 rev 2 判据（胶囊/选择运动/两开关默认开/摘要联动 unit、mobile flex-wrap AC-004b-1）全部保留。
- [ ] **硬要求**：`scope-chip`、`scope-chip-selected` 镜像到对应组件根元素。
- [ ] AC-004c-1（e2e-browser，desktop）：选中态 vs 常态配色（bg / border / color / radius / padding）computed 精确相等。
- [ ] testing / lint / type。

## 备注
精确值见 contract C-4 AC-004c-1。依赖 001c。

## 执行记录（awaiting_validation, 分支 feat/004c-scope-bar）
- **data-vc 镜像**：`scope-chip` / `scope-chip-selected` 镜像到 4 个日范围胶囊 `<button>` 根元素（`data-vc={active ? 'scope-chip-selected' : 'scope-chip'}`）。默认 range=3 → 1 个 selected + 3 个常态共存，两锚点均可命中。「选择运动」picker 复用同一视觉但**不带 data-vc**（无 AC 治理它）。
- **token 基础补全**（v3.1 三表 1:1）：新增 `--color-accent-18`(accent@0.18)、`--color-border-input`(borderInput rgb(42,58,85))、`--pad-chip`(padChip 5px 13px)；tokens.ts 同步 `accent18`/`borderInput`（off-scale pad-* 惯例仅存 CSS）。
- **⚠ 共享 token 校正**：`--color-text-muted` 由 `#8a97a8`(rgb 138,151,168) 校正为 **`#8a94a8`(rgb 138,148,168)**，对齐 v3.1 表 (a) 权威 textMuted。原值与三表不符（绿通道差 3），AC-004c-1 常态 color 契约要求 rgb(138,148,168) 必须命中。**零 AC 值变更**：全仓 grep 无任何已 verified e2e/单测断言旧值（AC-001c-1 仅断言 active 态 rgb(230,235,244)）。此改影响所有用 textMuted 的常态文字（top-nav/type-chip/health-tab/status-pill 常态），均朝权威值收敛。
- **验证**：`npm run lint` / `typecheck` 0 error；`npm run test` 183/183 通过（含 tokens 一致性 test）；`npm run e2e scope-bar.spec.ts` 2/2 通过（含 AC-004c-1 desktop）。
