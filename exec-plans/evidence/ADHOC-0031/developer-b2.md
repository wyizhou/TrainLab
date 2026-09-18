# Developer B2 报告：ADHOC-0031 B2 / ADHOC-0025+0026

## 修改摘要

实现了 B2 的唯一只读采样查询 `get_running_records(activity_id)`，并让工具索引与机器声明保持一致：

- 新增 `trainlab.running_records`，提供：
  - `get_running_records(activity_id, *, db_path, authorization, capacity=None)`；
  - `handle_get_running_records(request, *, db_path, authorization, capacity=None)` 用于结构化 tool payload 校验。
- 查询只读取宿主传入的受控 SQLite DB，使用既有 `read_view()` 只读事务，不创建数据库、不读取 FIT 原件、不读写报告表。
- 成功只允许宿主授权且真实 `sport=running` 的活动，返回该活动全部 records，保持原 `record_index` 顺序、重复时间、缺失和 `metrics_json` 对象。
- 错误场景返回固定 `GetRunningRecordsResult` 失败外壳，覆盖额外参数、越权、非跑步、未知运动、不存在活动、无库、坏 JSON、Schema 不支持、容量超限。
- 更新 `source/tools/README.md`，明确当前机器声明 `TOOL_CONTRACTS` 只有 `get_running_records`；`read_reference` 属后续 B5，当前未注册、不可用。
- 更新内部包版本到 `0.1.1` 并同步 `uv.lock`，确保 `uv sync --locked --no-editable` 会重新构建并包含新增模块。

## 文件清单

- `source/skills/_shared/scripts/trainlab/running_records.py`：新增只读 records 查询实现。
- `source/skills/_shared/scripts/trainlab/contracts/interfaces.py`：机器工具声明收敛为当前已交付的 `get_running_records`。
- `source/skills/_shared/scripts/trainlab/exports.py`：导出 B2 查询入口。
- `source/tools/README.md`：更新 B2 工具索引与未注册边界。
- `source/tests/tools/__init__.py`：新增测试包。
- `source/tests/tools/test_running_records.py`：新增合成测试和漂移检查。
- `source/pyproject.toml`、`source/uv.lock`：版本从 `0.1.0` 到 `0.1.1`，确保 locked no-editable 安装包含新增模块。

## 实际版本与未提交改动

- 分支：`work/adhoc-0031-local-web-system`
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`
- 工作区开始时已有未提交计划、证据和 `source/` 产品实现；本次未修改 `PLAN.md`、`exec-plans/**`、`MEMORY.md`、Git 索引或私人 `states`。
- 当前无暂存文件。

## 检查表

| 命令 | 预期 | 实际结果 | 退出码 / 证据 |
| --- | --- | --- | --- |
| `cd source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b2-dev-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable` | 按锁文件隔离安装 | 通过；安装 `trainlab-source==0.1.1`，新增模块可导入 | 0，终端输出 |
| `cd source && /tmp/trainlab-b2-dev-venv/bin/python -m pytest tests/tools/test_running_records.py -q -p no:cacheprovider` | B2 新测试通过 | `6 passed` | 0，终端输出 |
| `cd source && /tmp/trainlab-b2-dev-venv/bin/python -m pytest tests -q -p no:cacheprovider` | 全量 Python 测试通过 | `163 passed, 2 warnings` | 0，终端输出 |
| `cd source && /tmp/trainlab-b2-dev-venv/bin/python -m ruff check --no-cache .` | 静态检查通过 | `All checks passed!` | 0，终端输出 |
| `cd source && /tmp/trainlab-b2-dev-venv/bin/python -m mypy -p trainlab -p tests --no-incremental` | 类型检查通过 | `Success: no issues found in 38 source files` | 0，终端输出 |
| `cd source && /tmp/trainlab-b2-dev-venv/bin/python -m compileall -q skills schemas tests` | 编译通过 | 无错误输出 | 0，终端输出 |
| `cd source && /tmp/trainlab-b2-dev-venv/bin/python -m trainlab.check_architecture` | 架构门通过 | `architecture and public Schema checks passed` | 0，终端输出 |
| `git diff --check && git diff --cached --name-only` | 无空白错误且无暂存 | 通过，暂存列表为空 | 0，终端输出 |

调试中出现过三类失败并已修正：旧 B1 venv 未包含新增模块；版本更新后锁文件需同步；新增测试 import 排序和变量名类型推断需修正。最终检查均已通过。

## 未运行 / 未解决事项

- 未运行前端检查；本次未改前端代码。
- 未做真实 Garmin、AI Provider、网络或私人 `states` 数据调用。
- 本次是 Developer 自查，不替代后续全新只读 Validator 和主验收。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "仅在允许的 source 范围内实现 B2：新增 get_running_records 只读查询、收敛 TOOL_CONTRACTS/README、补充合成测试；未修改协调记录、私人 states 或 Git 索引。"
    },
    {
      "id": "criterion-2",
      "status": "satisfied",
      "evidence": "报告列出修改文件、测试新增、实际命令、通过结果、剩余风险和无暂存状态，可供独立验收复核。"
    }
  ],
  "changedFiles": [
    "source/skills/_shared/scripts/trainlab/running_records.py",
    "source/skills/_shared/scripts/trainlab/contracts/interfaces.py",
    "source/skills/_shared/scripts/trainlab/exports.py",
    "source/tools/README.md",
    "source/tests/tools/__init__.py",
    "source/tests/tools/test_running_records.py",
    "source/pyproject.toml",
    "source/uv.lock"
  ],
  "testsAddedOrUpdated": [
    "source/tests/tools/__init__.py",
    "source/tests/tools/test_running_records.py"
  ],
  "commandsRun": [
    {
      "command": "cd source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b2-dev-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable",
      "result": "passed",
      "summary": "按锁文件创建隔离环境并安装 trainlab-source==0.1.1。"
    },
    {
      "command": "cd source && /tmp/trainlab-b2-dev-venv/bin/python -m pytest tests/tools/test_running_records.py -q -p no:cacheprovider",
      "result": "passed",
      "summary": "6 passed。"
    },
    {
      "command": "cd source && /tmp/trainlab-b2-dev-venv/bin/python -m pytest tests -q -p no:cacheprovider",
      "result": "passed",
      "summary": "163 passed, 2 warnings。"
    },
    {
      "command": "cd source && /tmp/trainlab-b2-dev-venv/bin/python -m ruff check --no-cache .",
      "result": "passed",
      "summary": "All checks passed。"
    },
    {
      "command": "cd source && /tmp/trainlab-b2-dev-venv/bin/python -m mypy -p trainlab -p tests --no-incremental",
      "result": "passed",
      "summary": "Success: no issues found in 38 source files。"
    },
    {
      "command": "cd source && /tmp/trainlab-b2-dev-venv/bin/python -m compileall -q skills schemas tests && /tmp/trainlab-b2-dev-venv/bin/python -m trainlab.check_architecture",
      "result": "passed",
      "summary": "compileall 无错误；架构门输出 architecture and public Schema checks passed。"
    },
    {
      "command": "git diff --check && git diff --cached --name-only",
      "result": "passed",
      "summary": "无空白错误；暂存列表为空。"
    }
  ],
  "validationOutput": [
    "pytest tests/tools/test_running_records.py: 6 passed",
    "pytest tests: 163 passed, 2 warnings",
    "ruff: All checks passed",
    "mypy: Success: no issues found in 38 source files",
    "architecture: architecture and public Schema checks passed",
    "no staged files"
  ],
  "residualRisks": [
    "未运行前端检查；本次未改前端。",
    "未做真实 Garmin/AI/网络/私人 states 调用。",
    "仍需后续全新只读 Validator 独立复验。"
  ],
  "noStagedFiles": true,
  "diffSummary": "新增只读 running records 工具、更新工具声明和 README，新增 B2 合成测试及索引漂移检查，并同步 package version/lock 以保证 locked no-editable 安装包含新增模块。",
  "reviewFindings": [
    "no blockers"
  ],
  "manualNotes": "工作区存在任务开始前已有的未提交计划/证据/source 实现；本次只改 source 允许范围内文件，未暂存。"
}
```
