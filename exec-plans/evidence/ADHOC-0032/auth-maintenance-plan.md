# ADHOC-0032 认证维护增量规划（待审核）

## 1. 理解与核对结果

本次是只读规划调整，依据 `exec-plans/evidence/ADHOC-0032/auth-maintenance-planner-task.md`、`AGENTS.md` 和 `subagent-templates/planner.md`，覆盖 AU32-01～06。交付目标是**一个认证所有者、可分步登录的通用接口、本人终端入口，以及显式启动后实际执行到期前刷新的维护进程**。

本轮不新增 React 登录页面或 HTTP 认证路由，不启动正式常驻服务、不修改系统调度，不恢复 AI 工作。不把“更新访问令牌”说成“底层授权永不过期”。规划不代表批准实施或功能通过。

已核对：

- 根目录及分支符合派发：`.`、`work/adhoc-0031-local-web-system`；HEAD 为 `a5893ac6eb8295cd8a60d8f2537bc213d1412885`。存在原有源码、测试、依赖、前端及协调记录改动，暂存区为空。本次没有改动仓库文件。
- `exec-plans/evidence/ADHOC-0032/parent-acceptance/source-after.json` 的 **78 个文件哈希全部相符**；不能因此认为新认证维护已完成。
- 实际没有认证维护调度器。`GarminSyncState.due()`/`should_run_sync()` 只作三小时判断；Web 的 `app_contract()` 和 `/api/health` 明确 `starts_background_jobs=False`。前端依赖名 `scheduler` 与认证后台执行无关。
- 当前 `garmin_sync.py` 在构造真实客户端时就可能联网，发生在同步 busy/due 检查之前；真实适配器 `refresh_auth()` 原样返回配置；通用同步函数直接写认证配置。仅添一个刷新函数，不能满足单一所有者与主动维护要求。
- DI 三字段被拼成空签名 secret 的 OAuth1，缺少有效期时补 `now+1800`，确有代码依据。此路线必须退出，不能用新登录掩盖。真实 401 唯一原因仍未确认。
- 产品包由 `source/pyproject.toml` 映射到 Skill/scripts；可在现有共享包增加模块，无需新实现根、运行时 `sys.path` 修改或架构例外。
- 项目未找到 `SKILL.md`；默认全局技能目录不存在，无适用技能可读取。

### 锁定 SDK 的独立核对

从 `source/uv.lock` 导出依赖，在自有仓库外 Python 3.12.13 环境安装，实测版本为 **garminconnect 0.2.40 / garth 0.6.3**。以下由源码及阻断真实网络的小探针核对，不依赖注解猜测：

| 入口 | 具体行为及规划影响 |
| --- | --- |
| `Garmin(..., return_on_mfa=True).login()` | 普通成功实际返回两个 OAuth 对象，不是注解所称的字符串；此分支直接返回，不加载 profile/settings。需要 MFA 时返回 `("needs_mfa", dict)`，不是整个返回值为字典。必须严格区分，不能以返回值真值判断成功。 |
| MFA `client_state` | 含 `signin_params` 和活的 `garth.Client`（会话/cookie/响应状态）；此时客户端 token 属性暂为字符串和字典，不能持久化、序列化或当令牌使用。 |
| `Garmin.resume_login(state, code)` | 先完成交换并赋 token，再尝试 profile、请求 settings；因此可能“已经赋 token，随后 settings 报错”。错误验证码的合成响应产生通用 `GarthException`，没有可靠的专门错误码；不能把所有缺 ticket、网络或页面变化都断言为验证码错误。 |
| `garth.Client.refresh_oauth2()` | 要求真正的 `OAuth1Token`，调用 `garth.sso.exchange()`，更新客户端属性，**返回 None**。不是用 DI refresh token 调刷新端点，也不是依据 OAuth2 refresh token 的期限判定底层授权期限。 |
| `dump/load` | `dump` 分别覆盖两个文件，非事务；权限受 umask 影响，探针中为 0644。显式 `load(directory)` 不设置 `_garth_home`，刷新不会自动保存；只有环境自动恢复的特定路径会自动 dump。产品不能依赖该隐式写盘。 |
| 环境与导入 | `garth.http` 有模块级 `Client()`；构造器会按 `GARTH_HOME/GARTH_TOKEN` 自动读认证。`Garmin.login()` 还读取 `GARMINTOKENS`。保持产品惰性导入，并在 SDK 导入/构造之前检查环境冲突。 |
| 隐私与超时 | SDK 会打印异常链，OAuth1 repr 也含敏感值，须延续 `garmin_privacy.py` 边界。`GARTH_TELEMETRY=true` 会覆盖显式关闭设置。SDK 首次取 OAuth consumer 配置的 `requests.get` 没有 timeout，不能声称只设置客户端 timeout 就约束了全部请求。 |

SDK 证据定位：`source/uv.lock` 的对应包条目；锁定分发包中的 `garminconnect.Garmin.login/resume_login`、`garth.http.Client`、`garth.sso.login/resume_login/exchange/GarminOAuth1Session`、`garth.auth_tokens`、`garth.telemetry.Telemetry.configure`。本次探针只用合成账号、令牌及临时文件；真实网络尝试为 0。

## 2. 有限增量拆解

保留 G1/G2/G3、0032-T1/T2/T3，不改号。建议新增以下六项，初始均为 `[plan]`；主 Agent 审核后写入现有执行计划，不另建总计划。

| 稳定任务 / 阶段 | 目标、输入 → 输出 / 文件落点 | 依赖与边界 | 检查及预期 |
| --- | --- | --- | --- |
| **0032-T4 / G2** 认证所有者、SDK边界与存储 | AU32-03/05/06；输入锁定SDK、路径/错误合同 → `GarminAuthService` 骨架、SDK窄适配、唯一私有令牌仓储。新增 `source/skills/_shared/scripts/trainlab/garmin_auth.py`、`garmin_auth_sdk.py`、`garmin_auth_store.py`；按需增补 `contracts/paths.py` 与 `exports.py`。 | 首项；只处理认证数据。SDK令牌不得进入公开DTO；使用实例级跨进程锁及安全原子提交。不得沿用DI拼接、默认未来期限或SDK隐式写盘。 | 新增 `source/tests/sync/test_garmin_auth_store.py`、`test_garmin_auth_sdk.py`：锁定SDK序列化往返、异常隐私、权限、崩溃/写盘失败、跨进程互斥、环境冲突、无导入副作用。旧活动/报告数据不动。 |
| **0032-T5 / G2** 普通登录与分步MFA | AU32-01/02/03；输入T4所有者 → `begin_login/submit_mfa/cancel_login/status`，实现于 `garmin_auth.py`，SDK细节留适配模块。 | T4；只接受当前流程的账号/密码/验证码。MFA状态内存保存、有界失效、并发提交只执行一次；失败不切换旧配置。 | 新增 `test_garmin_auth.py`：普通成功、待MFA、验证码成功/未完成、超时、取消、重复/未知句柄、并发、SDK返回畸形、交换后settings失败。正常返回且持久化成功才宣告认证成功。 |
| **0032-T6 / G2** 主动维护与终端入口 | AU32-01～04/06；输入T4/T5接口 → 新增 `garmin_auth_maintenance.py`、`garmin_auth_cli.py`；提供终端登录、状态、维护单次/循环入口，正文第3节给合同。更新 `source/README.md`。 | T4/T5；显式启动前台循环，不接入Web生命周期，不装系统任务，不扩为通用同步/报告调度器。通用服务无input/getpass。 | 新增 `test_garmin_auth_maintenance.py`、`test_garmin_auth_cli.py`：假时钟到期前触发、真实SDK离线交换/持久化、退避、人工介入退出、SIGINT/EOF清理、非TTY安全失败；实际子进程/伪终端完整登录→MFA→维护→重启，不只测函数。 |
| **0032-T7 / G2** 真实同步统一接线与迁移 | AU32-03/04/05；输入新所有者及旧同步入口 → 修改 `garmin_sync.py` 与 `exports.py`、现有同步/隐私测试；CLI补 `sync-once` 调现有同步入口。同步不再自行读写秘密或构造独立认证。 | T4～T6；先检查due/busy再创建认证会话；保留首次七天、三小时判断、FIT命名/去重/入库、错误回滚及公开同步结果。DI配置受控提示迁移，成功登录后保全旧配置再切换。 | 扩展 `test_garmin_sync.py`、`test_garmin_privacy.py`；实际SDK离线登录/刷新→列表→FIT→SQLite；同步中隐式刷新也保存；登录/维护/同步多进程竞争无覆盖。原DI成功假设改为“拒绝且无网络”的回归，原隐私强断言转用真实OAuth夹具保留。 |
| **0032-T8 / G3** 固定版本独立验证 | AU32-01～06；输入T4～T7开发自查、当前要求及固定快照 → 全新Validator独立正常/错误/边界证据。 | T4～T7完成开发自查；冻结受审内容。开发测试全部合成、阻断真实外部请求。 | 独立设计第5节场景，执行静态门及完整CLI/SDK集成；核快照和权限/并发/安全证据。未运行和环境阻塞明确记“无法判断”，不得用函数级mock代替完整入口。 |
| **0032-T9 / G3** 主验收与本人终端真实闭环 | AU32-01～06及原T2/T3；输入独立通过版本 → 主Agent亲自离线复核；用户在本人终端完成真实认证，随后受控维护、重启复用和原有有界同步验收，公开只留脱敏收据。 | T8；真实操作在安全入口就绪后，按原授权实施。不让用户向聊天提交凭据/验证码/令牌。 | 普通登录或实际出现的MFA、真实到期前刷新保存、进程重启复用、原T2列表/下载/入库有证据；没有实际遇到的MFA/撤销由离线场景覆盖并标明未实服务触发。主验收后才处理原T3交付，不能提前完成G2/G3。 |

执行顺序：**T4 → T5 → T6 → T7 → T8 → T9**。每项实现同时补测试；仅一个Developer写入。这里描述执行计划，不调度任何角色。

## 3. 拟定接口与运行合同

### 3.1 通用认证接口

`GarminAuthService(instance_root, …)` 的依赖允许注入时钟、SDK工厂和存储实现用于测试；构造和模块导入不读私有文件、不联网、不启动线程。生产路径由受信宿主确定，不接收未来Web请求任意指定的文件路径。

| 公开操作 | 输入与安全返回 |
| --- | --- |
| `begin_login(username, password, *, is_cn)` | `is_cn` 明确选择；返回 `authenticated` 或 `needs_mfa`，后者只带随机不透明 `flow_id` 和流程截止时间。不得返回token、密码、账号、SDK client_state、cookie或HTML。 |
| `submit_mfa(flow_id, code)` | 仅同一服务实例中的活跃流程可继续；成功后安全提交令牌，返回 `authenticated`。错误/过期/取消/已消费句柄不重复请求SDK。 |
| `cancel_login(flow_id)` | 清理当前流程，重复取消可幂等；不删除已有持久令牌。 |
| `status()` | 显式本地读取；返回配置状态、已保存与否、访问令牌实际 `expires_at_utc`、建议维护时间、是否需人工操作。不联网、不刷新；仅有本地令牌不表述为“服务端认证已核验”。 |
| `maintain_once(*, now_utc)` | 已保存令牌未到维护时间则无网络；到点调用SDK刷新并提交，返回 `unchanged/refreshed/manual_required` 或受控错误及下次检查建议。UTC输入必须有时区；真实CLI使用系统时间，不能让用户用伪造时间改期限。 |

返回采用现有 `ok/data/error` envelope 与 `ErrorCode`；DTO/`to_json` 为字段白名单。`needs_mfa` 是流程成功进入等待态，不是认证成功。`flow_id` 仅交当前调用方用于继续，不写日志、不嵌入SDK状态；未来Web需由服务器持有同一服务实例，并绑定自己的请求会话。本轮不声称已解决未来HTTP的会话、CSRF等问题。

建议沿用错误码而非扩大公共枚举：`INVALID_ARGUMENT`（输入/未知句柄）、`TIMEOUT`（流程过期或请求超时）、`RUN_BUSY`（锁/重复操作）、`SOURCE_CONFLICT`（旧流程基于的认证代次已变化）、`CONFIG_UNAVAILABLE`（缺配置/环境冲突）、`DATA_INVALID`（存储结构损坏）、`AUTH_REFRESH_REQUIRED`（需要登录/迁移/认证未完成）、`RESOURCE_LIMIT`（限流）、`EXTERNAL_SERVICE_FAILED`（服务异常/存储提交失败）。固定 `details.reason` 区分场景，不装入原异常或路径值。

SDK缺少可靠错误分类时，报告“验证码验证未完成，请重新开始”，不武断指认验证码输错；HTTP 401/403、429、超时和本地格式错误尽量依据异常类型及嵌套response状态分类，不能只搜异常字符串。

### 3.2 MFA生命周期与同步竞争

以下为实现建议，不是用户规定的时限：同一服务实例、同一私人实例最多一个待MFA流程，默认5分钟TTL，用单调时钟判超时。SDK/password引用在不再需要时释放；结束、取消、过期均关闭会话并清理上下文，不声称Python字符串能可靠内存擦除。

- 登录请求、提交验证码、刷新及真实同步的认证操作，共用实例级线程锁与进程锁；本机环境可采用 `fcntl.flock`，不虚构已有跨平台锁设施。
- 不在人等验证码期间长期持有磁盘锁。流程记录创建时的存储代次，提交时先加锁并重新核对；期间发生另一次登录/刷新提交，则旧流程失效，不能覆盖新令牌。
- 一个提交在途时再次提交返回busy；提交成功或发生SDK验证/网络异常后消耗上下文，禁止自动重放验证码。空白等本地输入错误可保持等待，不发网络。
- 进程重启后待MFA流程消失，明确要求重新登录；已提交令牌仍可复用。TTL不承诺延长Garmin自己的挑战期限。

### 3.3 唯一令牌仓储与迁移

建议使用**不可变令牌代次目录＋单一原子配置指针**，避免把SDK的两次普通写文件误称“原子保存”：

1. `states/verification/garmin.json` 继续作为唯一活动配置入口，版本化记录真实SDK后端、区域和实例内相对tokenstore路径，不再承载DI拼装逻辑。
2. 新令牌写至 `states/verification/garmin-tokenstore/` 下的新代次。私有目录0700、文件0600；预创建安全文件后调用SDK dump，再用SDK load做结构往返检查。父目录和目标禁止符号链接/路径逃逸；不用全进程临时umask作为Web服务的唯一权限保证。
3. 同文件系统暂存、必要的flush/fsync、完整代次就绪后原子替换活动配置；失败不切换指针。读取者必须经所有者和同一锁获取完整一对令牌。保留上一完整代次供失败恢复，清理只涉及本模块自建的非活动代次，不删未知私人文件。
4. 首次切换前把旧 `garmin.json` 原字节保全为权限受限的私有备份；备份或提交失败即不切换。用户明确执行登录入口后，成功才执行该切换，不要求先手工提取cookie/token。
5. DI配置只识别、提示 `AUTH_REFRESH_REQUIRED` / `legacy_auth_requires_login`，不发“试试看”的真实请求，不用本地JWT解码伪造SDK期限。旧SDK tokenstore由所有者接管：实例内合法目录或原私有编码形状经严格校验后导入新仓储；原件保留。超出实例的旧路径受控拒绝并提示先迁入私人实例，不隐式扩读。
6. 重启只从活动代次恢复。SDK环境自动恢复/自动dump必须禁用；不得把保存后的base64串放入公开配置结果或命令行参数。无有效期限时返回未知/格式错误，不用当前时间补未来值。

“失败保留旧有效令牌”指不破坏旧的本地完整数据；若服务端已撤销或轮换旧授权，客户端不能保证它仍能使用，也不能回滚服务端状态。

### 3.4 主动刷新与真实可启动入口

采用认证专用前台维护循环，不假设已有scheduler。建议命令合同（T6/T7实施后才存在）：

```bash
python -m trainlab.garmin_auth_cli login --instance-root . --region com
python -m trainlab.garmin_auth_cli status --instance-root .
python -m trainlab.garmin_auth_cli maintain --instance-root . --once
python -m trainlab.garmin_auth_cli maintain --instance-root .
python -m trainlab.garmin_auth_cli sync-once --instance-root .
```

- `login` 在本人TTY提示账号，用getpass隐藏密码和验证码；无密码/验证码命令行参数，不从环境变量接收秘密，不在缺TTY时降级回显。等待MFA时调用同一通用接口；EOF/SIGINT清理会话。
- `maintain --once` 是可调用的一次检查；不加 `--once` 才显式运行循环，实际等待、调用SDK刷新、保存，再等待下一次。退出即不再自动维护，休眠/断网/未启动期间不保证到期前执行。默认Web行为不变。
- 到期前窗口建议 `min(300秒, max(1秒, expires_in×10%))`，从SDK真实期限计算；循环最多睡60秒后重新读取配置和时钟，检测其他进程登录/刷新。数值可调并测试，不作为产品永久保证。新令牌仍过期或立即反复到期时受控停止，不忙循环。
- 主动更新调用真实 `client.garth.refresh_oauth2()`，读取其更新后的token，而不是把返回的None当失败。OAuth2 refresh token的过期不直接等于OAuth1交换一定失败；是否须重新登录以SDK机制及服务响应为准，不捏造OAuth1通用期限。
- 临时网络错误/限流采用有上限的退避，默认一次连续故障最多3次尝试后退出非零，保留旧存储；人工验证/撤销立即退出并提示重新登录，不能循环试密码或验证码。等待时不占认证锁。
- SDK操作设置有限timeout、禁用嵌套自动重试；首次consumer配置获取也要覆盖。建议SDK窄适配层按锁定SDK自己的URL/代理/TLS设置，带timeout预载并校验其consumer缓存，随后仍走SDK的OAuth交换；不改全局HTTP函数、不猜Garmin私有端点。该内部SDK接点需独立回归与版本锁保护。
- SDK导入前若存在会自动读认证的环境变量，或开启SDK遥测，返回固定配置冲突提示，不打印变量值、不改宿主进程环境。显式调用再惰性导入；复用现有日志保护并扩测首次导入、登录/MFA、新logger和异常链。

同步内部通过所有者的**私有认证会话租约**取得SDK客户端，不把客户端作为可JSON化公开结果。按“同步锁→认证实例锁”固定顺序，先due/busy判断再联网。每次受保护SDK调用后检查令牌变化；若SDK在列表/下载中自行刷新，也由所有者保存。数据请求失败但刷新已完整成功，应保存这次完整刷新结果，同时保持同步失败；认证交换/提交失败则不覆盖旧代次。保留同步状态的原子写入逻辑，但从同步模块移除认证写入。

当前 `AuthRefreshResult.updated_config`、`GarminSyncClient.refresh_auth(auth_config)` 会传递秘密并让同步写盘，必须调整：同步协议只暴露数据操作与安全认证准备结果，认证配置/写入归所有者。仓库内调用者与合成客户端同批改造；若保留兼容名字，只能代理给所有者，不能留下第二套配置落盘路径。

## 4. 调整理由与不变项

- **原0032-T2遗漏**：仅有客户端构造和受控认证失败，缺普通登录/MFA状态机、安全存储事务、主动维护进程和单一认证所有者。T4～T7补齐；不改原真实同步窗口、FIT/SQLite要求。
- **原0032-T3补充**：离线Web/SDK验证不能证明新认证产品可运行。T8/T9增加完整CLI、存储/并发/重启和本人终端真实证据；已完成G1不回退，也不免除受影响的Web合同回归。
- `source/README.md` 中“支持DI配置”和“无真实维护入口”的旧描述应随产品实际能力更新，不将离线通过描述为实服务成功。
- 历史编号/计数不重置：D31-LIVE-002原真实检查失败1、接线尝试1、成功链路未验证；RV-001/RV-002各首次发现1、首次修法1、修复复验失败0；INFRA-001结果传递失败1、INFRA-002网络失败1，均不混计产品修复失败。其他既有记录原样保留。

## 5. 验收映射与最小检查集

| 目标 | 必须留下的证据 |
| --- | --- |
| AU32-01 | 实际锁定SDK的普通登录返回对象、MFA二元组分支；非法凭据/限流/断网不假成功；CLI本人操作入口可达。 |
| AU32-02 | 同一活会话分步提交；未知/过期/取消/重复/并发提交受控；错误响应与真实网络超时分别测；所有公开返回、日志、traceback、repr、stdout/stderr、磁盘均无合成密码/验证码/秘密canary。 |
| AU32-03 | 新登录/刷新后重启新进程恢复；双文件一致性、每个提交阶段注入失败、旧指针/备份保留、权限及符号链接边界；旧DI不造期限，不作OAuth1。 |
| AU32-04 | 到期前一刻/恰好维护点/已过期/时钟跳变/睡眠恢复；实际SDK交换而非只mock刷新函数；刷新持久化后旧进程不能覆盖；限流退避与需要人工操作的停止；显式维护进程确实有执行循环。 |
| AU32-05 | 同步、CLI、维护共享同一仓储/锁；同步未due或busy不认证联网；同步中隐式刷新保存；首次七天/三小时/去重/FIT导入/部分失败回归；Web健康合同和导入无副作用不变。 |
| AU32-06 | 开发自查→固定快照独立验证→主验收；真实子进程/TTY完整CLI集成、跨进程竞争、锁持有者崩溃恢复；用户本人真实登录、重启复用及原T2同步成功证据。实服务未执行项明确保留。 |

开发与验证测试应阻断socket真实连接，并清空SDK自动认证环境；HTTP层使用合成响应，保留真正的SDK登录/MFA/交换/序列化控制流。CLI子进程也必须继承网络禁止策略，不能只在父pytest进程打补丁。不得为保留旧DI绿灯而继续伪造OAuth1；改正旧测试预期时，原隐私、错误和SDK集成覆盖必须迁移保留。

现有架构门只约束布局及sys.path，不会证明“唯一认证写入者”。建议在合同测试加入针对本次所有权的静态检查，发现 `garmin_sync`/CLI/维护绕过所有者直接load/dump或写认证路径；同时人工审查全部真实SDK调用与认证写点，说明静态检查不覆盖任意动态反射。

实施后的命令（**本次未运行这些产品验收**）：

```bash
# 项目根；环境预先指向仓库外独立Python3.12环境
uv sync --project source --python 3.12 --locked --extra dev --no-editable
# 激活后从source运行；产品改变后先重新安装，不能测试旧wheel
python -m pytest tests -q -p no:cacheprovider
python -m ruff check --no-cache .
python -m mypy -p trainlab -p tests --no-incremental
python -m compileall -q skills schemas tests
python -m trainlab.check_architecture
# 项目根
git diff --check
```

预期全部退出0，新认证测试和原同步/隐私/Web API测试实际执行；测试数量以实际结果为准，不预写通过数。若不改前端/服务路由，不要求重跑所有历史额外浏览器场景；主验收至少复跑既有默认Chrome入口，证明Web启动/状态卡未因认证模块接线新增后台行为。若扩大受影响范围，检查随之补齐。

真实验收：用户在本人终端选择区域并登录；不预设一定出现MFA。用新进程检查已提交存储并执行受控真实同步；维护进程至少观察一次依据**真实SDK期限**触发的到期前交换与持久化，再重启复用。不能修改真实token期限来假造“已验收”。若观察窗口尚未到、网络不可用或需要人工验证，该项保留待验，不宣告G2/G3完成。公开收据仅记版本、动作类别、错误码/退出结果与成功与否，不带账号、凭据、原响应或私人活动明细。

## 6. 本次实际检查记录

| 人工方式/命令 | 结果与证据 |
| --- | --- |
| 完整读取派发材料、Planner模板、规则、总计划及关联执行计划；阅读列出的当前代码、测试、README、锁文件与Git diff | 完成；事实和文件定位见第1节及各任务落点。未读真实states、账号或凭据。 |
| `pwd; git branch --show-current; git rev-parse HEAD; git status --short; git diff --stat; git diff --cached --name-only` | 退出0；分支/HEAD与材料一致，原未提交改动保留，无暂存。 |
| `git diff -- source/skills/_shared/scripts/trainlab/garmin_sync.py source/pyproject.toml source/tests/sync/test_garmin_sync.py` | 退出0；独立确认DI映射、默认未来期限及已有测试的假设。 |
| `uv export --project source --locked --no-emit-project --no-dev --output-file "$work/requirements.txt"`；`uv venv --python 3.12 "$work/venv"`；`uv pip install --python "$work/venv/bin/python" --requirement "$work/requirements.txt"` | 均退出0；`$work` 为自有仓库外临时检查目录。仅安装锁定依赖作SDK阅读，没有editable或产品实现安装。实查版本0.2.40/0.6.3。 |
| `"$work/venv/bin/python" "$work/sdk_probe.py"` | 退出0；临时合成探针核实正常/MFA实际类型、resume赋token后settings失败、坏MFA通用异常、显式load后刷新不写盘、dump权限、环境自动load及遥测覆盖。原始关键输出摘录见下。 |
| Python逐项比较 `source-after.json` 中路径的SHA-256 | 退出0；`source_snapshot_files 78 mismatches []`。只读清单中的source公开文件。 |
| 只输出SDK环境变量是否存在的探针 | 退出0；`GARTH_HOME/GARTH_TOKEN/GARMINTOKENS/GARTH_TELEMETRY` 均不存在；无变量值输出。 |
| `git diff --cached --quiet; git diff --check` | 退出0；暂存为空、工作区差异空白检查通过。 |
| 查找项目技能及默认全局技能 | 项目无匹配；默认全局目录不存在，查找工具报告非目录。未换模式反复尝试，不影响基于实际源代码规划。 |

SDK探针的脱敏关键输出：

```text
normal_login: tuple[OAuth1Token,OAuth2Token]; no profile/settings request
mfa: tuple[str,dict]; client_state contains live client; resume returns token objects
bad_mfa: generic GarthException, not a dedicated invalid-code type
resume_settings_failure: tokens already assigned; failure is after token exchange
persistence: explicit load does not auto-save refresh; refresh returns None; dump respects permissive umask
constructor: GARTH_HOME invokes load (intercepted; no file read)
telemetry: environment true overrides explicit configure(false)
probe passed; real network attempts=0; only temporary synthetic token files used
```

未执行产品全套pytest/静态门/浏览器复验，也未登录Garmin、提交验证码、下载或写正式数据库。上述是规划依据，不是AU32产品验收。

## 7. 审核决定与残余风险

**主Agent本次需决定：**审核T4～T9及接口/文件边界是否与目标一致，尤其确认“显式前台认证维护进程、不接HTTP路由”和“所有者替代原认证配置写入协议”的衔接；通过后再更新执行计划、派发实施。无需把TTL/刷新提前量等实现参数冒充用户决策，Developer可在上述边界内落实并验证。

**用户当前无需追加范围确认。**区域由本人使用登录入口时选择，真实验收操作时间由主Agent与用户安排。若改成现在就上Web登录、随Web自动启动维护、安装系统常驻任务或跨实例读取认证文件，则属于范围/授权变化，暂停该扩展再确认；本规划不包含这些分支。

残余风险：

- 锁定SDK属于外部服务适配，MFA页面、授权撤销及区域行为仍可能变化；离线通过不能证明当前401唯一原因或长期服务可用性。
- SDK首次consumer预载是锁定实现接点；网络超时、日志/遥测和环境自动读取需新增回归，不能直接沿用旧隐私通过结论。
- 原子持久化与跨进程锁尚未实现；崩溃时只能保证本地数据提交边界，不能承诺服务端令牌轮换回滚。
- 不运行维护进程、机器休眠或持续断网时无法保证到期前刷新；正式常驻部署不在本次授权内。
- 本次未完成真实认证/主动刷新/同步成功验收；D31-LIVE-002仍未闭合。若后续遇到已有失败阈值或环境阻塞，保留编号计数并按项目停止规则处理，不自动重试扩范围。
