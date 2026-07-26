#!/usr/bin/env bash
set -euo pipefail
echo "=== Building applefirmware ==="

# Fetch AppleFirmware Rules
mkdir -p rules/Domain  # 确保目录存在

# 下载 AppleFirmware 规则文件
curl -sL "https://raw.githubusercontent.com/LM-Firefly/Rules/refs/heads/master/Apple/AppleFirmware.list" -o rules/Domain/applefirmware.list

# Extract DOMAIN and DOMAIN-SUFFIX rules from applefirmware.list
# 提取 DOMAIN 和 DOMAIN-SUFFIX 规则，并处理成需要的格式
grep -E 'DOMAIN-SUFFIX|DOMAIN' rules/Domain/applefirmware.list | sed -E 's/DOMAIN-SUFFIX,/*./g; s/DOMAIN,//g' > rules/Domain/applefirmware-domain.list

# Convert AppleFirmware Rules to YAML
echo "payload:" > rules/Domain/applefirmware.yaml
sort -u rules/Domain/applefirmware-domain.list | awk '{print "  - \047" $0 "\047"}' >> rules/Domain/applefirmware.yaml

# Convert AppleFirmware Rules to MRS
# 使用 mihomo 转换为 MRS 格式
mihomo convert-ruleset domain yaml rules/Domain/applefirmware.yaml rules/Domain/applefirmware.mrs
rm -f rules/Domain/applefirmware-domain.list rules/Domain/applefirmware.list

