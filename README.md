# Rules

基于 [Lanlan13-14/Rules](https://github.com/Lanlan13-14/Rules) 的自用分支，维护 Mihomo 配置与分流规则。不接受需求类 issue，欢迎问题反馈和讨论。

## 配置文件

| 文件 | 用途 |
|---|---|
| [configfull_new.yaml](configfull_new.yaml) | 当前三机场主配置，使用机场名称1、3、4 |
| [cinfigfull_new_4.yaml](cinfigfull_new_4.yaml) | 独立四机场模板，增加机场名称2家宽；准备好订阅后再使用 |
| [configfull.bak.yaml](configfull.bak.yaml) | 重构前的原版备份，用于对照 |

每次加载一份完整配置，无需拼接。当前模板使用官方 Mihomo 的 `rematch`，固定验收版本为 **v1.19.30**；不要直接当作 Stash 或其他内核的通用模板使用。

使用前填写机场订阅，核对节点名称过滤条件，并按自己的环境调整监听地址、控制器密钥和 DNS。升级时以新模板为基础迁移个人设置，旧分组名称与缓存选择不保证兼容。

## 如何选择出口

规则先确定业务分组，业务 `select` 保存用户选择，自动链路再按 CF、GitHub 或通用探针选择节点。

TCP、UDP 共用 `sub-rules.业务分流` 的规则顺序。TCP 通过 `NETWORK,tcp,业务分流入口` 的 rematch 直接进入业务表，保留具体业务规则信息。UDP 继续用 SUB-RULE 确定首个业务，选择不支持该协议的节点时由外层拒绝，不再落到后面的其他业务或直连规则；对应 v1.19.30 的 [子规则匹配](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/rules/logic/logic.go) 与 [UDP 出口检查](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/tunnel/tunnel.go)。官方自动池也不会按 UDP 能力另选节点；通话、游戏需要手选实际支持 UDP 的节点，保留订阅原有的能力声明。

| 默认政策 | 三机场顺序 | 四机场顺序 |
|---|---|---|
| 最高要求（AI） | 机场名称1日本自动池 | 同左 |
| 高要求 | 1 → 3 → 4 | 2 → 1 → 3 → 4 |
| 普通 | 1 → 3 → 4 | 1 → 2 → 3 → 4 |
| 成本优先 | 3 → 1 → 4 | 3 → 1 → 2 → 4 |

- 自动链路先在同机场换地区，再跨机场。机场名称1按日本 → 香港 → 新加坡 → 美国；机场名称3按日本 → 新加坡 → 香港 → 美国。纯下载使用独立策略。
- 业务可以手选机场优先链、指定地区或实际节点，具体以组内选项为准。地区链仍可跨机场；地区和 IP 稳定是尽力而为，不是固定出口承诺。
- AI 默认仅在机场名称1的日本池内自动择优，不自动跨地区或机场；允许主动选择其他链路或节点。金融保持独立；Netflix、DisneyPlus 等需要分别选路的服务也各自保留。
- 哔哩东南亚默认新加坡：它属于[官方列出的东南亚服务地区](https://www.bilibili.tv/en/about)，也是配置现有的东南亚地区池；不同地区的内容可能不同，通用探针不保证内容解锁。已有保存的选择优先，升级后如需新默认请手动切换。
- TVB 使用普通政策，默认机场名称1优先自动链；规则同时包含 myTV SUPER、TVBAnywhere 和北美版服务，需按实际平台手选地区。[myTV SUPER 香港版](https://promo.mytvsuper.com/tc/faq_webview)可选香港；[TVBAnywhere 全球版](https://staticsfm.tvbanywhere.com.sg/html/en/payment-tnc.html)应选套餐支持的海外地区，不能把香港作为所有 TVB 服务的通用出口。
- Google 包含 GoogleVPN、FCM；Microsoft 包含 OneDrive；开发下载包含 GitHub、Docker、HuggingFace。共享云父域 `blob.core.windows.net`、`vsassets.io` 不整体归入开发下载，具体资源由 AI、游戏等业务规则判断；普通境外影音、通信、社媒及游戏平台按各自分组共用选择。
- Telegram 独立为可见业务组，域名和 IP 规则共用该组；沿用成本优先政策及完整手选候选，选择与境外通信互不影响。
- `自建/家宽节点` 是共享手选入口：修改它会影响所有选择该入口的业务。普通业务之间的独立选择互不影响。
- 家宽入口只认明确的“自建”“家宽”或独立英文标签 `home`、`private`、`The_house`、`Self_Back`；CF、HKT、ATT 等线路或运营商名称不作为依据。四机场版给机场名称2统一追加 ` [家宽]`，原始名称只有 `HK01` 等地区编号的节点也可进入家宽入口；使用前须确认该订阅整体为家宽，修改显示前缀时保留此后缀。旧版机场名称2的节点名称会因此改变，原有节点手选可能需要重选。
- 英文地区码支持紧接数字编号，如 `HK01`、`JP01`、`SG01`、`US01`、`TW01`；仍拒绝 `XHK01`、`JP01test` 等字母子串。机场名称3的日新自动池将空格、连字符、竖线、括号等分隔的独立 `CTCU` 标签排除，继续保留 `CTCUCM`。
- 机场名称3美国自动池保留低倍率和 CTCU 例外，仍排除 BETA、wcloud、traffic 和 ≥5 倍节点；问题节点继续保留在业务手选列表中。
- 临时让流量统一走单个节点：切换客户端到全局模式，再在 `GLOBAL` 选择该节点；结束后切回规则模式。
- 手选结果在核心重启后保留；切换出口通常只影响新连接，已有连接不会自动迁移。

明确国内直连规则优先于普通境外归类。Apple、哔哩哔哩和 Cloudflare Tunnel 默认直连，保留各自的手选入口。

业务组只控制实际命中它的流量，较早的固定直连规则不受该组手选影响。Emby 默认的低倍率入口是手选组，故障时需主动换节点。空池使用 REJECT；有候选但全部探测失败时，核心仍可能尝试首节点。

所有机场（含备用机场名称4）每 60 秒持续探测；上层回退统一为 30 秒、按使用情况检查。手选组复用通用探测，CF/GitHub 专用池自行注册对应探针，不再为全部手选节点注册 CF 探测；额外探针仍使用 [provider 的周期和超时](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/provider/healthcheck.go)。探测周期不等于故障恢复上限：探测排队、超时、组状态更新和应用重试都会影响恢复。连接失败仅在符合条件时触发复测，`max-failed-times` 不承诺固定切换时间。

HTTP 探针只比较可达性和响应延迟，不验证 AI/媒体解锁、下载吞吐或 UDP。需要固定 IP 的业务应手选实际节点；同机场同地区的自动池仍会换 IP。首次使用需确保订阅地址可直连获取；TUN 的协议栈、网卡名和 MTU 应按目标设备验证。

以下行为按 v1.19.30 源码核实，调参时需保留其边界：

- [`URLTest.fast()`](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/outboundgroup/urltest.go) 为每个组保存当前节点、容差与选点缓存。AI 日本池与普通 CF 日本池即使候选相同，也有各自的选点状态；保留独立池，共享 provider 的同 URL 探测。
- [`registerHealthCheckTask()`](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/provider/healthcheck.go) 合并同 URL 的筛选范围；[`ParseProxyGroup()`](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/outboundgroup/parser.go) 注册时只传入 `filter`，不传 `exclude-filter`。退出自动候选不代表停止 provider 探测。检查每个 provider 最多并发 10 个请求，节点多或超时集中时应先测量一轮检查耗时，再调整周期。
- `url-test` 与 `fallback` 的 `SupportUDP()` 只检查当前节点，配置不提供按节点 UDP 声明自动筛池的字段；`exclude-type` 也不能代替 UDP 能力检查。保持订阅原始 UDP 声明，不强制覆盖。
- [规则匹配阶段的 DNS 查询](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/tunnel/tunnel.go) 与 DIRECT 出口解析是不同阶段。域名分类优先；未命中域名规则时，业务 IP 兜底允许按需解析，后续规则复用结果，避免等到 `cn_ip` 才解析而错过 Telegram、Google 等业务。该查询仍受默认解析策略影响，`direct-nameserver` 不能提前保证它走国内 DNS。固定直连的 `ifast_domain`、国内 Apple 等规则是业务例外，其优先级按现有使用政策保留。
- [TUN 官方说明](https://wiki.metacubex.one/config/inbound/tun/)中 `auto-redirect` 仅支持 Linux，macOS 设备名需以 `utun` 开头。TUN MTU 与物理链路 MTU 不能直接等同；当前保留 9000，目标设备出现大包或 UDP 问题时再做实测调整。

Tunnel 专用规则限定端点及 TCP/UDP 7844，并保留地址发现所需的真实 IP 解析。普通 CF 204 探针不能证明 Tunnel 的连接注册、UDP 可用性或长连接稳定性。

TCP 手选实际节点时，连接页可显示命中的业务规则，例如 `RuleSet(telegram_domain)`、`RuleSet(telegram_ip)`；选择自动链路后仍可能显示后续 rematch 的 `MATCH` 或 CF/GitHub 分类规则。UDP 公共入口仍可能显示 `SubRules`。顶层入口计数不等于业务计数，排查时应结合目标域名及实际出口链。

## OpenClash Smart 规避设置

配置与验收以官方 Mihomo 为主，不加入 Smart 专属字段或定制内核。TCP 入口已避免所有业务共用外层 `SubRules [(NETWORK,tcp)]` 目标，但 CF/GitHub 的后续 rematch 仍会合并目标；业务 select 独立不代表底层 Smart 状态独立。

在 `alpha-smart-g4bc3d49` 上，本地回环测试已复现：ASN、LightGBM 都关闭时，共用 CF/GitHub 目标的另一业务改选节点并新建连接，仍可能触发旧连接关闭；AI 组内也有同类现象。原因涉及 Smart 的 [`closeSameConnection()`](https://github.com/vernesong/mihomo/blob/4bc3d49/adapter/outboundgroup/smart.go)。保持原有组类型后，同内核、两份配置的这些用例均保留旧连接。测试使用本地代理和手动换点，未覆盖路由器实网；单关 ASN、LightGBM 不能作为问题已规避的依据。

此套配置的规避方式是使用原有 `url-test`/`fallback`，不让 OpenClash 将它们转换成 Smart。原有探针、机场/地区回退与业务手选继续生效；路由器可以保留现有 Smart 二进制，但此配置不启用 Smart 分组。

1. 在 OpenClash 中用本仓库的新模板更新原始配置，并迁移自己的订阅等设置；不要把已被覆写成 Smart 的运行配置当作原始模板。
2. 关闭 Smart 自动转换。当前上游[启动脚本](https://github.com/vernesong/OpenClash/blob/master/luci-app-openclash/root/etc/init.d/openclash)读取的选项为 `auto_smart_switch`；[覆写脚本](https://github.com/vernesong/OpenClash/blob/master/luci-app-openclash/root/usr/share/openclash/yml_rules_change.sh)会把 `url-test`、`load-balance` 改成 `smart`。在路由器上可执行下列命令，重启会中断当时的连接。

   ```sh
   uci set openclash.config.auto_smart_switch='0'
   uci commit openclash
   /etc/init.d/openclash restart
   ```

3. 切回规则模式，用下面的只读检查核验实际运行状态。出现任何 Smart 组时，检查原始配置及自定义覆写后重新加载；仅更改开关不会把已有的 `type: smart` 自动还原。

```sh
# 在能访问控制器的电脑运行；将地址改为实际路由器地址。
# 控制器启用密钥时，先设置 MIHOMO_SECRET 环境变量。
python3 scripts/check-proxy-route.py check-smart --controller http://192.168.1.1:9090
```

检查仅在**规则模式且 Smart 组为零**时返回成功；鉴权失败、控制器不可达不会被当作通过。它不修改配置或选择，也不证明线路自身稳定。需要持续连接稳定时仍应手选经过实际业务验证的节点，Google 204 健康不代表 Telegram 通话或 MTProto 长连接正常。

## 通过实际规则路径测速

官方 v1.19.30 与上述 Smart 版本都存在 rematch 直接测速限制：面板对 rematch 或当前选择它的业务组调用 `/proxies/<name>/delay` 时，可能报 503，但真实流量可用。[`URLTest()`](https://github.com/MetaCubeX/mihomo/blob/v1.19.30/adapter/adapter.go) 直接调用出口拨号，无法替代 rematch 所需的规则匹配。实际节点与可直接拨号的自动池仍可使用面板测速。

使用 Python 3 和 curl，通过混合/HTTP 代理端口测试目标 URL，即可覆盖当前业务选择及其 rematch 路径。先将客户端设为规则模式，使用应用实际涉及的域名；切换业务组或节点后重跑，比较结果。

```sh
python3 scripts/check-proxy-route.py probe --proxy http://127.0.0.1:7890 \
  https://telegram.org/ https://github.com/ https://unpkg.com/

# 精确检查 204，并保存逐次结果；路由场景将 proxy 地址改为实际路由器地址。
python3 scripts/check-proxy-route.py probe --proxy http://127.0.0.1:7890 \
  --expect 204 --count 5 --json https://www.gstatic.com/generate_204
```

每个 URL 默认请求 3 次，单次上限 15 秒，输出 HTTP 状态、首字节及总耗时；默认接受 200–399，不跟随重定向。返回码 0 表示全部通过，1 表示存在探测失败或规避条件不满足，2 表示工具/参数/控制器错误。`--json` 额外记录 curl 返回码、字节数和连接/TLS 时间；这些是从请求开始计算的时间点，其中 `connect_s` 只表示连接到代理入口，不代表节点延迟。

工具不调用 `/delay`、不切换分组、也不清除连接；在规则模式下，固定直连目标仍会按配置直连。它测量 HTTP/TCP 可达性与响应时间，不测带宽、UDP、解锁或 MTProto；Telegram 网页成功不能证明客户端长连接正常。短时网络波动仍需结合客户端表现和连接日志判断。

## 维护与验证

- 手工直连、代理补充分别维护在 `scripts/data/direct.list`、`scripts/data/proxy.list`；修改后运行 `bash scripts/build/direct.sh`、`bash scripts/build/proxy.sh`，同步发布列表及 YAML/MRS。
- `rules/`：发布的规则产物；`scripts/`：构建和验证脚本；`icon/`：图标资源。
- `.github/workflows/main.yml`：每日同步上游规则并构建验证，使用最新稳定版及固定 v1.19.30 内核检查；两者相同时只执行一轮。发布前运行完整回退、节点筛选、UDP、DNS 和真实规则分流测试。
- `docs/`：本地临时研究笔记，不纳入 Git，也不是使用或构建依赖。正式用法以本 README 和配置为准。

修改配置后，可先运行静态检查（需 Python 3、Ruby）：

```sh
python3 scripts/test-config-design.py --static
python3 scripts/test-config-design.py --static --config cinfigfull_new_4.yaml
```

运行时测试需 Mihomo，按改动选择对应脚本：

| `scripts/` 下的脚本 | 验证内容 |
| --- | --- |
| `test-real-rule-routing.py` | 真实规则的业务归属、Fake-IP/DNS 后的业务 IP 兜底、TCP 业务规则信息、手选隔离、默认出口及 Tunnel TCP 边界；`--rules-dir` 指定完整规则快照，`--prepare-rules` 可新建快照 |
| `test-config-design.py` | 结构约束、探针隔离、地区及机场回退、AI 边界、下载与规则更新选路、实际规则测速工具 |
| `test-rematch-udp.py` | UDP 转发与拒绝、共享手选、全局切换及 Tunnel UDP 边界 |
| `test-node-filters.py` | 节点准入、家宽筛选与订阅 UDP 声明 |
| `test-dns-policy.py` | 国内／海外、私有域、STUN 与 Tunnel 的 DNS 策略 |

完整规则产物校验运行 `ruby scripts/validate-rules.rb`。两份配置均需验证，参数见各脚本或 CI；`proxy-fixture.py` 是共享工具。

真实规则快照只需建立一次，两份配置及两个内核版本复用同一份快照。例如：

```sh
python3 scripts/test-real-rule-routing.py --prepare-rules --rules-dir /tmp/rules-snapshot
python3 scripts/test-real-rule-routing.py --rules-dir /tmp/rules-snapshot --config cinfigfull_new_4.yaml
```

新建时目录必须尚不存在；本仓库的规则使用当前工作区 `rules/` 产物，其他规则通过 curl 从配置 URL 下载。全部准备成功后才写入清单，测试再核对 URL、SHA256 和内核加载结果。此流程无需真实机场订阅。

新增用例应对应本仓库的具体配置风险；相同机制复用代表场景，内核升级时按需开展专项验收。

## 使用声明与致谢

沿用上游要求：禁止转载或发布至中国大陆平台；使用者应遵守所在地法律法规。本项目仅用于学习研究，不保证规则的完整性、准确性或适用性，请勿用于商业或非法用途，使用风险由使用者承担。

感谢上游项目及 [Mihomo](https://github.com/MetaCubeX/mihomo)、[OpenClash](https://github.com/vernesong/OpenClash)、[ACL4SSR](https://github.com/ACL4SSR/ACL4SSR)、[Custom_OpenClash_Rules](https://github.com/Aethersailor/Custom_OpenClash_Rules)、[blackmatrix7](https://github.com/blackmatrix7/ios_rule_script)、[meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat)、[SSTap-Rule](https://github.com/FQrabbit/SSTap-Rule) 等配置、规则和工具来源。各资源的许可与署名要求以上游为准。
