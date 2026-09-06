# FIT 同步编排

这是 M12 的内部 Python 接口，尚未启用真实采集命令、邮件或守护进程。接口连接
[同步日历](sync-calendar.md)、[Garmin 适配器](garmin-fit-adapter.md)和
[独立存储](fit-weekly-storage.md)，不依赖旧数据库或归档。

## 一次任务的含义

`fit_weekly.fit_sync.synchronize` 接收实例根、`SyncSpec`、显式 Token 目录。
`SyncSpec` 固定活动日期、查询时点、分页大小、查询/下载/会话启动预算、单次超时和地区。
同一任务键不能换日期、地区或增加预算。实例中的业务路径均相对实例根；Token 不复制。
路径只在启动本机 MCP 和下载暂存时解析为当前绝对路径，不成为业务身份。

| 环节 | 成功依据 | 中断处理 |
| --- | --- | --- |
| 发现活动 | 完整分页；历史日 complete、当日 provisional | 保存成功页；下一次显式调用只处理余下页 |
| 领取调用 | SQLite 不可变 intent 已提交 | 已领取预算不因重启清零 |
| 取得结果 | 私有描述文件和原始 MCP 文本均落盘并 fsync | 可用闭合 capture 恢复，不能只根据文本猜测成功 |
| 收集 FIT | 已有唯一有效 FIT 复用；新 FIT 校验 CRC、SHA、身份并入库 | 保留每次独立下载目录；不覆盖旧暂存 |
| 结束会话 | 同一 asyncio Task 关闭 MCP、Token 前后不变 | 审计失败永久标记 blocked，普通续跑不再调用 Provider |
| 整体完成 | 成员、FIT/明确无原文件、账本、产物清单闭合 | 最终回执失败可本地重放，成功重放不联网、不新增结果 |

活动不支持原始 FIT 时保存 `no_fit/provider_no_original`，仍计入活动数，不冒充“当天无运动”。
同活动出现多个已登记 FIT 修订时停止，不猜测应使用哪份。
`sync_days.complete` 只代表查完整，下载未完的任务仍由 `unfinished_jobs` 返回，调度方不能只查日期表。

## 保存与恢复

新实例 `sync/<任务键摘要>/<调用序号>/` 只允许本次声明的文件：

- `result.json`：绑定 intent SHA、capture SHA、适配器成功/错误判定和规范化结果；先持久化，防止丢失 MCP `isError` 语义。
- `response.mcp`：非空原始 MCP 文本，明确不是 Garmin HTTP raw；两份文件闭合后才记录 SQLite outcome。
- 下载调用的 `download/<活动编号>.fit`：每次空目录，原字节保留。

这些都是私有证据：目录 `0700`、文件 `0600`，拒绝链接、空文件、未声明文件及残留未完成临时文件。
原始 MCP 文本可能包含活动名称或本机下载路径；不提供给 AI、不进入 Git。AI 只消费后续解析器的去标识投影。
只有原始文本、缺少判定描述，或描述声明的 capture 丢失时停止，不把失败响应升级为成功。
原始文件和描述已保存但 SQLite 尚未完成时，恢复再次确认持久化屏障后采用原结果。
同一页只允许一个成功结果：已保存页不再次绑定；尚未保存页只采用最近一次匹配领取。
更早没有结果的领取保留为 inventory 回执的 `unresolved_calls`，不伪装成额外成功查询或清零预算。

`provider_calls` 是已持久化领取的保守上界（initialize/inventory/download/total），不是凭空证明每次网络请求已抵达 Garmin。
超时、失败及未确认结果仍占预算。每次函数调用遇到错误立即退出，没有内部自动重试；显式续跑才可使用剩余只读额度。
模型和外部动作不属于本接口，`external_actions=0`。本模块不生成同步邮件，也不完成历史覆盖或部署验收。

## 验证入口

`tests/code/contract/test_m12_fit_sync.py` 使用实际 `FitClient`＋合成 MCP 会话，覆盖分页与下载串联、复用/无 FIT、
预算、真实子进程退出、capture/SQLite 落盘边界、Token 审计、任务恢复、产物漂移和搬迁后零调用重放。
保留 `test_m12_sync_calendar.py` 的同步调用入口，异步编排与其复用同一个分页生成器，不复制状态机、不创建后台线程。
