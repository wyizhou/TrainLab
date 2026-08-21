# M10 Gmail 传输回归映射

本文件只记录脱敏的工程失败事实，不含邮箱地址、邮件正文、Token 或 Candidate 内容。

| 迭代 | Block 原因 | r06 处理 | REST 回归 |
| --- | --- | --- | --- |
| r04 | MCP 调用结果未能由后续进程可靠保存，首封终态为 `unknown` | 保留历史，不改写；新批次不复用旧动作 | send 响应丢失后只按稳定 Message-ID 查询，不重发 |
| r04 | 精确查询一次未落账、一次 0 命中 | 本地账本不再冒充远程事实根 | list 0/1/2 条分别发送、复用、阻断 |
| r05 | 草稿、发送、下载跨 MCP 文本适配与 SQLite 触发器重复表达 | 删除未交付 MCP host，改用官方 REST JSON | RAW MIME 读回并核对收件人、主题、text、HTML、Message-ID |
| r05 | 同 UID 可构造本地文件和 SQL，伪造自洽“远程证明” | A-010 明确 owner-only Candidate/单写者为可信运行边界 | Validator 只检查应用 API、正常崩溃恢复、幂等和数据一致性 |
| r05 | Provider 已产生副作用、本地未落账之间不存在共同事务 | durable intent 先于 send；发送一旦开始永不自动重发 | Provider 成功后进程中断的恢复仅查询 Message-ID |
| r05 | 临时 finalizer/人工转抄造成结果丢失窗口 | 单进程完成查询、send、RAW、capture、SQLite 终态 | capture 先落 owner-only 文件，成功结果再写 SQLite |
| r06 首次Code Validator | OAuth库也接受`web` client，不能只依赖类名声称Desktop | 在打开浏览器前解析owner-only JSON并只接受完整`installed`客户端 | `web`客户端在flow/profile调用前拒绝 |
| r06 首次Code Validator | 认证profile 1次调用未进入持久总账 | 认证回执强制落盘并绑定Candidate；认证1次与投递最多128次共同受129次总预算约束 | 认证1次+投递128次后下一次调用在传输前拒绝 |
| r06 首次Code Validator | 无refresh token凭据会被误报成功但投递无法重载 | 发布前验证authorized-user字段、refresh token、Scopes并真实重载 | 缺refresh token在profile前阻断且不发布Token |
| r06 最终Code Validator | profile请求已经发出，但连接错误、5xx或错误JSON没有失败回执 | profile各终态同步写入脱敏owner-only回执，失败不发布Token | 三类失败均记录`blocked/provider_calls=1/token_published=false` |
| r06 最终Code Validator | Desktop结构存在但OAuth端点未锁定为Google官方端点 | 浏览器打开前精确校验授权与换Token地址 | 两个伪造端点分别在Provider调用0时拒绝 |
| r06 查询合同澄清 | 旧实现每阶段最多3次，不能覆盖已批准的短暂网络波动窗口 | lookup/recovery、RAW和confirmation各持久共享5次，等待1/2/4/8秒 | 第1至5次恢复、跨进程预算、5次耗尽与429/5xx回归 |
| r06 发送合同澄清 | Gmail没有公开幂等键，0命中不能证明可以安全重发 | 每个动作持久send上限固定1；发送后只查询，耗尽后`unknown` | 响应丢失、重启、重放和5次0命中均证明POST不超过1次 |
| r06窄化Validator | profile失败回执路径可由调用方更换，重启后会重新获得profile预算 | Client、收件配置、Token和认证回执固定为`source/`下唯一文件；任意替代路径在浏览器前拒绝 | 首次profile失败后改任一私有路径重启仍为Provider 0次，旧回执与Token保持不变 |
| r06最终Validator | 认证入口虽已锁路径，Candidate构建和REST Client仍接受替代邮箱/Token；普通程序异常也被当作连接错误重试 | 构建、认证、投递三处共享固定私有路径；只重试连接/超时异常，其他请求异常立即停止 | 替代recipient/token/receipt均Provider 0次拒绝；lookup和RAW普通异常均只调用1次且等待0次 |

仍适用的旧安全场景已经迁移到 `test_m10_gmail_rest.py`：权限和原子写、固定收件人、确定性
内容、0/1/2 命中、401/403/5xx/连接丢失、响应丢失恢复、RAW 字段不匹配、canary 门、零重发、
调用预算、成功重放和 Git 私有边界。旧 MCP 工具名、文本解析和“本地账本不可伪造”对抗不再是
A-010 下的产品合同，不能作为 REST 交付阻断。
