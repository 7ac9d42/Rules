# 变更记录 / Changelog

## Unreleased（2026-08-02）

本节记录当前待发布版本的破坏性更新，发布时应将其归入对应版本。

### 功能更新

- KISS 审计删除 `cn_ip` 之后与最终 `MATCH` 同策略的 Cloudflare、GFW 和非中国地理集合：未命中国内安全网的流量仍由 `MATCH,节点选择` 防漏兜底，分流结果不变，同时减少 3 个远程 rule provider 的更新、存储和匹配开销；classical provider 改用单一公共模板，避免三份等价参数漂移。
- 全项目审计后收紧人工代理补充的优先级：`proxy_domain` 不再抢占高置信广告、PCDN、明确国内白名单及 Apple/B 站跨区策略，仅作为 `cn_domain` 之前的窄例外；验证器同时锁定“全球直连”的真实直连出口、direct/proxy 源产物一致性及跨集合冲突，防止每日上游同步静默破坏国内优先语义。
- 重排主配置的分流优先级：广告、自定义覆盖及 Apple/B 站等跨区策略之后，先以 `cn_domain` 保障国内域名直连，再处理常规代理服务；具体服务规则之后新增可解析的 `cn_ip` 安全网，减少国内域名被宽泛代理集合提前截获。
- Mihomo 健康检查改为分层调度：机场 provider 的全量节点刷新从 60 秒放宽到 180 秒，机场内部与主多机场根仍保持 60 秒非 lazy；机场名称3优先、同地区跨机场及规则更新等排序视图改为 lazy，复用主根维护的共享健康状态，减少 VLESS+Reality 的重复握手、流量与设备唤醒，同时保留业务失败强检和黑洞场景的 60 秒级回退兜底。
- 新增 `HuggingFace`、`Docker` 与 `开发下载` 策略组，默认使用共享的“机场名称3 → 机场名称1 → 机场名称4”自动回退链，同时保留其他代理选路。自动链全部不可用时拒绝连接，服务组也不再提供直连或旧的机场名称3直选项，避免 `store-selected` 缓存阻止升级后启用自动回退。Docker 使用独立图标和策略，不再与其他开发下载共用切换状态。
- 开发下载集合补充 JSR，并移除 Deno、npm、PyPA 的明显非下载父域；Python 包体域收窄为 `files.pythonhosted.org`。Kubernetes 与 SourceForge 只保证入口命中，不为动态镜像粗放接管云厂商父域。
- AOSP 下载规则扩展到全部 `googlesource.com`、Repo 启动器所在的 `storage.googleapis.com`，以及 Android SDK/Maven 使用的 `dl.google.com`，修复此前只有 `android.googlesource.com` 明确走机场名称3的缺口。由于 Mihomo 不能按 HTTPS 路径匹配，`storage.googleapis.com` 是有意接受的整域例外。
- Docker Hub 拉取链和官方安装/更新端点采用窄规则；账号、Scout、AI 等 Docker 产品域不纳入。共享机场出口仍可能触发 Docker Hub 的按 IP 拉取限额。
- 补齐已禁用 `Airport_02` 的四机场恢复模板与成套启用说明；恢复时共享服务按“机场名称3 → 机场名称1 → 机场名称2 → 机场名称4”回退并失败关闭，规则更新链则独立保留末位直连以避免启动死锁。

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
