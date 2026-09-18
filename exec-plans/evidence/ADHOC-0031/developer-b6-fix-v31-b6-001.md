# Developer 修复报告：V31-B6-001

## 修改摘要

已修复 ADHOC-0031 B6 / 0031-T6 的 V31-B6-001：FastAPI 参数/路径/body 解析失败产生的 `RequestValidationError` 现在会进入项目统一错误响应路径，返回 `ok=false,data=null,error={code,message,details}`，错误码为 `INVALID_ARGUMENT`，HTTP 状态使用项目映射的 400，不再返回 FastAPI 默认 `{"detail": ...}`。

## 文件清单

- `source/skills/local-web/scripts/server.py`：新增 `RequestValidationError` exception handler，复用 `_error_response(ErrorCode.INVALID_ARGUMENT, ...)`，不暴露 FastAPI 原始校验 detail、堆栈或请求内容。
- `source/tests/web/test_b6_api.py`：新增 V31-B6-001 回归，覆盖：
  - `GET /api/activities?limit=abc`
  - `GET /api/reports/weekly/not-int`
  - `POST /api/reports/weekly/generate` body 为非对象 JSON
  - 均断言统一 envelope、`INVALID_ARGUMENT`、HTTP 400、无顶层 `detail`。
- `source/pyproject.toml`：版本更新到 `0.1.12`。
- `source/skills/_shared/scripts/trainlab/__init__.py`：包版本更新到 `0.1.12`。
- `source/uv.lock`：同步 locked no-editable 安装版本。

未修改前端代码；API 错误显示合同不需要前端变更。

## 修复说明

- 根因：B6 首轮实现只处理了 `StarletteHTTPException` 和业务 `ValueError`，没有注册 FastAPI `RequestValidationError` 处理器；因此 query/path/body 类型解析失败时绕过项目 `_error_response`，直接返回 FastAPI 默认 422 `detail` body。
- 本次修法与失败实现的区别：不在各 endpoint 内逐项手工解析所有参数，而是在 FastAPI 应用层统一捕获请求校验错误，并复用项目现有 envelope/status 映射，保证 `/api` 参数解析类错误也与业务错误格式一致。
- 隐私与安全边界：响应只返回通用消息 `request parameters are invalid`，不回显请求体、私密路径、内部校验结构或堆栈。
- 累计失败事实：V31-B6-001 首次独立验证失败 1；本次为修复尝试 1，开发自查通过，仍需全新只读 Validator 复验。
- 实施中发现：初次 targeted pytest 使用 no-editable 旧安装包时仍复现失败；随后同步版本到 `0.1.12` 并用 `--reinstall-package trainlab-source` 重装隔离 venv，确认安装包包含本次 handler 后全部检查通过。

## 实际版本与未提交改动

- 工作目录：`/Volumes/DiskOther/Code/TrainLab`
- 分支：`work/adhoc-0031-local-web-system`
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`
- Python package version：`trainlab-source 0.1.12`
- 工作区开始前已有未提交的计划/证据移动、`source/` 产品实现和协调记录。本次只修改允许范围内的 `source/**` 文件，未修改 `PLAN.md`、`exec-plans/**`、`MEMORY.md`、私人 `states`、Git 配置或 Git 索引。
- 当前暂存文件数：0。
- 已清理本次检查在仓库内产生的 `source/**/__pycache__`、`source/.mypy_cache`、`source/build`、`source/trainlab_source.egg-info`。

## 检查表

| 命令 | 预期 | 实际结果 | 退出码 / 证据 |
| --- | --- | --- | --- |
| `cd source && uv lock` | 同步锁文件 | `trainlab-source` 版本同步到 `0.1.12` | 0，`/tmp/trainlab-b6-fix-v31-b6-001-logs/uv-lock.log` |
| `cd source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b6-fix-v31-b6-001-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable --reinstall-package trainlab-source` | 仓库外隔离安装，安装包包含修复 | 通过；探针确认 installed `trainlab.local_web.server` 包含 `request_validation_error_handler` | 0，`/tmp/trainlab-b6-fix-v31-b6-001-logs/uv-sync.log` |
| `cd source && /tmp/trainlab-b6-fix-v31-b6-001-venv/bin/python -m pytest tests/web/test_b6_api.py -q -p no:cacheprovider` | B6 后端 API 测试和新增 422/envelope 回归通过 | `5 passed, 2 warnings` | 0，`/tmp/trainlab-b6-fix-v31-b6-001-logs/pytest-web.log` |
| `cd source && /tmp/trainlab-b6-fix-v31-b6-001-venv/bin/python -m pytest tests -q -p no:cacheprovider` | 全量 Python 测试通过 | `196 passed, 2 warnings` | 0，`/tmp/trainlab-b6-fix-v31-b6-001-logs/pytest-all.log` |
| `cd source && /tmp/trainlab-b6-fix-v31-b6-001-venv/bin/python -m ruff check --no-cache .` | Ruff 通过 | `All checks passed!` | 0，`/tmp/trainlab-b6-fix-v31-b6-001-logs/ruff.log` |
| `cd source && /tmp/trainlab-b6-fix-v31-b6-001-venv/bin/python -m mypy -p trainlab -p tests --no-incremental` | 类型检查通过 | `Success: no issues found in 52 source files` | 0，`/tmp/trainlab-b6-fix-v31-b6-001-logs/mypy.log` |
| `cd source && /tmp/trainlab-b6-fix-v31-b6-001-venv/bin/python -m compileall -q skills schemas tests` | 编译通过 | 无错误输出 | 0，`/tmp/trainlab-b6-fix-v31-b6-001-logs/compileall.log` |
| `cd source && /tmp/trainlab-b6-fix-v31-b6-001-venv/bin/python -m trainlab.check_architecture` | 架构门通过 | `architecture and public Schema checks passed` | 0，`/tmp/trainlab-b6-fix-v31-b6-001-logs/architecture.log` |
| validation envelope probe for `limit=abc`, `weekly/not-int`, list JSON body | 三类 FastAPI 校验失败均返回 envelope + `INVALID_ARGUMENT` + HTTP 400 | 三项均返回 `{'ok': False, 'data': None, 'error': {'code': 'INVALID_ARGUMENT', 'message': 'request parameters are invalid', 'details': {}}}` | 0，`/tmp/trainlab-b6-fix-v31-b6-001-logs/probe-validation-envelope.log` |
| `git diff --check && git diff --cached --name-only` | 无空白错误且无暂存 | 通过；暂存列表为空 | 0，`/tmp/trainlab-b6-fix-v31-b6-001-logs/git-diff-check.log`、`/tmp/trainlab-b6-fix-v31-b6-001-logs/staged.log` |

## 未运行 / 未解决事项

- 未运行前端 lint/type/test/build，因为本次未修改 `source/frontend/**` 或前端合同显示逻辑。
- 未做真实 AI Provider、Garmin、网络、登录/MFA、私人 `states/ai.json`、私人认证或真实活动数据调用，符合本次边界。
- 未推进 B7，未提交、未推送、未创建 PR。
- 本次是 Developer 修复自查，不替代后续全新只读 Validator 复验。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "仅修复 V31-B6-001：新增 RequestValidationError 处理器并补充后端回归，覆盖 FastAPI query/path/body 校验失败统一 envelope。"
    },
    {
      "id": "criterion-2",
      "status": "satisfied",
      "evidence": "报告列出修改文件、失败原因、修复方式、命令结果、日志路径、残余风险和无暂存状态，可供独立验收复核。"
    }
  ],
  "changedFiles": [
    "source/skills/local-web/scripts/server.py",
    "source/tests/web/test_b6_api.py",
    "source/pyproject.toml",
    "source/skills/_shared/scripts/trainlab/__init__.py",
    "source/uv.lock"
  ],
  "testsAddedOrUpdated": [
    "source/tests/web/test_b6_api.py"
  ],
  "commandsRun": [
    {
      "command": "cd source && uv lock",
      "result": "passed",
      "summary": "同步 trainlab-source 到 0.1.12。"
    },
    {
      "command": "cd source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b6-fix-v31-b6-001-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable --reinstall-package trainlab-source",
      "result": "passed",
      "summary": "隔离安装成功，安装包包含本次 RequestValidationError handler。"
    },
    {
      "command": "cd source && /tmp/trainlab-b6-fix-v31-b6-001-venv/bin/python -m pytest tests/web/test_b6_api.py -q -p no:cacheprovider",
      "result": "passed",
      "summary": "5 passed, 2 warnings。"
    },
    {
      "command": "cd source && /tmp/trainlab-b6-fix-v31-b6-001-venv/bin/python -m pytest tests -q -p no:cacheprovider",
      "result": "passed",
      "summary": "196 passed, 2 warnings。"
    },
    {
      "command": "cd source && /tmp/trainlab-b6-fix-v31-b6-001-venv/bin/python -m ruff check --no-cache .",
      "result": "passed",
      "summary": "All checks passed。"
    },
    {
      "command": "cd source && /tmp/trainlab-b6-fix-v31-b6-001-venv/bin/python -m mypy -p trainlab -p tests --no-incremental",
      "result": "passed",
      "summary": "Success: no issues found in 52 source files。"
    },
    {
      "command": "cd source && /tmp/trainlab-b6-fix-v31-b6-001-venv/bin/python -m compileall -q skills schemas tests && /tmp/trainlab-b6-fix-v31-b6-001-venv/bin/python -m trainlab.check_architecture",
      "result": "passed",
      "summary": "compileall 无错误；架构门通过。"
    },
    {
      "command": "validation envelope probe for /api/activities?limit=abc, /api/reports/weekly/not-int, and list JSON body",
      "result": "passed",
      "summary": "三项均返回 HTTP 400、ok=false、INVALID_ARGUMENT、空 details 的项目 envelope。"
    },
    {
      "command": "git diff --check && git diff --cached --name-only",
      "result": "passed",
      "summary": "无空白错误；暂存列表为空。"
    }
  ],
  "validationOutput": [
    "/tmp/trainlab-b6-fix-v31-b6-001-logs/uv-lock.log",
    "/tmp/trainlab-b6-fix-v31-b6-001-logs/uv-sync.log",
    "/tmp/trainlab-b6-fix-v31-b6-001-logs/pytest-web.log",
    "/tmp/trainlab-b6-fix-v31-b6-001-logs/pytest-all.log",
    "/tmp/trainlab-b6-fix-v31-b6-001-logs/ruff.log",
    "/tmp/trainlab-b6-fix-v31-b6-001-logs/mypy.log",
    "/tmp/trainlab-b6-fix-v31-b6-001-logs/compileall.log",
    "/tmp/trainlab-b6-fix-v31-b6-001-logs/architecture.log",
    "/tmp/trainlab-b6-fix-v31-b6-001-logs/probe-validation-envelope.log",
    "/tmp/trainlab-b6-fix-v31-b6-001-logs/git-diff-check.log",
    "/tmp/trainlab-b6-fix-v31-b6-001-logs/staged.log"
  ],
  "residualRisks": [
    "未做真实 AI/Garmin/网络/私人 states 调用。",
    "未运行前端检查，因为前端文件未修改。",
    "本次自查不替代全新只读 Validator 复验。"
  ],
  "noStagedFiles": true,
  "diffSummary": "为 local-web FastAPI app 添加 RequestValidationError -> INVALID_ARGUMENT envelope 处理；新增 B6 API validation 回归；同步 source 包版本/锁文件到 0.1.12。",
  "reviewFindings": [
    "no blockers from developer self-check; independent Validator still required"
  ],
  "manualNotes": "工作区存在任务开始前已有的未提交计划/证据/source 实现；本次只改允许范围内 source 文件，未暂存。初次 targeted pytest 曾因 no-editable venv 仍使用旧 0.1.11 安装包而复现失败，已通过版本/锁文件同步和 --reinstall-package 修正，最终检查全部通过。"
}
```
