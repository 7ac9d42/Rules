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

| 默认政策 | 三机场顺序 | 四机场顺序 |
|---|---|---|
| 最高要求（AI） | 机场名称1日本手选池 | 同左 |
| 高要求 | 1 → 3 → 4 | 2 → 1 → 3 → 4 |
| 普通 | 1 → 3 → 4 | 1 → 2 → 3 → 4 |
| 成本优先 | 3 → 1 → 4 | 3 → 1 → 2 → 4 |

- 自动链路先在同机场换地区，再跨机场。机场名称1按日本 → 香港 → 新加坡 → 美国；机场名称3按日本 → 新加坡 → 香港 → 美国。纯下载使用独立策略。
- 业务可以手选机场优先链、指定地区或实际节点，具体以组内选项为准。地区链仍可跨机场；地区和 IP 稳定是尽力而为，不是固定出口承诺。
- AI 默认不自动换路，但允许主动选择其他机场或节点。金融保持独立；Netflix、DisneyPlus 等需要分别选路的服务也各自保留。
- Google 包含 GoogleVPN、FCM；Microsoft 包含 OneDrive；开发下载包含 GitHub、Docker、HuggingFace；普通境外影音、通信、社媒及游戏平台按各自分组共用选择。
- `自建/家宽节点` 是共享手选入口：修改它会影响所有选择该入口的业务。普通业务之间的独立选择互不影响。
- 临时让流量统一走单个节点：切换客户端到全局模式，再在 `GLOBAL` 选择该节点；结束后切回规则模式。
- 手选结果在核心重启后保留；切换出口通常只影响新连接，已有连接不会自动迁移。

明确国内直连规则优先于普通境外归类。Apple、哔哩哔哩和 Cloudflare Tunnel 默认直连，保留各自的手选入口。

Tunnel 专用规则限定端点及 TCP/UDP 7844，并保留地址发现所需的真实 IP 解析。普通 CF 204 探针不能证明 Tunnel 的连接注册、UDP 可用性或长连接稳定性。

连接页的 `MATCH` 可能是 `rematch` 子规则的最终结果，不代表最初没有命中业务分组；判断主兜底覆盖率应查看顶层规则的命中计数。

## 维护与验证

- 手工直连、代理补充分别维护在 `scripts/data/direct.list`、`scripts/data/proxy.list`；修改后运行 `bash scripts/build/direct.sh`、`bash scripts/build/proxy.sh`，同步发布列表及 YAML/MRS。
- `rules/`：发布的规则产物；`scripts/`：构建和验证脚本；`icon/`：图标资源。
- `.github/workflows/main.yml`：每日同步上游规则并构建验证，使用最新稳定版及固定 v1.19.30 内核检查。
- `docs/`：本地临时研究笔记，不纳入 Git，也不是使用或构建依赖。正式用法以本 README 和配置为准。

修改配置后，可先运行静态检查（需 Python 3、Ruby）：

```sh
python3 scripts/test-config-design.py --static
python3 scripts/test-config-design.py --static --config cinfigfull_new_4.yaml
```

`scripts/proxy-fixture.py` 是共享测试工具，不是测试入口。AI 手选和重启验证使用 `scripts/test-runtime-lifecycle.py`，下载回退验证使用 `scripts/test-config-design.py`。

修改路由或回退行为时，还应运行对应的 `scripts/test-*.py` 专项测试；完整规则校验入口为 `ruby scripts/validate-rules.rb`，需要 Mihomo。具体参数见各脚本的帮助或 CI 调用。

## 使用声明与致谢

沿用上游要求：禁止转载或发布至中国大陆平台；使用者应遵守所在地法律法规。本项目仅用于学习研究，不保证规则的完整性、准确性或适用性，请勿用于商业或非法用途，使用风险由使用者承担。

感谢上游项目及 [Mihomo](https://github.com/MetaCubeX/mihomo)、[OpenClash](https://github.com/vernesong/OpenClash)、[ACL4SSR](https://github.com/ACL4SSR/ACL4SSR)、[Custom_OpenClash_Rules](https://github.com/Aethersailor/Custom_OpenClash_Rules)、[blackmatrix7](https://github.com/blackmatrix7/ios_rule_script)、[meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat)、[SSTap-Rule](https://github.com/FQrabbit/SSTap-Rule) 等配置、规则和工具来源。各资源的许可与署名要求以上游为准。
