# ADHOC-0031 B0 首次独立验证

## 结论

**失败：当前0031-T1工程底座及0031-T2公共合同不能整体验收通过。**

- 已有Python检查、前端测试/静态构建、部分SQLite/时间/内存合同通过。
- 已复现：缺React和前端lint/type入口、缺pytest声明、SQLite主键空值约束不一致、静态根软链接泄露合成密钥、历史时间依赖本机时区。
- T2仍是部分骨架，完整JSON、错误、重复、授权和容量接口未闭合。不能以常量/列数测试通过代替合同冻结。
- **B1～B7产品行为未验收**；其尚未实现不是本报告另加的B0功能缺陷。未调用真实业务、读取正式states或启动正式调度器。

首次验证，无历史问题裁决、修法或复验材料。以下是独立结论，不代替主Agent最终验收。

## 受验版本与环境

- 分支：`work/adhoc-0031-local-web-system`。
- HEAD：`9db8bb1dda5922e85fe42581e27d2428dbc9f195`；25个`source/**`文件均为未提交新增。
- 固定副本为派发指定审核根`trainlab-0031-b0-review-djgcz9jg`中的`baseline/`。下文`S`表示该根的`scratch-validator/`，`E`表示`evidence-validator/`；产品文件名均用项目相对路径。
- manifest SHA-256：`4a035b2641708f4bee47c4be84929aac9a90333047bd53557306fc8325360d24`。
- 25个source文件聚合SHA-256：`71c2bbac5b502e8afcb571c57791dc309a28f175ee658bcd5c3822bdb566f25a`。算法为按路径排序，将`路径 + NUL + 文件SHA256 + NUL + 模式 + LF`连接后取SHA-256。
- 开始及结束均核对固定副本29个文件的SHA/模式，以及原仓库25个source文件的SHA/模式和文件集合，**无变化**；scratch运行前与baseline一致。父级记录修改未纳入source冻结对象。
- 未修改、暂存或提交仓库文件；最终暂存区为空。证据：`E/freeze-initial.json`、`E/freeze-final.json`。
- Python 3.12.13、uv 0.12.3、Node 26.5.0、npm 11.17.0。声明依赖可安装，未遇基础设施阻塞。验证环境及仅声明依赖环境都位于S，没有使用仓库`.venv`或全局安装。
- 完整依赖版本：`E/dependencies-freeze.log`。pytest 9.1.1及httpx 0.28.1是Validator额外安装的测试依赖；**不能用补装后的通过证明项目依赖声明完整**。

## 场景与实际结果

命令中`P=S/venv/bin/python`。默认工作目录S，`PYTHONPATH=S/source`；前端命令在`S/source/frontend`，mypy在`S/source`。完整参数、工作目录及逐命令退出码保存在`E/commands.json`、`E/followup-commands.json`。独立场景完整代码在`S/test_independent_b0.py`。

| 场景 / 对应要求 | 类型、命令或步骤 | 预期 | 实际、退出码 | 证据 |
| --- | --- | --- | --- | --- |
| S01 / U31-06冻结 | 比对manifest、baseline、原仓库source，结束重复核对 | 摘要、模式、集合、HEAD不变 | 通过；两次核对退出0，25个source不变 | `E/freeze-initial.json`、`E/freeze-final.json` |
| S02 / T1依赖 | 隔离venv；`uv pip install --python S/venv/bin/python -r source/pyproject.toml --extra dev pytest httpx` | 声明及测试必要依赖可用 | 安装退出0 | `E/dependencies-install.log` |
| S03 / T1声明自足 | 新建`S/declared-venv`，仅安装pyproject声明的运行/dev依赖；`S/declared-venv/bin/python -m pytest source/tests -p no:cacheprovider` | pytest入口可运行 | 安装0；pytest退出1：`No module named pytest` | `E/declared-only-install.log`、`E/declared-pytest.log` |
| S04 / T1现有测试 | `P -m pytest source/tests -vv -p no:cacheprovider`；`P -m unittest discover -s source/tests -v` | 现有测试可运行且有效断言成立 | 各退出0，均9通过；是同一组测试，不是18项独立覆盖 | `E/pytest.log`、`E/unittest.log` |
| S05 / T1静态检查 | Ruff `check --no-cache source`；mypy `trainlab skills tools tests`；`P -m compileall -q source` | lint、strict type、编译通过 | 均0；mypy检查15个文件 | `E/ruff.log`、`E/mypy.log`、`E/compile.log` |
| S06 / T1目录 | `P source/tools/check_b0_static.py`；人工核对目录及导入server | 无被禁止旧入口；脚本、前端输出位置正确 | 命令0；无`source/src`、`source/index.py`；实际factory可导入。共享实现位置另见未闭合项 | `E/static-contract.log`、`E/manual-audit.md` |
| S07 / T1前端基础 | `npm run lint`、`npm run typecheck`；检查依赖及构建源码 | 有React依赖和真实lint/type入口 | 两命令各退出1：Missing script；依赖为空，无React实现 | `E/frontend-lint.log`、`E/frontend-typecheck.log`、`E/independent-observations.json` |
| S08 / T1构建、测试 | `npm test`；`npm run build`；比对产物SHA | 本地测试及构建成功，默认输出后端web | 各0，3个node测试通过；HTML/CSS均输出到指定目录且与baseline字节相同；只是字符串静态壳 | `E/frontend-test.log`、`E/frontend-build.log`、`E/independent-observations.json` |
| S09 / T2实际DDL | 内存SQLite执行全部DDL，读取`PRAGMA table_info` | 四表12/4/3/3列及config三列与声明一致 | 列名、类型、数量通过；独立用例通过 | `E/independent-observations.json`：`sqlite_table_info` |
| S10 / U31-05关系与全文 | 显式开启外键；乱序插入records后按index查询；重复键/孤儿行；126000字合成报告；删周报后再插入 | 原序可重建；重复时间点保留；复合键/外键有效；全文保真；ID自增 | 独立用例通过。未将原生SQL操作冒充仓储服务或事务验收 | 同上：`sqlite_normal` |
| S11 / T2空值错误 | activities、activties_report、config分别插入两条NULL主键 | 声明`nullable=False`应拒绝 | 3个独立用例失败；三表都存下2条NULL主键 | 同上：`null_primary_key_*`；`E/independent-pytest.log` |
| S12 / U31-02、04时间 | 有时区输入跨UTC日/年，七天窗口，凌晨4点前一微秒/恰好4点，无时区时间 | UTC转换与七天长度正确；无时区输入明确拒绝 | 时间helper用例通过；恰好4点的next函数返回次日，仅记录其当前语义 | 同上：`schedule_boundary` |
| S13 / U31-02命名 | 合成字节取SHA；UTC日期或None；非法摘要及路径字符 | 正常`日期-SHA.fit`或`unknown-SHA.fit`，拒绝错误摘要 | 正常及上述错误输入通过；另观察到无效日历日期/全角数字仍可接受 | 同上：`filename_calendar_validation_gap` |
| S14 / U31-04内存历史 | 两实例隔离、snapshot后clear、新进程重建 | 无串话、无持久化 | 独立用例通过；未连接DB或私人状态 | `E/independent-pytest.log` |
| S15 / T2时间错误 | history.append传无时区`2026-09-16 00:00`，分别设置`TZ=UTC`和`TZ=Asia/Shanghai` | 不应随机器时区隐式改变绝对时刻；与ensure_utc一致拒绝不明确时间 | 独立断言失败；两探针均0但输出分别为`2026-09-16T00:00Z`、`2026-09-15T16:00Z` | `E/history-naive-utc.log`、`E/history-naive-shanghai.log` |
| S16 / T2错误壳 | 构造成功及RESOURCE_LIMIT失败envelope，再JSON往返 | 成功/失败字段自洽，无半份data | 合成用例通过；仅证明构造函数，不证明真实工具/容量执行 | `E/independent-observations.json`：`envelopes` |
| S17 / U31-01私有边界正常 | scratch合成states；真实create_app+TestClient请求HTML、CSS、health、私有路径、编码遍历、文件软链接 | 正常200；私有内容不返回 | 正常3项200；私有路径、编码遍历、指向合成ai.json的单文件链接均404 | 同上：`actual_http` |
| S18 / 私有边界错误 | `validate_static_mount(WEB_STATIC_DIR / '../../../../states')`；独立合成实例把静态根链接至合成states，真实factory请求`/ai.json` | 拒绝越界目录及指向私人目录的静态根 | 两用例失败：路径校验放行；真实HTTP为200并含合成密钥标记 | 同上：`accepted_static_escape`、`static_root_symlink` |
| S19 / T2公共接口完整性 | 人工检查全部source合同、工具README及factory真实JSON | 有可冻结的DTO/JSON、错误映射、时间/重复、权限/容量合同 | 未闭合；health/404也未使用现有envelope。`/api/activities`为404仅说明B6未实现，不另算功能缺陷 | `E/manual-audit.md`、`E/independent-observations.json` |

独立运行命令：`P -m pytest test_independent_b0.py -vv -p no:cacheprovider --basetemp=pytest-temp`，**退出1：11通过、8失败**。8个失败断言归并为下面001～005；006来自合同人工核对。测试报告另有依赖弃用警告，没有因此跳过检查。

## 问题与最小复现

### V31-B0-001：前端工程底座缺React及lint/type检查

- 对应：U31-01、0031-T1。位置：`source/frontend/package.json:6-11`、`scripts/build.mjs:10-21`、`src/app-contract.mjs:15`。
- 最小复现：在frontend运行`npm run lint`、`npm run typecheck`，均报Missing script；检查package依赖为空，build只将字符串写入HTML/CSS。
- 预期：本批建立面向React的依赖和实际本地lint/type/test/build基础，不要求本批完成B6业务页面。
- 实际/影响：test/build通过不能证明React基础或lint/type门已建立。**阻塞T1整体通过。**
- 证据：S07/S08及`test_declared_frontend_is_react_base`。

### V31-B0-002：声明依赖无法运行要求的pytest入口

- 对应：0031-T1、U31-06。位置：`source/pyproject.toml:11-15`。
- 最小复现：空venv仅安装`pyproject.toml`的运行依赖与dev extra，再执行`python -m pytest source/tests`。
- 预期：声明的开发依赖支持本批要求的pytest本地检查。
- 实际：退出1，`No module named pytest`。现有unittest测试本身能运行，补装pytest后9项也通过；缺陷是工程入口不自足，不是测试断言失败。
- 证据：`E/declared-pytest.log`。

### V31-B0-003：SQLite TEXT主键允许NULL，与非空声明不一致

- 对应：0031-T2、U31-05。位置：`source/trainlab/contracts/schema.py:29,51,63,74,112,139`。
- 最小复现：内存库执行DDL并开启外键，连续两次执行`INSERT INTO config VALUES(NULL, '{}', '2026-09-16T00:00:00Z')`；activities和activties_report按独立测试提供其余合法值也同样复现。
- 预期：标记`nullable=False`的身份字段拒绝NULL。
- 实际：三表各接受两条NULL身份记录。SQLite普通`TEXT PRIMARY KEY`不自动提供所声明的NOT NULL语义；外键开启也不能阻止NULL报告ID。
- 影响：活动身份、报告关联、配置唯一身份的合同无法成立。**不能因列数正确判DDL正确。**
- 证据：`E/independent-observations.json`中的三组`null_primary_key_*`及PRAGMA结果。

### V31-B0-004：静态目录校验只检查词法父路径，可放行私人目录

- 对应：U31-01、U31-06及私有路径边界。位置：`source/trainlab/contracts/paths.py:58-67`、`source/skills/local-web/scripts/server.py:41`。
- 最小复现：
  1. 直接调用`validate_static_mount(Path('source/skills/local-web/web/../../../../states'))`，未抛错。
  2. 在独立合成实例下创建含合成密钥标记的`states/ai.json`，将`source/skills/local-web/web`设为指向该states目录的软链接。
  3. 以该实例为cwd调用受审`create_app()`，用TestClient请求`/ai.json`。
- 预期：拒绝越界/私有静态根，不提供私有文件。
- 实际：步骤1放行；步骤3响应200并包含合成密钥。
- 影响边界：**根软链接配置下确有泄露**。正常目录、普通编码URL遍历以及目录内指向私密文件的单个软链接测试都被挡住；不宣称远程请求可自行替换本机静态根，也未泄露真实秘密。
- 证据：`E/independent-observations.json`中的`static_root_symlink`；最小测试`test_real_app_rejects_static_root_symlink`。

### V31-B0-005：内存历史把无时区输入当本机时间，UTC合同不一致

- 对应：0031-T2统一时间、U31-04历史。位置：`source/trainlab/contracts/session.py:20-21`。
- 最小复现：同一`history.append('user', 'synthetic', datetime(2026,9,16))`在`TZ=UTC`和`TZ=Asia/Shanghai`的子进程运行。
- 预期：明确拒绝没有时区的输入，或遵循已冻结的明确解释；不能悄悄依赖运行机器的时区。现有`ensure_utc`已选择拒绝无时区输入。
- 实际：相同输入得到相差8小时的UTC时刻。该问题不影响已验证的“历史只在内存保存”结论。
- 证据：`E/history-naive-utc.log`、`E/history-naive-shanghai.log`。

### V31-B0-006：T2公共接口仍未形成精确合同（验收缺口）

- 对应：0031-T2要求的DTO、JSON、错误、时间/重复、授权/预算/容量合同；不是要求提前实现B1～B7。
- 复核入口：`source/trainlab/contracts/`、`source/tools/README.md`、`source/skills/local-web/scripts/server.py`。
- 当前只有列/DDL元数据、通用envelope、路由名称、时间函数和工具文字边界。尚未定义/证明：
  - 活动JSON四类字段、records和报告/API/工具的精确输入输出结构与缺失值规则；没有相应可执行JSON Schema检查入口。
  - 具体错误到API/工具结果的映射；实际health返回`ok/service/b0_contract_only`，404返回`detail`，并未使用公共envelope。
  - 重复导入/报告及冲突处理合同、七天端点包含关系、统一时间锚传递。
  - 宿主可信授权作用域、真实running判定与资料白名单的接口；README文字不是授权执行合同。
  - 技术容量不足时整体失败、无部分输出/保存的合同；只有RESOURCE_LIMIT枚举。
  - 周报“无活动”和“有活动但缺报告”的明确分支；固定文本常量不能证明分支已定义。
- 预期：以上实施前公共接口可供后续阶段依赖；无需现在接通真实同步、AI或业务页面。
- 结论：**T2仅部分骨架，不能冻结或标记完整B0通过**。不擅自设定具体JSON字段、窗口包含规则、技术阈值或费用上限。
- 证据：`E/manual-audit.md`、`E/independent-observations.json`中实际HTTP JSON。

## 未验证事项、残余风险与停止范围

1. B1～B7：未验真实FIT解析/完整采样、业务仓储事务、宿主授权执行、下载分页/去重/不改旧原件、认证刷新/MFA、正式调度、AI协议循环、三模式Context、缺报处理、报告自动写入、浏览器视觉/搜索以及完整8080系统。现阶段没有相应实现，**无法判断，不记通过**。
2. 命名函数仍接受`20260230`及全角数字；实际日期应由UTC转换得到，但对外字符串输入的精确校验未闭合。没有实际下载器，不能据此证明“使用实际FIT字节SHA”在业务上得到执行。
3. 已核实禁止旧目录不存在、运行脚本和web产物位置正确。公共基础设施实际位于`source/trainlab/contracts/`，`source/skills/_shared/scripts/contracts.py`只是转导出；提供材料未说明该布局与“共享基础设施在_shared/scripts”之间的关系。**完整目录A共享分层合规不能直接记通过**，该部分停在客观位置核对，交主Agent核对批准范围；未擅自新增禁止包目录规则。
4. config配置键名仅作静态元数据核对，未读取私人配置，因此不声称真实配置可用。依赖全部可安装；没有环境故障需要恢复或重试。实际HTTP检查只用合成根和TestClient，所有上下文已关闭，没有遗留服务。
5. 已有9个Python、3个前端测试主要检查常量、少量正常helper及DDL建表；不会发现本次复现的NULL主键、静态根软链接及naive时间问题。Ruff/mypy/compile通过不能替代这些边界测试。
6. 证据位于审核临时根，建议主Agent按项目规则保存其必要公开/合成部分后再清理临时目录。Validator未改协调记录，也未读取Developer报告或历史裁决。
