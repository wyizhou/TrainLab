---
id: "014"
status: verified
source_design_rev: 1
supersedes: null
superseded_by: null
contract_ref: "C-14"
branch: "feat/014-settings"
---

# 设置 SettingsSections

## 背景 / 目标
落成 contract C-14。设置五分组。被 006（AI 接口/系统提示词）、008（区间设定）反向消费。

## 范围
- 做：账户信息/单位制/区间设定/数据保留策略/AI 接口 五分组；区间设定仅作标注边界。
- 不做：把区间用于系统计算衍生指标。

## 涉及组件 / token
SettingsSections。

## 验收标准（来源：contract.md C-14；不要求 e2e）
- [ ] 五分组齐全（账户新密码×2 一致校验 / 单位制 / 区间设定 MaxHR·LTHR·FTP·Z1–Z4 上界 / 数据保留策略占用+期限+自动清理 / AI 接口 base_url 默认 deepseek + Key + 模型名 + 测试连接 + 系统提示词查看）。
- [ ] 区间设定仅作标注边界（供 C-8/C-6），不用于计算。
- [ ] unit：密码不一致报错；区间写入后被详情页读取。
- [ ] testing/lint/type：G-* 基线。
