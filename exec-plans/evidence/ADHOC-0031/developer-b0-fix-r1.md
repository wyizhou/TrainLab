Implemented ADHOC-0031 B0 first repair for V31-B0-001～006.

## 修改摘要

- V31-B0-001：将前端改为真实 React + Vite + TypeScript 最小工程，新增 lint/type/test/build 入口；生产构建输出到 `source/skills/local-web/web`，生成产物由 `.gitignore` 精确忽略。
- V31-B0-002：补全 `source/pyproject.toml` dev 依赖（pytest/httpx/ruff/mypy），已用隔离 venv 仅按声明依赖安装并运行 pytest/ruff/mypy/compile/Schema 检查。
- V31-B0-003：修复 SQLite DDL 中 TEXT 身份主键的显式 `NOT NULL`，补 NULL、重复键、孤儿行、跨表删除保护和正常插入回归。
- V31-B0-004：静态根校验改为正规化路径 + 真实根检查，拒绝越界和静态根软链接；FastAPI health/404 使用公共错误壳，TestClient 覆盖正常静态与合成 states 软链接拒绝。
- V31-B0-005：内存历史统一使用 `ensure_utc`，拒绝无时区绝对时间；测试覆盖 UTC/Asia-Shanghai 系统 TZ 下行为一致。
- V31-B0-006：新增公共 DTO/JSON Schema/工具/资料/授权/容量/重复/报告写入/周窗口/未决政策合同，显式保留 D31-03A/B、D31-02A 为未配置；未实现 B1～B7 业务执行。

## 变更文件

- `.gitignore`
- `source/README.md`
- `source/pyproject.toml`
- `source/frontend/eslint.config.js`
- `source/frontend/index.html`
- `source/frontend/package-lock.json`
- `source/frontend/package.json`
- `source/frontend/src/App.tsx`
- `source/frontend/src/contracts.ts`
- `source/frontend/src/main.tsx`
- `source/frontend/src/styles.css`
- `source/frontend/src/vite-env.d.ts`
- `source/frontend/tests/app-contract.test.tsx`
- `source/frontend/tsconfig.json`
- `source/frontend/vite.config.ts`
- `source/skills/_shared/scripts/contracts.py`
- `source/skills/local-web/scripts/server.py`
- `source/tests/__init__.py`
- `source/tests/contracts/__init__.py`
- `source/tests/contracts/test_b0_contracts.py`
- `source/tools/README.md`
- `source/tools/check_b0_static.py`
- `source/trainlab/__init__.py`
- `source/trainlab/contracts/__init__.py`
- `source/trainlab/contracts/config.py`
- `source/trainlab/contracts/errors.py`
- `source/trainlab/contracts/interfaces.py`
- `source/trainlab/contracts/paths.py`
- `source/trainlab/contracts/schema.py`
- `source/trainlab/contracts/session.py`
- `source/trainlab/contracts/time.py`
- `source/trainlab/contracts/web.py`
- `source/trainlab/py.typed`

未修改协调记录；`PLAN.md`、`MEMORY.md`、`exec-plans/**` 的未提交状态为任务开始前已有。

## 修复说明

- 失败原因：B0 初版只有前端字符串壳和部分合同骨架；Python dev 依赖不自足；SQLite TEXT PK 未显式非空；静态根只做词法父路径检查；历史时间对 naive datetime 使用本机时区；T2 缺少后续消费者可依赖的 DTO/权限/容量/错误/报告等公共协议。
- 本次办法与历史办法区别：这是首次实质修复（修复尝试 0 → 1），不再用占位脚本/常量测试代替合同；通过真实 React/Vite、声明依赖环境、可执行边界测试和接口合同类型补齐 B0。
- 累计失败事实：首次验收失败 1 轮；修复验证失败 0 轮；本轮仍需全新 Validator 独立复验。

## 实际版本与未提交状态

- 分支：`work/adhoc-0031-local-web-system`
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`
- 开始状态：存在既有未提交协调记录与未提交 `source/` 实现。
- 结束状态：`.gitignore` 修改、`source/` 非忽略产品文件未跟踪；协调记录仍显示既有未提交改动；暂存区为空。

## 检查表

| 命令 | 预期 | 实际 |
| --- | --- | --- |
| `git status --short --branch`（开始） | 核对分支与未提交改动 | 退出0；分支正确；显示既有协调记录改动和未跟踪 source |
| `cd source/frontend && npm install` | 安装前端声明依赖 | 退出0；生成 `package-lock.json`；0 vulnerabilities |
| `cd source/frontend && npm ci` | 锁文件可重装 | 退出0；0 vulnerabilities；提示 fsevents install script 待 approve，但未阻塞 |
| `cd source/frontend && npm run lint && npm run typecheck && npm test && npm run build` | 前端 lint/type/test/build 全通过，构建到后端 web | 退出0；Vitest 1 文件 3 通过；Vite 输出到 `../skills/local-web/web` |
| `python3.12 -m venv /tmp/trainlab-b0-fix-venv && uv pip install --python /tmp/trainlab-b0-fix-venv/bin/python -r source/pyproject.toml --extra dev` | 仅声明依赖可安装 | 退出0；安装 pytest/httpx/ruff/mypy/FastAPI 等声明依赖 |
| `cd source && /tmp/trainlab-b0-fix-venv/bin/python -m pytest tests -vv -p no:cacheprovider` | B0 回归覆盖正常/错误/边界 | 退出0；17 passed，2 个第三方 deprecation warnings |
| `cd source && /tmp/trainlab-b0-fix-venv/bin/python -m ruff check --no-cache .` | Python lint 通过 | 退出0；All checks passed |
| `cd source && /tmp/trainlab-b0-fix-venv/bin/python -m mypy trainlab skills tools tests` | 类型检查通过 | 退出0；Success: no issues found in 16 source files |
| `/tmp/trainlab-b0-fix-venv/bin/python -m compileall -q source` | Python 编译通过 | 退出0 |
| `PYTHONPATH=source /tmp/trainlab-b0-fix-venv/bin/python source/tools/check_b0_static.py` | 静态合同/Schema 样例检查通过 | 退出0；B0 static contract check passed |
| `git diff --check` | 无 whitespace diff 问题 | 退出0 |
| `git diff --cached --quiet && echo no-staged-files` | 无暂存文件 | 退出0；no-staged-files |

说明：曾并行在 `npm ci` 同时运行 lint/type/test，因 `npm ci` 正在重建 node_modules 导致这些并行命令失败；随后按顺序重跑同一前端检查全部通过。

## 未运行/未完成/风险

- 未读取 `states/ai.json`、Garmin 认证、私人 FIT/Goal/报告；未启动真实同步、真实 AI 或正式定时器。
- B1～B7 业务行为未实现也未声明完成。
- D31-03A、D31-03B、D31-02A 仍显式未配置，等待用户后续决定。
- 本轮为 Developer 自查，仍需全新 Validator 独立复验和主Agent验收。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "Only B0 repair scope was changed: source/** product base/contracts/tests and precise .gitignore additions; no PLAN.md/MEMORY.md/exec-plans/subagent template edits were made by this worker, and B1-B7 are explicitly not claimed complete."
    },
    {
      "id": "criterion-2",
      "status": "satisfied",
      "evidence": "Report lists changed files, tests, exact validation commands/results, residual risks, and no-staged-files evidence for independent review."
    }
  ],
  "changedFiles": [
    ".gitignore",
    "source/README.md",
    "source/pyproject.toml",
    "source/frontend/eslint.config.js",
    "source/frontend/index.html",
    "source/frontend/package-lock.json",
    "source/frontend/package.json",
    "source/frontend/src/App.tsx",
    "source/frontend/src/contracts.ts",
    "source/frontend/src/main.tsx",
    "source/frontend/src/styles.css",
    "source/frontend/src/vite-env.d.ts",
    "source/frontend/tests/app-contract.test.tsx",
    "source/frontend/tsconfig.json",
    "source/frontend/vite.config.ts",
    "source/skills/_shared/scripts/contracts.py",
    "source/skills/local-web/scripts/server.py",
    "source/tests/__init__.py",
    "source/tests/contracts/__init__.py",
    "source/tests/contracts/test_b0_contracts.py",
    "source/tools/README.md",
    "source/tools/check_b0_static.py",
    "source/trainlab/__init__.py",
    "source/trainlab/contracts/__init__.py",
    "source/trainlab/contracts/config.py",
    "source/trainlab/contracts/errors.py",
    "source/trainlab/contracts/interfaces.py",
    "source/trainlab/contracts/paths.py",
    "source/trainlab/contracts/schema.py",
    "source/trainlab/contracts/session.py",
    "source/trainlab/contracts/time.py",
    "source/trainlab/contracts/web.py",
    "source/trainlab/py.typed"
  ],
  "testsAddedOrUpdated": [
    "source/tests/contracts/test_b0_contracts.py",
    "source/frontend/tests/app-contract.test.tsx"
  ],
  "commandsRun": [
    {
      "command": "git status --short --branch",
      "result": "passed",
      "summary": "Confirmed branch work/adhoc-0031-local-web-system and pre-existing unstaged coordination/source state."
    },
    {
      "command": "cd source/frontend && npm install",
      "result": "passed",
      "summary": "Installed frontend dependencies and created package-lock; 0 vulnerabilities."
    },
    {
      "command": "cd source/frontend && npm ci",
      "result": "passed",
      "summary": "Lockfile reinstall passed; npm warned about pending fsevents install-script approval but did not fail."
    },
    {
      "command": "cd source/frontend && npm run lint && npm run typecheck && npm test && npm run build",
      "result": "passed",
      "summary": "ESLint, tsc, Vitest (3 passed), and Vite build all passed; build output directory was ../skills/local-web/web."
    },
    {
      "command": "python3.12 -m venv /tmp/trainlab-b0-fix-venv && uv pip install --python /tmp/trainlab-b0-fix-venv/bin/python -r source/pyproject.toml --extra dev",
      "result": "passed",
      "summary": "Declared Python runtime/dev dependencies installed into an isolated venv."
    },
    {
      "command": "cd source && /tmp/trainlab-b0-fix-venv/bin/python -m pytest tests -vv -p no:cacheprovider",
      "result": "passed",
      "summary": "17 passed, 2 third-party deprecation warnings."
    },
    {
      "command": "cd source && /tmp/trainlab-b0-fix-venv/bin/python -m ruff check --no-cache .",
      "result": "passed",
      "summary": "All checks passed."
    },
    {
      "command": "cd source && /tmp/trainlab-b0-fix-venv/bin/python -m mypy trainlab skills tools tests",
      "result": "passed",
      "summary": "Success: no issues found in 16 source files."
    },
    {
      "command": "/tmp/trainlab-b0-fix-venv/bin/python -m compileall -q source",
      "result": "passed",
      "summary": "Compileall exited 0."
    },
    {
      "command": "PYTHONPATH=source /tmp/trainlab-b0-fix-venv/bin/python source/tools/check_b0_static.py",
      "result": "passed",
      "summary": "B0 static contract check passed."
    },
    {
      "command": "git diff --check",
      "result": "passed",
      "summary": "No whitespace errors."
    },
    {
      "command": "git diff --cached --quiet && echo no-staged-files",
      "result": "passed",
      "summary": "No staged files."
    }
  ],
  "validationOutput": [
    "Python pytest: 17 passed, 2 warnings.",
    "Frontend Vitest: 1 test file passed, 3 tests passed.",
    "Ruff, mypy, compileall, B0 static contract check, frontend lint/type/build, and git diff --check passed."
  ],
  "residualRisks": [
    "B1-B7 business implementation and real external sync/AI checks are not part of this repair and remain unvalidated.",
    "D31-03A, D31-03B, and D31-02A remain explicit unconfigured policy decisions.",
    "Developer self-check only; independent Validator review is still required."
  ],
  "noStagedFiles": true,
  "diffSummary": "Replaced B0 placeholders with a real React/Vite frontend base, fixed Python dependency declarations, hardened SQLite/time/static-root contracts, added public DTO/tool/error/capacity policy contracts, and expanded B0 regression tests/docs.",
  "reviewFindings": [
    "no blockers"
  ],
  "manualNotes": "Pre-existing PLAN.md/MEMORY.md/exec-plans changes remain in the working tree but were not modified by this worker. A transient failed parallel npm check occurred while npm ci was rebuilding node_modules; the same frontend checks passed when rerun sequentially."
}
```
