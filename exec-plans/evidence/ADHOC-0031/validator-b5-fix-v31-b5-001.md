# Validator 复验报告：ADHOC-0031 B5 fix V31-B5-001

结论：**通过**。固定快照核对通过；V31-B5-001 原失败场景已修复；B5 相关正常、错误和边界回归在合成隔离环境中通过。

## 受审版本与冻结核对

- 分支：`work/adhoc-0031-local-web-system`。
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`。
- 固定快照：`exec-plans/evidence/ADHOC-0031/b5-fix-v31-b5-001-review-snapshot.json`。
- 快照结果：71 个产品文件逐项 `path/size/mode/sha256` 均一致；按快照 items 的排序 JSON 聚合 SHA 为 `9e9e5925d96129ebd83bca2617c52e1ad93e64d8ad5129558e85b5e6507772ac`，与任务要求一致。
- 工作区存在已说明的协调记录和未提交 `source/` 受审产品文件；未暂存文件。验证只按固定快照检查产品文件。

## 场景表

| 场景 | 类型 | 步骤与输入 | 预期 | 实际 | 结果/证据 |
| --- | --- | --- | --- | --- | --- |
| 隔离安装 | 环境 | `UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b5-fix-validator-v31-venv uv sync --locked --extra dev --no-editable` | 按锁文件安装固定源码 | 安装 `trainlab-source==0.1.7` 成功 | 通过；`/tmp/trainlab-b5-fix-validator-v31-logs/uv-sync.log` |
| 全量 pytest | 回归 | `python -m pytest tests -q -p no:cacheprovider` | 全部通过 | `191 passed, 2 warnings` | 通过；`pytest-all.log` |
| Ruff / mypy / compileall / 架构门 | 静态 | ruff、mypy、compileall、`trainlab.check_architecture` | 均退出 0 | 均退出 0；mypy 为 50 个源文件无问题 | 通过；对应日志 |
| V31-B5-001 活动报告容量 | 错误边界 | `ReportService` + `ToolDispatcher.capacity=CapacityPolicy(storage_bytes_limit=5, model_payload_bytes_limit=None)`，Fake AI 返回 `0123456789 long` | 抛出 `RESOURCE_LIMIT` 或等价错误；不插入、不覆盖 `activties_report` | 抛出 `ReportStorageError`，code=`RESOURCE_LIMIT`；插入数仍 0；已有旧报告未覆盖；成功历史未追加 | 通过；`pytest-independent.log` |
| 周报 AI summary 超限 | 错误边界 | 已有活动总结，周报 Fake AI 返回超限文本，storage limit=5 | 明确失败且不插入 `weekly_report` | `RESOURCE_LIMIT`，`weekly_report` 仍 0 | 通过；`pytest-independent.log` |
| 空周固定 summary 容量 | 边界 | 空周生成固定 summary，storage limit=5 | 同样受容量限制，不插入 | `RESOURCE_LIMIT`，`weekly_report` 仍 0 | 通过；`pytest-independent.log` |
| 正常活动/周报保存 | 正常 | storage limit=100000，Fake AI 分别返回正常活动和周报 summary | 两类报告保存，全文一致 | `activties_report` 与 `weekly_report` 均保存预期全文 | 通过；`pytest-independent.log` |
| AI tool loop 正常/错误 | 正常/错误 | 无真实网络；Fake AI 调用 `read_reference`、`get_running_records`，并覆盖截断、坏结构、未知工具 | 正常完成；错误映射明确 code | 正常得到最终文本；错误分别为 `RESOURCE_LIMIT`、`DATA_INVALID`、`TOOL_NOT_ALLOWED` | 通过；`pytest-independent.log` |
| Dispatcher / reference | 权限边界 | 检查 `TOOL_CONTRACTS`，只派发 `get_running_records`/`read_reference`；传 path、任意 reference id、未授权 activity、shell | 只允许白名单工具和 ID 映射，不读任意路径/URL | 白名单正确；非法 path/id/activity/tool 均拒绝 | 通过；`pytest-independent.log` |
| Context 三模式 | 正常/边界 | activity、daily、weekly 三模式；缺活动报告；空周 | activity 包含事实；daily 无写入；weekly 缺报为 `POLICY_UNCONFIGURED`；空周固定 summary | 均符合预期 | 通过；`pytest-independent.log` |
| 失败/截断/越权不写报告 | 错误 | AI 截断失败后检查报告表计数 | 不新增、不覆盖报告 | 计数保持不变 | 通过；`pytest-independent.log` |
| api_key 不泄露 | 安全 | AIConfig 使用 `secret`，检查 AI 请求和返回消息 JSON | 不包含 api_key | 未发现 `secret` | 通过；`pytest-independent.log` |
| 前端 | 范围说明 | 本次修复快照未修改 `source/frontend/**`，任务核心为 B5 AI/Context/ReportService | 可说明未运行 | 未运行前端 lint/type/test/build | 未验证；见未验证事项 |

## 问题表

| 编号 | 结论 | 对应要求 | 复验结果 | 证据 |
| --- | --- | --- | --- | --- |
| V31-B5-001 | 已通过复验 | U31-03/B5：资源耗尽必须明确失败，不能保存失败/半份报告；活动/周/空周保存均须执行 storage 容量限制 | 原失败场景和周报/空周关联容量场景均抛出 `RESOURCE_LIMIT`，未插入或覆盖报告；正常活动和周报仍可保存 | `/tmp/trainlab-b5-fix-validator-v31-logs/pytest-independent.log` |

未发现新的阻塞问题。

## 命令与证据路径

- `/tmp/trainlab-b5-fix-validator-v31-logs/freeze.log`：分支、HEAD、工作区、71 文件快照和聚合 SHA 核对。
- `/tmp/trainlab-b5-fix-validator-v31-logs/uv-sync.log`：隔离安装。
- `/tmp/trainlab-b5-fix-validator-v31-logs/pytest-all.log`：`191 passed, 2 warnings`。
- `/tmp/trainlab-b5-fix-validator-v31-logs/ruff.log`：Ruff 通过。
- `/tmp/trainlab-b5-fix-validator-v31-logs/mypy.log`：mypy 通过。
- `/tmp/trainlab-b5-fix-validator-v31-logs/compileall.log`：compileall 通过。
- `/tmp/trainlab-b5-fix-validator-v31-logs/architecture.log`：架构门通过。
- `/tmp/trainlab-b5-fix-validator-v31-logs/diff-check.log`：`git diff --check` 通过。
- `/tmp/trainlab-b5-fix-validator-v31-logs/staged.log`：暂存列表为空。
- `/tmp/trainlab-b5-fix-validator-v31-logs/test_v31_b5_revalidation.py`：本次隔离独立复验用例。
- `/tmp/trainlab-b5-fix-validator-v31-logs/pytest-independent.log`：独立复验 `3 passed`。

## 未验证事项

- 未读取真实 `states/ai.json`、密钥、私人状态或真实活动数据。
- 未调用真实 AI、Garmin、网络、登录/MFA。
- 未推进 B6/B7、未验证 Web/API 完整端到端。
- 前端本次未运行；理由是 V31-B5-001 修复仅涉及后端 AI/Context/ReportService 与 Python 锁文件，`source/frontend/**` 快照未变化。
- D31-03A/B、D31-02A 仍属后续未配置策略范围，本次不验证自动批次、补跑、周触发和旧 records 周配额。
