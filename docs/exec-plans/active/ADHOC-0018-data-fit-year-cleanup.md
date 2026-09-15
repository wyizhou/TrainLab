# ADHOC-0018：data精简与FIT按运动年份命名

- 状态：`validating`；开始日期：2026-09-14；执行：Main串行实施，最后一次全新只读验证。
- Git：主根 `/Volumes/DiskOther/Code/TrainLab`，main，HEAD `25e8b92cd170809610d2e5feb4dbdb0033594ff2`；52项已有未暂存改动，暂存为空。本任务不修改旧产品或无关工作。
- 上一任务ADHOC-0017已结束，本任务是用户新批准的目录整理/删除，不重启旧代码修复。

## 冻结合同

<!-- VC-001-BEGIN -->

- 版本：`VC-001`；状态：`frozen`；日期：2026-09-14。
- 批准来源：用户要求data仅保留fit和verification、FIT按运动年份目录及`20260901-run.fit`形式命名，删除其他文件/目录和多余认证；随后明确批准同日同运动重名加`-02`等序号，并将无法识别文件保留到`fit/unknown/`，要求开始工作。已说明运动开始日期采用香港时区。
- 范围：仅整理主根的`data/`；保留其中所有现有FIT字节及两份现用完整认证，按以下标准重命名/精简。允许删除data内旧config/recovery/README、旧认证目录/副本、旧by-sha空目录和杂项；不把这些内容搬到别处假称删除。

| 标准 | 要求和来源 |
| --- | --- |
| AC-01 | data顶层最终仅fit和verification两个目录，无README/config/recovery或额外文件。来源：用户明确删除要求。 |
| AC-02 | 全部现有`.fit`原字节保留；从FIT自身运动开始时间确定香港日期，放入`fit/YYYY/YYYYMMDD-english-sport.fit`，同日同名加`-02`、`-03`等序号，不能覆盖另一份文件。年份取实际数据，不限定2024–2026。来源：用户格式和重名批准。 |
| AC-03 | 缺少可确定运动时间或类型/无法读取的FIT放入`fit/unknown/`并保留原字节，不用文件mtime或路径日期伪造运动日期，不删除损坏/测试样本来使数量符合预期。来源：用户unknown批准及数据原字节安全。 |
| AC-04 | verification最终仅`garmin.json`及`gmail.json`两个普通文件，分别来自此前现用Garmin和Gmail完整Token，内容逐字保持且刷新令牌不丢；Gmail保留Token中原client字段，不将两套账户凭据拼接。不因短期access token到期而丢弃完整刷新材料；不声称离线核对证明在线有效。来源：用户一个Garmin/Gmail认证文件目标及已确认解释。 |
| AC-05 | 新目录0700/文件0600，data整体Git忽略且无tracked data。精确删除只发生在主data边界；不跟随链接删除界外对象，不删除原source/state、原私人配置/令牌、data-backup、next或其他仓库资料。来源：用户限定data及A-004。 |
| AC-06 | 不实现API、修旧代码、调用Provider/网络/模型业务/认证刷新或启动旧daemon；不连接SQLite、checkpoint或操作原数据库sidecar；不安装依赖、不暂存/提交/推送。来源：本次收尾范围及既有安全授权。 |
| GATE-01 | 变更前记录当前FIT/两份认证的原路径/身份/大小/SHA及精确删除根；先固定合成字节解析、错误、重名、不覆盖及链接边界预期，再实施一次性文件操作。创建目标后全量核保留字节/数量一致才删旧布局和其他data内容。来源：根保护与测试先行边界。 |
| GATE-02 | 全新只读Validator仅接收逐字本合同、适用规则及当前文件/清单，独立核命名来源、保留SHA、目录形态、认证/权限/ignore/删除边界并返回八字段。证据和脚本在仓库外私有临时目录，不在最终data留下第三目录。旧产品完整门不适用于本次文件整理，不将其未运行称为通过。来源：根独立验证及用户不要反复修旧代码要求。 |

- 实施细节：英文运动标签基于FIT sport/sub_sport，不使用私人活动标题；running统一`run`。多session若全部同一可辨认类型，取最早session开始时间；多种类型统一`multisport`，证据不全则unknown。未知文件保留SHA命名，避免虚构日期或冲突。
- 本次明确删除授权替代ADHOC-0017中data内旧保护副本/配置不得删的任务边界，仅针对data内副本；根Git、原件、历史公开合同与失败判定不改写。删除的旧证据路径会失效，后续记录如实披露，不为保留旧验收路径另复制10GiB归档。

<!-- VC-001-END -->

## 执行步骤

| 步骤 | 状态 | 产物/边界 |
| --- | --- | --- |
| S1 冻结和映射 | done | 私有清单及17项合成检查；两份认证与原现用来源SHA一致 |
| S2 整理和精确清理 | done | 568份保留目标逐字核验后，删除精确清单中198759个旧节点 |
| S3 独立核对与交付 | blocked | 独立核对已返回INCONCLUSIVE；等待人工澄清FIT保留集合，不修改合同/数据或自动重验 |

## 检查点

- 整理前data含fit（566份FIT及系统杂项）、verification、config、recovery（约10GiB）及README。
- 初步只读解析见7份时间/类型不明候选、9份多session；这是盘点结果不是固定验收数量，以实际字节及解析证据为准。
- 私有证据：`/private/tmp/trainlab-data-year-p1sgptcj/`，只有本次工具、元数据/SHA清单及合成检查，无旧归档/凭据/FIT备份。
- 使用本机已有UV缓存fitdecode 0.11.0，只加入当前临时进程导入路径，不安装、不修改全局配置、不导入旧产品。完整解码及CRC检查：555份可命名、11份unknown（7个header错误、2个CRC错误、2份session信息不足）；有效年份2021/2024/2025/2026，多session按合同归类。
- `PYTHONDONTWRITEBYTECODE=1 python3 /private/tmp/trainlab-data-year-p1sgptcj/test_organize.py`：17项合成测试通过；只读compile通过。ruff不在当前PATH；没有新增交付产品代码，未安装工具。旧产品pytest/Ruff/mypy/双平台不在本次范围，不冒称通过。
- 删除清单10个根、198759个节点；检查发现两个硬链接，经完整链接计数证明同一inode的两个链接都在待删的旧合成目录内，无界外共享链接。安全盘点后继续，没有数据修复或弱化预期。
- 已执行一次`organize.py apply`，退出0。data现约70MiB，只剩fit及verification；566份FIT原字节全部匹配，555份按年份命名、11份unknown；Garmin/Gmail各一个完整原字节认证文件，目录0700/文件0600。
- 删除前全量保留校验和删除后形态/SHA校验均通过；旧config/recovery/README/旧verification/by-sha及系统杂项已移除，没有另搬旧归档。此项为本次用户新授权，不追溯修改旧失败判定。
- Main核原认证原件SHA/元数据及source/state的9350个节点元数据全不变；SQLite未打开。已有无关worktree文件摘要/模式及HEAD/index不变，`git diff --check`退出0；data未tracked且被忽略。
- 派发：ADHOC-0018-Validator，VC-001，高风险数据删除及认证隐私，high/high、native fresh只读角色；同Main能力档，按实测平台指定high推理。允许临时合成检查和工具绑定报告，禁止改项目/数据/计划、调用Provider、安装、Git写入及读旧裁决。输入只有合同、规则、当前文件、私有前后清单和完整Git受审快照。
- 冻结合同SHA：`9b047580d15c6711b305f8bbfdc5aae7ba748664eca4d9a554058054aad8b279`；受审快照`review-snapshot.json` SHA：`1108564459aa3dd2096dfc476234389728299407995f275d2c9a0639ba916c51`，包含53项完整Git差异及568份当前data文件摘要。
- 独立验证结束：native async workflow `b9f26dc2-1f6e-4217-a3f6-352da0bb30cd`，key `adhoc-0018-final-validator`，child `76d5ca3b-c518-4796-ba4e-a0870e00acf0`；总体`INCONCLUSIVE`，不是FAIL或PASS。实际报告：`/Users/lucas/.pi/agent/sessions/--Volumes-DiskOther-Code-TrainLab--/subagent-artifacts/outputs/b9f26dc2-1f6e-4217-a3f6-352da0bb30cd/adhoc-0018-data-layout-validation.md`。
- AC-01/04/05/06及GATE-02通过；AC-03仅对当前保留集合通过。独立实测确认566份保留FIT的SHA/大小、555份已知命名/11份unknown、49个连续序号组、两份完整认证、全部0700/0600权限及576个节点Git忽略；原认证及9350个state节点元数据不变，17项合成测试通过。
- AC-02/GATE-01为INCONCLUSIVE（U-01）：精确删除清单共16499个FIT路径，其中566个源在保留清单，另15933个全部位于已明确可删除的recovery树。后者只有lstat，无本轮删除前SHA；大小能匹配保留文件不等于字节证明，不能声称它们全是566份的重复字节。合同同时写“全部现有FIT”及允许整体删除recovery，集合关系不明确。Main已如实答复，不补造授权、不引用旧PASS、不改判。尚无证据证明违反保留要求，也无证据支持无条件全部保留。
- 用户后续选择先检查旧FIT是否重复及能否补充，未确认缩窄合同。只读补证见下节；本轮不升合同、不追加删除/恢复或自动重验，不改旧代码，也不将历史INCONCLUSIVE回写成PASS。
- 独立证据：`/private/tmp/trainlab-adhoc0018-validator-XmFL3A/independent_check.py` SHA `5be8a1d150e8b6f22340b0bcd2fcd7fc5d53c9413dfc329b86717d382f06fb89`；去敏最终摘要SHA `e76303954a83277bbd0185f254b27c6587e32c452b07ffd922870fbc9e942806`。与本次合同和受审快照绑定；未运行在线有效性或数据库语义验证。
- blocker_type：CONTRACT_SCOPE_UNCLEAR；诊断状态：not_triggered（一次证据/范围不明，不是已确认不可同时满足的合同冲突或实施失败循环）。保持validating，不归档、不声称完成。

## 当前只读补证

- 用户进一步要求查看这些FIT是否多份备份、能否补充到data/fit。此请求启动只读来源/字节比较，不当作确认缩窄VC-001，也不先行补文件或删除任何来源。
- Git恢复检查仍为main/同HEAD、53项现有改动及空暂存；data根出现不在上次受审快照的`.DS_Store`，本轮不删除，不将旧形态结论冒称当前完整形态。
- 待查15933个FIT路径全部来自旧C06：raw下8722、restore下7211。来源定位是主目录、next、TrainLab-data、handoffs及三个登记工作树；历史报告仅用于定位，结论须由当前原件SHA核查，不引用旧PASS代替。
- 仓库内数据、外部原件、SQLite/sidecar及认证均不写；不扫描无关用户目录、不跟随界外链接、不安装、不解包不透明容器或调用Provider。只读结果和必要私有清单留仓库外，不启动旧任务循环。
- 实测只读补证完成：15933个旧路径均能对应现存来源；raw 8722条、restore 7211条，合并为8722个来源定位。逐份实际读取现存源及当前566份FIT做SHA-256和前后身份检查，得到565种不同来源字节，全部已在当前data/fit中，缺失/冲突/新增SHA均0。无须为这些来源增加重复FIT，本轮未新增/移动/删除FIT。
- 来源分组：主源510文件/510种字节；next 6677文件/47种；TrainLab-data 1文件/1种；handoffs 1510文件/14种；三个登记工作树各8文件/4种。分组间有重复，不能将各组唯一数相加或当运动次数。主/next等S01–S04映射从旧报告定位后实查；S06/S08/S09的精确ID绑定原清单已删，因此对全部三个现存候选逐一哈希，三者相同且均在data/fit，不猜单个ID映射。
- 限制：这些是现存对应原件的实测SHA，不是被删除副本的事后字节校验；不存在的副本仍无法直接打开/重新哈希，不追溯制造其删除前SHA。支持“现存对应来源无新FIT可补充”，不声称已直接证明每份已删副本当时的字节或自动替换独立裁决。
- 私有证据：`/private/tmp/trainlab-fit-backup-audit-0arc_0tr/`（0700；文件0600）。`audit_sources.py` SHA `97583e5e93a807b0987392f56327e02752277df56efcea009c46476a05b711a9`；`summary.json` SHA `cdc826e574a89c12558766b50b8220e767439e0f49f9d5dc8e34a2cad34f1392`；逐来源比较`source-comparison.json` SHA `771c7236d3e3ca3e8dd0d02601c3c1c1cf6e8565e7d21fbaf8fb2a260e184d83`。不含FIT载荷或认证值，不是旧归档副本。
- 检查命令：`PYTHONDONTWRITEBYTECODE=1 python3 /private/tmp/trainlab-fit-backup-audit-0arc_0tr/audit_sources.py`退出0；另行集合/路径覆盖断言退出0；`git diff --check`及空暂存检查退出0。next Git身份/状态仍同已记录基准；首次状态汇总的临时单行Python有括号语法错误，修正汇总命令后检查通过，不影响文件、不掩盖失败。

## 迭代日志

2026-09-14：用户批准序号及unknown，Main冻结VC-001后实施一次性整理/删除；当前566份FIT和两份认证完整，独立实测其命名/字节/权限/原件边界通过，但旧recovery中15933个额外FIT没有删除前SHA，保留集合语义不明确，总体INCONCLUSIVE。未修改旧代码、追加删除或自动重试。用户随后要求只读查看是否重复/能否补充；本轮实查8722个现存来源，565种字节全部已在data/fit，新增候选0；该补证不是对已删副本直接重哈希，不改旧裁决。
