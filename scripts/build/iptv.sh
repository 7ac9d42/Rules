#!/usr/bin/env bash
set -euo pipefail
echo "=== Building iptv ==="

# Fetch IPTV Mainland Rules
mkdir -p rules/Domain  # 确保目录存在

# 下载 IPTV Mainland 规则文件
curl -sL "https://raw.githubusercontent.com/Aethersailor/Custom_OpenClash_Rules/refs/heads/main/rule/IPTVMainland_Domain.list" -o rules/Domain/iptv.list

# Extract DOMAIN and DOMAIN-SUFFIX rules from IPTV.list
# 提取 DOMAIN 和 DOMAIN-SUFFIX 规则，并过滤掉以 # 开头的注释行
grep -E '^(DOMAIN-SUFFIX|DOMAIN),' rules/Domain/iptv.list | sed -E 's/DOMAIN-SUFFIX,/*./g; s/DOMAIN,//g' > rules/Domain/iptv-domain.list

# Convert IPTV Mainland Rules to YAML
echo "payload:" > rules/Domain/iptv.yaml
sort -u rules/Domain/iptv-domain.list | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/iptv.yaml

# Convert IPTV Mainland Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/iptv.yaml rules/Domain/iptv.mrs
rm -f rules/Domain/iptv-domain.list rules/Domain/iptv.list

