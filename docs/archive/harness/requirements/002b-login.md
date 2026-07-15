---
id: "002b"
status: verified
source_design_rev: 2
supersedes: "002"
superseded_by: null
contract_ref: "C-2"
branch: "feat/002b-login"
---

# 登录页响应式 + 保真（返工，轻）

## 背景 / 目标
落成 contract C-2（返工，design_rev 2）。**无功能/API 变更**：rev 1 登录逻辑全部保留，本条只做视觉保真 + 移动视口再验（rev 1 仅在 ≥980px e2e 过，从未在 390px 验证，标低会让登录卡在 mobile 溢出却照旧通过）。原 002 留 `completed/` 当 rev 1 历史，不改写。

## 范围
- 做：mobile 视口下登录卡外层 padding 收窄、无横向溢出；视觉保真（token 承接）。
- 不做：任何字段/校验/跳转逻辑改动（rev 1 原样保留）。

## 涉及组件 / token
LoginForm、登录卡外层 padding。

## 验收标准（来源：contract.md C-2，Validator 只认该条目）
- [ ] rev 1 功能判据保留：居中卡片，字段=用户名/密码/4 位验证码（点击刷新）；回车提交；错误提示可见；无营销元素；演示校验（任意用户名+密码≥4 位+验证码正确→分析页，任一不满足→报错不跳转）。
- [ ] e2e（门禁#1）：错误验证码被拒 → 正确输入登录成功跳分析页。
- [ ] AC-002b-1（e2e-browser，/login，mobile）：卡片 offsetWidth=342（390−48）；`documentElement.scrollWidth <= 390`。
- [ ] testing / lint / type：`npm run test`、`npm run e2e`、`npm run lint`、`npm run typecheck`。

## 备注
依赖 001b 的 BreakpointState。`/login` 渲染在 AppLayout 之外、无任何导航 chrome（门禁#6 对 /login 单独断言「两种导航均不存在」）。

## 执行记录（Executor，awaiting_validation）
分支 `feat/002b-login`，commit `bd64894`。

- **实测发现**：rev 1 的登录卡几何在 mobile 已达标，无需改 CSS。`src/design/global.css` 全局 `box-sizing: border-box`；`.login` 外层 padding `var(--space-5)`=24px；`.login__card` `width:100%; max-width:360px`。390px 视口下内区 = 390−24×2 = 342px < 360，卡片 border-box offsetWidth = 342，卡片恰好铺满内区、无横向溢出。rev 1 仅缺该视口的 e2e 验证（此前只在桌面宽度跑过）。
- **改动**：仅新增 AC-002b-1 的 e2e（`tests/e2e/login.spec.ts`）——mobile 390 视口下 `.login__card` offsetWidth=342 且 `documentElement.scrollWidth<=390`。**未改 LoginForm.tsx 逻辑、未改 LoginForm.css**（符合 C-2「无功能/API 变更」「token 承接」——卡片样式已全量引用 design token）。
- **门禁全绿**：`npm run e2e`（15 通过，含新 AC-002b-1 + 门禁#1 登录链路）、`npm run test`（170 通过）、`npm run lint`、`npm run typecheck`。
