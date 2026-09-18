# Validator 报告：ADHOC-0031 B4 / 0031-T3

## 结论

失败。适用范围：固定 B4 受审快照（65 文件，聚合 SHA `162c7eb2aa76a591538d2b8d0e1813d237baefe79450b083e2b1eabaa2302c58`）的合成 Garmin 同步/认证/下载恢复底座；未做真实 Garmin、pygarminconnect、网络、登录/MFA、私人凭据或真实 FIT 调用。

主要失败：部分同步已有上次成功状态时，后续导入失败会把 `last_success_at_utc` 写成 `null`，违反“部分失败不得错误重置 last_success 导致未来窗口无限回退”。

## 受审版本、未提交改动和冻结核对

- 分支：`work/adhoc-0031-local-web-system`。
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`。
- 工作区存在计划/证据协调记录和 `source/` 未提交内容；本次验证未修改受审内容、未暂存。
- 快照核对：逐文件核对 65 个 `path/size/mode/sha256` 通过；按快照 items 的排序 JSON 聚合核对为 `162c7eb2aa76a591538d2b8d0e1813d237baefe79450b083e2b1eabaa2302c58`，通过。
- 验证隔离目录：`/tmp/trainlab-b4-validator-run/source`。
- 证据目录：`/tmp/trainlab-b4-validator-logs`；临时探针：`/tmp/trainlab-b4-validator-probes/test_b4_contract.py`。

## 场景表

| 对应要求 | 类型 | 步骤与输入 | 预期 | 实际 / 退出结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| 快照冻结 | 正常 | 读取 `b4-developer-review-snapshot.json`，核分支/HEAD/65 文件 SHA/大小/权限/聚合 SHA | 全部一致 | 通过，退出 0 | `snapshot-verify.log` |
| 隔离依赖 | 正常 | 复制 `source/` 到 `/tmp`，`uv sync --locked --extra dev --no-editable` | 仓库外环境安装成功 | 通过，退出 0 | `uv-sync.log` |
| Python 回归 | 回归 | `pytest tests -q -p no:cacheprovider` | 全量通过 | 177 passed, 2 warnings，退出 0 | `pytest-all.log` |
| 静态/类型/编译/架构 | 回归 | `ruff`、`mypy`、`compileall`、`trainlab.check_architecture` | 全部通过 | 全部退出 0；初次 ruff 因隔离复制带入未受审 `source/build` 失败，删除该构建产物后对受审文件复跑通过 | `ruff.log`、`mypy.log`、`compileall.log`、`architecture.log` |
| 前端抽查 | 回归 | 隔离副本 `npm ci`、lint、typecheck、test、build | 未改前端仍可构建/测试 | 全部退出 0；1 test file / 3 tests passed | `npm-ci.log`、`frontend-*.log` |
| 首次七天、分页/去重、刷新、SHA 命名、单 FIT ZIP、导入、secret 不落状态/结果 | 正常/边界 | 合成 2 页活动、重复 remote_id、刷新 token、一个 FIT bytes + 一个单 FIT ZIP | 窗口最近七天；分页去重；刷新写回；下载命名 UTC 日期 + FIT 字节 SHA；结果/状态不含 secret | 通过 | `pytest-probes.log` 前 2 项通过 |
| 三小时 due/force、已同步跳过、manual_required、坏 JSON/非对象、路径越界 | 正常/错误/安全 | 构造未到 3 小时、force、已 synced、manual_required、坏认证文件、非对象认证、`../` 路径 | 未到期不列表；force 可运行；已同步不下载；manual_required 不列表/下载；坏配置失败；越界失败 | 通过 | `pytest-probes.log` 前 2 项通过 |
| ZIP 无 FIT/多 FIT、unknown 日期、原子 tmp 清理、导入失败保留原件且不标记失败 remote | 错误/边界 | 无 FIT ZIP、多 FIT ZIP、unknown 活动、导入第二个活动失败 | 明确失败或 unknown 命名；无 tmp 残留；失败远端不标记 synced | 这些子项通过 | `pytest-probes.log` 失败用例中前置断言通过 |
| 有上次成功状态的部分失败恢复 | 错误/边界 | 初始 `last_success_at_utc=2031-02-07T12:00Z`；本轮两个新活动，第一个导入成功，第二个导入失败 | 返回失败；保留失败 FIT 原件；不标记失败 remote；`last_success_at_utc` 仍为上次成功时间 | 失败：状态中 `last_success_at_utc` 实际为 `None`；探针退出 1 | `pytest-probes.log` |
| 安全边界 | 安全 | 合成 tmp 实例，不读取仓库真实 `states/verification/garmin.json`；仅 fake client | 不触碰真实凭据/网络/MFA | 通过；无真实调用 | 人工核对 + 探针设计 |

## 问题表

| 稳定问题编号 | 对应要求 | 可复现步骤 | 预期 | 实际 | 影响 | 证据 |
| --- | --- | --- | --- | --- | --- | --- |
| V31-B4-001 | 失败恢复：若已有上次成功状态，部分失败不得错误重置 `last_success` 导致未来窗口无限回退 | 在隔离实例写入 `GarminSyncState(last_attempt=上一轮, last_success=上一轮)`；本轮 force 同步两个新活动；第一个导入成功，第二个导入器抛 `RuntimeError`；读取 `states/garmin-sync.json` | 本轮失败，失败远端不标记 synced；失败 FIT 原件保留；`last_success_at_utc` 保持上一轮成功时间 | 本轮失败、失败远端未标记、原件保留，但 `last_success_at_utc` 被写成 `null` | 后续 `sync_window()` 会回退到首次七天窗口，可能重复拉取历史窗口；与恢复语义和三小时调度状态持久化不符 | `pytest-probes.log`：`AssertionError: assert None == datetime.datetime(2031, 2, 7, 12, 0, tzinfo=datetime.timezone.utc)` |

## 未验证事项、证据缺口、环境限制和停止原因

- 未做真实 Garmin/pygarminconnect/网络/登录/MFA/私人凭据/真实活动调用；这是本任务明确边界。
- 未验证真实适配器与真实服务端兼容性；当前仅确认其为薄包装形状和合成边界。
- 同名不同字节冲突未用真实 SHA 碰撞复现；基于 SHA 命名设计，真实冲突需要 SHA256 碰撞或特殊 monkeypatch，未作为本次阻塞问题。
- 停止原因：发现可复现产品验收失败 V31-B4-001；受审内容只读，未修改产品。

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "已给出独立验证结论失败、问题 V31-B4-001、命令证据和残余风险。"
    }
  ],
  "changedFiles": [],
  "testsAddedOrUpdated": [],
  "commandsRun": [
    {
      "command": "python3 snapshot verification script",
      "result": "passed",
      "summary": "65 文件逐项和聚合 SHA 核对通过。"
    },
    {
      "command": "cd /tmp/trainlab-b4-validator-run/source && UV_PROJECT_ENVIRONMENT=/tmp/trainlab-b4-validator-venv uv sync --project . --python 3.12 --locked --extra dev --no-editable",
      "result": "passed",
      "summary": "隔离依赖安装成功。"
    },
    {
      "command": "python -m pytest tests -q -p no:cacheprovider",
      "result": "passed",
      "summary": "177 passed, 2 warnings。"
    },
    {
      "command": "python -m ruff check --no-cache .",
      "result": "passed",
      "summary": "删除隔离复制带入的未受审 build 产物后，对受审源文件检查通过。"
    },
    {
      "command": "python -m mypy -p trainlab -p tests --no-incremental && python -m compileall -q skills schemas tests && python -m trainlab.check_architecture",
      "result": "passed",
      "summary": "类型、编译、架构门均通过。"
    },
    {
      "command": "npm ci && npm run lint && npm run typecheck && npm test && npm run build",
      "result": "passed",
      "summary": "前端隔离抽查全部通过；3 tests passed。"
    },
    {
      "command": "python -m pytest /tmp/trainlab-b4-validator-probes -q -p no:cacheprovider",
      "result": "failed",
      "summary": "3 个独立探针中 2 passed、1 failed；复现 V31-B4-001。"
    },
    {
      "command": "git diff --cached --name-only",
      "result": "passed",
      "summary": "暂存列表为空。"
    }
  ],
  "validationOutput": [
    "/tmp/trainlab-b4-validator-logs/snapshot-verify.log",
    "/tmp/trainlab-b4-validator-logs/uv-sync.log",
    "/tmp/trainlab-b4-validator-logs/pytest-all.log",
    "/tmp/trainlab-b4-validator-logs/ruff.log",
    "/tmp/trainlab-b4-validator-logs/mypy.log",
    "/tmp/trainlab-b4-validator-logs/compileall.log",
    "/tmp/trainlab-b4-validator-logs/architecture.log",
    "/tmp/trainlab-b4-validator-logs/frontend-test.log",
    "/tmp/trainlab-b4-validator-logs/pytest-probes.log"
  ],
  "residualRisks": [
    "未做真实 Garmin/pygarminconnect/网络/私人凭据调用。",
    "真实适配器只做合成/薄包装边界验证，未真实联调。",
    "同名不同字节冲突未用真实 SHA256 碰撞构造。"
  ],
  "noStagedFiles": true,
  "diffSummary": "未修改受审内容；仅在 /tmp 写入隔离副本、日志和临时探针，并写出本验证报告。",
  "reviewFindings": [
    "blocker: source/skills/_shared/scripts/trainlab/garmin_sync.py - 部分同步已有 last_success 时，后续导入失败会把 last_success_at_utc 持久化为 null（V31-B4-001）。"
  ],
  "manualNotes": "结论：失败。受审快照核对通过；静态门和既有回归通过；独立恢复探针发现 B4 验收失败。"
}
```
