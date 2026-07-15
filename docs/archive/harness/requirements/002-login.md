---
id: "002"
status: verified
source_design_rev: 1
supersedes: null
superseded_by: null
contract_ref: "C-2"
branch: "feat/002-login"
---

# 登录页 LoginForm

## 背景 / 目标
落成 contract C-2。独立登录页，演示级校验。

## 范围
- 做：居中卡片（用户名/密码/4 位验证码可刷新）、回车提交、错误提示、登录跳分析页。
- 不做：真实鉴权、注册、找回密码、营销元素。

## 涉及组件 / token
LoginForm。

## 验收标准（来源：contract.md C-2）
- [ ] 字段与刷新验证码、回车提交、错误提示可见；无营销元素。
- [ ] 任意用户名 + 密码 ≥4 位 + 验证码正确 → 进入分析页；任一不满足 → 报错不跳转。
- [ ] e2e（门禁#1）：错误验证码被拒 → 正确输入登录成功跳分析页。
- [ ] testing/lint/type：G-* 基线。

## 验收记录（Validator，2026-07-10）
按 contract C-2 标准（G-* + 门禁#1 e2e），在 `feat/002-login` 分支执行：
- **G-type**：`npm run typecheck`（tsc --noEmit）0 error。✅
- **G-lint**：`npm run lint`（eslint --max-warnings 0 + prettier --check + stylelint）0 error / 0 warning。✅
- **G-unit**：`npm run test`（vitest run）16/16 通过，含新增 `LoginForm.test.tsx` 7 项。✅
- **G-e2e**：`npm run e2e`（Playwright，desktop 1280×800）3/3 通过——含门禁#1 `login.spec.ts`（错误验证码被拒 → 正确输入登录成功跳分析页），C-1 五路由回归仍绿。✅

结论：**verified**。合并 `feat/002-login` → `main`（--no-ff），迁移至 `completed/`，删除分支。
