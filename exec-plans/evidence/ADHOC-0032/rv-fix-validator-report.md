# ADHOC-0032 修复后独立复验报告

## 结论与适用范围

| 范围 | 结论 | 依据 |
|---|---|---|
| RV-001：Garmin 失败不泄露 token/secret | **通过（当前锁定 SDK、离线受测边界）** | 真实 SDK 加载畸形 tokenstore，捕获 WARNING 以上日志、完整 LogRecord、异常 traceback、控制台和返回值，均未暴露合成秘密；另有裸 SDK 阳性对照，证明采集确实能发现泄露。 |
| RV-002：默认 E2E 使用调用者指定环境 | **通过** | 默认 webServer 命令独立探针通过；实际 `npm run e2e` 使用本轮仓库外、路径含空格的非 editable Python 环境，并由系统 Chrome 完成测试。 |
| T1：当前 Web 可见功能及正常/错误/边界回归 | **通过（本地合成数据）** | 默认 E2E 2 项通过；独立系统 Chrome 场景 10 项通过，覆盖搜索、详情、全文报告、周总结、空态、失败、加载和竞态等。 |
| T2：锁定 SDK 合成构造、认证、刷新、列举、下载、FIT 导入和失败安全 | **通过（离线集成）** | 独立 21 项测试通过；使用真实 SDK、实际 OAuth 请求准备及刷新实现，仅替换 HTTP 传输；真实 FIT 解码并落入合成 SQLite。 |
| T3：安装一致性、后端/前端检查、默认启动合同 | **通过** | 包及 Schema 36 个文件与源码逐字节一致；规定检查均通过。 |
| 真实 Garmin 服务端认证、刷新、下载成功链路 | **无法判断** | 本轮禁止真实 Garmin 请求，无实服务证据；离线通过不能替代。 |
| 真实 AI 功能 | **未运行，不作通过结论** | AI 暂停；全量 pytest 中既有 fake AI 单测不等于真实 Provider 验证。 |

未发现 RV-001/RV-002 在上述受测范围内的阻断缺陷。**不据此宣告整体功能交付或真实 Garmin 联调完成。**

## 受审版本、环境与只读约束

- 完整阅读任务材料、`AGENTS.md`、Validator 模板和 `source/README.md`；未阅读 Developer 输出、历史 Validator 裁决、PLAN 进度或旧对话。
- 分支：`work/adhoc-0031-local-web-system`。
- HEAD：`a5893ac6eb8295cd8a60d8f2537bc213d1412885`，加本轮开始时全部公开 source 未提交内容。
- 检查了当前 diff、新增隐私模块、Garmin 同步、相关测试、默认 Playwright 配置、前端 App、Web 服务、合成启动夹具及打包配置。
- 冻结：公开 source 的 tracked/untracked 非忽略文件集合共 **78 个**；before/after 集合及 SHA256 完全相同，**0 个变化**。未读取私人 states。
- 只新建本轮证据/临时测试、仓库外自有环境及正常忽略构建产物；未修改 source、协调记录或正式数据，未提交/暂存/推送。
- Python **3.12.13**、uv **0.12.3**、Node **26.5.0**、npm **11.17.0**。
- 新建仓库外独立环境，目录名含 `python environment`；按锁文件 `--no-editable` 安装。`direct_url.json` 无 editable 标志，产品导入来自该环境。36 个产品/Schema 文件与当前源码字节匹配，排除了旧 wheel。
- SDK：`garminconnect 0.2.40`、`garth 0.6.3`、`garmin-fit-sdk 21.214.0`、`jsonschema 4.26.0`。
- 浏览器：**系统 Google Chrome 152.0.7977.83**，Playwright **1.63.0**，通道 `chrome`，headless；不是随附 Chromium。默认入口启动进程和独立浏览器 `browser.version()` 双重记录。
- 8080 开始及结束均无监听；未借用已有实例，仅清理本轮自有服务和浏览器进程。

以下 `E/` 统一指 `exec-plans/evidence/ADHOC-0032/rv-fix-validator/`。完整文件哈希清单见 `E/evidence-index.json`；冻结与环境见 `E/source-before.json`、`E/source-after.json`、`E/freeze-result.json`、`E/environment.json`、`E/installed-consistency.json`。

## 独立场景与实际结果

### RV-001 与 Garmin 关联正常回归

独立脚本：`E/test_independent_garmin.py`；最终输出：`E/independent-garmin-final.log`，**21 passed，退出 0**。测试阻断 socket 连接及未替换的 HTTP 传输，断言无意外网络尝试。

| 类型 | 输入/操作及预期 | 实际结果 |
|---|---|---|
| 采集阳性对照 | 裸调用真实 SDK，用含短合成秘密的对象作为 `oauth_token`；应能采集原始 SDK 失败日志 | WARNING 采集级别下确实取得含标记的 ERROR/异常日志；仅在内存核验并清空，证明不是“没有记录日志所以通过” |
| RV-001 复现边界 | 临时目录 `oauth1_token.json` 的 `oauth_token` 为对象；从 `run_real_garmin_sync` 和构造入口进入真实 SDK 加载 | 受控返回 `EXTERNAL_SERVICE_FAILED`；日志仍有 ERROR 信号，但原始参数、异常与堆栈被安全消息替代；返回/控制台/格式化 traceback/完整日志属性无标记；未建业务数据库 |
| 其他敏感字段 | 目录和 base64 tokenstore 两种形状，分别让 OAuth1 token/secret、OAuth2 access/refresh token 类型错误，共 8 例 | 全部受控失败且无合成秘密外泄 |
| 配置错误 | `expires_in` 为合成秘密字符串、DI token 或 domain 为错误对象 | 受控 `DATA_INVALID`，无 traceback/返回/日志泄露 |
| HTTP 错误 | 真实 SDK 列活动/下载；合成 401、429、500 响应，reason/body 携带标记 | 分别映射 `AUTH_REFRESH_REQUIRED`、`RESOURCE_LIMIT`、`EXTERNAL_SERVICE_FAILED`；6 例均安全；实际 PreparedRequest 带预期认证头 |
| 正常 DI/正常 tokenstore | 构造真实客户端，实际 SDK 列举两页、下载 ZIP、真实 FIT 解析和导入 | 每种模式 1 场活动、4 条 records；落盘 FIT 字节与输入一致，同步状态无标记 |
| 过期 tokenstore 刷新 | 过期 OAuth2，保留 `garth.sso.exchange`、OAuth 签名、请求准备和解析，仅合成传输响应 | 确实访问合成 consumer/exchange 分支，刷新后列举/下载/真实 FIT 导入成功；不是仅替换 refresh 函数返回成功 |
| 未到期回归 | 同一实例成功后 1 分钟再次调用 | 返回成功但 `due=false`，不再次列活动或下载 |

补充代码及既有测试核对：隐私边界位于 SDK 登录、配置、列举、下载调用；当前异常对外抑制上游异常链。全量单测亦覆盖嵌套日志边界、退出恢复、其他线程和无关模块诊断不受影响。上述结论只针对当前锁定依赖，不承诺未来 SDK 新日志行为。

### RV-002：独立命令探针及真实默认启动

独立脚本 `E/probe_environment.mjs` **导入当前配置并执行原 webServer.command**，没有复制替代配置。PATH 中设置会明确报错的 uv/global Python 探针，保证无隐式安装/解释器回退。

| 类型 | 输入/预期 | 实际结果 |
|---|---|---|
| 缺少变量 | 未设置 `UV_PROJECT_ENVIRONMENT`；应明确失败 | 退出 **127**，提示设置该变量；预期错误场景通过 |
| 缺少解释器 | 指定环境不存在 `bin/python`；不得回退 | 退出 **127**，明确找不到指定解释器 |
| 不可执行解释器 | `bin/python` 无执行权限 | 退出 **126**，明确 Permission denied |
| 路径边界 | 环境路径同时含空格和单引号 | 退出 **0**；记录的解释器、工作目录、`-m tests.e2e_support.serve_web` 参数完全匹配调用者指定值 |
| 正常集成入口 | 指定本轮非 editable Python 3.12 环境，运行默认 `npm run e2e` | **2 passed，退出 0**；进程实证为该环境的 `bin/python`；实际系统 Chrome 启动并执行 DOM 断言 |

证据：`E/environment-probes.json`、`E/default-e2e.log`、`E/default-e2e-process.json`。实际默认命令只通过 CLI 将 reporter/output 指向本轮目录，未修改 testDir、webServer、通道或配置，没有覆盖历史证据。

### T1：系统 Chrome 独立功能场景

脚本 `E/independent_browser.mjs` 仍使用当前默认 webServer 原命令启动本轮合成实例；另开系统 Chrome。正常场景走真实 FastAPI/SQLite；错误、加载、竞态及特殊文本通过浏览器路由精确注入，不冒充服务端真实故障。

| 类型 | 场景与关键 DOM/行为断言 | 结果/证据前缀 |
|---|---|---|
| 正常/搜索边界 | 状态卡、服务卡、活动倒序、点击切换详情、活动报告和周总结；运动类型/完整 ID/FIT 相对路径搜索；前后空格、Enter、中文无匹配、SQL 样式文本；200 字符正常空态、201 字符明确 INVALID_ARGUMENT；空白及清空恢复列表和默认详情 | 通过，`ui-normal-boundaries` |
| 加载 | 暂缓状态响应，确实观察“加载中…”及读取同步状态；释放后正常列表 | 通过，`ui-loading` |
| 空态 | 合成空列表、空周总结、尚未同步/成功、数据库未找到 | 通过，`ui-empty` |
| 网络失败/恢复 | 中断状态请求，显示 Failed to fetch、结束加载且列表为空；恢复网络后搜索成功并清除错误 | 通过，`ui-network-recovery` |
| API envelope 失败/恢复 | 周总结返回 503 失败 envelope，显示明确错误码；恢复后正常搜索 | 通过，`ui-envelope-recovery` |
| 非法响应 | 活动接口返回坏 JSON，显示错误、结束加载、不显示活动 | 通过，`ui-malformed-json` |
| 请求竞态 | 旧 running 成功响应晚于新 cycling；旧结果不能覆盖新列表和详情 | 通过，`ui-race-old-success` |
| 请求竞态 | 旧 running 错误响应晚于新 cycling；旧错误不能覆盖新成功结果 | 通过，`ui-race-old-failure` |
| 全文与安全文本 | 活动/周总结分别注入超过 4096 字的全文，含 img/script；逐字 `textContent` 完整相等，无生成 img/script 节点，无脚本效果 | 通过，`ui-full-report-text` |
| API/SPA 分离 | 不存在 API、错误分页和不存在活动返回 JSON 失败 envelope；不存在 SPA 路由返回 HTML 200 并显示应用 | 通过，`api-spa-separation` |

以上 **10 项通过，退出 0**。每项均检查无 pageerror、无业务页外网请求、无 states/FIT/数据库直接请求。结果见 `E/independent-browser-results.json`、`E/independent-browser-final.log`；各前缀对应 `.dom.txt` 和 `.png`。加载/竞态中间状态由脚本实际断言，截图保存最终状态；不是把最终截图当作中间过程证明。

## 规定检查与执行记录

表中 `$P` 表示指定仓库外环境的 `bin/python`，不是系统 Python。

| 工作目录 | 实际命令/操作 | 退出与关键结果 | 证据 |
|---|---|---|---|
| 根目录 | `UV_PROJECT_ENVIRONMENT=… uv sync --project source --python 3.12 --locked --extra dev --no-editable` | 0；新建独立 3.12.13 环境，47 包安装 | `E/install.log` |
| 根目录 | 读取安装元数据并逐字节比对包/Schema | 0；36 文件一致，非 editable | `E/installed-consistency.json` |
| source | `$P -m pytest tests -q -p no:cacheprovider` | 0；**214 passed**，2 条依赖弃用警告 | `E/pytest.log` |
| source | `$P -m ruff check --no-cache .` | 0；All checks passed | `E/ruff.log` |
| source | `$P -m mypy -p trainlab -p tests --no-incremental` | 0；56 source files 无错误 | `E/mypy.log` |
| source | `$P -m compileall -q skills schemas tests` | 0 | `E/compileall.log` |
| source | `$P -m trainlab.check_architecture` | 0；architecture and public Schema checks passed | `E/architecture.log` |
| 根目录 | `git diff --check` | 0 | `E/diff-check.log` |
| source/frontend | `npm ci` | 0；0 vulnerabilities；有 fsevents install-script 授权提示，未改全局配置 | `E/npm-ci.log` |
| source/frontend | `npm run lint` | 0 | `E/npm-lint.log` |
| source/frontend | `npm run typecheck` | 0 | `E/npm-typecheck.log` |
| source/frontend | `npm test` | 0；**11 tests passed** | `E/npm-test.log` |
| source/frontend | `npm run build` | 0；生成忽略的静态资源 | `E/npm-build.log` |
| 根目录 | `node exec-plans/evidence/ADHOC-0032/rv-fix-validator/probe_environment.mjs` | 0；4 类启动环境探针通过，错误场景预期退出非零 | `E/environment-probes.json` |
| source/frontend | `npm run e2e -- --reporter=list --output=../../exec-plans/evidence/ADHOC-0032/rv-fix-validator/default-e2e-results`，设置指定环境及 `DEBUG=pw:browser` | 0；**2 passed**，默认配置真实启动 | `E/default-e2e.log` |
| source | `$P -m pytest ../exec-plans/evidence/ADHOC-0032/rv-fix-validator/test_independent_garmin.py -v -p no:cacheprovider` | 最终 0；**21 passed** | `E/independent-garmin-final.log` |
| 根目录 | `node exec-plans/evidence/ADHOC-0032/rv-fix-validator/independent_browser.mjs`，设置指定环境 | 0；系统 Chrome **10 场景通过** | `E/independent-browser-final.log` |
| 根目录 | 冻结 SHA256/文件集合比对、`git diff --cached --name-only`、8080 监听核对 | 0 个 source 变化、0 个暂存文件、无残留监听 | `E/freeze-result.json`、`E/environment.json` |

### 未隐藏的验证辅助错误

1. 前端检查辅助脚本首次误用系统 `python3`，导入 `tomllib` 失败，退出 1，尚未执行 npm。随后改用已经核实的指定 Python 3.12 直接执行，同一前端检查全部通过。不是产品环境故障或安装模式变更。
2. 独立 Garmin 测试初版 **18 passed / 2 failed**：临时 HTTP 夹具将 user-settings 请求提前匹配为 profile，返回缺少 `userData` 的合成响应。核对实际 SDK URL 后，仅调整本轮临时夹具两条分支顺序；产品和断言未改。随后 20 项全过，再增加日志阳性对照后 21 项全过。首次失败日志完整保留。
3. Chrome 输出存在 macOS 显示链接/allocator 诊断；实际浏览器、DOM 断言、进程退出均正常。pytest 的两条弃用警告和 npm 提示保留，没有改配置隐藏。

说明见 `E/harness-notes.json`；首次测试日志 `E/independent-garmin.log`、复核日志 `E/independent-garmin-v2.log` 均保留。

## 问题表、证据缺口和停止说明

| 编号 | 本轮判断 | 对应要求/剩余事项 |
|---|---|---|
| RV-001 | 受测范围通过，无阻断复现 | 必须保持锁定 SDK；依赖升级或新的日志出口需要重新验证。 |
| RV-002 | 通过，无阻断复现 | 使用者仍须按 README 预先安装非 editable 包；默认 E2E 不会替调用者安装或刷新旧包。 |
| 真实 Garmin 成功链路 | 无法判断 | 本轮无真实凭据、服务端认证/刷新/下载证据，不能推断 DI 字段映射已获真实服务接受。 |
| 真实 AI / 正式调度 | 未验证 | 暂停/禁止范围，未登录、未处理 MFA、未运行正式调度或真实 Provider。 |

没有新增已确认的产品缺陷编号。本轮只读复验到此结束；真实服务证据缺口提交主 Agent 处理，**不等待追加消息、不继续扩大验证、不建议用合成结果代替真实验收**。主 Agent 仍须亲自完成适用的完整功能验收和交付决定。
