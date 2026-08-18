# M9 Codex 日报调用器状态机与回归矩阵

本文件冻结 M9-r06 的应用层威胁模型，并记录 r07 的版本化 Structured Outputs 扩展。它记录
r05/r06 连续 Block 的原因，避免 Validator 在实现后逐轮扩张合同。日期、Prompt、Context、业务
Schema 和训练安全预期不在本批次修改范围；wire v1 作为失败证据冻结，wire v2 只补显式类型。

## 时间与信任边界

- 180 秒只约束 Codex 启动、Prompt 完整送入、模型运行和终止。
- 模型结束后的 owner-only 证据同步收尾不计入 180 秒。
- 文件系统调用应最终成功或返回错误；永久内核 I/O 阻塞属于 `host_io_unavailable`。
- Candidate 只允许受管单写者；协作进程遵守锁。持续恶意同 UID、root、内核和硬件故障属于
  host compromise，不要求应用同时保证绝对可用性和不可篡改。
- 无论主机故障如何，不完整 pending 都不得成为成功或下游输入。

## 固定状态机

```text
preflight
→ ai-attempt-3.pending/attempt-intent.json durable
→ Codex running (<=180s)
→ process stopped
→ result validated by wire + business schemas
→ terminal bundle durable inside pending
→ atomic rename pending to ai-attempt-3
→ downstream
```

模型时钟在 intent 和 pending 已持久化后、直接调用 `Popen` 前开始。成功只允许在 180 秒截止前
确认子进程已经退出；到达截止即先判失败，再同步发送终止信号并确认退出，确认与后续落盘不属于
180 秒模型预算。若无法确认退出，只保留 pending，不发布 terminal bundle。

## 单写者与持久化协议

- runner 以 `O_RDONLY|O_DIRECTORY|O_NOFOLLOW` 打开 `daily-20260817` run root，并在该目录
  descriptor 上取得非阻塞独占 `flock`；从前检开始一直持有到复用返回或 final 发布完成。
- 所有协作入口必须取得同一目录锁；锁竞争返回 `ai_attempt_lock_unavailable`，不创建 pending。
- 持锁后以排他 `mkdir(ai-attempt-3.pending, 0700)` 建立唯一 pending；已存在时禁止 Popen。
- `attempt-intent.json` 通过 pending 内 0600 临时文件写入、文件 `fsync`、原子改名、pending
  目录 `fsync`、run root 目录 `fsync` 后才允许启动 Codex。
- Codex 只写 pending。子进程确认结束后，主进程同步完成文件 `fsync`、receipt 原子写入和
  pending 目录 `fsync`；确认 final 不存在后，在锁内以不覆盖语义把整个 pending 目录改名为
  `ai-attempt-3`，随后 `fsync` run root。
- 原子目录改名是终态可见性的线性点；任何改名前失败保持 pending。改名成功但父目录 `fsync`
  报错时，本次不进入下游；后续只能在相同锁下只读重验 final 闭包，不能再次调用 Codex。
- 不允许任何线程、子进程或清理器在 runner 返回后写 final；同 UID 非协作恶意进程属于已排除
  host compromise。

合法文件状态只有：

| 状态 | `ai-attempt-3.pending/` | `ai-attempt-3/` | 含义 |
| --- | --- | --- | --- |
| 未开始 | 不存在 | 不存在 | 可进行 attempt 3 前检 |
| 未完成 | 存在 | 不存在 | `blocked`；禁止再次启动 Codex |
| 已终止 | 不存在 | 存在 | 只信任目录内通过闭包校验的 terminal receipt |
| 非法 | 存在 | 存在 | fail closed；Candidate 判废 |

最终目录必须包含 `attempt-intent.json`、`events.jsonl`、`stderr.log` 和
`attempt-receipt.json`；仅成功结果包含 `ai-result.json`。所有目录 `0700`、文件 `0600`、
单链接、普通文件且非空。final 精确白名单为：

- failed：`attempt-intent.json`、`events.jsonl`、`stderr.log`、`attempt-receipt.json`；
- succeeded：上述四项加 `ai-result.json`；
- 任何隐藏临时文件、匿名 Schema 路径、额外文件或子目录均使 final 无效。

receipt 不绑定自身；它必须绑定 intent、events、stderr 和可选 result 的大小与 SHA-256。
`codex_ai_attempt_v1` 增加 attempt 3 条件字段 `intent_bytes`、`intent_sha256`，attempt 2 旧回执
继续按原合同有效。`codex_ai_attempt_intent_v1` 精确包含：attempt=3、创建时间、180秒预算、
日志预算、完整命令合同、attempt 2 receipt SHA、Context SHA、Prompt SHA、wire Schema SHA、
业务 Schema SHA、provider_calls=0、external_actions=0；禁止额外字段。

## 故障矩阵

| ID | 前置/故障 | 预期结果 | Codex/Provider/外部动作 |
| --- | --- | --- | --- |
| T01 | Prompt、Context、Schema 或 attempt 2 证据不匹配 | 无 pending，前检失败 | `0/0/0` |
| T02 | intent 持久化后、Popen 前崩溃 | pending-only，`blocked` | `0/0/0` |
| T03 | Popen 返回错误 | failed terminal；无法持久化则 pending-only | `<=1/0/0` |
| T04 | stdin 提前关闭或 Prompt 未完整送入 | failed terminal | `1/0/0` |
| T05 | Codex 到达 180 秒 | 终止进程组，绝无 success | `1/0/0` |
| T06 | 无法确认 Codex 已停止 | pending-only，禁止发布 final | `1/0/0` |
| T07 | 非零退出或结构化 error 事件 | 分类后的 failed terminal | `1/0/0` |
| T08 | wire 或业务 Schema 失败 | `schema_non_retryable`，无 result | `1/0/0` |
| T09a | intent 前的有限 read/stat/open/lock 错误 | 无 pending，前检 blocked | `0/0/0` |
| T09b | intent 后的有限 write/fsync/rename/read 错误 | failed terminal 或 pending-only，绝无 success | `<=1/0/0` |
| T10 | terminal bundle 完整前任一点崩溃 | pending 被忽略，禁止下游 | `<=1/0/0` |
| T11 | 完整 bundle 原子发布 | pending 消失，final 一次性可见 | `1/0/0` |
| T12 | 返回后晚到子进程 | 只能触碰 pending；final 不变 | `1/0/0` |
| T13 | 预存 attempt 4、未知 attempt、pending 或无效/不匹配 final | fail closed，不启动 Codex | `0/0/0` |
| T14a | 有效且输入匹配的 succeeded final | 复用原成功，不新增输出 | `0/0/0` |
| T14b | 有效 failed final | 返回原失败，绝不重启 | `0/0/0` |
| T15 | 正式 state、Token 或冻结 SHA 漂移 | 模型前 blocked | `0/0/0` |
| T16 | 成功后的 SQLite/报告/receipt 重放 | ID、SHA、HTML 和行数不变 | `0/0/0` |

## 下游信任合同

- `complete_live_daily.py` 不再接受任意 `--ai-result-json`；改为接收固定 run root，并只从
  `ai-attempt-4/` 解析终态，同时要求闭合的 attempt 2 failed、attempt 3 failed 和公开 canary
  succeeded 证据。
- 下游先取得同一 run-root 目录锁，再验证 final 精确白名单、owner/mode/nlink、intent Schema、
  receipt Schema、四类 SHA/大小闭包、冻结输入 SHA 和 `status=succeeded`，最后才读取 result。
- pending、孤立 result、failed final、无效 final 或输入不匹配一律 blocked，不写 Candidate
  SQLite、不生成报告或 workflow receipt。
- 有效 succeeded final 的确定性重放复用既有 SQLite 输出、报告和 receipt；Codex、Garmin、
  Gmail、Workout、Sites 和 external action 都保持零。

## r07 Structured Outputs v2 扩展

```text
attempt 2 failed + attempt 3 failed
→ public schema-canary-v2 succeeded
→ ai-attempt-4.pending intent durable
→ Codex running with wire v2
→ wire v2 + original business schema validated
→ atomic ai-attempt-4 terminal
→ downstream
```

- `daily_ai_result_codex_v1` 及 attempt 2/3 原字节不可修改。wire v2 只为
  `schema_version/status/safety/provider_calls` 增加显式类型，payload 的业务版本值不变。
- 离线 allowlist 在创建 canary/attempt 4 pending 前递归验证显式类型、本地引用、严格对象、数组
  items、受支持关键字及官方规模预算；任何失败时模型调用为零。
- canary 仅使用仓库外 owner-only 目录和公开合成 Prompt，不接受 Candidate、goal、正式 state、
  Token 或私人 Prompt/Context 路径。失败 canary 永久终止本批次。
- attempt 4 intent 绑定 attempt 3 receipt、canary receipt、Prompt、Context、wire v2 和原业务
  Schema 的 SHA。attempt 4 pending/failed 均 blocked；成功重放不启动 Codex；attempt 5 禁止。
- 下游只接受 `2 failed → 3 failed → canary succeeded → 4 succeeded` 完整链。任何历史漂移、额外
  attempt 目录、canary/终态大小或 SHA 不闭合都在 SQLite/报告写入前停止。

### r06 真实失败与 r07 回归

| 失败 | 根因 | r07 回归与不变量 |
| --- | --- | --- |
| attempt 3 服务端 400 | wire v1 的四个 const/enum 节点缺显式类型；服务端只报告首个 | 四个逐项删除 type 的反例；wire v2 与业务 Schema 双验证 |
| 旧测试漏检 | 只检查禁用关键字和 object required/additionalProperties | 递归 allowlist、引用闭合、类型相容和规模上限 |
| 证据不能覆盖 | 原地改 wire v1 会破坏 attempt 3 SHA 链 | 新增 v2/intents/receipts，不覆盖 v1 或 attempt 2/3 |
| 未知服务端差异 | CLI 没有 validate-only | 先执行一次公开 canary；PASS 后才允许唯一私人 attempt 4 |
| 首轮 r07 Validator | 未引用/嵌套 `$defs`、重复引用深度与重复 `required` 可绕过检查 | 遍历全部定义；每个 `$ref` 位置重算展开深度；严格对象拒绝重复 required |
| 首轮 r07 Validator | canary 的通用根可指向 Candidate 或 `source/state` | 仅接受系统临时目录下专用前缀、无未声明内容且不在 Candidate/state/repo 内的 owner-only 根 |
| 最终 r07 Validator | 生成端隔离已生效，但消费端仍可接受复制进 Candidate 的同名 bundle | 生成端与 attempt4/finalizer 共用同一根验证；Candidate 内复制品一律拒绝 |
| 最终边界复验 | 共享门仍允许专用根嵌套在系统临时目录中的 `state/tokens/private-context` 下 | 专用根必须是系统临时目录的直接子目录；所有嵌套根统一拒绝 |

## r05 Block 回归映射

| Validator | 根因 | r06 保留的不变量/测试 |
| --- | --- | --- |
| 1 | 调用方 SHA 未绑定 attempt 2 | T01，冻结 SHA 从 attempt 2 receipt 派生 |
| 2 | stdin 背压绕过模型期限 | T04/T05，非阻塞完整送入 |
| 3 | 启动、终止和发布异常缺统一终态 | T03/T05/T09 |
| 4 | Prompt 未完整仍可成功、成功发布跨线 | T04/T11 |
| 5 | wait/attempt 历史/回执异常路径分叉 | T06/T13，单一状态机 |
| 6 | attempt 2 capture 未闭合、result 早于 fallback | T01/T11，result 只在终态 bundle 中出现 |
| 7 | 未双 Schema 后验、回执覆盖/终止等待竞态 | T05/T08/T11 |
| 8 | 空 capture 大小不闭合、失败回执挤入模型期限 | T07/T09；本地收尾不属于模型期限 |
| 9 | daemon writer 在返回后晚到覆盖 | T12；删除后台 writer、取消和 rollback |
| 10 | 无限阻塞 I/O 与绝对180秒/持久回执冲突 | 明确 host failure；180秒只约束 Codex |

### r06 首轮 Code Validator 合并修正

r06 首轮独立 Code Validator 在冻结矩阵内一次性发现六类缺陷；这些缺陷作为一个批次修正，
不得再拆成逐轮补丁：

| 缺陷 | 矩阵 | 修正与回归 |
| --- | --- | --- |
| 主进程退出后同进程组子进程仍持有日志 FD | T06/T12 | 始终终止并确认整个进程组；晚到子进程测试证明 final 字节不变 |
| 模型结束后的日志 fsync 被计入模型 elapsed | T05/T09b | 在进程组停止点冻结模型 elapsed；延迟本地 fsync 仍可同步成功 |
| 业务 Schema 未回绑 attempt 2 | T01/T15 | attempt 2 的 `schema_sha256` 必须等于当前业务 Schema；单字节漂移在 Popen 前阻断 |
| 正式 state/Token 漂移门缺失 | T15 | 模型前复核 Candidate 对正式 state 的来源，并在内存中两次比较 Token 指纹；模型后再次比较，摘要值不落盘 |
| final receipt 未强制 attempt 3 | T13 | intent 与 receipt 均必须为 attempt 3；attempt 2 伪装 final 被拒绝 |
| 有限 I/O 错误泄漏且阶段回归不足 | T02/T09/T10 | 公共入口统一返回稳定 blocked；覆盖前检、intent、Schema FD、capture、terminal write/rename/read，任何故障都无 success |

既有测试场景不得删除、skip 或 xfail。原来把本地落盘计入180秒的测试改为验证：模型期限仍为
180 秒、本地同步收尾不会被误分类为模型超时、没有返回后后台写入。测试预期的这一变化来自
2026-08-18 的用户明确批准，不是为了让实现通过而降低正确标准。

## 既有 44 个收集场景的保留映射

下表覆盖当前两个 r05 测试模块的 31 个测试定义；其中错误分类、attempt 2 文件和哈希变化测试
使用参数化，共收集 44 个场景。实现可重命名测试以匹配 r06 语义，但每一行场景必须保留并通过，
不得减少参数组合。

| 既有测试定义 | r06 映射与新断言 |
| --- | --- |
| `test_success_is_owner_only_atomic_and_schema_valid` | T11/T14a；pending 原子变 final、精确白名单和闭包 |
| `test_failure_categories_are_persisted`（全部参数） | T07；全部分类值原样保留 |
| `test_model_text_containing_500_is_not_server_error` | T07；模型正文不得触发5xx分类 |
| `test_timeout_is_transport_failure_and_cannot_be_retried` | T05/T14b；180秒模型超时且绝不重启 |
| `test_stdin_backpressure_is_inside_the_hard_timeout` | T04/T05；Prompt 送入属于模型期限 |
| `test_child_exit_before_full_prompt_is_a_failure` | T04 |
| `test_result_and_evidence_finalization_are_inside_the_hard_timeout` | T09b/T11；改为本地同步收尾不被误报模型超时 |
| `test_process_launch_is_inside_the_hard_timeout` | T03/T05；Popen 前开始模型时钟 |
| `test_kill_permission_error_still_produces_a_failure_receipt` | T06；不能确认停止则 pending-only |
| `test_group_and_process_kill_failures_do_not_escape_without_receipt` | T06；不要求伪造 terminal receipt |
| `test_receipt_write_crossing_deadline_cannot_persist_success` | T09b/T11；本地写入与模型期限解耦、绝无部分 final |
| `test_success_receipt_post_replace_failure_cannot_leave_success` | T09b/T11；目录发布前失败只留 pending |
| `test_termination_wait_cannot_extend_the_hard_deadline` | T05/T06；截止后同步确认，未确认只留 pending |
| `test_failure_receipt_delay_cannot_extend_or_mutate_after_deadline` | T09b；同步收尾，无后台晚到写 |
| `test_late_success_replace_is_rolled_back_after_caller_timeout` | T12；删除 rollback，晚到写永远不能触碰 final |
| `test_failed_attempt_2_is_preserved_and_does_not_block_attempt_3` | T01；attempt 2 原字节不变，允许唯一 attempt 3 |
| `test_attempt_3_requires_closed_attempt_2_capture_evidence`（全部参数） | T01；events/stderr大小和SHA闭包 |
| `test_success_result_is_not_published_before_fallback_receipt` | T10/T11；改为 result 只随完整 terminal bundle 发布 |
| `test_unapproved_attempt_directory_blocks_attempt_3` | T13；含 pending、attempt4和未知目录 |
| `test_attempt_3_rejects_prompt_or_context_not_bound_to_attempt_2`（全部参数） | T01 |
| `test_schema_failure_does_not_publish_ai_result` | T08 |
| `test_business_valid_but_wire_invalid_result_is_rejected` | T08 |
| `test_hash_mismatch_stops_before_process_and_attempt_creation` | T01/T09a |
| `test_missing_codex_stops_before_attempt_creation` | T03；无 pending、Popen=0 |
| `test_launch_failure_is_persisted_as_cli_failure` | T03；有 intent 后发布 failed terminal或保留pending |
| `test_frozen_bytes_are_used_even_if_source_paths_change_after_loading` | T01；只使用一次读取的冻结字节和只读 Schema FD |
| `test_log_budget_is_bounded_and_result_is_not_published` | T07；日志截断/预算与无result |
| `test_cli_has_no_date_mode_or_request_id` | 公开接口不变；仍拒绝日期、模式和request-id |
| `test_codex_wire_schema_uses_supported_strict_subset` | T08；wire Schema约束不变 |
| `test_codex_wire_payload_must_also_pass_original_business_schema` | T08；双Schema |
| `test_original_business_schema_is_not_weakened_by_wire_schema` | T08；业务正确预期不变 |

新增测试覆盖 T02、T09a/T09b 每个发布阶段、T10、T11 目录白名单、T12、T14a/T14b、T15、
T16 和下游 final 闭包；新增测试只增加覆盖，不能替代上表场景。
