> 主 Agent 保存的原输出副本；仅将工作目录绝对路径替换为 `.`，检查结论未改写。来源：运行 `9556171e-b78b-463e-b039-a1511411897f` 的受管输出。

# ADHOC-0031 B1 / ADHOC-0024 T1-T3 Developer 事实报告

## 修改摘要

- 新增 `source/trainlab/fit/` 基础层：ParsedActivity/ParsedRecord 数据结构、FIT decoder 协议边界、SQLite 初始化与导入 API。
- `init_database()` / `initialize_schema()` 创建并保留 activities、records、activties_report、weekly_report、config；开启 `PRAGMA foreign_keys=ON`。
- `import_fit_file()` 使用实际 FIT 字节 SHA-256 作为 activity_id，并保存实例根相对 fit_path；真实 Garmin FIT SDK 解码尚未接入，当前通过受控 decoder 边界支持合成 FIT 测试。
- `import_activity()` 在一个事务中 upsert activity 并替换该 activity 的 records，不删除报告表/config；JSON 使用稳定序列化并拒绝 NaN/不可序列化值；record_index 按原解析顺序从 0 编号，重复 timestamp、不规则 timestamp、缺失 timestamp 和真实 0 均保留。
- `get_activity_facts()` 提供默认 AI 事实边界：basic/summary/segments/sensors/source_timestamps，不包含全量 records；sensors_json 拒绝嵌入 `records` 列表。
- 更新 `source/README.md` 与 `source/tools/README.md` 描述 B1 SQLite/ActivityFacts 边界；修正 `source/tools/check_b0_static.py` 使 `cd source && python tools/check_b0_static.py` 在未安装包时也能找到 `trainlab`。

## 文件清单与对应 AC/任务

- `source/trainlab/fit/__init__.py`：导出 B1 FIT/SQLite API（T3，AC-01..05）。
- `source/trainlab/fit/models.py`：合成/后续真实解析共用的 ParsedActivity、ParsedRecord、JSON 类型（T1/T3，AC-02/04）。
- `source/trainlab/fit/parser.py`：后续真实 FIT decoder 协议边界；当前不伪装真实 Garmin FIT 解码已完成（T1/T3）。
- `source/trainlab/fit/storage.py`：数据库初始化、FIT 文件导入、解析结果事务入库、默认 ActivityFacts 读取（T3，AC-01..05）。
- `source/tests/fit/test_storage.py`：新增合成 FIT/合成解析输入/SQLite 回归测试（T2/T4 前置自查，AC-01..05）。
- `source/tools/check_b0_static.py`：允许按任务命令直接运行静态检查（检查入口修复）。
- `source/README.md`、`source/tools/README.md`：同步 B1 边界说明（T3 文档）。

## 覆盖的验收点

- AC-01：测试核对五张表共存、activities 12 列、records 4 列、records 联合主键显式 NOT NULL、外键指向 activities；初始化后报告表/config 数据仍在。
- AC-02：测试保存全部合成 record，按输入顺序编号；重复 timestamp 保留两条，不按时间排序；不规则 timestamp 不补点；真实 0 保留；timestamp 合法缺失保留 NULL。
- AC-03：`get_activity_facts()` 不返回 records；sensors_json 仅保留设备/字段定义，若嵌入 records 列表则失败。
- AC-04：导入 activity 与 records 使用同一事务；非法 JSON/NaN、传感器嵌入 records、子行约束失败均不留下半场；同字节/同 activity 重导入替换 records 且不破坏报告表。
- AC-05：`import_fit_file()` 用实际 FIT bytes SHA-256；fit_path 保存为实例根相对路径；schema_version 保留；测试核对 has_running、parse_status、session_count、parser_version、data_revision、quality_json 不存在；初始化/导入不清空报告表。

## 实际版本与 Git 状态

- 工作目录：`.`
- 分支：`work/adhoc-0031-local-web-system`
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`
- `git status --short --branch`：仍显示既有未提交协调记录改动；`source/` 整体为未跟踪目录。未修改 PLAN.md、MEMORY.md、exec-plans/active/*。
- 暂存区：`git diff --cached --quiet` 退出 0，无 staged 文件。

## 检查表

| 命令 | 预期 | 实际/退出码 | 关键证据 |
| --- | --- | --- | --- |
| `cd source && python -m pytest tests -q -p no:cacheprovider` | pytest 全部通过 | 初次直接运行失败，退出 127：当前 shell 无 `python` 命令 | 已用 PATH 指向 B0 验证虚拟环境恢复运行 |
| `cd source && python3.12 -m pytest tests -q -p no:cacheprovider` | pytest 全部通过 | 失败，退出 1：`No module named pytest` | 系统 python3.12 未安装 dev 依赖 |
| `cd source && PATH=/tmp/trainlab-b0-fix-venv/bin:$PATH python -m pytest tests -q -p no:cacheprovider` | pytest 全部通过 | 通过，退出 0 | `24 passed, 2 warnings in 0.16s` |
| `cd source && PATH=/tmp/trainlab-b0-fix-venv/bin:$PATH python -m ruff check .` | Ruff 通过 | 通过，退出 0 | `All checks passed!` |
| `cd source && PATH=/tmp/trainlab-b0-fix-venv/bin:$PATH python -m mypy trainlab tests` | mypy 通过 | 通过，退出 0 | `Success: no issues found in 18 source files` |
| `cd source && PATH=/tmp/trainlab-b0-fix-venv/bin:$PATH python -m compileall -q trainlab tests tools` | 编译通过 | 通过，退出 0 | 无输出 |
| `cd source && PATH=/tmp/trainlab-b0-fix-venv/bin:$PATH python tools/check_b0_static.py` | B0 静态合同仍通过 | 通过，退出 0 | `B0 static contract check passed` |
| `git diff --check -- source/trainlab source/tests source/tools source/README.md source/pyproject.toml source/tools/README.md` | 无空白错误 | 通过，退出 0 | 无输出 |

## 未运行/未通过检查

- 未运行前端 lint/type/test/build：本次未改前端相关文件。
- 未运行真实 Garmin/FIT SDK/AI Provider/外部服务：本任务仅使用合成 FIT bytes 和合成解析输入，不读取私人 states 或真实 Provider。
- 直接 `python` 命令因本机 PATH 无 `python` 失败；已用同一 B0 验证虚拟环境通过等价命令，且命令中仍为 `python -m ...`。

## 未解决事项/风险

- 真实 Garmin FIT SDK 解码未实现；当前只冻结 decoder 协议和 SQLite 入库行为，后续 B4/真实同步接线需提供真实 decoder。
- 旧 D31-03A/B、D31-02A 仍未实现/未猜测；本次没有启动定时器、Web 业务 UI、真实同步或 AI 真实调用。
- `source/` 在当前 Git 状态下整体仍是未跟踪目录，独立验收时需按实际文件清单固定受审版本。
