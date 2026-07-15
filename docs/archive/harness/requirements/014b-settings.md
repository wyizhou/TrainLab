---
id: "014b"
status: verified
source_design_rev: 2
supersedes: "014"
superseded_by: null
contract_ref: "C-14"
branch: "feat/014b-settings"
---

# 设置：删除数据保留 + 响应式（返工，scope）

## 背景 / 目标
落成 contract C-14（返工，design_rev 2，**scope**）。分组由五 → 四：**删除「数据保留策略」分组**（占用统计/保留期限/到期自动清理开关），系统不再提供整体删除/到期自动清理数据功能；mobile 心率区间输入 2×2 网格。rev 1 其余分组与区间边界联调保留。原 014 留 `completed/` 当 rev 1 历史，不改写。

## 范围
- 做：删除「数据保留策略」分组与相关 action（无到期清理/整体删除调用路径）；四分组（账户信息/单位制/区间设定/AI 接口）；mobile 心率区间输入 `repeat(2,1fr)`、desktop/tablet `repeat(4,minmax(80px,1fr))`。
- 不做：账户密码校验/区间边界联调（rev 1 保留）；单位制/AI 接口字段改动。

## 涉及组件 / token
SettingsSections（−RetentionGroup）、心率区间输入 grid token。

## 验收标准（来源：contract.md C-14，Validator 只认该条目）
- [ ] 分组由五 → 四：账户信息 / 单位制 / 区间设定 / AI 接口（base_url 默认 `https://api.deepseek.com` / API Key / 模型名 / 测试连接 / 隐藏系统提示词查看）；rev 1「数据保留策略」分组删除。
- [ ] 区间设定仅作原始数据标注边界（供 C-8 心率区间图 + AI 对话），系统不用于计算；账户密码一致性校验保留（unit）。
- [ ] 系统不提供整体删除 / 到期自动清理数据功能（无相关 action，unit 断言无此调用路径）。
- [ ] AC-014b-1（e2e-browser，/settings，[mobile,desktop]）：页面不存在文本「数据保留策略」「到期自动清理」「保留期限」；无对应控件。
- [ ] AC-014b-2（e2e-browser，/settings，mobile）：心率区间输入 `repeat(2,1fr)`（首行 2 框 top 相同、第 3 个换行）；desktop/tablet `repeat(4,minmax(80px,1fr))`。
- [ ] unit：密码不一致报错；区间设定写入后被 C-8 详情页读取（联调保留）。
- [ ] testing / lint / type。

## 备注
依赖 001b；被 006b（AI 接口/系统提示词查看）、008b（心率区间边界）反向消费——全前端共享 settings store，先落默认值，014b 落成后接入。
