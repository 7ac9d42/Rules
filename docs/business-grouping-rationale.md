# 业务聚合依据与取舍

日期：2026-09-11。适用于[三机场配置](../configfull_new.yaml)及[四机场模板](../cinfigfull_new_4.yaml)；完整入口与选项见[设计说明](single-config-design.md)。本轮查阅官方资料，结合既有文件实测和原生内核回归作决定。没有真实订阅或付费账号的本轮测试，不宣称验证了平台解锁或账号风控结果。

## 判断方法

四层政策决定默认机场顺序，并直接落实为业务选项的首项；业务入口决定哪些请求共同接受一次手选；探针只在已选链路范围内判断连通性。三者分别判断，菜单不再增加重复的层级自动入口。

- 明确的代理拒绝、内容能力下降或网络信誉影响，是保留独立控制的重要依据；采用高要求政策属于设计取舍，不代表已经证明机场名称1或未来家宽能解决平台限制。
- 只有地区功能差异时，可以独立选择地区而继续使用普通政策。TikTok、TVB属于这种情况。
- 普通登录提醒、一般排障建议、账号付款国家或API配额，不能一律解释成高信誉IP要求。
- 用户已确认影音以普通播放为主，游戏以下载和日常游玩为主。普通业务在各自语义范围内聚合，不扩成跨用途的“日常服务”总开关。
- 证据不足不等于零风险；“境外影音”表示本次按普通播放处理，没有逐站证明其所有成员都不受地区或代理限制。

## 影音

| 服务 | 决定 | 一手依据及限制 |
|---|---|---|
| Netflix | 独立，高要求 | [官方VPN说明](https://help.netflix.com/en/node/114701/)指出代理连接可能只显示全球授权内容，广告套餐和直播不支持VPN。这直接涉及播放能力，不证明固定IP或家宽必定可用。 |
| DisneyPlus | 独立，高要求 | [Error 73](https://help.disneyplus.com/article/disneyplus-error-73)涉及不支持地区及VPN/IP匿名服务。出口仍需适合实际服务地区。 |
| HBO/Max | 独立，高要求 | [VPN检测错误](https://help.hbomax.com/ag-en/answer/detail/000002566)明确要求关闭VPN、代理或匿名服务才能继续播放。 |
| Primevideo | 独立，高要求 | [播放排障](https://www.primevideo.com/region/na/help?csTools=2&nodeId=GU85HKX66NVFNQ9Y)要求停用VPN/代理；[直播帮助](https://www.primevideo.com/-/it/help?experiment=14&nodeId=GCA8ZKP4GC97ZNCH)还明确限制此类连接。证据强度低于专门的代理检测错误，保留属于保守设计。 |
| Spotify | 独立，高要求 | [反滥用说明](https://support.spotify.com/us/article/abuse-detection/)明确把VPN/Proxy列为账号请求拒绝的可能原因。它不仅是Premium订阅国家问题，因此在用户确认普通播放后仍保留；不能外推为每次音乐流都拒绝代理。[国家设置](https://support.spotify.com/us/article/country-region-settings/)另有注册地、居住地和付款方式要求。 |
| YouTube | 并入境外影音，成本 | 用户已确认普通播放。[Premium政策](https://support.google.com/youtube/answer/6307365?hl=en-GB)有主要使用国家及虚报位置可能取消订阅的要求；这些不作为本次普通播放升层的依据，也不承诺合并后适合跨区订阅。 |
| AppleTV | 并入境外影音，成本 | 按[常规订阅播放](https://support.apple.com/en-ie/118404)用途聚合；未找到足够证据把它整体定为高IP要求。[第三方频道](https://support.apple.com/en-ie/102306)可能有海外不可播或直播定位要求，不能用常规播放判断覆盖全部特殊内容。 |
| Twitch/原其他影音 | 留在境外影音，改成本 | [官方浏览器排障](https://help.twitch.tv/s/article/supported-browsers?language=en_US)的VPN建议属于一般排障，证据不足以据此建立独立高要求入口。其他影音没有逐站完成风险证明。 |
| TVB/mytv | 独立，普通 | [myTV SUPER FAQ](https://promo.mytvsuper.com/tc/faq_webview)明确港澳服务范围，存在独立地区选择价值。但当前23条TVB规则还包含TVBAnywhere、美国/澳洲产品及第三方站，不能把这条FAQ外推到全组或统一锁香港。本轮只恢复独立操作范围，不臆造专属IP质量要求。 |
| 哔哩东南亚、Emby | 各自独立 | 用户明确要求；分别沿用普通政策和低倍率/MITM特殊默认。 |

普通播放的合并意味着YouTube与AppleTV共享一次出口选择。严格媒体各自保存选择；高要求的默认回退仍可能换地区，具体地区需求应通过已有地区选项表达。

## 通信与社媒

| 服务 | 决定 | 一手依据及限制 |
|---|---|---|
| Telegram | 并入境外通信，成本 | [官方代理文档](https://core.telegram.org/proxy)支持代理访问；不能仅因手机号账号就推断必须家宽或固定国家。 |
| Signal | 并入境外通信，成本 | [官方代理支持](https://support.signal.org/hc/en-us/articles/360056052052-Proxy-Support)允许使用代理，代理被封锁后可更换。这不保证任意共享出口都正常。 |
| LINE | 并入境外通信，成本 | [号码验证](https://help.line.me/line/?contentId=20000104&lang=en)和[登录通知](https://help.line.me/line/smartphone/sp?contentId=20014794&lang=en)支持号码限制及安全检查的判断，未证明独立高信誉出口必要。 |
| Discord | 并入境外通信，成本 | [账号验证](https://support.discord.com/hc/en-us/articles/6181726888215-How-to-Verify-Your-Discord-Account)涉及行为风控；[语音排障](https://support.discord.com/hc/en-us/articles/115001310031-Voice-Connection-Errors)指出VPN需要UDP支持。不能把社区的个别封禁经历当作普遍IP门槛。 |
| Meta、X | 合入/留在境外社媒，普通 | [Meta说明](https://about.fb.com/news/2018/04/data-off-facebook/)和[X账号安全](https://help.x.com/en/safety-and-security/account-security-tips)表明异地或可疑登录会增加验证。Meta材料较旧，二者均不足以证明必须逐品牌使用高要求出口。 |
| Reddit | 独立，高要求 | [CQS说明](https://support.reddithelp.com/hc/en-us/articles/19023371170196-What-is-the-Contributor-Quality-Score)明确网络和位置参与账号质量评分，评分可用于帖子/评论过滤。保留独立并升高要求是保守推断，不代表官方要求家宽或更换IP会提高分数。 |
| TikTok | 独立，普通 | [位置说明](https://support.tiktok.com/en/account-and-privacy/account-privacy-settings/location-services-on-tiktok)涉及SIM、IP等地区信号及内容体验。保留地区操作能力，不将地区依赖直接等同高IP信誉。 |
| Talkatone | 独立，高要求 | 沿用既定需求。[官方旅行说明](https://talkatone.zendesk.com/hc/en-us/articles/360037776052-Traveling-with-Talkatone)允许取得号码后全球使用，不将本配置选择描述为官方强制美国出口。 |

境外通信与境外社媒仍是两个入口。复评后通信整组采用成本，三机场文件：3→1→4、四机场文件：3→1→2→4：Telegram恢复原成本顺序，LINE/Discord/Signal及原通信集合由普通转成本。现有证据没有证明机场名称1的语音、图片或消息长连接优于机场名称3；HTTP探针也不能代替实际协议质量。两层均保留地区顺序和兜底，不因“通信重要”就认定必须机场名称1优先。TikTok/Reddit/Talkatone的规则先于宽集合，不因聚合而被其接管。

## 开发、游戏与厂商生态

HuggingFace、Docker合入已有开发下载；GitHub/GitBook此前已合并。[HF配额](https://huggingface.co/docs/hub/en/rate-limits)、[Docker使用限制](https://docs.docker.com/docker-hub/usage/)、[GitHub API配额](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)区分匿名IP与鉴权账户额度，Docker另有共享IP反滥用限制。它们支持重视共享出口质量和正确鉴权，但不足以支持永久按品牌拆选择器。合并没有增加换IP绕过限额的机制；健康探针也不能检测所有应用配额。

纯下载保持独立，仍只含两个既有GitHub域。[历史五候选文件测试](download-policy-validation.md)已经记录普通GitHub固定香港时，附件自动链可走美国并传输完整文件，也记录了HEAD与正文结果不一致。这里保留的是有实测依据的传输选路与扩区算法，不把整个开发集合放进跨区择优池。

Steam并入游戏平台，按用户明确的下载/日常游玩用途保留成本政策。[Steam商店国家](https://help.steampowered.com/en/faqs/view/2B3F-DAEF-846B-A0E8)与[下载地区](https://help.steampowered.com/en/faqs/view/5AC5-8056-E88F-F3FF)是不同概念；[Epic](https://www.epicgames.com/help/en-US/billing-support-c5719364845851/general-support-c5719348744091/how-do-i-change-the-country-on-my-epic-games-account-a5720356470555)、[EA](https://help.ea.com/en/articles/technical-issues/fix-payment-issues/)、[PlayStation](https://www.playstation.com/en-ie/support/account/check-account-country-region/)同样存在账号或付款地区限制，Steam并非唯一特殊平台。合并后不能同时为不同游戏平台保存不同国家偏好；不把这项合并理解成跨区购买保证。国内游戏、Steam CDN等明确DIRECT规则保持。

Google整组保留普通，三机场文件：1→3→4、四机场文件：1→2→3→4。[搜索官方说明](https://support.google.com/websearch/answer/86640?hl=en)明确指出，共享网络/VPN中他人的异常流量会导致验证码，部分VPN网络甚至搜索受阻。这支持沿用原Google/GoogleVPN的保守出口信誉偏好，但本地没有机场名称1验证码更少的对照，不能称为已测最优。AI已独立，不以AI要求抬高Google；现有GoogleVPN规则及[地区限制](https://support.google.com/pixelphone/answer/2819573?hl=en)仍保留。

FCM继续跟随Google共用一次选择，原FCM成本默认随之改变；这是整组简化的代价，不是推送需要高信誉IP。[FCM网络说明](https://firebase.google.com/docs/cloud-messaging/network-configuration)重点是端口、长连接、NAT超时及VPN对连接维护的影响，不能据此断言机场名称1更可靠。gstatic 204不验证推送到达率、搜索验证码或GoogleVPN嵌套连接。

Microsoft与OneDrive整组采用成本，三机场文件：3→1→4、四机场文件：3→1→2→4，OneDrive恢复原默认，Microsoft主体由普通转成本。[OneDrive网络规划](https://learn.microsoft.com/en-us/sharepoint/network-utilization-planning)指出同步流量主要来自文件上传下载，受文件规模、丢包、延迟等影响；没有本人的业务占比数据，不宣称整个Microsoft组都以下载为主。[Microsoft异常登录说明](https://support.microsoft.com/en-us/accounts-billing/security/what-is-the-recent-activity-page)支持保持地区稳定偏好，成本层同样具备地区隔离，不能从账号生态推出机场名称1优先。

[既有五候选实测](download-policy-validation.md)只有少量HEAD和GitHub文件数据，不构成机场名称1与机场名称3的长期质量比较，也不验证OneDrive同步或通信语音。两组改成本后仍可手选机场名称1优先、指定地区或实际节点；没有新增分支、测速池或评分机制。首次默认出口可能从机场名称1香港变为机场名称3日本，不把层级调整说成出口完全不变。

金融、电商、通用代理继续各管各的业务范围；国内银行和明确直连不并入金融。Apple与哔哩哔哩分别默认DIRECT。AI、台湾限定、Emby、Kryptex、Speedtest以及工具入口按用户要求保持独立。

## 证据与验证的分工

官方资料用于确认具体限制，既有实网文件数据用于保留有价值的传输能力；本轮临时内核夹具验证归属、聚合控制、高要求独立、地区回退、重启与订阅更新。没有真实机场解锁或真实账号评分测试。不同用途、套餐、地区或规则集更新可能改变判断，不能把一次首页HTTP成功当作风险消除。

此前聚合改变24条主规则目标，层级复评将Microsoft、境外通信改为成本。随后三/四机场拆成独立文件，默认层级静默落实为机场偏好首项；相同地区链合并为机场优先名称。本次拆分的全部主规则、92个provider、CF范围、节点筛选、DNS/TUN与原自动健康池保持。具体执行结果和配置摘要见[验收记录](config-optimization-audit.md)。

## Cloudflare Tunnel传输入口

新增的Cloudflare Tunnel仅控制被穿透端到CF边缘的7844连接，默认DIRECT，可主动选择机场/地区自动链、共享家宽或实际节点；其要求是传输稳定性，不能由AI的IP信誉层级推导机场顺序。原生复现已证明仅按域名DIRECT会漏掉没有域名元数据的真实端点IP。规则现覆盖官方全球40个精确地址，普通CF网站及其他端口继续原分流。Tunnel完成时共31个可见入口，110/145组、131条主规则、93个规则provider；没有新增测速池。真机直连/14个固定节点握手对照支持保留DIRECT默认；两region新增精确real-ip和国内DNS策略，修复地址池被Fake-IP压缩的问题。尚无持续负载或全天稳定性排名，数据与边界见[研究记录](cloudflare-tunnel-uplink.md)。

自建/家宽快捷入口按用户的集中操作需求恢复：各业务主动选择该入口后才共享组内手选，原默认保持，台湾范围保持；AI与Tunnel随后补齐主动覆盖选项。沿用名称筛选仅用于快速定位，不提升其IP质量评级。当前为32个可见入口、111/146组；规则数量不变。
