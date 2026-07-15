---
id: "012"
status: verified
source_design_rev: 1
supersedes: null
superseded_by: null
contract_ref: "C-12"
branch: "feat/012-conflict-merge"
---

# 连接器·双账号合并 ConflictBanner + ConflictModal

## 背景 / 目标
落成 contract C-12。双账号按开始时间+时长去重与冲突处理。依赖 010、011。

## 范围
- 做：自动去重（开始时间+时长）保留来源标注、冲突横幅、逐组保留选择弹窗、确认合并。
- 不做：跨设备更多合并策略。

## 涉及组件 / token
ConflictBanner、ConflictModal。

## 验收标准（来源：contract.md C-12）
- [ ] 自动去重规则正确、来源标注保留。
- [ ] 无法自动判定→横幅「发现 n 组疑似重复」+「处理重复」→逐组选保留中国区/国际区→确认合并。
- [ ] 演示：连接国际区后出现 2 组冲突。
- [ ] e2e（门禁#3）：触发冲突→逐组选择→合并后横幅消失。
- [ ] testing/lint/type：G-* 基线。
