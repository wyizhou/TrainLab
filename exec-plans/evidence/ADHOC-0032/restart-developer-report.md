# ADHOC-0032-V1-001 Developer 核实报告

## 结论与修改

**已有非 editable 安装合同下检查全部通过，无需修改产品、配置、锁文件、README 或测试。** 本轮只完成 0032-T3 的检查入口核实，不代表 ADHOC-0032 整体功能完成。

- 完整读取首次任务材料、适用规则、安装合同及旧检查记录；未续用旧聊天，未派发其他角色。
- 分支：`work/adhoc-0031-local-web-system`；HEAD：`a5893ac6eb8295cd8a60d8f2537bc213d1412885`。
- 开始与结束均对照 `exec-plans/evidence/ADHOC-0032/restart-review-snapshot.json`：76 个公开文件全部匹配，无缺失或额外产品文件。
- 原有前端 E2E、Garmin 接线、依赖和测试等未提交改动全部保留。`AGENTS.md`、`PLAN.md`、当前执行计划、`MEMORY.md` 的内容哈希未变。
- 仓库内仅新增 `exec-plans/evidence/ADHOC-0032/restart-developer/` 下的 28 份脱敏检查记录，完整清单见文末。未暂存、提交、推送或合并。
- 未新增或修改测试：未发现需要产品修复的缺陷；使用现有 199 项测试及临时安装方式对照核实，未降低断言或静态检查标准。

## 原因与本轮办法

稳定编号：**ADHOC-0032-V1-001**。

旧命令采用默认 editable 安装，随后用 `uv run` 检查；这与 `source/README.md` 已规定的“非 editable 安装后检查已安装包”不同。

本轮在两个新建、独立的仓库外临时环境中，对同一工作区、同一锁文件、同一 Python 和 mypy 版本做了对照：

| 安装方式 | 实际包形态与运行时导入 | mypy 结果 |
| --- | --- | --- |
| 合同要求的非 editable | `site-packages/trainlab/` 实体包；离开工程目录仍可导入主包、FIT、Web、合同及 Schema 包 | 退出 0；54 个源文件无问题 |
| 仅用于诊断的默认 editable | 没有该实体目录，通过 setuptools 生成的 `.pth` 和 finder 映射回源码；Python 仍能导入 | 退出 2；复现 `Can't find package 'trainlab'` |

由此确认：**本环境中的 editable 运行时导入机制与 mypy 静态包发现不一致，是旧包发现失败的直接原因；不是已有非 editable 安装合同下缺少 `trainlab` 包。** 不需要为另一种安装方式移动产品目录、修改 `sys.path`、放宽类型检查或新增产品要求。

另将非 editable 环境内的 35 个产品代码、类型标记及 Schema 文件逐一与当前工作区比对 SHA-256，全部一致，排除检查到旧安装包的情况。证据分别为 `package-noneditable.log`、`package-editable-control.log`、`mypy.log`、`mypy-editable-control.log`。

与历史办法的区别：先按原合同安装并直接使用该环境的 Python，不使用可能重新同步安装方式的 `uv run`，不改走物理目录检查。第二个环境仅用于一次受控错误复现，未改变主检查环境。

历史计数保留：检查失败记录 1、修复派发中止 1、完成修复及修复复验失败 0。本轮另有一次明确记录的 editable 诊断失败；没有产品修复尝试，不将该对照记为修复失败，也不抹去历史失败。

## 环境与实际检查

Python 3.12.13；uv 0.12.3；mypy 1.20.2；pytest 9.1.1；Ruff 0.16.7。另实际核对 npm 11.17.0、Node 26.5.0、系统 Chrome 152.0.7977.83 可用，但未运行前端验收。

`$UV_PROJECT_ENVIRONMENT` 指本轮新建的仓库外主环境，`$EDITABLE_CONTROL_ENV` 指独立诊断环境；缓存亦置于本轮临时目录。检查进程移除继承的 `PYTHONPATH`、`PYTHONHOME`、`VIRTUAL_ENV`，直接使用环境内 Python，未全局安装或创建仓库 `.venv`。

以下证据文件均位于 `exec-plans/evidence/ADHOC-0032/restart-developer/`，完整命令、工作目录、退出码及耗时见 `commands.jsonl`。

| 工作目录 | 实际命令或核实方式 | 退出结果与关键输出 | 证据 |
| --- | --- | --- | --- |
| `.` | `uv sync --project source --python 3.12 --locked --extra dev --no-editable` | 0；安装 47 个包 | `install-noneditable.log` |
| `source/` | `$UV_PROJECT_ENVIRONMENT/bin/python -m mypy -p trainlab -p tests --no-incremental` | 0；`Success: no issues found in 54 source files` | `mypy.log` |
| `source/` | `$UV_PROJECT_ENVIRONMENT/bin/python -m pytest tests -q -p no:cacheprovider` | 0；`199 passed, 2 warnings in 8.98s` | `pytest.log` |
| `source/` | `$UV_PROJECT_ENVIRONMENT/bin/python -m ruff check --no-cache .` | 0；`All checks passed!` | `ruff.log` |
| `source/` | `$UV_PROJECT_ENVIRONMENT/bin/python -m compileall -q skills schemas tests` | 0；无错误输出 | `compileall.log` |
| `source/` | `$UV_PROJECT_ENVIRONMENT/bin/python -m trainlab.check_architecture` | 0；`architecture and public Schema checks passed` | `architecture.log` |
| `.` | `git diff --check` | 0；无输出 | `diff-check.log` |
| 仓库外临时目录 | Python 导入位置、安装元数据、35 个安装文件哈希核对 | 0；非 editable，全部匹配 | `package-noneditable.log` |
| `.` | `UV_PROJECT_ENVIRONMENT="$EDITABLE_CONTROL_ENV" uv sync --project source --python 3.12 --locked --extra dev` | 0；独立对照环境安装成功 | `install-editable-control.log` |
| 仓库外临时目录 | editable 包导入位置、`.pth` 与 finder 映射核对 | 0；运行时导入成功，使用源码映射 | `package-editable-control.log` |
| `source/` | `$EDITABLE_CONTROL_ENV/bin/python -m mypy -p trainlab -p tests --no-incremental` | 2；`Can't find package 'trainlab'`，仅诊断复现，不是合同验收入口 | `mypy-editable-control.log` |
| `.` | 76 个公开文件 SHA-256/大小、文件清单及受保护记录比对 | 全部一致 | `snapshot-before.json`、`snapshot-after.json`、`preservation.json` |
| `.` | `git diff --cached --name-only` | 0；开始与结束均无输出 | `staged-before.log`、`staged-after.log` |

安装及包探针日志中的环境和工程绝对路径均已换为通用变量或项目相对路径；`$PROJECT_ROOT` 表示项目根。探针仅检查公开安装产物，不调用业务同步或报告服务。

pytest 的两个警告来自锁定依赖：Starlette 的 httpx 测试客户端弃用提示，以及 anyio 的 `BlockingPortal` 别名弃用提示。本轮未因警告升级依赖或修改检查合同。

## 未验证事项与停止边界

- 本轮是 Developer 自查，未替代后继独立复验或主验收。
- 前端完整 Playwright Chrome 验收未运行，按首次任务留待后继独立验证；Chrome 可用不等于 Web 验收通过。
- 未发起真实 Garmin 请求。真实成功下载、入库链路仍未验证；历史 401 不能单独证明凭据过期、必须 MFA 或客户端实现正确。
- AI 参数及实服务检查继续暂停，未发起真实 AI 请求。
- 未读写正式 `states/`，未启动后台正式服务或调度，未输出凭据，未修改全局配置或启动 CI。依赖安装网络访问仅用于获取锁定依赖。
- 当前合同内未发现需要最小修复的实现问题；本轮在核实完成处停止。上述未决事项交主 Agent 按原边界处理，不扩大修改范围。
