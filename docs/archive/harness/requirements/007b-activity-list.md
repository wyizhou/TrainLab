---
id: "007b"
status: verified
source_design_rev: 2
supersedes: "007"
superseded_by: null
contract_ref: "C-7"
branch: "feat/007b-activity-list"
---

# 运动列表响应式（返工）

## 背景 / 目标
落成 contract C-7（返工，design_rev 2）。mobile 隐藏大表、渲染卡片列（ActivityCardList，新，mobile 形态）；desktop 反之。rev 1 列集/筛选/分页/批量计数全部保留。原 007 留 `completed/` 当 rev 1 历史，不改写。

## 范围
- 做：mobile `min-width:960px` 表格容器 display=none + 卡片列；desktop 表格显示、无卡片列；两视口无横向溢出（表格内横滚不外溢页面）。
- 不做：列集/筛选/分页/批量逻辑改动（rev 1 原样保留）。

## 涉及组件 / token
ActivityTable、ActivityCardList（新）、Pager。

## 验收标准（来源：contract.md C-7，Validator 只认该条目）
- [ ] rev 1 功能判据保留：列（复选框/日期/类型色点/名称/距离/时长/平均心率/配速或功率/来源/单条 FIT 下载）；类型筛选胶囊实时过滤；分页 20(默认)/50/100；批量「下载选中 FIT (n)」计数随勾选更新。
- [ ] e2e：筛选 + 翻页 + 批量勾选计数。
- [ ] AC-007b-1（e2e-browser，/activities，[mobile,desktop]）：mobile 表格容器 display=none、卡片数=min(每页条数,剩余条数)；desktop 表格 display≠none 且无卡片列；两视口无横向溢出。
- [ ] testing / lint / type。

## 备注
依赖 001b。
