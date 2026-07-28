# Legacy 与回滚材料

本目录保存已被当前 Garmin 五层架构替代、但在生产切换和回滚验证完成前仍需保留的
说明。它们不是当前运行配置、数据权威来源或新功能的设计依据。任何重启旧链路的
操作都必须使用具名备份、校验清单和单独授权；不得以旧路径覆盖
`state/foundation/` 的当前数据。

| 子目录 | 内容 | 当前状态 |
|---|---|---|
| [drive/](drive/) | Google Drive、rclone、旧 `source/` 同步 | 仅用于迁移排查与受控回滚 |
| [garmin/](garmin/) | 早期 Garmin shadow 对账记录 | 仅作历史对账说明，不恢复旧命令 |
| [operations/](operations/) | 早期多服务部署观测 | 仅作历史环境记录 |
| [training/](training/) | Apple Health、旧心率/训练策略 | 仅作历史说明；当前分析以 Garmin 与 Hansons 规则为准 |

当前的 Gmail MCP 接入说明继续保留在
[`references/gmail_mcp_setup.md`](../../references/gmail_mcp_setup.md)，因为它仍为当前
`gmail` MCP 集成的参考资料。

`harness/runtime/HARNESS.md` 与其输入/输出 schemas 也保留为旧 Runtime 路线的历史
证据；当前分析和邮件路线不加载它们。

本机旧根数据库、旧 `source/` 输入和退役私有配置存放在被 Git 忽略的
`state/legacy/root-runtime-2026-07-28/`，目录内的
`MOVE-MANIFEST.sha256` 用于验证搬迁与回滚；它不是当前数据源。
