# Rules

基于 [Lanlan13-14/Rules](https://github.com/Lanlan13-14/Rules) 的自用分支，维护 Mihomo 配置与分流规则。不接受需求类 issue，欢迎问题反馈和讨论。

## 配置

| 文件 | 用途 |
|---|---|
| [configfull_new.yaml.bak](configfull_new.yaml.bak) | 原三机场配置备份：机场名称1、3、4 |
| [configfull_new_4.yaml.bak](configfull_new_4.yaml.bak) | 原四机场配置备份：增加机场名称2家宽 |
| [configfull_new.yaml](configfull_new.yaml) | 三机场主配置：五类探针、共享目标分类、同区测速、下载扁平回退 |
| [configfull_new_4.yaml](configfull_new_4.yaml) | 四机场配置：冻结上一轮设计，待三机场定稿后同步架构 |

每次加载一份完整配置，无需拼接。原两份模板以 `.yaml.bak` 备份，新配置接替原文件名；新模板最低支持官方 **Mihomo v1.19.30**，以 v1.19.30 执行必要运行回归，v1.19.31 执行关键兼容检查，未引入 v1.19.31 独有特性。原模板与冻结的四机场配置保留基础校验和关键业务验证，CI 不追踪浮动最新版。使用前填写订阅，核对节点过滤条件，并调整监听地址、控制器密钥、DNS 和 TUN 参数。首次订阅需能直连获取。`机场名称1` 等字符串是替换目标，修改真实名称时应完整替换，不能先改为缩写。

升级时以新模板迁移个人设置。三机场业务组统一开放 19 个出口选项及全部原始订阅节点，只按用途调整默认项和排列顺序。菜单包含机场名称1／3优先、五地区的两种机场优先顺序、两种下载入口、自建家宽、低倍率／MITM、机场名称1日本 Google／CF 池及 DIRECT。隐私拦截另外保留 REJECT、REJECT-DROP。台湾限定默认台湾、纯下载默认下载政策，但都允许主动选择其他出口。

AI、金融、Talkatone 默认共用 `机场名称1-日本-Google`，`机场名称1-日本-CF` 为相邻手选项；各业务独立保存选择。Google 是多服务混用时的通用基准，不代表已经证明其对敏感业务更准确；CF 204 也不能代表目标站点的风控、登录或源站可用。两个池沿用相同的节点准入，不新增探针。默认不按域名分别选点，也不在 Google 失败时自动换到 CF、其他地区、其他机场或直连。固定机场和地区不等于固定 IP，需要固定节点时直接手选实际节点。

有效缓存选择优先于新默认：已手选 CF 的业务继续使用 CF，采用新默认需主动选择 Google 池。已移除的名称回到该业务首项，仍存在的原始节点选择继续保留。选择共享的 `自建/家宽节点` 或 `低倍率/MITM节点` 后会共享该辅助组内部选择；直接手选原始节点仍各自独立。Google FCM 默认机场名称1优先，OneDrive 默认机场名称3优先，各自选择不影响 Google / Microsoft。

## 分流与出口

以下说明以新模板为准；展示的新名称以三机场配置为准，冻结的四机场配置仍使用旧名称。规则确定业务分组，业务组保存独立选择；普通自动、固定地区与下载入口按目标选择相应探针。旧模板仍将 OneDrive 合并在 Microsoft、FCM 合并在 Google，金融和 Talkatone 仍采用跨机场高要求政策。

| 默认政策 | 三机场顺序 | 四机场顺序 |
|---|---|---|
| AI | 机场名称1日本 Google 自动池 | 机场名称1日本 CF 自动池 |
| 金融、Talkatone | 与 AI 共用机场名称1日本 Google 自动池 | 各自的机场名称2香港自动池 |
| 高要求媒体、Reddit | 1 → 3 → 4 | 2 → 1 → 3 → 4 |
| 普通 | 1 → 3 → 4 | 1 → 2 → 3 → 4 |
| 成本优先 | 3 → 1 → 4 | 3 → 1 → 2 → 4 |

- Microsoft、FCM、Telegram、境外通信和通用代理采用普通政策。OneDrive、Google（含 GoogleVPN）、开发下载（含 GitHub、Docker、HuggingFace）、游戏平台、Kryptex、纯下载、境外影音和测速采用成本优先；Emby 使用低倍率手选入口。Netflix、Disney+、HBO、Prime Video、Spotify、Reddit 保留高要求政策。
- 可跨机场的自动链路先换同机场地区，再跨机场。普通机场名称1按日本 → 香港 → 新加坡 → 美国；普通机场名称3按日本 → 新加坡 → 香港 → 美国。纯下载各机场按日本 → 新加坡 → 美国 → 香港，机场名称4另保留其他地区兜底。
- 三机场 AI、金融、Talkatone 默认共用 Google 探针自动池和自动选点状态，业务手选实际节点仍独立；四机场暂保留独立自动池。默认专用池只在默认机场和地区内换节点；池空或全部故障均不自动跨地区、跨机场或直连。三机场沿用机场名称1日本，四机场金融和 Talkatone 沿用原高要求首选的机场名称2香港；AI 两版均为机场名称1日本，四机场冻结版仍使用 CF 探针。需要其他出口时，可在对应业务中改选其他分组或实际节点；主动选择跨机场政策后遵循该政策的回退范围。哔哩东南亚默认新加坡，TVB 按实际平台手选地区。
- FCM 先匹配现有 `googlefcm` 域名集（如 `mtalk.google.com`）；缺失域名时，仅以 TCP 5228–5230 与 Google IP / AS24424 地址集的交集补足。更早的明确业务规则仍优先，Google 443、UDP 和非 Google 地址不会仅因端口进入 FCM；`fcm.googleapis.com` 发送 API 仍按 Google 归类。OneDrive 使用现有独立规则集，保留更早的国内直连例外。
- Pixiv 的 `pixiv.net`、`pximg.net` 归入境外社媒，默认机场名称1优先。Telegram 的域名和 IP 共用独立业务组，与境外通信的选择互不影响。
- AUR 的 `aur.archlinux.org`（网页、RPC、Git）归入纯下载，默认机场名称3、日本优先；PKGBUILD 中其他域名的源文件下载仍按目标域名分流。
- 明确国内直连规则优先。Apple、哔哩哔哩和 Cloudflare Tunnel 默认直连，保留手选入口；业务手选不覆盖更早的固定直连规则。Tunnel 专用规则限定端点及 TCP/UDP 7844，并保留真实 IP 解析。
- `自建/家宽节点` 是共享手选入口，换点影响所有选用它的业务。它只认明确的自建、家宽或独立英文标签，不以运营商名称判断；四机场版为机场名称2统一追加 ` [家宽]`，使用前应确认订阅性质，修改前缀时保留此后缀。
- 地区码支持 `HK01`、`JP01` 等编号。机场名称3日新自动池排除独立 `CTCU` 标签，保留 `CTCUCM`；各池保留自身倍率筛选，被排除的自动候选仍可手选。

TCP、UDP 共用业务规则表。UDP 命中首个业务后，所选出口不支持 UDP 就拒绝，不继续匹配后续业务；自动池不会按 UDP 能力另选节点，需保留订阅原始能力声明并手选支持 UDP 的节点。

所有机场每 60 秒持续探测，上层回退每 30 秒按需检查。探针只验证可达性和延迟，不代表带宽、媒体解锁或整页资源可用，也不承诺恢复时限。同机场同地区仍可能换 IP；固定出口需求应手选实际节点。空池使用 REJECT，有候选但全部探测失败时核心仍可能尝试首节点。

订阅更新不是即时撤销：v1.19.30 的 `url-test` 选点缓存为 10 秒，候选列表变空后可能短暂继续使用原节点。回归检查这段过渡只保留原机场原地区的旧节点，随后收敛到 REJECT。

三机场的敏感业务共享自动选点状态，四机场配置暂保留独立状态；同一 provider、同一探针 URL 的健康记录由内核共用。保留叶子池的节点倍率、CTCU、香港质量、纯下载与 Emby 筛选不变，固定地区沿用各地区现有准入范围；成本优化通过业务分配与机场顺序实现，没有据此承诺实际节省比例。

切换出口通常只影响新连接。临时统一出口可切换全局模式并在 `GLOBAL` 选实际节点，结束后切回规则模式。面板直接测 rematch 延迟可能失败，应通过实际代理入口访问目标站点，并结合连接日志确认出口。

## OpenClash

使用原始模板，关闭 Smart 自动转换，保持 `url-test`/`fallback` 组类型并使用规则模式。仅关闭 ASN、LightGBM 不能替代关闭 Smart 转换；已被覆写成 Smart 的运行配置需从原始模板重新加载。

OpenClash 的对应设置为 `auto_smart_switch=0`。加载后在面板核对实际分组类型；配置以官方 Mihomo 验收，不启用 Smart 专属功能。

三机场配置显式配置 `tun.device: tun0`，用于裸核启动；安卓与路由设备客户端按自身设置覆写设备名。macOS 裸核启动时改用 `utun` 开头的名称；四机场配置仍冻结，待同步时恢复此字段。保留 `system` 栈、MTU 9000 与既有 DNS 语义，DNS 服务器列表仅用 YAML 锚去重。OpenClash 或手机 App 可能覆写 TUN、DNS 端口和路由设置，应核对实际运行配置。手机独立加载需要支持这些 Mihomo 字段；仅设置 Wi-Fi HTTP 代理无法承载 Android FCM 推送连接，独立代理应使用客户端的 VPN/TUN 接管。iOS APNs 不归入 FCM。

配置回归使用官方内核、真实规则快照与本地假代理，覆盖选路和故障边界；不等同于路由器或手机的公网吞吐、长期推送存活、媒体解锁验收。此次文件调整不自动部署到设备。

## 三机场架构与迁移

本轮只修改三机场配置，四机场配置冻结。五类探针共用一张目标分类表，机场、地区、倍率与成本顺序保持不变。同机场同地区仍由 `url-test` 优先选择低延迟节点，不改为按订阅顺序盲选。

| 探针 | URL | 预期状态 | 用途与边界 |
|---|---|---|---|
| Google | `https://www.gstatic.com/generate_204` | 204 | 未单独分类目标的基准；不证明所有网站都可达 |
| CF | `https://cp.cloudflare.com/generate_204` | 204 | CF 自有域名、已知 CDN 域名和官方网段；只能反映该 CF 端点 |
| GitHub | `https://github.com/robots.txt` | 200 | github.com；API 和其余 GitHub 相关域名是近似覆盖 |
| GitHubRaw | `https://raw.githubusercontent.com/MetaCubeX/mihomo/v1.19.30/README.md` | 200 | Raw 内容及本配置规则更新 |
| GitHub归档 | `https://codeload.github.com/_ping` | 200 | codeload 归档；Release 资产是近似覆盖 |

分类顺序：Raw → codeload/Release → GitHub 主站/API → CF 域名或 IP → 其余 GitHub 域名 → 通用。明确 GitHub 服务先于 CF 判断，避免 CDN 地址掩盖实际服务类型。GitBook 不再被当作 GitHub，仍属于开发下载；AUR 仍属于纯下载，依据目标使用 CF 或通用探针。GitHub API 不额外设置周期探针，避免每个节点消耗未认证 API 配额。

新增 `cloudflare_cdn_ipv4/ipv6` 规则集，从 Cloudflare 官方文本列表每天更新，通过可直接拨号的 `机场名称1优先-CF` 获取。分类只发生在代理自动入口内部，既有国内直连与业务规则仍先执行。未知域名的 IP 判断需要解析真实地址，可能增加首次连接延迟；Fake-IP 应先还原域名再解析。IPv6 规则准备就绪，但配置的 IPv6 开关仍为关闭。

| 路径 | 结构 |
|---|---|
| 普通自动 | 业务 select → 机场名称1／3优先 rematch → 共享分类 → 对应探针 fallback → 地区 url-test |
| 固定地区 | 业务 select → 地区 rematch → 共享分类 → 同地区、对应探针 fallback → 地区 url-test |
| 敏感业务默认 | AI / 金融 / Talkatone 各自 select → 同一个机场名称1日本 Google url-test |
| 纯下载自动 | 纯下载 select → 下载 rematch → 共享分类 → 下载 fallback → 下载地区 url-test |
| GLOBAL | 直接选择物理回退组或节点，不引用 rematch |

下载只建立通用、CF、归档三类池，保留独立倍率和特殊用途筛选；删除机场中间回退层，按原顺序展开各地区叶子。Raw/网页不是现有纯下载规则的目的地，对下载标记显式拒绝这两个分支，防止误用普通池。手选固定地区仍是普通地区策略；要保留下载准入，应选择下载自动入口。

固定地区会按目标使用正确探针，但始终留在指定地区。台湾沿用现有通用台湾准入，机场名称4的地区候选不新增倍率限制。AI、金融、Talkatone 默认共用 Google 日本池和自动选点状态，手选实际节点仍分别保存；CF 成功不等于 AI 登录、金融风控或 Talkatone 业务一定成功。

相对上一版候选，策略组从 100 增至 **197**：36 个 select、89 个 url-test、72 个 fallback；rematch 从 3 增至 15，子规则为 7 张。增加的是五类可达性与固定地区所需的隐藏状态，业务入口数不变。分类逻辑只写一次。不同探针叶子不能合并：父组用 Raw 测一个通用 url-test，并不会使该子组按 Raw 的健康和延迟重新选点。

全部超时统一为 5000ms；provider 每 60 秒持续检查，父级每 30 秒按需检查，延迟容差仍为 50ms。`max-failed-times: 3` 是实际连接失败触发复测的阈值，不是连续三轮探针失败才切换；`tolerance` 也不是失败防抖。Mihomo 使用 HTTPS HEAD、校验状态码，不检查正文且不跟随重定向。403、429、5xx、TLS 失败和超时不能被判为预期服务正常。状态码不符时，控制器测速 API 仍可能返回延迟；选路看对应 URL 的 `extra[url].alive`，不能只看面板是否显示延迟。

额外探针使用完整正向 `filter`，防止内核未把 `exclude-filter` 传给 provider 而多测不入池节点。修改地区/倍率规则时须同步 `filter_auto_*` / `filter_download_*`，并运行准入测试。同一 provider、URL 的额外候选取并集并去重；同 URL 各组必须使用相同状态码。机场名称4保留完整备用探测，父组仍独立探测所引用的子组。组数不等于请求数，本轮不沿用旧三探针的流量统计，也不承诺额外探针零成本。

回归保留节点准入、provider 探测范围与去重、五类故障隔离和实际分流边界。删除启动流量统计及重复场景矩阵；测试不以组数、启动请求数或固定案例数量作为通过条件。

单个成功探针只能证明该 URL 此刻可达。CF 探针不能证明每个租户的 WAF、源站或登录可用；归档探针不能精确证明 Release 资产可用；网页探针不能精确证明 API 可用。纯配置无法对多个 URL 做 AND/多数表决，也无法证明整页全部依赖可用。本轮未增加守护进程或控制器脚本，未使用 v1.19.31 独有特性。

### 命名与缓存迁移

| 层级 | 示例 |
|---|---|
| 自动入口 | `机场名称1优先`、`机场名称3优先` |
| 固定地区入口 | `日本-机场名称3优先` |
| 下载入口 | `下载-机场名称3优先` |
| 物理回退 | `机场名称1优先-CF`、`日本-机场名称3优先-GitHub` |
| 同区测速池 | `机场名称1-日本-Google`、`机场名称1-日本-CF` |
| 备用池 | `机场名称4-备用-GitHub归档` |
| 下载物理回退 / 测速池 | `下载-机场名称3优先-GitHub归档` / `下载-机场名称3-日本-GitHub归档` |
| 手选辅助组 | `自建/家宽节点`、`低倍率/MITM节点` |
| 内部规则 | `分流-业务规则`、`分流-探针分类`、`分流-GitHubRaw-出口` |

`机场名称1优先`对应机场名称1 → 机场名称3 → 机场名称4；`机场名称3优先`对应机场名称3 → 机场名称1 → 机场名称4。不再用质量／成本作为显示名称，避免误解为动态评估 IP 信誉或订阅价格。探针标识统一为 Google、CF、GitHub（网页）、GitHubRaw、GitHub归档；它们表示健康检查端点，不表示该组只能访问这些服务。`机场名称x` 完整占位符、provider 键及业务名称保留。四机场暂不应用本轮命名。

普通业务可选 rematch 自动入口，GLOBAL 只提供可直接拨号的物理组和节点，例如 `机场名称3优先-Google`，其引用链不含 rematch。面板直接对 rematch 测延迟可能失败，应通过实际代理入口访问目标站点验证。

迁移时，旧 `自动-质量优先` / `自动-成本优先` 对应新 `机场名称1优先` / `机场名称3优先`；旧 `地区-日本-成本优先` 对应 `日本-机场名称3优先`；下载入口同样改用机场名称。旧名称失效时会回到业务默认项，应核对自己的手选意图。仍有效的 CF 或实际节点手选不会被新默认覆盖。不创建兼容别名组、不清空全部选择或 Fake-IP 缓存，也不自动操作设备缓存。

名称不变的 `规则更新` 若固定过已改名子组，需在面板解除固定选择，或使用控制器 `DELETE /proxies/{URL编码组名}`；恢复自动后继续按原机场顺序使用 GitHubRaw 探针更新规则。

## 官方依据

- 敏感业务探针取舍：当前 AI 规则覆盖多家服务；Google 作为通用基准，CF 作为手选替代，不宣称任一端点代表完整业务。以 [ChatGPT 官方网络要求](https://help.openai.com/en/articles/9247338-network-recommendations-for-chatgpt-errors-on-web-and-apps) 为例，业务还依赖多个域名和 WebSocket；[Cloudflare 挑战说明](https://developers.cloudflare.com/cloudflare-challenges/concepts/clearance/)涉及访客与设备验证，单个 204 响应不能代表通过挑战。

- 探针 HEAD、状态码与重定向：[v1.19.30 adapter.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/adapter.go)。GitHub 官方连接检查使用的主站/归档端点见 [Actions runner connectivity checks](https://github.com/actions/runner/blob/main/docs/checks/actions.md)；API 限额见 [GitHub REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)。
- CF 边缘与源站的边界见 [Cloudflare CDN-CGI 文档](https://developers.cloudflare.com/fundamentals/reference/cdn-cgi-endpoint/)；分类地址来自官方 [IPv4](https://www.cloudflare.com/ips-v4)、[IPv6](https://www.cloudflare.com/ips-v6) 列表。

- 独立选择与自动选点：[select 文档](https://wiki.metacubex.one/config/proxy-groups/select/)、[url-test 文档](https://wiki.metacubex.one/config/proxy-groups/url-test/)。缓存候选失效与选点状态按 [v1.19.30 selector.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/outboundgroup/selector.go)、[urltest.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/outboundgroup/urltest.go) 核对。
- `use` 组额外探针注册、相同 URL 合并与 provider 周期，以 [v1.19.30 parser.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/outboundgroup/parser.go)、[healthcheck.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/provider/healthcheck.go) 为准；故障顺序与全红行为见 [fallback.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/outboundgroup/fallback.go)。
- 分层健康状态和恢复：[adapter.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/adapter.go)、[groupbase.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/outboundgroup/groupbase.go)；旧固定选择恢复与解除：[executor.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/hub/executor/executor.go)、[proxies.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/hub/route/proxies.go)。
- TCP 重匹配与 UDP 能力边界：[rematch.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/outbound/rematch.go)、[tunnel.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/tunnel/tunnel.go)。保留首业务后的 UDP 拒绝护栏，避免核心因不支持 UDP 而继续匹配其他业务。
- [DNS 文档](https://wiki.metacubex.one/config/dns/)、[TUN 文档](https://wiki.metacubex.one/config/inbound/tun/)、[v1.19.30 TUN 实现](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/listener/sing_tun/server.go)。
- 推送范围与客户端接管：[Google FCM 网络要求](https://firebase.google.com/docs/cloud-messaging/network-configuration)、[Apple APNs 网络要求](https://support.apple.com/en-ca/102266)。

## 项目文件

```text
.github/workflows/main.yml          每日规则构建、产物校验与发布
.github/workflows/config-check.yml  配置变更与手动配置回归
configfull_new.yaml.bak      原三机场配置备份
configfull_new_4.yaml.bak    原四机场配置备份
configfull_new.yaml       新三机场配置
configfull_new_4.yaml     新四机场配置
rules/                      发布规则，保留构建输入及 YAML/MRS 等产物
icon/                       配置引用的图标
sources/Telegram/           Telegram 构建源
scripts/
  build/                    规则构建脚本
  data/                     手工规则源
  canonicalize-domain-rules.awk
  validate-rules.rb          规则产物或指定配置的基础校验
  test-config.py             统一配置回归入口
  mihomo_fixture.py          回环代理、DNS、内核进程与规则快照
README.md
LICENSE
.gitignore
```

历史配置从 Git 查阅。临时诊断脚本、浏览器采集结果和审计笔记不作为项目文件维护。

## 构建与验证

规则构建使用 Bash、curl、Git、jq、Node.js 24、Ruby 和固定 Mihomo v1.19.30；配置测试另需 Python 3 与 GNU `timeout`。Python 仅使用标准库，YAML 由 Ruby 解析。

每日北京时间 08:00 的发布流程只执行：同步上游 `rules/` → 构建 → 校验产物一次 → 提交规则变化。它不运行配置回归，也不下载配置测试所用的外部规则快照。手工修改规则源后，运行对应的 `scripts/build/*.sh`，再检查产物：

```sh
ruby scripts/validate-rules.rb
```

产物校验保留 YAML/MRS 配对和内容一致性、源文件一致性、域名冲突、关键范围保护及构建脚本语法检查。指定 `--config` 时只验证该配置，不扫描规则产物；此参数可重复：

```sh
ruby scripts/validate-rules.rb --config configfull_new.yaml
```

配置检查为独立只读 CI，在配置、回归脚本或相关校验/工作流文件变化时运行，也可手动触发；单纯更新 `rules/` 不触发。它只准备一次共享规则快照，先跑 v1.19.30 的 `full`，再由 v1.19.31 复用快照跑 `smoke`。

| 回归级别 | 覆盖范围 |
|---|---|
| `static` | 四份配置的 YAML、重复定义、引用、循环、内核加载及关键政策约束；不下载规则 |
| `smoke` | 加上四份配置的关键业务与默认出口，以及三机场配置的五类分类、UDP 护栏、Fake-IP/CF 与 GLOBAL |
| `full`（默认） | 加上三机场配置的节点准入、探针范围/去重、故障隔离与恢复、同区测速、DNS、独立手选的重载/重启和订阅移除后的空池收敛 |

原始配置及冻结的四机场配置不再重复运行完整故障矩阵；旧版本缓存迁移、长期空闲观测和逐机场规则更新链不作为持续回归项目。业务差异以独立案例表表达，测试不通过历史重命名映射转换待测配置。

```sh
python3 scripts/test-config.py --suite static
python3 scripts/test-config.py --suite full --mihomo /path/to/mihomo-v1.19.30 --rules-dir /tmp/config-rules
python3 scripts/test-config.py --suite smoke --mihomo /path/to/mihomo-v1.19.31 --rules-dir /tmp/config-rules
```

`--mihomo` 默认为 `MIHOMO_BIN` 或 PATH 中的 `mihomo`。不指定 `--rules-dir` 时使用临时快照；指定的目录不存在时创建，已存在时严格核验 URL、SHA256 和工作区规则版本，不会静默修补不完整快照。更新来源后如需重新下载，应使用新的快照目录。本仓库规则读取当前工作区产物，外部规则从配置 URL 下载；下载失败即失败，不退化为模拟规则后报告通过。

运行回归需要允许回环监听。测试使用公开规则与本地模拟代理，不使用真实机场订阅，不验证公网探针端点或设备 TUN 接管效果，也不会部署配置。

## 使用声明与致谢

沿用上游要求：禁止转载或发布至中国大陆平台；使用者应遵守所在地法律法规。本项目仅用于学习研究，不保证规则的完整性、准确性或适用性，请勿用于商业或非法用途，使用风险由使用者承担。

感谢上游项目及 [Mihomo](https://github.com/MetaCubeX/mihomo)、[OpenClash](https://github.com/vernesong/OpenClash)、[ACL4SSR](https://github.com/ACL4SSR/ACL4SSR)、[Custom_OpenClash_Rules](https://github.com/Aethersailor/Custom_OpenClash_Rules)、[blackmatrix7](https://github.com/blackmatrix7/ios_rule_script)、[meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat)、[SSTap-Rule](https://github.com/FQrabbit/SSTap-Rule) 等配置、规则和工具来源。各资源的许可与署名要求以上游为准。
