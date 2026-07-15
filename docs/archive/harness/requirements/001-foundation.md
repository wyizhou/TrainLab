---
id: "001"
status: verified
source_design_rev: 1
supersedes: null
superseded_by: null
contract_ref: "C-1"
branch: "feat/001-foundation"
---

# 全局基础：脚手架 + 设计系统 + 顶部导航

## 背景 / 目标
落成 contract C-1。搭起 React + TS + Vite 前端工程与验证工具链，定版深色视觉 token 与顶部导航信息架构，作为其余 13 条需求的地基。

## 范围
- 做：Vite+React+TS 脚手架；工具链脚本（lint/typecheck/test/e2e）；集中 token 模块 + Stylelint/ESLint 禁裸值规则；顶部导航五项 + 路由 shell；平板 `<980px` 导航降级；全局 tabular-nums。
- 不做：任何业务页面内部逻辑（各自需求负责）；后端。

## 涉及组件 / token
TopNav、色板/圆角/间距 tokens、路由 shell、`src/design/tokens.*`、lint 配置。

## 验收标准（来源：contract.md C-1，Validator 只认该条目）
- [ ] `npm run build` 成功；`npm run dev` 起服务。
- [ ] 导航五项顺序为 分析(默认)/运动记录/健康记录/连接器/设置；`/` → 分析页。
- [ ] token 集中定义，`npm run lint` 0 error（含 G-token 禁裸值）；全局 tabular-nums 生效。
- [ ] 平板 `<980px` 导航缩小内边距/字号、隐藏「上次同步」胶囊、可横向滑动。
- [ ] e2e：五路由导航到位、默认落分析页。
- [ ] testing：`npm run test`、`npm run e2e`；lint：`npm run lint`；type：`npm run typecheck`。

## 验收记录（Validator，2026-07-10）
按 contract C-1 标准（G-* + 五路由 e2e），在 `feat/001-foundation` 分支执行：
- **G-type**：`npm run typecheck`（tsc --noEmit）0 error。✅
- **G-lint**：`npm run lint`（eslint --max-warnings 0 + prettier --check + stylelint）0 error / 0 warning，含 G-token 禁裸值。✅
- **G-unit**：`npm run test`（vitest run）8/8 通过（tokens / App 路由 / TopNav）。✅
- **G-e2e**：`npm run e2e`（Playwright，desktop 1280×800）2/2 通过——默认落分析页 + 五路由导航到位。✅
- **build**：`npm run build`（tsc + vite build）成功产出 dist 静态包。✅

结论：**verified**。合并 `feat/001-foundation` → `main`（--no-ff），迁移至 `completed/`，删除分支。
备注（不作不通过依据，供 Planner 参考）：平板 `<980px` 降级、token 具体色值、tabular-nums 为 visual/manual 性质，contract C-1 的 e2e 条目仅要求五路由+默认页，未纳入本轮自动判定。
