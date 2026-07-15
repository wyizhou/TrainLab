---
id: "006b"
status: verified
source_design_rev: 2
supersedes: "006"
superseded_by: null
contract_ref: "C-6"
branch: "feat/006b-chat-html"
---

# 分析·对话气泡返工（返工）

## 背景 / 目标
落成 contract C-6（返工，design_rev 2）。用户/AI 气泡尾角不对称 4px；AI 气泡移除 46% 最小宽度（自 005b 移交）、max-width 按断点分级。rev 1 AI HTML 渲染/系统提示词/安全白名单全部保留。原 006 留 `completed/` 当 rev 1 历史，不改写。

## 范围
- 做：气泡尾角不对称圆角（用户 bottom-right 4px、AI bottom-left 4px，其余三角 14px）；AI 气泡 min-width→auto/0、max-width 断点分级（mobile 100%）。
- 不做：HTML 渲染/白名单/系统提示词逻辑改动（rev 1 原样保留）。

## 涉及组件 / token
ChatMessage、SysPrompt、气泡圆角/宽度 token。

## 验收标准（来源：contract.md C-6，Validator 只认该条目）
- [ ] rev 1 功能判据保留：AI HTML 渲染（表格/有序列表、计划 7 天课表、健康/习惯解读段）；隐藏系统提示词随请求发送、不入对话流、设置可查看/收起；转义/白名单禁脚本；unit（含系统提示词不入 DOM、`<script>` 不执行）。
- [ ] AC-006b-1（e2e-browser，desktop，前置：发一条分析消息）：用户气泡 `border-bottom-right-radius=4px`、其余三角 14px；AI 气泡 `border-bottom-left-radius=4px`、其余三角 14px。
- [ ] AC-006b-2（e2e-browser，[mobile,desktop]，前置：发一条 AI 回复入 DOM）：AI 气泡 computed `min-width` 解析 auto/0；mobile computed `max-width` 解析为容器 100%；均直接读 computed 值、与内容长度无关。
- [ ] e2e：见 005b 门禁#5 联合流。
- [ ] testing / lint / type。

## 备注
依赖 001b、005b（46% 最小宽移交自 005b）。
