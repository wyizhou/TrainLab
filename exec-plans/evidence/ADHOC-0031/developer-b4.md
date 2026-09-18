# Developer B4 报告：ADHOC-0031 B4 / 0031-T3

## 修改摘要

实现了 Garmin 同步/认证适配、三小时调度和下载恢复的合成可测底座，未做真实 Garmin/网络/凭据调用。

- 新增 `trainlab.garmin_sync`：
  - `run_garmin_sync(instance_root, client, now_utc=...)`：通过宿主注入的 `GarminSyncClient` 协议执行同步。
  - `GarminActivity` / `GarminActivityPage` / `AuthRefreshResult` / `GarminSyncState` / `GarminSyncResult` 等稳定数据结构。
  - 首次同步窗口为最近七天；后续按三小时 `SYNC_INTERVAL` due 判断，可 `force` 强制。
  - 读取实例内 `states/verification/garmin.json`，刷新成功时原子更新；需要人工登录/MFA 时返回 `AUTH_REFRESH_REQUIRED`。
  - 分页列活动、远端 ID 去重、已同步跳过。
  - 下载 FIT 或单 FIT ZIP，按 `states/activities/YYYYMMDD-SHA256.fit` / `unknown-SHA256.fit` 原子写入；多 FIT/无 FIT ZIP 明确失败。
  - 下载后调用既有 FIT 导入入口；导入失败保留原件、不标记已同步。
  - 状态持久化到 `states/garmin-sync.json`，仅保存同步时间、远端活动 ID、activity_id、FIT 相对路径和 SHA，不保存认证秘密。
  - 单进程并发锁，忙碌时返回 `RUN_BUSY`。
- 新增 `PyGarminConnectAdapter` 薄适配器形状，包装由宿主传入的 pygarminconnect-like client；本轮未新增依赖、未真实调用。
- 更新 `trainlab.exports`、`source/README.md` 和包版本 `0.1.3` / `uv.lock`。
- 新增合成测试覆盖 B4 正常、错误和边界路径。

## 文件清单

- `source/skills/_shared/scripts/trainlab/garmin_sync.py`：新增同步/认证/命名/状态/调度实现。
- `source/skills/_shared/scripts/trainlab/exports.py`：导出 B4 同步接口。
- `source/skills/_shared/scripts/trainlab/__init__.py`：同步包版本。
- `source/tests/sync/__init__.py`：新增测试包。
- `source/tests/sync/test_garmin_sync.py`：新增 B4 合成测试。
- `source/README.md`：更新当前实现状态与同步合成底座说明。
- `source/pyproject.toml`：版本 `0.1.3`。
- `source/uv.lock`：同步锁文件版本。

## 实际版本与未提交改动

- 分支：`work/adhoc-0031-local-web-system`
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`
- 工作区开始时已有未提交计划/证据移动和 `source/` 产品实现；本次只修改允许范围内的 `source/**` 文件。
- 未修改 `PLAN.md`、`exec-plans/**`、`MEMORY.md`、私人 `states`、Git 配置或 Git 索引。
- 当前暂存文件数：0。

## 检查表

| 命令 | 预期 | 实际结果 | 退出码 / 证据 |
| --- | --- | --- | --- |
| `cd source && uv lock` | 同步锁文件 | `trainlab-source v0.1.2 -> v0.1.3` | 0 |
| `cd source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b4-developer-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable` | 仓库外隔离安装 | 安装 `trainlab-source==0.1.3` | 0；`/tmp/trainlab-b4-developer-logs/uv-sync-final.log` |
| `cd source && /tmp/trainlab-b4-developer-venv/bin/python -m pytest tests/sync/test_garmin_sync.py -q -p no:cacheprovider` | B4 新测试通过 | `6 passed` | 0；`/tmp/trainlab-b4-developer-logs/pytest-sync-final.log` |
| `cd source && /tmp/trainlab-b4-developer-venv/bin/python -m pytest tests -q -p no:cacheprovider` | 全量 Python 测试通过 | `177 passed, 2 warnings` | 0；`/tmp/trainlab-b4-developer-logs/pytest-all-final3.log` |
| `cd source && /tmp/trainlab-b4-developer-venv/bin/python -m ruff check --no-cache .` | 静态检查通过 | `All checks passed!` | 0；`/tmp/trainlab-b4-developer-logs/ruff-final.log` |
| `cd source && /tmp/trainlab-b4-developer-venv/bin/python -m mypy -p trainlab -p tests --no-incremental` | 类型检查通过 | `Success: no issues found in 44 source files` | 0；`/tmp/trainlab-b4-developer-logs/mypy-final.log` |
| `cd source && /tmp/trainlab-b4-developer-venv/bin/python -m compileall -q skills schemas tests` | 编译通过 | 无错误输出 | 0；`/tmp/trainlab-b4-developer-logs/compileall-final3.log` |
| `cd source && /tmp/trainlab-b4-developer-venv/bin/python -m trainlab.check_architecture` | 架构门通过 | `architecture and public Schema checks passed` | 0；`/tmp/trainlab-b4-developer-logs/architecture-final.log` |
| `git diff --check && git diff --cached --name-only` | 无空白错误且无暂存 | 通过，暂存列表为空 | 0；`/tmp/trainlab-b4-developer-logs/git-diff-check-final3.log`、`staged-final3.log` |

## 覆盖要点

- 首次最近七天窗口、三小时 due 判断、未到期跳过。
- 认证文件读取、刷新成功原子写回、人工登录/MFA 明确失败、缺认证文件明确失败。
- 分页、去重、已同步活动跳过。
- FIT 字节 SHA 命名、UTC 日期和 unknown 日期。
- ZIP 单 FIT 提取、多 FIT/无 FIT 错误。
- 下载原子写入、中断/导入失败后保留原件且不标记 synced。
- 状态持久化、并发忙碌 `RUN_BUSY`。
- 导入入口被调用，真实 FIT 合成样本入库。
- 实例相对路径保护；结果/状态不泄露认证 secret。

## 未运行 / 未解决事项

- 未运行前端检查；本次未改前端代码。
- 未做真实 Garmin、pygarminconnect、网络、登录/MFA、私人 `states/verification/garmin.json` 或私人活动数据调用。
- 未新增 `pygarminconnect` 依赖；真实适配器仅保留可包装宿主 client 的薄形状，需后续在获准真实联调时验证。
- B4 只完成同步合成底座，不代表 B5 AI/Context、B6 Web/API 或完整真实端到端已完成。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "在允许的 source 范围内实现 B4 同步合成底座；未修改 PLAN.md、exec-plans、MEMORY.md、私人 states 或 Git 索引；未做真实外部调用。"
    },
    {
      "id": "criterion-2",
      "status": "satisfied",
      "evidence": "报告列出修改文件、测试新增、命令结果、日志路径、残余风险和无暂存状态，可供独立验收复核。"
    }
  ],
  "changedFiles": [
    "source/skills/_shared/scripts/trainlab/garmin_sync.py",
    "source/skills/_shared/scripts/trainlab/exports.py",
    "source/skills/_shared/scripts/trainlab/__init__.py",
    "source/tests/sync/__init__.py",
    "source/tests/sync/test_garmin_sync.py",
    "source/README.md",
    "source/pyproject.toml",
    "source/uv.lock"
  ],
  "testsAddedOrUpdated": [
    "source/tests/sync/__init__.py",
    "source/tests/sync/test_garmin_sync.py"
  ],
  "commandsRun": [
    {
      "command": "cd source && uv lock",
      "result": "passed",
      "summary": "同步 trainlab-source 版本到 0.1.3。"
    },
    {
      "command": "cd source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b4-developer-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable",
      "result": "passed",
      "summary": "按锁文件创建仓库外隔离环境并安装 trainlab-source==0.1.3。"
    },
    {
      "command": "cd source && /tmp/trainlab-b4-developer-venv/bin/python -m pytest tests/sync/test_garmin_sync.py -q -p no:cacheprovider",
      "result": "passed",
      "summary": "6 passed。"
    },
    {
      "command": "cd source && /tmp/trainlab-b4-developer-venv/bin/python -m pytest tests -q -p no:cacheprovider",
      "result": "passed",
      "summary": "177 passed, 2 warnings。"
    },
    {
      "command": "cd source && /tmp/trainlab-b4-developer-venv/bin/python -m ruff check --no-cache .",
      "result": "passed",
      "summary": "All checks passed。"
    },
    {
      "command": "cd source && /tmp/trainlab-b4-developer-venv/bin/python -m mypy -p trainlab -p tests --no-incremental",
      "result": "passed",
      "summary": "Success: no issues found in 44 source files。"
    },
    {
      "command": "cd source && /tmp/trainlab-b4-developer-venv/bin/python -m compileall -q skills schemas tests && /tmp/trainlab-b4-developer-venv/bin/python -m trainlab.check_architecture",
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
    "/tmp/trainlab-b4-developer-logs/uv-sync-final.log",
    "/tmp/trainlab-b4-developer-logs/pytest-sync-final.log",
    "/tmp/trainlab-b4-developer-logs/pytest-all-final3.log",
    "/tmp/trainlab-b4-developer-logs/ruff-final.log",
    "/tmp/trainlab-b4-developer-logs/mypy-final.log",
    "/tmp/trainlab-b4-developer-logs/compileall-final3.log",
    "/tmp/trainlab-b4-developer-logs/architecture-final.log",
    "/tmp/trainlab-b4-developer-logs/git-diff-check-final3.log",
    "/tmp/trainlab-b4-developer-logs/staged-final3.log"
  ],
  "residualRisks": [
    "未做真实 Garmin/pygarminconnect/网络/私人 states 调用。",
    "真实适配器只保留薄包装形状，仍需后续受控真实联调验证。",
    "B5 AI/Context、B6 Web/API 和完整真实端到端仍未实施。"
  ],
  "noStagedFiles": true,
  "diffSummary": "新增 Garmin 同步合成底座、测试与导出，更新 README 和 source 包版本/锁文件。",
  "reviewFindings": [
    "no blockers from developer self-check; independent Validator still required"
  ],
  "manualNotes": "工作区存在任务开始前已有的未提交计划/证据/source 实现；本次只改 source 允许范围内文件，未暂存。"
}
```
