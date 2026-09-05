# M11 Live Canary 验收边界与有限故障矩阵

## 权威边界

- 本章程服从 `rules.md` 的 A-010、A-011、A-013 和当前 M11 exec plan。
- Candidate、owner-only 私有文件、当前 UID 和单写者进程属于可信运行环境。
- 应用负责正常进程崩溃、返回型 I/O 错误、Provider 错误、OAuth Token 正常刷新、发送结果丢失、
  幂等恢复和内容核验。
- 同 UID 恶意替换、root、内核、永久磁盘/硬件故障、绕过锁的直接 SQLite/文件篡改不属于应用
  验收范围，不得作为 Validator `FAIL` 的依据。

## 三个线性化点

1. **发送前冻结**：固定请求、收件人、认证回执、MIME、预算和 durable intent 均通过后才能进入
   Provider；此前失败必须保持 Provider 调用为零。
2. **发送已开始**：`send-started` 持久化后，无论响应丢失、崩溃或后续核验失败，都只能查询或
   获取 RAW，禁止再次调用 `messages.send`。
3. **远端成功**：唯一 Gmail ID、实际 RFC822 Message-ID、收件人、主题、text、HTML 和全部 CID
   PNG 闭合后才可写入成功终态；否则 external action 只能是 `failed_safe` 或 `unknown`。

Authorization header 和 MIME 在第二个线性化点前已绑定。之后私有路径的非合作篡改属于排除项，
不能追溯要求已经开始的 Provider 调用归零。

## 双层状态合同

- external action 使用 `prepared/in_progress/failed_safe/unknown/succeeded`；`failed_safe` 不是
  Skill run 状态。
- Skill run 只能使用 `pending/running/succeeded/failed/blocked/interrupted/cancelled`。
- 发送前的环境、认证或 Provider 只读失败：external action=`failed_safe`，Skill run=`blocked`。
- `send-started` 后结果不确定或远端闭合失败：external action=`unknown`，Skill run=`blocked`。
- 远端完整闭合：external action 与 Skill run 均为 `succeeded`。
- 真实进程崩溃留下的旧 Skill run 为 `interrupted`，恢复必须建立新的 Skill run；实现或不变量错误
  使用 Skill run=`failed`，external action 仍按 `send-started` 前后分别为 `failed_safe/unknown`。
- 稳定错误族至少包含 `gmail_live_preflight_failed`、`gmail_live_read_retry_exhausted`、
  `gmail_live_send_result_unknown`、`gmail_live_remote_mismatch`、`gmail_live_internal_invariant` 和
  `gmail_live_interrupted`；实现可使用更细子码，但不得改变上述映射。

## 有限故障矩阵

| ID | 场景 | 必须结果 |
| --- | --- | --- |
| F01 | request、recipient、auth receipt、Token 路径/权限/JSON/Scope 在发送前无效 | `failed_safe`，Provider 0 |
| F02 | 正式 state 合作式锁不可取得或发送前指纹与构建基线不符 | `failed_safe`，Provider 0 |
| F03 | durable intent 或本地 MIME 在 `send-started` 前写入失败 | `failed_safe`，Provider 0，可安全重试 |
| F04 | `send-started` 后进程崩溃或发送响应丢失 | `unknown`，只读按 Message-ID 对账，send 不增加 |
| F05 | Provider 已返回 Gmail ID 后崩溃 | 优先按该 Gmail ID 获取 RAW，send 不增加 |
| F06 | pre-send/recovery lookup、RAW get、final confirmation 遇连接错误、429 或 5xx | 每阶段首次加最多 4 次重试，等待 1/2/4/8 秒；阶段上限 5 次，预算跨进程持久化 |
| F07 | 只读遇 401/403、其他 4xx、请求构造错误、畸形 JSON/body、重复命中或内容不一致 | 不重试；发送前为 `failed_safe`，发送后为 `unknown`；`messages.send` 从不自动重试 |
| F08 | OAuth Token 正常刷新后进程崩溃 | 使用同目录 `0600` 临时文件、文件 fsync、原子改名和父目录 fsync；`send-started` 前可用当前合法 Token 安全重启，之后为 `unknown` 且仅只读恢复；Token SHA 只作审计 |
| F09 | 日报 external action 未成功、RAW/CID 未闭合，或网页/手机任一未确认 | 周报 `provider_calls=0` 且 `send_calls=0`；四项全部成立才可放行 |
| F10 | 两封均成功后的确定性重放 | Provider、send、SQLite 业务行和产物均无增量 |
| F11 | Candidate 权限、Git ignore 或私人产物边界不符 | 发送前阻断，不泄漏地址、Token、EML 或图片 |
| F12 | 正常成功路径 | 每封 send=1、批次 send=2；每个 PNG 的 CID、角色、SHA-256、尺寸、来源 manifest、HTML 引用和 RAW 附件一一闭合 |

补充发送结果分类：`messages.send` 每封最多一次。明确完整的 HTTP 拒绝且没有 Gmail ID 时为
`failed_safe`；连接丢失、超时、响应不完整或无法确定是否受理时为 `unknown`。两者都立即停止当前
批次。发送后查询 0 命中可以在 lookup 阶段预算内继续，耗尽仍为 0 时保持 `unknown`。

## 历史 Block 归类

| Attempt | 结论 |
| --- | --- |
| 7 | capture 中间目录非 `0700`，属于 F11 的有效隐私缺陷，历史原样保留 |
| 8 | 正式 state 合作式预检有价值；同 UID Token 替换不属于 A-010 阻断范围 |
| 9 | 发送前加载替代 Token 的防御性绑定可保留；邮件冻结后 state 任意漂移不得扩张为新合同 |
| 10 | 任意 Python 语句间替换 Token 并要求 HTTP 0 调用属于排除威胁；刷新崩溃恢复应按 F08 验收 |
| 11 | 未启动；因 high/high 连续失败和威胁模型冲突而取消 |

## Validator 规则

- `FAIL` 必须引用 F01–F12 或 A-010/A-011/A-013 的具体条款，并证明受支持入口可达。
- 同 UID 篡改、root/内核/硬件、任意 monkeypatch 语句间替换或直接账本伪造只能记为非阻断风险。
- 新威胁不能在一次 Code Validator 中直接扩大为完成门；必须停止并由用户决定是否修改本章程。
- 首次 Code Validator 允许一个合并修正批次；全新最终 Validator 仍为 `FAIL/INCONCLUSIVE` 时停止，
  不得自动开启第三轮。
- 不删除适用测试，不使用 `skip`、`xfail` 或降低正确业务断言制造绿灯。历史越界用例改为验证已冻结
  header/MIME 不受路径变化影响、后续安全停止且单封 send 始终不超过一次。
