# R5 本地发布接口

本模块为新 SQLite 实例增加离线验证的发布接口；R6 统一命令、定时运行、正式配置切换与真实邮箱/Garmin验收另行完成。所有调用以显式实例根为准，不查找旧 Candidate 或旧账本，不读取正式数据补齐参数。

## 准备与同源

`publication.prepare_weekly(root, end, revision_id, revision_sha, recipient=..., sender=..., late=...)` 先通过 R4 `seal` 固定显式修订，再读同一个 Bundle。返回 `seal`、`mail` 动作键和每个跑步日的 `create`/`schedule` 动作键；休息日没有 Workout。邮件采用简单中文正文，标明原周期和显式补发标志，附封存 PDF 原字节。完整步骤、重复组、目的、剂量、RPE、技术备注与停止条件由有效计划转换到 Garmin DTO。

`publication.prepare_sync(root, job_key, recipient=..., sender=...)` 从新库同步 job、FIT同步回执及日期状态生成简单邮件。查询完整、完整无运动、当日暂定、缺口、不完整、错误、FIT已取得/无FIT分别表达；没有最终FIT回执时不伪造下载完成。准备后来源发生变化，原动作内容冲突，须由 Host 决定正确准备时机，不通过换内容 SHA 重新领取发送资格。

准备是本地动作，不调用模型、细读或 Provider。周动作按原周结束时间、渠道/动作与课程日期唯一，同步邮件按同步 job 唯一；路径、源码版本和内容 SHA 不构成新身份。显式封存后不能编辑或另选版本。

## 授权与执行

`publication_ledger.Authorization` 必填授权键、精确 `action_keys`、开始/结束日期、UTC开始/到期时间及每个工具的 `max_calls`。没有默认业务数量；Host 根据本次用户授权填写。相同授权键的范围不能改变；每次调用在 SQLite 不可变 `delivery_receipt` 中先扣预算，崩溃和搬迁不退还。不同授权可增加已批准的只读对账预算，不能重复任何已占用外部写入。

Gmail 工具为 `gmail.profile`、`gmail.refresh`、`gmail.send`、`gmail.get`、`gmail.list`。`gmail_auth.Auth(token_file, account)` 只在显式调用时读取现有私有专用 Token，验证 send/readonly scopes 和官方端点；不交互登录。正常刷新先记录调用，再经0600临时文件、fsync和原子改名保存；失败保留旧文件并停止该认证对象。账号还须通过官方 profile核对。凭据/认证头和任意服务错误正文不进入账本、捕获或日志。

`gmail_rest.Client(auth, session=None)` 默认使用官方 REST；`deliver(root, action, client, authorization)` 每封只发送一次；`reconcile(...)` 只读。发送返回合法 Gmail ID先耐久保存，再读 RAW核验实际 Message-ID、唯一收件人/发件人、主题、正文和解码PDF SHA。允许服务改写本地Message-ID。没有发送ID时只按原Message-ID查询；空、多条或未排除分页歧义均不成功。查询列表不能代替RAW。

同步 REST 在主线程使用 POSIX ITIMER_REAL 包住 Token刷新和整个HTTP请求；已有计时器或非主线程在业务请求前拒绝，超时中断后保持非成功，不启动后台发送或自动重试。连接/读取timeout只是补充。正常 macOS/Linux单进程 Host 是本模块运行环境，不宣称抵抗进程不可中断的永久内核故障。

Garmin发布会话 `garmin_publication.open_session(token_root, work_root, is_cn=..., timeout=..., journal=..., action=...)` 在进入会话前先扣 `garmin.session`，沿用固定 MCP commit、依赖覆盖和原凭据不刷新guard。`journal` 来自 `open_ledger`，`action` 必须在授权精确列表中。会话只暴露 `upload_workout/get_workout_by_id/schedule_workout/get_scheduled_workouts` 四工具；FIT采集仍为原两工具。初始化和各次调用受剩余时间限制；关闭优先使用剩余时间，已耗尽时仍使用显式会话timeout完成有界安全收尾，不增加任何业务额度；关闭/凭据审计失败由 Host保留并报告，不能等同整体发布成功。`asyncio`时限要求底层SDK遵守取消协议。

Host可用 `session_opener(token_root, work_root, is_cn=..., timeout=...)` 创建延迟会话工厂，再将该工厂作为 `session` 参数交给 `await garmin_publication.deliver(root, create, schedule, session, authorization)`；会话在动作持有的同一实例锁和账本内打开，避免嵌套锁。该接口 创建并按可信返回ID读回完整课程后，才提交单项排期，再查询原日期。自有Workout ID与日历entry ID分别保存，不按名称认领，不删除或撤排。执行当时已经过去的日期不创建/排期，也不平移其他日期。`reconcile(...)` 只核验已占用动作，不为尚未占用的排期发起写入。

## 状态与恢复

`publication_ledger.status(root, action)` 返回 `prepared`、`unknown`或有当前证据的`success`。邮件、每课创建、每课排期独立；创建成功而排期失败时保留创建成功。已经成功的动作只返回耐久结果，不重新发起调用。unknown只能只读对账；创建响应完全丢失且没有可信课程ID时无法自动恢复，不以名字寻找或重建课程。

每个请求、intent、调用及成功结果使用当前 `fit_delivery_*_v1` Schema。单写者实例锁覆盖每次动作处理；在请求边界提交intent和预算，在成功前提交经过窄字段筛选/核验的捕获。文件与SQLite使用既有0700/0600实例边界。账本不声称抵抗同UID恶意修改、root或永久硬件故障。

## 离线检查边界

合成测试使用真实新库、R2/R3/R4报告链和假Gmail/MCP会话；覆盖附件/身份损坏、实际Message-ID改写、部分响应丢失、重复组、日期/所有权、原子刷新失败、阻塞请求时限、重放和资源闭包。它们不证明真实账号登录、真实Gmail投递或Garmin设备行为；真实业务须完整离线验收后另获精确授权和读回核验。

有限刷新保存故障的恢复以目标 Token 的实际字节为准：即使超时发生在 rename
已生效、Python 尚未记录返回之间，仍恢复原完整文件并传播中断，清理临时文件。
同一认证对象在失败后停止使用；已有调用额度不返还，不转成后台刷新或重新发送。

当前离线回归还覆盖真实 HTTP 替身入口从另一个只读 SQLite 连接观察已提交的
intent/精确占用、提交失败零发送、所有 Token 字段与认证头不进入投递证据、
实际 RAW 的身份/正文/附件/MIME 歧义，以及服务合法 ID 改写和正文重新编码。
闭包集成在仅含当前运行资源的副本中准备封存发布，模拟一次邮件与单课创建/排期；
搬迁 source 和实例后在新解释器中重放，两个渠道均零新增调用。
