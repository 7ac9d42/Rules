# Rules

基于 [Lanlan13-14/Rules](https://github.com/Lanlan13-14/Rules) 的自用分支，维护 Mihomo 配置与分流规则。不接受需求类 issue，欢迎问题反馈和讨论。

## 配置与维护

| 文件 | 用途 |
|---|---|
| [configfull_new.yaml](configfull_new.yaml) | 三机场完整配置：机场名称1、3、4，119 个组 |
| [configfull_new_4.yaml](configfull_new_4.yaml) | 四机场完整配置：增加机场名称2家宽，159 个组 |
| [configfull_new.yaml.bak](configfull_new.yaml.bak) | 本次迁移前的三机场正式配置 |
| [configfull_new_4.yaml.bak](configfull_new_4.yaml.bak) | 本次迁移前的四机场正式配置 |

每次导入一份完整配置，无需拼接。两份正式配置采用同一架构，最低支持官方 **Mihomo v1.19.30**，不依赖 v1.19.31 独有特性。备份仅用于查阅与回退，更早版本从 Git 历史获取。

人工维护源为 [common.yaml](config-source/common.yaml) 和两个模型文件 [three-airports.yaml](config-source/three-airports.yaml)、[four-airports.yaml](config-source/four-airports.yaml)。共同源维护设备设置、机场订阅、地区识别、准入、探针、业务规则和规则集；模型文件只声明启用机场、优先顺序、敏感池目标及业务默认覆盖。模型按顶层字段覆盖共同源，不进行递归合并；`business-defaults` 单独按业务名覆盖默认项。

```sh
ruby scripts/build-config.rb
ruby scripts/build-config.rb --check
```

默认命令离线生成两份正式配置；`--check` 只检查两份产物是否与维护源一致。生成器不修改备份。产物无锚点、别名或 `<<` 合并，代理组的 `proxies`、`use` 使用行内列表并保留顺序。维护源集中定义规则，展开后的行数不是人工维护量。

填写当前模型启用机场的订阅、替换机场名称和调整监听地址、控制器密钥、DNS、TUN 后重新生成，再导入客户端。不要在生成产物中长期维护修改。源中的 `机场名称1`、`机场名称2`、`机场名称3`、`机场名称4` 是完整文本替换目标，不能先改成缩写；provider 键继续保留。首次订阅通过 DIRECT 获取。

## 出口与手选

普通自动路径为：业务 select → 机场优先或固定地区 rematch → 共享目标分类 → 对应探针 fallback → 同机场同地区 url-test。同区池按延迟选点，跨地区链路先换同机场地区，再跨机场；固定地区始终留在选定地区。

| 默认政策 | 三机场 | 四机场 |
|---|---|---|
| AI | 机场名称1日本专用 Google 池 | 机场名称1日本专用 Google 池 |
| 金融、Talkatone | 与 AI 共用专用池 | 机场名称2香港专用 Google 池 |
| Netflix、Disney+、HBO、Prime Video、Spotify、Reddit | 机场名称1 → 3 → 4 | 机场名称2 → 1 → 3 → 4 |
| 普通 | 机场名称1 → 3 → 4 | 机场名称1 → 2 → 3 → 4 |
| 成本优先 | 机场名称3 → 1 → 4 | 机场名称3 → 1 → 2 → 4 |

机场名称1按日本 → 香港 → 新加坡 → 美国；机场名称2按香港 → 日本 → 新加坡 → 美国；机场名称3按日本 → 新加坡 → 香港 → 美国。机场名称4按香港 → 日本 → 新加坡 → 美国 → 台湾 → 欧洲 → 其他排序兜底。

- Microsoft、Google FCM、Telegram、境外通信和通用代理默认机场名称1优先。OneDrive、Google、下载、游戏平台、Kryptex、境外影音和 Speedtest 默认机场名称3优先。哔哩东南亚默认新加坡，台湾限定默认台湾；默认项不限制主动手选。
- `纯下载`、`开发下载` 合并为 `下载`，共用普通准入及地区顺序，不保留 `下载-…` 自动链路。AUR、codeload、Release 保留较早的下载业务优先级；PKGBUILD 中其他源文件按实际目标分流。下载组不出现在其他业务菜单里。
- 普通业务可选各机场优先、五地区的各机场优先、自建家宽、全部节点、DIRECT，以及符合普通准入的原始订阅节点。隐私拦截另有 REJECT、REJECT-DROP；仅 Emby 可选 `低倍率/MITM节点`。
- 只有 AI、金融、Talkatone 可选专用池。三机场有机场名称1日本 Google／CF 两个池；四机场另有机场名称2香港 Google／CF 两个池，三项敏感业务均可手选这四个池。默认 Google，CF 相邻备选；同一专用池的选点状态由选用它的业务共用，并与普通池分开。默认不自动跨探针、地区、机场或直连；仍可主动改选普通政策、其他地区或实际节点。
- `自建/家宽节点` 是共享手选入口，换点影响所有选用它的业务。识别明确自建、家宽或独立英文标签，不以运营商名称判断。机场名称2订阅统一追加 ` [家宽]`，请确认订阅性质，替换机场名称时保留此后缀。
- 大小写不敏感的 `MITM|pornhub` 从所有自动池、普通业务及 GLOBAL 的原始节点列表、自建家宽入口排除。它们仅能从 `全部节点`、`低倍率/MITM节点` 显式手选；这两个入口首项及空池均为 REJECT。低倍率入口限制港日新及既有倍率／标签，其他地区特殊节点可在全部节点中选择。
- GLOBAL 使用 Google 物理回退组和手选入口，其引用链不含 rematch、业务组、专用池或低倍率/MITM 入口；可通过全部节点手选特殊节点。

普通池继续保留倍率、机场名称1香港质量限制、机场名称3日新独立 CTCU 排除（保留 CTCUCM）及美国低倍率例外。自动候选之外的普通节点仍可手选；特殊节点按上述入口选择。成本取舍通过业务默认与机场、地区顺序表达，不承诺实际节省比例或动态评估 IP 信誉。

各业务 select 保存独立选择；直接手选实际节点互不影响，选择共享辅助组则共用它的内部选择。独立自动池不代表独占节点、出口 IP、带宽或健康记录。同机场同地区仍可能换 IP，固定出口需求应手选实际节点。

## 探针与分流边界

| 探针 | URL | 预期状态 | 用途 |
|---|---|---|---|
| Google | `https://www.gstatic.com/generate_204` | 204 | 其余自动目标的通用基准 |
| CF | `https://cp.cloudflare.com/generate_204` | 204 | CF 自有域名、已知 CDN 域名及官方 IP 段 |
| GitHub | `https://github.com/robots.txt` | 200 | GitHub 相关目标与规则更新 |
| TG | `https://flora.web.telegram.org/apiw1` | 501 | 顶层机场优先链路中的 Telegram 域名/IP |

分类顺序：作用域内的 Telegram → GitHub 主站/API/Raw/codeload/Release 明确域名 → CF 域名/CDN/IP → 其余 GitHub → Google。GitBook 保留下载业务，但不强行归类 GitHub；明确 GitHub 服务优先于 CF 地址。CF 官方 IPv4/IPv6 文本规则每天更新，由 `机场名称1优先-CF` 获取；未知域名的 IP 分类可能需要解析真实地址。配置的 IPv6 默认关闭。

TG 只覆盖三机场的两种、四机场的三种顶层机场优先。两模型分别有 11、16 个 TG 隐藏组，测速叶子与上层回退均使用同一 URL、预期 501。固定地区选项继续使用 Google／CF／GitHub 分类；GLOBAL 及敏感专用池保持原探针。TG 作用域从模型的 `priority-order` 自动推导，不另维护一份策略名单。

501 是 DC5 HTTPS 端点对 HEAD 的实测响应，不是官方健康 API 的长期状态码承诺。它近似反映该端点响应，不能证明其他 DC、实际 TCP 目标、MTProto 业务或媒体访问正常。非 501、超时和 TLS 失败均不符合预期，不自动换成 Google／CF。Google、CF、GitHub 同样只验证单个 URL，不代表敏感业务登录、风控、整页资源、解锁或带宽。

全部超时为 5000ms，延迟容差 50ms；provider 每 60 秒持续检查，上层 fallback 每 30 秒按需检查。相同 provider、URL 的额外候选取并集并去重，状态码须一致；组数不等于探测请求数。自动池使用完整正向 `filter`，保证额外探针遵守准入。低倍率入口的 `filter-regions` 复用地区识别，`filter-tags` 保留倍率和标签；这些维护字段不写入内核配置。

内核使用 HEAD 并校验状态码，不检查正文、不跟随重定向。测速 API 在状态码不符时仍可能返回延迟，选路依据对应 URL 的 `extra[url].alive`；`max-failed-times: 3` 是连接失败触发复测的阈值，容差不是失败防抖。空池使用 REJECT；有候选但全部探测失败时内核仍可能尝试首节点，不等同于空池拒绝。

TCP、UDP 共用业务规则。UDP 命中首个业务后，所选出口不支持 UDP 就拒绝，不继续匹配其他业务，也不会按 UDP 能力另选节点；需保留订阅能力声明并手选支持 UDP 的节点。FCM 先匹配既有域名集，缺失时仅用 TCP 5228–5230 与 Google IP／AS24424 的交集补足；Google 443、UDP、非 Google 地址不会只因端口进入 FCM。

OneDrive、Telegram 保留独立业务选择；Pixiv 归入境外社媒。国内明确直连规则优先，业务手选不覆盖更早的固定直连规则。Apple、哔哩哔哩、Cloudflare Tunnel 默认直连并保留手选；Tunnel 专用规则限制既定端点及 TCP/UDP 7844，保留真实 IP 解析。

## 迁移与设备使用

旧正式配置已原样保存在两份 `.bak`；新文件接替原配置名。旧 `纯下载`／`开发下载` 选择不会自动迁移到 `下载`，旧普通日本池名称也已从敏感业务菜单移除。失效选择回到业务首项；仍有效的普通节点选择继续保留，新默认不覆盖有效缓存选择。迁移后核对自己的业务选择；Emby 和全部节点首次需要主动手选。

名称不变的 `规则更新` 若固定过已移除的子组，应在面板解除固定选择，或使用控制器 `DELETE /proxies/{URL编码组名}` 恢复自动。订阅移除节点也不是即时撤销：v1.19.30 的 url-test 有 10 秒选点缓存，空池可能短暂保留旧节点，再收敛到 REJECT。上层 fallback 根据子组对应 URL 的健康记录切换；订阅更新和子组 `now` 的变化不会直接清除该记录，还需复测确认。

切换出口通常只影响新连接。临时统一出口可切换全局模式并在 GLOBAL 手选，结束后切回规则模式。面板直接测 rematch 延迟可能失败，应通过实际代理入口访问目标，并结合连接日志确认出口。

OpenClash 使用原始模板并关闭 Smart 自动转换，设置 `auto_smart_switch=0`；保持 url-test／fallback 类型和规则模式。仅关闭 ASN、LightGBM 不能替代关闭 Smart，已经转换的运行配置应从原始模板重新加载。

两配置均显式使用 `tun.device: tun0` 支持裸核启动；安卓和路由客户端可自行覆写设备名，macOS 裸核使用 `utun` 开头名称。保留 system 栈、MTU 9000 及既有 DNS 策略；客户端可能覆写 TUN、DNS 端口和路由，应核对实际运行配置。手机独立加载需支持这些 Mihomo 字段；仅设置 Wi-Fi HTTP 代理不能承载 Android FCM 推送，独立代理应使用 VPN/TUN 接管。iOS APNs 不归入 FCM。

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

配置检查继续使用独立只读 CI，在正式配置、备份、维护源、回归脚本或相关校验／工作流变化时触发，也可手动运行；单纯更新规则不触发。两份活动配置均执行回归，备份仅基础校验。v1.19.30 执行 full，v1.19.31 复用同一规则快照执行 smoke，不追踪浮动最新版。

| 回归级别 | 覆盖范围 |
|---|---|
| `static` | 两产物生成一致性、四份配置基础加载、活动配置的引用／循环／菜单／专用池隔离；不下载规则 |
| `smoke` | 两模型关键业务及默认出口、四类探针分类及 TG 作用域、UDP、Fake-IP、GLOBAL |
| `full`（默认） | 再验证节点准入、探测范围／去重、故障隔离／恢复、同区测速、DNS、手选重载／重启、订阅移除及空池 |

```sh
python3 scripts/test-config.py --suite static
python3 scripts/test-config.py --suite full --mihomo /path/to/mihomo-v1.19.30 --rules-dir /tmp/config-rules
python3 scripts/test-config.py --suite smoke --mihomo /path/to/mihomo-v1.19.31 --rules-dir /tmp/config-rules
```

`--mihomo` 默认为 `MIHOMO_BIN` 或 PATH 中的 mihomo。不指定 `--rules-dir` 时使用临时快照；指定目录不存在则创建，已存在则核验 URL、SHA256 与工作区规则版本，不静默修补。更换来源后需使用新的快照目录。本仓库规则读取工作区产物，外部规则从配置 URL 下载；失败不退化为模拟规则。

运行回归需允许回环监听。测试使用公开规则与本地模拟代理，不使用真实机场订阅，不验证公网端点、设备 TUN、吞吐、长期推送或媒体解锁；生成和测试不部署到设备。

## 项目文件与实现依据

```text
configfull_new.yaml / configfull_new_4.yaml    可导入的正式配置
configfull_new.yaml.bak / configfull_new_4.yaml.bak  迁移前备份
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
- TG 端点：[Telegram DC 域名与传输](https://core.telegram.org/mtproto/transports#uri-format)、[Web K 的 apiw1 配置](https://github.com/morethanwords/tweb/blob/master/src/lib/mtproto/dcConfigurator.ts)；CF 分类来自 [官方 IPv4](https://www.cloudflare.com/ips-v4)、[IPv6](https://www.cloudflare.com/ips-v6) 列表。
- 推送接管范围：[Google FCM 网络要求](https://firebase.google.com/docs/cloud-messaging/network-configuration)、[Apple APNs 网络要求](https://support.apple.com/en-ca/102266)。

## 使用声明与致谢

沿用上游要求：禁止转载或发布至中国大陆平台；使用者应遵守所在地法律法规。本项目仅用于学习研究，不保证规则完整性、准确性或适用性，请勿用于商业或非法用途，使用风险由使用者承担。

感谢上游项目及 [Mihomo](https://github.com/MetaCubeX/mihomo)、[OpenClash](https://github.com/vernesong/OpenClash)、[ACL4SSR](https://github.com/ACL4SSR/ACL4SSR)、[Custom_OpenClash_Rules](https://github.com/Aethersailor/Custom_OpenClash_Rules)、[blackmatrix7](https://github.com/blackmatrix7/ios_rule_script)、[meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat)、[SSTap-Rule](https://github.com/FQrabbit/SSTap-Rule) 等配置、规则和工具来源。各资源许可与署名要求以上游为准。
