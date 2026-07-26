#!/usr/bin/env bash
set -euo pipefail
echo "=== Building proxy ==="

source_file="rules/Domain/Proxymini.list"
if [[ ! -s "$source_file" ]]; then
  echo "Missing proxy source: $source_file" >&2
  exit 1
fi

# Extract DOMAIN and DOMAIN-SUFFIX rules from proxymini.list
# 提取 DOMAIN 和 DOMAIN-SUFFIX 规则，并过滤掉以 # 开头的注释行
grep -E '^(DOMAIN-SUFFIX|DOMAIN),' "$source_file" |
  sed -E 's/DOMAIN-SUFFIX,/+./g; s/DOMAIN,//g' > rules/Domain/proxymini-domain.list

# Convert Proxymini Rules to YAML
echo "payload:" > rules/Domain/proxy.yaml
sort -u rules/Domain/proxymini-domain.list | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/proxy.yaml

# Convert Proxymini Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/proxy.yaml rules/Domain/proxy.mrs
rm -f rules/Domain/proxymini-domain.list
