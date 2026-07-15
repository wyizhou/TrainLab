---
id: "003"
status: verified
source_design_rev: 1
supersedes: null
superseded_by: null
contract_ref: "C-3"
branch: "feat/003-session-rail"
---

# 分析·多会话 SessionRail

## 背景 / 目标
落成 contract C-3。分析页左侧多会话管理。

## 范围
- 做：212px 会话栏、新建/重命名（行内 Enter/Esc）/删除、选中态色条、删空自动新建；平板降级下拉。
- 不做：会话内容/消息渲染（属 C-5/C-6）。

## 涉及组件 / token
SessionRail。

## 验收标准（来源：contract.md C-3）
- [ ] 会话栏 212px：新建主按钮、会话项（名称+消息数、选中左侧强调色条）。
- [ ] 行内重命名 Enter 确认/Esc 取消；删当前切第一个；删空自动新建。
- [ ] 平板 `<980px` 降级为顶部下拉 + 新建。
- [ ] e2e：新建→重命名→删除至空自动新建。
- [ ] testing/lint/type：G-* 基线。

## 验收记录（Validator，2026-07-10）
按 contract C-3 标准（G-* + e2e 完整链路），在 `feat/003-session-rail` 分支执行：
- **G-type**：`npm run typecheck`（tsc --noEmit）0 error。✅
- **G-lint**：`npm run lint`（eslint --max-warnings 0 + prettier --check + stylelint）0 error / 0 warning。✅
- **G-unit**：`npm run test`（vitest run）30/30 通过，含新增 `SessionRail.test.tsx` 7 项、`useSessions.test.ts` 6 项、`AnalysisPage.test.tsx` 1 项。✅
- **G-e2e**：`npm run e2e`（Playwright，desktop 1280×800）4/4 通过——含 `session-rail.spec.ts`（新建→重命名→删除至空自动新建完整链路），C-1/C-2 回归仍绿。✅

结论：**verified**。合并 `feat/003-session-rail` → `main`（--no-ff），迁移至 `completed/`，删除分支。
