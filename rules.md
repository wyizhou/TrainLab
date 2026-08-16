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
