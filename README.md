# Rules

基于 [Lanlan13-14/Rules](https://github.com/Lanlan13-14/Rules) 的自用分支，维护 Mihomo 配置与分流规则。不接受需求类 issue，欢迎问题反馈和讨论。

## 配置

| 文件 | 用途 |
|---|---|
| [configfull_new.yaml](configfull_new.yaml) | 三机场主配置：机场名称1、3、4 |
| [cinfigfull_new_4.yaml](cinfigfull_new_4.yaml) | 四机场独立模板：增加机场名称2家宽 |

每次加载一份完整配置，无需拼接。模板使用官方 Mihomo 的 `rematch`，固定验收版本为 **v1.19.31**，CI 同时检查最新稳定版。使用前填写订阅，核对节点过滤条件，并调整监听地址、控制器密钥、DNS 和 TUN 参数。首次订阅需能直连获取。

升级时以新模板迁移个人设置。保存的手选优先于新默认顺序：Microsoft、Telegram、境外通信和通用代理若仍保存旧默认，应改选 `机场名称1优先-自动`；Kryptex 应选 `机场名称3优先-自动`。旧分组或节点改名后需要重选。

## 分流与出口

规则确定业务分组，业务组保存独立选择，自动链路再使用通用、Cloudflare 或 GitHub 探针选点。

| 默认政策 | 三机场顺序 | 四机场顺序 |
|---|---|---|
| AI | 机场名称1日本自动池 | 同左 |
| 高要求 | 1 → 3 → 4 | 2 → 1 → 3 → 4 |
| 普通 | 1 → 3 → 4 | 1 → 2 → 3 → 4 |
| 成本优先 | 3 → 1 → 4 | 3 → 1 → 2 → 4 |

- Microsoft（含 OneDrive）、Telegram、境外通信和通用代理采用普通政策。开发下载（含 GitHub、Docker、HuggingFace）、游戏平台、Kryptex、纯下载、境外影音和测速采用成本优先；Emby 使用低倍率手选入口。
- 自动链路先换同机场地区，再跨机场。普通机场名称1按日本 → 香港 → 新加坡 → 美国；普通机场名称3按日本 → 新加坡 → 香港 → 美国。纯下载各机场按日本 → 新加坡 → 美国 → 香港，机场名称4另保留其他地区兜底。
- AI 默认只在机场名称1日本池内选点。金融及需要独立选路的媒体服务保留独立业务组；哔哩东南亚默认新加坡，TVB 按实际平台手选地区。
- Pixiv 的 `pixiv.net`、`pximg.net` 归入境外社媒，默认机场名称1优先。Telegram 的域名和 IP 共用独立业务组，与境外通信的选择互不影响。
- 明确国内直连规则优先。Apple、哔哩哔哩和 Cloudflare Tunnel 默认直连，保留手选入口；业务手选不覆盖更早的固定直连规则。Tunnel 专用规则限定端点及 TCP/UDP 7844，并保留真实 IP 解析。
- `自建/家宽节点` 是共享手选入口，换点影响所有选用它的业务。它只认明确的自建、家宽或独立英文标签，不以运营商名称判断；四机场版为机场名称2统一追加 ` [家宽]`，使用前应确认订阅性质，修改前缀时保留此后缀。
- 地区码支持 `HK01`、`JP01` 等编号。机场名称3日新自动池排除独立 `CTCU` 标签，保留 `CTCUCM`；各池保留自身倍率筛选，被排除的自动候选仍可手选。

TCP、UDP 共用业务规则表。UDP 命中首个业务后，所选出口不支持 UDP 就拒绝，不继续匹配后续业务；自动池不会按 UDP 能力另选节点，需保留订阅原始能力声明并手选支持 UDP 的节点。

所有机场每 60 秒持续探测，上层回退每 30 秒按需检查。探针只验证可达性和延迟，不代表带宽、媒体解锁或整页资源可用，也不承诺恢复时限。同机场同地区仍可能换 IP；固定出口需求应手选实际节点。空池使用 REJECT，有候选但全部探测失败时核心仍可能尝试首节点。

切换出口通常只影响新连接。临时统一出口可切换全局模式并在 `GLOBAL` 选实际节点，结束后切回规则模式。面板直接测 rematch 延迟可能失败，应通过实际代理入口访问目标站点，并结合连接日志确认出口。

## OpenClash

使用原始模板，关闭 Smart 自动转换，保持 `url-test`/`fallback` 组类型并使用规则模式。仅关闭 ASN、LightGBM 不能替代关闭 Smart 转换；已被覆写成 Smart 的运行配置需从原始模板重新加载。

OpenClash 的对应设置为 `auto_smart_switch=0`。加载后在面板核对实际分组类型；配置以官方 Mihomo 验收，不启用 Smart 专属功能。

## 项目文件

```text
.github/workflows/main.yml   同步、构建、验证和发布
configfull_new.yaml          三机场配置
cinfigfull_new_4.yaml        四机场配置
rules/                      发布规则，保留构建输入及 YAML/MRS 等产物
icon/                       两份配置引用的 29 个图标
sources/Telegram/           Telegram 构建源
scripts/
  build/                    规则构建脚本
  data/                     手工规则源
  canonicalize-domain-rules.awk
  validate-rules.rb         产物、引用和配置静态校验
  proxy-fixture.py          测试共用的本地假代理
  test-*.py                 六类配置回归
README.md
LICENSE
.gitignore
```

历史配置从 Git 查阅。临时诊断脚本、浏览器采集结果和审计笔记不作为项目文件维护。

## 构建与验证

构建依赖 Bash、curl、Git、jq、Node.js 24、Ruby、Python 3 和 Mihomo；Python 测试仅使用标准库，YAML 由 Ruby 解析。CI 每天北京时间 08:00 镜像上游 `rules/`，随后执行全部构建脚本、验证并发布规则。

手工补充维护在 `scripts/data/`；例如修改直连或代理规则后，分别运行 `bash scripts/build/direct.sh`、`bash scripts/build/proxy.sh`。完整构建按顺序执行 `scripts/build/*.sh`，再运行 `ruby scripts/validate-rules.rb`。

| 测试脚本 | 保留的验证职责 |
|---|---|
| `test-config-design.py` | 结构约束、探针隔离、地区及机场回退、AI 边界和下载策略 |
| `test-node-filters.py` | 节点准入、家宽筛选和订阅 UDP 声明 |
| `test-real-rule-routing.py` | 真实规则归属、默认出口、手选隔离、业务 IP 兜底和 Tunnel TCP 边界 |
| `test-rematch-udp.py` | UDP 转发与拒绝、共享手选、全局切换和 Tunnel UDP 边界 |
| `test-dns-policy.py` | 国内外解析、私有域、Fake-IP 过滤和 Tunnel DNS 策略 |
| `test-runtime-lifecycle.py` | 当前配置的重启/重载、订阅更新、选择与 Fake-IP 缓存、规则更新链及离线缓存 |

快速静态检查：

```sh
python3 scripts/test-config-design.py --static
python3 scripts/test-config-design.py --static --config cinfigfull_new_4.yaml
```

运行回归需要本机允许监听回环端口，不使用真实机场订阅。用 `MIHOMO_BIN` 指定内核，`MIHOMO_DESIGN_CONFIG` 或脚本的 `--config` 选择模板；完整调用见 CI。两份配置都要验证，DNS 配置由静态检查保证一致，因此 DNS 运行测试只执行一次。

真实规则测试需先建立快照，再供两份模板及两个内核复用：

```sh
python3 scripts/test-real-rule-routing.py --prepare-rules --rules-dir /tmp/rules-snapshot
python3 scripts/test-real-rule-routing.py --rules-dir /tmp/rules-snapshot --config cinfigfull_new_4.yaml
```

新建快照目录必须尚不存在。本仓库规则读取当前工作区产物，外部规则从配置 URL 下载；测试核对来源、SHA256 和内核加载结果。增加测试应对应具体配置风险，不重复实现内核自身的测试。

## 使用声明与致谢

沿用上游要求：禁止转载或发布至中国大陆平台；使用者应遵守所在地法律法规。本项目仅用于学习研究，不保证规则的完整性、准确性或适用性，请勿用于商业或非法用途，使用风险由使用者承担。

感谢上游项目及 [Mihomo](https://github.com/MetaCubeX/mihomo)、[OpenClash](https://github.com/vernesong/OpenClash)、[ACL4SSR](https://github.com/ACL4SSR/ACL4SSR)、[Custom_OpenClash_Rules](https://github.com/Aethersailor/Custom_OpenClash_Rules)、[blackmatrix7](https://github.com/blackmatrix7/ios_rule_script)、[meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat)、[SSTap-Rule](https://github.com/FQrabbit/SSTap-Rule) 等配置、规则和工具来源。各资源的许可与署名要求以上游为准。
