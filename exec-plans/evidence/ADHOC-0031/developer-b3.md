# Developer B3 报告：ADHOC-0031 B3 / ADHOC-0027+0028

## 修改摘要

实现 B3 的报告全文存储受控接口：

- 新增 `trainlab.reports`：
  - `save_activity_report` / `get_activity_report`：保存并读取 `activties_report` 三列活动总结；`start_time_utc` 只从 `activities.start_time_utc` 读取，重复保存采用“每活动当前报告替换”策略。
  - `save_weekly_report` / `get_weekly_report`：追加保存并读取 `weekly_report` 三列周总结；`run_time_utc` 使用同一个传入时间锚 T 格式化为 UTC，自增 `id` 由 SQLite 分配。
  - `ReportStorageError`：对活动不存在、空白/非法报告、容量超限等受控失败返回稳定 `ErrorCode`。
- 报告写入使用既有 `write_gate` 和 SQLite 事务；空白 summary、容量超限、缺活动、触发器失败等不会留下半份报告。
- 未新增 AI 工具、任意 SQL/file/path 能力、报告元数据列、调度任务或真实 AI/Garmin/网络调用。
- 更新 `trainlab.exports` 导出报告存储入口。
- 将包版本从 `0.1.1` 提升到 `0.1.2` 并同步 `uv.lock`，保证 `uv sync --locked --no-editable` 安装包含新增模块。
- 更新 `source/README.md`，避免继续把报告存储说成未实现；仍明确报告生成、同步、AI/Context 和完整 Web 业务在后续阶段。

## 文件清单

- `source/skills/_shared/scripts/trainlab/reports.py`：新增 B3 报告存储接口。
- `source/skills/_shared/scripts/trainlab/exports.py`：导出 B3 接口。
- `source/tests/reports/__init__.py`：新增测试包。
- `source/tests/reports/test_report_storage.py`：新增合成测试，覆盖活动/周报告正常、错误、边界、事务与工具不漂移。
- `source/README.md`：更新当前实现状态说明。
- `source/pyproject.toml`：版本 `0.1.2`。
- `source/uv.lock`：同步版本锁。

## 实际版本与未提交改动

- 分支：`work/adhoc-0031-local-web-system`
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`
- 工作区开始时已有未提交计划、证据移动和 `source/` 产品实现；本次未修改 `PLAN.md`、`exec-plans/**`、`MEMORY.md`、私人 `states`、Git 配置或 Git 索引。
- 当前暂存文件数：0。

## 检查表

| 命令 | 预期 | 实际结果 | 退出码 / 证据 |
| --- | --- | --- | --- |
| `cd source && uv lock` | 同步版本锁 | `trainlab-source v0.1.1 -> v0.1.2` | 0，终端输出 |
| `cd source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b3-developer-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable` | 仓库外隔离安装 | 通过，安装 `trainlab-source==0.1.2` | 0，`/tmp/trainlab-b3-developer-logs/uv-sync-final2.log` |
| `cd source && /tmp/trainlab-b3-developer-venv/bin/python -m pytest tests/reports/test_report_storage.py -q -p no:cacheprovider` | B3 新测试通过 | `8 passed` | 0，`/tmp/trainlab-b3-developer-logs/pytest-reports.log` |
| `cd source && /tmp/trainlab-b3-developer-venv/bin/python -m pytest tests -q -p no:cacheprovider` | 全量 Python 测试通过 | `171 passed, 2 warnings` | 0，`/tmp/trainlab-b3-developer-logs/pytest-all-final2.log` |
| `cd source && /tmp/trainlab-b3-developer-venv/bin/python -m ruff check --no-cache .` | 静态检查通过 | `All checks passed!` | 0，`/tmp/trainlab-b3-developer-logs/ruff-final3.log` |
| `cd source && /tmp/trainlab-b3-developer-venv/bin/python -m mypy -p trainlab -p tests --no-incremental` | 类型检查通过 | `Success: no issues found in 41 source files` | 0，`/tmp/trainlab-b3-developer-logs/mypy-final3.log` |
| `cd source && /tmp/trainlab-b3-developer-venv/bin/python -m compileall -q skills schemas tests` | 编译通过 | 无错误输出 | 0，`/tmp/trainlab-b3-developer-logs/compileall-final2.log` |
| `cd source && /tmp/trainlab-b3-developer-venv/bin/python -m trainlab.check_architecture` | 架构门通过 | `architecture and public Schema checks passed` | 0，`/tmp/trainlab-b3-developer-logs/architecture-final2.log` |
| `git diff --check && git diff --cached --name-only` | 无空白错误且无暂存 | 通过，暂存列表为空 | 0，`/tmp/trainlab-b3-developer-logs/git-diff-check-final2.log`、`staged-final2.log` |

调试中曾出现 Ruff 导入/排序、`__all__` 排序和 mypy 返回类型标注问题，已修正；上表为最终有效检查结果。

## 覆盖要点

- `activties_report`：三列、外键活动隔离、`start_time_utc` 来源于 `activities` 且合法缺失保留、中文/Markdown/SQL片段/多行全文往返、空白 summary 拒绝、重复保存替换当前报告、失败回滚、不破坏 FIT `summary_json` / `records` / `weekly_report` / `config`。
- `weekly_report`：三列、自增 ID、不强求无间隙、相同 `run_time_utc` 可多条、UTC 时间锚、空周固定文本可保存、全文往返、空白 summary 拒绝、失败回滚、不破坏 FIT 基础和活动报告。
- 工具边界：`TOOL_CONTRACTS` 仍只有 `get_running_records`，未新增 AI 报告工具。

## 未运行 / 未解决事项

- 未运行前端检查；本次未改前端代码。
- 未做真实 Garmin、AI Provider、网络或私人 `states` 数据调用。
- B3 只交付报告存储受控接口，不代表真实 AI 总结生成、每日 4 点触发、周 Context 接线或 Web/API 展示已完成。
- 仍需后续全新只读 Validator 独立复验。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "仅在允许的 source 范围内实现 B3 报告存储：新增 trainlab.reports、导出接口、合成测试、README 状态说明和包版本锁；未修改协调记录、私人 states 或 Git 索引。"
    },
    {
      "id": "criterion-2",
      "status": "satisfied",
      "evidence": "报告列出修改文件、测试新增、最终命令、通过结果、日志路径、残余风险和无暂存状态，可供独立验收复核。"
    }
  ],
  "changedFiles": [
    "source/skills/_shared/scripts/trainlab/reports.py",
    "source/skills/_shared/scripts/trainlab/exports.py",
    "source/tests/reports/__init__.py",
    "source/tests/reports/test_report_storage.py",
    "source/README.md",
    "source/pyproject.toml",
    "source/uv.lock"
  ],
  "testsAddedOrUpdated": [
    "source/tests/reports/__init__.py",
    "source/tests/reports/test_report_storage.py"
  ],
  "commandsRun": [
    {
      "command": "cd source && uv lock",
      "result": "passed",
      "summary": "同步 trainlab-source 版本到 0.1.2。"
    },
    {
      "command": "cd source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b3-developer-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable",
      "result": "passed",
      "summary": "按锁文件创建仓库外隔离环境并安装 trainlab-source==0.1.2。"
    },
    {
      "command": "cd source && /tmp/trainlab-b3-developer-venv/bin/python -m pytest tests/reports/test_report_storage.py -q -p no:cacheprovider",
      "result": "passed",
      "summary": "8 passed。"
    },
    {
      "command": "cd source && /tmp/trainlab-b3-developer-venv/bin/python -m pytest tests -q -p no:cacheprovider",
      "result": "passed",
      "summary": "171 passed, 2 warnings。"
    },
    {
      "command": "cd source && /tmp/trainlab-b3-developer-venv/bin/python -m ruff check --no-cache .",
      "result": "passed",
      "summary": "All checks passed。"
    },
    {
      "command": "cd source && /tmp/trainlab-b3-developer-venv/bin/python -m mypy -p trainlab -p tests --no-incremental",
      "result": "passed",
      "summary": "Success: no issues found in 41 source files。"
    },
    {
      "command": "cd source && /tmp/trainlab-b3-developer-venv/bin/python -m compileall -q skills schemas tests && /tmp/trainlab-b3-developer-venv/bin/python -m trainlab.check_architecture",
      "result": "passed",
      "summary": "compileall 无错误；架构门通过。"
    },
    {
      "command": "git diff --check && git diff --cached --name-only",
      "result": "passed",
      "summary": "无空白错误；暂存列表为空。"
    }
  ],
  "validationOutput": [
    "/tmp/trainlab-b3-developer-logs/uv-sync-final2.log",
    "/tmp/trainlab-b3-developer-logs/pytest-reports.log",
    "/tmp/trainlab-b3-developer-logs/pytest-all-final2.log",
    "/tmp/trainlab-b3-developer-logs/ruff-final3.log",
    "/tmp/trainlab-b3-developer-logs/mypy-final3.log",
    "/tmp/trainlab-b3-developer-logs/compileall-final2.log",
    "/tmp/trainlab-b3-developer-logs/architecture-final2.log",
    "/tmp/trainlab-b3-developer-logs/git-diff-check-final2.log",
    "/tmp/trainlab-b3-developer-logs/staged-final2.log"
  ],
  "residualRisks": [
    "未运行前端检查；本次未改前端。",
    "未做真实 Garmin/AI/网络/私人 states 调用。",
    "B3 只完成存储受控接口，真实生成、调度、Context 和 Web/API 接线仍属后续阶段。",
    "仍需全新只读 Validator 独立复验。"
  ],
  "noStagedFiles": true,
  "diffSummary": "新增报告存储模块与测试，导出受控接口，更新 README 状态说明，并将 source 包版本/锁文件同步到 0.1.2。",
  "reviewFindings": [
    "no blockers from developer self-check; independent Validator still required"
  ],
  "manualNotes": "工作区存在任务开始前已有的未提交计划/证据/source 实现；本次只改 source 允许范围内文件，未暂存。"
}
```
