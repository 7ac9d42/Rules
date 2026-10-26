# Rules

基于 [Lanlan13-14/Rules](https://github.com/Lanlan13-14/Rules) 的自用分支，维护 Mihomo 配置与分流规则。不接受需求类 issue，欢迎问题反馈和讨论。

## 配置与维护

| 文件 | 用途 |
|---|---|
| [configfull_new.yaml](configfull_new.yaml) | 三机场完整配置：机场名称1、3、4，120 个组 |
| [configfull_new_4.yaml](configfull_new_4.yaml) | 四机场完整配置：增加机场名称2家宽，160 个组 |

每次导入一份完整配置，无需拼接。两份正式配置采用同一架构，最低支持官方 **Mihomo v1.19.30**，不依赖 v1.19.31 独有特性。

人工维护源为 [common.yaml](config-source/common.yaml) 和两个模型文件 [three-airports.yaml](config-source/three-airports.yaml)、[four-airports.yaml](config-source/four-airports.yaml)。共同源维护设备设置、机场订阅、地区识别、准入、探针、业务规则和规则集；模型文件只声明启用机场、优先顺序、敏感池目标及业务默认覆盖。模型按顶层字段覆盖共同源，不进行递归合并；`business-defaults` 单独按业务名覆盖默认项。

```sh
ruby scripts/build-config.rb
ruby scripts/build-config.rb --check
```

默认命令离线生成两份正式配置；`--check` 只检查两份产物是否与维护源一致。产物无锚点、别名或 `<<` 合并，代理组的 `proxies`、`use` 使用行内列表并保留顺序。维护源集中定义规则，展开后的行数不是人工维护量。

填写当前模型启用机场的订阅、替换机场名称和调整监听地址、控制器密钥、DNS、TUN 后重新生成，再导入客户端。不要在生成产物中长期维护修改。源中的 `机场名称1`、`机场名称2`、`机场名称3`、`机场名称4` 是完整文本替换目标，不能先改成缩写；provider 键继续保留。首次订阅通过 DIRECT 获取。

## 出口与手选

普通自动路径为：业务 select → 机场优先或固定地区 rematch → 共享目标分类 → 对应探针 fallback → 同机场同地区 url-test。同区池按延迟选点，跨地区链路先换同机场地区，再跨机场；固定地区始终留在选定地区。

| 默认政策 | 三机场 | 四机场 |
|---|---|---|
| AI | 机场名称1日本专用 Google 池 | 机场名称1日本专用 Google 池 |
| 金融、Talkatone | 与 AI 共用专用池 | 机场名称2香港专用 Google 池 |
| Netflix、Disney+、HBO、Prime Video、Spotify、Reddit | 机场名称1 → 3 → 4 | 机场名称2 → 1 → 3 → 4 |
| 机场名称1优先 | 机场名称1 → 3 → 4 | 机场名称1 → 2 → 3 → 4 |
| 成本优先 | 机场名称3 → 1 → 4 | 机场名称3 → 1 → 2 → 4 |

机场名称1按日本 → 香港 → 新加坡 → 美国；机场名称2按香港 → 日本 → 新加坡 → 美国；机场名称3按日本 → 新加坡 → 香港 → 美国。机场名称4按香港 → 日本 → 新加坡 → 美国 → 台湾 → 欧洲 → 其他排序兜底。

- 默认代理、Telegram代理、FCM、OneDrive、Google、下载、游戏平台、Kryptex、境外影音和 Speedtest 默认机场名称3优先。Microsoft站点、海外通讯、TikTok站点、海外社媒、海外电商、TVB站点也默认机场名称3优先。哔哩东南亚站点默认新加坡-机场名称3优先，台湾限定站点默认台湾-机场名称3优先；默认项不限制主动手选。
- `纯下载`、`开发下载` 合并为 `下载`，共用普通准入及地区顺序，不保留 `下载-…` 自动链路。AUR、codeload、Release 保留较早的下载业务优先级；PKGBUILD 中其他源文件按实际目标分流。下载组不出现在其他业务菜单里。
- 普通业务可选各机场优先、五地区的各机场优先、自建家宽、全部节点、DIRECT，以及符合普通准入的原始订阅节点。隐私拦截另有 REJECT、REJECT-DROP；仅 Emby 可选 `低倍率/MITM节点`。
- 明确 CF 质询、管理 API、Access 等分流合入 AI，共用 AI 业务选择；不再单设 CF 业务组。CF 探针、普通 CF 物理组、DNS代理和 Cloudflare Tunnel 继续保留。
- 只有 AI、金融、Talkatone 可选专用池，业务入口保持 select。机场名称1日本 Google／CF 两个池恢复为 url-test，按延迟选点，三机场的金融、Talkatone 共用这两个池；日本地区识别包含“东京”。四机场另有机场名称2香港 Google／CF 两个 url-test 池，金融、Talkatone 默认使用香港 Google；三项敏感业务均可手选四个池。专用 url-test 组均设为 `hidden: false`，可在面板查看。默认 Google，CF 相邻备选；同一专用池的选点状态由选用它的业务共用，并与普通池分开。已有手动固定选点在重载、重启后保留，解除固定后恢复自动选点。默认不自动跨探针、地区、机场或直连；仍可主动改选普通政策、其他地区或实际节点。
- `自建/家宽节点` 是共享手选入口，换点影响所有选用它的业务。识别明确自建、家宽或独立英文标签，不以运营商名称判断。机场名称2订阅统一追加 ` [家宽]`，请确认订阅性质，替换机场名称时保留此后缀。
- 大小写不敏感的 `MITM|pornhub` 从所有自动池、普通业务及 GLOBAL 的原始节点列表、自建家宽入口排除。它们仅能从 `全部节点`、`低倍率/MITM节点` 显式手选；这两个入口首项及空池均为 REJECT。低倍率入口限制港日新及既有倍率／标签，其他地区特殊节点可在全部节点中选择。
- GLOBAL 使用 Google 物理回退组和手选入口，其引用链不含 rematch、业务组、专用池或低倍率/MITM 入口；可通过全部节点手选特殊节点。

普通池继续保留倍率、机场名称1香港质量限制、机场名称3日新独立 CTCU 排除（保留 CTCUCM）及美国低倍率例外。自动候选之外的普通节点仍可手选；特殊节点按上述入口选择。成本取舍通过业务默认与机场、地区顺序表达，不承诺实际节省比例或动态评估 IP 信誉。

上述八个业务的默认出口调整不改变 AI、金融、Talkatone 专用池及其他媒体业务默认项；新加坡、台湾业务保留同地区跨机场回退顺序。

各业务 select 保存独立选择；直接手选实际节点互不影响，选择共享辅助组则共用它的内部选择。独立自动池不代表独占节点、出口 IP、带宽或健康记录。同机场同地区仍可能换 IP，固定出口需求应手选实际节点。

## 探针与分流边界

| 探针 | URL | 预期状态 | 用途 |
|---|---|---|---|
| Google | `https://www.gstatic.com/generate_204` | 204 | 其余自动目标的通用基准 |
| CF | `https://cp.cloudflare.com/generate_204` | 204 | 明确质询/API/探针及指定站点 |
| GitHub | `https://github.com/robots.txt` | 200 | GitHub 相关目标与规则更新 |
| TG | `https://flora.web.telegram.org/apiw1` | 501 | 顶层机场优先链路中的 Telegram 域名/IP |

分类顺序：作用域内的 Telegram → GitHub 主站/API/Raw/codeload/Release 明确域名 → CF 明确端点 → 其余 GitHub → Google。GitBook 保留下载业务，但不强行归类 GitHub。业务规则和探针分类均不再按 CF 官方 IP 段或 Pages/Workers/R2 等共享托管后缀接管未知站点；不再下载宽泛 CF 域名及 IP 规则。配置的 IPv6 默认关闭。

`cf_sensitive_domain` 共维护八项：独立质询 `challenges.cloudflare.com`；管理 API `api.cloudflare.com`／`api.fed.cloudflare.com`；管理登录后缀 `dash.cloudflare.com`／`dash.fed.cloudflare.com`（包含 `one.dash.cloudflare.com`）；旧 Zero Trust 入口 `dash.teams.cloudflare.com`；Access 认证后缀 `cloudflareaccess.com`；探针 `cp.cloudflare.com`。精确端点与受限后缀分别覆盖质询、控制面和认证，不扩大到普通托管站。管理/API 入口的存在不等于它们均强制要求高信誉 IP；本配置将其与质询入口统一选路。[CF 控制面与认证域名](https://developers.cloudflare.com/cloudflare-one/traffic-policies/global-policies/)、[Access 认证接口](https://developers.cloudflare.com/cloudflare-one/access-controls/authenticate-agents/)。

业务分流和探针分类复用同一名单：业务指向 AI，探针分类仍使用 CF。其他 CF 主页、CDN 及托管站点按已有业务或普通规则处理。`linux.do` 的 CF 特例已移除。AI、下载、通信、Tunnel、DNS、隐私拦截和明确直连仍保留各自用途，Docker 等既定 R2 下载端点继续走下载。

去除特例后，使用 Google/Cloudflare 公开 DNS 的 IPv4 地址和实际规则快照核对，两模型中的 `linux.do`、`connect.linux.do`、PackyAPI 的 `.com`／`.ai` 主站及已解析的文档/API 子域、当前端点 `cf.api.fan` 均命中 `MATCH,默认代理`，无需另加域名规则。该核对不固化为逐站点回归；公开 DNS 地址及上游规则变化可能改变未来结果。[PackyAPI 当前入口与 API 端点](https://docs.packyapi.com/docs/register/)。

`challenges.cloudflare.com` 的 Turnstile 脚本随 AI 选择；默认专用池路径下，ChatGPT 与该质询入口共用池内选点。网站自身 `/cdn-cgi/challenge-platform/…` 的 JS 质询仍随网站域名分流。域名规则不能识别 HTTPS 路径，不增加 MITM。CF 探针 204 不代表质询成功；AI 手选普通政策时仍按目标分类使用 Google／CF 物理组，不保证最终节点相同。AI 改选出口或专用池故障回退仍可能更换 IP，其他业务的网站与质询入口也未必使用同一出口。[Turnstile 脚本](https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/)、[JS 检测路径](https://developers.cloudflare.com/cloudflare-challenges/challenge-types/javascript-detections/)、[质询出口限制](https://developers.cloudflare.com/cloudflare-challenges/concepts/how-challenges-work/)。

AI 本地补充源为 [ai.list](scripts/data/ai.list)，通过 `scripts/build/ai.sh` 生成 YAML/MRS，再由 `ai_extra_domain` 接入配置；每日上游同步后仍能重建，不直接在 `rules/` 维护补充。它与国外 AI 集位于宽泛国内域名、通用代理和 CF 明确端点之前，国内 AI、明确下载及现有隐私规则保持优先。第一方后缀覆盖认证、API、ChatGPT/Codex 控制通道、桌面资源及附件；专属 Azure/CDN 主机使用精确匹配，LiveKit 仅限定既有专属子域，不扩大到整个共享云平台。桌面更新补入 `oaisidekickupdates.blob.core.windows.net`；既有 Statsig 遥测拦截不因 AI 补充而放行。[官方桌面端点](https://learn.chatgpt.com/docs/enterprise/govcloud-configuration)、[上游 OpenAI 集](https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/openai.list)。

社区补充覆盖附件存储 `fileserviceuploadsperm.blob.core.windows.net`、功能配置 `featuregates.org`／`featureassets.org`／`prodregistryv2.org`、登录 CDN 和历史 Arkose 验证码主机。共享平台只列具体主机，不整体接管 Azure、Auth0 或 Arkose。异步回复通道使用锚定的 `DOMAIN-REGEX` 覆盖 `chatgpt-async-webps-prod-区域-编号.webpubsub.azure.com`，并保留历史生产主机 `fp-async-webps-prod.webpubsub.azure.com`；不覆盖 staging 或任意 Web PubSub 服务。旧客户端记录用于兼容，不能证明最新客户端仍调用所有主机。[附件下载记录](https://github.com/lencx/ChatGPT/issues/1033)、[功能配置记录](https://github.com/terminalcommandnewsletter/everything-chatgpt#statsig-feature-gates)、[社区规则](https://github.com/imetn/SurgeToolkit/blob/main/Rules/ai.list)、[异步通道故障记录](https://github.com/EFForg/privacybadger/issues/2949)。

官方 Remote Control 的配对、主机发现和中继属于此次 AI 域名核对范围。社区日志确认 `wss://chatgpt.com/backend-api/wham/remote/control/server` 和桌面云端通道 `wss://codex-cloud-backend.chatgpt.com/`；它们与 `codex-cloud-environments.chatgpt.com` 均被现有 `chatgpt.com` 后缀覆盖，不重复添加子域名规则。回归验证这些域名的 AI 分流和选择隔离，不代表真实配对、长连接或重连已验证；绕过系统代理的连接仍需实际进入代理/TUN 才能应用规则。自定义 SSH 主机不按端口泛归 AI。[Remote Control 日志](https://github.com/openai/codex/issues/39856)、[桌面云端 WebSocket 排查](https://github.com/openai/codex/issues/49829)。

AI 构建会移除相同条目及被后缀包含的子域条目，校验同时拒绝维护源中的这两类冗余。已有第一方后缀作为本地覆盖保障保留，不照抄外部 AI 集的所有条目；专属 CDN 和动态 Azure 通道只补缺口。`api.statsig.com` 的既有隐私拦截保持优先，即使部分客户端使用它初始化配置，也不在本次补齐中自动放行。

TG 只覆盖三机场的两种、四机场的三种顶层机场优先。两模型分别有 11、16 个 TG 隐藏组，测速叶子与上层回退均使用同一 URL、预期 501。固定地区选项继续使用 Google／CF／GitHub 分类；GLOBAL 及敏感专用池保持原探针。TG 作用域从模型的 `priority-order` 自动推导，不另维护一份策略名单。

501 是 DC5 HTTPS 端点对 HEAD 的实测响应，不是官方健康 API 的长期状态码承诺。它近似反映该端点响应，不能证明其他 DC、实际 TCP 目标、MTProto 业务或媒体访问正常。非 501、超时和 TLS 失败均不符合预期，不自动换成 Google／CF。Google、CF、GitHub 同样只验证单个 URL，不代表敏感业务登录、风控、整页资源、解锁或带宽。

探测调度按 Mihomo v1.19.30／v1.19.31 的实际实现分层理解：

| 层级 | 实际周期与按需行为 | 取舍 |
|---|---|---|
| 机场 provider 基准探针及附加 URL | 75 秒，`lazy: false`；启动也会检查 | 从 60 秒略调至 75 秒，保留备用节点和手选节点的持续健康记录 |
| 普通及敏感专用 url-test 叶子池（仅 `use`） | 复用 provider 的 75 秒周期，无独立计时器 | 不另设重复周期；各目标仍有独立健康记录 |
| 备用机场 fallback（仅 `use`） | 声明 30 秒、`lazy: true`，但已有 provider 的 75 秒周期优先 | 保留统一 fallback 参数；这里的 30 秒不会加速物理节点探测 |
| 顶层机场优先、规则更新 fallback（仅 `proxies`） | 独立 30 秒，`lazy: true` | 活跃时及时复核子组出口；子组选点变化不会自动更新父组健康记录 |
| 固定地区 fallback（`proxies` + `use`） | 子组入口独立 30 秒、按需；备用机场物理节点复用 75 秒 | 两层分别验证入口和物理节点，不将全部节点改为 30 秒 |
| 业务及手选 select | 无周期探测计时器 | 选择或使用下层入口可使其活跃；面板手动测速另计 |
| 订阅与规则资源刷新 | 86400 秒 | 属于资源更新，不是连通性检查，保持每日刷新 |

provider 正常定时轮次由每小时 60 次降至 48 次，减少 20%；这不是总探测请求或流量下降 20% 的承诺，启动、手动测速、故障复测及父组探测仍存在。`lazy: true` 的计时器仅在近期被使用时执行，但启动检查仍会执行，父组探测也可能使下层活跃。保留 provider 持续检查，避免把此次小幅调整变成冷备用策略。

每次探测超时保持 5000ms，给移动网络建连、TLS／QUIC 留出余量；缩短容易误判，延长则增加失败等待。嵌套子组沿用请求上下文，不按层数叠加 5 秒。provider 一轮共享最多 10 个并发任务，每个任务开始后独立计时；大量失败节点会产生排队，一轮可能超过周期，此次调整不降低单轮并发峰值。`unified-delay: false` 保持不变，成功探测不再追加用于排除握手耗时的第二次 HEAD。

url-test 的 `tolerance: 50` 是 50ms 延迟差：当前节点健康时，候选须快过此差值才切换，避免移动网络抖动导致频繁换点；当前节点失效或消失时不受该差值限制。它不是等待时间或失败防抖。选点有 10 秒缓存，订阅变化、失效和恢复也可能受缓存影响。`max-failed-times: 3` 保持不变：约 5 秒窗口内累计 3 次符合条件的拨号失败会触发复测，连接拒绝可立即触发；并非连续三轮探测失败，慢速失败或 UDP 丢包也不保证触发。75 秒／30 秒均不是恢复时限，实际还受缓存、任务排队和父组健康记录影响。

相同 provider、URL 的额外候选取并集并去重，状态码须一致；组数不等于探测请求数，也不意味着跨 provider 或父子层全局去重。自动池使用完整正向 `filter`，保证额外探针遵守准入。低倍率入口的 `filter-regions` 复用地区识别，`filter-tags` 保留倍率和标签；这些维护字段不写入内核配置。

内核使用 HEAD 并校验状态码，不检查正文、不跟随重定向。测速 API 在状态码不符时仍可能返回延迟，选路依据对应 URL 的 `extra[url].alive`。空池使用 REJECT；有候选但全部探测失败时内核仍可能尝试首节点，不等同于空池拒绝。

TCP、UDP 共用业务规则。UDP 命中首个业务后，所选出口不支持 UDP 就拒绝，不继续匹配其他业务，也不会按 UDP 能力另选节点；需保留订阅能力声明并手选支持 UDP 的节点。FCM 先匹配既有域名集，缺失时仅用 TCP 5228–5230 与 Google IP／AS24424 的交集补足；Google 443、UDP、非 Google 地址不会只因端口进入 FCM。

OneDrive、Telegram代理保留独立业务选择；Pixiv 归入海外社媒。国内明确直连规则优先，业务手选不覆盖更早的固定直连规则。Apple、哔哩哔哩、Cloudflare Tunnel 默认直连并保留手选；Tunnel 专用规则限制既定端点及 TCP/UDP 7844，保留真实 IP 解析。

## 迁移与设备使用

旧版本从 Git 历史获取；现有文件继续作为正式导入入口。旧 `纯下载`／`开发下载` 选择不会自动迁移到 `下载`，旧普通日本池名称也已从敏感业务菜单移除。失效选择回到业务首项；仍有效的普通节点选择继续保留，新默认不覆盖有效缓存选择。迁移后核对自己的业务选择；Emby 和全部节点首次需要主动手选。

本次将 `通用代理` → `默认代理`、`DNS出口` → `DNS代理`、`Telegram` → `Telegram代理`、`Google FCM` → `FCM`。四个新组名隔离旧名称的选择缓存，首次加载新组使用新的三优先默认项；不保留旧名称别名。`store-selected: true` 继续保存新组及其他业务的选择，不清空全局缓存。

进一步更名：`Microsoft` → `Microsoft站点`、`境外通信` → `海外通讯`、`TikTok` → `TikTok站点`、`境外社媒` → `海外社媒`、`境外电商` → `海外电商`、`TVB` → `TVB站点`、`哔哩东南亚` → `哔哩东南亚站点`、`台湾限定` → `台湾限定站点`。这八组也隔离旧选择，首次使用三优先默认项，并保留新加坡、台湾地区偏好。

名称不变的 `规则更新` 若固定过已移除的子组，应在面板解除固定选择，或使用控制器 `DELETE /proxies/{URL编码组名}` 恢复自动。订阅移除节点也不是即时撤销：v1.19.30 的 url-test 有 10 秒选点缓存，空池可能短暂保留旧节点，再收敛到 REJECT。上层 fallback 根据子组对应 URL 的健康记录切换；订阅更新和子组 `now` 的变化不会直接清除该记录，还需复测确认。

切换出口通常只影响新连接。临时统一业务出口可切换全局模式并在 GLOBAL 手选，结束后切回规则模式；境外 DoH 仍使用独立的 DNS代理。面板直接测 rematch 延迟可能失败，应通过实际代理入口访问目标，并结合连接日志确认出口。

OpenClash 使用原始模板并关闭 Smart 自动转换，设置 `auto_smart_switch=0`；保持 url-test／fallback 类型和规则模式。仅关闭 ASN、LightGBM 不能替代关闭 Smart，已经转换的运行配置应从原始模板重新加载。

两配置均显式使用 `tun.device: tun0` 支持裸核启动；安卓和路由客户端可自行覆写设备名，macOS 裸核使用 `utun` 开头名称。保留 system 栈、MTU 9000；客户端可能覆写 TUN、DNS 端口和路由，应核对实际运行配置。手机独立加载需支持这些 Mihomo 字段；仅设置 Wi-Fi HTTP 代理不能承载 Android FCM 推送，独立代理应使用 VPN/TUN 接管。iOS APNs 不归入 FCM。

境外默认解析及对应 `nameserver-policy` 中的 Cloudflare／Google DoH 均通过 `#DNS代理` 显式选路，继续并发查询。`DNS代理` 默认使用 `机场名称3优先-CF`，复用普通机场／地区 CF 实体组、家宽入口和普通节点手选；不经过 rematch，不引用敏感专用池、下载或 MITM 组，也不提供 DIRECT。国内、节点域名、引导解析及 Fake-IP 策略保持不变；`respect-rules: true` 保留，显式出口优先生效。DNS 自动菜单统一使用 CF 物理组；GLOBAL 继续使用 Google 物理组，不新增自动池或探针。CF 健康记录建立后，Google 探针故障不会决定 DNS 自动出口；Cloudflare／Google DoH 仍保留双上游冗余。

修改 Google、默认代理或 GLOBAL 选择不会改变上述 DNS 出口。DNS 手选只保证新建连接采用所选策略，已有 DoH 长连接和解析缓存可能继续使用；排障时重启内核可排除旧状态，不额外运行监听或清缓存脚本。统一 DNS 出口不保证跟随每项业务的实际节点，也不能控制机场服务器的远端解析；BrowserLeaks 的国家数量不作为正确性标准。

## 构建与验证

规则构建依赖 Bash、curl、Git、jq、Node.js 24、Ruby 和固定 Mihomo v1.19.30；配置测试另需 Python 3 与 GNU `timeout`。Python、Ruby 仅使用标准库。

每日北京时间 08:00 的规则流程只执行：同步上游 `rules/` → 运行所有 `scripts/build/*.sh` → 校验产物一次 → 提交规则变化。公开规则、手工源和构建脚本不仅服务这两份配置，继续保留。该流程不运行配置回归，也不下载回归使用的外部规则快照。

手工规则源位于 `scripts/data/` 和 `sources/Telegram/`；修改后运行对应构建脚本，再检查：

```sh
ruby scripts/validate-rules.rb
```

产物校验覆盖 YAML/MRS 配对、内容及源文件一致性、域名冲突、关键范围保护和构建脚本语法。指定 `--config` 只校验配置，不扫描规则库；参数可重复：

```sh
ruby scripts/validate-rules.rb --config configfull_new.yaml --config configfull_new_4.yaml
```

配置检查继续使用独立只读 CI，在正式配置、维护源、回归脚本或相关校验／工作流变化时触发，也可手动运行；单纯更新规则不触发。两份正式配置均执行回归。v1.19.30 执行 full，v1.19.31 复用同一规则快照执行 smoke，不追踪浮动最新版。

| 回归级别 | 覆盖范围 |
|---|---|
| `static` | 两产物生成一致性、两份配置基础加载及引用／循环／菜单／专用池隔离；不下载规则 |
| `smoke` | 两模型关键业务及默认出口、业务更名后的选择迁移、日本专用池按延迟选点与故障切换、手选在池类型变更及重载／重启后保留和解除固定、四类探针分类及 TG 作用域、UDP、Fake-IP、GLOBAL |
| `full`（默认） | 再验证节点准入、探测范围／去重、故障隔离／恢复、同区测速、DNS 策略及实际出口／上游冗余／CF 与 Google 探针隔离、手选重载／重启、订阅移除及空池 |

```sh
python3 scripts/test-config.py --suite static
python3 scripts/test-config.py --suite full --mihomo /path/to/mihomo-v1.19.30 --rules-dir /tmp/config-rules
python3 scripts/test-config.py --suite smoke --mihomo /path/to/mihomo-v1.19.31 --rules-dir /tmp/config-rules
```

`--mihomo` 默认为 `MIHOMO_BIN` 或 PATH 中的 mihomo。不指定 `--rules-dir` 时使用临时快照；指定目录不存在则创建，已存在则核验 URL、SHA256 与工作区规则版本，不静默修补。更换来源后需使用新的快照目录。本仓库规则读取工作区产物，外部规则从配置 URL 下载；失败不退化为模拟规则。

运行回归需允许回环监听。测试使用公开规则与本地模拟代理，不使用真实机场订阅，不验证公网端点、设备 TUN、吞吐、长期推送或媒体解锁；生成和测试不部署到设备。

域名回归保留认证、远程通道、CDN 重叠及动态主机的代表见证，不逐条重测同类域名；完整源/YAML/MRS 一致性由规则校验负责。AI 选择切换只验证规则集与动态规则两类入口，组名缓存迁移只运行一模型；两模型业务默认出口和机场差异仍分别验证。

## 项目文件与实现依据

```text
configfull_new.yaml / configfull_new_4.yaml    可导入的正式配置
config-source/common.yaml                   共同维护源
config-source/three-airports.yaml / four-airports.yaml  模型差异
scripts/build-config.rb                     两模型离线生成及一致性检查
scripts/test-config.py / mihomo_fixture.py   共用配置回归与回环夹具
scripts/validate-rules.rb                    规则产物或指定配置基础校验
scripts/build/ / scripts/data/              规则构建与手工规则源
scripts/canonicalize-domain-rules.awk        直连／代理域名覆盖去重
sources/Telegram/                          Telegram 构建源
rules/ / icon/                             公开规则产物与图标
.github/workflows/main.yml                  每日规则同步、构建、校验、发布
.github/workflows/config-check.yml          配置变更及手动回归
```

历史配置从 Git 查阅，临时诊断脚本与研究笔记不作为项目文件维护。实现语义以官方文档及固定版本源码为准：

- 健康检查、HEAD 与状态码：[adapter.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/adapter.go)、[健康检查配置](https://wiki.metacubex.one/config/proxy-groups/)、[parser.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/outboundgroup/parser.go)、[healthcheck.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/provider/healthcheck.go)。
- 候选、选点与手选缓存：[groupbase.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/outboundgroup/groupbase.go)、[urltest.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/outboundgroup/urltest.go)、[fallback.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/outboundgroup/fallback.go)、[selector.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/outboundgroup/selector.go)、[proxies.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/hub/route/proxies.go)；组包装器见 [config.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/config/config.go#L895)。
- 重匹配与 UDP：[rematch.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/outbound/rematch.go)、[tunnel.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/tunnel/tunnel.go)；设备设置见 [DNS](https://wiki.metacubex.one/config/dns/)、[TUN](https://wiki.metacubex.one/config/inbound/tun/)。
- TG 端点：[Telegram DC 域名与传输](https://core.telegram.org/mtproto/transports#uri-format)、[Web K 的 apiw1 配置](https://github.com/morethanwords/tweb/blob/master/src/lib/mtproto/dcConfigurator.ts)；CF 分类仅引用维护源中的明确端点名单。
- 推送接管范围：[Google FCM 网络要求](https://firebase.google.com/docs/cloud-messaging/network-configuration)、[Apple APNs 网络要求](https://support.apple.com/en-ca/102266)。

## 使用声明与致谢

沿用上游要求：禁止转载或发布至中国大陆平台；使用者应遵守所在地法律法规。本项目仅用于学习研究，不保证规则完整性、准确性或适用性，请勿用于商业或非法用途，使用风险由使用者承担。

感谢上游项目及 [Mihomo](https://github.com/MetaCubeX/mihomo)、[OpenClash](https://github.com/vernesong/OpenClash)、[ACL4SSR](https://github.com/ACL4SSR/ACL4SSR)、[Custom_OpenClash_Rules](https://github.com/Aethersailor/Custom_OpenClash_Rules)、[blackmatrix7](https://github.com/blackmatrix7/ios_rule_script)、[meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat)、[SSTap-Rule](https://github.com/FQrabbit/SSTap-Rule) 等配置、规则和工具来源。各资源许可与署名要求以上游为准。
