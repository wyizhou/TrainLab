---
id: "013"
status: verified
source_design_rev: 1
supersedes: null
superseded_by: null
contract_ref: "C-13"
branch: "feat/013-file-upload"
---

# 连接器·文件上传 FileUpload

## 背景 / 目标
落成 contract C-13。连接器页内 FIT/TCX/GPX 上传入库。依赖 007、010。

## 范围
- 做：多选上传（≤50MB 超限拒绝）、已解析文件列表、入库后进运动记录标来源「FIT上传」。
- 不做：真实云同步。

## 涉及组件 / token
FileUpload。

## 验收标准（来源：contract.md C-13；不要求 e2e）
- [x] FIT/TCX/GPX 多选、单文件 ≤50MB 超限拒绝提示。
- [x] 已解析文件列表（名称/大小/时间/已入库）；入库后出现在运动记录、来源「FIT上传」。
- [x] unit：>50MB 或非法扩展名被拒；合法文件进入列表。
- [x] testing/lint/type：G-* 基线。

## 验收记录（Validator，2026-07-11）
- G-type：`npm run typecheck` 0 error。
- G-lint：`npm run lint` 0 error / 0 warning（ESLint + Prettier + Stylelint）。
- G-unit：`npm run test` 32 文件 154 测试全绿；含 `uploadImport.test.ts`（validateUpload 拒绝非法扩展名/超限、FIT/TCX/GPX 解析）与 `FileUpload.test.tsx`（超限拒绝不入库、已解析列表、入库进 ActivitiesPage 标 FIT上传）。
- e2e：契约 C-13 不要求；合并前跑门禁冒烟集回归，9/9 全绿，无回归。
- 判定：通过。分支合并入 main，迁移至 completed/，状态置 verified。
</content>
</invoke>
