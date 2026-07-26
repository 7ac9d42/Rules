#!/usr/bin/env bash
set -euo pipefail
echo "=== Building wechat ==="

# Fetch WeChat Rules
mkdir -p rules/Domain  # 确保目录存在

# 下载 WeChat 规则文件
curl --fail --show-error --silent --location "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/refs/heads/master/rule/Clash/WeChat/WeChat.list" -o rules/Domain/WeChat.list

# Extract DOMAIN rules from WeChat.list
# 提取 WeChat.list 中的 DOMAIN 和 DOMAIN-SUFFIX 规则，忽略注释行，并处理格式
grep -E '^(DOMAIN-SUFFIX|DOMAIN),' rules/Domain/WeChat.list | grep -v '^#' | sed -E 's/DOMAIN-SUFFIX,/+./g; s/DOMAIN,//g' > rules/Domain/WeChat-domain.list

# Convert WeChat Rules to YAML
echo "payload:" > rules/Domain/WeChat.yaml
sort -u rules/Domain/WeChat-domain.list | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/WeChat.yaml

# Convert WeChat DOMAIN rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/WeChat.yaml rules/Domain/WeChat.mrs

# Clean up the source files
# 删除中间步骤文件，只保留 WeChat.yaml 和 WeChat.mrs
rm -f rules/Domain/WeChat.list rules/Domain/WeChat-domain.list

