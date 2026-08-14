# M4-15 真实 Gmail 验收记录

日期：2026-07-27

范围：第四层固定 recipient 的真实读取、发送、标签、无标签跟踪与发送结果对账

数据原则：不记录邮箱地址、邮件正文、provider 明文 ID、OAuth 信息或 token

## 前置证据

- 当前 Codex 环境中的服务器名称为 `gmail`。
- 注册包精确为 `@artymclabin/gmail-mcp`，未使用主机固定命令、cwd 或复制凭据。
- 项目通用 `config/trainlab.json` 已配置有效 `mail.recipient_email`，该文件受 Git 忽略。
- Foundation `PRAGMA integrity_check` 为 `ok`。
- 写入前备份 ID：`mail-m4-15-20260727T025811Z`。
- 备份大小：3,703,128,064 bytes。
- 备份 SHA-256：`7da86002291403b4ab2cba4685e19228aa3b07af4674213c6c08c181da36cf4d`。

## 验收结果

1. 只读搜索找到 1 个近期 TrainLab thread；完整 thread 读取成功，未输出正文或地址。
2. 实际 provider 使用 RFC 2822 `Date`；adapter 已将其严格规范化为 UTC，同时保留原始
   provider payload。
3. 首次生产 poll 暴露了 raw 根路径组合错误；修复后 poll 成功归档并规范化 1 个 thread
   和 1 条 message。
4. 固定 recipient 真实发送 1 次成功；未传 `from`、CC、BCC、attachment 或自由 query。
5. 相同 idempotency marker 第二次调用返回 `already_sent`，未再次发送。
6. 独立 marker 对账只找到 1 个 provider 结果，证明 receipt 丢失时可进入唯一对账路径。
7. TrainLab 标签成功应用。临时移除该测试 thread 全部消息的 TrainLab 标签后，
   `tracked_threads` poll 仍成功；测试结束后标签全部恢复。
8. 发送后的再次 poll 成功归档新增消息；由于这次发送不属于生产 delivery 记录，
   该消息按安全规则进入 quarantine，没有被误当成用户请求或再次回复。
9. Gmail recipient identity 只以 HMAC 写入 `subject_identities`；数据库没有保存明文地址。
10. 最终 Foundation 完整性为 `ok`，Gmail raw JSON 共 4 份、17,373 bytes；未删除既有
    raw、FIT、健康数据、邮件数据或备份。

脱敏 provider message SHA-256：
`e88134b1ee28480c7211cef710a58334478e1cb18207c470dabdc80737f0865b`

脱敏 provider thread SHA-256：
`e245dec008706e893af4aa9a7208b56f4f083f3f17c6c2acf6e52b0f5afca54e`

## 未开放的门

- 没有启用 daemon、timer、第五层调度或双写。
- 没有执行第三层计划修订，也没有代发第三层 artifact。
- M4-14B/X-04 仍必须等待第五层 S5-10；生产 cutover 与 IG-7 在该跨层门完成前保持关闭。

## 最终离线复验

- 完整第四层邮件/Gmail 离线回归通过。
- 全项目离线回归通过。
- 首次 identity provisioning 的确定性并发测试与连续 30 次独立复验通过。
- `compileall`、`git diff --check`、五层冻结契约哈希与独立只读终验通过。
