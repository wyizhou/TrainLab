# ADHOC-0031 B1 第二轮修复复验（恢复验证环境）

## 结论

**通过**。适用范围：仅针对固定受审版本 `9db8bb1dda5922e85fe42581e27d2428dbc9f195`、快照 `exec-plans/evidence/ADHOC-0031/b1-fix-r2-review-snapshot.json` 中 56 个受审文件，对 U31-05、U31-06、ADHOC-0024 AC-01..04、V31-B1-001/002/003 及关联正常回归进行只读复验。未验证真实 Garmin/AI/网络业务调用，未推进 B2。

证据目录：`/tmp/trainlab-b1-fix-r2-validator-20260917215409`

## 受审版本、未提交改动与冻结核对

- 分支：`work/adhoc-0031-local-web-system`。
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`，与快照一致。
- 快照核对：56/56 文件路径、大小、mode、sha256 均一致；按 `json.dumps(items, sort_keys=True, separators=(',', ':'))` 计算的 `product_aggregate_sha256` 为 `5cb22a1f1950c1e73c0624c2ac2981f090c246738dc53f62eb13f9a5996149d8`，与快照一致。
- 当前工作区仍有既有计划/证据/产品未提交内容；本次未修改受审内容，未暂存文件。
- 关键证据：`/tmp/trainlab-b1-fix-r2-validator-20260917215409/snapshot-verify.log`、`git-status-final.log`。

## 环境恢复证据

| 项目 | 命令 | 结果 | 耗时 | 证据 |
| --- | --- | --- | --- | --- |
| Python/uv 版本 | `python3 -V`; `uv --version` | 退出 0 | - | `python-version.log`, `uv-version.log` |
| Python 依赖安装 | `UV_PROJECT_ENVIRONMENT=/tmp/.../venv uv sync --project source --python 3.12 --locked --extra dev --no-editable` | 退出 0 | 1s | `uv-sync.log`, `uv-sync-summary.log` |
| 前端依赖安装 | `npm ci`（隔离副本 `source/frontend`） | 退出 0 | 1s | `npm-ci.log`, `npm-ci-summary.log` |

环境已从上轮 E31-B1-001 的 200 秒外层中断恢复；本轮安装有明确退出码 0，随后动态 FIT/SQLite 项已实际运行。

## 场景表

| 要求/问题 | 类型 | 步骤与输入 | 预期 | 实际/退出结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| 冻结核对 / U31-06 | 边界 | 核分支、HEAD、56 文件 sha/size/mode、聚合 SHA | 全部一致后才继续 | 通过，0 个文件错误，聚合 SHA 匹配 | `snapshot-verify.log` |
| 环境恢复 / E31-B1-001 | 正常 | 按锁文件在 `/tmp` 隔离环境运行 `uv sync --locked --extra dev --no-editable` | 安装退出 0，有日志 | 退出 0，1s，安装 `trainlab-source==0.1.0` 和 FIT SDK 等依赖 | `uv-sync.log` |
| 全量 Python 回归 / U31-05/06 | 正常/错误/边界 | `python -m pytest tests -q -p no:cacheprovider` | 全部通过 | 157 passed，2 warnings，退出 0 | `pytest.log` |
| Ruff | 静态 | `python -m ruff check --no-cache .` | 退出 0 | All checks passed，退出 0 | `ruff.log` |
| mypy | 静态 | `python -m mypy -p trainlab -p tests --no-incremental` | 退出 0 | Success，34 source files，退出 0 | `mypy.log` |
| compileall | 静态 | `python -m compileall -q skills schemas tests` | 退出 0 | 退出 0 | `compile.log` |
| 架构门 / V31-B1-002 | 静态/边界 | `python -m trainlab.check_architecture` | 不放行违规目录、sys.path 写入、tools shell 等 | `architecture and public Schema checks passed`，退出 0 | `architecture.log` |
| 前端公共合同抽查 | 关联回归 | `npm run lint/typecheck/test/build` 于隔离副本 | 不破坏 B1 相关公共合同/构建 | lint/typecheck/test/build 均退出 0；Vitest 1 文件 3 测试通过 | `frontend-*.log` |
| FIT/SQLite 独立探针：正常入库 | 正常 | 合成 FIT 导入，插入 `activties_report`、`weekly_report`、`config` | activities 12 列、records 4 列、报告表 3/3 列、config 3 列；重复时间采样不合并；默认 facts 不含 records | 通过；records 为 0..3，含两个相同 timestamp；facts keys 不含 `records` | `validator-probe.log` |
| V31-B1-001 | 错误 | 非法标准字段号 255、空 record 必需消息 | 拒绝，且不改变既有 DB/报告/config | 均抛 ValueError，库快照保持 | `validator-probe.log` |
| V31-B1-001 | 边界 | FIT 时间下界 `0x0fffffff`、开发者字段、HR 累计数组/组件 | 时间作为 relative raw 证据保留；开发者和 HR 累计数组完整 | `time_evidence.kind=relative`，raw 保留；数组含 `[10,11]` 和 `[12,13]` | `validator-probe.log` |
| 幂等/冲突/报告保护 | 正常/错误 | 同字节普通导入；有报告后维护性 reparse 改变 records | 普通导入不改库；有报告时事实变化 `REPARSE_CONFLICT` 且保留旧库 | 通过，库快照未变，冲突显式失败 | `validator-probe.log` |
| 路径边界 / 架构 | 错误/边界 | 传入实例根外 FIT；调用架构 API | 越界路径拒绝；架构门无违规 | `INVALID_ARGUMENT`；`violations=None` | `validator-probe.log` |
| 工作区检查 | 交付边界 | `git diff --check`; `git diff --cached --name-only` | 空白检查通过，无暂存 | `git diff --check` 退出 0；暂存列表为空 | `git-diff-check.log`, `git-status-final.log` |

## 问题表

| 稳定问题编号 | 对应要求 | 复现步骤 | 预期与实际 | 影响 | 证据 |
| --- | --- | --- | --- | --- | --- |
| E31-B1-001 | 验证环境恢复 | `uv sync --locked --extra dev --no-editable`，随后执行 Python/FIT/SQLite 动态检查 | 预期安装完成并可运行动态项；实际退出 0，动态项已运行 | 已恢复，不再阻塞本次结论 | `uv-sync.log`, `pytest.log`, `validator-probe.log` |
| V31-B1-001 | FIT 协议边界/解析完整性 | 全量 pytest + 独立探针覆盖非法字段、空消息、HR 累计数组、时间下界 | 预期拒绝非法并保留合法边界；实际通过 | 未发现阻塞 | `pytest.log`, `validator-probe.log` |
| V31-B1-002 | 目录迁移/架构门 | 架构门、compile、Ruff/mypy、路径越界探针 | 预期无违规且越界拒绝；实际通过 | 未发现阻塞 | `architecture.log`, `validator-probe.log` |
| V31-B1-003 | 时间、证据、消息身份内部一致性 | 全量 pytest + 独立探针覆盖事实闭包、时间证据、默认 123、报告保护 | 预期内部矛盾不可提交；实际通过已测场景 | 未发现阻塞 | `pytest.log`, `validator-probe.log` |

## 未验证事项、证据缺口、环境限制和停止原因

- 未进行真实 Garmin 下载、真实 AI Provider 请求、真实私人 states 数据读取；本轮要求允许合成隔离验证，且明确不得读取秘密/真实私人数据。
- 前端只做 B1 相关公共合同/构建抽查，不代表完整 Web/API 功能验收。
- 未发现需要停止的快照不一致、产品修改需求、秘密依赖或持续安装失败。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "按固定 56 文件快照只读复验；恢复隔离 Python/前端环境，运行静态门、157 项 pytest、前端抽查和独立 FIT/SQLite 探针，未修改受审内容。"
    },
    {
      "id": "criterion-2",
      "status": "satisfied",
      "evidence": "报告列明受审版本、冻结核对、安装退出码/耗时、场景表、问题表、命令和 /tmp 证据路径，可供独立复核。"
    }
  ],
  "changedFiles": [],
  "testsAddedOrUpdated": [
    "/tmp/trainlab-b1-fix-r2-validator-20260917215409/validator_probe.py"
  ],
  "commandsRun": [
    {
      "command": "git branch --show-current && git rev-parse HEAD; snapshot sha/size/mode/product aggregate verification",
      "result": "passed",
      "summary": "分支/HEAD 与快照一致；56 个文件全匹配；聚合 SHA 匹配。"
    },
    {
      "command": "UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b1-fix-r2-validator-20260917215409/venv uv sync --project source --python 3.12 --locked --extra dev --no-editable",
      "result": "passed",
      "summary": "退出 0，耗时 1s。"
    },
    {
      "command": "cd /tmp/trainlab-b1-fix-r2-validator-20260917215409/repo/source && /tmp/trainlab-b1-fix-r2-validator-20260917215409/venv/bin/python -m pytest tests -q -p no:cacheprovider",
      "result": "passed",
      "summary": "157 passed, 2 warnings。"
    },
    {
      "command": "python -m ruff check --no-cache .; python -m mypy -p trainlab -p tests --no-incremental; python -m compileall -q skills schemas tests; python -m trainlab.check_architecture",
      "result": "passed",
      "summary": "Ruff/mypy/compile/architecture 均退出 0。"
    },
    {
      "command": "cd /tmp/trainlab-b1-fix-r2-validator-20260917215409/repo/source/frontend && npm ci && npm run lint && npm run typecheck && npm test && npm run build",
      "result": "passed",
      "summary": "前端依赖安装、lint、typecheck、Vitest 3 项、build 均退出 0。"
    },
    {
      "command": "PYTHONPATH=. /tmp/trainlab-b1-fix-r2-validator-20260917215409/venv/bin/python /tmp/trainlab-b1-fix-r2-validator-20260917215409/validator_probe.py",
      "result": "passed",
      "summary": "8 个独立 FIT/SQLite 探针场景全部 ok。"
    },
    {
      "command": "git diff --check; git diff --cached --name-only",
      "result": "passed",
      "summary": "空白检查退出 0；暂存列表为空。"
    }
  ],
  "validationOutput": [
    "/tmp/trainlab-b1-fix-r2-validator-20260917215409/snapshot-verify.log",
    "/tmp/trainlab-b1-fix-r2-validator-20260917215409/uv-sync.log",
    "/tmp/trainlab-b1-fix-r2-validator-20260917215409/pytest.log",
    "/tmp/trainlab-b1-fix-r2-validator-20260917215409/architecture.log",
    "/tmp/trainlab-b1-fix-r2-validator-20260917215409/validator-probe.log",
    "/tmp/trainlab-b1-fix-r2-validator-20260917215409/frontend-test.log",
    "/tmp/trainlab-b1-fix-r2-validator-20260917215409/git-status-final.log"
  ],
  "residualRisks": [
    "未做真实 Garmin/AI/网络业务调用；前端仅按 B1 相关公共合同抽查。"
  ],
  "noStagedFiles": true,
  "diffSummary": "未修改项目受审内容；仅在 /tmp 创建隔离副本、虚拟环境、日志和临时验证脚本，并写出本复验报告。",
  "reviewFindings": [
    "no blockers"
  ],
  "manualNotes": "结论：通过。当前工作区仍存在任务开始前已有的未提交/未跟踪计划、证据和 source 内容；本次未暂存文件。"
}
```
