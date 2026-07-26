#!/usr/bin/env bash
set -euo pipefail
echo "=== Building GoogleVPN ==="

source_file="rules/Domain/googleVPN.list"
if [[ ! -s "$source_file" ]]; then
  echo "Missing Google VPN source: $source_file" >&2
  exit 1
fi

# Extract DOMAIN-SUFFIX rules from googleVPN.list
# 提取 googleVPN.list 中的 DOMAIN-SUFFIX 规则，并添加 +.
grep -Eo 'DOMAIN-SUFFIX,[^,]+' "$source_file" |
  sed 's/DOMAIN-SUFFIX,//' |
  awk '{print "+." $0}' > rules/Domain/googleVPN-domain.list

# Convert Google VPN Rules to YAML
echo "payload:" > rules/Domain/googleVPN.yaml
sort -u rules/Domain/googleVPN-domain.list | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/googleVPN.yaml

# Convert Google VPN Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/googleVPN.yaml rules/Domain/googleVPN.mrs

# Clean up the source files
# 删除中间文件，但保留 googleVPN.list 和 googleVPN.yaml
rm -f rules/Domain/googleVPN-domain.list
