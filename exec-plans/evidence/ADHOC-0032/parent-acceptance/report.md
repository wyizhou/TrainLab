# ADHOC-0032 主 Agent 本轮本地验收

- 日期：2026-09-18。
- 结论：RV-001、RV-002修复，以及本轮Web/SDK离线集成范围通过；真实Garmin成功链路无法判断，ADHOC-0032整体不标完成。AI实测继续暂停。
- 分支：`work/adhoc-0031-local-web-system`；HEAD `a5893ac6eb8295cd8a60d8f2537bc213d1412885` 加当前未提交source。
- 独立前置：已读取[全新Validator报告](../rv-fix-validator-report.md)，对应子任务`e2f4c2ff-fbbf-4032-8aa1-a96be452555a`，workflow `67a8c40f-cef9-4f07-ac80-f894db16b9d1`已成功完成。报告不是主验收替代品。
- 主Agent检查实际代码、回归测试及差异；确认原有公共接口/错误码保留，日志隐私边界只在当前上下文启用，不全局关闭日志；默认E2E不再调用uv或覆盖调用者环境。现有包结构及依赖未因修复变更。
- 主Agent新建独立仓库外、路径含空格的Python3.12环境，按README锁文件非editable安装，逐字节核对36个产品/Schema文件与当前源码一致；未复用开发或验证环境。
- 冻结：78个公开source文件与Validator受验快照完全一致，主验收前后0变化；暂存区为空，8080无残留监听。见`freeze-result.json`、`source-before.json`、`source-after.json`。

## 亲自执行的检查

所有命令、cwd、退出码见`commands.json`和对应日志；安装见`install.log`。`python`均为本轮指定环境解释器，未使用可能重新同步安装方式的uv run。

| 范围 | 实际方式 | 结果 |
| --- | --- | --- |
| 安装一致性 | `uv sync --project source --python 3.12 --locked --extra dev --no-editable`；`check-installed.py`逐字节核对 | 退出0，36文件一致 |
| Python回归 | `python -m pytest tests -q -p no:cacheprovider` | 退出0，214 passed |
| 真实SDK离线集成/隐私 | 直接复跑Validator独立`test_independent_garmin.py`，网络连接阻断 | 退出0，21 passed，包含日志阳性对照、畸形配置、服务错误、真实SDK刷新/请求准备、FIT解码和SQLite入库 |
| Python静态/架构 | Ruff、mypy包检查、compileall、`trainlab.check_architecture` | 全部退出0，mypy 56源文件 |
| 前端 | npm ci、lint、typecheck、test、build | 全部退出0，11单测 |
| 默认E2E | `npm run e2e -- --reporter=list --output=../../exec-plans/evidence/ADHOC-0032/parent-acceptance/default-e2e-artifacts` | 退出0，原2项通过；默认配置、调用者解释器、系统Chrome |
| 额外浏览器完整场景 | `node exec-plans/evidence/ADHOC-0032/parent-acceptance/independent_browser.mjs` | 退出0，10项通过；channel=chrome，实际版本152.0.7977.83 |
| 差异 | `git diff --check`、源文件SHA256/集合、Git版本/暂存区和8080检查 | 均符合预期 |

额外浏览器脚本从本轮Validator材料复制，仅将证据输出目录改为主验收目录，其余行为/断言未变。主Agent实际启动和运行，并查看正常列表/详情/周报告、空态、坏JSON错误态三张截图；显示与DOM断言一致。场景覆盖状态/服务卡、搜索/边界/恢复、选择/详情、报告全文保真与HTML安全、周总结、加载、空态、网络/API/坏JSON错误、旧成功/错误响应竞态及API/SPA分离。每个场景断言无浏览器异常、业务外网请求或私人文件请求；不以截图代替自动断言。

## 限制和交付状态

- 本轮只用合成实例；未读写正式states/凭据，未发起真实Garmin或AI请求，未运行正式调度。
- 当前日志安全结论适用已锁定SDK及受测同步调用；依赖升级/新日志出口须重新验证。
- 两项首次修法均通过独立复验及主验收；累计完成修复复验失败0。历史首次缺陷、开发自查/验证辅助错误及两次基础设施失败继续保留，不改写为从未失败。
- 真实Garmin此前401的原因仍未查明；不能推断凭据必然过期、必须MFA或DI认证映射已经得到真实服务接受。后续应先核对实际认证接口合同和配置形状，不能靠重复同一请求宣告完成。
- 214项测试的两条依赖弃用警告、Chrome显示诊断与npm提示已保留；不因这些提示隐藏有效失败或修改依赖。
- 未暂存、提交、推送、更新PR或合并；真实成功链路与整体交付未完成，不把局部通过升级为整个ADHOC-0032通过。
