---
id: "009"
status: verified
source_design_rev: 1
supersedes: null
superseded_by: null
contract_ref: "C-9"
branch: "feat/009-health"
---

# 健康记录 HealthTabs + HabitPicker

## 背景 / 目标
落成 contract C-9。健康记录五子标签。

## 范围
- 做：睡眠/体重/静息心率/HRV/习惯 五标签、图表 + 明细表、习惯日期选择与四组因子勾选按日期存储、统一分页。
- 不做：AI 关联分析（消费方为 C-6）。

## 涉及组件 / token
HealthTabs、HabitPicker。

## 验收标准（来源：contract.md C-9；不要求 e2e）
- [ ] 五子标签内容齐全（睡眠深/浅/REM 堆叠柱+静息心率明细；体重曲线+体脂/肌肉/水分；RHR；HRV；习惯四组因子）。
- [ ] 数据量级（可数）：体重/RHR/HRV 各 ≥30 行；睡眠 ≥14 行；习惯抽样某日四组可勾选并计入已记录计数；各表分页 20/50/100。
- [ ] unit：行数下界 + 分页档位断言；渲染无错。
- [ ] testing/lint/type：G-* 基线。
