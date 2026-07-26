#!/usr/bin/env bash
set -euo pipefail
echo "=== Building direct ==="

source_file="rules/Domain/direct.list"
if [[ ! -s "$source_file" ]]; then
  echo "Missing direct source: $source_file" >&2
  exit 1
fi

# Extract DOMAIN and DOMAIN-SUFFIX rules from direct.list
# 提取 DOMAIN-SUFFIX 规则并加上 +.
grep -Eo 'DOMAIN-SUFFIX,[^,]+' "$source_file" | sed 's/DOMAIN-SUFFIX,//' | sed 's/^/+./' > rules/Domain/direct-domain.list
# 提取 DOMAIN 规则
grep -Eo 'DOMAIN,[^,]+' "$source_file" | sed 's/DOMAIN,//' >> rules/Domain/direct-domain.list

# Convert Direct Rules to YAML
echo "payload:" > rules/Domain/direct.yaml
sort -u rules/Domain/direct-domain.list | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/direct.yaml

# Convert Direct Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/direct.yaml rules/Domain/direct.mrs
rm -f rules/Domain/direct-domain.list
