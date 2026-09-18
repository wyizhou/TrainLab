# D31-LIVE-002 认证401只读诊断

- 日期：2026-09-18。用户要求优先解决Garmin 401，询问是否认证失效并表示可以协助重新认证。
- 受审：`work/adhoc-0031-local-web-system`，HEAD `a5893ac6eb8295cd8a60d8f2537bc213d1412885`加已完成本地验收的未提交内容。
- 方法：主Agent仅程序化读取已授权的`states/verification/garmin.json`，输出已知字段是否存在、类型、令牌是否JWT形状以及时间字段比较；未输出令牌值、签名、账号、其他payload或凭据摘要，未复制原配置到证据。核对本机UTC时钟和当前锁定SDK源码，未请求Garmin、登录或修改认证文件。
- 事实：配置只含`di_token`、`di_refresh_token`、`di_client_id`三个字符串，无tokenstore、真实expires_at或区域字段；访问令牌形状为JWT，其exp声明早于本机当前时刻。仅本地解码未验证签名，也未在线验证撤销状态；刷新令牌是否有效未知。
- 产品事实：`source/skills/_shared/scripts/trainlab/garmin_sync.py`在配置缺少expires_at时使用当前时间加1800秒，而不是令牌中原有有效期；并将di_client_id放入OAuth1的oauth_token，签名secret为空。GarminConnectClientAdapter.refresh_auth本身只返回原配置。
- 依赖事实：锁定garth 0.6.3在OAuth2到期时调用refresh_oauth2，再由sso.exchange通过OAuth1签名交换新OAuth2；不是直接使用当前DI refresh token完成刷新。离线合成OAuth1刷新成功不能证明三个DI字段可按该方式刷新。
- 判断：令牌过期是401的具体原因线索；同时存在产品有效期/DI刷新接口匹配问题，不能只让用户反复登录后宣称长期同步已修好。当前不能判定唯一服务端原因，也不能判定必须MFA。
- 人工协助方式（按用户最新纠正）：不再要求浏览器提取凭据；指导用户在本人终端用已锁定的pygarminconnect登录。已核对0.2.40的Garmin构造器支持prompt_mfa回调，login()需要验证码时调用该回调；用getpass隐藏密码/验证码，成功后由api.garth.dump保存OAuth1/OAuth2到`states/verification/garmin-tokenstore/`，不打印login返回值或令牌。先保留原garmin.json不覆盖；成功后再安全切换产品配置及做有界列表检查。环境在仓库外，锁文件非editable安装；新令牌目录/文件用umask 077。需要中国区时由用户明确选择is_cn，不猜账号区域。失败不自动重复登录，只反馈错误类型。产品修复仍须按Developer→全新Validator→主验收流程，不由操作说明冒充实际登录成功。
- 保全：原认证文件未改、Git忽略规则生效；未请求真实AI、下载FIT、写数据库、提交/推送/合并。原真实检查失败1、接线尝试1继续保留，本次没有新增真实请求失败或修复尝试。
