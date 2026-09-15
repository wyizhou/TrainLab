# M12 统一入口

## 手动调度、接管与恢复

从 source 执行 `python -m skills._shared.fit_weekly --instance <明确的新实例> daemon --schedule schedule.json`。
[调度模板](../config/examples/fit-weekly.schedule.template.json)只有空占位。first_day 必须显式填写香港日期，
表示本实例开始负责的日期，不默认回溯到2022。grants 是最多1000项的有限映射：日槽位键为
`daily:YYYY-MM-DD`，周槽位键为 `weekly:YYYY-MM-DDT07:00:00Z`（香港周日15:00），值为实例内
对应精确授权JSON的相对文件名。配置、授权分开，启动daemon不产生许可。授权仍需原完整日期、
工具、次数、总墙钟、两模型阶段和发布action_keys。未到期槽位不读取对应授权或服务。
映射在本次启动时读取，修改后显式退出并重启；没有cron、launchd、登录项、开机服务或聊天监控。

唯一 schedule_state 模块将接管、观察时间、领取、每次执行开始和结果追加保存到 runtime/schedule/。
事件含版本、序号、前项SHA和本项SHA，原子写入、0700/0600，校验owner、类型、单链接与路径；
完整事件不可覆盖，未改名的 .pending-* 保留待查。不增加SQLite kind或修改Schema。
首次接管日期在重启或搬迁后不得更改。启动登记接管日起至昨日尚未查询完整的日期，保留已知
离散缺口和历史导入未建立coverage的事实。普通停机日缺口留待下一晚间任务，白天不逐日补跑。

每日22:00按当日、昨日、已知缺口的准确集合，复用原run_sync和总预算，冻结完整批次并通过
原REST/动作账本发一封邮件；整组日期必须获批，不能扩大离散区间。库存complete不代表下载
或关闭审计完成，领取和结果另保存原unfinished_jobs。已终结失败不因tick或重启自动重试、
生成recoveryN或换授权key；恢复已封存失败仍使用原显式sync恢复入口和精确授权。

周日15:00先原完整周同步，再原plan/summary、修订、PDF、邮件和Garmin链。持续运行到点固定
late=false，错过后启动只补最近一期，固定late=true、原窗口、原七日课表与业务身份。不逐周补、
平移日期或改已发送内容；过去且未领取课程明确skip，其余保持原日期。

业务前先耐久领取槽位，绑定原授权文件、完整Grant SHA、精确日期与业务key。重复tick、回拨、
重启和搬迁不能新建第二份资格；原授权改动在成功重放前也拒绝。无授权、过期、反序、冲突或
缺额度保存blocked，不读取其他凭据或自动续费。未终结领取在下次手动启动时最多尝试一次原链
恢复，原同步剩余额度和绝对期限仍生效；超过最近一期的旧周不自动补发。模型成功不重跑，
未知捕获沿原本地路径恢复，未知邮件或课程不重发；外部只读对账仍走reconcile精确授权。
失败槽位不妨碍以后独立获批的新槽位。

所有领取、执行开始、结果和blocked事件的时间都进入耐久高水位，重启回拨不能绕过后续观察。
同轮每项开始和前项业务返回后重新读取当前时间，后项按自身真正开始时的原期限检查；正常耗时
不会被旧tick时刻误判为回拨。未过期的多个原领取可在此次启动内依次恢复，实际回拨仍停止调度，
后项已过期则零业务调用且不新增执行尝试，不改变原授权、日期、业务key或剩余额度。
status新增schedule接管日期、观察时间、槽位原执行结果/次数/late及blocked原因；业务账本的
当前pending/unknown/failed另行保留。原执行结果是历史事实，显式对账不改写它。
槽位没有最终回执时显示unsettled；实际进程是否running或interrupted仍由OS锁和生命周期判断。
调度记录不可可靠读取时schedule=unreadable、退出3。SIGINT/SIGTERM即使经过capture中断转换，
仍按原信号记录stopped并退出130/143；SIGKILL不伪造stop，OS锁释放后显示interrupted。
离线子进程测试不表示真实模型、Provider、Linux或正式实例已经验收。

从 `source/` 执行 `python -m skills._shared.fit_weekly --instance <实例根> status`。
默认实例为 `source/state/fit-weekly`；相对实例路径以 `source/` 为基准，显式绝对路径支持搬迁。
不依赖调用者当前目录，不自动创建实例、服务、凭据或后台任务。

实际提供只读 `status`、显式 `import-history`、授权 `sync`、双阶段 `weekly`、
发布前 `edit` 和本地/外部只读 `reconcile`、配置读取、生命周期锁及运行记录。
`daemon --schedule <调度配置>` 手动运行香港日历调度，退出即停止等待。
大功能总览见根 [PLAN.md](../../PLAN.md)，统一入口与旧路径退出的验收证据、当前任务和恢复位置见 [M12 执行计划](../../exec-plans/active/M12-fit-weekly.md)。

## 配置和授权

[配置模板](../config/examples/fit-weekly.config.template.json)及
[授权模板](../config/examples/fit-weekly.authorization.template.json)只有结构与空占位，填充前会拒绝。
实例目录和其中私有子目录必须为 0700，私有文件为 0600、当前用户所有、普通单链接文件；
拒绝符号链接、硬链接和上级跳转。错误只返回固定代码，不回显私人正文。

`run_config.load(instance, filename="config.json")` 只读主配置。
`Config.service(name)` 才读取选定的服务文件，服务专用字段仍由后续适配器验证。
主配置和授权文件路径相对于实例根。目标及服务文件、其中明确声明的 Token 文件或目录
可以用实例相对路径或原位置的绝对路径；不复制凭据。绝对路径只用于目标及指定服务的必要私有项，
检查路径上无符号链接、文件 owner/单链接/0600 及其私有父目录0700，不开放任意文件读取。
服务路径求值不打开文件，选择服务后才校验并读取。Garmin 的
[服务模板](../config/examples/fit-weekly.garmin.template.json)只有 `token_root` 与布尔 `is_cn`；
Gmail 的[服务模板](../config/examples/fit-weekly.gmail.template.json)只有私有 `token_file` 与 `email_file` 路径。
`email_file` 指向说明文字加单独一行唯一邮箱的 `Email.md`，同时收件与发件。
Token 独立保存在仓库外私有目录，正常运行只用现有官方认证与原子刷新；失效需要明确重新授权。
填写方式、首次授权与标签额度见[邮件配置](email-configuration.md)。
`status`、导入、本地 `edit` 和本地 `reconcile` 不读服务配置或 Token。
主配置的 goal 填写实际私有自然语言文件路径，通常为 `Goal.md`；不要求固定标题、字段、顺序或分类。
直接冻结接口默认读取实例内 `Goal.md`，配置可指向已批准的仓库外私有位置。
公开[填写说明](../goal.module.md)不含私人目标。仅首次冻结周输入时读取原 UTF-8 正文；已有周恢复使用
原目标快照，即使当前目标文件被改名或删除也不重写原输入。

配置不含 `enabled` 或授权开关。`run_authorization.load(instance, filename, now=...)`
严格读取另行提供的授权文件；调用者必须显式传入当前 UTC 时间。
授权绑定稳定 key、起止有效窗口，及以下可选业务范围，不能全空：

| 范围 | 明确字段与接口 |
| --- | --- |
| 同步 | 排序且不重复的精确日期、as_of、三项工具、页大小/总页数、活动/下载/会话上限、单次和总墙钟。可显式指定 `max_tool_calls` 总数，兼容未填写时取三个调用上限之和。`Grant.sync_spec` 只接受授权内连续子范围并生成稳定 `SyncSpec`；离散日期不得扩大成连续范围。 |
| 模型 | 原周日截止时间、plan/summary、命令身份、正墙钟；`Grant.command` 要求三项身份完全相同，返回 `CommandGrant`。 |
| 发布 | 精确 action_keys、日期范围、每工具调用额度；`Grant.publication` 返回已有 `publication_ledger.Authorization`，沿用原有效窗口与 key。 |

`Grant.freeze` 使用短时原 writer.lock，将完整授权写入实例 `authorizations/` 的不可变私有文件。
同 key 改额度或内容会冲突；搬迁、重开不改变原内容。子同步 key 由授权 key、精确日期及
as_of 确定，API 不接受任意替换 job key。`Grant.freeze` 保存授权身份，不执行预算消费。
同步、日期选择和通知入口先以 `Grant.check_frozen` 比较已保存的完整授权，已封存批次、
已成功邮件及 unknown 恢复也不跳过；同 key 修改同步、模型、发布或有效窗口均在服务
配置读取前拒绝。调用者持有相同 Grant 时，collect/notify API 可直接读取已封存同步与
已成功邮件，包括授权到期后；这不允许新的外部调用。CLI 读取授权文件仍检查有效窗口。
需要访问服务时先检查有效窗口并冻结完整授权，再读取服务配置。
后来明确提供的独立邮件授权可用新 key 精确绑定原批次 action_key；同样冻结完整内容，
unknown 仍只对账，成功仍不重发，不自动生成新授权 key 或追加额度。
`sync_budget.Budget` 补充实际执行账本，所有子同步与显式恢复共享同一授权 key 的页、活动、
下载、会话、总工具和墙钟限额。会话与业务调用均先耐久扣额，再进入原 FitClient；只够打开
会话却不够执行业务调用时不打开会话。完整响应才将活动预留量结算为实际返回数；响应未知
仍占用整页容量。因此剩余活动额度不足一整页时停止，不扩大查询来证明空页。
绝对截止时间、时间高水位及进程单调时钟一起约束调用；重启、回拨、搬迁和其他子 job key
不能重新领取。关闭会话属于必要收尾，保留单次超时上限；超出总预算不能再调用业务或
生成新的完成回执。模型墙钟绑定 Runtime、capability 与 prepared 身份，并实际传入
唯一 `model_process.execute` 监督器；授权截止早于模型墙钟时取更早截止。

## 导入、同步与批次邮件

```sh
python -m skills._shared.fit_weekly --instance /明确的新实例 import-history --archive /明确的已验证备份
python -m skills._shared.fit_weekly --instance /明确的新实例 --authorization authorization.json sync
python -m skills._shared.fit_weekly --instance /明确的新实例 --authorization authorization.json sync --date 2026-09-07 --date 2026-09-09
```

上述只是参数示例，不构成真实服务授权。导入只读验证显式备份，复用原登记身份、SHA、CRC、
完整备份权限和 immutable 恢复库验证。首次新实例在生命周期锁内初始化，重放保持幂等；
结果始终保留 `history_coverage=not_established`，不将已有FIT解释为2022起逐日查询完整。
普通 status/sync/weekly/daemon 不加载旧归档读取器。

sync 默认使用授权中的全部精确日期；可通过重复 `--date` 选择其中排序、不重复的子集。
连续日期合为一个原 SyncSpec，离散缺口保持分段；每段使用现有 `fit_sync.synchronize`、
`garmin_fit.open_session/FitClient` 和原 cache-only MCP guard，完整分页、空日、当日暂定、
无FIT、坏FIT、下载未完及关闭失败分别保留。首段失败后停止新业务调用，已完成子任务
仍只读复用。`run_sync.daily_dates` 返回今日、昨日、已知缺口及原 unfinished_jobs，
校验整组均在授权内，由 daemon 的到期槽位调用。

每次明确运行封存一个 `sync-batch:<摘要>` 回执，绑定整批日期、原子job身份、真实快照、
来源SHA及每次下载/关闭结果。邮件由 `publication.prepare_sync_batch` 从该封存来源生成，
使用原 MIME、Gmail REST 和发布账本；原单job `prepare_sync` API继续保留原行为。
封存中断后用原请求/捕获恢复；已封存结果重复执行直接读取，不改变原邮件或用新SHA重发。

批次邮件 action_key 为 `run_sync.action_key(grant, dates)`；收件人和发送账号来自指定服务
配置的 Email.md。新投递还需要账号标签和贴标 action，分别授权标签查询、创建、贴标与读回，见邮件配置。
需明确原 key、日期窗口及 gmail.profile/send/get 调用额度；响应丢失
后的只读恢复还可能需要 gmail.list，正常 Token 刷新另消耗 gmail.refresh。sync 许可本身
不允许邮件。缺邮件许可或配置时返回已封存同步批次和明确 mail blocked，Gmail零调用；
退出码5表示同步或邮件未全部成功。仅全部成功退出0，错误参数/配置退出2。

失败批次若需继续原未完成job，显式使用 `sync --recovery 1`，下一次为2，以此类推；
前一批次必须已封存且失败，不自动增加序号。恢复仍使用原授权、原SyncSpec和剩余额度，
不会续费，关闭审计 blocked 仍禁止恢复。新回执 key 增加 `:recovery:1`，其邮件需要
单独精确的 `run_sync.action_key(grant, dates, recovery=1)` 授权（可在初始动作清单列明）。
原已发邮件保持原内容，成功批次不允许新恢复。邮件unknown只能走原 `reconcile`，
不能通过 deliver 兜底；成功动作零重发。

## 生命周期和状态

已接通及后续所有写命令和 daemon 统一使用 `lifecycle.run(instance, command)`。
它持有独立 `lifecycle.lock`，拒绝第二写命令；业务函数仍自行短时取得 `writer.lock`。
`run_state` 统一保存 `runtime/runs/<序号>/start.json` 和 `stop.json`，追加不可变记录，
不向现有 `documents` 增加 kind，不修改数据库 Schema。停止记录绑定开始记录的 SHA。

只读状态核验实际 OS flock；PID 仅作为开始记录事实，不用于认定进程仍活着。
数据库用 `mode=ro` 和只读事务，不争用 writer.lock；SQLite 自身暂时排他锁、坏库或权限
会明确返回 `unreadable`，不会修改或创建实例恢复成假正常。当前存储使用 DELETE journal，
意外 WAL/SHM 不尝试恢复，明确不可读。

| 输出 | 含义 |
| --- | --- |
| `instance: uninitialized` | 实例不存在；status 退出 0，不创建。 |
| `lifecycle: running` | 观察到生命周期锁正被占用，数据库可独立报告不可读。 |
| `lifecycle: not_running` | 未占锁，无未终结的最新运行；正常结束、捕获信号和已记录失败见 last_run。 |
| `lifecycle: interrupted` | 锁已释放，最新运行只有开始记录，不能推断业务是否完成。 |
| `unreadable` | 权限、库、记录或状态转换无法可靠读取；status 退出 3。 |
| `business` | 已保存请求及同步批次中 pending/unknown/failed 数量；不执行模型或外部对账，不把 capture 未入账称为成功。失败批次是历史事实，后续新恢复回执不抹掉它。 |

SIGINT/SIGTERM 记录 stopped 并退出 128+信号；SIGKILL 无法写终止记录，OS 释放锁后
下次 status 判断 interrupted。普通异常只记录 failed，不保存异常消息。重启追加新序号，
保留旧记录与业务账本。若中断发生在开始记录写入前，保留原尝试目录并报告
`start_record: missing`，新尝试使用下一序号；业务在开始记录耐久保存后才能进入。
模型和 MCP 的业务进程另由 parent_watch 监护本次父进程与所在会话。
SIGKILL 后监护进程停止原会话及其他进程组的后代并退出；它不读写业务账本、不调度或重试任务。
原模型监督器继续负责超时、流量上限、实际停止确认和 capture。启动错误通过独立管道传回，
不会把业务主动返回125解释为未启动。监护只支持同一POSIX会话内的后代，不支持业务自行另建
会话逃离；同UID恶意进程和永久内核故障仍不属于承诺范围。

新增运行接口由 `runtime_resources.ENTRYPOINT_MODULES` 显式登记；
`runtime_resources.files(source, entrypoint=True)` 生成可独立运行入口的资源集合。
同步再指定 `collection=True`；显式历史导入可另外指定 `history=True` 纳入现有导入/只读
备份验证依赖。普通运行资源不包含归档内容，旧源码退役与依赖精简的实际证据见 [M12 执行计划](../../exec-plans/active/M12-fit-weekly.md)。
模型资源包含其实际调用的私有路径校验及原业务模块，入口资源另外纳入周协调、授权和发布接线。
资源登记模块本身变化进入源码身份。旧 Runtime 4 曾增加模型墙钟与授权截止；当前 Command Runtime 继续绑定这些边界，新的 capability 必须
绑定当前完整 Runtime 身份。旧 prepared/capture 按保存身份只读恢复，不能因此重新启动。

对应测试：`tests/code/contract/test_m12_entrypoint.py`、`tests/code/contract/test_m12_sync_command.py` 和
`tests/code/integration/test_m12_lifecycle.py`。真实子进程检查使用合成实例和本地等待进程，
不连接真实 Provider 或读取正式数据。

## 完整周任务与发布前编辑

```sh
python -m skills._shared.fit_weekly --instance /明确的新实例 --authorization authorization.json weekly --period-end 2026-08-09T07:00:00Z
python -m skills._shared.fit_weekly --instance /明确的新实例 --authorization authorization.json weekly --period-end 2026-08-09T07:00:00Z --phase draft
python -m skills._shared.fit_weekly --instance /明确的新实例 edit --period-end 2026-08-09T07:00:00Z --base-id ai --base-sha <原修订SHA> --revision-id reviewed --part summary --content review.json
python -m skills._shared.fit_weekly --instance /明确的新实例 --authorization publication.json weekly --period-end 2026-08-09T07:00:00Z --phase publish --revision-id reviewed --revision-sha <新修订SHA>
```

默认 all 一次完成完整窗口同步、两阶段、修订、Markdown/PDF 和发布。周窗口必须是香港
周日15:00的原截止时间，尚未到截止不执行。单个原同步job覆盖窗口两端香港日期，as_of
不早于截止；完整分页、FIT下载和关闭审计成功后才冻结输入。每日状态或单独截止日查询
不能代替完整前置。未冻结前中断继续原 job 与原授权剩余额度；冻结后恢复原 sync/input。

[模型模板](../config/examples/fit-weekly.model.template.json)只配置可替换的命令适配 ID（codex 或 claude）、实际可执行入口、Host instructions 和每阶段能力证明路径。模型、推理等级、Provider 来自环境原选择；不要求用户在产品配置或授权中再填写。

`coaching.command_contracts` 延迟创建两个 CommandAdapter，plan 后 summary。授权 v2 绑定原周、stage、CommandSpec 的命令 SHA（协议、实际入口和二进制 SHA）及墙钟/截止。只有尚未领取的阶段加载新配置；旧 v1 授权不能批准新命令。切换命令不重置阶段或每周细读预算，已有 success/unknown 继续原 profile、prepared 和输出 SHA，只读恢复。

命令语法、环境选择与输出提取集中在适配层；同一 `model_process`/`process_capture` 负责完整 stdin、真实进程退出、后代回收和耐久记录。Codex 使用原环境的选择和禁重试的同等 Provider 配置，Claude 继承环境选择并禁请求重试及断流备用请求。CLI终态输出经过严格 JSON、完整业务 Schema 和证据校验；不从日志寻找碰巧合法的 JSON。

实际环境选型与工具权限分开：不传用户指引、历史、Skill、插件、任意文件/命令能力；只接预绑定的 FIT MCP。凭据仅由 CLI 的已有认证机制或有限环境变量使用，不写 AI job 或身份快照。环境工具/配置漂移、未知适配、过期能力证据在新 intent 前停止。能力证明必须绑定当前源码、Schema、Prompt、实际命令与非秘密环境设置；配置存在不是已验收。细节与已验证边界见[命令运行器](command-runner.md)。

CLI 始终使用明确 `Grant.command.timeout_seconds`，授权截止更早时按更早时间停止。超时且确认停止为 failed；无法确认停止或 capture 不完整保持 unknown，不自动重试。

draft 只运行至可编辑修订及实际 Markdown/PDF，输出 revision_id、revision_sha256、pdf_sha256。
edit 接收实例内最大2MiB的私有 JSON 文件，显式基准ID/SHA与新ID；真正调用 R4 校验和渲染。
summary 编辑保持原计划，plan 编辑仍按原跑步输入重新校验；AI原文及原目标/历史不变。
发布封存后拒绝编辑。publish 只使用显式修订或已固定的原发布选择，不执行同步或模型；
不指定修订时采用原 ai 修订，不隐式选择“最新”编辑。

同一发布选择固定修订、收发人和 late。默认首次准备日期晚于原周日才标补发；
`--late` 可由已判定为补发的调用者显式传入，正常周同日执行不会因花费几秒误标补发。
恢复不会重算 late 或平移课表。过去且未领取的课程动作写入 skipped/past_date，已知成功不重做，
unknown不转成假成功；其余日期继续。每封邮件、创建和排期独立授权、独立记账；
缺授权/配置返回原 prepared/unknown 和固定错误码，其他有授权渠道仍可完成。
全部动作 success 或明确 skipped 时退出0，输出保留每项状态；pending/unknown/failed退出5。

## 本地恢复和外部只读对账

```sh
python -m skills._shared.fit_weekly --instance /明确的新实例 reconcile --period-end 2026-08-09T07:00:00Z
python -m skills._shared.fit_weekly --instance /明确的新实例 --authorization readonly.json reconcile --external --action-key weekly:2026-08-09T07:00:00Z:gmail
```

本地 reconcile 不需要配置或授权文件，只处理已存在的阶段 intent/capture，不启动缺失阶段；
可省略period-end检查已有全部周。外部必须列精确 action_keys，授权工具集合不得含 send、
upload_workout 或 schedule_workout；课程需同时列原 create/schedule 两个 key。
直接调用 Gmail/Garmin reconcile；prepared 未领取时零调用，success 零重放，完全丢失课程ID
保持 unknown，不能按名字认领或删除。Gmail可按已捕获ID或明确预算内的唯一Message-ID查询
恢复，再验证RAW及PDF SHA。外部对账不会通过 deliver 补发未执行动作。

完整入口离线集成测试为 `tests/code/integration/test_m12_weekly_entrypoint.py`，合成替身只在
模型可执行进程、MCP会话和HTTP传输边界。实际安装CLI的 --help 与版本仅证明公开参数可见，
不证明工具拒绝、细读完整交接、认证或真实模型能力；同一可执行文件的当前离线能力核对
已在R6-6及独立/Main验收中完成，证据见 [M12 执行计划](../../exec-plans/active/M12-fit-weekly.md)。真实服务仍须 R7 精确授权，离线通过不表示正式实例已启用。
