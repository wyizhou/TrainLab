# TrainLab approved rules

## 维护规则

1. 只有用户与 Agent 已明确协商确认的内容才能写入本文件；Agent 不得单方面扩张授权。
2. 新约定按编号追加，并记录日期、适用范围、必须遵守的规则和事故背景。
3. 不得静默删除、弱化或改写已有约定。需要调整时，新增带日期的替代条目，并明确被替代的编号。
4. 本文件不得记录凭据、令牌、账号、个人健康数据、原始 FIT/JSON 内容或其他敏感信息。
5. 若本文件与系统、开发者指令或用户当前明确指令冲突，遵循更高优先级指令，并在继续前向用户说明冲突。

## A-001: Garmin 在线验收必须严格限定同步范围

- 确认日期：2026-08-09
- 适用范围：Garmin 在线验收、增量同步测试、重复同步测试、快照测试、审计测试，以及任何使用隔离数据库访问真实 Garmin Provider 的测试。

必须遵守：

1. 正式环境已经保存的 FIT、raw 和 SQLite 数据是离线清洗、解析、迁移和 AI 分析的首选数据源。不得仅为在线验收而重新抓取全部历史数据。
2. 隔离数据库用于避免污染正式数据，不代表允许扩大 Provider 请求范围。空隔离数据库不得回退到项目历史起点、配置历史起点或其他隐式默认日期。
3. 每次在线验收在获得批准前必须冻结并展示：
   - `Asia/Hong_Kong` 语义下的明确开始日期和结束日期；
   - 明确的资源类型白名单；
   - 最大 Provider entry 数量；
   - 最长墙钟运行时间；
   - 最大活动数量、FIT 下载数量和原始对象数量（适用时）。
4. 开始日期不得为 `null`。在第一次数据 Provider entry 前，程序必须验证开始日期、结束日期、允许跨度、资源白名单和所有预算；任何缺失、反序、超限或可能触发历史回退的情况必须 fail closed，Provider entry 保持为零。
5. 在线验收默认只获取满足验证目的的最小短窗口，例如明确的一天。扩大日期、资源、请求次数或运行时限属于外部影响扩张，必须生成新的编排计划版本和哈希并由用户重新批准。
6. 若执行中观察到请求范围或实际范围超出批准边界，必须立即停止且不得在同一计划版本中重试；保留脱敏证据，修复并完成离线测试和独立验证后，再提交新版本审批。
7. 隔离测试数据不得替换、合并进或冒充正式数据。不得因此删除或覆盖本地已有 FIT、raw、SQLite 或凭据。
8. 已成功完成的认证刷新不得仅因重跑数据验收而再次执行。任何新的认证刷新或凭据写入都必须有独立、明确的新授权和必要性证据。

事故背景：

> 2026-08-09 的 v5 Garmin 在线验收原计划使用短窗口，但增量请求只有结束日期、开始日期为 `null`。空隔离数据库没有同步游标，程序随后采用了 `2022-01-01` 的历史起点，使测试错误扩大为全历史重新获取。执行被停止，隔离证据被保留，正式 FIT、raw 和 SQLite 未被替换。该事故不是因为已有数据不满足要求，而是验收边界合同不完整。

## A-002: 开发 Harness 与产品 Harness 分层

- 确认日期：2026-08-12
- 适用范围：TrainLab 仓库开发、验证、产品运行和发布。
- 替代范围：只替代 A-001 第 5、6 条所述的开发编排载体；不改变其外部影响必须重新获得批准的安全要求。

必须遵守：

1. 仓库根 agentForge 只管理开发过程；`product/harness/` 只管理 TrainLab 产品运行行为。
2. TrainLab 开发禁止加载或调用 `orchestrate-parallel-work`，禁止恢复 `.orchestration`、Graph Dashboard、hash-bound handoff 或连续 attempt-version 审批机制。
3. A-001 要求重新批准时，使用一个明确更新范围的 agentForge exec plan 和用户批准记录，不再生成编排版本目录或 handoff hash。
4. 不卸载、不修改、不复制或链接用户级的全局 `orchestrate-parallel-work` skill。
5. `product/` 是唯一产品源码和运行根；`dist/` 只能由白名单构建，不得包含本地私有数据。
6. `product/src/trainlab/orchestration` 是产品业务模块，不属于本条禁止范围。

协商原因：

> 旧编排控制面为同一目标生成了大量版本、重复门禁和不稳定的 handoff，妨碍了开发和审计。用户决定采用 agentForge 的文件式 Roadmap 与执行计划，并与 TrainLab 产品运行 Harness 明确分层。

## A-003: TrainLab 采用 agentForge 0.4.2 根项目布局

- 确认日期：2026-08-12
- 适用范围：TrainLab 源码、测试、项目描述、产品 Harness、本地运行目录、构建和发布。
- 替代范围：替代 A-002 第 1、5、6 条中的 `product/` 路径和“根目录只管理开发过程”表述；
  保留 A-002 第 2、3、4 条以及其禁止旧控制面的全部安全目的。A-001 不受影响。

必须遵守：

1. 仓库根同时承载 agentForge 开发 Harness 和 TrainLab 项目；两者通过文件职责分层，
   不再通过 `product/` 目录分层。
2. `src/trainlab/` 是唯一产品实现，`tests/` 是唯一产品测试根；新功能测试使用
   `tests/<feature-slug>/`。根 `pyproject.toml` 和 `requirements.lock` 是唯一 Python
   项目描述与锁文件。
3. TrainLab 产品运行 Harness 位于根 `harness/`；根 `AGENTS.md` 等开发 Harness 不得
   当作产品运行提示，产品 Harness 也不得管理开发 Roadmap。
4. `state/`、`config/`、`logs/` 和 `test_data/` 是本地运行目录，继续执行现有私有数据、
   权限和 Git ignore 边界；不得因迁移改变数据字节或把私有内容加入 Git。
5. `dist/` 是 TrainLab 实际技术栈需要的白名单生成目录，可以保留，但不是源码且不得
   纳入 Git；构建产物不得包含运行数据、凭据或 agentForge 开发状态。
6. `product/` 在迁移完成后必须不存在；CI、质量门、构建、部署和文档命令均从仓库根执行。
7. `src/trainlab/orchestration` 是产品业务模块，不属于对旧 `.orchestration`、Graph、
   Dashboard 或 hash-bound handoff 控制面的禁止范围。

协商原因：

> 用户复核 agentForge 0.4.2 后明确指出，上一阶段把 `product/` 作为永久项目级适配是
> 错误解释；要求完全遵循最新版脚手架，将实现迁到根 `src/`、测试迁到根 `tests/`，
> 并同步更新其余项目结构与运行路径。

## A-004: 私人测试数据不得作为仓库测试夹具

- 确认日期：2026-08-12
- 适用范围：TrainLab 测试夹具、本地测试数据、隐私边界和跨设备验证。
- 替代范围：替代 A-003 第 4 条中把 `test_data/` 作为长期本地运行目录的表述；
  `state/`、`config/`、`logs/` 及 A-001 的正式数据保护要求不变。

必须遵守：

1. 仓库根不得创建或依赖 `test_data/`；测试需要的 FIT 由
   `tests/fixtures/synthetic_fit.py` 确定性生成。
2. 合成夹具不得从个人 FIT、健康数据、账号资料或生产数据库复制值或派生内容。
3. 私人测试资料若确需保留，必须位于仓库外，不得进入 Git、测试包或发布产物。
4. 构建器继续把 `test_data` 和 FIT 视为禁止发布内容，防止该路径意外恢复后泄漏。

协商原因：

> 历史私人 FIT 使测试依赖单台电脑，且没有必要作为长期样本保存。用户批准改用
> 合成夹具，在保持解析、错误和边界测试强度的同时删除项目内私人测试数据。

## A-005: 产品代码资源与私人实例数据分离

- 确认日期：2026-08-13
- 适用范围：TrainLab wheel、runtime bundle、本地实例、部署和生产入口。
- 替代范围：替代 A-003 第 3 条的根 `harness/` 路径，以及第 4 条中把私有运行目录
  视为源码 checkout 固有组成的表述；A-001、A-002 的旧控制面禁令和 A-004 不受影响。

必须遵守：

1. TrainLab 产品 Harness、schema、policy、公开默认值和邮件模板是不可变产品资源，
   随 wheel 存放于 `src/trainlab/` 对应包内；仓库根不得保留第二份运行时权威副本。
2. 私有配置、`state/`、`logs/`、数据库、raw、FIT 和凭据只属于外置 instance root；
   wheel、runtime bundle 和升级流程不得复制、覆盖、删除或展示这些内容。
3. 正式部署产物由标准 application wheel、锁定的运行依赖 wheelhouse、部署资产、
   安全示例和逐成员 SHA-256 manifest 组成；不得发布裸 `src/` 或源码 checkout 快照。
4. 构建器必须使用根 `requirements.lock` 的完整、带 hash 依赖锁，校验 application
   wheel、依赖 wheel 和 archive 成员，并提供解包前验证入口。`dist/` 仍只是一种默认
   生成位置，仓库日常状态不得依赖其存在。
5. 安装后的产品通过 `TRAINLAB_INSTANCE_ROOT` 定位实例；不得依赖仓库根 `.venv`、
   `PYTHONPATH=src`、开发 Harness、当前工作目录或源码相对路径。
6. `src/trainlab/orchestration/` 继续作为产品 Supervisor、定时调度和恢复层；它不属于
   已删除的 `.orchestration`、Graph/Dashboard 或 hash-bound 开发控制面。

协商原因：

> 用户要求把 TrainLab 收敛为 agentForge 0.4.2 根项目，同时形成真正可安装、可验证且
> 不携带私人数据的产品产物；开发 Harness 不能替代产品自动调度，源码 checkout 也不应
> 被当作正式安装包。

## A-006: 根开发 Harness 与 source 产品工程分离

- 确认日期：2026-08-13
- 适用范围：TrainLab 仓库布局、本机直接运行、测试、构建、实例数据和发布。
- 替代范围：替代 A-003 第 1～7 条与 A-005 第 1、2、4、5、6 条的目录路径和本机运行
  方式；保留 A-001、A-002 的旧控制面禁令、A-004 的私人测试数据禁令，以及 A-005
  第 3 条的安全发布产物要求。

必须遵守：

1. 仓库根只承载 agentForge 开发 Harness、Roadmap、exec plans、开发 skills/references、
   GitHub 配置、根索引和版本记录；TrainLab 产品工程完整位于 `source/`。
2. `source/trainlab/` 是唯一产品包实现；`source/tests/` 是唯一产品测试根；
   `source/pyproject.toml` 与 `source/requirements.lock` 是唯一产品项目描述和依赖锁。
3. 产品 Harness、schema、policy、公开默认值和邮件模板仍作为不可变包资源位于
   `source/trainlab/resources/`，不得在仓库根保留第二份权威副本。
4. 本机直接运行使用 `source/` 中的明确脚本入口，例如
   `python source/garmin.py auth` 或 `python source/trainlab.py ...`；脚本必须加载同一份
   `source/trainlab/` 产品代码，不得建立第二套实现。
5. 本机私有 `config/`、`state/`、`logs/` 和产品凭据位置收拢到 `source/`，真实内容继续
   被 Git 精确忽略；安全 example、README 和空目录标记可以跟踪。迁移不得改变私人数据
   字节、属主或权限。
6. `source/` 同时保留 tests、deploy、产品 docs、scripts、tools 和可选 wheel/runtime
   bundle 构建能力；发布产物仍必须排除私人数据、凭据、开发 Harness 和旧控制面。
7. 根不得恢复 `product/`、根产品 `harness/`、`.orchestration`、Graph/Dashboard 或
   hash-bound handoff；`source/trainlab/orchestration/` 仍是产品业务调度层。

协商原因：

> 用户希望一眼区分开发 Harness 与可运行产品：根目录只保留 agentForge，所有产品源码、
> 测试、依赖、配置与本机实例统一进入 `source/`，并可用一个 Python 脚本直接运行。

## Rule template

```text
## A-NNN: Title

- Confirmation date: YYYY-MM-DD
- Scope:
- Supersedes: none

Requirements:

1. ...

Reason:

> ...

## A-007: `source/` 单产品工程与离线 Foundation v4

- 确认日期：2026-08-13
- 适用范围：本仓库的产品源码、运行入口、测试、实例数据迁移和运行时教练 Harness。
- 替代范围：替代 A-003、A-005、A-006 中关于 `product/`、根 `src/`、wheel/bundle、Supervisor
  和产品 Orchestration 的路径与交付方式；A-001、A-002、A-004 的安全边界保持不变。

必须遵守：

1. 根目录只维护 agentForge 开发 Harness；TrainLab 唯一产品工程位于 `source/`，其唯一
   Python 源码包位于 `source/src/`，唯一测试根位于 `source/tests/`，唯一直接入口为
   `source/index.py`。
2. 不恢复 `orchestrate-parallel-work`、`.orchestration`、Graph/Dashboard、hash-bound
   handoff、Supervisor 或后台服务模板；产品 `orchestration` 目录和自动调度 CLI 已退役。
3. `source/pyproject.toml` 只保存 Python 版本、依赖和检查配置；不声明 wheel、bundle、
   setuptools 构建或 console-script 发布。日常运行使用 `python source/index.py ...`。
4. `source/config/`、`source/state/`、`source/logs/`、数据库、raw、FIT、token、凭据和
   `data-backup/` 私有忽略；只允许 README、examples、`.gitkeep` 进入 Git。
5. Foundation v4 新库只从 Garmin raw/FIT 离线重建，不迁移 AI 报告、邮件、用户事实、
   交付或旧调度历史；旧实例只原子归档到 `data-backup/`，不删除、不覆盖。
6. 运行时教练 Harness 只接受有界、可追溯的 schema JSON；课程和日报/周报合同必须经过
   确定性安全门。不得读取聊天、数据库、FIT、网络或凭据来替代有界输入。
7. 本阶段不调用 Garmin/Gmail、不发送邮件、不执行正式分析或 Supervisor，不提交、推送、
   发布或部署；完成必须由全新只读 Validator `PASS` 后再等待用户决定。

协商原因：

> 用户明确要求把开发 Harness 与产品工程分开，用 `source/` 直接运行，并清理历史
> Orchestration；旧实例数据需要可回滚归档，不能在迁移中丢失。

```

## A-008: AI + Skills 运行 Harness 与 raw-first 状态边界

- 确认日期：2026-08-15
- 适用范围：TrainLab `source/` 运行目录、Skills、无状态 cron、SQLite 状态、Garmin/Gmail
  适配器和本地报告流程。
- 替代范围：替代 A-003、A-005、A-006、A-007 中关于 `source/src`、`source/tests`、统一
  CLI、旧产品 Harness、Foundation 业务事实表、wheel/bundle 和后台运行层的交付要求；
  A-001、A-002、A-004 及其外部影响安全边界保持不变。

必须遵守：

1. `source/` 只保留运行时 Harness、六个本地 Skills、模板、非秘密系统配置、私有 goal 和
   私有 state；根目录继续只承载 agentForge 开发 Harness。不得恢复 `orchestrate-parallel-work`、
   `.orchestration`、Graph/Dashboard 或旧集中式 CLI。
2. 每次 `cron + codex exec` 都视为无状态运行。`source/AGENTS.md`、`config.json`、私有
   `goal.md`、对应 Skill 和 `source/state/trainlab.db` 是唯一恢复上下文；任何 Skill 的结果、
   状态、批准和外部动作必须追加写 SQLite，不得依赖聊天记忆或未记录的临时文件。
3. 健康与运动原始证据只保留为 owner-only raw 文件；新数据库不建立健康、睡眠或活动业务事实
   表。数据库只保存 raw 索引、活动采集控制状态、Skill 运行/输出、批准和外部动作。
4. Garmin 正常同步只处理昨日完整数据及今日早晨结束的主睡眠，不自动回读最近 14 天；补数、
   Garmin 写入、Gmail 读写和 Sites 发布均须有明确范围、批准、幂等记录和可对账结果。
5. `source/goal.md` 和 `source/state/**` 永远不入 Git；`goal.module.md` 只提供脱敏结构模板。
   AI、Skill 和定时流程不得自行改写长期 goal。用户或已记录的自动运行授权可以批准具体课表，
   但批准必须绑定输出 SHA-256。
6. 新建和迁移必须先在仓库外 owner-only candidate 中完成；正式 `source/state` 只有在 raw 哈希
   闭包、SQLite 完整性、权限、回滚和独立 Validator 通过后才可原子切换。旧 state 归档到
   `data-backup/`，不删除、不覆盖、不作为新系统数据源。
7. 本阶段只生成 cron 配置，不安装、不启用、不调用 Garmin、Gmail 或 Sites；完成后等待用户另行
   批准外部运行和提交。

协商原因：

> 用户明确要求运行层简单化为 AI + Skills，并让无状态 cron 可以仅靠文件和 SQLite 恢复；
> 原始健康/活动文件保留可重算证据，业务输出和动作状态集中落地 SQLite。

## A-009: AI + Skills 双层测试布局

- 确认日期：2026-08-16
- 适用范围：`source/` 运行 Harness 的确定性代码测试、AI 语义验收和持续质量门。
- 替代范围：仅替代 A-008 关于测试目录的约定；A-001、A-002、A-004、A-008 的数据、隐私、
  外部授权和 raw-first 边界保持不变。

必须遵守：

1. 确定性测试唯一位于 `source/tests/code/`，按 `unit/`、`contract/`、`integration/` 和
   `fixtures/` 组织；已退役的 `source/skills/_tests/` 不得与其并存。
2. AI 语义验收位于 `source/tests/ai/`，包含 cases、rubrics、schemas、templates 和被 Git
   忽略的 results；正常运行不得读取测试目录。
3. Schema、哈希、权限、状态机、幂等和外部副作用必须由 code 测试确定性判断；AI 评测只判断
   解释、证据一致性、训练合理性和是否编造，`REVIEW` 不得计为通过。
4. 测试只使用合成输入或仓库外隔离实例，不读取正式 goal、state、raw、凭据，不调用 Garmin、
   Gmail 或 Sites。AI 评测按需运行，不默认进入 PR CI。
5. CI 和质量门必须同时覆盖 `skills` 与 `tests/code`，并检查 `tests/ai` 的结构、Schema、隐私
   和忽略边界；不得通过删除测试、降低断言或静默忽略诊断取得绿灯。

协商原因：

> 用户希望把“代码是否正确”和“AI 是否按 Harness 产出”分开验收，同时保持无状态运行和私人
> 数据隔离；两层测试能分别提供可重复的机器门和可读的语义复核。

## A-010: Gmail REST 直接投递边界

- 确认日期：2026-08-19
- 适用范围：TrainLab 的 Gmail 认证、自投递、远端对账和崩溃恢复。
- 替代范围：仅替代 Gmail 必须通过 `@artymclabin/gmail-mcp` 的传输约定；Garmin MCP 与
  A-001、A-004、A-008、A-009 保持不变。

必须遵守：

1. Gmail 只允许官方 Gmail REST API，不得回退 Gmail MCP、SMTP 或 Codex Gmail Connector。
2. OAuth 使用 Desktop installed-app 浏览器流程，权限固定为 `gmail.send` 与 `gmail.readonly`；
   OAuth client、专用 token、邮箱地址和邮件正文不得进入 Git、SQLite 或公开日志。
3. 每封邮件必须先持久化确定性 intent，并使用稳定 RFC822 `Message-ID` 对账；发送开始后不得
   自动重发，响应不确定时只能查询该 Message-ID。
4. Candidate、owner-only 文件和单写者进程属于可信运行环境；SQLite 是运行账本，不承担对
   同 UID 恶意篡改、root、内核、磁盘或硬件故障的不可伪造远程证明。
5. REST message ID、RAW MIME、收件人、主题、text、HTML 与 Message-ID 闭合后才能成功；
   认证、权限、重复命中或内容不一致均安全停止。

协商原因：

> Gmail MCP 的跨进程结果保存与本地 SQLite 证明无法构成可靠远程事实根；用户批准改为官方
> REST API、稳定 Message-ID 和单写者恢复流程，并明确收敛应用层威胁模型。

## A-011: Gmail 实际 Message-ID 与单次发送对账

- 确认日期：2026-08-20
- 适用范围：TrainLab Gmail REST 发送、RAW 核验、崩溃恢复和 M10 邮件续跑。
- 替代范围：仅替代 A-010 第 3、5 条中“Gmail 必须原样保留本地预设 RFC822
  `Message-ID`”的假设；A-010 的 REST-only、OAuth、隐私、单写者和信任边界不变。

必须遵守：

1. 本地预设 RFC822 `Message-ID` 继续用于确定性 intent、MIME 和幂等键，但不得假设
   Gmail 会原样保留它。
2. `messages.send` 每个业务请求最多一次。响应丢失或无法确认进程停止时必须保持
   `unknown`，不得自动重发。
3. 发送成功必须同时绑定 Gmail message ID、该 ID 读回 RAW 中唯一的实际 RFC822
   `Message-ID`、收件人、主题、text 和 HTML；任一不一致都不得成功落账。
4. 成功响应和 RAW 已耐久化时，允许按 Gmail 实际 `Message-ID` 进行确认查询；
   查询必须唯一命中同一 Gmail message ID。
5. 已发送 canary 可以用既有 send/RAW 证据和用户明确收件确认做零 Provider
   追加对账；不得改写原始失败证据或补发第九封。

协商原因：

> M10 r06 真实 canary 的 Gmail `messages.send` 返回成功，且按 Gmail ID 读回的收件人、
> 主题、text 和 HTML 均一致，但 Gmail 将本地 `@trainlab.invalid` Message-ID 改写为
> Provider 实际 ID。用户确认收件后，批准保留本地幂等意图并以 Gmail 实际身份完成对账。

## A-012: M10 更正标题邮件批次

- 确认日期：2026-08-20
- 适用范围：仅限 M10 r08 的 8 封更正标题邮件。
- 替代范围：仅替代 A-011 第 5 条在原 r07 范围内“不得补发第九封”的总量上限；
  A-010/A-011 的 REST-only、单次发送、实际 Message-ID、内容核验、隐私和信任边界不变。

必须遵守：

1. r06/r07 已发送的 8 封及全部成功证据永久保留，不改写、不删除。
2. r08 获准新增恰好 8 个更正标题的独立业务请求，完成后邮箱累计恰好 16 封；禁止第 17 封。
3. r08 每个请求使用新的 MIME、批准、动作和本地 Message-ID；每个请求最多调用一次
   `messages.send`，不得复用或覆盖旧记录。
4. r08 第一封为 canary；Provider RAW 闭合且用户明确确认收到后，才允许发送其余 7 封。
5. 标题之外的 AI 输出、训练证据、安全判断和课表保持不变；正文样式债 TD-0002 继续延期。

协商原因：

> 用户确认旧 8 封已经全部收到，但标题设计错误，明确授权保留旧邮件并重新发送 8 封标题
> 正确的邮件。因此这是一个版本化的新业务批次，不是对旧请求的自动重发。

## A-019: agentForge v0.4.4 开发 Harness 与失败诊断合同

- 确认日期：2026-08-24
- 适用范围：TrainLab 根开发 Harness、exec plan、Worker、Validator 与 Failure Analyst 协作。
- 替代范围：仅替代 A-003 中“当前根开发 Harness 固定为 agentForge v0.4.2”的版本事实；
  A-003 的历史目录决策以及 A-001～A-018 其余规则继续有效。

必须遵守：

1. 当前根开发 Harness 固定适配 agentForge `v0.4.4`，上游 Tag 对象为
   `34f548d4fbf31d7850388b40997edaa4eb33ebad`，源码提交为
   `00e03cfb6e25e35967e414bea9233dc7b33929d5`。适配不得覆盖 TrainLab 的 `source/`
   产品边界、隐私、Skills、Git 或外部动作规则。
2. 每个新仓库任务必须在 exec plan 中保存冻结验证合同。初始 `VC-001` 随用户任务或批准计划
   冻结；合同至少包含 `AC-*`、`INV-*`、`TM-*`、`EX-*`、`GATE-*` 和修订记录。
3. Validator 可以使用新检查方法，但 `FAIL` 的每项阻塞发现必须绑定既有冻结标准或已批准规则。
   未绑定、合同含糊、证据不足或无法判断范围时必须返回 `INCONCLUSIVE`，不得触发实现修改。
4. 命中 `EX-*`、超出 `TM-*` 或提出新质量要求的发现只能作为 advisory 或
   scope-change candidate，不能阻塞当前合同。
5. 同一失败特征采用两种实质不同修法仍失败、连续三轮没有收敛，或直接发现冻结合同冲突时，
   任务必须进入 `blocked`、`blocker_type=DIAGNOSIS_PENDING`，不得继续自动补丁循环。
6. Failure Analyst 必须是全新、只读、未参与实施的 `high/high` Agent，只能归因为
   `IMPLEMENTATION_DEFECT`、`PLAN_CONTRACT_CONFLICT`、`VALIDATION_DEFECT`、
   `ENVIRONMENT_FAILURE` 或 `UNDETERMINED`。它可以读取失败历史，但不得修改实现、测试、
   合同或规则，不得替代 Validator 或宣布 `PASS`。
7. Validator 只接收逐字冻结合同、适用规则和当前仓库结果；历史 Validator verdict 与实施推理
   不得成为当前裁决证据。只有人工明确批准才能升级合同版本。
8. 本规则不授权修改 `source/` 运行 Harness、正式 state、外部 Provider、提交、推送、发布或部署。

协商原因：

> 用户要求将根开发 Harness 升级到 agentForge v0.4.4，以冻结任务验收边界、区分实现失败与
> 验证/合同问题，并通过独立 Failure Analyst 阻止 M11 继续出现无边界的补丁和验证循环。

## A-020: agentForge main 治理简化适配

- 确认日期：2026-09-05
- 适用范围：TrainLab 根开发 Harness、执行协议、计划模板和开发验证；不改变产品运行规则。
- 替代范围：仅替代 A-003 的根 Harness 旧版本事实，以及 A-019 第 1、2 条的固定版本和所有任务必建完整合同要求；A-019 的独立验证、失败诊断和历史记录要求保持有效。

必须遵守：

1. 开发脚手架固定适配 agentForge main `9964970d38df95bbd8fab53166c27c2e5648b82e`，属于 v0.4.4 之后更新，不称为新正式版本；保留 TrainLab 的 source、隐私、Git、Skills、测试和业务外部授权边界。
2. 单次只读分析和纯拼写/排版可轻量处理；跨会话只读工作保留简短检查点。代码、配置、功能或治理语义变化仍须正式计划、冻结合同和独立验证。命令、链接目标或约束含义变化不属于排版豁免。
3. 根 AGENTS 保留核心要求，详细执行协议集中于 docs/exec-plans/README.md；模板只有填写结构。正式合同必需批准来源、范围、AC 和适用 GATE，INV/TM/EX 按实际风险加入，不虚构或遗漏已批准要求。
4. 按角色读取上下文；Validator 不继承实施会话、不把 memory 或历史 verdict 作为裁决输入；Failure Analyst 为归因可以读取相关失败历史。AI 自选方法和未经确认假设不自动成为冻结要求。
5. 能力不足可直接选择充分档位，不强制逐档路线，不降低已选维度；合同争议、验证越界或环境故障不靠升级模型解决。既有失败诊断门保留。
6. 验证绑定合同和当前文件快照；语义变更须重新验证，纯粹记录真实结果、状态和归档链接可沿用原验证。串行任务不要求不存在的集成级验证。
7. 本规则不追溯改写旧计划、合同或失败记录，不授权产品重构、业务模型/Provider、正式 state 修改、部署或长期运行。Git 提交和推送仍逐次依据用户明确授权，本次授权记录于 ADHOC-0016。

协商原因：

> 用户要求将上游治理简化更新适配到 TrainLab，在保留授权、隐私、测试和独立验证的同时减少重复读取、填表与归档重验；随后明确批准完成后提交本地并推送远端一次。
