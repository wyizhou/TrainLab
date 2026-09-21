# ADHOC-0035 本地验收与交付证据摘要

## 固定来源及边界

- 2026-09-20固定官方仓库 https://github.com/wyizhou/agentsmd.git 提交a313e6319b249c2c78e92079f3c0b0b013929660，17项SHA见[source-manifest.json](source-manifest.json)。本轮只安装README和.pi六文件；其他通用规则/模板/技能原本与该版一致。
- 候选基线07cc51608f7cf3a9c65bec6767ddfeb6076e3a99，分支work/adhoc-0035-agentsmd-role-adapter；原实际区基线ab43cc4df231ad61aa7ab30793645dcc59d4d8c2，分支work/adhoc-0033-ai-coach。只在候选提交，不带原区业务差异。
- 本文件为最小发布摘要。完整原始本地证据保留于原工作区exec-plans/evidence/ADHOC-0035；未把完整历史会话、安装环境源码、机器私有目录或业务证据复制进本PR。以下run ID和摘要是定位证据，不冒充可在其他机器重放的目录。

## 已执行检查（2026-09-21）

| 范围 | 实际方法/命令 | 实际结果及证据 |
| --- | --- | --- |
| 源与payload | 对官方17文件及两区七文件执行SHA-256；正确上游clone中git rev-parse / remote get-url / ls-tree及17次git show | 主均核一致；源仓库位于导出目录的git子目录，不能把导出父目录当Git根 |
| 首次候选独立 | 官方Validator workflow a3a29fa8-d525-4c21-99fb-31b2708e6b0e，child 638673af-ab77-4fff-a36c-4336bfd5d09d；独立正常/错误/边界与冻结核对 | 候选适用范围通过；38合同项、39配置项、350尾查、91/92冻结核对。原检查器路径失败保留，不推导尚未执行的原区/最终组合通过 |
| 精确安装 | 原区python3 exec-plans/evidence/ADHOC-0035/install-original.py及同命令--apply | 两命令退出0；仅替换README和.pi；旧architect及dev目录退出项目；恢复备份只在Git内部，不发布 |
| 业务保护 | 原基线6825个对象SHA/链接目标、git status --porcelain --untracked-files=all -- source、git diff --binary -- source摘要；两区git diff --cached --name-only | 保护无变化、source原38项差异保留，两个暂存区均空；业务PLAN/MEMORY只做本轮最小增量 |
| 官方角色发现 | 原生list/models/get，核精确agentsmd.planner、agentsmd.developer、agentsmd.validator及项目源 | 三角色可执行；inherit解析当前主模型，不将发现当认证/真实启动证明 |
| 官方Developer实际探针 | child 92116531-2640-4274-8338-3a7864b4de95；一次python3 -B读取自己PI_*及核11文件/根/分支/HEAD | 工具退出0、11/11；真实模型openai-codex/gpt-6-astra、xhigh；会话01a0c1d0-c114-713b-9eee-f6e3b80d7548 |
| 官方Planner实际探针 | 首轮child 917a48e6-a1f0-4ca9-9f22-1a30f6c842f0；恢复child 481e459b-7a8e-4263-876d-68bb31a3a7d5 | 首轮末尾报告目录缺失，bash退出1；保留原错后预建外置目录，新实例一次检查退出0、11/11、报告写读一致。真实同模型/xhigh，会话01a0c1d9-5c1d-773b-bae5-c13534390713 |
| 主APPEND | 主直接核对当前有效上下文，结合项目APPEND SHA、实际cwd及不存在全局同名APPEND/SYSTEM的源事实 | 当前主可见同版运行约定；这是主上下文人工验收，不是文件存在推断，也不是伪造的宿主完整prompt/reload回执 |

实际模型/等级仅说明本次运行，不是发布文件新增固定模型。角色配置仍为官方inherit；没有明确thinking策略时主按当次环境xhigh给同模型后缀，没有修改全局配置。

## 原失败保留

- H35-INFRA-001：历史后台.ts入口MODULE_NOT_FOUND，安装为.js；失败1次，未修改安装，后续新进程同协议恢复。产品修复0。
- H35-INFRA-002：只读Planner报告父目录未创建，工具失败1次；预建外置输出目录后全新实例恢复。runner退出0不覆盖原工具退出1。产品修复0。
- V35-T02-L01：20项补强来源检查曾误用导出父目录，退出128；正确git子目录后来由主核17个对象，最终独立仍需补核。
- V35-T02-L02：/var与/private/var字符串比较曾有3项误判，samefile/realpath后39项配置检查通过。原错不删除，不当候选实现修复。

## 最终组合及交付

- 最终两组合全新独立验证及主完整本地验收已接受，见[最终摘要](validation-summary.md)及[证据指纹](acceptance.json)。正确Git根17对象已由最终Validator首尾独立补核。独立主prompt复核无法判断的限制保留，由主直接核当前有效上下文；不将所有接入层写成子独立实测通过。
- 2026-09-21已重核触发/合并条件：Actions workflows=0、rulesets=0，#22基准头仍07cc516、无必需检查；15项最小增量提交7faadf4已推送并创建[PR #23](https://github.com/wyizhou/TrainLab/pull/23)，实际核对PR头及15文件清单。后续闭合提交仅归档真实结果/链接，不改受验payload。
- 未运行：产品构建/全测、浏览器、数据库、私人账号与业务真实服务、多Developer并行试验。本轮不需要也不宣称覆盖这些范围；ADHOC-0033继续暂停。
- PR #23为OPEN，基准为#22分支；尚未合并，合并须用户另行确认。未新增或主动运行远端CI；基准/组合变化影响结果须补查与适用独立验证。
