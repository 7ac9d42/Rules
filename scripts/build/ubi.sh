#!/usr/bin/env bash
set -euo pipefail
echo "=== Building ubi ==="

# Fetch UBI Rules
mkdir -p rules/Domain  # 确保目录存在

# 下载 UBI 规则文件
curl -sL "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/UBI/UBI.list" -o rules/Domain/ubi.list

# Extract DOMAIN and DOMAIN-SUFFIX rules from UBI.list
# 提取 DOMAIN 和 DOMAIN-SUFFIX 规则，并过滤掉以 # 开头的注释行
grep -E '^(DOMAIN-SUFFIX|DOMAIN),' rules/Domain/ubi.list | sed -E 's/DOMAIN-SUFFIX,/*./g; s/DOMAIN,//g' > rules/Domain/ubi-domain.list

# Convert UBI Rules to YAML
echo "payload:" > rules/Domain/ubi.yaml
sort -u rules/Domain/ubi-domain.list | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/ubi.yaml

# Convert UBI Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/ubi.yaml rules/Domain/ubi.mrs
rm -f rules/Domain/ubi-domain.list rules/Domain/ubi.list

