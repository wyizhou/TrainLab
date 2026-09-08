# 已保存模型结果的本地恢复

本模块补上 M12 内部的一段接线：模型进程已经结束、原始输出已经保存，但周任务主回执
还没写完就退出时，可以直接核验并补记结果，不重新调用模型。
它不是完整 Codex 启动器、周报命令或 `codex exec resume`。

## 只认原任务的证据

恢复与正常调用共用 `model_job.prepare_request`，绑定原周身份、本周细读范围、完整输入、
业务 Schema 和 adapter profile；没有原 intent 时不创建 intent 或结果目录。
同一周/阶段改输入不能获得新的机会，也不能挪用另一周或另一阶段的结果。
新阶段显式传stage；旧无stage仅在原intent存在时只读恢复，不产生两阶段授权。

`codex_recovery.resume` 只读取实例内固定位置：
`model-results/<周和阶段标识摘要>/codex/process/`（旧无stage路径原样保留）。它不接受外部结果文件路径、命令或凭据。
目录及文件必须 owner-only、普通对象且非链接；继承
[进程原始证据](process-capture.md)的完整字节、SHA、Prompt 绑定及停止确认。

| 当前证据 | 处理 |
| --- | --- |
| 没有原 intent | unknown；不创建任务、不调用模型。 |
| 原始 capture 缺失、不完整、损坏、输入不符或停止未确认 | unknown；不补造终态，也不再次启动。 |
| 完整已停止的 capture，CLI、事件或结果 Schema 明确失败 | 保存同任务失败终态；原始流仍保留，不重试。 |
| 结果通过 CLI/wire/业务 Schema 与 Host 业务校验 | 原子发布原格式外层 capture，再以短事务记入 SQLite。 |
| 外层 capture 已存在 | 优先核对并复用；损坏时拒绝，不能用原始流覆盖它。 |

本地写入或 SQLite 失败后，可再尝试同一份证据的持久化和补账；这不是模型重试。
每次都会核对输入、目录权限和内容、补文件与目录 fsync；不覆盖历史终态。
并发恢复也不会新增模型启动机会或重复结果 document。

## 接口职责和未交付范围

- 通用 `model_job.recover` 的 `read_completed` 是受信 Host 内部只读结果接口，不是 AI 工具。
  它只接受已停止进程的原结果；不能启动程序或访问模型服务。Codex 的具体实现复用
  `process_capture.read_terminal` 和 `codex_output.parse_result`。
- 将文件保存为“已停止”，必须由既有进程监督器确认；当前模块不会用退出猜测替代它。
- Launcher 仍须提供冻结的 Prompt、已批准公开能力前检中的诊断白名单、同一 profile、
  固定进程预算及实际工具隔离。这里不完成这些启动前工作，也不推断认证或模型可用。
- 当前采用既有进程证据默认 stdout/stderr 大小限制；预算与启动配置应由同一 Launcher
  提供，不能用恢复参数临时放宽旧任务。
- 业务输入/结果校验器仍必填；本模块没有训练决策，也不是 Fake 结果转为真实 AI 的通道。
  [模型任务账本](model-job-ledger.md)的 model_attempts 为保守机会计数，不是本次恢复调用数。

实际 CLI 的 `--json` 输出为事件流，`--ephemeral` 不保存可恢复会话；TrainLab 保存自己的
有界证据实现本地恢复，参见[官方非交互说明](https://learn.chatgpt.com/docs/non-interactive-mode)。

回归：[test_m12_codex_recovery.py](../tests/code/contract/test_m12_codex_recovery.py)。
只使用合成 FIT、新 SQLite 和公开假输出；包含真实本地进程退出、多个恢复者、有限持久化
错误及实例搬迁，不连接真实 Codex、Garmin、Gmail 或其他业务 Provider。
