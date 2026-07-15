---
id: "011b"
status: verified
source_design_rev: 2
supersedes: "011"
superseded_by: null
contract_ref: "C-11"
branch: "feat/011b-connector-auth"
---

# 授权弹窗 mobile 全屏（返工）

## 背景 / 目标
落成 contract C-11（返工，design_rev 2）。mobile 弹窗全屏化（offsetWidth=视口宽、border-radius=0）、desktop 居中定宽 390px、border-radius=14px。rev 1 2FA 两段式流程全部保留。原 011 留 `completed/` 当 rev 1 历史，不改写。

## 范围
- 做：ConnectorAuthModal mobile 全屏、desktop 居中定宽的断点响应。
- 不做：2FA 两段式流程逻辑改动（rev 1 原样保留）。

## 涉及组件 / token
ConnectorAuthModal、弹窗宽度/圆角 token。

## 验收标准（来源：contract.md C-11，Validator 只认该条目）
- [ ] rev 1 功能判据保留：字段（账号/密码/「启用了 2FA」勾选），未勾选一次登录接入；勾选 2FA 两段式（校验账密→6 位验证码输入区锁定→再次登录模拟验证），校验与 busy 态齐全。
- [ ] e2e（门禁#2）：2FA 两段式流程直到接入成功。
- [ ] AC-011b-1（e2e-browser，/connectors，[mobile,desktop]，前置：打开 2FA 授权弹窗）：mobile 面板 offsetWidth=390、`border-radius=0px`；desktop 面板宽 390px、居中、`border-radius=14px`。
- [ ] testing / lint / type。

## 备注
依赖 001b、010b。
