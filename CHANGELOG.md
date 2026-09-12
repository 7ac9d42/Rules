# 变更记录

仅保留发布变化和迁移影响；逐轮分析与试验过程不作为使用说明。

## 2026-09-12

- README 集中说明配置选择、出口控制与验证入口，修正指向上游模板的链接。
- `docs/` 改为本地忽略目录，取消跟踪历史分析；配置不再依赖其中的文档。

## 2026-09-11

- `configfull_new.yaml` 提升为三机场主配置；四机场家宽模板独立为 `cinfigfull_new_4.yaml`，原版保留为 `configfull.bak.yaml`。
- 默认政策、业务手选、探针节点池分离。三机场高要求与普通政策共用选项，保留有独立选路需求的业务；移除重复自动入口和 load-balance。
- AI 默认机场名称1日本手选，Tunnel 默认 DIRECT；两者均允许用户主动覆盖。恢复共享家宽入口及 GLOBAL 单节点全局选择，重启保留有效手选。
- 明确国内直连优先；Tunnel 保留端点 7844 精确分流和地址发现真实 IP 解析。机场名称1地区顺序改为日本 → 香港 → 新加坡 → 美国。
- 恢复两份配置各 32 个可见分组的图标，已有图标改用仓库资源链接。
- 固定内核验收更新为 v1.19.30；旧 v1.19.19 无法解析 rematch。

## 旧配置迁移

- 以新模板迁移订阅、本地设置和手选偏好，不直接拼接旧业务组。GoogleVPN、FCM 归入 Google，OneDrive 归入 Microsoft；GitHub、Docker、HuggingFace 归入开发下载；Telegram 地区组并入境外通信，IP provider 使用 `telegram_ip`。
- `emby_ip`、`Amazon_ip`、`discord_asn`、`wechat_asn` 以及旧广告 provider 引用需按当前 `rule-providers` 和 `rules` 调整；Emby 使用域名与 classical 规则。
- 不再发布游戏源 `BypassCNandLan`、`BypassCNandLan_someip`、`China-IP-only`、`Skip-all-China-IP-mini-and-LAN`、`WoW-EU` 的产物；游戏规则过滤非公网、过宽及可疑网段。旧 URL 应改为仍保留的具体游戏规则。
- Talkatone IP 范围收窄为 `50.117.27.96/29`。旧规则的完整差异可从 Git 历史及原版备份查阅。
