# T10～T13 Developer 自查结果

## 交付与冻结

已实现两区可选的真实 Web 登录/验证码面板、安全 HTTP/内存会话、Web 生命周期认证维护和产品启动入口。不是 CLI 代替 GUI，也没有用 HTTP 假成功替换认证链。仅完成 Developer 自查；T14 独立验证、T15 主验收及真实 Garmin 操作仍未执行。

- 分支 `work/adhoc-0031-local-web-system`；HEAD `a5893ac6eb8295cd8a60d8f2537bc213d1412885` 加现有未提交工作。
- 开始核对原96个 source＋4个 references 哈希全相同；最终116个 source，原80个逐字节未变、授权修改16个、新增20个；4个 references 全部未变。没有删除原文件。
- 冻结依据：`source-after.json`、`references-after.json`、`web-build.json`、`freeze.json`；完整本轮文件表 `changed-files.json`，Git 实际状态 `git-before.txt` / `git-after.txt`。`working-tree.diff` 包含原有未提交差异，不应全部归因本轮。
- Python3.12.13 独立仓库外非 editable 环境；锁定 garminconnect0.2.40 / garth0.6.3 未升级。最终强制重装后46个已安装产品/Schema文件与源逐字节一致，见 `installed-files.log`。
- 未暂存、提交、切分支、推送、调度其他角色或修改协调记录；未读取正式 states，未进行真实认证/维护/下载/AI，未启动正式实例。

## 按目标修改

| 任务 / 目标 | 实际实现与证据 |
| --- | --- |
| T10 / GUI32-03、04 | 所有者新增安全区域及内部代次观察；Web 一个长期所有者、一个可唤醒维护循环，操作门及受保留的 worker 任务，关闭等待在途完成再 close。共享 CLI/Web 纯重试/检查延迟策略，不复制令牌规则。维护区分 scheduled/retry_wait/paused/manual_required/blocked，真实 commit 后才记录 refreshed；旧代次人工错误不能被 status 洗掉。`test_auth_lifecycle.py`、Chrome C07～C10、C12。 |
| T11 / GUI32-01～05 | 六条 `/api/garmin/auth` 路由；16条精确方法/路径集合。规范 Host 全站门、认证 Origin/Fetch Metadata/CSRF/内存 cookie 会话、会话与 attempt 双绑定、严格字段与实际16KiB流式限制、固定错误、no-store/no-referrer/frame-ancestors。HTTP/运行态不接触仓储或 SDK。`test_auth_http.py`、`test_auth_security.py`、所有权门、Chrome C06/C11。 |
| T12 / GUI32-01～03、05 | 独立 `GarminAuthPanel`＋API/状态模型；无 DB/AI 仍可登录。国际/中国区、遮挡输入、提交清空、MFA/取消/过期/重来/重启反馈、维护重试、保存/期限/在线未核验分开显示；不持久化输入、不自动重放，序号阻止旧异步结果盖新状态。原仪表盘仅挂载，原关键断言保留。 |
| T13 / GUI32-06 | 系统 Chrome→构建 React→真实 HTTP→真实所有者→实际锁定 SDK login/resume/OAuth/profile/settings→原仓储；仅远端传输替换。私有 stdin IPC 控制合成时钟、错误/锁/进程重启；生产无测试路由。所有服务及 CLI 子进程显式阻断外连。认证关闭 trace/HAR/video/截图，并禁用 Playwright 自动失败页面快照。 |
| 产品入口 | `python -m trainlab.local_web.cli --instance-root . --project-root .`；固定127.0.0.1:8080、单worker、无reload、无代理信任、关闭默认access log。帮助、缺构建的固定可操作错误和实际合成 CLI 子进程启动/健康/干净退出均检查，见 `product-cli.log`。 |

## 实际命令与结果

命令从项目根、`source` 或 `source/frontend` 执行。Python 均直接使用本轮独立环境解释器，不使用 `uv run`。环境实际路径及安装元数据保留在安装日志；可重复检查入口见 `source/README.md`。

| cwd | 命令 / 方式 | 最终退出与输出 | 证据 |
| --- | --- | --- | --- |
| 根 | `UV_PROJECT_ENVIRONMENT=<本轮仓库外环境> uv sync --project source --python 3.12 --locked --offline --extra dev --no-editable --reinstall-package trainlab-source` | 0；最终第7次安装为当前版本 | `install-7.log` |
| 根 | 源/安装副本逐文件比较及非editable元数据断言 | 0；46文件完全一致 | `installed-files.log` |
| frontend | `npm ci`，先于完整pytest的 `npm run build` | 各0；141包审计无已知漏洞，fsevents脚本许可警告未扩大授权 | `npm-ci.log`、`build-final.log` |
| source | `python -m pytest tests -q -p no:cacheprovider` | 0；318 passed，2条上游弃用警告 | `pytest-final.log` |
| source | `python -m ruff check --no-cache .` | 0 | `ruff-final.log` |
| source | `python -m mypy -p trainlab -p tests --no-incremental` | 0 | `mypy-final.log` |
| source | `python -m compileall -q skills schemas tests`；`python -m trainlab.check_architecture` | 各0；Schema/所有权合同同时在pytest覆盖 | `compileall-final.log`、`architecture-final.log` |
| frontend | `npm run lint`；`npm run typecheck`；`npm test` | 各0；14项前端测试 | `lint-final.log`、`typecheck-final.log`、`frontend-test-final.log` |
| frontend | `UV_PROJECT_ENVIRONMENT=<环境> npm run e2e` | 0；原仪表盘2项实际Chrome通过 | `chrome-default-final.log`、`playwright-default-results.json` |
| frontend | `UV_PROJECT_ENVIRONMENT=<环境> npx playwright test -c playwright.auth.config.ts` | 0；认证24项实际Chrome通过 | `chrome-auth-final.log`、`playwright-auth-results.json` |
| source | 产品CLI帮助、缺前端构建、阻断外连的真实CLI合成进程启动/HTTP健康/SIGINT停止 | 检查程序0；缺构建按合同2；实际服务退出0 | `product-cli.log` |
| 根 | `git diff --check`；`git diff --cached --quiet` | 各0；暂存为空 | `diff-check.log`、`freeze.json` |
| 根 | source/references/构建哈希、53份日志canary扫描及阳性对照、端口检查 | 原资料4/4未变；日志命中0，阳性对照有效；8080/8081无监听 | `freeze.json`、`source-after.json`、`web-build.json` |

Chrome C01～C12：两区各普通/MFA、MFA刷新恢复、不依赖DB/AI；401/403/429/超时/异常页面/MFA未完成/settings失败；取消/旧attempt/真实HTTP状态响应乱序不盖新流程/过期/会话失效；并发验证码、跨BrowserContext抢答、健康不阻塞；真实子进程重启；期限前维护保存/重启；503/429/超时3次耗尽与用户重试、401/403粘性人工状态；CLI新代次、外进程锁及写盘失败；真实跨端口浏览器攻击；输入清空/持久存储为空/日志与私有文件扫描、在途停服等待。Python补精确TTL前/到点/之后、请求头/分块大小/严格JSON、断开等待及所有权边界。安全SDK收据作为Playwright JSON附件保存，仅域名、方法、固定路径、次数和合成指针摘要，不含请求体/令牌。

## 原失败与修正（未抹去）

| 记录 | 原事实、根因及修正 | 当前结果 |
| --- | --- | --- |
| GUI32-V1-001 | 首轮定向pytest：MFA成功返回仍带 operation_in_progress，因 DTO 在操作门释放前生成；改为释放后取安全视图。首次2项失败，1种修法。 | 定向149项及最终318项通过；Chrome正常/MFA通过。 |
| GUI32-V1-002 | 首轮定向另4项把普通SDK早返回路径误当会取settings；锁定SDK源码证实只有resume后该路径才取settings。将故障注入放到真实MFA后，保留失败码/旧指针/隐私强断言。另1项测试立即第二次提交撞启动观察门，重启持久化场景前半明确关闭调度，后半启用；维护另有专门覆盖。 | 7个原失败全闭合，见 `pytest-target-1.log` / `pytest-target-2.log`。不是SDK降级或删断言。 |
| GUI32-V1-003 | 首轮Chrome 12失败/10通过：4个旧仪表盘错误文本并无alert角色；7个hasText字符串误写成正则；1个外进程锁原因缺专属可理解文案。修正定位器与固定auth_lock_busy文案。 | 第二轮22通过；补超时维护后23通过，补真实延迟状态响应后最终24通过。原日志 `chrome-auth-1.log`，首轮产物保存在 `*-run1`。 |
| GUI32-V1-004 | 人工自查发现MFA在磁盘锁忙、尚未执行SDK时不应丢Web映射；保留待MFA以便明确重试。补Chrome真实外进程锁→提交→未执行→仍待验证回归。同时未知异常不保留虚假submitting。 | 最终C10及错误边界通过；无已失败修法。 |
| GUI32-V1-005 | 首次全量pytest 316 passed＋1 teardown error：隐私canary测试没装离线传输，真实socket尝试被预置安全门阻断（外部请求未发出）。不是环境故障；修正client夹具总是先装offline传输。 | `pytest-full-1.log`保留原证据；最终完整318通过且外连尝试0。 |
| GUI32-V1-006 | 原默认Chrome第一次1失败/1通过，原断言仍写API路由10。按批准合同精确改16，其他原行为断言保留。 | 最终默认Chrome2通过，见两轮日志。 |
| GUI32-V1-007 | 最后边界复核发现HTTP校验不应把全空格密码当空输入；仅密码按原始非空字符串校验，不trim/截断。新增两项真实SDK请求体回归核对首尾空格及全空格原样传输。人工发现，无已失败修法。 | 最终完整318项及全部静态/Chrome再次通过。 |
| 静态/类型 | 首轮Ruff导入/未用项/显式subprocess check等；mypy测试传输替换类型问题；TS缺Node类型（未增依赖，进程宿主按已有测试JS做法实现并给自有接口声明）；新增JS用globalThis.fetch修正lint。 | 原日志完整保留，最终全部退出0；没有禁用全局检查或降低业务断言。 |

未触发两种实质修法仍失败或连续三轮同问题不收敛的停止条件。原 D31-LIVE-002、AU32-V1-001/002/003、RV、INFRA 编号与计数未改写。

## 未检与残余风险

- 尚无独立Validator、主Agent实际验收或真实Garmin服务证据；不得把本自查写成整个ADHOC-0032完成或真实401已闭合。正式凭据、本人登录/MFA、真实刷新/同步/下载与AI未操作。
- AU32-V1-002/003 的既有Context/资料错误未修、未作为本轮闭合目标；对应业务代码和原公开资料保持不变，原有效检查未删除。
- 仅规范回环HTTP、单进程单worker；不防恶意同机进程/浏览器扩展/管理员，不保证内存物理擦除。浏览器密码管理器不由应用绝对控制。
- SDK逐HTTP请求15秒，不是完整认证/停服总硬上限；休眠/停服/持续断网不保证刷新。锁定SDK内部页面/行为将来变化仍需重新适配和真实验证。
- 维护历史只在本次Web内存，重启后显示本次尚无刷新成功；本地加载绝不冒充在线核验。
