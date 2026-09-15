# 默认邮箱与官方认证

私有 `Email.md` 中可保留说明文字，但邮箱必须单独占一行、仅出现一次。填写自己的 Gmail，同时用于发送和接收；不填显示姓名、多个地址、Token 或 Client secret。公开空模板在 `config/examples/Email.template.md`。
服务配置只填写 `email_file` 和 `token_file` 路径；路径相对明确实例根，或指向原私有位置的绝对路径。文件必须 0600、私有父目录 0700，不使用符号链接。Token 与 OAuth Client 必须留在仓库外；更改邮箱后实际 Gmail profile 必须重新匹配，不能用另一账号发送。

首次授权是单独、明确执行的维护命令，weekly/daemon 不自动打开浏览器：

```sh
python skills/gmail-sender/scripts/gmail_rest_auth.py --instance /私有实例 --client-file /私有认证/desktop-client.json --email-file /私有实例/Email.md --token-file /私有认证/token.json --receipt /私有认证/gmail-api-auth-receipt.json
```

沿用 Google Desktop InstalledAppFlow、PKCE 与 127.0.0.1 随机端口，login_hint 只作提示，最终核对实际 profile。已存在 Token 或同目录固定 receipt 时不覆盖。失效/撤销需由用户明确重新授权；正常单次刷新保持原 Scope、原子写入和旧 Token 恢复。首次申请 `https://www.googleapis.com/auth/gmail.modify`，覆盖读取、发送和标签，不申请整邮箱永久删除权限。旧 send+readonly Token 保留读取旧记录的能力，不能通过刷新得到标签权限。

# 标签与投递账本

新邮件请求使用 `fit_delivery_request_v2`，仍沿用原 v1 intent/call/result 的结构与每 action 一次写入门禁。旧请求、SHA、标题、预算与成功/unknown 均按保存格式恢复；旧冻结选择缺少 mail_version 时保持 v1，不追补标签。

| 动作 | 稳定 action_key | 工具和边界 |
| --- | --- | --- |
| 确认账号标签 | `gmail-label:<默认账号的SHA256>` | gmail.profile、gmail.labels.list；无 TrainLab 用户标签时最多一次 gmail.labels.create，随后读回 |
| 发送 | 原 weekly 或 sync-batch 邮件 action | gmail.profile、gmail.send、gmail.get；响应丢失用 capture 或 gmail.list 唯一查询恢复 |
| 给邮件贴标 | `<邮件action>:label` | gmail.profile、gmail.get、gmail.modify、gmail.get；仅添加 TrainLab，不移除其他标签 |

所有可能刷新另计 gmail.refresh。调用次数为每授权共享耐久预算；创建/发送/贴标分别独立授权，不能只写邮件的 action 或漏掉标签额度。标签动作日期采用首次来源日期，跨日期恢复必须明确包含原日期。成功动作不再次调用 Provider。创建响应丢失只查询标签；贴标响应丢失只读邮件；缺确认保持 unknown。标签未确认不会重发成功邮件；新整体投递必须发送、标签均成功才返回 success/complete。返回中 mail、ensure_label、label 各自显示真实状态，status 反映整个投递。

周标题固定为 `TrainLab｜每周训练报告｜回顾{中文开始日期}—{中文结束日期}｜计划{中文开始日期}—{中文结束日期}`。回顾保留香港上周日15:00至本周日15:00前闭后开窗口，计划为下一周一至周日。迟发使用原期次，补发说明放正文，不用发送当天生成新标题。

只读 reconcile 禁止 gmail.send、gmail.labels.create、gmail.modify 等所有写工具；prepared 保留待授权，unknown 仅查询。同步、weekly、daemon 与 status 均识别标签动作。合成检查不能证明真实 OAuth、邮箱或服务已验收。
