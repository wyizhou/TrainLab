---
id: "011"
status: verified
source_design_rev: 1
supersedes: null
superseded_by: null
contract_ref: "C-11"
branch: "feat/011-connector-auth"
---

# 连接器·授权登录弹窗 ConnectorAuthModal

## 背景 / 目标
落成 contract C-11。佳明授权弹窗，可选 2FA 两段式。依赖 010。

## 范围
- 做：账号/密码/2FA 勾选；未勾选一次接入；勾选走两段式 6 位验证码；校验与 busy 态。
- 不做：真实鉴权（模拟）。

## 涉及组件 / token
ConnectorAuthModal。

## 验收标准（来源：contract.md C-11）
- [ ] 未勾选 2FA：一次登录接入。
- [ ] 勾选 2FA：校验账密→6 位验证码区（勾选锁定）→再次登录后台验证；校验/busy 齐全。
- [ ] e2e（门禁#2）：2FA 两段式直到接入成功。
- [ ] testing/lint/type：G-* 基线。
