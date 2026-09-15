# FIT-only Garmin MCP 协议适配器

`skills/_shared/fit_weekly/garmin_fit.py` 是内部连接与解码层，已接入内部 FIT 同步编排，
没有公开采集命令，也未启用真实在线任务。
当前验收只使用合成 MCP/SDK，不连接 Garmin，不读取私人 Token，也不建立新在线授权。

## 保留与收窄

- 固定 MCP commit `3610be6feed93088d85b0f35aba9d7d07c2505a7`，沿用已保留的
  `garmin-sync/scripts/mcp_server_guard.py` 认证保护及 `live-overrides.txt` 两项精确依赖。
  这两个是保留的通用 Provider 组件，不依赖旧数据库、旧归档、日报或健康流程。
- 通过 PATH 查找 uvx；相对源码位置解析保护脚本，Token 和工作目录由实例显式传入，
  不固定本机目录。只允许离线缓存、禁配置/环境文件和 Python 下载，缓存缺失即失败。
- 仅暴露 `get_activities_by_date` 与 `download_activity_file`，不暴露健康、课表写入、
  GPX/TCX、目录配置工具。可选天气尚未接入，不能宣称已经采集。
- 用户级缓存 Token 不复制，与下载暂存根禁止重叠或互相嵌套；启动前/关闭后只在内存比较文件和元数据，
  不把 Token 内容或摘要保存到 SQLite/capture/日志。密码、MFA、主动刷新与重试被禁用。
- stdio 进入、初始化、调用、退出均保持同一个异步任务；有限超时/失败关闭会话，
  不启动第二个会话或自动重试。正常主机上的子进程清理由 MCP SDK 承担。
- 编排器传入只读剩余预算回调；启动、初始化、工具发现和每次采集共用原截止时间。
  同步前检和解码后再核对剩余时间；超限结果不能作为成功采集。正常关闭和认证审计仍保留。
- 单写者会话期间，宿主MCP SDK诊断在进入任何日志handler前变为固定诊断码，保留错误等级，
  移除响应正文、异常文本和堆栈；退出后恢复进程原日志工厂，不修改磁盘或用户全局配置。
  关闭失败、认证文件有限IO失败均返回固定错误码，不能据此发布成功。

## 三种不同结果

| Provider 结果 | 本层结果 | 不代表什么 |
| --- | --- | --- |
| 完整合法页，活动数组为空 | 明确的空成员页 | 不跳过分页链或自动证明其他日期完整 |
| 精确 `No fit data returned for activity ID` | `no_fit/provider_no_original` | 不是“没有运动”，也不是下载成功 |
| 连接/认证/工具错误、错误文本、格式漂移 | 固定错误码，原响应可供私有保存 | 不能转成空页或无FIT |

分页验证日期、页号、页容量、count、has_more、next_page与活动身份。
只投影活动ID和当地活动日期供[同步账本](sync-calendar.md)使用；名字等其他MCP字段不进入该投影。
周窗口仍由后续FIT中的活动结束时间判定，不以inventory开始时间替代。

## FIT 与捕获边界

- 上游下载工具会覆盖同名文件，所以只接受本次新建的空私有暂存目录，绝不直接写入正式FIT目录。
- 返回的活动身份、FIT格式、精确暂存路径、大小以及目录唯一文件必须一致；拒绝软硬链接、
  空文件、宽权限、损坏CRC和非活动FIT。数据字节不改写，验证后返回SHA和相对文件名。
- `Captured.payload` 和 `CallFailure.payload` 是原始MCP TextContent的UTF-8字节，
  不是Garmin HTTP响应。仅由Host保存为私有capture，绝不传给AI。
- 若底层消息本身不是合法MCP响应，SDK未交出TextContent，则只保留固定故障状态，
  不把SDK日志冒充原始capture，也不把错误原文打到普通日志。
- 该层不擅自落库或声称成功回执已持久化；后续同步编排器必须在连接/调用前领取持久预算，
  原响应先安全保存，再记录成功页/下载索引。旧已成功范围必须在启动MCP前复用。
- 本层的响应大小/文件大小/单次超时是解析保护；真实批次的日期、资源、累计次数和墙钟预算
  仍须在在线清单中冻结，不能由直接使用此内部类绕过。

## 验证

合成回归：`tests/code/contract/test_m12_garmin_fit_adapter.py`。
覆盖固定离线启动、Token边界、精确工具名单、分页解码、空页/无FIT/错误区分、
原字节capture、真实CRC合成FIT、文件路径/权限/冲突、同任务SDK关闭、认证/进程/超时失败，
并将合成下载结果接入[新FIT存储](fit-weekly-storage.md)验证SHA闭合。
`runtime_resources.files(source, collection=True)` 明确包含上述 guard 和 overrides，供
同步闭合副本使用；不调用 Garmin 的模型资源身份默认不绑定这两项。必要资源缺失失败，
不从原仓库或全局 Skill 补缺。空实例副本经 Fake MCP、实际 FitClient、编排、全运动解析、
细读和搬迁零调用重放的入口为 `test_m12_resource_closure.py`。
尚未证明真实 Garmin 会话可用；内部实现的独立验收与真实在线授权是另外的门禁。
