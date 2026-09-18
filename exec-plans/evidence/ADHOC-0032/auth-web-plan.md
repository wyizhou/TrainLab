# ADHOC-0032：Garmin Web GUI 认证增量规划（供主 Agent 审核）

## 1. 目标、范围与已核对事实

本次为全新、只读 Planner 的规划调整。依据 `exec-plans/evidence/ADHOC-0032/auth-web-planner-task.md`、`AGENTS.md`、`subagent-templates/planner.md`、当前执行计划及真实源码，覆盖 **GUI32-01～06**，承接 AU32-01～06。

**交付必须是能实际操作的 Web 页面：选择国际区/中国区，输入账号密码，需要时提交验证码，看到认证保存及维护状态。CLI 不再是用户完成认证的前置条件。** Web 显式运行期间自动协调认证维护；退出、休眠期间不保证刷新。不加系统守护、不启用 AI 或活动同步调度，不新增账户管理平台。

本报告只是规划，未实施或验收 GUI。没有读取正式 `states/`，没有真实登录、下载或启动正式服务，没有修改产品、测试、配置、规则及协调记录。

### 基线与材料

- 工作目录为项目根 `.`，分支 `work/adhoc-0031-local-web-system`；HEAD 为 `a5893ac6eb8295cd8a60d8f2537bc213d1412885`，加全部既有未提交工作。暂存区为空。
- 实际逐文件核对 `exec-plans/evidence/ADHOC-0032/auth-maintenance-parent/source-after.json` 的 **96 个 source 文件**及 `references-after.json` 的 **4 个资料文件**，哈希全部相符。本次没有回退、提交、推送或切分支。
- 已完整阅读本次派发、根规则、Planner 模板、总计划、当前执行计划、旧认证规划及审核；读取当前认证、Web、前端和相关测试/架构合同。项目相关目录未发现额外 `AGENTS.md`。
- 项目 `skills/` 未发现 `SKILL.md`；检索全局技能目录，现有 Garmin 技能针对训练计划下发，不适用于本次认证 GUI；未采用旧编排技能或依赖目录内技能。

### 真实接线与缺口

| 实际位置 | 当前行为 | 本次需要补的衔接 |
| --- | --- | --- |
| `source/frontend/src/App.tsx` | 只有仪表盘；状态、活动、周报用 `Promise.all` 加载，任一路由失败会使该组加载失败；没有认证面板 | 认证面板独立挂载、独立请求及状态机，不能等仪表盘/数据库/AI 成功后才显示 |
| `source/frontend/src/contracts.ts` | 10 条业务路由；`staticPolicy.startsBackgroundJobs=false` | 同批增加认证路由和 DTO；改成真实的生命周期合同，不能继续写“完全无后台任务” |
| `source/skills/local-web/scripts/server.py` | `create_app()` 无 lifespan、无认证 HTTP 路由；健康合同写死后台任务为 false；没有 Host/会话/CSRF 保护 | 新增独立认证路由、安全门和生命周期模块；`server.py` 仅接线，认证路由必须在 `/api/{_path:path}` 兜底及 SPA 挂载之前注册 |
| `garmin_auth.py` | 一个 `GarminAuthService` 持有一个内存 MFA 流程；已有 begin/submit/cancel/status/maintain；服务线程锁与仓储进程锁 | 同一 Web 进程长期复用同一所有者，不能每个请求重新创建；HTTP 自己绑定浏览器会话，不能直接把通用 `flow_id` 当全局授权 |
| `GarminAuthService.status()` | 本地 load 验证、返回保存状态和真实期限，始终 `server_verified=false`；不返回区域，不保留上次维护错误 | 补安全区域字段和所有者提供的内部代次观察；维护运行结果由 Web 运行态保存，防止本地 load 成功把已知撤销/失败“洗成正常” |
| `garmin_auth_store.py` | 唯一代次仓储、原子指针、0700/0600、旧配置备份、线程及 `flock` 互斥 | HTTP/运行态不得绕过它读写 token。注意 `status()` 的锁可能创建目录/锁文件，不能声称每次状态查询绝对零磁盘写入；它仍不联网、不刷新 |
| `garmin_auth_maintenance.py` | 阻塞式显式循环，成功最多等 60 秒，临时失败最多 3 次、间隔 5/10 秒，无 Web 停止信号和运行态 | 复用维护操作与纯调度策略，增加可唤醒/停止的 Web 协调器；不能直接在异步 lifespan 内调用无限循环 |
| `garmin_sync.py` | 同步经所有者租约认证；`run_real_garmin_sync()` 为调用创建独立所有者，仓储锁跨进程协调 | 不新增 Web 同步调度；保留当前所有者/锁/代次合同及同步回归，不误称 CLI 与 Web 共用同一个 Python 对象 |
| `source/tests/e2e_support/serve_web.py` | 仅合成仪表盘服务入口，没有产品启动命令或 SDK 离线传输接线 | 新增正式本机 Web 启动入口，测试宿主接相同产品工厂与 lifespan，不把该合成脚本当用户入口 |
| 当前 Playwright | 系统 Chrome、8080、拒绝借用旧服务；默认两项，活动错误场景使用 `route.fulfill` | 原测试保留；新认证成功/失败链必须经过真实 HTTP、所有者及实际锁定 SDK，只替换外部传输 |

### 锁定库及阻塞行为核对

在自有仓库外 Python 3.12.13 环境，使用锁文件**离线**导出并安装依赖，实际为 `garminconnect 0.2.40`、`garth 0.6.3`、`FastAPI 0.141.1`、`Starlette 1.6.0`、`AnyIO 4.15.1`，未安装或导入产品。

- 读取锁定 `Garmin.login/resume_login` 与 `garth.sso`：普通登录和 MFA 都走同步 HTTP；`is_cn` 实际控制 `garmin.com/garmin.cn`；MFA 返回含活 client 的上下文，不能序列化到浏览器。`resume_login` 交换后还会取 profile/settings，后续失败不能宣称保存成功。
- 锁定 SDK 的源码与现有产品适配一致：刷新走 OAuth1 交换、更新客户端属性，并非把 `refresh_oauth2()` 的返回值当令牌。产品已设置单次请求 15 秒和零自动重试，consumer 首次请求也受覆盖。**15 秒是单次 HTTP 超时，不是完整登录或关服的总时限。**
- 实际小探针确认：FastAPI 构造不执行 lifespan；进入/退出 lifespan 才调用 start/stop；同步路由由工作线程执行。取消 `asyncio.to_thread` 的等待并不会终止其线程，因此不能“取消任务后马上 close 所有者”，也不能让仍在写仓储的线程逃出生命周期。

## 2. 调整理由与稳定增量拆解

保留 G1～G3、0032-T1～T9 及原证据。旧 T4～T8 完成的是认证模块/CLI；新增 GUI、HTTP 安全和 Web 维护不是对旧任务补一个“已完成”标签。建议只在现有执行计划补 **G4、0032-T10～T15**，初始均为 `[plan]`。

| 稳定任务 / 阶段 | 对应目标；输入 → 输出与落点 | 依赖、接口和错误边界 | 检查方法及预期 |
| --- | --- | --- | --- |
| **0032-T10 / G4：所有者安全观察与 Web 维护生命周期** | GUI32-03/04/05，AU32-03～05；现有所有者/维护器 → 区域和内部代次观察、可停止的 Web 协调器及真实启动命令。落点：共享包 `garmin_auth.py`、必要的维护纯策略；新增 `source/skills/local-web/scripts/auth_runtime.py`、`cli.py`，`server.py` 小范围接线；更新 README 和生命周期合同 | 先实施；只由所有者接触仓储。Web 一个所有者、一条维护调度链；无导入/构造联网。单次 SDK 操作不阻塞事件循环，关闭须等待在途操作后清理；不启动 AI/同步调度。内部代次标识不进浏览器 | 新增 `source/tests/web/test_auth_lifecycle.py` 及所有者回归：到期前刷新、保存/重启、手动介入/有限退避、CLI 更新后恢复、无构造副作用、关服/取消不留线程。产品启动帮助及合成子进程启动可用 |
| **0032-T11 / G4：安全认证 HTTP 与会话合同** | GUI32-01～05；T10 运行态 → 第3节真实路由、严格 DTO、固定错误壳、内存会话绑定。新增 `auth_routes.py`、`auth_security.py`；补 `contracts/web.py` 与路由表、所有权测试 | T10；只调用所有者/运行态，不 import SDK/仓储；先检查安全门再读敏感 body 或调用服务。区域仅 com/cn；密码/MFA 不落盘；其他浏览器不能继续/取消当前 MFA。不借此修全局 AI/Context 错误 | 新增 `test_auth_http.py`、`test_auth_security.py`：正常/错误 HTTP、会话/CSRF/Host、重复/并发/旧请求、请求限额和脱敏；失败前 SDK 调用数为零，成功必须实际保存 |
| **0032-T12 / G4：两区登录/2FA 独立 React 面板** | GUI32-01/02/03/05；T11 DTO → 独立 `GarminAuthPanel.tsx`、认证 API/状态模型及必要样式，`App.tsx` 仅挂载。更新 `contracts.ts`，不把全部逻辑塞进 App | T11 合同确定后；认证加载与仪表盘解耦。账号/密码/验证码仅本次内存提交；不自动重放。取消只取消流程，不删除既有令牌；重启/会话失效提示重来 | 面板状态及渲染测试；无库/无 AI、两区、普通/MFA、忙碌/过期/重来、刷新恢复、失败可理解；输入有 label、密码遮挡、状态可读，不吞掉错误 |
| **0032-T13 / G4：真实 HTTP＋锁定 SDK 的 Chrome 验收宿主** | GUI32-06及所有目标；T10～T12 → 测试专用离线传输、受控时钟/子进程重启、Chrome 场景和隐私证据。落点 `source/tests/e2e_support/`、`source/frontend/tests/e2e/`、Playwright 配置、相关 Web/合同测试 | T10～T12；生产不得携带测试控制路由、固定成功返回或传输替身。替换外部 HTTP，不替换认证业务函数；服务子进程也阻断非授权外部 socket。保留原仪表盘强断言 | 第6节矩阵；系统 Chrome 操作真实页面，核 SDK 域名/请求次数、持久代次和重启状态。前端先构建，再完整回归；先安全合成验收，不能让用户试半成品 |
| **0032-T14 / G4：固定完整副本、全新独立验证** | GUI32-01～06；开发自查版本 → 独立正常/错误/边界/完整 Chrome 证据 | T10～T13 自查结束；固定 source＋references＋客观协调视图，冻结受审内容。只给要求、审核拆解、当前材料和客观异常；不给旧裁决或开发辩护 | 全新 Validator 独立场景及实际 Chrome；安装产物匹配、所有者边界、隐私、生命周期、全部适用门。未运行/环境阻塞记“无法判断”，新问题用 GUI32-V1-xxx |
| **0032-T15 / G4：主 Agent 实际 Chrome 验收与 GUI 交付** | GUI32-01～06；独立通过的固定版本 → 主 Agent 亲自用系统 Chrome 复核、产品启动说明和可用本机页面；随后由用户在安全 GUI 本人输入真实认证 | T14；不让用户把秘密交聊天，不要求另开 CLI 登录。真实认证/维护/同步成功仍归原 T9/T2，GUI 离线交付不能替代它们 | 主 Agent 按矩阵复跑完整操作及关键错误、重启、安全场景，核版本/构建/进程清理；确认后交用户页面。真实请求按原授权继续并单列收据，没有实服务证据不完成 T2/T9/G2/G3 |

实施顺序：**T10 → T11 → T12 → T13 → T14 → T15**；T10～T13 每项同时补测试，同一时刻只有一个 Developer 写入。本报告不调度任何角色。

主 Agent 还需把原 **T9 的后续真实操作由“本人终端登录”改接“本人 Web GUI 登录”**，保留编号、已做离线证据及未完成状态；不另设重复真实验收任务。旧规划/审核原文保留为历史，不抹去当时不做 Web 的范围事实。

## 3. 前后端接口与安全会话合同

以下为可直接实施的最小接口建议；名称在主 Agent 审核时一次确定，前后端及测试同批保持一致。所有响应沿用 `ok/data/error`，成功 `error=null`，失败 `data=null`。

### 3.1 HTTP 路由

统一前缀 `/api/garmin/auth`，没有秘密或流程标识的 URL 参数。

| 方法/后缀 | 请求 | 安全返回与行为 |
| --- | --- | --- |
| `GET /session` | 同源自定义头 `X-TrainLab-GUI: 1`；可带已有会话 cookie | 新建或复用内存浏览器会话；设置不透明 cookie，返回内存 CSRF 值、会话期限及 `session_replaced`。未知旧 cookie 不恢复旧 MFA；不读取认证仓储、不联网。有效会话刷新页面时不无故轮换 CSRF，避免破坏同会话标签页 |
| `GET /status` | 同源自定义头＋有效会话 cookie | 第3.2节状态 DTO；显式调用本地所有者观察，不因 GET 刷新认证或发起登录。只返回当前会话的待 MFA 状态；另一会话最多看到“其他操作占用” |
| `POST /login` | `{region:"com"|"cn", username:string, password:string}`；会话＋CSRF | `com → is_cn=False`，`cn → True`，无账号推断/失败自动换区。普通成功返回 `authenticated/saved`；待验证码返回新的 Web `attempt_id`、期限和区域。所有者真正 `flow_id` 留服务端 |
| `POST /mfa` | `{attempt_id:string, code:string}`；会话＋CSRF | 必须同时匹配当前会话、当前尝试、活跃期限；服务端取内部 flow 调 `submit_mfa`。成功保存后返回 authenticated；重复/外会话/旧尝试不能发 SDK 请求 |
| `POST /cancel` | `{attempt_id:string}`；会话＋CSRF | 只取消该会话对应的当前等待流程，释放 SDK 上下文；同一次已取消可幂等。旧尝试不能取消更新的流程；不撤销或删除已保存认证 |
| `POST /maintenance/retry` | 空对象；会话＋CSRF | 仅显式解除当前维护的临时失败暂停并安排一次按真实期限检查；不提供 `force`/伪造时间/文件路径。人工验证仍提示登录；运行中返回 busy，不创建第二条循环。用于断网恢复后在 GUI 操作，无需 CLI |

普通 login/MFA 返回时已经完成该步 SDK 操作和必要持久化，不虚构异步“成功任务”。页面等待期间可查状态；不要引入通用任务队列。对已经提交但 HTTP 断开的操作，用户先查状态，不自动重发账号密码或验证码。

请求体必须是严格 JSON 对象，禁止额外字段和隐式布尔/数字转换；`region` 仅上述枚举。建议请求体上限 16 KiB，账号/密码/验证码及句柄分别有合理长度上限，空白码本地拒绝；密码不 trim 或截断，不假设所有 MFA 都是六位数字。这些是实现安全上限，不是用户新增的业务要求；上限在前后端及测试一致。body 限制覆盖分块请求，不只信 Content-Length。

### 3.2 状态 DTO：分开“保存”“流程”“维护”

不能用一个 `authenticated: true` 包住所有含义。建议返回三个相互独立的小对象：

- `stored`：`state`（missing/legacy/stored/invalid/unavailable）、`saved`（true/false；无法检查时 null）、`region`（com/cn/null）、`expires_at_utc`、`refresh_due_at_utc`、`observed_at_utc`、`stale`、`server_verified:false`、固定 `reason`。期限只从所有者实际 SDK 数据得到；失效或未知不补未来值。访问令牌过期不等于底层 OAuth1 必然失效，也不自动等同人工登录。
- `login`：当前会话的 idle/submitting/needs_mfa/verifying/cancelled/expired/failed/completed；必要时带当前 Web `attempt_id`、MFA 截止时刻和所选区域。其他会话只给 busy_elsewhere，不给句柄、区域、账号或截止细节。attempt_id 是防旧请求误操作的随机标识，不是 Garmin token，也不能单独授权。
- `maintenance`：`enabled`、`state`（starting/scheduled/running/retry_wait/paused/manual_required/blocked/stopping）、上次尝试时间、**上次真正刷新成功**时间、下一次计划检查时间、连续失败次数、固定结果/原因。`unchanged` 只能记本地检查成功，不能刷新“在线成功时间”。启动后尚未检查、正在操作而仅能拿到缓存时必须明确，不把缓存冒充实时结果。

`status()` 当前缺区域，建议由所有者在已验证加载的 SDK 上读 `is_cn` 转安全枚举，并增加仅供运行态使用的内部代次观察。可采用 `observe_status()` 返回“安全状态＋不透明代次标识”，保留原 `status()` 兼容；HTTP 白名单去掉代次标识，禁止由 HTTP 读取 `garmin.json` 求代次。该标识只用于识别 CLI/同步是否换了认证，不能是 token 内容或浏览器可用的凭据。

已知服务端撤销/需验证的结果要锁定到当时代次：后续本地 load 成功不能把 `manual_required` 清掉。检测到新代次后重新评估、取消旧流程及旧结果；只改 UI 区域选择不改变已保存区域。仓储损坏/环境冲突显示 blocked 和固定原因，不承诺“再登录一次”能修好所有本地错误，也不要求用户手写 token。

### 3.3 浏览器会话及安全门

1. **本机单进程服务，不是多用户账户系统。** 产品入口固定绑定 `127.0.0.1`，默认端口 8080；推荐只接受规范 `127.0.0.1:8080` Host，页面使用同一 Origin。不为了 `localhost`、Vite 代理或远程访问放宽为任意域/任意端口；需要支持别名时须显式白名单并独立验证。Host 校验应用于全站，拒绝 DNS rebinding 的任意 Host；不信请求提供的转发头，产品启动不启用反向代理信任。
2. 会话用密码学随机不透明 cookie，服务器只在内存保存映射；`HttpOnly; SameSite=Strict; Path=/api/garmin/auth`，不设 Domain、不设持久 Expires/Max-Age。当前是回环 HTTP，不宣称具有公网 HTTPS cookie 的安全性质，也不使用会被浏览器拒绝的 `__Host-` 命名组合。建议闲置 30 分钟失效、最多 32 个活会话，到期/关闭清理；待 MFA 仍以原默认 5 分钟单调时钟为准，刷新页面不延长。
3. 状态/会话 GET 要求自定义头；检查存在的 Origin、Fetch Metadata，拒绝 cross-site，以及跨端口的 same-site 非同源来源。POST **要求精确 Origin＋有效 cookie＋会话绑定的 `X-CSRF-Token`**，拒绝缺失/null/不匹配 Origin；常量时间比较随机值。不得只靠 SameSite，不能宽 CORS；不放行跨源预检。会话/CSRF 由服务器生成，不接受客户端自行指定会话 ID。
4. 安全验证、body 限制在 SDK 调用之前完成；外会话即使知道 A 的 attempt_id，也不能提交或取消 A。有效会话下同一次重复提交最多执行一次，正在操作立即 busy，不排无界队列；同浏览器标签页共享 cookie，但旧 attempt_id 不能误伤新流程。
5. 每个 Web 运行实例最多一个活跃登录流程。服务端保留 `session → attempt → owner flow` 映射，客户端只收自己的 Web attempt。会话失效时清理其待 MFA；后端重启则所有会话/CSRF/待 MFA 失效，已保存认证不丢。bootstrap 收到旧未知 cookie 时，明确返回“服务重启或会话已失效，未完成验证请重新开始”。
6. 认证响应统一 `Cache-Control: no-store`，页面设置禁止被框架嵌入和 `Referrer-Policy: no-referrer`。前端不使用 localStorage/sessionStorage/IndexedDB/服务工作线程保存认证输入、OAuth、CSRF 或流程上下文；cookie 是明确允许的不透明浏览器会话标识，**不是 Garmin OAuth**。输入在发起当前提交后清空，finally 释放请求引用；不承诺运行时字符串可物理擦除。
7. 不记录 body、cookie、CSRF、账号、密码、验证码、SDK 上下文/原异常。产品启动关闭含请求目标的默认 access log，或只输出固定路由模板和状态码；不能把 query 中的恶意输入写日志。不得向浏览器重抛异常正文、路径或 SDK HTML。测试/真实验收也不把敏感请求带进截图、trace、HAR 或公开报告。
8. 现有 `garmin_privacy.py` 的保护范围是 SDK/HTTP 调用，**不是**新路由自动安全的证据。认证路由需要自己的安全异常边界，包含校验、序列化、存储/未知异常及 shutdown 错误；采用固定信息并保留安全原因枚举。

### 3.4 错误与 HTTP 映射

复用现有 ErrorCode，不批量重写所有业务错误。认证边界建议：

| 场景 | HTTP / code | 行为 |
| --- | --- | --- |
| JSON/字段/区域/旧句柄不合法 | 400 / INVALID_ARGUMENT | 固定 message/reason，无输入回显 |
| Host、Origin、CSRF 或外会话越权 | 403 / TOOL_NOT_ALLOWED | 固定 `request_not_allowed`，不泄露某句柄是否存在 |
| 会话过期/重启后的旧会话 | 409 / SOURCE_CONFLICT | 固定 `browser_session_expired`，引导重新 bootstrap，不自动重放提交 |
| 本地认证操作/进程锁忙 | 409 / RUN_BUSY | 旧保存状态不丢，按钮有反馈 |
| 存储代次变化 | 409 / SOURCE_CONFLICT | 旧 MFA 失效，重新开始；不覆盖新代次 |
| 需人工登录/未知验证码未完成 | 409 / AUTH_REFRESH_REQUIRED | 沿用所有者安全原因，不能都声称“密码或验证码错误” |
| MFA 过期或 SDK 超时 | 504 / TIMEOUT | 区分安全 reason；SDK 提交后异常的 MFA 不重放 |
| 本地 body 超限 | 413 / RESOURCE_LIMIT | 拒绝并不调用 SDK |
| 上游限流 | 429 / RESOURCE_LIMIT | 认证路由可按 reason 局部覆盖 HTTP；现有公共 RESOURCE_LIMIT=413 不全局改义 |
| 存储损坏/环境冲突/外部失败 | 422 / DATA_INVALID、503 / CONFIG_UNAVAILABLE、502 / EXTERNAL_SERVICE_FAILED | 固定安全返回；保存未确认不能显示成功 |

当前全局 ValueError 会回传 `str(exc)`，还存在既有 Context 纯文本 500。新增安全门及认证异常处理只覆盖认证前缀；如必须在 `server.py` 的公共 handler 加认证分支，限定该分支且补回归。**本轮不把 AU32-V1-002/003 隐藏、跳过或借机修复。**

## 4. 最小 Web 维护生命周期与并发合同

### 4.1 产品入口与启动边界

建议新增产品命令（实施前不存在）：

```bash
# 项目根；先按 source/README.md 安装锁定的仓库外非 editable 环境并构建前端
python -m trainlab.local_web.cli --instance-root . --project-root .
```

- 使用现有 setuptools 的 `trainlab.local_web` 映射，新增模块即可；不加新的实现根、运行时 sys.path 补丁或 SDK 升级。
- 产品 CLI 启动 `create_app(WebAppSettings(...))`，Uvicorn **一个 worker、不开 reload**，绑定 127.0.0.1:8080，打印不含秘密的页面地址和停服方式。只能通过受信启动参数指定实例，HTTP 不能指定路径。
- factory/模块导入只组装对象、注册路由，不读私人认证、不启动线程/定时器、不联网。真正进入 ASGI lifespan 才创建该次运行的所有者、内存会话和维护协调器；退出 lifespan 负责清理。
- 显式启动这个产品 Web 服务即运行认证维护，不要求另跑 `maintain`。测试可显式禁用维护以测旧路由，但这些禁用测试不能算 GUI32-04 证据；新的 E2E 必须运行启用维护的真实 lifespan。
- 无数据库/无 AI 配置仍能启动并显示认证面板。前端构建缺失时启动给固定可操作错误，不意外挂载项目根或 states；AI 仍不配置、不实调用。

### 4.2 最小协调器

复用 `maintain_once()`，维护提前量仍由 SDK/所有者决定。建议从现维护器提取少量**纯延迟/退避策略**供 CLI 与 Web 共享，不复制 token 或提交规则；CLI 原行为保持。

- 仅一条异步协调循环，等候用可唤醒事件；本地状态读取和同步 SDK 调用放到工作线程。使用非阻塞操作门控制一个在途认证操作，忙时返回 busy，不让密码请求在无界线程池排队。状态查询可暂回有时间戳的安全缓存＋busy/stale；不能为了状态刷新阻塞整个站点。
- 启动先本地观察；missing/legacy/manual/blocked 不试密码、不持续联网，显示原因。正常保存认证按真实到期前维护点安排；等待最多 60 秒重新观察状态/时钟，允许唤醒立即重算。GET 查询本身不触发网络维护。
- 到维护点调用所有者：`unchanged` 表示未到点或已有其他进程更新；`refreshed` 必须已完成仓储提交。GUI 只在提交成功后显示刷新成功和新期限。
- TIMEOUT/限流/临时外部错误按当前策略最多连续 3 次尝试、等待 5/10 秒，之后进入 paused，不再自动发网络请求；页面给“重试维护”。RUN_BUSY 属于未执行，不称为认证失败；可以同样有界退避，持续占用时停在可见 paused，不忙循环。
- 人工验证/撤销立即停在 manual_required，不自动登录或重试 MFA；格式/环境/存储安全错误停在 blocked。轮询本地观察仍可发现 CLI/同步提交的新代次，但不能仅凭旧代次能 load 就解除 manual/paused。
- 当前 Web 登录成功或发现其他进程新代次，更新保存状态、废弃旧代次结果/流程，重新安排维护。临时故障由用户点击维护重试可重启一个有界尝试组；不提供无限自动重试开关。
- **等验证码期间不占磁盘锁。** 若既有认证到了维护点，允许维护/CLI/同步正常推进；一旦代次改变，旧挑战明确失效、提示重新开始，不让旧 MFA 覆盖新的令牌。此行为沿用现有代次保护，不能为保住 UI 等待而长期阻止必要维护。

### 4.3 关闭、断开与重启

- 停服先标记 stopping、拒绝新的变更请求并唤醒睡眠循环；停止安排下一轮。等待当前已受理的 SDK/提交操作结束，随后取消未完成的 MFA、清空 Web 会话，最后调用 owner.close；资源清理顺序必须测试。
- 不用 `asyncio.wait_for` 超时后丢弃 worker，也不在锁仍被 worker 持有时并发 close。取消 await 不是取消实际 SDK 请求。现 SDK 有逐请求超时/无重试，但完整链可含多次请求；不承诺停服一定 15 秒结束。宿主强制终止按已存在的仓储崩溃保护恢复，不能把未完成操作报告成功。
- 页面关闭/请求断开不会撤销已经到服务端的登录或保存；不自动重复。用户回来先读取状态。取消按钮保证取消**等待验证码的流程**；网络请求在途时明确“操作中，结束后可取消或重来”，按钮禁用，不能谎称撤销了已执行的认证。
- 重启后读取最后完整活动代次；浏览器旧会话与 MFA 不恢复。维护内存历史可以显示“本次服务尚未检查”，不伪造上次刷新成功。已保存认证可立即由新进程使用；尚待验证码不能冒充已保存。
- CLI/Web/同步仍共享唯一仓储规则及跨进程锁，不持有终身排他锁。多个进程可能各自等待 MFA，**当前实现并非全机只允许一个内存挑战**；最终提交用代次冲突裁决。无需引入守护进程或分布式会话库。

### 4.4 如实更新健康与前端合同

`app_contract` 表达能力/启动策略，`/api/health` 表达本次实际状态，不混为一谈。建议统一字段：

- `reads_private_state_on_import=false`；新增/明确 `starts_background_jobs_on_create=false`。
- 能力声明 `background_jobs_on_lifespan=["garmin_auth_maintenance"]`。
- 健康返回当前 `starts_background_jobs`、`auth_maintenance_enabled`、维护状态；运行循环即使因人工操作而停在本地等待，也不能继续声称整个 Web 不运行维护任务。
- 前端删除或替换误导性的静态 `startsBackgroundJobs:false`，展示后端实际维护状态；AI/活动同步自动调度仍 false。
- 后端 API_ROUTES、前端 apiRoutes、health/status 路由表、合同/前端/Chrome 测试一起更新。按本方案为原 10 条＋6 条认证路由；测试应核对精确方法/路径集合，不以降低数量断言绕过接线。

## 5. UI 状态转换与用户操作

面板入口与仪表盘并列，标题例如“Garmin 登录与认证维护”。初次打开始终有国际区(com)/中国区(cn)两个清楚选项；没有已保存区域时提示用户在页面选择，不猜测账户归属。已有保存区域可作为显示/初始选择，但用户仍可选择另一侧重新登录。

流程：

`初始化会话/读状态 → 输入区域/账号/密码 → 提交中 → 已登录并安全保存 或 等待验证码 → 验证中 → 已保存/失败需重来`。

必须可见：

- 所选区域；普通成功不出现多余验证码步骤；验证码仅服务实际要求时显示。
- 分开显示“本地保存了认证”“实际访问令牌期限”“未做本次在线核验”“维护计划/上次实际刷新结果”。不只给绿色“在线”灯。
- 网络/锁忙/限流/验证码未完成/超时/代次变化各有固定可理解提示。校验前空输入可保留等待；SDK 验证已尝试后失败需要重来，不能静默复用一次性上下文。
- 待 MFA 可取消；取消后账号密码表单恢复，重新选择区域不会偷改旧流程。建议用户取消旧流程再换区，不能自动切换正在等待的 SDK client。
- 页面刷新，同会话未过期待 MFA 可继续，期限不续期；已保存认证仍显示。后端重启或会话过期明确重来；旧字段不得自动填回密码/验证码。
- 操作中按钮防双击，状态轮询不重叠；旧请求晚返回不能覆盖新 attempt 或卸载后的状态。仪表盘 API 失败不隐藏/禁用认证入口。
- 输入使用明确 label、password 类型、适当 autocomplete 提示；应用自身不保存输入。Chrome 自带密码管理器和操作系统内存不在应用可绝对控制范围，验收使用全新无密码保存提示的测试上下文，不能据此承诺安全擦除。

## 6. 实际 Chrome 验收方案

### 6.1 链路与测试宿主

必须经过：**系统 Chrome → 构建后的产品 React → 真实本机 FastAPI 路由/安全门 → Web 运行态 → 原 GarminAuthService → 实际锁定 Garmin/garth 控制流 → 测试专用离线 HTTP 传输 → 原仓储**。

- 复用 `tests/sync/auth_support.py` 的实际 SDK 传输模式，扩展为两区域名校验、HTTP 错误、延迟门、短有效期/受控时钟和安全计数。不能只核路径而忽略域名；consumer 下载属于 SDK 的单独域，不误判为必须带 com/cn 的 Garmin 站点。
- 不 mock begin_login/submit_mfa/maintain_once/commit，不为认证用 `page.route().fulfill()` 伪造成功。现有活动错误显示的 route.fulfill 可以保留，但不能算认证集成覆盖。
- 在服务子进程启动前安装离线传输和网络门；pytest 的 `tests/sync/conftest.py` 不会自动保护独立 E2E 服务。允许浏览器/测试控制所需的明确回环通信，其他实际外连一律阻断并记录尝试数；意外外连尝试应使测试失败。
- 测试控制使用测试宿主参数/私有管道/进程通信，禁止在产品 HTTP 留 `/test/reset`、改时钟或填 token 的端点。重启测试使用相同临时实例、重启真实应用子进程，不只刷新 React 或换一个模拟对象。
- 时钟推进同时覆盖所有者 UTC/单调时钟与 SDK 计算期限所用的时钟，确保“提前刷新”真的经过 SDK 交换与 commit。可用短期限合成响应，不修改正式 token 到期值。终端副进程用已有 CLI 测试设施接同一离线传输，不让父进程的 mock 失效后真实联网。
- 继续使用 `channel:"chrome"`、拒绝借用已有服务、串行使用 8080；每个场景实例/会话/计数隔离。认证测试默认关闭 trace/HAR/video 等会保存 body 的产物，失败也不自动上传；脱敏截图只拍清空输入后的状态。真实本人操作更不能录制敏感阶段。

### 6.2 场景矩阵

| 场景编号 | 要求与实际操作 | 通过证据 |
| --- | --- | --- |
| GUI32-C01 | 无 DB、无 AI、无认证启动；Chrome 打开产品页面，两区选择均可操作 | 面板独立可用，仪表盘失败不拦截；未读 AI/未发外部请求；状态明确未保存 |
| GUI32-C02 | com、cn 各做普通登录 | 浏览器选择值→HTTP body→SDK 正确 Garmin 域；实际交换、仓储提交、GUI saved；不出现 MFA、不回传账号/OAuth |
| GUI32-C03 | com、cn 各做 MFA 成功；刷新页面后继续提交 | login 真正 needs_mfa；同会话恢复期限不变；真实 resume_login/profile/settings 控制流后安全保存；仅一次验证码提交 |
| GUI32-C04 | 凭据流程 401/403、SDK 页面异常、MFA 未完成、settings 失败、网络超时、429 | 真实错误 HTTP/固定 envelope/GUI 提示；未知失败不冒称密码或验证码错；保存失败不亮成功；旧指针保留；密码/码不重放 |
| GUI32-C05 | 取消后重来、MFA 恰好 TTL 前/到点/之后、会话到期、旧 attempt 延迟返回 | 取消清理且不删旧令牌；边界由服务端判定；旧请求不能提交/取消新流程；重来仍可选择两区 |
| GUI32-C06 | 双击/连续 Enter、同时提交验证码；A/B 两个 BrowserContext 互抢 MFA/取消 | SDK 真正最多一次；B 即使持有 A 的 Web attempt 也被拒绝，A 可继续；忙碌可见，健康/静态页面响应不中断 |
| GUI32-C07 | 正常保存后刷新页面、关闭并重启服务；待 MFA 时重启 | 保存认证由新进程 load，期限/区域一致；新 session/CSRF 有效，旧 session/attempt 拒绝；MFA 重来而不是假成功 |
| GUI32-C08 | 未到维护点/恰到点/已过期；自动到期前维护；保存后再重启 | 无需 CLI maintain；未到点零交换，到点实际 refresh/commit，GUI 新期限；重启恢复新代次；本地文件存在从不显示本次在线核验成功 |
| GUI32-C09 | 刷新 503/超时/429、3 次耗尽、用户点击重试；401/403/需人工验证 | 5/10 秒或受控时钟等价调度、有界网络次数；暂停/人工状态不被 status load 清掉；重试只启动一组；成功后状态恢复且真正落盘 |
| GUI32-C10 | Web MFA 与 CLI 登录/维护/同步竞争、外进程持锁、写盘失败 | 无死锁/双写；新代次后旧 MFA 拒绝覆盖；busy 不假成功；保存失败保留旧完整代次；同步仍使用唯一所有者 |
| GUI32-C11 | Origin 缺失/null/外站/回环另一端口、错误 CSRF、外会话、非法 Host、非 JSON/超大 body | 浏览器跨站页面实测＋直接 HTTP 异常头补测；状态码/envelope 符合合同，拒绝前 SDK 计数不变，无 CORS 放行，无跨站取消/刷新 |
| GUI32-C12 | 合成秘密 canary 扫描；关闭空闲/睡眠/在途 Web，再启动；完整仪表盘回归 | URL/日志/响应/异常/浏览器持久存储/服务器非 OAuth 文件均无密码或码；OAuth 只在私有代次和必要备份；cookie 非 OAuth、HttpOnly。无线程/端口残留；原活动搜索/选择/安全全文/周报/API-SPA 等仍可用 |

期限/并发精确边界、存储故障注入和所有者静态检查可由 Python 集成补强，但不能省去表中 Chrome 对可见流程的操作。Chrome 不能自由伪造 Host/Origin，相关异常头用直接 HTTP 补测；跨站/跨端口浏览器攻击仍必须实际从另一页面发起，不能只用 TestClient 宣称浏览器保护成立。

隐私扫描需有阳性对照，证明扫描能发现 canary。测试统计只记录方法、固定路径类别、域名与次数；不保存包含 ticket/query/Authorization 的完整请求。不要把“所有临时磁盘完全没有 OAuth”作为错误断言：OAuth 本来就应该仅在后端私有仓储存在。

### 6.3 独立验证材料与检查顺序

1. 主 Agent 固定完整 source、4 个公开 references、适用规则/模板、当前 GUI/AU 要求、审核后的本拆解，以及不含旧裁决的客观协调视图；记录 HEAD、未提交清单、哈希和验证入口。完整复制必要资料，不只复制 Git 已跟踪文件。
2. Validator 使用固定副本和仓库外独立 Python 3.12 **非 editable** 环境，强制重装当前产品并核对安装文件。前端先 `npm ci` 和 build，再开始完整 pytest/Web/Chrome 回归，避免静态文件缺失造成假故障。生成物与证据写到隔离位置，原受审文件前后哈希不变。
3. 本轮新增所有权检查覆盖 `local-web/scripts` 的 HTTP/运行态/CLI：禁止直接读认证路径、import 仓储/SDK、dump/load token。既有架构门继续运行；静态门不能证明任意动态绕过，须人工核对真实写点和调用链。
4. 当前 Web 测试默认 TestClient 主机是 `testserver`，部分未使用上下文管理器；新 Host/lifespan 接线后，测试须显式使用规范回环 base_url，并用 `with TestClient(app)` 或实际子进程执行生命周期。不能为让旧测试变绿而在生产放行任意 Host，不能把未进入 lifespan 的检查冒充维护启动测试。
5. 执行现有适用门，并加新认证 Web/生命周期/Chrome 场景；不能只跑新测试或降低旧断言。已知 AU32-V1-002/003 若复现仍如实记录，不能把两个未修项写绿。

实施后检查命令示例（本次 Planner 未运行产品验收）：

```bash
# 项目根，环境预先指向仓库外
uv sync --project source --python 3.12 --locked --extra dev --no-editable --reinstall-package trainlab-source
# source/frontend：先构建
npm ci
npm run build
npm run lint
npm run typecheck
npm test
# source：使用上述已激活环境
python -m pytest tests -q -p no:cacheprovider
python -m ruff check --no-cache .
python -m mypy -p trainlab -p tests --no-incremental
python -m compileall -q skills schemas tests
python -m trainlab.check_architecture
# source/frontend：真实系统 Chrome，含新增认证场景
npm run e2e
# 项目根
git diff --check
```

预期是所有本轮适用检查实际退出 0，测试数量以运行结果为准；原有效未修问题单独列失败与范围，不删弱断言。主 Agent 在独立通过版本亲自重复实际 Chrome 操作和关键安全/重启场景，核对服务关闭、版本与产物，不以读报告代替主验收。

## 7. 真实用户操作与不变边界

- T15 本地安全 GUI 验收后，主 Agent 给用户本机页面及操作说明；用户在页面选择 com/cn 并本人输入账号、密码、必要验证码。**不再问“要不要 GUI”、不再要求在聊天先选区，也不要求先 CLI 登录。**
- 真实账户验证由用户参与完成，公开只记录操作类别、版本、时间、是否保存、固定错误码等脱敏信息；不把真实敏感阶段录进 Playwright trace/截图/聊天。
- 原 T9 的真实到期前刷新/保存/重启证据，以及 T2 的有界列表/下载/FIT/SQLite 证据继续保留；没有真实遇到 MFA 或撤销，就说明仅离线覆盖，不能造出来。到期前观察时点未到时继续待验，不修改正式 token 期限造证据。
- Web 不顺带启用活动同步/AI 定时任务；后续原授权有界同步可用已有入口，不是认证 GUI 必须先依赖同步成功。本轮不增加同步按钮、账户列表、登出撤销、配置编辑器或系统常驻安装。
- D31-LIVE-002 真实失败1、旧接线尝试1、新认证实现1及真实未验证状态保留；RV-001/002、INFRA-001/002 原计数不清零。AU32-V1-001 材料失败2及恢复事实保留；AU32-V1-002/003 修法0，AI 实服务仍暂停。新 GUI 缺陷使用新稳定编号，不借编号变化重置历史。

## 8. 本次实际检查、残余事项及下一步

### 实际检查记录

| 已执行方式/命令 | 结果 |
| --- | --- |
| 完整读取派发材料、规则、Planner 模板、PLAN、当前执行计划、旧认证规划与审核；定向读取当前源码/合同/测试/README/配置/锁定库 | 完成；关键证据位置见本报告第1节各文件/符号，未读真实 states |
| `pwd`、`git branch --show-current`、`git rev-parse HEAD`、`git status --short`、`git diff --stat`、定向 `git diff -- ...` | 退出0；根目录/分支/HEAD一致，未提交工作保护，暂存为空 |
| Python 对 source-after.json / references-after.json 逐项计算 SHA-256 | 退出0；`source-after.json files 96 mismatches []`；`references-after.json files 4 mismatches []` |
| 在自有仓库外目录执行 `uv export --project source --locked --offline --no-emit-project --no-dev --output-file "$probe/requirements.txt"`、`uv venv --python 3.12 "$probe/venv"`、`uv pip install --offline --python "$probe/venv/bin/python" --requirement "$probe/requirements.txt"` | 各退出0；锁定依赖已缓存，无产品安装、无真实网络请求；版本见第1节 |
| 仓库外、阻断 socket 的库级小探针 | 退出0；两区 SDK 构造的域名映射正确；construct=0 lifespan events，enter/exit=start/stop；同步路由在工作线程；取消 await 不终止 worker、释放后已等待结束；外连尝试0；未执行登录 |
| 项目及全局技能/适用规则检索 | 完成；未发现本次适用技能，不使用旧编排流程 |
| `git diff --check`、`git diff --cached --quiet` | 退出0；未产生仓库修改/暂存 |

读取时曾按猜测的 `dashboard.spec.ts` 文件名得到不存在，随后通过实际目录找到并读取 `tests/e2e/local-web.spec.ts`；不将这次路径探查误记为产品测试失败。未运行本轮完整 pytest/前端/Chrome、没有真实账户操作，这些不是本报告的通过结论。

### 主 Agent 需审核的内容

只需审核 T10～T15 的有限范围、路由/DTO衔接、生命周期与安全会话是否一致；审核通过后由主 Agent 更新现有执行计划、总计划并按流程推进。重点确认本轮必须替换的“无后台任务”合同及原 T9 的 GUI 接入点。**当前没有需要再次向用户确认的两区或 GUI 范围问题，也没有要等待追加材料的阻塞。**

### 残余风险与停止边界

1. Web GUI、会话安全及维护生命周期尚未实现；本报告不构成产品通过。真实 Garmin 行为、当前401唯一原因、真实登录/刷新/同步仍未验证，外部 SDK/页面可能变化。
2. 回环 HTTP/内存会话不防本机恶意进程、已被控制的浏览器扩展或管理员；不把本机单用户服务包装成公网认证系统。浏览器密码管理器、系统交换区及语言运行时内存不能由应用保证物理擦除。
3. 工作线程不能靠取消 await 强制终止；逐请求超时不是完整链硬截止。实现和验收必须证明正常关闭顺序及强制中断恢复，遇无法停止的真实 I/O 不宣称已干净退出或自动反复重启。
4. 跨进程认证更新会使旧 MFA 挑战失效，这是保护新令牌不被覆盖的必要边界，GUI 必须清楚说明，不承诺验证码永远可续。
5. 两个既有 Context/Web 缺陷仍未修、AI继续暂停。本轮用认证专属错误边界避免继承泄密；若实现确实需要改变其他业务错误语义，先返回主 Agent 审核范围，不顺带扩修。
6. 一旦需要升级 SDK、开放远程/多 worker、长期守护、读实例外认证或恢复 AI，就超出本方案，暂停受影响内容。保留各稳定编号和失败累计，遵守两种实质修法或连续三轮不收敛的停止规则。
