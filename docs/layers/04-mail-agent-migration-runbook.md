# 第四层邮件 Agent：M4-15 离线迁移与回滚包

状态：离线准备和 M4-15 真实 Gmail 验收已完成；生产 cutover 与 IG-7 仍等待
M4-14B/S5-10/X-04。

## 离线准备

`trainlab.mail_agent.migration` 只对比脱敏的 thread、message、response、delivery 和
cursor 元数据。比较结果不得携带邮件正文、健康数据、OAuth 凭据或模型输出。任何缺失、
重复或状态不一致都冻结切换。

切换前需要：具名备份 ID、无差异的 shadow 对账、且旧/新路径恰有一个写入者启用。新旧
路径不得同时处理同一 provider message，也不得由第四层代发第三层 artifact。

## 真实环境授权门

以下三项必须由用户在执行前明确授权，离线测试和本文件均不构成授权：

- 受控账号的只读 recipient-config/poll；
- 一次指定的固定 `mail.recipient_email` send；
- 对该次发送中断或未知结果的 reconcile。

未获得相应授权时，保持当前单写路径，记录缺少的授权并停止；不得尝试 Gmail MCP、复制
token、启用第五层调度或猜测验收结果。

2026-07-27 已取得上述授权并完成真实验收，脱敏记录见
[M4-15 真实 Gmail 验收记录](evidence/mail/M4-15-real-gmail-acceptance-2026-07-27.md)。
本次只使用当前环境名为 `gmail`、包为 `@artymclabin/gmail-mcp` 的绑定；没有读取
provider 登录身份，也没有把 recipient、token 或邮件正文写入验收文档。

## 回滚

发现 shadow 差异、未知投递、重复回复或身份漂移时，立即冻结 cutover。先停止新写入者，
保留具名备份和原始证据，再由人工审查决定是否恢复旧路径。回滚也不得删除 raw、response
revision 或 delivery 记录，不得以重新发送修复未知投递。

本次没有启用第五层调度或生产 cutover。临时移除的测试标签已经恢复，Foundation
数据库完整性为 `ok`；写入前具名备份继续保留，未执行数据库回滚。
