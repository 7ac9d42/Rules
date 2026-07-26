#!/usr/bin/env bash
set -euo pipefail
echo "=== Building appletv ==="

# Fetch AppleTV Rules
mkdir -p rules/Domain  # 确保目录存在

# 下载 AppleTV 规则文件
curl --fail --show-error --silent --location "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/refs/heads/master/rule/Clash/AppleTV/AppleTV.list" -o rules/Domain/appletv.list

# Extract DOMAIN and DOMAIN-SUFFIX rules from appletv.list
# 提取 DOMAIN 和 DOMAIN-SUFFIX 规则，并过滤掉以 # 开头的注释行
grep -E '^(DOMAIN-SUFFIX|DOMAIN),' rules/Domain/appletv.list | sed -E 's/DOMAIN-SUFFIX,/+./g; s/DOMAIN,//g' > rules/Domain/appletv-domain.list

# Convert AppleTV Rules to YAML
echo "payload:" > rules/Domain/appletv.yaml
sort -u rules/Domain/appletv-domain.list | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/appletv.yaml

# Convert AppleTV Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/appletv.yaml rules/Domain/appletv.mrs
rm -f rules/Domain/appletv-domain.list rules/Domain/appletv.list

