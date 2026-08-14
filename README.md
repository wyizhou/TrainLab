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
    ├── index.py          # 唯一直接入口
    ├── src/              # 唯一产品 Python 包
    ├── tests/            # 唯一产品测试
    ├── config/           # 仅 README/examples 跟踪，真实配置忽略
    ├── state/ logs/      # 私有实例目录，忽略
    ├── scripts/ tools/ docs/
    ├── pyproject.toml
    └── requirements.lock
```

`data-backup/` 仅保存旧实例的可回滚归档，不是当前运行目录；它完全被 Git 忽略。
真实配置、数据库、raw、FIT、token、日志和 state 不会进入 Git，也不会被测试或发布
产物展示。

## 直接运行

在仓库根目录执行：

```sh
python3.12 source/index.py --help
python3.12 source/index.py foundation status
python3.12 source/index.py garmin auth
python3.12 source/index.py analysis daily --report-date YYYY-MM-DD
python3.12 source/index.py analysis weekly --week-ending YYYY-MM-DD
```

入口会默认把实例根设为 `source/`；设置 `TRAINLAB_INSTANCE_ROOT` 可使用另一个
经过权限检查的实例目录。`index.py` 只转发到 `source/src/`，不复制业务实现。
运行报告默认不发送；任何 Garmin、Gmail、正式分析、同步或邮件交付都需要单独的
用户授权，本迁移不会自动执行。

## 安装依赖与检查

项目不要求仓库内 `.venv`，可使用用户选择的 Python 3.12 环境：

```sh
python3.12 -m pip install --require-hashes -r source/requirements.lock
cd source
python3.12 -m pytest -q
python3.12 tools/verify_repository_quality.py all
python3.12 -m ruff check src tests scripts tools index.py
python3.12 -m ruff format --check src tests scripts tools index.py
python3.12 -m mypy src
```

CI 的所有产品步骤都以 `source/` 为工作目录。`source/pyproject.toml` 只保存 Python
版本、依赖和测试/静态检查配置，不声明 wheel、bundle 或 console script 发布。

## 运行时边界

TrainLab 运行 Harness 位于 `source/src/resources/harness/`，只接受有 schema、来源和
lineage 的有界 JSON。分析层不自行读取数据库、FIT、聊天、网络或凭据；Garmin 和
Gmail 的外部写入必须由各自明确授权的边界完成。产品不再包含历史自动 Orchestration、
Supervisor 或后台服务入口，日/周分析和同步均通过显式一次性命令执行。

## 数据重建说明

旧实例已在本机归档到 `data-backup/<timestamp>/`。新 Foundation v4 候选库只从
Garmin raw/FIT 离线重建，不迁移旧 AI 报告、邮件、用户事实、交付或后台运行历史；
候选库完成完整性、外键、哈希和权限验证后才会成为 `source/state/`。

## 开发规则

开始任何仓库工作前先阅读 [AGENTS.md](AGENTS.md)、[rules.md](rules.md)、
[PLANS.md](PLANS.md) 和当前执行计划。TrainLab 禁止使用
`orchestrate-parallel-work`，不得恢复 `.orchestration`、Graph/Dashboard 或旧
hash-bound 审批控制面。
