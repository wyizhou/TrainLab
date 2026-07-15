---
id: "007"
status: verified
source_design_rev: 1
supersedes: null
superseded_by: null
contract_ref: "C-7"
branch: "feat/007-activity-list"
---

# 运动记录·列表 ActivityTable + Pager

## 背景 / 目标
落成 contract C-7。运动记录列表页。

## 范围
- 做：列集、类型筛选胶囊实时过滤、分页 20/50/100、单条/批量 FIT 下载（模拟）。
- 不做：详情页（C-8）、上传入库（C-13）。

## 涉及组件 / token
ActivityTable、Pager。

## 验收标准（来源：contract.md C-7）
- [x] 列：复选框/日期/类型色点/名称/距离/时长/平均心率/配速或功率/来源/单条 FIT 下载。
- [x] 类型筛选（全部/跑步/骑行/游泳/力量/越野跑）实时过滤；分页 20(默认)/50/100。
- [x] 批量「下载选中 FIT (n)」计数随勾选更新。
- [x] e2e：筛选+翻页+批量勾选计数。
- [x] testing/lint/type：G-* 基线。

## 验收记录（Validator）
- 日期：2026-07-11
- 被测分支：feat/007-activity-list（合并 commit d142dc8）
- G-type `tsc --noEmit`：0 error。
- G-lint（ESLint + Prettier + Stylelint）：0 error / 0 warning。
- G-unit（Vitest）：72/72 全绿，含 ActivityTable / Pager / ActivitiesPage / activityData 专项。
- C-7 e2e（门禁：筛选+翻页+批量勾选计数）：1 passed。
- 判定：**verified**。
