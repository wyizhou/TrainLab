# Developer 修复报告：V31-B5-001

## 修改摘要

修复 ADHOC-0031 B5 / 0031-T4+T5 的 V31-B5-001：`ReportService` 现在会把宿主配置在 `ToolDispatcher.capacity` 里的 storage 容量限制传给活动报告与周报告保存函数。AI 已经成功返回最终文本后，如果 summary 超过 `storage_bytes_limit`，保存层会抛出 `RESOURCE_LIMIT`，不会插入或覆盖报告，也不会把活动报告历史追加为成功对话。

## 文件清单

- `source/skills/_shared/scripts/trainlab/report_service.py`：保存 activity / weekly / empty-week 报告时传入 `self.dispatcher.capacity`。
- `source/tests/ai/test_b5_ai_context.py`：新增 V31-B5-001 回归，覆盖活动报告超限不插入/不覆盖、周报告 AI summary 超限不插入、空周固定 summary 同样受容量限制；保留正常成功用例。
- `source/pyproject.toml`：版本更新到 `0.1.7`。
- `source/skills/_shared/scripts/trainlab/__init__.py`：包版本更新到 `0.1.7`。
- `source/uv.lock`：同步 locked no-editable 安装版本。

## 修复说明

- 根因：`reports.py` 的 `save_activity_report` / `save_weekly_report` 已有 `capacity` 参数并能返回 `RESOURCE_LIMIT`，但 `report_service.py` 调用保存函数时没有传入 `dispatcher.capacity`，导致报告服务层绕过 storage 容量限制。
- 本次修法与失败实现的区别：不新增另一套容量检查，而是复用既有保存层容量边界，确保所有报告写入路径（活动报告、AI 周报告、空周固定周报）都走同一个 `CapacityPolicy`。
- 累计失败事实：V31-B5-001 首次独立验证失败 1；本次为修复尝试 1，开发自查全部通过，仍需全新只读 Validator 复验。

## 实际版本与未提交改动

- 工作目录：`/Volumes/DiskOther/Code/TrainLab`
- 分支：`work/adhoc-0031-local-web-system`
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`
- 工作区开始前已有未提交计划/证据移动和 `source/` 产品实现；本次只修改允许范围内的 `source/**` 文件，未修改 `PLAN.md`、`exec-plans/**`、`MEMORY.md`、私人 `states`、Git 配置或 Git 索引。
- 当前暂存文件数：0。

## 检查表

| 命令 | 预期 | 实际结果 | 退出码 / 证据 |
| --- | --- | --- | --- |
| `cd source && uv lock` | 同步锁文件 | `trainlab-source v0.1.6 -> v0.1.7` | 0，终端输出 |
| `cd source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b5-fix-v31-b5-001-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable` | 仓库外隔离安装，安装包包含修复 | 通过，安装 `trainlab-source==0.1.7` | 0，`/tmp/trainlab-b5-fix-v31-b5-001-logs/uv-sync.log` |
| `cd source && /tmp/trainlab-b5-fix-v31-b5-001-venv/bin/python -m pytest tests/ai/test_b5_ai_context.py -q -p no:cacheprovider` | B5 AI/Context 测试和新增容量回归通过 | `13 passed` | 0，`/tmp/trainlab-b5-fix-v31-b5-001-logs/pytest-ai.log` |
| `cd source && /tmp/trainlab-b5-fix-v31-b5-001-venv/bin/python -m pytest tests -q -p no:cacheprovider` | 全量 Python 测试通过 | `191 passed, 2 warnings` | 0，`/tmp/trainlab-b5-fix-v31-b5-001-logs/pytest-all.log` |
| `cd source && /tmp/trainlab-b5-fix-v31-b5-001-venv/bin/python -m ruff check --no-cache .` | 静态检查通过 | `All checks passed!` | 0，`/tmp/trainlab-b5-fix-v31-b5-001-logs/ruff.log` |
| `cd source && /tmp/trainlab-b5-fix-v31-b5-001-venv/bin/python -m mypy -p trainlab -p tests --no-incremental` | 类型检查通过 | `Success: no issues found in 50 source files` | 0，`/tmp/trainlab-b5-fix-v31-b5-001-logs/mypy.log` |
| `cd source && /tmp/trainlab-b5-fix-v31-b5-001-venv/bin/python -m compileall -q skills schemas tests` | 编译通过 | 无错误输出 | 0，`/tmp/trainlab-b5-fix-v31-b5-001-logs/compileall.log` |
| `cd source && /tmp/trainlab-b5-fix-v31-b5-001-venv/bin/python -m trainlab.check_architecture` | 架构门通过 | `architecture and public Schema checks passed` | 0，`/tmp/trainlab-b5-fix-v31-b5-001-logs/architecture.log` |
| `git diff --check && git diff --cached --name-only` | 无空白错误且无暂存 | 通过，暂存列表为空 | 0，`/tmp/trainlab-b5-fix-v31-b5-001-logs/git-diff-check.log`、`/tmp/trainlab-b5-fix-v31-b5-001-logs/staged.log` |

## 未运行 / 未解决事项

- 未做真实 AI Provider、Garmin、网络、登录/MFA、私人 `states/ai.json`、私人认证或真实活动数据调用，符合本次边界。
- 未推进 B6～B7。
- 本次是 Developer 修复自查，不替代后续全新只读 Validator 复验。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "仅修复 V31-B5-001：ReportService 将 dispatcher.capacity 传给活动和周报告保存路径，新增容量回归覆盖活动报告插入/覆盖、AI 周报和空周固定周报。"
    },
    {
      "id": "criterion-2",
      "status": "satisfied",
      "evidence": "报告列出修改文件、失败原因、修复方式、命令结果、日志路径、残余风险和无暂存状态，可供独立验收复核。"
    }
  ],
  "changedFiles": [
    "source/skills/_shared/scripts/trainlab/report_service.py",
    "source/tests/ai/test_b5_ai_context.py",
    "source/skills/_shared/scripts/trainlab/__init__.py",
    "source/pyproject.toml",
    "source/uv.lock"
  ],
  "testsAddedOrUpdated": [
    "source/tests/ai/test_b5_ai_context.py"
  ],
  "commandsRun": [
    {
      "command": "cd source && uv lock",
      "result": "passed",
      "summary": "同步 trainlab-source 版本到 0.1.7。"
    },
    {
      "command": "cd source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b5-fix-v31-b5-001-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable",
      "result": "passed",
      "summary": "按锁文件创建仓库外隔离环境并安装 trainlab-source==0.1.7。"
    },
    {
      "command": "cd source && /tmp/trainlab-b5-fix-v31-b5-001-venv/bin/python -m pytest tests/ai/test_b5_ai_context.py -q -p no:cacheprovider",
      "result": "passed",
      "summary": "13 passed。"
    },
    {
      "command": "cd source && /tmp/trainlab-b5-fix-v31-b5-001-venv/bin/python -m pytest tests -q -p no:cacheprovider",
      "result": "passed",
      "summary": "191 passed, 2 warnings。"
    },
    {
      "command": "cd source && /tmp/trainlab-b5-fix-v31-b5-001-venv/bin/python -m ruff check --no-cache .",
      "result": "passed",
      "summary": "All checks passed。"
    },
    {
      "command": "cd source && /tmp/trainlab-b5-fix-v31-b5-001-venv/bin/python -m mypy -p trainlab -p tests --no-incremental",
      "result": "passed",
      "summary": "Success: no issues found in 50 source files。"
    },
    {
      "command": "cd source && /tmp/trainlab-b5-fix-v31-b5-001-venv/bin/python -m compileall -q skills schemas tests && /tmp/trainlab-b5-fix-v31-b5-001-venv/bin/python -m trainlab.check_architecture",
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
    "/tmp/trainlab-b5-fix-v31-b5-001-logs/uv-sync.log",
    "/tmp/trainlab-b5-fix-v31-b5-001-logs/pytest-ai.log",
    "/tmp/trainlab-b5-fix-v31-b5-001-logs/pytest-all.log",
    "/tmp/trainlab-b5-fix-v31-b5-001-logs/ruff.log",
    "/tmp/trainlab-b5-fix-v31-b5-001-logs/mypy.log",
    "/tmp/trainlab-b5-fix-v31-b5-001-logs/compileall.log",
    "/tmp/trainlab-b5-fix-v31-b5-001-logs/architecture.log",
    "/tmp/trainlab-b5-fix-v31-b5-001-logs/git-diff-check.log",
    "/tmp/trainlab-b5-fix-v31-b5-001-logs/staged.log"
  ],
  "residualRisks": [
    "未做真实 AI Provider/Garmin/网络/私人 states 调用。",
    "真实 AI 实服务检查、B6 Web/API 和完整端到端仍未实施。",
    "本次自查不替代全新只读 Validator 复验。"
  ],
  "noStagedFiles": true,
  "diffSummary": "ReportService 保存报告时传递 dispatcher.capacity；新增活动/周报告 storage 容量边界回归；同步 source 包版本/锁文件到 0.1.7。",
  "reviewFindings": [
    "no blockers from developer self-check; independent Validator still required"
  ],
  "manualNotes": "工作区存在任务开始前已有的未提交计划/证据/source 实现；本次只改允许范围内 source 文件，未暂存。"
}
```
