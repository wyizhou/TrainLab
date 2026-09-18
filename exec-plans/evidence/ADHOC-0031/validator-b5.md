# Validator B5 报告：ADHOC-0031 / 0031-T4+T5

结论：**失败**。固定版本与快照核对通过，常规全量检查和大部分独立场景通过；但发现 1 个阻塞问题：报告服务没有把已配置的存储容量耗尽作为失败处理，AI 最终返回超限 summary 时仍保存完整活动报告，违反“资源耗尽明确失败，不保存半份/失败报告”的 B5 边界。

## 版本与快照核对

- 分支：`work/adhoc-0031-local-web-system`。
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`。
- 受审快照：`exec-plans/evidence/ADHOC-0031/b5-developer-review-snapshot.json`。
- 核对结果：71 文件 path/size/mode/sha256 全部一致；聚合 SHA 为 `976298d534aab7d0f2f62c51d0362a1d96698dc02e0e3a881fd73804cb710000`，与快照一致。
- 当前额外未提交的计划/证据协调记录按任务说明不纳入产品受审内容；无暂存文件。

## 检查与场景表

| 场景 | 方法 | 结果 |
| --- | --- | --- |
| 隔离安装 | `UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b5-validator-venv uv sync --locked --extra dev --no-editable` | 通过 |
| 全量 pytest | `189 passed, 2 warnings` | 通过 |
| Ruff | `All checks passed!` | 通过 |
| mypy | `Success: no issues found in 50 source files` | 通过 |
| compileall | `python -m compileall -q skills schemas tests` | 通过 |
| 架构门 | `architecture and public Schema checks passed` | 通过 |
| diff 空白 | `git diff --check` | 通过 |
| AI loop 正常 | 独立 pytest 覆盖无工具、多工具同轮、多 tool_call_id、最终文本、工具声明集合 | 通过 |
| AI loop 错误 | 独立 pytest 覆盖截断、坏结构、越权参数、越权 activity；HTTP/坏 JSON 用 monkeypatch 探针覆盖 | 通过 |
| Dispatcher/reference | 独立 pytest 覆盖仅 `get_running_records`/`read_reference`、映射 ID、拒绝 path/url/任意 ID、授权失败 | 通过 |
| Context 三模式 | 独立 pytest 覆盖 activity facts、tools README、references README、内存 history、当前对话、daily 无写入、weekly 同一 T 与缺报策略 | 通过 |
| Report service 常规 | 独立 pytest 覆盖 AI 成功后保存、失败/截断/越权不写、空周固定文本写入、summary 全文保真、api_key 不进入消息 | 通过 |
| Report service 资源耗尽 | 独立探针配置 `CapacityPolicy(storage_bytes_limit=5)`，AI 返回超限 summary | **失败：仍保存报告** |
| 前端 | 本次 B5 未修改 `source/frontend/**`，未运行前端检查 | 未验证 |

## 问题表

| 编号 | 严重性 | 对应要求 | 复现步骤 | 预期 | 实际 | 证据 |
| --- | --- | --- | --- | --- | --- | --- |
| V31-B5-001 | blocker | U31-03/B5：错误/截断/越权/资源耗尽必须明确失败，不将半份结果保存为完整报告；Report service 只有 AI 最终成功且满足边界后才保存 | 构造合成活动 DB；创建 `ReportService`，其 `ToolDispatcher.capacity=CapacityPolicy(storage_bytes_limit=5, model_payload_bytes_limit=None)`；Fake AI 返回 `0123456789 long`；调用 `generate_activity_report` | 抛出 `RESOURCE_LIMIT` 或等价明确错误，且 `activties_report` 不新增/不覆盖 | 调用成功返回，`activties_report.summary` 被保存为 `0123456789 long` | `/tmp/trainlab-b5-validator-logs/probe-resource-capacity.log` 输出 `UNEXPECTED_SAVE summary='0123456789 long' saved='0123456789 long'` |

定位说明：`source/skills/_shared/scripts/trainlab/reports.py` 的 `save_activity_report/save_weekly_report` 已有 `capacity` 参数和 `RESOURCE_LIMIT` 保护，但 `source/skills/_shared/scripts/trainlab/report_service.py` 调用保存函数时没有传入任何容量策略；因此报告服务层无法执行已配置的 storage 限制。

## 未验证项

- 未做真实 AI Provider、Garmin、网络、登录/MFA、私人 `states/ai.json` 或真实活动数据调用。
- 未推进 B6 Web/API 与完整端到端。
- 前端未改，仅说明未运行前端 lint/type/test/build。
- D31-03A/B、D31-02A 仍未配置；本次未验证自动批次、补跑、周触发和旧 records 周配额策略。

## 证据路径

- `/tmp/trainlab-b5-validator-logs/uv-sync.log`
- `/tmp/trainlab-b5-validator-logs/pytest-all.log`
- `/tmp/trainlab-b5-validator-logs/ruff.log`
- `/tmp/trainlab-b5-validator-logs/mypy.log`
- `/tmp/trainlab-b5-validator-logs/compileall.log`
- `/tmp/trainlab-b5-validator-logs/architecture.log`
- `/tmp/trainlab-b5-validator-logs/diff-check.log`
- `/tmp/trainlab-b5-validator-logs/pytest-independent.log`
- `/tmp/trainlab-b5-validator-logs/probe-http-client.log`
- `/tmp/trainlab-b5-validator-logs/probe-resource-capacity.log`

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "已返回结论、阻塞问题 V31-B5-001、通过/失败场景表、命令结果、证据路径和残余风险。"
    }
  ],
  "changedFiles": [
    "/Users/lucas/.pi/agent/sessions/--Volumes-DiskOther-Code-TrainLab--/subagent-artifacts/outputs/5951e2c6-2705-4653-9c2e-e3ef2fe43402/adhoc0031/validator-b5.md"
  ],
  "testsAddedOrUpdated": [],
  "commandsRun": [
    {
      "command": "git rev-parse --abbrev-ref HEAD && git rev-parse HEAD && git status --short",
      "result": "passed",
      "summary": "确认分支与 HEAD；工作区有任务说明中已知的未提交产品/计划/证据内容。"
    },
    {
      "command": "python3 snapshot verification script for exec-plans/evidence/ADHOC-0031/b5-developer-review-snapshot.json",
      "result": "passed",
      "summary": "71 文件逐项 path/size/mode/sha256 一致，聚合 SHA 一致。"
    },
    {
      "command": "cd source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b5-validator-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable",
      "result": "passed",
      "summary": "隔离安装成功。"
    },
    {
      "command": "cd source && /tmp/trainlab-b5-validator-venv/bin/python -m pytest tests -q -p no:cacheprovider",
      "result": "passed",
      "summary": "189 passed, 2 warnings。"
    },
    {
      "command": "cd source && /tmp/trainlab-b5-validator-venv/bin/python -m ruff check --no-cache .",
      "result": "passed",
      "summary": "All checks passed。"
    },
    {
      "command": "cd source && /tmp/trainlab-b5-validator-venv/bin/python -m mypy -p trainlab -p tests --no-incremental",
      "result": "passed",
      "summary": "Success: no issues found in 50 source files。"
    },
    {
      "command": "cd source && /tmp/trainlab-b5-validator-venv/bin/python -m compileall -q skills schemas tests",
      "result": "passed",
      "summary": "compileall 无错误；运行后已清理生成的 __pycache__。"
    },
    {
      "command": "cd source && /tmp/trainlab-b5-validator-venv/bin/python -m trainlab.check_architecture",
      "result": "passed",
      "summary": "architecture and public Schema checks passed。"
    },
    {
      "command": "git diff --check",
      "result": "passed",
      "summary": "无空白错误。"
    },
    {
      "command": "cd source && /tmp/trainlab-b5-validator-venv/bin/python -m pytest /tmp/trainlab-b5-validator-logs/test_b5_independent.py -q -p no:cacheprovider",
      "result": "passed",
      "summary": "独立 B5 场景 7 passed。"
    },
    {
      "command": "cd source && PYTHONPATH=. /tmp/trainlab-b5-validator-venv/bin/python <HTTP client monkeypatch probe>",
      "result": "passed",
      "summary": "坏 JSON 与 HTTPError 均转换为 EXTERNAL_SERVICE_FAILED。"
    },
    {
      "command": "cd source && PYTHONPATH=. /tmp/trainlab-b5-validator-venv/bin/python /tmp/trainlab-b5-validator-logs/probe_resource_capacity.py",
      "result": "failed",
      "summary": "配置 storage_bytes_limit=5 后，ReportService 仍保存超限 AI summary，复现 V31-B5-001。"
    },
    {
      "command": "git diff --cached --name-only | wc -l",
      "result": "passed",
      "summary": "暂存文件数为 0。"
    }
  ],
  "validationOutput": [
    "结论：B5 独立验证失败。",
    "快照、全量测试、静态检查、架构门和多数合成场景通过。",
    "阻塞：V31-B5-001 ReportService 未执行 storage capacity，资源耗尽场景仍保存报告。"
  ],
  "residualRisks": [
    "未做真实 AI/Garmin/网络/私人 states 调用。",
    "未验证 B6 Web/API 和完整端到端。",
    "D31-03A/B、D31-02A 未配置范围仍未验证。"
  ],
  "noStagedFiles": true,
  "diffSummary": "未修改受审产品内容；仅写入本 Validator 报告和 /tmp 隔离证据。",
  "reviewFindings": [
    "blocker: source/skills/_shared/scripts/trainlab/report_service.py - V31-B5-001：ReportService 保存活动/周报告时未传递或执行 CapacityPolicy.storage_bytes_limit，资源耗尽场景仍保存 AI summary。"
  ],
  "manualNotes": "验证过程中未读取真实 states/ai.json、密钥或私人数据，未做真实外部请求。"
}
```
