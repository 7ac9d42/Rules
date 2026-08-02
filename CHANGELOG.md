# 变更记录 / Changelog

## Unreleased（2026-08-02）

本节记录当前待发布版本的破坏性更新，发布时应将其归入对应版本。

### 破坏性更新

- 游戏规则构建现在排除 5 个误分类或范围过宽的上游源：
  `BypassCNandLan`、`BypassCNandLan_someip`、`China-IP-only`、
  `Skip-all-China-IP-mini-and-LAN` 和 `WoW-EU`。对应的 `rules/Game/*`
  YAML/MRS 文件不再发布。
- 游戏规则会丢弃非公网地址、过宽 CIDR 和可疑的聚合地址，并在单个游戏内合并等价 CIDR。部分游戏规则的匹配范围因此收窄。
- `rules/IP/emby-ip.yaml`、`rules/IP/emby-ip.mrs` 及其构建脚本已移除。Emby 现在使用域名规则和 classical 规则。
- Talkatone IP 规则从多个历史网段收窄为当前维护的专用网段 `50.117.27.96/29`。
- Telegram Europe 规则移除旧的 `5.28.192.0/18` 网段。
- 配置中的规则提供者已拆分或重命名：广告规则拆为 core、PCDN、low 和 classical 层；Amazon、Apple、社交媒体、Emby 等 provider 名称及路由顺序也有调整。请不要直接覆盖旧配置，需重新合并本版 `configfull_new.yaml`。

### 迁移建议

- 依赖已删除游戏规则 URL 的用户应迁移到仍保留的具体游戏规则；不应继续引用上述旧文件。
- 依赖 `emby_ip`、`Amazon_ip`、`discord_asn` 或 `wechat_asn` provider 的自定义配置，需要删除这些引用或改用本版域名/规则集。
- 使用旧版广告 provider 名称的自定义配置，应按本版 `rule-providers` 和 `rules` 段重新配置。
