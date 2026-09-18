# FIT 基础层

本层消费 ADHOC-0031 已批准的 JSON、时间、身份和事务合同，不提供业务 Provider 或 AI 工具。

## 固定解析来源与适配

采用公开官方 `garmin-fit-sdk==21.214.0` 的 Profile、基础类型和 CRC 实现（FIT Protocol License）；Profile 有124种消息、200种类型。依赖源代码不复制进项目，完整依赖由 `source/uv.lock` 固定。

官方该版本的 Decoder 不支持 compressed timestamp，分组结果不能独立证明原消息顺序；会省略 invalid，组件同名可能覆盖，Developer重复描述采用首个匹配。本层因此不是简单包装其 `read()`：

- `wire.py` 按协议遍历每个链式部分，校验头、版本、长度、头/文件CRC、Definition、数据长度、基础类型和字节序；压缩时间戳显式解码。
- `profile_fields.py` 使用完整固定Profile解释所有遇到的已知字段、枚举、单位、子字段和组件；共享 `contracts/fit_profile.py` 直接引用同一SDK Profile供解析与身份校验使用，不复制影子字典。未知可解码字段保留编号和原值，不按常见运动指标筛选。
- `parser.py` 保留数据消息原始索引和跨链record次序；不启用HR合并，不改变record集合。直接字段与子字段/组件展开使用不同ID，累计组件先统一计量单位；不以展开值覆盖原字段。

累计字段按直接数组的原序读取有效基点，invalid不清零；同一消息先读取直接基点再展开组件，不受Definition字段排列影响，跨链不复用基点。date_time/local_date_time保留数值原值，Profile中的min是边界常量而非枚举标签。

原生字段只做一次Profile scale/offset。Developer只按其自身描述处理，不借 native_field_num 再套标准字段比例。未知字段不猜单位，字典以 `value_form=raw` 标明；未知bytes用单键十六进制对象，大整数用十进制字符串对象。无效值保留null、有效0不丢失；数组不拿首项代表全部。

来源别名按链、开发者索引及来源出现绑定；同名不同开发者不合并，字段重定义另分配ID。设备/开发者私有标识被排除，标准字段没有可核验证据时不猜它来自某个外接传感器；未知厂商字段语义仍未知。保留的字段可含GPS等私人事实，数据库、FIT、输出仍不得进Git。

## 消息分类

| 类别 | 消息规则 |
| --- | --- |
| 基本情况 | file_id(0)、activity(34)、file_creator(49)，加可确认运动和时间 |
| 整场摘要 | 每一条session(18)，不只取首条或挑熟悉指标 |
| 原生分段 | lap(19)、length(101)、segment_lap(142)、set(225)、split(312)、split_summary(313) |
| 第四类 | record(20)独立逐条入records；其余已知/未知消息保留于sensors的messages；字段及来源字典只存一次 |

私人身份字段和无关个人档案不进入字段字典或默认事实；对应消息仍留类型与原始索引。`sensors_json`不存records副本。默认123依据实际引用取得最小字段字典和组件父字段闭包，再附所需来源，不发送完整sensors。

## 时间与完整性

- FIT date_time低于 `0x10000000` 是相对系统秒，不转换成1990年前后的UTC；local_date_time保留原本地数值，不猜时区。
- start只取session可确认开始，end只取对应start＋elapsed；timer和摘要timestamp不替代结束。多session完整保存，只有所有session运动大类一致且可确认才形成单一sport，不拿第一段running代表混合运动。
- 所有SQL绝对时间为UTC、六位小数、Z。record时间证据区分absolute/relative/invalid/missing；不可确认则NULL。缺失/invalid不补前值、不插值、不合并同时间采样。
- 活动主体必须有file_id(type=activity及manufacturer)、activity、session、lap、record；每个含活动主体的链段分别检查，不能用前段摘要补尾段缺失。单独的追加HR/HRV链段只作为已有完整活动的补充，不把它当独立零record活动成功。缺少结构不恢复造值。
- 拒绝协议非法字段号255；session/lap必须定义start_time、total_elapsed_time、total_timer_time、timestamp四个uint32时间字段，允许其协议invalid值保留null。空activity和没有任何采样字段的record（包括仅有timestamp）不算完整；有采样字段的record仍允许缺失、invalid或相对时间，不强迫补UTC。
- 原始定义存在但数值invalid以及没有定义的可选字段分别保留null或缺键。没有记录集合的独立Activity不予成功：固定官方Activity指南把record列为必需，本轮没有发现其通用零record合法例外。Schema可承载空records不等于解析器宣告不完整FIT合法。
- 任一链CRC/长度/定义/消息失败整体报错，不宽松恢复、不提交半场。存储容量与模型发送容量分离，没有因模型限制裁剪入库记录。

## 写入和读取边界

共享单进程门保护初始化、普通导入、显式维护和只读视图；普通SQLite rollback journal，不使用活库immutable或REPLACE。等待参数是技术超时（调用者可指定），不是费用或采样配额。`read_view`用mode=ro及query_only，读取期间写入门不可取得；未创建后续AI宿主。

Schema在 `source/schemas/contracts.schema.json`，共享验证器另检查SQL/basic一致、连续record索引、消息原序、字段/来源/组件引用和时间证据。消息编号/名称、标准字段编号/名称/单位/原值形式及组件父项按同一Profile核对；未知消息名称保持null。Definition身份不能跨chain或消息复用；实际record timestamp字段、time_evidence和SQL UTC必须逐值一致。所有仓储入口实际调用完整校验。SQL子行失败回滚父行及全部子行；报告/config不参与本层修改。

## 公开核实来源

2026-09-16核实：

- [官方Python SDK 21.214.0](https://pypi.org/project/garmin-fit-sdk/21.214.0/)：已安装固定发行包并检查源码；不把Decoder的局限当完整性合同。
- [FIT Protocol](https://developer.garmin.com/fit/protocol/)：头/CRC、压缩时间、Definition、Developer Data与完整链式格式。
- [Activity File](https://developer.garmin.com/fit/file-types/activity/)：必需消息及多session结构。
- [项目解析参考](../../../references/garmin-fit-parsing.md)：来源/单位/合法缺失背景；不是字段白名单。

合成正常文件与官方Decoder交叉核对record数量、speed和elapsed；压缩时间、invalid保留、同名不覆盖等另由协议级合成断言验证。没有读取私人FIT，也没有声称每种设备/厂商未知语义均已实测。
