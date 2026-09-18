# Validator 报告：ADHOC-0031 B4 修复复验 V31-B4-001

## 结论

通过。适用范围：固定 B4 修复受审快照（65 文件，聚合 SHA `c8a51f548de7deb823b2e317f9908137695422283af63b42befce6e66d773818`）的合成 Garmin 同步/认证/下载恢复底座；未做真实 Garmin、pygarminconnect、网络、登录/MFA、私人凭据或真实活动调用。

V31-B4-001 已复验通过：已有 `last_success_at_utc=2031-02-07T12:00:00Z` 时，本轮 force 两个新活动，第一项导入成功、第二项导入失败后，状态仍保留上一轮 `last_success_at_utc`，失败远端未标记 synced，失败 FIT 原件保留，状态/结果未泄露认证 secret。

## 受审版本、未提交改动和冻结核对

- 分支：`work/adhoc-0031-local-web-system`。
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`。
- 工作区存在计划/证据协调记录和 `source/` 未提交内容；本次未修改受审内容、未暂存。
- 快照核对：逐文件核对 65 个 `path/size/mode/sha256` 通过；按快照 items 的排序紧凑 JSON 聚合 SHA 为 `c8a51f548de7deb823b2e317f9908137695422283af63b42befce6e66d773818`，与快照一致。
- 验证隔离目录：`/tmp/trainlab-b4-fix-validator-v31-1789658316/source`。
- 证据目录：`/tmp/trainlab-b4-fix-validator-v31-1789658316/logs`；临时探针：`/tmp/trainlab-b4-fix-validator-v31-1789658316/probes/test_b4_contract_independent.py`。

## 场景表

| 对应要求 | 类型 | 步骤与输入 | 预期 | 实际 / 退出结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| 快照冻结 | 正常 | 核分支/HEAD/65 文件 SHA/大小/权限/聚合 SHA | 全部一致 | 通过，退出 0 | `snapshot-verify.log` |
| 隔离依赖 | 正常 | 复制 `source/` 到 `/tmp`，`uv sync --locked --extra dev --no-editable` | 隔离安装成功 | 通过，安装 `trainlab-source==0.1.4` | `uv-sync.log` |
| Python 全量回归 | 回归 | `pytest tests -q -p no:cacheprovider` | 全量通过 | `178 passed, 2 warnings`，退出 0 | `pytest-all.log` |
| Ruff | 静态 | `python -m ruff check --no-cache .` | 通过 | `All checks passed!`，退出 0 | `ruff.log` |
| Mypy | 类型 | 使用只读源码等价包布局作为 `MYPYPATH`，运行 `python -m mypy -p trainlab -p tests --no-incremental` | 通过 | `Success: no issues found in 44 source files`，退出 0 | `mypy-typepath.log` |
| 编译/架构门 | 静态/架构 | `compileall -q skills schemas tests`、`python -m trainlab.check_architecture` | 通过 | 均退出 0；架构门输出 `architecture and public Schema checks passed` | `compileall.log`、`architecture.log` |
| 前端关联回归 | 回归 | `npm ci`、lint、typecheck、test、build | 未改前端仍可检查/构建 | 全部退出 0；Vitest 1 文件/3 测试通过；Vite build 通过 | `npm-ci.log`、`frontend-*.log` |
| V31-B4-001 部分失败恢复 | 错误/边界 | 初始已有上一轮 `last_success`；本轮 force 两个新活动；第一项导入成功，第二项导入器抛错 | 返回失败；上一轮 `last_success_at_utc` 保留；失败 remote 不 synced；失败 FIT 原件保留；无 tmp；不泄密 | 通过 | `pytest-probes-rerun.log` |
| 首次七天、分页/去重、认证刷新、FIT/ZIP 命名、导入 | 正常/边界 | 合成两页活动、重复 remote_id、刷新 token、FIT bytes + 单 FIT ZIP | 首次最近七天；分页去重；刷新写回；UTC 日期 + 实际 FIT SHA 命名；导入记录；状态/结果不含旧 secret | 通过 | `pytest-probes-rerun.log` |
| 三小时 due/force、已同步跳过、manual_required、缺/坏认证、路径安全、ZIP 错误 | 正常/错误/安全 | 构造未到 3 小时、force、已 synced、manual_required、缺认证、坏 JSON、`../` 路径、无 FIT/多 FIT ZIP | 未到期不列表；force 可运行；已同步不下载；manual_required/缺坏认证显式失败；越界拒绝；ZIP 错误显式失败 | 通过 | `pytest-probes-rerun.log` |
| unknown 日期命名和安全边界 | 边界/安全 | `start_time_utc=None`；全程 fake client/合成 tmp 实例 | `unknown-SHA.fit`；不触碰真实凭据/网络/MFA | 通过 | `pytest-probes-rerun.log` + 人工核对探针设计 |

## 问题表

| 稳定问题编号 | 对应要求 | 结论 | 证据 |
| --- | --- | --- | --- |
| V31-B4-001 | 已有上次成功状态时，部分成功后失败不得把 `last_success_at_utc` 重置为空 | 已修复，未复现失败 | `pytest-probes-rerun.log`：4 个独立探针全部通过；既有 `pytest tests` 178 项通过 |

## 未验证事项、证据缺口、环境限制和停止原因

- 未做真实 Garmin/pygarminconnect/网络/登录/MFA/私人凭据/真实活动调用；这是本任务边界。
- 未验证真实服务端兼容性；当前仅验证合成客户端、薄适配入口及状态/文件恢复语义。
- Mypy 首次直接对 PEP 660 editable finder 环境调用时无法定位包；随后在 `/tmp` 构造等价只读包布局并对同一源码运行通过。该调整不修改受审内容。
- 停止原因：复验范围内检查完成，无阻塞问题；未推进 B5～B7。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "只做 ADHOC-0031 B4 修复复验和关联正常回归；未修改受审产品内容，未推进 B5-B7，未真实调用 Garmin/网络/凭据。"
    },
    {
      "id": "criterion-2",
      "status": "satisfied",
      "evidence": "报告列明受审版本、快照核对、场景表、命令结果、日志路径、未验证事项、无暂存状态和 V31-B4-001 复验结论。"
    }
  ],
  "changedFiles": [
    "/Users/lucas/.pi/agent/sessions/--Volumes-DiskOther-Code-TrainLab--/subagent-artifacts/outputs/37235d1f-0779-48a4-b847-7e01514ca0b1/adhoc0031/validator-b4-fix-v31-b4-001.md"
  ],
  "testsAddedOrUpdated": [
    "/tmp/trainlab-b4-fix-validator-v31-1789658316/probes/test_b4_contract_independent.py"
  ],
  "commandsRun": [
    {
      "command": "git status --short && git branch --show-current && git rev-parse HEAD",
      "result": "passed",
      "summary": "分支 work/adhoc-0031-local-web-system，HEAD 9db8bb1dda5922e85fe42581e27d2428dbc9f195；存在既有未提交协调/产品受审内容。"
    },
    {
      "command": "python3 snapshot verification script",
      "result": "passed",
      "summary": "65 文件 path/size/mode/sha256 与聚合 SHA c8a51f548de7deb823b2e317f9908137695422283af63b42befce6e66d773818 核对通过。"
    },
    {
      "command": "cd /tmp/trainlab-b4-fix-validator-v31-1789658316/source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b4-fix-validator-v31-1789658316/venv uv sync --project . --python 3.12 --locked --extra dev --no-editable",
      "result": "passed",
      "summary": "隔离依赖安装成功，安装 trainlab-source==0.1.4。"
    },
    {
      "command": "python -m pytest tests -q -p no:cacheprovider",
      "result": "passed",
      "summary": "178 passed, 2 warnings。"
    },
    {
      "command": "python -m ruff check --no-cache .",
      "result": "passed",
      "summary": "All checks passed。"
    },
    {
      "command": "MYPYPATH=/tmp/trainlab-b4-fix-validator-v31-1789658316/typepath python -m mypy -p trainlab -p tests --no-incremental",
      "result": "passed",
      "summary": "Success: no issues found in 44 source files。"
    },
    {
      "command": "python -m compileall -q skills schemas tests && python -m trainlab.check_architecture",
      "result": "passed",
      "summary": "compileall 无错误；架构门通过。"
    },
    {
      "command": "cd frontend && npm ci && npm run lint && npm run typecheck && npm test && npm run build",
      "result": "passed",
      "summary": "前端依赖、lint、typecheck、Vitest 3 项、生产构建全部通过。"
    },
    {
      "command": "python -m pytest /tmp/trainlab-b4-fix-validator-v31-1789658316/probes -q -p no:cacheprovider",
      "result": "passed",
      "summary": "4 个独立 B4 合同探针全部通过，覆盖 V31-B4-001 及关联正常/错误/边界回归。"
    },
    {
      "command": "git diff --cached --name-only",
      "result": "passed",
      "summary": "暂存列表为空。"
    }
  ],
  "validationOutput": [
    "/tmp/trainlab-b4-fix-validator-v31-1789658316/logs/snapshot-verify.log",
    "/tmp/trainlab-b4-fix-validator-v31-1789658316/logs/uv-sync.log",
    "/tmp/trainlab-b4-fix-validator-v31-1789658316/logs/pytest-all.log",
    "/tmp/trainlab-b4-fix-validator-v31-1789658316/logs/ruff.log",
    "/tmp/trainlab-b4-fix-validator-v31-1789658316/logs/mypy-typepath.log",
    "/tmp/trainlab-b4-fix-validator-v31-1789658316/logs/compileall.log",
    "/tmp/trainlab-b4-fix-validator-v31-1789658316/logs/architecture.log",
    "/tmp/trainlab-b4-fix-validator-v31-1789658316/logs/npm-ci.log",
    "/tmp/trainlab-b4-fix-validator-v31-1789658316/logs/frontend-lint.log",
    "/tmp/trainlab-b4-fix-validator-v31-1789658316/logs/frontend-typecheck.log",
    "/tmp/trainlab-b4-fix-validator-v31-1789658316/logs/frontend-test.log",
    "/tmp/trainlab-b4-fix-validator-v31-1789658316/logs/frontend-build.log",
    "/tmp/trainlab-b4-fix-validator-v31-1789658316/logs/pytest-probes-rerun.log"
  ],
  "residualRisks": [
    "未做真实 Garmin/pygarminconnect/网络/登录/MFA/私人凭据/真实活动调用。",
    "未验证真实服务端兼容性；当前结论限于合成底座和薄适配入口。",
    "Mypy 使用 /tmp 等价只读包布局解决 editable finder 定位问题；不改变受审源码。"
  ],
  "noStagedFiles": true,
  "diffSummary": "未修改受审内容；仅在 /tmp 写隔离副本、日志、临时探针，并写出本验证报告。",
  "reviewFindings": [
    "no blockers"
  ],
  "manualNotes": "结论：通过。V31-B4-001 未复现，关联 B4 合成回归、静态门、全量 pytest、前端抽查均通过。"
}
```
