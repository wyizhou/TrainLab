# TrainLab

TrainLab 根开发 Harness 适配 [agentForge main](https://github.com/wyizhou/agentForge/tree/9964970d38df95bbd8fab53166c27c2e5648b82e)
提交 `9964970d38df95bbd8fab53166c27c2e5648b82e`（v0.4.4 之后的治理更新，不是新正式版本）；产品工程唯一位于
`source/`。根目录只维护开发规则、Roadmap、执行计划、技能和 CI，不再保留第二份
产品源码或产品运行 Harness。

## 目录边界

```text
TrainLab/
├── AGENTS.md rules.md memory.md PLANS.md
├── docs/ references/ skills/ .github/
├── data/                 # 私有Goal、FIT及认证，全部忽略
├── data-backup/          # 忽略的旧代码、数据和失败证据归档
└── source/
    ├── AGENTS.md         # M12 产品边界与迁移状态
    ├── skills/           # 当前 FIT-only 模块及独立维护工具
    ├── tests/            # 当前活动产品的代码/AI 验收
    ├── goal.module.md    # 可跟踪的脱敏目标模板
    ├── goal.md           # 私有用户目标，忽略
    ├── state/            # 旧正式实例，最终切换前保持不变
    ├── private/          # 可选的新独立实例根，忽略
    └── requirements.txt
```

`data-backup/` 保存可回滚历史，不是当前运行、模型输入或 CI 的依赖；它完全被 Git 忽略。
真实配置、数据库、raw、FIT、token、日志和 state 不会进入 Git，也不会被测试或发布
产物展示。

## 当前：API 重构前的未验证源码快照

本次按用户要求将 `TrainLab-next` 的实际公开产品树（含未提交成果和删除状态）保存到
`source/`，仅作为后续重构的代码基线，**不是已验证的可运行版本**。用户明确不需要旧代码
验证，因此本次不运行功能测试、静态质量门或独立功能验收，也不追补缺失的历史校验记录。
提交前仅检查公开文件范围与私人资料排除；已有失败和证据缺口不改写为通过。

**后续转向直接 API 接入，不再依赖其他产品的 Agent 运行。** API 改造尚未实施；快照内
仍有现存 Agent/命令 runner，不能描述为已经替换。后续 API 方案与实现另行开展，旧 R7、
业务调用及正式实例切换不自动续跑。本次不改动主根开发 Harness 或现有 CI。

[来源产品说明](docs/product-contract.md)、[来源迁移记录](docs/migration.md)及 `source/docs/`
保存 next 的上下文；其中旧验收、阶段状态及外部计划链接仅供来源追溯，不代表当前主树通过。
本次范围和实际 Git 结果见 [ADHOC-0019](docs/exec-plans/active/ADHOC-0019-adopt-next-before-api.md)。
私人 `data/Goal.md`、`data/fit/`、`data/verification/` 和旧 `source/state/` 不进入 Git。

## 安装依赖与检查

以下为后续开发的既有检查入口，本次快照保存未执行，不代表检查通过。项目不要求仓库内
`.venv`，需要安装时另按实际授权使用用户选择的 Python 3.12 环境：

```sh
python3.12 -m pip install -r source/requirements.txt
cd source
python3.12 -m pytest tests/code -q
python3.12 -m ruff --config skills/_shared/ruff.toml check skills tests/code
python3.12 -m ruff format --check skills tests/code
python3.12 -m mypy --config-file skills/_shared/mypy.ini skills tests/code
```

CI 的所有产品步骤都以 `source/` 为工作目录；Ruff 和 mypy 配置位于
`source/skills/_shared/`。产品不再声明 wheel、bundle 或 console script 发布。

## 运行时边界

根 agentForge 继续管理开发，不承担产品调度。M12 由 Python 管理来源、SQLite、定时和
动作状态，AI 只负责每周受约束的解释/课程决策。有来源的运动 GPS、路线、地点与活动名称
可交给选定 AI，但不公开或进入 Git；原始 FIT 字节、凭据及任意文件/SQL能力不交给模型。
Gmail 仅官方 REST，Garmin 写入需通过既定前置门与精确授权，Sites 不在新方向内。
不恢复旧 Orchestration、Supervisor、cron 或开机自动服务。

按 A-023，批准的新方案必须在同批次退出被替代的实现、入口和验收，更新配置/Schema/Prompt/CI
与文档。旧失败保留原文；必要安全测试按能力迁移，不以保留全部旧业务作为新系统完成条件。

## 历史数据说明

M12 之前的实例已在本机归档到 `data-backup/<timestamp>/`。当时的 raw-first 数据库只从
Garmin raw/FIT 离线重建，不迁移旧 AI 报告、邮件、用户事实、交付或后台运行历史；
数据库完成完整性、外键、哈希和权限验证后切换为 `source/state/`。M12 将另外建立新库，
目前尚未切换；本机旧数据和新的恢复归档均保留，不把归档作为新运行依赖。

## 开发规则

开始仓库工作先阅读 [AGENTS.md](AGENTS.md) 并通过 Git 检查，再按角色加载适用规则和必要上下文。
主协调 Agent 恢复项目状态；Worker 只接收获批目标与实现范围；Validator 不加载 memory 或计划历史。
详细规则统一在 [执行协议](docs/exec-plans/README.md)，[计划模板](docs/exec-plans/template.md) 只提供填写结构。TrainLab 禁止使用
`orchestrate-parallel-work`，不得恢复 `.orchestration`、Graph/Dashboard 或旧
hash-bound 审批控制面。

## 开发、验证与失败诊断

| 工作 | 适用流程 |
| --- | --- |
| 单次只读分析、纯拼写或排版 | 依据和适用检查即可，不强制完整计划或独立验证 |
| 跨会话只读分析 | 保存简短目标、证据、检查点和下一动作 |
| 代码、配置、功能或治理含义变更 | 正式计划、冻结验收、测试与独立验证 |
| 实际并行开发 | 正式流程加独立 worktree、任务级与集成级验证 |

轻量不等于改动少：命令、链接目标、配置值或约束含义变化均属于正式任务。
正式合同以 `AC-*` 和适用 `GATE-*` 为核心，按实际风险加入 `INV-*`、`TM-*`、`EX-*`，
不为填表虚构要求；AI 实施方法和未确认假设不自动成为验收要求。全新只读 Validator
只接收冻结合同、适用规则和当前结果，可以创造检查方法，但不能增加验收要求。

验证绑定实际受审文件快照，不以 HEAD 或历史 PASS 代替未提交内容检查；语义变更后重新验证。
仅追加真实结果、同步状态和归档链接不重新启动验证循环。能力不足时直接选择充分档位，
不要求固定逐档升级，不降低已选维度；合同争议和环境故障不靠升级模型解决。

- `PASS`：当前结果满足全部适用标准；
- `FAIL`：有可复核证据证明当前结果违反已绑定的冻结标准；
- `INCONCLUSIVE`：证据不足、环境不可用、合同含糊或报告未绑定标准，不能可靠判断。

同一失败用两种不同办法仍未解决、连续三轮没有收敛，或直接发现合同冲突时，任务进入
`DIAGNOSIS_PENDING`。独立 Failure Analyst 可以读取失败历史，判断属于实现、规划合同、验证、
环境或暂时无法确定；它不能修改文件、改变合同或代替 Validator 宣布通过。

```mermaid
flowchart TD
    A["冻结任务合同"] --> B["实现与测试"]
    B --> C["独立 Validator"]
    C -->|PASS| D["归档或下一任务"]
    C -->|INCONCLUSIVE| E["补证据、等环境或请用户澄清"]
    C -->|FAIL| F{"达到诊断条件？"}
    F -->|否| B
    F -->|是| G["Failure Analyst 归因"]
    G --> H["按归因修复、换 Validator、等环境或请用户决定"]
```
