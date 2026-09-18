# Developer B5 报告：ADHOC-0031 B5 / 0031-T4+T5

## 修改摘要

实现了 B5 的兼容 AI API 工具循环、三模式 Context、受限资料读取和报告服务合成接线；全程使用 fake AI/合成数据验证，未做真实 AI Provider、Garmin、网络、私人 `states` 或密钥调用。

- 新增 `trainlab.ai`：
  - `AIConfig` / `load_ai_config`：只按显式实例根读取 `states/ai.json`，不在测试中读取真实配置。
  - `HttpCompatibleAIClient`：OpenAI-compatible `/chat/completions` 薄 HTTP 客户端。
  - `run_tool_loop`：支持无工具、单/多轮工具调用、多个 `tool_call_id` 回填，直到无 tool calls 后返回最终全文。
  - 对截断、坏响应、HTTP/外部错误、超轮次、未知工具、参数越权、工具失败返回明确异常，不返回半份成功。
- 新增 `trainlab.reference_tools`：实现受限 `read_reference(reference_id)`，只允许 `garmin-fit-parsing`、`longdou` 映射 ID，不接受路径/URL/SQL/文件参数。
- 新增 `trainlab.context`：实现 activity / daily / weekly 三模式 Context；公共组成包含角色、tools README、references README、多轮内存历史和当前对话；activity 含 `ActivityFacts`；weekly 用同一 T 读取过去七天活动总结，缺活动总结返回 `POLICY_UNCONFIGURED`，空周保留固定文本；daily 仅占位且无数据库副作用。
- 新增 `trainlab.report_service`：活动/周报告仅在 AI 最终成功后保存；AI 失败、截断、工具越权或缺报策略未配置时不写入；空活动周按固定文本写入。
- 更新 `TOOL_CONTRACTS` 和 `source/tools/README.md`：当前注册 `get_running_records` 与 `read_reference`，其中 `get_running_records` 仍是唯一采样查询工具。
- 更新 `source/README.md`、导出入口和包版本/锁文件到 `0.1.6`。
- 新增 B5 合成测试覆盖 AI loop、dispatcher、Context、report service 和隐私边界。

## 文件清单

- `source/skills/_shared/scripts/trainlab/ai.py`
- `source/skills/_shared/scripts/trainlab/reference_tools.py`
- `source/skills/_shared/scripts/trainlab/context.py`
- `source/skills/_shared/scripts/trainlab/report_service.py`
- `source/skills/_shared/scripts/trainlab/contracts/interfaces.py`
- `source/skills/_shared/scripts/trainlab/exports.py`
- `source/skills/_shared/scripts/trainlab/__init__.py`
- `source/tools/README.md`
- `source/README.md`
- `source/tests/ai/__init__.py`
- `source/tests/ai/test_b5_ai_context.py`
- `source/tests/tools/test_running_records.py`
- `source/tests/reports/test_report_storage.py`
- `source/pyproject.toml`
- `source/uv.lock`

## 实际版本与未提交改动

- 分支：`work/adhoc-0031-local-web-system`
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`
- 工作区开始前已有未提交计划/证据移动和 `source/` 产品实现；本次只修改允许范围内的 `source/**` 文件。
- 未修改 `PLAN.md`、`exec-plans/**`、`MEMORY.md`、私人 `states`、Git 配置或 Git 索引。
- 当前暂存文件数：0。

## 检查表

| 命令 | 预期 | 实际结果 | 退出码 / 证据 |
| --- | --- | --- | --- |
| `cd source && uv lock` | 同步版本锁 | `trainlab-source v0.1.5 -> v0.1.6` | 0 |
| `cd source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b5-developer-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable` | 仓库外隔离安装 | 安装 `trainlab-source==0.1.6` | 0；`/tmp/trainlab-b5-developer-uv-sync-final.log` |
| `cd source && /tmp/trainlab-b5-developer-venv/bin/python -m pytest tests/ai/test_b5_ai_context.py -q -p no:cacheprovider` | B5 新测试通过 | `11 passed` | 0；终端输出 |
| `cd source && /tmp/trainlab-b5-developer-venv/bin/python -m pytest tests -q -p no:cacheprovider` | 全量 Python 测试通过 | `189 passed, 2 warnings` | 0；`/tmp/trainlab-b5-developer-pytest-all.log` |
| `cd source && /tmp/trainlab-b5-developer-venv/bin/python -m ruff check --no-cache .` | 静态检查通过 | `All checks passed!` | 0；`/tmp/trainlab-b5-developer-ruff.log` |
| `cd source && /tmp/trainlab-b5-developer-venv/bin/python -m mypy -p trainlab -p tests --no-incremental` | 类型检查通过 | `Success: no issues found in 50 source files` | 0；`/tmp/trainlab-b5-developer-mypy.log` |
| `cd source && /tmp/trainlab-b5-developer-venv/bin/python -m compileall -q skills schemas tests` | 编译通过 | 无错误输出 | 0；`/tmp/trainlab-b5-developer-compileall.log` |
| `cd source && /tmp/trainlab-b5-developer-venv/bin/python -m trainlab.check_architecture` | 架构门通过 | `architecture and public Schema checks passed` | 0；`/tmp/trainlab-b5-developer-architecture.log` |
| `git diff --check && git diff --cached --name-only` | 无空白错误且无暂存 | 通过，暂存列表为空 | 0；`/tmp/trainlab-b5-developer-diff-check.log`、`/tmp/trainlab-b5-developer-staged.log` |

## 未运行 / 未解决事项

- 未运行前端检查；本次未修改 `source/frontend/**`。
- 未做真实 AI Provider、Garmin、网络、登录/MFA、私人 `states/ai.json`、私人认证或真实活动数据调用。
- B5 只完成兼容 API / Context / 报告服务的合成接线；真实 AI 实服务检查、B6 Web/API 和完整端到端仍属后续阶段。
- D31-03A/B、D31-02A 仍未决定；本次没有猜测自动批次、补跑、周触发/缺报或旧 records 周配额策略。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "在允许的 source 范围内实现 B5：AI tool loop、dispatcher/read_reference、三模式 Context、报告服务合成接线和合成测试；未改协调记录、私人 states 或 Git 索引，未做真实外部调用。"
    },
    {
      "id": "criterion-2",
      "status": "satisfied",
      "evidence": "报告列出修改文件、测试新增、最终命令、通过结果、日志路径、残余风险和无暂存状态，可供独立验收复核。"
    }
  ],
  "changedFiles": [
    "source/skills/_shared/scripts/trainlab/ai.py",
    "source/skills/_shared/scripts/trainlab/reference_tools.py",
    "source/skills/_shared/scripts/trainlab/context.py",
    "source/skills/_shared/scripts/trainlab/report_service.py",
    "source/skills/_shared/scripts/trainlab/contracts/interfaces.py",
    "source/skills/_shared/scripts/trainlab/exports.py",
    "source/skills/_shared/scripts/trainlab/__init__.py",
    "source/tools/README.md",
    "source/README.md",
    "source/tests/ai/__init__.py",
    "source/tests/ai/test_b5_ai_context.py",
    "source/tests/tools/test_running_records.py",
    "source/tests/reports/test_report_storage.py",
    "source/pyproject.toml",
    "source/uv.lock"
  ],
  "testsAddedOrUpdated": [
    "source/tests/ai/__init__.py",
    "source/tests/ai/test_b5_ai_context.py",
    "source/tests/tools/test_running_records.py",
    "source/tests/reports/test_report_storage.py"
  ],
  "commandsRun": [
    {
      "command": "cd source && uv lock",
      "result": "passed",
      "summary": "同步 trainlab-source 版本到 0.1.6。"
    },
    {
      "command": "cd source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b5-developer-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable",
      "result": "passed",
      "summary": "按锁文件创建仓库外隔离环境并安装 trainlab-source==0.1.6。"
    },
    {
      "command": "cd source && /tmp/trainlab-b5-developer-venv/bin/python -m pytest tests/ai/test_b5_ai_context.py -q -p no:cacheprovider",
      "result": "passed",
      "summary": "11 passed。"
    },
    {
      "command": "cd source && /tmp/trainlab-b5-developer-venv/bin/python -m pytest tests -q -p no:cacheprovider",
      "result": "passed",
      "summary": "189 passed, 2 warnings。"
    },
    {
      "command": "cd source && /tmp/trainlab-b5-developer-venv/bin/python -m ruff check --no-cache .",
      "result": "passed",
      "summary": "All checks passed。"
    },
    {
      "command": "cd source && /tmp/trainlab-b5-developer-venv/bin/python -m mypy -p trainlab -p tests --no-incremental",
      "result": "passed",
      "summary": "Success: no issues found in 50 source files。"
    },
    {
      "command": "cd source && /tmp/trainlab-b5-developer-venv/bin/python -m compileall -q skills schemas tests && /tmp/trainlab-b5-developer-venv/bin/python -m trainlab.check_architecture",
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
    "/tmp/trainlab-b5-developer-uv-sync-final.log",
    "/tmp/trainlab-b5-developer-pytest-all.log",
    "/tmp/trainlab-b5-developer-ruff.log",
    "/tmp/trainlab-b5-developer-mypy.log",
    "/tmp/trainlab-b5-developer-compileall.log",
    "/tmp/trainlab-b5-developer-architecture.log",
    "/tmp/trainlab-b5-developer-diff-check.log",
    "/tmp/trainlab-b5-developer-staged.log"
  ],
  "residualRisks": [
    "未做真实 AI Provider/Garmin/网络/私人 states 调用。",
    "真实 AI 实服务检查、B6 Web/API 和完整端到端仍未实施。",
    "D31-03A/B、D31-02A 仍未决定，本次未实现默认自动策略。"
  ],
  "noStagedFiles": true,
  "diffSummary": "新增 B5 AI/Context/reference/report service 模块和合成测试；注册 read_reference 非采样工具；更新 README、工具索引、导出和 source 包版本/锁文件到 0.1.6。",
  "reviewFindings": [
    "no blockers from developer self-check; independent Validator still required"
  ],
  "manualNotes": "工作区存在任务开始前已有的未提交计划/证据/source 实现；本次只改 source 允许范围内文件，未暂存。"
}
```
