# TrainLab

TrainLab 使用 agentForge 0.4.2 的根目录开发 Harness；产品工程唯一位于
`source/`。根目录只维护开发规则、Roadmap、执行计划、技能和 CI，不再保留第二份
产品源码或产品运行 Harness。

## 目录边界

```text
TrainLab/
├── AGENTS.md rules.md memory.md PLANS.md
├── docs/ references/ skills/ .github/
├── data-backup/          # 本机忽略的旧数据归档
└── source/
    ├── AGENTS.md         # 无状态运行 Harness
    ├── skills/           # 本地 Skills、脚本与合同测试
    ├── templates/        # fixed/open-report 邮件外壳
    ├── config.json       # 非秘密运行参数
    ├── goal.module.md    # 可跟踪的脱敏目标模板
    ├── goal.md           # 私有用户目标，忽略
    ├── state/            # 私有 SQLite、raw 与运行状态，忽略
    └── requirements.txt
```

`data-backup/` 仅保存旧实例的可回滚归档，不是当前运行目录；它完全被 Git 忽略。
真实配置、数据库、raw、FIT、token、日志和 state 不会进入 Git，也不会被测试或发布
产物展示。

## 无状态运行

从仓库根目录执行 `codex exec -C source`。运行时先读取 `source/AGENTS.md`、`config.json`、
私有 `goal.md`、需要的 Skill 和 `state/trainlab.db`，再运行对应脚本；结果、状态、批准和
外部动作都追加写入 SQLite。当前只保留无状态 `auto.txt` Prompt，不安装或启用 cron。

## 安装依赖与检查

项目不要求仓库内 `.venv`，可使用用户选择的 Python 3.12 环境：

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

TrainLab 运行 Harness 位于 `source/AGENTS.md` 和 `source/skills/`，只接受有来源和 lineage
的有界输入。脚本负责读取 raw 并写入 SQLite，AI 负责受约束的解释和决策；Garmin、Gmail
和 Sites 的外部写入必须由各自明确授权的边界完成。产品不再包含历史自动 Orchestration、
Supervisor 或后台服务入口。

## 数据重建说明

旧实例已在本机归档到 `data-backup/<timestamp>/`。新 raw-first 数据库只从
Garmin raw/FIT 离线重建，不迁移旧 AI 报告、邮件、用户事实、交付或后台运行历史；
数据库完成完整性、外键、哈希和权限验证后已切换为 `source/state/`；旧 state 仍保留在
本机 `data-backup/` 的切换归档中。

## 开发规则

开始任何仓库工作前先阅读 [AGENTS.md](AGENTS.md)、[rules.md](rules.md)、
[PLANS.md](PLANS.md) 和当前执行计划。TrainLab 禁止使用
`orchestrate-parallel-work`，不得恢复 `.orchestration`、Graph/Dashboard 或旧
hash-bound 审批控制面。
