# Codex 响应与结果协议

这是 M12 的内部纯解析组件，不启动模型、写文件或提供完整权限隔离。
它连接[进程监督](model-process.md)、[任务账本](model-job-ledger.md)及 Host 的业务校验。
业务输入、运动证据和课表安全门仍必须由周任务调用，不由解析器补造内容。

## 一份业务 Schema，确定性生成 wire

`wire_schema` 从 Host 的业务 Schema 投影模型响应格式，保留字段、required、
enum/const、对象分支及本地引用。仅移除本地值约束与元数据；原业务 Schema 不被修改。
移除的长度、数值、格式等限制仍在返回后严格校验，不因模型端未采用而失效。
对象必须闭合、全部字段必填，未知组合关键字和外部/悬空引用在模型前拒绝。
复用现有通用 Structured Outputs 检查器，不加载退役的日报/周报实现。

公开能力探针的 `audit_initial_request(response_schema=...)` 必须看到精确的
`text.format`（严格 JSON Schema、固定格式名和派生 wire）。未传响应合同仍沿用
原模式，此时不允许额外的 text 字段。不会先删除实际请求的 text 再宣称合同一致。
Schema 或 CLI 合同漂移需先重新完成公开能力核对，不能直接向私人数据任务放行。

## 成功不是“日志中能找到一段 JSON”

`parse_result` 的顺序为：

1. 进程已经确认停止、退出码 0、无进程错误、完整 Prompt 已送入管道。
2. 严格 UTF-8/JSONL 解码，不忽略坏行、重复键或非有限数值。
3. 一个 thread、一个 turn；所有 started 调用闭合，最后完成项为 agent_message。
4. 只解析最后一条完成消息，不向前找“还能用”的 JSON，不剥离 Markdown 围栏。
5. 同时校验派生 wire 和原业务 Schema，之后仍交 Host 业务/证据校验。

记录分隔符仅是 ASCII LF；JSON 正文中的 Unicode 分隔符属于正常文字。
完整最后一行可以没有额外 LF，但截断 JSON、不完整轮次、重复完成事件、终止后的
新增内容均不接受。reasoning、todo 和工具结果不是最终周报。

顶层 error/turn.failed 无法被后续正常事件或 JSON 覆盖。正文里的 `500`、
`failed` 不等于服务器错误，stderr 也不作为结果流。有限 JSON 解析失败与 CLI
明确报告失败使用不同固定错误码，不把 Python 递归错误当成模型声明失败。

唯一工具为已配置的 FIT 细读；发现类只读工具的拒绝可以保留为诊断，不意味着
获得了资源内容。工具失败不自动冒充整轮失败，最终证据是否足够由 Host 判断。
未知工具、未配置服务的成功结果、参数变动和未闭合调用拒绝。

## 启动诊断不是一概忽略

默认不接受启动错误。`startup_messages` 只供受信任 Host 传入公开能力探针已核对、
并绑定本次配置的精确启动诊断；必须发生在 turn.started 之前。不能从本次待判
日志或模型文字里动态拼出允许列表，也不按“包含 error/500”等词猜测类别。
完整 adapter 尚需把该允许列表纳入配置身份及能力证明，本模块不替它伪造证明。

返回对象只含解析值、事件 SHA 和诊断/工具数量；默认 repr 不展示答案。
原始流和失败证据由 adapter 同步存入私有实例，不提交 Git。
无法确认停止仍抛原 `ProcessInterrupted`，保持未知；已停止但结果不合法可以记明确
失败，重放继续由任务账本保证不再次启动模型。

## 验证与资料

[合成回归](../tests/code/contract/test_m12_codex_output.py)覆盖 Schema 投影/真实请求格式、
单轮状态机、截断、重复、Unicode 正文、工具生命周期、末条答案、错误分类及账本重放。
不读取私人数据或调用模型服务；公开 CLI 留存样本只在仓库外核对，不进入正常运行依赖。

实现依据与本机公开样本共同核对：
[Codex 非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)、
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
（2026-09-06）。这里使用项目已采用的窄 wire 子集，不声称覆盖官方所有可选特性。
