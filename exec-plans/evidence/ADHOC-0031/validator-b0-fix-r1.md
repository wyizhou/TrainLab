# ADHOC-0031 B0 fix-r1 修复后复验报告

## 结论

**通过（适用范围：仅 ADHOC-0031 B0 本轮 V31-B0-001～006 修复复验及关联正常回归）。**

本次未代替主 Agent 最终验收；B1～B7、真实同步、真实 AI、正式调度、业务 Web 页面仍未纳入通过范围。

## 受审版本与冻结核对

- 分支：`work/adhoc-0031-local-web-system`
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`
- 受审清单：`exec-plans/evidence/ADHOC-0031/b0-fix-r1-review-snapshot.json`
- 开始/结束核对：33 个受审文件集合、SHA、模式、大小均匹配快照；`product_aggregate_sha256 = c80313240e8eb91ea20e152f8bf63a57f26788c92a37fcd9f11b1576d015d37d`。
- Git 暂存区：结束时为空；`git diff --check` 退出 0。
- 证据目录：`/tmp/adhoc0031-b0-fix-r1-validator-20260916T083618Z`

## 场景表

| 要求 | 类型 | 步骤/输入 | 预期 | 实际/退出码 | 证据 |
|---|---|---|---|---|---|
| 冻结/版本 | 边界 | 开始、结束读取固定清单并计算聚合 SHA；检查分支/HEAD/status/staged/diff-check | 受审集合不变、无暂存、diff-check 通过 | 通过；聚合 SHA 匹配；`git diff --check` 0 | `start-end-freeze-summary.json`, `start-git.txt`, `end-git.txt` |
| V31-B0-002 | 正常 | Python 3.12 venv；`uv pip install -r pyproject.toml --extra dev` | 仅声明依赖可安装 | 通过；退出 0 | `py312-uv-install-dev.log` |
| V31-B0-002/006 | 正常 | `python -m pytest tests -vv` | 项目测试通过 | 17 passed；退出 0 | `py312-pytest.log` |
| V31-B0-002 | 正常 | Ruff、mypy、compileall、B0 静态/Schema 检查 | 全部通过 | 全部退出 0；静态检查输出 `B0 static contract check passed` | `py312-ruff.log`, `py312-mypy.log`, `py312-compileall.log`, `py312-static-check.log` |
| V31-B0-001 | 正常 | `npm ci`, `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` | 前端依赖、lint/type/test/build 真实可运行，产物到后端 web | 全部退出 0；Vitest 3 passed；Vite 产物在 `source/skills/local-web/web` | `npm-ci.log`, `frontend-*.log`, `frontend-web-files.log` |
| V31-B0-001 | 人工核对 | 检查 `package.json`、`src/*.tsx`、测试 | React 最小工程，不是纯字符串壳 | 发现 React/ReactDOM/Vite/Vitest/ESLint/TS 依赖；`createRoot`、`App.tsx`、React 渲染测试存在 | grep 结果、`source/frontend/*` |
| V31-B0-003 | 正常/错误/边界 | 独立 pytest：建 SQLite DDL，插入正常活动/records/报告/config；NULL、重复键、孤儿行、删除父行、长全文 | 主外键/NOT NULL/重复/保护/全文均符合 | 通过；独立测试 4 passed 中覆盖 | `independent_r1_test.py`, `independent-r1-pytest-root.log` |
| V31-B0-004 | 正常/错误/边界 | TestClient 检查 `/api/health`、`/`、编码遍历；把静态根替换为指向合成 states 的软链接 | 正常静态可服务；越界/软链接私人根拒绝 | 通过；软链接根 `validate_static_mount` 和 `create_app` 均抛错；无合成秘密返回 | `independent-r1-pytest-root.log` |
| V31-B0-005 | 正常/错误/边界 | naive datetime、带 +08:00 偏移、TZ=Asia/Shanghai 后重复转换、内存历史 append | naive 拒绝；带偏移稳定转 UTC；不随系统 TZ 变化 | 通过；独立测试覆盖 | `independent-r1-pytest-root.log` |
| V31-B0-006 | 人工/可执行 | 校验 JSON schema 示例、工具参数、错误映射、容量策略、周窗口、未决策略显式未配置 | DTO/工具/错误/容量/权限/未决策略足够供 B1 消费；D31-03A/B、D31-02A 无默认假策略 | 通过；`UNCONFIGURED_POLICIES` 覆盖全部 PendingDecision；错误壳 health/404 正常 | `independent_r1_test.py`, `independent-r1-pytest-root.log`, `source/trainlab/contracts/interfaces.py` |

## 问题表

| 编号 | 复验结论 | 证据 |
|---|---|---|
| V31-B0-001 | 通过 | 前端 npm install/lint/type/test/build 全 0；React 源码与测试存在；构建输出到 `source/skills/local-web/web`。 |
| V31-B0-002 | 通过 | Python 3.12 声明依赖安装、pytest/Ruff/mypy/compileall/静态检查全 0。 |
| V31-B0-003 | 通过 | 独立 SQLite 正常、NULL、重复键、孤儿行、删除保护、全文测试通过。 |
| V31-B0-004 | 通过 | 实际 app/TestClient 正常静态、health、404 错误壳、编码遍历、静态根软链接到合成 states 拒绝均通过。 |
| V31-B0-005 | 通过 | naive 时间拒绝、偏移转 UTC、不同 TZ 稳定、内存历史只内存均通过。 |
| V31-B0-006 | 通过 | 公共 schema/DTO、工具、错误映射、容量、权限、周窗口、未决策略检查通过。 |
| V31-B0-R1-NEW-* | 无新增 blocker | 未发现需登记的新阻塞问题。 |

## 未验证事项与残余风险

- B1～B7 功能行为未验证：真实 FIT 解析、业务仓储、真实同步/AI、正式调度、完整 Web/API 页面不在 B0 复验范围。
- 额外探针 `python -m pip install '.[dev]'` 失败：setuptools 报 flat-layout 中多个顶层包 `skills/frontend/trainlab`。本次复验按任务要求使用 `pyproject.toml` 声明依赖安装并在隔离副本运行入口，未将该额外包装探针列为 B0 blocker；如后续要求可发布/可 editable install，应另行纳入合同。
- FastAPI/TestClient 警告来自依赖弃用提示，未导致检查失败。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "仅做只读复验并写入指定报告；未修改受审 source/.gitignore/计划文件；V31-B0-001～006 均按给定范围复验通过。"
    },
    {
      "id": "criterion-2",
      "status": "satisfied",
      "evidence": "报告列出受审版本、冻结核对、命令退出码、场景表、问题表和 /tmp 证据路径，可独立复核。"
    }
  ],
  "changedFiles": [
    "/Users/lucas/.pi/agent/sessions/--Volumes-DiskOther-Code-TrainLab--/subagent-artifacts/outputs/1c349135-bf22-42b9-96be-ed1c6ad64d41/adhoc0031/b0-fix-r1-validator.md"
  ],
  "testsAddedOrUpdated": [
    "/tmp/adhoc0031-b0-fix-r1-validator-20260916T083618Z/independent_r1_test.py"
  ],
  "commandsRun": [
    {
      "command": "git status --short --branch && git diff --check",
      "result": "passed",
      "summary": "开始和结束均核对；diff-check 退出 0；暂存区为空。"
    },
    {
      "command": "freeze snapshot SHA/mode/size check against b0-fix-r1-review-snapshot.json",
      "result": "passed",
      "summary": "33 个受审文件匹配；aggregate=c80313240e8eb91ea20e152f8bf63a57f26788c92a37fcd9f11b1576d015d37d。"
    },
    {
      "command": "uv pip install --python py312-declared-venv/bin/python -r pyproject.toml --extra dev",
      "result": "passed",
      "summary": "声明依赖安装退出 0。"
    },
    {
      "command": "python -m pytest tests -vv -p no:cacheprovider",
      "result": "passed",
      "summary": "17 passed, 2 warnings。"
    },
    {
      "command": "python -m ruff check --no-cache . && python -m mypy trainlab skills tools tests && python -m compileall -q . && python tools/check_b0_static.py",
      "result": "passed",
      "summary": "Ruff/mypy/compileall/static-check 均退出 0。"
    },
    {
      "command": "npm ci && npm run lint && npm run typecheck && npm test && npm run build",
      "result": "passed",
      "summary": "前端全部退出 0；Vitest 3 passed；Vite 构建输出到 local-web/web。"
    },
    {
      "command": "python -m pytest /tmp/.../independent_r1_test.py -vv",
      "result": "passed",
      "summary": "独立复验 4 passed，覆盖 SQLite、静态根、时间/历史、T2 合同。"
    },
    {
      "command": "python -m pip install '.[dev]'",
      "result": "failed",
      "summary": "额外包装探针失败：setuptools flat-layout 多顶层包；未列为本轮 B0 blocker。"
    }
  ],
  "validationOutput": [
    "证据目录：/tmp/adhoc0031-b0-fix-r1-validator-20260916T083618Z",
    "py312-pytest.log: 17 passed, 2 warnings",
    "independent-r1-pytest-root.log: 4 passed, 2 warnings",
    "frontend-test.log: 1 file / 3 tests passed"
  ],
  "residualRisks": [
    "B1～B7 和真实外部行为未纳入 B0 通过范围。",
    "额外 pip install .[dev] 包装探针失败，如需可安装包应另行明确。"
  ],
  "noStagedFiles": true,
  "diffSummary": "仓库受审内容未修改；仅写入指定外部复验报告和 /tmp 证据。",
  "reviewFindings": [
    "no blockers"
  ],
  "manualNotes": "结论为 B0 fix-r1 复验通过，不替代主 Agent 最终验收。"
}
``` 
