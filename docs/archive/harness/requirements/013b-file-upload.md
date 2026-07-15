---
id: "013b"
status: verified
source_design_rev: 2
supersedes: "013"
superseded_by: null
contract_ref: "C-13"
branch: "feat/013b-file-upload"
---

# 文件上传响应式（返工）

## 背景 / 目标
落成 contract C-13（返工，design_rev 2）。上传区与已解析列表同 grid 规则，mobile 单列堆叠、无横向溢出。rev 1 多选/≤50MB 拒超限/已解析列表入库/来源标注全部保留。原 013 留 `completed/` 当 rev 1 历史，不改写。

## 范围
- 做：FileUpload 上传区 + 「已解析文件」列表 mobile 单列堆叠、无横向溢出。
- 不做：多选/大小校验/入库/来源标注逻辑改动（rev 1 原样保留）。

## 涉及组件 / token
FileUpload、上传区/列表 grid token。

## 验收标准（来源：contract.md C-13，Validator 只认该条目）
- [x] rev 1 功能判据保留：FIT/TCX/GPX 多选、单文件 ≤50MB（超限拒绝并提示）；「已解析文件」列表（名称/大小/时间/已入库），入库后出现在运动记录、来源标「FIT上传」。
- [x] unit：>50MB 或非法扩展名被拒；合法文件进入已解析列表。
- [x] AC-013b-1（e2e-browser，/connectors，mobile）：上传区与「已解析文件」列表 mobile 单列堆叠；`scrollWidth <= 390`。
- [x] testing / lint / type。

## 备注
依赖 001b、007b、010b。不要求功能 e2e（unit 覆盖），AC-013b-1 响应式 e2e-browser 为验收组成部分。

## 验收记录（Validator，2026-07-13）
- G-lint：`npm run lint` 0 error/0 warning ✓
- G-type：`npm run typecheck` 0 error ✓
- G-unit：`npm run test` 176/176 全绿（含 `uploadImport.test.ts` 8 项、`FileUpload.test.tsx` 4 项，覆盖 rev1 功能判据 + >50MB/非法扩展名拒绝）✓
- G-e2e：`npm run e2e` 30/30 通过；AC-013b-1（`tests/e2e/file-upload.spec.ts`）单列堆叠 + `scrollWidth<=390` 断言通过；门禁 #1–6 全过 ✓
- 结论：C-13 全部可验证标准通过 → verified。
