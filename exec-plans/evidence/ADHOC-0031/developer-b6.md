# Developer 报告：ADHOC-0031 B6 / 0031-T6 local Web API and frontend

## 修改摘要

已实现 B6 本地 Web/API 与 React 前端：

- FastAPI 继续保持所有业务接口在 `/api` 下，新增 `/api/status`、活动搜索/详情、活动报告读/生成、周报告列表/详情/生成接口，并在静态挂载前增加 `/api/{path}` 兜底，确保 `/api` 404 返回 JSON envelope 而不是 `index.html`。
- API 只读取显式 `WebAppSettings.instance_root` 下的本地 SQLite/sync 状态；不会在 import 或普通状态/浏览接口读取真实 `states/ai.json`、Garmin 凭据、FIT 原件或密钥。
- 报告生成端点默认禁用 AI；只有调用方/测试显式注入本地 `ai_client` 和 `ai_config` 时才会通过 B5 `ReportService` 生成，避免隐式真实 Provider 请求或读取真实 AI 配置。
- 活动搜索支持 `q`、`sport`、`has_report`、`limit`、`offset`，固定按 `start_time_utc DESC, activity_id` 排序；无数据、非法分页、缺失报告、缺失周报和数据库不可用均返回清晰 envelope。
- 周报告生成复用 B5 缺活动报告策略：有活动但缺活动总结时返回 `POLICY_UNCONFIGURED`；空周仍写入固定文本 `本周无任何运动记录`。未实现自动批次/补跑/周触发策略。
- React 前端展示本地同步/服务状态、活动搜索列表、选中活动详情/报告、周报告、loading/error/empty 状态；报告文本使用 React 文本渲染/`<pre>`，不使用 HTML 注入。
- 前端生产构建仍输出到 `source/skills/local-web/web`，后端只挂载该静态目录，不暴露 `states`、FIT raw、DB、凭据或源码树任意路径。

## 文件清单

- `source/skills/local-web/scripts/server.py`：B6 FastAPI endpoints、显式本地设置、JSON envelope 错误、报告生成接线、SPA/API 404 分离。
- `source/skills/_shared/scripts/trainlab/contracts/web.py`：更新公开 API route contract。
- `source/frontend/src/App.tsx`：本地 dashboard、搜索、状态、活动详情、报告展示。
- `source/frontend/src/contracts.ts`：前端 API/DTO contract。
- `source/frontend/src/styles.css`：B6 UI 样式。
- `source/frontend/tests/app-contract.test.tsx`：前端路由、状态、empty/error、文本转义测试。
- `source/tests/web/test_b6_api.py`：后端 API、分页/过滤、静态/API 404、报告读/生成、无隐式 `states/ai.json` 回归。
- `source/skills/local-web/web/index.html`、`source/skills/local-web/web/assets/index-CG8UOJ96.css`、`source/skills/local-web/web/assets/index-CPbYmAtq.js`：生产前端构建产物。
- `source/pyproject.toml`、`source/skills/_shared/scripts/trainlab/__init__.py`、`source/uv.lock`：版本/锁文件同步到 `0.1.11`。

## API 与 UI 行为说明

- `/api/health`：本地服务健康、route contract、数据库是否存在、是否显式配置 AI；不启动后台任务、不读秘密。
- `/api/status`：本地综合状态、可用 API 路由、数据库存在性、sync state 摘要和 due 状态；只读 `garmin-sync.json` 状态，不读 Garmin 凭据。
- `/api/sync/status`：只读同步状态文件；缺失状态按空状态返回。
- `/api/activities`：支持搜索、运动类型过滤、是否已有活动报告过滤、分页；返回 `items/total/limit/offset/empty`。
- `/api/activities/{activity_id}`：返回选中活动详情与解析 JSON 摘要，不返回 raw FIT。
- `/api/reports/activity/{activity_id}`：读取已有活动报告。
- `POST /api/reports/activity/{activity_id}/generate`：仅在显式注入 fake/local AI client/config 时调用 B5 `ReportService`，成功后保存完整结果。
- `/api/reports/weekly`、`/api/reports/weekly/{report_id}`：读取周报告列表/详情。
- `POST /api/reports/weekly/generate`：显式触发一次周报生成；保留 B5 缺活动报告策略，不发明自动触发/补跑。
- 静态 SPA 通过后端挂载 `source/skills/local-web/web`；未知 `/api/*` 返回 JSON 404，未知非 API 路径回落到 SPA `index.html`。

## 实际版本与工作区

- 分支：`work/adhoc-0031-local-web-system`
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`
- Python package version：`trainlab-source 0.1.11`
- 工作区开始前已有 B1～B5 的未提交产品和协调记录。本次只修改允许范围内的 `source/**`；未修改 `PLAN.md`、`exec-plans/**`、`MEMORY.md`、私人 `states`、Git 配置或 Git 索引。
- 当前暂存文件数：0。

## 检查表

| 命令 | 预期 | 实际结果 | 退出码/证据 |
| --- | --- | --- | --- |
| `cd source && uv lock` | 同步锁文件 | `trainlab-source v0.1.10 -> v0.1.11` | 0，终端输出 |
| `cd source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b6-final-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable` | 隔离安装 | 安装 `trainlab-source==0.1.11` 成功 | 0，`/tmp/trainlab-b6-logs/uv-sync.log` |
| `cd source && /tmp/trainlab-b6-final-venv/bin/python -m pytest tests -q -p no:cacheprovider` | 全量 Python 测试通过 | `195 passed, 2 warnings` | 0，`/tmp/trainlab-b6-logs/pytest-all.log` |
| `cd source && /tmp/trainlab-b6-final-venv/bin/python -m ruff check --no-cache .` | Ruff 通过 | `All checks passed!` | 0，`/tmp/trainlab-b6-logs/ruff.log` |
| `cd source && /tmp/trainlab-b6-final-venv/bin/python -m mypy -p trainlab -p tests --no-incremental` | 类型检查通过 | `Success: no issues found in 52 source files` | 0，`/tmp/trainlab-b6-logs/mypy.log` |
| `cd source && /tmp/trainlab-b6-final-venv/bin/python -m compileall -q skills schemas tests` | 编译通过 | 无错误输出 | 0，`/tmp/trainlab-b6-logs/compileall.log` |
| `cd source && /tmp/trainlab-b6-final-venv/bin/python -m trainlab.check_architecture` | 架构门通过 | `architecture and public Schema checks passed` | 0，`/tmp/trainlab-b6-logs/architecture.log` |
| `cd source/frontend && npm ci --offline` | 前端依赖按锁文件离线安装 | 成功，0 vulnerabilities；npm 提示 fsevents install script 待 approve，未阻塞 | 0，`/tmp/trainlab-b6-logs/npm-ci.log` |
| `cd source/frontend && npm run lint` | 前端 lint 通过 | eslint 无错误 | 0，`/tmp/trainlab-b6-logs/npm-lint.log` |
| `cd source/frontend && npm run typecheck` | 前端类型检查通过 | `tsc --noEmit` 无错误 | 0，`/tmp/trainlab-b6-logs/npm-typecheck.log` |
| `cd source/frontend && npm test` | 前端测试通过 | `1 passed (1), 5 tests passed` | 0，`/tmp/trainlab-b6-logs/npm-test.log` |
| `cd source/frontend && npm run build` | 生产构建输出到后端 web | 输出 `../skills/local-web/web/index.html` 与 assets | 0，`/tmp/trainlab-b6-logs/npm-build.log` |
| `git diff --check` | 无空白错误 | 无输出 | 0，`/tmp/trainlab-b6-logs/git-diff-check.log` |
| `git diff --cached --name-only` | 无暂存文件 | 空输出 | 0，`/tmp/trainlab-b6-logs/staged.log` |

## 未运行 / 未解决事项

- 未做真实 AI Provider、Garmin、网络、登录/MFA、私人 `states/ai.json`、私人认证或真实活动数据调用。
- 未推进 B7、未提交、未推送、未创建 PR。
- `D31-03A/B`、`D31-02A` 仍为未配置策略范围；B6 只提供显式手动 API/合成底座，不实现自动批次、补跑、周触发或旧 records 周配额政策。
- npm 离线安装存在 `fsevents` install script approve 提示，但命令退出 0，前端 lint/type/test/build 均通过。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "仅实现 ADHOC-0031 B6 / 0031-T6：本地 /api endpoints、显式 fake/local AI 报告生成接线、React 浏览/搜索/报告 UI、后端静态服务和对应测试；未推进 B7，未做真实 AI/Garmin/网络调用。"
    },
    {
      "id": "criterion-2",
      "status": "satisfied",
      "evidence": "报告包含修改文件、API/UI 行为、版本/分支/HEAD、命令结果、日志路径、残余风险和无暂存状态；全量 Python 与前端检查均通过。"
    }
  ],
  "changedFiles": [
    "source/skills/local-web/scripts/server.py",
    "source/skills/_shared/scripts/trainlab/contracts/web.py",
    "source/frontend/src/App.tsx",
    "source/frontend/src/contracts.ts",
    "source/frontend/src/styles.css",
    "source/frontend/tests/app-contract.test.tsx",
    "source/tests/web/test_b6_api.py",
    "source/skills/local-web/web/index.html",
    "source/skills/local-web/web/assets/index-CG8UOJ96.css",
    "source/skills/local-web/web/assets/index-CPbYmAtq.js",
    "source/pyproject.toml",
    "source/skills/_shared/scripts/trainlab/__init__.py",
    "source/uv.lock"
  ],
  "testsAddedOrUpdated": [
    "source/tests/web/test_b6_api.py",
    "source/frontend/tests/app-contract.test.tsx"
  ],
  "commandsRun": [
    {
      "command": "cd source && uv lock",
      "result": "passed",
      "summary": "同步 trainlab-source 到 0.1.11。"
    },
    {
      "command": "cd source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b6-final-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable",
      "result": "passed",
      "summary": "隔离安装成功，安装 trainlab-source==0.1.11。"
    },
    {
      "command": "cd source && /tmp/trainlab-b6-final-venv/bin/python -m pytest tests -q -p no:cacheprovider",
      "result": "passed",
      "summary": "195 passed, 2 warnings。"
    },
    {
      "command": "cd source && /tmp/trainlab-b6-final-venv/bin/python -m ruff check --no-cache .",
      "result": "passed",
      "summary": "All checks passed。"
    },
    {
      "command": "cd source && /tmp/trainlab-b6-final-venv/bin/python -m mypy -p trainlab -p tests --no-incremental",
      "result": "passed",
      "summary": "Success: no issues found in 52 source files。"
    },
    {
      "command": "cd source && /tmp/trainlab-b6-final-venv/bin/python -m compileall -q skills schemas tests && /tmp/trainlab-b6-final-venv/bin/python -m trainlab.check_architecture",
      "result": "passed",
      "summary": "compileall 无错误；架构门通过。"
    },
    {
      "command": "cd source/frontend && npm ci --offline && npm run lint && npm run typecheck && npm test && npm run build",
      "result": "passed",
      "summary": "离线 npm ci、eslint、tsc、vitest 5 tests、vite build 均通过；构建输出到 backend web。"
    },
    {
      "command": "git diff --check && git diff --cached --name-only",
      "result": "passed",
      "summary": "无空白错误；暂存列表为空。"
    }
  ],
  "validationOutput": [
    "/tmp/trainlab-b6-logs/uv-sync.log",
    "/tmp/trainlab-b6-logs/pytest-all.log",
    "/tmp/trainlab-b6-logs/ruff.log",
    "/tmp/trainlab-b6-logs/mypy.log",
    "/tmp/trainlab-b6-logs/compileall.log",
    "/tmp/trainlab-b6-logs/architecture.log",
    "/tmp/trainlab-b6-logs/npm-ci.log",
    "/tmp/trainlab-b6-logs/npm-lint.log",
    "/tmp/trainlab-b6-logs/npm-typecheck.log",
    "/tmp/trainlab-b6-logs/npm-test.log",
    "/tmp/trainlab-b6-logs/npm-build.log",
    "/tmp/trainlab-b6-logs/git-diff-check.log",
    "/tmp/trainlab-b6-logs/staged.log"
  ],
  "residualRisks": [
    "未做真实 AI/Garmin/网络/私人 states 调用。",
    "B7 完整端到端和真实外部检查仍未实施。",
    "D31-03A/B、D31-02A 未配置范围仍未实现自动批次/补跑/周触发/旧 records 周配额。",
    "npm ci --offline 对 fsevents install script 给出 approve 提示但退出 0，后续前端检查均通过。"
  ],
  "noStagedFiles": true,
  "diffSummary": "新增 B6 FastAPI 本地 API 与显式报告生成接线，更新 route contracts；实现 React dashboard/search/report UI 并构建到 local-web web；新增后端和前端 B6 回归测试；同步版本/锁文件到 0.1.11。",
  "reviewFindings": [
    "no blockers from developer self-check; independent Validator still required"
  ],
  "manualNotes": "工作区存在任务开始前已有的未提交计划/证据/source 实现；本次仅修改允许范围内 source 文件，未暂存。开发中曾遇到迭代性检查失败（旧 Python 命令不可用、Vitest 不支持 --runInBand、早期 API/测试问题），均已修正；最终检查表命令全部通过。"
}
```
