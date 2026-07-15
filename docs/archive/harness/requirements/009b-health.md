---
id: "009b"
status: verified
source_design_rev: 2
supersedes: "009"
superseded_by: null
contract_ref: "C-9"
branch: "feat/009b-health"
---

# 健康记录响应式（返工）

## 背景 / 目标
落成 contract C-9（返工，design_rev 2）。睡眠柱数按断点（desktop/tablet 14 根、mobile 7 根）；mobile 四张明细表行转卡片、无大表溢出。rev 1 五子标签/习惯/数据量级全部保留。原 009 留 `completed/` 当 rev 1 历史，不改写。

## 范围
- 做：睡眠柱数断点门控（mobile 7「近 7 天」/ tablet·desktop 14「近 14 天」）；mobile 四表（体重/RHR/HRV/睡眠明细）卡片模式、无 min-width 表格、无横向溢出。
- 不做：五子标签/习惯记录/数据量级逻辑改动（rev 1 原样保留）。

## 涉及组件 / token
HealthTabs、HealthTables、SleepChart、HabitPicker。

## 验收标准（来源：contract.md C-9，Validator 只认该条目）
- [ ] rev 1 功能判据保留：五子标签（睡眠/体重/RHR/HRV/习惯）；习惯（日期选择+已记录计数、四组因子胶囊按日期存储）；数据量级（体重·RHR·HRV ≥30 行、睡眠 ≥14 行、分页 20/50/100）。
- [ ] unit：行数下界与分页档位断言；渲染无错。
- [ ] AC-009b-1（e2e-browser，[mobile,tablet]）：mobile 睡眠柱=7 根（标题含「近 7 天」）；tablet=14 根（含「近 14 天」）。
- [ ] AC-009b-2（e2e-browser，mobile）：四表卡片模式无 min-width 表格元素；`scrollWidth <= 390`。
- [ ] testing / lint / type。

## 备注
依赖 001b。不要求功能 e2e（unit 覆盖），AC-009b-* 响应式 e2e-browser 为验收组成部分。
