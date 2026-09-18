# RV-001 / RV-002 首次最小修复报告

结论：两项修复及本地自查已完成，目前无实施阻塞；尚未独立复验，不代表 ADHOC-0032 整体验收通过。

## 版本与范围

- 分支：`work/adhoc-0031-local-web-system`；HEAD：`a5893ac6eb8295cd8a60d8f2537bc213d1412885`，未提交、未暂存。
- 开始时核对 `network-recovery/source-snapshot.json`，76/76 文件哈希一致。
- 相对该快照，仅修改3个既有文件、新增3个产品/测试文件；其余73个原文件保持不变。原有9个 tracked source 改动及4个未跟踪产品文件均保留。没有改写 PLAN、执行计划、MEMORY、AGENTS。
- 最终快照：`exec-plans/evidence/ADHOC-0032/rv-fix-developer/source-snapshot-final.json`；Git状态：同目录 `git-status-final.txt`。
- 未新增依赖，未改全局配置，未执行提交、推送、PR或CI；未读取正式 states、真实凭据，未请求真实 Garmin/AI，未启动正式调度。

## 修复与文件

| 问题 | 本轮文件 | 根因及最小办法 |
| --- | --- | --- |
| RV-001 | `source/skills/_shared/scripts/trainlab/garmin_sync.py` | SDK先记录带敏感输入的异常，原来的结果净化晚于日志输出；并且 `raise ... from exc` 仍暴露异常链。登录、配置、列表、下载边界加入受控日志处理，对外异常不展示原始异常链；保留原错误码映射和业务失败。 |
| RV-001 | 新增 `source/skills/_shared/scripts/trainlab/garmin_privacy.py` | 仅当前产品调用上下文内，将已加载的 SDK/HTTP认证依赖日志替换为固定安全记录，保留级别与来源，移除原参数、extra、异常和堆栈。用 ContextVar 隔离，不全局关闭日志；嵌套、退出、其他模块及其他线程有回归验证。 |
| RV-001 | 新增 `source/tests/sync/test_garmin_privacy.py` | 15项实际锁定SDK离线回归，禁止真实网络；覆盖目录/编码tokenstore两种载体、OAuth1/OAuth2畸形输入、DI异常链、正常DI/tokenstore、过期tokenstore既有刷新钩子、list/download/FIT/SQLite链路、401/429/503映射及日志作用域。 |
| RV-002 | `source/frontend/playwright.config.ts` | 删除硬编码环境及 `uv run`。默认入口直接执行调用者 `UV_PROJECT_ENVIRONMENT/bin/python`，缺变量立即失败，无解释器则明确失败，不回退或安装。保留Chrome、8080、拒绝复用服务及原合成实例。 |
| RV-002 | 新增 `source/frontend/tests/e2e-environment.test.js` | 6项回归直接导入默认配置、执行其真实webServer命令。覆盖有效环境、含空格/引号路径、变量缺失、解释器不存在/不可执行、Chrome/端口/拒绝复用。用阻断uv的桩保证旧命令失败复现不会误装环境。 |
| 两项 | `source/README.md` | 仅更新受影响的E2E环境用法和日志隐私边界说明。 |

没有重写刷新策略、改变包结构、添加新依赖或扩大产品功能。既有四处 `Exception` SDK边界保留；因安全要求隐藏原异常链，在四处使用局部 `BLE001` 工具指令，未修改全局检查配置，未吞掉或改成成功结果。

## 环境与实际检查

证据目录统一为 `exec-plans/evidence/ADHOC-0032/rv-fix-developer/`，以下日志均相对此目录。日志保留实际命令、工作目录、退出码；环境路径和合成敏感标记已脱敏。

新建仓库外独立环境，路径包含空格。Python 3.12.13；uv 0.12.3；garminconnect 0.2.40；garth 0.6.3；Node 26.5.0；npm 11.17.0；Playwright 1.63.0；系统Chrome 152.0.7977.83。依README锁文件非editable安装，修改产品后重装；检查均直接使用该环境Python，没有用 `uv run` 重新同步产品环境。

表中 `python` 指该环境的 `bin/python`，不是全局解释器。

| 实际命令/检查 | 退出及结果 | 证据 |
| --- | --- | --- |
| `uv sync --project source --python 3.12 --locked --extra dev --no-editable --reinstall-package trainlab-source` | 0，重装完成 | `install-final.log` |
| `python .../check-installed.py` | 0；非editable、两个修复模块wheel字节与源码一致、环境路径含空格 | `installed-final.log` |
| `python -m pytest tests -q -p no:cacheprovider` | 0；214 passed，包含新增15项 | `pytest-final.log` |
| `python -m ruff check --no-cache .` | 0；全部通过 | `ruff-final.log` |
| `python -m mypy -p trainlab -p tests --no-incremental` | 0；56个源文件无问题 | `mypy-final.log` |
| `python -m compileall -q skills schemas tests` | 0 | `compileall-final.log` |
| `python -m trainlab.check_architecture` | 0；架构及公开Schema通过 | `architecture-final.log` |
| `git diff --check` | 0 | `diff-check-final.log` |
| `npm run lint` / `npm run typecheck` | 均0 | `frontend-lint-final.log`、`frontend-typecheck-final.log` |
| `npm test` | 0；11 passed，包含新增6项 | `frontend-test-final.log` |
| `npm run build` | 0 | `frontend-build-final.log` |
| 默认 `npm run e2e -- --reporter=line,json --output=../../exec-plans/evidence/ADHOC-0032/rv-fix-developer/playwright-final-artifacts --workers=1` | 0；原2个Chrome场景通过，没有替代配置。运行时设置JSON输出至本证据目录，DEBUG记录系统Chrome实际启动 | `default-e2e-final.log`、`default-e2e-final-results.json` |
| `env -u UV_PROJECT_ENVIRONMENT npm run e2e -- ...` | 1，预期拒绝启动；明确指出缺环境变量 | `default-e2e-missing.log` |
| `env UV_PROJECT_ENVIRONMENT=nonexistent-synthetic-env npm run e2e -- ...` | 1，预期拒绝启动；明确指出解释器不存在 | `default-e2e-invalid.log` |
| 用当前环境直接重跑原客观SDK复现文件 `restart-validator/test_validator_garmin.py` | 0；12 passed。只是开发自查，不冒称新的独立验证 | `original-probe-regression.log` |
| `python .../final-snapshot.py`；`git diff --cached --quiet` | 0；73个原文件未变，3改3增，暂存为空；8080服务已退出 | `snapshot-final.log`、`source-snapshot-final.json` |

默认Chrome场景实际覆盖原状态/服务卡、搜索、列表选择、详情、活动报告安全文本、周总结、搜索空态、API错误态及API/SPA分流。此前独立验证的另外8个临时场景本轮没有重新执行，不能把历史10项记成本轮10项。

## 失败、自查调整与计数

- 两项均无历史修法；本轮各采用1种产品修法，未更换产品方案反复尝试。
- 修前先补回归：RV-001初测13失败、1通过；其中11项复现敏感日志/异常链，2项来自新正常路径夹具错误。RV-002修前6项中5失败、1通过，实际阻断了旧入口调用uv。原始证据分别为 `red-rv001.log`、`red-rv002.log`。
- 修后第一次sync自查23通过、2失败：正常tokenstore夹具把 `user-settings` URL误归为profile返回。检查实际SDK路径后调整匹配顺序；未更改SDK或业务断言。详见 `green-rv001.log`，最终完整214项通过。
- 首次Ruff检查失败：隐藏异常链后既有宽异常边界触发4处BLE001，另有1处新增测试导入排序问题。局部安全边界指令和导入顺序修正后通过；保留 `ruff.log`。
- 首次前端typecheck失败：新增Node命令测试缺少本项目未安装的Node类型声明。没有添加依赖或关闭检查，改用普通JS承载相同6项命令回归；ESLint/Vitest仍执行全部断言，原TS检查范围和配置未动。保留 `frontend-typecheck.log`。
- 以上自查失败如实保留，未改写为成功；最终检查结果以 `*-final.log` 为准。两项既有“首次发现1、完成修复失败0”历史记录未改写；本轮尚未发生新的独立修复复验，由主Agent依据后续验证维护累计计数。

## 未验证与风险

- 无当前实施阻塞；仍须全新Validator固定版本复验和主Agent验收。
- 真实Garmin成功同步及历史401原因仍未验证；真实AI继续暂停。本轮网络边界只验证实际SDK的离线合成行为。
- SDK日志安全验证针对锁定版本及其同步调用路径；升级SDK或引入新的异步日志路径时应重新检查该边界。
- 保留两个既有Python依赖弃用警告和Chrome无显示器相关stderr；本轮所有浏览器断言通过，没有隐藏这些输出。
- 没有任何暂存文件、提交或推送。受审产品文件在最终检查后未再修改。
