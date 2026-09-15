# ADHOC-0019：Goal保留、主目录检查点及采用next代码

- 状态：`active`；日期：2026-09-14；Main协调，严格串行。
- 用户新指令：把goal添加到TrainLab/data，先在TrainLab提交，再以TrainLab-next代码为准添加回主目录，提交本地及远程，并在commit说明后续转向API接入、不再依靠其他产品的agent。
- 主根main：`25e8b92cd170809610d2e5feb4dbdb0033594ff2`；来源next分支codex/m12-completion：`7125a30f8d58e948516d72df39c1d5fb8d21d1d3`，采用其实际未提交树，不只HEAD。
- 原主树53项变更（46 tracked修改、7 untracked），暂存为空。next 87修改/226删除/93 untracked。两个HEAD可达对象无缺失，Git作者已配置；旧其他Git管理区失败不改写、不自动修复。
- 两仓origin均为`https://github.com/wyizhou/TrainLab.git`。用户已明确授权本次主目录本地提交和正常远程推送；不强推、清理外部目录、发布或部署。

## 冻结合同

<!-- VC-001-BEGIN -->

- 合同版本：`VC-001`；状态：`frozen`；来源：2026-09-14用户本轮明确指令及根适用安全规则。
- 目标：保留私人Goal；先保存当前主目录本地检查点，再将next现行产品代码、适用测试/依赖/资源/文档整合为主目录唯一产品工程，记录API后续方向并本地提交、正常推送主仓origin/main。

| ID | 验收要求与批准来源 |
| --- | --- |
| AC-01 | 将既有`TrainLab-data/m12/Goal.md`完整原字节复制为`TrainLab/data/Goal.md`，原件不动、目标0600、data0700，保留全部当前FIT和两份认证。私人Goal、FIT、凭据/数据库/运行日志不进Git或公开输出。来源：用户Goal请求及A-004。 |
| AC-02 | 在替换主产品代码之前，先形成一次本地检查点提交，保存本轮起始主树中已存在的公开tracked/untracked成果与真实协调记录；精确审查暂存白名单，不`add -f`私人资料。检查点仅证明当前成果被保存，不冒称旧产品功能完整通过，也不修旧代码来取得基线绿灯。来源：用户“然后在TrainLab下提交”的明确顺序及原工作保护。 |
| AC-03 | 以next实际当前公开产品树为权威，包含其未提交新增/修改及删除；不从next HEAD复原已删除旧业务，不与主旧实现拼接两套有效逻辑。保留主.git、根开发Harness及历史证据，source/仍为唯一产品工程；仅做接回主路径、适用文档/规则/CI一致性所必需的适配。来源：用户“以TrainLab-next目录的代码为准添加回TrainLab”及A-002/A-023。 |
| AC-04 | 采用next已确认两阶段plan/summary、自然语言Goal、邮箱/runner配置及FIT v3时间/字段等现行产品语义，来源为操作前next的docs/product-contract.md及source实际树；同批对齐受影响rules/产品合同/入口/Schema/Prompt/测试/文档，不使旧主产品目标或next开发流程反向覆盖本次授权和主Harness。next原“另一开发路线不改”和仓库外私有位置对本次明确代码接回及ignored data保留不构成禁止；其他业务安全界限保留。来源：用户指定next为准，先前已确认next产品方向，A-023。 |
| AC-05 | 最终提交信息明确表达“后续转向直接API接入，不再依赖其他产品的Agent运行”。本次是API改造前的next代码基线，不提前实现API、不声称已退出/替换现存Agent runner或已经具备API能力，不继续真实R7。同步README/Unreleased说明此方向与现状。来源：用户commit说明要求；未来方向不是立即功能实施授权。 |
| AC-06 | 完成当前整合结果的适用离线检查及全新独立验证后，在TrainLab本地提交，再正常推送既有origin/main；核对实际远端HEAD及适用CI。不force、不擅自rebase/丢弃远端新提交；远端变化/权限失败时停下报告。不创建PR/发布/部署或其他远程资源。来源：用户本地及远程提交请求、A-019/A-021。 |
| INV-01 | 原next、TrainLab-data、handoffs、其他工作树和主data-backup均原地保留；不写其工作树/Git或私人资料。主source/state、原Goal/Email/凭据与现有data/fit、verification不改字节；不连接原SQLite或操作sidecar，不启动产品/daemon/Provider、模型业务或认证刷新。代码测试只用合成输入/隔离临时实例；不把扫描原件当业务调用。来源：根数据与外部动作安全边界。 |
| INV-02 | 既有失败/INCONCLUSIVE记录不改判。ADHOC-0018原“data仅两目录”的布局目标被本轮明确新增Goal.md替代该处边界，其历史删除证据不足不自动修复/判PASS，不阻塞对本轮起始已存在566份FIT字节的精确保护。来源：用户新增Goal请求，历史记录真实边界。 |
| GATE-01 | 修改前记录主/next tracked/untracked/删除/模式/内容SHA，Goal来源与data/state保护基准、精确产品复制/删除集合；不覆盖ignored私人文件或未确认碰撞。相对源码的适配差异有理由及测试，来源树前后不变。来源：执行协议快照及保护要求。 |
| GATE-02 | S1检查点门：全新只读Validator核Goal原字节/权限/ignore、当前公开主树白名单与秘密边界、已有成果保全、Git身份及可达对象、适用syntax/JSON/diff检查；核第一提交仅快照性质，不评价或修复被替代旧产品的完整业务。不将此PASS当整合交付PASS。来源：检查点目标、独立验证及用户先提交顺序。 |
| GATE-03 | S2整合门：沿用当前完整适用pytest、Ruff/format/mypy、只读compile、Schema/JSON/metadata/布局/隐私/ignore/diff及必要合成离线链；使用隔离的公开代码环境，不读正式私人资料。保留主仓既有CI门而非通过复制next手动触发配置削弱检查；macOS实测，Linux按已有CI实测并如实记录。禁止删弱测试/skip/隐藏失败，环境缺失不记通过。来源：A-009/A-023及根已有CI。 |
| GATE-04 | S2由另一全新只读Validator接收逐字本合同/规则/当前快照，自行核对实现、来源一致性、适用完整检查及隐私保护，返回八字段。Main核摘要、暂存内容、提交与远端事实后收口。代码/合同语义后改需重验；仅真实协调回写按协议豁免。来源：A-019/A-020。 |

- 分阶段适用：S1为AC-01/02、INV-01/02、GATE-01的基准部分与GATE-02；S2为全部最终标准，但S1检查点历史只审查提交事实，不把尚未实施的S2标准用于阻塞S1。
- Git授权：Main执行上述精确暂存、第一次本地检查点、第二次整合提交及origin/main正常推送。Worker/Validator不提交或推送，不创建/切换分支，不修改原next。当前严格串行，不新增并行worktree。
- 不含：外部目录清除、历史Git故障修复、真实产品验收、发信/课程/同步/API实现、全局配置/Skill变动、新服务/VM启动、依赖网络安装。可复用现有缓存工具，必要临时检查位置在仓库外；安装缺失依赖或扩大外部操作需先报告。

<!-- VC-001-END -->

## 步骤与写入职责

| 步骤 | 状态 | 执行与边界 |
| --- | --- | --- |
| S1a Goal及基准 | done | Goal原字节复制/0700-0600/源不变；next公开来源及主/data/state基准已留私有证据 |
| S1b 检查点验证/提交 | in_progress | 全新只读Validator核S1；Main收到PASS后精确暂存/本地提交 |
| S2 接回next | pending | 单Writer仅主source公开工程、必要产品docs/README/CHANGELOG/规则及CI适配；不动私人路径/源next/主.git，不写计划memoryPLANS |
| S3 独立验证与推送 | pending | 全新Validator核整合；Main提交、正常推送与远端/CI核对、归档协调记录 |

## 检查点与证据

- 私有工作证据：`/private/tmp/trainlab-next-adoption-4yczzw0m/`；无产品运行或网络安装。
- Goal源已确认存在且0600；data/Goal.md整体被现有/data/忽略，不需要force-add或改变隐私规则。
- next现存公开产品文件277份；主公开产品364份，仅作盘点，不以数量验收。来源源码及现行产品合同待摘要冻结。
- 主和next产品模块布局相容；next根开发治理、手动CI触发及历史PLAN不直接覆盖主Harness。产品语义与路径需要同批协调，不能只复制Python文件。
- Goal已复制为data/Goal.md并逐字核对，源原件未变，未打印正文；566份FIT和两份认证不变。尚未暂存/提交/推送或修改主产品。
- 冻结合同SHA：`ba9274d7fff56b28d423eb7e9bfa8895d027c808a74304d7b63d0aa061b644f3`；next原产品合同SHA：`8c1691d1c96746b81ea0389a7ff4e01223175d9605dc28049b1298c630fadd9a`。
- 已将next的公开当前文件复制为仓库外冻结代码来源`next-public/`，未复制ignored私人资料或其.git。`next-source-snapshot.json`含525个tracked/untracked/删除条目；`main-start-snapshot.json`及`private-baseline.json`记录主公开树与data字节/state元数据。
- 使用现有UV离线缓存，在本任务私有目录创建`check-env/`并配置next固定requirements，两个命令均退出0，无网络安装或全局配置变化；日志quality-env.log。Python3.12.13及完整pytest/Ruff/mypy等现成缓存已可用于隔离公开代码检查。
- Main只读`git ls-remote --heads origin refs/heads/main`退出0，远端main仍为25e8b92，与主起始HEAD一致；未fetch/提交/推送。该检查不授权覆盖之后的远端变化，发布前须再核。
- S1受审快照SHA：`2afb1f9c6b91db30396b74f7eb6b40aab6567285074123158fbc680da2f70502`；54条精确公开提交路径在s1-whitelist.json。下一动作：收到S1实际报告后核对，若PASS则Main提交首个本地检查点，再通过supervisor给Writer明确起跑回执。
- 诊断：not_triggered；blocker_type：none。

## 派发记录

已启动一个native async串行workflow `384dc4b3-e41a-4501-9326-0c18ccf1d742`，mission `07432f23-04b0-4ad2-b4f7-19ad9ab6df9a`：S1独立只读检查 → 单Writer等待Main确认检查点提交后实施 → 全新整合Validator。角色high/high，原因是跨树代码/私有资料/Git发布边界；具体平台按会话可用模型配置，不在仓库固定厂商。Writer不具备协调或Git发布权限；只读阶段允许仓库外合成检查和工具绑定报告。任何工具/环境/有效标准阻塞原样返回，不自动切换执行协议或无限修复。

## 迭代记录

2026-09-14：收到新的Goal/主提交/next代码接回/远端提交授权，Git及来源检查通过，建立VC-001；旧保全/清理结论不改判，本轮不实现API或清除外部目录。
